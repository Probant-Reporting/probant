"""Imports de valeurs et gros exports en arrière-plan (``collecte.imports_arriere_plan``, ``collecte.exports_arriere_plan``).

    python manage.py run_imports              exécute les imports et les exports en attente de chaque espace, puis s'arrête
    python manage.py run_imports --schedule   sans fin : la file de chaque espace toutes les 2 s (lancé par l'image Docker)

Sans ce planificateur (développement, version Windows portable), le serveur web exécute lui-même imports et exports.
"""
from django.core.management.base import BaseCommand

from collecte import exports_arriere_plan as EAP
from collecte import imports_arriere_plan as AP
from espaces import contexte as ESP
from parametres import langues as L
from parametres import sauvegardes as SV


class Command(BaseCommand):
    help = ("Runs the large value imports and the large exports started in the tool (Import / Export) in the background. "
            "--schedule: run forever (started by the Docker image).")

    def add_arguments(self, parser):
        parser.add_argument("--schedule", "--planifier", dest="planifier", action="store_true",
                            help="Run forever: the queue of each space every 2 seconds.")

    def handle(self, *args, **o):
        with L.activer_interface("en"):
            if o["planifier"]:
                AP.planifier()
                return
            for code in ESP.chaque_espace():
                if SV.base_vide():
                    continue
                AP.traiter_file()
                EAP.traiter_file()
                self.stdout.write(f"Space \"{code}\": queue processed.")
