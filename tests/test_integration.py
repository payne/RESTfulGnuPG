"""
Integration tests for the GnuPG RESTful Service.

Prerequisites:
    docker compose up -d --build

Run:
    pytest tests/ -v
"""

import pytest


class TestHealth:
    """Health endpoint tests."""

    def test_health_returns_200(self, api):
        resp = api.get("/health")
        assert resp.status_code == 200

    def test_health_returns_healthy_status(self, api):
        resp = api.get("/health")
        data = resp.json()
        assert data["status"] == "healthy"


class TestServicePublicKey:
    """Service public key endpoint tests."""

    def test_get_service_pubkey_returns_200(self, api):
        resp = api.get("/service/pubkey")
        assert resp.status_code == 200

    def test_get_service_pubkey_contains_fingerprint(self, api):
        resp = api.get("/service/pubkey")
        data = resp.json()
        assert "fingerprint" in data
        assert len(data["fingerprint"]) == 40  # Full fingerprint

    def test_get_service_pubkey_contains_armored_key(self, api):
        resp = api.get("/service/pubkey")
        data = resp.json()
        assert "armored_key" in data
        assert data["armored_key"].startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----")


class TestKeyImport:
    """Key import endpoint tests."""

    def test_import_key_returns_201(self, api, test_key):
        resp = api.post("/keys", json={"key": test_key["public_key"]})
        assert resp.status_code == 201

        # Cleanup
        api.delete(f"/keys/{test_key['fingerprint']}")

    def test_import_key_returns_imported_count(self, api, test_key):
        resp = api.post("/keys", json={"key": test_key["public_key"]})
        data = resp.json()
        assert data["imported"] >= 1

        # Cleanup
        api.delete(f"/keys/{test_key['fingerprint']}")

    def test_import_key_returns_key_metadata(self, api, test_key):
        resp = api.post("/keys", json={"key": test_key["public_key"]})
        data = resp.json()
        assert "keys" in data
        assert len(data["keys"]) >= 1
        assert "fingerprint" in data["keys"][0]

        # Cleanup
        api.delete(f"/keys/{test_key['fingerprint']}")

    def test_import_key_missing_key_field_returns_400(self, api):
        resp = api.post("/keys", json={})
        assert resp.status_code == 400

    def test_import_key_invalid_key_returns_400(self, api):
        resp = api.post("/keys", json={"key": "not a valid key"})
        assert resp.status_code == 400


class TestKeyList:
    """Key listing endpoint tests."""

    def test_list_keys_returns_200(self, api):
        resp = api.get("/keys")
        assert resp.status_code == 200

    def test_list_keys_returns_count(self, api):
        resp = api.get("/keys")
        data = resp.json()
        assert "count" in data
        assert "keys" in data
        assert isinstance(data["keys"], list)

    def test_list_keys_includes_imported_key(self, api, test_key):
        # Import key first
        api.post("/keys", json={"key": test_key["public_key"]})

        resp = api.get("/keys")
        data = resp.json()
        fingerprints = [k["fingerprint"] for k in data["keys"]]
        assert test_key["fingerprint"] in fingerprints

        # Cleanup
        api.delete(f"/keys/{test_key['fingerprint']}")


class TestKeyExport:
    """Key export endpoint tests."""

    def test_export_key_returns_200(self, api, test_key):
        # Import key first
        api.post("/keys", json={"key": test_key["public_key"]})

        resp = api.get(f"/keys/{test_key['fingerprint']}")
        assert resp.status_code == 200

        # Cleanup
        api.delete(f"/keys/{test_key['fingerprint']}")

    def test_export_key_returns_armored_key(self, api, test_key):
        # Import key first
        api.post("/keys", json={"key": test_key["public_key"]})

        resp = api.get(f"/keys/{test_key['fingerprint']}")
        data = resp.json()
        assert "armored_key" in data
        assert data["armored_key"].startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----")

        # Cleanup
        api.delete(f"/keys/{test_key['fingerprint']}")

    def test_export_key_partial_fingerprint(self, api, test_key):
        # Import key first
        api.post("/keys", json={"key": test_key["public_key"]})

        # Use last 8 characters (key ID)
        key_id = test_key["fingerprint"][-8:]
        resp = api.get(f"/keys/{key_id}")
        assert resp.status_code == 200

        # Cleanup
        api.delete(f"/keys/{test_key['fingerprint']}")

    def test_export_nonexistent_key_returns_404(self, api):
        resp = api.get("/keys/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
        assert resp.status_code == 404

    def test_export_invalid_fingerprint_returns_400(self, api):
        resp = api.get("/keys/invalid!")
        assert resp.status_code == 400


class TestKeyDelete:
    """Key deletion endpoint tests."""

    def test_delete_key_returns_200(self, api, test_key):
        # Import key first
        api.post("/keys", json={"key": test_key["public_key"]})

        resp = api.delete(f"/keys/{test_key['fingerprint']}")
        assert resp.status_code == 200

    def test_delete_key_returns_deleted_true(self, api, test_key):
        # Import key first
        api.post("/keys", json={"key": test_key["public_key"]})

        resp = api.delete(f"/keys/{test_key['fingerprint']}")
        data = resp.json()
        assert data["deleted"] is True

    def test_delete_key_removes_from_list(self, api, test_key):
        # Import key first
        api.post("/keys", json={"key": test_key["public_key"]})

        # Delete it
        api.delete(f"/keys/{test_key['fingerprint']}")

        # Verify it's gone
        resp = api.get("/keys")
        data = resp.json()
        fingerprints = [k["fingerprint"] for k in data["keys"]]
        assert test_key["fingerprint"] not in fingerprints

    def test_delete_nonexistent_key_returns_404(self, api):
        resp = api.delete("/keys/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
        assert resp.status_code == 404


class TestMessageEncryption:
    """Message encryption endpoint tests."""

    def test_encrypt_message_returns_201(self, api, test_key):
        # Import recipient key first
        api.post("/keys", json={"key": test_key["public_key"]})

        resp = api.post("/messages", json={
            "plaintext": "Hello, World!",
            "recipients": [test_key["fingerprint"]]
        })
        assert resp.status_code == 201

        # Cleanup
        api.delete(f"/keys/{test_key['fingerprint']}")

    def test_encrypt_message_returns_ciphertext(self, api, test_key):
        # Import recipient key first
        api.post("/keys", json={"key": test_key["public_key"]})

        resp = api.post("/messages", json={
            "plaintext": "Hello, World!",
            "recipients": [test_key["fingerprint"]]
        })
        data = resp.json()
        assert "ciphertext" in data
        assert data["ciphertext"].startswith("-----BEGIN PGP MESSAGE-----")

        # Cleanup
        api.delete(f"/keys/{test_key['fingerprint']}")

    def test_encrypt_message_includes_signature_info(self, api, test_key):
        # Import recipient key first
        api.post("/keys", json={"key": test_key["public_key"]})

        resp = api.post("/messages", json={
            "plaintext": "Hello, World!",
            "recipients": [test_key["fingerprint"]]
        })
        data = resp.json()
        assert "signed_by" in data
        assert len(data["signed_by"]) == 40  # Full fingerprint

        # Cleanup
        api.delete(f"/keys/{test_key['fingerprint']}")

    def test_encrypt_message_missing_plaintext_returns_400(self, api, test_key):
        resp = api.post("/messages", json={
            "recipients": [test_key["fingerprint"]]
        })
        assert resp.status_code == 400

    def test_encrypt_message_missing_recipients_returns_400(self, api):
        resp = api.post("/messages", json={
            "plaintext": "Hello, World!"
        })
        assert resp.status_code == 400

    def test_encrypt_message_empty_recipients_returns_400(self, api):
        resp = api.post("/messages", json={
            "plaintext": "Hello, World!",
            "recipients": []
        })
        assert resp.status_code == 400

    def test_encrypt_message_nonexistent_recipient_returns_404(self, api):
        resp = api.post("/messages", json={
            "plaintext": "Hello, World!",
            "recipients": ["AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"]
        })
        assert resp.status_code == 404

    def test_encrypt_message_too_many_recipients_returns_400(self, api, test_key):
        # Import recipient key first
        api.post("/keys", json={"key": test_key["public_key"]})

        # Try with 21 recipients (max is 20)
        recipients = [test_key["fingerprint"]] * 21
        resp = api.post("/messages", json={
            "plaintext": "Hello, World!",
            "recipients": recipients
        })
        assert resp.status_code == 400

        # Cleanup
        api.delete(f"/keys/{test_key['fingerprint']}")


class TestUnknownRoutes:
    """Test handling of unknown routes."""

    def test_unknown_route_returns_404(self, api):
        resp = api.get("/unknown")
        assert resp.status_code == 404

    def test_unknown_method_returns_404(self, api):
        resp = api.delete("/health")
        assert resp.status_code == 404
