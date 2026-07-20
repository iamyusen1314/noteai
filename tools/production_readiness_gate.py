#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline production readiness gate for NoteAI.

This gate verifies deployable repository assets only. It does not call LLMs,
fact-search providers, payment APIs, or GitHub. The goal is to catch release
drift before CI/deploy: model artifacts, registry, release evidence, RQS-07
quality evidence, Docker startup behavior, and obvious secret mistakes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from artifact_loader import ensure_model_artifacts, sha256_file  # noqa: E402


REQUIRED_MODEL_ROLES = {"quality_regressor", "ready_classifier", "preference_ranker", "train_report"}
HUMAN_MODEL_RELEASE_MANIFEST = MODEL_DIR / "artifacts" / "MODEL_RELEASE_MANIFEST.md"
REQUIRED_ENV_NAMES = {
    "ANTHROPIC_API_KEY",
    "MOONSHOT_API_KEY",
    "ADMIN_PASSWORD",
    "NOTEAI_ENABLE_TEST_BILLING",
    "NOTEAI_USE_V04_COMPOSITE",
    "NOTEAI_MODEL_ARTIFACT_REQUIRED",
    "NOTEAI_MODEL_ARTIFACT_BASE_URL",
    "NOTEAI_FACT_SEARCH",
    "NOTEAI_API_STARTS_TREND_SCHEDULER",
    "NOTEAI_HOT_KEYWORD_FRESH_HOURS",
    "NOTEAI_MARKET_TIMING_REQUIRED",
    "NOTEAI_MARKET_TIMING_SNAPSHOT_URL",
    "AMAP_WEB_KEY",
    "MEITUAN_OPEN_TOKEN",
    "MEITUAN_AI_HUB_TOKEN",
}
REQUIRED_DOMAINS = {"美食", "旅行", "穿搭", "美妆", "家居", "健身"}
SECRET_NAME_RE = re.compile(
    r"\b([A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|WEB_KEY|SIGN_KEY|AES_KEY|APP_AUTH_TOKEN)[A-Z0-9_]*)\b"
    r"\s*[:=]\s*['\"]?([^'\"\n#]+)"
)
SAFE_SECRET_VALUES = {
    "",
    "0",
    "1",
    "test-key",
    "change-me-before-deploy",
    "example",
    "<base-url>",
    "<your-value>",
    "redacted",
    "placeholder",
}


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_model_path(raw_path: str) -> str:
    path = Path(raw_path)
    if path.is_absolute():
        try:
            return str(path.relative_to(ROOT))
        except ValueError:
            return f"model/artifacts/{path.name}"
    if path.parts and path.parts[0] == "model":
        return str(path)
    return str(Path("model") / path)


def _load_human_release_hashes(path: Path) -> dict[str, str]:
    """Read the path/SHA pairs from the human release manifest tables."""
    declared: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        code_fields = re.findall(r"`([^`]+)`", line)
        if len(code_fields) < 2:
            continue
        raw_path, raw_sha = code_fields[0], code_fields[-1].lower()
        if raw_path.startswith("model/") and re.fullmatch(r"[0-9a-f]{64}", raw_sha):
            declared[_normalize_model_path(raw_path)] = raw_sha
    return declared


def _declared_sha256_mismatches(
    declared: dict[str, str],
    *,
    root: Path = ROOT,
) -> list[str]:
    mismatches: list[str] = []
    for raw_path, expected in sorted(declared.items()):
        target = root / raw_path
        if not target.is_file() or sha256_file(target) != expected:
            mismatches.append(raw_path)
    return mismatches


def _ok(name: str, passed: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _fragments_in_order(text: str, fragments: tuple[str, ...]) -> bool:
    position = -1
    for fragment in fragments:
        position = text.find(fragment, position + 1)
        if position < 0:
            return False
    return True


def _check_entrypoint_runtime_contract(entrypoint: str) -> tuple[bool, str]:
    """Execute the role/command contract without loading artifacts or commands."""
    required_fragments = (
        "runtime_role_file=/etc/noteai-runtime-role",
        "cd /app/model",
        "  python -m artifact_loader",
        'exec "$@"',
    )
    missing = [fragment for fragment in required_fragments if fragment not in entrypoint]
    if missing:
        return False, f"harness_missing_fragments={len(missing)}"

    allowed_cases = {
        "api_start": ("api", ("/app/scripts/render_start_api.sh",)),
        "api_predeploy": ("api", ("python", "/app/scripts/render_predeploy.py")),
        "worker_admin_start": ("worker", ("/app/scripts/render_start_admin.sh",)),
        "worker_market_wrapper": ("worker", ("/app/scripts/render_run_market_timing.sh",)),
        "worker_crawler_wrapper": ("worker", ("/app/scripts/render_run_crawler.sh",)),
        "worker_admin_compose": (
            "worker",
            ("python", "-m", "uvicorn", "admin_server:admin_app", "--host", "0.0.0.0", "--port", "8001"),
        ),
        "worker_market_bare": ("worker", ("python", "market_timing_worker.py")),
        "worker_market_once": ("worker", ("python", "market_timing_worker.py", "--once")),
        "worker_market_daemon": (
            "worker",
            ("python", "market_timing_worker.py", "--daemon", "--interval", "60"),
        ),
        "worker_crawler_bare": ("worker", ("python", "crawler_worker.py")),
        "worker_crawler_once": ("worker", ("python", "crawler_worker.py", "--once")),
        "worker_crawler_loop": (
            "worker",
            ("python", "crawler_worker.py", "--loop", "--interval-minutes", "60", "--limit", "50"),
        ),
        "worker_predeploy": ("worker", ("python", "/app/scripts/render_predeploy.py")),
        "worker_fail_closed_default": ("worker", ("/bin/false",)),
    }
    rejected_command_cases = {
        "api_empty_command": ("api", ()),
        "api_direct_uvicorn": ("api", ("python", "-m", "uvicorn", "api:app")),
        "api_file": ("api", ("python", "api.py")),
        "api_module_worker": ("api", ("python", "-m", "crawler_worker")),
        "api_absolute_worker": ("api", ("python", "/app/model/crawler_worker.py")),
        "api_shell_wrapper": ("api", ("sh", "-c", "/app/scripts/render_start_api.sh")),
        "api_start_extra": ("api", ("/app/scripts/render_start_api.sh", "extra")),
        "api_predeploy_extra": ("api", ("python", "/app/scripts/render_predeploy.py", "extra")),
        "worker_api_start": ("worker", ("/app/scripts/render_start_api.sh",)),
        "worker_direct_api": (
            "worker",
            ("python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"),
        ),
        "worker_api_file": ("worker", ("python", "api.py")),
        "worker_absolute_api": ("worker", ("python", "/app/model/api.py")),
        "worker_module_worker": ("worker", ("python", "-m", "crawler_worker")),
        "worker_absolute_worker": ("worker", ("python", "/app/model/crawler_worker.py")),
        "worker_shell_wrapper": ("worker", ("sh", "-c", "/app/scripts/render_run_crawler.sh")),
        "worker_wrapper_extra": ("worker", ("/app/scripts/render_run_crawler.sh", "extra")),
        "worker_predeploy_extra": ("worker", ("python", "/app/scripts/render_predeploy.py", "extra")),
        "worker_false_extra": ("worker", ("/bin/false", "extra")),
        "worker_unknown_python": ("worker", ("python", "-c", "import api")),
        "worker_market_negative": (
            "worker",
            ("python", "market_timing_worker.py", "--daemon", "--interval", "-1"),
        ),
        "worker_market_empty": (
            "worker",
            ("python", "market_timing_worker.py", "--daemon", "--interval", ""),
        ),
        "worker_market_non_numeric": (
            "worker",
            ("python", "market_timing_worker.py", "--daemon", "--interval", "api:app"),
        ),
        "worker_crawler_negative": (
            "worker",
            ("python", "crawler_worker.py", "--loop", "--interval-minutes", "-1", "--limit", "50"),
        ),
        "worker_crawler_empty": (
            "worker",
            ("python", "crawler_worker.py", "--loop", "--interval-minutes", "60", "--limit", ""),
        ),
        "worker_crawler_non_numeric": (
            "worker",
            ("python", "crawler_worker.py", "--loop", "--interval-minutes", "api.py", "--limit", "50"),
        ),
    }
    marker_cases = {
        "marker_missing": ("missing", "api", "api"),
        "marker_unreadable": ("unreadable", "api", "api"),
        "marker_empty": ("empty", "api", "api"),
        "marker_read_failure": ("read_failure", "api", "api"),
        "marker_invalid": ("valid", "invalid", "invalid"),
        "marker_role_mismatch": ("valid", "api", "worker"),
    }
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="noteai-entrypoint-contract-") as tmp:
        root = Path(tmp)

        def run_case(
            name: str,
            image_role: str,
            declared_role: str,
            command: tuple[str, ...],
            *,
            marker_state: str = "valid",
            allowed: bool,
            extra_env: dict[str, str] | None = None,
        ) -> None:
            case_dir = root / name
            case_dir.mkdir()
            marker = case_dir / "noteai-runtime-role"
            if marker_state == "valid":
                marker.write_text(f"{image_role}\n", encoding="utf-8")
            elif marker_state == "unreadable":
                marker.write_text(f"{image_role}\n", encoding="utf-8")
                marker.chmod(0o000)
            elif marker_state == "empty":
                marker.write_text("\n", encoding="utf-8")
            elif marker_state == "read_failure":
                marker.write_text(image_role, encoding="utf-8")
            elif marker_state != "missing":
                failures.append(f"{name}:invalid_harness_marker_state")
                return

            artifact_sentinel = case_dir / "artifact-called"
            exec_sentinel = case_dir / "exec-called"
            script = case_dir / "docker_entrypoint.sh"
            transformed = entrypoint.replace(
                "runtime_role_file=/etc/noteai-runtime-role",
                f"runtime_role_file='{marker}'",
                1,
            ).replace(
                "cd /app/model",
                f"cd '{MODEL_DIR}'",
                1,
            ).replace(
                "  python -m artifact_loader",
                f"  printf '%s\\n' called > '{artifact_sentinel}'",
                1,
            ).replace(
                'exec "$@"',
                f"printf '%s\\n' called > '{exec_sentinel}'\nexit 0",
                1,
            )
            script.write_text(transformed, encoding="utf-8")
            env = {
                "PATH": os.defpath,
                "NOTEAI_RUNTIME_ROLE": declared_role,
                "NOTEAI_SKIP_MODEL_ARTIFACT_CHECK": "1" if allowed else "0",
                **(extra_env or {}),
            }
            try:
                result = subprocess.run(
                    ["sh", str(script), *command],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=5,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                failures.append(f"{name}:timeout")
                return
            finally:
                if marker.exists():
                    marker.chmod(0o600)

            artifact_called = artifact_sentinel.exists()
            exec_called = exec_sentinel.exists()
            if allowed:
                if result.returncode != 0 or artifact_called or not exec_called:
                    failures.append(f"{name}:allowed_contract_failed")
            elif result.returncode != 78 or artifact_called or exec_called:
                failures.append(f"{name}:reject_contract_failed")

        for name, (role, command) in allowed_cases.items():
            run_case(name, role, role, command, allowed=True)
        for name, (role, command) in rejected_command_cases.items():
            run_case(name, role, role, command, allowed=False)
        for name, (marker_state, image_role, declared_role) in marker_cases.items():
            run_case(
                name,
                image_role,
                declared_role,
                ("/app/scripts/render_start_api.sh",),
                marker_state=marker_state,
                allowed=False,
            )
        run_case(
            "api_scheduler_enabled",
            "api",
            "api",
            ("/app/scripts/render_start_api.sh",),
            allowed=False,
            extra_env={"NOTEAI_API_STARTS_TREND_SCHEDULER": "1"},
        )

    detail = f"allowed={len(allowed_cases)} rejected={len(rejected_command_cases) + len(marker_cases) + 1}"
    if failures:
        detail += f" failures={failures[:8]}"
    return not failures, detail


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def check_model_release() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    manifest_path = MODEL_DIR / "artifacts" / "model_release_manifest.v04.json"
    registry_path = MODEL_DIR / "model_registry.json"
    train_report_path = MODEL_DIR / "artifacts" / "model_v04_composite_train_report.json"
    readiness_path = MODEL_DIR / "artifacts" / "v04_composite_readiness.json"
    health_path = MODEL_DIR / "artifacts" / "v04_training_data_health.json"

    try:
        artifact_result = ensure_model_artifacts(manifest_path, check_only=True, required=True)
        checks.append(_ok(
            "model_artifacts_sha256",
            not artifact_result["missing_or_invalid"],
            f"checked={len(artifact_result['checked'])}",
        ))
    except Exception as exc:
        checks.append(_ok("model_artifacts_sha256", False, str(exc)))
        artifact_result = {"checked": []}

    manifest = _load_json(manifest_path)
    try:
        human_hashes = _load_human_release_hashes(HUMAN_MODEL_RELEASE_MANIFEST)
        human_mismatches = _declared_sha256_mismatches(human_hashes)
    except Exception as exc:
        human_hashes = {}
        human_mismatches = [type(exc).__name__]
    checks.append(_ok(
        "human_model_release_manifest_sha256",
        len(human_hashes) >= 8 and not human_mismatches,
        f"declared={len(human_hashes)} mismatches={human_mismatches}",
    ))

    roles = {item.get("role") for item in manifest.get("artifacts", [])}
    checks.append(_ok(
        "model_manifest_roles",
        REQUIRED_MODEL_ROLES.issubset(roles),
        f"roles={sorted(str(role) for role in roles)}",
    ))
    checks.append(_ok(
        "model_manifest_release",
        manifest.get("release") == "v0.4-composite" and manifest.get("run_id") == "20260628T013926Z",
        f"release={manifest.get('release')} run_id={manifest.get('run_id')}",
    ))

    size_mismatches = []
    for item in manifest.get("artifacts", []):
        expected_size = item.get("size_bytes")
        if not expected_size:
            continue
        target = ROOT / _normalize_model_path(str(item.get("path") or ""))
        if target.exists() and target.stat().st_size != int(expected_size):
            size_mismatches.append(_rel(target))
    checks.append(_ok("model_binary_sizes", not size_mismatches, ", ".join(size_mismatches)))

    registry = _load_json(registry_path)
    current = registry.get("current")
    model_info = (registry.get("models") or {}).get(str(current), {})
    registry_paths = {
        _normalize_model_path(str(model_info.get("file") or "")),
        _normalize_model_path(str(model_info.get("ready_classifier_file") or "")),
        _normalize_model_path(str(model_info.get("ranker_file") or "")),
        _normalize_model_path(str(model_info.get("train_report") or "")),
    }
    manifest_paths = {_normalize_model_path(str(item.get("path") or "")) for item in manifest.get("artifacts", [])}
    machine_human_mismatches = [
        path
        for item in manifest.get("artifacts", [])
        if (
            (path := _normalize_model_path(str(item.get("path") or ""))) not in human_hashes
            or human_hashes.get(path) != str(item.get("sha256") or "").lower()
        )
    ]
    checks.append(_ok(
        "machine_manifest_matches_human_manifest",
        not machine_human_mismatches,
        f"mismatches={machine_human_mismatches}",
    ))
    checks.append(_ok(
        "registry_points_to_v04_production",
        current == "v0.4-composite"
        and model_info.get("status") == "production"
        and model_info.get("run_id") == manifest.get("run_id"),
        f"current={current} status={model_info.get('status')} run_id={model_info.get('run_id')}",
    ))
    checks.append(_ok(
        "registry_matches_manifest",
        registry_paths.issubset(manifest_paths),
        f"missing={sorted(registry_paths - manifest_paths)}",
    ))

    train = _load_json(train_report_path)
    policy = train.get("training_policy") or {}
    gate = train.get("deployment_gate") or {}
    checks.append(_ok(
        "train_report_deployable",
        train.get("run_id") == manifest.get("run_id")
        and gate.get("passed") is True
        and policy.get("production_ready") is True
        and policy.get("do_not_deploy") is False,
        f"gate={gate.get('passed')} production_ready={policy.get('production_ready')} do_not_deploy={policy.get('do_not_deploy')}",
    ))

    readiness = _load_json(readiness_path)
    health = _load_json(health_path)
    checks.append(_ok(
        "v04_readiness_reports",
        readiness.get("decision") == "production_ready" and health.get("decision") == "production_ready",
        f"readiness={readiness.get('decision')} health={health.get('decision')}",
    ))
    checks.append(_ok(
        "v04_readiness_domains",
        REQUIRED_DOMAINS.issubset(set(readiness.get("core_domains") or [])),
        f"domains={readiness.get('core_domains')}",
    ))

    evidence_paths = [
        train_report_path,
        readiness_path,
        health_path,
        MODEL_DIR / "artifacts" / "v04_composite_audit.json",
        registry_path,
    ]
    missing_evidence = [_rel(path) for path in evidence_paths if not path.exists() or path.stat().st_size == 0]
    checks.append(_ok("model_release_evidence_files", not missing_evidence, ", ".join(missing_evidence)))

    return checks


def check_quality_evidence() -> list[dict[str, Any]]:
    report_path = ROOT / "docs" / "RQS07_REAL_CHAIN_ACCEPTANCE_REPORT.md"
    text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    checks = [
        _ok("rqs07_report_exists", report_path.exists(), _rel(report_path)),
        _ok("rqs07_gate_pass", "Gate: `PASS`" in text, "Gate: PASS"),
        _ok("rqs07_no_failures", "- Failures: `0`" in text, "Failures 0"),
        _ok("rqs07_no_blocking", "- Blocking: `0`" in text, "Blocking 0"),
        _ok("rqs07_no_low_score_delivery", "- Score >= 60: `48/48`" in text, "Score >=60 48/48"),
        _ok(
            "rqs07_titles_clean",
            "- Title issues after delivery sanitize: `0`" in text,
            "title issues 0",
        ),
        _ok(
            "rqs07_shadow_clean_current_set",
            "- Artifact set hard block count: `0`" in text,
            "shadow hard block 0",
        ),
    ]
    for domain in REQUIRED_DOMAINS:
        checks.append(_ok(f"rqs07_domain_{domain}", f"| {domain} |" in text, domain))
    return checks


def check_ci_and_deployment_config() -> list[dict[str, Any]]:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    requirements_api = (MODEL_DIR / "requirements-api.txt").read_text(encoding="utf-8")
    requirements_worker = (MODEL_DIR / "requirements-worker.txt").read_text(encoding="utf-8")
    requirements_compat = (MODEL_DIR / "requirements.txt").read_text(encoding="utf-8")
    api_requirement_lines = [
        line.strip()
        for line in requirements_api.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    env_example = (MODEL_DIR / ".env.example").read_text(encoding="utf-8")
    deploy_secrets = (ROOT / "docs" / "DEPLOYMENT_SECRETS.md").read_text(encoding="utf-8")
    cloud_strategy = (ROOT / "docs" / "MODEL_ARTIFACT_CLOUD_STRATEGY.md").read_text(encoding="utf-8")
    timing_strategy = (ROOT / "docs" / "MARKET_TIMING_CLOUD_PIPELINE.md").read_text(encoding="utf-8")
    image_build_spec = (ROOT / "docs" / "PRODUCTION_IMAGE_BUILD_SPEC.md").read_text(encoding="utf-8")
    fact_enrichment = (MODEL_DIR / "fact_enrichment.py").read_text(encoding="utf-8")
    api_source = (MODEL_DIR / "api.py").read_text(encoding="utf-8")
    api_readiness_source = api_source.split("def _readiness_payload()", 1)[1].split('@app.get("/health/live")', 1)[0]
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    render_blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")
    entrypoint = (ROOT / "scripts" / "docker_entrypoint.sh").read_text(encoding="utf-8")
    entrypoint_semantic_passed, entrypoint_semantic_detail = _check_entrypoint_runtime_contract(entrypoint)
    api_runtime_stage = dockerfile.split("FROM runtime-common AS api-runtime", 1)[1].split(
        "FROM runtime-common AS worker-runtime", 1
    )[0]
    worker_runtime_stage = dockerfile.split("FROM runtime-common AS worker-runtime", 1)[1].split(
        "FROM ${NOTEAI_RUNTIME_TARGET} AS noteai-runtime", 1
    )[0]
    service_start_sources = "\n".join(
        (ROOT / "scripts" / name).read_text(encoding="utf-8")
        for name in (
            "render_start_api.sh",
            "render_start_admin.sh",
            "render_run_market_timing.sh",
            "render_run_crawler.sh",
        )
    )
    db_source = (MODEL_DIR / "db.py").read_text(encoding="utf-8")
    init_db_source = db_source.split("def init_db()", 1)[1].split("def database_health", 1)[0]

    checks = [
        _ok("ci_runs_tests", "python -m unittest discover -s tests -p 'test_*.py'" in workflow),
        _ok("ci_checks_model_artifacts", "scripts/fetch_model_artifacts.py --check-only --required" in workflow),
        _ok("ci_runs_quality_gate", "tools/quality_gate.py quality/golden_notes.sample.json" in workflow),
        _ok("ci_runs_production_readiness_gate", "tools/production_readiness_gate.py" in workflow),
        _ok("ci_checks_docker_compose", "docker compose config --quiet" in workflow),
        _ok("dependabot_configured", "package-ecosystem: \"pip\"" in dependabot and "github-actions" in dependabot),
        _ok("docker_uses_artifact_entrypoint", "ENTRYPOINT [\"/app/scripts/docker_entrypoint.sh\"]" in dockerfile),
        _ok("docker_copies_entrypoint", "COPY scripts/docker_entrypoint.sh" in dockerfile),
        _ok(
            "docker_has_separate_api_and_worker_targets",
            "FROM runtime-common AS api-runtime" in dockerfile
            and "FROM runtime-common AS worker-runtime" in dockerfile
            and "ARG NOTEAI_RUNTIME_TARGET=api-runtime" in dockerfile
            and "FROM ${NOTEAI_RUNTIME_TARGET} AS noteai-runtime" in dockerfile
            and 'CMD ["/app/scripts/render_start_api.sh"]' in api_runtime_stage
            and 'CMD ["/bin/false"]' in worker_runtime_stage,
        ),
        _ok(
            "api_runtime_excludes_browser_and_graphics_stack",
            "playwright" not in api_runtime_stage.lower()
            and "chromium" not in api_runtime_stage.lower()
            and "playwright==" not in requirements_api
            and all(package not in dockerfile for package in ("libgl1", "libglib2.0-0", "libsm6", "libxext6", "libxrender1")),
        ),
        _ok(
            "worker_runtime_installs_playwright_chromium",
            "playwright==1.56.0" in requirements_worker
            and "python -m playwright install --with-deps chromium" in worker_runtime_stage,
        ),
        _ok(
            "docker_proves_headless_chromium_without_xvfb",
            "apt-get purge -y xvfb xserver-common" in worker_runtime_stage
            and 'page.goto("about:blank")' in worker_runtime_stage,
        ),
        _ok(
            "docker_removes_python_build_tooling",
            "python -m pip uninstall -y setuptools wheel" in dockerfile
            and "python -m pip check" in dockerfile,
        ),
        _ok(
            "docker_healthcheck_uses_python_stdlib",
            'import http.client, os, sys' in dockerfile
            and "'/health/live'" in dockerfile
            and "CMD curl" not in dockerfile,
        ),
        _ok(
            "docker_pins_node20_base_index",
            "node:20-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0" in dockerfile,
        ),
        _ok(
            "docker_pins_python311_base_index",
            "python:3.11.15-slim-trixie@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93" in dockerfile
            and "sha256:00af38ae2ed311628970782e8a2d7f014d8909dbc63cb97bc0a158187f4db045" in dockerfile,
        ),
        _ok(
            "docker_declares_oci_provenance_labels",
            all(value in dockerfile for value in (
                "ARG NOTEAI_OCI_REVISION=development",
                "ARG NOTEAI_OCI_SOURCE=https://github.com/iamyusen1314/noteai",
                "ARG NOTEAI_OCI_VERSION=development",
                "ARG NOTEAI_OCI_CREATED=1970-01-01T00:00:00Z",
                "org.opencontainers.image.revision",
                "org.opencontainers.image.source",
                "org.opencontainers.image.version",
                "org.opencontainers.image.created",
            )),
        ),
        _ok("docker_pins_meituan_travel_cli", "MEITUAN_TRAVEL_CLI_VERSION=1.0.16" in dockerfile),
        _ok(
            "docker_verifies_meituan_travel_integrity",
            "sha512-mYwkdd2jzFPKPacMM7CL3aAbfWqxkCh6q1kVi9YhgJoDPw22vAp1JFQrWuWJKzJiBBoYuXnMxzyC8i+f6mXzrA==" in dockerfile,
        ),
        _ok("docker_runtime_has_mttravel_without_npm", "COPY --from=meituan-travel-cli /usr/local/bin/node" in dockerfile and "MEITUAN_TRAVEL_CLI=/usr/local/bin/mttravel" in dockerfile),
        _ok(
            "meituan_runtime_uses_ephemeral_config",
            "TemporaryDirectory(prefix=\"noteai-mttravel-\")" in fact_enrichment
            and "os.O_EXCL, 0o600" in fact_enrichment
            and "home.chmod(0o700)" in fact_enrichment,
        ),
        _ok(
            "meituan_readiness_has_fixed_codes",
            all(code in fact_enrichment for code in (
                "MEITUAN_TRAVEL_READY",
                "MEITUAN_TRAVEL_CLI_MISSING",
                "MEITUAN_TRAVEL_TOKEN_MISSING",
                "MEITUAN_TRAVEL_EXEC_FAILED",
                "MEITUAN_TRAVEL_TIMEOUT",
            )),
        ),
        _ok(
            "api_readiness_is_core_only",
            'checks["database"]' in api_readiness_source
            and 'checks["model"]' in api_readiness_source
            and all(value not in api_readiness_source for value in (
                "claude_transport_readiness",
                "MOONSHOT_API_KEY",
                "meituan_travel_runtime_status",
                "market_readiness",
                "AMAP",
                "billing",
            )),
        ),
        _ok(
            "requirements_are_role_split_and_compatible",
            "playwright==" not in requirements_api
            and "-r requirements-api.txt" in requirements_worker
            and "playwright==1.56.0" in requirements_worker
            and "-r requirements-worker.txt" in requirements_compat
            and all(
                re.fullmatch(r"[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^\s]+", line)
                for line in api_requirement_lines
            ),
        ),
        _ok(
            "compose_runtime_targets_match_roles",
            compose.count("target: api-runtime") == 1
            and compose.count("target: worker-runtime") == 3
            and compose.count("NOTEAI_RUNTIME_ROLE=api") == 1
            and compose.count("NOTEAI_RUNTIME_ROLE=worker") == 3,
        ),
        _ok(
            "render_runtime_targets_match_roles",
            render_blueprint.count("key: NOTEAI_RUNTIME_TARGET") == 4
            and render_blueprint.count("value: api-runtime") == 1
            and render_blueprint.count("value: worker-runtime") == 3
            and render_blueprint.count("key: NOTEAI_RUNTIME_ROLE") == 4
            and len(re.findall(r"^\s*value:\s*api\s*$", render_blueprint, re.MULTILINE)) == 1
            and len(re.findall(r"^\s*value:\s*worker\s*$", render_blueprint, re.MULTILINE)) == 3,
        ),
        _ok(
            "entrypoint_fails_closed_on_runtime_role_marker",
            all(value in entrypoint for value in (
                'if [ ! -e "$runtime_role_file" ]',
                'if [ ! -r "$runtime_role_file" ]',
                'if ! IFS= read -r image_runtime_role < "$runtime_role_file"',
                'if [ -z "$image_runtime_role" ]',
                "runtime role marker is missing",
                "runtime role marker is unreadable",
                "runtime role marker could not be read",
                "runtime role marker is empty",
            ))
            and "declared runtime role does not match the image role" in entrypoint
            and _fragments_in_order(entrypoint, (
                'if [ ! -e "$runtime_role_file" ]',
                "command_allowed=0",
                'if [ "$command_allowed" -ne 1 ]',
                "cd /app/model",
                "python -m artifact_loader",
            )),
        ),
        _ok(
            "entrypoint_uses_strict_role_command_allowlists",
            "command_allowed=0" in entrypoint
            and "command_allowed=1" in entrypoint
            and "command is not allowed for this runtime role" in entrypoint
            and "api-runtime cannot start the trend scheduler" in entrypoint
            and "is_unsigned_integer" in entrypoint
            and "*[!0-9]*" in entrypoint
            and all(value in entrypoint for value in (
                "/app/scripts/render_start_api.sh",
                "/app/scripts/render_start_admin.sh",
                "/app/scripts/render_run_market_timing.sh",
                "/app/scripts/render_run_crawler.sh",
                "/app/scripts/render_predeploy.py",
                "admin_server:admin_app",
                "market_timing_worker.py",
                "crawler_worker.py",
                "/bin/false",
            ))
            and 'case " $* "' not in entrypoint
            and "api-runtime cannot start a browser worker command" not in entrypoint
            and "worker-runtime cannot start the public API command" not in entrypoint,
        ),
        _ok(
            "entrypoint_runtime_contract_semantics",
            entrypoint_semantic_passed,
            entrypoint_semantic_detail,
        ),
        _ok("compose_has_trends_worker", "noteai-trends-worker:" in compose and "market_timing_worker.py" in compose),
        _ok("entrypoint_can_skip_model_for_worker", "NOTEAI_SKIP_MODEL_ARTIFACT_CHECK" in entrypoint),
        _ok("compose_shares_artifacts", "./model/artifacts:/app/model/artifacts" in compose),
        _ok(
            "compose_uses_core_readiness",
            "noteai-admin:" in compose
            and compose.count("import http.client, sys") == 2
            and "HTTPConnection('127.0.0.1', 8000" in compose
            and "HTTPConnection('127.0.0.1', 8001" in compose
            and compose.count("'/health/ready'") == 2
            and '"curl"' not in compose,
        ),
        _ok(
            "postgres_migrations_are_predeploy_only",
            "apply_postgres_migrations()" not in init_db_source
            and "render_predeploy.py" not in service_start_sources
            and "NOTEAI_MIGRATE_ON_START" not in service_start_sources
            and render_blueprint.count("preDeployCommand: python /app/scripts/render_predeploy.py") == 2,
        ),
        _ok(
            "docker_context_blocks_sensitive_material",
            all(pattern in dockerignore for pattern in (
                "**/.env.*",
                "**/.ssh",
                "**/.aws",
                "**/.docker/config.json",
                "**/*.pem",
                "**/*.key",
                "**/*credentials*.json",
                "**/*cookie*.json",
                "**/*secret*.json",
            )),
        ),
        _ok("deployment_secrets_doc_exists", "GitHub Environment" in deploy_secrets),
        _ok("model_cloud_strategy_doc_exists", "NOTEAI_MODEL_ARTIFACT_BASE_URL" in cloud_strategy),
        _ok("market_timing_cloud_strategy_doc_exists", "NOTEAI_MARKET_TIMING_REQUIRED=1" in timing_strategy),
        _ok("market_timing_baseline_evidence_documented", "industry_baseline" in timing_strategy),
        _ok(
            "production_image_build_spec_exists",
            "linux/amd64" in image_build_spec
            and "org.opencontainers.image.revision" in image_build_spec
            and "Before any push" in image_build_spec,
        ),
    ]
    missing_env = [name for name in sorted(REQUIRED_ENV_NAMES) if name not in env_example]
    checks.append(_ok("env_example_contains_required_names", not missing_env, f"missing={missing_env}"))
    return checks


def check_optional_runtime_dependencies() -> list[dict[str, Any]]:
    cloud_runtime = os.environ.get("NOTEAI_CLOUD_RUNTIME", "0").strip().lower() in {"1", "true", "yes", "on"}
    if not cloud_runtime:
        return [_ok(
            "meituan_travel_runtime_dependency",
            True,
            "deferred: NOTEAI_CLOUD_RUNTIME is not enabled",
        )]

    import fact_enrichment as facts  # noqa: PLC0415

    status = facts.meituan_travel_runtime_status()
    passed = not status.get("required") or bool(status.get("ok"))
    return [_ok(
        "meituan_travel_runtime_dependency",
        passed,
        str(status.get("status_code") or "MEITUAN_TRAVEL_STATUS_UNKNOWN"),
    )]


def _line_has_secret_value(line: str) -> tuple[bool, str]:
    match = SECRET_NAME_RE.search(line)
    if not match:
        return False, ""
    name, value = match.groups()
    raw_value = value.strip().strip("'\"")
    if name.startswith("_") or name.startswith("SAFE_") or name.endswith("_RE"):
        return False, ""
    if raw_value.startswith("${{"):
        return False, ""
    if raw_value.startswith("$"):
        return False, ""
    if "{" in raw_value or "}" in raw_value:
        return False, ""
    if raw_value.startswith(("re.compile(", "os.environ.get(", "int(", "str(")):
        return False, ""
    if re.fullmatch(r"\d+(?:\s*[*+-]\s*\d+)*", raw_value):
        return False, ""
    if raw_value.lower() in SAFE_SECRET_VALUES:
        return False, ""
    if raw_value.startswith("<") and raw_value.endswith(">"):
        return False, ""
    if raw_value.startswith("http") and "example" in raw_value:
        return False, ""
    if not raw_value:
        return False, ""
    return True, name


def check_git_hygiene() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    tracked = _run_git(["ls-files", "-z"]).stdout.split("\0")
    tracked = [path for path in tracked if path]

    forbidden_exact = {"model/.env", ".env"}
    forbidden_prefixes = (
        ".venv/",
        "node_modules/",
        "model/mlruns/",
        "model/data/RedNote-Vibe-Dataset/",
        "model/data/rednote_vibe_raw/",
        "model/data/covers/",
        "model/data/covers_v2/",
        "quality/generated_variants/",
    )
    forbidden_tracked = [
        path
        for path in tracked
        if path in forbidden_exact or any(path.startswith(prefix) for prefix in forbidden_prefixes)
    ]
    checks.append(_ok("forbidden_paths_not_tracked", not forbidden_tracked, ", ".join(forbidden_tracked[:10])))

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    gitattributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    checks.extend([
        _ok("gitignore_blocks_env", "model/.env" in gitignore and "*.env" in gitignore),
        _ok("gitignore_blocks_generated_variants", "quality/generated_variants/" in gitignore),
        _ok("git_lfs_tracks_model_binaries", "*.lgb filter=lfs" in gitattributes),
    ])

    secret_hits = []
    binary_suffixes = {".lgb", ".png", ".jpg", ".jpeg", ".pdf", ".docx", ".pptx", ".xlsx"}
    skip_names = {"model/.env.example"}
    for raw_path in tracked:
        if raw_path in skip_names:
            continue
        path = ROOT / raw_path
        if path.suffix.lower() in binary_suffixes or not path.exists() or path.stat().st_size > 2_000_000:
            continue
        try:
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                has_secret, name = _line_has_secret_value(line)
                if has_secret:
                    secret_hits.append(f"{raw_path}:{lineno}:{name}")
                    break
        except UnicodeDecodeError:
            continue
    checks.append(_ok("tracked_files_no_obvious_secret_values", not secret_hits, ", ".join(secret_hits[:10])))

    entrypoint = ROOT / "scripts" / "docker_entrypoint.sh"
    checks.append(_ok("docker_entrypoint_exists", entrypoint.exists() and entrypoint.stat().st_size > 0, _rel(entrypoint)))
    return checks


def build_report() -> dict[str, Any]:
    sections = {
        "model_release": check_model_release(),
        "quality_evidence": check_quality_evidence(),
        "ci_and_deployment_config": check_ci_and_deployment_config(),
        "optional_runtime_dependencies": check_optional_runtime_dependencies(),
        "git_hygiene": check_git_hygiene(),
    }
    all_checks = [check for checks in sections.values() for check in checks]
    failed = [check for check in all_checks if not check["passed"]]
    return {
        "version": "production-readiness-gate-v0.1",
        "passed": not failed,
        "failed_count": len(failed),
        "check_count": len(all_checks),
        "sections": sections,
        "failed_checks": failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NoteAI production readiness checks.")
    parser.add_argument("--json", action="store_true", help="Print full JSON report.")
    args = parser.parse_args()

    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"production_readiness={'PASS' if report['passed'] else 'FAIL'}")
        print(f"checks={report['check_count']} failed={report['failed_count']}")
        for item in report["failed_checks"]:
            print(f"- {item['name']}: {item['detail']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
