"""Tests for setting up the integration."""

from __future__ import annotations

import base64
import os
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import cbor2
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vanmoof.api import VanMoofAuthError, VanMoofConnectionError
from custom_components.vanmoof.const import CONF_BIKES, DOMAIN
from custom_components.vanmoof.models import BikeState

from .conftest import ACCOUNT_UUID, FRAME_S3, FRAME_S5, S3_KEY, customer_data

CERT = base64.b64encode(os.urandom(64) + cbor2.dumps({"e": 4_000_000_000})).decode()


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ACCOUNT_UUID,
        data={CONF_EMAIL: "rider@example.com", CONF_PASSWORD: "secret"},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def cloud():
    with (
        patch(
            "custom_components.vanmoof.api.VanMoofApi.async_get_customer_data",
            new=AsyncMock(return_value=customer_data()),
        ) as customer,
        patch(
            "custom_components.vanmoof.api.VanMoofApi.async_create_certificate",
            new=AsyncMock(return_value=CERT),
        ) as certificate,
    ):
        yield customer, certificate


async def test_setup_creates_devices_and_entities(
    hass: HomeAssistant, entry: MockConfigEntry, cloud
) -> None:
    _, certificate = cloud
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    # Credentials were stored: S3 key from the cloud, S5 certificate for our key.
    bikes = entry.data[CONF_BIKES]
    assert bikes[FRAME_S3]["encryption_key"] == S3_KEY
    assert bikes[FRAME_S3]["user_key_id"] == 2
    assert bikes[FRAME_S5]["certificate"] == CERT
    assert bikes[FRAME_S5]["certificate_expiry"] == 4_000_000_000
    assert bikes[FRAME_S5]["private_key"]
    certificate.assert_awaited_once()
    assert certificate.await_args.args[0] == FRAME_S5

    devices = dr.async_get(hass)
    s3 = devices.async_get_device({(DOMAIN, FRAME_S3)})
    assert s3.name == "Blitz"
    assert s3.model == "VM01-203-EU (Dark)"

    registry = er.async_get(hass)
    unique_ids = {e.unique_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)}
    assert f"{FRAME_S3}_lock" in unique_ids
    assert f"{FRAME_S3}_bell_tone" in unique_ids
    assert f"{FRAME_S5}_lock" in unique_ids  # binary sensor on S5
    assert f"{FRAME_S5}_bell_tone" not in unique_ids
    assert f"{FRAME_S5}_calories" in unique_ids

    # Bike not in range: values unknown, "in range" off, cloud values present.
    assert hass.states.get("binary_sensor.blitz_in_range").state == "off"
    assert hass.states.get("sensor.blitz_battery").state == "unknown"
    assert hass.states.get("binary_sensor.donner_firmware_update").state == "on"
    assert hass.states.get("binary_sensor.blitz_reported_stolen").state == "off"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_bluetooth_values_are_exposed(
    hass: HomeAssistant, entry: MockConfigEntry, cloud
) -> None:
    state = BikeState(
        in_range=True,
        battery=77,
        distance_km=4321.0,
        lock_state="locked",
        power_level=3,
        light_mode="auto",
        errors="",
    )
    with patch(
        "custom_components.vanmoof.coordinator.VanMoofBikeCoordinator._async_session",
        new=AsyncMock(return_value=replace(state)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get("sensor.blitz_battery").state == "77"
    assert hass.states.get("sensor.blitz_odometer").state == "4321.0"
    assert hass.states.get("lock.blitz").state == "locked"
    assert hass.states.get("select.blitz_light").state == "auto"
    assert hass.states.get("binary_sensor.blitz_in_range").state == "on"
    assert hass.states.get("binary_sensor.donner_lock").state == "off"  # off = locked


async def test_cloud_down_uses_stored_bikes(
    hass: HomeAssistant, entry: MockConfigEntry, cloud
) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)

    customer, _ = cloud
    customer.side_effect = VanMoofConnectionError("down")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("binary_sensor.blitz_in_range") is not None


async def test_cloud_down_without_stored_bikes(
    hass: HomeAssistant, entry: MockConfigEntry, cloud
) -> None:
    customer, _ = cloud
    customer.side_effect = VanMoofConnectionError("down")
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, entry: MockConfigEntry, cloud
) -> None:
    customer, _ = cloud
    customer.side_effect = VanMoofAuthError("401")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_diagnostics_redact_secrets(
    hass: HomeAssistant, entry: MockConfigEntry, cloud
) -> None:
    from custom_components.vanmoof.diagnostics import async_get_config_entry_diagnostics

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diag)
    assert S3_KEY not in text
    assert "secret" not in text
    assert CERT not in text
    assert FRAME_S3 not in text
    assert FRAME_S5 not in text
