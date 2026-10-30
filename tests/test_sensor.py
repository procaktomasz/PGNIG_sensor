"""Testy encji sensorów."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorStateClass

from custom_components.pgnig_sensor import sensor
from custom_components.pgnig_sensor.const import DOMAIN
from tests.conftest import CRD_2, PPG_1, PPG_2, make_invoice

ENTRY_ID = "entry123"


def make_coordinator(**data):
    coordinator = MagicMock()
    coordinator.data = {
        "balance": None,
        "agreements": [],
        "invoices": [],
        "readings": {},
        "wear_charts": {},
        **data,
    }
    return coordinator


def test_balance_unknown_when_missing():
    entity = sensor.PGNiGAccountBalanceSensor(make_coordinator(balance=None), ENTRY_ID)
    assert entity.native_value is None


def test_balance_value():
    entity = sensor.PGNiGAccountBalanceSensor(make_coordinator(balance=-12.5), ENTRY_ID)
    assert entity.native_value == -12.5


def test_latest_invoice_skips_non_gas(agreements):
    invoices = [
        make_invoice("POLISA", date="2026-03-01T00:00:00.000000Z", gross=999.0, IsInsurancePolicy=True),
        make_invoice("GAZ", date="2026-02-01T00:00:00.000000Z", gross=321.0),
    ]
    entity = sensor.PGNiGLatestInvoiceSensor(make_coordinator(agreements=agreements, invoices=invoices), ENTRY_ID)
    assert entity.native_value == 321.0
    assert entity.extra_state_attributes["Numer Faktury"] == "GAZ"
    assert entity.unique_id == f"{DOMAIN}_{ENTRY_ID}_aktualna_faktura"


def test_unpaid_invoice_uses_remaining_amount(agreements):
    invoices = [
        make_invoice("P/1", paid=False, status="NotPaid", gross=300.0, to_pay=120.0),
        make_invoice("POLISA", paid=False, to_pay=999.0, IsInsurancePolicy=True,
                     deadline="2025-01-01T00:00:00.000000Z"),
    ]
    entity = sensor.PGNiGUnpaidInvoiceSensor(make_coordinator(agreements=agreements, invoices=invoices), ENTRY_ID)
    assert entity.native_value == 120.0
    assert entity.extra_state_attributes["Numer Faktury"] == "P/1"
    assert entity.unique_id == f"{DOMAIN}_{ENTRY_ID}_najblizsza_prognozowana_faktura"


def test_unpaid_invoice_all_paid(agreements):
    entity = sensor.PGNiGUnpaidInvoiceSensor(
        make_coordinator(agreements=agreements, invoices=[make_invoice("PAID")]), ENTRY_ID
    )
    assert entity.native_value == 0.0
    assert entity.extra_state_attributes == {"Informacja": "Wszystkie faktury są opłacone"}


def test_amount_due_sensor(agreements):
    invoices = [
        make_invoice("P/1", paid=False, status="NotPaid", to_pay=100.0,
                     deadline="2026-03-15T00:00:00.000000Z", days_remaining=-1),
        make_invoice("P/2", id_pp=CRD_2, paid=False, status="NotPaid", to_pay=50.0,
                     deadline="2026-04-15T00:00:00.000000Z"),
        make_invoice("POLISA", paid=False, to_pay=999.0, IsInsurancePolicy=True),
    ]
    entity = sensor.PGNiGAmountDueSensor(make_coordinator(agreements=agreements, invoices=invoices), ENTRY_ID)
    assert entity.unique_id == f"{DOMAIN}_{ENTRY_ID}_do_zaplaty"
    assert entity.native_value == 150.0
    assert entity.native_unit_of_measurement == "PLN"
    assert entity.state_class == SensorStateClass.TOTAL
    attrs = entity.extra_state_attributes
    assert attrs["Liczba nieopłaconych faktur"] == 2
    assert attrs["Najbliższy termin płatności"] == "2026-03-15T00:00:00.000000Z"
    assert attrs["Kwota najbliższej płatności"] == 100.0
    assert attrs["Faktury po terminie"] == 1


def test_meter_reading_picks_newest_and_exposes_wear():
    readings = {PPG_1: [
        {"Value": 100.0, "Wear": 10.0, "Status": "OK", "ReadingDateUtc": "2026-01-01T00:00:00.000000Z"},
        {"Value": 130.0, "Wear": 30.0, "Status": "OK", "ReadingDateUtc": "2026-03-01T00:00:00.000000Z"},
    ]}
    entity = sensor.PGNiGMeterReadingSensor(make_coordinator(readings=readings), ENTRY_ID, PPG_1)
    assert entity.native_value == 130.0
    attrs = entity.extra_state_attributes
    assert attrs["Data odczytu"] == "2026-03-01T00:00:00.000000Z"
    assert attrs["Zużycie od poprzedniego odczytu"] == 30.0


def test_wear_sensor_is_total_with_last_reset(agreements):
    invoices = [
        make_invoice("KOREKTA", date="2026-03-01T00:00:00.000000Z", wear_kwh=-100.0, Correction=True),
        make_invoice("GAZ", date="2026-02-01T00:00:00.000000Z", wear_kwh=1234.0, wear_m3=110.0,
                     start="2025-12-01T00:00:00.000000Z", end="2026-01-31T00:00:00.000000Z"),
    ]
    entity = sensor.PGNiGWearSensor(make_coordinator(agreements=agreements, invoices=invoices), ENTRY_ID, PPG_1)
    assert entity.unique_id == f"{DOMAIN}_{ENTRY_ID}_zuzycie_za_okres_{PPG_1}"
    assert entity.state_class == SensorStateClass.TOTAL
    assert entity.native_value == 1234.0
    assert entity.last_reset == datetime(2025, 12, 1, tzinfo=timezone.utc)
    attrs = entity.extra_state_attributes
    assert attrs["Okres rozliczeniowy"] == "2025-12-01 - 2026-01-31"
    assert attrs["Faktura"] == "GAZ"


def test_wear_sensor_without_invoice(agreements):
    entity = sensor.PGNiGWearSensor(make_coordinator(agreements=agreements), ENTRY_ID, PPG_1)
    assert entity.native_value is None
    assert entity.last_reset is None


def test_gas_price_sensor(agreements):
    invoices = [
        make_invoice("ZERO", date="2026-03-01T00:00:00.000000Z", wear_m3=0.0, gross=50.0),
        make_invoice("GAZ", date="2026-02-01T00:00:00.000000Z", gross=600.0, wear_m3=100.0, wear_kwh=1100.0),
    ]
    entity = sensor.PGNiGGasPriceSensor(make_coordinator(agreements=agreements, invoices=invoices), ENTRY_ID, PPG_1)
    assert entity.unique_id == f"{DOMAIN}_{ENTRY_ID}_cena_gazu_{PPG_1}"
    assert entity.native_value == 6.0
    assert entity.native_unit_of_measurement == "PLN/m³"
    assert entity.state_class == SensorStateClass.MEASUREMENT
    assert entity.device_class is None
    attrs = entity.extra_state_attributes
    assert attrs["Faktura"] == "GAZ"
    assert attrs["Cena za kWh"] == 0.5455
    assert attrs["Kwota brutto"] == 600.0
    assert attrs["Zużycie w m³"] == 100.0


def test_agreement_sensor_eco_attribute(agreements):
    entity = sensor.PGNiGAgreementSensor(make_coordinator(agreements=agreements), ENTRY_ID)
    attrs = entity.extra_state_attributes
    assert attrs["Punkty Poboru Gazu (PPG)"] == f"{PPG_1}, {PPG_2}"
    assert attrs["Brak e-faktury (Eco)"] == PPG_2


async def test_setup_entry_creates_entities_without_extra_refresh(agreements):
    coordinator = make_coordinator(
        balance=10.0,
        agreements=agreements,
        invoices=[make_invoice("GAZ")],
        readings={PPG_1: [], PPG_2: []},
        wear_charts={PPG_1: {}, PPG_2: {}},
    )
    hass = MagicMock()
    hass.data = {DOMAIN: {ENTRY_ID: coordinator}}
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    add_entities = MagicMock()

    await sensor.async_setup_entry(hass, entry, add_entities)

    entities, *rest = add_entities.call_args.args
    assert rest == [] and add_entities.call_args.kwargs == {}
    unique_ids = {e.unique_id for e in entities}
    prefix = f"{DOMAIN}_{ENTRY_ID}_"
    assert unique_ids == {
        prefix + "balance",
        prefix + "aktualna_faktura",
        prefix + "najblizsza_prognozowana_faktura",
        prefix + "do_zaplaty",
        prefix + "agreements_count",
        prefix + f"meter_reading_{PPG_1}",
        prefix + f"meter_reading_{PPG_2}",
        prefix + f"zuzycie_za_okres_{PPG_1}",
        prefix + f"zuzycie_za_okres_{PPG_2}",
        prefix + f"cena_gazu_{PPG_1}",
        prefix + f"cena_gazu_{PPG_2}",
    }
