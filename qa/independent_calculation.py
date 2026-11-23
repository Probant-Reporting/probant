"""Second, independent calculation of the KPI values (used by qa/calculation_fuzz.py).

Written from the rules of README.md ("Calculation rules", "Aggregation over time") without importing the tool's engine
(collecte/calcul.py), its formula parser (referentiel/formule.py) or Django. It works on a case described as plain data
(see ``qa/calculation_fuzz.py``, ``generate``) and computes, in exact arithmetic (fractions), the value of each cell
that the tool calculates, aggregates or cumulates: a value, N/A, incomplete or error.

The tool works with decimals (28 significant digits) and stores 10 decimals (SQLite: 15 significant digits). A value
that the tool cannot hold exactly is marked "inexact"; when a decision depends on such a value being exactly zero (a
division by zero, 0 / 0), the cell is "not verifiable" (IMPRECISE) instead of a false difference.
"""
# Commentaires en français (règles du projet) ; identifiants en français comme le reste du code.
import datetime
import re
from collections import Counter
from fractions import Fraction

NA = "NA"
IMPRECIS = "IMPRECIS"  # valeur que la précision des décimaux de l'outil ne permet pas de vérifier
MAXV = Fraction(10) ** 15
MOIS_PAR = {"annee": 12, "semestre": 6, "trimestre": 3, "mois": 1}
FINESSE = {"mois": 1, "trimestre": 2, "semestre": 3, "annee": 4}


class Nombre:
    """Valeur numérique exacte, et si l'outil la tient exactement (décimaux à 28 chiffres, base à 10 décimales)."""

    __slots__ = ("v", "exact")

    def __init__(self, v, exact=True):
        self.v = Fraction(v)
        self.exact = exact and representable(self.v)

    def __repr__(self):
        return f"{float(self.v)!r}{'' if self.exact else '~'}"


def representable(f, chiffres=28):
    """Vrai si la fraction s'écrit exactement en décimal avec au plus ``chiffres`` chiffres significatifs."""
    d = f.denominator
    while d % 2 == 0:
        d //= 2
    while d % 5 == 0:
        d //= 5
    if d != 1:
        return False
    if f == 0:
        return True
    n, e = abs(f.numerator), 0
    den = f.denominator
    # nombre de décimales nécessaires
    while den != 1:
        n *= 10
        e += 1
        g = gcd_(n, den)
        n //= g
        den //= g
    s = str(n).rstrip("0") or "0"
    return len(s) <= chiffres


def gcd_(a, b):
    while b:
        a, b = b, a % b
    return a


def arrondi_base(f):
    """Valeur relue en base : 15 chiffres significatifs (SQLite), puis 10 décimales (arrondi au pair, comme quantize)."""
    if f == 0:
        return f
    from decimal import Context, Decimal, ROUND_HALF_EVEN

    d = Context(prec=15).create_decimal(Decimal(f.numerator) / Decimal(f.denominator))
    d = d.quantize(Decimal("1e-10"), rounding=ROUND_HALF_EVEN)
    return Fraction(d)


# ---------------------------------------------------------------- formules (analyse propre, indépendante)
class FormuleIllisible(Exception):
    pass


def jetons(t):
    out, i = [], 0
    while i < len(t):
        ch = t[i]
        if ch.isspace():
            i += 1
        elif ch == "[":
            j = t.find("]", i)
            if j < 0 or "[" in t[i + 1:j]:
                raise FormuleIllisible("crochet")
            out.append(("R", t[i + 1:j]))
            i = j + 1
        elif ch.isdigit():
            m = re.match(r"\d+(\.\d+)?", t[i:])
            out.append(("N", Fraction(m.group(0))))
            i += len(m.group(0))
        elif ch in "+-*/()":
            out.append(("O", ch))
            i += 1
        else:
            raise FormuleIllisible("caractère " + ch)
    return out


def lire_reference(texte):
    code, at, dec = texte.partition("@")
    code, dec = code.strip(), dec.strip()
    if not code or "@" in dec:
        raise FormuleIllisible("référence")
    if not at:
        return code, "N"
    if dec in ("N", "N-1", "P-1") or re.fullmatch(r"\d{4}", dec):
        return code, dec
    raise FormuleIllisible("décalage")


def analyser(t):
    """Arbre en tuples : ("ref", code, décalage) | ("num", F) | ("neg", a) | (op, a, b)."""
    js, pos = jetons(t), [0]
    if not js:
        raise FormuleIllisible("vide")

    def voir():
        return js[pos[0]] if pos[0] < len(js) else (None, None)

    def prendre():
        pos[0] += 1
        return js[pos[0] - 1] if pos[0] - 1 < len(js) else (None, None)

    def expression():
        a = terme()
        while voir() in (("O", "+"), ("O", "-")):
            a = (prendre()[1], a, terme())
        return a

    def terme():
        a = facteur()
        while voir() in (("O", "*"), ("O", "/")):
            a = (prendre()[1], a, facteur())
        return a

    def facteur():
        k, v = prendre()
        if k == "R":
            return ("ref",) + lire_reference(v)
        if k == "N":
            return ("num", v)
        if (k, v) == ("O", "-"):
            return ("neg", facteur())
        if (k, v) == ("O", "("):
            a = expression()
            if prendre() != ("O", ")"):
                raise FormuleIllisible("parenthèse")
            return a
        raise FormuleIllisible("élément inattendu")

    a = expression()
    if pos[0] != len(js):
        raise FormuleIllisible("reste")
    return a


def references(a, out=None):
    out = [] if out is None else out
    if a[0] == "ref":
        if a not in out:
            out.append(a)
    elif a[0] == "neg":
        references(a[1], out)
    elif a[0] in ("+", "-", "*", "/"):
        references(a[1], out)
        references(a[2], out)
    return out


class Erreur(Exception):
    pass


def evaluer(a, valeurs, na_zero):
    """README : une source manquante rend incomplet (avant tout le reste) ; une source N/A rend le résultat N/A (case
    « N/A compte comme 0 » : elle compte 0, et le résultat n'est N/A que si toutes les sources le sont) ; 0 / 0 = 0 ;
    toute autre division par un vrai zéro est une erreur, quel que soit l'ordre des termes et même si une source est
    N/A ; diviser par une source N/A donne N/A. ``valeurs`` : {ref: Nombre | NA | None | IMPRECIS | texte}.
    Renvoie (résultat, raison) : Nombre, NA, None (incomplet), IMPRECIS ; lève Erreur."""
    refs = references(a)
    if any(valeurs[r] is None for r in refs):
        return None
    if any(valeurs[r] is IMPRECIS for r in refs):
        return IMPRECIS
    if any(not (valeurs[r] is NA or isinstance(valeurs[r], Nombre)) for r in refs):
        raise Erreur("source non numérique")
    etat = {"div_na": False, "imprecis": False}

    def ev(n):  # (Fraction, exact, issu d'une source N/A)
        t = n[0]
        if t == "num":
            return n[1], True, False
        if t == "ref":
            v = valeurs[n]
            return (Fraction(0), True, True) if v is NA else (v.v, v.exact, False)
        if t == "neg":
            x, e, f = ev(n[1])
            return -x, e, f
        x, ex, fx = ev(n[1])
        y, ey, fy = ev(n[2])
        if t in "+-*":
            r = x + y if t == "+" else x - y if t == "-" else x * y
            return r, ex and ey and representable(r), fx or fy
        if y == 0:
            if not ey:
                etat["imprecis"] = True
            if fy:  # diviseur venu d'une source N/A
                etat["div_na"] = True
                return Fraction(0), True, True
            if x == 0:
                if not ex:
                    etat["imprecis"] = True
                return Fraction(0), True, fx
            raise Erreur("division par zéro")
        if not ey and abs(y) < Fraction(1, 10 ** 12):
            etat["imprecis"] = True
        r = x / y
        return r, ex and ey and representable(r), fx or fy

    try:
        v, exact, _ = ev(a)
    except Erreur:
        if etat["imprecis"]:
            return IMPRECIS
        raise
    if etat["imprecis"]:
        return IMPRECIS
    nas = [r for r in refs if valeurs[r] is NA]
    if etat["div_na"] and nas:
        # sans la case, n'importe quelle source N/A rend N/A ; avec la case, diviser par une source N/A : N/A
        return NA
    if nas and (not na_zero or len(nas) == len(refs)):
        return NA
    return Nombre(v, exact)


# ---------------------------------------------------------------- périodes
def ajouter_mois(d, n):
    a, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return datetime.date(a, m + 1, 1)


class Periode:
    def __init__(self, type_, debut, statut, fermees=()):
        self.type, self.debut, self.statut = type_, debut, statut
        self.fin = ajouter_mois(debut, MOIS_PAR[type_]) - datetime.timedelta(days=1)
        # campagnes clôturées de la période : (référentiel, début) ; « bis » pour le second référentiel annuel
        self.fermees = tuple(fermees)

    @property
    def cle(self):
        return (self.type, self.debut)

    def __repr__(self):
        return f"{self.type}:{self.debut:%Y-%m}"


# ---------------------------------------------------------------- calcul
class Oracle:
    """Second calcul d'un cas. ``cas`` : dictionnaire de qa/calculation_fuzz.py. ``memoire_figee`` : valeurs enregistrées
    des périodes figées (un autre Oracle : celui des valeurs au moment où elles ont été calculées)."""

    def __init__(self, cas, saisies=None, memoire_figee=None, stockees=None, refaites=None):
        self.cas = cas
        self.kpis = {k["code"]: k for k in cas["kpis"]}
        self.orgs = {o["id"]: o for o in cas["orgs"]}
        # README : une période close, ou rouverte en gardant les chiffres de l'époque, se calcule
        # avec l'arbre des organisations de sa clôture (``closure_orgs`` : l'arbre noté quand les périodes closes du cas
        # l'ont été) ; toute autre période avec l'arbre d'aujourd'hui
        self.orgs_cloture = {o["id"]: o for o in cas["closure_orgs"]} if cas.get("closure_orgs") else self.orgs
        # README : une deuxième clôture après « garder » garde l'arbre de la première ; après « recalculer avec
        # l'organisation d'aujourd'hui », la clôture suivante note l'arbre de ce jour (``closure_orgs_by_period`` :
        # l'arbre d'une période reclôturée ainsi, à la place de ``closure_orgs``)
        self.orgs_cloture_par = {tuple_cle(c): {o["id"]: o for o in liste}
                                 for c, liste in (cas.get("closure_orgs_by_period") or {}).items()}
        for o in list(self.orgs.values()) + list(self.orgs_cloture.values()) + [
                x for arbre in self.orgs_cloture_par.values() for x in arbre.values()]:
            o["_fin"] = datetime.date.fromisoformat(o["closed"]) if o.get("closed") else None
            o["_debut"] = datetime.date.fromisoformat(o["opened"]) if o.get("opened") else None
        # valeurs enregistrées des périodes figées refaites par une correction : {(k, o, clé période): (statut, valeur)}
        self.stockees = stockees or {}
        # période figée corrigée (README, correction importée et réouverture « garder ») : {clé période: (KPI refaits, organisations
        # refaites ou None pour toutes)} ; toute autre case de la période est lue telle qu'enregistrée
        self.refaites = refaites or {}
        self.periodes = {}
        self.bis = set()  # périodes qui ont aussi une campagne du second référentiel annuel (« bis »)
        for p in cas["periods"]:
            debut = datetime.date.fromisoformat(p["debut"])
            fermees = ([(p["type"], debut)] if p["status"] == "cloturee" else []) + (
                [("bis", debut)] if p.get("bis") == "cloturee" else [])
            q = Periode(p["type"], debut, statut_effectif(p), fermees)
            self.periodes[q.cle] = q
            if p.get("bis"):
                self.bis.add(q.cle)
        self.saisies = {}  # (k, o, cle période) -> (origine, valeur)
        for s in (cas["inputs"] if saisies is None else saisies):
            self.saisies[(s["k"], s["o"], tuple_cle(s["p"]))] = (s["origin"], lire_valeur(s["v"]))
        self.memoire_figee = memoire_figee
        self.memo = {}
        self.erreurs = set()
        # fréquence la plus fine des référentiels qui contiennent le KPI (tous les référentiels du cas sont actifs)
        self.freq = {}
        for k in cas["kpis"]:
            # « autre » : référentiel annuel sans campagne ; « bis » : second référentiel annuel (fréquence de l'année)
            fs = ["annee" if f == "bis" else f for f in k.get("freqs") or [] if f in FINESSE or f == "bis"]
            self.freq[k["code"]] = min(fs, key=FINESSE.get) if fs else ("annee" if k.get("freqs") else None)
        self._perimetres = {}
        self._demandes = {}  # {(fréquence, début): KPI demandés dans cette période courte}
        # README (règle « Figer ses chiffres ») : KPI figés par une campagne clôturée d'une
        # période dont une autre campagne ne l'est pas, notés quand la campagne a été clôturée (``partial_frozen`` : la
        # note faite après le premier calcul du cas, ``a_figer`` ; sans elle, rien n'est encore figé à part : c'est le
        # calcul d'avant la clôture, celui dont ces KPI gardent les chiffres)
        self._gelees = None if "partial_frozen" not in cas else {
            tuple_cle(c): frozenset(v) for c, v in (cas.get("partial_frozen") or {}).items()}

    def perimetre(self, p):
        """README (étendue aux années, semestres et trimestres) : une
        période ne calcule que les KPI du périmètre de ses campagnes et de celles des périodes plus courtes qu'elle
        contient (chaque période d'un cas a une campagne du référentiel de sa fréquence) : KPI de ces référentiels que
        chacun demande dans la période de sa campagne (« demandé depuis »: date vide, ou début
        de cette période à cette date ou après), pour une période plus longue qu'un mois aussi les KPI hors de tout
        référentiel, et les sources de leurs formules, de proche en proche ; None : tout le catalogue (aucun KPI dans
        aucun référentiel). Lu dans le texte des formules, sans le code de l'outil."""
        if not any(k.get("freqs") for k in self.cas["kpis"]):
            return None
        campagnes = frozenset({(p.type, p.debut)} | {(q.type, q.debut) for q in self.periodes.values()
                                                       if FINESSE[q.type] < FINESSE[p.type] and q.debut >= p.debut and q.fin <= p.fin}
                              | ({("bis", p.debut)} if p.cle in self.bis else set()))
        cle = (p.type == "mois", campagnes)
        if cle not in self._perimetres:
            self._perimetres[cle] = self._perimetre(campagnes, p.type != "mois")
        return self._perimetres[cle]

    def _perimetre(self, campagnes, orphelins):
        sources = {k["code"]: set(re.findall(r"\[\s*(K\d+)", k.get("formula") or "")) for k in self.cas["kpis"]}

        def demande(k, f):
            d = (k.get("depuis") or {}).get(f)
            return any(t == f and (d is None or debut >= datetime.date.fromisoformat(d)) for t, debut in campagnes)

        utiles = {k["code"] for k in self.cas["kpis"] if any(demande(k, f) for f in k.get("freqs") or [])
                  or (orphelins and not k.get("freqs"))}
        pile = list(utiles)
        while pile:
            for s in sources.get(pile.pop(), ()):
                if s not in utiles:
                    utiles.add(s)
                    pile.append(s)
        return utiles

    def a_figer(self, p):
        """README (« Figer ses chiffres ») : dans une période non figée dont une campagne est clôturée, les KPI
        que demande cette campagne (ses KPI demandés dans la période, « demandé depuis », et les sources de leurs
        formules, de proche en proche : la règle des cases offertes, la même que celle qui bloque la saisie) gardent leurs chiffres."""
        if p.statut in ("cloturee", "gardee") or not p.fermees:
            return frozenset()
        return frozenset(self._perimetre(frozenset(p.fermees), False))

    def gelees(self, p):
        """KPI figés à part dans la période (note ``partial_frozen``, faite d'après ``a_figer``) ; vide pour une période
        figée (tout y est figé) ou sans note."""
        if self._gelees is None or p.statut in ("cloturee", "gardee"):
            return frozenset()
        return self._gelees.get(p.cle, frozenset())

    def figee_kpi(self, p, k):
        """Vrai si le KPI garde ses chiffres sur la période : période figée, ou KPI figé par une campagne clôturée."""
        return self.figee(p) or k in self.gelees(p)

    def origine_d_un_import(self, p, k):
        """README (« Formulas, N/A, and errors », import d'un KPI calculé) : ce que devient un chiffre importé (et
        confirmé) sur la case d'un KPI calculé. Période non clôturée, KPI pas figé par une campagne clôturée de la
        période : une valeur forcée (« forcee »), qui tient la case et remonte dans les totaux et les formules
        ([X@N-1] compris). Période clôturée ou KPI figé : None, l'import l'ignore (l'historique ne touche pas aux
        calculs). Aucun chiffre importé « en sommeil » ne naît plus dans une période ouverte."""
        if self.kpis[k]["comp"] != "calcul" or self.figee(p) or k in self.a_figer(p) or k in self.gelees(p):
            return None
        return "forcee"

    # -- arbre ------------------------------------------------------------------
    def arbre(self, p=None, k=None):
        """Organisations de l'arbre que suit la période : celui de la clôture si elle est figée, sinon celui d'aujourd'hui.
        Pour un KPI figé par une campagne clôturée : l'arbre du jour où il l'a été (celui de la clôture dans les cas)."""
        if p is not None and (self.figee(p) or (k is not None and k in self.gelees(p))):
            if self.figee(p) and p.cle in self.orgs_cloture_par:
                return self.orgs_cloture_par[p.cle]
            return self.orgs_cloture
        return self.orgs

    def rang(self, o, p=None, k=None):
        return self.arbre(p, k)[o]["rank"]

    def ouverte(self, o, p, k=None):
        orgs = self.arbre(p, k)
        if o not in orgs:  # créée depuis la clôture : n'existe pas dans cette période
            return False
        x = orgs[o]
        if x.get("_debut") is not None and x["_debut"] > p.fin:  # README : ne compte qu'à partir de sa date d'ouverture
            return False
        if not (x["active"] or (x["_fin"] is not None and x["_fin"] >= p.debut)):
            return False
        a = x["parent"]  # README : une organisation n'est pas ouverte avant son parent (seule la date d'ouverture remonte)
        while a is not None:
            y = orgs[a]
            if y.get("_debut") is not None and y["_debut"] > p.fin:
                return False
            a = y["parent"]
        return True

    def enfants(self, o, p, k=None):
        return [e for e, x in self.arbre(p, k).items() if x["parent"] == o and self.ouverte(e, p, k)]

    def descendants(self, o, p=None, k=None):
        orgs = self.arbre(p, k)
        pile, out = [o], []
        while pile:
            x = pile.pop()
            out.append(x)
            pile += [e for e, y in orgs.items() if y["parent"] == x]
        return out

    def a_du_detail(self, o, rk, p, k=None):
        """README : l'organisation a, en dessous d'elle (par les organisations ouvertes), une organisation du niveau du KPI."""
        if self.rang(o, p, k) == rk:
            return True
        return any(self.a_du_detail(e, rk, p, k) for e in self.enfants(o, p, k))

    def a_des_valeurs(self, o, p, k=None):
        """Une valeur (saisie, importée, forcée, N/A compris) sur la période, pour elle ou une organisation en dessous
        (dans l'arbre que suit le KPI ``k``)."""
        d = set(self.descendants(o, p, k))
        # une ancienne saisie d'un KPI devenu calculé (période non figée, KPI non figé) est remplacée par le calcul : pas
        # une valeur
        return any(oo in d and cp == p.cle and v is not None
                   and not (origine == "saisie" and self.kpis[kk]["comp"] == "calcul" and not self.figee_kpi(p, kk))
                   for (kk, oo, cp), (origine, v) in self.saisies.items())

    def valeurs_dans_les_mois(self, o, k, p):
        """README (« everything counts ») : pour un KPI cumulé depuis des périodes plus courtes, une valeur de
        l'organisation (ou d'une organisation en dessous, dans l'arbre de la période courte) dans l'une d'elles compte
        comme une valeur de la période."""
        f = self.freq[k]
        return any(q.type == f and q.debut >= p.debut and q.fin <= p.fin and self.a_des_valeurs(o, q, k)
                   for q in self.periodes.values())

    def porteur(self, k, o, p=None):
        """Paramètre hérité, sous sa granularité : l'ancêtre de ce niveau ; à défaut, la plus haute organisation de la
        lignée encore sous ce niveau (elle porte sa propre valeur). Dans l'arbre que suit la période."""
        rk, orgs = self.kpis[k]["gran"], self.arbre(p, k)
        x = o
        while True:
            par = orgs[x]["parent"]
            if par is None or orgs[par]["rank"] < rk:
                return x
            if orgs[par]["rank"] == rk:
                return par
            x = par

    def figee(self, p):
        """Close, ou rouverte en gardant les chiffres de l'époque (« gardee »)."""
        return p.statut in ("cloturee", "gardee")

    # -- périodes ---------------------------------------------------------------
    def cible(self, p, dec):
        if dec == "N":
            return p
        if dec == "N-1":
            d = ajouter_mois(p.debut, -12)
        elif dec == "P-1":
            d = ajouter_mois(p.debut, -MOIS_PAR[p.type])
        else:  # README : [ID@2021] = même période de l'exercice qui commence en 2021 (exercice décalé)
            m = self.cas.get("mois_debut", 1)
            exercice = p.debut.year if p.debut.month >= m else p.debut.year - 1
            d = ajouter_mois(p.debut, 12 * (int(dec) - exercice))
        return self.periodes.get((p.type, d))

    def cumule(self, k, p):
        kp = self.kpis[k]
        f = self.freq[k]
        return (kp["comp"] != "calcul" and kp["temps"] != "aucune" and kp.get("fmt") not in ("texte", "tableau") and f is not None
                and FINESSE[f] < FINESSE[p.type])

    # -- valeurs -------------------------------------------------------------------
    def saisie(self, k, o, p):
        s = self.saisies.get((k, o, p.cle))
        return (None, None) if s is None else s

    def lire(self, courante, k, o, p):
        """Valeur d'une case vue depuis le calcul de la période ``courante``. Une autre période figée : la valeur
        enregistrée (README : « A frozen period … prevails as saved »), relue en base. Dans une période figée corrigée,
        une case qui n'est pas refaite est lue de même."""
        r = self.refaites.get(p.cle)
        meme = p.cle == courante.cle
        if self.figee(p):
            enregistree = not meme or (r is not None and r[1] is not None and not (k in r[0] and o in r[1]))
        else:  # KPI figé par une campagne clôturée : lu tel qu'enregistré, hors des cases qu'une correction refait
            enregistree = k in self.gelees(p) and (
                not meme or not (r is not None and k in r[0] and (r[1] is None or o in r[1])))
        if enregistree:
            origine, v = self.saisie(k, o, p)  # saisies relues en base (une correction compte)
            if origine is not None and v is not None:
                return v
            if (k, o, p.cle) in self.stockees:  # case refaite par une correction précédente, enregistrée
                return self.stockees[(k, o, p.cle)][1]
            source = self.memoire_figee or self  # la période figée telle qu'elle a été calculée (avant les changements)
            if source.produite(k, o, p):
                v = source.valeur(p, k, o, p)
                if isinstance(v, Nombre):
                    r = arrondi_base(v.v)
                    return Nombre(r, v.exact and r == v.v)
                return v
        return self.valeur(courante, k, o, p)

    def valeur(self, courante, k, o, p):
        cle = (courante.cle, k, o, p.cle)
        if cle not in self.memo:
            self.memo[cle] = None  # garde-fou (boucle)
            v = self._valeur(courante, k, o, p)
            if isinstance(v, Nombre) and abs(v.v) >= MAXV:
                if not v.exact and abs(abs(v.v) - MAXV) < 1:
                    v = IMPRECIS
                else:
                    self.erreurs.add(cle)
                    v = None
            self.memo[cle] = v
        return self.memo[cle]

    def _valeur(self, c, k, o, p):
        if o not in self.arbre(p, k):  # créée depuis la clôture : rien dans cette période
            return None
        kp, rk, ro = self.kpis[k], self.kpis[k]["gran"], self.rang(o, p, k)
        origine, saisie = self.saisie(k, o, p)
        if kp["comp"] == "calcul" and origine == "forcee":
            return saisie
        if self.figee_kpi(p, k) and origine == "import" and saisie is not None:
            return saisie  # README : dans une période clôturée, le chiffre importé est le chiffre officiel
        propre = ro == rk
        if ro > rk:
            if kp["comp"] != "herite":
                return None
            x = self.porteur(k, o, p)
            if x != o:
                if p.cle != c.cle and not self.ouverte(x, p, k):
                    return None  # lu depuis une autre période : le porteur doit y être ouvert 
                return self.lire(c, k, x, p)
            propre = True
        if kp["comp"] in ("saisie", "herite"):
            if propre:
                if saisie is None and self.cumule(k, p):
                    return self.cumul(c, k, o, p)
                return saisie
            if kp.get("above") and kp["comp"] == "saisie":
                if saisie is not None:
                    return saisie  # saisie au-dessus : remplace le total
                if self.cumule(k, p):
                    v = self.agreger(c, k, o, p)
                    return self.cumul(c, k, o, p) if v is None else v
            v = self.agreger(c, k, o, p)
            if v is None and origine == "import" and saisie is not None:
                return saisie  # total publié par un fichier historique : vaut quand le détail manque
            return v
        # calculé
        if propre or kp["agg"] == "Formule":
            v = self.formule(c, k, o, p)
        elif kp["agg"] == "Somme":
            v = self.agreger(c, k, o, p)
            if v is None and self.sources_au_dessus(k):
                v = self.formule(c, k, o, p)  # README : un KPI calculé en somme refait sa formule à ce niveau
        else:
            v = None
        if v is None and saisie is not None and (origine == "import" or self.figee_kpi(p, k)):
            return saisie
        return v

    def sources_au_dessus(self, k):
        try:
            a = analyser(self.kpis[k]["formula"])
        except FormuleIllisible:
            return False
        return any(self.kpis[r[1]].get("above") and self.kpis[r[1]]["comp"] == "saisie" for r in references(a) if r[1] in self.kpis)

    def formule(self, c, k, o, p):
        kp = self.kpis[k]
        try:
            a = analyser(kp["formula"])
        except FormuleIllisible:
            self.erreurs.add((c.cle, k, o, p.cle))
            return None
        valeurs = {}
        for r in references(a):
            q = self.cible(p, r[2])
            if q is not None and q.cle != p.cle and r[1] in self.kpis and not self.ouverte(o, q, r[1]) and not (
                    self.kpis[r[1]]["comp"] == "herite" and o in self.arbre(q, r[1])
                    and self.rang(o, q, r[1]) > self.kpis[r[1]]["gran"] and self.porteur(r[1], o, q) != o):
                # README : une période où l'organisation n'est pas ouverte ne se lit pas (une
                # valeur gardée d'avant son ouverture ne compte nulle part) ; un paramètre hérité se lit chez son porteur
                valeurs[r] = None
                continue
            valeurs[r] = None if q is None or r[1] not in self.kpis else self.lire(c, r[1], o, q)
        try:
            return evaluer(a, valeurs, kp.get("na0", False))
        except Erreur:
            self.erreurs.add((c.cle, k, o, p.cle))
            return None

    def agreger(self, c, k, o, p):
        kp = self.kpis[k]
        if kp["agg"] not in ("Somme", "Décompte"):
            return None
        rk = kp["gran"]
        gardes = []
        for e in self.enfants(o, p, k):
            if self.rang(e, p, k) > rk:
                continue  # rattachée sous la granularité : pas de valeur propre
            v = self.lire(c, k, e, p)
            if v is None:
                if not self.a_du_detail(e, rk, p, k):
                    continue  # rien à saisir en dessous
                if not self.arbre(p, k)[e]["active"] and not self.a_des_valeurs(e, p, k) and not (
                        self.cumule(k, p) and self.valeurs_dans_les_mois(e, k, p)):
                    continue  # fermée pendant la période sans aucune valeur (ni dans les mois d'un KPI cumulé)
            gardes.append(v)
        if not gardes or any(v is None for v in gardes):
            return None
        if any(v is IMPRECIS for v in gardes):
            return IMPRECIS
        pleines = [v for v in gardes if v is not NA]
        if not pleines:
            return NA
        if kp["agg"] == "Décompte":
            total = Counter()
            for v in pleines:
                total.update(v if isinstance(v, Counter) else {v: 1})
            return total
        return Nombre(sum((v.v for v in pleines), Fraction(0)), all(v.exact for v in pleines))

    def cumul(self, c, k, o, p):
        kp = self.kpis[k]
        f = self.freq[k]
        n = MOIS_PAR[f]
        valeurs = []
        for i in range(MOIS_PAR[p.type] // n):
            d = ajouter_mois(p.debut, i * n)
            q = self.periodes.get((f, d))
            # README : un site fermé compte pour les mois où il était ouvert, un site ouvert en cours d'année à partir de
            # son ouverture : seuls les mois (trimestres) où l'organisation est ouverte entrent dans le cumul ; un mois
            # qui n'existe pas encore se lit avec l'arbre d'aujourd'hui
            if not self.ouverte(o, q if q is not None else Periode(f, d, "ouverte"), k):
                continue
            # README (« Requested since ») : un mois n'est sauté que si AUCUN référentiel ne
            # demande le KPI dans sa propre période qui contient ce mois : le mois lui-même pour un référentiel de cette
            # fréquence ; pour un référentiel moins fréquent, son trimestre, semestre ou exercice entier, et seulement
            # s'il a une campagne sur cette période (une période du cas) ; une source d'un KPI demandé l'est avec lui
            if not self.mois_demande(k, f, d):
                continue
            v = None if q is None else self.lire(c, k, o, q)
            valeurs.append(v)
        if not valeurs or any(v is None for v in valeurs):
            return None
        if any(v is IMPRECIS for v in valeurs):
            return IMPRECIS
        if kp["temps"] == "derniere" or kp["fmt"] not in ("nombre", "pourcentage"):
            return valeurs[-1]
        pleines = [v for v in valeurs if v is not NA]
        if not pleines:
            return NA
        total = sum((v.v for v in pleines), Fraction(0))
        exact = all(v.exact for v in pleines)
        if kp["temps"] == "moyenne":
            return Nombre(total / len(pleines), exact)
        return Nombre(total, exact)

    def mois_demande(self, k, f, d):
        """Vrai si la période courte de fréquence ``f`` qui commence le ``d`` entre dans un cumul pour le KPI ``k`` (voir
        ``cumul``). Écrit d'après le README, sans le code de l'outil."""
        m = self.cas.get("mois_debut", 1)
        for g in sorted({g for kk in self.cas["kpis"] for g in kk.get("freqs") or [] if g in FINESSE or g == "bis"}):
            t = "annee" if g == "bis" else g  # second référentiel annuel : une campagne sur l'exercice
            if FINESSE[t] <= FINESSE[f]:
                debut = d
            else:  # période du référentiel g qui contient d : exercice (début au mois m), découpé en périodes de g
                ex = datetime.date(d.year if d.month >= m else d.year - 1, m, 1)
                debut = next(x for x in (ajouter_mois(ex, i * MOIS_PAR[t]) for i in range(12 // MOIS_PAR[t]))
                             if x <= d < ajouter_mois(x, MOIS_PAR[t]))
                if g == "bis" and ("annee", debut) not in self.bis:
                    continue  # pas de campagne du second référentiel sur cet exercice
                if g != "bis" and (g, debut) not in self.periodes:  # pas de campagne de ce référentiel sur cette période
                    continue
            if (g, debut) not in self._demandes:
                self._demandes[(g, debut)] = self._perimetre(frozenset({(g, debut)}), False)
            if k in self._demandes[(g, debut)]:
                return True
        return False

    def comparable(self, k, o, p):
        """README : la valeur de ``k`` pour ``o`` dans la période ``p`` sert de comparaison
        (N-1, période précédente) si l'organisation y est ouverte, dans l'arbre de cette période (la règle du calcul pour
        une autre période). Le périmètre noté à la clôture (KPI sans case) n'est pas lu ici : ``verifier`` ne compare que
        des périodes jamais closes ; la date « demandé depuis » seule ne retire pas la comparaison."""
        return self.ouverte(o, p, k)

    # -- cases produites --------------------------------------------------------------
    def porte_lui_meme(self, k, o, p=None):
        rk, orgs = self.kpis[k]["gran"], self.arbre(p, k)
        if orgs[o]["rank"] <= rk:
            return False
        par = orgs[o]["parent"]
        return par is None or orgs[par]["rank"] < rk

    def produite(self, k, o, p):
        """README : cases calculées (niveau du KPI calculé), agrégées (au-dessus, selon l'agrégation) et cumulées dans
        le temps (niveau du KPI saisi, ou organisation qui porte elle-même un paramètre hérité), pour les KPI actifs et les
        organisations ouvertes pendant la période."""
        kp = self.kpis[k]
        # texte rédigé, tableau (enregistré en tableau Markdown) : jamais calculés
        if not kp["active"] or not self.ouverte(o, p, k) or kp.get("fmt") in ("texte", "tableau"):
            return False
        perimetre = self.perimetre(p)
        if perimetre is not None and k not in perimetre:
            return False  # hors du périmètre des campagnes de la période
        ro, rk = self.rang(o, p, k), kp["gran"]
        if kp["comp"] == "calcul":
            return ro == rk or (ro < rk and kp["agg"] != "Aucune")
        if (ro == rk or (kp["comp"] == "herite" and self.porte_lui_meme(k, o, p))) and self.cumule(k, p):
            return True
        return ro < rk and kp["agg"] in ("Somme", "Décompte")

    def bloquee(self, k, o, p):
        """Case produite mais tenue par une saisie : valeur importée ou forcée, ou saisie (KPI saisi, ou période figée)."""
        origine, v = self.saisie(k, o, p)
        if origine in ("import", "forcee"):
            return True
        return origine == "saisie" and v is not None and (self.kpis[k]["comp"] != "calcul" or self.figee_kpi(p, k))

    def attendu(self, k, o, p):
        """(statut, valeur) attendus d'une case produite : ("calcule", Nombre | texte | Counter), ("na", None),
        ("incomplet", None), ("erreur", None), ("imprecis", None)."""
        v = self.valeur(p, k, o, p)
        if v is IMPRECIS:
            return "imprecis", None
        if v is None:
            return ("erreur" if (p.cle, k, o, p.cle) in self.erreurs else "incomplet"), None
        if v is NA:
            return "na", None
        return "calcule", v


def statut_effectif(p):
    """Statut de la période d'après ses campagnes (README : figée si toutes ses campagnes sont clôturées, ou si l'une est
    rouverte en gardant les chiffres de l'époque) : la campagne de son référentiel, et celle du second référentiel annuel
    (« bis ») quand elle en a une."""
    statuts = [p["status"]] + ([p["bis"]] if p.get("bis") else [])
    if "gardee" in statuts:
        return "gardee"
    if all(st == "cloturee" for st in statuts):
        return "cloturee"
    return next(st for st in statuts if st != "cloturee")


def tuple_cle(p):
    t, d = p.split(":")
    return t, datetime.date.fromisoformat(d)


def lire_valeur(v):
    if v is None:
        return None
    if v == "NA":
        return NA
    if isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v):
        return Nombre(Fraction(v))
    return v  # oui / non, liste
