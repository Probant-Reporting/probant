"""Détail d'un total (``vues_cellule._detail_agregat``) × KPI cumulé depuis les mois × organisation fermée pendant l'année.

Troisième passe du calcul (``qa/calculation_fuzz.py --pages``, graine 38) : un site fermé le 30/06 dont
l'année est incomplète (un de ses mois manque) rend le total de son pays incomplet (« everything counts » : ses valeurs des mois comptent comme des valeurs de l'année) ; le détail du total ne le listait pas : le
total disait « Incomplet : E4 » et E4 n'apparaissait pas dessous. Le détail suit la même règle que la somme
(``Calculateur.compte_sans_valeur``), comme le total partiel de la Consolidation (``consolidation.partiel``). Données
inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Frequence, Niveau, Organisation, Referentiel

from . import calcul as C
from . import periodes as P
from .models import Campagne, Reponse
from .vues_cellule import _detail_agregat

FIN = timezone.localdate() + datetime.timedelta(days=30)


class _SiteFermeAvecMois(TestCase):
    """Groupe › Pays › E1 (12 mois), E4 fermé le 30/06 (janvier à mai) ; X dans un référentiel mensuel et un annuel."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e4 = Organisation.objects.create(nom="E4", niveau_id=Niveau.ENTITY, parent=self.p, actif=False,
                                              date_desactivation=datetime.date(2025, 6, 30))
        self.k = KPI.objects.create(code="X", libelle="X", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                    methode_agregation="Somme")
        mens = Referentiel.objects.create(code="M", nom="Mensuel", ordre=1, frequence=Frequence.MOIS)
        composer({"X": ["S"]}, mens)
        an = Referentiel.objects.create(code="A", nom="Annuel", ordre=2, frequence=Frequence.ANNEE)
        composer({"X": ["S"]}, an)
        self.ca, _ = P.campagne(an, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        for m in range(1, 13):
            cm, _ = P.campagne(mens, datetime.date(2025, m, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
            for o in (self.e1, self.e4):
                if o is self.e1 or m in (1, 2, 3, 4, 5):  # juin manque pour E4, fermé le 30/06
                    Reponse.objects.create(periode=cm.periode, kpi=self.k, organisation=o, valeur=Decimal(1),
                                           statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
            C.recalculer(cm)


class DetailAgregatMoisTests(_SiteFermeAvecMois):
    def test_site_ferme_qui_rend_le_total_incomplet_figure_au_detail(self):
        total = Reponse.objects.get(periode=self.ca.periode, kpi=self.k, organisation=self.p)
        self.assertEqual(total.statut, Reponse.Statut.INCOMPLET)
        self.assertIn("E4", total.message_calcul)
        noms = [n["org"].nom for n in _detail_agregat(self.ca, self.k, self.p)]
        self.assertEqual(noms, ["E1", "E4"])  # avant : ["E1"]

    def test_site_ferme_sans_aucune_valeur_reste_hors_du_detail_comme_de_la_somme(self):
        Reponse.objects.filter(kpi=self.k, organisation=self.e4).delete()
        C.recalculer(self.ca)
        total = Reponse.objects.get(periode=self.ca.periode, kpi=self.k, organisation=self.p)
        self.assertEqual((total.statut, total.valeur), (Reponse.Statut.CALCULE, Decimal(12)))
        self.assertEqual([n["org"].nom for n in _detail_agregat(self.ca, self.k, self.p)], ["E1"])


class PartielConsolidationMoisTests(_SiteFermeAvecMois):
    """Même cas, Consolidation (``consolidation.partiel`` : la somme connue d'un total incomplet et le nombre
    d'organisations qui manquent) : E4 manque (avant : il n'était pas compté, et aucun total partiel n'était montré)."""

    def test_partiel_compte_le_site_ferme_qui_manque(self):
        from referentiel.models import Utilisateur

        from . import consolidation as CO
        from . import visualisation as V

        admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        Reponse.objects.filter(organisation__in=[self.e1, self.e4]).update(statut=Reponse.Statut.VALIDE)
        source = V.Source(admin, codes=["X"])
        rang = source.calc.rangs[self.p.niveau_id]
        self.assertEqual(CO.partiel(source, self.k, self.p.id, self.ca.periode, rang), (Decimal(12), 1))  # avant : None
