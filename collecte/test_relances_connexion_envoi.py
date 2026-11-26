"""Les relances passent par le seul point de passage des envois (``parametres.envoi_emails.connexion_envoi``) : avec le
serveur réglé dans l'outil (sans SMTP_HOST), les relances manuelles, l'essai d'une relance et les relances automatiques
partent avec l'expéditeur de l'outil ; SMTP_HOST rempli, celui du fichier de réglages ; un mot de passe illisible (secret
changé) note l'échec avec un message clair, sans erreur ; un serveur réglé dans l'outil qui répond mal ne laisse dans la
relance que le nom de l'erreur, jamais la réponse brute."""
import datetime
from unittest import mock

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from parametres import envoi_emails as EE
from parametres.aides_tests.emails import AVEC_ENV, EXPEDITEUR, SANS_ENV, SMTP_REEL, FauxServeur, regler
from parametres.models import Instance
from referentiel.models import Attribution

from . import relances as R
from .aides_tests.saisie import Base
from .models import Relance


@SANS_ENV
class RelancesPointDePassageTests(Base):
    def setUp(self):
        super().setUp()
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.autre)
        self.enregistrer("12")

    def test_sans_serveur_rien_ne_part(self):
        self.assertFalse(R.envoi_actif())
        with self.assertLogs("reporting.relances", "WARNING"):
            self.assertEqual(R.envoyer(R.a_faire([self.c]), par=self.admin), [])
        self.assertEqual(mail.outbox, [])

    def test_relances_manuelles_avec_le_serveur_de_l_outil(self):
        regler()
        self.assertTrue(R.envoi_actif())
        with mock.patch.object(EE, "connexion_envoi", wraps=EE.connexion_envoi) as passage:
            sorties = R.envoyer(R.a_faire([self.c]), par=self.admin)
        passage.assert_called_once_with()
        self.assertEqual([r.statut for r in sorties], ["envoyee", "envoyee"])
        self.assertEqual({m.from_email for m in mail.outbox}, {EXPEDITEUR})

    def test_le_fichier_de_reglages_gagne_pour_les_relances(self):
        regler()
        with AVEC_ENV:
            R.envoyer(R.a_faire([self.c]), par=self.admin)
        self.assertEqual({m.from_email for m in mail.outbox}, {"it@it.example"})

    def test_essai_d_une_relance_depuis_la_page(self):
        regler()
        self.client.force_login(self.admin)
        rep = self.client.post(reverse("collecte:relances"), {"action": "essai", "personnes": [self.contrib.pk]}, follow=True)
        self.assertEqual(rep.status_code, 200)
        self.assertEqual([(m.from_email, m.to) for m in mail.outbox], [(EXPEDITEUR, [self.admin.email])])

    def test_relances_automatiques_avec_le_serveur_de_l_outil(self):
        regler()
        i = Instance.courante()
        i.relance_auto, i.relance_jours = True, "7"
        i.save()
        liste = R.relancer_automatiquement(self.c.date_fin_saisie - datetime.timedelta(days=7))
        self.assertEqual(len(liste), 2)
        self.assertEqual({m.from_email for m in mail.outbox}, {EXPEDITEUR})

    def test_mot_de_passe_illisible_echec_clair(self):
        regler()
        with override_settings(SECRET_KEY="secret-d-un-autre-serveur-0123456789-abcdefghijkl"), \
                self.assertLogs("reporting.relances", "WARNING"):
            sorties = R.envoyer(R.a_faire([self.c]), par=self.admin)
        self.assertEqual([r.statut for r in sorties], ["echec", "echec"])
        self.assertEqual(mail.outbox, [])
        self.assertEqual(R.cause_echec(sorties[0].erreur),
                         "le mot de passe enregistré du serveur d'e-mails ne peut plus être lu "
                         "(à saisir de nouveau dans Paramètres › Hébergement)")

    @SMTP_REEL
    def test_reponse_brute_jamais_gardee(self):
        s = FauxServeur("refus_identifiant")
        self.addCleanup(s.arreter)
        regler(hote="127.0.0.1", port=s.port, securite="none")
        with self.assertLogs("reporting.relances", "WARNING"):
            sorties = R.envoyer(R.a_faire([self.c], destinataires=[self.contrib.pk]), par=self.admin)
        self.assertEqual(Relance.objects.get().erreur, "SMTPAuthenticationError 535")
        self.assertEqual(R.cause_echec(sorties[0].erreur), "le serveur d'e-mails refuse l'identifiant ou le mot de passe de l'outil")
