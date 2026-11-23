"""Lien d'aide « ? » (collecte/aide.py, ``lien_aide``) : pour chaque page du menu et chacun des cinq rôles, la section du guide
qui décrit la page. ``None`` : le guide du rôle n'a pas de section pour cette page, le lien mène au
début du guide (jamais à une section d'une autre tâche)."""
from django.test import TestCase
from django.urls import reverse

from referentiel.models import Utilisateur

from . import aide as AI

ROLES = ("admin", "validateur", "contributeur", "lecteur", "auditeur")
# page → section de chaque rôle, dans l'ordre de ROLES
ATTENDU = {
    "saisie": ("entry", "review", "enter", None, "read-only"),
    "cellule": ("reopen", "review", "enter", None, "read-only"),
    "pour_moi": (None, "scope", "find", None, None),
    "tableau_de_bord": ("reminders", "dashboard", None, "dashboard", "dashboard"),
    "consolidation": ("consolidation", "dashboard", None, "consolidation", "dashboard"),
    "relances": ("reminders", "reminders", None, None, None),
    "coherence": ("consistency", "alerts", "check", None, "consistency"),
    "alerte": ("consistency", "alerts", "check", None, "consistency"),
    "historique": ("history", None, None, None, "history"),
    "echanges": ("large-exports", "import", "import", None, "large-exports"),
    "echanges_exporter": ("large-exports", "import", "import", None, "large-exports"),
    "echanges_importer": ("import-values", "import", "import", None, None),
    "visualisation": ("visualisation", None, "visualisation", "visualisation", "dashboard"),
    "mon_compte": ("account", "language", "account", "account", "language"),
}


class LienAideSectionsTests(TestCase):
    def setUp(self):
        self.u = {r: Utilisateur.objects.create(username=r, email=f"{r}@exemple.test", role=r) for r in ROLES}

    def test_section_de_chaque_page_pour_chaque_role(self):
        base = reverse("collecte:aide")
        for page, sections in ATTENDU.items():
            for role, section in zip(ROLES, sections):
                for langue in AI.LANGUES_GUIDES:
                    with self.subTest(page=page, role=role, langue=langue):
                        self.assertEqual(AI.lien_aide(self.u[role], page, langue), base + (f"#{section}" if section else ""))

    def test_un_role_n_arrive_jamais_sur_une_tache_d_une_autre_page(self):
        """« Rouvrir une saisie validée » décrit une action sur une saisie, pas la page Saisie ni Pour moi."""
        for page in ("saisie", "pour_moi"):
            self.assertNotIn("#reopen", AI.lien_aide(self.u["admin"], page, "en"))
