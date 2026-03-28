# Claude Code Interactions

This file records Claude Code sessions and changes made to this repository.

---

## 2026-03-28: Initial Setup

### Created CLAUDE.md

Generated project guidance file for future Claude Code sessions covering:
- Build & deploy commands (layer build, SAM deploy, tests, smoke tests)
- Architecture overview with ASCII diagram
- Code structure and key patterns
- Environment variables reference

### Added Local Development Environment

Created Docker Compose setup for running the service locally without AWS:

**Files created:**
- `docker-compose.yml` - LocalStack + app services
- `Dockerfile.local` - Python 3.12 container with GnuPG
- `requirements.txt` - python-gnupg, boto3, flask
- `src/local_server.py` - Flask wrapper translating HTTP requests to Lambda event format
- `scripts/localstack-init.sh` - Initializes S3 bucket and Secrets Manager secret in LocalStack

**Usage:**
```bash
docker-compose up --build
# API at http://localhost:8080
```

The local server patches boto3 to route AWS calls to LocalStack. Service keypair is auto-generated on first request.

### Added Swagger UI

Added interactive API documentation accessible at http://localhost:8080/docs

**Files created/modified:**
- `src/openapi.yaml` - OpenAPI 3.0 specification with all endpoints, schemas, and examples
- `src/local_server.py` - Added flask-swagger-ui integration
- `requirements.txt` - Added flask-swagger-ui dependency

### Fixed GnuPG 2.1+ Secret Key Export

Fixed `ValueError: For GnuPG >= 2.1, exporting secret keys needs a passphrase to be provided`.

GnuPG 2.1+ requires a passphrase parameter when exporting secret keys, even for keys with no protection. Added `passphrase=""` to the `export_keys()` call in `gnupg_service.py:114`.
