"""NoteAI stdin-only boundary for the pinned v5 pure signing algorithms."""
from __future__ import annotations
import hashlib
import base64
import json
import os
import re
from pathlib import Path
import subprocess
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).parent


def note_access_context(raw, note_id):
    """Validate the existing owned link's private context; never create a token."""
    if not raw:
        return {}
    try:
        if not isinstance(raw, str) or len(raw) > 4096:
            raise ValueError()
        if raw.startswith("{"):
            def unique_pairs(pairs):
                if len(dict(pairs)) != len(pairs):
                    raise ValueError()
                return dict(pairs)
            value = json.loads(raw, object_pairs_hook=unique_pairs)
        else:
            url = urlsplit(raw)
            if (url.scheme != "https" or url.hostname != "www.xiaohongshu.com"
                    or url.username or url.password or url.port not in (None, 443)
                    or url.fragment or url.path != "/explore/" + note_id):
                raise ValueError()
            query = parse_qs(url.query, keep_blank_values=True)
            if any(len(query.get(key, [])) != 1 for key in ("xsec_token", "xsec_source")):
                raise ValueError()
            value = {"note_id": note_id, "xsec_token": query["xsec_token"][0],
                     "xsec_source": query["xsec_source"][0]}
        if (not isinstance(value, dict) or set(value) != {"note_id", "xsec_token", "xsec_source"}
                or value["note_id"] != note_id
                or not isinstance(value["xsec_token"], str)
                or not re.fullmatch(r"[A-Za-z0-9_+/=-]{1,512}", value["xsec_token"])
                or not isinstance(value["xsec_source"], str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", value["xsec_source"])):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise RuntimeError("invalid_note_access_context") from None


def session_signing_storage(raw):
    """Validate optional existing PC state without importing any database code."""
    if not raw:
        return {}
    try:
        if not isinstance(raw,str) or len(raw)>4096:
            raise ValueError()
        value=json.loads(raw)
        if (not isinstance(value,dict) or set(value)!={'xhs-pc-web'}
            or not isinstance(value['xhs-pc-web'],str)
            or not 32<=len(base64.b64decode(value['xhs-pc-web'],validate=True))<=1024):
            raise ValueError()
        return {'webSsk':value}
    except (ValueError,TypeError):
        raise RuntimeError('invalid_session_signing_state') from None


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
