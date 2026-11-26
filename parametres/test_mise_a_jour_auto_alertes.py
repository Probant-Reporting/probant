"""Alertes de la mise à jour automatique (``mise_a_jour_auto.synchroniser_alertes``, appelée à chaque tour des boucles
planifiées) : le dernier résultat de la tâche de la machine devient un problème signalé (page Santé, alertes par
e-mail) par ``alertes.signaler`` et disparaît par ``alertes.resoudre``. Un seul cas à la fois, chacun sa clé."""
import datetime
import os
from unittest import mock

from django.core import mail
from django.utils import timezone

from espaces.essais import EspacesTestCase
from espaces.models import ProblemeSignale
from parametres import alertes as AL
from parametres import mise_a_jour_auto as MA
from parametres.aides_tests.alertes import T0, DossierAlertes
from parametres.test_mise_a_jour_auto_ecran import resultat

DOCKER = mock.patch.dict(os.environ, {"DANS_DOCKER": "1"})


def instant(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


class AlertesTests(DossierAlertes, EspacesTestCase):
    adresses = "it@exemple.example"

    def setUp(self):
        super().setUp()
        DOCKER.start()
        self.addCleanup(DOCKER.stop)

    def ecrire(self, **valeurs):
        MA.dossier().mkdir(parents=True, exist_ok=True)
        (MA.dossier() / MA.RESULTAT).write_text(resultat(**valeurs), encoding="utf-8")

    def signales(self):
        return sorted(ProblemeSignale.objects.values_list("cle", "etat"))

    def test_chaque_etat_son_alerte(self):
        maintenant = timezone.now()
        cas = {
            "updated": [("mise_a_jour_auto.updated", "regarder")],
            "available": [("mise_a_jour_auto.available", "regarder")],
            "refused": [("mise_a_jour_auto.refused", "regarder")],
            "rolled_back": [("mise_a_jour_auto.rolled_back", "regarder")],
            "failed": [("mise_a_jour_auto.failed", "panne")],
            "up_to_date": [], "off": [], "waiting": [], "postponed": [], "installed": [], "not_available": [],
            "task_removed": [], "check_failed": [],
        }
        for etat, attendu in cas.items():
            with self.subTest(etat):
                self.ecrire(state=etat, checked=instant(maintenant), since=instant(maintenant), available="1.0.3")
                MA.synchroniser_alertes(maintenant)
                self.assertEqual(self.signales(), attendu)

    def test_mise_a_jour_faite_montree_un_jour(self):
        self.ecrire(state="updated", checked=instant(T0), previous="1.0.1")
        MA.synchroniser_alertes(T0 + datetime.timedelta(hours=23))
        self.assertEqual(self.signales(), [("mise_a_jour_auto.updated", "regarder")])
        MA.synchroniser_alertes(T0 + datetime.timedelta(hours=25))
        self.assertEqual(self.signales(), [])

    def test_verification_impossible_depuis_plusieurs_jours(self):
        debut = T0 - datetime.timedelta(days=2)
        self.ecrire(state="check_failed", reason="network", checked=instant(T0), since=instant(debut))
        MA.synchroniser_alertes(T0)
        self.assertEqual(self.signales(), [], "une nuit sans réseau n'alerte pas")
        MA.synchroniser_alertes(T0 + datetime.timedelta(days=2))
        self.assertEqual(self.signales(), [("mise_a_jour_auto.check_failed", "regarder")])

    def test_tache_qui_ne_tourne_plus(self):
        self.ecrire(state="up_to_date", checked=instant(T0))
        MA.synchroniser_alertes(T0 + datetime.timedelta(days=4))
        self.assertEqual(self.signales(), [("mise_a_jour_auto.silence", "regarder")])
        self.ecrire(state="up_to_date", checked=instant(T0), task="manual")  # lancée à la main : pas de minuterie à surveiller
        MA.synchroniser_alertes(T0 + datetime.timedelta(days=4))
        self.assertEqual(self.signales(), [])

    def test_fichier_invalide_ou_hors_docker_rien_n_est_signale(self):
        self.ecrire(state="failed")
        MA.synchroniser_alertes()
        self.assertEqual(len(self.signales()), 1)
        (MA.dossier() / MA.RESULTAT).write_text("state=failed\nformat=1\nchecked=bad\n", encoding="utf-8")
        MA.synchroniser_alertes()
        self.assertEqual(self.signales(), [])
        self.ecrire(state="failed")
        with mock.patch.dict(os.environ, {"DANS_DOCKER": ""}):
            MA.synchroniser_alertes()
        self.assertEqual(self.signales(), [])

    def test_alerte_envoyee_par_e_mail_et_montree_sur_la_page_sante(self):
        self.ecrire(state="failed", reason="restore_failed", available="1.0.3", previous="1.0.2", checked=instant(T0))
        mail.outbox = []
        with mock.patch.object(AL, "_premier", -10**9):  # boucle planifiée lancée depuis longtemps
            r = AL.passage_planifie()
        self.assertEqual(self.signales(), [("mise_a_jour_auto.failed", "panne")])
        self.assertIn("signal-mise_a_jour_auto.failed", r["nouveaux"])
        texte = mail.outbox[0].body
        self.assertIn("1.0.3", texte)
        self.assertNotIn("restore_failed", texte, "le détail pour l'IT n'est jamais dans un e-mail")
        from parametres import sante_installation as SI

        lignes = [x for x in SI.constats(True) if x["cle"] == "signal-mise_a_jour_auto.failed"]
        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes[0]["etat"], "panne")
        # tout est rentré dans l'ordre : résolu
        self.ecrire(state="up_to_date")
        MA.synchroniser_alertes()
        self.assertEqual(self.signales(), [])
