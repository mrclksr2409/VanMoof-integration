"""Config flow for VanMoof: only e-mail and password are needed."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import VanMoofApi, VanMoofAuthError, VanMoofConnectionError, VanMoofError
from .const import (
    CONF_ACCOUNT_ID,
    CONF_REFRESH_TOKEN,
    CONF_RIDE_STATISTICS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
    }
)


class VanMoofConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for VanMoof."""

    VERSION = 1

    async def _async_validate(
        self, email: str, password: str
    ) -> tuple[dict[str, str], dict[str, Any] | None, str | None]:
        """Log in and fetch the account; return (errors, customer, refresh token)."""
        api = VanMoofApi(async_get_clientsession(self.hass), email, password)
        try:
            await api.async_login()
            customer = await api.async_get_customer_data()
        except VanMoofAuthError:
            return {"base": "invalid_auth"}, None, None
        except VanMoofConnectionError:
            return {"base": "cannot_connect"}, None, None
        except VanMoofError:
            _LOGGER.exception("Unexpected response from VanMoof")
            return {"base": "unknown"}, None, None
        return {}, customer, api.refresh_token

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for e-mail and password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]
            errors, customer, refresh_token = await self._async_validate(email, password)
            if customer is not None:
                account_id = str(customer.get("uuid") or email.lower())
                await self.async_set_unique_id(account_id)
                self._abort_if_unique_id_configured()
                if not (customer.get("bikeDetails") or customer.get("bikes")):
                    errors["base"] = "no_bikes"
                else:
                    return self.async_create_entry(
                        title=customer.get("name") or email,
                        data={
                            CONF_EMAIL: email,
                            CONF_PASSWORD: password,
                            CONF_ACCOUNT_ID: account_id,
                            CONF_REFRESH_TOKEN: refresh_token,
                        },
                    )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start re-authentication after the password changed."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            email = entry.data[CONF_EMAIL]
            errors, customer, refresh_token = await self._async_validate(
                email, user_input[CONF_PASSWORD]
            )
            if customer is not None:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_REFRESH_TOKEN: refresh_token,
                    },
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> VanMoofOptionsFlow:
        """Return the options flow."""
        return VanMoofOptionsFlow()


class VanMoofOptionsFlow(OptionsFlowWithReload):
    """Polling interval and optional ride statistics."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=30,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_RIDE_STATISTICS,
                    default=options.get(CONF_RIDE_STATISTICS, False),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
