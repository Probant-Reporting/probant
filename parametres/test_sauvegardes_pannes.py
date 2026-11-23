"""Pannes provoquées : arrêt brutal, disque plein,
base abîmée, horloge qui recule, clé secrète vide. Données inventées seulement."""
import datetime
import errno
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from django.apps import apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.db import OperationalError, connection, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.utils import timezone

from collecte import saisie as S
from collecte.models import Preuve
from collecte.aides_tests.saisie import Base
from espaces import contexte as ESP
from espaces.models import Compte
from espaces.stockage import StockageEspace
from referentiel.models import Utilisateur

from . import pannes as PN
from . import sauvegardes as SV
from .models import Instance
from .aides_tests.hebergement import DossiersTemporaires, MDP, reglages

SQLITE = settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")


def fichiers(racine):
    return {p.relative_to(racine).as_posix(): p.read_bytes() for p in Path(racine).rglob("*") if p.is_file()}


class Panne(BaseException):
    """Arrêt brutal simulé (comme un SIGKILL, rien ne le rattrape dans l'outil)."""


@unittest.skipUnless(SQLITE, "copie SQLite et contrôle d'intégrité : base SQLite seulement")
class RestaurationInterrompue(DossiersTemporaires, TransactionTestCase):
    def setUp(self):
        super().setUp()
        Instance.objects.update_or_create(pk=1, defaults={"nom": "Essai"})
        Utilisateur.objects.create_user("garde", email="garde@exemple.test", password=MDP)
        self.media = Path(settings.MEDIA_ROOT)
        for rel, contenu in {"evidence/2026/E1/EFF/facture.pdf": b"%PDF facture", "settings/logo/logo.png": b"PNG"}.items():
            (self.media / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.media / rel).write_bytes(contenu)
        self.archive = SV.creer("essai")
        self.attendu = fichiers(self.media)
        # après la sauvegarde : un compte en moins, une preuve changée, une autre ajoutée
        Utilisateur.objects.filter(username="garde").delete()
        (self.media / "evidence/2026/E1/EFF/facture.pdf").write_bytes(b"%PDF autre")
        (self.media / "evidence/2026/E1/EFF/nouvelle.pdf").write_bytes(b"%PDF nouvelle")

    def test_arret_pendant_l_echange_des_fichiers_puis_reprise(self):
        vrai = SV._echanger_fichiers

        def echange_coupe(racine):
            entree = next(p for p in Path(racine).iterdir() if not p.name.startswith("."))
            (Path(racine) / SV.ANCIENS_FICHIERS).mkdir(exist_ok=True)
            entree.rename(Path(racine) / SV.ANCIENS_FICHIERS / entree.name)  # un dossier déjà passé, puis l'arrêt
            raise Panne()

        with mock.patch.object(SV, "_echanger_fichiers", echange_coupe), self.assertRaises(Panne):
            SV.restaurer(self.archive.chemin, par="essai")
        self.assertIsNotNone(SV.restauration_en_cours())
        self.assertTrue(Utilisateur.objects.filter(username="garde").exists())  # base déjà restaurée
        rep = self.client.get("/sante/")
        self.assertEqual(rep.status_code, 503)
        self.assertIn("interrupted restore", rep.json()["alerte"])
        with self.assertRaisesMessage(SV.ErreurSauvegarde, "interrompue"):
            SV.restaurer(self.archive.chemin)  # pas une seconde restauration par-dessus
        self.assertIs(SV._echanger_fichiers, vrai)
        nom, erreur = SV.reprendre_restauration()  # ce que fait le démarrage suivant
        self.assertEqual((nom, erreur), (self.archive.nom, ""))
        self.assertIsNone(SV.restauration_en_cours())
        self.assertEqual(fichiers(self.media), self.attendu)
        self.assertEqual([h["archive"] for h in SV.historique_restaurations()], [self.archive.nom])
        self.assertEqual(self.client.get("/sante/").status_code, 200)

    @unittest.skipUnless(os.name == "posix", "processus vivant : Linux / macOS")
    def test_processus_du_serveur_tue_reprise_sans_redemarrage(self):
        with mock.patch.object(SV, "_echanger_fichiers", side_effect=Panne()), self.assertRaises(Panne):
            SV.restaurer(self.archive.chemin)
        self.assertFalse(SV.restauration_abandonnee())  # ce processus vit encore : on n'y touche pas
        mort = subprocess.Popen([sys.executable, "-c", "pass"])
        mort.wait()
        repere = SV.dossier() / SV.EN_COURS
        repere.write_text(json.dumps({**json.loads(repere.read_text()), "pid": mort.pid}))
        self.assertTrue(SV.restauration_abandonnee())  # le planificateur des sauvegardes la termine
        self.assertEqual(SV.reprendre_restauration()[1], "")
        self.assertEqual(fichiers(self.media), self.attendu)

    def test_arret_avant_les_migrations_puis_reprise(self):
        with mock.patch.object(SV, "call_command", side_effect=Panne()), self.assertRaises(Panne):
            SV.restaurer(self.archive.chemin)
        self.assertIsNotNone(SV.restauration_en_cours())
        self.assertEqual(SV.reprendre_restauration()[1], "")
        self.assertEqual(fichiers(self.media), self.attendu)
        self.assertTrue(Utilisateur.objects.filter(username="garde").exists())

    def test_disque_plein_pendant_l_extraction_rien_ne_change(self):
        avant = fichiers(self.media)
        vrai = shutil.copyfileobj
        n = [0]

        def plein(*a, **k):
            n[0] += 1
            if n[0] > 1:
                raise OSError(errno.ENOSPC, "No space left on device")
            return vrai(*a, **k)

        vraie_extraction = SV._extraire_fichiers

        def extraction(*a):
            with mock.patch.object(SV.shutil, "copyfileobj", plein):
                return vraie_extraction(*a)

        with mock.patch.object(SV, "_extraire_fichiers", extraction), self.assertRaisesMessage(SV.ErreurSauvegarde, "place"):
            SV.restaurer(self.archive.chemin, sauvegarder_avant=False)
        self.assertEqual(fichiers(self.media), avant)
        self.assertFalse(Utilisateur.objects.filter(username="garde").exists())  # base inchangée
        self.assertIsNone(SV.restauration_en_cours())
        self.assertFalse((self.media / SV.NOUVEAUX).exists())

    def test_base_abimee_ni_sauvegardee_ni_tournee(self):
        with mock.patch.object(SV, "controle_sqlite", return_value="Tree 7 page 12: btree corrupt"):
            with self.assertRaisesMessage(SV.ErreurSauvegarde, "abîmée"):
                SV.creer("auto")
            self.assertIn("corrupt", SV.base_abimee())
            rep = self.client.get("/sante/")
            self.assertEqual(rep.status_code, 503)
            self.assertIn("damaged database", rep.json()["alerte"])
            a = SV.creer("before-restore", accepter_abimee=True)  # avant une restauration : gardée quand même, marquée
            self.assertIn("damaged", a.nom)
        self.assertEqual(SV.derniere_archive_saine().nom, self.archive.nom)
        SV.creer("auto")  # base de nouveau saine : l'alerte disparaît
        self.assertEqual(SV.base_abimee(), "")

    def test_restes_d_un_arret_brutal_effaces(self):
        d = SV.dossier()
        (d / ".backup-123-456.partiel").write_bytes(b"zip partiel")
        (self.media / SV.NOUVEAUX / "evidence").mkdir(parents=True)
        partiel = self.media / "evidence/2026/E1/EFF/.gros.pdf.0123abcd.part"
        partiel.write_bytes(b"%PDF tronque")
        self.assertEqual(SV.nettoyer_restes() + SV.nettoyer_depots_partiels(), 3)
        self.assertEqual([p.name for p in d.iterdir()], [self.archive.nom])
        self.assertFalse(partiel.exists() or (self.media / SV.NOUVEAUX).exists())
        with zipfile.ZipFile(SV.creer("essai").chemin) as z:  # un dépôt en cours n'est jamais sauvegardé
            self.assertFalse([n for n in z.namelist() if n.endswith(".part")])


class HorlogeEtDisque(DossiersTemporaires, TestCase):
    def test_horloge_remise_en_arriere(self):
        """Archives faites pendant que l'horloge avançait d'un an : la rotation les garde mais n'efface pas la nouvelle,
        et la prochaine sauvegarde automatique n'attend pas un an."""
        d = Path(settings.SAUVEGARDES_DIR)
        d.mkdir()
        futur = timezone.localtime() + datetime.timedelta(days=365)
        for i in range(3):
            (d / f"backup-{futur + datetime.timedelta(days=i):%Y%m%d}-023000-auto.zip").write_bytes(b"x")
        for i in range(1, 4):
            (d / f"backup-{timezone.localtime() - datetime.timedelta(days=i):%Y%m%d}-023000-auto.zip").write_bytes(b"x")
        recente = d / f"backup-{timezone.localtime():%Y%m%d-%H%M%S}-auto.zip"
        recente.write_bytes(b"x")
        with self.assertLogs("reporting.sauvegarde", "WARNING"):
            supprimees = SV.tourner(2)
        self.assertEqual(len(supprimees), 2)
        self.assertTrue(recente.exists())
        self.assertEqual(len(SV.archives()), 5)  # 3 dans le futur + les 2 plus récentes
        prochaine = SV.echeance_suivante("jour", "02:30", futur, timezone.localtime())
        self.assertLessEqual(prochaine - timezone.localtime(), datetime.timedelta(days=1))

    def test_sante_disque_presque_plein(self):
        with self.settings(ALERTE_DISQUE_MO=10 ** 9):  # seuil plus grand que tout disque
            rep = self.client.get("/sante/")
        self.assertEqual(rep.status_code, 503)
        self.assertIn("disk almost full", rep.json()["alerte"])

    def test_sauvegarde_disque_plein_message_clair(self):
        Instance.objects.update_or_create(pk=1, defaults={"nom": "Essai"})
        with mock.patch.object(SV.zipfile.ZipFile, "writestr", side_effect=OSError(errno.ENOSPC, "No space left")):
            with self.assertRaisesMessage(SV.ErreurSauvegarde, "place"):
                SV.creer("essai", "json")
        self.assertEqual(SV.archives(), [])
        self.assertEqual([p.name for p in SV.dossier().iterdir()], [])  # pas d'archive partielle

    def test_depot_d_une_preuve_interrompu_sans_fichier_tronque(self):
        class Coupe(ContentFile):
            def chunks(self, chunk_size=None):
                yield b"%PDF debut"
                raise OSError(errno.ENOSPC, "No space left on device")

        stockage = StockageEspace()
        with self.assertRaises(OSError):
            stockage.save("evidence/2026/X/EFF/gros.pdf", Coupe(b"", name="gros.pdf"))
        self.assertEqual(fichiers(settings.MEDIA_ROOT), {})
        nom = stockage.save("evidence/2026/X/EFF/bon.pdf", ContentFile(b"%PDF bon"))
        self.assertEqual(fichiers(settings.MEDIA_ROOT), {nom: b"%PDF bon"})
        nom2 = stockage.save("evidence/2026/X/EFF/bon.pdf", ContentFile(b"%PDF second"))  # nom déjà pris
        self.assertNotEqual(nom2, nom)
        self.assertEqual(Path(settings.MEDIA_ROOT, nom).read_bytes(), b"%PDF bon")

    def test_page_claire_si_la_base_refuse_d_ecrire(self):
        m = PN.PanneStockageMiddleware(lambda r: None)
        requete = RequestFactory().post("/saisie/")
        with self.assertLogs("reporting.stockage", "ERROR"):
            rep = m.process_exception(requete, OperationalError("database or disk is full"))
        self.assertEqual(rep.status_code, 503)
        self.assertIn("n'a pas enregistré votre dernière action, même en partie", rep.content.decode())
        self.assertIsNone(m.process_exception(requete, ValueError("autre")))
        self.assertTrue(PN.panne_de_stockage(OSError(errno.EROFS, "Read-only file system")))


class PreuvesEtTransactions(Base):
    def setUp(self):
        super().setUp()
        self.r = self.enregistrer("40")

    def test_preuve_retiree_garde_son_fichier_si_l_enregistrement_echoue(self):
        p = S.ajouter_preuve(self.contrib, self.c, self.eff, self.e1, ContentFile(b"%PDF-1.4 x", name="facture.pdf"))
        chemin = Path(p.fichier.path)
        with self.assertRaises(Panne), transaction.atomic():
            S.retirer_preuve(self.contrib, Preuve.objects.get(pk=p.pk), self.c)
            raise Panne()  # la base n'enregistre pas la suppression
        self.assertTrue(chemin.exists() and Preuve.objects.filter(pk=p.pk).exists())
        with self.captureOnCommitCallbacks(execute=True):
            S.retirer_preuve(self.contrib, Preuve.objects.get(pk=p.pk), self.c)
        self.assertFalse(chemin.exists())

    def test_preuve_refusee_par_la_base_sans_fichier_orphelin(self):
        avant = fichiers(settings.MEDIA_ROOT)
        with mock.patch.object(S.Journal, "ecrire", side_effect=OperationalError("database or disk is full")):
            with self.assertRaises(OperationalError):
                S.ajouter_preuve(self.contrib, self.c, self.eff, self.e1, ContentFile(b"%PDF-1.4 y", name="releve.pdf"))
        self.assertEqual(fichiers(settings.MEDIA_ROOT), avant)

    def test_migration_0029_reprise_apres_arret(self):
        """Rangement des preuves interrompu : un fichier déjà déplacé dont le nom n'était pas encore enregistré est
        retrouvé à sa nouvelle place au redémarrage (avant : preuve sans fichier)."""
        media = Path(settings.MEDIA_ROOT)
        ancien = f"preuves/2026/EFF/{self.e1.id}_facture.pdf"
        nouveau = f"evidence/2026/{self.e1.code}/EFF/facture.pdf"
        (media / nouveau).parent.mkdir(parents=True, exist_ok=True)
        (media / nouveau).write_bytes(b"%PDF deja deplace")  # déplacé par l'exécution interrompue
        (p,) = Preuve.objects.bulk_create([Preuve(reponse=self.r, fichier=ancien, nom_fichier="facture.pdf")])
        migration = importlib.import_module("collecte.migrations.0029_rangement_fichiers")
        self.assertFalse(migration.Migration.atomic)
        migration.ranger(apps, type("Editeur", (), {"connection": connection})())
        p.refresh_from_db()
        self.assertEqual(p.fichier.name, nouveau)
        self.assertEqual((media / p.fichier.name).read_bytes(), b"%PDF deja deplace")


class RegistreToutOuRien(TransactionTestCase):
    databases = {"default", "commun"}

    def test_registre_refuse_reste_intact(self):
        with tempfile.TemporaryDirectory() as dossier, self.settings(SAUVEGARDES_DIR=Path(dossier) / "essai-registre"):
            tmp = Path(dossier) / "essai-registre"
            Utilisateur.objects.create_user("reg", email="reg@exemple.test", password=MDP)
            avant = Compte.objects.count()
            self.assertTrue(avant)
            casse = tmp / "registry-20261101-000000-casse.zip"
            casse.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(casse, "w") as z:
                z.writestr("backup.json", json.dumps({"format": 1, "outil": "probant", "contenu": "registre"}))
                z.writestr("registry.json", json.dumps([{"model": "espaces.accesespace", "pk": 1,
                                                         "fields": {"compte": 999999, "espace": 999999}}]))
            with self.assertRaises(Exception):
                SV.restaurer_registre(casse)
            self.assertEqual(Compte.objects.count(), avant)  # avant : registre vidé, plus aucun compte


class CleSecrete(TestCase):
    def test_fichier_vide_remplace(self):
        """Clé créée par une version interrompue entre la création du fichier et son écriture : fichier vide. Avant,
        toutes les pages (et /sante/) échouaient ; maintenant une nouvelle clé est écrite."""
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        tmp = Path(dossier.name) / "essai-cle"
        tmp.mkdir(parents=True, exist_ok=True)
        (tmp / ".secret_key").write_text("")
        cle = reglages({"DOSSIER_DONNEES": str(tmp)}, "print(json.dumps(s.SECRET_KEY))")
        self.assertGreaterEqual(len(cle), 50)
        self.assertEqual((tmp / ".secret_key").read_text(), cle)
        self.assertEqual(reglages({"DOSSIER_DONNEES": str(tmp)}, "print(json.dumps(s.SECRET_KEY))"), cle)
        self.assertEqual([p.name for p in tmp.iterdir()], [".secret_key"])  # pas de fichier temporaire laissé


@unittest.skipUnless(SQLITE, "base SQLite seulement")
class DemarrageBaseAbimee(DossiersTemporaires, TransactionTestCase):
    def test_demarrage_signale_sans_migrer(self):
        Instance.objects.update_or_create(pk=1, defaults={"nom": "Essai"})
        sortie, erreurs = io.StringIO(), io.StringIO()
        with mock.patch.object(SV, "controle_sqlite", return_value="Rowid 20017 out of order"):
            call_command("startup", stdout=sortie, stderr=erreurs)
        self.assertIn("DAMAGED DATABASE", erreurs.getvalue())
        self.assertIn("WITHOUT updating", erreurs.getvalue())
        self.assertTrue(SV.base_abimee(ESP.PRINCIPAL))
        call_command("startup", stdout=io.StringIO(), stderr=io.StringIO())  # base saine : alerte retirée
        self.assertEqual(SV.base_abimee(ESP.PRINCIPAL), "")
