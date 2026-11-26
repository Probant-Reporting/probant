"""Qui ÉCRIT les réglages de toute l'installation (serveur d'e-mails, alertes par e-mail, mises à jour automatiques, copie
externe des sauvegardes, essais qui joignent une adresse) : un gestionnaire des espaces actif, seulement
(``espaces.comptes.est_gestionnaire``, même règle que la page Espaces et la connexion d'entreprise). Un administrateur de
l'espace principal qui n'est pas gestionnaire LIT ces réglages (détail de l'installation compris) mais ne peut rien en
changer : sinon il choisirait le serveur d'e-mails ou la destination qui reçoit les archives de tous les espaces et du
registre commun (empreintes des mots de passe). Même règle dans une installation à un seul espace : il y a toujours un
gestionnaire actif, et ces réglages lui donneraient aussi les archives du registre commun. L'e-mail de test (réglages
enregistrés, adresse du destinataire seulement) et l'alerte d'essai (destinataires enregistrés) restent permis."""
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from espaces.aides_tests import creer
from espaces.comptes import est_gestionnaire
from espaces.essais import EspacesTestCase
from espaces.models import Compte, DestinationCopie, Espace, ReglageAlertes, ServeurEnvoi
from parametres import mise_a_jour_auto as MA
from parametres.aides_tests.copie import SANS_PROXY
from parametres.aides_tests.emails import HOTE, IDENTIFIANT, SANS_ENV, regler
from parametres.test_detail_installation_permis import connecter

HEBERGEMENT = "/administration/parametres/hebergement/"
COPIE = HEBERGEMENT + "copie-externe/"
SANTE = "/administration/parametres/sante/"
SMTP = {"action": "reglage_emails", "hote": "smtp.detourne.example", "port": "25", "securite": "starttls",
        "identifiant": "", "mot_de_passe": "", "expediteur": "envoi@detourne.example"}
S3 = {"action": "enregistrer", "genre": "s3", "adresse": "https://stockage.detourne.example", "region": "",
      "compartiment": "archives", "chemin": "", "style": "auto", "identifiant": "CLE", "secret": "Secret-detourne-9",
      "conserver": "0", "empreinte": "SHA256:x"}
COPIE_ACTIONS = ("enregistrer", "effacer_secrets", "retirer", "essayer", "confirmer_cle")
RESERVE = "Seul un gestionnaire des espaces"


class Reglages:
    """Mélange : un administrateur de l'espace principal gestionnaire (le premier) et un autre qui ne l'est pas."""

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for p in (override_settings(DOSSIER_DONNEES=self.tmp, EMAIL_HOST=""),
                  mock.patch.dict(os.environ, {"DANS_DOCKER": "1"}), SANS_PROXY):
            p.start() if hasattr(p, "start") else p.enable()
            self.addCleanup(p.stop if hasattr(p, "stop") else p.disable)

    def etat(self):
        return (list(ServeurEnvoi.objects.values()), list(DestinationCopie.objects.values()),
                list(ReglageAlertes.objects.values()), MA.dossier().exists())

    def verifier_refus(self, u, prefixe=""):
        c = connecter(u, "essai" if prefixe else "principal")
        avant = self.etat()
        for action in ("reglage_emails", "effacer_mdp_emails"):
            self.assertEqual(c.post(prefixe + HEBERGEMENT, {**SMTP, "action": action}).status_code, 403, action)
        rep = c.post(prefixe + HEBERGEMENT, {"action": "reglage_mise_a_jour_auto", "mode": "automatic", "delai": "0"})
        self.assertEqual(rep.status_code, 403, "mise à jour automatique")
        rep = c.post(prefixe + SANTE, {"action": "reglage_alertes", "actives": "on", "adresses": "moi@detourne.example"})
        self.assertEqual(rep.status_code, 403, "alertes")
        for action in COPIE_ACTIONS:
            self.assertEqual(c.post(prefixe + COPIE, {**S3, "action": action}).status_code, 403, f"copie {action}")
        self.assertEqual(self.etat(), avant)
        return c


@SANS_ENV
class GestionnaireSeulementTests(Reglages, EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gestionnaire = creer("gestion@exemple.example", "admin")  # premier administrateur : gestionnaire
        cls.admin = creer("admin2@exemple.example", "admin")  # administrateur de l'espace principal, pas gestionnaire
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")

    def test_regle_unique(self):
        self.assertTrue(est_gestionnaire(self.gestionnaire))
        self.assertFalse(est_gestionnaire(self.admin))
        Compte.objects.filter(pk=self.gestionnaire.pk).update(actif=False)
        self.assertFalse(est_gestionnaire(self.gestionnaire))  # compte bloqué au registre
        self.assertFalse(est_gestionnaire(None))

    def test_administrateur_de_l_espace_principal_non_gestionnaire_ne_regle_rien(self):
        regler()
        self.verifier_refus(self.admin)

    def test_lecture_seule_avec_le_detail_et_une_phrase_qui_dit_a_qui_s_adresser(self):
        regler()
        c = connecter(self.admin)
        page = c.get(HEBERGEMENT).content.decode()
        self.assertNotIn('name="hote"', page)
        self.assertNotIn('value="reglage_mise_a_jour_auto"', page)
        self.assertIn(f"{HOTE}:587", page)
        self.assertIn(IDENTIFIANT, page)  # il voit le détail de l'installation, comme avant
        self.assertIn("Réglé dans l'outil par un gestionnaire des espaces.", page)
        self.assertIn("Seuls les gestionnaires des espaces règlent les mises à jour automatiques.", page)
        page = c.get(COPIE + "?type=s3").content.decode()
        self.assertNotIn('name="adresse"', page)
        self.assertNotIn('value="essayer"', page)
        self.assertIn(RESERVE, page)
        page = c.get(SANTE).content.decode()
        self.assertNotIn('value="reglage_alertes"', page)
        self.assertIn('value="tester_alertes"', page)  # alerte d'essai aux destinataires enregistrés : permise
        self.assertIn("Seuls les gestionnaires des espaces règlent les alertes par e-mail.", page)

    def test_essais_avec_les_reglages_enregistres_permis(self):
        regler()
        c = connecter(self.admin)
        rep = c.post(HEBERGEMENT, {"action": "tester_email", "destinataire": "it@exemple.test"})
        self.assertEqual(rep.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(c.post(SANTE, {"action": "tester_alertes"}).status_code, 302)

    def test_gestionnaire_regle_depuis_tout_espace(self):
        Compte.objects.filter(pk=self.admin_essai.pk).update(gestionnaire=True)
        c = connecter(self.admin_essai, "essai")
        self.assertEqual(c.post("/espace/essai" + HEBERGEMENT, SMTP).status_code, 302)
        self.assertEqual(ServeurEnvoi.objects.get().hote, "smtp.detourne.example")
        self.assertEqual(c.post("/espace/essai" + COPIE, S3).status_code, 302)
        self.assertEqual(DestinationCopie.objects.get().compartiment, "archives")
        rep = c.post("/espace/essai" + SANTE, {"action": "reglage_alertes", "actives": "on", "adresses": "it@exemple.example"})
        self.assertEqual(rep.status_code, 302)
        rep = c.post("/espace/essai" + HEBERGEMENT, {"action": "reglage_mise_a_jour_auto", "mode": "automatic", "delai": "0"})
        self.assertEqual(rep.status_code, 302)
        self.assertEqual(MA.lire_choix()["mode"], "automatic")

    def test_gestionnaire_bloque_ne_regle_plus(self):
        """Compte bloqué au registre : sa session est refusée (retour à la connexion) et rien n'est écrit."""
        Compte.objects.filter(pk=self.gestionnaire.pk).update(actif=False)
        c = connecter(self.gestionnaire)
        avant = self.etat()
        rep = c.post(HEBERGEMENT, SMTP)
        self.assertEqual((rep.status_code, rep["Location"].split("?")[0]), (302, reverse("login")))
        self.assertEqual(c.post(COPIE, S3).status_code, 302)
        self.assertEqual(self.etat(), avant)

    def test_administrateur_d_un_autre_espace_toujours_refuse(self):
        self.verifier_refus(self.admin_essai, "/espace/essai")


@SANS_ENV
class UnSeulEspaceTests(Reglages, TestCase):
    """Installation à un seul espace : pas d'exception. Le premier administrateur est gestionnaire (installation neuve
    comme mise à jour) ; un autre administrateur ne règle rien de ce qui vaut pour toute l'installation."""

    databases = {"default", "commun"}

    @classmethod
    def setUpTestData(cls):
        Espace.objects.get_or_create(code="principal", defaults={"nom": "Principal", "etat": "actif"})
        super().setUpTestData()
        cls.gestionnaire = creer("gestion@exemple.example", "admin")
        cls.admin = creer("admin2@exemple.example", "admin")

    def test_il_y_a_toujours_un_gestionnaire(self):
        self.assertEqual(Espace.objects.count(), 1)
        self.assertTrue(est_gestionnaire(self.gestionnaire))

    def test_autre_administrateur_refuse(self):
        regler()
        self.verifier_refus(self.admin)

    def test_gestionnaire_regle(self):
        c = connecter(self.gestionnaire)
        self.assertEqual(c.post(HEBERGEMENT, SMTP).status_code, 302)
        self.assertEqual(ServeurEnvoi.objects.get().hote, "smtp.detourne.example")
