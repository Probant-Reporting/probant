"""Fuseau horaire réglable (variable TIME_ZONE, défaut Europe/Brussels) : heure des relances, de la sauvegarde et du contrôle
de nuit, « aujourd'hui », dates des exports. Une valeur inconnue arrête le démarrage avec un message clair."""
import shutil
import subprocess
import sys
import tempfile

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from referentiel.models import Utilisateur

from .aides_tests.hebergement import RACINE, environnement_propre, reglages

CODE = ("from django.utils import timezone; t = timezone.localtime(); "
        "print(json.dumps([s.TIME_ZONE, t.tzname() in ('CET', 'CEST', 'EST', 'EDT', 'JST'), t.utcoffset().total_seconds() / 3600]))")


class FuseauHoraireReglages(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_defaut_inchange(self):
        zone, connue, decalage = reglages({"DATA_DIR": self.tmp}, CODE)
        self.assertEqual(zone, "Europe/Brussels")
        self.assertTrue(connue)
        self.assertIn(decalage, (1.0, 2.0))
        self.assertEqual(reglages({"DATA_DIR": self.tmp, "TIME_ZONE": ""}, CODE)[0], "Europe/Brussels")  # vide : défaut

    def test_variable_suivie(self):
        self.assertEqual(reglages({"DATA_DIR": self.tmp, "TIME_ZONE": "Asia/Tokyo"}, CODE), ["Asia/Tokyo", True, 9.0])
        zone, _, decalage = reglages({"DATA_DIR": self.tmp, "TIME_ZONE": " America/New_York "}, CODE)
        self.assertEqual(zone, "America/New_York")
        self.assertIn(decalage, (-5.0, -4.0))

    def test_valeur_inconnue_arrete_le_demarrage(self):
        for valeur in ("Mars/Olympus", "Europe/Bruxelles", "../etc/passwd"):
            with self.subTest(valeur=valeur):
                r = subprocess.run([sys.executable, "manage.py", "check"], cwd=RACINE, capture_output=True, text=True, timeout=60,
                                   env={**environnement_propre(), "DATA_DIR": self.tmp, "TIME_ZONE": valeur})
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("ImproperlyConfigured", r.stderr)
                self.assertIn(f"TIME_ZONE={valeur!r} is not a known time zone", r.stderr)


class FuseauHorairePageHebergement(TestCase):
    def test_fuseau_affiche_avec_l_heure_du_serveur(self):
        admin = Utilisateur.objects.create_user("admin", email="admin@exemple.test", password="x", role=Utilisateur.Role.ADMIN)
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse("parametres:hebergement")), f"({settings.TIME_ZONE})")
