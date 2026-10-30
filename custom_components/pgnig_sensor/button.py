from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Konfiguracja przycisku odświeżania."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PGNiGRefreshButton(coordinator, entry.entry_id)])

class PGNiGRefreshButton(ButtonEntity):
    """Przycisk do ręcznego wymuszenia odświeżenia danych z API."""

    def __init__(self, coordinator, entry_id):
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_refresh_button"
        self._attr_name = "Odśwież dane"
        self._attr_icon = "mdi:refresh"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "PGNiG eBOK",
            "manufacturer": "PGNiG",
            "model": "Konto eBOK",
        }

    async def async_press(self) -> None:
        """Akcja po naciśnięciu przycisku."""
        await self.coordinator.async_request_refresh()
