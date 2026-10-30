"""Logika wyboru danych z odpowiedzi API PGNiG (bez zależności od Home Assistanta)."""
from datetime import datetime, timezone

# Faktury, które nie dotyczą zużycia gazu (korekty, noty, produkty dodatkowe)
EXCLUDED_INVOICE_FLAGS = (
    "IsCreditNote",
    "IsInterestNote",
    "Correction",
    "IsInsurancePolicy",
    "IsLawyerAgreement",
    "IsPersonalSecurityAgreement",
    "IsHomeAssistant",
    "IsVirtualSafe",
    "IsAdditionalAgreement",
)

UNPAID_STATUSES = ("notpaid", "niezapłacona")


def parse_datetime(value):
    """Zamienia datę ISO z API (np. '2025-11-01T00:00:00.000000Z') na datetime w UTC."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _to_float(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def gas_collection_points(agreements):
    """Zwraca mapę IdCRD punktu poboru -> numer PPG dla umów gazowych."""
    points = {}
    for agreement in agreements or []:
        ppg_id = agreement.get("PpNumber")
        if not ppg_id:
            continue
        id_crd = agreement.get("CollectionPointIdCRD")
        if id_crd:
            points[str(id_crd)] = ppg_id
        for point in agreement.get("CollectionPoints") or []:
            if point.get("IdCRD"):
                points[str(point["IdCRD"])] = ppg_id
    return points


def is_gas_invoice(invoice, gas_points):
    """Czy faktura dotyczy gazu (a nie korekty, noty lub produktu dodatkowego)."""
    if any(invoice.get(flag) for flag in EXCLUDED_INVOICE_FLAGS):
        return False
    # Bez znanych punktów poboru polegamy wyłącznie na flagach
    if gas_points:
        return str(invoice.get("IdPP")) in gas_points
    return True


def gas_invoices(invoices, agreements):
    """Filtruje listę faktur do faktur gazowych, zachowując kolejność."""
    points = gas_collection_points(agreements)
    return [inv for inv in invoices or [] if is_gas_invoice(inv, points)]


def latest_gas_invoice(invoices, agreements):
    """Najnowsza (wg daty wystawienia) faktura gazowa."""
    candidates = gas_invoices(invoices, agreements)
    if not candidates:
        return None
    return max(candidates, key=lambda inv: inv.get("Date") or "")


def is_unpaid(invoice):
    status = str(invoice.get("Status") or "").lower()
    return invoice.get("IsPaid") is False or status in UNPAID_STATUSES


def unpaid_gas_invoices(invoices, agreements):
    """Nieopłacone faktury gazowe posortowane od najbliższego terminu płatności."""
    unpaid = [inv for inv in gas_invoices(invoices, agreements) if is_unpaid(inv)]
    return sorted(unpaid, key=lambda inv: inv.get("PayingDeadlineDate") or inv.get("Date") or "")


def amount_to_pay(invoice):
    """Kwota pozostała do zapłaty (uwzględnia częściowe wpłaty)."""
    amount = invoice.get("AmountToPay")
    if amount is None:
        amount = invoice.get("GrossAmount")
    return _to_float(amount)


def amount_due_summary(invoices, agreements):
    """Podsumowanie wszystkich nieopłaconych faktur gazowych."""
    unpaid = unpaid_gas_invoices(invoices, agreements)
    total = sum(amount_to_pay(inv) or 0.0 for inv in unpaid)
    nearest = unpaid[0] if unpaid else None
    overdue = sum(
        1 for inv in unpaid
        if isinstance(inv.get("DaysRemainingToDeadline"), int) and inv["DaysRemainingToDeadline"] < 0
    )
    return {
        "total": round(total, 2),
        "count": len(unpaid),
        "next_deadline": nearest.get("PayingDeadlineDate") if nearest else None,
        "next_amount": amount_to_pay(nearest) if nearest else None,
        "overdue_count": overdue,
    }


def latest_invoice_for_ppg(invoices, agreements, ppg_id, require_consumption=False):
    """Najnowsza faktura gazowa dla danego PPG (opcjonalnie tylko z niezerowym zużyciem)."""
    points = gas_collection_points(agreements)
    candidates = [
        inv for inv in invoices or []
        if is_gas_invoice(inv, points) and points.get(str(inv.get("IdPP"))) == ppg_id
    ]
    if require_consumption:
        candidates = [
            inv for inv in candidates
            if (_to_float(inv.get("WearM3") or inv.get("Wear")) or 0) > 0
            and (_to_float(inv.get("GrossAmount")) or 0) > 0
        ]
    if not candidates:
        return None
    return max(candidates, key=lambda inv: inv.get("Date") or "")


def gas_price(invoice):
    """Średni koszt brutto 1 m³ gazu z faktury (paliwo + dystrybucja + opłaty stałe)."""
    if not invoice:
        return None
    gross = _to_float(invoice.get("GrossAmount"))
    wear_m3 = _to_float(invoice.get("WearM3") or invoice.get("Wear"))
    if gross is None or not wear_m3:
        return None
    return round(gross / wear_m3, 3)


def gas_price_per_kwh(invoice):
    """Średni koszt brutto 1 kWh gazu z faktury."""
    if not invoice:
        return None
    gross = _to_float(invoice.get("GrossAmount"))
    wear_kwh = _to_float(invoice.get("WearKWH"))
    if gross is None or not wear_kwh:
        return None
    return round(gross / wear_kwh, 4)


def latest_reading(readings):
    """Najnowszy odczyt licznika wg daty odczytu (niezależnie od kolejności listy)."""
    if not readings:
        return None
    return max(readings, key=lambda r: r.get("ReadingDateUtc") or r.get("ReadingDateLocal") or "")


def agreements_without_eco(agreements):
    """Numery PPG umów, dla których nie włączono e-faktury."""
    return [
        a.get("PpNumber") or a.get("AgreementNumber")
        for a in agreements or []
        if a.get("EcoInvoice") is False
    ]
