#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"

if [ -z "${NOTEAI_PUBLIC_API_BASE:-}" ]; then
  echo "NOTEAI_PUBLIC_API_BASE is required for the Render static-site build" >&2
  exit 1
fi

mkdir -p "$DIST_DIR"
cp "$ROOT_DIR/NoteAI_Pro_Demo_Framer.html" "$DIST_DIR/index.html"
cp -R "$ROOT_DIR/assets" "$DIST_DIR/assets"

NOTEAI_RUNTIME_CONFIG_PATH="$DIST_DIR/runtime-config.js" node -e '
const fs = require("fs");
const value = String(process.env.NOTEAI_PUBLIC_API_BASE || "").replace(/\/$/, "");
fs.writeFileSync(
  process.env.NOTEAI_RUNTIME_CONFIG_PATH,
  `window.NOTEAI_API_BASE = ${JSON.stringify(value)};\n`,
  "utf8",
);
'

echo "Frontend bundle ready: $DIST_DIR"
