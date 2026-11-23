"""Alerte « calcul impossible » : personne ne la justifie, nulle part. Le panneau de
saisie le refusait déjà ; la fiche de l'alerte (/coherence/alerte/<n>/) et l'outil MCP ``justify_alert`` l'acceptaient, et
l'alerte justifiée sortait de « À traiter ». Une seule règle (``coherence.justifiable``), lue par le panneau, la fiche et
``coherence.traiter`` (donc par l'outil MCP) ; la même explication partout. Une alerte justifiée ainsi avant la mise à
jour reste telle quelle (rien n'est réécrit). Un calcul impossible est vu par l'administrateur et le validateur."""
from django.test import Client
from django.urls import reverse
from django.utils.html import escape

from parametres.libelles import libelle
from serveur_mcp.aides_tests import BaseMCP

from . import coherence as CO
from .models import Alerte

EXPLICATION = "saisie.coherence.alerte.calcul_non_justifiable"


class CalculImpossibleTests(BaseMCP):
    def setUp(self):
        super().setUp()
        self.calc_alerte = Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e1, gravite=Alerte.Gravite.INFO,
                                                 controle=Alerte.Controle.CALCUL, message="Calcul impossible.")

    def page(self, u):
        c = Client()
        c.force_login(u)
        return c

    def fiche(self, a=None):
        return reverse("collecte:alerte", args=[(a or self.calc_alerte).pk])

    def statut(self, a=None):
        return Alerte.objects.get(pk=(a or self.calc_alerte).pk).statut

    def test_fiche_refuse_et_explique(self):
        for u in (self.validateur, self.admin):
            with self.subTest(role=u.role):
                rep = self.page(u).post(self.fiche(), {"action": "justifier", "texte": "Parce que"})
                self.assertContains(rep, escape(libelle(EXPLICATION)))
                self.assertEqual(self.statut(), Alerte.Statut.OUVERTE)

    def test_fiche_sans_formulaire_de_justification(self):
        rep = self.page(self.validateur).get(self.fiche())
        self.assertEqual(rep.status_code, 200)
        self.assertNotContains(rep, 'name="texte"')
        self.assertNotContains(rep, 'value="justifier"')
        self.assertContains(rep, escape(libelle(EXPLICATION)))
        rep = self.page(self.admin).get(self.fiche())  # l'administrateur peut toujours l'ignorer
        self.assertNotContains(rep, 'value="justifier"')
        self.assertContains(rep, 'value="ignorer"')
        self.assertContains(rep, escape(libelle(EXPLICATION)))

    def test_outil_mcp_refus_clair(self):
        _, res, d = self.outil("validateur", "justify_alert", {"alert_id": self.calc_alerte.pk, "text": "Parce que"})
        self.assertTrue(res["isError"])
        self.assertEqual(d["error"]["message"], libelle(EXPLICATION))
        self.assertEqual(self.statut(), Alerte.Statut.OUVERTE)

    def test_panneau_meme_explication(self):
        url = reverse("collecte:cellule", args=[self.c.pk, self.eff.pk, self.e1.pk])
        rep = self.page(self.validateur).get(url)
        self.assertContains(rep, escape(libelle(EXPLICATION)))
        rep = self.page(self.validateur).post(url, {"action": "justifier", "alerte": self.calc_alerte.pk, "justification": "x"})
        self.assertEqual(rep.status_code, 403)
        self.assertEqual(self.statut(), Alerte.Statut.OUVERTE)

    def test_traiter_refuse(self):
        from django.core.exceptions import ValidationError

        with self.assertRaisesMessage(ValidationError, libelle(EXPLICATION)):
            CO.traiter(self.admin, self.calc_alerte, "justifier", "Parce que")
        self.assertEqual(self.statut(), Alerte.Statut.OUVERTE)
        CO.traiter(self.admin, self.calc_alerte, "ignorer")  # la décision de l'administrateur reste possible
        self.assertEqual(self.statut(), Alerte.Statut.IGNOREE)

    def test_deja_justifiee_avant_la_mise_a_jour_reste_telle_quelle(self):
        Alerte.objects.filter(pk=self.calc_alerte.pk).update(statut=Alerte.Statut.JUSTIFIEE, justification="Ancienne explication")
        rep = self.page(self.validateur).get(self.fiche())
        self.assertContains(rep, "Ancienne explication")
        self.assertNotContains(rep, 'value="justifier"')  # plus de « compléter »
        self.page(self.validateur).post(self.fiche(), {"action": "justifier", "texte": "Encore"})
        a = Alerte.objects.get(pk=self.calc_alerte.pk)
        self.assertEqual((a.statut, a.justification), (Alerte.Statut.JUSTIFIEE, "Ancienne explication"))
        rep = self.page(self.admin).get(self.fiche())  # l'administrateur décide comme avant
        self.assertContains(rep, 'value="accepter"')

    def test_une_autre_alerte_se_justifie_toujours(self):
        a = Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.FORMAT,
                                  message="Valeur négative.")
        self.page(self.validateur).post(self.fiche(a), {"action": "justifier", "texte": "Reprise de provision"})
        self.assertEqual(self.statut(a), Alerte.Statut.JUSTIFIEE)
