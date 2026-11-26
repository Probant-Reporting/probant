# File layout

This page tells you where each kind of document goes: in the data folder of an installation, or in the code folder.

The rule is simple: **each kind of document has its own folder, and nothing is mixed**. What ships with the tool (the
code, the starter framework) stays in the code folder. What belongs to an installation (databases, evidence files,
logo, backups) goes into **its data folder**, never into the code folder. A single place defines the layout:
`parametres/rangement.py`.

## 1. The data folder of an installation

### Find the data folder

The table shows where the data folder is, for each kind of installation:

| Where | Data folder |
|---|---|
| Docker image (IT server) | `/data` (the volume) |
| Development machine, Codespace | `local-data/` in the project folder (never versioned) |
| All-in-one version (Windows, Mac) | `data/` next to `Start.bat` / `Start.command` (already organised in the package, which `portable/build_package.py` builds) |
| Managed hosting provider | The persistent folder set by `DATA_DIR` |

### Contents of the data folder

The tool organises the data folder itself. A `README.txt` file in the folder reminds IT of this layout:

```
<data folder>/
├── README.txt                   this layout
├── db.sqlite3                   database of the main space (SQLite; with PostgreSQL, the database lives elsewhere)
├── shared.sqlite3               account registry, shared by all spaces
├── .secret_key                  installation key: never share it
├── .secret_key_all_in_one       key of the all-in-one version: never share it (a server makes its own)
├── files/                       DOCUMENTS UPLOADED IN THE TOOL (main space)
│   ├── evidence/                contributors' evidence files
│   │   └── <period>/<organisation>/<KPI>/<file>
│   │       example: evidence/2026/ES-COM/100245/gas-invoice.pdf
│   ├── settings/
│   │   └── logo/                logo of the installation (Administration › Settings › Identity)
│   ├── pending-imports/         files uploaded for an import; deleted after use, never backed up
│   └── exports/                 large exports made in the background; deleted after 7 days (setting), never backed up
├── sign-in-attempts/            count of failed sign-ins, shared by all the server processes (never backed up)
├── ai-keys/<code>.key           key of the AI assistant of each space (docs/ai_socket.md): never in the database, never backed up
├── ca-bundle.pem                certificate authorities of the system and those added by the IT, joined at each start (only when the IT adds authorities, docs/installation.md, "Company network"); never backed up
├── backups/                     DATED ARCHIVES (database + files)
│   ├── backup-YYYYMMDD-HHMMSS-<reason>.zip    main space
│   ├── restores.jsonl           restore history
│   ├── data-checks.json         last results of the nightly data check (check_data)
│   ├── .restore-in-progress.json  only while a restore runs (or was interrupted: finished at the next start)
│   ├── .database-damaged        only if the integrity check failed (reported by /sante/)
│   ├── shared/                  archives of the account registry
│   └── spaces/<code>/           archives of the other spaces
└── spaces-data/                 OTHER SPACES (Purchasing, HR…)
    └── <code>/
        ├── database.sqlite3
        └── files/               same layout as above (evidence/, settings/logo/, pending-imports/, exports/)
```

The names of folders and files are in English, for example `evidence/` for evidence files and `backups/` for backups.
The interface of the tool is available in French, English, Spanish, German, Italian, Dutch, and Portuguese.

### Reasons in the names of backup archives

The reason at the end of the name of an archive says why the tool made it:

| Reason | The archive comes from |
|---|---|
| `auto` | The automatic backup |
| `manuelle` | The **Create and download a backup** button, in **Administration › Settings › Hosting** |
| `before-update` | The backup before an update |
| `before-restore` | The backup before a restore |
| `uploaded` | An archive imported in the tool |
| No reason | The `backup` command, without `--reason` |

### Where each kind of document goes

The table shows who adds each kind of document, where it goes, and if the backups contain it:

| Kind of document | Who adds it | Where it goes | Backed up |
|---|---|---|---|
| Evidence file (PDF, JPG, PNG) | Contributor, validator, administrator, from the cell of a KPI | `files/evidence/<period>/<organisation>/<KPI>/` | Yes |
| Logo | Administrator (**Administration › Settings › Identity**) | `files/settings/logo/` | Yes |
| Import file (values, configuration, framework, data migration) | Administrator | `files/pending-imports/`, deleted after the import or after one day | No (temporary) |
| Backup archive | Automatic, or administrator / IT | `backups/` | — |
| Copy of a backup archive outside the server | The tool, when a destination is set (**Settings › Hosting › External copy**) | At the destination: `<folder or prefix>/<identifier of the installation>/`, with the same layout as `backups/` (`backup-….zip`, `spaces/<code>/`, `shared/`). What is already copied is noted in the shared account registry, never in a file of the data folder. | — |
| Excel or CSV export | Any user | Downloaded directly, never kept on the server | — |
| Large export (above the threshold of **Settings › Hosting › Large exports**) | Any user who can export | `files/exports/<random name>.xlsx` or `.csv`, until the person downloads it within 7 days (setting); then deleted by the scheduler, also at startup | No (made again on request) |

### Folders of evidence files

The folder of an evidence file follows the path of an auditor:

1. The period: "2026", or "2026-03" for a shorter period
2. The organisation: its code, which does not change when you rename the organisation
3. The KPI

The file name is the name of the file that the person added, without special characters. Two files with the same name in the same
cell never overwrite each other: the second file gets a suffix.

## 2. The code folder

The code folder contains the tool and the content that ships with it:

```
collecte/  parametres/  referentiel/  espaces/  serveur_mcp/  config/   the tool's code
templates/  static/  libelles/                           pages, styles, texts (seven languages)
resources/                                              local working files, never versioned (empty in the repository)
docs/                                                    guides (installation, acceptance testing, file layout…)
docs/fr/                                                 French translation of the key guides
docs/guides/, docs/<language>/guides/                    guides by role in the seven languages (fr, es, de, it, nl, pt), served by the tool (Help)
docs/screenshots/<language>/                             screenshots of the guides (made by qa/guide_screenshots.js)
qa/  docker/  portable/  .devcontainer/                  verification and installation tools
local-data/                                              development data (ignored by git)
```

A real working file (real data, names, emails) never goes into `resources/`. Import it in the tool, or put it in the
data folder of the installation.

## 3. Switch to this layout, without loss

An installation changes to this layout by itself when you update it. Nothing is lost.

### Files of each space

At startup, and then through migration `collecte/0029`, the tool changes these folders for each space:

| Before | After |
|---|---|
| `media/` | `files/` |
| `evidence/<period>/<KPI>/<organisation no.>_<file>` | `evidence/<period>/<organisation>/<KPI>/<file>` |
| `identite/` (logo) | `settings/logo/` |
| `imports/` | `pending-imports/` |

The tool moves the files: it never copies or overwrites them. The name of each file in the database follows the move.
A file that is already missing keeps its name.

### Development machine and Codespace

On first launch, the databases, files, and backups at the root of the project move by themselves into `local-data/`.

### Old backup archives

You can still restore an old backup archive. The migration organises its files, like the files of an updated
installation.
