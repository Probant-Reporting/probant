import csv

from django.core.management.base import BaseCommand, CommandError

from espaces import contexte as ESP
from referentiel.models import Organisation, OrgAlias


class Command(BaseCommand):
    help = "Imports external names of organisations (CSV: source, libelle, organisation)."

    def add_arguments(self, parser):
        parser.add_argument("fichier", metavar="file", help="CSV file (UTF-8).")

    def handle(self, fichier, **o):
        orgs = {x.nom: x for x in Organisation.objects.all()}
        lignes, inconnues = [], []
        with open(fichier, encoding="utf-8") as f:
            for ligne in csv.DictReader(f):
                org = orgs.get(ligne["organisation"].strip())
                if not org:
                    inconnues.append(ligne["organisation"])
                    continue
                lignes.append((ligne["source"].strip(), ligne["libelle"].strip(), org))
        if inconnues:  # tout ou rien 
            raise CommandError("Unknown organisations: " + ", ".join(inconnues) + ". Correct these lines, then import again: "
                               "nothing has been saved.")
        with ESP.atomic():
            for source, libelle, org in lignes:
                OrgAlias.objects.update_or_create(source=source, libelle=libelle, defaults={"organisation": org})
        self.stdout.write(f"{len(lignes)} aliases saved.")
