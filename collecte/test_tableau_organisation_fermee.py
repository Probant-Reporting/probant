"""Consolidation (``consolidation.tableau``) et Visualisation (``Source.enfants``, ``comparaison``, ``repartition``) ×
organisation fermée pendant la période.

Un site fermé le 30/06/2025 compte dans les totaux de 2025 (il était ouvert pendant la
période). Troisième passe du calcul : la Consolidation n'en montrait pas la ligne, et la Visualisation ne
le montrait ni sous son pays ni dans la répartition, parce que la liste des organisations de la page ne gardait que les
organisations actives aujourd'hui. Le total du pays (20) n'était plus la somme des lignes montrées dessous (10), règle
écrite dans ``consolidation.tableau``. Les organisations sont maintenant celles du périmètre ouvertes pendant la période
(``calcul.ouverte``, la règle des totaux) ; sans période, seulement les actives (comme avant). Données inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Frequence, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import consolidation as CO
from . import periodes as P
from . import visualisation as V
from .models import Campagne, Reponse

FIN = timezone.localdate() + datetime.timedelta(days=30)


class TableauOrganisationFermeeTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p, actif=False,
                                              date_desactivation=datetime.date(2025, 6, 30))
        self.k = KPI.objects.create(code="X", libelle="X", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                    methode_agregation="Somme")
        ref = Referentiel.objects.create(code="A", nom="Annuel", ordre=1, frequence=Frequence.ANNEE)
        composer({"X": ["S"]}, ref)
        self.c, _ = P.campagne(ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        for org in (self.e1, self.e2):
            Reponse.objects.create(periode=self.c.periode, kpi=self.k, organisation=org, valeur=Decimal(10),
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
        C.recalculer(self.c)

    def test_consolidation_total_egal_a_la_somme_des_lignes(self):
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.k, organisation=self.p).valeur, Decimal(20))
        t = CO.tableau(self.admin, self.c.periode, [self.k])
        valeurs = {l.org.nom: l.cases[0].point.valeur for l in t.lignes}
        self.assertEqual(valeurs.get("Pays"), Decimal(20))
        self.assertEqual(valeurs.get("E2"), Decimal(10))  # avant : pas de ligne E2
        self.assertEqual(valeurs["E1"] + valeurs["E2"], valeurs["Pays"])

    def test_visualisation_dessous_et_repartition(self):
        source = V.Source(self.admin, codes=["X"])
        self.assertEqual([o.nom for o in source.enfants(self.p, self.c.periode)], ["E1", "E2"])  # avant : ["E1"]
        parts, total = source.repartition("X", self.p, self.c.periode)
        self.assertEqual(total, Decimal(20))  # avant : 10, pour un total affiché de 20
        self.assertEqual(sorted(str(o) for _, _, _, o in parts), ["E1", "E2"])

    def test_annee_ou_le_site_n_etait_plus_ouvert_inchangee(self):
        c26, _ = P.campagne(self.c.referentiel, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        source = V.Source(self.admin, codes=["X"])
        self.assertEqual([o.nom for o in source.enfants(self.p, c26.periode)], ["E1"])
        self.assertNotIn("E2", [o.nom for o in source.organisations()])  # sans période : les actives, comme avant
