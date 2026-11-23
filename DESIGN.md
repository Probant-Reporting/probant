---
name: Probant
description: KPI collection as clear as good signage, in each client's colours.
colors:
  client-principale: "#1F5FAD"
  client-principale-survol: "#4375B1"
  client-principale-teinte: "#E6EDF6"
  principale-texte: "#1F5FAD"
  principale-bord: "#1F5FAD"
  sur-principale: "#FFFFFF"
  client-fond: "#F2F4F7"
  client-surface: "#FCFCFD"
  entete-table: "#F8F9FB"
  client-texte: "#1E2A38"
  texte-doux: "#5C656E"
  filet: "#DFE2E6"
  contour: "#848A91"
  neutre: "#E3E6EA"
  bandeau: "#1F5FAD"
  sur-bandeau: "#FFFFFF"
  etat-valide-texte: "#0B6644"
  etat-valide-fond: "#D7F3E6"
  barre-valide: "#2E9E68"
  etat-brouillon-texte: "#6A5A00"
  etat-brouillon-fond: "#FFF5C2"
  barre-brouillon: "#E3B530"
  avertissement: "#A86F00"
  avertissement-fond: "#FFF1D6"
  avertissement-bord: "#E8C98A"
  avertissement-texte: "#7A4F00"
  info-fond: "#E2E9FD"
  info-texte: "#2B4596"
  erreur: "#D92D20"
  erreur-texte: "#9B1C1C"
  erreur-teinte: "#FDECEC"
typography:
  display:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "32px"
    fontWeight: 700
    lineHeight: 1.1
    fontFeature: "tnum"
  headline:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1.25
  title:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 700
    lineHeight: 1.25
  body:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "15.5px"
    fontWeight: 400
    lineHeight: 1.45
  value:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "15.5px"
    fontWeight: 700
    lineHeight: 1.3
    fontFeature: "tnum"
  label:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    lineHeight: 1.3
  mini:
    fontFamily: "Source Sans 3, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.3
rounded:
  fin: "2px"
  sm: "4px"
  md: "6px"
  full: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  bandeau:
    backgroundColor: "{colors.bandeau}"
    textColor: "{colors.sur-bandeau}"
    height: "64px"
  onglet-actif:
    backgroundColor: "{colors.sur-bandeau}"
    textColor: "{colors.client-principale}"
    rounded: "{rounded.sm}"
    padding: "8px 14px"
  button-primary:
    backgroundColor: "{colors.client-principale}"
    textColor: "{colors.sur-principale}"
    rounded: "{rounded.sm}"
    padding: "7px 14px"
  button-primary-hover:
    backgroundColor: "{colors.client-principale-survol}"
    textColor: "{colors.sur-principale}"
  button-secondary:
    backgroundColor: "{colors.client-surface}"
    textColor: "{colors.client-texte}"
    rounded: "{rounded.sm}"
    padding: "7px 14px"
  input:
    backgroundColor: "{colors.client-surface}"
    textColor: "{colors.client-texte}"
    rounded: "{rounded.sm}"
    padding: "7px 10px"
  card:
    backgroundColor: "{colors.client-surface}"
    rounded: "{rounded.md}"
    padding: "16px 20px"
  statut-valide:
    backgroundColor: "{colors.etat-valide-fond}"
    textColor: "{colors.etat-valide-texte}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "2px 9px 2px 7px"
  statut-brouillon:
    backgroundColor: "{colors.etat-brouillon-fond}"
    textColor: "{colors.etat-brouillon-texte}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "2px 9px 2px 7px"
  statut-a-saisir:
    backgroundColor: "{colors.neutre}"
    textColor: "{colors.texte-doux}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "2px 9px 2px 7px"
  a-traiter:
    backgroundColor: "{colors.client-surface}"
    textColor: "{colors.client-texte}"
    rounded: "{rounded.md}"
    padding: "16px 20px"
  encart-avertissement:
    backgroundColor: "{colors.avertissement-fond}"
    textColor: "{colors.avertissement-texte}"
    rounded: "{rounded.md}"
    padding: "10px 14px 10px 42px"
  button-compact:
    rounded: "{rounded.sm}"
    padding: "4px 10px"
---

# Design System: Probant

## Overview

**Creative North Star: "Clear signage"**

The tool reads like a well-designed railway station: you know where you are, what is left to do and the status of each
value, without thinking. Clarity is the signature. There is no graphic universe to impose: the identity lies in the
typography, the hierarchy and states that are always readable, and it takes on each client's colours (Administration ›
Settings › Identity).

The density is that of a work tool: tables, figures aligned in columns, rows tall enough for the finger and the eye.
The contributor who comes three times a year must understand everything at first glance; the admin who comes every
day must never have to wait.

Everything is kept in a single stylesheet, `static/css/outil.css`, as named rules. The font is served by the tool
(`static/polices`). The installation's colours, and the ones derived from them to stay readable, are computed in
`parametres/couleurs.py` and injected by `templates/base.html`. The colour values above are those of the default
palette (Ocean).

Explicitly ruled out (first round of directions, October 2026): assertive identities (library universe, school
universe), gradients, emoji, icon tiles, letter-spaced capitals, pink used for everything.

**Key Characteristics:**
- Solid header bar in the client's primary colour, white text, white active tab; automatic light version if white is not readable on it.
- A single font, Source Sans 3, with tabular figures wherever there are numbers.
- States encoded three times: shape, word, colour (● validated, ◐ draft, ○ to fill in), including in counters and legends.
- Discreet corners: 4 px for controls, 6 px for cards.
- Flat: hairlines; a shadow only for what floats (menus, lists, panel).
- Icons drawn with a single stroke (Lucide set), never a symbol or emoji.

## Colors

The palette is the client's; the tool derives from it what it needs to stay readable, and only adds colours that carry a meaning.

### Primary
- **Client primary colour**: header bar, primary button, active tab. Set by the client (4 base colours).
- **Primary as text**: the same colour, darkened just enough for 4.5:1 when it is used as text (links, active tab, link-style actions).
- **Primary as outline**: the same colour, brought to 3:1 for the borders, rings and underlines of active elements.
- **Text on primary**: white if white is readable on it (4.5:1), otherwise the client's text colour, otherwise black.

### Tertiary
- **Validated green**, **draft yellow** (text, pale background, bar): the two states of an entry.
- **Warning orange** (icon at 3:1, background, border, text; `--orange…` variables): consistency alerts
  ("To check" badge, "To be handled" status), variance vs N-1 beyond the threshold (to be explained, same colour as its
  badge), the question asked before losing an entry or an unsaved explanation (entry panel), and the warning about a
  missing setting that prevents an action (callout at the top of the page, short note, "warning" message).
- **Information blue** (background, text; `--bleu3`, `--bleu-texte` variables): break-in-series variances, validator role, information callouts.
- **Error red** (stroke, text, background): errors, blocks (blocking rule, rejected entry), deletion zone.

### Neutral
- **Client background**, **surface** (lightened background) and **table header** (lighter still): the three planes of the page.
- **Client text** and **soft text** (recomputed for 4.5:1 on all light backgrounds).
- **Hairline**: separations between rows and cards.
- **Outline**: border of fields and secondary buttons, at least 3:1 against the background and the surface.
- **Neutral**: "to fill in" state, tracks of the progress bars.

### Named Rules
**The Client Palette Rule.** Every brand colour comes from the installation's settings. No colour is written in a
template or a `style=`; only computed values remain there (widths, indents, data colours).

**The Meaning-Only Rule.** The product only brings colours that carry a meaning: green for validated, yellow for
draft, grey for to fill in, orange for an alert or a warning (value to check, variance to explain, entry that would be
lost), red for an error or for what blocks. Never a decorative colour. The default colours of the entry types stay
outside these state colours.

**The Readable-Brand Rule.** The tool checks and adapts by itself: button text, header bar, links, outlines. The
Identity page shows these checks and explains each adjustment (light header bar, darkened primary). The page has no side
column: a small simulator in "Your organisation" shows where each text goes (header bar, sign-in
page) instead of help sentences; palettes, base colours and the light and dark previews share one block; the contrast
rows sit in a collapsed panel whose summary shows a pass count per appearance and which opens when a check fails.

### Dark appearance
- **Follows the system** (`prefers-color-scheme: dark`). Each person can force it in My account › Appearance:
  Automatic, Light or Dark (three buttons, applied at once). The choice belongs to the device: a cookie, nothing in
  the database, so it also works for read-only accounts and on the sign-in page.
- **Derived from the client's palette** (`parametres/couleurs.py`, `gamme_sombre`): backgrounds near black with a
  faint tint of the client's text and primary colours; light text; primary lightened only as much as needed for 4.5:1
  as text and 3:1 as an outline; buttons keep the client's colour when white text stays readable on it. State colours
  (green, yellow, orange, blue, red), level, entry type and framework labels get dark pale backgrounds and light text.
  Chart series are lightened to 3:1 on dark cards.
- **Same checks**: the Identity page shows a dark preview and the same contrast rows for the dark appearance.
- **Header bar**: dark (the surface), with the primary colour as the 4 px top line and the active tab on its tint.
  The logo keeps a light square (softened).
- **Stays light**: printing, exported PNG images (the Visualisation redraws its charts in light for printing), Excel
  files. The error pages 400 to 503 follow the system with the default palette.

## Typography

**Body Font:** Source Sans 3 (with system-ui, sans-serif), served by the tool in 400, 600, 700 and 400 italic,
Latin and Latin Extended subsets (OFL licence in `static/polices`).

**Character:** A signage humanist, open and readable at small sizes, with equal-width figures: columns of numbers
line up by themselves.

### Hierarchy
- **Display** (700, 32px, 1.1): key figures on the dashboard.
- **Headline** (700, 24px, 1.25): page title.
- **Title** (700, 17px): titles of cards and collapsible sections.
- **Body** (400, 15.5px, 1.45): running text, cells, fields, buttons (600 for buttons, tabs and KPI names).
- **Value** (700, 15.5px): value for the period in the table; 24px in the entry panel.
- **Label** (700, 13px): column headers, status labels.
- **Mini** (400, 12px): notes, years, codes. Nothing smaller.

### Named Rules
**The Tabular Rule.** Every number that gets compared (values, N-1, variances, rates, counters) is displayed in tabular figures.

**The No-Shouting Rule.** No letter-spaced capitals, no text under 12px, no gradient.

## Layout

Centred content, 1400 px at most, 24 px margins (16 px under 1100 px, phone included; header bar too). 64 px header bar on desktop; under 800 px,
it switches to two rows (brand and account, then tabs that scroll horizontally, with a fade to indicate it).
Tables: cells with 11 × 10 px inner padding; secondary columns are hidden depending on the width (1100,
800 and 560 px). The N-1 column directly follows the value for the period, on the table header background. Under 560 px,
the entry panel actions stack up ("Validate" first, full width) and the page title wraps onto two
lines. No page scrolls horizontally at 768 or at 390 px (checked by the acceptance tests): a grid reduced to one
column is written `minmax(0, 1fr)`, and two action links on the same row ("Download", "Restore…") share
a cell, side by side, then one under the other when space runs out. A hidden column keeps no width
(neither its own nor that of its labels). Rhythm: 4, 8, 12, 16, 24 px.

**Touch targets** (replaces the spacing exception). Every clickable target (link, button, check box,
radio button, summary) has a **clickable area of at least 24 × 24 px, on every screen**. The area is what counts, not the
drawing: a check box or radio button takes the area of its label (`label` at least 24 px tall), and in the entry grid the
area of its cell (`td.choix`, a click on it ticks the box; the header cell does the same); the drawn box may stay smaller
than 24 px. A check box without a visible label (the Attributions grid) is drawn at 24 px. An unclassed link gets 5 px of
vertical padding (`a:where(:not([class]))`: it widens the area of an inline link without moving anything), a list or
table link or a summary gets `min-height: 24px`. Links inside a sentence are exempt (WCAG 2.5.8). Touch screens and phones
keep their 44 px (`@media (pointer: coarse), (max-width: 560px)`): the 24 px rules are written with `:where()` or in the
base rule of the component, so they never override the 44 px. A new component with a smaller link, button or box adds its
selector to the block "CIBLES TACTILES", the last of `outil.css`. `collecte/test_navigateur_cibles_tactiles.py` measures
29 pages at 1,440 and 390 px and fails under 24 px.

**Table answers on a phone**. Up to 560 px, a table answer (and any Markdown table of a written answer) shows
each row as a card: one cell per line, the column label in front (`data-label`, drawn by `::before`), never a table that
scrolls sideways. The ARIA roles `table`, `row` and `cell` are written in the template so that the announcement stays.

## Elevation & Depth

Flat. Depth comes from the three colour planes (background, surface, table header) and from 1 px hairlines. Cards
have no shadow; what passes above the page has one.

### Shadow Vocabulary
- **Floating** (`box-shadow: 0 8px 24px rgba(20, 24, 32, .14)`): menus, drop-down lists, tooltips, bulk action bar.
- **Panel** (`box-shadow: -8px 0 24px rgba(0, 0, 0, .12)`): side entry panel, only when open (hidden and inactive once closed).
- **Light** (`box-shadow: 0 1px 2px rgba(20, 24, 32, .12)`): active segment of a selector, knob of a toggle switch.
- **Veil** (`rgba(20, 24, 32, .32)`): darkened background behind the panel and loading waits.

### Named Rules
**The Flat Rule.** A card stands out by its border, never by a shadow or by a colour band on one side.

## Shapes

Discreet, regular corners: 2 px for thin bars, 4 px for buttons, fields, labels, tabs and
counters; 6 px for cards, sections and panels; circle for avatars and status dots. 1 px
borders; only the panel's value field takes a 2 px border, in the text colour.

## Components

### Buttons
- **Shape:** 4px corners, on every button (tree "add" buttons, SPOC cell, theme choice included).
- **Two sizes only**: normal (padding 7 × 14 px) and **compact** (`.compact`, padding 4 × 10 px, 13 px text) for
  tables, toolbars and list rows. No large button: "Save" has the same size on every page (`gros-bouton` is gone); the
  full-width sign-in button and the danger button keep the normal size.
- **One height per type and size** (`--haut-champ` 40 px, 44 px on phones; `--haut-compact` 30 px): fields, lists, time and
  date fields, the grey pill (`.segments`) and normal buttons share the first; compact buttons and fields share the
  second. A rule that sets its own height for a field or a button is a defect.
- **Pressed:** a primary button is darker than at rest (not the hover tint); the danger button likewise.
- **Danger:** an irreversible action (close a campaign for good, delete an account, restore a backup) is a danger
  button (`bouton-danger`, or `secondaire danger`, or `lien lien-danger` in a row); its confirmation window takes
  the same style (the script copies it from the button).
- **Primary:** client primary colour, "on primary" text, weight 600, padding 7 × 14 px. Only one per area.
- **Hover / Focus:** client hover tint; 2 px focus ring (primary as text), offset by 2 px.
- **Secondary:** surface, client text, outline border.
- **Action link** ("Reopen the entry"): primary as text, underlined, no frame.
- **Create**: the main creation of a page is always a primary button at the top right, with the drawn "plus"
  icon (`{% icone "plus" %}`), never the "+" character and never a plain link ("New account", "New export", "New view",
  "Add a framework", "Add a language", "New campaign", "New rule", "New KPI", "New space", "Create a list"). Bulk
  creation ("Several accounts", "Several organisations") is a secondary button next to it, same icon. In a list row of
  the Administration overview, "Add a framework" is the same button in compact size. The dashed button stays reserved
  for adding inside a tree ("+ Country", "+ Theme", "+ KPI"). "Add a language" opens its two fields under the button.
- **Row action** (`.lien-action`): an underlined link in body size, in the last column (`td.action-ligne`, right-aligned);
  the base rule is underlined, no page re-underlines it ("Manage" in Campaigns looks like "Edit" everywhere else). One
  main action per row; rare actions go in a "…" menu, deletion last. The framework card (`.actions-carte-ref`, review of
  09/11) keeps its own list of actions.
- **Delete or remove**: a **bin** icon button deletes an object (saved export, KPI list, evidence, data
  migration profile; `aria-label` names the object); a drawn **cross** (`{% icone "x" %}`) removes an item from a
  selection (alias, formula token, filter, KPI of a visual), never the "×" character; the word "Delete" in red is only
  used inside a deletion zone (`.zone-suppression`, `.zone-danger`) or as the last item of a menu.

### Save bar
- **One bar ends every form** (`.barre-enregistrement`): primary button on the left, "Cancel" next (a secondary button,
  never a bare link), status message on the right (`.etat-barre`: "3 changes not saved", "Tick at least one KPI").
- **Sticky when the form is longer than the screen** (`.barre-enregistrement.collante`): the bar stays at the bottom of
  the screen while the form goes on below, and takes its place at the end of the form. One dress in every page:
  surface, hairline, card corners, padding 10 × 14 px. Used by the KPI sheet, account, organisation, campaign, rule,
  Identity, Languages, Translations, Units, tree levels, thresholds, "New export", KPI lists, import previews and the
  installation of a framework ("Continue" or "Install" first, then "Back", then "Cancel").
- **Under the fields for a form of one to three fields** (no modifier): My account, password, "Replace a person",
  duplicate a framework, automatic backups, deletion delay, new space. Never a button on the same row as the fields.
- Never a new form footer (`pied-export`, `pied-collant`, `pied-apercu`, `pied-reprise`, `pied-cocher`,
  `actions-formulaire`… are gone). Exceptions: the entry panel ("Validate" / "Save the draft", see "Unsaved entry"),
  the confirmation window and the windows of the Visualisation (buttons on the right, as in every dialog), and the
  editing bar of a view.

### Choosing an option
- **Two shapes.** The **pill** for a short choice (`.puce`: "All my KPIs", format, period; `.puce-reponse` is its large
  size for Yes / No in the entry panel; `.puce-catalogue`, `.choix-forme`). The **card** for a choice that needs a
  sentence (`.carte-choix`, `.carte-role`, `.palette-choix`, `.modele-niveaux`; `.choix-ligne` when the cards form a
  framed list, as in the KPI sheet).
- **One way to show the chosen option**: border in the primary colour (thickened by an inner hairline, so nothing
  moves) and a **solid tinted background** (`--principale-teinte`). Never a pale background that merges with the page
  (the chosen card must not look "transparent"), never the full primary colour (it stays for the action), no halo.
  One grouped rule in `outil.css` ("CHOIX D'UNE OPTION") carries it: a new choice component is added to that rule.
- Exception: the level buttons (`.niveau-radio`) keep the colour of the level, set in the tool.

### Switch or checkbox
- **Switch** (`.interrupteur`, or `button.bascule-statut` with the same 40 × 22 px slider): only when the setting
  applies at once (pause a rule in the list; N/A in the entry panel, which changes the form at once).
- **Checkbox** (`label.case-option`: box, title in bold, help sentence): in every form that has a "Save" button
  (KPI sheet, account, organisation, rule, framework settings, automatic backup, "Replace a person").

### Frameworks page
- **Your frameworks**: compact rows (`.lignes-referentiels`): colour dot and name (link to the content), figures in soft
  text, one status label, "Settings", then the "…" menu for the rare actions. No large cards with repeated actions.
- **Library**: a tinted block under the list, visible without a click. Sets are grouped by subject (small soft
  heading); groups follow each other on the same row while there is room. A discreet search field sits on the right
  of the block title. Each card ends with its state on the left and one action on the right.
- **Your own framework**: a dashed block at the end of the library, one secondary button and one link.

### Calculations in plain words
- A calculated KPI shows its calculation under its name: `.calcul-clair`, small soft text, an accent-coloured "=" in
  front, KPI names instead of codes, two lines at most (the tooltip has the whole text). Same rule in the catalogue,
  the content of a framework and the page of a library set. Never a list of codes ("Calculated from: A, B").
- In the catalogue, the chips "Calculated with" and "Used to calculate" open the one menu of the tool with the linked
  KPIs (code chip and name); a click opens the KPI sheet in the side panel.

### Menus
- **One menu**: `details.menu-deroulant` > `summary` + `.menu-liste`, the "…" menu of the Visualisation (surface,
  hairline, card corners, floating shadow, 4 px padding, rows of 32 px, 44 px on phones; Escape and a click outside
  close it and give the focus back to the button that opened it, arrows move in it). A "…" button alone is a `.bouton-menu`. A setting inside a menu is a `label` (caption
  above its control). An unavailable action stays readable, greyed. "Delete" comes last, in red, with the bin.
  The theme menu of a framework uses it (`.menu-theme-liste` is gone).
- Not menus: the header bar selectors (campaign, space, language: context pickers) and the organisation selector.

### Chips
- **One shape for every label**: 12 px, weight 600, 4 px corners, padding 2 × 8 px, no border. One rule in
  `outil.css` ("ÉTIQUETTES") carries the shape; every label class only adds its tint. Seven tints: neutral, green, yellow,
  orange, red, blue, accent (`.e-neutre` … `.e-accent` for a new label: `<span class="etiquette e-bleu">`). Three uses:
  - **Status**: its shape, a word, a tint (● ◐ ○ for a value; `.etat-actif` ● / `.etat-inactif` ○ for "Active" and
    "Inactive", written the same way in Accounts, Organisations, Spaces, frameworks and KPI sheets).
  - **Category**: role, level, KPI type, origin, "Shared". Role tints are kept (administrator on the
    primary colour, validator blue, contributor green, reader neutral, auditor accent). Colours set in the tool (tree
    levels, entry types, frameworks) keep their colour: only the shape is shared.
  - **Code**: fixed-width font, inset hairline (`.id-chip`, `.code-langue`).
  Never a new size, corner, padding or border for a label. Exception: the large status at the top of the entry panel.
- **State:** ● full = validated; ◐ half = draft; ○ empty = to fill in; filled square = error. The shape alone is enough.
- **Legend dots and counters**: same shapes, without the background.
- **Campaign status** (`_statut_campagne.html`, `.statut-campagne`): never the ● ◐ ○ dots used for values.
  Label shape; icon + word: pencil and information blue background for "Open for data entry", neutral pencil for "Review",
  neutral padlock for "Closed", word alone for "In preparation". Same icon in the "I answer for" button.
- **Period label** (header of the Value column): neutral, like the N-1 label; the primary colour stays reserved
  for the action and for where you are.
- **Cell without a SPOC** (assignment grid) and **"No SPOC"** everywhere: warning orange, never red.
- **"Enter"** (value still empty in the entry list): dotted frame in outline colour, word in primary as text,
  13 px 600; it is a block (`inline-block`) so that its frame never covers the unit written below it on a phone.
- **Counter label** (Dashboard): icon or dot facing the first line of the label, even
  when it wraps onto two lines (phone, Spanish).

### Cards / Containers
- **Corner Style:** 6px.
- **Background:** client surface.
- **Shadow Strategy:** none (see Elevation & Depth).
- **Border:** 1 px hairline.
- **Internal Padding: two values only**: 16 × 20 px for a card (`--marge-carte`: `.carte`,
  `section.bloc`, side panel page, dialog) and 12 × 14 px for a compact block (`--marge-bloc`: a card inside a card, a
  tile, a choice card, an inset). A new container uses one of the two variables, never its own padding.
- **Tables: one dress**: the framed table (hairline, card corners, header on the header background).
  **One column header everywhere**: the header of the Data entry grid, pale tint of the
  installation's colour (`--principale-pale`) with a 2 px rule (`--principale-claire`), on every table, the scrolling
  grids and the History list. `--entete-table` (neutral) stays for sub-title rows and neutral blocks.
  `.carte-table` for a new table; the Dashboard, Reminders and Forced values tables (`.tdb`) and the Hosting tables
  (`.table-mep`) take the same frame, so a table is never bare on the page nor unframed inside a card. Grids that
  scroll (Data entry, Consolidation, KPI assignments) carry the frame on their scrolling wrapper. **Column headings
  are 13 px everywhere** (Accounts, Organisations, Consistency and KPI assignments no longer use 12 px).

### Inputs / Fields
- **Style:** surface, outline border (3:1), 4px corners, padding 7 × 10 px, text at 15.5px.
- **Focus:** 2 px ring (primary as text); text cursor in the same colour.
- **Error / Disabled:** border and message in error red under the field; disabled at 45 % opacity.
- **Search in a list**: every `input[type=search]` shows the magnifier (drawn in the field background by the
  stylesheet, no markup needed), comes first in its toolbar and has the height of the lists next to it.
- **Drop-down list**: every `select` shows the thin chevron of the menus (`--svg-chevron-liste`, drawn in
  the background like the magnifier), not the browser arrow. Forced colours: the browser arrow comes back.
- **Check box in a toolbar or a display menu**: 18 px, like the boxes of the forms (22 px on touch screens).
- **Row of controls** (Visualisation filters, toolbar): lists and buttons side by side have the
  same height (40 px on large screens, 44 px on phones) and align on their bottom edge; a `details` drop-down menu
  placed in the row adds no gap under its button.

### Entry panel on a small screen
- Under 560 px the row of actions ("Save the draft", "Validate") stays stuck to the bottom of the panel, so the main
  action is reachable without scrolling. The order on screen is the order of the code (and of Tab): no `order`,
  no reversed column, no positive `tabindex`.

### Filters
One model for every page that filters a list (Data entry, For me, Consistency, KPI catalogue, KPI assignments,
Organisations, Accounts, History). Markup: `.barre-filtres`; script: `initChampsFiltre` in `_app/05_filtres.js`.
- **Order, always the same**: search first, then the filter fields, then on the right (`.filtres-droite`) the
  "Display" menu and the actions of the page. Search is 320 px wide on every page.
- **A filter field** (`.champ-filtre` > `label` + `select[data-panneau-filtre]`): its name above it, always visible.
  The script replaces the list by a button (`.liste-filtre`) that opens a panel (`.panneau-filtre`): a search field
  from 9 choices, check boxes (`data-multiple`: several values at once, "Select all") or a single choice, and **the
  number of rows of each choice** (`option[data-nb]`). Without JavaScript the browser list stays.
- **Active filter**: the field is framed and tinted in the primary colour; with several values it shows the first one
  and "+1". Never the same look as a field left on "All".
- **Applied at once**: a choice filters the page as soon as it is ticked. When the server filters (Consistency,
  History; `data-envoyer`), the form is sent when the panel closes, or with "Apply".
- **Under the bar** (`.etat-filtres`, only when a filter is active): the number of results ("37 results of 1,823")
  and "Clear filters".
- **Filter or display option**: a filter narrows the list and lives in the bar; an option that changes how rows are
  shown (codes, calculated KPIs) lives in the "Display" menu (`details.menu-affichage`, check boxes `label.case-menu`).
  The grey pill (`.segments`) stays for a display switch (organisation tree, row order), never for a filter with figures.
- **The clickable legend of Data entry** (statuses, `.legende-filtre`) stays: it is the progress of the page and a
  filter at once; it adds up with the bar and "Clear filters" resets it too.
- **Keyboard and screen readers**: the button carries the field name and its value; Down arrow opens; arrows move
  between choices; Escape closes and gives the focus back; the count under the bar is a `role="status"` (except
  where the page already announces "12 KPIs displayed").
- **Phones**: search on the full width, fields two by two, the panel is a sheet at the bottom of the screen, rows of 44 px.
- The Visualisation keeps its own view filters (same look: name above each list). The Consolidation keeps its check
  boxes visible in their card: they change the figures shown ("Include drafts"), they are not display options.

### Navigation
- **Header bar**: primary colour, 64 px, brand on the left (initials on a white square, name 17px 700, subtitle 13px), account on the right.
- **Header bar selectors** (on the right, in this order): campaign, **space** (only from two accessible spaces
  upwards), language, account, sign-out. Campaign and space are context selectors: light bordered boxes,
  same height (38 px on large screens); language, account and sign-out stay on the header bar. Chevron flipped when the
  menu is open; 44 px touch target on phones. In their panels (light surface), the focus ring
  uses primary as text: the header bar's white would be invisible there. Under 480 px, the space selector takes the
  remaining room (44 to 150 px, name cut with "…") so that the row fits on the screen; at 320 px, sign-out
  wraps onto the next line rather than being cut.
- **Light header bar** (colour too light for white): surface, 4 px hairline in the primary colour, client text, tinted active tab.
- **Page introduction**: title, actions on the right, tabs, then **one sentence in body size** under the
  tabs (`.intro-page`: soft text, 80 characters per line at most). Never inside a card, never in small print under the
  title. **Only when it adds understanding**: a sentence that repeats what the screen already shows (the
  names of the tabs, the columns, the buttons) is removed. A long explanation read once (how to assign KPIs, how the
  organisation tree works) is folded behind a question (`details.aide-repliable.aide-page`), so the list moves up.
- **Main action of a page**: at the right end of the first row under the tabs. That row is the filter bar
  when the page has one (Accounts, Organisations, KPI catalogue, KPI assignments, History), else the title row. One style replaces `intro-rubrique`, `chapeau-installation`, `chapeau-donnees`, `intro-espaces` and the small
  subtitle of the Administration (now shown once, on the overview). A link back to the list above a detail page is a
  `.retour-page`.
- **Tabs**: text 600; darkened on hover; active on a white background, text in primary colour 700.
- **Tabs and switches: two appearances only**.
  - **Underlined tab** (`.sous-onglets`): to change page or section. Links with `aria-current="page"` (Administration,
    Import / Export, For me, Dashboard: Progress / Consolidation, the views of the Visualisation) or `role="tab"` buttons with
    `aria-selected` (Dashboard: Organisations, SPOC, Themes). 2 px underline (primary as outline) and primary text on
    the active one. `.petits` for a third level (Settings pages, pages of a framework, Translations sections).
  - **Grey pill with a white choice** (`.segments`): to change the display of the same list (organisation tree, row
    order, Appearance, translation language). Buttons with `aria-pressed`, links with `aria-current`, or radio inputs
    in labels. Never the primary colour: it stays for the action. The solid-colour switch (`.bascule-segments`) and
    the card-tabs are gone. Now a filter is never a pill: it is a filter field (see "Filters").
  - **Two levels of tabs at most**: what would be a third row and filters the same list is a filter field
    (the framework of the KPI catalogue, the two logs of the History).
  - Exception: the level cards of the KPI assignments (reviewed: they carry each level's progress). The
    "folder" tabs of the Visualisation are gone: its views are underlined tabs.
- **Compact menu** (phones, under 560 px): the Administration sections and the Settings pages fold behind one full-width
  secondary button "Section: Accounts" / "Page: Identity" with a chevron (disclosure button, `aria-expanded`, Escape
  closes and gives the focus back). It opens the same links as a list of 44 px rows, the current one in primary text on
  a pale background. Without JavaScript, the tabs stay shown. The three Frameworks sub-tabs stay as tabs.
- **Icon tabs** (Import / Export, Administration): label visible on large screens (1,440 px included); under
  1,440 px the icon alone for non-active tabs, under 1,340 px for the active one too (tooltip and accessible name kept).
  The account name is hidden under 1,600 px. Above 800 px, tabs are never cut: when they still overflow
  (long tool name, wide campaign choice, tablet), the script removes, in this order, the account name, the
  non-active labels, then the active one's, and as a last resort moves the tabs onto their own row,
  as under 800 px, where they get their labels back (`serrerOnglets`, classes `bandeau-serre`, `onglets-serres`,
  `onglets-tres-serres`, `onglets-a-la-ligne`). Under 800 px, they scroll with a fade; the tab of the current
  page is brought to the middle of the visible part on load (`montrerOngletActif`), and the fade disappears at the end
  of the bar (class `au-bout`).
- **Brand**: tool name and subtitle on one line each, cut with "…" beyond 360 px (300 under 1,440 px,
  220 under 1,340, 180 under 560); the full name stays in the tooltip and for screen readers.
- **Skip to content**: first link of the header bar, off screen until it has focus; it then appears at the
  top left (surface, 2 px border and text in primary as text) and leads to the content (`main#contenu`, focus without a ring).
  On Data entry and For me, a second link, "Skip to KPIs", leads to the list (`#liste`): the first row
  is then two tabs away (summary of the section, then the row).
- **Section headings**: the name of a collapsible section is a real heading (h2, h3 under a framework's title)
  inside its summary, styled like the summary (Title); screen readers find it in the list of headings.
- **Filter chips** (the clickable legend of Data entry): toggle buttons (`aria-pressed`, named group); the number of
  rows displayed is announced ("12 KPIs displayed") when the person filters, never after a save (area outside the
  re-read banner).
- **Empty page, empty block** (`_vide.html`): a whole page with nothing to show gets the centred state in
  a card (`.page-vide`: icon, title, one sentence that explains, a button to go on) and no filter bar above it; an
  empty block inside a page that shows other things gets the same elements on one line (`.page-vide.compact`). "No
  result" of a filter stays a plain soft sentence (`.etat-vide`).

### Icons
- Drawn set, stroke of 2, in the text colour: `{% icone "nom" %}` tag (close, tick, alert, paperclip,
  download, send, padlock, pencil, chevrons, external link). The markers of collapsible sections and contrast
  checks use the same paths in CSS (masks). The ▲ ▼ arrows of N-1 variances are data marks.

### Callouts (messages in the page)
One component, four tints: `{% encart "avertissement" %}…{% endencart %}` (classes `encart encart-<tint>`).
- **Tints:** information blue (`info`), warning orange (`avertissement`), error red (`erreur`: error or block), success
  green (`succes`). Yellow stays reserved for the draft state: no yellow callout.
- **Always an icon, then a first sentence in bold.** The icon comes from the stylesheet (mask on `::before`: circled "i",
  triangle, circled "!", circled tick), so a script that rewrites the text keeps it. The tag puts the first sentence in
  `<strong class="encart-titre">` (its own line); a one-sentence message is bold as a whole. Longer content: a first
  `<p class="encart-titre">`, then paragraphs or a list.
- **Shape:** 6 px corners, padding 10 × 14 px (42 px on the icon side), body text; orange and red have a 1 px border.
  `compact=True` (13 px text, title inline) inside an already dense block: import preview, status list, panel.
- **Same look for the messages at the top of the page** (`.messages`, sign-in page): same tints, icon and bold first sentence.
- Options of the tag: `role`, `id`, `classe`, `balise="li"`, any HTML attribute (`hidden=condition`, `data_x=True`).
  Former styles removed: `.alerte`, `.alerte.erreur`, `.succes`, `.encart-au-dessus`, `.encart-avertissement-court`,
  `.alerte-comptage`, `.bandeau-traduction` (the "Translate all languages at once" block of Languages is an ordinary card).

### What is left to do (banners, summary, action lists)
Every work page starts with what is left to do, in one sentence, with a single primary action.
- **"To do" banner** (Data entry, For me): one sentence at 17px, figures in 700, a single primary action on the right
  (full width on phones). It covers the person's whole scope in the campaign (values and alerts to
  justify), same calculation as For me and "I answer for"; on Data entry, the sentence starts with the organisation displayed
  (name in 600). Six states:
  - **still to do here**: "Lyon: N to fill in · M drafts to validate · K alerts to justify · data entry ends on …",
    "Start" / "Continue" button, and below it, as help (soft text), "Elsewhere: N values in M organisations"
    (no "Go to …" link: the organisation selector is enough);
  - **alerts here**: "Lyon: everything is entered · N consistency alerts to justify", "Justify" button; the help and
    the "Elsewhere: …" line are two separate lines;
  - **done here, still to do elsewhere**: "Lyon: nothing left to do here. N values left in M organisations", button
    "Go to <organisation>" (the first one in the tree where values remain, otherwise alerts);
  - **alerts elsewhere**: same form, "N alerts left to justify in M organisations";
  - **all done** (pale green background, tick in a green circle) only when the whole scope is finished; on Data entry,
    the sentence says that it covers all the organisations ("… out of 14 in your 3 organisations");
  - **data entry closed** (campaign in review, closed or end date passed): padlock in soft text, "Data entry closed: N
    values not validated · K alerts to justify" ("all values are validated", or "nothing to fill in here"
    when the organisation has no cell), without "Go to"; "Justify" button only if an alert remains
    (justification is still possible). For the administrator, the sentence starts with the organisation displayed.
  In the "done here" and "alerts elsewhere" states, only the organisation name is in 600.
  For the administrator, the leading figures are those of the organisation displayed and the rest goes into "Elsewhere".
  Each state carries its sentence in plain text (`data-annonce`), reused by the end message of "Validate and next".
- **Campaign progress status** (For me tabs, "I answer for"): a few words, the state shape and colour
  only: "N to do" (text, 600), triangle and "N alerts to justify" in warning orange, tick and
  "all done" in validated green, "nothing to fill in" in soft text, padlock and "data entry closed" in soft text (followed
  by "N not validated" and, if any remain, the alerts to justify in orange). Never the primary colour (it
  designates the action and where you are).
- **Organisation selector, one component** (`details.selecteur-org`: tree, level labels, search): Data entry,
  Consistency, For me; as a form field (`_selecteur_org_champ.html`, the `select` stays the submitted field and the
  fallback without JavaScript) in Import › file to fill in and in the **Organisation filter of the
  Visualisation** (same height as the lists next to it; a script that changes the list sends it `selecteur:maj`).
- **Organisation selector** (Data entry): for each organisation, the mini-bar and "validated / expected", then,
  if any remain, an orange badge (triangle and number) for the alerts to justify; the legend at the top of the list
  names both ("validated / expected", triangle "alerts to justify").
- **Two named rates** (Dashboard): the summary counts all cells ("Rate", "Validated", "To fill in");
  "Current campaigns" only counts mandatory items, and its headers say so under the label, in
  soft text ("Rate (mandatory)"); on phones, this detail is only read by screen readers, since the
  sentence under the card title already says it.
- **Key figures: tiles only on the Dashboard**. Four tiles at most, one model: label on top (13 px 700,
  with the state shape), figure in bold (Display), detail in soft text; orange background and alert icon for a problem;
  the whole tile is the link. Elsewhere the form follows the role of the figure:
  - **a sentence of figures** when they are a reminder (`.resume-comptes`: Accounts, Organisations);
  - **a bar and its legend** when the figures make a whole (Data entry, For me): the 8 px bar, then the legend
    (`.legende-filtre`): shape, figure in bold, underlined word; each item is a toggle button that filters the list;
  - **figures in the filter** when each figure mainly filters (Consistency checks and statuses, Accounts roles, KPI
    catalogue types, organisation levels): in the panel of the filter field, beside each choice (see "Filters");
  - **only what needs an action** (Hosting, "Installation status"): what is fine in one sentence, then one orange row per
    problem with its link.
  The import preview keeps its two result tiles (they are the answer to an action, not a page header).
- **Summary** (Dashboard): on the left the days remaining (Display, 32px), separated by a hairline; on the right the
  completion rate with its bar and a 2 px stroke in the text colour for the expected pace, then the counters
  (Label with the state shape, Display figure, aligned with each other). A delay turns warning orange
  (icon, label, figure), never red.
- **"To be handled" list** (Dashboard and Administration, one shared block:
  `collecte/templates/collecte/administration/_a_traiter.html`, topics written once in `collecte/a_traiter.py`): white card, title "To be
  handled" with its counter, one row per topic (orange alert icon, title 700 with the figure, detail in soft text),
  underlined action link on the right (below on phones). Same words in both pages: "Assign", "See and remind",
  "Hosting". On the Dashboard the secondary button "Prepare the reminder…" sits in the title row, "See and remind" shows
  the late organisations in the page, and "Assign" / "Hosting" are only given to the administrator. Administration only:
  "Nothing to handle" in green when the list is empty. No orange block any more.
- **Section rows**: name 600, figure in soft text, chevron; the whole row is the link. Descriptions
  go into collapsible help, not on the page.
- **Per-row action link** ("Remind", "Assign"): underlined link in the last column, only on the
  rows where something remains to be done.
- **Page warning callout** (e.g. Reminders without an email server; the model of every callout, see "Callouts"): at the
  top of the page, under the title, pale orange
  background, orange border, orange alert icon, first sentence in 700 saying what does not work ("nothing is sent
  from here"), then what can be done instead; `role=status`. The link to the setting is only given to whoever can
  change it (the administrator). Elsewhere, the same situation is stated by a short **orange note** (icon and word, e.g.
  "emails not enabled" next to the dashboard's secondary button "Prepare the reminder…"): never a primary
  button for an action that will not do what it announces.
- **Writing to a person** (Reminders without an email server): "Write" as the row's action link (read as "Write to
  X"), then a block with the address and the subject (each with a "Copy …" link), the message text, a primary
  button "Copy the message" and a secondary button "Open in my email app" (prepared link, only if it
  stays short). The copy is announced in the toast (`data-copier-annonce`). What is not sent by the tool never goes
  into the history.
- **New row in a history**: "just now" label in information blue, only in the display that follows
  the action.
- **Column hidden on phones that keeps its information**: the column becomes `mq-xs`, and a discreet line
  (soft text, mini size) repeats it under the name (e.g. "Last reminder: 12/10 09:00").
- **Sign-in page message** (e.g. "Restore successful"): in the card, above the fields, like the
  sign-in errors (success green or error red), and linked to the Email field (`aria-describedby`) so that it is read with it.

### Unsaved entry (entry panel)
A value, the N/A box, the comment or the written text that have been changed are saved as a draft on their own
and what cannot be saved is never lost without a question.
- **Autosaved draft**: about 2 seconds after the last keystroke or choice, when the panel closes (cross, veil, Escape,
  phone back, a link of the panel) and when the page is hidden or left (`visibilitychange`, `pagehide`, a request that
  survives the page), the entry is sent as "Save the draft" sends it (same checks, version, history), with `auto=1`:
  never validated, the panel is not redrawn, focus does not move. The History only grows (it is the audit trail): each
  autosave writes one line per field that actually changed since the saved state, nothing when nothing changed, and
  never updates or deletes a line. Not sent, and said in the marker: a **validated value** (it changes only on "Save the change",
  which makes it a draft again: the person decides, the closing question stays), an **ambiguous separator** ("1,234":
  the reading is chosen when the person saves; the question is never opened by an autosave), an entry the server has
  just **refused** as it is (not a number…), and after a **version conflict** (someone else saved the cell: only an
  explicit save replaces their value). Read-only roles and closed campaigns have no `data-auto` form, and the server
  refuses them (403).
- **Marker** (soft text, 13 px, right-aligned above the buttons, on the left on phones), `role=status`: its announced
  part changes only for a lasting state: "Draft saved at 14:32", "Not saved: <reason>" (stays until the entry changes:
  Error-Stays), "Not saved yet. A validated value changes only when you save it.", "Changes undone". The 2-second wait
  ("Not saved yet") and "Saving…" are shown only (`aria-hidden`), so that a screen reader does not speak at every pause.
- **"Undo my changes"** (link button next to the marker, 44 px tall on phones): shown once an autosave has changed the
  cell since it was opened (or since the last explicit save); it puts back the value, N/A and comment found at opening and
  saves them (new History lines: the value put back; nothing is removed), then focus goes to the value. This replaces "Close without saving"
  for an autosaved entry: closing never restores silently.
- **Closing question**: asked only for what could not be saved (validated value, refusal, ambiguous separator,
  conflict). Its "Close without saving" drops only the part that is not saved; after an autosave it says so ("The draft
  saved at 14:32 is kept.", read with the question). At the top of the panel, sticky at the top when scrolling, on a pale orange background, orange
  border, floating shadow; orange triangle and 700 title in orange text "This entry is not saved"
  (`role=alertdialog`, named by this title). Three buttons, only one primary: "Save the draft and close"
  ("Save the change and close" for a validated value, with "you will need to validate it
  again" below), then "Close without saving" and "Continue entering data" as secondary buttons. Focus goes to the first
  button and Tab stays within the question (`aria-modal`); Escape, "Continue entering data" or a click in the form
  return to the field (the rest of the panel is not inert, so that a click resumes the entry). "Continue
  entering data" is aligned to the right; under 560 px, the buttons stack, 44 px tall. Sticky at the very top of the panel
  when it scrolls, with no strip of content above it. Asked by the cross, the veil, Escape, the phone's back button and
  the panel's links; for a link, the first two buttons say "… and open the link" and "Open the link
  without saving". Never on the full page (Escape closes nothing there): leaving it sends what can be autosaved, and the
  browser warns only for the rest (validated value, refusal, a value that cannot be a number, ambiguous separator).
  **Version conflict** (someone else saved the cell in the meantime): a sentence in orange text says so
  ("saving will replace their value with yours", linked by `aria-describedby`); "Close without saving"
  comes first, as the primary button, and receives focus (Enter replaces nothing); the second button says
  "Replace with my entry and close". Once saved and closed, a brief message confirms it ("Draft
  saved.", "Change saved as a draft."). On phones, a second back during the question asks
  it again (the history entry is restored immediately).
- **Rejected entry** (value that is not a number, version conflict, validation refused): the reason is displayed
  in the "To check" box, linked by `aria-describedby` to the value and the comment, with the label "Not
  saved" when nothing is in the database ("Blocks validation" when the draft is saved but validation
  refused); the rejected value carries `aria-invalid` and an error red border (not for a version conflict: the
  value itself is correct); focus returns to the value field.
- **What "Validate" commits to**: one sentence in Mini, soft text, under the row of buttons ("Validating confirms that
  your entry is complete, and an administrator can still reopen it."), linked to the button by `aria-describedby`, with
  no tooltip (read once by screen readers, readable by touch); on phones, with the buttons stacked, it sits just under
  "Validate", before "Save the draft". The end of an import puts the same sentence ("…these values…") under "Validate
  these M values".

### Alert to check (list and entry panel)
A consistency alert is read and settled where the data is entered, without going through the Consistency page.
- **In the list**: orange badge (triangle and "To check", the number in brackets if there are several;
  red only for a blocking rule) after the KPI name, and below it the finding in plain words, in Body 13px in the
  text colour ("42 h, compared with around 3,480 h usually (median of the 5 previous reporting years): 83 times lower."); the
  row's accessible name repeats it ("to check, …"). Never only in a tooltip.
- **Finding**: the value, the reference and the variance in words; "times higher / times lower" only for a
  positive value. Variance vs N-1: "160 employees, compared with 100 employees in 2025: +60 %.", written the same way in the
  list, the panel and the Consistency page (in the panel, the variance is rounded to one decimal, like the N-1 box and the
  "Variance" column of the list). Non-annual period: "(median of the 5 previous years, same period)",
  without nested brackets. Alerts saved before this version ("20.0 × the median…", "+68 % compared
  with N-1, without comment.") are rewritten this way on display, without re-checking ("20 times higher" taken from the
  saved report; under 1, no "times lower", which rounding would make wrong). Accessible name of the row: the
  finding without its final full stop, then ": open (Enter)".
- **"To check" box** in the panel: a titled section (h3); first the reasons (rejection, block), read with the
  rejected value, then each alert: title of the check, status label, finding, and what the person can do.
  Bullet and label of a blocking point in red, of an alert to be handled in orange; a justified (yellow) or
  accepted (green) alert has the status colour of the Consistency page (`.pa-statut-*`).
  - "Is it correct? I explain why": label 600, text field, secondary button "Save the
    explanation"; the suggested text (comment on the entry, or an explanation rejected without the admin's decision)
    is pre-filled and says where it comes from, nothing is saved without a click (an alert reopened because the value changed
    does not take back its old explanation). Same cell to justify in another framework for the same period:
    "Also to justify in "…"" (an explanation only applies to its own framework). Error in red under the
    field (`aria-invalid`, `aria-describedby`); success in pale green (`role=status`), which receives focus; alert
    corrected in the meantime: information blue callout ("This alert no longer applies…"), which receives focus.
  - In read-only mode (data entry closed, campaign closed), the variance vs N-1 is not a "Blocks validation" reason:
    it is then justified like the other alerts. The other reasons (evidence, value or N/A, N/A comment)
    remain displayed.
  - Explanation field: on phones (560 px and below), text at 16 px, so that taking focus does not zoom the
    page; when the script gives it focus, the cursor goes to the end of the suggested text.
  - Variance vs N-1: secondary button "I explain in the comment", which takes you to the Comment field (a validated
    value will go back to draft, the sentence says so).
  - "Alert sheet ›" link (primary as text, 24 px tall, 44 px on touch screens like the button
    "Save the explanation") only if the person can open it; otherwise "The responsible team is handling this alert."
    in soft text. Never a link that leads to "Access denied".
- **"Justify"** in the banner opens the first row with an alert in the list, with focus on its explanation (for a
  variance vs N-1 that can be edited, on "I explain in the comment"); with no row
  with an alert displayed (or without JavaScript), the Consistency page filtered on what remains to be justified.
- **Unsaved explanation**: same closing question as for the entry, titled "This explanation is not
  saved" ("Save the explanation and close / Close without saving it / Continue"); if the entry
  has also been changed, the entry's question says so in one orange sentence.

### Value and N-1 (signature component)
The value for the period and its comparison live side by side: "Value" column (700) then "N-1" column on the
table header background, year as a bordered label. In the panel, the value (24px, 700, 2 px border) and the N-1
box (table header background, outline border) follow each other; on phones, the N-1 box moves under the value.
On tablets and phones (under 800 px), where the variance column is hidden, a variance beyond the threshold is repeated under
the value: arrow and percentage in orange (like its badge), kept together, followed by "vs N-1" (or "vs
September 2025" for a monthly framework) in a discreet style, which wraps when space runs out; screen readers
hear "Variance vs N-1 beyond the campaign threshold".

### Written answer (Markdown toolbar)

- **Where**: the entry panel and the full-page entry of a KPI in the "written text" format (`_saisie_texte.html`).
- **Toolbar**: one row above the text area, joined to it (same 2 px dark border, header-table background), buttons of 40 × 40 px
  minimum: Bold, Italic | Heading, Bulleted list, Numbered list | Link. Each button has an `aria-label` and a `title` (shortcut);
  `role="toolbar"` with a single tab stop and arrow keys (Home / End). Ctrl+B and Ctrl+I work in the text area.
- **Preview**: secondary button at the right of the "Answer" label, `aria-pressed`; it replaces the text area (and the toolbar) by
  the rendered answer in a dashed box (`.md-rendu`), which receives the focus; the button then reads "Edit the text".
- **Rendered text** (`.md-rendu`): headings under the page's level (h4 to h6), lists indented 24 px, quotes with a left rule, code
  on the table-header background; links in the link colour, opened in a new tab.
- **Lists**: a plain-text extract, left-aligned, normal weight, small size (`td.extrait-redige`), never the Markdown syntax.
- **Previous answer**: a collapsible grey box under the text area ("N-1 · 2025 · extract…"), the rendered text inside.

### Import / Export and files
**Data** is exchanged in Import / Export (for everyone); **configuration as files** in Administration ›
Configuration files (admin). No landing page made of cards nor a "Who / When" banner: an introductory
sentence (`.intro-page`, soft text, 80 characters per line at most), then the action.
- **Export list** (`.liste-exports`, My exports): one row per export within a single bordered surface (not one card
  per export): name 600 with the label "Shared" (accent) or "Personal" (neutral), description, summary in 13px soft
  text; on the right "Download" (secondary, icon), "Edit" or "See the settings" (action link), drawn
  bin. Drawn handle for the admin (drag to reorder). A single primary button: "New export" (drawn plus icon). Under
  560 px, the actions move under the text. The accessible name of each link quotes the export ("Download "…"").
- **Large files** (exports made in the background above the threshold of Settings › Hosting): an h2 list at
  the top of My exports, same rows and surface as the export list (name 600, 13px soft status line); while the file is
  prepared, an 8 px indeterminate bar (`role=progressbar`, name that quotes the file) and "Waiting to start" or "Being
  prepared since 14:05"; when ready, "Ready · 12.3 MB · available until …" and "Download" (secondary, icon, accessible
  name that quotes the file), the row replaced in place and announced once (`role=status`); a failure in red text with
  its reason. One help sentence under the list (how long a file waits). The page that asked for it shows an information
  message, never a modal.
- **Export builder**: never opened by default. Questions in the order KPIs, organisations, period, file (h3,
  without numbers); what is rarely used goes into "More options" (open if changed); one-sentence summary and preview;
  "Download" bar sticky at the bottom; saving takes you back to the list.
- **KPI choice** (`.choix-kpi`, the same partial in the export and in the file to fill in): three chips "All KPIs",
  "A saved list", "Choose the KPIs". The checkboxes, grouped by theme (theme checkbox that ticks its visible KPIs,
  indeterminate state), scroll in an area bounded by two hairlines (no frame within the frame), with search,
  "Tick / Untick the KPIs displayed" and the count. "Save this list": name field and secondary button; same
  name = update. Enter never downloads.
- **KPI lists** (tab): same rows as My exports (name, Shared / Personal label, "N KPIs: first three…",
  "Export" as a secondary button, "File to fill in" and "Edit" links, Delete icon); "Create a list"
  opens a card: name and description side by side, sharing (admin), then the KPI choice in `seul` mode (checkboxes only, without
  chips or "Save this list"), "Save the list" and "Cancel".
- **Import preview**: two tiles only, *Values to save* (detail "N new · M replaced") and *Rejected*; identical and
  ignored rows in one discreet sentence under them. Under 560 px each row is a card that opens on the KPI (no "KPI:"
  prefix), the file row number last, empty "Before" and "Remark" hidden. A Table or Review export dropped here is
  refused with a sentence that says which file to use.
- **Excel files** (same rules as the screen): sample cells in the real colours, never a colour name in the text; the
  legend of the import roles (to fill in / key / for information) only on a file that is re-imported, a read-only sheet
  has its own legend or none; written answers in their own "Written answers" tab in plain text, never raw Markdown
  and never a column widened for them; long N-1 texts as an extract with the full text in a comment; rows aligned at
  the top; "Read me" starts with how to read the file.
- **End of import**: the sentence saying what remains ("N values saved, M of them as drafts: to be validated") with a single
  primary button "Validate these M values" and, under it, the sentence about what "Validate" commits to; "All done" (green) when
  everything is validated; what remains as a draft after validation is listed with its reason. In the preview, variances
  vs N-1 beyond the threshold are announced by a short orange callout and repeated on the row (▲ / ▼ and percentage in
  orange, as on Data entry).
- **Configuration files**: two cards side by side (Export the configuration / Edit in bulk), then the templates as
  section rows (the whole row is the link, download icon or chevron), then the data migration; "Good to know"
  collapsed.
- **Calculated KPIs in an import**: the rows get the label "Force" (orange tint: they replace a calculation) and come
  first after the rejections; under the table, a fieldset (legend "N values for calculated KPIs", a compact orange
  callout that says what forcing does) with two choice cards, "Force these N values" and "Ignore these N rows", none
  selected in advance and required before "Import" (the radios belong to the save bar form by `form=`; "Cancel" has
  `formnovalidate`). The end of import says how many values were forced (link to Overridden values) and how many rows
  were not imported.
- **Import preview**: what will change (tiles and labels "Creation", "Change") in information blue or neutral;
  orange stays for variances and alerts, green for "validated", red for rejections. Under 560 px, one card per row
  (`data-titre`), the KPI always visible.
- **End of import**: only the values that will pass the checks are offered for "Validate"; the others are listed
  under "To complete before validating" with their reason, and the primary button becomes "Complete on the Data entry page".
- **Order of exports** (admin): drag and drop, or "Move up / Move down" arrows with the keyboard (focus stays on the arrow).
- Numbers: plural following the language's rules (`pluriel`: in French "0 valeur", "1 valeur", "2 valeurs"; in English "0 values", "1 value", "2 values").

### Read-only accounts (reader, auditor)
- Tabs: the reader sees Dashboard and Visualisation; the auditor also sees Data entry, Consistency, **History** (clock
  icon) and Import / Export (without "Import values"). Neutral role label (neutral background, client text).
- Auditor's Data entry: the leading sentence says "Read-only: N values not validated · K alerts to justify", without a
  button; callout "Auditor account: you can see all the values, their evidence and their history; nothing can be
  changed."; panel with disabled fields, without "I explain why".
- Reader's Dashboard: organisation names without links (no Data entry), no "cells without a SPOC" alert.
- Account: "Organisations viewed" (multiple-choice list, indented according to the tree) only appears with these roles.

### Closing certificate (page to print)
- A sheet on the page on screen (white card, same tables as the rest of the tool, `.certificat-table`); the **Print** button
  and the back link sit above it and are hidden when printing. Printing: no menus, black on white whatever the appearance of
  the screen, a header (installation name, certificate and campaign) and a footer (date of issue, version) fixed on every
  sheet, `@page` margins for A4 and Letter, a table never cut in the middle (`break-inside: avoid`), the headings stay with
  what follows. The fingerprint is shown in four groups of 16 characters in the code font. Rule: a page made to print is a
  normal page of the tool with a print style, never a file made by the server.

### Guided tour (bubble)
- `#visite`: a small card (360 px at most), not modal: no veil, no focus trap, the focus is never taken on opening. Under
  the top-bar item it shows (a pointer and an outline `.visite-cible`), or at the bottom of the screen on a phone and for a
  step without an item. Content: "Step n of N", a short title, one or two sentences, **Back** (secondary), **Next** (last
  step: **Done**), "Don't show again" (link), a close cross of 24 px at least. Announced politely (`role="status"`); Esc
  closes it; the focus goes back to the button that started it. The animation follows "reduce motion". It opens once, on a
  home page, after the sign-in page; never on a direct link.

### Visualisation (views and charts)
A page made of **views** (tabs, like the pages of a Power BI report); visuals on a grid, under the
view's filters. The server computes and formats (`collecte/visuels/`), the browser draws with **Apache
ECharts** (canvas rendering, `static/js/visualisation.js`), without any colour written in JavaScript: the `outil` theme is
read from the installation's CSS variables on load.
- **Data colours** (`--viz-1` to `--viz-8`, `--viz-autres`, `--viz-pale`): the palette provided, checked for
  colour blindness, unless the admin replaces it (Settings › Identity › "Chart colours": preview, contrast of
  each colour on the card background, "Back to the default colours"); a colour chosen below 3:1 is flagged
  "too light" and the values of its series are always written (stacked bars: inside the segment, on a chip in the
  card colour). Never the client's colour (it designates the action) nor the state colours. Fixed order, never
  recycled: beyond 8 series or segments, "Other" in `--viz-autres`. Patterns (`decal`) from 3 stacked series or 3 segments
  of a ring onwards, and on a provisional value. Axis ticks in `--texte-doux` 12 px, grid lines in `--bord`, font
  Source Sans 3.
- **States**: validated = colour of the series; **provisional** (drafts included) = same hue, paler, striped pattern and
  "provisional" written in the tooltip and the table; **pending validation** = no bar, "pending";
  N/A and "–" without a bar. A KPI that has disappeared: the card says so ("This KPI is no longer available…"). A visual outside the
  person's scope is not sent to the page (no code, no name, no organisation): the status sentence only gives
  their number ("2 visuals in this view do not concern you").
- **View tabs**: links in `<nav aria-label="Vues">`, the open tab on a white surface with a 3 px stroke
  in the primary colour at the top; "Shared" badge. "New view" is a compact secondary button with the drawn plus icon,
  right after the last tab (lot 3: "Edit the view" is the one primary action of the area). On phones: a
  "View: …" button opens the list, "New view" included.
- **View filters**: one row above everything they control (period, compare with, organisation, framework,
  themes, values), never inside a card; a change waits 300 ms then reloads the data in place (the old
  content stays displayed, faded, `aria-busy`), and updates the address. Under the filters: the status sentence (validated,
  pending, provisional ◐) and the organisation path to go back up. On phones: "Filters · N" in a dialog.
  Filters changed: "Reset view filters" and, for whoever can edit the view, "Save these filters in
  the view" (only the filters); in edit mode, "Keep these filters in the view" (in the draft).
- **Grid** of 12 columns (6 on tablets, 1 on phones); widths 1/4, 1/3, 1/2, 2/3, 3/4, full width;
  heights 200, 320, 480 px (260 px on phones). **Visual card**: title (the KPI name, link to its view),
  subtitle in soft text (organisation, period, unit, its own filters), "…" menu (show data, full screen,
  image, Excel, definition), then the chart and the "Show data" link that opens its **data table**
  (column headers, first cell as row header; as cards under 560 px; open by default in forced colours mode).
- **Key figure**: value 32 px in 700, variance ▲ / ▼ and percentage written (never coloured) then "vs 2024: value" in
  soft text, small grey trend line whose last point is in `--viz-1`. Yes / no or list answer at 20 px.
- **Bars, line, N and N-1**: the chosen value written at the end or above; comparison of organisations as sorted horizontal
  bars, marker for the comparison period as a vertical stroke in soft text with its legend, the value
  written after the bar and after the marker (never cut by the stroke); a click or
  Enter on an organisation drills down into the tree. **Ring**: total in the centre, legend with figures (value and share).
  **Completion rate**: stacked bars validated (`--barre-valide`), drafts (`--barre-brouillon`, pattern), to fill in
  (`--contour`), rate written next to the name.
- **Tooltip**: the value first (700), the label next, the category under a hairline; texts from the server, escaped.
  With the keyboard: the chart has focus (`tabindex="0"`), the arrows move through the points, the announcement area reads the
  text, Escape hides the tooltip.
- **No animation** (`animation: false` for ECharts, `animation: 0` for SortableJS).
- **Edit mode**: KPI list on the left (280 px), visual settings on the right (320 px, only when a visual
  is selected). **Top bar** sticky at the top of the screen, always visible: "Editing the view", draft
  status, shortcut (Ctrl + S, Cmd + S on Mac: `aria-keyshortcuts`, written and read with the button), "Cancel
  changes", "Save view"; on entering, focus goes to the bar and the screen reader announces the mode;
  the panels stick below it; on phones, only the two buttons side by side. At the end of the page, the
  view name bar with the same buttons. Ctrl + S only saves the view in edit mode. Card in
  edit mode: dotted "Move" handle (also with the arrows), "Settings" button, dotted "Add to visual" area,
  "Other types" chips. Selected visual: border in the primary colour. The 9 chart types as radio
  buttons (icon and name); a greyed-out type writes its reason below it. Tablet: panels open as drawers;
  phone: full screen, adding via buttons, no dragging (the empty view says so), 44 px targets.
- **Definition and calculation method** (automatic view of a KPI): full-width card under the visuals, texts from the KPI sheet,
  then type, format, level and total as a 4-column list.

### Adding a framework (three doors, installation in three screens)
- **Three doors** (`_trois_portes.html`): three cards of equal rank, in the order install, compose, import; one
  column under 1,000 px (and in the setup wizard under 1,500 px). The "recommended to start with" mention is a neutral
  label (background, hairline, soft text), never the primary colour.
- **Horizontal step indicator** (`_etapes_installation.html`, `.etapes-numerotees`, shared with the import, the campaign and the data migration): numbered 24 px circles, tick for a completed step
  (primary tint), solid primary circle for the current step (`aria-current="step"`), 18 px hairline between two.
- **Template card**: dot in the framework's colour in front of the title, no colour band on an edge.
- **Checkbox tree**: one `fieldset` per theme (legend on the table header background: three-state checkbox, name,
  "3 / 8" counter in tabular figures, Collapse); one row per KPI (checkbox, code in `id-chip`, name, entry type
  label, unit on the right, hidden under 600 px); "Will be added anyway" is information (blue), not an alert.
  24 px checkboxes and 44 px rows on phones; the save bar, sticky, with "Continue ›" then "Cancel" (see "Save bar").
- **Summary**: sentences, not tiles; the technical detail (codes already used, units created, rules) stays collapsed.
  The sentence about levels only names the families present (entered, inherited parameters, calculated); tree still empty:
  a sentence recalls its levels with a link in the sentence. "Install" only goes once ("Installation in
  progress…", `aria-disabled`), restored on going back.
- **Keyboard**: on the KPI screen, a second skip link "Skip to the Continue button" (same style as "Skip to
  content"). Template whose KPIs are all installed: "See the framework" button and "All its KPIs are installed."
  in discreet text, no more "Add other KPIs".

### AI assistant (optional, off by default)
- **No AI control while it is off**: a button exists only when the socket, the use and the key are there (`docs/ai_socket.md`)
  and the person has the right; it is `hidden` without JavaScript (no button that does nothing).
- **Button**: compact secondary button with the drawn "sparkles" icon and a verb ("Explain with AI", "Propose with AI"),
  never the primary button (the page's action stays the person's). Busy state "Asking…" (`aria-busy`).
- **A proposal is marked**: compact block (`--marge-bloc`, hairline, card corners, surface), first line "Proposed by AI
  (<provider>)" in accent text with the icon, the text escaped (never HTML or Markdown), "The AI can be wrong…" in Mini
  soft text, then "Use as my explanation" and "Close". It receives the focus. In a list (matches, translations): an
  "AI" chip (`e-accent`), the proposal, its reason in soft text and a compact "Use" button that only fills the field
  ("Used" afterwards); the status line above says how many and offers "Use all N proposals". Saving stays the page's
  usual button.
- **Errors stay** (Error-Stays): a refusal or a failure is a red compact callout (`role="alert"`) in place of the proposal.
- **Settings › AI assistant**: what each use sends and never sends is always visible (two lists side by side, one
  column under 560 px), never folded.

## Principles from the Apple HIG

The Apple Human Interface Guidelines were read in full (about 70 of 173 pages apply to a web tool) and transposed.
The rules below are the ones that change or complete this design system; they apply
to every new screen and to every review.

### Named Rules

**The Answer-Every-Tap Rule.** Every button shows four states: hover, focus ring, **pressed** (`:active`, darker tint
and a 1 px push) and, for an action that takes time, **busy** (label in the "-ing" form, "Saving…", `aria-busy="true"`,
restored on error). A tap on a phone never leaves the screen still.

**The No-Hidden-Control Rule.** No control appears only on hover. A control revealed on hover is also shown on
`:focus-visible` / `:focus-within` and always shown under `(pointer: coarse)`.

**The Own-Confirmation Rule.** Never the browser's `window.confirm()`. A destructive action asks with the tool's
dialog: a title that says what will happen ("Delete the export “Monthly energy”?"), one sentence on the consequence,
a button with the verb ("Delete", in the danger style) and "Cancel", which has the focus. Escape cancels. Only for
uncommon, irreversible actions; prefer "Undo" for the others (to come).

**The Error-Stays Rule.** A message that something failed (not saved, not loaded, not sent) stays on screen until the
person closes it, with `role="alert"`. Only success messages disappear on their own (toast, 3.5 s).

**The One-Scroll Rule.** No vertical scroll area inside the scrolling page. Long lists grow with the page; headers and
action bars become sticky instead. An inner scroll is kept only for an unbounded list in a fixed panel (entry panel,
edit-mode KPI list).

**The Heading-Stays Rule.** A table longer than the screen keeps its column headings visible (sticky `thead`, below the
sticky bars), as in the consolidation table. The assignment grid scrolls only sideways in its frame and grows with the
page: CSS cannot keep its headings at the top of the screen, so a short script (`_app/09_grilles_formule.js`) moves the heading cells
down (`translateY`, position only, no animation) while the top of the grid is above the screen.

**The Respect-The-System Rule.** The tool follows the person's system settings: `prefers-reduced-motion` (no slide, no
rotation, no transition longer than a fade), `prefers-contrast: more` (soft text, hairlines and outlines darkened),
`forced-colors` (states and focus stay visible), browser zoom to 200 %, `color-scheme: light` declared. Fields are
16 px on phones so the iPhone does not zoom the page.

### Components (additions)

| Component | Rule |
|---|---|
| Menus ("…", pull-down) | Verb items, most used first. An unavailable item is dimmed with its reason, never removed. A destructive item comes last, in the danger colour, and asks for confirmation. Escape closes and returns focus to the button. |
| Tooltips (`title`) | Start with a verb, 75 characters at most, never the only place of needed information (not reachable by touch). |
| Collapsible help | Two appearances. **Help** (an explanation to read): `.aide-repliable`, a link in the primary colour with a chevron, at the bottom of the block it explains (Hosting, Dashboard "How these figures are calculated", Identity, Levels, Administration "What each section is for", Campaigns). **Options** (more fields): `.options-repliables`, a thin frame, bold title with a chevron ("Advanced options" of the import, "More options" of the export). "Good to know" cards (`.bon-a-savoir`) stay, always as the last block of the page. |
| Progress bars | Two heights and one track: 8 px in a page (`.progression`, completion of a language, loading), 4 px in a row of a table or list (`.mini-barre`, Dashboard rows, aggregate share, history). Track `--neutre`, validated fill `--barre-valide`. |
| Empty state | `.etat-vide`: one sentence in soft text, then the action to start (a link in the sentence or the page's button). No frame, no tick in a circle, no greyed tile. The dotted frame is reserved for areas where something is dropped (file drop zone, view in edit mode). |
| Numbered steps | `.etapes-numerotees`: the circles of a framework installation, everywhere (installation, import, campaign, data migration, setup wizard): 24 px circle, tick on a primary tint for a completed step, solid primary circle for the current one (`aria-current="step"`), 18 px hairline between two. |
| Progress | Precise words ("Reading 5,000 rows…"), never a bare "Loading…"; "N of M" when known; cancel when safe. |
| Keyboard shortcuts | Declared for both platforms (`aria-keyshortcuts="Control+B Meta+B"`), written "Ctrl" and "Cmd". |
| Printing | Dashboard and Visualisation print without header bar, tabs, filters, menus or buttons; cards are not cut across pages. |
| Charts | Title names the data; a one-line takeaway under the title is the target (to come). |

### Interaction rules

| Rule | Behaviour |
|---|---|
| Answer-Every-Tap | Pressed state (`:active`) on every button; busy state (`aria-busy`, small spinner) on the submit button of the entry panel and of every `data-ajax` form |
| Own-Confirmation | `<dialog id="confirmation">` in `templates/base.html`, `confirmer()` in `_app/01_socle.js`: the 6 `window.confirm()` are gone. The confirm button takes the verb of the original button ("Delete this export"), danger style for a deletion, focus on "Cancel", Escape cancels. Fixed on the way: 3 forms carried `data-confirmer` on the form itself (delete an export, a list, a data migration profile) and were sent without any question |
| Error-Stays | `erreur()` in `_app/01_socle.js`, `#erreur-persistante` (`role="alert"`, "Close" button): not saved, not loaded, order not saved, assignment refused, download interrupted. The toast is kept for successes |
| No-Hidden-Control | Assignment grid checkbox, remove buttons of KPI theme rows and of tokens: shown on keyboard focus and always on touch screens |
| Heading-Stays | Sticky column headings in the Data entry table (`details.section` now `overflow: clip`) |
| Respect-The-System | `color-scheme: light dark` (dark appearance); fields at 16 px under 560 px (no iPhone zoom); global `prefers-reduced-motion`; `prefers-contrast: more` (soft text and hairlines darkened); `forced-colors` (states and focus) |
| Keyboard shortcuts | Alt + up / down arrow on a KPI row of a framework moves it within its theme: a visible message with "Undo" follows, and the tip is written above the list (`.astuce-clavier`); Markdown toolbar: `Control+B Meta+B`, `Control+I Meta+I`; "Cmd" written for Mac in every language |
| Printing | `@media print`: header bar, tabs, filters, menus, buttons and messages hidden; cards not cut across pages |

### Further rules

- **Leaving the Visualisation edit mode** with unsaved changes by a link of the tool (view tabs, header tabs, any
  internal link): the tool's question "Your changes to this view are not saved" with three choices, "Save and leave",
  "Leave without saving" and "Continue editing" (focus, Escape, click outside). "Save and leave" follows the link only
  once the view is saved; refused, the person stays in edit mode and the reason stays on screen (Error-Stays). The
  browser's question (`beforeunload`) is kept only for closing the tab or the window, where it cannot be replaced.
- **What "Validate" commits to**: one visible sentence again under "Validate" (entry panel) and under "Validate these M
  values" (end of import), read with the button, without the tooltip (see "Unsaved entry").
- **Long For me list** (validator, 647 rows in the demo): past 200 rows, the first sections (organisations or
  themes, as grouped) open until about 200 rows are shown, the next ones are collapsed (`details`, keyboard and screen
  reader). The toggle says what it does: "Expand all" while a section is collapsed, otherwise "Collapse all" (also on
  Data entry). The "To do" banner, the counts and the search keep every row.
- **Nine Administration tabs on phones**: under 560 px, one compact menu "Section: <current>" (and "Page: <current>"
  for the Settings pages) instead of three rows of tabs; desktop unchanged.
- **Wording**: "backup" names only the database backup (Settings › Hosting); the card for the configuration file is
  "Export the configuration".
- **KPI assignment grid without inner scroll**: it grows with the page, keeps its sideways scroll and its sticky KPI
  column; its headings stay at the top of the screen (script); focused cells keep clear of the headings and the KPI column.

### Data and privacy

- **Data and privacy** (`collecte/templates/collecte/donnees_confidentialite.html`): one card per subject, each item a
  heading, one sentence, then three facts side by side (Why, How long, Who can see it; stacked under 800 px). Every
  figure comes from the settings. The company's own statement (Markdown) follows in its own card. Link in the footer of
  every page (sign-in page included) and in My account.

### Undo after a deletion and sortable tables

**The Undo-Not-Ask Rule.** Deleting something a person made for themselves, common and reversible (a saved export, a
KPI list, a Visualisation view, a visual of a view being edited), asks nothing: it is done at once and a message says
"Deleted “Monthly energy”." with an "Undo" button. The message is at the bottom centre (full width with 16 px margins
on phones), `role="status"`, and takes the focus on "Undo" (the deleted row no longer exists); it stays while it has
the focus or the pointer, then 10 seconds; Escape closes it and returns the focus. Without JavaScript it stays on the
page. Shared or irreversible deletions (campaigns, accounts, organisations, frameworks, evidence) keep the
Own-Confirmation dialog. Server side: the object goes to a trash (`supprime_le`), disappears everywhere, can be restored
by the person who deleted it or an administrator for 30 days, then is erased (`collecte/corbeille.py`).

**The Sortable-Columns Rule.** In a list where people compare (Dashboard tabs, Consistency, Reminders, Accounts,
History), a column heading that sorts is a button inside the `th` (a link when the server sorts), with `aria-sort` on
the `th` and a Lucide arrow: up-down when not sorted, up for ascending, down for descending. First click ascending,
next click reverses. Numbers sort as numbers, text with the language's collation, empty values always last. The sort is
kept in the address (`?tri-<table>=col` or `-col`). A tree table sorts inside each level and keeps the hierarchy. When
the page shows only part of the rows (History, Consistency over 500 alerts), the server sorts before cutting. Two keys
in one column ("KPI · Organisation", "Status · Date") are two buttons in the same heading. A sorted column is announced
("Sorted by Rate, descending."). Columns hidden on small screens hide their sort button too.

### Recently deleted

**The Find-It-Again Rule.** What the Undo message offers for 10 seconds stays reachable for the whole trash delay:
My account has a "Recently deleted" card (after the password card) listing what the person deleted and can still
restore: name in bold, then type ("Saved export", "KPI list", "View"), "Deleted on 12/03/2026 at 14:05 · 29 days
left" in small grey text, and a secondary "Restore" button on the right (`aria-label` "Restore “X”"). Under 560 px
the button goes under the text, full width, 44 px high. "Restore" puts the item back in its place and stays on the
list, with the message "Restored “X”.". Empty state: one sentence that gives the delay. Read-only accounts see only
what they deleted themselves (their views). Administrators also get **Administration › History › Recently deleted**
(link "Recently deleted (N)" at the top right of History, and in Settings › Hosting next to the delay): same rows,
plus "Deleted by". The delay (1 to 365 days, 30 by default) is a setting in Settings › Hosting, "Deleted items" box.

## Do's and Don'ts

### Do:
- **Do** run `python3 qa/css_orphelins.py` after removing or renaming a component: it lists the classes and ids of `outil.css` that no template, `.py` or `.js` uses any more (classes built at run time, such as `niveau-{{ code }}`, are kept); a test fails while one remains.
- **Do** take every brand colour from the installation's variables (`--principale`, `--principale-texte`, `--principale-bord`, `--contour`…).
- **Do** encode each state with a shape, a word and a colour, wherever it appears.
- **Do** display numbers in tabular figures, with the unit's decimals.
- **Do** keep 4.5:1 for text and 3:1 for borders, active outlines and icons.
- **Do** use a named rule from `static/css/outil.css` rather than a `style=` (margin, width and text utilities).
- **Do** draw icons with `{% icone %}` (Lucide set, `collecte/icones/`; any Lucide name works).
- **Do** apply the rules of "Principles from the Apple HIG" (HIG rules transposed to the web) to a new screen.

- **Do** reuse, in the standalone error pages (`templates/400.html` to `500.html`, served without the database), the
  values of the default palette above (soft text, hairline, surface), without any invented colour.
- **Do** give every inline `<script>` and `<style>` the nonce of the request: `<script nonce="{% jeton_csp %}">`
  (library `collecte`, loaded in each template that uses it). Each page has a strict content security policy
  (`collecte/politique_contenus.py`): a script or a style without the nonce does not run. Put behaviour in a
  listener (`addEventListener`, delegated on `document` for parts inserted later), driven by a `data-` attribute:
  `data-envoi-changement` (a choice that submits its form), `data-lien-inerte` (a link with no effect). A
  `<script type="application/json">` (`json_script`) needs no nonce. A test reads every template and module
  (`collecte/test_politique_contenus_gabarits.py`), another opens every page (`collecte/test_politique_contenus_pages.py`),
  and every browser test fails on a violation.

### Don't:
- **Don't** use gradients, emoji, Unicode symbols as icons, or icon tiles.
- **Don't** write a colour in a template's `style=`.
- **Don't** put text in letter-spaced capitals or under 12px.
- **Don't** use the primary colour to decorate (figures, bullets, column backgrounds): it designates the action and where you are.
- **Don't** add shadows to cards or a thick colour band on one side.
- **Don't** animate in a loop: the only movement is the indeterminate loading bar, turned off if the user reduces motion.
- **Don't** use `window.confirm()`, hover-only controls, self-hiding error messages or a scroll area inside the page.
- **Don't** write an event handler in an attribute (`onclick=`, `onchange=`, `oninput=`…), a `javascript:` link,
  `eval`, `new Function`, a timer with a string, or `setAttribute("style", …)` in a script (set `el.style.…` instead):
  the content security policy blocks them. A `style=` attribute still works (computed widths, indents and colours), but
  prefer a class: the policy may forbid it later.

## Later screens

The rules above apply; this section lists only what is new.

- **Help icon** (`.aide-haut`, Lucide `circle-help`): in the top bar of every page for a signed-in person, left of the
  account, with a title and an `aria-label` ("Help"). It opens the guide of the role at the section of the page (same
  tab). No introduction on the page repeats it.
- **Language menu**: seven entries, each written in its own language (Deutsch, Español, Français, Italiano, Nederlands,
  Português, English). German and Dutch texts are the longest: test every button and tab label in them.
- **Assignments on a large group**: above 60 organisations at a level, a **Group** field is added to the filter bar
  (`#filtre-groupe`, the panel of the filter model, with the number of organisations of each group); the page shows one
  group of organisations at a time and reloads from the server. The last option, "All (slow for a large group)", is not
  remembered. The filters, the selection of a whole row, and the bulk save apply to the group shown only.
- **Evidence to delete** (Administration › History › Evidence to delete): a page of the filter-bar model (search, KPI,
  organisation, campaign), one row per evidence file, selection by row or for all rows shown, a destructive action that opens the
  tool's confirmation. Without a retention period, the page shows the empty-page state with a link to the setting. It has
  no tab of its own (the tab bar is full).
- **Settings › Assistants** and **Settings › AI assistant**: one card per switch, the key field is a password field that
  stays empty, and the page lists exactly what is sent. Same save bar and callouts as the other Settings pages.
- **My account › AI assistants (MCP)**: a card with the token list and a form. A token appears once, with a copy button.
  Focus moves to the token when it is created, and "Copied" is announced (`role=status`).
- **Error page for an out-of-date form** (`templates/403_csrf.html`): the standalone error page (default palette, code
  shown, no technical text) with a link back to the previous page. Sent as JSON to the page script.
- **Large files**: see "My exports" above.
