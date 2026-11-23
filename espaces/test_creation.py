"""Création d'un espace depuis l'outil : page réservée aux gestionnaires, code de l'adresse, création réelle (base,
marque, créateur administrateur, assistant à l'étape 2), espace déclaré à la volée ; sélecteur « Espace »."""

from django.db import connections
from django.test import Client

from parametres.models import Instance
from referentiel.models import Utilisateur

from . import contexte as E
from .creation import ErreurEspace, code_propose, verifier_code
from .essais import EspacesTestCase
from .models import Compte, Espace, MarqueEspace
from .aides_tests import creer
from .aides_tests import oublier_alias
from .aides_tests import DossierTemporaire
from collecte.outils_tests import html_de


class CodeTests(EspacesTestCase):
    def test_code_propose(self):
        self.assertEqual(code_propose("Achats & Logistique"), "achatslogistique")
        self.assertEqual(code_propose("Ressources humaines 2026"), "ressourceshumaines20")
        self.assertEqual(code_propose("2026 Énergie"), "energie")
        self.assertEqual(code_propose("É"), "")

    def test_codes_refuses(self):
        for code in ("../x", "Achats", "a", "a" * 21, "principal", "commun", "essai", "ach-ats", ""):
            with self.assertRaises(ErreurEspace, msg=code):
                verifier_code(code)
        verifier_code("achats")


class PageTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gestionnaire = creer("gestion@exemple.example", "admin")  # premier compte : gestionnaire
        cls.admin = creer("admin@exemple.example", "admin")
        creer("admin@exemple.example", "contributeur", "essai")

    def test_reservee_aux_gestionnaires(self):
        self.client.force_login(Utilisateur.objects.get(pk=self.admin.pk))
        self.assertEqual(self.client.get("/administration/espaces/").status_code, 403)
        self.assertEqual(self.client.post("/administration/espaces/nouveau/", {"nom": "Pirate"}).status_code, 403)
        self.assertNotContains(self.client.get("/administration/parametres/"), "/administration/espaces/")
        self.client.force_login(Utilisateur.objects.get(pk=self.gestionnaire.pk))
        r = self.client.get("/administration/espaces/")
        self.assertContains(r, "/espace/essai/")
        self.assertContains(self.client.get("/administration/parametres/"), 'href="/administration/espaces/"')

    def test_renommer_et_archiver(self):
        self.client.force_login(Utilisateur.objects.get(pk=self.gestionnaire.pk))
        self.client.post("/administration/espaces/", {"code": "essai", "action": "renommer", "nom": "Achats groupe"})
        self.assertEqual(Espace.objects.get(code="essai").nom, "Achats groupe")
        self.client.post("/administration/espaces/", {"code": "essai", "action": "archiver"})
        self.assertEqual(Espace.objects.get(code="essai").etat, "archive")
        self.client.post("/administration/espaces/", {"code": "principal", "action": "archiver"})
        self.assertEqual(Espace.objects.get(code="principal").etat, "actif")  # le principal ne s'archive pas
        self.client.post("/administration/espaces/", {"code": "essai", "action": "reactiver"})
        self.assertEqual(Espace.objects.get(code="essai").etat, "actif")

    def test_nom_trop_long_refuse(self):
        # le navigateur limite à 80 caractères ; le serveur aussi (sinon nom tronqué ou base refusée sous PostgreSQL)
        self.client.force_login(Utilisateur.objects.get(pk=self.gestionnaire.pk))
        r = self.client.post("/administration/espaces/nouveau/", {"nom": "X" * 300, "code": "xx"})
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, "80 caractères", status_code=400)
        self.assertFalse(Espace.objects.filter(code="xx").exists())
        with self.assertRaises(ErreurEspace):
            from .creation import creer as creer_espace

            creer_espace("X" * 81, "xx", self.gestionnaire)

    def test_personnes_et_acces(self):
        self.client.force_login(Utilisateur.objects.get(pk=self.gestionnaire.pk))
        r = self.client.get("/administration/espaces/")
        self.assertContains(r, "admin@exemple.example")
        self.assertContains(r, "Contributeur")  # rôle dans « essai »
        self.client.post("/administration/espaces/", {"action": "gestionnaire", "compte": self.admin.pk, "valeur": "1"})
        self.assertTrue(Compte.objects.get(pk=self.admin.pk).gestionnaire)
        self.client.post("/administration/espaces/", {"action": "gestionnaire", "compte": self.gestionnaire.pk, "valeur": "0"})
        self.assertTrue(Compte.objects.get(pk=self.gestionnaire.pk).gestionnaire)  # pas soi-même
        autre = Client()
        autre.force_login(Utilisateur.objects.get(pk=self.admin.pk))
        self.assertEqual(autre.get("/mon-compte/").status_code, 200)
        self.client.post("/administration/espaces/", {"action": "bloquer", "compte": self.admin.pk, "valeur": "1"})
        self.assertFalse(Compte.objects.get(pk=self.admin.pk).actif)
        self.assertEqual(autre.get("/mon-compte/").status_code, 302)  # déconnecté partout
        self.assertEqual(autre.get("/espace/essai/mon-compte/").status_code, 302)
        self.client.post("/administration/espaces/", {"action": "bloquer", "compte": self.gestionnaire.pk, "valeur": "1"})
        self.assertTrue(Compte.objects.get(pk=self.gestionnaire.pk).actif)

    def test_selecteur_a_partir_de_deux_espaces(self):
        self.client.force_login(Utilisateur.objects.get(pk=self.admin.pk))
        r = self.client.get("/mon-compte/")
        self.assertContains(r, 'id="bouton-espace"')
        self.assertContains(r, 'aria-controls="liste-espaces"')
        self.assertContains(r, 'href="/espace/essai/"')
        self.assertContains(r, "<title>RSE · ")
        html = self.client.get("/espace/essai/mon-compte/").content.decode()
        self.assertIn('aria-current="true" class="courant"><span class="nom">Achats', html)
        self.assertIn("Contributeur", html)
        self.client.force_login(Utilisateur.objects.get(pk=self.gestionnaire.pk))  # un seul espace : pas de bouton
        r = self.client.get("/mon-compte/")
        self.assertNotContains(r, 'id="bouton-espace"')
        self.assertNotContains(r, "<title>RSE · ")


class CreationTests(DossierTemporaire, EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gestionnaire = creer("gestion@exemple.example", "admin")

    def test_creation_reelle(self):
        Instance.courante()
        Instance.objects.filter(pk=1).update(nom="Client", couleur_principale="#E6007E")
        self.client.force_login(Utilisateur.objects.get(pk=self.gestionnaire.pk))
        r = self.client.post("/administration/espaces/nouveau/", {"nom": "Achats France", "code": "achats", "identite": "on"})
        self.assertEqual(r.status_code, 302, r.content.decode().split("role=\"alert\">")[-1][:300])
        self.assertRedirects(r, "/espace/achats/mise-en-place/2/", fetch_redirect_response=False)
        e = Espace.objects.get(code="achats")
        self.assertEqual((e.nom, e.etat, e.cree_par), ("Achats France", "actif", self.gestionnaire.pk))
        if connections["espace_achats"].vendor == "sqlite":
            self.assertTrue((self.tmp / "spaces-data" / "achats" / "database.sqlite3").is_file())
        with E.activer("achats"):
            self.assertEqual(MarqueEspace.objects.get().code, "achats")
            i = Instance.courante()
            self.assertEqual((i.nom, i.couleur_principale, i.mise_en_place_etape), ("Client", "#E6007E", 2))
            u = Utilisateur.objects.get(pk=self.gestionnaire.pk)
            self.assertTrue(u.est_admin)
            self.assertEqual(u.password, Compte.objects.get(pk=u.pk).password)
            from parametres.models import NiveauHierarchique

            self.assertEqual(NiveauHierarchique.objects.count(), 4)  # migrations de données faites dans le nouvel espace
        self.assertEqual(Instance.courante().mise_en_place_etape, Instance.objects.get(pk=1).mise_en_place_etape)
        oublier_alias("espace_achats")  # un autre processus du serveur, qui ne connaît pas encore cet espace
        r = self.client.get("/espace/achats/mise-en-place/2/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="bouton-espace"')
        r = self.client.post("/administration/espaces/nouveau/", {"nom": "Achats bis", "code": "achats", "identite": "on"})
        self.assertContains(r, "/espace/achats/", status_code=400)  # adresse déjà prise

    def test_palette_enregistree_reprise(self):
        """L'identité reprise d'un espace dont la palette est une palette enregistrée (charte) : la palette suit, et
        l'identité du nouvel espace s'enregistre sans avoir à recliquer une palette."""
        from parametres import couleurs as CO
        from parametres.models import PaletteEnregistree

        Instance.courante()
        gamme = {**CO.gamme("#E6007E", "#1D1D1B", "#FFFFFF", "#1D1D1B"), "bandeau": "#B00060"}  # gamme fixée de la charte
        p = PaletteEnregistree.objects.create(nom="Charte", principale="#E6007E", accent="#1D1D1B", fond="#FFFFFF",
                                              texte="#1D1D1B", gamme=gamme)
        Instance.objects.filter(pk=1).update(palette=p.code, couleur_principale="#E6007E", couleur_accent="#1D1D1B",
                                             couleur_fond="#FFFFFF", couleur_texte="#1D1D1B")
        self.client.force_login(Utilisateur.objects.get(pk=self.gestionnaire.pk))
        r = self.client.post("/administration/espaces/nouveau/", {"nom": "Achats France", "code": "achats", "identite": "on"})
        self.assertEqual(r.status_code, 302)
        with E.activer("achats"):
            i = Instance.courante()
            copie = PaletteEnregistree.depuis_code(i.palette)
            self.assertIsNotNone(copie)
            self.assertEqual((copie.nom, copie.couleurs, copie.gamme),
                             ("Charte", ("#E6007E", "#1D1D1B", "#FFFFFF", "#1D1D1B"), gamme))
        oublier_alias("espace_achats")
        r = self.client.get("/espace/achats/mise-en-place/2/")
        self.assertContains(r, f'name="palette" value="{copie.code}" checked')
        # sans palette cochée (espace créé avant la correction) : enregistré quand même, en « perso »
        with E.activer("achats"):
            Instance.objects.filter(pk=1).update(palette="p999")
        donnees = {"nom": "Achats", "titre": "Reporting", "sous_titre": "", "sigle": "A", "contact": "rse@exemple.example",
                   "couleur_principale": "#E6007E", "couleur_accent": "#1D1D1B", "couleur_fond": "#FFFFFF",
                   "couleur_texte": "#1D1D1B"}
        r = self.client.post("/espace/achats/administration/parametres/", donnees)
        self.assertEqual(r.status_code, 302, r.context and r.context["form"].errors)
        with E.activer("achats"):
            self.assertEqual((Instance.courante().nom, Instance.courante().palette), ("Achats", "perso"))


class EspacesTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gestionnaire = creer("gestion@exemple.example", "admin")  # premier compte : gestionnaire

    def test_textes_courts_et_bouton_bien_nomme(self):
        self.client.force_login(Utilisateur.objects.get(pk=self.gestionnaire.pk))
        html = html_de(self.client, "/administration/espaces/")
        self.assertLess(html.index("<h1"), html.index('class="intro-page"'))  # le titre d'abord, puis l'explication (un seul style d'introduction, lot 3)
        self.assertNotIn("bouton « Espace »", html)  # le bouton porte le nom de l'espace, pas le mot « Espace »
        self.assertEqual(html.count("Administration › Comptes"), 1)  # dit une seule fois
        self.assertNotIn('class="carte aide"', html)
