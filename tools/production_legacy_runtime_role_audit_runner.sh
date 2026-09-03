#!/usr/bin/env bash
set -u
set -o pipefail

task_root=/var/lib/noteai/legacy-role-audit
source_root="${task_root}/source"
private_key="${task_root}/transport_private.pem"
ciphertext="${task_root}/database_url.enc"
result_path="${task_root}/identity-result.json"
result_tmp="${result_path}.tmp"
error_path="${task_root}/identity-error.log"
prepared_sentinel="${task_root}/runner.prepared"
dispatch_sentinel="${task_root}/dispatch.started"
container_name=noteai-legacy-role-audit-once
auditor_sha256=195e5ff1cfec1d3a143ada91dd661663fd040ea9acf5f3a656f856a7ec2b8ab9

fail_preconnect() {
    printf '%s\n' \
        "SAFE_IDENTITY_RUN incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 retry_same_path=0 ids_printed=0 secrets=0"
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
        "SAFE_IDENTITY_RUN incident_class=CONNECTED_UNKNOWN database_connection=unknown transaction=unknown database_write=unknown cleanup_required=${cleanup_required} automatic_retry=0 ids_printed=0 secrets=0"
    exit 1
}

fail_connected_known() {
    result_recovery_required="${1:-1}"
    cleanup_required="${2:-0}"
    printf '%s\n' \
        "SAFE_IDENTITY_RUN incident_class=CONNECTED_KNOWN database_connection=1 transaction=1 database_write=0 database_outcome=READ_ONLY_COMPLETED result_recovery_required=${result_recovery_required} cleanup_required=${cleanup_required} automatic_retry=0 ids_printed=0 secrets=0"
    exit 30
}

case "${task_root}" in
    /var/lib/noteai/legacy-role-audit) ;;
    *) fail_preconnect ;;
esac

test -f "${source_root}/package.sha256" || fail_preconnect
test -f "${source_root}/tools/production_legacy_runtime_role_audit.py" \
    || fail_preconnect
test -f "${private_key}" || fail_preconnect
test -f "${ciphertext}" || fail_preconnect
cipher_bytes="$(wc -c <"${ciphertext}" | tr -d ' ')" || fail_preconnect
test "${cipher_bytes}" = 384 || fail_preconnect
observed_auditor_line="$(
    sha256sum "${source_root}/tools/production_legacy_runtime_role_audit.py"
)" || fail_preconnect
observed_auditor_sha="${observed_auditor_line%% *}"
test "${observed_auditor_sha}" = "${auditor_sha256}" || fail_preconnect
(cd "${source_root}" && sha256sum -c package.sha256 >/dev/null 2>&1) \
    || fail_preconnect
openssl pkey -in "${private_key}" -check -noout >/dev/null 2>&1 \
    || fail_preconnect

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
test ! -e "${dispatch_sentinel}" || fail_preconnect
test ! -e "${result_path}" || fail_preconnect

rm -f \
    "${result_tmp}" \
    "${error_path}" \
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
        -v "${source_root}:/audit:ro" \
        -w /audit \
        --entrypoint python \
        "${image_id}" \
        -c 'import sys; value=sys.stdin.read(); from tools.production_legacy_runtime_role_audit import main; code=main(database_url=value); del value; raise SystemExit(code)' \
        >"${result_tmp}" 2>>"${error_path}"
pipeline_status=("${PIPESTATUS[@]}")

openssl_exit="${pipeline_status[0]:-125}"
audit_exit="${pipeline_status[1]:-125}"
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

if { test "${audit_exit}" = 126 || test "${audit_exit}" = 127; } \
    && test "${container_count}" = 0 \
    && test "${result_bytes}" = 0; then
    printf '%s\n' \
        "SAFE_IDENTITY_RUN incident_class=PRE_CONNECT openssl_exit=${openssl_exit} audit_exit=${audit_exit} database_connection=0 transaction=0 database_write=0 result_bytes=0 error_bytes=${error_bytes} container=0 retry_same_path=0 ids_printed=0 secrets=0"
    exit 2
fi

if test "${audit_exit}" = 2 \
    && grep -Fq 'production_legacy_runtime_role_audit=FAIL' \
        "${error_path}" \
    && grep -Fq \
        'incident_class=PRE_CONNECT database_connected=0 connection_attempted=0 database_outcome=NOT_CONNECTED' \
        "${error_path}"; then
    rm -f "${result_tmp}" || true
    if test "${container_count}" != 0; then
        printf '%s\n' \
            "SAFE_IDENTITY_RUN incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 container=${container_count} cleanup_required=1 retry_same_path=0 ids_printed=0 secrets=0"
        exit 2
    fi
    printf '%s\n' \
        "SAFE_IDENTITY_RUN incident_class=PRE_CONNECT openssl_exit=${openssl_exit} audit_exit=${audit_exit} database_connection=0 transaction=0 database_write=0 result_bytes=${result_bytes} error_bytes=${error_bytes} container=${container_count} retry_same_path=0 ids_printed=0 secrets=0"
    exit 2
fi

if test "${openssl_exit}" = 0 \
    && { test "${audit_exit}" = 0 || test "${audit_exit}" = 30; } \
    && test "${result_bytes}" -gt 0 \
    && grep -Eq '"status":"(identified|state_changed)"' "${result_tmp}" \
    && grep -Fq '"incident_class":"CONNECTED_KNOWN"' "${result_tmp}"; then
    test "${container_count}" = 0 || fail_connected_known 1 1
    result_sha_line="$(sha256sum "${result_tmp}")" \
        || fail_connected_known 1 0
    result_sha256="${result_sha_line%% *}"
    test "${#result_sha256}" = 64 || fail_connected_known 1 0
    case "${result_sha256}" in
        *[!0-9a-f]*) fail_connected_known 1 0 ;;
    esac
    mv "${result_tmp}" "${result_path}" || fail_connected_known 1 0
    printf '%s\n' \
        "SAFE_IDENTITY_RUN incident_class=CONNECTED_KNOWN openssl_exit=${openssl_exit} audit_exit=${audit_exit} database_connection=1 transaction=1 database_write=0 result_bytes=${result_bytes} result_sha256=${result_sha256} error_bytes=${error_bytes} container=${container_count} automatic_retry=0 ids_printed=0 secrets=0"
    exit "${audit_exit}"
fi

fail_connected_unknown
