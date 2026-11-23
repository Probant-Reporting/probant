"""Seconde recette (B1) : Administration › Attributions, « Attribuer à… » une personne sur une case envoie aussi la
campagne affichée ; la page ne doit jamais changer toute seule le filtre Référentiel (avant : le référentiel de cette
campagne devenait celui mémorisé, et au rechargement les KPI des autres référentiels disparaissaient sans message)."""
import json

from django.urls import reverse

from referentiel.models import ElementReferentiel, Referentiel

from .aides_tests.saisie import Base
from .models import Campagne


class FiltreInchangeTests(Base):
    def setUp(self):
        super().setUp()
        ElementReferentiel.objects.create(referentiel=self.c.referentiel, kpi=self.eff)
        self.autre = Referentiel.objects.create(code="AUTRE", nom="Reporting du groupe", ordre=5)
        ElementReferentiel.objects.create(referentiel=self.autre, kpi=self.taux)
        self.c_autre = Campagne.objects.create(referentiel=self.autre, periode=self.c.periode, exercice=self.c.exercice,
                                               statut=Campagne.Statut.OUVERTE)
        self.client.force_login(self.admin)

    def attribuer(self, campagne):
        return self.client.post(reverse("collecte:attribuer"), json.dumps(
            {"cles": [f"{self.eff.pk}|{self.e2.pk}"], "utilisateur": self.contrib.pk, "campagne": campagne.pk,
             "format": "cellule"}), content_type="application/json")

    def kpis_affiches(self):
        html = self.client.get(reverse("collecte:admin_attributions")).content.decode()
        return {code for code in ("EFF", "TX") if f'data-kpi="{code}"' in html or f">{code}<" in html}

    def test_tous_les_referentiels_reste_tous(self):
        self.client.get(reverse("collecte:admin_attributions") + "?ref=")
        avant = self.kpis_affiches()
        self.assertEqual(avant, {"EFF", "TX"})
        self.assertEqual(self.attribuer(self.c_autre).status_code, 200)
        self.assertEqual(self.client.session.get("referentiel"), "")
        self.assertEqual(self.kpis_affiches(), avant)

    def test_un_referentiel_choisi_reste_choisi(self):
        self.client.get(reverse("collecte:admin_attributions") + f"?ref={self.c.referentiel_id}")
        self.attribuer(self.c_autre)
        self.assertEqual(self.client.session.get("referentiel"), self.c.referentiel_id)
