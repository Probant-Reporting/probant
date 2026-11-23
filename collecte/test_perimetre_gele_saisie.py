"""Ce qui est offert à la saisie et ce qui est calculé coïncident (constat 5 ; recette du même
jour, point 8). Une seule fonction, ``calcul.perimetre_gele`` : un exercice clos (jamais rouvert : les KPI qui y ont une
case) ou rouvert (son périmètre gelé) ne reçoit aucune case pour un KPI ajouté depuis : ni grille, ni case par l'adresse
directe, ni taux de remplissage, ni calcul. Un KPI ajouté au référentiel d'une campagne rouverte avec « demandé depuis »
cet exercice (choix explicite) entre dans le périmètre de la période, avec une ligne au journal ;
sans ce choix (l'exercice en cours), un modèle installé ou un KPI ajouté pendant la clôture, non.

Données inventées uniquement."""
import datetime
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, ElementReferentiel, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import periodes as P
from . import saisie as S
from .administration import changer_statut
from .models import Campagne, Journal, Reponse

D = Decimal


class PerimetreGele(TestCase):
    """Groupe > E1, E2 ; EFF (entité, somme) ; exercices 2025 (clôturé) et 2026 (ouvert)."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.g)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")
        self.ref = Referentiel.objects.create(code="RAP", nom="Rapport", ordre=1)
        composer({"EFF": ["Social"]}, self.ref)
        fin = timezone.localdate() + datetime.timedelta(days=30)
        self.c25 = P.campagne(self.ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=fin)[0]
        self.c26 = P.campagne(self.ref, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=fin)[0]
        for org, v in ((self.e1, 10), (self.e2, 20)):
            Reponse.objects.create(periode=self.c25.periode, kpi_id="EFF", organisation=org, valeur=D(v),
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
        C.recalculer(self.c25)
        changer_statut(self.admin, self.c25, "cloturer")

    def nouveau_kpi(self):
        KPI.objects.create(code="NEW", libelle="Nouveau", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")

    def offerts(self, c):
        c = Campagne.objects.get(pk=c.pk)
        return {k.code for k, o in S.cellules(self.admin, campagne=c)}

    def attendues(self, c):
        c = Campagne.objects.get(pk=c.pk)
        return {(l.kpi.code, l.organisation.id) for l in S.lignes(self.admin, c) if l.attendue}

    def ajouter_par_la_page(self, depuis=""):
        self.client.force_login(self.admin)
        self.client.post(reverse("parametres:referentiels"), {"action": "ajouter_kpi", "ref": self.ref.code, "kpi": "NEW",
                                                              "depuis": depuis})
        self.assertTrue(ElementReferentiel.objects.filter(referentiel=self.ref, kpi_id="NEW").exists())


class KpiAjouteApresLaClotureTests(PerimetreGele):
    def setUp(self):
        super().setUp()
        self.nouveau_kpi()
        ElementReferentiel.objects.create(referentiel=self.ref, kpi_id="NEW", ordre=99)  # ajouté pendant la clôture

    def test_exercice_clos_aucune_case_pour_le_kpi_ajoute(self):
        self.assertEqual(C.perimetre_gele(self.c25.periode), {"EFF"})
        self.assertNotIn("NEW", self.offerts(self.c25))
        self.assertNotIn("NEW", {k for k, _ in self.attendues(self.c25)})  # ni taux de remplissage, ni tableau de bord
        d = S.droits(self.admin, Campagne.objects.get(pk=self.c25.pk), KPI.objects.get(pk="NEW"), self.e1)
        # adresse directe : rien à modifier, et la raison au lieu de la page 403 (point 1 de la : « pas
        # demandé dans cette période », ``test_droits_kpi_pas_demande.py``)
        self.assertTrue(d.voir and d.hors_periode)
        self.assertFalse(d.modifier or d.repasser_brouillon)
        self.assertTrue(d.motif)
        with self.assertRaises(PermissionDenied):
            S.enregistrer(self.admin, Campagne.objects.get(pk=self.c25.pk), KPI.objects.get(pk="NEW"), self.e1, "5", False, "")
        self.assertIn("NEW", self.offerts(self.c26))  # exercice vivant : demandé

    def test_exercice_rouvert_aucune_case_et_aucun_calcul(self):
        for garder in (True, False):
            with self.subTest(garder=garder):
                changer_statut(self.admin, Campagne.objects.get(pk=self.c25.pk), "rouvrir", garder=garder)
                self.assertNotIn("NEW", self.offerts(self.c25))
                self.assertNotIn("NEW", C.perimetre_calcul(Campagne.objects.get(pk=self.c25.pk).periode))
                C.recalculer(self.c25)
                # self.c25 : objet d'avant la réouverture (son périmètre gelé est relu en base)
                self.assertFalse(Reponse.objects.filter(periode=self.c25.periode, kpi_id="NEW").exists())
                changer_statut(self.admin, Campagne.objects.get(pk=self.c25.pk), "cloturer")

    def test_sans_aucune_cloture_rien_ne_change(self):
        self.assertIsNone(C.perimetre_gele(self.c26.periode))


class PerimetreNoteTests(PerimetreGele):
    def test_note_a_la_premiere_cloture_sans_rien_changer(self):
        self.assertEqual(Campagne.objects.get(pk=self.c25.pk).periode.perimetre_fige, ["EFF"])
        self.assertIsNone(Campagne.objects.get(pk=self.c26.pk).periode.perimetre_fige)

    def test_mise_a_jour_note_les_exercices_deja_clos(self):
        from .mise_a_jour import faire_les_travaux
        from referentiel.models import TravailApresMiseAJour

        c24 = P.campagne(self.ref, datetime.date(2024, 1, 1), statut=Campagne.Statut.CLOTUREE)[0]  # close avant la version
        self.assertIsNone(c24.periode.perimetre_fige)
        TravailApresMiseAJour.objects.create(code="geler_perimetres", motif="Essai.")
        self.assertIn("geler_perimetres", faire_les_travaux())
        c24.periode.refresh_from_db()
        self.assertEqual(c24.periode.perimetre_fige, ["EFF"])  # ce qu'il demande aujourd'hui : rien ne change
        self.nouveau_kpi()
        ElementReferentiel.objects.create(referentiel=self.ref, kpi_id="NEW", ordre=99)
        self.assertNotIn("NEW", self.offerts(c24))

    def test_campagne_creee_sur_une_periode_close_y_fait_entrer_son_referentiel(self):
        self.nouveau_kpi()
        autre = Referentiel.objects.create(code="AUT", nom="Autre", ordre=2)
        composer({"NEW": ["T"]}, autre)
        c = P.campagne(autre, datetime.date(2025, 1, 1), statut=Campagne.Statut.CLOTUREE)[0]  # reprise d'historique
        self.assertIn("NEW", C.perimetre_gele(c.periode))
        self.assertTrue(Journal.objects.filter(action="perimetre_periode", objet_id=str(c.pk), apres="NEW").exists())


class KpiAjouteExplicitementApresLaReouvertureTests(PerimetreGele):
    # Règle du projet : l'entrée implicite (ajout pendant la réouverture) est remplacée par le choix
    # explicite « demandé depuis » ; par défaut (l'exercice en cours), le KPI n'entre pas dans l'exercice rouvert.
    def test_ajoute_sans_choix_n_entre_pas(self):
        changer_statut(self.admin, self.c25, "rouvrir", garder=False)
        self.nouveau_kpi()
        self.ajouter_par_la_page()
        self.assertNotIn("NEW", self.offerts(self.c25))
        self.assertIn("NEW", self.offerts(self.c26))

    def test_ajoute_par_la_page_du_referentiel_entre_dans_le_perimetre(self):
        changer_statut(self.admin, self.c25, "rouvrir", garder=False)
        self.nouveau_kpi()
        self.ajouter_par_la_page(depuis="2025-01-01")  # « l'ajouter aussi à 2025 » choisi
        periode = Campagne.objects.get(pk=self.c25.pk).periode
        self.assertIn("NEW", C.perimetre_gele(periode))
        self.assertIn("NEW", self.offerts(self.c25))
        self.assertIn("NEW", C.perimetre_calcul(periode))
        j = Journal.objects.get(action="perimetre_periode")
        self.assertEqual((j.objet_id, j.apres), (str(self.c25.pk), "NEW"))
        S.enregistrer(self.admin, Campagne.objects.get(pk=self.c25.pk), KPI.objects.get(pk="NEW"), self.e1, "3", False, "")
        self.assertTrue(Reponse.objects.filter(periode=periode, kpi_id="NEW", organisation=self.g).exists())  # total au-dessus

    def test_pendant_la_cloture_l_ajout_n_entre_pas(self):
        self.nouveau_kpi()
        self.ajouter_par_la_page()  # 2025 clôturé : pas de campagne rouverte, rien n'est étendu
        self.assertFalse(Journal.objects.filter(action="perimetre_periode").exists())
        changer_statut(self.admin, self.c25, "rouvrir", garder=False)
        self.assertNotIn("NEW", self.offerts(self.c25))
