import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import execute_item33_trends_promotion as controller
import item33_trends_host_actions as actions
import item33_trends_host_readback as reader
from tests import test_item33_trends_promotion_executor as fixtures


@unittest.skipUnless(os.geteuid() == 0, "root filesystem fixtures run only inside the isolated test container")
class HostReadbackTests(unittest.TestCase):
    cid = "d" * 64
    now = datetime(2026, 9, 19, 0, 10, tzinfo=timezone.utc)

    def container(self):
        mounts = [{"Type": "bind", "Source": str(controller.V5_RUNTIME_OVERLAY_ROOT / name),
                   "Destination": "/app/" + name, "RW": False}
                  for name in (*controller.V5_RUNTIME_OVERLAY_SHA256, *controller.V5_CAPTURE_TOOLS,
                               controller.V5_CAPTURE_LAUNCHER_PATH)]
        mounts += [
            {"Type": "bind", "Source": str(controller.V5_CAPTURE_ROOT / "runtime-config.json"),
             "Destination": "/run/noteai-item33/capture-config.json", "RW": False},
            {"Type": "bind", "Source": str(controller.V5_CAPTURE_ROOT / "capture.sock"),
             "Destination": "/run/noteai-item33/capture.sock", "RW": False}]
        return {"id": self.cid, "name": "/noteai-xhs-trends", "image": "sha256:" + controller.V5_IMAGE_CONFIG_SHA256,
                "state": {"Running": True, "Paused": False, "Restarting": False, "Pid": 456,
                          "Error": "synthetic-untrusted-error-with-cookie-value"},
                "user": "999:999", "entrypoint": ["/app/scripts/docker_entrypoint.sh"],
                "cmd": ["/app/scripts/render_run_market_timing.sh"], "mounts": mounts,
                "readonly_rootfs": True, "network_mode": "bridge", "ipc_mode": "private",
                "memory": 512 * 1024 * 1024, "nano_cpus": 500_000_000, "pids_limit": 64,
                "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"], "ports": {}, "restart": "no",
                "flags": [*[{"name": key, "matches": True} for key in reader.FLAGS], None]}

    def invoke(self, *, phase="promoted", change=None, task=False, unit_dropin=False, health=True,
               process_ok=True, change_after=False, session_wrong=False, temp_artifact=False,
               collector=None, ready_bad=False, capture_failed=False, namespace_bad=False):
        active = phase in {"promoted", "final", "normal"}
        collector = phase == "preflight" if collector is None else collector
        fixture = fixtures.Item33V5PromotionTests()
        commands = []
        original = fixtures.Item33HostActionPreparationTests().suspended()
        container = self.container()
        if phase == "normal":
            container["cmd"] = ["python", "market_timing_worker.py", "--daemon", "--interval", "360"]
            container["mounts"] = container["mounts"][:8]
        if change: change(container)
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            capture_root = root / "capture"; capture_root.mkdir(mode=0o700)
            for mount in container['mounts']:
                if mount['Source'].startswith(str(controller.V5_CAPTURE_ROOT)+'/'):
                    mount['Source']=str(capture_root/Path(mount['Source']).name)
            from tests.test_item33_trends_runtime_capture import config_fixture
            from tests.test_item33_trends_capture_catalog import catalog_fixture
            config = config_fixture()
            proof = catalog_fixture(config)
            config['bucket_key'] = self.now.date().isoformat()
            for facts in (proof['before'],proof['after']):
                facts['bucket_key']=config['bucket_key'];facts['observed_at']=self.now.isoformat()
            binding = fixture.capture()
            ready = {"schema":"noteai.item33.capture_service_ready.v1","state":"LISTENING_READY",
                "activation_identity_sha256":binding['activation_identity_sha256'],"configuration_sha256":binding['configuration_sha256'],
                "bucket_key":self.now.date().isoformat(),"pid":1,"observed_at":self.now.isoformat(),
                "catalog_before":proof['before'],"provider_calls":0,"schema_changes":0,"secret_values_recorded":False}
            start = {key:value for key,value in ready.items() if key not in {'observed_at','catalog_before'}}
            start.update(schema='noteai.item33.capture_service_start.v1',state='STARTED_UNKNOWN',
                started_at=(self.now-timedelta(seconds=1)).isoformat(),deadline=(self.now+timedelta(minutes=20)).isoformat())
            if ready_bad: ready['configuration_sha256']='f'*64
            for name,value,mode in [('runtime-config.json',config,0o444),('service-ready.json',ready,0o600),('service-started.json',start,0o600)]:
                path=capture_root/name;path.write_text(json.dumps(value));path.chmod(mode)
            if capture_failed: (capture_root/'service-failure.json').write_text('{}')
            unit_path = root / controller.UNIT_NAME
            unit_path.write_bytes(controller.render_managed_unit(original, runtime_profile=controller.V5_PROFILE, normal=phase == "normal") if active else original)
            unit_path.chmod(0o644)
            session_path = root / "session.env"
            session_path.write_bytes(b"SYNTHETIC=local-only\n")
            session_path.chmod(0o600)
            run_root = root / "run"
            run_root.mkdir()
            systemd = root / "systemd"
            systemd.mkdir()
            if temp_artifact: (run_root / "noteai-item33-runtime-abc12345").mkdir()
            unit = {"FragmentPath": str(unit_path), "DropInPaths": "bad.conf" if unit_dropin else "",
                    "LoadState": "loaded", "ActiveState": "active" if active else "inactive",
                    "SubState": "running" if active else "dead", "UnitFileState": "enabled" if active else "disabled",
                    "MainPID": "123" if active else "0", "ControlPID": "0", "ExecStartPost": (
                        "{ path=/usr/bin/docker ; argv[]=/usr/bin/docker exec noteai-xhs-trends python market_timing_worker.py --healthcheck ; "
                        "pid=789 ; code=exited ; status=" + ("0" if health else "1") + " }")}
            show_count = 0
            def run(argv):
                nonlocal show_count
                commands.append(argv)
                if argv[:2] == ["systemctl", "show"]:
                    show_count += 1
                    observed = dict(unit)
                    if change_after and show_count > 1: observed["MainPID"] = "321"
                    return ("\n".join(key + "=" + value for key, value in observed.items()) + "\n").encode()
                if argv[0] == "sha256sum":
                    return (("f" * 64 if session_wrong else reader.SESSION_SHA256) + "  " + str(session_path) + "\n").encode()
                if argv[:3] == ["docker", "image", "inspect"]:
                    return json.dumps({"id": "sha256:" + controller.V5_IMAGE_CONFIG_SHA256, "role": "xhs-http",
                                       "entrypoint": ["/app/scripts/docker_entrypoint.sh"], "cmd": ["/bin/false"]}).encode()
                if argv[:3] == ["docker", "container", "ls"]:
                    if "task=item33-trends-capture" in argv[-1]: return ("c"*64+"\n").encode() if collector else b""
                    if "service=noteai-xhs-trends" in argv[-1] or "name=" in argv[-1]:
                        return (self.cid + "\n").encode() if active else b""
                    if task and "item32-readonly-successor" in argv[-1]: return ("e" * 64 + "\n").encode()
                    return b""
                if argv[:3] == ["docker", "container", "inspect"]:
                    if argv[-1]=="c"*64: return json.dumps(dict(id="c"*64,image="sha256:"+controller.V5_IMAGE_CONFIG_SHA256,running=True,paused=False,restarting=False,pid=789)).encode()
                    return json.dumps(container).encode()
                raise AssertionError("Unapproved command")
            stack.enter_context(mock.patch.object(controller, "_load_verified_dependencies", return_value=fixture.dependencies()))
            stack.enter_context(mock.patch.object(actions, "UNIT_PATH", unit_path))
            stack.enter_context(mock.patch.object(controller,"V5_CAPTURE_ROOT",capture_root))
            stack.enter_context(mock.patch.object(reader,"_namespace_pid",return_value=2 if namespace_bad else 1))
            stack.enter_context(mock.patch.object(actions, "_assert_host_identity"))
            stack.enter_context(mock.patch.object(actions.Item33HostUnitActions, "_assert_overlays"))
            stack.enter_context(mock.patch.object(actions.Item33HostUnitActions, "_assert_capture"))
            stack.enter_context(mock.patch.object(reader, "SESSION_PATH", session_path))
            stack.enter_context(mock.patch.object(reader, "RUN_ROOT", run_root))
            stack.enter_context(mock.patch.object(reader, "SYSTEMD_ROOT", systemd))
            result = reader.read_host_facts(phase=phase, dependencies=fixture.dependencies(),
                capture_binding=fixture.capture(), clock=lambda: self.now, run=run,
                process_matches=lambda pid, args: process_ok)
        return result, commands

    def test_active_facts_are_safe_and_do_not_claim_new_database_health(self):
        result, commands = self.invoke()
        self.assertEqual(result["formal_container_count"], 1)
        self.assertTrue(result["startup_healthcheck_succeeded"])
        self.assertNotIn("health", result)
        self.assertNotIn("database_role", result)
        self.assertEqual(result["observation_database_connections"], 0)
        self.assertNotIn("synthetic-untrusted", json.dumps(result))
        self.assertNotIn(self.cid, json.dumps(result))
        self.assertNotIn("Env", json.dumps(result))
        self.assertTrue(all(command[0] in {"systemctl", "docker", "sha256sum"} for command in commands))
        self.assertFalse(any(any(word in command for word in ("start", "run", "exec", "restart", "enable")) for command in commands))
        self.assertEqual(sum(command[:3] == ["docker", "container", "inspect"] for command in commands), 2)

    def test_normal_host_uses_eight_mounts_without_capture_socket(self):
        result, _ = self.invoke(phase="normal")
        self.assertEqual(result["unit_sha256"], controller.V5_NORMAL_UNIT_SHA256)
        self.assertEqual(result["formal_container_count"], 1)
        self.assertTrue(result["startup_healthcheck_succeeded"])

    def test_preflight_and_rollback_require_inactive_original_without_health_probe(self):
        for phase in ("preflight", "rollback"):
            with self.subTest(phase=phase):
                result, commands = self.invoke(phase=phase)
                self.assertEqual(result["unit_sha256"], controller.SUSPENDED_UNIT_SHA256)
                self.assertEqual(result["process_count"], 0)
                self.assertIsNone(result["startup_healthcheck_succeeded"])
                self.assertEqual(sum(command[:3] == ["docker", "container", "inspect"] for command in commands),2 if phase=="preflight" else 0)
                self.assertEqual(result["capture_container_count"],1 if phase=="preflight" else 0)
                self.assertFalse(result["capture_service_failure_present"])

    def test_collector_label_requires_actual_ready_binding_and_live_namespace_pid(self):
        for options,code in [(dict(phase="preflight",collector=False),"host_capture_container_or_failure"),
                             (dict(phase="preflight",ready_bad=True),"host_capture_ready"),
                             (dict(phase="preflight",namespace_bad=True),"host_capture_process"),
                             (dict(phase="normal",collector=True),"host_capture_container_or_failure"),
                             (dict(phase="normal",capture_failed=True),"host_capture_container_or_failure")]:
            with self.subTest(options=options), self.assertRaisesRegex(controller.Item33ExecutionError,code): self.invoke(**options)

    def test_wrong_runtime_source_mount_or_flag_fails_without_mutation(self):
        changes = [lambda value: value.update(image="sha256:" + "e" * 64),
                   lambda value: value["mounts"][0].update(RW=True),
                   lambda value: value["flags"].insert(0, {"name": "NOTEAI_XHS_PROTOCOL", "matches": False}),
                   lambda value: value.update(entrypoint=["/bin/sh"])]
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(controller.Item33ExecutionError, "host_runtime_binding"):
                self.invoke(change=change)

    def test_unknown_task_pid_dropin_and_changed_unit_each_fail_closed(self):
        cases = [(dict(task=True), "host_task_container_present"), (dict(process_ok=False), "host_runtime_binding"),
                 (dict(unit_dropin=True), "host_unit_binding"), (dict(change_after=True), "host_readback_changed")]
        for options, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(controller.Item33ExecutionError, code): self.invoke(**options)

    def test_health_exit_is_not_assumed_and_changed_session_is_not_accepted(self):
        for options, code in [(dict(health=False), "host_startup_health_unproven"),
                              (dict(session_wrong=True), "host_session_binding"),
                              (dict(temp_artifact=True), "host_temporary_artifact_present")]:
            with self.subTest(code=code), self.assertRaisesRegex(controller.Item33ExecutionError, code): self.invoke(**options)


class PureHostProjectionTests(unittest.TestCase):
    def test_env_template_projects_booleans_and_never_whole_env(self):
        template = reader._inspect_format()
        self.assertIn("range .Config.Env", template)
        self.assertNotIn("json .Config.Env", template)
        self.assertNotIn("{{println .}}", template)
        self.assertNotIn("COOKIES", template)
        self.assertNotIn("DATABASE_URL", template)
        self.assertEqual(template.count('"matches":'), len(reader.FLAGS))

    def test_unknown_or_duplicate_container_ids_are_rejected(self):
        for raw in (b"unknown\n", b"a" * 64 + b"\n" + b"a" * 64 + b"\n"):
            with self.assertRaisesRegex(controller.Item33ExecutionError, "host_container_inventory"):
                reader._ids(raw)

    def test_prior_health_fragment_cannot_be_inferred_from_missing_or_failed_command(self):
        self.assertFalse(reader._startup_health_passed(""))
        self.assertFalse(reader._startup_health_passed("{ argv[]=/bin/false ; code=exited ; status=0 ; pid=1 }"))


if __name__ == "__main__":
    unittest.main()
