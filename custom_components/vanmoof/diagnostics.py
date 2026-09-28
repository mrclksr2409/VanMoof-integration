"""Diagnostics for VanMoof."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import CONF_BIKES, CONF_REFRESH_TOKEN
from .coordinator import VanMoofConfigEntry

TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    "encryption_key",
    "encryptionKey",
    "passcode",
    "private_key",
    "public_key",
    "certificate",
    "key",
    "email",
    "phone",
    "name",
    "ownerName",
    "latestLocation",
    "account_id",
    "mac_address",
    "macAddress",
    "ble_address",
    "frame_number",
    "frameNumber",
    "frameSerial",
    "bikeId",
    "links",
    "mainEcuSerial",
    "uuid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: VanMoofConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    return {
        "entry": async_redact_data(
            {k: v for k, v in entry.data.items() if k != CONF_BIKES}, TO_REDACT
        ),
        "options": dict(entry.options),
        "cloud": {
            section: {
                f"bike_{frame[-4:]}": async_redact_data(value, TO_REDACT)
                for frame, value in (runtime.cloud.data or {}).get(section, {}).items()
            }
            for section in ("bikes", "rides")
        },
        "bikes": {
            f"bike_{frame[-4:]}": {
                "config": async_redact_data(runtime.cloud.bike_configs[frame].as_dict(), TO_REDACT),
                "state": asdict(coordinator.data) if coordinator.data else None,
                "update_interval": str(coordinator.update_interval),
            }
            for frame, coordinator in runtime.bikes.items()
        },
    }
