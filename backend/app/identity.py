"""Sign-in behind one small interface, so university sign-in can replace access codes later.

Version 1 is deliberately simple: each student has a personal access code (only its hash is
stored) and the instructor has one passcode from the service's environment. Codes are
secrets. Hand them out privately.
"""

import hashlib
import secrets
from typing import Protocol

from app.store import AppStore, StoredAccount


def hash_code(code: str) -> str:
    """Access codes are long random strings, so a plain SHA-256 is enough to avoid storing them."""
    return hashlib.sha256(code.strip().encode()).hexdigest()


class IdentityProvider(Protocol):
    def authenticate(self, credential: str) -> StoredAccount | None:
        """The account this credential belongs to, or None."""


class AccessCodeIdentity:
    def __init__(self, store: AppStore, instructor_passcode: str) -> None:
        self._store = store
        self._passcode = instructor_passcode

    def authenticate(self, credential: str) -> StoredAccount | None:
        code = credential.strip()
        if secrets.compare_digest(code.encode(), self._passcode.encode()):
            return next((a for a in self._store.list_accounts() if a.role == "instructor"), None)
        return self._store.get_account_by_code(hash_code(code))
