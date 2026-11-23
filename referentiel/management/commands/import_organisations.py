from django.core.management.base import BaseCommand, CommandError

from referentiel.echange import importer_organisations


class Command(BaseCommand):
    help = "Imports the organisations from the \"Organizational structure\" sheet of the KPI and structure definition file."

    def add_arguments(self, parser):
        parser.add_argument("fichier", metavar="file", help="Excel file (.xlsx).")

    def handle(self, fichier, **o):
        rapport = importer_organisations(fichier)
        self.stdout.write(str(rapport))
        if rapport.erreurs:
            raise CommandError("Correct these lines, then import again: nothing has been saved.")
