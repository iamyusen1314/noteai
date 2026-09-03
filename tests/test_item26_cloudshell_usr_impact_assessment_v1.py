import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import stat
import types
import unittest
from pathlib import Path
from unittest import mock

from tools import validate_item26_cloudshell_usr_impact_assessment_v1 as validator


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / ".codex" / "item26-cloudshell-usr-impact-assessment-v1.template.py"
SPEC = importlib.util.spec_from_file_location("item26_usr_impact_atom", TEMPLATE)
atom = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(atom)


class Item26CloudShellUsrImpactAssessmentTests(unittest.TestCase):
    def mount(self, access="READ_WRITE", filesystem="OVERLAY"):
        return {
            "filesystem_class": filesystem,
            "mountpoint_class": "ROOT",
            "access_mode": access,
            "propagation": "PRIVATE",
            "filesystem_root_class": "FS_ROOT",
            "noexec": False,
            "nosuid": False,
            "nodev": False,
            "upperdir_present": filesystem == "OVERLAY",
            "usr_mount_mode_class": "NOT_APPLICABLE",
        }

    def observation(
        self,
        usr_class="ROOT_OWNED_STICKY_EXACT_1777",
        access="READ_WRITE",
        shell_trusted=True,
    ):
        return {
            "root_prerequisite_satisfied": True,
            "usr_exact_predecessor_mode": (
                usr_class == "ROOT_OWNED_STICKY_EXACT_1777"
            ),
            "usr_current_class": usr_class,
            "fixed_shell_component_trusted": shell_trusted,
            "mount": self.mount(access),
            "pid1_mount_namespace_relation": "SAME_AS_PID1",
        }

    def receipt(self, observation, state=None):
        access = observation["mount"]["access_mode"]
        usr_class = observation["usr_current_class"]
        if state is None:
            if usr_class == "ROOT_OWNED_NON_GROUP_OTHER_WRITABLE":
                state = "CURRENT_STABLE_SAFE_CURRENT_METADATA"
            elif usr_class == "UNSAFE_OR_UNKNOWN":
                state = "CURRENT_STABLE_UNSAFE_OR_UNKNOWN"
            elif access == "READ_ONLY":
                state = "CURRENT_STABLE_MOUNT_READ_ONLY"
            else:
                state = "CURRENT_STABLE_MOUNT_READ_WRITE"
        reasons = {
            "CURRENT_STABLE_SAFE_CURRENT_METADATA": (
                "PREDECESSOR_NOT_REPRODUCED_SAFE_CURRENT_METADATA"
            ),
            "CURRENT_STABLE_UNSAFE_OR_UNKNOWN": (
                "USR_CURRENT_METADATA_UNSAFE_OR_UNKNOWN"
            ),
            "CURRENT_STABLE_MOUNT_READ_ONLY": (
                "USR_WRITABLE_BITS_MOUNT_READ_ONLY"
            ),
            "CURRENT_STABLE_MOUNT_READ_WRITE": (
                "USR_WRITABLE_BITS_MOUNT_READ_WRITE"
            ),
        }
        if state == "CURRENT_STABLE_MOUNT_READ_ONLY":
            candidate = "READ_ONLY_MOUNT"
        elif (
            state == "CURRENT_STABLE_MOUNT_READ_WRITE"
            and observation["fixed_shell_component_trusted"]
            and observation["mount"]["filesystem_class"]
            in ("OVERLAY", "TMPFS")
        ):
            candidate = "ROOT_OWNED_STICKY_EXACT_USR"
        else:
            candidate = "NONE"
        value = {
            "schema": validator.SCHEMA,
            "status": "BLOCKED",
            "predecessor": copy.deepcopy(validator.PREDECESSOR),
            "scope": copy.deepcopy(validator.SCOPE),
            "assessment_complete": True,
            "assessment_state": state,
            "reason_code": reasons[state],
            "before": copy.deepcopy(observation),
            "after": copy.deepcopy(observation),
            "before_after_equal": True,
            "pinned_private_state_equal": True,
            "offline_allowlist_candidate": candidate,
            "effective_mount_read_write_observed": access == "READ_WRITE",
            "read_only_mount_observed": access == "READ_ONLY",
        }
        value.update(copy.deepcopy(validator.BOUNDARY_VALUES))
        return self.recommit(value)

    def recommit(self, value):
        payload = {
            key: item for key, item in value.items()
            if key != "commitment_sha256"
        }
        value["commitment_sha256"] = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        return value

    def private(self, fd, mount_id=9, raw="selected-line"):
        return {
            "usr_fd": fd,
            "root_stat": (1,),
            "usr_stat": (2,),
            "shell_stat": (3,),
            "self_ns_stat": (4,),
            "pid1_ns_stat": (4,),
            "mount_id": mount_id,
            "selected_mount_raw": raw,
        }

    def test_validator_accepts_only_terminal_stable_classes(self):
        values = (
            self.receipt(self.observation()),
            self.receipt(self.observation(access="READ_ONLY")),
            self.receipt(self.observation(
                usr_class="ROOT_OWNED_NON_GROUP_OTHER_WRITABLE"
            )),
            self.receipt(self.observation(
                usr_class="UNSAFE_OR_UNKNOWN", shell_trusted=False
            )),
        )
        for value in values:
            with self.subTest(state=value["assessment_state"]):
                self.assertEqual(
                    validator.validate(value),
                    (value["assessment_state"], value["commitment_sha256"]),
                )
                self.assertEqual(value["status"], "BLOCKED")
                self.assertFalse(value["allowlist_proven_safe"])
                self.assertFalse(value["next_stage_authorized"])
                self.assertFalse(value["mutation_authorized"])
                self.assertFalse(value["effective_write_access_proven"])

    def test_rw_is_only_a_mount_flag_not_dac_or_effective_access(self):
        value = self.receipt(self.observation())
        self.assertTrue(value["effective_mount_read_write_observed"])
        self.assertFalse(value["effective_write_access_proven"])
        self.assertFalse(value["process_privilege_assessed"])
        self.assertFalse(value["user_namespace_assessed"])
        self.assertFalse(value["idmapped_mount_semantics_assessed"])
        self.assertFalse(value["cross_namespace_metadata_visibility_proven"])
        self.assertFalse(value["platform_operator_intent_proven"])

    def test_unsafe_current_cannot_be_relabelled_safe_or_allowlisted(self):
        value = self.receipt(self.observation(
            usr_class="UNSAFE_OR_UNKNOWN", shell_trusted=False
        ))
        mutations = []
        for key, replacement in (
            ("assessment_state", "CURRENT_STABLE_SAFE_CURRENT_METADATA"),
            ("offline_allowlist_candidate", "ROOT_OWNED_STICKY_EXACT_USR"),
            ("reason_code", "PREDECESSOR_NOT_REPRODUCED_SAFE_CURRENT_METADATA"),
        ):
            changed = copy.deepcopy(value)
            changed[key] = replacement
            mutations.append(self.recommit(changed))
        for changed in mutations:
            with self.assertRaises(validator.Invalid):
                validator.validate(changed)

    def test_usr_stat_classifier_separates_safe_and_unsafe_drift(self):
        def metadata(mode, uid=0, gid=0, nlink=1):
            return types.SimpleNamespace(
                st_mode=stat.S_IFDIR | mode,
                st_uid=uid,
                st_gid=gid,
                st_nlink=nlink,
            )

        self.assertEqual(
            atom.classify_usr_stat(metadata(0o1777)),
            "ROOT_OWNED_STICKY_EXACT_1777",
        )
        self.assertEqual(
            atom.classify_usr_stat(metadata(0o0755)),
            "ROOT_OWNED_NON_GROUP_OTHER_WRITABLE",
        )
        for value in (
            metadata(0o0777),
            metadata(0o1777, uid=1000),
            metadata(0o1777, nlink=2),
        ):
            with self.subTest(value=value):
                self.assertEqual(
                atom.classify_usr_stat(value), "UNSAFE_OR_UNKNOWN"
                )

        self.assertTrue(atom.fixed_shell_component_trusted(metadata(0o0755)))
        self.assertFalse(
            atom.fixed_shell_component_trusted(metadata(0o0755, nlink=0))
        )

    def test_validator_binds_exact_predecessor_and_recursive_types(self):
        value = self.receipt(self.observation())
        mutations = []
        changed = copy.deepcopy(value)
        changed["predecessor"]["nlink"] = 1.0
        mutations.append(self.recommit(changed))
        changed = copy.deepcopy(value)
        changed["predecessor"]["receipt_bytes"] = True
        mutations.append(self.recommit(changed))
        changed = copy.deepcopy(value)
        changed["before"]["usr_exact_predecessor_mode"] = 1
        changed["after"]["usr_exact_predecessor_mode"] = 1
        mutations.append(self.recommit(changed))
        changed = copy.deepcopy(value)
        changed["proc_mountinfo_read_limit"] = 2.0
        mutations.append(self.recommit(changed))
        for changed in mutations:
            with self.assertRaises(validator.Invalid):
                validator.validate(changed)

    def test_validator_rejects_raw_identifiers_paths_and_nonallowlisted_keys(self):
        value = self.receipt(self.observation())
        for key, leaked in (
            ("mount_id", 44),
            ("mount_source", "/private/source"),
            ("device_major", 8),
            ("upperdir", "/private/upper"),
        ):
            changed = copy.deepcopy(value)
            changed["before"]["mount"][key] = leaked
            changed["after"]["mount"][key] = leaked
            with self.subTest(key=key), self.assertRaises(validator.Invalid):
                validator.validate(self.recommit(changed))

    def test_mount_projection_uses_exact_fdinfo_id_and_emits_only_classes(self):
        raw = (
            "41 1 0:7 / /usr rw - tmpfs hidden rw\n"
            "42 1 0:7 / / rw,nosuid,nodev shared:8 - overlay hidden "
            "rw,lowerdir=/private/l,upperdir=/private/u,workdir=/private/w\n"
        ).encode("ascii")
        metadata = types.SimpleNamespace(st_dev=os.makedev(0, 7))
        normalized, selected_raw = atom.selected_mount(raw, 42, metadata)
        self.assertEqual(normalized, {
            "filesystem_class": "OVERLAY",
            "mountpoint_class": "ROOT",
            "access_mode": "READ_WRITE",
            "propagation": "SHARED",
            "filesystem_root_class": "FS_ROOT",
            "noexec": False,
            "nosuid": True,
            "nodev": True,
            "upperdir_present": True,
            "usr_mount_mode_class": "NOT_APPLICABLE",
        })
        self.assertIn("/private/u", selected_raw)
        emitted = json.dumps(normalized, sort_keys=True)
        self.assertNotIn("private", emitted)
        self.assertNotIn("mount_id", emitted)
        self.assertNotIn("device", emitted)

    def test_superblock_ro_overrides_per_mount_rw(self):
        raw = b"42 1 0:7 /sub /usr rw,noexec - ext4 hidden ro\n"
        metadata = types.SimpleNamespace(st_dev=os.makedev(0, 7))
        normalized, _ = atom.selected_mount(raw, 42, metadata)
        self.assertEqual(normalized["access_mode"], "READ_ONLY")
        self.assertEqual(normalized["filesystem_root_class"], "SUBTREE")
        self.assertEqual(normalized["mountpoint_class"], "EXACT_USR")
        self.assertEqual(normalized["usr_mount_mode_class"], "ABSENT")

    def test_exact_usr_mount_mode_is_allowlisted_without_value_leak(self):
        metadata = types.SimpleNamespace(st_dev=os.makedev(0, 7))
        cases = (
            ("rw,mode=1777", "EXPLICIT_1777"),
            ("rw", "ABSENT"),
            ("rw,mode=0755", "OTHER_OR_AMBIGUOUS"),
        )
        for super_options, expected in cases:
            raw = (
                "42 1 0:7 / /usr rw - tmpfs hidden %s\n"
                % super_options
            ).encode("ascii")
            normalized, _ = atom.selected_mount(raw, 42, metadata)
            with self.subTest(super_options=super_options):
                self.assertEqual(normalized["usr_mount_mode_class"], expected)
                self.assertNotIn("0755", json.dumps(normalized))
        duplicate = (
            b"42 1 0:7 / /usr rw - tmpfs hidden "
            b"rw,mode=1777,mode=1777\n"
        )
        with self.assertRaises(atom.AssessmentBlocked) as raised:
            atom.selected_mount(duplicate, 42, metadata)
        self.assertEqual(
            raised.exception.code, "MOUNTINFO_MODE_OPTION_DUPLICATE"
        )

    def test_other_filesystem_never_gets_sticky_candidate(self):
        value = self.receipt(self.observation())
        value["before"]["mount"]["filesystem_class"] = "OTHER"
        value["after"]["mount"]["filesystem_class"] = "OTHER"
        value["before"]["mount"]["upperdir_present"] = False
        value["after"]["mount"]["upperdir_present"] = False
        value["offline_allowlist_candidate"] = "NONE"
        self.assertEqual(
            validator.validate(self.recommit(value))[0],
            "CURRENT_STABLE_MOUNT_READ_WRITE",
        )

    def test_mount_selection_rejects_duplicate_id_and_wrong_device(self):
        line = "42 1 0:7 / / rw - tmpfs hidden rw\n"
        metadata = types.SimpleNamespace(st_dev=os.makedev(0, 7))
        with self.assertRaises(atom.AssessmentBlocked) as duplicate:
            atom.selected_mount((line + line).encode("ascii"), 42, metadata)
        self.assertEqual(duplicate.exception.code, "SELECTED_MOUNT_NOT_UNIQUE")
        wrong = types.SimpleNamespace(st_dev=os.makedev(0, 8))
        with self.assertRaises(atom.AssessmentBlocked) as mismatch:
            atom.selected_mount(line.encode("ascii"), 42, wrong)
        self.assertEqual(
            mismatch.exception.code, "SELECTED_MOUNT_DEVICE_MISMATCH"
        )

    def test_fdinfo_requires_one_mount_id(self):
        with mock.patch.object(
            atom, "read_bounded", return_value=b"pos:\t0\nmnt_id:\t42\n"
        ):
            self.assertEqual(atom.pinned_mount_id(9), 42)
        for raw in (b"pos:\t0\n", b"mnt_id:\t42\nmnt_id:\t43\n"):
            with mock.patch.object(atom, "read_bounded", return_value=raw):
                with self.assertRaises(atom.AssessmentBlocked) as raised:
                    atom.pinned_mount_id(9)
            self.assertEqual(
                raised.exception.code, "FDINFO_MOUNT_ID_NOT_UNIQUE"
            )

    def test_diagnose_detects_private_raw_mount_drift_without_emitting_it(self):
        observation = self.observation()
        with mock.patch.object(
            atom,
            "observe_once",
            side_effect=[
                (copy.deepcopy(observation), self.private(10, raw="line-a"), []),
                (copy.deepcopy(observation), self.private(11, raw="line-b"), []),
            ],
        ), contextlib.redirect_stdout(io.StringIO()) as output:
            status = atom.diagnose()
        self.assertEqual(status, 4)
        value = json.loads(output.getvalue())
        self.assertEqual(value["assessment_state"], "UNSTABLE")
        self.assertTrue(value["before_after_equal"])
        self.assertFalse(value["pinned_private_state_equal"])
        self.assertNotIn("line-a", output.getvalue())
        self.assertNotIn("line-b", output.getvalue())
        self.assertEqual(validator.validate(value)[0], "UNSTABLE")

    def test_diagnose_stable_rw_is_blocked_candidate_only(self):
        observation = self.observation()
        with mock.patch.object(
            atom,
            "observe_once",
            side_effect=[
                (copy.deepcopy(observation), self.private(10), []),
                (copy.deepcopy(observation), self.private(11), []),
            ],
        ), contextlib.redirect_stdout(io.StringIO()) as output:
            status = atom.diagnose()
        self.assertEqual(status, 3)
        value = json.loads(output.getvalue())
        self.assertEqual(value["assessment_state"], "CURRENT_STABLE_MOUNT_READ_WRITE")
        self.assertEqual(
            value["offline_allowlist_candidate"],
            "ROOT_OWNED_STICKY_EXACT_USR",
        )
        self.assertFalse(value["allowlist_proven_safe"])
        self.assertFalse(value["deeper_execution_chain_verified"])
        self.assertTrue(value["same_fd_chain_execution_required"])
        self.assertTrue(value["execveat_equivalent_required"])
        self.assertEqual(validator.validate(value)[0], value["assessment_state"])

    def test_blocked_receipt_is_empty_terminal(self):
        with mock.patch.object(
            atom,
            "observe_once",
            side_effect=atom.AssessmentBlocked("USR_NOT_DIRECTORY"),
        ), contextlib.redirect_stdout(io.StringIO()) as output:
            status = atom.main()
        self.assertEqual(status, 3)
        value = json.loads(output.getvalue())
        self.assertEqual(validator.validate(value)[0], "OBSERVATION_BLOCKED")
        self.assertEqual(value["offline_allowlist_candidate"], "NONE")

    def test_validator_rejects_commitment_boundary_and_projection_forgery(self):
        value = self.receipt(self.observation())
        mutations = []
        changed = copy.deepcopy(value)
        changed["allowlist_proven_safe"] = True
        mutations.append(self.recommit(changed))
        changed = copy.deepcopy(value)
        changed["commitment_sha256"] = "0" * 64
        mutations.append(changed)
        changed = copy.deepcopy(value)
        changed["before"]["mount"]["filesystem_class"] = "OTHER"
        changed["after"]["mount"]["filesystem_class"] = "OTHER"
        changed["before"]["mount"]["upperdir_present"] = True
        changed["after"]["mount"]["upperdir_present"] = True
        mutations.append(self.recommit(changed))
        for changed in mutations:
            with self.assertRaises(validator.Invalid):
                validator.validate(changed)

    def test_validator_cli_rejects_duplicate_and_nonobject_json(self):
        for raw in ('{"schema":"one","schema":"two"}', "[]", "null"):
            with mock.patch.object(
                validator.Path, "read_text", return_value=raw
            ), contextlib.redirect_stdout(io.StringIO()) as output:
                status = validator.main(["validator", "/unused"])
            self.assertEqual(status, 1)
            self.assertEqual(
                output.getvalue(), "ITEM26_USR_IMPACT_ASSESSMENT_INVALID\n"
            )

    def test_source_is_bounded_read_only_and_relative_fd_chained(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        for forbidden in (
            "import subprocess",
            "import socket",
            "import urllib",
            "import requests",
            "os.listdir(",
            "os.scandir(",
            "os.walk(",
            "os.system(",
            "os.exec",
            "os.chmod(",
            "os.chown(",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn('dir_fd=root_handle["fd"]', source)
        self.assertIn('dir_fd=usr_handle["fd"]', source)
        self.assertIn('MAX_MOUNTINFO_BYTES = 1024 * 1024', source)
        self.assertIn('MAX_MOUNTINFO_LINES = 4096', source)
        self.assertIn('MAX_MOUNTINFO_LINE_BYTES = 64 * 1024', source)
        self.assertIn('"wrapper_content_read_count": 0', source)
        self.assertIn('"cli_invocation_count": 0', source)
        self.assertIn('"host_write_count": 0', source)


if __name__ == "__main__":
    unittest.main()
