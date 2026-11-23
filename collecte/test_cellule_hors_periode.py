"""Panneau d'une case qui ne compte pas dans la période (organisation pas encore ouverte, KPI pas demandé) : un encadré dit
la raison à la place du point « À vérifier » (le compteur ne porte pas le verrouillage) ; sans valeur enregistrée, pas de
statut « À saisir » (la case n'existe pas ici) ; avec une valeur gardée (date d'ouverture posée après coup), le statut
reste et la mention dit qu'elle ne compte dans aucun total, avec le lien vers la fiche pour un administrateur. L'organisation
n'est plus proposée dans la grille de saisie de la période. Aucun calcul ne change.

Données inventées uniquement."""
import datetime

from django.urls import reverse

from referentiel.models import Organisation

from . import saisie as S
from .aides_tests.lecture_seule import Base
from .models import Campagne


class CelluleHorsPeriodeTests(Base):
    def setUp(self):
        super().setUp()
        S.valider(self.admin, self.c, self.eff, self.e2)  # E2 : valeur 40 validée, avant la date d'ouverture
        Organisation.objects.filter(pk=self.p.pk).update(date_ouverture=datetime.date(2027, 1, 1))  # posée après coup
        self.c = Campagne.objects.get(pk=self.c.pk)  # objet relu (l'arbre est lu une fois par objet campagne)

    def panneau(self, utilisateur, kpi, org):
        self.client.force_login(utilisateur)
        url = reverse("collecte:cellule", args=[self.c.pk, kpi, org.pk])
        return self.client.get(url, HTTP_X_REQUESTED_WITH="fetch").json()["html"]

    def test_case_vide_sans_statut_a_saisir_ni_a_verifier(self):
        html = self.panneau(self.admin, "TX", self.e2)  # aucune valeur enregistrée pour TX à E2
        self.assertNotIn("statut-a_saisir", html)
        self.assertNotIn("data-points", html)  # pas de « À vérifier 1 » porteur du verrouillage
        self.assertIn("hors-periode", html)
        self.assertIn("rien à saisir", html)
        self.assertIn(reverse("collecte:admin_organisation", args=[self.p.pk]), html)

    def test_valeur_gardee_statut_et_mention(self):
        html = self.panneau(self.admin, "EFF", self.e2)
        self.assertIn("statut-valide", html)  # la valeur existe toujours, validée
        self.assertIn("ne compte dans aucun total", html)
        self.assertNotIn("rien à saisir", html)
        self.assertIn("01/01/2027", html)
        self.assertNotIn("data-points", html)
        self.assertIn(reverse("collecte:admin_organisation", args=[self.p.pk]), html)

    def test_autre_role_sans_lien(self):
        self.client.force_login(self.contrib)
        html = self.panneau(self.contrib, "EFF", self.e1)
        self.assertIn("ne compte dans aucun total", html)
        self.assertIn("administrateur", html)
        self.assertNotIn(reverse("collecte:admin_organisation", args=[self.p.pk]), html)

    def test_auditeur_voit_la_mention_sans_lien(self):
        self.client.force_login(self.auditeur)
        rep = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "EFF", self.e2.pk]), HTTP_X_REQUESTED_WITH="fetch")
        html = rep.json()["html"]
        self.assertIn("ne compte dans aucun total", html)
        self.assertNotIn("admin/organisation", html)

    def test_organisation_plus_proposee_dans_la_grille(self):
        for u in (self.admin, self.contrib):
            for personnel in (False, True):
                paires = {(k.code, o.pk) for k, o in S.cellules(u, campagne=self.c, personnel=personnel)}
                self.assertNotIn(("EFF", self.e2.pk), paires, (u.username, personnel))
                self.assertNotIn(("EFF", self.e1.pk), paires, (u.username, personnel))
        lignes = {(l.kpi.code, l.organisation.pk) for l in S.lignes(self.admin, self.c)}
        self.assertNotIn(("EFF", self.e2.pk), lignes)
        self.client.force_login(self.admin)
        page = self.client.get(reverse("collecte:saisie") + f"?campagne={self.c.pk}").content.decode()
        self.assertNotIn(reverse("collecte:cellule", args=[self.c.pk, "EFF", self.e2.pk]), page)
