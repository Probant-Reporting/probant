"""Démo sur un serveur (``demo_serveur.ligne``, page Paramètres › Santé) : base de la démo, hors mode développement et
hors version tout-en-un, comptes de démo au mot de passe public : ligne « À regarder » avec quoi faire, reprise par les
alertes par e-mail ; l'outil démarre quand même ; la ligne disparaît quand plus aucun compte de démo actif n'a le mot de
passe public. Coût : un mot de passe n'est vérifié qu'une fois par empreinte (pas à chaque affichage)."""
import io
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.hashers import check_password
from django.core import mail
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from collecte.management.commands import charger_demo as CD
from collecte.models import Journal
from espaces.essais import EspacesTestCase
from parametres import demo_serveur as DS
from parametres import sante_installation as SI
from parametres.aides_tests.alertes import DossierAlertes, disque_plein, passer
from parametres.models import Instance
from referentiel.models import Utilisateur

SERVEUR = override_settings(DEBUG=False, TOUT_EN_UN=False)


def demo(*noms):
    Journal.ecrire(None, CD.MARQUEUR, Instance.courante(), "client", "", "exemplia")
    for nom in noms:
        Utilisateur.objects.create_user(nom, email=f"{nom}@exemple.test", password=CD.MOT_DE_PASSE,
                                        role="admin" if nom == "admin" else "contributeur")


def ligne_demo(permis=True):
    return next((x for x in SI.constats(permis) if x["cle"] == "demo"), None)


@SERVEUR
class LigneDemoServeurTests(TestCase):
    databases = {"default", "commun"}

    def setUp(self):
        DS._publics.clear()

    def test_a_regarder_avec_quoi_faire(self):
        demo("admin", "contributeur")
        x = ligne_demo()
        self.assertEqual((x["etat"], x["alerte"], x["portee"]), (SI.A_REGARDER, "publics", SI.ESPACE))
        self.assertEqual(x["titre"], "Données de démonstration")
        self.assertIn("2 comptes de démo ont encore le mot de passe public", x["constat"])
        self.assertIn("supprimez-le quand vous avez fini", x["quoi"])
        self.assertIn("changez les mots de passe de ces comptes", x["quoi"])
        self.assertIn("admin, contributeur", x["quoi"])

    def test_disparait_quand_plus_aucun_compte_n_a_le_mot_de_passe_public(self):
        demo("admin", "contributeur")
        admin = Utilisateur.objects.get(username="admin")
        admin.set_password("Un-vrai-mot-de-passe-2026")
        admin.save()
        self.assertIn("1 compte de démo a encore", ligne_demo()["constat"])
        Utilisateur.objects.filter(username="contributeur").update(is_active=False)  # désactivé : ne compte plus
        self.assertIsNone(ligne_demo())

    def test_ni_en_developpement_ni_dans_la_version_tout_en_un(self):
        demo("admin")
        with override_settings(DEBUG=True):
            self.assertIsNone(ligne_demo())
        with override_settings(TOUT_EN_UN=True):
            self.assertIsNone(ligne_demo())
        self.assertIsNotNone(ligne_demo())

    def test_base_reelle_aucune_ligne(self):
        Utilisateur.objects.create_user("admin", email="admin@entreprise.example", password=CD.MOT_DE_PASSE)
        self.assertIsNone(ligne_demo())  # pas de marqueur de démo : pas la base de la démo

    def test_un_mot_de_passe_verifie_une_seule_fois_par_empreinte(self):
        demo("admin", "contributeur")
        with mock.patch.object(DS, "check_password", wraps=check_password) as verif:
            ligne_demo()
            self.assertEqual(verif.call_count, 2)
            ligne_demo()
            ligne_demo(permis=False)
            self.assertEqual(verif.call_count, 2)  # affichages suivants : aucun calcul
            admin = Utilisateur.objects.get(username="admin")
            admin.set_password("Un-vrai-mot-de-passe-2026")
            admin.save()
            self.assertIn("1 compte", ligne_demo()["constat"])
            self.assertEqual(verif.call_count, 3)  # nouvelle empreinte : vérifiée une fois

    def test_la_page_sante_la_montre(self):
        demo("admin")
        c = Client()
        c.force_login(Utilisateur.objects.get(username="admin"))
        rep = c.get("/administration/parametres/sante/")
        self.assertContains(rep, "Données de démonstration")
        self.assertContains(rep, "1 compte de démo a encore le mot de passe public")

    def test_l_outil_demarre_quand_meme(self):
        demo("admin")
        with tempfile.TemporaryDirectory() as tmp, override_settings(
                DOSSIER_DONNEES=Path(tmp), MEDIA_ROOT=Path(tmp) / "media", SAUVEGARDES_DIR=Path(tmp) / "sauvegardes"):
            sortie = io.StringIO()
            call_command("demarrage", stdout=sortie, stderr=io.StringIO())
        self.assertIn("demo database", sortie.getvalue())


@SERVEUR
class AlerteDemoServeurTests(DossierAlertes, EspacesTestCase):
    adresses = "it@exemple.example"

    def setUp(self):
        DS._publics.clear()
        super().setUp()

    def test_partie_dans_les_alertes_par_e_mail(self):
        demo("admin")
        with disque_plein():
            r = passer()
        self.assertIn("principal:demo.publics", r["nouveaux"])
        corps = [m for m in mail.outbox if "it@exemple.example" in m.to][0].body
        self.assertIn("Données de démonstration (À regarder)", corps)
        self.assertIn("changez les mots de passe de ces comptes", corps)
