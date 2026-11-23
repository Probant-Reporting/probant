"""Visualisation v2 : filtres de l'adresse et sources de KPI (plan du référentiel)."""
from referentiel.models import KPI, Theme
from referentiel.plans import Plan

from ..models import SelectionKPI

from .formes import lib


# ---------------------------------------------------------------- filtres
ID_MAX = 2**31 - 1  # au-delà, un identifiant lu dans l'adresse ne désigne rien (et SQLite refuse l'entier)


def _entier(x):
    try:
        n = int(x)
    except (TypeError, ValueError):
        return None
    return n if -ID_MAX <= n <= ID_MAX else None


def filtres_depuis_adresse(parametres):
    """Changements temporaires lus dans l'adresse : ?periode=5&cmp=n1&org=2&ref=RSE&theme=31,32&brouillons=1."""
    q = parametres or {}
    d = {}
    if q.get("periode"):
        d["periode"] = q["periode"] if q["periode"] in ("auto", "je_reponds_a") else _entier(q["periode"])
    if q.get("cmp") in ("n1", "p1", "aucune"):
        d["comparaison"] = q["cmp"]
    if q.get("org"):
        d["org"] = "tout" if q["org"] == "tout" else _entier(q["org"])
    if q.get("ref"):
        d["referentiel"] = str(q["ref"])[:30]
    if "theme" in q:
        d["themes"] = [i for i in (_entier(x) for x in str(q["theme"]).split(",")) if i]
    if "brouillons" in q:
        d["valeurs"] = "brouillons" if q.get("brouillons") == "1" else "validees"
    return {k: v for k, v in d.items() if v is not None}


def nettoyer_filtres(f, erreurs=None):
    """Filtres d'une vue réduits aux clés et valeurs connues (le reste est ignoré, et signalé dans ``erreurs``)."""
    erreurs = erreurs if erreurs is not None else []
    f = f if isinstance(f, dict) else {}
    sortie = {}
    for cle, v in f.items():
        if cle == "periode" and (v in ("auto", "je_reponds_a") or (isinstance(v, int) and not isinstance(v, bool))):
            sortie[cle] = v
        elif cle == "comparaison" and v in ("n1", "p1", "aucune"):
            sortie[cle] = v
        elif cle == "org" and (v is None or v == "tout" or (isinstance(v, int) and not isinstance(v, bool))):
            sortie[cle] = v
        elif cle == "referentiel" and isinstance(v, str) and len(v) <= 30:
            sortie[cle] = v
        elif cle == "themes" and isinstance(v, list) and all(isinstance(i, int) and abs(i) <= ID_MAX for i in v) and len(v) <= 100:
            sortie[cle] = v
        elif cle == "valeurs" and v in ("validees", "brouillons"):
            sortie[cle] = v
        else:
            erreurs.append({"visuel": "", "message": lib("visu.erreur.filtre", filtre=str(cle)[:40])})
    return sortie


# ---------------------------------------------------------------- KPI d'un tableau (liste, thème, filtre Thèmes)
def _plan(plans, referentiel):
    cle = referentiel.pk if referentiel is not None else None
    if cle not in plans:
        plans[cle] = Plan(referentiel)
    return plans[cle]


def _plan_de(ctx, referentiel):
    return _plan(ctx.__dict__.setdefault("_plans", {}), referentiel)


def codes_du_plan(plan, themes=None):
    """Codes des KPI actifs du plan, dans son ordre ; sous l'un des ``themes`` (et leurs sous-thèmes) s'il y en a."""
    ids = {t.pk for t in themes or []}
    codes = []
    actifs = set(KPI.objects.filter(actif=True, code__in=plan.codes).values_list("code", flat=True))
    for code in sorted(actifs, key=plan.position):
        if ids:
            e = plan.element(code)
            if not e or not ids & {t.pk for t in plan.chemin(e.theme_id)}:
                continue
        codes.append(code)
    return codes


def codes_source(ctx, source):
    """Codes d'un tableau : « liste:<id> » (liste de KPI visible), « theme:<id> » (thème d'un référentiel actif) ou
    « filtre_theme » (KPI du filtre Thèmes de la vue) ; None si la liste ou le thème n'existe plus."""
    if source == "filtre_theme":
        return codes_du_plan(ctx.plan, ctx.themes)
    return codes_source_fixes(ctx.utilisateur, source, ctx.__dict__.setdefault("_plans", {}))


def codes_source_fixes(utilisateur, source, plans=None):
    """Codes d'un tableau « liste:<id> » ou « theme:<id> », qui ne dépendent pas des filtres de la vue ; None pour
    « filtre_theme » (il dépend du filtre Thèmes), pour un visuel sans source, ou si la liste ou le thème n'existe plus."""
    plans = {} if plans is None else plans
    genre, _, pk = str(source or "").partition(":")
    if not pk.isdecimal():
        return None
    if genre == "liste":
        liste = SelectionKPI.visibles(utilisateur).filter(pk=pk).first()
        if liste is None:
            return None
        plan = _plan(plans, None)
        return [k.code for k in sorted(liste.kpis.filter(actif=True), key=lambda k: plan.position(k.code, k.ordre))]
    if genre == "theme":
        t = Theme.objects.select_related("referentiel").filter(pk=pk, referentiel__actif=True).first()
        return codes_du_plan(_plan(plans, t.referentiel), [t]) if t else None
    return None


def libelle_source(ctx, source):
    genre, _, pk = (source or "").partition(":")
    if genre == "filtre_theme":
        noms = ", ".join(t.tr("nom") for t in ctx.themes)
        return lib("visu.kpi.filtre_theme") + (f" : {noms}" if noms else "")
    if genre == "liste" and pk.isdecimal():
        x = SelectionKPI.objects.filter(pk=pk).first()
        return lib("visu.kpi.liste", nom=x.nom) if x else ""
    if genre == "theme" and pk.isdecimal():
        x = Theme.objects.select_related("referentiel").filter(pk=pk).first()
        return f"{x.referentiel} · {x.tr('nom')}" if x else ""
    return ""
