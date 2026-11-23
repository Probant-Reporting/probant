# Interface translation (seven languages)

This page explains how the tool shows its interface in seven languages: English, French, Spanish, German, Italian,
Dutch, and Portuguese. It also gives the rules for everyone who translates a zone of the site, people or assistants.

The whole interface is translated, and each person can change the language. A language is its label
files only, and it is offered to the people only when it is complete (section 5, "Add a language").

The words and the tone of each language are in the [translation glossary](translation_glossary.md). A native reader
must still check German, Italian, Dutch, and Portuguese (and, as for French and Spanish, the AI translations) before a
sale in the country of each language.

To know how to write the texts themselves (tone, length, words, typography), see the
[writing guide](writing_guide.md). **English is the base language**: you write a text in English
first, then you translate it.

## 1. How it works

The table shows the parts of the translation system.

| Element | Where | Purpose |
|---|---|---|
| Language files | `libelles/<zone>.<language>.json` | One file per zone and per language: `cadre.en.json`, `cadre.fr.json`, `cadre.de.json`… (9 zones × 7 languages). Flat keys, texts, `{nom}` parameters, plurals. |
| Split into zones | `parametres/zones_langue.py` | For each zone: title, key prefixes, files (templates, Python modules, scripts). Zones do not overlap. |
| Reading | `parametres/libelles.py` | `libelle(cle, langue=None, n=None, **valeurs)`, `libelles(prefixe)`, `choix(objet, champ)`. |
| Interface language | `parametres/langues.py` | `interface()`, `interface_de(code)`, `activer_interface(code)`, `pour(utilisateur)`, `LangueMiddleware`. |
| Choice of language | Top bar (`templates/_choix_langue.html`, address `/langue/`) and **My account** | Visitor: kept in the session. Signed-in person: session **and** `Utilisateur.langue`. |
| Checks | `parametres/controle_libelles.py`, `parametres/test_controle_libelles.py`, `parametres/test_traduction.py`, `qa/translation_check.py` | One check serves the start of the tool, the tests, and the translation tool: same keys, parameters, tags, and plural forms as English, in every language. Zones that do not overlap, no hard-coded French text in translated zones. |

The whole site uses a single system: the Visualisation one, extended. The tool does not use Django's translation tool
(gettext), because gettext needs `msgfmt`, a piece of software that is missing on the server.

The tool reads the language files once, at startup. **After you change a language file, restart the server.**
`runserver` restarts by itself.

### Displayed language

A single preference per person sets two things:

| | Language used | Fallback |
|---|---|---|
| **Interface** (menus, buttons, messages) | the preference if the language is complete (en, fr, es, de, it, nl, pt) | its base language (`pt-BR` → `pt`), then the installation's default language, then English (the base language) |
| **Contents** (KPI names, definitions, themes, units, list answers) | the preference if it is an **active** content language (Settings › Languages) | the installation's default language, then the reference language (unchanged) |

Order of the preference: choice in the top bar (session) → `Utilisateur.langue` → the installation's default language.
A key missing from a language (empty file, zone not yet translated) is displayed in the default language, then in
English, the base language. A key missing everywhere is displayed as is (visible, never an error).
A new installation starts in English (`DEFAULT_LANGUAGE` in `.env`: `en` by default; any other language of the interface
is possible); existing installations keep their language. **Entered contents** (values, comments,
organisation names, identity of the installation) are never translated.

## 2. The zones

A zone is a language file (in each language) and a list of files. One person (or assistant) works on one zone:
nobody changes the file of another zone. The exact list of files is in `parametres/zones_langue.py`. The test checks
that each template is in exactly one zone.

The table shows the 9 zones.

| Zone | Prefixes | Language file | Content | Status |
|---|---|---|---|---|
| `cadre` | `cadre.`, `commun.`, `choix.` | `libelles/cadre.*.json` | Top bar, menu, language selector, footer, sign-in page, My account, Data and privacy, error pages. Common words (`commun.*`) and model choice lists (`choix.*`) | **Translated** (7 languages) |
| `saisie` | `saisie.` | `libelles/saisie.*.json` | Data entry (both views), data entry panel, KPI sheet, Consistency, History, page script (`_app.js`) | **Translated** (7 languages) |
| `suivi` | `suivi.` | `libelles/suivi.*.json` | Dashboard, Reminders page, Import / Export, Excel files (exports, import templates) | **Translated** (7 languages) |
| `admin` | `admin.` | `libelles/admin.*.json` | Administration (accounts, organisations, campaigns, assignments, files, data migration, History) and Settings (identity, languages, translations, levels, thresholds, hosting, restore, Visualisation settings) | **Translated** (7 languages) |
| `referentiels` | `referentiels.` | `libelles/referentiels.*.json` | Setup wizard, Frameworks (home, content, settings, sharing, new), installation from the library, packages, KPI framework page | **Translated** (7 languages) |
| `messages` | `messages.` | `libelles/messages.*.json` | Reminder emails, common Python messages: model validation errors, calculations, formulas, periods, permissions (read-only), script responses | **Translated** (7 languages) |
| `visualisation` | `visu.`, `format.` | `libelles/visualisation.*.json` | Visualisation | **Translated** (7 languages) |
| `espaces` | `espaces.` | `libelles/espaces.*.json` | Spaces: top bar selector, Spaces page (list, People and access), New space, "no access" page, creation messages and errors | **Translated** (7 languages) |
| `mcp` | `mcp.` | `libelles/mcp.*.json` | Assistants: the Settings › Assistants page, the card of My account, the messages and the history lines of the MCP server | **Translated** (7 languages) |

All zones use the `commun.*` keys (Save, Cancel, Yes, No, N/A…) and the `choix.*` keys (statuses, roles,
frequencies…). Only the `cadre` zone changes them. If a zone needs another common word, it puts the word in its own
keys.

## 3. Tools

The table shows how to write a translated text in each place.

| Need | How to write it |
|---|---|
| Text in a template | `{% load collecte %}` then `{% libelle "saisie.panneau.titre" %}` |
| With parameters | `{% libelle "saisie.fin_saisie" date=campagne.date_fin_saisie|date:"d/m/Y" %}` |
| Plural | `{% libelle "saisie.valeurs.nb" n=total %}` (the `n` parameter chooses the form and replaces `{n}`) |
| In an attribute, or reused | `{% libelle "cadre.deconnexion" as texte %}` then `title="{{ texte }}"` |
| Formatting in the text | `{% libelle_html "cadre.connexion.aide" contact=instance.contact %}` (allowed tags: `<strong>`, `<b>`, `<em>`, `<code>`, `<br>`. Parameters are escaped.) |
| Value of a model's choice list | `{{ campagne|choix:"statut" }}`, `{{ user|choix:"role" }}` (instead of `get_…_display`). In Python: `LB.choix(objet, "statut")`, `LB.choix_valeur(Reponse, "statut", valeur)` |
| Python (view, message) | `from parametres.libelles import libelle` then `messages.success(request, libelle("admin.compte.cree", nom=u))` |
| Page script (`_app.js`) | `lib("saisie.js.enregistre")`, `lib("saisie.js.n_valeurs", { n: 3 })`. The `commun.*` and `<zone>.js.*` keys go with every page (`{% libelles_js %}` in `base.html`). |
| Email or message for another person | `with L.pour(utilisateur): …` (interface and contents in their language). Reminders already do this: `relances.rediger`. |
| File exported in a chosen language | `libelle(cle, langue)` with the language of the export, or `with L.activer_interface(code): …` |
| Django messages (password too short…) | `with translation.override(L.interface()): …` around the validation **and** the display (done in My account). `LangueMiddleware` (`parametres/langues.py`) activates the Django language of the interface for each request, except `/admin/`, which stays in French. Numbers that Django shows follow the language. In Python, write a percentage with `avec_pourcent()` (`collecte/templatetags/collecte.py`, filter `|pct` in templates, `pourcent_texte()` in `collecte/visuels/formes.py`), never `f"{x} %"`. |

## 4. Conventions

### Keys

- A key has lowercase letters, digits and `_`, separated by dots: `<zone prefix>.<page or block>.<element>`. For
  example: `saisie.panneau.valider`, `admin.comptes.supprimer_confirmer`, `suivi.export.colonne.statut`.
- The prefix is the prefix of the **zone of the file that shows the text**. For example, a text from
  `collecte/views.py` is in `saisie.`, even if it appears on the Dashboard. Script texts: `<zone>.js.*`.
- One key has one meaning. Do not reuse a key from another page because the French is the same: the English or the
  Spanish can be different.
- Do not cut a sentence into pieces. Put one whole sentence per key, with its parameters, because the word order
  changes from one language to another.
- No empty key, no empty text. Sort the files by key (`json.dump(..., ensure_ascii=False, indent=1, sort_keys=True)`).

### Parameters

- Write `{nom}` in lowercase, with the same parameters in all the languages (test). Use names with a meaning: `{kpi}`,
  `{organisation}`, `{date}`, `{nombre}`.
- Some names are **reserved** (arguments of `libelle()`). `langue` and `cle` are forbidden (test). `n` is the number
  for the plural.
- A parameter receives a value that is already formatted (date `d/m/Y`, number with `nombre()`), never a French
  sentence.

### Plurals

- A text that depends on a number has 2 forms: `{"one": "{n} valeur validée", "other": "{n} valeurs validées"}`.
  Write both forms in every language. The test checks that the form is the same.
- Rule: in French, 0 and 1 are singular. In the other languages, only 1 is singular ("0 KPIs", "0 valores", "0 Werte"). Each language sets it in `format.zero_singulier` (`visualisation.<language>.json`).
- Plurals replace the `|pluriel` filter and the "(s)": no more "2 valeur(s)".

### Typography

The table shows the typography rules for each language.

| | French | English | Spanish |
|---|---|---|---|
| Colon, semicolon, ? ! | space before (« Total : 3 », « Annuler ? ») | no space ("Total: 3") | no space, ¿ ¡ at the start (« ¿Eliminar? ») |
| Quotation marks | « … » (non-breaking spaces) | “…” | «…» (no space) |
| Apostrophe | ’ or ' (keep the one in the current text) | ' | — |
| Capitals in titles and buttons | first letter only | first letter only (the style of the tool, not "Title Case") | first letter only |
| Numbers and percentages (format of the chosen language) | « 1 234,5 », « 12,5 % » | "1,234.5", "12.5%" | «1.234,5», «12,5 %» |
| Dates | 28/10/2026 | 28/10/2026 | 28/10/2026 |
| Form of address | vous | you | usted (« Haga clic », « Compruebe ») |
| Spelling | — | British English (Visualisation, organisation, authorised) | Spanish from Spain |

- German, Italian, Dutch, and Portuguese: form of address, quotation marks, numbers, percentages, dates, and spelling
  are in sections 3 and 4 of the [translation glossary](translation_glossary.md).
- Tone: short, simple sentences, no jargon. Users are not IT people.
- Never change the case of a name that comes from a setting or a translation (a level, a status, a role, a unit). German
  nouns keep their capital in the middle of a sentence. For a status, a role, a frequency, or a response format used in
  the middle of a sentence or in brackets, the label of each language carries the case: the keys `choix.phrase.*`
  (`{{ campagne|choix_phrase:"statut" }}` in a template, `choix_phrase()` in Python), never `|lower` or `.lower()`.
- Keep the "›" in menu paths. Translate menu names with the same words as the menu (glossary).
- Ellipsis: the "…" character. Dashes: "–" between two parts of a title.

### What is not translated

- Entered contents and identity (title, name, contact, subtitle of the installation).
- Codes (KPIs, organisations).
- Units: they are translated as contents, in **Administration › Settings › Languages**, then **Translate**.
- The contents that the tool installs itself (levels of the tree, entry types, answer types, description categories, the 15
  first units) are stored in the language of the installation. Their translation in the seven languages is in the data
  migration `parametres/0036` and in `parametres/traductions_depart.py` (an installation that is new or emptied). An
  administrator who turns on a content language (**Administration › Settings › Languages**) sees them in that language.
  The level templates of the setup assistant (Organisation step: "Group › Country › Entity › Site", "Holding › Subsidiary"…)
  are in `parametres/niveaux.py` (`NOMS_MODELES`), in the seven languages: the choice shows the language of the screen,
  and the levels that a template creates take the language of the installation, with the six other languages as
  translations.
  To add a language of the interface, add its words with a new additive data migration, as `0036` does, add them to
  `NOMS_MODELES`, and add the guides of the roles
  (`docs/<language>/guides/`, `collecte/aide.py`).
- `verbose_name` and `help_text` of models. Do not change them: each change creates a migration. Expert mode
  (`/admin/`) stays in French. A form that shows these labels replaces them in the view or the template.
- `manage.py` commands (for IT) and the server log: they are in English whatever the language of the interface.
- The **headers of files that are imported again** (import templates, exports that you can import again). The import
  must recognise the header in all languages (French and the language of the file). Never break the current
  recognition.
- Fixed names that other tools read (the "Valeurs" tab that Power BI reads…).
- The demo contents, the library templates, the maps of the charts (English), and the official EFRAG workbook (English,
  French, Spanish).
- The administration files (configuration workbook, framework file): French or English only (`fichiers.selon`). The
  exports, the file to fill in, and the rejected-rows report follow the language of the export, in any complete language.

### No hard-coded text

- The `AucunTexteEnDurTests` test scans the templates and scripts of the zones listed in `TRADUITES`
  (`parametres/zones_langue.py`). It checks:
  - Text between tags
  - Attributes that are read (`title`, `aria-label`, `placeholder`, `alt`, `label`, `data-confirmer`…)
  - Literals shown in `{% %}` and `{{ }}` (`default:"Aucun"`, `with titre="…"`)
- These words are allowed as is: KPI, N/A, GHG, ID, PDF, CSV, Excel…
- The test ignores a line that contains `libelle-ok` (technical text: font name, code example). Use it rarely, and
  give the reason: `{# libelle-ok : format de date technique #}`.
- When a zone is finished (templates, Python and scripts), add it to `TRADUITES`.

## 5. Translate a zone

Before you start:

- Read this document and `parametres/zones_langue.py` (the list of the files of the zone).
- Only change the files of your zone and its language files.
- For a new text, write the English first (see the [writing guide](writing_guide.md)).

To translate a zone:

1. For each text that the zone shows, create the key in `libelles/<zone>.fr.json`, with the current French text,
   identical.
2. Replace the text with `{% libelle %}`, `libelle()` or `lib()`.
3. For statuses and roles, use `|choix` instead of `get_…_display`. For common words, use the existing `commun.*`
   keys.
4. Write the English texts in `libelles/<zone>.en.json`, with the same keys. Use the glossary (section 6).
5. Write the texts of every other language in `libelles/<zone>.<language>.json`, with the same keys. A language that
   lacks a key is not offered (the test of complete languages fails): a lot that adds a text adds it in all seven
   languages.
6. Add the zone to `TRADUITES`.
7. Run `python3 -I qa/translation_check.py check <language>` for each language, then
   `python3 manage.py test --noinput --parallel 4`. All tests pass.
8. Check the pages in the languages at 1,440 and 390 px. The German, Spanish, and Dutch texts are longer: nothing must
   overflow.

As long as a file is empty (`{}`), the zone is displayed in the fallback language. As soon as it is no longer empty,
it must be complete.

### Add a language

A new interface language needs **only its label files**: no code per language.

1. Translate the nine zones from English with the [translation glossary](translation_glossary.md), and
   `qa/translation_check.py` (extract by batch, apply, check). Then translate the batches back to French with the same
   tool and read the list of wrong meanings (done for German, Italian, Dutch, and Portuguese on a sample).
2. Set the language settings in the files themselves: `format.milliers`, `format.decimal`, `format.pourcent` and
   `format.zero_singulier` (`visualisation.<lang>.json`), `cadre.langue.nom`, `saisie.date_longue`.
3. A language appears in the top bar, in My account, in reminder emails and in exports **only when it is complete**: all
   zones, the same keys, parameters and tags as English (`parametres/controle_libelles.py`, checked at startup, no
   switch to turn on). A language in progress is never offered.
4. `parametres/test_controle_libelles.py` applies every check (keys, parameters, tags, plural forms, no "RSE") to every
   language that has files. Month names and quarter prefixes of the six planned languages are in `collecte/periodes.py`.
5. A native reader checks the language before the tool is offered in its country.

## 6. Glossary

The table gives the word for each concept in French, English, and Spanish. For German, Italian, Dutch, and Portuguese,
use the [translation glossary](translation_glossary.md). Use only these words.

| French | English | Spanish |
|---|---|---|
| KPI (indicateur) | KPI (indicator) | KPI (indicador) |
| référentiel | framework | marco de referencia |
| référentiel KPI (liste des KPI) | KPI framework | marco de KPI |
| bibliothèque (de référentiels) | library | biblioteca |
| campagne | campaign | campaña |
| exercice | reporting year | ejercicio |
| période | period | periodo |
| saisie (action, menu) | data entry | captura |
| saisir | enter | capturar |
| saisie ouverte / fermée | open / closed for data entry | captura abierta / cerrada |
| valeur | value | valor |
| valider (une saisie) | validate | validar |
| validé | validated | validado |
| brouillon | draft | borrador |
| à saisir | to fill in | por capturar |
| rouvrir | reopen | reabrir |
| valeur forcée, demande de forçage | overridden value, override request | valor forzado, solicitud de valor forzado |
| accepter / refuser (une demande de forçage) | approve / reject | aceptar / rechazar |
| N/A (non applicable) | N/A (not applicable) | N/A (no aplica) |
| calculé | calculated | calculado |
| agrégation, agrégé | aggregation, aggregated | agregación, agregado |
| formule | formula | fórmula |
| unité | unit | unidad |
| thème | theme | tema |
| organisation | organisation | organización |
| niveau (de l'arbre) | level | nivel |
| arbre des organisations | organisation tree | árbol de organizaciones |
| administrateur | administrator | administrador |
| validateur | validator | validador |
| contributeur | contributor | colaborador |
| lecteur | reader | lector |
| auditeur | auditor | auditor |
| compte | account | cuenta |
| mot de passe (provisoire) | (temporary) password | contraseña (provisional) |
| SPOC (personne référente) | SPOC (point of contact) | SPOC (persona de referencia) |
| attribution | assignment | asignación |
| preuve | evidence | justificante |
| commentaire | comment | comentario |
| relance | reminder | recordatorio |
| relancer | send a reminder | enviar un recordatorio |
| cohérence | consistency | coherencia |
| alerte (à traiter) | alert (to be handled) | alerta (por tratar) |
| justification | justification | justificación |
| écart (N-1) | variance (vs N-1) | desviación (respecto a N-1) |
| tableau de bord | dashboard | cuadro de mando |
| Visualisation, vue, visuel | Visualisation, view, visual | Visualización, vista, visual |
| taux de remplissage | completion rate | tasa de cumplimentación |
| Une organisation à la fois, Tout ce qui m'est attribué (vues de la Saisie) | One organisation at a time, Everything assigned to me (Data entry views) | Una organización a la vez, Todo lo que se me ha asignado (vistas de la Captura) |
| Je réponds à | I am answering | Respondo a |
| Historique (journal) | History (log) | Historial (registro) |
| Import / Export | Import / Export | Importar / Exportar |
| Administration, Paramètres | Administration, Settings | Administración, Configuración |
| identité (de l'installation) | identity | identidad |
| langue de référence / par défaut | reference / default language | idioma de referencia / predeterminado |
| traduction | translation | traducción |
| mise en place (assistant) | setup (wizard) | puesta en marcha (asistente): "configuración" is already "Paramètres" |
| installation (de l'outil) | installation | instalación |
| sauvegarde, restauration | backup, restore | copia de seguridad, restauración |
| hébergement | hosting | alojamiento |
| espace (département) | space | espacio |
| paramètre hérité | inherited parameter | parámetro heredado |
| facteur d'émission | emission factor | factor de emisión |
| type de saisie, type de réponse | entry type, answer type | tipo de captura, tipo de respuesta |
| liste de choix | choice list | lista de opciones |
| oui / non | yes / no | sí / no |
| fiche KPI | KPI sheet | ficha del KPI |
| enregistrer, annuler | save, cancel | guardar, cancelar |
| supprimer | delete | eliminar |
| se connecter, se déconnecter | sign in, sign out | iniciar sesión, cerrar sesión |

### Exports and emails

- **Excel exports**: the files of the `suivi` zone take their texts from the language files, with `X.t(langue, cle)`
  (`collecte/fichiers.py`). The terms of the interface (statuses, origins, yes / no) go through `traduire()` in
  `collecte/exports.py` (keys `suivi.export.terme.*`). Spanish, and any language that has its files, comes by itself.
  This replaced the first method (`X.selon(langue, fr, en)` and an `EN` dictionary). `X.selon()` stays only for the
  administration files (`admin` zone), in French or English.
- **Reminders**: `relances.rediger` writes in the language of the recipient (`L.pour`). The default template
  (`SUJET_DEFAUT`, `MESSAGE_DEFAUT`) and the small words ("demain", "brouillon à valider") are in `messages.*`
  (`messages.relances.*` keys).

## 7. Open points and answered questions

### Open

- **Proofreading by native readers** of the six languages translated from English. AI translated English and Spanish, then German,
  Italian, Dutch, and Portuguese (6,029 to 6,042 texts each, checked on screen and by back-translation of a sample of 150 texts). Choices of tone to confirm: section 5
  of the glossary.
- **Texts still in French**:
  - Contents saved in the database: consistency alerts of a closed campaign (the alerts of an open campaign are
    written again in the language of the reader), a configured reminder template that has no version in the language,
    names of the provided exports after a rename
  - Form labels that come from Django models (`help_text`)
  - Month names in dates ("décembre")

### Answered

- **Numbers and dates**. The question was: outside Visualisation, numbers and
  dates stay in French format ("1 234,5", 28/10/2026) in all languages. Must English use "1,234.5" and accept the
  point in data entry? Answer: numbers and percentages follow the chosen language (see "Typography"). Data entry
  accepts the comma or the point. Dates stay 28/10/2026 in all languages.
- **Reminder template** (migration `parametres/0017`). The question was: the template that
  the administrator sets is a single text. Is one template per language necessary? Answer: yes. The reminder template
  has a version per language (`relance_traductions`), set on the **Reminders** page.
- **Unit "o" for file sizes**: it now follows the language of the interface ("o", "Ko" in French, "B", "KB" in the
  other languages, `parametres/sauvegardes.py`).
