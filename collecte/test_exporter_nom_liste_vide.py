"""Constructeur d'export (page Import / Export) : deux bornes.

- Nom d'un export enregistré : coupé à 100 caractères, la longueur du champ (au-delà, PostgreSQL refuserait l'écriture).
- Liste de KPI sauvegardée vide : son nombre de KPI est 0 dans le choix des KPI (``vues_echanges._choix_kpi``)."""
from django.urls import reverse

from . import exports as E
from . import vues_echanges as VE
from .models import ReglageExport, SelectionKPI
from .aides_tests.echanges import Base


class NomEtListeVideTests(Base):
    def test_nom_d_export_coupe_a_100_caracteres(self):
        self.client.force_login(self.admin)
        rep = self.client.post(reverse("collecte:echanges_exporter"), {
            "action": "enregistrer", "nom": "N" * 150, "presentation": "base", "exercices": ["courant"], "niveaux": E.N.codes()})
        self.assertEqual(rep.status_code, 302)
        self.assertEqual(ReglageExport.objects.get(proprietaire=self.admin).nom, "N" * 100)

    def test_liste_vide_zero_kpi(self):
        vide = SelectionKPI.objects.create(nom="Vide", proprietaire=self.admin)
        pleine = SelectionKPI.objects.create(nom="Deux", proprietaire=self.admin)
        pleine.kpis.set([self.eff, self.taux])
        listes = {x.pk: x.nb for x in VE._choix_kpi(self.admin)["listes"]}
        self.assertEqual((listes[vide.pk], listes[pleine.pk]), (0, 2))
