# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Session Log:** Record all Claude Code work in `CLAUDE_INTERACTIONS.md`.

## Project Overview

Serverless REST API wrapping GnuPG operations on AWS Lambda. Clients upload public keys, list/export/delete them, and request messages encrypted to recipients and signed by the service's private key.

## Build & Deploy Commands

```bash
# Build Lambda Layer (requires Docker)
./scripts/build_layer.sh

# Deploy to AWS
sam deploy \
  --template-file infra/template.yaml \
  --stack-name gnupg-lambda-dev \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --parameter-overrides Environment=dev \
  --resolve-s3

# Run unit tests
pip install python-gnupg boto3 pytest
pytest src/test_handler.py -v

# Run a single test
pytest src/test_handler.py::TestRouting::test_post_keys_success -v

# Smoke test against live endpoint
BASE_URL=https://<id>.execute-api.<region>.amazonaws.com/dev ./scripts/smoke_test.sh

# Run locally with Docker Compose (uses LocalStack for AWS services)
docker-compose up --build

# Smoke test against local
BASE_URL=http://localhost:8080 ./scripts/smoke_test.sh
```

## Architecture

```
Client → API Gateway (HTTP API) → Lambda (Python 3.12 / arm64)
                                       │
                               ┌───────┴────────┐
                               │                │
                          S3 Bucket      Secrets Manager
                      (public keys)    (service private key)
```

**Cold-start bootstrap:**
1. Lambda creates GNUPGHOME in `/tmp/gnupg`
2. Loads service private key from Secrets Manager (or generates 4096-bit RSA if none exists)
3. Re-imports all public keys from S3 to populate the keyring

## Code Structure

- `src/handler.py` - Lambda entry point with HTTP router. Uses singleton `GnuPGService` for warm Lambda reuse. Routes defined in `ROUTES` dict mapping `(method, path)` tuples to handler functions.
- `src/gnupg_service.py` - Core service layer. Manages GNUPGHOME setup, service keypair (via Secrets Manager), public key persistence (via S3), and all GnuPG operations.
- `src/test_handler.py` - Unit tests with mocked `GnuPGService`
- `src/local_server.py` - Flask wrapper for local development (translates HTTP to Lambda events)
- `infra/template.yaml` - SAM/CloudFormation template defining S3 bucket, Secrets Manager secret, IAM role, Lambda Layer, Lambda function, and HTTP API

## Key Patterns

**Service singleton**: `_get_service()` in handler.py returns a singleton `GnuPGService` instance, initialized once per Lambda container for warm reuse.

**Custom exceptions**: `GnuPGError`, `KeyNotFoundError`, `InvalidKeyError` in gnupg_service.py map to HTTP 400/404/500 responses.

**S3 key naming**: Public keys stored as `public-keys/{FINGERPRINT}.asc` (uppercase fingerprint).

**Fingerprint validation**: 8-40 hex character regex validation in handler route functions.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `KEY_BUCKET` | S3 bucket for public keys |
| `SERVICE_KEY_SECRET_ARN` | Secrets Manager ARN for service keypair |
| `GNUPGHOME` | GPG home directory (default: `/tmp/gnupg`) |
| `SERVICE_KEY_ID` | Optional pre-existing service key fingerprint |
