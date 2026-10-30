import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD, CONF_AUTHTOKEN, CONF_DEVICE_ID, CONF_AUTOMATIC_TOKEN
from .api import PGNiGApi, AuthFailed, CannotConnect

_LOGGER = logging.getLogger(__name__)

class PGNiGConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Obsługa logowania (Config Flow) dla PGNIG."""

    VERSION = 1

    def __init__(self):
        """Inicjalizacja przepływu."""
        self._username = None
        self._password = None
        self._api = None

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Krok 1: Wprowadzenie loginu i hasła."""
        errors = {}
        
        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            
            await self.async_set_unique_id(self._username.lower())
            self._abort_if_unique_id_configured()
            
            self._api = PGNiGApi(self.hass, self._username, self._password)
            
            try:
                result = await self._api.login_step1()
                if result.get("status") == "sms_required":
                    return await self.async_step_sms()
                elif result.get("status") == "success":
                    return self.async_create_entry(
                        title=self._username, 
                        data={
                            CONF_USERNAME: self._username,
                            CONF_PASSWORD: self._password,
                            CONF_AUTHTOKEN: result.get("authtoken"),
                            CONF_DEVICE_ID: self._api.device_id,
                            CONF_AUTOMATIC_TOKEN: result.get("automatic_token")
                        }
                    )
            except CannotConnect as e:
                _LOGGER.error("Brak połączenia z serwerem PGNiG: %s", str(e))
                errors["base"] = "cannot_connect"
            except AuthFailed as e:
                _LOGGER.error("Błąd uwierzytelnienia: %s", str(e))
                errors["base"] = "invalid_auth"
            except Exception as e:
                _LOGGER.exception("Nieoczekiwany błąd: %s", str(e))
                errors["base"] = "unknown"

        data_schema = vol.Schema({
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
        })

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_reconfigure(self, user_input=None) -> FlowResult:
        """Krok wywoływany ręcznie z poziomu interfejsu (Opcja 'Konfiguruj')."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        self._username = entry.data.get(CONF_USERNAME)
        self._password = entry.data.get(CONF_PASSWORD)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth(self, entry_data) -> FlowResult:
        """Krok wywoływany automatycznie przez HA po wygaśnięciu tokenu."""
        self._username = entry_data.get(CONF_USERNAME)
        self._password = entry_data.get(CONF_PASSWORD)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> FlowResult:
        """Krok weryfikacji hasła i ponownego podłączenia."""
        errors = {}
        if user_input is not None:
            self._password = user_input[CONF_PASSWORD]
            entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
            device_id = entry.data.get(CONF_DEVICE_ID) if entry else None
            
            self._api = PGNiGApi(self.hass, self._username, self._password, device_id=device_id)
            try:
                result = await self._api.login_step1()
                if result.get("status") == "sms_required":
                    return await self.async_step_sms()
                elif result.get("status") == "success":
                    self.hass.config_entries.async_update_entry(
                        entry, data={
                            **entry.data, 
                            CONF_AUTHTOKEN: result.get("authtoken"), 
                            CONF_PASSWORD: self._password,
                            CONF_DEVICE_ID: self._api.device_id,
                            CONF_AUTOMATIC_TOKEN: result.get("automatic_token")
                        }
                    )
                    self.hass.async_create_task(
                        self.hass.config_entries.async_reload(entry.entry_id)
                    )
                    return self.async_abort(reason="reauth_successful")
            except CannotConnect as e:
                _LOGGER.error("Brak połączenia z serwerem PGNiG: %s", str(e))
                errors["base"] = "cannot_connect"
            except AuthFailed as e:
                _LOGGER.error("Błąd uwierzytelnienia: %s", str(e))
                errors["base"] = "invalid_auth"
            except Exception as e:
                _LOGGER.exception("Nieoczekiwany błąd: %s", str(e))
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD, default=self._password or ""): str}),
            errors=errors,
            description_placeholders={"username": self._username}
        )

    async def async_step_sms(self, user_input=None) -> FlowResult:
        """Krok 2: Wprowadzenie kodu SMS."""
        errors = {}
        
        if user_input is not None:
            sms_code = user_input.get("sms_code")
            try:
                result = await self._api.login_step2(sms_code)
                if result.get("status") == "success":
                    # Ponowne logowanie i rekonfiguracja aktualizują istniejący wpis zamiast tworzyć nowy
                    if self.source in (config_entries.SOURCE_REAUTH, config_entries.SOURCE_RECONFIGURE):
                        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
                        self.hass.config_entries.async_update_entry(
                            entry, data={
                                **entry.data, 
                                CONF_AUTHTOKEN: result.get("authtoken"), 
                                CONF_PASSWORD: self._password,
                                CONF_DEVICE_ID: self._api.device_id,
                                CONF_AUTOMATIC_TOKEN: result.get("automatic_token")
                            }
                        )
                        self.hass.async_create_task(
                            self.hass.config_entries.async_reload(entry.entry_id)
                        )
                        return self.async_abort(reason="reauth_successful")
                    else:
                        return self.async_create_entry(
                            title=self._username, 
                            data={
                                CONF_USERNAME: self._username,
                                CONF_PASSWORD: self._password,
                                CONF_AUTHTOKEN: result.get("authtoken"),
                                CONF_DEVICE_ID: self._api.device_id,
                                CONF_AUTOMATIC_TOKEN: result.get("automatic_token")
                            }
                        )
            except CannotConnect as e:
                _LOGGER.error("Brak połączenia z serwerem PGNiG (SMS): %s", str(e))
                errors["base"] = "cannot_connect"
            except AuthFailed as e:
                _LOGGER.error("Błąd uwierzytelnienia (SMS): %s", str(e))
                errors["base"] = "invalid_sms"
            except Exception as e:
                _LOGGER.exception("Nieoczekiwany błąd (SMS): %s", str(e))
                errors["base"] = "unknown"

        data_schema = vol.Schema({
            vol.Required("sms_code"): str,
        })

        return self.async_show_form(
            step_id="sms", data_schema=data_schema, errors=errors
        )
