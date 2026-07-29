#!/usr/bin/env python3
"""Small hybrid envelope for protected cross-node task payloads."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


SCHEMA_VERSION = 1
ASSOCIATED_DATA = b"noteai-managed-secrets-v1"


class SecretEnvelopeError(RuntimeError):
    """Fixed envelope error which never contains protected values."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def encrypt_payload(payload: bytes, public_key_path: Path) -> bytes:
    try:
        public_key = serialization.load_pem_public_key(
            public_key_path.read_bytes()
        )
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise SecretEnvelopeError("public_key_type")
        data_key = os.urandom(32)
        nonce = os.urandom(12)
        ciphertext = AESGCM(data_key).encrypt(
            nonce,
            payload,
            ASSOCIATED_DATA,
        )
        wrapped_key = public_key.encrypt(
            data_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=ASSOCIATED_DATA,
            ),
        )
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "algorithm": "RSA-OAEP-SHA256+AES-256-GCM",
            "wrapped_key": base64.b64encode(wrapped_key).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        return json.dumps(
            envelope,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except SecretEnvelopeError:
        raise
    except BaseException as exc:
        raise SecretEnvelopeError("encrypt_failed") from exc


def decrypt_payload(envelope_bytes: bytes, private_key_path: Path) -> bytes:
    try:
        envelope = json.loads(envelope_bytes)
        if (
            not isinstance(envelope, dict)
            or envelope.get("schema_version") != SCHEMA_VERSION
            or envelope.get("algorithm")
            != "RSA-OAEP-SHA256+AES-256-GCM"
            or set(envelope)
            != {
                "schema_version",
                "algorithm",
                "wrapped_key",
                "nonce",
                "ciphertext",
            }
        ):
            raise SecretEnvelopeError("envelope_shape")
        private_key = serialization.load_pem_private_key(
            private_key_path.read_bytes(),
            password=None,
        )
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise SecretEnvelopeError("private_key_type")
        data_key = private_key.decrypt(
            base64.b64decode(envelope["wrapped_key"], validate=True),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=ASSOCIATED_DATA,
            ),
        )
        if len(data_key) != 32:
            raise SecretEnvelopeError("data_key")
        return AESGCM(data_key).decrypt(
            base64.b64decode(envelope["nonce"], validate=True),
            base64.b64decode(envelope["ciphertext"], validate=True),
            ASSOCIATED_DATA,
        )
    except SecretEnvelopeError:
        raise
    except BaseException as exc:
        raise SecretEnvelopeError("decrypt_failed") from exc
