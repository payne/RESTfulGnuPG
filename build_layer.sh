#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# build_layer.sh
#
# Builds a Lambda Layer zip containing:
#   - /opt/bin/gpg2           (statically linked GnuPG 2.4.x for AL2023/arm64)
#   - /opt/python/gnupg.py    (python-gnupg wheel)
#
# Run on an arm64 Amazon Linux 2023 host, or use the Docker approach below.
#
# Usage:
#   ./scripts/build_layer.sh            # uses Docker (recommended)
#   ./scripts/build_layer.sh --no-docker  # runs natively (must be AL2023 arm64)
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LAYER_DIR="$ROOT_DIR/layer"
LAYER_ZIP="$LAYER_DIR/gnupg-layer.zip"
BUILD_DIR="$(mktemp -d)"

PYTHON_GNUPG_VERSION="0.5.2"
# GnuPG 2.4.x is available in the AL2023 package repos
GPG_PACKAGES="gnupg2 pinentry-tty"

cleanup() { rm -rf "$BUILD_DIR"; }
trap cleanup EXIT

echo "==> Build directory: $BUILD_DIR"
mkdir -p "$BUILD_DIR/opt/bin" "$BUILD_DIR/opt/python"

use_docker=true
if [[ "${1:-}" == "--no-docker" ]]; then
  use_docker=false
fi

if $use_docker; then
  echo "==> Building inside Docker (public.ecr.aws/lambda/python:3.12-arm64)"

  docker run --rm \
    --platform linux/arm64 \
    -v "$BUILD_DIR:/build" \
    public.ecr.aws/lambda/python:3.12-arm64 \
    /bin/bash -c "
      set -euo pipefail
      # Install GnuPG from AL2023 repo
      dnf install -y ${GPG_PACKAGES} 2>/dev/null || yum install -y ${GPG_PACKAGES}

      # Copy gpg binary and required shared libs
      cp \$(which gpg2 || which gpg) /build/opt/bin/gpg
      cp \$(which gpgconf)           /build/opt/bin/gpgconf  2>/dev/null || true
      cp \$(which gpg-agent)         /build/opt/bin/gpg-agent 2>/dev/null || true
      cp \$(which pinentry-tty)      /build/opt/bin/pinentry-tty 2>/dev/null || true

      # Bundle required shared libraries not present in Lambda base
      mkdir -p /build/opt/lib
      for bin in /build/opt/bin/*; do
        ldd \$bin 2>/dev/null | awk '/=> \// { print \$3 }' | while read lib; do
          [ -f \"\$lib\" ] && cp -n \"\$lib\" /build/opt/lib/ || true
        done
      done

      # Install python-gnupg
      pip install python-gnupg==${PYTHON_GNUPG_VERSION} -t /build/opt/python --no-deps -q

      # Permissions
      chmod +x /build/opt/bin/*
    "
else
  echo "==> Native build (must run on Amazon Linux 2023 arm64)"
  dnf install -y $GPG_PACKAGES || yum install -y $GPG_PACKAGES
  cp "$(which gpg2 || which gpg)" "$BUILD_DIR/opt/bin/gpg"
  pip install "python-gnupg==${PYTHON_GNUPG_VERSION}" -t "$BUILD_DIR/opt/python" --no-deps -q
fi

echo "==> Packaging layer zip → $LAYER_ZIP"
mkdir -p "$LAYER_DIR"
(cd "$BUILD_DIR" && zip -r9 "$LAYER_ZIP" opt/)

echo "==> Done. Layer zip: $LAYER_ZIP ($(du -sh "$LAYER_ZIP" | cut -f1))"
echo ""
echo "Deploy with:"
echo "  sam deploy --template-file infra/template.yaml \\"
echo "             --stack-name gnupg-lambda-dev \\"
echo "             --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \\"
echo "             --parameter-overrides Environment=dev"
