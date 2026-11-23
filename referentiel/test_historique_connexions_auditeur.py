"""Historique des connexions ouvert à l'auditeur, en lecture seule (règle du projet). L'auditeur n'a pas
le menu Administration : il y arrive comme au reste de son audit, par « Historique » (lien « Historique des connexions »
au bout de la barre de filtres), sur une adresse à lui (/historique/connexions/), avec les mêmes filtres que la page de
l'administrateur et les lignes de son espace seulement. Il n'écrit jamais rien (collecte/lecture_seule.py) et ne règle
pas la durée de conservation (pas de lien vers Hébergement). Périmètre : comme la vue « Modifications
d'administration » de l'Historique, seulement pour un auditeur sans limite d'organisations (l'historique des connexions
porte sur tous les comptes de l'espace). Le lecteur, le contributeur et le validateur restent refusés."""
from django.test import Client, SimpleTestCase

from collecte import lecture_seule as LS
from espaces import contexte as E
from espaces.aides_tests import MDP, creer
from parametres.libelles import libelle
from parametres.models import NiveauHierarchique
from referentiel.models import HistoriqueConnexion, Organisation

from .test_historique_connexions import PIEGE, Base, se_connecter

URL = "/historique/connexions/"


class HistoriqueConnexionsAuditeurTests(Base):
    def test_droits_par_role(self):
        self.assertIn("historique_connexions", LS.PAGES_AUDITEUR)
        self.assertNotIn("historique_connexions", LS.PAGES_LECTEUR | LS.ECRITURES_PERMISES)
        for u in (self.contrib, self.lecteur, self.validateur):
            self.assertEqual(self.client_de(u).get(URL).status_code, 403, u.role)
        self.assertEqual(Client().get(URL).status_code, 302)
        self.assertEqual(self.client_de(self.auditeur).get(URL).status_code, 200)
        self.assertEqual(self.client_de(self.admin).get(URL).status_code, 200)

    def test_memes_filtres_et_son_espace_seulement(self):
        se_connecter("contrib@exemple.example")
        se_connecter("lecteur@exemple.example", "mauvais")
        se_connecter(PIEGE, "x")
        se_connecter("achats@exemple.example", MDP, "essai")  # dans « essai » : pas ici
        c = self.client_de(self.auditeur)
        rep = c.get(URL)
        self.assertEqual(len(rep.context["lignes"]), 3)
        self.assertNotContains(rep, "achats@exemple.example")
        self.assertContains(rep, 'class="carte-table table-connexions"')
        self.assertEqual({x.resultat for x in c.get(URL, {"resultat": "echec"}).context["lignes"]}, {"echec"})
        self.assertEqual([x.utilisateur_id for x in c.get(URL, {"q": "lecteur"}).context["lignes"]], [self.lecteur.pk])
        rep = c.get(URL, {"periode": "1"})
        self.assertContains(rep, f'href="{URL}"')  # « Effacer les filtres » reste sur sa page
        self.assertNotContains(rep, "/administration/")  # ni menu Administration, ni réglage de la durée
        self.assertContains(rep, 'href="/historique/"')  # retour à l'Historique

    def test_auditeur_d_un_autre_espace(self):
        se_connecter("contrib@exemple.example")
        auditeur_essai = creer("audit-essai@exemple.example", "auditeur", "essai")
        se_connecter("achats@exemple.example", MDP, "essai")
        with E.activer("essai"):
            rep = self.client_de(auditeur_essai, "essai").get(f"/espace/essai{URL}")
            self.assertEqual(rep.status_code, 200)
            self.assertEqual([x.utilisateur_id for x in rep.context["lignes"]], [self.achats.pk])

    def test_n_ecrit_rien(self):
        se_connecter("contrib@exemple.example")
        avant = list(HistoriqueConnexion.objects.values_list("pk", "resultat"))
        c = self.client_de(self.auditeur)
        self.assertEqual(c.post(URL, {"q": "x"}).status_code, 403)
        self.assertEqual(list(HistoriqueConnexion.objects.values_list("pk", "resultat")), avant)
        rep = c.post("/administration/parametres/hebergement/", {"action": "reglage_connexions", "connexions_jours": "5"})
        self.assertEqual(rep.status_code, 403)

    def test_lien_depuis_l_historique(self):
        self.assertContains(self.client_de(self.auditeur).get("/historique/"), f'href="{URL}"')
        self.assertNotContains(self.client_de(self.lecteur).get("/tableau-de-bord/"), f'href="{URL}"')

    def test_auditeur_limite_a_des_organisations(self):
        """Comme la vue « Modifications d'administration » de l'Historique : pas pour un auditeur limité à des organisations."""
        niveau = NiveauHierarchique.objects.order_by("rang").first()
        if niveau is None:
            niveau = NiveauHierarchique.objects.create(code="SITE", rang=1, nom="Site", nom_pluriel="Sites")
        org = Organisation.objects.create(nom="Site A", code="SA", niveau=niveau)
        self.auditeur.perimetre_lecture.add(org)
        c = self.client_de(self.auditeur)
        self.assertEqual(c.get(URL).status_code, 403)
        rep = c.get(URL, HTTP_X_REQUESTED_WITH="fetch")  # le motif du refus, tel que le script des pages le lit
        self.assertEqual(rep.json()["erreur"], libelle("admin.connexions.auditeur_limite"))
        self.assertNotContains(c.get("/historique/"), f'href="{URL}"')

    def test_page_de_confidentialite(self):
        rep = Client().get("/confidentialite/")
        qui = next(ligne[-1] for ligne in rep.context["lignes"] if ligne[0] == "historique_connexions")
        self.assertIn(libelle("choix.utilisateur.role.auditeur").lower(), qui.lower())


class GuideAuditeurTests(SimpleTestCase):
    def test_guide_de_l_auditeur_dans_les_sept_langues(self):
        from collecte import aide as AI

        for langue in AI.LANGUES_GUIDES:
            with self.subTest(langue=langue):
                texte = AI.chemin_guide("auditor", langue).read_text(encoding="utf-8")
                self.assertIn("{#sign-ins}", texte)
                self.assertIn(f"**{libelle('admin.connexions.lien', langue=langue)}**", texte)
