"""Tests for the save_settings action."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vanmoof.const import DOMAIN
from custom_components.vanmoof.models import BikeState
from custom_components.vanmoof.services import SERVICE_SAVE_SETTINGS

from .conftest import ACCOUNT_UUID, FRAME_S3, FRAME_S5, customer_data
from .test_init import CERT


@pytest.fixture
async def loaded(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ACCOUNT_UUID,
        data={CONF_EMAIL: "rider@example.com", CONF_PASSWORD: "secret"},
    )
    entry.add_to_hass(hass)
    session = MagicMock()
    session.set_power_level = AsyncMock()
    session.set_light_mode = AsyncMock()
    session.set_bell_tone = AsyncMock()

    async def fake_session(_self, action):
        # Polls return a state; the action's writes go to the mock session.
        if action.__name__ != "write":
            return BikeState(in_range=True)
        return await action(session)

    with (
        patch(
            "custom_components.vanmoof.api.VanMoofApi.async_get_customer_data",
            new=AsyncMock(return_value=customer_data()),
        ),
        patch(
            "custom_components.vanmoof.api.VanMoofApi.async_create_certificate",
            new=AsyncMock(return_value=CERT),
        ),
        patch(
            "custom_components.vanmoof.coordinator.VanMoofBikeCoordinator._async_session",
            new=fake_session,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield session


def _device_id(hass: HomeAssistant, frame: str) -> str:
    return dr.async_get(hass).async_get_device({(DOMAIN, frame)}).id


async def test_save_settings_writes_in_one_session(hass: HomeAssistant, loaded) -> None:
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SAVE_SETTINGS,
        {
            "device_id": _device_id(hass, FRAME_S3),
            "power_level": 3,
            "light_mode": "off",
            "bell_tone": "foghorn",
        },
        blocking=True,
    )
    loaded.set_power_level.assert_awaited_once_with(3)
    loaded.set_light_mode.assert_awaited_once_with(2)
    loaded.set_bell_tone.assert_awaited_once_with(0x18)


async def test_save_settings_only_given_values(hass: HomeAssistant, loaded) -> None:
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SAVE_SETTINGS,
        {"device_id": [_device_id(hass, FRAME_S3)], "light_mode": "auto"},
        blocking=True,
    )
    loaded.set_light_mode.assert_awaited_once_with(0)
    loaded.set_power_level.assert_not_awaited()
    loaded.set_bell_tone.assert_not_awaited()


async def test_save_settings_rejects_s5(hass: HomeAssistant, loaded) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SAVE_SETTINGS,
            {"device_id": _device_id(hass, FRAME_S5), "power_level": "2"},
            blocking=True,
        )


async def test_save_settings_needs_a_setting(hass: HomeAssistant, loaded) -> None:
    with pytest.raises(Exception, match="at least one"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SAVE_SETTINGS,
            {"device_id": _device_id(hass, FRAME_S3)},
            blocking=True,
        )


async def test_save_settings_unknown_device(hass: HomeAssistant, loaded) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SAVE_SETTINGS,
            {"device_id": "nope", "bell_tone": "bell"},
            blocking=True,
        )
