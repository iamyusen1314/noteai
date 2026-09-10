"""NoteAI stdin-only boundary for the pinned v5 pure signing algorithms."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).parent


def verify_assets():
    manifest = json.loads((ROOT / "upstream.json").read_text())
    for name, entry in manifest["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError("signer_asset_integrity_failed")


def invoke(value):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    if len(raw) > 65536:
        raise RuntimeError("signer_input_limit")
    result = subprocess.run(
        ["node", str(ROOT / "bridge.js")], input=raw, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, timeout=10,
        env={"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")},
        cwd=str(ROOT),
    )
    if result.returncode or len(result.stdout) > 65536:
        raise RuntimeError("signer_failed")
    parsed = json.loads(result.stdout)
    if not isinstance(parsed, dict):
        raise RuntimeError("signer_invalid_response")
    return parsed


def generate_b1(options=None):
    value = invoke({"operation": "b1", "options": dict(options or {})}).get("b1")
    if not isinstance(value, str) or len(value) < 500 or len(value) % 4:
        raise RuntimeError("signer_invalid_b1")
    return value


def sign(profile, api, data, dsl):
    context = profile.next_sign_context(api)
    payload = {key: context[key] for key in (
        "tier", "now", "version", "loadts", "seq", "envConst", "envFpTail",
        "webBuild", "signVersion", "appId", "platform",
    )}
    payload.update({"api": api, "data": data, "a1": profile.cookie_map["a1"],
                    "cookie": profile.document_cookie, "b1": profile.current_b1(context["now"]),
                    "dslPair": profile.dsl_pair(dsl, timestamp_ms=context["now"])})
    if "webSsk" in context:
        payload["webSsk"] = context["webSsk"]
    result = invoke({"operation": "sign", "payload": payload})
    required = {"xs", "xt", "xs_common"}
    if api.endswith("/feed"):
        required.add("x_rap_param")
    if set(result) != required or any(not isinstance(v, str) or not v for v in result.values()):
        raise RuntimeError("signer_invalid_response")
    return result, context
