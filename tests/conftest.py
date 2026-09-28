"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]

S3_KEY = "00112233445566778899aabbccddeeff"
FRAME_S3 = "ASY1234567"
FRAME_S5 = "SVTBKL0000001"
ACCOUNT_UUID = "8e7c4b0a-1111-2222-3333-444455556666"


def customer_data() -> dict:
    """A trimmed `getCustomerData?includeBikeDetails` response."""
    return {
        "uuid": ACCOUNT_UUID,
        "name": "Test Rider",
        "email": "rider@example.com",
        "country": "DE",
        "bikeDetails": [
            {
                "id": 111,
                "name": "Blitz",
                "frameNumber": FRAME_S3,
                "bikeId": "111",
                "modelName": "VM01-203-EU",
                "modelColor": {"name": "Dark"},
                "macAddress": "F8:8A:5E:00:11:22",
                "bleProfile": "ELECTRIFIED_2020",
                "smartmoduleCurrentVersion": "1.9.3",
                "smartmoduleDesiredVersion": "1.9.3",
                "isTracking": True,
                "stolen": {"isStolen": False},
                "key": {"encryptionKey": S3_KEY, "passcode": "aabbccddeeff", "userKeyId": 2},
            },
            {
                "id": 222,
                "name": "Donner",
                "frameNumber": FRAME_S5,
                "bikeId": "SVTBKL0000001",
                "modelName": "S5",
                "macAddress": None,
                "bleProfile": "ELECTRIFIED_2022",
                "smartmoduleCurrentVersion": "2.0.0",
                "smartmoduleDesiredVersion": "2.1.0",
                "stolen": {"isStolen": False},
                "key": None,
            },
        ],
    }


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations) -> None:
    """Enable custom integrations."""
    return


@pytest.fixture(autouse=True)
def no_bluetooth(hass) -> Generator[None]:
    """Skip real Bluetooth: mark the dependency loaded and see no devices."""
    hass.config.components.add("bluetooth_adapters")
    hass.config.components.add("bluetooth")
    with (
        patch(
            "custom_components.vanmoof.coordinator.bluetooth.async_discovered_service_info",
            return_value=[],
        ),
        patch(
            "custom_components.vanmoof.coordinator.bluetooth.async_ble_device_from_address",
            return_value=None,
        ),
    ):
        yield
