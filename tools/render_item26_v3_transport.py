#!/usr/bin/env python3
"""Render and validate the Secret-free Item 26 v3 transport chain."""

from __future__ import annotations

import ast
import base64
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from types import MappingProxyType
from typing import Callable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATHS = {
    "source": REPOSITORY_ROOT / ".codex" / "item26-source-manifest.template.sh",
    "executor": (
        REPOSITORY_ROOT
        / ".codex"
        / "item26-source-manifest-executor-v3.template.sh"
    ),
    "controller": (
        REPOSITORY_ROOT
        / ".codex"
        / "item26-source-manifest-executor-v3-controller.template.py"
    ),
    "wrapper": (
        REPOSITORY_ROOT
        / ".codex"
        / "item26-source-manifest-executor-v3-wrapper.template.sh"
    ),
    "readback": (
        REPOSITORY_ROOT
        / ".codex"
        / "item26-source-manifest-readback-v3.template.sh"
    ),
}
SUMMARY_LAYER_NAMES = (
    "source",
    "driver",
    "transfer_gzip",
    "executor",
    "executor_gzip",
    "controller",
    "controller_gzip",
    "wrapper",
    "readback",
)
SUMMARY_KEYS = frozenset(
    SUMMARY_LAYER_NAMES
    + ("command_content", "production_provenance", "public_bindings")
)
PLACEHOLDER = re.compile(br"@@[A-Z][A-Z0-9_]*@@")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DRIVER_START = b"cat >\"$DRIVER_PATH\" <<'PY'\n"
DRIVER_END = b"PY\nchmod 0600 \"$DRIVER_PATH\""
MAX_TEMPLATE_BYTES = 262144
MAX_BOUND_LAYER_BYTES = 131072
MAX_COMMAND_CONTENT_BYTES = 18000
EXPECTED_ENVELOPE_BYTES = 894
EXPECTED_DRIVER_BYTES = 18084
EXPECTED_DRIVER_SHA256 = (
    "282c789b8918cdbe9e1512a0a54e248ab7d9e2814aea1629f8353487d962d67e"
)
_TEMPLATE_IDENTITY_ROWS = (
    (
        "source",
        35352,
        "7e2bc2651a9dcd4ca546a03a9ada937c9133f21c725b5d1508f69eb6ebe9668e",
    ),
    (
        "executor",
        16961,
        "87d70818bcf695e843325e0a1a475549c2e661f65919c695b8651acc53aad0b4",
    ),
    (
        "controller",
        10039,
        "b89ee0fdcf3420694d7a45547664e3ef12bb810ad2285b9feaf09c175c096c07",
    ),
    (
        "wrapper",
        3276,
        "5fd926666ccabd678be44fde5c0b3e1bdf5555ae249899448ea6746dd457c021",
    ),
    (
        "readback",
        25827,
        "ef80ff4eb3a090959882ff0dff392a309c7cb691f128394fb9767c5f07eca8b1",
    ),
)
TEMPLATE_IDENTITIES = MappingProxyType(
    {
        name: MappingProxyType({"bytes": size, "sha256": digest})
        for name, size, digest in _TEMPLATE_IDENTITY_ROWS
    }
)
PRODUCTION_PROVENANCE = MappingProxyType(
    {
        "gzip_arguments": ("-9", "-n", "-c"),
        "gzip_implementation": "GNU",
        "platform": "linux",
        "templates": TEMPLATE_IDENTITIES,
    }
)


class RenderError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _production_provenance_summary() -> dict[str, object]:
    return {
        "gzip_arguments": list(PRODUCTION_PROVENANCE["gzip_arguments"]),
        "gzip_implementation": PRODUCTION_PROVENANCE["gzip_implementation"],
        "platform": PRODUCTION_PROVENANCE["platform"],
        "templates": {
            name: dict(identity)
            for name, identity in TEMPLATE_IDENTITIES.items()
        },
    }


def _read_template(name: str) -> bytes:
    path = TEMPLATE_PATHS[name]
    expected = TEMPLATE_IDENTITIES[name]
    try:
        before = path.lstat()
    except OSError as exc:
        raise RenderError("{}_template_stat".format(name)) from exc
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_size != expected["bytes"]
        or not 1 <= before.st_size <= MAX_TEMPLATE_BYTES
    ):
        raise RenderError("{}_template_metadata".format(name))
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        file_descriptor = os.open(str(path), flags)
        try:
            opened = os.fstat(file_descriptor)
            if (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
                opened.st_size,
            ) != (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_size,
            ):
                raise RenderError("{}_template_race".format(name))
            payload = b""
            while len(payload) <= expected["bytes"]:
                chunk = os.read(
                    file_descriptor,
                    min(65536, expected["bytes"] + 1 - len(payload)),
                )
                if not chunk:
                    break
                payload += chunk
            closed = os.fstat(file_descriptor)
            if (
                closed.st_dev,
                closed.st_ino,
                closed.st_mode,
                closed.st_size,
            ) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
                opened.st_size,
            ):
                raise RenderError("{}_template_race".format(name))
        finally:
            os.close(file_descriptor)
        after = path.lstat()
    except RenderError:
        raise
    except OSError as exc:
        raise RenderError("{}_template_read".format(name)) from exc
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    )
    if before_identity != after_identity:
        raise RenderError("{}_template_race".format(name))
    if len(payload) != expected["bytes"] or _sha256(payload) != expected["sha256"]:
        raise RenderError("{}_template_identity".format(name))
    _validate_ascii_lf(name + "_template", payload)
    return payload


def _validate_ascii_lf(name: str, payload: bytes) -> None:
    if not payload or b"\x00" in payload or b"\r" in payload:
        raise RenderError(name + "_encoding")
    try:
        payload.decode("ascii")
    except UnicodeError as exc:
        raise RenderError(name + "_encoding") from exc
    if not payload.endswith(b"\n"):
        raise RenderError(name + "_terminal_lf")


def _render(name: str, template: bytes, bindings: dict[bytes, bytes]) -> bytes:
    if not bindings:
        raise RenderError(name + "_bindings")
    expected = Counter({token: 1 for token in bindings})
    supplied = Counter(PLACEHOLDER.findall(template))
    if supplied != expected or template.count(b"@@") != 2 * len(bindings):
        raise RenderError(name + "_placeholder_inventory")
    for token, value in bindings.items():
        if (
            PLACEHOLDER.fullmatch(token) is None
            or not value
            or b"\n" in value
            or b"\r" in value
            or b"\x00" in value
        ):
            raise RenderError(name + "_binding_value")

    rendered = PLACEHOLDER.sub(lambda match: bindings[match.group(0)], template)
    # Base85 is opaque data and may naturally contain a bare ``@@`` pair.
    # Only a complete placeholder-shaped token represents unresolved syntax.
    if PLACEHOLDER.search(rendered) is not None:
        raise RenderError(name + "_placeholder_residue")
    _validate_ascii_lf(name, rendered)
    return rendered


def _run_bash_syntax(name: str, payload: bytes) -> None:
    try:
        result = subprocess.run(
            ["/bin/bash", "-n", "-s"],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            timeout=30,
            check=False,
        )
    except BaseException as exc:
        raise RenderError(name + "_bash_syntax") from exc
    if result.returncode != 0 or result.stdout or len(result.stderr) > 4096:
        raise RenderError(name + "_bash_syntax")


def _python_heredocs(name: str, payload: bytes, expected_count: int) -> list[bytes]:
    lines = payload.splitlines(keepends=True)
    bodies = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if b"<<'PY'" not in line:
            index += 1
            continue
        body = []
        index += 1
        while index < len(lines) and lines[index] not in (b"PY\n", b"PY"):
            body.append(lines[index])
            index += 1
        if index >= len(lines):
            raise RenderError(name + "_python_heredoc")
        bodies.append(b"".join(body))
        index += 1
    if len(bodies) != expected_count or any(not body for body in bodies):
        raise RenderError(name + "_python_heredoc")
    return bodies


def _python36_syntax(name: str, payload: bytes) -> None:
    try:
        source = payload.decode("ascii")
        ast.parse(source, filename=name, mode="exec", feature_version=(3, 6))
    except BaseException as exc:
        raise RenderError(name + "_python36_syntax") from exc


def _validate_bash_python(
    name: str,
    payload: bytes,
    expected_heredocs: int,
) -> None:
    _run_bash_syntax(name, payload)
    for index, body in enumerate(
        _python_heredocs(name, payload, expected_heredocs),
        start=1,
    ):
        _python36_syntax("{}_heredoc_{}".format(name, index), body)


def _extract_driver(source: bytes) -> bytes:
    if source.count(DRIVER_START) != 1 or source.count(DRIVER_END) != 1:
        raise RenderError("driver_markers")
    _head, separator, tail = source.partition(DRIVER_START)
    if not separator:
        raise RenderError("driver_markers")
    driver, separator, _remainder = tail.partition(DRIVER_END)
    if not separator or not driver.endswith(b"\n"):
        raise RenderError("driver_terminal_lf")
    if any(line.rstrip(b"\n") == b"PY" for line in driver.splitlines(keepends=True)):
        raise RenderError("driver_delimiter")
    _validate_ascii_lf("driver", driver)
    if len(driver) != EXPECTED_DRIVER_BYTES or _sha256(driver) != EXPECTED_DRIVER_SHA256:
        raise RenderError("driver_current_binding")

    probe = b"cat <<'PY'\n" + driver + b"PY\n"
    try:
        result = subprocess.run(
            ["/bin/bash", "-s"],
            input=probe,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            timeout=30,
            check=False,
        )
    except BaseException as exc:
        raise RenderError("driver_shell_roundtrip") from exc
    if result.returncode != 0 or result.stderr or result.stdout != driver:
        raise RenderError("driver_shell_roundtrip")
    return driver


def _production_gzip_compressor() -> Callable[[bytes], bytes]:
    if not sys.platform.startswith("linux"):
        raise RenderError("linux_required")
    clean_environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    try:
        version = subprocess.run(
            ["/usr/bin/gzip", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=clean_environment,
            timeout=10,
            check=False,
        )
    except BaseException as exc:
        raise RenderError("gnu_gzip_required") from exc
    if (
        version.returncode != 0
        or version.stderr
        or len(version.stdout) > 8192
        or not version.stdout.startswith(b"gzip ")
        or b"Free Software Foundation" not in version.stdout
    ):
        raise RenderError("gnu_gzip_required")

    def compress(payload: bytes) -> bytes:
        try:
            result = subprocess.run(
                ["/usr/bin/gzip", "-9", "-n", "-c"],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=clean_environment,
                timeout=30,
                check=False,
            )
        except BaseException as exc:
            raise RenderError("gnu_gzip") from exc
        if result.returncode != 0 or result.stderr:
            raise RenderError("gnu_gzip")
        return result.stdout

    return compress


def _compress(
    name: str,
    payload: bytes,
    compressor: Callable[[bytes], bytes],
) -> bytes:
    try:
        compressed = compressor(payload)
    except RenderError:
        raise
    except BaseException as exc:
        raise RenderError(name + "_gzip") from exc
    if (
        type(compressed) is not bytes
        or not 1 <= len(compressed) <= MAX_BOUND_LAYER_BYTES
    ):
        raise RenderError(name + "_gzip")
    try:
        restored = gzip.decompress(compressed)
    except BaseException as exc:
        raise RenderError(name + "_gzip_roundtrip") from exc
    if restored != payload:
        raise RenderError(name + "_gzip_roundtrip")
    return compressed


def _b85(name: str, payload: bytes) -> bytes:
    encoded = base64.b85encode(payload)
    try:
        restored = base64.b85decode(encoded)
    except BaseException as exc:
        raise RenderError(name + "_b85_roundtrip") from exc
    if restored != payload or b"\n" in encoded or b"\r" in encoded:
        raise RenderError(name + "_b85_roundtrip")
    return encoded


def _layer(payload: bytes) -> dict[str, object]:
    return {"bytes": len(payload), "sha256": _sha256(payload)}


def _validate_public_inputs(
    envelope_bytes: int,
    envelope_sha256: str,
    public_key_sha256: str,
) -> None:
    if type(envelope_bytes) is not int or envelope_bytes != EXPECTED_ENVELOPE_BYTES:
        raise RenderError("envelope_bytes")
    if (
        type(envelope_sha256) is not str
        or HEX64.fullmatch(envelope_sha256) is None
        or type(public_key_sha256) is not str
        or HEX64.fullmatch(public_key_sha256) is None
    ):
        raise RenderError("public_sha256")


def _render_item26_v3_transport_core(
    envelope_bytes: int,
    envelope_sha256: str,
    public_key_sha256: str,
    *,
    gzip_compressor: Callable[[bytes], bytes],
) -> dict[str, object]:
    """Render artifacts for production or explicitly non-production tests."""

    _validate_public_inputs(envelope_bytes, envelope_sha256, public_key_sha256)
    templates = {name: _read_template(name) for name in TEMPLATE_PATHS}

    source = _render(
        "source",
        templates["source"],
        {
            b"@@ENVELOPE_BYTES@@": str(envelope_bytes).encode("ascii"),
            b"@@ENVELOPE_SHA256@@": envelope_sha256.encode("ascii"),
            b"@@PUBLIC_KEY_SHA256@@": public_key_sha256.encode("ascii"),
        },
    )
    _validate_bash_python("source", source, 3)
    driver = _extract_driver(source)
    transfer_gzip = _compress("transfer", source, gzip_compressor)
    if len(source) > MAX_BOUND_LAYER_BYTES:
        raise RenderError("source_size")

    executor = _render(
        "executor",
        templates["executor"],
        {
            b"@@TRANSFER_BYTES@@": str(len(transfer_gzip)).encode("ascii"),
            b"@@TRANSFER_SHA256@@": _sha256(transfer_gzip).encode("ascii"),
            b"@@RAW_BYTES@@": str(len(source)).encode("ascii"),
            b"@@RAW_SHA256@@": _sha256(source).encode("ascii"),
        },
    )
    _validate_bash_python("executor", executor, 1)
    executor_gzip = _compress("executor", executor, gzip_compressor)
    if len(executor) > MAX_BOUND_LAYER_BYTES:
        raise RenderError("executor_size")

    executor_b85 = _b85("executor", executor_gzip)
    controller = _render(
        "controller",
        templates["controller"],
        {
            b"@@EXECUTOR_GZIP_BYTES@@": str(len(executor_gzip)).encode("ascii"),
            b"@@EXECUTOR_GZIP_SHA256@@": _sha256(executor_gzip).encode("ascii"),
            b"@@EXECUTOR_BYTES@@": str(len(executor)).encode("ascii"),
            b"@@EXECUTOR_SHA256@@": _sha256(executor).encode("ascii"),
            b"@@EXECUTOR_GZIP_B85@@": executor_b85,
        },
    )
    _python36_syntax("controller", controller)
    controller_gzip = _compress("controller", controller, gzip_compressor)
    if len(controller) > MAX_BOUND_LAYER_BYTES:
        raise RenderError("controller_size")

    controller_b85 = _b85("controller", controller_gzip)
    wrapper = _render(
        "wrapper",
        templates["wrapper"],
        {
            b"@@CONTROLLER_GZIP_BYTES@@": str(len(controller_gzip)).encode("ascii"),
            b"@@CONTROLLER_GZIP_SHA256@@": _sha256(controller_gzip).encode("ascii"),
            b"@@CONTROLLER_BYTES@@": str(len(controller)).encode("ascii"),
            b"@@CONTROLLER_SHA256@@": _sha256(controller).encode("ascii"),
            b"@@CONTROLLER_GZIP_B85@@": controller_b85,
        },
    )
    _validate_bash_python("wrapper", wrapper, 1)

    readback = _render(
        "readback",
        templates["readback"],
        {
            b"@@TRANSFER_BYTES@@": str(len(transfer_gzip)).encode("ascii"),
            b"@@TRANSFER_SHA256@@": _sha256(transfer_gzip).encode("ascii"),
            b"@@DRIVER_BYTES@@": str(len(driver)).encode("ascii"),
            b"@@DRIVER_SHA256@@": _sha256(driver).encode("ascii"),
        },
    )
    _validate_bash_python("readback", readback, 1)

    command_content = base64.b64encode(wrapper)
    try:
        decoded = base64.b64decode(command_content, validate=True)
    except BaseException as exc:
        raise RenderError("command_content_roundtrip") from exc
    if (
        decoded != wrapper
        or b"\n" in command_content
        or len(command_content) > MAX_COMMAND_CONTENT_BYTES
    ):
        raise RenderError("command_content_limit")

    artifacts = {
        "source": source,
        "driver": driver,
        "transfer_gzip": transfer_gzip,
        "executor": executor,
        "executor_gzip": executor_gzip,
        "controller": controller,
        "controller_gzip": controller_gzip,
        "wrapper": wrapper,
        "readback": readback,
    }
    if set(artifacts) != set(SUMMARY_LAYER_NAMES):
        raise RenderError("artifact_contract")
    sizing = {name: _layer(artifacts[name]) for name in SUMMARY_LAYER_NAMES}
    sizing["command_content"] = {
        "base64": command_content.decode("ascii"),
        "bytes": len(command_content),
        "sha256": _sha256(command_content),
    }
    return {"artifacts": artifacts, "sizing": sizing}


def _render_item26_v3_transport_for_test(
    envelope_bytes: int,
    envelope_sha256: str,
    public_key_sha256: str,
    *,
    gzip_compressor: Callable[[bytes], bytes],
) -> dict[str, object]:
    """Return a result that cannot be mistaken for a production receipt."""

    result = _render_item26_v3_transport_core(
        envelope_bytes,
        envelope_sha256,
        public_key_sha256,
        gzip_compressor=gzip_compressor,
    )
    return {
        "artifacts": result["artifacts"],
        "mode": "TEST_SIZING_ONLY",
        "sizing": result["sizing"],
    }


def render_item26_v3_transport(
    envelope_bytes: int,
    envelope_sha256: str,
    public_key_sha256: str,
) -> dict[str, object]:
    """Render the authoritative Linux/GNU transport and production summary."""

    _validate_public_inputs(envelope_bytes, envelope_sha256, public_key_sha256)
    result = _render_item26_v3_transport_core(
        envelope_bytes,
        envelope_sha256,
        public_key_sha256,
        gzip_compressor=_production_gzip_compressor(),
    )
    summary = dict(result["sizing"])
    summary["production_provenance"] = _production_provenance_summary()
    summary["public_bindings"] = {
        "envelope_bytes": envelope_bytes,
        "envelope_sha256": envelope_sha256,
        "public_key_sha256": public_key_sha256,
    }
    canonical_summary(summary)
    return {"artifacts": result["artifacts"], "summary": summary}


def canonical_summary(summary: dict[str, object]) -> bytes:
    if set(summary) != SUMMARY_KEYS:
        raise RenderError("summary_contract")
    for name in SUMMARY_LAYER_NAMES:
        value = summary.get(name)
        if (
            type(value) is not dict
            or set(value) != {"bytes", "sha256"}
            or type(value.get("bytes")) is not int
            or value["bytes"] < 1
            or type(value.get("sha256")) is not str
            or HEX64.fullmatch(value["sha256"]) is None
        ):
            raise RenderError("summary_contract")
    command = summary.get("command_content")
    if (
        type(command) is not dict
        or set(command) != {"base64", "bytes", "sha256"}
        or type(command.get("base64")) is not str
        or type(command.get("bytes")) is not int
        or not 1 <= command["bytes"] <= MAX_COMMAND_CONTENT_BYTES
        or len(command["base64"].encode("ascii")) != command["bytes"]
        or type(command.get("sha256")) is not str
        or HEX64.fullmatch(command["sha256"]) is None
    ):
        raise RenderError("summary_contract")
    try:
        command_bytes = command["base64"].encode("ascii")
        decoded_command = base64.b64decode(command_bytes, validate=True)
    except BaseException as exc:
        raise RenderError("summary_contract") from exc
    if (
        _sha256(command_bytes) != command["sha256"]
        or len(decoded_command) != summary["wrapper"]["bytes"]
        or _sha256(decoded_command) != summary["wrapper"]["sha256"]
    ):
        raise RenderError("summary_contract")
    public_bindings = summary.get("public_bindings")
    if (
        type(public_bindings) is not dict
        or set(public_bindings)
        != {"envelope_bytes", "envelope_sha256", "public_key_sha256"}
    ):
        raise RenderError("summary_contract")
    _validate_public_inputs(
        public_bindings.get("envelope_bytes"),
        public_bindings.get("envelope_sha256"),
        public_bindings.get("public_key_sha256"),
    )
    if summary.get("production_provenance") != _production_provenance_summary():
        raise RenderError("summary_contract")
    body = (
        json.dumps(
            summary,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")
    decoded = json.loads(body.decode("ascii"))
    if decoded != summary:
        raise RenderError("summary_canonical")
    return body


def _write_all(file_descriptor: int, payload: bytes) -> bool:
    offset = 0
    try:
        while offset < len(payload):
            written = os.write(file_descriptor, payload[offset:])
            if written <= 0:
                return False
            offset += written
    except BaseException:
        return False
    return True


def _cli(argv: list[str]) -> int:
    try:
        if len(argv) != 3 or re.fullmatch(r"[1-9][0-9]{0,5}", argv[0]) is None:
            raise RenderError("arguments")
        rendered = render_item26_v3_transport(
            int(argv[0]),
            argv[1],
            argv[2],
        )
        body = canonical_summary(rendered["summary"])
    except RenderError as exc:
        error = "ITEM26_V3_RENDER_FAILED:{}\n".format(exc.code).encode("ascii")
        _write_all(2, error)
        return 2
    except BaseException:
        _write_all(2, b"ITEM26_V3_RENDER_FAILED:internal\n")
        return 2
    return 0 if _write_all(1, body) else 2


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
