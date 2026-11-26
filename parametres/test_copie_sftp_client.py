"""Client SFTP de la copie externe (``copie_sftp.ClientSFTP``), contre un faux serveur écrit avec les classes serveur de
paramiko (``aides_tests/faux_sftp.py``) : clé du serveur épinglée (inconnue : arrêt AVANT toute authentification, rien
n'est envoyé ; différente : refus, toujours avant l'authentification), mot de passe ou clé privée, dépôt dans un fichier
caché renommé à la fin, liste, relecture, suppression, causes en clair, connexion coupée pendant un dépôt."""
import hashlib
import logging
import os
import shutil
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from parametres import copie_sftp as F
from parametres.aides_tests.faux_sftp import FauxSFTP, cle_client_texte
from parametres.copie_reseau import ErreurCopie

logging.getLogger("paramiko").setLevel(logging.CRITICAL)  # le faux serveur voit des connexions coupées : attendu


@override_settings(COPIE_EXTERNE_LOCAL=True)
class ClientSFTPTests(SimpleTestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine, True)
        self.faux = FauxSFTP(self.racine)
        self.addCleanup(self.faux.fermer)
        self.archive = Path(self.racine) / "local.zip"
        self.contenu = os.urandom(70000)
        self.archive.write_bytes(self.contenu)
        self.sha = hashlib.sha256(self.contenu).hexdigest()

    def ouvrir(self, cle_epinglee="", mot_de_passe=None, cle_privee="", faux=None):
        faux = faux or self.faux
        return F.ClientSFTP("127.0.0.1", faux.port, "copie", faux.mot_de_passe if mot_de_passe is None else mot_de_passe,
                            cle_privee, "/sauvegardes", cle_epinglee, base="inst/", delai=5)

    def test_cle_inconnue_rien_n_est_envoye(self):
        with self.assertRaises(F.CleAConfirmer) as e, self.ouvrir():
            pass
        self.assertEqual(e.exception.cle, self.faux.cle_publique)
        self.assertEqual(self.faux.authentifications, [])  # ni mot de passe ni signature avant la confirmation
        self.assertTrue(F.empreinte(e.exception.cle).startswith("SHA256:"))
        self.assertNotIn("=", F.empreinte(e.exception.cle))

    def test_cle_differente_refusee_avant_l_authentification(self):
        autre = FauxSFTP(self.racine)  # même dossier, autre clé : le « serveur » a changé
        self.addCleanup(autre.fermer)
        with self.assertRaises(F.CleDifferente) as e, self.ouvrir(self.faux.cle_publique, faux=autre):
            pass
        self.assertEqual((e.exception.code, e.exception.cle), ("empreinte", autre.cle_publique))
        self.assertEqual(autre.authentifications, [])

    def test_depot_mot_de_passe(self):
        with self.ouvrir(self.faux.cle_publique) as c:
            c.deposer("spaces/achats/backup-20261101-023000-auto.zip", self.archive, len(self.contenu), self.sha)
            c.deposer("shared/registry-20261101-023000-auto.zip", self.archive, len(self.contenu), self.sha)
            self.assertEqual(c.taille("spaces/achats/backup-20261101-023000-auto.zip"), (len(self.contenu), None))
            self.assertIsNone(c.taille("absente.zip"))
            self.assertEqual(c.lire("shared/registry-20261101-023000-auto.zip", 10 ** 6), self.contenu)
            self.assertEqual(sorted(c.lister()), [("shared/registry-20261101-023000-auto.zip", len(self.contenu)),
                                                  ("spaces/achats/backup-20261101-023000-auto.zip", len(self.contenu))])
            c.supprimer("shared/registry-20261101-023000-auto.zip")
            c.supprimer("shared/registry-20261101-023000-auto.zip")  # déjà absente : sans erreur
        dossier = Path(self.racine) / "sauvegardes" / "inst"
        self.assertEqual(sorted(os.listdir(dossier / "spaces" / "achats")), ["backup-20261101-023000-auto.zip"])  # sans .part
        self.assertEqual(os.stat(dossier).st_mode & 0o777, 0o700)

    def test_depot_cle_privee(self):
        texte, cle = cle_client_texte()
        self.faux.cle_client = cle
        with self.ouvrir(self.faux.cle_publique, mot_de_passe="", cle_privee=texte) as c:
            c.deposer("backup-20261101-023000-auto.zip", self.archive, len(self.contenu), self.sha)
        self.assertEqual(self.faux.authentifications, [("publickey", "copie")])
        with self.assertRaises(ErreurCopie) as e:
            # en morceaux : le contrôle de publication cherche la forme d'une vraie clé privée
            F.lire_cle_privee("-----BEGIN OPENSSH " + "PRIVATE KEY-----\nabc\n-----END OPENSSH " + "PRIVATE KEY-----")
        self.assertEqual(e.exception.code, "cle_privee")

    def test_causes(self):
        with self.assertRaises(ErreurCopie) as e, self.ouvrir(self.faux.cle_publique, mot_de_passe="faux"):
            pass
        self.assertEqual(e.exception.code, "identifiants")
        self.faux.refus = {"write"}
        with self.ouvrir(self.faux.cle_publique) as c, self.assertRaises(ErreurCopie) as e:
            c.deposer("backup-20261101-023000-auto.zip", self.archive, len(self.contenu), self.sha)
        self.assertEqual(e.exception.code, "droits_ecrire")
        self.faux.refus = {"remove"}
        with self.ouvrir(self.faux.cle_publique) as c:
            c.deposer("backup-20261101-023000-auto.zip", self.archive, len(self.contenu), self.sha)
            with self.assertRaises(ErreurCopie) as e:
                c.supprimer("backup-20261101-023000-auto.zip")
        self.assertEqual(e.exception.code, "droits_supprimer")

    def test_connexion_coupee_pendant_un_depot(self):
        self.faux.couper_apres = 20000
        with self.assertRaises(ErreurCopie), self.ouvrir(self.faux.cle_publique) as c:
            c.deposer("backup-20261101-023000-auto.zip", self.archive, len(self.contenu), self.sha)
        dossier = Path(self.racine) / "sauvegardes" / "inst"
        self.assertNotIn("backup-20261101-023000-auto.zip", os.listdir(dossier))  # jamais un fichier final incomplet
        with self.ouvrir(self.faux.cle_publique) as c:  # reprise
            c.deposer("backup-20261101-023000-auto.zip", self.archive, len(self.contenu), self.sha)
        self.assertEqual((dossier / "backup-20261101-023000-auto.zip").read_bytes(), self.contenu)
