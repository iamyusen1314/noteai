import base64
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import collect_item26_manual_cost_stop_raw_v2 as collector  # noqa: E402
import extract_item26_manual_cost_stop_raw_v2 as extractor  # noqa: E402
from tests.test_extract_item26_manual_cost_stop_raw_v2 import (  # noqa: E402
    CLONE_ID,
    CONTROL_REVISION,
    SOURCE_ID,
    SOURCE_NAME,
    actiontrail_capture,
    provider_capture,
)


VALIDATE_RUNTIME_ACTIVATION = collector._validate_runtime_activation
VALIDATE_ACTIVATION = collector._validate_activation
SOURCE_HASHES = collector._source_hashes


def decoded(value):
    return base64.b64decode(value, validate=True)


class ManualCostStopCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix=".item26-collector-test-",
            dir=ROOT,
        )
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name).resolve()
        self.journal = root / "journal"
        self.authority = root / "authority"
        self.journal.mkdir(mode=0o700)
        self.authority.mkdir(mode=0o700)
        root_file = self.authority / collector.ROOT_FILE
        root_file.write_bytes(b"{}\n")
        root_file.chmod(0o600)
        self.owner_uid = os.getuid()
        self.finalized_patch = mock.patch.object(
            collector.authority,
            "AUTHORITY_V2_FINALIZED",
            True,
        )
        self.finalized_patch.start()
        self.addCleanup(self.finalized_patch.stop)
        self.root_hash_patch = mock.patch.object(
            collector.authority,
            "EXPECTED_AUTHORITY_ROOT_FILE_SHA256",
            "f" * 64,
        )
        self.root_hash_patch.start()
        self.addCleanup(self.root_hash_patch.stop)
        self.source_hashes = {
            "collector_source_sha256": "a" * 64,
            "extractor_source_sha256": "b" * 64,
            "authority_source_sha256": "c" * 64,
        }
        self.source_patch = mock.patch.object(
            collector,
            "_source_hashes",
            return_value=self.source_hashes,
        )
        self.source_patch.start()
        self.addCleanup(self.source_patch.stop)
        self.activation_patch = mock.patch.object(
            collector,
            "_validate_activation",
            return_value={
                "authority_root_file_sha256": "f" * 64,
                "authority_root_git_blob_sha256": "f" * 64,
                "authority_epoch": collector.AUTHORITY_EPOCH_ID,
                "control_revision": CONTROL_REVISION,
                "post_action_readback_only": True,
                "authorizes_new_action": False,
                "readiness_credit_allowed": False,
                "root_value": {
                    "authority_epoch_id": collector.AUTHORITY_EPOCH_ID,
                },
                "authority_keys": {
                    "provider": (b"test-provider-public-key", "1" * 64),
                    "confirmation": (
                        b"test-confirmation-public-key",
                        "2" * 64,
                    ),
                    "local_ci_observation": (
                        b"test-local-ci-public-key",
                        "3" * 64,
                    ),
                },
            },
        )
        self.activation_mock = self.activation_patch.start()
        self.addCleanup(self.activation_patch.stop)
        self.runtime_binding = {
            "authority_epoch": collector.AUTHORITY_EPOCH_ID,
            "authority_root_file_sha256": "f" * 64,
            "authority_root_git_blob_sha256": "f" * 64,
            "activation_receipt_schema": collector.ACTIVATION_RECEIPT_SCHEMA,
            "activation_receipt_sha256": "e" * 64,
        }
        self.runtime_patch = mock.patch.object(
            collector,
            "_validate_runtime_activation",
            return_value=self.runtime_binding,
        )
        self.runtime_patch.start()
        self.addCleanup(self.runtime_patch.stop)

        provider = provider_capture()
        actiontrail = actiontrail_capture()
        provider["collector_source_sha256"] = "a" * 64
        provider["extractor_source_sha256"] = "b" * 64
        provider["authority_source_sha256"] = "c" * 64
        provider["activation_receipt_sha256"] = "e" * 64
        actiontrail["collector_source_sha256"] = "a" * 64
        actiontrail["extractor_source_sha256"] = "b" * 64
        actiontrail["authority_source_sha256"] = "c" * 64
        actiontrail["activation_receipt_sha256"] = "e" * 64
        self.provider = provider
        self.actiontrail = actiontrail
        protection_request = "test-protection-provider-request"
        deletion_request = "test-delete-provider-request"
        protection_marker = "test-protection-idempotency-marker"
        first_page = extractor.decode_canonical_json(
            actiontrail["records"][0]["response_json_base64"],
            "fixture",
        )
        first_page["Events"][0]["requestId"] = protection_request
        first_page["Events"][0]["requestParameters"] = {
            "ClientToken": protection_marker,
            "DBInstanceId": CLONE_ID,
            "DeletionProtection": False,
        }
        actiontrail["records"][0]["response_json_base64"] = (
            base64.b64encode(
                extractor.canonical_bytes(first_page)
            ).decode("ascii")
        )
        second_page = extractor.decode_canonical_json(
            actiontrail["records"][1]["response_json_base64"],
            "fixture",
        )
        second_page["Events"][0]["requestId"] = deletion_request
        second_page["Events"][0]["requestParameters"] = {
            "DBInstanceId": CLONE_ID,
        }
        actiontrail["records"][1]["response_json_base64"] = (
            base64.b64encode(extractor.canonical_bytes(second_page)).decode(
                "ascii"
            )
        )
        billing_response = extractor.decode_canonical_json(
            provider["records"][2]["response_json_base64"], "fixture"
        )
        self.patchers = [
            mock.patch.object(
                extractor,
                "EXPECTED_OLD_CLONE_SHA256",
                extractor.value_sha256(CLONE_ID),
            ),
            mock.patch.object(
                extractor,
                "EXPECTED_SOURCE_SHA256",
                extractor.value_sha256(SOURCE_ID),
            ),
            mock.patch.object(
                extractor,
                "EXPECTED_SOURCE_NAME_SHA256",
                extractor.value_sha256(SOURCE_NAME),
            ),
            mock.patch.object(
                extractor,
                "EXPECTED_OLD_CLONE_NAME_SHA256",
                extractor.value_sha256(
                    SOURCE_NAME.replace("source", "old-clone")
                ),
            ),
            mock.patch.object(
                extractor,
                "EXPECTED_BILLING_RESPONSE_SHA256",
                extractor.sha256(extractor.canonical_bytes(billing_response)),
            ),
            mock.patch.object(
                extractor,
                "EXPECTED_PROTECTION_REQUEST_ID_SHA256",
                extractor.value_sha256(protection_request),
            ),
            mock.patch.object(
                extractor,
                "EXPECTED_DELETE_REQUEST_ID_SHA256",
                extractor.value_sha256(deletion_request),
            ),
            mock.patch.object(
                extractor,
                "EXPECTED_PROTECTION_CLIENT_TOKEN_SHA256",
                extractor.value_sha256(protection_marker),
            ),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def invoke_pair(self, slot, request_raw, response_raw):
        first = collector.begin(
            control_revision=CONTROL_REVISION,
            slot=slot,
            request_raw=request_raw,
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        second = collector.finish(
            control_revision=CONTROL_REVISION,
            slot=slot,
            response_raw=response_raw,
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        self.assertEqual(first["cloud_call_count"], 0)
        self.assertEqual(second["cloud_call_count"], 0)

    def complete_journal(self):
        for row in self.actiontrail["records"]:
            self.invoke_pair(
                row["slot"],
                decoded(row["request_json_base64"]),
                decoded(row["response_json_base64"]),
            )
        for row in self.provider["records"]:
            self.invoke_pair(
                row["slot"],
                decoded(row["request_json_base64"]),
                decoded(row["response_json_base64"]),
            )

    def test_offline_importer_builds_and_promotes_exact_captures(self):
        self.complete_journal()
        result = collector.finalize(
            control_revision=CONTROL_REVISION,
            journal_directory=self.journal,
            authority_directory=self.authority,
            owner_uid=self.owner_uid,
        )
        self.assertEqual(result["status"], "CAPTURE_INSTALLED")
        self.assertEqual(result["cloud_call_count"], 0)
        self.assertEqual(
            set(path.name for path in self.authority.iterdir()),
            {
                collector.ROOT_FILE,
                collector.PROVIDER_FILE,
                collector.ACTIONTRAIL_FILE,
            },
        )
        for name in (collector.PROVIDER_FILE, collector.ACTIONTRAIL_FILE):
            row = (self.authority / name).stat()
            self.assertEqual(stat.S_IMODE(row.st_mode), 0o600)
            self.assertEqual(row.st_nlink, 1)
        projection = extractor.extract_verified_projection(
            (self.authority / collector.PROVIDER_FILE).read_bytes(),
            (self.authority / collector.ACTIONTRAIL_FILE).read_bytes(),
            expected_control_revision=CONTROL_REVISION,
        )
        self.assertEqual(
            projection.provider["collector_source_sha256"], "a" * 64
        )
        self.assertTrue(projection.provider["old_clone"]["absent"])

    def test_finalize_is_local_and_idempotent_without_new_readback(self):
        self.complete_journal()
        first = collector.finalize(
            control_revision=CONTROL_REVISION,
            journal_directory=self.journal,
            authority_directory=self.authority,
            owner_uid=self.owner_uid,
        )
        second = collector.finalize(
            control_revision=CONTROL_REVISION,
            journal_directory=self.journal,
            authority_directory=self.authority,
            owner_uid=self.owner_uid,
        )
        self.assertEqual(first, second)

    def test_finalize_recovers_after_hard_link_before_stage_unlink(self):
        self.complete_journal()
        journal_fd = os.open(self.journal, os.O_RDONLY | os.O_DIRECTORY)
        try:
            events, _stages, _writes = collector._scan_journal(
                journal_fd,
                self.owner_uid,
            )
            provider_raw, _actiontrail_raw = collector._captures(
                events,
                CONTROL_REVISION,
            )
        finally:
            os.close(journal_fd)
        stage = self.journal / collector.PROVIDER_STAGE_FILE
        stage.write_bytes(provider_raw)
        stage.chmod(0o600)
        target = self.authority / collector.PROVIDER_FILE
        os.link(stage, target)
        self.assertEqual(stage.stat().st_nlink, 2)

        result = collector.finalize(
            control_revision=CONTROL_REVISION,
            journal_directory=self.journal,
            authority_directory=self.authority,
            owner_uid=self.owner_uid,
        )
        self.assertEqual(result["status"], "CAPTURE_INSTALLED")
        self.assertFalse(stage.exists())
        self.assertEqual(target.stat().st_nlink, 1)

    def test_request_must_be_frozen_before_response(self):
        with self.assertRaisesRegex(
            collector.CollectorError, "finish_without_begin"
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=collector.COST_SLOT,
                response_raw=b"{}",
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )

    def test_begin_checks_exact_activation_before_journal_write(self):
        request = decoded(
            self.actiontrail["records"][0]["request_json_base64"]
        )
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=collector.COST_SLOT,
            request_raw=request,
            journal_directory=self.journal,
            authority_directory=self.authority,
            owner_uid=self.owner_uid,
        )
        self.activation_mock.assert_called_with(
            control_revision=CONTROL_REVISION,
            authority_directory=self.authority,
            owner_uid=self.owner_uid,
            require_root_only=True,
        )

    def test_activation_loader_binds_v2_epoch_and_exact_inventory(self):
        root_raw = (self.authority / collector.ROOT_FILE).read_bytes()
        root_digest = collector._sha(root_raw)
        root_value = {
            "authority_epoch_id": collector.AUTHORITY_EPOCH_ID,
            "post_action_readback_only": True,
            "authorizes_new_action": False,
            "readiness_credit_allowed": False,
        }
        keys = {
            "provider": (b"provider", "1" * 64),
            "confirmation": (b"confirmation", "2" * 64),
            "local_ci_observation": (b"ci", "3" * 64),
        }
        with mock.patch.object(
            collector.authority,
            "EXPECTED_AUTHORITY_ROOT_FILE_SHA256",
            root_digest,
        ), mock.patch.object(
            collector.authority,
            "load_activation_root",
            return_value={
                "authority_root_file_sha256": root_digest,
                "authority_root_git_blob_sha256": root_digest,
                "authority_epoch_id": collector.AUTHORITY_EPOCH_ID,
                "root_value": root_value,
                "authority_keys": keys,
            },
        ) as loader:
            binding = VALIDATE_ACTIVATION(
                control_revision=CONTROL_REVISION,
                authority_directory=self.authority,
                owner_uid=self.owner_uid,
                require_root_only=True,
            )
        self.assertEqual(binding["authority_epoch"], collector.AUTHORITY_EPOCH_ID)
        self.assertEqual(binding["authority_root_file_sha256"], root_digest)
        self.assertEqual(
            loader.call_args.kwargs["expected_inventory"],
            (collector.ROOT_FILE,),
        )

    def test_v2_authority_runtime_journal_and_custody_are_disjoint(self):
        directories = (
            collector.AUTHORITY_DIRECTORY,
            collector.RUNTIME_DIRECTORY,
            collector.JOURNAL_DIRECTORY,
            collector.CUSTODY_DIRECTORY,
        )
        self.assertEqual(len(set(directories)), 4)
        for index, first in enumerate(directories):
            for second in directories[index + 1:]:
                self.assertNotIn(first, second.parents)
                self.assertNotIn(second, first.parents)

    def test_runtime_receipt_v3_binds_epoch_root_and_source_blobs(self):
        runtime = Path(self.temporary.name).resolve() / "runtime"
        runtime.mkdir(mode=0o700)
        receipt_path = runtime / collector.ACTIVATION_RECEIPT_FILE
        receipt_path.write_bytes(b'{"schema":"receipt-v3-test"}\n')
        receipt_path.chmod(0o600)
        receipt_binding = {
            "activated_at_utc": "2026-08-17T00:00:03Z",
            "authority_epoch_id": collector.AUTHORITY_EPOCH_ID,
            "authority_root_file_sha256": "f" * 64,
            "authority_root_git_blob_sha256": "f" * 64,
            "activation_receipt_schema": collector.ACTIVATION_RECEIPT_SCHEMA,
            "activation_receipt_sha256": collector._sha(
                receipt_path.read_bytes()
            ),
        }
        with mock.patch.object(
            collector,
            "__file__",
            str(runtime / Path(collector.COLLECTOR_REF).name),
        ), mock.patch.object(
            collector.authority,
            "validate_runtime_activation_receipt",
            return_value=receipt_binding,
        ) as validator, mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:00:04Z",
        ):
            binding = VALIDATE_RUNTIME_ACTIVATION(
                control_revision=CONTROL_REVISION,
                authority_root_file_sha256="f" * 64,
                authority_root_git_blob_sha256="f" * 64,
                authority_epoch=collector.AUTHORITY_EPOCH_ID,
                source_hashes=self.source_hashes,
                root_value={
                    "authority_epoch_id": collector.AUTHORITY_EPOCH_ID,
                },
                authority_keys={
                    "provider": (b"provider", "1" * 64),
                    "confirmation": (b"confirmation", "2" * 64),
                    "local_ci_observation": (b"ci", "3" * 64),
                },
                owner_uid=self.owner_uid,
            )
        self.assertEqual(binding, {
            "authority_epoch": collector.AUTHORITY_EPOCH_ID,
            "authority_root_file_sha256": receipt_binding[
                "authority_root_file_sha256"
            ],
            "authority_root_git_blob_sha256": receipt_binding[
                "authority_root_git_blob_sha256"
            ],
            "activation_receipt_schema": collector.ACTIVATION_RECEIPT_SCHEMA,
            "activation_receipt_sha256": receipt_binding[
                "activation_receipt_sha256"
            ],
        })
        validator.assert_called_once()

    def test_receipt_v2_and_epoch_drift_fail_before_journal_write(self):
        request = decoded(
            self.actiontrail["records"][0]["request_json_base64"]
        )
        for code in ("receipt_v2_schema", "authority_epoch_drift"):
            with self.subTest(code=code), mock.patch.object(
                collector,
                "_validate_runtime_activation",
                side_effect=collector.CollectorError(code),
            ), self.assertRaisesRegex(collector.CollectorError, code):
                collector.begin(
                    control_revision=CONTROL_REVISION,
                    slot=collector.COST_SLOT,
                    request_raw=request,
                    journal_directory=self.journal,
                    authority_directory=self.authority,
                    owner_uid=self.owner_uid,
                )
            self.assertEqual(list(self.journal.iterdir()), [])

    def test_unfinalized_or_missing_root_fails_with_zero_journal(self):
        request = decoded(
            self.actiontrail["records"][0]["request_json_base64"]
        )
        with mock.patch.object(
            collector.authority,
            "AUTHORITY_V2_FINALIZED",
            False,
        ), self.assertRaisesRegex(
            collector.CollectorError,
            "authority_v2_not_finalized",
        ):
            collector.begin(
                control_revision=CONTROL_REVISION,
                slot=collector.COST_SLOT,
                request_raw=request,
                journal_directory=self.journal,
                authority_directory=self.authority,
                owner_uid=self.owner_uid,
            )
        self.assertEqual(list(self.journal.iterdir()), [])
        blocked = collector._blocked_status("authority_v2_not_finalized")
        self.assertEqual(blocked["journal_write_count"], 0)
        self.assertEqual(blocked["cloud_call_count"], 0)
        self.assertEqual(blocked["database_connection_count"], 0)

        (self.authority / collector.ROOT_FILE).unlink()
        with mock.patch.object(
            collector,
            "_validate_activation",
            side_effect=lambda **kwargs: VALIDATE_ACTIVATION(**kwargs),
        ), self.assertRaisesRegex(
            collector.CollectorError,
            "activation_inventory",
        ):
            collector.begin(
                control_revision=CONTROL_REVISION,
                slot=collector.COST_SLOT,
                request_raw=request,
                journal_directory=self.journal,
                authority_directory=self.authority,
                owner_uid=self.owner_uid,
            )
        self.assertEqual(list(self.journal.iterdir()), [])

    def test_v3_runtime_tool_inventory_is_exact_and_versioned(self):
        runtime = Path(self.temporary.name).resolve() / "runtime-inventory"
        runtime.mkdir(mode=0o700)
        contents = {
            Path(collector.COLLECTOR_REF).name: b"collector-v2\n",
            Path(collector.EXTRACTOR_REF).name: b"extractor-v2\n",
            Path(collector.AUTHORITY_REF).name: b"authority-v2\n",
            collector.ACTIVATION_RECEIPT_FILE: b"receipt-v3\n",
        }
        for name, raw in contents.items():
            path = runtime / name
            path.write_bytes(raw)
            path.chmod(0o600)
        self.assertEqual(
            collector.ACTIVATION_RECEIPT_FILE,
            "runtime-activation-receipt-v3.json",
        )
        self.assertEqual(
            collector.ACTIVATION_RECEIPT_SCHEMA,
            "noteai.item26.manual-cost-stop-runtime-activation-receipt.v3",
        )
        self.assertEqual(collector.TOOL_INVENTORY, set(contents))
        with mock.patch.object(
            collector,
            "__file__",
            str(runtime / Path(collector.COLLECTOR_REF).name),
        ), mock.patch.object(
            extractor,
            "__file__",
            str(runtime / Path(collector.EXTRACTOR_REF).name),
        ), mock.patch.object(
            collector.authority,
            "__file__",
            str(runtime / Path(collector.AUTHORITY_REF).name),
        ), mock.patch.object(
            collector,
            "RUNTIME_DIRECTORY",
            runtime,
        ):
            self.assertEqual(
                SOURCE_HASHES(owner_uid=self.owner_uid),
                {
                    "collector_source_sha256": collector._sha(
                        contents[Path(collector.COLLECTOR_REF).name]
                    ),
                    "extractor_source_sha256": collector._sha(
                        contents[Path(collector.EXTRACTOR_REF).name]
                    ),
                    "authority_source_sha256": collector._sha(
                        contents[Path(collector.AUTHORITY_REF).name]
                    ),
                },
            )
            legacy = runtime / "runtime-activation-receipt-v2.json"
            legacy.write_bytes(b"legacy\n")
            legacy.chmod(0o600)
            with self.assertRaisesRegex(
                collector.CollectorError,
                "source_inventory",
            ):
                SOURCE_HASHES(owner_uid=self.owner_uid)

    def test_slot_order_and_control_revision_are_fixed(self):
        request = decoded(
            self.actiontrail["records"][0]["request_json_base64"]
        )
        with self.assertRaisesRegex(collector.CollectorError, "slot_order"):
            collector.begin(
                control_revision=CONTROL_REVISION,
                slot=collector.CREATE_SLOT,
                request_raw=request,
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        with self.assertRaisesRegex(
            collector.CollectorError, "control_revision"
        ):
            collector.begin(
                control_revision=extractor.M0_ANCHOR_REVISION,
                slot=collector.COST_SLOT,
                request_raw=request,
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )

    def test_lookup_next_token_is_derived_from_prior_response(self):
        first = self.actiontrail["records"][0]
        self.invoke_pair(
            first["slot"],
            decoded(first["request_json_base64"]),
            decoded(first["response_json_base64"]),
        )
        self.assertEqual(
            collector.status(
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )["status"],
            "READY_FOR_NEXT_REQUEST",
        )
        second = self.actiontrail["records"][1]
        request = json.loads(decoded(second["request_json_base64"]))
        request["NextToken"] = "different-token"
        with self.assertRaisesRegex(
            collector.CollectorError, "lookup_request"
        ):
            collector.begin(
                control_revision=CONTROL_REVISION,
                slot=second["slot"],
                request_raw=extractor.canonical_bytes(request),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )

    def test_lookup_window_max_results_and_attribute_order_are_fixed(self):
        source = self.actiontrail["records"][0]
        for mutation in ("StartTime", "EndTime", "MaxResults"):
            with self.subTest(mutation=mutation):
                request = json.loads(decoded(source["request_json_base64"]))
                request[mutation] = "wrong"
                with self.assertRaisesRegex(
                    collector.CollectorError, "lookup_request"
                ):
                    collector.begin(
                        control_revision=CONTROL_REVISION,
                        slot=source["slot"],
                        request_raw=extractor.canonical_bytes(request),
                        journal_directory=self.journal,
                        owner_uid=self.owner_uid,
                    )
        request = json.loads(decoded(source["request_json_base64"]))
        request["LookupAttribute"].reverse()
        with self.assertRaisesRegex(
            collector.CollectorError, "lookup_request"
        ):
            collector.begin(
                control_revision=CONTROL_REVISION,
                slot=source["slot"],
                request_raw=extractor.canonical_bytes(request),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )

    def test_mutation_request_is_rejected(self):
        request = {
            "Action": "DeleteDBInstance",
            "Version": "2014-08-15",
            "DBInstanceId": CLONE_ID,
        }
        with self.assertRaisesRegex(
            collector.CollectorError, "lookup_request"
        ):
            collector.begin(
                control_revision=CONTROL_REVISION,
                slot=collector.COST_SLOT,
                request_raw=extractor.canonical_bytes(request),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )

    def test_invalid_response_is_discarded_as_unknown_and_stops(self):
        first = self.actiontrail["records"][0]
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            request_raw=decoded(first["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        with self.assertRaisesRegex(
            collector.CollectorError, "response_unknown"
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                response_raw=b"not-json",
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        state = collector.status(
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        self.assertEqual(state["status"], "UNKNOWN_INFLIGHT")
        event_raw = (self.journal / "000001-finish.json").read_bytes()
        self.assertNotIn(b"not-json", event_raw)
        marker = json.loads(
            base64.b64decode(json.loads(event_raw)["payload_base64"])
        )
        self.assertEqual(
            marker["reason"],
            "OFFICIAL_RESPONSE_EXPORT_FAILED",
        )
        with self.assertRaisesRegex(collector.CollectorError, "journal_unknown"):
            collector.begin(
                control_revision=CONTROL_REVISION,
                slot=collector.COST_SLOT,
                request_raw=decoded(first["request_json_base64"]),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )

    def test_duplicate_json_key_is_unknown(self):
        first = self.actiontrail["records"][0]
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            request_raw=decoded(first["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        with self.assertRaisesRegex(
            collector.CollectorError, "response_unknown"
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                response_raw=b'{"RequestId":"a","RequestId":"b"}',
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )

    def test_non_finite_float_overflow_is_fixed_unknown(self):
        first = self.actiontrail["records"][0]
        deep_value = (
            b"[" * (extractor.MAX_JSON_NESTING_DEPTH + 1)
            + b"0"
            + b"]" * (extractor.MAX_JSON_NESTING_DEPTH + 1)
        )
        rejected_literals = (b"1e999", b"-1e999", b"9" * 5000, deep_value)
        for index, literal in enumerate(rejected_literals, start=1):
            with self.subTest(literal=literal):
                journal = self.journal.parent / f"overflow-{index}"
                journal.mkdir(mode=0o700)
                collector.begin(
                    control_revision=CONTROL_REVISION,
                    slot=first["slot"],
                    request_raw=decoded(first["request_json_base64"]),
                    journal_directory=journal,
                    owner_uid=self.owner_uid,
                )
                response = extractor.decode_canonical_json(
                    first["response_json_base64"],
                    "fixture",
                )
                response["ignoredOverflowProbe"] = 1
                response_raw = extractor.canonical_bytes(response).replace(
                    b'"ignoredOverflowProbe":1',
                    b'"ignoredOverflowProbe":' + literal,
                )
                with self.assertRaisesRegex(
                    collector.CollectorError,
                    "response_unknown",
                ):
                    collector.finish(
                        control_revision=CONTROL_REVISION,
                        slot=first["slot"],
                        response_raw=response_raw,
                        journal_directory=journal,
                        owner_uid=self.owner_uid,
                    )
                event_raw = (journal / "000001-finish.json").read_bytes()
                self.assertNotIn(literal, event_raw)
                marker = json.loads(
                    base64.b64decode(
                        json.loads(event_raw)["payload_base64"]
                    )
                )
                self.assertEqual(
                    marker["reason"],
                    "OFFICIAL_RESPONSE_EXPORT_FAILED",
                )
                self.assertEqual(
                    collector.status(
                        journal_directory=journal,
                        owner_uid=self.owner_uid,
                    )["status"],
                    "UNKNOWN_INFLIGHT",
                )

        journal = self.journal.parent / "oversized-integer"
        journal.mkdir(mode=0o700)
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            request_raw=decoded(first["request_json_base64"]),
            journal_directory=journal,
            owner_uid=self.owner_uid,
        )
        response = extractor.decode_canonical_json(
            first["response_json_base64"],
            "fixture",
        )
        response["Events"][0]["userIdentity"] = (
            '{"principal":' + "9" * 5000 + "}"
        )
        with self.assertRaisesRegex(
            collector.CollectorError,
            "response_unknown",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                response_raw=extractor.canonical_bytes(response),
                journal_directory=journal,
                owner_uid=self.owner_uid,
            )
        self.assertTrue((journal / "000001-finish.json").is_file())
        event_raw = (journal / "000001-finish.json").read_bytes()
        self.assertNotIn(("9" * 5000).encode("ascii"), event_raw)
        event = json.loads(event_raw)
        self.assertEqual(
            base64.b64decode(event["payload_base64"]),
            collector._unknown_marker("OFFICIAL_RESPONSE_EXPORT_FAILED"),
        )
        self.assertEqual(
            collector.status(
                journal_directory=journal,
                owner_uid=self.owner_uid,
            )["status"],
            "UNKNOWN_INFLIGHT",
        )

        journal = self.journal.parent / "invalid-unicode"
        journal.mkdir(mode=0o700)
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            request_raw=decoded(first["request_json_base64"]),
            journal_directory=journal,
            owner_uid=self.owner_uid,
        )
        response = extractor.decode_canonical_json(
            first["response_json_base64"],
            "fixture",
        )
        response["Events"][0]["userIdentity"] = "\ud800"
        with self.assertRaisesRegex(
            collector.CollectorError,
            "response_unknown",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                response_raw=extractor.canonical_bytes(response),
                journal_directory=journal,
                owner_uid=self.owner_uid,
            )
        event_raw = (journal / "000001-finish.json").read_bytes()
        self.assertNotIn(b"\\ud800", event_raw)
        event = json.loads(event_raw)
        self.assertEqual(
            base64.b64decode(event["payload_base64"]),
            collector._unknown_marker("OFFICIAL_RESPONSE_EXPORT_FAILED"),
        )

        journal = self.journal.parent / "billing-float"
        journal.mkdir(mode=0o700)
        completed_rows = [
            *self.actiontrail["records"],
            *self.provider["records"][:2],
        ]
        for row in completed_rows:
            collector.begin(
                control_revision=CONTROL_REVISION,
                slot=row["slot"],
                request_raw=decoded(row["request_json_base64"]),
                journal_directory=journal,
                owner_uid=self.owner_uid,
            )
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=row["slot"],
                response_raw=decoded(row["response_json_base64"]),
                journal_directory=journal,
                owner_uid=self.owner_uid,
            )
        billing = self.provider["records"][2]
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=billing["slot"],
            request_raw=decoded(billing["request_json_base64"]),
            journal_directory=journal,
            owner_uid=self.owner_uid,
        )
        response_raw = decoded(billing["response_json_base64"]).replace(
            b'"PretaxGrossAmount":"198.462"',
            b'"PretaxGrossAmount":198.46199999999999',
        )
        with self.assertRaisesRegex(
            collector.CollectorError,
            "response_unknown",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=billing["slot"],
                response_raw=response_raw,
                journal_directory=journal,
                owner_uid=self.owner_uid,
            )
        event_raw = (journal / "000006-finish.json").read_bytes()
        self.assertNotIn(b"198.46199999999999", event_raw)
        event = json.loads(event_raw)
        self.assertEqual(
            base64.b64decode(event["payload_base64"]),
            collector._unknown_marker("OFFICIAL_RESPONSE_EXPORT_FAILED"),
        )

    def test_semantically_invalid_actiontrail_page_is_unknown(self):
        first = self.actiontrail["records"][0]
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            request_raw=decoded(first["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        response = extractor.decode_canonical_json(
            first["response_json_base64"],
            "fixture",
        )
        response["Events"][0]["resourceName"] = "different-instance"
        with self.assertRaisesRegex(
            collector.CollectorError,
            "response_unknown",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                response_raw=extractor.canonical_bytes(response),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        self.assertEqual(
            collector.status(
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )["status"],
            "UNKNOWN_INFLIGHT",
        )
        event_raw = (self.journal / "000001-finish.json").read_bytes()
        self.assertNotIn(b"different-instance", event_raw)
        event = json.loads(event_raw)
        self.assertEqual(
            base64.b64decode(event["payload_base64"]),
            collector._unknown_marker("OFFICIAL_RESPONSE_EXPORT_FAILED"),
        )

    def test_sensitive_browser_wrapper_is_discarded_into_fixed_unknown(self):
        first = self.actiontrail["records"][0]
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            request_raw=decoded(first["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        response = extractor.decode_canonical_json(
            first["response_json_base64"],
            "fixture",
        )
        response["Events"][0]["EventDetail"] = {
            "headers": {"Cookie": "session=test-sensitive-cookie"},
        }
        with self.assertRaisesRegex(
            collector.CollectorError,
            "response_unknown",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                response_raw=extractor.canonical_bytes(response),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        event_raw = (self.journal / "000001-finish.json").read_bytes()
        self.assertNotIn(b"test-sensitive-cookie", event_raw)
        event = json.loads(event_raw)
        marker = json.loads(base64.b64decode(event["payload_base64"]))
        self.assertEqual(marker["reason"], "SENSITIVE_WRAPPER_DETECTED")
        self.assertFalse(marker["response_bytes_retained"])

    def test_truncated_sensitive_wrapper_is_never_persisted(self):
        first = self.actiontrail["records"][0]
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            request_raw=decoded(first["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        raw = b'{"headers":{"Cookie":"test-truncated-sensitive-cookie"'
        with self.assertRaisesRegex(
            collector.CollectorError,
            "response_unknown",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                response_raw=raw,
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        event_raw = (self.journal / "000001-finish.json").read_bytes()
        self.assertNotIn(b"test-truncated-sensitive-cookie", event_raw)
        marker = json.loads(
            base64.b64decode(json.loads(event_raw)["payload_base64"])
        )
        self.assertEqual(marker["reason"], "SENSITIVE_WRAPPER_DETECTED")

    def test_repeated_next_token_is_unknown(self):
        first, second = self.actiontrail["records"][:2]
        self.invoke_pair(
            first["slot"],
            decoded(first["request_json_base64"]),
            decoded(first["response_json_base64"]),
        )
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=second["slot"],
            request_raw=decoded(second["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        response = extractor.decode_canonical_json(
            second["response_json_base64"],
            "fixture",
        )
        response["NextToken"] = "page-2-token"
        with self.assertRaisesRegex(
            collector.CollectorError,
            "response_unknown",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=second["slot"],
                response_raw=extractor.canonical_bytes(response),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )

    def test_cost_stop_terminal_page_cannot_omit_consumed_delete(self):
        first = self.actiontrail["records"][0]
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            request_raw=decoded(first["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        response = extractor.decode_canonical_json(
            first["response_json_base64"],
            "fixture",
        )
        response["NextToken"] = ""
        with self.assertRaisesRegex(
            collector.CollectorError,
            "response_unknown",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                response_raw=extractor.canonical_bytes(response),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )

    def test_cost_stop_terminal_page_closes_cross_page_identity(self):
        first, second = self.actiontrail["records"][:2]
        self.invoke_pair(
            first["slot"],
            decoded(first["request_json_base64"]),
            decoded(first["response_json_base64"]),
        )
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=second["slot"],
            request_raw=decoded(second["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        response = extractor.decode_canonical_json(
            second["response_json_base64"],
            "fixture",
        )
        response["Events"][0]["userIdentity"] = {
            "principalId": "different-principal",
        }
        with self.assertRaisesRegex(
            collector.CollectorError,
            "response_unknown",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=second["slot"],
                response_raw=extractor.canonical_bytes(response),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        self.assertEqual(
            collector.status(
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )["status"],
            "UNKNOWN_INFLIGHT",
        )
        event = json.loads(
            (self.journal / "000002-finish.json").read_text("ascii")
        )
        self.assertEqual(
            base64.b64decode(event["payload_base64"]),
            collector._unknown_marker("OFFICIAL_RESPONSE_EXPORT_FAILED"),
        )

    def test_lookup_page_cannot_exceed_requested_event_limit(self):
        first = self.actiontrail["records"][0]
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            request_raw=decoded(first["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        response = extractor.decode_canonical_json(
            first["response_json_base64"],
            "fixture",
        )
        response["Events"] = [response["Events"][0]] * 51
        with self.assertRaisesRegex(
            collector.CollectorError,
            "response_unknown",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                response_raw=extractor.canonical_bytes(response),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )

    def test_clone_create_terminal_page_cannot_be_empty(self):
        for row in self.actiontrail["records"][:2]:
            self.invoke_pair(
                row["slot"],
                decoded(row["request_json_base64"]),
                decoded(row["response_json_base64"]),
            )
        create = self.actiontrail["records"][2]
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=create["slot"],
            request_raw=decoded(create["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        response = extractor.decode_canonical_json(
            create["response_json_base64"],
            "fixture",
        )
        response["Events"] = []
        with self.assertRaisesRegex(
            collector.CollectorError,
            "response_unknown",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=create["slot"],
                response_raw=extractor.canonical_bytes(response),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )

    def test_present_clone_response_is_unknown_before_source_query(self):
        for row in self.actiontrail["records"]:
            self.invoke_pair(
                row["slot"],
                decoded(row["request_json_base64"]),
                decoded(row["response_json_base64"]),
            )
        clone = self.provider["records"][0]
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=clone["slot"],
            request_raw=decoded(clone["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        response = extractor.decode_canonical_json(
            clone["response_json_base64"],
            "fixture",
        )
        response["Items"]["DBInstance"] = [{"DBInstanceId": CLONE_ID}]
        response["PageRecordCount"] = 1
        response["TotalRecordCount"] = 1
        with self.assertRaisesRegex(
            collector.CollectorError,
            "response_unknown",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=clone["slot"],
                response_raw=extractor.canonical_bytes(response),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )

    def test_terminal_cross_page_mismatch_is_recorded_unknown(self):
        first = self.actiontrail["records"][0]
        second = self.actiontrail["records"][1]
        response = extractor.decode_canonical_json(
            second["response_json_base64"],
            "fixture",
        )
        response["Events"][0]["userIdentity"] = {"principalId": "other"}
        second["response_json_base64"] = base64.b64encode(
            extractor.canonical_bytes(response)
        ).decode("ascii")
        self.invoke_pair(
            first["slot"],
            decoded(first["request_json_base64"]),
            decoded(first["response_json_base64"]),
        )
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=second["slot"],
            request_raw=decoded(second["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        with self.assertRaisesRegex(
            collector.CollectorError,
            "response_unknown",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=second["slot"],
                response_raw=decoded(second["response_json_base64"]),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        self.assertEqual(
            collector.status(
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )["status"],
            "UNKNOWN_INFLIGHT",
        )

    def test_aggregate_capture_budget_is_checked_on_each_finish(self):
        first = self.actiontrail["records"][0]
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            request_raw=decoded(first["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        with mock.patch.object(
            collector,
            "_capture_envelopes",
            return_value=(
                b"p" * collector.extractor.MAX_CAPTURE_BYTES,
                b"a" * collector.extractor.MAX_CAPTURE_BYTES,
            ),
        ), self.assertRaisesRegex(
            collector.CollectorError,
            "response_unknown",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                response_raw=decoded(first["response_json_base64"]),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        self.assertEqual(
            collector.status(
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )["status"],
            "UNKNOWN_INFLIGHT",
        )
        event = json.loads(
            (self.journal / "000001-finish.json").read_text("ascii")
        )
        self.assertEqual(
            base64.b64decode(event["payload_base64"]),
            collector._unknown_marker("OFFICIAL_RESPONSE_EXPORT_FAILED"),
        )

    def test_extra_inventory_symlink_and_hardlink_fail_closed(self):
        extra = self.journal / "extra"
        extra.write_text("x")
        extra.chmod(0o600)
        with self.assertRaisesRegex(
            collector.CollectorError, "journal_inventory"
        ):
            collector.status(
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        extra.unlink()
        link = self.journal / "000001-begin.json"
        link.symlink_to(self.authority / collector.ROOT_FILE)
        with self.assertRaises(collector.CollectorError):
            collector.status(
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )

    def test_wrong_directory_mode_is_rejected(self):
        self.journal.chmod(0o755)
        with self.assertRaisesRegex(
            collector.CollectorError, "directory_identity"
        ):
            collector.status(
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )

    def test_world_writable_parent_is_rejected(self):
        parent = self.journal.parent
        parent.chmod(0o777)
        try:
            with self.assertRaisesRegex(
                collector.CollectorError, "source_parent_identity"
            ):
                collector.status(
                    journal_directory=self.journal,
                    owner_uid=self.owner_uid,
                )
        finally:
            parent.chmod(0o700)

    def test_partial_event_write_is_not_treated_as_a_frozen_request(self):
        partial = self.journal / collector._event_writing_name(
            "000001-begin.json",
            "2026-08-17T00:00:00Z",
        )
        partial.write_bytes(b'{"incomplete":')
        partial.chmod(0o600)
        state = collector.status(
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        self.assertEqual(state["status"], "LOCAL_WRITE_RECOVERY_REQUIRED")
        self.assertEqual(state["recorded_request_count"], 0)

    def test_partial_finish_write_precedes_pending_status(self):
        first = self.actiontrail["records"][0]
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            request_raw=decoded(first["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        partial = self.journal / collector._event_writing_name(
            "000001-finish.json",
            "2026-08-17T00:00:01Z",
        )
        partial.write_bytes(b'{"incomplete":')
        partial.chmod(0o600)
        state = collector.status(
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        self.assertEqual(state["status"], "LOCAL_WRITE_RECOVERY_REQUIRED")
        self.assertEqual(state["recorded_request_count"], 1)
        self.assertEqual(state["recorded_response_count"], 0)

    def test_expired_pending_request_is_terminal_unknown_status(self):
        first = self.actiontrail["records"][0]
        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:00:00Z",
        ):
            collector.begin(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                request_raw=decoded(first["request_json_base64"]),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:15:01Z",
        ):
            state = collector.status(
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        self.assertEqual(state["status"], "REQUEST_EXPIRED_UNKNOWN")
        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:15:01Z",
        ), self.assertRaisesRegex(
            collector.CollectorError,
            "response_unknown",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                response_raw=decoded(first["response_json_base64"]),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        event = json.loads(
            (self.journal / "000001-finish.json").read_text("ascii")
        )
        self.assertEqual(
            base64.b64decode(event["payload_base64"]),
            collector._unknown_marker("OFFICIAL_RESPONSE_EXPORT_FAILED"),
        )

    def test_status_distinguishes_finalize_ready_and_installed(self):
        self.complete_journal()
        ready = collector.status(
            journal_directory=self.journal,
            authority_directory=self.authority,
            owner_uid=self.owner_uid,
        )
        self.assertEqual(ready["status"], "READY_TO_FINALIZE")
        collector.finalize(
            control_revision=CONTROL_REVISION,
            journal_directory=self.journal,
            authority_directory=self.authority,
            owner_uid=self.owner_uid,
        )
        installed = collector.status(
            journal_directory=self.journal,
            authority_directory=self.authority,
            owner_uid=self.owner_uid,
        )
        self.assertEqual(installed["status"], "CAPTURE_INSTALLED")

    def test_empty_journal_does_not_claim_a_request_is_frozen(self):
        state = collector.status(
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        self.assertEqual(
            state["status"],
            "EMPTY_JOURNAL_NO_REQUEST_FROZEN",
        )

    def test_explicit_unknown_closes_pending_without_raw_or_replay(self):
        first = self.actiontrail["records"][0]
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            request_raw=decoded(first["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        result = collector.mark_unknown(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            reason="TRANSPORT_TIMEOUT",
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        self.assertEqual(result["status"], "UNKNOWN_INFLIGHT")
        self.assertFalse(result["cloud_request_replay_allowed"])
        state = collector.status(
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        self.assertEqual(state["status"], "UNKNOWN_INFLIGHT")
        finish_event = json.loads(
            (self.journal / "000001-finish.json").read_text("ascii")
        )
        marker = json.loads(
            base64.b64decode(finish_event["payload_base64"])
        )
        self.assertEqual(marker["reason"], "TRANSPORT_TIMEOUT")
        self.assertFalse(marker["cloud_request_replay_allowed"])
        rendered = collector._canonical(finish_event)
        for value in (CLONE_ID, SOURCE_ID, SOURCE_NAME):
            self.assertNotIn(value.encode("ascii"), rendered)
        with self.assertRaisesRegex(
            collector.CollectorError,
            "journal_unknown",
        ):
            collector.begin(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                request_raw=decoded(first["request_json_base64"]),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )

    def test_empty_and_oversize_finish_stdin_dispatch_fixed_unknown(self):
        for raw, reason in (
            (b"", "NO_RESPONSE_BODY"),
            (b"x" * (collector.MAX_INPUT_BYTES + 1), "RESPONSE_BODY_OVERSIZE"),
        ):
            with self.subTest(reason=reason), mock.patch.object(
                collector.os,
                "geteuid",
                return_value=0,
            ), mock.patch.object(
                collector,
                "_validate_interpreter",
            ), mock.patch.object(
                collector,
                "mark_unknown",
                return_value={
                    "schema": collector.COLLECTOR_STATUS_SCHEMA,
                    "status": "UNKNOWN_INFLIGHT",
                },
            ) as marked, mock.patch.object(
                collector.sys,
                "stdin",
                mock.Mock(buffer=io.BytesIO(raw)),
            ), mock.patch.object(
                collector.sys,
                "stdout",
                io.StringIO(),
            ):
                code = collector.main([
                    "finish",
                    "--control-revision",
                    CONTROL_REVISION,
                    "--slot",
                    collector.COST_SLOT,
                ])
            self.assertEqual(code, 0)
            self.assertEqual(marked.call_args.kwargs["reason"], reason)

    def test_exclusive_writer_recovers_linked_complete_temp(self):
        raw = b'{"complete":true}\n'
        temporary = self.journal / ".recovery.json.writing"
        target = self.journal / "recovery.json"
        temporary.write_bytes(raw)
        temporary.chmod(0o600)
        os.link(temporary, target)
        descriptor = os.open(self.journal, os.O_RDONLY | os.O_DIRECTORY)
        try:
            collector._write_exclusive(
                descriptor,
                target.name,
                raw,
                self.owner_uid,
            )
        finally:
            os.close(descriptor)
        self.assertFalse(temporary.exists())
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(target.stat().st_nlink, 1)

    def test_event_writer_recovers_full_temp_with_original_timestamp(self):
        first = self.actiontrail["records"][0]
        request = decoded(first["request_json_base64"])
        response = decoded(first["response_json_base64"])
        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:00:01Z",
        ), mock.patch.object(
            collector.os,
            "link",
            side_effect=OSError("simulated crash before publish"),
        ), self.assertRaisesRegex(
            collector.CollectorError,
            "write_failed",
        ):
            collector.begin(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                request_raw=request,
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:00:02Z",
        ):
            collector.begin(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                request_raw=request,
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        begin_event = json.loads(
            (self.journal / "000001-begin.json").read_text("ascii")
        )
        self.assertEqual(
            begin_event["recorded_at_utc"],
            "2026-08-17T00:00:01Z",
        )

        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:00:03Z",
        ), mock.patch.object(
            collector.os,
            "link",
            side_effect=OSError("simulated crash before publish"),
        ), self.assertRaisesRegex(
            collector.CollectorError,
            "write_failed",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                response_raw=response,
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:16:04Z",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                response_raw=response,
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        finish_event = json.loads(
            (self.journal / "000001-finish.json").read_text("ascii")
        )
        self.assertEqual(
            finish_event["recorded_at_utc"],
            "2026-08-17T00:00:03Z",
        )

    def test_event_writer_recovers_partial_inside_timestamp_value(self):
        first = self.actiontrail["records"][0]
        request = decoded(first["request_json_base64"])
        recorded_at = "2026-08-17T00:00:01.123456Z"
        value = collector._event_value(
            control_revision=CONTROL_REVISION,
            sequence=1,
            phase="begin",
            slot=first["slot"],
            recorded_at_utc=recorded_at,
            payload=request,
            source_hashes={**self.source_hashes, **self.runtime_binding},
            outcome="REQUEST_FROZEN",
        )
        raw = collector._canonical(value)
        marker = b'"recorded_at_utc":"2026-08-17T00:00'
        cutoff = raw.index(marker) + len(marker)
        partial = self.journal / collector._event_writing_name(
            "000001-begin.json",
            recorded_at,
        )
        partial.write_bytes(raw[:cutoff])
        partial.chmod(0o600)
        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:00:02Z",
        ):
            collector.begin(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                request_raw=request,
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        event = json.loads(
            (self.journal / "000001-begin.json").read_text("ascii")
        )
        self.assertEqual(event["recorded_at_utc"], recorded_at)

    def test_operation_retry_recovers_publish_before_temp_unlink(self):
        first = self.actiontrail["records"][0]
        request = decoded(first["request_json_base64"])
        response = decoded(first["response_json_base64"])
        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:00:01Z",
        ), mock.patch.object(
            collector.os,
            "unlink",
            side_effect=OSError("simulated crash after publish"),
        ), self.assertRaisesRegex(
            collector.CollectorError,
            "write_failed",
        ):
            collector.begin(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                request_raw=request,
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:00:02Z",
        ):
            begin_result = collector.begin(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                request_raw=request,
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        self.assertEqual(begin_result["status"], "REQUEST_FROZEN")

        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:00:03Z",
        ), mock.patch.object(
            collector.os,
            "unlink",
            side_effect=OSError("simulated crash after publish"),
        ), self.assertRaisesRegex(
            collector.CollectorError,
            "write_failed",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                response_raw=response,
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        finish_result = collector.finish(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            response_raw=response,
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        self.assertEqual(finish_result["status"], "RESPONSE_RECORDED")

        unknown_journal = (
            Path(self.temporary.name) / "unknown-journal"
        ).resolve()
        unknown_journal.mkdir(mode=0o700)
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            request_raw=request,
            journal_directory=unknown_journal,
            owner_uid=self.owner_uid,
        )
        with mock.patch.object(
            collector.os,
            "unlink",
            side_effect=OSError("simulated crash after publish"),
        ), self.assertRaisesRegex(
            collector.CollectorError,
            "write_failed",
        ):
            collector.mark_unknown(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                reason="TRANSPORT_TIMEOUT",
                journal_directory=unknown_journal,
                owner_uid=self.owner_uid,
            )
        unknown_result = collector.mark_unknown(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            reason="TRANSPORT_TIMEOUT",
            journal_directory=unknown_journal,
            owner_uid=self.owner_uid,
        )
        self.assertEqual(unknown_result["status"], "UNKNOWN_INFLIGHT")
        self.assertFalse(unknown_result["cloud_request_replay_allowed"])

    def test_create_terminal_retry_validates_the_frozen_finish_time(self):
        for index, row in enumerate(self.actiontrail["records"][:2]):
            with mock.patch.object(
                collector,
                "_utc_now",
                side_effect=(
                    f"2026-08-17T00:00:0{index * 2}Z",
                    f"2026-08-17T00:00:0{index * 2 + 1}Z",
                ),
            ):
                self.invoke_pair(
                    row["slot"],
                    decoded(row["request_json_base64"]),
                    decoded(row["response_json_base64"]),
                )
        create = self.actiontrail["records"][2]
        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:00:04Z",
        ):
            collector.begin(
                control_revision=CONTROL_REVISION,
                slot=create["slot"],
                request_raw=decoded(create["request_json_base64"]),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:00:05Z",
        ), mock.patch.object(
            collector.os,
            "link",
            side_effect=OSError("simulated crash before publish"),
        ), self.assertRaisesRegex(
            collector.CollectorError,
            "write_failed",
        ):
            collector.finish(
                control_revision=CONTROL_REVISION,
                slot=create["slot"],
                response_raw=decoded(create["response_json_base64"]),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:20:05Z",
        ):
            result = collector.finish(
                control_revision=CONTROL_REVISION,
                slot=create["slot"],
                response_raw=decoded(create["response_json_base64"]),
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        self.assertEqual(result["status"], "RESPONSE_RECORDED")
        event = json.loads(
            (self.journal / "000003-finish.json").read_text("ascii")
        )
        self.assertEqual(event["recorded_at_utc"], "2026-08-17T00:00:05Z")

    def test_unknown_writer_recovers_full_temp_without_request_replay(self):
        first = self.actiontrail["records"][0]
        collector.begin(
            control_revision=CONTROL_REVISION,
            slot=first["slot"],
            request_raw=decoded(first["request_json_base64"]),
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:00:05Z",
        ), mock.patch.object(
            collector.os,
            "link",
            side_effect=OSError("simulated crash before publish"),
        ), self.assertRaisesRegex(
            collector.CollectorError,
            "write_failed",
        ):
            collector.mark_unknown(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                reason="TRANSPORT_TIMEOUT",
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        with mock.patch.object(
            collector,
            "_utc_now",
            return_value="2026-08-17T00:00:06Z",
        ):
            result = collector.mark_unknown(
                control_revision=CONTROL_REVISION,
                slot=first["slot"],
                reason="TRANSPORT_TIMEOUT",
                journal_directory=self.journal,
                owner_uid=self.owner_uid,
            )
        self.assertEqual(result["status"], "UNKNOWN_INFLIGHT")
        self.assertFalse(result["cloud_request_replay_allowed"])
        event = json.loads(
            (self.journal / "000001-finish.json").read_text("ascii")
        )
        self.assertEqual(event["recorded_at_utc"], "2026-08-17T00:00:05Z")

    def test_stdout_status_never_contains_raw_identifiers(self):
        request = decoded(
            self.actiontrail["records"][0]["request_json_base64"]
        )
        result = collector.begin(
            control_revision=CONTROL_REVISION,
            slot=collector.COST_SLOT,
            request_raw=request,
            journal_directory=self.journal,
            owner_uid=self.owner_uid,
        )
        rendered = collector._canonical(result)
        for value in (CLONE_ID, SOURCE_ID, SOURCE_NAME):
            self.assertNotIn(value.encode("ascii"), rendered)
        self.assertEqual(result["raw_value_emitted_count"], 0)

    def test_cli_has_no_path_time_or_identity_parameters(self):
        source = (ROOT / collector.COLLECTOR_REF).read_text()
        for forbidden in (
            "--authority-directory",
            "--journal-directory",
            "--started-at",
            "--completed-at",
            "--observed-at",
            "--db-instance-id",
            "--access-key",
            "--secret",
        ):
            self.assertNotIn(forbidden, source)
        for transport in (
            "import requests",
            "import socket",
            "urllib.request",
            "http.client",
            "subprocess.",
        ):
            self.assertNotIn(transport, source)

    def test_main_requires_root_and_emits_fixed_error_only(self):
        output = io.StringIO()
        with mock.patch.object(collector.os, "geteuid", return_value=501), mock.patch.object(
            collector.sys, "stderr", output
        ):
            code = collector.main(["status"])
        self.assertEqual(code, 2)
        value = json.loads(output.getvalue())
        self.assertEqual(value["code"], "root_required")
        self.assertEqual(value["raw_value_emitted_count"], 0)

    def test_main_rejects_untrusted_interpreter_contract(self):
        output = io.StringIO()
        with mock.patch.object(collector.os, "geteuid", return_value=0), mock.patch.object(
            collector,
            "_validate_interpreter",
            side_effect=collector.CollectorError("interpreter_contract"),
        ), mock.patch.object(collector.sys, "stderr", output):
            code = collector.main(["status"])
        self.assertEqual(code, 2)
        value = json.loads(output.getvalue())
        self.assertEqual(value["code"], "interpreter_contract")

    def test_unfinalized_cli_rejects_before_accepting_response_bytes(self):
        output = io.StringIO()
        with mock.patch.object(
            collector,
            "FixedArgumentParser",
        ) as parser, mock.patch.object(
            collector.os,
            "geteuid",
        ) as geteuid, mock.patch.object(
            collector,
            "_validate_interpreter",
        ) as interpreter, mock.patch.object(
            collector.authority,
            "AUTHORITY_V2_FINALIZED",
            False,
        ), mock.patch.object(
            collector,
            "_stdin_bytes",
        ) as stdin_reader, mock.patch.object(
            collector.sys,
            "stderr",
            output,
        ):
            code = collector.main([
                "finish",
                "--control-revision",
                CONTROL_REVISION,
                "--slot",
                collector.COST_SLOT,
            ])
        self.assertEqual(code, 2)
        parser.assert_not_called()
        geteuid.assert_not_called()
        interpreter.assert_not_called()
        stdin_reader.assert_not_called()
        value = json.loads(output.getvalue())
        self.assertEqual(value["code"], "authority_v2_not_finalized")
        self.assertEqual(value["journal_write_count"], 0)
        self.assertEqual(value["cloud_call_count"], 0)
        self.assertEqual(value["database_connection_count"], 0)

    def test_cli_argument_error_and_tty_are_fixed_and_non_sensitive(self):
        sentinel = "must-not-appear-in-fixed-error"
        output = io.StringIO()
        with mock.patch.object(collector.sys, "stderr", output):
            code = collector.main([
                "begin",
                "--control-revision",
                CONTROL_REVISION,
                "--slot",
                sentinel,
            ])
        self.assertEqual(code, 2)
        self.assertNotIn(sentinel, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["code"], "arguments")

        tty_buffer = mock.Mock()
        tty_buffer.isatty.return_value = True
        output = io.StringIO()
        with mock.patch.object(
            collector.os,
            "geteuid",
            return_value=0,
        ), mock.patch.object(
            collector,
            "_validate_interpreter",
        ), mock.patch.object(
            collector.sys,
            "stdin",
            mock.Mock(buffer=tty_buffer),
        ), mock.patch.object(
            collector.sys,
            "stderr",
            output,
        ):
            code = collector.main([
                "begin",
                "--control-revision",
                CONTROL_REVISION,
                "--slot",
                collector.COST_SLOT,
            ])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["code"], "stdin_tty")

    def test_inert_production_entrypoint_blocks_before_help_and_bytecode(self):
        runtime = Path(self.temporary.name) / "runtime"
        runtime.mkdir(mode=0o700)
        for ref in (
            collector.COLLECTOR_REF,
            collector.EXTRACTOR_REF,
            collector.AUTHORITY_REF,
        ):
            source = ROOT / ref
            target = runtime / source.name
            target.write_bytes(source.read_bytes())
            target.chmod(0o600)
        result = subprocess.run(
            [
                "/usr/bin/python3",
                "-O",
                "-E",
                "-S",
                "-B",
                str(runtime / Path(collector.COLLECTOR_REF).name),
                "--help",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 2, result.stderr.decode())
        self.assertEqual(
            json.loads(result.stderr),
            collector._blocked_status("authority_v2_not_finalized"),
        )
        self.assertEqual(result.stdout, b"")
        self.assertFalse((runtime / "__pycache__").exists())


if __name__ == "__main__":
    unittest.main()
