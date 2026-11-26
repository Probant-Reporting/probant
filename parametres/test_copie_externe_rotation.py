"""Rotation à distance de la copie externe : par défaut (« 0 »), rien n'est jamais supprimé à la destination ; sinon les N
plus récentes de chaque dossier (chaque espace, le registre) sont gardées, et SEULS les fichiers que l'outil dépose (dossier
et nom reconnus, sous le dossier de cette installation) sont supprimés : jamais un autre fichier, jamais ce qui est
ailleurs dans le compartiment ou sur le serveur (une autre installation, un autre usage)."""
import logging

from django.test import SimpleTestCase, TestCase

from parametres import copie_externe as CE
from parametres.aides_tests.copie import DossiersTemporaires, archive, identifiant_installation, regler_s3, regler_sftp
from parametres.aides_tests.faux_s3 import FauxS3, Objet
from parametres.aides_tests.faux_sftp import FauxSFTP

logging.getLogger("paramiko").setLevel(logging.CRITICAL)
ETRANGERS = ["notes.txt", "backup-2026.zip", "backup-20261101-023000-auto.zip.bak", "shared/backup-20260101-023000-auto.zip",
             "spaces/Achats/backup-20260101-023000-auto.zip", "spaces/achats/sous/backup-20260101-023000-auto.zip",
             "spaces/../backup-20260101-023000-auto.zip", ".probant-test-0011.txt", "autre/backup-20260101-023000-auto.zip"]


class ReconnaissanceTests(SimpleTestCase):
    def test_seuls_les_fichiers_de_l_outil(self):
        for rel in ("backup-20261101-023000-auto.zip", "spaces/achats/backup-20261101-023000-manuelle.zip",
                    "shared/registry-20261101-023000-auto.zip", "sauvegarde-20261101-023000.zip"):
            self.assertTrue(CE.reconnue(rel), rel)
        for rel in ETRANGERS:
            self.assertFalse(CE.reconnue(rel), rel)

    def test_garder_les_plus_recentes_par_dossier(self):
        objets = [(f"backup-2026110{i}-023000-auto.zip", 1) for i in range(1, 6)]
        objets += [(f"spaces/achats/backup-2026110{i}-023000-auto.zip", 1) for i in range(1, 4)]
        objets += [(f"shared/registry-2026110{i}-023000-auto.zip", 1) for i in range(1, 3)]
        objets += [(r, 1) for r in ETRANGERS]
        self.assertEqual(CE.a_supprimer(objets, 0), [])
        # une archive qui vient de partir n'est jamais supprimée dans le même passage (horloge remise en arrière : son
        # nom paraît plus ancien que les autres)
        self.assertNotIn("backup-20261101-023000-auto.zip", CE.a_supprimer(objets, 2, garder={"backup-20261101-023000-auto.zip"}))
        self.assertEqual(sorted(CE.a_supprimer(objets, 2)), sorted(
            ["backup-20261101-023000-auto.zip", "backup-20261102-023000-auto.zip", "backup-20261103-023000-auto.zip",
             "spaces/achats/backup-20261101-023000-auto.zip"]))


class RotationS3Tests(DossiersTemporaires, TestCase):
    databases = {"default", "commun"}

    def setUp(self):
        self.sauvegardes = self.dossiers()
        self.faux = FauxS3()
        self.addCleanup(self.faux.fermer)
        for i in range(1, 5):
            archive(self.sauvegardes, f"backup-2026110{i}-023000-auto.zip", 100)
            archive(self.sauvegardes, f"spaces/achats/backup-2026110{i}-023000-auto.zip", 100)
        archive(self.sauvegardes, "shared/registry-20261104-023000-auto.zip", 100)
        self.base = f"pre/{identifiant_installation()}/"
        for rel in ETRANGERS:
            self.faux.objets[self.base + rel] = Objet(b"x", "", 1, None)
        self.faux.objets["pre/autre-installation/backup-20200101-023000-auto.zip"] = Objet(b"x", "", 1, None)
        self.faux.objets["ailleurs/backup-20200101-023000-auto.zip"] = Objet(b"x", "", 1, None)

    def test_par_defaut_rien_n_est_supprime(self):
        regler_s3(self.faux)
        CE.passage()
        self.assertEqual([r for r in self.faux.requetes if r[0] == "DELETE"], [])
        self.assertEqual(len(self.faux.objets), 9 + len(ETRANGERS) + 2)

    def test_garder_deux_par_espace(self):
        regler_s3(self.faux, conserver=2)
        self.assertEqual(CE.passage(), 9)
        restant = sorted(k[len(self.base):] for k in self.faux.objets if k.startswith(self.base))
        self.assertEqual(restant, sorted(ETRANGERS + [
            "backup-20261103-023000-auto.zip", "backup-20261104-023000-auto.zip",
            "spaces/achats/backup-20261103-023000-auto.zip", "spaces/achats/backup-20261104-023000-auto.zip",
            "shared/registry-20261104-023000-auto.zip"]))
        self.assertIn("pre/autre-installation/backup-20200101-023000-auto.zip", self.faux.objets)
        self.assertIn("ailleurs/backup-20200101-023000-auto.zip", self.faux.objets)

    def test_la_derniere_archive_faite_jamais_supprimee(self):
        """Horloge remise en arrière (constat de l'essai réel) : la nouvelle archive a un nom plus ancien que les copies
        déjà là ; elle reste quand même à la destination."""
        import os
        import time

        regler_s3(self.faux, conserver=1)
        CE.passage()
        nouvelle = archive(self.sauvegardes, "backup-20261001-023000-auto.zip", 100)
        plus_tard = time.time() + 60
        os.utime(nouvelle, (plus_tard, plus_tard))
        self.assertEqual(CE.passage(), 1)
        self.assertIn(self.base + "backup-20261001-023000-auto.zip", self.faux.objets)
        self.assertIn(self.base + "backup-20261104-023000-auto.zip", self.faux.objets)


class RotationSFTPTests(DossiersTemporaires, TestCase):
    databases = {"default", "commun"}

    def test_garder_une_seule(self):
        sauvegardes = self.dossiers()
        racine = self.tmp / "serveur"
        dossier = racine / "sauvegardes" / identifiant_installation()
        (dossier / "spaces" / "achats").mkdir(parents=True)
        (dossier / "notes.txt").write_text("à garder")
        (racine / "sauvegardes" / "backup-20200101-023000-auto.zip").write_text("hors du dossier de l'installation")
        faux = FauxSFTP(racine)
        self.addCleanup(faux.fermer)
        for i in range(1, 4):
            archive(sauvegardes, f"backup-2026110{i}-023000-auto.zip", 100)
        regler_sftp(faux, conserver=1)
        self.assertEqual(CE.passage(), 3)
        self.assertEqual(sorted(p.name for p in dossier.iterdir() if p.is_file()), ["backup-20261103-023000-auto.zip", "notes.txt"])
        self.assertTrue((racine / "sauvegardes" / "backup-20200101-023000-auto.zip").exists())
