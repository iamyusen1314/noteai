#!/usr/bin/env python3
"""Source-only Item 26 M1 capture/materialization stager checkpoint.

This module's source implementation is complete but intentionally
non-operational.  It freezes the repository, runtime, transport, capture, and
public-artifact contracts while all execution gates remain false.  The
credential interface remains NOT_PROVISIONED.  A separate exact-source
acceptance checkpoint and a new action-scoped CTO operational authorization
are required before either root payload may run.

The two embedded root programs are deliberately different physical payloads.
The capture payload coordinates the already-installed collector
with the accepted FD-only Alibaba Cloud legacy RPC adapter.  The materializer
payload builds and validates the two public M1 artifacts from an
already-finalized root capture.  It must never contain a provider transport,
OAuth, or network path.  This source-only checkpoint performs neither action.
"""

from __future__ import annotations

import ast
import builtins
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import resource
import selectors
import signal
import socket
import stat
import subprocess
import sys
import time
import types
from typing import Any, Optional


BASE_REVISION = "a30b879d06c388a4a0e230b5a23b2eaedc93649d"
ADAPTER_SOURCE_REVISION = "65b82ffd890479315c9a93769cf11e2a9d27074b"
ADAPTER_ACCEPTANCE_REVISION = BASE_REVISION
# Compatibility name for reviewers of the scaffold's first frozen bytes.
ADAPTER_REVISION = ADAPTER_SOURCE_REVISION
INSTALL_RESULT_REVISION = "9146d7a264418f59d76e4d8c7a46ac2abc80e9e8"
INSTALL_ACCEPTANCE_REVISION = "35fede04256442f7853d38980de174526cf28220"
INSTALL_SOURCE_REVISION = "c5acaf37fabe4a1f9d3333f75e157b77ca327daf"
CONTROL_REVISION = "68aa82ffbdd43e78e585d8956d13d3030ef6a640"
PRESERVATION_REVISION = "2cfb58b9f227a37cc86843bef7dc1014bc185391"

STAGER_REF = (
    "tools/stage_collect_and_materialize_item26_manual_cost_stop_m1_v2.py"
)
TEST_REF = (
    "tests/test_stage_collect_and_materialize_item26_manual_cost_stop_m1_v2.py"
)
ADAPTER_REF = "tools/item26_aliyun_official_read_v2.py"
C1_CAPSULE_REF = "tools/item26_aliyun_temporary_sts_capsule_v1.py"
C1_CAPSULE_SOURCE_REVISION = "86206f816fb092a7fca7a577b1391e251dfca5ca"
C1_CAPSULE_ACCEPTANCE_REVISION = "314a6b885bc7bda9790074a201ac176e498326b5"
C1_CAPSULE_GIT_BLOB_OID = "99110863d055929fbc76950ec2bc9aa8fd0f7bc6"
C1_CAPSULE_FILE_SHA256 = (
    "7ed50fd5acdbb5733a174367e8bcb339b3a6bc07b49fed3a31243fddf763e4e3"
)
C1_CAPSULE_BYTES = 49494
C1_CAPSULE_FIXED_BINDING = {
    "source_ref": C1_CAPSULE_REF,
    "source_revision": C1_CAPSULE_SOURCE_REVISION,
    "acceptance_revision": C1_CAPSULE_ACCEPTANCE_REVISION,
    "git_blob_oid": C1_CAPSULE_GIT_BLOB_OID,
    "file_sha256": C1_CAPSULE_FILE_SHA256,
    "size": C1_CAPSULE_BYTES,
}
C1_HANDSHAKE_SCHEMA = "noteai.item26.m1-c1-capture-handshake.v1"
C1_READY_BINDING_SCHEMA = "noteai.item26.m1-c1-ready-binding.v1"
C1_READY_STATUS = "ROOT_CUSTODY_TEMPORARY_STS_READY_FOR_CAPTURE_ACK"
C1_ACK_STATUS = "ROOT_CUSTODY_TEMPORARY_STS_CAPTURE_ACKNOWLEDGED"
C1_READY_SHA256_DOMAIN = b"noteai.item26.m1-c1-ready-sha256.v1\x00"
MAX_C1_HANDSHAKE_BYTES = 4096
C1_SESSION_SETUP_TIMEOUT_SECONDS = 20
COLLECTOR_REF = "tools/collect_item26_manual_cost_stop_raw_v2.py"
EXTRACTOR_REF = "tools/extract_item26_manual_cost_stop_raw_v2.py"
BUILDER_REF = "tools/build_item26_manual_cost_stop_evidence_v2.py"
EVIDENCE_VERIFIER_REF = "tools/verify_item26_manual_cost_stop_evidence_v2.py"
AUTHORITY_VERIFIER_REF = "tools/verify_item26_manual_cost_stop_authority_v2.py"
AUTHORITY_ROOT_REF = (
    "deploy/production/authorities/"
    "item26-manual-cost-stop-authority-root-v2.json"
)
INSTALL_RESULT_REF = (
    ".codex/item26-manual-cost-stop-runtime-v3-install-result-"
    + INSTALL_ACCEPTANCE_REVISION
    + ".json"
)
ACTIVATION_RECEIPT_REF = (
    ".codex/item26-manual-cost-stop-activation-receipt-v3-"
    + CONTROL_REVISION
    + ".json"
)
M1_RECEIPT_REF = (
    "deploy/production/evidence/"
    "item26-manual-cost-stop-provider-receipt-v2-20260817.json"
)
M1_EVIDENCE_REF = (
    "deploy/production/evidence/"
    "production-item26-manual-cost-stop-v2-20260817.json"
)
M2_CHECKPOINT_REF = (
    "deploy/production/evidence/"
    "item26-manual-cost-stop-terminal-checkpoint-v2-20260817.json"
)

LEDGER_REFS = frozenset(
    {
        ".codex/handoffs/current-task.md",
        ".codex/notes/architecture-summary.md",
        ".codex/notes/risk-register.md",
        "deploy/production/internal-deployment-readiness.json",
    }
)
SOURCE_REFS = frozenset({STAGER_REF, TEST_REF, *LEDGER_REFS})
ACCEPTANCE_REFS = LEDGER_REFS

SOURCE_SUCCESSOR_DISTANCE = 6
ACCEPTANCE_SUCCESSOR_DISTANCE = 4
STAGE_RESULT_PREFIX = (
    ".codex/item26-m1-capture-materializer-stage-result-"
)
STAGE_RESULT_SCHEMA = "noteai.item26.m1-root-staging-result.v1"
STAGE_CHILD_STATUS_SCHEMA = "noteai.item26.m1-root-staging-child-status.v1"
STAGE_BUNDLE_SCHEMA = "noteai.item26.m1-root-staging-public-bundle.v1"
STAGE_AUTHORIZATION_ID = (
    "CTO-AUTH-ITEM26-M1-CAPTURE-MATERIALIZER-STAGER-SOURCE-001"
)
MAX_STAGE_BUNDLE_BYTES = 256 * 1024
MAX_STAGE_STATUS_BYTES = 16 * 1024
MAX_STAGE_GIT_BYTES = 1024 * 1024
STAGE_SUDO_MONITOR_TIMEOUT_SECONDS = 120
STAGE_CHILD_TIMEOUT_SECONDS = 125
STAGE_GIT_TIMEOUT_SECONDS = 15
STAGE_SUDO_COMMAND_PREFIX = (
    "/usr/bin/sudo",
    "-T",
    str(STAGE_SUDO_MONITOR_TIMEOUT_SECONDS),
    "--",
    "/usr/bin/python3",
    "-I",
    "-S",
    "-B",
)
STAGE_SUDO_ENVIRONMENT = {
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
}
STAGE_ROOT_ENVIRONMENT = {
    "HOME": "/var/root",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": (
        "/Library/Developer/CommandLineTools/usr/bin:/usr/bin:/bin"
    ),
    "TMPDIR": "/tmp",
}
STAGE_ROOT_PYTHON_EXECUTABLE = (
    "/Library/Developer/CommandLineTools/usr/bin/python3"
)
STAGE_ROOT_PYTHON_RESOLVED_EXECUTABLE = (
    "/Library/Developer/CommandLineTools/Library/Frameworks/"
    "Python3.framework/Versions/3.9/bin/python3.9"
)
STAGE_ROOT_GIT_EXECUTABLE = (
    "/Library/Developer/CommandLineTools/usr/bin/git"
)
STAGE_GIT_ENVIRONMENT = {
    "GIT_CONFIG_COUNT": "4",
    "GIT_CONFIG_KEY_0": "core.fsmonitor",
    "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "core.hooksPath",
    "GIT_CONFIG_VALUE_1": "/dev/null",
    "GIT_CONFIG_KEY_2": "fetch.recurseSubmodules",
    "GIT_CONFIG_VALUE_2": "false",
    "GIT_CONFIG_KEY_3": "submodule.recurse",
    "GIT_CONFIG_VALUE_3": "false",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "HOME": "/var/empty",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/Library/Developer/CommandLineTools/usr/bin:/usr/bin:/bin",
}
STAGE_CHILD_SUCCESS_KEYS = frozenset(
    {
        "schema",
        "status",
        "source_revision",
        "acceptance_revision",
        "capture_directory_create_count",
        "materialize_directory_create_count",
        "capture_file_create_count",
        "materialize_file_create_count",
        "sudo_dispatch_count",
        "automatic_retry_count",
        "cleanup_count",
        "rollback_count",
        "private_key_read_count",
    }
)

FUTURE_TOPOLOGY_CONTRACT = {
    "schema": "noteai.item26.m1-source-acceptance-topology.v1",
    "base_revision": BASE_REVISION,
    "source_revision_argument": "S",
    "acceptance_revision_argument": "F",
    "base_to_source_direct_child": True,
    "base_to_source_exact_changed_paths": sorted(SOURCE_REFS),
    "base_to_source_exact_changed_path_count": SOURCE_SUCCESSOR_DISTANCE,
    "source_to_acceptance_direct_child": True,
    "source_to_acceptance_exact_changed_paths": sorted(ACCEPTANCE_REFS),
    "source_to_acceptance_exact_changed_path_count": (
        ACCEPTANCE_SUCCESSOR_DISTANCE
    ),
    "head_upstream_origin_main_equal_acceptance": True,
    "tracked_worktree_clean_required": True,
    "untracked_paths_ignored_but_never_read": True,
    "fixed_control_receipt_install_adapter_zero_drift": True,
}

STAGE_SYSTEM_TOOL_BINDINGS = {
    "/usr/bin/sudo": {
        "size": 1580368,
        "mode": "4511",
        "uid": 0,
        "gid": 0,
        "nlink": 1,
        "sha256": None,
        "content_read_allowed": False,
    },
    "/usr/bin/python3": {
        "size": 118928,
        "mode": "0755",
        "uid": 0,
        "gid": 0,
        "nlink": 78,
        "sha256": (
            "179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818"
        ),
        "content_read_allowed": True,
    },
    "/usr/bin/git": {
        "size": 118928,
        "mode": "0755",
        "uid": 0,
        "gid": 0,
        "nlink": 78,
        "sha256": (
            "179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818"
        ),
        "content_read_allowed": True,
    },
    STAGE_ROOT_PYTHON_RESOLVED_EXECUTABLE: {
        "size": 102352,
        "mode": "0755",
        "uid": 0,
        "gid": 0,
        "nlink": 1,
        "sha256": (
            "4b42b1a117605cafc8607b67b0892a609c2cd125012dd56288abeed8c89cdfb1"
        ),
        "content_read_allowed": True,
    },
    STAGE_ROOT_GIT_EXECUTABLE: {
        "size": 7604272,
        "mode": "0755",
        "uid": 0,
        "gid": 0,
        "nlink": 1,
        "sha256": (
            "3121e7e4d16059539731c58d94888709c12904abe922acde8e37caef4607c1d1"
        ),
        "content_read_allowed": True,
    },
}
STAGE_SYSTEM_SYMLINK_BINDINGS = {
    STAGE_ROOT_PYTHON_EXECUTABLE: (
        "../../Library/Frameworks/Python3.framework/Versions/3.9/bin/python3"
    ),
    (
        "/Library/Developer/CommandLineTools/Library/Frameworks/"
        "Python3.framework/Versions/3.9/bin/python3"
    ): "python3.9",
}

FIXED_BINDINGS = {
    ADAPTER_REF: {
        "revision": ADAPTER_ACCEPTANCE_REVISION,
        "source_revision": ADAPTER_SOURCE_REVISION,
        "git_blob_oid": "f53a01805ea68005ca9e56a08dfa491221c224cf",
        "file_sha256": (
            "719886d2846a7602bf3fc0529f5c191305b58465c668d171461860d4c60aadb9"
        ),
        "size": 31410,
    },
    COLLECTOR_REF: {
        "revision": CONTROL_REVISION,
        "git_blob_oid": "e584b87cb7c2dcea46efe5ba01042e7e7e0d94e0",
        "file_sha256": (
            "739b8e8bea29250ccd4c24b400af791c67e687f0cecd23a4b1ddbc8b70750ea4"
        ),
        "size": 85025,
    },
    EXTRACTOR_REF: {
        "revision": CONTROL_REVISION,
        "git_blob_oid": "64b87e4630b894f57f64317e0b3cb70b8367e153",
        "file_sha256": (
            "7264bc6d1b3028c141a32d56a69e248fac283c835f776ed6f7c09b9f1c2d0fd4"
        ),
        "size": 62917,
    },
    BUILDER_REF: {
        "revision": CONTROL_REVISION,
        "git_blob_oid": "861f355a92505c9e3f000a74acb57598375dd16e",
        "file_sha256": (
            "ecf0a3d984b99b09e9f3d189f28fb8b60bd2355a28bf04565fd7c297fa765acb"
        ),
        "size": 16835,
    },
    EVIDENCE_VERIFIER_REF: {
        "revision": CONTROL_REVISION,
        "git_blob_oid": "95727f7e6b8bcb7ff738ee2b2f0b9c650fc59968",
        "file_sha256": (
            "8834c524165f3104cdf848e26eaefdcb3ed0e0e635e9ec3c1a02d3bcb02c6269"
        ),
        "size": 40689,
    },
    AUTHORITY_VERIFIER_REF: {
        "revision": CONTROL_REVISION,
        "git_blob_oid": "91d5eaf9d63f3595c257ad31502407d1bb9a3cb0",
        "file_sha256": (
            "19cc65133410cfa4face4887943504c8726430cc196b4f83d68cb3e0675a959d"
        ),
        "size": 125914,
    },
    AUTHORITY_ROOT_REF: {
        "revision": CONTROL_REVISION,
        "git_blob_oid": "a15720151f141e6b783a51d136e94d9957a7b1c6",
        "file_sha256": (
            "8bfb8834c1e241a18cde984d42524759f53423bcf809dd8657fa4b2be102ff85"
        ),
        "size": 20816,
    },
    INSTALL_RESULT_REF: {
        "revision": INSTALL_RESULT_REVISION,
        "git_blob_oid": "225a3d23e494b86f6e8a8c8594dbacfc40bdb639",
        "file_sha256": (
            "5ac98e74d18c22ee424448284f552f70d859cfe6b1a081769116aa5bcd333a5c"
        ),
        "size": 675,
    },
    ACTIVATION_RECEIPT_REF: {
        "revision": PRESERVATION_REVISION,
        "git_blob_oid": "2a52e03416a096ccfca5ef9958d61a25290b10ac",
        "file_sha256": (
            "61b756abed72b2f6ab8fb3b20a260b03c0932f6e4c271c4f723a4e5942cd7f2a"
        ),
        "size": 22068,
    },
}

CAPTURE_SLOTS = (
    "cost_stop_rds_write_lookup_page",
    "clone_create_lookup_page",
    "fresh_clone_inventory",
    "fresh_source_inventory",
    "historical_billing_snapshot",
)
CAPTURE_SLOT_OPERATIONS = {
    "cost_stop_rds_write_lookup_page": ("LookupEvents", "2020-07-06"),
    "clone_create_lookup_page": ("LookupEvents", "2020-07-06"),
    "fresh_clone_inventory": ("DescribeDBInstances", "2014-08-15"),
    "fresh_source_inventory": ("DescribeDBInstances", "2014-08-15"),
    "historical_billing_snapshot": ("QueryInstanceBill", "2017-12-14"),
}
MAX_PROVIDER_DISPATCHES = 64
MAX_RECORD_SECONDS = 14 * 60
FULL_CAPTURE_TIMEOUT_SECONDS = 14 * 60
POST_CAPTURE_IDENTITY_DEADLINE_SECONDS = 30
POST_CAPTURE_MAX_FILE_READ_COUNT = 18
ADAPTER_CHILD_WALL_TIMEOUT_SECONDS = 45
MAX_ACTIVE_ADAPTER_CHILDREN = 1
PARALLEL_PROVIDER_DISPATCH_COUNT = 0
# Kept as an audit alias: it means additional/overlapping dispatches, not the
# number of children that may be active for the one current record.
PROVIDER_DISPATCH_CONCURRENCY = PARALLEL_PROVIDER_DISPATCH_COUNT
AUTOMATIC_RETRY_COUNT = 0
REPLAY_COUNT = 0

AUTHORITY_DIRECTORY = (
    "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2"
)
RUNTIME_DIRECTORY = (
    "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-tools"
)
JOURNAL_DIRECTORY = (
    "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-journal"
)
CUSTODY_DIRECTORY = (
    "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-custody"
)
CAPTURE_RUNTIME_DIRECTORY = (
    "/Library/Application Support/NoteAI/"
    "item26-manual-cost-stop-v2-m1-capture"
)
MATERIALIZE_RUNTIME_DIRECTORY = (
    "/Library/Application Support/NoteAI/"
    "item26-manual-cost-stop-v2-m1-materialize"
)
EXISTING_ROOT_PARTITIONS = {
    "authority": AUTHORITY_DIRECTORY,
    "runtime": RUNTIME_DIRECTORY,
    "journal": JOURNAL_DIRECTORY,
    "custody": CUSTODY_DIRECTORY,
}
NEW_ROOT_PARTITIONS = {
    "capture": CAPTURE_RUNTIME_DIRECTORY,
    "materialize": MATERIALIZE_RUNTIME_DIRECTORY,
}
ROOT_RUNTIME_DIRECTORY_MODE = "0700"

CAPTURE_RUNTIME_INVENTORY = {
    "capture-root-program.py": {
        "mode": "0500",
        "source_ref": "embedded:CAPTURE_ROOT_PROGRAM",
        "purpose": "capture-root-entry",
    },
    "item26_aliyun_official_read_v2.py": {
        "mode": "0500",
        "source_ref": ADAPTER_REF,
        "purpose": "single-request-fd-transport",
    },
    "capture-runtime-manifest.json": {
        "mode": "0600",
        "source_ref": None,
        "purpose": "o-excl-root-binding-manifest",
    },
}
MATERIALIZE_RUNTIME_INVENTORY = {
    "materialize-root-program.py": {
        "mode": "0500",
        "source_ref": "embedded:MATERIALIZE_ROOT_PROGRAM",
        "purpose": "materialize-root-entry",
    },
    "build_item26_manual_cost_stop_evidence_v2.py": {
        "mode": "0500",
        "source_ref": BUILDER_REF,
        "purpose": "receipt-evidence-builder",
    },
    "verify_item26_manual_cost_stop_evidence_v2.py": {
        "mode": "0500",
        "source_ref": EVIDENCE_VERIFIER_REF,
        "purpose": "receipt-evidence-verifier",
    },
    "extract_item26_manual_cost_stop_raw_v2.py": {
        "mode": "0500",
        "source_ref": EXTRACTOR_REF,
        "purpose": "frozen-extraction-parity",
    },
    "verify_item26_manual_cost_stop_authority_v2.py": {
        "mode": "0500",
        "source_ref": AUTHORITY_VERIFIER_REF,
        "purpose": "exact-source-with-fd-signature-patch-before-use",
    },
    "materialize-runtime-manifest.json": {
        "mode": "0600",
        "source_ref": None,
        "purpose": "o-excl-root-binding-manifest",
    },
}
CAPTURE_DEPENDENCY_ALLOWLIST = (
    ADAPTER_REF,
    COLLECTOR_REF,
    EXTRACTOR_REF,
    AUTHORITY_VERIFIER_REF,
    ACTIVATION_RECEIPT_REF,
)
MATERIALIZE_DEPENDENCY_ALLOWLIST = (
    BUILDER_REF,
    EVIDENCE_VERIFIER_REF,
    EXTRACTOR_REF,
    AUTHORITY_VERIFIER_REF,
)
CAPTURE_DEPENDENCY_LOCATIONS = {
    ADAPTER_REF: CAPTURE_RUNTIME_DIRECTORY,
    COLLECTOR_REF: RUNTIME_DIRECTORY,
    EXTRACTOR_REF: RUNTIME_DIRECTORY,
    AUTHORITY_VERIFIER_REF: RUNTIME_DIRECTORY,
    ACTIVATION_RECEIPT_REF: RUNTIME_DIRECTORY,
}
MATERIALIZE_DEPENDENCY_LOCATIONS = {
    BUILDER_REF: MATERIALIZE_RUNTIME_DIRECTORY,
    EVIDENCE_VERIFIER_REF: MATERIALIZE_RUNTIME_DIRECTORY,
    EXTRACTOR_REF: MATERIALIZE_RUNTIME_DIRECTORY,
    AUTHORITY_VERIFIER_REF: MATERIALIZE_RUNTIME_DIRECTORY,
}

RUNTIME_MANIFEST_SCHEMA = "noteai.item26.m1-root-runtime-manifest.v1"
RUNTIME_MANIFEST_PAYLOAD_FIELDS = (
    "name",
    "byte_count",
    "sha256",
    "mode",
    "source_revision",
    "source_ref",
)
CAPTURE_RUNTIME_MANIFEST_SPEC = {
    "schema": RUNTIME_MANIFEST_SCHEMA,
    "manifest_name": "capture-runtime-manifest.json",
    "manifest_mode": "0600",
    "payloads": {
        "capture-root-program.py": {
            "name": "capture-root-program.py",
            "byte_count": "EXPECTED_CAPTURE_ROOT_BYTES_ARGUMENT",
            "sha256": "EXPECTED_CAPTURE_ROOT_SHA256_ARGUMENT",
            "mode": "0500",
            "source_revision": "EXPECTED_ACCEPTANCE_REVISION_ARGUMENT",
            "source_ref": STAGER_REF + ":CAPTURE_ROOT_PROGRAM",
        },
        "item26_aliyun_official_read_v2.py": {
            "name": "item26_aliyun_official_read_v2.py",
            "byte_count": FIXED_BINDINGS[ADAPTER_REF]["size"],
            "sha256": FIXED_BINDINGS[ADAPTER_REF]["file_sha256"],
            "mode": "0500",
            "source_revision": ADAPTER_ACCEPTANCE_REVISION,
            "source_ref": ADAPTER_REF,
        },
    },
}
MATERIALIZE_RUNTIME_MANIFEST_SPEC = {
    "schema": RUNTIME_MANIFEST_SCHEMA,
    "manifest_name": "materialize-runtime-manifest.json",
    "manifest_mode": "0600",
    "payloads": {
        "materialize-root-program.py": {
            "name": "materialize-root-program.py",
            "byte_count": "EXPECTED_MATERIALIZE_ROOT_BYTES_ARGUMENT",
            "sha256": "EXPECTED_MATERIALIZE_ROOT_SHA256_ARGUMENT",
            "mode": "0500",
            "source_revision": "EXPECTED_ACCEPTANCE_REVISION_ARGUMENT",
            "source_ref": STAGER_REF + ":MATERIALIZE_ROOT_PROGRAM",
        },
        "build_item26_manual_cost_stop_evidence_v2.py": {
            "name": "build_item26_manual_cost_stop_evidence_v2.py",
            "byte_count": FIXED_BINDINGS[BUILDER_REF]["size"],
            "sha256": FIXED_BINDINGS[BUILDER_REF]["file_sha256"],
            "mode": "0500",
            "source_revision": CONTROL_REVISION,
            "source_ref": BUILDER_REF,
        },
        "verify_item26_manual_cost_stop_evidence_v2.py": {
            "name": "verify_item26_manual_cost_stop_evidence_v2.py",
            "byte_count": FIXED_BINDINGS[EVIDENCE_VERIFIER_REF]["size"],
            "sha256": FIXED_BINDINGS[EVIDENCE_VERIFIER_REF]["file_sha256"],
            "mode": "0500",
            "source_revision": CONTROL_REVISION,
            "source_ref": EVIDENCE_VERIFIER_REF,
        },
        "extract_item26_manual_cost_stop_raw_v2.py": {
            "name": "extract_item26_manual_cost_stop_raw_v2.py",
            "byte_count": FIXED_BINDINGS[EXTRACTOR_REF]["size"],
            "sha256": FIXED_BINDINGS[EXTRACTOR_REF]["file_sha256"],
            "mode": "0500",
            "source_revision": CONTROL_REVISION,
            "source_ref": EXTRACTOR_REF,
        },
        "verify_item26_manual_cost_stop_authority_v2.py": {
            "name": "verify_item26_manual_cost_stop_authority_v2.py",
            "byte_count": FIXED_BINDINGS[AUTHORITY_VERIFIER_REF]["size"],
            "sha256": FIXED_BINDINGS[AUTHORITY_VERIFIER_REF]["file_sha256"],
            "mode": "0500",
            "source_revision": CONTROL_REVISION,
            "source_ref": AUTHORITY_VERIFIER_REF,
        },
    },
}

EXISTING_AUTHORITY_ACTIVATION_INVENTORY = ("authority-root-v2.json",)
EXISTING_RUNTIME_INVENTORY = (
    "collect_item26_manual_cost_stop_raw_v2.py",
    "extract_item26_manual_cost_stop_raw_v2.py",
    "verify_item26_manual_cost_stop_authority_v2.py",
    "runtime-activation-receipt-v3.json",
)
EXISTING_CUSTODY_INVENTORY = (
    "provider-private-key.pem",
    "confirmation-private-key.pem",
    "local-ci-observation-private-key.pem",
)
EXISTING_PUBLIC_FILE_BINDINGS = {
    "authority-root-v2.json": {
        "source_ref": AUTHORITY_ROOT_REF,
        "size": 20816,
        "sha256": (
            "8bfb8834c1e241a18cde984d42524759f53423bcf809dd8657fa4b2be102ff85"
        ),
        "mode": "0600",
    },
    "collect_item26_manual_cost_stop_raw_v2.py": {
        "source_ref": COLLECTOR_REF,
        "size": FIXED_BINDINGS[COLLECTOR_REF]["size"],
        "sha256": FIXED_BINDINGS[COLLECTOR_REF]["file_sha256"],
        "mode": "0600",
    },
    "extract_item26_manual_cost_stop_raw_v2.py": {
        "source_ref": EXTRACTOR_REF,
        "size": FIXED_BINDINGS[EXTRACTOR_REF]["size"],
        "sha256": FIXED_BINDINGS[EXTRACTOR_REF]["file_sha256"],
        "mode": "0600",
    },
    "verify_item26_manual_cost_stop_authority_v2.py": {
        "source_ref": AUTHORITY_VERIFIER_REF,
        "size": FIXED_BINDINGS[AUTHORITY_VERIFIER_REF]["size"],
        "sha256": FIXED_BINDINGS[AUTHORITY_VERIFIER_REF]["file_sha256"],
        "mode": "0600",
    },
    "runtime-activation-receipt-v3.json": {
        "source_ref": ACTIVATION_RECEIPT_REF,
        "size": FIXED_BINDINGS[ACTIVATION_RECEIPT_REF]["size"],
        "sha256": FIXED_BINDINGS[ACTIVATION_RECEIPT_REF]["file_sha256"],
        "mode": "0600",
    },
}
EXISTING_INVENTORY_SNAPSHOT_CONTRACT = {
    "schema": "noteai.item26.m1-existing-root-inventory-snapshot.v1",
    "snapshot_phase": "ROOT_STAGING_PRE_AND_POST_BEFORE_CAPTURE_BEGIN",
    "authority_names": list(EXISTING_AUTHORITY_ACTIVATION_INVENTORY),
    "runtime_names": list(EXISTING_RUNTIME_INVENTORY),
    "journal_names": [],
    "custody_names": list(EXISTING_CUSTODY_INVENTORY),
    "directory_mode": "0700",
    "directory_pre_post_name_inode_mode_equal": True,
    "public_file_bindings": EXISTING_PUBLIC_FILE_BINDINGS,
    "public_file_content_read_allowed": True,
    "public_file_pre_post_name_inode_hash_size_mode_equal": True,
    "custody_file_mode": "0600",
    "custody_file_nlink": 1,
    "custody_content_read_count": 0,
    "custody_content_hash_allowed": False,
    "custody_metadata_manifest_sha256_required": True,
    "custody_pre_post_name_inode_size_mode_equal": True,
    "journal_pre_post_empty_required": True,
    "authority_runtime_journal_custody_stage_write_count": 0,
    "noteai_parent_stable_identity_fields": [
        "st_dev",
        "st_ino",
        "st_mode",
        "st_uid",
        "st_gid",
    ],
    "noteai_parent_expected_direct_child_create_count": 2,
    "noteai_parent_nlink_mtime_ctime_change_allowed_for_direct_child_mkdirs": True,
    "noteai_parent_other_identity_drift_allowed": False,
}

CAPTURE_FINAL_AUTHORITY_INVENTORY = (
    "authority-root-v2.json",
    "provider-raw-v2.json",
    "actiontrail-raw-v2.json",
)
ADAPTER_FD_CHANNELS = (
    "logical_request",
    "temporary_sts",
    "raw_response",
    "fixed_status",
)
MAX_ADAPTER_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_CHILD_STATUS_BYTES = 4096
MAX_MATERIALIZE_RECEIPT_BYTES = 8 * 1024 * 1024
MAX_MATERIALIZE_EVIDENCE_BYTES = 8 * 1024 * 1024
MAX_MATERIALIZE_STATUS_BYTES = 4096
MAX_SUPERVISED_STATUS_BYTES = 8192
CAPTURE_ROOT_RESULT_SCHEMA = "noteai.item26.m1-capture-root-result.v1"
MATERIALIZE_CHILD_STATUS_SCHEMA = (
    "noteai.item26.m1-materialize-child-status.v1"
)
M1_RECEIPT_SCHEMA = "noteai.item26.manual-cost-stop-provider-receipt.v2"
M1_EVIDENCE_SCHEMA = "noteai.item26.manual-cost-stop-evidence.v2"
MATERIALIZE_OUTER_RESULT_SCHEMA = (
    "noteai.item26.m1-materialize-outer-result.v1"
)
ROOT_PAYLOAD_SUPERVISOR_SCHEMA = "noteai.item26.m1-root-payload-supervisor.v1"
CAPTURE_CREDENTIAL_CAPSULE_SCHEMA = (
    "noteai.item26.m1-root-custody-temporary-sts-interface.v1"
)
MATERIALIZE_CAPTURE_CAPSULE_SCHEMA = (
    "noteai.item26.m1-finalized-capture-inventory-capsule.v1"
)
CAPTURE_SUDO_MONITOR_TIMEOUT_SECONDS = 920
MATERIALIZE_SUDO_MONITOR_TIMEOUT_SECONDS = 120
CAPTURE_OUTER_HARD_TIMEOUT_SECONDS = 20 * 60
MATERIALIZE_OUTER_HARD_TIMEOUT_SECONDS = 5 * 60
OUTER_TERMINAL_EOF_GRACE_SECONDS = 2
OUTER_INTERACTIVE_AUTH_TIMEOUT_SECONDS = 15 * 60
CAPTURE_C1_HANDSHAKE_TIMEOUT_SECONDS = 20
OUTER_TERMINATE_GRACE_SECONDS = 7
OUTER_KILL_GRACE_SECONDS = 2
SUPERVISOR_ACK_TIMEOUT_SECONDS = 4
CAPTURE_SUPERVISOR_ACK_TIMEOUT_SECONDS = 8
SUPERVISOR_NORMAL_WAIT_SECONDS = 2
SUPERVISOR_TERM_GRACE_SECONDS = 3
SUPERVISOR_KILL_GRACE_SECONDS = 2
SUPERVISOR_TERMINAL_EMIT_BUDGET_SECONDS = 1
CAPTURE_SUPERVISOR_RUNTIME_TIMEOUT_SECONDS = 900
MATERIALIZE_SUPERVISOR_RUNTIME_TIMEOUT_SECONDS = 105
OUTER_COMMIT_SIGNALS = (
    signal.SIGTERM,
    signal.SIGINT,
    signal.SIGHUP,
    signal.SIGQUIT,
    signal.SIGALRM,
)
MAX_FINALIZED_CAPTURE_ARTIFACT_BYTES = 24 * 1024 * 1024
CAPTURE_RUNTIME_PROGRAM_PATH = (
    CAPTURE_RUNTIME_DIRECTORY + "/capture-root-program.py"
)
MATERIALIZE_RUNTIME_PROGRAM_PATH = (
    MATERIALIZE_RUNTIME_DIRECTORY + "/materialize-root-program.py"
)
MATERIALIZE_SUDO_COMMAND_PREFIX = (
    "/usr/bin/sudo",
    "-T",
    str(MATERIALIZE_SUDO_MONITOR_TIMEOUT_SECONDS),
)
CAPTURE_EXEC_BOOTSTRAP = r'''
import fcntl
import json
import os
import resource
import selectors
import signal
import socket
import stat
import subprocess
import sys
import time

SCHEMA = "noteai.item26.m1-root-payload-supervisor.v1"
TERMINATION_SIGNALS = (
    signal.SIGTERM,
    signal.SIGINT,
    signal.SIGHUP,
    signal.SIGQUIT,
    signal.SIGALRM,
)
ACTIVE = None
MAX_PAYLOAD_STATUS_BYTES = 4096
ACK_TIMEOUT_SECONDS = 8
NORMAL_WAIT_SECONDS = 2.0
TERM_GRACE_SECONDS = 3.0
KILL_GRACE_SECONDS = 2.0
RUNTIME_TIMEOUT_SECONDS = 900
TERMINAL_EMIT_BUDGET_SECONDS = 1.0
GATE_CODE = (
    "import os,sys\n"
    "descriptor=int(sys.argv[1])\n"
    "token=os.read(descriptor,2)\n"
    "os.close(descriptor)\n"
    "if token != b'G': raise SystemExit(78)\n"
    "arguments=sys.argv[2:]\n"
    "os.execve(arguments[0],arguments,dict(os.environ))\n"
)

class SupervisorSignal(BaseException):
    pass

def canonical(value):
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )

def emit(value):
    raw = canonical(value)
    while raw:
        count = os.write(1, raw)
        if count < 1:
            raise RuntimeError("supervisor_status_write")
        raw = raw[count:]

def emit_payload(raw):
    if type(raw) is not bytes or not raw or len(raw) > MAX_PAYLOAD_STATUS_BYTES:
        raise RuntimeError("supervisor_payload_status")
    framed = raw
    while framed:
        count = os.write(1, framed)
        if count < 1:
            raise RuntimeError("supervisor_status_write")
        framed = framed[count:]

def on_signal(_signum, _frame):
    raise SupervisorSignal()

def settle(process, force_kill):
    pid = getattr(process, "pid", None)
    if type(pid) is not int or pid <= 1:
        raise RuntimeError("supervisor_process")
    reaped = process.poll() is not None
    returncode = process.returncode if reaped else None
    if not force_kill and not reaped:
        try:
            returncode = process.wait(timeout=NORMAL_WAIT_SECONDS)
            reaped = True
        except Exception:
            force_kill = True
    if reaped and not force_kill:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return returncode
        except OSError:
            pass
    if force_kill and not reaped:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        term_deadline = time.monotonic() + TERM_GRACE_SECONDS
        while not reaped and time.monotonic() < term_deadline:
            try:
                returncode = process.wait(timeout=0.05)
                reaped = True
            except Exception:
                pass
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        if reaped:
            return returncode
    except OSError:
        pass
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + KILL_GRACE_SECONDS
    while True:
        if not reaped:
            try:
                returncode = process.wait(timeout=0.05)
                reaped = True
            except Exception:
                pass
        absent = False
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            absent = True
        except OSError:
            pass
        if reaped and absent:
            return returncode
        if time.monotonic() >= deadline:
            raise RuntimeError("supervisor_group_containment")
        time.sleep(0.01)

def settle_active(force_kill):
    global ACTIVE
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, TERMINATION_SIGNALS)
    try:
        returncode = settle(ACTIVE, force_kill)
        ACTIVE = None
        return returncode
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

def status_pair():
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    for channel in (parent, child):
        if (
            channel.fileno() < 3
            or channel.family != socket.AF_UNIX
            or channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
            != socket.SOCK_STREAM
            or channel.getsockname() not in (None, "", b"")
            or channel.getpeername() not in (None, "", b"")
            or not channel.getblocking()
        ):
            raise RuntimeError("supervisor_status_channel")
    if os.fstat(parent.fileno())[:2] == os.fstat(child.fileno())[:2]:
        raise RuntimeError("supervisor_status_alias")
    return parent, child

def gate_pipe():
    reader, writer = os.pipe()
    reader_row = os.fstat(reader)
    writer_row = os.fstat(writer)
    reader_flags = fcntl.fcntl(reader, fcntl.F_GETFL)
    writer_flags = fcntl.fcntl(writer, fcntl.F_GETFL)
    if (
        reader < 3
        or writer < 3
        or reader == writer
        or not stat.S_ISFIFO(reader_row.st_mode)
        or not stat.S_ISFIFO(writer_row.st_mode)
        or reader_flags & os.O_ACCMODE != os.O_RDONLY
        or writer_flags & os.O_ACCMODE != os.O_WRONLY
        or reader_flags & os.O_NONBLOCK
        or writer_flags & os.O_NONBLOCK
    ):
        raise RuntimeError("supervisor_gate_channel")
    return reader, writer

def inherited_credential_endpoints():
    ready = ack = None
    try:
        ready = os.dup(2)
        ack = os.dup(0)
        probes = []
        identities = []
        for descriptor, direction in ((ready, "ready"), (ack, "ack")):
            row = os.fstat(descriptor)
            flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
            duplicate = os.dup(descriptor)
            channel = socket.socket(fileno=duplicate)
            probes.append(channel)
            identity = (row.st_dev, row.st_ino)
            identities.append(identity)
            if (
                descriptor < 3
                or not stat.S_ISSOCK(row.st_mode)
                or flags & os.O_ACCMODE != os.O_RDWR
                or flags & (os.O_NONBLOCK | getattr(os, "O_ASYNC", 0))
                or channel.family != socket.AF_UNIX
                or channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
                != socket.SOCK_STREAM
                or channel.getsockname() not in (None, "", b"")
                or channel.getpeername() not in (None, "", b"")
                or direction not in {"ready", "ack"}
            ):
                raise RuntimeError("supervisor_credential_channel")
        if len(set(identities)) != 2:
            raise RuntimeError("supervisor_credential_alias")
        return ready, ack
    except BaseException:
        for descriptor in (ready, ack):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except BaseException:
                    pass
        raise
    finally:
        for channel in locals().get("probes", ()):
            channel.close()

def close_inherited_credential_stdio(owned):
    failure = None
    for descriptor in (0, 2):
        if descriptor not in owned:
            continue
        owned.remove(descriptor)
        try:
            os.close(descriptor)
        except BaseException as exc:
            if failure is None:
                failure = exc
    if failure is not None:
        raise RuntimeError("supervisor_credential_stdio_close") from None

def drain_payload_status(process, channel, control_descriptor):
    selector = selectors.DefaultSelector()
    raw = bytearray()
    eof = False
    try:
        channel.setblocking(False)
        selector.register(channel, selectors.EVENT_READ, "payload")
        selector.register(control_descriptor, selectors.EVENT_READ, "control")
        while not eof:
            events = selector.select(0.25)
            for key, mask in events:
                if not mask & selectors.EVENT_READ:
                    continue
                if key.data == "control":
                    try:
                        os.read(control_descriptor, 1)
                    except OSError:
                        pass
                    raise SupervisorSignal()
                try:
                    chunk = key.fileobj.recv(
                        min(65536, MAX_PAYLOAD_STATUS_BYTES + 1 - len(raw))
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    eof = True
                    selector.unregister(key.fileobj)
                else:
                    raw.extend(chunk)
                    if len(raw) > MAX_PAYLOAD_STATUS_BYTES:
                        raise RuntimeError("supervisor_payload_status")
        value = json.loads(bytes(raw))
        if type(value) is not dict or canonical(value) != bytes(raw):
            raise RuntimeError("supervisor_payload_status")
        return bytes(raw)
    finally:
        selector.close()

resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
for signum in TERMINATION_SIGNALS:
    signal.signal(signum, on_signal)
returncode = 78
started = False
released = False
contained = False
failed = False
supervisor_pid = os.getpid()
payload_pgid = None
status_parent = None
status_child = None
gate_reader = None
gate_writer = None
credential_ready_fd = None
credential_ack_fd = None
payload_status = None
credential_stdio_owned = {0, 2}
try:
    credential_ready_fd, credential_ack_fd = inherited_credential_endpoints()
    status_parent, status_child = status_pair()
    gate_reader, gate_writer = gate_pipe()
    internal_descriptors = (
        credential_ready_fd,
        credential_ack_fd,
        status_parent.fileno(),
        status_child.fileno(),
        gate_reader,
        gate_writer,
    )
    if min(internal_descriptors) < 3 or len(set(internal_descriptors)) != 6:
        raise RuntimeError("supervisor_internal_fd_alias")
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, TERMINATION_SIGNALS)
    try:
        ACTIVE = subprocess.Popen(
            [
                "/usr/bin/python3",
                "-I",
                "-S",
                "-B",
                "-c",
                GATE_CODE,
                str(gate_reader),
                "/usr/bin/python3",
                "-I",
                "-S",
                "-B",
                "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-m1-capture/capture-root-program.py",
                "--capture",
                str(credential_ready_fd),
                str(credential_ack_fd),
                *sys.argv[1:],
            ],
            cwd="/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-m1-capture",
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            stdin=subprocess.DEVNULL,
            stdout=status_child.fileno(),
            stderr=subprocess.DEVNULL,
            close_fds=True,
            pass_fds=(gate_reader, credential_ready_fd, credential_ack_fd),
            start_new_session=True,
            text=False,
            bufsize=0,
        )
        started = True
        payload_pgid = ACTIVE.pid
        if os.getpgid(payload_pgid) != payload_pgid:
            raise RuntimeError("supervisor_payload_group")
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    close_inherited_credential_stdio(credential_stdio_owned)
    status_child.close()
    status_child = None
    os.close(credential_ready_fd)
    credential_ready_fd = None
    os.close(credential_ack_fd)
    credential_ack_fd = None
    os.close(gate_reader)
    gate_reader = None
    signal.alarm(ACK_TIMEOUT_SECONDS)
    emit(
        {
            "schema": SCHEMA,
            "status": "READY",
            "supervisor_pid": supervisor_pid,
            "payload_pgid": payload_pgid,
            "payload_release_count": 0,
            "payload_mode": "CAPTURE",
            "payload_program_sha256": "258d11ca4094efd5018ef8100378ea139949136953c318b6e10604a91ea6435d",
            "pre_release_action_count": 0,
            "automatic_retry_count": 0,
            "cleanup_count": 0,
            "raw_value_emitted_count": 0,
        }
    )
    if os.read(1, 2) != b"A":
        raise RuntimeError("supervisor_ack")
    if os.write(gate_writer, b"G") != 1:
        raise RuntimeError("supervisor_gate_release")
    os.close(gate_writer)
    gate_writer = None
    released = True
    signal.alarm(RUNTIME_TIMEOUT_SECONDS)
    payload_status = drain_payload_status(ACTIVE, status_parent, 1)
    returncode = settle_active(False)
    contained = True
except BaseException:
    failed = True
    if ACTIVE is not None:
        try:
            returncode = settle_active(True)
            contained = True
        except BaseException:
            contained = False
finally:
    signal.alarm(0)
    for descriptor in tuple(credential_stdio_owned):
        credential_stdio_owned.remove(descriptor)
        try:
            os.close(descriptor)
        except BaseException:
            pass
    for descriptor in (gate_reader, gate_writer):
        if descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException:
                pass
    for descriptor in (credential_ready_fd, credential_ack_fd):
        if descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException:
                pass
    for channel in (status_parent, status_child):
        if channel is not None:
            try:
                channel.close()
            except BaseException:
                pass
if contained or not started:
    if started and contained and payload_status is not None:
        emit_payload(payload_status)
    emit(
        {
            "schema": SCHEMA,
            "status": "PAYLOAD_GROUP_ABSENT",
            "payload_started": started,
            "payload_released": released,
            "supervisor_pid": supervisor_pid,
            "payload_pgid": payload_pgid,
            "payload_release_count": 1 if released else 0,
            "payload_mode": "CAPTURE",
            "payload_program_sha256": "258d11ca4094efd5018ef8100378ea139949136953c318b6e10604a91ea6435d",
            "pre_release_action_count": 0,
            "payload_returncode": returncode,
            "group_absent": True,
            "automatic_retry_count": 0,
            "cleanup_count": 0,
            "raw_value_emitted_count": 0,
        }
    )
raise SystemExit(0 if started and contained and not failed and returncode == 0 else 78)
'''
MATERIALIZE_STDIO_BOOTSTRAP = r'''
import fcntl
import json
import os
import resource
import selectors
import signal
import socket
import stat
import subprocess
import sys
import time

SCHEMA = "noteai.item26.m1-root-payload-supervisor.v1"
TERMINATION_SIGNALS = (
    signal.SIGTERM,
    signal.SIGINT,
    signal.SIGHUP,
    signal.SIGQUIT,
    signal.SIGALRM,
)
ACTIVE = None
MAX_PAYLOAD_STATUS_BYTES = 4096
ACK_TIMEOUT_SECONDS = 4
NORMAL_WAIT_SECONDS = 2.0
TERM_GRACE_SECONDS = 3.0
KILL_GRACE_SECONDS = 2.0
RUNTIME_TIMEOUT_SECONDS = 105
TERMINAL_EMIT_BUDGET_SECONDS = 1.0
GATE_CODE = (
    "import os,sys\n"
    "descriptor=int(sys.argv[1])\n"
    "token=os.read(descriptor,2)\n"
    "os.close(descriptor)\n"
    "if token != b'G': raise SystemExit(78)\n"
    "arguments=sys.argv[2:]\n"
    "os.execve(arguments[0],arguments,dict(os.environ))\n"
)

class SupervisorSignal(BaseException):
    pass

def canonical(value):
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )

def emit(value):
    raw = canonical(value)
    while raw:
        count = os.write(5, raw)
        if count < 1:
            raise RuntimeError("supervisor_status_write")
        raw = raw[count:]

def emit_payload(raw):
    if type(raw) is not bytes or not raw or len(raw) > MAX_PAYLOAD_STATUS_BYTES:
        raise RuntimeError("supervisor_payload_status")
    framed = raw
    while framed:
        count = os.write(5, framed)
        if count < 1:
            raise RuntimeError("supervisor_status_write")
        framed = framed[count:]

def on_signal(_signum, _frame):
    raise SupervisorSignal()

def settle(process, force_kill):
    pid = getattr(process, "pid", None)
    if type(pid) is not int or pid <= 1:
        raise RuntimeError("supervisor_process")
    reaped = process.poll() is not None
    returncode = process.returncode if reaped else None
    if not force_kill and not reaped:
        try:
            returncode = process.wait(timeout=NORMAL_WAIT_SECONDS)
            reaped = True
        except Exception:
            force_kill = True
    if reaped and not force_kill:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return returncode
        except OSError:
            pass
    if force_kill and not reaped:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        term_deadline = time.monotonic() + TERM_GRACE_SECONDS
        while not reaped and time.monotonic() < term_deadline:
            try:
                returncode = process.wait(timeout=0.05)
                reaped = True
            except Exception:
                pass
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        if reaped:
            return returncode
    except OSError:
        pass
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + KILL_GRACE_SECONDS
    while True:
        if not reaped:
            try:
                returncode = process.wait(timeout=0.05)
                reaped = True
            except Exception:
                pass
        absent = False
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            absent = True
        except OSError:
            pass
        if reaped and absent:
            return returncode
        if time.monotonic() >= deadline:
            raise RuntimeError("supervisor_group_containment")
        time.sleep(0.01)

def settle_active(force_kill):
    global ACTIVE
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, TERMINATION_SIGNALS)
    try:
        returncode = settle(ACTIVE, force_kill)
        ACTIVE = None
        return returncode
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

def status_pair():
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    for channel in (parent, child):
        if (
            channel.fileno() < 6
            or channel.family != socket.AF_UNIX
            or channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
            != socket.SOCK_STREAM
            or channel.getsockname() not in (None, "", b"")
            or channel.getpeername() not in (None, "", b"")
            or not channel.getblocking()
        ):
            raise RuntimeError("supervisor_status_channel")
    if os.fstat(parent.fileno())[:2] == os.fstat(child.fileno())[:2]:
        raise RuntimeError("supervisor_status_alias")
    return parent, child

def gate_pipe():
    reader, writer = os.pipe()
    reader_row = os.fstat(reader)
    writer_row = os.fstat(writer)
    reader_flags = fcntl.fcntl(reader, fcntl.F_GETFL)
    writer_flags = fcntl.fcntl(writer, fcntl.F_GETFL)
    if (
        reader < 6
        or writer < 6
        or reader == writer
        or not stat.S_ISFIFO(reader_row.st_mode)
        or not stat.S_ISFIFO(writer_row.st_mode)
        or reader_flags & os.O_ACCMODE != os.O_RDONLY
        or writer_flags & os.O_ACCMODE != os.O_WRONLY
        or reader_flags & os.O_NONBLOCK
        or writer_flags & os.O_NONBLOCK
    ):
        raise RuntimeError("supervisor_gate_channel")
    return reader, writer

def drain_payload_status(process, channel, control_descriptor):
    selector = selectors.DefaultSelector()
    raw = bytearray()
    eof = False
    try:
        channel.setblocking(False)
        selector.register(channel, selectors.EVENT_READ, "payload")
        selector.register(control_descriptor, selectors.EVENT_READ, "control")
        while not eof:
            events = selector.select(0.25)
            for key, mask in events:
                if not mask & selectors.EVENT_READ:
                    continue
                if key.data == "control":
                    try:
                        os.read(control_descriptor, 1)
                    except OSError:
                        pass
                    raise SupervisorSignal()
                try:
                    chunk = key.fileobj.recv(
                        min(65536, MAX_PAYLOAD_STATUS_BYTES + 1 - len(raw))
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    eof = True
                    selector.unregister(key.fileobj)
                else:
                    raw.extend(chunk)
                    if len(raw) > MAX_PAYLOAD_STATUS_BYTES:
                        raise RuntimeError("supervisor_payload_status")
        value = json.loads(bytes(raw))
        if type(value) is not dict or canonical(value) != bytes(raw):
            raise RuntimeError("supervisor_payload_status")
        return bytes(raw)
    finally:
        selector.close()

def identity(descriptor):
    duplicate = os.dup(descriptor)
    wrapper = socket.socket(fileno=duplicate)
    try:
        flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        row = os.fstat(descriptor)
        if (
            wrapper.family != socket.AF_UNIX
            or wrapper.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
            != socket.SOCK_STREAM
            or os.isatty(descriptor)
            or flags & os.O_ACCMODE != os.O_RDWR
            or flags & os.O_NONBLOCK
            or flags & getattr(os, "O_ASYNC", 0)
            or wrapper.getsockname() not in (None, "", b"")
            or wrapper.getpeername() not in (None, "", b"")
        ):
            raise RuntimeError("materialize_stdio_identity")
        return row.st_dev, row.st_ino
    finally:
        wrapper.close()

identities = tuple(identity(descriptor) for descriptor in (1, 2, 0))
if len(set(identities)) != 3:
    raise RuntimeError("materialize_stdio_alias")
for source, target in ((1, 3), (2, 4), (0, 5)):
    os.dup2(source, target, inheritable=True)
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
for signum in TERMINATION_SIGNALS:
    signal.signal(signum, on_signal)
returncode = 78
started = False
released = False
contained = False
failed = False
supervisor_pid = os.getpid()
payload_pgid = None
status_parent = None
status_child = None
gate_reader = None
gate_writer = None
payload_status = None
try:
    status_parent, status_child = status_pair()
    gate_reader, gate_writer = gate_pipe()
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, TERMINATION_SIGNALS)
    try:
        ACTIVE = subprocess.Popen(
            [
                "/usr/bin/python3",
                "-I",
                "-S",
                "-B",
                "-c",
                GATE_CODE,
                str(gate_reader),
                "/usr/bin/python3",
                "-I",
                "-S",
                "-B",
                "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-m1-materialize/materialize-root-program.py",
                "--materialize",
                "3",
                "4",
                str(status_child.fileno()),
                *sys.argv[1:],
            ],
            cwd="/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-m1-materialize",
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            pass_fds=(3, 4, status_child.fileno(), gate_reader),
            start_new_session=True,
            text=False,
            bufsize=0,
        )
        started = True
        payload_pgid = ACTIVE.pid
        if os.getpgid(payload_pgid) != payload_pgid:
            raise RuntimeError("supervisor_payload_group")
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    status_child.close()
    status_child = None
    os.close(gate_reader)
    gate_reader = None
    signal.alarm(ACK_TIMEOUT_SECONDS)
    emit(
        {
            "schema": SCHEMA,
            "status": "READY",
            "supervisor_pid": supervisor_pid,
            "payload_pgid": payload_pgid,
            "payload_release_count": 0,
            "payload_mode": "MATERIALIZE",
            "payload_program_sha256": "5d6ae172422b805fa2b358c605285a8056e37e492ce31fb2fdf724bc3047ec16",
            "pre_release_action_count": 0,
            "automatic_retry_count": 0,
            "cleanup_count": 0,
            "raw_value_emitted_count": 0,
        }
    )
    if os.read(5, 2) != b"A":
        raise RuntimeError("supervisor_ack")
    if os.write(gate_writer, b"G") != 1:
        raise RuntimeError("supervisor_gate_release")
    os.close(gate_writer)
    gate_writer = None
    released = True
    signal.alarm(RUNTIME_TIMEOUT_SECONDS)
    payload_status = drain_payload_status(ACTIVE, status_parent, 5)
    returncode = settle_active(False)
    contained = True
except BaseException:
    failed = True
    if ACTIVE is not None:
        try:
            returncode = settle_active(True)
            contained = True
        except BaseException:
            contained = False
finally:
    signal.alarm(0)
    for descriptor in (gate_reader, gate_writer):
        if descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException:
                pass
    for channel in (status_parent, status_child):
        if channel is not None:
            try:
                channel.close()
            except BaseException:
                pass
if contained or not started:
    if started and contained and payload_status is not None:
        emit_payload(payload_status)
    emit(
        {
            "schema": SCHEMA,
            "status": "PAYLOAD_GROUP_ABSENT",
            "payload_started": started,
            "payload_released": released,
            "supervisor_pid": supervisor_pid,
            "payload_pgid": payload_pgid,
            "payload_release_count": 1 if released else 0,
            "payload_mode": "MATERIALIZE",
            "payload_program_sha256": "5d6ae172422b805fa2b358c605285a8056e37e492ce31fb2fdf724bc3047ec16",
            "pre_release_action_count": 0,
            "payload_returncode": returncode,
            "group_absent": True,
            "automatic_retry_count": 0,
            "cleanup_count": 0,
            "raw_value_emitted_count": 0,
        }
    )
raise SystemExit(0 if started and contained and not failed and returncode == 0 else 78)
'''
MATERIALIZE_PUBLIC_PATHS = (
    "/Users/openclaw/Desktop/noteai/" + M1_RECEIPT_REF,
    "/Users/openclaw/Desktop/noteai/" + M1_EVIDENCE_REF,
)
MATERIALIZE_FORBIDDEN_PATH = (
    "/Users/openclaw/Desktop/noteai/" + M2_CHECKPOINT_REF
)
MATERIALIZE_SECRET_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b'"AccessKeySecret"',
    b'"SecurityToken"',
    b'"access_key_secret"',
    b'"security_token"',
)
CAPTURE_ROOT_SUCCESS_KEYS = frozenset(
    {
        "schema",
        "status",
        "logical_slot_count",
        "provider_dispatch_count",
        "maximum_provider_dispatches",
        "parallel_provider_dispatch_count",
        "finalize_call_count",
        "cloud_write_count",
        "database_connection_count",
        "private_key_read_count",
        "automatic_retry_count",
        "cleanup_count",
        "raw_value_emitted_count",
        "readiness_credit_added",
    }
)
MATERIALIZE_CHILD_SUCCESS_KEYS = frozenset(
    {
        "schema",
        "status",
        "receipt_build_count",
        "evidence_build_count",
        "checkpoint_build_count",
        "receipt_validation_count",
        "evidence_validation_count",
        "network_dispatch_count",
        "provider_dispatch_count",
        "database_connection_count",
        "database_transaction_count",
        "database_write_count",
        "private_key_read_count",
        "private_key_write_count",
        "private_key_output_count",
        "credential_configuration_count",
        "credential_refresh_count",
        "raw_value_emitted_count",
        "automatic_retry_count",
        "cleanup_count",
    }
)
MINIMUM_STS_VALIDITY_SECONDS = 16 * 60
INITIAL_MINIMUM_STS_VALIDITY_SECONDS = 31 * 60
MAXIMUM_STS_VALIDITY_SECONDS = 24 * 60 * 60
EXECUTION_ENABLED = False

CAPTURE_PAGE_SEQUENCE = (
    "collector_begin_success_observed",
    "adapter_child_spawned_exactly_once",
    "request_credential_feed_and_response_status_concurrent_drain",
    "child_exit_reap_and_process_group_absence_observed",
    "collector_finish_invoked_at_most_once_with_same_raw_response",
    "collector_finish_success_observed",
    "pagination_token_or_identifier_derived",
)
IDENTITY_DERIVATION_CONTRACT = {
    "schema": "noteai.item26.m1-in-memory-identity-derivation.v1",
    "derivation_after_finish_success_only": True,
    "cost_stop_slot": CAPTURE_SLOTS[0],
    "cost_stop_candidate_raw_values_all_equal": True,
    "cost_stop_candidate_old_clone_sha256": (
        "820121638125fcebe3b7c03f3416ddae1fef1a0a9f1de731320fa75dd69a1525"
    ),
    "clone_create_slot": CAPTURE_SLOTS[1],
    "clone_create_source_candidate_count": 1,
    "clone_create_source_sha256": (
        "d3712c09b28ee82257ab128fa1b5ba79b223f8b774e5fa20f761a2c4782eee8d"
    ),
    "candidate_raw_persistence_allowed": False,
    "candidate_raw_output_allowed": False,
    "extractor_ref": EXTRACTOR_REF,
    "extractor_file_sha256": FIXED_BINDINGS[EXTRACTOR_REF]["file_sha256"],
}
CAPTURE_AT_MOST_ONCE_FAILURE_MATRIX = {
    "before_begin": {
        "begin_success_count": 0,
        "child_spawn_count": 0,
        "finish_call_count": 0,
        "bridge_mark_unknown_maximum_count": 0,
        "automatic_retry_count": 0,
    },
    "begin_rejected": {
        "begin_success_count": 0,
        "child_spawn_count": 0,
        "finish_call_count": 0,
        "bridge_mark_unknown_maximum_count": 0,
        "automatic_retry_count": 0,
    },
    "begin_status_lost_after_single_invocation": {
        "begin_call_count": 1,
        "begin_success_observed_count": 0,
        "child_spawn_count": 0,
        "finish_call_count": 0,
        "bridge_mark_unknown_maximum_count": 0,
        "second_begin_call_allowed": False,
        "automatic_retry_count": 0,
    },
    "begin_committed_child_spawn_failed": {
        "begin_success_count": 1,
        "child_spawn_count": 0,
        "finish_call_count": 0,
        "bridge_mark_unknown_maximum_count": 1,
        "automatic_retry_count": 0,
    },
    "child_timeout_after_group_absence": {
        "begin_success_count": 1,
        "child_spawn_count": 1,
        "finish_call_count": 0,
        "bridge_mark_unknown_maximum_count": 1,
        "automatic_retry_count": 0,
    },
    "child_failure_without_process_group_absence_proof": {
        "begin_success_count": 1,
        "child_spawn_count": 1,
        "finish_call_count": 0,
        "bridge_mark_unknown_maximum_count": 0,
        "second_child_spawn_allowed": False,
        "automatic_retry_count": 0,
    },
    "child_status_lost_after_group_absence": {
        "begin_success_count": 1,
        "child_spawn_count": 1,
        "finish_call_count": 0,
        "bridge_mark_unknown_maximum_count": 1,
        "automatic_retry_count": 0,
        "second_child_spawn_allowed": False,
    },
    "child_fixed_failure_after_group_absence": {
        "begin_success_count": 1,
        "child_spawn_count": 1,
        "finish_call_count": 0,
        "bridge_mark_unknown_maximum_count": 1,
        "automatic_retry_count": 0,
    },
    "finish_records_unknown_and_raises": {
        "begin_success_count": 1,
        "child_spawn_count": 1,
        "finish_call_count": 1,
        "collector_unknown_count": 1,
        "bridge_mark_unknown_maximum_count": 0,
        "automatic_retry_count": 0,
    },
    "finish_other_failure_after_invocation": {
        "begin_success_count": 1,
        "child_spawn_count": 1,
        "finish_call_count": 1,
        "bridge_mark_unknown_maximum_count": 0,
        "automatic_retry_count": 0,
    },
    "finish_success_then_token_or_identity_failure": {
        "begin_success_count": 1,
        "child_spawn_count": 1,
        "finish_call_count": 1,
        "bridge_mark_unknown_maximum_count": 0,
        "next_begin_count": 0,
        "automatic_retry_count": 0,
    },
    "bridge_mark_unknown_status_lost_after_single_invocation": {
        "mark_unknown_call_count": 1,
        "bridge_mark_unknown_maximum_count": 1,
        "second_mark_unknown_call_allowed": False,
        "finish_call_count": 0,
        "automatic_retry_count": 0,
    },
    "finalize_failure": {
        "finalize_call_count": 1,
        "bridge_mark_unknown_maximum_count": 0,
        "automatic_retry_count": 0,
    },
    "finalize_status_lost_after_single_invocation": {
        "finalize_call_count": 1,
        "second_finalize_call_allowed": False,
        "bridge_mark_unknown_maximum_count": 0,
        "automatic_retry_count": 0,
    },
}

MATERIALIZE_AT_MOST_ONCE_FAILURE_MATRIX = {
    "root_status_lost": {
        "root_invocation_count": 1,
        "root_reinvoke_allowed": False,
        "receipt_write_count": 0,
        "evidence_write_count": 0,
        "automatic_retry_count": 0,
    },
    "receipt_output_missing_oversize_or_no_eof": {
        "root_invocation_count": 1,
        "root_reinvoke_allowed": False,
        "receipt_write_count": 0,
        "evidence_write_count": 0,
        "automatic_retry_count": 0,
    },
    "evidence_output_missing_oversize_or_no_eof": {
        "root_invocation_count": 1,
        "root_reinvoke_allowed": False,
        "receipt_write_count": 0,
        "evidence_write_count": 0,
        "automatic_retry_count": 0,
    },
    "outer_independent_validation_failure": {
        "root_invocation_count": 1,
        "root_reinvoke_allowed": False,
        "receipt_write_count": 0,
        "evidence_write_count": 0,
        "automatic_retry_count": 0,
    },
    "receipt_write_fsync_or_readback_failure": {
        "root_invocation_count": 1,
        "root_reinvoke_allowed": False,
        "receipt_write_maximum_count": 1,
        "evidence_write_count": 0,
        "automatic_retry_count": 0,
    },
    "evidence_write_fsync_or_readback_failure": {
        "root_invocation_count": 1,
        "root_reinvoke_allowed": False,
        "receipt_write_count": 1,
        "evidence_write_maximum_count": 1,
        "automatic_retry_count": 0,
    },
    "outer_success_status_lost_after_both_readbacks": {
        "root_invocation_count": 1,
        "root_reinvoke_allowed": False,
        "receipt_write_count": 1,
        "evidence_write_count": 1,
        "automatic_retry_count": 0,
    },
}

REPOSITORY_ROOT = "/Users/openclaw/Desktop/noteai"
REPOSITORY_OWNER_UID = 501
REPOSITORY_OWNER_GID = 20
REPOSITORY_METADATA_MAXIMUMS = {
    "HEAD": 4096,
    "index": 8 * 1024 * 1024,
    "config": 1024 * 1024,
}
SYSTEM_TOOL_BINDINGS = {
    "/usr/bin/git": {
        "sha256": (
            "179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818"
        ),
        "size": 118928,
        "mode": "0755",
        "uid": 0,
        "gid": 0,
        "nlink": 78,
        "symlink": False,
    },
    "/Library/Developer/CommandLineTools/usr/bin/git": {
        "sha256": (
            "3121e7e4d16059539731c58d94888709c12904abe922acde8e37caef4607c1d1"
        ),
        "size": 7604272,
        "mode": "0755",
        "uid": 0,
        "gid": 0,
        "nlink": 1,
        "symlink": False,
    },
    "/usr/bin/python3": {
        "sha256": (
            "179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818"
        ),
        "size": 118928,
        "mode": "0755",
        "uid": 0,
        "gid": 0,
        "nlink": 78,
        "symlink": False,
    },
    (
        "/Library/Developer/CommandLineTools/Library/Frameworks/"
        "Python3.framework/Versions/3.9/bin/python3.9"
    ): {
        "sha256": (
            "4b42b1a117605cafc8607b67b0892a609c2cd125012dd56288abeed8c89cdfb1"
        ),
        "size": 102352,
        "mode": "0755",
        "uid": 0,
        "gid": 0,
        "nlink": 1,
        "symlink": False,
    },
    "/usr/bin/openssl": {
        "sha256": (
            "517827f877751b6d7abebe404a296fa8e82425c63694a73ab06db35e6d9a8362"
        ),
        "size": 1134000,
        "mode": "0755",
        "uid": 0,
        "gid": 0,
        "nlink": 1,
        "symlink": False,
    },
    "/etc/ssl/cert.pem": {
        "sha256": (
            "9dae8d76e55cb08991f2b672d58999ea15560d910759c16b544f843bdffbb994"
        ),
        "size": 333483,
        "mode": "0644",
        "uid": 0,
        "gid": 0,
        "nlink": 1,
        "symlink": False,
    },
}
SYSTEM_TOOL_IDENTITY_CONTRACT = {
    "schema": "noteai.item26.m1-system-tool-identity.v1",
    "bindings": SYSTEM_TOOL_BINDINGS,
    "pre_post_inode_hash_size_mode_uid_gid_nlink_equal": True,
    "file_symlink_allowed": False,
    "parent_chain_root_owned_required": True,
    "parent_chain_group_or_world_write_allowed": False,
    "allowed_parent_symlinks": {"/etc": "private/etc"},
    "allowed_parent_symlink_pre_post_identity_required": True,
}
MATERIALIZE_PROCESS_ENV = {
    "PATH": "/usr/bin:/bin",
    "LC_ALL": "C",
    "LANG": "C",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_TERMINAL_PROMPT": "0",
}
OPENSSL_PROCESS_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"}
MATERIALIZE_GIT_CONTRACT = {
    "schema": "noteai.item26.m1-materialize-read-only-git.v1",
    "executable": "/usr/bin/git",
    "resolved_executable": "/Library/Developer/CommandLineTools/usr/bin/git",
    "cwd": REPOSITORY_ROOT,
    "fixed_prefix": [
        "/usr/bin/git",
        "-c",
        "safe.directory=" + REPOSITORY_ROOT,
        "--no-replace-objects",
    ],
    "allowed_argument_shapes": [
        ["show", "REVISION:REF"],
        ["rev-parse", "REVISION:REF"],
        ["cat-file", "-e", "REVISION_OR_REVISION:REF"],
        ["merge-base", "--is-ancestor", "REVISION", "REVISION"],
    ],
    "environment": MATERIALIZE_PROCESS_ENV,
    "stdin": "DEVNULL",
    "stderr": "DEVNULL",
    "network_subcommand_allowed": False,
    "write_subcommand_allowed": False,
    "promisor_remote_allowed": False,
    "partial_clone_extension_allowed": False,
    "partial_clone_filter_allowed": False,
    "required_objects_missing_allowed": False,
    "all_required_objects_cat_file_preflight": True,
    "authority_git_helper_exact_semantic_environment_adapter_required": True,
    "authority_git_helper_original_environment_allowed": False,
    "tool_identity_pre_post_required": True,
    "repository_identity_pre_post_required": True,
    "automatic_retry_count": 0,
}
AUTHORITY_GIT_PATCH_CONTRACT = {
    "schema": "noteai.item26.m1-authority-read-only-git-patch.v1",
    "required_in_capture": True,
    "required_in_materialize": True,
    "exact_source_ref": AUTHORITY_VERIFIER_REF,
    "exact_source_sha256": FIXED_BINDINGS[AUTHORITY_VERIFIER_REF][
        "file_sha256"
    ],
    "patch_target": "_git",
    "exact_argument_semantics_preserved": True,
    "exact_cwd_tool_repository_identity_semantics_preserved": True,
    "environment_additions_only": {
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0",
    },
    "local_object_preflight_before_patch_use": True,
    "promisor_remote_absence_required": True,
    "partial_clone_config_absence_required": True,
    "required_object_absence_fails_before_provider_child": True,
    "required_object_absence_provider_child_count": 0,
    "original_callable_invocation_count": 0,
    "automatic_retry_count": 0,
}
AUTHORITY_SIGNATURE_PATCH_CONTRACT = {
    "schema": "noteai.item26.m1-authority-signature-fd-patch.v1",
    "exact_source_ref": AUTHORITY_VERIFIER_REF,
    "exact_source_sha256": FIXED_BINDINGS[AUTHORITY_VERIFIER_REF][
        "file_sha256"
    ],
    "patch_target": "_verify_signature",
    "patch_signature": "(payload:bytes,signature:bytes,key:bytes)->bool",
    "patch_after_dynamic_guards": True,
    "patch_before_any_authority_validation": True,
    "original_callable_invocation_count": 0,
    "other_module_symbol_patch_count": 2,
    "other_module_symbol_patch_targets": ["_git", "_openssl"],
    "temporary_directory_create_count": 0,
    "semantic_parity_domain_message_signature_key_required": True,
    "semantic_parity_normal_and_optimized_tests_required": True,
}
ADAPTER_CHILD_STATUS_CONTRACT = {
    "schema": "noteai.item26.m1-adapter-child-status.v1",
    "canonical_ascii_json_required": True,
    "maximum_bytes": MAX_CHILD_STATUS_BYTES,
    "eof_required": True,
    "secret_free_fixed_codes_only": True,
    "success_status": "ONE_READ_DISPATCH_COMPLETED",
    "success_cloud_dispatch_count": 1,
    "success_cloud_write_count": 0,
    "success_automatic_retry_count": 0,
    "failure_cloud_dispatch_count": "ZERO_OR_ONE_FROM_TRANSPORT_ERROR_ONLY",
    "raw_value_emitted_count": 0,
    "status_loss_second_dispatch_allowed": False,
}
MATERIALIZE_STATUS_CONTRACT = {
    "schema": "noteai.item26.m1-materialize-child-status.v1",
    "canonical_ascii_json_required": True,
    "maximum_bytes": MAX_MATERIALIZE_STATUS_BYTES,
    "eof_required": True,
    "success_status": "RECEIPT_AND_EVIDENCE_BUILT_AND_VERIFIED",
    "receipt_build_count": 1,
    "evidence_build_count": 1,
    "checkpoint_build_count": 0,
    "network_dispatch_count": 0,
    "provider_dispatch_count": 0,
    "database_connection_count": 0,
    "automatic_retry_count": 0,
    "raw_value_emitted_count": 0,
}
CAPTURE_CHILD_IDENTITY_CONTRACT = {
    "schema": "noteai.item26.m1-capture-child-identity.v1",
    "adapter_binding": FIXED_BINDINGS[ADAPTER_REF],
    "python_launcher_binding": SYSTEM_TOOL_BINDINGS["/usr/bin/python3"],
    "python_executable_binding": SYSTEM_TOOL_BINDINGS[
        (
            "/Library/Developer/CommandLineTools/Library/Frameworks/"
            "Python3.framework/Versions/3.9/bin/python3.9"
        )
    ],
    "ca_path": "/etc/ssl/cert.pem",
    "ca_binding": SYSTEM_TOOL_BINDINGS["/etc/ssl/cert.pem"],
    "adapter_python_ca_pre_post_inode_hash_size_mode_equal": True,
    "credential_fd_pre_post_inode_size_mode_equal": True,
    "credential_envelope_sha256_memory_only": True,
    "credential_content_persisted_count": 0,
}
MATERIALIZE_ENTRYPOINT_CALL_CONTRACT = {
    "schema": "noteai.item26.m1-materialize-entrypoint-calls.v1",
    "builder_entrypoints": ["build_receipt", "build_evidence"],
    "root_verifier_entrypoints": ["validate_receipt", "validate_evidence"],
    "outer_verifier_entrypoints": ["validate_receipt", "validate_evidence"],
    "builder_call_count": 2,
    "root_receipt_validation_call_count": 3,
    "root_evidence_validation_call_count": 2,
    "outer_receipt_validation_call_count": 1,
    "outer_evidence_validation_call_count": 1,
    "global_receipt_validation_call_count": 4,
    "global_evidence_validation_call_count": 3,
    "root_validation_before_emit_required": True,
    "outer_validation_before_first_write_required": True,
    "builder_expected_control_revision": CONTROL_REVISION,
    "builder_root": REPOSITORY_ROOT,
    "builder_authority_directory": AUTHORITY_DIRECTORY,
    "builder_default_root_allowed": False,
    "checkpoint_entrypoint_call_count": 0,
    "network_dispatch_count": 0,
    "database_connection_count": 0,
}
GLOBAL_ZERO_ACTION_CONTRACT = {
    "schema": "noteai.item26.m1-source-capture-materialize-zero-actions.v1",
    "authorized_cny": "0.00",
    "incurred_cny": "0.00",
    "cloud_write_count": 0,
    "database_connection_count": 0,
    "database_transaction_count": 0,
    "database_write_count": 0,
    "private_key_read_count": 0,
    "private_key_write_count": 0,
    "private_key_output_count": 0,
    "oauth_configuration_count": 0,
    "oauth_refresh_count": 0,
    "materialize_provider_dispatch_count": 0,
}

SOURCE_SCHEMA = "noteai.item26.m1-capture-materializer-stager-source.v1"
SOURCE_ONLY_IMPLEMENTATION_STATUS = (
    "SOURCE_ONLY_IMPLEMENTATION_COMPLETE_NOT_AUTHORIZED"
)
SOURCE_ONLY_STATUS = {
    "schema": SOURCE_SCHEMA,
    "status": SOURCE_ONLY_IMPLEMENTATION_STATUS,
    "authorizes_future_execution": False,
    "implementation_complete": True,
    "operational_ready": False,
    "credential_interface_status": "NOT_PROVISIONED",
    "sudo_dispatch_count": 0,
    "root_write_count": 0,
    "oauth_configuration_count": 0,
    "credential_read_count": 0,
    "provider_dispatch_count": 0,
    "database_connection_count": 0,
    "capture_count": 0,
    "materialization_count": 0,
    "cleanup_count": 0,
    "automatic_retry_count": 0,
    "replay_count": 0,
    "readiness_credit_added": False,
    "authorized_cny": "0.00",
    "incurred_cny": "0.00",
    "cloud_write_count": 0,
    "database_transaction_count": 0,
    "database_write_count": 0,
    "private_key_read_count": 0,
    "private_key_write_count": 0,
    "private_key_output_count": 0,
    "oauth_refresh_count": 0,
    "materialize_provider_dispatch_count": 0,
    "zero_action_contract": GLOBAL_ZERO_ACTION_CONTRACT,
}

FUTURE_CAPTURE_CONTRACT = {
    "schema": "noteai.item26.m1-capture-root-contract.v1",
    "status": SOURCE_ONLY_IMPLEMENTATION_STATUS,
    "requires_new_cto_authorization": True,
    "scaffold_execution_enabled": EXECUTION_ENABLED,
    "implementation_complete": True,
    "operational_ready": False,
    "zero_action_contract": GLOBAL_ZERO_ACTION_CONTRACT,
    "collector_control_revision": CONTROL_REVISION,
    "logical_slots": list(CAPTURE_SLOTS),
    "logical_slot_operations": {
        slot: list(operation)
        for slot, operation in CAPTURE_SLOT_OPERATIONS.items()
    },
    "logical_slot_count": 5,
    "per_page_sequence": list(CAPTURE_PAGE_SEQUENCE),
    "begin_success_must_be_observed_before_child_spawn": True,
    "finish_receives_exact_adapter_raw_response_bytes": True,
    "token_or_identity_before_finish_success_allowed": False,
    "identity_derivation_contract": IDENTITY_DERIVATION_CONTRACT,
    "at_most_once_failure_matrix": CAPTURE_AT_MOST_ONCE_FAILURE_MATRIX,
    "maximum_provider_dispatches": MAX_PROVIDER_DISPATCHES,
    "maximum_begin_to_finish_seconds": MAX_RECORD_SECONDS,
    "full_capture_timeout_seconds": FULL_CAPTURE_TIMEOUT_SECONDS,
    "post_capture_identity_deadline_seconds": (
        POST_CAPTURE_IDENTITY_DEADLINE_SECONDS
    ),
    "post_capture_identity_maximum_file_reads": (
        POST_CAPTURE_MAX_FILE_READ_COUNT
    ),
    "post_capture_identity_process_spawn_count": 0,
    "adapter_child_wall_timeout_seconds": (
        ADAPTER_CHILD_WALL_TIMEOUT_SECONDS
    ),
    "maximum_active_adapter_children": MAX_ACTIVE_ADAPTER_CHILDREN,
    "parallel_provider_dispatch_count": PARALLEL_PROVIDER_DISPATCH_COUNT,
    "adapter_child_count_per_record": 1,
    "adapter_child_executable": "/usr/bin/python3",
    "adapter_child_isolated_flags": ["-I", "-S", "-B"],
    "adapter_child_core_limit_zero": True,
    "adapter_child_clean_environment_required": True,
    "adapter_child_new_process_group": True,
    "adapter_child_timeout_kill_scope": "PROCESS_GROUP",
    "adapter_child_timeout_signal": "SIGKILL",
    "adapter_child_wait_and_reap_required": True,
    "adapter_child_group_absence_proof_required": True,
    "anonymous_fd_channels": list(ADAPTER_FD_CHANNELS),
    "anonymous_fd_channel_count": 4,
    "anonymous_fd_transport": "AF_UNIX_SOCK_STREAM",
    "anonymous_fd_minimum_number": 3,
    "anonymous_fd_unique_open_file_descriptions_required": True,
    "anonymous_fd_non_tty_required": True,
    "anonymous_fd_f_getfl_direction_preflight_required": True,
    "anonymous_fd_blocking_required": True,
    "anonymous_fd_access_mode_required": "O_RDWR",
    "anonymous_fd_async_flag_allowed": False,
    "anonymous_fd_directions": {
        "logical_request": "CHILD_READ_PARENT_WRITE",
        "temporary_sts": "CHILD_READ_PARENT_WRITE",
        "raw_response": "CHILD_WRITE_PARENT_READ",
        "fixed_status": "CHILD_WRITE_PARENT_READ",
    },
    "child_close_fds": True,
    "child_pass_fds_exactly": list(ADAPTER_FD_CHANNELS),
    "child_core_limit_and_clean_environment_before_fd_read": True,
    "request_parent_shutdown_write_after_exact_bytes": True,
    "credential_parent_shutdown_write_after_exact_bytes": True,
    "response_child_shutdown_write_required": True,
    "status_child_shutdown_write_required": True,
    "response_parent_drain_to_eof_required": True,
    "status_parent_drain_to_eof_required": True,
    "maximum_response_bytes": MAX_ADAPTER_RESPONSE_BYTES,
    "maximum_status_bytes": MAX_CHILD_STATUS_BYTES,
    "child_stdout": "DEVNULL",
    "child_stderr": "DEVNULL",
    "child_status_contract": ADAPTER_CHILD_STATUS_CONTRACT,
    "child_identity_contract": CAPTURE_CHILD_IDENTITY_CONTRACT,
    "authority_git_patch_contract": AUTHORITY_GIT_PATCH_CONTRACT,
    "authority_git_patch_before_collector_load_or_use": True,
    "parent_concurrent_feed_response_status_drain_required": True,
    "second_provider_dispatch_during_drain_allowed": False,
    "raw_request_allowed_channels": ["logical_request"],
    "raw_credential_allowed_channels": ["temporary_sts"],
    "raw_response_allowed_channels": ["raw_response"],
    "status_channel_fixed_secret_free_only": True,
    "raw_in_argv_allowed": False,
    "raw_in_environment_allowed": False,
    "raw_in_regular_file_allowed": False,
    "raw_in_stdout_allowed": False,
    "raw_in_stderr_allowed": False,
    "pagination_token_cycle_rejected": True,
    "pagination_tokens_memory_only": True,
    "global_record_limit_includes_all_pages": True,
    "slot_order_is_fixed": True,
    "identifier_derivation_in_memory_only": True,
    "identifier_hash_binding_required": True,
    "identifier_extractor_parity_required": True,
    "identifier_extractor_ref": EXTRACTOR_REF,
    "collector_finish_may_create_unknown": True,
    "collector_finish_unknown_excludes_bridge_mark_unknown": True,
    "bridge_mark_unknown_maximum_count": 1,
    "bridge_mark_unknown_requires_future_explicit_authorization": True,
    "bridge_mark_unknown_requires_process_group_absent": True,
    "bridge_mark_unknown_requires_begin_committed": True,
    "bridge_mark_unknown_requires_finish_not_invoked": True,
    "bridge_mark_unknown_requires_no_existing_unknown": True,
    "bridge_mark_unknown_without_all_conditions_allowed": False,
    "credential_interface_status": "NOT_PROVISIONED",
    "credential_source": "ROOT_CUSTODY_PROJECTED_TEMPORARY_STS_ONLY",
    "credential_capsule_fixed_binding": dict(C1_CAPSULE_FIXED_BINDING),
    "credential_capsule_handshake_schema": C1_HANDSHAKE_SCHEMA,
    "credential_capsule_ready_status": C1_READY_STATUS,
    "credential_capsule_ack_status": C1_ACK_STATUS,
    "credential_capsule_handshake_timeout_seconds": (
        CAPTURE_C1_HANDSHAKE_TIMEOUT_SECONDS
    ),
    "credential_capsule_single_root_session_required": True,
    "credential_capsule_opaque_receipts_required": True,
    "credential_capsule_ready_ack_channels": 2,
    "credential_capsule_ready_ack_independent_anonymous_streams": True,
    "credential_reader_uid": 0,
    "credential_minimum_remaining_validity_seconds": (
        MINIMUM_STS_VALIDITY_SECONDS
    ),
    "credential_initial_minimum_validity_seconds": (
        INITIAL_MINIMUM_STS_VALIDITY_SECONDS
    ),
    "credential_validity_checked_before_first_begin": True,
    "credential_validity_checked_before_every_begin": True,
    "credential_below_per_dispatch_minimum_begin_count": 0,
    "credential_refresh_allowed": False,
    "oauth_configure_allowed": False,
    "oauth_access_or_refresh_token_ingress_allowed": False,
    "default_user_config_read_allowed": False,
    "provider_account_binding_required": True,
    "provider_account_binding_raw_persistence_allowed": False,
    "capture_runtime_directory": CAPTURE_RUNTIME_DIRECTORY,
    "capture_runtime_directory_mode": ROOT_RUNTIME_DIRECTORY_MODE,
    "capture_runtime_inventory": CAPTURE_RUNTIME_INVENTORY,
    "capture_runtime_manifest_spec": CAPTURE_RUNTIME_MANIFEST_SPEC,
    "capture_dependency_allowlist": list(CAPTURE_DEPENDENCY_ALLOWLIST),
    "capture_dependency_locations": CAPTURE_DEPENDENCY_LOCATIONS,
    "existing_runtime_read_only_inventory": list(EXISTING_RUNTIME_INVENTORY),
    "existing_runtime_file_bindings": {
        name: EXISTING_PUBLIC_FILE_BINDINGS[name]
        for name in EXISTING_RUNTIME_INVENTORY
    },
    "existing_inventory_snapshot_contract": (
        EXISTING_INVENTORY_SNAPSHOT_CONTRACT
    ),
    "existing_partition_stage_write_count": 0,
    "existing_runtime_inventory_drift_allowed": False,
    "existing_custody_inventory_drift_allowed": False,
    "public_m1_output_create_count": 0,
    "finalize_required_count_after_all_terminal": 1,
    "automatic_retry_allowed": False,
    "historical_replay_allowed": False,
    "cleanup_allowed": False,
    "failure_residue_preserved": True,
}

FUTURE_MATERIALIZE_CONTRACT = {
    "schema": "noteai.item26.m1-materialize-root-contract.v1",
    "status": SOURCE_ONLY_IMPLEMENTATION_STATUS,
    "requires_new_cto_authorization": True,
    "scaffold_execution_enabled": EXECUTION_ENABLED,
    "implementation_complete": True,
    "operational_ready": False,
    "zero_action_contract": GLOBAL_ZERO_ACTION_CONTRACT,
    "requires_finalized_root_capture": True,
    "at_most_once_failure_matrix": MATERIALIZE_AT_MOST_ONCE_FAILURE_MATRIX,
    "required_final_authority_inventory": list(
        CAPTURE_FINAL_AUTHORITY_INVENTORY
    ),
    "required_collector_status": "CAPTURE_INSTALLED",
    "capture_or_provider_dispatch_allowed": False,
    "public_artifact_refs": [M1_RECEIPT_REF, M1_EVIDENCE_REF],
    "public_artifact_count": 2,
    "terminal_checkpoint_ref": M2_CHECKPOINT_REF,
    "terminal_checkpoint_must_remain_absent": True,
    "terminal_checkpoint_create_allowed": False,
    "outer_precreates_exclusive_files": True,
    "outer_open_flags": ["O_EXCL", "O_NOFOLLOW", "O_RDWR"],
    "outer_output_mode": "0600",
    "outer_precreates_both_before_root_dispatch": True,
    "outer_holds_output_file_descriptors": True,
    "outer_output_parent_identity_required": True,
    "outer_output_inode_identity_required": True,
    "outer_output_alias_rejected": True,
    "outer_output_nlink_required": 1,
    "outer_fsync_before_and_after_write": True,
    "outer_parent_directory_fsync_required": True,
    "outer_readback_exact_bytes_required": True,
    "root_output_anonymous_fd_only": True,
    "root_output_fd_channels": ["receipt", "evidence", "fixed_status"],
    "root_output_fd_count": 3,
    "root_output_fd_transport": "AF_UNIX_SOCK_STREAM",
    "root_output_child_fd_identity_preflight_required": True,
    "root_output_fd_unique_open_file_descriptions_required": True,
    "root_output_fd_non_tty_required": True,
    "root_output_fd_blocking_required": True,
    "root_output_fd_access_mode_required": "O_RDWR",
    "root_output_fd_async_flag_allowed": False,
    "root_output_fd_f_getfl_direction_preflight_required": True,
    "root_output_fd_directions": {
        "receipt": "CHILD_WRITE_PARENT_READ",
        "evidence": "CHILD_WRITE_PARENT_READ",
        "fixed_status": "CHILD_WRITE_PARENT_READ",
    },
    "root_output_child_shutdown_write_required": True,
    "root_output_concurrent_drain_required": True,
    "root_output_limits": {
        "receipt": MAX_MATERIALIZE_RECEIPT_BYTES,
        "evidence": MAX_MATERIALIZE_EVIDENCE_BYTES,
        "fixed_status": MAX_MATERIALIZE_STATUS_BYTES,
    },
    "root_output_each_requires_eof": True,
    "root_fixed_status_contract": MATERIALIZE_STATUS_CONTRACT,
    "root_output_bundle_artifacts_exactly": ["receipt", "evidence"],
    "materialize_runtime_directory": MATERIALIZE_RUNTIME_DIRECTORY,
    "materialize_runtime_directory_mode": ROOT_RUNTIME_DIRECTORY_MODE,
    "materialize_runtime_inventory": MATERIALIZE_RUNTIME_INVENTORY,
    "materialize_runtime_manifest_spec": MATERIALIZE_RUNTIME_MANIFEST_SPEC,
    "materialize_dependency_allowlist": list(
        MATERIALIZE_DEPENDENCY_ALLOWLIST
    ),
    "materialize_dependency_locations": MATERIALIZE_DEPENDENCY_LOCATIONS,
    "dynamic_network_guard_required": True,
    "dynamic_subprocess_guard_required": True,
    "dynamic_guards_installed_before_module_load": True,
    "materialize_process_cwd_fixed_before_dynamic_load": (
        MATERIALIZE_RUNTIME_DIRECTORY
    ),
    "network_audit_events_denied": [
        "socket.__new__",
        "socket.connect",
        "socket.getaddrinfo",
    ],
    "process_audit_events_denied": [
        "os.exec",
        "os.fork",
        "os.system",
        "os.posix_spawn",
        "subprocess.Popen",
    ],
    "process_guard_exact_executable_exceptions": [
        "/usr/bin/git",
        "/usr/bin/openssl",
    ],
    "process_guard_all_other_executables_denied": True,
    "process_guard_git_contract": MATERIALIZE_GIT_CONTRACT,
    "process_guard_openssl_fd_only_signature_verification": True,
    "builder_ref": BUILDER_REF,
    "verifier_ref": EVIDENCE_VERIFIER_REF,
    "builder_allowed_entrypoints": ["build_receipt", "build_evidence"],
    "verifier_allowed_entrypoints": ["validate_receipt", "validate_evidence"],
    "checkpoint_builder_entrypoint_allowed": False,
    "authority_verifier_ref_exact_source_load_required": True,
    "authority_signature_patch_contract": AUTHORITY_SIGNATURE_PATCH_CONTRACT,
    "authority_git_patch_contract": AUTHORITY_GIT_PATCH_CONTRACT,
    "authority_original_signature_callable_allowed": False,
    "entrypoint_call_contract": MATERIALIZE_ENTRYPOINT_CALL_CONTRACT,
    "network_path_present": False,
    "provider_transport_present": False,
    "oauth_path_present": False,
    "database_path_present": False,
    "automatic_retry_allowed": False,
    "overwrite_allowed": False,
    "cleanup_allowed": False,
    "failure_residue_preserved": True,
    "empty_or_partial_output_residue_preserved": True,
    "first_output_preserved_if_second_precreate_fails": True,
    "output_pair_cleanup_allowed": False,
    "drain_validate_write_order": [
        "concurrently_drain_receipt_evidence_status_to_eof",
        "validate_fixed_status_and_independent_size_limits",
        "validate_receipt_and_evidence_in_memory",
        "write_fsync_readback_receipt",
        "write_fsync_readback_evidence",
        "fsync_both_files_and_parent_directories",
    ],
    "receipt_write_failure_prevents_evidence_write": True,
    "readiness_credit_added": False,
}

FD_ONLY_AUTHORITY_VERIFIER_CONTRACT = {
    "schema": "noteai.item26.m1-fd-only-authority-verifier-contract.v1",
    "status": SOURCE_ONLY_IMPLEMENTATION_STATUS,
    "requires_new_cto_authorization": True,
    "implementation_complete": True,
    "operational_ready": False,
    "replacement_required_in_capture": True,
    "replacement_required_in_materialize": True,
    "legacy_tempfile_signature_path_allowed": False,
    "temporary_directory_create_count": 0,
    "regular_file_create_count": 0,
    "openssl_executable": "/usr/bin/openssl",
    "openssl_processes_per_role_signature": 1,
    "fd_channels": ["public_key", "signature", "message", "fixed_status"],
    "fd_channel_count": 4,
    "fd_transport": "ANONYMOUS_PIPE",
    "fd_minimum_number": 3,
    "fd_unique_open_file_descriptions_required": True,
    "fd_non_tty_required": True,
    "fd_f_getfl_direction_preflight_required": True,
    "fd_directions": {
        "public_key": "PIPE_CHILD_READ_PARENT_WRITE",
        "signature": "PIPE_CHILD_READ_PARENT_WRITE",
        "message": "PIPE_CHILD_READ_PARENT_WRITE",
        "fixed_status": "PIPE_CHILD_WRITE_PARENT_READ",
    },
    "close_fds": True,
    "pass_fds_exactly": ["public_key", "signature", "message"],
    "fixed_status_mapped_to_child_stdout": True,
    "core_limit_and_clean_environment_before_fd_read": True,
    "public_key_channel": "ANONYMOUS_PIPE_FD",
    "signature_channel": "ANONYMOUS_PIPE_FD",
    "message_channel": "ANONYMOUS_PIPE_FD",
    "result_channel": "ANONYMOUS_PIPE_FD_FIXED_STATUS",
    "argv_material": "FD_NUMBERS_ONLY",
    "environment_material_allowed": False,
    "stdout_material_allowed": False,
    "stderr_material_allowed": False,
    "domain_message_signature_key_semantic_parity_required": True,
    "exact_equivalence_tests_required": True,
}

ROOT_PARTITION_CONTRACT = {
    "schema": "noteai.item26.m1-root-partition-contract.v1",
    "status": SOURCE_ONLY_IMPLEMENTATION_STATUS,
    "requires_new_cto_authorization": True,
    "scaffold_execution_enabled": EXECUTION_ENABLED,
    "implementation_complete": True,
    "operational_ready": False,
    "existing_partitions": EXISTING_ROOT_PARTITIONS,
    "new_partitions": NEW_ROOT_PARTITIONS,
    "new_partitions_are_siblings": True,
    "new_partitions_are_disjoint": True,
    "new_partition_mode": ROOT_RUNTIME_DIRECTORY_MODE,
    "new_partition_uid": 0,
    "new_partition_gid": 0,
    "mkdir_without_parents": True,
    "file_create_semantics": "O_EXCL_O_NOFOLLOW",
    "rollback_allowed": False,
    "cleanup_allowed": False,
    "failure_residue_preserved": True,
    "existing_partition_stage_write_count": 0,
    "existing_partition_inventory_drift_allowed": False,
    "noteai_parent_stable_identity_fields": [
        "st_dev",
        "st_ino",
        "st_mode",
        "st_uid",
        "st_gid",
    ],
    "noteai_parent_expected_direct_child_create_count": 2,
    "noteai_parent_nlink_mtime_ctime_change_allowed_for_direct_child_mkdirs": True,
    "noteai_parent_other_identity_drift_allowed": False,
}


class StagerError(ValueError):
    """A fixed, non-sensitive source-checkpoint error code."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )


def _materialize_build_and_validate_once(
    builder: Any,
    verifier: Any,
    *,
    expected_control_revision: str,
    root: Any,
    authority_directory: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        expected_control_revision != CONTROL_REVISION
        or str(root) != REPOSITORY_ROOT
        or str(authority_directory) != AUTHORITY_DIRECTORY
    ):
        raise StagerError("materialize_explicit_context")
    build_receipt = getattr(builder, "build_receipt", None)
    build_evidence = getattr(builder, "build_evidence", None)
    validate_receipt = getattr(verifier, "validate_receipt", None)
    validate_evidence = getattr(verifier, "validate_evidence", None)
    if not all(
        callable(value)
        for value in (
            build_receipt,
            build_evidence,
            validate_receipt,
            validate_evidence,
        )
    ):
        raise StagerError("materialize_entrypoints")
    receipt = build_receipt(
        expected_control_revision=expected_control_revision,
        root=root,
        authority_directory=authority_directory,
    )
    evidence = build_evidence(
        receipt,
        expected_control_revision=expected_control_revision,
        root=root,
        authority_directory=authority_directory,
    )
    receipt_errors, acceptance = validate_receipt(
        receipt,
        expected_control_revision=expected_control_revision,
    )
    if receipt_errors or type(acceptance) is not str or not acceptance:
        raise StagerError("materialize_receipt_validation")
    evidence_errors = validate_evidence(
        evidence,
        receipt,
        canonical_bytes(receipt),
        expected_control_revision=expected_control_revision,
    )
    if evidence_errors:
        raise StagerError("materialize_evidence_validation")
    if type(receipt) is not dict or type(evidence) is not dict:
        raise StagerError("materialize_artifact_shape")
    return receipt, evidence


def _materialize_independent_validate_once(
    verifier: Any,
    receipt: Any,
    evidence: Any,
    *,
    expected_control_revision: str,
) -> None:
    validate_receipt = getattr(verifier, "validate_receipt", None)
    validate_evidence = getattr(verifier, "validate_evidence", None)
    if not callable(validate_receipt) or not callable(validate_evidence):
        raise StagerError("materialize_entrypoints")
    receipt_errors, acceptance = validate_receipt(
        receipt,
        expected_control_revision=expected_control_revision,
    )
    if receipt_errors or type(acceptance) is not str or not acceptance:
        raise StagerError("materialize_receipt_validation")
    evidence_errors = validate_evidence(
        evidence,
        receipt,
        canonical_bytes(receipt),
        expected_control_revision=expected_control_revision,
    )
    if evidence_errors:
        raise StagerError("materialize_evidence_validation")


def _safe_process_token(value: Any) -> bool:
    return (
        type(value) is str
        and bool(value)
        and "\0" not in value
        and "\n" not in value
        and "\r" not in value
    )


def _materialize_git_tail_allowed(arguments: Any) -> bool:
    if type(arguments) is not list or not all(
        _safe_process_token(value) for value in arguments
    ):
        return False
    if len(arguments) == 2 and arguments[0] in {"show", "rev-parse"}:
        return not arguments[1].startswith("-")
    if (
        len(arguments) == 3
        and arguments[:2] == ["cat-file", "-e"]
    ):
        return not arguments[2].startswith("-")
    if (
        len(arguments) == 4
        and arguments[:2] == ["merge-base", "--is-ancestor"]
    ):
        return not arguments[2].startswith("-") and not arguments[3].startswith(
            "-"
        )
    return False


def _fd_path_number(value: Any) -> Optional[int]:
    prefix = "/dev/fd/"
    if type(value) is not str or not value.startswith(prefix):
        return None
    raw = value[len(prefix) :]
    if (
        not 1 <= len(raw) <= 10
        or not raw.isascii()
        or not raw.isdigit()
        or raw != str(int(raw))
    ):
        return None
    number = int(raw)
    return number if number >= 3 else None


def _materialize_openssl_arguments_allowed(arguments: Any) -> bool:
    if arguments in (
        ["/usr/bin/openssl", "pkey", "-pubin", "-pubout"],
        [
            "/usr/bin/openssl",
            "pkey",
            "-pubin",
            "-inform",
            "PEM",
            "-outform",
            "DER",
        ],
    ):
        return True
    if (
        type(arguments) is not list
        or len(arguments) != 8
        or arguments[:4] != [
            "/usr/bin/openssl",
            "dgst",
            "-sha256",
            "-verify",
        ]
        or arguments[5] != "-signature"
    ):
        return False
    numbers = (
        _fd_path_number(arguments[4]),
        _fd_path_number(arguments[6]),
        _fd_path_number(arguments[7]),
    )
    return None not in numbers and len(set(numbers)) == 3


def _materialize_process_allowed(
    executable: Any,
    arguments: Any,
    environment: Any,
    cwd: Any,
    *,
    parent_cwd_verified: bool = False,
) -> bool:
    if executable == "/usr/bin/git":
        prefix = MATERIALIZE_GIT_CONTRACT["fixed_prefix"]
        return (
            type(arguments) is list
            and arguments[: len(prefix)] == prefix
            and _materialize_git_tail_allowed(arguments[len(prefix) :])
            and environment == MATERIALIZE_PROCESS_ENV
            and cwd == REPOSITORY_ROOT
        )
    if executable == "/usr/bin/openssl":
        return (
            _materialize_openssl_arguments_allowed(arguments)
            and environment == OPENSSL_PROCESS_ENV
            and (
                cwd == MATERIALIZE_RUNTIME_DIRECTORY
                or (cwd is None and parent_cwd_verified is True)
            )
        )
    return False


def _materialize_audit_event_allowed(
    event: Any,
    executable: Any = None,
    arguments: Any = None,
    environment: Any = None,
    cwd: Any = None,
    *,
    parent_cwd_verified: bool = False,
) -> bool:
    if type(event) is not str or not event:
        return False
    if event.startswith("socket."):
        return False
    if event in {"os.fork", "os.system"}:
        return False
    if event in {"os.exec", "os.posix_spawn", "subprocess.Popen"}:
        return _materialize_process_allowed(
            executable,
            arguments,
            environment,
            cwd,
            parent_cwd_verified=parent_cwd_verified,
        )
    return True


def _execution_gate() -> None:
    if EXECUTION_ENABLED is not True:
        raise StagerError("future_execution_disabled")


def _hex_text(value: Any, width: int) -> bool:
    return (
        type(value) is str
        and len(value) == width
        and not (set(value) - set("0123456789abcdef"))
    )


def _sha256_bytes(raw: bytes) -> str:
    if type(raw) is not bytes:
        raise StagerError("stage_bytes")
    return hashlib.sha256(raw).hexdigest()


def _git_blob_oid_bytes(raw: bytes) -> str:
    if type(raw) is not bytes:
        raise StagerError("stage_bytes")
    prefix = b"blob " + str(len(raw)).encode("ascii") + b"\0"
    return hashlib.sha1(prefix + raw).hexdigest()


def _read_regular_nofollow(
    path: str,
    expected_row: Any,
    maximum: int,
    *,
    opener: Any = os.open,
    fstater: Any = os.fstat,
    reader: Any = os.read,
    closer: Any = os.close,
) -> bytes:
    if type(path) is not str or type(maximum) is not int or maximum < 0:
        raise StagerError("stage_safe_read")
    try:
        descriptor = opener(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise StagerError("stage_safe_read") from exc
    try:
        before = fstater(descriptor)
        expected = (
            expected_row.st_dev,
            expected_row.st_ino,
            expected_row.st_size,
            expected_row.st_mode,
            expected_row.st_uid,
            expected_row.st_gid,
            expected_row.st_nlink,
            expected_row.st_mtime_ns,
            expected_row.st_ctime_ns,
        )
        observed = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_nlink,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        if observed != expected or before.st_size > maximum:
            raise StagerError("stage_safe_read")
        raw = bytearray()
        while len(raw) <= maximum:
            chunk = reader(descriptor, maximum + 1 - len(raw))
            if not chunk:
                break
            raw.extend(chunk)
        after = fstater(descriptor)
        stable = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mode,
            after.st_uid,
            after.st_gid,
            after.st_nlink,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if len(raw) > maximum or stable != observed:
            raise StagerError("stage_safe_read")
        return bytes(raw)
    except OSError as exc:
        raise StagerError("stage_safe_read") from exc
    finally:
        closer(descriptor)


def _extract_ascii_literal(source: bytes, name: str) -> bytes:
    if type(source) is not bytes or type(name) is not str or not name:
        raise StagerError("stage_literal")
    try:
        tree = ast.parse(source.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError, ValueError) as exc:
        raise StagerError("stage_literal") from exc
    values: list[Any] = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            try:
                values.append(ast.literal_eval(node.value))
            except (SyntaxError, TypeError, ValueError) as exc:
                raise StagerError("stage_literal") from exc
    if len(values) != 1 or type(values[0]) is not str:
        raise StagerError("stage_literal")
    try:
        return values[0].encode("ascii")
    except UnicodeEncodeError as exc:
        raise StagerError("stage_literal") from exc


def _validate_future_topology(
    snapshot: Any,
    source_revision: str,
    acceptance_revision: str,
) -> None:
    if (
        not _hex_text(source_revision, 40)
        or not _hex_text(acceptance_revision, 40)
        or len({BASE_REVISION, source_revision, acceptance_revision}) != 3
        or type(snapshot) is not dict
        or set(snapshot)
        != {
            "parents",
            "base_to_source_paths",
            "source_to_acceptance_paths",
            "head_revision",
            "upstream_revision",
            "origin_main_revision",
            "tracked_changes",
        }
        or snapshot["parents"]
        != {
            source_revision: [BASE_REVISION],
            acceptance_revision: [source_revision],
        }
        or snapshot["base_to_source_paths"] != sorted(SOURCE_REFS)
        or snapshot["source_to_acceptance_paths"]
        != sorted(ACCEPTANCE_REFS)
        or snapshot["head_revision"] != acceptance_revision
        or snapshot["upstream_revision"] != acceptance_revision
        or snapshot["origin_main_revision"] != acceptance_revision
        or snapshot["tracked_changes"] != []
    ):
        raise StagerError("stage_topology")


def _read_git_identity(
    git_reader: Any,
    revision: str,
    ref: str,
) -> tuple[bytes, dict[str, Any]]:
    if not callable(git_reader) or not _hex_text(revision, 40):
        raise StagerError("stage_git_reader")
    value = git_reader(revision, ref)
    if type(value) is not dict or set(value) != {"raw", "git_blob_oid"}:
        raise StagerError("stage_git_reader")
    raw = value["raw"]
    oid = value["git_blob_oid"]
    if (
        type(raw) is not bytes
        or not raw
        or not _hex_text(oid, 40)
        or _git_blob_oid_bytes(raw) != oid
    ):
        raise StagerError("stage_git_identity")
    return raw, {
        "revision": revision,
        "ref": ref,
        "byte_count": len(raw),
        "sha256": _sha256_bytes(raw),
        "git_blob_oid": oid,
    }


def _future_result_path(acceptance_revision: str) -> str:
    if not _hex_text(acceptance_revision, 40):
        raise StagerError("stage_acceptance_revision")
    return str(Path(REPOSITORY_ROOT) / (STAGE_RESULT_PREFIX + acceptance_revision + ".json"))


def _stage_system_tool_snapshot(
    *,
    lstater: Any = os.lstat,
    reader: Any = _read_regular_nofollow,
    readlinker: Any = os.readlink,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    allowed_symlinks = {"/etc": "private/etc"}
    for path, expected in sorted(STAGE_SYSTEM_TOOL_BINDINGS.items()):
        row = lstater(path)
        if (
            not stat.S_ISREG(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or row.st_size != expected["size"]
            or format(stat.S_IMODE(row.st_mode), "04o") != expected["mode"]
            or row.st_uid != expected["uid"]
            or row.st_gid != expected["gid"]
            or row.st_nlink != expected["nlink"]
        ):
            raise StagerError("stage_system_tool")
        digest = None
        if expected["content_read_allowed"]:
            raw = reader(path, row, row.st_size)
            digest = _sha256_bytes(raw)
            if digest != expected["sha256"]:
                raise StagerError("stage_system_tool")
        parents = []
        for parent in Path(path).parents:
            parent_row = lstater(str(parent))
            if stat.S_ISLNK(parent_row.st_mode):
                target = readlinker(str(parent))
                if (
                    allowed_symlinks.get(str(parent)) != target
                    or parent_row.st_uid != 0
                ):
                    raise StagerError("stage_system_parent")
                kind = ["symlink", target]
            else:
                if (
                    not stat.S_ISDIR(parent_row.st_mode)
                    or parent_row.st_uid != 0
                    or stat.S_IMODE(parent_row.st_mode) & 0o022
                ):
                    raise StagerError("stage_system_parent")
                kind = ["directory", ""]
            parents.append(
                [
                    str(parent),
                    *kind,
                    parent_row.st_dev,
                    parent_row.st_ino,
                    parent_row.st_mode,
                    parent_row.st_uid,
                    parent_row.st_gid,
                    parent_row.st_nlink,
                    parent_row.st_mtime_ns,
                    parent_row.st_ctime_ns,
                ]
            )
        snapshot[path] = {
            "kind": "regular",
            "file": [
                row.st_dev,
                row.st_ino,
                row.st_size,
                row.st_mode,
                row.st_uid,
                row.st_gid,
                row.st_nlink,
                row.st_mtime_ns,
                row.st_ctime_ns,
                digest,
            ],
            "parents": parents,
        }
    for path, expected_target in sorted(STAGE_SYSTEM_SYMLINK_BINDINGS.items()):
        row = lstater(path)
        target = readlinker(path)
        if (
            not stat.S_ISLNK(row.st_mode)
            or row.st_uid != 0
            or row.st_gid != 0
            or row.st_nlink != 1
            or target != expected_target
        ):
            raise StagerError("stage_system_tool")
        parents = []
        for parent in Path(path).parents:
            parent_row = lstater(str(parent))
            if stat.S_ISLNK(parent_row.st_mode):
                parent_target = readlinker(str(parent))
                if (
                    allowed_symlinks.get(str(parent)) != parent_target
                    or parent_row.st_uid != 0
                ):
                    raise StagerError("stage_system_parent")
                kind = ["symlink", parent_target]
            else:
                if (
                    not stat.S_ISDIR(parent_row.st_mode)
                    or parent_row.st_uid != 0
                    or stat.S_IMODE(parent_row.st_mode) & 0o022
                ):
                    raise StagerError("stage_system_parent")
                kind = ["directory", ""]
            parents.append(
                [
                    str(parent),
                    *kind,
                    parent_row.st_dev,
                    parent_row.st_ino,
                    parent_row.st_mode,
                    parent_row.st_uid,
                    parent_row.st_gid,
                    parent_row.st_nlink,
                    parent_row.st_mtime_ns,
                    parent_row.st_ctime_ns,
                ]
            )
        snapshot[path] = {
            "kind": "symlink",
            "file": [
                row.st_dev,
                row.st_ino,
                row.st_size,
                row.st_mode,
                row.st_uid,
                row.st_gid,
                row.st_nlink,
                row.st_mtime_ns,
                row.st_ctime_ns,
                target,
            ],
            "parents": parents,
        }
    return snapshot


def _stage_repository_snapshot(
    *,
    lstater: Any = os.lstat,
    reader: Any = _read_regular_nofollow,
) -> dict[str, Any]:
    root = REPOSITORY_ROOT
    paths = [root, root + "/.git", root + "/.git/objects", root + "/.git/objects/info"]
    rows = {}
    owner = None
    for path in paths:
        row = lstater(path)
        if (
            not stat.S_ISDIR(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or stat.S_IMODE(row.st_mode) & 0o022
            or row.st_uid == 0
        ):
            raise StagerError("stage_repository")
        if owner is None:
            owner = (row.st_uid, row.st_gid)
        elif (row.st_uid, row.st_gid) != owner:
            raise StagerError("stage_repository")
        rows[path] = [
            row.st_dev,
            row.st_ino,
            row.st_mode,
            row.st_uid,
            row.st_gid,
            row.st_nlink,
        ]
    if owner != (REPOSITORY_OWNER_UID, REPOSITORY_OWNER_GID):
        raise StagerError("stage_repository")
    absent = [
        root + "/.git/shallow",
        root + "/.git/commondir",
        root + "/.git/worktrees",
        root + "/.git/objects/info/alternates",
        root + "/.git/objects/info/http-alternates",
    ]
    for path in absent:
        try:
            lstater(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise StagerError("stage_repository") from exc
        raise StagerError("stage_repository")
    files = {}
    file_rows = {}
    for name, maximum in REPOSITORY_METADATA_MAXIMUMS.items():
        path = root + "/.git/" + name
        row = lstater(path)
        if (
            not stat.S_ISREG(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or row.st_uid != owner[0]
            or row.st_gid != owner[1]
            or row.st_nlink != 1
            or stat.S_IMODE(row.st_mode) != 0o644
            or row.st_size > maximum
        ):
            raise StagerError("stage_repository")
        file_rows[path] = row
    for path, row in file_rows.items():
        raw = reader(path, row, REPOSITORY_METADATA_MAXIMUMS[Path(path).name])
        if len(raw) != row.st_size:
            raise StagerError("stage_repository")
        files[path] = [
            row.st_dev,
            row.st_ino,
            row.st_size,
            row.st_mode,
            row.st_uid,
            row.st_gid,
            row.st_nlink,
            _sha256_bytes(raw),
        ]
    return {"directories": rows, "files": files, "absent": absent}


def _settle_stage_git_process(
    process: Any,
    *,
    force_kill: bool,
    killpg: Any = os.killpg,
    monotonic: Any = time.monotonic,
    sleep: Any = time.sleep,
) -> int:
    pid = getattr(process, "pid", None)
    if type(pid) is not int or pid <= 1:
        raise StagerError("stage_git_process")
    reaped = False
    returncode = None
    if not force_kill:
        try:
            returncode = process.wait(timeout=0.2)
            reaped = True
        except Exception:
            pass
        if reaped:
            try:
                killpg(pid, 0)
            except ProcessLookupError:
                return returncode
            except OSError:
                pass
    try:
        killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        raise StagerError("stage_git_containment") from exc
    deadline = monotonic() + 2.0
    if not reaped:
        try:
            returncode = process.wait(timeout=max(0.01, deadline - monotonic()))
            reaped = True
        except Exception:
            pass
    while reaped:
        try:
            killpg(pid, 0)
        except ProcessLookupError:
            return returncode
        except OSError:
            break
        if monotonic() >= deadline:
            break
        sleep(min(0.01, max(0.0, deadline - monotonic())))
    raise StagerError("stage_git_containment")


def _stage_local_git(
    arguments: list[str],
    maximum: int,
    *,
    popen: Any = subprocess.Popen,
    selector_factory: Any = selectors.DefaultSelector,
    monotonic: Any = time.monotonic,
) -> tuple[int, bytes]:
    if (
        type(arguments) is not list
        or not arguments
        or type(maximum) is not int
        or not 1 <= maximum <= MAX_STAGE_GIT_BYTES
    ):
        raise StagerError("stage_git_arguments")
    selector = selector_factory()
    try:
        process = popen(
            [
                STAGE_ROOT_GIT_EXECUTABLE,
                "--no-replace-objects",
                "-c",
                "safe.directory=" + REPOSITORY_ROOT,
                "-c",
                "protocol.file.allow=never",
                "-c",
                "protocol.ext.allow=never",
                *arguments,
            ],
            cwd=REPOSITORY_ROOT,
            env=dict(STAGE_GIT_ENVIRONMENT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
            text=False,
            bufsize=0,
        )
    except BaseException:
        selector.close()
        raise
    output = bytearray()
    failure: Optional[BaseException] = None
    eof = False
    deadline = monotonic() + STAGE_GIT_TIMEOUT_SECONDS
    try:
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        while not eof:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise StagerError("stage_git_timeout")
            for key, _mask in selector.select(min(remaining, 0.25)):
                try:
                    chunk = os.read(
                        key.fileobj.fileno(),
                        min(65536, maximum + 1 - len(output)),
                    )
                except BlockingIOError:
                    continue
                if chunk:
                    output.extend(chunk)
                    if len(output) > maximum:
                        raise StagerError("stage_git_output")
                else:
                    selector.unregister(key.fileobj)
                    eof = True
    except BaseException as exc:
        failure = exc
    finally:
        selector.close()
        try:
            process.stdout.close()
        except BaseException:
            pass
        returncode = _settle_stage_git_process(
            process,
            force_kill=failure is not None,
            monotonic=monotonic,
        )
    if failure is not None:
        if isinstance(failure, StagerError):
            raise failure
        raise StagerError("stage_git_io") from None
    return returncode, bytes(output)


def _stage_git_text(
    arguments: list[str],
    maximum: int = 16384,
    *,
    allowed: tuple[int, ...] = (0,),
) -> str:
    returncode, raw = _stage_local_git(arguments, maximum)
    if returncode not in allowed:
        raise StagerError("stage_git_return")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StagerError("stage_git_text") from exc


def _stage_git_reader(revision: str, ref: str) -> dict[str, Any]:
    if (
        not _hex_text(revision, 40)
        or type(ref) is not str
        or not ref
        or ref.startswith("-")
        or "\0" in ref
    ):
        raise StagerError("stage_git_arguments")
    oid = _stage_git_text(
        ["rev-parse", "--verify", revision + ":" + ref],
        128,
    ).strip()
    if not _hex_text(oid, 40):
        raise StagerError("stage_git_oid")
    returncode, raw = _stage_local_git(
        ["cat-file", "blob", oid],
        MAX_STAGE_GIT_BYTES,
    )
    if returncode != 0 or _git_blob_oid_bytes(raw) != oid:
        raise StagerError("stage_git_object")
    return {"raw": raw, "git_blob_oid": oid}


def _stage_commit_parent(revision: str) -> str:
    fields = _stage_git_text(
        ["rev-list", "--parents", "-n", "1", revision],
        256,
    ).strip().split()
    if len(fields) != 2 or fields[0] != revision or not _hex_text(fields[1], 40):
        raise StagerError("stage_topology")
    return fields[1]


def _stage_path_list(arguments: list[str]) -> list[str]:
    values = _stage_git_text(arguments, 32768).splitlines()
    if any(not value or "\0" in value for value in values) or len(values) != len(set(values)):
        raise StagerError("stage_topology")
    return sorted(values)


def _stage_topology_snapshot(
    source_revision: str,
    acceptance_revision: str,
) -> dict[str, Any]:
    promisor_code, promisor_raw = _stage_local_git(
        [
            "config",
            "--local",
            "--get-regexp",
            "^(extensions\\.partialClone|remote\\..*\\.promisor)$",
        ],
        4096,
    )
    if promisor_code not in (0, 1) or promisor_raw:
        raise StagerError("stage_promisor")
    return {
        "parents": {
            source_revision: [_stage_commit_parent(source_revision)],
            acceptance_revision: [_stage_commit_parent(acceptance_revision)],
        },
        "base_to_source_paths": _stage_path_list(
            [
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                BASE_REVISION,
                source_revision,
            ]
        ),
        "source_to_acceptance_paths": _stage_path_list(
            [
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                source_revision,
                acceptance_revision,
            ]
        ),
        "head_revision": _stage_git_text(
            ["rev-parse", "--verify", "HEAD"],
            128,
        ).strip(),
        "upstream_revision": _stage_git_text(
            ["rev-parse", "--verify", "@{upstream}"],
            128,
        ).strip(),
        "origin_main_revision": _stage_git_text(
            ["rev-parse", "--verify", "refs/remotes/origin/main"],
            128,
        ).strip(),
        "tracked_changes": _stage_git_text(
            ["status", "--porcelain=v1", "--untracked-files=no"],
            32768,
        ).splitlines(),
    }


def _build_stage_bundle(
    source_revision: str,
    acceptance_revision: str,
    *,
    topology_snapshot: Any,
    git_reader: Any,
    system_tool_snapshot: Any,
    repository_snapshot: Any,
) -> dict[str, Any]:
    _validate_future_topology(
        topology_snapshot,
        source_revision,
        acceptance_revision,
    )
    if (
        type(system_tool_snapshot) is not dict
        or set(system_tool_snapshot)
        != set(STAGE_SYSTEM_TOOL_BINDINGS) | set(STAGE_SYSTEM_SYMLINK_BINDINGS)
    ):
        raise StagerError("stage_system_tools")
    if (
        type(repository_snapshot) is not dict
        or set(repository_snapshot) != {"directories", "files", "absent"}
    ):
        raise StagerError("stage_repository")
    source_rows: dict[str, dict[str, Any]] = {}
    source_raw: dict[str, bytes] = {}
    for ref in sorted(SOURCE_REFS):
        raw, row = _read_git_identity(git_reader, source_revision, ref)
        source_raw[ref] = raw
        source_rows[ref] = row
    acceptance_rows: dict[str, dict[str, Any]] = {}
    for ref in sorted(SOURCE_REFS):
        raw, row = _read_git_identity(git_reader, acceptance_revision, ref)
        acceptance_rows[ref] = row
        if ref not in ACCEPTANCE_REFS and raw != source_raw[ref]:
            raise StagerError("stage_acceptance_drift")
    stager_raw = source_raw[STAGER_REF]
    capture_raw = _extract_ascii_literal(stager_raw, "CAPTURE_ROOT_PROGRAM")
    materialize_raw = _extract_ascii_literal(
        stager_raw,
        "MATERIALIZE_ROOT_PROGRAM",
    )
    stage_raw = _extract_ascii_literal(stager_raw, "STAGE_ROOT_PROGRAM")
    if (
        capture_raw != CAPTURE_ROOT_PROGRAM.encode("ascii")
        or materialize_raw != MATERIALIZE_ROOT_PROGRAM.encode("ascii")
        or stage_raw != STAGE_ROOT_PROGRAM.encode("ascii")
    ):
        raise StagerError("stage_embedded_payload")
    fixed_rows: dict[str, dict[str, Any]] = {}
    for ref, expected in sorted(FIXED_BINDINGS.items()):
        frozen_raw, frozen = _read_git_identity(
            git_reader,
            expected["revision"],
            ref,
        )
        live_raw, live = _read_git_identity(
            git_reader,
            acceptance_revision,
            ref,
        )
        provenance: Optional[dict[str, Any]] = None
        if "source_revision" in expected:
            provenance_raw, provenance = _read_git_identity(
                git_reader,
                expected["source_revision"],
                ref,
            )
        else:
            provenance_raw = frozen_raw
        if (
            frozen_raw != live_raw
            or provenance_raw != frozen_raw
            or frozen["git_blob_oid"] != expected["git_blob_oid"]
            or frozen["byte_count"] != expected["size"]
            or frozen["sha256"] != expected["file_sha256"]
            or live["git_blob_oid"] != expected["git_blob_oid"]
        ):
            raise StagerError("stage_fixed_binding_drift")
        fixed_rows[ref] = {
            "revision": expected["revision"],
            "source_revision": expected.get("source_revision"),
            "frozen": frozen,
            "provenance": provenance,
            "acceptance": live,
        }
    payloads = {
        "capture-root-program.py": {
            "byte_count": len(capture_raw),
            "sha256": _sha256_bytes(capture_raw),
            "mode": "0500",
            "source_revision": acceptance_revision,
            "source_ref": STAGER_REF + ":CAPTURE_ROOT_PROGRAM",
        },
        "materialize-root-program.py": {
            "byte_count": len(materialize_raw),
            "sha256": _sha256_bytes(materialize_raw),
            "mode": "0500",
            "source_revision": acceptance_revision,
            "source_ref": STAGER_REF + ":MATERIALIZE_ROOT_PROGRAM",
        },
        "stage-root-program.py": {
            "byte_count": len(stage_raw),
            "sha256": _sha256_bytes(stage_raw),
            "mode": "MEMORY_ONLY",
            "source_revision": acceptance_revision,
            "source_ref": STAGER_REF + ":STAGE_ROOT_PROGRAM",
        },
    }
    bundle = {
        "schema": STAGE_BUNDLE_SCHEMA,
        "authorization_id": STAGE_AUTHORIZATION_ID,
        "base_revision": BASE_REVISION,
        "source_revision": source_revision,
        "acceptance_revision": acceptance_revision,
        "source_rows": source_rows,
        "acceptance_rows": acceptance_rows,
        "fixed_rows": fixed_rows,
        "payloads": payloads,
        "system_tool_snapshot": system_tool_snapshot,
        "repository_snapshot": repository_snapshot,
        "capture_runtime_directory": CAPTURE_RUNTIME_DIRECTORY,
        "materialize_runtime_directory": MATERIALIZE_RUNTIME_DIRECTORY,
        "result_path": _future_result_path(acceptance_revision),
        "automatic_retry_count": 0,
        "cleanup_count": 0,
    }
    raw = canonical_bytes(bundle)
    if not 1 <= len(raw) <= MAX_STAGE_BUNDLE_BYTES:
        raise StagerError("stage_bundle_size")
    return bundle


def _precreate_stage_result(
    path: str,
    *,
    opener: Any = os.open,
    lstater: Any = os.lstat,
    fstater: Any = os.fstat,
    closer: Any = os.close,
    fsyncer: Any = os.fsync,
    directory_opener: Any = os.open,
) -> tuple[int, dict[str, Any]]:
    expected_parent = str(Path(REPOSITORY_ROOT) / ".codex")
    if str(Path(path).parent) != expected_parent:
        raise StagerError("stage_result_path")
    parent = lstater(expected_parent)
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or stat.S_IMODE(parent.st_mode) & 0o022
        or parent.st_uid != os.geteuid()
    ):
        raise StagerError("stage_result_parent")
    descriptor = opener(
        path,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    row = fstater(descriptor)
    if (
        not stat.S_ISREG(row.st_mode)
        or row.st_nlink != 1
        or stat.S_IMODE(row.st_mode) != 0o600
        or row.st_size != 0
        or row.st_uid != os.geteuid()
    ):
        closer(descriptor)
        raise StagerError("stage_result_identity")
    fsyncer(descriptor)
    directory_descriptor = directory_opener(
        expected_parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW,
    )
    try:
        fsyncer(directory_descriptor)
    finally:
        closer(directory_descriptor)
    return descriptor, {
        "path": path,
        "parent": (
            parent.st_dev,
            parent.st_ino,
            parent.st_mode,
            parent.st_uid,
            parent.st_gid,
            parent.st_nlink,
        ),
        "file": (
            row.st_dev,
            row.st_ino,
            row.st_mode,
            row.st_uid,
            row.st_gid,
            row.st_nlink,
        ),
    }


def _check_stage_result_identity(
    descriptor: int,
    identity: dict[str, Any],
    *,
    fstater: Any = os.fstat,
    lstater: Any = os.lstat,
    expected_size: Optional[int] = None,
) -> None:
    if type(identity) is not dict or set(identity) != {"path", "parent", "file"}:
        raise StagerError("stage_result_identity")
    row = fstater(descriptor)
    path_row = lstater(identity["path"])
    parent_row = lstater(str(Path(identity["path"]).parent))
    if (
        (row.st_dev, row.st_ino) != (path_row.st_dev, path_row.st_ino)
        or (expected_size is not None and row.st_size != expected_size)
        or (
            row.st_dev,
            row.st_ino,
            row.st_mode,
            row.st_uid,
            row.st_gid,
            row.st_nlink,
        )
        != identity["file"]
        or (
            parent_row.st_dev,
            parent_row.st_ino,
            parent_row.st_mode,
            parent_row.st_uid,
            parent_row.st_gid,
            parent_row.st_nlink,
        )
        != identity["parent"]
    ):
        raise StagerError("stage_result_identity")


def _validate_stage_child_status(
    raw: bytes,
    source_revision: str,
    acceptance_revision: str,
) -> dict[str, Any]:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_STAGE_STATUS_BYTES:
        raise StagerError("stage_child_status")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise StagerError("stage_child_status") from exc
    if (
        type(value) is not dict
        or set(value) != STAGE_CHILD_SUCCESS_KEYS
        or canonical_bytes(value) != raw
        or value.get("schema") != STAGE_CHILD_STATUS_SCHEMA
        or value.get("status") != "BOTH_RUNTIME_PARTITIONS_STAGED"
        or value.get("source_revision") != source_revision
        or value.get("acceptance_revision") != acceptance_revision
        or value.get("sudo_dispatch_count") != 1
        or value.get("automatic_retry_count") != 0
        or value.get("cleanup_count") != 0
        or value.get("capture_file_create_count") != 3
        or value.get("materialize_file_create_count") != 6
        or value.get("capture_directory_create_count") != 1
        or value.get("materialize_directory_create_count") != 1
        or value.get("rollback_count") != 0
        or value.get("private_key_read_count") != 0
    ):
        raise StagerError("stage_child_status")
    return value


def _write_stage_result_once(
    descriptor: int,
    value: dict[str, Any],
    *,
    path: Optional[str] = None,
    identity: Optional[dict[str, Any]] = None,
    writer: Any = os.write,
    seeker: Any = os.lseek,
    reader: Any = os.read,
    fsyncer: Any = os.fsync,
    fstater: Any = os.fstat,
    lstater: Any = os.lstat,
    directory_opener: Any = os.open,
    closer: Any = os.close,
) -> bytes:
    if type(identity) is not dict or path != identity.get("path"):
        raise StagerError("stage_result_identity")
    before = fstater(descriptor)
    parent_path = str(Path(path).parent)
    parent_before = lstater(parent_path)
    if (
        (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_nlink,
        )
        != identity["file"]
        or before.st_size != 0
        or (
            parent_before.st_dev,
            parent_before.st_ino,
            parent_before.st_mode,
            parent_before.st_uid,
            parent_before.st_gid,
            parent_before.st_nlink,
        )
        != identity["parent"]
    ):
        raise StagerError("stage_result_identity")
    raw = canonical_bytes(value)
    view = memoryview(raw)
    while view:
        count = writer(descriptor, view)
        if count < 1:
            raise StagerError("stage_result_write")
        view = view[count:]
    fsyncer(descriptor)
    seeker(descriptor, 0, os.SEEK_SET)
    readback = bytearray()
    while len(readback) <= len(raw):
        chunk = reader(descriptor, len(raw) + 1 - len(readback))
        if not chunk:
            break
        readback.extend(chunk)
    row = fstater(descriptor)
    path_row = lstater(path)
    parent_after = lstater(parent_path)
    if (
        bytes(readback) != raw
        or row.st_size != len(raw)
        or (row.st_dev, row.st_ino) != (path_row.st_dev, path_row.st_ino)
        or (
            row.st_dev,
            row.st_ino,
            row.st_mode,
            row.st_uid,
            row.st_gid,
            row.st_nlink,
        )
        != identity["file"]
        or (
            parent_after.st_dev,
            parent_after.st_ino,
            parent_after.st_mode,
            parent_after.st_uid,
            parent_after.st_gid,
            parent_after.st_nlink,
        )
        != identity["parent"]
    ):
        raise StagerError("stage_result_readback")
    fsyncer(descriptor)
    directory_descriptor = directory_opener(
        parent_path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW,
    )
    try:
        fsyncer(directory_descriptor)
    except BaseException:
        try:
            closer(directory_descriptor)
        except BaseException:
            pass
        raise
    try:
        closer(directory_descriptor)
    except BaseException:
        # The file, its readback, and its directory entry are already durable.
        # A directory-FD close failure cannot reverse that public terminal.
        pass
    return raw


def _stage_socket_identity(channel: Any) -> tuple[int, int]:
    try:
        descriptor = channel.fileno()
        flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        row = os.fstat(descriptor)
        socket_type = channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
        local_name = channel.getsockname()
        peer_name = channel.getpeername()
    except (AttributeError, OSError, ValueError) as exc:
        raise StagerError("stage_fd_identity") from exc
    if (
        type(descriptor) is not int
        or descriptor < 3
        or channel.family != socket.AF_UNIX
        or socket_type != socket.SOCK_STREAM
        or os.isatty(descriptor)
        or not channel.getblocking()
        or flags & os.O_ACCMODE != os.O_RDWR
        or flags & os.O_NONBLOCK
        or flags & getattr(os, "O_ASYNC", 0)
        or local_name not in (None, "", b"")
        or peer_name not in (None, "", b"")
    ):
        raise StagerError("stage_fd_identity")
    return row.st_dev, row.st_ino


def _stage_sudo_preexec() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _settle_stage_process(
    process: Any,
    *,
    force_kill: bool,
    wait_timeout: float,
    monotonic: Any = time.monotonic,
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    pid = getattr(process, "pid", None)
    if type(pid) is not int or pid <= 1:
        return {"reaped": False, "returncode": None, "kill_sent": False}
    try:
        returncode = process.wait()
        return {"reaped": True, "returncode": returncode, "kill_sent": False}
    except Exception:
        return {
            "reaped": False,
            "returncode": None,
            "kill_sent": False,
        }


def _pump_stage_channels(
    process: Any,
    bundle_channel: Any,
    status_channel: Any,
    bundle_raw: bytes,
    *,
    selector_factory: Any = selectors.DefaultSelector,
    monotonic: Any = time.monotonic,
) -> bytes:
    if (
        type(bundle_raw) is not bytes
        or not 1 <= len(bundle_raw) <= MAX_STAGE_BUNDLE_BYTES
    ):
        raise StagerError("stage_bundle_size")
    selector = selector_factory()
    pending = memoryview(bundle_raw)
    status = bytearray()
    bundle_closed = False
    status_eof = False
    failure: Optional[BaseException] = None
    try:
        bundle_channel.setblocking(False)
        status_channel.setblocking(False)
        selector.register(bundle_channel, selectors.EVENT_WRITE, "bundle")
        selector.register(status_channel, selectors.EVENT_READ, "status")
        while not (bundle_closed and status_eof):
            events = selector.select(0.25)
            if not events and process.poll() is not None and not status_eof:
                # A closed peer is still expected to become readable; continue
                # only inside the same fixed deadline.
                continue
            for key, mask in events:
                if key.data == "bundle" and mask & selectors.EVENT_WRITE:
                    if pending:
                        try:
                            count = bundle_channel.send(pending[:16384])
                        except BlockingIOError:
                            continue
                        if count < 1:
                            raise StagerError("stage_bundle_write")
                        pending = pending[count:]
                    if not pending:
                        bundle_channel.shutdown(socket.SHUT_WR)
                        selector.unregister(bundle_channel)
                        bundle_closed = True
                elif key.data == "status" and mask & selectors.EVENT_READ:
                    try:
                        chunk = status_channel.recv(4096)
                    except BlockingIOError:
                        continue
                    if chunk:
                        status.extend(chunk)
                        if len(status) > MAX_STAGE_STATUS_BYTES:
                            raise StagerError("stage_child_status_size")
                    else:
                        selector.unregister(status_channel)
                        status_eof = True
        return bytes(status)
    except BaseException as exc:
        failure = exc
    finally:
        selector.close()
    if failure is not None:
        try:
            bundle_channel.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        try:
            status_channel.setblocking(True)
            while True:
                chunk = status_channel.recv(4096)
                if not chunk:
                    break
                if len(status) <= MAX_STAGE_STATUS_BYTES:
                    status.extend(chunk)
        except OSError:
            pass
        raise StagerError("stage_channel_io") from None
    return bytes(status)


def _dispatch_stage_root_once(
    bundle_raw: bytes,
    *,
    expected_tool_snapshot: Any,
    tool_snapshot: Any = _stage_system_tool_snapshot,
    socketpair_factory: Any = socket.socketpair,
    selector_factory: Any = selectors.DefaultSelector,
    popen: Any = subprocess.Popen,
    monotonic: Any = time.monotonic,
    sleep: Any = time.sleep,
) -> bytes:
    if type(bundle_raw) is not bytes or not 1 <= len(bundle_raw) <= MAX_STAGE_BUNDLE_BYTES:
        raise StagerError("stage_bundle_size")
    try:
        bundle = json.loads(bundle_raw)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise StagerError("stage_bundle") from exc
    if canonical_bytes(bundle) != bundle_raw:
        raise StagerError("stage_bundle")
    source_revision = bundle.get("source_revision")
    acceptance_revision = bundle.get("acceptance_revision")
    stage_identity = bundle.get("payloads", {}).get("stage-root-program.py", {})
    if (
        not _hex_text(source_revision, 40)
        or not _hex_text(acceptance_revision, 40)
        or stage_identity.get("byte_count") != len(STAGE_ROOT_PROGRAM.encode("ascii"))
        or stage_identity.get("sha256")
        != _sha256_bytes(STAGE_ROOT_PROGRAM.encode("ascii"))
        or tool_snapshot() != expected_tool_snapshot
    ):
        raise StagerError("stage_dispatch_preflight")
    pairs: list[tuple[Any, Any]] = []
    process = None
    proof = None
    stage_selector = None
    failure: Optional[BaseException] = None
    status_raw = b""
    started = monotonic()
    try:
        pairs = [
            socketpair_factory(socket.AF_UNIX, socket.SOCK_STREAM),
            socketpair_factory(socket.AF_UNIX, socket.SOCK_STREAM),
        ]
        channels = [channel for pair in pairs for channel in pair]
        identities = [_stage_socket_identity(channel) for channel in channels]
        if len(set(identities)) != 4:
            raise StagerError("stage_fd_alias")
        parent_bundle, child_bundle = pairs[0]
        parent_status, child_status = pairs[1]
        stage_selector = selector_factory()
        command = [
            *STAGE_SUDO_COMMAND_PREFIX,
            "-c",
            STAGE_ROOT_PROGRAM,
            "--stage-root",
            source_revision,
            acceptance_revision,
            str(stage_identity["byte_count"]),
            stage_identity["sha256"],
        ]
        process = popen(
            command,
            stdin=child_bundle.fileno(),
            stdout=child_status.fileno(),
            stderr=None,
            cwd=REPOSITORY_ROOT,
            env=dict(STAGE_SUDO_ENVIRONMENT),
            close_fds=True,
            start_new_session=False,
            preexec_fn=_stage_sudo_preexec,
            text=False,
            bufsize=0,
        )
        child_bundle.close()
        child_status.close()
        status_raw = _pump_stage_channels(
            process,
            parent_bundle,
            parent_status,
            bundle_raw,
            selector_factory=lambda: stage_selector,
            monotonic=monotonic,
        )
    except BaseException as exc:
        failure = exc
    finally:
        if process is not None:
            proof = _settle_stage_process(
                process,
                force_kill=failure is not None,
                wait_timeout=max(
                    0.0,
                    STAGE_CHILD_TIMEOUT_SECONDS - (monotonic() - started),
                ),
                monotonic=monotonic,
                sleep=sleep,
            )
        for pair in pairs:
            for channel in pair:
                try:
                    channel.close()
                except Exception:
                    pass
        if stage_selector is not None:
            try:
                stage_selector.close()
            except Exception:
                pass
    if (
        failure is not None
        or type(proof) is not dict
        or proof.get("reaped") is not True
        or proof.get("returncode") != 0
        or tool_snapshot() != expected_tool_snapshot
    ):
        raise StagerError("stage_single_sudo_failed") from None
    return status_raw


def _future_stage_once(
    source_revision: str,
    acceptance_revision: str,
    *,
    topology_snapshot: Any,
    git_reader: Any,
    system_tool_snapshot: Any,
    repository_snapshot: Any,
    dispatcher: Any,
    result_precreator: Any = _precreate_stage_result,
    result_writer: Any = _write_stage_result_once,
    closer: Any = os.close,
    outer_identity_validator: Any = lambda: None,
    result_identity_checker: Any = _check_stage_result_identity,
) -> dict[str, Any]:
    bundle = _build_stage_bundle(
        source_revision,
        acceptance_revision,
        topology_snapshot=topology_snapshot,
        git_reader=git_reader,
        system_tool_snapshot=system_tool_snapshot,
        repository_snapshot=repository_snapshot,
    )
    outer_identity_validator()
    descriptor, identity = result_precreator(bundle["result_path"])
    write_started = False
    committed = False
    try:
        result_identity_checker(descriptor, identity, expected_size=0)
        status_raw = dispatcher(canonical_bytes(bundle))
        outer_identity_validator()
        result_identity_checker(descriptor, identity, expected_size=0)
        child = _validate_stage_child_status(
            status_raw,
            source_revision,
            acceptance_revision,
        )
        result = {
            "schema": STAGE_RESULT_SCHEMA,
            "status": child["status"],
            "authorization_id": STAGE_AUTHORIZATION_ID,
            "base_revision": BASE_REVISION,
            "source_revision": child["source_revision"],
            "acceptance_revision": child["acceptance_revision"],
            "result_path": bundle["result_path"],
            "bundle_sha256": _sha256_bytes(canonical_bytes(bundle)),
            "source_stager_sha256": bundle["source_rows"][STAGER_REF]["sha256"],
            "source_test_sha256": bundle["source_rows"][TEST_REF]["sha256"],
            "stage_root_program_sha256": bundle["payloads"]
            ["stage-root-program.py"]["sha256"],
            "capture_root_program_sha256": bundle["payloads"]
            ["capture-root-program.py"]["sha256"],
            "materialize_root_program_sha256": bundle["payloads"]
            ["materialize-root-program.py"]["sha256"],
            "capture_directory_create_count": child[
                "capture_directory_create_count"
            ],
            "materialize_directory_create_count": child[
                "materialize_directory_create_count"
            ],
            "capture_file_create_count": child["capture_file_create_count"],
            "materialize_file_create_count": child[
                "materialize_file_create_count"
            ],
            "sudo_dispatch_count": child["sudo_dispatch_count"],
            "automatic_retry_count": child["automatic_retry_count"],
            "cleanup_count": child["cleanup_count"],
            "rollback_count": child["rollback_count"],
            "private_key_read_count": child["private_key_read_count"],
        }
        write_started = True
        result_writer(
            descriptor,
            result,
            path=bundle["result_path"],
            identity=identity,
        )
        committed = True
        return result
    finally:
        try:
            if not committed:
                outer_identity_validator()
                result_identity_checker(
                    descriptor,
                    identity,
                    expected_size=None if write_started else 0,
                )
        finally:
            try:
                closer(descriptor)
            except Exception as exc:
                if not committed:
                    raise StagerError("stage_result_close") from exc


def _materialize_output_parent_identity(
    *,
    lstater: Any = os.lstat,
) -> tuple[int, int, int, int, int, int]:
    parent_path = str(Path(MATERIALIZE_PUBLIC_PATHS[0]).parent)
    if any(str(Path(path).parent) != parent_path for path in MATERIALIZE_PUBLIC_PATHS):
        raise StagerError("materialize_public_parent")
    row = lstater(parent_path)
    if (
        not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) & 0o022
        or row.st_uid != os.geteuid()
    ):
        raise StagerError("materialize_public_parent")
    return (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_uid,
        row.st_gid,
        row.st_nlink,
    )


def _fsync_materialize_parent(
    parent_path: str,
    *,
    opener: Any = os.open,
    fsyncer: Any = os.fsync,
    closer: Any = os.close,
) -> None:
    descriptor = opener(
        parent_path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW,
    )
    if type(descriptor) is not int or descriptor < 3:
        try:
            closer(descriptor)
        except BaseException:
            pass
        raise StagerError("materialize_public_parent_fd")
    try:
        fsyncer(descriptor)
    except BaseException:
        try:
            closer(descriptor)
        except BaseException:
            pass
        raise
    try:
        closer(descriptor)
    except BaseException:
        # Once the directory fsync has completed, close cannot reverse the
        # durable empty-file or durable artifact terminal.
        pass


def _precreate_one_materialize_output(
    path: str,
    parent_identity: tuple[int, int, int, int, int, int],
    *,
    opener: Any = os.open,
    fstater: Any = os.fstat,
    lstater: Any = os.lstat,
    get_flags: Any = fcntl.fcntl,
    fsyncer: Any = os.fsync,
    parent_fsyncer: Any = _fsync_materialize_parent,
    closer: Any = os.close,
) -> tuple[int, dict[str, Any]]:
    if path not in MATERIALIZE_PUBLIC_PATHS:
        raise StagerError("materialize_public_path")
    descriptor = opener(
        path,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    if type(descriptor) is not int or descriptor < 3:
        try:
            closer(descriptor)
        except BaseException:
            pass
        raise StagerError("materialize_public_fd")
    try:
        row = fstater(descriptor)
        path_row = lstater(path)
        flags = get_flags(descriptor, fcntl.F_GETFL)
        file_identity = (
            row.st_dev,
            row.st_ino,
            row.st_mode,
            row.st_uid,
            row.st_gid,
            row.st_nlink,
        )
        if (
            not stat.S_ISREG(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or row.st_nlink != 1
            or stat.S_IMODE(row.st_mode) != 0o600
            or row.st_uid != os.geteuid()
            or row.st_size != 0
            or (row.st_dev, row.st_ino)
            != (path_row.st_dev, path_row.st_ino)
            or flags & os.O_ACCMODE != os.O_RDWR
            or flags & (os.O_APPEND | os.O_NONBLOCK)
            or flags & getattr(os, "O_ASYNC", 0)
            or _materialize_output_parent_identity(lstater=lstater)
            != parent_identity
        ):
            raise StagerError("materialize_public_identity")
        fsyncer(descriptor)
        parent_fsyncer(str(Path(path).parent))
        return descriptor, {
            "path": path,
            "parent": parent_identity,
            "file": file_identity,
        }
    except BaseException:
        try:
            closer(descriptor)
        except BaseException:
            pass
        raise


def _precreate_materialize_outputs(
    *,
    forbidden_lstater: Any = os.lstat,
    parent_identity_reader: Any = _materialize_output_parent_identity,
    create_one: Any = _precreate_one_materialize_output,
    closer: Any = os.close,
) -> tuple[tuple[int, dict[str, Any]], tuple[int, dict[str, Any]]]:
    try:
        forbidden_lstater(MATERIALIZE_FORBIDDEN_PATH)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise StagerError("materialize_checkpoint_identity") from exc
    else:
        raise StagerError("materialize_checkpoint_present")
    parent_identity = parent_identity_reader()
    held: list[tuple[int, dict[str, Any]]] = []
    try:
        for path in MATERIALIZE_PUBLIC_PATHS:
            held.append(create_one(path, parent_identity))
        descriptors = [row[0] for row in held]
        inodes = [row[1]["file"][:2] for row in held]
        if (
            len(set(descriptors)) != 2
            or len(set(inodes)) != 2
            or parent_identity_reader() != parent_identity
        ):
            raise StagerError("materialize_public_alias")
        return held[0], held[1]
    except BaseException:
        for descriptor, _identity in held:
            try:
                closer(descriptor)
            except BaseException:
                pass
        # O_EXCL residue is deliberately retained; there is no unlink path.
        raise


def _check_materialize_output_identity(
    descriptor: int,
    identity: dict[str, Any],
    *,
    expected_size: Optional[int],
    fstater: Any = os.fstat,
    lstater: Any = os.lstat,
    get_flags: Any = fcntl.fcntl,
) -> None:
    if type(identity) is not dict or set(identity) != {"path", "parent", "file"}:
        raise StagerError("materialize_public_identity")
    row = fstater(descriptor)
    path_row = lstater(identity["path"])
    parent_row = lstater(str(Path(identity["path"]).parent))
    flags = get_flags(descriptor, fcntl.F_GETFL)
    if (
        (row.st_dev, row.st_ino) != (path_row.st_dev, path_row.st_ino)
        or (
            row.st_dev,
            row.st_ino,
            row.st_mode,
            row.st_uid,
            row.st_gid,
            row.st_nlink,
        )
        != identity["file"]
        or (
            parent_row.st_dev,
            parent_row.st_ino,
            parent_row.st_mode,
            parent_row.st_uid,
            parent_row.st_gid,
            parent_row.st_nlink,
        )
        != identity["parent"]
        or (expected_size is not None and row.st_size != expected_size)
        or flags & os.O_ACCMODE != os.O_RDWR
        or flags & (os.O_APPEND | os.O_NONBLOCK)
        or flags & getattr(os, "O_ASYNC", 0)
    ):
        raise StagerError("materialize_public_identity")


def _write_materialize_output_once(
    descriptor: int,
    identity: dict[str, Any],
    raw: bytes,
    *,
    maximum: int,
    identity_checker: Any = _check_materialize_output_identity,
    writer: Any = os.write,
    seeker: Any = os.lseek,
    reader: Any = os.read,
    fsyncer: Any = os.fsync,
    parent_fsyncer: Any = _fsync_materialize_parent,
) -> None:
    if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
        raise StagerError("materialize_public_size")
    identity_checker(descriptor, identity, expected_size=0)
    view = memoryview(raw)
    while view:
        count = writer(descriptor, view)
        if type(count) is not int or count < 1 or count > len(view):
            raise StagerError("materialize_public_write")
        view = view[count:]
    fsyncer(descriptor)
    seeker(descriptor, 0, os.SEEK_SET)
    readback = bytearray()
    while len(readback) <= len(raw):
        chunk = reader(descriptor, len(raw) + 1 - len(readback))
        if not chunk:
            break
        readback.extend(chunk)
    if bytes(readback) != raw:
        raise StagerError("materialize_public_readback")
    identity_checker(descriptor, identity, expected_size=len(raw))
    fsyncer(descriptor)
    parent_fsyncer(str(Path(identity["path"]).parent))


def _drain_output_channels_to_eof(
    process: Any,
    channels: dict[str, Any],
    limits: dict[str, int],
    *,
    hard_timeout: float,
    readiness_role: str,
    readiness_frame: Optional[bytes] = None,
    readiness_state: Optional[dict[str, Any]] = None,
    output_state: Optional[dict[str, bytearray]] = None,
    expected_payload_mode: Optional[str] = None,
    expected_payload_sha256: Optional[str] = None,
    authentication_timeout: float = OUTER_INTERACTIVE_AUTH_TIMEOUT_SECONDS,
    terminal_eof_grace: float = OUTER_TERMINAL_EOF_GRACE_SECONDS,
    selector_factory: Any = selectors.DefaultSelector,
    monotonic: Any = time.monotonic,
) -> dict[str, bytes]:
    if (
        type(channels) is not dict
        or set(channels) != set(limits)
        or readiness_role not in channels
        or (
            readiness_frame is not None
            and (
                type(readiness_frame) is not bytes
                or not readiness_frame.endswith(b"\n")
            )
        )
        or any(type(limit) is not int or limit < 1 for limit in limits.values())
        or type(hard_timeout) not in (int, float)
        or hard_timeout <= 0
        or type(authentication_timeout) not in (int, float)
        or authentication_timeout <= 0
        or type(terminal_eof_grace) not in (int, float)
        or terminal_eof_grace <= 0
        or expected_payload_mode not in (None, "CAPTURE", "MATERIALIZE")
        or (
            expected_payload_sha256 is not None
            and not _hex_text(expected_payload_sha256, 64)
        )
    ):
        raise StagerError("outer_channel_contract")
    if readiness_state is None:
        readiness_state = {}
    if type(readiness_state) is not dict or readiness_state:
        raise StagerError("outer_channel_contract")
    if output_state is None:
        output = {name: bytearray() for name in channels}
    else:
        if type(output_state) is not dict or output_state:
            raise StagerError("outer_channel_contract")
        output_state.update({name: bytearray() for name in channels})
        output = output_state
    selector = selector_factory()
    active = set(channels)
    deadline = monotonic() + authentication_timeout
    ready_observed = False
    terminal_at = None
    try:
        for name, channel in channels.items():
            channel.setblocking(False)
            selector.register(channel, selectors.EVENT_READ, name)
        while active:
            now = monotonic()
            if deadline is not None and now >= deadline:
                raise StagerError("outer_channel_timeout")
            if process.poll() is not None:
                if terminal_at is None:
                    terminal_at = now
                elif now - terminal_at >= terminal_eof_grace:
                    raise StagerError("outer_channel_eof")
            select_timeout = 0.25
            if deadline is not None:
                select_timeout = min(
                    select_timeout,
                    max(0.0, deadline - now),
                )
            if terminal_at is not None:
                select_timeout = min(
                    select_timeout,
                    max(0.0, terminal_eof_grace - (now - terminal_at)),
                )
            events = selector.select(select_timeout)
            events = sorted(
                events,
                key=lambda item: item[0].data != readiness_role,
            )
            for key, mask in events:
                if not mask & selectors.EVENT_READ:
                    continue
                name = key.data
                try:
                    chunk = key.fileobj.recv(
                        min(65536, limits[name] + 1 - len(output[name]))
                    )
                except BlockingIOError:
                    continue
                if chunk:
                    output[name].extend(chunk)
                    if len(output[name]) > limits[name]:
                        raise StagerError("outer_channel_size")
                    if name == readiness_role and not ready_observed:
                        observed = bytes(output[name])
                        newline = observed.find(b"\n")
                        if newline < 0:
                            if len(observed) > 1024:
                                raise StagerError("outer_supervisor_ready")
                            if readiness_frame is not None:
                                comparable = min(
                                    len(observed),
                                    len(readiness_frame),
                                )
                                if (
                                    observed[:comparable]
                                    != readiness_frame[:comparable]
                                ):
                                    raise StagerError("outer_supervisor_ready")
                        else:
                            frame = observed[: newline + 1]
                            if (
                                readiness_frame is not None
                                and frame != readiness_frame
                            ):
                                raise StagerError("outer_supervisor_ready")
                            readiness_state.update(
                                _validate_supervisor_ready_frame(
                                    frame,
                                    expected_payload_mode=(
                                        expected_payload_mode
                                    ),
                                    expected_payload_sha256=(
                                        expected_payload_sha256
                                    ),
                                )
                            )
                            try:
                                acknowledged = key.fileobj.send(b"A")
                            except (BlockingIOError, OSError):
                                raise StagerError(
                                    "outer_supervisor_ack"
                                ) from None
                            if acknowledged != 1:
                                raise StagerError("outer_supervisor_ack")
                            ready_observed = True
                            deadline = monotonic() + hard_timeout
                else:
                    selector.unregister(key.fileobj)
                    active.remove(name)
        if not ready_observed:
            raise StagerError("outer_supervisor_ready")
        return {name: bytes(raw) for name, raw in output.items()}
    except BaseException:
        raise StagerError("outer_channel_drain") from None
    finally:
        try:
            selector.close()
        except BaseException:
            pass


def _cancel_and_drain_for_containment(
    channels: dict[str, Any],
    output_state: dict[str, bytearray],
    limits: dict[str, int],
    readiness_state: dict[str, Any],
    *,
    readiness_role: str,
    timeout: float = OUTER_TERMINATE_GRACE_SECONDS,
    selector_factory: Any = selectors.DefaultSelector,
    monotonic: Any = time.monotonic,
) -> bool:
    if (
        type(channels) is not dict
        or set(channels) != set(limits)
        or set(output_state) != set(channels)
        or readiness_role not in channels
        or type(readiness_state) is not dict
        or type(timeout) not in (int, float)
        or timeout <= 0
    ):
        return False
    control = channels[readiness_role]
    try:
        if readiness_state:
            try:
                control.send(b"C")
            except (BlockingIOError, OSError):
                pass
        control.shutdown(socket.SHUT_WR)
    except OSError:
        pass
    selector = None
    active = set(channels)
    deadline = monotonic() + timeout
    try:
        selector = selector_factory()
        for name, channel in channels.items():
            channel.setblocking(False)
            selector.register(channel, selectors.EVENT_READ, name)
        while active:
            remaining = deadline - monotonic()
            if remaining <= 0:
                return False
            events = selector.select(min(0.25, remaining))
            for key, mask in events:
                if not mask & selectors.EVENT_READ:
                    continue
                name = key.data
                try:
                    chunk = key.fileobj.recv(65536)
                except BlockingIOError:
                    continue
                except OSError:
                    selector.unregister(key.fileobj)
                    active.remove(name)
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    active.remove(name)
                    continue
                if name == readiness_role:
                    remaining_capacity = limits[name] - len(output_state[name])
                    if remaining_capacity > 0:
                        output_state[name].extend(chunk[:remaining_capacity])
                # Artifact bytes are deliberately discarded after failure;
                # raw provider values are never surfaced or persisted.
        return True
    except BaseException:
        return False
    finally:
        if selector is not None:
            try:
                selector.close()
            except BaseException:
                pass


def _prove_root_supervisor_absent(
    readiness: dict[str, Any],
    *,
    kill: Any = os.kill,
    killpg: Any = os.killpg,
    sleep: Any = time.sleep,
) -> bool:
    try:
        supervisor_pid = readiness["supervisor_pid"]
        payload_pgid = readiness["payload_pgid"]
    except (KeyError, TypeError):
        return False
    if (
        type(supervisor_pid) is not int
        or type(payload_pgid) is not int
        or supervisor_pid <= 1
        or payload_pgid <= 1
        or supervisor_pid == payload_pgid
    ):
        return False
    for attempt in range(2):
        for probe, identifier in (
            (kill, supervisor_pid),
            (killpg, payload_pgid),
        ):
            try:
                probe(identifier, 0)
            except ProcessLookupError:
                continue
            except OSError:
                return False
            return False
        if attempt == 0:
            sleep(0.01)
    return True


def _failure_supervisor_terminal_observed(
    raw: bytes,
    readiness: dict[str, Any],
) -> bool:
    if type(raw) is not bytes or type(readiness) is not dict or not readiness:
        return False
    frames = raw.splitlines(keepends=True)
    if not frames:
        return False
    try:
        observed = _validate_supervisor_ready_frame(frames[0])
        if observed != readiness:
            return False
        _validate_supervisor_terminal_frame(
            frames[-1],
            readiness,
            require_success=False,
        )
    except StagerError:
        return False
    return True


def _settle_interactive_sudo_process(
    process: Any,
    *,
    force_terminate: bool,
    wait_timeout: float,
) -> dict[str, Any]:
    pid = getattr(process, "pid", None)
    if type(pid) is not int or pid <= 1:
        return {
            "reaped": False,
            "returncode": None,
            "terminate_sent": False,
            "kill_sent": False,
        }
    terminate_sent = False
    kill_sent = False
    returncode = None
    if not force_terminate:
        try:
            returncode = process.wait(timeout=wait_timeout)
            return {
                "reaped": True,
                "returncode": returncode,
                "terminate_sent": False,
                "kill_sent": False,
            }
        except BaseException:
            force_terminate = True
    if force_terminate:
        try:
            process.terminate()
            terminate_sent = True
        except BaseException:
            pass
        try:
            returncode = process.wait(timeout=OUTER_TERMINATE_GRACE_SECONDS)
            return {
                "reaped": True,
                "returncode": returncode,
                "terminate_sent": terminate_sent,
                "kill_sent": False,
            }
        except BaseException:
            pass
        try:
            process.kill()
            kill_sent = True
        except BaseException:
            pass
        try:
            returncode = process.wait(timeout=OUTER_KILL_GRACE_SECONDS)
            return {
                "reaped": True,
                "returncode": returncode,
                "terminate_sent": terminate_sent,
                "kill_sent": kill_sent,
            }
        except BaseException:
            pass
    return {
        "reaped": False,
        "returncode": None,
        "terminate_sent": terminate_sent,
        "kill_sent": kill_sent,
    }


def _supervisor_ready_frame(
    supervisor_pid: int = 101,
    payload_pgid: int = 102,
    payload_mode: str = "CAPTURE",
    payload_program_sha256: str = "a" * 64,
) -> bytes:
    return canonical_bytes(
        {
            "schema": ROOT_PAYLOAD_SUPERVISOR_SCHEMA,
            "status": "READY",
            "supervisor_pid": supervisor_pid,
            "payload_pgid": payload_pgid,
            "payload_release_count": 0,
            "payload_mode": payload_mode,
            "payload_program_sha256": payload_program_sha256,
            "pre_release_action_count": 0,
            "automatic_retry_count": 0,
            "cleanup_count": 0,
            "raw_value_emitted_count": 0,
        }
    )


def _validate_supervisor_ready_frame(
    raw: bytes,
    *,
    expected_payload_mode: Optional[str] = None,
    expected_payload_sha256: Optional[str] = None,
) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise StagerError("outer_supervisor_ready") from exc
    if (
        type(value) is not dict
        or set(value)
        != {
            "schema",
            "status",
            "supervisor_pid",
            "payload_pgid",
            "payload_release_count",
            "payload_mode",
            "payload_program_sha256",
            "pre_release_action_count",
            "automatic_retry_count",
            "cleanup_count",
            "raw_value_emitted_count",
        }
        or canonical_bytes(value) != raw
        or value.get("schema") != ROOT_PAYLOAD_SUPERVISOR_SCHEMA
        or value.get("status") != "READY"
        or type(value.get("supervisor_pid")) is not int
        or value["supervisor_pid"] <= 1
        or type(value.get("payload_pgid")) is not int
        or value["payload_pgid"] <= 1
        or value["payload_pgid"] == value["supervisor_pid"]
        or type(value.get("payload_release_count")) is not int
        or value["payload_release_count"] != 0
        or value.get("payload_mode") not in {"CAPTURE", "MATERIALIZE"}
        or not _hex_text(value.get("payload_program_sha256"), 64)
        or type(value.get("pre_release_action_count")) is not int
        or value["pre_release_action_count"] != 0
        or (
            expected_payload_mode is not None
            and value["payload_mode"] != expected_payload_mode
        )
        or (
            expected_payload_sha256 is not None
            and value["payload_program_sha256"]
            != expected_payload_sha256
        )
        or type(value.get("automatic_retry_count")) is not int
        or value["automatic_retry_count"] != 0
        or type(value.get("cleanup_count")) is not int
        or value["cleanup_count"] != 0
        or type(value.get("raw_value_emitted_count")) is not int
        or value["raw_value_emitted_count"] != 0
    ):
        raise StagerError("outer_supervisor_ready")
    return value


def _validate_supervisor_terminal_frame(
    raw: bytes,
    readiness: dict[str, Any],
    *,
    require_success: bool,
) -> dict[str, Any]:
    try:
        terminal = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise StagerError("outer_supervisor_frames") from exc
    if (
        type(readiness) is not dict
        or type(terminal) is not dict
        or set(terminal)
        != {
            "schema",
            "status",
            "payload_started",
            "payload_released",
            "supervisor_pid",
            "payload_pgid",
            "payload_release_count",
            "payload_mode",
            "payload_program_sha256",
            "pre_release_action_count",
            "payload_returncode",
            "group_absent",
            "automatic_retry_count",
            "cleanup_count",
            "raw_value_emitted_count",
        }
        or canonical_bytes(terminal) != raw
        or terminal.get("schema") != ROOT_PAYLOAD_SUPERVISOR_SCHEMA
        or terminal.get("status") != "PAYLOAD_GROUP_ABSENT"
        or terminal.get("payload_started") is not True
        or terminal.get("payload_released") is not True
        or terminal.get("supervisor_pid") != readiness.get("supervisor_pid")
        or terminal.get("payload_pgid") != readiness.get("payload_pgid")
        or type(terminal.get("payload_release_count")) is not int
        or terminal["payload_release_count"] != 1
        or terminal.get("payload_mode") != readiness.get("payload_mode")
        or terminal.get("payload_program_sha256")
        != readiness.get("payload_program_sha256")
        or type(terminal.get("pre_release_action_count")) is not int
        or terminal["pre_release_action_count"] != 0
        or type(terminal.get("payload_returncode")) is not int
        or terminal.get("group_absent") is not True
        or type(terminal.get("automatic_retry_count")) is not int
        or terminal["automatic_retry_count"] != 0
        or type(terminal.get("cleanup_count")) is not int
        or terminal["cleanup_count"] != 0
        or type(terminal.get("raw_value_emitted_count")) is not int
        or terminal["raw_value_emitted_count"] != 0
        or (require_success and terminal["payload_returncode"] != 0)
    ):
        raise StagerError("outer_supervisor_frames")
    return terminal


def _unwrap_supervised_status(
    raw: bytes,
    *,
    readiness: Optional[dict[str, Any]] = None,
) -> bytes:
    if type(raw) is not bytes or not 3 <= raw.count(b"\n") <= 3:
        raise StagerError("outer_supervisor_frames")
    frames = raw.splitlines(keepends=True)
    if len(frames) != 3:
        raise StagerError("outer_supervisor_frames")
    observed_readiness = _validate_supervisor_ready_frame(frames[0])
    if readiness is not None and observed_readiness != readiness:
        raise StagerError("outer_supervisor_frames")
    terminal = _validate_supervisor_terminal_frame(
        frames[2],
        observed_readiness,
        require_success=True,
    )
    if (
        terminal["payload_returncode"] != 0
        or not frames[1].endswith(b"\n")
    ):
        raise StagerError("outer_supervisor_frames")
    return frames[1]


def _validate_c1_source_identity(value: Any) -> dict[str, Any]:
    if type(value) is not dict or value != C1_CAPSULE_FIXED_BINDING:
        raise StagerError("capture_c1_source_identity")
    return dict(value)


def _validate_c1_capsule_api(value: Any) -> types.ModuleType:
    required_functions = (
        "canonical_json",
        "read_anonymous_frame",
        "scrub_bytearray",
        "source_only_status",
        "validate_fd_roles",
        "write_anonymous_frame",
    )
    if type(value) is not types.ModuleType:
        raise StagerError("capture_c1_source_api")
    try:
        constants = (
            getattr(value, "SOURCE_SCHEMA"),
            getattr(value, "INTERFACE_SCHEMA"),
            getattr(value, "INITIAL_MINIMUM_VALIDITY_SECONDS"),
            getattr(value, "PER_BEGIN_MINIMUM_VALIDITY_SECONDS"),
            getattr(value, "MAXIMUM_VALIDITY_SECONDS"),
            getattr(value, "MAX_PROVIDER_DISPATCHES"),
        )
        functions = tuple(getattr(value, name) for name in required_functions)
        status = value.source_only_status()
    except Exception:
        raise StagerError("capture_c1_source_api") from None
    if (
        constants
        != (
            "noteai.item26.aliyun-temporary-sts-capsule-source.v1",
            CAPTURE_CREDENTIAL_CAPSULE_SCHEMA,
            INITIAL_MINIMUM_STS_VALIDITY_SECONDS,
            MINIMUM_STS_VALIDITY_SECONDS,
            MAXIMUM_STS_VALIDITY_SECONDS,
            MAX_PROVIDER_DISPATCHES,
        )
        or any(not callable(function) for function in functions)
    ):
        raise StagerError("capture_c1_source_api")
    zero_counts = (
        "cli_install_count",
        "cli_configure_count",
        "oauth_configure_count",
        "oauth_refresh_count",
        "credential_read_count",
        "root_read_count",
        "root_write_count",
        "filesystem_mutation_count",
        "subprocess_count",
        "network_call_count",
        "provider_call_count",
        "database_connection_count",
        "capture_count",
        "materialization_count",
        "automatic_retry_count",
        "cleanup_count",
    )
    if (
        type(status) is not dict
        or set(status)
        != {
            "schema",
            "status",
            "implementation_complete",
            "authorizes_execution",
            "operational_ready",
            "credential_capsule_status",
            "execution_gates",
            *zero_counts,
            "authorized_cny",
            "incurred_cny",
        }
        or status.get("schema")
        != "noteai.item26.aliyun-temporary-sts-capsule-source.v1"
        or status.get("status")
        != "SOURCE_ONLY_IMPLEMENTATION_COMPLETE_NOT_AUTHORIZED"
        or status.get("implementation_complete") is not True
        or status.get("authorizes_execution") is not False
        or status.get("operational_ready") is not False
        or status.get("credential_capsule_status") != "NOT_PROVISIONED"
        or status.get("execution_gates")
        != {
            "cli_oauth_configuration": False,
            "credential_projection": False,
            "root_custody_stage": False,
            "capture_integration": False,
        }
        or any(type(status.get(key)) is not int or status[key] != 0 for key in zero_counts)
        or status.get("authorized_cny") != "0.00"
        or status.get("incurred_cny") != "0.00"
    ):
        raise StagerError("capture_c1_source_api")
    return value


def _load_bound_c1_capsule_api(raw: Any) -> types.ModuleType:
    if (
        type(raw) is not bytes
        or len(raw) != C1_CAPSULE_BYTES
        or hashlib.sha256(raw).hexdigest() != C1_CAPSULE_FILE_SHA256
        or _git_blob_oid_bytes(raw) != C1_CAPSULE_GIT_BLOB_OID
    ):
        raise StagerError("capture_c1_source_api")
    module_name = "_noteai_item26_c1_capsule_accepted"
    previous = sys.modules.get(module_name)
    had_previous = module_name in sys.modules
    try:
        module = types.ModuleType(module_name)
        module.__file__ = C1_CAPSULE_REF
        module.__package__ = ""
        sys.modules[module_name] = module
        code = compile(
            raw,
            C1_CAPSULE_REF + "@" + C1_CAPSULE_ACCEPTANCE_REVISION,
            "exec",
            dont_inherit=True,
            optimize=0,
        )
        exec(code, module.__dict__)
    except Exception:
        raise StagerError("capture_c1_source_api") from None
    finally:
        if had_previous:
            sys.modules[module_name] = previous
        else:
            sys.modules.pop(module_name, None)
    return _validate_c1_capsule_api(module)


class _C1DarwinSocketStat:
    __slots__ = ("_row", "st_dev")

    def __init__(self, row: Any) -> None:
        self._row = row
        self.st_dev = (1 << 64) - 1

    def __getattr__(self, name: str) -> Any:
        return getattr(self._row, name)


def _c1_platform_fstat(descriptor: int) -> Any:
    row = os.fstat(descriptor)
    if (
        sys.platform == "darwin"
        and type(row.st_dev) is int
        and row.st_dev == -1
        and type(row.st_mode) is int
        and stat.S_ISSOCK(row.st_mode)
    ):
        duplicate = -1
        channel = None
        try:
            duplicate = os.dup(descriptor)
            channel = socket.socket(fileno=duplicate)
            duplicate = -1
            if (
                channel.family == socket.AF_UNIX
                and channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
                == socket.SOCK_STREAM
                and channel.getsockname() in {None, "", b""}
                and channel.getpeername() in {None, "", b""}
            ):
                return _C1DarwinSocketStat(row)
        except (OSError, ValueError):
            pass
        finally:
            if channel is not None:
                channel.close()
            elif duplicate >= 0:
                os.close(duplicate)
    return row


def _c1_ready_sha256(projection: Any) -> str:
    validated = _validate_capture_credential_capsule(projection)
    binding = {
        "schema": C1_READY_BINDING_SCHEMA,
        "ready_status": C1_READY_STATUS,
        "projection": validated,
        "capsule_source_revision": C1_CAPSULE_SOURCE_REVISION,
        "capsule_acceptance_revision": C1_CAPSULE_ACCEPTANCE_REVISION,
    }
    return hashlib.sha256(
        C1_READY_SHA256_DOMAIN + canonical_bytes(binding)
    ).hexdigest()


def _c1_handshake_frame(
    projection: Any,
    *,
    status: str,
    ack_count: int,
) -> dict[str, Any]:
    if (
        status not in {C1_READY_STATUS, C1_ACK_STATUS}
        or type(ack_count) is not int
        or ack_count != (0 if status == C1_READY_STATUS else 1)
    ):
        raise StagerError("capture_c1_handshake")
    validated = _validate_capture_credential_capsule(projection)
    return {
        "schema": C1_HANDSHAKE_SCHEMA,
        "status": status,
        "projection": dict(validated),
        "ready_sha256": _c1_ready_sha256(validated),
        "capsule_source_revision": C1_CAPSULE_SOURCE_REVISION,
        "capsule_acceptance_revision": C1_CAPSULE_ACCEPTANCE_REVISION,
        "ack_count": ack_count,
    }


def _reject_c1_handshake_duplicates(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise StagerError("capture_c1_handshake")
        value[key] = item
    return value


def _validate_c1_handshake_frame(
    raw: Any,
    *,
    expected_status: str,
    expected_ack_count: int,
) -> dict[str, Any]:
    if (
        type(raw) not in {bytes, bytearray}
        or not 1 <= len(raw) <= MAX_C1_HANDSHAKE_BYTES
        or 0 in raw
    ):
        raise StagerError("capture_c1_handshake")
    try:
        value = json.loads(
            bytes(raw).decode("ascii"),
            object_pairs_hook=_reject_c1_handshake_duplicates,
            parse_constant=lambda _raw: (_ for _ in ()).throw(
                StagerError("capture_c1_handshake")
            ),
        )
    except StagerError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise StagerError("capture_c1_handshake") from None
    try:
        canonical = canonical_bytes(value)
    except (TypeError, ValueError, RecursionError):
        raise StagerError("capture_c1_handshake") from None
    if (
        type(value) is not dict
        or canonical != bytes(raw)
        or set(value)
        != {
            "schema",
            "status",
            "projection",
            "ready_sha256",
            "capsule_source_revision",
            "capsule_acceptance_revision",
            "ack_count",
        }
        or value.get("schema") != C1_HANDSHAKE_SCHEMA
        or value.get("status") != expected_status
        or type(value.get("ack_count")) is not int
        or value.get("ack_count") != expected_ack_count
        or value.get("capsule_source_revision")
        != C1_CAPSULE_SOURCE_REVISION
        or value.get("capsule_acceptance_revision")
        != C1_CAPSULE_ACCEPTANCE_REVISION
    ):
        raise StagerError("capture_c1_handshake")
    projection = _validate_capture_credential_capsule(value.get("projection"))
    if (
        not _hex_text(value.get("ready_sha256"), 64)
        or value["ready_sha256"] != _c1_ready_sha256(projection)
    ):
        raise StagerError("capture_c1_handshake")
    return value


def _capture_c1_root_session_not_provisioned() -> Any:
    raise StagerError("capture_credential_interface_not_provisioned")


def _validate_c1_fixed_git_binding(*, git_reader: Any) -> dict[str, Any]:
    observed = []
    for revision in (
        C1_CAPSULE_SOURCE_REVISION,
        C1_CAPSULE_ACCEPTANCE_REVISION,
    ):
        row = git_reader(revision, C1_CAPSULE_REF)
        if type(row) is not dict or set(row) != {"raw", "git_blob_oid"}:
            raise StagerError("capture_c1_git_binding")
        raw = row["raw"]
        oid = row["git_blob_oid"]
        if (
            type(raw) is not bytes
            or oid != C1_CAPSULE_GIT_BLOB_OID
            or _git_blob_oid_bytes(raw) != oid
            or len(raw) != C1_CAPSULE_BYTES
            or hashlib.sha256(raw).hexdigest() != C1_CAPSULE_FILE_SHA256
        ):
            raise StagerError("capture_c1_git_binding")
        observed.append((oid, raw))
    if observed[0] != observed[1]:
        raise StagerError("capture_c1_git_binding")
    return {
        "identity": dict(C1_CAPSULE_FIXED_BINDING),
        "raw": observed[0][1],
    }


def _validate_capture_credential_capsule(value: Any) -> dict[str, Any]:
    if (
        type(value) is not dict
        or set(value)
        != {
            "schema",
            "status",
            "account_binding_sha256",
            "minimum_remaining_validity_seconds",
            "credential_payload_exposed",
            "oauth_refresh_count",
            "oauth_configure_count",
        }
        or value.get("schema") != CAPTURE_CREDENTIAL_CAPSULE_SCHEMA
        or value.get("status") != "ROOT_CUSTODY_TEMPORARY_STS_READY"
        or not _hex_text(value.get("account_binding_sha256"), 64)
        or type(value.get("minimum_remaining_validity_seconds")) is not int
        or value["minimum_remaining_validity_seconds"]
        < INITIAL_MINIMUM_STS_VALIDITY_SECONDS
        or value["minimum_remaining_validity_seconds"]
        > MAXIMUM_STS_VALIDITY_SECONDS
        or value.get("credential_payload_exposed") is not False
        or type(value.get("oauth_refresh_count")) is not int
        or value.get("oauth_refresh_count") != 0
        or type(value.get("oauth_configure_count")) is not int
        or value.get("oauth_configure_count") != 0
    ):
        raise StagerError("capture_credential_capsule")
    return value


def _capture_credential_interface_not_provisioned() -> dict[str, Any]:
    raise StagerError("capture_credential_interface_not_provisioned")


def _assert_public_m1_absent(*, lstater: Any = os.lstat) -> None:
    for path in (*MATERIALIZE_PUBLIC_PATHS, MATERIALIZE_FORBIDDEN_PATH):
        try:
            lstater(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise StagerError("capture_public_identity") from exc
        raise StagerError("capture_public_output_present")


def _validate_capture_root_status(raw: bytes) -> dict[str, Any]:
    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= MAX_CHILD_STATUS_BYTES
        or any(marker in raw for marker in MATERIALIZE_SECRET_MARKERS)
    ):
        raise StagerError("capture_root_status")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise StagerError("capture_root_status") from exc
    exact_counts = {
        "logical_slot_count": 5,
        "maximum_provider_dispatches": MAX_PROVIDER_DISPATCHES,
        "parallel_provider_dispatch_count": 0,
        "finalize_call_count": 1,
        "cloud_write_count": 0,
        "database_connection_count": 0,
        "private_key_read_count": 0,
        "automatic_retry_count": 0,
        "cleanup_count": 0,
        "raw_value_emitted_count": 0,
    }
    if (
        type(value) is not dict
        or set(value) != CAPTURE_ROOT_SUCCESS_KEYS
        or canonical_bytes(value) != raw
        or value.get("schema") != CAPTURE_ROOT_RESULT_SCHEMA
        or value.get("status") != "FIVE_STREAM_CAPTURE_FINALIZED"
        or any(
            type(value.get(key)) is not int or value[key] != expected
            for key, expected in exact_counts.items()
        )
        or type(value.get("provider_dispatch_count")) is not int
        or not 5 <= value["provider_dispatch_count"] <= MAX_PROVIDER_DISPATCHES
        or value.get("readiness_credit_added") is not False
    ):
        raise StagerError("capture_root_status")
    return value


def _validate_capture_runtime_arguments(arguments: Any) -> tuple[str, ...]:
    if type(arguments) not in (tuple, list) or len(arguments) != 5:
        raise StagerError("capture_runtime_arguments")
    values = tuple(arguments)
    if (
        not _hex_text(values[0], 40)
        or any(
            type(values[index]) is not str
            or not values[index].isascii()
            or not values[index].isdigit()
            or values[index] != str(int(values[index]))
            or not 1 <= int(values[index]) <= MAX_STAGE_GIT_BYTES
            for index in (1, 3)
        )
        or not _hex_text(values[2], 64)
        or not _hex_text(values[4], 64)
    ):
        raise StagerError("capture_runtime_arguments")
    return values


def _build_capture_runtime_arguments(
    acceptance_revision: str,
) -> tuple[str, ...]:
    if not _hex_text(acceptance_revision, 40):
        raise StagerError("capture_runtime_arguments")
    program_raw = CAPTURE_ROOT_PROGRAM.encode("ascii")
    manifest = {
        "schema": RUNTIME_MANIFEST_SCHEMA,
        "manifest_name": "capture-runtime-manifest.json",
        "manifest_mode": "0600",
        "payloads": {
            "capture-root-program.py": {
                "name": "capture-root-program.py",
                "byte_count": len(program_raw),
                "sha256": _sha256_bytes(program_raw),
                "mode": "0500",
                "source_revision": acceptance_revision,
                "source_ref": STAGER_REF + ":CAPTURE_ROOT_PROGRAM",
            },
            "item26_aliyun_official_read_v2.py": {
                "name": "item26_aliyun_official_read_v2.py",
                "byte_count": FIXED_BINDINGS[ADAPTER_REF]["size"],
                "sha256": FIXED_BINDINGS[ADAPTER_REF]["file_sha256"],
                "mode": "0500",
                "source_revision": ADAPTER_ACCEPTANCE_REVISION,
                "source_ref": ADAPTER_REF,
            },
        },
    }
    manifest_raw = canonical_bytes(manifest)
    return _validate_capture_runtime_arguments(
        (
            acceptance_revision,
            str(len(program_raw)),
            _sha256_bytes(program_raw),
            str(len(manifest_raw)),
            _sha256_bytes(manifest_raw),
        )
    )


def _read_capture_supervisor_ready_once(
    process: Any,
    channel: Any,
    *,
    expected_payload_sha256: str,
    selector_factory: Any,
    monotonic: Any,
) -> tuple[dict[str, Any], bytearray]:
    selector = selector_factory()
    raw = bytearray()
    deadline = monotonic() + OUTER_INTERACTIVE_AUTH_TIMEOUT_SECONDS
    try:
        channel.setblocking(False)
        selector.register(channel, selectors.EVENT_READ)
        while b"\n" not in raw:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise StagerError("outer_channel_timeout")
            events = selector.select(min(0.25, remaining))
            if not events:
                if process.poll() is not None:
                    raise StagerError("outer_channel_eof")
                continue
            try:
                chunk = channel.recv(1025 - len(raw))
            except BlockingIOError:
                continue
            if not chunk:
                raise StagerError("outer_channel_eof")
            raw.extend(chunk)
            if len(raw) > 1024:
                raise StagerError("outer_channel_size")
        newline = raw.find(b"\n")
        if newline != len(raw) - 1:
            raise StagerError("outer_supervisor_ready")
        readiness = _validate_supervisor_ready_frame(
            bytes(raw),
            expected_payload_mode="CAPTURE",
            expected_payload_sha256=expected_payload_sha256,
        )
        return readiness, raw
    except StagerError:
        raise
    except BaseException:
        raise StagerError("outer_supervisor_ready") from None
    finally:
        try:
            selector.close()
        except BaseException:
            pass


def _read_c1_ready_with_deadline(
    api: types.ModuleType,
    descriptor: int,
    process: Any,
    *,
    deadline: float,
    selector_factory: Any,
    monotonic: Any,
) -> bytearray:
    if type(deadline) not in {int, float} or not math.isfinite(deadline):
        raise StagerError("capture_c1_handshake")

    def read_ready(fd: int, maximum: int) -> bytes:
        selector = selector_factory()
        try:
            selector.register(fd, selectors.EVENT_READ)
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise StagerError("capture_c1_handshake")
                events = selector.select(min(0.25, remaining))
                if events:
                    return os.read(fd, maximum)
                if process.poll() is not None:
                    raise StagerError("capture_c1_handshake")
        finally:
            selector.close()

    def probe_eof(fd: int) -> bool:
        return read_ready(fd, 1) == b""

    try:
        return api.read_anonymous_frame(
            descriptor,
            MAX_C1_HANDSHAKE_BYTES,
            reader=read_ready,
            eof_probe=probe_eof,
            fstat_fn=_c1_platform_fstat,
        )
    except Exception:
        raise StagerError("capture_c1_handshake") from None


def _wait_c1_ack_peer_eof(
    descriptor: int,
    *,
    deadline: float,
    selector_factory: Any,
    monotonic: Any,
) -> None:
    if (
        type(descriptor) is not int
        or descriptor < 3
        or type(deadline) not in {int, float}
        or not math.isfinite(deadline)
    ):
        raise StagerError("capture_c1_handshake")
    selector = selector_factory()
    try:
        selector.register(descriptor, selectors.EVENT_READ)
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise StagerError("capture_c1_handshake")
            events = selector.select(min(0.25, remaining))
            if not events:
                continue
            try:
                reverse = os.read(descriptor, 1)
            except (BlockingIOError, OSError):
                raise StagerError("capture_c1_handshake") from None
            if reverse != b"":
                raise StagerError("capture_c1_handshake")
            return
    finally:
        try:
            selector.close()
        except BaseException:
            pass


def _drain_capture_status_after_ready(
    process: Any,
    channel: Any,
    raw: bytearray,
    *,
    selector_factory: Any,
    monotonic: Any,
) -> bytes:
    selector = selector_factory()
    deadline = monotonic() + CAPTURE_OUTER_HARD_TIMEOUT_SECONDS
    terminal_at: Optional[float] = None
    try:
        channel.setblocking(False)
        selector.register(channel, selectors.EVENT_READ)
        while True:
            now = monotonic()
            if now >= deadline:
                raise StagerError("outer_channel_timeout")
            if process.poll() is not None:
                if terminal_at is None:
                    terminal_at = now
                elif now - terminal_at >= OUTER_TERMINAL_EOF_GRACE_SECONDS:
                    raise StagerError("outer_channel_eof")
            timeout = min(0.25, deadline - now)
            if terminal_at is not None:
                timeout = min(
                    timeout,
                    OUTER_TERMINAL_EOF_GRACE_SECONDS - (now - terminal_at),
                )
            events = selector.select(max(0.0, timeout))
            if not events:
                continue
            try:
                chunk = channel.recv(
                    min(65536, MAX_SUPERVISED_STATUS_BYTES + 1 - len(raw))
                )
            except BlockingIOError:
                continue
            if not chunk:
                return bytes(raw)
            raw.extend(chunk)
            if len(raw) > MAX_SUPERVISED_STATUS_BYTES:
                raise StagerError("outer_channel_size")
    except StagerError:
        raise
    except BaseException:
        raise StagerError("outer_channel_drain") from None
    finally:
        try:
            selector.close()
        except BaseException:
            pass


def _dispatch_capture_root_once(
    runtime_arguments: Any,
    *,
    tool_snapshot: Any,
    capsule_api: Any,
    credential_ready_validator: Any,
    pre_ack_identity_validator: Any,
    tool_snapshot_reader: Any = _stage_system_tool_snapshot,
    socketpair_factory: Any = socket.socketpair,
    selector_factory: Any = selectors.DefaultSelector,
    popen: Any = subprocess.Popen,
    settler: Any = _settle_interactive_sudo_process,
    monotonic: Any = time.monotonic,
    signal_masker: Any = signal.pthread_sigmask,
    absence_prover: Any = _prove_root_supervisor_absent,
) -> bytes:
    arguments = _validate_capture_runtime_arguments(runtime_arguments)
    api = _validate_c1_capsule_api(capsule_api)
    if (
        not callable(credential_ready_validator)
        or not callable(pre_ack_identity_validator)
    ):
        raise StagerError("capture_c1_session")
    if tool_snapshot_reader() != tool_snapshot:
        raise StagerError("capture_dispatch_identity")
    expected_payload_sha256 = _sha256_bytes(
        CAPTURE_ROOT_PROGRAM.encode("ascii")
    )
    pairs: list[tuple[Any, Any]] = []
    parent_status = child_status = None
    parent_ready = child_ready = None
    parent_ack = child_ack = None
    process = None
    proof = None
    failure = None
    output_raw = b""
    output_state: dict[str, bytearray] = {"status": bytearray()}
    readiness_state: dict[str, Any] = {}
    ready_raw: Optional[bytearray] = None
    ack_raw: Optional[bytearray] = None
    containment_eof = False
    root_absent = False
    deferred_signal = None
    containment_mask = None
    try:
        try:
            for _unused in range(3):
                pair = socketpair_factory(socket.AF_UNIX, socket.SOCK_STREAM)
                pairs.append(pair)
                if type(pair) is not tuple or len(pair) != 2:
                    raise StagerError("capture_status_channel")
            channels = [channel for pair in pairs for channel in pair]
            identities = [
                _stage_socket_identity(channel) for channel in channels
            ]
            if len(set(identities)) != 6:
                raise StagerError("capture_status_fd_alias")
        except BaseException:
            for pair in pairs:
                candidates = pair if type(pair) is tuple else (pair,)
                for channel in candidates:
                    try:
                        channel.close()
                    except BaseException:
                        pass
            pairs = []
            raise
        (parent_status, child_status), (parent_ready, child_ready), (
            parent_ack,
            child_ack,
        ) = pairs
        pairs = []
        process = popen(
            [
                "/usr/bin/sudo",
                "-T",
                str(CAPTURE_SUDO_MONITOR_TIMEOUT_SECONDS),
                "--",
                "/usr/bin/python3",
                "-I",
                "-S",
                "-B",
                "-c",
                CAPTURE_EXEC_BOOTSTRAP,
                *arguments,
            ],
            cwd=REPOSITORY_ROOT,
            env=dict(STAGE_SUDO_ENVIRONMENT),
            stdin=child_ack.fileno(),
            stdout=child_status.fileno(),
            stderr=child_ready.fileno(),
            close_fds=True,
            start_new_session=False,
            preexec_fn=_stage_sudo_preexec,
            text=False,
            bufsize=0,
        )
        for channel in (child_status, child_ready, child_ack):
            channel.close()
        child_status = child_ready = child_ack = None
        readiness, prefix = _read_capture_supervisor_ready_once(
            process,
            parent_status,
            expected_payload_sha256=expected_payload_sha256,
            selector_factory=selector_factory,
            monotonic=monotonic,
        )
        readiness_state.update(readiness)
        output_state["status"].extend(prefix)
        c1_handshake_deadline = (
            monotonic() + CAPTURE_C1_HANDSHAKE_TIMEOUT_SECONDS
        )
        try:
            if parent_status.send(b"A") != 1:
                raise StagerError("outer_supervisor_ack")
        except (BlockingIOError, OSError):
            raise StagerError("outer_supervisor_ack") from None
        api.validate_fd_roles(
            parent_ready.fileno(),
            parent_ack.fileno(),
            fstat_fn=_c1_platform_fstat,
        )
        ready_raw = _read_c1_ready_with_deadline(
            api,
            parent_ready.fileno(),
            process,
            deadline=c1_handshake_deadline,
            selector_factory=selector_factory,
            monotonic=monotonic,
        )
        ready_endpoint = parent_ready
        parent_ready = None
        try:
            ready_endpoint.close()
        except BaseException:
            raise StagerError("capture_c1_handshake") from None
        ack = credential_ready_validator(ready_raw)
        pre_ack_identity_validator()
        if monotonic() >= c1_handshake_deadline:
            raise StagerError("capture_c1_handshake")
        ack_raw = bytearray(canonical_bytes(ack))
        api.write_anonymous_frame(
            parent_ack.fileno(),
            ack_raw,
            MAX_C1_HANDSHAKE_BYTES,
            fstat_fn=_c1_platform_fstat,
        )
        _wait_c1_ack_peer_eof(
            parent_ack.fileno(),
            deadline=c1_handshake_deadline,
            selector_factory=selector_factory,
            monotonic=monotonic,
        )
        ack_endpoint = parent_ack
        parent_ack = None
        try:
            ack_endpoint.close()
        except BaseException:
            raise StagerError("capture_c1_handshake") from None
        output_raw = _drain_capture_status_after_ready(
            process,
            parent_status,
            output_state["status"],
            selector_factory=selector_factory,
            monotonic=monotonic,
        )
    except BaseException as exc:
        failure = exc
    finally:
        for raw in (ready_raw, ack_raw):
            if raw is not None:
                try:
                    api.scrub_bytearray(raw)
                except BaseException as exc:
                    if failure is None:
                        failure = exc
        for channel in (parent_ready, parent_ack, child_ready, child_ack):
            if channel is not None:
                try:
                    channel.close()
                except BaseException as exc:
                    if failure is None:
                        failure = exc
        if process is not None:
            try:
                containment_mask = signal_masker(
                    signal.SIG_BLOCK,
                    OUTER_COMMIT_SIGNALS,
                )
            except BaseException as exc:
                if failure is None:
                    failure = exc
            try:
                if failure is not None and parent_status is not None:
                    containment_eof = _cancel_and_drain_for_containment(
                        {"status": parent_status},
                        output_state,
                        {"status": MAX_SUPERVISED_STATUS_BYTES},
                        readiness_state,
                        readiness_role="status",
                        monotonic=monotonic,
                    )
                try:
                    proof = settler(
                        process,
                        force_terminate=(
                            failure is not None and not containment_eof
                        ),
                        wait_timeout=CAPTURE_SUDO_MONITOR_TIMEOUT_SECONDS + 5,
                    )
                except BaseException as exc:
                    if failure is None:
                        failure = exc
                for channel in (parent_status, child_status):
                    if channel is not None:
                        try:
                            channel.close()
                        except BaseException:
                            pass
                if readiness_state:
                    try:
                        root_absent = absence_prover(readiness_state) is True
                    except BaseException as exc:
                        if failure is None:
                            failure = exc
            finally:
                if containment_mask is not None:
                    try:
                        signal_masker(signal.SIG_SETMASK, containment_mask)
                    except BaseException as exc:
                        deferred_signal = exc
        else:
            for channel in (parent_status, child_status):
                if channel is not None:
                    try:
                        channel.close()
                    except BaseException:
                        pass
    if deferred_signal is not None:
        raise deferred_signal
    normal_proof = proof == {
        "reaped": True,
        "returncode": 0,
        "terminate_sent": False,
        "kill_sent": False,
    }
    if failure is not None:
        if (
            type(proof) is not dict
            or proof.get("reaped") is not True
            or (readiness_state and not root_absent)
        ):
            raise StagerError("capture_root_containment_unproven") from None
        # Whether the fixed terminal frame survived or the status stream was
        # lost, the bound supervisor PID and payload PGID are both absent.
        _failure_supervisor_terminal_observed(
            bytes(output_state.get("status", b"")),
            readiness_state,
        )
        raise StagerError("capture_single_sudo_failed") from None
    if (
        not normal_proof
        or not root_absent
        or proof
        != {
            "reaped": True,
            "returncode": 0,
            "terminate_sent": False,
            "kill_sent": False,
        }
        or tool_snapshot_reader() != tool_snapshot
        or not output_raw
    ):
        raise StagerError("capture_single_sudo_failed") from None
    return _unwrap_supervised_status(
        output_raw,
        readiness=readiness_state,
    )


def _validate_materialize_runtime_arguments(arguments: Any) -> tuple[str, ...]:
    if type(arguments) not in (tuple, list) or len(arguments) != 10:
        raise StagerError("materialize_runtime_arguments")
    values = tuple(arguments)
    if (
        not _hex_text(values[0], 40)
        or values[0] == BASE_REVISION
        or any(
            type(values[index]) is not str
            or not values[index].isascii()
            or not values[index].isdigit()
            or values[index] != str(int(values[index]))
            or not 1 <= int(values[index]) <= MAX_STAGE_GIT_BYTES
            for index in (1, 4)
        )
        or any(
            type(values[index]) is not str
            or not values[index].isascii()
            or not values[index].isdigit()
            or values[index] != str(int(values[index]))
            or not 1
            <= int(values[index])
            <= MAX_FINALIZED_CAPTURE_ARTIFACT_BYTES
            for index in (6, 8)
        )
        or not _hex_text(values[2], 64)
        or not _hex_text(values[3], 40)
        or not _hex_text(values[5], 64)
        or not _hex_text(values[7], 64)
        or not _hex_text(values[9], 64)
    ):
        raise StagerError("materialize_runtime_arguments")
    return values


def _dispatch_materialize_root_once(
    runtime_arguments: Any,
    *,
    tool_snapshot: Any,
    tool_snapshot_reader: Any = _stage_system_tool_snapshot,
    socketpair_factory: Any = socket.socketpair,
    selector_factory: Any = selectors.DefaultSelector,
    popen: Any = subprocess.Popen,
    settler: Any = _settle_interactive_sudo_process,
    monotonic: Any = time.monotonic,
    signal_masker: Any = signal.pthread_sigmask,
    absence_prover: Any = _prove_root_supervisor_absent,
) -> dict[str, bytes]:
    arguments = _validate_materialize_runtime_arguments(runtime_arguments)
    if tool_snapshot_reader() != tool_snapshot:
        raise StagerError("materialize_dispatch_identity")
    pairs: list[tuple[Any, Any]] = []
    process = None
    proof = None
    failure = None
    output: dict[str, bytes] = {}
    output_state: dict[str, bytearray] = {}
    readiness_state: dict[str, Any] = {}
    containment_eof = False
    root_absent = False
    deferred_signal = None
    containment_mask = None
    try:
        pairs = [
            socketpair_factory(socket.AF_UNIX, socket.SOCK_STREAM)
            for _name in ("receipt", "evidence", "status")
        ]
        channels = [channel for pair in pairs for channel in pair]
        identities = [_stage_socket_identity(channel) for channel in channels]
        if len(set(identities)) != 6:
            raise StagerError("materialize_output_fd_alias")
        parent_receipt, child_receipt = pairs[0]
        parent_evidence, child_evidence = pairs[1]
        parent_status, child_status = pairs[2]
        process = popen(
            [
                *MATERIALIZE_SUDO_COMMAND_PREFIX,
                "--",
                "/usr/bin/python3",
                "-I",
                "-S",
                "-B",
                "-c",
                MATERIALIZE_STDIO_BOOTSTRAP,
                *arguments,
            ],
            cwd=REPOSITORY_ROOT,
            env=dict(STAGE_SUDO_ENVIRONMENT),
            stdin=child_status.fileno(),
            stdout=child_receipt.fileno(),
            stderr=child_evidence.fileno(),
            close_fds=True,
            start_new_session=False,
            preexec_fn=_stage_sudo_preexec,
            text=False,
            bufsize=0,
        )
        for child_channel in (child_receipt, child_evidence, child_status):
            child_channel.close()
        for parent_channel in (parent_receipt, parent_evidence):
            parent_channel.shutdown(socket.SHUT_WR)
        output = _drain_output_channels_to_eof(
            process,
            {
                "receipt": parent_receipt,
                "evidence": parent_evidence,
                "status": parent_status,
            },
            {
                "receipt": MAX_MATERIALIZE_RECEIPT_BYTES,
                "evidence": MAX_MATERIALIZE_EVIDENCE_BYTES,
                "status": MAX_SUPERVISED_STATUS_BYTES,
            },
            hard_timeout=MATERIALIZE_OUTER_HARD_TIMEOUT_SECONDS,
            readiness_role="status",
            readiness_frame=None,
            readiness_state=readiness_state,
            output_state=output_state,
            expected_payload_mode="MATERIALIZE",
            expected_payload_sha256=_sha256_bytes(
                MATERIALIZE_ROOT_PROGRAM.encode("ascii")
            ),
            selector_factory=selector_factory,
            monotonic=monotonic,
        )
    except BaseException as exc:
        failure = exc
    finally:
        if process is not None:
            try:
                containment_mask = signal_masker(
                    signal.SIG_BLOCK,
                    OUTER_COMMIT_SIGNALS,
                )
            except BaseException as exc:
                if failure is None:
                    failure = exc
            try:
                if failure is not None and pairs:
                    containment_eof = _cancel_and_drain_for_containment(
                        {
                            "receipt": pairs[0][0],
                            "evidence": pairs[1][0],
                            "status": pairs[2][0],
                        },
                        output_state,
                        {
                            "receipt": MAX_MATERIALIZE_RECEIPT_BYTES,
                            "evidence": MAX_MATERIALIZE_EVIDENCE_BYTES,
                            "status": MAX_SUPERVISED_STATUS_BYTES,
                        },
                        readiness_state,
                        readiness_role="status",
                        monotonic=monotonic,
                    )
                try:
                    proof = settler(
                        process,
                        force_terminate=(
                            failure is not None and not containment_eof
                        ),
                        wait_timeout=MATERIALIZE_SUDO_MONITOR_TIMEOUT_SECONDS + 5,
                    )
                except BaseException as exc:
                    if failure is None:
                        failure = exc
                for pair in pairs:
                    for channel in pair:
                        try:
                            channel.close()
                        except BaseException:
                            pass
                if readiness_state:
                    try:
                        root_absent = absence_prover(readiness_state) is True
                    except BaseException as exc:
                        if failure is None:
                            failure = exc
            finally:
                if containment_mask is not None:
                    try:
                        signal_masker(signal.SIG_SETMASK, containment_mask)
                    except BaseException as exc:
                        deferred_signal = exc
        else:
            for pair in pairs:
                for channel in pair:
                    try:
                        channel.close()
                    except BaseException:
                        pass
    if deferred_signal is not None:
        raise deferred_signal
    normal_proof = proof == {
        "reaped": True,
        "returncode": 0,
        "terminate_sent": False,
        "kill_sent": False,
    }
    if failure is not None:
        if (
            type(proof) is not dict
            or proof.get("reaped") is not True
            or (readiness_state and not root_absent)
        ):
            raise StagerError("materialize_root_containment_unproven") from None
        _failure_supervisor_terminal_observed(
            bytes(output_state.get("status", b"")),
            readiness_state,
        )
        raise StagerError("materialize_single_sudo_failed") from None
    if (
        not normal_proof
        or not root_absent
        or proof
        != {
            "reaped": True,
            "returncode": 0,
            "terminate_sent": False,
            "kill_sent": False,
        }
        or tool_snapshot_reader() != tool_snapshot
        or set(output) != {"receipt", "evidence", "status"}
    ):
        raise StagerError("materialize_single_sudo_failed") from None
    output["status"] = _unwrap_supervised_status(
        output["status"],
        readiness=readiness_state,
    )
    return output


def _validate_materialize_child_status(raw: bytes) -> dict[str, Any]:
    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= MAX_MATERIALIZE_STATUS_BYTES
        or any(marker in raw for marker in MATERIALIZE_SECRET_MARKERS)
    ):
        raise StagerError("materialize_child_status")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise StagerError("materialize_child_status") from exc
    expected_zero = (
        "checkpoint_build_count",
        "network_dispatch_count",
        "provider_dispatch_count",
        "database_connection_count",
        "database_transaction_count",
        "database_write_count",
        "private_key_read_count",
        "private_key_write_count",
        "private_key_output_count",
        "credential_configuration_count",
        "credential_refresh_count",
        "raw_value_emitted_count",
        "automatic_retry_count",
        "cleanup_count",
    )
    expected_nonzero = {
        "receipt_build_count": 1,
        "evidence_build_count": 1,
        "receipt_validation_count": 3,
        "evidence_validation_count": 2,
    }
    if (
        type(value) is not dict
        or set(value) != MATERIALIZE_CHILD_SUCCESS_KEYS
        or canonical_bytes(value) != raw
        or value.get("schema") != MATERIALIZE_CHILD_STATUS_SCHEMA
        or value.get("status")
        != "RECEIPT_AND_EVIDENCE_BUILT_AND_VERIFIED"
        or any(
            type(value.get(key)) is not int or value[key] != expected
            for key, expected in expected_nonzero.items()
        )
        or any(
            type(value.get(key)) is not int or value[key] != 0
            for key in expected_zero
        )
    ):
        raise StagerError("materialize_child_status")
    return value


def _decode_public_artifact(raw: bytes, *, schema: str, maximum: int) -> dict[str, Any]:
    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= maximum
        or any(marker in raw for marker in MATERIALIZE_SECRET_MARKERS)
    ):
        raise StagerError("materialize_public_artifact")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise StagerError("materialize_public_artifact") from exc
    if (
        type(value) is not dict
        or value.get("schema") != schema
        or canonical_bytes(value) != raw
    ):
        raise StagerError("materialize_public_artifact")
    return value


class _FrozenOuterVerifier:
    def __init__(self, modules: dict[str, Any], evidence: Any) -> None:
        self._modules = dict(modules)
        self._evidence = evidence

    @staticmethod
    def _process_allowed(arguments: Any) -> bool:
        del arguments
        return False

    def _invoke(self, name: str, *args: Any, **kwargs: Any) -> Any:
        previous_modules = {
            module_name: sys.modules.get(module_name)
            for module_name in self._modules
        }
        missing = {
            module_name
            for module_name in self._modules
            if module_name not in sys.modules
        }
        previous_dont_write = sys.dont_write_bytecode
        original_open = builtins.open
        original_io_open = io.open
        original_os_open = os.open
        original_socket = socket.socket
        original_popen = subprocess.Popen
        original_run = subprocess.run
        mutation_names = (
            "remove",
            "unlink",
            "rename",
            "replace",
            "mkdir",
            "makedirs",
            "rmdir",
            "removedirs",
            "chmod",
            "chown",
            "link",
            "symlink",
            "truncate",
        )
        original_mutations = {
            mutation_name: getattr(os, mutation_name)
            for mutation_name in mutation_names
        }

        def deny_mutation(*_args: Any, **_kwargs: Any) -> Any:
            raise StagerError("materialize_outer_verifier_guard")

        def guarded_open(file: Any, mode: str = "r", *values: Any, **options: Any) -> Any:
            del file, mode, values, options
            raise StagerError("materialize_outer_verifier_guard")

        def guarded_io_open(file: Any, mode: str = "r", *values: Any, **options: Any) -> Any:
            del file, mode, values, options
            raise StagerError("materialize_outer_verifier_guard")

        def guarded_os_open(path: Any, flags: int, *values: Any, **options: Any) -> Any:
            del path, flags, values, options
            raise StagerError("materialize_outer_verifier_guard")

        def guarded_socket(*_args: Any, **_kwargs: Any) -> Any:
            raise StagerError("materialize_outer_verifier_guard")

        def guarded_popen(arguments: Any, *values: Any, **options: Any) -> Any:
            del arguments, values, options
            raise StagerError("materialize_outer_verifier_guard")

        def guarded_run(arguments: Any, *values: Any, **options: Any) -> Any:
            del arguments, values, options
            raise StagerError("materialize_outer_verifier_guard")

        try:
            sys.dont_write_bytecode = True
            sys.modules.update(self._modules)
            builtins.open = guarded_open
            io.open = guarded_io_open
            os.open = guarded_os_open
            socket.socket = guarded_socket
            subprocess.Popen = guarded_popen
            subprocess.run = guarded_run
            for mutation_name in mutation_names:
                setattr(os, mutation_name, deny_mutation)
            function = getattr(self._evidence, name, None)
            if not callable(function):
                raise StagerError("materialize_outer_verifier")
            return function(*args, **kwargs)
        finally:
            for mutation_name, function in original_mutations.items():
                setattr(os, mutation_name, function)
            subprocess.run = original_run
            subprocess.Popen = original_popen
            socket.socket = original_socket
            os.open = original_os_open
            io.open = original_io_open
            builtins.open = original_open
            sys.dont_write_bytecode = previous_dont_write
            for module_name, previous in previous_modules.items():
                if module_name in missing:
                    sys.modules.pop(module_name, None)
                else:
                    sys.modules[module_name] = previous

    def validate_receipt(self, *args: Any, **kwargs: Any) -> Any:
        return self._invoke("validate_receipt", *args, **kwargs)

    def validate_evidence(self, *args: Any, **kwargs: Any) -> Any:
        return self._invoke("validate_evidence", *args, **kwargs)


def _load_outer_evidence_verifier(
    *,
    git_reader: Any = _stage_git_reader,
) -> Any:
    specs = (
        (
            "extract_item26_manual_cost_stop_raw_v2",
            EXTRACTOR_REF,
        ),
        (
            "verify_item26_manual_cost_stop_authority_v2",
            AUTHORITY_VERIFIER_REF,
        ),
        (
            "verify_item26_manual_cost_stop_evidence_v2",
            EVIDENCE_VERIFIER_REF,
        ),
    )
    sources: dict[str, tuple[str, bytes]] = {}
    for module_name, ref in specs:
        binding = FIXED_BINDINGS[ref]
        row = git_reader(binding["revision"], ref)
        if type(row) is not dict or set(row) != {"raw", "git_blob_oid"}:
            raise StagerError("materialize_outer_verifier")
        raw = row["raw"]
        if (
            type(raw) is not bytes
            or len(raw) != binding["size"]
            or _sha256_bytes(raw) != binding["file_sha256"]
            or row["git_blob_oid"] != binding["git_blob_oid"]
            or _git_blob_oid_bytes(raw) != binding["git_blob_oid"]
        ):
            raise StagerError("materialize_outer_verifier")
        sources[module_name] = (ref, raw)
    previous = {
        module_name: sys.modules.get(module_name)
        for module_name, _ref in specs
    }
    missing = {
        module_name
        for module_name, _ref in specs
        if module_name not in sys.modules
    }
    previous_dont_write = sys.dont_write_bytecode
    original_import = builtins.__import__
    original_open = builtins.open
    original_io_open = io.open
    original_os_open = os.open
    original_socket = socket.socket
    original_popen = subprocess.Popen
    original_run = subprocess.run
    mutation_names = (
        "remove",
        "unlink",
        "rename",
        "replace",
        "mkdir",
        "makedirs",
        "rmdir",
        "removedirs",
        "chmod",
        "chown",
        "link",
        "symlink",
        "truncate",
    )
    original_mutations = {
        mutation_name: getattr(os, mutation_name)
        for mutation_name in mutation_names
    }
    standard_import_roots = {
        "__future__",
        "argparse",
        "base64",
        "copy",
        "datetime",
        "decimal",
        "hashlib",
        "importlib",
        "json",
        "math",
        "os",
        "pathlib",
        "re",
        "stat",
        "subprocess",
        "tempfile",
        "typing",
    }
    allowed_import_roots = standard_import_roots | {
        module_name for module_name, _ref in specs
    }

    def deny_effect(*_args: Any, **_kwargs: Any) -> Any:
        raise StagerError("materialize_outer_verifier_guard")

    def frozen_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        root = name.split(".", 1)[0] if type(name) is str else None
        if level != 0 or root not in allowed_import_roots or root not in sys.modules:
            raise StagerError("materialize_outer_verifier_import")
        return original_import(name, globals, locals, fromlist, level)

    modules: dict[str, Any] = {}
    try:
        sys.dont_write_bytecode = True
        for module_name in sorted(standard_import_roots):
            original_import(module_name)
        for module_name, ref in specs:
            module = types.ModuleType(module_name)
            module.__file__ = str(Path(REPOSITORY_ROOT) / ref)
            module.__package__ = None
            modules[module_name] = module
            sys.modules[module_name] = module
        builtins.__import__ = frozen_import
        builtins.open = deny_effect
        io.open = deny_effect
        os.open = deny_effect
        socket.socket = deny_effect
        subprocess.Popen = deny_effect
        subprocess.run = deny_effect
        for mutation_name in mutation_names:
            setattr(os, mutation_name, deny_effect)
        for module_name, ref in specs:
            module = modules[module_name]
            frozen_builtins = dict(vars(builtins))
            frozen_builtins["__import__"] = frozen_import
            frozen_builtins["open"] = deny_effect
            module.__dict__["__builtins__"] = frozen_builtins
            source_ref, raw = sources[module_name]
            exec(compile(raw, source_ref, "exec"), module.__dict__)
    except BaseException:
        raise StagerError("materialize_outer_verifier") from None
    finally:
        for mutation_name, function in original_mutations.items():
            setattr(os, mutation_name, function)
        subprocess.run = original_run
        subprocess.Popen = original_popen
        socket.socket = original_socket
        os.open = original_os_open
        io.open = original_io_open
        builtins.open = original_open
        builtins.__import__ = original_import
        sys.dont_write_bytecode = previous_dont_write
        for module_name, old in previous.items():
            if module_name in missing:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = old
    evidence = modules["verify_item26_manual_cost_stop_evidence_v2"]
    if (
        not callable(getattr(evidence, "validate_receipt", None))
        or not callable(getattr(evidence, "validate_evidence", None))
    ):
        raise StagerError("materialize_outer_verifier")
    return _FrozenOuterVerifier(modules, evidence)


def _validate_materialize_capture_capsule(value: Any) -> dict[str, Any]:
    if (
        type(value) is not dict
        or set(value)
        != {
            "schema",
            "status",
            "provider",
            "actiontrail",
            "raw_value_exposed_count",
            "provider_dispatch_count",
            "automatic_retry_count",
            "cleanup_count",
        }
        or value.get("schema") != MATERIALIZE_CAPTURE_CAPSULE_SCHEMA
        or value.get("status") != "FINALIZED_CAPTURE_INVENTORY_READY"
        or type(value.get("raw_value_exposed_count")) is not int
        or value.get("raw_value_exposed_count") != 0
        or type(value.get("provider_dispatch_count")) is not int
        or not 5 <= value["provider_dispatch_count"] <= MAX_PROVIDER_DISPATCHES
        or type(value.get("automatic_retry_count")) is not int
        or value.get("automatic_retry_count") != 0
        or type(value.get("cleanup_count")) is not int
        or value.get("cleanup_count") != 0
    ):
        raise StagerError("materialize_capture_capsule")
    for name in ("provider", "actiontrail"):
        row = value.get(name)
        if (
            type(row) is not dict
            or set(row) != {"byte_count", "sha256"}
            or type(row.get("byte_count")) is not int
            or not 1
            <= row["byte_count"]
            <= MAX_FINALIZED_CAPTURE_ARTIFACT_BYTES
            or not _hex_text(row.get("sha256"), 64)
        ):
            raise StagerError("materialize_capture_capsule")
    return value


def _materialize_capture_interface_not_provisioned() -> dict[str, Any]:
    raise StagerError("materialize_capture_interface_not_provisioned")


def _build_materialize_runtime_arguments(
    source_revision: str,
    capture_capsule: Any,
    *,
    git_reader: Any = _stage_git_reader,
) -> tuple[str, ...]:
    if not _hex_text(source_revision, 40) or source_revision == BASE_REVISION:
        raise StagerError("materialize_source_revision")
    capsule = _validate_materialize_capture_capsule(capture_capsule)
    stager_row = git_reader(source_revision, STAGER_REF)
    if type(stager_row) is not dict or set(stager_row) != {"raw", "git_blob_oid"}:
        raise StagerError("materialize_stager_binding")
    stager_raw = stager_row["raw"]
    stager_oid = stager_row["git_blob_oid"]
    if (
        type(stager_raw) is not bytes
        or not stager_raw
        or not _hex_text(stager_oid, 40)
        or _git_blob_oid_bytes(stager_raw) != stager_oid
    ):
        raise StagerError("materialize_stager_binding")
    materialize_raw = MATERIALIZE_ROOT_PROGRAM.encode("ascii")
    return _validate_materialize_runtime_arguments(
        (
            source_revision,
            str(len(stager_raw)),
            _sha256_bytes(stager_raw),
            stager_oid,
            str(len(materialize_raw)),
            _sha256_bytes(materialize_raw),
            str(capsule["provider"]["byte_count"]),
            capsule["provider"]["sha256"],
            str(capsule["actiontrail"]["byte_count"]),
            capsule["actiontrail"]["sha256"],
        )
    )


def _future_capture_once(
    source_revision: str,
    acceptance_revision: str,
    *,
    credential_state: Any,
    dispatcher: Any,
    outer_identity_validator: Any = lambda: None,
    public_absence_checker: Any = _assert_public_m1_absent,
) -> dict[str, Any]:
    if not _hex_text(source_revision, 40) or not _hex_text(acceptance_revision, 40):
        raise StagerError("capture_revisions")
    if type(credential_state) is not dict or credential_state:
        raise StagerError("capture_credential_capsule")
    outer_identity_validator()
    public_absence_checker()
    raw = dispatcher()
    if set(credential_state) != {"projection", "ready_sha256"}:
        raise StagerError("capture_credential_capsule")
    projection = _validate_capture_credential_capsule(
        credential_state["projection"]
    )
    if (
        not _hex_text(credential_state.get("ready_sha256"), 64)
        or credential_state["ready_sha256"] != _c1_ready_sha256(projection)
    ):
        raise StagerError("capture_credential_capsule")
    result = _validate_capture_root_status(raw)
    outer_identity_validator()
    public_absence_checker()
    return result


def _future_materialize_once(
    source_revision: str,
    acceptance_revision: str,
    *,
    precreator: Any,
    capture_capsule_supplier: Any,
    runtime_arguments_builder: Any,
    dispatcher: Any,
    verifier_loader: Any,
    output_writer: Any = _write_materialize_output_once,
    identity_checker: Any = _check_materialize_output_identity,
    outer_identity_validator: Any = lambda: None,
    closer: Any = os.close,
    commit_state: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if not _hex_text(source_revision, 40) or not _hex_text(acceptance_revision, 40):
        raise StagerError("materialize_revisions")
    if commit_state is not None and (
        type(commit_state) is not dict or commit_state
    ):
        raise StagerError("materialize_commit_state")
    held: list[tuple[int, dict[str, Any]]] = []
    committed = False
    try:
        # Both names become durable empty O_EXCL residue before a capsule
        # supplier can perform any future sudo or root capture read.
        receipt_held, evidence_held = precreator()
        held = [receipt_held, evidence_held]
        descriptors = [row[0] for row in held]
        inodes = [row[1]["file"][:2] for row in held]
        if len(set(descriptors)) != 2 or len(set(inodes)) != 2:
            raise StagerError("materialize_public_alias")
        for descriptor, identity in held:
            identity_checker(descriptor, identity, expected_size=0)
        capsule = capture_capsule_supplier()
        runtime_arguments = runtime_arguments_builder(source_revision, capsule)
        output = dispatcher(runtime_arguments)
        if type(output) is not dict or set(output) != {"receipt", "evidence", "status"}:
            raise StagerError("materialize_output_bundle")
        child = _validate_materialize_child_status(output["status"])
        receipt = _decode_public_artifact(
            output["receipt"],
            schema=M1_RECEIPT_SCHEMA,
            maximum=MAX_MATERIALIZE_RECEIPT_BYTES,
        )
        evidence = _decode_public_artifact(
            output["evidence"],
            schema=M1_EVIDENCE_SCHEMA,
            maximum=MAX_MATERIALIZE_EVIDENCE_BYTES,
        )
        verifier = verifier_loader()
        _materialize_independent_validate_once(
            verifier,
            receipt,
            evidence,
            expected_control_revision=CONTROL_REVISION,
        )
        outer_identity_validator()
        for descriptor, identity in held:
            identity_checker(descriptor, identity, expected_size=0)
        result = {
            "schema": MATERIALIZE_OUTER_RESULT_SCHEMA,
            "status": "M1_RECEIPT_AND_EVIDENCE_MATERIALIZED",
            "source_revision": source_revision,
            "acceptance_revision": acceptance_revision,
            "receipt_path": receipt_held[1]["path"],
            "evidence_path": evidence_held[1]["path"],
            "receipt_write_count": 1,
            "evidence_write_count": 1,
            "root_invocation_count": 1,
            "sudo_dispatch_count": 1,
            "provider_dispatch_count": child["provider_dispatch_count"],
            "network_dispatch_count": child["network_dispatch_count"],
            "database_connection_count": child["database_connection_count"],
            "private_key_read_count": child["private_key_read_count"],
            "automatic_retry_count": 0,
            "cleanup_count": 0,
        }
        output_writer(
            receipt_held[0],
            receipt_held[1],
            output["receipt"],
            maximum=MAX_MATERIALIZE_RECEIPT_BYTES,
        )
        previous_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK,
            OUTER_COMMIT_SIGNALS,
        )
        try:
            output_writer(
                evidence_held[0],
                evidence_held[1],
                output["evidence"],
                maximum=MAX_MATERIALIZE_EVIDENCE_BYTES,
            )
            if commit_state is not None:
                commit_state["durable_result"] = result
            committed = True
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        return result
    finally:
        for descriptor, _identity in held:
            try:
                closer(descriptor)
            except BaseException as exc:
                if not committed:
                    # Failure remains failure and the O_EXCL residue remains;
                    # no close error authorizes a retry or cleanup.
                    _ = exc


def _parse_future_mode(arguments: Any) -> tuple[str, str, str]:
    if (
        type(arguments) is not list
        or len(arguments) != 3
        or arguments[0] not in {"--stage", "--capture", "--materialize"}
        or not _hex_text(arguments[1], 40)
        or not _hex_text(arguments[2], 40)
    ):
        raise StagerError("future_arguments")
    return arguments[0][2:], arguments[1], arguments[2]


def _run_future_mode(*args: Any, **kwargs: Any) -> None:
    _execution_gate()
    _run_future_mode_after_gate(*args, **kwargs)


def _run_future_mode_after_gate(
    arguments: list[str],
    *,
    stage_runner: Any,
    capture_runner: Any = None,
    materialize_runner: Any = None,
) -> Any:
    mode, source_revision, acceptance_revision = _parse_future_mode(arguments)
    runner = {
        "stage": stage_runner,
        "capture": capture_runner,
        "materialize": materialize_runner,
    }[mode]
    if not callable(runner):
        raise StagerError("future_mode_unbound")
    return runner(source_revision, acceptance_revision)


def _default_future_stage(
    source_revision: str,
    acceptance_revision: str,
) -> dict[str, Any]:
    tools = _stage_system_tool_snapshot()
    repository = _stage_repository_snapshot()
    topology = _stage_topology_snapshot(source_revision, acceptance_revision)
    if (
        _stage_system_tool_snapshot() != tools
        or _stage_repository_snapshot() != repository
    ):
        raise StagerError("stage_outer_identity_drift")

    def validate_outer_identity() -> None:
        if (
            _stage_system_tool_snapshot() != tools
            or _stage_repository_snapshot() != repository
            or _stage_topology_snapshot(source_revision, acceptance_revision)
            != topology
        ):
            raise StagerError("stage_outer_identity_drift")

    return _future_stage_once(
        source_revision,
        acceptance_revision,
        topology_snapshot=topology,
        git_reader=_stage_git_reader,
        system_tool_snapshot=tools,
        repository_snapshot=repository,
        dispatcher=lambda raw: _dispatch_stage_root_once(
            raw,
            expected_tool_snapshot=tools,
        ),
        outer_identity_validator=validate_outer_identity,
    )


def _default_future_capture(
    source_revision: str,
    acceptance_revision: str,
    *,
    credential_session_factory: Any = _capture_c1_root_session_not_provisioned,
    c1_git_reader: Any = _stage_git_reader,
) -> dict[str, Any]:
    # This factory is the first boundary and is shipped NOT_PROVISIONED.  A
    # future action may return only the single-root-session dispatcher; it may
    # not construct or export a capsule in this unprivileged process.
    session_dispatcher = credential_session_factory()
    if not callable(session_dispatcher):
        raise StagerError("capture_c1_session")
    c1_receipt = _validate_c1_fixed_git_binding(git_reader=c1_git_reader)
    c1_api = _load_bound_c1_capsule_api(c1_receipt["raw"])
    c1_binding = _validate_c1_source_identity(c1_receipt["identity"])
    runtime_arguments = _build_capture_runtime_arguments(acceptance_revision)
    tools = _stage_system_tool_snapshot()
    repository = _stage_repository_snapshot()
    topology = _stage_topology_snapshot(source_revision, acceptance_revision)
    credential_state: dict[str, Any] = {}

    def validate_outer_identity() -> None:
        if (
            _stage_system_tool_snapshot() != tools
            or _stage_repository_snapshot() != repository
            or _stage_topology_snapshot(source_revision, acceptance_revision)
            != topology
            or _validate_c1_fixed_git_binding(git_reader=c1_git_reader)[
                "identity"
            ]
            != c1_binding
        ):
            raise StagerError("capture_outer_identity_drift")

    def validate_public_outer_identity() -> None:
        validate_outer_identity()
        _assert_public_m1_absent()

    def accept_credential_ready(raw: Any) -> dict[str, Any]:
        if credential_state:
            raise StagerError("capture_c1_handshake")
        ready = _validate_c1_handshake_frame(
            raw,
            expected_status=C1_READY_STATUS,
            expected_ack_count=0,
        )
        projection = _validate_capture_credential_capsule(
            ready["projection"]
        )
        credential_state.update(
            {
                "projection": dict(projection),
                "ready_sha256": ready["ready_sha256"],
            }
        )
        return _c1_handshake_frame(
            projection,
            status=C1_ACK_STATUS,
            ack_count=1,
        )

    return _future_capture_once(
        source_revision,
        acceptance_revision,
        credential_state=credential_state,
        dispatcher=lambda: session_dispatcher(
            runtime_arguments,
            tool_snapshot=tools,
            capsule_api=c1_api,
            credential_ready_validator=accept_credential_ready,
            pre_ack_identity_validator=validate_public_outer_identity,
        ),
        outer_identity_validator=validate_outer_identity,
    )


def _default_future_materialize(
    source_revision: str,
    acceptance_revision: str,
    *,
    capture_capsule_supplier: Any = _materialize_capture_interface_not_provisioned,
    commit_state: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {}

    def supply_capture_capsule() -> dict[str, Any]:
        tools = _stage_system_tool_snapshot()
        repository = _stage_repository_snapshot()
        topology = _stage_topology_snapshot(
            source_revision,
            acceptance_revision,
        )
        context.update(
            {
                "tools": tools,
                "repository": repository,
                "topology": topology,
            }
        )
        return capture_capsule_supplier()

    def validate_outer_identity() -> None:
        if set(context) != {"tools", "repository", "topology"}:
            raise StagerError("materialize_outer_identity_unbound")
        if (
            _stage_system_tool_snapshot() != context["tools"]
            or _stage_repository_snapshot() != context["repository"]
            or _stage_topology_snapshot(source_revision, acceptance_revision)
            != context["topology"]
        ):
            raise StagerError("materialize_outer_identity_drift")

    return _future_materialize_once(
        source_revision,
        acceptance_revision,
        precreator=_precreate_materialize_outputs,
        capture_capsule_supplier=supply_capture_capsule,
        runtime_arguments_builder=_build_materialize_runtime_arguments,
        dispatcher=lambda arguments: (
            validate_outer_identity()
            or _dispatch_materialize_root_once(
                arguments,
                tool_snapshot=context["tools"],
            )
        ),
        verifier_loader=_load_outer_evidence_verifier,
        outer_identity_validator=validate_outer_identity,
        commit_state=commit_state,
    )


CAPTURE_ROOT_PROGRAM = r'''
import fcntl
import hashlib
import hmac
import json
import math
import os
import resource
import selectors
import signal
import socket
import stat
import subprocess
import sys
import time
import types

EXECUTION_ENABLED = False
SOURCE_ONLY_IMPLEMENTATION_STATUS = "SOURCE_ONLY_IMPLEMENTATION_COMPLETE_NOT_AUTHORIZED"
CONTROL_REVISION = "68aa82ffbdd43e78e585d8956d13d3030ef6a640"
SLOTS = (
    "cost_stop_rds_write_lookup_page",
    "clone_create_lookup_page",
    "fresh_clone_inventory",
    "fresh_source_inventory",
    "historical_billing_snapshot",
)
OPERATIONS = {
    "cost_stop_rds_write_lookup_page": ("LookupEvents", "2020-07-06"),
    "clone_create_lookup_page": ("LookupEvents", "2020-07-06"),
    "fresh_clone_inventory": ("DescribeDBInstances", "2014-08-15"),
    "fresh_source_inventory": ("DescribeDBInstances", "2014-08-15"),
    "historical_billing_snapshot": ("QueryInstanceBill", "2017-12-14"),
}
MAX_PROVIDER_DISPATCHES = 64
MAX_RECORD_SECONDS = 840
FULL_CAPTURE_TIMEOUT_SECONDS = 840
POST_CAPTURE_IDENTITY_DEADLINE_SECONDS = 30
POST_CAPTURE_MAX_FILE_READ_COUNT = 18
MAX_ACTIVE_CHILDREN = 1
PARALLEL_DISPATCH_COUNT = 0
ADAPTER_CHILD_FLAGS = ("-I", "-S", "-B")
FD_CHANNELS = (
    "logical_request",
    "temporary_sts",
    "raw_response",
    "fixed_status",
)
RUNTIME_DIRECTORY = "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-m1-capture"
EXISTING_RUNTIME_DIRECTORY = "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-tools"
AUTHORITY_DIRECTORY = "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2"
JOURNAL_DIRECTORY = "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-journal"
REPOSITORY_ROOT = "/Users/openclaw/Desktop/noteai"
REPOSITORY_OWNER_UID = 501
REPOSITORY_OWNER_GID = 20
MAX_REPOSITORY_PACK_FILES = 4096
CAPTURE_PROGRAM_PATH = RUNTIME_DIRECTORY + "/capture-root-program.py"
ADAPTER_PATH = RUNTIME_DIRECTORY + "/item26_aliyun_official_read_v2.py"
CAPTURE_MANIFEST_PATH = RUNTIME_DIRECTORY + "/capture-runtime-manifest.json"
COLLECTOR_PATH = EXISTING_RUNTIME_DIRECTORY + "/collect_item26_manual_cost_stop_raw_v2.py"
EXTRACTOR_PATH = EXISTING_RUNTIME_DIRECTORY + "/extract_item26_manual_cost_stop_raw_v2.py"
AUTHORITY_PATH = EXISTING_RUNTIME_DIRECTORY + "/verify_item26_manual_cost_stop_authority_v2.py"
PYTHON_RUNTIME_EXECUTABLE = "/Library/Developer/CommandLineTools/usr/bin/python3"
PYTHON_RESOLVED_EXECUTABLE = "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9"
ADAPTER_SOURCE_REVISION = "65b82ffd890479315c9a93769cf11e2a9d27074b"
ADAPTER_ACCEPTANCE_REVISION = "a30b879d06c388a4a0e230b5a23b2eaedc93649d"
ADAPTER_SHA256 = "719886d2846a7602bf3fc0529f5c191305b58465c668d171461860d4c60aadb9"
ADAPTER_BYTES = 31410
C1_CAPSULE_REF = "tools/item26_aliyun_temporary_sts_capsule_v1.py"
C1_CAPSULE_SOURCE_REVISION = "86206f816fb092a7fca7a577b1391e251dfca5ca"
C1_CAPSULE_ACCEPTANCE_REVISION = "314a6b885bc7bda9790074a201ac176e498326b5"
C1_CAPSULE_GIT_BLOB_OID = "99110863d055929fbc76950ec2bc9aa8fd0f7bc6"
C1_CAPSULE_SHA256 = "7ed50fd5acdbb5733a174367e8bcb339b3a6bc07b49fed3a31243fddf763e4e3"
C1_CAPSULE_BYTES = 49494
C1_RUNTIME_ROOT = "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-m1-credential-runtime"
C1_CUSTODY_ROOT = "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-m1-credential-custody"
C1_CAPSULE_PATH = C1_RUNTIME_ROOT + "/item26_aliyun_temporary_sts_capsule_v1.py"
C1_SOURCE_SCHEMA = "noteai.item26.aliyun-temporary-sts-capsule-source.v1"
C1_INTERFACE_SCHEMA = "noteai.item26.m1-root-custody-temporary-sts-interface.v1"
C1_HANDSHAKE_SCHEMA = "noteai.item26.m1-c1-capture-handshake.v1"
C1_READY_BINDING_SCHEMA = "noteai.item26.m1-c1-ready-binding.v1"
C1_READY_STATUS = "ROOT_CUSTODY_TEMPORARY_STS_READY_FOR_CAPTURE_ACK"
C1_ACK_STATUS = "ROOT_CUSTODY_TEMPORARY_STS_CAPTURE_ACKNOWLEDGED"
C1_READY_SHA256_DOMAIN = b"noteai.item26.m1-c1-ready-sha256.v1\0"
MAX_C1_HANDSHAKE_BYTES = 4096
C1_SESSION_SETUP_TIMEOUT_SECONDS = 20
COLLECTOR_SHA256 = "739b8e8bea29250ccd4c24b400af791c67e687f0cecd23a4b1ddbc8b70750ea4"
COLLECTOR_BYTES = 85025
EXTRACTOR_SHA256 = "7264bc6d1b3028c141a32d56a69e248fac283c835f776ed6f7c09b9f1c2d0fd4"
EXTRACTOR_BYTES = 62917
AUTHORITY_SHA256 = "19cc65133410cfa4face4887943504c8726430cc196b4f83d68cb3e0675a959d"
AUTHORITY_BYTES = 125914
ACTIVATION_RECEIPT_SHA256 = "61b756abed72b2f6ab8fb3b20a260b03c0932f6e4c271c4f723a4e5942cd7f2a"
ACTIVATION_RECEIPT_BYTES = 22068
EXPECTED_OLD_CLONE_SHA256 = "820121638125fcebe3b7c03f3416ddae1fef1a0a9f1de731320fa75dd69a1525"
EXPECTED_SOURCE_SHA256 = "d3712c09b28ee82257ab128fa1b5ba79b223f8b774e5fa20f761a2c4782eee8d"
MAX_REQUEST_BYTES = 32768
MAX_CREDENTIAL_BYTES = 131072
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_STATUS_BYTES = 4096
MINIMUM_STS_SECONDS = 960
INITIAL_MINIMUM_STS_SECONDS = 1860
MAXIMUM_STS_SECONDS = 86400
CHILD_TIMEOUT_SECONDS = 45
CHILD_REAP_GRACE_SECONDS = 2
CHILD_ENV = {
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
}
GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "HOME": "/var/empty",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/Library/Developer/CommandLineTools/usr/bin:/usr/bin:/bin",
}
CHILD_STATUS_SCHEMA = "noteai.item26.m1-adapter-child-status.v1"
CAPTURE_SUCCESS_SCHEMA = "noteai.item26.m1-capture-root-result.v1"
CAPTURE_PUBLIC_STATUS_SCHEMA = "noteai.item26.m1-capture-root-public-status.v1"
RUNTIME_MANIFEST_SCHEMA = "noteai.item26.m1-root-runtime-manifest.v1"
CAPTURE_RUNTIME_NAMES = frozenset({
    "capture-root-program.py",
    "item26_aliyun_official_read_v2.py",
    "capture-runtime-manifest.json",
})
EXISTING_RUNTIME_BINDINGS = {
    "collect_item26_manual_cost_stop_raw_v2.py": (COLLECTOR_BYTES, COLLECTOR_SHA256, 0o600),
    "extract_item26_manual_cost_stop_raw_v2.py": (EXTRACTOR_BYTES, EXTRACTOR_SHA256, 0o600),
    "verify_item26_manual_cost_stop_authority_v2.py": (AUTHORITY_BYTES, AUTHORITY_SHA256, 0o600),
    "runtime-activation-receipt-v3.json": (ACTIVATION_RECEIPT_BYTES, ACTIVATION_RECEIPT_SHA256, 0o600),
}
CHILD_SYSTEM_TOOL_BINDINGS = {
    "/usr/bin/python3": {
        "sha256": "179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818",
        "size": 118928,
        "mode": 0o755,
        "uid": 0,
        "gid": 0,
        "nlink": 78,
    },
    "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9": {
        "sha256": "4b42b1a117605cafc8607b67b0892a609c2cd125012dd56288abeed8c89cdfb1",
        "size": 102352,
        "mode": 0o755,
        "uid": 0,
        "gid": 0,
        "nlink": 1,
    },
    "/etc/ssl/cert.pem": {
        "sha256": "9dae8d76e55cb08991f2b672d58999ea15560d910759c16b544f843bdffbb994",
        "size": 333483,
        "mode": 0o644,
        "uid": 0,
        "gid": 0,
        "nlink": 1,
    },
    "/usr/bin/git": {
        "sha256": "179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818",
        "size": 118928,
        "mode": 0o755,
        "uid": 0,
        "gid": 0,
        "nlink": 78,
    },
    "/Library/Developer/CommandLineTools/usr/bin/git": {
        "sha256": "3121e7e4d16059539731c58d94888709c12904abe922acde8e37caef4607c1d1",
        "size": 7604272,
        "mode": 0o755,
        "uid": 0,
        "gid": 0,
        "nlink": 1,
    },
    "/usr/bin/openssl": {
        "sha256": "517827f877751b6d7abebe404a296fa8e82425c63694a73ab06db35e6d9a8362",
        "size": 1134000,
        "mode": 0o755,
        "uid": 0,
        "gid": 0,
        "nlink": 1,
    },
}
CHILD_TOOL_BINDINGS = {
    **CHILD_SYSTEM_TOOL_BINDINGS,
    ADAPTER_PATH: {
        "sha256": ADAPTER_SHA256,
        "size": ADAPTER_BYTES,
        "mode": 0o500,
        "uid": 0,
        "gid": 0,
        "nlink": 1,
    },
}
LOCAL_OBJECT_BINDINGS = {
    C1_CAPSULE_REF: {
        "accepted_revision": C1_CAPSULE_ACCEPTANCE_REVISION,
        "source_revision": C1_CAPSULE_SOURCE_REVISION,
        "blob_oid": C1_CAPSULE_GIT_BLOB_OID,
        "sha256": C1_CAPSULE_SHA256,
        "size": C1_CAPSULE_BYTES,
    },
    "tools/item26_aliyun_official_read_v2.py": {
        "accepted_revision": ADAPTER_ACCEPTANCE_REVISION,
        "source_revision": ADAPTER_SOURCE_REVISION,
        "blob_oid": "f53a01805ea68005ca9e56a08dfa491221c224cf",
        "sha256": ADAPTER_SHA256,
        "size": ADAPTER_BYTES,
    },
    "tools/collect_item26_manual_cost_stop_raw_v2.py": {
        "accepted_revision": CONTROL_REVISION,
        "source_revision": CONTROL_REVISION,
        "blob_oid": "e584b87cb7c2dcea46efe5ba01042e7e7e0d94e0",
        "sha256": COLLECTOR_SHA256,
        "size": COLLECTOR_BYTES,
    },
    "tools/extract_item26_manual_cost_stop_raw_v2.py": {
        "accepted_revision": CONTROL_REVISION,
        "source_revision": CONTROL_REVISION,
        "blob_oid": "64b87e4630b894f57f64317e0b3cb70b8367e153",
        "sha256": EXTRACTOR_SHA256,
        "size": EXTRACTOR_BYTES,
    },
    "tools/verify_item26_manual_cost_stop_authority_v2.py": {
        "accepted_revision": CONTROL_REVISION,
        "source_revision": CONTROL_REVISION,
        "blob_oid": "91d5eaf9d63f3595c257ad31502407d1bb9a3cb0",
        "sha256": AUTHORITY_SHA256,
        "size": AUTHORITY_BYTES,
    },
}
CONTRACT = {
    "schema": "noteai.item26.m1-capture-root-scaffold-contract.v1",
    "status": SOURCE_ONLY_IMPLEMENTATION_STATUS,
    "requires_new_cto_authorization": True,
    "implementation_complete": True,
    "operational_ready": False,
    "runtime_mode": "0700",
    "fd_count": 4,
    "fd_transport": "AF_UNIX_SOCK_STREAM",
    "fd_direction_and_f_getfl_preflight_required": True,
    "child_close_fds_and_exact_pass_fds_required": True,
    "fd_blocking_o_rdwr_no_async_required": True,
    "four_channels_half_close_and_eof_required": True,
    "core_limit_and_clean_environment_before_fd_read": True,
    "raw_argv_env_file_stdout_stderr_allowed": False,
    "process_group_kill_reap_and_absence_proof_required": True,
    "collector_finish_unknown_and_bridge_unknown_mutually_exclusive": True,
    "bridge_unknown_requires_future_authorization_and_dead_group": True,
    "token_cycle_rejected": True,
    "identifier_derivation_memory_only_with_extractor_parity": True,
    "page_order": (
        "begin_success_observed",
        "spawn_once",
        "concurrent_drain",
        "finish_same_raw_at_most_once",
        "finish_success_observed",
        "derive_token_or_identifier",
    ),
    "credential_interface_status": "NOT_PROVISIONED",
    "credential_capsule_source_ref": C1_CAPSULE_REF,
    "credential_capsule_live_session_required": True,
    "credential_capsule_opaque_receipts_required": True,
    "credential_capsule_default_factory_provisioned": False,
    "minimum_temporary_sts_validity_seconds": 960,
    "initial_minimum_temporary_sts_validity_seconds": 1860,
    "temporary_sts_checked_before_every_begin": True,
    "credential_refresh_or_configure_allowed": False,
    "fd_only_signature_verifier_required": True,
    "authority_git_no_lazy_fetch_patch_before_collector": True,
    "missing_local_object_provider_child_count": 0,
    "authorized_and_incurred_cny": "0.00",
    "cloud_write_database_private_key_counts": 0,
}
STATUS = {
    "schema": "noteai.item26.m1-capture-root-source.v1",
    "status": SOURCE_ONLY_IMPLEMENTATION_STATUS,
    "authorizes_execution": False,
    "implementation_complete": True,
    "operational_ready": False,
    "provider_dispatch_count": 0,
    "capture_count": 0,
    "root_write_count": 0,
    "cleanup_count": 0,
    "automatic_retry_count": 0,
    "replay_count": 0,
    "authorized_cny": "0.00",
    "incurred_cny": "0.00",
    "cloud_write_count": 0,
    "database_connection_count": 0,
    "database_transaction_count": 0,
    "database_write_count": 0,
    "private_key_read_count": 0,
    "private_key_write_count": 0,
    "private_key_output_count": 0,
    "oauth_configuration_count": 0,
    "oauth_refresh_count": 0,
}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n"

class CaptureError(RuntimeError):
    def __init__(self, code, state=None):
        super().__init__(code)
        self.code = code
        self.state = dict(state or {})

CAPTURE_TERMINATION_SIGNALS = (
    signal.SIGTERM,
    signal.SIGINT,
    signal.SIGHUP,
    signal.SIGQUIT,
    signal.SIGALRM,
)
ACTIVE_ADAPTER_PROCESS = None
ACTIVE_CAPTURE_AUX_PROCESS = None
CAPTURE_TERMINATION_REQUESTED = False

class CaptureSignal(BaseException):
    pass

def _capture_signal_handler(_signum, _frame):
    global CAPTURE_TERMINATION_REQUESTED
    CAPTURE_TERMINATION_REQUESTED = True
    raise CaptureSignal()

def _install_capture_signal_handlers(*, installer=signal.signal):
    for signum in CAPTURE_TERMINATION_SIGNALS:
        installer(signum, _capture_signal_handler)
    return True

def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()

def _value_sha256(value):
    if type(value) is not str or not value:
        raise CaptureError("identifier_shape")
    return _sha256(value.encode("utf-8"))

def _reject_constant(_raw):
    raise CaptureError("json_number")

def _reject_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise CaptureError("json_duplicate")
        value[key] = item
    return value

def _strict_object(raw, maximum, code):
    if type(raw) is not bytes or not raw or len(raw) > maximum:
        raise CaptureError(code)
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except CaptureError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        raise CaptureError(code) from None
    if type(value) is not dict:
        raise CaptureError(code)
    return value

def _c1_canonical(value):
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii") + b"\n"
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise CaptureError("credential_handshake") from None

def _validate_root_c1_projection(value, minimum):
    if (
        type(value) is not dict
        or set(value) != {
            "schema",
            "status",
            "account_binding_sha256",
            "minimum_remaining_validity_seconds",
            "credential_payload_exposed",
            "oauth_refresh_count",
            "oauth_configure_count",
        }
        or value.get("schema") != C1_INTERFACE_SCHEMA
        or value.get("status") != "ROOT_CUSTODY_TEMPORARY_STS_READY"
        or not _sha256_text(value.get("account_binding_sha256"))
        or type(value.get("minimum_remaining_validity_seconds")) is not int
        or not minimum
        <= value["minimum_remaining_validity_seconds"]
        <= MAXIMUM_STS_SECONDS
        or value.get("credential_payload_exposed") is not False
        or type(value.get("oauth_refresh_count")) is not int
        or value["oauth_refresh_count"] != 0
        or type(value.get("oauth_configure_count")) is not int
        or value["oauth_configure_count"] != 0
    ):
        raise CaptureError("credential_projection")
    return value

def _root_c1_ready_sha256(projection):
    projection = _validate_root_c1_projection(
        projection,
        INITIAL_MINIMUM_STS_SECONDS,
    )
    binding = {
        "schema": C1_READY_BINDING_SCHEMA,
        "ready_status": C1_READY_STATUS,
        "projection": projection,
        "capsule_source_revision": C1_CAPSULE_SOURCE_REVISION,
        "capsule_acceptance_revision": C1_CAPSULE_ACCEPTANCE_REVISION,
    }
    return _sha256(C1_READY_SHA256_DOMAIN + _c1_canonical(binding))

def _root_c1_frame(projection, status, ack_count):
    if (
        status not in {C1_READY_STATUS, C1_ACK_STATUS}
        or type(ack_count) is not int
        or ack_count != (0 if status == C1_READY_STATUS else 1)
    ):
        raise CaptureError("credential_handshake")
    projection = _validate_root_c1_projection(
        projection,
        INITIAL_MINIMUM_STS_SECONDS,
    )
    return {
        "schema": C1_HANDSHAKE_SCHEMA,
        "status": status,
        "projection": dict(projection),
        "ready_sha256": _root_c1_ready_sha256(projection),
        "capsule_source_revision": C1_CAPSULE_SOURCE_REVISION,
        "capsule_acceptance_revision": C1_CAPSULE_ACCEPTANCE_REVISION,
        "ack_count": ack_count,
    }

def _validate_root_c1_ack(raw, projection):
    if (
        type(raw) not in {bytes, bytearray}
        or not 1 <= len(raw) <= MAX_C1_HANDSHAKE_BYTES
        or 0 in raw
    ):
        raise CaptureError("credential_handshake")
    try:
        value = json.loads(
            bytes(raw).decode("ascii"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except CaptureError:
        raise CaptureError("credential_handshake") from None
    except (UnicodeError, ValueError, RecursionError):
        raise CaptureError("credential_handshake") from None
    expected = _root_c1_frame(projection, C1_ACK_STATUS, 1)
    if (
        type(value) is not dict
        or _c1_canonical(value) != bytes(raw)
        or value != expected
        or not hmac.compare_digest(
            value.get("ready_sha256", ""),
            expected["ready_sha256"],
        )
    ):
        raise CaptureError("credential_handshake")
    return value

def _validate_root_c1_module(module):
    required = (
        "read_anonymous_frame",
        "root_custody_contract",
        "scrub_bytearray",
        "source_only_status",
        "validate_fd_roles",
        "validate_root_custody_inventory",
        "write_anonymous_frame",
    )
    if type(module) is not types.ModuleType:
        raise CaptureError("credential_source_api")
    try:
        constants = (
            module.SOURCE_SCHEMA,
            module.INTERFACE_SCHEMA,
            module.INITIAL_MINIMUM_VALIDITY_SECONDS,
            module.PER_BEGIN_MINIMUM_VALIDITY_SECONDS,
            module.MAXIMUM_VALIDITY_SECONDS,
            module.MAX_PROVIDER_DISPATCHES,
        )
        functions = tuple(getattr(module, name) for name in required)
        status = module.source_only_status()
        contract = module.root_custody_contract()
        capsule_type = module._RootCustodyTemporaryStsCapsule
        issued_type = module.IssuedTemporarySts
    except Exception:
        raise CaptureError("credential_source_api") from None
    zero_counts = (
        "cli_install_count",
        "cli_configure_count",
        "oauth_configure_count",
        "oauth_refresh_count",
        "credential_read_count",
        "root_read_count",
        "root_write_count",
        "filesystem_mutation_count",
        "subprocess_count",
        "network_call_count",
        "provider_call_count",
        "database_connection_count",
        "capture_count",
        "materialization_count",
        "automatic_retry_count",
        "cleanup_count",
    )
    if (
        constants
        != (
            C1_SOURCE_SCHEMA,
            C1_INTERFACE_SCHEMA,
            INITIAL_MINIMUM_STS_SECONDS,
            MINIMUM_STS_SECONDS,
            MAXIMUM_STS_SECONDS,
            MAX_PROVIDER_DISPATCHES,
        )
        or any(not callable(function) for function in functions)
        or type(capsule_type) is not type
        or type(issued_type) is not type
        or type(status) is not dict
        or status.get("schema") != C1_SOURCE_SCHEMA
        or status.get("status")
        != "SOURCE_ONLY_IMPLEMENTATION_COMPLETE_NOT_AUTHORIZED"
        or status.get("implementation_complete") is not True
        or status.get("authorizes_execution") is not False
        or status.get("operational_ready") is not False
        or status.get("credential_capsule_status") != "NOT_PROVISIONED"
        or status.get("execution_gates") != {
            "cli_oauth_configuration": False,
            "credential_projection": False,
            "root_custody_stage": False,
            "capture_integration": False,
        }
        or any(type(status.get(key)) is not int or status[key] != 0 for key in zero_counts)
        or status.get("authorized_cny") != "0.00"
        or status.get("incurred_cny") != "0.00"
        or type(contract) is not dict
        or contract.get("runtime_root") != C1_RUNTIME_ROOT
        or contract.get("custody_root") != C1_CUSTODY_ROOT
        or contract.get("directory_mode") != 0o700
        or contract.get("file_mode") != 0o600
        or contract.get("root_uid") != 0
        or contract.get("wheel_gid") != 0
        or contract.get("file_nlink") != 1
        or contract.get("exact_inventory_required") is not True
        or C1_CAPSULE_PATH not in contract.get("file_paths", ())
    ):
        raise CaptureError("credential_source_api")
    return module

def _load_root_c1_module(raw):
    if (
        type(raw) is not bytes
        or len(raw) != C1_CAPSULE_BYTES
        or _sha256(raw) != C1_CAPSULE_SHA256
        or hashlib.sha1(
            b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
        ).hexdigest()
        != C1_CAPSULE_GIT_BLOB_OID
    ):
        raise CaptureError("credential_source_identity")
    name = "_noteai_item26_root_c1_capsule_accepted"
    previous = sys.modules.get(name)
    had_previous = name in sys.modules
    try:
        module = types.ModuleType(name)
        module.__file__ = C1_CAPSULE_PATH
        module.__package__ = ""
        sys.modules[name] = module
        exec(
            compile(raw, C1_CAPSULE_PATH, "exec", dont_inherit=True, optimize=0),
            module.__dict__,
        )
    except BaseException:
        raise CaptureError("credential_source_api") from None
    finally:
        if had_previous:
            sys.modules[name] = previous
        else:
            sys.modules.pop(name, None)
    return _validate_root_c1_module(module)

def _root_c1_source_not_provisioned():
    raise CaptureError("root_custody_temporary_sts_not_provisioned")

def _root_c1_live_session_not_provisioned(_module):
    raise CaptureError("root_custody_temporary_sts_not_provisioned")

def _prepare_root_c1_live_session(
    module,
    session_factory,
    *,
    wall_clock,
    monotonic_ns_clock,
):
    module = _validate_root_c1_module(module)
    if not callable(session_factory):
        raise CaptureError("credential_session")
    capsule = None
    context = None
    failure = None
    try:
        session = session_factory(module)
        if type(session) is dict:
            candidate = session.get("capsule")
            if type(candidate) is module._RootCustodyTemporaryStsCapsule:
                capsule = candidate
        if (
            type(session) is not dict
            or set(session) != {
                "capsule",
                "live_snapshot",
                "creation_receipts",
            }
        ):
            raise CaptureError("credential_session")
        if type(capsule) is not module._RootCustodyTemporaryStsCapsule:
            raise CaptureError("credential_capsule")
        if type(capsule.round_count) is not int or capsule.round_count != 0:
            raise CaptureError("credential_capsule_freshness")
        contract = module.validate_root_custody_inventory(
            session["live_snapshot"],
            creation_receipts=session["creation_receipts"],
        )
        source_row = session["live_snapshot"]["file_lstat"][C1_CAPSULE_PATH]
        if (
            contract != module.root_custody_contract()
            or type(source_row) is not dict
            or source_row.get("size") != C1_CAPSULE_BYTES
            or source_row.get("sha256") != C1_CAPSULE_SHA256
        ):
            raise CaptureError("credential_inventory")
        wall_now = wall_clock()
        monotonic_now = monotonic_ns_clock()
        if type(wall_now) is not int or type(monotonic_now) is not int:
            raise CaptureError("credential_clock")
        projection = _validate_root_c1_projection(
            capsule.project_m1_interface(
                wall_now_unix=wall_now,
                monotonic_now_ns=monotonic_now,
            ),
            INITIAL_MINIMUM_STS_SECONDS,
        )
        ready = _root_c1_frame(projection, C1_READY_STATUS, 0)
        context = {
            "module": module,
            "capsule": capsule,
            "live_snapshot": session["live_snapshot"],
            "creation_receipts": session["creation_receipts"],
            "inventory_contract": contract,
            "projection": dict(projection),
            "ready_frame": ready,
            "wall_clock": wall_clock,
            "monotonic_ns_clock": monotonic_ns_clock,
            "handshake_attempt_count": 0,
            "acknowledged": False,
        }
    except BaseException as exc:
        failure = exc
    if failure is not None or context is None:
        if capsule is not None:
            try:
                capsule.scrub()
            except BaseException:
                pass
        if isinstance(failure, CaptureSignal):
            raise failure
        raise CaptureError("credential_session") from None
    return context

def _complete_root_c1_handshake(context, ready_fd, ack_fd, *, closer=os.close):
    if (
        type(context) is not dict
        or set(context) != {
            "module",
            "capsule",
            "live_snapshot",
            "creation_receipts",
            "inventory_contract",
            "projection",
            "ready_frame",
            "wall_clock",
            "monotonic_ns_clock",
            "handshake_attempt_count",
            "acknowledged",
        }
        or type(context.get("handshake_attempt_count")) is not int
        or context["handshake_attempt_count"] != 0
        or context.get("acknowledged") is not False
        or type(ready_fd) is not int
        or type(ack_fd) is not int
        or ready_fd < 3
        or ack_fd < 3
        or ready_fd == ack_fd
        or not callable(closer)
    ):
        raise CaptureError("credential_handshake")
    context["handshake_attempt_count"] = 1
    ready_frame = context.pop("ready_frame")
    module = None
    ready_raw = ack_raw = None
    failure = None
    try:
        module = _validate_root_c1_module(context.get("module"))
        module.validate_fd_roles(
            ack_fd,
            ready_fd,
            fstat_fn=_c1_platform_fstat,
        )
        ready_raw = bytearray(_c1_canonical(ready_frame))
        module.write_anonymous_frame(
            ready_fd,
            ready_raw,
            MAX_C1_HANDSHAKE_BYTES,
            fstat_fn=_c1_platform_fstat,
        )
        ack_raw = module.read_anonymous_frame(
            ack_fd,
            MAX_C1_HANDSHAKE_BYTES,
            fstat_fn=_c1_platform_fstat,
        )
        _validate_root_c1_ack(ack_raw, context["projection"])
        wall_now = context["wall_clock"]()
        monotonic_now = context["monotonic_ns_clock"]()
        initial = _initial_credential_capsule(
            context["capsule"].initial_probe(
                wall_now_unix=wall_now,
                monotonic_now_ns=monotonic_now,
            )
        )
        if (
            initial["account_binding_sha256"]
            != context["projection"]["account_binding_sha256"]
            or initial["initial_remaining_seconds"]
            > context["projection"]["minimum_remaining_validity_seconds"]
        ):
            raise CaptureError("initial_temporary_sts")
        context["initial"] = {
            "remaining_seconds": initial["initial_remaining_seconds"],
            "account_binding_sha256": initial["account_binding_sha256"],
            "credential_envelope_sha256": initial[
                "credential_envelope_sha256"
            ],
            "refresh_count": 0,
            "configure_count": 0,
        }
        context["acknowledged"] = True
    except BaseException as exc:
        failure = exc
    finally:
        for raw in (ready_raw, ack_raw):
            if raw is not None:
                try:
                    if module is not None:
                        module.scrub_bytearray(raw)
                    else:
                        _scrub(raw)
                except BaseException:
                    pass
        for descriptor in (ready_fd, ack_fd):
            try:
                closer(descriptor)
            except BaseException as exc:
                if failure is None:
                    failure = exc
    if failure is not None:
        if isinstance(failure, CaptureSignal):
            raise failure
        raise CaptureError("credential_handshake") from None
    return context

def _scrub(value):
    if type(value) is bytearray:
        value[:] = b"\x00" * len(value)

class _C1DarwinSocketStat:
    __slots__ = ("_row", "st_dev")

    def __init__(self, row):
        self._row = row
        self.st_dev = (1 << 64) - 1

    def __getattr__(self, name):
        return getattr(self._row, name)

def _c1_platform_fstat(descriptor):
    row = os.fstat(descriptor)
    if (
        sys.platform == "darwin"
        and type(row.st_dev) is int
        and row.st_dev == -1
        and type(row.st_mode) is int
        and stat.S_ISSOCK(row.st_mode)
    ):
        duplicate = -1
        channel = None
        try:
            duplicate = os.dup(descriptor)
            channel = socket.socket(fileno=duplicate)
            duplicate = -1
            if (
                channel.family == socket.AF_UNIX
                and channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
                == socket.SOCK_STREAM
                and channel.getsockname() in {None, "", b""}
                and channel.getpeername() in {None, "", b""}
            ):
                return _C1DarwinSocketStat(row)
        except (OSError, ValueError):
            pass
        finally:
            if channel is not None:
                channel.close()
            elif duplicate >= 0:
                os.close(duplicate)
    return row

def _early_core0_clean_env_preflight(
    *,
    getrlimit=resource.getrlimit,
    environ=None,
    geteuid=os.geteuid,
    flags=None,
    executable=None,
    realpath=os.path.realpath
):
    if geteuid() != 0:
        raise CaptureError("root_required")
    try:
        limits = getrlimit(resource.RLIMIT_CORE)
    except (OSError, ValueError):
        raise CaptureError("core_limit_unknown") from None
    if limits != (0, 0):
        raise CaptureError("core_dump_enabled")
    actual_environment = dict(os.environ if environ is None else environ)
    if actual_environment != CHILD_ENV:
        raise CaptureError("child_environment")
    actual_flags = sys.flags if flags is None else flags
    if not (
        getattr(actual_flags, "isolated", 0) == 1
        and getattr(actual_flags, "ignore_environment", 0) == 1
        and getattr(actual_flags, "no_user_site", 0) == 1
        and getattr(actual_flags, "no_site", 0) == 1
        and bool(getattr(actual_flags, "dont_write_bytecode", 0))
    ):
        raise CaptureError("isolated_runtime_required")
    actual_executable = sys.executable if executable is None else executable
    if (
        actual_executable != PYTHON_RUNTIME_EXECUTABLE
        or realpath(actual_executable) != PYTHON_RESOLVED_EXECUTABLE
    ):
        raise CaptureError("child_python_resolution")
    return True

def _runtime_row(raw, row, expected_size, expected_sha256, expected_mode):
    if (
        type(raw) is not bytes
        or len(raw) != expected_size
        or _sha256(raw) != expected_sha256
        or type(row) is not dict
        or row.get("regular") is not True
        or row.get("symlink") is not False
        or row.get("uid") != 0
        or row.get("gid") != 0
        or row.get("nlink") != 1
        or row.get("mode") != expected_mode
        or row.get("size") != expected_size
    ):
        raise CaptureError("runtime_identity")

def _snapshot_bound_file(path, binding):
    descriptor = -1
    try:
        before = os.lstat(path)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise CaptureError("child_tool_identity")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise CaptureError("child_tool_identity")
        chunks = []
        total = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > binding["size"]:
                raise CaptureError("child_tool_identity")
            chunks.append(chunk)
        after = os.fstat(descriptor)
    except CaptureError:
        raise
    except OSError:
        raise CaptureError("child_tool_identity") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    raw = b"".join(chunks)
    expected = (
        binding["size"],
        binding["mode"],
        binding["uid"],
        binding["gid"],
        binding["nlink"],
        binding["sha256"],
    )
    observed = (
        len(raw),
        stat.S_IMODE(after.st_mode),
        after.st_uid,
        after.st_gid,
        after.st_nlink,
        _sha256(raw),
    )
    if observed != expected or (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mode,
        before.st_uid,
        before.st_gid,
        before.st_nlink,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mode,
        after.st_uid,
        after.st_gid,
        after.st_nlink,
    ):
        raise CaptureError("child_tool_identity")
    return {
        "path": path,
        "dev": after.st_dev,
        "ino": after.st_ino,
        "size": after.st_size,
        "mode": stat.S_IMODE(after.st_mode),
        "uid": after.st_uid,
        "gid": after.st_gid,
        "nlink": after.st_nlink,
        "sha256": _sha256(raw),
        "parent_chain": _snapshot_parent_chain(path),
    }

def _snapshot_parent_chain(path):
    result = []
    parent = os.path.dirname(path)
    while True:
        try:
            row = os.lstat(parent)
        except OSError:
            raise CaptureError("child_tool_parent_chain") from None
        if stat.S_ISLNK(row.st_mode):
            try:
                target = os.readlink(parent)
            except OSError:
                raise CaptureError("child_tool_parent_chain") from None
            if parent != "/etc" or target != "private/etc" or row.st_uid != 0 or row.st_gid != 0:
                raise CaptureError("child_tool_parent_chain")
            kind = "allowed_symlink"
        else:
            target = None
            if (
                not stat.S_ISDIR(row.st_mode)
                or row.st_uid != 0
                or row.st_gid != 0
                or stat.S_IMODE(row.st_mode) & 0o022
            ):
                raise CaptureError("child_tool_parent_chain")
            kind = "directory"
        result.append({
            "path": parent,
            "kind": kind,
            "target": target,
            "dev": row.st_dev,
            "ino": row.st_ino,
            "mode": stat.S_IMODE(row.st_mode),
            "uid": row.st_uid,
            "gid": row.st_gid,
            "nlink": row.st_nlink,
        })
        if parent == "/":
            break
        parent = os.path.dirname(parent)
    return result

def _capture_child_identity_snapshot():
    return {
        path: _snapshot_bound_file(path, binding)
        for path, binding in CHILD_TOOL_BINDINGS.items()
    }

def _capture_system_identity_snapshot():
    return {
        path: _snapshot_bound_file(path, binding)
        for path, binding in CHILD_SYSTEM_TOOL_BINDINGS.items()
    }

def _parse_runtime_count(value):
    if (
        type(value) is not str
        or not value.isascii()
        or not value.isdigit()
        or value != str(int(value))
    ):
        raise CaptureError("runtime_arguments")
    count = int(value)
    if not 1 <= count <= 1024 * 1024:
        raise CaptureError("runtime_arguments")
    return count

def _parse_runtime_arguments(arguments):
    if type(arguments) not in (tuple, list) or len(arguments) != 5:
        raise CaptureError("runtime_arguments")
    acceptance, program_size_raw, program_sha256, manifest_size_raw, manifest_sha256 = tuple(arguments)
    program_size = _parse_runtime_count(program_size_raw)
    manifest_size = _parse_runtime_count(manifest_size_raw)
    if (
        type(acceptance) is not str
        or len(acceptance) != 40
        or any(character not in "0123456789abcdef" for character in acceptance)
        or acceptance in {CONTROL_REVISION, ADAPTER_ACCEPTANCE_REVISION}
        or not _sha256_text(program_sha256)
        or not _sha256_text(manifest_sha256)
    ):
        raise CaptureError("runtime_arguments")
    return {
        "acceptance_revision": acceptance,
        "program_size": program_size,
        "program_sha256": program_sha256,
        "manifest_size": manifest_size,
        "manifest_sha256": manifest_sha256,
    }

def _read_runtime_regular(path, maximum):
    if type(path) is not str or type(maximum) is not int or maximum < 1:
        raise CaptureError("runtime_identity")
    descriptor = -1
    try:
        before = os.lstat(path)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise CaptureError("runtime_identity")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise CaptureError("runtime_identity")
        chunks = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise CaptureError("runtime_identity")
            chunks.append(chunk)
        after = os.fstat(descriptor)
    except CaptureError:
        raise
    except OSError:
        raise CaptureError("runtime_identity") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    stable = lambda row: (
        row.st_dev,
        row.st_ino,
        row.st_size,
        row.st_mode,
        row.st_uid,
        row.st_gid,
        row.st_nlink,
        getattr(row, "st_mtime_ns", 0),
        getattr(row, "st_ctime_ns", 0),
    )
    if stable(before) != stable(after):
        raise CaptureError("runtime_identity")
    return b"".join(chunks), {
        "regular": stat.S_ISREG(after.st_mode),
        "symlink": False,
        "uid": after.st_uid,
        "gid": after.st_gid,
        "nlink": after.st_nlink,
        "mode": stat.S_IMODE(after.st_mode),
        "size": after.st_size,
        "dev": after.st_dev,
        "ino": after.st_ino,
        "mtime_ns": getattr(after, "st_mtime_ns", 0),
        "ctime_ns": getattr(after, "st_ctime_ns", 0),
    }

def _runtime_dynamic_bindings(arguments):
    parsed = _parse_runtime_arguments(arguments)
    return {
        CAPTURE_PROGRAM_PATH: {
            "sha256": parsed["program_sha256"],
            "size": parsed["program_size"],
            "mode": 0o500,
            "uid": 0,
            "gid": 0,
            "nlink": 1,
        },
        CAPTURE_MANIFEST_PATH: {
            "sha256": parsed["manifest_sha256"],
            "size": parsed["manifest_size"],
            "mode": 0o600,
            "uid": 0,
            "gid": 0,
            "nlink": 1,
        },
    }

def _capture_runtime_identity_snapshot(arguments):
    return {
        path: _snapshot_bound_file(path, binding)
        for path, binding in _runtime_dynamic_bindings(arguments).items()
    }

def _validate_runtime_and_local_objects(
    *,
    list_capture_names,
    read_capture_file,
    stat_capture_file,
    list_existing_names,
    read_existing_file,
    stat_existing_file,
    git_probe,
    expected_program_bytes,
    expected_program_sha256,
    expected_manifest_bytes,
    expected_manifest_sha256,
    expected_acceptance_revision
):
    if (
        type(expected_program_bytes) is not int
        or expected_program_bytes <= 0
        or type(expected_program_sha256) is not str
        or len(expected_program_sha256) != 64
        or type(expected_manifest_bytes) is not int
        or expected_manifest_bytes <= 0
        or type(expected_manifest_sha256) is not str
        or len(expected_manifest_sha256) != 64
        or type(expected_acceptance_revision) is not str
        or len(expected_acceptance_revision) != 40
    ):
        raise CaptureError("runtime_expected_binding")
    if set(list_capture_names()) != CAPTURE_RUNTIME_NAMES:
        raise CaptureError("capture_runtime_inventory")
    program_raw = read_capture_file("capture-root-program.py")
    adapter_raw = read_capture_file("item26_aliyun_official_read_v2.py")
    manifest_raw = read_capture_file("capture-runtime-manifest.json")
    _runtime_row(
        program_raw,
        stat_capture_file("capture-root-program.py"),
        expected_program_bytes,
        expected_program_sha256,
        0o500,
    )
    _runtime_row(
        adapter_raw,
        stat_capture_file("item26_aliyun_official_read_v2.py"),
        ADAPTER_BYTES,
        ADAPTER_SHA256,
        0o500,
    )
    _runtime_row(
        manifest_raw,
        stat_capture_file("capture-runtime-manifest.json"),
        expected_manifest_bytes,
        expected_manifest_sha256,
        0o600,
    )
    manifest = _strict_object(
        manifest_raw,
        1024 * 1024,
        "capture_runtime_manifest",
    )
    expected_manifest = {
        "schema": RUNTIME_MANIFEST_SCHEMA,
        "manifest_name": "capture-runtime-manifest.json",
        "manifest_mode": "0600",
        "payloads": {
            "capture-root-program.py": {
                "name": "capture-root-program.py",
                "byte_count": expected_program_bytes,
                "sha256": expected_program_sha256,
                "mode": "0500",
                "source_revision": expected_acceptance_revision,
                "source_ref": "tools/stage_collect_and_materialize_item26_manual_cost_stop_m1_v2.py:CAPTURE_ROOT_PROGRAM",
            },
            "item26_aliyun_official_read_v2.py": {
                "name": "item26_aliyun_official_read_v2.py",
                "byte_count": ADAPTER_BYTES,
                "sha256": ADAPTER_SHA256,
                "mode": "0500",
                "source_revision": ADAPTER_ACCEPTANCE_REVISION,
                "source_ref": "tools/item26_aliyun_official_read_v2.py",
            },
        },
    }
    if manifest != expected_manifest or canonical(manifest) != manifest_raw:
        raise CaptureError("capture_runtime_manifest")
    if set(list_existing_names()) != set(EXISTING_RUNTIME_BINDINGS):
        raise CaptureError("existing_runtime_inventory")
    for name, binding in EXISTING_RUNTIME_BINDINGS.items():
        size, digest, mode = binding
        _runtime_row(
            read_existing_file(name),
            stat_existing_file(name),
            size,
            digest,
            mode,
        )
    for ref, binding in LOCAL_OBJECT_BINDINGS.items():
        observed = git_probe(ref, dict(binding))
        if observed != {
            "accepted_revision": binding["accepted_revision"],
            "source_revision": binding["source_revision"],
            "blob_oid": binding["blob_oid"],
            "sha256": binding["sha256"],
            "size": binding["size"],
            "object_local": True,
            "promisor_remote_count": 0,
            "partial_clone_extension_count": 0,
        }:
            raise CaptureError("local_object_binding")
    return manifest

def _capture_runtime_validator_from_arguments(arguments):
    parsed = _parse_runtime_arguments(arguments)

    def validate():
        repository_before = _repository_local_identity()
        tools_before = _capture_system_identity_snapshot()
        dynamic_before = _capture_runtime_identity_snapshot(arguments)
        capture_cache = {}
        existing_cache = {}

        def capture_entry(name):
            if name not in CAPTURE_RUNTIME_NAMES:
                raise CaptureError("capture_runtime_inventory")
            if name not in capture_cache:
                maximum = {
                    "capture-root-program.py": parsed["program_size"],
                    "item26_aliyun_official_read_v2.py": ADAPTER_BYTES,
                    "capture-runtime-manifest.json": parsed["manifest_size"],
                }[name]
                capture_cache[name] = _read_runtime_regular(
                    RUNTIME_DIRECTORY + "/" + name,
                    maximum,
                )
            return capture_cache[name]

        def existing_entry(name):
            if name not in EXISTING_RUNTIME_BINDINGS:
                raise CaptureError("existing_runtime_inventory")
            if name not in existing_cache:
                existing_cache[name] = _read_runtime_regular(
                    EXISTING_RUNTIME_DIRECTORY + "/" + name,
                    EXISTING_RUNTIME_BINDINGS[name][0],
                )
            return existing_cache[name]

        manifest = _validate_runtime_and_local_objects(
            list_capture_names=lambda: tuple(os.listdir(RUNTIME_DIRECTORY)),
            read_capture_file=lambda name: capture_entry(name)[0],
            stat_capture_file=lambda name: capture_entry(name)[1],
            list_existing_names=lambda: tuple(os.listdir(EXISTING_RUNTIME_DIRECTORY)),
            read_existing_file=lambda name: existing_entry(name)[0],
            stat_existing_file=lambda name: existing_entry(name)[1],
            git_probe=_capture_local_object_probe,
            expected_program_bytes=parsed["program_size"],
            expected_program_sha256=parsed["program_sha256"],
            expected_manifest_bytes=parsed["manifest_size"],
            expected_manifest_sha256=parsed["manifest_sha256"],
            expected_acceptance_revision=parsed["acceptance_revision"],
        )
        tools_after = _capture_system_identity_snapshot()
        dynamic_after = _capture_runtime_identity_snapshot(arguments)
        repository_after = _repository_local_identity()
        if (
            tools_after != tools_before
            or dynamic_after != dynamic_before
            or repository_after != repository_before
        ):
            raise CaptureError("runtime_identity_drift")
        return {
            "manifest": manifest,
            "runtime_raw": {
                "adapter": capture_entry(
                    "item26_aliyun_official_read_v2.py"
                )[0],
                "collector": existing_entry(
                    "collect_item26_manual_cost_stop_raw_v2.py"
                )[0],
                "extractor": existing_entry(
                    "extract_item26_manual_cost_stop_raw_v2.py"
                )[0],
                "authority": existing_entry(
                    "verify_item26_manual_cost_stop_authority_v2.py"
                )[0],
            },
            "identities": {
                "tools": tools_before,
                "dynamic": dynamic_before,
                "repository": repository_before,
                "capture": {
                    name: capture_entry(name)[1]
                    for name in sorted(CAPTURE_RUNTIME_NAMES)
                },
                "existing": {
                    name: existing_entry(name)[1]
                    for name in sorted(EXISTING_RUNTIME_BINDINGS)
                },
            },
        }

    validate.arguments = tuple(arguments)
    return validate

def _capture_child_runtime_validator_from_arguments(arguments):
    parsed = _parse_runtime_arguments(arguments)

    def validate():
        capture_names = tuple(os.listdir(RUNTIME_DIRECTORY))
        if (
            len(capture_names) != len(CAPTURE_RUNTIME_NAMES)
            or set(capture_names) != CAPTURE_RUNTIME_NAMES
        ):
            raise CaptureError("capture_runtime_inventory")
        tools_before = _capture_system_identity_snapshot()
        dynamic_before = _capture_runtime_identity_snapshot(arguments)
        program_raw, program_row = _read_runtime_regular(
            CAPTURE_PROGRAM_PATH,
            parsed["program_size"],
        )
        adapter_raw, adapter_row = _read_runtime_regular(
            ADAPTER_PATH,
            ADAPTER_BYTES,
        )
        manifest_raw, manifest_row = _read_runtime_regular(
            CAPTURE_MANIFEST_PATH,
            parsed["manifest_size"],
        )
        _runtime_row(
            program_raw,
            program_row,
            parsed["program_size"],
            parsed["program_sha256"],
            0o500,
        )
        _runtime_row(
            adapter_raw,
            adapter_row,
            ADAPTER_BYTES,
            ADAPTER_SHA256,
            0o500,
        )
        _runtime_row(
            manifest_raw,
            manifest_row,
            parsed["manifest_size"],
            parsed["manifest_sha256"],
            0o600,
        )
        manifest = _strict_object(
            manifest_raw,
            1024 * 1024,
            "capture_runtime_manifest",
        )
        expected = {
            "schema": RUNTIME_MANIFEST_SCHEMA,
            "manifest_name": "capture-runtime-manifest.json",
            "manifest_mode": "0600",
            "payloads": {
                "capture-root-program.py": {
                    "name": "capture-root-program.py",
                    "byte_count": parsed["program_size"],
                    "sha256": parsed["program_sha256"],
                    "mode": "0500",
                    "source_revision": parsed["acceptance_revision"],
                    "source_ref": "tools/stage_collect_and_materialize_item26_manual_cost_stop_m1_v2.py:CAPTURE_ROOT_PROGRAM",
                },
                "item26_aliyun_official_read_v2.py": {
                    "name": "item26_aliyun_official_read_v2.py",
                    "byte_count": ADAPTER_BYTES,
                    "sha256": ADAPTER_SHA256,
                    "mode": "0500",
                    "source_revision": ADAPTER_ACCEPTANCE_REVISION,
                    "source_ref": "tools/item26_aliyun_official_read_v2.py",
                },
            },
        }
        if manifest != expected or canonical(manifest) != manifest_raw:
            raise CaptureError("capture_runtime_manifest")
        if (
            _capture_system_identity_snapshot() != tools_before
            or _capture_runtime_identity_snapshot(arguments) != dynamic_before
        ):
            raise CaptureError("runtime_identity_drift")
        return {
            "manifest": manifest,
            "runtime_raw": {"adapter": adapter_raw},
            "identities": {
                "tools": tools_before,
                "dynamic": dynamic_before,
                "program": program_row,
                "adapter": adapter_row,
                "manifest": manifest_row,
            },
        }

    validate.arguments = tuple(arguments)
    return validate

def _capture_post_identity_snapshot(
    arguments,
    expected_identities,
    *,
    monotonic=time.monotonic,
):
    parsed = _parse_runtime_arguments(arguments)
    if (
        type(expected_identities) is not dict
        or set(expected_identities) != {
            "tools",
            "dynamic",
            "repository",
            "capture",
            "existing",
        }
    ):
        raise CaptureError("runtime_identity_drift")
    started = monotonic()
    file_read_count = 0

    def bounded(value, increment):
        nonlocal file_read_count
        file_read_count += increment
        elapsed = monotonic() - started
        if (
            elapsed < 0
            or elapsed > POST_CAPTURE_IDENTITY_DEADLINE_SECONDS
            or file_read_count > POST_CAPTURE_MAX_FILE_READ_COUNT
        ):
            raise CaptureError("post_capture_identity_timeout")
        return value

    capture_names = tuple(os.listdir(RUNTIME_DIRECTORY))
    if (
        len(capture_names) != len(CAPTURE_RUNTIME_NAMES)
        or set(capture_names) != CAPTURE_RUNTIME_NAMES
    ):
        raise CaptureError("capture_runtime_inventory")
    existing_names = tuple(os.listdir(EXISTING_RUNTIME_DIRECTORY))
    if (
        len(existing_names) != len(EXISTING_RUNTIME_BINDINGS)
        or set(existing_names) != set(EXISTING_RUNTIME_BINDINGS)
    ):
        raise CaptureError("existing_runtime_inventory")
    tools = bounded(
        _capture_system_identity_snapshot(),
        len(CHILD_SYSTEM_TOOL_BINDINGS),
    )
    dynamic = bounded(_capture_runtime_identity_snapshot(arguments), 2)
    capture_rows = {}
    capture_bindings = {
        "capture-root-program.py": (
            parsed["program_size"],
            parsed["program_sha256"],
            0o500,
        ),
        "item26_aliyun_official_read_v2.py": (
            ADAPTER_BYTES,
            ADAPTER_SHA256,
            0o500,
        ),
        "capture-runtime-manifest.json": (
            parsed["manifest_size"],
            parsed["manifest_sha256"],
            0o600,
        ),
    }
    for name in sorted(CAPTURE_RUNTIME_NAMES):
        size, digest, mode = capture_bindings[name]
        raw, row = _read_runtime_regular(RUNTIME_DIRECTORY + "/" + name, size)
        bounded(None, 1)
        _runtime_row(raw, row, size, digest, mode)
        capture_rows[name] = row
    existing_rows = {}
    for name in sorted(EXISTING_RUNTIME_BINDINGS):
        size, digest, mode = EXISTING_RUNTIME_BINDINGS[name]
        raw, row = _read_runtime_regular(
            EXISTING_RUNTIME_DIRECTORY + "/" + name,
            size,
        )
        bounded(None, 1)
        _runtime_row(raw, row, size, digest, mode)
        existing_rows[name] = row
    repository = bounded(_repository_local_identity(), 1)
    observed = {
        "tools": tools,
        "dynamic": dynamic,
        "repository": repository,
        "capture": capture_rows,
        "existing": existing_rows,
    }
    if observed != expected_identities:
        raise CaptureError("runtime_identity_drift")
    return observed

def _load_fixed_module(name, path, raw):
    if (
        type(name) is not str
        or not name
        or type(path) is not str
        or not path.startswith("/")
        or type(raw) is not bytes
        or not raw
        or name in sys.modules
    ):
        raise CaptureError("capture_module_load")
    module = type(sys)(name)
    module.__file__ = path
    sys.modules[name] = module
    try:
        exec(
            compile(raw, path, "exec", dont_inherit=True, optimize=0),
            module.__dict__,
        )
    except BaseException:
        sys.modules.pop(name, None)
        raise CaptureError("capture_module_load") from None
    return module

def _load_adapter_from_validation(validated):
    if type(validated) is not dict or type(validated.get("runtime_raw")) is not dict:
        raise CaptureError("capture_runtime_validation")
    return _load_fixed_module(
        "item26_aliyun_official_read_v2",
        ADAPTER_PATH,
        validated["runtime_raw"]["adapter"],
    )

def _default_prepare_capture_dependencies(runtime_validator):
    validated = runtime_validator()
    if type(validated) is not dict or type(validated.get("runtime_raw")) is not dict:
        raise CaptureError("capture_runtime_validation")
    raw = validated["runtime_raw"]
    extractor = _load_fixed_module(
        "extract_item26_manual_cost_stop_raw_v2",
        EXTRACTOR_PATH,
        raw["extractor"],
    )
    authority = _load_fixed_module(
        "verify_item26_manual_cost_stop_authority_v2",
        AUTHORITY_PATH,
        raw["authority"],
    )
    repository_probe = getattr(authority, "_git_repository_identity", None)
    if not callable(repository_probe):
        raise CaptureError("authority_patch_seam")

    def bound_git(arguments, *, root, stdout=subprocess.PIPE):
        return _local_only_git(
            arguments,
            root=root,
            stdout=stdout,
            repository_probe=repository_probe,
        )

    _install_fd_only_authority_patches(
        authority,
        fd_signature_verifier=_fd_only_verify_signature,
        local_only_git=bound_git,
        fd_only_openssl=_fd_only_openssl,
    )
    collector = _load_fixed_module(
        "collect_item26_manual_cost_stop_raw_v2",
        COLLECTOR_PATH,
        raw["collector"],
    )
    if (
        getattr(collector, "extractor", None) is not extractor
        or getattr(collector, "authority", None) is not authority
    ):
        raise CaptureError("capture_module_closure")
    if not all(
        callable(getattr(collector, name, None))
        for name in ("begin", "finish", "mark_unknown", "finalize")
    ) or not callable(
        getattr(extractor, "validate_offline_import_response", None)
    ):
        raise CaptureError("capture_dependency_entrypoints")
    return collector, extractor

def _install_fd_only_authority_patches(
    authority_module,
    *,
    fd_signature_verifier,
    local_only_git,
    fd_only_openssl
):
    if (
        not callable(fd_signature_verifier)
        or not callable(local_only_git)
        or not callable(getattr(authority_module, "_verify_signature", None))
        or not callable(getattr(authority_module, "_git", None))
        or not callable(getattr(authority_module, "_openssl", None))
        or getattr(authority_module, "_item26_m1_patched", False)
    ):
        raise CaptureError("authority_patch_seam")
    authority_module._verify_signature = fd_signature_verifier
    authority_module._git = local_only_git
    authority_module._openssl = fd_only_openssl
    authority_module._item26_m1_patched = True
    return authority_module

def _prepare_capture_dependencies(
    *,
    runtime_validator,
    authority_loader,
    collector_loader,
    extractor_loader,
    fd_signature_verifier,
    local_only_git,
    fd_only_openssl
):
    runtime_validator()
    authority_module = authority_loader()
    _install_fd_only_authority_patches(
        authority_module,
        fd_signature_verifier=fd_signature_verifier,
        local_only_git=local_only_git,
        fd_only_openssl=fd_only_openssl,
    )
    collector = collector_loader(authority_module)
    extractor = extractor_loader(authority_module)
    if not all(
        callable(getattr(collector, name, None))
        for name in ("begin", "finish", "mark_unknown", "finalize")
    ) or not callable(
        getattr(extractor, "validate_offline_import_response", None)
    ):
        raise CaptureError("capture_dependency_entrypoints")
    return collector, extractor

def _identifier(identifiers, key, expected_sha256, value_sha256):
    if type(identifiers) is not dict:
        raise CaptureError("identifier_context")
    value = identifiers.get(key)
    if type(value) is not str or not value or value_sha256(value) != expected_sha256:
        raise CaptureError("identifier_binding")
    return value

def _token(value):
    if value is None:
        return None
    if type(value) is not str or not value:
        raise CaptureError("pagination_token")
    try:
        raw = value.encode("ascii")
    except UnicodeError:
        raise CaptureError("pagination_token") from None
    if len(raw) > 4096 or any(byte < 0x20 or byte > 0x7e for byte in raw):
        raise CaptureError("pagination_token")
    return value

def _build_page_request(slot, identifiers, next_token=None, *, value_sha256=_value_sha256):
    if slot not in SLOTS:
        raise CaptureError("capture_slot")
    next_token = _token(next_token)
    if slot == SLOTS[0]:
        request = {
            "Action": "LookupEvents",
            "Version": "2020-07-06",
            "Direction": "FORWARD",
            "StartTime": "2026-08-16T14:38:00Z",
            "EndTime": "2026-08-16T14:46:00Z",
            "LookupAttribute": [
                {"Key": "ServiceName", "Value": "Rds"},
                {"Key": "EventRW", "Value": "Write"},
            ],
            "MaxResults": "50",
        }
    elif slot == SLOTS[1]:
        old_clone = _identifier(
            identifiers,
            "old_clone",
            EXPECTED_OLD_CLONE_SHA256,
            value_sha256,
        )
        request = {
            "Action": "LookupEvents",
            "Version": "2020-07-06",
            "Direction": "FORWARD",
            "StartTime": "2026-08-12T00:00:00Z",
            "EndTime": "2026-08-13T00:00:00Z",
            "LookupAttribute": [
                {"Key": "EventName", "Value": "CloneDBInstance"},
                {"Key": "ResourceName", "Value": old_clone},
            ],
            "MaxResults": "50",
        }
    elif slot == SLOTS[2]:
        if next_token is not None:
            raise CaptureError("pagination_not_allowed")
        request = {
            "Action": "DescribeDBInstances",
            "Version": "2014-08-15",
            "RegionId": "cn-shenzhen",
            "DBInstanceId": _identifier(
                identifiers,
                "old_clone",
                EXPECTED_OLD_CLONE_SHA256,
                value_sha256,
            ),
            "PageNumber": 1,
            "PageSize": 100,
        }
    elif slot == SLOTS[3]:
        if next_token is not None:
            raise CaptureError("pagination_not_allowed")
        request = {
            "Action": "DescribeDBInstances",
            "Version": "2014-08-15",
            "RegionId": "cn-shenzhen",
            "DBInstanceId": _identifier(
                identifiers,
                "source",
                EXPECTED_SOURCE_SHA256,
                value_sha256,
            ),
            "PageNumber": 1,
            "PageSize": 100,
        }
    else:
        if next_token is not None:
            raise CaptureError("pagination_not_allowed")
        request = {
            "Action": "QueryInstanceBill",
            "Version": "2017-12-14",
            "BillingCycle": "2026-08",
            "ProductCode": "rds",
            "SubscriptionType": "PayAsYouGo",
            "IsBillingItem": False,
            "IsHideZeroCharge": False,
            "Granularity": "MONTHLY",
            "PageNum": 1,
            "PageSize": 300,
        }
    if next_token is not None:
        request["NextToken"] = next_token
    raw = canonical(request)
    if len(raw) > MAX_REQUEST_BYTES:
        raise CaptureError("request_oversize")
    return raw

def _event_parameters(event):
    if type(event) is not dict:
        raise CaptureError("response_event")
    direct = event.get("requestParameters")
    encoded = event.get("requestParameterJson")
    parsed = None
    if direct is not None:
        if type(direct) is not dict:
            raise CaptureError("response_parameters")
        parsed = direct
    if encoded is not None:
        if type(encoded) is not str or not encoded:
            raise CaptureError("response_parameters")
        candidate = _strict_object(
            encoded.encode("utf-8"),
            MAX_RESPONSE_BYTES,
            "response_parameters",
        )
        if parsed is not None and parsed != candidate:
            raise CaptureError("response_parameters")
        parsed = candidate
    if type(parsed) is not dict:
        raise CaptureError("response_parameters")
    return parsed

def _derive_after_finish(slot, request_raw, response_raw, extractor):
    request = _strict_object(request_raw, MAX_REQUEST_BYTES, "request_json")
    response = _strict_object(response_raw, MAX_RESPONSE_BYTES, "response_json")
    failure = None
    try:
        extractor.validate_offline_import_response(slot, request, response)
    except Exception:
        failure = "extractor_page_parity"
    if failure is not None:
        request = None
        response = None
        raise CaptureError(failure) from None
    next_token = response.get("NextToken")
    if next_token in (None, ""):
        next_token = None
    else:
        next_token = _token(next_token)
    candidates = []
    if slot in (SLOTS[0], SLOTS[1]):
        events = response.get("Events")
        if type(events) is not list:
            raise CaptureError("response_events")
        for event in events:
            parameters = _event_parameters(event)
            if slot == SLOTS[0]:
                candidate = parameters.get("DBInstanceId")
                if type(candidate) is not str or not candidate:
                    raise CaptureError("cost_stop_identifier")
                candidates.append(candidate)
            else:
                per_event = [
                    value
                    for value in (
                        parameters.get("DBInstanceId"),
                        parameters.get("SourceDBInstanceId"),
                    )
                    if type(value) is str and value
                ]
                if len(per_event) != 1:
                    raise CaptureError("source_identifier")
                candidates.append(per_event[0])
    elif next_token is not None:
        raise CaptureError("pagination_not_allowed")
    return {"next_token": next_token, "identifier_candidates": candidates}

def _collector_status(value, *, expected_status, slot=None, digest_key=None, digest=None):
    if type(value) is not dict or value.get("schema") != "noteai.item26.manual-cost-stop-collector-status.v2":
        raise CaptureError("collector_status")
    if value.get("status") != expected_status:
        raise CaptureError("collector_status")
    if slot is not None and value.get("slot") != slot:
        raise CaptureError("collector_status")
    if digest_key is not None and value.get(digest_key) != digest:
        raise CaptureError("collector_status")
    if value.get("cloud_call_count") != 0 or value.get("raw_value_emitted_count") != 0:
        raise CaptureError("collector_status")
    expected_keys = {
        "schema",
        "status",
        "sequence",
        "slot",
        "cloud_call_count",
        "raw_value_emitted_count",
    }
    if digest_key is not None:
        expected_keys.add(digest_key)
    if expected_status == "UNKNOWN_INFLIGHT":
        expected_keys.update({"reason", "cloud_request_replay_allowed"})
    if set(value) != expected_keys or type(value.get("sequence")) is not int or value["sequence"] < 1:
        raise CaptureError("collector_status")
    return value

def _child_status(raw):
    value = _strict_object(raw, MAX_STATUS_BYTES, "child_status")
    if canonical(value) != raw or set(value) != {
        "schema",
        "status",
        "cloud_dispatch_count",
        "cloud_write_count",
        "automatic_retry_count",
        "raw_value_emitted_count",
    } or value != {
        "schema": CHILD_STATUS_SCHEMA,
        "status": "ONE_READ_DISPATCH_COMPLETED",
        "cloud_dispatch_count": 1,
        "cloud_write_count": 0,
        "automatic_retry_count": 0,
        "raw_value_emitted_count": 0,
    }:
        raise CaptureError("child_status")
    return value

def _socket_identity(channel):
    fd = channel.fileno()
    try:
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        row = os.fstat(fd)
    except OSError:
        raise CaptureError("fd_identity") from None
    socket_type = channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
    local_name = channel.getsockname()
    peer_name = channel.getpeername()
    if (
        type(fd) is not int
        or fd < 3
        or channel.family != socket.AF_UNIX
        or socket_type != socket.SOCK_STREAM
        or os.isatty(fd)
        or not channel.getblocking()
        or flags & os.O_ACCMODE != os.O_RDWR
        or flags & os.O_NONBLOCK
        or flags & getattr(os, "O_ASYNC", 0)
        or local_name not in (None, "", b"")
        or peer_name not in (None, "", b"")
    ):
        raise CaptureError("fd_identity")
    return (row.st_dev, row.st_ino)

def _child_preexec():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.setsid()

def _kill_reap_prove_group_absent(
    process,
    *,
    force_kill,
    wait_timeout,
    reap_timeout=CHILD_REAP_GRACE_SECONDS,
    killpg=os.killpg,
    monotonic=time.monotonic,
    sleep=time.sleep
):
    pid = getattr(process, "pid", None)
    if type(pid) is not int or pid <= 1:
        return {"reaped": False, "group_absent": False, "returncode": None}
    reaped = False
    returncode = None
    group_absent = False
    if not force_kill:
        try:
            returncode = process.wait(timeout=max(0.0, wait_timeout))
            reaped = True
        except Exception:
            reaped = False
        if reaped:
            try:
                killpg(pid, 0)
            except ProcessLookupError:
                group_absent = True
            except OSError:
                group_absent = False
            if group_absent:
                return {
                    "reaped": True,
                    "group_absent": True,
                    "returncode": returncode,
                    "kill_sent": False,
                }
    try:
        killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        return {
            "reaped": reaped,
            "group_absent": False,
            "returncode": returncode,
            "kill_sent": False,
        }
    deadline = monotonic() + max(0.01, reap_timeout)
    if not reaped:
        try:
            returncode = process.wait(
                timeout=max(0.01, deadline - monotonic())
            )
            reaped = True
        except Exception:
            reaped = False
    while reaped:
        try:
            killpg(pid, 0)
        except ProcessLookupError:
            group_absent = True
            break
        except OSError:
            group_absent = False
            break
        if monotonic() >= deadline:
            break
        sleep(min(0.01, max(0.0, deadline - monotonic())))
    return {
        "reaped": reaped,
        "group_absent": group_absent,
        "returncode": returncode,
        "kill_sent": True,
    }

def _aux_preexec():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

def _spawn_capture_auxiliary(popen, arguments, **options):
    global ACTIVE_CAPTURE_AUX_PROCESS
    previous_mask = signal.pthread_sigmask(
        signal.SIG_BLOCK,
        CAPTURE_TERMINATION_SIGNALS,
    )
    process = None
    try:
        if ACTIVE_CAPTURE_AUX_PROCESS is not None:
            raise CaptureError("capture_aux_process_active")
        process = popen(arguments, **options)
        ACTIVE_CAPTURE_AUX_PROCESS = process
    except BaseException:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        raise
    try:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    except BaseException:
        proof = _kill_reap_prove_group_absent(
            process,
            force_kill=True,
            wait_timeout=0.0,
        )
        ACTIVE_CAPTURE_AUX_PROCESS = None
        if not proof.get("reaped") or not proof.get("group_absent"):
            raise CaptureError("capture_aux_containment") from None
        raise
    return process

def _settle_capture_auxiliary(process, *, force_kill=False, wait_timeout=2.0):
    global ACTIVE_CAPTURE_AUX_PROCESS
    previous_mask = signal.pthread_sigmask(
        signal.SIG_BLOCK,
        CAPTURE_TERMINATION_SIGNALS,
    )
    try:
        proof = _kill_reap_prove_group_absent(
            process,
            force_kill=force_kill,
            wait_timeout=wait_timeout,
        )
        if not proof.get("reaped") or not proof.get("group_absent"):
            raise CaptureError("capture_aux_containment")
        if ACTIVE_CAPTURE_AUX_PROCESS is process:
            ACTIVE_CAPTURE_AUX_PROCESS = None
        return proof.get("returncode")
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

def _git_arguments_allowed(arguments):
    if (
        type(arguments) is not list
        or not arguments
        or any(
            type(value) is not str
            or not value
            or "\0" in value
            or "safe.directory" in value.lower()
            for value in arguments
        )
    ):
        return False
    command = arguments[0]
    return (
        (command in {"show", "rev-parse"} and len(arguments) == 2)
        or (
            command == "rev-parse"
            and len(arguments) == 3
            and arguments[1] == "--verify"
        )
        or (
            command == "cat-file"
            and len(arguments) == 3
            and arguments[1] in {"-e", "blob"}
        )
        or (
            command == "merge-base"
            and len(arguments) == 4
            and arguments[1] == "--is-ancestor"
        )
        or (
            command == "config"
            and arguments == [
                "config",
                "--local",
                "--get-regexp",
                "^(extensions\\.partialClone|remote\\..*\\.promisor)$",
            ]
        )
    )

def _drain_aux_stdout(process, maximum, *, selector_factory=selectors.DefaultSelector, monotonic=time.monotonic):
    if type(maximum) is not int or not 0 <= maximum <= 24 * 1024 * 1024:
        raise CaptureError("capture_aux_output")
    stream = getattr(process, "stdout", None)
    if stream is None:
        if maximum != 0:
            raise CaptureError("capture_aux_output")
        return b""
    descriptor = stream.fileno()
    os.set_blocking(descriptor, False)
    selector = selector_factory()
    raw = bytearray()
    deadline = monotonic() + 15.0
    try:
        selector.register(descriptor, selectors.EVENT_READ)
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise CaptureError("capture_aux_timeout")
            events = selector.select(min(remaining, 0.25))
            for _key, mask in events:
                if not mask & selectors.EVENT_READ:
                    continue
                try:
                    chunk = os.read(
                        descriptor,
                        min(65536, maximum + 1 - len(raw)),
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    return bytes(raw)
                raw.extend(chunk)
                if len(raw) > maximum:
                    raise CaptureError("capture_aux_output")
    finally:
        selector.close()
        try:
            stream.close()
        except Exception:
            pass

def _repository_local_identity():
    paths = (
        REPOSITORY_ROOT,
        REPOSITORY_ROOT + "/.git",
        REPOSITORY_ROOT + "/.git/config",
        REPOSITORY_ROOT + "/.git/objects",
        REPOSITORY_ROOT + "/.git/objects/info",
        REPOSITORY_ROOT + "/.git/objects/pack",
    )
    rows = []
    repository_owner = None
    repository_group = None
    for path in paths:
        row = os.lstat(path)
        if stat.S_ISLNK(row.st_mode):
            raise CaptureError("capture_repository_identity")
        if path == REPOSITORY_ROOT:
            repository_owner = row.st_uid
            repository_group = row.st_gid
            if (repository_owner, repository_group) != (
                REPOSITORY_OWNER_UID,
                REPOSITORY_OWNER_GID,
            ):
                raise CaptureError("capture_repository_identity")
        elif (
            row.st_uid != repository_owner
            or row.st_gid != repository_group
        ):
            raise CaptureError("capture_repository_identity")
        if path.endswith("/config"):
            if not stat.S_ISREG(row.st_mode) or row.st_size > 1024 * 1024:
                raise CaptureError("capture_repository_identity")
        elif not stat.S_ISDIR(row.st_mode):
            raise CaptureError("capture_repository_identity")
        if stat.S_IMODE(row.st_mode) & 0o022:
            raise CaptureError("capture_repository_identity")
        rows.append((
            path,
            row.st_dev,
            row.st_ino,
            row.st_size,
            row.st_mode,
            row.st_uid,
            row.st_gid,
            row.st_nlink,
            getattr(row, "st_mtime_ns", 0),
            getattr(row, "st_ctime_ns", 0),
        ))
    if type(repository_owner) is not int or type(repository_group) is not int:
        raise CaptureError("capture_repository_identity")
    config_raw, _row = _read_runtime_regular(
        REPOSITORY_ROOT + "/.git/config",
        1024 * 1024,
    )
    lowered = config_raw.lower()
    if any(
        token in lowered
        for token in (
            b"promisor",
            b"partialclone",
            b"[include]",
            b"[includeif ",
        )
    ):
        raise CaptureError("capture_repository_nonlocal")
    pack_directory = REPOSITORY_ROOT + "/.git/objects/pack"
    try:
        pack_names = tuple(sorted(os.listdir(pack_directory)))
    except OSError:
        raise CaptureError("capture_repository_nonlocal") from None
    if len(pack_names) > MAX_REPOSITORY_PACK_FILES:
        raise CaptureError("capture_repository_nonlocal")
    pack_rows = []
    for name in pack_names:
        if (
            not name
            or "/" in name
            or "\0" in name
            or name.endswith(".promisor")
            or not name.endswith((".pack", ".idx", ".rev", ".bitmap"))
        ):
            raise CaptureError("capture_repository_nonlocal")
        row = os.lstat(pack_directory + "/" + name)
        if (
            stat.S_ISLNK(row.st_mode)
            or not stat.S_ISREG(row.st_mode)
            or row.st_uid != repository_owner
            or row.st_gid != repository_group
            or stat.S_IMODE(row.st_mode) & 0o022
        ):
            raise CaptureError("capture_repository_nonlocal")
        pack_rows.append((
            name,
            row.st_dev,
            row.st_ino,
            row.st_size,
            row.st_mode,
            row.st_uid,
            row.st_gid,
            row.st_nlink,
            getattr(row, "st_mtime_ns", 0),
            getattr(row, "st_ctime_ns", 0),
        ))
    for suffix in (
        "/.git/objects/info/alternates",
        "/.git/objects/info/http-alternates",
        "/.git/shallow",
        "/.git/commondir",
        "/.git/worktrees",
    ):
        try:
            os.lstat(REPOSITORY_ROOT + suffix)
        except FileNotFoundError:
            continue
        raise CaptureError("capture_repository_nonlocal")
    return {
        "rows": tuple(rows),
        "config_sha256": _sha256(config_raw),
        "pack_rows": tuple(pack_rows),
        "repository_uid": repository_owner,
        "repository_gid": repository_group,
    }

def _git_preexec(uid, gid):
    if (uid, gid) != (REPOSITORY_OWNER_UID, REPOSITORY_OWNER_GID):
        os._exit(78)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    os.umask(0o077)
    if (
        os.geteuid() != REPOSITORY_OWNER_UID
        or os.getegid() != REPOSITORY_OWNER_GID
        or os.getgroups() != []
        or resource.getrlimit(resource.RLIMIT_CORE) != (0, 0)
    ):
        os._exit(78)

def _local_only_git(arguments, *, root, stdout=subprocess.PIPE, popen=subprocess.Popen, repository_probe=None):
    if (
        not _git_arguments_allowed(arguments)
        or str(root) != REPOSITORY_ROOT
        or stdout not in (subprocess.PIPE, subprocess.DEVNULL)
    ):
        raise CaptureError("capture_git_arguments")
    local_repository_before = _repository_local_identity()
    semantic_repository_before = (
        repository_probe(root) if callable(repository_probe) else None
    )
    tools_before = _capture_system_identity_snapshot()
    command = [
        "/usr/bin/git",
        "-c",
        "safe.directory=" + REPOSITORY_ROOT,
        "-c",
        "protocol.file.allow=never",
        "-c",
        "protocol.ext.allow=never",
        "--no-replace-objects",
        *arguments,
    ]
    maximum = 0 if stdout == subprocess.DEVNULL else (
        24 * 1024 * 1024 if arguments[0] == "show" else 1024 * 1024
    )
    process = None
    try:
        process = _spawn_capture_auxiliary(
            popen,
            command,
            cwd=REPOSITORY_ROOT,
            env=dict(GIT_ENV),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
            preexec_fn=lambda: _git_preexec(
                local_repository_before["repository_uid"],
                local_repository_before["repository_gid"],
            ),
            text=False,
            bufsize=0,
        )
        raw = _drain_aux_stdout(process, maximum)
        returncode = _settle_capture_auxiliary(process)
    except BaseException as exc:
        if process is not None and ACTIVE_CAPTURE_AUX_PROCESS is process:
            try:
                _settle_capture_auxiliary(process, force_kill=True, wait_timeout=0.0)
            except BaseException:
                pass
        if isinstance(exc, CaptureSignal):
            raise
        if isinstance(exc, CaptureError):
            raise
        raise CaptureError("capture_git_process") from None
    local_repository_after = _repository_local_identity()
    semantic_repository_after = (
        repository_probe(root) if callable(repository_probe) else None
    )
    if (
        local_repository_after != local_repository_before
        or semantic_repository_after != semantic_repository_before
        or _capture_system_identity_snapshot() != tools_before
    ):
        raise CaptureError("capture_git_identity")
    return subprocess.CompletedProcess(command, returncode, raw, None)

def _capture_local_object_probe(ref, binding):
    if type(ref) is not str or type(binding) is not dict:
        raise CaptureError("local_object_binding")
    accepted = binding.get("accepted_revision")
    source = binding.get("source_revision")
    expected_oid = binding.get("blob_oid")
    expected_size = binding.get("size")
    expected_sha = binding.get("sha256")
    rows = []
    for revision in (source, accepted):
        oid_result = _local_only_git(
            ["rev-parse", "--verify", revision + ":" + ref],
            root=REPOSITORY_ROOT,
        )
        try:
            oid = oid_result.stdout.decode("ascii").strip()
        except (AttributeError, UnicodeError):
            raise CaptureError("local_object_binding") from None
        raw_result = _local_only_git(
            ["cat-file", "blob", oid],
            root=REPOSITORY_ROOT,
        )
        raw = raw_result.stdout
        computed_oid = hashlib.sha1(
            b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
        ).hexdigest()
        if computed_oid != oid:
            raise CaptureError("local_object_binding")
        rows.append((oid, raw))
    if (
        rows[0] != rows[1]
        or rows[0][0] != expected_oid
        or len(rows[0][1]) != expected_size
        or _sha256(rows[0][1]) != expected_sha
    ):
        raise CaptureError("local_object_binding")
    return {
        "accepted_revision": accepted,
        "source_revision": source,
        "blob_oid": expected_oid,
        "sha256": expected_sha,
        "size": expected_size,
        "object_local": True,
        "promisor_remote_count": 0,
        "partial_clone_extension_count": 0,
    }

def _preflight_pipe_pairs(pairs):
    identities = []
    descriptors = []
    for reader, writer in pairs:
        reader_row = os.fstat(reader)
        writer_row = os.fstat(writer)
        reader_flags = fcntl.fcntl(reader, fcntl.F_GETFL)
        writer_flags = fcntl.fcntl(writer, fcntl.F_GETFL)
        if (
            type(reader) is not int
            or type(writer) is not int
            or reader < 3
            or writer < 3
            or reader == writer
            or not stat.S_ISFIFO(reader_row.st_mode)
            or not stat.S_ISFIFO(writer_row.st_mode)
            or os.isatty(reader)
            or os.isatty(writer)
            or reader_flags & os.O_ACCMODE != os.O_RDONLY
            or writer_flags & os.O_ACCMODE != os.O_WRONLY
            or reader_flags & (os.O_NONBLOCK | getattr(os, "O_ASYNC", 0))
            or writer_flags & (os.O_NONBLOCK | getattr(os, "O_ASYNC", 0))
        ):
            raise CaptureError("capture_pipe_identity")
        descriptors.extend((reader, writer))
        identities.extend(
            (
                (reader_row.st_dev, reader_row.st_ino, os.O_RDONLY),
                (writer_row.st_dev, writer_row.st_ino, os.O_WRONLY),
            )
        )
    if len(descriptors) != len(set(descriptors)) or len(identities) != len(set(identities)):
        raise CaptureError("capture_pipe_alias")

def _pump_aux_pipes(process, writers, reader, payloads, *, maximum, timeout=15.0, selector_factory=selectors.DefaultSelector, monotonic=time.monotonic):
    if (
        type(writers) is not list
        or type(payloads) not in (tuple, list)
        or len(writers) != len(payloads)
        or any(type(raw) is not bytes or not raw for raw in payloads)
        or type(reader) is not int
        or reader < 3
        or type(maximum) is not int
        or maximum < 1
        or type(timeout) not in (int, float)
        or timeout <= 0
    ):
        raise CaptureError("capture_pipe_payload")
    selector = selector_factory()
    pending = {fd: memoryview(raw) for fd, raw in zip(writers, payloads)}
    output = bytearray()
    output_eof = False
    deadline = monotonic() + timeout
    try:
        for descriptor in writers:
            os.set_blocking(descriptor, False)
            selector.register(descriptor, selectors.EVENT_WRITE, "input")
        os.set_blocking(reader, False)
        selector.register(reader, selectors.EVENT_READ, "output")
        while pending or not output_eof:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise CaptureError("capture_pipe_timeout")
            events = selector.select(min(remaining, 0.25))
            if not events and process.poll() is not None and not output_eof:
                continue
            for key, mask in events:
                descriptor = key.fileobj
                if key.data == "input" and mask & selectors.EVENT_WRITE:
                    view = pending[descriptor]
                    try:
                        count = os.write(descriptor, view[:16384])
                    except BlockingIOError:
                        continue
                    if count < 1:
                        raise CaptureError("capture_pipe_write")
                    view = view[count:]
                    if view:
                        pending[descriptor] = view
                    else:
                        selector.unregister(descriptor)
                        pending.pop(descriptor)
                        os.close(descriptor)
                elif key.data == "output" and mask & selectors.EVENT_READ:
                    try:
                        chunk = os.read(
                            reader,
                            min(65536, maximum + 1 - len(output)),
                        )
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(reader)
                        os.close(reader)
                        output_eof = True
                    else:
                        output.extend(chunk)
                        if len(output) > maximum:
                            raise CaptureError("capture_pipe_output")
        return bytes(output)
    finally:
        selector.close()

def _fd_only_verify_signature(payload, signature, key, *, popen=subprocess.Popen):
    if (
        type(payload) is not bytes
        or type(signature) is not bytes
        or type(key) is not bytes
        or not payload
        or not signature
        or not key
        or len(payload) > 1024 * 1024
        or len(signature) > 16384
        or len(key) > 65536
    ):
        return False
    readers = []
    writers = []
    status_reader = status_writer = None
    process = None
    tools_before = None
    try:
        tools_before = _capture_system_identity_snapshot()
        for _unused in range(3):
            reader, writer = os.pipe()
            readers.append(reader)
            writers.append(writer)
        status_reader, status_writer = os.pipe()
        _preflight_pipe_pairs(
            [
                *list(zip(readers, writers)),
                (status_reader, status_writer),
            ]
        )
        arguments = [
            "/usr/bin/openssl",
            "dgst",
            "-sha256",
            "-verify",
            "/dev/fd/" + str(readers[2]),
            "-signature",
            "/dev/fd/" + str(readers[1]),
            "/dev/fd/" + str(readers[0]),
        ]
        process = _spawn_capture_auxiliary(
            popen,
            arguments,
            cwd=RUNTIME_DIRECTORY,
            env=dict(CHILD_ENV),
            stdin=subprocess.DEVNULL,
            stdout=status_writer,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            pass_fds=tuple(readers),
            start_new_session=True,
            preexec_fn=_aux_preexec,
            text=False,
            bufsize=0,
        )
        for descriptor in readers:
            os.close(descriptor)
        readers.clear()
        os.close(status_writer)
        status_writer = None
        status = _pump_aux_pipes(
            process,
            writers,
            status_reader,
            (payload, signature, key),
            maximum=4096,
        )
        writers.clear()
        status_reader = None
        return (
            _settle_capture_auxiliary(process) == 0
            and status == b"Verified OK\n"
            and _capture_system_identity_snapshot() == tools_before
        )
    except BaseException as exc:
        if process is not None and ACTIVE_CAPTURE_AUX_PROCESS is process:
            try:
                _settle_capture_auxiliary(process, force_kill=True, wait_timeout=0.0)
            except BaseException:
                pass
        if isinstance(exc, CaptureSignal):
            raise
        return False
    finally:
        for descriptor in readers + writers:
            try:
                os.close(descriptor)
            except OSError:
                pass
        for descriptor in (status_reader, status_writer):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

def _fd_only_openssl(arguments, *, stdin, timeout=15, popen=subprocess.Popen):
    allowed = (
        ["pkey", "-pubin", "-pubout"],
        ["pkey", "-pubin", "-inform", "PEM", "-outform", "DER"],
    )
    if (
        arguments not in allowed
        or type(stdin) is not bytes
        or not stdin
        or len(stdin) > 65536
        or timeout != 15
    ):
        raise CaptureError("capture_openssl_arguments")
    input_reader = input_writer = output_reader = output_writer = None
    process = None
    tools_before = _capture_system_identity_snapshot()
    try:
        input_reader, input_writer = os.pipe()
        output_reader, output_writer = os.pipe()
        _preflight_pipe_pairs(
            [
                (input_reader, input_writer),
                (output_reader, output_writer),
            ]
        )
        process = _spawn_capture_auxiliary(
            popen,
            ["/usr/bin/openssl", *arguments],
            cwd=RUNTIME_DIRECTORY,
            env=dict(CHILD_ENV),
            stdin=input_reader,
            stdout=output_writer,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            pass_fds=(input_reader,),
            start_new_session=True,
            preexec_fn=_aux_preexec,
            text=False,
            bufsize=0,
        )
        os.close(input_reader)
        input_reader = None
        os.close(output_writer)
        output_writer = None
        output = _pump_aux_pipes(
            process,
            [input_writer],
            output_reader,
            [stdin],
            maximum=65536,
            timeout=15.0,
        )
        input_writer = None
        output_reader = None
        if (
            _settle_capture_auxiliary(process) != 0
            or not output
            or _capture_system_identity_snapshot() != tools_before
        ):
            raise CaptureError("capture_openssl_process")
        return output
    except BaseException as exc:
        if process is not None and ACTIVE_CAPTURE_AUX_PROCESS is process:
            try:
                _settle_capture_auxiliary(process, force_kill=True, wait_timeout=0.0)
            except BaseException:
                pass
        if isinstance(exc, CaptureSignal):
            raise
        if isinstance(exc, CaptureError):
            raise
        raise CaptureError("capture_openssl_process") from None
    finally:
        for descriptor in (input_reader, input_writer, output_reader, output_writer):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

def _spawn_feed_drain_once(
    request_raw,
    credential_envelope,
    *,
    runtime_arguments,
    child_timeout_seconds=CHILD_TIMEOUT_SECONDS,
    socketpair_factory=socket.socketpair,
    selector_factory=selectors.DefaultSelector,
    popen=subprocess.Popen,
    monotonic=time.monotonic,
    killpg=os.killpg,
    sleep=time.sleep,
    identity_snapshot=_capture_child_identity_snapshot,
    runtime_identity_snapshot=_capture_runtime_identity_snapshot
):
    global ACTIVE_ADAPTER_PROCESS
    if (
        type(request_raw) is not bytes
        or not request_raw
        or len(request_raw) > MAX_REQUEST_BYTES
        or type(credential_envelope) is not bytearray
        or not credential_envelope
        or len(credential_envelope) > MAX_CREDENTIAL_BYTES
        or type(child_timeout_seconds) not in (int, float)
        or not 0 < child_timeout_seconds <= CHILD_TIMEOUT_SECONDS
    ):
        _scrub(credential_envelope)
        raise CaptureError("child_input")
    parsed_runtime = _parse_runtime_arguments(runtime_arguments)
    runtime_arguments = (
        parsed_runtime["acceptance_revision"],
        str(parsed_runtime["program_size"]),
        parsed_runtime["program_sha256"],
        str(parsed_runtime["manifest_size"]),
        parsed_runtime["manifest_sha256"],
    )
    pairs = []
    selector = None
    process = None
    proof = None
    identity_before = None
    runtime_identity_before = None
    state = {"child_spawned": False, "group_absent": False}
    response = bytearray()
    status = bytearray()
    failure = None
    timed_out = False
    hard_deadline = monotonic() + child_timeout_seconds
    reap_grace = min(
        CHILD_REAP_GRACE_SECONDS,
        max(0.01, child_timeout_seconds / 4.0),
    )
    io_deadline = hard_deadline - reap_grace
    try:
        identity_before = identity_snapshot()
        if type(identity_before) is not dict or set(identity_before) != set(CHILD_TOOL_BINDINGS):
            raise CaptureError("child_tool_identity")
        runtime_identity_before = runtime_identity_snapshot(runtime_arguments)
        if (
            type(runtime_identity_before) is not dict
            or set(runtime_identity_before)
            != {CAPTURE_PROGRAM_PATH, CAPTURE_MANIFEST_PATH}
        ):
            raise CaptureError("child_runtime_identity")
        for _name in FD_CHANNELS:
            pairs.append(socketpair_factory(socket.AF_UNIX, socket.SOCK_STREAM))
        channels = [channel for pair in pairs for channel in pair]
        identities = [_socket_identity(channel) for channel in channels]
        if len(set(identities)) != len(identities):
            raise CaptureError("fd_alias")
        parent_request, child_request = pairs[0]
        parent_credential, child_credential = pairs[1]
        parent_response, child_response = pairs[2]
        parent_status, child_status = pairs[3]
        pass_fds = (
            child_request.fileno(),
            child_credential.fileno(),
            child_response.fileno(),
            child_status.fileno(),
        )
        argv = [
            "/usr/bin/python3",
            "-I",
            "-S",
            "-B",
            CAPTURE_PROGRAM_PATH,
            "--adapter-child",
            *(str(fd) for fd in pass_fds),
            *runtime_arguments,
        ]
        previous_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK,
            CAPTURE_TERMINATION_SIGNALS,
        )
        try:
            if ACTIVE_ADAPTER_PROCESS is not None:
                raise CaptureError("active_adapter_process")
            process = popen(
                argv,
                executable="/usr/bin/python3",
                cwd=RUNTIME_DIRECTORY,
                env=dict(CHILD_ENV),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                pass_fds=pass_fds,
                preexec_fn=_child_preexec,
            )
            ACTIVE_ADAPTER_PROCESS = process
            state["child_spawned"] = True
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        for child in (child_request, child_credential, child_response, child_status):
            child.close()
        selector = selector_factory()
        selector.register(parent_request, selectors.EVENT_WRITE, "request")
        selector.register(parent_credential, selectors.EVENT_WRITE, "credential")
        selector.register(parent_response, selectors.EVENT_READ, "response")
        selector.register(parent_status, selectors.EVENT_READ, "status")
        offsets = {"request": 0, "credential": 0}
        inputs = {"request": request_raw, "credential": credential_envelope}
        outputs = {"response": response, "status": status}
        limits = {"response": MAX_RESPONSE_BYTES, "status": MAX_STATUS_BYTES}
        input_done = set()
        output_eof = set()
        while len(input_done) != 2 or len(output_eof) != 2:
            remaining = io_deadline - monotonic()
            if remaining <= 0:
                timed_out = True
                failure = "child_timeout"
                break
            events = selector.select(min(remaining, 0.25))
            if not events and process.poll() is not None and len(output_eof) != 2:
                continue
            for key, mask in events:
                name = key.data
                channel = key.fileobj
                if name in inputs and mask & selectors.EVENT_WRITE:
                    raw = inputs[name]
                    offset = offsets[name]
                    try:
                        count = channel.send(raw[offset:offset + 16384])
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        failure = "child_input_channel"
                        break
                    if count <= 0:
                        failure = "child_input_channel"
                        break
                    offsets[name] += count
                    if offsets[name] == len(raw):
                        channel.shutdown(socket.SHUT_WR)
                        selector.unregister(channel)
                        input_done.add(name)
                        if name == "credential":
                            _scrub(credential_envelope)
                elif name in outputs and mask & selectors.EVENT_READ:
                    try:
                        chunk = channel.recv(65536)
                    except (ConnectionResetError, OSError):
                        failure = "child_output_channel"
                        break
                    if not chunk:
                        selector.unregister(channel)
                        output_eof.add(name)
                    else:
                        outputs[name].extend(chunk)
                        if len(outputs[name]) > limits[name]:
                            failure = name + "_oversize"
                            break
            if failure is not None:
                break
        previous_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK,
            CAPTURE_TERMINATION_SIGNALS,
        )
        try:
            proof = _kill_reap_prove_group_absent(
                process,
                force_kill=(failure is not None or timed_out),
                wait_timeout=max(0.0, io_deadline - monotonic()),
                reap_timeout=min(
                    CHILD_REAP_GRACE_SECONDS,
                    max(0.01, hard_deadline - monotonic()),
                ),
                killpg=killpg,
                monotonic=monotonic,
                sleep=sleep,
            )
            if proof["reaped"] and proof["group_absent"]:
                ACTIVE_ADAPTER_PROCESS = None
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        state["group_absent"] = proof["group_absent"]
        if not proof["reaped"] or not proof["group_absent"]:
            failure = "process_group_absence_unproven"
        elif failure is None and proof["returncode"] != 0:
            failure = "adapter_child_failed"
        elif failure is None and (len(output_eof) != 2 or len(input_done) != 2):
            failure = "child_channel_eof"
        if failure is None:
            _child_status(bytes(status))
            if not response:
                failure = "response_empty"
    except CaptureError as exc:
        failure = exc.code
    except BaseException:
        failure = "child_internal"
    finally:
        if process is not None and proof is None:
            previous_mask = signal.pthread_sigmask(
                signal.SIG_BLOCK,
                CAPTURE_TERMINATION_SIGNALS,
            )
            try:
                proof = _kill_reap_prove_group_absent(
                    process,
                    force_kill=True,
                    wait_timeout=0.0,
                    reap_timeout=CHILD_REAP_GRACE_SECONDS,
                    killpg=killpg,
                    monotonic=monotonic,
                    sleep=sleep,
                )
                if proof["reaped"] and proof["group_absent"]:
                    ACTIVE_ADAPTER_PROCESS = None
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            state["group_absent"] = proof["group_absent"]
            if not proof["reaped"] or not proof["group_absent"]:
                failure = "process_group_absence_unproven"
        if identity_before is not None:
            try:
                identity_after = identity_snapshot()
                if identity_after != identity_before:
                    failure = "child_tool_identity_drift"
            except CaptureError as exc:
                failure = exc.code
            except Exception:
                failure = "child_tool_identity_drift"
        if runtime_identity_before is not None:
            try:
                if runtime_identity_snapshot(runtime_arguments) != runtime_identity_before:
                    failure = "child_runtime_identity_drift"
            except CaptureError as exc:
                failure = exc.code
            except Exception:
                failure = "child_runtime_identity_drift"
        _scrub(credential_envelope)
        if selector is not None:
            try:
                selector.close()
            except Exception:
                pass
        for pair in pairs:
            for channel in pair:
                try:
                    channel.close()
                except Exception:
                    pass
    if failure is not None:
        response[:] = b""
        status[:] = b""
        raise CaptureError(failure, state) from None
    return {
        "response_raw": bytes(response),
        "status_raw": bytes(status),
        "cloud_dispatch_count": 1,
        "group_absent": True,
        "child_spawned": True,
    }

def _maybe_mark_unknown_once(
    collector,
    *,
    slot,
    reason,
    state,
    explicitly_authorized,
    existing_unknown=False
):
    allowed = (
        explicitly_authorized is True
        and state.get("begin_observed") is True
        and state.get("finish_invoked") is False
        and state.get("group_absent") is True
        and existing_unknown is False
        and state.get("mark_unknown_invoked") is not True
    )
    if not allowed:
        return False
    state["mark_unknown_invoked"] = True
    result = None
    failure = None
    try:
        result = collector.mark_unknown(
            control_revision=CONTROL_REVISION,
            slot=slot,
            reason=reason,
        )
    except Exception:
        failure = "mark_unknown_result_unknown"
    if failure is not None:
        raise CaptureError(failure, state) from None
    try:
        _collector_status(result, expected_status="UNKNOWN_INFLIGHT", slot=slot)
    except CaptureError:
        raise CaptureError("mark_unknown_result_unknown", state) from None
    if (
        result.get("reason") != reason
        or result.get("cloud_request_replay_allowed") is not False
        or result.get("sequence") != state.get("begin_sequence")
    ):
        raise CaptureError("mark_unknown_result_unknown", state)
    state["mark_unknown_observed"] = True
    return True

def _sha256_text(value):
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )

def _initial_credential_capsule(value):
    if (
        type(value) is not dict
        or set(value) != {
            "remaining_seconds",
            "account_binding_sha256",
            "credential_envelope_sha256",
            "refresh_count",
            "configure_count",
        }
        or type(value.get("remaining_seconds")) is not int
        or not INITIAL_MINIMUM_STS_SECONDS <= value["remaining_seconds"] <= 86400
        or not _sha256_text(value.get("account_binding_sha256"))
        or not _sha256_text(value.get("credential_envelope_sha256"))
        or type(value.get("refresh_count")) is not int
        or value["refresh_count"] != 0
        or type(value.get("configure_count")) is not int
        or value["configure_count"] != 0
    ):
        raise CaptureError("initial_temporary_sts")
    return {
        "account_binding_sha256": value["account_binding_sha256"],
        "credential_envelope_sha256": value[
            "credential_envelope_sha256"
        ],
        "initial_remaining_seconds": value["remaining_seconds"],
        "last_remaining_seconds": value["remaining_seconds"],
    }

def _validate_dispatch_credential(value, expected):
    if (
        type(value) is not dict
        or set(value) != {
            "envelope",
            "remaining_seconds",
            "account_binding_sha256",
            "credential_envelope_sha256",
            "refresh_count",
            "configure_count",
        }
        or type(value.get("envelope")) is not bytearray
        or not value["envelope"]
        or len(value["envelope"]) > MAX_CREDENTIAL_BYTES
        or type(value.get("remaining_seconds")) is not int
        or not MINIMUM_STS_SECONDS <= value["remaining_seconds"] <= 86400
        or type(expected) is not dict
        or set(expected) != {
            "account_binding_sha256",
            "credential_envelope_sha256",
            "initial_remaining_seconds",
            "last_remaining_seconds",
        }
        or value["remaining_seconds"] > expected["initial_remaining_seconds"]
        or value["remaining_seconds"] > expected["last_remaining_seconds"]
        or value.get("account_binding_sha256")
        != expected["account_binding_sha256"]
        or value.get("credential_envelope_sha256")
        != expected["credential_envelope_sha256"]
        or _sha256(bytes(value["envelope"]))
        != expected["credential_envelope_sha256"]
        or type(value.get("refresh_count")) is not int
        or value["refresh_count"] != 0
        or type(value.get("configure_count")) is not int
        or value["configure_count"] != 0
    ):
        if type(value) is dict:
            _scrub(value.get("envelope"))
        raise CaptureError("temporary_sts_pre_begin")
    expected["last_remaining_seconds"] = value["remaining_seconds"]
    return value["envelope"]

def _record_page_once(
    collector,
    extractor,
    *,
    slot,
    request_raw,
    credential_supplier,
    expected_credential_capsule,
    expected_sequence,
    child_runner=_spawn_feed_drain_once,
    child_timeout_seconds=CHILD_TIMEOUT_SECONDS,
    explicitly_authorized_mark_unknown=False
):
    state = {
        "begin_invoked": False,
        "begin_observed": False,
        "child_spawn_count": 0,
        "group_absent": False,
        "finish_invoked": False,
        "finish_observed": False,
        "mark_unknown_invoked": False,
    }
    if type(expected_sequence) is not int or not 1 <= expected_sequence <= MAX_PROVIDER_DISPATCHES:
        raise CaptureError("record_sequence")
    credential = None
    try:
        supplied = None
        supplier_failure = None
        try:
            supplied = credential_supplier()
        except Exception:
            supplier_failure = "temporary_sts_pre_begin"
        if supplier_failure is not None:
            raise CaptureError(supplier_failure) from None
        credential = _validate_dispatch_credential(
            supplied,
            expected_credential_capsule,
        )
        state["begin_invoked"] = True
        begin_result = None
        begin_failure = None
        try:
            begin_result = collector.begin(
                control_revision=CONTROL_REVISION,
                slot=slot,
                request_raw=request_raw,
            )
        except Exception:
            begin_failure = "begin_result_unknown"
        if begin_failure is not None:
            raise CaptureError(begin_failure, state) from None
        try:
            _collector_status(
                begin_result,
                expected_status="REQUEST_FROZEN",
                slot=slot,
                digest_key="request_sha256",
                digest=_sha256(request_raw),
            )
        except CaptureError:
            raise CaptureError("begin_result_unknown", state) from None
        if begin_result.get("sequence") != expected_sequence:
            raise CaptureError("begin_result_unknown", state)
        state["begin_observed"] = True
        state["begin_sequence"] = expected_sequence
        child_result = None
        child_failure = None
        try:
            state["child_spawn_count"] = 1
            child_result = child_runner(
                request_raw,
                credential,
                child_timeout_seconds=child_timeout_seconds,
            )
        except CaptureError as exc:
            child_failure = exc.code
            state["child_spawn_count"] = 1 if exc.state.get("child_spawned") else 0
            state["group_absent"] = exc.state.get("group_absent") is True
        except Exception:
            child_failure = "child_result_unknown"
            state["group_absent"] = False
        if child_failure is not None:
            reason = (
                "TRANSPORT_TIMEOUT"
                if child_failure == "child_timeout"
                else "RESPONSE_BODY_OVERSIZE"
                if child_failure == "response_oversize"
                else "NO_RESPONSE_BODY"
                if child_failure == "response_empty"
                else "OFFICIAL_RESPONSE_EXPORT_FAILED"
            )
            _maybe_mark_unknown_once(
                collector,
                slot=slot,
                reason=reason,
                state=state,
                explicitly_authorized=explicitly_authorized_mark_unknown,
            )
            raise CaptureError(child_failure, state) from None
        if type(child_result) is not dict:
            raise CaptureError("child_result_unknown", state)
        state["group_absent"] = child_result.get("group_absent") is True
        if not state["group_absent"]:
            raise CaptureError("process_group_absence_unproven", state)
        response_raw = child_result.get("response_raw")
        status_raw = child_result.get("status_raw")
        try:
            _child_status(status_raw)
        except CaptureError:
            _maybe_mark_unknown_once(
                collector,
                slot=slot,
                reason="OFFICIAL_RESPONSE_EXPORT_FAILED",
                state=state,
                explicitly_authorized=explicitly_authorized_mark_unknown,
            )
            raise CaptureError("child_status", state) from None
        if (
            type(response_raw) is not bytes
            or not response_raw
            or len(response_raw) > MAX_RESPONSE_BYTES
            or child_result.get("cloud_dispatch_count") != 1
        ):
            _maybe_mark_unknown_once(
                collector,
                slot=slot,
                reason="NO_RESPONSE_BODY",
                state=state,
                explicitly_authorized=explicitly_authorized_mark_unknown,
            )
            raise CaptureError("response_shape", state) from None
        state["finish_invoked"] = True
        finish_result = None
        finish_failure = None
        try:
            finish_result = collector.finish(
                control_revision=CONTROL_REVISION,
                slot=slot,
                response_raw=response_raw,
            )
        except Exception:
            finish_failure = "finish_result_unknown"
        if finish_failure is not None:
            response_raw = b""
            raise CaptureError(finish_failure, state) from None
        try:
            _collector_status(
                finish_result,
                expected_status="RESPONSE_RECORDED",
                slot=slot,
                digest_key="response_sha256",
                digest=_sha256(response_raw),
            )
        except CaptureError:
            response_raw = b""
            raise CaptureError("finish_result_unknown", state) from None
        if finish_result.get("sequence") != expected_sequence:
            response_raw = b""
            raise CaptureError("finish_result_unknown", state)
        state["finish_observed"] = True
        derived = None
        derive_failure = None
        try:
            derived = _derive_after_finish(
                slot,
                request_raw,
                response_raw,
                extractor,
            )
        except Exception:
            derive_failure = "post_finish_derivation"
        response_raw = b""
        if derive_failure is not None:
            raise CaptureError(derive_failure, state) from None
        return {
            "next_token": derived["next_token"],
            "identifier_candidates": derived["identifier_candidates"],
            "cloud_dispatch_count": 1,
            "state": dict(state),
        }
    finally:
        _scrub(credential)

def _terminal_identifier(candidates, expected_sha256, *, value_sha256=_value_sha256):
    if type(candidates) is not list or not candidates:
        raise CaptureError("terminal_identifier_missing")
    first = candidates[0]
    if (
        type(first) is not str
        or not first
        or any(type(value) is not str or value != first for value in candidates)
        or value_sha256(first) != expected_sha256
    ):
        raise CaptureError("terminal_identifier_binding")
    return first

def _finalize_status(value):
    if type(value) is not dict or set(value) != {
        "schema",
        "status",
        "provider_raw_file_sha256",
        "actiontrail_raw_file_sha256",
        "cloud_call_count",
        "raw_value_emitted_count",
    } or value.get("schema") != "noteai.item26.manual-cost-stop-collector-status.v2" or value.get("status") != "CAPTURE_INSTALLED" or value.get("cloud_call_count") != 0 or value.get("raw_value_emitted_count") != 0:
        raise CaptureError("finalize_result_unknown")
    for key in ("provider_raw_file_sha256", "actiontrail_raw_file_sha256"):
        if type(value.get(key)) is not str or len(value[key]) != 64:
            raise CaptureError("finalize_result_unknown")
    return value

def _run_capture_once(
    *,
    prepare_dependencies,
    credential_initial,
    credential_supplier,
    child_runner=_spawn_feed_drain_once,
    monotonic=time.monotonic,
    value_sha256=_value_sha256,
    explicitly_authorized_mark_unknown=False
):
    started = monotonic()
    try:
        credential_capsule = _initial_credential_capsule(credential_initial)
    except Exception:
        raise CaptureError("initial_temporary_sts") from None
    collector, extractor = prepare_dependencies()
    identifiers = {}
    dispatch_count = 0
    all_candidates = {SLOTS[0]: [], SLOTS[1]: []}
    for slot in SLOTS:
        seen_tokens = set()
        next_token = None
        while True:
            elapsed = monotonic() - started
            if elapsed < 0 or elapsed >= FULL_CAPTURE_TIMEOUT_SECONDS:
                raise CaptureError("full_capture_timeout")
            if dispatch_count >= MAX_PROVIDER_DISPATCHES:
                raise CaptureError("global_record_limit")
            request_raw = _build_page_request(
                slot,
                identifiers,
                next_token,
                value_sha256=value_sha256,
            )
            remaining = FULL_CAPTURE_TIMEOUT_SECONDS - elapsed
            result = _record_page_once(
                collector,
                extractor,
                slot=slot,
                request_raw=request_raw,
                credential_supplier=credential_supplier,
                expected_credential_capsule=credential_capsule,
                expected_sequence=dispatch_count + 1,
                child_runner=child_runner,
                child_timeout_seconds=min(CHILD_TIMEOUT_SECONDS, remaining),
                explicitly_authorized_mark_unknown=(
                    explicitly_authorized_mark_unknown
                ),
            )
            dispatch_count += 1
            if slot in all_candidates:
                all_candidates[slot].extend(result["identifier_candidates"])
            new_token = result["next_token"]
            if slot not in (SLOTS[0], SLOTS[1]) and new_token is not None:
                raise CaptureError("pagination_not_allowed")
            if new_token is None:
                break
            if new_token in seen_tokens:
                raise CaptureError("pagination_token_cycle")
            seen_tokens.add(new_token)
            next_token = new_token
        if slot == SLOTS[0]:
            identifiers["old_clone"] = _terminal_identifier(
                all_candidates[slot],
                EXPECTED_OLD_CLONE_SHA256,
                value_sha256=value_sha256,
            )
        elif slot == SLOTS[1]:
            identifiers["source"] = _terminal_identifier(
                all_candidates[slot],
                EXPECTED_SOURCE_SHA256,
                value_sha256=value_sha256,
            )
    if monotonic() - started >= FULL_CAPTURE_TIMEOUT_SECONDS:
        raise CaptureError("full_capture_timeout")
    finalize_result = None
    finalize_failure = None
    try:
        finalize_result = collector.finalize(control_revision=CONTROL_REVISION)
    except Exception:
        finalize_failure = "finalize_result_unknown"
    if finalize_failure is not None:
        raise CaptureError(finalize_failure) from None
    _finalize_status(finalize_result)
    if monotonic() - started >= FULL_CAPTURE_TIMEOUT_SECONDS:
        raise CaptureError("finalize_completed_after_deadline")
    return {
        "schema": CAPTURE_SUCCESS_SCHEMA,
        "status": "FIVE_STREAM_CAPTURE_FINALIZED",
        "logical_slot_count": 5,
        "provider_dispatch_count": dispatch_count,
        "maximum_provider_dispatches": MAX_PROVIDER_DISPATCHES,
        "parallel_provider_dispatch_count": 0,
        "finalize_call_count": 1,
        "cloud_write_count": 0,
        "database_connection_count": 0,
        "private_key_read_count": 0,
        "automatic_retry_count": 0,
        "cleanup_count": 0,
        "raw_value_emitted_count": 0,
        "readiness_credit_added": False,
    }

def _write_fd_all(fd, raw):
    if type(fd) is not int or fd < 3 or type(raw) is not bytes or not raw:
        raise CaptureError("status_fd_write")
    offset = 0
    try:
        while offset < len(raw):
            count = os.write(fd, raw[offset:])
            if count <= 0:
                raise OSError("short write")
            offset += count
    except OSError:
        raise CaptureError("status_fd_write") from None

def _shutdown_write(fd):
    duplicate = -1
    try:
        duplicate = os.dup(fd)
        channel = socket.socket(fileno=duplicate)
        duplicate = -1
        try:
            channel.shutdown(socket.SHUT_WR)
        finally:
            channel.close()
    except OSError:
        if duplicate >= 0:
            os.close(duplicate)
        raise CaptureError("fd_shutdown") from None

def _preflight_child_fd_quad(fds):
    if (
        type(fds) is not tuple
        or len(fds) != 4
        or any(type(fd) is not int or fd < 3 for fd in fds)
        or len(set(fds)) != 4
    ):
        raise CaptureError("child_fd_contract")
    duplicates = []
    try:
        identities = []
        for fd in fds:
            duplicate = os.dup(fd)
            duplicates.append(socket.socket(fileno=duplicate))
            identities.append(_socket_identity(duplicates[-1]))
        if len(set(identities)) != 4:
            raise CaptureError("child_fd_alias")
        if duplicates[3].send(b"") != 0:
            raise CaptureError("status_fd_write_preflight")
    except OSError:
        raise CaptureError("child_fd_contract") from None
    finally:
        for channel in duplicates:
            channel.close()

def _adapter_child_main(
    argv,
    *,
    runtime_validator=None,
    adapter_loader=None,
    preflight=_early_core0_clean_env_preflight
):
    preflight()
    if type(argv) is not list or len(argv) != 10 or argv[0] != "--adapter-child":
        raise CaptureError("adapter_child_arguments")
    try:
        fds = tuple(int(value, 10) for value in argv[1:5])
    except (TypeError, ValueError):
        raise CaptureError("adapter_child_arguments") from None
    if any(str(fd) != value for fd, value in zip(fds, argv[1:5])):
        raise CaptureError("adapter_child_arguments")
    _preflight_child_fd_quad(fds)
    runtime_arguments = tuple(argv[5:])
    if runtime_validator is None:
        runtime_validator = _capture_child_runtime_validator_from_arguments(
            runtime_arguments
        )
    validated = runtime_validator()
    if adapter_loader is None:
        adapter = _load_adapter_from_validation(validated)
    else:
        adapter = adapter_loader()
    dispatch = getattr(adapter, "dispatch_authorized_fds", None)
    if not callable(dispatch):
        raise CaptureError("adapter_entrypoint")
    request_fd, credential_fd, response_fd, status_fd = fds
    result = None
    failure = None
    try:
        result = dispatch(request_fd, credential_fd, response_fd)
    except Exception as exc:
        count = getattr(exc, "cloud_dispatch_count", 0)
        failure = count if type(count) is int and count in (0, 1) else 0
    if failure is not None:
        status = {
            "schema": CHILD_STATUS_SCHEMA,
            "status": "READ_DISPATCH_FAILED",
            "cloud_dispatch_count": failure,
            "cloud_write_count": 0,
            "automatic_retry_count": 0,
            "raw_value_emitted_count": 0,
        }
        _write_fd_all(status_fd, canonical(status))
        _shutdown_write(status_fd)
        return 1
    if result != {
        "request_fd_read_count": 1,
        "credential_fd_read_count": 1,
        "response_fd_write_count": 1,
        "cloud_dispatch_count": 1,
        "cloud_write_count": 0,
        "automatic_retry_count": 0,
    }:
        status = {
            "schema": CHILD_STATUS_SCHEMA,
            "status": "READ_DISPATCH_FAILED",
            "cloud_dispatch_count": 1,
            "cloud_write_count": 0,
            "automatic_retry_count": 0,
            "raw_value_emitted_count": 0,
        }
        _write_fd_all(status_fd, canonical(status))
        _shutdown_write(status_fd)
        return 1
    _shutdown_write(response_fd)
    status = {
        "schema": CHILD_STATUS_SCHEMA,
        "status": "ONE_READ_DISPATCH_COMPLETED",
        "cloud_dispatch_count": 1,
        "cloud_write_count": 0,
        "automatic_retry_count": 0,
        "raw_value_emitted_count": 0,
    }
    _write_fd_all(status_fd, canonical(status))
    _shutdown_write(status_fd)
    return 0

def future_capture(*args, **kwargs):
    if EXECUTION_ENABLED is not True:
        raise RuntimeError("future_execution_disabled")
    if len(args) != 1 or kwargs:
        raise CaptureError("capture_public_arguments")
    return _enabled_main(args[0])

def _root_c1_supplier_mapping(context):
    if (
        type(context) is not dict
        or set(context) != {
            "module",
            "capsule",
            "live_snapshot",
            "creation_receipts",
            "inventory_contract",
            "projection",
            "wall_clock",
            "monotonic_ns_clock",
            "handshake_attempt_count",
            "acknowledged",
            "initial",
        }
        or type(context.get("handshake_attempt_count")) is not int
        or context["handshake_attempt_count"] != 1
        or context.get("acknowledged") is not True
    ):
        raise CaptureError("temporary_sts_pre_begin")
    module = _validate_root_c1_module(context.get("module"))
    capsule = context.get("capsule")
    if type(capsule) is not module._RootCustodyTemporaryStsCapsule:
        raise CaptureError("temporary_sts_pre_begin")
    issued = None
    mapping = None
    failure = None
    try:
        wall_now = context["wall_clock"]()
        monotonic_now = context["monotonic_ns_clock"]()
        if type(wall_now) is not int or type(monotonic_now) is not int:
            raise CaptureError("credential_clock")
        issued = capsule.issue_for_begin(
            wall_now_unix=wall_now,
            monotonic_now_ns=monotonic_now,
        )
        if type(issued) is not module.IssuedTemporarySts:
            raise CaptureError("temporary_sts_pre_begin")
        mapping = issued.take_m1_supplier_mapping()
        if (
            type(mapping) is not dict
            or set(mapping) != {
                "envelope",
                "remaining_seconds",
                "account_binding_sha256",
                "credential_envelope_sha256",
                "refresh_count",
                "configure_count",
            }
            or type(mapping.get("envelope")) is not bytearray
        ):
            raise CaptureError("temporary_sts_pre_begin")
    except BaseException as exc:
        failure = exc
    finally:
        if issued is not None:
            try:
                issued.scrub()
            except BaseException as exc:
                if failure is None:
                    failure = exc
    if failure is not None or mapping is None:
        if type(mapping) is dict:
            module.scrub_bytearray(mapping.get("envelope"))
        if isinstance(failure, CaptureSignal):
            raise failure
        raise CaptureError("temporary_sts_pre_begin") from None
    return mapping

def _default_capture_runner(runtime_arguments, credential_context):
    runtime_arguments = tuple(runtime_arguments)
    if (
        type(credential_context) is not dict
        or set(credential_context)
        != {
            "module",
            "capsule",
            "live_snapshot",
            "creation_receipts",
            "inventory_contract",
            "projection",
            "wall_clock",
            "monotonic_ns_clock",
            "handshake_attempt_count",
            "acknowledged",
            "initial",
        }
        or credential_context.get("handshake_attempt_count") != 1
        or credential_context.get("acknowledged") is not True
    ):
        raise CaptureError("credential_session")
    module = _validate_root_c1_module(credential_context["module"])
    capsule = credential_context["capsule"]
    if type(capsule) is not module._RootCustodyTemporaryStsCapsule:
        raise CaptureError("credential_capsule")
    runtime_validator = _capture_runtime_validator_from_arguments(
        runtime_arguments
    )
    validation_state = {}

    def prepare_dependencies():
        if validation_state:
            raise CaptureError("runtime_validation_repeated")

        def validate_once():
            observed = runtime_validator()
            validation_state["before"] = observed
            return observed

        collector, extractor = _default_prepare_capture_dependencies(
            validate_once
        )
        return collector, extractor

    def child_runner(request_raw, credential_envelope, *, child_timeout_seconds):
        return _spawn_feed_drain_once(
            request_raw,
            credential_envelope,
            runtime_arguments=runtime_arguments,
            child_timeout_seconds=child_timeout_seconds,
        )

    try:
        result = _run_capture_once(
            prepare_dependencies=prepare_dependencies,
            credential_initial=credential_context["initial"],
            credential_supplier=lambda: _root_c1_supplier_mapping(
                credential_context
            ),
            child_runner=child_runner,
        )
        if capsule.round_count != result.get("provider_dispatch_count"):
            raise CaptureError("credential_round_count")
        if (
            module.validate_root_custody_inventory(
                credential_context["live_snapshot"],
                creation_receipts=credential_context["creation_receipts"],
            )
            != credential_context["inventory_contract"]
        ):
            raise CaptureError("credential_inventory")
        before = validation_state.get("before")
        if type(before) is not dict or type(before.get("identities")) is not dict:
            raise CaptureError("runtime_identity_drift")
        _capture_post_identity_snapshot(
            runtime_arguments,
            before["identities"],
        )
        return result
    finally:
        try:
            capsule.scrub()
        except BaseException:
            pass

def _enabled_main(
    argv,
    *,
    adapter_child_runner=_adapter_child_main,
    capture_runner=None,
    status_stream=None,
    credential_source_supplier=_root_c1_source_not_provisioned,
    credential_session_factory=_root_c1_live_session_not_provisioned,
    wall_clock=lambda: int(time.time()),
    monotonic_ns_clock=time.monotonic_ns,
    session_monotonic=time.monotonic,
    early_preflight=_early_core0_clean_env_preflight,
    closer=os.close
):
    if type(argv) is not list:
        raise CaptureError("capture_root_arguments")
    if argv and argv[0] == "--adapter-child":
        return adapter_child_runner(argv)
    if (
        len(argv) != 8
        or argv[0] != "--capture"
    ):
        raise CaptureError("capture_root_arguments")
    ready_fd = ack_fd = -1
    runtime_arguments = tuple(argv[3:])
    context = None
    result = None
    failure = None
    try:
        try:
            ready_fd = int(argv[1], 10)
            ack_fd = int(argv[2], 10)
        except (TypeError, ValueError):
            raise CaptureError("capture_root_arguments") from None
        if (
            ready_fd < 3
            or ack_fd < 3
            or ready_fd == ack_fd
            or argv[1] != str(ready_fd)
            or argv[2] != str(ack_fd)
        ):
            raise CaptureError("capture_root_arguments")
        setup_started = session_monotonic()
        if (
            type(setup_started) not in {int, float}
            or not math.isfinite(setup_started)
        ):
            raise CaptureError("credential_clock")
        _parse_runtime_arguments(runtime_arguments)
        early_preflight()
        module = _load_root_c1_module(credential_source_supplier())
        context = _prepare_root_c1_live_session(
            module,
            credential_session_factory,
            wall_clock=wall_clock,
            monotonic_ns_clock=monotonic_ns_clock,
        )
        handshake_owned = {ready_fd, ack_fd}

        def close_handshake_descriptor(descriptor):
            if descriptor not in handshake_owned:
                raise CaptureError("credential_handshake")
            closer(descriptor)
            handshake_owned.remove(descriptor)

        try:
            _complete_root_c1_handshake(
                context,
                ready_fd,
                ack_fd,
                closer=close_handshake_descriptor,
            )
        finally:
            if ready_fd not in handshake_owned:
                ready_fd = -1
            if ack_fd not in handshake_owned:
                ack_fd = -1
        setup_elapsed = session_monotonic() - setup_started
        if (
            type(setup_elapsed) not in {int, float}
            or not math.isfinite(setup_elapsed)
            or setup_elapsed < 0
            or setup_elapsed >= C1_SESSION_SETUP_TIMEOUT_SECONDS
        ):
            raise CaptureError("credential_handshake_timeout")
        runner = _default_capture_runner if capture_runner is None else capture_runner
        result = runner(runtime_arguments, context)
    except BaseException as exc:
        failure = exc
    finally:
        if context is not None:
            try:
                context["capsule"].scrub()
            except BaseException as exc:
                if failure is None:
                    failure = exc
        closed = set()
        for descriptor in (ready_fd, ack_fd):
            if descriptor >= 3 and descriptor not in closed:
                closed.add(descriptor)
                try:
                    closer(descriptor)
                except BaseException as exc:
                    if failure is None:
                        failure = exc
    if failure is not None:
        if isinstance(failure, (CaptureError, CaptureSignal)):
            raise failure
        raise CaptureError("capture_root_session") from None
    if (
        type(result) is not dict
        or result.get("schema") != CAPTURE_SUCCESS_SCHEMA
        or result.get("status") != "FIVE_STREAM_CAPTURE_FINALIZED"
        or result.get("raw_value_emitted_count") != 0
    ):
        raise CaptureError("capture_root_status")
    stream = sys.stdout.buffer if status_stream is None else status_stream
    stream.write(canonical(result))
    stream.flush()
    return 0

def _public_enabled_main(
    argv,
    *,
    enabled_runner=_enabled_main,
    status_stream=None,
    signal_installer=_install_capture_signal_handlers
):
    signal_installer()
    result = None
    failed = False
    try:
        result = enabled_runner(argv)
    except BaseException:
        failed = True
    if not failed:
        return result
    status = {
        "schema": CAPTURE_PUBLIC_STATUS_SCHEMA,
        "status": "BLOCKED_FIXED_FAILURE",
        "provider_dispatch_count_known": False,
        "automatic_retry_count": 0,
        "cleanup_count": 0,
        "raw_value_emitted_count": 0,
    }
    stream = sys.stdout.buffer if status_stream is None else status_stream
    stream.write(canonical(status))
    stream.flush()
    return 78

def main():
    if EXECUTION_ENABLED is True:
        return _public_enabled_main(sys.argv[1:])
    sys.stdout.buffer.write(canonical(STATUS))
    sys.stdout.buffer.flush()
    return 78

if __name__ == "__main__":
    raise SystemExit(main())
'''


MATERIALIZE_ROOT_PROGRAM = r'''
import ast
import fcntl
import hashlib
import json
import os
import pathlib
import resource
import selectors
import signal
import socket
import stat
import subprocess
import sys
import time

EXECUTION_ENABLED = False
SOURCE_ONLY_IMPLEMENTATION_STATUS = "SOURCE_ONLY_IMPLEMENTATION_COMPLETE_NOT_AUTHORIZED"
PUBLIC_REFS = (
    "deploy/production/evidence/item26-manual-cost-stop-provider-receipt-v2-20260817.json",
    "deploy/production/evidence/production-item26-manual-cost-stop-v2-20260817.json",
)
FORBIDDEN_PUBLIC_REF = "deploy/production/evidence/item26-manual-cost-stop-terminal-checkpoint-v2-20260817.json"
RUNTIME_DIRECTORY = "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-m1-materialize"
AUTHORITY_DIRECTORY = "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2"
EXISTING_RUNTIME_DIRECTORY = "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-tools"
JOURNAL_DIRECTORY = "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-journal"
CUSTODY_DIRECTORY = "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-custody"
REPOSITORY_ROOT = "/Users/openclaw/Desktop/noteai"
CONTROL_REVISION = "68aa82ffbdd43e78e585d8956d13d3030ef6a640"
PARENT_ACCEPTANCE_REVISION = "a30b879d06c388a4a0e230b5a23b2eaedc93649d"
STAGER_REF = "tools/stage_collect_and_materialize_item26_manual_cost_stop_m1_v2.py"
MATERIALIZE_PROGRAM_PATH = RUNTIME_DIRECTORY + "/materialize-root-program.py"
MAX_RECEIPT_BYTES = 8 * 1024 * 1024
MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
MAX_STATUS_BYTES = 4096
MAX_SIGNATURE_MESSAGE_BYTES = 1024 * 1024
MAX_SIGNATURE_BYTES = 4096
MAX_PUBLIC_KEY_BYTES = 16384
CHILD_ENV = {"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"}
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
}
OUTPUT_STATUS_SCHEMA = "noteai.item26.m1-materialize-child-status.v1"
PUBLIC_STATUS_SCHEMA = "noteai.item26.m1-materialize-public-status.v1"
RUNTIME_MANIFEST_SCHEMA = "noteai.item26.m1-root-runtime-manifest.v1"
RECEIPT_SCHEMA = "noteai.item26.manual-cost-stop-provider-receipt.v2"
EVIDENCE_SCHEMA = "noteai.item26.manual-cost-stop-evidence.v2"
CAPTURE_ORDER = (
    "authority-root-v2.json",
    "provider-raw-v2.json",
    "actiontrail-raw-v2.json",
)
CAPTURE_NAMES = frozenset(CAPTURE_ORDER)
RUNTIME_NAMES = frozenset({
    "materialize-root-program.py",
    "build_item26_manual_cost_stop_evidence_v2.py",
    "verify_item26_manual_cost_stop_evidence_v2.py",
    "extract_item26_manual_cost_stop_raw_v2.py",
    "verify_item26_manual_cost_stop_authority_v2.py",
    "materialize-runtime-manifest.json",
})
FIXED_RUNTIME_BINDINGS = {
    "build_item26_manual_cost_stop_evidence_v2.py": (16835, "ecf0a3d984b99b09e9f3d189f28fb8b60bd2355a28bf04565fd7c297fa765acb", 0o500, "tools/build_item26_manual_cost_stop_evidence_v2.py"),
    "verify_item26_manual_cost_stop_evidence_v2.py": (40689, "8834c524165f3104cdf848e26eaefdcb3ed0e0e635e9ec3c1a02d3bcb02c6269", 0o500, "tools/verify_item26_manual_cost_stop_evidence_v2.py"),
    "extract_item26_manual_cost_stop_raw_v2.py": (62917, "7264bc6d1b3028c141a32d56a69e248fac283c835f776ed6f7c09b9f1c2d0fd4", 0o500, "tools/extract_item26_manual_cost_stop_raw_v2.py"),
    "verify_item26_manual_cost_stop_authority_v2.py": (125914, "19cc65133410cfa4face4887943504c8726430cc196b4f83d68cb3e0675a959d", 0o500, "tools/verify_item26_manual_cost_stop_authority_v2.py"),
}
LOCAL_OBJECT_BINDINGS = {
    "tools/build_item26_manual_cost_stop_evidence_v2.py": ("861f355a92505c9e3f000a74acb57598375dd16e", 16835, "ecf0a3d984b99b09e9f3d189f28fb8b60bd2355a28bf04565fd7c297fa765acb"),
    "tools/verify_item26_manual_cost_stop_evidence_v2.py": ("95727f7e6b8bcb7ff738ee2b2f0b9c650fc59968", 40689, "8834c524165f3104cdf848e26eaefdcb3ed0e0e635e9ec3c1a02d3bcb02c6269"),
    "tools/extract_item26_manual_cost_stop_raw_v2.py": ("64b87e4630b894f57f64317e0b3cb70b8367e153", 62917, "7264bc6d1b3028c141a32d56a69e248fac283c835f776ed6f7c09b9f1c2d0fd4"),
    "tools/verify_item26_manual_cost_stop_authority_v2.py": ("91d5eaf9d63f3595c257ad31502407d1bb9a3cb0", 125914, "19cc65133410cfa4face4887943504c8726430cc196b4f83d68cb3e0675a959d"),
}
AUTHORITY_ROOT_BINDING = (20816, "8bfb8834c1e241a18cde984d42524759f53423bcf809dd8657fa4b2be102ff85", 0o600)
EXISTING_RUNTIME_BINDINGS = {
    "collect_item26_manual_cost_stop_raw_v2.py": (85025, "739b8e8bea29250ccd4c24b400af791c67e687f0cecd23a4b1ddbc8b70750ea4", 0o600),
    "extract_item26_manual_cost_stop_raw_v2.py": (62917, "7264bc6d1b3028c141a32d56a69e248fac283c835f776ed6f7c09b9f1c2d0fd4", 0o600),
    "verify_item26_manual_cost_stop_authority_v2.py": (125914, "19cc65133410cfa4face4887943504c8726430cc196b4f83d68cb3e0675a959d", 0o600),
    "runtime-activation-receipt-v3.json": (22068, "61b756abed72b2f6ab8fb3b20a260b03c0932f6e4c271c4f723a4e5942cd7f2a", 0o600),
}
CUSTODY_NAMES = frozenset({
    "provider-private-key.pem",
    "confirmation-private-key.pem",
    "local-ci-observation-private-key.pem",
})
SYSTEM_TOOL_BINDINGS = {
    "/usr/bin/git": (118928, "179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818", 0o755, 0, 0, 78),
    "/Library/Developer/CommandLineTools/usr/bin/git": (7604272, "3121e7e4d16059539731c58d94888709c12904abe922acde8e37caef4607c1d1", 0o755, 0, 0, 1),
    "/usr/bin/openssl": (1134000, "517827f877751b6d7abebe404a296fa8e82425c63694a73ab06db35e6d9a8362", 0o755, 0, 0, 1),
    "/usr/bin/python3": (118928, "179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818", 0o755, 0, 0, 78),
    "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9": (102352, "4b42b1a117605cafc8607b67b0892a609c2cd125012dd56288abeed8c89cdfb1", 0o755, 0, 0, 1),
}
ALLOWED_PARENT_SYMLINKS = {"/etc": "private/etc"}
CONTRACT = {
    "schema": "noteai.item26.m1-materialize-root-scaffold-contract.v1",
    "status": SOURCE_ONLY_IMPLEMENTATION_STATUS,
    "requires_new_cto_authorization": True,
    "implementation_complete": True,
    "operational_ready": False,
    "runtime_mode": "0700",
    "finalized_capture_inventory_required": True,
    "network_guard_required_before_dynamic_load": True,
    "process_guard_required_before_dynamic_load": True,
    "process_guard_exact_executable_exceptions": (
        "/usr/bin/git",
        "/usr/bin/openssl",
    ),
    "process_guard_all_other_executables_denied": True,
    "authority_signature_patch_target": "_verify_signature",
    "authority_original_signature_callable_allowed": False,
    "authority_git_no_lazy_fetch_patch_before_validation": True,
    "public_output_fd_only": True,
    "public_output_fd_channels": ("receipt", "evidence", "fixed_status"),
    "public_output_concurrent_drain_required": True,
    "public_output_count": 2,
    "allowed_builder_entrypoints": ("build_receipt", "build_evidence"),
    "builder_expected_control_revision": "68aa82ffbdd43e78e585d8956d13d3030ef6a640",
    "builder_root": "/Users/openclaw/Desktop/noteai",
    "builder_authority_directory": "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2",
    "builder_default_root_allowed": False,
    "runtime_source_names": (
        "materialize-root-program.py",
        "build_item26_manual_cost_stop_evidence_v2.py",
        "verify_item26_manual_cost_stop_evidence_v2.py",
        "extract_item26_manual_cost_stop_raw_v2.py",
        "verify_item26_manual_cost_stop_authority_v2.py",
        "materialize-runtime-manifest.json",
    ),
    "checkpoint_create_allowed": False,
    "temporary_signature_files_allowed": False,
    "authorized_and_incurred_cny": "0.00",
    "cloud_write_database_private_key_counts": 0,
}
STATUS = {
    "schema": "noteai.item26.m1-materialize-root-source.v1",
    "status": SOURCE_ONLY_IMPLEMENTATION_STATUS,
    "authorizes_execution": False,
    "implementation_complete": True,
    "operational_ready": False,
    "public_artifact_count": 0,
    "root_read_count": 0,
    "root_write_count": 0,
    "cleanup_count": 0,
    "automatic_retry_count": 0,
    "readiness_credit_added": False,
    "authorized_cny": "0.00",
    "incurred_cny": "0.00",
    "cloud_write_count": 0,
    "provider_dispatch_count": 0,
    "database_connection_count": 0,
    "database_transaction_count": 0,
    "database_write_count": 0,
    "private_key_read_count": 0,
    "private_key_write_count": 0,
    "private_key_output_count": 0,
    "credential_configuration_count": 0,
    "credential_refresh_count": 0,
}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n"

class MaterializeError(ValueError):
    pass

MATERIALIZE_TERMINATION_SIGNALS = (
    signal.SIGTERM,
    signal.SIGINT,
    signal.SIGHUP,
    signal.SIGQUIT,
    signal.SIGALRM,
)
ACTIVE_MATERIALIZE_PROCESS = None
MATERIALIZE_TERMINATION_REQUESTED = False

class MaterializeSignal(BaseException):
    pass

def _materialize_signal_handler(_signum, _frame):
    global MATERIALIZE_TERMINATION_REQUESTED
    MATERIALIZE_TERMINATION_REQUESTED = True
    raise MaterializeSignal()

def _install_materialize_signal_handlers(*, installer=signal.signal):
    for signum in MATERIALIZE_TERMINATION_SIGNALS:
        installer(signum, _materialize_signal_handler)
    return True

def _sha256(raw):
    if type(raw) is not bytes:
        raise MaterializeError("materialize_bytes")
    return hashlib.sha256(raw).hexdigest()

def _hex(value, width):
    return type(value) is str and len(value) == width and all(character in "0123456789abcdef" for character in value)

def _read_file_bounded(path, maximum, *, opener=os.open, fstat=os.fstat, reader=os.read, closer=os.close):
    if type(path) is not str or not path.startswith("/") or type(maximum) is not int or maximum < 1:
        raise MaterializeError("materialize_file_path")
    descriptor = opener(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        row = fstat(descriptor)
        if not stat.S_ISREG(row.st_mode) or row.st_size < 0 or row.st_size > maximum:
            raise MaterializeError("materialize_file_identity")
        chunks = []
        total = 0
        while True:
            chunk = reader(descriptor, min(65536, maximum + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise MaterializeError("materialize_file_size")
            chunks.append(chunk)
        raw = b"".join(chunks)
        if len(raw) != row.st_size:
            raise MaterializeError("materialize_file_changed")
        return raw
    finally:
        closer(descriptor)

def _stable_regular(path, raw, expected, *, lstater=os.lstat):
    row = lstater(path)
    size, digest, mode = expected
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or row.st_uid != 0
        or row.st_gid != 0
        or row.st_nlink != 1
        or stat.S_IMODE(row.st_mode) != mode
        or row.st_size != size
        or len(raw) != size
        or _sha256(raw) != digest
    ):
        raise MaterializeError("materialize_file_binding")
    return (row.st_dev, row.st_ino, row.st_size, row.st_mode, row.st_uid, row.st_gid, row.st_nlink, digest)

def _stable_directory(path, expected_names, *, list_names=os.listdir, lstater=os.lstat):
    row = lstater(path)
    if (
        not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or row.st_uid != 0
        or row.st_gid != 0
        or row.st_nlink < 1
        or stat.S_IMODE(row.st_mode) != 0o700
        or set(list_names(path)) != set(expected_names)
    ):
        raise MaterializeError("materialize_directory_binding")
    return (row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid, row.st_nlink)

def _root_parent_probe(path, *, lstater=os.lstat):
    rows = []
    for parent in pathlib.Path(path).parents:
        row = lstater(str(parent))
        if (
            not stat.S_ISDIR(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or row.st_uid != 0
            or stat.S_IMODE(row.st_mode) & 0o022
        ):
            raise MaterializeError("materialize_parent_binding")
        rows.append((str(parent), row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid, row.st_nlink))
    return tuple(rows)

def _expected_manifest(program_size, program_sha256, accepted_source_revision):
    if (
        type(program_size) is not int
        or program_size < 1
        or not _hex(program_sha256, 64)
        or not _hex(accepted_source_revision, 40)
        or accepted_source_revision == PARENT_ACCEPTANCE_REVISION
    ):
        raise MaterializeError("materialize_program_binding")
    payloads = {
        "materialize-root-program.py": {
            "name": "materialize-root-program.py",
            "byte_count": program_size,
            "sha256": program_sha256,
            "mode": "0500",
            "source_revision": accepted_source_revision,
            "source_ref": STAGER_REF + ":MATERIALIZE_ROOT_PROGRAM",
        }
    }
    for name, (size, digest, mode, source_ref) in FIXED_RUNTIME_BINDINGS.items():
        payloads[name] = {
            "name": name,
            "byte_count": size,
            "sha256": digest,
            "mode": format(mode, "04o"),
            "source_revision": CONTROL_REVISION,
            "source_ref": source_ref,
        }
    return {
        "schema": RUNTIME_MANIFEST_SCHEMA,
        "manifest_name": "materialize-runtime-manifest.json",
        "manifest_mode": "0600",
        "payloads": payloads,
    }

def _default_object_probe(revision, source_ref, expected_oid, expected_size, expected_sha256):
    del revision, source_ref, expected_oid, expected_size, expected_sha256
    raise MaterializeError("materialize_object_probe_unbound")

def _default_tool_probe(path, expected):
    raw = _read_file_bounded(path, expected[0])
    row = os.lstat(path)
    parent_rows = []
    for parent in pathlib.Path(path).parents:
        parent_row = parent.lstat()
        if stat.S_ISLNK(parent_row.st_mode):
            target = os.readlink(parent)
            if (
                ALLOWED_PARENT_SYMLINKS.get(str(parent)) != target
                or parent_row.st_uid != 0
            ):
                raise MaterializeError("materialize_tool_parent")
            kind = ("symlink", target)
        else:
            if (
                not stat.S_ISDIR(parent_row.st_mode)
                or parent_row.st_uid != 0
                or stat.S_IMODE(parent_row.st_mode) & 0o022
            ):
                raise MaterializeError("materialize_tool_parent")
            kind = ("directory", "")
        parent_rows.append(
            (
                str(parent),
                *kind,
                parent_row.st_dev,
                parent_row.st_ino,
                parent_row.st_mode,
                parent_row.st_uid,
                parent_row.st_gid,
                parent_row.st_nlink,
                getattr(parent_row, "st_mtime_ns", 0),
                getattr(parent_row, "st_ctime_ns", 0),
            )
        )
    if not (
        stat.S_ISREG(row.st_mode)
        and not stat.S_ISLNK(row.st_mode)
        and row.st_size == expected[0]
        and _sha256(raw) == expected[1]
        and stat.S_IMODE(row.st_mode) == expected[2]
        and row.st_uid == expected[3]
        and row.st_gid == expected[4]
        and row.st_nlink == expected[5]
    ):
        raise MaterializeError("materialize_tool_binding")
    return (
        (
            path,
            row.st_dev,
            row.st_ino,
            row.st_size,
            row.st_mode,
            row.st_uid,
            row.st_gid,
            row.st_nlink,
            getattr(row, "st_mtime_ns", 0),
            getattr(row, "st_ctime_ns", 0),
            expected[1],
        ),
        tuple(parent_rows),
    )

def _snapshot_preserved_partitions(*, list_names=os.listdir, lstater=os.lstat, read_file=_read_file_bounded, parent_probe=_root_parent_probe):
    identities = {}
    for path, names in (
        (EXISTING_RUNTIME_DIRECTORY, frozenset(EXISTING_RUNTIME_BINDINGS)),
        (JOURNAL_DIRECTORY, frozenset()),
        (CUSTODY_DIRECTORY, CUSTODY_NAMES),
    ):
        identities["parents/" + path] = parent_probe(path, lstater=lstater)
        identities["directory/" + path] = _stable_directory(
            path,
            names,
            list_names=list_names,
            lstater=lstater,
        )
    for name, expected in sorted(EXISTING_RUNTIME_BINDINGS.items()):
        path = EXISTING_RUNTIME_DIRECTORY + "/" + name
        raw = read_file(path, expected[0])
        identities["existing-runtime/" + name] = _stable_regular(
            path,
            raw,
            expected,
            lstater=lstater,
        )
    for name in sorted(CUSTODY_NAMES):
        path = CUSTODY_DIRECTORY + "/" + name
        row = lstater(path)
        if (
            not stat.S_ISREG(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or row.st_uid != 0
            or row.st_gid != 0
            or row.st_nlink != 1
            or stat.S_IMODE(row.st_mode) != 0o600
            or row.st_size < 1
        ):
            raise MaterializeError("materialize_custody_binding")
        identities["custody/" + name] = (
            row.st_dev,
            row.st_ino,
            row.st_size,
            row.st_mode,
            row.st_uid,
            row.st_gid,
            row.st_nlink,
            row.st_mtime_ns,
            row.st_ctime_ns,
        )
    return identities

def _validate_runtime_capture_and_local_objects(
    *,
    program_size,
    program_sha256,
    accepted_source_revision,
    stager_size,
    stager_sha256,
    stager_blob_oid,
    manifest_size,
    manifest_sha256,
    capture_bindings,
    list_names=os.listdir,
    lstater=os.lstat,
    read_file=_read_file_bounded,
    object_probe=_default_object_probe,
    tool_probe=_default_tool_probe,
    preserved_snapshot=_snapshot_preserved_partitions,
    parent_probe=_root_parent_probe,
):
    if (
        type(stager_size) is not int
        or stager_size <= program_size
        or not _hex(stager_sha256, 64)
        or not _hex(stager_blob_oid, 40)
    ):
        raise MaterializeError("materialize_stager_binding")
    manifest = canonical(_expected_manifest(program_size, program_sha256, accepted_source_revision))
    if manifest_size != len(manifest) or manifest_sha256 != _sha256(manifest):
        raise MaterializeError("materialize_manifest_argument")
    if type(capture_bindings) is not dict or set(capture_bindings) != CAPTURE_NAMES:
        raise MaterializeError("materialize_capture_binding")
    if capture_bindings.get("authority-root-v2.json") != AUTHORITY_ROOT_BINDING:
        raise MaterializeError("materialize_authority_root_binding")
    runtime_parents = parent_probe(RUNTIME_DIRECTORY, lstater=lstater)
    authority_parents = parent_probe(AUTHORITY_DIRECTORY, lstater=lstater)
    _stable_directory(RUNTIME_DIRECTORY, RUNTIME_NAMES, list_names=list_names, lstater=lstater)
    _stable_directory(AUTHORITY_DIRECTORY, CAPTURE_NAMES, list_names=list_names, lstater=lstater)
    runtime_expected = {
        "materialize-root-program.py": (program_size, program_sha256, 0o500),
        "materialize-runtime-manifest.json": (manifest_size, manifest_sha256, 0o600),
    }
    runtime_expected.update({name: row[:3] for name, row in FIXED_RUNTIME_BINDINGS.items()})
    runtime_raw = {}
    identities = preserved_snapshot(
        list_names=list_names,
        lstater=lstater,
        read_file=read_file,
    )
    identities["parents/" + RUNTIME_DIRECTORY] = runtime_parents
    identities["parents/" + AUTHORITY_DIRECTORY] = authority_parents
    for name in sorted(RUNTIME_NAMES):
        expected = runtime_expected[name]
        raw = read_file(RUNTIME_DIRECTORY + "/" + name, max(expected[0], 1))
        if name == "materialize-runtime-manifest.json" and raw != manifest:
            raise MaterializeError("materialize_manifest_bytes")
        runtime_raw[name] = raw
        identities["runtime/" + name] = _stable_regular(
            RUNTIME_DIRECTORY + "/" + name,
            raw,
            expected,
            lstater=lstater,
        )
    capture_raw = {}
    for name in sorted(CAPTURE_NAMES):
        expected = capture_bindings[name]
        if (
            type(expected) is not tuple
            or len(expected) != 3
            or type(expected[0]) is not int
            or expected[0] < 1
            or expected[0] > 64 * 1024 * 1024
            or not _hex(expected[1], 64)
            or expected[2] != 0o600
        ):
            raise MaterializeError("materialize_capture_binding")
        raw = read_file(AUTHORITY_DIRECTORY + "/" + name, expected[0])
        capture_raw[name] = raw
        identities["capture/" + name] = _stable_regular(
            AUTHORITY_DIRECTORY + "/" + name,
            raw,
            expected,
            lstater=lstater,
        )
    for source_ref, (oid, size, digest) in sorted(LOCAL_OBJECT_BINDINGS.items()):
        observed = object_probe(CONTROL_REVISION, source_ref, oid, size, digest)
        if observed != {
            "present": True,
            "git_blob_oid": oid,
            "byte_count": size,
            "sha256": digest,
            "promisor_remote_count": 0,
            "partial_clone_config_count": 0,
        }:
            raise MaterializeError("materialize_local_object")
    stager_observed = object_probe(
        accepted_source_revision,
        STAGER_REF,
        stager_blob_oid,
        stager_size,
        stager_sha256,
    )
    if stager_observed != {
        "present": True,
        "git_blob_oid": stager_blob_oid,
        "byte_count": stager_size,
        "sha256": stager_sha256,
        "promisor_remote_count": 0,
        "partial_clone_config_count": 0,
        "embedded_literal_name": "MATERIALIZE_ROOT_PROGRAM",
        "embedded_literal_byte_count": program_size,
        "embedded_literal_sha256": program_sha256,
    }:
        raise MaterializeError("materialize_stager_object")
    for path, expected in sorted(SYSTEM_TOOL_BINDINGS.items()):
        observed_tool = tool_probe(path, expected)
        if not observed_tool:
            raise MaterializeError("materialize_tool_binding")
        identities["tool/" + path] = observed_tool
    return {
        "runtime_raw": runtime_raw,
        "capture_sha256": {name: _sha256(raw) for name, raw in capture_raw.items()},
        "identities": identities,
        "manifest_sha256": manifest_sha256,
    }

def _safe_token(value):
    return type(value) is str and bool(value) and all(character not in value for character in ("\0", "\n", "\r"))

def _git_tail_allowed(arguments):
    if type(arguments) is not list or not all(_safe_token(value) for value in arguments):
        return False
    if len(arguments) == 2 and arguments[0] in ("show", "rev-parse"):
        return not arguments[1].startswith("-")
    if len(arguments) == 3 and arguments[:2] == ["cat-file", "-e"]:
        return not arguments[2].startswith("-")
    if len(arguments) == 4 and arguments[:2] == ["merge-base", "--is-ancestor"]:
        return not arguments[2].startswith("-") and not arguments[3].startswith("-")
    return False

def _fd_path(value):
    if type(value) is not str or not value.startswith("/dev/fd/"):
        return None
    raw = value[8:]
    if not raw.isascii() or not raw.isdigit() or raw != str(int(raw)):
        return None
    number = int(raw)
    return number if number >= 3 else None

def _process_allowed(executable, arguments, environment, cwd):
    if executable == "/usr/bin/git":
        prefix = [
            "/usr/bin/git",
            "-c",
            "safe.directory=" + REPOSITORY_ROOT,
            "--no-replace-objects",
        ]
        return (
            type(arguments) is list
            and arguments[:len(prefix)] == prefix
            and _git_tail_allowed(arguments[len(prefix):])
            and environment == GIT_ENV
            and str(cwd) == REPOSITORY_ROOT
        )
    if executable == "/usr/bin/openssl":
        if arguments in (
            ["/usr/bin/openssl", "pkey", "-pubin", "-pubout"],
            ["/usr/bin/openssl", "pkey", "-pubin", "-inform", "PEM", "-outform", "DER"],
        ):
            return environment == CHILD_ENV and str(cwd) == RUNTIME_DIRECTORY
        if (
            type(arguments) is not list
            or len(arguments) != 8
            or arguments[:4] != ["/usr/bin/openssl", "dgst", "-sha256", "-verify"]
            or arguments[5] != "-signature"
        ):
            return False
        numbers = (_fd_path(arguments[4]), _fd_path(arguments[6]), _fd_path(arguments[7]))
        return (
            None not in numbers
            and len(set(numbers)) == 3
            and environment == CHILD_ENV
            and str(cwd) == RUNTIME_DIRECTORY
        )
    return False

def _audit_event_allowed(event, arguments):
    if type(event) is not str or type(arguments) is not tuple:
        return False
    if event.startswith("socket."):
        return False
    if event in ("os.fork", "os.system"):
        return False
    if event in {
        "os.remove",
        "os.unlink",
        "os.rename",
        "os.renames",
        "os.replace",
        "os.mkdir",
        "os.makedirs",
        "os.rmdir",
        "os.removedirs",
        "os.chmod",
        "os.fchmod",
        "os.chown",
        "os.fchown",
        "os.lchown",
        "os.truncate",
        "os.ftruncate",
        "os.link",
        "os.symlink",
        "os.utime",
        "os.setxattr",
        "os.removexattr",
    }:
        return False
    if event == "open" and len(arguments) >= 3 and type(arguments[2]) is int:
        flags = arguments[2]
        return not (flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
    if event == "subprocess.Popen":
        if len(arguments) != 4:
            return False
        executable, process_arguments, cwd, environment = arguments
        return _process_allowed(executable, process_arguments, environment, cwd)
    if event in ("os.exec", "os.posix_spawn"):
        return False
    return True

def _install_dynamic_guards(*, add_hook=sys.addaudithook):
    def guard(event, arguments):
        if not _audit_event_allowed(event, arguments):
            raise MaterializeError("materialize_dynamic_guard")
    add_hook(guard)
    return guard

def _early_core0_clean_env_preflight(
    *,
    get_limit=resource.getrlimit,
    set_limit=resource.setrlimit,
    environ=os.environ,
    get_euid=os.geteuid,
    getcwd=os.getcwd,
    executable=sys.executable,
    flags=sys.flags,
    realpath=os.path.realpath,
    opener=os.open,
    fstater=os.fstat,
    lstater=os.lstat,
):
    if (
        get_euid() != 0
        or getcwd() != RUNTIME_DIRECTORY
        or executable != "/Library/Developer/CommandLineTools/usr/bin/python3"
        or realpath(executable) != "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9"
        or flags.isolated != 1
        or flags.ignore_environment != 1
        or flags.no_user_site != 1
        or flags.no_site != 1
        or flags.dont_write_bytecode != 1
        or dict(environ) != CHILD_ENV
    ):
        raise MaterializeError("materialize_early_identity")
    set_limit(resource.RLIMIT_CORE, (0, 0))
    if get_limit(resource.RLIMIT_CORE) != (0, 0):
        raise MaterializeError("materialize_core_limit")
    descriptor = opener("/dev/null", os.O_RDWR | os.O_NOFOLLOW)
    try:
        opened = fstater(descriptor)
        named = lstater("/dev/null")
        flags_value = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        stable = lambda row: (
            row.st_dev,
            row.st_ino,
            row.st_rdev,
            row.st_mode,
            row.st_uid,
            row.st_gid,
            row.st_nlink,
        )
        if (
            not stat.S_ISCHR(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o666
            or opened.st_uid != 0
            or opened.st_gid != 0
            or opened.st_nlink != 1
            or stable(opened) != stable(named)
            or flags_value & os.O_ACCMODE != os.O_RDWR
            or flags_value & (os.O_NONBLOCK | getattr(os, "O_ASYNC", 0))
        ):
            raise MaterializeError("materialize_null_fd")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise

def _default_repository_probe(root):
    if root != pathlib.Path(REPOSITORY_ROOT):
        raise MaterializeError("materialize_repository_identity")
    git_directory = root / ".git"
    if not git_directory.is_dir() or git_directory.is_symlink():
        raise MaterializeError("materialize_repository_identity")
    config_raw = _read_file_bounded(str(git_directory / "config"), 1024 * 1024)
    try:
        config_text = config_raw.decode("utf-8").lower()
    except UnicodeDecodeError:
        raise MaterializeError("materialize_repository_identity")
    if any(token in config_text for token in ("promisor", "partialclone", "partialclonefilter")):
        raise MaterializeError("materialize_repository_nonlocal")
    pack_directory = git_directory / "objects" / "pack"
    pack_names = tuple(sorted(os.listdir(pack_directory)))
    if (
        any(name.endswith(".promisor") for name in pack_names)
        or os.path.lexists(git_directory / "objects" / "info" / "alternates")
        or os.path.lexists(git_directory / "shallow")
    ):
        raise MaterializeError("materialize_repository_nonlocal")
    rows = []
    for path in (root, git_directory, git_directory / "config", pack_directory):
        row = path.lstat()
        rows.append((str(path), row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid, row.st_nlink, row.st_size))
    return (tuple(rows), _sha256(config_raw), pack_names)

def _drain_git_stdout(process, maximum, *, selector_factory=selectors.DefaultSelector, monotonic=time.monotonic):
    if type(maximum) is not int or not 0 <= maximum <= 2 * 1024 * 1024:
        raise MaterializeError("materialize_git_output_limit")
    stream = getattr(process, "stdout", None)
    if stream is None:
        raise MaterializeError("materialize_git_stdout")
    descriptor = stream.fileno()
    os.set_blocking(descriptor, False)
    selector = selector_factory()
    raw = bytearray()
    deadline = monotonic() + 15.0
    try:
        selector.register(descriptor, selectors.EVENT_READ)
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise MaterializeError("materialize_git_timeout")
            events = selector.select(remaining)
            if not events:
                raise MaterializeError("materialize_git_timeout")
            for _key, mask in events:
                if not mask & selectors.EVENT_READ:
                    continue
                try:
                    chunk = os.read(descriptor, min(65536, maximum + 1 - len(raw)))
                except BlockingIOError:
                    continue
                if not chunk:
                    return bytes(raw)
                raw.extend(chunk)
                if len(raw) > maximum:
                    raise MaterializeError("materialize_git_output_limit")
    finally:
        selector.close()
        try:
            stream.close()
        except Exception:
            pass

def _local_only_git(
    arguments,
    *,
    root,
    stdout=subprocess.PIPE,
    null_fd,
    maximum_stdout=None,
    popen=subprocess.Popen,
    tool_probe=_default_tool_probe,
    repository_probe=_default_repository_probe,
):
    if (
        type(arguments) is not list
        or not _git_tail_allowed(arguments)
        or root != pathlib.Path(REPOSITORY_ROOT)
        or type(null_fd) is not int
        or null_fd < 3
        or stdout not in (subprocess.PIPE, subprocess.DEVNULL)
    ):
        raise MaterializeError("materialize_git_arguments")
    git_before = tool_probe("/usr/bin/git", SYSTEM_TOOL_BINDINGS["/usr/bin/git"])
    resolved_before = tool_probe(
        "/Library/Developer/CommandLineTools/usr/bin/git",
        SYSTEM_TOOL_BINDINGS["/Library/Developer/CommandLineTools/usr/bin/git"],
    )
    if not git_before or not resolved_before:
        raise MaterializeError("materialize_git_identity")
    repository_before = repository_probe(root)
    command = [
        "/usr/bin/git",
        "-c",
        "safe.directory=" + REPOSITORY_ROOT,
        "--no-replace-objects",
        *arguments,
    ]
    if maximum_stdout is None:
        maximum_stdout = 2 * 1024 * 1024 if arguments[0] == "show" else (128 if arguments[0] == "rev-parse" else 1)
    if type(maximum_stdout) is not int or not 0 <= maximum_stdout <= 2 * 1024 * 1024:
        raise MaterializeError("materialize_git_output_limit")
    process = None
    result = None
    failure = None
    try:
        process = _spawn_materialize_process(
            popen,
            command,
            cwd=REPOSITORY_ROOT,
            env=dict(GIT_ENV),
            stdin=null_fd,
            stdout=subprocess.PIPE,
            stderr=null_fd,
            close_fds=True,
            pass_fds=(),
            start_new_session=True,
        )
        raw = _drain_git_stdout(process, maximum_stdout)
        returncode = _settle_materialize_process(process)
        result = subprocess.CompletedProcess(
            command,
            returncode,
            None if stdout == subprocess.DEVNULL else raw,
            None,
        )
    except BaseException as exc:
        failure = exc
        if process is not None:
            try:
                _settle_materialize_process(process, force_kill=True)
            except BaseException as containment_exc:
                failure = containment_exc
    git_after = tool_probe("/usr/bin/git", SYSTEM_TOOL_BINDINGS["/usr/bin/git"])
    resolved_after = tool_probe(
        "/Library/Developer/CommandLineTools/usr/bin/git",
        SYSTEM_TOOL_BINDINGS["/Library/Developer/CommandLineTools/usr/bin/git"],
    )
    if (
        git_after != git_before
        or resolved_after != resolved_before
        or repository_probe(root) != repository_before
    ):
        raise MaterializeError("materialize_git_identity")
    if failure is not None:
        if isinstance(failure, MaterializeSignal):
            raise failure
        if isinstance(failure, MaterializeError):
            raise failure
        raise MaterializeError("materialize_git_process") from failure
    return result

def _git_blob_oid(raw):
    header = b"blob " + str(len(raw)).encode("ascii") + b"\0"
    return hashlib.sha1(header + raw).hexdigest()

def _extract_literal_binding(raw, name):
    try:
        source = raw.decode("utf-8")
        tree = ast.parse(source)
    except (UnicodeDecodeError, SyntaxError, ValueError):
        raise MaterializeError("materialize_embedded_literal")
    matches = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError):
                raise MaterializeError("materialize_embedded_literal")
            matches.append(value)
    if len(matches) != 1 or type(matches[0]) is not str:
        raise MaterializeError("materialize_embedded_literal")
    try:
        literal_raw = matches[0].encode("ascii")
    except UnicodeEncodeError:
        raise MaterializeError("materialize_embedded_literal")
    return len(literal_raw), _sha256(literal_raw)

def _local_object_probe(revision, source_ref, expected_oid, expected_size, expected_sha256, *, null_fd):
    if (
        not _hex(revision, 40)
        or type(source_ref) is not str
        or not source_ref.startswith("tools/")
        or not _hex(expected_oid, 40)
        or type(expected_size) is not int
        or expected_size < 1
        or not _hex(expected_sha256, 64)
    ):
        raise MaterializeError("materialize_local_object")
    root = pathlib.Path(REPOSITORY_ROOT)
    repository_before = _default_repository_probe(root)
    if revision != CONTROL_REVISION:
        lineage = _local_only_git(
            ["merge-base", "--is-ancestor", PARENT_ACCEPTANCE_REVISION, revision],
            root=root,
            stdout=subprocess.DEVNULL,
            null_fd=null_fd,
        )
        if lineage.returncode != 0:
            raise MaterializeError("materialize_source_lineage")
    exists = _local_only_git(
        ["cat-file", "-e", revision + ":" + source_ref],
        root=root,
        stdout=subprocess.DEVNULL,
        null_fd=null_fd,
    )
    oid_result = _local_only_git(
        ["rev-parse", revision + ":" + source_ref],
        root=root,
        null_fd=null_fd,
    )
    raw_result = _local_only_git(
        ["show", revision + ":" + source_ref],
        root=root,
        null_fd=null_fd,
        maximum_stdout=expected_size,
    )
    try:
        observed_oid = oid_result.stdout.decode("ascii").strip()
    except (AttributeError, UnicodeDecodeError):
        raise MaterializeError("materialize_local_object")
    raw = raw_result.stdout
    if (
        exists.returncode != 0
        or oid_result.returncode != 0
        or raw_result.returncode != 0
        or type(raw) is not bytes
        or observed_oid != expected_oid
        or len(raw) != expected_size
        or _sha256(raw) != expected_sha256
        or _git_blob_oid(raw) != expected_oid
        or _default_repository_probe(root) != repository_before
    ):
        raise MaterializeError("materialize_local_object")
    result = {
        "present": True,
        "git_blob_oid": observed_oid,
        "byte_count": len(raw),
        "sha256": _sha256(raw),
        "promisor_remote_count": 0,
        "partial_clone_config_count": 0,
    }
    if source_ref == STAGER_REF:
        literal_size, literal_sha256 = _extract_literal_binding(raw, "MATERIALIZE_ROOT_PROGRAM")
        result.update(
            {
                "embedded_literal_name": "MATERIALIZE_ROOT_PROGRAM",
                "embedded_literal_byte_count": literal_size,
                "embedded_literal_sha256": literal_sha256,
            }
        )
    return result

def _pump_pipe_inputs(process, writers, status_reader, payloads, *, maximum_status=MAX_STATUS_BYTES, timeout=15.0, selector_factory=selectors.DefaultSelector, monotonic=time.monotonic):
    selector = selector_factory()
    pending = {}
    status = bytearray()
    deadline = monotonic() + timeout
    try:
        for descriptor, raw in zip(writers, payloads):
            os.set_blocking(descriptor, False)
            pending[descriptor] = memoryview(raw)
            selector.register(descriptor, selectors.EVENT_WRITE, ("input", descriptor))
        os.set_blocking(status_reader, False)
        selector.register(status_reader, selectors.EVENT_READ, ("status", status_reader))
        while pending or status_reader is not None:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise MaterializeError("materialize_signature_timeout")
            events = selector.select(remaining)
            if not events:
                raise MaterializeError("materialize_signature_timeout")
            for key, mask in events:
                kind, descriptor = key.data
                if kind == "input" and mask & selectors.EVENT_WRITE:
                    view = pending[descriptor]
                    try:
                        count = os.write(descriptor, view[:65536])
                    except BlockingIOError:
                        continue
                    if count < 1:
                        raise MaterializeError("materialize_signature_pipe")
                    view = view[count:]
                    if view:
                        pending[descriptor] = view
                    else:
                        selector.unregister(descriptor)
                        os.close(descriptor)
                        pending.pop(descriptor)
                elif kind == "status" and mask & selectors.EVENT_READ:
                    try:
                        chunk = os.read(descriptor, 4096)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(descriptor)
                        os.close(descriptor)
                        status_reader = None
                    else:
                        status.extend(chunk)
                        if len(status) > maximum_status:
                            raise MaterializeError("materialize_signature_status")
        return bytes(status)
    finally:
        selector.close()
        for descriptor in list(pending):
            try:
                os.close(descriptor)
            except OSError:
                pass
        if status_reader is not None:
            try:
                os.close(status_reader)
            except OSError:
                pass

def _preflight_pipe_pairs(pairs, *, fstater=os.fstat, get_flags=fcntl.fcntl, is_tty=os.isatty):
    if type(pairs) is not list or not pairs:
        raise MaterializeError("materialize_pipe_identity")
    descriptors = []
    pair_identities = []
    for pair in pairs:
        if type(pair) is not tuple or len(pair) != 2:
            raise MaterializeError("materialize_pipe_identity")
        reader, writer = pair
        if (
            type(reader) is not int
            or type(writer) is not int
            or reader < 3
            or writer < 3
            or reader == writer
        ):
            raise MaterializeError("materialize_pipe_identity")
        reader_row = fstater(reader)
        writer_row = fstater(writer)
        reader_flags = get_flags(reader, fcntl.F_GETFL)
        writer_flags = get_flags(writer, fcntl.F_GETFL)
        if (
            not stat.S_ISFIFO(reader_row.st_mode)
            or not stat.S_ISFIFO(writer_row.st_mode)
            or is_tty(reader)
            or is_tty(writer)
            or reader_flags & os.O_ACCMODE != os.O_RDONLY
            or writer_flags & os.O_ACCMODE != os.O_WRONLY
            or reader_flags & (os.O_NONBLOCK | getattr(os, "O_ASYNC", 0))
            or writer_flags & (os.O_NONBLOCK | getattr(os, "O_ASYNC", 0))
        ):
            raise MaterializeError("materialize_pipe_identity")
        reader_identity = (reader_row.st_dev, reader_row.st_ino, os.O_RDONLY)
        writer_identity = (writer_row.st_dev, writer_row.st_ino, os.O_WRONLY)
        descriptors.extend((reader, writer))
        pair_identities.extend((reader_identity, writer_identity))
    if len(descriptors) != len(set(descriptors)) or len(pair_identities) != len(set(pair_identities)):
        raise MaterializeError("materialize_pipe_alias")
    return tuple(pair_identities)

def _group_absent(process_group, *, kill_group=os.killpg):
    try:
        kill_group(process_group, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False

def _prove_group_absent(process_group, *, probe=_group_absent, monotonic=time.monotonic, sleeper=time.sleep, timeout=0.25):
    deadline = monotonic() + timeout
    while True:
        if probe(process_group) is True:
            return True
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        sleeper(min(0.01, remaining))

def _settle_process(process, *, force_kill=False, kill_group=os.killpg, prove_group_absent=_prove_group_absent):
    returncode = process.poll()
    if not force_kill and returncode is None:
        try:
            returncode = process.wait(timeout=2)
        except Exception:
            force_kill = True
    if not force_kill and prove_group_absent(process.pid) is not True:
        force_kill = True
    if force_kill:
        try:
            kill_group(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            raise MaterializeError("materialize_process_group") from exc
        if process.poll() is None:
            try:
                returncode = process.wait(timeout=2)
            except Exception as exc:
                raise MaterializeError("materialize_process_reap") from exc
        else:
            returncode = process.returncode
        if prove_group_absent(process.pid) is not True:
            raise MaterializeError("materialize_process_group")
    return returncode

def _spawn_materialize_process(popen, arguments, **options):
    global ACTIVE_MATERIALIZE_PROCESS
    previous_mask = signal.pthread_sigmask(
        signal.SIG_BLOCK,
        MATERIALIZE_TERMINATION_SIGNALS,
    )
    process = None
    try:
        if ACTIVE_MATERIALIZE_PROCESS is not None:
            raise MaterializeError("materialize_active_process")
        process = popen(arguments, **options)
        ACTIVE_MATERIALIZE_PROCESS = process
    except BaseException:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        raise
    try:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    except BaseException:
        containment_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK,
            MATERIALIZE_TERMINATION_SIGNALS,
        )
        try:
            _settle_process(process, force_kill=True)
            if ACTIVE_MATERIALIZE_PROCESS is process:
                ACTIVE_MATERIALIZE_PROCESS = None
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, containment_mask)
        raise
    return process

def _settle_materialize_process(process, *, force_kill=False):
    global ACTIVE_MATERIALIZE_PROCESS
    previous_mask = signal.pthread_sigmask(
        signal.SIG_BLOCK,
        MATERIALIZE_TERMINATION_SIGNALS,
    )
    try:
        result = _settle_process(process, force_kill=force_kill)
        if ACTIVE_MATERIALIZE_PROCESS is process:
            ACTIVE_MATERIALIZE_PROCESS = None
        return result
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

def _invoke_fd_signature(payload, signature, key, *, null_fd, popen=subprocess.Popen, tool_probe=_default_tool_probe):
    openssl_before = tool_probe(
        "/usr/bin/openssl",
        SYSTEM_TOOL_BINDINGS["/usr/bin/openssl"],
    )
    if (
        type(payload) is not bytes
        or type(signature) is not bytes
        or type(key) is not bytes
        or not payload
        or not signature
        or not key
        or len(payload) > MAX_SIGNATURE_MESSAGE_BYTES
        or len(signature) > MAX_SIGNATURE_BYTES
        or len(key) > MAX_PUBLIC_KEY_BYTES
        or type(null_fd) is not int
        or null_fd < 3
        or not openssl_before
    ):
        return False
    readers = []
    writers = []
    status_reader = None
    status_writer = None
    process = None
    try:
        for _unused in range(3):
            reader, writer = os.pipe()
            readers.append(reader)
            writers.append(writer)
        status_reader, status_writer = os.pipe()
        _preflight_pipe_pairs(
            [
                *(tuple(pair) for pair in zip(readers, writers)),
                (status_reader, status_writer),
            ]
        )
        arguments = [
            "/usr/bin/openssl",
            "dgst",
            "-sha256",
            "-verify",
            "/dev/fd/" + str(readers[2]),
            "-signature",
            "/dev/fd/" + str(readers[1]),
            "/dev/fd/" + str(readers[0]),
        ]
        process = _spawn_materialize_process(
            popen,
            arguments,
            cwd=RUNTIME_DIRECTORY,
            env=dict(CHILD_ENV),
            stdin=null_fd,
            stdout=status_writer,
            stderr=null_fd,
            close_fds=True,
            pass_fds=tuple(readers),
            start_new_session=True,
        )
        for descriptor in readers:
            os.close(descriptor)
        readers.clear()
        os.close(status_writer)
        status_writer = None
        status = _pump_pipe_inputs(process, writers, status_reader, (payload, signature, key))
        writers.clear()
        status_reader = None
        return (
            _settle_materialize_process(process) == 0
            and status == b"Verified OK\n"
            and tool_probe("/usr/bin/openssl", SYSTEM_TOOL_BINDINGS["/usr/bin/openssl"]) == openssl_before
        )
    except BaseException as exc:
        if process is not None:
            try:
                _settle_materialize_process(process, force_kill=True)
            except BaseException:
                pass
        if isinstance(exc, MaterializeSignal):
            raise
        return False
    finally:
        for descriptor in readers + writers:
            try:
                os.close(descriptor)
            except OSError:
                pass
        for descriptor in (status_reader, status_writer):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

def _fd_only_verify_signature(payload, signature, key, *, null_fd=None, invoke=_invoke_fd_signature):
    try:
        if null_fd is None:
            return invoke(payload, signature, key) is True
        return invoke(payload, signature, key, null_fd=null_fd) is True
    except Exception:
        return False

def _fd_only_openssl(arguments, *, stdin, timeout=15, null_fd, popen=subprocess.Popen, tool_probe=_default_tool_probe):
    allowed = (
        ["pkey", "-pubin", "-pubout"],
        ["pkey", "-pubin", "-inform", "PEM", "-outform", "DER"],
    )
    openssl_before = tool_probe(
        "/usr/bin/openssl",
        SYSTEM_TOOL_BINDINGS["/usr/bin/openssl"],
    )
    if (
        arguments not in allowed
        or type(stdin) is not bytes
        or not stdin
        or len(stdin) > MAX_PUBLIC_KEY_BYTES
        or timeout != 15
        or type(null_fd) is not int
        or null_fd < 3
        or not openssl_before
    ):
        raise MaterializeError("materialize_public_key_process")
    input_reader = input_writer = output_reader = output_writer = None
    process = None
    try:
        input_reader, input_writer = os.pipe()
        output_reader, output_writer = os.pipe()
        _preflight_pipe_pairs(
            [
                (input_reader, input_writer),
                (output_reader, output_writer),
            ]
        )
        process = _spawn_materialize_process(
            popen,
            ["/usr/bin/openssl", *arguments],
            cwd=RUNTIME_DIRECTORY,
            env=dict(CHILD_ENV),
            stdin=input_reader,
            stdout=output_writer,
            stderr=null_fd,
            close_fds=True,
            pass_fds=(input_reader,),
            start_new_session=True,
        )
        os.close(input_reader)
        input_reader = None
        os.close(output_writer)
        output_writer = None
        output = _pump_pipe_inputs(
            process,
            [input_writer],
            output_reader,
            [stdin],
            maximum_status=MAX_PUBLIC_KEY_BYTES,
            timeout=15.0,
        )
        input_writer = None
        output_reader = None
        if (
            _settle_materialize_process(process) != 0
            or not output
            or tool_probe("/usr/bin/openssl", SYSTEM_TOOL_BINDINGS["/usr/bin/openssl"]) != openssl_before
        ):
            raise MaterializeError("materialize_public_key_process")
        return output
    except BaseException as exc:
        if process is not None:
            try:
                _settle_materialize_process(process, force_kill=True)
            except BaseException:
                pass
        if isinstance(exc, MaterializeSignal):
            raise
        if isinstance(exc, MaterializeError):
            raise
        raise MaterializeError("materialize_public_key_process") from exc
    finally:
        for descriptor in (input_reader, input_writer, output_reader, output_writer):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

def _install_authority_patches(
    authority,
    *,
    null_fd,
    signature_verifier=_fd_only_verify_signature,
    git_runner=_local_only_git,
    openssl_runner=_fd_only_openssl,
):
    if (
        getattr(authority, "_verify_signature", None) is None
        or getattr(authority, "_git", None) is None
        or getattr(authority, "_openssl", None) is None
        or getattr(authority, "_git_repository_identity", None) is None
        or not callable(signature_verifier)
        or not callable(git_runner)
        or not callable(openssl_runner)
        or type(null_fd) is not int
        or null_fd < 3
    ):
        raise MaterializeError("materialize_authority_patch")
    repository_probe = authority._git_repository_identity
    def bound_signature(payload, signature, key):
        return signature_verifier(payload, signature, key, null_fd=null_fd)
    def bound_git(arguments, *, root, stdout=subprocess.PIPE):
        return git_runner(
            arguments,
            root=root,
            stdout=stdout,
            null_fd=null_fd,
            repository_probe=repository_probe,
        )
    def bound_openssl(arguments, *, stdin, timeout=15):
        return openssl_runner(
            arguments,
            stdin=stdin,
            timeout=timeout,
            null_fd=null_fd,
        )
    authority._verify_signature = bound_signature
    authority._git = bound_git
    authority._openssl = bound_openssl
    if not all(callable(getattr(authority, name, None)) for name in ("_verify_signature", "_git", "_openssl")):
        raise MaterializeError("materialize_authority_patch")

def _load_module(name, path, raw):
    if type(name) is not str or type(path) is not str or type(raw) is not bytes or not raw:
        raise MaterializeError("materialize_module")
    module = type(sys)(name)
    module.__file__ = path
    sys.modules[name] = module
    try:
        exec(compile(raw, path, "exec", dont_inherit=True, optimize=0), module.__dict__)
    except Exception:
        sys.modules.pop(name, None)
        raise MaterializeError("materialize_module")
    return module

def _prepare_materialize_dependencies(runtime_validator, *, null_fd, guard_installer=_install_dynamic_guards, loader=_load_module, patcher=_install_authority_patches):
    validated = runtime_validator()
    if type(validated) is not dict or type(validated.get("runtime_raw")) is not dict:
        raise MaterializeError("materialize_runtime_validation")
    guard_installer()
    raw = validated["runtime_raw"]
    loaded = []
    try:
        extractor = loader("extract_item26_manual_cost_stop_raw_v2", RUNTIME_DIRECTORY + "/extract_item26_manual_cost_stop_raw_v2.py", raw["extract_item26_manual_cost_stop_raw_v2.py"])
        loaded.append("extract_item26_manual_cost_stop_raw_v2")
        authority = loader("verify_item26_manual_cost_stop_authority_v2", RUNTIME_DIRECTORY + "/verify_item26_manual_cost_stop_authority_v2.py", raw["verify_item26_manual_cost_stop_authority_v2.py"])
        loaded.append("verify_item26_manual_cost_stop_authority_v2")
        patcher(authority, null_fd=null_fd)
        verifier = loader("verify_item26_manual_cost_stop_evidence_v2", RUNTIME_DIRECTORY + "/verify_item26_manual_cost_stop_evidence_v2.py", raw["verify_item26_manual_cost_stop_evidence_v2.py"])
        loaded.append("verify_item26_manual_cost_stop_evidence_v2")
        builder = loader("build_item26_manual_cost_stop_evidence_v2", RUNTIME_DIRECTORY + "/build_item26_manual_cost_stop_evidence_v2.py", raw["build_item26_manual_cost_stop_evidence_v2.py"])
        loaded.append("build_item26_manual_cost_stop_evidence_v2")
    except Exception:
        for name in reversed(loaded):
            sys.modules.pop(name, None)
        raise MaterializeError("materialize_dependency_load")
    return validated, extractor, authority, verifier, builder

def _verify_finalized_capture(authority):
    if tuple(getattr(authority, "CAPTURE_INVENTORY", ())) != CAPTURE_ORDER:
        raise MaterializeError("materialize_capture_inventory")
    loader = getattr(authority, "load_verified_projection", None)
    if not callable(loader):
        raise MaterializeError("materialize_capture_loader")
    projection, binding = loader(
        expected_control_revision=CONTROL_REVISION,
        expected_authority_root_file_sha256=AUTHORITY_ROOT_BINDING[1],
        root=pathlib.Path(REPOSITORY_ROOT),
        authority_directory=pathlib.Path(AUTHORITY_DIRECTORY),
        runtime_directory=pathlib.Path(EXISTING_RUNTIME_DIRECTORY),
    )
    if (
        projection is None
        or type(binding) is not dict
        or binding.get("control_revision") != CONTROL_REVISION
        or binding.get("authority_root_file_sha256") != AUTHORITY_ROOT_BINDING[1]
        or binding.get("authorizes_new_action") is not False
    ):
        raise MaterializeError("materialize_finalized_capture")
    return projection, binding

def _build_validate_artifacts(builder, verifier):
    build_receipt = getattr(builder, "build_receipt", None)
    build_evidence = getattr(builder, "build_evidence", None)
    validate_receipt = getattr(verifier, "validate_receipt", None)
    validate_evidence = getattr(verifier, "validate_evidence", None)
    if not all(callable(value) for value in (build_receipt, build_evidence, validate_receipt, validate_evidence)):
        raise MaterializeError("materialize_entrypoints")
    context = {
        "expected_control_revision": CONTROL_REVISION,
        "root": pathlib.Path(REPOSITORY_ROOT),
        "authority_directory": pathlib.Path(AUTHORITY_DIRECTORY),
    }
    receipt = build_receipt(**context)
    evidence = build_evidence(receipt, **context)
    receipt_errors, acceptance = validate_receipt(receipt, expected_control_revision=CONTROL_REVISION)
    if receipt_errors or type(acceptance) is not str or not acceptance:
        raise MaterializeError("materialize_receipt_validation")
    receipt_raw = canonical(receipt)
    evidence_errors = validate_evidence(evidence, receipt, receipt_raw, expected_control_revision=CONTROL_REVISION)
    if evidence_errors:
        raise MaterializeError("materialize_evidence_validation")
    if (
        type(receipt) is not dict
        or type(evidence) is not dict
        or receipt.get("schema") != RECEIPT_SCHEMA
        or evidence.get("schema") != EVIDENCE_SCHEMA
        or len(receipt_raw) > MAX_RECEIPT_BYTES
    ):
        raise MaterializeError("materialize_artifact_shape")
    evidence_raw = canonical(evidence)
    if len(evidence_raw) > MAX_EVIDENCE_BYTES:
        raise MaterializeError("materialize_artifact_size")
    return receipt, evidence, receipt_raw, evidence_raw

def _socket_identity(descriptor, role, seen, *, keep_wrapper=False, fstater=os.fstat, get_flags=fcntl.fcntl, socket_factory=socket.socket, is_tty=os.isatty):
    if type(descriptor) is not int or descriptor < 3 or type(role) is not str or not role:
        raise MaterializeError("materialize_output_fd")
    if descriptor in seen:
        raise MaterializeError("materialize_output_alias")
    row = fstater(descriptor)
    flags = get_flags(descriptor, fcntl.F_GETFL)
    if (
        not stat.S_ISSOCK(row.st_mode)
        or is_tty(descriptor)
        or flags & (os.O_NONBLOCK | getattr(os, "O_ASYNC", 0))
        or flags & os.O_ACCMODE != os.O_RDWR
    ):
        raise MaterializeError("materialize_output_fd")
    identity = (row.st_dev, row.st_ino)
    if identity in seen.values():
        raise MaterializeError("materialize_output_alias")
    duplicate = os.dup(descriptor)
    wrapper = socket_factory(fileno=duplicate)
    try:
        if (
            wrapper.family != socket.AF_UNIX
            or wrapper.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
            or wrapper.getsockname() not in ("", b"")
            or wrapper.getpeername() not in ("", b"")
        ):
            raise MaterializeError("materialize_output_fd")
        wrapper.send(b"")
    except Exception:
        wrapper.close()
        raise
    seen[descriptor] = identity
    if keep_wrapper:
        return identity, wrapper
    wrapper.close()
    return identity

def _preflight_output_fds(receipt_fd, evidence_fd, status_fd):
    seen = {}
    channels = {}
    try:
        for role, descriptor in (
            ("receipt", receipt_fd),
            ("evidence", evidence_fd),
            ("status", status_fd),
        ):
            channels[role] = _socket_identity(
                descriptor,
                role,
                seen,
                keep_wrapper=True,
            )
        return channels
    except Exception:
        for value in channels.values():
            try:
                value[1].close()
            except Exception:
                pass
        raise

def _write_all(descriptor, raw):
    view = memoryview(raw)
    while view:
        count = os.write(descriptor, view)
        if count < 1:
            raise MaterializeError("materialize_output_write")
        view = view[count:]

def _emit_one_once(role, descriptor, raw, state, *, writer=_write_all, shutdown_wrapper=None):
    if state.get(role) != 0:
        raise MaterializeError("materialize_output_repeat")
    state[role] = 1
    writer(descriptor, raw)
    if shutdown_wrapper is None:
        raise MaterializeError("materialize_output_channel")
    shutdown_wrapper.shutdown(socket.SHUT_WR)

SUCCESS_STATUS = {
    "schema": OUTPUT_STATUS_SCHEMA,
    "status": "RECEIPT_AND_EVIDENCE_BUILT_AND_VERIFIED",
    "receipt_build_count": 1,
    "evidence_build_count": 1,
    "checkpoint_build_count": 0,
    "receipt_validation_count": 3,
    "evidence_validation_count": 2,
    "network_dispatch_count": 0,
    "provider_dispatch_count": 0,
    "database_connection_count": 0,
    "database_transaction_count": 0,
    "database_write_count": 0,
    "private_key_read_count": 0,
    "private_key_write_count": 0,
    "private_key_output_count": 0,
    "credential_configuration_count": 0,
    "credential_refresh_count": 0,
    "raw_value_emitted_count": 0,
    "automatic_retry_count": 0,
    "cleanup_count": 0,
}
FAILURE_STATUS = {
    "schema": OUTPUT_STATUS_SCHEMA,
    "status": "BLOCKED_FIXED_FAILURE",
    "automatic_retry_count": 0,
    "cleanup_count": 0,
    "raw_value_emitted_count": 0,
}

def _emit_outputs_once(receipt_fd, evidence_fd, status_fd, receipt_raw, evidence_raw, state, channels, *, emit=_emit_one_once):
    if (
        type(receipt_raw) is not bytes
        or type(evidence_raw) is not bytes
        or len(receipt_raw) > MAX_RECEIPT_BYTES
        or len(evidence_raw) > MAX_EVIDENCE_BYTES
    ):
        raise MaterializeError("materialize_output_size")
    try:
        receipt = json.loads(receipt_raw)
        evidence = json.loads(evidence_raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise MaterializeError("materialize_output_json")
    if (
        canonical(receipt) != receipt_raw
        or canonical(evidence) != evidence_raw
        or type(receipt) is not dict
        or type(evidence) is not dict
        or receipt.get("schema") != RECEIPT_SCHEMA
        or evidence.get("schema") != EVIDENCE_SCHEMA
    ):
        raise MaterializeError("materialize_output_schema")
    status_raw = canonical(SUCCESS_STATUS)
    if len(status_raw) > MAX_STATUS_BYTES:
        raise MaterializeError("materialize_output_status")
    if type(channels) is not dict or set(channels) != {"receipt", "evidence", "status"}:
        raise MaterializeError("materialize_output_channel")
    emit("receipt", receipt_fd, receipt_raw, state, shutdown_wrapper=channels["receipt"][1])
    emit("evidence", evidence_fd, evidence_raw, state, shutdown_wrapper=channels["evidence"][1])
    emit("status", status_fd, status_raw, state, shutdown_wrapper=channels["status"][1])

def _close_output_channels(state):
    channels = state.pop("_channels", None)
    if type(channels) is dict:
        for value in channels.values():
            if type(value) is tuple and len(value) == 2:
                try:
                    value[1].close()
                except Exception:
                    pass
    null_fd = state.pop("_null_fd", None)
    if type(null_fd) is int and null_fd >= 3:
        try:
            os.close(null_fd)
        except OSError:
            pass

def _materialize_once(receipt_fd, evidence_fd, status_fd, *, runtime_validator, dependency_preparer=_prepare_materialize_dependencies, capture_verifier=_verify_finalized_capture, artifact_builder=_build_validate_artifacts, output_emitter=_emit_outputs_once, early_preflight=_early_core0_clean_env_preflight, output_preflight=_preflight_output_fds, state=None):
    emission = {"receipt": 0, "evidence": 0, "status": 0} if state is None else state
    null_fd = early_preflight()
    if type(null_fd) is not int or null_fd < 3:
        raise MaterializeError("materialize_null_fd")
    emission["_null_fd"] = null_fd
    try:
        runtime_validator.null_fd = null_fd
    except Exception as exc:
        raise MaterializeError("materialize_runtime_validation") from exc
    channels = output_preflight(receipt_fd, evidence_fd, status_fd)
    emission["_channels"] = channels
    first, extractor, authority, verifier, builder = dependency_preparer(
        runtime_validator,
        null_fd=null_fd,
    )
    if extractor is None:
        raise MaterializeError("materialize_extractor")
    capture_verifier(authority)
    receipt, evidence, receipt_raw, evidence_raw = artifact_builder(builder, verifier)
    second = runtime_validator()
    if (
        first.get("identities") != second.get("identities")
        or first.get("capture_sha256") != second.get("capture_sha256")
        or first.get("manifest_sha256") != second.get("manifest_sha256")
    ):
        raise MaterializeError("materialize_post_identity")
    del receipt, evidence
    output_emitter(receipt_fd, evidence_fd, status_fd, receipt_raw, evidence_raw, emission, channels)
    return dict(SUCCESS_STATUS)

def _parse_fd(value):
    if type(value) is not str or not value.isascii() or not value.isdigit() or value != str(int(value)):
        raise MaterializeError("materialize_arguments")
    descriptor = int(value)
    if descriptor < 3:
        raise MaterializeError("materialize_arguments")
    return descriptor

def _parse_count(value):
    if type(value) is not str or not value.isascii() or not value.isdigit() or value != str(int(value)):
        raise MaterializeError("materialize_arguments")
    count = int(value)
    if count < 1 or count > 64 * 1024 * 1024:
        raise MaterializeError("materialize_arguments")
    return count

def _runtime_validator_from_arguments(arguments):
    if type(arguments) is not list or len(arguments) != 10:
        raise MaterializeError("materialize_arguments")
    (
        accepted_source_revision,
        stager_size_raw,
        stager_sha256,
        stager_blob_oid,
        program_size_raw,
        program_sha256,
        provider_size_raw,
        provider_sha256,
        actiontrail_size_raw,
        actiontrail_sha256,
    ) = arguments
    stager_size = _parse_count(stager_size_raw)
    program_size = _parse_count(program_size_raw)
    provider_size = _parse_count(provider_size_raw)
    actiontrail_size = _parse_count(actiontrail_size_raw)
    if (
        not _hex(accepted_source_revision, 40)
        or accepted_source_revision == PARENT_ACCEPTANCE_REVISION
        or not _hex(stager_sha256, 64)
        or not _hex(stager_blob_oid, 40)
        or not _hex(program_sha256, 64)
        or not _hex(provider_sha256, 64)
        or not _hex(actiontrail_sha256, 64)
    ):
        raise MaterializeError("materialize_arguments")
    manifest = canonical(_expected_manifest(program_size, program_sha256, accepted_source_revision))
    def validate():
        null_fd = getattr(validate, "null_fd", None)
        if type(null_fd) is not int or null_fd < 3:
            raise MaterializeError("materialize_object_probe_unbound")
        return _validate_runtime_capture_and_local_objects(
            program_size=program_size,
            program_sha256=program_sha256,
            accepted_source_revision=accepted_source_revision,
            stager_size=stager_size,
            stager_sha256=stager_sha256,
            stager_blob_oid=stager_blob_oid,
            manifest_size=len(manifest),
            manifest_sha256=_sha256(manifest),
            capture_bindings={
                "authority-root-v2.json": AUTHORITY_ROOT_BINDING,
                "provider-raw-v2.json": (provider_size, provider_sha256, 0o600),
                "actiontrail-raw-v2.json": (actiontrail_size, actiontrail_sha256, 0o600),
            },
            object_probe=lambda revision, source_ref, oid, size, digest: _local_object_probe(
                revision,
                source_ref,
                oid,
                size,
                digest,
                null_fd=null_fd,
            ),
        )
    validate.null_fd = None
    return validate

def _enabled_main(argv, *, runner):
    if type(argv) is not list or len(argv) != 14 or argv[0] != "--materialize":
        raise MaterializeError("materialize_arguments")
    descriptors = tuple(_parse_fd(value) for value in argv[1:4])
    if len(set(descriptors)) != 3:
        raise MaterializeError("materialize_arguments")
    runtime_validator = _runtime_validator_from_arguments(argv[4:])
    return runner(*descriptors, runtime_validator=runtime_validator)

def _public_enabled_main(
    argv,
    *,
    runner,
    failure_writer=_emit_one_once,
    state=None,
    signal_installer=_install_materialize_signal_handlers
):
    signal_installer()
    emission = {"receipt": 0, "evidence": 0, "status": 0} if state is None else state
    status_fd = None
    try:
        if type(argv) is list and len(argv) == 14:
            status_fd = _parse_fd(argv[3])
        _enabled_main(
            argv,
            runner=lambda receipt_fd, evidence_fd, parsed_status_fd, runtime_validator: runner(
                receipt_fd,
                evidence_fd,
                parsed_status_fd,
                runtime_validator=runtime_validator,
                state=emission,
            ),
        )
        return 0
    except BaseException:
        channels = emission.get("_channels")
        if status_fd is not None and emission.get("status") == 0 and type(channels) is dict and "status" in channels:
            try:
                failure_writer("status", status_fd, canonical(FAILURE_STATUS), emission, shutdown_wrapper=channels["status"][1])
            except Exception:
                pass
        return 78
    finally:
        _close_output_channels(emission)

def future_materialize(*args, **kwargs):
    if EXECUTION_ENABLED is not True:
        raise RuntimeError("future_execution_disabled")
    return _materialize_once(*args, **kwargs)

def main():
    if EXECUTION_ENABLED is True:
        return _public_enabled_main(sys.argv[1:], runner=_materialize_once)
    sys.stdout.buffer.write(canonical(STATUS))
    sys.stdout.buffer.flush()
    return 78

if __name__ == "__main__":
    raise SystemExit(main())
'''


STAGE_ROOT_PROGRAM = r'''
import ast
import fcntl
import hashlib
import json
import os
import pathlib
import resource
import selectors
import signal
import socket
import stat
import subprocess
import sys
import time

EXECUTION_ENABLED = False
SOURCE_ONLY_IMPLEMENTATION_STATUS = "SOURCE_ONLY_IMPLEMENTATION_COMPLETE_NOT_AUTHORIZED"
BASE_REVISION = "a30b879d06c388a4a0e230b5a23b2eaedc93649d"
CONTROL_REVISION = "68aa82ffbdd43e78e585d8956d13d3030ef6a640"
ADAPTER_SOURCE_REVISION = "65b82ffd890479315c9a93769cf11e2a9d27074b"
INSTALL_RESULT_REVISION = "9146d7a264418f59d76e4d8c7a46ac2abc80e9e8"
PRESERVATION_REVISION = "2cfb58b9f227a37cc86843bef7dc1014bc185391"
REPOSITORY_ROOT = "/Users/openclaw/Desktop/noteai"
REPOSITORY_OWNER_UID = 501
REPOSITORY_OWNER_GID = 20
REPOSITORY_METADATA_MAXIMUMS = {
    "HEAD": 4096,
    "index": 8 * 1024 * 1024,
    "config": 1024 * 1024,
}
NOTEAI_ROOT = "/Library/Application Support/NoteAI"
CAPTURE_DIRECTORY = NOTEAI_ROOT + "/item26-manual-cost-stop-v2-m1-capture"
MATERIALIZE_DIRECTORY = NOTEAI_ROOT + "/item26-manual-cost-stop-v2-m1-materialize"
AUTHORITY_DIRECTORY = NOTEAI_ROOT + "/item26-manual-cost-stop-v2"
RUNTIME_DIRECTORY = NOTEAI_ROOT + "/item26-manual-cost-stop-v2-tools"
JOURNAL_DIRECTORY = NOTEAI_ROOT + "/item26-manual-cost-stop-v2-journal"
CUSTODY_DIRECTORY = NOTEAI_ROOT + "/item26-manual-cost-stop-v2-custody"
STAGER_REF = "tools/stage_collect_and_materialize_item26_manual_cost_stop_m1_v2.py"
TEST_REF = "tests/test_stage_collect_and_materialize_item26_manual_cost_stop_m1_v2.py"
ADAPTER_REF = "tools/item26_aliyun_official_read_v2.py"
BUILDER_REF = "tools/build_item26_manual_cost_stop_evidence_v2.py"
EVIDENCE_VERIFIER_REF = "tools/verify_item26_manual_cost_stop_evidence_v2.py"
EXTRACTOR_REF = "tools/extract_item26_manual_cost_stop_raw_v2.py"
AUTHORITY_VERIFIER_REF = "tools/verify_item26_manual_cost_stop_authority_v2.py"
COLLECTOR_REF = "tools/collect_item26_manual_cost_stop_raw_v2.py"
AUTHORITY_ROOT_REF = "deploy/production/authorities/item26-manual-cost-stop-authority-root-v2.json"
INSTALL_RESULT_REF = ".codex/item26-manual-cost-stop-runtime-v3-install-result-35fede04256442f7853d38980de174526cf28220.json"
ACTIVATION_RECEIPT_REF = ".codex/item26-manual-cost-stop-activation-receipt-v3-68aa82ffbdd43e78e585d8956d13d3030ef6a640.json"
BUNDLE_SCHEMA = "noteai.item26.m1-root-staging-public-bundle.v1"
STATUS_SCHEMA = "noteai.item26.m1-root-staging-child-status.v1"
MANIFEST_SCHEMA = "noteai.item26.m1-root-runtime-manifest.v1"
AUTHORIZATION_ID = "CTO-AUTH-ITEM26-M1-CAPTURE-MATERIALIZER-STAGER-SOURCE-001"
MAX_BUNDLE_BYTES = 256 * 1024
MAX_GIT_BYTES = 512 * 1024
GIT_TIMEOUT_SECONDS = 15
PYTHON_EXECUTABLE = "/Library/Developer/CommandLineTools/usr/bin/python3"
PYTHON_RESOLVED_EXECUTABLE = "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9"
GIT_EXECUTABLE = "/Library/Developer/CommandLineTools/usr/bin/git"
ROOT_ENVIRONMENT = {
    "HOME": "/var/root",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/Library/Developer/CommandLineTools/usr/bin:/usr/bin:/bin",
    "TMPDIR": "/tmp",
}
GIT_ENVIRONMENT = {
    **ROOT_ENVIRONMENT,
    "GIT_CONFIG_COUNT": "4",
    "GIT_CONFIG_KEY_0": "core.fsmonitor",
    "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "core.hooksPath",
    "GIT_CONFIG_VALUE_1": "/dev/null",
    "GIT_CONFIG_KEY_2": "fetch.recurseSubmodules",
    "GIT_CONFIG_VALUE_2": "false",
    "GIT_CONFIG_KEY_3": "submodule.recurse",
    "GIT_CONFIG_VALUE_3": "false",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
}
_ACTIVE_GIT_PROCESS = None
_TERMINATION_SIGNALS = (
    signal.SIGTERM,
    signal.SIGINT,
    signal.SIGHUP,
    signal.SIGQUIT,
    signal.SIGALRM,
)
SOURCE_REFS = frozenset({
    STAGER_REF,
    TEST_REF,
    ".codex/handoffs/current-task.md",
    ".codex/notes/architecture-summary.md",
    ".codex/notes/risk-register.md",
    "deploy/production/internal-deployment-readiness.json",
})
ACCEPTANCE_REFS = frozenset(SOURCE_REFS - {STAGER_REF, TEST_REF})
CAPTURE_ORDER = (
    "capture-root-program.py",
    "item26_aliyun_official_read_v2.py",
    "capture-runtime-manifest.json",
)
MATERIALIZE_ORDER = (
    "materialize-root-program.py",
    "build_item26_manual_cost_stop_evidence_v2.py",
    "verify_item26_manual_cost_stop_evidence_v2.py",
    "verify_item26_manual_cost_stop_authority_v2.py",
    "extract_item26_manual_cost_stop_raw_v2.py",
    "materialize-runtime-manifest.json",
)
EXISTING_RUNTIME_NAMES = frozenset({
    "collect_item26_manual_cost_stop_raw_v2.py",
    "extract_item26_manual_cost_stop_raw_v2.py",
    "verify_item26_manual_cost_stop_authority_v2.py",
    "runtime-activation-receipt-v3.json",
})
CUSTODY_NAMES = frozenset({
    "provider-private-key.pem",
    "confirmation-private-key.pem",
    "local-ci-observation-private-key.pem",
})
FIXED_EXPECTED = {
    ADAPTER_REF: (BASE_REVISION, ADAPTER_SOURCE_REVISION, "f53a01805ea68005ca9e56a08dfa491221c224cf", 31410, "719886d2846a7602bf3fc0529f5c191305b58465c668d171461860d4c60aadb9"),
    COLLECTOR_REF: (CONTROL_REVISION, None, "e584b87cb7c2dcea46efe5ba01042e7e7e0d94e0", 85025, "739b8e8bea29250ccd4c24b400af791c67e687f0cecd23a4b1ddbc8b70750ea4"),
    EXTRACTOR_REF: (CONTROL_REVISION, None, "64b87e4630b894f57f64317e0b3cb70b8367e153", 62917, "7264bc6d1b3028c141a32d56a69e248fac283c835f776ed6f7c09b9f1c2d0fd4"),
    BUILDER_REF: (CONTROL_REVISION, None, "861f355a92505c9e3f000a74acb57598375dd16e", 16835, "ecf0a3d984b99b09e9f3d189f28fb8b60bd2355a28bf04565fd7c297fa765acb"),
    EVIDENCE_VERIFIER_REF: (CONTROL_REVISION, None, "95727f7e6b8bcb7ff738ee2b2f0b9c650fc59968", 40689, "8834c524165f3104cdf848e26eaefdcb3ed0e0e635e9ec3c1a02d3bcb02c6269"),
    AUTHORITY_VERIFIER_REF: (CONTROL_REVISION, None, "91d5eaf9d63f3595c257ad31502407d1bb9a3cb0", 125914, "19cc65133410cfa4face4887943504c8726430cc196b4f83d68cb3e0675a959d"),
    AUTHORITY_ROOT_REF: (CONTROL_REVISION, None, "a15720151f141e6b783a51d136e94d9957a7b1c6", 20816, "8bfb8834c1e241a18cde984d42524759f53423bcf809dd8657fa4b2be102ff85"),
    INSTALL_RESULT_REF: (INSTALL_RESULT_REVISION, None, "225a3d23e494b86f6e8a8c8594dbacfc40bdb639", 675, "5ac98e74d18c22ee424448284f552f70d859cfe6b1a081769116aa5bcd333a5c"),
    ACTIVATION_RECEIPT_REF: (PRESERVATION_REVISION, None, "2a52e03416a096ccfca5ef9958d61a25290b10ac", 22068, "61b756abed72b2f6ab8fb3b20a260b03c0932f6e4c271c4f723a4e5942cd7f2a"),
}
PUBLIC_EXISTING_BINDINGS = {
    AUTHORITY_DIRECTORY + "/authority-root-v2.json": (20816, "8bfb8834c1e241a18cde984d42524759f53423bcf809dd8657fa4b2be102ff85", 0o600),
    RUNTIME_DIRECTORY + "/collect_item26_manual_cost_stop_raw_v2.py": (85025, "739b8e8bea29250ccd4c24b400af791c67e687f0cecd23a4b1ddbc8b70750ea4", 0o600),
    RUNTIME_DIRECTORY + "/extract_item26_manual_cost_stop_raw_v2.py": (62917, "7264bc6d1b3028c141a32d56a69e248fac283c835f776ed6f7c09b9f1c2d0fd4", 0o600),
    RUNTIME_DIRECTORY + "/verify_item26_manual_cost_stop_authority_v2.py": (125914, "19cc65133410cfa4face4887943504c8726430cc196b4f83d68cb3e0675a959d", 0o600),
    RUNTIME_DIRECTORY + "/runtime-activation-receipt-v3.json": (22068, "61b756abed72b2f6ab8fb3b20a260b03c0932f6e4c271c4f723a4e5942cd7f2a", 0o600),
}
SYSTEM_TOOL_BINDINGS = {
    "/usr/bin/sudo": (1580368, 0o4511, 0, 0, 1, None),
    "/usr/bin/python3": (118928, 0o755, 0, 0, 78, "179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818"),
    "/usr/bin/git": (118928, 0o755, 0, 0, 78, "179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818"),
    PYTHON_RESOLVED_EXECUTABLE: (102352, 0o755, 0, 0, 1, "4b42b1a117605cafc8607b67b0892a609c2cd125012dd56288abeed8c89cdfb1"),
    GIT_EXECUTABLE: (7604272, 0o755, 0, 0, 1, "3121e7e4d16059539731c58d94888709c12904abe922acde8e37caef4607c1d1"),
}
SYSTEM_SYMLINK_BINDINGS = {
    PYTHON_EXECUTABLE: "../../Library/Frameworks/Python3.framework/Versions/3.9/bin/python3",
    "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3": "python3.9",
}
INERT_STATUS = {
    "schema": "noteai.item26.m1-root-staging-source.v1",
    "status": SOURCE_ONLY_IMPLEMENTATION_STATUS,
    "authorizes_execution": False,
    "implementation_complete": True,
    "operational_ready": False,
    "sudo_dispatch_count": 0,
    "root_write_count": 0,
    "automatic_retry_count": 0,
    "cleanup_count": 0,
}

class StageRootError(ValueError):
    pass

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n"

def _sha(raw):
    if type(raw) is not bytes:
        raise StageRootError("stage_root_bytes")
    return hashlib.sha256(raw).hexdigest()

def _oid(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()

def _hex(value, width):
    return type(value) is str and len(value) == width and not (set(value) - set("0123456789abcdef"))

def _read_regular_nofollow(path, expected_row, maximum, *, opener=os.open, fstater=os.fstat, reader=os.read, closer=os.close):
    if type(path) is not str or type(maximum) is not int or maximum < 0:
        raise StageRootError("stage_root_safe_read")
    descriptor = opener(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = fstater(descriptor)
        expected = (expected_row.st_dev, expected_row.st_ino, expected_row.st_size, expected_row.st_mode, expected_row.st_uid, expected_row.st_gid, expected_row.st_nlink, expected_row.st_mtime_ns, expected_row.st_ctime_ns)
        observed = (before.st_dev, before.st_ino, before.st_size, before.st_mode, before.st_uid, before.st_gid, before.st_nlink, before.st_mtime_ns, before.st_ctime_ns)
        if observed != expected or before.st_size > maximum:
            raise StageRootError("stage_root_safe_read")
        raw = bytearray()
        while len(raw) <= maximum:
            chunk = reader(descriptor, maximum + 1 - len(raw))
            if not chunk:
                break
            raw.extend(chunk)
        after = fstater(descriptor)
        stable = (after.st_dev, after.st_ino, after.st_size, after.st_mode, after.st_uid, after.st_gid, after.st_nlink, after.st_mtime_ns, after.st_ctime_ns)
        if len(raw) > maximum or stable != observed:
            raise StageRootError("stage_root_safe_read")
        return bytes(raw)
    except OSError:
        raise StageRootError("stage_root_safe_read") from None
    finally:
        closer(descriptor)

def _socket_fd_identity(descriptor):
    wrapper = None
    try:
        duplicate = os.dup(descriptor)
        wrapper = socket.socket(fileno=duplicate)
        flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        row = os.fstat(descriptor)
        socket_type = wrapper.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
        if (
            wrapper.family != socket.AF_UNIX
            or socket_type != socket.SOCK_STREAM
            or os.isatty(descriptor)
            or flags & os.O_ACCMODE != os.O_RDWR
            or flags & os.O_NONBLOCK
            or flags & getattr(os, "O_ASYNC", 0)
            or wrapper.getsockname() not in (None, "", b"")
            or wrapper.getpeername() not in (None, "", b"")
        ):
            raise StageRootError("stage_root_fd")
        return row.st_dev, row.st_ino
    except (OSError, ValueError):
        raise StageRootError("stage_root_fd") from None
    finally:
        if wrapper is not None:
            wrapper.close()

def _root_termination_handler(_signum, _frame):
    global _ACTIVE_GIT_PROCESS
    process = _ACTIVE_GIT_PROCESS
    pid = getattr(process, "pid", None)
    if type(pid) is int and pid > 1:
        try:
            _settle_git_process(process, force_kill=True)
        except StageRootError:
            _ACTIVE_GIT_PROCESS = None
            raise
        except BaseException:
            _ACTIVE_GIT_PROCESS = None
            raise StageRootError("stage_root_git_containment") from None
        _ACTIVE_GIT_PROCESS = None
    raise StageRootError("stage_root_terminated")

def _early_root_preflight():
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except Exception:
        raise StageRootError("stage_root_early") from None
    os.environ.clear()
    os.environ.update(ROOT_ENVIRONMENT)
    flags = sys.flags
    if (
        os.geteuid() != 0
        or resource.getrlimit(resource.RLIMIT_CORE) != (0, 0)
        or dict(os.environ) != ROOT_ENVIRONMENT
        or os.getcwd() != REPOSITORY_ROOT
        or sys.executable != PYTHON_EXECUTABLE
        or os.path.realpath(sys.executable) != PYTHON_RESOLVED_EXECUTABLE
        or flags.isolated != 1
        or flags.no_site != 1
        or flags.no_user_site != 1
        or flags.ignore_environment != 1
        or flags.dont_write_bytecode != 1
    ):
        raise StageRootError("stage_root_early")
    identities = (_socket_fd_identity(0), _socket_fd_identity(1))
    if identities[0] == identities[1]:
        raise StageRootError("stage_root_fd_alias")
    for signum in _TERMINATION_SIGNALS:
        signal.signal(signum, _root_termination_handler)
    signal.alarm(105)
    return identities

def _tool_snapshot(*, lstater=os.lstat, reader=_read_regular_nofollow, readlinker=os.readlink):
    snapshot = {}
    allowed_parent_symlinks = {"/etc": "private/etc"}
    for path, expected in sorted(SYSTEM_TOOL_BINDINGS.items()):
        size, mode, uid, gid, nlink, digest = expected
        row = lstater(path)
        if (
            not stat.S_ISREG(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or row.st_size != size
            or stat.S_IMODE(row.st_mode) != mode
            or row.st_uid != uid
            or row.st_gid != gid
            or row.st_nlink != nlink
        ):
            raise StageRootError("stage_root_tool")
        observed_digest = None
        if digest is not None:
            observed_digest = _sha(reader(path, row, row.st_size))
            if observed_digest != digest:
                raise StageRootError("stage_root_tool")
        parents = []
        for parent in pathlib.Path(path).parents:
            parent_row = lstater(str(parent))
            if stat.S_ISLNK(parent_row.st_mode):
                target = readlinker(str(parent))
                if allowed_parent_symlinks.get(str(parent)) != target or parent_row.st_uid != 0:
                    raise StageRootError("stage_root_tool_parent")
                kind = ("symlink", target)
            else:
                if not stat.S_ISDIR(parent_row.st_mode) or parent_row.st_uid != 0 or stat.S_IMODE(parent_row.st_mode) & 0o022:
                    raise StageRootError("stage_root_tool_parent")
                kind = ("directory", "")
            parents.append([str(parent), *kind, parent_row.st_dev, parent_row.st_ino, parent_row.st_mode, parent_row.st_uid, parent_row.st_gid, parent_row.st_nlink, parent_row.st_mtime_ns, parent_row.st_ctime_ns])
        snapshot[path] = {
            "kind": "regular",
            "file": [row.st_dev, row.st_ino, row.st_size, row.st_mode, row.st_uid, row.st_gid, row.st_nlink, row.st_mtime_ns, row.st_ctime_ns, observed_digest],
            "parents": parents,
        }
    for path, expected_target in sorted(SYSTEM_SYMLINK_BINDINGS.items()):
        row = lstater(path)
        target = readlinker(path)
        if not stat.S_ISLNK(row.st_mode) or row.st_uid != 0 or row.st_gid != 0 or row.st_nlink != 1 or target != expected_target:
            raise StageRootError("stage_root_tool")
        parents = []
        for parent in pathlib.Path(path).parents:
            parent_row = lstater(str(parent))
            if stat.S_ISLNK(parent_row.st_mode):
                parent_target = readlinker(str(parent))
                if allowed_parent_symlinks.get(str(parent)) != parent_target or parent_row.st_uid != 0:
                    raise StageRootError("stage_root_tool_parent")
                kind = ("symlink", parent_target)
            else:
                if not stat.S_ISDIR(parent_row.st_mode) or parent_row.st_uid != 0 or stat.S_IMODE(parent_row.st_mode) & 0o022:
                    raise StageRootError("stage_root_tool_parent")
                kind = ("directory", "")
            parents.append([str(parent), *kind, parent_row.st_dev, parent_row.st_ino, parent_row.st_mode, parent_row.st_uid, parent_row.st_gid, parent_row.st_nlink, parent_row.st_mtime_ns, parent_row.st_ctime_ns])
        snapshot[path] = {
            "kind": "symlink",
            "file": [row.st_dev, row.st_ino, row.st_size, row.st_mode, row.st_uid, row.st_gid, row.st_nlink, row.st_mtime_ns, row.st_ctime_ns, target],
            "parents": parents,
        }
    return snapshot

def _repository_snapshot(*, lstater=os.lstat, reader=_read_regular_nofollow):
    paths = [REPOSITORY_ROOT, REPOSITORY_ROOT + "/.git", REPOSITORY_ROOT + "/.git/objects", REPOSITORY_ROOT + "/.git/objects/info"]
    rows = {}
    owner = None
    for path in paths:
        row = lstater(path)
        if not stat.S_ISDIR(row.st_mode) or stat.S_ISLNK(row.st_mode) or stat.S_IMODE(row.st_mode) & 0o022 or row.st_uid == 0:
            raise StageRootError("stage_root_repository")
        if owner is None:
            owner = (row.st_uid, row.st_gid)
        elif (row.st_uid, row.st_gid) != owner:
            raise StageRootError("stage_root_repository")
        rows[path] = [row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid, row.st_nlink]
    if owner != (REPOSITORY_OWNER_UID, REPOSITORY_OWNER_GID):
        raise StageRootError("stage_root_repository")
    absent = [
        REPOSITORY_ROOT + "/.git/shallow",
        REPOSITORY_ROOT + "/.git/commondir",
        REPOSITORY_ROOT + "/.git/worktrees",
        REPOSITORY_ROOT + "/.git/objects/info/alternates",
        REPOSITORY_ROOT + "/.git/objects/info/http-alternates",
    ]
    for path in absent:
        try:
            lstater(path)
        except FileNotFoundError:
            continue
        except OSError:
            raise StageRootError("stage_root_repository") from None
        raise StageRootError("stage_root_repository")
    files = {}
    file_rows = {}
    for name, maximum in REPOSITORY_METADATA_MAXIMUMS.items():
        path = REPOSITORY_ROOT + "/.git/" + name
        row = lstater(path)
        if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid != owner[0] or row.st_gid != owner[1] or row.st_nlink != 1 or stat.S_IMODE(row.st_mode) != 0o644 or row.st_size > maximum:
            raise StageRootError("stage_root_repository")
        file_rows[path] = row
    for path, row in file_rows.items():
        raw = reader(path, row, REPOSITORY_METADATA_MAXIMUMS[path.rsplit("/", 1)[-1]])
        if len(raw) != row.st_size:
            raise StageRootError("stage_root_repository")
        files[path] = [row.st_dev, row.st_ino, row.st_size, row.st_mode, row.st_uid, row.st_gid, row.st_nlink, _sha(raw)]
    return {"directories": rows, "files": files, "absent": absent}

def _directory_identity(path, *, exact_mode=None, lstater=os.lstat):
    row = lstater(path)
    if (
        not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or row.st_uid != 0
        or row.st_gid != 0
        or (exact_mode is not None and stat.S_IMODE(row.st_mode) != exact_mode)
        or (exact_mode is None and stat.S_IMODE(row.st_mode) & 0o022)
    ):
        raise StageRootError("stage_root_directory_identity")
    return (row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid, row.st_nlink, row.st_mtime_ns, row.st_ctime_ns)

def _snapshot_existing(*, lstater=os.lstat, lister=os.listdir, reader=_read_regular_nofollow):
    noteai = _directory_identity(NOTEAI_ROOT, lstater=lstater)[:5]
    expected_names = {
        AUTHORITY_DIRECTORY: {"authority-root-v2.json"},
        RUNTIME_DIRECTORY: set(EXISTING_RUNTIME_NAMES),
        JOURNAL_DIRECTORY: set(),
        CUSTODY_DIRECTORY: set(CUSTODY_NAMES),
    }
    directories = {}
    for path, names in expected_names.items():
        directories[path] = _directory_identity(path, exact_mode=0o700, lstater=lstater)
        if set(lister(path)) != names:
            raise StageRootError("stage_root_existing_names")
    public = {}
    public_rows = {}
    for path, expected in sorted(PUBLIC_EXISTING_BINDINGS.items()):
        size, digest, mode = expected
        row = lstater(path)
        if (
            not stat.S_ISREG(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or row.st_uid != 0
            or row.st_gid != 0
            or row.st_nlink != 1
            or row.st_size != size
            or stat.S_IMODE(row.st_mode) != mode
        ):
            raise StageRootError("stage_root_existing_public")
        public_rows[path] = row
    for path, expected in sorted(PUBLIC_EXISTING_BINDINGS.items()):
        size, digest, _mode = expected
        row = public_rows[path]
        raw = reader(path, row, size)
        if len(raw) != size or _sha(raw) != digest:
            raise StageRootError("stage_root_existing_public")
        public[path] = (row.st_dev, row.st_ino, row.st_size, row.st_mode, row.st_uid, row.st_gid, row.st_nlink, row.st_mtime_ns, row.st_ctime_ns, digest)
    custody = {}
    for name in sorted(CUSTODY_NAMES):
        path = CUSTODY_DIRECTORY + "/" + name
        row = lstater(path)
        if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid != 0 or row.st_gid != 0 or row.st_nlink != 1 or stat.S_IMODE(row.st_mode) != 0o600:
            raise StageRootError("stage_root_custody")
        custody[path] = (row.st_dev, row.st_ino, row.st_size, row.st_mode, row.st_uid, row.st_gid, row.st_nlink, row.st_mtime_ns, row.st_ctime_ns)
    return {"noteai": noteai, "directories": directories, "public": public, "custody": custody, "custody_content_read_count": 0}

def _assert_new_absent(*, lstater=os.lstat):
    for path in (CAPTURE_DIRECTORY, MATERIALIZE_DIRECTORY):
        try:
            lstater(path)
        except FileNotFoundError:
            continue
        except OSError:
            raise StageRootError("stage_root_new_absence") from None
        raise StageRootError("stage_root_new_residue")
    return (CAPTURE_DIRECTORY, MATERIALIZE_DIRECTORY)

def _verify_new_partitions(capture_payloads, materialize_payloads, *, lstater=os.lstat, lister=os.listdir, reader=_read_regular_nofollow):
    seen = set()
    result = {}
    pending = []
    for directory, payloads, order in ((CAPTURE_DIRECTORY, capture_payloads, CAPTURE_ORDER), (MATERIALIZE_DIRECTORY, materialize_payloads, MATERIALIZE_ORDER)):
        directory_identity = _directory_identity(directory, exact_mode=0o700, lstater=lstater)
        if (directory_identity[0], directory_identity[1]) in seen or set(lister(directory)) != set(order):
            raise StageRootError("stage_root_new_inventory")
        seen.add((directory_identity[0], directory_identity[1]))
        files = {}
        for name in order:
            raw, mode = payloads[name]
            path = directory + "/" + name
            row = lstater(path)
            identity = (row.st_dev, row.st_ino)
            if (
                identity in seen
                or not stat.S_ISREG(row.st_mode)
                or stat.S_ISLNK(row.st_mode)
                or row.st_uid != 0
                or row.st_gid != 0
                or row.st_nlink != 1
                or stat.S_IMODE(row.st_mode) != mode
                or row.st_size != len(raw)
            ):
                raise StageRootError("stage_root_new_inventory")
            seen.add(identity)
            pending.append((directory, name, path, row, raw))
        result[directory] = {"directory": directory_identity, "files": files}
    for directory, name, path, row, raw in pending:
        observed = reader(path, row, len(raw))
        if observed != raw:
            raise StageRootError("stage_root_new_inventory")
        result[directory]["files"][name] = (row.st_dev, row.st_ino, row.st_size, row.st_mode, _sha(observed))
    return result

def _literal(source, name):
    try:
        tree = ast.parse(source.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError, ValueError):
        raise StageRootError("stage_root_literal")
    values = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name:
            try:
                values.append(ast.literal_eval(node.value))
            except (SyntaxError, TypeError, ValueError):
                raise StageRootError("stage_root_literal")
    if len(values) != 1 or type(values[0]) is not str:
        raise StageRootError("stage_root_literal")
    try:
        return values[0].encode("ascii")
    except UnicodeEncodeError:
        raise StageRootError("stage_root_literal")

def _row_exact(row, revision, ref):
    return (
        type(row) is dict
        and set(row) == {"revision", "ref", "byte_count", "sha256", "git_blob_oid"}
        and row.get("revision") == revision
        and row.get("ref") == ref
        and type(row.get("byte_count")) is int
        and row["byte_count"] > 0
        and _hex(row.get("sha256"), 64)
        and _hex(row.get("git_blob_oid"), 40)
    )

def _validate_bundle(bundle):
    if (
        type(bundle) is not dict
        or set(bundle) != {
            "schema", "authorization_id", "base_revision",
            "source_revision", "acceptance_revision", "source_rows",
            "acceptance_rows", "fixed_rows", "payloads",
            "system_tool_snapshot", "repository_snapshot", "capture_runtime_directory",
            "materialize_runtime_directory", "result_path",
            "automatic_retry_count", "cleanup_count",
        }
        or bundle.get("schema") != BUNDLE_SCHEMA
        or bundle.get("authorization_id") != AUTHORIZATION_ID
        or bundle.get("base_revision") != BASE_REVISION
        or not _hex(bundle.get("source_revision"), 40)
        or not _hex(bundle.get("acceptance_revision"), 40)
        or len({BASE_REVISION, bundle.get("source_revision"), bundle.get("acceptance_revision")}) != 3
        or set(bundle.get("source_rows", {})) != SOURCE_REFS
        or set(bundle.get("acceptance_rows", {})) != SOURCE_REFS
        or set(bundle.get("fixed_rows", {})) != set(FIXED_EXPECTED)
        or set(bundle.get("payloads", {})) != {
            "capture-root-program.py",
            "materialize-root-program.py",
            "stage-root-program.py",
        }
        or set(bundle.get("system_tool_snapshot", {})) != set(SYSTEM_TOOL_BINDINGS) | set(SYSTEM_SYMLINK_BINDINGS)
        or type(bundle.get("repository_snapshot")) is not dict
        or set(bundle.get("repository_snapshot", {})) != {"directories", "files", "absent"}
        or bundle.get("capture_runtime_directory") != CAPTURE_DIRECTORY
        or bundle.get("materialize_runtime_directory") != MATERIALIZE_DIRECTORY
        or bundle.get("result_path") != REPOSITORY_ROOT + "/.codex/item26-m1-capture-materializer-stage-result-" + bundle.get("acceptance_revision", "") + ".json"
        or bundle.get("automatic_retry_count") != 0
        or bundle.get("cleanup_count") != 0
    ):
        raise StageRootError("stage_root_bundle")
    source_revision = bundle["source_revision"]
    acceptance_revision = bundle["acceptance_revision"]
    for ref in SOURCE_REFS:
        if not _row_exact(bundle["source_rows"][ref], source_revision, ref) or not _row_exact(bundle["acceptance_rows"][ref], acceptance_revision, ref):
            raise StageRootError("stage_root_bundle")
    for name, mode in (("capture-root-program.py", "0500"), ("materialize-root-program.py", "0500"), ("stage-root-program.py", "MEMORY_ONLY")):
        row = bundle["payloads"][name]
        if (
            type(row) is not dict
            or set(row) != {"byte_count", "sha256", "mode", "source_revision", "source_ref"}
            or type(row.get("byte_count")) is not int
            or row["byte_count"] < 1
            or not _hex(row.get("sha256"), 64)
            or row.get("mode") != mode
            or row.get("source_revision") != acceptance_revision
            or row.get("source_ref") != STAGER_REF + ":" + {
                "capture-root-program.py": "CAPTURE_ROOT_PROGRAM",
                "materialize-root-program.py": "MATERIALIZE_ROOT_PROGRAM",
                "stage-root-program.py": "STAGE_ROOT_PROGRAM",
            }[name]
        ):
            raise StageRootError("stage_root_bundle")
    return source_revision, acceptance_revision

def _topology_exact(snapshot, source_revision, acceptance_revision):
    return (
        type(snapshot) is dict
        and snapshot.get("parents") == {
            source_revision: [BASE_REVISION],
            acceptance_revision: [source_revision],
        }
        and snapshot.get("base_to_source_paths") == sorted(SOURCE_REFS)
        and snapshot.get("source_to_acceptance_paths") == sorted(ACCEPTANCE_REFS)
        and snapshot.get("head_revision") == acceptance_revision
        and snapshot.get("upstream_revision") == acceptance_revision
        and snapshot.get("origin_main_revision") == acceptance_revision
        and snapshot.get("tracked_changes") == []
    )

def _settle_git_process(process, *, force_kill, monotonic=time.monotonic, sleep=time.sleep):
    pid = getattr(process, "pid", None)
    if type(pid) is not int or pid <= 1:
        raise StageRootError("stage_root_git_process")
    reaped = False
    returncode = None
    if not force_kill:
        try:
            returncode = process.wait(timeout=0.2)
            reaped = True
        except Exception:
            pass
        if reaped:
            try:
                os.killpg(pid, 0)
            except ProcessLookupError:
                return returncode
            except OSError:
                pass
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        raise StageRootError("stage_root_git_containment") from None
    deadline = monotonic() + 2.0
    while True:
        remaining = deadline - monotonic()
        if not reaped and remaining > 0:
            try:
                returncode = process.wait(timeout=min(0.05, max(0.01, remaining)))
                reaped = True
            except Exception:
                pass
        group_absent = False
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            group_absent = True
        except OSError:
            pass
        if reaped and group_absent:
            return returncode
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(0.01, remaining))
    raise StageRootError("stage_root_git_containment")

def _settle_active_git_process(process, *, force_kill):
    global _ACTIVE_GIT_PROCESS
    previous_mask = None
    mask_failure = None
    try:
        previous_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK,
            _TERMINATION_SIGNALS,
        )
    except BaseException as exc:
        mask_failure = exc
    returncode = None
    settle_failure = None
    try:
        returncode = _settle_git_process(
            process,
            force_kill=force_kill or mask_failure is not None,
        )
    except BaseException as exc:
        settle_failure = exc
    _ACTIVE_GIT_PROCESS = None
    restore_failure = None
    if previous_mask is not None:
        try:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        except BaseException as exc:
            restore_failure = exc
    if settle_failure is not None:
        if isinstance(settle_failure, StageRootError):
            raise settle_failure
        raise StageRootError("stage_root_git_containment") from None
    if restore_failure is not None:
        if isinstance(restore_failure, StageRootError):
            raise restore_failure
        raise StageRootError("stage_root_signal_mask") from None
    if mask_failure is not None:
        raise StageRootError("stage_root_signal_mask") from None
    return returncode

def _git_child_preexec():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.setgroups([])
    os.setgid(REPOSITORY_OWNER_GID)
    os.setuid(REPOSITORY_OWNER_UID)
    os.umask(0o077)
    if (
        os.geteuid() != REPOSITORY_OWNER_UID
        or os.getegid() != REPOSITORY_OWNER_GID
        or os.getgroups() != []
        or resource.getrlimit(resource.RLIMIT_CORE) != (0, 0)
    ):
        os._exit(78)

def _local_git(arguments, maximum, *, popen=subprocess.Popen, selector_factory=selectors.DefaultSelector, monotonic=time.monotonic):
    global _ACTIVE_GIT_PROCESS
    if type(arguments) is not list or not arguments or type(maximum) is not int or not 1 <= maximum <= MAX_GIT_BYTES:
        raise StageRootError("stage_root_git_arguments")
    selector = selector_factory()
    try:
        previous_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK,
            _TERMINATION_SIGNALS,
        )
    except BaseException:
        selector.close()
        raise StageRootError("stage_root_signal_mask") from None
    process = None
    spawn_failure = None
    try:
        process = popen(
            [GIT_EXECUTABLE, "--no-replace-objects", "-c", "safe.directory=" + REPOSITORY_ROOT, "-c", "protocol.file.allow=never", "-c", "protocol.ext.allow=never", *arguments],
            cwd=REPOSITORY_ROOT,
            env=dict(GIT_ENVIRONMENT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
            preexec_fn=_git_child_preexec,
            text=False,
            bufsize=0,
        )
        _ACTIVE_GIT_PROCESS = process
    except BaseException as exc:
        spawn_failure = exc
    restore_failure = None
    try:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    except BaseException as exc:
        restore_failure = exc
    if spawn_failure is not None or restore_failure is not None:
        containment_failure = None
        if process is not None and _ACTIVE_GIT_PROCESS is process:
            try:
                _settle_active_git_process(process, force_kill=True)
            except BaseException as exc:
                containment_failure = exc
        selector.close()
        if containment_failure is not None:
            if isinstance(containment_failure, StageRootError):
                raise containment_failure
            raise StageRootError("stage_root_git_containment") from None
        failure = restore_failure if restore_failure is not None else spawn_failure
        if isinstance(failure, StageRootError):
            raise failure
        raise StageRootError("stage_root_git_spawn") from None
    output = bytearray()
    failure = None
    eof = False
    deadline = monotonic() + GIT_TIMEOUT_SECONDS
    try:
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        while not eof:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise StageRootError("stage_root_git_timeout")
            for key, _mask in selector.select(min(remaining, 0.25)):
                try:
                    chunk = os.read(key.fileobj.fileno(), min(65536, maximum + 1 - len(output)))
                except BlockingIOError:
                    continue
                if chunk:
                    output.extend(chunk)
                    if len(output) > maximum:
                        raise StageRootError("stage_root_git_output")
                else:
                    selector.unregister(key.fileobj)
                    eof = True
    except BaseException as exc:
        failure = exc
    finally:
        selector.close()
        returncode = _settle_active_git_process(
            process,
            force_kill=failure is not None,
        )
    if failure is not None:
        if isinstance(failure, StageRootError):
            raise failure
        raise StageRootError("stage_root_git_io") from None
    return returncode, bytes(output)

def _git_text(arguments, maximum=16384, *, allowed=(0,)):
    returncode, raw = _local_git(arguments, maximum)
    if returncode not in allowed:
        raise StageRootError("stage_root_git_return")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise StageRootError("stage_root_git_text") from None

def _default_git_reader(revision, ref):
    if not _hex(revision, 40) or type(ref) is not str or not ref or ref.startswith("-") or "\0" in ref:
        raise StageRootError("stage_root_git_arguments")
    oid = _git_text(["rev-parse", "--verify", revision + ":" + ref], 128).strip()
    if not _hex(oid, 40):
        raise StageRootError("stage_root_git_oid")
    returncode, raw = _local_git(["cat-file", "blob", oid], MAX_GIT_BYTES)
    if returncode != 0 or _oid(raw) != oid:
        raise StageRootError("stage_root_git_object")
    return {"raw": raw, "git_blob_oid": oid}

def _commit_parent(revision):
    fields = _git_text(["rev-list", "--parents", "-n", "1", revision], 256).strip().split()
    if len(fields) != 2 or fields[0] != revision or not _hex(fields[1], 40):
        raise StageRootError("stage_root_topology")
    return fields[1]

def _path_list(arguments):
    raw = _git_text(arguments, 32768)
    values = raw.splitlines()
    if any(not value or "\0" in value for value in values) or len(values) != len(set(values)):
        raise StageRootError("stage_root_topology")
    return sorted(values)

def _default_topology_reader(source_revision, acceptance_revision):
    promisor_code, promisor_raw = _local_git(["config", "--local", "--get-regexp", "^(extensions\\.partialClone|remote\\..*\\.promisor)$"], 4096)
    if promisor_code not in (0, 1) or promisor_raw:
        raise StageRootError("stage_root_promisor")
    head = _git_text(["rev-parse", "--verify", "HEAD"], 128).strip()
    upstream = _git_text(["rev-parse", "--verify", "@{upstream}"], 128).strip()
    origin = _git_text(["rev-parse", "--verify", "refs/remotes/origin/main"], 128).strip()
    tracked = _git_text(["status", "--porcelain=v1", "--untracked-files=no"], 32768).splitlines()
    return {
        "parents": {
            source_revision: [_commit_parent(source_revision)],
            acceptance_revision: [_commit_parent(acceptance_revision)],
        },
        "base_to_source_paths": _path_list(["diff-tree", "--no-commit-id", "--name-only", "-r", BASE_REVISION, source_revision]),
        "source_to_acceptance_paths": _path_list(["diff-tree", "--no-commit-id", "--name-only", "-r", source_revision, acceptance_revision]),
        "head_revision": head,
        "upstream_revision": upstream,
        "origin_main_revision": origin,
        "tracked_changes": tracked,
    }

def _read_bound(git_reader, revision, ref, expected):
    row = git_reader(revision, ref)
    if not _row_exact(expected, revision, ref) or type(row) is not dict or set(row) != {"raw", "git_blob_oid"}:
        raise StageRootError("stage_root_git")
    raw = row["raw"]
    oid = row["git_blob_oid"]
    if (
        type(raw) is not bytes
        or not raw
        or not _hex(oid, 40)
        or _oid(raw) != oid
        or expected.get("byte_count") != len(raw)
        or expected.get("sha256") != _sha(raw)
        or expected.get("git_blob_oid") != oid
    ):
        raise StageRootError("stage_root_git_binding")
    return raw

def _manifest_payload(name, raw, mode, source_revision, source_ref):
    return {
        "name": name,
        "byte_count": len(raw),
        "sha256": _sha(raw),
        "mode": format(mode, "04o"),
        "source_revision": source_revision,
        "source_ref": source_ref,
    }

def _make_payloads(bundle, git_reader):
    source_revision = bundle["source_revision"]
    acceptance_revision = bundle["acceptance_revision"]
    source_raw = {}
    for ref in sorted(SOURCE_REFS):
        first = _read_bound(git_reader, source_revision, ref, bundle["source_rows"][ref])
        second = _read_bound(git_reader, acceptance_revision, ref, bundle["acceptance_rows"][ref])
        if (ref in ACCEPTANCE_REFS and first == second) or (ref not in ACCEPTANCE_REFS and first != second):
            raise StageRootError("stage_root_source_drift")
        source_raw[ref] = first
    stager = source_raw[STAGER_REF]
    capture = _literal(stager, "CAPTURE_ROOT_PROGRAM")
    materialize = _literal(stager, "MATERIALIZE_ROOT_PROGRAM")
    stage = _literal(stager, "STAGE_ROOT_PROGRAM")
    if (
        bundle["payloads"]["capture-root-program.py"]["sha256"] != _sha(capture)
        or bundle["payloads"]["capture-root-program.py"]["byte_count"] != len(capture)
        or bundle["payloads"]["materialize-root-program.py"]["sha256"] != _sha(materialize)
        or bundle["payloads"]["materialize-root-program.py"]["byte_count"] != len(materialize)
        or bundle["payloads"]["stage-root-program.py"]["sha256"] != _sha(stage)
        or bundle["payloads"]["stage-root-program.py"]["byte_count"] != len(stage)
    ):
        raise StageRootError("stage_root_payload_binding")
    fixed_raw = {}
    for ref, expected in sorted(FIXED_EXPECTED.items()):
        revision, provenance_revision, oid, size, digest = expected
        rows = bundle["fixed_rows"][ref]
        if (
            type(rows) is not dict
            or set(rows) != {"revision", "source_revision", "frozen", "provenance", "acceptance"}
            or rows["revision"] != revision
            or rows["source_revision"] != provenance_revision
            or not _row_exact(rows["frozen"], revision, ref)
            or not _row_exact(rows["acceptance"], acceptance_revision, ref)
            or rows["frozen"]["git_blob_oid"] != oid
            or rows["frozen"]["byte_count"] != size
            or rows["frozen"]["sha256"] != digest
        ):
            raise StageRootError("stage_root_fixed_bundle")
        frozen = _read_bound(git_reader, revision, ref, rows["frozen"])
        accepted = _read_bound(git_reader, acceptance_revision, ref, rows["acceptance"])
        if provenance_revision is None:
            if rows["provenance"] is not None:
                raise StageRootError("stage_root_fixed_bundle")
            provenance = frozen
        else:
            if not _row_exact(rows["provenance"], provenance_revision, ref):
                raise StageRootError("stage_root_fixed_bundle")
            provenance = _read_bound(git_reader, provenance_revision, ref, rows["provenance"])
        if frozen != accepted or provenance != frozen:
            raise StageRootError("stage_root_fixed_drift")
        fixed_raw[ref] = frozen
    adapter = fixed_raw[ADAPTER_REF]
    builder = fixed_raw[BUILDER_REF]
    verifier = fixed_raw[EVIDENCE_VERIFIER_REF]
    authority = fixed_raw[AUTHORITY_VERIFIER_REF]
    extractor = fixed_raw[EXTRACTOR_REF]
    capture_manifest = {
        "schema": MANIFEST_SCHEMA,
        "manifest_name": "capture-runtime-manifest.json",
        "manifest_mode": "0600",
        "payloads": {
            "capture-root-program.py": _manifest_payload("capture-root-program.py", capture, 0o500, acceptance_revision, STAGER_REF + ":CAPTURE_ROOT_PROGRAM"),
            "item26_aliyun_official_read_v2.py": _manifest_payload("item26_aliyun_official_read_v2.py", adapter, 0o500, BASE_REVISION, ADAPTER_REF),
        },
    }
    materialize_manifest = {
        "schema": MANIFEST_SCHEMA,
        "manifest_name": "materialize-runtime-manifest.json",
        "manifest_mode": "0600",
        "payloads": {
            "materialize-root-program.py": _manifest_payload("materialize-root-program.py", materialize, 0o500, acceptance_revision, STAGER_REF + ":MATERIALIZE_ROOT_PROGRAM"),
            "build_item26_manual_cost_stop_evidence_v2.py": _manifest_payload("build_item26_manual_cost_stop_evidence_v2.py", builder, 0o500, CONTROL_REVISION, BUILDER_REF),
            "verify_item26_manual_cost_stop_evidence_v2.py": _manifest_payload("verify_item26_manual_cost_stop_evidence_v2.py", verifier, 0o500, CONTROL_REVISION, EVIDENCE_VERIFIER_REF),
            "verify_item26_manual_cost_stop_authority_v2.py": _manifest_payload("verify_item26_manual_cost_stop_authority_v2.py", authority, 0o500, CONTROL_REVISION, AUTHORITY_VERIFIER_REF),
            "extract_item26_manual_cost_stop_raw_v2.py": _manifest_payload("extract_item26_manual_cost_stop_raw_v2.py", extractor, 0o500, CONTROL_REVISION, EXTRACTOR_REF),
        },
    }
    return {
        "capture-root-program.py": (capture, 0o500),
        "item26_aliyun_official_read_v2.py": (adapter, 0o500),
        "capture-runtime-manifest.json": (canonical(capture_manifest), 0o600),
    }, {
        "materialize-root-program.py": (materialize, 0o500),
        "build_item26_manual_cost_stop_evidence_v2.py": (builder, 0o500),
        "verify_item26_manual_cost_stop_evidence_v2.py": (verifier, 0o500),
        "verify_item26_manual_cost_stop_authority_v2.py": (authority, 0o500),
        "extract_item26_manual_cost_stop_raw_v2.py": (extractor, 0o500),
        "materialize-runtime-manifest.json": (canonical(materialize_manifest), 0o600),
    }

def _mkdir_one(path, *, mkdir=os.mkdir, lstater=os.lstat):
    mkdir(path, 0o700)
    row = lstater(path)
    if not stat.S_ISDIR(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid != 0 or row.st_gid != 0 or stat.S_IMODE(row.st_mode) != 0o700:
        raise StageRootError("stage_root_directory")
    return (row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid, row.st_nlink)

def _write_file_one(path, raw, mode, *, opener=os.open, writer=os.write, seeker=os.lseek, reader=os.read, fsyncer=os.fsync, fstater=os.fstat, closer=os.close):
    descriptor = opener(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        view = memoryview(raw)
        while view:
            count = writer(descriptor, view)
            if count < 1:
                raise StageRootError("stage_root_write")
            view = view[count:]
        fsyncer(descriptor)
        seeker(descriptor, 0, os.SEEK_SET)
        readback = bytearray()
        while len(readback) <= len(raw):
            chunk = reader(descriptor, len(raw) + 1 - len(readback))
            if not chunk:
                break
            readback.extend(chunk)
        row = fstater(descriptor)
        if (
            bytes(readback) != raw
            or not stat.S_ISREG(row.st_mode)
            or row.st_uid != 0
            or row.st_gid != 0
            or row.st_nlink != 1
            or stat.S_IMODE(row.st_mode) != mode
            or row.st_size != len(raw)
        ):
            raise StageRootError("stage_root_readback")
        fsyncer(descriptor)
        return (row.st_dev, row.st_ino, row.st_size, row.st_mode, _sha(raw))
    finally:
        closer(descriptor)

def _fsync_directory(path, *, opener=os.open, fsyncer=os.fsync, closer=os.close):
    descriptor = opener(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW)
    try:
        fsyncer(descriptor)
    finally:
        closer(descriptor)

def _stage_once(bundle, *, topology_reader=_default_topology_reader, git_reader=_default_git_reader, inventory_snapshot=_snapshot_existing, tool_snapshot=_tool_snapshot, repository_snapshot=_repository_snapshot, absence_checker=_assert_new_absent, new_inventory_verifier=_verify_new_partitions, mkdir_one=_mkdir_one, write_one=_write_file_one, fsync_directory=_fsync_directory):
    source_revision, acceptance_revision = _validate_bundle(bundle)
    tools_before = tool_snapshot()
    if tools_before != bundle["system_tool_snapshot"]:
        raise StageRootError("stage_root_tools")
    repository_before = repository_snapshot()
    if repository_before != bundle["repository_snapshot"]:
        raise StageRootError("stage_root_repository")
    topology = topology_reader(source_revision, acceptance_revision)
    if not _topology_exact(topology, source_revision, acceptance_revision):
        raise StageRootError("stage_root_topology")
    existing_before = inventory_snapshot()
    absence_checker()
    capture_payloads, materialize_payloads = _make_payloads(bundle, git_reader)
    if tuple(capture_payloads) != CAPTURE_ORDER or tuple(materialize_payloads) != MATERIALIZE_ORDER:
        raise StageRootError("stage_root_order")
    if inventory_snapshot() != existing_before or tool_snapshot() != tools_before or repository_snapshot() != repository_before:
        raise StageRootError("stage_root_prewrite_drift")
    if topology_reader(source_revision, acceptance_revision) != topology:
        raise StageRootError("stage_root_prewrite_topology_drift")
    capture_check, materialize_check = _make_payloads(bundle, git_reader)
    if capture_check != capture_payloads or materialize_check != materialize_payloads:
        raise StageRootError("stage_root_prewrite_object_drift")
    absence_checker()
    mkdir_one(CAPTURE_DIRECTORY)
    fsync_directory(NOTEAI_ROOT)
    for name in CAPTURE_ORDER:
        raw, mode = capture_payloads[name]
        write_one(CAPTURE_DIRECTORY + "/" + name, raw, mode)
        fsync_directory(CAPTURE_DIRECTORY)
    fsync_directory(CAPTURE_DIRECTORY)
    fsync_directory(NOTEAI_ROOT)
    mkdir_one(MATERIALIZE_DIRECTORY)
    fsync_directory(NOTEAI_ROOT)
    for name in MATERIALIZE_ORDER:
        raw, mode = materialize_payloads[name]
        write_one(MATERIALIZE_DIRECTORY + "/" + name, raw, mode)
        fsync_directory(MATERIALIZE_DIRECTORY)
    fsync_directory(MATERIALIZE_DIRECTORY)
    fsync_directory(NOTEAI_ROOT)
    if topology_reader(source_revision, acceptance_revision) != topology:
        raise StageRootError("stage_root_postwrite_topology_drift")
    capture_check, materialize_check = _make_payloads(bundle, git_reader)
    if capture_check != capture_payloads or materialize_check != materialize_payloads:
        raise StageRootError("stage_root_postwrite_object_drift")
    staged = new_inventory_verifier(capture_payloads, materialize_payloads)
    if (
        set(staged) != {CAPTURE_DIRECTORY, MATERIALIZE_DIRECTORY}
        or inventory_snapshot() != existing_before
        or tool_snapshot() != tools_before
        or repository_snapshot() != repository_before
    ):
        raise StageRootError("stage_root_existing_drift")
    return {
        "schema": STATUS_SCHEMA,
        "status": "BOTH_RUNTIME_PARTITIONS_STAGED",
        "source_revision": source_revision,
        "acceptance_revision": acceptance_revision,
        "capture_directory_create_count": 1,
        "materialize_directory_create_count": 1,
        "capture_file_create_count": 3,
        "materialize_file_create_count": 6,
        "sudo_dispatch_count": 1,
        "automatic_retry_count": 0,
        "cleanup_count": 0,
        "rollback_count": 0,
        "private_key_read_count": 0,
    }

def _read_bundle(stream):
    raw = stream.read(MAX_BUNDLE_BYTES + 1)
    if not 1 <= len(raw) <= MAX_BUNDLE_BYTES:
        raise StageRootError("stage_root_bundle_size")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise StageRootError("stage_root_bundle")
    if canonical(value) != raw:
        raise StageRootError("stage_root_bundle")
    return value

def _write_public_status(value, *, writer=os.write):
    raw = canonical(value)
    view = memoryview(raw)
    while view:
        count = writer(1, view)
        if count < 1:
            raise StageRootError("stage_root_status_write")
        view = view[count:]

def _parse_public_arguments(argv):
    if (
        type(argv) is not list
        or len(argv) != 5
        or argv[0] != "--stage-root"
        or not _hex(argv[1], 40)
        or not _hex(argv[2], 40)
        or type(argv[3]) is not str
        or not argv[3].isascii()
        or not argv[3].isdigit()
        or argv[3] != str(int(argv[3]))
        or not 1 <= int(argv[3]) <= MAX_BUNDLE_BYTES
        or not _hex(argv[4], 64)
    ):
        raise StageRootError("stage_root_arguments")
    return argv[1], argv[2], int(argv[3]), argv[4]

def _public_main(argv, *, runner, early_preflight=_early_root_preflight, status_writer=_write_public_status):
    channels_ready = False
    try:
        early_preflight()
        channels_ready = True
        source_revision, acceptance_revision, stage_size, stage_sha256 = _parse_public_arguments(argv)
        bundle = _read_bundle(sys.stdin.buffer)
        _validate_bundle(bundle)
        stage_row = bundle["payloads"]["stage-root-program.py"]
        if (
            bundle["source_revision"] != source_revision
            or bundle["acceptance_revision"] != acceptance_revision
            or stage_row["byte_count"] != stage_size
            or stage_row["sha256"] != stage_sha256
        ):
            raise StageRootError("stage_root_self_binding")
        result = runner(bundle)
        status_writer(result)
        return 0
    except BaseException:
        if channels_ready:
            try:
                status_writer({
                    "schema": STATUS_SCHEMA,
                    "status": "BLOCKED_FIXED_FAILURE",
                    "automatic_retry_count": 0,
                    "cleanup_count": 0,
                    "raw_value_emitted_count": 0,
                })
            except Exception:
                pass
        return 78

def main():
    if EXECUTION_ENABLED is True:
        return _public_main(sys.argv[1:], runner=_stage_once)
    sys.stdout.buffer.write(canonical(INERT_STATUS))
    sys.stdout.buffer.flush()
    return 78

if __name__ == "__main__":
    raise SystemExit(main())
'''


def main(argv: Optional[list[str]] = None) -> int:
    if EXECUTION_ENABLED is True:
        _execution_gate()
        arguments = sys.argv[1:] if argv is None else argv
        materialize_commit_state: dict[str, Any] = {}
        try:
            result = _run_future_mode_after_gate(
                arguments,
                stage_runner=_default_future_stage,
                capture_runner=_default_future_capture,
                materialize_runner=lambda source, acceptance: (
                    _default_future_materialize(
                        source,
                        acceptance,
                        commit_state=materialize_commit_state,
                    )
                ),
            )
            sys.stdout.buffer.write(canonical_bytes(result))
            sys.stdout.buffer.flush()
            return 0
        except BaseException:
            if "durable_result" in materialize_commit_state:
                # The two public files have both passed readback and their
                # parent directory fsync.  A lost CLI status cannot reverse
                # that one-way terminal and must never emit BLOCKED/78.
                return 0
            sys.stdout.buffer.write(
                canonical_bytes(
                    {
                        "schema": STAGE_RESULT_SCHEMA,
                        "status": "BLOCKED_FIXED_FAILURE",
                        "automatic_retry_count": 0,
                        "cleanup_count": 0,
                        "raw_value_emitted_count": 0,
                    }
                )
            )
            sys.stdout.buffer.flush()
            return 78
    arguments = sys.argv[1:] if argv is None else argv
    if arguments:
        raise StagerError("source_only_arguments")
    sys.stdout.buffer.write(canonical_bytes(SOURCE_ONLY_STATUS))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
