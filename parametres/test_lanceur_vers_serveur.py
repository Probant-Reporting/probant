"""Du PC au serveur (docs/from_pc_to_server.md), joué de bout en bout dans des processus séparés, comme en vrai :

1. « PC » : la version tout-en-un, préparée par le lanceur lui-même (``portable/launch.py``, premier démarrage « outil
   vide », DJANGO_DEBUG=1, sa propre clé secrète dans data/.secret_key_all_in_one) ; de vraies données : comptes avec leur mot de passe, une
   valeur saisie, une preuve jointe, un logo ; une sauvegarde faite comme le bouton de Paramètres › Hébergement.
2. Fenêtre fermée, le dossier ``data`` recopié tel quel sur le « serveur » (réglages de production, autre clé secrète,
   créée au premier ``startup``) : mêmes mots de passe, valeur, preuve et logo retrouvés, /sante/ verte. La sauvegarde
   du PC, signée avec le secret du PC, est refusée par la page Hébergement du serveur (« restore --unsigned » pour l'IT).
3. Vers un autre serveur (chemin de PostgreSQL, joué ici en SQLite) : sauvegarde JSON et archive du registre faites sur
   le serveur, restaurées sur un serveur neuf (« restore --shared », puis « restore --unsigned ») : mêmes mots de passe.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from django.test import SimpleTestCase

from .aides_tests.hebergement import RACINE, environnement_propre

MDP_ADMIN = "Mot-de-passe-du-PC-2026"
MDP_SAM = "Mot-de-passe-de-Sam-2026"
PDF = b"%PDF-1.4 facture d'electricite"
# PNG de 1 x 1 pixel
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")

PREPARER_COMME_LE_LANCEUR = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("launch", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.organise()
import django
django.setup()
print(m.prepare(m.package(), "empty", m.Steps(3)))
"""

SAISIR_SUR_LE_PC = f"""
import datetime, json
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from collecte import saisie as S
from collecte.models import Campagne
from parametres import sauvegardes as SV
from parametres.models import Instance
from parametres.referentiel import unite_depuis_symbole as U
from referentiel.models import KPI, Niveau, Organisation, Utilisateur
i = Instance.courante()
i.nom, i.mise_en_place_terminee = "Atelier", True
i.logo.save("logo.png", ContentFile({PNG!r}), save=False)
i.save()
alex = Utilisateur.objects.create_user("alex", email="alex@exemple.test", password={MDP_ADMIN!r}, role="admin")
Utilisateur.objects.create_user("sam", email="sam@exemple.test", password={MDP_SAM!r})
g = Organisation.objects.create(nom="Atelier", niveau_id=Niveau.GROUP)
p = Organisation.objects.create(nom="France", niveau_id=Niveau.COUNTRY, parent=g)
e = Organisation.objects.create(nom="Lyon", niveau_id=Niveau.ENTITY, parent=p)
c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE,
                            date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
k = KPI.objects.create(code="ELEC", libelle="Electricite", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                       methode_agregation="Somme", unite=U("ETP"))
S.enregistrer(alex, c, k, e, "123456", False, "")
preuve = S.ajouter_preuve(alex, c, k, e, ContentFile({PDF!r}, name="facture.pdf"))
archive = SV.creer("manuelle")  # bouton « Créer et télécharger une sauvegarde »
print(json.dumps({{"cellule": f"/saisie/{{c.pk}}/ELEC/{{e.pk}}/", "preuve": preuve.pk, "archive": archive.nom,
                  "secret": settings.SECRET_KEY}}))
"""

VERIFIER_SUR_LE_SERVEUR = f"""
import json, sys
from django.conf import settings
from django.test import Client
from collecte.models import Preuve, Reponse
from parametres import sauvegardes as SV
from parametres.models import Instance
d = json.loads(sys.argv[1])
r = {{"secret": settings.SECRET_KEY}}
for nom, mdp in (("sam@exemple.test", {MDP_SAM!r}), ("alex@exemple.test", {MDP_ADMIN!r})):
    c = Client(HTTP_HOST="localhost")
    rep = c.post("/connexion/", {{"username": nom, "password": mdp}})
    r["connexion " + nom] = rep.status_code == 302 and "_auth_user_id" in c.session
r["cellule"] = c.get(d["cellule"]).status_code
rep = c.get(f"/preuve/{{d['preuve']}}/")
r["preuve"] = [rep.status_code, b"".join(rep.streaming_content if rep.streaming else [rep.content])[:8].decode()]
r["valeur"] = str(Reponse.objects.get(kpi_id="ELEC", organisation__nom="Lyon").valeur.normalize())
i = Instance.courante()
r["logo"] = i.logo_disponible
sante = Client(HTTP_HOST="localhost").get("/sante/")
r["sante"] = [sante.status_code, sante.json().get("etat")]
if d.get("archive"):
    r["archive du PC signee ici"] = SV.signature_valide(SV.dossier() / d["archive"])
print(json.dumps(r))
"""


class DuPcAuServeurTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def lancer(self, env, *args, entree=None):
        r = subprocess.run([sys.executable, *args], cwd=RACINE, env={**environnement_propre(), **env}, input=entree,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-3000:])
        return r.stdout

    def shell(self, env, code, *args):
        """``code`` exécuté avec les réglages de ``env`` (comme « manage.py shell ») ; renvoie le JSON de sa dernière ligne."""
        sortie = self.lancer(env, "-c", "import os, sys, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE', "
                             "'config.settings'); django.setup()\n" + code, *args)
        return json.loads(sortie.strip().splitlines()[-1])

    def manage(self, env, *args):
        return self.lancer(env, "manage.py", *args)

    def verifier(self, env, d):
        r = self.shell(env, VERIFIER_SUR_LE_SERVEUR, json.dumps(d))
        self.assertTrue(r["connexion sam@exemple.test"], r)
        self.assertTrue(r["connexion alex@exemple.test"], r)
        self.assertEqual(r["cellule"], 200, r)
        self.assertEqual(r["preuve"], [200, "%PDF-1.4"], r)
        self.assertEqual(r["valeur"], "123456", r)
        self.assertTrue(r["logo"], r)
        self.assertEqual(r["sante"], [200, "ok"], r)
        return r

    @unittest.skipUnless(os.name == "posix", "lien symbolique vers le code, comme dans le paquet (system/app)")
    def test_du_pc_au_serveur_puis_vers_un_autre_serveur(self):
        # 1. le PC, préparé par le lanceur (paquet : system/launch.py, system/app = le code, data/)
        systeme = self.tmp / "pc" / "system"
        systeme.mkdir(parents=True)
        shutil.copy(RACINE / "portable" / "launch.py", systeme / "launch.py")
        (systeme / "app").symlink_to(RACINE, target_is_directory=True)
        pc = {"DATA_DIR": str(self.tmp / "pc" / "data"), "DJANGO_DEBUG": "1", "PROBANT_ALL_IN_ONE": "1",
              "PYTHONUTF8": "1"}  # comme le lanceur
        self.lancer({}, "-c", PREPARER_COMME_LE_LANCEUR, str(systeme / "launch.py"))
        self.assertFalse((self.tmp / "pc" / "data" / ".secret_key").exists())  # pas le nom de la clé d'un serveur
        cle_du_pc = (self.tmp / "pc" / "data" / ".secret_key_all_in_one").read_text().strip()  # sa clé à lui
        d = self.shell(pc, SAISIR_SUR_LE_PC)
        self.assertEqual(d["secret"], cle_du_pc)
        self.assertNotEqual(d["secret"], "dev-only-change-me")

        # 2. fenêtre fermée ; le dossier « data » recopié tel quel sur le serveur (réglages de production)
        serveur = {"DATA_DIR": str(self.tmp / "serveur" / "data")}
        shutil.copytree(self.tmp / "pc" / "data", self.tmp / "serveur" / "data")
        self.assertIn('installation "Atelier", 2 account(s)', self.manage(serveur, "startup"))
        r = self.verifier(serveur, d)
        self.assertNotEqual(r["secret"], d["secret"])  # deux secrets différents : le serveur ne prend pas la clé du PC
        self.assertTrue((self.tmp / "serveur" / "data" / ".secret_key").exists())
        self.assertEqual((self.tmp / "serveur" / "data" / ".secret_key").read_text().strip(), r["secret"])
        self.assertFalse(r["archive du PC signee ici"])  # la page Hébergement du serveur la refuse

        # 3. vers un autre serveur (chemin de PostgreSQL) : sauvegarde JSON et archive du registre, restaurées ailleurs
        self.manage(serveur, "backup", "--json", "--reason", "move")
        self.shell(serveur, "from parametres import sauvegardes as SV; import json; "
                            "print(json.dumps(str(SV.creer_registre('move'))))")
        neuf = {"DATA_DIR": str(self.tmp / "neuf" / "data")}
        (self.tmp / "neuf" / "data").mkdir(parents=True)
        self.manage(neuf, "startup")  # le premier démarrage d'un serveur neuf : base vide, assistant de mise en place
        sauvegardes = self.tmp / "serveur" / "data" / "backups"
        registre = next((sauvegardes / "shared").glob("registry-*-move.zip"))
        archive = next(sauvegardes.glob("backup-*-move.zip"))
        self.manage(neuf, "restore", "--shared", str(registre), "--yes")
        self.manage(neuf, "restore", str(archive), "--unsigned", "--yes")
        self.verifier(neuf, {**d, "archive": ""})
