# TODO-Triage: API-Subtree (9 Treffer)

**Quelle:** `/tmp/agentflow-todos-api.txt` — erzeugt mit `grep -rn 'TODO|FIXME' app --include=*.py`, Teilmenge `app/api/`.

**Zentrales Ergebnis:** Alle 9 Treffer sind **Fehltreffer**. Das grep-Muster `TODO` matcht die
Teilzeichenkette `TODO` in **`VTODO`** — dem iCalendar-Task-Komponentennamen aus RFC 5545 — bzw.
den literalen Suchstring `TODO` in einem Regex-Muster. Kein einziger Treffer ist ein echter
TODO/FIXME-Arbeitsmarker. Jede Zeile wurde im umgebenden Code nachgelesen: Es handelt sich um
korrekte Docstrings, lauffähige Marshmallow-/CalDAV-Definitionen oder funktionale Regex-Daten.

**Statistik:** 9 × `kommentar` · 0 × `kleinfix` · 0 × `feature`

**Nacharbeit für künftige Scans (Vorschlag an Orchestrator, außerhalb dieses Tasks):** Das
Scan-Muster auf Wortgrenzen umstellen, z.B. `grep -rnE '\b(TODO|FIXME)\b' app --include=*.py`,
damit `VTODO`-Referenzen nicht mehr als Marker gemeldet werden. Bis dahin gilt für alle Zeilen
unten: keine Aktion, kein app/-Code ändern.

| referenz | code-kontext | todo | klasse | aktion |
| --- | --- | --- | --- | --- |
| app/api/v1/calendar/ApiCalendar.py:282 | Klassen-Docstring von `ApiCalendarTaskList` (Route `/calendars/<key>/tasks`); GET listet Tasks mit Date-Range-/Search-Args, POST legt neue Tasks über `interface.create_task` an. | `"""API to list and create tasks (VTODO) in a calendar."""` | kommentar | Fehltreffer: Docstring benennt die iCalendar-Task-Komponente (RFC 5545 VTODO) korrekt — keine Aktion. |
| app/api/v1/calendar/schemas/task.py:25 | Klassen-Docstring von `CalendarTaskSchema`; die Feldliste darunter (date_due, percent_complete, completed_at, …) bildet genau eine Task-Antwort ab. | `"""Representation of a single VTODO in API responses."""` | kommentar | Fehltreffer: präziser Schema-Docstring — keine Aktion. |
| app/api/v1/calendar/schemas/task.py:32 | Ausführbare Marshmallow-Felddefinition in `CalendarTaskSchema`; die Metadata-Description erklärt, dass DTSTART für Tasks optional ist — passend zum `allow_none=True`. | `date_start = fields.String(allow_none=True, metadata={"description": "ISO 8601 UTC start (optional for VTODOs)."})` | kommentar | Fehltreffer: lauffähiger Code, kein Marker — keine Aktion. |
| app/api/v1/calendar/schemas/task.py:54 | Klassen-Docstring von `CalendarTaskCreateSchema`; der Körper definiert die Create-Felder (title required, date_due, percent_complete 0–100, …). | `"""Request body for creating a new VTODO."""` | kommentar | Fehltreffer: Docstring beschreibt das Schema korrekt — keine Aktion. |
| app/api/v1/calendar/schemas/task.py:87 | Klassen-Docstring von `CalendarTaskPatchSchema`; alle Felder sind optional (kein `required=True`), wie beschrieben. | `"""Request body for partially updating a VTODO. All fields optional."""` | kommentar | Fehltreffer: Docstring deckt sich mit der Implementierung — keine Aktion. |
| app/api/v1/calendar/schemas/task.py:110 | Klassen-Docstring von `CalendarTaskResponseSchema` (erbt `ApiBaseResponse`); `data` nestet ein einzelnes `CalendarTaskSchema`. | `"""Response schema for a single VTODO."""` | kommentar | Fehltreffer: Docstring passt zum Code — keine Aktion. |
| app/api/v1/calendar/schemas/task.py:123 | Klassen-Docstring von `CalendarTaskListResponseSchema`; `data` nestet `CalendarTaskListDataSchema` (tasks-Liste + total_count). | `"""Response schema for a list of VTODOs."""` | kommentar | Fehltreffer: Docstring beschreibt die Listen-Antwort korrekt — keine Aktion. |
| app/api/v1/user/ApiTranscripts.py:73 | Regex-Muster in der `action_triggers`-Liste von `_extract_action_items()`; erkennt wörtliche „TODO:"-Marker in Benutzer-Transkripten, um daraus Action-Items zu extrahieren. | `r"TODO\s*:?\s*"` | kommentar | Fehltreffer: `TODO` ist hier Daten (Suchmuster über Fremdtext), kein Arbeitsmarker — keine Aktion. |
| app/api/v1/caldav/ApiCalDAV.py:351 | Ausführbarer Code in `_build_calendar_props()`; baut die CalDAV-Eigenschaft `supported-calendar-component-set` mit den comp-Kindern VEVENT und VTODO. | `children=[_prop("comp", ns=CALDAV_NS, attrib={"name": c}) for c in ("VEVENT", "VTODO")],` | kommentar | Fehltreffer: lauffähige CalDAV-PROPFIND-Antwort, kein Marker — keine Aktion. |
