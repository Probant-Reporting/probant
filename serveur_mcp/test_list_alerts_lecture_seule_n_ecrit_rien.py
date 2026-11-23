"""Assistants (``list_alerts``) : l'outil refait la détection des alertes à l'ouverture comme la page Cohérence, sauf pour
un compte en lecture seule (lecteur, auditeur), qui n'écrit jamais rien ; il reste borné aux droits de la personne pour une
campagne en préparation, que seul l'administrateur ouvre."""
from collecte.models import Alerte, Campagne, RegleCoherence
from referentiel.models import Niveau

from .aides_tests import MODERNE, BaseMCP
from .models import ReglageMCP


class ListAlertsEcritureTests(BaseMCP):
    def setUp(self):
        super().setUp()
        ReglageMCP.objects.filter(pk=1).update(lecteur_lit=True)
        RegleCoherence.objects.create(nom="Effectif minimal", gauche="[EFF]", operateur=">=", droite="500", niveau_id=Niveau.ENTITY)
        self.assertEqual(Alerte.objects.count(), 0)

    def lister(self, role):
        _, res, d = self.outil(role, "list_alerts", {"campaign_id": self.c.pk, "status": "all"}, MODERNE)
        self.assertFalse(res["isError"], d)
        return d

    def test_lecteur_et_auditeur_ne_creent_aucune_alerte(self):
        for role in ("lecteur", "auditeur"):
            self.lister(role)
            self.assertEqual(Alerte.objects.count(), 0, role)

    def test_l_admin_les_detecte_comme_la_page(self):
        self.lister("admin")
        self.assertGreater(Alerte.objects.count(), 0)


class CampagneEnPreparationTests(BaseMCP):
    def setUp(self):
        super().setUp()
        ReglageMCP.objects.filter(pk=1).update(lecteur_lit=True)
        self.prep = Campagne.objects.create(exercice=2027, statut=Campagne.Statut.PREPARATION)

    def test_refusee_hors_administrateur(self):
        for role in ("contributeur", "validateur", "auditeur", "lecteur"):
            _, res, d = self.outil(role, "list_organisations", {"campaign_id": self.prep.pk}, MODERNE)
            self.assertTrue(res["isError"], role)

    def test_ouverte_a_l_administrateur(self):
        _, res, d = self.outil("admin", "list_organisations", {"campaign_id": self.prep.pk}, MODERNE)
        self.assertFalse(res["isError"], d)
