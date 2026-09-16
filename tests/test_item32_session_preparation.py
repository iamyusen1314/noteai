import base64
from contextlib import redirect_stdout
import fcntl
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import warnings

from tools import prepare_item32_session as m


class SessionPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/"sessions"
        self.root.mkdir(mode=0o700)
        self.directory = self.root/("a"*32)
        self.directory.mkdir(mode=0o700)
        self.target = Path(self.temp.name)/"xhs-trends.env"
        self.lock = Path(self.temp.name)/"executor.lock"
        self.original = b"# retained\r\nDATABASE_URL=postgresql://FAKE_DATABASE\r\nNOTEAI_XHS_COOKIES_JSON=[]\r\nOTHER=keep-exact\n"
        self.target.write_bytes(self.original)
        self.target.chmod(0o600)
        self.lock.write_bytes(b"")
        self.lock.chmod(0o600)
        self.raw_cookie = "a1=FAKE_A1; web_session=FAKE_SESSION; gid=FAKE_EXISTING_GID; extra_cookie=context=="
        self.candidate = b"NOTEAI_XHS_COOKIES_JSON="+m.encoded(m.cookie_records(self.raw_cookie))+b"\n"
        (self.directory/"session-candidate.env").write_bytes(self.candidate)
        (self.directory/"session-candidate.env").chmod(0o600)
        for name, value in [("ROOT",self.root),("TARGET",self.target),("LOCK",self.lock)]:
            patch = mock.patch.object(m,name,value)
            patch.start()
            self.addCleanup(patch.stop)

    def apply(self):
        return m.apply_once(self.directory,expected_env_sha=m.digest(self.original),expected_unit_sha="b"*64)

    def test_complete_cookie_context_preserved_and_malformed_denied(self):
        records=m.cookie_records(self.raw_cookie)
        self.assertEqual([r["name"] for r in records],["a1","web_session","gid","extra_cookie"])
        self.assertEqual(records[-1]["value"],"context==")
        for raw in ["a1=x", "a1=x; web_session=y; a1=z", "a1=x\n; web_session=y", "a1=x; web_session="]:
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                m.cookie_records(raw)

    def test_merge_only_changes_cookie_and_existing_optional_state(self):
        original=self.original+b"NOTEAI_XHS_WEB_SSK_JSON=old-unbound-state\n"
        merged=m.merge_trends_env(original,self.candidate)
        rows=m.env_rows(merged)
        self.assertEqual(rows["DATABASE_URL"],"postgresql://FAKE_DATABASE")
        self.assertEqual(rows["NOTEAI_XHS_WEB_SSK_JSON"],"")
        self.assertNotIn("NOTEAI_XHS_PROTOCOL",rows)
        self.assertNotIn("NOTEAI_XHS_V5_BUDGET_JSON",rows)
        self.assertIn(b"# retained\r\nDATABASE_URL=postgresql://FAKE_DATABASE\r\n",merged)
        self.assertIn(b"OTHER=keep-exact\n",merged)
        self.assertEqual(len(json.loads(rows["NOTEAI_XHS_COOKIES_JSON"])),4)

    def test_optional_existing_webssk_is_validated_never_invented(self):
        ssk=m.encoded({"xhs-pc-web":base64.b64encode(b"f"*32).decode()})
        candidate=self.candidate+b"NOTEAI_XHS_WEB_SSK_JSON="+ssk+b"\n"
        self.assertEqual(m.env_rows(m.merge_trends_env(self.original,candidate))["NOTEAI_XHS_WEB_SSK_JSON"],ssk.decode())
        for value in [b"{}",b'{"xhs-pc-web":"invalid"}',b'{"other":"abc"}']:
            with self.assertRaises((ValueError,TypeError)):
                m.validate_candidate(self.candidate+b"NOTEAI_XHS_WEB_SSK_JSON="+value+b"\n")

    def test_candidate_cannot_replace_database_or_duplicate_env(self):
        for candidate in [self.candidate+b"DATABASE_URL=other\n",self.candidate+self.candidate,
                          self.candidate.replace(b'"path":"/"',b'"path":"/other"')]:
            with self.assertRaises(ValueError):
                m.merge_trends_env(self.original,candidate)

    def test_apply_retains_recovery_bytes_without_runtime_or_database_action(self):
        with mock.patch.object(m,"quiescent") as quiescent:
            result=self.apply()
        self.assertEqual(quiescent.call_count,3)
        self.assertEqual(result["state"],"APPLIED_SUSPENDED_NOT_PROVIDER_VALIDATED")
        self.assertEqual((result["xhs_requests"],result["database_operations"],result["service_restarts"]),(0,0,0))
        self.assertFalse(result["session_block_cleared"])
        self.assertEqual((self.directory/"original.env").read_bytes(),self.original)
        self.assertEqual((self.directory/"merged.env").read_bytes(),self.target.read_bytes())
        self.assertEqual(self.target.stat().st_mode&0o777,0o600)
        self.assertNotIn("FAKE",json.dumps(result))

    def test_existing_once_marker_cannot_be_replayed(self):
        with mock.patch.object(m,"quiescent"):
            self.apply()
            after=self.target.read_bytes()
            with self.assertRaises(FileExistsError):
                m.apply_once(self.directory,expected_env_sha=m.digest(after),expected_unit_sha="b"*64)
        self.assertEqual(self.target.read_bytes(),after)

    def test_interrupted_post_replace_preserves_unknown_and_backup(self):
        with mock.patch.object(m,"quiescent",side_effect=[None,None,ValueError("changed")]):
            with self.assertRaises(ValueError):
                self.apply()
        marker=json.loads((self.directory/"apply-started.json").read_bytes())
        self.assertEqual(marker["after_sha256"],m.digest(self.target.read_bytes()))
        self.assertFalse((self.directory/"apply-result.json").exists())
        self.assertEqual((self.directory/"original.env").read_bytes(),self.original)

    def test_current_env_cas_rejects_before_marker_or_write(self):
        changed=self.original+b"EXTERNAL=changed\n"
        self.target.write_bytes(changed)
        with mock.patch.object(m,"quiescent"),self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.target.read_bytes(),changed)
        self.assertFalse((self.directory/"apply-started.json").exists())

    def test_existing_executor_lock_conflict_prevents_any_action(self):
        with self.lock.open("r+b") as stream:
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            with mock.patch.object(m,"quiescent") as quiescent,self.assertRaises(BlockingIOError):
                self.apply()
            quiescent.assert_not_called()
        self.assertEqual(self.target.read_bytes(),self.original)

    def test_lock_metadata_and_replacement_are_rejected_before_env_change(self):
        self.lock.chmod(0o644)
        with mock.patch.object(m,"quiescent") as quiescent,self.assertRaises(ValueError):
            self.apply()
        quiescent.assert_not_called()
        self.lock.chmod(0o600)
        checks=[]
        def changed_lock(_):
            checks.append(True)
            if len(checks)==2:
                self.lock.unlink()
                self.lock.write_bytes(b"")
                self.lock.chmod(0o600)
        with mock.patch.object(m,"quiescent",side_effect=changed_lock),self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.target.read_bytes(),self.original)

    def test_quiescent_rejects_every_original_task_label_including_stopped(self):
        status=b"ActiveState=inactive\nSubState=dead\nJob=\nMainPID=0\nNeedDaemonReload=no\n"
        tasks=("item32-readonly","item32-xhs-diagnostic","item32-readonly-successor")
        for blocked in tasks:
            seen=[]
            def run(args,**kwargs):
                seen.append(args)
                output=status if args[0].endswith("systemctl") else (
                    b"f"*64+b"\n" if args[-1]=="label=com.noteai.task="+blocked else b"")
                return m.subprocess.CompletedProcess(args,0,output,b"")
            with self.subTest(task=blocked),mock.patch.object(m,"read_private",return_value=b"unit"), \
                 mock.patch.object(m.subprocess,"run",side_effect=run),self.assertRaises(ValueError):
                m.quiescent(m.digest(b"unit"))
            self.assertTrue(any(args[-1]=="label=com.noteai.task="+blocked for args in seen))

    def test_symlink_candidate_is_not_followed(self):
        path=self.directory/"session-candidate.env"
        path.unlink();path.symlink_to(self.target)
        with mock.patch.object(m,"quiescent"),self.assertRaises(OSError):
            self.apply()
        self.assertEqual(self.target.read_bytes(),self.original)

    def test_hidden_input_echo_failure_creates_no_candidate(self):
        output=io.StringIO()
        with mock.patch.object(m.socket,"gethostname",return_value="noteai-api-f"), \
             mock.patch.object(m.sys,"argv",["prepare_item32_session.py","stage"]), \
             mock.patch.object(m.sys.stdin,"isatty",return_value=True), \
             mock.patch.object(m.sys.stderr,"isatty",return_value=True), \
             mock.patch.object(m.getpass,"getpass",side_effect=lambda *_: warnings.warn("no echo",m.getpass.GetPassWarning)), \
             redirect_stdout(output),self.assertRaises(m.getpass.GetPassWarning):
            m.main()
        fresh=[p for p in self.root.iterdir() if p!=self.directory]
        self.assertEqual(len(fresh),1)
        self.assertFalse(list(fresh[0].iterdir()))
        self.assertEqual(output.getvalue(),"")


if __name__=="__main__":
    unittest.main()
