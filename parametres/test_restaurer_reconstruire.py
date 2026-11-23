"""Retour arrière après une mise à jour, sous PostgreSQL : archive JSON faite avant la mise à jour, base qui a depuis
des migrations de plus (version plus récente). Sans option : refus, rien n'est changé, le message dit quoi faire. Avec
« restore --rebuild » : base reconstruite pour la version installée puis remplie, tout ou rien."""
import io
import json
import unittest
import zipfile

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TransactionTestCase

from . import sauvegardes as SV
from .aides_tests.hebergement import DossiersTemporaires
from .models import Instance
from collecte.aides_tests import jeu_trois_niveaux as J
from collecte.models import Reponse

POSTGRES = settings.DATABASES["default"]["ENGINE"].endswith("postgresql")
FUTURE = ("collecte", "9999_version_plus_recente")


def contenu_base():
    sortie = io.StringIO()
    SV.exporter_json(sortie)
    return json.loads(sortie.getvalue())


def tables():
    return set(connection.introspection.table_names())


class RetourArriere(DossiersTemporaires, TransactionTestCase):

    def setUp(self):
        super().setUp()
        J.charger()  # jeu d'essai à trois niveaux : comptes, référentiels, campagnes, réponses, journal
        self.archive = SV.creer("before-update", "json")
        self.avant = contenu_base()
        self.migrations_archive = SV.migrations_appliquees()

    def mettre_a_jour(self):
        """Ce qu'une version plus récente laisse : une migration de plus, une table et une colonne nouvelles, des saisies
        faites après la mise à jour."""
        self.addCleanup(self.defaire)
        with connection.cursor() as c:
            c.execute("INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, CURRENT_TIMESTAMP)", FUTURE)
            if POSTGRES:
                c.execute("CREATE TABLE collecte_futur (id serial PRIMARY KEY, x integer)")
                c.execute("ALTER TABLE parametres_instance ADD COLUMN futur integer")
        Reponse.objects.filter(pk__in=Reponse.objects.order_by("pk").values("pk")[:5]).delete()
        Instance.objects.filter(pk=1).update(nom="Après la mise à jour")
        self.apres = contenu_base()

    def defaire(self):
        with connection.cursor() as c:
            c.execute("DELETE FROM django_migrations WHERE app = %s AND name = %s", FUTURE)
            if POSTGRES:
                c.execute("DROP TABLE IF EXISTS collecte_futur")
                c.execute("ALTER TABLE parametres_instance DROP COLUMN IF EXISTS futur")

    def test_sans_option_refus_explicite_et_rien_ne_change(self):
        self.mettre_a_jour()
        with self.assertRaises(SV.ErreurSauvegarde) as e:
            SV.restaurer(self.archive.chemin, sauvegarder_avant=False)
        self.assertIn("--rebuild", str(e.exception))
        self.assertEqual(contenu_base(), self.apres)
        self.assertIn(list(FUTURE), SV.migrations_appliquees())
        if POSTGRES:
            with self.assertRaises(CommandError) as e:
                call_command("restore", self.archive.nom, "--yes", stdout=io.StringIO())
            self.assertIn(f"python manage.py restore {self.archive.nom} --rebuild", str(e.exception))
            self.assertIn("Nothing was changed", str(e.exception))
            self.assertEqual(contenu_base(), self.apres)

    @unittest.skipUnless(POSTGRES, "reconstruction : PostgreSQL seulement")
    def test_rebuild_rend_l_etat_de_l_archive(self):
        self.mettre_a_jour()
        sortie = io.StringIO()
        call_command("restore", self.archive.nom, "--yes", "--rebuild", stdout=sortie)
        self.assertIn("Restore complete", sortie.getvalue())
        self.assertEqual(contenu_base(), self.avant)
        self.assertEqual(SV.migrations_appliquees(), self.migrations_archive)
        self.assertNotIn("collecte_futur", tables())
        colonnes = [c.name for c in connection.introspection.get_table_description(connection.cursor(), "parametres_instance")]
        self.assertNotIn("futur", colonnes)
        self.assertTrue([a for a in SV.archives() if a.motif == "before-restore"])  # l'état mis à jour est gardé
        # une restauration ordinaire marche de nouveau ensuite
        Instance.objects.filter(pk=1).update(nom="Autre")
        SV.restaurer(self.archive.chemin, sauvegarder_avant=False)
        self.assertEqual(contenu_base(), self.avant)

    @unittest.skipUnless(POSTGRES, "reconstruction : PostgreSQL seulement")
    def test_rebuild_tout_ou_rien(self):
        """Contenu refusé au chargement (lien cassé) : tables supprimées et recréées annulées avec le reste, la base
        mise à jour est intacte (table, colonne, migration de plus)."""
        self.mettre_a_jour()
        casse = SV.dossier() / "backup-20261101-000000-casse.zip"
        with zipfile.ZipFile(self.archive.chemin) as src, zipfile.ZipFile(casse, "w") as z:
            for n in src.namelist():
                data = src.read(n)
                if n == "database.json":
                    objets = json.loads(data)
                    next(o for o in objets if o["model"] == "collecte.reponse")["fields"]["organisation"] = 999999
                    data = json.dumps(objets).encode()
                z.writestr(n, data)
        with self.assertRaises(Exception):
            SV.restaurer(casse, sauvegarder_avant=False, reconstruire=True)
        self.assertEqual(contenu_base(), self.apres)
        self.assertIn(list(FUTURE), SV.migrations_appliquees())
        self.assertIn("collecte_futur", tables())
        self.assertFalse(SV.restauration_en_cours())

    @unittest.skipUnless(POSTGRES, "reconstruction : PostgreSQL seulement")
    def test_rebuild_refuse_une_archive_d_une_autre_version_que_le_code(self):
        """Archive plus ancienne que le code installé (serveur remplacé) : pas de reconstruction (le contenu se charge
        avec les modèles du code) ; le message dit d'installer la version qui l'a faite."""
        ancienne = SV.dossier() / "backup-20261101-000001-ancienne.zip"
        with zipfile.ZipFile(self.archive.chemin) as src, zipfile.ZipFile(ancienne, "w") as z:
            for n in src.namelist():
                data = src.read(n)
                if n == "backup.json":
                    d = json.loads(data)
                    d["migrations"] = [m for m in d["migrations"] if m != ["collecte", "0037_exports_arriere_plan"]]
                    data = json.dumps(d).encode()
                z.writestr(n, data)
        with self.assertRaises(CommandError) as e:
            call_command("restore", ancienne.name, "--yes", "--rebuild", stdout=io.StringIO())
        self.assertIn("install that version first", str(e.exception))
        with self.assertRaises(SV.ErreurSauvegarde):
            SV.restaurer(ancienne, sauvegarder_avant=False, reconstruire=True)
        self.assertEqual(contenu_base(), self.avant)
        self.assertIn(["collecte", "0037_exports_arriere_plan"], SV.migrations_appliquees())

    @unittest.skipUnless(POSTGRES, "reconstruction : PostgreSQL seulement")
    def test_rebuild_reprise_apres_un_arret(self):
        """Arrêt brutal après le repère « restauration en cours » : la reprise au démarrage refait la reconstruction."""
        self.mettre_a_jour()
        from unittest import mock

        with mock.patch.object(SV, "_echanger_fichiers", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            SV.restaurer(self.archive.chemin, sauvegarder_avant=False, reconstruire=True)
        self.assertTrue(SV.restauration_en_cours()["reconstruire"])
        self.assertEqual(SV.reprendre_restauration(), (self.archive.nom, ""))
        self.assertEqual(contenu_base(), self.avant)
        self.assertEqual(SV.migrations_appliquees(), self.migrations_archive)
