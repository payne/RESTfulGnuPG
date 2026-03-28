#!/bin/bash
# Initialize LocalStack resources for local development

set -e

echo "Creating S3 bucket..."
awslocal s3 mb s3://gnupg-lambda-keys-local

echo "Creating Secrets Manager secret..."
awslocal secretsmanager create-secret \
    --name gnupg-lambda/service-key/local \
    --secret-string '{}' \
    || echo "Secret may already exist, continuing..."

echo "LocalStack initialization complete."
