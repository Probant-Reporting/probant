"""Une correction importée dans une campagne clôturée ne refait que l'organisation corrigée
et ses totaux au-dessus (plus ses descendants pour un paramètre hérité) ; les autres organisations de la campagne
clôturée gardent leurs chiffres publiés (``calcul._recalculer``, ``calcul.organisations_touchees``).

Dans une campagne clôturée, la saisie, le N/A saisi et la valeur forcée sont refusés (``saisie.droits``,
``forcage._possible``) : la seule écriture possible est l'import d'historique (valeur ou N/A), qui recalcule en fin de
lot (``imports._ecrire_historique``, ``signals.en_lot``). Cas voisins de ``test_calcul_correctifs.PeriodeClotureeTests``.

Données inventées uniquement."""
from decimal import Decimal

from django.test import TestCase

from referentiel.models import KPI, Niveau, Organisation

from .calcul import recalculer
from .models import Campagne, Reponse
from .signals import en_lot, signaler

D = Decimal


class CorrectionCampagneClotureeTests(TestCase):
    """Groupe > P1 > {E1, E2} ; Groupe > P2 > {E3}. X = [A] + [A@N-1] ; 2025 ouverte, 2026 clôturée."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p1 = Organisation.objects.create(nom="P1", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.p2 = Organisation.objects.create(nom="P2", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p1)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p1)
        self.e3 = Organisation.objects.create(nom="E3", niveau_id=Niveau.ENTITY, parent=self.p2)
        self.kpi("A")
        self.kpi("X", "Calculé", "[A] + [A@N-1]")
        self.c25 = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.OUVERTE)
        self.c26 = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        for org, v25, v26 in ((self.e1, 10, 1), (self.e2, 20, 2), (self.e3, 30, 3)):
            self.poser(self.c25, "A", org, v25)
            self.poser(self.c26, "A", org, v26)
        recalculer(self.c25)
        recalculer(self.c26)
        Campagne.objects.filter(pk=self.c26.pk).update(statut=Campagne.Statut.CLOTUREE)
        # 2025 change après la clôture de 2026 : un recalcul complet de 2026 changerait E1, E2 et E3
        Reponse.objects.filter(periode=self.c25.periode, kpi_id="A").update(valeur=D(100))
        recalculer(self.c25, propager=False)

    def kpi(self, code, t="Saisi", f="", gran=Niveau.ENTITY):
        return KPI.objects.create(code=code, libelle=code, type_saisie_id=t, formule=f, granularite_id=gran,
                                  methode_agregation="Somme" if t != "FE" else "Aucune")

    def poser(self, c, kpi, org, v, origine=Reponse.Origine.IMPORT):
        Reponse.objects.bulk_create([Reponse(periode=c.periode, kpi_id=kpi, organisation=org, valeur=D(v), origine=origine)])

    def importer(self, kpi, org, valeur=None, na=False):
        """Comme ``imports._ecrire_historique`` dans la campagne clôturée : import validé, recalcul en fin de lot."""
        with en_lot():
            r = Reponse.objects.filter(periode=self.c26.periode, kpi_id=kpi, organisation=org).first() or Reponse(
                periode=self.c26.periode, kpi_id=kpi, organisation=org)
            r.valeur, r.non_applicable = (None if na else D(valeur)), na
            r.statut, r.origine = Reponse.Statut.VALIDE, Reponse.Origine.IMPORT
            r.save()
            signaler(r)

    def valeur(self, kpi, org):
        r = Reponse.objects.get(periode=self.c26.periode, kpi_id=kpi, organisation=org)
        return "N/A" if r.non_applicable else r.valeur

    def etat(self, orgs):
        return sorted(Reponse.objects.filter(periode=self.c26.periode, organisation__in=orgs)
                      .values_list("kpi_id", "organisation_id", "valeur", "non_applicable", "statut", "message_calcul"))

    def test_autre_branche_et_organisation_soeur_inchangees(self):
        avant = self.etat([self.e2, self.e3, self.p2])
        self.importer("A", self.e1, 5)
        self.assertEqual(self.etat([self.e2, self.e3, self.p2]), avant)  # E2, E3, P2 : chiffres publiés gardés
        self.assertEqual(self.valeur("X", self.e1), D(105))  # E1 corrigée : refaite (avec le 2025 d'aujourd'hui)
        self.assertEqual(self.valeur("X", self.p1), D(105 + 22))  # E2 : 2 + 20, tel qu'enregistré
        self.assertEqual(self.valeur("X", self.g), D(105 + 22 + 33))
        self.assertEqual(self.valeur("A", self.g), D(5 + 2 + 3))

    def test_na_importe(self):
        self.importer("A", self.e2, na=True)
        self.assertEqual(self.valeur("A", self.p1), D(1))  # N/A exclu de la somme
        self.assertEqual(self.valeur("X", self.e1), D(11))  # sœur inchangée (un recalcul complet donnerait 101)
        self.assertEqual(self.valeur("X", self.e3), D(33))

    def test_case_jamais_calculee_ailleurs_calculee(self):
        """Les cases encore absentes ailleurs (branche jamais calculée dans la période clôturée) sont calculées : le
        total du groupe reste la somme de chiffres affichés."""
        Reponse.objects.filter(periode=self.c26.periode, kpi_id="X", organisation__in=[self.e3, self.p2]).delete()
        self.importer("A", self.e1, 5)
        self.assertEqual(self.valeur("X", self.e3), D(103))  # calculée avec le 2025 d'aujourd'hui
        self.assertEqual(self.valeur("X", self.p2), D(103))
        self.assertEqual(self.valeur("X", self.e2), D(22))  # case présente : inchangée
        self.assertEqual(self.valeur("X", self.g), D(105 + 22 + 103))

    def test_parametre_herite_descend_aux_descendants(self):
        self.kpi("FE", "FE", gran=Niveau.COUNTRY)
        self.kpi("Y", "Calculé", "[A] * [FE]")
        Campagne.objects.filter(pk=self.c26.pk).update(statut=Campagne.Statut.OUVERTE)
        for p in (self.p1, self.p2):
            self.poser(self.c26, "FE", p, 2)
        recalculer(self.c26)
        Campagne.objects.filter(pk=self.c26.pk).update(statut=Campagne.Statut.CLOTUREE)
        # chiffre de E3 changé sans recalcul (comme un réglage changé après la clôture) : un recalcul de toutes les
        # organisations le reprendrait dans Y de E3
        Reponse.objects.filter(periode=self.c26.periode, kpi_id="A", organisation=self.e3).update(valeur=D(4))
        self.importer("FE", self.p1, 10)
        self.assertEqual((self.valeur("Y", self.e1), self.valeur("Y", self.e2)), (D(10), D(20)))  # sous P1 : refaits
        self.assertEqual(self.valeur("Y", self.e3), D(6))  # sous P2 : inchangé
        self.assertEqual(self.valeur("Y", self.g), D(36))

    def test_recalcul_complet_inchange(self):
        """Sans organisations (recalcul d'une campagne par la commande ou la réouverture), tout est refait comme avant."""
        recalculer(self.c26)
        self.assertEqual((self.valeur("X", self.e1), self.valeur("X", self.e3)), (D(101), D(103)))
