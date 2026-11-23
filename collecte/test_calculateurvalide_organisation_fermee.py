"""Visualisation et Consolidation (``visualisation.CalculateurValide`` avec une liste de KPI) × organisation fermée
pendant la période.

Troisième passe du calcul (``qa/calculation_fuzz.py --pages``, graine 8) : une organisation fermée pendant
la période compte dans le total de son parent si elle a une valeur sur la période, de n'importe quel KPI (« everything
counts », README) ; sans valeur pour ce KPI, elle rend le total incomplet. Le calculateur de la Visualisation, limité aux
KPI du visuel (et aux sources de leurs formules), ne voyait pas ses valeurs des autres KPI : le visuel et la
Consolidation montraient 10 (le total sans elle) là où la Saisie, les exports et le serveur MCP disent « Incomplet ».
Données inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Frequence, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import periodes as P
from . import visualisation as V
from .models import Campagne, Reponse

FIN = timezone.localdate() + datetime.timedelta(days=30)


class CalculateurValideOrganisationFermeeTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p, actif=False,
                                              date_desactivation=datetime.date(2025, 6, 30))
        for code in ("X", "Y"):
            KPI.objects.create(code=code, libelle=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                               methode_agregation="Somme")
        ref = Referentiel.objects.create(code="A", nom="Annuel", ordre=1, frequence=Frequence.ANNEE)
        composer({"X": ["S"], "Y": ["S"]}, ref)
        self.c, _ = P.campagne(ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        for kpi, org in (("X", self.e1), ("Y", self.e1), ("Y", self.e2)):  # E2 : une valeur de Y, pas de X
            Reponse.objects.create(periode=self.c.periode, kpi_id=kpi, organisation=org, valeur=Decimal(10),
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
        C.recalculer(self.c)

    def test_visuel_d_un_kpi_dit_incomplet_comme_la_saisie(self):
        total = Reponse.objects.get(periode=self.c.periode, kpi_id="X", organisation=self.p)
        self.assertEqual((total.statut, total.valeur), (Reponse.Statut.INCOMPLET, None))
        self.assertIn("E2", total.message_calcul)
        for codes in (None, ["X"]):
            with self.subTest(codes=codes):
                point = V.Source(self.admin, codes=codes).point("X", self.p, self.c.periode)
                self.assertIsNone(point.valeur)  # avant, avec codes=["X"] : 10
                self.assertIsNone(V.CalculateurValide(codes).valeur("X", self.p.id, self.c.periode))

    def test_valeur_en_brouillon_de_l_autre_kpi_compte_pour_les_valeurs_validees(self):
        # règle « Tout brouillon compte » (règle du projet, qui remplace « seules les valeurs validées
        # font compter un site fermé », 10) : E2 n'a qu'un brouillon de Y, il compte quand même dans le total de X, qui
        # n'a pas de valeur validée (la Saisie dit « Incomplet »), avec ou sans liste de KPI
        Reponse.objects.filter(kpi_id="Y", organisation=self.e2).update(statut=Reponse.Statut.BROUILLON)
        for codes in (None, ["X"]):
            with self.subTest(codes=codes):
                self.assertIsNone(V.CalculateurValide(codes).valeur("X", self.p.id, self.c.periode))
                self.assertIsNone(V.Source(self.admin, codes=codes).point("X", self.p, self.c.periode).valeur)

    def test_temoin_site_ferme_sans_aucune_valeur(self):
        """Témoin : E2 n'a plus aucune valeur sur la période (ni validée, ni en brouillon) : fermée avant d'avoir rien
        saisi, elle ne compte pas ; le total des valeurs validées est 10 (règle inchangée)."""
        Reponse.objects.filter(organisation=self.e2).delete()
        C.recalculer(self.c)
        for codes in (None, ["X"]):
            with self.subTest(codes=codes):
                self.assertEqual(V.CalculateurValide(codes).valeur("X", self.p.id, self.c.periode), Decimal(10))
