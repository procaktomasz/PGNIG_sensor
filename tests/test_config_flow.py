"""Testy kreatora konfiguracji (config flow)."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pgnig_sensor.api import AuthFailed, CannotConnect
from custom_components.pgnig_sensor.const import DOMAIN

API = "custom_components.pgnig_sensor.config_flow.PGNiGApi"
SUCCESS = {"status": "success", "authtoken": "NEW_TOKEN", "automatic_token": "NEW_AUTO"}


@pytest.fixture(autouse=True)
def skip_setup():
    with patch("custom_components.pgnig_sensor.async_setup_entry", return_value=True):
        yield


@pytest.fixture
def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        title="user@example.com",
        data={"username": "user@example.com", "password": "old", "authtoken": "OLD",
              "device_id": "dev1", "automatic_token": "OLD_AUTO"},
    )
    entry.add_to_hass(hass)
    return entry


async def test_user_flow_with_sms_creates_entry(hass):
    with patch(API) as api_cls:
        api = api_cls.return_value
        api.login_step1 = AsyncMock(return_value={"status": "sms_required"})
        api.login_step2 = AsyncMock(return_value=SUCCESS)
        api.device_id = "dev1"

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "user@example.com", "password": "pw"})
        assert result["step_id"] == "sms"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"sms_code": "123456"})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["authtoken"] == "NEW_TOKEN"


async def test_user_flow_cannot_connect(hass):
    with patch(API) as api_cls:
        api_cls.return_value.login_step1 = AsyncMock(side_effect=CannotConnect("timeout"))
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "user@example.com", "password": "pw"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_invalid_auth(hass):
    with patch(API) as api_cls:
        api_cls.return_value.login_step1 = AsyncMock(side_effect=AuthFailed("bad"))
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "user@example.com", "password": "pw"})
    assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.parametrize("source", [config_entries.SOURCE_REAUTH, config_entries.SOURCE_RECONFIGURE])
async def test_reauth_and_reconfigure_with_sms_update_existing_entry(hass, entry, source):
    with patch(API) as api_cls:
        api = api_cls.return_value
        api.login_step1 = AsyncMock(return_value={"status": "sms_required"})
        api.login_step2 = AsyncMock(return_value=SUCCESS)
        api.device_id = "dev1"

        if source == config_entries.SOURCE_REAUTH:
            result = await entry.start_reauth_flow(hass)
        else:
            result = await entry.start_reconfigure_flow(hass)
        assert result["step_id"] == "reauth_confirm"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "new"})
        assert result["step_id"] == "sms"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"sms_code": "123456"})
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].data["authtoken"] == "NEW_TOKEN"
    assert entries[0].data["automatic_token"] == "NEW_AUTO"
    assert entries[0].data["password"] == "new"
