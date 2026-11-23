"""Correction d'une organisation déplacée dans un exercice rouvert « garder les chiffres de l'époque » et
``calcul._recalculer``, ``calcul.cibles_par_periode``). Dans la période corrigée, seules
l'organisation corrigée et ses ancêtres DE L'ÉPOQUE sont refaits : un parent d'aujourd'hui qui ne l'était pas à l'époque
garde son chiffre publié. Données inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase

from referentiel.composition import composer
from referentiel.models import KPI, Frequence, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import periodes as P
from . import saisie as S
from .administration import changer_statut
from .models import Campagne, Reponse

D = Decimal


def rep(periode, kpi, org, v):
    Reponse.objects.update_or_create(periode=periode, kpi_id=kpi, organisation=org,
                                     defaults=dict(valeur=D(v), statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE))


def etat(periode):
    return {(r.kpi_id, r.organisation_id): (r.valeur, r.statut, r.message_calcul) for r in Reponse.objects.filter(periode=periode)}


class CiblesParPeriodeGarderTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        self.g = Organisation.objects.create(nom="G", niveau_id=Niveau.GROUP)
        self.p1 = Organisation.objects.create(nom="P1", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.p2 = Organisation.objects.create(nom="P2", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p1)
        self.e3 = Organisation.objects.create(nom="E3", niveau_id=Niveau.ENTITY, parent=self.p2)
        KPI.objects.create(code="X", libelle="X", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        KPI.objects.create(code="EV", libelle="EV", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY,
                           methode_agregation="Formule", formule="[X]-[X@N-1]")
        self.ref = Referentiel.objects.create(code="A", nom="A", ordre=1, frequence=Frequence.ANNEE)
        composer({"X": ["S"], "EV": ["S"]}, self.ref)

    def construire(self, avec_2026=False):
        c25, _ = P.campagne(self.ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE)
        rep(c25.periode, "X", self.e1, 10)
        rep(c25.periode, "X", self.e3, 5)
        C.recalculer(c25)
        c26 = None
        if avec_2026:
            c26, _ = P.campagne(self.ref, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE)
            rep(c26.periode, "X", self.e1, 20)
            rep(c26.periode, "X", self.e3, 6)
            C.recalculer(c26)
        changer_statut(self.admin, c25, "cloturer")
        # chiffre publié de P2 qu'un recalcul ne redonnerait pas (ancienne règle, fichier historique) : figé à la main
        Reponse.objects.filter(periode=c25.periode, kpi_id="X", organisation=self.p2).update(
            valeur=None, statut=Reponse.Statut.INCOMPLET, message_calcul="Incomplet : (publié)")
        Organisation.objects.filter(pk=self.e1.pk).update(parent=self.p2)  # déplacée après la clôture
        C.recalculer_en_cours()
        changer_statut(self.admin, Campagne.objects.get(pk=c25.pk), "rouvrir", garder=True)
        return Campagne.objects.get(pk=c25.pk), c26 and Campagne.objects.get(pk=c26.pk)

    def test_parent_d_aujourd_hui_pas_reecrit(self):
        """Constat du relecteur : « Incomplet » devenait 5 pour P2, parent d'aujourd'hui de E1, pas celui de 2025."""
        c25, _ = self.construire()
        avant = etat(c25.periode)
        S.enregistrer(self.admin, c25, KPI.objects.get(code="X"), self.e1, "11", False, "correction")
        apres = etat(c25.periode)
        self.assertEqual(apres[("X", self.p2.id)][1], Reponse.Statut.INCOMPLET, "le chiffre publié de P2 a bougé")
        self.assertEqual(apres[("X", self.p1.id)][0], D(11))  # parent de l'époque : refait
        changees = {k for k in apres if apres[k] != avant.get(k)}
        lignee = {self.e1.id, self.p1.id, self.g.id}
        self.assertTrue({o for _, o in changees} <= lignee, changees)

    def test_recalcul_cible_direct(self):
        """Même constat par l'appel du recalcul ciblé (scénario du relecteur)."""
        c25, _ = self.construire()
        rep(c25.periode, "X", self.e1, 11)
        C.recalculer(c25, kpi_ids=["X"], organisations=[self.e1.id])
        r = Reponse.objects.get(periode=c25.periode, kpi_id="X", organisation=self.p2)
        self.assertEqual(r.statut, Reponse.Statut.INCOMPLET)

    def test_annee_suivante_suit_son_arbre(self):
        """2026 (ouverte, arbre d'aujourd'hui) lit 2025 par [X@N-1] : E1 et ses ancêtres D'AUJOURD'HUI y sont refaits,
        et aussi P1, dont la formule refaite au-dessus lit P1 en 2025 (changé) : tout est comme un recalcul complet."""
        c25, c26 = self.construire(avec_2026=True)
        S.enregistrer(self.admin, c25, KPI.objects.get(code="X"), self.e1, "11", False, "correction")
        lue = {(r.kpi_id, r.organisation_id): r.valeur for r in Reponse.objects.filter(periode=c26.periode)}
        self.assertEqual(lue[("EV", self.e1.id)], 20 - 11)
        calc = C.Calculateur(c26)
        for o in (self.e1, self.e3, self.p1, self.p2, self.g):
            self.assertEqual(lue.get(("EV", o.id)), calc.valeur("EV", o.id), o.nom)

    def test_exercice_clos_pas_reecrit_par_une_autre_annee(self):
        """Un exercice CLOS n'est jamais réécrit par une saisie d'une autre période qui le lit ou qu'il lit."""
        c25, c26 = self.construire(avec_2026=True)
        changer_statut(self.admin, c25, "cloturer")
        avant = etat(c25.periode)
        S.enregistrer(self.admin, c26, KPI.objects.get(code="X"), self.e1, "25", False, "")
        C.recalculer(c26, ["X"], organisations=[self.e1.id, self.e3.id])
        self.assertEqual(etat(c25.periode), avant)
