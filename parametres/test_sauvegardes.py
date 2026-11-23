"""Sauvegarde puis restauration sans perte (SQLite et JSON), rotation, refus des archives abîmées."""
import datetime
import io
import json
import shutil
import unittest
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from . import sauvegardes as SV
from .aides_tests.hebergement import DossiersTemporaires, MDP
from .models import Instance
from collecte.aides_tests import jeu_trois_niveaux as J
from collecte.models import Preuve, Reponse
from referentiel.models import Utilisateur


def contenu_base():
    """Toutes les tables, dates à la microseconde près (comparaison avant / après)."""
    sortie = io.StringIO()
    SV.exporter_json(sortie)
    return json.loads(sortie.getvalue())


def contenu_fichiers(racine):
    return {p.relative_to(racine).as_posix(): p.read_bytes() for p in Path(racine).rglob("*") if p.is_file()}


class SauvegardeRestauration(DossiersTemporaires, TransactionTestCase):
    """Jeu d'essai à trois niveaux complet (comptes, référentiels, campagnes, réponses, journal), une preuve et un logo."""

    def setUp(self):
        super().setUp()
        J.charger()
        r = Reponse.objects.exclude(valeur=None).first()
        Preuve.objects.create(reponse=r, fichier=ContentFile(b"%PDF-1.4 preuve fictive", name="facture.pdf"))
        i = Instance.courante()
        i.logo.save("logo.png", ContentFile(b"\x89PNG\r\n\x1a\nlogo fictif"))
        (Path(settings.MEDIA_ROOT) / "pending-imports").mkdir()
        (Path(settings.MEDIA_ROOT) / "pending-imports" / "temporaire.xlsx").write_bytes(b"temporaire")

    def aller_retour(self, format_base):
        avant_base, avant_fichiers = contenu_base(), contenu_fichiers(settings.MEDIA_ROOT)
        a = SV.creer("essai", format_base)
        with zipfile.ZipFile(a.chemin) as z:
            noms = z.namelist()
            d = json.loads(z.read("backup.json"))
        self.assertIn("database.sqlite3" if format_base == "sqlite" else "database.json", noms)
        self.assertIn("files/settings/logo/logo.png", noms)
        self.assertFalse([n for n in noms if "imports" in n])  # fichiers temporaires non sauvegardés
        self.assertEqual((d["version"], d["installation"], d["fichiers"]), (settings.VERSION, "Essai", 2))
        self.assertEqual(d["tables"]["collecte.Reponse"], Reponse.objects.count())
        # tout casser : réponses supprimées, identité changée, fichiers effacés
        Reponse.objects.all().delete()
        Instance.objects.filter(pk=1).update(nom="Autre")
        Utilisateur.objects.create_user("intrus", email="intrus@exemple.test", password=MDP)
        shutil.rmtree(Path(settings.MEDIA_ROOT) / "evidence")
        (Path(settings.MEDIA_ROOT) / "settings" / "logo" / "logo.png").write_bytes(b"autre logo")
        SV.restaurer(a.chemin)
        self.assertEqual(contenu_base(), avant_base)
        self.assertEqual(contenu_fichiers(settings.MEDIA_ROOT), avant_fichiers)
        self.assertTrue([x for x in SV.archives() if x.motif == "before-restore"])  # l'état cassé est gardé
        self.assertEqual(Instance.courante().nom, "Essai")

    @unittest.skipUnless(settings.DATABASES["default"]["ENGINE"].endswith("sqlite3"), "copie SQLite : base SQLite seulement")
    def test_sqlite_sans_perte(self):
        self.aller_retour("sqlite")

    def test_json_sans_perte(self):
        self.aller_retour("json")

    def test_archive_dit_probant(self):
        a = SV.creer("essai", "json")
        with zipfile.ZipFile(a.chemin) as z:
            self.assertEqual(json.loads(z.read("backup.json"))["outil"], "probant")

    def test_json_refuse_ne_vide_pas_la_base(self):
        """Une archive JSON dont le contenu est refusé (lien cassé) laisse la base telle qu'elle était : avant, la base
        était vidée puis le chargement échouait, sans plus aucun compte pour se reconnecter."""
        a = SV.creer("essai", "json")
        casse = SV.dossier() / "backup-20261101-000000-casse.zip"
        with zipfile.ZipFile(a.chemin) as src, zipfile.ZipFile(casse, "w") as z:
            for n in src.namelist():
                data = src.read(n)
                if n == "database.json":
                    objets = json.loads(data)
                    next(o for o in objets if o["model"] == "collecte.reponse")["fields"]["organisation"] = 999999
                    data = json.dumps(objets).encode()
                z.writestr(n, data)
        avant = contenu_base()
        with self.assertRaises(Exception):
            SV.restaurer(casse, sauvegarder_avant=False)
        self.assertEqual(contenu_base(), avant)
        self.assertTrue(Utilisateur.objects.exists())

    def test_commandes(self):
        sortie = io.StringIO()
        call_command("sauvegarde", "--motif", "essai", stdout=sortie)
        self.assertIn("Backup created", sortie.getvalue())
        nom = SV.archives()[0].nom
        Reponse.objects.all().delete()
        call_command("restauration", nom, "--oui", "--sans-sauvegarde-avant", stdout=io.StringIO())
        self.assertTrue(Reponse.objects.exists())
        self.assertEqual(len(SV.archives()), 1)
        sortie = io.StringIO()
        call_command("sauvegarde", "--liste", stdout=sortie)
        self.assertIn(nom, sortie.getvalue())


class Archives(DossiersTemporaires, TestCase):
    def test_rotation(self):
        d = Path(settings.SAUVEGARDES_DIR)
        d.mkdir()
        for jour in range(1, 6):
            (d / f"sauvegarde-202610{jour:02d}-023000-auto.zip").write_bytes(b"x")
        (d / "autre-fichier.zip").write_bytes(b"x")
        supprimees = SV.tourner(2)
        self.assertEqual(len(supprimees), 3)
        self.assertEqual([a.nom for a in SV.archives()], ["sauvegarde-20261005-023000-auto.zip", "sauvegarde-20261004-023000-auto.zip"])
        self.assertTrue((d / "autre-fichier.zip").exists())  # seules les archives de l'outil sont concernées

    def test_refus(self):
        for nom in ("../settings.py", "sauvegarde-x.zip", "sauvegarde-20261001-000000.zip"):
            with self.assertRaises(SV.ErreurSauvegarde):
                SV.archive(nom)
        faux = self.tmp / "faux.zip"
        faux.write_bytes(b"pas un zip")
        with self.assertRaisesMessage(SV.ErreurSauvegarde, "n'est pas une sauvegarde"):
            SV.restaurer(faux)
        recente = self.tmp / "recente.zip"
        with zipfile.ZipFile(recente, "w") as z:
            z.writestr("sauvegarde.json", json.dumps({"format": 1, "outil": "probant", "version": "9.0",
                                                      "migrations": [["collecte", "9999_futur"]]}))
            z.writestr("base.json", "[]")
        with self.assertRaisesMessage(SV.ErreurSauvegarde, "version plus récente"):
            SV.restaurer(recente)

    def test_prochaine_echeance(self):
        tz = timezone.get_current_timezone()
        avant = datetime.datetime(2026, 10, 26, 1, 0, tzinfo=tz)
        apres = datetime.datetime(2026, 10, 26, 3, 0, tzinfo=tz)
        self.assertEqual(SV.prochaine("02:30", avant), datetime.datetime(2026, 10, 26, 2, 30, tzinfo=tz))
        self.assertEqual(SV.prochaine("02:30", apres), datetime.datetime(2026, 10, 27, 2, 30, tzinfo=tz))

    def test_echeances_selon_la_frequence(self):
        tz = timezone.get_current_timezone()
        t = lambda j, h, m=0: datetime.datetime(2026, 10, j, h, m, tzinfo=tz)  # noqa: E731
        maintenant = t(26, 10)
        self.assertEqual(SV.echeance_suivante("6h", "02:30", None, maintenant), t(26, 14, 30))
        self.assertEqual(SV.echeance_suivante("12h", "02:30", None, maintenant), t(26, 14, 30))
        self.assertEqual(SV.echeance_suivante("jour", "02:30", None, maintenant), t(27, 2, 30))
        self.assertEqual(SV.echeance_suivante("6h", "02:30", t(26, 8, 31), maintenant), t(26, 14, 30))
        # serveur arrêté : l'échéance manquée (après la dernière sauvegarde) est déjà passée, donc rattrapée tout de suite
        self.assertEqual(SV.echeance_suivante("jour", "02:30", t(24, 2, 30), maintenant), t(25, 2, 30))
        self.assertEqual(SV.echeance_suivante("semaine", "02:30", t(20, 2, 30), maintenant), t(27, 2, 30))

    def test_base_vide_rien_a_sauvegarder(self):
        self.assertFalse(SV.base_vide())
