"""
Local development server that wraps the Lambda handler.
Translates Flask requests to Lambda event format.

Swagger UI available at: http://localhost:8080/docs
"""

import json
import os
from flask import Flask, request, Response, send_from_directory
from flask_swagger_ui import get_swaggerui_blueprint

# Patch boto3 to use LocalStack endpoint before importing handler
import boto3

_original_client = boto3.client

def _patched_client(service_name, **kwargs):
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
    if endpoint_url and service_name in ("s3", "secretsmanager"):
        kwargs.setdefault("endpoint_url", endpoint_url)
    return _original_client(service_name, **kwargs)

boto3.client = _patched_client

from handler import lambda_handler

app = Flask(__name__)

# Swagger UI configuration
SWAGGER_URL = '/docs'
API_URL = '/openapi.yaml'
swaggerui_blueprint = get_swaggerui_blueprint(
    SWAGGER_URL,
    API_URL,
    config={'app_name': "GnuPG RESTful Service"}
)
app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)


@app.route('/openapi.yaml')
def openapi_spec():
    """Serve the OpenAPI specification."""
    return send_from_directory(os.path.dirname(__file__), 'openapi.yaml')


def _build_event(path: str) -> dict:
    """Convert Flask request to Lambda HTTP API v2 event format."""
    return {
        "requestContext": {
            "http": {
                "method": request.method,
                "path": path,
            }
        },
        "headers": dict(request.headers),
        "body": request.get_data(as_text=True) or None,
        "isBase64Encoded": False,
        "pathParameters": {},
        "queryStringParameters": dict(request.args) or None,
    }


@app.route("/", defaults={"path": "/"}, methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def proxy(path: str):
    if not path.startswith("/"):
        path = "/" + path

    event = _build_event(path)
    result = lambda_handler(event, None)

    return Response(
        response=result.get("body", ""),
        status=result.get("statusCode", 200),
        headers=result.get("headers", {}),
    )


if __name__ == "__main__":
    print("Starting local GnuPG service on http://localhost:8080")
    print("")
    print("Swagger UI: http://localhost:8080/docs")
    print("")
    print("Endpoints:")
    print("  GET  /health")
    print("  GET  /service/pubkey")
    print("  POST /keys")
    print("  GET  /keys")
    print("  GET  /keys/{fingerprint}")
    print("  DELETE /keys/{fingerprint}")
    print("  POST /messages")
    app.run(host="0.0.0.0", port=8080, debug=True)
