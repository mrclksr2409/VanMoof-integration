"""Base entities for VanMoof."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VanMoofBikeCoordinator, VanMoofCloudCoordinator


def cloud_details(cloud: VanMoofCloudCoordinator, frame_number: str) -> dict[str, Any]:
    """Latest `bikeDetails` for a bike, or an empty dict."""
    if not cloud.data:
        return {}
    return cloud.data.get("bikes", {}).get(frame_number, {})


def device_info(cloud: VanMoofCloudCoordinator, frame_number: str) -> DeviceInfo:
    """Device registry info for a bike."""
    bike = cloud.bike_configs[frame_number]
    details = cloud_details(cloud, frame_number)
    color = (details.get("modelColor") or {}).get("name")
    model = details.get("modelName") or bike.ble_profile
    return DeviceInfo(
        identifiers={(DOMAIN, frame_number)},
        name=bike.name,
        manufacturer="VanMoof",
        model=f"{model} ({color})" if model and color else model,
        model_id=details.get("modelName"),
        serial_number=frame_number,
        sw_version=details.get("smartmoduleCurrentVersion"),
    )


class VanMoofBikeEntity(CoordinatorEntity[VanMoofBikeCoordinator]):
    """Entity backed by the Bluetooth coordinator of one bike."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: VanMoofBikeCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.frame_number}_{key}"
        self._attr_device_info = device_info(coordinator.cloud, coordinator.frame_number)


class VanMoofCloudEntity(CoordinatorEntity[VanMoofCloudCoordinator]):
    """Entity backed by the cloud coordinator, attached to one bike."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: VanMoofCloudCoordinator, frame_number: str, key: str) -> None:
        super().__init__(coordinator)
        self.frame_number = frame_number
        self._attr_unique_id = f"{frame_number}_{key}"
        self._attr_device_info = device_info(coordinator, frame_number)

    @property
    def details(self) -> dict[str, Any]:
        """Cloud data of this bike."""
        return cloud_details(self.coordinator, self.frame_number)
