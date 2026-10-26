"""Fail-closed port for a future approved OS/server secret adapter. No credentials."""
from typing import Protocol


class CredentialsRequired(Exception):
    pass


class SecretStore(Protocol):
    available: bool

    def resolve(self, secret_ref: str) -> bytes: ...


class UnavailableSecretStore:
    available = False

    def resolve(self, secret_ref):
        # Do not echo even the reference into errors or log it.
        raise CredentialsRequired("Secret store unavailable; real credentials are not accepted")

    def save(self, *args, **kwargs):
        raise CredentialsRequired("Secure credential persistence is disabled")
