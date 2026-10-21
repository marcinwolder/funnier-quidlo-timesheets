---
name: sync-timesheets
description: Synchronizuje Google Kalendarz („Projects”) z Quidlo Timesheets przez MCP – dodaje, edytuje i usuwa wpisy tak, by dzień w Timesheets odpowiadał kalendarzowi. Użyj, gdy użytkownik prosi o zsynchronizowanie / uzupełnienie / wyklikanie timesheetów z kalendarza.
argument-hint: "[zakres dat] [+odrabianie | +<nazwa kalendarza>]"
---

# Sync kalendarz → Timesheets

Kalendarz jest źródłem prawdy. Po synchronizacji każdy dzień z zakresu ma w Timesheets dokładnie te wpisy, które wynikają z kalendarza – z wyjątkiem projektu „Miquido - Absence” (zarządza nim zewnętrzny bot) i wpisów zatwierdzonych (tylko do odczytu).

Oczekiwane godziny per dzień są w arkuszu „Arkusz godzin Miquido” (`spreadsheetId` `1BbUMBnxit3N-w8cgG1O5uAyrvwqJf_qQ-QS8QPZUXMA`): jedna zakładka na miesiąc, np. „Październik 2026”, kolumny „Quildo” (godziny dnia) i „Suma częściowa godzin Quildo” (suma od 1. dnia miesiąca do danego dnia włącznie). Ostrzeżenie o sumie pojawia się tylko, gdy stan po synchronizacji różni się od którejś z tych kolumn.

Gdy kalendarz zgadza się z arkuszem, przebieg jest automatyczny – bez pytań (`auto_approve` w kroku 5).

Całą logikę mapowania, diffu i porównania z arkuszem liczy `scripts/sync_plan.py` (obok tego pliku, sam stdlib, Python 3.11+). Ty robisz I/O przez MCP i rozmowę z użytkownikiem; plan bierzesz wyłącznie z wyjścia skryptu, bez własnych poprawek.

## Reguły kalendarza (dla kontekstu – egzekwuje je skrypt)

- Tytuł `[Projekt] Opis` → projekt i tytuł wpisu; inne tytuły są pomijane z ostrzeżeniem.
- Hashtagi w opisie wydarzenia (`#backend`) → tagi.
- Czas trwania = koniec − start; wydarzenia całodniowe i odwołane są pomijane.
- Wydarzenia jednego dnia z tym samym projektem, tytułem i tagami sumują się w jeden wpis.

## Kroki

1. **Argumenty.**
   - Zakres: domyślnie od poniedziałku bieżącego tygodnia do dziś. Akceptuj „ten/poprzedni tydzień”, „wrzesień”, pojedynczą datę lub `RRRR-MM-DD..RRRR-MM-DD`. Zbuduj listę **wszystkich** dni zakresu (także weekendów) – dzień z zakresu bez wydarzeń zostanie wyczyszczony, więc zakres pokazujesz użytkownikowi w podglądzie.
   - Kalendarze: zawsze `Projects`. Dodatkowe tylko na wyraźną prośbę w argumencie: `+odrabianie` = `Projects - Odrabianie (+)`, `+<nazwa>` = kalendarz o tej nazwie. Kalendarze „Odrabianie”/„Do odrobienia” bez takiej prośby zostają poza synchronizacją.
   Gotowe, gdy masz listę dat ISO i listę nazw kalendarzy.

2. **Kalendarze.** `Google_Calendar__list_calendars` → dopasuj każdą nazwę do `summary` (dokładnie). Brak dopasowania → zatrzymaj się i zapytaj użytkownika (AskUserQuestion z listą kalendarzy).

3. **Odczyt.** Równolegle:
   - dla każdego kalendarza `Google_Calendar__list_events` z `calendarId`, `startTime=<pierwszy dzień>T00:00:00`, `endTime=<dzień po ostatnim>T00:00:00`, `pageSize=250`; dociągaj kolejne strony po `nextPageToken`, aż go zabraknie;
   - `timesheets__get_time_entries` z `date=<1. dzień miesiąca pierwszego dnia zakresu>`, `date_to=<ostatni dzień>` – wcześniejsze dni miesiąca są potrzebne do sumy częściowej (skrypt ich nie zmienia);
   - `timesheets__list_projects`;
   - `Google_Sheets__get_spreadsheet` arkusza godzin z `fields=["sheets.properties.title"]`.
   Potem `timesheets__list_tags` dla każdego projektu z `[...]` w tytułach wydarzeń, który istnieje na liście projektów, oraz `Google_Sheets__get_values` z `range='<Miesiąc> <RRRR>'!A1:AB40` dla każdego miesiąca zakresu, którego zakładka istnieje (nazwa miesiąca w mianowniku, wielką literą). Brak zakładki nie zatrzymuje synchronizacji – skrypt zgłosi, że miesiąc nie był porównany.

4. **Plan.** Zapisz w katalogu scratchpad (albo tymczasowym) plik `input.json`:
   ```json
   {
     "dates": ["2026-10-13", "..."],
     "events": [{"summary": "...", "description": "...", "status": "...", "start": {...}, "end": {...}, "recurrence": [...]}],
     "timesheet": <odpowiedź get_time_entries bez zmian>,
     "catalog": {"<nazwa projektu>": ["<nazwa tagu>", "..."]},
     "sheets": [<odpowiedź get_values bez zmian>, "..."]
   }
   ```
   `events` to wydarzenia ze wszystkich wybranych kalendarzy razem, przycięte do tych pól. Uruchom `python3 <katalog tego skilla>/scripts/sync_plan.py <ścieżka>/input.json`. Wyjście: `operations` (kolejność wykonania, gotowe argumenty narzędzi), `blocked`, `warnings`, `days`, `auto_approve`, `preview`.

5. **Podgląd i zgoda.** Pokaż `preview` w całości, a pod nim liczbę operacji wg typu. Gdy `operations` jest puste, zakończ na tym.
   - `auto_approve: true` (sumy dni i sumy częściowe zgodne z arkuszem, każde wydarzenie ma `[Projekt]` i tag znane w Timesheets, nic zablokowanego, brak ostrzeżeń) → nie pytaj, napisz jednym zdaniem, że kalendarz zgadza się z arkuszem, i przejdź od razu do kroku 6.
   - W przeciwnym razie zablokowane pozycje i ostrzeżenia omów krótko (np. zatwierdzony dzień różni się od kalendarza → poprawka tylko ręcznie w Quidlo; niezgodna suma częściowa → podaj od którego dnia i o ile) i zapytaj AskUserQuestion: „Wykonać N operacji?” → `Wykonaj` / `Anuluj`. Okno pytania zasłania wcześniejszy tekst odpowiedzi, więc podgląd wstaw też w pole `preview` opcji `Wykonaj`: dzień po dniu, wpisy z czasem i tagami, suma dnia, znacznik ⚠ tylko przy dniach, które `preview` oznacza „⚠ …” (suma dnia lub suma od 1. dnia ≠ arkusz), na końcu liczba operacji wg typu. Ta jedna zgoda obejmuje wszystkie usunięcia z planu.

6. **Wykonanie.** Wywołuj operacje po kolei, dokładnie w kolejności z `operations`: `tool` → `mcp__claude_ai_timesheets__<tool>`, argumenty = `args` 1:1. Pozycji z `blocked` nie wykonujesz. Przy pierwszym błędzie zatrzymaj się. Gotowe, gdy każda operacja ma wynik albo przebieg zatrzymał błąd.

7. **Raport.** Krótko: ile dodano / zmieniono / usunięto per dzień, co się nie udało (komunikat serwera), co zostało niewykonane. Dodaj, że cały przebieg cofa `timesheets__rollback_changes` z `count` = liczba udanych operacji.

## Testy skryptu

`python3 -m unittest discover -s <katalog tego skilla>/scripts` – uruchom po każdej zmianie `sync_plan.py`.
