import base64
import gzip
import hashlib
import io
import json
import os
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

    def rewrap(self, wrapped=None):
        if wrapped is None:
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
        transport = {
            "control_envelope_b64": base64.b64encode(envelope).decode("ascii"),
            "control_envelope_bytes": len(envelope),
            "control_envelope_sha256": hashlib.sha256(envelope).hexdigest(),
            "recipient_public_key_sha256": self.recipient,
            "same_invocation_replay_allowed": False,
            "schema_version": 1,
            "secret_values_emitted": 0,
        }
        receipt = {
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
        }
        composite = ops.canonical({"receipt": receipt, "transport": transport})
        return keygen, composite, ops.canonical(transport)

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
        expected_recipient = (
            self.recipient
            if contract.startswith("rewrap_") or contract == "broker_readback"
            else None
        )
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
        keygen, readback_raw, create = self.fixtures()
        composite = json.loads(readback_raw)
        receipt = composite["receipt"]
        envelope = base64.b64decode(
            composite["transport"]["control_envelope_b64"], validate=True,
        )
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
        self.assertEqual(broker["state_machine"], {
            "create": {"0": "READBACK_REQUIRED", "3": "STOP", "4": "READBACK_REQUIRED"},
            "post_broker_requires_composite": True,
            "readback": {"0": "POST_BROKER_ALLOWED", "3": "STOP", "4": "STOP"},
            "readback_dispatch_count": 1,
        })
        self.assertEqual([row["request"]["Overwrite"] for row in result["send_files"]], [False, False])
        self.assertTrue(all(row["evidence"]["content_base64_bytes"] <= 18000 for row in result["send_files"]))
        self.assertEqual(result["send_files"][0]["request"]["Name"], "control-envelope-successor-v1.json")
        self.assertEqual(result["send_files"][1]["request"]["Name"], "restored-capture-transfer-successor-v1.sh.gz")
        official = {"Content", "ContentType", "Description", "FileGroup", "FileMode", "FileOwner", "InstanceId", "Name", "Overwrite", "RegionId", "Tag", "TargetDir"}
        for row in result["send_files"]:
            self.assertEqual(set(row), {"evidence", "request"})
            self.assertEqual(set(row["request"]), official)
            self.assertEqual(set(row["evidence"]), {"content_base64_bytes", "content_sha256"})
            self.assertEqual(row["request"]["RegionId"], "cn-shenzhen")
            self.assertEqual(row["request"]["InstanceId"], ["i-builder123"])
            self.assertEqual(row["request"]["Tag"], [{"Key": "noteai-task", "Value": "item26-restored-v1"}])
            self.assertNotIn("TargetFileName", row["request"])

    def test_high_entropy_broker_commands_and_composite_remain_bounded(self):
        maximum = {"create": 0, "readback": 0}
        for _ in range(12):
            broker = ops.broker_commands(
                "i-api123", "api-role", "restore.example.rds.aliyuncs.com",
                self.public, self.rewrap(os.urandom(384)), self.compressor,
            )
            for mode, command in broker["commands"].items():
                maximum[mode] = max(maximum[mode], command["bytes"])
        self.assertTrue(all(size <= 18000 for size in maximum.values()), maximum)

        envelope = json.dumps({
            "algorithm": "RSA-OAEP-SHA256+AES-256-GCM",
            "ciphertext": base64.b64encode(os.urandom(8700)).decode("ascii"),
            "nonce": base64.b64encode(os.urandom(12)).decode("ascii"),
            "schema_version": 1,
            "wrapped_key": base64.b64encode(os.urandom(384)).decode("ascii"),
        }, sort_keys=True, separators=(",", ":")).encode("ascii")
        self.assertLessEqual(len(envelope), 12288)
        composite = json.loads(self.fixtures()[1])
        transport = composite["transport"]
        transport["control_envelope_b64"] = base64.b64encode(envelope).decode("ascii")
        transport["control_envelope_bytes"] = len(envelope)
        transport["control_envelope_sha256"] = hashlib.sha256(envelope).hexdigest()
        composite["receipt"]["control_envelope_bytes"] = len(envelope)
        composite["receipt"]["control_envelope_sha256"] = hashlib.sha256(envelope).hexdigest()
        body = ops.canonical(composite)
        self.assertLessEqual(len(body), 18000)
        self.assertEqual(ops.validate_broker(composite, self.recipient)[0], envelope)

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
        self.assertIn(b"readback() {", rewrap_raw)
        self.assertNotIn(b"create() {", rewrap_raw)
        broker_raw = ops.render("broker", {
            b"@@MODE@@": b"READBACK",
            b"@@API_C_IDENTITY_SHA256@@": b"a" * 64,
            b"@@RESTORED_HOST@@": b"restore.example.rds.aliyuncs.com",
            b"@@RECIPIENT_PUBLIC_KEY_SHA256@@": self.recipient.encode("ascii"),
            b"@@RECIPIENT_PUBLIC_KEY_B64@@": base64.b64encode(self.public),
            b"@@PASSWORD_REWRAP_RESULT_B64@@": base64.b64encode(self.rewrap()),
        })
        subprocess.run(["bash", "-n", "-s"], input=broker_raw, check=True)
        self.assertIn(b"readback() {", broker_raw)
        self.assertNotIn(b"create() {", broker_raw)
        keygen, readback, create = self.fixtures()
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
            ("broker_readback", readback),
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

        _keygen, readback, create = self.fixtures()
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
        bad_readback = json.loads(readback)
        bad_readback["receipt"]["source_manifest_bytes"] = True
        wrong_types = (
            ("broker_create", {**json.loads(create), "secret_values_emitted": False}),
            ("broker_readback", bad_readback),
            ("rewrap_create", {**json.loads(self.rewrap()), "database_connection_count": False}),
            ("rewrap_readback", {**json.loads(self.rewrap()), "schema_version": True}),
            ("stage_finalize", {**stage_receipt, "transfer_bytes": True}),
            ("stage_readback", stage_state),
        )
        for contract, value in wrong_types:
            result = self.run_loader(ops.canonical(value), contract)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (4, b"", fixed))

        composite = json.loads(readback)
        wrong_recipient = json.loads(readback)
        wrong_recipient["receipt"]["recipient_public_key_sha256"] = "d" * 64
        wrong_recipient["transport"]["recipient_public_key_sha256"] = "d" * 64
        for body in (
            ops.canonical(composite["receipt"]),
            ops.canonical(wrong_recipient),
        ):
            result = self.run_loader(body, "broker_readback")
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

    def test_broker_cleanup_strictly_binds_inventory_and_preserves_evidence(self):
        source = ops.PATHS["broker"].read_text()
        cleanup = "cleanup_container() {" + source.split(
            "cleanup_container() {", 1,
        )[1].split("\n}\n\nfixed()", 1)[0] + "\n}\n"
        metadata_guard = (
            '  [ -d "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] && '
            '[ "$(stat -c \'%d:%i|%u|%g|%a\' "$TASK_ROOT")" = '
            '"$task_identity|0|0|700" ] || return 1'
        )
        cleanup = cleanup.replace(
            metadata_guard, '  [ -d "$TASK_ROOT" ] || return 1',
        )
        for marker in (
            "container ls -aq --no-trunc",
            'cid_present=$((cid_present+1))',
            '[ "$cid_present" -le 1 ] || return 1',
            'inspect "$cid" --format',
            'rm -f "$cid"',
            '"$row" = "$cid|/$CONTAINER_NAME|$IMAGE_CONFIG|${CONTAINER_LABEL#com.noteai.task=}"',
        ):
            self.assertIn(marker, cleanup)
        self.assertEqual(cleanup.count("container ls -aq --no-trunc"), 4)
        self.assertNotIn('if row="$(/usr/bin/docker', cleanup)

        cid = "a" * 64
        expectations = {
            "inspect125": f"1|TASK|CID|\n",
            "list125": f"1|TASK|CID|\n",
            "exact": f"0|TASK|CID|{cid}\n",
            "absent": f"0|TASK|CID|\n",
        }
        for scenario, expected in expectations.items():
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                task = root / "task"
                config = task / "docker-config"
                task.mkdir(mode=0o700)
                config.mkdir(mode=0o700)
                cidfile = task / "container.cid"
                cidfile.write_text(cid + "\n", encoding="ascii")
                cidfile.chmod(0o600)
                state = root / "container-present"
                deleted = root / "deleted-cid"
                if scenario != "absent":
                    state.write_text("present\n", encoding="ascii")
                fake = root / "docker"
                fake.write_text(
                    "#!/bin/bash\n"
                    f"scenario={scenario!r}\n"
                    f"cid={cid!r}\n"
                    f"state={str(state)!r}\n"
                    f"deleted={str(deleted)!r}\n"
                    "args=\" $* \"\n"
                    "if [[ \"$args\" == *\" container ls \"* ]]; then\n"
                    "  [ \"$scenario\" != list125 ] || exit 125\n"
                    "  [ ! -e \"$state\" ] || printf '%s\\n' \"$cid\"\n"
                    "  exit 0\n"
                    "fi\n"
                    "if [[ \"$args\" == *\" inspect \"* ]]; then\n"
                    "  [ \"$scenario\" != inspect125 ] || exit 125\n"
                    "  [ -e \"$state\" ] || exit 1\n"
                    "  printf '%s|/%s|%s|%s\\n' \"$cid\" noteai-item26-restored-package-broker-v1 sha256:fixture task\n"
                    "  exit 0\n"
                    "fi\n"
                    "if [[ \"$args\" == *\" rm -f \"* ]]; then\n"
                    "  target=\"${@: -1}\"\n"
                    "  [ \"$target\" = \"$cid\" ] || exit 98\n"
                    "  printf '%s\\n' \"$target\" >\"$deleted\"\n"
                    "  rm -f \"$state\"\n"
                    "  exit 0\n"
                    "fi\n"
                    "exit 99\n",
                    encoding="ascii",
                )
                fake.chmod(0o700)
                harness_cleanup = cleanup.replace("/usr/bin/docker", str(fake))
                harness = f"""
set +e
task_identity=x
TASK_ROOT={str(task)!r}
DOCKER_CONFIG_ROOT={str(config)!r}
CIDFILE={str(cidfile)!r}
CONTAINER_NAME=noteai-item26-restored-package-broker-v1
CONTAINER_LABEL=com.noteai.task=task
IMAGE_CONFIG=sha256:fixture
container_attempted=1
read_full_cid() {{ printf '%s\n' '{cid}'; }}
{harness_cleanup}
cleanup_container
rc=$?
[ -d "$TASK_ROOT" ] && task_state=TASK || task_state=LOST
[ -f "$CIDFILE" ] && cid_state=CID || cid_state=LOST
deleted_value="$(cat {str(deleted)!r} 2>/dev/null || true)"
printf '%s|%s|%s|%s\n' "$rc" "$task_state" "$cid_state" "$deleted_value"
"""
                result = subprocess.run(
                    ["bash", "-s"], input=harness.encode("ascii"),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    check=False, timeout=10,
                )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.decode("ascii"), expected)

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

    def test_broker_readback_composite_recovers_unknown_and_rejects_mismatch(self):
        keygen, readback, create = self.fixtures()
        composite = json.loads(readback)
        legacy_receipt = ops.canonical(composite["receipt"])
        with self.assertRaisesRegex(ops.RenderError, "broker_readback"):
            ops._post_broker_context(
                "i-builder123", ops.BUILDER_RAM_ROLE, keygen, legacy_receipt,
            )

        recovered = ops._post_broker_for_test(
            "i-builder123", ops.BUILDER_RAM_ROLE,
            keygen, readback, None, self.compressor,
        )
        self.assertEqual(
            recovered["control_envelope_sha256"],
            composite["transport"]["control_envelope_sha256"],
        )

        different = json.loads(create)
        envelope = json.loads(base64.b64decode(
            different["control_envelope_b64"], validate=True,
        ))
        envelope["ciphertext"] = base64.b64encode(b"x" * 1201).decode("ascii")
        envelope_raw = json.dumps(
            envelope, sort_keys=True, separators=(",", ":"),
        ).encode("ascii")
        different["control_envelope_b64"] = base64.b64encode(envelope_raw).decode("ascii")
        different["control_envelope_bytes"] = len(envelope_raw)
        different["control_envelope_sha256"] = hashlib.sha256(envelope_raw).hexdigest()
        with self.assertRaisesRegex(ops.RenderError, "broker_create_mismatch"):
            ops._post_broker_context(
                "i-builder123", ops.BUILDER_RAM_ROLE,
                keygen, readback, ops.canonical(different),
            )

    def test_post_broker_cli_accepts_composite_without_create_transport(self):
        keygen, readback, _create = self.fixtures()
        request = ops.canonical({
            "broker_readback_result_base64": base64.b64encode(readback).decode("ascii"),
            "builder_instance_id": "i-builder123",
            "builder_ram_role": ops.BUILDER_RAM_ROLE,
            "keygen_result_base64": base64.b64encode(keygen).decode("ascii"),
            "mode": "post_broker",
        })
        stdin = mock.Mock()
        stdin.buffer = io.BytesIO(request)
        stdout = mock.Mock()
        stdout.buffer = io.BytesIO()
        with mock.patch.object(ops.sys, "stdin", stdin), mock.patch.object(
            ops.sys, "stdout", stdout,
        ), mock.patch.object(
            ops, "post_broker", return_value={"validated": True},
        ) as post:
            returncode = ops.cli()
        self.assertEqual(returncode, 0)
        self.assertEqual(json.loads(stdout.buffer.getvalue()), {"validated": True})
        post.assert_called_once_with(
            "i-builder123", ops.BUILDER_RAM_ROLE, keygen, readback, None,
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
        keygen_raw, readback_raw, create_raw = self.fixtures()
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
        composite = json.loads(readback_raw)
        receipt = composite["receipt"]
        for field, value in (
            ("schema_version", True),
            ("control_envelope_bytes", True),
            ("secret_values_emitted", False),
        ):
            mutated = dict(create)
            mutated[field] = value
            with self.subTest(contract="broker_create", field=field), self.assertRaises(ops.RenderError):
                ops.validate_broker(composite, self.recipient, mutated)
        for field, value in (
            ("schema_version", True),
            ("control_envelope_bytes", True),
            ("source_manifest_bytes", True),
            ("secret_values_emitted", False),
            ("algorithm", "RSA-OAEP-SHA1+AES-256-GCM"),
        ):
            mutated = dict(composite)
            mutated["receipt"] = {**receipt, field: value}
            with self.subTest(contract="broker_readback", field=field), self.assertRaises(ops.RenderError):
                ops.validate_broker(mutated, self.recipient)

    def test_builder_role_is_fixed_before_render_or_post_broker(self):
        with self.assertRaisesRegex(ops.RenderError, "builder_ram_role"):
            ops.keygen_commands("i-builder123", "other-role", self.compressor)
        with self.assertRaisesRegex(ops.RenderError, "builder_ram_role"):
            ops._post_broker_for_test(
                "i-builder123", "other-role", *self.fixtures(), self.compressor,
            )


if __name__ == "__main__":
    unittest.main()
