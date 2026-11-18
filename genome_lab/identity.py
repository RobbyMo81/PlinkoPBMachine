"""Authenticated component identities (Document 01 responsibilities table).

Each lab component holds an Identity (name plus secret key). Tokens are
HMAC-SHA256 signatures over a canonical payload and are verified through the
shared registry. The owner's authority is key possession: the owner key is
never issued by the lab, so AI participants cannot mint owner records -
authorization arrives out of band and is only ever verified here.
"""

import hashlib
import hmac
import json
import secrets

COMPONENTS = (
    "controller",
    "discovery",
    "validator",
    "critical_verifier",
    "snapshot_preparer",
    "gate",
    "irc",
    "journal_writer",
    "evaluator",
)
OWNER = "owner"
GENOME = "genome"  # containers: denied access to journal, evidence, interfaces


class AuthError(RuntimeError):
    """Raised when a token or record fails authentication."""


def canonical_bytes(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _key_bytes(key: str) -> bytes:
    return hashlib.sha256(key.encode("utf-8")).digest()


class Identity:
    def __init__(self, name: str, key: str) -> None:
        if name != OWNER and name != GENOME and name not in COMPONENTS:
            raise ValueError(f"unknown component identity: {name!r}")
        self.name = name
        self._key = _key_bytes(key)

    def sign(self, payload: bytes) -> str:
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def issue_token(self, payload) -> str:
        body = canonical_bytes(payload)
        envelope = {"identity": self.name, "payload": payload, "mac": self.sign(body)}
        return json.dumps(envelope, sort_keys=True, separators=(",", ":"))


class IdentityRegistry:
    def __init__(self) -> None:
        self._identities: dict[str, Identity] = {}

    def register(self, name: str, key: str | None = None) -> Identity:
        if name in self._identities:
            raise ValueError(f"identity already registered: {name}")
        identity = Identity(name, key if key is not None else secrets.token_hex(32))
        self._identities[name] = identity
        return identity

    def get(self, name: str) -> Identity:
        try:
            return self._identities[name]
        except KeyError:
            raise AuthError(f"unknown identity: {name}") from None

    def verify_token(self, token: str) -> dict:
        try:
            envelope = json.loads(token)
            identity = self.get(envelope["identity"])
            expected = identity.sign(canonical_bytes(envelope["payload"]))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AuthError(f"malformed token: {exc}") from None
        if not hmac.compare_digest(expected, str(envelope.get("mac"))):
            raise AuthError(f"invalid token signature for {envelope.get('identity')}")
        return envelope
