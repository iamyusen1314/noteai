#!/usr/bin/env python3
"""Pure builder for the future complete Item 26 authority root v2.

The command-line entry point is intentionally inert in this source-only
revision.  Tests and a later explicitly authorized root-custody runner may
pass canonical public PEM bytes directly to :func:`build_authority_root`.
This module never generates, reads, or writes private-key material.
"""

from __future__ import annotations

from typing import Any, Optional

import verify_item26_manual_cost_stop_authority_v2 as authority


def build_authority_root(public_keys: dict[str, bytes]) -> bytes:
    """Return the deterministic canonical public root for three RSA keys."""
    if type(public_keys) is not dict or set(public_keys) != set(
        authority.ROLE_NAMES
    ):
        raise ValueError("manual authority root v2 public key set")
    rows: dict[str, dict[str, Any]] = {}
    for role in authority.ROLE_NAMES:
        key = public_keys[role]
        if type(key) is not bytes:
            raise ValueError("manual authority root v2 public key bytes")
        rows[role] = authority.public_key_row(role, key)
    value = authority.authority_root_document(rows)
    return authority.canonical_bytes(value)


def main(argv: Optional[list[str]] = None) -> int:
    """Fail before argument expansion or file I/O while the root is absent."""
    del argv
    authority._require_finalized()
    raise ValueError("manual authority root v2 command is install-disabled")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_authority_root", "main"]
