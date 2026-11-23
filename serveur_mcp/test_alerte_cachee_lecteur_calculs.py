"""Réglage « un lecteur peut lire par un assistant » allumé : une alerte dont le constat cite une valeur CALCULÉE depuis un
brouillon (total d'un pays, KPI calculé, détail d'une valeur saisie au-dessus) n'est pas montrée au lecteur, comme la
valeur elle-même (« en attente »). Avant, seules les cases saisies de l'organisation de l'alerte étaient regardées : une
règle au niveau du pays (« [EFF] >= 500 ») donnait au lecteur le total 150 fait de deux brouillons.

Données inventées uniquement."""
from collecte import calcul as C
from collecte import coherence as CO
from collecte.models import Alerte, RegleCoherence, Reponse
from referentiel.models import Niveau

from .aides_tests import MODERNE, BaseMCP
from .models import ReglageMCP


class AlerteCalculeeLecteurTests(BaseMCP):
    def setUp(self):
        super().setUp()
        ReglageMCP.objects.filter(pk=1).update(lecteur_lit=True)
        C.recalculer(self.c)

    def valider_tout(self):
        Reponse.objects.filter(periode=self.c.periode, origine="saisie").update(statut=Reponse.Statut.VALIDE)
        C.recalculer(self.c)

    def alertes(self, role="lecteur"):
        _, res, d = self.outil(role, "list_alerts", {"campaign_id": self.c.pk, "status": "all"}, MODERNE)
        self.assertFalse(res["isError"], d)
        return d["alerts"]

    def test_regle_sur_un_total_fait_de_brouillons(self):
        regle = RegleCoherence.objects.create(nom="Effectif du pays", gauche="[EFF]", operateur=">=", droite="500",
                                              niveau_id=Niveau.COUNTRY)
        CO.controler(self.c)
        a = Alerte.objects.get(regle=regle, organisation=self.p)
        self.assertIn(a.pk, [x["id"] for x in self.alertes("auditeur")])  # l'auditeur voit ce que montrent ses pages
        self.assertNotIn(a.pk, [x["id"] for x in self.alertes()])  # 110 + 40 en brouillon : rien pour le lecteur
        self.valider_tout()
        CO.controler(self.c)
        self.assertIn(a.pk, [x["id"] for x in self.alertes()])

    def test_regle_sur_un_kpi_calcule_depuis_un_brouillon(self):
        regle = RegleCoherence.objects.create(nom="Double", gauche="[DBL]", operateur=">=", droite="500",
                                              niveau_id=Niveau.ENTITY)
        CO.controler(self.c)
        a = Alerte.objects.get(regle=regle, organisation=self.e1)
        self.assertNotIn(a.pk, [x["id"] for x in self.alertes()])  # 2 × 110 en brouillon
        self.valider_tout()
        CO.controler(self.c)
        self.assertIn(a.pk, [x["id"] for x in self.alertes()])

    def test_ecart_avec_le_detail_fait_de_brouillons(self):
        # valeur saisie au niveau du pays, validée ; le détail (110 + 40) est fait de brouillons
        a = Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.p, controle=Alerte.Controle.DETAIL,
                                  message="écart avec le détail", valeur="300", reference="détail : 150")
        Reponse.objects.filter(periode=self.c.periode, kpi=self.eff, organisation=self.p).delete()
        Reponse.objects.create(periode=self.c.periode, kpi=self.eff, organisation=self.p, valeur=300, statut="valide",
                               origine="saisie")
        self.assertNotIn(a.pk, [x["id"] for x in self.alertes()])
        self.valider_tout()
        self.assertIn(a.pk, [x["id"] for x in self.alertes()])
