#!/usr/bin/env bash
set -u
set -o pipefail
umask 077

mode="${1:-}"
task_root=/var/lib/noteai/schema-roles-v5-owner
source_root="${task_root}/source"
private_key="${task_root}/transport_private.pem"
ciphertext="${task_root}/database_url.enc"
import_sentinel="${task_root}/import.passed"
incident_sentinel="${task_root}/incident.binding"
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
    python3 -I - "${1}" "${2}" <<'PY'
import json
import sys


def require(condition):
    if not condition:
        raise SystemExit(1)


mode = sys.argv[1]
with open(sys.argv[2], encoding="utf-8") as handle:
    result = json.load(handle)

require(
    result.get("task_id")
    == "PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001"
)
for key in (
    "provider_calls",
    "service_changes",
    "public_traffic_requests",
    "secret_values_exposed",
):
    require(result.get(key) == 0)

if mode == "preflight":
    require(result.get("status") == "accepted_risk_observed")
    require(result.get("acceptance") == {
        "session": True,
        "ledger_inventory": True,
        "role_graph": True,
        "xhs_acl": True,
    })
elif mode == "preflight_state_changed":
    require(result.get("status") == "state_changed")
else:
    require(mode in {"apply", "outcome"})

if mode in {"preflight", "preflight_state_changed"}:
    require(result.get("incident_class") == "CONNECTED_KNOWN")
    require(result.get("read_only") is True)
    require(result.get("transaction_rolled_back") is True)
    require(result.get("fixed_query_count") == 4)
    require(result.get("database_connection_count") == 1)
    require(result.get("database_write_count") == 0)
    require(result.get("business_row_values_read") == 0)

if mode == "preflight":
    ledger = result.get("ledger_inventory", {})
    require(ledger.get("ledger_exact") is True)
    require(ledger.get("tables_exact") is True)
    require(ledger.get("sequences_exact") is True)
    require(ledger.get("ledger_count") == 8)
    require(ledger.get("table_count") == 30)
    require(ledger.get("sequence_count") == 5)
    require(ledger.get("ledger_sha_column_count") == 0)
    require(ledger.get("ledger_sha_constraint_count") == 0)
    require(ledger.get("new_runtime_role_count") == 0)
    require(ledger.get("new_table_count") == 0)
    require(ledger.get("retention_backfill_source_count") == 0)
    role = result.get("role_graph", {})
    require(role.get("runtime_role_count") == 2)
    require(role.get("new_runtime_role_count") == 0)
    require(role.get("app_attributes_exact") is True)
    require(role.get("xhs_attributes_exact") is True)
    require(role.get("membership_count") == 1)
    require(role.get("exact_edge_count") == 1)
    require(role.get("membership_admin") is True)
    require(role.get("membership_inherit") is False)
    require(role.get("membership_set") is False)
    require(role.get("app_incoming_membership_count") == 0)
    require(role.get("app_high_privilege_inheritance_count") == 0)
elif mode == "apply":
    require(result.get("status") == "verified")
    require(result.get("transaction_committed") is True)
    require(result.get("applied_versions") == [
        f"{number:04d}" for number in range(9, 17)
    ])
    require(result.get("database_writes", {}) == {
        "migration_ledger_rows": 8,
        "migration_ledger_hash_backfills": 8,
        "schema_seed_rows": 2,
        "retention_backfill_rows": 0,
        "existing_business_row_updates": 0,
    })
    roles = result.get("roles", {})
    require(roles.get("runtime_role_count") == 8)
    require(roles.get("new_roles_login_enabled") == 0)
    require(roles.get("privilege_mismatch_count") == 0)
    require(roles.get("ownership_count") == 0)
    require(roles.get("membership_count") == 7)
    require(roles.get("management_membership_count") == 6)
    require(roles.get("migration_owner_mismatch_count") == 0)
    require(roles.get("executor_owned_object_count") == 0)
    require(roles.get("elevation_count") == 1)
    require(
        roles.get("accepted_risk_profile")
        == "FIRST_LAUNCH_LEGACY_ROLE_RISK_V1"
    )
    require(roles.get("accepted_risk_count") == 2)
    require(roles.get("unexpected_membership_count") == 0)
    require(roles.get("unexpected_elevation_count") == 0)
    require(roles.get("high_privilege_inheritance_count") == 0)
    verification = result.get("verification", {})
    require(verification.get("migration_count") == 16)
    require(verification.get("runtime_role_count") == 8)
    require(verification.get("table_count") == 56)
    require(verification.get("sequence_count") == 5)
    require(verification.get("table_privilege_checks") == 3136)
    require(verification.get("table_grant_option_count") == 0)
    require(verification.get("column_privilege_checks", 0) > 0)
    require(verification.get("column_grant_option_count") == 0)
    require(verification.get("sequence_privilege_checks") == 120)
    require(verification.get("sequence_grant_option_count") == 0)
    require(verification.get("default_acl_entry_count") == 0)
    require(verification.get("schema_seed_rows") == 2)
    require(verification.get("retention_backfill_rows") == 0)
    require(verification.get("accepted_role_risk_count") == 2)
    require(verification.get("accepted_role_attribute_count") == 1)
    require(verification.get("accepted_role_membership_count") == 1)
    require(
        verification.get("runtime_management_membership_count") == 6
    )
    require(verification.get("unexpected_role_attribute_count") == 0)
    require(verification.get("unexpected_role_membership_count") == 0)
    require(
        verification.get("app_high_privilege_inheritance_count") == 0
    )
    require(verification.get("migration_owner_relation_count", 0) > 0)
    require(verification.get("migration_owner_function_count", -1) >= 0)
    require(verification.get("migration_owner_mismatch_count") == 0)
elif mode == "outcome":
    require(result.get("status") == "classified")
    database_outcome = result.get("database_outcome")
    require(database_outcome in {"COMMITTED", "ROLLED_BACK"})
    require(result.get("read_only") is True)
    require(result.get("default_transaction_read_only") is True)
    require(result.get("transaction_read_only") is True)
    observation = result.get("observation", {})
    require(observation.get("business_row_values_read") == 0)
    require(
        observation.get("accepted_role_risk_profile")
        == "FIRST_LAUNCH_LEGACY_ROLE_RISK_V1"
    )
    require(observation.get("accepted_role_risk_exact") is True)
    require(observation.get("app_incoming_membership_count") == 0)
    require(
        observation.get("app_high_privilege_inheritance_count") == 0
    )
    require(observation.get("executor_not_xhs") is True)
    require(observation.get("runtime_ownership_count") == 0)
    require(observation.get("migration_owner_role_exact") is True)
    require(observation.get("migration_owner_database_exact") is True)
    require(observation.get("migration_owner_mismatch_count") == 0)
    require(observation.get("sequence_count") == 5)
    require(observation.get("runtime_elevation_count") == 1)
    require(observation.get("runtime_management_membership_exact") is True)
    if database_outcome == "COMMITTED":
        require(observation.get("ledger_count") == 16)
        require(observation.get("ledger_first") == "0001")
        require(observation.get("ledger_last") == "0016")
        require(observation.get("sha_column_count") == 1)
        require(observation.get("sha_constraint_count") == 1)
        require(observation.get("sha_constraint_exact_count") == 1)
        require(observation.get("matching_migration_hash_count") == 16)
        require(observation.get("canonical_migration_name_count") == 16)
        require(observation.get("table_count") == 56)
        require(observation.get("runtime_role_count") == 8)
        require(observation.get("new_runtime_role_count") == 6)
        require(observation.get("new_runtime_login_count") == 0)
        require(observation.get("runtime_membership_count") == 7)
        require(
            observation.get("runtime_management_membership_count") == 6
        )
        require(observation.get("trends_seed_count") == 1)
        require(observation.get("trends_seed_exact_count") == 1)
        require(observation.get("dispatcher_seed_count") == 1)
        require(observation.get("dispatcher_seed_exact_count") == 1)
        require(observation.get("retention_row_count") == 0)
        require(observation.get("full_contract_matrix_verified") is True)
        require(observation.get("table_privilege_checks") == 3136)
        require(observation.get("table_grant_option_count") == 0)
        require(observation.get("column_privilege_checks", 0) > 0)
        require(observation.get("column_grant_option_count") == 0)
        require(observation.get("sequence_privilege_checks") == 120)
        require(observation.get("sequence_grant_option_count") == 0)
        require(observation.get("default_acl_entry_count") == 0)
    else:
        require(observation.get("ledger_count") == 8)
        require(observation.get("ledger_first") == "0001")
        require(observation.get("ledger_last") == "0008")
        require(observation.get("sha_column_count") == 0)
        require(observation.get("sha_constraint_count") == 0)
        require(observation.get("sha_constraint_exact_count") == 0)
        require(observation.get("matching_migration_hash_count") == 0)
        require(observation.get("canonical_migration_name_count") == 8)
        require(observation.get("table_count") == 30)
        require(observation.get("runtime_role_count") == 2)
        require(observation.get("new_runtime_role_count") == 0)
        require(observation.get("new_runtime_login_count") == 0)
        require(observation.get("runtime_membership_count") == 1)
        require(
            observation.get("runtime_management_membership_count") == 0
        )
        for key in (
            "trends_seed_count",
            "dispatcher_seed_count",
            "retention_row_count",
            "full_contract_matrix_verified",
            "table_privilege_checks",
            "table_grant_option_count",
            "column_privilege_checks",
            "column_grant_option_count",
            "sequence_privilege_checks",
            "sequence_grant_option_count",
            "default_acl_entry_count",
        ):
            require(observation.get(key) is None)
PY
}

result_binding_payload() {
    result_mode="${1}"
    result_file="${2}"
    result_sha_line="$(sha256sum "${result_file}")" || return 1
    result_sha="${result_sha_line%% *}"
    printf '%s %s %s %s\n' \
        "${incident_id}" \
        "${package_manifest_sha}" \
        "${result_mode}" \
        "${result_sha}"
}

write_result_binding() {
    result_mode="${1}"
    result_file="${2}"
    binding_file="${task_root}/${result_mode}-result.binding"
    test ! -e "${binding_file}" || return 1
    result_binding_payload "${result_mode}" "${result_file}" \
        >"${binding_file}" || return 1
    test ! -L "${binding_file}" || return 1
    test "$(stat -c '%u:%g:%a:%h' "${binding_file}")" = "0:0:600:1" \
        || return 1
}

verify_result_binding() {
    result_mode="${1}"
    result_file="${2}"
    binding_file="${task_root}/${result_mode}-result.binding"
    test -f "${binding_file}" || return 1
    test ! -L "${binding_file}" || return 1
    test "$(stat -c '%u:%g:%a:%h' "${binding_file}")" = "0:0:600:1" \
        || return 1
    expected_binding="$(
        result_binding_payload "${result_mode}" "${result_file}"
    )" || return 1
    test "$(cat "${binding_file}")" = "${expected_binding}"
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
incident_binding_line="$(
    printf '%s\n' "${incident_id}:${package_manifest_sha}" | sha256sum
)" || fail_preconnect
incident_binding_sha="${incident_binding_line%% *}"
if test "${mode}" != prepare; then
    test -f "${incident_sentinel}" || fail_preconnect
    test ! -L "${incident_sentinel}" || fail_preconnect
    test "$(stat -c '%u:%g:%a:%h' "${incident_sentinel}")" = \
        "0:0:600:1" || fail_preconnect
    test "$(cat "${incident_sentinel}")" = "${incident_binding_sha}" \
        || fail_preconnect
fi

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
    test ! -e "${incident_sentinel}" || fail_preconnect
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
    printf '%s\n' "${incident_binding_sha}" >"${incident_sentinel}" \
        || fail_preconnect
    test "$(stat -c '%u:%g:%a:%h' "${import_sentinel}")" = "0:0:600:1" \
        || fail_preconnect
    test "$(stat -c '%u:%g:%a:%h' "${incident_sentinel}")" = \
        "0:0:600:1" || fail_preconnect
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V5 mode=prepare incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 import=passed incident_binding=1 cleanup_required=1 automatic_retry=0 ids_printed=0 secrets=0"
    exit 0
fi

test -f "${import_sentinel}" || fail_preconnect
test ! -L "${import_sentinel}" || fail_preconnect
test "$(stat -c '%u:%g:%a:%h' "${import_sentinel}")" = "0:0:600:1" \
    || fail_preconnect
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
    prepared_sentinel="${task_root}/preflight.prepared"
    dispatch_sentinel="${task_root}/preflight.started"
    python_code='import sys; value=sys.stdin.read(); from production_first_launch_role_risk_set_audit import main; code=main(database_url=value); del value; raise SystemExit(code)'
elif test "${mode}" = apply; then
    result_path="${task_root}/apply-result.json"
    result_tmp="${result_path}.tmp"
    prepared_sentinel="${task_root}/apply.prepared"
    dispatch_sentinel="${task_root}/apply.started"
    preflight_result="${task_root}/preflight-result.json"
    test -s "${preflight_result}" || fail_preconnect
    validate_result preflight "${preflight_result}" >/dev/null 2>&1 \
        || fail_preconnect
    verify_result_binding preflight "${preflight_result}" \
        || fail_preconnect
    python_code='import sys; value=sys.stdin.read(); from production_schema_roles import main; code=main(["--apply"],database_url=value,confirmation=sys.argv[1]); del value; raise SystemExit(code)'
else
    result_path="${task_root}/outcome-result.json"
    result_tmp="${result_path}.tmp"
    prepared_sentinel="${task_root}/outcome.prepared"
    dispatch_sentinel="${task_root}/outcome.started"
    test -f "${task_root}/apply.started" || fail_preconnect
    if test -f "${task_root}/apply-result.json"; then
        verify_result_binding apply "${task_root}/apply-result.json" \
            || fail_preconnect
    fi
    python_code='import sys; value=sys.stdin.read(); from production_schema_outcome_audit import main; code=main(database_url=value); del value; raise SystemExit(code)'
fi

decrypt_error_path="${task_root}/${mode}-decrypt-error.log"
task_error_path="${task_root}/${mode}-task-error.log"
result_binding_path="${task_root}/${mode}-result.binding"
test ! -e "${dispatch_sentinel}" || fail_preconnect
test ! -e "${result_path}" || fail_preconnect
test ! -e "${result_binding_path}" || fail_preconnect
rm -f \
    "${result_tmp}" \
    "${decrypt_error_path}" \
    "${task_error_path}" \
    "${prepared_sentinel}" \
    || fail_preconnect
printf 'prepared\n' >"${prepared_sentinel}" || fail_preconnect
printf 'dispatched\n' >"${dispatch_sentinel}" || fail_preconnect

set +e
openssl pkeyutl \
    -decrypt \
    -inkey "${private_key}" \
    -pkeyopt rsa_padding_mode:oaep \
    -pkeyopt rsa_oaep_md:sha256 \
    -in "${ciphertext}" 2>"${decrypt_error_path}" \
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
        >"${result_tmp}" 2>"${task_error_path}"
pipeline_status=("${PIPESTATUS[@]}")

openssl_exit="${pipeline_status[0]:-125}"
task_exit="${pipeline_status[1]:-125}"
decrypt_error_bytes="$(wc -c <"${decrypt_error_path}" | tr -d ' ')" \
    || fail_connected_unknown
task_error_bytes="$(wc -c <"${task_error_path}" | tr -d ' ')" \
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
    && test "${container_count}" = 0 \
    && test "${result_bytes}" = 0 \
    && test "$(wc -l <"${task_error_path}" | tr -d ' ')" = 1; then
    preconnect_error_ok=0
    if test "${mode}" = preflight \
        && grep -Eq \
            '^production_first_launch_role_risk_set_audit=FAIL stage=(local_source|connect) sqlstate=[0-9A-Z]{5} incident_class=PRE_CONNECT database_connected=0 database_outcome=NOT_CONNECTED automatic_retry=0 secrets=0$' \
            "${task_error_path}"; then
        preconnect_error_ok=1
    elif test "${mode}" = apply \
        && grep -Fxq \
            'production_schema_roles=FAIL code=confirmation_missing' \
            "${task_error_path}"; then
        preconnect_error_ok=1
    elif test "${mode}" = outcome \
        && grep -Eq \
            '^production_schema_outcome_audit=FAIL stage=[a-z_]+ incident_class=PRE_CONNECT database_connected=0 connection_attempted=0 database_outcome=NOT_CONNECTED retry_same_path=0$' \
            "${task_error_path}"; then
        preconnect_error_ok=1
    fi
    if test "${preconnect_error_ok}" = 1; then
        rm -f "${result_tmp}" || true
        fail_preconnect
    fi
fi

if test "${mode}" = preflight \
    && test "${openssl_exit}" = 0 \
    && test "${task_exit}" = 0 \
    && test "${decrypt_error_bytes}" = 0 \
    && test "${task_error_bytes}" = 0 \
    && test "${result_bytes}" -gt 0 \
    && validate_result preflight "${result_tmp}" >/dev/null 2>&1; then
    test "${container_count}" = 0 || fail_connected_unknown
    result_sha_line="$(sha256sum "${result_tmp}")" \
        || fail_connected_unknown
    result_sha256="${result_sha_line%% *}"
    mv "${result_tmp}" "${result_path}" || fail_connected_unknown
    write_result_binding preflight "${result_path}" \
        || fail_connected_known READ_ONLY_VERIFIED 0
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V5 mode=preflight incident_class=CONNECTED_KNOWN database_outcome=READ_ONLY_VERIFIED database_connection=1 audit_transaction=rolled_back database_write=0 result_bytes=${result_bytes} result_sha256=${result_sha256} decrypt_error_bytes=0 task_error_bytes=0 container=0 incident_binding=1 result_binding=1 cleanup_required=1 automatic_retry=0 ids_printed=0 secrets=0"
    exit 0
fi

if test "${mode}" = apply \
    && test "${openssl_exit}" = 0 \
    && test "${task_exit}" = 0 \
    && test "${decrypt_error_bytes}" = 0 \
    && test "${task_error_bytes}" = 0 \
    && test "${result_bytes}" -gt 0 \
    && validate_result apply "${result_tmp}" >/dev/null 2>&1; then
    test "${container_count}" = 0 \
        || fail_connected_known COMMITTED 18
    result_sha_line="$(sha256sum "${result_tmp}")" \
        || fail_connected_known COMMITTED 18
    result_sha256="${result_sha_line%% *}"
    mv "${result_tmp}" "${result_path}" \
        || fail_connected_known COMMITTED 18
    write_result_binding apply "${result_path}" \
        || fail_connected_known COMMITTED 18
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V5 mode=apply incident_class=CONNECTED_KNOWN database_connection=1 database_outcome=COMMITTED apply_transaction=committed database_write=18 result_bytes=${result_bytes} result_sha256=${result_sha256} decrypt_error_bytes=0 task_error_bytes=0 container=0 incident_binding=1 result_binding=1 cleanup_required=1 automatic_retry=0 ids_printed=0 secrets=0"
    exit 0
fi

if test "${mode}" = outcome \
    && test "${openssl_exit}" = 0 \
    && test "${task_exit}" = 0 \
    && test "${decrypt_error_bytes}" = 0 \
    && test "${task_error_bytes}" = 0 \
    && test "${result_bytes}" -gt 0 \
    && validate_result outcome "${result_tmp}" >/dev/null 2>&1; then
    test "${container_count}" = 0 || fail_connected_unknown
    database_outcome="$(
        python3 -I -c \
            'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["database_outcome"])' \
            "${result_tmp}"
    )" || fail_connected_unknown
    result_sha_line="$(sha256sum "${result_tmp}")" \
        || fail_connected_unknown
    result_sha256="${result_sha_line%% *}"
    mv "${result_tmp}" "${result_path}" || fail_connected_unknown
    observed_writes=0
    test "${database_outcome}" = COMMITTED && observed_writes=18
    write_result_binding outcome "${result_path}" \
        || fail_connected_known "${database_outcome}" "${observed_writes}"
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V5 mode=outcome incident_class=CONNECTED_KNOWN database_connection=1 database_outcome=${database_outcome} audit_transaction=rolled_back database_write=${observed_writes} result_bytes=${result_bytes} result_sha256=${result_sha256} decrypt_error_bytes=0 task_error_bytes=0 container=0 incident_binding=1 result_binding=1 cleanup_required=1 automatic_retry=0 ids_printed=0 secrets=0"
    exit 0
fi

if test "${mode}" = preflight \
    && test "${openssl_exit}" = 0 \
    && test "${task_exit}" = 30 \
    && test "${decrypt_error_bytes}" = 0 \
    && test "${task_error_bytes}" = 0 \
    && test "${result_bytes}" -gt 0 \
    && validate_result preflight_state_changed \
        "${result_tmp}" >/dev/null 2>&1 \
    && test "${container_count}" = 0; then
    result_sha_line="$(sha256sum "${result_tmp}")" \
        || fail_connected_known READ_ONLY_STATE_CHANGED 0
    result_sha256="${result_sha_line%% *}"
    mv "${result_tmp}" "${result_path}" \
        || fail_connected_known READ_ONLY_STATE_CHANGED 0
    write_result_binding preflight "${result_path}" \
        || fail_connected_known READ_ONLY_STATE_CHANGED 0
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V5 mode=preflight incident_class=CONNECTED_KNOWN database_outcome=READ_ONLY_STATE_CHANGED database_connection=1 audit_transaction=rolled_back database_write=0 result_bytes=${result_bytes} result_sha256=${result_sha256} decrypt_error_bytes=0 task_error_bytes=0 container=0 incident_binding=1 result_binding=1 cleanup_required=1 automatic_retry=0 ids_printed=0 secrets=0"
    exit 30
fi

if test "${mode}" = preflight \
    && test "${openssl_exit}" = 0 \
    && test "${task_exit}" = 31 \
    && test "${decrypt_error_bytes}" = 0 \
    && test "${result_bytes}" = 0 \
    && test "${task_error_bytes}" -gt 0 \
    && test "$(wc -l <"${task_error_path}" | tr -d ' ')" = 1 \
    && grep -Eq \
        '^production_first_launch_role_risk_set_audit=FAIL stage=(session|ledger_inventory|role_graph|xhs_acl|rollback) sqlstate=[0-9A-Z]{5} incident_class=CONNECTED_KNOWN database_connected=1 database_outcome=KNOWN_READ_ONLY_FAILURE automatic_retry=0 secrets=0$' \
        "${task_error_path}" \
    && test "${container_count}" = 0; then
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V5 mode=preflight incident_class=CONNECTED_KNOWN database_outcome=READ_ONLY_REJECTED database_connection=1 audit_transaction=rolled_back database_write=0 result_bytes=0 decrypt_error_bytes=0 task_error_lines=1 container=0 incident_binding=1 cleanup_required=1 automatic_retry=0 ids_printed=0 secrets=0"
    exit 30
fi

fail_connected_unknown
