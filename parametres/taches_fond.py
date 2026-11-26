"""Signe de vie des tâches de fond (``backup --schedule``, ``send_reminders --schedule``, ``check_data --schedule``,
``run_imports --schedule``) : chaque boucle planifiée pose, dans un fil à part, un fichier par tâche dans le dossier des
données (``.tasks/<tâche>``, sa date de modification), hors de toute base ; il survit aux restaurations.

Une tâche est « arrêtée » quand son fichier existe et n'a pas bougé depuis ``SEUIL`` : elle a tourné ici, puis son
processus s'est arrêté (plantage, mémoire, arrêt à la main). Une tâche jamais lancée ici (version tout-en-un, serveur de
développement, hébergement géré avec des tâches planifiées « cron » au lieu de workers) n'a pas de fichier : rien n'est
signalé. Une tâche retirée exprès : effacer son fichier (docs/installation.md, « Troubleshooting »).

Lu par la page Santé et les alertes par e-mail (``sante_installation.py``, ligne « Tâches de fond »)."""
import logging
import os
import threading
import time
from pathlib import Path

from django.conf import settings

journal = logging.getLogger("reporting.taches")

TACHES = ("backup", "reminders", "data_check", "imports")  # ordre d'affichage ; noms des fichiers
PAS = 60  # secondes entre deux signes de vie
SEUIL = 10 * 60  # secondes sans signe de vie : la tâche est arrêtée


def dossier():
    return Path(settings.DOSSIER_DONNEES) / ".tasks"


def battre(nom, ou=None):
    """Signe de vie de la tâche ``nom`` (fichier remplacé d'un coup : jamais à moitié écrit) ; ``ou`` : le dossier."""
    f = (ou or dossier()) / nom
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        partiel = f.with_name(f".{nom}.{os.getpid()}.partiel")
        partiel.write_text(str(int(time.time())), encoding="utf-8")
        os.replace(partiel, f)
        _refus.discard(nom)
    except OSError:
        if nom not in _refus:  # une ligne au journal, pas une par minute
            _refus.add(nom)
            journal.warning("Cannot write the sign of life of the task \"%s\" in %s", nom, f.parent)


_refus = set()  # tâches dont le dernier signe de vie n'a pas pu s'écrire (journal du serveur)


def demarrer(nom):
    """Fil qui pose le signe de vie de ``nom`` toutes les ``PAS`` secondes tant que le processus vit (même pendant une
    longue sauvegarde ou un long contrôle : seul l'arrêt du processus l'arrête)."""
    if nom not in TACHES:
        raise ValueError(nom)
    ou = dossier()  # lu une fois : le fil écrit toujours au même endroit
    battre(nom, ou)

    pause = threading.Event()  # jamais posé : une attente que les essais qui remplacent time.sleep ne touchent pas

    def boucle():
        while True:
            pause.wait(PAS)
            if not ou.parent.is_dir():  # dossier des données retiré (dossier temporaire d'un essai) : plus rien à signer
                return
            battre(nom, ou)

    threading.Thread(target=boucle, name=f"sign-of-life-{nom}", daemon=True).start()


def arretees(maintenant=None):
    """Tâches qui ont tourné ici et ne donnent plus signe de vie depuis ``SEUIL``, dans l'ordre de ``TACHES``."""
    maintenant = maintenant or time.time()
    sortie = []
    for nom in TACHES:
        try:
            age = maintenant - (dossier() / nom).stat().st_mtime
        except OSError:
            continue  # jamais lancée ici
        if age > SEUIL:
            sortie.append(nom)
    return sortie
