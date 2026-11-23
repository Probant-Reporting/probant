"""Formules des KPI calculés.

Syntaxe (cahier des charges, section 5.2) :
    [ACC-01] / [HEU-01] * 1000000
    ([EFF-01] - [EFF-01@N-1]) / [EFF-01@N-1]
    ([CO2-01] / [CA-01]) / ([CO2-01@2021] / [CA-01@2021]) - 1

- [ID]        valeur du KPI pour la même organisation et la même période
- [ID@N-1]    même période de l'exercice précédent (l'an dernier ; pour une année : l'exercice précédent)
- [ID@P-1]    période précédente (le mois, le trimestre… d'avant ; pour une année : l'exercice précédent)
- [ID@2021]   même période en 2021
- opérateurs + - * /, parenthèses, nombres (point décimal)

La formule est analysée par un petit parseur dédié : aucune évaluation de code Python.
"""
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from parametres.libelles import libelle

TOKEN = re.compile(r"\s*(?:(?P<ref>\[[^\[\]]+\])|(?P<num>\d+(?:\.\d+)?)|(?P<op>[-+*/()]))")
TOKEN_REF = re.compile(r"\[[^\[\]]+\]")
# espaces permis partout dans les crochets : « [ EFF-01 @ N-1 ] » (une espace avant « ] » était refusée après un décalage)
REF = re.compile(r"^\[(?P<id>[^@\]]+?)\s*(?:@\s*(?P<dec>N-1|P-1|N|\d{4})\s*)?\]$")


# Garde-fous contre les formules démesurées (sinon RecursionError, erreur 500) : parenthèses ou signes « - » imbriqués,
# et profondeur de l'arbre (une somme de n termes a une profondeur n). Les formules réelles en sont très loin.
IMBRICATION_MAX = 50
ANNEE_MIN, ANNEE_MAX = 1900, 2999  # années acceptées dans [X@AAAA]
PROFONDEUR_MAX = 200


class FormuleInvalide(ValueError):
    pass


@dataclass(frozen=True)
class Ref:
    kpi: str
    decalage: str = "N"  # "N", "N-1", "P-1" ou une année "2021"


@dataclass(frozen=True)
class Num:
    valeur: Decimal


@dataclass(frozen=True)
class Op:
    op: str
    gauche: object
    droite: object


@dataclass(frozen=True)
class Neg:
    arg: object


def _tokens(texte):
    pos, out = 0, []
    texte = texte.strip()
    while pos < len(texte):
        m = TOKEN.match(texte, pos)
        if not m or m.end() == pos:
            raise FormuleInvalide(libelle("messages.formule.caractere_inattendu", position=pos + 1, extrait=texte[pos:pos + 15]))
        pos = m.end()
        if m.group("ref"):
            r = REF.match(m.group("ref"))
            if not r or not r.group("id").strip():  # « [ ] », « [ @N-1] » : pas de code (refusé, au lieu d'un KPI « »)
                raise FormuleInvalide(libelle("messages.formule.reference_invalide", reference=m.group("ref")))
            dec = r.group("dec") or "N"
            # [X@0000], [X@9999] : pas un exercice (et une date impossible faisait planter chaque saisie du KPI cité)
            if dec.isdecimal() and not ANNEE_MIN <= int(dec) <= ANNEE_MAX:
                raise FormuleInvalide(libelle("messages.formule.reference_invalide", reference=m.group("ref")))
            out.append(("ref", Ref(r.group("id").strip(), dec)))
        elif m.group("num"):
            out.append(("num", Num(Decimal(m.group("num")))))
        else:
            out.append(("op", m.group("op")))
    return out


def analyser(texte):
    """Transforme le texte d'une formule en arbre. Lève FormuleInvalide."""
    if not texte or not texte.strip():
        raise FormuleInvalide(libelle("messages.formule.vide"))
    toks = _tokens(texte)
    i = 0
    niveau = 0

    def peek():
        return toks[i] if i < len(toks) else (None, None)

    def take():
        nonlocal i
        t = peek()
        i += 1
        return t

    def expr():
        node = terme()
        while peek() in (("op", "+"), ("op", "-")):
            node = Op(take()[1], node, terme())
        return node

    def terme():
        node = facteur()
        while peek() in (("op", "*"), ("op", "/")):
            node = Op(take()[1], node, facteur())
        return node

    def imbriquer():
        nonlocal niveau
        niveau += 1
        if niveau > IMBRICATION_MAX:
            raise FormuleInvalide(libelle("messages.formule.trop_complexe"))

    def facteur():
        nonlocal niveau
        kind, val = take()
        if kind in ("ref", "num"):
            return val
        if (kind, val) == ("op", "-"):
            imbriquer()
            node = Neg(facteur())
            niveau -= 1
            return node
        if (kind, val) == ("op", "("):
            imbriquer()
            node = expr()
            if take() != ("op", ")"):
                raise FormuleInvalide(libelle("messages.formule.parenthese_manquante"))
            niveau -= 1
            return node
        raise FormuleInvalide(libelle("messages.formule.expression_incomplete") if kind is None
                              else libelle("messages.formule.element_inattendu", element=val))

    arbre = expr()
    if i != len(toks):
        raise FormuleInvalide(libelle("messages.formule.element_inattendu", element=toks[i][1]))
    if _profondeur(arbre) > PROFONDEUR_MAX:
        raise FormuleInvalide(libelle("messages.formule.trop_complexe"))
    return arbre


def _profondeur(arbre):
    """Profondeur de l'arbre, calculée sans récursion."""
    plus, pile = 0, [(arbre, 1)]
    while pile:
        n, p = pile.pop()
        plus = max(plus, p)
        if isinstance(n, Op):
            pile += [(n.gauche, p + 1), (n.droite, p + 1)]
        elif isinstance(n, Neg):
            pile.append((n.arg, p + 1))
    return plus


def references(arbre_ou_texte):
    """Liste des références (Ref) d'une formule, sans doublon, dans l'ordre d'apparition."""
    arbre = analyser(arbre_ou_texte) if isinstance(arbre_ou_texte, str) else arbre_ou_texte
    vus, out = set(), []

    def walk(n):
        if isinstance(n, Ref):
            if n not in vus:
                vus.add(n)
                out.append(n)
        elif isinstance(n, Op):
            walk(n.gauche)
            walk(n.droite)
        elif isinstance(n, Neg):
            walk(n.arg)

    walk(arbre)
    return out


def codes_cites(texte, decalage=None):
    """Codes des KPI cités par une formule : toutes périodes ([X], [X@N-1]…), ou seulement celles du ``decalage`` donné
    (« N » : même période) ; aucun si elle est illisible."""
    try:
        refs = references(texte or "")
    except FormuleInvalide:
        return set()
    return {r.kpi for r in refs if decalage is None or r.decalage == decalage}


def refs_additives(arbre):
    """Références qui ne sont qu'additionnées ou soustraites (termes d'un total, hors produit et quotient)."""
    sortie = set()

    def walk(n):
        if isinstance(n, Ref):
            sortie.add(n)
        elif isinstance(n, Neg):
            walk(n.arg)
        elif isinstance(n, Op) and n.op in "+-":
            walk(n.gauche)
            walk(n.droite)

    walk(arbre)
    return sortie


def additive(arbre_ou_texte):
    """Vrai si la formule est une somme : seulement des références, des nombres, + et −, et des parenthèses (au moins une
    référence). Faux pour un produit, un quotient ou une formule invalide. Une telle formule compte par défaut une source
    N/A comme 0 (case de la fiche KPI)."""
    try:
        arbre = analyser(arbre_ou_texte) if isinstance(arbre_ou_texte, str) else arbre_ou_texte
    except FormuleInvalide:
        return False

    def walk(n):
        if isinstance(n, (Ref, Num)):
            return True
        if isinstance(n, Neg):
            return walk(n.arg)
        return isinstance(n, Op) and n.op in "+-" and walk(n.gauche) and walk(n.droite)

    return walk(arbre) and bool(references(arbre))


def renommer(texte, codes):
    """Remplace des codes de KPI dans une formule ({ancien: nouveau}), décalages et espaces conservés."""
    if not texte or not codes:
        return texte

    def remplacer(m):
        r = REF.match(m.group(0))
        if not r or r.group("id").strip() not in codes:
            return m.group(0)
        debut, fin = r.span("id")
        brut = m.group(0)
        ancien = r.group("id")
        return brut[:debut] + ancien.replace(ancien.strip(), codes[ancien.strip()]) + brut[fin:]

    return TOKEN_REF.sub(remplacer, texte)


def en_clair(texte, noms, exercice_precedent="N-1", periode_precedente="P-1"):
    """Formule écrite pour être lue : le nom de chaque KPI à la place de son code, × et ÷ à la place de * et /.
    « [A] * [B@N-1] » → « Électricité × Facteur du réseau (exercice précédent) ». ``noms`` : {code: nom} ; un code
    inconnu reste tel quel. Chaîne vide si la formule est vide ou illisible (elle est signalée ailleurs)."""
    texte = (texte or "").strip()
    if not texte:
        return ""
    morceaux, pos = [], 0
    while pos < len(texte):
        m = TOKEN.match(texte, pos)
        if not m or m.end() == pos:
            return "" if texte[pos:].strip() else " ".join(morceaux).replace("( ", "(").replace(" )", ")")
        pos = m.end()
        if m.group("ref"):
            r = REF.match(m.group("ref"))
            if not r:
                return ""
            code, dec = r.group("id").strip(), r.group("dec")
            nom = noms.get(code) or code
            if dec == "N-1":
                nom = f"{nom} ({exercice_precedent})"
            elif dec == "P-1":
                nom = f"{nom} ({periode_precedente})"
            elif dec and dec != "N":
                nom = f"{nom} ({dec})"
            morceaux.append(nom)
        elif m.group("num"):
            morceaux.append(m.group("num"))
        else:
            morceaux.append({"*": "×", "/": "÷", "-": "−"}.get(m.group("op"), m.group("op")))
    return " ".join(morceaux).replace("( ", "(").replace(" )", ")")


class _NA:
    """Valeur « non applicable » : se propage dans les calculs."""

    def __repr__(self):
        return "N/A"


NA = _NA()


class ValeurManquante(Exception):
    pass


class ErreurCalcul(Exception):
    pass


def evaluer(arbre, resoudre, na_zero=False):
    """Évalue l'arbre. `resoudre(ref)` renvoie un Decimal, NA, ou None si la valeur manque.

    Renvoie un Decimal ou NA. Lève ValeurManquante si une source manque, ErreurCalcul en cas de division par zéro ou
    si une source n'est pas un nombre (réponse oui / non ou liste).
    Une source N/A rend le résultat N/A ; avec ``na_zero`` (case « Une source N/A compte comme 0 » de la fiche KPI), elle
    compte comme 0 et le résultat n'est N/A que si toutes les sources sont N/A (ou si l'on divise par une source N/A).
    Le résultat ne dépend pas de l'ordre des termes : toutes les sources sont lues d'abord (une source manquante rend le
    calcul impossible, quoi que donnent les autres) ; puis une division par un vrai zéro est une erreur, même si une
    division par une source N/A la précède.
    """
    valeurs, manquante = {}, None
    for ref in references(arbre):
        valeurs[ref] = v = resoudre(ref)
        if v is None and manquante is None:
            manquante = ref
    if manquante is not None:
        raise ValeurManquante(manquante)
    vu_na = vu_valeur = division_par_na = False

    def ev(n):
        nonlocal vu_na, vu_valeur, division_par_na
        if isinstance(n, Num):
            return n.valeur
        if isinstance(n, Ref):
            v = valeurs[n]
            if v is NA:
                vu_na = True
                return Decimal(0)
            if isinstance(v, int) and not isinstance(v, bool):
                v = Decimal(v)
            if not isinstance(v, Decimal):  # oui / non, liste (texte ou décompte) : pas un nombre
                raise ErreurCalcul(libelle("messages.formule.non_numerique", kpi=n.kpi))
            vu_valeur = True
            return v
        if isinstance(n, Neg):
            return -ev(n.arg)
        a = ev(n.gauche)
        na_avant, vu_na = vu_na, False
        b = ev(n.droite)
        na_diviseur, vu_na = vu_na, na_avant or vu_na  # le diviseur vient-il d'une source N/A ?
        if n.op == "+":
            return a + b
        if n.op == "-":
            return a - b
        if n.op == "*":
            return a * b
        if b == 0:
            # division par une source N/A (comptée comme 0) : N/A ; par un vrai zéro : erreur, même si une autre
            # source de la formule est N/A (sinon le résultat dépendrait de l'ordre des termes)
            if na_diviseur:
                division_par_na = division_par_na or na_zero
                return Decimal(0)
            if a == 0:  # 0 / 0 (ex. aucun accident sur aucune heure travaillée) : 0, convention du produit
                return Decimal(0)
            raise ErreurCalcul(libelle("messages.formule.division_zero"))
        try:
            return a / b
        except InvalidOperation as e:  # pragma: no cover
            raise ErreurCalcul(str(e))

    resultat = ev(arbre)
    if division_par_na:
        return NA
    if not vu_na:
        return resultat
    return resultat if na_zero and vu_valeur else NA
