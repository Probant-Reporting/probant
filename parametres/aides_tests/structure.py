"""Aides des tests qui parcourent le code : liste des fichiers Python du dépôt (hors tests et migrations)."""
from pathlib import Path



RACINE = Path(__file__).resolve().parent.parent.parent  # racine du dépôt (ce fichier est dans parametres/aides_tests/)


EXCLUS = {".git", ".claude", "migrations", "node_modules", "local-data", "staticfiles", "__pycache__"}


def est_test(chemin):
    aide = "aides_tests" in chemin.parts or chemin.stem == "aides_tests"  # aides des tests : du code de test, comme test_*.py
    return chemin.name.startswith("test") or chemin.name == "tests.py" or "tests" in chemin.parts or aide


def fichiers_python(racine=RACINE, tests=False):
    for p in sorted(racine.rglob("*.py")):
        rel = p.relative_to(racine)
        if EXCLUS & set(rel.parts) or (est_test(rel) and not tests):
            continue
        yield p
