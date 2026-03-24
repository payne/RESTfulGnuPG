"""
GnuPG RESTful Service — AWS Lambda Handler
Routes HTTP API Gateway v2 requests to service operations.
"""

import json
import logging
import os
import re
import traceback
from typing import Any

from gnupg_service import GnuPGService, GnuPGError, KeyNotFoundError, InvalidKeyError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Singleton service (warm Lambda reuse)
# ---------------------------------------------------------------------------
_service: GnuPGService | None = None


def _get_service() -> GnuPGService:
    global _service
    if _service is None:
        _service = GnuPGService(
            gnupghome=os.environ.get("GNUPGHOME", "/tmp/gnupg"),
            s3_bucket=os.environ["KEY_BUCKET"],
            secret_arn=os.environ["SERVICE_KEY_SECRET_ARN"],
            service_key_id=os.environ.get("SERVICE_KEY_ID", ""),
        )
        _service.initialize()
    return _service


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------
def _resp(status: int, body: Any, headers: dict | None = None) -> dict:
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    return {
        "statusCode": status,
        "headers": h,
        "body": json.dumps(body, default=str),
    }


def _ok(body: Any) -> dict:
    return _resp(200, body)


def _created(body: Any) -> dict:
    return _resp(201, body)


def _bad(msg: str) -> dict:
    return _resp(400, {"error": msg})


def _not_found(msg: str) -> dict:
    return _resp(404, {"error": msg})


def _server_error(msg: str) -> dict:
    return _resp(500, {"error": msg})


# ---------------------------------------------------------------------------
# Request parsing helpers
# ---------------------------------------------------------------------------
def _body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64
        raw = base64.b64decode(raw).decode()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _path_param(event: dict, name: str) -> str | None:
    return (event.get("pathParameters") or {}).get(name)


def _query_param(event: dict, name: str) -> str | None:
    return (event.get("queryStringParameters") or {}).get(name)


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------
def _post_keys(event: dict, svc: GnuPGService) -> dict:
    """POST /keys — import a public key."""
    data = _body(event)
    armored_key = data.get("key") or data.get("armored_key")
    if not armored_key:
        return _bad("Request body must contain 'key' field with ASCII-armored public key.")

    try:
        result = svc.import_public_key(armored_key)
    except InvalidKeyError as exc:
        return _bad(str(exc))

    return _created(result)


def _get_keys(event: dict, svc: GnuPGService) -> dict:
    """GET /keys — list all imported public keys."""
    keys = svc.list_public_keys()
    return _ok({"keys": keys, "count": len(keys)})


def _get_key(event: dict, svc: GnuPGService) -> dict:
    """GET /keys/{fingerprint} — export a specific public key."""
    fingerprint = _path_param(event, "fingerprint")
    if not fingerprint:
        return _bad("Missing fingerprint path parameter.")

    # Allow partial fingerprints / key IDs (min 8 hex chars)
    if not re.fullmatch(r"[0-9A-Fa-f]{8,40}", fingerprint):
        return _bad("fingerprint must be 8–40 hex characters.")

    try:
        result = svc.export_public_key(fingerprint)
    except KeyNotFoundError as exc:
        return _not_found(str(exc))

    return _ok(result)


def _delete_key(event: dict, svc: GnuPGService) -> dict:
    """DELETE /keys/{fingerprint} — remove a public key."""
    fingerprint = _path_param(event, "fingerprint")
    if not fingerprint:
        return _bad("Missing fingerprint path parameter.")

    if not re.fullmatch(r"[0-9A-Fa-f]{8,40}", fingerprint):
        return _bad("fingerprint must be 8–40 hex characters.")

    try:
        svc.delete_public_key(fingerprint)
    except KeyNotFoundError as exc:
        return _not_found(str(exc))

    return _ok({"deleted": True, "fingerprint": fingerprint.upper()})


def _post_messages(event: dict, svc: GnuPGService) -> dict:
    """POST /messages — encrypt & sign a test message."""
    data = _body(event)

    plaintext = data.get("plaintext")
    if not plaintext:
        return _bad("Request body must contain 'plaintext' field.")

    recipients = data.get("recipients")
    if not recipients or not isinstance(recipients, list):
        return _bad("Request body must contain 'recipients' list of fingerprints.")

    if len(recipients) > 20:
        return _bad("Maximum 20 recipients per message.")

    try:
        result = svc.encrypt_and_sign(plaintext=plaintext, recipient_fingerprints=recipients)
    except KeyNotFoundError as exc:
        return _not_found(str(exc))
    except GnuPGError as exc:
        return _bad(str(exc))

    return _created(result)


def _get_service_pubkey(_event: dict, svc: GnuPGService) -> dict:
    """GET /service/pubkey — return the service's own public key."""
    result = svc.get_service_public_key()
    return _ok(result)


def _get_health(_event: dict, _svc: GnuPGService) -> dict:
    """GET /health — liveness check."""
    return _ok({"status": "healthy"})


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
ROUTES: dict[tuple[str, str], Any] = {
    ("POST",   "/keys"):             _post_keys,
    ("GET",    "/keys"):             _get_keys,
    ("GET",    "/keys/{fingerprint}"): _get_key,
    ("DELETE", "/keys/{fingerprint}"): _delete_key,
    ("POST",   "/messages"):         _post_messages,
    ("GET",    "/service/pubkey"):   _get_service_pubkey,
    ("GET",    "/health"):           _get_health,
}


def _match_route(method: str, path: str):
    """Return (handler, path_params) for the matching route, or (None, {})."""
    for (route_method, route_path), handler in ROUTES.items():
        if route_method != method:
            continue
        # Convert {param} patterns to regex groups
        pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", route_path)
        m = re.fullmatch(pattern, path)
        if m:
            return handler, m.groupdict()
    return None, {}


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------
def lambda_handler(event: dict, _context) -> dict:
    logger.info("Event: %s", json.dumps({k: v for k, v in event.items() if k != "body"}))

    method = (event.get("requestContext", {}).get("http", {}).get("method") or
              event.get("httpMethod", "GET")).upper()
    path   = (event.get("requestContext", {}).get("http", {}).get("path") or
              event.get("path", "/"))

    # Strip stage prefix if present (e.g. /prod/keys → /keys)
    stage = (event.get("requestContext", {}) or {}).get("stage", "")
    if stage and path.startswith(f"/{stage}"):
        path = path[len(f"/{stage}"):]

    handler, path_params = _match_route(method, path)
    if handler is None:
        return _resp(404, {"error": f"No route for {method} {path}"})

    # Inject path params back into the event (API GW v2 style)
    if path_params:
        event.setdefault("pathParameters", {}).update(path_params)

    try:
        svc = _get_service()
        return handler(event, svc)
    except Exception:  # pylint: disable=broad-except
        logger.error("Unhandled exception:\n%s", traceback.format_exc())
        return _server_error("Internal server error.")
