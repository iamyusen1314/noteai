import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import run_item26_restored_renderer_bridge_v1 as bridge


class Item26RestoredRendererBridgeV1Tests(unittest.TestCase):
    INVOCATION_ID = "0123456789abcdef0123456789abcdef"

    @contextlib.contextmanager
    def private_root(self, mode="preflight"):
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            os.chmod(root, 0o700)
            bridge._create_exclusive(
                root / (self.INVOCATION_ID + ".request.json"),
                bridge._canonical({"mode": mode}),
            )
            yield root

    @staticmethod
    def completed(stdout=b'{"ok":true}\n', stderr=b"", returncode=0):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    @contextlib.contextmanager
    def mocked_sources(self):
        bodies = {path: (path + "\n").encode("ascii") for path in bridge.SOURCE_IDENTITIES}
        with mock.patch.object(bridge, "_read_source", side_effect=lambda path, identity: bodies[str(path.relative_to(bridge.REPOSITORY_ROOT))]):
            yield bodies

    def test_command_is_exactly_bounded_and_mounts_only_private_bundle(self):
        with self.private_root() as root:
            command = bridge._docker_command(
                mode="preflight", token=self.INVOCATION_ID,
                bundle_path=root / "source-bundle",
                cidfile_path=root / (self.INVOCATION_ID + ".cid"),
            )
        joined = "\n".join(command)
        for marker in (
            "--rm", "--interactive", "--pull\nnever", "--platform\nlinux/amd64",
            "--network\nnone", "--read-only", "--cap-drop\nALL",
            "--security-opt\nno-new-privileges:true", "--memory\n384m",
            "--memory-swap\n384m", "--cpus\n1.0", "--pids-limit\n128",
            "--ipc\nprivate", "--user\n65532:65532", bridge.IMAGE,
            "/work/tools/render_item26_restored_preflight_v1.py",
        ):
            self.assertIn(marker, joined)
        self.assertEqual(joined.count("type=bind,"), 1)
        self.assertEqual(command.count("--interactive"), 1)
        self.assertIn("dst=/work,readonly", joined)
        self.assertNotIn(str(bridge.REPOSITORY_ROOT), joined)
        self.assertNotIn("colima", joined.lower())
        self.assertNotIn("--env-file", joined)
        self.assertEqual(set(bridge.MODE_ENTRYPOINTS), bridge.MODES)
        self.assertEqual(set(bridge.MODE_ENTRYPOINTS.values()), {
            "tools/render_item26_restored_ops_v1.py",
            "tools/render_item26_restored_preflight_v1.py",
        })

    def test_pass_retains_bundle_attempt_result_stderr_meta_and_readback(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return self.completed()

        with self.private_root() as root, self.mocked_sources() as sources, mock.patch.object(
            bridge, "_safe_cleanup", return_value="ABSENT_PROVEN",
        ):
            summary = bridge.run_bridge(mode="preflight", private_root=root, token=self.INVOCATION_ID, run=fake_run)
            self.assertEqual(summary["outcome"], "PASS")
            paths = bridge._mode_paths(root, "preflight", self.INVOCATION_ID)
            self.assertEqual(paths["result"].read_bytes(), b'{"ok":true}\n')
            self.assertEqual(paths["stderr"].read_bytes(), b"")
            meta = json.loads(paths["meta"].read_bytes())
            self.assertFalse(meta["automatic_retry_allowed"])
            self.assertFalse(meta["same_invocation_replay_allowed"])
            self.assertEqual(meta["cleanup_state"], "ABSENT_PROVEN")
            self.assertEqual(meta["residue_state"], "ABSENT_PROVEN")
            self.assertEqual(json.loads(paths["attempt"].read_bytes())["mode"], "preflight")
            for relative in bridge.MODE_SOURCE_FILES["preflight"]:
                body = sources[relative]
                target = root / "preflight.source-bundle" / relative
                self.assertEqual(target.read_bytes(), body)
                self.assertEqual(target.stat().st_mode & 0o777, 0o444)
            self.assertEqual(calls[0][1]["input"], bridge._canonical({"mode": "preflight"}))
            self.assertEqual(calls[0][1]["timeout"], bridge.TIMEOUT_SECONDS)
            self.assertEqual(bridge.readback(mode="preflight", private_root=root, token=self.INVOCATION_ID), summary)
            with self.assertRaisesRegex(bridge.BridgeError, "mode_already_attempted"):
                bridge.run_bridge(mode="preflight", private_root=root, token="f" * 32, run=fake_run)

    def test_failure_never_promotes_result_and_retains_meta(self):
        with self.private_root("broker") as root, self.mocked_sources(), mock.patch.object(
            bridge, "_safe_cleanup", return_value="ABSENT_PROVEN",
        ):
            summary = bridge.run_bridge(
                mode="broker", private_root=root, token=self.INVOCATION_ID,
                run=lambda *args, **kwargs: self.completed(
                    b"", b"ITEM26_RESTORED_OPS_RENDER_FAILED:request_contract\n", 2,
                ),
            )
            paths = bridge._mode_paths(root, "broker", self.INVOCATION_ID)
            self.assertEqual(summary["outcome"], "FAIL")
            self.assertFalse(paths["result"].exists())
            self.assertEqual(
                paths["stderr"].read_bytes(),
                b"ITEM26_RESTORED_OPS_RENDER_FAILED:request_contract\n",
            )
            meta = json.loads(paths["meta"].read_bytes())
            self.assertEqual(meta["cleanup_state"], "ABSENT_PROVEN")
            self.assertEqual(meta["residue_state"], "ABSENT_PROVEN")
            self.assertEqual(meta["returncode"], 2)

    def test_docker_125_and_signal_are_unknown_not_renderer_failures(self):
        for index, returncode in enumerate((125, -9), start=1):
            token = (str(index) * 32)
            with self.private_root("keygen") as root, self.mocked_sources(), mock.patch.object(
                bridge, "_safe_cleanup", return_value="ABSENT_PROVEN",
            ):
                original = root / (self.INVOCATION_ID + ".request.json")
                renamed = root / (token + ".request.json")
                original.rename(renamed)
                summary = bridge.run_bridge(
                    mode="keygen", private_root=root, token=token,
                    run=lambda *args, _rc=returncode, **kwargs: self.completed(
                        b"", b"docker runtime failure\n", _rc,
                    ),
                )
                self.assertEqual(summary["outcome"], "UNKNOWN")
                meta = json.loads((root / (token + ".meta.json")).read_bytes())
                self.assertEqual(meta["terminal_error"], "docker_returncode")
                self.assertFalse((root / (token + ".result.json")).exists())

    def test_partial_readback_closes_attempt_without_replay(self):
        for bundle_state in ("ABSENT", "PARTIAL_OR_CHANGED", "EXACT_RETAINED"):
            with self.subTest(bundle_state=bundle_state), self.private_root("keygen") as root, self.mocked_sources():
                request = bridge._canonical({"mode": "keygen"})
                sources = bridge._source_snapshot("keygen")
                manifest = bridge._source_manifest(sources)
                attempt = {
                    "attempt_time_ns": 1,
                    "automatic_retry_allowed": False,
                    "container_image": bridge.IMAGE,
                    "container_platform": bridge.PLATFORM,
                    "mode": "keygen",
                    "request_bytes": len(request),
                    "request_sha256": bridge._sha256(request),
                    "same_invocation_replay_allowed": False,
                    "schema_version": 1,
                    "source_bundle_manifest_sha256": bridge._sha256(manifest),
                    "token": self.INVOCATION_ID,
                }
                paths = bridge._mode_paths(root, "keygen", self.INVOCATION_ID)
                bridge._create_exclusive(paths["attempt"], bridge._canonical(attempt))
                if bundle_state == "PARTIAL_OR_CHANGED":
                    bundle = root / "keygen.source-bundle"
                    bundle.mkdir(mode=0o755)
                    os.chmod(bundle, 0o755)
                    (bundle / "unexpected").mkdir(mode=0o755)
                elif bundle_state == "EXACT_RETAINED":
                    bundle = bridge._build_bundle(root, "keygen", sources, manifest)
                    bridge._verify_bundle(bundle, manifest, "keygen")
                    bridge._create_exclusive(paths["result"], b"")
                    bridge._create_exclusive(paths["stdout"], b"")
                    bridge._create_exclusive(paths["stderr"], b"partial-error")
                with mock.patch.object(bridge, "_safe_cleanup", return_value="ABSENT_PROVEN") as cleanup:
                    summary = bridge.readback(
                        mode="keygen", private_root=root, token=self.INVOCATION_ID,
                        run=mock.Mock(),
                    )
                self.assertEqual(summary["outcome"], "UNKNOWN")
                self.assertIsNone(summary["result_path"])
                meta = json.loads(paths["meta"].read_bytes())
                self.assertEqual(meta["terminal_error"], "recovered_incomplete")
                self.assertEqual(meta["bundle_state"], bundle_state)
                self.assertEqual(meta["cleanup_state"], "ABSENT_PROVEN")
                self.assertFalse(meta["result_verified"])
                if bundle_state == "EXACT_RETAINED":
                    self.assertTrue(meta["stdout_path_present"])
                    self.assertEqual(meta["stdout_bytes"], 0)
                self.assertTrue(paths["attempt"].exists())
                self.assertTrue(paths["stderr"].exists())
                cleanup.assert_called_once()
                second_run = mock.Mock()
                self.assertEqual(
                    bridge.readback(
                        mode="keygen", private_root=root, token=self.INVOCATION_ID,
                        run=second_run,
                    ),
                    summary,
                )
                second_run.assert_not_called()
                with self.assertRaisesRegex(bridge.BridgeError, "mode_already_attempted"):
                    bridge.run_bridge(
                        mode="keygen", private_root=root, token="f" * 32,
                        run=mock.Mock(),
                    )

    def test_readback_rejects_invalid_or_traversal_token_before_side_effect(self):
        with self.private_root() as root:
            run = mock.Mock()
            for token in ("../outside", "g" * 32, "a" * 31):
                with self.subTest(token=token), self.assertRaisesRegex(
                    bridge.BridgeError, "arguments",
                ):
                    bridge.readback(
                        mode="preflight", private_root=root, token=token, run=run,
                    )
            with self.assertRaisesRegex(bridge.BridgeError, "arguments"):
                bridge.readback(
                    mode="not-a-mode", private_root=root, token=self.INVOCATION_ID, run=run,
                )
            run.assert_not_called()

    def test_partial_readback_downgrades_self_consistent_unbound_bundle(self):
        with self.private_root("keygen") as root, self.mocked_sources():
            request = bridge._canonical({"mode": "keygen"})
            sources = bridge._source_snapshot("keygen")
            manifest = bridge._source_manifest(sources)
            attempt = {
                "attempt_time_ns": 1,
                "automatic_retry_allowed": False,
                "container_image": bridge.IMAGE,
                "container_platform": bridge.PLATFORM,
                "mode": "keygen",
                "request_bytes": len(request),
                "request_sha256": bridge._sha256(request),
                "same_invocation_replay_allowed": False,
                "schema_version": 1,
                "source_bundle_manifest_sha256": "f" * 64,
                "token": self.INVOCATION_ID,
            }
            paths = bridge._mode_paths(root, "keygen", self.INVOCATION_ID)
            bridge._create_exclusive(paths["attempt"], bridge._canonical(attempt))
            bundle = bridge._build_bundle(root, "keygen", sources, manifest)
            bridge._verify_bundle(bundle, manifest, "keygen")
            with mock.patch.object(bridge, "_safe_cleanup", return_value="ABSENT_PROVEN"):
                summary = bridge.readback(
                    mode="keygen", private_root=root, token=self.INVOCATION_ID,
                    run=mock.Mock(),
                )
            self.assertEqual(summary["outcome"], "UNKNOWN")
            meta = json.loads(paths["meta"].read_bytes())
            self.assertEqual(meta["bundle_state"], "PARTIAL_OR_CHANGED")
            self.assertEqual(meta["source_bundle_manifest_sha256"], "f" * 64)

    def test_existing_meta_readback_checks_final_private_root_identity(self):
        with self.private_root() as root, self.mocked_sources(), mock.patch.object(
            bridge, "_safe_cleanup", return_value="ABSENT_PROVEN",
        ):
            bridge.run_bridge(
                mode="preflight", private_root=root, token=self.INVOCATION_ID,
                run=lambda *args, **kwargs: self.completed(),
            )
            actual = bridge._directory_metadata(root, 0o700)
            changed = mock.Mock(st_dev=actual.st_dev, st_ino=actual.st_ino + 1)
            calls = {"count": 0}

            def metadata(path, mode):
                calls["count"] += 1
                return actual if calls["count"] == 1 else changed

            with mock.patch.object(bridge, "_directory_metadata", side_effect=metadata):
                with self.assertRaisesRegex(bridge.BridgeError, "private_root_race"):
                    bridge.readback(
                        mode="preflight", private_root=root, token=self.INVOCATION_ID,
                        run=mock.Mock(),
                    )

    def test_request_result_and_root_fail_closed_before_or_after_start(self):
        with self.private_root("keygen") as root, self.mocked_sources():
            with self.assertRaisesRegex(bridge.BridgeError, "request_mode"):
                bridge.run_bridge(mode="rewrap", private_root=root, token=self.INVOCATION_ID, run=mock.Mock())
            self.assertFalse((root / "rewrap.attempt.json").exists())

        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o755)
            os.chmod(root, 0o755)
            run = mock.Mock()
            with self.assertRaisesRegex(bridge.BridgeError, "directory_metadata"):
                bridge.run_bridge(mode="preflight", private_root=root, token=self.INVOCATION_ID, run=run)
            run.assert_not_called()

        with self.private_root("keygen") as root, self.mocked_sources(), mock.patch.object(
            bridge, "_safe_cleanup", return_value="CID_UNAVAILABLE",
        ):
            summary = bridge.run_bridge(
                mode="keygen", private_root=root, token=self.INVOCATION_ID,
                run=lambda *args, **kwargs: self.completed(b'{"z":1, "a":2}\n'),
            )
            self.assertEqual(summary["outcome"], "UNKNOWN")
            self.assertTrue((root / (self.INVOCATION_ID + ".meta.json")).exists())
            self.assertFalse((root / (self.INVOCATION_ID + ".result.json")).exists())

    def test_timeout_cleanup_requires_exact_cid_name_and_image(self):
        cid = "a" * 64
        calls = []

        def exact_run(command, **kwargs):
            calls.append(command)
            if command[1] == "ps":
                self.assertEqual(
                    command[-1],
                    '{{.ID}}|{{.Names}}|{{.Image}}|{{.Label "com.noteai.item26-render-token"}}',
                )
                self.assertNotIn(".Labels", command[-1])
                row = "{}|{}|{}|{}\n".format(
                    cid, bridge.CONTAINER_NAME_PREFIX + self.INVOCATION_ID,
                    bridge.IMAGE, self.INVOCATION_ID,
                ).encode("ascii")
                return self.completed(row) if len(calls) == 1 else self.completed(b"")
            if command[1] == "inspect":
                return self.completed((cid + "|/" + bridge.CONTAINER_NAME_PREFIX + self.INVOCATION_ID + "|" + bridge.IMAGE + "|" + self.INVOCATION_ID + "\n").encode("ascii"))
            return self.completed((cid + "\n").encode("ascii"))

        with self.private_root() as root:
            bridge._create_exclusive(root / (self.INVOCATION_ID + ".cid"), (cid + "\n").encode("ascii"))
            self.assertEqual(bridge._safe_cleanup(run=exact_run, token=self.INVOCATION_ID, cidfile_path=root / (self.INVOCATION_ID + ".cid")), "EXACT_REMOVED")
            self.assertEqual([call[1] for call in calls], ["ps", "inspect", "rm", "ps"])

        calls = []
        with self.private_root() as root:
            bridge._create_exclusive(root / (self.INVOCATION_ID + ".cid"), (cid + "\n").encode("ascii"))
            def wrong_run(command, **kwargs):
                calls.append(command)
                if command[1] == "ps":
                    return self.completed(
                        "{}|{}|{}|{}\n".format(
                            cid, bridge.CONTAINER_NAME_PREFIX + self.INVOCATION_ID,
                            bridge.IMAGE, self.INVOCATION_ID,
                        ).encode("ascii")
                    )
                return self.completed((cid + "|/other|" + bridge.IMAGE + "|" + self.INVOCATION_ID + "\n").encode("ascii"))
            self.assertEqual(bridge._safe_cleanup(run=wrong_run, token=self.INVOCATION_ID, cidfile_path=root / (self.INVOCATION_ID + ".cid")), "IDENTITY_UNPROVEN")
            self.assertEqual([call[1] for call in calls], ["ps", "inspect"])

    def test_inventory_projects_only_task_label_and_unrelated_rows_cannot_poison_it(self):
        unrelated_cid = "b" * 64
        target_cid = "c" * 64

        def projected_run(command, **kwargs):
            self.assertEqual(
                command[-1],
                '{{.ID}}|{{.Names}}|{{.Image}}|{{.Label "com.noteai.item26-render-token"}}',
            )
            self.assertNotIn(".Labels", command[-1])
            return self.completed(
                (
                    "{}|unrelated|unrelated@example|\n"
                    "{}|{}|{}|{}\n"
                ).format(
                    unrelated_cid, target_cid,
                    bridge.CONTAINER_NAME_PREFIX + self.INVOCATION_ID,
                    bridge.IMAGE, self.INVOCATION_ID,
                ).encode("ascii")
            )

        state, rows = bridge._inventory(projected_run, self.INVOCATION_ID)
        self.assertEqual(state, "OK")
        self.assertEqual(rows[unrelated_cid][2], "")
        self.assertEqual(rows[target_cid][2], self.INVOCATION_ID)

        for bad_label in ("not-a-token", self.INVOCATION_ID + "|extra", self.INVOCATION_ID + "\nextra"):
            state, rows = bridge._inventory(
                lambda *args, value=bad_label, **kwargs: self.completed(
                    (target_cid + "|name|image|" + value + "\n").encode("ascii")
                ),
                self.INVOCATION_ID,
            )
            self.assertEqual((state, rows), ("QUERY_UNKNOWN", {}))

    def test_cli_stdout_is_summary_only(self):
        summary = {
            "cleanup_state": "NOT_REQUIRED", "meta_path": "/private/meta.json",
            "mode": "post_broker", "outcome": "PASS", "residue_state": "NONE_EXPECTED",
            "result_path": "/private/result.json", "stderr_path": "/private/stderr.bin",
            "token": self.INVOCATION_ID,
        }
        stdout = mock.Mock(); stdout.buffer = io.BytesIO()
        with mock.patch.object(bridge, "run_bridge", return_value=summary), mock.patch.object(bridge.sys, "stdout", stdout):
            self.assertEqual(bridge.cli(["--action", "RUN", "--mode", "post_broker", "--private-root", "/private", "--token", self.INVOCATION_ID]), 0)
        self.assertEqual(stdout.buffer.getvalue(), bridge._canonical(summary))
        self.assertNotIn(b"request_sha256", stdout.buffer.getvalue())
        self.assertNotIn(b"result_sha256", stdout.buffer.getvalue())
        for outcome, expected in (("FAIL", 3), ("UNKNOWN", 4)):
            changed = {**summary, "outcome": outcome}
            sink = mock.Mock(); sink.buffer = io.BytesIO()
            with mock.patch.object(bridge, "readback", return_value=changed), mock.patch.object(bridge.sys, "stdout", sink):
                self.assertEqual(bridge.cli(["--action", "READBACK", "--mode", "post_broker", "--private-root", "/private", "--token", self.INVOCATION_ID]), expected)

    def test_source_identity_table_is_frozen_and_mode_sets_are_minimal(self):
        self.assertEqual(
            {path for path, identity in bridge.SOURCE_IDENTITIES.items() if identity["bytes"] is None or identity["sha256"] is None},
            set(),
        )
        for path, identity in bridge.SOURCE_IDENTITIES.items():
            self.assertEqual(len(bridge._read_source(bridge.REPOSITORY_ROOT / path, identity)), identity["bytes"])
        self.assertEqual(bridge.MODE_SOURCE_FILES["preflight"], {
            "tools/render_item26_restored_preflight_v1.py",
            "tools/render_item26_v3_transport.py",
            ".codex/item26-restored-api-c-preflight-v1.template.sh",
            ".codex/item26-restored-builder-preflight-v1.template.sh",
        })
        self.assertNotIn(
            ".codex/item26-password-rewrap.template.sh",
            bridge.MODE_SOURCE_FILES["broker"],
        )

    def test_exclusive_writer_handles_short_writes(self):
        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "out"
            real_write = os.write

            def short_write(descriptor, body):
                return real_write(descriptor, body[:3])

            with mock.patch.object(bridge.os, "write", side_effect=short_write):
                bridge._create_exclusive(target, b"0123456789")
            self.assertEqual(target.read_bytes(), b"0123456789")
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_bundle_inventory_rejects_unexpected_directory_and_symlink(self):
        with self.private_root() as root, self.mocked_sources():
            bodies = bridge._source_snapshot("preflight")
            manifest = bridge._source_manifest(bodies)
            bundle = bridge._build_bundle(root, "preflight", bodies, manifest)
            bridge._verify_bundle(bundle, manifest, "preflight")
            (bundle / "unexpected").mkdir(mode=0o755)
            with self.assertRaisesRegex(bridge.BridgeError, "bundle_inventory"):
                bridge._verify_bundle(bundle, manifest, "preflight")

        with self.private_root() as root, self.mocked_sources():
            bodies = bridge._source_snapshot("preflight")
            manifest = bridge._source_manifest(bodies)
            bundle = bridge._build_bundle(root, "preflight", bodies, manifest)
            target = bundle / next(iter(bridge.MODE_SOURCE_FILES["preflight"]))
            target.unlink()
            target.symlink_to(bundle / "manifest.json")
            with self.assertRaisesRegex(bridge.BridgeError, "bundle_inventory"):
                bridge._verify_bundle(bundle, manifest, "preflight")


if __name__ == "__main__":
    unittest.main()
