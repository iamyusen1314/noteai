#!/usr/bin/env python3
"""Render a bounded API unit change and byte-exact rollback, without applying it.

No cloud SDK, subprocess, environment, database or service access is used.
The input must be a separately reviewed, Secret-free copy of the current unit.
This preparation produces no terminal Evidence or readiness credit.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import re
from pathlib import Path


RFC1918 = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"
))
IMMUTABLE_IMAGE = re.compile(
    r"[a-z0-9][a-z0-9.-]*(?::[0-9]+)?/"
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"
    r"@sha256:[0-9a-f]{64}"
)
_VALUE_OPTIONS = frozenset({
    "--pull", "--name", "--label", "--user", "--cap-drop", "--security-opt",
    "--network", "--net", "--ipc", "--memory", "--cpus", "--pids-limit",
    "--tmpfs", "--mount", "--volume", "--env-file", "--env", "--log-driver",
    "--log-opt", "--restart", "--publish", "--ulimit", "--stop-timeout",
})
_BOOLEAN_OPTIONS = frozenset({"--rm", "--read-only", "--init"})


def _docker_argument_spans(command: str):
    """Parse only the reviewed literal API run options, never an application argv."""
    tokens = list(re.finditer(r"\S+", command))
    bindings = []
    index = 2  # ExecStart=/usr/bin/docker run
    while index < len(tokens):
        token = tokens[index]
        word = token.group()
        if not word.startswith("-"):
            if index != len(tokens) - 1 or IMMUTABLE_IMAGE.fullmatch(word) is None:
                raise ValueError("single_final_image_argument_required")
            return bindings
        option, separator, value = word.partition("=")
        begin = token.start() + len(option) + 1
        end = token.end()
        if word.startswith("-p") and not word.startswith("--"):
            option, value = "--publish", word[2:]
            separator = "=" if value else ""
            begin = token.start() + 2
        if option in _BOOLEAN_OPTIONS:
            if separator and value not in {"true", "false"}:
                raise ValueError("literal_docker_option_required")
            index += 1
            continue
        if option not in _VALUE_OPTIONS:
            raise ValueError("unsupported_docker_option")
        if not separator:
            index += 1
            if index >= len(tokens) or tokens[index].group().startswith("-"):
                raise ValueError("docker_option_value_required")
            value = tokens[index].group()
            begin, end = tokens[index].span()
        if not value:
            raise ValueError("docker_option_value_required")
        if option in {"--network", "--net"} and value != "bridge":
            raise ValueError("unsafe_network_scope")
        if option == "--publish":
            bindings.append((value, begin, end))
        index += 1
    raise ValueError("immutable_image_required")


def _literal_api_unit(unit: bytes, expected_sha256: str):
    if (
        not 0 < len(unit) <= 65536
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        or hashlib.sha256(unit).hexdigest() != expected_sha256
    ):
        raise ValueError("unit_source_binding")
    text = unit.decode("utf-8", errors="strict")
    if "\x00" in text or "\r" in text:
        raise ValueError("unit_encoding")
    starts = list(re.finditer(r"^ExecStart=[^\n]*$", text, re.MULTILINE))
    if len(starts) != 1 or not starts[0].group().startswith("ExecStart=/usr/bin/docker run "):
        raise ValueError("single_docker_execstart_required")
    command = starts[0].group()
    # Only the existing literal mapping changes; no shell expansion or
    # multiline command rewriting is attempted.
    if any(value in command for value in ("\\", "$", "`", ";", "&&", "||", "'", '"')):
        raise ValueError("literal_execstart_required")
    bindings = _docker_argument_spans(command)
    return text, starts[0], command, bindings


def _private_address(private_ip: str) -> None:
    try:
        address = ipaddress.IPv4Address(private_ip)
    except ipaddress.AddressValueError:
        raise ValueError("private_ipv4_required") from None
    if str(address) != private_ip or not any(address in network for network in RFC1918):
        raise ValueError("private_ipv4_required")


def render_private_bind(unit: bytes, *, expected_sha256: str, private_ip: str) -> tuple[bytes, bytes]:
    """Return candidate and untouched rollback bytes for one exact API unit."""
    text, start, command, bindings = _literal_api_unit(unit, expected_sha256)
    _private_address(private_ip)
    if [binding[0] for binding in bindings] != ["127.0.0.1:8000:8000"]:
        raise ValueError("single_loopback_api_binding_required")
    _value, begin, end = bindings[0]
    replacement = command[:begin] + f"{private_ip}:8000:8000" + command[end:]
    return (text[:start.start()] + replacement + text[start.end():]).encode("utf-8"), unit


def render_image_update(
    unit: bytes, *, expected_sha256: str, expected_image: str, candidate_image: str,
) -> tuple[bytes, bytes]:
    """Replace only the reviewed final image argument; preserve its private bind."""
    text, start, command, bindings = _literal_api_unit(unit, expected_sha256)
    if any(IMMUTABLE_IMAGE.fullmatch(image) is None for image in (expected_image, candidate_image)):
        raise ValueError("immutable_image_required")
    if command.rsplit(" ", 1)[-1] != expected_image:
        raise ValueError("image_source_binding")
    if expected_image == candidate_image:
        raise ValueError("candidate_image_unchanged")
    if len(bindings) != 1 or not bindings[0][0].endswith(":8000:8000"):
        raise ValueError("single_private_api_binding_required")
    address = bindings[0][0][:-len(":8000:8000")]
    if address != "127.0.0.1":
        _private_address(address)
    replacement = command[:-len(expected_image)] + candidate_image
    return (text[:start.start()] + replacement + text[start.end():]).encode("utf-8"), unit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--private-ip")
    mode.add_argument("--candidate-image")
    parser.add_argument("--expected-image")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.unit.is_symlink():
        parser.error("unit must be a regular reviewed local file")
    if args.candidate_image:
        if not args.expected_image:
            parser.error("--expected-image is required for an image update")
        candidate, rollback = render_image_update(
            args.unit.read_bytes(), expected_sha256=args.expected_sha256,
            expected_image=args.expected_image, candidate_image=args.candidate_image,
        )
    else:
        if args.expected_image:
            parser.error("--expected-image applies only to an image update")
        candidate, rollback = render_private_bind(
            args.unit.read_bytes(), expected_sha256=args.expected_sha256, private_ip=args.private_ip
        )
    # Exclusive directory creation avoids overwriting a prior recovery package.
    args.output_dir.mkdir(mode=0o700)
    for name, payload in (
        ("noteai-api.service.candidate", candidate),
        ("noteai-api.service.rollback", rollback),
    ):
        path = args.output_dir / name
        with path.open("xb") as output:
            output.write(payload)
        path.chmod(0o600)
    print("PREPARED_NOT_APPLIED readiness_credit=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
