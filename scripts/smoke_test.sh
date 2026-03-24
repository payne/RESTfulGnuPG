#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# smoke_test.sh — end-to-end smoke test against a running API endpoint
#
# Usage:
#   BASE_URL=https://abc123.execute-api.us-east-1.amazonaws.com/dev \
#   ./scripts/smoke_test.sh
#
# Or against sam local:
#   BASE_URL=http://localhost:3000 ./scripts/smoke_test.sh
# ---------------------------------------------------------------------------
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:3000}"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
pass() { echo -e "${GREEN}✔ $1${NC}"; }
fail() { echo -e "${RED}✘ $1${NC}"; exit 1; }
info() { echo -e "${YELLOW}► $1${NC}"; }

info "Target: $BASE_URL"

# ---------------------------------------------------------------------------
# 1. Health check
# ---------------------------------------------------------------------------
info "1. GET /health"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health")
[ "$STATUS" = "200" ] && pass "Health check" || fail "Health returned $STATUS"

# ---------------------------------------------------------------------------
# 2. Get service public key
# ---------------------------------------------------------------------------
info "2. GET /service/pubkey"
SVC_RESP=$(curl -sf "$BASE_URL/service/pubkey")
SVC_FP=$(echo "$SVC_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['fingerprint'])")
SVC_KEY=$(echo "$SVC_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['armored_key'])")
[ -n "$SVC_FP" ] && pass "Service fingerprint: $SVC_FP" || fail "No fingerprint returned"

# Import service key into local test keyring
export GNUPGHOME="$TMPDIR/testgpg"
mkdir -p -m 700 "$GNUPGHOME"
echo "$SVC_KEY" | gpg --import --quiet 2>/dev/null || true

# ---------------------------------------------------------------------------
# 3. Generate a test keypair and upload it
# ---------------------------------------------------------------------------
info "3. Generate test recipient keypair"
gpg --batch --gen-key --quiet 2>/dev/null <<EOF
Key-Type: RSA
Key-Length: 2048
Name-Real: Smoke Test User
Name-Email: smoke@test.local
Expire-Date: 1y
%no-protection
%commit
EOF

TEST_FP=$(gpg --list-keys --with-colons smoke@test.local 2>/dev/null \
          | awk -F: '/^fpr/ { print $10; exit }')
TEST_KEY=$(gpg --armor --export "$TEST_FP" 2>/dev/null)
[ -n "$TEST_FP" ] && pass "Test key generated: $TEST_FP" || fail "Key generation failed"

info "4. POST /keys — upload test public key"
IMPORT_RESP=$(curl -sf -X POST "$BASE_URL/keys" \
  -H "Content-Type: application/json" \
  -d "$(python3 -c "import json,sys; print(json.dumps({'key':sys.stdin.read()}))" <<< "$TEST_KEY")")
IMPORTED=$(echo "$IMPORT_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['imported'])")
[ "$IMPORTED" -ge 1 ] && pass "Key imported (count=$IMPORTED)" || fail "Import failed: $IMPORT_RESP"

# ---------------------------------------------------------------------------
# 5. List keys
# ---------------------------------------------------------------------------
info "5. GET /keys"
LIST_RESP=$(curl -sf "$BASE_URL/keys")
COUNT=$(echo "$LIST_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])")
[ "$COUNT" -ge 1 ] && pass "Key list returned $COUNT key(s)" || fail "No keys listed"

# ---------------------------------------------------------------------------
# 6. Get key by fingerprint
# ---------------------------------------------------------------------------
info "6. GET /keys/$TEST_FP"
GET_RESP=$(curl -sf "$BASE_URL/keys/$TEST_FP")
RETURNED_FP=$(echo "$GET_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['fingerprint'])")
[ "$RETURNED_FP" = "$TEST_FP" ] && pass "Key retrieved by fingerprint" \
  || fail "Fingerprint mismatch: $RETURNED_FP"

# ---------------------------------------------------------------------------
# 7. Encrypt + sign a message
# ---------------------------------------------------------------------------
info "7. POST /messages — encrypt to test key, sign with service key"
MSG_RESP=$(curl -sf -X POST "$BASE_URL/messages" \
  -H "Content-Type: application/json" \
  -d "{\"plaintext\":\"Hello from smoke test $(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"recipients\":[\"$TEST_FP\"]}")

CIPHERTEXT=$(echo "$MSG_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['ciphertext'])")
SIGNED_BY=$(echo "$MSG_RESP"  | python3 -c "import sys,json; print(json.load(sys.stdin)['signed_by'])")

[ -n "$CIPHERTEXT" ] && pass "Got ciphertext (signed by $SIGNED_BY)" || fail "No ciphertext"

# ---------------------------------------------------------------------------
# 8. Decrypt the message locally and verify signature
# ---------------------------------------------------------------------------
info "8. Decrypt and verify signature locally"
echo "$CIPHERTEXT" | gpg --decrypt --quiet 2>/tmp/gpg_verify_out \
  && VERIFY_OUT=$(cat /tmp/gpg_verify_out)

if echo "$VERIFY_OUT" | grep -q "Good signature"; then
  pass "Signature verified: $(echo "$VERIFY_OUT" | grep 'Good signature')"
else
  fail "Signature verification failed: $VERIFY_OUT"
fi

# ---------------------------------------------------------------------------
# 9. Delete the test key
# ---------------------------------------------------------------------------
info "9. DELETE /keys/$TEST_FP"
DEL_RESP=$(curl -sf -X DELETE "$BASE_URL/keys/$TEST_FP")
DELETED=$(echo "$DEL_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['deleted'])")
[ "$DELETED" = "True" ] && pass "Key deleted" || fail "Delete failed: $DEL_RESP"

# ---------------------------------------------------------------------------
echo ""
pass "All smoke tests passed ✓"
