from django.core.management.base import BaseCommand, CommandError

from collecte.calcul import recalculer
from collecte.models import Campagne


class Command(BaseCommand):
    help = "Recomputes the calculated, aggregated and cumulative values of a campaign (reporting year, or identifier with --campaign)."

    def add_arguments(self, parser):
        parser.add_argument("exercice", type=int, nargs="?", metavar="year", help="Reporting year (annual campaign).")
        parser.add_argument("--campaign", "--campagne", dest="campagne", type=int, metavar="ID",
                            help="Identifier of the campaign (framework and period).")

    def handle(self, exercice=None, campagne=None, **o):
        qs = Campagne.objects.filter(pk=campagne) if campagne else Campagne.objects.filter(exercice=exercice, periode__type="annee")
        c = qs.first()
        if c is None:
            raise CommandError("Campaign not found.")
        n = recalculer(c)
        self.stdout.write(f"{c.nom_complet}: {n} cells updated.")
