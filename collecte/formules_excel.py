"""Formules Excel du « Tableau lisible » (option « Valeurs calculées : en formules Excel » du constructeur d'export).

Dans un onglet (une période), une ligne par KPI et une colonne par organisation. Une case calculée par l'outil devient
une formule qui cite les cases de ses sources, pour suivre et refaire les calculs dans Excel :
- KPI calculé (à sa granularité, ou agrégation « Formule » au-dessus) : sa formule de l'outil, chaque [ID] remplacé par
  la case du KPI cité dans la même colonne ; un facteur d'émission hérité : la case de l'organisation qui le porte ;
- total d'un KPI agrégé par somme : SUM des cases des organisations enfants comptées par le moteur (ouvertes pendant la
  période, pas sous la granularité du KPI, avec une valeur ; N/A en texte, que SUM ignore comme le moteur) ;
- division : ``IF(AND(a=0,b=0),0,a/b)`` (0 / 0 = 0, toute autre division par zéro reste une erreur, comme l'outil) ;
  une source N/A comptée comme 0 (case de la fiche KPI) : ``N(case)``.

Mêmes règles que le moteur (``collecte.calcul``, qui fait foi). Jamais une formule fausse : chaque formule est d'abord
évaluée ici comme Excel le fera (nombres en virgule flottante, case vide = 0, texte dans un calcul = #VALUE!) et n'est
écrite que si elle redonne le chiffre enregistré ; sinon la case garde sa valeur, avec une bulle qui dit pourquoi
(valeur forcée, chiffre importé tel quel, cumul de périodes plus courtes, autre période citée, source absente de
l'export, recalcul différent du chiffre enregistré…). N/A, cases vides et réponses en texte restent des valeurs.
"""

from openpyxl.utils import get_column_letter

from parametres import niveaux as N
from referentiel import formule as F
from referentiel.models import KPI, Organisation, porteur_herite

from .calcul import arbre_periode, figes_partiels, ouverte
from .models import Reponse

LONGUEUR_MAX = 8000  # Excel : 8 192 caractères au plus par formule
ARGUMENTS_MAX = 255  # Excel : 255 arguments au plus par fonction (SUM)
RAISONS = ("saisie_dessus", "importe", "forcee", "cumul", "autre_periode", "source_absente", "ecart", "trop_long")


class Impossible(Exception):
    """La case ne peut pas être une formule fidèle ; ``args[0]`` : la raison (une de ``RAISONS``)."""


def _nombre(x):
    """Valeur d'une case dans un calcul Excel : un nombre, ou une erreur (« #VALUE! »…)."""
    if x is None:
        return 0.0
    if isinstance(x, float):
        return x
    return x if x.startswith("#") else "#VALUE!"


def _erreur(x):
    return isinstance(x, str) and x.startswith("#")


def egal(calcule, enregistre):
    """Le résultat d'Excel (flottant) redonne-t-il le chiffre enregistré (Decimal arrondi à 10 décimales) ?"""
    if not isinstance(calcule, float):
        return False
    e = float(enregistre)
    return abs(calcule - e) <= 1e-9 + 1e-9 * abs(e)


class FormulesOnglet:
    """Formules d'un onglet du tableau lisible.

    ``cases`` : {(code du KPI, identifiant de l'organisation): réponse écrite dans l'onglet (ou None)} ;
    ``rangees`` : {code du KPI: numéro de ligne} ; ``colonnes`` : {identifiant de l'organisation: numéro de colonne}.
    ``contexte`` : données communes aux onglets (``Contexte``)."""

    def __init__(self, periode, cases, rangees, colonnes, contexte):
        self.periode, self.cases, self.rangees, self.colonnes, self.ctx = periode, cases, rangees, colonnes, contexte
        self._lettres = {o: get_column_letter(c) for o, c in colonnes.items()}
        self.stockees = {}  # valeurs enregistrées de la période (même hors de l'export) : Decimal, NA, texte ou None
        for k, o, v, texte, na in Reponse.objects.filter(periode=periode).values_list(
                "kpi_id", "organisation_id", "valeur", "texte", "non_applicable"):
            self.stockees[(k, o)] = F.NA if na else texte if texte else v
        self._decisions = {}
        self._en_cours = set()
        self._enfants = {}
        # arbre de la période (celui de sa clôture pour un exercice clos ou rouvert en gardant les chiffres de l'époque,
        #) : la formule d'un total additionne les mêmes organisations que le moteur
        self.orgs = arbre_periode(periode, contexte.orgs)
        for o in self.orgs.values():
            if o.parent_id and ouverte(o, periode, self.orgs):
                self._enfants.setdefault(o.parent_id, []).append(o)
        # un KPI figé par une campagne clôturée de la période suit l'arbre du jour où il l'a été 
        self._partiels = figes_partiels(periode)
        self._arbres = {None: (self.orgs, self._enfants)}

    def _arbre(self, code):
        """(organisations, enfants ouverts par parent) de l'arbre que suit le KPI sur la période."""
        cle = self._partiels["kpis"].get(code) if self._partiels else None
        if cle not in self._arbres:
            orgs, enfants = arbre_periode(self.periode, self.ctx.orgs, code), {}
            for o in orgs.values():
                if o.parent_id and ouverte(o, self.periode, orgs):
                    enfants.setdefault(o.parent_id, []).append(o)
            self._arbres[cle] = (orgs, enfants)
        return self._arbres[cle]

    # -- cases de l'onglet --------------------------------------------------------
    def _ref(self, code, org_id):
        """« E12 » : case (KPI, organisation) de l'onglet, si elle y est avec une valeur ; sinon None."""
        r = self.cases.get((code, org_id))
        if r is None or code not in self.rangees or org_id not in self.colonnes:
            return None
        if not r.non_applicable and r.valeur is None and not r.texte:
            return None
        return f"{self._lettres[org_id]}{self.rangees[code]}"

    def _valeur_excel(self, code, org_id):
        """Ce qu'Excel lira dans la case : le nombre (résultat de la formule, s'il y en a une), « N/A », un texte."""
        r = self.cases[(code, org_id)]
        if r.non_applicable:
            return "N/A"
        if r.texte or r.valeur is None:
            return r.texte or None
        d = self.decision(code, org_id)
        return d[2] if d[0] else float(r.valeur)

    # -- décision pour une case ---------------------------------------------------
    def decision(self, code, org_id):
        """(formule sans « = » ou None, raison de la valeur écrite ou None, valeur qu'Excel calculera)."""
        cle = (code, org_id)
        if cle not in self._decisions:
            if cle in self._en_cours:  # boucle (ne devrait pas arriver : formules vérifiées) : valeur
                raise Impossible("ecart")
            self._en_cours.add(cle)
            try:
                self._decisions[cle] = self._decider(code, org_id)
            finally:
                self._en_cours.discard(cle)
        return self._decisions[cle]

    def _decider(self, code, org_id):
        r = self.cases.get((code, org_id))
        k, o = self.ctx.kpis.get(code), self._arbre(code)[0].get(org_id)
        if r is None or k is None or o is None or r.non_applicable or r.texte or r.valeur is None or not k.est_numerique:
            return None, None, None
        rang_k, rang_o = self.ctx.rangs[k.granularite_id], self.ctx.rangs[o.niveau_id]
        origine = r.origine
        if origine == Reponse.Origine.FORCEE:
            return None, "forcee", None
        if origine == Reponse.Origine.CUMUL:
            return None, "cumul", None
        if origine == Reponse.Origine.IMPORT:
            return None, ("importe" if k.est_calcule or rang_o < rang_k else None), None
        if origine == Reponse.Origine.SAISIE:
            return None, ("saisie_dessus" if not k.est_calcule and rang_o < rang_k else None), None
        # calcul ou agrégation : comme le moteur (calcul.Calculateur._valeur)
        if k.est_calcule:
            essais = [self._formule] if rang_o == rang_k or k.methode_agregation == KPI.Agregation.FORMULE else \
                [self._somme, self._formule] if k.methode_agregation == KPI.Agregation.SOMME else []
        else:
            essais = [self._somme] if k.methode_agregation == KPI.Agregation.SOMME and rang_o < rang_k else []
        raisons = []  # celle du premier essai est donnée
        for essai in essais:
            try:
                texte, valeur = essai(k, o)
            except Impossible as e:
                raisons.append(e.args[0])
                continue
            if len(texte) > LONGUEUR_MAX:
                raisons.append("trop_long")
            elif egal(valeur, r.valeur):
                return texte, None, valeur
            else:
                raisons.append("ecart")
        return None, (raisons[0] if raisons else "ecart"), None

    # -- total : somme des enfants ------------------------------------------------
    def _somme(self, k, o):
        rang_k = self.ctx.rangs[k.granularite_id]
        refs, total = [], 0.0
        for e in self._arbre(k.code)[1].get(o.id, []):
            if self.ctx.rangs[e.niveau_id] > rang_k:  # rattachée sous la granularité : pas de valeur propre
                continue
            v = self.stockees.get((k.code, e.id))
            if v is None:  # sans valeur : écartée par le moteur (sinon le total serait incomplet)
                continue
            ref = self._ref(k.code, e.id)
            if ref is None:
                raise Impossible("source_absente")
            x = self._valeur_excel(k.code, e.id)
            if _erreur(x):
                raise Impossible("ecart")
            if isinstance(x, float):  # SUM ignore le texte (N/A), comme le moteur
                total += x
            refs.append((self.colonnes[e.id], ref))
        if not refs:
            raise Impossible("ecart")
        if len(refs) > ARGUMENTS_MAX:
            raise Impossible("trop_long")
        refs.sort()  # dans l'ordre des colonnes
        return f"SUM({','.join(r for _, r in refs)})", total

    # -- KPI calculé : sa formule, en cases de la même colonne --------------------
    def _formule(self, k, o):
        try:
            arbre = self.ctx.arbre(k)
        except F.FormuleInvalide:
            raise Impossible("ecart")
        rangs = self.ctx.rangs

        def source(ref):
            if ref.decalage != "N":
                raise Impossible("autre_periode")
            s = self.ctx.kpis.get(ref.kpi)
            if s is None:
                raise Impossible("ecart")
            cible = o
            if s.est_herite and rangs[o.niveau_id] > rangs[s.granularite_id]:
                cible = self.ctx.porteur(s, o, self._arbre(s.code)[0])  # facteur d'émission : la case de l'organisation qui le porte
            case = self._ref(s.code, cible.id)
            if case is None:
                raise Impossible("source_absente")
            x = self._valeur_excel(s.code, cible.id)
            if x == "N/A" and k.na_compte_zero:  # « Une source N/A compte comme 0 » (fiche KPI)
                return f"N({case})", 0.0
            return case, x

        def tr(n):
            """(texte, priorité, valeur) ; priorité : 1 = + −, 2 = × ÷, 3 = signe −, 4 = case, nombre ou fonction."""
            if isinstance(n, F.Num):
                return format(n.valeur.normalize(), "f"), 4, float(n.valeur)
            if isinstance(n, F.Ref):
                texte, x = source(n)
                return texte, 4, x
            if isinstance(n, F.Neg):
                t, p, x = tr(n.arg)
                x = _nombre(x)
                return "-" + (t if p >= 4 else f"({t})"), 3, (-x if isinstance(x, float) else x)
            ta, pa, a = tr(n.gauche)
            tb, pb, b = tr(n.droite)
            if n.op == "/" and not (isinstance(n.droite, F.Num) and n.droite.valeur != 0):
                # 0 / 0 = 0 (convention du produit) ; toute autre division par zéro : erreur
                texte = f"IF(AND({ta}=0,{tb}=0),0,{_par(ta, pa, 2, False)}/{_par(tb, pb, 2, True)})"
                return texte, 4, _diviser(a, b, zero=True)
            p = 1 if n.op in "+-" else 2
            texte = f"{_par(ta, pa, p, False)}{n.op}{_par(tb, pb, p, True)}"
            na, nb = _nombre(a), _nombre(b)
            if _erreur(na):
                return texte, p, na
            if _erreur(nb):
                return texte, p, nb
            if n.op == "+":
                return texte, p, na + nb
            if n.op == "-":
                return texte, p, na - nb
            if n.op == "*":
                return texte, p, na * nb
            return texte, p, _diviser(a, b, zero=False)

        texte, _, valeur = tr(arbre)
        return texte, valeur


def _par(texte, priorite, parent, droite):
    """Parenthèses pour garder l'ordre exact des calculs de l'outil (et un signe « − » toujours entre parenthèses)."""
    if priorite == 3 or priorite < parent or (droite and priorite == parent):
        return f"({texte})"
    return texte


def _diviser(a, b, zero):
    """a / b comme Excel ; ``zero`` : formule ``IF(AND(a=0,b=0),0,a/b)``."""
    if zero:
        # AND(a=0,b=0) : une erreur se propage ; un texte n'est pas égal à 0
        if _erreur(a):
            return a
        if _erreur(b):
            return b
        if (a is None or a == 0.0) and (b is None or b == 0.0):
            return 0.0
    na, nb = _nombre(a), _nombre(b)
    if _erreur(na):
        return na
    if _erreur(nb):
        return nb
    if nb == 0:
        return "#DIV/0!"
    return na / nb


class Contexte:
    """Ce qui ne dépend pas de la période : KPI, organisations, niveaux, formules analysées."""

    def __init__(self):
        self.kpis = {k.code: k for k in KPI.objects.all()}
        self.orgs = {o.id: o for o in Organisation.objects.select_related("niveau")}
        self.rangs = N.rangs()
        self._arbres, self._porteurs = {}, {}
        self.compte = {"formules": 0, **{r: 0 for r in RAISONS}}

    def arbre(self, k):
        if k.code not in self._arbres:
            try:
                self._arbres[k.code] = F.analyser(k.formule)
            except F.FormuleInvalide as e:
                self._arbres[k.code] = e
        a = self._arbres[k.code]
        if isinstance(a, Exception):
            raise a
        return a

    def porteur(self, k, o, orgs=None):
        """Organisation qui porte le paramètre hérité pour ``o``, dans l'arbre ``orgs`` (celui de la période de l'onglet)."""
        orgs = self.orgs if orgs is None else orgs
        cle = (k.granularite_id, o.id, id(orgs))
        if cle not in self._porteurs:
            self._porteurs[cle] = porteur_herite(orgs.get(o.id, o), k.granularite_id, self.rangs, orgs)
        return self._porteurs[cle]


def sources_transitives(codes):
    """Codes des KPI cités, de proche en proche, par les formules (même période) des KPI ``codes`` (eux non compris)."""
    from referentiel.models import KPIFormule

    graphe = {}
    for c, s in KPIFormule.objects.filter(decalage="N").values_list("kpi_calcule_id", "kpi_source_id"):
        graphe.setdefault(c, set()).add(s)
    vus, pile = set(), list(codes)
    while pile:
        for s in graphe.get(pile.pop(), ()):
            if s not in vus:
                vus.add(s)
                pile.append(s)
    return vus - set(codes)
