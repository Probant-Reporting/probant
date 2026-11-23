"""Test statique : dans le code de l'outil, aucune transaction ni connexion qui viserait la base de l'espace principal
quel que soit l'espace courant (sous PostgreSQL, la garde ne voit pas un ``transaction.atomic()`` sans base), aucun
dossier de fichiers figé, aucune écriture de comptes qui contournerait le registre commun."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

RACINE = Path(settings.BASE_DIR)
DOSSIERS = ["collecte", "parametres", "referentiel", "config"]

REGLES = [
    (re.compile(r"transaction\.atomic\((?![^)]*using)"), "transaction.atomic() sans base : ESP.atomic()"),
    (re.compile(r"@transaction\.atomic\b"), "@transaction.atomic : @ESP.atomic"),
    (re.compile(r"transaction\.(set_rollback|on_commit|savepoint\w*|get_connection)\((?![^)]*using)"),
     "transaction.… sans base : using=ESP.alias_courant()"),
    (re.compile(r"from django\.db import ([^\n]*\b)?connection\b(?!s)"), "connection nue : ESP.connexion()"),
    (re.compile(r"settings\.(MEDIA_ROOT|SAUVEGARDES_DIR)"), "dossier figé : ESP.dossier_medias() / dossier_sauvegardes()"),
    (re.compile(r"Utilisateur\.(objects|_default_manager)[^\n]*\.(update|bulk_create|bulk_update)\("),
     "écriture de comptes hors du registre (pas de signal) : enregistrer chaque compte"),
    (re.compile(r"DATABASES\[\"default\"\]"), "configuration de la base principale : ESP.connexion().settings_dict"),
    (re.compile(r"call_command\(\"(flush|loaddata|dumpdata)\"(?![^\n]*database)"), "commande sans base : database=ESP.alias_courant()"),
]
# exceptions motivées : (fichier, numéro de la règle dans REGLES)
EXCEPTIONS = {
    ("config/settings.py", 4), ("config/settings.py", 6),  # les réglages eux-mêmes
    ("parametres/management/commands/demarrage.py", 4),  # dossiers de l'installation créés au démarrage (voulu)
    ("collecte/aides_tests/vitesse.py", 3),  # aide de test : compte les requêtes de la connexion de l'espace principal
    ("referentiel/auth.py", 5),  # nouvelle empreinte du mot de passe : registre d'abord, puis copies (connexion)
}


class StatiqueTests(SimpleTestCase):
    def test_code_de_l_outil(self):
        fautes = []
        for d in DOSSIERS:
            for f in sorted((RACINE / d).rglob("*.py")):
                rel = f.relative_to(RACINE).as_posix()
                if "/migrations/" in rel or f.name.startswith("test_") or f.name == "tests.py":
                    continue
                texte = f.read_text(encoding="utf-8")
                for n, (motif, explication) in enumerate(REGLES):
                    if (rel, n) in EXCEPTIONS:
                        continue
                    for m in motif.finditer(texte):
                        ligne = texte.count("\n", 0, m.start()) + 1
                        fautes.append(f"{rel}:{ligne} : {explication}")
        self.assertEqual(fautes, [])

    def test_les_regles_reconnaissent_les_fautes(self):
        exemples = ["with transaction.atomic():", "@transaction.atomic", "from django.db import connection",
                    "from django.db import models, connection", "x = settings.MEDIA_ROOT", "transaction.set_rollback(True)",
                    "Utilisateur.objects.filter(pk=1).update(password='x')", 'settings.DATABASES["default"]',
                    'call_command("flush", interactive=False)']
        for e in exemples:
            self.assertTrue(any(m.search(e) for m, _ in REGLES), e)
        for bon in ["with ESP.atomic():", "transaction.atomic(using=ESP.COMMUN)", "from django.db import connections",
                    "transaction.set_rollback(True, using=ESP.alias_courant())"]:
            self.assertFalse(any(m.search(bon) for m, _ in REGLES), bon)
