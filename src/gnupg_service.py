"""
GnuPG service layer.

Responsibilities:
  - Bootstrap a fresh GNUPGHOME in /tmp on cold start
  - Load / generate the service keypair from AWS Secrets Manager
  - Persist imported public keys to / restore them from S3
  - Provide encrypt-and-sign, key import/export/delete operations
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import stat
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

import boto3
import gnupg

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------
class GnuPGError(Exception):
    """Generic GnuPG operation failure."""


class KeyNotFoundError(GnuPGError):
    """Requested key fingerprint does not exist in the keyring."""


class InvalidKeyError(GnuPGError):
    """Supplied key material is invalid or could not be imported."""


# ---------------------------------------------------------------------------
# S3 key-ring persistence helpers
# ---------------------------------------------------------------------------
S3_KEY_PREFIX = "public-keys/"


def _s3_key(fingerprint: str) -> str:
    return f"{S3_KEY_PREFIX}{fingerprint.upper()}.asc"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
@dataclass
class GnuPGService:
    gnupghome: str
    s3_bucket: str
    secret_arn: str
    service_key_id: str  # fingerprint or email; resolved on init

    # resolved at init time
    _gpg: gnupg.GPG = field(init=False, repr=False)
    _service_fingerprint: str = field(init=False, repr=False, default="")
    _s3: Any = field(init=False, repr=False)
    _sm: Any = field(init=False, repr=False)

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------
    def initialize(self) -> None:
        """Bootstrap GNUPGHOME, load the service key, restore public keys."""
        self._s3 = boto3.client("s3")
        self._sm = boto3.client("secretsmanager")

        self._prepare_gnupghome()
        self._gpg = gnupg.GPG(gnupghome=self.gnupghome, use_agent=False)
        self._gpg.encoding = "utf-8"

        self._load_or_create_service_key()
        self._restore_public_keys_from_s3()

        logger.info(
            "GnuPGService ready. Service fingerprint: %s", self._service_fingerprint
        )

    def _prepare_gnupghome(self) -> None:
        os.makedirs(self.gnupghome, mode=0o700, exist_ok=True)
        os.chmod(self.gnupghome, stat.S_IRWXU)

    # ------------------------------------------------------------------
    # Service keypair management
    # ------------------------------------------------------------------
    def _load_or_create_service_key(self) -> None:
        """
        Load the service private key from Secrets Manager.
        If the secret is empty, generate a new keypair and store it.
        """
        secret = self._get_secret()
        if secret.get("private_key") and secret.get("fingerprint"):
            # Import the stored private key
            import_result = self._gpg.import_keys(secret["private_key"])
            if import_result.count == 0:
                raise GnuPGError("Failed to import service private key from Secrets Manager.")
            self._service_fingerprint = secret["fingerprint"]
            logger.info("Loaded service key from Secrets Manager: %s", self._service_fingerprint)
        else:
            logger.info("No service key found — generating a new one.")
            self._service_fingerprint = self._generate_service_key()
            armored = str(self._gpg.export_keys(self._service_fingerprint, secret=True, armor=True, passphrase=""))
            self._store_secret(
                {
                    "fingerprint": self._service_fingerprint,
                    "private_key": armored,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            )

    def _generate_service_key(self) -> str:
        key_input = self._gpg.gen_key_input(
            key_type="RSA",
            key_length=4096,
            subkey_type="RSA",
            subkey_length=4096,
            name_real="GnuPG Lambda Service",
            name_email="service@gnupg-lambda.local",
            name_comment="Auto-generated service key",
            expire_date="2y",
            no_protection=True,       # No passphrase — key lives in Secrets Manager
        )
        key = self._gpg.gen_key(key_input)
        if not key.fingerprint:
            raise GnuPGError(f"Key generation failed: {key.status}")
        return key.fingerprint

    # ------------------------------------------------------------------
    # Secrets Manager helpers
    # ------------------------------------------------------------------
    def _get_secret(self) -> dict:
        try:
            resp = self._sm.get_secret_value(SecretId=self.secret_arn)
            raw = resp.get("SecretString") or "{}"
            return json.loads(raw)
        except self._sm.exceptions.ResourceNotFoundException:
            return {}
        except Exception as exc:
            raise GnuPGError(f"Could not retrieve secret: {exc}") from exc

    def _store_secret(self, data: dict) -> None:
        try:
            self._sm.put_secret_value(
                SecretId=self.secret_arn,
                SecretString=json.dumps(data),
            )
        except Exception as exc:
            raise GnuPGError(f"Could not store secret: {exc}") from exc

    # ------------------------------------------------------------------
    # S3 key persistence
    # ------------------------------------------------------------------
    def _restore_public_keys_from_s3(self) -> None:
        """Re-import all public keys stored in S3 on cold start."""
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.s3_bucket, Prefix=S3_KEY_PREFIX):
            for obj in page.get("Contents", []):
                try:
                    body = self._s3.get_object(Bucket=self.s3_bucket, Key=obj["Key"])["Body"].read()
                    self._gpg.import_keys(body.decode())
                except Exception as exc:
                    logger.warning("Failed to restore key %s: %s", obj["Key"], exc)

    def _persist_key_to_s3(self, fingerprint: str, armored: str) -> None:
        self._s3.put_object(
            Bucket=self.s3_bucket,
            Key=_s3_key(fingerprint),
            Body=armored.encode(),
            ContentType="application/pgp-keys",
        )

    def _delete_key_from_s3(self, fingerprint: str) -> None:
        self._s3.delete_object(Bucket=self.s3_bucket, Key=_s3_key(fingerprint))

    # ------------------------------------------------------------------
    # Public API — key operations
    # ------------------------------------------------------------------
    def import_public_key(self, armored_key: str) -> dict:
        """Import an ASCII-armored public key. Returns metadata."""
        result = self._gpg.import_keys(armored_key)
        if result.count == 0:
            problems = "; ".join(result.problem_reason) if result.problem_reason else "unknown"
            raise InvalidKeyError(f"Key import failed: {problems}")

        imported = []
        for fp in result.fingerprints:
            key_meta = self._key_metadata(fp)
            self._persist_key_to_s3(fp, armored_key)
            imported.append(key_meta)

        return {
            "imported": len(imported),
            "keys": imported,
        }

    def list_public_keys(self) -> list[dict]:
        """List all public keys in the keyring (excluding the service key)."""
        keys = self._gpg.list_keys()
        return [
            self._format_key(k)
            for k in keys
            if k["fingerprint"] != self._service_fingerprint
        ]

    def export_public_key(self, fingerprint: str) -> dict:
        """Export a public key as ASCII armor."""
        normalized = fingerprint.upper()
        armored = str(self._gpg.export_keys(normalized, armor=True))
        if not armored:
            raise KeyNotFoundError(f"Key not found: {fingerprint}")
        meta = self._key_metadata(normalized)
        return {"armored_key": armored, **meta}

    def delete_public_key(self, fingerprint: str) -> None:
        """Remove a public key from the keyring and S3."""
        normalized = fingerprint.upper()
        if normalized == self._service_fingerprint:
            raise GnuPGError("Cannot delete the service signing key.")

        keys = self._gpg.list_keys(keys=normalized)
        if not keys:
            raise KeyNotFoundError(f"Key not found: {fingerprint}")

        result = self._gpg.delete_keys(normalized)
        if str(result) != "ok":
            raise GnuPGError(f"Failed to delete key: {result}")

        try:
            self._delete_key_from_s3(normalized)
        except Exception as exc:
            logger.warning("Could not remove key from S3: %s", exc)

    def get_service_public_key(self) -> dict:
        """Return the service's own public key (for clients to verify signatures)."""
        armored = str(self._gpg.export_keys(self._service_fingerprint, armor=True))
        return {
            "fingerprint": self._service_fingerprint,
            "armored_key": armored,
            "note": "Import this key to verify messages signed by the service.",
        }

    # ------------------------------------------------------------------
    # Public API — message operations
    # ------------------------------------------------------------------
    def encrypt_and_sign(
        self, plaintext: str, recipient_fingerprints: list[str]
    ) -> dict:
        """
        Encrypt `plaintext` to each recipient fingerprint and sign with the
        service private key. Returns the ASCII-armored ciphertext.
        """
        # Validate all recipient keys exist
        normalized_recipients = []
        for fp in recipient_fingerprints:
            fp_up = fp.upper()
            keys = self._gpg.list_keys(keys=fp_up)
            if not keys:
                raise KeyNotFoundError(f"Recipient key not found: {fp}")
            normalized_recipients.append(fp_up)

        encrypted = self._gpg.encrypt(
            data=plaintext,
            recipients=normalized_recipients,
            sign=self._service_fingerprint,
            always_trust=True,
            armor=True,
        )

        if not encrypted.ok:
            raise GnuPGError(f"Encryption failed: {encrypted.status} — {encrypted.stderr}")

        return {
            "ciphertext": str(encrypted),
            "signed_by": self._service_fingerprint,
            "encrypted_for": normalized_recipients,
            "recipient_count": len(normalized_recipients),
            "status": "ok",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _key_metadata(self, fingerprint: str) -> dict:
        keys = self._gpg.list_keys(keys=fingerprint)
        if not keys:
            return {"fingerprint": fingerprint}
        return self._format_key(keys[0])

    @staticmethod
    def _format_key(key: dict) -> dict:
        uids = key.get("uids", [])
        return {
            "fingerprint": key.get("fingerprint", ""),
            "key_id": key.get("keyid", ""),
            "length": key.get("length", ""),
            "algo": key.get("algo", ""),
            "date": key.get("date", ""),
            "expires": key.get("expires", ""),
            "trust": key.get("trust", ""),
            "uids": uids,
        }
