"""The VanMoof integration."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VanMoofApi
from .const import CONF_REFRESH_TOKEN
from .coordinator import (
    VanMoofBikeCoordinator,
    VanMoofCloudCoordinator,
    VanMoofConfigEntry,
    VanMoofRuntimeData,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.LOCK,
    Platform.SELECT,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: VanMoofConfigEntry) -> bool:
    """Set up VanMoof from a config entry."""
    api = VanMoofApi(
        async_get_clientsession(hass),
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        entry.data.get(CONF_REFRESH_TOKEN),
    )
    cloud = VanMoofCloudCoordinator(hass, entry, api)
    try:
        await cloud.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        # Bluetooth works without the cloud once credentials are stored.
        if not cloud.bike_configs:
            raise
        _LOGGER.warning("VanMoof cloud unavailable, continuing with stored bike data")

    bikes = {
        frame: VanMoofBikeCoordinator(hass, entry, cloud, frame) for frame in cloud.bike_configs
    }
    entry.runtime_data = VanMoofRuntimeData(api=api, cloud=cloud, bikes=bikes)

    @callback
    def _async_check_new_bikes() -> None:
        if set(cloud.bike_configs) - set(bikes):
            _LOGGER.info("New VanMoof bike found in account, reloading")
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(cloud.async_add_listener(_async_check_new_bikes))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Bluetooth polls can take a while; do not block Home Assistant startup.
    for coordinator in bikes.values():
        entry.async_create_background_task(
            hass,
            coordinator.async_refresh(),
            f"vanmoof_initial_poll_{coordinator.frame_number}",
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: VanMoofConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
