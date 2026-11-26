"""Historique (Administration › Historique) : toute action que le code écrit au journal appartient à une famille de
``administration.FAMILLES``. Une action hors des familles est en base mais n'apparaît dans aucun onglet de la page (et
fausse le compteur de l'onglet « modifications d'administration », calculé par différence).

Le test lit le code (arbre syntaxique, sans l'exécuter) : chaque ``Journal.ecrire(…, action, …)``, ``Journal(action=…)``
et ``Journal.objects.create(action=…)``. Une action écrite d'après une variable doit être résolue : constante du module,
expression conditionnelle de deux textes, ou l'un des appels variables connus (``VARIABLES``, valeurs lues dans le code
qui les définit). Un nouvel appel variable fait échouer le test : l'ajouter à ``VARIABLES`` avec ses valeurs."""
import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from parametres.libelles import libelle

from . import administration as A
from . import coherence as CO
from . import saisie as S

RACINE = Path(settings.BASE_DIR)
VARIABLES = {  # (fichier, texte de l'argument) : actions possibles
    ("collecte/administration.py", "action"): set(A.TRANSITIONS),
    ("collecte/coherence.py", "f'alerte_{action}'"): {f"alerte_{a}" for a in CO.TRANSITIONS},
    ("collecte/saisie.py", "action_don"): {d for d, _ in S.ACTIONS_JOURNAL_ATTRIBUTION.values()},
    ("collecte/saisie.py", "action_retrait"): {r for _, r in S.ACTIONS_JOURNAL_ATTRIBUTION.values()},
}


def _textes(noeud, constantes):
    if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
        return {noeud.value}
    if isinstance(noeud, ast.IfExp):
        a, b = _textes(noeud.body, constantes), _textes(noeud.orelse, constantes)
        return None if a is None or b is None else a | b
    if isinstance(noeud, ast.Name) and noeud.id in constantes:
        return {constantes[noeud.id]}
    return None


def _est_journal(n):
    return isinstance(n, ast.Name) and n.id == "Journal"


def actions_du_code():
    """({action: [fichier:ligne]}, [(fichier, argument) non résolus])."""
    trouvees, inconnues = {}, []
    for p in sorted(RACINE.rglob("*.py")):
        rel = p.relative_to(RACINE).as_posix()
        if rel.startswith(("qa/", "publication/", "docs/", "portable/")) or "/migrations/" in rel \
                or "/aides_tests/" in rel or Path(rel).name.startswith("test_") or "/node_modules/" in rel:
            continue
        arbre = ast.parse(p.read_text(encoding="utf-8"))
        constantes = {n.targets[0].id: n.value.value for n in arbre.body
                      if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                      and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)}
        for n in ast.walk(arbre):
            if not isinstance(n, ast.Call):
                continue
            f, cible = n.func, None
            if isinstance(f, ast.Attribute) and f.attr == "ecrire" and _est_journal(f.value):
                cible = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "action"), None)
            elif _est_journal(f) or (isinstance(f, ast.Attribute) and f.attr in ("create", "get_or_create")
                                     and isinstance(f.value, ast.Attribute) and f.value.attr == "objects" and _est_journal(f.value.value)):
                cible = next((k.value for k in n.keywords if k.arg == "action"), None)
            if cible is None:
                continue
            valeurs = _textes(cible, constantes)
            if valeurs is None:
                cle = (rel, ast.unparse(cible))
                if cle not in VARIABLES:
                    inconnues.append(cle)
                    continue
                valeurs = VARIABLES[cle]
            for a in valeurs:
                trouvees.setdefault(a, []).append(f"{rel}:{n.lineno}")
    return trouvees, inconnues


class FamillesTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.trouvees, cls.inconnues = actions_du_code()

    def test_le_balayage_trouve_les_actions_connues(self):
        for a in ("reglage_emails", "reglage_connexion_entreprise", "reglage_alertes", "reglage_mise_a_jour_auto",
                  "attribution_validateur", "alerte_justifier", "cloturer", "appel_mcp"):
            self.assertIn(a, self.trouvees, a)

    def test_aucun_appel_variable_inconnu(self):
        self.assertEqual(self.inconnues, [])

    def test_chaque_action_du_code_dans_une_famille(self):
        connues = {a for _, _, acts in A.FAMILLES for a in acts}
        absentes = {a: lieux for a, lieux in self.trouvees.items() if a not in connues}
        self.assertEqual(absentes, {})

    def test_chaque_famille_et_chaque_action_ont_un_libelle(self):
        for code, cle, acts in A.FAMILLES:
            self.assertNotEqual(libelle(cle), cle, code)
        for a in self.trouvees:
            self.assertNotEqual(libelle(f"admin.journal.action.{a}"), f"admin.journal.action.{a}", a)
