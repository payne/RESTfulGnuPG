"""
Pytest configuration for integration tests.
Requires: docker compose up -d --build
"""

import pytest
import requests
import time

BASE_URL = "http://localhost:8080"


def wait_for_service(url: str, timeout: int = 30) -> bool:
    """Wait for the service to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{url}/health", timeout=2)
            if resp.status_code == 200:
                return True
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    return False


@pytest.fixture(scope="session", autouse=True)
def ensure_service_running():
    """Ensure the Docker Compose service is running before tests."""
    if not wait_for_service(BASE_URL, timeout=60):
        pytest.exit(
            "Service not available at localhost:8080. "
            "Run 'docker compose up -d --build' first.",
            returncode=1
        )


@pytest.fixture
def api():
    """Provide API helper for making requests."""
    class APIClient:
        def __init__(self, base_url: str):
            self.base_url = base_url

        def get(self, path: str, **kwargs) -> requests.Response:
            return requests.get(f"{self.base_url}{path}", **kwargs)

        def post(self, path: str, **kwargs) -> requests.Response:
            return requests.post(f"{self.base_url}{path}", **kwargs)

        def delete(self, path: str, **kwargs) -> requests.Response:
            return requests.delete(f"{self.base_url}{path}", **kwargs)

    return APIClient(BASE_URL)


# Sample test key (2048-bit RSA, no passphrase, expires 2030)
# Generated specifically for testing - DO NOT use for real encryption
TEST_PUBLIC_KEY = """-----BEGIN PGP PUBLIC KEY BLOCK-----

mQENBGnIY9QBCADQ7mSxBlqnMxXsPLz048UT6aXEb5AnLhQcOOD9mliNHb3TN5E2
4YNar4H1DWsi+9wDVXDrxNkspenmD1RRChPiWCKHaXk5+huNmz+0297XxKUyq0mb
AEcOoZgMR+pNvXBLVWgTxFnOHIk3ptyDvLRvxpAWKLMXQIFDIARRK0NQM+mD8Vgp
sXCGtkOv6ZDQeRCkAs6KWQXbzcEnDiz1fbhqW5flG/Jalp4Mofm1iegB/0zpfJSt
qjv3TSs+GBfzJFZ11KfOoANBosxnKSsU542ZE49uAFeFRAliAxS/P6DBYNCSMEmU
64Nhzj6gdWdzWuwGhX7gtA1wMdCPPVgZXPmDABEBAAG0HlRlc3QgVXNlciA8dGVz
dEBleGFtcGxlLmxvY2FsPokBVQQTAQoAPxYhBDxrO8thz6yNr0JUVBOBM8wevhXf
BQJpyGPUAxsvBAUJBxQdbAULCQgHAgYVCgkICwIEFgIDAQIeAQIXgAAKCRATgTPM
Hr4V3329B/9gO2Hrh2/FTyh9I5jKrvSEmncfCu9XsY+bCIUSLb5FYseoBy71WS7Y
wcKaAacNwPrdiQ1NwZ96aqqSX+w+L5RCKctFSFeLRmlEGgx833titPq5haluZtHQ
dbGB66yhQMmMOTd1xw4zcj5lR8Dea/aR8WZO9tOUKm7l4FsKewElW14vPQ7Jydf9
3gunhM8v5fcFPBvc0cr9SrtVdEXIhElos5Hc7P8ri96X4l1v4qPPJU+ceW67Q9Jz
6eJdtA/0XzNVj7kTp8+F1WlZuNTRd0lnBnSHmAL17GZR2RdiD3W47Dbo1SnthyxW
+vkbjNd5xB1okcr8ZIfBPX2/n7epySnB
=noSQ
-----END PGP PUBLIC KEY BLOCK-----"""

TEST_KEY_FINGERPRINT = "3C6B3BCB61CFAC8DAF425454138133CC1EBE15DF"


@pytest.fixture
def test_key():
    """Provide test key data."""
    return {
        "public_key": TEST_PUBLIC_KEY,
        "fingerprint": TEST_KEY_FINGERPRINT,
    }
