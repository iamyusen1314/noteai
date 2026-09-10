import json
import io
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "model"), str(ROOT / "tools")]
import spider_xhs_http as xhs
import security_redaction as redaction
import diagnose_item34_xhs as diagnostic


class ResponseDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "NOTEAI_XHS_ACQUISITION_ADAPTER": xhs.ADAPTER_NAME,
            "NOTEAI_RUNTIME_ROLE": "xhs-http", "NOTEAI_XHS_SERVICE": "tracking",
            "NOTEAI_XHS_COLLECTION_SUSPENDED": "0",
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.safety = types.SimpleNamespace(collection_safety_status=lambda: {"session_blocked": False})
        modules = mock.patch.dict(sys.modules, {"xhs_acquisition": self.safety})
        modules.start()
        self.addCleanup(modules.stop)
        self.signer = mock.Mock()
        self.signer.sign.return_value = {"xs": "FAKE_SIG", "xt": "1", "xs_common": "FAKE_COMMON", "x_rap_param": "FAKE_RAP"}
        self.records = []
        self.sent = []

    def factory(self, *, client):
        return xhs.SpiderXHSHTTPAdapter(client=client, signer=self.signer,
            credentials=xhs.SessionCredentials.from_records([
                {"name": "a1", "value": "FAKE_A1"}, {"name": "web_session", "value": "FAKE_SESSION"},
            ]))

    def test_complete_request_cookie_staging_is_private_and_does_not_apply(self):
        cookie = "Cookie: a1=FAKE_A1; web_session=FAKE_SESSION==; gid=FAKE_GID; webBuild=6.47.2; custom=FAKE_CONTEXT"
        rows = diagnostic.request_cookie_records(cookie)
        self.assertEqual([r["name"] for r in rows], ["a1", "web_session", "gid", "webBuild", "custom"])
        self.assertEqual(rows[1]["value"], "FAKE_SESSION==")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "session-candidate.env"
            output = io.StringIO()
            with mock.patch.object(diagnostic, "Path", return_value=path), \
                 mock.patch.object(diagnostic.os, "geteuid", return_value=0), \
                 mock.patch.object(sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(sys.stderr, "isatty", return_value=True), \
                 mock.patch.object(diagnostic.getpass, "getpass", side_effect=[cookie, ""]) as prompt, \
                 mock.patch.object(sys, "stdout", output), \
                 mock.patch.object(diagnostic, "readonly_safety") as db_read:
                self.assertEqual(diagnostic.stage_session(), 0)
                with self.assertRaisesRegex(diagnostic.DiagnosticStop, "existing_session_candidate"):
                    diagnostic.stage_session()
                db_read.assert_not_called()
                self.assertEqual(prompt.call_count, 2)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text().split("=", 1)[1]), rows)
            self.assertNotIn("FAKE", output.getvalue())
            self.assertEqual(list(Path(folder).iterdir()), [path])
        for raw in ("a1=FAKE", "a1=FAKE; web_session=FAKE\nBAD=VALUE", "a1=FAKE; a1=FAKE2; web_session=FAKE"):
            with self.assertRaises(diagnostic.DiagnosticStop):
                diagnostic.request_cookie_records(raw)

    def execute(self, handler, *, safety=lambda: {"session_blocked": False}):
        def send(request):
            self.sent.append(request)
            return handler(request)
        return diagnostic.run(self.records.append, transport=httpx.MockTransport(send),
                              adapter_factory=self.factory, safety=safety)

    def test_business_rejection_retains_only_bounded_metadata(self):
        result = self.execute(lambda _: httpx.Response(200, json={
            "success": False, "code": -10001, "msg": "参数错误 FAKE_SECRET_RAW_TEXT",
            "data": {"code": "3001", "message": "FAKE_USER_CONTENT", "cookie": "FAKE_COOKIE"},
        }))
        self.assertEqual(result["outcome"], "REMOTE_REJECTED")
        self.assertEqual(result["error_code"], "remote_business_error")
        meta = result["response_diagnostics"]
        self.assertEqual(meta["http_status"], 200)
        self.assertEqual(meta["business_code"], -10001)
        self.assertEqual(meta["nested_business_code"], "3001")
        self.assertEqual(meta["message_tags"], ["invalid_parameter"])
        output = json.dumps(self.records)
        for forbidden in ("FAKE_", "cookie", "Authorization", "source_note_id"):
            self.assertNotIn(forbidden, output)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual([r["event"] for r in self.records],
                         ["safety_readback", "dispatch_intent", "response_headers_received", "result"])

    def test_validation_success_contract_is_unchanged(self):
        for code in (None, 0, "0", "", "ok", "success"):
            payload = {"success": True, "code": code}
            self.assertIs(xhs._validate_response(200, payload), payload)
        for code in (200, "200", -1):
            with self.assertRaises(xhs.XHSAdapterError) as caught:
                xhs._validate_response(200, {"success": True, "code": code})
            self.assertEqual(caught.exception.code, "remote_business_error")
        with self.assertRaises(xhs.XHSAdapterError):
            xhs._validate_response(200, {"success": False, "code": 0})

    def test_malicious_metadata_and_string_codes_cannot_leak(self):
        payload = {"code": "FAKE_CREDENTIAL", "success": False,
                   "msg": "FAKE_SECRET", "data": {"code": "19872819531"}}
        meta = redaction.xhs_response_diagnostics(200, payload)
        meta.update({"cookie": "FAKE_COOKIE", "message_tags": ["login", {}, "FAKE_SECRET"],
                     "business_code": "FAKE_TOKEN", "http_status": "FAKE_AUTH"})
        event = redaction.sanitize_crawler_event({"action": "note_error", "response_diagnostics": meta})
        self.assertNotIn("FAKE", json.dumps(event))
        self.assertNotIn("19872819531", json.dumps(event))
        self.assertEqual(event["response_diagnostics"]["message_tags"], ["login"])

    def test_redirect_is_one_request_and_location_is_not_recorded(self):
        result = self.execute(lambda _: httpx.Response(302,
            headers={"Location": "https://example.invalid/?token=FAKE_TOKEN"}, text="FAKE_BODY"))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(result["response_diagnostics"]["http_status"], 302)
        self.assertEqual(result["response_diagnostics"]["payload_kind"], "non_json")
        self.assertNotIn("FAKE", json.dumps(self.records))

    def test_timeout_is_unknown_and_not_retried(self):
        def timeout(request):
            raise httpx.ReadTimeout("FAKE_SECRET", request=request)
        result = self.execute(timeout)
        self.assertEqual(result["outcome"], "UNKNOWN")
        self.assertEqual(result["provider_admissions"], 1)
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn("FAKE", json.dumps(self.records))

    def test_operator_and_persistent_stops_prevent_signing_and_request(self):
        for stop in ("operator", "persistent", "unavailable"):
            with self.subTest(stop=stop):
                os.environ["NOTEAI_XHS_COLLECTION_SUSPENDED"] = "1" if stop == "operator" else "0"
                def safety():
                    raise diagnostic.DiagnosticStop("persistent_session_stop" if stop == "persistent" else "safety_unavailable")
                result = self.execute(lambda _: self.fail("HTTP forbidden"), safety=safety)
                self.assertEqual(result["provider_admissions"], 0)
        self.signer.sign.assert_not_called()
        self.assertEqual(self.sent, [])

    def test_guard_blocks_second_send_before_transport(self):
        guard = diagnostic.OneRequest(self.records.append, lambda: {})
        request = httpx.Request("POST", diagnostic.ENDPOINT, json={
            "source_note_id": diagnostic.NOTE_URL.rsplit("/", 1)[1],
            "image_formats": ["jpg", "webp", "avif"], "extra": {"need_body_topic": "1"},
            "xsec_source": "pc_search", "xsec_token": "",
        })
        guard.before(request)
        with self.assertRaisesRegex(diagnostic.DiagnosticStop, "additional_or_unapproved"):
            guard.before(request)
        self.assertEqual(guard.admitted, 1)
        self.assertEqual(len(self.records), 1)

    def test_partial_existing_journal_never_calls_database_or_http(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "result.jsonl"
            path.write_text('{"event":"dispatch_intent"')
            with mock.patch.object(diagnostic, "JOURNAL", path), mock.patch.object(
                diagnostic, "configure_readonly_database") as configure, mock.patch.object(sys, "argv", ["diagnose"]):
                with self.assertRaises(FileExistsError):
                    diagnostic.main()
                configure.assert_not_called()
            self.assertEqual(path.read_text(), '{"event":"dispatch_intent"')

    def test_repair_records_initialization_separately_and_unknown_never_retries(self):
        os.environ["NOTEAI_XHS_PROTOCOL"] = "pc_v5"
        def factory(*, http_observer):
            adapter = mock.Mock(last_response_diagnostics={}, last_owned_metrics=None)
            def read(url):
                self.assertEqual(url, diagnostic.NOTE_URL)
                for phase in ("dispatch", "unknown"):
                    http_observer({"phase": phase, "request_kind": "dsl", "sequence": 1,
                                   "at": "2026-09-11T01:02:03.000000+00:00"})
                raise xhs.XHSAdapterError("network_error")
            adapter.note_detail.side_effect = read
            return adapter
        result = diagnostic.run_repair(self.records.append, adapter_factory=factory, safety=lambda: {})
        self.assertEqual(result["outcome"], "UNKNOWN")
        self.assertEqual(result["physical_http_requests"], 1)
        self.assertEqual(result["initialization_requests"], 1)
        self.assertEqual(result["provider_detail_admissions"], 0)
        self.assertEqual(result["automatic_retries"], 0)

    def test_repair_actual_adapter_wires_durable_observer_before_mock_network(self):
        os.environ["NOTEAI_XHS_PROTOCOL"] = "pc_v5"
        def factory(*, http_observer):
            client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403)))
            self.addCleanup(client.close)
            return xhs.SpiderXHSHTTPAdapter(client=client, signer=self.signer,
                credentials=xhs.SessionCredentials.from_records([
                    {"name": "a1", "value": "a" * 52}, {"name": "web_session", "value": "FAKE_SESSION"},
                ]), http_observer=http_observer)
        result = diagnostic.run_repair(self.records.append, adapter_factory=factory, safety=lambda: {})
        self.assertEqual(result["error_code"], "login_or_challenge_required")
        self.assertEqual(result["physical_http_requests"], 1)
        self.assertEqual([r["event"] for r in self.records], ["safety_readback", "xhs_http", "xhs_http", "result"])

    def test_repair_refuses_existing_journal_and_unprojected_private_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "repair.jsonl"
            path.write_text('partial')
            with mock.patch.object(diagnostic, "REPAIR_JOURNAL", path), mock.patch.object(
                sys, "argv", ["diagnose", "--repair-v5"]), mock.patch.object(diagnostic, "run_repair") as run:
                with self.assertRaises(FileExistsError):
                    diagnostic.main()
                run.assert_not_called()
        value = {"phase": "response", "request_kind": "session", "sequence": 2,
                 "at": "2026-09-11T01:02:03+00:00", "Cookie": "FAKE_SECRET",
                 "response_diagnostics": {"http_status": 200, "body": "FAKE_PRIVATE"}}
        self.assertNotIn("FAKE", json.dumps(redaction.sanitize_xhs_http_event(value)))

    def test_readonly_configuration_preserves_pg_routing_and_dsn_options(self):
        import db
        from psycopg.conninfo import conninfo_to_dict
        os.environ["DATABASE_URL"] = (
            "postgresql://fake:FAKE_PASSWORD@example.invalid/noteai?sslmode=require"
            "&options=-c%20application_name%3Ditem34&connect_timeout=90"
        )
        os.environ["PGOPTIONS"] = "-c application_name=ignored"
        diagnostic.configure_readonly_database()
        self.assertTrue(db.using_postgres())
        query = parse_qs(urlsplit(os.environ["DATABASE_URL"]).query)
        self.assertEqual(query["sslmode"], ["require"])
        self.assertEqual(query["connect_timeout"], ["5"])
        self.assertEqual(query["options"], [
            "-c application_name=item34 -c default_transaction_read_only=on -c statement_timeout=5000"])
        self.assertEqual(conninfo_to_dict(os.environ["DATABASE_URL"])["options"], query["options"][0])
        conn = mock.Mock()
        conn.execute.return_value.fetchone.side_effect = [
            {"role": "noteai_xhs_tracking", "readonly": "on"},
            {"value_json": '{"session_blocked":false}', "is_secret": False},
        ]
        with mock.patch.object(db, "get_conn", return_value=conn):
            self.assertTrue(diagnostic.readonly_safety()["transaction_read_only"])
        conn.close.assert_called_once()
        self.assertEqual(len(conn.execute.call_args_list), 2)
        self.assertTrue(all(call.args[0].startswith("SELECT ") for call in conn.execute.call_args_list))

    def test_readonly_safety_rejects_mutable_connection_before_state_read(self):
        import db
        os.environ["DATABASE_URL"] = "postgresql://fake@example.invalid/noteai"
        conn = mock.Mock()
        conn.execute.return_value.fetchone.return_value = {"role": "noteai_xhs_tracking", "readonly": "off"}
        with mock.patch.object(db, "get_conn", return_value=conn):
            with self.assertRaisesRegex(diagnostic.DiagnosticStop, "readonly_identity"):
                diagnostic.readonly_safety()
        conn.execute.assert_called_once()
        conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
