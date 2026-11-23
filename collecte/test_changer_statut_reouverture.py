"""Règle du projet (« pouvoir avoir le choix entre changer ou garder ») : à la réouverture d'un
exercice clos, l'administrateur choisit entre (a) garder les chiffres de l'époque (rien n'est recalculé ; ensuite seules
les organisations corrigées et leurs totaux au-dessus le sont) et (b) recalculer avec l'organisation
d'aujourd'hui (comportement d'avant). Interprétation retenue, à confirmer.

Données inventées uniquement."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import periodes as P
from . import saisie as S
from .administration import changer_statut
from .models import Campagne, Journal, Reponse

D = Decimal


class Reouverture(TestCase):
    """Groupe > Pays > E1 (10), E2 (20) ; Groupe > Pays 2 > E3 (5) ; exercice 2025 calculé puis clôturé ; ``deplacer`` :
    E2 rattachée à Pays 2 après la clôture."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.p2 = Organisation.objects.create(nom="Pays 2", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e3 = Organisation.objects.create(nom="E3", niveau_id=Niveau.ENTITY, parent=self.p2)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.eff = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      methode_agregation="Somme")
        self.ref = Referentiel.objects.create(code="RAP", nom="Rapport", ordre=1)
        composer({"EFF": ["Social"]}, self.ref)
        self.c, _ = P.campagne(self.ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE,
                               date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        for org, v in ((self.e1, 10), (self.e2, 20), (self.e3, 5)):
            Reponse.objects.create(periode=self.c.periode, kpi=self.eff, organisation=org, valeur=D(v),
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
        C.recalculer(self.c)
        changer_statut(self.admin, self.c, "cloturer")

    def deplacer(self):
        Organisation.objects.filter(pk=self.e2.pk).update(parent=self.p2)
        self.e2.refresh_from_db()

    def total(self, org):
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=org)
        return r.valeur, r.statut

    def corriger(self, org, v):
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=org)
        S.enregistrer(self.admin, self.c, self.eff, org, str(v), False, "Correction")
        return r


class GarderLesChiffresTests(Reouverture):
    def test_rien_n_est_recalcule_a_la_reouverture(self):
        self.deplacer()
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        self.c.refresh_from_db()
        self.assertEqual((self.c.statut, self.c.chiffres_gardes), (Campagne.Statut.REVUE, True))
        self.assertTrue(C.figee(self.c.periode))
        self.assertEqual(self.total(self.p), (D(30), Reponse.Statut.CALCULE))
        self.assertEqual(self.total(self.p2), (D(5), Reponse.Statut.CALCULE))
        self.assertEqual(self.total(self.g), (D(35), Reponse.Statut.CALCULE))
        j = Journal.objects.get(action="mode_reouverture")
        self.assertEqual((j.champ, j.apres), ("chiffres", "gardes"))

    def test_une_correction_ne_refait_que_l_organisation_et_ses_totaux(self):
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        self.corriger(self.e1, 12)
        self.assertEqual(self.total(self.p), (D(32), Reponse.Statut.CALCULE))  # 12 + 20 (E2 lue telle qu'enregistrée)
        self.assertEqual(self.total(self.p2), (D(5), Reponse.Statut.CALCULE))  # pas refaite : E2 n'y est pas ajoutée
        self.assertEqual(self.total(self.g), (D(37), Reponse.Statut.CALCULE))  # 32 + 5

    def test_organisation_deplacee_corrigee(self):
        """Règle du projet (remplace la limite d'avant, où E2 comptait deux fois) : l'exercice rouvert
        en gardant les chiffres se calcule avec l'arbre de sa clôture ; E2 corrigée remonte dans son parent de
        l'époque."""
        self.deplacer()
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        self.corriger(self.e2, 21)
        self.assertEqual(self.total(self.p2), (D(5), Reponse.Statut.CALCULE))  # pas refait : E2 n'y était pas
        self.assertEqual(self.total(self.p), (D(31), Reponse.Statut.CALCULE))  # 10 + 21
        self.assertEqual(self.total(self.g), (D(36), Reponse.Statut.CALCULE))  # 35 + 1 : E2 une seule fois

    def test_correction_sous_l_ancien_parent(self):
        """Même décision (remplace la limite d'avant, où E2 ne comptait plus) : une correction sous l'ancien parent
        refait ce parent avec ses enfants de l'époque, E2 comprise."""
        self.deplacer()
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        self.corriger(self.e1, 12)
        self.assertEqual(self.total(self.p), (D(32), Reponse.Statut.CALCULE))  # 12 + 20 : E2 était sous Pays
        self.assertEqual(self.total(self.p2), (D(5), Reponse.Statut.CALCULE))  # publié, pas refait
        self.assertEqual(self.total(self.g), (D(37), Reponse.Statut.CALCULE))

    def test_aucun_recalcul_d_ensemble_pendant_la_revue(self):
        self.deplacer()
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        C.recalculer_en_cours()  # ce que déclenche un changement d'organisation ou de réglage
        C.recalculer(self.c)
        self.assertEqual(self.total(self.p), (D(30), Reponse.Statut.CALCULE))
        self.assertEqual(self.total(self.p2), (D(5), Reponse.Statut.CALCULE))

    def test_la_cloture_suivante_remet_le_choix(self):
        self.deplacer()
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        changer_statut(self.admin, self.c, "cloturer")
        self.c.refresh_from_db()
        self.assertFalse(self.c.chiffres_gardes)
        changer_statut(self.admin, self.c, "rouvrir", garder=False)
        self.assertEqual(self.total(self.p), (D(10), Reponse.Statut.CALCULE))


class RecalculerTests(Reouverture):
    def test_recalculer_avec_l_organisation_d_aujourd_hui(self):
        self.deplacer()
        changer_statut(self.admin, self.c, "rouvrir", garder=False)
        self.c.refresh_from_db()
        self.assertFalse(self.c.chiffres_gardes)
        self.assertFalse(C.figee(self.c.periode))
        self.assertEqual(self.total(self.p), (D(10), Reponse.Statut.CALCULE))  # comportement d'avant
        self.assertEqual(self.total(self.p2), (D(25), Reponse.Statut.CALCULE))
        self.assertEqual(Journal.objects.get(action="mode_reouverture").apres, "recalcules")


class EcranTests(Reouverture):
    def setUp(self):
        super().setUp()
        self.deplacer()
        self.client.force_login(self.admin)
        self.url = reverse("collecte:admin_campagne", args=[self.c.pk])

    def test_le_choix_est_propose_et_garder_par_defaut(self):
        page = self.client.get(self.url).content.decode()
        self.assertIn('name="reouverture" value="garder" checked', page)
        self.assertIn('name="reouverture" value="recalculer"', page)

    def test_sans_choix_envoye_les_chiffres_sont_gardes(self):
        self.client.post(self.url, {"action": "rouvrir"})
        self.c.refresh_from_db()
        self.assertTrue(self.c.chiffres_gardes)
        self.assertEqual(self.total(self.p), (D(30), Reponse.Statut.CALCULE))

    def test_recalculer_choisi(self):
        self.client.post(self.url, {"action": "rouvrir", "reouverture": "recalculer"})
        self.c.refresh_from_db()
        self.assertFalse(self.c.chiffres_gardes)
        self.assertEqual(self.total(self.p), (D(10), Reponse.Statut.CALCULE))

    def test_bouton_recalculer_refuse_quand_les_chiffres_sont_gardes(self):
        self.client.post(self.url, {"action": "rouvrir"})
        page = self.client.get(self.url).content.decode()
        self.assertNotIn('name="action" value="recalculer"', page)
        self.assertIn("Chiffres de l'époque gardés", page)
        self.client.post(self.url, {"action": "recalculer"})
        self.assertEqual(self.total(self.p), (D(30), Reponse.Statut.CALCULE))
