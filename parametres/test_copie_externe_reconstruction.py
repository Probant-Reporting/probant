"""Reconstruction complète d'une installation à DEUX espaces à partir de la SEULE copie externe, sur un serveur neuf
(dossier des données vide, autre clé secrète), avec les commandes existantes : c'est la raison d'être de la copie de
l'archive du registre commun.

Serveur A : deux espaces, un compte avec son mot de passe, une organisation témoin, une destination S3 (faux stockage
local qui vérifie les signatures) ; sauvegardes, puis passage de la copie externe. Serveur B : installation vide ; le
dossier de l'installation est recopié tel quel depuis la destination dans ``backups/`` ; puis, dans cet ordre :
``restore --shared`` (registre), ``restore --unsigned`` (espace principal), ``SPACE=achats restore --unsigned``. Tout
revient : espaces, comptes et mots de passe, données des deux espaces, réglage de la copie (secret « à saisir de
nouveau » : autre clé secrète). Chaque commande réussit, sans erreur (avant : la restauration du registre s'arrêtait sur
la base pas encore créée du second espace)."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from parametres.aides_tests.faux_s3 import ID, SECRET, FauxS3
from parametres.aides_tests.serveurs_tls import RACINE, environnement

PREPARER_A = r"""
import json, os, django
django.setup()
from espaces import contexte as E, comptes as EC
from espaces.creation import creer
from espaces.models import Compte
from referentiel.models import Utilisateur
from parametres import sauvegardes as SV, copie_externe as CE
admin = Utilisateur(username="admin", email="admin@exemple.test", role="admin", is_superuser=True, is_staff=True)
admin.set_password("Mdp-Serveur-A-2026")
admin.save()
EC.reconcilier()
creer("Achats", "achats", Compte.objects.get(username="admin"))
with E.activer("achats"):
    Utilisateur.objects.create(username="acheteur", email="acheteur@exemple.test", role="contributeur")
EC.reconcilier()
SV.creer("essai")
with E.activer("achats"):
    SV.creer("essai")
CE.enregistrer(None, "s3", {"adresse": os.environ["ADRESSE"], "region": "", "compartiment": "sauvegardes", "style": "path",
                            "identifiant": os.environ["ID"], "chemin": "copies", "conserver": 0}, secret=os.environ["SECRET"])
SV.creer_registre("essai")
print("RESULTAT " + json.dumps({"copiees": CE.passage(), "ident": EC.installation().identifiant,
                                "comptes": Utilisateur.objects.count()}))
"""
VERIFIER_B = r"""
import json, django
django.setup()
from django.contrib.auth import authenticate
from espaces import contexte as E
from espaces.models import Espace
from referentiel.models import Utilisateur
from parametres import copie_externe as CE
with E.activer("achats"):
    achats = sorted(Utilisateur.objects.values_list("username", flat=True))
print("RESULTAT " + json.dumps({"espaces": sorted(Espace.objects.values_list("code", flat=True)),
                                "admin": authenticate(username="admin", password="Mdp-Serveur-A-2026") is not None,
                                "achats": achats, "copie": [CE.reglage().genre, list(CE.reglage().manques)]}))
"""


def resultat(r):
    lignes = [x for x in r.stdout.splitlines() if x.startswith("RESULTAT ")]
    assert lignes, r.stdout + r.stderr
    return json.loads(lignes[-1][len("RESULTAT "):])


class ReconstructionTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="reconstruction-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.faux = FauxS3()
        self.addCleanup(self.faux.fermer)

    def env(self, nom, **autres):
        (self.tmp / nom).mkdir(exist_ok=True)
        return environnement(DATA_DIR=self.tmp / nom, DJANGO_SECRET_KEY=f"cle-secrete-du-serveur-{nom}-0123456789abcdef",
                             DJANGO_DEBUG="1", ADRESSE=self.faux.adresse, ID=ID, SECRET=SECRET, NO_PROXY="*", no_proxy="*",
                             **autres)

    def commande(self, env, *args, attendu=0):
        r = subprocess.run([sys.executable, "manage.py", *args], cwd=RACINE, env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, attendu, f"{args}\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
        self.assertNotIn("Traceback", r.stderr, args)
        return r

    def test_deux_espaces_depuis_la_seule_copie_externe(self):
        a = self.env("a")
        self.commande(a, "migrate", "--noinput", "-v", "0")
        r = subprocess.run([sys.executable, "-c", PREPARER_A], cwd=RACINE, env=a, capture_output=True, text=True, timeout=300)
        etat_a = resultat(r)
        self.assertEqual(etat_a["copiees"], 3, r.stderr[-2000:])  # espace principal, achats, registre
        base = f"copies/{etat_a['ident']}/"
        # serveur B neuf : le dossier de l'installation, recopié tel quel depuis la destination
        b = self.env("b")
        self.commande(b, "migrate", "--noinput", "-v", "0")
        sauvegardes = self.tmp / "b" / "backups"
        noms = {}
        for cle, objet in self.faux.objets.items():
            self.assertTrue(cle.startswith(base), cle)
            rel = cle[len(base):]
            (sauvegardes / rel).parent.mkdir(parents=True, exist_ok=True)
            (sauvegardes / rel).write_bytes(objet.contenu)
            noms[rel.rsplit("/", 1)[0] if "/" in rel else ""] = rel.rsplit("/", 1)[-1]
        self.assertEqual(set(noms), {"", "shared", "spaces/achats"})
        self.commande(b, "restore", "--shared", noms["shared"], "--yes")
        self.commande(b, "restore", noms[""], "--yes", attendu=1)  # signée par A : refusée sans --unsigned
        self.commande(b, "restore", "--unsigned", noms[""], "--yes")
        self.commande({**b, "SPACE": "achats"}, "restore", "--unsigned", noms["spaces/achats"], "--yes")
        r = subprocess.run([sys.executable, "-c", VERIFIER_B], cwd=RACINE, env=b, capture_output=True, text=True, timeout=300)
        self.assertEqual(resultat(r), {"espaces": ["achats", "principal"], "admin": True, "achats": ["acheteur", "admin"],
                                       "copie": ["s3", ["secret_illisible"]]})
