"""Async client for the VanMoof cloud API.

The cloud only knows static data (bike identity, firmware, theft status) and
hands out the credentials needed to talk to the bike over Bluetooth. Live values
such as battery or odometer are read locally, see ``ble_s3`` and ``ble_s5``.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import time
from datetime import date, timedelta
from typing import Any

import aiohttp

from .const import (
    API_BASE_URLS,
    API_KEY,
    BIKE_API_URL,
    TENJIN_API_URL,
    TOKEN_EXPIRY_MARGIN,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class VanMoofError(Exception):
    """Base error for the VanMoof cloud."""


class VanMoofAuthError(VanMoofError):
    """Credentials or tokens were rejected."""


class VanMoofConnectionError(VanMoofError):
    """The cloud could not be reached or answered with a server error."""


def jwt_expiry(token: str | None) -> int | None:
    """Return the `exp` claim of a JWT, or None if it cannot be read."""
    if not token:
        return None
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return int(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except (IndexError, KeyError, ValueError, TypeError, binascii.Error):
        return None


def _token_valid(token: str | None) -> bool:
    expiry = jwt_expiry(token)
    return expiry is not None and time.time() < expiry - TOKEN_EXPIRY_MARGIN


class VanMoofApi:
    """VanMoof cloud client with transparent token handling."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        refresh_token: str | None = None,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self.refresh_token = refresh_token
        self._token: str | None = None
        self._app_token: str | None = None
        self._base_url = API_BASE_URLS[0]
        self._token_lock = asyncio.Lock()

    # -- low level ---------------------------------------------------------

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: Any = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json_body,
                params=params,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                text = await resp.text()
                if resp.status in (401, 403):
                    raise VanMoofAuthError(f"{method} {url}: HTTP {resp.status}")
                if resp.status >= 500:
                    raise VanMoofConnectionError(f"{method} {url}: HTTP {resp.status}")
                if resp.status >= 400:
                    raise VanMoofError(f"{method} {url}: HTTP {resp.status} {text[:200]}")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise VanMoofConnectionError(f"{method} {url}: {err}") from err
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as err:
            raise VanMoofError(f"{method} {url}: invalid JSON") from err

    async def _v8(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any = None,
    ) -> Any:
        """Call the v8 API, falling back to the alternative host if one is down."""
        hdrs = {"Api-Key": API_KEY, "Accept": "application/json", **(headers or {})}
        bases = [self._base_url] + [b for b in API_BASE_URLS if b != self._base_url]
        last_err: VanMoofError | None = None
        for base in bases:
            try:
                result = await self._request(
                    method, f"{base}/{path}", headers=hdrs, json_body=json_body
                )
            except VanMoofConnectionError as err:
                _LOGGER.debug("VanMoof host %s failed: %s", base, err)
                last_err = err
                continue
            self._base_url = base
            return result
        assert last_err is not None
        raise last_err

    # -- authentication -----------------------------------------------------

    async def async_login(self) -> None:
        """Authenticate with e-mail and password."""
        basic = base64.b64encode(f"{self._email}:{self._password}".encode()).decode()
        data = await self._v8("POST", "authenticate", headers={"Authorization": f"Basic {basic}"})
        try:
            self._token = data["token"]
            self.refresh_token = data["refreshToken"]
        except (KeyError, TypeError) as err:
            raise VanMoofError("Incomplete authentication response") from err
        self._app_token = None

    async def _async_refresh(self) -> bool:
        """Get a new auth token from the refresh token; False if not possible."""
        if not self.refresh_token:
            return False
        try:
            data = await self._v8("POST", "token", json_body={"refreshToken": self.refresh_token})
        except VanMoofAuthError:
            return False
        except VanMoofError as err:
            if isinstance(err, VanMoofConnectionError):
                raise
            # Some API revisions expect the refresh token as bearer instead.
            try:
                data = await self._v8(
                    "POST",
                    "token",
                    headers={"Authorization": f"Bearer {self.refresh_token}"},
                )
            except VanMoofAuthError:
                return False
        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            return False
        self._token = token
        if data.get("refreshToken"):
            self.refresh_token = data["refreshToken"]
        return True

    async def async_ensure_token(self) -> str:
        """Return a valid auth token, refreshing or logging in if needed."""
        async with self._token_lock:
            if not _token_valid(self._token) and not await self._async_refresh():
                await self.async_login()
            assert self._token is not None
            return self._token

    async def async_app_token(self) -> str:
        """Return a valid application token for the *.vanmoof.cloud services."""
        token = await self.async_ensure_token()
        if not _token_valid(self._app_token):
            data = await self._v8(
                "GET",
                "getApplicationToken",
                headers={"Authorization": f"Bearer {token}"},
            )
            self._app_token = data.get("token") if isinstance(data, dict) else None
            if not self._app_token:
                raise VanMoofError("No application token returned")
        return self._app_token

    async def _authed_v8(self, method: str, path: str) -> Any:
        token = await self.async_ensure_token()
        try:
            return await self._v8(method, path, headers={"Authorization": f"Bearer {token}"})
        except VanMoofAuthError:
            # Token may have been revoked server side; one fresh login.
            self._token = None
            await self.async_login()
            return await self._v8(method, path, headers={"Authorization": f"Bearer {self._token}"})

    # -- data ---------------------------------------------------------------

    async def async_get_customer_data(self) -> dict[str, Any]:
        """Return the customer record including `bikeDetails`."""
        data = await self._authed_v8("GET", "getCustomerData?includeBikeDetails")
        customer = data.get("data") if isinstance(data, dict) else None
        if not isinstance(customer, dict):
            raise VanMoofError("Unexpected customer data response")
        return customer

    async def async_create_certificate(self, bike_id: str, public_key_b64: str) -> str:
        """Request a BLE certificate for an S5/A5 bike (base64 encoded)."""
        app_token = await self.async_app_token()
        data = await self._request(
            "POST",
            f"{BIKE_API_URL}/bikes/{bike_id}/create_certificate",
            headers={
                "Authorization": f"Bearer {app_token}",
                "Content-Type": "application/json",
            },
            json_body={"public_key": public_key_b64},
        )
        if not isinstance(data, dict) or "certificate" not in data:
            raise VanMoofError(f"Certificate request failed: {data}")
        return data["certificate"]

    async def async_get_ride_summary(
        self, rider_id: str, bike_id: int | str, country: str | None, tz: str
    ) -> dict[str, Any]:
        """Return the summary of the current week's rides."""
        app_token = await self.async_app_token()
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        country = (country or "de").lower()
        data = await self._request(
            "GET",
            f"{TENJIN_API_URL}/rides/{rider_id}/{bike_id}/weekly",
            headers={
                "Authorization": f"Bearer {app_token}",
                "Api-Key": API_KEY,
                "Accept-Language": f"{country}_{country.upper()}",
                "timezone": tz,
            },
            params={"lastSeenWeek": monday.isoformat(), "limit": "1"},
        )
        summary = (data.get("carousel") or {}).get("summary") if isinstance(data, dict) else None
        return summary if isinstance(summary, dict) else {}
