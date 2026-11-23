"""Efface pour de bon ce qui est dans la corbeille depuis plus que le délai réglé (Paramètres › Hébergement, 30 jours par
défaut ; exports enregistrés, listes de KPI, vues de la
Visualisation supprimés dans l'outil ; ``collecte/corbeille.py``), dans chaque espace actif (SPACE=<code> : un seul).

    python manage.py purge_deleted        (aussi lancé à chaque démarrage par « startup », chaque nuit par
                                          « check_data --schedule », et à chaque suppression)

L'IT n'a rien à planifier : la commande sert à vérifier ou à forcer l'effacement.
"""
from django.core.management.base import BaseCommand

from collecte.models import jours_corbeille, purger_corbeille
from espaces import contexte as ESP
from parametres import sauvegardes as SV


class Command(BaseCommand):
    help = ("Permanently erases the items deleted in the tool longer ago than the trash delay of each space "
            "(Settings > Hosting, 30 days by default: saved exports, KPI lists, Visualisation views), in each active space.")

    def handle(self, *args, **o):
        for code in ESP.chaque_espace():
            if SV.base_vide():
                continue
            n = purger_corbeille()
            self.stdout.write(f"Space \"{code}\": {n} deleted item(s) erased for good (kept {jours_corbeille()} days).")
