"""Une seule règle d'arrondi (``collecte.nombres.arrondi``) pour les pages et la Visualisation.

Comparaison systématique avec les deux anciennes fonctions, recopiées ici telles qu'elles étaient :
- identique à l'ancienne fonction des pages partout (même valeur ; seul le signe d'un zéro change : « -0,00 » n'existe
  plus, ce que ``nombre`` des pages retirait déjà à l'écran ; et un nombre trop long pour 28 chiffres est désormais
  arrondi au lieu d'être laissé tel quel) ;
- identique à l'ancienne fonction de la Visualisation, sauf pour un nombre à virgule flottante dont le texte court
  (``str``) diffère de son texte à 15 chiffres significatifs (0.33499999999999996 → 0,34 et non plus 0,33) : c'était
  l'écart entre une page et un graphique.
"""
import math
import random
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from django.test import SimpleTestCase

from . import nombres
from .templatetags import collecte as T
from .visuels import formes as F


def ancien_pages(v, decimales=0):
    if isinstance(v, float) and math.isfinite(v):
        d = Decimal(format(v, ".15g"))
    else:
        d = v if isinstance(v, Decimal) else Decimal(str(v))
    try:
        return d.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return d


def ancien_visu(v, decimales):
    d = v if isinstance(v, Decimal) else Decimal(str(v))
    if not d.is_finite():
        return d
    n = int(decimales or 0)
    with localcontext() as c:
        c.prec = max(28, d.adjusted() + n + 3)
        d = d.quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP)
    return abs(d) if d == 0 else d


def valeurs():
    """Plusieurs milliers de valeurs : décimaux et flottants, positifs et négatifs, limites x,5, très grands, très petits."""
    hasard = random.Random(20261112)
    sortie = []
    for n in range(0, 7):
        for _ in range(250):  # limites x,5 à la décimale n+1, en décimal et en flottant
            entier = hasard.randint(0, 10 ** hasard.randint(0, 9))
            d = (Decimal(entier) * 10 + 5).scaleb(-(n + 1))  # ex. 1234,5 ; 12,345 (n = 2)
            sortie += [d, -d, float(d), -float(d)]
    for _ in range(1500):  # décimaux et flottants quelconques, de 1e-12 à 1e15
        x = hasard.uniform(-1, 1) * 10 ** hasard.randint(-12, 15)
        sortie += [x, Decimal(repr(x)), Decimal(str(round(x, hasard.randint(0, 12))))]
    for _ in range(300):  # sommes de flottants (0,1 + 0,235…)
        a, b = round(hasard.uniform(-1000, 1000), 3), round(hasard.uniform(-1000, 1000), 3)
        sortie += [a + b, a - b, a * 3]
    sortie += [0.1 + 0.235, 1.005, 2.675, 0.125, -0.125, 2.5, -2.5, 0.0, -0.0, -0.001, -0.0049, 1e-300, -1e-300,
               1e15, 1e300, -1e300, 123456789012345.67, Decimal("0"), Decimal("-0"), Decimal("-0.0000001"),
               Decimal("12345678901234567890123456.785"), Decimal("1E+30"), Decimal("-9.99999999999999999999999E+40"),
               Decimal("0.00000000000000000000000000005"), 0, 1, -7, 10 ** 20, -(10 ** 30) - 5]
    return sortie


def meme(a, b):
    """Même valeur et même écriture (au signe d'un zéro près)."""
    return a == b and str(abs(a) if a == 0 else a) == str(abs(b) if b == 0 else b)


class RegleUniqueTests(SimpleTestCase):
    def test_un_seul_arrondi(self):
        self.assertIs(T.arrondi, nombres.arrondi)
        self.assertIs(F.arrondi, nombres.arrondi)

    def test_ecart_page_graphique_corrige(self):
        x = 0.1 + 0.235  # 0.33499999999999996, qu'Excel lit 0,335
        self.assertEqual(T.arrondi(x, 2), Decimal("0.34"))
        self.assertEqual(F.arrondi(x, 2), Decimal("0.34"))
        self.assertEqual(F.nombre(x, 2), T.nombre(x, 2, "fr"))

    def test_garanties(self):
        A = nombres.arrondi
        self.assertEqual(str(A(-0.001, 2)), "0.00")  # pas de « -0 »
        self.assertEqual(str(A(Decimal("-0.004"), 2)), "0.00")
        self.assertEqual(A(2.5), 3)
        self.assertEqual(A(-2.5), -3)
        self.assertEqual(A(Decimal("12345678901234567890123456789.5")), Decimal("12345678901234567890123456790"))
        self.assertTrue(A(float("inf"), 2).is_infinite())
        self.assertTrue(A(float("nan"), 2).is_nan())
        self.assertEqual(A(Decimal("1.25"), None), 1)

    def test_comparaison_systematique(self):
        vals = valeurs()
        self.assertGreater(len(vals), 5000)
        ecarts_visu, autres_pages = [], []
        for v in vals:
            for n in range(0, 7):
                nouveau = nombres.arrondi(v, n)
                p = ancien_pages(v, n)
                if not meme(nouveau, p):
                    # seule différence admise : l'ancienne fonction des pages laissait sans arrondi un nombre trop long
                    with localcontext() as c:
                        c.prec = 400
                        lu = Decimal(format(v, ".15g")) if isinstance(v, float) else v if isinstance(v, Decimal) else Decimal(str(v))
                        trop_long = p == lu and not meme(p, nouveau) and nouveau == lu.quantize(Decimal(1).scaleb(-n),
                                                                                                   rounding=ROUND_HALF_UP)
                    autres_pages.append((v, n)) if not trop_long else None
                if not meme(nouveau, ancien_visu(v, n)):
                    ecarts_visu.append((v, n))
        self.assertEqual(autres_pages, [])
        # avec la Visualisation, l'écart ne vient que des flottants dont str() et le texte à 15 chiffres diffèrent
        for v, n in ecarts_visu:
            self.assertIsInstance(v, float, (v, n))
            self.assertNotEqual(Decimal(str(v)), Decimal(format(v, ".15g")), (v, n))
        self.assertIn((0.1 + 0.235, 2), ecarts_visu)


class SignePourcentTests(SimpleTestCase):
    """« % » de la Visualisation (fichier de langue) comme celui des pages (``avec_pourcent``) : espace fine insécable en
    français et en espagnol (docs/writing_guide.md : « 12,5 % (non-breaking space) »), collé en anglais."""

    def test_fichiers_de_langue(self):
        import json
        from pathlib import Path

        from django.conf import settings

        for langue in ("fr", "en", "es"):
            chemin = Path(settings.BASE_DIR) / "libelles" / f"visualisation.{langue}.json"
            modele = json.loads(chemin.read_text(encoding="utf-8"))["format.pourcent"]
            self.assertEqual(modele.format(valeur="12,5"), T.avec_pourcent("12,5", langue), langue)
