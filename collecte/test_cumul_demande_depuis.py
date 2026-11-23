"""Cumul de l'année depuis les mois (``Calculateur._cumul``) × « demandé depuis » en cours d'année.

Règle de la (à confirmer), cohérente avec les organisations ouvertes : le cumul ne
porte que sur les mois où la case existe (organisation ouverte ET KPI demandé par un référentiel de cette fréquence,
``demande_depuis.filtre_demande``, sources des formules comprises) ; l'année est complète quand tous ces mois-là sont
saisis. Avant : un KPI demandé depuis juillet 2025 restait « Incomplet : janvier 2025… » sur l'année 2025, pour toujours.
Données inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, ElementReferentiel, Frequence, Niveau, Organisation, Referentiel

from . import calcul as C
from . import periodes as P
from .demande_depuis import changer
from .models import Campagne, Reponse

D = Decimal
FIN = timezone.localdate() + datetime.timedelta(days=30)


def rep(periode, kpi, org, v):
    Reponse.objects.update_or_create(periode=periode, kpi_id=kpi, organisation=org,
                                     defaults=dict(valeur=D(v), statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE))


def lue(periode, kpi, org):
    r = Reponse.objects.filter(periode=periode, kpi_id=kpi, organisation=org).first()
    return None if r is None else (r.valeur, r.statut)


class CumulDemandeDepuisTests(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        for code in ("X", "Y"):
            KPI.objects.create(code=code, libelle=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                               methode_agregation="Somme")
        self.mens = Referentiel.objects.create(code="M", nom="Mensuel", ordre=1, frequence=Frequence.MOIS)
        composer({"X": ["S"], "Y": ["S"]}, self.mens)
        ElementReferentiel.objects.filter(referentiel=self.mens, kpi_id="X").update(demande_depuis=datetime.date(2025, 7, 1))
        self.cs = []
        for m in range(1, 13):
            cm, _ = P.campagne(self.mens, datetime.date(2025, m, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
            self.cs.append(cm)
            for o in (self.e1, self.e2):
                rep(cm.periode, "Y", o, 1)
                if m >= 7:
                    rep(cm.periode, "X", o, 1)
        for cm in self.cs:
            C.recalculer(cm)
        self.an = P.obtenir(Frequence.ANNEE, datetime.date(2025, 1, 1), 1)

    def test_annee_complete_avec_les_mois_demandes(self):
        C.recalculer(self.an)
        self.assertEqual(lue(self.an, "X", self.e1), (D(6), Reponse.Statut.CALCULE))  # avant : « Incomplet : janvier… »
        self.assertEqual(lue(self.an, "X", self.p), (D(12), Reponse.Statut.CALCULE))
        self.assertEqual(lue(self.an, "Y", self.p), (D(24), Reponse.Statut.CALCULE))  # KPI demandé toute l'année : inchangé

    def test_un_mois_demande_manquant_rend_l_annee_incomplete(self):
        Reponse.objects.filter(periode=self.cs[8].periode, kpi_id="X", organisation=self.e1).delete()
        C.recalculer(self.an)
        r = Reponse.objects.get(periode=self.an, kpi_id="X", organisation=self.e1)
        self.assertEqual(r.statut, Reponse.Statut.INCOMPLET)
        self.assertIn("2025", r.message_calcul)  # « Incomplet : septembre 2025 » (seul mois manquant)
        self.assertNotIn(str(self.cs[0].periode), r.message_calcul)  # janvier n'est pas demandé

    def test_date_avancee_a_janvier_l_annee_redevient_incomplete(self):
        """La date avancée par la gestion des KPI recalcule les mois et l'année qui les contient."""
        C.recalculer(self.an)
        changer(None, self.mens, ["X"], datetime.date(2025, 1, 1))
        self.assertEqual(lue(self.an, "X", self.e1)[1], Reponse.Statut.INCOMPLET)
        self.assertEqual(lue(self.an, "X", self.p)[1], Reponse.Statut.INCOMPLET)

    def test_date_reculee_sans_campagne_touchee_l_annee_suit(self):
        """Mois de janvier à mars sans campagne (pas encore créés) : reculer la date d'avril ne touche aucune campagne,
        mais l'année qui cumule les mois est recalculée (``demande_depuis._recalculer_cumuls``)."""
        Reponse.objects.all().delete()
        Campagne.objects.filter(periode__debut__lt=datetime.date(2025, 4, 1), periode__type=Frequence.MOIS).delete()
        ElementReferentiel.objects.filter(referentiel=self.mens, kpi_id="X").update(demande_depuis=datetime.date(2025, 1, 1))
        for cm in self.cs[3:]:
            for o in (self.e1, self.e2):
                rep(cm.periode, "X", o, 1)
            C.recalculer(cm)
        self.assertEqual(lue(self.an, "X", self.e1)[1], Reponse.Statut.INCOMPLET)  # janvier à mars demandés, absents
        changer(None, self.mens, ["X"], datetime.date(2025, 4, 1))
        self.assertEqual(lue(self.an, "X", self.e1), (D(9), Reponse.Statut.CALCULE))
        self.assertEqual(lue(self.an, "X", self.p), (D(18), Reponse.Statut.CALCULE))

    def test_source_d_un_kpi_demande_reste_demandee(self):
        """Une source d'une formule d'un KPI demandé depuis janvier est demandée avec lui dès janvier : ses mois de
        janvier à juin comptent (cases offertes à la saisie par ``saisie.kpis_collectes``)."""
        KPI.objects.create(code="R", libelle="R", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme", formule="[X]*2")
        composer({"X": ["S"], "Y": ["S"], "R": ["S"]}, self.mens)
        ElementReferentiel.objects.filter(referentiel=self.mens, kpi_id="X").update(demande_depuis=datetime.date(2025, 7, 1))
        C.recalculer(self.an)
        self.assertEqual(lue(self.an, "X", self.e1)[1], Reponse.Statut.INCOMPLET)  # janvier à juin demandés par R

    def test_formule_p1_sur_un_mois_qui_ne_demande_pas_le_kpi(self):
        """Choix documenté (inchangé) : [X@P-1] qui cite un mois où X n'est pas demandé voit une source manquante, comme
        le premier mois d'un historique (aucune période précédente) : le résultat de juillet est incomplet."""
        KPI.objects.create(code="EV", libelle="EV", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme", formule="[X]-[X@P-1]")
        composer({"X": ["S"], "Y": ["S"], "EV": ["S"]}, self.mens)
        ElementReferentiel.objects.filter(referentiel=self.mens, kpi_id__in=["X", "EV"]).update(
            demande_depuis=datetime.date(2025, 7, 1))
        for cm in self.cs:
            C.recalculer(cm)
        self.assertEqual(lue(self.cs[6].periode, "EV", self.e1)[1], Reponse.Statut.INCOMPLET)  # juillet : juin manque
        self.assertEqual(lue(self.cs[7].periode, "EV", self.e1), (D(0), Reponse.Statut.CALCULE))  # août : 1 - 1
