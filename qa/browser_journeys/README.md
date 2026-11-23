# Browser journeys

Scripts that drive a real browser (Node.js, Playwright, Chromium) through the tool, role by role, and report what is
wrong. They find the faults that unit tests do not: a page that fails for one role, a write accepted for a read-only
role, a filter bar that does not close, a page that scrolls sideways on a phone.

Run them against a **throwaway demo**, never against an installation with real data: some scripts click and post.

## What each tool covers

| Tool | What it checks |
|---|---|
| `routes.py` | Not a test: lists every route of the tool with a real address, and the access of the reader and of the auditor (read from `collecte/lecture_seule.py`). The input of `crawl.js` and `readonly_writes.js`. |
| `crawl.js` | Opens **every route with every role** (and as a visitor). Anomaly: 5xx, JavaScript error, static file not served, visitor not sent to the sign-in page, reader or auditor with a different access from `lecture_seule.py`, administrator refused, another role that opens what the administrator cannot. Writes `access_matrix.tsv` (the matrix of accesses). With `--baseline` / `--write-baseline`: pins the matrix of the validator and of the contributor. |
| `readonly_writes.js` | **Writes refused to the read-only roles.** A POST with a valid CSRF token to every route as reader and auditor: 403 everywhere except the routes allowed by `ECRITURES_PERMISES` (own preferences, downloads); a real entry and a real validation on a cell: 403. A POST without CSRF token: 403. |
| `filters.js` | The filter bar (`.barre-filtres`, `DESIGN.md` "Filters"): search, check-list panels (open, Escape, click outside), "Display" menu, "Clear filters". |
| `mobile.js` | Phone, 390 px, touch: the page must not scroll sideways, on every route, for each role. |
| `keyboard.js` | Entry panel and dialogs with the keyboard only: focus trap, Escape, return of the focus, visible focus mark on Data entry. |
| `languages.js` | **Every complete language of the interface** (read from `libelles/`), for the five roles (the reader and the auditor start from the page they land on). Per page: `<html lang>` follows the switch; no raw translation key or template leftover; no interface text left in another language (a visible text that is, word for word, the French or English value of a label key whose value in the current language differs; the catalogue of units and themes and the demo contents are left out); no sideways scroll at 1 440 and 390 px. Hard-coded text that looks French and is in no label file is a warning (mostly demo contents, which are in French). The names of levels and types stored in the database of the demo are listed in `languages_demo_data.txt` (`--data FILE`): the installation translates them, not the label files. Options: `--langs`, `--roles`, `--pages`, `--labels`, `--no-narrow`, `--keep-languages`. The languages of the run that are off in Settings > Languages are turned on first (a language that is off shows the default language for the demo contents) and turned off again at the end, even after an error; `--keep-languages` leaves the settings alone. The language of the account is put back as found. |
| `click_all.js` | Clicks every harmless control of some pages: JavaScript errors, console errors, 5xx. A control that cannot be clicked is skipped (`--click-timeout`, 1 s), each page has a time budget (`--page-budget`, 90 s), and a summary closes the run. |

Not duplicated here:

* `qa/browser_check.py` is the acceptance test by role (31 pages and 5 panels, axe-core WCAG 2.1 AA, 768 and 390 px,
  response times, named checks of the critique, entry journey, proof that nothing was written). `mobile.js` goes wider
  (every route, every role) but without axe-core and without response times; `keyboard.js` adds the focus trap, the
  return of the focus and the dialog to what `browser_check.py` does with the keyboard.
* `qa/journeys.js` is the complete journeys that write (admin prepares a campaign, creates an account, contributor
  enters and validates, validator accepts or refuses a forced value, reminders), in three languages, on a computer and on
  a phone. The scripts here read much more and write almost nothing.

## Requirements

* Node.js with the `playwright` package and Chromium (`npm install playwright`, `npx playwright install chromium`); if
  Playwright is installed in another folder, give it to Node with `NODE_PATH=/path/to/node_modules`.
* Python with the project requirements (only for `routes.py`).
* A demo database: `python3 manage.py load_demo` in a folder of your choice. The demo accounts are `admin`,
  `validateur`, `contributeur`, `lecteur`, `auditeur`, password `demo-probant-2026`.

## Run

```bash
# 1. a throwaway demo (a new folder; the same variable DATA_DIR for every command)
export DATA_DIR=/tmp/journeys-demo/data && mkdir -p "$DATA_DIR"
python3 manage.py migrate && python3 manage.py load_demo
python3 manage.py runserver 8091 --noreload &        # or: qa/disposable_demo.sh --client exemplia --port 8013

# 2. the list of routes (same DATA_DIR: the example identifiers come from this demo)
python3 qa/browser_journeys/routes.py > /tmp/journeys-demo/routes.json

# 3. the scripts
OUT=/tmp/journeys-demo/out
node qa/browser_journeys/crawl.js          --routes /tmp/journeys-demo/routes.json --base http://127.0.0.1:8091 --out $OUT
node qa/browser_journeys/readonly_writes.js --routes /tmp/journeys-demo/routes.json --base http://127.0.0.1:8091 --out $OUT
node qa/browser_journeys/filters.js        --base http://127.0.0.1:8091 --out $OUT
node qa/browser_journeys/mobile.js         --routes /tmp/journeys-demo/routes.json --base http://127.0.0.1:8091 --out $OUT
node qa/browser_journeys/keyboard.js       --base http://127.0.0.1:8091 --out $OUT
node qa/browser_journeys/languages.js      --base http://127.0.0.1:8091 --out $OUT        # all languages, five roles; --langs de,it --roles admin to narrow
node qa/browser_journeys/click_all.js      --roles contributeur --pages /pour-moi/,/saisie/ --base http://127.0.0.1:8091 --out $OUT
```

Options common to all the scripts (command line first, then the environment variable, then the default):

| Option | Variable | Default | Meaning |
|---|---|---|---|
| `--base` | `BASE_URL` | `http://127.0.0.1:8000` | address of the tool (a space: `http://host/espace/achats`) |
| `--password` | `PASSWORD` | `demo-probant-2026` | password of the demo accounts |
| `--out` | `OUT_DIR` | `./journeys-output` | folder of the reports (screenshots of the faults included); never commit it |
| `--roles` | `ROLES` | depends on the script | roles to run, comma separated (the account name is the role name) |
| `--routes` | `ROUTES` | none | `routes.json` written by `routes.py` |

Other options are at the top of each script. Durations on a laptop, demo of 680 organisations: `readonly_writes.js` and
`keyboard.js` under a minute, `filters.js` a few minutes, `languages.js` about 30 minutes (7 languages, 5 roles, two widths), `crawl.js` and `mobile.js` 5 to 10 minutes,
`click_all.js` several minutes per page.

## Read the result

* The **exit code** is 0 when nothing is wrong, **1 when there is at least one anomaly**, 2 when the script itself could
  not run (sign-in refused, server not reachable). Use it in a script or a check.
* Each script prints one line per anomaly (`ANOMALY  role page : what`) and per warning (`warning ...`), and writes
  `<script>.json` in `--out` (`anomalies`, `warnings`, `notes`).
* An **anomaly** is a fault to fix or to explain: 5xx, JavaScript error, a write accepted for a read-only role, a page
  that scrolls sideways, a panel that does not close, a raw translation key. A **warning** is a hint to look at by hand
  (a French text in the English interface can be the name of a demo KPI).
* `crawl.js` also writes `access_matrix.tsv`: one line per route, one column per role (status, `>` then the address
  when the page redirects). Read the validator and contributor columns, which no file declares. When they are right,
  save them with `--write-baseline matrix.json`; the next runs with `--baseline matrix.json` report every cell that
  changed.

## Routes and expected accesses are not written by hand

`routes.py` reads the URL configuration (`config/urls.py`, `collecte/urls.py`, `parametres/urls.py`, `espaces/urls.py`),
takes an example identifier for each parameter from the demo database, and reads the pages of the reader and of the
auditor in `collecte/lecture_seule.py`. Run it again after any change of routes or of demo. A route without example
(a backup file name, a library model code, an empty table) is listed under `skipped`. Nothing else to maintain, except
`IGNORED` and `PUBLIC` at the top of `routes.py` (routes that end the session or need a file name; pages open to
visitors).

## Add a script

Put it here, take `lib.js` (options, sign-in, report, exit code), write messages and comments in English, give anomalies
as `rep.anomaly(where, what)`, and finish with `return rep.finish(cfg)`. Reports and screenshots go to `--out`, never
to the repository.
