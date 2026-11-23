"""Rangement des fichiers de l'installation : un seul endroit qui dit quel document va où (noms en anglais, pour les
installations à l'étranger ; les anciens noms français sont repris tout seuls).

Dossier des données (``DATA_DIR`` : ``/data`` dans l'image Docker, ``local-data`` sur un poste de développement ou un
Codespace, ``data`` dans la version Windows) :

    README.txt                    ce plan, écrit par l'outil au démarrage
    db.sqlite3, shared.sqlite3    bases de données (SQLite) : l'espace principal, le registre des comptes
    .secret_key                   clé de l'installation, à ne jamais partager
    files/                        documents déposés dans l'outil (espace principal)
        evidence/<période>/<organisation>/<KPI>/<fichier>
                                  preuves déposées par les contributeurs
        settings/logo/            logo de l'installation (Administration › Paramètres › Identité)
        pending-imports/          fichiers déposés pour un import, effacés après usage (jamais sauvegardés)
        exports/                  gros exports fabriqués en arrière-plan, effacés après quelques jours (jamais sauvegardés)
    sign-in-attempts/             compteur des essais de connexion manqués, partagé par les processus (jamais sauvegardé)
    ai-keys/<code>.key            clé de l'assistant IA de chaque espace, saisie par son administrateur (jamais sauvegardée)
    backups/                      archives datées (base + fichiers) de l'espace principal, historique des restaurations
        shared/                   archives du registre des comptes
        spaces/<code>/            archives des autres espaces
    spaces-data/<code>/           autres espaces : database.sqlite3 et files/, rangés de la même façon

Les fichiers ne sont jamais mélangés : une preuve n'est jamais à côté d'un fichier de réglage ou d'un fichier
temporaire, et rien de ce qui est propre à l'installation n'est rangé dans le dossier du code.
"""
import os
import re
import shutil
from pathlib import Path

FICHIERS = "files"  # racine des documents déposés d'un espace (MEDIA_ROOT pour l'espace principal)
ANCIENNES_RACINES = ("media", "fichiers")  # noms d'avant la mise à jour et, repris au démarrage et par migration
PREUVES = "evidence"
LOGO = "settings/logo"
IMPORTS = "pending-imports"
EXPORTS = "exports"  # gros exports fabriqués en arrière-plan (collecte/exports_arriere_plan.py)
# anciens sous-dossiers → nouveaux (dans cet ordre)
ANCIENS = {"imports": IMPORTS, "imports-en-cours": IMPORTS, "identite": LOGO, "reglages/logo": LOGO, "preuves": PREUVES}
LISEZ_MOI_FICHIER = "README.txt"

LISEZ_MOI = """Probant - data folder layout
==================================

This folder holds everything that belongs to this installation. The tool keeps it in order:
do not move anything by hand (backups and restores take care of it).

db.sqlite3            database of the main space (when the installation uses SQLite)
shared.sqlite3        account registry, shared by all spaces
.secret_key           installation key: never share it

files/                files uploaded in the tool (main space)
  evidence/           evidence files uploaded by contributors,
                      filed by period, then organisation, then KPI:
                      evidence/2026/ES-COM/ENE-01/gas-invoice.pdf
  settings/logo/      logo of the installation (Settings > Identity)
  pending-imports/    files uploaded for an import; deleted after use, never backed up
  exports/            large exports made in the background; deleted after a few days, never backed up

sign-in-attempts/     count of failed sign-ins (temporary, never backed up)
ai-keys/<code>.key    key of the AI assistant of each space, entered by its administrator (never backed up)

backups/              dated archives (database + files) of the main space
  restores.jsonl      history of restores
  data-checks.json    last results of the nightly data check
  shared/             archives of the account registry
  spaces/<code>/      archives of the other spaces

spaces-data/<code>/   other spaces (Purchasing, HR...): database.sqlite3 and files/, organised the same way

Details: docs/file_layout.md (in the tool's code).
"""


def _segment(texte):
    """Morceau de chemin lisible et sûr : lettres, chiffres, tirets, points et soulignés seulement."""
    t = re.sub(r"[^A-Za-z0-9._-]+", "-", str(texte or "").strip()).strip("-.")
    return t or "sans-nom"


def _nom_fichier(nom):
    """Nom de fichier sûr qui garde son extension : « отчёт.pdf » devient « file.pdf » (et non « pdf », sans extension,
    que la page ne savait plus afficher)."""
    racine, ext = os.path.splitext(os.path.basename(str(nom or "")))
    ext = re.sub(r"[^A-Za-z0-9]+", "", ext)
    if not ext:
        return _segment(racine)
    racine = re.sub(r"[^A-Za-z0-9._-]+", "-", racine.strip()).strip("-.")
    return f"{racine or 'file'}.{ext}"


def periode_dossier(debut, annuelle):
    """« 2026 » pour une période annuelle, « 2026-03 » sinon (mois de début)."""
    return str(debut.year) if annuelle else debut.strftime("%Y-%m")


def chemin_preuve(periode_debut, annuelle, code_organisation, code_kpi, nom):
    """preuves/<période>/<organisation>/<KPI>/<nom du fichier> : comme un auditeur les cherche."""
    return "/".join([PREUVES, periode_dossier(periode_debut, annuelle), _segment(code_organisation), _segment(code_kpi),
                     _nom_fichier(nom)])


def _fusionner(ancien, nouveau):
    """Déplace le contenu du dossier ``ancien`` dans ``nouveau`` sans rien écraser, puis retire ``ancien`` s'il est vide."""
    ancien, nouveau = Path(ancien), Path(nouveau)
    if not ancien.is_dir() or ancien.resolve() == nouveau.resolve():
        return
    if not nouveau.exists():
        nouveau.parent.mkdir(parents=True, exist_ok=True)
        ancien.rename(nouveau)
        return
    for x in list(ancien.iterdir()):
        cible = nouveau / x.name
        if x.is_dir() and cible.is_dir():
            _fusionner(x, cible)
        elif not cible.exists():
            shutil.move(str(x), str(cible))
    try:
        ancien.rmdir()
    except OSError:
        pass  # quelque chose n'a pas pu être déplacé (même nom des deux côtés) : laissé en place, rien n'est perdu


def ranger_racine(racine):
    """Anciens dossiers « media » et « fichiers » voisins de ``racine`` (dossier « files ») : leur contenu y passe ; anciens
    sous-dossiers français (preuves, reglages/logo, identite, imports…) : renommés. Sans effet si tout est déjà rangé."""
    racine = Path(racine)
    if racine.name == FICHIERS:
        for ancienne in ANCIENNES_RACINES:
            _fusionner(racine.parent / ancienne, racine)
    for ancien, nouveau in ANCIENS.items():
        if (racine / ancien).is_dir():
            _fusionner(racine / ancien, racine / nouveau)
    if (racine / "reglages").is_dir():  # vidé par le déplacement du logo
        _retirer_dossiers_vides(racine / "reglages", racine)


def deplacer(racine, ancien_nom, nouveau_nom):
    """Déplace un fichier déposé de ``ancien_nom`` à ``nouveau_nom`` (chemins relatifs à ``racine``) sans écraser :
    renvoie le nom réellement utilisé (suffixe « -2 », « -3 »… si la place est prise), ou None si le fichier n'existe
    pas (le nom enregistré est alors laissé tel quel)."""
    racine = Path(racine)
    source = racine / ancien_nom
    candidats = [ancien_nom] + [n + ancien_nom[len(a):] for a, n in ANCIENS.items() if ancien_nom.startswith(f"{a}/")]
    for nom_ancien in candidats:
        if (racine / nom_ancien).is_file():
            source = racine / nom_ancien
            break
    if not source.is_file():
        return None
    cible = Path(nouveau_nom)
    nom = cible
    n = 2
    while (racine / nom).exists() and (racine / nom).resolve() != source.resolve():
        nom = cible.with_name(f"{cible.stem}-{n}{cible.suffix}")
        n += 1
    if (racine / nom).resolve() != source.resolve():
        (racine / nom).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(racine / nom))
        _retirer_dossiers_vides(source.parent, racine)
    return nom.as_posix()


def _retirer_dossiers_vides(dossier, racine):
    dossier, racine = Path(dossier), Path(racine)
    while dossier != racine and racine in dossier.parents:
        try:
            dossier.rmdir()
        except OSError:
            return
        dossier = dossier.parent


def ecrire_lisez_moi(dossier):
    """README.txt du dossier des données (réécrit s'il a changé ; jamais dans le dossier du code)."""
    from django.conf import settings

    dossier = Path(dossier)
    if dossier.resolve() == Path(settings.BASE_DIR).resolve() or not dossier.is_dir():
        return
    (dossier / "LISEZ-MOI.txt").unlink(missing_ok=True)  # ancien nom
    f = dossier / LISEZ_MOI_FICHIER
    try:
        if not f.exists() or f.read_text(encoding="utf-8") != LISEZ_MOI:
            f.write_text(LISEZ_MOI, encoding="utf-8")
    except OSError:
        pass
