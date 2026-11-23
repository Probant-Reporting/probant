"""Correctifs du moteur de calcul trouvés par le test d'équivalence du recalcul ciblé, écrits à la main.

1. Organisation fermée pendant la période : elle ne compte dans le total de son parent que si sa branche a une valeur
   sur la période (n'importe quel KPI). Sa première valeur (ou la dernière effacée) change donc les totaux des AUTRES KPI
   au-dessus d'elle ; avant, seuls le KPI saisi et ses dépendants étaient refaits, et ces totaux restaient faux jusqu'à
   une saisie de leur propre KPI (``calcul.kpis_a_refaire``).
2. [X@AAAA] qui cite sa propre période : le message « Source manquante » ne dépend plus du chemin par lequel la case
   est calculée (directement, ou citée depuis une autre case) : « A (2026) » dans les deux cas.
3. Constat (comportement voulu, gardé) : une période clôturée n'est pas recalculée quand une période ouverte qu'elle
   cite change. Une correction importée dans la période clôturée ne refait plus que l'organisation corrigée et ses
   totaux au-dessus ; avant, elle refaisait ses KPI dépendants dans toutes les
   organisations et reprenait au passage les changements des périodes ouvertes citées.

Données inventées uniquement."""
import datetime
from decimal import Decimal

from django.test import TestCase

from referentiel.models import KPI, Niveau, Organisation

from .calcul import Calculateur, recalculer
from .models import Campagne, Reponse
from .signals import en_lot, signaler

D = Decimal


class Base(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)

    def kpi(self, code, t="Saisi", f="", agg="Somme"):
        return KPI.objects.create(code=code, libelle=code, type_saisie_id=t, formule=f, granularite_id=Niveau.ENTITY,
                                  methode_agregation=agg)

    def poser(self, c, kpi, org, v, origine=Reponse.Origine.IMPORT):
        """Valeur posée sans recalcul (pas de signal)."""
        Reponse.objects.bulk_create([Reponse(periode=c.periode, kpi_id=kpi, organisation=org, valeur=D(v), origine=origine)])

    def saisir(self, c, kpi, org, v):
        """Comme une saisie à l'écran : enregistrement, puis recalcul automatique (signal)."""
        r = Reponse.objects.filter(periode=c.periode, kpi_id=kpi, organisation=org).first() or Reponse(
            periode=c.periode, kpi_id=kpi, organisation=org)
        r.valeur, r.origine, r.statut = (None if v is None else D(v)), Reponse.Origine.SAISIE, Reponse.Statut.BROUILLON
        r.save()

    def cellule(self, c, kpi, org):
        r = Reponse.objects.get(periode=c.periode, kpi_id=kpi, organisation=org)
        return r.statut, r.valeur, r.message_calcul


class OrganisationFermeeTotauxDesAutresKpiTests(Base):
    def setUp(self):
        super().setUp()
        self.e1.actif, self.e1.date_desactivation = False, datetime.date(2026, 6, 30)  # fermée pendant 2026
        self.e1.save()
        self.kpi("A")
        self.kpi("B")
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.poser(self.c, "A", self.e2, 5)
        self.poser(self.c, "B", self.e2, 7)
        recalculer(self.c)

    def test_premiere_valeur_de_l_organisation_fermee(self):
        # E1, fermée sans aucune valeur : écartée des totaux
        self.assertEqual(self.cellule(self.c, "B", self.p)[:2], (Reponse.Statut.CALCULE, D(7)))
        self.saisir(self.c, "A", self.e1, 3)  # sa première valeur : elle compte, B lui manque
        self.assertEqual(self.cellule(self.c, "A", self.p)[:2], (Reponse.Statut.CALCULE, D(8)))
        self.assertEqual(self.cellule(self.c, "B", self.p), (Reponse.Statut.INCOMPLET, None, "Incomplet : E1"))  # avant : 7
        self.assertEqual(self.cellule(self.c, "B", self.g), (Reponse.Statut.INCOMPLET, None, "Incomplet : Pays"))

    def test_derniere_valeur_effacee(self):
        self.saisir(self.c, "A", self.e1, 3)
        self.saisir(self.c, "A", self.e1, None)  # plus aucune valeur : de nouveau écartée
        self.assertEqual(self.cellule(self.c, "B", self.p)[:2], (Reponse.Statut.CALCULE, D(7)))  # avant : incomplet
        self.assertEqual(self.cellule(self.c, "A", self.p)[:2], (Reponse.Statut.CALCULE, D(5)))

    def test_meme_resultat_qu_un_recalcul_complet(self):
        self.saisir(self.c, "A", self.e1, 3)
        apres_saisie = sorted(Reponse.objects.values_list("kpi_id", "organisation_id", "statut", "valeur", "message_calcul"))
        recalculer(self.c)
        self.assertEqual(sorted(Reponse.objects.values_list("kpi_id", "organisation_id", "statut", "valeur",
                                                            "message_calcul")), apres_saisie)


class MessageSourceManquanteAnneeFixeTests(Base):
    def setUp(self):
        super().setUp()
        self.kpi("A")
        self.kpi("X", "Calculé", "[A@2026] + [A]")  # [A@2026] dans la campagne 2026 : la période elle-même
        self.kpi("Y", "Calculé", "[X@2026] * 2")
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)

    def test_meme_message_quel_que_soit_le_chemin(self):
        direct = Calculateur(self.c)
        self.assertIsNone(direct.valeur("X", self.e1.id))
        cite = Calculateur(self.c)
        self.assertIsNone(cite.valeur("Y", self.e1.id))  # X calculé d'abord parce que Y le cite par [X@2026]
        self.assertIsNone(cite.valeur("X", self.e1.id))
        self.assertEqual(direct.message("X", self.e1.id), "Source manquante : A (2026)")
        self.assertEqual(cite.message("X", self.e1.id), "Source manquante : A (2026)")  # avant : « A »


class PeriodeClotureeTests(Base):
    """Constat 3 (comportement voulu) : 2025 ouverte, 2026 clôturée ; X = [A] + [A@N-1]."""

    def test_cloturee_figee_puis_correction_importee(self):
        self.kpi("A")
        self.kpi("X", "Calculé", "[A] + [A@N-1]")
        c25 = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.OUVERTE)
        c26 = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.CLOTUREE)
        for org, v25, v26 in ((self.e1, 10, 1), (self.e2, 20, 2)):
            self.poser(c25, "A", org, v25)
            self.poser(c26, "A", org, v26)
        recalculer(c25)
        recalculer(c26)
        self.assertEqual(self.cellule(c26, "X", self.e1)[1], D(11))
        self.saisir(c25, "A", self.e1, 100)  # saisie dans 2025 : 2026, clôturée, n'est pas recalculée
        self.assertEqual(self.cellule(c26, "X", self.e1)[1], D(11))
        # correction importée dans 2026 pour E2 (comme ``imports._ecrire_historique`` : un recalcul en fin de lot) :
        # seuls E2 et ses totaux au-dessus sont refaits ; E1 garde son chiffre publié (avant : 101)
        with en_lot():
            r = Reponse.objects.get(periode=c26.periode, kpi_id="A", organisation=self.e2)
            r.valeur, r.statut = D(3), Reponse.Statut.VALIDE
            r.save()
            signaler(r)
        self.assertEqual(self.cellule(c26, "X", self.e2)[1], D(23))
        self.assertEqual(self.cellule(c26, "X", self.e1)[1], D(11))
        self.assertEqual(self.cellule(c26, "X", self.p)[1], D(34))  # somme des chiffres affichés : 11 + 23
        self.assertEqual(self.cellule(c26, "A", self.p)[1], D(4))
