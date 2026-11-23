"""Rangement des fichiers (parametres/rangement.py, migrations collecte/0029 et 0030) : chaque document à sa place, sans perte."""
import importlib
import shutil
import tempfile
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import connection
from django.test import override_settings

from collecte import saisie as S
from collecte.models import Preuve
from collecte.aides_tests.saisie import Base
from config import settings as reglages

from . import rangement as RG
from .models import Instance


class RangementTests(Base):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        o = override_settings(MEDIA_ROOT=self.tmp / "files")
        o.enable()
        self.addCleanup(o.disable)
        self.r = S.enregistrer(self.contrib, self.c, self.eff, self.e1, "40", False, "")

    def test_preuve_rangee_par_periode_organisation_kpi(self):
        p = Preuve.objects.create(reponse=self.r, fichier=ContentFile(b"%PDF-1.4 x", name="facture gaz.pdf"))
        self.assertEqual(p.fichier.name, f"evidence/2026/{self.e1.code}/EFF/facture-gaz.pdf")
        self.assertTrue((self.tmp / "files" / p.fichier.name).is_file())
        p2 = Preuve.objects.create(reponse=self.r, fichier=ContentFile(b"%PDF-1.4 y", name="facture gaz.pdf"))
        self.assertNotEqual(p2.fichier.name, p.fichier.name)  # même nom : la première garde sa place
        self.assertEqual((self.tmp / "files" / p.fichier.name).read_bytes(), b"%PDF-1.4 x")

    def test_ancien_dossier_media_range(self):
        ancien = self.tmp / "media"
        for rel, contenu in {"preuves/2025/EFF/3_a.pdf": b"a", "imports/x.xlsx": b"x", "identite/logo.png": b"l"}.items():
            (ancien / rel).parent.mkdir(parents=True, exist_ok=True)
            (ancien / rel).write_bytes(contenu)
        (self.tmp / "files").mkdir()  # déjà créé (vide) par le démarrage
        RG.ranger_racine(self.tmp / "files")
        racine = self.tmp / "files"
        self.assertFalse(ancien.exists())
        self.assertEqual((racine / "evidence/2025/EFF/3_a.pdf").read_bytes(), b"a")
        self.assertEqual((racine / "pending-imports/x.xlsx").read_bytes(), b"x")
        self.assertEqual((racine / "settings/logo/logo.png").read_bytes(), b"l")
        RG.ranger_racine(racine)  # une seconde fois : rien ne bouge
        self.assertEqual(sorted(p.relative_to(racine).as_posix() for p in racine.rglob("*") if p.is_file()),
                         ["evidence/2025/EFF/3_a.pdf", "pending-imports/x.xlsx", "settings/logo/logo.png"])

    def test_migration_des_fichiers_existants(self):
        """Ancien rangement (dossier « media », preuves/<période>/<KPI>/<n°>_<nom>, logo dans identite/) : fichiers
        déplacés, noms enregistrés mis à jour, contenu intact ; un fichier absent garde son nom."""
        ancien = self.tmp / "media"
        anciens = {f"preuves/2026/EFF/{self.e1.id}_facture.pdf": b"%PDF facture",
                   f"preuves/2026/EFF/{self.e1.id}_releve.pdf": b"%PDF releve", "identite/logo.png": b"PNG"}
        for rel, contenu in anciens.items():
            (ancien / rel).parent.mkdir(parents=True, exist_ok=True)
            (ancien / rel).write_bytes(contenu)
        p1, p2, p3 = Preuve.objects.bulk_create([  # enregistrées telles quelles, comme avant la mise à jour
            Preuve(reponse=self.r, fichier=f"preuves/2026/EFF/{self.e1.id}_facture.pdf", nom_fichier="facture.pdf"),
            Preuve(reponse=self.r, fichier=f"preuves/2026/EFF/{self.e1.id}_releve.pdf", nom_fichier="releve.pdf"),
            Preuve(reponse=self.r, fichier="preuves/2026/EFF/perdu.pdf", nom_fichier="perdu.pdf")])  # déjà absent
        Instance.objects.update_or_create(pk=1, defaults={"logo": "identite/logo.png"})
        migration = importlib.import_module("collecte.migrations.0029_rangement_fichiers")
        migration.ranger(apps, type("Editeur", (), {"connection": connection})())
        racine = self.tmp / "files"
        for p, contenu, nom in ((p1, b"%PDF facture", "facture.pdf"), (p2, b"%PDF releve", "releve.pdf")):
            p.refresh_from_db()
            self.assertEqual(p.fichier.name, f"evidence/2026/{self.e1.code}/EFF/{nom}")
            self.assertEqual((racine / p.fichier.name).read_bytes(), contenu)
        p3.refresh_from_db()
        self.assertEqual(p3.fichier.name, "preuves/2026/EFF/perdu.pdf")
        self.assertEqual(Instance.objects.get(pk=1).logo.name, "settings/logo/logo.png")
        self.assertEqual((racine / "settings/logo/logo.png").read_bytes(), b"PNG")
        self.assertFalse(ancien.exists())
        self.assertFalse((racine / "preuves/2026/EFF").exists() or (racine / "preuves").exists())  # anciens dossiers vides retirés

    def test_migration_noms_anglais(self):
        """Rangement français (fichiers/preuves, fichiers/reglages/logo) : passé en anglais, noms enregistrés suivis."""
        ancien = self.tmp / "fichiers"
        for rel, contenu in {"preuves/2026/X/EFF/f.pdf": b"%PDF f", "reglages/logo/logo.png": b"PNG",
                             "imports-en-cours/t.xlsx": b"t"}.items():
            (ancien / rel).parent.mkdir(parents=True, exist_ok=True)
            (ancien / rel).write_bytes(contenu)
        (p,) = Preuve.objects.bulk_create([Preuve(reponse=self.r, fichier="preuves/2026/X/EFF/f.pdf", nom_fichier="f.pdf")])
        Instance.objects.update_or_create(pk=1, defaults={"logo": "reglages/logo/logo.png"})
        migration = importlib.import_module("collecte.migrations.0030_noms_anglais_fichiers")
        migration.renommer(apps, type("Editeur", (), {"connection": connection})())
        racine = self.tmp / "files"
        p.refresh_from_db()
        self.assertEqual(p.fichier.name, "evidence/2026/X/EFF/f.pdf")
        self.assertEqual((racine / p.fichier.name).read_bytes(), b"%PDF f")
        self.assertEqual(Instance.objects.get(pk=1).logo.name, "settings/logo/logo.png")
        self.assertEqual((racine / "settings/logo/logo.png").read_bytes(), b"PNG")
        self.assertEqual((racine / "pending-imports/t.xlsx").read_bytes(), b"t")
        self.assertFalse(ancien.exists() or (racine / "reglages").exists() or (racine / "preuves").exists())

    def test_donnees_de_developpement_sorties_du_code(self):
        projet = self.tmp / "projet"
        (projet / "media" / "preuves").mkdir(parents=True)
        (projet / "media" / "preuves" / "a.pdf").write_bytes(b"a")
        (projet / "db.sqlite3").write_bytes(b"base")
        (projet / "sauvegardes").mkdir()
        dossier = projet / reglages.DONNEES_LOCALES
        reglages._ranger_donnees_locales(projet, dossier)
        reglages._noms_anglais(dossier)
        RG.ranger_racine(dossier / RG.FICHIERS)
        self.assertEqual((dossier / "db.sqlite3").read_bytes(), b"base")
        self.assertEqual((dossier / "files" / "evidence" / "a.pdf").read_bytes(), b"a")
        self.assertTrue((dossier / "backups").is_dir())
        self.assertFalse((projet / "db.sqlite3").exists() or (projet / "media").exists())

    def test_lisez_moi(self):
        RG.ecrire_lisez_moi(self.tmp)
        texte = (self.tmp / "README.txt").read_text(encoding="utf-8")
        self.assertIn("evidence/", texte)
        self.assertIn("settings/logo/", texte)
        RG.ecrire_lisez_moi(settings.BASE_DIR)  # jamais dans le dossier du code
        self.assertFalse((Path(settings.BASE_DIR) / "README.txt").exists())
