"""Exercice décalé (avril à mars) × corrections de la : cumul depuis les mois d'un site fermé ou
ouvert en cours d'exercice (``Calculateur.case_courte``), « demandé depuis » en cours d'exercice
(``Calculateur.demande_courte``), formule [X@N-1] d'une organisation pas ouverte l'exercice d'avant
(``Calculateur.lisible``) et recalcul ciblé dans l'arbre de chaque période (``calcul.cibles_par_arbre``). Les mois
s'y lisent dans l'exercice qui commence en avril. Données inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, ElementReferentiel, Frequence, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import periodes as P
from . import saisie as S
from .administration import changer_statut
from .models import Campagne, Reponse

D = Decimal
FIN = timezone.localdate() + datetime.timedelta(days=30)


def rep(periode, kpi, org, v):
    Reponse.objects.update_or_create(periode=periode, kpi_id=kpi, organisation=org,
                                     defaults=dict(valeur=D(v), statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE))


def lue(periode, kpi, org):
    r = Reponse.objects.filter(periode=periode, kpi_id=kpi, organisation=org).first()
    return None if r is None else (r.valeur, r.statut)


def mois_de_l_exercice(exercice):
    return [P.ajouter_mois(datetime.date(exercice, 4, 1), i) for i in range(12)]


class ExerciceDecaleTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.p2 = Organisation.objects.create(nom="Pays 2", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        for code in ("X", "EFF"):
            KPI.objects.create(code=code, libelle=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                               methode_agregation="Somme")

    def mensuel(self, e4, mois_e4, depuis=None):
        mens = Referentiel.objects.create(code="M", nom="Mensuel", ordre=1, frequence=Frequence.MOIS, mois_debut=4)
        composer({"X": ["S"]}, mens)
        if depuis:
            ElementReferentiel.objects.filter(referentiel=mens, kpi_id="X").update(demande_depuis=depuis)
        ann = Referentiel.objects.create(code="A", nom="Annuel", ordre=2, frequence=Frequence.ANNEE, mois_debut=4)
        composer({"EFF": ["S"]}, ann)
        ca, _ = P.campagne(ann, datetime.date(2025, 4, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        for d in mois_de_l_exercice(2025):
            cm, _ = P.campagne(mens, d, statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
            for o in (self.e1, self.e2):
                if depuis is None or d >= depuis:
                    rep(cm.periode, "X", o, 1)
            if e4 is not None and d in mois_e4:
                rep(cm.periode, "X", e4, 1)
            C.recalculer(cm)
        C.recalculer(ca)
        self.assertEqual((ca.periode.debut, ca.periode.fin), (datetime.date(2025, 4, 1), datetime.date(2026, 3, 31)))
        return ca.periode

    def test_site_ferme_le_30_septembre(self):
        e4 = Organisation.objects.create(nom="E4", niveau_id=Niveau.ENTITY, parent=self.p, actif=False,
                                         date_desactivation=datetime.date(2025, 9, 30))
        an = self.mensuel(e4, mois_de_l_exercice(2025)[:6])
        self.assertEqual(lue(an, "X", e4), (D(6), Reponse.Statut.CALCULE))  # avril à septembre
        self.assertEqual(lue(an, "X", self.p), (D(30), Reponse.Statut.CALCULE))

    def test_site_ouvert_le_15_juin(self):
        e4 = Organisation.objects.create(nom="E4", niveau_id=Niveau.ENTITY, parent=self.p, date_ouverture=datetime.date(2025, 6, 15))
        an = self.mensuel(e4, mois_de_l_exercice(2025)[2:])
        self.assertEqual(lue(an, "X", e4), (D(10), Reponse.Statut.CALCULE))  # juin à mars
        self.assertEqual(lue(an, "X", self.g), (D(34), Reponse.Statut.CALCULE))

    def test_demande_depuis_octobre(self):
        an = self.mensuel(None, (), depuis=datetime.date(2025, 10, 1))
        self.assertEqual(lue(an, "X", self.e1), (D(6), Reponse.Statut.CALCULE))  # octobre à mars
        self.assertEqual(lue(an, "X", self.p), (D(12), Reponse.Statut.CALCULE))

    def test_n_1_et_recalcul_cible_dans_l_arbre_de_l_epoque(self):
        """[EFF@N-1] d'un exercice décalé : organisation pas ouverte l'exercice d'avant, et correction de l'exercice
        d'avant rouvert « garder » après un déplacement."""
        KPI.objects.create(code="EVOL", libelle="Evol", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY,
                           methode_agregation="Formule", formule="[EFF]-[EFF@N-1]")
        ann = Referentiel.objects.create(code="A", nom="Annuel", ordre=2, frequence=Frequence.ANNEE, mois_debut=4)
        composer({"EFF": ["S"], "EVOL": ["S"]}, ann)
        e3 = Organisation.objects.create(nom="E3", niveau_id=Niveau.ENTITY, parent=self.p2)
        c24, _ = P.campagne(ann, datetime.date(2024, 4, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        c25, _ = P.campagne(ann, datetime.date(2025, 4, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        for o, a, b in ((self.e1, 1, 10), (self.e2, 2, 20), (e3, 3, 30)):
            rep(c24.periode, "EFF", o, a)
            rep(c25.periode, "EFF", o, b)
        C.recalculer(c24)
        C.recalculer(c25)
        changer_statut(self.admin, c24, "cloturer")
        Organisation.objects.filter(pk=self.e2.pk).update(parent=self.p2)
        C.recalculer_en_cours()
        changer_statut(self.admin, Campagne.objects.get(pk=c24.pk), "rouvrir", garder=True)
        S.enregistrer(self.admin, Campagne.objects.get(pk=c24.pk), KPI.objects.get(code="EFF"), self.e2, "7", False, "")
        self.assertEqual(lue(c25.periode, "EVOL", self.p)[0], 10 - 8)  # Pays : E1 en 2025/26 - (E1 + E2) de l'époque
        # E3 ouverte le 01/04/2025 (date posée après coup) : 2024/25 suit l'arbre de sa clôture, où E3 était ouverte ;
        # sa valeur y est publiée (dans le total de l'époque) et se lit donc par [EFF@N-1]
        Organisation.objects.filter(pk=e3.pk).update(date_ouverture=datetime.date(2025, 4, 1))
        C.recalculer(c25)
        self.assertEqual(lue(c25.periode, "EVOL", e3), (D(27), Reponse.Statut.CALCULE))
        # 2024/25 recalculé avec l'organisation d'aujourd'hui (plus figé) : E3 n'y est plus ouverte, son N-1 ne se lit pas
        changer_statut(self.admin, Campagne.objects.get(pk=c24.pk), "cloturer")
        changer_statut(self.admin, Campagne.objects.get(pk=c24.pk), "rouvrir", garder=False)
        C.recalculer(c25)
        self.assertEqual(lue(c25.periode, "EVOL", e3)[1], Reponse.Statut.INCOMPLET)
