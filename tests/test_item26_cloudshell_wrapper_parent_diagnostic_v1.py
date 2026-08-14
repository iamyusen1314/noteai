import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import re
import stat
import types
import unittest
from pathlib import Path
from unittest import mock

from tools import validate_item26_cloudshell_wrapper_parent_diagnostic_v1 as validator


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / ".codex" / "item26-cloudshell-wrapper-parent-diagnostic-v1.template.py"
SPEC = importlib.util.spec_from_file_location("item26_wrapper_parent_atom", TEMPLATE)
atom = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(atom)


class Item26CloudShellWrapperParentDiagnosticTests(unittest.TestCase):
    def record(
        self,
        chain,
        ordinal,
        actual_path,
        entry_type="directory",
        mode="0755",
        uid=0,
        gid=0,
        nlink=1,
    ):
        path_digest = validator.path_hash(actual_path)
        alias = -1
        for index, fixed in enumerate(validator.LEXICAL_PARENTS):
            if path_digest == validator.path_hash(fixed):
                alias = index
                break
        return {
            "chain": chain,
            "ordinal": ordinal,
            "path": actual_path if chain == "lexical" else None,
            "path_sha256": path_digest,
            "path_depth": len(actual_path.split("/")) - 1,
            "entry_type": entry_type,
            "is_symlink": entry_type == "symlink",
            "uid": uid,
            "gid": gid,
            "mode": mode,
            "nlink": nlink,
            "identity_sha256": hashlib.sha256(
                (chain + ":" + str(ordinal) + ":" + actual_path).encode("ascii")
            ).hexdigest(),
            "target_sha256": "f" * 64 if entry_type == "symlink" else None,
            "group_or_other_writable": (
                entry_type == "directory" and bool(int(mode, 8) & 0o022)
            ),
            "matches_lexical_index": alias,
        }

    def lexical(self, writable_index=None):
        records = []
        for index, path in enumerate(validator.LEXICAL_PARENTS):
            mode = "0775" if index == writable_index else "0755"
            records.append(self.record("lexical", index, path, mode=mode))
        return records

    def full_observation(self, writable_canonical_index=None):
        canonical_paths = ("/opt", "/opt/aliyun")
        canonical = []
        for index, path in enumerate(canonical_paths):
            mode = "0775" if index == writable_canonical_index else "0755"
            canonical.append(self.record("canonical", index, path, mode=mode))
        return {
            "lexical": self.lexical(),
            "canonical": canonical,
            "endpoint": self.record(
                "endpoint",
                0,
                validator.WRAPPER_PATH,
                entry_type="symlink",
                mode="0777",
            ),
            "canonical_path_sha256": validator.path_hash("/opt/aliyun/aliyun"),
            "canonical_depth": 3,
        }

    def lexical_match_observation(self):
        return {
            "lexical": self.lexical(writable_index=1),
            "canonical": [],
            "endpoint": None,
            "canonical_path_sha256": None,
            "canonical_depth": 0,
        }

    def receipt(self, observation, state, reason, scope, index):
        value = {
            "schema": validator.SCHEMA,
            "status": "BLOCKED",
            "predecessor": copy.deepcopy(validator.PREDECESSOR),
            "scope": {
                "role": "wrapper",
                "invoked_path": validator.WRAPPER_PATH,
                "lexical_parents": list(validator.LEXICAL_PARENTS),
            },
            "diagnostic_complete": True,
            "diagnostic_state": state,
            "reason_code": reason,
            "before": copy.deepcopy(observation),
            "after": copy.deepcopy(observation),
            "before_after_equal": True,
            "culprit_scope": scope,
            "culprit_index": index,
            "culprit_path": None,
            "culprit_path_sha256": None,
        }
        value.update(copy.deepcopy(validator.BOUNDARY_VALUES))
        if scope == "LEXICAL":
            value["culprit_path"] = validator.LEXICAL_PARENTS[index]
            value["culprit_path_sha256"] = validator.path_hash(
                validator.LEXICAL_PARENTS[index]
            )
        elif scope == "CANONICAL":
            value["culprit_path_sha256"] = observation["canonical"][index][
                "path_sha256"
            ]
        return self.recommit(value)

    def recommit(self, value):
        payload = {
            key: item for key, item in value.items() if key != "commitment_sha256"
        }
        value["commitment_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return value

    def test_validator_accepts_lexical_and_canonical_matches(self):
        lexical = self.receipt(
            self.lexical_match_observation(),
            "CURRENT_STABLE_MATCH",
            "WRITABLE_EXECUTABLE_PARENT",
            "LEXICAL",
            1,
        )
        canonical_observation = self.full_observation(writable_canonical_index=1)
        canonical = self.receipt(
            canonical_observation,
            "CURRENT_STABLE_MATCH",
            "WRITABLE_EXECUTABLE_PARENT",
            "CANONICAL",
            1,
        )
        for value in (lexical, canonical):
            with self.subTest(scope=value["culprit_scope"]):
                self.assertEqual(
                    validator.validate(value),
                    (value["diagnostic_state"], value["commitment_sha256"]),
                )

    def test_symlink_mode_0777_is_not_classified_as_writable(self):
        observation = self.full_observation()
        observation["lexical"][1] = self.record(
            "lexical",
            1,
            validator.LEXICAL_PARENTS[1],
            entry_type="symlink",
            mode="0777",
        )
        value = self.receipt(
            observation,
            "CURRENT_STABLE_NO_MATCH",
            "CURRENT_STATE_NOT_REPRODUCED",
            "NONE",
            -1,
        )
        self.assertEqual(validator.validate(value)[0], "CURRENT_STABLE_NO_MATCH")

    def test_untrusted_endpoint_symlink_cannot_reach_canonical_match(self):
        endpoint_only = {
            "lexical": self.lexical(),
            "canonical": [],
            "endpoint": self.record(
                "endpoint",
                0,
                validator.WRAPPER_PATH,
                entry_type="symlink",
                mode="0777",
                uid=1000,
            ),
            "canonical_path_sha256": None,
            "canonical_depth": 0,
        }
        no_match = self.receipt(
            endpoint_only,
            "CURRENT_STABLE_NO_MATCH",
            "CURRENT_STATE_NOT_REPRODUCED",
            "NONE",
            -1,
        )
        self.assertEqual(validator.validate(no_match)[0], "CURRENT_STABLE_NO_MATCH")

        forged = self.full_observation(writable_canonical_index=1)
        forged["endpoint"] = copy.deepcopy(endpoint_only["endpoint"])
        forged_receipt = self.receipt(
            forged,
            "CURRENT_STABLE_MATCH",
            "WRITABLE_EXECUTABLE_PARENT",
            "CANONICAL",
            1,
        )
        with self.assertRaises(validator.Invalid):
            validator.validate(forged_receipt)

    def test_endpoint_absolute_self_symlink_is_never_a_stable_receipt(self):
        observation = {
            "lexical": self.lexical(),
            "canonical": [
                self.record("canonical", index, path)
                for index, path in enumerate(validator.LEXICAL_PARENTS)
            ],
            "endpoint": self.record(
                "endpoint",
                0,
                validator.WRAPPER_PATH,
                entry_type="symlink",
                mode="0777",
            ),
            "canonical_path_sha256": validator.path_hash(validator.WRAPPER_PATH),
            "canonical_depth": 4,
        }
        observation["endpoint"]["target_sha256"] = validator.path_hash(
            validator.WRAPPER_PATH
        )
        value = self.receipt(
            observation,
            "CURRENT_STABLE_NO_MATCH",
            "CURRENT_STATE_NOT_REPRODUCED",
            "NONE",
            -1,
        )
        with self.assertRaises(validator.Invalid):
            validator.validate(value)

        observation["endpoint"]["target_sha256"] = "e" * 64
        arbitrary_target = self.receipt(
            observation,
            "CURRENT_STABLE_NO_MATCH",
            "CURRENT_STATE_NOT_REPRODUCED",
            "NONE",
            -1,
        )
        with self.assertRaises(validator.Invalid):
            validator.validate(arbitrary_target)

        endpoint_mismatch = {
            "lexical": self.lexical(),
            "canonical": [],
            "endpoint": self.record(
                "endpoint",
                0,
                validator.WRAPPER_PATH,
                entry_type="symlink",
                mode="0777",
                uid=1000,
            ),
            "canonical_path_sha256": None,
            "canonical_depth": 0,
        }
        endpoint_mismatch["endpoint"]["target_sha256"] = validator.path_hash(
            validator.WRAPPER_PATH
        )
        real_no_match = self.receipt(
            endpoint_mismatch,
            "CURRENT_STABLE_NO_MATCH",
            "CURRENT_STATE_NOT_REPRODUCED",
            "NONE",
            -1,
        )
        self.assertEqual(validator.validate(real_no_match)[0], "CURRENT_STABLE_NO_MATCH")

    def test_opaque_targets_do_not_claim_independent_reachability_proof(self):
        for raw_target in ("/", "aliyun", "./aliyun", "../bin/aliyun"):
            observation = self.full_observation()
            observation["endpoint"]["target_sha256"] = validator.path_hash(raw_target)
            value = self.receipt(
                observation,
                "CURRENT_STABLE_NO_MATCH",
                "CURRENT_STATE_NOT_REPRODUCED",
                "NONE",
                -1,
            )
            with self.subTest(raw_target=raw_target):
                self.assertEqual(validator.validate(value)[0], "CURRENT_STABLE_NO_MATCH")
                self.assertFalse(value["receipt_origin_authenticated"])
                self.assertFalse(value["opaque_target_resolution_proven_by_validator"])
                self.assertFalse(value["commitment_is_authentication_signature"])
                self.assertTrue(value["target_sha256_is_opaque_evidence"])
                self.assertTrue(value["direct_single_execution_provenance_required"])
                self.assertFalse(value["next_stage_authorized"])

    def test_relative_endpoint_target_respects_resolved_lexical_topology(self):
        observation = {
            "lexical": self.lexical(),
            "canonical": [
                self.record("canonical", 0, "/opt"),
                self.record("canonical", 1, "/opt/bin"),
            ],
            "endpoint": self.record(
                "endpoint",
                0,
                validator.WRAPPER_PATH,
                entry_type="symlink",
                mode="0777",
            ),
            "canonical_path_sha256": validator.path_hash("/opt/bin/aliyun"),
            "canonical_depth": 3,
        }
        observation["lexical"][2] = self.record(
            "lexical",
            2,
            validator.LEXICAL_PARENTS[2],
            entry_type="symlink",
            mode="0777",
        )
        observation["endpoint"]["target_sha256"] = validator.path_hash(
            "../bin/aliyun"
        )
        value = self.receipt(
            observation,
            "CURRENT_STABLE_NO_MATCH",
            "CURRENT_STATE_NOT_REPRODUCED",
            "NONE",
            -1,
        )
        self.assertEqual(validator.validate(value)[0], "CURRENT_STABLE_NO_MATCH")

    def test_lexical_target_hash_is_opaque_not_a_resolver_proof(self):
        observation = self.full_observation()
        observation["lexical"][1] = self.record(
            "lexical",
            1,
            validator.LEXICAL_PARENTS[1],
            entry_type="symlink",
            mode="0777",
        )
        observation["lexical"][1]["target_sha256"] = validator.path_hash(
            validator.WRAPPER_PATH
        )
        value = self.receipt(
            observation,
            "CURRENT_STABLE_NO_MATCH",
            "CURRENT_STATE_NOT_REPRODUCED",
            "NONE",
            -1,
        )
        self.assertEqual(validator.validate(value)[0], "CURRENT_STABLE_NO_MATCH")
        self.assertFalse(value["opaque_target_resolution_proven_by_validator"])
        self.assertFalse(value["next_stage_authorized"])

    def test_validator_rejects_recursive_type_aliases(self):
        mutations = []
        for mutate in (
            lambda value: value["predecessor"].__setitem__("command_bytes", 8506.0),
            lambda value: value["before"]["lexical"][0].__setitem__("ordinal", False),
            lambda value: value["after"]["lexical"][0].__setitem__("uid", False),
            lambda value: value["before"]["canonical"][0].__setitem__("nlink", 1.0),
            lambda value: value.__setitem__("before_after_equal", 1),
            lambda value: value.__setitem__("culprit_index", True),
            lambda value: value.__setitem__("wrapper_content_read_count", False),
            lambda value: value["before"].__setitem__("canonical_depth", 3.0),
        ):
            value = self.receipt(
                self.full_observation(writable_canonical_index=1),
                "CURRENT_STABLE_MATCH",
                "WRITABLE_EXECUTABLE_PARENT",
                "CANONICAL",
                1,
            )
            mutate(value)
            mutations.append(self.recommit(value))
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(validator.Invalid):
                validator.validate(mutation)

    def test_validator_rejects_unbound_endpoint_depth_and_canonical_order(self):
        mutations = []
        value = self.receipt(
            self.full_observation(writable_canonical_index=1),
            "CURRENT_STABLE_MATCH",
            "WRITABLE_EXECUTABLE_PARENT",
            "CANONICAL",
            1,
        )
        value["before"]["endpoint"]["path_sha256"] = "a" * 64
        value["after"]["endpoint"]["path_sha256"] = "a" * 64
        mutations.append(self.recommit(value))
        value = self.receipt(
            self.full_observation(writable_canonical_index=1),
            "CURRENT_STABLE_MATCH",
            "WRITABLE_EXECUTABLE_PARENT",
            "CANONICAL",
            1,
        )
        value["before"]["canonical"][1]["path_depth"] = 9
        value["after"]["canonical"][1]["path_depth"] = 9
        mutations.append(self.recommit(value))
        value = self.receipt(
            self.full_observation(writable_canonical_index=1),
            "CURRENT_STABLE_MATCH",
            "WRITABLE_EXECUTABLE_PARENT",
            "CANONICAL",
            1,
        )
        value["before"]["canonical_path_sha256"] = value["before"]["canonical"][1][
            "path_sha256"
        ]
        value["after"]["canonical_path_sha256"] = value["after"]["canonical"][1][
            "path_sha256"
        ]
        mutations.append(self.recommit(value))
        value = self.receipt(
            self.full_observation(writable_canonical_index=1),
            "CURRENT_STABLE_MATCH",
            "WRITABLE_EXECUTABLE_PARENT",
            "CANONICAL",
            1,
        )
        value["before"]["canonical"] = []
        value["after"]["canonical"] = []
        value["before"]["endpoint"] = None
        value["after"]["endpoint"] = None
        value["before"]["canonical_path_sha256"] = None
        value["after"]["canonical_path_sha256"] = None
        value["before"]["canonical_depth"] = 0
        value["after"]["canonical_depth"] = 0
        mutations.append(self.recommit(value))
        for mutation in mutations:
            with self.assertRaises(validator.Invalid):
                validator.validate(mutation)

    def test_validator_binds_canonical_alias_metadata_and_fixed_non_symlink_path(self):
        alias_conflict = self.full_observation(writable_canonical_index=1)
        alias_conflict["canonical"][0] = self.record(
            "canonical", 0, "/usr", mode="0775"
        )
        alias_receipt = self.receipt(
            alias_conflict,
            "CURRENT_STABLE_MATCH",
            "WRITABLE_EXECUTABLE_PARENT",
            "CANONICAL",
            0,
        )
        with self.assertRaises(validator.Invalid):
            validator.validate(alias_receipt)

        redirected = self.full_observation(writable_canonical_index=1)
        redirected["endpoint"] = self.record(
            "endpoint", 0, validator.WRAPPER_PATH, entry_type="other", mode="0755"
        )
        redirected_receipt = self.receipt(
            redirected,
            "CURRENT_STABLE_MATCH",
            "WRITABLE_EXECUTABLE_PARENT",
            "CANONICAL",
            1,
        )
        with self.assertRaises(validator.Invalid):
            validator.validate(redirected_receipt)

        fixed = {
            "lexical": self.lexical(),
            "canonical": [
                self.record("canonical", index, path)
                for index, path in enumerate(validator.LEXICAL_PARENTS)
            ],
            "endpoint": self.record(
                "endpoint", 0, validator.WRAPPER_PATH, entry_type="other", mode="0755"
            ),
            "canonical_path_sha256": validator.path_hash(validator.WRAPPER_PATH),
            "canonical_depth": 4,
        }
        fixed_receipt = self.receipt(
            fixed,
            "CURRENT_STABLE_NO_MATCH",
            "CURRENT_STATE_NOT_REPRODUCED",
            "NONE",
            -1,
        )
        self.assertEqual(validator.validate(fixed_receipt)[0], "CURRENT_STABLE_NO_MATCH")

    def test_validator_binds_known_final_path_and_rejects_endpoint_as_parent(self):
        known_final = self.receipt(
            self.full_observation(writable_canonical_index=1),
            "CURRENT_STABLE_MATCH",
            "WRITABLE_EXECUTABLE_PARENT",
            "CANONICAL",
            1,
        )
        known_final["before"]["canonical_path_sha256"] = validator.path_hash(
            "/usr/shell"
        )
        known_final["after"]["canonical_path_sha256"] = validator.path_hash(
            "/usr/shell"
        )
        with self.assertRaises(validator.Invalid):
            validator.validate(self.recommit(known_final))

        endpoint_parent = self.receipt(
            self.full_observation(writable_canonical_index=1),
            "CURRENT_STABLE_MATCH",
            "WRITABLE_EXECUTABLE_PARENT",
            "CANONICAL",
            1,
        )
        for side in ("before", "after"):
            endpoint_parent[side]["canonical"][1]["path_sha256"] = validator.path_hash(
                validator.WRAPPER_PATH
            )
            endpoint_parent[side]["canonical"][1]["matches_lexical_index"] = -1
        with self.assertRaises(validator.Invalid):
            validator.validate(self.recommit(endpoint_parent))

    def test_canonical_known_alias_requires_its_fixed_prefix(self):
        observation = self.full_observation(writable_canonical_index=1)
        observation["canonical"][1] = self.record(
            "canonical", 1, "/usr/shell", mode="0775"
        )
        observation["lexical"][1]["mode"] = "0775"
        observation["lexical"][1]["group_or_other_writable"] = True
        value = self.receipt(
            observation,
            "CURRENT_STABLE_MATCH",
            "WRITABLE_EXECUTABLE_PARENT",
            "LEXICAL",
            1,
        )
        with self.assertRaises(validator.Invalid):
            validator.validate(value)

    def test_bounded_resolver_pins_absolute_symlink_chain(self):
        targets = {"/usr/shell": "/opt/vendor"}
        kinds = {"/usr/shell": "symlink", "/opt/vendor/bin/aliyun": "other"}
        counter = [10]

        def fake_capture(path, chain, ordinal, reveal_path, require_directory=False):
            kind = kinds.get(path, "directory")
            target_hash = (
                hashlib.sha256(targets[path].encode("ascii")).hexdigest()
                if kind == "symlink"
                else None
            )
            counter[0] += 1
            return (
                {"entry_type": kind},
                {
                    "fd": counter[0],
                    "path": path,
                    "signature": (1, counter[0], 0, 0, 0, 1, 0, 1),
                    "kind": kind,
                    "target_sha256": target_hash,
                },
            )

        with mock.patch.object(atom, "capture", side_effect=fake_capture), \
                mock.patch.object(atom, "readlink_value", side_effect=lambda path: targets[path]):
            path, handles = atom.resolve_bounded(atom.WRAPPER_PATH)
        self.assertEqual(path, "/opt/vendor/bin/aliyun")
        self.assertGreaterEqual(len(handles), 6)

    def test_bounded_resolver_rejects_loop_and_closes_owned_handles(self):
        target = "/usr/shell"
        closed = []
        counter = [20]

        def fake_capture(path, chain, ordinal, reveal_path, require_directory=False):
            kind = "symlink" if path == "/usr/shell" else "directory"
            counter[0] += 1
            return (
                {"entry_type": kind},
                {
                    "fd": counter[0],
                    "path": path,
                    "signature": (1, 99 if kind == "symlink" else counter[0], 0, 0, 0, 1, 0, 1),
                    "kind": kind,
                    "target_sha256": (
                        hashlib.sha256(target.encode("ascii")).hexdigest()
                        if kind == "symlink"
                        else None
                    ),
                },
            )

        with mock.patch.object(atom, "capture", side_effect=fake_capture), \
                mock.patch.object(atom, "readlink_value", return_value=target), \
                mock.patch.object(atom, "close_handles", side_effect=lambda values: closed.extend(values)):
            with self.assertRaises(atom.ObservationBlocked) as raised:
                atom.resolve_bounded(atom.WRAPPER_PATH)
        self.assertEqual(raised.exception.code, "SYMLINK_RESOLUTION_LOOP")
        self.assertTrue(closed)

    def test_bounded_resolver_rejects_more_than_eight_symlink_hops(self):
        targets = {"/usr/shell": "/link1"}
        for index in range(1, 10):
            targets["/link%d" % index] = "/link%d" % (index + 1)
        counter = [40]

        def fake_capture(path, chain, ordinal, reveal_path, require_directory=False):
            kind = "symlink" if path in targets else "directory"
            counter[0] += 1
            return (
                {"entry_type": kind},
                {
                    "fd": counter[0],
                    "path": path,
                    "signature": (1, counter[0], 0, 0, 0, 1, 0, 1),
                    "kind": kind,
                    "target_sha256": (
                        hashlib.sha256(targets[path].encode("ascii")).hexdigest()
                        if kind == "symlink"
                        else None
                    ),
                },
            )

        with mock.patch.object(atom, "capture", side_effect=fake_capture), \
                mock.patch.object(atom, "readlink_value", side_effect=lambda path: targets[path]), \
                mock.patch.object(atom, "close_handles"):
            with self.assertRaises(atom.ObservationBlocked) as raised:
                atom.resolve_bounded(atom.WRAPPER_PATH)
        self.assertEqual(raised.exception.code, "SYMLINK_HOP_LIMIT")

    def test_verify_handle_detects_parent_ctime_change(self):
        before = types.SimpleNamespace(
            st_dev=1,
            st_ino=2,
            st_mode=stat.S_IFDIR | 0o755,
            st_uid=0,
            st_gid=0,
            st_nlink=2,
            st_size=64,
            st_ctime_ns=100,
        )
        changed = copy.copy(before)
        changed.st_ctime_ns = 101
        handle = {
            "fd": 50,
            "path": "/usr",
            "signature": atom.stat_signature(before),
            "kind": "directory",
            "target_sha256": None,
        }
        with mock.patch.object(atom.os, "fstat", return_value=before), \
                mock.patch.object(atom.os, "lstat", return_value=changed):
            with self.assertRaises(atom.ObservationBlocked) as raised:
                atom.verify_handle(handle)
        self.assertEqual(raised.exception.code, "PATH_IDENTITY_CHANGED")

    def test_diagnose_returns_blocking_exit_for_complete_match(self):
        observation = self.lexical_match_observation()
        with mock.patch.object(
            atom,
            "observe_once",
            side_effect=[
                (copy.deepcopy(observation), [], "WRITABLE", 1),
                (copy.deepcopy(observation), [], "WRITABLE", 1),
            ],
        ), contextlib.redirect_stdout(io.StringIO()) as output:
            status = atom.diagnose()
        self.assertEqual(status, 3)
        value = json.loads(output.getvalue())
        self.assertEqual(validator.validate(value)[0], "CURRENT_STABLE_MATCH")
        self.assertFalse(value["next_stage_authorized"])

    def test_observation_blocked_is_empty_terminal_and_type_strict(self):
        with mock.patch.object(
            atom, "observe_once", side_effect=atom.ObservationBlocked("PATH_PIN_FAILED")
        ), contextlib.redirect_stdout(io.StringIO()) as output:
            status = atom.main()
        self.assertEqual(status, 3)
        value = json.loads(output.getvalue())
        self.assertEqual(validator.validate(value)[0], "OBSERVATION_BLOCKED")
        mutation = copy.deepcopy(value)
        mutation["before"] = self.lexical_match_observation()
        with self.assertRaises(validator.Invalid):
            validator.validate(self.recommit(mutation))
        mutation = copy.deepcopy(value)
        mutation["reason_code"] = "IMPOSSIBLE_SOURCE_REASON"
        with self.assertRaises(validator.Invalid):
            validator.validate(self.recommit(mutation))

    def test_blocked_reason_set_matches_frozen_source_literals(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        reasons = set(
            re.findall(r'ObservationBlocked\("([A-Z0-9_]+)"\)', source)
        )
        reasons.add("INTERNAL_VALIDATION_ERROR")
        self.assertEqual(reasons, validator.BLOCKED_REASONS)

    def test_unstable_receipt_requires_distinct_observations(self):
        value = self.receipt(
            self.full_observation(),
            "CURRENT_STABLE_NO_MATCH",
            "CURRENT_STATE_NOT_REPRODUCED",
            "NONE",
            -1,
        )
        value["diagnostic_state"] = "UNSTABLE"
        value["reason_code"] = "OBSERVATION_UNSTABLE"
        value["before_after_equal"] = False
        with self.assertRaises(validator.Invalid):
            validator.validate(self.recommit(value))

    def test_validator_cli_rejects_duplicate_and_noncanonical_shapes(self):
        for raw in ('{"schema":"one","schema":"two"}', "[]", "null"):
            output = io.StringIO()
            with mock.patch.object(validator.Path, "read_text", return_value=raw), \
                    contextlib.redirect_stdout(output):
                status = validator.main(["validator", "/unused"])
            self.assertEqual(status, 1)
            self.assertEqual(
                output.getvalue(), "ITEM26_WRAPPER_PARENT_DIAGNOSTIC_INVALID\n"
            )

    def test_template_never_reads_wrapper_content_or_invokes_cli(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        for forbidden in (
            "os.path.realpath",
            "read_wrapper_bytes",
            "parse_wrapper",
            "import subprocess",
            "import socket",
            "import urllib",
            "os.system(",
            "os.exec",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("MAX_SYMLINK_HOPS = 8", source)
        self.assertIn('"wrapper_content_read_count": 0', source)
        self.assertIn('"cli_invocation_count": 0', source)


if __name__ == "__main__":
    unittest.main()
