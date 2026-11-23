from django.core.management.base import BaseCommand, CommandError

from referentiel.echange import importer_kpi


class Command(BaseCommand):
    help = "Imports the KPI framework from the Excel file (KPI sheet, technical format of the former framework files)."

    def add_arguments(self, parser):
        parser.add_argument("fichier", metavar="file", help="Excel file (.xlsx).")
        parser.add_argument("--simulation", action="store_true", help="Check the file without saving anything.")

    def handle(self, fichier, simulation, **o):
        rapport = importer_kpi(fichier, simulation=simulation)
        self.stdout.write(str(rapport))
        if rapport.erreurs:
            raise CommandError("Import cancelled: fix the errors above.")
        if simulation:
            self.stdout.write("Simulation: nothing was saved.")
