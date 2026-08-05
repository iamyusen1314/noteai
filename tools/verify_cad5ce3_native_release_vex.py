#!/usr/bin/env python3
"""Build and verify the exact cad5ce3 native source-candidate VEX.

The successor bundle binds the one approved GitHub run and its native
artifact archive digest to five local image/SBOM identities.  Canonical raw
Debian findings remain unsuppressed at 4 Critical / 19 High per role.  Local
image IDs are never treated as Registry manifests or deployment authority.
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
PRIOR_RELEASE_COMMIT = "0149888d16468c8e8ea055e62ce0aa5d56a28971"
RELEASE_COMMIT = "cad5ce35664f617c6e19f90a6159285ddf975594"
RELEASE_SHORT = RELEASE_COMMIT[:7]
TASK_ID = "PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001"
RUN_ID = 31017791512
JOB_ID = 92346323999
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
BASELINE_EVIDENCE_PATH = (
    ROOT / "security" / "vex" / "b55f118-github-native-release-evidence.json"
)
EXPECTED_SUMMARY_SHA256 = (
    "f35516fb0030e16c8f392db7e308f10e2858cb8f7b9ed2fd3f10a11b0fce6160"
)
EXPECTED_EVIDENCE_SEMANTIC_SHA256 = (
    "4c9d997f4dc2c75102e9688d41ee6db77047d7294b8364ab42119e7eb0d9c71f"
)
EXPECTED_VEX_SEMANTIC_SHA256 = (
    "7ef605d1cc60ce9700dc810e80e8b4604ae64b9c7ac0cb533cdb96b2f4a227a9"
)
EXPECTED_ARTIFACT_BINDING = {
    "id": 8935383018,
    "name": (
        "native-amd64-release-evidence-"
        "cad5ce35664f617c6e19f90a6159285ddf975594"
    ),
    "archive_digest": (
        "sha256:281f208b3047fbff6dddb0fe0de3065203f1b507ca0f6a71381880f306390949"
    ),
    "archive_digest_kind": "github_actions_artifact_archive_sha256",
    "size_bytes": 1963638,
    "expires_at": "2026-08-19T15:01:04Z",
    "file_count": 43,
    "summary_sha256": EXPECTED_SUMMARY_SHA256,
}
EXPECTED_ROLE_IDENTITIES = {
    "api": {
        "local_image_id": "sha256:b868d8b625465681b0fc8837f49be4fcf32024ca4da9876651843e49cbb60f3a",
        "sbom_sha256": "ea317d7c438e0fe5e311a3b73a439ba62bd2cfb997f0649947d7504ff2042a52",
        "vulnerability_sha256": "4b2138f883328c60fc65fb51537a91b5e877a36593ce7a8363d0dbea8d1a0260",
        "secret_sha256": "578f5c36b2886f5d490ffbde1e64431eb234de65953d6509969d7dad46af13dc",
    },
    "admin": {
        "local_image_id": "sha256:30735bbe569f01cbc8b4e3acea9eb93e6d7f8266f9aa731af7b61d6b70e9d6c6",
        "sbom_sha256": "8416944e138223c6a3eb80c9841f2ad74421d1946ee8991e8e8c0efa8701dfac",
        "vulnerability_sha256": "2094454bd667ff1b63eeb28277b6f63dd06debf72686c2953960637d1ab01abe",
        "secret_sha256": "77ae97b2ddebd93bbad2c3cf6cb148906078bb3234e8b7b766ee11b0b240bd4b",
    },
    "payment": {
        "local_image_id": "sha256:8f044d7fa5da88ce3e6b1df7880f25f304006297ae05b1149004af3ec0ed19db",
        "sbom_sha256": "56c62ac4bc943dbb7f6e6c053c48fcbe22556b14642b95476b1b3c92debf8bc3",
        "vulnerability_sha256": "404954d93747b4b0b722c508429fc3550791a161d395740e9771da2c891ca474",
        "secret_sha256": "d59f7b7213a447c5861fe79fc917892321eb9dc27fe83a98403f187384ab32d9",
    },
    "ai-worker": {
        "local_image_id": "sha256:18db7ceff942788bc4ca1c77a466c17570c3fcc6f109957661e1a35f047ba62f",
        "sbom_sha256": "1bf79388f65009b793f241cd96dc714fa0ed042341654a7fc99eb38ecb3cd9e2",
        "vulnerability_sha256": "a7ed31ac0fe4c599ca89d3a398962e632c06a8a03d9357eb91c875bc8709e5ac",
        "secret_sha256": "166dc53bf0ec0c7c2325c693c9c44873267dd83cb4c7e1f43c55c6d69dbffc6a",
    },
    "xhs-http": {
        "local_image_id": "sha256:a30c0427ff855df19e23a5f7dc012f0a068afa4d81e1a2a41336e5956874cd76",
        "sbom_sha256": "b91d0c39345618fabfd903bb024f6a7f0e6f8ec0d20bb9402a9b9ce38c47a7cc",
        "vulnerability_sha256": "efe6cbd5cc53dcd4e5d29108857a7df9bf1feeb7e197b8c009a5a18a7f326c74",
        "secret_sha256": "0936f7569417abb2631618bc2a7baf2a99ba50b231193450e8aa8f371ec604ae",
    },
}
EXPECTED_FINDINGS = {
    "critical": 4,
    "high": 19,
    "secrets": 0,
    "browser_components": 0,
    "cryptography_version": "50.0.0",
    "cryptography_components": 1,
    "forbidden_os_packages": 0,
}
EXPECTED_IMAGE_CONTEXT_DELTA = ("model/requirements-api.txt",)
DURABLE_AI_SYSTEMD_PATHS = (
    "deploy/production/systemd/noteai-ai-dispatcher.service.template",
    "deploy/production/systemd/noteai-ai-worker.service.template",
    "deploy/production/systemd/noteai-ai-dispatcher-acceptance.service.template",
    "deploy/production/systemd/noteai-ai-worker-acceptance.service.template",
)
SOURCE_PATHS = native.SOURCE_PATHS + DURABLE_AI_SYSTEMD_PATHS


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
        raise ValueError("cannot enumerate successor image-context delta")
    changed = tuple(sorted(result.stdout.splitlines()))
    if changed != EXPECTED_IMAGE_CONTEXT_DELTA:
        raise ValueError(f"successor image-context delta changed: {changed}")
    return {
        "prior_application_revision": PRIOR_RELEASE_COMMIT,
        "image_context_changed_paths": list(changed),
        "prior_blob_sha256": {
            path: _sha256_bytes(_git_blob(PRIOR_RELEASE_COMMIT, path))
            for path in changed
        },
        "release_blob_sha256": {
            path: _sha256_bytes(_git_blob(RELEASE_COMMIT, path)) for path in changed
        },
        "purpose": (
            "Replace cryptography 48.0.1 with 50.0.0 to remove the two "
            "actionable Python High findings without changing the image base, "
            "application command graph or runtime constraints."
        ),
    }


def _validate_durable_ai_systemd_contract() -> None:
    common_tokens = (
        "Restart=no",
        "/usr/bin/docker image inspect @@NOTEAI_AI_WORKER_IMAGE@@",
        "/usr/bin/docker run --pull=never",
        "--rm",
        "--user=999:999",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--network=bridge",
        "--ipc=private",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,",
        "@@NOTEAI_AI_WORKER_IMAGE@@ python durable_ai_worker.py",
    )
    sources = {
        path: _git_blob(RELEASE_COMMIT, path).decode("utf-8")
        for path in DURABLE_AI_SYSTEMD_PATHS
    }
    for path, source in sources.items():
        if any(token not in source for token in common_tokens):
            raise ValueError(f"durable AI systemd hardening changed: {path}")
        forbidden = (
            "--publish",
            "--privileged",
            "--device",
            "--network=host",
            "--pid=host",
            "--ipc=host",
            "--mount",
            "/bin/sh",
            "bash -c",
        )
        if any(token in source for token in forbidden):
            raise ValueError(f"durable AI systemd exposure changed: {path}")
        if source.count("@@NOTEAI_AI_WORKER_IMAGE@@") != 2:
            raise ValueError(f"durable AI systemd image binding changed: {path}")

    expected_modes = {
        DURABLE_AI_SYSTEMD_PATHS[0]: (
            "--memory=256m --cpus=0.25 --pids-limit=64",
            "--env-file=/etc/noteai/ai-dispatcher.env",
            "--env=NOTEAI_DURABLE_AI_SUSPENDED=1",
            "durable_ai_worker.py --dispatcher-loop",
            "ExecStartPost=/usr/bin/docker exec noteai-ai-dispatcher python durable_ai_worker.py --healthcheck",
        ),
        DURABLE_AI_SYSTEMD_PATHS[1]: (
            "--memory=1536m --cpus=1.0 --pids-limit=96",
            "--env-file=/etc/noteai/ai-worker.env --env-file=/etc/noteai/private-storage.env",
            "--env=NOTEAI_DURABLE_AI_SUSPENDED=1",
            "durable_ai_worker.py --worker-loop",
            "ExecStartPost=/usr/bin/docker exec noteai-ai-worker python durable_ai_worker.py --healthcheck",
        ),
        DURABLE_AI_SYSTEMD_PATHS[2]: (
            "--memory=256m --cpus=0.25 --pids-limit=64",
            "--env-file=/etc/noteai/ai-dispatcher.env",
            "--env=NOTEAI_DURABLE_AI_SUSPENDED=0",
            "--env=NOTEAI_DURABLE_AI_ACCEPTANCE_MODE=1",
            "--env=NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID=@@NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID@@",
            "durable_ai_worker.py --dispatcher-once",
            "RuntimeMaxSec=120",
        ),
        DURABLE_AI_SYSTEMD_PATHS[3]: (
            "--memory=1536m --cpus=1.0 --pids-limit=96",
            "--env-file=/etc/noteai/ai-worker.env --env-file=/etc/noteai/private-storage.env",
            "--env=NOTEAI_DURABLE_AI_SUSPENDED=0",
            "--env=NOTEAI_DURABLE_AI_PROCESSOR=internal-acceptance-v1",
            "--env=NOTEAI_DURABLE_AI_ACCEPTANCE_MODE=1",
            "--env=NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID=@@NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID@@",
            "--env=NOTEAI_DURABLE_AI_ACCEPTANCE_ACTION=@@NOTEAI_DURABLE_AI_ACCEPTANCE_ACTION@@",
            "durable_ai_worker.py --worker-once",
            "RuntimeMaxSec=360",
        ),
    }
    for path, tokens in expected_modes.items():
        if any(token not in sources[path] for token in tokens):
            raise ValueError(f"durable AI systemd execution mode changed: {path}")
    if "/etc/noteai/private-storage.env" in sources[DURABLE_AI_SYSTEMD_PATHS[0]]:
        raise ValueError("dispatcher production unit gained private storage")
    if "/etc/noteai/private-storage.env" in sources[DURABLE_AI_SYSTEMD_PATHS[2]]:
        raise ValueError("dispatcher acceptance unit gained private storage")
    for path in DURABLE_AI_SYSTEMD_PATHS[2:]:
        if "ExecStartPost=" in sources[path]:
            raise ValueError(f"acceptance unit gained a persistent health hook: {path}")


def _expected_artifact_names() -> set[str]:
    names = {"python-base-index.json", "node-base-index.json", "summary.json"}
    suffixes = (
        "build-metadata.json",
        "history.jsonl",
        "inspect.json",
        "os-packages.txt",
        "sbom.cdx.json",
        "secret.json",
        "summary.json",
        "vuln-high-critical.json",
    )
    for role in ROLES:
        names.update(f"{role}-{suffix}" for suffix in suffixes)
    return names


def _verify_downloaded_artifact(evidence_root: Path) -> dict[str, Any]:
    children = tuple(evidence_root.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in children):
        raise ValueError("native artifact contains a non-regular file")
    if {path.name for path in children} != _expected_artifact_names():
        raise ValueError("native artifact 43-file contract changed")
    if native._sha256(evidence_root / "summary.json") != EXPECTED_SUMMARY_SHA256:
        raise ValueError("native artifact summary hash mismatch")
    for role in ROLES:
        sbom = _json(evidence_root / f"{role}-sbom.cdx.json")
        crypto = [
            component
            for component in sbom.get("components", [])
            if component.get("name") == "cryptography"
        ]
        if len(crypto) != 1 or crypto[0].get("version") != "50.0.0":
            raise ValueError(f"{role}: exact cryptography component changed")
        secret = _json(evidence_root / f"{role}-secret.json")
        secret_count = sum(
            len(result.get("Secrets") or []) for result in secret.get("Results", [])
        )
        if secret_count:
            raise ValueError(f"{role}: raw Secret report is nonzero")
        inspect = _json(evidence_root / f"{role}-inspect.json")
        if inspect[0].get("RepoDigests"):
            raise ValueError(f"{role}: local evidence claims a RepoDigest")
        metadata = _json(evidence_root / f"{role}-build-metadata.json")
        if metadata.get("containerimage.config.digest") != inspect[0].get("Id"):
            raise ValueError(f"{role}: config digest and local image ID differ")
    return dict(EXPECTED_ARTIFACT_BINDING)


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
    native.EXPECTED_NATIVE_SUMMARY_SCHEMA = "noteai.native-release-evidence.v2"
    native.EXPECTED_FINDINGS = EXPECTED_FINDINGS
    native.REVIEW_DEPENDENCY_CHECKS = {"cryptography_50_0_0_per_role": 1}
    native.SOURCE_PATHS = SOURCE_PATHS
    native.EXPECTED_PRODUCTION_SERVICES = (
        "api",
        "admin",
        "payment",
        "ai-dispatcher",
        "ai-worker",
        "xhs-trends",
        "xhs-tracking",
    )


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
        "EXPECTED_NATIVE_SUMMARY_SCHEMA",
        "EXPECTED_FINDINGS",
        "REVIEW_DEPENDENCY_CHECKS",
        "SOURCE_PATHS",
        "EXPECTED_PRODUCTION_SERVICES",
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
        _validate_durable_ai_systemd_contract()
        evidence_root = native._find_evidence_root(source_dir)
        artifact = _verify_downloaded_artifact(evidence_root)
        evidence = native.build_evidence(source_dir)
        baseline = _json(BASELINE_EVIDENCE_PATH)
        if evidence["base_images"] != baseline["base_images"]:
            raise ValueError("base image identity changed from reviewed baseline")
        if evidence["vulnerability_rows_per_role"] != baseline["vulnerability_rows_per_role"]:
            raise ValueError("canonical Debian vulnerability rows changed")
        evidence["native_workflow"]["attempt"] = 1
        evidence["native_workflow"]["artifact"] = artifact
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
        try:
            _validate_durable_ai_systemd_contract()
        except (UnicodeDecodeError, ValueError) as exc:
            return [f"malformed cad5ce3 successor evidence: {exc}"]
        errors = native.validate_documents(evidence, vex, review)
    try:
        baseline = _json(BASELINE_EVIDENCE_PATH)
        workflow = evidence.get("native_workflow", {})
        if workflow.get("attempt") != 1:
            errors.append("native workflow attempt must remain one")
        if workflow.get("artifact") != EXPECTED_ARTIFACT_BINDING:
            errors.append("GitHub native artifact binding changed")
        if evidence.get("release_delta") != _image_context_delta():
            errors.append("successor image-context delta changed")
        if evidence.get("base_images") != baseline.get("base_images"):
            errors.append("base images differ from reviewed baseline")
        if (
            evidence.get("vulnerability_rows_per_role")
            != baseline.get("vulnerability_rows_per_role")
        ):
            errors.append("canonical Debian rows differ from reviewed baseline")
        if (
            workflow.get("artifact_summary_sha256")
            != EXPECTED_SUMMARY_SHA256
        ):
            errors.append("native artifact summary hash mismatch")
        if (
            review.get("evidence_semantic_sha256")
            != EXPECTED_EVIDENCE_SEMANTIC_SHA256
        ):
            errors.append("successor evidence semantic hash changed")
        if review.get("vex_semantic_sha256") != EXPECTED_VEX_SEMANTIC_SHA256:
            errors.append("successor VEX semantic hash changed")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        errors.append(f"malformed cad5ce3 successor evidence: {exc}")
    return errors


def validate_bundle() -> list[str]:
    try:
        return validate_documents(
            _json(EVIDENCE_PATH),
            _json(VEX_PATH),
            _json(REVIEW_PATH),
        )
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load cad5ce3 native VEX bundle: {exc}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build-from",
        type=Path,
        help="Build from the downloaded exact successor evidence directory.",
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
        "PASS: exact cad5ce3 native five-role source-candidate VEX; "
        "cryptography findings are zero and raw Debian reports remain "
        "unsuppressed at 4 Critical / 19 High per role"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
