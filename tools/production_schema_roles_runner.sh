#!/usr/bin/env bash
set -u
set -o pipefail

mode="${1:-}"
task_root=/var/lib/noteai/schema-roles-v5-owner
source_root="${task_root}/source"
private_key="${task_root}/transport_private.pem"
ciphertext="${task_root}/database_url.enc"
import_sentinel="${task_root}/import.passed"
container_name="noteai-schema-roles-v5-owner-${mode}-once"
import_container_name=noteai-schema-roles-v5-owner-import-once
executor_sha256=56d148fbbbadc2f8b15c6cfdc5ef978f10b79dbd86dbbf5ccb272dc1ce23972a
outcome_sha256=223ee1df52e53ef53a7e3247d78a8d4e40e4792876032807d78a25d8a04861fb
preflight_sha256=2d873101db846689be20d8fee2d4adb21017fe51c54cc4ebfaffd54e58d3ad17
incident_id=PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-V5-OWNER-001
confirmation=PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001

fail_preconnect() {
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V5 mode=${mode} incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 cleanup_required=1 retry_same_path=0 ids_printed=0 secrets=0"
    exit 2
}

fail_connected_unknown() {
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V5 mode=${mode} incident_class=CONNECTED_UNKNOWN database_connection=unknown transaction=unknown database_write=unknown cleanup_required=1 container_count=${container_count:-unknown} automatic_retry=0 ids_printed=0 secrets=0"
    exit 1
}

fail_connected_known() {
    outcome="${1:-RECOVERY_REQUIRED}"
    known_write_count="${2:-0}"
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V5 mode=${mode} incident_class=CONNECTED_KNOWN database_connection=1 database_outcome=${outcome} database_write=${known_write_count} cleanup_required=1 automatic_retry=0 ids_printed=0 secrets=0"
    exit 30
}

validate_result() {
    python3 - "${1}" "${2}" <<'PY'
import json
import sys

mode = sys.argv[1]
with open(sys.argv[2], encoding="utf-8") as handle:
    result = json.load(handle)

assert result.get("task_id") == (
    "PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001"
)
for key in (
    "provider_calls",
    "service_changes",
    "public_traffic_requests",
    "secret_values_exposed",
):
    assert result.get(key) == 0

if mode == "preflight":
    assert result.get("status") == "accepted_risk_observed"
    assert result.get("incident_class") == "CONNECTED_KNOWN"
    assert result.get("read_only") is True
    assert result.get("transaction_rolled_back") is True
    assert result.get("fixed_query_count") == 4
    assert result.get("database_connection_count") == 1
    assert result.get("database_write_count") == 0
    assert result.get("acceptance") == {
        "session": True,
        "ledger_inventory": True,
        "role_graph": True,
        "xhs_acl": True,
    }
    ledger = result.get("ledger_inventory", {})
    assert ledger.get("ledger_exact") is True
    assert ledger.get("ledger_count") == 8
    assert ledger.get("table_count") == 30
    assert ledger.get("sequence_count") == 5
    assert ledger.get("ledger_sha_column_count") == 0
    assert ledger.get("new_runtime_role_count") == 0
    assert ledger.get("retention_backfill_source_count") == 0
    role = result.get("role_graph", {})
    assert role.get("membership_count") == 1
    assert role.get("membership_admin") is True
    assert role.get("membership_inherit") is False
    assert role.get("membership_set") is False
    assert role.get("app_high_privilege_inheritance_count") == 0
elif mode == "apply":
    assert result.get("status") == "verified"
    assert result.get("transaction_committed") is True
    assert result.get("applied_versions") == [
        f"{number:04d}" for number in range(9, 17)
    ]
    assert result.get("database_writes", {}) == {
        "migration_ledger_rows": 8,
        "migration_ledger_hash_backfills": 8,
        "schema_seed_rows": 2,
        "retention_backfill_rows": 0,
        "existing_business_row_updates": 0,
    }
    roles = result.get("roles", {})
    assert roles.get("membership_count") == 7
    assert roles.get("management_membership_count") == 6
    assert roles.get("migration_owner_mismatch_count") == 0
    assert roles.get("executor_owned_object_count") == 0
    assert roles.get("unexpected_membership_count") == 0
    assert roles.get("unexpected_elevation_count") == 0
    assert roles.get("high_privilege_inheritance_count") == 0
elif mode == "outcome":
    assert result.get("status") == "classified"
    assert result.get("database_outcome") in {"COMMITTED", "ROLLED_BACK"}
    assert result.get("read_only") is True
    assert result.get("default_transaction_read_only") is True
    assert result.get("transaction_read_only") is True
    assert result.get("observation", {}).get(
        "business_row_values_read"
    ) == 0
else:
    raise AssertionError("unsupported mode")
PY
}

case "${mode}" in
    prepare | preflight | apply | outcome) ;;
    *) fail_preconnect ;;
esac
test "${incident_id}" = \
    PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-V5-OWNER-001 \
    || fail_preconnect
case "${task_root}" in
    /var/lib/noteai/schema-roles-v5-owner) ;;
    *) fail_preconnect ;;
esac

test -d "${task_root}" || fail_preconnect
test ! -L "${task_root}" || fail_preconnect
test "$(stat -c '%u:%g:%a' "${task_root}")" = "0:0:700" \
    || fail_preconnect
test -d "${source_root}" || fail_preconnect
test ! -L "${source_root}" || fail_preconnect
test "$(stat -c '%u:%g:%a' "${source_root}")" = "0:0:755" \
    || fail_preconnect
test -z "$(find "${source_root}" -type l -print -quit)" \
    || fail_preconnect
test -f "${source_root}/package.sha256" || fail_preconnect
test -f "${source_root}/tools/production_schema_roles.py" \
    || fail_preconnect
test -f "${source_root}/tools/production_schema_outcome_audit.py" \
    || fail_preconnect
test -f \
    "${source_root}/tools/production_first_launch_role_risk_set_audit.py" \
    || fail_preconnect
observed_executor_line="$(
    sha256sum "${source_root}/tools/production_schema_roles.py"
)" || fail_preconnect
observed_executor_sha="${observed_executor_line%% *}"
test "${observed_executor_sha}" = "${executor_sha256}" || fail_preconnect
observed_outcome_line="$(
    sha256sum "${source_root}/tools/production_schema_outcome_audit.py"
)" || fail_preconnect
observed_outcome_sha="${observed_outcome_line%% *}"
test "${observed_outcome_sha}" = "${outcome_sha256}" || fail_preconnect
observed_preflight_line="$(
    sha256sum \
        "${source_root}/tools/production_first_launch_role_risk_set_audit.py"
)" || fail_preconnect
observed_preflight_sha="${observed_preflight_line%% *}"
test "${observed_preflight_sha}" = "${preflight_sha256}" \
    || fail_preconnect
(cd "${source_root}" && sha256sum -c package.sha256 >/dev/null 2>&1) \
    || fail_preconnect
package_manifest_line="$(
    sha256sum "${source_root}/package.sha256"
)" || fail_preconnect
package_manifest_sha="${package_manifest_line%% *}"

api_container="$(
    docker ps \
        --filter label=com.noteai.runtime.role=api \
        --format '{{.ID}}'
)" || fail_preconnect
test -n "${api_container}" || fail_preconnect
case "${api_container}" in
    *$'\n'*) fail_preconnect ;;
esac
image_id="$(
    docker inspect --format '{{.Image}}' "${api_container}" 2>/dev/null
)" || fail_preconnect
test -n "${image_id}" || fail_preconnect
existing_container="$(
    docker ps -a \
        --filter "name=^/${container_name}$" \
        --format '{{.ID}}'
)" || fail_preconnect
test -z "${existing_container}" || fail_preconnect

if test "${mode}" = prepare; then
    existing_import_container="$(
        docker ps -a \
            --filter "name=^/${import_container_name}$" \
            --format '{{.ID}}'
    )" || fail_preconnect
    test -z "${existing_import_container}" || fail_preconnect
    test ! -e "${import_sentinel}" || fail_preconnect
    docker run \
        --rm \
        --pull never \
        --network none \
        --name "${import_container_name}" \
        --user 999:999 \
        --read-only \
        --cap-drop=ALL \
        --security-opt=no-new-privileges:true \
        --pids-limit 64 \
        --memory 128m \
        --cpus 0.25 \
        --tmpfs /tmp:rw,noexec,nosuid,nodev,size=8m \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -e PYTHONPATH=/task/tools \
        -v "${source_root}:/task:ro" \
        -w /task \
        --entrypoint python \
        "${image_id}" \
        -c 'import production_schema_roles; import production_schema_outcome_audit; import production_first_launch_role_risk_set_audit' \
        >/dev/null 2>&1 \
        || fail_preconnect
    printf '%s\n' "${package_manifest_sha}" >"${import_sentinel}" \
        || fail_preconnect
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V5 mode=prepare incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 import=passed cleanup_required=1 automatic_retry=0 ids_printed=0 secrets=0"
    exit 0
fi

test -f "${import_sentinel}" || fail_preconnect
observed_import_sha="$(tr -d '\n' <"${import_sentinel}")" \
    || fail_preconnect
test "${observed_import_sha}" = "${package_manifest_sha}" \
    || fail_preconnect
test -f "${private_key}" || fail_preconnect
test -f "${ciphertext}" || fail_preconnect
test ! -L "${private_key}" || fail_preconnect
test ! -L "${ciphertext}" || fail_preconnect
test "$(stat -c '%u:%g' "${private_key}")" = "0:0" || fail_preconnect
test "$(stat -c '%u:%g' "${ciphertext}")" = "0:0" || fail_preconnect
test "$(stat -c '%a' "${private_key}")" = 600 || fail_preconnect
test "$(stat -c '%a' "${ciphertext}")" = 600 || fail_preconnect
test "$(stat -c '%h' "${private_key}")" = 1 || fail_preconnect
test "$(stat -c '%h' "${ciphertext}")" = 1 || fail_preconnect
cipher_bytes="$(wc -c <"${ciphertext}" | tr -d ' ')" || fail_preconnect
test "${cipher_bytes}" = 384 || fail_preconnect
openssl pkey -in "${private_key}" -check -noout >/dev/null 2>&1 \
    || fail_preconnect

if test "${mode}" = preflight; then
    result_path="${task_root}/preflight-result.json"
    result_tmp="${result_path}.tmp"
    error_path="${task_root}/preflight-error.log"
    prepared_sentinel="${task_root}/preflight.prepared"
    dispatch_sentinel="${task_root}/preflight.started"
    python_code='import sys; value=sys.stdin.read(); from production_first_launch_role_risk_set_audit import main; code=main(database_url=value); del value; raise SystemExit(code)'
elif test "${mode}" = apply; then
    result_path="${task_root}/apply-result.json"
    result_tmp="${result_path}.tmp"
    error_path="${task_root}/apply-error.log"
    prepared_sentinel="${task_root}/apply.prepared"
    dispatch_sentinel="${task_root}/apply.started"
    preflight_result="${task_root}/preflight-result.json"
    test -s "${preflight_result}" || fail_preconnect
    validate_result preflight "${preflight_result}" >/dev/null 2>&1 \
        || fail_preconnect
    python_code='import sys; value=sys.stdin.read(); from production_schema_roles import main; code=main(["--apply"],database_url=value,confirmation=sys.argv[1]); del value; raise SystemExit(code)'
else
    result_path="${task_root}/outcome-result.json"
    result_tmp="${result_path}.tmp"
    error_path="${task_root}/outcome-error.log"
    prepared_sentinel="${task_root}/outcome.prepared"
    dispatch_sentinel="${task_root}/outcome.started"
    test -f "${task_root}/apply.started" || fail_preconnect
    python_code='import sys; value=sys.stdin.read(); from production_schema_outcome_audit import main; code=main(database_url=value); del value; raise SystemExit(code)'
fi

test ! -e "${dispatch_sentinel}" || fail_preconnect
test ! -e "${result_path}" || fail_preconnect
rm -f "${result_tmp}" "${error_path}" "${prepared_sentinel}" \
    || fail_preconnect
printf 'prepared\n' >"${prepared_sentinel}" || fail_preconnect
printf 'dispatched\n' >"${dispatch_sentinel}" || fail_preconnect

set +e
openssl pkeyutl \
    -decrypt \
    -inkey "${private_key}" \
    -pkeyopt rsa_padding_mode:oaep \
    -pkeyopt rsa_oaep_md:sha256 \
    -in "${ciphertext}" 2>"${error_path}" \
    | docker run \
        --rm \
        --pull never \
        --network host \
        --name "${container_name}" \
        --user 999:999 \
        --read-only \
        --cap-drop=ALL \
        --security-opt=no-new-privileges:true \
        --pids-limit 128 \
        --memory 256m \
        --cpus 0.5 \
        --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -e PYTHONPATH=/task/tools \
        -i \
        -v "${source_root}:/task:ro" \
        -w /task \
        --entrypoint python \
        "${image_id}" \
        -c "${python_code}" \
        "${confirmation}" \
        >"${result_tmp}" 2>>"${error_path}"
pipeline_status=("${PIPESTATUS[@]}")

openssl_exit="${pipeline_status[0]:-125}"
task_exit="${pipeline_status[1]:-125}"
error_bytes="$(wc -c <"${error_path}" | tr -d ' ')" \
    || fail_connected_unknown
container_ids="$(
    docker ps -a \
        --filter "name=^/${container_name}$" \
        --format '{{.ID}}'
)" || fail_connected_unknown
container_count=0
test -z "${container_ids}" || container_count=1
result_bytes=0
if test -f "${result_tmp}"; then
    result_bytes="$(wc -c <"${result_tmp}" | tr -d ' ')" \
        || fail_connected_unknown
fi

if { test "${task_exit}" = 126 || test "${task_exit}" = 127; } \
    && test "${container_count}" = 0 \
    && test "${result_bytes}" = 0; then
    fail_preconnect
fi

if test "${task_exit}" = 2 \
    && grep -Fq 'incident_class=PRE_CONNECT' "${error_path}" \
    && test "${container_count}" = 0; then
    rm -f "${result_tmp}" || true
    fail_preconnect
fi

if test "${mode}" = preflight \
    && test "${openssl_exit}" = 0 \
    && test "${task_exit}" = 0 \
    && test "${result_bytes}" -gt 0 \
    && validate_result preflight "${result_tmp}" >/dev/null 2>&1; then
    test "${container_count}" = 0 || fail_connected_unknown
    result_sha_line="$(sha256sum "${result_tmp}")" \
        || fail_connected_unknown
    result_sha256="${result_sha_line%% *}"
    mv "${result_tmp}" "${result_path}" || fail_connected_unknown
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V5 mode=preflight incident_class=CONNECTED_KNOWN database_connection=1 audit_transaction=rolled_back database_write=0 result_bytes=${result_bytes} result_sha256=${result_sha256} error_bytes=${error_bytes} container=0 cleanup_required=1 automatic_retry=0 ids_printed=0 secrets=0"
    exit 0
fi

if test "${mode}" = apply \
    && test "${openssl_exit}" = 0 \
    && test "${task_exit}" = 0 \
    && test "${result_bytes}" -gt 0 \
    && validate_result apply "${result_tmp}" >/dev/null 2>&1; then
    test "${container_count}" = 0 \
        || fail_connected_known COMMITTED 18
    result_sha_line="$(sha256sum "${result_tmp}")" \
        || fail_connected_known COMMITTED 18
    result_sha256="${result_sha_line%% *}"
    mv "${result_tmp}" "${result_path}" \
        || fail_connected_known COMMITTED 18
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V5 mode=apply incident_class=CONNECTED_KNOWN database_connection=1 database_outcome=COMMITTED apply_transaction=committed database_write=18 result_bytes=${result_bytes} result_sha256=${result_sha256} error_bytes=${error_bytes} container=0 cleanup_required=1 automatic_retry=0 ids_printed=0 secrets=0"
    exit 0
fi

if test "${mode}" = outcome \
    && test "${openssl_exit}" = 0 \
    && test "${task_exit}" = 0 \
    && test "${result_bytes}" -gt 0 \
    && validate_result outcome "${result_tmp}" >/dev/null 2>&1; then
    test "${container_count}" = 0 || fail_connected_unknown
    database_outcome="$(
        grep -oE '"database_outcome":"(COMMITTED|ROLLED_BACK)"' \
            "${result_tmp}" \
        | head -1 \
        | cut -d '"' -f 4
    )" || fail_connected_unknown
    result_sha_line="$(sha256sum "${result_tmp}")" \
        || fail_connected_unknown
    result_sha256="${result_sha_line%% *}"
    mv "${result_tmp}" "${result_path}" || fail_connected_unknown
    observed_writes=0
    test "${database_outcome}" = COMMITTED && observed_writes=18
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V5 mode=outcome incident_class=CONNECTED_KNOWN database_connection=1 database_outcome=${database_outcome} audit_transaction=rolled_back database_write=${observed_writes} result_bytes=${result_bytes} result_sha256=${result_sha256} error_bytes=${error_bytes} container=0 cleanup_required=1 automatic_retry=0 ids_printed=0 secrets=0"
    exit 0
fi

if test "${mode}" = preflight \
    && { test "${task_exit}" = 30 || test "${task_exit}" = 31; } \
    && test "${container_count}" = 0; then
    fail_connected_known READ_ONLY_REJECTED 0
fi

fail_connected_unknown
