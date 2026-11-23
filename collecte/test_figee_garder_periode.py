"""« Garder les chiffres de l'époque » vaut pour la période (constat 2) : tant qu'une campagne
rouverte en mode « garder » n'est pas reclôturée, aucune autre campagne de la même période (créée, ouverte, supprimée,
dates changées) ne fait recalculer l'année avec l'arbre d'aujourd'hui. Avant : une campagne en préparation créée sur la
même période rendait ``figee`` faux, et le recalcul suivant refaisait tous les totaux publiés, sans message ni journal.
Et une réouverture « recalculer » écrit au journal le changement de mode de chaque autre campagne de la période.

Données inventées uniquement."""
import datetime

from django.urls import reverse

from referentiel.composition import composer
from referentiel.models import Referentiel

from . import calcul as C
from . import periodes as P
from .administration import changer_statut
from .models import Campagne, Journal, Reponse
from .test_changer_statut_reouverture import D, Reouverture


class GarderVautPourLaPeriodeTests(Reouverture):
    def setUp(self):
        super().setUp()
        self.deplacer()  # E2 rattachée à Pays 2 après la clôture
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        self.autre_ref = Referentiel.objects.create(code="AUT", nom="Autre", ordre=2)
        composer({"EFF": ["Social"]}, self.autre_ref)

    def publies(self):
        self.assertEqual(self.total(self.p), (D(30), Reponse.Statut.CALCULE))
        self.assertEqual(self.total(self.p2), (D(5), Reponse.Statut.CALCULE))
        self.assertEqual(self.total(self.g), (D(35), Reponse.Statut.CALCULE))

    def creer_autre(self):
        n, _ = P.campagne(self.autre_ref, datetime.date(2025, 1, 1))
        return n

    def test_creation_d_une_campagne_sur_la_meme_periode(self):
        n = self.creer_autre()
        self.assertTrue(C.figee(self.c.periode))
        self.assertTrue(C.chiffres_gardes(self.c.periode))
        C.recalculer(n)
        C.recalculer_en_cours()
        self.publies()

    def test_creation_par_la_fiche_puis_ouverture_dates_et_cloture(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("collecte:admin_campagne_nouvelle"),
                         {"action": "enregistrer", "referentiel": self.autre_ref.pk, "exercice": 2025, "rang": 1,
                          "seuil_historique": "2"})
        n = Campagne.objects.get(referentiel=self.autre_ref)  # créée, puis recalculée par la fiche
        self.publies()
        changer_statut(self.admin, n, "ouvrir")
        C.recalculer_en_cours()
        self.publies()
        self.client.post(reverse("collecte:admin_campagne", args=[n.pk]),
                         {"action": "enregistrer", "date_fin_saisie": "2030-01-01", "seuil_historique": "2"})
        C.recalculer_en_cours()
        self.publies()
        self.client.post(reverse("collecte:admin_campagne", args=[n.pk]), {"action": "recalculer"})
        self.publies()
        changer_statut(self.admin, n, "revue")
        changer_statut(self.admin, n, "cloturer")
        C.recalculer_en_cours()
        self.publies()

    def test_suppression_d_une_campagne_de_la_periode(self):
        n = self.creer_autre()
        n.delete()
        C.recalculer_en_cours()
        self.publies()

    def test_reclotee_le_mode_cesse(self):
        n = self.creer_autre()
        changer_statut(self.admin, self.c, "cloturer")
        self.assertFalse(C.chiffres_gardes(self.c.periode))
        self.assertFalse(C.figee(self.c.periode))  # la campagne neuve est vivante : comme avant la réouverture « garder »
        C.recalculer(n)
        # règle « Figer ses chiffres » (règle du projet, qui remplace ici « recalculé avec l'arbre
        # d'aujourd'hui », 10) : EFF, que demande la campagne clôturée, garde ses chiffres tant que l'autre campagne de
        # la période ne l'est pas (sa saisie y est bloquée, KPI commun d'une campagne clôturée) ; le mode « garder » a bien cessé
        self.assertEqual(self.total(self.p), (D(30), Reponse.Statut.CALCULE))
        self.assertEqual(C.kpis_figes(self.c.periode), {"EFF"})

    def test_recalculer_ecrit_le_changement_de_mode_des_autres_campagnes(self):
        n, _ = P.campagne(self.autre_ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE)
        changer_statut(self.admin, n, "cloturer")
        changer_statut(self.admin, self.c, "cloturer")
        changer_statut(self.admin, n, "rouvrir", garder=True)
        changer_statut(self.admin, self.c, "rouvrir", garder=False)
        n.refresh_from_db()
        self.assertFalse(n.chiffres_gardes)
        lignes = Journal.objects.filter(action="mode_reouverture", apres="recalcules")
        self.assertEqual(sorted(lignes.values_list("objet_id", flat=True)), sorted([str(n.pk), str(self.c.pk)]))
