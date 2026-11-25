"""Version tout-en-un : le démarrage montre sa progression (étapes numérotées, ligne qui bouge) et le message final liste
un compte de démo par rôle (``portable/launch.py``)."""
import io
from unittest import mock

from django.test import SimpleTestCase, TestCase

from collecte.management.commands import charger_demo
from parametres.test_lanceur_point_de_depart import module


class Console(io.StringIO):
    def isatty(self):
        return True


class ComptesDeDemo(SimpleTestCase):
    def setUp(self):
        self.m = module()

    def test_un_compte_par_role_de_la_vraie_demo(self):
        """Les comptes du message sont ceux que load_demo crée, avec son mot de passe : un par rôle."""
        attendus = [(ident, role) for ident, _prenom, _nom, role in charger_demo.COMPTES]
        self.assertEqual([nom for nom, _texte in self.m.DEMO_ACCOUNTS], [ident for ident, _role in attendus])
        self.assertEqual(len({role for _ident, role in attendus}), len(attendus))
        self.assertEqual(self.m.DEMO_PASSWORD, charger_demo.MOT_DE_PASSE)
        texte = self.m.demo_login()
        self.assertIn(charger_demo.MOT_DE_PASSE, texte)
        for ident, _role in attendus:
            self.assertIn(f" {ident} ", texte)

    def test_message_garde_au_premier_demarrage(self):
        self.assertEqual(self.m.login_text("demo"), self.m.demo_login())
        self.assertEqual(self.m.login_text("empty"), self.m.EMPTY_LOGIN)
        # démo préparée par le lanceur d'avant (texte complet gardé) : message d'aujourd'hui
        ancien = "Login: admin (also validateur, contributeur)\n  Password: demo-probant-2026"
        self.assertEqual(self.m.login_text(ancien), self.m.demo_login())
        # paquet d'une installation : son propre texte
        self.assertEqual(self.m.login_text("Login: marie"), "Login: marie")

    def test_message_final(self):
        prete = self.m.ready_message("http://127.0.0.1:8001/", "COMPTES", True)
        self.assertIn("ready: http://127.0.0.1:8001/", prete)
        self.assertIn("COMPTES", prete)
        self.assertIn("still starting", self.m.ready_message("http://127.0.0.1:8001/", "COMPTES", False))


class Progression(SimpleTestCase):
    def setUp(self):
        self.m = module()

    def test_sans_console_titre_et_fin_seulement(self):
        sortie = io.StringIO()
        with self.m.Step(2, 4, "Preparing the database", out=sortie) as etape:
            etape.update(0.5)
        texte = sortie.getvalue()
        self.assertIn("[2/4] Preparing the database", texte)
        self.assertIn("done (0:00)", texte)
        self.assertNotIn("\r", texte)

    def test_console_ligne_qui_bouge(self):
        sortie = Console()
        etape = self.m.Step(1, 3, "Loading", out=sortie)
        etape.update(0.5, "64/128")
        ligne = etape.line(1)
        self.assertIn("[############............]  50%", ligne)
        self.assertIn("64/128", ligne)
        self.assertLessEqual(len(ligne), 76)
        self.assertIn("working", self.m.Step(1, 3, "Loading", out=sortie).line(0))  # part inconnue : signe qui tourne
        with mock.patch.object(self.m.Step, "CREEP", 0.01):
            with etape:
                self.m.time.sleep(0.4)
        self.assertIn("\r", sortie.getvalue())
        self.assertIn("done", sortie.getvalue())

    def test_erreur_dans_une_etape(self):
        sortie = io.StringIO()
        with self.assertRaises(RuntimeError):
            with self.m.Step(1, 1, "Loading", out=sortie):
                raise RuntimeError("panne")
        self.assertIn("stopped", sortie.getvalue())

    def test_avance_vers_le_jalon_sans_l_atteindre(self):
        etape = self.m.Step(1, 1, "Demo", out=io.StringIO())
        etape.update(0.30, toward=0.36)
        with mock.patch.object(self.m.time, "monotonic", return_value=etape.since + 5 * self.m.Step.CREEP):
            self.assertGreater(etape.shown(), 0.35)
            self.assertLess(etape.shown(), 0.36)
        etape.update(0.50)
        self.assertEqual(etape.shown(), 0.50)

    def test_lignes_completes_seulement(self):
        vues = []
        flux = self.m.Lines(vues.append)
        flux.write("  Applying a.0001...")
        self.assertEqual(vues, [])
        flux.write(" OK\n  Applying a.0002... OK\nfin")
        self.assertEqual(vues, ["  Applying a.0001... OK", "  Applying a.0002... OK"])

    def test_migrations_comptees(self):
        def migrate_factice(nom, **options):
            for n in range(3):
                options["stdout"].write(f"  Applying a.000{n}...")
                options["stdout"].write(" OK\n")

        etape = self.m.Step(1, 1, "Database", out=io.StringIO())
        with mock.patch.object(self.m, "planned_migrations", return_value=4), \
                mock.patch("django.core.management.call_command", migrate_factice):
            self.m.migrate(etape)
        self.assertEqual((etape.share, etape.detail), (1.0, "3/4"))

    def test_jalons_de_la_demo(self):
        parts = []

        def demo_factice(nom, **options):
            for n in range(len(self.m.DEMO_MILESTONES) + 2):  # lignes en trop : la barre reste bornée
                options["stdout"].write(f"line {n}\n")
                parts.append(etape.share)

        etape = self.m.Step(1, 1, "Demo", out=io.StringIO())
        with mock.patch("django.core.management.call_command", demo_factice):
            self.m.load_demo(etape)
        self.assertEqual(parts[:len(self.m.DEMO_MILESTONES)], self.m.DEMO_MILESTONES)
        self.assertEqual(parts, sorted(parts))
        self.assertEqual(etape.share, 1.0)



class MigrationsPrevues(TestCase):
    databases = "__all__"

    def test_base_a_jour_aucune_migration(self):
        """Base des tests, déjà migrée : rien à appliquer (le compte lit la base principale et le registre commun)."""
        self.assertEqual(module().planned_migrations(), 0)
