"""« Demandé depuis » changé dans un référentiel ANNUEL (``demande_depuis.changer``) × cumul d'une période plus longue
que les mois ou les trimestres (le semestre, ou l'année, depuis les trimestres).

Un trimestre entre dans le cumul s'il est demandé par un référentiel de sa fréquence, ou par un référentiel moins fréquent
(l'annuel) qui a une campagne sur sa période et y demande le KPI (``Calculateur.demande_courte``).
Troisième passe du calcul (``qa/calculation_fuzz.py --v3 --full-check``, graine 4179) : avancer la date de
l'annuel faisait entrer le premier trimestre dans le cumul du semestre, mais le semestre (sans campagne de ce référentiel)
n'était pas recalculé : il restait à 5 au lieu de « Incomplet » jusqu'au recalcul suivant. ``_recalculer_cumuls`` ne
faisait rien pour un référentiel annuel. Données inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Frequence, Niveau, Organisation, Referentiel

from . import calcul as C
from . import periodes as P
from .demande_depuis import changer
from .models import Campagne, Reponse

FIN = timezone.localdate() + datetime.timedelta(days=30)


class ChangerDemandeDepuisAnnuelCumulsTests(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        KPI.objects.create(code="X", libelle="X", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")
        self.an = Referentiel.objects.create(code="A", nom="Annuel", ordre=1, frequence=Frequence.ANNEE)
        composer({"X": ["S"]}, self.an)
        trim = Referentiel.objects.create(code="T", nom="Trimestriel", ordre=2, frequence=Frequence.TRIMESTRE)
        composer({"X": ["S"]}, trim)
        sem = Referentiel.objects.create(code="S", nom="Semestriel", ordre=3, frequence=Frequence.SEMESTRE)
        composer({}, sem)
        from referentiel.models import ElementReferentiel

        ElementReferentiel.objects.filter(referentiel=self.an).update(demande_depuis=datetime.date(2026, 1, 1))
        ElementReferentiel.objects.filter(referentiel=trim).update(demande_depuis=datetime.date(2025, 4, 1))
        self.ca, _ = P.campagne(self.an, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        ct, _ = P.campagne(trim, datetime.date(2025, 4, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        cs, _ = P.campagne(sem, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        self.s1 = cs.periode
        Reponse.objects.create(periode=ct.periode, kpi_id="X", organisation=self.e1, valeur=Decimal(5),
                               statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
        for c in (ct, cs, self.ca):
            C.recalculer(c)

    def semestre(self):
        r = Reponse.objects.get(periode=self.s1, kpi_id="X", organisation=self.e1)
        return r.statut, r.valeur

    def test_avancer_la_date_de_l_annuel_refait_le_semestre(self):
        self.assertEqual(self.semestre(), (Reponse.Statut.CALCULE, Decimal(5)))  # T1 demandé par personne : sauté
        changer(None, self.an, ["X"], datetime.date(2025, 1, 1), confirmer=True)
        self.assertEqual(self.semestre()[0], Reponse.Statut.INCOMPLET)  # avant : (calculé, 5) jusqu'au recalcul suivant
        C.recalculer(self.s1)  # le recalcul complet donne la même chose
        self.assertEqual(self.semestre()[0], Reponse.Statut.INCOMPLET)
