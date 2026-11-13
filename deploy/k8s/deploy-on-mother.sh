#!/usr/bin/env bash
# Deploy the Couchbase Harborline demo ON the K3s node itself (mother, hal, ...), straight from the public
# GitHub repository - no Mac, no image copy over ssh. Pulls (or clones) the
# repo into ~/insurance-deploy/src, builds the two demo images there with Docker,
# imports them into K3s and runs the Helm install, i.e. deploy.sh with
# MOTHER=local.
#
# First time, on mother:
#   curl -fsSL https://raw.githubusercontent.com/Couchbase-Field-Engineering/couchbase-insurance-mobile-ai-personalization-demo/main/deploy/k8s/deploy-on-mother.sh \
#     | AOM_ADMIN_PASSWORD='<AOM admin password>' bash
# After that (the checkout is kept):
#   AOM_ADMIN_PASSWORD='<AOM admin password>' ~/insurance-deploy/src/deploy/k8s/deploy-on-mother.sh
#
# Environment (all optional except the password):
#   AOM_ADMIN_PASSWORD  the in-cluster AOM's admin password (https://192.168.111.4:3111); prompted if unset
#   BRANCH              branch or tag to deploy (default main)
#   ONLY                insurance (default) | aom | all - "aom" and "all" also pull
#                       couchbaselabs/couchbase-agent-operations-manager and deploy the AOM chart
#   FORCE_DUMP=true     re-export today's partition on start (after a catalog change)
#   SKIP_BUILD=1 TAG=.. reuse images already imported into K3s
#   SRC                 where the checkout lives (default ~/insurance-deploy/src)
#   VALUES_FILE         per-node chart values; defaults to deploy/k8s/values-<hostname>.yaml when that
#                       file exists (values-mother.yaml on mother, values-hal.yaml on hal), else mother's
#
# Needs on mother: git, docker (with buildx) for the builds, sudo for `k3s ctr images import`,
# kubectl (K3s) and helm (installed into ~/.local/bin by deploy.sh if missing).
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Couchbase-Field-Engineering/couchbase-insurance-mobile-ai-personalization-demo.git}"
AOM_REPO_URL="${AOM_REPO_URL:-https://github.com/couchbaselabs/couchbase-agent-operations-manager.git}"
BRANCH="${BRANCH:-main}"
AOM_BRANCH="${AOM_BRANCH:-main}"
SRC="${SRC:-$HOME/insurance-deploy/src}"
AOM_SRC="${AOM_SRC:-$HOME/insurance-deploy/aom-src}"
ONLY="${ONLY:-insurance}"

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1 - $2"; exit 1; }; }

need git "sudo apt-get install -y git"
if [ -z "${SKIP_BUILD:-}" ]; then
  need docker "install Docker Engine (https://docs.docker.com/engine/install/ubuntu/) and add yourself to the docker group"
  docker buildx version >/dev/null 2>&1 || { echo "docker buildx is missing: sudo apt-get install -y docker-buildx-plugin"; exit 1; }
fi
need kubectl "this should be the K3s node"

sync_repo() { # url branch dir
  local url="$1" branch="$2" dir="$3"
  if [ -d "$dir/.git" ]; then
    say "Updating $dir ($branch)"
    git -C "$dir" fetch --depth 1 origin "$branch"
    # The checkout on mother is deploy-only: no local edits to preserve.
    git -C "$dir" checkout -q -B "$branch" FETCH_HEAD
  else
    say "Cloning $url ($branch) into $dir"
    mkdir -p "$(dirname "$dir")"
    git clone --depth 1 --branch "$branch" "$url" "$dir"
  fi
  echo "  at $(git -C "$dir" log -1 --format='%h %cd %s' --date=short)"
}

sync_repo "$REPO_URL" "$BRANCH" "$SRC"
if [ "$ONLY" != insurance ]; then
  sync_repo "$AOM_REPO_URL" "$AOM_BRANCH" "$AOM_SRC"
fi

if [ "$ONLY" != aom ] && [ -z "${AOM_ADMIN_PASSWORD:-}" ]; then
  read -r -s -p "AOM admin password (the in-cluster AOM, https://$(hostname -I | awk '{print $1}'):3111): " AOM_ADMIN_PASSWORD; echo
  export AOM_ADMIN_PASSWORD
fi

say "Deploying from $SRC"
cd "$SRC"
[ "$ONLY" = all ] && ONLY=""   # deploy.sh: empty ONLY = both charts
if [ -z "${VALUES_FILE:-}" ]; then
  VALUES_FILE="deploy/k8s/values-$(hostname -s).yaml"
  [ -f "$VALUES_FILE" ] || VALUES_FILE="deploy/k8s/values-mother.yaml"
fi
echo "  chart values: $VALUES_FILE"
MOTHER=local AOM_DIR="$AOM_SRC" ONLY="$ONLY" VALUES_FILE="$VALUES_FILE" exec ./deploy/k8s/deploy.sh
