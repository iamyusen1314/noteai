#!/usr/bin/env bash
set -u
set -o pipefail

mode="${1:-}"
task_root=/var/lib/noteai/schema-privileged-owner-preflight-v2
source_root="${task_root}/source"
admin_env=/etc/noteai/admin.env
private_key="${task_root}/transport_private.pem"
ciphertext="${task_root}/task_password.enc"
import_sentinel="${task_root}/import.passed"
result_path="${task_root}/result.json"
result_tmp="${result_path}.tmp"
decrypt_error_path="${task_root}/decrypt-error.log"
audit_error_path="${task_root}/audit-error.log"
prepared_sentinel="${task_root}/audit.prepared"
dispatch_sentinel="${task_root}/audit.started"
container_name=noteai-schema-privileged-owner-audit-once
import_container_name=noteai-schema-privileged-owner-import-once
auditor_sha256=091a96673f0391cf5196c4a2492702b6438ec49d462a47da19177dd15379c851
base_auditor_sha256=449f2583daea5ea9cbe47b5a8dd0aa87fb3944ea80e83806248f226206974917

fail_preconnect() {
    printf '%s\n' \
        "SAFE_PRIVILEGED_OWNER_PREFLIGHT mode=${mode} incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 cleanup_required=1 retry_same_path=0 ids_printed=0 secrets=0"
    exit 2
}

fail_connected_unknown() {
    printf '%s\n' \
        "SAFE_PRIVILEGED_OWNER_PREFLIGHT mode=${mode} incident_class=CONNECTED_UNKNOWN database_connection=unknown transaction=unknown database_write=unknown cleanup_required=1 container_count=${container_count:-unknown} automatic_retry=0 ids_printed=0 secrets=0"
    exit 1
}

fail_connected_known() {
    printf '%s\n' \
        "SAFE_PRIVILEGED_OWNER_PREFLIGHT mode=${mode} incident_class=CONNECTED_KNOWN database_connection=1 database_outcome=KNOWN_READ_ONLY_FAILURE audit_transaction=rolled_back database_write=0 cleanup_required=1 automatic_retry=0 ids_printed=0 secrets=0"
    exit 31
}

case "${mode}" in
    prepare | audit) ;;
    *) fail_preconnect ;;
esac
case "${task_root}" in
    /var/lib/noteai/schema-privileged-owner-preflight-v2) ;;
    *) fail_preconnect ;;
esac

test -d "${task_root}" || fail_preconnect
test ! -L "${task_root}" || fail_preconnect
test "$(stat -c '%U:%G:%a' "${task_root}")" = "root:root:700" \
    || fail_preconnect
test -d "${source_root}" || fail_preconnect
test ! -L "${source_root}" || fail_preconnect
test "$(stat -c '%U:%G:%a' "${source_root}")" = "root:root:755" \
    || fail_preconnect
test -f "${source_root}/package.sha256" || fail_preconnect
test -f \
    "${source_root}/tools/production_schema_privileged_owner_preflight.py" \
    || fail_preconnect
test -f \
    "${source_root}/tools/production_schema_owner_authority_preflight.py" \
    || fail_preconnect
observed_auditor_line="$(
    sha256sum \
        "${source_root}/tools/production_schema_privileged_owner_preflight.py"
)" || fail_preconnect
observed_auditor_sha="${observed_auditor_line%% *}"
test "${observed_auditor_sha}" = "${auditor_sha256}" || fail_preconnect
observed_base_line="$(
    sha256sum \
        "${source_root}/tools/production_schema_owner_authority_preflight.py"
)" || fail_preconnect
observed_base_sha="${observed_base_line%% *}"
test "${observed_base_sha}" = "${base_auditor_sha256}" || fail_preconnect
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
        -c 'import production_schema_privileged_owner_preflight' \
        >/dev/null 2>&1 \
        || fail_preconnect
    printf '%s\n' "${package_manifest_sha}" >"${import_sentinel}" \
        || fail_preconnect
    printf '%s\n' \
        "SAFE_PRIVILEGED_OWNER_PREFLIGHT mode=prepare incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 import=passed cleanup_required=1 automatic_retry=0 ids_printed=0 secrets=0"
    exit 0
fi

test -f "${import_sentinel}" || fail_preconnect
observed_import_sha="$(tr -d '\n' <"${import_sentinel}")" \
    || fail_preconnect
test "${observed_import_sha}" = "${package_manifest_sha}" \
    || fail_preconnect
test -f "${admin_env}" || fail_preconnect
test ! -L "${admin_env}" || fail_preconnect
test "$(stat -c '%U:%G:%a' "${admin_env}")" = "root:root:600" \
    || fail_preconnect
database_url_count="$(
    awk 'index($0,"DATABASE_URL=")==1 { count += 1 } END { print count+0 }' \
        "${admin_env}"
)" || fail_preconnect
test "${database_url_count}" = 1 || fail_preconnect
database_url_bytes="$(
    awk 'index($0,"DATABASE_URL=")==1 { print substr($0,14) }' \
        "${admin_env}" \
        | wc -c \
        | tr -d ' '
)" || fail_preconnect
test "${database_url_bytes}" -gt 1 || fail_preconnect
test "${database_url_bytes}" -le 2049 || fail_preconnect
database_url_scheme_count="$(
    awk '
        index($0,"DATABASE_URL=")==1 {
            value=substr($0,14)
            if (value ~ /^postgres(ql)?:\/\//) count += 1
        }
        END { print count+0 }
    ' "${admin_env}"
)" || fail_preconnect
test "${database_url_scheme_count}" = 1 || fail_preconnect
test -f "${private_key}" || fail_preconnect
test ! -L "${private_key}" || fail_preconnect
test -f "${ciphertext}" || fail_preconnect
test ! -L "${ciphertext}" || fail_preconnect
test "$(stat -c '%U:%G:%a' "${private_key}")" = "root:root:600" \
    || fail_preconnect
test "$(stat -c '%U:%G:%a' "${ciphertext}")" = "root:root:600" \
    || fail_preconnect
test "$(stat -c '%h' "${private_key}")" = 1 || fail_preconnect
test "$(stat -c '%h' "${ciphertext}")" = 1 || fail_preconnect
cipher_bytes="$(wc -c <"${ciphertext}" | tr -d ' ')" || fail_preconnect
test "${cipher_bytes}" = 384 || fail_preconnect
openssl pkey -in "${private_key}" -check -noout >/dev/null 2>&1 \
    || fail_preconnect
test ! -e "${dispatch_sentinel}" || fail_preconnect
test ! -e "${result_path}" || fail_preconnect
rm -f \
    "${result_tmp}" \
    "${decrypt_error_path}" \
    "${audit_error_path}" \
    "${prepared_sentinel}" \
    || fail_preconnect
printf 'prepared\n' >"${prepared_sentinel}" || fail_preconnect
printf 'dispatched\n' >"${dispatch_sentinel}" || fail_preconnect

sanitize_admin_topology() {
    awk \
        'index($0,"DATABASE_URL=")==1 { printf "%s", substr($0,14) }' \
        "${admin_env}" \
        | (
            cd "${source_root}" || exit 2
            PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="${source_root}/tools" python3 -c 'import sys; value=sys.stdin.read(); from production_schema_privileged_owner_preflight import sanitize_admin_topology_from_protected_input; code=sanitize_admin_topology_from_protected_input(value); del value; raise SystemExit(code)'
        )
}

validate_result() {
    python3 -c 'import json,sys; result=json.load(open(sys.argv[1],encoding="utf-8")); expected="privileged_owner_authority_verified" if sys.argv[2]=="0" else "state_changed"; session=result.get("session",{}); assert result.get("task_id")=="PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-PRIVILEGED-OWNER-PREFLIGHT-005"; assert result.get("predecessor_disposition")=="no_retry" and result.get("same_database_action_retry") is False; assert result.get("status")==expected and result.get("incident_class")=="CONNECTED_KNOWN"; assert result.get("fixed_query_count")==3 and result.get("owner_activation_command_count")==1; assert result.get("transaction_rolled_back") is True and result.get("database_write_count")==0; assert session.get("executor_non_superuser") is True and session.get("executor_rds_privileged") is True; assert session.get("direct_managed_privileged_membership_count")==1; assert session.get("unexpected_direct_membership_count")==0; assert session.get("direct_owner_membership_count")==0; assert session.get("direct_owner_set_membership_count")==0' \
        "${1}" "${2}" >/dev/null 2>&1
}

set +e
{
    sanitize_admin_topology 2>"${decrypt_error_path}" || exit 120
    printf '\0'
    openssl pkeyutl \
        -decrypt \
        -inkey "${private_key}" \
        -pkeyopt rsa_padding_mode:oaep \
        -pkeyopt rsa_oaep_md:sha256 \
        -in "${ciphertext}" 2>>"${decrypt_error_path}"
} | docker run \
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
        -c 'import sys; payload=sys.stdin.buffer.read(); from production_schema_privileged_owner_preflight import main_from_protected_input; code=main_from_protected_input(payload); del payload; raise SystemExit(code)' \
        >"${result_tmp}" 2>"${audit_error_path}"
pipeline_status=("${PIPESTATUS[@]}")

protected_input_exit="${pipeline_status[0]:-125}"
audit_exit="${pipeline_status[1]:-125}"
decrypt_error_bytes="$(wc -c <"${decrypt_error_path}" | tr -d ' ')" \
    || fail_connected_unknown
audit_error_bytes="$(wc -c <"${audit_error_path}" | tr -d ' ')" \
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

if { test "${audit_exit}" = 126 || test "${audit_exit}" = 127; } \
    && test "${container_count}" = 0 \
    && test "${result_bytes}" = 0; then
    fail_preconnect
fi

if test "${audit_exit}" = 2 \
    && grep -Fq 'incident_class=PRE_CONNECT' "${audit_error_path}" \
    && test "${container_count}" = 0; then
    rm -f "${result_tmp}" || true
    fail_preconnect
fi

if test "${protected_input_exit}" = 0 \
    && { test "${audit_exit}" = 0 || test "${audit_exit}" = 30; } \
    && test "${result_bytes}" -gt 0 \
    && test "${decrypt_error_bytes}" = 0 \
    && test "${audit_error_bytes}" = 0 \
    && validate_result "${result_tmp}" "${audit_exit}"; then
    test "${container_count}" = 0 || fail_connected_unknown
    result_sha_line="$(sha256sum "${result_tmp}")" \
        || fail_connected_unknown
    result_sha256="${result_sha_line%% *}"
    mv "${result_tmp}" "${result_path}" || fail_connected_unknown
    printf '%s\n' \
        "SAFE_PRIVILEGED_OWNER_PREFLIGHT mode=audit incident_class=CONNECTED_KNOWN audit_exit=${audit_exit} database_connection=1 database_outcome=READ_ONLY_CLASSIFIED audit_transaction=rolled_back database_write=0 result_bytes=${result_bytes} result_sha256=${result_sha256} decrypt_error_bytes=0 audit_error_bytes=0 container=0 cleanup_required=1 automatic_retry=0 ids_printed=0 secrets=0"
    exit "${audit_exit}"
fi

known_error_line_count="$(
    wc -l <"${audit_error_path}" | tr -d ' '
)" || fail_connected_unknown
if test "${protected_input_exit}" = 0 \
    && test "${audit_exit}" = 31 \
    && test "${result_bytes}" = 0 \
    && test "${decrypt_error_bytes}" = 0 \
    && test "${known_error_line_count}" = 1 \
    && grep -Eq \
        '^production_schema_privileged_owner_preflight=FAIL stage=(session|migration_owner_activation|owner_contract|production_state) sqlstate=[0-9A-Z]{5} incident_class=CONNECTED_KNOWN database_connected=1 database_outcome=KNOWN_READ_ONLY_FAILURE automatic_retry=0 secrets=0$' \
        "${audit_error_path}" \
    && test "${container_count}" = 0; then
    fail_connected_known
fi

fail_connected_unknown
