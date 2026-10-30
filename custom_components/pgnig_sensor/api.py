import asyncio
import logging
import base64
import hashlib
import re
import urllib.parse
import uuid

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
_LOGGER = logging.getLogger(__name__)

class AuthFailed(Exception):
    pass

class APIError(Exception):
    pass

class CannotConnect(Exception):
    pass

class PGNiGApi:
    def __init__(self, hass, username, password, authtoken=None, device_id=None, automatic_token=None):
        self.hass = hass
        self.username = username
        self.password = password
        self.authtoken = authtoken
        self.automatic_token = automatic_token
        
        self.code_verifier = None
        self.sms_action_url = None
        self.device_id = device_id or str(uuid.uuid4()).replace('-', '')
        self.cookie_jar = aiohttp.CookieJar()
        
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"

    def _new_session(self):
        """Osobna sesja HTTP dla logowania (cookies Keycloak muszą przetrwać między krokami)."""
        return aiohttp.ClientSession(cookie_jar=self.cookie_jar)

    async def refresh_automatic_token(self):
        """Używa AutomaticToken z aplikacji mobilnej do cichego odnowienia sesji."""
        if not self.automatic_token:
            return False
            
        _LOGGER.debug("Attempting to refresh session using AutomaticToken")
        session = async_get_clientsession(self.hass)
        url = "https://mbok.myorlen.pl/auth/login-automatic-token?api-version=3.0"
        payload = {
            "AutomaticToken": self.automatic_token,
            "DeviceId": self.device_id
        }
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        try:
            async with session.post(url, json=payload, headers=headers) as r:
                if r.status == 200:
                    data = await r.json()
                    self.authtoken = data.get("Token")
                    
                    new_automatic = data.get("AutomaticLoginToken")
                    if new_automatic:
                        self.automatic_token = new_automatic
                        
                    _LOGGER.debug("Successfully refreshed session via AutomaticToken")
                    return True
                else:
                    _LOGGER.error("Failed to refresh via AutomaticToken: %s", await r.text())
                    return False
        except Exception as e:
            _LOGGER.error("Exception during AutomaticToken refresh: %s", e)
            return False

    def _generate_pkce(self):
        import secrets
        code_verifier = secrets.token_urlsafe(32)
        code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')
        return code_verifier, code_challenge

    async def login_step1(self):
        """Krok 1: Wysłanie loginu i hasła, sprawdzenie czy potrzebny kod SMS. Symulacja aplikacji mobilnej."""
        self.cookie_jar.clear()
        self.code_verifier, code_challenge = self._generate_pkce()
        
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

        # OIDC init dla mobile
        state = "state" + self.device_id[:10]
        auth_url = f"https://oid-ws.orlen.pl/realms/oid/protocol/openid-connect/auth?response_type=code&code_challenge_method=S256&scope=openid&client_id=pgnig-mobile&redirect_uri=mbok%3A%2F%2Fpgnigapp.pl%2Foid-login&state={state}&code_challenge={code_challenge}"

        try:
            async with self._new_session() as session:
                async with session.get(auth_url, headers=headers) as res1:
                    text = await res1.text()

                match = re.search(r'action="([^"]+)"', text)
                if not match:
                    _LOGGER.error("Cannot find login form action URL in OIDC response.")
                    raise AuthFailed("Form action not found")

                action_url = match.group(1).replace("&amp;", "&")
                payload = {"username": self.username, "password": self.password, "credentialId": ""}

                async with session.post(action_url, data=payload, headers=headers, allow_redirects=False) as res2:
                    text2 = await res2.text()

                if "kc-sms-code-login-form" in text2:
                    match_action = re.search(r'id="kc-sms-code-login-form"[^>]*action="([^"]+)"', text2)
                    if not match_action:
                        raise AuthFailed("SMS action not found")
                    self.sms_action_url = match_action.group(1).replace("&amp;", "&")
                    return {"status": "sms_required"}
                elif res2.status == 302:
                    redirect_url = res2.headers.get('Location')
                    return await self._process_redirect(session, redirect_url)
                else:
                    error_msg = "Invalid credentials"
                    match_err = re.search(r'<p class="instruction">(.*?)</p>', text2)
                    if match_err:
                        error_msg = match_err.group(1)
                    raise AuthFailed(error_msg)
        except AuthFailed as e:
            _LOGGER.error("Błąd podczas logowania 1. etapu: %s", e)
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            _LOGGER.error("Brak połączenia z serwerem podczas logowania 1. etapu: %s", e)
            raise CannotConnect(str(e)) from e
        except Exception as e:
            _LOGGER.error("Błąd podczas logowania 1. etapu: %s", e)
            raise AuthFailed(str(e)) from e

    async def login_step2(self, sms_code):
        """Krok 2: Wysłanie kodu SMS i zakończenie logowania w trybie mobilnym."""
        headers = {"User-Agent": self.user_agent}

        sms_payload = {
            "code": sms_code,
            "step": "codeValidation",
            "submit": "Potwierdź"
        }

        try:
            async with self._new_session() as session:
                async with session.post(self.sms_action_url, data=sms_payload, headers=headers, allow_redirects=False) as res_sms:
                    if res_sms.status != 302:
                        raise AuthFailed("Invalid SMS code")
                    redirect_url = res_sms.headers.get('Location')
                return await self._process_redirect(session, redirect_url)
        except AuthFailed as e:
            _LOGGER.error("Błąd podczas logowania 2. etapu (SMS): %s", e)
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            _LOGGER.error("Brak połączenia z serwerem podczas logowania 2. etapu (SMS): %s", e)
            raise CannotConnect(str(e)) from e
        except Exception as e:
            _LOGGER.error("Błąd podczas logowania 2. etapu (SMS): %s", e)
            raise AuthFailed(str(e)) from e

    async def _process_redirect(self, session, redirect_url):
        # Adres przekierowania zawiera jednorazowy kod OIDC, więc go nie logujemy
        _LOGGER.debug("Przetwarzanie przekierowania po zalogowaniu")
        code = None
        
        # Jeśli Keycloak wrzucił nas z powrotem na jakiś URL przed finalnym redirectem (co robi rzadko)
        while redirect_url and not redirect_url.startswith("mbok://"):
            from yarl import URL
            safe_url = URL(redirect_url, encoded=True)
            async with session.get(safe_url, allow_redirects=False) as res_mid:
                if res_mid.status in [301, 302, 303]:
                    redirect_url = res_mid.headers.get('Location')
                else:
                    break
                    
        if redirect_url and redirect_url.startswith("mbok://"):
            parsed = urllib.parse.urlparse(redirect_url)
            params = urllib.parse.parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            
        if not code:
            raise AuthFailed("Could not extract OIDC code from mobile redirect")

        # Krok 3: OIDC Token Exchange
        token_url = "https://oid-ws.orlen.pl/realms/oid/protocol/openid-connect/token"
        token_payload = {
            "grant_type": "authorization_code",
            "client_id": "pgnig-mobile",
            "code": code,
            "redirect_uri": "mbok://pgnigapp.pl/oid-login",
            "code_verifier": self.code_verifier
        }
        async with session.post(token_url, data=token_payload) as res_token:
            if res_token.status != 200:
                body = await res_token.text()
                _LOGGER.error("OIDC Token Error: %s", body)
                raise AuthFailed("OIDC token exchange failed")
            tokens = await res_token.json()
            id_token = tokens.get("id_token")
            access_token = tokens.get("access_token")
            refresh_token = tokens.get("refresh_token")

        if not id_token or not access_token:
            raise AuthFailed("No tokens returned from OIDC")

        # Krok 4: Wymiana na AutomaticToken w mBOK
        cb_url = f"https://mbok.myorlen.pl/auth/oid/after-login-callback?api-version=3.0&deviceId={self.device_id}"
        cb_headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        cb_payload = {
            "AccessToken": access_token,
            "IdToken": id_token,
            "DeviceId": self.device_id,
            "DeviceType": "Web"
        }
        
        async with session.post(cb_url, json=cb_payload, headers=cb_headers) as res_cb:
            if res_cb.status != 200:
                body = await res_cb.text()
                _LOGGER.error("after-login-callback Error: %s", body)
                raise AuthFailed("Failed to exchange access_token for AutomaticToken")

            data = await res_cb.json()
            # Nie logujemy treści odpowiedzi - zawiera tokeny sesji
            _LOGGER.debug("after-login-callback OK, otrzymane pola: %s", sorted(data.keys()))
            self.authtoken = data.get("Token")
            
            # W mobilnym flow authtoken to zazwyczaj ten stały AutomaticToken
            # Klucz to AutomaticLoginToken!
            automatic_token = data.get("AutomaticLoginToken") or refresh_token
            self.automatic_token = automatic_token

            return {
                "status": "success", 
                "authtoken": self.authtoken,
                "automatic_token": automatic_token
            }

    async def _request(self, endpoint):
        """Pomocnicza metoda do zapytań API z tokenem."""
        if not self.authtoken:
            if not await self.refresh_automatic_token():
                raise AuthFailed("Brak authtoken, wymagane ponowne zalogowanie")
            
        session = async_get_clientsession(self.hass)
        url = f"https://ebok.myorlen.pl{endpoint}"
        if "?" in url:
            url += "&api-version=3.0"
        else:
            url += "?api-version=3.0"
            
        headers = {
            "AuthToken": self.authtoken,
            "accept": "application/json",
            "User-Agent": self.user_agent
        }
        
        async with session.get(url, headers=headers) as res:
            if res.status == 401:
                _LOGGER.debug("API zwróciło 401. Próba odnowienia sesji przez AutomaticToken.")
                if await self.refresh_automatic_token():
                    headers["AuthToken"] = self.authtoken
                    async with session.get(url, headers=headers) as res_retry:
                        if res_retry.status == 401:
                            raise AuthFailed("Token wygasł lub jest nieważny")
                        elif res_retry.status != 200:
                            raise APIError(f"API Error {res_retry.status}")
                        return await res_retry.json()
                else:
                    raise AuthFailed("Token wygasł lub jest nieważny")
            elif res.status != 200:
                raise APIError(f"API Error {res.status}")
            return await res.json()

    async def get_agreements(self):
        """Pobiera listę umów."""
        return await self._request("/crm/get-agreements")
        
    async def get_invoices(self, load_after_30_days=False):
        """Pobiera listę faktur."""
        url = "/crm/get-invoices-v2?pageNumber=1&pageSize=50"
        if load_after_30_days:
            url += "&loadAfter30Days=true"
        return await self._request(url)

    async def get_readings(self, ppg_id):
        """Pobiera odczyty dla PPG."""
        return await self._request(f"/crm/get-all-ppg-readings-for-meter?idPpg={ppg_id}&pageNumber=1&pageSize=10")

    async def get_balance(self):
        """Pobiera informacje o saldzie."""
        return await self._request("/crm/get-balance")

    async def get_wear_chart(self, ppg_id):
        """Pobiera statystyki zużycia gazu dla danego licznika (PPG)."""
        return await self._request(f"/crm/get-monthly-wear-chart-data?ppgIds={ppg_id}&hasReachedEnd=false&pageNumber=1&pageSize=14&totalEntries=0")
