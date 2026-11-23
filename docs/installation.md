# Install Probant

This guide tells you how to install, set up, back up, update, and monitor Probant with Docker. It is for the
IT team. You do not need to know Django or Python.

The tool runs in **a single Docker container**. All its data is in **a single volume**, `/data`: database, evidence
files, logo, backups, and secret key.

This table shows the main operations:

| Operation | Command | Duration |
|---|---|---|
| Install | `./install.sh` | 3 to 5 minutes |
| Update | `./update.sh` | 1 to 3 minutes |
| Back up | Automatic every night, or `docker compose exec web python manage.py backup` | A few seconds |
| Restore | `docker compose exec web python manage.py restore <archive>` | A few seconds |

If you do not want to manage a server, see [Managed hosting (Clever Cloud)](managed_hosting.md).

## 1. Prerequisites

This table shows what you need before you install the tool:

| Need | Recommended minimum |
|---|---|
| Server | 64-bit Linux (Debian 12, Ubuntu 22.04 or later), 1 CPU, 1 GB of memory, 5 GB of disk |
| Software | Docker Engine 24 or later with the Compose plugin v2.24 or later (`docker compose version`), Git |
| Network, internal access | 1 port open to the server (8000 by default) |
| Network, HTTPS access | A domain name that points to the server (for example, `reporting.example.com`), and ports 80 and 443 open from the Internet (automatic Let's Encrypt certificate) |
| Emails (optional) | An SMTP account (server, port, username, password, sender address) |
| AI assistant (optional) | Outgoing HTTPS (TCP 443) from the server to `api.anthropic.com`, only if the client turns the assistant on. See “AI assistant” in section 4 |

The server does not need Python, a web server, or a database. Everything is in the image.

### Install Docker on Debian or Ubuntu

The official procedure is at https://docs.docker.com/engine/install/. In short, run these commands:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER     # then sign out and sign in again
docker compose version            # must show v2.24 or later
```

## 2. Install the tool

To install the tool:

1. Get the code and go to its folder:

   ```bash
   git clone https://github.com/Probant-Reporting/probant.git probant
   cd probant
   ```

2. Run the installer:

   ```bash
   ./install.sh                      # or: ./install.sh --domain reporting.example.com
   ```

   The script shows the address to open.

The script does these steps, in this order:

1. It checks that Docker responds.
2. It creates the `.env` settings file from `.env.example`. It does not replace an existing `.env` file.
3. It builds the image and starts the tool.
4. It waits for the tool to respond.
5. It shows the address to open.

This table shows the options of `./install.sh`:

| Option | Effect |
|---|---|
| No option | The tool opens over HTTP at `http://SERVER-ADDRESS:8000`. Use it for an internal network or a trial. |
| `--domain reporting.example.com` | The tool opens over HTTPS. The script adds Caddy in front of the tool, and Caddy gets the certificate automatically. Port 8000 is then open only to the server itself. |
| `--port 8080` | The tool uses another HTTP port. |

### Install without the script

To do the same installation by hand:

1. Create the settings file: `cp .env.example .env`.
2. Open the file (`nano .env`) and set at least `DOMAIN`.
3. Build and start the tool: `docker compose up -d --build`.

## 3. Set up the tool on first launch

When you first open the tool, it has no account yet. The **Setup** wizard opens in place of the sign-in page. It has
8 steps.

> **Important: create the administrator account right away.** Until step 1 is done, the first person who opens the
> address of the tool creates the administrator account. After step 1, the wizard opens only for that account.

### Start empty, or with the demo

A new installation is empty: you set up your own structure with the wizard. This is the way to start for real.

To look at the tool first, you can load the demo instead: Exemplia, a fictitious company, with its organisations,
its KPIs and three reporting years. Do it before step 1 of the wizard, on the empty database:

```bash
docker compose exec web python manage.py load_demo
```

The command shows the demo accounts and their password.

> **Important:** the password of the demo accounts is public. Load the demo only on an installation that you use for
> an evaluation, and do not leave it open to the internet. The command refuses a database that already holds your
> data. To start for real afterwards, delete the evaluation and its data (`docker compose down -v`), then install
> again: the tool starts empty.

The tool asks for no installation code. As long as nothing is created, the tool holds no sensitive data. What
protects it is the order of the steps: you create the administrator account right after the installation, and
before you share the address.

To set up the tool:

1. Right after the installation (or deployment), open the address of the tool. The **Setup** wizard opens.
2. Complete step 1, **Administrator account**, before you share the address.
3. Complete the other steps, or give the address to the person who does the setup.

If step 1 has to wait, keep the tool unreachable from the Internet until then. For example, do not set the domain
name yet.

This table shows the 8 steps of the wizard:

| Step | Name | What you set |
|---|---|---|
| 1 | **Administrator account** | The account of the administrator |
| 2 | **Your organisation** | The name, logo, and colours of the tool |
| 3 | **Languages** | The default language and the content languages |
| 4 | **Organisation** | The levels of the tree and the organisations |
| 5 | **Frameworks** | The KPI frameworks: the KPIs to collect |
| 6 | **KPI sheet** | Description categories, units, types, and fields |
| 7 | **Team** | The accounts of contributors and validators |
| 8 | **First campaign** | The period, the dates, and the opening of data entry |

You can stop and continue later. The person who does the setup does not need the IT team, except for emails
(section 7).

![First launch: the wizard opens on the administrator account](screenshots/en/setup-admin-account.png)

![Step 5: choose a framework from the library, compose it or import your own](screenshots/en/setup-frameworks.png)

![Step 8: the first campaign, current period suggested](screenshots/en/setup-campaign.png)

After the setup, each person signs in with their email address. The **Dashboard** shows the progress of the
collection:

![Sign-in page](screenshots/en/login.png)

![Dashboard](screenshots/en/dashboard.png)

Data entry also works on a phone:

![Data entry on a phone](screenshots/en/entry-phone.png)

### Have the translated texts proofread

The interface exists in French, English, Spanish, German, Italian, Dutch, and Portuguese. An AI translated the texts
that are not in French or English. Before you open a language to users, ask a person who speaks it in the company to
proofread its texts. The texts are in the files `libelles/*.<code>.json` (for example `libelles/*.es.json`). The person needs no technical skills: they only read the texts.

## 4. Change the settings (`.env` file)

The settings are in the `.env` file. The `.env.example` file explains each line. To apply a change, run
`docker compose up -d`. A setting with no value keeps its default value.

The tool still accepts the former French names of the settings (`DOMAINE`, `PORT_HTTP`, `SMTP_HOTE`…). They can be in
older `.env` files. Use the names in the table that follows.

This table shows each setting, its default value, and what it does:

| Setting | Default | Purpose |
|---|---|---|
| `DOMAIN` | IP address of the server (set by the installer) | The domain name or address that people use to open the tool. Separate several values with commas. The tool refuses any other address (error 400). |
| `DJANGO_HTTPS` | `0` | Set to `1` behind Caddy or another HTTPS proxy. This turns on secure cookies, redirection to HTTPS, and HSTS. |
| `HTTP_PORT` | `8000` | The port of the tool. To expose it only to the proxy, write `127.0.0.1:8000`. |
| `COMPOSE_PROFILES` | Empty | `https` adds Caddy. `postgres` adds PostgreSQL. For both, write `https,postgres`. |
| `DATABASE_URL` | Empty (SQLite) | The address of the PostgreSQL database. See section 8. |
| `DJANGO_SECRET_KEY` | Generated | The key that encrypts the sessions and signs the backups. If it is empty, the tool creates it on first startup in `/data/.secret_key`. If you change it, the tool no longer accepts the backups made before in **Administration › Settings › Hosting**: restore them from the command line with `--unsigned`. |
| `DJANGO_HSTS_SECONDS`, `DJANGO_HSTS_SUBDOMAINS`, `DJANGO_HSTS_PRELOAD` | 1 year, `1`, `0` | The HSTS settings. They apply when `DJANGO_HTTPS=1`. |
| `CONTENT_SECURITY_POLICY_MODE` | `enforce` | The content security policy of the pages. `enforce` blocks what the policy does not allow. `report-only` blocks nothing: the browser only reports, in its console, what it would block. See “Security, already active” below. |
| `SMTP_…` | Empty | Emails. See section 7. |
| `AI_SOCKET` | `on` | `off` turns off the optional AI assistant for the whole installation: no AI button anywhere and nothing sent, whatever the administrators set. See “AI assistant” below. |
| `DEFAULT_LANGUAGE` | `en` | The language of a new installation (interface and contents): one of the seven languages of the interface (`en`, `fr`, `es`, `de`, `it`, `nl`, `pt`). The tool reads it only when it creates the database. Afterwards, change it in **Administration › Settings › Languages**. For a French installation, set `fr` before the first start. |
| `GUIDED_TOUR` | `on` | `off` removes the short guided tour that people see at their first sign-in. The tour only changes the display. |
| `TIME_ZONE` | `Europe/Brussels` | The time zone of the installation, as a name from the IANA list, for example `Europe/Paris` or `America/New_York`. The times of the automatic reminders, of the automatic backup and of the nightly data check, "today", and the dates in the exports and in the log use this time zone. **Administration › Settings › Hosting** shows it next to the server time. If the name is unknown, the tool does not start and the log shows the error. |
| `MAX_EVIDENCE_SIZE_MB`, `MAX_IMPORT_SIZE_MB` | `5`, `10` | The maximum size, in MB, of an evidence file and of an import file. |
| `MAX_BACKUP_UPLOAD_MB` | `2048` | The maximum size, in MB, of a backup that an administrator uploads in the tool (**Hosting** › **Restore**). The tool refuses every other request larger than the larger of `MAX_EVIDENCE_SIZE_MB` and `MAX_IMPORT_SIZE_MB` (plus 1 MB) before it receives it. With the HTTPS proxy, `CADDY_MAX_SIZE` (50 MB by default) also applies: increase it to upload a larger backup. |
| `MAX_XLSX_UNCOMPRESSED_MB` | 20 × `MAX_IMPORT_SIZE_MB` | The maximum size, in MB, of an Excel file once uncompressed. The tool refuses a larger file before it opens it. A cell text longer than 32,767 characters (the limit of Excel) is also refused. The same limits apply to the import commands that you run on the server (`import_kpi`, `import_organisations`, `import_valeurs`): to import a larger file with a command, increase `MAX_XLSX_UNCOMPRESSED_MB` for that run. |
| `BACKGROUND_IMPORT_ROWS` | `5000` | A value import (**Import / Export › Import values**) with more rows than this number runs in the background. The person sees a progress bar, and can leave the page and come back. The `run_imports --schedule` process runs these imports. The image starts it automatically, so you install nothing. `0` means never: every import runs within the page, which can last 120 s at most. |
| `DISK_ALERT_MB` | `100` | When the free space on the data disk is below this value, in MB, `/sante/` answers `503` (“disk almost full”). |
| `BACKUP_AUTO`, `BACKUP_TIME`, `BACKUPS_KEEP` | `1`, `02:30`, `14` | Starting values only. After that, you set these values in the tool, in **Administration › Settings › Hosting**: automatic backup on or off, frequency (6 h, 12 h, day, week), time, and number of backups kept. |
| `DATA_CHECK_TIME` | `03:30` | The time of the nightly data check and clean-up. The check reads the database and changes nothing. The clean-up erases the expired sessions and the deleted items older than the trash delay. See section 9. |
| `GUNICORN_WORKERS`, `GUNICORN_THREADS` | 1 worker per processor (2 to 4), `4` | Server capacity. A worker uses 1 processor at a time and about 170 MB of memory. The default suits a server with 2 to 4 processors. See “Capacity” in section 8. |
| `GUNICORN_TIMEOUT`, `GUNICORN_KEEPALIVE` | `120`, `75` | The longest time for a request, in seconds, and the time that an idle connection stays open. Keep `GUNICORN_KEEPALIVE` above the idle timeout of the proxy in front of the tool. The Caddy provided closes idle connections after 60 s. If the value is lower, a save can sometimes fail with error 502. |
| `DJANGO_LOG_LEVEL` | `INFO` | The level of detail of the log (`INFO`, `WARNING`, `ERROR`). |
| `IMAGE` | Empty (image built on the server) | The published image to use, for example `ghcr.io/probant-reporting/probant:latest`. |

### Security, already active

With no particular setting, the tool applies these protections:

- Debug mode is turned off.
- The server is gunicorn. It runs without root rights (user 1000).
- The code of the tool in the image (`/app`) belongs to root: the tool can read it but cannot change it. The tool
  writes only in the data folder (`/data`). Files and folders there are readable by the tool only (`0600` and
  `0700`).
- The archives of a space contain no password hashes, and the tool signs each archive. The page **Hosting** restores
  only the archives of this installation, unchanged.
- WhiteNoise serves the static files, with browser caching.
- The tool sends the pages compressed.
- The tool sends the headers `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and
  `Referrer-Policy: same-origin`.
- Each page has a content security policy (`Content-Security-Policy` header). The browser runs only the scripts and
  the styles of the tool. A script or a style that comes from elsewhere does not run, even if someone puts it in a
  text. The page loads nothing from another site, and no other site can show it in a frame. The evidence files and the
  logo keep their own, stricter policy.
- A session expires after 12 hours.
- The tool serves the evidence files only after it checks the permissions. There is never direct access to them.
- After 5 failed sign-ins for the same identifier from the same address, the tool refuses sign-in for 15 minutes.
  It does the same after 50 failed sign-ins from the same address (all identifiers), and after 20 failed sign-ins on
  the same account from all addresses (the same person in every space; an unknown identifier is counted the same way,
  so the message does not tell whether the account exists). The message is the same for each limit. The limit applies
  to the sign-in page of the tool and to expert mode (`/admin/`). It never closes a session that is already open, and
  it does not stop the tokens of AI assistants (MCP), which do not use the password. Known and accepted drawback:
  somebody who knows the identifier of a person can block the password sign-in of this person on purpose for
  15 minutes. The server log has a line for each blocking.
- In **My account**, after 5 wrong current passwords, the tool does not check the current password for 15 minutes,
  even the right one, and says so. The session stays open. This count is per person, separate from the sign-in.
  All the server processes share these counts, and they stay after a restart: the tool keeps them in the
  `sign-in-attempts/` folder of the data folder. There is nothing to set up.
- The tool reads the address of the visitor from `X-Forwarded-For` only when `DJANGO_HTTPS=1`. Caddy or the other
  HTTPS proxy must add this header.

Over HTTPS, `python manage.py check --deploy` reports no warning.

If a screen does not work after an update (a button does nothing, a page has no colors), the content security policy
can be the cause. To find out:

1. In the `.env` file, set `CONTENT_SECURITY_POLICY_MODE=report-only`.
2. Restart the tool: `docker compose up -d`.
3. Open the screen again. If it works now, open the console of the browser (F12): each line that starts with
   `[Report Only]` names what the policy would block. Send these lines with the version of the tool.
4. When a corrected version is installed, remove the line or set `CONTENT_SECURITY_POLICY_MODE=enforce`, and restart.

With `report-only`, the protection is off: keep this value only for the time of the check.

### AI assistants (MCP): nothing to do

The tool includes a server for AI assistants (Model Context Protocol), at the address `/mcp/` of each space
(`/espace/<code>/mcp/` for another space). It runs in the same container, on the same port, behind the same HTTPS: there
is no service, no port, no variable and nothing to install. It stays off until an administrator turns it on in
**Administration › Settings › Assistants**. The only condition is that the reverse proxy passes the `Authorization`
header to the tool: Caddy (the `https` profile) and Clever Cloud do it without any setting. Assistant tokens are never in
the backups. The log of the tool shows the refused tokens (`serveur_mcp: MCP: token refused`). Details:
[`docs/mcp.md`](mcp.md), section 7.

### AI assistant (optional)

The tool can ask an AI provider (Claude, by Anthropic) for proposals: explain a consistency alert, match the KPIs of a
former file, translate labels. It is **off** in every space. An administrator of the space turns it on in
**Administration › Settings › AI assistant**, with the API key of the client's own provider account. The page lists
exactly what each use sends. Full description: `docs/ai_socket.md`.

What the IT does:

| Item | Value |
|---|---|
| Network | Allow outgoing HTTPS (TCP 443) from the server to `api.anthropic.com`. Nothing comes in. |
| Proxy | If the server goes out through a proxy, set `HTTPS_PROXY=http://proxy:port` in `.env`. |
| Key | Nothing to do: the administrator enters it in the tool. The tool keeps it in `ai-keys/` in the data folder, readable by the tool only, never in the database and never in a backup. After a restore on another server, the administrator enters it again. |
| Forbid it | `AI_SOCKET=off` in `.env`, then `docker compose up -d`. |

While the assistant is off in a space, the tool opens no connection to the provider.

## 5. Back up and restore

### What the `/data` volume contains

The tool organises this folder itself and writes a `README.txt` file in it:

- Databases and key: at the root
- Documents added to the tool: in `files/` (`evidence/<period>/<organisation>/<KPI>/`, `settings/logo/`,
  `pending-imports/`)
- Archives: in `backups/`
- Other spaces: in `spaces-data/<code>/`

Do not move anything in this folder by hand. For details, see [`docs/file_layout.md`](file_layout.md).

Only the user of the tool can read what is in this folder: the tool creates files with mode `0600` and folders with
mode `0700`, also when you run a command with `docker compose exec`. At each start, it removes the rights of the group
and of the others from the files that an older version made.

### What a backup contains

A backup is a dated `.zip` archive in `/data/backups`. It contains:

- The complete database: accounts, frameworks, campaigns, values, history, and the sign-in history of the last days
  (Administration › Settings › Hosting sets how many)
- The files added to the tool: evidence files and logo
- A description: the version of the tool and the number of rows per table

The archive contains confidential data. Keep it in a safe place.

The archive of a space contains no passwords, not even their hashes. An administrator of the space can download it, so
the tool removes the hashes from it. The passwords stay in the shared account registry, which has its own backups in
`/data/backups/shared/`. Only IT can reach these backups: the tool never lists them and never lets anyone download
them. They contain the password hashes. Keep them in a safe place and copy them with the other backups.

> **Note:** Archives made by an earlier version of the tool can still contain the password hashes. This includes the archives that
> administrators downloaded and the copies that IT made off the server. Delete them when you no longer need them, or
> keep them in a place that only IT can open.

### Back up the tool

This table shows how to back up the tool:

| To… | Do |
|---|---|
| Back up automatically | Nothing. By default, the tool makes a backup every day at 02:30 and keeps 14 archives. The team in charge sets the frequency in **Administration › Settings › Hosting**. **Copy the backups folder off the server regularly.** |
| Back up now | Run `docker compose exec web python manage.py backup`. An administrator can also click **Create and download a backup** in **Administration › Settings › Hosting**. |
| List the backups | Run `docker compose exec web python manage.py backup --list`. |
| Copy the backups off the server | Run `docker compose cp web:/data/backups/. ../probant-backups/`. This copies the archives, subfolders included, to the folder `probant-backups` next to the folder of the tool. Do not copy them into the folder of the tool: the update builds the image from this folder. Then copy `probant-backups` off the server with your usual backup tool (rsync, Veeam…), on a schedule. The copied files keep their rights: only the account that ran `docker compose cp` can read them (files `0600`, folders `0700`). If your backup tool runs under another account, give this account access to `probant-backups`, for example with `chown -R`. Do not change the rights inside the volume. |

**Without Docker**, schedule the same backup with cron: `30 2 * * * cd /opt/reporting && python manage.py backup`.

![Administration › Settings › Hosting: version, backups, test email](screenshots/en/hosting.png)

### Backups and deleted evidence

An administrator can delete the evidence files of sensitive KPIs in **Administration › Evidence to delete**. The tool deletes the file at once. A backup keeps the evidence files that existed when it was made. So the backups that already exist keep the file until the tool replaces them.

- The number of backups kept sets how long a deleted file stays. With the default values (one backup a day, 14 kept), it stays up to 14 days. If the data is very sensitive, lower the number in **Administration › Settings › Hosting**.
- A restore brings the deleted file back, and it appears again in **Evidence to delete**. After a restore, the administrator deletes it again.
- The copies that you make off the server also keep the file. Delete the old copies on a schedule that matches how long you may keep sensitive data, and tell the administrators how long the copies last.

### Restore a backup

A restore does these steps:

1. It asks for confirmation.
2. It first backs up the current state (“before-restore” archive).
3. It replaces the database and the files added to the tool.

> **Warning:** A restore replaces everything done since the date of the backup. Other people who are signed in can be
> signed out. Warn the teams, and do not restore during a data entry period.

To restore a backup from the tool:

1. Go to **Administration › Settings › Hosting**.
2. Next to the backup in the list, click **Restore…**. The confirmation page opens.

   To use a `.zip` file downloaded earlier, open **Restore from a .zip file downloaded earlier**. Choose the file,
   then click **Check the file**. The tool adds the file to the list.
3. Select the box, then enter `RESTORE`.
4. Click **Restore this backup**. The tool backs up the current state first. Then the sign-in page shows “Restore
   complete. The tool is back to the state of …”.
5. Sign in with an administrator account from the restored database.

The tool restores only the backups that it made itself, unchanged. When it makes a backup, it signs the archive with a
key that comes from the secret key of the installation (`/data/.secret_key` or `DJANGO_SECRET_KEY`). The page
refuses an archive without a valid signature, also when you add a `.zip` file: “This backup was not made by this
installation, or it was changed after it was made”. These archives have no valid signature:

- Archives made by an earlier version of the tool (before the signature existed)
- Archives made by another server, or before a change of `DJANGO_SECRET_KEY`
- Archives that someone changed after the backup

IT can still restore such an archive from the command line, if it trusts the archive: add `--unsigned` to the
`restore` command. Without this option, the command refuses the archive and changes nothing.

To restore an archive from the server (if the tool no longer starts):

1. Run `docker compose exec web python manage.py restore backup-20261026-023000-auto.zip`. For an archive without a
   valid signature, add `--unsigned`.
2. Run `docker compose restart web`.

To restore an archive that you downloaded:

1. Copy the archive into the backups folder: `docker compose cp archive.zip web:/data/backups/`.
2. Do the 2 steps of the previous procedure.

After a restore, people sign in with the password that the shared account registry has for them: their current
password. The archive of a space contains no passwords. If the registry does not know an account, this account has no
password after the restore. This occurs when you restore an archive on another server, or when an account was deleted
after the backup. The restore says it (“… account(s) of this space have no password on this server”). Then do one of
these:

- Restore the backup of the shared registry made at the same time, from `/data/backups/shared/`:
  `docker compose exec web python manage.py restore --shared <registry-….zip> --yes`. On a new server, copy the whole
  `backups` folder first, subfolders included.
- Give new passwords: `docker compose exec web python manage.py changepassword <username>` for one administrator.
  This administrator then gives the other accounts a temporary password in **Administration › Accounts**.

With SQLite, you can restore an archive made with an older version of the tool into a more recent version. The tool
updates the database automatically. The tool refuses the reverse. With PostgreSQL, an archive restores only with the
version of the tool that made it: see [Going back to the previous version](#going-back-to-the-previous-version) and
[Restore a PostgreSQL backup on a new server](#restore-a-postgresql-backup-on-a-new-server).

To restore a PostgreSQL archive made by an older version after an update:

1. Try the restore. The more recent version refuses the archive and says so. Nothing changes.
2. Go back to the version that made the archive (the restore shows its version, also in `backup.json`), and restore the
   archive with that version: see [Going back to the previous version](#going-back-to-the-previous-version).
3. Update the tool again with `./update.sh`. The update brings the restored data to the new version.

### If a restore is interrupted

If a restore is interrupted (server stopped, container stopped, disk full), nothing is lost:

- The tool first extracts the files of the archive to a separate place. If the disk is full, the restore stops before
  anything changes.
- Then the tool replaces the database in one step and swaps the files.
- If the restore stops after that point, the tool **finishes it automatically at the next start**. The log shows
  “the restore of …, interrupted, has been finished”. Until then, `/sante/` answers `503` (“interrupted restore”).

> **Warning:** Never copy `db.sqlite3` by hand. An old `db.sqlite3-wal` file next to it can damage it, with no error
> message. Always use `restore`.

### Back up and restore several spaces

An installation can have several spaces (departments). Each space has its own backups, in
`/data/backups/spaces/<code>/`. The shared account registry has its own backups, in `/data/backups/shared/`.
**Copy the whole of `/data/backups`, subfolders included.**

To run a command for one space, add `SPACE=<code>`. For example:
`docker compose exec -e SPACE=achats web python manage.py backup`. For details, see
[docs/spaces.md](spaces.md), § 2.

## 6. Update the tool

To update the tool:

1. Go to the folder of the tool (`probant`). For example: `cd probant`.
2. Run `./update.sh`. The script shows the new version when the update is complete.

The script does these steps, in this order:

1. It makes a backup named “before-update” of each space, with the version that is installed now. If the backup of
   a space fails, the update stops and changes nothing.
2. It gets the new version:
   - With `git pull`, followed by a new build of the image
   - Or, if `IMAGE` is set in `.env`, with `docker compose pull`
3. It restarts the tool. The tool applies the changes to the database structure automatically at startup. If the
   database must change, the tool first makes an automatic backup.
4. It waits for the tool to respond.

At each start, the log (`docker compose logs web`) shows a short summary in English. For example:

```text
Probant, version 1.0.0 (3f2a9c1d7e4b)
Database: PostgreSQL (db/probant), 0 migration(s) applied; installation "Probant", 23 account(s)
Data: /data; backups: /data/backups (14 archive(s))
Address(es): reporting.example.com; HTTPS: yes
E-mails: SMTP smtp.example.com:587
```

When the database must change, the log shows this line and the path of the archive before the summary:
`Updating space "principal" (3 migration(s)): automatic backup before.`

The version number is shown at the bottom of every page and in **Administration › Settings › Hosting**.

### Going back to the previous version

> **Warning:** Going back replaces everything done since the “before-update” backup. Warn the teams, and do it when
> nobody enters data.

The update makes a “before-update” backup of each space before it changes anything. List the backups:
`docker compose exec web python manage.py backup --list` (add `-e SPACE=<code>` for another space). The archives of
another space are in `/data/backups/spaces/<code>/`, and the archive of the shared registry is in
`/data/backups/shared/`. The version that made an archive can always read it: to go back, use the oldest
“before-update” archive of the update.

The steps depend on the database:

- **SQLite** (default): do the steps below, without `--rebuild`.
- **PostgreSQL**: a PostgreSQL backup (JSON format) restores only into a database that has exactly its migrations.
  After an update, the database has more migrations. The option `--rebuild` of `restore` drops the tables of the space,
  creates them again for the version that is installed, then loads the backup. It does all of this in one step: if a
  step fails, the database does not change.

To go back to the previous version:

1. Stop the tool: `docker compose stop web`.
2. Get the previous version, without starting it:
   - With `git`: find it (`git log --oneline -5`), then run `git checkout <previous-version>` and
     `docker compose build web`.
   - With a published image: set `IMAGE=` to the previous image in `.env`, then run `docker compose pull web`.
3. Restore the “before-update” archive of the main space:
   `docker compose run --rm web python manage.py restore <before-update archive> --yes --rebuild`
   (SQLite: without `--rebuild`).
4. For each other space, restore its own archive:
   `docker compose run --rm -e SPACE=<code> web python manage.py restore <archive of this space> --yes --rebuild`.
5. Optional: to bring back the accounts and passwords as they were before the update, restore the shared registry:
   `docker compose run --rm web python manage.py restore --shared <registry-…-before-update.zip> --yes`.
   Without this step, everyone keeps their current password.
6. Start the tool: `docker compose up -d`.

If a restore says that the archive has no valid signature of this installation (an archive made on another server,
for example), run the same command again with `--unsigned`.

Each restore first backs up the current state (“before-restore” archive). Keep these archives until the tool works
again.

To update the tool again later, go back to the main branch first: `git checkout main`, then `./update.sh`. After
`git checkout <previous-version>`, `git pull` refuses to run (“You are not currently on a branch”), and `update.sh`
stops.

#### Restore a PostgreSQL backup on a new server

A PostgreSQL backup restores only with the version of the tool that made it, or with `--rebuild`. On a new server,
install the tool, restore the shared registry (`restore --shared`), then the main space and each other space (steps 3
and 4 above). The new server has another secret key: add `--unsigned` to the restore of each space, or copy the file
`.secret_key` of the former data folder into the new one before the first start.

## 7. Set up emails (SMTP)

To set up emails:

1. Add these values to `.env`:

   ```
   SMTP_HOST=smtp.office365.com
   SMTP_PORT=587
   SMTP_SECURITY=starttls        # starttls (587), ssl (465) or none
   SMTP_USER=reporting@example.com
   SMTP_PASSWORD=…
   SMTP_FROM=reporting@example.com
   ```

2. Run `docker compose up -d`.
3. Go to **Administration › Settings › Hosting**, and click **Send a test email**. If the email is not sent, a message
   gives the exact cause.

Without SMTP, the tool sends no email. It only writes the messages in the log (`docker compose logs web`).

### Reminders

The team in charge manages the reminder emails in **Dashboard › Remind…**. Each person receives a single email, with
no copy. The email lists what the person still has to enter. Before the tool sends the email, it shows the exact
preview of the message. The team in charge sets the template.

The team in charge can turn on automatic reminders on the same page. The tool sends them on the chosen days before
the end of data entry. It checks for them every day at `REMINDER_TIME` (09:00 by default). `PUBLIC_URL` gives the
address in these emails. By default, the tool takes this address from `DOMAIN`.

![Dashboard › Reminders: people, message preview, template and automatic reminders](screenshots/en/reminders.png)

## 8. Use PostgreSQL (optional)

SQLite is the default database. You do not need to manage a database server. SQLite writes one save at a time. The
other saves wait for their turn, for up to 60 seconds.

### Capacity

Two load tests measured the capacity. The capacity depends on the size of the database, because each save
recalculates the totals that it changes. This table shows the results:

| Database | Measure | Result |
|---|---|---|
| Small (the demo) | Load test, SQLite, server with 2 to 4 processors used only by the tool | Comfortable with up to about 100 people who enter data at the same moment |
| Large (679 organisations, 1.27 million answers) | Load test (`qa/load/README.md`). Each simulated person works about ten times faster than a real person. | SQLite: 10 very active people without an error. From 15 to 20 people, some saves fail with "database is locked". PostgreSQL: 50 people without an error and without a lost save, but saves wait in a queue. |

Recommendation: use PostgreSQL when more than about twenty people are active at the same moment. Also use PostgreSQL if
the server runs other heavy programs, and give the server more processors.

During the busiest days of a campaign, avoid the operations that rewrite everything at once:

- **Redo all calculations** on a campaign
- Reopening a closed campaign
- Adding or deactivating an organisation
- An import of several thousand rows

The tool writes an import in blocks of 100 rows. Other people are not blocked, but the import takes longer. Above
`BACKGROUND_IMPORT_ROWS` rows, the import runs in the background, one import at a time.

### Switch to PostgreSQL

You can switch to PostgreSQL in 2 ways. This table shows the settings in `.env` for each way:

| Option | Setting in `.env` |
|---|---|
| PostgreSQL provided in the same file | `COMPOSE_PROFILES=postgres` and `DATABASE_URL=postgres://probant:PASSWORD@db:5432/probant`, where `PASSWORD` is the value of `POSTGRES_PASSWORD`. |
| Existing PostgreSQL server | `DATABASE_URL=postgres://user:password@server:5432/database`. Encode a special character in the password. For example, `@` becomes `%40`. |

With PostgreSQL, the backup contains the database in JSON format. You can restore it only with the version of the tool
that made it. To go back to the previous version after an update, see
[Going back to the previous version](#going-back-to-the-previous-version).

After a large load in one step, the tool updates the statistics of the PostgreSQL planner (`ANALYZE` on the tables of
the space). A large load is a restore, the installation or update of a library template, the import of a configuration
file, or a data takeover. The database user must own the tables of the tool. This is the case when the tool creates
them. If `ANALYZE` fails, the operation is kept and the log shows a warning. PostgreSQL then updates the statistics
itself, a few minutes later.

### Move an existing SQLite installation to PostgreSQL

Do this when nobody works in the tool: whatever people enter after the backups of step 1 is lost. Keep the same data folder
(the same `/data` volume), use an empty PostgreSQL database, and keep the same version of the tool.

The move needs these archives: one backup in JSON format for **each space**, and one archive of the **shared registry**
(accounts, list of spaces, access). The new PostgreSQL registry has a new identity. Without the archive of the registry, the
tool refuses the backup of the main space (“another installation”).

Do these steps in this order:

1. Back up each space in JSON format. Run `docker compose exec web python manage.py backup --json` for the main space, and
   `docker compose exec -e SPACE=<code> web python manage.py backup --json` for each other space. The command
   `docker compose exec web python manage.py spaces` lists the spaces and their codes.
2. Make an archive of the shared registry:
   `docker compose exec web python manage.py shell -c "from parametres import sauvegardes as SV; print(SV.creer_registre('before-postgresql'))"`.
   The tool also makes one every day in `backups/shared/`: use it only if nobody created or changed an account since then.
3. Write down the name of each archive: `backups/` (main space), `backups/spaces/<code>/` (other spaces), `backups/shared/`
   (registry). Copy the three folders off the server.
4. Change `DATABASE_URL` in `.env`.
5. Run `docker compose up -d`. The tool starts with an empty database and shows the setup wizard. Do not use the wizard.
6. Restore the shared registry: `docker compose exec web python manage.py restore --shared <registry archive> --yes`.
   The command can end with a database error about a table that does not exist (`relation "referentiel_utilisateur"
   does not exist`). This is expected, because the other spaces have no tables yet. The registry is restored. Run
   `docker compose exec web python manage.py spaces` to check that it lists your spaces.
7. Restore the main space: `docker compose exec web python manage.py restore <archive of the main space> --yes`.
8. Restore each other space: `docker compose exec -e SPACE=<code> web python manage.py restore <archive of this space> --yes --rebuild`.
   The option `--rebuild` creates the tables of the space in PostgreSQL before it loads the archive.
9. Run `docker compose restart web`. Sign in, and check the values of each space.

If the installation has only the main space, you can make it shorter. Skip steps 2, 6, and 8, and add `--other-space` to
step 7. This way, the tool creates the registry again from the accounts of the main space. The tool does not keep the
name of the space or the accounts that exist only in another space.

The command `python manage.py shell` in step 2 is the only way to make an archive of the registry on demand. The tool does not
have a command for it. We compared the data of the PostgreSQL installation with the SQLite installation, table by table, for
two spaces: it is identical (only the numbers of the access rows of the registry change).

### Several spaces with PostgreSQL

Each space (department) opens its own connections to the database. Before you create many spaces, check the
connection limit of your plan (small Clever Cloud plans). See [docs/spaces.md](spaces.md).

## 9. Monitor the tool and read the logs

### Check that the tool is healthy

`GET /sante/` answers with one of these codes:

- `200` with `{"etat": "ok"}`: the tool works.
- `503` with `{"etat": "erreur"}`: the database or the storage has a problem, the database is damaged, a restore was
  interrupted, or the disk is almost full (less than 100 MB free, `DISK_ALERT_MB` setting). The details give the
  cause in `alerte`.

The page needs no sign-in and shows no sensitive data. Docker uses it too: `docker compose ps` shows `healthy`.

The tool gives the details of the whole installation only to a call from the server itself (from `127.0.0.1`, with
none of the headers that a proxy adds: `X-Forwarded-For`, `X-Real-IP`, `Forwarded`), to a signed-in space manager,
and to a signed-in administrator of the main space. The administrator of another space gets the details of their own
space only: the shared registry and the disk are measured, but the names, failures and stuck tasks of the other spaces
and the folders of the disk are not shown. Other people get the state only. The reason is that the exact version can
help to find an installation that is not up to date, and that the administrator of one space does not have to know the
other spaces. To see the details from the server, run this command:

```bash
docker compose exec web python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/sante/').read().decode())"
```

This table shows the fields of the details:

| Field | Content |
|---|---|
| `version`, `base`, `stockage`, `derniere_sauvegarde` | The version, the state of the database and of the storage, and the date of the latest backup |
| `alerte` | The cause of a `503` answer |
| `avertissement` | A warning that does not cause `503`, for example a stuck import or export, or a backup dated in the future |
| `controle_donnees` | The latest data check: `etat` (`ok`, `problems`, `late` if there is no data check for 48 hours, `never`), `date`, `erreurs`, `avertissements` |
| `background_imports` | The state of the background imports (see “Check that a large import is not stuck”) |
| `background_exports` | The state of the large exports in the background: `running`, `waiting`, `stuck` (same section) |

A data problem or a late check **never** makes `/sante/` answer `503`. `503` means “the tool does not answer”. Docker
or Clever Cloud then restart the tool, and a restart fixes neither a figure nor a stopped scheduler. To watch the
nightly check, set an alert on `controle_donnees.etat` = `late`.

![Response of /sante/](screenshots/en/health.png)

The administrators read the same measures, in plain words, in **Administration › Settings › Health**: one line per
check (version, database, files, last backup, disk space, email, background tasks, database update, HTTPS), with
**Good**, **To check** or **Failure** and what to do. The detail for IT (names of the spaces, folders on the disk,
messages of `/sante/`) is shown only to the space managers and to the administrators of the main space. The same rule
applies to the “For IT” box of **Settings › Hosting**: in another space, the administrator who is not a space manager
does not see the data folder, the allowed addresses, the database server, the SMTP username or the backups folder.

### Check that the data is consistent

Every night at `DATA_CHECK_TIME` (03:30), the tool checks the database of each space. It **changes nothing**. It
checks these points:

- Every stored total and calculation, in the periods that are not closed: the tool calculates it again in memory and
  compares (for closed periods, it only reports)
- No value attached to a deleted KPI or organisation, to a period without a campaign, or recorded twice
- Consistent statuses
- Plausible percentages (−100% to 1,000%)
- Figures of calculated KPIs imported as they are in an open period
- Assignments of open campaigns to inactive or read-only accounts, or to closed organisations
- Evidence files present on the disk (and files left over in `files/evidence`)
- Formulas and their stored dependencies
- A tree with no loop and with consistent levels
- A readable latest backup (valid zip, `backup.json`)

The tool keeps the last 10 results in `backups/data-checks.json`, outside the database, like `restores.jsonl`. The
administrator sees them in **Administration › Settings › Hosting**, in the **Data check** box. This box has the
**Check now** button. When the check finds something, it also shows in **To be handled**.

To run the check by hand, run `docker compose exec web python manage.py check_data`. The French name
`controler_donnees` also works. The command has these options and results:

- Output: readable text in English, or JSON with `--json`
- `--no-save`: the tool does not keep the result
- `SPACE=<code>`: only one space
- Exit code 1 if the check finds an error
- Duration: a few seconds (6 s on the demo, with 6 reporting years)

### Deleted items (trash) and expired sessions

When a person deletes a saved export, a KPI list or a Visualisation view, the tool keeps it in a trash, so that the
person can undo the deletion or restore the item from **My account › Recently deleted**. An administrator sees the
items of everyone in **Administration › History › Recently deleted**. The trash keeps the items for 30 days by
default. An administrator sets this delay, from 1 to 365 days, in **Administration › Settings › Hosting**, box
**Deleted items**. After the delay, the tool erases the item for good.

The `check_data --schedule` process also does a clean-up every night at `DATA_CHECK_TIME`, and once when it starts:

- It erases the expired sessions, like `manage.py clearsessions`. The sessions of all the spaces are in the shared
  registry. A session that is still valid is never erased.
- It erases the deleted items older than the delay, in each space.
- It writes one line in the log: `Nightly clean-up: N expired session(s) and N deleted item(s) erased for good`.

You have nothing to schedule. The tool also does this at each start (`manage.py startup`), and erases the old deleted
items each time someone deletes something. To erase the deleted items by hand, run
`docker compose exec web python manage.py purge_deleted` (French name: `purger_corbeille`; `SPACE=<code>` for only
one space). To erase the expired sessions by hand, run `docker compose exec web python manage.py clearsessions`.

### Check that a large import is not stuck

Large value imports run in the background, in the `run_imports --schedule` process. The image starts this process
next to the backups, the reminders, and the data check. The same process makes the large exports (above the threshold
that the administrator sets in **Administration › Settings › Hosting › Large exports**). Their files are in
`files/exports/` of the data folder, are deleted after 7 days, and are never in the backups: nothing to copy. The details of `/sante/` give `background_imports` for the imports and `background_exports` for the
large exports, with the same three fields:

- `running`: the number of imports (or exports) that run
- `waiting`: the number of imports (or exports) that wait
- `stuck`, with a `message` (also in `avertissement`): an import (or an export) that gives no sign of life, or that
  waits for more than 10 minutes

If an import or an export is stuck:

1. Check that the process runs: `docker compose logs web | grep "Background"`.
2. If necessary, restart the tool: `docker compose restart web`.

A stuck import or export never makes `/sante/` answer `503`. If a restart stops a task, the task starts again once
automatically. After that, the tool marks it as “interrupted”. It tells the person to import the file again, or to ask
for the export again.

### Read the log and manage the services

This table shows the other monitoring operations:

| To… | Do |
|---|---|
| Read the log | Run `docker compose logs -f web`. Each line has the date. The log contains the startup (version, database, addresses, emails), each request (address, page, code, duration), the backups, and the errors. Like the output of the `manage.py` commands, the log is always in English, whatever the language of the interface. |
| See the state of the services | Run `docker compose ps`. |
| Restart | Run `docker compose restart web`. |
| Stop, then start again | Run `docker compose down`, then `docker compose up -d`. The data stays in the volume. |

## 10. Troubleshooting

This table shows common problems, their likely cause, and the solution:

| Symptom | Likely cause and solution |
|---|---|
| `Bad Request (400)` when you open the tool | The address is not in `DOMAIN`. Add it to `.env` (separate several values with commas). Then run `docker compose up -d`. |
| The page does not open | Check that the service runs (`docker compose ps`). Check that the firewall opens the port. Then read `docker compose logs web`. |
| Redirect loop or CSRF error (403) over HTTPS | `DJANGO_HTTPS=1` is set, but the proxy does not send `X-Forwarded-Proto: https`. Caddy sends it automatically. With another proxy (nginx, Traefik…), add this header. |
| No HTTPS certificate | The domain name must point to the server, and ports 80 and 443 must be open. Read `docker compose logs caddy`. |
| “The folder /data is not writable by the tool” | A folder mounted in place of the volume belongs to another user. Run `sudo chown -R 1000:1000 <folder>`. |
| “Database unreachable” | With PostgreSQL, check `DATABASE_URL`. Then read `docker compose logs db`. |
| “DAMAGED DATABASE” in the log, `/sante/` answers `503` “damaged database” | The startup check (or a backup) found that the SQLite file is damaged (disk fault, file copied by hand next to an old `-wal` file…). The tool starts without updating the database and refuses to back it up, so the good archives stay. The log gives the last good archive. Restore it: `docker compose exec web python manage.py restore <that archive> --yes`. Then run `docker compose restart web`. The tool keeps the damaged state: a “before-restore-damaged” archive, or the file renamed `db.sqlite3.damaged-<date>` if it no longer opens. If no archive is good, use the external copy of the backups. |
| “Not enough disk space” (backup, update, or restore), `/sante/` “disk almost full” | Nothing is half-written. The tool does not keep the backup and does not apply the update (the database does not change). It cancels the restore. Free some space: copy old archives off the server, or enlarge the disk. Then run the command again, or run `docker compose restart web`. People who try to save see “Saving is not possible for now”. Nothing that they did is half-saved. |
| “This archive has no valid signature of this installation” (restore command), or “This backup was not made by this installation” (Hosting page) | Nothing was changed. The archive was made by an earlier version, by another server, or before a change of `DJANGO_SECRET_KEY`, or someone changed it. If you trust it, restore it from the command line with `--unsigned`: `docker compose exec web python manage.py restore <archive> --yes --unsigned`. If you do not know where it comes from, do not restore it. |
| “The database was updated by a more recent version of the tool” or “made with other database migrations” (restore, PostgreSQL) | Nothing was changed. The message gives the exact command. To go back after an update, see [Going back to the previous version](#going-back-to-the-previous-version). To restore on a new server, install first the version that made the backup. To restore an older archive after an update: restore it with the version that made it, then update again with `./update.sh`. |
| “the restore of … was interrupted and could not be finished” | The archive in the message is missing or cannot be read. Restore it again (`python manage.py restore <name> --yes`). To go back to the state before, restore the “before-restore” archive. |
| Everyone must sign in again after a restart | The `.secret_key` file of the data folder was deleted or empty. The tool created a new key (log: “New secret key created”). Nothing else is lost. |
| Wrong server clock (date in the future, then corrected) | The tool keeps the backups dated in the future, but does not count them in the rotation. The next automatic backup runs at the usual time. `/sante/` gives a warning (`avertissement`). Fix the clock (NTP). |
| “database is locked” | A save waited more than 60 seconds for its turn: SQLite writes one save at a time. This is rare, because SQLite runs in WAL mode. When it occurs, the server is overloaded. Check that the tool has its processors to itself (`docker stats`). Avoid **Redo all calculations** and large imports during the busiest hours. Then give the server more processors, or switch to PostgreSQL (section 8). |
| The test email fails | The message gives the cause (username refused, port blocked, TLS…). Check the `SMTP_…` settings with the email provider. |
| The AI assistant says “The provider cannot be reached from the server” | Allow outgoing HTTPS to `api.anthropic.com` in the firewall, or set `HTTPS_PROXY` (section 4, “AI assistant”). |
| Administrator password lost | Another administrator resets it in **Administration › Accounts**. If there is no other administrator, run `docker compose exec web python manage.py changepassword <email>`. |
| No account can open **Administration** any more | The tool never lets the last active administrator lose the role or the access. This can still occur after a restore of an old backup, or after a change made directly in the database. Give the administrator role back to an existing account: `docker compose exec web python manage.py grant_admin <email>`. The tool records the change in the history. |
| Start again from scratch (trial) | **Warning:** this **deletes all the data**. Run `docker compose down -v`, then `./install.sh`. |

## 11. Test the installation

The script `bash docker/test_installation.sh` reproduces an installation on a blank machine. It copies the repository
into an empty folder and runs `./install.sh`. Then it checks these points:

- The health page
- The wizard, shown in place of the sign-in page
- The static files and the compression
- The security headers
- `check --deploy` over HTTPS
- The backup
- The update, with a backup made first
- The data, kept after the update

At the end, the script deletes everything that it created. To run the same test with the test suite, run
`TESTER_DOCKER=1 python manage.py test parametres.test_hebergement`.
