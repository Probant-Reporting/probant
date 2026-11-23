# Measurement at large volume

Two tools to know how the pages behave on a large installation, before its users find out. They work on
**fictitious data only**.

| Tool | Question it answers |
|---|---|
| `make_big_data.py` | Builds the big database of a fictitious group, from an empty database: about 680 organisations on 4 levels, 200 accounts, an annual framework of about 320 KPIs with formulas over 4 years, a monthly framework, alerts, evidence records, a history of 1.2 million lines. It depends on no client. |
| `measure_pages.py` | For each main page and each role: how many SQL queries, how much server CPU time, how big is the page? |
| `concurrent_users.py` | What happens when 50 people work **at the same moment** on the big database: times per page, errors, lost or doubled saves, totals after a full recalculation, processor, memory and database connections of the server. |
| `../load_test.py` (not in this folder) | The same question on the small demo (needs the `requests` package); the figures are in `docs/installation.md`, "Capacity". |

The first two answer "is one page too heavy for this much data"; `concurrent_users.py` and `load_test.py` answer "do
many users at once lose or break something". Use both before a release that touches queries, lists, saving or exports.

## Build the big database

```bash
DATA_DIR=/tmp/big/data python3 qa/load/make_big_data.py                      # full size: about 20 minutes, 0.9 GB
DATA_DIR=/tmp/small/data python3 qa/load/make_big_data.py --sites 60 --months 3 --journal-rows 20000   # 1 minute
DATA_DIR=/tmp/big/data python3 qa/load/make_big_data.py --only journal       # restart one step after a failure
DATABASE_URL=postgres://user:password@127.0.0.1:5432/big python3 qa/load/make_big_data.py   # same under PostgreSQL
```

It refuses a database that is not empty, and it refuses to run without `DATA_DIR`, `DATABASE_URL` or `SQLITE_FILE`.
Fictitious data only: the group "Grandgroupe" (12 countries, about 66 subsidiaries, 600 sites, some closed), accounts
`@exemple.test`, values drawn at random from `--seed` (same seed, same data).

| What | Full size (default options) |
|---|---|
| Organisations | 1 group, 12 countries, about 66 subsidiaries, `--sites` sites (600); 6 sites closed in 2024, 6 closed during 2026 |
| Accounts | the 5 demo accounts (`admin`, `validateur`, `contributeur`, `lecteur`, `auditeur`, password `demo-probant-2026`) and `contrib000`-`149`, `valid000`-`029`, `lect000`-`009` (one in three limited to one country), `audit000`-`004`, `adm000`-`004`; all written in the registry of the spaces, so they can sign in |
| Assignments | one contributor for 4 sites, one per subsidiary, one validator per country (`valid000`-`011`), the others on one subsidiary each; a few cells without a contributor |
| Annual framework `GROUPE` | about 320 KPIs: inputs at site and subsidiary level (numbers, yes / no, lists, some optional), emission factors at group level, about 80 calculated KPIs (a headcount cited by 30 ratios, factors cited by 20 emissions, changes on N-1); 10 KPIs outside any framework, 5 inactive. Campaigns 2023, 2024, 2025 closed (all validated), 2026 open (about 45 % validated, 15 % draft) |
| Monthly framework `MENSUEL` | 40 site KPIs, `--months` months from January 2025 (22), the last month open |
| Alerts | consistency check of 2025 (accepted) and of the open campaigns (30 % justified); 2 rules between KPIs |
| Evidence | one validated site answer in 25 has an evidence record (no file on the disk: pages only list them) |
| History | `--journal-rows` lines (1,200,000), dated from 2023 to 2026, 95 % on answers |
| In all (seed 1) | 679 organisations, 205 accounts, 366 KPIs, 1,273,762 answers (about 410,000 entered in the years, 511,000 in the months, the rest calculated totals), 17,933 alerts, 15,242 evidence records, 1,200,000 history lines. Counted again with the current code: an earlier count of 2,587,458 answers came from a calculation in which a month also calculated the KPIs of the annual framework ("incomplete" rows); now a period calculates only the KPIs of its campaigns |

Steps, all by default: `setup` (settings, tree, accounts, KPIs, frameworks, assignments, campaigns), `answers`
(answers, calculations, alerts, evidence), `journal`. `--only` runs one step, to restart after a failure. The
calculations dominate the time. Then measure the pages from any branch with the same `DATA_DIR`.

## Measure the pages

```bash
DATA_DIR=/tmp/big/data python3 qa/load/measure_pages.py --out /tmp/big/measure.json
DATA_DIR=/tmp/big/data python3 qa/load/measure_pages.py --filter "Data entry" --reps 5
DATA_DIR=/tmp/big/data python3 qa/load/measure_pages.py --skip-exports --max-cpu-ms 1500 --max-queries 150
```

It also runs on the plain demo (`load_demo`) to get the reference figures: compare the same line on the two databases.
The accounts `contrib001` and `valid000` of the big database are used when they exist, the demo accounts otherwise
(`make_big_data.py` also creates the demo accounts, so every line runs on the big database).

Read the table (one line per page and role):

| Column | Meaning |
|---|---|
| status | 200 is a page; 302 or 404 is shown as it is (for instance a personal view of another account): look before trusting the line |
| queries | SQL queries of one call. A number that grows with the data is an N+1: compare the demo and the big database |
| sql ms | time of the database for these queries |
| cpu ms | median CPU time of the whole call, SQL included, without network and browser |
| wall ms | median elapsed time of the call: under PostgreSQL, the time of the database server is in it and not in "cpu ms" |
| kB, gz kB | size of the page, and compressed (what travels) |

What to look for: a page whose queries or CPU time grow between the demo and the big database (the list is not
paginated or not indexed), a page above one second of CPU, an export above a few seconds. With `--max-cpu-ms` or
`--max-queries`, the exit code is 1 when a line goes beyond (or fails), so the measurement can be given a budget.

The measurement runs in the process of Django through the test client, so it does not include the network, gunicorn or
the browser. The pages only read. Two exceptions: an export above the threshold of Settings › Hosting is prepared in the
background (the line shows 302, and the file is written in My exports of the measured database, as for a person); the
MCP lines (`tools/list`, `get_value`), measured last, create a token and log each call, inside a transaction rolled back
at the end. The account `audit000` of the big database (an auditor limited to one country) gives the lines "restricted
auditor".

## Fifty people at the same moment

```bash
# 1. the plan: accounts and cells of the big database (adds a few assignments so that 4 people write in one site)
DATABASE_URL=postgres://user:password@127.0.0.1:5432/big python3 qa/load/concurrent_users.py prepare --plan /tmp/plan.json
# 2. the server as in production (docker/entrypoint.sh): gunicorn, 1 worker per processor (2 to 4) x 4 threads,
#    DJANGO_DEBUG=0, collectstatic done, and "python3 manage.py run_imports --schedule" for the background exports
# 3. the scenario, then the check (same environment as step 1)
python3 qa/load/concurrent_users.py run --plan /tmp/plan.json --url http://127.0.0.1:8000 --log /tmp/run.jsonl \
    --duration 300 --server-pid <gunicorn master> --watch-pid <run_imports>
python3 qa/load/concurrent_users.py check --plan /tmp/plan.json --log /tmp/run.jsonl --server-log gunicorn.log \
    --postgres-log /var/log/postgresql/postgresql-16-main.log --json /tmp/result.json
```

Standard library only (`run` talks HTTP with `urllib`). Default mix: 38 contributors (sites side by side in the tree,
so several write in the same subsidiary, plus 4 in one site), 4 or 5 validators, 3 administrators, 5 readers. Think
time `--think 4` (0.5 to 1.5 times): about ten times faster than a real person, so 50 simulated people are a campaign
of several hundred real ones. A second run on the same database takes `--run 2` (the values written change).

`check` exits with 1 on a 5xx, a lost or doubled save, a final value that is not one of the last acknowledged saves, a
save accepted on a version not seen, a duplicate answer, a total different from a full recalculation, "database is
locked" or a PostgreSQL deadlock. "Refused" saves are not errors: the automatic draft is refused on a validated value
(the person uses "Save the change"), a version conflict is the expected answer when two people change the same cell.

Measured (big database of seed 1: 679 organisations, 1.27 million answers, 1.2 million history lines;
4 processors **shared with other heavy jobs**, load average 6 to 18: the times are pessimistic, compare the runs
between them rather than with a quiet server):

| | PostgreSQL 16, 50 people | SQLite, 50 people | SQLite, 20 people | SQLite, 10 people |
|---|---|---|---|---|
| Lost, doubled or wrong saves; totals different from a full recalculation; deadlocks | none | none | none | none |
| Errors | 1 (the backup, see below) | 25 errors 500 ("database is locked", 48 in the log) | 3 errors 500 ("database is locked") | none |
| Save (draft, validate), median / 95th percentile | 17 to 33 s / 90 s | 28 to 42 s / 170 s | 10 s / 50 s | 1 to 2 s / 12 s |
| Open a cell, open the grid, median | 6 s, 12 s | 6 s, 3.5 s | 0.2 s, 1.2 s | 0.1 s, 0.5 s |

Why saves wait: every save recalculates the totals it touches while it holds the lock of all the periods
(`calcul._recalculer`: one recalculation at a time, so that two saves never write the same total). On the big database
this recalculation takes about 1.5 s for a cell of the year and 4 to 5 s for a cell of a month (cumul of the months
into the year), so the saves form a queue: up to 15 sessions waiting for this lock under PostgreSQL. Under SQLite the
same queue waits for the write lock, and after 60 s the save fails with "database is locked". The validation, the
return to draft and the evidence upload no longer recalculate (the status does not change any total): 1.6 s and 4.6 s
less per validation.

Other findings: a backup started from Settings › Hosting under PostgreSQL takes 5 minutes during the load (JSON of all
the tables in the request): the archive is made, but the page does not answer within 3 minutes (the error above).
Large exports go to the background (one at a time per space, the others wait); the "review report" of the year
(about 9.5 million cells) took 5 to 6 minutes and up to 3.8 GB of memory in the scheduler process.

## Not kept

The first measurement also timed actions (saving an entry, validating, importing, backing up) with a second script. It
is not kept here: `qa/load_test.py` already runs these actions and gives response times per page, and the actions are
covered at the size of the demo by the test suite.
