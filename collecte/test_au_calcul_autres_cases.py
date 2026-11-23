"""Formules à corriger, cases en erreur au calcul (``formules.au_calcul``) : quelques cases sont données en exemple, la
page dit « … et N autres cases en erreur » pour le reste ; N = nombre de cases en erreur moins les exemples montrés."""
from django.urls import reverse

from parametres.libelles import libelle
from referentiel.models import Niveau, Organisation

from . import formules as FM
from .calcul import recalculer
from .aides_tests.arbre import Arbre


class AutresCasesEnErreurTests(Arbre):
    def setUp(self):
        super().setUp()
        self.e4 = Organisation.objects.create(nom="E4", niveau_id=Niveau.ENTITY, parent=self.p2)
        self.e5 = Organisation.objects.create(nom="E5", niveau_id=Niveau.ENTITY, parent=self.p2)
        self.kpi("A")
        self.kpi("B")
        self.kpi("R", t="Calculé", f="[A] / [B]", agg="Formule")
        for o in (self.e1, self.e2, self.e3, self.e4, self.e5):  # division par zéro dans les cinq entités
            self.saisir("A", o, 10)
            self.saisir("B", o, 0)
        recalculer(self.c)

    def test_nombre_de_cases_au_dela_des_exemples(self):
        # en erreur : les cinq entités, leurs deux pays et le groupe (la formule se refait à chaque niveau), soit 8 cases
        e = next(e for e in FM.au_calcul() if e["kpi"].code == "R")
        self.assertEqual((e["n"], len(e["exemples"]), e["autres"]), (8, FM.EXEMPLES, 8 - FM.EXEMPLES))
        self.client.force_login(self.admin)
        page = self.client.get(reverse("collecte:admin_formules"))
        self.assertContains(page, libelle("admin.formules.autres_cases", n=8 - FM.EXEMPLES))
        self.assertNotContains(page, libelle("admin.formules.autres_cases", n=8 + FM.EXEMPLES))
