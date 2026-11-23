"""Règle qui tient dans le temps (politique de sécurité des contenus, collecte/politique_contenus.py ; DESIGN.md) : aucun
gabarit, aucun script de l'outil ni aucun HTML fabriqué en Python ne contient de gestionnaire en attribut (``onclick=``…),
de lien ``javascript:``, d'évaluation de texte (``eval``, ``new Function``, minuteur avec une chaîne), ni de script ou de
style intégrés sans le jeton de la requête."""
import ast
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

RACINE = Path(settings.BASE_DIR)
APPS = ("collecte", "parametres", "referentiel", "espaces", "serveur_mcp")
JETON = 'nonce="{% jeton_csp %}"'


def gabarits():
    dossiers = [RACINE / "templates"] + [RACINE / a / "templates" for a in APPS]
    return sorted(f for d in dossiers if d.is_dir() for f in d.rglob("*") if f.suffix in (".html", ".js", ".txt"))


def scripts():
    return sorted((RACINE / "static" / "js").glob("*.js"))


def modules_python():
    return sorted(f for a in APPS + ("config",) for f in (RACINE / a).rglob("*.py")
                  if not f.name.startswith("test_") and "aides_tests" not in f.parts and "migrations" not in f.parts)


def sans_balises_django(texte):
    """Texte d'un gabarit sans commentaires ni balises Django ({% %}, {{ }}) : les arguments d'une balise
    (``onglet=…``) ne sont pas des attributs HTML."""
    texte = re.sub(r"{% comment %}.*?{% endcomment %}", "", texte, flags=re.S)
    texte = re.sub(r"{#.*?#}", "", texte, flags=re.S)
    return re.sub(r"{%.*?%}|{{.*?}}", "X", texte, flags=re.S)


def chaines(source):
    """Chaînes littérales d'un module Python, sans ses docstrings."""
    arbre = ast.parse(source)
    docs = set()
    for n in ast.walk(arbre):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
            premier = n.body[0]
            if isinstance(premier, ast.Expr) and isinstance(premier.value, ast.Constant):
                docs.add(id(premier.value))
    return [n.value for n in ast.walk(arbre) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


GESTIONNAIRE = re.compile(r"<[a-zA-Z][^<>]*?\son[a-z]+\s*=", re.S)
JAVASCRIPT = re.compile(r"""(href|src|action|formaction)\s*=\s*["']?\s*javascript:""", re.I)
SCRIPT = re.compile(r"<script\b([^>]*)>", re.I)
STYLE = re.compile(r"<style\b([^>]*)>", re.I)
EVALUATION = re.compile(r"""\beval\s*\(|\bnew\s+Function\s*\(|\bset(Timeout|Interval)\s*\(\s*["'`]|setAttribute\(\s*["'](on|style)""")


class PolitiqueContenusGabaritsTests(SimpleTestCase):
    def test_gabarits(self):
        defauts = []
        for f in gabarits():
            brut = f.read_text(encoding="utf-8")
            texte = sans_balises_django(brut)
            nom = f.relative_to(RACINE)
            if GESTIONNAIRE.search(texte):
                defauts.append(f"{nom} : gestionnaire en attribut")
            if JAVASCRIPT.search(texte):
                defauts.append(f"{nom} : lien javascript:")
            if f.suffix == ".js" and EVALUATION.search(texte):
                defauts.append(f"{nom} : évaluation de texte ou attribut on…/style posé par le script")
            for m in SCRIPT.finditer(brut):
                attributs = m.group(1)
                if "src=" not in attributs and "application/json" not in attributs and JETON not in attributs:
                    defauts.append(f"{nom} : <script{attributs}> sans le jeton")
            for m in STYLE.finditer(brut):
                if JETON not in m.group(1):
                    defauts.append(f"{nom} : <style{m.group(1)}> sans le jeton")
        self.assertEqual(defauts, [])
        self.assertGreater(len(gabarits()), 150)

    def test_scripts_statiques(self):
        defauts = []
        for f in scripts():
            texte = f.read_text(encoding="utf-8")
            if GESTIONNAIRE.search(texte) or JAVASCRIPT.search(texte) or EVALUATION.search(texte):
                defauts.append(f.name)
            if re.search(r"""\bel\([^)]*\{[^}]*\bstyle\s*:\s*["'`]""", texte):  # attribut style posé par setAttribute
                defauts.append(f"{f.name} : attribut style")
        self.assertEqual(defauts, [])
        self.assertTrue(scripts())

    def test_html_fabrique_en_python(self):
        """Chaînes des modules (hors docstrings, qui décrivent la règle) : rendu de la ligne de saisie, Markdown,
        balises des gabarits, messages."""
        defauts = []
        for f in modules_python():
            texte = "\n".join(chaines(f.read_text(encoding="utf-8")))
            if GESTIONNAIRE.search(texte) or JAVASCRIPT.search(texte):
                defauts.append(f"{f.relative_to(RACINE)} : gestionnaire ou lien javascript:")
            for m in list(SCRIPT.finditer(texte)) + list(STYLE.finditer(texte)):
                if "nonce" not in m.group(1) and "application/json" not in m.group(1) and "src=" not in m.group(1):
                    defauts.append(f"{f.relative_to(RACINE)} : {m.group(0)}")
        self.assertEqual(defauts, [])

    def test_le_detecteur_reconnait_les_defauts(self):
        """Témoin : les motifs trouvent bien ce qu'ils cherchent (sans quoi les tests ci-dessus passeraient à vide)."""
        self.assertTrue(GESTIONNAIRE.search(sans_balises_django('<select name="x" onchange="this.form.submit()">')))
        self.assertTrue(GESTIONNAIRE.search(sans_balises_django('<a href="#"\n   onclick="return false">')))
        self.assertFalse(GESTIONNAIRE.search(sans_balises_django('<p>{% libelle "a" onglet=r.onglet %}</p>')))
        self.assertTrue(JAVASCRIPT.search('<a href="javascript:alert(1)">'))
        self.assertTrue(EVALUATION.search('setTimeout("maj()", 10)'))
        self.assertFalse(EVALUATION.search("setTimeout(() => maj(), 10)"))
        self.assertTrue(EVALUATION.search('b.setAttribute("style", "x")'))
        self.assertEqual(len(SCRIPT.findall("<script>x</script><script nonce=\"{% jeton_csp %}\">")), 2)
