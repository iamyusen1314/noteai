#!/usr/bin/env python3
"""Fail-closed readiness accounting for the complete NoteAI first launch.

This tool validates a finite evidence ledger and computes three distinct
layers. It never contacts cloud services or providers and cannot turn a green
repository test suite into production evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from verify_api_c_current_release_evidence import (
    EXPECTED_MANIFEST_EVIDENCE as API_C_EXPECTED_MANIFEST_EVIDENCE,
)
from verify_api_c_current_release_evidence import (
    validate_bundle as validate_api_c_current_release_evidence,
)
from verify_api_f_current_release_evidence import (
    EXPECTED_MANIFEST_EVIDENCE as API_F_EXPECTED_MANIFEST_EVIDENCE,
)
from verify_api_f_current_release_evidence import (
    validate_bundle as validate_api_f_current_release_evidence,
)
from verify_admin_current_release_evidence import (
    validate_bundle as validate_admin_current_release_evidence,
)
from verify_internal_zero_provider_smoke_evidence import (
    validate_manifest_evidence as validate_internal_zero_provider_smoke_evidence,
)
from verify_internal_failure_rollback_evidence import (
    validate_manifest_evidence as validate_internal_failure_rollback_evidence,
)
from verify_capacity_100_jobs_evidence import (
    validate_manifest_evidence as validate_capacity_100_jobs_evidence,
)
from verify_real_ai_provider_chain_evidence import (
    validate_manifest_evidence as validate_real_ai_provider_chain_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "deploy" / "production" / "internal-deployment-readiness.json"
EXPECTED_LAYERS = ("repository_isolated", "internal_runtime", "public_launch")
VALID_STATUSES = {"verified", "unverified", "blocked"}
VALID_EVIDENCE_KINDS = {"git", "path"}
VALID_EXECUTION_CLASSES = {
    "repository_offline",
    "authenticated_production",
    "external_or_public",
    "professional_review",
}
ACCEPTED_RISK_CONTROL_ID = "production_schema_roles"
EXPECTED_ACCEPTED_RISK_FINDINGS = {
    "FIRST-LAUNCH-LEGACY-XHS-ADMIN-MEMBERSHIP-20260728": {
        "granted_role": "noteai_xhs",
        "member_role": "noteai_admin",
        "admin_option": True,
        "inherit_option": False,
        "set_option": False,
    },
    "FIRST-LAUNCH-LEGACY-APP-INHERIT-20260728": {
        "role": "noteai_app",
        "rolinherit": True,
        "incoming_membership_count": 0,
        "high_privilege_inheritance_count": 0,
    },
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
# Canonical failed root saved at 9e7f4df; append-only prospective child excluded.
ITEM34_SEALED_OBSERVATION_SHA256 = "657cb64162b98ccdfc9d6693ceaea4bac670ca3955d9e65c6b8e06b6c1dc5cb1"
ITEM34_SEALED_GENERATION1_SHA256 = "115b8916c6b7eb828f4cd654b175a3b9fbb4be754286ad9b68149d1dc37b670f"
ITEM26_TERMINAL_EVIDENCE = [
    {"kind": "path", "ref": ".codex/handoffs/current-task.md"}
]
ITEM26_TERMINAL_ACCEPTANCE_SHA256 = (
    "4285231c59a111056426c643aac0764a1d7c32904caf46eacf555188d082a7b8"
)
ITEM26_HANDOFF_TERMINAL_BINDINGS = (
    "c-sz06us1t8hwu4u8",
    "t-sz06us1t8ijb7y8",
    "01A02A52-80FB-5218-AB42-9C2A98555BA6",
    "99fc8321d11db344af51f69b735f7dcdd4d09ea3a988148896034258067a842a",
    "476a9d2b6daf79f4d190bf3e08dfefe07e372fd6387f858bbe584b40c2a7910b",
    "438e9d19f5e4ea2284165e3a927e146ad1a22af62b010c7140f2bb999242e29b",
    "01A02A58-801E-59B8-868E-3E583F0FEFBD",
    "01A02A58-B2EA-598A-BCDF-3D96BF3CCD50",
    "01A02A5D-53B9-513F-8500-2944A1A79E4D",
    "01A02A63-23A2-592B-A670-75A568B96008",
    "01A02A72-9985-5D33-8ADB-D507E6A482FE",
    "t-sz06us4hlzxn7r4",
    "01A02A73-B23A-56A6-B9BE-FA7F30D5CF71",
    "01A02A6F-02C0-501E-8B83-59FE19AC358F",
    "01A02A6F-479B-5842-9BB6-1D9C43BD7328",
    "01A02A71-EE82-5D2F-8698-AA5C7BD0B81E",
    "01A02A76-B492-59AA-A15F-A541D7234041",
)
ITEM34_TRACKING_EVIDENCE = (
    "deploy/production/evidence/"
    "production-tracking-observation-audit-20260903.json"
)
ITEM34_CANONICAL_NOTE_ID = "6a7954010000000026034707"
ITEM34_OBSERVATION_STARTED_AT = "2026-09-04T22:30:38+08:00"
ITEM34_RUNTIME_CONFIG_MIGRATION = (
    "model/migrations/postgres/0019_xhs_tracking_runtime_config.sql"
)
ITEM34_RUNTIME_CONFIG_MIGRATION_SHA256 = (
    "bad6b9df591aba93a6f636c3185d955062a878ce9ed2a92d6c1dff5e5c267a6f"
)
ITEM34_RUNTIME_CONFIG_POLICY = "noteai_xhs_tracking_config_read_v1"
ITEM34_RUNTIME_CONFIG_POLICY_QUAL = (
    "((CURRENT_USER = 'noteai_xhs_tracking'::name) AND (is_secret = 0) "
    "AND (key = ANY (ARRAY['crawler_config'::text, "
    "'xhs_collection_safety'::text])))"
)
ITEM34_RUNTIME_CONFIG_POLICY_QUAL_SHA256 = (
    "0b9f96f9d27f4213c57554297af0d3111f7885ea2f0b0fb8dc9bbe91648e7af0"
)
ITEM32_TRENDS_EVIDENCE_SCHEMA = "noteai.item32.xhs_trends_readonly.v2"
ITEM32_V5_EVIDENCE_SCHEMA = "noteai.item32.xhs_trends_readonly.v3"
ITEM32_V5_EXECUTION_PLAN = "deploy/production/plans/item32-v5-successor-prospective.json"
ITEM32_V5_SEP17_EXECUTION_PLAN = "deploy/production/plans/item32-v5-sep17-successor-prospective.json"
ITEM32_V5_NETWORK_EXECUTION_PLAN = "deploy/production/plans/item32-v5-network-repair-prospective.json"
ITEM32_V5_NETWORK_WORK_ROOT = "/var/lib/noteai/item32-v5-network-repair-20260917"
ITEM32_V5_SOURCE_RETENTION_WORK_ROOT = "/var/lib/noteai/item32-v5-source-retention-20260918"
ITEM32_V5_SOURCE_RETENTION_EXECUTION_PLAN = "deploy/production/plans/item32-v5-source-retention-prospective.json"
ITEM32_V5_NETWORK_FINAL_REF = "deploy/production/evidence/production-item32-network-repair-final-readback-20260917.json"
ITEM32_V5_NETWORK_FINAL_SHA256 = "13857aef4ea9ce3e41cef2bbabbf8b8e2b1059792f9772f316ffc2e30a5a284f"
ITEM32_V5_SEP17_FINAL_REF = "deploy/production/evidence/production-item32-v5-hold-final-readback-20260917.json"
ITEM32_V5_SEP17_FINAL_SHA256 = "163eeaca405359bfd20afaf0186133c8be14f71609df41788131d5a3b466d3d1"
ITEM32_V5_NETWORK_D0_REF = "deploy/production/evidence/production-item32-network-repair-d0-20260917.json"
ITEM32_V5_NETWORK_D0_SHA256 = "6ee589052e1a8b2ed36434a2d97c2448964bc82f60589bfd3c8701e9c026ca48"
ITEM32_V5_NETWORK_D1_SHA256 = "2fc87837f1aba434db7df2c35a34a4226794246e13db2988fb34ac0d9ac7336c"
ITEM32_V5_NETWORK_D2_SHA256 = "3cdd2b5cada5935a6fdea2de16036ea650f46025b9434e83974795f208f4d878"
ITEM32_V5_NETWORK_D0M_SHA256 = "092127cf6f5c1c1bc075874f265e141e018a1ff00dce179ee6a354fc1a21a42d"
ITEM32_V5_SEP16_FINAL_REF = "deploy/production/evidence/production-item32-v5-hold-final-readback-20260916.json"
ITEM32_V5_SEP16_FINAL_SHA256 = "b7c11b3013849ab1370d96fb36118cc710b02ecb1cd8113f8945ece01b45a4e2"
ITEM32_V5_CONFIG_SHA256 = "6d5dcf058c5a0990ba7df3103f63e414de69b62b0ec3481c08490d66ae30b703"
ITEM32_V5_MANIFEST_SHA256 = "87b9bf70c7ded691659ca39d3ea2453f9a97dfbdb83c05c44e838c8b0cf417c9"
ITEM32_V5_UPSTREAM_SHA256 = "ede5937cf326c3fe19edbae8e98cecc8dd9b3b5b983a87594f8d262336328fb6"
ITEM32_V5_OVERLAYS = {
    "model/spider_xhs_http.py", "model/spider_xhs_v5.py", "model/security_redaction.py",
    "model/hot_keywords.py", "model/scheduler_a.py", "model/vendor/spider_xhs/v5/trends_bridge.js",
}
ITEM32_V5_SOURCE_RETENTION_OVERLAYS = ITEM32_V5_OVERLAYS | {"model/trends_contract.py", "model/market_timing_worker.py"}
ITEM32_ATTEMPT_AUDIT_SCHEMA = "noteai.item32.trends_attempt_audit.v1"
ITEM32_DATABASE_PROOF_SCHEMA = "noteai.item32.production_db_zero_write.v1"
ITEM32_TRENDS_DOMAINS = {"美食", "旅行", "穿搭", "美妆", "家居", "健身"}
ITEM32_REAL_XHS_SOURCES = {
    "hot_search",
    "search_recommend",
    "search_phrase",
    "search_token",
    "homefeed_phrase",
    "homefeed_token",
    "crawler",
    "xhs_downloader",
    "mediacrawler",
}
ITEM32_SEARCH_RESULT_SOURCES = {"search_phrase", "search_token"}
ITEM32_RUNTIME_READBACK_MAX_AGE = timedelta(minutes=15)
ITEM32_TRENDS_EVIDENCE = (
    "deploy/production/evidence/"
    "production-item32-xhs-trends-readonly-verified.json"
)
ITEM32_EXECUTION_PLAN = (
    "deploy/production/plans/item32-readonly-successor-prospective.json"
)
ITEM32_OUTER_EXECUTOR = (
    "tools/execute_item32_readonly_trends_successor.py"
)
ITEM32_HOLD_EVIDENCE = (
    "deploy/production/evidence/"
    "production-item32-xhs-diagnostic-hold-unknown-20260906.json"
)
ITEM32_HOLD_EVIDENCE_SHA256 = (
    "7c77706e1d7b7bf7b7c157162f95e2d8f04152f736b25bf8b636dd7225cf9ed9"
)
ITEM32_ORIGINAL_ADMISSION_SHA256 = (
    "8b20840ad5f6e5ec44f14086bfe635ff464c2125bfd76b2cb3b377fa2b48bfd8"
)
ITEM32_ORIGINAL_STORE_SHA256 = (
    "10e01542b261719794bdaf67ebbc355a8d2fe66e7448c516b206ad300f6402f8"
)
ITEM32_DIAGNOSTIC_ADMISSION_SHA256 = (
    "85d370068016ccf72fda32840a0cb58e99be82efb2dee6112c29967f76652561"
)
ITEM32_DIAGNOSTIC_RESULT_SHA256 = (
    "14406787e1064a265ab050b9e7d905752f1144c50498b9f9e281f373b8857382"
)
ITEM32_SIGNER_ASSET_SHA256 = (
    "723dc6ef64836b0998aa4ba85796e2ffd99bfb20f222d69adcbcf66ea589292d"
)
ITEM32_USER_AGENT_SHA256 = (
    "736357d05d01fc4e8f96dfe240061ad6ad7db6d207361cafc6dea2256037f621"
)
ITEM32_EXPECTED_UNIT_SHA256 = (
    "3ed7e555d61c8286ab6d1116d99171d23d073b6a318dbd4890ce3106b976e3b6"
)
ITEM32_EXPECTED_CONFIG_SHA256 = (
    "a78f4753591fd824ef3e4cfd8ed229c32542d1ac50d3c8c03b529e71fd01f8ec"
)
ITEM32_EXPECTED_MANIFEST_SHA256 = (
    "406445820107cda130698b157a20663b99697a0acdae65030784d3cb083c1e50"
)
ITEM32_EXPECTED_DB_PROBE_SHA256 = (
    "74c665e6361a6f7e9c11637faf7891effad4e98e2a480870ec0af586c39afbb7"
)
ITEM32_EXPECTED_SOURCE_SHA256 = {
    "model/market_timing_worker.py": (
        "e89be24bd3d32c8283acf4cba3f6586d2d5dff7c2c113377b743897bd0527978"
    ),
    "model/trends_contract.py": (
        "530820f68b1feb67aba0037d76ff9548ac0e629fea1c9854cc3df2048e2f2ca8"
    ),
    "model/spider_xhs_http.py": (
        "642c159992636b54bc4c26ffe70ca27caf48d025c5b693a4308074f9f8628ff7"
    ),
    "model/hot_keywords.py": (
        "48073372ef7c490192ff6cff54c326401b14d313d427e705a1a90f9bc17449b4"
    ),
}
# Preserve the legacy source contract used by the still-unpromoted Item33.
# Item32's frozen image and effective three-file overlay are separate facts.
ITEM32_IMAGE_SOURCE_SHA256 = {
    key: value for key, value in ITEM32_EXPECTED_SOURCE_SHA256.items()
    if key != "model/spider_xhs_http.py"
}
ITEM32_RUNTIME_OVERLAY_SHA256 = {
    "model/spider_xhs_http.py": "360a43f781e55e2c529387e70ef7be3b5f47a716bf6ede56d3daaaefa9b6bea1",
    "model/security_redaction.py": "c5fc02966035a01012a1a35b7005f3a62a72602c042e98dbad707029ca56f451",
    "model/hot_keywords.py": "77ff2a7e6b279d35a65f1dc497d32c92cc3bf46c061f0e42229dc42e3b81fc6d",
}
ITEM32_EFFECTIVE_SOURCE_SHA256 = {
    **ITEM32_IMAGE_SOURCE_SHA256, **ITEM32_RUNTIME_OVERLAY_SHA256,
}
ITEM33_TRENDS_PROMOTION_EVIDENCE_SCHEMA = (
    "noteai.item33.trends_managed_promotion.v1"
)
ITEM33_TRENDS_PROMOTION_EVIDENCE = (
    "deploy/production/evidence/"
    "production-item33-trends-managed-promotion-verified.json"
)
ITEM33_TRENDS_PROMOTION_EXECUTOR = (
    "tools/execute_item33_trends_promotion.py"
)
ITEM33_SUSPENDED_UNIT_SHA256 = (
    "3ed7e555d61c8286ab6d1116d99171d23d073b6a318dbd4890ce3106b976e3b6"
)
ITEM33_PROMOTED_UNIT_SHA256 = (
    "13d777c7705cc1dbc539c3dad3e034ba0ce5226b038e355d91bd3a440e565f8c"
)
ITEM33_EFFECTIVE_PROMOTED_UNIT_SHA256 = (
    "0a1c100462e62e9043ef0b73d81a8b12b85bd684b90c9e1d3a24e0a705fb88ff"
)
ITEM33_V5_PROMOTED_UNIT_SHA256 = "0a613724bb4f30fd914a8463ecb1ae866661941468757e5dc03ffefbc1eaa87e"
ITEM33_V5_LAUNCHER_SHA256 = "893533532eee48a5fae136b15f93c44de81ba0996540b52d82e219cfbca57e4e"
ITEM33_V5_CAPTURE_TOOLS = {
    "tools/item33_trends_runtime_capture.py", "tools/item33_trends_dml_capture.py",
}
ITEM33_V5_CAPTURE_EVIDENCE = "deploy/production/evidence/production-item33-trends-capture-seal.json"
ITEM33_V5_CAPTURE_JOURNAL = "deploy/production/evidence/production-item33-trends-dml-journal.jsonl"
ITEM33_V5_HTTP_RECEIPT = "deploy/production/evidence/production-item33-trends-worker-http-receipt.json"
ITEM33_V5_NORMAL_UNIT_SHA256 = "94da6db2f3746e6fb74d3447757bb80cec546512e2116b2713124ccbc8cda47f"
ITEM33_V5_NORMAL_ACTION = "deploy/production/evidence/production-item33-trends-normal-handoff-action.json"
ITEM33_V5_NORMAL_READBACK = "deploy/production/evidence/production-item33-trends-normal-handoff-readback.json"
ITEM33_V5_CAPTURE_TEARDOWN = "deploy/production/evidence/production-item33-trends-capture-teardown.json"
ITEM33_V5_CAPTURE_CLOSE_REFS = {
    "service_result": "deploy/production/evidence/production-item33-trends-capture-service-result.json",
    "close": "deploy/production/evidence/production-item33-trends-capture-service-close.json",
    "host": "deploy/production/evidence/production-item33-trends-normal-host-readback.json",
}
ITEM33_V5_RUNTIME_OVERLAY_SHA256 = {
    "model/hot_keywords.py": "77ff2a7e6b279d35a65f1dc497d32c92cc3bf46c061f0e42229dc42e3b81fc6d",
    "model/market_timing_worker.py": "ad5eb9d65cbe7b1b4919d388770260af8b490bd1ab72d52e32ee6a927f831e1f",
    "model/scheduler_a.py": "2cd8bbd094e0013fb023675618a532715a194afcde684715d5692150524f1f5b",
    "model/security_redaction.py": "09e31604f6d52d7fb101b38c1856d9388b6ce5e1612cc2c67095344ce725f694",
    "model/spider_xhs_http.py": "04c94f75ea34cd1d136f0db6808abed35d0c0007081d225a15af20e05fc12d93",
    "model/spider_xhs_v5.py": "d76bdc50578c886cdf1451cc03a204bb628c036c6c3da767d8e5e50361885dae",
    "model/trends_contract.py": "5ee865bad89fa8a96b3f0c35f02e2412958f07bf87ba158bab5796ba7da12a3c",
    "model/vendor/spider_xhs/v5/trends_bridge.js": "37152cb6c704da670f95df066f0b4e665588610eb1836daaaf05754c5ec81cd7",
}
ITEM33_ALLOWED_WRITE_TABLES = {
    "xhs_trends_runs",
    "xhs_trends_service_state",
    "xhs_trends_provider_attempts",
    "hot_keywords",
    "keyword_snapshots",
    "xhs_crawler_health",
    "xhs_freshness_ledger",
    "xhs_trends_snapshot_evidence",
}
ITEM33_FORBIDDEN_WRITE_GROUPS = {
    "system_settings",
    "crawler_events",
    "tracking",
    "authentication",
    "billing",
    "payment",
}
ITEM33_ENDPOINTS = {"homefeed", "search_recommend", "search_notes"}
ITEM31_PAYMENT_EVIDENCE_SCHEMA = "noteai.item31.direct_payment_chain.v1"
ITEM31_MERCHANT_APPROVAL_SCHEMA = "noteai.item31.merchant_approval.v1"
ITEM31_CANARY_AUDIT_SCHEMA = "noteai.item31.direct_provider_canary_audit.v1"
ITEM31_DIRECT_PROVIDERS = {"wechatpay_direct"}
ITEM31_CANARY_AMOUNT_FEN = 1200
ITEM31_PROVIDER_OPERATION_COUNT = 5
ITEM31_PAYMENT_EVIDENCE = (
    "deploy/production/evidence/"
    "production-item31-direct-payment-chain-verified.json"
)
ITEM31_REQUIRED_WRITE_TABLES = {
    "credits",
    "credit_transactions",
    "payment_orders",
    "payment_events",
    "payment_cash_ledger",
    "payment_credit_positions",
    "payment_entitlement_ledger",
    "payment_refunds",
    "payment_reconciliation_runs",
}
ITEM31_ALLOWED_WRITE_TABLES = ITEM31_REQUIRED_WRITE_TABLES | {
    "payment_reconciliation_items",
    "payment_settlement_summaries",
    "subscriptions",
}
ITEM35_APPROVAL_EVIDENCE_SCHEMA = "noteai.item35.professional_approval.v1"
ITEM35_APPROVAL_BINDING_SCHEMA = "noteai.item35.approval_binding.v1"
ITEM35_REVIEW_PACKAGE = "docs/ITEM35_PROFESSIONAL_REVIEW_PACKAGE_20260903.md"
ITEM35_APPROVAL_EVIDENCE = (
    "deploy/production/evidence/"
    "production-item35-professional-approval-verified.json"
)
ITEM35_REQUIRED_APPROVALS = {
    "legal_privacy",
    "provider_commercial_and_xhs",
}
ITEM35_REQUIRED_DOCUMENTS = {"privacy", "terms", "refund", "cross_border"}
ITEM35_DOCUMENT_SCOPE_PATHS = {
    "privacy": {
        "NoteAI_Pro_Demo_Framer.html",
        "docs/FIRST_LAUNCH_DATA_AND_SECURITY_CONTRACT.md",
        "docs/PRIVATE_STORAGE_AND_RECOVERY_CONTRACT.md",
        (
            "deploy/production/evidence/"
            "production-private-storage-runtime-verified-20260729.json"
        ),
    },
    "terms": {
        "NoteAI_Pro_Demo_Framer.html",
        "docs/FIRST_LAUNCH_UI_ADMIN_CONTRACT.md",
    },
    "refund": {
        "NoteAI_Pro_Demo_Framer.html",
        "docs/PAYMENT_PRODUCTION_CONTRACT.md",
    },
    "cross_border": {
        "NoteAI_Pro_Demo_Framer.html",
        "docs/FIRST_LAUNCH_DATA_AND_SECURITY_CONTRACT.md",
        "docs/CLAUDE_GATEWAY.md",
        "docs/PRIVATE_STORAGE_AND_RECOVERY_CONTRACT.md",
        (
            "deploy/production/evidence/"
            "production-private-storage-runtime-verified-20260729.json"
        ),
    },
}
ITEM35_APPROVAL_SCOPE_PATHS = {
    "legal_privacy": {
        ITEM35_REVIEW_PACKAGE,
        *set().union(*ITEM35_DOCUMENT_SCOPE_PATHS.values()),
    },
    "provider_commercial_and_xhs": {
        ITEM35_REVIEW_PACKAGE,
        "docs/CLAUDE_GATEWAY.md",
        "docs/XHS_TRENDS_PRODUCTION_CONTRACT.md",
        "docs/XHS_TRACKING_PRODUCTION_CONTRACT.md",
        (
            "deploy/production/evidence/"
            "production-real-ai-provider-chain-verified-20260824.json"
        ),
    },
}
ITEM36_ALB_EVIDENCE_SCHEMA = "noteai.item36.alb_tls.v1"
ITEM36_COST_APPROVAL_SCHEMA = "noteai.item36.recurring_cost_approval.v1"
ITEM36_COST_QUOTE_SCHEMA = "noteai.item36.aliyun_cost_quote.v1"
ITEM36_ACTUAL_USAGE_APPROVAL_SCHEMA = "noteai.item36.recurring_cost_approval.v2"
ITEM36_CURRENT_QUOTE_SCHEMA = "noteai.item36.aliyun_cost_quote.v2"
ITEM36_ACTUAL_USAGE_MODE = "ACTUAL_USAGE_CONTINUING"
ITEM36_BILLING_READBACK_SCHEMA = "noteai.item36.aliyun_billing_readback.v1"
ITEM36_MAX_EVIDENCE_AGE = timedelta(hours=36)
ITEM36_API_HOSTNAME = "api.noteaipro.cn"
ITEM36_CURRENT_API_HOSTNAME = "api.noteaipro.com"
ITEM36_ALB_EVIDENCE = (
    "deploy/production/evidence/production-item36-alb-tls-verified.json"
)
EXPECTED_PUBLIC_LAUNCH_DEPENDENCIES = {
    "real_ai_provider_chain": ["internal_failure_rollback"],
    "real_payment_chain": ["payment_internal_runtime", "monitoring_alerting"],
    "real_xhs_trends": ["trends_suspended_runtime", "monitoring_alerting"],
    "trends_managed_promotion": ["real_xhs_trends", "internal_failure_rollback"],
    "tracking_real_and_promotion": [
        "tracking_suspended_runtime",
        "monitoring_alerting",
        "internal_failure_rollback",
    ],
    "legal_provider_approval": [],
    "alb_tls": [
        "capacity_100_jobs",
        "trends_managed_promotion",
        "tracking_real_and_promotion",
    ],
    "pre_dns_commercial_smoke": [
        "real_ai_provider_chain",
        "real_payment_chain",
        "alb_tls",
    ],
    "dns_cutover": ["pre_dns_commercial_smoke"],
}
EXPECTED_CONTROL_DEPENDENCIES = {
    "product_scope_contract": [],
    "security_compliance_contract": [],
    "model_quality_release": [],
    "tracking_contract": [],
    "trends_contract": [],
    "durable_ai_contract": [],
    "private_storage_contract": [],
    "payment_contract": [],
    "ui_admin_contract": [],
    "admin_database_role": [],
    "self_hosted_browser_assets": [],
    "runtime_role_hardening": [],
    "production_readonly_preflight": [],
    "immutable_release_candidate": [],
    "production_schema_roles": [
        "production_readonly_preflight",
        "immutable_release_candidate",
    ],
    "managed_secret_distribution": [
        "production_readonly_preflight",
        "production_schema_roles",
    ],
    "private_storage_runtime": [
        "production_schema_roles",
        "managed_secret_distribution",
    ],
    "api_c_current_release": [
        "immutable_release_candidate",
        "production_schema_roles",
        "managed_secret_distribution",
        "private_storage_runtime",
    ],
    "api_f_current_release": ["api_c_current_release"],
    "admin_current_release": [
        "api_c_current_release",
        "production_schema_roles",
    ],
    "durable_ai_workers": [
        "private_storage_runtime",
        "production_schema_roles",
        "immutable_release_candidate",
    ],
    "trends_suspended_runtime": [
        "production_schema_roles",
        "immutable_release_candidate",
    ],
    "tracking_suspended_runtime": [
        "production_schema_roles",
        "immutable_release_candidate",
    ],
    "payment_internal_runtime": [
        "production_schema_roles",
        "immutable_release_candidate",
        "managed_secret_distribution",
    ],
    "monitoring_alerting": [
        "api_c_current_release",
        "api_f_current_release",
        "admin_current_release",
        "durable_ai_workers",
        "trends_suspended_runtime",
        "tracking_suspended_runtime",
        "payment_internal_runtime",
    ],
    "backup_pitr_restore": [
        "production_schema_roles",
        "private_storage_runtime",
    ],
    "internal_zero_provider_smoke": [
        "backup_pitr_restore",
        "api_c_current_release",
        "api_f_current_release",
        "admin_current_release",
        "durable_ai_workers",
        "trends_suspended_runtime",
        "tracking_suspended_runtime",
        "payment_internal_runtime",
    ],
    "internal_failure_rollback": [
        "monitoring_alerting",
        "backup_pitr_restore",
        "internal_zero_provider_smoke",
    ],
    "capacity_100_jobs": [
        "durable_ai_workers",
        "monitoring_alerting",
        "internal_failure_rollback",
    ],
    **EXPECTED_PUBLIC_LAUNCH_DEPENDENCIES,
}
EXPECTED_CONTROL_IDS = {
    "repository_isolated": (
        "product_scope_contract",
        "security_compliance_contract",
        "model_quality_release",
        "tracking_contract",
        "trends_contract",
        "durable_ai_contract",
        "private_storage_contract",
        "payment_contract",
        "ui_admin_contract",
        "admin_database_role",
        "self_hosted_browser_assets",
        "runtime_role_hardening",
    ),
    "internal_runtime": (
        "production_readonly_preflight",
        "immutable_release_candidate",
        "production_schema_roles",
        "managed_secret_distribution",
        "private_storage_runtime",
        "api_c_current_release",
        "api_f_current_release",
        "admin_current_release",
        "durable_ai_workers",
        "trends_suspended_runtime",
        "tracking_suspended_runtime",
        "payment_internal_runtime",
        "monitoring_alerting",
        "backup_pitr_restore",
        "internal_zero_provider_smoke",
        "internal_failure_rollback",
        "capacity_100_jobs",
    ),
    "public_launch": tuple(EXPECTED_PUBLIC_LAUNCH_DEPENDENCIES),
}


class ManifestError(ValueError):
    """Raised when the readiness ledger is ambiguous or unverifiable."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def _verify_git_ref(ref: str, *, root: Path) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}^{{commit}}"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _verify_path(ref: str, *, root: Path) -> bool:
    candidate = Path(ref)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return False
    return resolved.is_file()


def _exact_int(value: Any, expected: int | None = None) -> bool:
    if type(value) is not int:
        return False
    return expected is None or value == expected


def _finite_number(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _actual_file_sha256(ref: Any, *, root: Path) -> str | None:
    if not isinstance(ref, str) or not _verify_path(ref, root=root):
        return None
    try:
        return hashlib.sha256((root / ref).read_bytes()).hexdigest()
    except (OSError, UnicodeDecodeError):
        return None


def _read_json_artifact(
    ref: Any,
    schema: str,
    *,
    root: Path,
    max_bytes: int = 2 * 1024 * 1024,
) -> tuple[dict[str, Any] | None, str | None]:
    if (
        not isinstance(ref, str)
        or not ref.startswith("deploy/production/evidence/")
        or not ref.endswith(".json")
        or not _verify_path(ref, root=root)
    ):
        return None, None
    try:
        raw = (root / ref).read_bytes()
        if not raw or len(raw) > max_bytes:
            return None, None
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None, None
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        return None, None
    return payload, hashlib.sha256(raw).hexdigest()


def _keys_exact(value: Any, expected: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == expected


def _has_sensitive_evidence_key(value: Any) -> bool:
    """Reject credential-shaped fields without inspecting or logging values."""

    allowed_flags = {
        "secret_values_recorded",
        "raw_provider_identifiers_recorded",
        "production_database_url_present",
    }
    exact = {
        "a1",
        "api_key",
        "api_secret",
        "app_secret",
        "client_secret",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "live_key",
        "merchant_key",
        "password",
        "private_key",
        "private_key_pem",
        "refresh_token",
        "secret",
        "signing_key",
        "test_key",
        "token",
        "access_token",
        "web_session",
    }
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized not in allowed_flags and (
                normalized in exact
                or "password" in normalized
                or "private_key" in normalized
                or normalized.endswith("_secret")
                or normalized.endswith("_token")
                or normalized.endswith("_cookie")
            ):
                return True
            if _has_sensitive_evidence_key(nested):
                return True
    elif isinstance(value, list):
        return any(_has_sensitive_evidence_key(item) for item in value)
    return False


def _file_ledger_valid(
    ledger: Any,
    expected_paths: set[str],
    *,
    root: Path,
) -> bool:
    if not isinstance(ledger, list) or len(ledger) != len(expected_paths):
        return False
    if any(
        not _keys_exact(item, {"path", "sha256"})
        for item in ledger
    ):
        return False
    paths = [item.get("path") for item in ledger]
    if any(not isinstance(path, str) for path in paths):
        return False
    if len(paths) != len(set(paths)) or set(paths) != expected_paths:
        return False
    return all(
        _sha256(item.get("sha256"))
        and _actual_file_sha256(item["path"], root=root) == item["sha256"]
        for item in ledger
    )


def _file_ledger_sha256(ledger: list[dict[str, Any]]) -> str:
    normalized = [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in sorted(ledger, key=lambda item: item["path"])
    ]
    serialized = json.dumps(
        normalized,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _item36_resource_scope_sha256(alb: Any) -> str | None:
    """Bind billing readback to the exact existing Item36 resource set."""

    if not isinstance(alb, dict):
        return None
    fields = (
        "alb_identity_sha256",
        "vpc_identity_sha256",
        "server_group_identity_sha256",
        "listener_identity_sha256",
        "certificate_identity_sha256",
    )
    scope = {field: alb.get(field) for field in fields}
    public_eips = alb.get("public_eip_identity_sha256s")
    if (
        any(not _sha256(value) for value in scope.values())
        or not isinstance(public_eips, list)
        or len(public_eips) != 2
        or any(not _sha256(value) for value in public_eips)
        or len(set(public_eips)) != 2
    ):
        return None
    scope["public_eip_identity_sha256s"] = sorted(public_eips)
    serialized = json.dumps(
        scope,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _canonical_object_sha256(value: Any) -> str | None:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(serialized).hexdigest()


def _item36_configuration_response_sha256(alb: Any) -> str | None:
    if not isinstance(alb, dict):
        return None
    keys = {
        "alb_identity_sha256",
        "vpc_identity_sha256",
        "server_group_identity_sha256",
        "listener_identity_sha256",
        "certificate_identity_sha256",
        "public_eip_identity_sha256s",
        "region",
        "protocol",
        "listener_port",
        "dual_zone_count",
        "tls_verification",
        "hostname",
        "certificate_status",
        "certificate_dns_names",
        "certificate_sha256",
        "certificate_not_before",
        "certificate_not_after",
        "resource_created_at",
    }
    if not keys.issubset(alb):
        return None
    return _canonical_object_sha256({key: alb[key] for key in sorted(keys)})


def _item36_health_response_sha256(health: Any, alb: Any) -> str | None:
    if (
        not isinstance(health, dict)
        or not isinstance(health.get("backends"), list)
        or not isinstance(alb, dict)
    ):
        return None
    backends = sorted(
        health["backends"],
        key=lambda item: item.get("role", "") if isinstance(item, dict) else "",
    )
    return _canonical_object_sha256(
        {
            "path": health.get("path"),
            "expected_status": health.get("expected_status"),
            "routing_scope": {
                "alb_identity_sha256": alb.get("alb_identity_sha256"),
                "server_group_identity_sha256": alb.get(
                    "server_group_identity_sha256"
                ),
                "listener_identity_sha256": alb.get("listener_identity_sha256"),
            },
            "backends": backends,
            "security_group_rule": health.get("security_group_rule"),
        }
    )


def _item36_probe_response_sha256(probe: Any, alb: Any) -> str | None:
    if not isinstance(probe, dict) or not isinstance(alb, dict):
        return None
    keys = {
        "result",
        "executed_at",
        "connection_mode",
        "endpoint_identity_sha256",
        "hostname",
        "sni_hostname",
        "host_header",
        "path",
        "status_code",
        "tls_verified",
        "certificate_sha256",
    }
    if not keys.issubset(probe):
        return None
    value = {key: probe[key] for key in sorted(keys)}
    value["routing_scope"] = {
        "alb_identity_sha256": alb.get("alb_identity_sha256"),
        "listener_identity_sha256": alb.get("listener_identity_sha256"),
        "certificate_identity_sha256": alb.get("certificate_identity_sha256"),
    }
    return _canonical_object_sha256(value)


def _item36_security_group_response_sha256(
    rule: Any, alb: Any, backends: Any
) -> str | None:
    """Bind the provider rule readback to the exact ALB and two API targets."""

    if (
        not isinstance(rule, dict)
        or not isinstance(alb, dict)
        or not isinstance(backends, list)
    ):
        return None
    keys = {
        "api_security_group_identity_sha256",
        "alb_security_group_identity_sha256",
        "rule_identity_sha256",
        "source_type",
        "source_identity_sha256",
        "protocol",
        "destination_port",
        "target_instance_identity_sha256s",
        "wider_ingress_rule_count",
    }
    if not keys.issubset(rule):
        return None
    return _canonical_object_sha256(
        {
            **{key: rule[key] for key in sorted(keys)},
            "alb_identity_sha256": alb.get("alb_identity_sha256"),
            "backend_instance_identity_sha256s": sorted(
                item.get("instance_identity_sha256")
                for item in backends
                if isinstance(item, dict)
            ),
        }
    )


def _item36_ndr_readback_sha256(fresh_ndr: Any) -> str | None:
    if not isinstance(fresh_ndr, dict) or not isinstance(
        fresh_ndr.get("units"), list
    ):
        return None
    units = sorted(
        fresh_ndr["units"],
        key=lambda item: item.get("name", "") if isinstance(item, dict) else "",
    )
    return _canonical_object_sha256(
        {
            "instance_role": fresh_ndr.get("instance_role"),
            "mask": fresh_ndr.get("mask"),
            "observed_at": fresh_ndr.get("observed_at"),
            "units": units,
        }
    )


def _item36_activation_output_sha256(execution: Any) -> str | None:
    if not isinstance(execution, dict):
        return None
    keys = {
        "role",
        "result",
        "planned_restart_count",
        "exit_code",
        "started_at",
        "finished_at",
        "before_unit_sha256",
        "after_unit_sha256",
        "after_effective_unit_sha256",
        "before_container_identity_sha256",
        "after_container_identity_sha256",
    }
    if not keys.issubset(execution):
        return None
    return _canonical_object_sha256(
        {key: execution[key] for key in sorted(keys)}
    )


def _item36_rollback_unit_sha256(executions: Any) -> str | None:
    if not isinstance(executions, list) or len(executions) != 2:
        return None
    ledger = []
    for execution in executions:
        if not isinstance(execution, dict):
            return None
        role = execution.get("role")
        before_unit = execution.get("before_unit_sha256")
        if not isinstance(role, str) or not _sha256(before_unit):
            return None
        ledger.append({"role": role, "before_unit_sha256": before_unit})
    return _canonical_object_sha256(sorted(ledger, key=lambda item: item["role"]))


def validate_item26_terminal_evidence(
    control: dict[str, Any], *, root: Path = ROOT
) -> tuple[list[str], str | None]:
    """Validate the original Item 26 DoD without later proof structures."""

    errors: list[str] = []
    if control.get("evidence") != ITEM26_TERMINAL_EVIDENCE:
        errors.append("original DoD evidence ref mismatch")
    elif not _verify_path(ITEM26_TERMINAL_EVIDENCE[0]["ref"], root=root):
        errors.append("original DoD evidence path missing")

    reconciliation = control.get("latest_reconciliation")
    if not isinstance(reconciliation, dict):
        return [*errors, "latest reconciliation missing"], None
    if reconciliation.get("status") != (
        "ORIGINAL_ITEM26_DOD_VERIFIED_ZERO_RESIDUE"
    ):
        errors.append("latest reconciliation status mismatch")
    if reconciliation.get("readiness_credit_added") is not True:
        errors.append("latest reconciliation readiness credit mismatch")

    acceptance = reconciliation.get(
        "original_dod_terminal_acceptance_20260823"
    )
    if not isinstance(acceptance, dict):
        return [*errors, "original DoD terminal acceptance missing"], None
    semantic = json.dumps(
        acceptance, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    acceptance_sha256 = hashlib.sha256(semantic).hexdigest()
    if acceptance_sha256 != ITEM26_TERMINAL_ACCEPTANCE_SHA256:
        errors.append("original DoD terminal acceptance mismatch")

    if not errors:
        handoff = (root / ITEM26_TERMINAL_EVIDENCE[0]["ref"]).read_text(
            encoding="utf-8"
        )
        if any(value not in handoff for value in ITEM26_HANDOFF_TERMINAL_BINDINGS):
            errors.append("handoff terminal binding missing")

    return (errors, None) if errors else ([], acceptance_sha256)


def _item34_zoned_clock(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"tracking_real_and_promotion: {field} required")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise ManifestError(
            f"tracking_real_and_promotion: invalid {field}"
        ) from exc
    _require(
        parsed.tzinfo is not None and parsed.utcoffset() is not None,
        f"tracking_real_and_promotion: zoned {field} required",
    )
    return parsed.astimezone(timezone.utc)


def _schema_evidence(
    control: dict[str, Any],
    schema: str,
    *,
    root: Path,
    expected_ref: str | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    matches: list[dict[str, Any]] = []
    for item in control.get("evidence", []):
        if not isinstance(item, dict) or item.get("kind") != "path":
            continue
        ref = item.get("ref")
        if not isinstance(ref, str) or not ref.endswith(".json"):
            continue
        if expected_ref is not None and ref != expected_ref:
            continue
        path = root / ref
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("schema") == schema:
            matches.append(payload)
    if len(matches) != 1:
        return None, [f"exactly one {schema} evidence object required"]
    return matches[0], []


def _validate_item32_snapshot(
    ref: Any,
    *,
    root: Path,
    execution_started_at: datetime | None,
    execution_finished_at: datetime | None,
    observed_at: datetime | None,
) -> tuple[
    dict[str, int] | None,
    int | None,
    str | None,
    int | None,
    set[str] | None,
    set[str] | None,
]:
    if (
        not isinstance(ref, str)
        or not ref.startswith("deploy/production/evidence/")
        or not ref.endswith(".json")
        or not _verify_path(ref, root=root)
    ):
        return None, None, None, None, None, None
    try:
        raw = (root / ref).read_bytes()
        if not raw or len(raw) > 1024 * 1024:
            return None, None, None, None, None, None
        snapshot = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None, None, None, None, None, None
    if (
        not _keys_exact(
            snapshot,
            {"schema_version", "generated_at", "freshness_max_hours", "domains"},
        )
        or not _exact_int(snapshot.get("schema_version"), 1)
        or not _exact_int(snapshot.get("freshness_max_hours"))
        or not 1 <= snapshot["freshness_max_hours"] <= 48
        or not isinstance(snapshot.get("domains"), dict)
        or set(snapshot["domains"]) != ITEM32_TRENDS_DOMAINS
        or _has_sensitive_evidence_key(snapshot)
    ):
        return None, None, None, None, None, None
    generated_at = _evidence_clock(snapshot.get("generated_at"))
    if (
        generated_at is None
        or execution_started_at is None
        or execution_finished_at is None
        or observed_at is None
        or not execution_started_at
        <= generated_at
        <= execution_finished_at
        <= observed_at
        or observed_at - generated_at
        > timedelta(hours=snapshot["freshness_max_hours"])
    ):
        return None, None, None, None, None, None

    real_counts: dict[str, int] = {}
    search_result_domains: set[str] = set()
    search_recommend_domains: set[str] = set()
    total = 0
    keyword_keys = {
        "keyword",
        "search_vol",
        "trend_dir",
        "source",
        "category",
        "sample_count",
        "quality_score",
        "evidence_level",
        "quality_reason",
        "captured_at",
    }
    allowed_sources = ITEM32_REAL_XHS_SOURCES | {"industry_baseline"}
    for domain in ITEM32_TRENDS_DOMAINS:
        bucket = snapshot["domains"].get(domain)
        if not _keys_exact(bucket, {"captured_at", "keywords"}):
            return None, None, None, None, None, None
        if _evidence_clock(bucket.get("captured_at")) != generated_at:
            return None, None, None, None, None, None
        keywords = bucket.get("keywords")
        if not isinstance(keywords, list) or not 12 <= len(keywords) <= 15:
            return None, None, None, None, None, None
        seen: set[str] = set()
        real_count = 0
        for item in keywords:
            keyword = item.get("keyword") if isinstance(item, dict) else None
            normalized_keyword = (
                keyword.strip() if isinstance(keyword, str) else None
            )
            if (
                not _keys_exact(item, keyword_keys)
                or not isinstance(keyword, str)
                or not normalized_keyword
                or keyword != normalized_keyword
                or normalized_keyword in seen
                or item.get("category") != domain
                or item.get("source") not in allowed_sources
                or _evidence_clock(item.get("captured_at")) != generated_at
                or not _exact_int(item.get("search_vol"))
                or not _exact_int(item.get("trend_dir"))
                or not _exact_int(item.get("sample_count"))
                or not _exact_int(item.get("quality_score"))
                or not 5 <= item["quality_score"] <= 100
                or item.get("evidence_level")
                not in {"weak", "medium", "strong"}
                or not isinstance(item.get("quality_reason"), str)
                or not item["quality_reason"].strip()
            ):
                return None, None, None, None, None, None
            seen.add(normalized_keyword)
            qualifies_as_real = (
                item["source"] in ITEM32_REAL_XHS_SOURCES
                and item["quality_score"] >= 55
                and item["evidence_level"] in {"medium", "strong"}
            )
            if qualifies_as_real:
                real_count += 1
            if qualifies_as_real and item["source"] in ITEM32_SEARCH_RESULT_SOURCES:
                search_result_domains.add(domain)
            if qualifies_as_real and item["source"] == "search_recommend":
                search_recommend_domains.add(domain)
        real_counts[domain] = real_count
        total += len(keywords)
    if total > 90:
        return None, None, None, None, None, None
    return (
        real_counts,
        total,
        hashlib.sha256(raw).hexdigest(),
        len(raw),
        search_result_domains,
        search_recommend_domains,
    )


def _item32_plan_window(admission: Any) -> tuple[datetime, datetime, datetime] | None:
    if not isinstance(admission, dict):
        return None
    start = _evidence_clock(admission.get("not_before_utc"))
    deadline = _evidence_clock(admission.get("dispatch_deadline_utc"))
    finish = _evidence_clock(admission.get("must_finish_before_utc"))
    if (
        start is None or deadline is None or finish is None
        or start.isoformat() != admission.get("not_before_utc")
        or deadline.isoformat() != admission.get("dispatch_deadline_utc")
        or finish.isoformat() != admission.get("must_finish_before_utc")
        or admission.get("bucket_date_utc") != start.date().isoformat()
        or deadline.date() != start.date()
        or not start < deadline < finish
        or finish - deadline < timedelta(minutes=20)
        or finish > start.replace(hour=0, minute=0, second=0, microsecond=0)
        + timedelta(days=1)
    ):
        return None
    return start, deadline, finish


def _item32_plan_authorized(
    plan: Any, window: tuple[datetime, datetime, datetime] | None, current: datetime,
) -> datetime | None:
    if not isinstance(plan, dict) or window is None:
        return None
    authorization = plan.get("authorization")
    if (
        not _keys_exact(authorization, {"status", "confirmed_at_utc", "approved_scope_sha256"})
        or authorization.get("status") != "AUTHORIZED"
    ):
        return None
    confirmed = _evidence_clock(authorization.get("confirmed_at_utc"))
    if (
        confirmed is None
        or confirmed.isoformat() != authorization.get("confirmed_at_utc")
        or confirmed > current
        or confirmed >= window[1]
    ):
        return None
    scope = {key: value for key, value in plan.items() if key != "authorization"}
    try:
        digest = hashlib.sha256(json.dumps(
            scope, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest()
    except (TypeError, ValueError):
        return None
    if authorization.get("approved_scope_sha256") != digest:
        return None
    return confirmed


def _item32_v5_profile_valid(plan: Any, *, root: Path) -> bool:
    if not isinstance(plan, dict):
        return False
    image, overlays = plan.get("image_source_sha256"), plan.get("runtime_overlay_sha256")
    browser = {
        "protocol": "pc_v5", "curl_cffi_version": "0.15.0", "node_major": 20,
        "upstream_manifest_ref": "model/vendor/spider_xhs/v5/upstream.json",
        "upstream_manifest_sha256": ITEM32_V5_UPSTREAM_SHA256,
        "cold_initialization": True, "first_homefeed_is_gate": True,
    }
    previous = plan.get("previous_successor")
    if (not isinstance(image, dict) or set(image) != set(ITEM32_IMAGE_SOURCE_SHA256)
            or not isinstance(overlays, dict) or set(overlays) != (
                ITEM32_V5_SOURCE_RETENTION_OVERLAYS if isinstance(plan.get("admission"), dict)
                and plan["admission"].get("work_root") == ITEM32_V5_SOURCE_RETENTION_WORK_ROOT else ITEM32_V5_OVERLAYS)
            or not all(_sha256(value) for value in [*image.values(), *overlays.values()])
            or plan.get("source_sha256") != {**image, **overlays}
            or plan.get("browser_binding") != browser
            or plan["browser_binding"]["cold_initialization"] is not True
            or plan["browser_binding"]["first_homefeed_is_gate"] is not True
            or _actual_file_sha256(browser["upstream_manifest_ref"], root=root) != ITEM32_V5_UPSTREAM_SHA256
            or plan.get("physical_http_budget") != {"initialization": 2, "collection": 34, "total": 36}
            or not _keys_exact(plan.get("bounds"), {"cycles", "provider_requests_per_run_max",
                "provider_requests_per_utc_day_max", "keywords_max", "real_keywords_per_domain_min",
                "domains", "automatic_retry"})
            or not _keys_exact(previous, {"work_root", "files", "provider_call_count", "no_replay"})
            or previous.get("work_root") != "/var/lib/noteai/item32-readonly-successor"
            or not _exact_int(previous.get("provider_call_count"), 1) or previous.get("no_replay") is not True):
        return False
    files = previous.get("files")
    if not isinstance(files, dict) or len(files) != 11:
        return False
    base = previous["work_root"]
    worker_paths = [name for name in files if isinstance(name, str) and re.fullmatch(
        re.escape(base) + r"/run-[A-Za-z0-9_-]{1,64}/worker-receipt\.json", name)]
    if len(worker_paths) != 1:
        return False
    run = str(Path(worker_paths[0]).parent)
    expected = {base + "/item32-admission.json", worker_paths[0], run + "/task-store/hot_keywords.db"}
    for stage in ("item32-successor-package-20260915-79e1e35", "item32-repair-package-20260915-fac5dd0"):
        expected.update(f"/var/lib/noteai/{stage}/{name}" for name in
                        ("dispatch-started.json", "dispatch-child.json", "dispatch-done.json", "dispatch.log"))
    return set(files) == expected and all(
        _keys_exact(value, {"bytes", "sha256"}) and _exact_int(value.get("bytes"))
        and 0 < value["bytes"] <= 64 * 1024 * 1024 and _sha256(value.get("sha256"))
        for value in files.values())


def _item32_sep17_previous_binding(*, root: Path) -> dict[str, Any] | None:
    try:
        raw = (root / ITEM32_V5_SEP16_FINAL_REF).read_bytes()
        if len(raw) != 2386 or hashlib.sha256(raw).hexdigest() != ITEM32_V5_SEP16_FINAL_SHA256:
            return None
        seal = json.loads(raw)
    except (OSError, ValueError):
        return None
    base = "/var/lib/noteai/item32-v5-successor-20260916"
    return {"work_root": base, "package_root": "/var/lib/noteai/item32-v5-package-20260916-92dad86",
            "status": "HOLD", "call_date_utc": "2026-09-16", "collection_admissions": 11,
            "initialization_count": 2, "physical_http_count": 13, "outcome_unknown_count": 0,
            "automatic_retry_count": 0, "no_replay": True, "files": seal["files"],
            "final_readback": {"ref": ITEM32_V5_SEP16_FINAL_REF,
                "host_ref": base + "/hold-final-readback.json", "bytes": 2386,
                "sha256": ITEM32_V5_SEP16_FINAL_SHA256}}


def _item32_network_diagnostics_bindings(*, root: Path) -> dict[str, Any] | None:
    try:
        bindings, values = {}, {}
        for name in ("d1", "d2"):
            ref = f"deploy/production/evidence/production-item32-network-repair-{name}-20260917.json"
            raw = (root / ref).read_bytes()
            if not 0 < len(raw) <= 65536:
                return None
            values[name] = json.loads(raw)
            bindings[name] = {"ref": ref, "host_ref": f"/var/lib/noteai/item32-network-repair-20260917/{name}/result.json",
                "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "finished_at_utc": values[name]["finished_at_utc"]}
        d1, d2 = values["d1"], values["d2"]
        delivery = d2.get("result")
        worker = delivery.get("worker") if isinstance(delivery, dict) else None
        required = {"schema": "noteai.item32.d2_dsl_once.v1", "state": "D2_COMPLETED",
            "d0_sha256": ITEM32_V5_NETWORK_D0_SHA256, "d1_result_sha256": ITEM32_V5_NETWORK_D1_SHA256,
            "d0m_result_sha256": ITEM32_V5_NETWORK_D0M_SHA256, "container_removed": True, "bindings_unchanged": True,
            "automatic_retry_count": 0, "maximum_dsl_get": 1, "session_requests": 0, "collection_requests": 0,
            "database_operations": 0, "business_credentials_loaded": False, "readiness_credit": False,
            "second_dsl_automatically_allowed": False}
        worker_required = {"schema": "noteai.item32.d2_dsl_worker.v1", "state": "DSL_SHAPE_VERIFIED",
            "phase": "response_parse", "http_dispatches_observed": 1, "automatic_retry_count": 0,
            "response_headers_state": "received", "response_body_state": "complete", "dsl_shape_valid": True,
            "body_limit_exceeded": False, "error_type": "none", "business_credentials_loaded": False,
            "response_body_saved": False, "response_headers_saved": False, "dsl_value_saved": False}
        if (bindings["d1"]["bytes"] != 1999 or bindings["d1"]["sha256"] != ITEM32_V5_NETWORK_D1_SHA256
            or bindings["d2"]["bytes"] != 1407 or bindings["d2"]["sha256"] != ITEM32_V5_NETWORK_D2_SHA256
            or not isinstance(worker, dict)
            or not isinstance(delivery, dict) or delivery.get("local_process_reaped") is not True
            or any(type(d2.get(key)) is not type(value) or d2[key] != value for key, value in required.items())
            or any(type(worker.get(key)) is not type(value) or worker[key] != value for key, value in worker_required.items())
            or not _exact_int(worker.get("http_status")) or not 200 <= worker["http_status"] < 300
            or _evidence_clock(d1["finished_at_utc"]) is None or _evidence_clock(d2["finished_at_utc"]) is None
            or _evidence_clock(d1["finished_at_utc"]) > _evidence_clock(d2["finished_at_utc"])):
            return None
        return bindings
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _item32_network_repair_bindings(*, root: Path) -> dict[str, Any] | None:
    try:
        raw = (root / ITEM32_V5_SEP17_FINAL_REF).read_bytes()
        d0_raw = (root / ITEM32_V5_NETWORK_D0_REF).read_bytes()
        if (len(raw) != 6794 or hashlib.sha256(raw).hexdigest() != ITEM32_V5_SEP17_FINAL_SHA256
            or len(d0_raw) != 2895 or hashlib.sha256(d0_raw).hexdigest() != ITEM32_V5_NETWORK_D0_SHA256):
            return None
        seal, d0 = json.loads(raw), json.loads(d0_raw)
        diagnostics = _item32_network_diagnostics_bindings(root=root)
        if diagnostics is None:
            return None
        base = "/var/lib/noteai/item32-v5-successor-20260917"
        return {"previous_v5_initialization_hold": {
            "work_root": base, "package_root": "/var/lib/noteai/item32-v5-package-20260917-84f2e6e",
            "status": "HOLD_INITIALIZATION_NETWORK_UNKNOWN_RESTORED", "call_date_utc": "2026-09-17",
            "collection_admissions": 0, "collection_outcome_unknown_count": 0,
            "initialization_count": 1, "initialization_outcome_unknown_count": 1, "physical_http_count": 1,
            "automatic_retry_count": 0, "no_replay": True, "files": seal["files"],
            "final_readback": {"ref": ITEM32_V5_SEP17_FINAL_REF, "host_ref": base + "/hold-final-readback.json",
                "bytes": 6794, "sha256": ITEM32_V5_SEP17_FINAL_SHA256}},
            "network_repair_preflight": {"ref": ITEM32_V5_NETWORK_D0_REF,
                "host_ref": "/var/lib/noteai/item32-network-repair-20260917/d0.json",
                "bytes": len(d0_raw), "sha256": hashlib.sha256(d0_raw).hexdigest(),
                "finished_at_utc": d0["finished_at_utc"], "diagnostics": diagnostics}}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _item32_source_retention_previous_binding(*, root: Path) -> dict[str, Any] | None:
    try:
        raw = (root / ITEM32_V5_NETWORK_FINAL_REF).read_bytes()
        if len(raw) != 31944 or hashlib.sha256(raw).hexdigest() != ITEM32_V5_NETWORK_FINAL_SHA256:
            return None
        seal = json.loads(raw)
        if (seal["state"] != "V1_FINAL_READBACK_HOLD" or seal["errors"] != []
            or seal["no_in_flight"] is not True or seal["readiness_credit"] is not False
            or seal["admission"]["provider_calls"] != 34 or seal["admission"]["outcome_unknown_count"] != 0
            or seal["retained_store"]["run"]["last_error_code"] != "trends_current_run_xhs_evidence_incomplete"
            or len(seal["own_files"]) != 12 or len(seal["original_files"]) != 36):
            return None
        return {"work_root": ITEM32_V5_NETWORK_WORK_ROOT,
            "package_root": "/var/lib/noteai/item32-v5-network-package-20260917-1136898",
            "source_revision": seal["source_revision"], "run_directory_name": seal["run_directory_name"],
            "status": "HOLD_CURRENT_RUN_EVIDENCE_INCOMPLETE", "call_date_utc": "2026-09-17",
            "collection_admissions": 34, "initialization_count": 2, "physical_http_count": 36,
            "outcome_unknown_count": 0, "automatic_retry_count": 0, "no_replay": True,
            "worker_error_code": "trends_current_run_xhs_evidence_incomplete",
            "finished_at_utc": seal["finished_at_utc"], "files": seal["own_files"],
            "previous_files": seal["original_files"],
            "final_readback": {"ref": ITEM32_V5_NETWORK_FINAL_REF,
                "host_ref": ITEM32_V5_NETWORK_WORK_ROOT + "/final-readback-1136898/final.json",
                "bytes": 31944, "sha256": ITEM32_V5_NETWORK_FINAL_SHA256}}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _item32_v5_physical_valid(physical: Any, summary: Any, attempts: Any,
                             started_at: datetime | None, finished_at: datetime | None) -> bool:
    summary_keys = {"initialization_count", "collection_count", "total_count", "total_limit",
                    "automatic_retry_count", "first_homefeed_is_gate", "worker_receipt_sha256"}
    expected_counts = {"initialization_count": 2, "collection_count": 34, "total_count": 36,
                       "total_limit": 36, "automatic_retry_count": 0}
    if (not _keys_exact(summary, summary_keys)
            or not _keys_exact(physical, summary_keys | {"observations"})
            or any(not _exact_int(summary.get(key), count) for key, count in expected_counts.items())
            or any(not _exact_int(physical.get(key), count) for key, count in expected_counts.items())
            or summary.get("first_homefeed_is_gate") is not True
            or physical.get("first_homefeed_is_gate") is not True
            or not _sha256(summary.get("worker_receipt_sha256"))
            or {key: physical[key] for key in summary_keys} != summary
            or not isinstance(attempts, list) or len(attempts) != 34
            or started_at is None or finished_at is None):
        return False
    observations = physical["observations"]
    if not isinstance(observations, list) or len(observations) != 72:
        return False
    kinds = ["dsl", "session", *(["homefeed"] * 10),
             *[kind for _ in range(12) for kind in ("search_recommend", "search_notes")]]
    previous_end = started_at
    diagnostic_keys = {"http_status", "payload_kind", "success_state", "business_code_kind", "business_code",
                       "nested_business_code_kind", "nested_business_code", "message_present", "message_tags",
                       "recommendation_items_total", "recommendation_items_usable"}
    for index, kind in enumerate(kinds):
        dispatch, response = observations[index * 2:index * 2 + 2]
        if (not isinstance(dispatch, dict) or not isinstance(response, dict)
                or not {"phase", "request_kind", "sequence", "at"} <= set(dispatch)
                or set(dispatch) - {"phase", "request_kind", "sequence", "at", "request_body_bytes"}
                or not {"phase", "request_kind", "sequence", "at", "response_diagnostics"} <= set(response)
                or set(response) - {"phase", "request_kind", "sequence", "at", "response_bytes", "response_diagnostics"}
                or dispatch.get("phase") != "dispatch" or response.get("phase") != "response"
                or any(item.get("request_kind") != kind or not _exact_int(item.get("sequence"), index + 1)
                       for item in (dispatch, response))):
            return False
        first, last = _evidence_clock(dispatch.get("at")), _evidence_clock(response.get("at"))
        if first is None or last is None or not previous_end <= first <= last <= finished_at:
            return False
        previous_end = last
        for item, key in ((dispatch, "request_body_bytes"), (response, "response_bytes")):
            if key in item and (not _exact_int(item[key]) or not 0 <= item[key] <= 2 * 1024 * 1024):
                return False
        diag = response["response_diagnostics"]
        if (not isinstance(diag, dict) or set(diag) - diagnostic_keys
                or not _exact_int(diag.get("http_status")) or not 200 <= diag["http_status"] < 300
                or not isinstance(diag.get("payload_kind"), str)
                or diag.get("payload_kind") not in {"non_json", "object", "array", "scalar"}
                or diag.get("message_tags", []) != []
                or ("message_present" in diag and type(diag["message_present"]) is not bool)):
            return False
        for key, choices in (
            ("success_state", {"true", "false", "absent", "other"}),
            ("business_code_kind", {"absent", "null", "integer", "numeric_string", "omitted"}),
            ("nested_business_code_kind", {"absent", "null", "integer", "numeric_string", "omitted"}),
        ):
            if key in diag and (not isinstance(diag[key], str) or diag[key] not in choices):
                return False
        for key in ("business_code", "nested_business_code"):
            if key in diag and not (
                _exact_int(diag[key]) and abs(diag[key]) <= 999999999
                or isinstance(diag[key], str) and re.fullmatch(r"-?[0-9]{1,9}", diag[key])
            ):
                return False
        recommendation_keys = {"recommendation_items_total", "recommendation_items_usable"}
        recommendation_counts_valid = (
            kind == "search_recommend" and recommendation_keys <= set(diag)
            and _exact_int(diag["recommendation_items_total"])
            and _exact_int(diag["recommendation_items_usable"])
            and 0 <= diag["recommendation_items_usable"] <= diag["recommendation_items_total"])
        if recommendation_keys & set(diag) and not recommendation_counts_valid:
            return False
        if kind != "dsl":
            code = diag.get("business_code")
            code_ok = ((_exact_int(code, 0) and diag.get("business_code_kind") == "integer")
                       or (type(code) is str and code == "0" and diag.get("business_code_kind") == "numeric_string"))
            if recommendation_counts_valid and diag["recommendation_items_usable"] > 0:
                code_ok = code_ok or (
                    _exact_int(code, 1000) and diag.get("business_code_kind") == "integer"
                    or type(code) is str and code == "1000" and diag.get("business_code_kind") == "numeric_string")
            if diag.get("payload_kind") != "object" or diag.get("success_state") != "true" or not code_ok:
                return False
        if "nested_business_code" in diag and not (
            _exact_int(diag["nested_business_code"], 0) or type(diag["nested_business_code"]) is str and diag["nested_business_code"] == "0"
        ):
            return False
        if index >= 2:
            attempt = attempts[index - 2]
            if not isinstance(attempt, dict):
                return False
            admitted, completed = _evidence_clock(attempt.get("admitted_at")), _evidence_clock(attempt.get("completed_at"))
            if (attempt.get("endpoint") != kind or attempt.get("status") != "succeeded"
                    or admitted is None or completed is None or not admitted <= first <= last <= completed):
                return False
    return True


def validate_item32_trends_evidence(
    control: dict[str, Any],
    *,
    root: Path = ROOT,
    now: datetime | None = None,
) -> list[str]:
    """Validate one bounded real-XHS cycle with production DB zero-write."""

    payload, errors = _schema_evidence(
        control,
        ITEM32_TRENDS_EVIDENCE_SCHEMA,
        root=root,
        expected_ref=ITEM32_TRENDS_EVIDENCE,
    )
    if payload is None:
        candidate, _ = _schema_evidence(control, ITEM32_V5_EVIDENCE_SCHEMA, root=root, expected_ref=ITEM32_TRENDS_EVIDENCE)
        if candidate is None:
            return errors
        payload, errors = candidate, []
    v5 = payload.get("schema") == ITEM32_V5_EVIDENCE_SCHEMA
    source_retention = v5 and isinstance(payload.get("successor"), dict) and "previous_v5_full_cycle_hold" in payload["successor"]
    network_repair = v5 and isinstance(payload.get("successor"), dict) and "previous_v5_initialization_hold" in payload["successor"]
    sep17 = v5 and isinstance(payload.get("successor"), dict) and "previous_v5_successor" in payload["successor"]
    v5_work_root = ITEM32_V5_SOURCE_RETENTION_WORK_ROOT if source_retention else ITEM32_V5_NETWORK_WORK_ROOT if network_repair else "/var/lib/noteai/item32-v5-successor-20260917" if sep17 else "/var/lib/noteai/item32-v5-successor-20260916"
    sep17_previous = _item32_sep17_previous_binding(root=root) if sep17 else None
    network_bindings = _item32_network_repair_bindings(root=root) if network_repair else None
    full_cycle_binding = _item32_source_retention_previous_binding(root=root) if source_retention else None
    if not _keys_exact(
        payload,
        {
            "schema",
            "item",
            "status",
            "readiness_credit",
            "observed_at",
            "successor",
            "execution",
            "quality",
            "production_database",
            "task_store",
            "cleanup",
            "secret_values_recorded",
        },
    ):
        errors.append("Item32 terminal evidence schema mismatch")
    if _has_sensitive_evidence_key(payload):
        errors.append("Item32 sensitive field present")
    if (
        not _exact_int(payload.get("item"), 32)
        or payload.get("status") != "VERIFIED"
        or payload.get("readiness_credit") is not True
    ):
        errors.append("Item32 terminal status mismatch")
    observed_at = _evidence_clock(payload.get("observed_at"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if observed_at is None or observed_at > current:
        errors.append("Item32 real observation clock invalid")

    plan_path = root / (ITEM32_V5_SOURCE_RETENTION_EXECUTION_PLAN if source_retention else ITEM32_V5_NETWORK_EXECUTION_PLAN if network_repair else ITEM32_V5_SEP17_EXECUTION_PLAN if sep17 else ITEM32_V5_EXECUTION_PLAN if v5 else ITEM32_EXECUTION_PLAN)
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    except (OSError, json.JSONDecodeError):
        plan = None
        plan_sha256 = None
        errors.append("Item32 canonical execution plan missing")
    try:
        executor_sha256 = hashlib.sha256(
            (root / ITEM32_OUTER_EXECUTOR).read_bytes()
        ).hexdigest()
        adapter_sha256 = hashlib.sha256(
            (root / "model/spider_xhs_http.py").read_bytes()
        ).hexdigest()
        hold_sha256 = hashlib.sha256(
            (root / ITEM32_HOLD_EVIDENCE).read_bytes()
        ).hexdigest()
    except OSError:
        executor_sha256 = adapter_sha256 = hold_sha256 = None
    browser_binding = plan.get("browser_binding") if isinstance(plan, dict) else None
    predecessor_plan = (
        plan.get("predecessor_closure") if isinstance(plan, dict) else None
    )
    admission_plan = plan.get("admission") if isinstance(plan, dict) else None
    plan_window = _item32_plan_window(admission_plan)
    authorization_at = _item32_plan_authorized(plan, plan_window, current)
    plan_bucket = admission_plan.get("bucket_date_utc") if plan_window else None
    image_sources = plan.get("image_source_sha256") if v5 and isinstance(plan, dict) else ITEM32_IMAGE_SOURCE_SHA256
    overlays = plan.get("runtime_overlay_sha256") if v5 and isinstance(plan, dict) else ITEM32_RUNTIME_OVERLAY_SHA256
    config_sha = ITEM32_V5_CONFIG_SHA256 if v5 else ITEM32_EXPECTED_CONFIG_SHA256
    manifest_sha = ITEM32_V5_MANIFEST_SHA256 if v5 else ITEM32_EXPECTED_MANIFEST_SHA256
    plan_valid = bool(
        isinstance(plan, dict)
        and _keys_exact(
            plan,
            {
                "schema",
                "item",
                "status",
                "readiness_credit",
                "authorization",
                "outer_executor",
                "outer_executor_sha256",
                "adapter_overlay_ref",
                "adapter_overlay_sha256",
                "existing_unit_sha256",
                "existing_image_config_sha256",
                "existing_registry_manifest_sha256",
                "registry_manifest_provenance",
                "database_readonly_probe_sha256",
                "image_source_sha256",
                "source_sha256",
                "browser_binding",
                "predecessor_closure",
                "admission",
                "bounds",
                "provider_calls_dispatched",
                "cloud_resources_started",
            } | ({"runtime_overlay_sha256", "physical_http_budget", "previous_successor"} if v5 else set())
              | ({"previous_v5_successor"} if sep17 else set())
              | ({"previous_v5_initialization_hold", "network_repair_preflight"} if network_repair else set())
              | ({"previous_v5_full_cycle_hold"} if source_retention else set()),
        )
        and plan.get("schema") == ("noteai.item32.readonly_successor_plan.v3" if v5 else "noteai.item32.readonly_successor_plan.v2")
        and authorization_at is not None
        and plan_window is not None
        and (not sep17 or (sep17_previous is not None
            and json.dumps(plan.get("previous_v5_successor"), sort_keys=True) == json.dumps(sep17_previous, sort_keys=True)
            and (network_repair or tuple(value.isoformat() for value in plan_window) == (
                "2026-09-17T01:00:00+00:00", "2026-09-17T01:40:00+00:00", "2026-09-17T02:00:00+00:00"))))
        and (not network_repair or (sep17 and network_bindings is not None
            and all(json.dumps(plan.get(key), sort_keys=True) == json.dumps(value, sort_keys=True)
                    for key, value in network_bindings.items())
            and plan_window[0] >= _evidence_clock(network_bindings["network_repair_preflight"]["diagnostics"]["d2"]["finished_at_utc"])
            and authorization_at > _evidence_clock("2026-09-17T01:06:56.372948+00:00")))
        and (not source_retention or (network_repair and full_cycle_binding is not None
            and json.dumps(plan.get("previous_v5_full_cycle_hold"), sort_keys=True) == json.dumps(full_cycle_binding, sort_keys=True)
            and tuple(value.isoformat() for value in plan_window) == (
                "2026-09-18T11:30:00+00:00", "2026-09-18T12:25:00+00:00", "2026-09-18T13:00:00+00:00")
            and authorization_at > _evidence_clock(full_cycle_binding["finished_at_utc"])))
        and _exact_int(plan.get("item"), 32)
        and plan.get("status") == "PREPARED_NOT_EXECUTED"
        and plan.get("readiness_credit") is False
        and plan.get("outer_executor") == ITEM32_OUTER_EXECUTOR
        and plan.get("outer_executor_sha256") == executor_sha256
        and plan.get("adapter_overlay_ref") == "model/spider_xhs_http.py"
        and plan.get("adapter_overlay_sha256") == adapter_sha256
        and plan.get("existing_unit_sha256") == ITEM32_EXPECTED_UNIT_SHA256
        and plan.get("existing_image_config_sha256")
        == config_sha
        and plan.get("existing_registry_manifest_sha256")
        == manifest_sha
        and plan.get("registry_manifest_provenance")
        == "SEALED_RELEASE_ATTESTATION_PLUS_FRESH_LOCAL_CONFIG_READBACK"
        and plan.get("database_readonly_probe_sha256")
        == ITEM32_EXPECTED_DB_PROBE_SHA256
        and (_item32_v5_profile_valid(plan, root=root) if v5 else (
            plan.get("source_sha256") == ITEM32_EFFECTIVE_SOURCE_SHA256
            and plan.get("image_source_sha256") == image_sources
            and _keys_exact(
                browser_binding,
                {
                    "user_agent",
                    "user_agent_sha256",
                    "signer_asset_ref",
                    "signer_asset_sha256",
                    "exact_match_required",
                },
            )
            and isinstance(browser_binding.get("user_agent"), str)
            and hashlib.sha256(
                browser_binding["user_agent"].encode("utf-8")
            ).hexdigest()
            == ITEM32_USER_AGENT_SHA256
            and browser_binding.get("user_agent_sha256")
            == ITEM32_USER_AGENT_SHA256
            and browser_binding.get("signer_asset_ref")
            == "model/vendor/spider_xhs/xhs_main_260411.js"
            and browser_binding.get("signer_asset_sha256")
            == ITEM32_SIGNER_ASSET_SHA256
            and browser_binding.get("exact_match_required") is True
        ))
        and _keys_exact(
            predecessor_plan,
            {
                "evidence_ref",
                "evidence_sha256",
                "original",
                "diagnostic",
                "cumulative_provider_call_count",
            },
        )
        and predecessor_plan.get("evidence_ref") == ITEM32_HOLD_EVIDENCE
        and predecessor_plan.get("evidence_sha256")
        == ITEM32_HOLD_EVIDENCE_SHA256
        and hold_sha256 == ITEM32_HOLD_EVIDENCE_SHA256
        and predecessor_plan.get("original")
        == {
            "status": "HOLD",
            "admission_sha256": ITEM32_ORIGINAL_ADMISSION_SHA256,
            "store_sha256": ITEM32_ORIGINAL_STORE_SHA256,
            "provider_call_count": 1,
            "outcome_unknown_count": 0,
            "automatic_retry_count": 0,
            "no_replay": True,
        }
        and predecessor_plan.get("diagnostic")
        == {
            "status": "HOLD_UNKNOWN",
            "admission_sha256": ITEM32_DIAGNOSTIC_ADMISSION_SHA256,
            "result_sha256": ITEM32_DIAGNOSTIC_RESULT_SHA256,
            "provider_call_count": 1,
            "outcome_unknown_count": 1,
            "automatic_retry_count": 0,
            "no_replay": True,
        }
        and _exact_int(
            predecessor_plan.get("cumulative_provider_call_count"), 2
        )
        and admission_plan
        == {
            "work_root": v5_work_root if v5 else "/var/lib/noteai/item32-readonly-successor",
            "not_before_utc": plan_window[0].isoformat(),
            "bucket_date_utc": plan_bucket,
            "dispatch_deadline_utc": plan_window[1].isoformat(),
            "must_finish_before_utc": plan_window[2].isoformat(),
            "current_utc_day_used_required": 0,
            "current_utc_day_remaining_required": 34,
            "provider_requests_planned": 34,
        }
        and isinstance(plan.get("bounds"), dict)
        and _exact_int(plan["bounds"].get("cycles"), 1)
        and _exact_int(
            plan["bounds"].get("provider_requests_per_run_max"), 34
        )
        and _exact_int(
            plan["bounds"].get("provider_requests_per_utc_day_max"), 34
        )
        and _exact_int(plan["bounds"].get("keywords_max"), 90)
        and _exact_int(
            plan["bounds"].get("real_keywords_per_domain_min"), 12
        )
        and _exact_int(plan["bounds"].get("domains"), 6)
        and _exact_int(plan["bounds"].get("automatic_retry"), 0)
        and _exact_int(plan.get("provider_calls_dispatched"), 0)
        and _exact_int(plan.get("cloud_resources_started"), 0)
    )
    if isinstance(plan, dict) and not plan_valid:
        errors.append("Item32 canonical execution plan binding mismatch")

    successor = payload.get("successor")
    successor_runtime = None
    successor_budget = None
    runtime_observed_at: datetime | None = None
    if not _keys_exact(
        successor,
        {
            "fresh_identity",
            "no_replay",
            "work_root_identity_sha256",
            "predecessor_closure_sha256",
            "original_admission_sha256",
            "original_store_sha256",
            "diagnostic_admission_sha256",
            "diagnostic_result_sha256",
            "predecessor_provider_call_count",
            "predecessors_unchanged",
            "budget",
            "runtime_readback",
        } | ({"previous_successor"} if v5 else set()) | ({"previous_v5_successor"} if sep17 else set())
          | ({"previous_v5_initialization_hold", "network_repair_preflight"} if network_repair else set())
          | ({"previous_v5_full_cycle_hold"} if source_retention else set()),
    ):
        errors.append("Item32 successor evidence schema mismatch")
    else:
        successor_budget = successor.get("budget")
        successor_runtime = successor.get("runtime_readback")
        if (
            successor.get("fresh_identity") is not True
            or successor.get("no_replay") is not True
            or not _sha256(successor.get("work_root_identity_sha256"))
            or successor.get("predecessor_closure_sha256")
            != ITEM32_HOLD_EVIDENCE_SHA256
            or successor.get("original_admission_sha256")
            != ITEM32_ORIGINAL_ADMISSION_SHA256
            or successor.get("original_store_sha256")
            != ITEM32_ORIGINAL_STORE_SHA256
            or successor.get("diagnostic_admission_sha256")
            != ITEM32_DIAGNOSTIC_ADMISSION_SHA256
            or successor.get("diagnostic_result_sha256")
            != ITEM32_DIAGNOSTIC_RESULT_SHA256
            or not _exact_int(
                successor.get("predecessor_provider_call_count"), 48 if source_retention else 14 if sep17 else 3 if v5 else 2
            )
            or successor.get("predecessors_unchanged") is not True
        ):
            errors.append("Item32 successor predecessor binding mismatch")
        if (
            not _keys_exact(
                successor_budget,
                {
                    "bucket_date",
                    "used_before",
                    "remaining_before",
                    "planned",
                    "limit",
                },
            )
            or not isinstance(successor_budget.get("bucket_date"), str)
            or successor_budget.get("bucket_date")
            != plan_bucket
            or not _exact_int(successor_budget.get("used_before"), 0)
            or not _exact_int(successor_budget.get("remaining_before"), 34)
            or not _exact_int(successor_budget.get("planned"), 34)
            or not _exact_int(successor_budget.get("limit"), 34)
        ):
            errors.append("Item32 successor UTC budget mismatch")
        if not _keys_exact(
            successor_runtime,
            {
                "observed_at",
                "image_config_sha256",
                "registry_manifest_sha256",
                "registry_manifest_provenance",
                "adapter_overlay_sha256",
                "runtime_overlay_sha256",
                } | ({"protocol", "curl_cffi_version", "node_major", "upstream_manifest_sha256"} if v5 else
                 {"user_agent_sha256", "signer_asset_sha256", "user_agent_exact_match"}),
        ):
            errors.append("Item32 successor runtime readback schema mismatch")
        else:
            runtime_observed_at = _evidence_clock(
                successor_runtime.get("observed_at")
            )
            if (
                runtime_observed_at is None
                or successor_runtime.get("image_config_sha256")
                != config_sha
                or successor_runtime.get("registry_manifest_sha256")
                != manifest_sha
                or successor_runtime.get("registry_manifest_provenance")
                != (
                    "SEALED_RELEASE_ATTESTATION_PLUS_"
                    "FRESH_LOCAL_CONFIG_READBACK"
                )
                or not isinstance(overlays, dict)
                or successor_runtime.get("adapter_overlay_sha256") != overlays.get("model/spider_xhs_http.py")
                or successor_runtime.get("runtime_overlay_sha256") != overlays
                or (any(successor_runtime.get(key) != value for key, value in {
                    "protocol": "pc_v5", "curl_cffi_version": "0.15.0", "node_major": 20,
                    "upstream_manifest_sha256": ITEM32_V5_UPSTREAM_SHA256,
                }.items()) if v5 else (
                    successor_runtime.get("user_agent_sha256") != ITEM32_USER_AGENT_SHA256
                    or successor_runtime.get("signer_asset_sha256") != ITEM32_SIGNER_ASSET_SHA256
                    or successor_runtime.get("user_agent_exact_match") is not True
                ))
            ):
                errors.append("Item32 successor runtime binding mismatch")

    if v5:
        previous = successor.get("previous_successor") if isinstance(successor, dict) else None
        expected_previous = None
        if _item32_v5_profile_valid(plan, root=root):
            raw = (json.dumps(plan["previous_successor"]["files"], ensure_ascii=False,
                              sort_keys=True, indent=2) + "\n").encode("utf-8")
            expected_previous = {"files_sha256": hashlib.sha256(raw).hexdigest(),
                                 "provider_call_count": 1, "call_date_utc": "2026-09-15", "no_replay": True}
        if (expected_previous is None or previous != expected_previous
                or not _exact_int(previous.get("provider_call_count"), 1)
                or previous.get("no_replay") is not True
                or plan_bucket == "2026-09-15"
                or successor.get("work_root_identity_sha256") != hashlib.sha256(
                    ("noteai-item32:successor-work-root:" + v5_work_root).encode()).hexdigest()):
            errors.append("Item32 previous successor closure mismatch")
    if sep17:
        expected_previous_v5 = ({**sep17_previous, "host_final_readback_verified": True,
                                 "database_readonly_probes_verified": True} if sep17_previous is not None else None)
        if (expected_previous_v5 is None or (not network_repair and plan_bucket != "2026-09-17")
            or json.dumps(successor.get("previous_v5_successor"), sort_keys=True)
            != json.dumps(expected_previous_v5, sort_keys=True)):
            errors.append("Item32 Sep16 v5 HOLD closure mismatch")
    if network_repair:
        expected = ({"previous_v5_initialization_hold": {
                        **network_bindings["previous_v5_initialization_hold"],
                        "host_final_readback_verified": True, "database_readonly_probes_verified": True},
                     "network_repair_preflight": {
                        **network_bindings["network_repair_preflight"], "host_readback_verified": True}}
                    if network_bindings is not None else None)
        if (expected is None or not sep17
            or any(json.dumps(successor.get(key), sort_keys=True) != json.dumps(value, sort_keys=True)
                   for key, value in expected.items())):
            errors.append("Item32 Sep17 initialization UNKNOWN closure mismatch")
    if source_retention:
        expected = ({**full_cycle_binding, "host_final_readback_verified": True,
                     "database_readonly_probes_verified": True, "collection_ledger_verified": True}
                    if full_cycle_binding is not None else None)
        if (expected is None or not network_repair or plan_bucket != "2026-09-18"
            or json.dumps(successor.get("previous_v5_full_cycle_hold"), sort_keys=True) != json.dumps(expected, sort_keys=True)):
            errors.append("Item32 prior full-cycle HOLD closure mismatch")

    execution = payload.get("execution")
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempt_identities: set[str] = set()
    if not isinstance(execution, dict):
        errors.append("Item32 execution evidence missing")
    else:
        if not _keys_exact(
            execution,
            {
                "cycle_count",
                "provider_request_count",
                "provider_request_limit",
                "attempt_count",
                "succeeded_attempt_count",
                "automatic_retry_count",
                "all_admitted_attempts_succeeded",
                "outcome_unknown_count",
                "challenge_detected",
                "authenticated_session",
                "source",
                "started_at",
                "finished_at",
                "run_identity_sha256",
                "task_store_identity_sha256",
                "container_identity_sha256",
                "outer_executor_sha256",
                "execution_plan_sha256",
                "image_config_sha256",
                "registry_manifest_sha256",
                "source_sha256",
                "endpoint_counts",
                "attempt_audit_ref",
                "attempt_audit_sha256",
            } | ({"physical_http"} if v5 else set()),
        ):
            errors.append("Item32 execution evidence schema mismatch")
        request_count = execution.get("provider_request_count")
        endpoint_counts = execution.get("endpoint_counts")
        if (
            not _exact_int(execution.get("cycle_count"), 1)
            or not _exact_int(request_count, 34)
            or not _exact_int(execution.get("provider_request_limit"), 34)
            or not _exact_int(execution.get("attempt_count"), 34)
            or not _exact_int(execution.get("succeeded_attempt_count"), 34)
            or not _exact_int(execution.get("automatic_retry_count"), 0)
            or execution.get("all_admitted_attempts_succeeded") is not True
            or not _exact_int(execution.get("outcome_unknown_count"), 0)
            or execution.get("challenge_detected") is not False
            or execution.get("authenticated_session") is not True
            or execution.get("source") != "real_xhs"
            or not _sha256(execution.get("run_identity_sha256"))
            or not _sha256(execution.get("task_store_identity_sha256"))
            or not _sha256(execution.get("container_identity_sha256"))
        ):
            errors.append("Item32 bounded real-XHS execution mismatch")
        if (
            not isinstance(endpoint_counts, dict)
            or set(endpoint_counts)
            != {"homefeed", "search_recommend", "search_notes"}
            or not _exact_int(endpoint_counts.get("homefeed"), 10)
            or not _exact_int(endpoint_counts.get("search_recommend"), 12)
            or not _exact_int(endpoint_counts.get("search_notes"), 12)
        ):
            errors.append("Item32 endpoint request ledger mismatch")
        started_at = _evidence_clock(execution.get("started_at"))
        finished_at = _evidence_clock(execution.get("finished_at"))
        if (
            started_at is None
            or finished_at is None
            or observed_at is None
            or not started_at <= finished_at <= observed_at
        ):
            errors.append("Item32 execution clock ordering invalid")
        if (
            started_at is None
            or runtime_observed_at is None
            or runtime_observed_at > started_at
            or started_at - runtime_observed_at
            > ITEM32_RUNTIME_READBACK_MAX_AGE
            or not isinstance(successor_budget, dict)
            or successor_budget.get("bucket_date")
            != started_at.date().isoformat()
            or finished_at is None
            or finished_at.date() != started_at.date()
            or started_at.date().isoformat()
            != plan_bucket
        ):
            errors.append("Item32 successor admission clock mismatch")
        if (
            plan_window is None or authorization_at is None
            or started_at is None or finished_at is None
            or not plan_window[0] <= started_at < plan_window[1]
            or not authorization_at <= started_at <= finished_at < plan_window[2]
        ):
            errors.append("Item32 approved execution window mismatch")
        if plan_valid:
            expected_sources = plan.get("source_sha256")
            actual_sources = execution.get("source_sha256")
            outer_executor = plan.get("outer_executor")
            outer_executor_sha256 = plan.get("outer_executor_sha256")
            sources_current = all(
                _actual_file_sha256(path, root=root) == digest
                for path, digest in expected_sources.items()
            )
            if (
                execution.get("execution_plan_sha256") != plan_sha256
                or execution.get("outer_executor_sha256")
                != outer_executor_sha256
                or not _sha256(outer_executor_sha256)
                or _actual_file_sha256(outer_executor, root=root)
                != outer_executor_sha256
                or execution.get("image_config_sha256")
                != plan.get("existing_image_config_sha256")
                or execution.get("registry_manifest_sha256")
                != plan.get("existing_registry_manifest_sha256")
                or actual_sources != expected_sources
                or not sources_current
            ):
                errors.append("Item32 canonical executor/release binding mismatch")
        else:
            errors.append("Item32 canonical executor/release binding mismatch")

        audit_ref = execution.get("attempt_audit_ref")
        audit, audit_sha = _read_json_artifact(
            audit_ref,
            ITEM32_ATTEMPT_AUDIT_SCHEMA,
            root=root,
        )
        attempts = audit.get("attempts") if isinstance(audit, dict) else None
        audit_started_at = (
            _evidence_clock(audit.get("started_at"))
            if isinstance(audit, dict)
            else None
        )
        audit_finished_at = (
            _evidence_clock(audit.get("finished_at"))
            if isinstance(audit, dict)
            else None
        )
        attempt_endpoints: dict[str, int] = {
            "homefeed": 0,
            "search_recommend": 0,
            "search_notes": 0,
        }
        expected_endpoint_sequence = ["homefeed"] * 10 + [
            endpoint
            for _ in range(12)
            for endpoint in ("search_recommend", "search_notes")
        ]
        attempts_valid = isinstance(attempts, list) and len(attempts) == 34
        if attempts_valid:
            for ordinal, attempt in enumerate(attempts, start=1):
                admitted_at = (
                    _evidence_clock(attempt.get("admitted_at"))
                    if isinstance(attempt, dict)
                    else None
                )
                completed_at = (
                    _evidence_clock(attempt.get("completed_at"))
                    if isinstance(attempt, dict)
                    else None
                )
                endpoint = attempt.get("endpoint") if isinstance(attempt, dict) else None
                identity = (
                    attempt.get("identity_sha256")
                    if isinstance(attempt, dict)
                    else None
                )
                if (
                    not _keys_exact(
                        attempt,
                        {
                            "ordinal",
                            "endpoint",
                            "status",
                            "admitted_at",
                            "completed_at",
                            "identity_sha256",
                        },
                    )
                    or not _exact_int(attempt.get("ordinal"), ordinal)
                    or endpoint != expected_endpoint_sequence[ordinal - 1]
                    or attempt.get("status") != "succeeded"
                    or not _sha256(identity)
                    or identity in attempt_identities
                    or admitted_at is None
                    or completed_at is None
                    or started_at is None
                    or finished_at is None
                    or not started_at <= admitted_at <= completed_at <= finished_at
                    or admitted_at.date().isoformat()
                    != plan_bucket
                    or completed_at.date().isoformat()
                    != plan_bucket
                ):
                    attempts_valid = False
                    break
                attempt_identities.add(identity)
                attempt_endpoints[endpoint] += 1
        if (
            not isinstance(audit, dict)
            or not _keys_exact(
                audit,
                {
                    "schema",
                    "run_identity_sha256",
                    "task_store_identity_sha256",
                    "started_at",
                    "finished_at",
                    "provider_request_limit",
                    "attempts",
                    "secret_values_recorded",
                } | ({"physical_http"} if v5 else set()),
            )
            or audit_sha != execution.get("attempt_audit_sha256")
            or audit.get("run_identity_sha256")
            != execution.get("run_identity_sha256")
            or audit.get("task_store_identity_sha256")
            != execution.get("task_store_identity_sha256")
            or audit_started_at != started_at
            or audit_finished_at != finished_at
            or not _exact_int(audit.get("provider_request_limit"), 34)
            or audit.get("secret_values_recorded") is not False
            or _has_sensitive_evidence_key(audit)
            or not attempts_valid
            or attempt_endpoints != endpoint_counts
        ):
            errors.append("Item32 provider attempt audit binding mismatch")
        if v5 and not _item32_v5_physical_valid(
            audit.get("physical_http") if isinstance(audit, dict) else None,
            execution.get("physical_http"), attempts, started_at, finished_at,
        ):
            errors.append("Item32 physical HTTP/init/collection evidence mismatch")

    quality = payload.get("quality")
    if not isinstance(quality, dict):
        errors.append("Item32 real-source quality evidence missing")
    else:
        if not _keys_exact(
            quality,
            {
                "real_keyword_counts_by_domain",
                "keyword_count",
                "search_result_domains",
                "search_recommend_domains",
                "snapshot_ref",
                "snapshot_sha256",
                "snapshot_size",
            },
        ):
            errors.append("Item32 quality evidence schema mismatch")
        counts = quality.get("real_keyword_counts_by_domain")
        search_domains = quality.get("search_result_domains")
        recommend_domains = quality.get("search_recommend_domains")
        keyword_count = quality.get("keyword_count")
        if (
            not isinstance(counts, dict)
            or set(counts) != ITEM32_TRENDS_DOMAINS
            or any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 12 <= value <= 15
                for value in counts.values()
            )
            or not _exact_int(keyword_count)
            or keyword_count < sum(counts.values())
            or keyword_count > 90
            or not isinstance(search_domains, list)
            or len(search_domains) != len(ITEM32_TRENDS_DOMAINS)
            or any(not isinstance(value, str) for value in search_domains)
            or set(search_domains) != ITEM32_TRENDS_DOMAINS
            or not isinstance(recommend_domains, list)
            or len(recommend_domains) != len(ITEM32_TRENDS_DOMAINS)
            or any(not isinstance(value, str) for value in recommend_domains)
            or set(recommend_domains) != ITEM32_TRENDS_DOMAINS
        ):
            errors.append("Item32 six-domain real-source quality mismatch")
        digest = quality.get("snapshot_sha256")
        size = quality.get("snapshot_size")
        snapshot_ref = quality.get("snapshot_ref")
        declared_search_domains = (
            set(search_domains)
            if isinstance(search_domains, list)
            and all(isinstance(value, str) for value in search_domains)
            else None
        )
        declared_recommend_domains = (
            set(recommend_domains)
            if isinstance(recommend_domains, list)
            and all(isinstance(value, str) for value in recommend_domains)
            else None
        )
        (
            snapshot_real_counts,
            snapshot_keyword_count,
            snapshot_sha256,
            snapshot_size,
            snapshot_search_domains,
            snapshot_recommend_domains,
        ) = _validate_item32_snapshot(
            snapshot_ref,
            root=root,
            execution_started_at=started_at,
            execution_finished_at=finished_at,
            observed_at=observed_at,
        )
        if (
            not _sha256(digest)
            or not _exact_int(size)
            or not 1 <= size <= 1024 * 1024
            or not isinstance(snapshot_ref, str)
            or not snapshot_ref.startswith("deploy/production/evidence/")
            or snapshot_ref == ITEM32_TRENDS_EVIDENCE
            or snapshot_sha256 != digest
            or snapshot_size != size
            or snapshot_real_counts != counts
            or snapshot_search_domains != declared_search_domains
            or snapshot_recommend_domains != declared_recommend_domains
            or snapshot_keyword_count is None
            or not _exact_int(keyword_count)
            or snapshot_keyword_count != keyword_count
        ):
            errors.append("Item32 snapshot identity invalid")

    database = payload.get("production_database")
    database_invalid = not isinstance(database, dict)
    proof: dict[str, Any] | None = None
    if isinstance(database, dict):
        if not _keys_exact(
            database,
            {
                "server_enforced_read_only",
                "write_count",
                "tuple_write_count",
                "write_tables",
                "xid_assigned",
                "transaction_rolled_back",
                "session_identity_sha256",
                "proof_ref",
                "proof_sha256",
                "before_observed_at",
                "after_observed_at",
            },
        ):
            errors.append("Item32 production database evidence schema mismatch")
        before_at = _evidence_clock(database.get("before_observed_at"))
        after_at = _evidence_clock(database.get("after_observed_at"))
        proof, proof_sha = _read_json_artifact(
            database.get("proof_ref"),
            ITEM32_DATABASE_PROOF_SCHEMA,
            root=root,
        )
        database_invalid = (
            database.get("server_enforced_read_only") is not True
            or not _exact_int(database.get("write_count"), 0)
            or not _exact_int(database.get("tuple_write_count"), 0)
            or database.get("write_tables") != []
            or database.get("xid_assigned") is not False
            or database.get("transaction_rolled_back") is not True
            or not _sha256(database.get("session_identity_sha256"))
            or not _sha256(database.get("proof_sha256"))
            or before_at is None
            or after_at is None
            or started_at is None
            or finished_at is None
            or observed_at is None
            or not before_at <= started_at <= finished_at <= after_at <= observed_at
            or not isinstance(proof, dict)
            or not _keys_exact(
                proof,
                {
                    "schema",
                    "run_identity_sha256",
                    "session_identity_sha256",
                    "server_enforced_read_only",
                    "write_count",
                    "tuple_write_count",
                    "write_tables",
                    "xid_assigned",
                    "transaction_rolled_back",
                    "before_observed_at",
                    "after_observed_at",
                    "readback_query_sha256",
                    "secret_values_recorded",
                },
            )
            or proof_sha != database.get("proof_sha256")
            or proof.get("run_identity_sha256")
            != (
                execution.get("run_identity_sha256")
                if isinstance(execution, dict)
                else None
            )
            or proof.get("session_identity_sha256")
            != database.get("session_identity_sha256")
            or proof.get("server_enforced_read_only") is not True
            or not _exact_int(proof.get("write_count"), 0)
            or not _exact_int(proof.get("tuple_write_count"), 0)
            or proof.get("write_tables") != []
            or proof.get("xid_assigned") is not False
            or proof.get("transaction_rolled_back") is not True
            or _evidence_clock(proof.get("before_observed_at")) != before_at
            or _evidence_clock(proof.get("after_observed_at")) != after_at
            or proof.get("readback_query_sha256")
            != ITEM32_EXPECTED_DB_PROBE_SHA256
            or not plan_valid
            or proof.get("readback_query_sha256")
            != plan.get("database_readonly_probe_sha256")
            or proof.get("secret_values_recorded") is not False
            or _has_sensitive_evidence_key(proof)
        )
    if database_invalid:
        errors.append("Item32 production database zero-write proof missing")
    task_store = payload.get("task_store")
    if (
        not isinstance(task_store, dict)
        or not _keys_exact(
            task_store,
            {
                "isolated",
                "production_database_url_present",
                "production_data_mount_present",
                "docker_socket_mount_present",
                "path_identity_sha256",
            },
        )
        or task_store.get("isolated") is not True
        or task_store.get("production_database_url_present") is not False
        or task_store.get("production_data_mount_present") is not False
        or task_store.get("docker_socket_mount_present") is not False
        or not _sha256(task_store.get("path_identity_sha256"))
    ):
        errors.append("Item32 isolated task-store boundary missing")
    cleanup = payload.get("cleanup")
    if (
        not isinstance(cleanup, dict)
        or not _keys_exact(
            cleanup,
            {"task_container_count", "postpaid_resources_started"},
        )
        or not _exact_int(cleanup.get("task_container_count"), 0)
        or not _exact_int(cleanup.get("postpaid_resources_started"), 0)
    ):
        errors.append("Item32 task-exact cleanup missing")
    if payload.get("secret_values_recorded") is not False:
        errors.append("Item32 secret-value exclusion missing")
    identity_values = [
        execution.get("run_identity_sha256") if isinstance(execution, dict) else None,
        execution.get("task_store_identity_sha256")
        if isinstance(execution, dict)
        else None,
        execution.get("container_identity_sha256")
        if isinstance(execution, dict)
        else None,
        database.get("session_identity_sha256")
        if isinstance(database, dict)
        else None,
        task_store.get("path_identity_sha256")
        if isinstance(task_store, dict)
        else None,
        proof.get("readback_query_sha256") if isinstance(proof, dict) else None,
    ]
    valid_identity_values = [value for value in identity_values if _sha256(value)]
    if (
        len(valid_identity_values) != len(identity_values)
        or len(set(valid_identity_values)) != len(valid_identity_values)
        or any(value in attempt_identities for value in valid_identity_values)
    ):
        errors.append("Item32 semantic identity domains are not distinct")
    return errors


def _validate_item33_snapshot(
    ref: Any,
    *,
    root: Path,
) -> tuple[
    dict[str, int] | None,
    dict[str, int] | None,
    set[str] | None,
    set[str] | None,
    str | None,
    int | None,
    datetime | None,
]:
    """Read the bounded published Trends snapshot without trusting its summary."""

    if (
        not isinstance(ref, str)
        or not ref.startswith("deploy/production/evidence/")
        or not ref.endswith(".json")
        or not _verify_path(ref, root=root)
    ):
        return None, None, None, None, None, None, None
    try:
        raw = (root / ref).read_bytes()
        if not 1 <= len(raw) <= 1024 * 1024:
            return None, None, None, None, None, None, None
        snapshot = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None, None, None, None, None, None, None
    if (
        not _keys_exact(
            snapshot,
            {"schema_version", "generated_at", "freshness_max_hours", "domains"},
        )
        or not _exact_int(snapshot.get("schema_version"), 1)
        or not _exact_int(snapshot.get("freshness_max_hours"))
        or not 1 <= snapshot["freshness_max_hours"] <= 48
        or not isinstance(snapshot.get("domains"), dict)
        or set(snapshot["domains"]) != ITEM32_TRENDS_DOMAINS
        or _has_sensitive_evidence_key(snapshot)
    ):
        return None, None, None, None, None, None, None
    generated_at = _evidence_clock(snapshot.get("generated_at"))
    if generated_at is None:
        return None, None, None, None, None, None, None
    row_keys = {
        "keyword",
        "search_vol",
        "trend_dir",
        "source",
        "category",
        "sample_count",
        "quality_score",
        "evidence_level",
        "quality_reason",
        "captured_at",
    }
    counts: dict[str, int] = {}
    real_counts: dict[str, int] = {}
    search_result_domains: set[str] = set()
    search_recommend_domains: set[str] = set()
    allowed_sources = ITEM32_REAL_XHS_SOURCES | {"industry_baseline"}
    for domain in ITEM32_TRENDS_DOMAINS:
        bucket = snapshot["domains"].get(domain)
        if (
            not _keys_exact(bucket, {"captured_at", "keywords"})
            or _evidence_clock(bucket.get("captured_at")) != generated_at
            or not isinstance(bucket.get("keywords"), list)
            or not 12 <= len(bucket["keywords"]) <= 15
        ):
            return None, None, None, None, None, None, None
        seen: set[str] = set()
        real_count = 0
        for row in bucket["keywords"]:
            keyword = row.get("keyword") if isinstance(row, dict) else None
            normalized_keyword = (
                keyword.strip() if isinstance(keyword, str) else None
            )
            source = row.get("source") if isinstance(row, dict) else None
            evidence_level = (
                row.get("evidence_level") if isinstance(row, dict) else None
            )
            if (
                not _keys_exact(row, row_keys)
                or not isinstance(keyword, str)
                or not normalized_keyword
                or keyword != normalized_keyword
                or normalized_keyword in seen
                or row.get("category") != domain
                or not isinstance(source, str)
                or source not in allowed_sources
                or _evidence_clock(row.get("captured_at")) != generated_at
                or not _exact_int(row.get("search_vol"))
                or not _exact_int(row.get("trend_dir"))
                or not _exact_int(row.get("sample_count"))
                or not _exact_int(row.get("quality_score"))
                or not 5 <= row["quality_score"] <= 100
                or not isinstance(evidence_level, str)
                or evidence_level not in {"weak", "medium", "strong"}
                or not isinstance(row.get("quality_reason"), str)
                or not row["quality_reason"].strip()
            ):
                return None, None, None, None, None, None, None
            seen.add(normalized_keyword)
            qualifies_as_real = (
                source in ITEM32_REAL_XHS_SOURCES
                and row["quality_score"] >= 55
            )
            if qualifies_as_real:
                real_count += 1
            if qualifies_as_real and source in ITEM32_SEARCH_RESULT_SOURCES:
                search_result_domains.add(domain)
            if qualifies_as_real and source == "search_recommend":
                search_recommend_domains.add(domain)
        counts[domain] = len(bucket["keywords"])
        real_counts[domain] = real_count
    return (
        counts,
        real_counts,
        search_result_domains,
        search_recommend_domains,
        hashlib.sha256(raw).hexdigest(),
        len(raw),
        generated_at,
    )


def _item33_v5_capture_valid(
    binding: Any, cycle: Any, writes: Any, *, root: Path, observed_at: Any = None,
) -> bool:
    """Bind the managed writer's independent, counted journal to this cycle."""
    if (not _keys_exact(binding, {
            "source_sha256", "launcher_sha256", "configuration_sha256",
            "activation_identity_sha256", "receipt_ref", "receipt_sha256",
        }) or not isinstance(cycle, dict) or not isinstance(writes, dict)
        or not isinstance(writes.get("distinct_rows_touched_by_table"), dict)
        or any(not _exact_int(value) for value in writes["distinct_rows_touched_by_table"].values())
        or not _keys_exact(binding.get("source_sha256"), ITEM33_V5_CAPTURE_TOOLS)
        or any(not _sha256(value) or _actual_file_sha256(name, root=root) != value
               for name, value in binding["source_sha256"].items())
        or binding.get("launcher_sha256") != ITEM33_V5_LAUNCHER_SHA256
        or not _sha256(binding.get("configuration_sha256"))
        or not _sha256(binding.get("activation_identity_sha256"))
        or binding.get("activation_identity_sha256") != cycle.get("activation_identity_sha256")
        or cycle.get("activation_identity_sha256") == cycle.get("run_identity_sha256")
        or binding.get("receipt_ref") != ITEM33_V5_CAPTURE_EVIDENCE
        or not _sha256(binding.get("receipt_sha256"))):
        return False
    seal, seal_sha = _read_json_artifact(
        ITEM33_V5_CAPTURE_EVIDENCE, "noteai.item33.runtime_capture_seal.v1", root=root,
    )
    if (seal is None or seal_sha != binding["receipt_sha256"]
        or _has_sensitive_evidence_key(seal)
        or seal.get("activation_identity_sha256") != cycle["activation_identity_sha256"]
        or seal.get("run_identity_sha256") != cycle.get("run_identity_sha256")
        or seal.get("bucket_key") != cycle.get("bucket_key")
        or seal.get("config_sha256") != binding["configuration_sha256"]
        or seal.get("accepted_source_sha256") != ITEM33_V5_RUNTIME_OVERLAY_SHA256
        or seal.get("instrumentation_sha256") != {
            **binding["source_sha256"],
            "scripts/render_run_market_timing.sh": binding["launcher_sha256"],
        }):
        return False
    journal = seal.get("journal")
    if (not isinstance(journal, dict) or journal.get("ref") != ITEM33_V5_CAPTURE_JOURNAL
        or not _verify_path(ITEM33_V5_CAPTURE_JOURNAL, root=root)):
        return False
    try:
        # Import the reviewed local verifier, never a module named by evidence.
        import item33_trends_runtime_capture as capture
        import item33_trends_dml_capture as dml
        import item33_trends_capture_catalog as catalog
        for module, ref in ((capture, "tools/item33_trends_runtime_capture.py"),
                            (dml, "tools/item33_trends_dml_capture.py")):
            if hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() != binding["source_sha256"][ref]:
                return False
        proof = seal.get("catalog_proof")
        if (not isinstance(proof, dict) or proof.get("source_ref") != catalog.SOURCE_REF
            or proof.get("source_sha256") != _actual_file_sha256(catalog.SOURCE_REF, root=root)
            or proof.get("source_sha256") != hashlib.sha256(Path(catalog.__file__).read_bytes()).hexdigest()):
            return False
        clocks = [_evidence_clock(value) for value in (
            proof["before"]["observed_at"], cycle.get("started_at"), cycle.get("completed_at"),
            proof["after"]["observed_at"], observed_at)]
        if None in clocks or clocks != sorted(clocks):
            return False
        raw = (root / ITEM33_V5_CAPTURE_JOURNAL).read_bytes()
        if (not 0 < len(raw) <= 16 * 1024 * 1024
            or not _exact_int(journal.get("bytes"), len(raw))
            or journal.get("sha256") != hashlib.sha256(raw).hexdigest()):
            return False
        aggregate = capture.verify_capture_artifacts(seal, raw)
        if not isinstance(aggregate, dict) or dml.cycle_contract_errors(
            aggregate, request_count=cycle.get("provider_request_count"),
            keyword_count=writes.get("distinct_rows_touched_by_table", {}).get("hot_keywords"),
        ):
            return False
        if (any(aggregate.get(key) != writes.get(key) for key in (
                "out_of_contract_row_mutations", "delete_rows", "truncate_count",
                "forbidden_table_mutations", "atomic_publish"))
            or {name: aggregate["distinct_rows_touched_by_table"].get(name)
                for name in ITEM33_ALLOWED_WRITE_TABLES} != writes.get("distinct_rows_touched_by_table")):
            return False
    except (ImportError, OSError, AttributeError, KeyError, TypeError, ValueError):
        return False
    return True


def _item33_v5_capture_closed_valid(item: dict, cycle: dict, seal: dict, teardown: dict, *, root: Path, terminal_at) -> bool:
    """Original collector/host facts must prove cleanup, not just a valid seal."""
    binding = item.get("capture_close")
    if not _keys_exact(binding, {name + suffix for name in ITEM33_V5_CAPTURE_CLOSE_REFS for suffix in ("_ref", "_sha256")}):
        return False
    try:
        facts = {}
        for name, ref in ITEM33_V5_CAPTURE_CLOSE_REFS.items():
            if binding[name + "_ref"] != ref or not _verify_path(ref, root=root):
                return False
            raw = (root / ref).read_bytes()
            if not 0 < len(raw) <= 65536 or hashlib.sha256(raw).hexdigest() != binding[name + "_sha256"]:
                return False
            facts[name] = json.loads(raw, object_pairs_hook=_json_object_without_duplicate_keys)
            if not isinstance(facts[name], dict) or _has_sensitive_evidence_key(facts[name]):
                return False
        result, closed, host = (facts[name] for name in ("service_result", "close", "host"))
        common = {"activation_identity_sha256": cycle["activation_identity_sha256"],
                  "configuration_sha256": seal["config_sha256"], "bucket_key": cycle["bucket_key"]}
        if (not _keys_exact(result, {"schema", "state", *common, "observed_at", "run_identity_sha256",
                "capture_seal_sha256", "provider_calls", "schema_changes", "secret_values_recorded"})
            or result["schema"] != "noteai.item33.capture_service_result.v1" or result["state"] != "SEALED"
            or result["run_identity_sha256"] != cycle["run_identity_sha256"]
            or result["capture_seal_sha256"] != item["capture_receipt_sha256"]
            or any(result[key] != value or closed.get(key) != value for key, value in common.items())
            or any(not _exact_int(result[key], 0) for key in ("provider_calls", "schema_changes"))
            or result["secret_values_recorded"] is not False
            or not _keys_exact(closed, {*common, "state", "connection_count", "observed_at", "secret_values_recorded"})
            or closed["state"] != "CONNECTIONS_CLOSED" or not _exact_int(closed["connection_count"], 3)
            or closed["secret_values_recorded"] is not False):
            return False
        host_body = {key: value for key, value in host.items() if key != "canonical_sha256"}
        if (host.get("canonical_sha256") != hashlib.sha256(json.dumps(host_body,
                sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            or host.get("schema") != "noteai.item33.host_facts.v1" or host.get("phase") != "normal"
            or host.get("host") != "noteai-api-f"
            or host.get("activation_identity_sha256") != cycle["activation_identity_sha256"]
            or host.get("unit_sha256") != ITEM33_V5_NORMAL_UNIT_SHA256
            or host.get("unit_active") != "active" or host.get("unit_sub") != "running"
            or host.get("unit_enabled") != "enabled" or host.get("collection_suspended") is not False
            or host.get("startup_healthcheck_succeeded") is not True
            or host.get("capture_service_failure_present") is not False or host.get("secret_values_recorded") is not False
            or any(not _exact_int(host.get(key), 1) for key in ("formal_unit_count", "formal_container_count", "process_count"))
            or any(not _exact_int(host.get(key), 0) for key in (
                "capture_container_count", "task_container_count", "inspection_container_count",
                "runtime_directory_count", "stage_directory_count", "temporary_unit_count", "temporary_dropin_count",
                "observation_provider_calls", "observation_database_connections", "observation_mutations"))):
            return False
        sequence = [_evidence_clock(value) for value in (cycle["completed_at"], seal["catalog_proof"]["after"]["observed_at"], result["observed_at"],
            closed["observed_at"], teardown["execution"]["started_at"], teardown["after"]["observed_at"],
            item["started_at"], item["completed_at"], host["observed_at"])]
        return (None not in sequence and sequence == sorted(sequence) and sequence[-1] <= terminal_at
            and all(clock.date().isoformat() == cycle["bucket_key"] for clock in sequence))
    except (OSError, KeyError, TypeError, ValueError):
        return False


def _item33_v5_normal_handoff_valid(payload: dict, *, root: Path) -> bool:
    """Keep the instrumented recovery trace and verify its one normal-unit CAS."""
    item, cycle, recovery = (payload.get(key) for key in ("normal_handoff", "cycle", "recovery"))
    keys = {"status", "started_at", "completed_at", "observed_at", "activation_identity_sha256",
        "run_identity_sha256", "capture_receipt_sha256", "before_unit_sha256", "normal_unit_sha256",
        "image_config_sha256", "runtime_overlay_sha256", "mutation_count", "other_unit_actions",
        "restart_policy", "same_bucket", "preserved", "final", "action_ref", "action_sha256",
        "readback_ref", "readback_sha256", "teardown_ref", "teardown_sha256", "capture_close"}
    if (not _keys_exact(item, keys) or not isinstance(cycle, dict) or not isinstance(recovery, dict)
        or not isinstance(payload.get("release_binding"), dict)):
        return False
    capture = payload["release_binding"].get("capture_binding")
    if not isinstance(capture, dict):
        return False
    try:
        start, finish, observed = (_evidence_clock(item[key]) for key in ("started_at", "completed_at", "observed_at"))
        original_final = _evidence_clock(payload["readbacks"]["final"]["observed_at"])
        terminal_at = _evidence_clock(payload["observed_at"])
        seal, seal_sha = _read_json_artifact(
            ITEM33_V5_CAPTURE_EVIDENCE, "noteai.item33.runtime_capture_seal.v1", root=root,
        )
        catalog_after = _evidence_clock(seal["catalog_proof"]["after"]["observed_at"]) if seal else None
        if (None in (start, finish, observed, original_final, terminal_at)
            or catalog_after is None or seal_sha != capture.get("receipt_sha256") or catalog_after > start
            or not original_final <= start <= finish <= observed <= terminal_at
            or any(clock.date().isoformat() != cycle.get("bucket_key") for clock in (start, finish, observed))
            or item["status"] != "VERIFIED"
            or item["activation_identity_sha256"] != cycle.get("activation_identity_sha256")
            or item["run_identity_sha256"] != cycle.get("run_identity_sha256")
            or item["capture_receipt_sha256"] != capture.get("receipt_sha256")
            or item["before_unit_sha256"] != ITEM33_V5_PROMOTED_UNIT_SHA256
            or item["normal_unit_sha256"] != ITEM33_V5_NORMAL_UNIT_SHA256
            or item["image_config_sha256"] != ITEM32_V5_CONFIG_SHA256
            or item["runtime_overlay_sha256"] != ITEM33_V5_RUNTIME_OVERLAY_SHA256
            or not _exact_int(item["mutation_count"], 1) or not _exact_int(item["other_unit_actions"], 0)
            or item["restart_policy"] != "no"
            or item["action_ref"] != ITEM33_V5_NORMAL_ACTION
            or item["readback_ref"] != ITEM33_V5_NORMAL_READBACK
            or item["teardown_ref"] != ITEM33_V5_CAPTURE_TEARDOWN):
            return False
        teardown, teardown_sha = _read_json_artifact(
            ITEM33_V5_CAPTURE_TEARDOWN, "noteai.item33.capture_teardown.v1", root=root,
        )
        if (teardown is None or teardown_sha != item["teardown_sha256"]
            or _has_sensitive_evidence_key(teardown)):
            return False
        import item33_trends_capture_teardown as removal
        source_sha = _actual_file_sha256(removal.SOURCE_REF, root=root)
        if (not _sha256(source_sha) or teardown.get("source_sha256") != source_sha
            or source_sha != hashlib.sha256(Path(removal.__file__).read_bytes()).hexdigest()):
            return False
        removal.verify_teardown_proof(teardown,
            seal_raw=(root / ITEM33_V5_CAPTURE_EVIDENCE).read_bytes(),
            journal=(root / ITEM33_V5_CAPTURE_JOURNAL).read_bytes(), source_sha256=source_sha)
        teardown_at = _evidence_clock(teardown["after"]["observed_at"])
        if teardown_at is None or teardown_at > start:
            return False
        if not _item33_v5_capture_closed_valid(item, cycle, seal, teardown, root=root, terminal_at=terminal_at):
            return False
        # JSON comparison preserves bool-versus-integer distinctions in nested
        # factual readbacks; source and identity hashes above are exact strings.
        def same(left, right):
            return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)
        same_bucket = {"bucket_key": cycle["bucket_key"], "new_run_delta": 0, "provider_call_delta": 0}
        if (not same(item["same_bucket"], same_bucket)
            or not same(item["preserved"], recovery.get("preserved"))
            or not same(item["final"], recovery.get("final"))):
            return False
        if not _verify_path(ITEM33_V5_NORMAL_ACTION, root=root):
            return False
        raw = (root / ITEM33_V5_NORMAL_ACTION).read_bytes()
        if not 0 < len(raw) <= 65536 or hashlib.sha256(raw).hexdigest() != item["action_sha256"]:
            return False
        action = json.loads(raw, object_pairs_hook=_json_object_without_duplicate_keys)
        expected_action = {"phase": "normal_handoff", "status": "APPLIED_REQUIRES_STATE_READBACK",
            "activation_identity_sha256": cycle["activation_identity_sha256"],
            "run_identity_sha256": cycle["run_identity_sha256"], "bucket_key": cycle["bucket_key"],
            "before_unit_sha256": ITEM33_V5_PROMOTED_UNIT_SHA256,
            "after_unit_sha256": ITEM33_V5_NORMAL_UNIT_SHA256, "observed_at": item["started_at"],
            "completed_at": item["completed_at"], "capture_receipt_sha256": item["capture_receipt_sha256"],
            "teardown_sha256": item["teardown_sha256"]}
        if not same(action, expected_action):
            return False
        readback, readback_sha = _read_json_artifact(
            ITEM33_V5_NORMAL_READBACK, "noteai.item33.normal_readback.v1", root=root, max_bytes=65536,
        )
        expected_readback = {"schema": "noteai.item33.normal_readback.v1",
            "activation_identity_sha256": cycle["activation_identity_sha256"],
            "run_identity_sha256": cycle["run_identity_sha256"], "bucket_key": cycle["bucket_key"],
            "observed_at": item["observed_at"], "unit_sha256": ITEM33_V5_NORMAL_UNIT_SHA256,
            "preserved": item["preserved"], "final": item["final"], "same_bucket": same_bucket,
            "capture_receipt_sha256": item["capture_receipt_sha256"], "teardown_sha256": item["teardown_sha256"],
            "capture_close": item["capture_close"], "secret_values_recorded": False}
        return readback_sha == item["readback_sha256"] and same(readback, expected_readback)
    except (ImportError, OSError, AttributeError, KeyError, TypeError, ValueError):
        return False


def validate_item33_trends_promotion_evidence(
    control: dict[str, Any],
    *,
    root: Path = ROOT,
    now: datetime | None = None,
) -> list[str]:
    """Validate one real Trends cycle and the existing singleton promotion."""

    payload, errors = _schema_evidence(
        control,
        ITEM33_TRENDS_PROMOTION_EVIDENCE_SCHEMA,
        root=root,
        expected_ref=ITEM33_TRENDS_PROMOTION_EVIDENCE,
    )
    if payload is None:
        return errors
    # Only V5 terminal evidence adds the independently preserved normal handoff.
    preliminary_item32, _ = _read_json_artifact(ITEM32_TRENDS_EVIDENCE, ITEM32_V5_EVIDENCE_SCHEMA, root=root)
    if not _keys_exact(
        payload,
        {
            "schema",
            "item",
            "status",
            "readiness_credit",
            "observed_at",
            "release_binding",
            "cycle",
            "quality_snapshot",
            "promotion",
            "recovery",
            "production_write_set",
            "readbacks",
            "cleanup",
            "cost",
            "secret_values_recorded",
        } | ({"normal_handoff"} if preliminary_item32 is not None else set()),
    ):
        errors.append("Item33 terminal evidence schema mismatch")
    if _has_sensitive_evidence_key(payload):
        errors.append("Item33 sensitive field present")
    if (
        not _exact_int(payload.get("item"), 33)
        or payload.get("status") != "VERIFIED"
        or payload.get("readiness_credit") is not True
        or payload.get("secret_values_recorded") is not False
    ):
        errors.append("Item33 terminal status mismatch")
    observed_at = _evidence_clock(payload.get("observed_at"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if observed_at is None or observed_at > current:
        errors.append("Item33 observation clock invalid")

    item32_terminal, item32_sha256 = _read_json_artifact(
        ITEM32_TRENDS_EVIDENCE,
        ITEM32_TRENDS_EVIDENCE_SCHEMA,
        root=root,
    )
    if item32_terminal is None:
        item32_terminal, item32_sha256 = _read_json_artifact(
            ITEM32_TRENDS_EVIDENCE, ITEM32_V5_EVIDENCE_SCHEMA, root=root,
        )
    v5 = isinstance(item32_terminal, dict) and item32_terminal.get("schema") == ITEM32_V5_EVIDENCE_SCHEMA
    item32_bucket = None
    try:
        item32_bucket_text = item32_terminal["successor"]["budget"][
            "bucket_date"
        ]
        item32_bucket = datetime.fromisoformat(item32_bucket_text).date()
        if item32_bucket.isoformat() != item32_bucket_text:
            raise ValueError("non-canonical date")
    except (KeyError, TypeError, ValueError):
        errors.append("Item33 Item32 terminal bucket binding missing")

    release = payload.get("release_binding")
    release_keys = {
        "outer_executor_ref", "outer_executor_sha256", "source_sha256",
        "image_config_sha256", "registry_manifest_sha256",
        "suspended_unit_sha256", "promoted_unit_sha256",
    }
    effective_keys = {
        "image_source_sha256", "runtime_overlay_sha256", "item32_terminal_sha256",
    }
    effective_release = _keys_exact(
        release, release_keys | effective_keys | ({"capture_binding"} if v5 else set()),
    )
    item32_execution = (
        item32_terminal.get("execution") if isinstance(item32_terminal, dict) else None
    )
    item32_sources = (
        item32_execution.get("source_sha256") if isinstance(item32_execution, dict) else None
    )
    expected_sources = ITEM32_EXPECTED_SOURCE_SHA256
    expected_config = ITEM32_EXPECTED_CONFIG_SHA256
    expected_manifest = ITEM32_EXPECTED_MANIFEST_SHA256
    promoted_unit_sha = ITEM33_PROMOTED_UNIT_SHA256
    inherited_release_valid = item32_sources in (None, ITEM32_EXPECTED_SOURCE_SHA256)
    if v5:
        expected_sources = {**ITEM32_IMAGE_SOURCE_SHA256, **ITEM33_V5_RUNTIME_OVERLAY_SHA256}
        expected_config = ITEM32_V5_CONFIG_SHA256
        expected_manifest = ITEM32_V5_MANIFEST_SHA256
        promoted_unit_sha = ITEM33_V5_PROMOTED_UNIT_SHA256
        inherited_release_valid = bool(
            effective_release
            and _sha256(promoted_unit_sha)
            and release.get("item32_terminal_sha256") == item32_sha256
            and _sha256(item32_sha256)
            and item32_sources == expected_sources
            and item32_execution.get("image_config_sha256") == expected_config
            and item32_execution.get("registry_manifest_sha256") == expected_manifest
            and release.get("image_source_sha256") == ITEM32_IMAGE_SOURCE_SHA256
            and release.get("runtime_overlay_sha256") == ITEM33_V5_RUNTIME_OVERLAY_SHA256
            and not validate_item32_trends_evidence(
                {"evidence": [{"kind": "path", "ref": ITEM32_TRENDS_EVIDENCE}]},
                root=root, now=current,
            )
        )
    elif effective_release:
        expected_sources = ITEM32_EFFECTIVE_SOURCE_SHA256
        promoted_unit_sha = ITEM33_EFFECTIVE_PROMOTED_UNIT_SHA256
        inherited_release_valid = bool(
            release.get("item32_terminal_sha256") == item32_sha256
            and _sha256(item32_sha256)
            and item32_sources == ITEM32_EFFECTIVE_SOURCE_SHA256
            and release.get("image_source_sha256") == ITEM32_IMAGE_SOURCE_SHA256
            and release.get("runtime_overlay_sha256") == ITEM32_RUNTIME_OVERLAY_SHA256
            and not validate_item32_trends_evidence(
                {"evidence": [{"kind": "path", "ref": ITEM32_TRENDS_EVIDENCE}]},
                root=root, now=current,
            )
        )
    executor_sha = None
    executor_path = root / ITEM33_TRENDS_PROMOTION_EXECUTOR
    try:
        executor_sha = hashlib.sha256(executor_path.read_bytes()).hexdigest()
    except OSError:
        pass
    if (
        not (effective_release or _keys_exact(release, release_keys))
        or not inherited_release_valid
        or release.get("outer_executor_ref")
        != ITEM33_TRENDS_PROMOTION_EXECUTOR
        or not _sha256(executor_sha)
        or release.get("outer_executor_sha256") != executor_sha
        or release.get("source_sha256") != expected_sources
        or release.get("image_config_sha256") != expected_config
        or release.get("registry_manifest_sha256")
        != expected_manifest
        or release.get("suspended_unit_sha256")
        != ITEM33_SUSPENDED_UNIT_SHA256
        or release.get("promoted_unit_sha256")
        != promoted_unit_sha
    ):
        errors.append("Item33 release binding mismatch")

    cycle = payload.get("cycle")
    cycle_keys = {
        "run_identity_sha256",
        "bucket_key",
        "started_at",
        "completed_at",
        "lease_expires_at",
        "cycle_count",
        "same_bucket_completed_run_count",
        "source",
        "authenticated_session",
        "challenge_detected",
        "provider_request_limit",
        "provider_request_count",
        "provider_request_succeeded",
        "provider_request_failed",
        "active_admitted_count",
        "outcome_unknown_count",
        "automatic_retry_count",
        "endpoint_counts",
        "attempts",
    }
    if v5:
        cycle_keys.update({"physical_http", "activation_identity_sha256"})
    started_at = completed_at = lease_expires_at = None
    request_count = None
    attempts: Any = None
    if not _keys_exact(cycle, cycle_keys):
        errors.append("Item33 real cycle schema mismatch")
    else:
        started_at = _evidence_clock(cycle.get("started_at"))
        completed_at = _evidence_clock(cycle.get("completed_at"))
        lease_expires_at = _evidence_clock(cycle.get("lease_expires_at"))
        request_count = cycle.get("provider_request_count")
        attempts = cycle.get("attempts")
        endpoints = cycle.get("endpoint_counts")
        clocks_valid = (
            started_at is not None
            and completed_at is not None
            and lease_expires_at is not None
            and started_at <= completed_at
            and completed_at.date() == started_at.date()
            and lease_expires_at == started_at + timedelta(minutes=30)
            and completed_at <= lease_expires_at
            and observed_at is not None
            and completed_at <= observed_at
            and cycle.get("bucket_key") == started_at.date().isoformat()
        )
        counts_valid = (
            _exact_int(request_count)
            and 1 <= request_count <= 34
            and _exact_int(cycle.get("provider_request_limit"), 34)
            and _exact_int(cycle.get("provider_request_succeeded"), request_count)
            and _exact_int(cycle.get("provider_request_failed"), 0)
            and _exact_int(cycle.get("active_admitted_count"), 0)
            and _exact_int(cycle.get("outcome_unknown_count"), 0)
            and _exact_int(cycle.get("automatic_retry_count"), 0)
            and _exact_int(cycle.get("cycle_count"), 1)
            and _exact_int(cycle.get("same_bucket_completed_run_count"), 1)
        )
        endpoints_valid = (
            isinstance(endpoints, dict)
            and set(endpoints) == ITEM33_ENDPOINTS
            and all(_exact_int(value) and value >= 0 for value in endpoints.values())
            and sum(endpoints.values()) == request_count
            and endpoints.get("search_recommend", 0) > 0
            and endpoints.get("search_notes", 0) > 0
        )
        if v5:
            counts_valid = counts_valid and _exact_int(request_count, 34)
            endpoints_valid = endpoints_valid and endpoints == {
                "homefeed": 10, "search_recommend": 12, "search_notes": 12,
            }
        if (
            not _sha256(cycle.get("run_identity_sha256"))
            or cycle.get("source") != "real_xhs"
            or cycle.get("authenticated_session") is not True
            or cycle.get("challenge_detected") is not False
            or not clocks_valid
            or not counts_valid
            or not endpoints_valid
        ):
            errors.append("Item33 real single-cycle proof mismatch")
        if (
            item32_bucket is None
            or started_at is None
            or started_at.date() <= item32_bucket
        ):
            errors.append("Item33 UTC budget overlaps Item32 terminal cycle")
        attempt_ids: set[str] = set()
        expected_ordinals = list(range(1, request_count + 1)) if _exact_int(request_count) and request_count > 0 else []
        observed_ordinals: list[int] = []
        observed_endpoint_counts = {key: 0 for key in ITEM33_ENDPOINTS}
        if not isinstance(attempts, list) or len(attempts) != request_count:
            errors.append("Item33 provider-attempt ledger mismatch")
        else:
            for attempt in attempts:
                admitted_at = (
                    _evidence_clock(attempt.get("admitted_at"))
                    if isinstance(attempt, dict)
                    else None
                )
                attempt_completed_at = (
                    _evidence_clock(attempt.get("completed_at"))
                    if isinstance(attempt, dict)
                    else None
                )
                valid = (
                    _keys_exact(
                        attempt,
                        {
                            "attempt_identity_sha256",
                            "ordinal",
                            "endpoint",
                            "status",
                            "admitted_at",
                            "completed_at",
                        },
                    )
                    and _sha256(attempt.get("attempt_identity_sha256"))
                    and _exact_int(attempt.get("ordinal"))
                    and isinstance(attempt.get("endpoint"), str)
                    and attempt.get("endpoint") in ITEM33_ENDPOINTS
                    and attempt.get("status") == "succeeded"
                    and started_at is not None
                    and completed_at is not None
                    and admitted_at is not None
                    and attempt_completed_at is not None
                    and started_at <= admitted_at <= attempt_completed_at <= completed_at
                    and admitted_at.date() == started_at.date()
                    and attempt_completed_at.date() == started_at.date()
                )
                if not valid:
                    errors.append("Item33 provider-attempt ledger mismatch")
                    break
                identity = attempt["attempt_identity_sha256"]
                attempt_ids.add(identity)
                observed_ordinals.append(attempt["ordinal"])
                observed_endpoint_counts[attempt["endpoint"]] += 1
            if (
                len(attempt_ids) != len(attempts)
                or observed_ordinals != expected_ordinals
                or observed_endpoint_counts != endpoints
            ):
                errors.append("Item33 provider-attempt ledger mismatch")

    if v5:
        physical = cycle.get("physical_http") if isinstance(cycle, dict) else None
        summary = (
            {key: value for key, value in physical.items() if key != "observations"}
            if isinstance(physical, dict) else None
        )
        if not _item32_v5_physical_valid(physical, summary, attempts, started_at, completed_at):
            errors.append("Item33 V5 physical HTTP evidence mismatch")
        receipt, receipt_sha = _read_json_artifact(
            ITEM33_V5_HTTP_RECEIPT, "noteai.item33.worker_http_receipt.v1", root=root,
        )
        try:
            import item33_trends_http_readback as http_readback
            receipt_valid = (receipt is not None and isinstance(physical, dict)
                and receipt_sha == physical.get("worker_receipt_sha256")
                and not _has_sensitive_evidence_key(receipt)
                and http_readback.verify_worker_receipt(receipt, cycle))
        except (ImportError, OSError, TypeError, ValueError, RuntimeError):
            receipt_valid = False
        if not receipt_valid:
            errors.append("Item33 V5 worker HTTP receipt mismatch")

    quality = payload.get("quality_snapshot")
    published_counts = derived_real_counts = None
    derived_search_result_domains = derived_search_recommend_domains = None
    snapshot_sha = snapshot_size = snapshot_generated_at = None
    if isinstance(quality, dict):
        (
            published_counts,
            derived_real_counts,
            derived_search_result_domains,
            derived_search_recommend_domains,
            snapshot_sha,
            snapshot_size,
            snapshot_generated_at,
        ) = _validate_item33_snapshot(quality.get("snapshot_ref"), root=root)
    quality_keys = {
        "snapshot_ref",
        "snapshot_sha256",
        "snapshot_size_bytes",
        "snapshot_schema_version",
        "snapshot_row_count",
        "run_snapshot_sha256",
        "run_snapshot_size_bytes",
        "real_keyword_counts_by_domain",
        "search_result_domains",
        "search_recommend_domains",
        "published_keyword_counts_by_domain",
        "published_keyword_count",
    }
    real_counts = quality.get("real_keyword_counts_by_domain") if isinstance(quality, dict) else None
    search_result_domains = quality.get("search_result_domains") if isinstance(quality, dict) else None
    search_recommend_domains = quality.get("search_recommend_domains") if isinstance(quality, dict) else None
    published_total = sum(published_counts.values()) if isinstance(published_counts, dict) else None
    if (
        not _keys_exact(quality, quality_keys)
        or not isinstance(real_counts, dict)
        or set(real_counts) != ITEM32_TRENDS_DOMAINS
        or any(not _exact_int(value) or not 12 <= value <= 15 for value in real_counts.values())
        or real_counts != derived_real_counts
        or not isinstance(search_result_domains, list)
        or len(search_result_domains) != 6
        or any(not isinstance(value, str) for value in search_result_domains)
        or set(search_result_domains) != ITEM32_TRENDS_DOMAINS
        or set(search_result_domains) != derived_search_result_domains
        or not isinstance(search_recommend_domains, list)
        or len(search_recommend_domains) != 6
        or any(
            not isinstance(value, str) for value in search_recommend_domains
        )
        or set(search_recommend_domains) != ITEM32_TRENDS_DOMAINS
        or set(search_recommend_domains) != derived_search_recommend_domains
        or published_counts is None
        or quality.get("published_keyword_counts_by_domain") != published_counts
        or quality.get("published_keyword_count") != published_total
        or not isinstance(published_total, int)
        or not 72 <= published_total <= 90
        or quality.get("snapshot_sha256") != snapshot_sha
        or quality.get("run_snapshot_sha256") != snapshot_sha
        or not _exact_int(quality.get("snapshot_size_bytes"), snapshot_size)
        or not _exact_int(quality.get("run_snapshot_size_bytes"), snapshot_size)
        or not _exact_int(quality.get("snapshot_schema_version"), 1)
        or not _exact_int(quality.get("snapshot_row_count"), 1)
        or snapshot_generated_at is None
        or started_at is None
        or completed_at is None
        or not started_at <= snapshot_generated_at <= completed_at
    ):
        errors.append("Item33 six-domain quality snapshot mismatch")

    promotion = payload.get("promotion")
    before = promotion.get("before") if isinstance(promotion, dict) else None
    after = promotion.get("after") if isinstance(promotion, dict) else None
    runtime = promotion.get("runtime") if isinstance(promotion, dict) else None
    promotion_keys = {
        "unit_name",
        "container_name",
        "database_role",
        "argv",
        "before",
        "after",
        "runtime",
        "singleton_winner_count",
        "restart_policy",
        "automatic_restart_count",
    }
    if (
        not _keys_exact(promotion, promotion_keys)
        or promotion.get("unit_name") != "noteai-xhs-trends.service"
        or promotion.get("container_name") != "noteai-xhs-trends"
        or promotion.get("database_role") != "noteai_xhs_trends"
        or promotion.get("argv") != (
            ["/app/scripts/render_run_market_timing.sh"] if v5 else
            ["python", "market_timing_worker.py", "--daemon", "--interval", "360"]
        )
        or not _keys_exact(before, {"active", "sub", "enabled", "collection_suspended", "formal_container_count"})
        or before != {
            "active": "inactive",
            "sub": "dead",
            "enabled": "disabled",
            "collection_suspended": True,
            "formal_container_count": 0,
        }
        or not _keys_exact(
            after,
            {
                "active",
                "sub",
                "enabled",
                "collection_suspended",
                "formal_unit_count",
                "formal_container_count",
                "process_count",
                "service_state_row_count",
                "database_service_status",
                "active_run_count",
                "active_attempt_count",
                "outcome_unknown_count",
                "unlinked_attempt_count",
                "health",
            },
        )
        or after != {
            "active": "active",
            "sub": "running",
            "enabled": "enabled",
            "collection_suspended": False,
            "formal_unit_count": 1,
            "formal_container_count": 1,
            "process_count": 1,
            "service_state_row_count": 1,
            "database_service_status": "idle",
            "active_run_count": 0,
            "active_attempt_count": 0,
            "outcome_unknown_count": 0,
            "unlinked_attempt_count": 0,
            "health": "ready",
        }
        or not _keys_exact(
            runtime,
            {
                "memory_bytes",
                "cpus_millis",
                "pids_limit",
                "user",
                "read_only",
                "cap_drop",
                "no_new_privileges",
                "log_driver",
                "log_max_size",
                "log_max_file",
            },
        )
        or runtime != {
            "memory_bytes": 536870912,
            "cpus_millis": 500,
            "pids_limit": 64,
            "user": "999:999",
            "read_only": True,
            "cap_drop": ["ALL"],
            "no_new_privileges": True,
            "log_driver": "local",
            "log_max_size": "10m",
            "log_max_file": 2,
        }
        or not _exact_int(promotion.get("singleton_winner_count"), 1)
        or promotion.get("restart_policy") != "no"
        or not _exact_int(promotion.get("automatic_restart_count"), 0)
    ):
        errors.append("Item33 managed singleton promotion mismatch")

    recovery = payload.get("recovery")
    rollback_started = rollback_completed = reapplied_at = None
    if isinstance(recovery, dict):
        rollback_started = _evidence_clock(recovery.get("rollback_started_at"))
        rollback_completed = _evidence_clock(recovery.get("rollback_completed_at"))
        reapplied_at = _evidence_clock(recovery.get("reapplied_at"))
    rollback_final = recovery.get("rollback_final") if isinstance(recovery, dict) else None
    final = recovery.get("final") if isinstance(recovery, dict) else None
    preserved = recovery.get("preserved") if isinstance(recovery, dict) else None
    same_bucket = recovery.get("same_bucket") if isinstance(recovery, dict) else None
    recovery_keys = {
        "status",
        "scope",
        "rollback_count",
        "rollback_started_at",
        "rollback_completed_at",
        "rollback_final",
        "other_unit_actions",
        "provider_call_delta",
        "database_audit_deletes",
        "preserved",
        "reapplied_promoted_unit_sha256",
        "reapplied_at",
        "manual_start_count",
        "restart_policy",
        "same_bucket",
        "final",
    }
    if (
        not _keys_exact(recovery, recovery_keys)
        or recovery.get("status") != "VERIFIED"
        or recovery.get("scope") != "trends_only"
        or not _exact_int(recovery.get("rollback_count"), 1)
        or completed_at is None
        or rollback_started is None
        or rollback_completed is None
        or reapplied_at is None
        or observed_at is None
        or not completed_at <= rollback_started <= rollback_completed <= reapplied_at <= observed_at
        or (v5 and (started_at is None or reapplied_at.date() != started_at.date()))
        or rollback_final != {
            "active": "inactive",
            "sub": "dead",
            "enabled": "disabled",
            "collection_suspended": True,
            "formal_container_count": 0,
        }
        or not _exact_int(recovery.get("other_unit_actions"), 0)
        or not _exact_int(recovery.get("provider_call_delta"), 0)
        or not _exact_int(recovery.get("database_audit_deletes"), 0)
        or not _keys_exact(
            preserved,
            {
                "run_count",
                "attempt_count",
                "snapshot_count",
                "run_sha256",
                "attempt_ledger_sha256",
                "snapshot_sha256",
            },
        )
        or not _exact_int(preserved.get("run_count") if isinstance(preserved, dict) else None, 1)
        or not _exact_int(preserved.get("attempt_count") if isinstance(preserved, dict) else None, request_count)
        or not _exact_int(preserved.get("snapshot_count") if isinstance(preserved, dict) else None, 1)
        or any(
            not _sha256(preserved.get(field) if isinstance(preserved, dict) else None)
            for field in ("run_sha256", "attempt_ledger_sha256", "snapshot_sha256")
        )
        or (isinstance(preserved, dict) and preserved.get("snapshot_sha256") != snapshot_sha)
        or recovery.get("reapplied_promoted_unit_sha256")
        != promoted_unit_sha
        or not _exact_int(recovery.get("manual_start_count"), 1)
        or recovery.get("restart_policy") != "no"
        or same_bucket != {
            "bucket_key": cycle.get("bucket_key") if isinstance(cycle, dict) else None,
            "new_run_delta": 0,
            "provider_call_delta": 0,
        }
        or final != {
            "active": "active",
            "sub": "running",
            "enabled": "enabled",
            "collection_suspended": False,
            "formal_unit_count": 1,
            "formal_container_count": 1,
            "process_count": 1,
            "health": "ready",
        }
    ):
        errors.append("Item33 Trends-only rollback/no-replay mismatch")

    writes = payload.get("production_write_set")
    rows = (
        writes.get("distinct_rows_touched_by_table")
        if isinstance(writes, dict)
        else None
    )
    forbidden = writes.get("forbidden_table_mutations") if isinstance(writes, dict) else None
    atomic = writes.get("atomic_publish") if isinstance(writes, dict) else None
    keyword_count = quality.get("published_keyword_count") if isinstance(quality, dict) else None
    expected_rows = {
        "xhs_trends_runs": 1,
        "xhs_trends_service_state": 1,
        "xhs_trends_provider_attempts": request_count,
        "hot_keywords": keyword_count,
        "keyword_snapshots": keyword_count,
        "xhs_crawler_health": 6,
        "xhs_freshness_ledger": 6,
        "xhs_trends_snapshot_evidence": 1,
    }
    if (
        not _keys_exact(
            writes,
            {
                "tables",
                "distinct_rows_touched_by_table",
                "out_of_contract_row_mutations",
                "delete_rows",
                "truncate_count",
                "ddl_count",
                "forbidden_table_mutations",
                "atomic_publish",
            },
        )
        or not isinstance(writes.get("tables") if isinstance(writes, dict) else None, list)
        or any(
            not isinstance(value, str)
            for value in (writes.get("tables", []) if isinstance(writes, dict) else [])
        )
        or set(writes.get("tables", [])) != ITEM33_ALLOWED_WRITE_TABLES
        or len(writes.get("tables", [])) != len(ITEM33_ALLOWED_WRITE_TABLES)
        or rows != expected_rows
        or not _exact_int(writes.get("out_of_contract_row_mutations"), 0)
        or not _exact_int(writes.get("delete_rows"), 0)
        or not _exact_int(writes.get("truncate_count"), 0)
        or not _exact_int(writes.get("ddl_count"), 0)
        or not isinstance(forbidden, dict)
        or set(forbidden) != ITEM33_FORBIDDEN_WRITE_GROUPS
        or any(not _exact_int(value, 0) for value in forbidden.values())
        or atomic != {
            "business_pack_snapshot_run_success_one_transaction": True,
            "attempt_audit_outside_transaction": True,
        }
    ):
        errors.append("Item33 production write-set mismatch")

    if v5 and not _item33_v5_capture_valid(
        release.get("capture_binding") if isinstance(release, dict) else None,
        cycle, writes, root=root, observed_at=payload.get("observed_at"),
    ):
        errors.append("Item33 V5 independent capture binding mismatch")
    if v5 and not _item33_v5_normal_handoff_valid(payload, root=root):
        errors.append("Item33 V5 normal managed handoff mismatch")

    readbacks = payload.get("readbacks")
    preflight = readbacks.get("preflight") if isinstance(readbacks, dict) else None
    post_cycle = readbacks.get("post_cycle") if isinstance(readbacks, dict) else None
    rollback_readback = readbacks.get("rollback") if isinstance(readbacks, dict) else None
    final_readback = readbacks.get("final") if isinstance(readbacks, dict) else None
    preflight_at = _evidence_clock(preflight.get("observed_at")) if isinstance(preflight, dict) else None
    post_cycle_at = _evidence_clock(post_cycle.get("observed_at")) if isinstance(post_cycle, dict) else None
    rollback_at = _evidence_clock(rollback_readback.get("observed_at")) if isinstance(rollback_readback, dict) else None
    final_at = _evidence_clock(final_readback.get("observed_at")) if isinstance(final_readback, dict) else None
    budget_used = preflight.get("utc_provider_budget_used_before") if isinstance(preflight, dict) else None
    budget_remaining = preflight.get("utc_provider_budget_remaining_before") if isinstance(preflight, dict) else None
    if (
        not _keys_exact(readbacks, {"preflight", "post_cycle", "rollback", "final"})
        or not _keys_exact(
            preflight,
            {
                "observed_at",
                "canonical_sha256",
                "database_role",
                "role_exact",
                "acl_exact",
                "unit_active",
                "unit_sub",
                "unit_enabled",
                "formal_container_count",
                "active_run_count",
                "same_bucket_run_count",
                "outcome_unknown_count",
                "unlinked_attempt_count",
                "utc_provider_budget_used_before",
                "utc_provider_budget_remaining_before",
                "provider_calls",
                "production_database_writes",
            },
        )
        or not _sha256(preflight.get("canonical_sha256") if isinstance(preflight, dict) else None)
        or preflight.get("database_role") != "noteai_xhs_trends"
        or preflight.get("role_exact") is not True
        or preflight.get("acl_exact") is not True
        or preflight.get("unit_active") != "inactive"
        or preflight.get("unit_sub") != "dead"
        or preflight.get("unit_enabled") != "disabled"
        or any(
            not _exact_int(preflight.get(field), 0)
            for field in (
                "formal_container_count",
                "active_run_count",
                "same_bucket_run_count",
                "outcome_unknown_count",
                "unlinked_attempt_count",
                "provider_calls",
                "production_database_writes",
            )
        )
        or not _exact_int(budget_used, 0)
        or not _exact_int(budget_remaining, 34)
        or not _exact_int(request_count)
        or budget_used + request_count > 34
        or not _keys_exact(post_cycle, {"observed_at", "canonical_sha256", "health", "provider_calls", "production_database_writes"})
        or not _sha256(post_cycle.get("canonical_sha256") if isinstance(post_cycle, dict) else None)
        or post_cycle.get("health") != "ready"
        or not _exact_int(post_cycle.get("provider_calls"), 0)
        or not _exact_int(post_cycle.get("production_database_writes"), 0)
        or not _keys_exact(rollback_readback, {"observed_at", "canonical_sha256", "provider_calls", "database_audit_deletes"})
        or not _sha256(rollback_readback.get("canonical_sha256") if isinstance(rollback_readback, dict) else None)
        or not _exact_int(rollback_readback.get("provider_calls"), 0)
        or not _exact_int(rollback_readback.get("database_audit_deletes"), 0)
        or not _keys_exact(final_readback, {"observed_at", "canonical_sha256", "health", "provider_calls", "production_database_writes"})
        or not _sha256(final_readback.get("canonical_sha256") if isinstance(final_readback, dict) else None)
        or final_readback.get("health") != "ready"
        or not _exact_int(final_readback.get("provider_calls"), 0)
        or not _exact_int(final_readback.get("production_database_writes"), 0)
        or None in {
            preflight_at,
            post_cycle_at,
            rollback_at,
            final_at,
            started_at,
            completed_at,
            rollback_started,
            rollback_completed,
            reapplied_at,
            observed_at,
        }
        or preflight_at.date() != started_at.date()
        or not (
            preflight_at
            <= started_at
            <= completed_at
            <= post_cycle_at
            <= rollback_started
            <= rollback_completed
            <= rollback_at
            <= reapplied_at
            <= final_at
            <= observed_at
        )
    ):
        errors.append("Item33 provider-free readback/budget mismatch")

    cleanup = payload.get("cleanup")
    if (
        not _keys_exact(
            cleanup,
            {
                "task_container_count",
                "inspection_container_count",
                "stage_directory_count",
                "runtime_directory_count",
                "temporary_unit_count",
                "temporary_dropin_count",
                "local_snapshot_count",
                "local_export_count",
                "formal_managed_container_count",
                "rollback_artifact_retained",
                "rollback_artifact_sha256",
            },
        )
        or any(
            not _exact_int(cleanup.get(field), 0)
            for field in (
                "task_container_count",
                "inspection_container_count",
                "stage_directory_count",
                "runtime_directory_count",
                "temporary_unit_count",
                "temporary_dropin_count",
                "local_snapshot_count",
                "local_export_count",
            )
        )
        or not _exact_int(cleanup.get("formal_managed_container_count"), 1)
        or cleanup.get("rollback_artifact_retained") is not True
        or not _sha256(cleanup.get("rollback_artifact_sha256"))
    ):
        errors.append("Item33 task-exact cleanup mismatch")

    cost = payload.get("cost")
    if (
        not _keys_exact(
            cost,
            {
                "currency",
                "xhs_provider_requests",
                "provider_fee_fen",
                "incremental_cloud_cost_fen",
                "postpaid_resources_started",
                "postpaid_resources_running",
                "new_recurring_resource_count",
                "new_recurring_monthly_fen",
                "real_funds_fen",
                "payment_actions",
            },
        )
        or cost.get("currency") != "CNY"
        or not _exact_int(cost.get("xhs_provider_requests"), 36 if v5 else request_count)
        or any(
            cost.get(field) != "UNKNOWN"
            and not (_exact_int(cost.get(field)) and cost[field] >= 0)
            for field in ("provider_fee_fen", "incremental_cloud_cost_fen")
        )
        or any(
            not _exact_int(cost.get(field), 0)
            for field in (
                "postpaid_resources_started",
                "postpaid_resources_running",
                "new_recurring_resource_count",
                "new_recurring_monthly_fen",
                "real_funds_fen",
                "payment_actions",
            )
        )
    ):
        errors.append("Item33 cost/resource boundary mismatch")
    return errors


def _item31_live_capability_approval_valid(
    binding: dict[str, Any],
    approval: Any,
    actual_approval_sha: str | None,
    item: dict[str, Any],
    observed_at: datetime | None,
) -> bool:
    """Bind observed Live capabilities without inventing an approval date."""
    if not isinstance(approval, dict):
        return False
    verified_at = _evidence_clock(binding.get("verified_at"))
    finished_at = _evidence_clock(item.get("finished_at"))
    payment = item.get("payment")
    refund = item.get("refund")
    reconciliation = item.get("reconciliation")
    if not all(isinstance(value, dict) for value in (payment, refund, reconciliation)):
        return False
    expected_proofs = {
        "payment_create": payment.get("create_response_sha256"),
        "asynchronous_callback": payment.get("callback_payload_sha256"),
        "full_refund": refund.get("response_sha256"),
        "bill_reconciliation": reconciliation.get("readback_sha256"),
    }
    capabilities = approval.get("product_capabilities")
    return (
        _keys_exact(binding, {
            "status", "approved_at", "verification_basis", "verified_at",
            "artifact_path", "artifact_sha256",
        })
        and binding.get("status") == "VERIFIED"
        and binding.get("approved_at") is None
        and binding.get("verification_basis") == "AUTHENTICATED_LIVE_CAPABILITIES"
        and isinstance(binding.get("artifact_path"), str)
        and binding["artifact_path"].startswith("deploy/production/evidence/")
        and _sha256(binding.get("artifact_sha256"))
        and actual_approval_sha == binding["artifact_sha256"]
        and verified_at is not None
        and finished_at is not None
        and observed_at is not None
        and finished_at <= verified_at <= observed_at
        and _keys_exact(approval, {
            "schema", "provider", "status", "approved_at", "verification_basis",
            "verified_at", "merchant_identity_sha256", "application_identity_sha256",
            "configuration_readback_sha256", "product_capabilities",
            "capability_proofs", "secret_values_recorded",
        })
        and approval.get("schema") == ITEM31_MERCHANT_APPROVAL_SCHEMA
        and approval.get("provider") == item.get("name") == "wechatpay_direct"
        and approval.get("status") == "VERIFIED"
        and approval.get("approved_at") is None
        and approval.get("verification_basis") == binding["verification_basis"]
        and _evidence_clock(approval.get("verified_at")) == verified_at
        and all(_sha256(approval.get(field)) for field in (
            "merchant_identity_sha256", "application_identity_sha256",
            "configuration_readback_sha256",
        ))
        and isinstance(capabilities, list)
        and len(capabilities) == 4
        and all(isinstance(value, str) for value in capabilities)
        and set(capabilities) == set(expected_proofs)
        and all(_sha256(value) for value in expected_proofs.values())
        and approval.get("capability_proofs") == expected_proofs
        and payment.get("create_result") == "SUCCEEDED"
        and payment.get("callback_result") == "SUCCEEDED"
        and payment.get("signature_verification") == "VERIFIED"
        and payment.get("signature_scheme") == "WECHATPAY2-SHA256-RSA2048"
        and refund.get("create_result") == "SUCCEEDED"
        and refund.get("provider_status") == "refunded"
        and refund.get("full_refund") is True
        and reconciliation.get("status") == "MATCHED"
        and _exact_int(reconciliation.get("discrepancy_count"), 0)
        and approval.get("secret_values_recorded") is False
        and not _has_sensitive_evidence_key(approval)
    )


def _item31_multi_capture_manifest_valid(canary: dict[str, Any], *, root: Path) -> bool:
    """Verify a source manifest; its digest is not an original capture digest."""
    if not _keys_exact(canary, {
        "schema", "provider", "environment", "canary_identity_sha256",
        "started_at", "finished_at", "payment_amount_fen", "payment", "refund",
        "reconciliation", "write_mutations_by_table", "write_ledger_readback_sha256",
        "secret_values_recorded", "raw_provider_identifiers_recorded",
        "write_ledger_readback_kind", "write_ledger_manifest_ref",
    }) or canary.get("write_ledger_readback_kind") != "MULTI_CAPTURE_MANIFEST":
        return False
    manifest, actual_sha = _read_json_artifact(
        canary.get("write_ledger_manifest_ref"),
        "noteai.item31.write_capture_manifest.v1",
        root=root,
    )
    if not _keys_exact(manifest, {
        "schema", "provider", "canary_identity_sha256", "captures",
        "secret_values_recorded",
    }):
        return False
    canonical_sha = hashlib.sha256(json.dumps(
        manifest, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    if (
        actual_sha != canonical_sha
        or actual_sha != canary.get("write_ledger_readback_sha256")
        or manifest.get("provider") != canary.get("provider")
        or manifest.get("canary_identity_sha256") != canary.get("canary_identity_sha256")
        or manifest.get("secret_values_recorded") is not False
        or _has_sensitive_evidence_key(manifest)
    ):
        return False
    captures = manifest.get("captures")
    if not isinstance(captures, list) or len(captures) != 2:
        return False
    original_hashes: set[str] = set()
    totals: dict[str, int] = {}
    for phase, capture in zip(("trade", "bill"), captures):
        if not _keys_exact(capture, {
            "phase", "original_capture_sha256", "row_mutations_by_table",
        }):
            return False
        original_sha = capture.get("original_capture_sha256")
        counts = capture.get("row_mutations_by_table")
        if (
            capture.get("phase") != phase
            or not _sha256(original_sha)
            or original_sha in original_hashes
            or not isinstance(counts, dict)
            or not counts
            or not set(counts).issubset(ITEM31_ALLOWED_WRITE_TABLES)
            or not all(_exact_int(count) and count > 0 for count in counts.values())
            or (phase == "bill" and counts != {"payment_reconciliation_runs": 1})
            or (phase == "trade" and "payment_reconciliation_runs" in counts)
        ):
            return False
        original_hashes.add(original_sha)
        for table, count in counts.items():
            totals[table] = totals.get(table, 0) + count
    return totals == canary.get("write_mutations_by_table")


def validate_item31_payment_evidence(
    control: dict[str, Any],
    *,
    root: Path = ROOT,
    now: datetime | None = None,
) -> list[str]:
    """Validate both bounded direct-provider Live payment/refund chains."""

    payload, errors = _schema_evidence(
        control,
        ITEM31_PAYMENT_EVIDENCE_SCHEMA,
        root=root,
        expected_ref=ITEM31_PAYMENT_EVIDENCE,
    )
    if payload is None:
        return errors
    if not _keys_exact(
        payload,
        {
            "schema",
            "item",
            "status",
            "readiness_credit",
            "environment",
            "observed_at",
            "pingxx_readiness_credit",
            "providers",
            "cumulative_payment_fen",
            "cumulative_refund_fen",
            "net_real_funds_fen",
            "owner_over_20_cny_approval",
            "actual_production_write_set",
            "secret_values_recorded",
            "raw_provider_identifiers_recorded",
        },
    ):
        errors.append("Item31 terminal evidence schema mismatch")
    if _has_sensitive_evidence_key(payload):
        errors.append("Item31 sensitive field present")
    if (
        not _exact_int(payload.get("item"), 31)
        or payload.get("status") != "VERIFIED"
        or payload.get("readiness_credit") is not True
        or payload.get("environment") != "LIVE"
        or not _exact_int(payload.get("pingxx_readiness_credit"), 0)
    ):
        errors.append("Item31 direct Live terminal status mismatch")
    observed_at = _evidence_clock(payload.get("observed_at"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if observed_at is None or observed_at > current:
        errors.append("Item31 terminal observation clock invalid")

    providers = payload.get("providers")
    if not isinstance(providers, list):
        return [*errors, "Item31 direct-provider evidence missing"]
    names = [item.get("name") for item in providers if isinstance(item, dict)]
    if (
        len(names) != len(providers)
        or any(not isinstance(name, str) for name in names)
        or len(names) != len(set(names))
        or set(names) != ITEM31_DIRECT_PROVIDERS
    ):
        errors.append("Item31 requires the approved WeChat Native provider exactly once")
    total_payment_fen = 0
    total_refund_fen = 0
    payment_identities: set[str] = set()
    callback_identities: set[str] = set()
    refund_identities: set[str] = set()
    approval_artifacts: set[str] = set()
    canary_artifacts: set[str] = set()
    canary_identities: set[str] = set()
    provider_write_totals: dict[str, int] = {}
    provider_write_readbacks: list[str] = []
    signature_schemes = {
        "wechatpay_direct": "WECHATPAY2-SHA256-RSA2048",
        "alipay_direct": "RSA2",
    }
    for item in providers:
        if not isinstance(item, dict):
            errors.append("Item31 provider evidence invalid")
            continue
        provider_name = item.get("name")
        amount_fen = item.get("payment_amount_fen")
        started_at = _evidence_clock(item.get("started_at"))
        finished_at = _evidence_clock(item.get("finished_at"))
        if (
            not _keys_exact(
                item,
                {
                    "name",
                    "environment",
                    "synthetic_user",
                    "synthetic_order",
                    "real_user_order",
                    "payment_amount_fen",
                    "started_at",
                    "finished_at",
                    "provider_operation_count",
                    "automatic_retry_count",
                    "outcome_unknown_count",
                    "canary_identity_sha256",
                    "merchant_approval",
                    "payment",
                    "refund",
                    "reconciliation",
                    "canary_audit_ref",
                    "canary_audit_sha256",
                },
            )
            or not isinstance(provider_name, str)
            or provider_name not in ITEM31_DIRECT_PROVIDERS
            or item.get("environment") != "LIVE"
            or item.get("synthetic_user") is not False
            or item.get("synthetic_order") is not False
            or item.get("real_user_order") is not True
            or not _exact_int(amount_fen, ITEM31_CANARY_AMOUNT_FEN)
            or not _exact_int(
                item.get("provider_operation_count"),
                ITEM31_PROVIDER_OPERATION_COUNT,
            )
            or not _exact_int(item.get("automatic_retry_count"), 0)
            or not _exact_int(item.get("outcome_unknown_count"), 0)
            or not _sha256(item.get("canary_identity_sha256"))
            or started_at is None
            or finished_at is None
            or observed_at is None
            or not started_at <= finished_at <= observed_at
        ):
            errors.append("Item31 bounded provider canary mismatch")
            continue
        total_payment_fen += amount_fen
        if item["canary_identity_sha256"] in canary_identities:
            errors.append("Item31 provider canary identities must be distinct")
        canary_identities.add(item["canary_identity_sha256"])
        merchant_approval = item.get("merchant_approval")
        if isinstance(merchant_approval, dict):
            approval_path = merchant_approval.get("artifact_path")
            approval_sha = merchant_approval.get("artifact_sha256")
            approved_at = _evidence_clock(merchant_approval.get("approved_at"))
            approval, actual_approval_sha = _read_json_artifact(
                approval_path,
                ITEM31_MERCHANT_APPROVAL_SCHEMA,
                root=root,
            )
            capabilities = (
                approval.get("product_capabilities")
                if isinstance(approval, dict)
                else None
            )
            approval_valid = (
                _keys_exact(
                    merchant_approval,
                    {"status", "approved_at", "artifact_path", "artifact_sha256"},
                )
                and merchant_approval.get("status") == "VERIFIED"
                and isinstance(approval_path, str)
                and approval_path.startswith("deploy/production/evidence/")
                and _sha256(approval_sha)
                and actual_approval_sha == approval_sha
                and approved_at is not None
                and approved_at <= started_at
                and isinstance(approval, dict)
                and _keys_exact(
                    approval,
                    {
                        "schema",
                        "provider",
                        "status",
                        "approved_at",
                        "merchant_identity_sha256",
                        "application_identity_sha256",
                        "product_capabilities",
                        "official_readback_sha256",
                        "secret_values_recorded",
                    },
                )
                and approval.get("provider") == provider_name
                and approval.get("status") == "APPROVED"
                and _evidence_clock(approval.get("approved_at")) == approved_at
                and _sha256(approval.get("merchant_identity_sha256"))
                and _sha256(approval.get("application_identity_sha256"))
                and _sha256(approval.get("official_readback_sha256"))
                and isinstance(capabilities, list)
                and len(capabilities) == 4
                and all(isinstance(value, str) for value in capabilities)
                and set(capabilities)
                == {
                    "payment_create",
                    "asynchronous_callback",
                    "full_refund",
                    "bill_reconciliation",
                }
                and approval.get("secret_values_recorded") is False
                and not _has_sensitive_evidence_key(approval)
            )
            if not approval_valid:
                approval_valid = _item31_live_capability_approval_valid(
                    merchant_approval, approval, actual_approval_sha, item, observed_at
                )
        else:
            approval_path = None
            approval_sha = None
            approval_valid = False
        if not approval_valid:
            errors.append("Item31 merchant/product approval binding missing")
        elif approval_sha in approval_artifacts:
            errors.append("Item31 provider approval artifacts must be distinct")
        else:
            approval_artifacts.add(approval_sha)

        payment = item.get("payment")
        payment_hash_fields = (
            "provider_payment_identity_sha256",
            "callback_identity_sha256",
            "create_request_sha256",
            "create_response_sha256",
            "signature_input_sha256",
            "callback_payload_sha256",
            "ledger_readback_sha256",
        )
        if (
            not isinstance(payment, dict)
            or not _keys_exact(
                payment,
                {
                    "create_result",
                    "callback_result",
                    "signature_verification",
                    "signature_scheme",
                    "internal_status",
                    "entitlement_mutation_count",
                    "duplicate_callback_count",
                    "duplicate_entitlement_mutation_count",
                    *payment_hash_fields,
                },
            )
            or payment.get("create_result") != "SUCCEEDED"
            or payment.get("callback_result") != "SUCCEEDED"
            or payment.get("signature_verification") != "VERIFIED"
            or payment.get("signature_scheme")
            != signature_schemes.get(provider_name)
            or payment.get("internal_status") not in ("paid", "succeeded")
            or not _exact_int(payment.get("entitlement_mutation_count"), 1)
            or not _exact_int(payment.get("duplicate_callback_count"))
            or payment["duplicate_callback_count"] < 1
            or not _exact_int(
                payment.get("duplicate_entitlement_mutation_count"), 0
            )
            or any(not _sha256(payment.get(field)) for field in payment_hash_fields)
            or len({payment.get(field) for field in payment_hash_fields})
            != len(payment_hash_fields)
        ):
            errors.append("Item31 payment/callback exactly-once proof mismatch")
        elif (
            payment["provider_payment_identity_sha256"] in payment_identities
            or payment["callback_identity_sha256"] in callback_identities
        ):
            errors.append("Item31 provider payment/callback identities must be distinct")
        else:
            payment_identities.add(payment["provider_payment_identity_sha256"])
            callback_identities.add(payment["callback_identity_sha256"])

        refund = item.get("refund")
        if (
            not isinstance(refund, dict)
            or not _keys_exact(
                refund,
                {
                    "create_result",
                    "provider_status",
                    "internal_status",
                    "amount_fen",
                    "full_refund",
                    "provider_refund_identity_sha256",
                    "request_sha256",
                    "response_sha256",
                },
            )
            or refund.get("create_result") != "SUCCEEDED"
            or refund.get("provider_status") != "refunded"
            or refund.get("internal_status") != "refunded"
            or not _exact_int(refund.get("amount_fen"), amount_fen)
            or refund.get("full_refund") is not True
            or not _sha256(refund.get("provider_refund_identity_sha256"))
            or not _sha256(refund.get("request_sha256"))
            or not _sha256(refund.get("response_sha256"))
            or len(
                {
                    refund.get("provider_refund_identity_sha256"),
                    refund.get("request_sha256"),
                    refund.get("response_sha256"),
                }
            )
            != 3
        ):
            errors.append("Item31 full Live refund proof mismatch")
        elif refund["provider_refund_identity_sha256"] in refund_identities:
            errors.append("Item31 provider refund identities must be distinct")
        else:
            refund_identities.add(refund["provider_refund_identity_sha256"])
            total_refund_fen += refund["amount_fen"]

        reconciliation = item.get("reconciliation")
        required_sides = {
            "internal_order",
            "provider_payment",
            "callback",
            "payment_ledger",
            "entitlement",
            "provider_refund",
            "refunded_state",
            "duplicate_no_replay",
        }
        matched_sides = (
            reconciliation.get("matched_sides")
            if isinstance(reconciliation, dict)
            else None
        )
        if (
            not isinstance(reconciliation, dict)
            or not _keys_exact(
                reconciliation,
                {"status", "matched_sides", "discrepancy_count", "readback_sha256"},
            )
            or reconciliation.get("status") != "MATCHED"
            or not isinstance(matched_sides, list)
            or len(matched_sides) != len(required_sides)
            or any(not isinstance(value, str) for value in matched_sides)
            or set(matched_sides) != required_sides
            or not _exact_int(reconciliation.get("discrepancy_count"), 0)
            or not _sha256(reconciliation.get("readback_sha256"))
        ):
            errors.append("Item31 direct-provider reconciliation mismatch")
        if (
            isinstance(payment, dict)
            and isinstance(refund, dict)
            and isinstance(reconciliation, dict)
        ):
            semantic_hashes = {
                *(payment.get(field) for field in payment_hash_fields),
                refund.get("provider_refund_identity_sha256"),
                refund.get("request_sha256"),
                refund.get("response_sha256"),
                reconciliation.get("readback_sha256"),
            }
            if len(semantic_hashes) != len(payment_hash_fields) + 4:
                errors.append("Item31 semantic proof identities must be distinct")

        canary_ref = item.get("canary_audit_ref")
        canary, actual_canary_sha = _read_json_artifact(
            canary_ref,
            ITEM31_CANARY_AUDIT_SCHEMA,
            root=root,
        )
        write_mutations = (
            canary.get("write_mutations_by_table")
            if isinstance(canary, dict)
            else None
        )
        write_readback = (
            canary.get("write_ledger_readback_sha256")
            if isinstance(canary, dict)
            else None
        )
        canary_valid = (
            isinstance(canary, dict)
            and (
                _keys_exact(
                    canary,
                    {
                        "schema",
                        "provider",
                        "environment",
                        "canary_identity_sha256",
                        "started_at",
                        "finished_at",
                        "payment_amount_fen",
                        "payment",
                        "refund",
                        "reconciliation",
                        "write_mutations_by_table",
                        "write_ledger_readback_sha256",
                        "secret_values_recorded",
                        "raw_provider_identifiers_recorded",
                    },
                )
                or _item31_multi_capture_manifest_valid(canary, root=root)
            )
            and actual_canary_sha == item.get("canary_audit_sha256")
            and canary.get("provider") == provider_name
            and canary.get("environment") == "LIVE"
            and canary.get("canary_identity_sha256")
            == item.get("canary_identity_sha256")
            and _evidence_clock(canary.get("started_at")) == started_at
            and _evidence_clock(canary.get("finished_at")) == finished_at
            and _exact_int(canary.get("payment_amount_fen"), amount_fen)
            and canary.get("payment") == payment
            and canary.get("refund") == refund
            and canary.get("reconciliation") == reconciliation
            and isinstance(write_mutations, dict)
            and ITEM31_REQUIRED_WRITE_TABLES.issubset(set(write_mutations))
            and set(write_mutations).issubset(ITEM31_ALLOWED_WRITE_TABLES)
            and all(isinstance(table, str) for table in write_mutations)
            and all(
                _exact_int(count) and count > 0
                for count in write_mutations.values()
            )
            and _sha256(write_readback)
            and canary.get("secret_values_recorded") is False
            and canary.get("raw_provider_identifiers_recorded") is False
            and not _has_sensitive_evidence_key(canary)
        )
        if not canary_valid:
            errors.append("Item31 provider canary audit binding mismatch")
        else:
            if actual_canary_sha in canary_artifacts:
                errors.append("Item31 provider canary artifacts must be distinct")
            canary_artifacts.add(actual_canary_sha)
            provider_write_readbacks.append(write_readback)
            for table, count in write_mutations.items():
                provider_write_totals[table] = (
                    provider_write_totals.get(table, 0) + count
                )

    if not _exact_int(payload.get("cumulative_payment_fen"), total_payment_fen):
        errors.append("Item31 cumulative real-payment amount mismatch")
    if (
        not _exact_int(payload.get("cumulative_refund_fen"), total_refund_fen)
        or total_refund_fen != total_payment_fen
        or not _exact_int(payload.get("net_real_funds_fen"), 0)
    ):
        errors.append("Item31 cumulative full-refund amount mismatch")
    if total_payment_fen > 2000 and payload.get("owner_over_20_cny_approval") is not True:
        errors.append("Item31 over-CNY20 authorization missing")
    writes = payload.get("actual_production_write_set")
    expected_write_readback = hashlib.sha256(
        json.dumps(
            sorted(provider_write_readbacks),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if (
        not isinstance(writes, dict)
        or not _keys_exact(
            writes,
            {
                "tables",
                "row_mutations_by_table",
                "ledger_readback_sha256",
                "out_of_contract_row_mutations",
            },
        )
        or not isinstance(writes.get("tables"), list)
        or any(not isinstance(value, str) for value in writes.get("tables", []))
        or len(writes.get("tables", [])) != len(set(writes.get("tables", [])))
        or not ITEM31_REQUIRED_WRITE_TABLES.issubset(set(writes.get("tables", [])))
        or not set(writes.get("tables", [])).issubset(ITEM31_ALLOWED_WRITE_TABLES)
        or not isinstance(writes.get("row_mutations_by_table"), dict)
        or writes.get("row_mutations_by_table") != provider_write_totals
        or set(writes.get("row_mutations_by_table", {}))
        != set(writes.get("tables", []))
        or writes.get("ledger_readback_sha256") != expected_write_readback
        or not _exact_int(writes.get("out_of_contract_row_mutations"), 0)
    ):
        errors.append("Item31 production write-set evidence invalid")
    if (
        payload.get("secret_values_recorded") is not False
        or payload.get("raw_provider_identifiers_recorded") is not False
    ):
        errors.append("Item31 secret/raw-identity exclusion missing")
    return errors


def _evidence_clock(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def validate_item35_approval_evidence(
    control: dict[str, Any],
    *,
    root: Path = ROOT,
    now: datetime | None = None,
) -> list[str]:
    """Validate real professional/provider approvals without inferring them."""

    payload, errors = _schema_evidence(
        control,
        ITEM35_APPROVAL_EVIDENCE_SCHEMA,
        root=root,
        expected_ref=ITEM35_APPROVAL_EVIDENCE,
    )
    if payload is None:
        return errors
    if not _keys_exact(
        payload,
        {
            "schema",
            "item",
            "status",
            "readiness_credit",
            "environment",
            "public_launch_scope",
            "review_package_sha256",
            "review_package_frozen_at",
            "approved_documents",
            "approvals",
            "secret_values_recorded",
        },
    ):
        errors.append("Item35 terminal evidence schema mismatch")
    if _has_sensitive_evidence_key(payload):
        errors.append("Item35 sensitive field present")
    if (
        not _exact_int(payload.get("item"), 35)
        or payload.get("status") != "VERIFIED"
        or payload.get("readiness_credit") is not True
        or payload.get("environment") != "production"
        or payload.get("public_launch_scope") is not True
    ):
        errors.append("Item35 terminal status mismatch")
    package = root / ITEM35_REVIEW_PACKAGE
    try:
        package_bytes = package.read_bytes()
        package_text = package_bytes.decode("utf-8")
        expected_package_sha = hashlib.sha256(package_bytes).hexdigest()
    except OSError:
        package_text = ""
        expected_package_sha = None
        errors.append("Item35 review package missing")
    freeze_match = re.search(
        r"审核包冻结时间：([^\s]+)",
        package_text,
    )
    package_frozen_at = (
        _evidence_clock(freeze_match.group(1)) if freeze_match else None
    )
    if (
        expected_package_sha is None
        or payload.get("review_package_sha256") != expected_package_sha
        or package_frozen_at is None
        or _evidence_clock(payload.get("review_package_frozen_at"))
        != package_frozen_at
    ):
        errors.append("Item35 review package binding mismatch")

    documents = payload.get("approved_documents")
    if not isinstance(documents, list):
        errors.append("Item35 approved document ledger missing")
    else:
        categories = [
            item.get("category")
            for item in documents
            if isinstance(item, dict)
        ]
        if (
            len(categories) != len(documents)
            or any(not isinstance(category, str) for category in categories)
            or len(categories) != len(set(categories))
            or set(categories) != ITEM35_REQUIRED_DOCUMENTS
            or len(documents) != len(ITEM35_REQUIRED_DOCUMENTS)
        ):
            errors.append("Item35 approved document coverage mismatch")
        else:
            for item in documents:
                if (
                    not _keys_exact(item, {"category", "status", "artifacts"})
                    or
                    item.get("status") != "APPROVED"
                    or not _file_ledger_valid(
                        item.get("artifacts"),
                        ITEM35_DOCUMENT_SCOPE_PATHS[item["category"]],
                        root=root,
                    )
                ):
                    errors.append("Item35 approved document binding mismatch")
                    break

    approvals = payload.get("approvals")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not isinstance(approvals, list):
        errors.append("Item35 professional approval ledger missing")
    else:
        categories = [
            item.get("category")
            for item in approvals
            if isinstance(item, dict)
        ]
        if (
            len(categories) != len(approvals)
            or any(not isinstance(category, str) for category in categories)
            or len(categories) != len(set(categories))
            or set(categories) != ITEM35_REQUIRED_APPROVALS
            or len(approvals) != len(ITEM35_REQUIRED_APPROVALS)
        ):
            errors.append("Item35 required approval coverage mismatch")
        signed_artifact_paths: set[str] = set()
        signed_artifact_hashes: set[str] = set()
        binding_artifact_paths: set[str] = set()
        binding_artifact_hashes: set[str] = set()
        for item in approvals:
            signed_at = _evidence_clock(
                item.get("signed_at") if isinstance(item, dict) else None
            )
            category = item.get("category") if isinstance(item, dict) else None
            scope_artifacts = (
                item.get("scope_artifacts") if isinstance(item, dict) else None
            )
            scope_valid = (
                isinstance(category, str)
                and category in ITEM35_APPROVAL_SCOPE_PATHS
                and _file_ledger_valid(
                    scope_artifacts,
                    ITEM35_APPROVAL_SCOPE_PATHS[category],
                    root=root,
                )
            )
            signed_path = (
                item.get("signed_artifact_path")
                if isinstance(item, dict)
                else None
            )
            signed_sha = (
                item.get("signed_artifact_sha256")
                if isinstance(item, dict)
                else None
            )
            binding_path = (
                item.get("binding_artifact_path")
                if isinstance(item, dict)
                else None
            )
            binding_sha = (
                item.get("binding_artifact_sha256")
                if isinstance(item, dict)
                else None
            )
            binding, actual_binding_sha = _read_json_artifact(
                binding_path,
                ITEM35_APPROVAL_BINDING_SCHEMA,
                root=root,
            )
            if (
                not isinstance(item, dict)
                or not _keys_exact(
                    item,
                    {
                        "category",
                        "status",
                        "signer_name",
                        "organization",
                        "professional_role",
                        "signed_at",
                        "signed_artifact_path",
                        "signed_artifact_sha256",
                        "binding_artifact_path",
                        "binding_artifact_sha256",
                        "scope_artifacts",
                        "scope_sha256",
                        "open_condition_count",
                    },
                )
                or item.get("status") != "APPROVED"
                or not isinstance(item.get("signer_name"), str)
                or not item["signer_name"].strip()
                or not isinstance(item.get("organization"), str)
                or not item["organization"].strip()
                or not isinstance(item.get("professional_role"), str)
                or not item["professional_role"].strip()
                or signed_at is None
                or package_frozen_at is None
                or signed_at < package_frozen_at
                or signed_at > current
                or not isinstance(signed_path, str)
                or not signed_path.startswith("deploy/production/evidence/")
                or not _sha256(signed_sha)
                or _actual_file_sha256(signed_path, root=root) != signed_sha
                or not scope_valid
                or item.get("scope_sha256")
                != (
                    _file_ledger_sha256(scope_artifacts)
                    if scope_valid
                    else None
                )
                or not _exact_int(item.get("open_condition_count"), 0)
                or not isinstance(binding, dict)
                or not _keys_exact(
                    binding,
                    {
                        "schema",
                        "category",
                        "status",
                        "signer_name",
                        "organization",
                        "professional_role",
                        "signed_at",
                        "signed_artifact_sha256",
                        "scope_sha256",
                        "open_condition_count",
                        "secret_values_recorded",
                    },
                )
                or actual_binding_sha != binding_sha
                or binding.get("category") != category
                or binding.get("status") != item.get("status")
                or binding.get("signer_name") != item.get("signer_name")
                or binding.get("organization") != item.get("organization")
                or binding.get("professional_role") != item.get("professional_role")
                or _evidence_clock(binding.get("signed_at")) != signed_at
                or binding.get("signed_artifact_sha256") != signed_sha
                or binding.get("scope_sha256") != item.get("scope_sha256")
                or not _exact_int(binding.get("open_condition_count"), 0)
                or binding.get("secret_values_recorded") is not False
                or _has_sensitive_evidence_key(binding)
            ):
                errors.append("Item35 professional approval invalid")
                break
            if (
                signed_path in signed_artifact_paths
                or signed_sha in signed_artifact_hashes
                or binding_path in binding_artifact_paths
                or binding_sha in binding_artifact_hashes
            ):
                errors.append("Item35 separately signed approval artifacts required")
                break
            signed_artifact_paths.add(signed_path)
            signed_artifact_hashes.add(signed_sha)
            binding_artifact_paths.add(binding_path)
            binding_artifact_hashes.add(binding_sha)
        if (
            not signed_artifact_paths.isdisjoint(binding_artifact_paths)
            or not signed_artifact_hashes.isdisjoint(binding_artifact_hashes)
        ):
            errors.append("Item35 signed and binding artifacts must be distinct")
    if payload.get("secret_values_recorded") is not False:
        errors.append("Item35 secret-value exclusion missing")
    return errors


def _item36_current_cost_terms_valid(
    costs: dict[str, Any],
    approval: Any,
    quote: Any,
    alb: Any,
    *,
    approved_at: datetime | None,
    resource_created_at: datetime | None,
    root: Path,
) -> bool:
    """Bind the current actual-use approval without inventing a spend cap."""

    if not all(isinstance(value, dict) for value in (approval, quote, alb)):
        return False
    configuration = {
        "vpc_identity_sha256": alb.get("vpc_identity_sha256"),
        "region": "cn-shenzhen",
        "zones": ["cn-shenzhen-c", "cn-shenzhen-f"],
        "alb_count": 1,
        "edition": "Standard",
        "ip_version": "IPv4",
        "network_type": "Internet",
        "eip_count": 2,
        "eip_isp": "BGP",
        "eip_charge_type": "PayByTraffic",
        "shared_bandwidth": False,
        "api_hostname": ITEM36_CURRENT_API_HOSTNAME,
    }
    egress_pricing = {
        "billing": "CDT",
        "usage_scope": "SUM_TWO_EIPS_OUTBOUND",
        "free_allowance_assumed_gb": 0,
        "tiers": [
            {"upper_tb": 10, "unit_price_cny": 0.80},
            {"upper_tb": 50, "unit_price_cny": 0.75},
            {"upper_tb": 150, "unit_price_cny": 0.70},
            {"upper_tb": None, "unit_price_cny": 0.65},
        ],
    }
    recheck = costs.get("purchase_readback")
    if not _keys_exact(
        recheck,
        {
            "observed_at", "pricing_sha256", "resource_configuration_sha256",
            "source_artifact_path", "source_artifact_sha256",
        },
    ):
        return False
    recheck_at = _evidence_clock(recheck.get("observed_at"))
    pricing = {
        "components": quote.get("components"),
        "variable_egress": quote.get("variable_egress"),
        "public_egress_pricing": quote.get("public_egress_pricing"),
        "pricing_basis_hours": quote.get("pricing_basis_hours"),
        "vat_included": quote.get("vat_included"),
    }
    current_unit_prices = {
        item["service"]: item["unit_price_cny"]
        for item in quote.get("components", [])
        if isinstance(item, dict) and "service" in item and "unit_price_cny" in item
    }
    source_paths = []
    for record in (approval, quote, recheck):
        source_path = record.get("source_artifact_path")
        source_sha = record.get("source_artifact_sha256")
        if (
            not isinstance(source_path, str)
            or not source_path.startswith("deploy/production/evidence/")
            or not _sha256(source_sha)
            or source_sha == hashlib.sha256(b"").hexdigest()
            or _actual_file_sha256(source_path, root=root) != source_sha
        ):
            return False
        source_paths.append(source_path)
    variable = quote.get("variable_egress")
    return (
        len(set(source_paths)) == len(source_paths)
        and not set(source_paths) & {
            costs.get("approval_artifact_path"),
            costs.get("quote_artifact_path"),
            costs.get("billing_readback_path"),
        }
        and approval.get("authorization_mode") == ITEM36_ACTUAL_USAGE_MODE
        and approval.get("cost_triggered_service_actions") == "NONE"
        and _canonical_object_sha256(approval.get("resource_configuration"))
        == _canonical_object_sha256(configuration)
        and _canonical_object_sha256(quote.get("resource_configuration"))
        == _canonical_object_sha256(configuration)
        and quote.get("pricing_validity") == "CURRENT_DISPLAY_NO_LOCK"
        and quote.get("vat_included") is True
        and current_unit_prices == {
            "alb_instance": 0.125, "alb_lcu": 0.042, "public_eip": 0.020,
        }
        and _canonical_object_sha256(quote.get("public_egress_pricing"))
        == _canonical_object_sha256(egress_pricing)
        and isinstance(variable, dict)
        and _finite_number(variable.get("unit_price_cny"))
        and variable["unit_price_cny"] == 0.8
        and _finite_number(variable.get("estimated_usage"))
        # This is a first-tier estimate, not a limit on actual billable usage.
        and 0 <= variable["estimated_usage"] <= 10000
        and approved_at is not None
        and resource_created_at is not None
        and recheck_at is not None
        and approved_at <= recheck_at <= resource_created_at
        and recheck_at >= resource_created_at - ITEM36_MAX_EVIDENCE_AGE
        and recheck.get("pricing_sha256") == _canonical_object_sha256(pricing)
        and recheck.get("resource_configuration_sha256")
        == _canonical_object_sha256(configuration)
    )


def validate_item36_alb_evidence(
    control: dict[str, Any],
    *,
    root: Path = ROOT,
    now: datetime | None = None,
) -> list[str]:
    """Validate pre-DNS ALB/TLS and controlled health routing only."""

    payload, errors = _schema_evidence(
        control,
        ITEM36_ALB_EVIDENCE_SCHEMA,
        root=root,
        expected_ref=ITEM36_ALB_EVIDENCE,
    )
    if payload is None:
        return errors
    actual_usage_approval = (
        isinstance(payload.get("costs"), dict)
        and payload["costs"].get("authorization_mode") == ITEM36_ACTUAL_USAGE_MODE
    )
    api_hostname = (
        ITEM36_CURRENT_API_HOSTNAME if actual_usage_approval else ITEM36_API_HOSTNAME
    )
    if not _keys_exact(
        payload,
        {
            "schema",
            "item",
            "status",
            "readiness_credit",
            "environment",
            "observed_at",
            "alb",
            "health_routing",
            "activation",
            "actual_production_write_set",
            "launch_boundary",
            "costs",
            "secret_values_recorded",
        },
    ):
        errors.append("Item36 terminal evidence schema mismatch")
    if _has_sensitive_evidence_key(payload):
        errors.append("Item36 sensitive field present")
    if (
        not _exact_int(payload.get("item"), 36)
        or payload.get("status") != "VERIFIED"
        or payload.get("readiness_credit") is not True
        or payload.get("environment") != "production"
    ):
        errors.append("Item36 terminal status mismatch")
    observed_at = _evidence_clock(payload.get("observed_at"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    freshness_floor = current - ITEM36_MAX_EVIDENCE_AGE
    if (
        observed_at is None
        or observed_at > current
        or observed_at < freshness_floor
    ):
        errors.append("Item36 observation clock invalid")

    def readback_clock(value: Any) -> datetime | None:
        if (
            not isinstance(value, dict)
            or not _keys_exact(
                value,
                {"provider", "request_identity_sha256", "response_sha256", "observed_at"},
            )
            or value.get("provider") != "aliyun"
            or not _sha256(value.get("request_identity_sha256"))
            or not _sha256(value.get("response_sha256"))
        ):
            return None
        clock = _evidence_clock(value.get("observed_at"))
        if clock is None or clock > current or clock < freshness_floor:
            return None
        return clock

    alb = payload.get("alb")
    certificate_sha256: str | None = None
    resource_created_at: datetime | None = None
    configuration_read_at: datetime | None = None
    if not isinstance(alb, dict):
        errors.append("Item36 ALB identity missing")
    else:
        if not _keys_exact(
            alb,
            {
                "alb_identity_sha256",
                "vpc_identity_sha256",
                "server_group_identity_sha256",
                "listener_identity_sha256",
                "certificate_identity_sha256",
                "public_eip_identity_sha256s",
                "region",
                "protocol",
                "listener_port",
                "dual_zone_count",
                "tls_verification",
                "hostname",
                "certificate_status",
                "certificate_dns_names",
                "certificate_sha256",
                "certificate_not_before",
                "certificate_not_after",
                "resource_created_at",
                "configuration_readback",
            },
        ):
            errors.append("Item36 ALB evidence schema mismatch")
        for field in (
            "alb_identity_sha256",
            "vpc_identity_sha256",
            "server_group_identity_sha256",
            "listener_identity_sha256",
            "certificate_identity_sha256",
        ):
            if not _sha256(alb.get(field)):
                errors.append(f"Item36 {field} missing")
        resource_identity_values = [
            alb.get(field)
            for field in (
                "alb_identity_sha256",
                "vpc_identity_sha256",
                "server_group_identity_sha256",
                "listener_identity_sha256",
                "certificate_identity_sha256",
            )
        ]
        public_eip_identities = alb.get("public_eip_identity_sha256s")
        if (
            any(not _sha256(value) for value in resource_identity_values)
            or not isinstance(public_eip_identities, list)
            or len(public_eip_identities) != 2
            or any(not _sha256(value) for value in public_eip_identities)
            or len(set(public_eip_identities)) != 2
            or len(set(resource_identity_values)) != len(resource_identity_values)
            or bool(set(resource_identity_values) & set(public_eip_identities or []))
        ):
            errors.append("Item36 resource identities are not distinct")
        certificate_sha256 = alb.get("certificate_sha256")
        certificate_names = alb.get("certificate_dns_names")
        not_before = _evidence_clock(alb.get("certificate_not_before"))
        if (
            alb.get("region") != "cn-shenzhen"
            or alb.get("protocol") != "HTTPS"
            or not _exact_int(alb.get("listener_port"), 443)
            or not _exact_int(alb.get("dual_zone_count"), 2)
            or alb.get("tls_verification") != "PASS"
            or alb.get("hostname") != api_hostname
            or alb.get("certificate_status") != "ISSUED"
            or not _sha256(certificate_sha256)
            or not isinstance(certificate_names, list)
            or any(not isinstance(value, str) for value in certificate_names)
            or len(certificate_names) != len(set(certificate_names))
            or api_hostname not in certificate_names
        ):
            errors.append("Item36 ALB/TLS configuration mismatch")
        not_after = _evidence_clock(alb.get("certificate_not_after"))
        resource_created_at = _evidence_clock(alb.get("resource_created_at"))
        configuration_read_at = readback_clock(alb.get("configuration_readback"))
        if (
            not_before is None
            or not_after is None
            or not not_before <= current < not_after
            or resource_created_at is None
            or configuration_read_at is None
            or (
                alb.get("configuration_readback", {}).get("response_sha256")
                if isinstance(alb.get("configuration_readback"), dict)
                else None
            ) != _item36_configuration_response_sha256(alb)
            or observed_at is None
            or not resource_created_at <= configuration_read_at <= observed_at
        ):
            errors.append("Item36 certificate is not currently valid")

    health = payload.get("health_routing")
    health_read_at: datetime | None = None
    probe_at: datetime | None = None
    if not isinstance(health, dict):
        errors.append("Item36 health routing evidence missing")
    else:
        if not _keys_exact(
            health,
            {
                "path",
                "expected_status",
                "provider_readback",
                "backends",
                "security_group_rule",
                "controlled_probe",
            },
        ):
            errors.append("Item36 health routing evidence schema mismatch")
        backends = health.get("backends")
        roles = (
            [item.get("role") for item in backends if isinstance(item, dict)]
            if isinstance(backends, list)
            else []
        )
        health_read_at = readback_clock(health.get("provider_readback"))
        security_group_rule = health.get("security_group_rule")
        security_group_observed_at = (
            _evidence_clock(security_group_rule.get("observed_at"))
            if isinstance(security_group_rule, dict)
            else None
        )
        backend_instance_identities = (
            sorted(
                item.get("instance_identity_sha256")
                for item in backends
                if isinstance(item, dict)
            )
            if isinstance(backends, list)
            else []
        )
        if (
            health.get("path") != "/health/ready"
            or not _exact_int(health.get("expected_status"), 200)
            or not isinstance(backends, list)
            or len(backends) != 2
            or len(roles) != len(backends)
            or any(not isinstance(role, str) for role in roles)
            or len(roles) != len(set(roles))
            or set(roles) != {"API-C", "API-F"}
            or any(
                not _keys_exact(
                    item,
                    {
                        "role",
                        "instance_identity_sha256",
                        "target_identity_sha256",
                        "target_port",
                        "target_health",
                        "private_bind",
                        "security_group_alb_only",
                        "private_address_sha256",
                        "unit_sha256",
                        "effective_unit_sha256",
                        "container_identity_sha256",
                        "health_observed_at",
                    },
                )
                or
                item.get("target_health") != "healthy"
                or item.get("private_bind") is not True
                or item.get("security_group_alb_only") is not True
                or not _sha256(item.get("instance_identity_sha256"))
                or not _sha256(item.get("target_identity_sha256"))
                or not _exact_int(item.get("target_port"), 8000)
                or not _sha256(item.get("private_address_sha256"))
                or not _sha256(item.get("unit_sha256"))
                or not _sha256(item.get("effective_unit_sha256"))
                or not _sha256(item.get("container_identity_sha256"))
                or _evidence_clock(item.get("health_observed_at")) is None
                for item in backends
                if isinstance(item, dict)
            )
            or health_read_at is None
            or (
                health.get("provider_readback", {}).get("response_sha256")
                if isinstance(health.get("provider_readback"), dict)
                else None
            ) != _item36_health_response_sha256(health, alb)
        ):
            errors.append("Item36 controlled health route mismatch")
        if isinstance(backends, list) and len(backends) == 2:
            for identity_field in (
                "instance_identity_sha256",
                "target_identity_sha256",
                "private_address_sha256",
                "container_identity_sha256",
            ):
                identities = [
                    item.get(identity_field)
                    for item in backends
                    if isinstance(item, dict)
                ]
                if (
                    len(identities) != 2
                    or any(not _sha256(value) for value in identities)
                    or len(set(identities)) != 2
                ):
                    errors.append("Item36 backend identities are not distinct")
                    break
        if (
            not isinstance(security_group_rule, dict)
            or not _keys_exact(
                security_group_rule,
                {
                    "provider",
                    "api_security_group_identity_sha256",
                    "alb_security_group_identity_sha256",
                    "rule_identity_sha256",
                    "source_type",
                    "source_identity_sha256",
                    "protocol",
                    "destination_port",
                    "target_instance_identity_sha256s",
                    "wider_ingress_rule_count",
                    "request_identity_sha256",
                    "response_sha256",
                    "observed_at",
                },
            )
            or security_group_rule.get("provider") != "aliyun"
            or any(
                not _sha256(security_group_rule.get(field))
                for field in (
                    "api_security_group_identity_sha256",
                    "alb_security_group_identity_sha256",
                    "rule_identity_sha256",
                    "source_identity_sha256",
                    "request_identity_sha256",
                    "response_sha256",
                )
            )
            or len(
                {
                    security_group_rule.get("api_security_group_identity_sha256"),
                    security_group_rule.get("alb_security_group_identity_sha256"),
                    security_group_rule.get("rule_identity_sha256"),
                }
            )
            != 3
            or security_group_rule.get("source_type") != "security_group"
            or security_group_rule.get("source_identity_sha256")
            != security_group_rule.get("alb_security_group_identity_sha256")
            or security_group_rule.get("protocol") != "TCP"
            or not _exact_int(security_group_rule.get("destination_port"), 8000)
            or security_group_rule.get("target_instance_identity_sha256s")
            != backend_instance_identities
            or len(backend_instance_identities) != 2
            or len(set(backend_instance_identities)) != 2
            or not _exact_int(
                security_group_rule.get("wider_ingress_rule_count"), 0
            )
            or security_group_rule.get("response_sha256")
            != _item36_security_group_response_sha256(
                security_group_rule, alb, backends
            )
            or security_group_observed_at is None
            or security_group_observed_at < freshness_floor
            or security_group_observed_at > current
        ):
            errors.append("Item36 ALB-only security-group rule mismatch")
        probe = health.get("controlled_probe")
        probe_at = (
            _evidence_clock(probe.get("executed_at"))
            if isinstance(probe, dict)
            else None
        )
        if (
            not isinstance(probe, dict)
            or not _keys_exact(
                probe,
                {
                    "result",
                    "executed_at",
                    "connection_mode",
                    "endpoint_identity_sha256",
                    "hostname",
                    "sni_hostname",
                    "host_header",
                    "path",
                    "status_code",
                    "tls_verified",
                    "certificate_sha256",
                    "run_identity_sha256",
                    "response_sha256",
                },
            )
            or probe.get("result") != "PASS"
            or probe.get("connection_mode") != "pre_dns_ip_override"
            or probe.get("endpoint_identity_sha256")
            not in (alb.get("public_eip_identity_sha256s", []) if isinstance(alb, dict) else [])
            or probe.get("hostname") != api_hostname
            or probe.get("sni_hostname") != api_hostname
            or probe.get("host_header") != api_hostname
            or probe.get("path") != "/health/ready"
            or not _exact_int(probe.get("status_code"), 200)
            or probe.get("tls_verified") is not True
            or probe.get("certificate_sha256") != certificate_sha256
            or not _sha256(probe.get("run_identity_sha256"))
            or not _sha256(probe.get("response_sha256"))
            or probe.get("response_sha256")
            != _item36_probe_response_sha256(probe, alb)
            or probe_at is None
            or observed_at is None
            or probe_at > observed_at
        ):
            errors.append("Item36 controlled TLS probe mismatch")

    activation = payload.get("activation")
    activation_finished_at: datetime | None = None
    ndr_observed_at: datetime | None = None
    if not isinstance(activation, dict):
        errors.append("Item36 bounded rolling activation evidence missing")
    else:
        if not _keys_exact(
            activation,
            {
                "mode",
                "result",
                "started_at",
                "finished_at",
                "planned_restart_count",
                "unplanned_restart_count",
                "fresh_ndr",
                "rollback_state_retained",
                "rollback_unit_sha256",
                "backend_executions",
            },
        ):
            errors.append("Item36 activation evidence schema mismatch")
        activation_started_at = _evidence_clock(activation.get("started_at"))
        activation_finished_at = _evidence_clock(activation.get("finished_at"))
        fresh_ndr = activation.get("fresh_ndr")
        ndr_observed_at = (
            _evidence_clock(fresh_ndr.get("observed_at"))
            if isinstance(fresh_ndr, dict)
            else None
        )
        ndr_units = (
            fresh_ndr.get("units") if isinstance(fresh_ndr, dict) else None
        )
        ndr_unit_names = (
            [item.get("name") for item in ndr_units if isinstance(item, dict)]
            if isinstance(ndr_units, list)
            else []
        )
        executions = activation.get("backend_executions")
        execution_roles = (
            [item.get("role") for item in executions if isinstance(item, dict)]
            if isinstance(executions, list)
            else []
        )
        execution_windows_valid = False
        if (
            isinstance(executions, list)
            and len(executions) == 2
            and activation_started_at is not None
            and activation_finished_at is not None
        ):
            execution_windows = [
                (
                    _evidence_clock(item.get("started_at")),
                    _evidence_clock(item.get("finished_at")),
                )
                for item in executions
                if isinstance(item, dict)
            ]
            execution_windows_valid = (
                len(execution_windows) == 2
                and all(
                    started is not None
                    and finished is not None
                    and activation_started_at <= started <= finished
                    <= activation_finished_at
                    for started, finished in execution_windows
                )
                and execution_windows[0][1] <= execution_windows[1][0]
            )
        if (
            activation.get("mode") != "BOUNDED_ROLLING"
            or activation.get("result") != "PASS"
            or not _exact_int(activation.get("planned_restart_count"), 2)
            or not _exact_int(activation.get("unplanned_restart_count"), 0)
            or activation.get("rollback_state_retained") is not True
            or not _sha256(activation.get("rollback_unit_sha256"))
            or activation.get("rollback_unit_sha256")
            != _item36_rollback_unit_sha256(executions)
            or not isinstance(fresh_ndr, dict)
            or not _keys_exact(
                fresh_ndr,
                {"instance_role", "mask", "observed_at", "readback_sha256", "units"},
            )
            or fresh_ndr.get("instance_role") != "API-F"
            or not _exact_int(fresh_ndr.get("mask"), 0)
            or not _sha256(fresh_ndr.get("readback_sha256"))
            or fresh_ndr.get("readback_sha256")
            != _item36_ndr_readback_sha256(fresh_ndr)
            or not isinstance(ndr_units, list)
            or len(ndr_units) != 3
            or len(ndr_unit_names) != len(ndr_units)
            or any(not isinstance(name, str) for name in ndr_unit_names)
            or len(ndr_unit_names) != len(set(ndr_unit_names))
            or set(ndr_unit_names)
            != {
                "noteai-api.service",
                "noteai-xhs-trends.service",
                "noteai-xhs-tracking.service",
            }
            or any(
                not _keys_exact(
                    item,
                    {"name", "unit_file_sha256", "effective_unit_sha256"},
                )
                or not _sha256(item.get("unit_file_sha256"))
                or not _sha256(item.get("effective_unit_sha256"))
                for item in ndr_units
                if isinstance(item, dict)
            )
            or activation_started_at is None
            or activation_finished_at is None
            or ndr_observed_at is None
            or observed_at is None
            or not activation_started_at
            <= activation_finished_at
            <= ndr_observed_at
            <= observed_at
            or activation_started_at < freshness_floor
            or not isinstance(executions, list)
            or len(executions) != 2
            or len(execution_roles) != len(executions)
            or any(not isinstance(role, str) for role in execution_roles)
            or len(execution_roles) != len(set(execution_roles))
            or execution_roles != ["API-C", "API-F"]
            or not execution_windows_valid
            or any(
                not _keys_exact(
                    item,
                    {
                        "role",
                        "result",
                        "planned_restart_count",
                        "exit_code",
                        "started_at",
                        "finished_at",
                        "command_identity_sha256",
                        "invoke_identity_sha256",
                        "output_sha256",
                        "before_unit_sha256",
                        "after_unit_sha256",
                        "after_effective_unit_sha256",
                        "before_container_identity_sha256",
                        "after_container_identity_sha256",
                    },
                )
                or item.get("result") != "PASS"
                or not _exact_int(item.get("planned_restart_count"), 1)
                or not _exact_int(item.get("exit_code"), 0)
                or not _sha256(item.get("command_identity_sha256"))
                or not _sha256(item.get("invoke_identity_sha256"))
                or not _sha256(item.get("output_sha256"))
                or item.get("output_sha256")
                != _item36_activation_output_sha256(item)
                or not _sha256(item.get("before_unit_sha256"))
                or not _sha256(item.get("after_unit_sha256"))
                or not _sha256(item.get("after_effective_unit_sha256"))
                or item.get("before_unit_sha256") == item.get("after_unit_sha256")
                or not _sha256(item.get("before_container_identity_sha256"))
                or not _sha256(item.get("after_container_identity_sha256"))
                or item.get("before_container_identity_sha256")
                == item.get("after_container_identity_sha256")
                for item in executions
                if isinstance(item, dict)
            )
        ):
            errors.append("Item36 bounded rolling activation evidence invalid")
        if (
            activation.get("rollback_unit_sha256")
            != _item36_rollback_unit_sha256(executions)
        ):
            errors.append("Item36 rollback binding mismatch")

    identity_binding_valid = False
    if (
        isinstance(health, dict)
        and isinstance(health.get("backends"), list)
        and isinstance(activation, dict)
        and isinstance(activation.get("backend_executions"), list)
        and isinstance(activation.get("fresh_ndr"), dict)
        and isinstance(activation["fresh_ndr"].get("units"), list)
    ):
        health_by_role = {
            item.get("role"): item
            for item in health["backends"]
            if isinstance(item, dict) and isinstance(item.get("role"), str)
        }
        execution_by_role = {
            item.get("role"): item
            for item in activation["backend_executions"]
            if isinstance(item, dict) and isinstance(item.get("role"), str)
        }
        ndr_by_name = {
            item.get("name"): item
            for item in activation["fresh_ndr"]["units"]
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        identity_binding_valid = (
            set(health_by_role) == {"API-C", "API-F"}
            and set(execution_by_role) == {"API-C", "API-F"}
            and all(
                execution_by_role[role].get("after_unit_sha256")
                == health_by_role[role].get("unit_sha256")
                and execution_by_role[role].get("after_effective_unit_sha256")
                == health_by_role[role].get("effective_unit_sha256")
                and execution_by_role[role].get(
                    "after_container_identity_sha256"
                )
                == health_by_role[role].get("container_identity_sha256")
                for role in ("API-C", "API-F")
            )
            and isinstance(ndr_by_name.get("noteai-api.service"), dict)
            and ndr_by_name["noteai-api.service"].get("unit_file_sha256")
            == health_by_role["API-F"].get("unit_sha256")
            and ndr_by_name["noteai-api.service"].get("effective_unit_sha256")
            == health_by_role["API-F"].get("effective_unit_sha256")
        )
    if not identity_binding_valid:
        errors.append("Item36 activation/health identity binding mismatch")

    configuration_readback = (
        alb.get("configuration_readback") if isinstance(alb, dict) else None
    )
    provider_readback = (
        health.get("provider_readback") if isinstance(health, dict) else None
    )
    security_group_readback = (
        health.get("security_group_rule") if isinstance(health, dict) else None
    )
    controlled_probe = (
        health.get("controlled_probe") if isinstance(health, dict) else None
    )
    fresh_ndr = (
        activation.get("fresh_ndr") if isinstance(activation, dict) else None
    )
    execution_events = (
        activation.get("backend_executions")
        if isinstance(activation, dict)
        else None
    )
    stage_identities = [
        configuration_readback.get("request_identity_sha256")
        if isinstance(configuration_readback, dict)
        else None,
        provider_readback.get("request_identity_sha256")
        if isinstance(provider_readback, dict)
        else None,
        security_group_readback.get("request_identity_sha256")
        if isinstance(security_group_readback, dict)
        else None,
        controlled_probe.get("run_identity_sha256")
        if isinstance(controlled_probe, dict)
        else None,
        fresh_ndr.get("readback_sha256")
        if isinstance(fresh_ndr, dict)
        else None,
    ]
    request_response_pairs = [
        (
            configuration_readback.get("request_identity_sha256"),
            configuration_readback.get("response_sha256"),
        )
        if isinstance(configuration_readback, dict)
        else (None, None),
        (
            provider_readback.get("request_identity_sha256"),
            provider_readback.get("response_sha256"),
        )
        if isinstance(provider_readback, dict)
        else (None, None),
        (
            security_group_readback.get("request_identity_sha256"),
            security_group_readback.get("response_sha256"),
        )
        if isinstance(security_group_readback, dict)
        else (None, None),
        (
            controlled_probe.get("run_identity_sha256"),
            controlled_probe.get("response_sha256"),
        )
        if isinstance(controlled_probe, dict)
        else (None, None),
    ]
    execution_invoke_output_pairs = [
        (item.get("invoke_identity_sha256"), item.get("output_sha256"))
        for item in execution_events
        if isinstance(item, dict)
    ] if isinstance(execution_events, list) else []
    execution_invoke_identities = [
        pair[0] for pair in execution_invoke_output_pairs
    ]
    execution_container_identities = [
        identity
        for item in execution_events
        if isinstance(item, dict)
        for identity in (
            item.get("before_container_identity_sha256"),
            item.get("after_container_identity_sha256"),
        )
    ] if isinstance(execution_events, list) else []
    if (
        any(not _sha256(value) for value in stage_identities)
        or len(set(stage_identities)) != len(stage_identities)
        or any(
            not _sha256(left) or not _sha256(right) or left == right
            for left, right in request_response_pairs
        )
        or len(execution_invoke_output_pairs) != 2
        or any(
            not _sha256(left) or not _sha256(right) or left == right
            for left, right in execution_invoke_output_pairs
        )
        or len(set(execution_invoke_identities))
        != len(execution_invoke_identities)
    ):
        errors.append("Item36 operational evidence identities are not distinct")
    if (
        len(execution_container_identities) != 4
        or any(not _sha256(value) for value in execution_container_identities)
        or len(set(execution_container_identities)) != 4
    ):
        errors.append("Item36 container identities are not distinct")

    health_clocks: list[datetime] = []
    if isinstance(health, dict) and isinstance(health.get("backends"), list):
        health_clocks = [
            clock
            for item in health["backends"]
            if isinstance(item, dict)
            for clock in [_evidence_clock(item.get("health_observed_at"))]
            if clock is not None
        ]
    if (
        activation_finished_at is None
        or configuration_read_at is None
        or health_read_at is None
        or probe_at is None
        or security_group_observed_at is None
        or len(health_clocks) != 2
        or any(clock < freshness_floor for clock in health_clocks)
        or any(clock < activation_finished_at for clock in health_clocks)
        or any(clock > health_read_at for clock in health_clocks)
        or configuration_read_at < activation_finished_at
        or health_read_at < activation_finished_at
        or security_group_observed_at < activation_finished_at
        or probe_at
        < max(
            configuration_read_at,
            health_read_at,
            security_group_observed_at,
            *health_clocks,
        )
    ):
        errors.append("Item36 post-activation freshness binding missing")

    writes = payload.get("actual_production_write_set")
    if (
        not isinstance(writes, dict)
        or not _keys_exact(
            writes,
            {
                "alb_instance_create_count",
                "server_group_create_count",
                "https_listener_create_count",
                "certificate_binding_count",
                "backend_registration_count",
                "api_unit_update_count",
                "security_group_rule_change_count",
                "planned_service_restart_count",
                "unplanned_service_restart_count",
                "public_eip_change_count",
                "new_vpc_count",
                "waf_resource_count",
                "extra_resource_count",
                "production_database_write_count",
                "payment_or_funds_action_count",
                "dns_write_count",
            },
        )
        or not _exact_int(writes.get("alb_instance_create_count"), 1)
        or not _exact_int(writes.get("server_group_create_count"), 1)
        or not _exact_int(writes.get("https_listener_create_count"), 1)
        or not _exact_int(writes.get("certificate_binding_count"), 1)
        or not _exact_int(writes.get("backend_registration_count"), 2)
        or not _exact_int(writes.get("api_unit_update_count"), 2)
        or not _exact_int(writes.get("security_group_rule_change_count"), 1)
        or not _exact_int(writes.get("planned_service_restart_count"), 2)
        or not _exact_int(writes.get("unplanned_service_restart_count"), 0)
        or not _exact_int(writes.get("public_eip_change_count"))
        or not 0 <= writes["public_eip_change_count"] <= 2
        or not _exact_int(writes.get("new_vpc_count"), 0)
        or not _exact_int(writes.get("waf_resource_count"), 0)
        or not _exact_int(writes.get("extra_resource_count"), 0)
        or not _exact_int(writes.get("production_database_write_count"), 0)
        or not _exact_int(writes.get("payment_or_funds_action_count"), 0)
        or not _exact_int(writes.get("dns_write_count"), 0)
    ):
        errors.append("Item36 actual production write set invalid")

    boundary = payload.get("launch_boundary")
    if (
        not isinstance(boundary, dict)
        or not _keys_exact(
            boundary,
            {
                "dns_write_count",
                "real_user_request_count",
                "synthetic_probe_only",
                "production_database_write_count",
                "payment_or_funds_action_count",
            },
        )
        or not _exact_int(boundary.get("dns_write_count"), 0)
        or not _exact_int(boundary.get("real_user_request_count"), 0)
        or boundary.get("synthetic_probe_only") is not True
        or not _exact_int(boundary.get("production_database_write_count"), 0)
        or not _exact_int(boundary.get("payment_or_funds_action_count"), 0)
    ):
        errors.append("Item36 pre-DNS boundary mismatch")
    costs = payload.get("costs")
    costs_invalid = not isinstance(costs, dict)
    if isinstance(costs, dict):
        approved_at = _evidence_clock(costs.get("approved_at"))
        quote_observed_at = _evidence_clock(costs.get("quote_observed_at"))
        quote_valid_until = _evidence_clock(costs.get("quote_valid_until"))
        approved_ceiling = costs.get("approved_monthly_ceiling_cny")
        approved_egress_ceiling = costs.get(
            "approved_variable_egress_ceiling_cny"
        )
        estimated = costs.get("estimated_monthly_cny")
        estimated_egress = costs.get("estimated_variable_egress_cny")
        actual_incurred = costs.get("actual_incurred_cny_to_observed_at")
        actual_egress = costs.get(
            "actual_variable_egress_cny_to_observed_at"
        )
        components = costs.get("components")
        variable_egress = costs.get("variable_egress")
        approval, actual_approval_sha = _read_json_artifact(
            costs.get("approval_artifact_path"),
            (
                ITEM36_ACTUAL_USAGE_APPROVAL_SCHEMA
                if actual_usage_approval else ITEM36_COST_APPROVAL_SCHEMA
            ),
            root=root,
        )
        quote, actual_quote_sha = _read_json_artifact(
            costs.get("quote_artifact_path"),
            (
                ITEM36_CURRENT_QUOTE_SCHEMA
                if actual_usage_approval else ITEM36_COST_QUOTE_SCHEMA
            ),
            root=root,
        )
        billing, actual_billing_sha = _read_json_artifact(
            costs.get("billing_readback_path"),
            ITEM36_BILLING_READBACK_SCHEMA,
            root=root,
        )
        approval_scope = (
            approval.get("resource_scope")
            if isinstance(approval, dict)
            else None
        )
        component_names = (
            [item.get("service") for item in components if isinstance(item, dict)]
            if isinstance(components, list)
            else []
        )
        component_total = (
            sum(float(item["estimated_monthly_cny"]) for item in components)
            if isinstance(components, list)
            and all(
                isinstance(item, dict)
                and _finite_number(item.get("estimated_monthly_cny"))
                for item in components
            )
            else math.nan
        )
        quote_components = (
            quote.get("components") if isinstance(quote, dict) else None
        )
        quote_variable_egress = (
            quote.get("variable_egress") if isinstance(quote, dict) else None
        )
        quote_component_names = (
            [item.get("service") for item in quote_components if isinstance(item, dict)]
            if isinstance(quote_components, list)
            else []
        )
        quote_component_total = (
            sum(
                float(item["estimated_monthly_cny"])
                for item in quote_components
            )
            if isinstance(quote_components, list)
            and all(
                isinstance(item, dict)
                and _finite_number(item.get("estimated_monthly_cny"))
                for item in quote_components
            )
            else math.nan
        )
        billing_items = (
            billing.get("line_items") if isinstance(billing, dict) else None
        )
        billing_item_names = (
            [item.get("service") for item in billing_items if isinstance(item, dict)]
            if isinstance(billing_items, list)
            else []
        )
        billing_total = (
            sum(float(item["actual_incurred_cny"]) for item in billing_items)
            if isinstance(billing_items, list)
            and all(
                isinstance(item, dict)
                and _finite_number(item.get("actual_incurred_cny"))
                for item in billing_items
            )
            else math.nan
        )
        billing_egress = (
            next(
                (
                    float(item["actual_incurred_cny"])
                    for item in billing_items
                    if isinstance(item, dict)
                    and item.get("service") == "public_egress"
                    and _finite_number(item.get("actual_incurred_cny"))
                ),
                math.nan,
            )
            if isinstance(billing_items, list)
            else math.nan
        )
        billing_fixed_total = (
            billing_total - billing_egress
            if math.isfinite(billing_total) and math.isfinite(billing_egress)
            else math.nan
        )
        billing_observed_at = (
            _evidence_clock(billing.get("observed_at"))
            if isinstance(billing, dict)
            else None
        )
        expected_services = {"alb_instance", "alb_lcu", "public_eip"}
        expected_billing_services = expected_services | {"public_egress"}
        expected_quantities = {
            "alb_instance": 1,
            "alb_lcu": 1,
            "public_eip": 2,
        }
        expected_units = {
            "alb_instance": "instance_hour",
            "alb_lcu": "lcu_hour",
            "public_eip": "ip_hour",
        }
        retired_cost_fields = {
            "approved_monthly_ceiling_cny",
            "approved_variable_egress_ceiling_cny",
            "quote_valid_until",
        } if actual_usage_approval else set()
        current_cost_fields = (
            {"authorization_mode", "purchase_readback"}
            if actual_usage_approval else set()
        )
        current_approval_fields = {
            "authorization_mode", "cost_triggered_service_actions",
            "resource_configuration", "source_artifact_path",
            "source_artifact_sha256",
        } if actual_usage_approval else set()
        current_quote_fields = {
            "pricing_validity", "vat_included", "public_egress_pricing",
            "resource_configuration", "source_artifact_path",
            "source_artifact_sha256",
        } if actual_usage_approval else set()
        pricing_hours = quote.get("pricing_basis_hours") if isinstance(quote, dict) else None
        terminal_components_by_name = (
            {
                item["service"]: float(item["estimated_monthly_cny"])
                for item in components
            }
            if isinstance(components, list)
            and all(
                isinstance(item, dict)
                and isinstance(item.get("service"), str)
                and _finite_number(item.get("estimated_monthly_cny"))
                for item in components
            )
            else {}
        )
        quote_components_by_name = (
            {
                item["service"]: float(item["estimated_monthly_cny"])
                for item in quote_components
            }
            if isinstance(quote_components, list)
            and all(
                isinstance(item, dict)
                and isinstance(item.get("service"), str)
                and _finite_number(item.get("estimated_monthly_cny"))
                for item in quote_components
            )
            else {}
        )
        costs_invalid = (
            not _keys_exact(
                costs,
                {
                    "owner_recurring_cost_approved",
                    "approval_artifact_path",
                    "approval_artifact_sha256",
                    "approved_at",
                    "approved_monthly_ceiling_cny",
                    "approved_variable_egress_ceiling_cny",
                    "quote_artifact_path",
                    "quote_sha256",
                    "quote_observed_at",
                    "quote_valid_until",
                    "estimated_monthly_cny",
                    "estimated_variable_egress_cny",
                    "actual_incurred_cny_to_observed_at",
                    "actual_variable_egress_cny_to_observed_at",
                    "billing_readback_path",
                    "billing_readback_sha256",
                    "components",
                    "variable_egress",
                } - retired_cost_fields | current_cost_fields,
            )
            or costs.get("owner_recurring_cost_approved") is not True
            or not _sha256(costs.get("quote_sha256"))
            or actual_quote_sha != costs.get("quote_sha256")
            or (
                not actual_usage_approval
                and (
                    not _finite_number(approved_ceiling)
                    or approved_ceiling <= 0
                    or not _finite_number(approved_egress_ceiling)
                    or approved_egress_ceiling <= 0
                )
            )
            or not _finite_number(estimated)
            or estimated <= 0
            or (not actual_usage_approval and estimated > approved_ceiling)
            or not _finite_number(estimated_egress)
            or estimated_egress < 0
            or (not actual_usage_approval and estimated_egress > approved_egress_ceiling)
            or not _finite_number(actual_incurred)
            or actual_incurred < 0
            or (
                not actual_usage_approval
                and actual_incurred > approved_ceiling + approved_egress_ceiling
            )
            or not _finite_number(actual_egress)
            or actual_egress < 0
            or (not actual_usage_approval and actual_egress > approved_egress_ceiling)
            or not math.isfinite(billing_fixed_total)
            or billing_fixed_total < 0
            or (not actual_usage_approval and billing_fixed_total > approved_ceiling)
            or not math.isclose(
                float(actual_egress), billing_egress, abs_tol=0.01
            )
            or not _sha256(costs.get("billing_readback_sha256"))
            or actual_billing_sha != costs.get("billing_readback_sha256")
            or not isinstance(components, list)
            or len(components) != 3
            or len(component_names) != len(components)
            or any(not isinstance(name, str) for name in component_names)
            or len(component_names) != len(set(component_names))
            or set(component_names) != {"alb_instance", "alb_lcu", "public_eip"}
            or any(
                not _keys_exact(item, {"service", "estimated_monthly_cny"})
                or item["estimated_monthly_cny"] < 0
                for item in components
                if isinstance(item, dict)
                and _finite_number(item.get("estimated_monthly_cny"))
            )
            or not math.isclose(component_total, float(estimated), abs_tol=0.01)
            or not _keys_exact(
                variable_egress,
                {
                    "service",
                    "unit",
                    "unit_price_cny",
                    "estimated_usage",
                    "estimated_cost_cny",
                },
            )
            or variable_egress.get("service") != "public_egress"
            or variable_egress.get("unit") != "GB"
            or not _finite_number(variable_egress.get("unit_price_cny"))
            or variable_egress.get("unit_price_cny") <= 0
            or not _finite_number(variable_egress.get("estimated_usage"))
            or variable_egress.get("estimated_usage") < 0
            or not _finite_number(variable_egress.get("estimated_cost_cny"))
            or variable_egress.get("estimated_cost_cny") < 0
            or not math.isclose(
                float(variable_egress.get("estimated_cost_cny", math.nan)),
                float(variable_egress.get("unit_price_cny", math.nan))
                * float(variable_egress.get("estimated_usage", math.nan)),
                abs_tol=0.01,
            )
            or not math.isclose(
                float(variable_egress.get("estimated_cost_cny", math.nan)),
                float(estimated_egress),
                abs_tol=0.01,
            )
            or approved_at is None
            or quote_observed_at is None
            or (not actual_usage_approval and quote_valid_until is None)
            or resource_created_at is None
            or not quote_observed_at <= approved_at <= resource_created_at
            or (not actual_usage_approval and not resource_created_at <= quote_valid_until)
            or not isinstance(approval, dict)
            or not _keys_exact(
                approval,
                {
                    "schema",
                    "status",
                    "approved_at",
                    "approved_monthly_ceiling_cny",
                    "approved_variable_egress_ceiling_cny",
                    "resource_scope",
                    "quote_sha256",
                    "quote_observed_at",
                    "quote_valid_until",
                    "secret_values_recorded",
                } - retired_cost_fields | current_approval_fields,
            )
            or actual_approval_sha != costs.get("approval_artifact_sha256")
            or approval.get("status") != "APPROVED"
            or _evidence_clock(approval.get("approved_at")) != approved_at
            or (
                not actual_usage_approval
                and (
                    approval.get("approved_monthly_ceiling_cny") != approved_ceiling
                    or approval.get("approved_variable_egress_ceiling_cny")
                    != approved_egress_ceiling
                )
            )
            or not isinstance(approval_scope, list)
            or len(approval_scope) != 4
            or any(not isinstance(value, str) for value in approval_scope)
            or set(approval_scope) != expected_billing_services
            or approval.get("quote_sha256") != costs.get("quote_sha256")
            or _evidence_clock(approval.get("quote_observed_at"))
            != quote_observed_at
            or (
                not actual_usage_approval
                and _evidence_clock(approval.get("quote_valid_until"))
                != quote_valid_until
            )
            or approval.get("secret_values_recorded") is not False
            or _has_sensitive_evidence_key(approval)
            or not isinstance(quote, dict)
            or not _keys_exact(
                quote,
                {
                    "schema",
                    "provider",
                    "region",
                    "currency",
                    "observed_at",
                    "valid_until",
                    "pricing_basis_hours",
                    "components",
                    "variable_egress",
                    "estimated_monthly_cny",
                    "secret_values_recorded",
                } - ({"valid_until"} if actual_usage_approval else set())
                | current_quote_fields,
            )
            or quote.get("provider") != "aliyun"
            or quote.get("region") != "cn-shenzhen"
            or quote.get("currency") != "CNY"
            or _evidence_clock(quote.get("observed_at")) != quote_observed_at
            or (
                not actual_usage_approval
                and _evidence_clock(quote.get("valid_until")) != quote_valid_until
            )
            or not _exact_int(pricing_hours)
            or pricing_hours not in ((720, 744) if actual_usage_approval else (720,))
            or not isinstance(quote_components, list)
            or len(quote_components) != 3
            or len(quote_component_names) != len(quote_components)
            or any(not isinstance(name, str) for name in quote_component_names)
            or len(quote_component_names) != len(set(quote_component_names))
            or set(quote_component_names) != expected_services
            or any(
                not _keys_exact(
                    item,
                    {
                        "service",
                        "quantity",
                        "unit",
                        "unit_price_cny",
                        "estimated_monthly_cny",
                    },
                )
                or (
                    not (
                        _finite_number(item.get("quantity"))
                        and item["quantity"] >= 0
                    )
                    if actual_usage_approval and item.get("service") == "alb_lcu"
                    else not _exact_int(
                        item.get("quantity"),
                        expected_quantities.get(item.get("service")),
                    )
                )
                or item.get("unit") != expected_units.get(item.get("service"))
                or not _finite_number(item.get("unit_price_cny"))
                or item["unit_price_cny"] <= 0
                or not _finite_number(item.get("estimated_monthly_cny"))
                or (
                    item["estimated_monthly_cny"] < 0
                    if actual_usage_approval and item.get("service") == "alb_lcu"
                    else item["estimated_monthly_cny"] <= 0
                )
                or not math.isclose(
                    float(item["estimated_monthly_cny"]),
                    float(item["unit_price_cny"])
                    * float(item["quantity"])
                    * pricing_hours,
                    abs_tol=0.01,
                )
                for item in quote_components
                if isinstance(item, dict)
            )
            or not _finite_number(quote.get("estimated_monthly_cny"))
            or not math.isclose(
                quote_component_total,
                float(quote.get("estimated_monthly_cny", math.nan)),
                abs_tol=0.01,
            )
            or not math.isclose(
                float(quote.get("estimated_monthly_cny", math.nan)),
                float(estimated),
                abs_tol=0.01,
            )
            or quote_components_by_name != terminal_components_by_name
            or quote_variable_egress != variable_egress
            or quote.get("secret_values_recorded") is not False
            or _has_sensitive_evidence_key(quote)
            or not isinstance(billing, dict)
            or not _keys_exact(
                billing,
                {
                    "schema",
                    "provider",
                    "region",
                    "currency",
                    "observed_at",
                    "resource_scope_identity_sha256",
                    "line_items",
                    "actual_incurred_cny",
                    "secret_values_recorded",
                },
            )
            or billing.get("provider") != "aliyun"
            or billing.get("region") != "cn-shenzhen"
            or billing.get("currency") != "CNY"
            or not _sha256(billing.get("resource_scope_identity_sha256"))
            or billing.get("resource_scope_identity_sha256")
            != _item36_resource_scope_sha256(alb)
            or billing_observed_at is None
            or resource_created_at is None
            or observed_at is None
            or not resource_created_at <= billing_observed_at <= observed_at
            or billing_observed_at < freshness_floor
            or probe_at is None
            or billing_observed_at < probe_at
            or not isinstance(billing_items, list)
            or len(billing_items) != 4
            or len(billing_item_names) != len(billing_items)
            or any(not isinstance(name, str) for name in billing_item_names)
            or len(billing_item_names) != len(set(billing_item_names))
            or set(billing_item_names) != expected_billing_services
            or any(
                not _keys_exact(item, {"service", "actual_incurred_cny"})
                or not _finite_number(item.get("actual_incurred_cny"))
                or item["actual_incurred_cny"] < 0
                for item in billing_items
                if isinstance(item, dict)
            )
            or not _finite_number(billing.get("actual_incurred_cny"))
            or not math.isclose(
                billing_total,
                float(billing.get("actual_incurred_cny", math.nan)),
                abs_tol=0.01,
            )
            or not math.isclose(
                float(billing.get("actual_incurred_cny", math.nan)),
                float(actual_incurred),
                abs_tol=0.01,
            )
            or billing.get("secret_values_recorded") is not False
            or _has_sensitive_evidence_key(billing)
        )
        if actual_usage_approval and not costs_invalid:
            costs_invalid = not _item36_current_cost_terms_valid(
                costs, approval, quote, alb,
                approved_at=approved_at,
                resource_created_at=resource_created_at,
                root=root,
            )
    if costs_invalid:
        errors.append("Item36 recurring-cost approval missing")
    if payload.get("secret_values_recorded") is not False:
        errors.append("Item36 secret-value exclusion missing")
    return errors


def _validate_item34_auxiliary_effects(value: Any, *, generation: int = 0,
                                       authorization: Any = None) -> list[str]:
    """The September 7 owner supplement; direct auth counts may be unobserved.

    This is a scoped disclosure in the existing write ledger, not a whole-DB
    audit. Action names fix the allowed auth code paths; arbitrary tables,
    columns, policies or privileges cannot be added through this object.
    """
    error = ["Item34 authorized auxiliary effects invalid"]
    base_keys = {
        "authorization_checkpoint", "authorization_plan_sha256",
        "execution_record_ref", "authentication", "policy_ddl",
        "temporary_attempts_select", "safety_flag", "unexpected_effects",
    }
    if not isinstance(value, dict) or not (
        _keys_exact(value, base_keys)
        or _keys_exact(value, base_keys | {"test_account_setup"})
    ):
        return error
    expected_checkpoint = "9802111a27b131e510c1c686870121baead5c45d"
    expected_plan = "ae5b7fa36456dd01a7c1b9be63889d0e9d86298e54d354082c90859b0116e47d"
    expected_policy = {"operation": "APPLY_EXACT_0019",
                       "readback": "USE_EXISTING_RUNTIME_CONFIG_MIGRATION"}
    if generation in {1,2}:
        # Filled from a future explicit owner approval in the SAME manifest;
        # absent today. The closed approval cannot authorize another job.
        if (not isinstance(authorization, dict) or not _keys_exact(authorization, {
                "authorization_checkpoint", "authorization_plan_sha256"})
            or not isinstance(authorization["authorization_checkpoint"], str)
            or re.fullmatch(r"[0-9a-f]{40}", authorization["authorization_checkpoint"]) is None
            or authorization["authorization_checkpoint"] == expected_checkpoint
            or not isinstance(authorization["authorization_plan_sha256"], str)
            or SHA256.fullmatch(authorization["authorization_plan_sha256"]) is None
            or authorization["authorization_plan_sha256"] == expected_plan
            or "test_account_setup" in value or value["authentication"] != []):
            return error
        expected_checkpoint = authorization["authorization_checkpoint"]
        expected_plan = authorization["authorization_plan_sha256"]
        expected_policy = {"operation": "APPLY_EXACT_0020_VERIFY_EXISTING_0019",
                           "readback": "USE_EXISTING_MIGRATION_RECORDS"}
        if generation==2:
            expected_policy['operation']='VERIFY_EXISTING_0019_0020'
    # The later owner instruction authorizes exactly one new test identity and
    # one 900-point gift. Keep it in this SAME auxiliary ledger/write digest;
    # it cannot be disguised as an existing-user login or a core Tracking row.
    if "test_account_setup" in value:
        setup = value["test_account_setup"]
        setup_error = ["Item34 owner test account setup invalid"]
        if not isinstance(setup, dict) or not _keys_exact(setup, {
            "authorization_record_ref", "username_sha256", "user_identity_sha256",
            "registration", "credit_gift",
        }):
            return setup_error
        if (setup["authorization_record_ref"] != ".codex/handoffs/current-task.md"
                or setup["username_sha256"] != "56e5c09dfca80f6c2f70b328fc42af3c125bdd97c8beb47b93747f2e16cf7387"
                or not isinstance(setup["user_identity_sha256"], str)
                or SHA256.fullmatch(setup["user_identity_sha256"]) is None):
            return setup_error
        if setup["registration"] != {
            "outcome": "SUCCEEDED", "readback": "VERIFIED", "phone_bound": False,
            "actual_committed_row_mutations": None,
            "count_basis": "SOURCE_BOUNDED_NOT_OBSERVED",
            "direct_row_mutations_upper_bound": 4,
        }:
            return setup_error
        gift = setup["credit_gift"]
        if not isinstance(gift, dict) or not _keys_exact(gift, {
            "outcome", "readback", "amount", "type", "paid_rmb",
            "balance_after", "total_purchased_after", "ledger_match_count",
            "transaction_identity_sha256", "replayed", "actual_committed_row_mutations",
            "count_basis", "direct_row_mutations_upper_bound",
        }):
            return setup_error
        if (gift["outcome"] != "SUCCEEDED" or gift["readback"] != "VERIFIED"
                or not _exact_int(gift["amount"], 900) or gift["type"] != "gift"
                or not _exact_int(gift["paid_rmb"], 0)
                or not _exact_int(gift["balance_after"], 900)
                or not _exact_int(gift["total_purchased_after"], 0)
                or not _exact_int(gift["ledger_match_count"], 1)
                or gift["replayed"] is not False
                or gift["actual_committed_row_mutations"] is not None
                or gift["count_basis"] != "SOURCE_BOUNDED_NOT_OBSERVED"
                or not _exact_int(gift["direct_row_mutations_upper_bound"], 3)
                or not isinstance(gift["transaction_identity_sha256"], str)
                or SHA256.fullmatch(gift["transaction_identity_sha256"]) is None):
            return setup_error
    if (
        value["authorization_checkpoint"] != expected_checkpoint
        or value["authorization_plan_sha256"] != expected_plan
        or value["execution_record_ref"] != ".codex/handoffs/current-task.md"
        or value["unexpected_effects"] != []
        or value["policy_ddl"] != expected_policy
    ):
        return error
    authentication = value["authentication"]
    if not isinstance(authentication, list):
        return error
    # login: auth_login_limits INSERT/DELETE, users.last_login UPDATE,
    # user_sessions INSERT; rejected login may update only its limiter keys.
    bounds = {
        ("existing_user_password_login", "SUCCEEDED"): 6,
        ("existing_user_password_login", "FAILED"): 4,
        ("existing_user_password_login", "UNKNOWN"): 6,
        ("expired_token_cleanup", "SUCCEEDED"): 1,
        ("expired_token_cleanup", "UNKNOWN"): 1,
        ("valid_session_check", "SUCCEEDED"): 0,
    }
    for action in authentication:
        if not isinstance(action, dict) or not _keys_exact(action, {
            "action", "outcome", "actual_committed_row_mutations",
            "count_basis", "direct_row_mutations_upper_bound",
        }):
            return error
        bound = bounds.get((str(action["action"]), str(action["outcome"])))
        if bound is None or not _exact_int(action["direct_row_mutations_upper_bound"], bound):
            return error
        # There is no approved production auth DML collector in this job.
        # A response (including a lost response) cannot prove affected-row count.
        if (action["count_basis"] != "SOURCE_BOUNDED_NOT_OBSERVED"
                or action["actual_committed_row_mutations"] is not None):
            return error
    grants = value["temporary_attempts_select"]
    if not isinstance(grants, list) or len(grants) != 2:
        return error
    stages = []
    for grant in grants:
        if not isinstance(grant, dict) or not _keys_exact(grant, {
            "stage", "grant_added", "original_acl_restored",
            "original_acl_sha256", "restored_acl_sha256",
        }):
            return error
        stages.append(grant["stage"])
        acl = grant["original_acl_sha256"]
        if (
            type(grant["grant_added"]) is not bool
            or grant["original_acl_restored"] is not True
            or not isinstance(acl, str) or SHA256.fullmatch(acl) is None
            or grant["restored_acl_sha256"] != acl
        ):
            return error
    if sorted(str(stage) for stage in stages) != ["24h", "3d"]:
        return error
    # Safety writes remain saved on failure but cannot turn it into acceptance.
    safety = value["safety_flag"]
    if (
        not isinstance(safety, dict)
        or not _keys_exact(safety, {"key", "outcome", "actual_committed_row_mutations"})
        or safety["key"] != "xhs_collection_safety"
        or safety["outcome"] != "NOT_NEEDED"
        or not _exact_int(safety["actual_committed_row_mutations"], 0)
    ):
        return error
    return []


def validate_item34_tracking_evidence(
    control: dict[str, Any],
    *,
    root: Path = ROOT,
    now: datetime | None = None,
) -> list[str]:
    """Validate the owner-approved real 24h/3d Tracking acceptance."""

    errors: list[str] = []
    refs = {
        item.get("ref")
        for item in control.get("evidence", [])
        if isinstance(item, dict) and item.get("kind") == "path"
    }
    if ITEM34_TRACKING_EVIDENCE not in refs:
        return ["canonical tracking evidence ref missing"]
    path = root / ITEM34_TRACKING_EVIDENCE
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except (OSError, json.JSONDecodeError, ValueError):
        return ["canonical tracking evidence is unreadable"]

    # Explicitly selecting a prospective generation does not rewrite the sealed
    # legacy object. Default manifest accounting still evaluates the old branch.
    canonical_anchor = ITEM34_OBSERVATION_STARTED_AT
    generation = control.get("observation_generation", 0)
    if type(generation) is not int or generation not in {0, 1, 2}:
        return ["tracking observation generation invalid"]
    if generation in {1,2}:
        legacy = dict(payload)
        recovery=legacy.pop('recovery_observation',None)
        if generation==2:
            payload=recovery
            previous=legacy.get('prospective_observation')
        else:
            payload=legacy.pop("prospective_observation", None)
            previous=legacy
        if not isinstance(payload, dict):
            return ["prospective tracking evidence missing"]
        legacy_digest = hashlib.sha256(json.dumps(legacy, ensure_ascii=True,
            separators=(",", ":"), sort_keys=True).encode("ascii")).hexdigest()
        if not isinstance(previous,dict):return ['sealed failed observation history mismatch']
        legacy_observation=previous.get("observation") or {}
        legacy_writes=previous.get("actual_production_write_set") or {}
        old_attempts = legacy_observation.get("actual_provider_attempts") if isinstance(legacy_observation,dict) else None
        old_counts = legacy_writes.get("rows_by_table") if isinstance(legacy_writes,dict) else None
        expected_status='FAILED_24H_OLD_WINDOW_EXPIRED' if generation==1 else 'FAILED_24H_REMOTE_BUSINESS_ERROR'
        expected_digest=ITEM34_SEALED_OBSERVATION_SHA256 if generation==1 else ITEM34_SEALED_GENERATION1_SHA256
        if (previous.get("status") != expected_status
            or previous.get("readiness_credit") is not False
            or old_counts != {"schema_migrations":1,"tracked_notes":1,
                              "tracking_provider_attempts":1,"crawler_events":2,"system_settings":1}
            or not isinstance(old_attempts,list) or len(old_attempts)!=1
            or not isinstance(old_attempts[0],dict)
            or old_attempts[0].get("status")!="failed"
            or old_attempts[0].get("error_code") in {None,"provider_outcome_unknown"}
            or payload.get("previous_observation_sha256") != legacy_digest
            or legacy_digest != expected_digest):
            errors.append("sealed failed observation history mismatch")
        if not _exact_int(payload.get("observation_generation"),generation):
            errors.append("prospective tracking generation mismatch")
        binding = payload.get("observation_binding_sha256")
        if not isinstance(binding,str) or SHA256.fullmatch(binding) is None:
            errors.append("prospective tracking binding missing")
        new_observation = payload.get("observation", {})
        canonical_anchor = new_observation.get("observation_started_at") if isinstance(new_observation,dict) else None
        try:
            _require(_item34_zoned_clock(canonical_anchor,"new anchor") >
                     _item34_zoned_clock(ITEM34_OBSERVATION_STARTED_AT,"old anchor")+timedelta(hours=72),
                     "prospective observation must follow the sealed window")
        except ManifestError as exc:
            errors.append(str(exc))
        for key in ("checkpoint_24h","checkpoint_3d"):
            value=new_observation.get(key) if isinstance(new_observation,dict) else None
            if not isinstance(value,dict) or value.get("observation_binding_sha256")!=binding:
                errors.append("prospective checkpoint binding mismatch")
        from execute_item34_tracking_checkpoint import (
            observation_context, observation_identity, Item34CheckpointError,
        )
        try:
            with observation_context(payload.get("observation_binding")) as bound:
                _require(bound is not None, "prospective binding content missing")
                _require(observation_identity().get("observation_binding_sha256") == binding,
                         "prospective binding content mismatch")
                old_track = legacy_observation.get("managed_track", {})
                new_track = new_observation.get("managed_track", {})
                track_hash = hashlib.sha256(
                    f"noteai-item34-tracking-row-v1:{bound['track_id']}".encode("ascii")).hexdigest()
                _require(new_track.get("identity_sha256") == old_track.get("identity_sha256") == track_hash
                         and new_track.get("submitted_at") == old_track.get("submitted_at"),
                         "prospective observation changed original track")
                _require(_item34_zoned_clock(bound["observation_started_at"], "binding anchor") ==
                         _item34_zoned_clock(canonical_anchor, "new anchor")
                         and bound["initial_snapshot"] == new_observation.get("initial_snapshot", {}).get("metrics"),
                         "prospective initial observation binding mismatch")
                previous_hash = hashlib.sha256(
                    f"noteai-item34-tracking-attempt-row-v1:{bound['previous_attempt_id']}".encode("ascii")).hexdigest()
                _require(previous_hash == old_attempts[0].get("identity_sha256"),
                         "prospective previous attempt binding mismatch")
                _require(bound['generation']==generation,'prospective binding generation mismatch')
                if generation==2:
                    prior_binding=previous['observation_binding']
                    _require(bound['track_id']==prior_binding['track_id'] and bound['owner_id']==prior_binding['owner_id'],
                             'recovery changed original owner or track')
                    root_attempts=legacy.get('observation',{}).get('actual_provider_attempts',[])
                    _require(len(root_attempts)==1,'sealed root attempt missing')
                    for entry,old in zip(bound['sealed_attempts'],[root_attempts[0],old_attempts[0]]):
                        identity=hashlib.sha256(f"noteai-item34-tracking-attempt-row-v1:{entry['attempt_id']}".encode('ascii')).hexdigest()
                        _require(identity==old.get('identity_sha256'),'sealed attempt identity mismatch')
                    _require(bound['sealed_attempts'][0]['sha256']==previous.get('observation_binding',{}).get('previous_attempt_sha256'),
                             'sealed root attempt projection mismatch')
                    readback=previous['production_execution_20260910']['owner_readback']['final_readback']
                    old_row={key:readback[key] for key in ('run_id','stage','admitted_at','completed_at','error_code')}
                    old_row.update(id=readback['attempt_id'],status=readback['attempt_status'],
                        observation_generation=int(readback['attempt_generation']),
                        track_id=prior_binding['track_id'],user_id=prior_binding['owner_id'])
                    from tracking_contract import observation_history_digest
                    _require(old_row['observation_generation']==1 and old_row['status']=='failed'
                             and old_row['id']==bound['previous_attempt_id']
                             and observation_history_digest(old_row)==bound['previous_attempt_sha256'],
                             'sealed generation1 attempt projection mismatch')
                    _require(_item34_zoned_clock(bound['observation_started_at'],'new anchor')>
                             _item34_zoned_clock(old_attempts[0].get('completed_at'),'prior completion'),
                             'recovery anchor must follow failed generation')
                _require(all(_exact_int(a.get("observation_generation"), generation)
                             and a.get("observation_binding_sha256") == binding
                             for a in new_observation.get("actual_provider_attempts", [])),
                         "prospective attempt generation binding mismatch")
        except (Item34CheckpointError, ManifestError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
            errors.append(str(exc) if isinstance(exc, ManifestError) else "prospective binding invalid")
        old_ids={a.get('identity_sha256') for a in old_attempts or [] if isinstance(a,dict)} if isinstance(old_attempts,list) else set()
        if generation==2:
            old_ids.update(a.get('identity_sha256') for a in legacy.get('observation',{}).get('actual_provider_attempts',[]) if isinstance(a,dict))
        new_attempts=new_observation.get('actual_provider_attempts') if isinstance(new_observation,dict) else None
        if isinstance(new_attempts,list) and any(isinstance(a,dict) and a.get('identity_sha256') in old_ids for a in new_attempts):
            errors.append('old provider attempt reused by prospective observation')
        migration=payload.get("generation_migration",{})
        migration_path="model/migrations/postgres/0020_tracking_observation_generation.sql"
        migration_digest=_actual_file_sha256(migration_path,root=root)
        if (not isinstance(migration,dict) or migration.get("path")!=migration_path
            or migration.get("version")!="0020_tracking_observation_generation.sql"
            or not isinstance(migration_digest,str) or SHA256.fullmatch(migration_digest) is None
            or migration_digest!='22ef0a2c21529fe4d8ed38c42c2283ae61e6e6822d6411bd07620d353042d7a9'
            or migration.get("sha256")!=migration_digest
            or migration.get("ledger_source_sha256")!=migration_digest
            or not _exact_int(migration.get("ledger_exact_count"),1)
            or not _exact_int(migration.get("schema_migrations_insert_count"),1 if generation==1 else 0)
            or migration.get("production_status")!="VERIFIED"
            or migration.get("ledger_readback")!="VERIFIED"):
            errors.append("prospective migration verification missing")
        combined=payload.get("combined_production_write_set",{})
        counts={"schema_migrations":2,"tracked_notes":1,"tracking_provider_attempts":generation+2,
                "crawler_events":2*(generation+1),"system_settings":1,"growth_records":1,"user_memories":1}
        if (not isinstance(combined,dict) or combined.get("rows_by_table")!=counts
            or any(not _exact_int(combined['rows_by_table'].get(k),v) for k,v in counts.items())
            or not _exact_int(combined.get("distinct_rows"),13 if generation==1 else 16)
            or not _exact_int(combined.get("provider_admissions"),generation+2)
            or combined.get("ledger_readback")!="VERIFIED"):
            errors.append("combined observation history accounting invalid")

    if payload.get("schema") != "noteai.item34.tracking_observation.v1":
        errors.append("tracking evidence schema mismatch")
    if _has_sensitive_evidence_key(payload):
        errors.append("tracking evidence contains sensitive credential-shaped field")
    if (
        not _exact_int(payload.get("item"), 34)
        or payload.get("status") != "VERIFIED"
    ):
        errors.append("tracking terminal status mismatch")
    if payload.get("readiness_credit") is not True:
        errors.append("tracking readiness credit mismatch")

    preparation = payload.get("production_preparation_20260907")
    migration = (
        preparation.get("runtime_config_migration")
        if isinstance(preparation, dict)
        else None
    )
    if not isinstance(migration, dict):
        errors.append("runtime config migration evidence missing")
    else:
        migration_readback = {
            "version": migration.get("version"),
            "ledger_source_sha256": migration.get("ledger_source_sha256"),
            "ledger_exact_count": migration.get("ledger_exact_count"),
            "search_path_binding": migration.get("search_path_binding"),
            "rls_contract_exact": migration.get("rls_contract_exact"),
            "policy_name": migration.get("policy_name"),
            "production_policy_count": migration.get("production_policy_count"),
            "policy_contract_count": migration.get("policy_contract_count"),
            "policy_qual_readback": migration.get("policy_qual_readback"),
            "policy_qual_readback_sha256": migration.get(
                "policy_qual_readback_sha256"
            ),
            "schema_migrations_insert_count": migration.get(
                "schema_migrations_insert_count"
            ),
            "business_row_mutations": migration.get("business_row_mutations"),
        }
        policy_qual_readback = migration.get("policy_qual_readback")
        actual_policy_qual_sha256 = (
            hashlib.sha256(policy_qual_readback.encode("utf-8")).hexdigest()
            if isinstance(policy_qual_readback, str)
            else None
        )
        expected_migration_readback_sha256 = hashlib.sha256(
            json.dumps(
                migration_readback,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
        ).hexdigest()
        if (
            migration.get("path") != ITEM34_RUNTIME_CONFIG_MIGRATION
            or migration.get("sha256") != ITEM34_RUNTIME_CONFIG_MIGRATION_SHA256
            or _actual_file_sha256(ITEM34_RUNTIME_CONFIG_MIGRATION, root=root)
            != ITEM34_RUNTIME_CONFIG_MIGRATION_SHA256
            or migration.get("version")
            != "0019_xhs_tracking_runtime_config.sql"
            or migration.get("ledger_source_sha256")
            != ITEM34_RUNTIME_CONFIG_MIGRATION_SHA256
            or not _exact_int(migration.get("ledger_exact_count"), 1)
            or migration.get("search_path_binding") is not True
            or migration.get("rls_contract_exact") is not True
            or migration.get("policy_name") != ITEM34_RUNTIME_CONFIG_POLICY
            or not _exact_int(migration.get("production_policy_count"), 1)
            or not _exact_int(migration.get("policy_contract_count"), 1)
            or policy_qual_readback != ITEM34_RUNTIME_CONFIG_POLICY_QUAL
            or actual_policy_qual_sha256
            != ITEM34_RUNTIME_CONFIG_POLICY_QUAL_SHA256
            or migration.get("policy_qual_readback_sha256")
            != ITEM34_RUNTIME_CONFIG_POLICY_QUAL_SHA256
            or migration.get("production_status") != "VERIFIED"
            or not _exact_int(migration.get("schema_migrations_insert_count"), 0 if generation else 1)
            or not _exact_int(migration.get("business_row_mutations"), 0)
            or migration.get("ledger_readback") != "VERIFIED"
            or migration.get("ledger_readback_sha256")
            != expected_migration_readback_sha256
        ):
            errors.append("runtime config migration verification invalid")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    observation = payload.get("observation")
    if not isinstance(observation, dict):
        return [*errors, "tracking observation missing"]
    note_id = observation.get("note_id")
    if note_id != ITEM34_CANONICAL_NOTE_ID:
        errors.append("canonical XHS note identity mismatch")
    if not isinstance(note_id, str) or re.fullmatch(r"[0-9a-f]{24}", note_id) is None:
        errors.append("canonical XHS note id missing")
    else:
        expected_url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if observation.get("canonical_url") != expected_url:
            errors.append("canonical XHS URL mismatch")
        expected_hash = hashlib.sha256(
            f"noteai-item34-xhs-note-v1:{note_id}".encode("ascii")
        ).hexdigest()
        if observation.get("object_identity_sha256") != expected_hash:
            errors.append("tracking object identity hash mismatch")

    started: datetime | None = None
    observed_24h: datetime | None = None
    observed_3d: datetime | None = None
    finalized: datetime | None = None
    checkpoint_24h: dict[str, Any] | None = None
    checkpoint_3d: dict[str, Any] | None = None
    object_identity = observation.get("object_identity_sha256")
    try:
        started = _item34_zoned_clock(
            observation.get("observation_started_at"),
            "observation_started_at",
        )
        canonical_started = _item34_zoned_clock(
            canonical_anchor,
            "canonical_observation_started_at",
        )
        _require(
            started == canonical_started,
            "tracking_real_and_promotion: canonical observation anchor mismatch",
        )
        checkpoint_24h = observation.get("checkpoint_24h")
        checkpoint_3d = observation.get("checkpoint_3d")
        _require(isinstance(checkpoint_24h, dict), "tracking_real_and_promotion: checkpoint_24h missing")
        _require(isinstance(checkpoint_3d, dict), "tracking_real_and_promotion: checkpoint_3d missing")
        observed_24h = _item34_zoned_clock(
            checkpoint_24h.get("observed_at"), "checkpoint_24h.observed_at"
        )
        observed_3d = _item34_zoned_clock(
            checkpoint_3d.get("observed_at"), "checkpoint_3d.observed_at"
        )
        finalized = _item34_zoned_clock(
            payload.get("terminal_finalized_at"), "terminal_finalized_at"
        )
        initial = observation.get("initial_snapshot")
        _require(
            isinstance(initial, dict),
            "tracking_real_and_promotion: initial_snapshot missing",
        )
        initial_at = _item34_zoned_clock(
            initial.get("observed_at"), "initial_snapshot.observed_at"
        )
        _require(
            initial_at == started,
            "tracking_real_and_promotion: initial snapshot/start mismatch",
        )
        _require(
            initial.get("object_identity_sha256") == object_identity,
            "tracking_real_and_promotion: initial object binding mismatch",
        )
        for name, clock in (
            ("observation_started_at", started),
            ("checkpoint_24h.observed_at", observed_24h),
            ("checkpoint_3d.observed_at", observed_3d),
            ("terminal_finalized_at", finalized),
        ):
            _require(
                clock <= current,
                f"tracking_real_and_promotion: future {name} prohibited",
            )
        _require(
            observed_24h >= started + timedelta(hours=24),
            "tracking_real_and_promotion: 24h checkpoint credited early",
        )
        _require(
            observed_24h < started + timedelta(hours=72),
            "tracking_real_and_promotion: 24h checkpoint window closed",
        )
        _require(
            observed_3d >= started + timedelta(hours=72),
            "tracking_real_and_promotion: 3d checkpoint credited early",
        )
        _require(
            observed_24h < observed_3d,
            "tracking_real_and_promotion: checkpoint order invalid",
        )
        _require(
            finalized >= observed_3d,
            "tracking_real_and_promotion: terminal finalized before 3d",
        )
        for name, checkpoint in (
            ("initial_snapshot", initial),
            ("checkpoint_24h", checkpoint_24h),
            ("checkpoint_3d", checkpoint_3d),
        ):
            metrics = checkpoint.get("metrics")
            _require(isinstance(metrics, dict), f"tracking_real_and_promotion: {name} metrics missing")
            _require(
                all(
                    isinstance(metrics.get(key), int)
                    and not isinstance(metrics.get(key), bool)
                    and metrics[key] >= 0
                    for key in ("likes", "saves", "comments")
                ),
                f"tracking_real_and_promotion: {name} metrics invalid",
            )
    except ManifestError as exc:
        errors.append(str(exc).split(": ", 1)[-1])

    managed_track = observation.get("managed_track")
    managed_track_identity: str | None = None
    if not isinstance(managed_track, dict):
        errors.append("managed tracking row evidence missing")
    else:
        managed_track_identity = managed_track.get("identity_sha256")
        if not isinstance(managed_track_identity, str) or SHA256.fullmatch(
            managed_track_identity
        ) is None:
            errors.append("managed tracking identity invalid")
        if managed_track.get("object_identity_sha256") != object_identity:
            errors.append("managed tracking object binding mismatch")
        try:
            managed_submitted_at = _item34_zoned_clock(
                managed_track.get("submitted_at"), "managed_track.submitted_at"
            )
            if managed_submitted_at > current:
                errors.append("future managed tracking start prohibited")
        except ManifestError as exc:
            errors.append(str(exc).split(": ", 1)[-1])
        if managed_track.get("ledger_readback") != "VERIFIED":
            errors.append("managed tracking ledger readback missing")
        readback_sha = managed_track.get("ledger_readback_sha256")
        if not isinstance(readback_sha, str) or SHA256.fullmatch(readback_sha) is None:
            errors.append("managed tracking ledger digest invalid")

    attempts = observation.get("actual_provider_attempts")
    attempt_by_stage: dict[str, dict[str, Any]] = {}
    if not isinstance(attempts, list) or len(attempts) != 2:
        errors.append("exact two provider attempts required")
    else:
        stages = {
            item.get("canonical_stage")
            for item in attempts
            if isinstance(item, dict)
        }
        if stages != {"24h", "3d"}:
            errors.append("24h and 3d provider attempts required")
        expected_persisted_stage = {"24h": "24h", "3d": "7d"}
        for item in attempts:
            if not isinstance(item, dict):
                errors.append("provider attempt evidence invalid")
                continue
            stage = item.get("canonical_stage")
            identity = item.get("identity_sha256")
            run_identity = item.get("run_identity_sha256")
            if (
                stage not in expected_persisted_stage
                or item.get("persisted_stage")
                != expected_persisted_stage.get(stage)
                or item.get("status") != "succeeded"
                or item.get("ledger_readback") != "VERIFIED"
                or item.get("actual_supplier_call") is not True
                or not _exact_int(item.get("call_count"), 1)
                or item.get("worker_mode") != "once"
                or not _exact_int(item.get("round_limit"), 1)
                or not _exact_int(item.get("run_provider_calls"), 1)
                or not _exact_int(item.get("automatic_retry_count"), 0)
                or not _exact_int(item.get("due_candidate_count_before"), 1)
                or item.get("due_target_match") is not True
                or item.get("force_used") is not False
                or not _exact_int(item.get("other_row_mutations"), 0)
                or not _exact_int(item.get("outcome_unknown_count_before"), 0)
                or not _exact_int(item.get("outcome_unknown_count_after"), 0)
                or item.get("runtime_quiescent_before") is not True
                or item.get("runtime_quiescent_after") is not True
                or not _exact_int(item.get("crawler_events_inserted"), 1)
                or type(item.get("configuration_transition_used")) is not bool
                or not _exact_int(
                    item.get("configuration_row_mutations"),
                    2 if item.get("configuration_transition_used") else 0,
                )
                or item.get("configuration_restored") is not True
                or not isinstance(identity, str)
                or SHA256.fullmatch(identity) is None
                or not isinstance(run_identity, str)
                or SHA256.fullmatch(run_identity) is None
                or item.get("object_identity_sha256") != object_identity
                or item.get("managed_track_identity_sha256")
                != managed_track_identity
            ):
                errors.append("provider attempt evidence invalid")
                continue
            try:
                admitted_at = _item34_zoned_clock(
                    item.get("admitted_at"), f"{stage}.admitted_at"
                )
                completed_at = _item34_zoned_clock(
                    item.get("completed_at"), f"{stage}.completed_at"
                )
                floor = timedelta(hours=24 if stage == "24h" else 72)
                _require(
                    started is not None,
                    "tracking_real_and_promotion: observation anchor missing",
                )
                _require(
                    admitted_at >= started + floor,
                    f"tracking_real_and_promotion: {stage} attempt admitted early",
                )
                _require(
                    admitted_at <= completed_at <= current,
                    f"tracking_real_and_promotion: {stage} attempt clock invalid",
                )
            except ManifestError as exc:
                errors.append(str(exc).split(": ", 1)[-1])
                continue
            if stage == "24h":
                if not _exact_int(item.get("premature_7d_attempt_count"), 0):
                    errors.append("premature 7d provider attempt detected")
                    continue
                try:
                    post_next_check_at = _item34_zoned_clock(
                        item.get("post_next_check_at"),
                        "24h.post_next_check_at",
                    )
                    _require(
                        started is not None
                        and post_next_check_at == started + timedelta(hours=72),
                        "tracking_real_and_promotion: 24h next-check schedule mismatch",
                    )
                except ManifestError as exc:
                    errors.append(str(exc).split(": ", 1)[-1])
                    continue
            else:
                memory_content_sha256 = item.get("memory_content_sha256")
                if (
                    item.get("training_eligible") is not False
                    or item.get("score_window") != "3d"
                    or item.get("growth_action") != "url_crawl_3d"
                    or item.get("memory_window") != "3d"
                    or not isinstance(memory_content_sha256, str)
                    or SHA256.fullmatch(memory_content_sha256) is None
                ):
                    errors.append("3d terminal semantics invalid")
                    continue
            attempt_by_stage[stage] = item
        identities = {
            item.get("identity_sha256")
            for item in attempts
            if isinstance(item, dict)
        }
        run_identities = {
            item.get("run_identity_sha256")
            for item in attempts
            if isinstance(item, dict)
        }
        if len(identities) != 2 or len(run_identities) != 2:
            errors.append("provider attempt identities must be unique")

    if checkpoint_24h is not None and checkpoint_3d is not None:
        for stage, checkpoint, observed in (
            ("24h", checkpoint_24h, observed_24h),
            ("3d", checkpoint_3d, observed_3d),
        ):
            attempt = attempt_by_stage.get(stage)
            if (
                checkpoint.get("object_identity_sha256") != object_identity
                or checkpoint.get("managed_track_identity_sha256")
                != managed_track_identity
                or attempt is None
                or checkpoint.get("attempt_identity_sha256")
                != attempt.get("identity_sha256")
            ):
                errors.append(f"{stage} checkpoint identity binding mismatch")
            elif observed is not None:
                try:
                    completed = _item34_zoned_clock(
                        attempt.get("completed_at"), f"{stage}.completed_at"
                    )
                    if observed < completed:
                        errors.append(f"{stage} checkpoint precedes attempt completion")
                except ManifestError:
                    pass

    if observation.get("manual_fill_used") is not False:
        errors.append("manual fill cannot prove real observation")
    if observation.get("backfill_used") is not False:
        errors.append("backfill cannot prove real observation")
    if observation.get("early_credit") is not False:
        errors.append("early credit must be false")
    interruptions = observation.get("interruptions")
    if observation.get("continuity_break_count") != 0:
        errors.append("continuous three-day observation required")
    if not isinstance(interruptions, list):
        errors.append("interruptions ledger required")
    elif interruptions:
        errors.append("continuous three-day observation has interruptions")

    if payload.get("managed_tracking_row_started") is not True:
        errors.append("managed tracking row was not started")
    if payload.get("provider_calls") != 2:
        errors.append("exact two provider calls required")

    promotion = payload.get("managed_promotion")
    if not isinstance(promotion, dict):
        errors.append("managed promotion evidence missing")
    else:
        if promotion.get("status") != "VERIFIED":
            errors.append("managed promotion status mismatch")
        if promotion.get("singleton_winner_count") != 1:
            errors.append("managed singleton evidence missing")
        if promotion.get("rollback_rehearsal") != "PASS":
            errors.append("managed rollback evidence missing")
        for field in (
            "resource_controls",
            "restart_controls",
            "log_controls",
            "alert_controls",
            "health_check",
        ):
            if promotion.get(field) != "PASS":
                errors.append(f"managed promotion {field} missing")
        for field in (
            "execution_identity_sha256",
            "immutable_artifact_sha256",
            "managed_service_identity_sha256",
        ):
            value = promotion.get(field)
            if not isinstance(value, str) or SHA256.fullmatch(value) is None:
                errors.append(f"managed promotion {field} invalid")
        bounded_attempt = promotion.get(
            "bounded_validation_attempt_identity_sha256"
        )
        attempt_identities = {
            item.get("identity_sha256")
            for item in attempts or []
            if isinstance(item, dict)
        }
        if bounded_attempt not in attempt_identities:
            errors.append("managed promotion supplier validation not bound")

    writes = payload.get("actual_production_write_set")
    required_tables = {
        "schema_migrations",
        "tracked_notes",
        "tracking_provider_attempts",
        "growth_records",
        "user_memories",
        "crawler_events",
        "system_settings",
    }
    if generation==2:required_tables.remove('schema_migrations')
    if not isinstance(writes, dict) or not isinstance(writes.get("tables"), list):
        errors.append("actual production write set missing")
    else:
        if not _keys_exact(
            writes,
            {
                "tables",
                "rows_by_table",
                "row_mutations",
                "out_of_contract_row_mutations",
                "ledger_readback",
                "ledger_readback_sha256",
            },
        ):
            errors.append("actual production write set fields invalid")
        table_values = writes["tables"]
        tables_are_strings = all(
            isinstance(table, str) for table in table_values
        )
        tables = set(table_values) if tables_are_strings else set()
        if (
            not tables_are_strings
            or len(table_values) != len(tables)
            or tables != required_tables
        ):
            errors.append("production write set exceeds Tracking contract")
        if tables != required_tables:
            errors.append("terminal Tracking write set incomplete")
        row_counts = writes.get("rows_by_table")
        expected_row_counts = {
            "schema_migrations": 1,
            "tracked_notes": 1,
            "tracking_provider_attempts": 2,
            "growth_records": 1,
            "user_memories": 1,
            "crawler_events": 2,
            "system_settings": 1,
        }
        if generation==2:expected_row_counts.pop('schema_migrations')
        if (
            not isinstance(row_counts, dict)
            or set(row_counts) != required_tables
            or any(
                not _exact_int(row_counts.get(table), expected)
                for table, expected in expected_row_counts.items()
            )
        ):
            errors.append("terminal Tracking row counts invalid")
        if not _exact_int(writes.get("row_mutations"), 8 if generation==2 else 9):
            errors.append("terminal Tracking mutation count invalid")
        if not _exact_int(writes.get("out_of_contract_row_mutations"), 0):
            errors.append("out-of-contract production writes detected")
        if writes.get("ledger_readback") != "VERIFIED":
            errors.append("production write ledger readback missing")
        write_readback = {
            "tables": sorted(table_values) if tables_are_strings else table_values,
            "rows_by_table": row_counts,
            "row_mutations": writes.get("row_mutations"),
            "out_of_contract_row_mutations": writes.get(
                "out_of_contract_row_mutations"
            ),
        }
        if "authorized_auxiliary_effects" in payload:
            auxiliary = payload["authorized_auxiliary_effects"]
            errors.extend(_validate_item34_auxiliary_effects(auxiliary, generation=generation,
                authorization=control.get("observation_authorization")))
            # Keep the original digest algorithm for historical evidence.
            write_readback["authorized_auxiliary_effects"] = auxiliary
        if generation and "authorized_auxiliary_effects" not in payload:
            errors.append("prospective authorized auxiliary effects missing")
        expected_write_digest = hashlib.sha256(
            json.dumps(
                write_readback,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
        ).hexdigest()
        write_digest = writes.get("ledger_readback_sha256")
        if write_digest != expected_write_digest:
            errors.append("production write ledger digest invalid")
    if payload.get("secret_values_recorded") is not False:
        errors.append("secret-value exclusion missing")
    return errors


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot load readiness manifest: {exc}") from exc
    _require(isinstance(payload, dict), "manifest root must be an object")
    return payload


def validate_manifest(manifest: dict[str, Any], *, root: Path = ROOT) -> None:
    _require(manifest.get("schema_version") == 1, "unsupported schema_version")
    _require(
        manifest.get("task_id") == "PROD-COMPLETE-FIRST-LAUNCH-001",
        "unexpected umbrella task",
    )
    _require(
        set(manifest.get("status_values") or []) == VALID_STATUSES,
        "status_values must match the fail-closed status vocabulary",
    )
    layers = manifest.get("layers")
    _require(isinstance(layers, list), "layers must be a list")
    layer_ids = tuple(layer.get("id") for layer in layers if isinstance(layer, dict))
    _require(layer_ids == EXPECTED_LAYERS, "readiness layers are missing or out of order")

    controls_by_id: dict[str, dict[str, Any]] = {}
    for layer in layers:
        _require(
            layer.get("default_execution_class") in VALID_EXECUTION_CLASSES,
            f"{layer.get('id')}: invalid default_execution_class",
        )
        controls = layer.get("controls")
        _require(isinstance(controls, list) and controls, f"{layer.get('id')}: controls required")
        _require(
            tuple(
                control.get("id")
                for control in controls
                if isinstance(control, dict)
            )
            == EXPECTED_CONTROL_IDS[layer["id"]],
            f"{layer.get('id')}: exact control ids and order required",
        )
        for control in controls:
            _require(isinstance(control, dict), "control must be an object")
            control_id = control.get("id")
            _require(
                isinstance(control_id, str) and control_id and control_id not in controls_by_id,
                f"duplicate or invalid control id: {control_id}",
            )
            _require(
                isinstance(control.get("title"), str) and control["title"].strip(),
                f"{control_id}: title required",
            )
            status = control.get("status")
            _require(status in VALID_STATUSES, f"{control_id}: invalid status {status}")
            _require(
                control.get("execution_class", layer["default_execution_class"])
                in VALID_EXECUTION_CLASSES,
                f"{control_id}: invalid execution_class",
            )
            dependencies = control.get("dependencies")
            _require(isinstance(dependencies, list), f"{control_id}: dependencies must be a list")
            _require(
                all(isinstance(item, str) and item for item in dependencies),
                f"{control_id}: invalid dependency",
            )
            if control_id in EXPECTED_CONTROL_DEPENDENCIES:
                _require(
                    dependencies
                    == EXPECTED_CONTROL_DEPENDENCIES[control_id],
                    f"{control_id}: canonical dependencies changed",
                )
            evidence = control.get("evidence")
            _require(isinstance(evidence, list), f"{control_id}: evidence must be a list")
            if status == "verified":
                _require(evidence, f"{control_id}: verified without evidence")
                _require(not control.get("blocker"), f"{control_id}: verified with blocker")
            else:
                _require(
                    isinstance(control.get("blocker"), str) and control["blocker"].strip(),
                    f"{control_id}: non-verified control requires blocker",
                )
                _require(
                    isinstance(control.get("next_task"), str) and control["next_task"].strip(),
                    f"{control_id}: non-verified control requires next_task",
                )
            if status == "blocked":
                _require(
                    isinstance(control.get("resume_condition"), str)
                    and control["resume_condition"].strip(),
                    f"{control_id}: blocked control requires resume_condition",
                )
            for item in evidence:
                _require(isinstance(item, dict), f"{control_id}: invalid evidence entry")
                kind = item.get("kind")
                ref = item.get("ref")
                _require(kind in VALID_EVIDENCE_KINDS, f"{control_id}: invalid evidence kind")
                _require(isinstance(ref, str) and ref, f"{control_id}: evidence ref required")
                if kind == "git":
                    _require(_verify_git_ref(ref, root=root), f"{control_id}: missing git evidence {ref}")
                else:
                    _require(_verify_path(ref, root=root), f"{control_id}: missing path evidence {ref}")
            if control_id == "api_c_current_release" and status == "verified":
                _require(
                    evidence == API_C_EXPECTED_MANIFEST_EVIDENCE,
                    f"{control_id}: exact runtime evidence refs required",
                )
                runtime_errors = validate_api_c_current_release_evidence(
                    root=root
                )
                _require(
                    not runtime_errors,
                    f"{control_id}: invalid runtime evidence: "
                    f"{runtime_errors[0] if runtime_errors else ''}",
                )
            if control_id == "api_f_current_release" and status == "verified":
                _require(
                    evidence == API_F_EXPECTED_MANIFEST_EVIDENCE,
                    f"{control_id}: exact runtime evidence refs required",
                )
                runtime_errors = validate_api_f_current_release_evidence(
                    root=root
                )
                _require(
                    not runtime_errors,
                    f"{control_id}: invalid runtime evidence: "
                    f"{runtime_errors[0] if runtime_errors else ''}",
                )
            if control_id == "admin_current_release" and status == "verified":
                required_refs = {
                    (
                        "git",
                        "5335bdaed933b1f999b5f819c047ec50c11821ae",
                    ),
                    (
                        "path",
                        "deploy/production/evidence/"
                        "production-admin-current-release-verified-20260805.json",
                    ),
                    (
                        "path",
                        "tools/verify_admin_current_release_evidence.py",
                    ),
                }
                actual_refs = {
                    (item.get("kind"), item.get("ref")) for item in evidence
                }
                _require(
                    required_refs.issubset(actual_refs),
                    f"{control_id}: final runtime evidence refs required",
                )
                runtime_errors = validate_admin_current_release_evidence(
                    root=root
                )
                _require(
                    not runtime_errors,
                    f"{control_id}: invalid runtime evidence: "
                    f"{runtime_errors[0] if runtime_errors else ''}",
                )
            if control_id == "real_xhs_trends" and status == "verified":
                trends_errors = validate_item32_trends_evidence(
                    control,
                    root=root,
                )
                _require(
                    not trends_errors,
                    f"{control_id}: invalid semantic evidence: "
                    f"{trends_errors[0] if trends_errors else ''}",
                )
            if (
                control_id == "trends_managed_promotion"
                and status == "verified"
            ):
                promotion_errors = validate_item33_trends_promotion_evidence(
                    control,
                    root=root,
                )
                _require(
                    not promotion_errors,
                    f"{control_id}: invalid semantic evidence: "
                    f"{promotion_errors[0] if promotion_errors else ''}",
                )
            if control_id == "real_payment_chain" and status == "verified":
                payment_errors = validate_item31_payment_evidence(
                    control,
                    root=root,
                )
                _require(
                    not payment_errors,
                    f"{control_id}: invalid semantic evidence: "
                    f"{payment_errors[0] if payment_errors else ''}",
                )
            if control_id == "legal_provider_approval" and status == "verified":
                approval_errors = validate_item35_approval_evidence(
                    control,
                    root=root,
                )
                _require(
                    not approval_errors,
                    f"{control_id}: invalid semantic evidence: "
                    f"{approval_errors[0] if approval_errors else ''}",
                )
            if control_id == "alb_tls" and status == "verified":
                alb_errors = validate_item36_alb_evidence(
                    control,
                    root=root,
                )
                _require(
                    not alb_errors,
                    f"{control_id}: invalid semantic evidence: "
                    f"{alb_errors[0] if alb_errors else ''}",
                )
            if (
                control_id == "tracking_real_and_promotion"
                and status == "verified"
            ):
                tracking_errors = validate_item34_tracking_evidence(
                    control,
                    root=root,
                )
                _require(
                    not tracking_errors,
                    f"{control_id}: invalid semantic evidence: "
                    f"{tracking_errors[0] if tracking_errors else ''}",
                )
            accepted_risks = control.get("accepted_risks", [])
            _require(
                isinstance(accepted_risks, list),
                f"{control_id}: accepted_risks must be a list",
            )
            if accepted_risks:
                _require(
                    control_id == ACCEPTED_RISK_CONTROL_ID,
                    f"{control_id}: accepted_risks are not allowed",
                )
                _require(
                    len(accepted_risks) == len(
                        EXPECTED_ACCEPTED_RISK_FINDINGS
                    ),
                    f"{control_id}: exact accepted_risks required",
                )
                observed_ids = {
                    item.get("id")
                    for item in accepted_risks
                    if isinstance(item, dict)
                }
                _require(
                    observed_ids == set(EXPECTED_ACCEPTED_RISK_FINDINGS),
                    f"{control_id}: accepted_risk ids changed",
                )
                for risk in accepted_risks:
                    risk_id = risk["id"]
                    _require(
                        risk.get("status") == "accepted_risk",
                        f"{risk_id}: status must be accepted_risk",
                    )
                    _require(
                        risk.get("accepted_by") == "product_owner",
                        f"{risk_id}: product-owner acceptance required",
                    )
                    _require(
                        risk.get("environment") == "production",
                        f"{risk_id}: production environment required",
                    )
                    _require(
                        risk.get("finding")
                        == EXPECTED_ACCEPTED_RISK_FINDINGS[risk_id],
                        f"{risk_id}: finding changed",
                    )
                    _require(
                        isinstance(risk.get("decision_at_utc"), str)
                        and risk["decision_at_utc"].endswith("Z"),
                        f"{risk_id}: UTC decision timestamp required",
                    )
                    _require(
                        risk.get("owner") == "CTO",
                        f"{risk_id}: CTO owner required",
                    )
                    _require(
                        risk.get("review_due")
                        == "first_public_launch_plus_30_days",
                        f"{risk_id}: review trigger changed",
                    )
                    for field in (
                        "scope",
                        "remediation",
                        "actual_effective_privileges",
                    ):
                        _require(
                            isinstance(risk.get(field), str)
                            and risk[field].strip(),
                            f"{risk_id}: {field} required",
                        )
                    for field in (
                        "prohibited_expansion",
                        "compensating_controls",
                        "invalidates_on",
                    ):
                        _require(
                            isinstance(risk.get(field), list)
                            and risk[field]
                            and all(
                                isinstance(value, str) and value.strip()
                                for value in risk[field]
                            ),
                            f"{risk_id}: {field} required",
                        )
                    _require(
                        risk.get("readiness_credit") == 0,
                        f"{risk_id}: readiness credit must be zero",
                    )
                    _require(
                        risk.get("migration_verified") is False,
                        f"{risk_id}: migration cannot be accepted by risk",
                    )
                    _require(
                        risk.get("database_action_authorized") is False,
                        f"{risk_id}: risk cannot authorize database action",
                    )
                    _require(
                        risk.get("not_verified_fixed") is True,
                        f"{risk_id}: risk must not claim verified fixed",
                    )
                    digest = risk.get("source_evidence_sha256")
                    _require(
                        isinstance(digest, str)
                        and SHA256.fullmatch(digest) is not None,
                        f"{risk_id}: source evidence SHA-256 required",
                    )
                    risk_evidence = risk.get("evidence")
                    _require(
                        isinstance(risk_evidence, list)
                        and risk_evidence,
                        f"{risk_id}: evidence required",
                    )
                    for item in risk_evidence:
                        _require(
                            isinstance(item, dict)
                            and item.get("kind") == "path",
                            f"{risk_id}: path evidence required",
                        )
                        ref = item.get("ref")
                        _require(
                            isinstance(ref, str)
                            and _verify_path(ref, root=root),
                            f"{risk_id}: missing risk evidence {ref}",
                        )
            controls_by_id[control_id] = control

    item26 = controls_by_id.get("backup_pitr_restore") or {}
    if item26.get("status") == "verified":
        item26_errors, item26_acceptance_sha256 = (
            validate_item26_terminal_evidence(item26, root=root)
        )
        _require(
            not item26_errors
            and isinstance(item26_acceptance_sha256, str)
            and SHA256.fullmatch(item26_acceptance_sha256) is not None,
            "backup_pitr_restore: invalid semantic evidence: "
            f"{item26_errors[0] if item26_errors else ''}",
        )
        internal_controls = [
            *manifest["layers"][0]["controls"],
            *manifest["layers"][1]["controls"],
        ]
        all_controls = [
            control
            for layer in manifest["layers"]
            for control in layer["controls"]
        ]
        deferred = {
            "backup_pitr_restore",
            "internal_zero_provider_smoke",
            "internal_failure_rollback",
            "capacity_100_jobs",
        }
        internal_before = sum(
            control["status"] == "verified"
            for control in internal_controls
            if control["id"] not in deferred
        )
        public_before = sum(
            control["status"] == "verified"
            for control in internal_controls
            if control["id"] not in deferred
        )
        _require(
            internal_before == 25
            and public_before == 25
            and len(internal_controls) == 29
            and len(all_controls) == 38,
            "backup_pitr_restore: exact 25/29 predecessor state required",
        )

    smoke = controls_by_id.get("internal_zero_provider_smoke") or {}
    if smoke.get("status") == "verified":
        item26 = controls_by_id.get("backup_pitr_restore") or {}
        _require(
            item26.get("status") == "verified",
            "internal_zero_provider_smoke: Item26 terminal verification required",
        )
        item26_errors, item26_acceptance_sha256 = (
            validate_item26_terminal_evidence(item26, root=root)
        )
        _require(
            not item26_errors
            and isinstance(item26_acceptance_sha256, str)
            and SHA256.fullmatch(item26_acceptance_sha256) is not None,
            "internal_zero_provider_smoke: Item26 semantic evidence invalid: "
            f"{item26_errors[0] if item26_errors else ''}",
        )
        internal_controls = [
            *manifest["layers"][0]["controls"],
            *manifest["layers"][1]["controls"],
        ]
        all_controls = [
            control
            for layer in manifest["layers"]
            for control in layer["controls"]
        ]
        internal_before = sum(
            control["status"] == "verified"
            for control in internal_controls
            if control["id"] not in {
                "internal_zero_provider_smoke",
                "internal_failure_rollback",
                "capacity_100_jobs",
            }
        )
        public_before = sum(
            control["status"] == "verified"
            for control in internal_controls
            if control["id"] not in {
                "internal_zero_provider_smoke",
                "internal_failure_rollback",
                "capacity_100_jobs",
            }
        )
        _require(
            internal_before == 26
            and public_before == 26
            and len(internal_controls) == 29
            and len(all_controls) == 38,
            "internal_zero_provider_smoke: exact 26/29 predecessor state required",
        )
        internal_after = internal_before + 1
        public_after = public_before + 1
        expected_readiness = {
            "internal_verified_before": internal_before,
            "internal_verified_after": internal_after,
            "internal_total": len(internal_controls),
            "internal_percentage_after": (
                internal_after * 100 + len(internal_controls) // 2
            ) // len(internal_controls),
            "complete_public_verified_before": public_before,
            "complete_public_verified_after": public_after,
            "complete_public_total": len(all_controls),
            "complete_public_percentage_after": (
                public_after * 100 + len(all_controls) // 2
            ) // len(all_controls),
            "next_task": "PROD-FIRST-LAUNCH-INTERNAL-ROLLBACK-001",
            "public_launch_authorized": False,
            "real_provider_chain_verified": False,
            "full_system_failure_rollback_verified": False,
            "capacity_100_jobs_verified": False,
        }
        runtime_errors = validate_internal_zero_provider_smoke_evidence(
            smoke["evidence"],
            root=root,
            expected_item26_terminal_acceptance_sha256=(
                item26_acceptance_sha256
            ),
            expected_readiness=expected_readiness,
        )
        _require(
            not runtime_errors,
            "internal_zero_provider_smoke: invalid semantic evidence: "
            f"{runtime_errors[0] if runtime_errors else ''}",
        )

    rollback = controls_by_id.get("internal_failure_rollback") or {}
    if rollback.get("status") == "verified":
        internal_controls = [
            *manifest["layers"][0]["controls"],
            *manifest["layers"][1]["controls"],
        ]
        all_controls = [
            control
            for layer in manifest["layers"]
            for control in layer["controls"]
        ]
        internal_before = sum(
            control["status"] == "verified"
            for control in internal_controls
            if control["id"] not in {
                "internal_failure_rollback",
                "capacity_100_jobs",
            }
        )
        public_before = sum(
            control["status"] == "verified"
            for control in internal_controls
            if control["id"] not in {
                "internal_failure_rollback",
                "capacity_100_jobs",
            }
        )
        _require(
            internal_before == 27
            and public_before == 27
            and len(internal_controls) == 29
            and len(all_controls) == 38,
            "internal_failure_rollback: exact 27/29 predecessor state required",
        )
        expected_readiness = {
            "internal_verified_before": 27,
            "internal_verified_after": 28,
            "internal_total": 29,
            "internal_percentage_after": 97,
            "complete_public_verified_before": 27,
            "complete_public_verified_after": 28,
            "complete_public_total": 38,
            "complete_public_percentage_after": 74,
            "next_task": "PROD-FIRST-LAUNCH-CAPACITY-100-001",
            "public_launch_authorized": False,
            "real_provider_chain_verified": False,
            "capacity_100_jobs_verified": False,
        }
        runtime_errors = validate_internal_failure_rollback_evidence(
            rollback["evidence"],
            root=root,
            expected_readiness=expected_readiness,
        )
        _require(
            not runtime_errors,
            "internal_failure_rollback: invalid semantic evidence: "
            f"{runtime_errors[0] if runtime_errors else ''}",
        )

    capacity = controls_by_id.get("capacity_100_jobs") or {}
    if capacity.get("status") == "verified":
        _require(
            all(
                (controls_by_id.get(dependency) or {}).get("status") == "verified"
                for dependency in capacity.get("dependencies", [])
            ),
            "capacity_100_jobs: verified dependency required",
        )
        internal_controls = [
            *manifest["layers"][0]["controls"],
            *manifest["layers"][1]["controls"],
        ]
        all_controls = [
            control
            for layer in manifest["layers"]
            for control in layer["controls"]
        ]
        internal_before = sum(
            control["status"] == "verified"
            for control in internal_controls
            if control["id"] != "capacity_100_jobs"
        )
        public_before = sum(
            control["status"] == "verified"
            for control in internal_controls
            if control["id"] != "capacity_100_jobs"
        )
        _require(
            internal_before == 28
            and public_before == 28
            and len(internal_controls) == 29
            and len(all_controls) == 38,
            "capacity_100_jobs: exact 28/29 predecessor state required",
        )
        expected_readiness = {
            "internal_verified_before": 28,
            "internal_verified_after": 29,
            "internal_total": 29,
            "internal_percentage_after": 100,
            "complete_public_verified_before": 28,
            "complete_public_verified_after": 29,
            "complete_public_total": 38,
            "complete_public_percentage_after": 76,
            "next_task": "PROD-FIRST-LAUNCH-PROVIDER-CHAIN-001",
            "public_launch_authorized": False,
            "real_provider_chain_verified": False,
            "capacity_100_jobs_verified": True,
        }
        capacity_errors = validate_capacity_100_jobs_evidence(
            capacity.get("evidence"),
            root=root,
            expected_readiness=expected_readiness,
        )
        _require(
            not capacity_errors,
            "capacity_100_jobs: invalid semantic evidence: "
            + (capacity_errors[0] if capacity_errors else ""),
        )

    provider_chain = controls_by_id.get("real_ai_provider_chain") or {}
    if provider_chain.get("status") == "verified":
        _require(
            all(
                (controls_by_id.get(dependency) or {}).get("status")
                == "verified"
                for dependency in provider_chain.get("dependencies", [])
            ),
            "real_ai_provider_chain: verified dependency required",
        )
        expected_readiness = {
            "internal_verified_before": 29,
            "internal_verified_after": 29,
            "internal_total": 29,
            "internal_percentage_after": 100,
            "complete_public_verified_before": 29,
            "complete_public_verified_after": 30,
            "complete_public_total": 38,
            "complete_public_percentage_after": 79,
            "next_task": "PROD-FIRST-LAUNCH-PAYMENT-REAL-001",
            "public_launch_authorized": False,
            "real_provider_chain_verified": True,
        }
        provider_errors = validate_real_ai_provider_chain_evidence(
            provider_chain.get("evidence"),
            root=root,
            expected_readiness=expected_readiness,
        )
        _require(
            not provider_errors,
            "real_ai_provider_chain: invalid semantic evidence: "
            + (provider_errors[0] if provider_errors else ""),
        )

    for control_id, control in controls_by_id.items():
        for dependency in control["dependencies"]:
            _require(dependency in controls_by_id, f"{control_id}: unknown dependency {dependency}")
            _require(dependency != control_id, f"{control_id}: self dependency")
            if control["status"] == "verified":
                _require(
                    controls_by_id[dependency]["status"] == "verified",
                    f"{control_id}: verified dependency required: {dependency}",
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(control_id: str) -> None:
        if control_id in visiting:
            raise ManifestError(f"dependency cycle at {control_id}")
        if control_id in visited:
            return
        visiting.add(control_id)
        for dependency in controls_by_id[control_id]["dependencies"]:
            visit(dependency)
        visiting.remove(control_id)
        visited.add(control_id)

    for control_id in controls_by_id:
        visit(control_id)


def _withdrawn(control: dict[str, Any]) -> bool:
    # The owner withdrew this professional-signature requirement, not its history.
    return control["id"] == "legal_provider_approval" and bool(control.get("withdrawn_by_owner"))


def _score(controls: list[dict[str, Any]], *, historical: bool = False) -> dict[str, Any]:
    if not historical:
        controls = [item for item in controls if not _withdrawn(item)]
    total = len(controls)
    verified = sum(item["status"] == "verified" for item in controls)
    blocked = sum(item["status"] == "blocked" for item in controls)
    percentage = (verified * 100 + total // 2) // total
    return {
        "passed": verified == total,
        "percentage": percentage,
        "verified": verified,
        "total": total,
        "blocked": blocked,
        "remaining": total - verified,
    }


def build_report(
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    validate_manifest(manifest, root=root)
    layers: dict[str, dict[str, Any]] = {}
    controls_by_id: dict[str, dict[str, Any]] = {}
    for layer in manifest["layers"]:
        controls = layer["controls"]
        layers[layer["id"]] = _score(controls)
        controls_by_id.update({item["id"]: item for item in controls})

    internal_controls = [
        *manifest["layers"][0]["controls"],
        *manifest["layers"][1]["controls"],
    ]
    all_controls = [
        item
        for layer in manifest["layers"]
        for item in layer["controls"]
    ]
    actionable = []
    layer_by_control = {
        control["id"]: layer
        for layer in manifest["layers"]
        for control in layer["controls"]
    }
    for control in all_controls:
        if control["status"] == "verified" or _withdrawn(control):
            continue
        if all(
            controls_by_id[dependency]["status"] == "verified"
            for dependency in control["dependencies"]
        ):
            actionable.append(
                {
                    "id": control["id"],
                    "status": control["status"],
                    "next_task": control["next_task"],
                    "blocker": control["blocker"],
                    "execution_class": control.get(
                        "execution_class",
                        layer_by_control[control["id"]]["default_execution_class"],
                    ),
                }
            )
    safe_actionable = [
        item for item in actionable if item["execution_class"] == "repository_offline"
    ]
    return {
        "version": "noteai-internal-deployment-readiness-v1",
        "task_id": manifest["task_id"],
        "manifest_valid": True,
        "layers": layers,
        "internal_deployment": _score(internal_controls),
        "complete_public_launch": _score(all_controls),
        "historical_complete_public_launch": _score(all_controls, historical=True),
        "withdrawn": [{"id": item["id"], "reason": item["withdrawn_by_owner"],
                       "historical_status": item["status"]}
                      for item in all_controls if _withdrawn(item)],
        "actionable": actionable,
        "next_safe_task": safe_actionable[0] if safe_actionable else None,
        "accepted_risks": [
            {
                "control_id": control["id"],
                "risk_id": risk["id"],
                "readiness_credit": risk["readiness_credit"],
                "not_verified_fixed": risk["not_verified_fixed"],
            }
            for control in all_controls
            for risk in control.get("accepted_risks", [])
        ],
        "blocked": [
            {
                "id": control["id"],
                "resume_condition": control["resume_condition"],
            }
            for control in all_controls
            if control["status"] == "blocked" and not _withdrawn(control)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute fail-closed NoteAI deployment readiness."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--require",
        choices=("manifest", "repository", "internal", "public"),
        default="manifest",
        help="Return non-zero unless the selected evidence layer is complete.",
    )
    args = parser.parse_args()
    try:
        report = build_report(args.manifest)
    except ManifestError as exc:
        print(f"internal_deployment_readiness=INVALID\nerror={exc}")
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        internal = report["internal_deployment"]
        public = report["complete_public_launch"]
        print(
            "internal_deployment_readiness="
            f"{internal['percentage']}% ({internal['verified']}/{internal['total']})"
        )
        print(
            "complete_public_launch_readiness="
            f"{public['percentage']}% ({public['verified']}/{public['total']})"
        )
        for item in report["actionable"]:
            print(f"- {item['status']}: {item['next_task']} ({item['id']})")

    required = {
        "manifest": True,
        "repository": report["layers"]["repository_isolated"]["passed"],
        "internal": report["internal_deployment"]["passed"],
        "public": report["complete_public_launch"]["passed"],
    }[args.require]
    return 0 if required else 1


if __name__ == "__main__":
    raise SystemExit(main())
