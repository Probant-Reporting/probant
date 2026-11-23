# Writing guide

The single writing system for every text of the tool: interface (menus, buttons, labels, help, messages), reminder
emails, exports, and documentation. French version: [`docs/fr/guide_ecriture.md`](fr/guide_ecriture.md) (keep both
in step).

**English is the base language.** Every text is written first in English, following this guide. The interface exists in
seven languages: English, French, Spanish, German, Italian, Dutch, and Portuguese. The other six are translated from the
English, then adapted with the rules of section 8. The words of each concept are fixed in the glossary
([`docs/translation_glossary.md`](translation_glossary.md), one column per language). The mechanics (zones, keys,
parameters, how to add a language) are in [`docs/translation.md`](translation.md).

A new text is not finished until it exists in the seven languages: a language that lacks one key is not offered to the
people (`parametres/controle_libelles.py`), and `qa/translation_check.py check <language>` lists what is missing.

Sources. The guide takes from each source only what suits a web tool used by
non-specialists, in seven languages:

| Source | Used for |
|---|---|
| Apple Style Guide | Interface text: names of actions, buttons, messages, mechanics |
| Google developer documentation style guide | Documentation: structure of pages, procedures, headings |
| ASD-STE100 (Simplified Technical English) | Controlled language on top of both: one word = one meaning, short sentences, active voice |

When the sources disagree, this guide decides (for example: no contractions, as in STE100, because they make
translation harder).

## 1. Principles

1. **Write for a busy person who is not an IT specialist.** Use the words of the job, not the words of the code.
2. **One concept = one word, everywhere.** Use the glossary. Do not change a word to avoid repetition.
3. **Say what to do, then why (if necessary).** The action comes first.
4. **Short.** If a text needs more than two sentences on screen, put the rest in a foldable help or in the
   documentation.
5. **Write for translation.** Simple sentence structure, no idioms, no wordplay, no humour.

## 2. Voice and tone

| Rule | Do | Do not |
|---|---|---|
| Speak to the reader as "you" | You can reopen a validated value. | Users can reopen… / The administrator can reopen… (when the reader is the administrator) |
| No "we" | The tool calculates this value. | We calculate this value. |
| Make the reader the subject | You can export the table to Excel. | This page allows you to export… |
| Active voice | The validator validates the value. | The value is validated by the validator. |
| Present tense | The reminder goes on Monday. | The reminder will be sent on Monday. |
| No "please", no exclamation mark | Enter a number. | Please enter a number! |
| No contractions | You cannot delete this campaign. | You can't delete… |
| Neutral and calm, even for errors | This file is larger than 5 MB. Select a smaller file. | Error! Invalid file. |
| Gender-neutral | the contributor, they | he or she |

## 3. Interface text

### Capitals

**Sentence case everywhere**: only the first word and proper names take a capital. This applies to page titles, menus,
tabs, buttons, column headings, labels and messages, in the seven languages.

- Do: `Export to Excel`, `Reporting year`, `Send a reminder`
- Do not: `Export To Excel`, `Reporting Year`

### Length

| Element | Maximum | Form |
|---|---|---|
| Button, link that acts | 3 words | Verb + object: `Validate`, `Add an organisation`, `Export to Excel` |
| Menu item, tab, page title | 3 words | Noun: `Data entry`, `Reminders`, `Settings` |
| Field label, column heading | 4 words | Noun phrase, no colon at the end in a table |
| Help under a field | 1 sentence, 20 words | Says what to enter or what the field changes |
| Introduction of a page | 2 sentences, 25 words each | Says what the page is for, then the main action |
| Message after an action | 1 or 2 sentences | What happened, then what to do (if anything) |
| Noun cluster | 3 nouns | `KPI validation status` is the limit. Not `KPI validation status filter` |

Longer explanations go in a foldable help ("How does it work?") or in the documentation.

### Buttons and actions

- A button starts with a **verb** that says exactly what happens: `Delete the campaign`, not `OK`.
- The same action has the same verb everywhere (section 5).
- An action that cannot be undone says so in its confirmation, with the consequence:
  `Delete the campaign? Its 1,240 values and their evidence are deleted. You cannot undo this.`
  The confirm button repeats the verb (`Delete`), the other button is `Cancel`.
- No ellipsis (…) at the end of a button, except when the action opens a step that asks for more information.

### Messages

| Type | Structure | Example |
|---|---|---|
| Success | What happened (past participle) | `Value saved.` |
| Error the person can fix | What is wrong + what to do | `This file is a Word document. Select a PDF, JPG or PNG file.` |
| Error the person cannot fix | What happened + who can help | `The email was not sent. Contact your IT team.` |
| Warning before an action | Consequence + question | see "Buttons and actions" |
| Empty state | What is missing + how to add it | `No campaign yet. Create a campaign to start the data entry.` |

- Never blame the reader: `This value is not a number`, not `You entered an invalid value`.
- No technical codes or terms in a message (no "error 500", "exception", "invalid input").

### Referring to the interface in help and documentation

- Write the name of a button or menu **exactly as on screen**, in bold in the documentation:
  "Click **Export to Excel**."
- Paths with `›`: **Administration › Settings › Languages**.
- Do not describe position or colour only ("the green button on the right"): give the name.
- Do not refer to a sense: "A message appears", not "You see a message".

## 4. Sentences (controlled language)

From ASD-STE100, for every sentence (help, messages, emails, documentation):

1. **One instruction per sentence.** Two actions → two sentences, or a numbered list.
2. **Instructions: 20 words maximum. Descriptions: 25 words maximum.** Numbers, codes, quoted button names and
   names count as one word.
3. **Condition first, then a comma, then the action**: "If the campaign is closed, ask an administrator to reopen it."
4. **Keep the small words**: articles (the, a), "that" after verbs ("Make sure that the file is a PDF").
5. **No semicolon.** Write two sentences.
6. **No phrasal verbs** when a simple verb exists: "start" (not "kick off"), "find" (not "find out"), "give"
   (not "hand over").
7. **No Latin abbreviations**: "for example", "that is", "and so on" (not e.g., i.e., etc.).
8. **Avoid** "should" (write "must" or "can"), "may" for possibility (write "can"), "in order to" (write "to"),
   "via" (write "through" or "with"), "and/or", "(s)" for plurals.
9. **A paragraph has one topic and 6 sentences maximum** (documentation).

## 5. Words for actions

One verb per action, in every language. The French and Spanish columns are the translations to use. The German, Italian, Dutch, and Portuguese verbs are in section 2.5 of the [translation glossary](translation_glossary.md).

| Action | English | French | Spanish | Do not use (English) |
|---|---|---|---|---|
| Open a session | sign in / sign out | se connecter / se déconnecter | iniciar sesión / cerrar sesión | log in, log on |
| Press an on-screen element | click | cliquer | hacer clic | click on, press, hit |
| Type information | enter | saisir | capturar (a value), introducir (a name, a password, an email) | input, fill in, type in (except "fill in a form") |
| Tick a box, pick an option or a row | select / deselect | cocher / décocher (box), sélectionner (row) | marcar / desmarcar (box), seleccionar (row) | tick, check, uncheck |
| Pick an item in a list or menu | choose | choisir | elegir | select a command, pick |
| Switch a setting | turn on / turn off | activer / désactiver | activar / desactivar | enable, disable, toggle |
| Keep a change | save | enregistrer | guardar | store, record |
| Make something disappear for good | delete | supprimer | eliminar | erase, destroy |
| Take something out of a list, without destroying it | remove | retirer | quitar | delete |
| Make something new | create (an object), add (to a list) | créer, ajouter | crear, añadir | make, generate, new (as a verb) |
| Change something | edit (an object), change (a value, a setting) | modifier | modificar | modify, update (except software updates) |
| Send a file to the tool | import (data), add (evidence) | importer, ajouter | importar, añadir | upload |
| Get a file from the tool | export (data), download (a file) | exporter, télécharger | exportar, descargar | extract, save as |
| Confirm that data is complete | validate | valider | validar | approve (except below), submit, confirm |
| Accept or refuse a request for an overridden value | approve / reject | accepter / refuser | aceptar / rechazar | validate (reserved for data entry) |
| Undo a validation | reopen | rouvrir | reabrir | unvalidate, unlock |
| Show something | show | afficher | mostrar | display (as a verb), view (as a verb) |
| Stop an action | cancel | annuler | cancelar | abort, quit |

Words for things (KPI, framework, campaign, organisation, evidence, reminder…) are in the
[translation glossary](translation_glossary.md), which has one column per language. Add a word there, in every
column, before using it in a new text.

## 6. Words to avoid

| Instead of | Write |
|---|---|
| e-mail | email |
| okay, Ok | OK |
| drop-down, dropdown | list (or the name of the field) |
| tooltip | help |
| user (when speaking to the reader) | you |
| utilise, utilize | use |
| commence, initiate | start |
| additional, further | more |
| prior to | before |
| due to | because of |
| whether | if |
| in order to | to |
| appropriate | correct, applicable |
| corrupted (file) | damaged |
| whitelist / blacklist | allow list / deny list |
| bug, crash | problem, stops |
| kill, abort | stop, cancel |

## 7. Mechanics (English)

| Topic | Rule |
|---|---|
| Spelling | British English (organisation, colour, authorised, centre), as decided |
| Numbers in text | Numerals for all numbers (`3 KPIs`), because they are data. Thousands with a comma (`1,240`), decimal with a point |
| Percentages | `%` with no space (`12.5%`) |
| Units | A space between number and unit (`5 MB`, `120 t CO2e`) |
| Dates | `4 November 2026` in sentences. In tables, the format of the installation |
| Lists | A colon before every list. Items start with a capital. Fragments: no full stop. Full sentences: full stop |
| Steps | A numbered list, one action per step, each step a full sentence |
| Serial comma | Yes: "KPIs, organisations, and campaigns" |
| Quotation marks | “…” for on-screen messages quoted in text and for examples. Not for button names (bold in docs) |
| Ampersand (&) | Only in a name that has one. Otherwise "and" |
| Abbreviations | Spell out on first use in a page if the reader does not know it: `greenhouse gas (GHG)`. Known as is: KPI, PDF, CSV, Excel, N/A, ID |
| Ellipsis | The "…" character. For a text that continues or a loading state (`Saving…`) |

## 8. French, Spanish, and the other languages

The French and Spanish texts follow the same rules (sections 1 to 5): same meaning, same structure, same length as far
as the language allows. They do not add or remove information. Then:

| | French | Spanish |
|---|---|---|
| Form of address | vous | usted (« Haga clic », « Compruebe ») |
| Instructions | imperative (« Saisissez un nombre. ») | imperative with usted (« Capture un valor. », « Introduzca su contraseña. ») |
| Buttons | infinitive (« Exporter vers Excel ») | infinitive (« Exportar a Excel ») |
| Colon, semicolon, ? ! | non-breaking space before (« Total : 3 ») | no space before; ¿ ¡ at the start |
| Quotation marks | « … » with non-breaking spaces | «…» without space |
| Numbers | `1 240,5` (narrow non-breaking space, comma) | `1.240,5` |
| Percentages | `12,5 %` (non-breaking space) | `12,5 %` |
| Dates | `4 novembre 2026`, `04/11/2026` in tables | `4 de noviembre de 2026`, `04/11/2026` in tables |
| Capitals | sentence case (as in English) | sentence case |
| Semicolon | allowed only where English has a list; prefer two sentences | same |
| Variant | French from France | Spanish from Spain |

German, Italian, Dutch, and Portuguese follow the same rules. Their form of address, instructions, buttons, quotation
marks, number and date formats, and spelling are in section 4 of the [translation glossary](translation_glossary.md):
German with "Sie", Italian impersonal, Dutch with "u", and European Portuguese. A native reader must check each of these
four languages before the tool is offered in its country.

## 9. Documentation

From the Google developer documentation style guide:

- **Start with the goal**: the first sentence of a page says what the reader can do with it.
- **Headings** in sentence case, as tasks where possible: "Restore a backup", not "Backup restoration".
- **Procedures**: an introduction ending with a colon, then numbered steps. One action per step. Put the result of a
  step after the action ("Click **Save**. The tool shows the new value.").
- **Prerequisites before the steps**, not in the middle.
- **Notes give information only**, never an instruction. A risk of data loss is a **Warning**, placed before the step.
- **Tables** for comparisons and settings; a sentence before each table says what it shows.
- **Code, commands, file names and paths** in code font: `./update.sh`, `docs/installation.md`.
- **Links**: the link text says where it goes ("see [Installation](installation.md)"), never "click here".

## 10. Check before you commit a text

- [ ] The English is written first, and the six other languages follow it.
- [ ] Every word of a concept or an action is the glossary word (section 5 and `docs/translation.md`).
- [ ] Sentence case. No "please", no "!", no "we", no contraction, no semicolon in English.
- [ ] Buttons: verb first, 3 words maximum. Help: 20 words maximum per sentence.
- [ ] Messages: what happened, then what to do.
- [ ] The same text says the same thing in the seven languages, with the same parameters (`{n}`, `{nom}`). `python3 -I qa/translation_check.py check <language>` reports no error.
