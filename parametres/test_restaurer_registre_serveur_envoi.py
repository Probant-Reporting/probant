"""Après une restauration ou un changement du secret de l'installation : le serveur d'envoi réglé dans l'outil.

- Restaurer un espace ne touche pas au réglage (il est au registre commun, jamais dans l'archive d'un espace).
- Restaurer le registre commun (IT, ``restore --shared``) remet le réglage de l'archive ; son mot de passe se relit avec
  le même secret.
- Secret changé (``DJANGO_SECRET_KEY``, ``.secret_key`` perdu, registre venu d'un autre serveur) : le mot de passe ne se
  lit plus. Aucune erreur 500 : la page Hébergement et la page Santé disent « à saisir de nouveau », l'e-mail de test et
  les relances échouent avec ce message clair, et un nouveau mot de passe enregistré remet tout en marche."""
import shutil
import tempfile
from pathlib import Path

from django.core import mail
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from espaces.models import ServeurEnvoi
from parametres import envoi_emails as EE
from parametres import sauvegardes as SV
from parametres.aides_tests.emails import HOTE, MDP, SANS_ENV, regler
from referentiel.models import Utilisateur

AUTRE_SECRET = override_settings(SECRET_KEY="secret-d-un-autre-serveur-0123456789-abcdefghijkl")


@SANS_ENV
class SecretChangeTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)
        regler()

    def test_pages_disent_a_ressaisir_sans_erreur(self):
        with AUTRE_SECRET:
            self.client.force_login(self.admin)  # la session est signée avec le secret
            r = EE.reglage()
            self.assertEqual((r.source, r.mot_de_passe, r.mot_de_passe_illisible), (EE.OUTIL, True, True))
            page = self.client.get(reverse("parametres:hebergement"))
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, "Le mot de passe du serveur d&#x27;e-mails doit être saisi de nouveau")
            self.assertContains(page, "Saisissez de nouveau le mot de passe")
            sante = self.client.get(reverse("parametres:sante_installation"))
            ligne = next(x for x in sante.context["lignes"] if x["cle"] == "email")
            self.assertEqual(ligne["etat"], "regarder")
            self.assertIn("ne peut plus être lu", ligne["constat"])
            rep = self.client.post(reverse("parametres:hebergement"), {"action": "tester_email", "destinataire": "it@exemple.test"},
                                   follow=True)
            self.assertContains(rep, "Le mot de passe enregistré ne peut plus être lu.")
            self.assertEqual(len(mail.outbox), 0)
            # ressaisi : tout repart
            self.client.post(reverse("parametres:hebergement"), {"action": "reglage_emails", "hote": HOTE, "port": "587",
                                                                 "securite": "starttls", "identifiant": "", "expediteur": "e@outil.example",
                                                                 "mot_de_passe": "Nouveau-mdp"})
            self.assertFalse(EE.reglage().mot_de_passe_illisible)
            rep = self.client.post(reverse("parametres:hebergement"), {"action": "tester_email", "destinataire": "it@exemple.test"},
                                   follow=True)
            self.assertContains(rep, "E-mail de test envoyé à it@exemple.test")

    def test_demarrage_le_dit_a_l_it(self):
        from parametres.management.commands.demarrage import Command

        self.assertEqual(Command._emails(), f"SMTP {HOTE}:587 (set in the tool, Settings > Hosting)")
        with AUTRE_SECRET:
            self.assertIn("enter it again", Command._emails())


@SANS_ENV
class RestaurationsTests(TransactionTestCase):
    databases = {"default", "commun"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        reglages = override_settings(DOSSIER_DONNEES=self.tmp, MEDIA_ROOT=self.tmp / "files", SAUVEGARDES_DIR=self.tmp / "backups",
                                     ESPACES_DOSSIER=self.tmp / "spaces-data")
        reglages.enable()
        self.addCleanup(reglages.disable)
        Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)

    def test_restaurer_un_espace_ne_touche_pas_au_reglage(self):
        a = SV.creer("avant", format_base="json")
        regler()
        SV.restaurer(a.chemin, exiger_signature=False)
        self.assertEqual((EE.reglage().hote, EE.connexion_envoi()[1]), (HOTE, "envoi@outil.example"))

    def test_restaurer_le_registre(self):
        regler()
        chemin = SV.creer_registre("essai")
        regler(hote="autre.example", mot_de_passe="Autre-mdp")
        SV.restaurer_registre(chemin)
        s = ServeurEnvoi.objects.get()
        self.assertEqual(s.hote, HOTE)
        from parametres import chiffrement as CH

        self.assertEqual(CH.dechiffrer(s.mot_de_passe_chiffre, CH.MOT_DE_PASSE_SMTP), MDP)
        with AUTRE_SECRET:  # registre remis sur un serveur au secret différent : à ressaisir
            self.assertTrue(EE.reglage().mot_de_passe_illisible)
