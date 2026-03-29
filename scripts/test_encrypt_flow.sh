#!/bin/bash
set -e

BASE_URL="${BASE_URL:-http://localhost:8080}"

# Create timestamped folder
TIMESTAMP=$(date +%Y%m%d%H%M%S)
WORKDIR="tmp${TIMESTAMP}"
mkdir -p "$WORKDIR"
echo "Created working directory: $WORKDIR"

# Set up GPG home in the working directory
export GNUPGHOME="$WORKDIR/gnupg"
mkdir -p "$GNUPGHOME"
chmod 700 "$GNUPGHOME"

# Step 1: Generate a GPG keypair
echo "Step 1: Generating GPG keypair..."
gpg --batch --gen-key <<EOF
Key-Type: RSA
Key-Length: 2048
Name-Real: Test Client
Name-Email: client@example.local
Expire-Date: 2030-01-01
%no-protection
%commit
EOF

FINGERPRINT=$(gpg --list-keys --with-colons | grep '^fpr' | head -1 | cut -d: -f10)
echo "Generated key with fingerprint: $FINGERPRINT"

# Step 2: Fetch service public key and import it
echo "Step 2: Fetching service public key..."
echo '{"method": "GET", "url": "'"$BASE_URL"'/service/pubkey"}' > "$WORKDIR/step2_request.json"
curl -s "$BASE_URL/service/pubkey" > "$WORKDIR/step2_response.json"

# Extract and import the service public key
SERVICE_KEY=$(jq -r '.armored_key' "$WORKDIR/step2_response.json")
echo "$SERVICE_KEY" | gpg --import
SERVICE_FP=$(jq -r '.fingerprint' "$WORKDIR/step2_response.json")
echo "Imported service key: $SERVICE_FP"

# Step 3: Export our public key and POST it to the service
echo "Step 3: Uploading our public key to the service..."
EXPORTED_KEY=$(gpg --armor --export "$FINGERPRINT")

# Create request JSON
jq -n --arg key "$EXPORTED_KEY" '{"key": $key}' > "$WORKDIR/step3_request.json"
curl -s -X POST "$BASE_URL/keys" \
    -H "Content-Type: application/json" \
    -d @"$WORKDIR/step3_request.json" > "$WORKDIR/step3_response.json"

echo "Upload response:"
cat "$WORKDIR/step3_response.json"
echo

# Step 4: Encrypt a message using the service
echo "Step 4: Encrypting message..."
jq -n --arg fp "$FINGERPRINT" '{"plaintext": "I like eggs.", "recipients": [$fp]}' > "$WORKDIR/step4_request.json"
curl -s -X POST "$BASE_URL/messages" \
    -H "Content-Type: application/json" \
    -d @"$WORKDIR/step4_request.json" > "$WORKDIR/step4_response.json"

echo "Encrypt response:"
cat "$WORKDIR/step4_response.json"
echo

# Extract and save the ciphertext
CIPHERTEXT=$(jq -r '.ciphertext' "$WORKDIR/step4_response.json")
echo "$CIPHERTEXT" > "$WORKDIR/encrypted_message.asc"

# Bonus: Decrypt the message to verify it works
echo
echo "Decrypting message to verify..."
DECRYPTED=$(echo "$CIPHERTEXT" | gpg --decrypt 2>/dev/null)
echo "Decrypted: $DECRYPTED"

echo
echo "All files saved in: $WORKDIR/"
ls -la "$WORKDIR/"
