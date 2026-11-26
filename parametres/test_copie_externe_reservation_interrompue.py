"""Copie externe interrompue (conteneur redémarré pendant un envoi : mise à jour, redémarrage du serveur) :

- pendant un passage, la réservation donne signe de vie (``en_cours_le`` rafraîchi toutes les ``VIE`` secondes) : une
  copie réellement en cours n'est jamais prise pour une copie abandonnée ;
- au démarrage (``startup``, avant les tâches de fond), une réservation sans signe de vie depuis plus de ``SANS_VIE``
  est libérée (son processus n'existe plus) ; une réservation vivante (autre instance pendant un déploiement, commande
  lancée à la main) est gardée ;
- ``backup --copy`` pendant une copie en cours le dit clairement et ne se termine pas comme une réussite."""
import datetime
import io
import threading
import time
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from espaces.models import EtatCopie
from parametres import copie_externe as CE
from parametres.aides_tests.copie import DossiersTemporaires, archive, regler_s3
from parametres.aides_tests.faux_s3 import FauxS3

ARCHIVES = ["backup-20261101-023000-auto.zip", "shared/registry-20261101-023000-auto.zip"]


class ReservationInterrompueTests(DossiersTemporaires, TestCase):
    databases = {"default", "commun"}

    def setUp(self):
        self.sauvegardes = self.dossiers()
        self.faux = FauxS3()
        self.addCleanup(self.faux.fermer)
        for rel in ARCHIVES:
            archive(self.sauvegardes, rel)
        regler_s3(self.faux)

    def test_signe_de_vie_pendant_l_envoi(self):
        appels = []
        lent = CE.sha256_fichier

        def sha_lent(chemin):
            time.sleep(0.25)
            return lent(chemin)

        with mock.patch.object(CE, "VIE", 0.05), mock.patch.object(CE, "sha256_fichier", sha_lent), \
                mock.patch.object(CE, "_signe_de_vie", lambda: appels.append(threading.get_ident())):
            self.assertEqual(CE.passage(), 2)
            n = len(appels)
            time.sleep(0.2)
        self.assertGreaterEqual(n, 3)
        self.assertEqual(len(appels), n)  # plus rien après la fin du passage
        self.assertNotIn(threading.get_ident(), appels)  # à côté de l'envoi, pas entre deux archives
        self.assertIsNone(EtatCopie.objects.get().en_cours_le)

    def test_signe_de_vie_rafraichit_seulement_une_reservation_posee(self):
        avant = timezone.now() - datetime.timedelta(minutes=2)
        EtatCopie.objects.create(pk=1, en_cours_le=avant)
        CE._signe_de_vie()
        self.assertGreater(EtatCopie.objects.get().en_cours_le, avant)
        EtatCopie.objects.filter(pk=1).update(en_cours_le=None)
        CE._signe_de_vie()  # passage terminé entre-temps : la réservation n'est pas recréée
        self.assertIsNone(EtatCopie.objects.get().en_cours_le)

    def demarrer(self):
        sortie = io.StringIO()
        call_command("startup", stdout=sortie, stderr=io.StringIO())
        return sortie.getvalue()

    def test_demarrage_libere_une_reservation_sans_vie(self):
        quand = timezone.now() - CE.SANS_VIE - datetime.timedelta(seconds=30)
        EtatCopie.objects.create(pk=1, en_cours_le=quand)
        sortie = self.demarrer()
        self.assertIsNone(EtatCopie.objects.get().en_cours_le)
        self.assertIn("interrupted copy", sortie)
        self.assertEqual(CE.passage(), 2)  # la copie reprend aussitôt

    def test_demarrage_garde_une_copie_vivante(self):
        quand = timezone.now() - datetime.timedelta(seconds=20)  # autre instance, signe de vie récent
        EtatCopie.objects.create(pk=1, en_cours_le=quand)
        self.assertNotIn("interrupted copy", self.demarrer())
        self.assertEqual(EtatCopie.objects.get().en_cours_le, quand)
        self.assertIsNone(CE.passage())

    def test_backup_copy_pendant_une_copie_en_cours(self):
        EtatCopie.objects.create(pk=1, en_cours_le=timezone.now() - datetime.timedelta(seconds=20))
        sortie = io.StringIO()
        with self.assertRaises(CommandError) as cm:
            call_command("backup", "--copy", stdout=sortie)
        self.assertIn("already running", str(cm.exception))
        self.assertIn("2 archive(s) waiting", str(cm.exception))
        self.assertNotEqual(cm.exception.returncode, 0)
        self.assertNotIn("copied", sortie.getvalue())
        self.assertEqual(self.faux.requetes, [])
