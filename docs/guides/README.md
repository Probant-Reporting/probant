# Guides by role

One short guide per role, written by task, in the seven languages of the interface. French version: [`docs/fr/guides/LISEZ-MOI.md`](../fr/guides/LISEZ-MOI.md).

| Role | English | French | Spanish | German | Italian | Dutch | Portuguese |
|---|---|---|---|---|---|---|---|
| Administrator | [administrator.md](administrator.md) | [administrateur.md](../fr/guides/administrateur.md) | [administrador.md](../es/guides/administrador.md) | [administrator.md](../de/guides/administrator.md) | [amministratore.md](../it/guides/amministratore.md) | [beheerder.md](../nl/guides/beheerder.md) | [administrador.md](../pt/guides/administrador.md) |
| Validator | [validator.md](validator.md) | [validateur.md](../fr/guides/validateur.md) | [validador.md](../es/guides/validador.md) | [validator.md](../de/guides/validator.md) | [validatore.md](../it/guides/validatore.md) | [validator.md](../nl/guides/validator.md) | [validador.md](../pt/guides/validador.md) |
| Contributor | [contributor.md](contributor.md) | [contributeur.md](../fr/guides/contributeur.md) | [colaborador.md](../es/guides/colaborador.md) | [mitwirkender.md](../de/guides/mitwirkender.md) | [collaboratore.md](../it/guides/collaboratore.md) | [bijdrager.md](../nl/guides/bijdrager.md) | [colaborador.md](../pt/guides/colaborador.md) |
| Reader | [reader.md](reader.md) | [lecteur.md](../fr/guides/lecteur.md) | [lector.md](../es/guides/lector.md) | [leser.md](../de/guides/leser.md) | [lettore.md](../it/guides/lettore.md) | [lezer.md](../nl/guides/lezer.md) | [leitor.md](../pt/guides/leitor.md) |
| Auditor | [auditor.md](auditor.md) | [auditeur.md](../fr/guides/auditeur.md) | [auditor.md](../es/guides/auditor.md) | [auditor.md](../de/guides/auditor.md) | [auditor.md](../it/guides/auditor.md) | [auditor.md](../nl/guides/auditor.md) | [auditor.md](../pt/guides/auditor.md) |

The English guide is the base. The other six are translated from it, with the exact words of the interface of each language.
The folders are `docs/guides/` (English) and `docs/<language>/guides/` (`fr`, `es`, `de`, `it`, `nl`, `pt`).

## Help in the tool

The tool serves these files itself, with no Internet access (`collecte/aide.py`):

- The **Help** icon in the top bar opens the guide of your role, at the section of the page that you are on, in the language
  of the interface. A language of the interface that has no guide yet gets the English guide, with a note.
- The address `/aide/` opens your guide, `/aide/<role>/` another one (`administrator`, `validator`, `contributor`,
  `reader`, `auditor`). Every signed-in person can read every guide: they contain no data.
- The Docker image and the portable package include `docs/guides/`, `docs/<language>/guides/` and `docs/screenshots/`.

## Write or change a guide

- Follow `docs/writing_guide.md`. Write the English guide first, then the French one, then the five other languages, with
  the same sections.
- A section is `## Task title {#anchor}`. The anchors are the same in the seven languages: the Help link uses them
  (`SECTIONS` and `PREFIXES` in `collecte/aide.py`). A test checks them.
- A bold text is a label of the tool, exact (path: **Administration › Settings**). A test checks each bold text against
  `libelles/` of the language of the guide, for the seven languages. Use plain text for anything else.
- An image is a line alone: `![Short description](../screenshots/en/name.png)` (other languages:
  `../../screenshots/<language>/…`). A guide cites the screenshots of its own language.
- A new language needs its folder `docs/<language>/guides/`, its names in `GUIDES` and `LANGUES_GUIDES` (`collecte/aide.py`),
  its screenshots, and the line in `docs/file_layout.md`.
- Tests: `python3 manage.py test collecte.test_aide_guides`.

## Make the screenshots again

The screenshots are made by a script from the fictitious Exemplia demo (2026 open), in the seven languages (one demo loaded in each language, so that the texts of the demo match the interface), at a fixed size
(1,280 × 720 px on a computer, 390 × 844 px on a phone, `deviceScaleFactor` 2). Nothing is real data. The 27 screens of the
guides are made for every language (the screen `guided-tour` is taken on purpose with the guided tour switched on; all others with it off). The 5 screens of the installation guide (`login`, `health`, `setup-*`) are made for
English and French only, because `docs/installation.md` exists in these two languages.

```bash
python3 -m pip install -r requirements-dev.txt          # Pillow compresses the images
node qa/guide_screenshots.js                            # all screens, the seven languages
node qa/guide_screenshots.js --langs en,fr --only dashboard,reminders --port 8271
```

The script creates throwaway databases in a temporary folder (never `local-data/`), starts two servers on `--port` and
`--port` + 1 (8261 by default), takes the screens, writes `docs/screenshots/<lang>/<name>.png` (each under 300 KB) and
stops. It needs Node.js with Playwright and Chromium (`qa/browser_journeys/README.md`). Options: `--python` (the Python of
the project), `--out`, `--keep`, `--data-dir`. Run it again after any change of a screen, then commit the images.
The installation guide (`docs/installation.md`) cites the same images.
