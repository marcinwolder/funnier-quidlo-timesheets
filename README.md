# Quidlo Timesheets – Time Tracker

Osobiste narzędzie CLI/TUI do importowania wpisów czasu pracy z kalendarza (plik `.ics` lub zdalny link) i wysyłania ich na [timesheets.quidlo.com](https://timesheets.quidlo.com/tracker).

## Wymagania

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- Przeglądarka Chromium dla Playwright

## Instalacja

```bash
cd src
uv sync
uv run playwright install chromium
```

## Uruchomienie

```bash
cd src
uv run cli
```

Przy pierwszym uruchomieniu i próbie wysyłki otworzy się okno przeglądarki – trzeba zalogować się ręcznie do Quidlo. Sesja jest zapamiętywana w profilu przeglądarki (`src/.playwright-profile`), więc kolejne uruchomienia nie wymagają ponownego logowania.

## Funkcje

- **Zakładka Manual** – ręczne dodawanie wpisu (data, czas trwania, opis, projekt, tagi), edycja i usuwanie wpisów z listy.
- **Zakładka From .ics** – import wpisów z pliku `.ics` (z podpowiadaniem nazw plików z katalogu `calendars/`) z opcjonalnym filtrem zakresu dat.
- **Zakładka Remote calendar** – zapisywanie nazwanych subskrypcji kalendarza (nazwa + URL), wczytywanie ich ponownie oraz import wpisów bezpośrednio ze zdalnego adresu, z tym samym filtrem dat.
- **Lista wpisów roboczych (staging)** – podgląd wszystkich dodanych/zaimportowanych wpisów z sumą czasu, przed wysyłką.
- **Wysyłka wsadowa** – jednym przyciskiem/skrótem wysyła wszystkie wpisy z listy do Quidlo przez Playwright; w razie błędu zatrzymuje się na pierwszym nieudanym wpisie.

### Skróty klawiszowe w TUI

| Skrót      | Akcja                        |
|------------|-------------------------------|
| `Ctrl+A`   | Dodaj wpis z formularza       |
| `Ctrl+S`   | Wyślij wszystkie wpisy        |
| `Delete`   | Usuń zaznaczony wpis          |
| `Escape`   | Wyczyść formularz             |
| `Q`        | Wyjście                       |

## Gdzie umieszczać pliki kalendarza

Pliki `.ics` wrzucaj do katalogu `calendars/` w głównym folderze repozytorium. Będą wtedy podpowiadane w polu „ICS file” w zakładce **From .ics**. Katalog ma wpis `.gitignore` na `*.ics`, więc kalendarze nie trafiają do repozytorium.

## Wymagany format wydarzeń w kalendarzu

- **Tytuł** wydarzenia musi mieć format `[Projekt] Opis`, np. `[Internal Tooling] Implement import flow`.
- **Opis/treść** wydarzenia może zawierać tagi jako hashtagi, np. `#billable #client-a`.
- Data i czas trwania są wyliczane z godziny startu/końca wydarzenia.
- Wydarzenia całodniowe (bez godziny) są pomijane.

Przykład:

- Tytuł: `[Internal Tooling] Implement import flow`
- Opis: `#billable #automation`
- Czas: `09:00–17:00`

→ da wpis: projekt `Internal Tooling`, opis `Implement import flow`, tagi `billable, automation`, czas trwania `8h`.

## Zdalne kalendarze

W zakładce **Remote calendar** można zapisać subskrypcję pod nazwą i adresem URL – zapisywane są lokalnie w `src/.remote_calendars.json` (poza repozytorium). Obsługiwane adresy:

- `http://` / `https://` – link do pliku `.ics`
- `webcal://` / `webcals://` – automatycznie zamieniane na `https://`
- link z ustawień kalendarza Google zawierający `cid=...` – automatycznie zamieniany na publiczny link `.ics`

## Znane ograniczenia

- Selektory na stronie Quidlo nie są w pełni zweryfikowane – w razie zmian na stronie automatyzacja może przestać działać.
- Wysyłka wsadowa zatrzymuje się na pierwszym błędzie i nie wznawia się automatycznie.
