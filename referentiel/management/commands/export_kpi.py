from django.core.management.base import BaseCommand

from referentiel.echange import exporter_kpi


class Command(BaseCommand):
    help = "Exports the KPI framework to an Excel file that can be imported again."

    def add_arguments(self, parser):
        parser.add_argument("fichier", metavar="file", help="Excel file written (.xlsx).")

    def handle(self, fichier, **o):
        exporter_kpi(fichier)
        self.stdout.write(f"Framework exported to {fichier}")
