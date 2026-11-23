# Calculation and data entry rules

This page gives the rules that Probant follows to calculate totals and formulas, and the rules of data entry,
validation, campaigns, and files. It is for administrators, validators, and auditors who must explain a figure. To learn
the screens, see the [guides by role](guides/README.md).

## 1. Organisations and periods

### Tree and granularity

- You set the levels of the tree in **Administration › Settings › Levels of the tree** (rank 1 is the top). You can
  attach an organisation to any level above its own.
- Each KPI has a **granularity**: the level where people enter it.
- Below its granularity, an inherited parameter (for example, an emission factor) comes from the ancestor
  organisation at that level. If no ancestor has that level, the organisation that has no ancestor of the right level
  carries it.

### Organisations open during a period

An organisation is **open during a period** when both conditions are true:

- It has no opening date, or it opened on or before the last day of the period.
- It is active, or it was deactivated after the start of the period.

So a closed site counts in the years when it was open, and a new site counts only from its opening date ("Open since"
on its sheet). An organisation is never open before the organisation above it: the opening date of an entity also
applies to its sites.

The same rule gives the cells to fill in, the reminders, the completion rate, the file to fill in, the exports, the
detail of a total, the consistency checks, and the AI assistants. The tool refuses a value for an organisation that is
not open during the period, and says why.

Changes to organisations:

- When you deactivate, move, or create an organisation, the tool recalculates the campaigns that are not closed.
- You cannot deactivate an organisation that still has collected organisations below it. Deactivate or move them first.
- The organisation sheet refuses an opening date after the closing date. If values exist before the new opening
  date, the sheet shows how many, and saves only after you confirm. These values then count in no total.

## 2. Aggregation in the tree

Above its granularity, the **aggregation** of the KPI gives the value:

| Aggregation | Result |
|---|---|
| **Sum** | Adds up the direct child organisations that are open during the period. |
| **Formula** | Calculates the formula again on the sources that are already aggregated (for ratios). |
| **Count** | For a yes / no or list answer: the number of answers for each value. |
| **None** | No value above the granularity. |

A sum follows these rules:

- It does not count the children attached below the granularity of the KPI.
- It excludes N/A values. If all the values are N/A, the result is N/A.
- A child without a value makes the result **incomplete**. Exception: a child that has no organisation at the level of
  the KPI below it (for example, a country just created).
- A closed site with no value at all in the period does not make the total incomplete. If it has another value in
  the period, a missing value makes the total incomplete.
- Percentages are never added up: the tool refuses the **Sum** aggregation for them. Use **None**, or a calculated KPI
  with the **Formula** aggregation.

### Entry at higher levels

**Entry at higher levels** is an option of the KPI sheet. When the detail is missing, an administrator or a validator
enters the value above the granularity (for example, for a country):

- This value replaces the calculated total and rolls up as it is.
- The organisations below are no longer expected (completion rate, reminders). You can still enter their values.
- If their complete sum differs from the value by more than 0.5%, a "Variance with the detail" alert appears.
- If you clear the value, the calculated total comes back.

## 3. Formulas

### References

| Reference | Value read |
|---|---|
| `[ID]` | The KPI in the same period and organisation |
| `[ID@P-1]` | The previous period of the same type (February for March, December 2025 for January 2026) |
| `[ID@N-1]` | The same period of the previous reporting year (March 2025 for March 2026) |
| `[ID@2021]` | The same period (same rank) of the reporting year that starts in 2021 |

With a reporting year that starts in another month (for example, July to June), `[ID@2021]` follows the same logic as
`[ID@N-1]`: in the year 2022/23, it reads 2021/22. A missing period gives a missing value, and the message names the
target period.

A formula that reads another period reads nothing for an organisation that was not open during that period: the
source is missing and the result is incomplete. An inherited parameter is still read at the organisation that carries
it, if that organisation is open.

### N/A, missing values, and errors

- An N/A source makes the result N/A. Exception: with the option **N/A, counted as 0** of the KPI sheet, an N/A source
  counts as 0, and the result is N/A only if all the sources are N/A. The tool offers this option for a formula that
  is only a sum.
- To keep a total calculable, enter 0 rather than N/A when there is nothing to report.
- A missing source makes the result incomplete.
- 0 / 0 gives 0 (nothing to report). Any other division by zero gives an error. Dividing by an N/A source gives N/A.
- A result too large to be stored (more than 15 digits before the decimal point) is an error.
- In a closed period, a figure imported as is (for example, from a former system) is the official figure. The
  formulas and totals that cite it use it. It never replaces a total that the tool can calculate.
- A figure imported as is on a calculated cell of a period that is not closed (data from before overridden values
  existed for imports) is used only when the calculation is not possible. **To be handled** lists these figures for
  the administrator, who forces them or removes them on the **Overridden values** page. If the period is closed
  first, the figure becomes the official one. At the closure, the periods that are not closed and that cite it
  (`[ID@N-1]`, `[ID@P-1]`, `[ID@2021]`) are calculated again at once. The closed period itself does not change: a total
  above the figure keeps the value calculated while the period was open. A closed period that cites it does not change.

### Numbers on screen

- Percentages are stored as fractions (0.25 = 25%). You enter them from 0 to 100.
- Numbers are rounded on screen as Excel rounds them, with the decimals of the unit. A unit "Whole number" has 0
  decimals.

## 4. Recalculation

- Any entry starts the calculation of the KPIs that depend on it, also in the periods that cite it (`[ID@P-1]`,
  `[ID@N-1]`, `[ID@2021]`) and in the longer periods that add it up.
- A KPI that cites itself in the previous month (like a stock) is calculated again in all the next months that are
  not closed.
- The recalculation never overwrites an imported value.
- When a KPI becomes calculated, the result of its formula replaces its entries in the campaigns that are not closed.
  The old value stays in the history.
- A period calculates only the KPIs of its campaigns, with the sources of their formulas. A month without a campaign
  calculates nothing.

### Closed periods

A period is **frozen** when all its campaigns are closed. Its figures do not change: formulas such as `[ID@N-1]`, the
Visualisation, and the exports read its saved values.

- The tool records the scope (the KPIs asked for) and the organisation tree of a period at its closure. A closed year
  is always calculated and shown with the tree of that day. A total shown is the sum of the detail shown.
- A KPI or a library template added later gets no cell in a closed period.
- A correction imported into a closed campaign recalculates only the corrected organisation and its totals above.
- With two campaigns on the same period, one closed: the KPIs of the closed campaign, and the sources of their
  formulas, keep their figures until the other campaign is closed. Their entry is blocked in the open campaign, with a
  message.

### Reopening a closed year

When you reopen a closed year, you choose:

| Choice | Effect |
|---|---|
| **Keep the figures of the time** (default) | Nothing is recalculated. Until the next closure, only an organisation whose value you correct, and the totals above it, are recalculated, with the tree of the closure. |
| **Recalculate with today's organisation** | The year is calculated again with today's tree, formulas, and settings. An entity moved since then moves its values to its new parent. |

The history records the choice.

### "Requested since"

Each KPI of a framework has a **Requested since** period: the first period in which the framework asks for it.

- Empty means "since the start".
- A KPI added to a framework is asked for from the current period, unless you choose an earlier period.
- Moving the date earlier adds the cells to the periods in progress or reopened. A closed year gets the KPI only at
  its reopening.
- Moving the date later is refused if a period that would lose the KPI is closed, or has a value, an N/A, a comment,
  or evidence for it.

## 5. Aggregation over time

**Aggregation over time** is a setting of the KPI sheet. A KPI entered in a more frequent framework (for example,
monthly) is calculated in the longer periods that contain it (quarter, half-year, reporting year):

| Setting | Result |
|---|---|
| **Sum** (default) | The sum of the sub-periods |
| **Average** (default for a percentage) | The average of the sub-periods |
| **Last value** (default for an emission factor, yes / no, list) | The value of the last sub-period |
| **None** | The KPI is entered separately at each frequency |

- The KPI is cumulated at its granularity, then aggregated in the tree as usual.
- Only the sub-periods that have a cell count: the organisation is open, and a framework asks for the KPI. A site
  closed on 30 June that enters 1 per month from January to June has 6 for the year.
- A missing sub-period (one that has a cell) makes the cumulation incomplete.
- A value entered or imported directly in the long period has priority. The tool never overwrites it.

## 6. Consistency checks

The rules between KPIs and the automatic checks (variance with N-1, outside history, format, series break) apply to
the organisations open during the period.

- Automatic alerts never block validation. The contributor justifies, and the administrator decides.
- Only the rules between KPIs marked "blocking" prevent validation.
- "Outside history" means a value above *threshold* × the median of the previous reporting years, or below
  median ÷ *threshold*. It needs at least 3 values. The threshold is set per campaign (2 by default).
- An alert disappears by itself when the entry is corrected. It comes back if the value changes after a decision.
- Once a campaign is closed, only an administrator handles its alerts.
- A rule on a percentage is written as a fraction (`[TX] <= 0.3`).
- One rule is one condition. Two rules with the same condition (same parts, letter case included, operator, tolerance,
  and level) are checked once, whatever their names: a template does not create a rule that already exists under another
  name, and only one alert shows for a violation.
- A rule of a library template is stored in the reference language of the installation. Its name and its explanation
  show in the language of the reader (then English, then French) while they are the text of the template.
- There is no N-1 value when the organisation was not open during the compared period, or when the KPI was outside the
  scope of that period.

## 7. Data entry and validation

### Who enters what

- The contributor gets the cells assigned to them.
- The validator gets, for each KPI assigned to them, the cells of that KPI in the organisation and the organisations
  below it.
- The administrator gets all the expected cells.
- Calculated KPIs are never entered.
- Readers and auditors never change anything.

### Statuses

A value has one of three statuses: **To fill in** (no value and no N/A), **Draft**, or **Validated**.

- Any change to a validated answer (value, N/A, comment, evidence) puts it back to draft. The history records every
  change.
- To validate, you give a value or N/A. You must also give a comment if you select N/A, or if the variance with the
  comparison period exceeds the variance threshold of the campaign. If the KPI requires evidence, you add at least one
  file (except for N/A).
- The contributor confirms that the entry is complete, not that it is exact. An administrator can reopen a value.
- **Back to draft** puts a validated answer back to draft without changing it (administrator; validator after the end
  date).
- **Clear the value** empties a cell after a confirmation. The comment and the evidence stay.

### Numbers

- You can use a comma or a point. With both, the last one is the decimal separator. A repeated separator is the
  thousands separator.
- A single separator followed by exactly 3 digits ("1,234", "12.500") is ambiguous. The entry panel asks which reading
  you mean before it saves. An import reads it in the language of the file (see "Import values") and shows a warning
  with the reading it made.
- A group of thousands starts with a digit from 1 to 9: "0,205" is always zero point two zero five, in every language,
  and "0,205,123" and "0,205.5" are not numbers (same reading on the server and in the browser).
- A year (unit "year") never has a thousands separator: 2028, in every language, on screen and in files.

### Answer formats

| Format | Rules |
|---|---|
| Number, percentage | Used in formulas and sums (percentages: not in sums) |
| Yes / no, list | Text answers; no N-1 variance; "Count" above the granularity; never in a formula |
| Written text | Markdown, 20,000 characters at most; HTML is shown as text; never in a formula, a sum, or a check |
| Table | A variable number of rows, columns of numbers, texts, or lists; saved as a Markdown table |

### Campaigns

A campaign covers one framework and one period. It goes through these statuses:

1. **In preparation**.
2. **Open for data entry**: contributors and validators enter values between the dates. After the end date,
   contributors can only read.
3. **Review**: only the administrator makes changes.
4. **Closed**: frozen for everyone. Its values become the N-1 of the next period.

A KPI shared by two frameworks with the same frequency is entered once. A cumulated value (for example, the year of a
monthly KPI) is read-only: you enter it in the campaigns of the most frequent framework.

### Closing certificate

A closed campaign has a page to print, the **closing certificate** (Administration › Campaigns, then the campaign, then
**Closing certificate**; for an auditor, the list at the top of **History**). It is for administrators and auditors. It
only reads data. Nothing is saved, and the fingerprint is computed again each time the page opens.

The page shows the campaign, its framework and period, who closed it and when (only if the history of the installation
keeps it; the tool never invents it), the reopenings and their mode, the scope (organisations of the tree of the
closing, by level, and those open in the period), the completion rate, the number of values (entered or imported,
calculated, overridden, validated, N/A), the evidence files, and the consistency alerts (handled, justified, still
open, with the short list of the open ones).

**Fingerprint.** It is a SHA-256 hash of the figures of the campaign. The hashed text is in UTF-8, one line per item,
lines separated by a line feed:

1. A header line: the JSON array `["probant-certificat-1", framework code, first day of the period, last day of the
   period]` (dates as `YYYY-MM-DD`).
2. One line per cell that holds a value, a text, or N/A, sorted by KPI code and then by organisation code: the JSON array
   `[KPI code, organisation code, value, N/A, text]`. The value is the decimal number without useless zeros (`110`,
   `0.5`) or `null`. N/A is `true` or `false`. The text is the answer as saved (list, yes or no, written text).

The KPIs are those of the framework of the campaign and the sources of their formulas. Empty cells are not hashed. The
status, the author, and the dates are not hashed: the fingerprint is about the figures, not about how they were entered.
If a single figure changes, the fingerprint changes. To check a figure later, open the certificate again and compare the
fingerprints.

**Partial certificate.** An auditor limited to some organisations gets a partial certificate. The top of the page and the
header of each printed page say "Partial certificate: N of M organisations" and name the organisations at the top of
what the auditor can see. The scope is the same as on every other page for this auditor: the organisations chosen for
the account and all the organisations below them. Every figure counts only these organisations: scope by level,
completion rate, values, evidence files, and alerts. The organisations above them are not in the scope, so their totals
are never counted. M (the number of organisations open in the period in the whole campaign) is the only figure about the
whole campaign.

The fingerprint of a partial certificate uses only the cells of these organisations, and its header line is
`["probant-certificat-1-partiel", framework code, first day of the period, last day of the period, [codes of the
organisations at the top of the scope]]`. It is therefore always different from the fingerprint of the full
certificate. Compare it only with the fingerprint of another partial certificate for the same organisations.

### Evidence of sensitive KPIs

- A KPI marked "Restricted" or "Confidential" is **sensitive**.
- In **Settings › Hosting**, an administrator can set a retention period for the evidence of sensitive KPIs.
- **Administration › History › Evidence to delete** lists the files whose period ended more than that period ago, when
  all its campaigns are closed. Nothing is deleted by itself: an administrator deletes after a confirmation, and the
  history records the deletion.

## 8. Files

### Files that the tool makes

- A "Read me" tab comes first. Yellow cells are to fill in, grey cells are keys not to change, white cells are
  information.
- Numbers have the decimals of the unit. Percentages go from 0 to 100.
- Each person exports only their scope, in the language of their choice.

| Export layout | Content |
|---|---|
| **Database** | Tables of values, indicators, and organisations, linked by "KPI ID" and "Organisation code". You can import the file again as it is. |
| **Readable table** | One row per organisation, themes as groups, N-1 as an option, printable. Calculated values can be Excel formulas. |
| **Review report** | Progress summary, then one organisation per printed page. |
| **Audit file** | For administrators and auditors. One row per KPI and organisation with the value, the status, who entered and validated it, any overridden value, the evidence, the alerts and their justifications. The tabs **History** and **Evidence** list the changes and the evidence files of these cells. It only reads data. |

### Import values

- The tool recognises the columns by their name, in the first 15 rows.
- It recognises organisations by their name, their code, or an import label.
- An empty cell erases nothing.
- The tool ignores totals of entered KPIs: it calculates them again.
- Numbers: a cell that holds an Excel number is read as it is. A number written as text (a CSV file, or a text cell)
  is read as the entry panel reads it in the language of the file:
  - In a CSV file separated by ";" or ",", the separator decides: ";" goes with a decimal comma, "," with a decimal
    point. The tool writes its CSV files this way.
  - Otherwise, the language of the header of the value column ("Value", "Valeur", "Wert"…): the files that the tool
    makes write this header in the language of the export. In English, "1,234" is 1234; in the other languages, it is
    1.234.
  - If neither shows how to read numbers, the tool uses the language of your interface.
  - The preview shows how the numbers were read. A text that is not a number in that language (for example "0,205.5")
    is rejected with a message.
  - The "Migrate a former system" wizard reads numbers written as text in the language of your screen.
- Calculated KPIs: in a closed period, the tool ignores them. In a period that is not closed, a figure that differs
  from the calculated result is shown in the preview, and you must choose **Force these values** or **Ignore these
  rows**. If you force them, each figure becomes an overridden value (same rights, history, and page as an overridden
  value set in the entry panel), and the totals and the formulas that use it, other periods included, are calculated
  again. Only an administrator, or a validator of the organisation while entry is open, can force a calculated value;
  for anyone else, the row is rejected.
- In an open campaign, the rights and checks are the same as on screen.
- In a closed campaign, only the administrator imports. An import never replaces a value entered in the tool.

### Organisation code

The organisation code is the stable identifier of the exports. The tool makes it from the name at creation. It is
unique, and it stays the same when you rename the organisation.

### Configuration and framework files

- An import deletes nothing. A missing KPI can only be deactivated, on request.
- A KPI with the same code and the same definition is reused. If it differs, you choose: reuse, rename, or ignore.
- The import of the configuration file is all or nothing.
- An answer format does not change when the KPI has answers. The unit of a KPI does not change either.
- Each space has a reference currency (the euro by default). A library template written in euros takes this currency
  when you install or update it ("M€" becomes "M$"). A KPI that already exists in the space keeps its unit, with or without values. No value is converted.
- The EFRAG official workbook uses the reference currency as the currency of the report. An amount whose unit is not
  the unit of the template in this currency stays empty, and the export report says so.

## 9. Languages

- The reference texts are the texts entered in the forms, in the reference language of the installation. The other
  languages are translations.
- A missing text shows in the default language, then in the reference language.
- The interface is available in seven languages. A language is offered only when it is complete. See
  [Interface translation](translation.md).
