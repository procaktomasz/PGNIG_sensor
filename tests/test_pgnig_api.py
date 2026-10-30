"""Testy klienta API (logowanie)."""
import logging
from unittest.mock import MagicMock, patch

import aiohttp
import pytest

from custom_components.pgnig_sensor.api import AuthFailed, CannotConnect, PGNiGApi


class FakeResponse:
    def __init__(self, status=200, json_data=None, text="", headers=None):
        self.status = status
        self._json = json_data
        self._text = text
        self.headers = headers or {}

    async def json(self):
        return self._json

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeSession:
    """Sesja zwracająca kolejno przygotowane odpowiedzi (lub rzucająca wyjątek)."""

    def __init__(self, responses=None, error=None):
        self._responses = list(responses or [])
        self._error = error
        self.closed = False

    def _next(self, *args, **kwargs):
        if self._error:
            raise self._error
        return self._responses.pop(0)

    get = _next
    post = _next

    async def close(self):
        self.closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
        return False


@pytest.fixture
async def api():
    # aiohttp.CookieJar wymaga działającej pętli zdarzeń
    return PGNiGApi(MagicMock(), "user@example.com", "pw", device_id="dev1")


async def test_login_step1_network_error_is_cannot_connect(api):
    session = FakeSession(error=aiohttp.ClientConnectionError("down"))
    with patch.object(api, "_new_session", return_value=session):
        with pytest.raises(CannotConnect):
            await api.login_step1()
    assert session.closed


async def test_login_step1_bad_credentials_is_auth_failed(api):
    session = FakeSession(responses=[
        FakeResponse(text='<form action="https://oid.example/login?a=1&amp;b=2">'),
        FakeResponse(status=200, text='<p class="instruction">Błędne dane</p>'),
    ])
    with patch.object(api, "_new_session", return_value=session):
        with pytest.raises(AuthFailed, match="Błędne dane"):
            await api.login_step1()
    assert session.closed


async def test_login_step1_sms_required(api):
    session = FakeSession(responses=[
        FakeResponse(text='<form action="https://oid.example/login">'),
        FakeResponse(status=200, text='<form id="kc-sms-code-login-form" action="https://oid.example/sms">'),
    ])
    with patch.object(api, "_new_session", return_value=session):
        assert await api.login_step1() == {"status": "sms_required"}
    assert api.sms_action_url == "https://oid.example/sms"


async def test_login_step2_network_error_is_cannot_connect(api):
    api.sms_action_url = "https://oid.example/sms"
    session = FakeSession(error=aiohttp.ClientConnectionError("down"))
    with patch.object(api, "_new_session", return_value=session):
        with pytest.raises(CannotConnect):
            await api.login_step2("123456")


async def test_process_redirect_does_not_log_tokens(api, caplog):
    api.code_verifier = "verifier"
    session = FakeSession(responses=[
        FakeResponse(json_data={"id_token": "SECRET_ID", "access_token": "SECRET_ACCESS", "refresh_token": "SECRET_REFRESH"}),
        FakeResponse(json_data={"Token": "SECRET_TOKEN", "AutomaticLoginToken": "SECRET_AUTO"}),
    ])
    with caplog.at_level(logging.DEBUG):
        result = await api._process_redirect(session, "mbok://pgnigapp.pl/oid-login?code=SECRET_CODE&state=s")

    assert result == {"status": "success", "authtoken": "SECRET_TOKEN", "automatic_token": "SECRET_AUTO"}
    assert "SECRET" not in caplog.text
