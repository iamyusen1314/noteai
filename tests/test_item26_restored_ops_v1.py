import base64
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

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
            "wrapped_password": base64.b64encode(b"w" * 384).decode("ascii"),
        })

    def fixtures(self):
        builder = ops.identity("i-builder123", "builder-role")
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

    def test_all_operational_commands_and_sendfiles_are_bounded(self):
        keygen = ops.keygen_commands("i-builder123", "builder-role", self.compressor)
        broker = ops.broker_commands(
            "i-api123", "api-role", "restore.example.rds.aliyuncs.com",
            self.public, self.rewrap(), self.compressor,
        )
        result = ops.post_broker(
            "i-builder123", "builder-role", *self.fixtures(), self.compressor,
        )
        commands = list(keygen["commands"].values()) + list(broker["commands"].values())
        commands += [result["finalize_command"], result["readback_command"], result["capture_command_content"]]
        self.assertTrue(all(row["bytes"] <= 18000 for row in commands))
        self.assertEqual([row["Overwrite"] for row in result["send_files"]], [False, False])
        self.assertTrue(all(row["content_base64_bytes"] <= 18000 for row in result["send_files"]))
        self.assertEqual(result["send_files"][0]["Name"], "control-envelope.json")
        self.assertEqual(result["send_files"][1]["Name"], "restored-capture-transfer-v1.sh.gz")
        for row in result["send_files"]:
            self.assertEqual(row["RegionId"], "cn-shenzhen")
            self.assertEqual(row["InstanceId"], ["i-builder123"])
            self.assertEqual(row["Tag"], [{"Key": "noteai-task", "Value": "item26-restored-v1"}])
            self.assertNotIn("TargetFileName", row)

    def test_templates_are_exact_and_rendered_syntax_is_valid(self):
        for name, expected in ops.IDENTITIES.items():
            body = ops.PATHS[name].read_bytes()
            self.assertEqual((len(body), hashlib.sha256(body).hexdigest()), (expected["bytes"], expected["sha256"]))
        subprocess.run(["bash", "-n", str(ops.PATHS["stage"])], check=True)
        raw = ops.render("stage", ops.stage_bindings("READBACK", "a" * 64, "b" * 64, b"{}", b"x"))
        subprocess.run(["bash", "-n", "-s"], input=raw, check=True)
        loader = base64.b64decode(ops.wrapper(b"printf 'ok\\n'", self.compressor)["base64"], validate=True)
        result = subprocess.run(["bash", "-s"], input=loader, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"ok\n", b""))

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


if __name__ == "__main__":
    unittest.main()
