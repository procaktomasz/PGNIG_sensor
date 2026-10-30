import logging

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import parsers
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Konfiguracja sensorów na podstawie danych z koordynatora."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []

    # Podstawowe sensory: Saldo, Najnowsza Faktura, Do Zapłaty, Liczba Umów
    entities.append(PGNiGAccountBalanceSensor(coordinator, entry.entry_id))
    entities.append(PGNiGAmountDueSensor(coordinator, entry.entry_id))

    invoices = coordinator.data.get("invoices", [])
    if invoices:
        entities.append(PGNiGLatestInvoiceSensor(coordinator, entry.entry_id))
        entities.append(PGNiGUnpaidInvoiceSensor(coordinator, entry.entry_id))

    agreements = coordinator.data.get("agreements", [])
    if agreements:
        entities.append(PGNiGAgreementSensor(coordinator, entry.entry_id))

        # Generowanie sensorów dla każdego Punktu Poboru Gazu (PPG)
        for agreement in agreements:
            ppg_id = agreement.get("PpNumber")
            if ppg_id:
                # Sensor odczytu z licznika
                if ppg_id in coordinator.data.get("readings", {}):
                    entities.append(PGNiGMeterReadingSensor(coordinator, entry.entry_id, ppg_id))

                # Sensor wykresu zużycia dla bieżącego miesiąca
                if ppg_id in coordinator.data.get("wear_charts", {}):
                    entities.append(PGNiGWearSensor(coordinator, entry.entry_id, ppg_id))

                # Sensor średniej ceny gazu z ostatniej faktury
                entities.append(PGNiGGasPriceSensor(coordinator, entry.entry_id, ppg_id))

    # Dane są już pobrane przez koordynatora - bez dodatkowego odświeżenia przy dodawaniu encji
    async_add_entities(entities)


class PGNiGSensorBase(CoordinatorEntity, SensorEntity):
    """Bazowa klasa dla sensora PGNIG."""

    def __init__(self, coordinator, entry_id, entity_suffix):
        super().__init__(coordinator)
        self._entry_id = entry_id
        # Unikalny identyfikator zachowujący regułę kompatybilności
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{entity_suffix}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "PGNiG eBOK",
            "manufacturer": "PGNiG",
            "model": "Konto eBOK",
        }


class PGNiGAccountBalanceSensor(PGNiGSensorBase):
    """Sensor bieżącego salda."""

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator, entry_id, "balance")
        self._attr_name = "Saldo"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "PLN"
        self._attr_state_class = SensorStateClass.TOTAL

    @property
    def native_value(self):
        balance = self.coordinator.data.get("balance")
        if balance is not None:
            try:
                return float(balance)
            except (ValueError, TypeError):
                pass
        return None


class PGNiGLatestInvoiceSensor(PGNiGSensorBase):
    """Sensor najnowszej wystawionej faktury (niezależnie od statusu opłacenia)."""

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator, entry_id, "aktualna_faktura")
        self._attr_name = "Aktualna faktura"
        self._attr_icon = "mdi:receipt"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "PLN"

    def _latest(self):
        # Tylko faktury gazowe - bez korekt, not odsetkowych i produktów dodatkowych
        return parsers.latest_gas_invoice(
            self.coordinator.data.get("invoices", []),
            self.coordinator.data.get("agreements", []),
        )

    @property
    def native_value(self):
        latest = self._latest()
        if latest:
            amount = latest.get("GrossAmount") or latest.get("AmountToPay")
            try:
                return float(amount)
            except (ValueError, TypeError):
                pass
        return None

    @property
    def extra_state_attributes(self):
        latest = self._latest()
        attrs = {}
        if latest:
            attrs["Numer Faktury"] = latest.get("Number")
            attrs["Data Wystawienia"] = latest.get("Date")
            attrs["Data Płatności"] = latest.get("PayingDeadlineDate")
            attrs["Status"] = latest.get("Status")
            attrs["Rodzaj"] = latest.get("Type")
            attrs["Czy posiada nieopłaconą prognozę"] = latest.get("HasNonPaidForecast")
        return attrs


class PGNiGUnpaidInvoiceSensor(PGNiGSensorBase):
    """Sensor najbliższej faktury (prognozy), która nie została jeszcze opłacona."""

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator, entry_id, "najblizsza_prognozowana_faktura")
        self._attr_name = "Najbliższa Prognozowana Faktura"
        self._attr_icon = "mdi:cash-fast"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "PLN"

    def _get_target_invoice(self):
        # Faktury prognozowane mają tę samą datę wystawienia (Date), więc sortujemy je po terminie płatności.
        unpaid = parsers.unpaid_gas_invoices(
            self.coordinator.data.get("invoices", []),
            self.coordinator.data.get("agreements", []),
        )
        return unpaid[0] if unpaid else None

    @property
    def native_value(self):
        target = self._get_target_invoice()
        if target:
            # Kwota pozostała do zapłaty (uwzględnia częściowe wpłaty)
            amount = parsers.amount_to_pay(target)
            if amount is not None:
                return amount
        return 0.0

    @property
    def extra_state_attributes(self):
        target = self._get_target_invoice()
        attrs = {}
        if target:
            attrs["Numer Faktury"] = target.get("Number")
            attrs["Data Wystawienia"] = target.get("Date")
            attrs["Data Płatności"] = target.get("PayingDeadlineDate")
            attrs["Status"] = target.get("Status")
            attrs["Rodzaj"] = target.get("Type")
        else:
            attrs["Informacja"] = "Wszystkie faktury są opłacone"
        return attrs


class PGNiGAgreementSensor(PGNiGSensorBase):
    """Sensor dla ogólnych informacji o umowach na koncie."""

    def __init__(self, coordinator, entry_id):
        # Zachowujemy 'agreements_count' żeby nie rzucało błędów encji
        super().__init__(coordinator, entry_id, "agreements_count")
        self._attr_name = "Aktywne Umowy"
        self._attr_icon = "mdi:file-document-outline"

    @property
    def native_value(self):
        # Stan to po prostu liczba posiadanych umów
        agreements = self.coordinator.data.get("agreements", [])
        return len(agreements)

    @property
    def extra_state_attributes(self):
        agreements = self.coordinator.data.get("agreements", [])
        attrs = {}

        lista_ppg = [a.get("PpNumber") for a in agreements if a.get("PpNumber")]
        lista_eco = parsers.agreements_without_eco(agreements)

        attrs["Punkty Poboru Gazu (PPG)"] = ", ".join(lista_ppg)
        if lista_eco:
            attrs["Brak e-faktury (Eco)"] = ", ".join(lista_eco)

        return attrs


class PGNiGMeterReadingSensor(PGNiGSensorBase):
    """Sensor dla ostatniego odczytu z licznika w konkretnym PPG."""

    def __init__(self, coordinator, entry_id, ppg_id):
        super().__init__(coordinator, entry_id, f"meter_reading_{ppg_id}")
        self._attr_name = f"Odczyt Licznika ({ppg_id})"
        self._ppg_id = ppg_id
        self._attr_device_class = SensorDeviceClass.GAS
        self._attr_native_unit_of_measurement = "m³"
        self._attr_state_class = SensorStateClass.TOTAL

    @property
    def native_value(self):
        readings = self.coordinator.data.get("readings", {}).get(self._ppg_id, [])
        latest_reading = parsers.latest_reading(readings)
        if latest_reading:
            val = latest_reading.get("Value")
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
        return None

    @property
    def extra_state_attributes(self):
        readings = self.coordinator.data.get("readings", {}).get(self._ppg_id, [])
        latest = parsers.latest_reading(readings)
        attrs = {}
        if latest:
            attrs["Data odczytu"] = latest.get("ReadingDateUtc") or latest.get("ReadingDateLocal")
            attrs["Status odczytu"] = latest.get("Status")
            attrs["Zużycie od poprzedniego odczytu"] = latest.get("Wear")
        return attrs


class PGNiGWearSensor(PGNiGSensorBase):
    """Sensor zużycia za ostatni okres rozliczeniowy (na podstawie faktury).

    Wartość dotyczy jednego okresu, dlatego state_class=TOTAL z last_reset ustawionym
    na początek okresu - statystyki HA liczą każdą nową fakturę w całości.
    """

    def __init__(self, coordinator, entry_id, ppg_id):
        super().__init__(coordinator, entry_id, f"zuzycie_za_okres_{ppg_id}")
        self._ppg_id = ppg_id
        self._attr_name = f"Zużycie za okres ({ppg_id})"
        self._attr_icon = "mdi:chart-bar"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_native_unit_of_measurement = "kWh"
        self._attr_state_class = SensorStateClass.TOTAL

    @property
    def _latest_invoice(self):
        # Najnowsza faktura gazowa tego punktu (bez korekt)
        return parsers.latest_invoice_for_ppg(
            self.coordinator.data.get("invoices", []),
            self.coordinator.data.get("agreements", []),
            self._ppg_id,
        )

    @property
    def last_reset(self):
        inv = self._latest_invoice
        return parsers.parse_datetime(inv.get("StartDate")) if inv else None

    @property
    def native_value(self):
        inv = self._latest_invoice
        if inv:
            try:
                # W JSON z HAR aplikacja korzysta z WearKWH
                return float(inv.get("WearKWH", 0.0))
            except (ValueError, TypeError):
                pass
        return None

    @property
    def extra_state_attributes(self):
        inv = self._latest_invoice
        attrs = {}
        if inv:
            start = (inv.get("StartDate") or "")[:10]
            end = (inv.get("EndDate") or "")[:10]
            attrs["Okres rozliczeniowy"] = f"{start} - {end}" if start and end else "Brak danych"
            attrs["Faktura"] = inv.get("Number")
            attrs["Zużycie w m³"] = inv.get("WearM3")
        return attrs


class PGNiGAmountDueSensor(PGNiGSensorBase):
    """Sensor sumy wszystkich nieopłaconych faktur za gaz."""

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator, entry_id, "do_zaplaty")
        self._attr_name = "Do zapłaty"
        self._attr_icon = "mdi:cash-clock"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "PLN"
        self._attr_state_class = SensorStateClass.TOTAL

    def _summary(self):
        return parsers.amount_due_summary(
            self.coordinator.data.get("invoices", []),
            self.coordinator.data.get("agreements", []),
        )

    @property
    def native_value(self):
        return self._summary()["total"]

    @property
    def extra_state_attributes(self):
        summary = self._summary()
        return {
            "Liczba nieopłaconych faktur": summary["count"],
            "Najbliższy termin płatności": summary["next_deadline"],
            "Kwota najbliższej płatności": summary["next_amount"],
            "Faktury po terminie": summary["overdue_count"],
        }


class PGNiGGasPriceSensor(PGNiGSensorBase):
    """Sensor średniego kosztu brutto 1 m³ gazu z ostatniej faktury.

    Obejmuje paliwo, dystrybucję i opłaty stałe - nie jest to cena z taryfy.
    """

    def __init__(self, coordinator, entry_id, ppg_id):
        super().__init__(coordinator, entry_id, f"cena_gazu_{ppg_id}")
        self._ppg_id = ppg_id
        self._attr_name = f"Cena gazu ({ppg_id})"
        self._attr_icon = "mdi:cash-multiple"
        # Brak device_class: MONETARY nie dopuszcza jednostki PLN/m³
        self._attr_native_unit_of_measurement = "PLN/m³"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def _invoice(self):
        return parsers.latest_invoice_for_ppg(
            self.coordinator.data.get("invoices", []),
            self.coordinator.data.get("agreements", []),
            self._ppg_id,
            require_consumption=True,
        )

    @property
    def native_value(self):
        return parsers.gas_price(self._invoice)

    @property
    def extra_state_attributes(self):
        inv = self._invoice
        attrs = {}
        if inv:
            start = (inv.get("StartDate") or "")[:10]
            end = (inv.get("EndDate") or "")[:10]
            attrs["Faktura"] = inv.get("Number")
            attrs["Okres rozliczeniowy"] = f"{start} - {end}" if start and end else "Brak danych"
            attrs["Kwota brutto"] = inv.get("GrossAmount")
            attrs["Zużycie w m³"] = inv.get("WearM3")
            attrs["Zużycie w kWh"] = inv.get("WearKWH")
            attrs["Cena za kWh"] = parsers.gas_price_per_kwh(inv)
        return attrs
