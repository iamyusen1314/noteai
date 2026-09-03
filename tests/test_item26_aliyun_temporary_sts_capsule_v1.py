from __future__ import annotations

import hashlib
import hmac
import importlib.util
import copy
import dataclasses
import json
import math
import os
import pickle
import socket
import stat
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "item26_aliyun_temporary_sts_capsule_v1.py"
MODULE_NAME = "item26_aliyun_temporary_sts_capsule_v1_tested"
WALL = 1_700_000_000
MONO = 40_000_000_000
LIFETIME = 4_000
ACCOUNT_DOMAIN = b"noteai.item26.account-id-commitment.v1\x00"
PRINCIPAL_DOMAIN = b"noteai.item26.principal-id-commitment.v1\x00"


def load_module() -> tuple[types.ModuleType, bytes]:
    raw = SOURCE.read_bytes()
    spec = importlib.util.spec_from_file_location(MODULE_NAME, SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("module fixture unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module, raw


def refresh_expected_commitments(value: dict[str, object]) -> dict[str, object]:
    key = value["commitment_key"]
    account = value["account_identity"]
    principal = value["principal_identity"]
    if type(key) is not bytearray or type(account) is not bytearray or type(principal) is not bytearray:
        raise RuntimeError("invalid private fixture")
    value["expected_account_commitment_hmac_sha256"] = hmac.new(
        bytes(key),
        ACCOUNT_DOMAIN + len(account).to_bytes(8, "big") + bytes(account),
        hashlib.sha256,
    ).hexdigest()
    value["expected_principal_commitment_hmac_sha256"] = hmac.new(
        bytes(key),
        PRINCIPAL_DOMAIN + len(principal).to_bytes(8, "big") + bytes(principal),
        hashlib.sha256,
    ).hexdigest()
    return value


def private_inputs(*, lifetime: int = LIFETIME) -> dict[str, object]:
    value = {
        "access_key_id": bytearray(b"S" + b"TS." + b"A" * 20),
        "access_key_secret": bytearray(b"k" * 40),
        "security_token": bytearray(b"t" * 240),
        "expiration_unix": WALL + lifetime,
        "account_identity": bytearray(b"1" * 16),
        "principal_identity": bytearray(b"acs:ram::" + b"2" * 16 + b":role/test"),
        "commitment_key": bytearray(range(32)),
        "wall_now_unix": WALL,
        "monotonic_now_ns": MONO,
    }
    return refresh_expected_commitments(value)


def build_capsule(module: types.ModuleType, *, lifetime: int = LIFETIME):
    values = private_inputs(lifetime=lifetime)
    capsule = module.build_root_custody_capsule(**values)
    return capsule, values


def fake_stat(*, inode: int = 10) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        st_mode=stat.S_IFSOCK | 0o600,
        st_dev=7,
        st_ino=inode,
    )


def fake_fd_dependencies(
    module: types.ModuleType,
    *,
    flags: int | None = None,
    inode_for_fd=None,
    probe_patch: dict[str, object] | None = None,
):
    selected_flags = os.O_RDWR if flags is None else flags

    def fstat_fn(fd: int):
        inode = inode_for_fd(fd) if inode_for_fd is not None else fd + 100
        return fake_stat(inode=inode)

    def getfl_fn(_fd: int, _operation: int) -> int:
        return selected_flags

    def socket_probe(_fd: int, direction: str):
        value = {
            "family": socket.AF_UNIX,
            "kind": socket.SOCK_STREAM,
            "local_name": "",
            "peer_name": "",
            "direction": direction,
        }
        if probe_patch:
            value.update(probe_patch)
        return value

    return {
        "fstat_fn": fstat_fn,
        "getfl_fn": getfl_fn,
        "isatty_fn": lambda _fd: False,
        "socket_probe": socket_probe,
    }


def valid_inventory(module: types.ModuleType):
    contract = module.root_custody_contract()
    live = {
        "ancestor_lstat": {},
        "file_lstat": {},
        "root_directory_entries": {},
    }
    receipts = {}
    calls: list[tuple[str, int, int]] = []
    listing_calls: list[tuple[str, int]] = []
    for index, (path, mode) in enumerate(
        contract["ancestor_directory_modes"].items(),
        start=1,
    ):
        live["ancestor_lstat"][path] = {
            "st_mode": stat.S_IFDIR | mode,
            "uid": 0,
            "gid": 0,
            "nlink": 1,
            "dev": 7,
            "ino": index,
        }
    for path, expected_names in contract["root_exact_entry_names"].items():
        root_stat = dict(live["ancestor_lstat"][path])

        def lister(
            selected_path: str,
            selected_flags: int,
            *,
            root_stat=root_stat,
            expected_names=expected_names,
        ):
            listing_calls.append((selected_path, selected_flags))
            return {
                "fd_stat": dict(root_stat),
                "entry_names": tuple(expected_names),
            }

        live["root_directory_entries"][path] = (
            module._capture_root_directory_listing(path, lister=lister)
        )
    for index, path in enumerate(contract["file_paths"], start=100):
        payload = ("inventory-payload-" + str(index)).encode("ascii")
        digest = hashlib.sha256(payload).hexdigest()
        pre = {
            "st_mode": stat.S_IFREG | 0o600,
            "uid": 0,
            "gid": 0,
            "nlink": 1,
            "dev": 9,
            "ino": index,
            "size": 0,
        }
        post = dict(pre)
        post["size"] = len(payload)

        def creator(
            selected_path: str,
            selected_flags: int,
            selected_mode: int,
            *,
            pre=pre,
            post=post,
            digest=digest,
        ):
            calls.append((selected_path, selected_flags, selected_mode))
            return {
                "pre_fd_stat": dict(pre),
                "post_fd_stat": dict(post),
                "pre_content_sha256": hashlib.sha256(b"").hexdigest(),
                "post_content_sha256": digest,
            }

        receipts[path] = module._capture_exclusive_creation_receipt(
            path,
            creator=creator,
        )
        live["file_lstat"][path] = {**post, "sha256": digest}
    return live, receipts, calls, listing_calls


class Item26TemporaryStsCapsuleSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module, cls.raw = load_module()

    @classmethod
    def tearDownClass(cls) -> None:
        sys.modules.pop(MODULE_NAME, None)

    def test_01_source_status_is_complete_but_every_action_is_closed(self) -> None:
        status = self.module.source_only_status()
        self.assertEqual(
            status["status"],
            "SOURCE_ONLY_IMPLEMENTATION_COMPLETE_NOT_AUTHORIZED",
        )
        self.assertIs(status["implementation_complete"], True)
        self.assertIs(status["authorizes_execution"], False)
        self.assertIs(status["operational_ready"], False)
        self.assertEqual(status["credential_capsule_status"], "NOT_PROVISIONED")
        self.assertEqual(set(status["execution_gates"]), set(self.module.EXECUTION_GATES))
        self.assertTrue(all(value is False for value in status["execution_gates"].values()))
        for key, value in status.items():
            if key.endswith("_count"):
                self.assertEqual(value, 0, key)
        self.assertEqual(status["authorized_cny"], "0.00")
        self.assertEqual(status["incurred_cny"], "0.00")

    def test_02_main_refuses_without_touching_argument_or_io(self) -> None:
        class Poison:
            def __getattribute__(self, _name):
                raise AssertionError("argument inspected")

            def __iter__(self):
                raise AssertionError("argument iterated")

            def __repr__(self):
                raise AssertionError("argument formatted")

        with mock.patch.object(self.module.os, "read", side_effect=AssertionError("read")), \
             mock.patch.object(self.module.os, "write", side_effect=AssertionError("write")), \
             mock.patch.object(self.module.os, "open", side_effect=AssertionError("open")), \
             mock.patch.object(self.module.os, "fstat", side_effect=AssertionError("fstat")), \
             mock.patch.object(self.module.os, "dup", side_effect=AssertionError("dup")):
            self.assertEqual(self.module.main(Poison()), 2)

    def test_03_source_has_no_execution_dependency_or_user_config_path(self) -> None:
        text = self.raw.decode("utf-8")
        for forbidden in (
            "import subprocess",
            "from subprocess",
            "http.client",
            "urllib.request",
            ".aliyun/config",
            "expanduser(",
            "getenv(",
            "environ[",
        ):
            self.assertNotIn(forbidden, text)
        self.assertEqual(text.count("def main("), 1)
        self.assertNotIn("sys.stdout", text)
        self.assertNotIn("sys.stderr", text)

    def test_04_fixed_schemas_and_custody_roots_are_exact(self) -> None:
        self.assertEqual(
            self.module.INNER_ENVELOPE_SCHEMA,
            "noteai.item26.aliyun-temporary-sts-envelope.v1",
        )
        self.assertEqual(
            self.module.INTERFACE_SCHEMA,
            "noteai.item26.m1-root-custody-temporary-sts-interface.v1",
        )
        self.assertEqual(self.module.PROFILE_NAME, "noteai-item26-m1")
        self.assertEqual(self.module.REGION_ID, "cn-shenzhen")
        self.assertEqual(
            self.module.RUNTIME_ROOT,
            "/Library/Application Support/NoteAI/"
            "item26-manual-cost-stop-v2-m1-credential-runtime",
        )
        self.assertEqual(
            self.module.CUSTODY_ROOT,
            "/Library/Application Support/NoteAI/"
            "item26-manual-cost-stop-v2-m1-credential-custody",
        )

    def test_05_canonical_json_is_ascii_sorted_exact_and_rejects_nonfinite(self) -> None:
        self.assertEqual(self.module.canonical_json({"z": 1, "a": "\u96ea"}), b'{"a":"\\u96ea","z":1}\n')
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaisesRegex(self.module.CapsuleError, "^json_canonical$"):
                self.module.canonical_json({"x": value})

    def test_06_strict_json_rejects_duplicate_nonfinite_nul_and_oversize(self) -> None:
        parser = self.module._strict_json_object
        invalid = (
            b'{"x":1,"x":2}\n',
            b'{"x":NaN}\n',
            b'{"x":Infinity}\n',
            b'{"x":"a\x00b"}\n',
            b"x" * 33,
        )
        for raw in invalid:
            with self.subTest(raw=raw[:12]):
                with self.assertRaises(self.module.CapsuleError):
                    parser(raw, 32, "fixture")

    def test_07_strict_json_rejects_excessive_depth_and_integer_width(self) -> None:
        nested: object = 1
        for _ in range(self.module.MAX_JSON_DEPTH + 2):
            nested = [nested]
        raw = self.module.canonical_json({"x": nested})
        with self.assertRaisesRegex(self.module.CapsuleError, "^json_depth$"):
            self.module._strict_json_object(raw, len(raw), "fixture")
        huge = b'{"x":' + b"9" * (self.module.MAX_JSON_INTEGER_DIGITS + 1) + b"}\n"
        with self.assertRaisesRegex(self.module.CapsuleError, "^json_number$"):
            self.module._strict_json_object(huge, len(huge), "fixture")

    def test_08_build_consumes_every_private_input_on_success(self) -> None:
        capsule, supplied = build_capsule(self.module)
        try:
            for key in (
                "access_key_id",
                "access_key_secret",
                "security_token",
                "account_identity",
                "principal_identity",
                "commitment_key",
            ):
                value = supplied[key]
                self.assertIs(type(value), bytearray)
                self.assertTrue(all(byte == 0 for byte in value), key)
        finally:
            capsule.scrub()

    def test_09_build_consumes_private_inputs_on_failure_and_suppresses_values(self) -> None:
        supplied = private_inputs(lifetime=100)
        markers = [bytes(value) for value in supplied.values() if type(value) is bytearray]
        with self.assertRaisesRegex(self.module.CapsuleError, "^credential_validity$") as caught:
            self.module.build_root_custody_capsule(**supplied)
        rendered = str(caught.exception) + repr(caught.exception)
        for marker in markers:
            self.assertNotIn(marker.decode("ascii", "ignore"), rendered)
        for value in supplied.values():
            if type(value) is bytearray:
                self.assertTrue(all(byte == 0 for byte in value))
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)

    def test_10_inner_envelope_is_exact_canonical_and_adapter_compatible(self) -> None:
        capsule, _ = build_capsule(self.module)
        issued = capsule.issue_for_begin(
            wall_now_unix=WALL,
            monotonic_now_ns=MONO,
        )
        raw = issued.take_m1_supplier_mapping()["envelope"]
        try:
            value = json.loads(bytes(raw))
            self.assertEqual(
                set(value),
                {
                    "schema",
                    "source",
                    "profile_name",
                    "region_id",
                    "access_key_id",
                    "access_key_secret",
                    "security_token",
                    "expiration_unix",
                },
            )
            self.assertEqual(value["schema"], self.module.INNER_ENVELOPE_SCHEMA)
            self.assertEqual(value["source"], self.module.INNER_ENVELOPE_SOURCE)
            self.assertEqual(value["profile_name"], "noteai-item26-m1")
            self.assertEqual(value["region_id"], "cn-shenzhen")
            self.assertEqual(self.module.canonical_json(value), bytes(raw))
            summary = self.module.validate_inner_envelope(
                raw,
                now_unix=WALL,
                minimum_remaining_seconds=1860,
            )
            self.assertEqual(summary.remaining_seconds, LIFETIME)
            self.assertEqual(
                summary.credential_envelope_sha256,
                hashlib.sha256(bytes(raw)).hexdigest(),
            )
        finally:
            self.module.scrub_bytearray(raw)
            issued.scrub()
            capsule.scrub()

    def test_11_inner_validator_rejects_noncanonical_and_wrong_exact_contract(self) -> None:
        capsule, _ = build_capsule(self.module)
        issued = capsule.issue_for_begin(wall_now_unix=WALL, monotonic_now_ns=MONO)
        raw = issued.take_m1_supplier_mapping()["envelope"]
        try:
            with self.assertRaisesRegex(self.module.CapsuleError, "^credential_canonical$"):
                self.module.validate_inner_envelope(
                    raw[:-1],
                    now_unix=WALL,
                    minimum_remaining_seconds=1860,
                )
            value = json.loads(bytes(raw))
            value["extra"] = 0
            altered = self.module.canonical_json(value)
            with self.assertRaisesRegex(self.module.CapsuleError, "^credential_contract$"):
                self.module.validate_inner_envelope(
                    altered,
                    now_unix=WALL,
                    minimum_remaining_seconds=1860,
                )
        finally:
            self.module.scrub_bytearray(raw)
            issued.scrub()
            capsule.scrub()

    def test_12_inner_validator_rejects_bool_float_and_wrong_identity(self) -> None:
        capsule, _ = build_capsule(self.module)
        issued = capsule.issue_for_begin(wall_now_unix=WALL, monotonic_now_ns=MONO)
        raw = issued.take_m1_supplier_mapping()["envelope"]
        try:
            base = json.loads(bytes(raw))
            variants = []
            for invalid_expiry in (True, float(WALL + LIFETIME)):
                value = dict(base)
                value["expiration_unix"] = invalid_expiry
                variants.append(self.module.canonical_json(value))
            for field, wrong in (
                ("schema", "wrong"),
                ("source", "wrong"),
                ("profile_name", "wrong"),
                ("region_id", "wrong"),
                ("access_key_id", "not-temporary"),
            ):
                value = dict(base)
                value[field] = wrong
                variants.append(self.module.canonical_json(value))
            for altered in variants:
                with self.subTest(altered=hashlib.sha256(altered).hexdigest()):
                    with self.assertRaises(self.module.CapsuleError):
                        self.module.validate_inner_envelope(
                            altered,
                            now_unix=WALL,
                            minimum_remaining_seconds=1860,
                        )
        finally:
            self.module.scrub_bytearray(raw)
            issued.scrub()
            capsule.scrub()

    def test_13_interface_projection_is_exact_secret_free_mapping(self) -> None:
        capsule, _ = build_capsule(self.module)
        try:
            value = capsule.project_m1_interface(
                wall_now_unix=WALL,
                monotonic_now_ns=MONO,
            )
            self.assertEqual(
                set(value),
                {
                    "schema",
                    "status",
                    "account_binding_sha256",
                    "minimum_remaining_validity_seconds",
                    "credential_payload_exposed",
                    "oauth_refresh_count",
                    "oauth_configure_count",
                },
            )
            self.assertEqual(value["schema"], self.module.INTERFACE_SCHEMA)
            self.assertEqual(value["status"], "ROOT_CUSTODY_TEMPORARY_STS_READY")
            self.assertEqual(value["minimum_remaining_validity_seconds"], LIFETIME)
            self.assertIs(value["credential_payload_exposed"], False)
            self.assertEqual(value["oauth_refresh_count"], 0)
            self.assertEqual(value["oauth_configure_count"], 0)
            encoded = self.module.canonical_json(value)
            self.assertNotIn(b"STS.", encoded)
            self.assertNotIn(b"security_token", encoded)
        finally:
            capsule.scrub()

    def test_14_initial_probe_is_exact_capture_core_mapping(self) -> None:
        capsule, _ = build_capsule(self.module)
        try:
            value = capsule.initial_probe(wall_now_unix=WALL, monotonic_now_ns=MONO)
            self.assertEqual(
                set(value),
                {
                    "remaining_seconds",
                    "account_binding_sha256",
                    "credential_envelope_sha256",
                    "refresh_count",
                    "configure_count",
                },
            )
            self.assertEqual(value["remaining_seconds"], LIFETIME)
            self.assertEqual(value["refresh_count"], 0)
            self.assertEqual(value["configure_count"], 0)
            self.assertRegex(value["account_binding_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(value["credential_envelope_sha256"], r"^[0-9a-f]{64}$")
        finally:
            capsule.scrub()

    def test_15_ttl_is_integer_nonincreasing_and_clock_regression_cannot_raise_it(self) -> None:
        capsule, _ = build_capsule(self.module)
        issued = []
        try:
            issued.append(capsule.issue_for_begin(
                wall_now_unix=WALL + 10,
                monotonic_now_ns=MONO + 10_000_000_000,
            ))
            issued.append(capsule.issue_for_begin(
                wall_now_unix=WALL - 500,
                monotonic_now_ns=MONO + 20_000_000_000,
            ))
            issued.append(capsule.issue_for_begin(
                wall_now_unix=WALL + 100,
                monotonic_now_ns=MONO + 21_000_000_000,
            ))
            remaining = [row.remaining_seconds for row in issued]
            self.assertEqual(remaining, [3990, 3980, 3900])
            self.assertTrue(all(type(value) is int for value in remaining))
            self.assertEqual(capsule.round_count, 3)
        finally:
            for row in issued:
                row.scrub()
            capsule.scrub()

    def test_16_subsecond_monotonic_elapsed_is_ceiled_and_never_overstates_ttl(self) -> None:
        capsule, _ = build_capsule(self.module)
        issued = capsule.issue_for_begin(
            wall_now_unix=WALL,
            monotonic_now_ns=MONO + 1,
        )
        try:
            self.assertEqual(issued.remaining_seconds, LIFETIME - 1)
        finally:
            issued.scrub()
            capsule.scrub()

    def test_17_initial_and_per_begin_thresholds_are_exact(self) -> None:
        for lifetime, accepted in ((1859, False), (1860, True), (86400, True), (86401, False)):
            supplied = private_inputs(lifetime=lifetime)
            if accepted:
                capsule = self.module.build_root_custody_capsule(**supplied)
                capsule.scrub()
            else:
                with self.assertRaisesRegex(self.module.CapsuleError, "^credential_validity$"):
                    self.module.build_root_custody_capsule(**supplied)
        capsule, _ = build_capsule(self.module, lifetime=1860)
        try:
            with self.assertRaisesRegex(self.module.CapsuleError, "^credential_validity$"):
                capsule.issue_for_begin(
                    wall_now_unix=WALL + 901,
                    monotonic_now_ns=MONO + 901_000_000_000,
                )
            issued = capsule.issue_for_begin(
                wall_now_unix=WALL + 900,
                monotonic_now_ns=MONO + 900_000_000_000,
            )
            self.assertEqual(issued.remaining_seconds, 960)
            issued.scrub()
        finally:
            capsule.scrub()

    def test_18_clock_and_expiration_bool_or_regression_fail_closed(self) -> None:
        supplied = private_inputs()
        supplied["expiration_unix"] = True
        with self.assertRaises(self.module.CapsuleError):
            self.module.build_root_custody_capsule(**supplied)
        capsule, _ = build_capsule(self.module)
        try:
            for wall, mono in ((True, MONO), (WALL, True), (WALL, MONO - 1)):
                with self.subTest(wall=wall, mono=mono):
                    with self.assertRaisesRegex(self.module.CapsuleError, "^credential_clock$"):
                        capsule.issue_for_begin(
                            wall_now_unix=wall,
                            monotonic_now_ns=mono,
                        )
        finally:
            capsule.scrub()

    def test_19_envelope_hash_and_account_binding_are_constant_for_all_rounds(self) -> None:
        capsule, _ = build_capsule(self.module)
        probe = capsule.initial_probe(wall_now_unix=WALL, monotonic_now_ns=MONO)
        issued = []
        mappings = []
        try:
            for second in (1, 2, 30, 300):
                row = capsule.issue_for_begin(
                    wall_now_unix=WALL + second,
                    monotonic_now_ns=MONO + second * 1_000_000_000,
                )
                issued.append(row)
                mapping = row.take_m1_supplier_mapping()
                mappings.append(mapping)
                self.assertEqual(
                    mapping["credential_envelope_sha256"],
                    probe["credential_envelope_sha256"],
                )
                self.assertEqual(
                    mapping["account_binding_sha256"],
                    probe["account_binding_sha256"],
                )
                self.assertEqual(
                    hashlib.sha256(bytes(mapping["envelope"])).hexdigest(),
                    probe["credential_envelope_sha256"],
                )
                self.assertEqual(mapping["refresh_count"], 0)
                self.assertEqual(mapping["configure_count"], 0)
            self.assertEqual(len({id(row["envelope"]) for row in mappings}), 4)
        finally:
            for mapping in mappings:
                self.module.scrub_bytearray(mapping["envelope"])
            for row in issued:
                row.scrub()
            capsule.scrub()

    def test_20_issued_transfers_do_not_alias_master_or_other_round(self) -> None:
        capsule, _ = build_capsule(self.module)
        first = capsule.issue_for_begin(wall_now_unix=WALL, monotonic_now_ns=MONO)
        second = capsule.issue_for_begin(wall_now_unix=WALL, monotonic_now_ns=MONO)
        first_raw = first.take_m1_supplier_mapping()["envelope"]
        second_raw = second.take_m1_supplier_mapping()["envelope"]
        try:
            first_raw[:] = b"\x00" * len(first_raw)
            self.assertNotEqual(first_raw, second_raw)
            first.scrub()
            self.assertEqual(
                capsule.credential_envelope_sha256,
                hashlib.sha256(bytes(second_raw)).hexdigest(),
            )
            third = capsule.issue_for_begin(wall_now_unix=WALL, monotonic_now_ns=MONO)
            try:
                third_raw = third.take_m1_supplier_mapping()["envelope"]
                try:
                    self.assertEqual(third_raw, second_raw)
                finally:
                    self.module.scrub_bytearray(third_raw)
            finally:
                third.scrub()
        finally:
            self.module.scrub_bytearray(first_raw)
            self.module.scrub_bytearray(second_raw)
            first.scrub()
            second.scrub()
            capsule.scrub()

    def test_21_commitments_are_domain_separated_hmac_and_aggregate_is_canonical(self) -> None:
        key = bytearray(range(32))
        account = bytearray(b"account-fixture")
        principal = bytearray(b"principal-fixture")
        account_result = self.module._commitment(
            key,
            self.module._ACCOUNT_DOMAIN,
            account,
        )
        principal_result = self.module._commitment(
            key,
            self.module._PRINCIPAL_DOMAIN,
            principal,
        )
        expected_account = hmac.new(
            bytes(key),
            self.module._ACCOUNT_DOMAIN
            + len(account).to_bytes(8, "big")
            + bytes(account),
            hashlib.sha256,
        ).hexdigest()
        expected_principal = hmac.new(
            bytes(key),
            self.module._PRINCIPAL_DOMAIN
            + len(principal).to_bytes(8, "big")
            + bytes(principal),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(account_result, expected_account)
        self.assertEqual(principal_result, expected_principal)
        self.assertNotEqual(account_result, principal_result)
        aggregate = {
            "account_commitment_hmac_sha256": account_result,
            "principal_commitment_hmac_sha256": principal_result,
            "schema": self.module.ACCOUNT_BINDING_SCHEMA,
        }
        self.assertEqual(
            self.module._account_binding(account_result, principal_result),
            hashlib.sha256(self.module.canonical_json(aggregate)).hexdigest(),
        )

    def test_22_binding_is_deterministic_but_changes_by_identity_key_or_role(self) -> None:
        def binding(**changes):
            supplied = private_inputs()
            supplied.update(changes)
            refresh_expected_commitments(supplied)
            capsule = self.module.build_root_custody_capsule(**supplied)
            try:
                return capsule.account_binding_sha256
            finally:
                capsule.scrub()

        baseline = binding()
        self.assertEqual(baseline, binding())
        self.assertNotEqual(
            baseline,
            binding(account_identity=bytearray(b"different-account")),
        )
        self.assertNotEqual(
            baseline,
            binding(principal_identity=bytearray(b"different-principal")),
        )
        self.assertNotEqual(
            baseline,
            binding(commitment_key=bytearray(reversed(range(32)))),
        )
        supplied = private_inputs()
        supplied["account_identity"], supplied["principal_identity"] = (
            supplied["principal_identity"],
            supplied["account_identity"],
        )
        refresh_expected_commitments(supplied)
        swapped = self.module.build_root_custody_capsule(**supplied)
        try:
            self.assertNotEqual(baseline, swapped.account_binding_sha256)
        finally:
            swapped.scrub()

    def test_23_private_values_never_appear_in_object_or_exception_repr(self) -> None:
        supplied = private_inputs()
        markers = [
            bytes(supplied["access_key_id"]).decode("ascii"),
            bytes(supplied["access_key_secret"]).decode("ascii"),
            bytes(supplied["security_token"]).decode("ascii"),
            bytes(supplied["account_identity"]).decode("ascii"),
            bytes(supplied["principal_identity"]).decode("ascii"),
        ]
        capsule = self.module.build_root_custody_capsule(**supplied)
        issued = capsule.issue_for_begin(wall_now_unix=WALL, monotonic_now_ns=MONO)
        try:
            rendered = repr(capsule) + repr(issued)
            for marker in markers:
                self.assertNotIn(marker, rendered)
            self.assertIn("<redacted>", rendered)
            self.assertIn("<committed>", rendered)
            with self.assertRaises(self.module.CapsuleError) as caught:
                self.module.validate_inner_envelope(
                    b'{"x":"private-fixture"}\n',
                    now_unix=WALL,
                    minimum_remaining_seconds=1860,
                )
            self.assertNotIn("private-fixture", str(caught.exception))
            self.assertNotIn("private-fixture", repr(caught.exception))
        finally:
            issued.scrub()
            capsule.scrub()

    def test_24_transfer_is_one_shot_and_explicit_scrub_zeros_the_exact_copy(self) -> None:
        capsule, _ = build_capsule(self.module)
        issued = capsule.issue_for_begin(wall_now_unix=WALL, monotonic_now_ns=MONO)
        mapping = issued.take_m1_supplier_mapping()
        raw = mapping["envelope"]
        self.assertIs(type(raw), bytearray)
        with self.assertRaisesRegex(self.module.CapsuleError, "^issued_credential_unavailable$"):
            issued.take_m1_supplier_mapping()
        self.assertFalse(hasattr(issued, "envelope_copy"))
        self.module.scrub_bytearray(raw)
        self.assertTrue(all(byte == 0 for byte in raw))
        issued.scrub()
        capsule.scrub()

    def test_25_scrubbed_capsule_refuses_probe_projection_and_supply(self) -> None:
        capsule, _ = build_capsule(self.module)
        capsule.scrub()
        calls = (
            lambda: capsule.initial_probe(wall_now_unix=WALL, monotonic_now_ns=MONO),
            lambda: capsule.project_m1_interface(wall_now_unix=WALL, monotonic_now_ns=MONO),
            lambda: capsule.issue_for_begin(wall_now_unix=WALL, monotonic_now_ns=MONO),
        )
        for call in calls:
            with self.assertRaisesRegex(self.module.CapsuleError, "^credential_scrubbed$"):
                call()

    def test_26_accepted_adapter_loader_accepts_generated_inner_envelope(self) -> None:
        adapter_name = "item26_aliyun_official_read_v2_capsule_fixture"
        adapter_path = ROOT / "tools" / "item26_aliyun_official_read_v2.py"
        spec = importlib.util.spec_from_file_location(adapter_name, adapter_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        adapter = importlib.util.module_from_spec(spec)
        sys.modules[adapter_name] = adapter
        try:
            spec.loader.exec_module(adapter)
            capsule, _ = build_capsule(self.module)
            issued = capsule.issue_for_begin(wall_now_unix=WALL, monotonic_now_ns=MONO)
            raw = issued.take_m1_supplier_mapping()["envelope"]
            try:
                loaded = adapter._load_temporary_credential_envelope(
                    bytes(raw),
                    now_unix=WALL,
                )
                self.assertEqual(loaded.expiration, WALL + LIFETIME)
                rendered = repr(loaded)
                self.assertNotIn("STS.", rendered)
                self.assertNotIn("kkkk", rendered)
                self.assertNotIn("tttt", rendered)
            finally:
                self.module.scrub_bytearray(raw)
                issued.scrub()
                capsule.scrub()
        finally:
            sys.modules.pop(adapter_name, None)

    def test_27_fd_roles_accept_exact_anonymous_blocking_rdwr_contract(self) -> None:
        dependencies = fake_fd_dependencies(self.module)
        reader, writer = self.module.validate_fd_roles(3, 4, **dependencies)
        self.assertEqual(reader.direction, "read")
        self.assertEqual(writer.direction, "write")
        self.assertNotEqual(reader.inode, writer.inode)

    def test_28_fd_roles_reject_numeric_and_underlying_aliases(self) -> None:
        dependencies = fake_fd_dependencies(self.module)
        for fds in ((2, 4), (3, 3), (True, 4)):
            with self.subTest(fds=fds):
                with self.assertRaises(self.module.CapsuleError):
                    self.module.validate_fd_roles(*fds, **dependencies)
        aliases = fake_fd_dependencies(self.module, inode_for_fd=lambda _fd: 99)
        with self.assertRaisesRegex(self.module.CapsuleError, "^fd_alias$"):
            self.module.validate_fd_roles(3, 4, **aliases)

    def test_29_fd_rejects_readonly_nonblocking_and_async_flags(self) -> None:
        flags = [os.O_RDONLY, os.O_RDWR | os.O_NONBLOCK]
        async_flag = getattr(os, "O_ASYNC", 0)
        if async_flag:
            flags.append(os.O_RDWR | async_flag)
        for selected in flags:
            with self.subTest(flags=selected):
                dependencies = fake_fd_dependencies(self.module, flags=selected)
                with self.assertRaisesRegex(self.module.CapsuleError, "^fd_identity$"):
                    self.module.validate_fd_roles(3, 4, **dependencies)

    def test_30_fd_rejects_tty_named_wrong_family_kind_and_direction(self) -> None:
        base = fake_fd_dependencies(self.module)
        cases = (
            {**base, "isatty_fn": lambda _fd: True},
            fake_fd_dependencies(self.module, probe_patch={"family": socket.AF_INET}),
            fake_fd_dependencies(self.module, probe_patch={"kind": socket.SOCK_DGRAM}),
            fake_fd_dependencies(self.module, probe_patch={"local_name": "named"}),
            fake_fd_dependencies(self.module, probe_patch={"peer_name": "named"}),
            fake_fd_dependencies(self.module, probe_patch={"direction": "wrong"}),
        )
        for dependencies in cases:
            with self.subTest(dependencies=tuple(dependencies)):
                with self.assertRaisesRegex(self.module.CapsuleError, "^fd_identity$"):
                    self.module.validate_fd_roles(3, 4, **dependencies)

    def test_31_read_frame_is_bounded_requires_eof_and_returns_owned_buffer(self) -> None:
        dependencies = fake_fd_dependencies(self.module)
        chunks = [b"abc", b"def", b""]
        events: list[object] = []

        def reader(fd: int, maximum: int) -> bytes:
            events.append(("read", fd, maximum))
            return chunks.pop(0)

        def eof_probe(fd: int) -> bool:
            events.append(("eof", fd))
            return True

        raw = self.module.read_anonymous_frame(
            3,
            6,
            reader=reader,
            eof_probe=eof_probe,
            **dependencies,
        )
        self.assertIs(type(raw), bytearray)
        self.assertEqual(raw, b"abcdef")
        self.assertEqual(events[-1], ("eof", 3))
        self.module.scrub_bytearray(raw)

    def test_32_read_frame_rejects_missing_eof_empty_oversize_and_wrong_leaf_type(self) -> None:
        dependencies = fake_fd_dependencies(self.module)
        cases = (
            ([b"abc", b""], 3, lambda _fd: False, "fd_eof"),
            ([b""], 3, lambda _fd: True, "fd_size"),
            ([b"abcde"], 4, lambda _fd: True, "fd_size"),
            ([bytearray(b"abc")], 3, lambda _fd: True, "fd_read"),
        )
        for chunks, maximum, eof_probe, code in cases:
            supplied = list(chunks)

            def reader(_fd: int, _maximum: int):
                return supplied.pop(0)

            with self.subTest(code=code):
                with self.assertRaisesRegex(self.module.CapsuleError, "^" + code + "$"):
                    self.module.read_anonymous_frame(
                        3,
                        maximum,
                        reader=reader,
                        eof_probe=eof_probe,
                        **dependencies,
                    )

    def test_33_write_frame_preflights_zero_bytes_before_any_private_byte(self) -> None:
        dependencies = fake_fd_dependencies(self.module)
        events: list[object] = []

        def writer(_fd: int, raw) -> int:
            copied = bytes(raw)
            events.append(copied)
            if not copied:
                return 0
            return min(2, len(copied))

        def shutdown_fn(fd: int, how: int) -> None:
            events.append(("shutdown", fd, how))

        raw = bytearray(b"abcdef")
        try:
            self.assertEqual(
                self.module.write_anonymous_frame(
                    4,
                    raw,
                    6,
                    writer=writer,
                    shutdown_fn=shutdown_fn,
                    **dependencies,
                ),
                6,
            )
            self.assertEqual(events[0], b"")
            self.assertEqual(events[-1], ("shutdown", 4, socket.SHUT_WR))
            self.assertEqual(
                b"".join(item for item in events[1:-1] if type(item) is bytes),
                b"abcdef" + b"cdef" + b"ef",
            )
            self.assertEqual(events.count(("shutdown", 4, socket.SHUT_WR)), 1)
        finally:
            self.module.scrub_bytearray(raw)

    def test_34_write_frame_preflight_failure_emits_no_private_bytes(self) -> None:
        dependencies = fake_fd_dependencies(self.module)
        events: list[bytes] = []

        def writer(_fd: int, raw) -> int:
            events.append(bytes(raw))
            return 1

        raw = bytearray(b"private-frame")
        try:
            with self.assertRaisesRegex(self.module.CapsuleError, "^fd_write_preflight$"):
                self.module.write_anonymous_frame(
                    4,
                    raw,
                    len(raw),
                    writer=writer,
                    shutdown_fn=lambda _fd, _how: (_ for _ in ()).throw(
                        AssertionError("shutdown reached")
                    ),
                    **dependencies,
                )
            self.assertEqual(events, [b""])
        finally:
            self.module.scrub_bytearray(raw)

    def test_35_root_custody_contract_is_exact_root_wheel_exclusive_nofollow(self) -> None:
        contract = self.module.root_custody_contract()
        self.assertEqual(contract["directory_paths"], (
            self.module.RUNTIME_ROOT,
            self.module.CUSTODY_ROOT,
        ))
        self.assertEqual(len(contract["file_paths"]), 4)
        self.assertEqual(contract["root_uid"], 0)
        self.assertEqual(contract["wheel_gid"], 0)
        self.assertEqual(contract["directory_mode"], 0o700)
        self.assertEqual(contract["file_mode"], 0o600)
        self.assertTrue(contract["file_create_flags"] & os.O_EXCL)
        self.assertTrue(contract["file_create_flags"] & os.O_NOFOLLOW)
        self.assertEqual(contract["file_nlink"], 1)
        self.assertIs(contract["exact_inventory_required"], True)
        self.assertEqual(contract["ancestor_observation"], "lstat-no-follow")
        self.assertEqual(
            set(contract["ancestor_directory_modes"]),
            {
                "/",
                "/Library",
                "/Library/Application Support",
                "/Library/Application Support/NoteAI",
                self.module.RUNTIME_ROOT,
                self.module.CUSTODY_ROOT,
            },
        )
        live, receipts, calls, listing_calls = valid_inventory(self.module)
        self.assertEqual(
            self.module.validate_root_custody_inventory(
                live,
                creation_receipts=receipts,
            ),
            contract,
        )
        self.assertEqual(len(calls), 4)
        self.assertTrue(
            all(flags == self.module.FILE_CREATE_FLAGS for _path, flags, _mode in calls)
        )
        self.assertTrue(all(mode == 0o600 for _path, _flags, mode in calls))
        self.assertEqual(len(listing_calls), 2)
        self.assertTrue(
            all(
                flags == self.module.DIRECTORY_READ_FLAGS
                for _path, flags in listing_calls
            )
        )

    def test_36_root_inventory_rejects_parent_symlink_pseudo_flags_and_leaf_drift(self) -> None:
        baseline, receipts, _calls, _listing_calls = valid_inventory(self.module)
        file_path = self.module.root_custody_contract()["file_paths"][0]
        mutations: list[dict[str, object]] = []
        value = copy.deepcopy(baseline)
        value["ancestor_lstat"]["/Library/Application Support/NoteAI"][
            "st_mode"
        ] = stat.S_IFLNK | 0o700
        mutations.append(value)
        value = copy.deepcopy(baseline)
        value["file_lstat"][file_path]["create_flags"] = self.module.FILE_CREATE_FLAGS
        mutations.append(value)
        for field, invalid in (
            ("st_mode", stat.S_IFLNK | 0o600),
            ("uid", 501),
            ("gid", 20),
            ("st_mode", stat.S_IFREG | 0o644),
            ("nlink", 2),
            ("ino", 999999),
            ("size", 999999),
            ("sha256", "0" * 64),
        ):
            value = copy.deepcopy(baseline)
            value["file_lstat"][file_path][field] = invalid
            mutations.append(value)
        for value in mutations:
            with self.subTest(digest=hashlib.sha256(repr(value).encode()).hexdigest()):
                with self.assertRaises(self.module.CapsuleError):
                    self.module.validate_root_custody_inventory(
                        value,
                        creation_receipts=receipts,
                    )

    def test_37_provision_boundary_refuses_before_argument_or_filesystem_access(self) -> None:
        class Poison:
            def __getattribute__(self, _name):
                raise AssertionError("poison inspected")

            def __repr__(self):
                raise AssertionError("poison formatted")

        with mock.patch.object(self.module.os, "open", side_effect=AssertionError("open")), \
             mock.patch.object(self.module.os, "lstat", side_effect=AssertionError("lstat")), \
             mock.patch.object(self.module.os, "write", side_effect=AssertionError("write")):
            with self.assertRaisesRegex(
                self.module.CapsuleError,
                "^source_only_execution_denied$",
            ) as caught:
                self.module.provision_root_custody(Poison(), payload=Poison())
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)

    def test_38_expected_commitment_format_and_both_mismatches_fail_and_scrub(self) -> None:
        cases = (
            ("expected_account_commitment_hmac_sha256", "A" * 64, "expected_commitment"),
            ("expected_principal_commitment_hmac_sha256", "0" * 63, "expected_commitment"),
            ("expected_account_commitment_hmac_sha256", "0" * 64, "commitment_mismatch"),
            ("expected_principal_commitment_hmac_sha256", "0" * 64, "commitment_mismatch"),
        )
        for field, replacement, code in cases:
            supplied = private_inputs()
            private_buffers = [
                value for value in supplied.values() if type(value) is bytearray
            ]
            supplied[field] = replacement
            with self.subTest(field=field, code=code):
                with self.assertRaisesRegex(
                    self.module.CapsuleError,
                    "^" + code + "$",
                ) as caught:
                    self.module.build_root_custody_capsule(**supplied)
                self.assertIsNone(caught.exception.__cause__)
                self.assertIsNone(caught.exception.__context__)
                self.assertTrue(
                    all(all(byte == 0 for byte in value) for value in private_buffers)
                )

    def test_39_builder_uses_two_constant_time_commitment_comparisons(self) -> None:
        text = self.raw.decode("utf-8")
        self.assertIn("account_matches = hmac.compare_digest(", text)
        self.assertIn("principal_matches = hmac.compare_digest(", text)
        self.assertIn("expected_account_commitment_hmac_sha256", text)
        self.assertIn("expected_principal_commitment_hmac_sha256", text)
        self.assertNotIn("account_commitment_mismatch", text)
        self.assertNotIn("principal_commitment_mismatch", text)
        supplied = private_inputs()
        supplied["expected_account_commitment_hmac_sha256"] = "0" * 64
        private_buffers = [value for value in supplied.values() if type(value) is bytearray]
        original = self.module.hmac.compare_digest
        calls: list[tuple[object, object]] = []

        def traced(left, right):
            calls.append((left, right))
            return original(left, right)

        with mock.patch.object(self.module.hmac, "compare_digest", side_effect=traced):
            with self.assertRaisesRegex(
                self.module.CapsuleError,
                "^commitment_mismatch$",
            ):
                self.module.build_root_custody_capsule(**supplied)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(all(byte == 0 for byte in row) for row in private_buffers))

    def test_40_supplier_is_capped_at_64_and_65th_rejects_before_validation_or_copy(self) -> None:
        capsule, _ = build_capsule(self.module, lifetime=86400)
        issued = []
        try:
            for index in range(64):
                row = capsule.issue_for_begin(
                    wall_now_unix=WALL + index,
                    monotonic_now_ns=MONO + index * 1_000_000_000,
                )
                issued.append(row)
            self.assertEqual(capsule.round_count, 64)
            with mock.patch.object(
                type(capsule),
                "_assert_binding_integrity",
                side_effect=AssertionError("validation reached"),
            ):
                with self.assertRaisesRegex(
                    self.module.CapsuleError,
                    "^credential_round_limit$",
                ):
                    capsule.issue_for_begin(
                        wall_now_unix=WALL + 64,
                        monotonic_now_ns=MONO + 64_000_000_000,
                    )
            self.assertEqual(capsule.round_count, 64)
        finally:
            for row in issued:
                row.scrub()
            capsule.scrub()

    def test_41_writer_half_closes_exactly_once_and_fails_closed_without_retry(self) -> None:
        dependencies = fake_fd_dependencies(self.module)
        raw = bytearray(b"abcdef")
        events: list[object] = []

        def writer(_fd: int, value) -> int:
            copied = bytes(value)
            events.append(("write", copied))
            return 0 if not copied else len(copied)

        def shutdown_fn(fd: int, how: int) -> None:
            events.append(("shutdown", fd, how))
            raise OSError("fixed fake failure")

        try:
            with self.assertRaisesRegex(self.module.CapsuleError, "^fd_shutdown$"):
                self.module.write_anonymous_frame(
                    4,
                    raw,
                    len(raw),
                    writer=writer,
                    shutdown_fn=shutdown_fn,
                    **dependencies,
                )
            self.assertEqual(events[-1], ("shutdown", 4, socket.SHUT_WR))
            self.assertEqual(events.count(("shutdown", 4, socket.SHUT_WR)), 1)
            self.assertEqual(events[0], ("write", b""))
            self.assertEqual(events[1], ("write", b"abcdef"))

            events.clear()

            def oversized_count(_fd: int, value) -> int:
                copied = bytes(value)
                events.append(("write", copied))
                return 0 if not copied else len(copied) + 1

            with self.assertRaisesRegex(self.module.CapsuleError, "^fd_write$"):
                self.module.write_anonymous_frame(
                    4,
                    raw,
                    len(raw),
                    writer=oversized_count,
                    shutdown_fn=lambda fd, how: events.append(("shutdown", fd, how)),
                    **dependencies,
                )
            self.assertFalse(any(event[0] == "shutdown" for event in events))
        finally:
            self.module.scrub_bytearray(raw)

    def test_42_capsule_constructor_is_internal_and_binding_is_rechecked(self) -> None:
        self.assertFalse(hasattr(self.module, "RootCustodyTemporaryStsCapsule"))
        with self.assertRaisesRegex(
            self.module.CapsuleError,
            "^capsule_construction_denied$",
        ):
            self.module._RootCustodyTemporaryStsCapsule(
                envelope=bytearray(b"x"),
                expiration_unix=WALL + LIFETIME,
                initial_wall_unix=WALL,
                initial_monotonic_ns=MONO,
                account_commitment_hmac_sha256="0" * 64,
                principal_commitment_hmac_sha256="0" * 64,
                account_binding_sha256="0" * 64,
                credential_envelope_sha256="0" * 64,
            )
        guarded, _ = build_capsule(self.module)
        try:
            for operation, code in (
                (lambda: copy.copy(guarded), "capsule_copy_denied"),
                (lambda: copy.deepcopy(guarded), "capsule_copy_denied"),
                (lambda: pickle.dumps(guarded), "capsule_serialization_denied"),
                (guarded.__getstate__, "capsule_serialization_denied"),
            ):
                with self.subTest(code=code):
                    with self.assertRaisesRegex(
                        self.module.CapsuleError,
                        "^" + code + "$",
                    ):
                        operation()
            self.assertEqual(guarded.round_count, 0)
        finally:
            guarded.scrub()
        for operation in ("project", "issue"):
            capsule, _ = build_capsule(self.module)
            try:
                setattr(
                    capsule,
                    "_RootCustodyTemporaryStsCapsule__account_binding",
                    "0" * 64,
                )
                with self.subTest(operation=operation):
                    with self.assertRaisesRegex(
                        self.module.CapsuleError,
                        "^credential_binding_drift$",
                    ):
                        if operation == "project":
                            capsule.project_m1_interface(
                                wall_now_unix=WALL,
                                monotonic_now_ns=MONO,
                            )
                        else:
                            capsule.issue_for_begin(
                                wall_now_unix=WALL,
                                monotonic_now_ns=MONO,
                            )
            finally:
                capsule.scrub()

    def test_43_issued_secret_has_no_dataclass_or_instance_dictionary_escape(self) -> None:
        capsule, _ = build_capsule(self.module)
        issued = capsule.issue_for_begin(wall_now_unix=WALL, monotonic_now_ns=MONO)
        try:
            self.assertFalse(hasattr(issued, "__dict__"))
            self.assertFalse(dataclasses.is_dataclass(issued))
            with self.assertRaises(TypeError):
                dataclasses.asdict(issued)
            self.assertEqual(repr(issued), "IssuedTemporarySts(<redacted>)")
            self.assertEqual(str(issued), "IssuedTemporarySts(<redacted>)")
            with self.assertRaises(AttributeError):
                issued.remaining_seconds = 1
            for operation, code in (
                (lambda: copy.copy(issued), "issued_copy_denied"),
                (lambda: copy.deepcopy(issued), "issued_copy_denied"),
                (lambda: pickle.dumps(issued), "issued_serialization_denied"),
                (issued.__getstate__, "issued_serialization_denied"),
            ):
                with self.subTest(code=code):
                    with self.assertRaisesRegex(
                        self.module.CapsuleError,
                        "^" + code + "$",
                    ):
                        operation()
            copied = issued.take_m1_supplier_mapping()["envelope"]
            try:
                self.assertGreater(len(copied), 0)
            finally:
                self.module.scrub_bytearray(copied)
        finally:
            issued.scrub()
            capsule.scrub()

    def test_44_creation_receipt_seals_pre_post_fd_identity_and_hash(self) -> None:
        live, receipts, calls, _listing_calls = valid_inventory(self.module)
        path = self.module.root_custody_contract()["file_paths"][0]
        self.assertEqual(calls[0][1], self.module.FILE_CREATE_FLAGS)
        self.assertFalse(hasattr(receipts[path], "__dict__"))
        with self.assertRaisesRegex(
            self.module.CapsuleError,
            "^custody_receipt_construction_denied$",
        ):
            self.module._ExclusiveCreationReceipt(
                None,
                path,
                {},
                {},
                "0" * 64,
                "0" * 64,
            )
        with self.assertRaises(self.module.CapsuleError):
            self.module.validate_root_custody_inventory(
                live,
                creation_receipts={**receipts, path: object()},
            )

        def drifting_creator(_path: str, _flags: int, _mode: int):
            row = {
                "st_mode": stat.S_IFREG | 0o600,
                "uid": 0,
                "gid": 0,
                "nlink": 1,
                "dev": 9,
                "ino": 123,
                "size": 0,
            }
            post = dict(row)
            post["ino"] = 124
            post["size"] = 1
            return {
                "pre_fd_stat": row,
                "post_fd_stat": post,
                "pre_content_sha256": hashlib.sha256(b"").hexdigest(),
                "post_content_sha256": hashlib.sha256(b"x").hexdigest(),
            }

        with self.assertRaisesRegex(
            self.module.CapsuleError,
            "^custody_creation_receipt$",
        ):
            self.module._capture_exclusive_creation_receipt(
                path,
                creator=drifting_creator,
            )

    def test_45_root_directory_listing_is_nofollow_inode_bound_and_exact(self) -> None:
        live, receipts, _calls, listing_calls = valid_inventory(self.module)
        contract = self.module.root_custody_contract()
        self.module.validate_root_custody_inventory(
            live,
            creation_receipts=receipts,
        )
        self.assertEqual(len(listing_calls), 2)
        self.assertTrue(
            all(flags == self.module.DIRECTORY_READ_FLAGS for _path, flags in listing_calls)
        )
        path = self.module.RUNTIME_ROOT
        root_stat = live["ancestor_lstat"][path]
        expected = contract["root_exact_entry_names"][path]
        for names in (expected[:-1], expected + ("unexpected-entry",)):
            with self.subTest(names=names):
                with self.assertRaisesRegex(
                    self.module.CapsuleError,
                    "^custody_directory_entries$",
                ):
                    self.module._capture_root_directory_listing(
                        path,
                        lister=lambda _path, _flags, names=names: {
                            "fd_stat": dict(root_stat),
                            "entry_names": names,
                        },
                    )
        with self.assertRaisesRegex(
            self.module.CapsuleError,
            "^custody_listing_construction_denied$",
        ):
            self.module._DirectoryListingReceipt()

    def test_46_malformed_fstat_is_normalized_to_fixed_fd_error(self) -> None:
        dependencies = fake_fd_dependencies(self.module)
        dependencies["fstat_fn"] = lambda _fd: object()
        with self.assertRaisesRegex(self.module.CapsuleError, "^fd_identity$") as caught:
            self.module.validate_fd_roles(3, 4, **dependencies)
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)
