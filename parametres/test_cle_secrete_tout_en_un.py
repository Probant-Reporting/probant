"""Version tout-en-un : sa propre clé secrète, créée au premier démarrage dans son dossier des données
(``.secret_key_all_in_one``, droits 600), au lieu de la clé fixe du mode développement, connue de tous
(``config.settings._cle_secrete``, ``portable/launch.py``). Le mode développement garde sa clé fixe. Un dossier existant,
créé avec la clé fixe, s'ouvre toujours : sessions à refaire une fois, sauvegardes d'avant refusées par la page avec un
message qui le dit (restaurables en ligne de commande avec --unsigned), « Reset » qui remet quand même le point de
départ du paquet."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from .aides_tests.hebergement import RACINE, environnement_propre

LIRE = ("import json, os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); django.setup(); "
        "from django.conf import settings as s; print(json.dumps({'cle': s.SECRET_KEY, 'debug': s.DEBUG}))")

AVANT = """
import json, os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.core.management import call_command
from parametres import sauvegardes as SV
from referentiel.models import Utilisateur
call_command("migrate", interactive=False, verbosity=0)
u = Utilisateur.objects.create_user("alex", email="alex@exemple.test", password="Mot-de-passe-2026", role="admin")
s = SessionStore()
s[SESSION_KEY] = str(u.pk)
s.create()
SV.creer("initial")
print(json.dumps({"cle": settings.SECRET_KEY, "session": s.session_key}))
"""

APRES = """
import json, os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.core.management import call_command
from parametres import sauvegardes as SV
from referentiel.models import Utilisateur
call_command("migrate", interactive=False, verbosity=0)
d = json.loads(sys.argv[1])
archive = sorted(SV.dossier().glob("backup-*-initial.zip"))[0]
try:
    SV.controler_signature(archive)
    refus = ""
except SV.ErreurSauvegarde as e:
    refus = str(e)
print(json.dumps({"cle": settings.SECRET_KEY, "session": SessionStore(d["session"]).get(SESSION_KEY),
                  "mot_de_passe": Utilisateur.objects.get(username="alex").check_password("Mot-de-passe-2026"),
                  "signee": SV.signature_valide(archive), "refus": refus}))
"""

RESET = """
import builtins, importlib.util, sys
spec = importlib.util.spec_from_file_location("launch", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
builtins.input = lambda question="": "YES"
m.reset(m.package())
"""


class CleSecreteToutEnUnTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.data = self.tmp / "data"
        self.data.mkdir()

    def lancer(self, env, *args):
        base = {**environnement_propre(), "LANGUAGE": "fr", "DEFAULT_LANGUAGE": "fr"}
        r = subprocess.run([sys.executable, *args], cwd=RACINE, env={**base, **env}, capture_output=True, text=True,
                           timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-3000:])
        return r

    def json(self, env, *args):
        return json.loads(self.lancer(env, *args).stdout.strip().splitlines()[-1])

    def env(self, tout_en_un=True):
        e = {"DATA_DIR": str(self.data), "DJANGO_DEBUG": "1"}
        return {**e, "PROBANT_ALL_IN_ONE": "1"} if tout_en_un else e

    def test_sa_propre_cle_creee_une_fois_gardee_en_600(self):
        r1 = self.json(self.env(), "-c", LIRE)
        self.assertTrue(r1["debug"])  # le serveur local reste en mode développement (HTTP, fichiers statiques)
        self.assertNotEqual(r1["cle"], "dev-only-change-me")
        self.assertGreaterEqual(len(r1["cle"]), 50)
        fichier = self.data / ".secret_key_all_in_one"
        self.assertEqual(fichier.read_text().strip(), r1["cle"])
        self.assertEqual(oct(fichier.stat().st_mode & 0o777), "0o600")
        self.assertFalse((self.data / ".secret_key").exists())  # pas le nom qu'un serveur lit
        self.assertEqual(self.json(self.env(), "-c", LIRE)["cle"], r1["cle"])  # gardée d'un démarrage à l'autre

    def test_mode_developpement_inchange(self):
        r = self.json(self.env(tout_en_un=False), "-c", LIRE)
        self.assertEqual(r["cle"], "dev-only-change-me")
        self.assertEqual(sorted(p.name for p in self.data.iterdir()), [])

    def test_le_lanceur_demande_sa_propre_cle(self):
        systeme = self.tmp / "system"
        systeme.mkdir()
        shutil.copy(RACINE / "portable" / "launch.py", systeme / "launch.py")
        code = ("import importlib.util, json, os, sys; spec = importlib.util.spec_from_file_location('l', sys.argv[1]); "
                "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
                "print(json.dumps({k: os.environ.get(k) for k in ('PROBANT_ALL_IN_ONE', 'DJANGO_DEBUG', 'DJANGO_SECRET_KEY')}))")
        r = self.json({"DJANGO_SECRET_KEY": "cle-du-poste"}, "-c", code, str(systeme / "launch.py"))
        self.assertEqual(r, {"PROBANT_ALL_IN_ONE": "1", "DJANGO_DEBUG": "1", "DJANGO_SECRET_KEY": None})

    def test_dossier_existant_cree_avec_la_cle_fixe(self):
        avant = self.json(self.env(tout_en_un=False), "-c", AVANT)
        self.assertEqual(avant["cle"], "dev-only-change-me")
        apres = self.json(self.env(), "-c", APRES, json.dumps(avant))
        self.assertNotEqual(apres["cle"], avant["cle"])
        self.assertTrue(apres["mot_de_passe"])  # les comptes et leurs mots de passe sont là : il s'ouvre
        self.assertIsNone(apres["session"])  # session d'avant illisible : se reconnecter une fois
        self.assertFalse(apres["signee"])  # signée avec une clé connue de tous : ne prouve plus rien
        self.assertIn("avant que cette copie de l'outil ait sa propre clé secrète", apres["refus"])
        # « Reset » remet le point de départ du paquet, même signé avec l'ancienne clé
        systeme = self.tmp / "system"
        systeme.mkdir()
        shutil.copy(RACINE / "portable" / "launch.py", systeme / "launch.py")
        (systeme / "app").symlink_to(RACINE, target_is_directory=True)
        sortie = self.lancer({}, "-c", RESET, str(systeme / "launch.py")).stdout
        self.assertIn("restored all the same", sortie)
        self.assertIn("Done: back to the starting point.", sortie)

    def test_paquet_sans_cle(self):
        spec = importlib.util.spec_from_file_location("bp_essai", RACINE / "portable" / "build_package.py")
        bp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bp)
        self.assertIn(".secret_key_all_in_one", bp.SECRETS_DONNEES)
        self.assertIn(".secret_key", bp.SECRETS_DONNEES)
        self.assertEqual(os.environ.get("PROBANT_ALL_IN_ONE"), None)  # l'environnement du test n'a pas changé
