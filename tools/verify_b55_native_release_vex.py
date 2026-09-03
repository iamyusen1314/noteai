#!/usr/bin/env python3
"""Build and verify the exact b55f118 native release source-candidate VEX.

This verifier reuses the fail-closed b06671f native evidence implementation
without rewriting its historical bundle.  It binds a fresh five-role AMD64
build to b55f118 and additionally proves that the image-build context changed
only for the private-storage runtime fix and its durable-worker consumer.
Registry publication and deployment remain separate gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import verify_native_release_vex as native


ROOT = Path(__file__).resolve().parents[1]
PRIOR_RELEASE_COMMIT = "b06671fbcca51f884b04c86edcf116e373c6cfa8"
RELEASE_COMMIT = "b55f11882100e9ef919522540729e366a511f88f"
RELEASE_SHORT = RELEASE_COMMIT[:7]
TASK_ID = "PROD-FIRST-LAUNCH-IMMUTABLE-RELEASE-B55F118-001"
RUN_ID = 30451355971
JOB_ID = 90573920470
RUN_URL = f"https://github.com/iamyusen1314/noteai/actions/runs/{RUN_ID}"
ROLES = native.ROLES
EVIDENCE_PATH = (
    ROOT / "security" / "vex" / f"{RELEASE_SHORT}-github-native-release-evidence.json"
)
VEX_PATH = (
    ROOT / "security" / "vex" / f"{RELEASE_SHORT}-github-native-release.vex.cdx.json"
)
REVIEW_PATH = (
    ROOT / "security" / "vex" / f"{RELEASE_SHORT}-github-native-release-review.json"
)
PRIOR_EVIDENCE_PATH = (
    ROOT / "security" / "vex" / "b06671f-github-native-release-evidence.json"
)
EXPECTED_SUMMARY_SHA256 = (
    "c6b1f206233583d271ff386e447ff5072900710203d5f78927bcbff4daf76162"
)
EXPECTED_ROLE_IDENTITIES = {
    "api": {
        "local_image_id": "sha256:d75ec1522963810058532bae82a28cbe22132dec32350e282350e65aa9e1f6a1",
        "sbom_sha256": "6af23da49ab3247215706a0dc4da55a37d080c4c92d864bd48f05df81d8a360f",
        "vulnerability_sha256": "85e01c3241bf8b9155f5ab8370a59785d6c9db06f7b09b03a5aca3322aae876e",
    },
    "admin": {
        "local_image_id": "sha256:50a21bea7e496a6f09e3e71fd0e1d4a9fb06fb23815d2bea702808bc24d98a71",
        "sbom_sha256": "1a3556c7ec02a95365865a37a31804e484eac0d1a4383f341df347abb01e0661",
        "vulnerability_sha256": "940d5828ddb0f82f04644d1e940cb568f7ae531d0634f28b286d46ba3e365817",
    },
    "payment": {
        "local_image_id": "sha256:8acd61e3640104207bad8f8018171640b69d2d760053bd7a152bf263de27a390",
        "sbom_sha256": "b6116a563d74d5058cffdbadd34c70196d9068d53c3db46d769fdb7a9e898347",
        "vulnerability_sha256": "75bb5a377afaf637a4fdf1edfe28d9726d7c843ca898a4380222b3b124160efa",
    },
    "ai-worker": {
        "local_image_id": "sha256:b34021f692ef4f5aa08ec8837e7e925c3ff7d2773b416763bd85498cd5c09f85",
        "sbom_sha256": "47ef611142ca9d141b3b90a2217b7b5755c58a82d7974d7fc68e11925a9757e4",
        "vulnerability_sha256": "96c45c5d09eab0c25e354dc477ad8fbe107ffb7e3b63f1355ab9c0294ef12257",
    },
    "xhs-http": {
        "local_image_id": "sha256:aae7bd0db630f642b970f7423ab27d1354985392657f17865b5cfab72f96aee3",
        "sbom_sha256": "3a4e776a79676a224026115b0f0305181bd461501e17af0e389ce0e36dec16f1",
        "vulnerability_sha256": "1c9f4f8a1bfd16888d110f7a2d0993cfea9484a66d308eeccdcc42adf5c009b9",
    },
}
EXPECTED_IMAGE_CONTEXT_DELTA = (
    "model/durable_ai_worker.py",
    "model/private_storage.py",
)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_blob(revision: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"cannot read release blob: {path}")
    return result.stdout


def _image_context_delta() -> dict[str, Any]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            PRIOR_RELEASE_COMMIT,
            RELEASE_COMMIT,
            "--",
            "Dockerfile",
            "model",
            "scripts/docker_entrypoint.sh",
            "scripts/render_start_api.sh",
            "scripts/render_start_admin.sh",
            "scripts/render_start_payment.sh",
            "scripts/render_predeploy.py",
            "scripts/render_run_market_timing.sh",
            "scripts/render_run_crawler.sh",
            "scripts/migrate_sqlite_to_postgres.py",
            "scripts/migrate_managed_prompts_v04.py",
            "NoteAI_Pro_Demo_Framer.html",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise ValueError("cannot enumerate image context delta")
    changed = tuple(sorted(result.stdout.splitlines()))
    if changed != EXPECTED_IMAGE_CONTEXT_DELTA:
        raise ValueError(f"image context delta changed: {changed}")
    return {
        "prior_application_revision": PRIOR_RELEASE_COMMIT,
        "image_context_changed_paths": list(changed),
        "release_blob_sha256": {
            path: _sha256_bytes(_git_blob(RELEASE_COMMIT, path)) for path in changed
        },
        "unchanged_build_contract_sha256": {
            path: _sha256_bytes(_git_blob(RELEASE_COMMIT, path))
            for path in (
                "Dockerfile",
                "model/requirements-api.txt",
                "scripts/docker_entrypoint.sh",
                "deploy/production/docker-compose.yml",
            )
        },
        "purpose": (
            "Require the production-proven IMDSv2-only private-storage "
            "configuration, canonical OSS metadata headers and bounded SDK "
            "error unwrapping without changing the reviewed command graph."
        ),
    }


def _configure_native_profile() -> None:
    native.RELEASE_COMMIT = RELEASE_COMMIT
    native.RELEASE_SHORT = RELEASE_SHORT
    native.TASK_ID = TASK_ID
    native.RUN_ID = RUN_ID
    native.JOB_ID = JOB_ID
    native.RUN_URL = RUN_URL
    native.EVIDENCE_PATH = EVIDENCE_PATH
    native.VEX_PATH = VEX_PATH
    native.REVIEW_PATH = REVIEW_PATH
    native.EXPECTED_ROLE_IDENTITIES = EXPECTED_ROLE_IDENTITIES


@contextmanager
def _native_profile():
    names = (
        "RELEASE_COMMIT",
        "RELEASE_SHORT",
        "TASK_ID",
        "RUN_ID",
        "JOB_ID",
        "RUN_URL",
        "EVIDENCE_PATH",
        "VEX_PATH",
        "REVIEW_PATH",
        "EXPECTED_ROLE_IDENTITIES",
    )
    previous = {name: getattr(native, name) for name in names}
    _configure_native_profile()
    try:
        yield
    finally:
        for name, value in previous.items():
            setattr(native, name, value)


def build_bundle(source_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    with _native_profile():
        evidence_root = native._find_evidence_root(source_dir)
        if native._sha256(evidence_root / "summary.json") != EXPECTED_SUMMARY_SHA256:
            raise ValueError("native artifact summary hash mismatch")
        evidence = native.build_evidence(source_dir)
        prior = _json(PRIOR_EVIDENCE_PATH)
        if evidence["base_images"] != prior["base_images"]:
            raise ValueError("base image identity changed from reviewed predecessor")
        if (
            evidence["vulnerability_rows_per_role"]
            != prior["vulnerability_rows_per_role"]
        ):
            raise ValueError("unsuppressed vulnerability rows changed from predecessor")
        evidence["release_delta"] = _image_context_delta()
        vex = native.build_vex(evidence)
        review = native.build_review(evidence, vex)
    return evidence, vex, review


def validate_documents(
    evidence: dict[str, Any],
    vex: dict[str, Any],
    review: dict[str, Any],
) -> list[str]:
    with _native_profile():
        errors = native.validate_documents(evidence, vex, review)
    try:
        prior = _json(PRIOR_EVIDENCE_PATH)
        if evidence.get("release_delta") != _image_context_delta():
            errors.append("release image-context delta changed")
        if evidence.get("base_images") != prior.get("base_images"):
            errors.append("base images differ from reviewed predecessor")
        if (
            evidence.get("vulnerability_rows_per_role")
            != prior.get("vulnerability_rows_per_role")
        ):
            errors.append("unsuppressed vulnerability rows differ from predecessor")
        if (
            evidence.get("native_workflow", {}).get("artifact_summary_sha256")
            != EXPECTED_SUMMARY_SHA256
        ):
            errors.append("native artifact summary hash mismatch")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        errors.append(f"malformed b55 release delta: {exc}")
    return errors


def validate_bundle() -> list[str]:
    try:
        return validate_documents(
            _json(EVIDENCE_PATH),
            _json(VEX_PATH),
            _json(REVIEW_PATH),
        )
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load b55 native VEX bundle: {exc}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build-from",
        type=Path,
        help="Build from a downloaded exact native evidence directory.",
    )
    args = parser.parse_args()
    if args.build_from:
        evidence, vex, review = build_bundle(args.build_from)
        native._write_json(EVIDENCE_PATH, evidence)
        native._write_json(VEX_PATH, vex)
        native._write_json(REVIEW_PATH, review)
    errors = validate_bundle()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(
        "PASS: exact b55f118 native five-role source-candidate VEX; "
        "raw reports remain unsuppressed at 4 Critical / 19 High per role"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
