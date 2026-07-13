"""DynamoDB-backed atomic control plane for the Claude Gateway."""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
from typing import Any, Callable

from control_store import (
    ControlStoreUnavailable,
    Lease,
    OperationClaim,
    OperationState,
    TERMINAL_STATES,
)


def _digest(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _s(value: str) -> dict[str, str]:
    return {"S": str(value)}


def _n(value: int) -> dict[str, str]:
    return {"N": str(int(value))}


def _conditional(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    error = response.get("Error", {}) if isinstance(response, dict) else {}
    code = error.get("Code")
    if code == "ConditionalCheckFailedException":
        return True
    if code != "TransactionCanceledException":
        return False
    reasons = response.get("CancellationReasons") if isinstance(response, dict) else None
    if not isinstance(reasons, list) or not reasons:
        return False
    reason_codes = {
        reason.get("Code", "") for reason in reasons if isinstance(reason, dict)
    }
    return (
        "ConditionalCheckFailed" in reason_codes
        and reason_codes <= {"None", "ConditionalCheckFailed"}
    )


class DynamoDBControlStore:
    def __init__(
        self,
        table_name: str,
        client: Any,
        *,
        call_timeout_seconds: float = 5.0,
        credential_method: str = "",
    ):
        self.table_name = str(table_name or "").strip()
        self.client = client
        self.call_timeout_seconds = max(0.01, float(call_timeout_seconds))
        self.credential_method = str(credential_method or "")
        if not self.table_name:
            raise ValueError("DynamoDB table name is required")

    @staticmethod
    def identity_environment_valid() -> bool:
        static_names = (
            "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
        )
        return bool(
            not any(os.environ.get(name, "").strip() for name in static_names)
            and os.environ.get("AWS_ROLE_ARN", "").strip()
            and os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE", "").strip()
            and os.environ.get("AWS_EC2_METADATA_DISABLED", "").strip().lower() == "true"
        )

    @classmethod
    def from_env(cls) -> "DynamoDBControlStore":
        import boto3
        from botocore.config import Config

        if not cls.identity_environment_valid():
            raise ValueError("DynamoDB web-identity configuration is required")
        region = os.environ.get("NOTEAI_CLAUDE_GATEWAY_DDB_REGION", "ap-southeast-1").strip()
        table = os.environ.get("NOTEAI_CLAUDE_GATEWAY_DDB_TABLE", "").strip()
        try:
            call_timeout = float(
                os.environ.get("NOTEAI_CLAUDE_GATEWAY_CONTROL_DEADLINE_SECONDS", "5") or 5
            )
        except (TypeError, ValueError):
            call_timeout = 5.0
        session = boto3.Session()
        credentials = session.get_credentials()
        credential_method = str(getattr(credentials, "method", "") or "")
        if credential_method != "assume-role-with-web-identity":
            raise ValueError("DynamoDB web-identity credentials are required")
        client = session.client(
            "dynamodb",
            region_name=region,
            config=Config(
                connect_timeout=min(2.0, max(0.1, call_timeout)),
                read_timeout=min(3.0, max(0.1, call_timeout)),
                retries={"mode": "standard", "total_max_attempts": 1},
            ),
        )
        return cls(
            table,
            client,
            call_timeout_seconds=call_timeout,
            credential_method=credential_method,
        )

    async def _call(self, method: str, **kwargs):
        fn: Callable[..., Any] = getattr(self.client, method)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fn, **kwargs),
                timeout=self.call_timeout_seconds,
            )
        except Exception as exc:
            if _conditional(exc):
                raise
            raise ControlStoreUnavailable("control store unavailable") from None

    @staticmethod
    def _principal(principal_id: str) -> str:
        return _digest(f"principal:{principal_id}")

    @staticmethod
    def _operation(operation_id: str) -> str:
        return _digest(f"operation:{operation_id}")

    async def claim_nonce(
        self,
        principal_id: str,
        nonce: str,
        now_epoch: int,
        expires_at: int,
    ) -> bool:
        if int(expires_at) <= int(now_epoch):
            return False
        principal = self._principal(principal_id)
        try:
            await self._call(
                "put_item",
                TableName=self.table_name,
                Item={
                    "pk": _s(f"NONCE#{principal}#{_digest(nonce)}"),
                    "kind": _s("NONCE"),
                    "principal_hash": _s(principal),
                    "expires_at": _n(expires_at),
                },
                ConditionExpression="attribute_not_exists(pk) OR expires_at <= :now",
                ExpressionAttributeValues={":now": _n(now_epoch)},
            )
            return True
        except BaseException as exc:
            if _conditional(exc):
                return False
            raise

    async def admit_rate(
        self, principal_id: str, now_epoch: float, limit: int, window_seconds: int,
    ) -> bool:
        principal = self._principal(principal_id)
        seconds = max(1, int(window_seconds))
        window = int(float(now_epoch) // seconds) * seconds
        try:
            await self._call(
                "update_item",
                TableName=self.table_name,
                Key={"pk": _s(f"RATE#{principal}")},
                UpdateExpression=(
                    "SET kind=:kind, principal_hash=:principal, window_start=:window, "
                    "request_count=:one, expires_at=:ttl"
                ),
                ConditionExpression=(
                    "attribute_not_exists(window_start) OR window_start < :window"
                ),
                ExpressionAttributeValues={
                    ":kind": _s("RATE"),
                    ":principal": _s(principal),
                    ":window": _n(window),
                    ":ttl": _n(window + seconds * 2),
                    ":one": _n(1),
                },
            )
            return True
        except BaseException as exc:
            if not _conditional(exc):
                raise
        try:
            await self._call(
                "update_item",
                TableName=self.table_name,
                Key={"pk": _s(f"RATE#{principal}")},
                UpdateExpression="ADD request_count :one",
                ConditionExpression=(
                    "attribute_exists(window_start) AND request_count < :limit"
                ),
                ExpressionAttributeValues={
                    ":one": _n(1),
                    ":limit": _n(limit),
                },
            )
            return True
        except BaseException as exc:
            if _conditional(exc):
                return False
            raise

    async def claim_operation(
        self,
        principal_id: str,
        operation_id: str,
    ) -> OperationClaim:
        principal = self._principal(principal_id)
        operation = self._operation(operation_id)
        key = f"OP#{operation}"
        try:
            await self._call(
                "put_item",
                TableName=self.table_name,
                Item={
                    "pk": _s(key),
                    "kind": _s("OPERATION"),
                    "principal_hash": _s(principal),
                    "operation_hash": _s(operation),
                    "state": _s(OperationState.CLAIMED.value),
                },
                ConditionExpression="attribute_not_exists(pk)",
            )
            return OperationClaim(OperationState.CLAIMED, True)
        except BaseException as exc:
            if not _conditional(exc):
                raise
        response = await self._call(
            "get_item",
            TableName=self.table_name,
            Key={"pk": _s(key)},
            ConsistentRead=True,
        )
        raw_state = response.get("Item", {}).get("state", {}).get("S", "")
        try:
            state = OperationState(raw_state)
        except ValueError:
            raise ControlStoreUnavailable("invalid operation state") from None
        return OperationClaim(state, False)

    async def acquire_lease(
        self,
        operation_id: str,
        slot_count: int,
        now_epoch: int,
        lease_seconds: int,
    ) -> Lease | None:
        operation = self._operation(operation_id)
        owner_token = secrets.token_urlsafe(24)
        owner_hash = _digest(owner_token)
        slots = max(1, int(slot_count))
        start = int(operation[:8], 16) % slots
        for offset in range(slots):
            slot = (start + offset) % slots
            try:
                response = await self._call(
                    "update_item",
                    TableName=self.table_name,
                    Key={"pk": _s(f"LEASE#{slot}")},
                    UpdateExpression=(
                        "SET kind=:kind, operation_hash=:operation, owner_hash=:owner, "
                        "lease_expires_at=:expiry, expires_at=:ttl ADD fence :one"
                    ),
                    ConditionExpression=(
                        "attribute_not_exists(lease_expires_at) OR lease_expires_at <= :now"
                    ),
                    ExpressionAttributeValues={
                        ":kind": _s("LEASE"),
                        ":operation": _s(operation),
                        ":owner": _s(owner_hash),
                        ":expiry": _n(now_epoch + lease_seconds),
                        ":ttl": _n(now_epoch + lease_seconds + 3600),
                        ":now": _n(now_epoch),
                        ":one": _n(1),
                    },
                    ReturnValues="ALL_NEW",
                )
                fence = int(response.get("Attributes", {}).get("fence", {}).get("N", "1"))
                return Lease(slot, operation, owner_token, fence, now_epoch + lease_seconds)
            except BaseException as exc:
                if _conditional(exc):
                    continue
                raise
        return None

    def _lease_values(self, lease: Lease) -> dict[str, dict[str, str]]:
        return {
            ":operation": _s(lease.operation_hash),
            ":owner": _s(_digest(lease.owner_token)),
            ":fence": _n(lease.fence),
        }

    async def begin_provider(
        self,
        operation_id: str,
        lease: Lease,
        dispatch_hash: str,
        model: str,
        now_epoch: int,
    ) -> bool:
        operation = self._operation(operation_id)
        lease_values = self._lease_values(lease)
        lease_values[":now"] = _n(now_epoch)
        operation_values = {
            ":now": _n(now_epoch),
            ":claimed": _s(OperationState.CLAIMED.value),
            ":started": _s(OperationState.PROVIDER_STARTED.value),
            ":dispatch": _s(str(dispatch_hash)),
            ":model": _s(str(model)),
        }
        try:
            await self._call(
                "transact_write_items",
                TransactItems=[
                    {"ConditionCheck": {
                        "TableName": self.table_name,
                        "Key": {"pk": _s(f"LEASE#{lease.slot}")},
                        "ConditionExpression": (
                            "operation_hash=:operation AND owner_hash=:owner AND "
                            "fence=:fence AND lease_expires_at > :now"
                        ),
                        "ExpressionAttributeValues": lease_values,
                    }},
                    {"Update": {
                        "TableName": self.table_name,
                        "Key": {"pk": _s(f"OP#{operation}")},
                        "UpdateExpression": (
                            "SET #state=:started, dispatch_hash=:dispatch, model=:model, "
                            "provider_started_at=:now REMOVE expires_at"
                        ),
                        "ConditionExpression": "#state=:claimed",
                        "ExpressionAttributeNames": {"#state": "state"},
                        "ExpressionAttributeValues": operation_values,
                    }},
                ],
            )
            return True
        except BaseException as exc:
            if _conditional(exc):
                return False
            raise

    async def renew_lease(
        self, lease: Lease, now_epoch: int, lease_seconds: int,
    ) -> Lease | None:
        values = self._lease_values(lease)
        values.update({
            ":now": _n(now_epoch),
            ":expiry": _n(now_epoch + lease_seconds),
            ":ttl": _n(now_epoch + lease_seconds + 3600),
        })
        try:
            await self._call(
                "update_item",
                TableName=self.table_name,
                Key={"pk": _s(f"LEASE#{lease.slot}")},
                UpdateExpression="SET lease_expires_at=:expiry, expires_at=:ttl",
                ConditionExpression=(
                    "operation_hash=:operation AND owner_hash=:owner AND fence=:fence "
                    "AND lease_expires_at > :now"
                ),
                ExpressionAttributeValues=values,
            )
            return Lease(
                lease.slot, lease.operation_hash, lease.owner_token,
                lease.fence, now_epoch + lease_seconds,
            )
        except BaseException as exc:
            if _conditional(exc):
                return None
            raise

    async def finish_operation(
        self,
        operation_id: str,
        lease: Lease,
        state: OperationState,
        now_epoch: int,
        *,
        retention_seconds: int,
        usage: dict[str, Any] | None = None,
        error_code: str = "",
    ) -> bool:
        if state not in TERMINAL_STATES:
            raise ValueError("terminal operation state required")
        operation = self._operation(operation_id)
        lease_values = self._lease_values(lease)
        operation_values = {
            ":started": _s(OperationState.PROVIDER_STARTED.value),
            ":terminal": _s(state.value),
            ":now": _n(now_epoch),
            ":expires": _n(
                now_epoch + max(1, min(int(retention_seconds), 90 * 24 * 60 * 60))
            ),
            ":error": _s(str(error_code or "")[:64]),
        }
        update = (
            "SET #state=:terminal, finished_at=:now, expires_at=:expires, "
            "error_code=:error"
        )
        safe_usage = usage if isinstance(usage, dict) else {}
        for field in (
            "input_tokens", "output_tokens", "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ):
            value = safe_usage.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                token = f":u_{field}"
                operation_values[token] = _n(value)
                update += f", usage_{field}={token}"
        try:
            await self._call(
                "transact_write_items",
                TransactItems=[
                    {"Update": {
                        "TableName": self.table_name,
                        "Key": {"pk": _s(f"OP#{operation}")},
                        "UpdateExpression": update,
                        "ConditionExpression": "#state=:started",
                        "ExpressionAttributeNames": {"#state": "state"},
                        "ExpressionAttributeValues": operation_values,
                    }},
                    {"Delete": {
                        "TableName": self.table_name,
                        "Key": {"pk": _s(f"LEASE#{lease.slot}")},
                        "ConditionExpression": (
                            "operation_hash=:operation AND owner_hash=:owner AND fence=:fence"
                        ),
                        "ExpressionAttributeValues": lease_values,
                    }},
                ],
            )
            return True
        except BaseException as exc:
            if _conditional(exc):
                return False
            raise

    async def release_lease(self, lease: Lease) -> bool:
        try:
            await self._call(
                "delete_item",
                TableName=self.table_name,
                Key={"pk": _s(f"LEASE#{lease.slot}")},
                ConditionExpression=(
                    "operation_hash=:operation AND owner_hash=:owner AND fence=:fence"
                ),
                ExpressionAttributeValues=self._lease_values(lease),
            )
            return True
        except BaseException as exc:
            if _conditional(exc):
                return False
            raise

    async def health(self) -> bool:
        response = await self._call("describe_table", TableName=self.table_name)
        return response.get("Table", {}).get("TableStatus") in {"ACTIVE", "UPDATING"}
