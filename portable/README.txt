Probant - all-in-one version (to try the tool on one computer, no installation, no administrator rights)

TRIAL VERSION: for one person on one computer, to discover the tool. Not for use by several people, and not for
data that you must keep. To use Probant as a team, install it on a server:
https://github.com/Probant-Reporting/probant/blob/main/docs/installation.md

1. Extract the .zip (Windows: right-click > Extract All; Mac: double-click), for example into Documents.
2. Double-click Start.bat (Windows) or Start.command (Mac). A window opens, then the browser opens.
   First start: the window asks what you want to try. Type 1 for the demo (Exemplia, a fictitious company with
   its data) or 2 for an empty tool (you set up your own structure with the setup wizard), then Enter.
   The window shows each step of the start, with a line that moves (bar, share done, elapsed time): the first
   start takes a few minutes, the next ones less. The browser opens when the tool is ready.
3. Demo: the window lists one account per role (admin, validateur, contributeur, lecteur, auditeur), all with the
   password demo-probant-2026. Log out to try another account. Empty tool: the setup wizard opens, and its first
   step creates your administrator account.
4. To stop: close the window.

Folders
-------
data/      the tool's data folder, organised by the tool (see data/README.txt after the first start):
             files/evidence/        evidence files, filed by period > organisation > KPI
             files/settings/logo/   logo of the installation
             files/pending-imports/ files being imported
             backups/               dated backups, restore history, nightly data check
system/    the program (Python and the tool): do not change anything in it

Reset.bat / Reset.command: back to the starting point (deletes your trials). The next start asks again what you
want to try: the demo or an empty tool.

If Windows shows "Windows protected your PC": "More info" > "Run anyway".
If the Mac refuses to open Start.command: System Settings > Privacy & Security > "Open Anyway".
If a message says the program is blocked by your organisation: do not work around it, contact your IT department.
