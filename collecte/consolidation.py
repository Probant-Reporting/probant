"""Tableau de bord › Consolidation : les valeurs de chaque niveau de l'arbre, du plus bas au plus haut, pour quelques KPI.

Lignes : les organisations du périmètre de la personne, dans l'ordre de l'arbre (on déplie un niveau pour voir ce qui le
compose). Colonnes : les KPI d'un thème du référentiel de la campagne, ou d'une liste enregistrée (Import / Export).
Les valeurs sont celles de la Visualisation (``visualisation.Source``) : même périmètre, mêmes règles (validées
seulement par défaut, brouillons sur demande, total provisoire ◐), mêmes totaux que le moteur de calcul ; la page
n'écrit rien (lecteur et auditeur compris). Seul ajout : quand un total en Somme est incomplet (des organisations du
dessous n'ont pas encore de valeur), la page montre le **total partiel** de ce qui est connu, marqué comme tel, avec le
nombre d'organisations qui manquent (même règle que le moteur pour savoir qui compte : ``Calculateur._agreger``).
"""
from dataclasses import dataclass, field
from decimal import Decimal

from referentiel.formule import NA

from referentiel.models import KPI

from . import calcul as C
from . import saisie as S
from . import visualisation as V
from .models import SelectionKPI

MAX_COLONNES = 30  # KPI en colonnes : au-delà, la page invite à choisir un sous-thème ou une liste plus courte
MAX_LIGNES_KPI = 150  # KPI en lignes (lignes et colonnes interverties) : la page défile en hauteur


@dataclass
class Case:
    """Une case du tableau : le point de la période, celui de N-1, et pourquoi elle est vide."""

    kpi: object = None
    point: object = None  # V.Point ou None (hors périmètre)
    org: object = None  # organisation de la case (lien vers son détail, dans les deux sens du tableau)
    n1: object = None
    absente: bool = False  # le KPI n'existe pas à ce niveau (saisi plus bas sans total, ou plus haut)
    incomplet: str = ""  # total ou calcul sans valeur : la cause donnée par le moteur de calcul (« Incomplet : … »)
    non_saisie: bool = False  # KPI saisi à ce niveau, pas encore saisi (rien à expliquer : « — »)
    partiel: object = None  # total incomplet en Somme : la somme de ce qui est connu en dessous (Decimal)
    manquants: int = 0  # organisations (du niveau de saisie) qui manquent à ce total partiel
    erreur: bool = False  # le calcul est en erreur (formule illisible, division par zéro…) : seul cas signalé en orange

    @property
    def a_valeur(self):
        return bool(self.point and (self.point.valeur is not None or self.point.en_attente)) or self.partiel is not None \
            or self.erreur

    @property
    def ecart(self):
        return V.ecart(self.point, self.n1) if self.point and self.n1 else None


@dataclass
class Ligne:
    org: object
    prof: int  # profondeur dans ce que la personne voit (0 : sommet)
    parent_id: object
    a_enfants: bool = False
    cases: list = field(default_factory=list)


def preparer(plan, utilisateur, campagne=None):
    """Garde dans le plan les KPI que la personne voit (tous pour l'administrateur, le lecteur et l'auditeur ; ses cases
    pour le contributeur et le validateur) : les thèmes proposés et le choix par défaut ne parlent que d'eux.
    ``campagne`` : seulement les KPI que son référentiel demande dans sa période (``saisie.codes_campagne``, la même
    fonction que la Saisie : « demandé depuis » et périmètre gelé d'un exercice clos ou rouvert)."""
    _, paires, resultats = V.perimetre(utilisateur, S.arbre_organisations())
    plan._conso_visibles = None if paires is None or resultats else {c for c, _ in paires}
    codes = S.codes_campagne(campagne) if campagne is not None else None
    plan._conso_demandes = None if codes is None else codes[1]
    plan.__dict__.pop("_conso_montrables", None)
    plan.__dict__.pop("_conso_par_theme", None)


def montrables(plan):
    """{code: KPI} des KPI du plan qui peuvent être en colonne : actifs, vus par la personne (``preparer``), et jamais
    le texte rédigé (hors de tout total)."""
    if not hasattr(plan, "_conso_montrables"):
        visibles = getattr(plan, "_conso_visibles", None)
        codes = plan.codes if visibles is None else plan.codes & visibles
        demandes = getattr(plan, "_conso_demandes", None)
        if demandes is not None:
            codes = codes & demandes
        kpis = KPI.objects.select_related("unite", "type_reponse", "type_saisie", "granularite").filter(code__in=codes, actif=True)
        plan._conso_montrables = {k.code: k for k in kpis if not k.est_texte}
    return plan._conso_montrables


def _sans_total_ici(kpi, org):
    """Vrai au-dessus du niveau de saisie d'un KPI sans agrégation (ni hérité) : aucun total n'y est attendu."""
    return (kpi.methode_agregation == KPI.Agregation.AUCUNE and not kpi.est_herite and kpi.granularite_id
            and org.niveau_id and org.niveau.rang < kpi.granularite.rang)


def _valeur_vue(source, code, org_id, periode):
    """Valeur d'une organisation telle que la case la montre (validées seulement, ou brouillons compris), sans le filtre de
    périmètre : un total couvre aussi les organisations que la personne ne voit pas une à une."""
    valide = source.calc.valeur(code, org_id, periode)
    if not source.brouillons:
        return valide
    officielle = V.valeur_officielle(source.officielles(periode).get((code, org_id)), source.kpis[code])
    return officielle if officielle is not None else valide


def partiel(source, kpi, org_id, periode, rang_org):
    """(somme connue, organisations manquantes) d'un total incomplet en Somme, ou None (rien de connu, ou pas une somme).
    Mêmes organisations que le moteur (``Calculateur._agreger``) : enfants à un niveau où le KPI existe, une organisation
    fermée sans aucune valeur ne manque pas ; un enfant lui-même incomplet apporte son propre total partiel."""
    calc = source.calc
    if kpi.methode_agregation != KPI.Agregation.SOMME or kpi.est_pourcentage or not kpi.granularite_id:
        return None
    rang_k = calc.rangs.get(kpi.granularite_id)
    if rang_k is None or rang_org >= rang_k:
        return None
    detail = calc._avec_detail(rang_k, periode, kpi.code)
    total, manquants, connu = Decimal(0), 0, False
    for e in calc.enfants(org_id, periode, kpi.code):
        if calc.rangs[e.niveau_id] > rang_k:
            continue
        v = _valeur_vue(source, kpi.code, e.id, periode)
        if isinstance(v, Decimal):
            total, connu = total + v, True
        elif v is NA:
            connu = True
        elif v is None:
            if not calc.compte_sans_valeur(kpi, e, periode, detail):
                continue  # organisation fermée sans valeur : elle ne manque pas (la règle du moteur)
            sous = partiel(source, kpi, e.id, periode, calc.rangs[e.niveau_id])
            if sous is None:
                manquants += 1
            else:
                total, connu, manquants = total + sous[0], True, manquants + sous[1]
    return (total, manquants) if connu and manquants else None


def themes(plan, referentiel):
    """[(thème, libellé en retrait, nombre de KPI dessous)] du référentiel : les thèmes qui ont au moins un KPI montrable."""
    sortie = []
    for t, prof in plan.arbre(referentiel):
        n = len(codes_du_theme(plan, t))
        if n:
            sortie.append((t, "\u2003" * prof + t.tr("nom"), n))
    return sortie


def codes_du_theme(plan, theme):
    """KPI placés sous le thème (lui et ses sous-thèmes), dans l'ordre du référentiel."""
    cache = plan.__dict__.setdefault("_conso_par_theme", {})
    if theme.id not in cache:
        ok = montrables(plan)
        cache[theme.id] = [c for c in sorted(plan.codes, key=plan.position) if c in ok and (e := plan.element(c)) is not None
                           and any(t.id == theme.id for t in plan.chemin(e.theme_id))]
    return cache[theme.id]


def theme_par_defaut(plan):
    """Le thème (d'au plus MAX_COLONNES KPI) qui a le plus de KPI saisis sous le sommet de l'arbre (le plus à déplier),
    sinon le premier thème qui a un KPI montrable."""
    tous = [t for t, _ in plan.arbre(plan.referentiel)] if plan.referentiel else []
    ok = montrables(plan)
    rang_haut = min((k.granularite.rang for k in ok.values() if k.granularite_id), default=None)

    def dessous(t):
        return sum(1 for c in codes_du_theme(plan, t) if ok[c].granularite_id and ok[c].granularite.rang != rang_haut)
    candidats = [t for t in tous if dessous(t) and len(codes_du_theme(plan, t)) <= MAX_COLONNES]
    return (max(candidats, key=dessous) if candidats else None) or next((t for t in tous if codes_du_theme(plan, t)), None)


def choix_kpi(utilisateur, plan, theme_id=None, liste_id=None, mode="theme", codes=()):
    """(KPI choisis, thème ou None, liste ou None, mode) : « choix » (KPI cochés un par un), « liste » (une liste
    enregistrée visible), sinon un thème du référentiel (par défaut ``theme_par_defaut``). Le texte rédigé n'entre dans
    aucun total : jamais en colonne. Un choix vide ou introuvable revient au thème."""
    ok = montrables(plan)
    if mode == "choix":
        choisis = [c for c in sorted(set(codes), key=plan.position) if c in ok]
        if choisis:
            return [ok[c] for c in choisis], None, None, "choix"
    liste = SelectionKPI.visibles(utilisateur).filter(pk=liste_id).first() if str(liste_id or "").isdecimal() else None
    if liste is not None and mode == "liste":  # le mode coché décide : « Un thème » ignore la liste encore choisie
        codes = sorted(liste.kpis.values_list("code", flat=True), key=plan.position)
        # une liste peut citer des KPI d'autres référentiels
        kpis = {k.code: k for k in KPI.objects.select_related("unite", "type_reponse", "type_saisie", "granularite")
                .filter(code__in=codes, actif=True) if not k.est_texte}
        return [kpis[c] for c in codes if c in kpis], None, liste, "liste"
    themes = themes_choisis(plan, theme_id)
    vus, codes = set(), []
    for t in themes:  # plusieurs thèmes cochés : leurs KPI, sans doublon, dans l'ordre du référentiel
        for c in codes_du_theme(plan, t):
            if c not in vus:
                vus.add(c)
                codes.append(c)
    return [ok[c] for c in sorted(codes, key=plan.position)], (themes[0] if themes else None), None, "theme"


def themes_choisis(plan, theme_ids):
    """Thèmes cochés (identifiants séparés par des virgules, ou un seul) dans l'ordre du référentiel ; aucun trouvé : le
    thème par défaut."""
    ids = {x.strip() for x in str(theme_ids or "").split(",") if x.strip()}
    tous = [t for t, _ in plan.arbre(plan.referentiel)] if plan.referentiel else []
    choisis = [t for t in tous if str(t.id) in ids]
    if not choisis:
        defaut = theme_par_defaut(plan)
        choisis = [defaut] if defaut else []
    return choisis


def groupes_a_cocher(plan):
    """[(thème du sommet, [KPI])] pour « Choisir les KPI » : les KPI montrables du référentiel, dans son ordre."""
    groupes = {}
    for c in sorted(montrables(plan), key=plan.position):
        k = montrables(plan)[c]
        k.refs = ""  # pas de filtre par référentiel ici : tout est du référentiel de la campagne
        groupes.setdefault(plan.titres(c)[0], []).append(k)
    return list(groupes.items())


@dataclass
class Tableau:
    lignes: list
    kpis: list  # colonnes montrées
    caches: int = 0  # KPI au-delà du maximum de colonnes
    vides: list = field(default_factory=list)  # KPI sans aucune valeur dans le tableau (masqués sauf demande)
    parametres: list = field(default_factory=list)  # paramètres hérités (masqués sauf demande)
    etats: set = field(default_factory=set)  # états présents (légende : seulement ceux qu'on voit)


def tableau(utilisateur, periode, kpis, brouillons=False, avec_n1=False, avec_vides=False, avec_parametres=False,
            max_kpis=MAX_COLONNES):
    """Tableau : une ligne par organisation du périmètre, une case par KPI. Les paramètres hérités (une valeur reprise
    par les organisations du dessous, jamais additionnée) et les KPI sans aucune valeur sont mis de côté, sauf demande."""
    parametres = [k for k in kpis if k.est_herite]
    if not avec_parametres:
        kpis = [k for k in kpis if not k.est_herite]
    source = V.Source(utilisateur, codes=[k.code for k in kpis], brouillons=brouillons)
    # lignes dans l'arbre de la période (celui de sa clôture pour un exercice clos ou rouvert en
    # gardant les chiffres de l'époque), seulement les organisations ouvertes pendant la période (``calcul.ouverte``,
    # comme les totaux) : chaque total est la somme des lignes montrées dessous
    # KPI figés par une campagne clôturée de la période : l'arbre du jour où ils l'ont été, si tous
    # les KPI du tableau le suivent (``calcul.arbre_commun``) ; sinon celui de la période
    commun = C.arbre_commun(periode, [k.code for k in kpis]) if periode is not None else None
    arbre = S.arbre_organisations(periode, commun)
    orgs = sorted((arbre[o.id] for o in source.organisations(periode, commun)), key=S.cle_arbre)  # fermées depuis comprises
    # seulement les KPI demandés dans la période (``Source.demande`` : une liste enregistrée peut citer un KPI qui n'y
    # est pas demandé) et que la personne voit quelque part dans son périmètre
    kpis = [k for k in kpis if source.demande(k.code, periode)
            and any(source.voit(k.code, o.id) and source.existe_a(k.code, o) for o in orgs)]
    caches = max(len(kpis) - max_kpis, 0)
    kpis = kpis[:max_kpis]
    prec = source.n1(periode) if avec_n1 else None
    ids = {o.id for o in orgs}
    base = min((o.prof for o in orgs), default=0)
    parents = {o.parent_id for o in orgs}
    lignes = []
    for o in orgs:
        ligne = Ligne(o, o.prof - base, o.parent_id if o.parent_id in ids else None, a_enfants=o.id in parents)
        for k in kpis:
            if not source.existe_a(k.code, o):
                ligne.cases.append(Case(k, absente=True))
                continue
            p = source.point(k.code, o, periode)
            if p is not None and p.valeur is None and not p.en_attente and _sans_total_ici(k, o):
                ligne.cases.append(Case(k, absente=True))  # ex. un taux sans agrégation, au-dessus de son niveau
                continue
            case = Case(k, point=p, n1=source.point(k.code, o, prec) if prec and p is not None else None)
            saisi_ici = not k.est_calcule and k.granularite_id and o.niveau_id and o.niveau.rang == k.granularite.rang
            if p is not None and p.valeur is None and p.en_attente and not saisi_ici and o.niveau_id:
                # total qui n'existe qu'avec des brouillons (validées seulement) : la part validée, en partiel
                sous = partiel(source, k, o.id, periode, source.calc.rangs.get(o.niveau_id, 0))
                if sous is not None:
                    case.partiel, case.manquants = sous
            if p is not None and p.valeur is None and not p.en_attente:
                if saisi_ici:
                    case.non_saisie = True
                else:
                    case.incomplet = source.calc.message(k.code, o.id, periode)
                    case.erreur = (k.code, o.id, periode.pk) in source.calc.erreurs
                    if not case.erreur and o.niveau_id:
                        sous = partiel(source, k, o.id, periode, source.calc.rangs.get(o.niveau_id, 0))
                        if sous is not None:
                            case.partiel, case.manquants = sous
            ligne.cases.append(case)
        for c in ligne.cases:
            c.org = o
        lignes.append(ligne)
    # seulement les lignes qui montrent une valeur (ou un état) à la personne, et leurs parents pour garder l'arbre
    gardees = {l.org.id for l in lignes if any(c.point is not None for c in l.cases)}
    par_id = {l.org.id: l for l in lignes}
    for i in list(gardees):
        p = par_id[i].parent_id
        while p is not None and p not in gardees:
            gardees.add(p)
            p = par_id[p].parent_id
    lignes = [l for l in lignes if l.org.id in gardees]
    avec_enfants = {l.parent_id for l in lignes}
    for l in lignes:
        l.a_enfants = l.org.id in avec_enfants
    # colonnes sans aucune valeur (ni partielle, ni en attente) : de côté, sauf demande
    vides = [k for i, k in enumerate(kpis) if not any(l.cases[i].a_valeur for l in lignes)]
    if vides and not avec_vides:
        garder = [i for i, k in enumerate(kpis) if k not in vides]
        kpis = [kpis[i] for i in garder]
        for l in lignes:
            l.cases = [l.cases[i] for i in garder]
    etats = set()
    for l in lignes:
        for c in l.cases:
            etats.update(n for n, v in (("absente", c.absente), ("non_saisie", c.non_saisie), ("partiel", c.partiel is not None),
                                        ("erreur", c.erreur), ("attente", bool(c.point and c.point.en_attente)),
                                        ("provisoire", bool(c.point and c.point.provisoire)),
                                        ("incomplet", bool(c.incomplet) and c.partiel is None and not c.erreur)) if v)
    return Tableau(lignes, kpis, caches, vides, parametres, etats)


def transposer(t, profondeur):
    """Lignes et colonnes interverties : (organisations en colonnes, [(KPI, [cases])] en lignes). Les organisations
    jusqu'à ``profondeur`` niveaux sous le sommet de ce que la personne voit (0 : le sommet seul), dans l'ordre de l'arbre."""
    gardees = [i for i, l in enumerate(t.lignes) if l.prof <= profondeur]
    colonnes = [t.lignes[i] for i in gardees]
    return colonnes, [(k, [t.lignes[i].cases[j] for i in gardees]) for j, k in enumerate(t.kpis)]


def profondeurs(lignes):
    """[(profondeur, libellé)] proposées quand les organisations sont en colonnes : « Groupe », « … › Pays »…, d'après
    les niveaux présents à chaque profondeur."""
    noms = {}
    for l in lignes:
        noms.setdefault(l.prof, [])
        n = str(l.org.niveau or "")
        if n and n not in noms[l.prof]:
            noms[l.prof].append(n)
    return [(p, " / ".join(noms[p])) for p in sorted(noms)]

