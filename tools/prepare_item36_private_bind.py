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


def render_private_bind(unit: bytes, *, expected_sha256: str, private_ip: str) -> tuple[bytes, bytes]:
    """Return candidate and untouched rollback bytes for one exact API unit."""
    if (
        not 0 < len(unit) <= 65536
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        or hashlib.sha256(unit).hexdigest() != expected_sha256
    ):
        raise ValueError("unit_source_binding")
    try:
        address = ipaddress.IPv4Address(private_ip)
    except ipaddress.AddressValueError:
        raise ValueError("private_ipv4_required") from None
    if str(address) != private_ip or not any(address in network for network in RFC1918):
        raise ValueError("private_ipv4_required")
    text = unit.decode("utf-8", errors="strict")
    if "\x00" in text or "\r" in text:
        raise ValueError("unit_encoding")
    starts = [line for line in text.splitlines() if line.startswith("ExecStart=")]
    if len(starts) != 1 or not starts[0].startswith("ExecStart=/usr/bin/docker run "):
        raise ValueError("single_docker_execstart_required")
    command = starts[0]
    # Only the existing literal mapping changes; no shell expansion or
    # multiline command rewriting is attempted.
    if any(value in command for value in ("\\", "$", "`", ";", "&&", "||")):
        raise ValueError("literal_execstart_required")
    bindings = re.findall(r"(?:^|\s)(?:-p\s+|--publish(?:=|\s+))(\S+)", command)
    if bindings != ["127.0.0.1:8000:8000"]:
        raise ValueError("single_loopback_api_binding_required")
    if re.search(r"(?:^|\s)(?:-P|--publish-all|--network[= ]host|--privileged)(?:\s|$)", command):
        raise ValueError("unsafe_network_scope")
    if re.search(r"\S+@sha256:[0-9a-f]{64}$", command) is None:
        raise ValueError("immutable_image_required")
    replacement = command.replace("127.0.0.1:8000:8000", f"{private_ip}:8000:8000", 1)
    return text.replace(command, replacement, 1).encode("utf-8"), unit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--private-ip", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.unit.is_symlink():
        parser.error("unit must be a regular reviewed local file")
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
