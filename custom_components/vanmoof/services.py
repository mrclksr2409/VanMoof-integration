"""Actions (services) for the VanMoof integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .ble_s3 import S3Session
from .const import (
    BELL_TONES,
    DOMAIN,
    POWER_LEVELS,
    S3_LIGHT_MODES,
    S3_SPEED_LIMITS,
    Generation,
)
from .coordinator import VanMoofBikeCoordinator, VanMoofConfigEntry

SERVICE_SAVE_SETTINGS = "save_settings"

ATTR_POWER_LEVEL = "power_level"
ATTR_LIGHT_MODE = "light_mode"
ATTR_BELL_TONE = "bell_tone"
ATTR_SPEED_LIMIT = "speed_limit"
SETTINGS = (ATTR_POWER_LEVEL, ATTR_LIGHT_MODE, ATTR_BELL_TONE, ATTR_SPEED_LIMIT)

LIGHT_BY_NAME = {v: k for k, v in S3_LIGHT_MODES.items()}
BELL_BY_NAME = {v: k for k, v in BELL_TONES.items()}
SPEED_LIMIT_BY_NAME = {v: k for k, v in S3_SPEED_LIMITS.items()}

SAVE_SETTINGS_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional(ATTR_POWER_LEVEL): vol.All(vol.Coerce(str), vol.In(POWER_LEVELS)),
            vol.Optional(ATTR_LIGHT_MODE): vol.In(list(LIGHT_BY_NAME)),
            vol.Optional(ATTR_BELL_TONE): vol.In(list(BELL_BY_NAME)),
            vol.Optional(ATTR_SPEED_LIMIT): vol.In(list(SPEED_LIMIT_BY_NAME)),
        }
    ),
    cv.has_at_least_one_key(*SETTINGS),
)


def _coordinator_for_device(hass: HomeAssistant, device_id: str) -> VanMoofBikeCoordinator:
    """Find the bike coordinator behind a device id."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_device",
            translation_placeholders={"device_id": device_id},
        )
    frames = [ident for domain, ident in device.identifiers if domain == DOMAIN]
    entry: VanMoofConfigEntry
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        for frame in frames:
            if coordinator := entry.runtime_data.bikes.get(frame):
                return coordinator
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="invalid_device",
        translation_placeholders={"device_id": device_id},
    )


async def _async_save_settings(call: ServiceCall) -> None:
    """Write the requested settings to one or more bikes."""
    coordinators = [_coordinator_for_device(call.hass, d) for d in call.data[ATTR_DEVICE_ID]]
    for coordinator in coordinators:
        if coordinator.generation is not Generation.S3:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="settings_not_supported",
                translation_placeholders={"name": coordinator.bike.name},
            )

    power_level: str | None = call.data.get(ATTR_POWER_LEVEL)
    light_mode: str | None = call.data.get(ATTR_LIGHT_MODE)
    bell_tone: str | None = call.data.get(ATTR_BELL_TONE)
    speed_limit: str | None = call.data.get(ATTR_SPEED_LIMIT)

    async def write(session: S3Session) -> None:
        # All values are written within one Bluetooth connection.
        if power_level is not None:
            await session.set_power_level(int(power_level))
        if light_mode is not None:
            await session.set_light_mode(LIGHT_BY_NAME[light_mode])
        if bell_tone is not None:
            await session.set_bell_tone(BELL_BY_NAME[bell_tone])
        if speed_limit is not None:
            await session.set_speed_limit(SPEED_LIMIT_BY_NAME[speed_limit])

    for coordinator in coordinators:
        await coordinator.async_command(write)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""
    hass.services.async_register(
        DOMAIN, SERVICE_SAVE_SETTINGS, _async_save_settings, schema=SAVE_SETTINGS_SCHEMA
    )
