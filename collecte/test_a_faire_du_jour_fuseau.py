"""Relances automatiques autour de minuit (``relances.a_faire_du_jour``) : « déjà relancé aujourd'hui » se lit dans le jour
de l'installation (fuseau ``TIME_ZONE``), pas en temps universel, sous SQLite comme sous PostgreSQL. Une relance partie à
00:30 à Bruxelles (la veille en temps universel) compte pour ce jour-là ; une relance de 23:30 la veille n'y compte pas."""
import datetime

from django.utils import timezone

from . import relances as R
from .models import Relance
from .aides_tests.relances import AVEC_SMTP
from .aides_tests.saisie import Base


@AVEC_SMTP
class DejaRelanceAujourdhui(Base):
    def setUp(self):
        super().setUp()
        self.jour = self.c.date_fin_saisie - datetime.timedelta(days=7)

    def relance_a(self, jour, heure, minute):
        r = Relance.objects.create(destinataire=self.contrib, statut=Relance.Statut.ENVOYEE, nb_a_saisir=1, nb_brouillons=0)
        quand = timezone.make_aware(datetime.datetime.combine(jour, datetime.time(heure, minute)))
        Relance.objects.filter(pk=r.pk).update(date=quand)
        return quand

    def relances(self):
        return {af.personne.pk for af in R.a_faire_du_jour([self.c], self.jour)}

    def test_relance_juste_apres_minuit_compte_pour_le_jour(self):
        self.assertIn(self.contrib.pk, self.relances())
        quand = self.relance_a(self.jour, 0, 30)
        self.assertNotEqual(quand.astimezone(datetime.timezone.utc).date(), self.jour)  # la veille en temps universel
        self.assertNotIn(self.contrib.pk, self.relances())

    def test_relance_de_la_veille_au_soir_ne_compte_pas(self):
        self.relance_a(self.jour - datetime.timedelta(days=1), 23, 30)
        self.assertIn(self.contrib.pk, self.relances())
