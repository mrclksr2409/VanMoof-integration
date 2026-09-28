"""Lock entity for VanMoof S3 / X3 bikes."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, Generation
from .coordinator import VanMoofBikeCoordinator, VanMoofConfigEntry
from .entity import VanMoofBikeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VanMoofConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the lock."""
    async_add_entities(
        VanMoofLock(coordinator)
        for coordinator in entry.runtime_data.bikes.values()
        if coordinator.generation is Generation.S3
    )


class VanMoofLock(VanMoofBikeEntity, LockEntity):
    """Rear wheel lock. Unlocking works over Bluetooth, locking by kicking it."""

    _attr_name = None

    def __init__(self, coordinator: VanMoofBikeCoordinator) -> None:
        super().__init__(coordinator, "lock")

    @property
    def is_locked(self) -> bool | None:
        """Return True if locked."""
        return None if self.coordinator.data is None else self.coordinator.data.locked

    @property
    def is_unlocking(self) -> bool:
        """Return True while waiting for the unlock to complete."""
        data = self.coordinator.data
        return data is not None and data.lock_state == "awaiting_unlock"

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the bike."""
        await self.coordinator.async_command(lambda s: s.unlock())

    async def async_lock(self, **kwargs: Any) -> None:
        """The bike can only be locked physically."""
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="lock_not_supported")
