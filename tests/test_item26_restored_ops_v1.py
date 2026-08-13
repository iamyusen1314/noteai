import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from tools import render_item26_restored_ops_v1 as ops


ROOT = Path(__file__).resolve().parents[1]


class Item26RestoredOpsV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.public = key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        der = key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        cls.recipient = hashlib.sha256(der).hexdigest()
        cls.compressor = staticmethod(lambda body: gzip.compress(body, 9, mtime=0))

    def rewrap(self):
        wrapped = b"".join(
            hashlib.sha256(f"item26-rewrap-{index}".encode("ascii")).digest()
            for index in range(12)
        )
        return ops.canonical({
            "account_exact": True,
            "automatic_retry_allowed": False,
            "database_connection_count": 0,
            "database_write_count": 0,
            "password_policy_exact": True,
            "provider_control_plane_mutation_count": 0,
            "recipient_public_key_sha256": self.recipient,
            "schema_version": 1,
            "secret_values_emitted": 0,
            "status": "PASSWORD_REWRAPPED",
            "wrapped_password": base64.b64encode(wrapped).decode("ascii"),
        })

    def fixtures(self):
        builder = ops.identity("i-builder123", ops.BUILDER_RAM_ROLE)
        envelope = json.dumps({
            "algorithm": "RSA-OAEP-SHA256+AES-256-GCM",
            "ciphertext": base64.b64encode(b"c" * 1200).decode("ascii"),
            "nonce": base64.b64encode(b"n" * 12).decode("ascii"),
            "schema_version": 1,
            "wrapped_key": base64.b64encode(b"k" * 384).decode("ascii"),
        }, sort_keys=True, separators=(",", ":")).encode("ascii")
        keygen = ops.canonical({
            "NOTEAI_ITEM26_RESTORED_BUILDER_KEYGEN": "PASS",
            "automatic_retry_allowed": False,
            "builder_identity_sha256": builder,
            "private_key_created": True,
            "private_key_pair_verified": True,
            "private_key_value_read_count": 1,
            "public_der_sha256": self.recipient,
            "public_key_pem_b64": base64.b64encode(self.public).decode("ascii"),
            "same_invocation_replay_allowed": False,
            "schema_version": 1,
        })
        create = ops.canonical({
            "control_envelope_b64": base64.b64encode(envelope).decode("ascii"),
            "control_envelope_bytes": len(envelope),
            "control_envelope_sha256": hashlib.sha256(envelope).hexdigest(),
            "recipient_public_key_sha256": self.recipient,
            "same_invocation_replay_allowed": False,
            "schema_version": 1,
            "secret_values_emitted": 0,
        })
        receipt = ops.canonical({
            "NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER": "PASS",
            "algorithm": "RSA-OAEP-SHA256+AES-256-GCM",
            "automatic_retry_allowed": False,
            "control_envelope_bytes": len(envelope),
            "control_envelope_sha256": hashlib.sha256(envelope).hexdigest(),
            "payload_schema_exact": True,
            "recipient_public_key_sha256": self.recipient,
            "restored_topology_sha256": "a" * 64,
            "same_invocation_replay_allowed": False,
            "schema_version": 1,
            "secret_values_emitted": 0,
            "source_manifest_bytes": ops.SOURCE_BYTES,
            "source_manifest_file_sha256": ops.SOURCE_FILE_SHA,
            "source_manifest_sha256": ops.SOURCE_SHA,
            "storage_config_sha256": "b" * 64,
        })
        return keygen, create, receipt

    def stage_receipt(self):
        return ops.canonical({
            "NOTEAI_ITEM26_RESTORED_BUILDER_STAGE": "PASS",
            "automatic_retry_allowed": False,
            "builder_identity_sha256": "a" * 64,
            "control_inventory_exact": True,
            "envelope_bytes": 1200,
            "envelope_sha256": "b" * 64,
            "materials_retained": True,
            "new_sendfile_allowed": False,
            "recipient_public_key_sha256": "c" * 64,
            "same_invocation_replay_allowed": False,
            "schema_version": 1,
            "secret_values_emitted": 0,
            "transfer_bytes": 4096,
            "transfer_sha256": "d" * 64,
        })

    def child(self, body, returncode=0, descriptor=None):
        if descriptor is None:
            descriptor = 1 if returncode == 0 else 2
        return (
            b"exec python3 -I -B - <<'PY'\n"
            b"import os\n"
            + f"body={body!r}\n".encode("ascii")
            + f"os.write({descriptor},body)\n".encode("ascii")
            + f"os._exit({returncode})\n".encode("ascii")
            + b"PY\n"
        )

    def run_loader(self, body, contract, returncode=0, descriptor=None, timeout=None):
        child = self.child(body, returncode, descriptor)
        expected_recipient = self.recipient if contract.startswith("rewrap_") else None
        rendered = (
            ops.wrapper(child, self.compressor, contract, expected_recipient)
            if timeout is None
            else ops._wrapper_for_test(
                child, self.compressor, contract, timeout,
                expected_recipient,
            )
        )
        loader = base64.b64decode(rendered["base64"], validate=True)
        return subprocess.run(
            ["bash", "-s"], input=loader, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False, timeout=10,
        )

    def production_render(self):
        builder = ops.identity("i-builder123", ops.BUILDER_RAM_ROLE)
        keygen, create, receipt_raw = self.fixtures()
        create_value = json.loads(create)
        receipt = json.loads(receipt_raw)
        envelope = base64.b64decode(create_value["control_envelope_b64"], validate=True)
        rendered = ops.capture._render_item26_restored_v1_transport_for_test(
            envelope, self.recipient, builder, ops.SOURCE_BYTES,
            ops.SOURCE_FILE_SHA, ops.SOURCE_SHA,
            receipt["restored_topology_sha256"],
            receipt["storage_config_sha256"],
            gzip_compressor=self.compressor,
        )
        summary = dict(rendered["sizing"])
        summary["production_provenance"] = ops.capture._production_provenance()
        summary["public_bindings"] = {
            "builder_identity_sha256": builder,
            "control_envelope_bytes": len(envelope),
            "control_envelope_sha256": hashlib.sha256(envelope).hexdigest(),
            "recipient_public_key_sha256": self.recipient,
            "restored_topology_sha256": receipt["restored_topology_sha256"],
            "source_manifest_bytes": ops.SOURCE_BYTES,
            "source_manifest_file_sha256": ops.SOURCE_FILE_SHA,
            "source_manifest_sha256": ops.SOURCE_SHA,
            "storage_config_sha256": receipt["storage_config_sha256"],
        }
        ops.capture.canonical_summary(summary)
        return {"artifacts": rendered["artifacts"], "summary": summary}

    def test_all_operational_commands_and_sendfiles_are_bounded(self):
        keygen = ops.keygen_commands(
            "i-builder123", ops.BUILDER_RAM_ROLE, self.compressor,
        )
        rewrap = ops.rewrap_commands(
            "i-api123", "api-role", self.public, self.compressor,
        )
        broker = ops.broker_commands(
            "i-api123", "api-role", "restore.example.rds.aliyuncs.com",
            self.public, self.rewrap(), self.compressor,
        )
        result = ops._post_broker_for_test(
            "i-builder123", ops.BUILDER_RAM_ROLE,
            *self.fixtures(), self.compressor,
        )
        commands = list(keygen["commands"].values()) + list(rewrap["commands"].values())
        commands += list(broker["commands"].values())
        commands += [result["finalize_command"], result["readback_command"], result["capture_command_content"]]
        self.assertTrue(all(row["bytes"] <= 18000 for row in commands))
        self.assertEqual(rewrap["recipient_public_key_sha256"], self.recipient)
        self.assertEqual(rewrap["template"], dict(ops.IDENTITIES["rewrap"]))
        self.assertEqual([row["request"]["Overwrite"] for row in result["send_files"]], [False, False])
        self.assertTrue(all(row["evidence"]["content_base64_bytes"] <= 18000 for row in result["send_files"]))
        self.assertEqual(result["send_files"][0]["request"]["Name"], "control-envelope.json")
        self.assertEqual(result["send_files"][1]["request"]["Name"], "restored-capture-transfer-v1.sh.gz")
        official = {"Content", "ContentType", "Description", "FileGroup", "FileMode", "FileOwner", "InstanceId", "Name", "Overwrite", "RegionId", "Tag", "TargetDir"}
        for row in result["send_files"]:
            self.assertEqual(set(row), {"evidence", "request"})
            self.assertEqual(set(row["request"]), official)
            self.assertEqual(set(row["evidence"]), {"content_base64_bytes", "content_sha256"})
            self.assertEqual(row["request"]["RegionId"], "cn-shenzhen")
            self.assertEqual(row["request"]["InstanceId"], ["i-builder123"])
            self.assertEqual(row["request"]["Tag"], [{"Key": "noteai-task", "Value": "item26-restored-v1"}])
            self.assertNotIn("TargetFileName", row["request"])

    def test_templates_are_exact_and_rendered_syntax_is_valid(self):
        for name, expected in ops.IDENTITIES.items():
            body = ops.PATHS[name].read_bytes()
            self.assertEqual((len(body), hashlib.sha256(body).hexdigest()), (expected["bytes"], expected["sha256"]))
        subprocess.run(["bash", "-n", str(ops.PATHS["stage"])], check=True)
        raw = ops.render("stage", ops.stage_bindings("READBACK", "a" * 64, "b" * 64, b"{}", b"x"))
        subprocess.run(["bash", "-n", "-s"], input=raw, check=True)
        rewrap_raw = ops.render("rewrap", {
            b"@@MODE@@": b"READBACK",
            b"@@API_C_IDENTITY_SHA256@@": b"a" * 64,
            b"@@RECIPIENT_PUBLIC_KEY_SHA256@@": b"b" * 64,
            b"@@RECIPIENT_PUBLIC_KEY_B64@@": base64.b64encode(self.public),
        })
        subprocess.run(["bash", "-n", "-s"], input=rewrap_raw, check=True)
        keygen, create, receipt = self.fixtures()
        stage_state = ops.canonical({
            "NOTEAI_ITEM26_RESTORED_BUILDER_STAGE": "READY_TO_FINALIZE",
            "automatic_retry_allowed": False,
            "finalize_allowed": True,
            "materials_retained": True,
            "new_sendfile_allowed": False,
            "same_invocation_replay_allowed": False,
            "secret_values_emitted": 0,
        })
        for contract, body in (
            ("keygen", keygen), ("broker_create", create),
            ("broker_readback", receipt),
            ("rewrap_create", self.rewrap()),
            ("rewrap_readback", self.rewrap()),
            ("stage_finalize", self.stage_receipt()),
            ("stage_readback", stage_state),
        ):
            result = self.run_loader(body, contract)
            self.assertEqual(
                (result.returncode, result.stdout, result.stderr),
                (0, body, b""), contract,
            )

    def test_loader_validates_failure_streams_and_suppresses_invalid_raw(self):
        fail = ops.canonical({
            "NOTEAI_ITEM26_RESTORED_BUILDER_KEYGEN": "FAIL",
            "automatic_retry_allowed": False,
            "phase": "root",
            "private_key_value_read_count": 0,
            "same_invocation_replay_allowed": False,
        })
        unknown = ops.canonical({
            "NOTEAI_ITEM26_RESTORED_PACKAGE_BROKER": "UNKNOWN",
            "automatic_retry_allowed": False,
            "phase": "unexpected",
            "same_invocation_replay_allowed": False,
            "secret_values_emitted": 0,
        })
        rewrap_fail = ops.canonical({
            "NOTEAI_ITEM26_PASSWORD_REWRAP": "FAIL",
            "automatic_retry_allowed": False,
            "database_connection_count": 0,
            "database_write_count": 0,
            "incident_class": "PRE_ATTEMPT",
            "new_rewrap_allowed": False,
            "phase": "root",
            "provider_control_plane_mutation_count": 0,
            "readback_required": False,
            "same_invocation_replay_allowed": False,
            "secret_values_emitted": 0,
        })
        rewrap_unknown = ops.canonical({
            "NOTEAI_ITEM26_PASSWORD_REWRAP": "UNKNOWN",
            "automatic_retry_allowed": False,
            "database_connection_count": 0,
            "database_write_count": 0,
            "incident_class": "ATTEMPTED_UNKNOWN",
            "new_rewrap_allowed": False,
            "phase": "readback_absent",
            "provider_control_plane_mutation_count": 0,
            "readback_required": True,
            "same_invocation_replay_allowed": False,
            "secret_values_emitted": 0,
        })
        for contract, body, returncode in (
            ("keygen", fail, 3), ("broker_create", unknown, 4),
            ("rewrap_create", rewrap_fail, 3),
            ("rewrap_readback", rewrap_unknown, 4),
        ):
            result = self.run_loader(body, contract, returncode)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (returncode, b"", body))

        fixed = b'{"NOTEAI_ITEM26_RESTORED_OPS_LOADER":"UNKNOWN","automatic_retry_allowed":false,"same_invocation_replay_allowed":false}\n'
        keygen = json.loads(self.fixtures()[0])
        invalid = []
        invalid.append((self.fixtures()[0].replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'), 0, None))
        invalid.append((ops.canonical({**keygen, "private_key_created": 1}), 0, None))
        invalid.append((ops.canonical({**keygen, "unexpected_secret_marker": "must-not-leak"}), 0, None))
        invalid.append((self.fixtures()[0], 0, 2))
        bad_phase = json.loads(fail)
        bad_phase["phase"] = "must-not-leak"
        invalid.append((ops.canonical(bad_phase), 3, None))
        for body, returncode, descriptor in invalid:
            result = self.run_loader(body, "keygen", returncode, descriptor)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (4, b"", fixed))
            self.assertNotIn(b"must-not-leak", result.stderr)

        _keygen, create, receipt = self.fixtures()
        stage_receipt = json.loads(self.stage_receipt())
        stage_state = {
            "NOTEAI_ITEM26_RESTORED_BUILDER_STAGE": "READY_TO_FINALIZE",
            "automatic_retry_allowed": False,
            "finalize_allowed": 1,
            "materials_retained": True,
            "new_sendfile_allowed": False,
            "same_invocation_replay_allowed": False,
            "secret_values_emitted": 0,
        }
        wrong_types = (
            ("broker_create", {**json.loads(create), "secret_values_emitted": False}),
            ("broker_readback", {**json.loads(receipt), "source_manifest_bytes": True}),
            ("rewrap_create", {**json.loads(self.rewrap()), "database_connection_count": False}),
            ("rewrap_readback", {**json.loads(self.rewrap()), "schema_version": True}),
            ("stage_finalize", {**stage_receipt, "transfer_bytes": True}),
            ("stage_readback", stage_state),
        )
        for contract, value in wrong_types:
            result = self.run_loader(ops.canonical(value), contract)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (4, b"", fixed))

    def test_loader_timeout_kills_the_entire_process_group(self):
        fixed = b'{"NOTEAI_ITEM26_RESTORED_OPS_LOADER":"UNKNOWN","automatic_retry_allowed":false,"same_invocation_replay_allowed":false}\n'
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "orphan-marker"
            child = (
                b"( sleep 2; printf x > " + shlex.quote(str(marker)).encode("ascii")
                + b" ) &\nwait\n"
            )
            rendered = ops._wrapper_for_test(child, self.compressor, "keygen", 1)
            loader = base64.b64decode(rendered["base64"], validate=True)
            result = subprocess.run(
                ["bash", "-s"], input=loader, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, check=False, timeout=5,
            )
            self.assertEqual((result.returncode, result.stdout, result.stderr), (4, b"", fixed))
            time.sleep(2.2)
            self.assertFalse(marker.exists())

    def test_production_post_broker_uses_public_renderer_and_returns_validated_summary(self):
        rendered = self.production_render()
        with mock.patch.object(
            ops.capture, "render_item26_restored_v1_transport",
            return_value=rendered,
        ) as public_renderer, mock.patch.object(
            ops.capture, "_render_item26_restored_v1_transport_for_test",
            side_effect=AssertionError("test-only renderer reached production"),
        ), mock.patch.object(
            ops, "production_compressor", return_value=self.compressor,
        ):
            result = ops.post_broker(
                "i-builder123", ops.BUILDER_RAM_ROLE, *self.fixtures(),
            )
        public_renderer.assert_called_once()
        self.assertEqual(result["capture_summary"], rendered["summary"])
        self.assertEqual(
            ops.capture.canonical_summary(result["capture_summary"]),
            ops.capture.canonical_summary(rendered["summary"]),
        )

    def test_rewrap_cli_returns_the_exact_render_summary(self):
        request = ops.canonical({
            "api_c_instance_id": "i-api123",
            "api_c_ram_role": "api-role",
            "mode": "rewrap",
            "recipient_public_key_pem_base64": base64.b64encode(self.public).decode("ascii"),
        })
        stdin = mock.Mock()
        stdin.buffer = io.BytesIO(request)
        stdout = mock.Mock()
        stdout.buffer = io.BytesIO()
        with mock.patch.object(ops.sys, "stdin", stdin), mock.patch.object(
            ops.sys, "stdout", stdout,
        ), mock.patch.object(
            ops, "production_compressor", return_value=self.compressor,
        ):
            returncode = ops.cli()
        self.assertEqual(returncode, 0)
        summary = json.loads(stdout.buffer.getvalue())
        self.assertEqual(
            set(summary),
            {"api_c_identity_sha256", "commands", "recipient_public_key_sha256", "template"},
        )
        self.assertEqual(set(summary["commands"]), {"create", "readback"})
        self.assertEqual(summary["recipient_public_key_sha256"], self.recipient)
        self.assertEqual(summary["template"], dict(ops.IDENTITIES["rewrap"]))

    def test_stage_has_four_states_and_durable_no_replay_guards(self):
        source = ops.PATHS["stage"].read_text()
        for marker in ("KEYGEN_ONLY", "ENVELOPE_EXACT", "READY_TO_FINALIZE", '"PASS"', "os.O_EXCL|os.O_NOFOLLOW", "os.fsync(fd)", "fsync_dir(CONTROL)", "new_sendfile_allowed"):
            self.assertIn(marker, source)
        self.assertNotIn("STAGE_PART", source)

    def test_rejects_shell_host_and_duplicate_rewrap(self):
        with self.assertRaises(ops.RenderError):
            ops.broker_commands("i-api123", "api-role", "$(id).rds.aliyuncs.com", self.public, self.rewrap(), self.compressor)
        bad = self.rewrap().replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
        with self.assertRaises(ops.RenderError):
            ops.broker_commands("i-api123", "api-role", "restore.example.rds.aliyuncs.com", self.public, bad, self.compressor)

    def test_outer_validators_reject_bool_integer_aliases_and_wrong_algorithm(self):
        builder = ops.identity("i-builder123", ops.BUILDER_RAM_ROLE)
        keygen_raw, create_raw, receipt_raw = self.fixtures()
        keygen = json.loads(keygen_raw)
        for field in ("schema_version", "private_key_value_read_count"):
            mutated = dict(keygen)
            mutated[field] = True
            with self.subTest(contract="keygen", field=field), self.assertRaises(ops.RenderError):
                ops.validate_keygen(mutated, builder)

        rewrap = json.loads(self.rewrap())
        for field, value in (
            ("schema_version", True),
            ("database_connection_count", False),
            ("database_write_count", False),
            ("provider_control_plane_mutation_count", False),
            ("secret_values_emitted", False),
        ):
            mutated = dict(rewrap)
            mutated[field] = value
            with self.subTest(contract="rewrap", field=field), self.assertRaises(ops.RenderError):
                ops.validate_rewrap(ops.canonical(mutated), self.recipient)

        create = json.loads(create_raw)
        receipt = json.loads(receipt_raw)
        for field, value in (
            ("schema_version", True),
            ("control_envelope_bytes", True),
            ("secret_values_emitted", False),
        ):
            mutated = dict(create)
            mutated[field] = value
            with self.subTest(contract="broker_create", field=field), self.assertRaises(ops.RenderError):
                ops.validate_broker(mutated, receipt, self.recipient)
        for field, value in (
            ("schema_version", True),
            ("control_envelope_bytes", True),
            ("source_manifest_bytes", True),
            ("secret_values_emitted", False),
            ("algorithm", "RSA-OAEP-SHA1+AES-256-GCM"),
        ):
            mutated = dict(receipt)
            mutated[field] = value
            with self.subTest(contract="broker_readback", field=field), self.assertRaises(ops.RenderError):
                ops.validate_broker(create, mutated, self.recipient)

    def test_builder_role_is_fixed_before_render_or_post_broker(self):
        with self.assertRaisesRegex(ops.RenderError, "builder_ram_role"):
            ops.keygen_commands("i-builder123", "other-role", self.compressor)
        with self.assertRaisesRegex(ops.RenderError, "builder_ram_role"):
            ops._post_broker_for_test(
                "i-builder123", "other-role", *self.fixtures(), self.compressor,
            )


if __name__ == "__main__":
    unittest.main()
