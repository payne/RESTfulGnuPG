"""
Unit tests for the GnuPG Lambda handler routing and response shaping.
The GnuPGService is mocked so no real GPG binary is needed.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from handler import lambda_handler


def _event(method: str, path: str, body: dict | None = None) -> dict:
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "body": json.dumps(body) if body else None,
        "isBase64Encoded": False,
        "pathParameters": {},
        "queryStringParameters": {},
    }


def _mock_service():
    svc = MagicMock()
    svc.import_public_key.return_value = {
        "imported": 1,
        "keys": [{"fingerprint": "ABCD1234" * 5, "uids": ["Test User <test@example.com>"]}],
    }
    svc.list_public_keys.return_value = [
        {"fingerprint": "ABCD1234" * 5, "uids": ["Test User <test@example.com>"]}
    ]
    svc.export_public_key.return_value = {
        "fingerprint": "ABCD1234ABCD1234ABCD1234ABCD1234ABCD1234",
        "armored_key": "-----BEGIN PGP PUBLIC KEY BLOCK-----\n...",
    }
    svc.delete_public_key.return_value = None
    svc.encrypt_and_sign.return_value = {
        "ciphertext": "-----BEGIN PGP MESSAGE-----\n...",
        "signed_by": "SERVICEKEY00000000000000000000000000000001",
        "encrypted_for": ["ABCD1234ABCD1234ABCD1234ABCD1234ABCD1234"],
        "recipient_count": 1,
        "status": "ok",
    }
    svc.get_service_public_key.return_value = {
        "fingerprint": "SERVICEKEY00000000000000000000000000000001",
        "armored_key": "-----BEGIN PGP PUBLIC KEY BLOCK-----\n...",
    }
    return svc


FINGERPRINT = "ABCD1234ABCD1234ABCD1234ABCD1234ABCD1234"


class TestRouting(unittest.TestCase):

    def setUp(self):
        self.svc = _mock_service()
        self.patcher = patch("handler._get_service", return_value=self.svc)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    # --- /keys -----------------------------------------------------------

    def test_post_keys_success(self):
        resp = lambda_handler(_event("POST", "/keys", {"key": "-----BEGIN PGP PUBLIC KEY BLOCK-----\n..."}), None)
        self.assertEqual(resp["statusCode"], 201)
        body = json.loads(resp["body"])
        self.assertIn("keys", body)

    def test_post_keys_missing_key(self):
        resp = lambda_handler(_event("POST", "/keys", {}), None)
        self.assertEqual(resp["statusCode"], 400)

    def test_get_keys(self):
        resp = lambda_handler(_event("GET", "/keys"), None)
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertIn("keys", body)
        self.assertEqual(body["count"], 1)

    def test_get_key_by_fingerprint(self):
        resp = lambda_handler(_event("GET", f"/keys/{FINGERPRINT}"), None)
        self.assertEqual(resp["statusCode"], 200)
        self.svc.export_public_key.assert_called_once_with(FINGERPRINT)

    def test_get_key_invalid_fingerprint(self):
        # Route matches but handler rejects the non-hex characters → 400
        resp = lambda_handler(_event("GET", "/keys/not-valid!"), None)
        self.assertIn(resp["statusCode"], (400, 404))

    def test_delete_key(self):
        resp = lambda_handler(_event("DELETE", f"/keys/{FINGERPRINT}"), None)
        self.assertEqual(resp["statusCode"], 200)
        self.svc.delete_public_key.assert_called_once_with(FINGERPRINT)

    # --- /messages -------------------------------------------------------

    def test_post_message_success(self):
        resp = lambda_handler(
            _event("POST", "/messages", {"plaintext": "Hello!", "recipients": [FINGERPRINT]}),
            None,
        )
        self.assertEqual(resp["statusCode"], 201)
        body = json.loads(resp["body"])
        self.assertIn("ciphertext", body)

    def test_post_message_missing_plaintext(self):
        resp = lambda_handler(
            _event("POST", "/messages", {"recipients": [FINGERPRINT]}),
            None,
        )
        self.assertEqual(resp["statusCode"], 400)

    def test_post_message_missing_recipients(self):
        resp = lambda_handler(
            _event("POST", "/messages", {"plaintext": "Hello!"}),
            None,
        )
        self.assertEqual(resp["statusCode"], 400)

    def test_post_message_too_many_recipients(self):
        resp = lambda_handler(
            _event("POST", "/messages", {"plaintext": "Hi", "recipients": ["AA" * 20] * 21}),
            None,
        )
        self.assertEqual(resp["statusCode"], 400)

    # --- /service/pubkey -------------------------------------------------

    def test_get_service_pubkey(self):
        resp = lambda_handler(_event("GET", "/service/pubkey"), None)
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertIn("fingerprint", body)
        self.assertIn("armored_key", body)

    # --- /health ---------------------------------------------------------

    def test_health(self):
        resp = lambda_handler(_event("GET", "/health"), None)
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertEqual(body["status"], "healthy")

    # --- 404 -------------------------------------------------------------

    def test_unknown_route(self):
        resp = lambda_handler(_event("GET", "/unknown"), None)
        self.assertEqual(resp["statusCode"], 404)


if __name__ == "__main__":
    unittest.main()
