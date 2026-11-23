# Life of a group (acceptance scenario)

A fictitious group lives three reporting years in the tool. The scenario finds the faults that show only in the second
or third year: a site that closed, an entity that moved, a formula that changed, a KPI made inactive, a year reopened
after all that.

Everything goes through the pages of the tool: one Django test client per account, signed in, posts the same forms as
a person (entry panel, campaign panel, organisation form, KPI sheet, import, export, reminders, Hosting). Only the
starting state is written directly in the database (`world.py`). The values come from a fixed seed: two runs with the
same seed play the same life. Fictitious data only (invented names, e-mails `@exemple.test`).

## Run

```bash
# outside the test suite: a new, empty data folder each time
export DATA_DIR=/tmp/group-life/data && rm -rf "$DATA_DIR" && mkdir -p "$DATA_DIR"
python3 qa/group_life/run.py --size small --seed 1 --out /tmp/group-life/report.json
```

| Option | Meaning |
|---|---|
| `--size micro` | 2 countries, 2 entities, 4 sites (the version of the test suite) |
| `--size tiny` | 2 countries, 4 entities, 8 sites (about 2 minutes) |
| `--size small` | 3 countries, 9 entities, about 35 sites (default) |
| `--size large` | 8 countries, 48 entities, about 480 sites (about an hour) |
| `--years 1..3` | number of reporting years to play |
| `--no-spaces` | play only the main space |
| `--export-threshold CELLS` | exports above this many cells are made in the background (Settings › Hosting, 100,000 by default). The actor follows the task (state, download from My exports) and checks that the file is the same as the immediate download. Lower it (for example `500`) to play the large exports on a small group |

Exit code 1 if an anomaly is found. The report (`--out`) lists each anomaly with its code, the step where it happened
and the detail. Anomalies marked `"rule": true` are behaviours to confirm (a product decision), not certain faults.

After a run, the data folder stays: `DATA_DIR=… python3 manage.py runserver 8205 --noreload`, then sign in as
`gl-admin` (or `gl-con-1-1`, `gl-val-1`, `gl-reader`, `gl-auditor`), password `Group-life-2026`. The browser journeys
(`browser.js`) run on this server.

A short version runs in the test suite: `collecte/test_vie_du_groupe.py` (micro size). The minimal tests of the
anomalies found are in `collecte/test_vie_du_groupe_anomalies.py`, marked as expected failures until they are fixed.

## The group

| Level | Micro | Tiny | Small | Large |
|---|---|---|---|---|
| Group | 1 | 1 | 1 | 1 |
| Countries | 2 | 2 | 3 | 8 |
| Entities | 2 | 4 | 9 | 48 |
| Sites | 4 | 8 | about 35 | about 480 |

Accounts: one administrator, one contributor per entity (its sites and its own KPIs), one validator per country, one
contributor for the group KPIs, one reader, one auditor.

Two frameworks: "Group annual report" (annual: energy, water, waste, accidents, certification (yes / no), waste by type
(table answer), emission factor, emissions (calculated), change on N-1 (calculated with `[ELEC@N-1]`), headcount, women,
share of women (ratio), training hours, revenue, carbon intensity) and "Monthly energy" (electricity and gas each
month, switched on in year 2: from then on the annual values are the sum of the months).

## Timeline

| Year | Events |
|---|---|
| 2023 | campaign created and opened from the campaign panel; blocking consistency rule created; entries with mistakes and corrections (decimal comma, text in a number), N/A without then with a comment, validation refused without evidence, evidence added, table answer with an unknown list value refused; import with rejected lines (unknown KPI, unknown organisation, text, cell of someone else) and a calculated KPI ignored; validators validate; the administrator clears a value and puts one back to draft; review, closure |
| 2024 | monthly framework switched on; annual campaign and 12 monthly campaigns; new KPI from the KPI sheet, formula changed; a site closes on 30/06, a site opens, an entity moves to another country, assignments; monthly values imported month by month; variance above the threshold justified; forced value asked by the contributor and accepted by the validator; reminders sent; closure of the 13 campaigns; correction imported in the closed year (refused for a value entered in the tool), then reopening, correction, closure |
| 2025 | KPI made inactive; annual and monthly campaigns; library template installed, then installed again as a new version; reminders; the administrator allows assistants, creates a token and uses the MCP server (`get_value`, `save_value`): same log lines, same cell and same totals as the same entry in the panel; closure; then 2023 and 2024 reopened and closed again (history probes) |
| second space | its own group, a VS template, a campaign, entries, the official workbook export; nothing of one space is visible in the other |
| end | backup from the Hosting page, a change, restore from the Hosting page: everything as it was |

## Fourth year (2026) and events between the years

`year4.py` plays what the first three years do not, each event through the same doors as a person (pages, imports, IT
commands) and followed by its checks (data check, totals equal to the sum of the detail, nothing changed in a closed
year, and the full checks of `checks.py` at the end). An event that crashes is reported as `event_crashed:<name>`; the
next events still play. The run prints, for each event, whether it was played and what came out.

```bash
export DATA_DIR=/tmp/group-life-4/data && rm -rf "$DATA_DIR" && mkdir -p "$DATA_DIR"
python3 qa/group_life/run4.py --size tiny --years 1 --out /tmp/group-life-4/report.json   # about 1 minute
python3 qa/group_life/run4.py --size small --years 3                                     # the whole life first
```

| Area | Events |
|---|---|
| People | a contributor becomes a reader before being replaced; a contributor leaves (drafts, validated values, evidence, assistant token, saved export, personal view) and is replaced with « Replace a person… »; a validator becomes a reader, then a validator again and gets validator assignments back from the Assignments page (choice « Validators »); the last administrator cannot be demoted or switched off; temporary password; e-mail changed; one person with accounts in two spaces |
| Organisations | site renamed and recoded (a file with the former code); level « Region » inserted between Country and Entity, an entity moved under it while the campaign is open; two sites merged (one closed on 30/06 with its values); an entity sold with its sites (closed on 31/03); a closed site reopened (its entity sold: attached elsewhere) |
| Framework | unit of a KPI changed between two years; answer format changed (refused); KPI removed from the framework and put back; KPI made optional; formula changed while the campaign is open; sensitive KPI past its retention period (evidence deleted); list value used in a table removed (refused); table column changed (refused); new library version over a local change (needs `--years 3`) |
| Campaigns | fiscal year April to March next to the calendar year; quarters, months and year on the same KPI (needs `--years 2` or more); two years open at the same time (file with and without a period); end date moved to the past; closing with drafts left. A campaign cannot be deleted in the tool: not playable |
| Installation | « startup » in the middle of a campaign (outside the test suite); default language changed, export read again; second space archived then reactivated |
| Languages | the same campaign entered in French, English, German and Portuguese (« 1 234,5 », « 1,234.5 », « 1.234,5 »), the file to fill downloaded and filled in each language, reminders in the language of each person, an export of a German speaker read again by an English speaker |

A short version runs in the test suite: `collecte/test_vie_du_groupe_quatrieme.py` (micro size, first year only, about
25 s). Not played: backup and restore in the middle of a campaign (followed by the work on restore,
`parametres/sauvegardes.py`), the move from SQLite to PostgreSQL (documented in `docs/installation.md`, section 8: play
it by hand with `backup --json` and `restore`).

## Checks after each year

`checks.py`:

* `check_data` without error (it also compares every calculated cell with a recalculation in memory);
* the "Recalculate" button of each open campaign changes no value;
* each total of a "Sum" KPI equals the sum of its detail (children open during the period, independent calculation);
* the consistency alerts planted on purpose are there;
* what is left to do is the same on the Dashboard and on the Reminders page, for each contributor;
* rights by role: the administration pages are refused to the other roles; the reader, the auditor, a contributor out
  of scope and a validator of another country cannot write a cell; the main pages never answer 500;
* the "Database" export of the year, imported again as it is, changes nothing and rejects nothing;
* after a closure: nobody writes in the closed campaign;
* during the whole run: no answer 500, no error line in the log.

## What it does not cover

The scenario does not check the content of the screens (labels, layout, accessibility: see `qa/browser_check.py`),
JavaScript (see `browser.js` and `qa/journeys.js`), PostgreSQL (run it with `DATABASE_URL`), concurrency, the
translations, the Visualisation views, the configuration files, the migration wizard and SMTP for real (e-mails stay in
memory).
