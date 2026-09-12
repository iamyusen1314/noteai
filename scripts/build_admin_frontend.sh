#!/usr/bin/env sh
set -eu
ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
DEST_DIR="${1:?Pass an isolated output directory for the original Admin bundle}"
mkdir -p "$DEST_DIR/assets/vendor"
cp "$ROOT_DIR/model/admin.html" "$DEST_DIR/index.html"
cp "$ROOT_DIR/assets/vendor/echarts-5.4.3.min.js" "$DEST_DIR/assets/vendor/"
python3 "$ROOT_DIR/tools/build_public_product_frontend.py" "$DEST_DIR"
