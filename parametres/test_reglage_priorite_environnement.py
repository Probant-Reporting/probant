"""Priorité des réglages d'envoi (``envoi_emails.reglage`` et ``connexion_envoi``) : SMTP_HOST dans le fichier de
réglages gagne toujours (comportement d'avant, aucune surprise à la mise à jour) et la page le montre en lecture seule,
sans le mot de passe ; sinon les réglages de l'outil servent ; sans rien, les e-mails restent écrits dans le journal du
serveur (moteur console) et aucune relance ne part."""
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from parametres import envoi_emails as EE
from parametres.aides_tests.emails import AVEC_ENV, EXPEDITEUR, HOTE, IDENTIFIANT, MDP, SANS_ENV, regler
from referentiel.models import Utilisateur

URL = reverse("parametres:hebergement")


class ReglageTests(TestCase):
    def test_sans_rien_comportement_d_avant(self):
        with SANS_ENV, override_settings(EMAIL_BACKEND=EE.CONSOLE, DEFAULT_FROM_EMAIL="reporting@localhost"):
            r = EE.reglage()
            self.assertEqual((r.source, r.actif), (EE.AUCUNE, False))
            self.assertFalse(EE.envoi_actif())
            connexion, expediteur = EE.connexion_envoi()
            self.assertEqual(f"{type(connexion).__module__}.{type(connexion).__name__}", EE.CONSOLE)
            self.assertEqual(expediteur, "reporting@localhost")

    def test_reglages_de_l_outil(self):
        with SANS_ENV:
            regler(port=465, securite="ssl")
            r = EE.reglage()
            self.assertEqual((r.source, r.hote, r.port, r.securite, r.identifiant, r.expediteur, r.mot_de_passe),
                             (EE.OUTIL, HOTE, 465, "ssl", IDENTIFIANT, EXPEDITEUR, True))
            self.assertTrue(EE.envoi_actif())
            with override_settings(EMAIL_BACKEND=EE.CONSOLE):  # en production sans SMTP_HOST : le SMTP, pas la console
                connexion, expediteur = EE.connexion_envoi(timeout=7)
            self.assertEqual(f"{type(connexion).__module__}.{type(connexion).__name__}", EE.SMTP)
            self.assertEqual((connexion.host, connexion.port, connexion.username, connexion.password, connexion.use_ssl,
                              connexion.use_tls, connexion.timeout), (HOTE, 465, IDENTIFIANT, MDP, True, False, 7))
            self.assertIsNone(connexion.connection)  # pas encore ouverte : rien ne part avant l'envoi
            self.assertEqual(expediteur, EXPEDITEUR)

    def test_le_fichier_de_reglages_gagne(self):
        with SANS_ENV:
            regler()
        with AVEC_ENV, override_settings(EMAIL_BACKEND=EE.SMTP):
            r = EE.reglage()
            self.assertEqual((r.source, r.hote, r.port, r.expediteur), (EE.ENVIRONNEMENT, "smtp.it.example", 2525, "it@it.example"))
            connexion, expediteur = EE.connexion_envoi()
            self.assertEqual((connexion.host, connexion.port, connexion.username, connexion.password),
                             ("smtp.it.example", 2525, "compte-it@it.example", "mdp-de-l-it"))
            self.assertEqual(expediteur, "it@it.example")

    def test_serveur_vide_dans_l_outil_rien_ne_part(self):
        with SANS_ENV:
            regler()
            regler(hote="")
            self.assertEqual(EE.reglage().source, EE.AUCUNE)


class PageTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def test_reglage_de_l_it_en_lecture_seule_sans_mot_de_passe(self):
        with SANS_ENV:
            regler()
        with AVEC_ENV:
            page = self.client.get(URL).content.decode()
            self.assertIn("Réglé par l'IT dans le fichier de réglages", page)
            self.assertIn("smtp.it.example:2525 (STARTTLS)", page)
            self.assertIn("compte-it@it.example", page)  # l'identifiant : administrateur de l'espace principal
            self.assertNotIn('name="hote"', page)
            self.assertNotIn('name="mot_de_passe"', page)
            for secret in ("mdp-de-l-it", MDP, HOTE):
                self.assertNotIn(secret, page)
            # un envoi du formulaire est refusé : les réglages de l'outil ne changent pas
            rep = self.client.post(URL, {"action": "reglage_emails", "hote": "autre.example", "port": 25, "securite": "none",
                                         "expediteur": "x@autre.example"}, follow=True)
            self.assertContains(rep, "L&#x27;IT a réglé les e-mails dans le fichier de réglages")
        self.assertEqual(EE.ligne().hote, HOTE)

    def test_e_mail_de_test_avec_les_reglages_de_l_it(self):
        with AVEC_ENV:
            rep = self.client.post(URL, {"action": "tester_email", "destinataire": "it@exemple.test"}, follow=True)
        self.assertContains(rep, "E-mail de test envoyé à it@exemple.test")
        self.assertEqual(mail.outbox[0].from_email, "it@it.example")

    def test_e_mail_de_test_avec_les_reglages_de_l_outil(self):
        with SANS_ENV:
            regler()
            rep = self.client.post(URL, {"action": "tester_email", "destinataire": "it@exemple.test"}, follow=True)
        self.assertContains(rep, "E-mail de test envoyé à it@exemple.test")
        self.assertEqual((mail.outbox[0].from_email, mail.outbox[0].to), (EXPEDITEUR, ["it@exemple.test"]))
