"""Sensors for VanMoof bikes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfSpeed,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ALARM_STATES,
    CONF_RIDE_STATISTICS,
    MODULE_STATES,
    S3_LIGHT_MODES,
    S3_SPEED_LIMITS,
    S5_LIGHT_MODES,
    S5_SPEED_LIMITS,
    UNIT_SYSTEMS,
    Generation,
)
from .coordinator import VanMoofBikeCoordinator, VanMoofConfigEntry
from .entity import VanMoofBikeEntity, VanMoofCloudEntity
from .models import BikeState

S3 = frozenset({Generation.S3})
S5 = frozenset({Generation.S5})
ALL = frozenset({Generation.S3, Generation.S5})


@dataclass(frozen=True, kw_only=True)
class VanMoofSensorDescription(SensorEntityDescription):
    """Sensor fed by the Bluetooth coordinator."""

    value_fn: Callable[[BikeState], Any]
    attrs_fn: Callable[[BikeState], dict[str, Any] | None] = lambda _: None
    generations: frozenset[Generation] = ALL


def _options(*mappings: dict[int, str]) -> list[str]:
    return sorted({v for m in mappings for v in m.values()})


BIKE_SENSORS: tuple[VanMoofSensorDescription, ...] = (
    VanMoofSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.battery,
    ),
    VanMoofSensorDescription(
        key="module_battery",
        translation_key="module_battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.module_battery,
    ),
    VanMoofSensorDescription(
        key="odometer",
        translation_key="odometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda s: s.distance_km,
    ),
    VanMoofSensorDescription(
        key="speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.speed_kmh,
    ),
    VanMoofSensorDescription(
        key="power_level",
        translation_key="power_level",
        value_fn=lambda s: s.power_level,
    ),
    VanMoofSensorDescription(
        key="light_mode",
        translation_key="light_mode",
        device_class=SensorDeviceClass.ENUM,
        options=_options(S3_LIGHT_MODES, S5_LIGHT_MODES),
        value_fn=lambda s: s.light_mode,
    ),
    VanMoofSensorDescription(
        key="speed_limit",
        translation_key="speed_limit",
        device_class=SensorDeviceClass.ENUM,
        options=_options(S3_SPEED_LIMITS, S5_SPEED_LIMITS),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.speed_limit,
    ),
    VanMoofSensorDescription(
        key="alarm",
        translation_key="alarm",
        device_class=SensorDeviceClass.ENUM,
        options=_options(ALARM_STATES),
        value_fn=lambda s: s.alarm_state,
    ),
    VanMoofSensorDescription(
        key="gear",
        translation_key="gear",
        state_class=SensorStateClass.MEASUREMENT,
        generations=S3,
        value_fn=lambda s: s.gear,
    ),
    VanMoofSensorDescription(
        key="module_state",
        translation_key="module_state",
        device_class=SensorDeviceClass.ENUM,
        options=_options(MODULE_STATES),
        entity_category=EntityCategory.DIAGNOSTIC,
        generations=S3,
        value_fn=lambda s: s.module_state,
    ),
    VanMoofSensorDescription(
        key="unit_system",
        translation_key="unit_system",
        device_class=SensorDeviceClass.ENUM,
        options=_options(UNIT_SYSTEMS),
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        generations=S3,
        value_fn=lambda s: s.unit_system,
    ),
    VanMoofSensorDescription(
        key="calories",
        translation_key="calories",
        native_unit_of_measurement="kcal",
        state_class=SensorStateClass.TOTAL_INCREASING,
        generations=S5,
        value_fn=lambda s: s.calories,
    ),
    VanMoofSensorDescription(
        key="error_code",
        translation_key="error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: None if s.errors is None else (s.errors or "none"),
    ),
    VanMoofSensorDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.firmware.get("bike") or next(iter(s.firmware.values()), None),
        attrs_fn=lambda s: dict(s.firmware) or None,
    ),
    VanMoofSensorDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.last_seen,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VanMoofConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up VanMoof sensors."""
    runtime = entry.runtime_data
    entities: list[SensorEntity] = []
    for frame, coordinator in runtime.bikes.items():
        entities.extend(
            VanMoofSensor(coordinator, description)
            for description in BIKE_SENSORS
            if coordinator.generation in description.generations
        )
        entities.append(VanMoofCloudFirmwareSensor(runtime.cloud, frame))
        if entry.options.get(CONF_RIDE_STATISTICS, False):
            entities.append(VanMoofRidesSensor(runtime.cloud, frame))
    async_add_entities(entities)


class VanMoofSensor(VanMoofBikeEntity, SensorEntity):
    """A value read over Bluetooth."""

    entity_description: VanMoofSensorDescription

    def __init__(
        self, coordinator: VanMoofBikeCoordinator, description: VanMoofSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the value."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)


class VanMoofCloudFirmwareSensor(VanMoofCloudEntity, SensorEntity):
    """Smart module firmware as known by the cloud."""

    _attr_translation_key = "cloud_firmware"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, frame_number: str) -> None:
        super().__init__(coordinator, frame_number, "cloud_firmware")

    @property
    def native_value(self) -> str | None:
        """Installed smart module firmware."""
        return self.details.get("smartmoduleCurrentVersion")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Desired and latest firmware."""
        return {
            "desired_version": self.details.get("smartmoduleDesiredVersion"),
            "latest_stable": self.details.get("smartmoduleLatestStable"),
            "ble_profile": self.details.get("bleProfile"),
            "model": self.details.get("modelName"),
            "model_details": self.details.get("modelDetails"),
        }


class VanMoofRidesSensor(VanMoofCloudEntity, SensorEntity):
    """Ride statistics of the current week from the VanMoof app."""

    _attr_translation_key = "rides_week"
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, frame_number: str) -> None:
        super().__init__(coordinator, frame_number, "rides_week")

    @property
    def _summary(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return self.coordinator.data.get("rides", {}).get(self.frame_number) or {}

    @property
    def native_value(self) -> float | None:
        """Distance ridden this week (first numeric *distance* field)."""
        for key, value in self._summary.items():
            if "distance" in key.lower() and isinstance(value, int | float):
                return float(value)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Full summary as returned by the app backend."""
        return {k: v for k, v in self._summary.items() if isinstance(v, str | int | float | bool)}
