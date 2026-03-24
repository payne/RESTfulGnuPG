# GnuPG RESTful Service — AWS Lambda

A serverless REST API that wraps GnuPG operations.  
Clients can upload public keys, list or export them, and request test messages that are simultaneously **encrypted** to one or more recipient keys and **signed** by the service's own private key.

---

## Architecture

```
Client  ──►  API Gateway (HTTP API)  ──►  Lambda (Python 3.12 / arm64)
                                              │
                                    ┌─────────┴──────────┐
                                    │                    │
                               S3 Bucket          Secrets Manager
                           (public keys .asc)   (service private key)
```

### Cold-start bootstrap
1. Lambda creates a fresh `GNUPGHOME` in `/tmp/gnupg`.
2. It reads the service private key from **Secrets Manager**. If none exists yet, it generates a 4096-bit RSA keypair and stores it automatically.
3. All previously uploaded public keys are re-imported from **S3** so the keyring is fully populated.

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/keys` | Import an ASCII-armored public key |
| `GET` | `/keys` | List all imported public keys |
| `GET` | `/keys/{fingerprint}` | Export a specific public key |
| `DELETE` | `/keys/{fingerprint}` | Remove a public key |
| `POST` | `/messages` | Encrypt + sign a test message |
| `GET` | `/service/pubkey` | Return the service's own public key |
| `GET` | `/health` | Liveness check |

### `POST /keys`
```json
Request:
{
  "key": "-----BEGIN PGP PUBLIC KEY BLOCK-----\n..."
}

Response 201:
{
  "imported": 1,
  "keys": [
    {
      "fingerprint": "ABCD1234...",
      "key_id": "ABCD1234",
      "uids": ["Alice <alice@example.com>"],
      "length": "4096",
      "algo": "17",
      "date": "1700000000",
      "expires": "",
      "trust": "-"
    }
  ]
}
```

### `POST /messages`
```json
Request:
{
  "plaintext": "This is a confidential test message.",
  "recipients": [
    "ABCD1234ABCD1234ABCD1234ABCD1234ABCD1234",
    "EFGH5678EFGH5678EFGH5678EFGH5678EFGH5678"
  ]
}

Response 201:
{
  "ciphertext": "-----BEGIN PGP MESSAGE-----\n...",
  "signed_by":  "SERVICEKEY000000000000000000000000000001",
  "encrypted_for": ["ABCD1234...", "EFGH5678..."],
  "recipient_count": 2,
  "status": "ok"
}
```

Recipients must have been previously imported via `POST /keys`.  
Maximum 20 recipients per message.

### `GET /service/pubkey`
Returns the service's own public key.  
Clients should import this key locally so they can verify the signature on messages.

```json
{
  "fingerprint": "SERVICEKEY000000000000000000000000000001",
  "armored_key": "-----BEGIN PGP PUBLIC KEY BLOCK-----\n...",
  "note": "Import this key to verify messages signed by the service."
}
```

---

## Project layout

```
gnupg-lambda/
├── src/
│   ├── handler.py          # Lambda entry point + HTTP router
│   ├── gnupg_service.py    # GnuPG operations + AWS integration
│   └── requirements.txt
├── tests/
│   └── test_handler.py     # Unit tests (mocked service)
├── infra/
│   └── template.yaml       # AWS SAM / CloudFormation template
├── layer/                  # Built by build_layer.sh (git-ignored)
│   └── gnupg-layer.zip
└── scripts/
    ├── build_layer.sh      # Builds the Lambda Layer (Docker-based)
    └── smoke_test.sh       # End-to-end smoke tests against a live endpoint
```

---

## Deployment

### Prerequisites
- AWS CLI configured
- AWS SAM CLI (`pip install aws-sam-cli`)
- Docker (for building the Lambda Layer)

### Step 1 — Build the Lambda Layer

The layer packages the `gpg` binary (compiled for Amazon Linux 2023 arm64) and `python-gnupg`:

```bash
chmod +x scripts/build_layer.sh
./scripts/build_layer.sh          # uses Docker
```

This produces `layer/gnupg-layer.zip`.

### Step 2 — Deploy

```bash
sam deploy \
  --template-file infra/template.yaml \
  --stack-name gnupg-lambda-dev \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --parameter-overrides Environment=dev \
  --resolve-s3
```

SAM will output the API endpoint URL on completion.

### Step 3 — Smoke test

```bash
BASE_URL=https://<id>.execute-api.<region>.amazonaws.com/dev \
  ./scripts/smoke_test.sh
```

---

## Running tests locally

```bash
pip install python-gnupg boto3 pytest
pytest tests/ -v
```

---

## Security considerations

| Concern | Mitigation |
|---------|------------|
| Service private key exposure | Stored in Secrets Manager, never logged or returned via API |
| No passphrase on service key | Key material lives only in Secrets Manager; access controlled by IAM |
| Recipient key trust | `always_trust=True` is set deliberately (test service); for production, implement a trust policy |
| API authentication | Template ships with auth disabled; add a JWT authorizer or API key before production use |
| Input validation | Fingerprints validated as 8–40 hex chars; recipient list capped at 20 |
| S3 bucket | Private, versioned, KMS-encrypted, no public access |
| Lambda ephemeral storage | `/tmp/gnupg` is isolated per execution environment |

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `KEY_BUCKET` | ✅ | S3 bucket name for public key storage |
| `SERVICE_KEY_SECRET_ARN` | ✅ | Secrets Manager ARN for the service keypair |
| `GNUPGHOME` | ✅ | GPG home directory (default: `/tmp/gnupg`) |
| `SERVICE_KEY_ID` | optional | Pre-existing service key fingerprint |
| `LOG_LEVEL` | optional | Python log level (default: `INFO`) |
