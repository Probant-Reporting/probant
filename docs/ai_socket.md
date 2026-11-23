# AI socket (optional AI assistant)

Status: built; checked with the fake provider on screen;
**not tried with a real key yet** (section 10). French version: [`docs/fr/prise_ia.md`](fr/prise_ia.md).

The AI socket lets an installation send a small, well-defined piece of data to an AI provider and get back a
**proposal** that a person accepts or not. It is **off by default**. Nothing leaves the installation while it is off.

## 1. Principles

| Principle | How the tool keeps it |
|---|---|
| Off by default | Every space starts with the socket off, no key and every use off (migration `parametres/0033`). |
| Turned on by the administrator, with the client's own key | Administration › Settings › AI assistant, in each space. The key is the client's provider account: the client pays the provider directly. |
| A page says exactly what is sent | The same page lists, for each use, the fields sent and the fields never sent (built from the same constants as the code: `parametres/ia_invites.py`, `ENVOYE`). |
| Nothing leaves while it is off | One function sends (`parametres/ia.py`, `appeler`). It refuses before any network access when the socket, the use or the key is missing, when the IT has blocked the socket, when the daily limit is reached or when the data is too large. No AI button is shown in any of these cases. |
| Every answer is a proposal | Nothing is written by an answer. The person clicks "Use" (copies the text into a field), then saves as usual. |
| Sensitive KPIs stay in by default | One setting per space, **Sensitive KPIs can be sent to the AI assistant**, off by default (migration `parametres/0037`). Off, nothing about a KPI marked Restricted or Confidential, or about a calculated KPI that uses it, leaves by any use (section 6, "Sensitive KPIs"). |

## 2. One interface, several providers

`parametres/ia_fournisseurs.py`:

- `Fournisseur`: `code`, `nom`, `hote` (for the IT), `modeles` (identifier, name), `modele_par_defaut`, and one method
  `demander(requete) -> ReponseIA`. `Requete` holds the key, the model, the fixed instructions, the data block, the JSON
  schema of the expected answer, the output limit, the effort level and the timeout.
- Errors are one class, `ErreurIA(code)`, with a closed list of codes shown to the person in plain words: `cle_refusee`,
  `credit`, `quota`, `surcharge`, `reseau`, `delai`, `refus`, `trop_long`, `modele`, `requete`, `reponse_invalide`.
- Registered providers: `claude` (Anthropic). `factice` (fake, deterministic, no network) exists only in the test suite
  and when the `AI_FAKE_PROVIDER=1` variable is set on a development machine, to check the screens.
- A new provider is one class and one line in `FOURNISSEURS`; the uses and the screens do not change.

### Claude

- Endpoint `POST https://api.anthropic.com/v1/messages`, API version header `anthropic-version: 2026-10-21`.
- **No new dependency**: the call is one HTTPS request made with the Python standard library (`urllib.request`). The
  official `anthropic` package (2.8.0 when checked) would add 13 packages to the image (pydantic, httpx2,
  opentelemetry…) for one endpoint; no heavy dependency is needed when one HTTPS call is enough.
- Models offered (Settings): Claude Fable 5.2 (`claude-fable-5-2`, the most capable, **default**), Claude Opus 5.5
  (`claude-opus-5-5`), Claude Sonnet 5.5 (`claude-sonnet-5-5`), Claude Haiku 5.5 (`claude-haiku-5-5`, the least costly).
  Prices per million tokens, input / output, when checked: 8 / 40 USD, 4 / 20, 2 / 10, 0.10 / 0.50.
- Parameters: no `temperature` (refused by API version 2026-10-21), no `thinking` field (thinking is adaptive by default
  on these models), `output_config.effort` per use, `output_config.format` = JSON schema of the expected answer
  (structured outputs: the answer is valid JSON of that shape), `max_tokens` per use.
- Refusals: `stop_reason: "refusal"` is an error (`refus`), never an answer. On Fable, Opus and Sonnet the request asks
  for the server-side fallback (`anthropic-beta: server-side-fallback-2026-07-01`, `fallbacks: "default"`): a refused
  request is retried by Anthropic on another Claude model inside the same call. If the account does not accept that
  beta header (HTTP 400 that names it), the request is sent again once without it.
- Data retention: Claude Fable 5.2 requires the provider's 30-day retention and is not available to an organisation
  under zero data retention (HTTP 400). Such a client chooses Opus 5.5. The settings page says so next to the model.

## 3. Network: what the IT opens

| Item | Value |
|---|---|
| Direction | Outbound only, from the tool's server (container `web`) |
| Host and port | `api.anthropic.com`, TCP 443 (HTTPS) |
| Proxy | The standard `HTTPS_PROXY` variable is used if it is set (in `.env` with Docker) |
| Kill switch | `AI_SOCKET=off` in `.env` (or the environment of the application): the socket is hidden in every space and no call leaves, whatever the administrators set |

Nothing else changes for the IT: no inbound port, no new service. While the socket is off in a space, the tool opens no
connection to the provider.

## 4. Timeouts, errors, size and daily limit

| Setting (Settings › AI assistant, per space) | Default | Range | Effect |
|---|---|---|---|
| Daily calls | 50 | 1 to 5,000 | Calls per day in the space. The next call is refused before it is sent. A failed call counts (it may have been billed). |
| Maximum size sent | 60,000 characters | 2,000 to 400,000 | Size of the data block of one call. Above it, the call is refused before it is sent, with the size and the limit. |
| Timeout | 60 s | 10 to 110 s | The whole call stops after this time (`delai`), the one retry without the beta header and a slow answer included. The server's request timeout is 120 s. |

- The output of each use is bounded (`max_tokens`: 2,000 for an explanation, 8,000 for matching, 16,000 for
  translations), so the cost of one call is bounded too. Example with Fable 5.2: one call with 60,000 characters (about
  15,000 tokens) in and 2,000 tokens out costs about 0.20 USD; 50 calls a day cost 10 USD at most.
- **Spending cap**: the tool limits the **number of calls**, not money, because it cannot know the client's prices or
  discounts. The client also sets a monthly spending limit in the provider's console (recommended in the guide).
- No automatic retry: a refused or failed call shows its reason, and the person can try again.
- The daily count is read and the call is reserved in one transaction, under the lock of the settings row
  (`select_for_update` on PostgreSQL; SQLite transactions are already "immediate"): two people clicking at the same
  time cannot pass the limit.

## 5. The key

| Question | Choice | Why |
|---|---|---|
| Where is it entered? | Settings › AI assistant, by an administrator of the space | The administrator of the space owns the choice. |
| One key per space or per installation? | **Per space** | The most prudent: each space is a separate department; turning the socket on in one space never makes the data of another space leave, and each space can use its own provider account and budget. |
| Where is it kept? | In a file of the data folder, `ai-keys/<space>.key`, readable by the tool only (mode 600), **never in the database** | A database row would go into every backup of the tool and into the database backups of the host (PostgreSQL add-on). The file is excluded from the tool's backups like `.secret_key`, and is neither replaced nor deleted by a restore. |
| Shown again? | Never | The field is a password field, always empty. The page shows "A key is saved since <date>" and "Remove the key". |
| In the log? | Never | The log says "saved a key" or "removed the key", without the value. The form field is named `api_key` and the view is marked `sensitive_post_parameters`: Django's error reports hide it. The provider errors are written without the request. |
| After a restore on another server | The key is not there: the socket stays set but unusable until an administrator enters the key again | The prudent side: a backup never carries the key. |
| Encrypted at rest? | No: protected by the file rights of the data folder, as `.secret_key` (which would be the encryption key anyway) | Encryption with a key kept in the same folder adds nothing; a real secret store is a decision for later. |

Compared with an environment variable given by the IT (as the SMTP password): the IT would have to set a functional
setting, the key would be the same for every space, and the administrator could not turn it on alone. The variable is
kept for the IT's kill switch only (`AI_SOCKET=off`).

## 6. Uses

Each use has its own switch in Settings, off by default. A button appears only when the socket is on, a key is saved,
the use is on and the person has the right (section 7).

### (a) Explain a consistency alert

- Where: the alert sheet (Consistency page) and the "To check" box of the entry panel, one button "Explain with AI" per
  alert.
- Sent: the language of the answer; the KPI name, its unit and its format; the name of the organisation's level (for
  example "Site"), never its name; the period; the check and its finding as the tool writes it; the value and the
  reference; the values of up to 6 previous periods of the same cell; for a rule between KPIs, the rule name, its
  description, the operator and the name and value of each KPI in it.
- Never sent: organisation names, people, comments, explanations, evidence, other cells.
- Not offered on a "calculation not possible" alert: it is information, there is nothing to justify, and its finding is
  the message of the calculation, which names organisations ("Value not entered: EFF / <organisation>", "Incomplete:
  <organisations>"). No button, and the server refuses the request before anything is sent.
- Answer: a short explanation in plain words (at most 1,200 characters) and up to 3 things to check. Shown in a block
  marked "Proposed by AI", with "Use as my explanation" (copies the text into the explanation field, which the person
  still saves) when the person can justify the alert.

### Sensitive KPIs (all three uses)

A setting per space, **Sensitive KPIs can be sent to the AI assistant**
(Settings › AI assistant, under the uses), **off by default**, written in the History (`reglage_ia`, field
`ia_kpi_sensibles`). The assistants (MCP) have the same kind of setting, but on by default (`docs/mcp.md`).

"Sensitive" has one definition for the two doors (`collecte/sensibles.py`, used by `serveur_mcp/outils.py` too): a KPI
marked **Restricted** or **Confidential** on its KPI sheet, and every calculated KPI that uses one, directly or through
another formula (`[S] * 1`, `[A] / [S]`, `[S@N-1]`, a formula that cites such a formula). An alert is sensitive when its
cell is such a KPI, or when its rule names one on either side (the KPIs noted when the alert was found, or named by the
rule today).

| Use | Setting off (default) | Setting on |
|---|---|---|
| (a) Explain an alert | No "Explain with AI" on a sensitive alert (alert sheet, entry panel); the server refuses the request before anything is sent ("This alert names a sensitive KPI…"). The other alerts are sent as before: none of their data is about a sensitive KPI | As before: the values, previous values and rule of these KPIs are sent |
| (b) Match the KPIs of a former file | The sensitive KPIs and the KPIs calculated from them are left out of the list of the tool's KPIs sent (code, name, unit): the AI never proposes them; the administrator matches them by hand. The labels of the former file still leave: they are labels, not values, and the tool cannot know which one is sensitive before the match | As before |
| (c) Translate the labels of a language | In the "KPI names" and "Descriptions" sections, the name and the descriptions of these KPIs are not sent; they stay empty, to translate by hand. When only such texts are left on the page, the answer says so. Themes and setting labels are not about a KPI: unchanged | As before |

**Update of an existing installation**: the setting arrives **off**. An installation that had turned the AI assistant
on loses "Explain with AI" on the alerts of sensitive KPIs (and their derived KPIs and rules), and these KPIs leave the
matches and translations, until an administrator turns the setting on.

### (b) Match the KPIs of a former file (data migration wizard)

- Where: Administration › Configuration files › Data migration, step "Match", button "Propose with AI".
- Sent: the labels of the former file that are not matched yet (at most 150 per call), with the name or unit read next
  to them; the tool's KPIs: code, name, unit.
- Never sent: values, organisations, periods, comments, the file itself.
- Answer: for each label, a KPI code (only a code that was sent; any other is dropped) or nothing, with a short reason.
  Shown in the "Proposal" column, marked AI, with "Use" per row and "Use all". The match is saved only by the wizard's
  usual button.

### (c) Translate the labels of a language

- Where: Settings › Languages › Translations of a language, button "Propose with AI" for the texts still empty on the
  page (at most 60 per call).
- Sent: the starting language and the target language; for each text, a number, its kind (KPI name, description,
  theme, label) and the starting text.
- Never sent: the technical keys, the other languages, anything else.
- Answer: a proposed translation per number (only numbers that were sent). Shown under each field, marked AI, with
  "Use" per row and "Use all". Saved only by the page's "Save" button.

## 7. Rights

| Use | Who can ask | Why |
|---|---|---|
| (a) Explain an alert | Administrator, validator, contributor, for an alert they can see (same rule as the Consistency page, `coherence.peut_voir`) | The person already sees every figure sent. |
| (a) for reader and auditor | **No** | A request writes a log line and counts against a paid limit; `collecte/lecture_seule.py` refuses every write of these roles except their own preferences. Reserved to the roles that write (product choice to confirm, section 9). |
| (b) Data migration | Administrator (the wizard is theirs) | Same rights as the page. |
| (c) Translations | Administrator (Settings) | Same rights as the page. |
| Settings › AI assistant | Administrator of the space | Same rights as the other Settings pages. |

## 8. Log and untrusted text

- **Log**: every call writes one line in the History before it is sent: who, which use, when, provider, model and size
  sent in characters; never the content sent nor the answer. Action `ia_appel`, family "AI assistant". Turning the
  socket or a use on or off, the settings and the key (saved or removed, never its value) write `reglage_ia` lines.
- **The answer is untrusted data**: it is read as JSON of a fixed shape; any other field is dropped; texts are cut to
  their limit and stripped of control characters; it is shown escaped (Django escaping, `textContent` in scripts),
  never as HTML or Markdown, never run, and it never triggers an action: only the person's click does.
- **The data sent can hold an injection attempt** (a KPI name or a former label written by anybody): the instructions
  are fixed and come first; the data is one JSON block between `<data>` and `</data>`, with `<` and `>` escaped so
  that a value cannot close the block; the instructions say that the data block holds no instructions. The answer has
  no power: a match is one of the codes sent, a translation is one of the numbers sent, an explanation is text.

## 9. Open product choices

The principle is settled. Every other product choice is listed here with what is in place meanwhile (always
the most prudent) and the recommendation.

| # | Question | In place meanwhile | Recommendation |
|---|---|---|---|
| IA1 | Default model: Fable 5.2 (most capable, 8 / 40 USD, 30-day retention required) or Opus 5.5 (half the price, very good for these short tasks)? | Fable 5.2, the administrator can choose another | Opus 5.5 by default: these uses are short, and Fable is refused under zero data retention |
| IA2 | Can the auditor (and the reader) ask for an explanation? | No (roles that write only) | Yes for the auditor later, once a request is accepted as "not a write" in the read-only rule |
| IA3 | Send the organisation name with an alert? | Never: only its level | Keep it out |
| IA4 | Limit by number of calls or by money? | Calls per day per space (50) | Keep calls, and tell the client to set a monthly limit in the provider console |
| IA5 | One key per space or one for the installation? | Per space | Keep per space |
| IA6 | Proposals for the organisations of a former file (b)? | KPIs only | Add later if asked |
| IA7 | Keep a copy of the answers (audit trail of what the AI proposed)? | No: only the log line | Keep it out (privacy), unless an audit need is stated |
| IA8 | The text "Proposed by AI" names the provider ("Proposed by AI (Claude)")? | Yes | Keep it |

## 10. What was not tested

No real call was made: there was no key, and the test suite never calls the network (the Claude provider refuses any
connection while the tests run). To try with a real key:

1. The exact answer of the API to the request built by `FournisseurClaude` (structured output, effort, fallback header)
   on each of the four models.
2. A refused key (401), an account without credit (400 or 402), a rate limit (429), a model refused under zero data
   retention (400).
3. The time of a translation call of 60 texts and of a matching call of 150 labels with Fable 5.2, against the 60 s
   default timeout.
4. The quality of the three uses in each of the seven languages of the interface (the request names the language of the answer: French, English, Spanish, German, Italian, Dutch, or Portuguese). Only the language of the person's interface is ever asked for.
5. A proxy (`HTTPS_PROXY`) and a closed firewall (the message "network").

## 11. Files

| File | Role |
|---|---|
| `parametres/ia.py` | The socket: state, key file, daily limit and log, the one function that sends |
| `parametres/ia_fournisseurs.py` | Interface, Claude, fake provider |
| `parametres/ia_invites.py` | The three uses: data sent, instructions, schema, checks of the answer, list shown on the settings page |
| `collecte/sensibles.py` | Sensitive KPIs and the KPIs calculated from them, sensitive alerts: one definition for the AI socket and the assistants (MCP) |
| `parametres/migrations/0037_ia_kpi_sensibles.py` | The setting "Sensitive KPIs can be sent to the AI assistant" of each space (off) |
| `parametres/vues_ia.py` | Settings › AI assistant; translation proposals |
| `collecte/vues_ia.py` | Explanation of an alert; matching proposals of the data migration wizard |
| `parametres/migrations/0033_prise_ia.py` | The settings of each space (all off) |
| `collecte/templates/collecte/_app/12b_ia.js` | Buttons, proposals, "Use" and "Use all" (page script) |
| `collecte/templates/collecte/_ia_explication.html`, `parametres/templates/parametres/ia.html` | The proposal of an explanation; the settings page |
| `parametres/aides_tests/ia.py` | Test helper: key folder per test, fake provider reset, socket turned on in one line |

## 12. Proofs

| What | Test |
|---|---|
| Request built for Claude (headers, body, no `temperature`), errors in plain words, fallback without the beta header, no network during the tests | `parametres/test_fournisseur_claude.py` |
| One time limit for the whole call: the retry without the beta header has only the time left, a slow answer is stopped at the limit | `parametres/test_demander_claude_robustesse.py` (`DelaiTotalTests`) |
| A cut or malformed HTTP answer, or a token count that is not a number, is a plain error ("The provider's answer could not be read"), never a server error | `parametres/test_demander_claude_robustesse.py` |
| Nothing leaves while off (socket, use, key, IT kill switch, unknown provider), size limit, daily limit (a failed call counts), log line without content, answer checked, data block escaped | `parametres/test_appeler_ia.py` |
| Two simultaneous requests never pass the daily limit | `parametres/test_appeler_ia_simultane.py` (real threads on PostgreSQL; fails without the row lock); on SQLite, two real processes on a file database: one call, one refusal (checked by hand) |
| Key: file mode 600, never in a table, never shown again, hidden from error reports, never backed up, untouched by a restore, one per space | `parametres/test_cle_ia.py` |
| Settings page: administrator only, no turning on without a key, log of each change, bounded limits, what is sent (text of the page in every language of the interface), IT kill switch | `parametres/test_reglages_ia.py` |
| Explanation: no button while off, rights (reader and auditor refused, alert out of scope refused), what is sent, answer escaped and marked, nothing saved | `collecte/test_alerte_ia.py` |
| No organisation or person name of the database is sent, for a real alert of each check and for each use; no button and a refusal for a "calculation not possible" alert | `collecte/test_appeler_ia_sans_noms.py` |
| Matches and translations: buttons, what is sent, codes and numbers not sent are dropped, nothing saved | `collecte/test_reprise_ia.py`, `parametres/test_traductions_ia.py` |
| Sensitive KPIs, setting off (default): recognisable sensitive values, every alert explained or refused, alert sheets and entry panels, matches and translations: none of these numbers, names or descriptions in what the fake provider receives; no button and a refusal on a sensitive alert (direct, rule, derived KPI); setting on: as before | `collecte/test_appeler_ia_kpi_sensibles.py` |
| New routes in the sweep of rights by role | `collecte/test_droits_balayage.py` (`test_assistant_ia_dans_le_balayage`) |
