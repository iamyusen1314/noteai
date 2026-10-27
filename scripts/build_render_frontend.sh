#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"

if [ "${NOTEAI_PUBLIC_ACCOUNT_ONLY:-0}" = "1" ] && [ "${NOTEAI_PUBLIC_PRODUCT:-0}" != "1" ]; then
  mkdir -p "$DIST_DIR"
  cp "$ROOT_DIR/public/index.html" "$ROOT_DIR/public/site.css" "$ROOT_DIR/public/site.js" "$DIST_DIR/"
  echo "Public website bundle ready: $DIST_DIR (publish only index.html, site.css, site.js)"
  exit 0
fi

if [ -z "${NOTEAI_PUBLIC_API_BASE:-}" ]; then
  echo "NOTEAI_PUBLIC_API_BASE is required for the Render static-site build" >&2
  exit 1
fi

mkdir -p "$DIST_DIR"
cp "$ROOT_DIR/NoteAI_Pro_Demo_Framer.html" "$DIST_DIR/index.html"
cp "$ROOT_DIR/wechat-pay.html" "$DIST_DIR/wechat-pay.html"
mkdir -p "$DIST_DIR/assets"
cp -R "$ROOT_DIR/assets/." "$DIST_DIR/assets/"

NOTEAI_RUNTIME_CONFIG_PATH="$DIST_DIR/runtime-config.js" node -e '
const fs = require("fs");
const value = String(process.env.NOTEAI_PUBLIC_API_BASE || "").replace(/\/$/, "");
fs.writeFileSync(
  process.env.NOTEAI_RUNTIME_CONFIG_PATH,
  `window.NOTEAI_API_BASE = ${JSON.stringify(value)};\nwindow.NOTEAI_PUBLIC_PRODUCT = ${process.env.NOTEAI_PUBLIC_PRODUCT === "1"};\n`,
  "utf8",
);
'

if [ "${NOTEAI_PUBLIC_PRODUCT:-0}" = "1" ]; then
  python3 "$ROOT_DIR/tools/build_public_product_frontend.py" "$DIST_DIR" --version-product-app
fi

echo "Frontend bundle ready: $DIST_DIR"
