# Spaces: several departments in a single installation

This page tells you how one installation of the tool serves several departments, each in its own space. Section 1 is
for administrators, section 2 is for IT, and sections 3 to 5 are for development.


---

## 1. For administrators: what a space is

A single installation of the tool can serve several departments (Sustainability, Purchasing, HR, Quality…). Each department has its
**space**, and each space has **its own database**. The database of a space holds its frameworks, KPIs,
organisations, campaigns, values, evidence files, history, identity (name, colours, logo), Visualisation views, and
backups. **Nothing is mixed** between two spaces.

The table answers the usual questions about spaces:

| Question | Answer |
|---|---|
| Does a person need one account per space? | No. **Accounts are shared.** A person signs in only once, with the same email and the same password. Then they change space with the space button in the top bar. This button shows the name of the current space. |
| Does a person have the same role everywhere? | No. **The role is specific to each space.** For example, a person can be an administrator in "Sustainability" and a contributor in "Achats". |
| Who sees the space button? | Only the people who have access to **at least two** spaces. For the others, nothing changes. |
| What changes for the current installation? | **Nothing changes.** The current database becomes the "main space", at the same addresses. The only new item is the **Administration › Settings › Spaces** tab, which only *space managers* see. |
| Who are the space managers? | On the first startup of the new version, the active administrators of the main space become space managers. On a new installation, the first active administrator created in the main space becomes a space manager (a contributor, a reader or the administrator of another space never does). If the installation has no active space manager, the next active administrator of the main space becomes one, also when an account is given the administrator role. A manager appoints other managers in the **People and access** table of **Administration › Settings › Spaces**. IT can also do it (§ 2). |
| What can only a space manager do? | Manage the spaces, set the company sign-in, and change the settings that apply to the whole installation: the email server, the email alerts, the automatic updates and the external copy of the backups. These settings decide where the emails and the backups of all spaces go, so an administrator who is not a space manager, also in the main space, only sees them. This rule is the same on an installation with one space. |

### Create a space

Before you start, make sure that you are a space manager.

To create a space:

1. Go to **Administration › Settings › Spaces**.
2. Click **+ New space**. The **New space** page opens.
3. In **Name of the space**, enter a name (for example "Achats"). The **Address code** fills in by itself (for example
   `achats`). The space is then at the address `…/espace/achats/`. After creation, you can change the name, but not
   the code.
4. Keep **Reuse the identity (organisation name, colours, logo) of the current space** selected to keep the
   organisation name, the colours, and the logo. You can edit them later.
5. Click **Create the space**. The creation takes a few seconds. You are the administrator of the new space, and the
   **Setup** wizard opens at step 2.

The next steps of the wizard are **Your organisation** (identity of the organisation), **Languages**,
**Organisation**, **Frameworks**, **KPI sheet**, **Team**, and **First campaign**.

### Give access to a space

To give a person access to a space:

1. Open the space.
2. Go to **Administration › Accounts**.
3. Click **+ New account**. You can also click **+ Several accounts**, or use the **Team** step of the setup wizard.
4. Enter the **exact email** of the person, and then create the account.

The result depends on the person:

- If the person already has an account in another space, a message appears: “This person already has an account.
  They sign in to this space with their current password.” The tool gives no temporary password. The person keeps
  their own password.
- If the person has no account, the tool creates a new account, with the usual access message (temporary password).

### Manage people and access

The **People and access** table is below the list of spaces. It shows each person and their role in each space. In
this table, you can:

- Appoint a space manager (**Appoint**), or remove the right (**Remove**).
- Block the sign-in of a person in all spaces at once (**Block**). The tool keeps the accounts and the history of the
  person. To restore the sign-in, click **Allow**.

### Security between spaces

The tool protects each space from the others:

- The administrator of a space **cannot** change the email, name, or password of some people. These are the people
  who also work in a space where this administrator is not an administrator. This rule applies even if the account of
  the person is deactivated in that space, or if that space is archived. The account page of the person says so, and
  the **Reset the password** button does not appear.
- Only these people can make the change: the person themselves (**My account**), an administrator of all the spaces
  of the person, or a space manager.
- A signed-in person can open the address of a space that they have no access to. The page “You do not have access to
  the space “…”” then appears, with links to their spaces.
- You can **rename** and **archive** a space from the **Spaces** page. An archived space is hidden from everyone. The
  tool keeps its data, and you can reactivate it. **You cannot delete a space in the tool.**

### Try the two-space demo

To load the demo with two spaces, run `python3 manage.py load_demo --spaces`.

The main space is called "Sustainability" (the usual demo). The "Achats" (Purchasing) space (`/espace/achats/`) contains a small
fictitious dataset: France, Spain, and Italy, 9 purchasing KPIs, 2025 closed, and 2026 open. The password is
`demo-probant-2026`.

The table shows the role of each demo account in each space:

| Account | Sustainability | Achats |
|---|---|---|
| `admin` | administrator | administrator |
| `contributeur` | contributor | **validator** |
| `acheteur` | — | contributor |
| `lecteur` | reader | — (shows the "no access" page) |

---

## 2. For IT: where the data is

The table shows where the tool keeps the data of each space, with SQLite and with PostgreSQL:

| What | SQLite (default, `/data` in Docker) | PostgreSQL |
|---|---|---|
| Main space | `db.sqlite3`, `files/` (an older `media/` folder is renamed automatically) | `public` schema (unchanged) |
| Shared registry (accounts, list of spaces, access, sessions, email server set in the tool) | `shared.sqlite3` | `commun` schema of the same database |
| Each other space | `spaces-data/<code>/database.sqlite3` and `spaces-data/<code>/files/` | `espace_<code>` schema of the same database. Files in `spaces-data/<code>/files/` |
| Backups of the main space | `backups/*.zip` (unchanged) | Same |
| Backups of the other spaces | `backups/spaces/<code>/*.zip` | Same |
| Backups of the registry | `backups/shared/registry-*.zip` (one per day and before each update) | Same |

Points for IT:

- **For the external copy of the backups, copy the whole of `/data/backups`**, with its subfolders.
- For the layout of each folder (evidence files, logo, pending imports), see [File layout](file_layout.md).
- PostgreSQL: the tool creates the `commun` and `espace_<code>` schemas itself. The database account must have the
  **CREATE right on the database**. The database owner has this right. Check it at Clever Cloud. The tool needs no new
  database: everything stays in the database provided.
- Databases side by side with `SQLITE_FILE=vide.sqlite3`: the registry and the folders take the name of the file
  (`vide-shared.sqlite3`, `vide-spaces-data/`).
- Optional settings: `SPACES_DIR` (folder of the spaces) and `SPACES_CONN_MAX_AGE`. With PostgreSQL,
  `SPACES_CONN_MAX_AGE` is the lifetime of the connections of the additional spaces (60 s by default). Set it to 0 if
  the plan limits the number of connections.

> **Important:** Before you create many spaces, check the limit of simultaneous connections of the plan (Clever Cloud
> or another PostgreSQL plan). Each space opens its own connections. If the limit is low, set `SPACES_CONN_MAX_AGE=0`,
> or take the next plan up.

**How many PostgreSQL connections.** Each thread of the web server keeps its connections
(`CONN_MAX_AGE`, 60 s): one to the main space, one to the shared registry, and one to each additional space it has
served. They are bounded (the threads are a fixed pool), not leaked. With `S` additional spaces:

| Part | Connections at most | With the image defaults |
|---|---|---|
| Web server (gunicorn) | workers × threads × (2 + `S`) | 2 to 4 workers (one per processor) × 4 threads: 16 × (2 + `S`) at most |
| Background tasks (backups, reminders, data check, imports: 4 processes) | 4 × (2 + `S`) | 8, plus 4 per additional space |

PostgreSQL allows 100 connections by default, 3 of them kept for its administrator. With the defaults on a server with
4 processors or more, 20 × (2 + `S`) stays below this limit up to 2 additional spaces (80); with 3 or more additional
spaces it can be exceeded ("too many clients already", errors 500). Measured with gunicorn started as in the image
(4 workers × 4 threads, one space, 6 rounds of 40 requests at the same time): 32 connections, stable, no error. From 3
additional spaces, or if the plan allows fewer connections: set `SPACES_CONN_MAX_AGE=0` (the connections of the
additional spaces are then closed at the end of each request: at most workers × threads × 3 for the web server, 48
with the defaults), lower `GUNICORN_THREADS` or `GUNICORN_WORKERS`, or take a bigger plan. The development server (`runserver`) starts one thread per request and does
not close these connections: never use it in production or for a load test.

### Update from a version without spaces

You do nothing more than usual: run `./update.sh`, or redeploy at Clever Cloud. The update then does this:

- At startup, `startup` backs up each database that has pending migrations, and migrates **all databases**. Then it
  creates the shared registry from the accounts of the main space (same IDs, same passwords).
- The current sessions are carried over: nobody is signed out.
- The main database receives only one small table (`espaces_marqueespace`, one row).
- **You can go back to the previous version.** The previous version ignores `shared.sqlite3`. The main database keeps
  all the accounts and their passwords up to date.

### Commands

The table shows the commands for spaces and what they do:

| Command | Effect |
|---|---|
| `python3 manage.py migrate` | Migrates all databases (main, registry, each active space), then brings the registry back in line |
| `SPACE=achats python3 manage.py <command>` | Runs any command in the `achats` space (backup, restore, import_kpi, recalculate, shell…). Without `SPACE`, the command runs in the main space |
| `python3 manage.py spaces` | Lists the spaces (address, state, number of accounts) |
| `python3 manage.py spaces --reconcile` | Brings the account registry and the spaces back in line (the tool also does it after every migrate and every restore) |
| `python3 manage.py spaces --manager <email>` | Gives the right to create and manage spaces (`--remove-manager` removes it) |
| `python3 manage.py spaces --archive <code>` / `--reactivate <code>` | Hides a space, or shows it again |
| `SPACE=achats python3 manage.py restore <archive>` | Restores a backup **of this space** |
| `python3 manage.py restore --shared <archive>` | Restores the shared registry (accounts, spaces, email server set in the tool) from `backups/shared` |

> **Warning:** **Never** run `migrate --database espace_x` by hand outside the command of the tool. The command of the
> tool always activates the correct space, and the data migrations write to the database of the activated space.

The schedulers (`backup --schedule`, `send_reminders --schedule`, `check_data --schedule`) go through all active
spaces. Each space uses its own settings: **Administration › Settings › Hosting** and the **Reminders** page **of that
space**. The schedulers take a new space into account on the next round. `send_reminders --auto` (cron outside Docker)
handles all spaces, or a single space with `SPACE=`.

### Back up and restore a space

Each archive contains only the database and the files **of its space**, never the account registry. It also contains
the code of the space and the identifier of the installation.

- The tool **refuses** an archive from another space or from another installation. IT can force it on the command line
  with `--other-space`, for example to clone a space. A space manager can restore an archive from another installation
  in the tool, into the current space: see
  [Restore a backup from another installation](installation.md#restore-a-backup-from-another-installation).
- You can restore an archive from before spaces only into the main space.
- After a restore, the tool brings the registry back in line. Everyone keeps their current password. A person added
  to the space after the date of the archive loses access to that space, but keeps their account.
- A restore of a space signs out the person who starts it (as before). That person must sign in again.

### Monitor the spaces

`/sante/` checks the registry, the database of each active space, and the files folder of each space.

At startup, the tool checks the database of each space. If the database is unreachable, or is not the database of
that space (different marker, or no marker), the tool marks the space **unavailable** (503 page). The other spaces are
not blocked, and the startup log gives the cause. The tool checks the marker before any migration: it writes nothing
to a database that is not the database of its space.

---

## 3. How it is built (for further development)

This section describes the code of spaces:

- The `espaces/` application contains these modules:
  - `contexte.py`: current space, leak guard, `ESP.atomic()`, `ESP.connexion()`, folders
  - `routeur.py`: registry in `commun`, the rest in the database of the current space
  - `intergiciels.py`: `/espace/<code>/` prefix, "no access" page
  - `session.py`: tool keys specific to each space
  - `stockage.py`: files per space
  - `comptes.py`: unique ID, linking by email, propagation, rule against privilege escalation, bootstrapping,
    reconciliation
  - `creation.py`
  - `management/commands/migrate.py`: all databases
- Guard: during a request or a command of a space, any SQL query to the database of another space raises
  `FuiteEspace`. In the code of the tool, use:
  - `with ESP.atomic():`, never `transaction.atomic()` without a database
  - `ESP.connexion()`, never `django.db.connection`
  - `ESP.dossier_medias()` / `ESP.dossier_sauvegardes()`

  The test `espaces/test_statique.py` checks this.
- Tests: `espaces.essais.EspacesTestCase` provides a second "essai" space. `test_balayage` opens every page in both
  spaces for the five roles.
- Interface texts: `libelles/espaces.<language>.json`, one file for each language of the interface.

## 4. Limits

These items are not in the tool yet:

1. "My spaces" block in **My account**. The space button in the top bar already lists the spaces.
2. Details of the registry and of the other spaces in the **Hosting** page. The administrator of a space already sees
   its backups there, and `/sante/` already checks all databases.
3. Colours of Excel files without global variables. Two simultaneous exports in two spaces could swap their colours.
   This is cosmetic.
4. Language saved in the account (`Utilisateur.langue`, language of emails), copied into all copies of the account.
   Today, the language chosen in the top bar applies to all spaces during the session. The language of the account
   remains specific to each space. The change needs a column in the shared registry, and so a migration.

## 5. Known security points

The tests of isolation cover every page, every address with an object ID, exports, evidence files, reminders,
backups, commands and roles, on SQLite and on PostgreSQL. These known points do not block the use of spaces:

- All spaces are at the same web address. An XSS-type flaw in one space would act in the others, for a person who has
  access to them. No such flaw is known. Stay vigilant: always escape texts.
- Information messages ("Saved…") follow the person from one space to another. They never go to another person.
- If IT replaces the database of a space by hand while the tool runs, the tool detects it only at the next startup
  (marker). Never replace the file or the schema of a space by hand: use the restore.
- A space manager can take control of any account. Only appoint trusted people.
- Only a space manager can change the email server or the external copy. The external copy receives the archives of
  all spaces and of the shared registry, which contain the password hashes.
- When an administrator of a space creates an account, they learn if the email already has an account in the
  installation (and the name of the person).
- PostgreSQL: the shared registry opens its own connections (about twice as many as before). Check the connection
  limit of the plan (small Clever Cloud plan). `SPACES_CONN_MAX_AGE=0` reduces the connections of the other spaces.
