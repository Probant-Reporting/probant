"""Cumul d'une période longue depuis les mois × « demandé depuis » de plusieurs référentiels
(``calcul.Calculateur.demande_courte``, second tour). Un mois n'est sauté que si AUCUN
référentiel actif ne demande le KPI dans sa propre période qui contient ce mois (pour un référentiel annuel : l'année
entière) ; la date d'un référentiel mensuel ne raccourcit l'année que si rien d'autre ne demande l'année entière.
Données inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, ElementReferentiel, Frequence, Niveau, Organisation, Referentiel

from . import calcul as C
from . import periodes as P
from .models import Campagne, Reponse

D = Decimal
FIN = timezone.localdate() + datetime.timedelta(days=30)


def rep(periode, kpi, org, v):
    Reponse.objects.update_or_create(periode=periode, kpi_id=kpi, organisation=org,
                                     defaults=dict(valeur=D(v), statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE))


def lue(periode, kpi, org):
    r = Reponse.objects.filter(periode=periode, kpi_id=kpi, organisation=org).first()
    return None if r is None else (r.valeur, r.statut, r.message_calcul)


class DemandeCourtePeriodeLongueTests(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        KPI.objects.create(code="X", libelle="X", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        KPI.objects.create(code="Y", libelle="Y", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        self.ordre = 0

    def ref(self, code, frequence, contenu, depuis=None):
        self.ordre += 1
        r = Referentiel.objects.create(code=code, nom=code, ordre=self.ordre, frequence=frequence)
        composer(contenu, r)
        for kpi, d in (depuis or {}).items():
            ElementReferentiel.objects.filter(referentiel=r, kpi_id=kpi).update(demande_depuis=d)
        return r

    def mois(self, mens, premiers=7, valeur=10, annee=2025):
        """Campagnes des 12 mois ; X saisi à ``valeur`` à partir du mois ``premiers`` (Y toujours, pour que le mois existe)."""
        for m in range(1, 13):
            cm, _ = P.campagne(mens, datetime.date(annee, m, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
            for o in (self.e1, self.e2):
                rep(cm.periode, "Y", o, 1)
                if m >= premiers:
                    rep(cm.periode, "X", o, valeur)
            C.recalculer(cm)

    def annee(self, annee=2025):
        an = P.obtenir(Frequence.ANNEE, datetime.date(annee, 1, 1), 1)
        C.recalculer(an)
        return an

    def test_annuel_toute_l_annee_et_mensuel_depuis_juillet_incomplet(self):
        """Constat du relecteur : 60, « calculé », sans message (120 pour le pays) ; l'annuel demande l'année entière."""
        ann = self.ref("A", Frequence.ANNEE, {"X": ["S"]})
        mens = self.ref("M", Frequence.MOIS, {"X": ["S"], "Y": ["S"]}, {"X": datetime.date(2025, 7, 1)})
        ca, _ = P.campagne(ann, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        self.mois(mens)
        C.recalculer(ca)
        v, statut, message = lue(ca.periode, "X", self.e1)
        self.assertIsNone(v)
        self.assertEqual(statut, Reponse.Statut.INCOMPLET)
        self.assertIn("2025", message)
        self.assertEqual(lue(ca.periode, "X", self.p)[1], Reponse.Statut.INCOMPLET)

    def test_mensuel_seul_depuis_juillet_reste_complet(self):
        """Règle d'hier inchangée quand rien d'autre ne demande l'année entière."""
        mens = self.ref("M", Frequence.MOIS, {"X": ["S"], "Y": ["S"]}, {"X": datetime.date(2025, 7, 1)})
        self.mois(mens)
        an = self.annee()
        self.assertEqual(lue(an, "X", self.e1)[:2], (D(60), Reponse.Statut.CALCULE))
        self.assertEqual(lue(an, "X", self.p)[:2], (D(120), Reponse.Statut.CALCULE))

    def test_annuel_depuis_2026_ne_raccourcit_rien_en_2025(self):
        """L'annuel ne demande X qu'à partir de 2026 : en 2025, seule la date du mensuel compte."""
        self.ref("A", Frequence.ANNEE, {"X": ["S"]}, {"X": datetime.date(2026, 1, 1)})
        mens = self.ref("M", Frequence.MOIS, {"X": ["S"], "Y": ["S"]}, {"X": datetime.date(2025, 7, 1)})
        self.mois(mens)
        self.assertEqual(lue(self.annee(), "X", self.e1)[:2], (D(60), Reponse.Statut.CALCULE))

    def test_annuel_depuis_2026_et_mensuel_depuis_toujours(self):
        self.ref("A", Frequence.ANNEE, {"X": ["S"]}, {"X": datetime.date(2026, 1, 1)})
        mens = self.ref("M", Frequence.MOIS, {"X": ["S"], "Y": ["S"]})
        self.mois(mens, premiers=7)
        self.assertEqual(lue(self.annee(), "X", self.e1)[1], Reponse.Statut.INCOMPLET)
        self.mois(mens, premiers=1, valeur=1)
        self.assertEqual(lue(self.annee(), "X", self.e1)[:2], (D(12), Reponse.Statut.CALCULE))

    def test_deux_mensuels_dates_differentes(self):
        """M1 depuis juillet, M2 depuis avril : un mois est demandé si l'un des deux le demande (avril à décembre)."""
        m1 = self.ref("M1", Frequence.MOIS, {"X": ["S"], "Y": ["S"]}, {"X": datetime.date(2025, 7, 1)})
        self.ref("M2", Frequence.MOIS, {"X": ["S"]}, {"X": datetime.date(2025, 4, 1)})
        self.mois(m1, premiers=7)
        self.assertEqual(lue(self.annee(), "X", self.e1)[1], Reponse.Statut.INCOMPLET)
        self.mois(m1, premiers=4)
        self.assertEqual(lue(self.annee(), "X", self.e1)[:2], (D(90), Reponse.Statut.CALCULE))

    def trimestres(self, trim, annee=2025):
        for m in (1, 4, 7, 10):
            P.campagne(trim, datetime.date(annee, m, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)

    def test_trimestriel_toute_l_annee_et_mensuel_depuis_juillet(self):
        """Un trimestriel qui demande X depuis toujours : janvier à juin restent demandés dans le cumul de l'année."""
        self.trimestres(self.ref("T", Frequence.TRIMESTRE, {"X": ["S"]}))
        mens = self.ref("M", Frequence.MOIS, {"X": ["S"], "Y": ["S"]}, {"X": datetime.date(2025, 7, 1)})
        self.mois(mens)
        self.assertEqual(lue(self.annee(), "X", self.e1)[1], Reponse.Statut.INCOMPLET)

    def test_annuel_sans_campagne_cette_annee_ne_la_demande_pas(self):
        """Un annuel qui contient X sans campagne en 2025 ne demande pas 2025 (comme le périmètre d'une période,
        ``perimetre_calcul``) : seule la date du mensuel compte."""
        ann = self.ref("A", Frequence.ANNEE, {"X": ["S"]})
        P.campagne(ann, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        mens = self.ref("M", Frequence.MOIS, {"X": ["S"], "Y": ["S"]}, {"X": datetime.date(2025, 7, 1)})
        self.mois(mens)
        self.assertEqual(lue(self.annee(), "X", self.e1)[:2], (D(60), Reponse.Statut.CALCULE))

    def test_trimestriel_depuis_avril_et_mensuel_depuis_juillet(self):
        """Trimestriel depuis le T2 : avril à juin demandés par lui, janvier à mars par personne."""
        self.trimestres(self.ref("T", Frequence.TRIMESTRE, {"X": ["S"]}, {"X": datetime.date(2025, 4, 1)}))
        mens = self.ref("M", Frequence.MOIS, {"X": ["S"], "Y": ["S"]}, {"X": datetime.date(2025, 7, 1)})
        self.mois(mens, premiers=7)
        self.assertEqual(lue(self.annee(), "X", self.e1)[1], Reponse.Statut.INCOMPLET)
        self.mois(mens, premiers=4)
        self.assertEqual(lue(self.annee(), "X", self.e1)[:2], (D(90), Reponse.Statut.CALCULE))

    def test_source_d_une_formule_de_l_annuel(self):
        """X n'est pas un élément de l'annuel, mais la source d'un KPI calculé qu'il demande : l'année entière compte."""
        KPI.objects.create(code="K", libelle="K", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme", formule="[X]*2")
        ann = self.ref("A", Frequence.ANNEE, {"K": ["S"]})
        mens = self.ref("M", Frequence.MOIS, {"X": ["S"], "Y": ["S"]}, {"X": datetime.date(2025, 7, 1)})
        ca, _ = P.campagne(ann, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        self.mois(mens)
        C.recalculer(ca)
        self.assertEqual(lue(ca.periode, "X", self.e1)[1], Reponse.Statut.INCOMPLET)
        self.assertEqual(lue(ca.periode, "K", self.e1)[1], Reponse.Statut.INCOMPLET)

    def test_changer_la_date_de_l_annuel_recalcule_l_annee(self):
        """« Demandé depuis » de l'annuel avancé à 2025 : sa campagne 2025 est recalculée et devient incomplète."""
        from referentiel.models import Utilisateur

        from .demande_depuis import changer

        admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        ann = self.ref("A", Frequence.ANNEE, {"X": ["S"]}, {"X": datetime.date(2026, 1, 1)})
        mens = self.ref("M", Frequence.MOIS, {"X": ["S"], "Y": ["S"]}, {"X": datetime.date(2025, 7, 1)})
        P.campagne(ann, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        self.mois(mens)
        an = self.annee()
        self.assertEqual(lue(an, "X", self.e1)[:2], (D(60), Reponse.Statut.CALCULE))
        changer(admin, ann, ["X"], datetime.date(2025, 1, 1), confirmer=True)
        self.assertEqual(lue(an, "X", self.e1)[1], Reponse.Statut.INCOMPLET)
