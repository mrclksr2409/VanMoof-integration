"""Tests for the config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vanmoof.api import VanMoofAuthError, VanMoofConnectionError
from custom_components.vanmoof.const import (
    CONF_ACCOUNT_ID,
    CONF_REFRESH_TOKEN,
    CONF_RIDE_STATISTICS,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)

from .conftest import ACCOUNT_UUID, customer_data

USER_INPUT = {CONF_EMAIL: "rider@example.com", CONF_PASSWORD: "secret"}


@pytest.fixture
def mock_api():
    with (
        patch(
            "custom_components.vanmoof.config_flow.VanMoofApi.async_login",
            new=AsyncMock(),
        ) as login,
        patch(
            "custom_components.vanmoof.config_flow.VanMoofApi.async_get_customer_data",
            new=AsyncMock(return_value=customer_data()),
        ) as customer,
        patch("custom_components.vanmoof.async_setup_entry", return_value=True),
    ):
        yield login, customer


async def test_user_flow(hass: HomeAssistant, mock_api) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Rider"
    assert result["data"][CONF_EMAIL] == "rider@example.com"
    assert result["data"][CONF_PASSWORD] == "secret"
    assert result["data"][CONF_ACCOUNT_ID] == ACCOUNT_UUID
    assert result["result"].unique_id == ACCOUNT_UUID


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (VanMoofAuthError("401"), "invalid_auth"),
        (VanMoofConnectionError("down"), "cannot_connect"),
    ],
)
async def test_user_flow_errors(hass: HomeAssistant, mock_api, error, key) -> None:
    login, _ = mock_api
    login.side_effect = error
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}

    login.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_no_bikes(hass: HomeAssistant, mock_api) -> None:
    _, customer = mock_api
    customer.return_value = {"uuid": ACCOUNT_UUID, "bikeDetails": []}
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "no_bikes"}


async def test_already_configured(hass: HomeAssistant, mock_api) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=ACCOUNT_UUID, data=USER_INPUT).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass: HomeAssistant, mock_api) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ACCOUNT_UUID,
        data={**USER_INPUT, CONF_REFRESH_TOKEN: "old"},
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-secret"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-secret"


async def test_options(hass: HomeAssistant, mock_api) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ACCOUNT_UUID, data=USER_INPUT)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 600, CONF_RIDE_STATISTICS: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_SCAN_INTERVAL: 600, CONF_RIDE_STATISTICS: True}
