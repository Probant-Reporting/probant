"""Builds the all-in-one version (Windows and / or Mac): one recipe for every package, the demo one and a client's one.

    python3 portable/build_package.py --out DIR [--ref HEAD]
        --python-windows DIR             Python for Windows (python.exe at its root)
        --python-mac-arm DIR --python-mac-intel DIR   Python for Mac (bin/python3), Apple and Intel processors
        --libs DIR                       libraries (pip install --target, pure Python: same folder for every platform)
        [--data DIR --login TEXT]        an installation's data folder, already filled with the tool (its database,
                                         uploaded files and an initial backup data/backups/backup-…-initial.zip);
                                         without it, an empty data folder and the demo at the first start. Copied
                                         without its secrets (.secret_key, .cle_secrete, ai-keys/) nor its large
                                         exports (files/exports/), and with the assistant (MCP) tokens removed from
                                         each database, as in a backup

Result: DIR/Probant-windows/ and / or DIR/Probant-mac/, each laid out as:
    README.txt  Start.*  Reset.*
    data/       files/evidence, files/settings/logo, files/pending-imports, backups (the tool's layout)
    system/     python…/, libs/, app/ (runtime files only), launch.py, package.json

app/ holds only what the tool needs to run: no tests, no project notes (DESIGN.md, notes of the
development assistants), no developer tools (qa/, .github/, .devcontainer/), no documentation history. The role guides and their screenshots (docs/guides, docs/<language>/guides, docs/screenshots) stay: the tool serves them offline (Help). The Python folders and the
libraries are prepared by the caller (.github/workflows/portable.yml, or by hand), never committed.
"""
import argparse
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
# ce que l'outil lit pour fonctionner (liste d'inclusion : rien d'autre n'entre dans le paquet)
APP = ["manage.py", "VERSION", "requirements.txt", "config", "collecte", "parametres", "referentiel", "espaces", "serveur_mcp",
       "libelles", "static", "templates",
       # guides par rôle lus par l'outil (lien Aide, collecte/aide.py), avec leurs captures
       "docs/guides", *(f"docs/{lg}/guides" for lg in ("fr", "es", "de", "it", "nl", "pt")),
       *(f"docs/screenshots/{lg}" for lg in ("en", "fr", "es", "de", "it", "nl", "pt"))]
LAYOUT = ["files/evidence", "files/settings/logo", "files/pending-imports", "backups"]


def _exclu(nom):
    """Fichiers jamais copiés dans app/ : tests, caches."""
    base = Path(nom).name
    return (base.startswith("test_") and base.endswith(".py")) or base == "tests.py" or "__pycache__" in Path(nom).parts


def extraire_app(ref, cible):
    """Les fichiers de APP au commit ``ref`` (git archive : jamais les fichiers locaux non versionnés)."""
    presents = [c for c in APP if subprocess.run(["git", "cat-file", "-e", f"{ref}:{c}"], cwd=RACINE,
                                                 capture_output=True).returncode == 0]
    archive = subprocess.run(["git", "archive", ref, "--", *presents], cwd=RACINE, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as t:
        membres = [m for m in t.getmembers() if not _exclu(m.name)]
        t.extractall(cible, members=membres, filter="data")


# traductions de Django gardées : celles des langues de l'interface (fichiers de libelles/, sans liste à tenir à jour)
LANGUES = {"en_GB"} | {p.name.split(".")[-2].replace("-", "_") for p in (RACINE / "libelles").glob("*.*.json")}
PYTHON_INUTILE = {"__pycache__", "test", "tests", "idlelib", "tkinter", "turtledemo", "include", "tcl", "tcl8.6", "tk8.6",
                  "Tix", "ensurepip"}


def _ignorer_libs(dossier, noms):
    """Bibliothèques : sans caches ni scripts, et seulement les traductions de Django des langues de l'interface."""
    ignores = {n for n in noms if n in ("__pycache__", "bin")}
    if Path(dossier).name == "locale":
        ignores |= {n for n in noms if n not in LANGUES and (Path(dossier) / n).is_dir()}
    return ignores


def _ignorer_python(dossier, noms):
    """Python embarqué : sans tests, interface graphique Tk ni en-têtes de compilation."""
    return {n for n in noms if n in PYTHON_INUTILE or n.startswith(("tcl", "tk", "itcl", "thread"))
            and (Path(dossier) / n).is_dir() and Path(dossier).name in ("lib", "python")}


# dossier des données d'une installation (--data) : jamais ses secrets ni ses fichiers jetables. Clé secrète (nouveau et
# ancien nom : chaque copie a la sienne), clés de la prise IA (docs/ai_socket.md), gros exports (refaits sur demande)
SECRETS_DONNEES = {".secret_key", ".cle_secrete", "ai-keys"}
# tables vidées dans chaque base SQLite copiée : celles que la sauvegarde vide dans sa copie, jetons des assistants compris
# (parametres.sauvegardes.TABLES_VIDEES_DANS_LA_COPIE ; mêmes tables, vérifié par parametres/test_build_package_donnees.py)
TABLES_VIDEES = ["django_session", "django_admin_log", "serveur_mcp_jetonmcp"]
# gros exports en arrière-plan prêts : leur fichier n'est pas copié, ils passent « expirés » avec le motif que la page
# donne au clic (collecte.exports_arriere_plan.FICHIER_ABSENT ; vérifié par parametres/test_vider_bases_exports_fond.py)
EXPORTS_FOND, FICHIER_ABSENT = "collecte_tacheexport", "fichier_absent"


def _ignorer_donnees(dossier, noms):
    """Copie du dossier des données : sans secrets, sans gros exports (``files/exports``, ancien nom ``fichiers/exports``),
    sans fichiers temporaires de SQLite ni caches."""
    ignores = {n for n in noms if n in SECRETS_DONNEES or n == "__pycache__" or n.endswith((".sqlite3-wal", ".sqlite3-shm"))}
    if Path(dossier).name in ("files", "fichiers") and "exports" in noms:
        ignores.add("exports")
    return ignores


def vider_bases(dossier):
    """Vide ``TABLES_VIDEES`` dans chaque base SQLite du dossier copié (base de chaque espace, registre commun), avec
    ``secure_delete`` comme la sauvegarde (les lignes effacées sont écrasées dans le fichier). Les archives des
    sauvegardes n'ont déjà pas de jetons. Renvoie les bases traitées."""
    import sqlite3

    vues = []
    for f in sorted(Path(dossier).rglob("*.sqlite3")):
        if {"backups", "sauvegardes"} & set(f.relative_to(dossier).parts):
            continue
        con = sqlite3.connect(f)
        try:
            presentes = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            con.execute("PRAGMA secure_delete = ON")
            for table in TABLES_VIDEES:
                if table in presentes:
                    con.execute(f'DELETE FROM "{table}"')
            if EXPORTS_FOND in presentes:  # gros exports « prêts » : leur fichier n'est pas copié (files/exports)
                con.execute(f"UPDATE \"{EXPORTS_FOND}\" SET statut = 'expire', erreur = '{FICHIER_ABSENT}' WHERE statut = 'pret'")
            con.commit()
        finally:
            con.close()
        vues.append(f)
    return vues


def construire(nom, out, app, pythons, libs, scripts, conf, donnees):
    racine = out / nom
    if racine.exists():
        raise SystemExit(f"{racine} already exists: choose another --out folder")
    system = racine / "system"
    system.mkdir(parents=True)
    if donnees:  # dossier des données d'une installation (sans ses secrets : chaque copie a sa clé)
        shutil.copytree(donnees, racine / "data", ignore=_ignorer_donnees)
        vider_bases(racine / "data")
    for d in LAYOUT:
        (racine / "data" / d).mkdir(parents=True, exist_ok=True)
    shutil.copytree(app, system / "app")
    shutil.copytree(libs, system / "libs", ignore=_ignorer_libs)
    for dossier, source in pythons.items():
        shutil.copytree(source, system / dossier, symlinks=True, ignore=_ignorer_python)
    shutil.copy2(RACINE / "portable" / "launch.py", system / "launch.py")
    (system / "package.json").write_text(json.dumps(conf, indent=2), encoding="utf-8")
    for s in ["README.txt", *scripts]:
        shutil.copy2(RACINE / "portable" / s, racine / s)
    return racine


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", required=True)
    p.add_argument("--ref", default="HEAD")
    p.add_argument("--python-windows")
    p.add_argument("--python-mac-arm")
    p.add_argument("--python-mac-intel")
    p.add_argument("--libs", required=True)
    p.add_argument("--data")
    p.add_argument("--login", default="")
    a = p.parse_args()
    conf = {"mode": "data", "login": a.login} if a.data else {"mode": "demo"}
    if a.data and not list(Path(a.data).glob("backups/backup-*-initial.zip")):
        raise SystemExit("--data needs an initial backup: python3 manage.py backup --reason initial (DATA_DIR=that folder)")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    app = out / ".app"
    if app.exists():
        raise SystemExit(f"{app} already exists: choose another --out folder")
    extraire_app(a.ref, app)
    faits = []
    if a.python_windows:
        faits.append(construire("Probant-windows", out, app, {"python": a.python_windows}, a.libs,
                                ["Start.bat", "Reset.bat"], conf, a.data))
    if a.python_mac_arm and a.python_mac_intel:
        faits.append(construire("Probant-mac", out, app, {"python-mac-arm": a.python_mac_arm,
                                                                 "python-mac-intel": a.python_mac_intel},
                                a.libs, ["Start.command", "Reset.command"], conf, a.data))
    shutil.rmtree(app)
    for f in faits:
        print(f"Built: {f}")


if __name__ == "__main__":
    main()
