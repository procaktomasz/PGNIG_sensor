import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PGNiGApi, AuthFailed
from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD, CONF_AUTHTOKEN, CONF_DEVICE_ID, CONF_AUTOMATIC_TOKEN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

class PGNiGDataUpdateCoordinator(DataUpdateCoordinator):
    """Koordynator pobierania danych z PGNiG."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Inicjalizacja."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.entry = entry
        
        # Odtworzenie obiektu API używając zapisanego w ConfigFlow tokenu
        self.api = PGNiGApi(
            hass, 
            entry.data.get(CONF_USERNAME), 
            entry.data.get(CONF_PASSWORD),
            authtoken=entry.data.get(CONF_AUTHTOKEN),
            device_id=entry.data.get(CONF_DEVICE_ID),
            automatic_token=entry.data.get(CONF_AUTOMATIC_TOKEN)
        )

    async def _fetch_all_data(self):
        """Pobiera wszystkie dane ze wszystkich końcówek API."""
        balance_response = await self.api.get_balance()
        balance = balance_response.get("Value") if isinstance(balance_response, dict) else None
        
        agreements_response = await self.api.get_agreements()
        agreements = agreements_response if isinstance(agreements_response, list) else agreements_response.get("Agreements", [])
        
        invoices_response = await self.api.get_invoices()
        invoices = invoices_response.get("InvoicesList", []) if isinstance(invoices_response, dict) else []
        
        # Pobieramy również faktury z odległym terminem płatności (>30 dni)
        invoices_future_response = await self.api.get_invoices(load_after_30_days=True)
        invoices_future = invoices_future_response.get("InvoicesList", []) if isinstance(invoices_future_response, dict) else []
        
        # Łączymy obie listy i usuwamy ewentualne duplikaty
        all_invoices = invoices + invoices_future
        seen = set()
        unique_invoices = []
        for inv in all_invoices:
            num = inv.get("Number")
            if num and num not in seen:
                seen.add(num)
                unique_invoices.append(inv)
                
        invoices = unique_invoices
        if invoices:
            invoices.sort(key=lambda x: x.get("Date", ""), reverse=True)
            
        readings = {}
        wear_charts = {}
        
        for agreement in agreements:
            ppg_id = agreement.get("PpNumber")
            if ppg_id:
                try:
                    reading_res = await self.api.get_readings(ppg_id)
                    meter_readings = reading_res.get("MeterReadings", []) if isinstance(reading_res, dict) else []
                    readings[ppg_id] = meter_readings
                    
                    wear_res = await self.api.get_wear_chart(ppg_id)
                    chart_data = wear_res.get("ChartData", {}) if isinstance(wear_res, dict) else {}
                    wear_charts[ppg_id] = chart_data
                except Exception as e:
                    _LOGGER.error("Błąd podczas pobierania danych licznika %s: %s", ppg_id, e)
        
        return {
            "balance": balance,
            "agreements": agreements,
            "invoices": invoices,
            "readings": readings,
            "wear_charts": wear_charts
        }

    async def _async_update_data(self):
        """Pobierz zaktualizowane dane z serwerów PGNiG."""
        try:
            _LOGGER.debug("Pobieranie danych z PGNiG API...")
            return await self._fetch_all_data()

        except AuthFailed as err:
            # AutomaticToken (odnawiany w api._request) przestał działać. Logowanie hasłem
            # i tak wymagałoby kodu SMS, więc od razu prosimy użytkownika o ponowne uwierzytelnienie.
            _LOGGER.warning("Sesja PGNiG wygasła, wymagane ponowne uwierzytelnienie: %s", err)
            raise ConfigEntryAuthFailed(str(err)) from err
        except Exception as err:
            _LOGGER.error("Błąd podczas pobierania danych z PGNiG: %s", err)
            raise UpdateFailed(f"Błąd API: {err}")
