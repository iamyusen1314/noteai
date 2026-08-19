from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import inspect
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import traceback
import unittest
from urllib.parse import quote
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "item26_aliyun_official_read_v2.py"
EXTRACTOR = ROOT / "tools" / "extract_item26_manual_cost_stop_raw_v2.py"
SPEC = importlib.util.spec_from_file_location(
    "item26_aliyun_official_read_v2_test_target",
    SOURCE,
)
assert SPEC is not None and SPEC.loader is not None
TARGET = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TARGET
SPEC.loader.exec_module(TARGET)


NOW_UNIX = 1_787_105_000
EXPIRATION = NOW_UNIX + 7200
VECTOR_ACCESS_KEY_ID = "testid000"
ACCESS_KEY_ID = "STS.testid000"
ACCESS_KEY_SECRET = "testsecret"
SECURITY_TOKEN = "testtoken"


def credential_raw(**overrides: object) -> bytes:
    value: dict[str, object] = {
        "schema": TARGET.CREDENTIAL_SCHEMA,
        "source": "BRIDGE_PROJECTED_CLI_OAUTH_TEMPORARY_STS",
        "profile_name": TARGET.PROFILE_NAME,
        "region_id": TARGET.REGION_ID,
        "access_key_id": ACCESS_KEY_ID,
        "access_key_secret": ACCESS_KEY_SECRET,
        "security_token": SECURITY_TOKEN,
        "expiration_unix": EXPIRATION,
    }
    value.update(overrides)
    return TARGET.canonical_json(value)


def rds_request() -> dict[str, object]:
    return {
        "Action": "DescribeDBInstances",
        "Version": "2014-08-15",
        "RegionId": "cn-shenzhen",
        "DBInstanceId": "db-fake",
        "PageNumber": 1,
        "PageSize": 100,
    }


def actiontrail_request() -> dict[str, object]:
    return {
        "Action": "LookupEvents",
        "Version": "2020-07-06",
        "Direction": "FORWARD",
        "StartTime": "2026-08-16T14:38:00Z",
        "EndTime": "2026-08-16T14:46:00Z",
        "LookupAttribute": [
            {"Key": "ServiceName", "Value": "Rds"},
            {"Key": "EventRW", "Value": "Write"},
        ],
        "MaxResults": "50",
    }


def billing_request() -> dict[str, object]:
    return {
        "Action": "QueryInstanceBill",
        "Version": "2017-12-14",
        "BillingCycle": "2026-08",
        "ProductCode": "rds",
        "SubscriptionType": "PayAsYouGo",
        "IsBillingItem": False,
        "IsHideZeroCharge": False,
        "Granularity": "MONTHLY",
        "PageNum": 1,
        "PageSize": 300,
    }


class FakeResponse:
    def __init__(
        self,
        raw: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        read_error: BaseException | None = None,
    ) -> None:
        self.raw = raw
        self.status = status
        self.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
            **(headers or {}),
        }
        self.read_error = read_error
        self.read_count = 0

    def getheader(self, name: str, default: object = None) -> object:
        return self.headers.get(name, default)

    def read(self, maximum: int) -> bytes:
        self.read_count += 1
        if self.read_error is not None:
            raise self.read_error
        return self.raw[:maximum]


class FakeConnection:
    def __init__(
        self,
        response: FakeResponse,
        *,
        request_error: BaseException | None = None,
    ) -> None:
        self.response = response
        self.request_error = request_error
        self.requests: list[tuple[object, ...]] = []
        self.close_count = 0

    def request(
        self,
        method: str,
        target: str,
        *,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        self.requests.append((method, target, body, dict(headers)))
        if self.request_error is not None:
            raise self.request_error

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.close_count += 1


class Item26AliyunOfficialReadV2Tests(unittest.TestCase):
    def fake_rds_identity(self) -> mock._patch:
        return mock.patch.object(
            TARGET,
            "EXPECTED_OLD_CLONE_SHA256",
            hashlib.sha256(b"db-fake").hexdigest(),
        )

    def credential(self) -> object:
        return TARGET._load_temporary_credential_envelope(
            credential_raw(),
            now_unix=NOW_UNIX,
        )

    def signed(
        self,
        request: dict[str, object],
        timestamp: str,
        nonce: str,
    ) -> tuple[str, dict[str, str], str]:
        host, parameters = TARGET._signed_rpc_parameters(
            request,
            TARGET.TemporaryCredential(
                VECTOR_ACCESS_KEY_ID,
                ACCESS_KEY_SECRET,
                SECURITY_TOKEN,
                EXPIRATION,
            ),
            timestamp=timestamp,
            nonce=nonce,
        )
        encoded = "&".join(
            quote(key, safe="-_.~")
            + "="
            + quote(parameters[key], safe="-_.~")
            for key in sorted(parameters)
        )
        return host, parameters, encoded

    def test_official_cli_3411_rds_signature_vector(self) -> None:
        host, parameters, encoded = self.signed(
            rds_request(),
            "2026-08-19T14:41:40Z",
            "9f54bf6a99cbecd60ff7612afa26c4d0",
        )
        self.assertEqual(host, "rds.aliyuncs.com")
        self.assertEqual(
            parameters["Signature"],
            "VmD8OdlXwo5bccR+yDmSvoqHt8g=",
        )
        self.assertEqual(
            encoded,
            "AccessKeyId=testid000&Action=DescribeDBInstances&"
            "DBInstanceId=db-fake&Format=JSON&PageNumber=1&PageSize=100&"
            "RegionId=cn-shenzhen&SecurityToken=testtoken&"
            "Signature=VmD8OdlXwo5bccR%2ByDmSvoqHt8g%3D&"
            "SignatureMethod=HMAC-SHA1&"
            "SignatureNonce=9f54bf6a99cbecd60ff7612afa26c4d0&"
            "SignatureType=&SignatureVersion=1.0&"
            "Timestamp=2026-08-19T14%3A41%3A40Z&Version=2014-08-15",
        )

    def test_official_cli_3411_actiontrail_signature_vector(self) -> None:
        host, parameters, encoded = self.signed(
            actiontrail_request(),
            "2026-08-19T14:41:41Z",
            "de27800e39f9d097c4e678ad3a964c7d",
        )
        self.assertEqual(host, "actiontrail.cn-shenzhen.aliyuncs.com")
        self.assertEqual(
            parameters["Signature"],
            "nSrSrkYz9te3wIEpcdpahL1mMso=",
        )
        self.assertIn(
            "LookupAttribute=%5B%7B%22Key%22%3A%22ServiceName%22%2C"
            "%22Value%22%3A%22Rds%22%7D%2C%7B%22Key%22%3A%22EventRW"
            "%22%2C%22Value%22%3A%22Write%22%7D%5D",
            encoded,
        )
        self.assertNotIn("LookupAttribute.1", encoded)
        self.assertIn("RegionId=cn-shenzhen", encoded)
        self.assertEqual(
            encoded,
            "AccessKeyId=testid000&Action=LookupEvents&Direction=FORWARD&"
            "EndTime=2026-08-16T14%3A46%3A00Z&Format=JSON&"
            "LookupAttribute=%5B%7B%22Key%22%3A%22ServiceName%22%2C"
            "%22Value%22%3A%22Rds%22%7D%2C%7B%22Key%22%3A%22EventRW"
            "%22%2C%22Value%22%3A%22Write%22%7D%5D&MaxResults=50&"
            "RegionId=cn-shenzhen&SecurityToken=testtoken&"
            "Signature=nSrSrkYz9te3wIEpcdpahL1mMso%3D&"
            "SignatureMethod=HMAC-SHA1&"
            "SignatureNonce=de27800e39f9d097c4e678ad3a964c7d&"
            "SignatureType=&SignatureVersion=1.0&"
            "StartTime=2026-08-16T14%3A38%3A00Z&"
            "Timestamp=2026-08-19T14%3A41%3A41Z&Version=2020-07-06",
        )

    def test_official_cli_3411_billing_signature_vector(self) -> None:
        host, parameters, encoded = self.signed(
            billing_request(),
            "2026-08-19T14:41:41Z",
            "451a74b201d339de95a9e19d0cc0018b",
        )
        self.assertEqual(host, "business.aliyuncs.com")
        self.assertEqual(
            parameters["Signature"],
            "SWfGf0Qg0RrwG2FKKC9h/qPW7no=",
        )
        self.assertIn("IsBillingItem=false", encoded)
        self.assertIn("IsHideZeroCharge=false", encoded)
        self.assertIn("RegionId=cn-shenzhen", encoded)
        self.assertEqual(
            encoded,
            "AccessKeyId=testid000&Action=QueryInstanceBill&"
            "BillingCycle=2026-08&Format=JSON&Granularity=MONTHLY&"
            "IsBillingItem=false&IsHideZeroCharge=false&PageNum=1&"
            "PageSize=300&ProductCode=rds&RegionId=cn-shenzhen&"
            "SecurityToken=testtoken&"
            "Signature=SWfGf0Qg0RrwG2FKKC9h%2FqPW7no%3D&"
            "SignatureMethod=HMAC-SHA1&"
            "SignatureNonce=451a74b201d339de95a9e19d0cc0018b&"
            "SignatureType=&SignatureVersion=1.0&"
            "SubscriptionType=PayAsYouGo&"
            "Timestamp=2026-08-19T14%3A41%3A41Z&Version=2017-12-14",
        )

    def test_request_contract_accepts_only_three_read_shapes(self) -> None:
        with self.fake_rds_identity():
            for value in (
                rds_request(),
                actiontrail_request(),
                billing_request(),
            ):
                raw = TARGET.canonical_json(value)
                self.assertEqual(TARGET._validate_logical_request(raw), value)
        drift = rds_request()
        drift["RegionId"] = "cn-hangzhou"
        with self.assertRaisesRegex(TARGET.TransportError, "request_describe"):
            TARGET._validate_logical_request(TARGET.canonical_json(drift))
        mutation = rds_request()
        mutation["Action"] = "DeleteDBInstance"
        with self.assertRaisesRegex(TARGET.TransportError, "request_operation"):
            TARGET._validate_logical_request(TARGET.canonical_json(mutation))
        noncanonical = json.dumps(rds_request(), indent=2).encode("ascii")
        with self.assertRaisesRegex(TARGET.TransportError, "request_canonical"):
            TARGET._validate_logical_request(noncanonical)

    def test_actiontrail_lookup_contract_and_token_are_bounded(self) -> None:
        value = actiontrail_request()
        value["NextToken"] = "next-page"
        self.assertEqual(
            TARGET._validate_logical_request(TARGET.canonical_json(value)),
            value,
        )
        value["LookupAttribute"] = [
            {"Key": "EventName", "Value": "DeleteDBInstance"},
            {"Key": "ResourceName", "Value": "db-fake"},
        ]
        with self.assertRaisesRegex(
            TARGET.TransportError,
            "request_lookup_attributes",
        ):
            TARGET._validate_logical_request(TARGET.canonical_json(value))
        value = actiontrail_request()
        value["NextToken"] = "x" * 4097
        with self.assertRaisesRegex(
            TARGET.TransportError,
            "request_next_token",
        ):
            TARGET._validate_logical_request(TARGET.canonical_json(value))
        value["NextToken"] = "bad\ud800"
        with self.assertRaisesRegex(
            TARGET.TransportError,
            "request_next_token",
        ):
            TARGET._validate_logical_request(TARGET.canonical_json(value))

    def test_clone_lookup_exact_window_and_hashed_identity_pass(self) -> None:
        value = actiontrail_request()
        value.update(
            {
                "StartTime": TARGET.CLONE_CREATE_LOOKUP_START,
                "EndTime": TARGET.CLONE_CREATE_LOOKUP_END,
                "LookupAttribute": [
                    {"Key": "EventName", "Value": "CloneDBInstance"},
                    {"Key": "ResourceName", "Value": "db-fake"},
                ],
            }
        )
        with self.fake_rds_identity():
            self.assertEqual(
                TARGET._validate_logical_request(
                    TARGET.canonical_json(value)
                ),
                value,
            )

    def test_item26_windows_and_identity_hashes_match_frozen_extractor(self) -> None:
        tree = ast.parse(EXTRACTOR.read_text(encoding="utf-8"))
        assignments: dict[str, object] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and target.id in {
                    "COST_STOP_LOOKUP_START",
                    "COST_STOP_LOOKUP_END",
                    "CLONE_CREATE_LOOKUP_START",
                    "CLONE_CREATE_LOOKUP_END",
                    "EXPECTED_OLD_CLONE_SHA256",
                    "EXPECTED_SOURCE_SHA256",
                }:
                    assignments[target.id] = ast.literal_eval(node.value)
        self.assertEqual(
            assignments,
            {
                "COST_STOP_LOOKUP_START": TARGET.COST_STOP_LOOKUP_START,
                "COST_STOP_LOOKUP_END": TARGET.COST_STOP_LOOKUP_END,
                "CLONE_CREATE_LOOKUP_START": (
                    TARGET.CLONE_CREATE_LOOKUP_START
                ),
                "CLONE_CREATE_LOOKUP_END": TARGET.CLONE_CREATE_LOOKUP_END,
                "EXPECTED_OLD_CLONE_SHA256": (
                    TARGET.EXPECTED_OLD_CLONE_SHA256
                ),
                "EXPECTED_SOURCE_SHA256": TARGET.EXPECTED_SOURCE_SHA256,
            },
        )

    def test_transport_rejects_non_item26_windows_and_resource_ids(self) -> None:
        with self.assertRaisesRegex(
            TARGET.TransportError,
            "request_instance_identity",
        ):
            TARGET._validate_logical_request(
                TARGET.canonical_json(rds_request())
            )
        lookup = actiontrail_request()
        lookup["StartTime"] = "2026-08-16T00:00:00Z"
        with self.assertRaisesRegex(
            TARGET.TransportError,
            "request_lookup_window",
        ):
            TARGET._validate_logical_request(TARGET.canonical_json(lookup))
        create = actiontrail_request()
        create.update(
            {
                "StartTime": TARGET.CLONE_CREATE_LOOKUP_START,
                "EndTime": TARGET.CLONE_CREATE_LOOKUP_END,
                "LookupAttribute": [
                    {"Key": "EventName", "Value": "CloneDBInstance"},
                    {"Key": "ResourceName", "Value": "db-wrong"},
                ],
            }
        )
        with self.assertRaisesRegex(
            TARGET.TransportError,
            "request_lookup_identity",
        ):
            TARGET._validate_logical_request(TARGET.canonical_json(create))

    def test_credential_profile_is_fixed_and_hidden_from_repr(self) -> None:
        credential = self.credential()
        rendered = repr(credential)
        for secret in (ACCESS_KEY_ID, ACCESS_KEY_SECRET, SECURITY_TOKEN):
            self.assertNotIn(secret, rendered)
        for overrides, code in (
            ({"expiration_unix": NOW_UNIX + 959}, "credential_expired"),
            (
                {"expiration_unix": NOW_UNIX + 24 * 60 * 60 + 1},
                "credential_expired",
            ),
            ({"region_id": "cn-hangzhou"}, "credential_identity"),
            ({"oauth_refresh_token": "prohibited"}, "credential_contract"),
            ({"profile_name": "default"}, "credential_identity"),
            ({"access_key_id": "longterm000"}, "credential_access_key_id"),
            ({"access_key_secret": "bad\ud800"},
             "credential_access_key_secret"),
            ({"security_token": "bad\nvalue"},
             "credential_security_token"),
        ):
            with self.assertRaisesRegex(TARGET.TransportError, code) as raised:
                TARGET._load_temporary_credential_envelope(
                    credential_raw(**overrides),
                    now_unix=NOW_UNIX,
                )
            for secret in (ACCESS_KEY_ID, ACCESS_KEY_SECRET, SECURITY_TOKEN):
                self.assertNotIn(secret, str(raised.exception))

        noncanonical = json.dumps(
            json.loads(credential_raw()),
            indent=2,
        ).encode("ascii")
        with self.assertRaisesRegex(
            TARGET.TransportError,
            "credential_canonical",
        ):
            TARGET._load_temporary_credential_envelope(
                noncanonical,
                now_unix=NOW_UNIX,
            )

    def test_duplicate_credential_key_is_rejected_without_secret_echo(self) -> None:
        raw = credential_raw().replace(
            b'"profile_name":"noteai-item26-m1"',
            b'"profile_name":"noteai-item26-m1",'
            b'"profile_name":"duplicate"',
        )
        with self.assertRaisesRegex(
            TARGET.TransportError,
            "json_duplicate_key",
        ) as raised:
            TARGET._load_temporary_credential_envelope(
                raw,
                now_unix=NOW_UNIX,
            )
        self.assertNotIn(ACCESS_KEY_SECRET, str(raised.exception))

    def test_one_request_preserves_exact_provider_body(self) -> None:
        provider_raw = b'{ "RequestId" : "fake-request" }\n'
        response = FakeResponse(provider_raw)
        connection = FakeConnection(response)
        factory_calls: list[tuple[str, int]] = []

        def factory(host: str, *, timeout: int) -> FakeConnection:
            factory_calls.append((host, timeout))
            return connection

        with self.fake_rds_identity():
            result = TARGET._dispatch_authorized_bytes(
                TARGET.canonical_json(rds_request()),
                credential_raw(),
                now=(NOW_UNIX, "2026-08-19T14:41:40Z"),
                nonce="9f54bf6a99cbecd60ff7612afa26c4d0",
                connection_factory=factory,
            )
        self.assertEqual(result.response, provider_raw)
        self.assertEqual(result.cloud_call_count, 1)
        self.assertEqual(result.cloud_write_count, 0)
        self.assertEqual(result.automatic_retry_count, 0)
        self.assertEqual(
            factory_calls,
            [("rds.aliyuncs.com", TARGET.CONNECT_AND_READ_TIMEOUT_SECONDS)],
        )
        self.assertEqual(len(connection.requests), 1)
        method, target, body, headers = connection.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(body, b"")
        self.assertTrue(target.startswith("/?AccessKeyId="))
        self.assertEqual(headers["Accept-Encoding"], "identity")
        self.assertEqual(connection.close_count, 1)
        self.assertEqual(response.read_count, 1)

    def test_transport_failure_is_fixed_and_never_retried(self) -> None:
        connection = FakeConnection(
            FakeResponse(b'{"RequestId":"unused"}\n'),
            request_error=TimeoutError("contains testtoken and testsecret"),
        )
        with self.fake_rds_identity(), self.assertRaisesRegex(
            TARGET.TransportError,
            "transport_failure",
        ) as raised:
            TARGET._dispatch_authorized_bytes(
                TARGET.canonical_json(rds_request()),
                credential_raw(),
                now=(NOW_UNIX, "2026-08-19T14:41:40Z"),
                nonce="9f54bf6a99cbecd60ff7612afa26c4d0",
                connection_factory=lambda _host, timeout: connection,
            )
        self.assertEqual(raised.exception.cloud_dispatch_count, 1)
        self.assertEqual(len(connection.requests), 1)
        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("testtoken", str(raised.exception))
        self.assertNotIn("testsecret", str(raised.exception))

    def test_http_and_response_failures_do_not_retry(self) -> None:
        rows = (
            FakeResponse(b'{"Code":"Denied"}\n', status=403),
            FakeResponse(
                b'{"RequestId":"fake"}\n',
                headers={"Content-Encoding": "gzip"},
            ),
            FakeResponse(b'{"RequestId":"one","RequestId":"two"}\n'),
            FakeResponse(b"not-json"),
            FakeResponse(
                b'{"RequestId":"short"}\n',
                headers={"Content-Length": "999"},
            ),
            FakeResponse(
                b'{"RequestId":"unread"}\n',
                headers={
                    "Content-Length": str(TARGET.MAX_RESPONSE_BYTES + 1)
                },
            ),
            FakeResponse(
                b'{"RequestId":"unread"}\n',
                read_error=OSError("testtoken testsecret"),
            ),
        )
        for response in rows:
            with self.subTest(status=response.status, raw=response.raw):
                connection = FakeConnection(response)
                with self.fake_rds_identity(), self.assertRaises(
                    TARGET.TransportError
                ) as raised:
                    TARGET._dispatch_authorized_bytes(
                        TARGET.canonical_json(rds_request()),
                        credential_raw(),
                        now=(NOW_UNIX, "2026-08-19T14:41:40Z"),
                        nonce="9f54bf6a99cbecd60ff7612afa26c4d0",
                        connection_factory=lambda _host, timeout: connection,
                    )
                self.assertEqual(raised.exception.cloud_dispatch_count, 1)
                self.assertEqual(len(connection.requests), 1)
                self.assertEqual(connection.close_count, 1)
                self.assertNotIn("Denied", str(raised.exception))
                self.assertNotIn("testtoken", str(raised.exception))
                self.assertNotIn("testsecret", str(raised.exception))

    def test_factory_failure_is_pre_request_and_secret_free(self) -> None:
        def fail_factory(_host: str, *, timeout: int) -> object:
            del timeout
            raise OSError("testsecret testtoken")

        with self.fake_rds_identity(), self.assertRaisesRegex(
            TARGET.TransportError,
            "transport_failure",
        ) as raised:
            TARGET._dispatch_authorized_bytes(
                TARGET.canonical_json(rds_request()),
                credential_raw(),
                now=(NOW_UNIX, "2026-08-19T14:41:40Z"),
                nonce="9f54bf6a99cbecd60ff7612afa26c4d0",
                connection_factory=fail_factory,
            )
        self.assertEqual(raised.exception.cloud_dispatch_count, 0)
        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("testsecret", str(raised.exception))

    def test_fd_only_entry_uses_three_anonymous_distinct_descriptors(self) -> None:
        request_writer, request_reader = socket.socketpair()
        credential_writer, credential_reader = socket.socketpair()
        response_reader, response_writer = socket.socketpair()
        sockets = (
            request_writer,
            request_reader,
            credential_writer,
            credential_reader,
            response_reader,
            response_writer,
        )
        try:
            request_writer.sendall(TARGET.canonical_json(rds_request()))
            request_writer.shutdown(socket.SHUT_WR)
            credential_writer.sendall(credential_raw())
            credential_writer.shutdown(socket.SHUT_WR)
            provider_raw = b'{ "RequestId" : "fd-response" }\n'
            connection = FakeConnection(FakeResponse(provider_raw))
            with self.fake_rds_identity():
                result = TARGET._dispatch_authorized_fds(
                    request_reader.fileno(),
                    credential_reader.fileno(),
                    response_writer.fileno(),
                    now=(NOW_UNIX, "2026-08-19T14:41:40Z"),
                    nonce="9f54bf6a99cbecd60ff7612afa26c4d0",
                    connection_factory=lambda _host, timeout: connection,
                )
            response_writer.shutdown(socket.SHUT_WR)
            self.assertEqual(response_reader.recv(65536), provider_raw)
            self.assertEqual(
                result,
                {
                    "request_fd_read_count": 1,
                    "credential_fd_read_count": 1,
                    "response_fd_write_count": 1,
                    "cloud_dispatch_count": 1,
                    "cloud_write_count": 0,
                    "automatic_retry_count": 0,
                },
            )
            self.assertEqual(len(connection.requests), 1)
        finally:
            for item in sockets:
                item.close()

    def test_fd_entry_rejects_regular_files_aliases_and_stdio(self) -> None:
        devnull = os.open(os.devnull, os.O_RDONLY)
        left, right = socket.socketpair()
        duplicate = os.dup(left.fileno())
        try:
            for fds in (
                (devnull, left.fileno(), right.fileno()),
                (left.fileno(), left.fileno(), right.fileno()),
                (left.fileno(), duplicate, right.fileno()),
                (0, left.fileno(), right.fileno()),
            ):
                with self.subTest(fds=fds), self.assertRaises(
                    TARGET.TransportError
                ):
                    TARGET._dispatch_authorized_fds(*fds)
        finally:
            os.close(devnull)
            os.close(duplicate)
            left.close()
            right.close()

    def test_fd_entry_rejects_tcp_named_unix_and_regular_file(self) -> None:
        left, right = socket.socketpair()
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with tempfile.TemporaryFile() as regular, tempfile.TemporaryDirectory() as tmp:
            named = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            named.bind(str(Path(tmp) / "named.sock"))
            try:
                for bad in (tcp.fileno(), named.fileno(), regular.fileno()):
                    with self.subTest(fd=bad), self.assertRaises(
                        TARGET.TransportError
                    ):
                        TARGET._dispatch_authorized_fds(
                            bad,
                            left.fileno(),
                            right.fileno(),
                        )
            finally:
                named.close()
                tcp.close()
                left.close()
                right.close()

    def test_fd_entry_rejects_unix_seqpacket_before_dispatch(self) -> None:
        seqpacket = getattr(socket, "SOCK_SEQPACKET", None)
        if seqpacket is None:
            self.skipTest("SOCK_SEQPACKET is unavailable")
        try:
            bad_left, bad_right = socket.socketpair(
                socket.AF_UNIX,
                seqpacket,
            )
        except OSError:
            self.skipTest("AF_UNIX SOCK_SEQPACKET socketpair is unavailable")
        good_left, good_right = socket.socketpair()
        try:
            with mock.patch.object(TARGET, "_dispatch_authorized_bytes") as dispatch:
                with self.assertRaisesRegex(
                    TARGET.TransportError,
                    "request_fd_identity",
                ):
                    TARGET._dispatch_authorized_fds(
                        bad_left.fileno(),
                        good_left.fileno(),
                        good_right.fileno(),
                    )
                dispatch.assert_not_called()
        finally:
            bad_left.close()
            bad_right.close()
            good_left.close()
            good_right.close()

    def test_fd_entry_rejects_closed_response_write_half_before_dispatch(self) -> None:
        request_writer, request_reader = socket.socketpair()
        credential_writer, credential_reader = socket.socketpair()
        response_reader, response_writer = socket.socketpair()
        sockets = (
            request_writer,
            request_reader,
            credential_writer,
            credential_reader,
            response_reader,
            response_writer,
        )
        try:
            response_writer.shutdown(socket.SHUT_WR)
            with mock.patch.object(TARGET, "_dispatch_authorized_bytes") as dispatch:
                with self.assertRaisesRegex(
                    TARGET.TransportError,
                    "response_fd_write_preflight",
                ):
                    TARGET._dispatch_authorized_fds(
                        request_reader.fileno(),
                        credential_reader.fileno(),
                        response_writer.fileno(),
                    )
                dispatch.assert_not_called()
        finally:
            for item in sockets:
                item.close()

    def test_fd_entry_rejects_nonblocking_input_or_output_before_dispatch(self) -> None:
        for nonblocking_role in ("request", "response"):
            request_writer, request_reader = socket.socketpair()
            credential_writer, credential_reader = socket.socketpair()
            response_reader, response_writer = socket.socketpair()
            sockets = (
                request_writer,
                request_reader,
                credential_writer,
                credential_reader,
                response_reader,
                response_writer,
            )
            try:
                target = (
                    request_reader
                    if nonblocking_role == "request"
                    else response_writer
                )
                target.setblocking(False)
                with mock.patch.object(
                    TARGET,
                    "_dispatch_authorized_bytes",
                ) as dispatch:
                    with self.subTest(role=nonblocking_role), self.assertRaisesRegex(
                        TARGET.TransportError,
                        nonblocking_role + "_fd_identity",
                    ):
                        TARGET._dispatch_authorized_fds(
                            request_reader.fileno(),
                            credential_reader.fileno(),
                            response_writer.fileno(),
                        )
                    dispatch.assert_not_called()
            finally:
                for item in sockets:
                    item.close()

    def test_public_entry_is_root_only_and_has_no_injection_parameters(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(TARGET.dispatch_authorized_fds).parameters),
            ("request_fd", "credential_fd", "response_fd"),
        )
        with mock.patch.object(TARGET.os, "geteuid", return_value=501), mock.patch.object(
            TARGET,
            "_dispatch_authorized_fds",
        ) as private:
            with self.assertRaisesRegex(TARGET.TransportError, "root_required"):
                TARGET.dispatch_authorized_fds(3, 4, 5)
            private.assert_not_called()

    def test_public_entry_checks_core_and_isolation_before_credential_read(self) -> None:
        with mock.patch.object(TARGET.os, "geteuid", return_value=0), mock.patch.object(
            TARGET.resource,
            "getrlimit",
            return_value=(1, 1),
        ), mock.patch.object(TARGET, "_dispatch_authorized_fds") as private:
            with self.assertRaisesRegex(
                TARGET.TransportError,
                "core_dump_enabled",
            ):
                TARGET.dispatch_authorized_fds(3, 4, 5)
            private.assert_not_called()

        fake_flags = type(
            "Flags",
            (),
            {
                "isolated": 1,
                "ignore_environment": 1,
                "no_user_site": 1,
                "no_site": 0,
            },
        )()
        with mock.patch.object(TARGET.sys, "dont_write_bytecode", True), mock.patch.object(
            TARGET.sys,
            "flags",
            fake_flags,
        ):
            self.assertFalse(TARGET._isolated_runtime())

        with mock.patch.object(TARGET.os, "geteuid", return_value=0), mock.patch.object(
            TARGET.resource,
            "getrlimit",
            return_value=(0, 0),
        ), mock.patch.object(
            TARGET,
            "_isolated_runtime",
            return_value=False,
        ), mock.patch.object(TARGET, "_dispatch_authorized_fds") as private:
            with self.assertRaisesRegex(
                TARGET.TransportError,
                "isolated_runtime_required",
            ):
                TARGET.dispatch_authorized_fds(3, 4, 5)
            private.assert_not_called()

    def test_public_entry_suppresses_causes_and_maps_unknown_errors(self) -> None:
        def credential_failure(*_args: object) -> object:
            try:
                raise UnicodeError("testsecret testtoken")
            except UnicodeError as exc:
                raise TARGET.TransportError("credential_json") from exc

        boundary = (
            mock.patch.object(TARGET.os, "geteuid", return_value=0),
            mock.patch.object(
                TARGET.resource,
                "getrlimit",
                return_value=(0, 0),
            ),
            mock.patch.object(TARGET, "_isolated_runtime", return_value=True),
        )
        with boundary[0], boundary[1], boundary[2], mock.patch.object(
            TARGET,
            "_dispatch_authorized_fds",
            side_effect=credential_failure,
        ):
            with self.assertRaisesRegex(
                TARGET.TransportError,
                "credential_json",
            ) as raised:
                TARGET.dispatch_authorized_fds(3, 4, 5)
        formatted = "".join(
            traceback.format_exception(
                type(raised.exception),
                raised.exception,
                raised.exception.__traceback__,
            )
        )
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertNotIn("testsecret", formatted)
        self.assertNotIn("testtoken", formatted)

        with mock.patch.object(TARGET.os, "geteuid", return_value=0), mock.patch.object(
            TARGET.resource,
            "getrlimit",
            return_value=(0, 0),
        ), mock.patch.object(
            TARGET,
            "_isolated_runtime",
            return_value=True,
        ), mock.patch.object(
            TARGET,
            "_dispatch_authorized_fds",
            side_effect=RuntimeError("testsecret testtoken"),
        ):
            with self.assertRaisesRegex(
                TARGET.TransportError,
                "transport_internal",
            ) as unknown:
                TARGET.dispatch_authorized_fds(3, 4, 5)
        self.assertIsNone(unknown.exception.__cause__)
        self.assertIsNone(unknown.exception.__context__)
        self.assertTrue(unknown.exception.__suppress_context__)
        self.assertNotIn("testsecret", str(unknown.exception))

    def test_tls_context_ignores_default_environment_and_disables_keylog(self) -> None:
        class FakeContext:
            def __init__(self) -> None:
                self.minimum_version = None
                self.check_hostname = False
                self.verify_mode = None
                self.keylog_filename = None
                self.cadata: str | None = None

            def load_verify_locations(self, *, cadata: str) -> None:
                self.cadata = cadata

        context = FakeContext()
        marker = object()
        with mock.patch.object(
            TARGET.ssl,
            "create_default_context",
            side_effect=AssertionError("environment-dependent TLS forbidden"),
        ) as default_context, mock.patch.object(
            TARGET.ssl,
            "SSLContext",
            return_value=context,
        ) as constructor, mock.patch.object(
            TARGET,
            "_system_ca_payload",
            return_value=b"PINNED TEST CA",
        ), mock.patch.object(
            TARGET.http.client,
            "HTTPSConnection",
            return_value=marker,
        ) as connection:
            self.assertIs(
                TARGET._default_connection(
                    "rds.aliyuncs.com",
                    timeout=30,
                ),
                marker,
            )
        default_context.assert_not_called()
        constructor.assert_called_once_with(TARGET.ssl.PROTOCOL_TLS_CLIENT)
        self.assertEqual(context.minimum_version, TARGET.ssl.TLSVersion.TLSv1_2)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, TARGET.ssl.CERT_REQUIRED)
        self.assertIsNone(context.keylog_filename)
        self.assertEqual(context.cadata, "PINNED TEST CA")
        connection.assert_called_once_with(
            "rds.aliyuncs.com",
            timeout=30,
            context=context,
        )
        self.assertEqual(TARGET.SYSTEM_CA_PATH, "/etc/ssl/cert.pem")
        self.assertEqual(TARGET.SYSTEM_CA_BYTES, 333483)
        self.assertEqual(
            TARGET.SYSTEM_CA_SHA256,
            "9dae8d76e55cb08991f2b672d58999ea15560d910759c16b544f843bdffbb994",
        )

    def test_operational_source_has_no_path_env_subprocess_or_cli_entry(self) -> None:
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        imports = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertNotIn("subprocess", imports)
        self.assertNotIn("pathlib", imports)
        forbidden_attributes = {
            (node.value.id, node.attr)
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
        }
        self.assertNotIn(("os", "environ"), forbidden_attributes)
        self.assertNotIn(("os", "getenv"), forbidden_attributes)
        self.assertEqual(
            TARGET.__all__,
            ("dispatch_authorized_fds", "source_only_status", "main"),
        )

    def test_main_is_inert_even_with_execute_like_arguments(self) -> None:
        stream = io.StringIO()
        with mock.patch.object(TARGET.sys, "stdout", stream):
            self.assertEqual(TARGET.main(["--execute-authorized-read"]), 2)
        value = json.loads(stream.getvalue())
        self.assertEqual(value["status"], "SOURCE_ONLY_NOT_AUTHORIZED")
        self.assertFalse(value["authorizes_new_action"])
        self.assertEqual(value["cloud_call_count"], 0)
        self.assertEqual(value["credential_value_read_count"], 0)


if __name__ == "__main__":
    unittest.main()
