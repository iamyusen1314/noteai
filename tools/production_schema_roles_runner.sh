#!/usr/bin/env bash
set -u
set -o pipefail

mode="${1:-}"
task_root=/var/lib/noteai/schema-roles-v4
source_root="${task_root}/source"
private_key="${task_root}/transport_private.pem"
ciphertext="${task_root}/database_url.enc"
import_sentinel="${task_root}/import.passed"
container_name="noteai-schema-roles-v4-${mode}-once"
import_container_name=noteai-schema-roles-v4-import-once
executor_sha256=610003288b9a4cbdc7f23fc7a58707c209be5f3bd59bb340881f490a5e691902
outcome_sha256=49cab9279005c21792b0f83753cafbf27b982edae44dba767086634490383aa7
preflight_sha256=2d873101db846689be20d8fee2d4adb21017fe51c54cc4ebfaffd54e58d3ad17
confirmation=PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001

fail_preconnect() {
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V4 mode=${mode} incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 retry_same_path=0 ids_printed=0 secrets=0"
    exit 2
}

fail_connected_unknown() {
    cleanup_required=unknown
    case "${container_count:-unknown}" in
        0) cleanup_required=0 ;;
        unknown) ;;
        *) cleanup_required=1 ;;
    esac
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V4 mode=${mode} incident_class=CONNECTED_UNKNOWN database_connection=unknown transaction=unknown database_write=unknown cleanup_required=${cleanup_required} automatic_retry=0 ids_printed=0 secrets=0"
    exit 1
}

fail_connected_known() {
    outcome="${1:-RECOVERY_REQUIRED}"
    known_write_count="${2:-0}"
    cleanup_required="${3:-0}"
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V4 mode=${mode} incident_class=CONNECTED_KNOWN database_connection=1 database_outcome=${outcome} database_write=${known_write_count} cleanup_required=${cleanup_required} automatic_retry=0 ids_printed=0 secrets=0"
    exit 30
}

case "${mode}" in
    prepare | preflight | apply | outcome) ;;
    *) fail_preconnect ;;
esac
case "${task_root}" in
    /var/lib/noteai/schema-roles-v4) ;;
    *) fail_preconnect ;;
esac

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
        -v "${source_root}:/task:ro" \
        -w /task \
        --entrypoint python \
        "${image_id}" \
        -c 'import tools.production_schema_roles; import tools.production_schema_outcome_audit; import tools.production_first_launch_role_risk_set_audit' \
        >/dev/null 2>&1 \
        || fail_preconnect
    printf '%s\n' "${package_manifest_sha}" >"${import_sentinel}" \
        || fail_preconnect
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V4 mode=prepare incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 import=passed automatic_retry=0 ids_printed=0 secrets=0"
    exit 0
fi

test -f "${import_sentinel}" || fail_preconnect
observed_import_sha="$(tr -d '\n' <"${import_sentinel}")" \
    || fail_preconnect
test "${observed_import_sha}" = "${package_manifest_sha}" \
    || fail_preconnect
test -f "${private_key}" || fail_preconnect
test -f "${ciphertext}" || fail_preconnect
test "$(stat -c '%a' "${private_key}")" = 600 || fail_preconnect
test "$(stat -c '%a' "${ciphertext}")" = 600 || fail_preconnect
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
    python_code='import sys; value=sys.stdin.read(); from tools.production_first_launch_role_risk_set_audit import main; code=main(database_url=value); del value; raise SystemExit(code)'
elif test "${mode}" = apply; then
    result_path="${task_root}/apply-result.json"
    result_tmp="${result_path}.tmp"
    error_path="${task_root}/apply-error.log"
    prepared_sentinel="${task_root}/apply.prepared"
    dispatch_sentinel="${task_root}/apply.started"
    preflight_result="${task_root}/preflight-result.json"
    test -s "${preflight_result}" || fail_preconnect
    grep -Fq '"status":"accepted_risk_observed"' "${preflight_result}" \
        || fail_preconnect
    grep -Fq '"ledger_count":8' "${preflight_result}" \
        || fail_preconnect
    grep -Fq '"table_count":30' "${preflight_result}" \
        || fail_preconnect
    grep -Fq '"sequence_count":5' "${preflight_result}" \
        || fail_preconnect
    grep -Fq '"retention_backfill_source_count":0' "${preflight_result}" \
        || fail_preconnect
    grep -Fq '"membership_count":1' "${preflight_result}" \
        || fail_preconnect
    grep -Fq '"membership_inherit":false' "${preflight_result}" \
        || fail_preconnect
    grep -Fq \
        '"app_high_privilege_inheritance_count":0' \
        "${preflight_result}" \
        || fail_preconnect
    python_code='import sys; value=sys.stdin.read(); from tools.production_schema_roles import main; code=main(["--apply"],database_url=value,confirmation=sys.argv[1]); del value; raise SystemExit(code)'
else
    result_path="${task_root}/outcome-result.json"
    result_tmp="${result_path}.tmp"
    error_path="${task_root}/outcome-error.log"
    prepared_sentinel="${task_root}/outcome.prepared"
    dispatch_sentinel="${task_root}/outcome.started"
    test -f "${task_root}/apply.started" || fail_preconnect
    python_code='import sys; value=sys.stdin.read(); from tools.production_schema_outcome_audit import main; code=main(database_url=value); del value; raise SystemExit(code)'
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
    && grep -Fq '"status":"accepted_risk_observed"' "${result_tmp}" \
    && grep -Fq '"incident_class":"CONNECTED_KNOWN"' "${result_tmp}" \
    && grep -Fq '"fixed_query_count":4' "${result_tmp}" \
    && grep -Fq '"transaction_rolled_back":true' "${result_tmp}"; then
    test "${container_count}" = 0 || fail_connected_unknown
    result_sha_line="$(sha256sum "${result_tmp}")" \
        || fail_connected_unknown
    result_sha256="${result_sha_line%% *}"
    mv "${result_tmp}" "${result_path}" || fail_connected_unknown
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V4 mode=preflight incident_class=CONNECTED_KNOWN database_connection=1 transaction=rolled_back database_write=0 result_bytes=${result_bytes} result_sha256=${result_sha256} error_bytes=${error_bytes} container=0 automatic_retry=0 ids_printed=0 secrets=0"
    exit 0
fi

if test "${mode}" = apply \
    && test "${openssl_exit}" = 0 \
    && test "${task_exit}" = 0 \
    && test "${result_bytes}" -gt 0 \
    && grep -Fq '"status":"verified"' "${result_tmp}" \
    && grep -Fq '"transaction_committed":true' "${result_tmp}" \
    && grep -Fq '"migration_ledger_hash_backfills":8' "${result_tmp}" \
    && grep -Fq '"migration_ledger_rows":8' "${result_tmp}" \
    && grep -Fq '"schema_seed_rows":2' "${result_tmp}" \
    && grep -Fq '"retention_backfill_rows":0' "${result_tmp}" \
    && grep -Fq '"existing_business_row_updates":0' "${result_tmp}"; then
    test "${container_count}" = 0 \
        || fail_connected_known COMMITTED 18 1
    result_sha_line="$(sha256sum "${result_tmp}")" \
        || fail_connected_known COMMITTED 18 0
    result_sha256="${result_sha_line%% *}"
    mv "${result_tmp}" "${result_path}" \
        || fail_connected_known COMMITTED 18 0
    printf '%s\n' \
        "SAFE_SCHEMA_ROLES_V4 mode=apply incident_class=CONNECTED_KNOWN database_connection=1 database_outcome=COMMITTED transaction=1 database_write=18 result_bytes=${result_bytes} result_sha256=${result_sha256} error_bytes=${error_bytes} container=0 automatic_retry=0 ids_printed=0 secrets=0"
    exit 0
fi

if test "${mode}" = outcome \
    && test "${openssl_exit}" = 0 \
    && test "${task_exit}" = 0 \
    && test "${result_bytes}" -gt 0 \
    && grep -Fq '"status":"classified"' "${result_tmp}" \
    && grep -Eq '"database_outcome":"(COMMITTED|ROLLED_BACK)"' \
        "${result_tmp}"; then
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
        "SAFE_SCHEMA_ROLES_V4 mode=outcome incident_class=CONNECTED_KNOWN database_connection=1 database_outcome=${database_outcome} transaction=rolled_back database_write=${observed_writes} result_bytes=${result_bytes} result_sha256=${result_sha256} error_bytes=${error_bytes} container=0 automatic_retry=0 ids_printed=0 secrets=0"
    exit 0
fi

if test "${mode}" = preflight \
    && { test "${task_exit}" = 30 || test "${task_exit}" = 31; } \
    && test "${container_count}" = 0; then
    fail_connected_known READ_ONLY_REJECTED 0 0
fi

fail_connected_unknown
