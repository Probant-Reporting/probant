"""All-in-one version (Windows / Mac): starts the tool on its data folder and opens the browser.

Package layout (built by portable/build_package.py):
    README.txt, Start.bat / Start.command, Reset.bat / Reset.command
    data/      the tool's data folder, organised by the tool itself (parametres/rangement.py)
    system/    Python, libraries, the tool (app/), this launcher and package.json

package.json says what the package holds:
    {"mode": "demo"}                         empty data folder: the first start asks what to prepare, the demo
                                             (admin / demo-probant-2026) or an empty tool (the setup wizard opens)
    {"mode": "data", "login": "..."}         a data folder already filled with the tool (an installation's copy):
                                             the start only applies the tool's updates (migrations), like any update
Reset (Reset.bat / Reset.command, i.e. ``launch.py --reset``): restores the starting point with the tool's own restore
(the archive data/backups/backup-…-initial.zip, the same as Settings › Hosting › Restore), or empties the data folder:
the next start asks the question again.
Progress: each start shows numbered steps (loading the program, the database, the demo data, starting the tool), each
with a line that moves (bar and share when the share is known, elapsed time, a turning sign), so that a slow first start
never looks stuck. The final message lists the demo accounts, one per role, with their shared password.
Close the window to stop the tool. Messages are in English, like the rest of the tool's messages for IT.
"""
import json
import math
import os
import shutil
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

SYSTEM = Path(__file__).resolve().parent
ROOT = SYSTEM.parent
DATA = ROOT / "data"
READY = DATA / ".package-ready"
LAYOUT = ["files/evidence", "files/settings/logo", "files/pending-imports", "backups"]
# comptes de démo (collecte/management/commands/_exemplia.py, COMPTES), un par rôle, et leur mot de passe commun
DEMO_PASSWORD = "demo-probant-2026"
DEMO_ACCOUNTS = [
    ("admin", "Administrator: settings, campaigns, everything"),
    ("validateur", "Validator: checks and validates the values entered"),
    ("contributeur", "Contributor: enters the values and adds evidence"),
    ("lecteur", "Reader: views and dashboard, read only"),
    ("auditeur", "Auditor: everything needed for an audit, read only"),
]
# démo : part du travail faite à chaque ligne écrite par load_demo (organisations et modèles, 2024, 2025, 2026, ESRS,
# fin), mesurée sur un poste ; une ligne en plus ou en moins ne casse rien (la barre reste bornée)
DEMO_MILESTONES = [0.30, 0.36, 0.43, 0.50, 0.97, 1.0]
STOP = threading.Event()  # posé quand le lanceur s'arrête sur une erreur : les lignes qui bougent s'arrêtent


def demo_login():
    """Message des comptes de démo : un compte par rôle, le même mot de passe pour tous."""
    lines = [f"Demo accounts (the same password for all: {DEMO_PASSWORD})"]
    lines += [f"    {name:<14}{role}" for name, role in DEMO_ACCOUNTS]
    lines.append("Log out to try another account.")
    return "\n  ".join(lines)


def clock(seconds):
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


class Step:
    """Une étape numérotée, avec une ligne qui bouge tant qu'elle dure : barre et part du travail quand on la connaît,
    temps écoulé et signe qui tourne sinon. Sans console (fichier, test), seulement le titre et la fin de l'étape."""

    SPIN = "|/-\\"
    WIDTH = 24
    CREEP = 20

    def __init__(self, number, total, label, out=None):
        self.number, self.total, self.label = number, total, label
        self.out = out or sys.stdout
        self.share = None  # 0 à 1, ou None (inconnue)
        self.toward, self.since = None, time.monotonic()
        self.detail = ""
        self.live = bool(getattr(self.out, "isatty", lambda: False)())
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self.start = time.monotonic()

    def update(self, share=None, detail=None, toward=None):
        """``toward`` : part du prochain jalon ; la barre s'en approche peu à peu sans jamais l'atteindre."""
        with self._lock:
            if share is not None:
                self.share = max(0.0, min(1.0, share))
                self.toward, self.since = toward, time.monotonic()
            if detail is not None:
                self.detail = detail

    def shown(self):
        """Part affichée : la part atteinte, plus une avance qui ralentit vers le prochain jalon (``CREEP`` secondes)."""
        with self._lock:
            share, toward, since = self.share, self.toward, self.since
        if share is None or toward is None or toward <= share:
            return share
        return share + (toward - share) * (1 - math.exp(-(time.monotonic() - since) / self.CREEP))

    def line(self, tick=0):
        elapsed = clock(time.monotonic() - self.start)
        share = self.shown()
        with self._lock:
            detail = self.detail
        if share is None:
            text = f"      working {self.SPIN[tick % 4]}  {elapsed}"
        else:
            full = int(round(share * self.WIDTH))
            text = f"      [{'#' * full}{'.' * (self.WIDTH - full)}] {int(share * 100):3d}%  {elapsed} {self.SPIN[tick % 4]}"
        return f"{text}  {detail}"[:76]

    def _write(self, text):
        try:
            self.out.write(text)
            self.out.flush()
        except (OSError, ValueError):
            pass

    def _run(self):
        tick = 0
        while not self._stop.wait(0.25) and not STOP.is_set():
            tick += 1
            self._write("\r" + self.line(tick).ljust(78))

    def __enter__(self):
        self._write(f"\n  [{self.number}/{self.total}] {self.label}\n")
        if self.live:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, kind, error, trace):
        self._stop.set()
        if self._thread:
            self._thread.join()
            self._write("\r" + " " * 78 + "\r")
        end = "done" if kind is None else "stopped"
        self._write(f"      {end} ({clock(time.monotonic() - self.start)})\n")
        return False


class Lines:
    """Flux de sortie d'une commande : chaque ligne complète est passée à ``on_line``, rien n'est affiché."""

    def __init__(self, on_line):
        self.on_line, self.rest = on_line, ""

    def write(self, text):
        self.rest += text
        *complete, self.rest = self.rest.split("\n")
        for line in complete:
            self.on_line(line)
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False

os.environ.update(DATA_DIR=str(DATA), DJANGO_DEBUG="1", PYTHONUTF8="1", DJANGO_SETTINGS_MODULE="config.settings")
for name in ("SPACE", "ESPACE"):
    os.environ.pop(name, None)
sys.path.insert(0, str(SYSTEM / "app"))


def package():
    try:
        return json.loads((SYSTEM / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"mode": "demo"}


def organise():
    for d in LAYOUT:
        (DATA / d).mkdir(parents=True, exist_ok=True)


def empty_data():
    """Empties the data folder (interrupted preparation of a demo), keeping its layout."""
    for x in DATA.iterdir() if DATA.exists() else []:
        shutil.rmtree(x) if x.is_dir() else x.unlink()
    organise()


def initial_backup():
    found = sorted(DATA.glob("backups/backup-*-initial.zip"))
    return found[0] if found else None


def starting_point(ask=input, forced=None):
    """What the first start prepares: "demo" (the default) or "empty".

    PROBANT_START=demo or empty answers in place of the person (a start with no keyboard, a test).
    """
    forced = (forced if forced is not None else os.environ.get("PROBANT_START", "")).strip().lower()
    if forced in ("demo", "empty"):
        return forced
    print("  What do you want to try?")
    print("    1. The demo: Exemplia, a fictitious company, with its data (recommended)")
    print("    2. An empty tool: you set up your own structure with the setup wizard")
    for _ in range(3):
        try:
            answer = ask("  Type 1 or 2, then Enter [1]: ").strip().lower()
        except EOFError:
            return "demo"
        if answer in ("", "1", "demo"):
            return "demo"
        if answer in ("2", "empty"):
            return "empty"
    return "demo"


EMPTY_LOGIN = "No account yet: the setup wizard opens. Its first step creates your administrator account."


def login_text(saved):
    """Message des comptes gardé dans ``.package-ready`` : « demo », « empty », ou un texte (paquet d'une installation,
    ou démo préparée par une version d'avant du lanceur : son mot de passe la fait reconnaître)."""
    if saved == "demo" or DEMO_PASSWORD in saved:
        return demo_login()
    if saved == "empty":
        return EMPTY_LOGIN
    return saved


def planned_migrations():
    """Nombre de migrations à appliquer (base principale et registre commun) ; None si on ne sait pas le compter."""
    try:
        from django.db import connections
        from django.db.migrations.executor import MigrationExecutor

        from espaces import contexte as E

        total = 0
        for alias in ("default", E.COMMUN):
            executor = MigrationExecutor(connections[alias])
            total += len(executor.migration_plan(executor.loader.graph.leaf_nodes()))
        return total
    except Exception:
        return None


def migrate(step):
    """Les migrations de l'outil, comptées une à une sur la ligne de l'étape."""
    from django.core.management import call_command

    total = planned_migrations()
    done = 0
    step.update(0.0 if total else None, "checking" if total == 0 else "")

    def on_line(line):
        nonlocal done
        if "Applying " in line:
            done += 1
            step.update(min(done / total, 0.99) if total else None, f"{done}/{total}" if total else f"{done} applied")

    call_command("migrate", interactive=False, verbosity=1, stdout=Lines(on_line))
    step.update(1.0, f"{done}/{total}" if total else "up to date")


def load_demo(step):
    """La démo, jalon par jalon (une ligne écrite par load_demo = un jalon de ``DEMO_MILESTONES``)."""
    from django.core.management import call_command

    seen = 0
    step.update(0.0, toward=DEMO_MILESTONES[0])

    def on_line(line):
        nonlocal seen
        if line.strip():
            seen = min(seen + 1, len(DEMO_MILESTONES))
            after = DEMO_MILESTONES[seen] if seen < len(DEMO_MILESTONES) else None
            step.update(DEMO_MILESTONES[seen - 1], toward=after)

    call_command("load_demo", verbosity=1, stdout=Lines(on_line))
    step.update(1.0)


def prepare(conf, start, steps):
    """Prépare la base (et la démo au premier démarrage) ; renvoie le message des comptes."""
    if conf.get("mode") == "data":  # data folder already filled with the tool: only the tool's updates
        with steps.next("Checking the database (updates of the tool)") as step:
            migrate(step)
        return conf.get("login", "")
    if READY.exists():
        with steps.next("Checking the database (updates of the tool)") as step:
            migrate(step)
        return login_text(READY.read_text(encoding="utf-8"))
    with steps.next("Preparing the database (first start only)") as step:
        migrate(step)
    if start == "empty":
        saved = "empty"
    else:
        with steps.next("Loading the demo data (first start only, the longest step)") as step:
            load_demo(step)
        saved = "demo"
    try:
        from parametres import rangement

        rangement.ecrire_lisez_moi(DATA)  # README.txt: layout of the data folder
    except Exception:
        pass
    READY.write_text(saved, encoding="utf-8")
    return login_text(saved)


def reset(conf):
    """Back to the starting point: the tool's restore of the initial backup, or an empty data folder."""
    print("This deletes all your trials and goes back to the starting point.")
    if input("Type YES then Enter to confirm: ").strip().lower() != "yes":
        print("Nothing changed.")
        return
    archive = initial_backup()
    if archive is None:
        READY.unlink(missing_ok=True)
        empty_data()
        print("Done: the next start asks again what to prepare (the demo or an empty tool).")
        return
    import django
    from django.core.management import call_command

    django.setup()
    call_command("migrate", interactive=False, verbosity=0)
    call_command("restore", archive.name, oui=True, sans_sauvegarde_avant=True)
    print("Done: back to the starting point. Start the tool again.")


def free_port():
    for port in range(8000, 8020):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 8000


def wait_for(port, limit=300):
    """Vrai dès que le serveur répond sur ``port`` ; faux après ``limit`` secondes ou si le lanceur s'arrête."""
    end = time.monotonic() + limit
    while time.monotonic() < end and not STOP.is_set():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


class Steps:
    """Numérotation des étapes d'un démarrage : « [2/4] … »."""

    def __init__(self, total):
        self.total, self.number = total, 0

    def next(self, label):
        self.number += 1
        return Step(self.number, self.total, label)


def ready_message(address, login, answered):
    lines = ["", "=" * 66]
    if answered:
        lines += [f"  Probant is ready: {address}",
                  "  The browser opens by itself. If it does not, copy this address into it."]
    else:
        lines += [f"  Probant is still starting: {address}",
                  "  Open this address in the browser in a moment."]
    lines += ["", f"  {login}", "", "  Keep this window open. Close it to stop the tool.", "=" * 66, ""]
    return "\n".join(lines)


def main():
    print("=" * 66)
    print("  Probant - all-in-one version")
    print("  Starting: the first start takes a few minutes, the next ones less.")
    print("=" * 66)
    organise()
    conf = package()
    if "--reset" in sys.argv:
        reset(conf)
        return
    first = conf.get("mode") != "data" and not READY.exists()
    start = starting_point() if first else None
    if first:
        empty_data()
    steps = Steps(4 if start == "demo" else 3)
    with steps.next("Loading the program"):
        import django
        from django.core.management import call_command

        django.setup()
    login = prepare(conf, start, steps)
    port = free_port()
    address = f"http://127.0.0.1:{port}/"
    starting = steps.next("Starting the tool")

    def when_ready():
        with starting:
            answered = wait_for(port)
        if STOP.is_set():
            return
        print(ready_message(address, login, answered), flush=True)
        if answered:
            webbrowser.open(address)

    threading.Thread(target=when_ready, daemon=True).start()
    # sortie de runserver tue (« Starting development server… ») : le message ci-dessus la remplace
    call_command("runserver", f"127.0.0.1:{port}", use_reloader=False, verbosity=0, stdout=Lines(lambda _line: None))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        STOP.set()
    except Exception:
        STOP.set()
        time.sleep(0.5)  # la ligne de l'étape en cours s'arrête avant le message
        traceback.print_exc()
        print("\n  Something went wrong (message above): take a screenshot of this window for support.")
        READY.unlink(missing_ok=True)
        input("  Press Enter to close.")
