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
Close the window to stop the tool. Messages are in English, like the rest of the tool's messages for IT.
"""
import json
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


def prepare(conf):
    import django
    from django.core.management import call_command

    if conf.get("mode") == "data":  # data folder already filled with the tool: only the tool's updates
        django.setup()
        call_command("migrate", interactive=False, verbosity=0)
        return conf.get("login", "")
    if READY.exists():
        return READY.read_text(encoding="utf-8")
    start = starting_point()
    empty_data()
    django.setup()
    if start == "empty":
        print("  Preparing an empty tool (first time: about a minute, do not close this window)...")
        call_command("migrate", interactive=False, verbosity=0)
        login = "No account yet: the setup wizard opens. Its first step creates your administrator account."
    else:
        print("  Preparing the demo (first time: a few minutes, do not close this window)...")
        call_command("migrate", interactive=False, verbosity=0)
        call_command("load_demo", verbosity=0)
        login = "Login: admin (also validateur, contributeur)\n  Password: demo-probant-2026"
    try:
        from parametres import rangement

        rangement.ecrire_lisez_moi(DATA)  # README.txt: layout of the data folder
    except Exception:
        pass
    READY.write_text(login, encoding="utf-8")
    return login


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


def main():
    print("=" * 66)
    print("  Probant - all-in-one version")
    print("=" * 66)
    organise()
    conf = package()
    if "--reset" in sys.argv:
        reset(conf)
        return
    login = prepare(conf)
    import django
    from django.core.management import call_command

    django.setup()
    port = free_port()
    address = f"http://127.0.0.1:{port}/"
    print("\n" + "=" * 66)
    print(f"  Site: {address}")
    print(f"  {login}")
    print("  Keep this window open. Close it to stop the tool.")
    print("=" * 66 + "\n")
    threading.Thread(target=lambda: (time.sleep(2), webbrowser.open(address)), daemon=True).start()
    call_command("runserver", f"127.0.0.1:{port}", use_reloader=False, verbosity=0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
        print("\n  Something went wrong (message above): take a screenshot of this window for support.")
        READY.unlink(missing_ok=True)
        input("  Press Enter to close.")
