#!/usr/bin/env bash
# Deploy the Couchbase Agent Operations Manager ("agent-ops") and the Couchbase
# Harborline demo ("insurance-app") with Helm onto the single-node K3s cluster on
# mother (Rancher-managed), without a container registry:
#
#   1. builds the 5 images here with Docker, for mother's CPU architecture
#        AOM:   couchbase-aom-operations-manager, couchbase-aom-sample-mcp-servers, couchbase-aom-ui
#        demo:  insurance-backend, insurance-web
#   2. copies them to mother and imports them into K3s's containerd
#      (asks for your sudo password on mother once)
#   3. copies both charts to mother and runs `helm upgrade --install` there
#      (installs helm into ~/.local/bin on mother if it's missing)
#
# Usage, from this repository on your Mac:
#   AOM_ADMIN_PASSWORD='<12+ chars>' ./deploy/k8s/deploy.sh
# Or on mother itself, straight from the public GitHub repo (no Mac involved):
#   deploy/k8s/deploy-on-mother.sh   (pulls the repo, then runs this script with MOTHER=local)
#
# mother already runs AOM (agent-ops) and the Royal Caribbean and Princess demos. To add
# this demo next to them, deploy only it, with the current AOM admin password:
#   AOM_ADMIN_PASSWORD='<current AOM password>' ONLY=insurance ./deploy/k8s/deploy.sh
#
# Environment:
#   MOTHER              ssh target              (default ehind@192.168.111.4; "local" = run on the node itself)
#   AOM_DIR             AOM repository checkout (default ~/github-couchbaselabs/couchbase-agent-operations-manager)
#   AOM_ADMIN_PASSWORD  AOM dashboard admin password. On a fresh AOM the demo backend sets it as the
#                       first-login password; on an existing AOM it must be the current one. Prompted if unset.
#   ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY   optional LLM keys for AOM (else labelled stubs)
#   ONLY                "aom" or "insurance" to deploy just one of them
#   VALUES_FILE         per-node chart values (default deploy/k8s/values-mother.yaml; deploy/k8s/values-hal.yaml for hal)
#   SKIP_BUILD=1        reuse the images already on mother (set TAG to the tag to deploy)
#   FORCE_DUMP=true     re-export today's partition on start (after a catalog change,
#                       e.g. new products or groups) - the backend reloads it automatically
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
ROOT=$(pwd)

MOTHER="${MOTHER:-ehind@192.168.111.4}"
AOM_DIR="${AOM_DIR:-$HOME/github-couchbaselabs/couchbase-agent-operations-manager}"
TAG="${TAG:-$(date +%Y%m%d-%H%M%S)}"
ONLY="${ONLY:-}"
VALUES_FILE="${VALUES_FILE:-deploy/k8s/values-mother.yaml}"
AOM_NS=agent-ops
INSURANCE_NS=insurance-app
REMOTE_DIR='~/insurance-deploy'

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
remote() { if [ "$MOTHER" = local ]; then bash -lc "$1"; else ssh "$MOTHER" "bash -lc $(printf '%q' "$1")"; fi; }
remote_tty() { if [ "$MOTHER" = local ]; then bash -lc "$1"; else ssh -t "$MOTHER" "bash -lc $(printf '%q' "$1")"; fi; }

want() { [ -z "$ONLY" ] || [ "$ONLY" = "$1" ]; }

if want aom || want insurance; then :; else echo "ONLY must be aom or insurance"; exit 1; fi
# The checkout may be nested one level down (…/couchbase-agent-operations-manager/couchbase-agent-operations-manager).
if [ ! -d "$AOM_DIR/helm" ] && [ -d "$AOM_DIR/couchbase-agent-operations-manager/helm" ]; then
  AOM_DIR="$AOM_DIR/couchbase-agent-operations-manager"
fi
if want aom && [ ! -d "$AOM_DIR/helm/couchbase-agent-operations-manager" ]; then
  echo "AOM checkout not found at $AOM_DIR (set AOM_DIR)"; exit 1
fi
if want insurance && [ -z "${AOM_ADMIN_PASSWORD:-}" ]; then
  read -r -s -p "AOM admin password (12+ characters): " AOM_ADMIN_PASSWORD; echo
fi

say "Checking mother ($MOTHER)"
ARCH=$(remote 'uname -m')
case "$ARCH" in x86_64|amd64) PLATFORM=linux/amd64 ;; aarch64|arm64) PLATFORM=linux/arm64 ;; *) echo "unsupported arch $ARCH"; exit 1 ;; esac
remote 'kubectl get nodes -o wide' || { echo "kubectl doesn't work on mother"; exit 1; }
echo "Platform $PLATFORM, image tag $TAG"

IMAGES=()
build() { # name context
  say "Building $1:$TAG ($PLATFORM)"
  docker buildx build --platform "$PLATFORM" -t "$1:$TAG" --load "$2"
  IMAGES+=("$1:$TAG")
}

if [ -z "${SKIP_BUILD:-}" ]; then
  if want aom; then
    build couchbase-aom-operations-manager "$AOM_DIR/operations-manager"
    build couchbase-aom-sample-mcp-servers "$AOM_DIR/sample-mcp-servers"
    build couchbase-aom-ui "$AOM_DIR/ui"
  fi
  if want insurance; then
    build insurance-backend "$ROOT/backend"
    build insurance-web "$ROOT/web"
  fi
else
  # SKIP_BUILD: reuse the images Docker already has for $TAG, but still import any
  # that K3s's containerd is missing (the kubelet garbage-collects images under
  # disk pressure, and `crictl rmi --prune` removes the rest).
  want aom && IMAGES+=("couchbase-aom-operations-manager:$TAG" "couchbase-aom-sample-mcp-servers:$TAG" "couchbase-aom-ui:$TAG")
  want insurance && IMAGES+=("insurance-backend:$TAG" "insurance-web:$TAG")
  PRESENT=$(remote 'sudo k3s crictl images -o json 2>/dev/null' | python3 -c 'import json,sys
try: d=json.load(sys.stdin)
except Exception: d={}
print("\n".join(t for i in d.get("images",[]) for t in i.get("repoTags",[])))' 2>/dev/null || true)
  MISSING=()
  for img in "${IMAGES[@]}"; do
    docker image inspect "$img" >/dev/null 2>&1 || { echo "Docker has no image $img - unset SKIP_BUILD or set TAG"; exit 1; }
    grep -qx "docker.io/library/$img" <<<"$PRESENT" || MISSING+=("$img")
  done
  IMAGES=("${MISSING[@]}")
  [ ${#IMAGES[@]} -eq 0 ] && echo "All images for tag $TAG are already on mother"
fi
if [ ${#IMAGES[@]} -gt 0 ]; then
  say "Copying ${#IMAGES[@]} images to mother and importing them into K3s"
  if [ "$MOTHER" = local ]; then
    docker save "${IMAGES[@]}" | sudo k3s ctr images import -
  else
    docker save "${IMAGES[@]}" | gzip -1 | ssh "$MOTHER" "cat > /tmp/insurance-images.tar.gz"
    remote_tty 'gunzip -f /tmp/insurance-images.tar.gz && sudo k3s ctr images import /tmp/insurance-images.tar && rm -f /tmp/insurance-images.tar'
  fi
fi

say "Copying the Helm charts to mother"
# Chart copies of the repo's init scripts and export generator.
cp couchbase-init/init.sh sync-gateway/db-config.json datagen/generate_mock_export.py helm/insurance-app/files/
STAGE=$(mktemp -d)
mkdir -p "$STAGE/charts"
cp -R helm/insurance-app "$STAGE/charts/insurance-app"
cp "$VALUES_FILE" "$STAGE/insurance-values.yaml"
want aom && cp -R "$AOM_DIR/helm/couchbase-agent-operations-manager" "$STAGE/charts/agent-ops"
if [ "$MOTHER" = local ]; then
  mkdir -p ~/insurance-deploy && cp -R "$STAGE"/. ~/insurance-deploy/
else
  remote "mkdir -p $REMOTE_DIR"
  tar -C "$STAGE" -czf - . | ssh "$MOTHER" "tar -C $REMOTE_DIR -xzf -"
fi
rm -rf "$STAGE"

# Secrets go into mode-600 values files on mother, never onto a command line.
yaml_str() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"; }
{
  echo "operationsManager:"
  echo "  providerApiKeys:"
  echo "    anthropic: $(yaml_str "${ANTHROPIC_API_KEY:-}")"
  echo "    openai: $(yaml_str "${OPENAI_API_KEY:-}")"
  echo "    gemini: $(yaml_str "${GEMINI_API_KEY:-}")"
} | remote "umask 077; cat > $REMOTE_DIR/aom-secrets.yaml"
if want insurance; then
  printf 'aom:\n  adminPassword: %s\n' "$(yaml_str "$AOM_ADMIN_PASSWORD")" \
    | remote "umask 077; cat > $REMOTE_DIR/insurance-secrets.yaml"
fi

if [ "$MOTHER" = local ]; then NODE_IP=$(hostname -I | awk '{print $1}'); else NODE_IP="${MOTHER#*@}"; fi

say "Installing with Helm on mother"
remote_tty "
set -euo pipefail
cd $REMOTE_DIR
export PATH=\$HOME/.local/bin:\$PATH
if [ ! -f \$HOME/.kube/config ] && [ -z \"\${KUBECONFIG:-}\" ] && [ -r /etc/rancher/k3s/k3s.yaml ]; then export KUBECONFIG=/etc/rancher/k3s/k3s.yaml; fi
if ! command -v helm >/dev/null; then
  echo 'Installing helm into ~/.local/bin ...'
  mkdir -p \$HOME/.local/bin
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | HELM_INSTALL_DIR=\$HOME/.local/bin USE_SUDO=false bash
fi
if [ '$ONLY' != insurance ]; then
  echo '--- agent-ops (Couchbase Agent Operations Manager) ---'
  helm upgrade --install aom charts/agent-ops -n $AOM_NS --create-namespace \
    -f charts/agent-ops/values-k3s.yaml -f aom-secrets.yaml \
    --set operationsManager.image.repository=couchbase-aom-operations-manager --set operationsManager.image.tag=$TAG \
    --set sampleMcpServers.image.repository=couchbase-aom-sample-mcp-servers --set sampleMcpServers.image.tag=$TAG \
    --set ui.image.repository=couchbase-aom-ui --set ui.image.tag=$TAG \
    --timeout 25m
  # No LoadBalancer implementation on this node: publish the dashboard on the node IP.
  kubectl -n $AOM_NS patch svc aom-ui --type merge -p '{\"spec\":{\"externalIPs\":[\"$NODE_IP\"]}}' || true
fi
if [ '$ONLY' != aom ]; then
  echo '--- insurance-app (Couchbase Harborline demo) ---'
  helm upgrade --install insurance-app charts/insurance-app -n $INSURANCE_NS --create-namespace \
    -f insurance-values.yaml -f insurance-secrets.yaml \
    --set backend.image.tag=$TAG --set web.image.tag=$TAG \
    --set nightlyExport.forceExportOnStart=${FORCE_DUMP:-false} \
    --timeout 25m
fi
kubectl get pods,svc -n $AOM_NS 2>/dev/null || true
kubectl get pods,svc -n $INSURANCE_NS 2>/dev/null || true
"

HOST="${MOTHER#*@}"; [ "$MOTHER" = local ] && HOST=$(remote "hostname -I | awk '{print \$1}'")
port() { python3 -c 'import re,sys; t=open(sys.argv[1]).read(); m=re.search(sys.argv[2]+r":\s*\n\s*service:.*?port:\s*(\d+)", t, re.S); print(m.group(1) if m else sys.argv[3])' "$VALUES_FILE" "$1" "$2"; }
WEB_PORT=$(port web 5156); API_PORT=$(port backend 8204); SG_PORT=$(port syncGateway 4990)
say "Done"
cat <<MSG
  AOM dashboard:        https://$HOST:3111   (admin / your AOM admin password)
  Harborline app:          https://$HOST:$WEB_PORT   (the story: https://$HOST:$WEB_PORT/story)
                        (sign in: demo / Couchbase123! unless web.auth is overridden; self-signed certificate)
  Backend status:       http://$HOST:$API_PORT/api/status   (aom.registration should reach "registered")
  Couchbase Lite:       ws://$HOST:$SG_PORT/insurance

First start takes several minutes (Couchbase init, the 100 MiB export, KB publishing). Watch with:
  ssh $MOTHER kubectl -n $INSURANCE_NS logs deploy/backend -f
MSG
