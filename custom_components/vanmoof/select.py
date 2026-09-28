"""Select entities (assist level, light mode, bell tone) for S3 / X3 bikes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .ble_s3 import S3Session
from .const import BELL_TONES, POWER_LEVELS, S3_LIGHT_MODES, Generation
from .coordinator import VanMoofBikeCoordinator, VanMoofConfigEntry
from .entity import VanMoofBikeEntity
from .models import BikeState

LIGHT_BY_NAME = {v: k for k, v in S3_LIGHT_MODES.items()}
BELL_BY_NAME = {v: k for k, v in BELL_TONES.items()}


@dataclass(frozen=True, kw_only=True)
class VanMoofSelectDescription(SelectEntityDescription):
    """Select backed by a Bluetooth write."""

    current_fn: Callable[[BikeState], str | None]
    write_fn: Callable[[S3Session, str], Awaitable[None]]


SELECTS: tuple[VanMoofSelectDescription, ...] = (
    VanMoofSelectDescription(
        key="power_level_select",
        translation_key="power_level_select",
        options=POWER_LEVELS,
        current_fn=lambda s: None if s.power_level is None else str(s.power_level),
        write_fn=lambda session, option: session.set_power_level(int(option)),
    ),
    VanMoofSelectDescription(
        key="light_mode_select",
        translation_key="light_mode_select",
        options=list(LIGHT_BY_NAME),
        current_fn=lambda s: s.light_mode,
        write_fn=lambda session, option: session.set_light_mode(LIGHT_BY_NAME[option]),
    ),
    VanMoofSelectDescription(
        key="bell_tone",
        translation_key="bell_tone",
        options=list(BELL_BY_NAME),
        entity_category=EntityCategory.CONFIG,
        current_fn=lambda s: s.bell_tone,
        write_fn=lambda session, option: session.set_bell_tone(BELL_BY_NAME[option]),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VanMoofConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up selects."""
    async_add_entities(
        VanMoofSelect(coordinator, description)
        for coordinator in entry.runtime_data.bikes.values()
        if coordinator.generation is Generation.S3
        for description in SELECTS
    )


class VanMoofSelect(VanMoofBikeEntity, SelectEntity):
    """Writable bike setting."""

    entity_description: VanMoofSelectDescription

    def __init__(
        self, coordinator: VanMoofBikeCoordinator, description: VanMoofSelectDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def current_option(self) -> str | None:
        """Return the current option."""
        if self.coordinator.data is None:
            return None
        value = self.entity_description.current_fn(self.coordinator.data)
        return value if value in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Write the new option to the bike."""
        write: Any = self.entity_description.write_fn
        await self.coordinator.async_command(lambda session: write(session, option))
