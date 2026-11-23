"""Relances automatiques réservées par jour (Instance.derniere_relance_auto, mise à jour conditionnelle) : deux
planificateurs lancés le même jour (redéploiement, deux instances) n'envoient qu'une fois ; le lendemain, on envoie ;
la simulation et les relances écrites depuis la page Relances ne sont pas bloquées."""
import datetime
import io

from django.core import mail
from django.core.management import call_command

from espaces import contexte as E
from espaces.essais import EspacesTestCase
from parametres.models import Instance
from referentiel.models import Attribution

from . import relances as R
from .models import Relance
from .aides_tests.relances import AVEC_SMTP
from .aides_tests.saisie import Base


@AVEC_SMTP
class ReservationRelancesTests(Base):
    def setUp(self):
        super().setUp()
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.autre)
        self.enregistrer("12")
        Instance.objects.filter(pk=Instance.courante().pk).update(relance_auto=True, relance_jours="7,6")
        self.jour = self.c.date_fin_saisie - datetime.timedelta(days=7)

    def test_deux_lancements_le_meme_jour_un_seul_envoi(self):
        self.assertEqual(len(R.relancer_automatiquement(self.jour)), 2)
        Relance.objects.all().delete()  # même sans trace des envois (l'autre processus n'a pas encore écrit) : réservé
        with self.assertLogs("reporting.relances", "INFO") as logs:
            self.assertEqual(R.relancer_automatiquement(self.jour), [])
        self.assertIn("already sent today", "\n".join(logs.output))
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(Instance.courante().derniere_relance_auto, self.jour)

    def test_echec_total_libere_la_journee(self):
        """SMTP en panne pour tous : la journée est rendue ; relancé le même jour après réparation, tout part."""
        from unittest import mock

        hier = self.jour - datetime.timedelta(days=5)
        Instance.objects.filter(pk=Instance.courante().pk).update(derniere_relance_auto=hier)
        with mock.patch("collecte.relances.EmailMessage.send", side_effect=OSError("SMTP en panne")), \
                self.assertLogs("reporting.relances", "WARNING"):
            self.assertEqual(len(R.relancer_automatiquement(self.jour)), 2)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Instance.courante().derniere_relance_auto, hier)  # valeur d'avant remise
        self.assertEqual(len(R.relancer_automatiquement(self.jour)), 2)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(Instance.courante().derniere_relance_auto, self.jour)
        self.assertEqual(R.relancer_automatiquement(self.jour), [])  # puis réservée : un seul envoi
        self.assertEqual(len(mail.outbox), 2)

    def test_exception_libere_la_journee(self):
        from unittest import mock

        with mock.patch.object(R, "envoyer", side_effect=RuntimeError("panne")), self.assertRaises(RuntimeError):
            R.relancer_automatiquement(self.jour)
        self.assertIsNone(Instance.courante().derniere_relance_auto)
        self.assertEqual(len(R.relancer_automatiquement(self.jour)), 2)
        self.assertEqual(len(mail.outbox), 2)

    def test_echec_partiel_garde_la_journee(self):
        """Une relance partie sur deux : la journée reste réservée (pas de second envoi à la première personne)."""
        from unittest import mock

        vrai = R.EmailMessage.send
        appels = []

        def un_sur_deux(message, *a, **k):
            appels.append(1)
            if len(appels) == 1:
                raise OSError("refusé")
            return vrai(message, *a, **k)
        with mock.patch("collecte.relances.EmailMessage.send", un_sur_deux), self.assertLogs("reporting.relances", "WARNING"):
            R.relancer_automatiquement(self.jour)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(Instance.courante().derniere_relance_auto, self.jour)
        self.assertEqual(R.relancer_automatiquement(self.jour), [])
        self.assertEqual(len(mail.outbox), 1)

    def test_liberation_conditionnelle(self):
        """Une réservation prise entre-temps pour un autre jour n'est pas écrasée."""
        lendemain = self.jour + datetime.timedelta(days=1)
        self.assertTrue(R.reserver_journee(lendemain))
        R.liberer_journee(self.jour, None)
        self.assertEqual(Instance.courante().derniere_relance_auto, lendemain)

    def test_reservation_conditionnelle(self):
        self.assertTrue(R.reserver_journee(self.jour))
        self.assertFalse(R.reserver_journee(self.jour))  # le second processus échoue
        self.assertFalse(R.reserver_journee(self.jour - datetime.timedelta(days=1)))  # jamais en arrière
        self.assertTrue(R.reserver_journee(self.jour + datetime.timedelta(days=1)))

    def test_le_lendemain_envoi(self):
        self.assertEqual(len(R.relancer_automatiquement(self.jour)), 2)
        lendemain = self.jour + datetime.timedelta(days=1)  # 6 jours avant la fin : jour d'échéance aussi
        self.assertEqual(len(R.relancer_automatiquement(lendemain)), 2)
        self.assertEqual(len(mail.outbox), 4)

    def test_simulation_et_envoi_manuel_non_bloques(self):
        self.assertEqual(len(R.relancer_automatiquement(self.jour)), 2)
        self.assertEqual(len(R.relancer_automatiquement(self.jour, simulation=True)), 2)  # dit toujours qui est concerné
        sortie = io.StringIO()
        call_command("relances", "--auto", "--simulation", stdout=sortie)
        self.assertEqual(len(mail.outbox), 2)
        af = R.a_faire([self.c], destinataires=[self.contrib.pk])[0]
        self.assertEqual(len(R.envoyer([af], par=self.admin)), 1)  # page Relances : envoyée
        self.assertEqual(len(mail.outbox), 3)

    def test_simulation_ne_reserve_pas(self):
        R.relancer_automatiquement(self.jour, simulation=True)
        self.assertIsNone(Instance.courante().derniere_relance_auto)
        self.assertEqual(len(R.relancer_automatiquement(self.jour)), 2)

    def test_pas_de_reservation_sans_campagne_du_jour(self):
        self.assertEqual(R.relancer_automatiquement(self.jour - datetime.timedelta(days=3)), [])
        self.assertIsNone(Instance.courante().derniere_relance_auto)


class ReservationParEspaceTests(EspacesTestCase):
    def test_chaque_espace_a_sa_journee(self):
        jour = datetime.date(2026, 11, 12)
        with E.activer("principal"):
            self.assertTrue(R.reserver_journee(jour))
            self.assertFalse(R.reserver_journee(jour))
        with E.activer("essai"):  # l'espace « essai » n'est pas bloqué par la réservation du principal
            self.assertTrue(R.reserver_journee(jour))
            self.assertFalse(R.reserver_journee(jour))
            self.assertEqual(Instance.courante().derniere_relance_auto, jour)
