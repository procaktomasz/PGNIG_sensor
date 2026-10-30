"""Testy koordynatora pobierania danych."""
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pgnig_sensor.api import APIError, AuthFailed
from custom_components.pgnig_sensor.const import DOMAIN
from custom_components.pgnig_sensor.coordinator import PGNiGDataUpdateCoordinator
from tests.conftest import make_invoice


@pytest.fixture
async def coordinator(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "user@example.com", "password": "x", "authtoken": "t",
              "device_id": "d", "automatic_token": "a"},
    )
    entry.add_to_hass(hass)
    coord = PGNiGDataUpdateCoordinator(hass, entry)
    coord.api.login_step1 = AsyncMock()
    coord.api.get_balance = AsyncMock(return_value={"Value": 12.5})
    coord.api.get_agreements = AsyncMock(return_value={"Agreements": []})
    coord.api.get_invoices = AsyncMock(return_value={"InvoicesList": []})
    coord.api.get_readings = AsyncMock(return_value={"MeterReadings": []})
    coord.api.get_wear_chart = AsyncMock(return_value={"ChartData": {}})
    return coord


async def test_auth_failure_requests_reauth_without_password_login(coordinator):
    coordinator.api.get_balance.side_effect = AuthFailed("expired")
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    coordinator.api.login_step1.assert_not_called()


async def test_api_error_is_update_failed(coordinator):
    coordinator.api.get_invoices.side_effect = APIError("API Error 500")
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    coordinator.api.login_step1.assert_not_called()


async def test_balance_unknown_when_missing(coordinator):
    coordinator.api.get_balance.return_value = {"Code": 0}
    data = await coordinator._async_update_data()
    assert data["balance"] is None


async def test_fetch_merges_and_sorts_invoices(coordinator):
    coordinator.api.get_invoices.side_effect = [
        {"InvoicesList": [make_invoice("A", date="2026-01-01T00:00:00.000000Z"),
                          make_invoice("B", date="2026-03-01T00:00:00.000000Z")]},
        {"InvoicesList": [make_invoice("B", date="2026-03-01T00:00:00.000000Z"),
                          make_invoice("C", date="2026-02-01T00:00:00.000000Z")]},
    ]
    data = await coordinator._async_update_data()
    assert [inv["Number"] for inv in data["invoices"]] == ["B", "C", "A"]
    assert data["balance"] == 12.5
