"""Contrôle de cohérence de la base, sans rien modifier (``collecte.controle_donnees``).

    python manage.py check_data              chaque espace actif (SPACE=<code> : un seul), résultat gardé
    python manage.py check_data --json       même chose, sortie JSON
    python manage.py check_data --schedule   chaque nuit à DATA_CHECK_TIME (lancé par l'image Docker)

Code de sortie 1 si une erreur est trouvée (supervision, cron).
"""
import json
import sys

from django.core.management.base import BaseCommand

from collecte import controle_donnees as CD
from espaces import contexte as ESP
from parametres import langues as L
from parametres import sauvegardes as SV

SIGNES = {CD.ERREUR: "ERROR", CD.AVERTISSEMENT: "WARNING", CD.INFO: "info"}


class Command(BaseCommand):
    help = "Checks the consistency of the database of each space (read only) and keeps the result (Settings > Hosting, /sante/)."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Output as JSON.")
        parser.add_argument("--no-save", "--sans-enregistrer", dest="sans_enregistrer", action="store_true",
                            help="Do not keep the result (Settings > Hosting and /sante/ keep showing the previous one).")
        parser.add_argument("--schedule", "--planifier", dest="planifier", action="store_true",
                            help="Run forever: a check of each space every day at DATA_CHECK_TIME.")
        parser.add_argument("--time", "--heure", dest="heure", default=None, metavar="HH:MM",
                            help="With --schedule: time of the daily check (default: DATA_CHECK_TIME, 03:30).")

    def handle(self, *args, **o):
        with L.activer_interface("en"):  # messages pour l'IT en anglais
            return self._handle(**o)

    def _handle(self, **o):
        if o["planifier"]:
            CD.planifier(o["heure"])
            return
        resultats = []
        for _ in ESP.chaque_espace():  # tous les espaces actifs (SPACE=<code> : un seul)
            if SV.base_vide():
                continue
            r = CD.controler()
            if not o["sans_enregistrer"]:
                CD.enregistrer(r)
            resultats.append(r)
            if not o["json"]:
                self._afficher(r)
        if o["json"]:
            self.stdout.write(json.dumps(resultats if len(resultats) != 1 else resultats[0], ensure_ascii=False, indent=1, default=str))
        if any(r["errors"] for r in resultats):
            sys.exit(1)

    def _afficher(self, r):
        self.stdout.write(f"Space \"{r['space']}\": {r['errors']} error(s), {r['warnings']} warning(s), {r['infos']} info "
                          f"({r['seconds']} s)")
        if not r["problems"]:
            self.stdout.write(self.style.SUCCESS("  No problem found."))
        for c in r["problems"]:
            ligne = f"  [{SIGNES.get(c['severity'], c['severity'])}] {c['check']}: {c['message']}"
            style = self.style.ERROR if c["severity"] == CD.ERREUR else self.style.WARNING if c["severity"] == CD.AVERTISSEMENT else str
            self.stdout.write(style(ligne))
            for e in c["examples"]:
                self.stdout.write(f"      - {e}")
            if c["count"] > len(c["examples"]):
                self.stdout.write(f"      … and {c['count'] - len(c['examples'])} more")
