"""Visualisation des valeurs validées (``visualisation.CalculateurValide``) × site fermé pendant la période qui n'a que
des brouillons.

 un site fermé pendant la période dont la valeur du KPI affiché est en brouillon sortait du total
sans un mot (le total, refait sur les seules valeurs validées, ne voyait aucune valeur de ce site sur la période) : le
lecteur voyait un total présenté comme validé et complet, alors que la Saisie et les exports disent « Incomplet », et
qu'un site actif dans le même cas donne « en attente de validation ». Règle du module : s'il manque une source validée,
le total est en attente. Une valeur non validée du KPI (ou d'une source de sa formule) pour le site, ou en dessous, est
une source validée qui manque à ce total : le site compte, le total est « en attente ».

Règle « Tout brouillon compte » (règle du projet) : un brouillon d'un AUTRE KPI fait aussi compter le
site fermé (``test_brouillon_d_un_autre_kpi_fait_compter_le_site_ferme`` ; ``test_attend_validation_tout_brouillon``).
Données inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Frequence, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import periodes as P
from . import visualisation as V
from .models import Campagne, Reponse

FIN = timezone.localdate() + datetime.timedelta(days=30)
FERMETURE = datetime.date(2025, 6, 30)


class SiteFermeBrouillonTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p, actif=False,
                                              date_desactivation=FERMETURE)
        # second pays fermé, avec un site fermé : le total du groupe
        self.p2 = Organisation.objects.create(nom="Pays2", niveau_id=Niveau.COUNTRY, parent=self.g, actif=False,
                                              date_desactivation=FERMETURE)
        self.e3 = Organisation.objects.create(nom="E3", niveau_id=Niveau.ENTITY, parent=self.p2, actif=False,
                                              date_desactivation=FERMETURE)
        for code in ("X", "Y"):
            KPI.objects.create(code=code, libelle=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                               methode_agregation="Somme")
        KPI.objects.create(code="Z", libelle="Z", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme", formule="[X]*2")
        ref = Referentiel.objects.create(code="A", nom="Annuel", ordre=1, frequence=Frequence.ANNEE)
        composer({"X": ["S"], "Y": ["S"], "Z": ["S"]}, ref)
        self.c, _ = P.campagne(ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)

    def saisir(self, kpi, org, statut):
        Reponse.objects.create(periode=self.c.periode, kpi_id=kpi, organisation=org, valeur=Decimal(10), statut=statut,
                               origine=Reponse.Origine.SAISIE)

    def valide(self, code, org, codes):
        return V.CalculateurValide(codes).valeur(code, org.id, self.c.periode)

    def test_brouillon_du_kpi_affiche_rend_le_total_en_attente(self):
        self.saisir("X", self.e1, Reponse.Statut.VALIDE)
        self.saisir("X", self.e2, Reponse.Statut.BROUILLON)
        C.recalculer(self.c)
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi_id="X", organisation=self.p).valeur, Decimal(20))
        for codes in (None, ["X"]):
            with self.subTest(codes=codes):
                self.assertIsNone(self.valide("X", self.p, codes))  # avant : 10, sans un mot
                point = V.Source(self.admin, codes=codes).point("X", self.p, self.c.periode)
                self.assertEqual((point.valeur, point.en_attente), (None, True))
                self.assertIsNone(self.valide("Z", self.p, codes))  # Z = 2 × X : sa source est en brouillon

    def test_site_actif_dans_le_meme_cas(self):
        """Référence : un site actif avec un brouillon donne déjà « en attente de validation »."""
        self.e2.actif, self.e2.date_desactivation = True, None
        self.e2.save()
        self.saisir("X", self.e1, Reponse.Statut.VALIDE)
        self.saisir("X", self.e2, Reponse.Statut.BROUILLON)
        C.recalculer(self.c)
        self.assertIsNone(self.valide("X", self.p, ["X"]))

    def test_pays_ferme_dont_le_site_ferme_a_un_brouillon(self):
        """Le site fermé compte aussi pour le total au-dessus de son parent fermé (ancêtres compris)."""
        self.saisir("X", self.e1, Reponse.Statut.VALIDE)
        self.saisir("X", self.e3, Reponse.Statut.BROUILLON)
        C.recalculer(self.c)
        for codes in (None, ["X"]):
            with self.subTest(codes=codes):
                self.assertEqual(self.valide("X", self.p, codes), Decimal(10))  # E3 n'est pas sous Pays
                self.assertIsNone(self.valide("X", self.g, codes))  # avant : 10

    def test_brouillon_d_un_autre_kpi_fait_compter_le_site_ferme(self):
        """Règle « Tout brouillon compte » (règle du projet, qui remplace l'ancienne frontière : un
        brouillon de Y, qui n'est pas une source de X, ne changeait rien, 10) : E2 a une valeur pas encore validée sur la
        période, il compte dans le total de X, sans valeur validée de X ; la Saisie dit « Incomplet »."""
        self.saisir("X", self.e1, Reponse.Statut.VALIDE)
        self.saisir("Y", self.e2, Reponse.Statut.BROUILLON)
        C.recalculer(self.c)
        total = Reponse.objects.get(periode=self.c.periode, kpi_id="X", organisation=self.p)
        self.assertEqual((total.statut, total.valeur), (Reponse.Statut.INCOMPLET, None))  # l'outil : « Incomplet »
        for codes in (None, ["X"]):
            with self.subTest(codes=codes):
                self.assertIsNone(self.valide("X", self.p, codes))

    def test_valeur_validee_du_site_ferme_comptee(self):
        self.saisir("X", self.e1, Reponse.Statut.VALIDE)
        self.saisir("X", self.e2, Reponse.Statut.VALIDE)
        C.recalculer(self.c)
        self.assertEqual(self.valide("X", self.p, ["X"]), Decimal(20))

    def test_outil_inchange(self):
        """Le calcul de l'outil (toutes les valeurs) ne change pas : ``attend_validation`` y est toujours faux."""
        self.saisir("X", self.e1, Reponse.Statut.VALIDE)
        self.saisir("X", self.e2, Reponse.Statut.BROUILLON)
        calc = C.Calculateur(self.c)
        self.assertFalse(calc.attend_validation(calc.kpis["X"], self.e2, self.c.periode))
