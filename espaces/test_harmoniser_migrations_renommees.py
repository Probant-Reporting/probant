"""Migration renommée (``espaces/migrations_renommees.py``) : une base créée avant le renommage la note sous l'ancien
nom dans django_migrations. Toutes les portes qui appliquent ou comparent des migrations la reconnaissent : ``migrate`` de
toutes les bases et ``migrate --database`` (le nom actuel est ajouté, l'ancien gardé pour la version d'avant), démarrage
(sauvegarde avant), restauration d'une archive ancienne (SQLite et PostgreSQL, commande et page), reconstruction. Sans
cela : InconsistentMigrationHistory (la migration suivante est appliquée, pas celle d'avant), archive refusée comme
« d'une version plus récente ».

L'ancien nom n'est écrit nulle part : la règle vaut pour tout autre nom de la migration 0002 de ``parametres`` ; les tests
emploient donc un nom de remplacement (``ANCIEN``), traité exactement comme l'ancien nom réel."""
import io
import unittest
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from django.test import TransactionTestCase, override_settings

from . import contexte as E
from . import migrations_renommees as MR
from .aides_tests import DossierTemporaire, creer
from .essais import EspacesTestCase
from .models import Espace, Installation, MarqueEspace

ACTUEL = ("parametres", "0002_identite")
ANCIEN = ("parametres", "0002_nom_d_avant")  # tout autre nom de la migration 0002 de parametres
DEUX = {ANCIEN[1], ACTUEL[1]}  # après la mise à jour : le nom actuel ajouté, l'ancien gardé
BASES = ("default", E.COMMUN, "espace_essai")
SQLITE = settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")


def noms(alias, app="parametres"):
    return set(MigrationRecorder(connections[alias]).migration_qs.filter(app=app, name__startswith="0002_")
               .values_list("name", flat=True))


def vieillir(alias):
    """Remet la base dans l'état d'une base créée avant le renommage : la ligne de la migration porte l'ancien nom."""
    n = MigrationRecorder(connections[alias]).migration_qs.filter(app=ACTUEL[0], name=ACTUEL[1]).update(name=ANCIEN[1])
    assert n == 1, (alias, n)


class NomActuelTests(EspacesTestCase):
    def test_noms_et_listes(self):
        self.assertEqual(MR.nom_actuel(*ANCIEN), ACTUEL[1])
        self.assertEqual(MR.nom_actuel(*ACTUEL), ACTUEL[1])
        self.assertEqual(MR.nom_actuel("parametres", "0003_niveaux"), "0003_niveaux")
        self.assertEqual(MR.nom_actuel("referentiel", "0002_mot_de_passe_provisoire"), "0002_mot_de_passe_provisoire")
        self.assertEqual(MR.paires_actuelles([list(ANCIEN), ["parametres", "0001_instance"]]),
                         [["parametres", "0001_instance"], list(ACTUEL)])
        self.assertEqual(MR.paires_actuelles([list(ANCIEN), list(ACTUEL)]), [list(ACTUEL)])  # jamais en double

    def test_le_nom_actuel_est_celui_du_code(self):
        self.assertIn(ACTUEL, MigrationLoader(None, ignore_no_migrations=True).disk_migrations)
        for (app, numero), actuel in MR.RENOMMEES.items():
            self.assertIn((app, actuel), MigrationLoader(None, ignore_no_migrations=True).disk_migrations)
            self.assertTrue(actuel.startswith(f"{numero}_"))


class MigrateTests(EspacesTestCase):
    """Deux espaces (principal, « essai ») et le registre commun, chacun avec l'ancien nom."""

    def setUp(self):
        Installation.objects.create(identifiant="ici")  # marques : sans elles, « essai » ne serait pas migré
        MarqueEspace.objects.create(code="principal", installation="ici")
        MarqueEspace.objects.using("espace_essai").create(code="essai", installation="ici")
        E.marquer_indisponible("essai", "")  # état du processus, laissé par un autre test
        self.addCleanup(E.marquer_indisponible, "essai", "")
        for alias in BASES:
            vieillir(alias)

    def migrer(self, **options):
        erreurs = io.StringIO()
        call_command("migrate", verbosity=0, stdout=io.StringIO(), stderr=erreurs, **options)
        self.assertEqual(erreurs.getvalue(), "")

    def test_sans_harmonisation_django_refuse(self):
        """Preuve que la règle est nécessaire : Django refuse l'historique tel quel."""
        for alias in BASES:
            with self.assertRaises(InconsistentMigrationHistory):
                MigrationLoader(connections[alias]).check_consistent_history(connections[alias])

    def test_migrate_toutes_les_bases(self):
        quand = MigrationRecorder(connections["espace_essai"]).migration_qs.get(app=ANCIEN[0], name=ANCIEN[1]).applied
        self.migrer()
        for alias in BASES:
            self.assertEqual(noms(alias), DEUX, alias)
            MigrationLoader(connections[alias]).check_consistent_history(connections[alias])
            from parametres.management.commands.demarrage import migrations_en_attente

            self.assertEqual(migrations_en_attente(alias), [], alias)  # rien n'est rejoué
        self.assertEqual(MigrationRecorder(connections["espace_essai"]).migration_qs.get(app=ACTUEL[0], name=ACTUEL[1])
                         .applied, quand)  # même date d'application
        self.migrer()  # une seconde fois : rien de plus
        for alias in BASES:
            self.assertEqual(MigrationRecorder(connections[alias]).migration_qs.filter(app=ACTUEL[0], name=ACTUEL[1])
                             .count(), 1, alias)

    def test_migrate_une_base(self):
        self.migrer(database="espace_essai")
        self.assertEqual(noms("espace_essai"), DEUX)
        self.assertEqual(noms("default"), {ANCIEN[1]})  # les autres bases ne sont pas touchées
        self.migrer(database="default")
        self.assertEqual(noms("default"), DEUX)

    def test_migrate_check_et_les_deux_noms(self):
        """Base déjà mise à jour (les deux noms) : rien n'est ajouté. ``migrate --check`` : à jour."""
        self.assertEqual(MR.harmoniser(connections["default"]), 1)
        self.assertEqual(MR.harmoniser(connections["default"]), 0)  # déjà fait : rien
        self.assertEqual(MR.a_harmoniser(connections["default"]), [])
        self.migrer(check_unapplied=True)  # SystemExit si une migration était en attente
        self.assertEqual(noms("default"), DEUX)

    def test_autres_applications_intactes(self):
        avant = {a: set(MigrationRecorder(connections[a]).migration_qs.exclude(app="parametres", name__startswith="0002_")
                        .values_list("app", "name")) for a in BASES}
        self.migrer()
        for alias in BASES:
            self.assertEqual(set(MigrationRecorder(connections[alias]).migration_qs.exclude(
                app="parametres", name__startswith="0002_").values_list("app", "name")), avant[alias])

    def test_plan_et_check_n_ecrivent_rien(self):
        """``migrate --plan`` et ``migrate --check`` (toutes les bases ou une seule) : lecture seule, et rien en attente."""
        def historique():
            return {a: sorted(MigrationRecorder(connections[a]).migration_qs.values_list("app", "name", "applied"))
                    for a in BASES}

        avant = historique()
        sortie = io.StringIO()
        call_command("migrate", plan=True, verbosity=1, stdout=sortie, stderr=io.StringIO())
        self.assertIn("No planned migration operations", sortie.getvalue())
        self.migrer(check_unapplied=True)  # SystemExit si une migration était vue en attente
        self.migrer(check_unapplied=True, database="espace_essai")
        self.migrer(plan=True, database="espace_essai")
        self.assertEqual(historique(), avant)
        for alias in BASES:
            self.assertEqual(noms(alias), {ANCIEN[1]}, alias)

    def test_base_creee_apres_la_mise_a_jour(self):
        """Base qui n'a que le nom actuel (nouvel espace, base reconstruite par le nouveau code) dans une installation
        existante : ``migrate`` de toutes les bases y recopie l'ancienne ligne, lue dans la base principale ou le registre,
        pour que la version d'avant y démarre. ``migrate --database`` seul ne lit aucune autre base."""
        self.migrer()
        MigrationRecorder(connections["espace_essai"]).migration_qs.filter(app=ANCIEN[0], name=ANCIEN[1]).delete()
        quand = MigrationRecorder(connections["espace_essai"]).migration_qs.get(app=ACTUEL[0], name=ACTUEL[1]).applied
        self.migrer(database="espace_essai")
        self.assertEqual(noms("espace_essai"), {ACTUEL[1]})
        self.migrer()
        self.assertEqual(noms("espace_essai"), DEUX)
        self.assertEqual(MigrationRecorder(connections["espace_essai"]).migration_qs.get(app=ANCIEN[0], name=ANCIEN[1])
                         .applied, quand)
        # registre seul porteur de l'ancienne ligne : il suffit aussi
        for alias in ("default", "espace_essai"):
            MigrationRecorder(connections[alias]).migration_qs.filter(app=ANCIEN[0], name=ANCIEN[1]).delete()
        self.migrer()
        for alias in BASES:
            self.assertEqual(noms(alias), DEUX, alias)


class InstallationNeuveTests(EspacesTestCase):
    """Installation neuve : aucune base n'a l'ancien nom, rien n'est ajouté (pas de version d'avant où revenir)."""

    def setUp(self):
        Installation.objects.create(identifiant="ici")
        MarqueEspace.objects.create(code="principal", installation="ici")
        MarqueEspace.objects.using("espace_essai").create(code="essai", installation="ici")
        E.marquer_indisponible("essai", "")
        self.addCleanup(E.marquer_indisponible, "essai", "")

    def test_rien_n_est_ajoute(self):
        erreurs = io.StringIO()
        call_command("migrate", verbosity=0, stdout=io.StringIO(), stderr=erreurs)
        self.assertEqual(erreurs.getvalue(), "")
        for alias in BASES:
            self.assertEqual(noms(alias), {ACTUEL[1]}, alias)
            self.assertEqual(MR.harmoniser(connections[alias], MR.autres_bases(alias)), 0)


class CreationDUnEspaceTests(DossierTemporaire, EspacesTestCase):
    """Espace créé depuis l'outil après la mise à jour d'une installation existante : sa base reçoit les deux lignes."""

    def test_nouvel_espace(self):
        from .creation import creer as creer_espace

        for alias in ("default", E.COMMUN):
            vieillir(alias)
            MR.harmoniser(connections[alias])  # installation existante mise à jour : les deux lignes
        gestionnaire = creer("gestion@exemple.example", "admin")
        creer_espace("Achats France", "achats", gestionnaire)
        self.assertEqual(noms("espace_achats"), DEUX)
        MigrationLoader(connections["espace_achats"]).check_consistent_history(connections["espace_achats"])


class DemarrageEtRestaurationTests(TransactionTestCase):
    """Démarrage de l'image (sauvegarde avant, puis migrations) et restauration d'une archive faite avant le renommage,
    dans l'espace principal et dans l'espace « essai ». Hors transaction : la copie SQLite et la restauration l'exigent."""

    databases = {"default", "commun", "espace_essai"}

    def setUp(self):
        from parametres import niveaux as N
        from parametres import referentiel as PR

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        reglages = override_settings(DOSSIER_DONNEES=tmp, MEDIA_ROOT=tmp / "media", SAUVEGARDES_DIR=tmp / "sauvegardes",
                                     ESPACES_DOSSIER=tmp / "espaces-donnees")
        reglages.enable()
        self.addCleanup(reglages.disable)
        for code in ("principal", "essai"):  # réglages des migrations, effacés par le test précédent
            with E.activer(code):
                N.creer_par_defaut()
                PR.creer_par_defaut()
        Installation.objects.create(identifiant="ici")
        Espace.objects.create(code="principal", nom="RSE", etat="actif")
        Espace.objects.create(code="essai", nom="Achats", etat="actif", rang=1)
        MarqueEspace.objects.create(code="principal", installation="ici")
        MarqueEspace.objects.using("espace_essai").create(code="essai", installation="ici")
        self.addCleanup(self.rajeunir)
        for alias in BASES:
            vieillir(alias)

    @staticmethod
    def rajeunir():
        """Remet l'historique des bases de test au seul nom actuel (django_migrations n'est pas vidé entre les tests)."""
        for alias in BASES:
            MR.harmoniser(connections[alias])
            MigrationRecorder(connections[alias]).migration_qs.filter(app=ANCIEN[0], name=ANCIEN[1]).delete()

    @staticmethod
    def migrations_brutes(chemin):
        import json
        import zipfile

        with zipfile.ZipFile(chemin) as z:
            return json.loads(z.read("backup.json"))["migrations"]

    def test_demarrage(self):
        from parametres import sauvegardes as SV

        sortie = io.StringIO()
        call_command("demarrage", attente=1, stdout=sortie, stderr=io.StringIO())
        for alias in BASES:
            self.assertEqual(noms(alias), DEUX, alias)
            MigrationLoader(connections[alias]).check_consistent_history(connections[alias])
        self.assertIn('Space "Achats" (essai): ready', sortie.getvalue())
        # la sauvegarde d'avant la mise à jour garde l'ancien nom : l'ancienne version la restaure telle quelle
        for code in ("principal", "essai"):
            with E.activer(code):
                avant = [a for a in SV.archives() if "before-update" in a.nom]
                self.assertEqual(len(avant), 1, code)
                self.assertIn(list(ANCIEN), self.migrations_brutes(avant[0].chemin), code)

    def test_restauration_d_une_archive_d_avant(self):
        """Archive faite avant le renommage (descriptif et base à l'ancien nom), restaurée par le nouveau code, dans
        chacun des deux espaces."""
        from parametres import sauvegardes as SV
        from parametres.models import Instance

        for code, alias in (("principal", "default"), ("essai", "espace_essai")):
            with E.activer(code):
                Instance.objects.update_or_create(pk=1, defaults={"nom": f"Avant le renommage {code}"})
                archive = SV.creer("manual")
                self.assertIn(list(ANCIEN), self.migrations_brutes(archive.chemin))
                self.assertEqual(SV.lire_descriptif(archive.chemin)["migrations"].count(list(ACTUEL)), 1)  # nom actuel
                call_command("migrate", database=alias, verbosity=0, stdout=io.StringIO())  # base à jour, puis changée
                self.assertEqual(noms(alias), DEUX)
                Instance.objects.filter(pk=1).update(nom="Après")
                SV.restaurer(archive.chemin, sauvegarder_avant=False)
                self.assertEqual(Instance.objects.get(pk=1).nom, f"Avant le renommage {code}")
                self.assertEqual(noms(alias), DEUX)
                MigrationLoader(connections[alias]).check_consistent_history(connections[alias])

    def test_restauration_par_la_commande(self):
        """``manage.py restore`` (l'IT) : même archive, sans question sur la structure (PostgreSQL : pas de --rebuild)."""
        from parametres import sauvegardes as SV
        from parametres.models import Instance

        Instance.objects.update_or_create(pk=1, defaults={"nom": "Avant"})
        archive = SV.creer("manual")
        call_command("migrate", database="default", verbosity=0, stdout=io.StringIO())
        Instance.objects.filter(pk=1).update(nom="Après")
        sortie = io.StringIO()
        call_command("restore", archive.nom, "--yes", "--no-backup-before", stdout=sortie)
        self.assertNotIn("--rebuild", sortie.getvalue())
        self.assertEqual(Instance.objects.get(pk=1).nom, "Avant")
        self.assertEqual(noms("default"), DEUX)

    @unittest.skipIf(SQLITE, "reconstruction : PostgreSQL seulement")
    def test_base_reconstruite_garde_l_ancienne_ligne(self):
        """« restore --rebuild » par le nouveau code dans une installation existante : la base recréée par les migrations
        reçoit l'ancienne ligne (lue dans le registre), la version d'avant y démarre encore."""
        from parametres import sauvegardes as SV

        call_command("migrate", verbosity=0, stdout=io.StringIO(), stderr=io.StringIO())  # mise à jour : les deux lignes
        archive = SV.creer("manual", "json")
        MigrationRecorder(connections["default"]).record_applied("collecte", "9999_version_plus_recente")
        self.addCleanup(lambda: MigrationRecorder(connections["default"]).migration_qs.filter(
            app="collecte", name="9999_version_plus_recente").delete())
        SV.restaurer(archive.chemin, sauvegarder_avant=False, reconstruire=True)
        self.assertEqual(noms("default"), DEUX)
        self.assertFalse(MigrationRecorder(connections["default"]).migration_qs.filter(
            app="collecte", name="9999_version_plus_recente").exists())

    def test_reconstruction_possible_avec_l_ancien_nom(self):
        """« restore --rebuild » (PostgreSQL) : une archive de la version d'avant le renommage, qui a sinon exactement les
        migrations du code, se reconstruit."""
        from parametres import sauvegardes as SV

        code = SV.migrations_du_code()
        d = {"migrations": [list(ANCIEN) if tuple(m) == ACTUEL else m for m in code]}
        self.assertEqual(MR.paires_actuelles(d["migrations"]), code)
        self.assertEqual(SV.reconstruction_possible(d), not SQLITE)
