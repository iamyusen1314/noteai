from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_transient_state_v5 as verifier  # noqa: E402


class AdminDependencyCacheTransientStateV5Tests(unittest.TestCase):
    BUILDER_NAME = "noteai-admin-cache-v5-producer-123"
    BASE = ROOT / "tools" / "verify_admin_dependency_cache_transient_state_v4.py"

    def _fixture(self, root: Path) -> tuple[Path, Path]:
        docker_config = root / "noteai-empty-docker-config-v5"
        buildx_config = root / "noteai-buildx-state-v5"
        docker_config.mkdir(mode=0o700)
        buildx_config.mkdir(mode=0o700)
        config = docker_config / "config.json"
        config.write_text(json.dumps({"auths": {}}), encoding="utf-8")
        config.chmod(0o600)
        instances = buildx_config / "instances"
        instances.mkdir(mode=0o700)
        instance = instances / self.BUILDER_NAME
        instance.write_text(
            json.dumps(
                {
                    "Name": self.BUILDER_NAME,
                    "Driver": "docker-container",
                    "Nodes": [
                        {
                            "Name": f"{self.BUILDER_NAME}0",
                            "Endpoint": "unix:///var/run/docker.sock",
                            "Platforms": None,
                            "DriverOpts": {
                                "image": (
                                    "moby/buildkit@sha256:"
                                    "2f5adac4ecd194d9f8c10b7b5d7bceb"
                                    "5186853db1b26e5abd3a657af0b7e26ec"
                                ),
                                "provenance-add-gha": "false",
                            },
                            "Flags": [
                                "--allow-insecure-entitlement=network.host"
                            ],
                            "Files": None,
                        }
                    ],
                    "Dynamic": False,
                }
            ),
            encoding="utf-8",
        )
        instance.chmod(0o600)
        return docker_config, buildx_config

    def _validate(
        self,
        root: Path,
        docker_config: Path,
        buildx_config: Path,
        phase: str,
        *,
        base: Path | None = None,
    ):
        with mock.patch.dict(
            os.environ,
            {verifier.CLIENT_TOKEN_CONTROL: "1"},
            clear=False,
        ):
            return verifier.validate(
                base_verifier=self.BASE if base is None else base,
                runner_temp=root,
                docker_config=docker_config,
                buildx_config=buildx_config,
                phase=phase,
            )

    def _write_node_id(self, buildx_config: Path, payload: bytes = b"0123456789abcdef"):
        node_id = buildx_config / ".buildNodeID"
        node_id.write_bytes(payload)
        node_id.chmod(0o600)
        return node_id

    def test_phase_transition_requires_exact_build_node_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docker_config, buildx_config = self._fixture(root)
            pre = self._validate(
                root,
                docker_config,
                buildx_config,
                "pre-build",
            )
            self.assertFalse(pre["build_node_id_present"])
            with self.assertRaises(Exception):
                self._validate(
                    root,
                    docker_config,
                    buildx_config,
                    "post-build",
                )
            self._write_node_id(buildx_config)
            post = self._validate(
                root,
                docker_config,
                buildx_config,
                "post-build",
            )
            self.assertTrue(post["client_token_disabled"])
            self.assertEqual(post["build_node_id_shape"], "pass")
            cleanup = self._validate(
                root,
                docker_config,
                buildx_config,
                "cleanup-active",
            )
            self.assertTrue(cleanup["build_node_id_present"])
            (buildx_config / ".buildNodeID").unlink()
            cleanup = self._validate(
                root,
                docker_config,
                buildx_config,
                "cleanup-active",
            )
            self.assertFalse(cleanup["build_node_id_present"])

    def test_pre_build_rejects_build_node_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docker_config, buildx_config = self._fixture(root)
            self._write_node_id(buildx_config)
            with self.assertRaises(Exception):
                self._validate(
                    root,
                    docker_config,
                    buildx_config,
                    "pre-build",
                )

    def test_build_node_id_shape_fails_closed(self) -> None:
        cases = {
            "short": b"0" * 15,
            "long": b"0" * 17,
            "uppercase": b"0123456789ABCDEf",
            "nonhex": b"0123456789abcdeg",
            "newline": b"0123456789abcde\n",
        }
        for case, payload in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                docker_config, buildx_config = self._fixture(root)
                self._write_node_id(buildx_config, payload)
                with self.assertRaises(Exception):
                    self._validate(
                        root,
                        docker_config,
                        buildx_config,
                        "post-build",
                    )

    def test_build_node_id_file_shape_fails_closed(self) -> None:
        for case in ("mode", "symlink", "hardlink", "directory"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                docker_config, buildx_config = self._fixture(root)
                node_id = buildx_config / ".buildNodeID"
                if case == "directory":
                    node_id.mkdir(mode=0o700)
                elif case == "symlink":
                    target = root / "target"
                    target.write_bytes(b"0123456789abcdef")
                    node_id.symlink_to(target)
                else:
                    self._write_node_id(buildx_config)
                    if case == "mode":
                        node_id.chmod(0o644)
                    else:
                        os.link(node_id, root / "hardlink")
                with self.assertRaises(Exception):
                    self._validate(
                        root,
                        docker_config,
                        buildx_config,
                        "post-build",
                    )

    def test_client_token_control_must_be_exact(self) -> None:
        for value in (None, "0", "true", "True", ""):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                docker_config, buildx_config = self._fixture(root)
                environment = dict(os.environ)
                if value is None:
                    environment.pop(verifier.CLIENT_TOKEN_CONTROL, None)
                else:
                    environment[verifier.CLIENT_TOKEN_CONTROL] = value
                with mock.patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "client token control changed",
                    ):
                        verifier.validate(
                            base_verifier=self.BASE,
                            runner_temp=root,
                            docker_config=docker_config,
                            buildx_config=buildx_config,
                            phase="pre-build",
                        )

    def test_driver_options_require_exact_disabled_projection(self) -> None:
        cases = (
            {"image": "wrong", "provenance-add-gha": "false"},
            {
                "image": (
                    "moby/buildkit@sha256:"
                    "2f5adac4ecd194d9f8c10b7b5d7bceb"
                    "5186853db1b26e5abd3a657af0b7e26ec"
                )
            },
            {
                "image": (
                    "moby/buildkit@sha256:"
                    "2f5adac4ecd194d9f8c10b7b5d7bceb"
                    "5186853db1b26e5abd3a657af0b7e26ec"
                ),
                "provenance-add-gha": "true",
            },
            {
                "image": (
                    "moby/buildkit@sha256:"
                    "2f5adac4ecd194d9f8c10b7b5d7bceb"
                    "5186853db1b26e5abd3a657af0b7e26ec"
                ),
                "provenance-add-gha": "false",
                "network": "host",
            },
        )
        for options in cases:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                docker_config, buildx_config = self._fixture(root)
                instance = buildx_config / "instances" / self.BUILDER_NAME
                payload = json.loads(instance.read_text(encoding="utf-8"))
                payload["Nodes"][0]["DriverOpts"] = options
                instance.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(Exception):
                    self._validate(
                        root,
                        docker_config,
                        buildx_config,
                        "pre-build",
                    )

    def test_docker_client_state_rejects_seed_lock_and_unknown_entries(self) -> None:
        for name in (".token_seed", ".token_seed.lock", "buildx", "opaque"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                docker_config, buildx_config = self._fixture(root)
                path = docker_config / name
                path.write_text("dummy-secret-sentinel", encoding="utf-8")
                path.chmod(0o600)
                with self.assertRaises(Exception):
                    self._validate(
                        root,
                        docker_config,
                        buildx_config,
                        "pre-build",
                    )

    def test_base_verifier_hash_is_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docker_config, buildx_config = self._fixture(root)
            drifted = root / "base.py"
            drifted.write_bytes(self.BASE.read_bytes() + b"\n")
            with self.assertRaisesRegex(RuntimeError, "hash changed"):
                self._validate(
                    root,
                    docker_config,
                    buildx_config,
                    "pre-build",
                    base=drifted,
                )

    def test_cli_failure_is_secret_free_and_writes_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docker_config, buildx_config = self._fixture(root)
            sentinel = "DUMMY_SECRET_SENTINEL_7c3f"
            hostile = docker_config / f"credential-{sentinel}"
            hostile.write_text(sentinel, encoding="utf-8")
            hostile.chmod(0o600)
            output = root / "result.json"
            environment = dict(os.environ)
            environment[verifier.CLIENT_TOKEN_CONTROL] = "1"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "verify_admin_dependency_cache_transient_state_v5.py"),
                    "--base-verifier",
                    str(self.BASE),
                    "--runner-temp",
                    str(root),
                    "--docker-config",
                    str(docker_config),
                    "--buildx-config",
                    str(buildx_config),
                    "--phase",
                    "pre-build",
                    "--output",
                    str(output),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertEqual(
                result.stderr,
                "FAIL: transient_state_contract_changed\n",
            )
            self.assertNotIn(sentinel, result.stdout + result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
