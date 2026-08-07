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
import hashlib
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
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from artifact_loader import ensure_model_artifacts, sha256_file  # noqa: E402
from verify_browserless_vex import validate_bundle as validate_browserless_vex_bundle  # noqa: E402
from verify_b55_native_release_vex import (  # noqa: E402
    validate_bundle as validate_b55_native_release_vex_bundle,
)
from verify_cad5ce3_native_release_vex import (  # noqa: E402
    validate_bundle as validate_cad5ce3_native_release_vex_bundle,
)
from verify_b55_registry_release_vex import (  # noqa: E402
    validate_bundle as validate_b55_registry_release_vex_bundle,
)
from verify_5335_admin_native_release_vex import (  # noqa: E402
    validate_bundle as validate_5335_admin_native_release_vex_bundle,
)
from verify_admin_private_publication_attempt_evidence import (  # noqa: E402
    validate_evidence as validate_admin_private_publication_attempt_evidence,
)
from verify_admin_private_publication_attempt_evidence import (  # noqa: E402
    load_evidence as load_admin_private_publication_attempt_evidence,
)
from verify_admin_dependency_cache_export_plan import (  # noqa: E402
    plan_state as admin_dependency_cache_plan_state,
)
from verify_admin_dependency_cache_export_plan import (  # noqa: E402
    validate_plan as validate_admin_dependency_cache_export_plan,
)
from verify_admin_dependency_cache_export_plan_v3 import (  # noqa: E402
    plan_state as admin_dependency_cache_plan_state_v3,
)
from verify_admin_dependency_cache_export_plan_v3 import (  # noqa: E402
    validate_plan as validate_admin_dependency_cache_export_plan_v3,
)
from verify_admin_dependency_cache_export_plan_v4 import (  # noqa: E402
    plan_state as admin_dependency_cache_plan_state_v4,
)
from verify_admin_dependency_cache_export_plan_v4 import (  # noqa: E402
    validate_plan as validate_admin_dependency_cache_export_plan_v4,
)
from verify_admin_dependency_cache_export_plan_v5 import (  # noqa: E402
    plan_state as admin_dependency_cache_plan_state_v5,
)
from verify_admin_dependency_cache_export_plan_v5 import (  # noqa: E402
    validate_plan as validate_admin_dependency_cache_export_plan_v5,
)
from verify_admin_dependency_cache_export_plan_v6 import (  # noqa: E402
    plan_state as admin_dependency_cache_plan_state_v6,
)
from verify_admin_dependency_cache_export_plan_v6 import (  # noqa: E402
    validate_plan as validate_admin_dependency_cache_export_plan_v6,
)
from verify_admin_dependency_cache_export_plan_v7 import (  # noqa: E402
    plan_state as admin_dependency_cache_plan_state_v7,
)
from verify_admin_dependency_cache_export_plan_v7 import (  # noqa: E402
    validate_plan as validate_admin_dependency_cache_export_plan_v7,
)
from verify_admin_dependency_cache_export_plan_v8 import (  # noqa: E402
    plan_state as admin_dependency_cache_plan_state_v8,
)
from verify_admin_dependency_cache_export_plan_v8 import (  # noqa: E402
    validate_plan as validate_admin_dependency_cache_export_plan_v8,
)
from verify_admin_dependency_cache_export_plan_v9 import (  # noqa: E402
    plan_state as admin_dependency_cache_plan_state_v9,
)
from verify_admin_dependency_cache_export_plan_v9 import (  # noqa: E402
    validate_plan as validate_admin_dependency_cache_export_plan_v9,
)
from verify_admin_dependency_cache_export_plan_v10 import (  # noqa: E402
    plan_state as admin_dependency_cache_plan_state_v10,
)
from verify_admin_dependency_cache_export_plan_v10 import (  # noqa: E402
    validate_plan as validate_admin_dependency_cache_export_plan_v10,
)
from verify_admin_dependency_cache_export_plan_v12 import (  # noqa: E402
    effective_plan_state as admin_dependency_cache_plan_state_v12,
)
from verify_admin_dependency_cache_export_plan_v12 import (  # noqa: E402
    validate_plan as validate_admin_dependency_cache_export_plan_v12,
)
from verify_admin_dependency_cache_export_plan_v12 import (  # noqa: E402
    validate_v11_untriggered_supersession,
)
from verify_admin_dependency_cache_export_plan_v12 import (  # noqa: E402
    v11_untriggered_supersession_state,
)
from verify_admin_dependency_cache_export_plan_v16 import (  # noqa: E402
    _validate_v15_predecessor as validate_admin_dependency_cache_v15_predecessor,
)
from verify_admin_dependency_cache_export_plan_v17 import (  # noqa: E402
    _validate_v16_predecessor as validate_admin_dependency_cache_v16_predecessor,
)
from verify_admin_dependency_cache_v2_failure_evidence import (  # noqa: E402
    load_strict as load_admin_dependency_cache_v2_failure_evidence,
)
from verify_admin_dependency_cache_v2_failure_evidence import (  # noqa: E402
    verify as verify_admin_dependency_cache_v2_failure_evidence,
)
from verify_admin_dependency_cache_v3_failure_evidence import (  # noqa: E402
    load_strict as load_admin_dependency_cache_v3_failure_evidence,
)
from verify_admin_dependency_cache_v3_failure_evidence import (  # noqa: E402
    verify as verify_admin_dependency_cache_v3_failure_evidence,
)
from verify_admin_dependency_cache_v4_failure_evidence import (  # noqa: E402
    load_strict as load_admin_dependency_cache_v4_failure_evidence,
)
from verify_admin_dependency_cache_v4_failure_evidence import (  # noqa: E402
    verify as verify_admin_dependency_cache_v4_failure_evidence,
)
from verify_admin_dependency_cache_v5_failure_evidence import (  # noqa: E402
    load_strict as load_admin_dependency_cache_v5_failure_evidence,
)
from verify_admin_dependency_cache_v5_failure_evidence import (  # noqa: E402
    verify as verify_admin_dependency_cache_v5_failure_evidence,
)
from verify_admin_dependency_cache_v6_failure_evidence import (  # noqa: E402
    load_strict as load_admin_dependency_cache_v6_failure_evidence,
)
from verify_admin_dependency_cache_v6_failure_evidence import (  # noqa: E402
    verify as verify_admin_dependency_cache_v6_failure_evidence,
)
from verify_admin_dependency_cache_v7_failure_evidence import (  # noqa: E402
    load_strict as load_admin_dependency_cache_v7_failure_evidence,
)
from verify_admin_dependency_cache_v7_failure_evidence import (  # noqa: E402
    verify as verify_admin_dependency_cache_v7_failure_evidence,
)
from verify_admin_dependency_cache_v8_failure_evidence import (  # noqa: E402
    load_strict as load_admin_dependency_cache_v8_failure_evidence,
)
from verify_admin_dependency_cache_v8_failure_evidence import (  # noqa: E402
    verify as verify_admin_dependency_cache_v8_failure_evidence,
)
from verify_admin_dependency_cache_v9_failure_evidence import (  # noqa: E402
    load_strict as load_admin_dependency_cache_v9_failure_evidence,
)
from verify_admin_dependency_cache_v9_failure_evidence import (  # noqa: E402
    verify as verify_admin_dependency_cache_v9_failure_evidence,
)
from verify_admin_dependency_cache_v10_failure_evidence import (  # noqa: E402
    load_strict as load_admin_dependency_cache_v10_failure_evidence,
)
from verify_admin_dependency_cache_v10_failure_evidence import (  # noqa: E402
    verify as verify_admin_dependency_cache_v10_failure_evidence,
)
from verify_admin_dependency_cache_v12_failure_evidence import (  # noqa: E402
    load_strict as load_admin_dependency_cache_v12_failure_evidence,
)
from verify_admin_dependency_cache_v12_failure_evidence import (  # noqa: E402
    verify as verify_admin_dependency_cache_v12_failure_evidence,
)
from verify_admin_dependency_cache_v15_failure_evidence import (  # noqa: E402
    load_strict as load_admin_dependency_cache_v15_failure_evidence,
)
from verify_admin_dependency_cache_v15_failure_evidence import (  # noqa: E402
    verify as verify_admin_dependency_cache_v15_failure_evidence,
)
from verify_admin_dependency_cache_v16_failure_evidence import (  # noqa: E402
    load_strict as load_admin_dependency_cache_v16_failure_evidence,
)
from verify_admin_dependency_cache_v16_failure_evidence import (  # noqa: E402
    verify as verify_admin_dependency_cache_v16_failure_evidence,
)
from verify_api_c_current_release_evidence import (  # noqa: E402
    validate_bundle as validate_api_c_current_release_evidence_bundle,
)
from verify_api_f_current_release_evidence import (  # noqa: E402
    validate_bundle as validate_api_f_current_release_evidence_bundle,
)
from verify_admin_current_release_evidence import (  # noqa: E402
    validate_bundle as validate_admin_current_release_evidence_bundle,
)
from verify_native_release_vex import validate_bundle as validate_native_release_vex_bundle  # noqa: E402
from verify_registry_release_vex import (  # noqa: E402
    validate_bundle as validate_registry_release_vex_bundle,
)


REQUIRED_MODEL_ROLES = {"quality_regressor", "ready_classifier", "preference_ranker", "train_report"}
HUMAN_MODEL_RELEASE_MANIFEST = MODEL_DIR / "artifacts" / "MODEL_RELEASE_MANIFEST.md"
PLAYWRIGHT_SECCOMP_PROFILE = ROOT / "deploy" / "security" / "playwright-chromium-seccomp-v1.56.0.json"
PLAYWRIGHT_SECCOMP_SHA256 = "cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849"
PRODUCTION_BROWSER_SOURCES = (
    MODEL_DIR / "crawler.py",
    MODEL_DIR / "download_covers.py",
    MODEL_DIR / "scheduler_a.py",
)
FORBIDDEN_CHROMIUM_FLAGS = (
    "--disable-setuid-sandbox",
    "--no-sandbox",
    "--no-zygote",
)
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
    "buildkit_no_client_token",
}


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compose_service_block(compose: str, service_name: str) -> str:
    marker = f"  {service_name}:\n"
    if marker not in compose:
        return ""
    tail = compose.split(marker, 1)[1]
    match = re.search(r"^  [a-zA-Z0-9_-]+:\s*$", tail, re.MULTILINE)
    return tail[:match.start()] if match else tail


def _compose_services_have_runtime_hardening(
    compose: str,
    service_names: tuple[str, ...],
) -> bool:
    active_compose = "\n".join(
        re.sub(r"\s+#.*$", "", line).rstrip()
        for line in compose.splitlines()
        if re.sub(r"\s+#.*$", "", line).strip()
    )
    required_patterns = (
        r'^    user:\s*["\']999:999["\']\s*$',
        r"^    read_only:\s*true\s*$",
        r"^    privileged:\s*false\s*$",
        r"^    cap_drop:\s*\n      -\s*ALL\s*$",
        r"^    security_opt:\s*\n      -\s*no-new-privileges:true\s*$",
        r"^      -\s*/tmp:rw,noexec,nosuid,nodev,size=(?:64|512)m,"
        r"mode=1777,uid=999,gid=999\s*$",
    )
    forbidden_patterns = (
        r'^\s*privileged:\s*["\']?true["\']?\s*$',
        r"^\s*cap_add\s*:",
        r"^\s*devices\s*:",
        r"^\s*device_cgroup_rules\s*:",
        r'^\s*(?:network_mode|pid|ipc):\s*["\']?host["\']?\s*$',
        r"\bseccomp=unconfined\b",
        r"^\s*-\s*[\"']?(?:SYS_ADMIN|SYS_RAWIO|MKNOD)[\"']?\s*$",
    )
    return (
        all(
            all(
                re.search(
                    pattern,
                    _compose_service_block(active_compose, service),
                    re.MULTILINE,
                )
                for pattern in required_patterns
            )
            for service in service_names
        )
        and not any(
            re.search(pattern, active_compose, re.MULTILINE)
            for pattern in forbidden_patterns
        )
    )


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

    xhs_trends_env = {
        "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
        "NOTEAI_XHS_SERVICE": "trends",
    }
    xhs_tracking_env = {
        "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
        "NOTEAI_XHS_SERVICE": "tracking",
    }
    durable_dispatcher_env = {
        "NOTEAI_DURABLE_AI_COMPONENT": "dispatcher",
    }
    durable_worker_env = {
        "NOTEAI_DURABLE_AI_COMPONENT": "worker",
    }
    durable_dispatcher_acceptance_env = {
        **durable_dispatcher_env,
        "NOTEAI_DURABLE_AI_SUSPENDED": "0",
        "NOTEAI_DURABLE_AI_ACCEPTANCE_MODE": "1",
        "NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID": (
            "00000000-0000-4000-8000-000000000017"
        ),
    }
    durable_acceptance_env = {
        **durable_worker_env,
        "NOTEAI_DURABLE_AI_SUSPENDED": "0",
        "NOTEAI_DURABLE_AI_PROCESSOR": "internal-acceptance-v1",
        "NOTEAI_DURABLE_AI_ACCEPTANCE_MODE": "1",
        "NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID": (
            "00000000-0000-4000-8000-000000000017"
        ),
        "NOTEAI_DURABLE_AI_ACCEPTANCE_ACTION": "fail_before_provider",
    }
    allowed_cases = {
        "api_start": ("api", ("/app/scripts/render_start_api.sh",), {}),
        "api_predeploy": ("api", ("python", "/app/scripts/render_predeploy.py"), {}),
        "admin_start": ("admin", ("/app/scripts/render_start_admin.sh",), {}),
        "admin_compose": (
            "admin",
            ("python", "-m", "uvicorn", "admin_server:admin_app", "--host", "0.0.0.0", "--port", "8001"),
            {},
        ),
        "payment_start": (
            "payment",
            ("/app/scripts/render_start_payment.sh",),
            {},
        ),
        "ai_worker_health": (
            "ai-worker",
            ("python", "durable_ai_worker.py", "--healthcheck"),
            {},
        ),
        "ai_worker_once_suspended": (
            "ai-worker",
            ("python", "durable_ai_worker.py", "--once"),
            {},
        ),
        "ai_worker_recover_unstarted": (
            "ai-worker",
            ("python", "durable_ai_worker.py", "--recover-unstarted"),
            {},
        ),
        "ai_worker_reconcile_stale": (
            "ai-worker",
            ("python", "durable_ai_worker.py", "--reconcile-stale"),
            {},
        ),
        "ai_dispatcher_health": (
            "ai-worker",
            ("python", "durable_ai_worker.py", "--healthcheck"),
            durable_dispatcher_env,
        ),
        "ai_dispatcher_once": (
            "ai-worker",
            ("python", "durable_ai_worker.py", "--dispatcher-once"),
            durable_dispatcher_env,
        ),
        "ai_dispatcher_loop": (
            "ai-worker",
            ("python", "durable_ai_worker.py", "--dispatcher-loop"),
            durable_dispatcher_env,
        ),
        "ai_dispatcher_internal_acceptance_once": (
            "ai-worker",
            ("python", "durable_ai_worker.py", "--dispatcher-once"),
            durable_dispatcher_acceptance_env,
        ),
        "ai_worker_component_health": (
            "ai-worker",
            ("python", "durable_ai_worker.py", "--healthcheck"),
            durable_worker_env,
        ),
        "ai_worker_component_once": (
            "ai-worker",
            ("python", "durable_ai_worker.py", "--worker-once"),
            durable_worker_env,
        ),
        "ai_worker_component_loop": (
            "ai-worker",
            ("python", "durable_ai_worker.py", "--worker-loop"),
            durable_worker_env,
        ),
        "ai_worker_internal_acceptance_once": (
            "ai-worker",
            ("python", "durable_ai_worker.py", "--worker-once"),
            durable_acceptance_env,
        ),
        "xhs_market_wrapper": ("xhs-http", ("/app/scripts/render_run_market_timing.sh",), xhs_trends_env),
        "xhs_crawler_wrapper": ("xhs-http", ("/app/scripts/render_run_crawler.sh",), xhs_tracking_env),
        "xhs_market_bare": ("xhs-http", ("python", "market_timing_worker.py"), xhs_trends_env),
        "xhs_market_once": ("xhs-http", ("python", "market_timing_worker.py", "--once"), xhs_trends_env),
        "xhs_market_daemon": (
            "xhs-http",
            ("python", "market_timing_worker.py", "--daemon", "--interval", "60"),
            xhs_trends_env,
        ),
        "xhs_market_health": ("xhs-http", ("python", "market_timing_worker.py", "--healthcheck"), xhs_trends_env),
        "xhs_market_ack": ("xhs-http", ("python", "market_timing_worker.py", "--acknowledge-unknown"), xhs_trends_env),
        "xhs_market_clear": ("xhs-http", ("python", "market_timing_worker.py", "--clear-session-block"), xhs_trends_env),
        "xhs_crawler_bare": ("xhs-http", ("python", "crawler_worker.py"), xhs_tracking_env),
        "xhs_crawler_once": ("xhs-http", ("python", "crawler_worker.py", "--once"), xhs_tracking_env),
        "xhs_crawler_health": ("xhs-http", ("python", "crawler_worker.py", "--healthcheck"), xhs_tracking_env),
        "xhs_crawler_loop": (
            "xhs-http",
            ("python", "crawler_worker.py", "--loop", "--interval-minutes", "60", "--limit", "50"),
            xhs_tracking_env,
        ),
        "xhs_fail_closed_default": ("xhs-http", ("/bin/false",), xhs_trends_env),
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
        "admin_api_start": ("admin", ("/app/scripts/render_start_api.sh",)),
        "admin_crawler": ("admin", ("/app/scripts/render_run_crawler.sh",)),
        "admin_predeploy": ("admin", ("python", "/app/scripts/render_predeploy.py")),
        "payment_empty": ("payment", ()),
        "payment_api_start": ("payment", ("/app/scripts/render_start_api.sh",)),
        "payment_admin_start": (
            "payment",
            ("/app/scripts/render_start_admin.sh",),
        ),
        "payment_direct_uvicorn": (
            "payment",
            ("python", "-m", "uvicorn", "payment_runtime:app"),
        ),
        "payment_start_extra": (
            "payment",
            ("/app/scripts/render_start_payment.sh", "extra"),
        ),
        "ai_worker_empty": ("ai-worker", ()),
        "ai_worker_api": ("ai-worker", ("python", "api.py")),
        "ai_worker_bare": ("ai-worker", ("python", "durable_ai_worker.py")),
        "ai_worker_extra": (
            "ai-worker",
            ("python", "durable_ai_worker.py", "--once", "extra"),
        ),
        "ai_worker_shell": (
            "ai-worker",
            ("sh", "-c", "python durable_ai_worker.py --once"),
        ),
        "xhs_api_start": ("xhs-http", ("/app/scripts/render_start_api.sh",)),
        "xhs_admin_start": ("xhs-http", ("/app/scripts/render_start_admin.sh",)),
        "xhs_predeploy": ("xhs-http", ("python", "/app/scripts/render_predeploy.py")),
        "xhs_direct_api": (
            "xhs-http",
            ("python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"),
        ),
        "xhs_api_file": ("xhs-http", ("python", "api.py")),
        "xhs_absolute_api": ("xhs-http", ("python", "/app/model/api.py")),
        "xhs_module_worker": ("xhs-http", ("python", "-m", "crawler_worker")),
        "xhs_absolute_worker": ("xhs-http", ("python", "/app/model/crawler_worker.py")),
        "xhs_shell_wrapper": ("xhs-http", ("sh", "-c", "/app/scripts/render_run_crawler.sh")),
        "xhs_wrapper_extra": ("xhs-http", ("/app/scripts/render_run_crawler.sh", "extra")),
        "xhs_false_extra": ("xhs-http", ("/bin/false", "extra")),
        "xhs_unknown_python": ("xhs-http", ("python", "-c", "import api")),
        "xhs_market_negative": (
            "xhs-http",
            ("python", "market_timing_worker.py", "--daemon", "--interval", "-1"),
        ),
        "xhs_market_empty": (
            "xhs-http",
            ("python", "market_timing_worker.py", "--daemon", "--interval", ""),
        ),
        "xhs_market_non_numeric": (
            "xhs-http",
            ("python", "market_timing_worker.py", "--daemon", "--interval", "api:app"),
        ),
        "xhs_crawler_negative": (
            "xhs-http",
            ("python", "crawler_worker.py", "--loop", "--interval-minutes", "-1", "--limit", "50"),
        ),
        "xhs_crawler_empty": (
            "xhs-http",
            ("python", "crawler_worker.py", "--loop", "--interval-minutes", "60", "--limit", ""),
        ),
        "xhs_crawler_non_numeric": (
            "xhs-http",
            ("python", "crawler_worker.py", "--loop", "--interval-minutes", "api.py", "--limit", "50"),
        ),
    }
    marker_cases = {
        "marker_missing": ("missing", "api", "api"),
        "marker_unreadable": ("unreadable", "api", "api"),
        "marker_empty": ("empty", "api", "api"),
        "marker_read_failure": ("read_failure", "api", "api"),
        "marker_invalid": ("valid", "invalid", "invalid"),
        "marker_role_mismatch": ("valid", "api", "admin"),
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

        for name, (role, command, case_env) in allowed_cases.items():
            run_case(name, role, role, command, allowed=True, extra_env=case_env)
        for name, (role, command) in rejected_command_cases.items():
            run_case(
                name,
                role,
                role,
                command,
                allowed=False,
                extra_env=xhs_tracking_env if role == "xhs-http" else None,
            )
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
        run_case(
            "xhs_wrong_adapter",
            "xhs-http",
            "xhs-http",
            ("/app/scripts/render_run_crawler.sh",),
            allowed=False,
            extra_env={
                "NOTEAI_XHS_ACQUISITION_ADAPTER": "",
                "NOTEAI_XHS_SERVICE": "tracking",
            },
        )
        run_case(
            "xhs_missing_service",
            "xhs-http",
            "xhs-http",
            ("/bin/false",),
            allowed=False,
            extra_env={
                "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
            },
        )
        run_case(
            "xhs_cross_service_command",
            "xhs-http",
            "xhs-http",
            ("python", "crawler_worker.py", "--once"),
            allowed=False,
            extra_env=xhs_trends_env,
        )
        run_case(
            "ai_dispatcher_rejects_worker_loop",
            "ai-worker",
            "ai-worker",
            ("python", "durable_ai_worker.py", "--worker-loop"),
            allowed=False,
            extra_env=durable_dispatcher_env,
        )
        run_case(
            "ai_worker_rejects_dispatcher_loop",
            "ai-worker",
            "ai-worker",
            ("python", "durable_ai_worker.py", "--dispatcher-loop"),
            allowed=False,
            extra_env=durable_worker_env,
        )
        run_case(
            "ai_worker_rejects_invalid_component",
            "ai-worker",
            "ai-worker",
            ("python", "durable_ai_worker.py", "--healthcheck"),
            allowed=False,
            extra_env={"NOTEAI_DURABLE_AI_COMPONENT": "combined"},
        )
        run_case(
            "ai_dispatcher_rejects_private_storage",
            "ai-worker",
            "ai-worker",
            ("python", "durable_ai_worker.py", "--healthcheck"),
            allowed=False,
            extra_env={
                **durable_dispatcher_env,
                "NOTEAI_PRIVATE_STORAGE_BACKEND": "",
            },
        )
        run_case(
            "ai_acceptance_rejects_worker_loop",
            "ai-worker",
            "ai-worker",
            ("python", "durable_ai_worker.py", "--worker-loop"),
            allowed=False,
            extra_env=durable_acceptance_env,
        )
        run_case(
            "ai_acceptance_rejects_malformed_uuid",
            "ai-worker",
            "ai-worker",
            ("python", "durable_ai_worker.py", "--worker-once"),
            allowed=False,
            extra_env={
                **durable_acceptance_env,
                "NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID": "not-a-uuid",
            },
        )
        run_case(
            "ai_dispatcher_acceptance_rejects_loop",
            "ai-worker",
            "ai-worker",
            ("python", "durable_ai_worker.py", "--dispatcher-loop"),
            allowed=False,
            extra_env=durable_dispatcher_acceptance_env,
        )
        run_case(
            "ai_dispatcher_acceptance_rejects_malformed_uuid",
            "ai-worker",
            "ai-worker",
            ("python", "durable_ai_worker.py", "--dispatcher-once"),
            allowed=False,
            extra_env={
                **durable_dispatcher_acceptance_env,
                "NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID": "not-a-uuid",
            },
        )

    detail = f"allowed={len(allowed_cases)} rejected={len(rejected_command_cases) + len(marker_cases) + 12}"
    if failures:
        detail += f" failures={failures[:8]}"
    return not failures, detail


V16_TERMINAL_FAILURE_STATES = frozenset(
    {
        "V16_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_SUPERSESSION_EXACT",
        "V16_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_RECEIPT_EXACT",
    }
)


def _v16_terminal_failure_evidence_accepted(
    state: str,
    errors: list[str],
) -> bool:
    return state in V16_TERMINAL_FAILURE_STATES and not errors


def _v16_terminal_failure_evidence_detail(
    state: str,
    errors: list[str],
) -> str:
    if errors:
        return "; ".join(errors[:5])
    if state not in V16_TERMINAL_FAILURE_STATES:
        return f"V16 terminal failure evidence is not active: state={state}"
    return (
        "unique run 30739167701/job 91473336858 attempt 1 failed "
        "closed after the producer Git SourceOp lifecycle assertion; "
        "consumer import, external-cache-removed same-consumer-builder "
        "replay and upload were not reached, portability remains "
        "UNKNOWN_NOT_REACHED, artifact/download/transfer/production "
        "mutations are zero, cleanup was effective with post-state "
        "parity but overall failed closed on pre-state drift, and V16 "
        "rerun is forbidden"
    )


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


CI_UNIT_TEST_CONTRACT = """      - name: Unit tests
        shell: bash
        run: |
          set -euo pipefail
          mapfile -t ambient_test_files < <(
            find tests -maxdepth 1 -type f -name 'test_*.py' \\
              ! -name 'test_admin_dependency_cache_export_plan_v13.py' \\
              ! -name 'test_admin_dependency_cache_export_plan_v14.py' \\
              ! -name 'test_admin_dependency_cache_export_plan_v15.py' \\
              ! -name 'test_admin_dependency_cache_v15_failure_evidence.py' \\
              ! -name 'test_admin_dependency_cache_export_plan_v16.py' \\
              ! -name 'test_admin_dependency_cache_v16_failure_evidence.py' \\
              -print | LC_ALL=C sort
          )
          test "${#ambient_test_files[@]}" -gt 0
          python -m unittest "${ambient_test_files[@]}"
          python -m unittest \\
            tests.test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_reviewed_authorities_validate_without_git_state \\
            tests.test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_template_fail_closed_matrix \\
            tests.test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_workflow_fail_closed_matrix \\
            tests.test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_strict_json_rejects_duplicate_noncanonical_and_nonfinite \\
            tests.test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_plan_state_classifier \\
            tests.test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_live_ledger_pre_and_post_cleanup_snapshots \\
            tests.test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_live_ledger_rejects_history_and_current_drift \\
            tests.test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_live_ledger_contract_copy_requires_private_mode \\
            tests.test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_pagination_rejects_duplicate_and_incomplete_pages \\
            tests.test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_python_optimized_mode_has_no_assert_contract
          env \\
            -u GITHUB_ACTIONS \\
            -u GITHUB_SHA \\
            -u GITHUB_EVENT_NAME \\
            -u GITHUB_REF \\
            python -m unittest \\
              tests.test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_exact_checkpoint_receipt_and_activation_git_history
          historical_v14_root="$(mktemp -d "${RUNNER_TEMP:-/tmp}/noteai-v14-history.XXXXXX")"
          git clone --quiet --no-hardlinks . "${historical_v14_root}/repo"
          git -C "${historical_v14_root}/repo" checkout --quiet --detach \\
            e18d24a204c33127a95fe3035b7fce43bdb0b4f8
          (
            cd "${historical_v14_root}/repo"
            env \\
              -u GITHUB_ACTIONS \\
              -u GITHUB_SHA \\
              -u GITHUB_EVENT_NAME \\
              -u GITHUB_REF \\
              python -m unittest \\
                tests/test_admin_dependency_cache_export_plan_v14.py
          )
          historical_v15_root="$(mktemp -d "${RUNNER_TEMP:-/tmp}/noteai-v15-history.XXXXXX")"
          git clone --quiet --no-hardlinks . "${historical_v15_root}/repo"
          git -C "${historical_v15_root}/repo" checkout --quiet --detach \\
            a94ee2b2feb81eafbcb523be2c95da4ee952cbc4
          (
            cd "${historical_v15_root}/repo"
            env \\
              -u GITHUB_ACTIONS \\
              -u GITHUB_SHA \\
              -u GITHUB_EVENT_NAME \\
              -u GITHUB_REF \\
              python -m unittest \\
                tests/test_admin_dependency_cache_export_plan_v15.py \\
                tests/test_admin_dependency_cache_v15_failure_evidence.py
          )
          historical_v16_root="$(mktemp -d "${RUNNER_TEMP:-/tmp}/noteai-v16-history.XXXXXX")"
          git clone --quiet --no-hardlinks . "${historical_v16_root}/repo"
          git -C "${historical_v16_root}/repo" checkout --quiet --detach \\
            751da973dd7136d792adfafa11e50f5e5e0bd689
          (
            cd "${historical_v16_root}/repo"
            env \\
              -u GITHUB_ACTIONS \\
              -u GITHUB_SHA \\
              -u GITHUB_EVENT_NAME \\
              -u GITHUB_REF \\
              python -m unittest \\
                tests/test_admin_dependency_cache_export_plan_v16.py \\
                tests/test_admin_dependency_cache_v16_failure_evidence.py
          )

      - name: Quality gate
"""


def _ci_unit_test_contract_valid(workflow: str) -> bool:
    return (
        workflow.count(CI_UNIT_TEST_CONTRACT) == 1
        and workflow.count(
            "tests.test_admin_dependency_cache_export_plan_v13."
            "AdminDependencyCacheExportPlanV13Tests."
        ) == 11
        and workflow.count(
            "test_admin_dependency_cache_export_plan_v13.py"
        ) == 1
        and workflow.count(
            "test_admin_dependency_cache_export_plan_v14.py"
        ) == 2
        and workflow.count(
            "test_admin_dependency_cache_export_plan_v15.py"
        ) == 2
        and workflow.count(
            "test_admin_dependency_cache_v15_failure_evidence.py"
        ) == 2
        and workflow.count(
            "test_admin_dependency_cache_export_plan_v16.py"
        ) == 2
        and workflow.count(
            "test_admin_dependency_cache_v16_failure_evidence.py"
        ) == 2
        and workflow.count("timeout-minutes: 35") == 1
    )


def check_ci_and_deployment_config() -> list[dict[str, Any]]:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    production_compose = (
        ROOT / "deploy" / "production" / "docker-compose.yml"
    ).read_text(encoding="utf-8")
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
    xhs_provenance = (ROOT / "docs" / "SPIDER_XHS_HTTP_PROVENANCE.md").read_text(encoding="utf-8")
    xhs_adapter = (MODEL_DIR / "spider_xhs_http.py").read_text(encoding="utf-8")
    tracking_worker = (MODEL_DIR / "crawler.py").read_text(encoding="utf-8")
    tracking_contract = (
        ROOT / "docs" / "XHS_TRACKING_PRODUCTION_CONTRACT.md"
    ).read_text(encoding="utf-8")
    tracking_migration = (
        MODEL_DIR
        / "migrations"
        / "postgres"
        / "0010_tracking_execution_contract.sql"
    ).read_text(encoding="utf-8")
    trends_contract = (
        ROOT / "docs" / "XHS_TRENDS_PRODUCTION_CONTRACT.md"
    ).read_text(encoding="utf-8")
    trends_migration = (
        MODEL_DIR
        / "migrations"
        / "postgres"
        / "0011_trends_execution_contract.sql"
    ).read_text(encoding="utf-8")
    trends_runtime = (
        MODEL_DIR / "trends_contract.py"
    ).read_text(encoding="utf-8")
    private_storage_source = (
        MODEL_DIR / "private_storage.py"
    ).read_text(encoding="utf-8")
    recovery_evidence_source = (
        MODEL_DIR / "storage_recovery_evidence.py"
    ).read_text(encoding="utf-8")
    private_storage_migration = (
        MODEL_DIR
        / "migrations"
        / "postgres"
        / "0013_private_storage_recovery_contract.sql"
    ).read_text(encoding="utf-8")
    private_storage_contract = (
        ROOT / "docs" / "PRIVATE_STORAGE_AND_RECOVERY_CONTRACT.md"
    ).read_text(encoding="utf-8")
    production_role_acl = (
        ROOT / "scripts" / "postgres" / "noteai_production_runtime_roles.sql"
    ).read_text(encoding="utf-8")
    production_schema_runner = (
        ROOT / "tools" / "production_schema_roles.py"
    ).read_text(encoding="utf-8")
    production_role_acl_executable = "\n".join(
        line
        for line in production_role_acl.splitlines()
        if not line.lstrip().startswith("--")
    )
    market_worker = (
        MODEL_DIR / "market_timing_worker.py"
    ).read_text(encoding="utf-8")
    xhs_tests = (ROOT / "tests" / "test_xhs_acquisition.py").read_text(encoding="utf-8")
    architecture_summary = (ROOT / ".codex" / "notes" / "architecture-summary.md").read_text(encoding="utf-8")
    risk_register = (ROOT / ".codex" / "notes" / "risk-register.md").read_text(encoding="utf-8")
    fact_enrichment = (MODEL_DIR / "fact_enrichment.py").read_text(encoding="utf-8")
    api_source = (MODEL_DIR / "api.py").read_text(encoding="utf-8")
    admin_server_source = (
        MODEL_DIR / "admin_server.py"
    ).read_text(encoding="utf-8")
    admin_auth_source = (
        MODEL_DIR / "admin_auth.py"
    ).read_text(encoding="utf-8")
    admin_html = (
        MODEL_DIR / "admin.html"
    ).read_text(encoding="utf-8")
    frontend_html = (
        ROOT / "NoteAI_Pro_Demo_Framer.html"
    ).read_text(encoding="utf-8")
    ui_admin_contract = (
        ROOT / "docs" / "FIRST_LAUNCH_UI_ADMIN_CONTRACT.md"
    ).read_text(encoding="utf-8")
    api_readiness_source = api_source.split("def _readiness_payload()", 1)[1].split('@app.get("/health/live")', 1)[0]
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    render_blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")
    browser_security = (MODEL_DIR / "chromium_security.py").read_text(encoding="utf-8")
    browser_sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in PRODUCTION_BROWSER_SOURCES
    }
    production_browser_text = "\n".join(browser_sources.values())
    seccomp_profile = _load_json(PLAYWRIGHT_SECCOMP_PROFILE)
    seccomp_user_namespace_rules = [
        rule
        for rule in seccomp_profile.get("syscalls", [])
        if {"clone", "setns", "unshare"}.issubset(set(rule.get("names", [])))
        and rule.get("action") == "SCMP_ACT_ALLOW"
    ]
    entrypoint = (ROOT / "scripts" / "docker_entrypoint.sh").read_text(encoding="utf-8")
    entrypoint_semantic_passed, entrypoint_semantic_detail = _check_entrypoint_runtime_contract(entrypoint)
    api_runtime_stage = dockerfile.split("FROM runtime-common AS api-runtime", 1)[1].split(
        "FROM runtime-common AS admin-runtime", 1
    )[0]
    admin_runtime_stage = dockerfile.split("FROM runtime-common AS admin-runtime", 1)[1].split(
        "FROM runtime-common AS payment-runtime", 1
    )[0]
    payment_runtime_stage = dockerfile.split(
        "FROM runtime-common AS payment-runtime", 1
    )[1].split(
        "FROM runtime-common AS ai-worker-runtime", 1
    )[0]
    ai_worker_runtime_stage = dockerfile.split(
        "FROM runtime-common AS ai-worker-runtime", 1
    )[1].split(
        "FROM runtime-common AS xhs-http-runtime", 1
    )[0]
    xhs_runtime_stage = dockerfile.split("FROM runtime-common AS xhs-http-runtime", 1)[1].split(
        "FROM ${NOTEAI_RUNTIME_TARGET} AS noteai-runtime", 1
    )[0]
    service_start_sources = "\n".join(
        (ROOT / "scripts" / name).read_text(encoding="utf-8")
        for name in (
            "render_start_api.sh",
            "render_start_admin.sh",
            "render_start_payment.sh",
            "render_run_market_timing.sh",
            "render_run_crawler.sh",
        )
    )
    api_start_source = (
        ROOT / "scripts" / "render_start_api.sh"
    ).read_text(encoding="utf-8")
    db_source = (MODEL_DIR / "db.py").read_text(encoding="utf-8")
    init_db_source = db_source.split("def init_db()", 1)[1].split("def database_health", 1)[0]

    checks = [
        _ok(
            "ci_runs_tests",
            _ci_unit_test_contract_valid(workflow),
        ),
        _ok("ci_checks_model_artifacts", "scripts/fetch_model_artifacts.py --check-only --required" in workflow),
        _ok("ci_runs_quality_gate", "tools/quality_gate.py quality/golden_notes.sample.json" in workflow),
        _ok("ci_runs_production_readiness_gate", "tools/production_readiness_gate.py" in workflow),
        _ok("ci_checks_docker_compose", "docker compose config --quiet" in workflow),
        _ok("dependabot_configured", "package-ecosystem: \"pip\"" in dependabot and "github-actions" in dependabot),
        _ok("docker_uses_artifact_entrypoint", "ENTRYPOINT [\"/app/scripts/docker_entrypoint.sh\"]" in dockerfile),
        _ok("docker_copies_entrypoint", "COPY scripts/docker_entrypoint.sh" in dockerfile),
        _ok(
            "docker_has_browser_free_production_role_targets",
            "FROM runtime-common AS api-runtime" in dockerfile
            and "FROM runtime-common AS admin-runtime" in dockerfile
            and "FROM runtime-common AS payment-runtime" in dockerfile
            and "FROM runtime-common AS ai-worker-runtime" in dockerfile
            and "FROM runtime-common AS xhs-http-runtime" in dockerfile
            and "FROM runtime-common AS worker-runtime" not in dockerfile
            and "ARG NOTEAI_RUNTIME_TARGET=api-runtime" in dockerfile
            and "FROM ${NOTEAI_RUNTIME_TARGET} AS noteai-runtime" in dockerfile
            and 'CMD ["/app/scripts/render_start_api.sh"]' in api_runtime_stage
            and 'CMD ["/app/scripts/render_start_admin.sh"]' in admin_runtime_stage
            and 'CMD ["/app/scripts/render_start_payment.sh"]' in payment_runtime_stage
            and 'CMD ["python", "durable_ai_worker.py", "--once"]' in ai_worker_runtime_stage
            and "NOTEAI_DURABLE_AI_SUSPENDED=1" in ai_worker_runtime_stage
            and "HEALTHCHECK NONE" in ai_worker_runtime_stage
            and 'CMD ["/bin/false"]' in xhs_runtime_stage
            and "NOTEAI_XHS_COLLECTION_SUSPENDED=1" in xhs_runtime_stage
            and "HEALTHCHECK NONE" in xhs_runtime_stage,
        ),
        _ok(
            "api_runtime_excludes_browser_and_graphics_stack",
            "playwright" not in api_runtime_stage.lower()
            and "chromium" not in api_runtime_stage.lower()
            and "playwright==" not in requirements_api
            and all(package not in dockerfile for package in ("libgl1", "libglib2.0-0", "libsm6", "libxext6", "libxrender1")),
        ),
        _ok(
            "cryptography_pins_native_scan_fixed_wheel",
            "cryptography==50.0.0" in api_requirement_lines
            and "cryptography==48.0.1" not in api_requirement_lines
            and "cryptography==46.0.7" not in api_requirement_lines,
        ),
        _ok(
            "production_targets_exclude_browser_dependencies_and_commands",
            all(
                "playwright" not in stage.lower() and "chromium" not in stage.lower()
                for stage in (
                    api_runtime_stage,
                    admin_runtime_stage,
                    payment_runtime_stage,
                    ai_worker_runtime_stage,
                    xhs_runtime_stage,
                )
            )
            and "python -m playwright install" not in dockerfile
            and "PLAYWRIGHT_BROWSERS_PATH" not in dockerfile,
        ),
        _ok(
            "xhs_signer_dependencies_are_fixed_and_minimal",
            "CRYPTO_JS_VERSION=4.2.0" in dockerfile
            and "sha512-KALDyEYgpY+Rlob/iriUtjV6d5Eq+Y191A5g4UqLAi8CyGP9N1+FdVbkc1SxKc2r4YAYqG8JzO2KGL+AizD70Q==" in dockerfile
            and "COPY --from=xhs-signer-node /opt/noteai/xhs-node" in xhs_runtime_stage
            and "xhs_xray" not in xhs_runtime_stage
            and "websectiga" not in xhs_runtime_stage,
        ),
        _ok(
            "all_production_roles_are_non_root",
            all(
                "USER noteai" in stage
                for stage in (
                    api_runtime_stage,
                    admin_runtime_stage,
                    ai_worker_runtime_stage,
                    xhs_runtime_stage,
                )
            ),
        ),
        _ok(
            "docker_removes_python_build_tooling",
            "python -m pip uninstall -y setuptools wheel" in dockerfile
            and "python -m pip check" in dockerfile,
        ),
        _ok(
            "private_storage_sdk_and_role_credentials_are_fixed",
            "alibabacloud-oss-v2==1.3.2" in api_requirement_lines
            and "alibabacloud_credentials==1.0.10" in api_requirement_lines
            and 'type="ecs_ram_role"' in private_storage_source
            and "role_name=role_name" in private_storage_source
            and "enable_imds_v2=True" in private_storage_source
            and "disable_imds_v1=True" in private_storage_source
            and "metadata_token_duration=60" in private_storage_source
            and "static OSS credentials are prohibited" in private_storage_source
            and "use_internal_endpoint = True" in private_storage_source,
        ),
        _ok(
            "private_storage_writes_are_conditional_encrypted_and_bounded",
            "forbid_overwrite=True" in private_storage_source
            and 'server_side_encryption="KMS" if self.kms_key_id else "AES256"'
            in private_storage_source
            and "PRIVATE_OBJECT_SIZE_MISMATCH" in private_storage_source
            and "MAX_VIDEO_BUNDLE_BYTES = 64 * 1024 * 1024"
            in private_storage_source
            and "ORPHAN_MIN_AGE_SECONDS = 24 * 60 * 60"
            in private_storage_source,
        ),
        _ok(
            "private_media_migration_is_grant_free_and_owner_guarded",
            "CREATE TABLE IF NOT EXISTS private_media_refs"
            in private_storage_migration
            and "CREATE TABLE IF NOT EXISTS ai_operation_media_refs"
            in private_storage_migration
            and "noteai_validate_operation_media_link_v1"
            in private_storage_migration
            and "invalid owner-bound media link" in private_storage_migration
            and "GRANT " not in private_storage_migration.upper()
            and "REVOKE " not in private_storage_migration.upper(),
        ),
        _ok(
            "production_uploads_are_owner_bound_and_local_cache_fails_closed",
            'NOTEAI_DEPLOYMENT_STAGE", "").strip().lower() == "production"'
            in api_source
            and "_stream_upload_to_temp" in api_source
            and "store_media_bytes(" in api_source
            and 'purpose="video_frames"' in api_source
            and 'purpose="image"' in api_source
            and "_private_storage.load_media_bytes(" in api_source
            and all(
                "NOTEAI_DEPLOYMENT_STAGE: production"
                in _compose_service_block(production_compose, service)
                for service in (
                    "api",
                    "admin",
                    "payment",
                    "ai-dispatcher",
                    "ai-worker",
                    "xhs-trends",
                    "xhs-tracking",
                )
            )
            and "NOTEAI_VIDEO_CACHE_DIR" not in production_compose,
        ),
        _ok(
            "restore_evidence_is_content_free_and_exact",
            "row_values_included" in recovery_evidence_source
            and "object_keys_included" in recovery_evidence_source
            and "database_tables" in recovery_evidence_source
            and "private_objects" in recovery_evidence_source
            and "manifest_sha256" in recovery_evidence_source
            and "must never overwrite the source instance"
            in private_storage_contract.lower(),
        ),
        _ok(
            "docker_healthcheck_uses_python_stdlib",
            'import http.client, os, sys' in dockerfile
            and "'/health/live'" in dockerfile
            and "CMD curl" not in dockerfile,
        ),
        _ok(
            "production_admin_mutations_fail_closed",
            "_is_restricted_admin_runtime" in admin_server_source
            and "_admin_capabilities_payload" in admin_server_source
            and '@admin_app.get("/admin/capabilities")' in admin_server_source
            and all(
                f'_require_admin_capability("{capability}")'
                in admin_server_source
                for capability in (
                    "business_mutation",
                    "prompt_mutation",
                    "model_mutation",
                    "crawler_control",
                    "tracking_requeue",
                )
            )
            and "NOTEAI_DEPLOYMENT_STAGE: production"
            in _compose_service_block(production_compose, "admin")
            and 'NOTEAI_CLOUD_RUNTIME: "1"'
            in _compose_service_block(production_compose, "admin"),
        ),
        _ok(
            "admin_bearer_and_browser_storage_are_minimized",
            "hashlib.sha256(token.encode(\"utf-8\")).hexdigest()"
            in admin_auth_source
            and "INSERT INTO admin_sessions" in admin_auth_source
            and "(_token_digest(token), username" in admin_auth_source
            and "sessionStorage.getItem('noteai_admin_token')" in admin_html
            and "sessionStorage.setItem('noteai_admin_token'" in admin_html
            and "localStorage.setItem('noteai_admin_token'" not in admin_html,
        ),
        _ok(
            "production_admin_cors_and_pii_fail_closed",
            "return [origin for origin in origins if origin != \"*\"]"
            in admin_server_source
            and 'public_user.pop("phone", None)' in admin_server_source
            and 'public_user.pop("email", None)' in admin_server_source
            and "payment_ref,recorded_at" not in admin_server_source
            and "生产只读控制台" in admin_html,
        ),
        _ok(
            "diagnosis_share_card_is_local_and_truthful",
            "function shareDiagnosisCard(button)" in frontend_html
            and "canvas.toBlob" in frontend_html
            and "link.download = 'noteai-diagnosis-card.png'"
            in frontend_html
            and "诊断卡片已生成，复制链接成功" not in frontend_html
            and "performs no NoteAI or supplier request" in ui_admin_contract,
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
            "api_forwarded_client_ip_requires_explicit_trusted_proxy",
            '--forwarded-allow-ips="${NOTEAI_TRUSTED_PROXY_IPS:-127.0.0.1}"'
            in api_start_source
            and '--forwarded-allow-ips="*"' not in api_start_source
            and (
                'NOTEAI_TRUSTED_PROXY_IPS: '
                '"${NOTEAI_API_TRUSTED_PROXY_IPS:-127.0.0.1}"'
            )
            in production_compose,
        ),
        _ok(
            "requirements_are_role_split_and_compatible",
            "playwright==" not in requirements_api
            and "-r requirements-api.txt" in requirements_worker
            and "playwright==1.56.0" in requirements_worker
            and "-r requirements-api.txt" in requirements_compat
            and all(
                re.fullmatch(r"[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^\s]+", line)
                for line in api_requirement_lines
            ),
        ),
        _ok(
            "compose_runtime_targets_match_roles",
            compose.count("target: api-runtime") == 1
            and compose.count("target: admin-runtime") == 1
            and compose.count("target: payment-runtime") == 1
            and compose.count("target: ai-worker-runtime") == 1
            and compose.count("target: xhs-http-runtime") == 2
            and "target: worker-runtime" not in compose
            and compose.count("NOTEAI_RUNTIME_ROLE=api") == 1
            and compose.count("NOTEAI_RUNTIME_ROLE=admin") == 1
            and compose.count("NOTEAI_RUNTIME_ROLE=payment") == 1
            and compose.count("NOTEAI_RUNTIME_ROLE=ai-worker") == 1
            and compose.count("NOTEAI_RUNTIME_ROLE=xhs-http") == 2
            and compose.count("NOTEAI_XHS_ACQUISITION_ADAPTER=spider_xhs_http") == 2,
        ),
        _ok(
            "compose_xhs_collection_defaults_suspended",
            compose.count("NOTEAI_XHS_COLLECTION_SUSPENDED=${NOTEAI_XHS_COLLECTION_SUSPENDED:-1}") == 2,
        ),
        _ok(
            "compose_all_browser_free_roles_have_least_privilege_runtime",
            _compose_services_have_runtime_hardening(
                compose,
                (
                    "noteai",
                    "noteai-admin",
                    "noteai-payment",
                    "noteai-ai-worker",
                    "noteai-trends-worker",
                    "noteai-tracking-worker",
                ),
            ),
        ),
        _ok(
            "production_compose_requires_digest_images_and_least_privilege_runtime",
            "build:" not in production_compose
            and _compose_services_have_runtime_hardening(
                production_compose,
                (
                    "api",
                    "admin",
                    "payment",
                    "ai-dispatcher",
                    "ai-worker",
                    "xhs-trends",
                    "xhs-tracking",
                ),
            )
            and "${NOTEAI_API_IMAGE_REPOSITORY:?set NOTEAI_API_IMAGE_REPOSITORY}@sha256:${NOTEAI_API_IMAGE_DIGEST_HEX:?set NOTEAI_API_IMAGE_DIGEST_HEX to 64 lowercase hex characters}" in production_compose
            and "${NOTEAI_ADMIN_IMAGE_REPOSITORY:?set NOTEAI_ADMIN_IMAGE_REPOSITORY}@sha256:${NOTEAI_ADMIN_IMAGE_DIGEST_HEX:?set NOTEAI_ADMIN_IMAGE_DIGEST_HEX to 64 lowercase hex characters}" in production_compose
            and "${NOTEAI_PAYMENT_IMAGE_REPOSITORY:?set NOTEAI_PAYMENT_IMAGE_REPOSITORY}@sha256:${NOTEAI_PAYMENT_IMAGE_DIGEST_HEX:?set NOTEAI_PAYMENT_IMAGE_DIGEST_HEX to 64 lowercase hex characters}" in production_compose
            and production_compose.count(
                "${NOTEAI_AI_WORKER_IMAGE_REPOSITORY:?set NOTEAI_AI_WORKER_IMAGE_REPOSITORY}@sha256:${NOTEAI_AI_WORKER_IMAGE_DIGEST_HEX:?set NOTEAI_AI_WORKER_IMAGE_DIGEST_HEX to 64 lowercase hex characters}"
            ) == 2
            and production_compose.count(
                "${NOTEAI_XHS_IMAGE_REPOSITORY:?set NOTEAI_XHS_IMAGE_REPOSITORY}@sha256:${NOTEAI_XHS_IMAGE_DIGEST_HEX:?set NOTEAI_XHS_IMAGE_DIGEST_HEX to 64 lowercase hex characters}"
            ) == 2
            and production_compose.count(
                "${NOTEAI_API_ENV_FILE:-/etc/noteai/api.env}"
            ) == 1
            and production_compose.count(
                "${NOTEAI_ADMIN_ENV_FILE:-/etc/noteai/admin.env}"
            ) == 1
            and production_compose.count(
                "${NOTEAI_PAYMENT_ENV_FILE:-/etc/noteai/payment.env}"
            ) == 1
            and production_compose.count(
                "${NOTEAI_AI_DISPATCHER_ENV_FILE:-/etc/noteai/ai-dispatcher.env}"
            ) == 1
            and production_compose.count(
                "${NOTEAI_AI_WORKER_ENV_FILE:-/etc/noteai/ai-worker.env}"
            ) == 1
            and production_compose.count(
                "${NOTEAI_PRIVATE_STORAGE_ENV_FILE:-/etc/noteai/private-storage.env}"
            ) == 1
            and production_compose.count(
                "${NOTEAI_XHS_TRENDS_ENV_FILE:-/etc/noteai/xhs-trends.env}"
            ) == 1
            and production_compose.count(
                "${NOTEAI_XHS_TRACKING_ENV_FILE:-/etc/noteai/xhs-tracking.env}"
            ) == 1
            and "NOTEAI_XHS_ENV_FILE" not in production_compose
            and "NOTEAI_PRODUCTION_ENV_FILE" not in production_compose
            and "durable-ai-dispatcher"
            in _compose_service_block(production_compose, "ai-dispatcher")
            and "durable-ai-worker"
            in _compose_service_block(production_compose, "ai-worker")
            and "NOTEAI_PRIVATE_STORAGE_ENV_FILE"
            not in _compose_service_block(production_compose, "ai-dispatcher")
            and production_compose.count("target: /app/model/data") == 3
            and "target: /app/model/data" not in _compose_service_block(
                production_compose,
                "xhs-trends",
            )
            and "target: /app/model/artifacts" not in production_compose,
        ),
        _ok(
            "direct_adapter_is_read_only_and_proxy_free",
            all(path in xhs_adapter for path in (
                "/api/sns/web/v1/homefeed",
                "/api/sns/web/v1/search/recommend",
                "/api/sns/web/v1/search/notes",
                "/api/sns/web/v1/feed",
            ))
            and 'method not in {"GET", "POST"}' in xhs_adapter
            and "trust_env=False" in xhs_adapter
            and "proxies=" not in xhs_adapter,
        ),
        _ok(
            "direct_adapter_collection_gate_fails_closed",
            '_EXPLICIT_COLLECTION_UNLOCK_VALUES = frozenset({"0", "false", "off", "no"})' in xhs_adapter
            and 'return os.environ.get("NOTEAI_RUNTIME_ROLE", "").strip() == "xhs-http"' in xhs_adapter
            and 'role in {"api", "admin"}' in xhs_adapter
            and '_LEGACY_BROWSER_RUNTIME_ROLES = frozenset({"local", "legacy"})' in xhs_adapter,
        ),
        _ok(
            "tracking_execution_contract_is_bounded_and_at_most_once",
            "FOR UPDATE SKIP LOCKED" in tracking_worker
            and "tracking_provider_attempts" in tracking_worker
            and "TrackingDailyLimitReached" in tracking_worker
            and "deterministic_effect_id" in tracking_worker
            and "active_attempt_id IS NULL" in tracking_worker
            and "UNIQUE(track_id, stage)" in tracking_migration
            and "FOREIGN KEY(track_id, user_id)" in tracking_migration
            and "FOREIGN KEY(id, active_attempt_id)" in tracking_migration
            and "tracked_notes_canonical_identity_contract" in tracking_migration
            and "CREATE UNIQUE INDEX uq_tracked_user_note" in tracking_migration
            and not any(
                re.match(r"\\s*(?:GRANT|REVOKE)\\b", line, re.IGNORECASE)
                for line in tracking_migration.splitlines()
            )
            and "at most one 24h and one 7d provider admission"
            in tracking_contract
            and "noteai_xhs_tracking" in tracking_contract,
        ),
        _ok(
            "trends_execution_contract_is_atomic_bounded_and_fail_closed",
            "xhs_trends_snapshot_evidence" in trends_migration
            and "UNIQUE (run_id, ordinal)" in trends_migration
            and "provider_attempt_count BETWEEN 0 AND 34" in trends_migration
            and not any(
                re.match(r"\\s*(?:GRANT|REVOKE)\\b", line, re.IGNORECASE)
                for line in trends_migration.splitlines()
            )
            and "def publish_transaction" in trends_runtime
            and "def record_snapshot_evidence" in trends_runtime
            and "def snapshot_payload_from_rows" in trends_runtime
            and "trends_snapshot_upload_not_allowed" in market_worker
            and "trends_current_run_xhs_evidence_incomplete" in market_worker
            and "trends_provider_attempt_evidence_incomplete" in market_worker
            and "noteai_xhs_trends" in trends_contract
            and "all commit or all roll back" in trends_contract,
        ),
        _ok(
            "production_trends_runtime_is_isolated_and_resource_bounded",
            "${NOTEAI_XHS_TRENDS_SUSPENDED:-1}" in production_compose
            and "NOTEAI_XHS_SERVICE: trends" in _compose_service_block(
                production_compose,
                "xhs-trends",
            )
            and 'restart: "no"' in _compose_service_block(
                production_compose,
                "xhs-trends",
            )
            and "--healthcheck" in _compose_service_block(
                production_compose,
                "xhs-trends",
            )
            and "--interval" in _compose_service_block(
                production_compose,
                "xhs-trends",
            )
            and 'cpus: "0.50"' in _compose_service_block(
                production_compose,
                "xhs-trends",
            )
            and "mem_limit: 512m" in _compose_service_block(
                production_compose,
                "xhs-trends",
            )
            and "pids_limit: 64" in _compose_service_block(
                production_compose,
                "xhs-trends",
            )
            and "target: /app/model/data" not in _compose_service_block(
                production_compose,
                "xhs-trends",
            ),
        ),
        _ok(
            "production_tracking_runtime_is_isolated_and_resource_bounded",
            "${NOTEAI_XHS_TRENDS_SUSPENDED:-1}" in production_compose
            and "${NOTEAI_XHS_TRACKING_SUSPENDED:-1}" in production_compose
            and 'restart: "no"' in _compose_service_block(
                production_compose,
                "xhs-tracking",
            )
            and "--healthcheck" in _compose_service_block(
                production_compose,
                "xhs-tracking",
            )
            and 'cpus: "0.25"' in _compose_service_block(
                production_compose,
                "xhs-tracking",
            )
            and "mem_limit: 256m" in _compose_service_block(
                production_compose,
                "xhs-tracking",
            )
            and "pids_limit: 64" in _compose_service_block(
                production_compose,
                "xhs-tracking",
            ),
        ),
        _ok(
            "direct_adapter_assets_are_sha_pinned",
            "723dc6ef64836b0998aa4ba85796e2ffd99bfb20f222d69adcbcf66ea589292d" in xhs_adapter
            and "e79fe1c79c97a73fbf5fdb6420af114ff591902aa60b436ac4b803a99b806d2e" in xhs_adapter
            and "9504b5249103f34a0a4e7062939258061559e2fd" in xhs_provenance
            and "7db08187cb5332a5a3c89a5923987e098ffddf14" in xhs_provenance,
        ),
        _ok(
            "compose_has_no_production_browser_security_profile",
            all(
                "no-new-privileges:true" in _compose_service_block(compose, service)
                for service in (
                    "noteai",
                    "noteai-admin",
                    "noteai-payment",
                    "noteai-trends-worker",
                    "noteai-tracking-worker",
                )
            )
            and "seccomp=" not in _compose_service_block(compose, "noteai")
            and "seccomp=" not in compose
            and "privileged: true" not in compose
            and "seccomp=unconfined" not in compose
            and "SYS_ADMIN" not in compose,
        ),
        _ok(
            "render_runtime_targets_match_roles",
            render_blueprint.count("key: NOTEAI_RUNTIME_TARGET") == 4
            and render_blueprint.count("value: api-runtime") == 1
            and render_blueprint.count("value: admin-runtime") == 1
            and render_blueprint.count("value: xhs-http-runtime") == 2
            and render_blueprint.count("key: NOTEAI_RUNTIME_ROLE") == 4
            and len(re.findall(r"^\s*value:\s*api\s*$", render_blueprint, re.MULTILINE)) == 1
            and len(re.findall(r"^\s*value:\s*admin\s*$", render_blueprint, re.MULTILINE)) == 1
            and len(re.findall(r"^\s*value:\s*xhs-http\s*$", render_blueprint, re.MULTILINE)) == 2
            and render_blueprint.count("value: spider_xhs_http") == 2,
        ),
        _ok(
            "render_xhs_collection_defaults_suspended",
            render_blueprint.count("key: NOTEAI_XHS_COLLECTION_SUSPENDED") == 2,
        ),
        _ok(
            "fresh_ci_xhs_tests_do_not_import_python_playwright",
            "import playwright.async_api" not in xhs_tests
            and 'ModuleType("playwright.async_api")' in xhs_tests
            and "playwright==" not in requirements_api
            and "playwright==" not in requirements_compat,
        ),
        _ok(
            "architecture_and_risk_describe_direct_http_production_boundary",
            "production xhs runtime boundary" in architecture_summary.lower()
            and "browser-free" in architecture_summary.lower()
            and "historical playwright crawler source" in architecture_summary.lower()
            and "spider_xhs_http" in architecture_summary
            and "spider_xhs private http interface" in risk_register.lower()
            and "默认暂停" in risk_register
            and "商业授权不等于" in risk_register,
        ),
        _ok(
            "render_does_not_request_unsupported_browser_bypass",
            "NOTEAI_XHS_LOW_MEMORY_BROWSER" not in render_blueprint
            and all(flag not in render_blueprint for flag in FORBIDDEN_CHROMIUM_FLAGS),
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
            and "xhs-http runtime requires the pinned acquisition adapter" in entrypoint
            and "ai-worker requires an exact production processor" in entrypoint
            and "is_unsigned_integer" in entrypoint
            and "*[!0-9]*" in entrypoint
            and all(value in entrypoint for value in (
                "/app/scripts/render_start_api.sh",
                "/app/scripts/render_start_admin.sh",
                "/app/scripts/render_start_payment.sh",
                "/app/scripts/render_run_market_timing.sh",
                "/app/scripts/render_run_crawler.sh",
                "/app/scripts/render_predeploy.py",
                "admin_server:admin_app",
                "market_timing_worker.py",
                "crawler_worker.py",
                "durable_ai_worker.py",
                "/bin/false",
            ))
            and 'case " $* "' not in entrypoint
            and "api-runtime cannot start a browser worker command" not in entrypoint
            and "worker-runtime" not in entrypoint,
        ),
        _ok(
            "entrypoint_runtime_contract_semantics",
            entrypoint_semantic_passed,
            entrypoint_semantic_detail,
        ),
        _ok("compose_has_trends_worker", "noteai-trends-worker:" in compose and "market_timing_worker.py" in compose),
        _ok("entrypoint_can_skip_model_for_xhs_runtime", "NOTEAI_SKIP_MODEL_ARTIFACT_CHECK" in entrypoint),
        _ok("compose_shares_artifacts", "./model/artifacts:/app/model/artifacts" in compose),
        _ok(
            "compose_uses_core_readiness",
            "noteai-admin:" in compose
            and "noteai-payment:" in compose
            and compose.count("import http.client, sys") == 3
            and "HTTPConnection('127.0.0.1', 8000" in compose
            and "HTTPConnection('127.0.0.1', 8001" in compose
            and "HTTPConnection('127.0.0.1', 8002" in compose
            and compose.count("'/health/ready'") == 3
            and '"curl"' not in compose,
        ),
        _ok(
            "postgres_migrations_are_predeploy_only",
            "apply_postgres_migrations()" not in init_db_source
            and "render_predeploy.py" not in service_start_sources
            and "NOTEAI_MIGRATE_ON_START" not in service_start_sources
            and render_blueprint.count("preDeployCommand: python /app/scripts/render_predeploy.py") == 1,
        ),
        _ok(
            "production_schema_role_acl_is_credential_free",
            "CREATE ROLE %I NOLOGIN NOSUPERUSER" in production_role_acl
            and "NOCREATEDB NOCREATEROLE" in production_role_acl
            and "NOINHERIT NOREPLICATION NOBYPASSRLS" in production_role_acl
            and "REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC" in production_role_acl
            and "REVOKE UPDATE ON notes FROM noteai_app" in production_role_acl
            and "REVOKE UPDATE ON saved_diagnoses FROM noteai_app" in production_role_acl
            and not re.search(
                r"\bPASSWORD\b", production_role_acl_executable, re.IGNORECASE
            )
            and not re.search(
                r"\bLOGIN\b", production_role_acl_executable, re.IGNORECASE
            )
            and not re.search(
                r"\bALTER\s+ROLE\b",
                production_role_acl_executable,
                re.IGNORECASE,
            ),
            "credential-free NOLOGIN runtime-role ACL",
        ),
        _ok(
            "production_schema_role_runner_is_bounded",
            'TASK_ID = "PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001"'
            in production_schema_runner
            and 'CONFIRM_ENV = "NOTEAI_SCHEMA_APPLY_CONFIRM"'
            in production_schema_runner
            and 'conn.execute("SET TRANSACTION READ ONLY")'
            in production_schema_runner
            and "with conn.transaction():" in production_schema_runner
            and "SET LOCAL statement_timeout='120s'" in production_schema_runner
            and "SET LOCAL lock_timeout='5s'" in production_schema_runner
            and '"existing_business_row_updates": 0' in production_schema_runner
            and '"provider_calls": 0' in production_schema_runner
            and "render_predeploy.py" not in production_schema_runner,
            "single-transaction apply plus independent read-only verify",
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


def check_browserless_vex() -> list[dict[str, Any]]:
    browserless_errors = validate_browserless_vex_bundle()
    native_errors = validate_native_release_vex_bundle()
    b55_native_errors = validate_b55_native_release_vex_bundle()
    cad5ce3_native_errors = validate_cad5ce3_native_release_vex_bundle()
    b55_registry_errors = validate_b55_registry_release_vex_bundle()
    admin_5335_native_errors = validate_5335_admin_native_release_vex_bundle()
    try:
        admin_publication_attempt_errors = (
            validate_admin_private_publication_attempt_evidence(
                load_admin_private_publication_attempt_evidence()
            )
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        admin_publication_attempt_errors = [
            f"cannot load Admin publication attempt evidence: {exc}"
        ]
    admin_dependency_cache_plan_errors = validate_admin_dependency_cache_export_plan()
    dependency_cache_plan_state = admin_dependency_cache_plan_state()
    try:
        admin_dependency_cache_v2_failure_errors = (
            verify_admin_dependency_cache_v2_failure_evidence(
                load_admin_dependency_cache_v2_failure_evidence()
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        admin_dependency_cache_v2_failure_errors = [
            f"cannot load Admin dependency-cache V2 failure evidence: {exc}"
        ]
    try:
        admin_dependency_cache_v3_failure_errors = (
            verify_admin_dependency_cache_v3_failure_evidence(
                load_admin_dependency_cache_v3_failure_evidence()
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        admin_dependency_cache_v3_failure_errors = [
            f"cannot load Admin dependency-cache V3 failure evidence: {exc}"
        ]
    try:
        admin_dependency_cache_v4_failure_errors = (
            verify_admin_dependency_cache_v4_failure_evidence(
                load_admin_dependency_cache_v4_failure_evidence()
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        admin_dependency_cache_v4_failure_errors = [
            f"cannot load Admin dependency-cache V4 failure evidence: {exc}"
        ]
    try:
        admin_dependency_cache_v5_failure_errors = (
            verify_admin_dependency_cache_v5_failure_evidence(
                load_admin_dependency_cache_v5_failure_evidence()
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        admin_dependency_cache_v5_failure_errors = [
            f"cannot load Admin dependency-cache V5 failure evidence: {exc}"
        ]
    try:
        admin_dependency_cache_v6_failure_errors = (
            verify_admin_dependency_cache_v6_failure_evidence(
                load_admin_dependency_cache_v6_failure_evidence()
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        admin_dependency_cache_v6_failure_errors = [
            f"cannot load Admin dependency-cache V6 failure evidence: {exc}"
        ]
    try:
        admin_dependency_cache_v7_failure_errors = (
            verify_admin_dependency_cache_v7_failure_evidence(
                load_admin_dependency_cache_v7_failure_evidence()
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        admin_dependency_cache_v7_failure_errors = [
            f"cannot load Admin dependency-cache V7 failure evidence: {exc}"
        ]
    try:
        admin_dependency_cache_v8_failure_errors = (
            verify_admin_dependency_cache_v8_failure_evidence(
                load_admin_dependency_cache_v8_failure_evidence()
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        admin_dependency_cache_v8_failure_errors = [
            f"cannot load Admin dependency-cache V8 failure evidence: {exc}"
        ]
    try:
        admin_dependency_cache_v9_failure_errors = (
            verify_admin_dependency_cache_v9_failure_evidence(
                load_admin_dependency_cache_v9_failure_evidence()
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        admin_dependency_cache_v9_failure_errors = [
            f"cannot load Admin dependency-cache V9 failure evidence: {exc}"
        ]
    try:
        admin_dependency_cache_v10_failure_errors = (
            verify_admin_dependency_cache_v10_failure_evidence(
                load_admin_dependency_cache_v10_failure_evidence()
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        admin_dependency_cache_v10_failure_errors = [
            f"cannot load Admin dependency-cache V10 failure evidence: {exc}"
        ]
    try:
        admin_dependency_cache_v12_failure_errors = (
            verify_admin_dependency_cache_v12_failure_evidence(
                load_admin_dependency_cache_v12_failure_evidence()
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        admin_dependency_cache_v12_failure_errors = [
            f"cannot load Admin dependency-cache V12 failure evidence: {exc}"
        ]
    try:
        admin_dependency_cache_v15_predecessor_errors = (
            validate_admin_dependency_cache_v15_predecessor()
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as exc:
        admin_dependency_cache_v15_predecessor_errors = [
            f"cannot evaluate Admin dependency-cache V15 predecessor: {exc}"
        ]
    try:
        admin_dependency_cache_v15_failure_errors = (
            verify_admin_dependency_cache_v15_failure_evidence(
                load_admin_dependency_cache_v15_failure_evidence(),
                verify_git_state=False,
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        admin_dependency_cache_v15_failure_errors = [
            f"cannot load Admin dependency-cache V15 failure evidence: {exc}"
        ]
    try:
        admin_dependency_cache_plan_v16_errors = (
            validate_admin_dependency_cache_v16_predecessor()
        )
        dependency_cache_plan_state_v16 = (
            "V16_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_RECEIPT_EXACT"
            if not admin_dependency_cache_plan_v16_errors
            else "INVALID"
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as exc:
        evaluation_error = (
            "cannot evaluate Admin dependency-cache V16 lifecycle: " f"{exc}"
        )
        admin_dependency_cache_plan_v16_errors = [evaluation_error]
        admin_dependency_cache_v16_failure_errors = [evaluation_error]
        dependency_cache_plan_state_v16 = "INVALID"
    else:
        try:
            admin_dependency_cache_v16_failure_errors = (
                verify_admin_dependency_cache_v16_failure_evidence(
                    load_admin_dependency_cache_v16_failure_evidence(),
                    verify_git_state=False,
                )
            )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            admin_dependency_cache_v16_failure_errors = [
                f"cannot load Admin dependency-cache V16 failure evidence: {exc}"
            ]
    admin_dependency_cache_plan_v3_errors = (
        validate_admin_dependency_cache_export_plan_v3()
    )
    dependency_cache_plan_state_v3 = admin_dependency_cache_plan_state_v3()
    admin_dependency_cache_plan_v4_errors = (
        validate_admin_dependency_cache_export_plan_v4()
    )
    dependency_cache_plan_state_v4 = admin_dependency_cache_plan_state_v4()
    admin_dependency_cache_plan_v5_errors = (
        validate_admin_dependency_cache_export_plan_v5()
    )
    dependency_cache_plan_state_v5 = admin_dependency_cache_plan_state_v5()
    admin_dependency_cache_plan_v6_errors = (
        validate_admin_dependency_cache_export_plan_v6()
    )
    dependency_cache_plan_state_v6 = admin_dependency_cache_plan_state_v6()
    admin_dependency_cache_plan_v7_errors = (
        validate_admin_dependency_cache_export_plan_v7()
    )
    dependency_cache_plan_state_v7 = admin_dependency_cache_plan_state_v7()
    admin_dependency_cache_plan_v8_errors = (
        validate_admin_dependency_cache_export_plan_v8()
    )
    dependency_cache_plan_state_v8 = admin_dependency_cache_plan_state_v8()
    admin_dependency_cache_plan_v9_errors = (
        validate_admin_dependency_cache_export_plan_v9()
    )
    dependency_cache_plan_state_v9 = admin_dependency_cache_plan_state_v9()
    accepted_dependency_cache_plan_states_v9 = {
        "PREPARED_V9_NOT_TRIGGERED",
        "V9_ARMED_OR_TRIGGERED_EXACT",
    }
    admin_dependency_cache_plan_v10_errors = (
        validate_admin_dependency_cache_export_plan_v10()
    )
    dependency_cache_plan_state_v10 = admin_dependency_cache_plan_state_v10()
    accepted_dependency_cache_plan_states_v10 = {
        "PREPARED_V10_NOT_TRIGGERED",
        "V10_ARMED_OR_TRIGGERED_EXACT",
    }
    admin_dependency_cache_v11_supersession_errors = (
        validate_v11_untriggered_supersession()
    )
    dependency_cache_v11_supersession_state = (
        v11_untriggered_supersession_state()
    )
    admin_dependency_cache_plan_v12_errors = (
        validate_admin_dependency_cache_export_plan_v12()
    )
    dependency_cache_plan_state_v12 = admin_dependency_cache_plan_state_v12()
    accepted_dependency_cache_plan_states_v12 = {
        "PREPARED_V12_NOT_TRIGGERED",
        "V12_ARMED_OR_TRIGGERED_EXACT",
        "V12_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_SUPERSESSION_EXACT",
        "V12_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_RECEIPT_EXACT",
    }
    accepted_dependency_cache_plan_states_v16 = {
        "V16_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_RECEIPT_EXACT",
    }
    accepted_dependency_cache_v11_supersession = (
        dependency_cache_v11_supersession_state
        == "V11_UNTRIGGERED_SUPERSEDED_EXACT"
        or (
            dependency_cache_v11_supersession_state
            == "V11_UNTRIGGERED_SUPERSESSION_PENDING"
            and dependency_cache_plan_state_v12
            == "PREPARED_V12_NOT_TRIGGERED"
            and not admin_dependency_cache_plan_v12_errors
        )
    )
    registry_errors = validate_registry_release_vex_bundle()
    return [
        _ok(
            "exact_a635692_browserless_vex_bundle",
            not browserless_errors,
            "; ".join(browserless_errors[:5])
            if browserless_errors
            else "12 exact-product dispositions independently reviewed",
        ),
        _ok(
            "exact_b06671f_github_native_five_role_source_bundle",
            not native_errors,
            "; ".join(native_errors[:5])
            if native_errors
            else (
                "five exact local images; 12 dispositions / 115 SBOM BOM-Links; "
                "raw 4 Critical / 19 High per role remains unsuppressed"
            ),
        ),
        _ok(
            "exact_b06671f_registry_native_five_role_vex_bundle",
            not registry_errors,
            "; ".join(registry_errors[:5])
            if registry_errors
            else (
                "five unique ACR manifest digests; exact control-plane binding; "
                "temporary publication access cleaned; deployment unauthorized"
            ),
        ),
        _ok(
            "exact_b55f118_github_native_five_role_source_bundle",
            not b55_native_errors,
            "; ".join(b55_native_errors[:5])
            if b55_native_errors
            else (
                "two-file image-context delta; five exact local images; "
                "raw 4 Critical / 19 High per role remains unsuppressed"
            ),
        ),
        _ok(
            "exact_cad5ce3_github_native_five_role_source_bundle",
            not cad5ce3_native_errors,
            "; ".join(cad5ce3_native_errors[:5])
            if cad5ce3_native_errors
            else (
                "exact run and GitHub artifact archive digest; five local "
                "images; cryptography findings zero; raw Debian 4 Critical / "
                "19 High per role remains unsuppressed"
            ),
        ),
        _ok(
            "exact_b55f118_registry_native_five_role_vex_bundle",
            not b55_registry_errors,
            "; ".join(b55_registry_errors[:5])
            if b55_registry_errors
            else (
                "five exact immutable tags and unique ACR manifest digests; "
                "serial no-retry publication; access cleaned; canary unauthorized"
            ),
        ),
        _ok(
            "exact_5335bda_github_native_admin_only_source_bundle",
            not admin_5335_native_errors,
            "; ".join(admin_5335_native_errors[:5])
            if admin_5335_native_errors
            else (
                "eleven exact Admin-only files; controller request and fresh "
                "image identity bound; raw 4 Critical / 19 High remains "
                "unsuppressed; publication and deployment unauthorized"
            ),
        ),
        _ok(
            "bounded_5335bda_admin_private_publication_attempt_clean",
            not admin_publication_attempt_errors,
            "; ".join(admin_publication_attempt_errors[:5])
            if admin_publication_attempt_errors
            else (
                "two bounded pre-publication failures; image/scan/login/push zero; "
                "temporary material cleaned; saving-mode builder stop verified"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_export_plan_fail_closed",
            not admin_dependency_cache_plan_errors,
            "; ".join(admin_dependency_cache_plan_errors[:5])
            if admin_dependency_cache_plan_errors
            else (
                f"state={dependency_cache_plan_state}; exact Dockerfile lines "
                "1-80 exported; isolated producer/fresh-consumer import plus "
                "full-context cacheless replay and pre-upload cleanup required; "
                "Registry publication unauthorized"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v2_attempt1_failed_artifact0",
            not admin_dependency_cache_v2_failure_errors,
            "; ".join(admin_dependency_cache_v2_failure_errors[:5])
            if admin_dependency_cache_v2_failure_errors
            else (
                "run 30591103183 attempt 1 failed before portability/upload; "
                "artifacts, download, transfer, cloud-builder start, Admin ACR "
                "private-publication and production mutations zero; V2 rerun "
                "forbidden"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v3_attempt1_failed_artifact0",
            not admin_dependency_cache_v3_failure_errors,
            "; ".join(admin_dependency_cache_v3_failure_errors[:5])
            if admin_dependency_cache_v3_failure_errors
            else (
                "run 30596283342 attempt 1 failed closed before export; "
                "Buildx 0.35.0 source proves one exact default network.host "
                "daemon-entitlement flag; artifact/download/transfer/cloud-builder/"
                "Admin ACR and production mutations zero; V3 rerun forbidden"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v3_recovery_plan_fail_closed",
            not admin_dependency_cache_plan_v3_errors,
            "; ".join(admin_dependency_cache_plan_v3_errors[:5])
            if admin_dependency_cache_plan_v3_errors
            else (
                f"state={dependency_cache_plan_state_v3}; BuildKit v0.31.2 "
                "builder/frontend and LLB target platforms separated; Docker "
                "auth and Buildx state use distinct task roots with aggregate "
                "cleanup; exact request-only V3 activation retained and terminal "
                "failure recorded without rerun"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v4_recovery_plan_fail_closed",
            not admin_dependency_cache_plan_v4_errors,
            "; ".join(admin_dependency_cache_plan_v4_errors[:5])
            if admin_dependency_cache_plan_v4_errors
            else (
                f"state={dependency_cache_plan_state_v4}; Buildx v0.35.0 "
                "source identity and sole ordered network.host daemon flag "
                "bound; build-level host networking and additional entitlements "
                "forbidden; request lifecycle represented by the reported state"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v4_attempt1_failed_artifact0",
            not admin_dependency_cache_v4_failure_errors,
            "; ".join(admin_dependency_cache_v4_failure_errors[:5])
            if admin_dependency_cache_v4_failure_errors
            else (
                "run 30599069993 attempt 1 failed after build at the exact "
                "provenance environment contract; artifact/download/transfer/"
                "cloud-builder/Admin ACR and production mutations zero; cleanup "
                "zero-residue remains unclaimed and V4 rerun is forbidden"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v5_recovery_plan_fail_closed",
            not admin_dependency_cache_plan_v5_errors,
            "; ".join(admin_dependency_cache_plan_v5_errors[:5])
            if admin_dependency_cache_plan_v5_errors
            else (
                f"state={dependency_cache_plan_state_v5}; V4 terminal receipt "
                "frozen; exact provenance injection disablement, client-token "
                "state prevention, phase-aware client-state validation and "
                "per-control cleanup receipt bound; request lifecycle represented "
                "by the reported state"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v5_attempt1_failed_artifact0",
            not admin_dependency_cache_v5_failure_errors,
            "; ".join(admin_dependency_cache_v5_failure_errors[:5])
            if admin_dependency_cache_v5_failure_errors
            else (
                "run 30606218502 attempt 1 failed after build because the "
                "frozen flat parser cannot consume nested SolveStatus rawjson; "
                "artifact/download/transfer/cloud-builder/Admin ACR and "
                "production mutations zero; cleanup zero-residue proven and "
                "V5 rerun forbidden"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v6_recovery_plan_fail_closed",
            not admin_dependency_cache_plan_v6_errors,
            "; ".join(admin_dependency_cache_plan_v6_errors[:5])
            if admin_dependency_cache_plan_v6_errors
            else (
                f"state={dependency_cache_plan_state_v6}; V5 terminal receipt "
                "frozen; nested SolveStatus identity, structural provenance "
                "binding, decoded-log scan and V2/V3/V6 verifier trust chain "
                "bound; frozen V5 transient/cleanup namespace retained; request "
                "lifecycle represented by the reported state"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v6_attempt1_failed_artifact0",
            not admin_dependency_cache_v6_failure_errors,
            "; ".join(admin_dependency_cache_v6_failure_errors[:5])
            if admin_dependency_cache_v6_failure_errors
            else (
                "run 30613707689 attempt 1 failed after the dependency build "
                "because the frozen verifier rejected an incremental "
                "same-digest update with a single-value cardinality rule; "
                "exact conflicting field remains "
                "UNKNOWN, artifact/download/transfer/cloud-builder/Admin ACR "
                "and production mutations are zero, enumerated cleanup-helper "
                "roots/files and Docker parity are proven, and V6 rerun is "
                "forbidden"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v7_recovery_plan_fail_closed",
            not admin_dependency_cache_plan_v7_errors,
            "; ".join(admin_dependency_cache_plan_v7_errors[:5])
            if admin_dependency_cache_plan_v7_errors
            else (
                f"state={dependency_cache_plan_state_v7}; V6 terminal receipt "
                "frozen; exact-nanosecond incremental same-digest intervals, "
                "full-copy inputs/progressGroup, structural role binding, "
                "decoded-log/network scan and V2/V3/V6/V7 verifier chain "
                "bound; frozen V5 transient/cleanup and legacy provider "
                "artifact protocol retained; request lifecycle represented "
                "by the reported state"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v7_attempt1_failed_artifact0",
            not admin_dependency_cache_v7_failure_errors,
            "; ".join(admin_dependency_cache_v7_failure_errors[:5])
            if admin_dependency_cache_v7_failure_errors
            else (
                "run 30622876575 attempt 1 failed after producer rawjson "
                "parsing completed because strict provenance location "
                "projection rejected LLB step9; the exact predicate and "
                "payload remain UNKNOWN_NOT_RETAINED, role/package-network "
                "validation was not reached, artifact/download/transfer/"
                "cloud-builder/Admin ACR and production mutations are zero, "
                "enumerated cleanup and Docker parity are proven, and V7 "
                "rerun is forbidden"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v8_recovery_plan_fail_closed",
            not admin_dependency_cache_plan_v8_errors,
            "; ".join(admin_dependency_cache_plan_v8_errors[:5])
            if admin_dependency_cache_plan_v8_errors
            else (
                f"state={dependency_cache_plan_state_v8}; V7 terminal "
                "checkpoint/receipt and failure evidence frozen; only exact "
                "empty source-location wrappers are nonbinding, populated "
                "locations and role/sourceIndex rules delegate to frozen V7; "
                "V2/V3/V6/V7/V8 verifier chain, V5 transient/cleanup and "
                "legacy provider artifact protocol retained; request "
                "lifecycle represented by the reported state"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v8_attempt1_failed_artifact0",
            not admin_dependency_cache_v8_failure_errors,
            "; ".join(admin_dependency_cache_v8_failure_errors[:5])
            if admin_dependency_cache_v8_failure_errors
            else (
                "run 30632611051 attempt 1 failed after producer verification, "
                "portable bundle generation and the fresh-consumer import build "
                "because strict same-digest input equality rejected processed "
                "vertex update 43; the exact digest, vectors and transition remain "
                "UNKNOWN_NOT_RETAINED, cacheless replay/final validation/upload "
                "were not reached, artifact/download/transfer/cloud-builder/Admin "
                "ACR and production mutations are zero, enumerated cleanup and "
                "Docker parity are proven, and V8 rerun is forbidden"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v9_recovery_plan_fail_closed",
            not admin_dependency_cache_plan_v9_errors
            and dependency_cache_plan_state_v9
            in accepted_dependency_cache_plan_states_v9,
            "; ".join(admin_dependency_cache_plan_v9_errors[:5])
            if admin_dependency_cache_plan_v9_errors
            else (
                f"state={dependency_cache_plan_state_v9} is not an accepted "
                "V9 control-plane state"
                if dependency_cache_plan_state_v9
                not in accepted_dependency_cache_plan_states_v9
                else (
                    f"state={dependency_cache_plan_state_v9}; V8 terminal "
                    "checkpoint/receipt and failure evidence frozen; only an "
                    "absent inputs member is nonbinding, explicit empty/null/"
                    "non-array values fail closed, the first nonempty ordered "
                    "vector binds and later values require an exact ordered "
                    "match; omission-only remains UNKNOWN and V8 runtime digest/"
                    "vectors/transition remain UNKNOWN_NOT_RETAINED; V2/V3/V6/"
                    "V7/V8/V9 verifier chain, V5 transient/cleanup and legacy "
                    "provider artifact protocol retained; request lifecycle "
                    "represented by the reported state"
                )
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v9_attempt1_failed_artifact0",
            not admin_dependency_cache_v9_failure_errors,
            "; ".join(admin_dependency_cache_v9_failure_errors[:5])
            if admin_dependency_cache_v9_failure_errors
            else (
                "run 30651679657 attempt 1 exercised the V9 missing-input "
                "contract with one mixed-presence digest and completed the "
                "fresh-consumer import build and rawjson parse; exact role "
                "validation then found meituan/apt cached and runtime_pip not "
                "cached, while the underlying dynamic cause remains "
                "UNKNOWN_NOT_RETAINED; cacheless replay/final validation/"
                "upload were not reached, artifact/download/transfer/cloud-"
                "builder/Admin ACR and production mutations are zero, "
                "enumerated cleanup and Docker parity are proven, the "
                "activation-HEAD ordinary CI failure is bound to one stale "
                "inert-only test, and V9 rerun is forbidden"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v10_recovery_plan_fail_closed",
            not admin_dependency_cache_plan_v10_errors
            and dependency_cache_plan_state_v10
            in accepted_dependency_cache_plan_states_v10,
            "; ".join(admin_dependency_cache_plan_v10_errors[:5])
            if admin_dependency_cache_plan_v10_errors
            else (
                f"state={dependency_cache_plan_state_v10} is not an accepted "
                "V10 control-plane state"
                if dependency_cache_plan_state_v10
                not in accepted_dependency_cache_plan_states_v10
                else (
                    f"state={dependency_cache_plan_state_v10}; V9 terminal "
                    "checkpoint/receipt and failure evidence frozen; producer "
                    "prefix and full replay remain byte-identical, while a "
                    "consumer-only network-none observer must execute uncached "
                    "and bind directly to runtime_pip; every dependency role "
                    "interval must remain uncached on producer and cached on "
                    "replay, the post-pip cacheless witness must execute "
                    "uncached, V2/V3/V6/V7/V8/V9/V10 verifier chain and legacy "
                    "provider protocol are retained, and request lifecycle is "
                    "represented by the reported state"
                )
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v10_attempt1_failed_artifact0",
            not admin_dependency_cache_v10_failure_errors,
            "; ".join(admin_dependency_cache_v10_failure_errors[:5])
            if admin_dependency_cache_v10_failure_errors
            else (
                "run 30672160324 attempt 1 completed producer verification and "
                "a 13-file/2-chunk portable core export, then the fresh-consumer "
                "observer build failed the unchanged all-interval cache predicate "
                "at runtime_pip; V10 identifies the rejecting verifier boundary "
                "but the underlying cache mechanism remains UNKNOWN_NOT_RETAINED, "
                "the producer-terminal-pip hypothesis was not tested and remains "
                "plausible, cacheless replay/final validation/upload were not "
                "reached, artifact/download/transfer/cloud-builder/Admin ACR and "
                "production mutations are zero, enumerated cleanup and Docker "
                "parity are proven, the activation PR-only failure is bound to "
                "the now-regressed synthetic-merge history false positive, and "
                "V10 rerun is forbidden"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v11_recovery_plan_fail_closed",
            not admin_dependency_cache_v11_supersession_errors
            and accepted_dependency_cache_v11_supersession,
            "; ".join(admin_dependency_cache_v11_supersession_errors[:5])
            if admin_dependency_cache_v11_supersession_errors
            else (
                f"state={dependency_cache_v11_supersession_state} is not an "
                "accepted V11 supersession state"
                if not accepted_dependency_cache_v11_supersession
                else (
                    f"state={dependency_cache_v11_supersession_state}; V11 was "
                    "never triggered, has no receipt or active request, and "
                    "is explicitly superseded by the exact V12 candidate "
                    "without editing its seven frozen authorities"
                )
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v12_recovery_plan_fail_closed",
            not admin_dependency_cache_plan_v12_errors
            and dependency_cache_plan_state_v12
            in accepted_dependency_cache_plan_states_v12,
            "; ".join(admin_dependency_cache_plan_v12_errors[:5])
            if admin_dependency_cache_plan_v12_errors
            else (
                f"state={dependency_cache_plan_state_v12} is not an accepted "
                "V12 control-plane state"
                if dependency_cache_plan_state_v12
                not in accepted_dependency_cache_plan_states_v12
                else (
                    f"state={dependency_cache_plan_state_v12}; V11 remains "
                    "untriggered and is explicitly superseded because the V2 "
                    "workflow has two immutable run records; V12 freezes both "
                    "V2 records, each unique V3-V10 attempt, V11 run zero and "
                    "the reused V11 runtime core under two fresh fully paginated "
                    "pre-resource/post-cleanup ledgers"
                )
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v12_attempt1_failed_artifact0",
            not admin_dependency_cache_v12_failure_errors,
            "; ".join(admin_dependency_cache_v12_failure_errors[:5])
            if admin_dependency_cache_v12_failure_errors
            else (
                "unique run 30696298423/job 91359681758 attempt 1 failed "
                "closed before consumer import because the V11 verifier "
                "compared BuildKit cache-key and vertex digest domains; "
                "artifact/download/transfer/production mutations are zero, "
                "both builders and transient Docker state were removed, "
                "fresh pre/post ledgers passed, portability is "
                "UNKNOWN_NOT_REACHED, and V12 rerun is forbidden"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v15_recovery_plan_fail_closed",
            not admin_dependency_cache_v15_predecessor_errors,
            "; ".join(admin_dependency_cache_v15_predecessor_errors[:5])
            if admin_dependency_cache_v15_predecessor_errors
            else (
                "V15 exact-one activation, unique attempt-one failure, terminal "
                "checkpoint and exact-four receipt remain immutable on the "
                "first-parent chain; V15 rerun remains forbidden"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v15_attempt1_failed_artifact0",
            not admin_dependency_cache_v15_failure_errors,
            "; ".join(admin_dependency_cache_v15_failure_errors[:5])
            if admin_dependency_cache_v15_failure_errors
            else (
                "unique run 30724578319/job 91433793914 attempt 1 failed "
                "closed on fresh-consumer runtime_pip DIGEST_DRIFT; the "
                "bounded cache structure passed, external-cache-removed "
                "same-consumer-builder replay and upload were not reached, "
                "artifact/download/transfer/production "
                "mutations are zero, both builders and transient Docker state "
                "were removed, fresh pre/post ledgers passed, and V15 rerun "
                "is forbidden"
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v16_recovery_plan_fail_closed",
            not admin_dependency_cache_plan_v16_errors
            and dependency_cache_plan_state_v16
            in accepted_dependency_cache_plan_states_v16,
            "; ".join(admin_dependency_cache_plan_v16_errors[:5])
            if admin_dependency_cache_plan_v16_errors
            else (
                f"state={dependency_cache_plan_state_v16} is not an accepted "
                "V16 control-plane state"
                if dependency_cache_plan_state_v16
                not in accepted_dependency_cache_plan_states_v16
                else (
                    f"state={dependency_cache_plan_state_v16}; the exact16/4/1 "
                    "controller is frozen at its accepted terminal receipt, "
                    "and its unique external run may not be repeated"
                )
            ),
        ),
        _ok(
            "exact_5335bda_admin_dependency_cache_v16_attempt1_failed_artifact0",
            _v16_terminal_failure_evidence_accepted(
                dependency_cache_plan_state_v16,
                admin_dependency_cache_v16_failure_errors,
            ),
            _v16_terminal_failure_evidence_detail(
                dependency_cache_plan_state_v16,
                admin_dependency_cache_v16_failure_errors,
            ),
        ),
    ]


def check_api_c_current_release_evidence() -> list[dict[str, Any]]:
    errors = validate_api_c_current_release_evidence_bundle()
    return [
        _ok(
            "exact_api_c_b55_runtime_deployment_evidence",
            not errors,
            "; ".join(errors[:5])
            if errors
            else (
                "ordered no-retry canary/promotion/restart chain; "
                "independent postcheck; rollback assets retained; final residue zero"
            ),
        )
    ]


def check_api_f_current_release_evidence() -> list[dict[str, Any]]:
    errors = validate_api_f_current_release_evidence_bundle()
    return [
        _ok(
            "exact_api_f_b55_runtime_deployment_evidence",
            not errors,
            "; ".join(errors[:5])
            if errors
            else (
                "API-F-owned pull identity and ordered no-retry deployment; "
                "single canary; rollback exercised; peer non-regression; "
                "final residue zero"
            ),
        )
    ]


def check_admin_current_release_evidence() -> list[dict[str, Any]]:
    errors = validate_admin_current_release_evidence_bundle()
    return [
        _ok(
            "exact_admin_current_release_deployment_evidence",
            not errors,
            "; ".join(errors[:5])
            if errors
            else (
                "exact private Admin digest; bounded canary and ACL audit; "
                "one session insert/delete; promotion, restart and zero residue"
            ),
        )
    ]


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
    if raw_value in {"r", "b", "rb", "br"}:
        return False, ""
    if re.fullmatch(r"[A-Z][A-Z0-9_]*(?:\s*/\s*)?", raw_value):
        return False, ""
    if raw_value in {"(", "[", "{"}:
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
        "browserless_vex": check_browserless_vex(),
        "api_c_runtime_evidence": check_api_c_current_release_evidence(),
        "api_f_runtime_evidence": check_api_f_current_release_evidence(),
        "admin_runtime_evidence": check_admin_current_release_evidence(),
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
