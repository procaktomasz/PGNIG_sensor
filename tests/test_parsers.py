"""Testy czystej logiki wyboru danych (parsers.py)."""
from datetime import datetime, timezone

import pytest

from custom_components.pgnig_sensor import parsers
from tests.conftest import CRD_1, CRD_2, PPG_1, PPG_2, make_invoice


def test_gas_collection_points_maps_crd_to_ppg(agreements):
    points = parsers.gas_collection_points(agreements)
    assert points == {CRD_1: PPG_1, CRD_2: PPG_2}


def test_gas_collection_points_includes_nested_collection_points():
    agreements = [{"PpNumber": PPG_1, "CollectionPoints": [{"IdCRD": CRD_1}]}]
    assert parsers.gas_collection_points(agreements) == {CRD_1: PPG_1}


@pytest.mark.parametrize(
    "flag",
    ["IsCreditNote", "IsInterestNote", "Correction", "IsInsurancePolicy",
     "IsLawyerAgreement", "IsHomeAssistant", "IsVirtualSafe", "IsAdditionalAgreement"],
)
def test_is_gas_invoice_excludes_flagged_invoices(agreements, flag):
    points = parsers.gas_collection_points(agreements)
    assert parsers.is_gas_invoice(make_invoice("F/1"), points)
    assert not parsers.is_gas_invoice(make_invoice("F/2", **{flag: True}), points)


def test_is_gas_invoice_excludes_unknown_collection_point(agreements):
    points = parsers.gas_collection_points(agreements)
    assert not parsers.is_gas_invoice(make_invoice("F/1", id_pp="9999999"), points)


def test_is_gas_invoice_without_known_points_falls_back_to_flags():
    assert parsers.is_gas_invoice(make_invoice("F/1", id_pp="9999999"), {})
    assert not parsers.is_gas_invoice(make_invoice("F/2", IsInsurancePolicy=True), {})


def test_latest_gas_invoice_skips_newer_non_gas_invoices(agreements):
    invoices = [
        make_invoice("POLISA", date="2026-03-01T00:00:00.000000Z", IsInsurancePolicy=True),
        make_invoice("KOREKTA", date="2026-02-15T00:00:00.000000Z", IsCreditNote=True, gross=-20.0),
        make_invoice("GAZ/NEW", date="2026-02-01T00:00:00.000000Z"),
        make_invoice("GAZ/OLD", date="2026-01-01T00:00:00.000000Z"),
    ]
    assert parsers.latest_gas_invoice(invoices, agreements)["Number"] == "GAZ/NEW"


def test_latest_gas_invoice_empty(agreements):
    assert parsers.latest_gas_invoice([], agreements) is None


def test_unpaid_gas_invoices_sorted_by_deadline(agreements):
    invoices = [
        make_invoice("P/2", paid=False, status="NotPaid", deadline="2026-04-15T00:00:00.000000Z"),
        make_invoice("P/1", paid=False, status="NotPaid", deadline="2026-03-15T00:00:00.000000Z"),
        make_invoice("PAID", paid=True),
        make_invoice("POLISA", paid=False, IsInsurancePolicy=True),
    ]
    result = parsers.unpaid_gas_invoices(invoices, agreements)
    assert [inv["Number"] for inv in result] == ["P/1", "P/2"]


def test_unpaid_gas_invoices_tolerates_missing_status_and_dates(agreements):
    invoices = [
        make_invoice("A", paid=None, status=None, deadline=None, date=None),
        make_invoice("B", paid=False, status=None, deadline=None),
    ]
    result = parsers.unpaid_gas_invoices(invoices, agreements)
    assert [inv["Number"] for inv in result] == ["B"]


def test_amount_to_pay_prefers_remaining_amount():
    assert parsers.amount_to_pay(make_invoice("A", gross=300.0, to_pay=120.5)) == 120.5
    assert parsers.amount_to_pay(make_invoice("B", gross=300.0, to_pay=None)) == 300.0
    assert parsers.amount_to_pay(make_invoice("C", gross=None, to_pay=None)) is None


def test_amount_due_summary(agreements):
    invoices = [
        make_invoice("P/1", paid=False, status="NotPaid", to_pay=100.10,
                     deadline="2026-03-15T00:00:00.000000Z", days_remaining=-2),
        make_invoice("P/2", id_pp=CRD_2, paid=False, status="NotPaid", to_pay=50.25,
                     deadline="2026-04-15T00:00:00.000000Z", days_remaining=30),
        make_invoice("POLISA", paid=False, to_pay=999.0, IsInsurancePolicy=True),
        make_invoice("KOREKTA", paid=False, to_pay=-40.0, IsCreditNote=True),
        make_invoice("PAID", paid=True, to_pay=0.0),
    ]
    summary = parsers.amount_due_summary(invoices, agreements)
    assert summary == {
        "total": 150.35,
        "count": 2,
        "next_deadline": "2026-03-15T00:00:00.000000Z",
        "next_amount": 100.10,
        "overdue_count": 1,
    }


def test_amount_due_summary_nothing_to_pay(agreements):
    summary = parsers.amount_due_summary([make_invoice("PAID")], agreements)
    assert summary == {
        "total": 0.0,
        "count": 0,
        "next_deadline": None,
        "next_amount": None,
        "overdue_count": 0,
    }


def test_latest_invoice_for_ppg_filters_by_collection_point(agreements):
    invoices = [
        make_invoice("PPG2/NEW", id_pp=CRD_2, date="2026-03-01T00:00:00.000000Z"),
        make_invoice("PPG1/NEW", id_pp=CRD_1, date="2026-02-01T00:00:00.000000Z"),
        make_invoice("PPG1/OLD", id_pp=CRD_1, date="2026-01-01T00:00:00.000000Z"),
    ]
    assert parsers.latest_invoice_for_ppg(invoices, agreements, PPG_1)["Number"] == "PPG1/NEW"
    assert parsers.latest_invoice_for_ppg(invoices, agreements, "PL_NIEZNANY") is None


def test_latest_invoice_for_ppg_skips_corrections(agreements):
    invoices = [
        make_invoice("KOREKTA", date="2026-03-01T00:00:00.000000Z", Correction=True),
        make_invoice("GAZ", date="2026-02-01T00:00:00.000000Z"),
    ]
    assert parsers.latest_invoice_for_ppg(invoices, agreements, PPG_1)["Number"] == "GAZ"


def test_latest_invoice_for_ppg_require_consumption(agreements):
    invoices = [
        make_invoice("ZERO", date="2026-03-01T00:00:00.000000Z", wear_m3=0.0),
        make_invoice("OK", date="2026-02-01T00:00:00.000000Z", wear_m3=40.0),
    ]
    assert parsers.latest_invoice_for_ppg(invoices, agreements, PPG_1)["Number"] == "ZERO"
    result = parsers.latest_invoice_for_ppg(invoices, agreements, PPG_1, require_consumption=True)
    assert result["Number"] == "OK"


def test_gas_price():
    assert parsers.gas_price(make_invoice("A", gross=500.0, wear_m3=100.0)) == 5.0
    assert parsers.gas_price(make_invoice("B", gross=100.0, wear_m3=3.0)) == 33.333
    assert parsers.gas_price(make_invoice("C", gross=500.0, wear_m3=0.0)) is None
    assert parsers.gas_price(make_invoice("D", gross=None, wear_m3=10.0)) is None
    assert parsers.gas_price(None) is None


def test_gas_price_per_kwh():
    assert parsers.gas_price_per_kwh(make_invoice("A", gross=550.0, wear_kwh=1000.0)) == 0.55
    assert parsers.gas_price_per_kwh(make_invoice("B", gross=550.0, wear_kwh=0.0)) is None


def test_latest_reading_picks_newest_regardless_of_order():
    readings = [
        {"Value": 100.0, "ReadingDateUtc": "2026-01-01T00:00:00.000000Z"},
        {"Value": 300.0, "ReadingDateUtc": "2026-03-01T00:00:00.000000Z"},
        {"Value": 200.0, "ReadingDateUtc": "2026-02-01T00:00:00.000000Z"},
    ]
    assert parsers.latest_reading(readings)["Value"] == 300.0
    assert parsers.latest_reading([]) is None


def test_agreements_without_eco(agreements):
    assert parsers.agreements_without_eco(agreements) == [PPG_2]


def test_parse_datetime():
    assert parsers.parse_datetime("2025-11-01T00:00:00.000000Z") == datetime(2025, 11, 1, tzinfo=timezone.utc)
    assert parsers.parse_datetime("2025-11-01T00:00:00") == datetime(2025, 11, 1, tzinfo=timezone.utc)
    assert parsers.parse_datetime("nie-data") is None
    assert parsers.parse_datetime(None) is None
