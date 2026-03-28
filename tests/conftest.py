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

mQENBGcWJ6UBCAC7hPnoca9k6dDpvOuqCvqnWBBPowJEOysNvFqwLPi+jigLtrRD
7HaDXXFfV7L5ph8cO2Pwn/1xvHit6fST/hTbcuwSLfN0iqIorwMFZdVkIuKawMpS
k1MuYqFdRJBQD9TKukxdKjpJwl/vr9O/egTiwVfViPnxKzyMhZSfJdGbAW6G1q3b
G9l8BzxnKsPr/lz8ky4VW1z/79OIAY0wL5FKJpSC6lqcJA8LSTJ3Y8bLiU2oYu/o
+WDCX8sjk/KlpRRr8kxi2tSPKMNs8tCmHpfc7yDKdRuvfyGgBhgnsiA8qVweTvqv
hNvlSqPAYidqnTbMZlxE5QOHWDxlNN7kCAkfABEBAAG0H1Rlc3QgVXNlciA8dGVz
dEBleGFtcGxlLmxvY2FsPoiRBBMBCgA7FiEEgLmqL3FHVx+Z/lN3BPBCQ+CzF3IF
AmcWJ6UCGwMFCwkIBwICIgIGFQoJCAsCBBYCAwECHgcCF4AACgkQBPBCQ+CzF3Kg
owf/bCJDdCqPPOJlsLMUlxNIuSpUMl/C3CRsxD4iQ0X7m7K2yjR2tWC01TY7Hj6s
N8oGqJYbCqxkFIaRRFjXh7KZzLnPtS7yR4RBPhTTjh/j4CqRqFqM7HbZudPcmg7Y
zOxPn6L3K8v0LoFRvvO9i6q4Lj1xmQm3p2i9K7mPiCSKh6UJQQ+VKJlQQy/K/hLn
cT3vSF0K8ixPmPTY9VLi1K9sm6KNli1O8gzlW/RFGQwBN3J4QBWQ8FjV3vdM0gWB
R7f9IKL+xmozrTi6OFMYvV8E0mOhTsGEAp0n5T3a2K7gWBDfE6NsPORpOnKqlgUh
k4NZg/rNGM8QL7wYRZGNXLfkILkBDQRnFielAQgA2d+VdF3G7GLRFRI3w5P+LXIG
RxDdG3v/G0fF+uQ3bVmJF7woRl9y3Y2EWLBvF3NzT6LenXSClQ5DHQK/qdZqMbCp
OqDfvqx5FMTmEo0b9tIyTLoH3j8FgRMxk5ePxKU5pMV8RgLtR5ekZhP7F/O1rKLK
vihvD5k1ZnQ/UKIG2YmCA8dMN1RAQSM2vj3NqFNN0lZYD0gmFNK5q8YXBIR8YNgT
U3Kq9dFjkl7IsBvPv5pjyIcg7LioK6o5Kp1WZgER/ihmW0F9Expp73RVak/sM9UK
q7f/hBLVjQmbrGIaXrNYzqYgKZlKJ9Fj0rEPkBgDkrPrRlTpwWcLYmYVPWoTFwAR
AQABiHoEGAEKACQWIQSAuaovcUdXH5n+U3cE8EJD4LMXcgUCZxYnpQIbDAUJA8Jn
AAAKCRAE8EJD4LMXcjQVB/9rvJHm+N3E7RFKF5aPqVLOjU/gNxYshCjvD2+8NJDC
jA5Kem0CmYaQn5gDxI/bZyLiTgQ3FZsYqLM5OwukzEr8ynLiW3mCkXJfKDy1xEtY
+G/Q8aWq3whY7l2jBX5C4qE9UU9a3PE7Xj0mWCv7lgPTf3wGf6A3G3qNbJlEdS12
vfL+nOq/6qDi7C8OwNfwqJDjPq/j2qZ5FhG/1EfAJy2IBRxshJKvRhJjMlpJ/cqR
lp3LcN/3bWZqlxFUxyjqG0JpviHk2q7E8f3EG5rnbSJJxuMy3UQxfIu8tMpVRAlu
Fwuq4xwL7TER0B3qEjRl1xf9f6FMvwMHRBBz7XMJR7Kq
=o8gZ
-----END PGP PUBLIC KEY BLOCK-----"""

TEST_KEY_FINGERPRINT = "80B9AA2F7147571F99FE537704F04243E0B31772"


@pytest.fixture
def test_key():
    """Provide test key data."""
    return {
        "public_key": TEST_PUBLIC_KEY,
        "fingerprint": TEST_KEY_FINGERPRINT,
    }
