#!/usr/bin/env bash
set -u
set -o pipefail

mode="${1:-}"
task_root=/var/lib/noteai/legacy-role-correction
source_root="${task_root}/source"
private_key="${task_root}/transport_private.pem"
ciphertext="${task_root}/database_url.enc"
container_name=noteai-legacy-role-correction-once
corrector_sha256=73db08c9acc021adcc93803196503f5fbe3f04390fe83c690f9e326338a3f4ed
confirmation=PROD-FIRST-LAUNCH-LEGACY-RUNTIME-ROLE-CORRECTION-001

fail_preconnect() {
    printf '%s\n' \
        "SAFE_ROLE_CORRECTION_RUN mode=${mode} incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 retry_same_path=0 ids_printed=0 secrets=0"
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
        "SAFE_ROLE_CORRECTION_RUN mode=${mode} incident_class=CONNECTED_UNKNOWN database_connection=unknown transaction=unknown database_write=unknown cleanup_required=${cleanup_required} automatic_retry=0 ids_printed=0 secrets=0"
    exit 1
}

fail_connected_known() {
    outcome="${1:-RECOVERY_REQUIRED}"
    known_write_count="${2:-unknown}"
    result_recovery_required="${3:-0}"
    cleanup_required="${4:-0}"
    printf '%s\n' \
        "SAFE_ROLE_CORRECTION_RUN mode=${mode} incident_class=CONNECTED_KNOWN database_connection=1 database_outcome=${outcome} database_write=${known_write_count} result_recovery_required=${result_recovery_required} cleanup_required=${cleanup_required} automatic_retry=0 ids_printed=0 secrets=0"
    exit 30
}

case "${mode}" in
    preflight | apply) ;;
    *) fail_preconnect ;;
esac
case "${task_root}" in
    /var/lib/noteai/legacy-role-correction) ;;
    *) fail_preconnect ;;
esac

test -f "${source_root}/package.sha256" || fail_preconnect
test -f \
    "${source_root}/tools/production_legacy_runtime_role_correction.py" \
    || fail_preconnect
test -f "${private_key}" || fail_preconnect
test -f "${ciphertext}" || fail_preconnect
cipher_bytes="$(wc -c <"${ciphertext}" | tr -d ' ')" || fail_preconnect
test "${cipher_bytes}" = 384 || fail_preconnect
observed_corrector_line="$(
    sha256sum \
        "${source_root}/tools/production_legacy_runtime_role_correction.py"
)" || fail_preconnect
observed_corrector_sha="${observed_corrector_line%% *}"
test "${observed_corrector_sha}" = "${corrector_sha256}" \
    || fail_preconnect
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

if test "${mode}" = preflight; then
    result_path="${task_root}/preflight-result.json"
    result_tmp="${result_path}.tmp"
    error_path="${task_root}/preflight-error.log"
    prepared_sentinel="${task_root}/preflight.prepared"
    dispatch_sentinel="${task_root}/preflight.started"
    test ! -e "${dispatch_sentinel}" || fail_preconnect
    test ! -e "${result_path}" || fail_preconnect
    python_args='["--preflight"]'
    confirmation_value=
    expected_status=ready
else
    result_path="${task_root}/apply-result.json"
    result_tmp="${result_path}.tmp"
    error_path="${task_root}/apply-error.log"
    prepared_sentinel="${task_root}/apply.prepared"
    dispatch_sentinel="${task_root}/apply.started"
    preflight_result="${task_root}/preflight-result.json"
    test -s "${preflight_result}" || fail_preconnect
    grep -Fq '"status":"ready"' "${preflight_result}" || fail_preconnect
    grep -Fq '"alter_capability_proven":true' "${preflight_result}" \
        || fail_preconnect
    grep -Fq '"revoke_capability_proven":true' "${preflight_result}" \
        || fail_preconnect
    grep -Fq '"elevated_attribute_count":1' "${preflight_result}" \
        || fail_preconnect
    grep -Fq '"bidirectional_membership_count":1' "${preflight_result}" \
        || fail_preconnect
    test ! -e "${dispatch_sentinel}" || fail_preconnect
    test ! -e "${result_path}" || fail_preconnect
    python_args='["--apply"]'
    confirmation_value="${confirmation}"
    expected_status=corrected
fi

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
        -v "${source_root}:/correction:ro" \
        -w /correction \
        --entrypoint python \
        "${image_id}" \
        -c 'import json,sys; value=sys.stdin.read(); from tools.production_legacy_runtime_role_correction import main; code=main(json.loads(sys.argv[1]),database_url=value,confirmation=(sys.argv[2] or None)); del value; raise SystemExit(code)' \
        "${python_args}" \
        "${confirmation_value}" \
        >"${result_tmp}" 2>>"${error_path}"
pipeline_status=("${PIPESTATUS[@]}")

openssl_exit="${pipeline_status[0]:-125}"
correction_exit="${pipeline_status[1]:-125}"
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

if { test "${correction_exit}" = 126 \
        || test "${correction_exit}" = 127; } \
    && test "${container_count}" = 0 \
    && test "${result_bytes}" = 0; then
    printf '%s\n' \
        "SAFE_ROLE_CORRECTION_RUN mode=${mode} incident_class=PRE_CONNECT openssl_exit=${openssl_exit} correction_exit=${correction_exit} database_connection=0 transaction=0 database_write=0 result_bytes=0 error_bytes=${error_bytes} container=0 retry_same_path=0 ids_printed=0 secrets=0"
    exit 2
fi

if test "${correction_exit}" = 2 \
    && grep -Fq 'production_legacy_runtime_role_correction=FAIL' \
        "${error_path}" \
    && grep -Fq \
        'incident_class=PRE_CONNECT database_connected=0 connection_attempted=0 database_outcome=NOT_CONNECTED' \
        "${error_path}"; then
    rm -f "${result_tmp}" || true
    if test "${container_count}" != 0; then
        printf '%s\n' \
            "SAFE_ROLE_CORRECTION_RUN mode=${mode} incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 container=${container_count} cleanup_required=1 retry_same_path=0 ids_printed=0 secrets=0"
        exit 2
    fi
    printf '%s\n' \
        "SAFE_ROLE_CORRECTION_RUN mode=${mode} incident_class=PRE_CONNECT openssl_exit=${openssl_exit} correction_exit=${correction_exit} database_connection=0 transaction=0 database_write=0 result_bytes=${result_bytes} error_bytes=${error_bytes} container=${container_count} retry_same_path=0 ids_printed=0 secrets=0"
    exit 2
fi

if test "${correction_exit}" = 30 \
    && grep -Fq 'production_legacy_runtime_role_correction=FAIL' \
        "${error_path}" \
    && grep -Fq 'incident_class=CONNECTED_KNOWN' "${error_path}" \
    && grep -Fq 'database_write=0' "${error_path}"; then
    cleanup_required=0
    test "${container_count}" = 0 || cleanup_required=1
    if test "${mode}" = preflight; then
        fail_connected_known \
            READ_ONLY_REJECTED 0 0 "${cleanup_required}"
    fi
    fail_connected_known ROLLED_BACK 0 0 "${cleanup_required}"
fi

if test "${openssl_exit}" = 0 \
    && test "${correction_exit}" = 0 \
    && test "${result_bytes}" -gt 0 \
    && grep -Fq "\"status\":\"${expected_status}\"" "${result_tmp}" \
    && grep -Fq "\"task_id\":\"${confirmation}\"" "${result_tmp}"; then
    known_write_count=2
    test "${mode}" = preflight && known_write_count=0
    known_outcome=COMMITTED
    test "${mode}" = preflight && known_outcome=READ_ONLY_COMPLETED
    test "${container_count}" = 0 \
        || fail_connected_known \
            "${known_outcome}" "${known_write_count}" 1 1
    result_sha_line="$(sha256sum "${result_tmp}")" \
        || fail_connected_known \
            "${known_outcome}" "${known_write_count}" 1 0
    result_sha256="${result_sha_line%% *}"
    if test "${#result_sha256}" != 64; then
        fail_connected_known \
            "${known_outcome}" "${known_write_count}" 1 0
    fi
    case "${result_sha256}" in
        *[!0-9a-f]*)
            fail_connected_known \
                "${known_outcome}" "${known_write_count}" 1 0
            ;;
    esac
    mv "${result_tmp}" "${result_path}" \
        || fail_connected_known \
            "${known_outcome}" "${known_write_count}" 1 0
    transaction_count=1
    printf '%s\n' \
        "SAFE_ROLE_CORRECTION_RUN mode=${mode} incident_class=CONNECTED_KNOWN openssl_exit=${openssl_exit} correction_exit=${correction_exit} database_connection=1 transaction=${transaction_count} database_write=${known_write_count} result_bytes=${result_bytes} result_sha256=${result_sha256} error_bytes=${error_bytes} container=${container_count} automatic_retry=0 ids_printed=0 secrets=0"
    exit 0
fi

fail_connected_unknown
