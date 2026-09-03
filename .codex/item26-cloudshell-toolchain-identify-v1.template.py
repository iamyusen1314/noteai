#!/usr/bin/python3
"""Secret-free, read-only Cloud Shell executable-chain identification atom.

This atom never invokes the wrapper or the final CLI.  It accepts only a very
small literal-dispatch wrapper language.  Unsupported syntax is a terminal
BLOCKED result, not a reason to infer or trace a target executable.
"""

from __future__ import print_function

import ast
import hashlib
import json
import os
import re
import stat
import struct
import sys


SCHEMA = "noteai.item26.cloudshell-toolchain-identification.v1"
PARSER = "strict-absolute-literal-exec-v1"
WRAPPER_PATH = "/usr/shell/bin/aliyun"
EXPECTED_WRAPPER_BYTES = 1289
EXPECTED_WRAPPER_SHA256 = (
    "af8fa54a2c4dbe063de90a7d47d2384b4c3fdd8c3484d42e56eb4fcd716eb7b9"
)
MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024
SAFE_PATH = re.compile(r"\A/[A-Za-z0-9._+/-]+\Z")
SAFE_NAME = re.compile(r"\A[A-Z][A-Z0-9_]*\Z")
FORBIDDEN_SHELL_NAMES = frozenset([
    "BASH", "BASHOPTS", "BASH_ENV", "BASH_SOURCE", "CDPATH", "DIRSTACK",
    "ENV", "EUID", "FUNCNAME", "GLOBIGNORE", "GROUPS", "HISTFILE", "HOME",
    "IFS", "LD_LIBRARY_PATH", "LD_PRELOAD", "LINENO", "OLDPWD", "OPTIND",
    "PATH", "PIPESTATUS", "PPID", "PROMPT_COMMAND", "PWD", "PYTHONHOME",
    "PYTHONPATH", "RANDOM", "SECONDS", "SHELLOPTS", "SHLVL", "UID", "_",
])


class Blocked(Exception):
    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def with_commitment(value):
    result = dict(value)
    result["commitment_sha256"] = hashlib.sha256(
        canonical(value).encode("utf-8")
    ).hexdigest()
    return result


def block(code):
    if not re.match(r"\A[A-Z0-9_]+\Z", code):
        code = "INTERNAL_VALIDATION_ERROR"
    value = {
        "schema": SCHEMA,
        "status": "BLOCKED",
        "reason_code": code,
    }
    print(canonical(with_commitment(value)))
    return 3


def _safe_absolute(path, code="UNSAFE_ABSOLUTE_PATH"):
    if not isinstance(path, str) or not SAFE_PATH.match(path):
        raise Blocked(code)
    if "//" in path or "/./" in path or "/../" in path or path.endswith("/"):
        raise Blocked(code)
    return path


def _mode(st):
    return "%04o" % stat.S_IMODE(st.st_mode)


def _hash_fd(fd):
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return digest.hexdigest()


def _path_prefixes(path):
    parts = path.split("/")[1:]
    current = ""
    for part in parts:
        current += "/" + part
        yield current


def _symlink_records(path):
    records = []
    prefixes = list(_path_prefixes(path))
    root_st = os.lstat("/")
    if (
        not stat.S_ISDIR(root_st.st_mode)
        or root_st.st_uid != 0
        or root_st.st_gid != 0
        or stat.S_IMODE(root_st.st_mode) & 0o022
    ):
        raise Blocked("UNTRUSTED_EXECUTABLE_PARENT")
    for index, prefix in enumerate(prefixes):
        st = os.lstat(prefix)
        if stat.S_ISLNK(st.st_mode):
            target = os.readlink(prefix)
            try:
                target.encode("ascii")
            except UnicodeEncodeError:
                raise Blocked("UNSAFE_SYMLINK_TARGET")
            if not target or "\x00" in target or "\n" in target or "\r" in target:
                raise Blocked("UNSAFE_SYMLINK_TARGET")
            if st.st_uid != 0 or st.st_gid != 0 or st.st_nlink != 1:
                raise Blocked("UNTRUSTED_SYMLINK_METADATA")
            records.append({
                "path": prefix,
                "uid": st.st_uid,
                "gid": st.st_gid,
                "mode": _mode(st),
                "nlink": st.st_nlink,
                "target_sha256": hashlib.sha256(target.encode("ascii")).hexdigest(),
            })
        elif index < len(prefixes) - 1:
            if not stat.S_ISDIR(st.st_mode):
                raise Blocked("NON_DIRECTORY_EXECUTABLE_PARENT")
            if st.st_uid != 0 or st.st_gid != 0:
                raise Blocked("UNTRUSTED_EXECUTABLE_PARENT_OWNER")
            if stat.S_IMODE(st.st_mode) & 0o022:
                raise Blocked("WRITABLE_EXECUTABLE_PARENT")
    if len(records) > 8:
        raise Blocked("TOO_MANY_EXECUTABLE_SYMLINKS")
    return records


def _verify_parent_directories(canonical_path):
    prefixes = list(_path_prefixes(canonical_path))[:-1]
    for prefix in prefixes:
        st = os.lstat(prefix)
        if not stat.S_ISDIR(st.st_mode):
            raise Blocked("NON_DIRECTORY_EXECUTABLE_PARENT")
        if st.st_uid != 0 or st.st_gid != 0:
            raise Blocked("UNTRUSTED_EXECUTABLE_PARENT_OWNER")
        if stat.S_IMODE(st.st_mode) & 0o022:
            raise Blocked("WRITABLE_EXECUTABLE_PARENT")


def snapshot(path, role, expected_size=None, expected_sha256=None):
    invoked = _safe_absolute(path)
    symlinks = _symlink_records(invoked)
    canonical_path = _safe_absolute(os.path.realpath(invoked))
    _verify_parent_directories(canonical_path)

    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(canonical_path, flags)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Blocked("EXECUTABLE_NOT_REGULAR")
        if st.st_uid != 0 or st.st_gid != 0:
            raise Blocked("EXECUTABLE_NOT_ROOT_OWNED")
        if stat.S_IMODE(st.st_mode) != 0o755:
            raise Blocked("EXECUTABLE_MODE_MISMATCH")
        if st.st_nlink != 1:
            raise Blocked("EXECUTABLE_LINK_COUNT_MISMATCH")
        if st.st_size <= 0 or st.st_size > MAX_EXECUTABLE_BYTES:
            raise Blocked("EXECUTABLE_SIZE_OUT_OF_RANGE")
        digest = _hash_fd(fd)
        head = os.read(fd, 131072)
        if expected_size is not None and st.st_size != expected_size:
            raise Blocked("WRAPPER_SIZE_MISMATCH")
        if expected_sha256 is not None and digest != expected_sha256:
            raise Blocked("WRAPPER_SHA256_MISMATCH")
        return ({
            "role": role,
            "invoked_path": invoked,
            "canonical_path": canonical_path,
            "uid": st.st_uid,
            "gid": st.st_gid,
            "mode": _mode(st),
            "nlink": st.st_nlink,
            "size": st.st_size,
            "sha256": digest,
            "symlinks": symlinks,
        }, head)
    finally:
        os.close(fd)


def read_wrapper_bytes():
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    canonical_path = os.path.realpath(WRAPPER_PATH)
    fd = os.open(canonical_path, flags)
    try:
        raw = b""
        while len(raw) <= EXPECTED_WRAPPER_BYTES:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            raw += chunk
        if len(raw) != EXPECTED_WRAPPER_BYTES:
            raise Blocked("WRAPPER_SIZE_MISMATCH")
        if hashlib.sha256(raw).hexdigest() != EXPECTED_WRAPPER_SHA256:
            raise Blocked("WRAPPER_SHA256_MISMATCH")
        return raw
    finally:
        os.close(fd)


def parse_shebang(raw):
    if b"\x00" in raw or b"\r" in raw:
        raise Blocked("UNSAFE_WRAPPER_ENCODING")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Blocked("UNSAFE_WRAPPER_ENCODING")
    first = text.split("\n", 1)[0]
    match = re.match(r"\A#!(/[^ \t]+)\Z", first)
    if not match:
        raise Blocked("NON_LITERAL_SHEBANG")
    interpreter = _safe_absolute(match.group(1), "NON_LITERAL_SHEBANG")
    if os.path.basename(interpreter) == "env":
        raise Blocked("ENV_SHEBANG_FORBIDDEN")
    return text, interpreter


def _unquote_literal(token):
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
        token = token[1:-1]
    return token


def parse_shell(text, inherited_environment=None):
    if inherited_environment is None:
        inherited_names = set(os.environ.keys())
    else:
        inherited_names = set(inherited_environment)
    if any(not isinstance(name, str) for name in inherited_names):
        raise Blocked("INVALID_INHERITED_ENVIRONMENT")
    lines = text.split("\n")[1:]
    active = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "#" in stripped or "\\" in stripped:
            raise Blocked("UNSUPPORTED_SHELL_GRAMMAR")
        active.append(stripped)
    if not active:
        raise Blocked("MISSING_FINAL_EXEC")

    literals = {}
    final_path = None
    final_variable = None
    exec_count = 0
    for index, line in enumerate(active):
        if line in (
            "set -e",
            "set -u",
            "set -eu",
            "set -eo pipefail",
            "set -euo pipefail",
            "set -o pipefail",
        ):
            continue
        match = re.match(
            r"\Areadonly ([A-Z][A-Z0-9_]*)=(['\"]?)(/[^'\" \t]+)\2\Z", line
        )
        if match:
            name = match.group(1)
            if name in FORBIDDEN_SHELL_NAMES or name in inherited_names:
                raise Blocked("INHERITED_ENVIRONMENT_DISPATCH_FORBIDDEN")
            if name in literals:
                raise Blocked("VARIABLE_REASSIGNMENT_FORBIDDEN")
            literals[name] = _safe_absolute(match.group(3), "NON_LITERAL_FINAL_PATH")
            continue
        match = re.match(r"\Aexec ([^ \t]+) \"\$@\"\Z", line)
        if match:
            exec_count += 1
            if index != len(active) - 1:
                raise Blocked("FINAL_EXEC_NOT_TERMINAL")
            target = match.group(1)
            variable = re.match(
                r"\A(?:\"\$([A-Z][A-Z0-9_]*)\"|\"\$\{([A-Z][A-Z0-9_]*)\}\")\Z",
                target,
            )
            if variable:
                final_variable = variable.group(1) or variable.group(2)
                if final_variable not in literals:
                    raise Blocked("VARIABLE_DISPATCH_FORBIDDEN")
                final_path = literals[final_variable]
            else:
                target = _unquote_literal(target)
                final_path = _safe_absolute(target, "NON_LITERAL_FINAL_PATH")
            continue
        raise Blocked("UNSUPPORTED_SHELL_GRAMMAR")
    if exec_count != 1 or final_path is None:
        raise Blocked("MISSING_OR_MULTIPLE_FINAL_EXEC")
    if set(literals) != (set([final_variable]) if final_variable else set()):
        raise Blocked("UNUSED_OR_ENVIRONMENT_ASSIGNMENT_FORBIDDEN")
    return final_path


def _string_value(node):
    constant_type = getattr(ast, "Constant", None)
    if constant_type is not None and isinstance(node, constant_type):
        if isinstance(node.value, str):
            return node.value
        return None
    string_type = getattr(ast, "Str", None)
    if string_type is not None and isinstance(node, string_type):
        return node.s
    return None


def _literal_string(node, literals):
    value = _string_value(node)
    if value is not None:
        return value
    if isinstance(node, ast.Name) and node.id in literals:
        return literals[node.id]
    raise Blocked("VARIABLE_DISPATCH_FORBIDDEN")


def _is_sys_argv_tail(node):
    if not isinstance(node, ast.Subscript):
        return False
    value = node.value
    if not (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == "sys"
        and value.attr == "argv"
    ):
        return False
    section = node.slice
    if isinstance(section, ast.Index):
        section = section.value
    if not isinstance(section, ast.Slice) or section.upper is not None or section.step is not None:
        return False
    lower = section.lower
    constant_type = getattr(ast, "Constant", None)
    if constant_type is not None and isinstance(lower, constant_type):
        return lower.value == 1 and not isinstance(lower.value, bool)
    number_type = getattr(ast, "Num", None)
    if number_type is not None and isinstance(lower, number_type):
        return lower.n == 1
    return False


def parse_python(text):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        raise Blocked("UNSUPPORTED_PYTHON_GRAMMAR")
    literals = {}
    final_path = None
    exec_count = 0
    for index, node in enumerate(tree.body):
        if isinstance(node, ast.Import):
            names = set(item.name for item in node.names)
            if (
                not names.issubset(set(["os", "sys"]))
                or any(item.asname is not None for item in node.names)
            ):
                raise Blocked("UNSUPPORTED_PYTHON_GRAMMAR")
            continue
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            value = _string_value(node.value)
            if not SAFE_NAME.match(name) or name in literals or value is None:
                raise Blocked("VARIABLE_DISPATCH_FORBIDDEN")
            literals[name] = _safe_absolute(value, "NON_LITERAL_FINAL_PATH")
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            func = call.func
            if not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
                and func.attr == "execv"
                and len(call.args) == 2
                and not call.keywords
            ):
                raise Blocked("UNSUPPORTED_PYTHON_GRAMMAR")
            if index != len(tree.body) - 1:
                raise Blocked("FINAL_EXEC_NOT_TERMINAL")
            final_path = _safe_absolute(
                _literal_string(call.args[0], literals), "NON_LITERAL_FINAL_PATH"
            )
            argv = call.args[1]
            if not (
                isinstance(argv, ast.BinOp)
                and isinstance(argv.op, ast.Add)
                and isinstance(argv.left, (ast.List, ast.Tuple))
                and len(argv.left.elts) == 1
                and _literal_string(argv.left.elts[0], literals) == final_path
                and _is_sys_argv_tail(argv.right)
            ):
                raise Blocked("ARGV_FORWARDING_NOT_EXACT")
            exec_count += 1
            continue
        raise Blocked("UNSUPPORTED_PYTHON_GRAMMAR")
    if exec_count != 1 or final_path is None:
        raise Blocked("MISSING_OR_MULTIPLE_FINAL_EXEC")
    used = set()
    call = tree.body[-1].value
    for argument in (call.args[0], call.args[1].left.elts[0]):
        if isinstance(argument, ast.Name):
            used.add(argument.id)
    if set(literals) != used:
        raise Blocked("UNUSED_OR_ENVIRONMENT_ASSIGNMENT_FORBIDDEN")
    return final_path


def parse_wrapper(raw, inherited_environment=None):
    text, interpreter = parse_shebang(raw)
    base = os.path.basename(interpreter)
    if base in ("sh", "bash"):
        final_path = parse_shell(text, inherited_environment=inherited_environment)
        language = "shell"
    elif base in ("python", "python3", "python3.6"):
        final_path = parse_python(text)
        language = "python"
    else:
        raise Blocked("UNSUPPORTED_WRAPPER_INTERPRETER")
    if final_path in (WRAPPER_PATH, interpreter):
        raise Blocked("RECURSIVE_EXEC_CHAIN")
    return interpreter, final_path, language


def verify_static_linux_amd64_elf(head, file_size):
    if not isinstance(head, bytes) or not isinstance(file_size, int) or file_size < 64:
        raise Blocked("FINAL_CLI_ELF_IDENTITY_MISMATCH")
    if len(head) < 64 or head[:4] != b"\x7fELF":
        raise Blocked("FINAL_CLI_NOT_ELF")
    if (
        head[4] != 2
        or head[5] != 1
        or head[6] != 1
        or head[7] != 0
        or head[8] != 0
        or head[9:16] != b"\x00" * 7
    ):
        raise Blocked("FINAL_CLI_ELF_CLASS_MISMATCH")
    e_type = struct.unpack_from("<H", head, 16)[0]
    e_machine = struct.unpack_from("<H", head, 18)[0]
    e_version = struct.unpack_from("<I", head, 20)[0]
    e_entry = struct.unpack_from("<Q", head, 24)[0]
    e_phoff = struct.unpack_from("<Q", head, 32)[0]
    e_shoff = struct.unpack_from("<Q", head, 40)[0]
    e_flags = struct.unpack_from("<I", head, 48)[0]
    e_ehsize = struct.unpack_from("<H", head, 52)[0]
    e_phentsize = struct.unpack_from("<H", head, 54)[0]
    e_phnum = struct.unpack_from("<H", head, 56)[0]
    e_shentsize = struct.unpack_from("<H", head, 58)[0]
    e_shnum = struct.unpack_from("<H", head, 60)[0]
    e_shstrndx = struct.unpack_from("<H", head, 62)[0]
    if (
        e_type not in (2, 3)
        or e_machine != 62
        or e_version != 1
        or e_flags != 0
        or e_ehsize != 64
        or e_phoff != 64
        or e_phentsize != 56
        or e_phnum <= 0
        or e_phnum == 0xFFFF
    ):
        raise Blocked("FINAL_CLI_ELF_IDENTITY_MISMATCH")
    end = e_phoff + e_phentsize * e_phnum
    if end < e_phoff or end > file_size or end > len(head):
        raise Blocked("FINAL_CLI_ELF_HEADERS_TOO_LARGE")
    if e_shoff == 0:
        if e_shentsize != 0 or e_shnum != 0 or e_shstrndx != 0:
            raise Blocked("FINAL_CLI_ELF_SECTION_TABLE_MISMATCH")
    else:
        section_end = e_shoff + e_shentsize * e_shnum
        if (
            e_shentsize != 64
            or e_shnum <= 0
            or e_shstrndx == 0xFFFF
            or (e_shstrndx != 0 and e_shstrndx >= e_shnum)
            or section_end < e_shoff
            or section_end > file_size
        ):
            raise Blocked("FINAL_CLI_ELF_SECTION_TABLE_MISMATCH")

    load_count = 0
    entry_in_executable_load = False
    for index in range(e_phnum):
        offset = e_phoff + index * e_phentsize
        (
            p_type,
            p_flags,
            p_offset,
            p_vaddr,
            _p_paddr,
            p_filesz,
            p_memsz,
            p_align,
        ) = struct.unpack_from("<IIQQQQQQ", head, offset)
        if p_type in (2, 3):
            raise Blocked("FINAL_CLI_NOT_STATIC")
        file_end = p_offset + p_filesz
        if file_end < p_offset or file_end > file_size:
            raise Blocked("FINAL_CLI_ELF_SEGMENT_RANGE_MISMATCH")
        if p_type == 1:
            load_count += 1
            memory_end = p_vaddr + p_memsz
            if (
                p_filesz > p_memsz
                or memory_end < p_vaddr
                or memory_end > 0xFFFFFFFFFFFFFFFF
                or (p_align not in (0, 1) and (p_align & (p_align - 1)) != 0)
                or (p_align not in (0, 1) and p_vaddr % p_align != p_offset % p_align)
            ):
                raise Blocked("FINAL_CLI_ELF_LOAD_RANGE_MISMATCH")
            if p_memsz > 0 and p_vaddr <= e_entry < memory_end and (p_flags & 1):
                entry_in_executable_load = True
    if load_count <= 0:
        raise Blocked("FINAL_CLI_ELF_LOAD_MISSING")
    if not entry_in_executable_load:
        raise Blocked("FINAL_CLI_ELF_ENTRY_OUTSIDE_LOAD")


def identify():
    wrapper_before, _ = snapshot(
        WRAPPER_PATH,
        "wrapper",
        expected_size=EXPECTED_WRAPPER_BYTES,
        expected_sha256=EXPECTED_WRAPPER_SHA256,
    )
    raw = read_wrapper_bytes()
    interpreter_path, final_path, language = parse_wrapper(raw)
    interpreter_before, _ = snapshot(interpreter_path, "wrapper_interpreter")
    final_before, final_head = snapshot(final_path, "final_cli")
    verify_static_linux_amd64_elf(final_head, final_before["size"])

    before = [wrapper_before, interpreter_before, final_before]
    wrapper_after, _ = snapshot(
        WRAPPER_PATH,
        "wrapper",
        expected_size=EXPECTED_WRAPPER_BYTES,
        expected_sha256=EXPECTED_WRAPPER_SHA256,
    )
    interpreter_after, _ = snapshot(interpreter_path, "wrapper_interpreter")
    final_after, final_head_after = snapshot(final_path, "final_cli")
    verify_static_linux_amd64_elf(final_head_after, final_after["size"])
    after = [wrapper_after, interpreter_after, final_after]
    if before != after:
        raise Blocked("EXEC_CHAIN_CHANGED_DURING_IDENTIFICATION")

    value = {
        "schema": SCHEMA,
        "status": "PASS",
        "parser": PARSER,
        "wrapper_language": language,
        "wrapper_policy": {
            "absolute_shebang": True,
            "literal_final_exec": True,
            "exact_argv_forwarding": True,
            "path_lookup": False,
            "variable_dispatch": False,
            "inherited_environment_dispatch": False,
            "dynamic_download": False,
            "cli_invocations": 0,
        },
        "final_cli_format": "elf64-static-linux-amd64",
        "before": before,
        "after": after,
        "before_after_equal": True,
    }
    print(canonical(with_commitment(value)))
    return 0


def main():
    try:
        return identify()
    except Blocked as exc:
        return block(exc.code)
    except Exception:
        return block("INTERNAL_VALIDATION_ERROR")


if __name__ == "__main__":
    sys.exit(main())
