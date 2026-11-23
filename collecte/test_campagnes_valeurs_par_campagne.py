"""Page Administration › Campagnes : la colonne « Valeurs » compte les valeurs saisies ou importées des KPI de la campagne
(``saisie.codes_campagne``), et non celles de toute sa période. Avant : une campagne d'un référentiel sans aucune valeur
affichait les valeurs des autres référentiels de la même période."""
from django.urls import reverse

from referentiel.models import ElementReferentiel, Referentiel

from .aides_tests.saisie import Base
from .models import Campagne


class ValeursParCampagneTests(Base):
    def test_valeurs_de_la_campagne_seulement(self):
        ElementReferentiel.objects.get_or_create(referentiel=self.c.referentiel, kpi=self.eff)
        autre = Referentiel.objects.create(code="AUTRE", nom="Autre", ordre=99)
        ElementReferentiel.objects.create(referentiel=autre, kpi=self.taux)
        voisine = Campagne.objects.create(referentiel=autre, periode=self.c.periode, exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.enregistrer("12")
        self.enregistrer("13", org=self.e2, user=self.admin)
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:admin_campagnes"))
        campagnes = {c.pk: c for _, cs, _ in rep.context["groupes"] for c in cs}
        self.assertEqual(campagnes[self.c.pk].nb_saisies, 2)
        self.assertEqual(campagnes[voisine.pk].nb_saisies, 0)
