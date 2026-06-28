"""Production model artifact verification and optional download helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen


MODEL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = MODEL_ROOT.parent
DEFAULT_MANIFEST = MODEL_ROOT / "artifacts" / "model_release_manifest.v04.json"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "model":
        return REPO_ROOT / path
    return MODEL_ROOT / path


def _manifest_path(raw_path: str | None) -> Path:
    if not raw_path:
        return DEFAULT_MANIFEST
    path = Path(raw_path)
    if path.is_absolute():
        return path
    candidates = [
        REPO_ROOT / path,
        MODEL_ROOT / path,
        MODEL_ROOT / "artifacts" / path.name,
    ]
    for item in candidates:
        if item.exists():
            return item
    return candidates[0]


def _url_for(base_url: str, raw_path: str) -> str:
    base = base_url.rstrip("/")
    parts = [quote(part) for part in Path(raw_path).parts]
    return f"{base}/{'/'.join(parts)}"


def _download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        with urlopen(url, timeout=60) as response, tmp.open("wb") as fh:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
        tmp.replace(target)
    except (HTTPError, URLError, TimeoutError) as exc:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"download failed for {url}: {exc}") from exc


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_model_artifacts(
    manifest_path: Path | None = None,
    base_url: str | None = None,
    *,
    check_only: bool = False,
    required: bool | None = None,
) -> dict:
    """Verify model artifacts and optionally download missing/mismatched files.

    When NOTEAI_MODEL_ARTIFACT_BASE_URL is unset, this function only verifies
    local files. Set NOTEAI_MODEL_ARTIFACT_REQUIRED=1 in production to fail
    startup if artifacts are missing and no remote source is configured.
    """

    manifest_path = manifest_path or _manifest_path(os.environ.get("NOTEAI_MODEL_ARTIFACT_MANIFEST"))
    base_url = base_url if base_url is not None else os.environ.get("NOTEAI_MODEL_ARTIFACT_BASE_URL", "").strip()
    required = _truthy(os.environ.get("NOTEAI_MODEL_ARTIFACT_REQUIRED")) if required is None else required

    manifest = load_manifest(manifest_path)
    checked: list[str] = []
    repaired: list[str] = []
    missing_or_invalid: list[str] = []

    for artifact in manifest.get("artifacts", []):
        raw_path = str(artifact.get("path") or "")
        expected_sha = str(artifact.get("sha256") or "")
        if not raw_path or not expected_sha:
            continue
        target = _target_path(raw_path)
        ok = target.exists() and sha256_file(target) == expected_sha
        if not ok and base_url and not check_only:
            _download(_url_for(base_url, raw_path), target)
            ok = target.exists() and sha256_file(target) == expected_sha
            if ok:
                repaired.append(raw_path)
        if ok:
            checked.append(raw_path)
        else:
            missing_or_invalid.append(raw_path)

    if missing_or_invalid and (required or check_only):
        raise RuntimeError(
            "model artifacts missing or checksum mismatch: "
            + ", ".join(missing_or_invalid)
        )

    return {
        "release": manifest.get("release"),
        "run_id": manifest.get("run_id"),
        "checked": checked,
        "repaired": repaired,
        "missing_or_invalid": missing_or_invalid,
        "base_url_configured": bool(base_url),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch or verify NoteAI model artifacts.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--required", action="store_true")
    args = parser.parse_args()

    result = ensure_model_artifacts(
        Path(args.manifest),
        args.base_url,
        check_only=args.check_only,
        required=args.required,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
