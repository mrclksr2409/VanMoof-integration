"""Coordinators for the VanMoof integration.

* ``VanMoofCloudCoordinator`` (one per account) refreshes static bike data and
  keeps the Bluetooth credentials (S3 key / S5 certificate) up to date.
* ``VanMoofBikeCoordinator`` (one per bike) opens a short Bluetooth session on
  every poll, reads all values and disconnects again so the phone app is not
  blocked.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, TypeVar

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import VanMoofApi, VanMoofAuthError, VanMoofError
from .ble_s3 import S3AuthError, S3Crypto, S3Session
from .ble_s5 import (
    S5AuthError,
    S5ProtocolError,
    S5Session,
    certificate_expiry,
    generate_keypair,
)
from .const import (
    CERT_RENEWAL_WINDOW,
    CLOUD_UPDATE_INTERVAL,
    CONF_BIKES,
    CONF_REFRESH_TOKEN,
    CONF_RIDE_STATISTICS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    S3_SERVICE_INFO,
    S3_SERVICE_SECURITY,
    S5_SERVICE,
    Generation,
    generation_for_profile,
)
from .models import BikeConfig, BikeState

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")

FAILURES_BEFORE_BACKOFF = 3
MAX_BACKOFF = timedelta(hours=1)
AUTH_FAILURES_BEFORE_KEY_REFRESH = 3


@dataclass
class VanMoofRuntimeData:
    """Objects shared by the platforms of one config entry."""

    api: VanMoofApi
    cloud: VanMoofCloudCoordinator
    bikes: dict[str, VanMoofBikeCoordinator]


type VanMoofConfigEntry = ConfigEntry[VanMoofRuntimeData]


def bike_configs_from_entry(entry: ConfigEntry) -> dict[str, BikeConfig]:
    """Load the stored bike credentials."""
    return {
        frame: BikeConfig.from_dict(data)
        for frame, data in (entry.data.get(CONF_BIKES) or {}).items()
    }


def update_bike_config(existing: BikeConfig | None, details: dict[str, Any]) -> BikeConfig:
    """Merge a cloud `bikeDetails` entry into the stored bike config."""
    frame = str(details["frameNumber"])
    key = details.get("key") or {}
    encryption_key = key.get("encryptionKey") if isinstance(key, dict) else None
    generation = generation_for_profile(details.get("bleProfile"), bool(encryption_key))
    config = existing or BikeConfig(
        frame_number=frame, bike_id=None, name=frame, generation=generation
    )
    config.bike_id = details.get("id", config.bike_id)
    config.name = details.get("name") or config.name
    config.ble_profile = details.get("bleProfile") or config.ble_profile
    config.mac_address = details.get("macAddress") or config.mac_address
    config.generation = generation
    if encryption_key:
        config.encryption_key = encryption_key
        config.user_key_id = key.get("userKeyId", config.user_key_id)
    return config


class VanMoofCloudCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Refreshes cloud data and Bluetooth credentials for all bikes."""

    config_entry: VanMoofConfigEntry

    def __init__(self, hass: HomeAssistant, entry: VanMoofConfigEntry, api: VanMoofApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_cloud",
            update_interval=timedelta(seconds=CLOUD_UPDATE_INTERVAL),
        )
        self.api = api
        self.bike_configs = bike_configs_from_entry(entry)
        self.customer: dict[str, Any] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            customer = await self.api.async_get_customer_data()
        except VanMoofAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except VanMoofError as err:
            raise UpdateFailed(f"VanMoof cloud unavailable: {err}") from err
        self.customer = customer

        details_by_frame: dict[str, dict[str, Any]] = {}
        for details in customer.get("bikeDetails") or customer.get("bikes") or []:
            if isinstance(details, dict) and details.get("frameNumber"):
                details_by_frame[str(details["frameNumber"])] = details
        if not details_by_frame and self.bike_configs:
            # The v8 API is known to occasionally return an empty bike list;
            # keep using the credentials we already have.
            _LOGGER.warning("VanMoof cloud returned no bikes, keeping stored data")

        for frame, details in details_by_frame.items():
            self.bike_configs[frame] = update_bike_config(self.bike_configs.get(frame), details)

        for frame, config in self.bike_configs.items():
            if config.generation is Generation.S5 and frame in details_by_frame:
                api_id = details_by_frame[frame].get("bikeId") or frame
                await self._async_ensure_certificate(config, str(api_id))

        rides: dict[str, dict[str, Any]] = {}
        if self.config_entry.options.get(CONF_RIDE_STATISTICS, False):
            for frame, config in self.bike_configs.items():
                if config.bike_id is None:
                    continue
                try:
                    rides[frame] = await self.api.async_get_ride_summary(
                        customer.get("uuid", ""),
                        config.bike_id,
                        customer.get("country"),
                        str(self.hass.config.time_zone),
                    )
                except VanMoofError as err:
                    _LOGGER.debug("Ride statistics unavailable for %s: %s", frame, err)

        self.async_persist()
        return {"bikes": details_by_frame, "rides": rides}

    async def _async_ensure_certificate(self, config: BikeConfig, api_id: str) -> None:
        expiry = config.certificate_expiry
        if config.certificate and expiry and expiry > time.time() + CERT_RENEWAL_WINDOW:
            return
        if not config.private_key or not config.public_key:
            config.private_key, config.public_key = generate_keypair()
        try:
            certificate = await self.api.async_create_certificate(api_id, config.public_key)
        except VanMoofError as err:
            _LOGGER.warning("Could not renew certificate for %s: %s", config.frame_number, err)
            return
        config.certificate = certificate
        config.certificate_expiry = certificate_expiry(certificate)
        _LOGGER.debug(
            "New certificate for %s valid until %s", config.frame_number, config.certificate_expiry
        )

    @callback
    def async_persist(self) -> None:
        """Store bike credentials and the refresh token if they changed."""
        entry = self.config_entry
        new_data = {
            **entry.data,
            CONF_REFRESH_TOKEN: self.api.refresh_token,
            CONF_BIKES: {frame: cfg.as_dict() for frame, cfg in self.bike_configs.items()},
        }
        if new_data != dict(entry.data):
            self.hass.config_entries.async_update_entry(entry, data=new_data)


class VanMoofBikeCoordinator(DataUpdateCoordinator[BikeState]):
    """Polls one bike over Bluetooth."""

    config_entry: VanMoofConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: VanMoofConfigEntry,
        cloud: VanMoofCloudCoordinator,
        frame_number: str,
    ) -> None:
        self._interval = timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{frame_number}",
            update_interval=self._interval,
        )
        self.cloud = cloud
        self.frame_number = frame_number
        self._lock = asyncio.Lock()
        self._failures = 0
        self._auth_failures = 0

    @property
    def bike(self) -> BikeConfig:
        """Current credentials (may be updated by the cloud coordinator)."""
        return self.cloud.bike_configs[self.frame_number]

    @property
    def generation(self) -> Generation:
        """Protocol generation of this bike."""
        return self.bike.generation

    # -- discovery -------------------------------------------------------------

    def _candidates(self) -> list[BLEDevice]:
        bike = self.bike
        known = {a.upper() for a in (bike.ble_address, bike.mac_address) if a}
        mac_suffix = (bike.mac_address or "").replace(":", "").upper()
        exact: list[BLEDevice] = []
        generic: list[BLEDevice] = []
        for info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
            name = (info.name or "").upper()
            services = {s.lower() for s in info.service_uuids}
            if info.address.upper() in known or (mac_suffix and name.endswith(mac_suffix)):
                exact.append(info.device)
            elif (
                self.generation is Generation.S3
                and (S3_SERVICE_INFO in services or S3_SERVICE_SECURITY in services)
            ) or (
                self.generation is Generation.S5
                and (S5_SERVICE in services or name.startswith("XS4-") or "VANMOOF" in name)
            ):
                generic.append(info.device)
        if not exact:
            for address in known:
                if device := bluetooth.async_ble_device_from_address(
                    self.hass, address, connectable=True
                ):
                    exact.append(device)
                    break
        return exact + generic

    # -- sessions --------------------------------------------------------------

    async def _async_session(self, action: Callable[[Any], Awaitable[_T]]) -> _T:
        """Connect, authenticate, run `action`, always disconnect."""
        bike = self.bike
        if bike.generation is Generation.S3 and not bike.encryption_key:
            raise HomeAssistantError("No encryption key for this bike yet")
        if bike.generation is Generation.S5 and not (bike.certificate and bike.private_key):
            raise HomeAssistantError("No certificate for this bike yet")
        if bike.generation is Generation.UNKNOWN:
            raise HomeAssistantError("Bluetooth protocol of this bike is not supported")

        candidates = self._candidates()
        if not candidates:
            raise BleakError("Bike is not advertising (out of range or asleep)")

        last_error: Exception | None = None
        async with self._lock:
            for device in candidates:
                try:
                    client = await establish_connection(
                        BleakClientWithServiceCache,
                        device,
                        f"VanMoof {bike.name}",
                        max_attempts=3,
                    )
                except BleakError as err:
                    last_error = err
                    _LOGGER.debug("Could not connect to %s: %s", device.address, err)
                    continue
                try:
                    if bike.generation is Generation.S3:
                        session: Any = S3Session(
                            client, S3Crypto(bike.encryption_key or "", bike.user_key_id or 0)
                        )
                    else:
                        session = S5Session(client, bike.certificate or "", bike.private_key or "")
                    await session.authenticate()
                    result = await action(session)
                except (S3AuthError, S5AuthError, S5ProtocolError) as err:
                    last_error = err
                    _LOGGER.debug("Candidate %s rejected: %s", device.address, err)
                    continue
                except BleakError:
                    # A stale GATT cache (e.g. after a module reboot) makes every
                    # request fail; force service discovery on the next connect.
                    await client.clear_cache()
                    raise
                finally:
                    await client.disconnect()
                if bike.ble_address != device.address:
                    bike.ble_address = device.address
                    self.cloud.async_persist()
                self._auth_failures = 0
                return result
        assert last_error is not None
        raise last_error

    async def _async_update_data(self) -> BikeState:
        try:
            state: BikeState = await self._async_session(lambda s: s.read_state())
        except (S3AuthError, S5AuthError) as err:
            self._auth_failures += 1
            if self._auth_failures >= AUTH_FAILURES_BEFORE_KEY_REFRESH:
                # Key or certificate may have been rotated: fetch fresh ones.
                self._auth_failures = 0
                self.hass.async_create_task(self.cloud.async_request_refresh())
            return self._offline(err)
        except (BleakError, TimeoutError, S5ProtocolError, HomeAssistantError) as err:
            return self._offline(err)

        self._failures = 0
        if self.update_interval != self._interval:
            self.update_interval = self._interval
        state.last_seen = dt_util.utcnow()
        return state

    def _offline(self, err: Exception) -> BikeState:
        """Keep the last known values but mark the bike as out of range."""
        self._failures += 1
        _LOGGER.debug("VanMoof %s not reachable: %s", self.frame_number, err)
        if self._failures >= FAILURES_BEFORE_BACKOFF and self.update_interval:
            self.update_interval = min(self.update_interval * 2, MAX_BACKOFF)
        if self.data is None:
            return BikeState(in_range=False)
        return replace(self.data, in_range=False)

    async def async_command(self, action: Callable[[Any], Awaitable[Any]]) -> None:
        """Run a write command and refresh afterwards."""
        try:
            await self._async_session(action)
        except (BleakError, TimeoutError, S3AuthError, S5AuthError, S5ProtocolError) as err:
            raise HomeAssistantError(f"Could not reach the bike: {err}") from err
        await self.async_request_refresh()


def credentials(entry: ConfigEntry) -> tuple[str, str]:
    """E-mail and password from the entry."""
    return entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
