"""Buttons for VanMoof bikes."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import S3_SOUND_HORN, Generation
from .coordinator import VanMoofBikeCoordinator, VanMoofConfigEntry
from .entity import VanMoofBikeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VanMoofConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons."""
    entities: list[ButtonEntity] = []
    for coordinator in entry.runtime_data.bikes.values():
        if coordinator.generation is Generation.UNKNOWN:
            continue
        entities.append(VanMoofRefreshButton(coordinator))
        if coordinator.generation is Generation.S3:
            entities.append(VanMoofBellButton(coordinator))
    async_add_entities(entities)


class VanMoofRefreshButton(VanMoofBikeEntity, ButtonEntity):
    """Poll the bike now."""

    _attr_translation_key = "refresh"

    def __init__(self, coordinator: VanMoofBikeCoordinator) -> None:
        super().__init__(coordinator, "refresh")

    async def async_press(self) -> None:
        """Refresh Bluetooth and cloud data."""
        await self.coordinator.cloud.async_request_refresh()
        await self.coordinator.async_request_refresh()


class VanMoofBellButton(VanMoofBikeEntity, ButtonEntity):
    """Play the horn sound (useful to find the bike)."""

    _attr_translation_key = "bell"

    def __init__(self, coordinator: VanMoofBikeCoordinator) -> None:
        super().__init__(coordinator, "bell")

    async def async_press(self) -> None:
        """Ring the bell."""
        await self.coordinator.async_command(lambda s: s.play_sound(S3_SOUND_HORN))
