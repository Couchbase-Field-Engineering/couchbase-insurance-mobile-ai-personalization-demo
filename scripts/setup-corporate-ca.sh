#!/usr/bin/env bash
# Exports the root CAs this Mac trusts (TLS-inspecting corporate proxies such as
# Zscaler / Netskope / GlobalProtect) to backend/certs/corporate-ca.crt so
# `docker compose build` can pip-install through the proxy. A no-op placeholder
# is already committed, so you only need this behind such a proxy.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$REPO_ROOT/backend/certs/corporate-ca.crt"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS only. On Linux, copy your proxy's root CA (PEM) to backend/certs/corporate-ca.crt" >&2
  exit 1
fi
mkdir -p "$(dirname "$DEST")"
security find-certificate -a -p /Library/Keychains/System.keychain > "$DEST" 2>/dev/null || true
N=$(grep -c "BEGIN CERTIFICATE" "$DEST" 2>/dev/null || echo 0)
echo "Exported $N certificate(s) to backend/certs/corporate-ca.crt"
