"""Binary sensors for VanMoof bikes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import Generation
from .coordinator import VanMoofBikeCoordinator, VanMoofConfigEntry
from .entity import VanMoofBikeEntity, VanMoofCloudEntity
from .models import BikeState

S3 = frozenset({Generation.S3})
S5 = frozenset({Generation.S5})
ALL = frozenset({Generation.S3, Generation.S5})


@dataclass(frozen=True, kw_only=True)
class VanMoofBinaryDescription(BinarySensorEntityDescription):
    """Binary sensor fed by the Bluetooth coordinator."""

    value_fn: Callable[[BikeState], bool | None]
    generations: frozenset[Generation] = ALL


BIKE_BINARY_SENSORS: tuple[VanMoofBinaryDescription, ...] = (
    VanMoofBinaryDescription(
        key="in_range",
        translation_key="in_range",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda s: s.in_range,
    ),
    VanMoofBinaryDescription(
        key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        generations=S3,
        value_fn=lambda s: s.charging,
    ),
    VanMoofBinaryDescription(
        key="module_charging",
        translation_key="module_charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        entity_category=EntityCategory.DIAGNOSTIC,
        generations=S3,
        value_fn=lambda s: s.module_charging,
    ),
    VanMoofBinaryDescription(
        key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.has_error,
    ),
    # S3 bikes get a real lock entity instead.
    VanMoofBinaryDescription(
        key="lock",
        device_class=BinarySensorDeviceClass.LOCK,
        generations=S5,
        value_fn=lambda s: None if s.locked is None else not s.locked,
    ),
)


@dataclass(frozen=True, kw_only=True)
class VanMoofCloudBinaryDescription(BinarySensorEntityDescription):
    """Binary sensor fed by cloud data."""

    value_fn: Callable[[dict[str, Any]], bool | None]


def _update_available(details: dict[str, Any]) -> bool | None:
    current = details.get("smartmoduleCurrentVersion")
    desired = details.get("smartmoduleDesiredVersion")
    if not current or not desired:
        return None
    return current != desired


CLOUD_BINARY_SENSORS: tuple[VanMoofCloudBinaryDescription, ...] = (
    VanMoofCloudBinaryDescription(
        key="stolen",
        translation_key="stolen",
        device_class=BinarySensorDeviceClass.SAFETY,
        value_fn=lambda d: (d.get("stolen") or {}).get("isStolen") if d else None,
    ),
    VanMoofCloudBinaryDescription(
        key="tracking",
        translation_key="tracking",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("isTracking") if d else None,
    ),
    VanMoofCloudBinaryDescription(
        key="firmware_update",
        translation_key="firmware_update",
        device_class=BinarySensorDeviceClass.UPDATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_update_available,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VanMoofConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up VanMoof binary sensors."""
    runtime = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for frame, coordinator in runtime.bikes.items():
        entities.extend(
            VanMoofBinarySensor(coordinator, description)
            for description in BIKE_BINARY_SENSORS
            if coordinator.generation in description.generations
        )
        entities.extend(
            VanMoofCloudBinarySensor(runtime.cloud, frame, description)
            for description in CLOUD_BINARY_SENSORS
        )
    async_add_entities(entities)


class VanMoofBinarySensor(VanMoofBikeEntity, BinarySensorEntity):
    """A Bluetooth backed binary sensor."""

    entity_description: VanMoofBinaryDescription

    def __init__(
        self, coordinator: VanMoofBikeCoordinator, description: VanMoofBinaryDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


class VanMoofCloudBinarySensor(VanMoofCloudEntity, BinarySensorEntity):
    """A cloud backed binary sensor."""

    entity_description: VanMoofCloudBinaryDescription

    def __init__(self, coordinator, frame_number: str, description) -> None:
        super().__init__(coordinator, frame_number, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        return self.entity_description.value_fn(self.details)
