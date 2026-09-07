import json
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import Mock, patch

from tools import submit_item34_managed_track as tool


TRACK_ID = "cb5a0714-1d3b-493a-ae37-f026c45dd9b4"
ROW = {"id": TRACK_ID, "xhs_note_id": tool.NOTE_ID, "domain": "宠物猫",
       "status": "pending", "submitted_at": "real-server-time"}


class SubmissionTest(unittest.TestCase):
    def execute(self, responses, journal=None):
        call = Mock(side_effect=responses)
        journal = journal or Mock()
        with patch.object(tool, "before_deadline"):
            result = tool.submit("existing-user", "private-password", "宠物猫", journal, call)
        return result, call, journal

    def test_success_uses_server_identity_without_logging_credentials(self):
        row, call, journal = self.execute([
            (200, {"token": "private-token", "user": {"phone": "private-phone"}}),
            (200, {"notes": []}), (200, {"id": TRACK_ID}), (200, ROW),
        ])
        self.assertEqual(row["id"], TRACK_ID)
        self.assertEqual(call.call_args_list[-1].args[1], "/notes/tracking/" + TRACK_ID)
        self.assertEqual(call.call_args_list[2].args[2]["published_at"], None)
        logged = repr(journal.mock_calls)
        for secret in ("private-password", "private-token", "private-phone", "existing-user"):
            self.assertNotIn(secret, logged)
        self.assertIn("SOURCE_BOUNDED_NOT_OBSERVED", logged)

    def test_unknown_post_is_read_back_once_and_never_replayed(self):
        _, call, _ = self.execute([
            (200, {"token": "t"}), (200, {"notes": []}),
            (None, {}), (200, {"notes": [ROW]}),
        ])
        self.assertEqual([c.args[1] for c in call.call_args_list].count("/notes/track-url"), 1)

    def test_existing_target_needs_no_post(self):
        _, call, _ = self.execute([(200, {"token": "t"}), (200, {"notes": [ROW]})])
        self.assertEqual(call.call_count, 2)

    def test_unknown_login_stops_without_retry(self):
        call = Mock(return_value=(None, {}))
        with patch.object(tool, "before_deadline"), self.assertRaisesRegex(ValueError, "login_unknown"):
            tool.submit("u", "p", "宠物猫", Mock(), call)
        self.assertEqual(call.call_count, 1)

    def test_multiple_target_rows_stop_before_post(self):
        with self.assertRaisesRegex(ValueError, "target_not_unique"):
            self.execute([(200, {"token": "t"}), (200, {"notes": [ROW, ROW]})])

    def test_missing_unknown_result_does_not_become_success(self):
        with self.assertRaisesRegex(ValueError, "managed_result_unknown"):
            self.execute([(200, {"token": "t"}), (200, {"notes": []}),
                          (None, {}), (200, {"notes": []})])

    def test_failed_journal_blocks_auth_dispatch(self):
        journal = Mock()
        journal.write.side_effect = OSError("disk full")
        call = Mock()
        with patch.object(tool, "before_deadline"), self.assertRaises(OSError):
            tool.submit("u", "p", "宠物猫", journal, call)
        call.assert_not_called()

    def test_window_closure_blocks_auth_dispatch(self):
        call = Mock()
        with patch.object(tool, "before_deadline", side_effect=ValueError("old_window_closed")), \
                self.assertRaisesRegex(ValueError, "old_window_closed"):
            tool.submit("u", "p", "宠物猫", Mock(), call)
        call.assert_not_called()

    def test_transport_is_loopback_and_does_not_follow_redirect(self):
        connection = Mock()
        connection.getresponse.return_value.status = 302
        connection.getresponse.return_value.read.return_value = b"{}"
        with patch.object(tool.http.client, "HTTPConnection", return_value=connection) as factory:
            self.assertEqual(tool.request("POST", "/auth/login", {"username": "u"}), (302, {}))
        factory.assert_called_once_with("127.0.0.1", 8000, timeout=20)
        connection.request.assert_called_once()
        connection.close.assert_called_once()

    def test_private_journal_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "managed.host.jsonl"
            journal = tool.Journal(path)
            journal.write("test", actual_row_mutations=None)
            journal.close()
            self.assertIsNone(json.loads(path.read_text())["actual_row_mutations"])
            with self.assertRaises(FileExistsError):
                tool.Journal(path)

    def test_exception_body_cannot_leak_authorization(self):
        self.assertEqual(tool.safe_error(ValueError("Invalid header value b'Bearer private-token'")), "ValueError")
        self.assertEqual(tool.safe_error(ValueError("target_not_unique")), "target_not_unique")

    def test_echo_fallback_is_refused(self):
        def fallback(*args):
            warnings.warn("Cannot control echo", tool.getpass.GetPassWarning)
            self.fail("must not read an echoing password")
        with patch.object(tool.getpass, "getpass", side_effect=fallback), \
                self.assertRaises(tool.getpass.GetPassWarning):
            tool.hidden_password()


if __name__ == "__main__":
    unittest.main()
