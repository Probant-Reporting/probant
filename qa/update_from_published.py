"""Check "you can update from any published version directly": every published version → the current code, in one step.

    python3 qa/update_from_published.py                       # SQLite, every published version
    python3 qa/update_from_published.py --database postgresql --postgres postgres://user:password@127.0.0.1:5432/postgres
    python3 qa/update_from_published.py --database both --postgres URL --versions 1.0.0 --port 8603

An installation of ANY published version must go to the current version without an intermediate step (the tool never
compares two versions: it applies every migration it does not find in the database). For each published version this
script:
  1. finds the code of that version (see "Which versions, which code");
  2. builds a database with THAT code, as a person would use it: ``startup``, the demo (``load_demo``), a few gestures
     (``qa/update_gestures.py``: a value validated, an evidence file, a log line) and a backup made by that old version;
  3. gives it to ``qa/migration_rehearsal.py``, which updates it with the current code exactly as the Docker image does
     (``manage.py startup``: backup, then migrations) and compares everything: rows of every table, KPI records, accounts,
     answers, statuses, evidence files, exports (so the figures of the closed years), log; backup then restore; going back
     to the old version; and, for this check, (a) the start of the tool on the updated database with ``/sante/`` green
     and a sign-in with a demo account, (b) the archive made by the OLD version restored by the CURRENT version (PostgreSQL: when the
     update applies migrations, the documented refusal is what is expected, see ``--old-archive``).
Nothing is written outside the working folder (deleted at the end unless ``--keep``) and the PostgreSQL databases that
this script creates (deleted at the end). Fictitious data only. Exit code: 0 if every update is identical, 1 if one
differs (details on screen: they are findings, never fixed here), 2 if a version cannot be tested.

Which versions, which code
  * The versions are the headings ``## X.Y.Z — YYYY-MM-DD`` of ``CHANGELOG.md`` (a heading with no date is not
    published yet). A new published version is taken by the next run without any change here.
  * The code of a version: the git tag ``vX.Y.Z``, or else ``VX.Y.Z`` (one tag of the public repository is written so),
    if it exists (the public repository: one commit and one tag per version; fetch the tags, ``fetch-depth: 0`` in the
    workflow); otherwise, in a longer history, the last commit whose
    ``VERSION`` file said ``X.Y.Z``; the current commit if its ``VERSION`` is ``X.Y.Z`` (then the "update" goes from the
    current version to itself: it still checks that nothing moves). A version with no code is an error (exit code 2);
    ``--skip-unavailable`` says so and goes on (a clone without tags).
  * The packages: when ``requirements.txt`` of the old version differs from the current one, a virtual environment
    with its own packages is made in the working folder (needs the network, once per different file).

Limits: only the main space is compared (the other spaces, and the sign-in of other roles, are not); the tool of
``qa/extract.py`` is the current one, run with the old code, so a future change of the models it reads has to be taken
into account there; the demo is small (a large database is the job of ``qa/load/`` and the rehearsal by hand).
"""
# Messages et rapport en anglais ; commentaires et identifiants en français.
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
from qa import migration_rehearsal as MR  # noqa: E402

TITRE_VERSION = re.compile(r"^##\s+(\d+\.\d+\.\d+)\s+[—–-]\s+(\d{4}-\d{2}-\d{2})\s*$", re.M)


class Impossible(Exception):
    """Une version ne peut pas être essayée (code introuvable, installation des paquets refusée…) : code de sortie 2."""


# ---------------------------------------------------------------- quelles versions, quel code
def versions_publiees(journal):
    """Versions publiées d'après le texte de ``CHANGELOG.md`` : celles dont le titre porte une date, de la plus ancienne à
    la plus récente (ordre des numéros)."""
    trouvees = {m.group(1) for m in TITRE_VERSION.finditer(journal)}
    return sorted(trouvees, key=lambda v: tuple(int(x) for x in v.split(".")))


def git(depot, *args, ok_si_echec=False):
    r = subprocess.run(["git", "-C", str(depot), *args], capture_output=True, text=True)
    if r.returncode:
        if ok_si_echec:
            return None
        raise Impossible(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def source_de(version, depot):
    """(commit, explication) du code publié sous ``version``, ou None. Dans l'ordre : l'étiquette ``v<version>``, puis
    ``V<version>`` (une étiquette du dépôt public a été posée avec un V majuscule ; les scripts d'installation acceptent
    les deux de la même façon) ; le commit courant si son fichier VERSION porte ce numéro ; le dernier commit (de la branche, merges non suivis) dont le
    fichier VERSION portait ce numéro."""
    for etiquette in (f"v{version}", f"V{version}"):
        commit = git(depot, "rev-parse", "--verify", "--quiet", f"refs/tags/{etiquette}^{{commit}}", ok_si_echec=True)
        if commit:
            return commit, f"tag {etiquette}"
    if git(depot, "show", "HEAD:VERSION", ok_si_echec=True) == version:
        return git(depot, "rev-parse", "HEAD"), "current commit (its VERSION file)"
    changements = (git(depot, "log", "--first-parent", "--format=%H", "--", "VERSION") or "").split()
    for i, c in enumerate(changements):
        if git(depot, "show", f"{c}:VERSION", ok_si_echec=True) == version and i > 0:
            # le commit d'avant (plus récent) a quitté ce numéro : son parent est le dernier à le porter
            parent = git(depot, "rev-parse", "--verify", "--quiet", f"{changements[i - 1]}^", ok_si_echec=True)
            if parent:
                return parent, "last commit with this VERSION"
    return None


# ---------------------------------------------------------------- code et paquets de l'ancienne version
def extraire_code(commit, dossier):
    """Le code de ``commit`` (sans l'historique) dans ``dossier``."""
    dossier.mkdir(parents=True)
    archive = dossier.parent / f"{dossier.name}.tar"
    git(RACINE, "archive", "--format=tar", "-o", str(archive), commit)
    with tarfile.open(archive) as t:
        t.extractall(dossier, filter="data")
    archive.unlink()


def interpreteur_pour(code, venvs):
    """Interpréteur qui a les paquets de ``code`` : celui-ci si ``requirements.txt`` est le même, sinon un environnement
    virtuel fait pour ce fichier (gardé dans ``venvs``, une fois par fichier différent)."""
    voulu = (code / "requirements.txt").read_bytes()
    if voulu == (RACINE / "requirements.txt").read_bytes():
        return sys.executable
    empreinte = hashlib.sha256(voulu).hexdigest()[:12]
    venv = venvs / empreinte
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        print(f"  packages differ from the current ones: environment {venv.name} (installing, once)", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        r = subprocess.run([str(python), "-m", "pip", "install", "-q", "-r", str(code / "requirements.txt")],
                           capture_output=True, text=True)
        if r.returncode:
            shutil.rmtree(venv, ignore_errors=True)
            raise Impossible(f"packages of the old version not installed: {r.stderr.strip()[-600:]}")
    return str(python)


def environnement(extra):
    """Environnement des commandes : celui du processus, sans réglage de base ni de dossier (les nôtres le remplacent)."""
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SQLITE_FILE", "DATA_DIR", "DOSSIER_DONNEES",
                                                            "MEDIA_ROOT", "DJANGO_SETTINGS_MODULE")}
    env.update(extra)
    return env


def lancer(commande, cwd, env, journal):
    r = subprocess.run(commande, cwd=cwd, env=env, capture_output=True, text=True)
    journal.write(f"$ {' '.join(map(str, commande))}\n{r.stdout}\n{r.stderr}\n")
    if r.returncode:
        raise Impossible(f"{' '.join(map(str, commande[1:4]))} failed with the old code:\n{(r.stdout + r.stderr)[-2500:]}")
    return r.stdout


def construire_base(version, code, python, travail, postgres, nom_pg):
    """Base de démonstration faite avec le code de l'ancienne version, puis ses gestes et une sauvegarde. Renvoie le dossier
    des données (SQLite : la base y est ; PostgreSQL : seulement fichiers et archives) et l'archive faite."""
    donnees = travail / "donnees-ancienne-version"
    donnees.mkdir(parents=True)
    extra = {"DJANGO_DEBUG": "1", "DATA_DIR": str(donnees), "DJANGO_SECRET_KEY": MR.CLE_SECRETE}
    if postgres:
        MR.pg_admin(postgres, f'DROP DATABASE IF EXISTS "{nom_pg}" WITH (FORCE)', f'CREATE DATABASE "{nom_pg}"')
        extra["DATABASE_URL"] = MR.url_base(postgres, nom_pg)
    env = environnement(extra)
    with open(travail / "construction.log", "w", encoding="utf-8") as journal:
        lancer([python, "manage.py", "startup"], code, env, journal)
        lancer([python, "manage.py", "load_demo", "--language", "fr"], code, env, journal)
        lancer([python, str(RACINE / "qa" / "update_gestures.py")], code, env, journal)
        lancer([python, "manage.py", "backup", "--reason", "old-version"], code, env, journal)
    archives = sorted((donnees / "backups").glob("*-old-version.zip"))
    if not archives:
        raise Impossible("the old version made no archive (manage.py backup)")
    return donnees, archives[-1]


# ---------------------------------------------------------------- une mise à jour
def essayer(version, source, o, venvs, moteur):
    """Une version, un moteur de base (``sqlite`` ou ``postgresql``) : construit la base avec l'ancien code, lance la
    répétition. Renvoie (code de sortie de la répétition, durée en secondes)."""
    debut = time.monotonic()
    commit, provenance = source
    travail = Path(tempfile.mkdtemp(prefix=f"mise-a-jour-{version}-{moteur}-", dir=o.work or None))
    nom_pg = f"{o.pg_prefix}_{version.replace('.', '_')}"[:50]
    postgres = o.postgres if moteur == "postgresql" else None
    try:
        print(f"\n==== {version} ({provenance}, {commit[:8]}) -> current version, {moteur}", flush=True)
        code = travail / "code"
        extraire_code(commit, code)
        python = interpreteur_pour(code, venvs)
        print("  building the database with the old code (startup, demo, gestures, backup)...", flush=True)
        donnees, archive = construire_base(version, code, python, travail, postgres, nom_pg)
        commande = [sys.executable, str(RACINE / "qa" / "migration_rehearsal.py"), "--before", str(code),
                    "--before-python", python, "--before-name", version, "--before-commit", commit[:8],
                    "--old-archive", str(archive), "--media", str(donnees / "files"), "--health-port", str(o.port),
                    "--source", f"demo built by the published version {version} ({moteur})"]
        if postgres:
            commande += ["--postgres", postgres, "--base", nom_pg]
        else:
            commande += ["--base", str(donnees / "db.sqlite3"), "--registry", str(donnees / "shared.sqlite3")]
        if o.report:
            commande += ["--report", str(o.report)]
        resultat = subprocess.run(commande, env=environnement({}), cwd=RACINE)
        return resultat.returncode, time.monotonic() - debut
    finally:
        if postgres and not o.keep:
            MR.pg_admin(postgres, f'DROP DATABASE IF EXISTS "{nom_pg}" WITH (FORCE)')
        if o.keep:
            print(f"Working folder kept: {travail}")
        else:
            shutil.rmtree(travail, ignore_errors=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--database", choices=["sqlite", "postgresql", "both"], default="sqlite")
    p.add_argument("--postgres", default=os.environ.get("POSTGRES_ADMIN_URL", ""),
                   help="URL of a PostgreSQL server, user allowed to create databases (or POSTGRES_ADMIN_URL).")
    p.add_argument("--pg-prefix", default="update_check",
                   help="Prefix of the names of the PostgreSQL databases made (and dropped).")
    p.add_argument("--versions", default="", help="Comma-separated versions to try (default: every published version).")
    p.add_argument("--code", action="append", default=[], metavar="VERSION=REF",
                   help="Take the code of VERSION from this commit or tag instead of looking for it (investigation, or a "
                   "control with an older commit that has migrations); can be repeated.")
    p.add_argument("--port", type=int, default=8603, help="Port to start the tool on, to check /sante/.")
    p.add_argument("--work", default="", help="Folder for the temporary work (default: the system one).")
    p.add_argument("--report", default="", help="Markdown file to which the reports are added (figures only).")
    p.add_argument("--skip-unavailable", action="store_true",
                   help="Say it and go on when the code of a version cannot be found (a clone without tags).")
    p.add_argument("--keep", action="store_true",
                   help="Keep the working folders and the PostgreSQL databases (investigation).")
    o = p.parse_args(argv)
    moteurs = ["sqlite", "postgresql"] if o.database == "both" else [o.database]
    if "postgresql" in moteurs and not o.postgres:
        p.error("--postgres URL (or POSTGRES_ADMIN_URL) is needed for PostgreSQL")
    journal = RACINE / "CHANGELOG.md"
    publiees = versions_publiees(journal.read_text(encoding="utf-8")) if journal.is_file() else []
    versions = [v for v in o.versions.split(",") if v] or publiees
    if not versions:
        print("No published version found in CHANGELOG.md (headings \"## X.Y.Z - YYYY-MM-DD\"): nothing to check.")
        return 2
    print(f"Published versions: {', '.join(versions)}; current version: {(RACINE / 'VERSION').read_text().strip()}; "
          f"database(s): {', '.join(moteurs)}")
    sources, absentes = {}, []
    imposees = dict(x.split("=", 1) for x in o.code)
    for v in versions:
        s = (git(RACINE, "rev-parse", "--verify", f"{imposees[v]}^{{commit}}"), f"given by --code ({imposees[v]})") \
            if v in imposees else source_de(v, RACINE)
        if s is None:
            absentes.append(v)
            print(f"  version {v}: no code found (no tag v{v} or V{v}, no commit with this VERSION file)")
        else:
            sources[v] = s
            print(f"  version {v}: {s[1]}, commit {s[0][:8]}")
    if absentes and not o.skip_unavailable:
        print(f"\nERROR: no code for {', '.join(absentes)}. Fetch the tags (git fetch --tags; in GitHub Actions, "
              "fetch-depth: 0) or use --skip-unavailable.")
        return 2
    if not sources:
        print("\nNothing could be tested: no code found for any published version (skipped).")
        return 0
    if o.work:
        Path(o.work).mkdir(parents=True, exist_ok=True)
    venvs = Path(tempfile.mkdtemp(prefix="venvs-", dir=o.work or None))
    resultats = []
    try:
        for v, source in sources.items():
            for moteur in moteurs:
                try:
                    code, duree = essayer(v, source, o, venvs, moteur)
                except Impossible as e:
                    print(f"\nCannot test {v} ({moteur}): {e}")
                    code, duree = 2, 0.0
                resultats.append((v, moteur, code, duree))
    finally:
        shutil.rmtree(venvs, ignore_errors=True)
    print("\n== Summary: update from a published version to the current version, in one step")
    print("| Version | Database | Result | Duration |\n|---|---|---|---|")
    for v, moteur, code, duree in resultats:
        texte = {0: "identical, /sante/ green", 1: "DIFFERENCES (see above)"}.get(code, "NOT TESTED (see above)")
        print(f"| {v} | {moteur} | {texte} | {duree / 60:.1f} min |")
    for v in absentes:
        print(f"| {v} | - | skipped: no code found | - |")
    return max((r[2] for r in resultats), default=0)


if __name__ == "__main__":
    sys.exit(main())
