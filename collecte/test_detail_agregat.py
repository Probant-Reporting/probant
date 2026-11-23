"""Détail d'un total (panneau de saisie) : il liste les organisations que la somme compte, y compris celles fermées
pendant la période, et toute organisation active, même sans valeur et sans rien à saisir
dessous."""
import datetime
from decimal import Decimal as D

from django.utils import timezone

from .calcul import recalculer
from .models import Reponse
from referentiel.models import Niveau, Organisation
from .aides_tests.arbre import Arbre
from .vues_cellule import _detail_agregat


def _noms(noeuds):
    return {n["org"].nom: _noms(n["sous"]) for n in noeuds}


class DetailAgregatTests(Arbre):
    def setUp(self):
        super().setUp()
        self.k = self.kpi("EFF")
        self.saisir("EFF", self.e1, 10)
        self.saisir("EFF", self.e2, 20)
        self.saisir("EFF", self.e3, 5)

    def fermer(self, org, date):
        org.actif = False
        org.date_desactivation = date
        org.save()

    def test_fermee_pendant_la_periode_listee_comme_dans_la_somme(self):
        self.fermer(self.e2, timezone.localdate())  # ouverte pendant l'exercice 2026 : compte dans la somme
        recalculer(self.c)
        self.assertEqual(self.cellule("EFF", self.p).valeur, D(30))
        detail = _detail_agregat(self.c, self.k, self.p)
        self.assertEqual(_noms(detail), {"E1": {}, "E2": {}})
        self.assertEqual(sum(n["r"].valeur for n in detail), self.cellule("EFF", self.p).valeur)

    def test_fermee_avant_la_periode_absente_comme_dans_la_somme(self):
        self.fermer(self.e2, datetime.date(2020, 1, 31))
        recalculer(self.c)
        self.assertEqual(self.cellule("EFF", self.p).valeur, D(10))
        self.assertEqual(_noms(_detail_agregat(self.c, self.k, self.p)), {"E1": {}})

    def test_fermee_sans_aucune_valeur_ecartee_comme_dans_la_somme(self):
        Reponse.objects.filter(kpi_id="EFF", organisation=self.e2).delete()
        self.fermer(self.e2, timezone.localdate())
        recalculer(self.c)
        self.assertEqual(self.cellule("EFF", self.p).valeur, D(10))
        self.assertEqual(_noms(_detail_agregat(self.c, self.k, self.p)), {"E1": {}})

    def test_arbre_depuis_le_groupe(self):
        self.fermer(self.e2, timezone.localdate())
        recalculer(self.c)
        self.assertEqual(_noms(_detail_agregat(self.c, self.k, self.g)),
                         {"Pays": {"E1": {}, "E2": {}}, "Pays 2": {"E3": {}}})

    def test_active_sans_valeur_listee_avec_valeur_vide(self):
        Reponse.objects.filter(kpi_id="EFF", organisation=self.e2).delete()
        recalculer(self.c)
        detail = _detail_agregat(self.c, self.k, self.p)
        self.assertEqual(_noms(detail), {"E1": {}, "E2": {}})
        e2 = next(n for n in detail if n["org"].nom == "E2")
        self.assertIsNone(e2["r"])
        self.assertIsNone(e2["part"])

    def test_active_sans_rien_a_saisir_dessous_listee(self):
        # un pays sans aucune entité dessous : rien à saisir, mais actif : il figure au détail du groupe
        Organisation.objects.create(nom="Pays vide", niveau_id=Niveau.COUNTRY, parent=self.g)
        recalculer(self.c)
        detail = _detail_agregat(self.c, self.k, self.g)
        self.assertEqual(_noms(detail), {"Pays": {"E1": {}, "E2": {}}, "Pays 2": {"E3": {}}, "Pays vide": {}})

    def test_fermee_sans_valeur_reste_ecartee_meme_avec_une_active_sans_valeur(self):
        Reponse.objects.filter(kpi_id="EFF", organisation=self.e2).delete()
        Reponse.objects.filter(kpi_id="EFF", organisation=self.e3).delete()
        self.fermer(self.e2, timezone.localdate())
        recalculer(self.c)
        self.assertEqual(_noms(_detail_agregat(self.c, self.k, self.g)), {"Pays": {"E1": {}}, "Pays 2": {"E3": {}}})
