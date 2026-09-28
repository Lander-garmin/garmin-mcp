"""OAuth 2.1 authorisation server with PKCE and Dynamic Client Registration.

Single-user model: one shared password (set via ``MCP_AUTH_PASSWORD``) gates
every authorisation. Tokens are JWTs signed with ``JWT_SECRET``. Refresh
tokens rotate on every use.

Restart-safe: hosts like Render restart the process on every deploy and at
will, so nothing a connected client depends on may live only in memory.

* **Client registrations are stateless.** The ``client_id`` handed back by
  Dynamic Client Registration is a signed token that carries the client's
  registration metadata, and the client secret is derived from it with an
  HMAC. After a restart ``get_client`` rebuilds the client from its id.
* **Refresh tokens are signed JWTs** (``typ=refresh``) bound to the client.
  A restart no longer invalidates them, so the connector does not drop when
  the 24 h access token expires. Rotation is enforced best-effort with an
  in-memory list of spent refresh-token ids.
* Authorisation codes and pending logins stay in memory: they live for
  minutes and are only needed while the user is on the login page.

Rotating ``JWT_SECRET`` invalidates every client, access and refresh token at
once, which is the documented way to revoke access.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

import jwt
import structlog
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

log = structlog.get_logger(__name__)

ACCESS_TOKEN_TTL_SECONDS = 24 * 60 * 60
REFRESH_TOKEN_TTL_SECONDS = 90 * 24 * 60 * 60
AUTHORIZATION_CODE_TTL_SECONDS = 10 * 60
LOGIN_STATE_TTL_SECONDS = 10 * 60

_CLIENT_ID_PREFIX = "c1."
_REFRESH_AUDIENCE_SUFFIX = "#refresh"
# Registration fields carried inside a stateless client_id.
_CLIENT_FIELDS = {
    "redirect_uris",
    "token_endpoint_auth_method",
    "grant_types",
    "response_types",
    "scope",
    "client_name",
}


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class InvalidLoginError(Exception):
    """Raised when /login receives the wrong password or a bad state value."""


class SimpleOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """Single-user OAuth server backed by a shared password and JWT secret."""

    def __init__(self, mcp_password: str, jwt_secret: str, issuer_url: str) -> None:
        if not mcp_password:
            raise ValueError("mcp_password must be a non-empty string.")
        if not jwt_secret or len(jwt_secret) < 16:
            raise ValueError("jwt_secret must be at least 16 characters.")
        self._password = mcp_password
        self._jwt_secret = jwt_secret
        self._issuer_url = issuer_url.rstrip("/")

        # Cache only: every entry can be rebuilt from its signed client_id.
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._codes: dict[str, AuthorizationCode] = {}
        # jti -> exp of refresh tokens already exchanged (rotation, best-effort).
        self._spent_refresh_jtis: dict[str, int] = {}
        # state -> (client_id, params, created_at)
        self._pending_logins: dict[str, tuple[str, AuthorizationParams, float]] = {}

    # ------------------------------------------------------------------
    # Stateless client registrations
    # ------------------------------------------------------------------

    def _mac(self, purpose: bytes, data: bytes) -> bytes:
        return hmac.new(self._jwt_secret.encode(), purpose + b"|" + data, hashlib.sha256).digest()

    def _client_secret_for(self, client_id: str) -> str:
        return self._mac(b"client-secret", client_id.encode()).hex()

    def _encode_client_id(self, client_info: OAuthClientInformationFull) -> str:
        meta: dict[str, Any] = client_info.model_dump(
            mode="json", include=_CLIENT_FIELDS, exclude_none=True
        )
        if isinstance(meta.get("client_name"), str):
            meta["client_name"] = meta["client_name"][:60]
        meta["iat"] = client_info.client_id_issued_at or int(time.time())
        body = _b64e(json.dumps(meta, separators=(",", ":"), sort_keys=True).encode())
        sig = _b64e(self._mac(b"client-id", body.encode())[:18])
        return f"{_CLIENT_ID_PREFIX}{body}.{sig}"

    def _decode_client_id(self, client_id: str) -> OAuthClientInformationFull | None:
        if not client_id.startswith(_CLIENT_ID_PREFIX):
            return None
        try:
            body, sig = client_id[len(_CLIENT_ID_PREFIX) :].rsplit(".", 1)
        except ValueError:
            return None
        expected = _b64e(self._mac(b"client-id", body.encode())[:18])
        if not hmac.compare_digest(sig, expected):
            return None
        try:
            meta: dict[str, Any] = json.loads(_b64d(body))
        except ValueError:
            return None
        issued_at = meta.pop("iat", None)
        method = meta.get("token_endpoint_auth_method")
        try:
            return OAuthClientInformationFull(
                client_id=client_id,
                client_id_issued_at=issued_at,
                client_secret=None if method == "none" else self._client_secret_for(client_id),
                **meta,
            )
        except ValueError:
            return None

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        client = self._clients.get(client_id)
        if client is None:
            client = self._decode_client_id(client_id)
            if client is not None:
                self._clients[client_id] = client
                log.info("oauth.client.restored")
        return client

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if client_info.client_id is None:
            raise ValueError("Registered client must have a client_id assigned by the SDK.")
        # Replace the SDK's random UUID with a signed, self-describing id and a
        # derived secret. The SDK returns this same object to the client, so the
        # client stores these values and they keep working across restarts.
        client_id = self._encode_client_id(client_info)
        client_info.client_id = client_id
        if client_info.token_endpoint_auth_method != "none":
            client_info.client_secret = self._client_secret_for(client_id)
        self._clients[client_id] = client_info
        log.info(
            "oauth.client.registered",
            client_id=client_id[:24] + "...",
            client_name=client_info.client_name,
            redirect_uris=[str(u) for u in (client_info.redirect_uris or [])],
        )

    # ------------------------------------------------------------------
    # Authorisation (password page)
    # ------------------------------------------------------------------

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        client_id = client.client_id
        if client_id is None:
            raise ValueError("Client passed to authorize() has no client_id.")
        self._sweep_pending_logins()
        state = secrets.token_urlsafe(24)
        self._pending_logins[state] = (client_id, params, time.monotonic())
        return f"{self._issuer_url}/login?state={state}"

    async def complete_login(self, state: str, password: str) -> str:
        """Finish the password challenge started by ``authorize``.

        Called by the /login POST handler. Returns the redirect URL the user
        should be sent to (their client's redirect_uri with code and state).
        """
        if not secrets.compare_digest(password, self._password):
            raise InvalidLoginError("Incorrect password.")

        self._sweep_pending_logins()
        record = self._pending_logins.pop(state, None)
        if record is None:
            raise InvalidLoginError("This login link has expired. Start the connection again.")

        client_id, params, _ = record
        code_value = secrets.token_urlsafe(32)
        self._codes[code_value] = AuthorizationCode(
            code=code_value,
            scopes=params.scopes or [],
            expires_at=time.time() + AUTHORIZATION_CODE_TTL_SECONDS,
            client_id=client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        return construct_redirect_uri(
            str(params.redirect_uri),
            code=code_value,
            state=params.state,
        )

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        code = self._codes.get(authorization_code)
        if code is None:
            return None
        if code.client_id != client.client_id:
            return None
        if code.expires_at <= time.time():
            self._codes.pop(authorization_code, None)
            return None
        return code

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        # PKCE is verified by the SDK before this is called.
        client_id = self._require_client_id(client)
        self._codes.pop(authorization_code.code, None)

        access_token = self._mint_jwt(
            client_id,
            authorization_code.scopes,
            authorization_code.resource,
        )
        refresh_value = self._mint_refresh(client_id, authorization_code.scopes)
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            refresh_token=refresh_value,
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
        )

    # ------------------------------------------------------------------
    # Refresh tokens (stateless JWTs)
    # ------------------------------------------------------------------

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        try:
            payload: dict[str, Any] = jwt.decode(
                refresh_token,
                self._jwt_secret,
                algorithms=["HS256"],
                audience=self._issuer_url + _REFRESH_AUDIENCE_SUFFIX,
                issuer=self._issuer_url,
            )
        except jwt.PyJWTError as exc:
            log.info("oauth.refresh_token.invalid", error=str(exc))
            return None
        if payload.get("typ") != "refresh" or payload.get("sub") != client.client_id:
            return None
        if payload.get("jti") in self._spent_refresh_jtis:
            log.info("oauth.refresh_token.reused")
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=str(payload["sub"]),
            scopes=list(payload.get("scopes", [])),
            expires_at=int(payload["exp"]),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # Rotation: mark the presented refresh token as spent.
        client_id = self._require_client_id(client)
        self._spend_refresh(refresh_token)

        new_scopes = scopes or refresh_token.scopes
        access_token = self._mint_jwt(client_id, new_scopes, None)
        new_refresh = self._mint_refresh(client_id, new_scopes)
        log.info("oauth.refresh_token.rotated")
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            refresh_token=new_refresh,
            scope=" ".join(new_scopes) if new_scopes else None,
        )

    # ------------------------------------------------------------------
    # Access tokens
    # ------------------------------------------------------------------

    async def load_access_token(self, token: str) -> AccessToken | None:
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self._jwt_secret,
                algorithms=["HS256"],
                audience=self._issuer_url,
                issuer=self._issuer_url,
            )
        except jwt.PyJWTError as exc:
            log.debug("oauth.access_token.invalid", error=str(exc))
            return None
        if payload.get("typ") == "refresh":
            return None

        return AccessToken(
            token=token,
            client_id=payload.get("sub", ""),
            scopes=list(payload.get("scopes", [])),
            expires_at=int(payload["exp"]) if "exp" in payload else None,
            resource=payload.get("resource"),
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, RefreshToken):
            self._spend_refresh(token)
        # Access tokens are stateless JWTs. We accept the revoke call so the
        # endpoint reports success, but the token will continue to validate
        # until it expires. For a single-user server this is acceptable.

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _mint_jwt(
        self,
        client_id: str,
        scopes: list[str],
        resource: str | None,
    ) -> str:
        now = int(time.time())
        payload: dict[str, Any] = {
            "sub": client_id,
            "iss": self._issuer_url,
            "aud": self._issuer_url,
            "iat": now,
            "exp": now + ACCESS_TOKEN_TTL_SECONDS,
            "scopes": scopes or [],
        }
        if resource is not None:
            payload["resource"] = resource
        encoded = jwt.encode(payload, self._jwt_secret, algorithm="HS256")
        return encoded if isinstance(encoded, str) else encoded.decode("ascii")

    def _mint_refresh(self, client_id: str, scopes: list[str]) -> str:
        now = int(time.time())
        payload: dict[str, Any] = {
            "typ": "refresh",
            "sub": client_id,
            "iss": self._issuer_url,
            "aud": self._issuer_url + _REFRESH_AUDIENCE_SUFFIX,
            "iat": now,
            "exp": now + REFRESH_TOKEN_TTL_SECONDS,
            "jti": secrets.token_urlsafe(12),
            "scopes": scopes or [],
        }
        encoded = jwt.encode(payload, self._jwt_secret, algorithm="HS256")
        return encoded if isinstance(encoded, str) else encoded.decode("ascii")

    def _spend_refresh(self, token: RefreshToken) -> None:
        try:
            payload = jwt.decode(token.token, options={"verify_signature": False})
        except jwt.PyJWTError:
            return
        jti = payload.get("jti")
        if jti:
            self._spent_refresh_jtis[str(jti)] = int(payload.get("exp", 0))
        now = int(time.time())
        for spent, exp in list(self._spent_refresh_jtis.items()):
            if exp and exp < now:
                self._spent_refresh_jtis.pop(spent, None)

    @staticmethod
    def _require_client_id(client: OAuthClientInformationFull) -> str:
        if client.client_id is None:
            raise ValueError("Client has no client_id.")
        return client.client_id

    def _sweep_pending_logins(self) -> None:
        cutoff = time.monotonic() - LOGIN_STATE_TTL_SECONDS
        stale = [s for s, (_, _, ts) in self._pending_logins.items() if ts < cutoff]
        for s in stale:
            self._pending_logins.pop(s, None)
