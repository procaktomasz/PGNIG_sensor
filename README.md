# PGNiG eBOK Sensor

Integracja Home Assistant do pobierania informacji o saldzie, fakturach, odczytach licznika i zużyciu gazu z serwisu PGNiG / ORLEN mBOK (myorlen.pl).

## Funkcje

- **Integracja Home Assistant** - automatyczne tworzenie sensorów dla salda, faktur, kwot do zapłaty, odczytów licznika, zużycia i ceny gazu.
- **Logowanie jak aplikacja mobilna** - kod SMS jest wymagany tylko przy pierwszej konfiguracji. Później sesja odnawia się automatycznie, bez kolejnych SMS-ów.
- **Wiele punktów poboru** - obsługa wielu punktów poboru gazu (PPG) na jednym koncie; sensory licznika, zużycia i ceny tworzone są osobno dla każdego punktu.
- **Tylko faktury za gaz** - korekty, noty odsetkowe i produkty dodatkowe (np. ubezpieczenia) są pomijane w sensorach faktur.
- **Przycisk odświeżania** - ręczne wymuszenie pobrania danych.

## Wymagania

- Aktywne konto w serwisie https://ebok.myorlen.pl (dawniej eBOK PGNiG) z numerem telefonu do kodów SMS.
- Instancja Home Assistant.

## Sensory

Integracja tworzy jedno urządzenie **PGNiG eBOK** dla konta, z następującymi encjami:

| Sensor | Opis | Wartość |
|--------|------|---------|
| `sensor.pgnig_ebok_saldo` | **Saldo** - bieżące saldo konta. | PLN |
| `sensor.pgnig_ebok_do_zaplaty` | **Do zapłaty** - suma wszystkich nieopłaconych faktur za gaz. W atrybutach liczba nieopłaconych faktur, najbliższy termin i kwota płatności, liczba faktur po terminie. | PLN |
| `sensor.pgnig_ebok_aktualna_faktura` | **Aktualna faktura** - kwota najnowszej faktury za gaz. W atrybutach numer, daty wystawienia i płatności, status, rodzaj. | PLN |
| `sensor.pgnig_ebok_najblizsza_prognozowana_faktura` | **Najbliższa Prognozowana Faktura** - kwota pozostała do zapłaty dla najbliższej nieopłaconej faktury (prognozy). W atrybutach numer i termin płatności. | PLN |
| `sensor.pgnig_ebok_aktywne_umowy` | **Aktywne Umowy** - liczba umów. W atrybutach lista punktów poboru gazu i umowy bez e-faktury. | liczba |

Dodatkowo dla każdego punktu poboru gazu (`<ppg>` - numer PPG):

| Sensor | Opis | Wartość |
|--------|------|---------|
| `sensor.pgnig_ebok_odczyt_licznika_<ppg>` | **Odczyt Licznika** - najnowszy odczyt licznika gazu. W atrybutach data i status odczytu, zużycie od poprzedniego odczytu. | m³ |
| `sensor.pgnig_ebok_zuzycie_za_okres_<ppg>` | **Zużycie za okres** - zużycie gazu za ostatni okres rozliczeniowy (z faktury). W atrybutach okres, numer faktury, zużycie w m³. | kWh |
| `sensor.pgnig_ebok_cena_gazu_<ppg>` | **Cena gazu** - średni koszt brutto 1 m³ gazu z ostatniej faktury (paliwo + dystrybucja + opłaty stałe). W atrybutach cena za kWh, kwota brutto, zużycie. Może służyć jako cena gazu w panelu **Energia**. | PLN/m³ |

Oraz przycisk:

| Encja | Opis |
|-------|------|
| `button.pgnig_ebok_odswiez_dane` | **Odśwież dane** - natychmiastowe pobranie aktualnych danych. |

> Identyfikatory encji mogą się nieznacznie różnić w zależności od wersji Home Assistant. Faktyczne nazwy znajdziesz w: **Ustawienia** > **Urządzenia i usługi** > **PGNiG eBOK Sensor**.

Koordynator aktualizuje dane co godzinę. W przypadku błędu (np. przerwy technicznej serwisu) próba zostanie ponowiona przy kolejnej aktualizacji.

## Instalacja

### Opcja 1: HACS (Zalecana)

Kliknij poniższy przycisk, aby automatycznie dodać repozytorium do HACS:

[![Otwórz w HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=procaktomasz&repository=PGNIG_sensor&category=integration)

Lub ręcznie:

1. Otwórz HACS w Home Assistant.
2. Kliknij trzy kropki w prawym górnym rogu.
3. Wybierz **Custom repositories**.
4. W polu URL wpisz: `https://github.com/procaktomasz/PGNIG_sensor`
5. W polu Category wybierz: **Integration**.
6. Kliknij Add, a następnie wyszukaj "PGNiG eBOK Sensor" i zainstaluj komponent.
7. Zrestartuj Home Assistant.

### Opcja 2: Instalacja manualna

1. Skopiuj folder `custom_components/pgnig_sensor` do folderu `config/custom_components/` w konfiguracji HA.
2. Zrestartuj Home Assistant.

## Konfiguracja

1. Przejdź do: **Ustawienia** > **Urządzenia i usługi** > **Dodaj integrację**.
2. Wyszukaj **PGNiG eBOK Sensor**.
3. Podaj e-mail i hasło do serwisu myORLEN (eBOK).
4. Na telefon powiązany z kontem zostanie wysłany kod SMS - wpisz go w kolejnym kroku.

Po pierwszym logowaniu integracja odnawia sesję samodzielnie. Jeśli sesja wygaśnie całkowicie, Home Assistant wyświetli powiadomienie o konieczności ponownego uwierzytelnienia - wystarczy podać hasło i nowy kod SMS. Dane logowania można też zmienić w dowolnym momencie opcją **Skonfiguruj ponownie**.

## Rozwiązywanie problemów

- **Nieprawidłowy e-mail lub hasło** - sprawdź, czy możesz zalogować się ręcznie na https://ebok.myorlen.pl.
- **Nie można połączyć się z serwerem** - serwis może mieć przerwę techniczną; spróbuj ponownie później.
- **Nie przychodzi kod SMS** - sprawdź numer telefonu przypisany do konta w serwisie myORLEN.
- Zmiany po stronie serwisu PGNiG / ORLEN mogą powodować tymczasowy brak danych w sensorach.
- Aby włączyć szczegółowe logowanie dla integracji, dodaj w `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.pgnig_sensor: debug
```

Logi nie zawierają haseł ani tokenów sesji, ale przed udostępnieniem ich w zgłoszeniu sprawdź, czy nie ma w nich danych osobowych (np. numerów PPG).

## Nota prawna

Projekt licencjonowany na zasadach MIT. Jest to projekt prywatny, niepowiązany, niesponsorowany ani niewspierany przez ORLEN S.A. ani PGNiG Obrót Detaliczny Sp. z o.o. Nazwy i znaki towarowe należą do ich właścicieli i służą wyłącznie do celów identyfikacyjnych.
Źródłem danych dla integracji są serwisy https://ebok.myorlen.pl/ oraz https://mbok.myorlen.pl/.
