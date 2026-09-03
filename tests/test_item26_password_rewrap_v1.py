import ast
from collections import Counter
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / ".codex" / "item26-password-rewrap.template.sh"
PLACEHOLDER = re.compile(r"@@[A-Z][A-Z0-9_]*@@")


def embedded_python(source: str) -> list[str]:
    return re.findall(r"<<'PY'[^\n]*\n(.*?)\nPY", source, re.DOTALL)


class Item26PasswordRewrapV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TEMPLATE.read_text(encoding="ascii")

    def test_shell_and_all_embedded_python_are_syntactically_valid(self):
        subprocess.run(["bash", "-n", str(TEMPLATE)], check=True)
        blocks = embedded_python(self.source)
        self.assertGreaterEqual(len(blocks), 8)
        for block in blocks:
            ast.parse(block)

    def test_placeholder_inventory_is_exact_and_rendered_shell_is_valid(self):
        self.assertEqual(
            Counter(PLACEHOLDER.findall(self.source)),
            Counter(
                {
                    "@@MODE@@": 1,
                    "@@API_C_IDENTITY_SHA256@@": 1,
                    "@@RECIPIENT_PUBLIC_KEY_SHA256@@": 2,
                    "@@RECIPIENT_PUBLIC_KEY_B64@@": 1,
                }
            ),
        )
        rendered = self.source
        rendered = rendered.replace("@@MODE@@", "READBACK")
        rendered = rendered.replace("@@API_C_IDENTITY_SHA256@@", "a" * 64)
        rendered = rendered.replace("@@RECIPIENT_PUBLIC_KEY_SHA256@@", "b" * 64)
        rendered = rendered.replace("@@RECIPIENT_PUBLIC_KEY_B64@@", "QQ==")
        self.assertIsNone(PLACEHOLDER.search(rendered))
        subprocess.run(["bash", "-n", "-s"], input=rendered.encode("ascii"), check=True)

    def test_persistent_create_and_readback_are_write_once(self):
        for marker in (
            "MODE='@@MODE@@'",
            "CREATE)",
            "READBACK)",
            "PERSISTENT_PARENT='/var/lib'",
            'PERSISTENT_ROOT="$PERSISTENT_PARENT/noteai-item26-restored-password-rewrap-successor-v1"',
            'ATTEMPT_FILE="$PERSISTENT_ROOT/attempted-v1.json"',
            'RESULT_FILE="$PERSISTENT_ROOT/password-rewrap-result-v1.json"',
            "os.O_EXCL|os.O_NOFOLLOW",
            "os.fsync(fd)",
            "os.fsync(dirfd)",
            "attempt_committed=1",
            "result_committed=1",
            "force_unknown=1",
            "phase='persistent_root_create'\n  force_unknown=1\n  mkdir -m 0700 -- \"$PERSISTENT_ROOT\"",
            'mkdir -m 0700 -- "$PERSISTENT_ROOT"',
            "emit_readback",
            'set(os.listdir(root))!={"attempted-v1.json","password-rewrap-result-v1.json"}',
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn("rm -rf", self.source)
        self.assertNotIn("/var/lib/noteai-item26-restored-password-rewrap-v1", self.source)

    def test_empty_helper_stderr_uses_the_gnu_empty_file_type(self):
        self.assertIn(
            "'regular empty file|0|0|600|1|0' ] || { phase='helper_stderr'; return 1; }",
            self.source,
        )
        self.assertNotIn(
            "'regular file|0|0|600|1|0' ] || { phase='helper_stderr'; return 1; }",
            self.source,
        )
        helper_guard = self.source.index("phase='helper_stderr'")
        result_commit = self.source.index("phase='result_commit'")
        self.assertLess(helper_guard, result_commit)

    def test_first_docker_call_is_credential_free_and_config_path_stays_absent(self):
        self.assertIn(
            "DC=/run/i26dc",
            self.source,
        )
        self.assertIn("dc()", self.source)
        self.assertNotIn("/root/.docker", self.source)
        create = self.source.split("create() {", 1)[1]
        first = create.index("/usr/bin/docker")
        first_line = create[first:create.index("\n", first)]
        self.assertIn('--config "$DC"', first_line)
        for line in create.splitlines():
            if "/usr/bin/docker" in line and "cleanup_container" not in line:
                self.assertIn("--config", line)
        self.assertIn("phase='docker_config_runtime'", self.source)
        self.assertIn("/usr/sbin/ss -Htan", self.source)
        self.assertNotRegex(self.source, r"(?<![/A-Za-z0-9_])ss -Htan")

    def test_source_control_and_api_c_identity_are_exact(self):
        for marker in (
            "@@API_C_IDENTITY_SHA256@@",
            "latest/api/token",
            "ram/security-credentials/",
            "/run/noteai-item26-source-account-v2",
            "control-database-url.enc\\ncontrol-private.pem\\ncontrol-public.pem",
            "SOURCE_ENVELOPE_BYTES=894",
            "2c522a13b236301c5276088dd6ae83cabb5ac9c6a45923385831ec582d81e90a",
            "dc8f8283248dd232030bb63d19f669ccdaad89faa87dbdffb7b5eb5aae83969a",
            "private_sha",
            "public_sha",
            "SOURCE_PUBLIC_KEY_SHA256",
            "after=os.lstat(path)",
            "stable(before)!=stable(opened)",
            "stable(before)!=stable(after)",
        ):
            self.assertIn(marker, self.source)

    def test_recipient_binding_crypto_and_secret_boundary(self):
        for marker in (
            "@@RECIPIENT_PUBLIC_KEY_B64@@",
            "@@RECIPIENT_PUBLIC_KEY_SHA256@@",
            'REWRAP_LABEL=b"noteai-item26-password-rewrap-v1"',
            "RSA-OAEP-SHA256+AES-256-GCM",
            "AESGCM(data_key).decrypt",
            "recipient.encrypt(password.encode",
            "--network none",
            "database_connection_count\":0",
            "database_write_count\":0",
            "provider_control_plane_mutation_count\":0",
            "secret_values_emitted\":0",
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn("psql", self.source)
        self.assertNotIn("psycopg", self.source)
        self.assertNotIn("oss2", self.source)
        self.assertNotIn("list_objects", self.source)
        self.assertNotIn("head_object", self.source)
        self.assertNotRegex(self.source, r"print\([^\n]*(?:password|control_url)")

    def test_result_and_fixed_terminal_contracts_are_canonical_and_typed(self):
        expected = {
            "account_exact",
            "automatic_retry_allowed",
            "database_connection_count",
            "database_write_count",
            "password_policy_exact",
            "provider_control_plane_mutation_count",
            "recipient_public_key_sha256",
            "schema_version",
            "secret_values_emitted",
            "status",
            "wrapped_password",
        }
        match = re.search(r'keys=\{([^\n]+)\}', self.source)
        self.assertIsNotNone(match)
        self.assertEqual(set(re.findall(r'"([a-z0-9_]+)"', match.group(1))), expected)
        for marker in (
            "object_pairs_hook=no_duplicates",
            'type(result["schema_version"]) is not int',
            "type(result[key]) is not int",
            'type(result["automatic_retry_allowed"]) is not bool',
            'type(attempt["schema_version"]) is not int',
            'type(attempt["automatic_retry_allowed"]) is not bool',
            'type(attempt["same_invocation_replay_allowed"]) is not bool',
            '"same_invocation_replay_allowed":false',
            '"new_rewrap_allowed":false',
            '"readback_required":%s',
        ):
            self.assertIn(marker, self.source)

    def test_container_cleanup_is_full_id_and_task_inode_bound(self):
        for marker in (
            'task_identity="$(stat -c \'%d:%i\' "$TASK_ROOT")"',
            "--cidfile \"$CIDFILE\"",
            're.fullmatch(r"[0-9a-f]{64}",value)',
            'len(value)!=64',
            "--no-trunc",
            'container ls -aq --no-trunc 2>/dev/null)" || return 1',
            'cid_present=$((cid_present+1))',
            '[ "$cid_present" -le 1 ] || return 1',
            'if [ "$cid_present" -eq 1 ]; then',
            'inspect "$cid" --format',
            'inspect "$cid" --format \'{{.Id}}|{{.Name}}|{{.Image}}|{{index .Config.Labels "com.noteai.task"}}\' 2>/dev/null)" || return 1',
            '"$row" = "$cid|/$CONTAINER_NAME|$IMAGE_CONFIG|${CONTAINER_LABEL#com.noteai.task=}"',
            "os.rmdir(name,dir_fd=basefd)",
            '"{}:{}".format(row.st_dev,row.st_ino)!=identity',
            "<<'PY' || return 1",
        ):
            self.assertIn(marker, self.source)
        cleanup = self.source.split("cleanup_container() {", 1)[1].split("\n}\n\ncleanup_task()", 1)[0]
        self.assertNotIn('if row="$(/usr/bin/docker', cleanup)
        self.assertIn('row="$(/usr/bin/docker', cleanup)

    def test_container_inspect_error_is_unknown_and_retains_cid_evidence(self):
        cleanup = "cleanup_container() {" + self.source.split(
            "cleanup_container() {", 1
        )[1].split("\n}\n\ncleanup_task()", 1)[0] + "\n}\n"
        metadata_guard = (
            '  [ -d "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ] && '
            '[ "$(stat -c \'%d:%i|%u|%g|%a\' "$TASK_ROOT")" = '
            '"$task_identity|0|0|700" ] || return 1'
        )
        cleanup = cleanup.replace(metadata_guard, '  [ -d "$TASK_ROOT" ] || return 1')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "task"
            config = task / "docker-config"
            task.mkdir(mode=0o700)
            config.mkdir(mode=0o700)
            cid = "a" * 64
            cidfile = task / "container.cid"
            cidfile.write_text(cid + "\n", encoding="ascii")
            cidfile.chmod(0o600)
            fake = root / "docker"
            fake.write_text(
                "#!/bin/bash\n"
                "case \" $* \" in\n"
                f"  *\" inspect \"*) exit 125 ;;\n"
                f"  *\" container ls \"*) printf '%s\\n' '{cid}'; exit 0 ;;\n"
                "  *) exit 99 ;;\n"
                "esac\n",
                encoding="ascii",
            )
            fake.chmod(0o700)
            cleanup = cleanup.replace("/usr/bin/docker", str(fake))
            harness = f"""
set +e
task_created=1
task_identity=x
TASK_ROOT={str(task)!r}
DOCKER_CONFIG_ROOT={str(config)!r}
CIDFILE={str(cidfile)!r}
CONTAINER_NAME=noteai-item26-password-rewrap-successor-v1
CONTAINER_LABEL=com.noteai.task=task
IMAGE_CONFIG=sha256:fixture
container_attempted=1
read_full_cid() {{ printf '%s\\n' '{cid}'; }}
{cleanup}
cleanup_container
rc=$?
[ -f "$CIDFILE" ] && retained=RETAINED || retained=LOST
printf '%s|%s\\n' "$rc" "$retained"
"""
            result = subprocess.run(
                ["bash", "-s"],
                input=harness.encode("ascii"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"1|RETAINED\n")

    def test_template_identity_is_reportable(self):
        body = TEMPLATE.read_bytes()
        self.assertGreater(len(body), 20_000)
        self.assertRegex(hashlib.sha256(body).hexdigest(), r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
