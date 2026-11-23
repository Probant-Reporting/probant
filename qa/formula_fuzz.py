"""Random formulas: the tool's formula parser and evaluator (referentiel/formule.py) against the independent one.

    python3 qa/formula_fuzz.py [--n 20000] [--seed 1]

Formulas are generated from the grammar, then sometimes damaged (characters inserted, removed or swapped, odd spaces,
very long or deeply nested expressions). For each: both parsers must agree (accepted or refused) and, when accepted,
give the same value, N/A, missing or error on random source values (exact fractions on the independent side).
Also checks the display rounding (``arrondi``: half away from zero, like Excel). Exit code 0 if no difference.
"""
# Commentaires en français (règles du projet) ; messages en anglais.
import argparse
import random
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "qa"))

import independent_calculation as IC  # noqa: E402
from calculation_fuzz import preparer_django  # noqa: E402

CODES = ["A", "B", "C", "K12", "123456", "X_1"]


def formule(R, d=0, longue=False):
    if d >= (8 if longue else 4) or (d > 0 and R.random() < 0.35):
        t = R.random()
        if t < 0.7:
            dec = R.choice(["", "", "@N-1", "@P-1", "@2021", "@N"])
            e1, e2 = R.choice(["", " "]), R.choice(["", " "])
            return f"[{e1}{R.choice(CODES)}{dec}{e2}]"
        return R.choice(["0", "1", "2.5", "10", "0.001", "1000000", "3"])
    op = R.choice("+-*/")
    a, b = formule(R, d + 1, longue), formule(R, d + 1, longue)
    s = R.choice(["", " ", "\t", "  "])
    t = f"{a}{s}{op}{s}{b}"
    if R.random() < 0.1:
        t = "-" + t if R.random() < 0.5 else "-(" + t + ")"
    return f"({t})" if R.random() < 0.5 else t


def abimer(R, t):
    """Abîme une formule : caractère inséré, retiré ou échangé."""
    for _ in range(R.randint(1, 3)):
        i = R.randrange(len(t) + 1)
        x = R.random()
        if x < 0.4:
            t = t[:i] + R.choice("[]()@+-*/. ,;xN1é ") + t[i:]
        elif x < 0.8 and t:
            t = t[:i] + t[i + 1:]
        elif len(t) > 2:
            j = R.randrange(len(t))
            l = list(t)
            l[i % len(t)], l[j] = l[j], l[i % len(t)]
            t = "".join(l)
    return t


def valeurs_au_hasard(R, refs):
    out = {}
    for r in refs:
        x = R.random()
        out[r] = None if x < 0.05 else IC.NA if x < 0.15 else Fraction(0) if x < 0.3 else Fraction(R.randint(-50, 200), R.choice([1, 2, 4, 10]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    preparer_django()
    from referentiel import formule as F
    from collecte.templatetags.collecte import arrondi

    R = random.Random(args.seed)
    differences = []
    acceptees = refusees = valeurs = 0
    for i in range(args.n):
        t = formule(R, longue=R.random() < 0.05)
        if R.random() < 0.3:
            t = abimer(R, t)
        if R.random() < 0.05:
            t = " ".join([t] * R.randint(2, 40)).replace(" ", " + ")  # très longues
        if R.random() < 0.02:
            n = R.randint(30, 80)
            t = "(" * n + t + ")" * n  # très imbriquées
        try:
            arbre = F.analyser(t)
            outil = True
        except F.FormuleInvalide:
            outil = False
        except RecursionError:
            differences.append(("recursion", t))
            continue
        try:
            a2 = IC.analyser(t)
            moi = True
        except (IC.FormuleIllisible, RecursionError):
            moi = False
        if outil != moi:
            # les seules différences admises : les garde-fous de l'outil, formule refusée, jamais un autre résultat ;
            # taille (imbrication 50, profondeur 200) et année impossible dans [X@AAAA] (hors de 1900 à 2999 : pas un
            # exercice, ``formule.ANNEE_MIN`` et ``ANNEE_MAX``)
            annee_impossible = moi and any(r[2].isdecimal() and not 1900 <= int(r[2]) <= 2999 for r in IC.references(a2))
            if not (moi and not outil and ("(" * 40 in t or len(t) > 600 or t.count("-") > 40 or annee_impossible)):
                differences.append(("parse", t, outil, moi))
            continue
        if not outil:
            refusees += 1
            continue
        acceptees += 1
        refs2 = IC.references(a2)
        for _ in range(3):
            v2 = valeurs_au_hasard(R, refs2)
            par_ref = {(r[1], r[2]): v for r, v in v2.items()}

            def resoudre(ref):
                v = par_ref.get((ref.kpi, ref.decalage))
                return v if v is None or v is IC.NA else Decimal(v.numerator) / Decimal(v.denominator)
            na_zero = R.random() < 0.5
            try:
                r1 = F.evaluer(arbre, lambda ref: F.NA if par_ref.get((ref.kpi, ref.decalage)) is IC.NA else resoudre(ref),
                               na_zero=na_zero)
                r1 = "NA" if r1 is F.NA else r1
            except F.ValeurManquante:
                r1 = "manquante"
            except F.ErreurCalcul:
                r1 = "erreur"
            try:
                r2 = IC.evaluer(a2, {r: (IC.NA if v is IC.NA else None if v is None else IC.Nombre(v)) for r, v in v2.items()}, na_zero)
                r2 = "manquante" if r2 is None else "NA" if r2 is IC.NA else r2
            except IC.Erreur:
                r2 = "erreur"
            valeurs += 1
            if r2 == IC.IMPRECIS:
                continue
            if isinstance(r2, IC.Nombre):
                ok = isinstance(r1, Decimal) and abs(Fraction(r1) - r2.v) <= Fraction(1, 10 ** 12) * max(1, abs(r2.v))
            else:
                ok = r1 == r2
            if not ok:
                differences.append(("value", t, {f"{k}{'' if d == 'N' else '@' + d}": str(v) for (k, d), v in par_ref.items()},
                                    na_zero, str(r1), str(r2)))
    # arrondi à l'écran : la moitié s'éloigne de zéro, comme Excel ; un float passe par son texte
    import math
    for _ in range(20000):
        d = R.randint(0, 4)
        n = R.randint(-10 ** 7, 10 ** 7)
        x = Decimal(n) / Decimal(10 ** R.randint(0, 7))
        attendu = (abs(x) * 10 ** d + Decimal("0.5")).to_integral_value(rounding="ROUND_FLOOR") / Decimal(10 ** d)
        attendu = attendu.copy_sign(x) if x else attendu
        if arrondi(x, d) != attendu:
            differences.append(("arrondi", str(x), d, str(arrondi(x, d)), str(attendu)))
        f = float(x)
        if not math.isfinite(f):
            continue
        attendu_f = (abs(Decimal(format(f, ".15g"))) * 10 ** d + Decimal("0.5")).to_integral_value(rounding="ROUND_FLOOR") / Decimal(10 ** d)
        if abs(arrondi(f, d)) != attendu_f:
            differences.append(("arrondi float", repr(f), d, str(arrondi(f, d)), str(attendu_f)))
    for d in differences[:40]:
        print(d)
    print(f"{args.n} formulas: {acceptees} accepted, {refusees} refused, {valeurs} evaluations; {len(differences)} differences")
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
