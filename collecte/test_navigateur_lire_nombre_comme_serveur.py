"""Lecture d'un nombre tapé dans le navigateur (``lireNombre``, ``_app/01_socle.js`` : constante du constructeur de
formule, aperçu de l'écart avec N-1, aperçu d'une unité, tri d'un tableau) : mêmes résultats que le serveur
(``saisie.texte_nombre``) dans les sept langues (Playwright, Chromium ; ignoré s'il manque, obligatoire avec
REQUIRE_BROWSER_TESTS=1).

Défaut corrigé : la règle « un groupe de milliers commence par un chiffre de 1 à 9 » du serveur n'était pas reportée dans
le JavaScript. En anglais, « 0,205 » tapé comme constante dans le constructeur de formule devenait 205 et s'enregistrait
dans la formule ; « 0,205,123 » était lu 205 123 (ou 0,205) au lieu d'être refusé. Le serveur, lui, lisait « 0,205.5 »
205,5 dans toutes les langues : ce texte n'est plus un nombre, ni d'un côté ni de l'autre."""
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from parametres import langues as L

from . import saisie as S
from .aides_tests.navigateur import NavigateurBase, _hors_boucle
from .templatetags.collecte import separateurs

SOURCE = Path(__file__).resolve().parent / "templates" / "collecte" / "_app" / "01_socle.js"
LANGUES = ("en", "fr", "es", "de", "it", "nl", "pt")
TABLE = ("0,205", "0,205,123", "1,234", "1.234,5", "1 234,5", "-0,5", "0,205.5", "0.205,5", "1,234.5", "1.234.567",
         "1,234,567", "12,5", "0.205", "-0,205", "1,5", "+1,234", "1.234.5", "007", "abc", "")


def lire_nombre_js():
    """Texte de la fonction ``lireNombre`` du script des pages, tel quel."""
    m = re.search(r"\n  function lireNombre\(texte\) \{\n.*?\n  \}\n", SOURCE.read_text(encoding="utf-8"), re.S)
    assert m, "lireNombre introuvable dans 01_socle.js"
    return m.group(0)


def lu_serveur(texte, langue):
    try:
        return Decimal(S.texte_nombre(texte, langue))
    except (InvalidOperation, ValueError):
        return None


class LireNombreCommeLeServeurTests(NavigateurBase):
    def test_table_dans_les_sept_langues(self):
        page = self.page()
        page.goto("about:blank")
        source = lire_nombre_js()
        for lg in LANGUES:
            decimale = separateurs(lg)[1]
            lus = page.evaluate(f"(textes) => {{ const DECIMALE = {decimale!r}; {source} return textes.map((t) => {{ "
                                "const v = lireNombre(t); return Number.isNaN(v) ? null : v; }); }", list(TABLE))
            for texte, js in zip(TABLE, lus):
                with self.subTest(langue=lg, texte=texte):
                    serveur = lu_serveur(texte, lg)
                    self.assertEqual(js, None if serveur is None else float(serveur))

    def test_serveur_zero_virgule_point(self):
        for lg in LANGUES:
            with self.subTest(langue=lg):
                self.assertIsNone(lu_serveur("0,205.5", lg))
                self.assertIsNone(lu_serveur("0.205,5", lg))
                self.assertEqual(lu_serveur("1,234.5", lg), Decimal("1234.5"))

    def test_constante_du_constructeur_de_formule_en_anglais(self):
        with _hors_boucle():
            self.admin.langue = "en"
            self.admin.save()
        page = self.page()
        self.aller(page, "/referentiel/kpi/nouveau/")
        self.assertEqual(page.locator("html").get_attribute("lang"), "en")
        page.locator("input[name=type_saisie][value='Calculé']").check()
        bloc = page.locator("[data-si-calcule]")
        for saisi, attendu in (("0,205", "0.205"), ("1,234", "1234")):
            with self.subTest(saisi):
                bloc.locator("[data-vider]").click()
                bloc.locator("[data-nombre]").fill(saisi)
                bloc.locator("[data-ajout-nombre]").click()
                self.assertEqual(bloc.locator("[data-constructeur] textarea").input_value().strip(), attendu)
        with L.activer("en"):
            self.assertEqual(S.texte_nombre("0,205"), "0.205")
        self.assertEqual(page.erreurs, [])
