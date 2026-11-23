"""Garde-fou neutre et facultatif : liste de mots et de couleurs que les mainteneurs ne veulent pas voir dans le dépôt
(optional list of words the maintainers do not want in the repository; without it the test is skipped).

La liste n'est écrite nulle part dans le dépôt, pas même en empreinte : l'empreinte d'un nom court ou d'une couleur se
retrouve en quelques secondes en essayant tous les candidats. Elle vient de la variable d'environnement
``PROBANT_FORBIDDEN`` (par exemple un secret GitHub du même nom, passé aux tests par ``.github/workflows/tests.yml``) :
mots et couleurs « #RRGGBB » séparés par des virgules. Sans elle (poste de développement, demande de fusion venue d'un
fork), les tests qui s'en servent sont sautés."""
import os
import re

VARIABLE = "PROBANT_FORBIDDEN"
SAUTE = f"liste des mots et couleurs interdits absente (variable {VARIABLE})"


def interdits():
    """(mots en minuscules, couleurs « #RRGGBB » en majuscules) ; deux ensembles vides sans la variable."""
    elements = [e.strip() for e in os.environ.get(VARIABLE, "").split(",") if e.strip()]
    mots = {e.lower() for e in elements if not e.startswith("#")}
    couleurs = {e.upper() for e in elements if re.fullmatch(r"#[0-9A-Fa-f]{6}", e)}
    return mots, couleurs


def present():
    return bool(os.environ.get(VARIABLE, "").strip())


def nombre_trouves(texte, mots=None, couleurs=None):
    """Nombre de mots interdits (mot entier, sans souci de la casse) et de couleurs interdites (avec ou sans « # »)
    présents dans ``texte``. Un nombre seulement : un test qui échoue ne doit pas écrire le mot dans un journal public."""
    if mots is None or couleurs is None:
        mots, couleurs = interdits()
    bas = texte.lower()
    n = sum(1 for m in mots if re.search(rf"(?<![a-z0-9]){re.escape(m)}(?![a-z0-9])", bas))
    return n + sum(1 for c in couleurs if re.search(rf"(?<![0-9a-f]){c[1:].lower()}(?![0-9a-f])", bas))
