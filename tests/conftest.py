"""Wspólne fixture'y testów. Wszystkie dane są fikcyjne (anonimizowane)."""
import pytest

PPG_1 = "PL0000000000000000000001"
PPG_2 = "PL0000000000000000000002"
CRD_1 = "1000001"
CRD_2 = "1000002"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Włącza ładowanie integracji z katalogu custom_components."""
    yield


def make_invoice(
    number,
    id_pp=CRD_1,
    date="2026-01-10T00:00:00.000000Z",
    deadline="2026-01-31T00:00:00.000000Z",
    gross=100.0,
    to_pay=0.0,
    paid=True,
    status="Posted",
    wear_m3=50.0,
    wear_kwh=550.0,
    start="2025-11-01T00:00:00.000000Z",
    end="2025-12-31T00:00:00.000000Z",
    days_remaining=10,
    **flags,
):
    """Buduje fakturę o strukturze zgodnej z odpowiedzią /crm/get-invoices-v2."""
    invoice = {
        "Number": number,
        "Date": date,
        "PayingDeadlineDate": deadline,
        "GrossAmount": gross,
        "AmountToPay": to_pay,
        "IsPaid": paid,
        "Status": status,
        "WearM3": wear_m3,
        "WearKWH": wear_kwh,
        "Wear": wear_m3,
        "StartDate": start,
        "EndDate": end,
        "IdPP": id_pp,
        "Type": "PPG",
        "DaysRemainingToDeadline": days_remaining,
        "HasNonPaidForecast": False,
        "IsCreditNote": False,
        "IsInterestNote": False,
        "Correction": False,
        "IsInsurancePolicy": False,
        "IsLawyerAgreement": False,
        "IsHomeAssistant": False,
        "IsVirtualSafe": False,
        "IsAdditionalAgreement": False,
    }
    invoice.update(flags)
    return invoice


@pytest.fixture
def agreements():
    """Dwie umowy gazowe i jedna umowa bez punktu poboru (np. polisa)."""
    return [
        {"PpNumber": PPG_1, "CollectionPointIdCRD": CRD_1, "EcoInvoice": True, "AgreementNumber": "UM/1"},
        {"PpNumber": PPG_2, "CollectionPointIdCRD": CRD_2, "EcoInvoice": False, "AgreementNumber": "UM/2"},
        {"AgreementNumber": "POLISA/1", "EcoInvoice": True},
    ]
