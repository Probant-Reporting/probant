"""Règles de structure du code, vérifiées par analyse statique (AST) de tous les fichiers Python du dépôt, hors tests et
hors migrations :

1. Aucun module n'utilise un nom privé (``_nom``) d'un autre module, ni par ``from x import _nom`` (au niveau du module
   ou dans une fonction), ni par ``X._nom`` sur un module importé : ce qui est partagé porte un nom public
   (``collecte/vues_communes.py`` pour les aides de vues). Exceptions : ``SOUS_PAQUETS_INTERNES`` ci-dessous.
2. Tout import d'un module du projet vise un module qui existe et un nom qu'il définit : un import placé dans une fonction
   ne casse plus seulement à l'exécution de la page après un renommage.
3. Les sens d'import entre applications absents aujourd'hui restent absents (``SENS_ABSENTS``) : la boucle d'imports
   existante entre ``collecte``, ``parametres``, ``referentiel`` et ``espaces`` ne s'étend pas.
"""
import ast
from pathlib import Path

from django.test import SimpleTestCase
from .aides_tests.structure import RACINE, est_test, fichiers_python

APPLICATIONS = ("collecte", "config", "espaces", "parametres", "referentiel")

# Sous-paquets découpés d'un ancien module unique (fichiers de référentiel, visuels) : leurs fichiers partagent leurs aides
# privées entre eux (privées au sous-paquet), et le ``__init__`` les réexpose pour les appelants et les tests d'avant le
# découpage. Hors de ces sous-paquets, leurs noms privés restent interdits.
SOUS_PAQUETS_INTERNES = ("collecte.paquets", "collecte.visuels")

# (application qui importe, application importée) : aucune arête aujourd'hui, et il n'en faut pas. ``espaces`` est la
# couche basse des espaces (base de données, contexte de la requête) : elle ne dépend pas des pages de ``collecte`` ;
# ``config`` (réglages, adresses) n'est importé par aucune application.
SENS_ABSENTS = {
    ("espaces", "collecte"),
    ("config", "parametres"), ("config", "referentiel"),
    ("collecte", "config"), ("espaces", "config"), ("parametres", "config"), ("referentiel", "config"),
}


def nom_module(chemin, racine=RACINE):
    parties = list(chemin.relative_to(racine).with_suffix("").parts)
    if parties[-1] == "__init__":
        parties.pop()
    return ".".join(parties)


class Module:
    """Ce qu'un fichier définit au niveau du module (fonctions, classes, variables, noms importés) et ses imports."""

    def __init__(self, chemin, racine=RACINE):
        self.chemin = chemin
        self.nom = nom_module(chemin, racine)
        self.paquet = chemin.name == "__init__.py"
        self.arbre = ast.parse(chemin.read_text(encoding="utf-8"), str(chemin))
        self.noms = set()
        self.ouvert = False  # ``import *`` ou ``__getattr__`` : noms impossibles à lister
        for n in self.arbre.body:
            self._definir(n)

    def _definir(self, n):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.noms.add(n.name)
            self.ouvert |= n.name == "__getattr__"
        elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for c in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                self.noms |= {e.id for e in ast.walk(c) if isinstance(e, ast.Name)}
        elif isinstance(n, ast.Import):
            self.noms |= {a.asname or a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name == "*":
                    self.ouvert = True
                else:
                    self.noms.add(a.asname or a.name)
        elif isinstance(n, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            for e in ast.iter_child_nodes(n):
                if isinstance(e, ast.stmt):
                    self._definir(e)
                elif isinstance(e, ast.ExceptHandler):
                    for f in e.body:
                        self._definir(f)

    def source(self, noeud):
        """Module absolu visé par un ``from … import`` (imports relatifs résolus)."""
        if not noeud.level:
            return noeud.module or ""
        base = self.nom.split(".")
        retire = noeud.level - (1 if self.paquet else 0)
        base = base[: len(base) - retire] if retire else base
        return ".".join(base + ([noeud.module] if noeud.module else []))


class Projet:
    def __init__(self, racine=RACINE):
        self.racine = racine
        self.modules = {}
        for p in fichiers_python(racine, tests=True):
            m = Module(p, racine)
            self.modules[m.nom] = m

    def du_projet(self, nom):
        return nom.split(".")[0] in {m.split(".")[0] for m in self.modules}

    def est_module(self, nom):
        return nom in self.modules

    def a_le_nom(self, module, nom):
        m = self.modules[module]
        return m.ouvert or nom in m.noms or self.est_module(f"{module}.{nom}")

    def a_analyser(self):
        return [m for m in self.modules.values() if not est_test(m.chemin.relative_to(self.racine))]


def interne(a, b):
    """Vrai si les modules ``a`` et ``b`` sont tous deux dans un même sous-paquet de ``SOUS_PAQUETS_INTERNES``."""
    return any((a == p or a.startswith(p + ".")) and (b == p or b.startswith(p + ".")) for p in SOUS_PAQUETS_INTERNES)


def noeuds_avec_portee(arbre):
    """(nœud, dans_une_fonction) pour chaque nœud de l'arbre."""
    pile = [(arbre, False)]
    while pile:
        n, f = pile.pop()
        yield n, f
        dedans = f or isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        pile.extend((e, dedans) for e in ast.iter_child_nodes(n))


def usages_prives(projet):
    """[(fichier, ligne, module source, nom, « import (module) » / « import (fonction) » / « attribut »)] : noms privés d'un
    autre module du projet utilisés hors des exceptions."""
    trouves = []
    for m in projet.a_analyser():
        rel = str(m.chemin.relative_to(projet.racine))
        alias = {}  # nom local → module du projet (``from . import saisie as S``, ``import collecte.views as V``)
        for n, dans_fonction in noeuds_avec_portee(m.arbre):
            if isinstance(n, ast.ImportFrom):
                src = m.source(n)
                for a in n.names:
                    if projet.est_module(f"{src}.{a.name}"):
                        alias[a.asname or a.name] = f"{src}.{a.name}"
                    elif (a.name.startswith("_") and not a.name.startswith("__") and src != m.nom and projet.du_projet(src)
                          and not interne(m.nom, src)):
                        trouves.append((rel, n.lineno, src, a.name, "import (fonction)" if dans_fonction else "import (module)"))
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.asname and projet.est_module(a.name):
                        alias[a.asname] = a.name
        for n in ast.walk(m.arbre):
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in alias
                    and n.attr.startswith("_") and not n.attr.startswith("__")):
                src = alias[n.value.id]
                if src != m.nom and not projet.est_module(f"{src}.{n.attr}") and not interne(m.nom, src):
                    trouves.append((rel, n.lineno, src, n.attr, "attribut"))
    return sorted(set(trouves))


def imports_casses(projet):
    """[(fichier, ligne, texte)] : imports d'un module du projet inexistant, ou d'un nom que ce module ne définit pas."""
    casses = []
    for m in projet.a_analyser():
        rel = str(m.chemin.relative_to(projet.racine))
        for n in ast.walk(m.arbre):
            if isinstance(n, ast.ImportFrom):
                src = m.source(n)
                if not projet.du_projet(src) or src.split(".")[0] not in APPLICATIONS + ("qa", "portable"):
                    continue
                if not projet.est_module(src):
                    casses.append((rel, n.lineno, f"module {src} introuvable"))
                    continue
                for a in n.names:
                    if a.name != "*" and not projet.a_le_nom(src, a.name):
                        casses.append((rel, n.lineno, f"{src} ne définit pas {a.name}"))
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.name.split(".")[0] in APPLICATIONS and not projet.est_module(a.name):
                        casses.append((rel, n.lineno, f"module {a.name} introuvable"))
    return casses


def sens_d_import(projet):
    """{(application, application importée): {fichiers}} pour les imports entre applications (tous niveaux)."""
    sens = {}
    for m in projet.a_analyser():
        app = m.nom.split(".")[0]
        if app not in APPLICATIONS:
            continue
        for n in ast.walk(m.arbre):
            cibles = []
            if isinstance(n, ast.ImportFrom):
                cibles = [m.source(n)]
            elif isinstance(n, ast.Import):
                cibles = [a.name for a in n.names]
            for c in cibles:
                autre = c.split(".")[0]
                if autre in APPLICATIONS and autre != app:
                    sens.setdefault((app, autre), set()).add(str(m.chemin.relative_to(projet.racine)))
    return sens


class StructureImportsTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.projet = Projet()

    def test_aucun_nom_prive_d_un_autre_module(self):
        trouves = usages_prives(self.projet)
        self.assertEqual(trouves, [], "noms privés utilisés hors de leur module (rendre le nom public) :\n"
                         + "\n".join(f"{f}:{l} {s}.{n} ({t})" for f, l, s, n, t in trouves))

    def test_imports_du_projet_resolus(self):
        casses = imports_casses(self.projet)
        self.assertEqual(casses, [], "\n".join(f"{f}:{l} {t}" for f, l, t in casses))

    def test_sens_d_import_absents_restent_absents(self):
        sens = sens_d_import(self.projet)
        for couple in sorted(SENS_ABSENTS):
            with self.subTest(sens=" → ".join(couple)):
                self.assertNotIn(couple, sens, sorted(sens.get(couple, ())))

    def test_le_detecteur_voit_les_trois_formes(self):
        """Le test lui-même : un import privé (module, fonction), un attribut privé, un import cassé sont bien vus."""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "collecte").mkdir()
            (base / "collecte" / "__init__.py").write_text("")
            (base / "collecte" / "a.py").write_text("def _cache():\n    pass\n\ndef public():\n    pass\n")
            (base / "collecte" / "b.py").write_text(
                "from .a import _cache\nfrom . import a as A\n\ndef f():\n    from collecte.a import absent, public\n"
                "    return A._cache\n")
            projet = Projet(base)
            self.assertEqual([(t[3], t[4]) for t in usages_prives(projet)], [("_cache", "import (module)"), ("_cache", "attribut")])
            self.assertEqual([t[2] for t in imports_casses(projet)], ["collecte.a ne définit pas absent"])
