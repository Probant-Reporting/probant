"""Droits des fichiers du dossier des données.

Depuis cette version, l'outil crée tout en 0600 (fichiers) et 0700 (dossiers) : masque posé dans ``config/settings.py``.
Au démarrage, ``resserrer()`` retire les droits du groupe et des autres à ce qu'une version antérieure a créé (bases et
dossiers en 0644 / 0755, archives en 0666 faites par « docker compose exec … backup »).

Ce qui est parcouru : le dossier des données lui-même, les fichiers posés à sa racine (bases, clé, README.txt, repères)
et les dossiers que l'outil y range (fichiers déposés, sauvegardes, autres espaces, essais de connexion, clés de la prise
IA), même placés ailleurs par l'IT (``MEDIA_ROOT``, ``BACKUPS_DIR``, ``SPACES_DIR``). Un autre dossier posé dans le
dossier des données n'est pas touché. Jamais suivi : un lien symbolique. Jamais changé : un fichier qui n'appartient pas
à l'utilisateur de l'outil. Seuls les droits du groupe et des autres sont retirés : ceux du propriétaire ne changent pas.
"""
import logging
import os
import stat
from pathlib import Path

from django.conf import settings

journal = logging.getLogger("reporting.droits")

AUTRES = stat.S_IRWXG | stat.S_IRWXO  # 0o077


def _resserrer_un(chemin):
    """Retire les droits du groupe et des autres à ``chemin`` (sans suivre un lien) ; vrai si quelque chose a changé."""
    try:
        s = os.lstat(chemin)
    except OSError:
        return False
    if stat.S_ISLNK(s.st_mode) or s.st_uid != os.getuid() or not (s.st_mode & AUTRES):
        return False
    try:
        os.chmod(chemin, stat.S_IMODE(s.st_mode) & ~AUTRES)
    except OSError:
        return False
    return True


def _arbre(racine):
    """``racine`` et tout ce qu'elle contient, sans suivre les liens symboliques."""
    racine = Path(racine)
    if racine.is_symlink() or not racine.is_dir():
        return
    yield racine
    for dossier, sous, noms in os.walk(racine, followlinks=False):
        for nom in sous + noms:
            yield Path(dossier) / nom


def racines():
    """Dossiers que l'outil range lui-même (parcourus en entier)."""
    from espaces import contexte as ESP

    donnees = Path(settings.DOSSIER_DONNEES)
    # dossiers de l'espace principal : ceux de toute l'installation (les autres espaces et leurs archives sont dessous,
    # ou dans ESPACES_DOSSIER)
    return [ESP.dossier_medias(ESP.PRINCIPAL), ESP.dossier_sauvegardes(ESP.PRINCIPAL), Path(settings.ESPACES_DOSSIER),
            Path(settings.IA_CLES_DIR), donnees / "sign-in-attempts"]


def resserrer():
    """Démarrage : fichiers et dossiers de l'outil ramenés à 0600 / 0700 (droits du groupe et des autres retirés).
    Renvoie le nombre d'éléments changés. Rien ici n'empêche le démarrage."""
    if os.name != "posix":
        return 0
    donnees = Path(settings.DOSSIER_DONNEES)
    vus, n = set(), 0
    candidats = [donnees]
    try:
        candidats += [p for p in donnees.iterdir() if p.is_file() or p.is_symlink()]
    except OSError:
        pass
    for r in racines():
        candidats += list(_arbre(r))
    for p in candidats:
        if p in vus:
            continue
        vus.add(p)
        n += _resserrer_un(p)
    if n:
        journal.info("File rights: %s file(s) or folder(s) of the tool made readable by its user only", n)
    return n
