"""The connector must survive server restarts.

Render restarts the process on every deploy (and whenever it likes). Before,
client registrations and refresh tokens lived only in memory, so the first
token refresh after a restart failed and claude.ai dropped the connector.
These tests run the real SDK OAuth routes, "restart" by building a fresh
provider with the same secret, and check that refresh still works.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp.server.auth.routes import create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from pydantic import AnyHttpUrl
from starlette.applications import Starlette

from garmin_mcp.auth import SimpleOAuthProvider

ISSUER = "https://example.test"
PASSWORD = "correct horse battery staple"
SECRET = "s" * 48
REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def _app(provider: SimpleOAuthProvider) -> Starlette:
    routes = create_auth_routes(
        provider,
        issuer_url=AnyHttpUrl(ISSUER),
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=["mcp"], default_scopes=["mcp"]
        ),
        revocation_options=RevocationOptions(enabled=True),
    )
    return Starlette(routes=routes)


def _client(provider: SimpleOAuthProvider) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(provider)), base_url=ISSUER)


async def _register(http: httpx.AsyncClient, auth_method: str) -> dict[str, Any]:
    r = await http.post(
        "/register",
        json={
            "client_name": "Claude",
            "redirect_uris": [REDIRECT],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": auth_method,
        },
    )
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def _auth_fields(reg: dict[str, Any]) -> dict[str, str]:
    fields = {"client_id": reg["client_id"]}
    if reg.get("client_secret"):
        fields["client_secret"] = reg["client_secret"]
    return fields


async def _login_and_get_tokens(
    http: httpx.AsyncClient, provider: SimpleOAuthProvider, reg: dict[str, Any]
) -> dict[str, Any]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    r = await http.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": reg["client_id"],
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "scope": "mcp",
        },
    )
    assert r.status_code in (302, 303, 307), r.text
    login_state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    redirect = await provider.complete_login(login_state, PASSWORD)
    code = parse_qs(urlparse(redirect).query)["code"][0]
    r = await http.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
            **_auth_fields(reg),
        },
    )
    assert r.status_code == 200, r.text
    tokens: dict[str, Any] = r.json()
    return tokens


async def _refresh(http: httpx.AsyncClient, reg: dict[str, Any], refresh: str) -> httpx.Response:
    return await http.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh, **_auth_fields(reg)},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_method", ["none", "client_secret_post"])
async def test_refresh_survives_restart(auth_method: str) -> None:
    before = SimpleOAuthProvider(PASSWORD, SECRET, ISSUER)
    async with _client(before) as http:
        reg = await _register(http, auth_method)
        tokens = await _login_and_get_tokens(http, before, reg)

    assert reg["client_id"].startswith("c1.")
    assert (reg.get("client_secret") is None) == (auth_method == "none")

    # Simulated restart: brand-new provider, empty memory, same JWT secret.
    after = SimpleOAuthProvider(PASSWORD, SECRET, ISSUER)
    async with _client(after) as http:
        r = await _refresh(http, reg, tokens["refresh_token"])
        assert r.status_code == 200, r.text
        new = r.json()
        assert new["access_token"] and new["refresh_token"] != tokens["refresh_token"]
        assert await after.load_access_token(new["access_token"]) is not None

        # Rotation: the spent refresh token is refused, the new one works.
        assert (await _refresh(http, reg, tokens["refresh_token"])).status_code == 400
        assert (await _refresh(http, reg, new["refresh_token"])).status_code == 200


@pytest.mark.asyncio
async def test_other_secret_rejects_everything() -> None:
    """Rotating JWT_SECRET is the documented way to revoke all access."""
    before = SimpleOAuthProvider(PASSWORD, SECRET, ISSUER)
    async with _client(before) as http:
        reg = await _register(http, "client_secret_post")
        tokens = await _login_and_get_tokens(http, before, reg)

    rotated = SimpleOAuthProvider(PASSWORD, "t" * 48, ISSUER)
    assert await rotated.get_client(reg["client_id"]) is None
    assert await rotated.load_access_token(tokens["access_token"]) is None
    async with _client(rotated) as http:
        assert (await _refresh(http, reg, tokens["refresh_token"])).status_code in (400, 401)


@pytest.mark.asyncio
async def test_tampered_client_id_and_token_types_are_rejected() -> None:
    provider = SimpleOAuthProvider(PASSWORD, SECRET, ISSUER)
    async with _client(provider) as http:
        reg = await _register(http, "none")
        tokens = await _login_and_get_tokens(http, provider, reg)

    fresh = SimpleOAuthProvider(PASSWORD, SECRET, ISSUER)
    body, sig = reg["client_id"][3:].rsplit(".", 1)
    forged = "c1." + body[:-2] + ("AA" if body[-2:] != "AA" else "BB") + "." + sig
    assert await fresh.get_client(forged) is None
    assert await fresh.get_client("some-random-uuid") is None
    # A refresh token must not work as an access token, nor the reverse.
    assert await fresh.load_access_token(tokens["refresh_token"]) is None
    client = await fresh.get_client(reg["client_id"])
    assert client is not None
    assert await fresh.load_refresh_token(client, tokens["access_token"]) is None
