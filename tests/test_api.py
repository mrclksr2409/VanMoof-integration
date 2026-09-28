"""Tests for the cloud API client."""

from __future__ import annotations

import base64
import json
import time

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.vanmoof.api import (
    VanMoofApi,
    VanMoofAuthError,
    VanMoofConnectionError,
    jwt_expiry,
)

from .conftest import customer_data

PRIMARY = "https://api.vanmoof-api.com/v8"
FALLBACK = "https://my.vanmoof.com/api/v8"


def make_jwt(exp: float) -> str:
    def enc(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc({'exp': int(exp)})}.sig"


def test_jwt_expiry() -> None:
    assert jwt_expiry(make_jwt(1234)) == 1234
    assert jwt_expiry("garbage") is None


async def test_login_and_customer_data() -> None:
    async with aiohttp.ClientSession() as session:
        api = VanMoofApi(session, "rider@example.com", "secret")
        with aioresponses() as mock:
            mock.post(
                f"{PRIMARY}/authenticate",
                payload={"token": make_jwt(time.time() + 3600), "refreshToken": "r1"},
            )
            mock.get(
                f"{PRIMARY}/getCustomerData?includeBikeDetails",
                payload={"data": customer_data()},
            )
            await api.async_login()
            customer = await api.async_get_customer_data()
            auth_call = next(iter(mock.requests.values()))[0]
        assert api.refresh_token == "r1"
        assert len(customer["bikeDetails"]) == 2
        expected = base64.b64encode(b"rider@example.com:secret").decode()
        assert auth_call.kwargs["headers"]["Authorization"] == f"Basic {expected}"
        assert auth_call.kwargs["headers"]["Api-Key"]


async def test_invalid_credentials() -> None:
    async with aiohttp.ClientSession() as session:
        api = VanMoofApi(session, "rider@example.com", "wrong")
        with aioresponses() as mock:
            mock.post(f"{PRIMARY}/authenticate", status=401)
            with pytest.raises(VanMoofAuthError):
                await api.async_login()


async def test_fallback_host() -> None:
    async with aiohttp.ClientSession() as session:
        api = VanMoofApi(session, "rider@example.com", "secret")
        with aioresponses() as mock:
            mock.post(f"{PRIMARY}/authenticate", status=503)
            mock.post(
                f"{FALLBACK}/authenticate",
                payload={"token": make_jwt(time.time() + 3600), "refreshToken": "r1"},
            )
            await api.async_login()
        assert api.refresh_token == "r1"


async def test_all_hosts_down() -> None:
    async with aiohttp.ClientSession() as session:
        api = VanMoofApi(session, "rider@example.com", "secret")
        with aioresponses() as mock:
            mock.post(f"{PRIMARY}/authenticate", exception=aiohttp.ClientError())
            mock.post(f"{FALLBACK}/authenticate", exception=aiohttp.ClientError())
            with pytest.raises(VanMoofConnectionError):
                await api.async_login()


async def test_refresh_token_used_before_password() -> None:
    async with aiohttp.ClientSession() as session:
        api = VanMoofApi(session, "rider@example.com", "secret", refresh_token="r0")
        with aioresponses() as mock:
            mock.post(f"{PRIMARY}/token", payload={"token": make_jwt(time.time() + 3600)})
            token = await api.async_ensure_token()
        assert token
        assert api.refresh_token == "r0"


async def test_expired_refresh_token_falls_back_to_login() -> None:
    async with aiohttp.ClientSession() as session:
        api = VanMoofApi(session, "rider@example.com", "secret", refresh_token="old")
        with aioresponses() as mock:
            mock.post(f"{PRIMARY}/token", status=401)
            mock.post(
                f"{PRIMARY}/authenticate",
                payload={"token": make_jwt(time.time() + 3600), "refreshToken": "new"},
            )
            await api.async_ensure_token()
        assert api.refresh_token == "new"


async def test_create_certificate() -> None:
    async with aiohttp.ClientSession() as session:
        api = VanMoofApi(session, "rider@example.com", "secret")
        with aioresponses() as mock:
            mock.post(
                f"{PRIMARY}/authenticate",
                payload={"token": make_jwt(time.time() + 3600), "refreshToken": "r"},
            )
            mock.get(
                f"{PRIMARY}/getApplicationToken", payload={"token": make_jwt(time.time() + 7200)}
            )
            mock.post(
                "https://bikeapi.production.vanmoof.cloud/bikes/B1/create_certificate",
                payload={"certificate": "Y2VydA==", "expiry": 1},
            )
            assert await api.async_create_certificate("B1", "cHVi") == "Y2VydA=="
