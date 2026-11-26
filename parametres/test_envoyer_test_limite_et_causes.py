"""Bouton « Envoyer un e-mail de test » avec les réglages de l'outil (le serveur et le port sont saisis dans l'outil) :
pas de porte pour sonder le réseau interne.

- Limite pour toute l'installation (``ESSAIS_MAX`` essais par ``ESSAIS_FENETRE``), relue sous verrou ; rien de tel avec
  les réglages de l'IT (comportement d'avant).
- Délai court (``DELAI_ESSAI``).
- Message d'échec en clair (identifiant refusé, connexion refusée, délai dépassé, pas un serveur d'e-mails…) avec le
  seul nom de l'erreur et son code SMTP : jamais la réponse du serveur. Chaque échec est noté dans l'historique.
- Un vrai envoi SMTP avec les réglages de l'outil arrive (faux serveur de qa/fake_smtp.py)."""
import importlib.util
import json
import ssl
import smtplib
import socket
import tempfile
import threading
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from collecte.models import Journal
from espaces.models import ServeurEnvoi
from parametres import envoi_emails as EE
from parametres.aides_tests.emails import AVEC_ENV, SANS_ENV, SMTP_REEL, FauxServeur, port_ferme, regler
from referentiel.models import Utilisateur

URL = reverse("parametres:hebergement")
TEST = {"action": "tester_email", "destinataire": "it@exemple.test"}


class Base(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def essayer(self):
        return self.client.post(URL, TEST, follow=True).content.decode()


@SANS_ENV
class LimiteTests(Base):
    def test_cinq_essais_puis_refus(self):
        regler()
        for _ in range(EE.ESSAIS_MAX):
            self.assertIn("E-mail de test envoyé à it@exemple.test", self.essayer())
        page = self.essayer()
        self.assertIn("Trop d&#x27;e-mails de test en peu de temps.</strong> Réessayez dans 15 minutes.", page)
        self.assertEqual(len(mail.outbox), EE.ESSAIS_MAX)
        self.assertEqual(len(ServeurEnvoi.objects.get().essais), EE.ESSAIS_MAX)
        # la fenêtre passée, l'essai repart
        plus_tard = __import__("django.utils.timezone", fromlist=["now"]).now() + EE.ESSAIS_FENETRE
        with mock.patch("parametres.envoi_emails.timezone.now", return_value=plus_tard):
            self.assertIsNone(EE.reserver_essai())

    def test_pas_de_limite_avec_les_reglages_de_l_it(self):
        with AVEC_ENV:
            for _ in range(EE.ESSAIS_MAX + 2):
                self.assertIn("E-mail de test envoyé", self.essayer())
        self.assertEqual(len(mail.outbox), EE.ESSAIS_MAX + 2)

    def test_dates_abimees_ignorees(self):
        regler()
        ServeurEnvoi.objects.filter(pk=1).update(essais=["pas une date", None, "2020-01-01T00:00:00+00:00"])
        self.assertIsNone(EE.reserver_essai())
        self.assertEqual(len(ServeurEnvoi.objects.get().essais), 1)


@SANS_ENV
@SMTP_REEL
class CausesTests(Base):
    def regler_local(self, port, securite="none", **kw):
        regler(hote="127.0.0.1", port=port, securite=securite, **kw)

    def serveur(self, genre):
        s = FauxServeur(genre)
        self.addCleanup(s.arreter)
        return s

    def test_identifiant_refuse_sans_la_banniere(self):
        s = self.serveur("refus_identifiant")
        self.regler_local(s.port)
        page = self.essayer()
        self.assertIn("Le serveur d&#x27;e-mails a refusé l&#x27;identifiant ou le mot de passe.", page)
        self.assertIn("Détail technique : SMTPAuthenticationError 535.", page)
        self.assertNotIn("banniere-secrete", page)
        j = Journal.objects.get(action="test_email_echec")
        self.assertEqual(j.apres, f"127.0.0.1:{s.port} · SMTPAuthenticationError 535")

    def test_autre_service_jamais_recopie(self):
        s = self.serveur("http")
        self.regler_local(s.port)
        page = self.essayer()
        self.assertIn("Le serveur d&#x27;e-mails a coupé la connexion.", page)
        for brut in ("reponse-interne-42", "X-Interne", "HTTP/1.0"):
            self.assertNotIn(brut, page)

    def test_connexion_refusee(self):
        self.regler_local(port_ferme())
        page = self.essayer()
        self.assertIn("Le serveur d&#x27;e-mails a refusé la connexion. Vérifiez le nom du serveur et le port.", page)
        self.assertNotIn("Errno", page)

    def test_delai_court(self):
        s = self.serveur("muet")
        self.regler_local(s.port)
        with mock.patch.object(EE, "DELAI_ESSAI", 1):
            page = self.essayer()
        self.assertIn("Le serveur d&#x27;e-mails n&#x27;a pas répondu en 1 secondes.", page)
        self.assertEqual(EE.delai_essai(), 10)

    def test_cles_des_causes(self):
        cas = [(EE.MotDePasseIllisible("x"), "mot_de_passe_illisible"),
               (smtplib.SMTPAuthenticationError(535, b"x"), "identifiants"),
               (smtplib.SMTPNotSupportedError("STARTTLS extension not supported by server."), "securite"),
               (ssl.SSLCertVerificationError("certificate verify failed"), "certificat"),
               (ssl.SSLError("wrong version number"), "securite"),
               (smtplib.SMTPSenderRefused(553, b"x", "a@b"), "expediteur"),
               (smtplib.SMTPRecipientsRefused({"a@b": (550, b"x")}), "destinataire"),
               (socket.gaierror(-2, "Name or service not known"), "introuvable"),
               (socket.timeout("timed out"), "delai"), (ConnectionRefusedError(111, "refused"), "refusee"),
               (smtplib.SMTPServerDisconnected("x"), "coupee"), (smtplib.SMTPConnectError(-1, b"x"), "coupee"),
               (smtplib.SMTPDataError(554, b"x"), "refuse"), (OSError("x"), "injoignable"), (ValueError("x"), "refuse")]
        for e, cle in cas:
            with self.subTest(e=e):
                self.assertEqual(EE.cle_cause(e), cle)
        try:  # délai dépassé en attendant la réponse : smtplib le rend en « connexion coupée »
            try:
                raise TimeoutError("timed out")
            except OSError:
                raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed: timed out")
        except smtplib.SMTPServerDisconnected as e:
            self.assertEqual(EE.cle_cause(e), "delai")
        self.assertEqual(EE.resume_technique(smtplib.SMTPRecipientsRefused({"a@b": (550, b"refus interne")})),
                         "SMTPRecipientsRefused 550")
        self.assertEqual(EE.resume_technique(smtplib.SMTPConnectError(-1, b"HTTP/1.0 200")), "SMTPConnectError")

    def test_vrai_envoi_avec_les_reglages_de_l_outil(self):
        spec = importlib.util.spec_from_file_location("faux_smtp", Path(settings.BASE_DIR) / "qa" / "fake_smtp.py")
        faux = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(faux)
        fichier = Path(tempfile.mkdtemp()) / "emails.json"
        serveur = faux.FauxSMTP(("127.0.0.1", 0), str(fichier), silencieux=True)
        threading.Thread(target=serveur.serve_forever, daemon=True).start()
        self.addCleanup(serveur.server_close)
        self.addCleanup(serveur.shutdown)
        self.regler_local(serveur.server_address[1], expediteur="envoi@outil.example")
        self.assertIn("E-mail de test envoyé à it@exemple.test", self.essayer())
        recus = json.loads(fichier.read_text(encoding="utf-8"))
        self.assertEqual([(r["expediteur"], r["destinataires"]) for r in recus], [("envoi@outil.example", ["it@exemple.test"])])


@override_settings(EMAIL_HOST="127.0.0.1", EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_USE_TLS=False,
                   EMAIL_USE_SSL=False, EMAIL_HOST_USER="", EMAIL_HOST_PASSWORD="", EMAIL_TIMEOUT=2)
class CausesReglagesDeLITTests(Base):
    def test_message_clair_et_renvoi_a_l_it(self):
        with override_settings(EMAIL_PORT=port_ferme()):
            page = self.essayer()
        self.assertIn("a refusé la connexion", page)
        self.assertIn("Ces réglages sont dans le fichier de réglages : transmettez ce message à l&#x27;IT.", page)
