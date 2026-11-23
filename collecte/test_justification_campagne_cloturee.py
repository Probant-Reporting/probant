"""Alerte d'une campagne clôturée : « administrateur seulement » (règle du projet). Après la clôture
définitive, ni le contributeur ni le validateur ne justifient plus une alerte : ni sur sa fiche, ni dans le panneau de
saisie, ni par l'outil MCP ``justify_alert`` ; le formulaire disparaît et une explication le dit. L'administrateur finit sa
revue (justifier, accepter, rejeter, ignorer). Une campagne en revue (clôture des contributeurs, pas encore définitive)
garde le comportement d'avant : le validateur y justifie encore. Une seule règle (``coherence.motif_justification_refusee``),
refaite sous verrou dans ``coherence.traiter`` ; une justification déjà enregistrée reste telle quelle."""
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils.html import escape

from parametres.libelles import libelle
from serveur_mcp.aides_tests import BaseMCP

from . import coherence as CO
from .models import Alerte, Campagne

EXPLICATION = "saisie.coherence.alerte.campagne_cloturee"


class JustificationCampagneClotureeTests(BaseMCP):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.c0.statut, Campagne.Statut.CLOTUREE)
        self.alerte = Alerte.objects.create(campagne=self.c0, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.FORMAT,
                                            message="Valeur négative.")

    def page(self, u):
        c = Client()
        c.force_login(u)
        return c

    def fiche(self):
        return reverse("collecte:alerte", args=[self.alerte.pk])

    def statut(self):
        return Alerte.objects.get(pk=self.alerte.pk).statut

    def test_regle_unique(self):
        self.assertEqual(CO.motif_justification_refusee(self.validateur, self.alerte), libelle(EXPLICATION))
        self.assertEqual(CO.motif_justification_refusee(self.admin, self.alerte), "")
        self.assertFalse(CO.peut_justifier(self.validateur, self.alerte))

    def test_fiche_sans_formulaire_avec_explication(self):
        rep = self.page(self.validateur).get(self.fiche())
        self.assertEqual(rep.status_code, 200)
        self.assertNotContains(rep, 'value="justifier"')
        self.assertContains(rep, escape(libelle(EXPLICATION)))
        rep = self.page(self.admin).get(self.fiche())  # l'administrateur finit sa revue
        self.assertContains(rep, 'value="justifier"')
        self.assertContains(rep, 'value="ignorer"')

    def test_fiche_refuse_le_post(self):
        rep = self.page(self.validateur).post(self.fiche(), {"action": "justifier", "texte": "Parce que"})
        self.assertContains(rep, escape(libelle(EXPLICATION)))
        self.assertEqual(self.statut(), Alerte.Statut.OUVERTE)

    def test_outil_mcp_refus_clair(self):
        _, res, d = self.outil("validateur", "justify_alert", {"alert_id": self.alerte.pk, "text": "Parce que"})
        self.assertTrue(res["isError"])
        self.assertEqual(d["error"]["message"], libelle(EXPLICATION))
        self.assertEqual(self.statut(), Alerte.Statut.OUVERTE)

    def test_panneau_explique_et_refuse(self):
        url = reverse("collecte:cellule", args=[self.c0.pk, self.eff.pk, self.e1.pk])
        rep = self.page(self.validateur).get(url)
        self.assertContains(rep, escape(libelle(EXPLICATION)))
        self.assertNotContains(rep, f'id="justif-{self.alerte.pk}"')
        rep = self.page(self.validateur).post(url, {"action": "justifier", "alerte": self.alerte.pk, "justification": "x"})
        self.assertEqual(rep.status_code, 403)
        self.assertEqual(self.statut(), Alerte.Statut.OUVERTE)

    def test_administrateur_finit_sa_revue(self):
        CO.traiter(self.admin, self.alerte, "justifier", "Reprise de provision")
        CO.traiter(self.admin, self.alerte, "rejeter", "Pas convaincant")
        self.assertEqual(self.statut(), Alerte.Statut.REJETEE)
        CO.traiter(self.admin, self.alerte, "rouvrir")
        CO.traiter(self.admin, self.alerte, "ignorer")
        self.assertEqual(self.statut(), Alerte.Statut.IGNOREE)

    def test_controle_refait_sous_verrou(self):
        """La page a été lue avant la clôture : la campagne relue sous verrou décide."""
        Campagne.objects.filter(pk=self.c0.pk).update(statut=Campagne.Statut.REVUE)
        a = Alerte.objects.select_related("campagne").get(pk=self.alerte.pk)  # lue « en revue »
        Campagne.objects.filter(pk=self.c0.pk).update(statut=Campagne.Statut.CLOTUREE)  # clôturée entre-temps
        with self.assertRaisesMessage(ValidationError, libelle(EXPLICATION)):
            CO.traiter(self.validateur, a, "justifier", "Parce que")
        self.assertEqual(self.statut(), Alerte.Statut.OUVERTE)

    def test_justification_deja_enregistree_reste(self):
        Alerte.objects.filter(pk=self.alerte.pk).update(statut=Alerte.Statut.JUSTIFIEE, justification="Ancienne explication",
                                                        justifie_par=self.validateur)
        rep = self.page(self.validateur).get(self.fiche())
        self.assertContains(rep, "Ancienne explication")
        self.assertNotContains(rep, 'value="justifier"')  # plus de « compléter »
        a = Alerte.objects.get(pk=self.alerte.pk)
        self.assertEqual((a.statut, a.justification), (Alerte.Statut.JUSTIFIEE, "Ancienne explication"))
        rep = self.page(self.admin).get(self.fiche())
        self.assertContains(rep, 'value="accepter"')

    def test_campagne_en_revue_inchangee(self):
        """Clôture des contributeurs (revue) : le validateur justifie encore, comme avant la décision."""
        Campagne.objects.filter(pk=self.c0.pk).update(statut=Campagne.Statut.REVUE)
        self.alerte.refresh_from_db()
        self.assertEqual(CO.motif_justification_refusee(self.validateur, self.alerte), "")
        rep = self.page(self.validateur).get(self.fiche())
        self.assertContains(rep, 'value="justifier"')
        self.page(self.validateur).post(self.fiche(), {"action": "justifier", "texte": "Reprise de provision"})
        self.assertEqual(self.statut(), Alerte.Statut.JUSTIFIEE)
