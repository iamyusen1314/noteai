import ast
import base64
import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
KEYGEN = ROOT / ".codex" / "item26-restored-builder-keygen-v1.template.sh"
BROKER = ROOT / ".codex" / "item26-restored-package-broker-v1.template.sh"


def embedded_python(source: str) -> list[str]:
    return re.findall(r"<<'PY'\n(.*?)\nPY", source, re.DOTALL)


class Item26RestoredPackageBrokerV1Tests(unittest.TestCase):
    def test_shell_and_embedded_python_syntax(self):
        for path in (KEYGEN, BROKER):
            subprocess.run(["bash", "-n", str(path)], check=True)
            blocks = embedded_python(path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(blocks), 1)
            for block in blocks:
                ast.parse(block)

    def test_persistent_paths_and_no_replay_contract(self):
        keygen = KEYGEN.read_text(encoding="utf-8")
        broker = BROKER.read_text(encoding="utf-8")
        self.assertIn("/var/lib/noteai/item26-restored-v1", keygen)
        self.assertIn("BASE_ROOT=/var/lib/noteai-item26-restored-broker-v1", broker)
        self.assertNotIn("/var/lib/noteai/item26-restored-v1", broker)
        for source in (keygen, broker):
            self.assertIn('"same_invocation_replay_allowed":false', source)
            self.assertNotIn("/run/noteai-item26-restored-control-v1", source)
        self.assertIn("private_key_value_read_count", keygen)
        self.assertIn("O_EXCL", keygen)
        self.assertIn("O_EXCL", broker)
        self.assertIn("capture-attempted-v1", keygen)
        self.assertNotIn("capture-attempt-v1.json", keygen)
        self.assertIn('PUBLIC_METADATA="$BASE_ROOT/keygen-public-metadata.json"', keygen)
        self.assertIn("$'control-private.pem\\ncontrol-public.pem'", keygen)

    def test_keygen_preflight_closes_database_and_capture_paths(self):
        source = KEYGEN.read_text(encoding="utf-8")
        for marker in (
            "latest/api/token",
            "ram/security-credentials/",
            "org.opencontainers.image.revision",
            "restored-capture-transfer-v1.sh.gz",
            "capture-task-v1",
            "restored-manifest-v1",
            "capture-attempted-v1",
            "state established",
            "/usr/sbin/ss -Htan",
        ):
            self.assertIn(marker, source)
        self.assertNotRegex(source, r"(?<![/A-Za-z0-9_])ss -Htan")

    def test_broker_payload_and_crypto_contract(self):
        source = BROKER.read_text(encoding="utf-8")
        for marker in (
            'AAD=b"noteai-item26-restored-control-v1"',
            "RSA-OAEP-SHA256+AES-256-GCM",
            "AESGCM.generate_key(bit_length=256)",
            "source_manifest_gzip",
            "restored_database",
            "wrapped_password",
            'STORAGE_ENV=\'/etc/noteai/storage.env\'',
            "noteai-item26-pitr-oss-reader-v1",
            "@@RECIPIENT_PUBLIC_KEY_B64@@",
            "@@PASSWORD_REWRAP_RESULT_B64@@",
            "--network none",
            "/usr/local/bin/python3.11",
            "cleanup_container",
            "container.cid",
            "os.O_NOFOLLOW",
            're.fullmatch(r"[0-9a-f]{64}"',
            "control_envelope_bytes",
            "18000",
            "no_duplicates",
            "hashlib.sha256(decoded).hexdigest()",
            "promote_fsync",
        ):
            self.assertIn(marker, source)
        match = re.search(r'payload=\{([^\n]+)\}', source)
        self.assertIsNotNone(match)
        self.assertEqual(
            set(re.findall(r'"([a-z_]+)":', match.group(1))),
            {"schema_version", "source_manifest_gzip", "restored_database", "wrapped_password", "storage"},
        )

    def test_broker_first_docker_call_uses_absent_credential_free_config(self):
        source = BROKER.read_text(encoding="utf-8")
        self.assertIn(
            "DC=/run/i26dc",
            source,
        )
        self.assertNotIn("/root/.docker", source)
        create = source.split("create() {", 1)[1]
        first = create.index("/usr/bin/docker")
        first_line = create[first:create.index("\n", first)]
        self.assertIn('--config "$DC"', first_line)
        self.assertIn("dc || fixed UNKNOWN docker_config_runtime 4", create)
        self.assertIn('mkdir -m 0700 -- "$BASE_ROOT"', create)
        self.assertIn("/usr/sbin/ss -Htan", source)
        self.assertNotRegex(source, r"(?<![/A-Za-z0-9_])ss -Htan")

    def test_source_tuple_and_public_only_create_output(self):
        source = BROKER.read_text(encoding="utf-8")
        self.assertIn("SOURCE_BYTES=9794", source)
        self.assertIn("dba5251aaf489358eab6b800dfa43ff108290abd851410da9a16f97b86d0b1f4", source)
        self.assertIn("99fc8321d11db344af51f69b735f7dcdd4d09ea3a988148896034258067a842a", source)
        self.assertGreaterEqual(source.count("dba5251aaf489358eab6b800dfa43ff108290abd851410da9a16f97b86d0b1f4"), 2)
        self.assertGreaterEqual(source.count("99fc8321d11db344af51f69b735f7dcdd4d09ea3a988148896034258067a842a"), 2)
        self.assertIn("control_envelope_b64", source)
        self.assertNotIn('"source_manifest_gzip":base64.b64encode(source).decode', source)

    def test_broker_capture_fixed_paths_and_control_inventory_match(self):
        broker = BROKER.read_text(encoding="utf-8")
        capture = (ROOT / ".codex" / "item26-restored-capture-v1.template.sh").read_text(encoding="utf-8")
        self.assertIn("BASE_ROOT=/var/lib/noteai-item26-restored-broker-v1", broker)
        self.assertIn("/var/lib/noteai/item26-restored-v1", capture)
        self.assertNotIn("/var/lib/noteai/item26-restored-v1", broker)
        self.assertIn("control-envelope.json", broker)
        self.assertIn("control-envelope.json", capture)
        self.assertIn("capture-attempted-v1", capture)
        self.assertIn("control-envelope.json\\ncontrol-private.pem\\ncontrol-public.pem", capture)


if __name__ == "__main__":
    unittest.main()
