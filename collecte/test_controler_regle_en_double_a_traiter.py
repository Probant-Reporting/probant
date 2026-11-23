"""Alertes d'une règle en double (même condition qu'une autre règle, ``coherence.doublons``) : toute alerte « à traiter »
de la règle écartée passe « corrigée », qu'elle soit ouverte ou rejetée ; une alerte justifiée ou acceptée garde son
statut et sa justification.

Défaut corrigé : seule l'alerte « ouverte » passait « corrigée » ; une alerte dont la justification avait été rejetée
(statut « rejetée », compté « à traiter » : ``Alerte.A_TRAITER``) restait à traiter pour toujours, même une fois la valeur
corrigée, car la règle écartée n'est plus contrôlée."""
from decimal import Decimal

from referentiel.models import Niveau

from . import coherence as CO
from .aides_tests.saisie import Base
from .models import Alerte, RegleCoherence, Reponse

D = Decimal


class RegleEnDoubleAlerteATraiterTests(Base):
    def setUp(self):
        super().setUp()
        self.a = RegleCoherence.objects.create(nom="Règle A", gauche="[EFF]", operateur="<=", droite="10", niveau_id=Niveau.ENTITY)
        self.b = RegleCoherence.objects.create(nom="Règle B", gauche="[EFF]", operateur="<=", droite="10", niveau_id=Niveau.ENTITY)
        self.reponses = {org: Reponse.objects.create(periode=self.c.periode, kpi=self.eff, organisation=org, valeur=D(20),
                                                     statut=Reponse.Statut.BROUILLON) for org in (self.e1, self.e2)}
        commun = dict(campagne=self.c, kpi=self.eff, controle=Alerte.Controle.REGLE, regle=self.b, message="x", empreinte="20|10")
        self.rejetee = Alerte.objects.create(organisation=self.e1, statut=Alerte.Statut.REJETEE, justification="Motif", **commun)
        self.acceptee = Alerte.objects.create(organisation=self.e2, statut=Alerte.Statut.ACCEPTEE, justification="Explication", **commun)

    def test_rejetee_de_la_regle_ecartee_passe_corrigee_apres_correction(self):
        self.assertEqual(CO.doublons([self.a, self.b]), {self.b.pk: self.a})
        CO.controler(self.c)  # valeur 20 : le constat reste à traiter sur la règle gardée
        self.assertEqual(Alerte.objects.get(regle=self.a, organisation=self.e1).statut, Alerte.Statut.OUVERTE)
        r = self.reponses[self.e1]
        r.valeur = D(5)
        r.save()
        CO.controler(self.c)
        self.rejetee.refresh_from_db()
        self.assertEqual(self.rejetee.statut, Alerte.Statut.CORRIGEE)
        self.assertEqual(Alerte.objects.get(regle=self.a, organisation=self.e1).statut, Alerte.Statut.CORRIGEE)
        self.assertFalse(Alerte.objects.filter(campagne=self.c, organisation=self.e1, statut__in=Alerte.A_TRAITER).exists())

    def test_acceptee_de_la_regle_ecartee_garde_son_statut(self):
        CO.controler(self.c)
        self.acceptee.refresh_from_db()
        self.assertEqual((self.acceptee.statut, self.acceptee.justification), (Alerte.Statut.ACCEPTEE, "Explication"))
