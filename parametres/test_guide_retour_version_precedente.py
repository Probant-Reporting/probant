"""Guide d'installation, « Going back to the previous version » : une procédure générique (restaurer l'archive faite
avant la mise à jour, avec l'image de la version précédente, ``restore --rebuild`` sous PostgreSQL), la même en anglais
et en français, sans nom de migration de l'histoire du projet. L'outil sait toujours restaurer d'anciennes archives
(``--unsigned``, ``qa.migration_rehearsal.cibles_retour`` : voir ``parametres/test_cibles_retour.py``)."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

RACINE = Path(settings.BASE_DIR)
GUIDES = ("docs/installation.md", "docs/fr/installation.md")


def section_retour(guide):
    texte = (RACINE / guide).read_text(encoding="utf-8")
    titre = "### Revenir à la version précédente" if "/fr/" in guide else "### Going back to the previous version"
    debut = texte.index(titre)
    fin = texte.index("\n## ", debut)
    return texte[debut:fin]


class GuideRetourVersionPrecedenteTests(SimpleTestCase):
    def test_la_procedure_generique_est_dans_les_deux_guides(self):
        for guide in GUIDES:
            with self.subTest(guide=guide):
                s = section_retour(guide)
                for attendu in ("before-update", "backup --list", "restore <", "--rebuild", "--unsigned",
                                "docker compose stop web", "docker compose up -d"):
                    self.assertIn(attendu, s)

    def test_aucun_nom_de_migration_de_l_histoire_du_projet(self):
        for guide in GUIDES:
            with self.subTest(guide=guide):
                s = section_retour(guide)
                self.assertNotRegex(s, r"\b\d{4}_[a-z_]+\b")
                self.assertNotIn("DELETE FROM django_migrations", s)
                self.assertNotIn("manage.py migrate", s)

    def test_les_commandes_sont_les_memes_en_anglais_et_en_francais(self):
        cmds = [re.findall(r"`(docker compose [^`]+)`", section_retour(g)) for g in GUIDES]
        norm = [[re.sub(r"<[^>]+>", "<x>", c) for c in lst] for lst in cmds]
        self.assertEqual(norm[0], norm[1])
