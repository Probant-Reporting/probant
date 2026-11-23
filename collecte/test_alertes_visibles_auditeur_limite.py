"""Cohérence (``coherence.alertes_visibles``) : un auditeur limité à des organisations ne lit que les alertes de ces
organisations, sur la page Cohérence comme dans le dossier d'audit ; sans limite, il les lit toutes."""
from django.urls import reverse

from collecte import coherence as CO
from collecte.aides_tests.lecture_seule import Base
from collecte.models import Alerte


class AlertesAuditeurLimiteTests(Base):
    def setUp(self):
        super().setUp()
        self.dans = Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.FORMAT,
                                          gravite=Alerte.Gravite.ALERTE, message="Alerte dans le périmètre")
        self.hors = Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.g, controle=Alerte.Controle.FORMAT,
                                          gravite=Alerte.Gravite.ALERTE, message="Alerte hors périmètre")

    def pks(self, utilisateur):
        return {a.pk for a in CO.alertes_visibles(utilisateur, self.c)}

    def test_sans_limite_toutes_les_alertes(self):
        self.assertEqual(self.pks(self.auditeur), {self.dans.pk, self.hors.pk})
        self.assertEqual(self.pks(self.admin), {self.dans.pk, self.hors.pk})

    def test_limite_a_une_organisation_seulement_les_siennes(self):
        self.auditeur.perimetre_lecture.add(self.p)  # p, e1 et e2 ; pas g
        from referentiel.models import Utilisateur

        u = Utilisateur.objects.get(pk=self.auditeur.pk)
        self.assertEqual(self.pks(u), {self.dans.pk})

    def test_page_coherence_de_l_auditeur_limite(self):
        self.auditeur.perimetre_lecture.add(self.p)
        self.client.force_login(self.auditeur)
        rep = self.client.get(reverse("collecte:coherence"), {"campagne": self.c.pk})
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, "Alerte dans le périmètre")
        self.assertNotContains(rep, "Alerte hors périmètre")
