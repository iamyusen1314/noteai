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
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from artifact_loader import ensure_model_artifacts, sha256_file  # noqa: E402


REQUIRED_MODEL_ROLES = {"quality_regressor", "ready_classifier", "preference_ranker", "train_report"}
REQUIRED_ENV_NAMES = {
    "ANTHROPIC_API_KEY",
    "MOONSHOT_API_KEY",
    "ADMIN_PASSWORD",
    "NOTEAI_ENABLE_TEST_BILLING",
    "NOTEAI_USE_V04_COMPOSITE",
    "NOTEAI_MODEL_ARTIFACT_REQUIRED",
    "NOTEAI_MODEL_ARTIFACT_BASE_URL",
    "NOTEAI_FACT_SEARCH",
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


def _ok(name: str, passed: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


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
    env_example = (MODEL_DIR / ".env.example").read_text(encoding="utf-8")
    deploy_secrets = (ROOT / "docs" / "DEPLOYMENT_SECRETS.md").read_text(encoding="utf-8")
    cloud_strategy = (ROOT / "docs" / "MODEL_ARTIFACT_CLOUD_STRATEGY.md").read_text(encoding="utf-8")

    checks = [
        _ok("ci_runs_tests", "python -m unittest discover -s tests -p 'test_*.py'" in workflow),
        _ok("ci_checks_model_artifacts", "scripts/fetch_model_artifacts.py --check-only --required" in workflow),
        _ok("ci_runs_quality_gate", "tools/quality_gate.py quality/golden_notes.sample.json" in workflow),
        _ok("ci_runs_production_readiness_gate", "tools/production_readiness_gate.py" in workflow),
        _ok("ci_checks_docker_compose", "docker compose config --quiet" in workflow),
        _ok("dependabot_configured", "package-ecosystem: \"pip\"" in dependabot and "github-actions" in dependabot),
        _ok("docker_uses_artifact_entrypoint", "ENTRYPOINT [\"/app/scripts/docker_entrypoint.sh\"]" in dockerfile),
        _ok("docker_copies_entrypoint", "COPY scripts/docker_entrypoint.sh" in dockerfile),
        _ok("compose_shares_artifacts", "./model/artifacts:/app/model/artifacts" in compose),
        _ok("compose_has_admin_service", "noteai-admin:" in compose and "/admin/health" in compose),
        _ok("deployment_secrets_doc_exists", "GitHub Environment" in deploy_secrets),
        _ok("model_cloud_strategy_doc_exists", "NOTEAI_MODEL_ARTIFACT_BASE_URL" in cloud_strategy),
    ]
    missing_env = [name for name in sorted(REQUIRED_ENV_NAMES) if name not in env_example]
    checks.append(_ok("env_example_contains_required_names", not missing_env, f"missing={missing_env}"))
    return checks


def _line_has_secret_value(line: str) -> tuple[bool, str]:
    match = SECRET_NAME_RE.search(line)
    if not match:
        return False, ""
    name, value = match.groups()
    raw_value = value.strip().strip("'\"")
    if name.startswith("_"):
        return False, ""
    if raw_value.startswith("${{"):
        return False, ""
    if raw_value.startswith("$"):
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
