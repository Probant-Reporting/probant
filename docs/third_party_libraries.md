# Third-party libraries

This page lists the libraries and the font that the tool includes, with their checksums and licences. It also
explains how to update a library.

The tool calls no external service. The libraries are **copied into the repository** (`static/vendor/`), without
change, with their licence next to them:

- WhiteNoise serves and compresses them, like the stylesheet.
- The version is part of the folder name, so browser caches are never out of date.
- Only the Visualisation page loads them (`{% block scripts %}` block of `templates/base.html`, filled in
  `collecte/templates/collecte/visualisation/page.html`).

The tool therefore works offline, also in the all-in-one version (Windows or Mac).

The table shows the libraries and the font.

| Library | Version | Released on | Licence | Role | Folder |
|---|---|---|---|---|---|
| Apache ECharts | 6.1.0 | 19/05/2026 | Apache-2.0 (contains zrender 6.1.0, BSD-3-Clause, excerpts from d3, BSD-3-Clause, and tslib, 0BSD) | Visualisation charts | `static/vendor/echarts-6.1.0/` |
| SortableJS | 1.15.7 | 11/02/2026 | MIT | Drag and drop in the Visualisation (KPIs, visuals, tabs) | `static/vendor/sortablejs-1.15.7/` |
| Source Sans 3 (font) | – | – | SIL OFL 1.1 | Interface font | `static/polices/` |
| Lucide (icons) | 1.2.151 (`@iconify-json/lucide`) | – | ISC (Feather icons: MIT) | All the icons of the interface, written into the pages by `{% icone %}` (no script) | `collecte/icones/` (see its `README.md`) |
| EFRAG VS Digital Template (Excel workbook) | 2.0.0 (taxonomy 2026-10-16) | 04/11/2026 | MIT (© 2025 EFRAG) | Official workbook of the Voluntary Standard (VS, formerly VSME), filled in by the official-format export; its labels and enumerations are reused in the VS templates | `referentiel/bibliotheque/formats/` (`vs_digital_template_2.0.0.xlsx`, SHA-256 `6de5209bb247317b5632332396f2787e4ad533b7ff15c5e6ae958eaa4b9dcdab`, notice `LICENSE-EFRAG.txt`) |

## Development package of the MCP server and the AI socket

The MCP server and the AI socket add **no package to production** (`requirements.txt` is unchanged): the MCP server is a
Django view, and the call to the AI provider uses the Python standard library. Only the development file
`requirements-dev.txt` gains the official MCP client (`mcp` 2.3.0 and its dependencies, all pinned). It serves one test,
the end-to-end test of the server (`serveur_mcp/test_client_officiel.py`). The AI socket calls the network only when an
administrator turns it on with a key; the tests never call it.

## Files and checksums (SHA-256)

`collecte/test_bibliotheques.py` checks these checksums: if a file is changed or replaced, the tests fail. The test
also fails if `static/vendor/` contains a file that is not in this list. The table shows each file and its checksum.

| File | Checksum |
|---|---|
| `echarts-6.1.0/echarts.min.js` (1,121,883 bytes, 369 KB compressed) | `b66b25aeb4df84e33199dc21694014d336d222cbd9deb0e5a7c14bd6aa0d0fd0` |
| `echarts-6.1.0/langFR.js` | `b754ab555ef9c5df6afe4baa8eb78274249c395165ae49b4a71e084919711ec2` |
| `echarts-6.1.0/langEN.js` | `58c4e62edd59e39e730deb563b88a6f47a10cc23bce3190f350a5ff34d9ef32e` |
| `echarts-6.1.0/LICENSE` | `634293835b43a6dd2094fa39182a3d9a6b9ca43b7fdb9ac354e8037af2a3093a` |
| `echarts-6.1.0/NOTICE` | `d491d358344f842685c1b1585970999db65fe30ecf7ef3867af8814f4016c016` |
| `echarts-6.1.0/LICENSE-d3` (`licenses/LICENSE-d3` from the package) | `e1211892da0b0e0585b7aebe8f98c1274fba15bafe47fa1f4ee8a7a502c06304` |
| `echarts-6.1.0/LICENSE-zrender` (`LICENSE` from zrender 6.1.0) | `a681e9d183c72b4af4856935893805eb48c08f0f5a3f260203db7444c20fb98a` |
| `sortablejs-1.15.7/Sortable.min.js` (45,478 bytes, 15 KB compressed) | `bf4241bc73fef7f11c59a283a69fe8051cdd31c6d8ff5a2b9ba219e7831fcf76` |
| `sortablejs-1.15.7/LICENSE` | `e94dfc31e800d169257569db270457c9f028440c9ccae41e7eb78b2db18f1298` |

Integrity of the npm packages (sha512 of the archive, checked by `npm pack`):

- echarts 6.1.0: `q0yaFPggC9FUdsWH4blavRWFmxdrIodbkoKNAjJudAI6CA9gNPxHtV2RcZNEepZVlk4yvBYkOkbk6HIVpIyHZA==`
- zrender 6.1.0: `oEGMDB6pOP2S6OwRR4PdVv610zrjnA3Bh+JnSG12fYJlBKjtNAoEb5fSUoCOOINlH96I2fU38/A2UpRKs67xYQ==`
- sortablejs 1.15.7: `Kk8wLQPlS+yi1ZEf48a4+fzHa4yxjC30M/Sr2AnQu+f/MPwvvX9XjZ6OWejiz8crBsLwSq8GHqaxaET7u6ux0A==`

## Licence obligations

ECharts (Apache-2.0):

- Redistribute `LICENSE` and `NOTICE`, and also the zrender and d3 licences.
- Do not change the file. If you change it, say so.
- Do not use the Apache trademark.

SortableJS (MIT):

- Keep `LICENSE` with the file.

## Why these choices

- **Full ECharts** and not `echarts.simple.min.js` (500 KB): the simple version has no tooltip, no legend and no
  title. A custom build (about 450 KB) needs a Node toolchain to maintain it. This option is ruled out, because IT
  does not develop.
- **Canvas** rendering for ECharts, for direct PNG export.
- **SortableJS** and not the native drag and drop of the browser. The Visualisation needs these things:
  - Clone a KPI from the list into the view, without removing the original
  - Drag with a finger (tablet)
  - Nested lists with handles

  SortableJS is configured without animation (`animation: 0`, see `DESIGN.md`) and with `delayOnTouchOnly`.

## Update a library

Prerequisites:

- The person who develops does this update, never IT.
- Work in a new, empty temporary folder, never in the repository.

To update a library:

1. Download and extract the packages. `npm pack` checks the sha512 integrity:

   ```bash
   mkdir -p /tmp/biblio && cd /tmp/biblio
   npm pack echarts@<version> zrender@<version> sortablejs@<version>   # npm checks the sha512 integrity
   for f in *.tgz; do mkdir -p "${f%.tgz}" && tar -xzf "$f" -C "${f%.tgz}"; done
   ```

2. Copy the same files, licences included, into a **new folder** `static/vendor/<name>-<version>/`.
3. Delete the old folder.
4. Change the address in the Visualisation templates (`collecte/templates/collecte/visualisation/page.html`).
5. Change the checksums in `collecte/test_bibliotheques.py` and on this page.
6. Run `python3 manage.py test`. All tests pass.
7. Run the browser acceptance check (`qa/browser_check.py`). Check the charts, the PNG export, the drag and drop,
   and the phone display.
