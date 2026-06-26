from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.passwords import hash_password, verify_password


def test_password_hash_roundtrip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong", h)
    assert h.startswith("pbkdf2_sha256$")


if __name__ == "__main__":
    test_password_hash_roundtrip()
    print("security tests passed")
