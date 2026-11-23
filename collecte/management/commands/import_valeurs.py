from django.core.management.base import BaseCommand

from collecte.echange import importer_valeurs

TYPES = {"saisi": "Saisi", "calcule": "Calculé", "fe": "FE"}


class Command(BaseCommand):
    help = "Imports historical values from a legacy file (columns ID KPI, Result, Organisation, Year)."

    def add_arguments(self, parser):
        parser.add_argument("fichier", metavar="file", help="Excel file (.xlsx).")
        parser.add_argument("--sheet", "--onglet", dest="onglet", help="Default: the first sheet with the columns ID KPI and Year.")
        parser.add_argument("--years", "--annees", dest="annees", type=int, nargs="*", help="Only these reporting years.")
        parser.add_argument("--types", nargs="*", choices=list(TYPES), help="Only these types of KPI.")
        parser.add_argument("--simulation", action="store_true", help="Check the file without saving anything.")

    def handle(self, fichier, onglet, annees, types, simulation, **o):
        r = importer_valeurs(fichier, onglet, annees=annees, types=[TYPES[t] for t in types] if types else None, simulation=simulation)
        self.stdout.write(f"{r.crees} values {'to import' if simulation else 'imported'}.")
        for _, m in r.avertissements:
            self.stdout.write(f"  {m}")
