#!/usr/bin/env bash
set -u
set -o pipefail
umask 077

mode="${1:-}"
host_label="${2:-}"
execution_root=/var/lib/noteai/managed-secrets-execution-v1
source_root="${execution_root}/source"
file_task_root=/var/lib/noteai/managed-secrets-v1
maintenance_image_ref=noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:c44354b5abfbb2b22f61e8db316d6abf9a44e805ba3ea3b64074508ff8562f1f
maintenance_image_id=sha256:0b13cd9cafe7de65d5a2754f7cd119cf6fcb822ab134b66a5009c06e08248504
control_private="${execution_root}/control-private.pem"
control_cipher="${execution_root}/control-database-url.enc"
api_f_private="${execution_root}/api-f-private.pem"
api_f_bundle="${execution_root}/api-f-bundle.enc"
prepare_sentinel="${execution_root}/prepare.passed"
incident_id=PROD-FIRST-LAUNCH-MANAGED-SECRETS-V1-001
confirmation=PROD-FIRST-LAUNCH-MANAGED-SECRETS-001
files_sha256=d9540eb6e38465993d0b95d857e3a306159c184ccd87c2326e9bb1c6b9cdaca8
roles_sha256=8d42df5a6ac5b466cd9040757448602f6fedcf0b87ae33fce7a9c3b3fc24973f
audit_sha256=e24f7227356b45ede866228e50911396f7491ed943365526ebd55abb05fed853
distribution_audit_sha256=4f51f1bd0e1220c0b5e856eef1c9157189accabc524fbd8ed53b512f7ca9ead4
lifecycle_sha256=d8d35ac336452a26ed47152da775e64734b4aaa2e7db97313be8dd6c39f743de
envelope_sha256=b6a67fab3fd66f8c378716935b105ac1fbe83c54190eb57baf1b1c3d6b7e2fbf
apply_sha256=387914c293a88c2992e2519465a578ec0bae6876510ea2468212061cc1260201
validator_sha256=0089e3a5736e675a45c8caa5452b3ec3919b64a8697a6b4272a900983402c875
wrapper_sha256=d5c5991fb37ac8279710b8160b99b1dfdd3273e9b975e8bb6e5c3a14138fdbbf

fail_preconnect() {
    printf '%s\n' \
        "SAFE_MANAGED_SECRETS mode=${mode} host=${host_label} incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 automatic_retry=0 cleanup_required=1 ids_printed=0 secrets=0"
    exit 2
}

fail_connected_unknown() {
    printf '%s\n' \
        "SAFE_MANAGED_SECRETS mode=${mode} host=${host_label} incident_class=CONNECTED_UNKNOWN database_connection=unknown transaction=unknown database_write=unknown automatic_retry=0 cleanup_required=1 ids_printed=0 secrets=0"
    exit 1
}

fail_connected_known() {
    outcome="${1:-READ_ONLY_FAILED}"
    writes="${2:-0}"
    printf '%s\n' \
        "SAFE_MANAGED_SECRETS mode=${mode} host=${host_label} incident_class=CONNECTED_KNOWN database_outcome=${outcome} database_write=${writes} automatic_retry=0 cleanup_required=1 ids_printed=0 secrets=0"
    exit 30
}

case "${mode}" in
    prepare | preflight | api-c | api-f | audit | finalize | metadata | cleanup) ;;
    *) fail_preconnect ;;
esac
case "${host_label}" in
    API-C | API-F) ;;
    *) fail_preconnect ;;
esac
case "${execution_root}" in
    /var/lib/noteai/managed-secrets-execution-v1) ;;
    *) fail_preconnect ;;
esac
test -d "${execution_root}" || fail_preconnect
test ! -L "${execution_root}" || fail_preconnect
test "$(stat -c '%u:%g:%a' "${execution_root}")" = "0:0:700" \
    || fail_preconnect
test -d "${source_root}" || fail_preconnect
test ! -L "${source_root}" || fail_preconnect
test -f "${source_root}/package.sha256" || fail_preconnect
test -z "$(find "${source_root}" -type l -print -quit)" || fail_preconnect
(cd "${source_root}" && sha256sum -c package.sha256 >/dev/null 2>&1) \
    || fail_preconnect
test "$(
    sha256sum "${source_root}/tools/production_managed_secret_files.py" \
        | cut -d' ' -f1
)" = "${files_sha256}" || fail_preconnect
test "$(
    sha256sum "${source_root}/tools/production_managed_secret_roles.py" \
        | cut -d' ' -f1
)" = "${roles_sha256}" || fail_preconnect
test "$(
    sha256sum \
        "${source_root}/tools/production_managed_secret_login_audit.py" \
        | cut -d' ' -f1
)" = "${audit_sha256}" || fail_preconnect
test "$(
    sha256sum \
        "${source_root}/tools/production_managed_secret_distribution_audit.py" \
        | cut -d' ' -f1
)" = "${distribution_audit_sha256}" || fail_preconnect
test "$(
    sha256sum \
        "${source_root}/tools/production_managed_secret_lifecycle.py" \
        | cut -d' ' -f1
)" = "${lifecycle_sha256}" || fail_preconnect
test "$(
    sha256sum "${source_root}/tools/production_secret_envelope.py" \
        | cut -d' ' -f1
)" = "${envelope_sha256}" || fail_preconnect
test "$(
    sha256sum \
        "${source_root}/tools/production_managed_secret_initial_apply.py" \
        | cut -d' ' -f1
)" = "${apply_sha256}" || fail_preconnect
test "$(
    sha256sum "${source_root}/scripts/validate_production_env_files.py" \
        | cut -d' ' -f1
)" = "${validator_sha256}" || fail_preconnect
test "$(
    sha256sum \
        "${source_root}/scripts/production/noteai-managed-secret-lifecycle-wrapper" \
        | cut -d' ' -f1
)" = "${wrapper_sha256}" || fail_preconnect
test -z "$(
    find "${source_root}" -type f -perm /022 -print -quit
)" || fail_preconnect

actual_image_id="$(
    docker image inspect --format '{{.Id}}' "${maintenance_image_ref}" \
        2>/dev/null
)" || fail_preconnect
test "${actual_image_id}" = "${maintenance_image_id}" || fail_preconnect
image_id="${maintenance_image_ref}"

validate_result() {
    result_mode="${1}"
    result_path="${2}"
    result_host="${3}"
    python3 -I - "${result_mode}" "${result_path}" "${result_host}" <<'PY'
import json
import sys


def require(condition):
    if not condition:
        raise SystemExit(1)


mode, path, host = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    result = json.load(handle)
require(
    result.get("task_id")
    == "PROD-FIRST-LAUNCH-MANAGED-SECRETS-001"
)
for key in (
    "secret_values_emitted",
    "service_changes",
    "public_traffic_requests",
):
    require(result.get(key) == 0)
if mode == "api-c":
    require(result.get("status") == "api_c_committed")
    require(result.get("incident_class") == "CONNECTED_KNOWN")
    require(result.get("database_outcome") == "COMMITTED")
    require(result.get("database_transactions") == 1)
    require(result.get("role_attribute_writes") == 5)
    require(result.get("password_writes") == 5)
    require(result.get("membership_writes") == 0)
    require(result.get("acl_writes") == 0)
    require(result.get("schema_writes") == 0)
    require(result.get("business_row_writes") == 0)
    require(result.get("dispatcher_login_enabled") == 0)
    require(result.get("api_c_promoted_files") == 3)
    require(result.get("api_f_encrypted_bundle_count") == 1)
    require(result.get("plaintext_task_file_count") == 0)
elif mode == "preflight":
    require(result.get("status") == "preflight_verified")
    require(result.get("host_label") == host)
    require(result.get("existing_file_count") == 2)
    require(result.get("new_file_count") == 0)
    require(result.get("database_connections") == 0)
    require(result.get("legacy_cookie_present") in {0, 1})
    require(result.get("legacy_database_url_present") in {0, 1})
elif mode == "api-f":
    require(result.get("status") == "api_f_promoted")
    require(result.get("incident_class") == "PRE_CONNECT")
    require(result.get("database_connections") == 0)
    require(result.get("database_transactions") == 0)
    require(result.get("database_writes") == 0)
    require(result.get("staged_files") == 2)
    require(result.get("promoted_files") == 2)
    require(result.get("plaintext_task_file_count") == 0)
elif mode == "audit":
    require(result.get("status") == "verified")
    require(result.get("host_label") == host)
    require(result.get("forced_read_only") is True)
    expected = 4 if host == "API-C" else 3
    require(result.get("file_count") == expected)
    require(result.get("connection_count") == expected)
    require(result.get("read_only_transaction_count") == expected)
    require(result.get("unexpected_elevation_count") == 0)
    require(result.get("incoming_membership_count") == 0)
    require(result.get("owned_object_count") == 0)
    require(result.get("ledger_read_count") == 0)
    require(result.get("business_values_read") == 0)
PY
}

if test "${mode}" = prepare; then
    test ! -e "${prepare_sentinel}" || fail_preconnect
    docker run \
        --rm \
        --pull never \
        --network none \
        --user 999:999 \
        --read-only \
        --cap-drop=ALL \
        --security-opt=no-new-privileges:true \
        --pids-limit 64 \
        --memory 128m \
        --cpus 0.25 \
        --tmpfs /tmp:rw,noexec,nosuid,nodev,size=8m \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -e PYTHONPATH=/task \
        -v "${source_root}:/task:ro" \
        -w /task \
        --entrypoint python \
        "${image_id}" \
        -c 'import tools.production_managed_secret_files; import tools.production_managed_secret_roles; import tools.production_managed_secret_login_audit; import tools.production_managed_secret_distribution_audit; import tools.production_managed_secret_lifecycle; import tools.production_secret_envelope; import tools.production_managed_secret_initial_apply' \
        >/dev/null 2>&1 \
        || fail_preconnect
    install -d -o root -g root -m 0755 /usr/local/lib/noteai \
        || fail_preconnect
    install -o root -g root -m 0644 \
        "${source_root}/tools/production_managed_secret_lifecycle.py" \
        /usr/local/lib/noteai/production_managed_secret_lifecycle.py \
        || fail_preconnect
    for tool in \
        noteai-rotate-production-secrets \
        noteai-revoke-production-secrets
    do
        install -o root -g root -m 0750 \
            "${source_root}/scripts/production/noteai-managed-secret-lifecycle-wrapper" \
            "/usr/local/sbin/${tool}" || fail_preconnect
    done
    test "$(
        sha256sum \
            /usr/local/lib/noteai/production_managed_secret_lifecycle.py \
            | cut -d' ' -f1
    )" = "${lifecycle_sha256}" || fail_preconnect
    test "$(
        sha256sum /usr/local/sbin/noteai-rotate-production-secrets \
            | cut -d' ' -f1
    )" = "${wrapper_sha256}" || fail_preconnect
    test "$(
        sha256sum /usr/local/sbin/noteai-revoke-production-secrets \
            | cut -d' ' -f1
    )" = "${wrapper_sha256}" || fail_preconnect
    package_sha="$(
        sha256sum "${source_root}/package.sha256" | cut -d' ' -f1
    )" || fail_preconnect
    printf '%s\n' "${incident_id}:${host_label}:${package_sha}" \
        >"${prepare_sentinel}" || fail_preconnect
    test "$(stat -c '%u:%g:%a:%h' "${prepare_sentinel}")" = \
        "0:0:600:1" || fail_preconnect
    printf '%s\n' \
        "SAFE_MANAGED_SECRETS mode=prepare host=${host_label} incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 import=passed lifecycle_tools=2 automatic_retry=0 cleanup_required=1 ids_printed=0 secrets=0"
    exit 0
fi

test -f "${prepare_sentinel}" || fail_preconnect
test ! -L "${prepare_sentinel}" || fail_preconnect
test "$(stat -c '%u:%g:%a:%h' "${prepare_sentinel}")" = \
    "0:0:600:1" || fail_preconnect

result_path="${execution_root}/${mode}-result.json"
error_path="${execution_root}/${mode}-error.log"
started_path="${execution_root}/${mode}.started"
test ! -e "${result_path}" || fail_preconnect
test ! -e "${error_path}" || fail_preconnect
test ! -e "${started_path}" || fail_preconnect

if test "${mode}" = cleanup; then
    test ! -e "${file_task_root}" || fail_preconnect
    rm -rf --one-file-system "${execution_root}" || fail_preconnect
    printf '%s\n' \
        "SAFE_MANAGED_SECRETS mode=cleanup host=${host_label} incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 task_residue=0 lifecycle_tools=2 automatic_retry=0 cleanup_required=0 ids_printed=0 secrets=0"
    exit 0
fi

printf 'started\n' >"${started_path}" || fail_preconnect
container_name="noteai-managed-secrets-${mode,,}-once"
existing="$(
    docker ps -a \
        --filter "name=^/${container_name}$" \
        --format '{{.ID}}'
)" || fail_preconnect
test -z "${existing}" || fail_preconnect

if test "${mode}" = preflight; then
    docker run \
        --rm \
        --pull never \
        --network none \
        --name "${container_name}" \
        --user 0:0 \
        --read-only \
        --cap-drop=ALL \
        --security-opt=no-new-privileges:true \
        --pids-limit 64 \
        --memory 128m \
        --cpus 0.25 \
        --tmpfs /tmp:rw,noexec,nosuid,nodev,size=8m \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -e PYTHONPATH=/task \
        -v /etc/noteai:/etc/noteai:ro \
        -v /var/lib/noteai:/var/lib/noteai:ro \
        -v "${source_root}:/task:ro" \
        -w /task \
        --entrypoint python \
        "${image_id}" \
        -m tools.production_managed_secret_files \
        preflight \
        --host-label "${host_label}" \
        >"${result_path}" 2>"${error_path}" \
        || fail_preconnect
    test ! -s "${error_path}" || fail_preconnect
    validate_result preflight "${result_path}" "${host_label}" \
        || fail_preconnect
    legacy_cookie="$(
        python3 -I -c \
            'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["legacy_cookie_present"])' \
            "${result_path}"
    )" || fail_preconnect
    legacy_database="$(
        python3 -I -c \
            'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["legacy_database_url_present"])' \
            "${result_path}"
    )" || fail_preconnect
    result_sha="$(
        sha256sum "${result_path}" | cut -d' ' -f1
    )" || fail_preconnect
    printf '%s\n' \
        "SAFE_MANAGED_SECRETS mode=preflight host=${host_label} incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 existing_files=2 new_files=0 legacy_cookie=${legacy_cookie} legacy_database=${legacy_database} result_sha256=${result_sha} automatic_retry=0 cleanup_required=1 ids_printed=0 secrets=0"
    exit 0
fi

if test "${mode}" = api-c; then
    test "${host_label}" = API-C || fail_preconnect
    for path in \
        "${control_private}" \
        "${control_cipher}" \
        "${execution_root}/api-c-public.pem" \
        "${execution_root}/api-f-public.pem"
    do
        test -f "${path}" || fail_preconnect
        test ! -L "${path}" || fail_preconnect
    done
    test "$(stat -c '%u:%g:%a:%h' "${control_private}")" = \
        "0:0:600:1" || fail_preconnect
    test "$(stat -c '%u:%g:%a:%h' "${control_cipher}")" = \
        "0:0:600:1" || fail_preconnect
    set +e
    openssl pkeyutl \
        -decrypt \
        -inkey "${control_private}" \
        -pkeyopt rsa_padding_mode:oaep \
        -pkeyopt rsa_oaep_md:sha256 \
        -in "${control_cipher}" 2>"${execution_root}/decrypt-error.log" \
        | docker run \
            --rm \
            --pull never \
            --network host \
            --name "${container_name}" \
            --user 0:0 \
            --read-only \
            --cap-drop=ALL \
            --security-opt=no-new-privileges:true \
            --pids-limit 128 \
            --memory 256m \
            --cpus 0.5 \
            --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
            -e PYTHONDONTWRITEBYTECODE=1 \
            -e PYTHONPATH=/task \
            -i \
            -v /etc/noteai:/etc/noteai:rw \
            -v /var/lib/noteai:/var/lib/noteai:rw \
            -v "${source_root}:/task:ro" \
            -v "${source_root}:${source_root}:ro" \
            -w /task \
            --entrypoint python \
            "${image_id}" \
            -m tools.production_managed_secret_initial_apply \
            --api-c \
            --confirm "${confirmation}" \
            >"${result_path}" 2>"${error_path}"
    pipeline_status=("${PIPESTATUS[@]}")
    decrypt_exit="${pipeline_status[0]:-125}"
    task_exit="${pipeline_status[1]:-125}"
    if test "${decrypt_exit}" = 0 \
        && test "${task_exit}" = 0 \
        && test ! -s "${execution_root}/decrypt-error.log" \
        && test ! -s "${error_path}" \
        && validate_result api-c "${result_path}" "${host_label}"; then
        result_sha="$(
            sha256sum "${result_path}" | cut -d' ' -f1
        )" || fail_connected_known COMMITTED 5
        printf '%s\n' \
            "SAFE_MANAGED_SECRETS mode=api-c host=API-C incident_class=CONNECTED_KNOWN database_outcome=COMMITTED database_connection=1 transaction=1 role_write=5 password_write=5 membership_write=0 schema_write=0 business_write=0 promoted_files=3 encrypted_bundles=2 result_sha256=${result_sha} automatic_retry=0 cleanup_required=1 ids_printed=0 secrets=0"
        exit 0
    fi
    if grep -Eq \
        '^production_managed_secret_initial_apply=FAIL code=pre_connect_' \
        "${error_path}" 2>/dev/null; then
        fail_preconnect
    fi
    if grep -Fxq \
        'production_managed_secret_initial_apply=FAIL code=connected_known_committed_file_promotion' \
        "${error_path}" 2>/dev/null; then
        fail_connected_known COMMITTED 5
    fi
    fail_connected_unknown
fi

if test "${mode}" = api-f; then
    test "${host_label}" = API-F || fail_preconnect
    test -f "${api_f_private}" || fail_preconnect
    test -f "${api_f_bundle}" || fail_preconnect
    docker run \
        --rm \
        --pull never \
        --network none \
        --name "${container_name}" \
        --user 0:0 \
        --read-only \
        --cap-drop=ALL \
        --security-opt=no-new-privileges:true \
        --pids-limit 64 \
        --memory 128m \
        --cpus 0.25 \
        --tmpfs /tmp:rw,noexec,nosuid,nodev,size=8m \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -e PYTHONPATH=/task \
        -v /etc/noteai:/etc/noteai:rw \
        -v /var/lib/noteai:/var/lib/noteai:rw \
        -v "${source_root}:/task:ro" \
        -v "${source_root}:${source_root}:ro" \
        -w /task \
        --entrypoint python \
        "${image_id}" \
        -m tools.production_managed_secret_initial_apply \
        --api-f \
        --confirm "${confirmation}" \
        >"${result_path}" 2>"${error_path}" \
        || fail_preconnect
    test ! -s "${error_path}" || fail_preconnect
    validate_result api-f "${result_path}" "${host_label}" \
        || fail_preconnect
    result_sha="$(
        sha256sum "${result_path}" | cut -d' ' -f1
    )" || fail_preconnect
    printf '%s\n' \
        "SAFE_MANAGED_SECRETS mode=api-f host=API-F incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 promoted_files=2 result_sha256=${result_sha} automatic_retry=0 cleanup_required=1 ids_printed=0 secrets=0"
    exit 0
fi

if test "${mode}" = audit; then
    docker run \
        --rm \
        --pull never \
        --network host \
        --name "${container_name}" \
        --user 0:0 \
        --read-only \
        --cap-drop=ALL \
        --security-opt=no-new-privileges:true \
        --pids-limit 64 \
        --memory 128m \
        --cpus 0.25 \
        --tmpfs /tmp:rw,noexec,nosuid,nodev,size=8m \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -e PYTHONPATH=/task \
        -v /etc/noteai:/etc/noteai:ro \
        -v "${source_root}:/task:ro" \
        -w /task \
        --entrypoint python \
        "${image_id}" \
        -m tools.production_managed_secret_login_audit \
        --host-label "${host_label}" \
        >"${result_path}" 2>"${error_path}" \
        || fail_connected_known READ_ONLY_FAILED 0
    test ! -s "${error_path}" || fail_connected_known READ_ONLY_FAILED 0
    validate_result audit "${result_path}" "${host_label}" \
        || fail_connected_known READ_ONLY_FAILED 0
    result_sha="$(
        sha256sum "${result_path}" | cut -d' ' -f1
    )" || fail_connected_known READ_ONLY_VERIFIED 0
    expected_connections=4
    test "${host_label}" = API-F && expected_connections=3
    printf '%s\n' \
        "SAFE_MANAGED_SECRETS mode=audit host=${host_label} incident_class=CONNECTED_KNOWN database_outcome=READ_ONLY_VERIFIED database_connection=${expected_connections} audit_transaction=${expected_connections} database_write=0 full_negative_matrix=1 result_sha256=${result_sha} automatic_retry=0 cleanup_required=1 ids_printed=0 secrets=0"
    exit 0
fi

if test "${mode}" = finalize; then
    docker run \
        --rm \
        --pull never \
        --network none \
        --name "${container_name}" \
        --user 0:0 \
        --read-only \
        --cap-drop=ALL \
        --security-opt=no-new-privileges:true \
        --pids-limit 64 \
        --memory 128m \
        --cpus 0.25 \
        --tmpfs /tmp:rw,noexec,nosuid,nodev,size=8m \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -e PYTHONPATH=/task \
        -v /etc/noteai:/etc/noteai:rw \
        -v /var/lib/noteai:/var/lib/noteai:rw \
        -v "${source_root}:/task:ro" \
        -v "${source_root}:${source_root}:ro" \
        -w /task \
        --entrypoint python \
        "${image_id}" \
        -m tools.production_managed_secret_files \
        finalize \
        --host-label "${host_label}" \
        >"${result_path}" 2>"${error_path}" \
        || fail_preconnect
    test ! -s "${error_path}" || fail_preconnect
    test ! -e "${file_task_root}" || fail_preconnect
    printf '%s\n' \
        "SAFE_MANAGED_SECRETS mode=finalize host=${host_label} incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 rollback_artifact=0 secret_task_root=0 automatic_retry=0 cleanup_required=1 ids_printed=0 secrets=0"
    exit 0
fi

if test "${mode}" = metadata; then
    docker run \
        --rm \
        --pull never \
        --network none \
        --name "${container_name}" \
        --user 0:0 \
        --read-only \
        --cap-drop=ALL \
        --security-opt=no-new-privileges:true \
        --pids-limit 64 \
        --memory 128m \
        --cpus 0.25 \
        --tmpfs /tmp:rw,noexec,nosuid,nodev,size=8m \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -e PYTHONPATH=/task \
        -v /etc/noteai:/etc/noteai:ro \
        -v /etc/systemd/system:/etc/systemd/system:ro \
        -v /usr/local/sbin:/usr/local/sbin:ro \
        -v "${source_root}:/task:ro" \
        -w /task \
        --entrypoint python \
        "${image_id}" \
        -m tools.production_managed_secret_distribution_audit \
        --host-label "${host_label}" \
        >"${result_path}" 2>"${error_path}" \
        || fail_preconnect
    test ! -s "${error_path}" || fail_preconnect
    python3 -I - "${result_path}" "${host_label}" <<'PY' \
        || fail_preconnect
import json
import sys

result = json.load(open(sys.argv[1], encoding="utf-8"))
host = sys.argv[2]
expected = 4 if host == "API-C" else 3
assert result["host_label"] == host
assert result["present_file_count"] == expected
assert result["missing_file_count"] == 0
assert result["root_only_file_count"] == expected
assert result["distinct_present_file_count"] == expected
assert result["rejected_key_count"] == 0
assert result["duplicate_key_count"] == 0
assert result["backup_artifact_count"] == 0
assert result["rotation_tool"]["present"] is True
assert result["rotation_tool"]["root_owned"] is True
assert result["rotation_tool"]["mode"] == "0750"
assert result["revocation_tool"]["present"] is True
assert result["revocation_tool"]["root_owned"] is True
assert result["revocation_tool"]["mode"] == "0750"
if host == "API-F":
    assert result["legacy_file"]["present"] is False
PY
    result_sha="$(
        sha256sum "${result_path}" | cut -d' ' -f1
    )" || fail_preconnect
    printf '%s\n' \
        "SAFE_MANAGED_SECRETS mode=metadata host=${host_label} incident_class=PRE_CONNECT database_connection=0 transaction=0 database_write=0 final_files=verified lifecycle_tools=2 legacy_xhs=0 result_sha256=${result_sha} automatic_retry=0 cleanup_required=1 ids_printed=0 secrets=0"
    exit 0
fi

fail_preconnect
