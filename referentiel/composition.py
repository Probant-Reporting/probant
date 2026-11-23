"""Composer un référentiel : référentiel par défaut, thèmes retrouvés ou créés par leur chemin de noms, place d'un KPI.

Sert aux imports (format historique, classeur de configuration d'avant les référentiels), à la démo et à la page
Référentiels › Gérer les référentiels.
"""
import re
import unicodedata

from django.db.models import Max

from parametres.libelles import libelle

from .models import ElementReferentiel, Referentiel, Theme


def code_theme(ref, nom, pris=None):
    """« 01.01 Reporting scope (BP-1) » → « 01_01_Reporting_scope_BP_1 », unique dans le référentiel."""
    base = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")[:36] or "Theme"
    pris = pris if pris is not None else set(Theme.objects.filter(referentiel=ref).values_list("code", flat=True))
    code, i = base, 2
    while code in pris:
        code, i = f"{base}_{i}", i + 1
    pris.add(code)
    return code


def code_referentiel(nom):
    base = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_").upper()[:26] or "REF"
    code, i = base, 2
    while Referentiel.objects.filter(code=code).exists():
        code, i = f"{base}_{i}", i + 1
    return code


def referentiel_par_defaut(nom=None):
    """Premier référentiel actif ; s'il n'y en a aucun, « Reporting <structure> » (code REPORTING) est créé.

    Une installation plus ancienne retrouve son référentiel de code RSE (créé par la migration referentiel/0006)."""
    r = Referentiel.objects.filter(actif=True).first()
    if r is None:
        r = Referentiel.objects.filter(code="RSE").first()
    if r is None:
        from parametres.models import Instance

        i = Instance.courante()
        r = Referentiel.objects.create(
            code=code_referentiel("Reporting"), nom=nom or (f"Reporting {i.nom}" if i.nom else "Reporting"),
            couleur=i.couleur_principale, ordre=Referentiel.objects.count() + 1)
    return r


def theme_par_chemin(ref, noms, cache=None):
    """Thème au bout d'un chemin de noms (« Environnement », « Énergie »…), créé au besoin à la fin de son parent."""
    cache = cache if cache is not None else {}
    parent = None
    for nom in [n for n in noms if n]:
        cle = (ref.pk, parent.pk if parent else None, nom)
        if cle not in cache:
            t = Theme.objects.filter(referentiel=ref, parent=parent, nom=nom).first()
            if t is None:
                ordre = (Theme.objects.filter(referentiel=ref, parent=parent).aggregate(m=Max("ordre"))["m"] or 0) + 1
                t = Theme.objects.create(referentiel=ref, parent=parent, nom=nom, code=code_theme(ref, nom), ordre=ordre)
            cache[cle] = t
        parent = cache[cle]
    return parent


def ordre_suivant(ref, theme):
    return (ElementReferentiel.objects.filter(referentiel=ref, theme=theme).aggregate(m=Max("ordre"))["m"] or 0) + 1


def placer(kpi, ref, theme, ordre=None, **autres):
    """Crée ou déplace l'élément du KPI dans le référentiel. Renvoie (élément, créé)."""
    e = ElementReferentiel.objects.filter(referentiel=ref, kpi=kpi).first()
    if e is None:
        return ElementReferentiel.objects.create(referentiel=ref, kpi=kpi, theme=theme,
                                                 ordre=ordre if ordre is not None else ordre_suivant(ref, theme), **autres), True
    champs = {"theme": theme, **({"ordre": ordre} if ordre is not None else {}), **autres}
    if any(getattr(e, c) != v for c, v in champs.items()):
        for c, v in champs.items():
            setattr(e, c, v)
        e.save()
    return e, False


def composer(places, ref=None):
    """Range des KPI dans un référentiel (par défaut le premier actif, créé au besoin), dans l'ordre donné :
    {code du KPI : [noms des thèmes du sommet vers le bas]}. Sert à la démo et aux tests."""
    from .models import KPI

    ref = ref or referentiel_par_defaut()
    kpis, cache = KPI.objects.in_bulk(list(places)), {}
    for code, noms in places.items():
        placer(kpis[code], ref, theme_par_chemin(ref, noms, cache))
    return ref


def chemin_noms(element):
    """Noms (langue de référence) des thèmes d'un élément, du sommet vers le bas."""
    noms, t = [], element.theme if element else None
    while t is not None:
        noms.insert(0, t.nom)
        t = t.parent
    return noms


def code_libre_theme(ref, code, nom, pris):
    if code and code not in pris:
        pris.add(code)
        return code
    return code_theme(ref, nom or code, pris)


def ordre_theme_suivant(ref, parent):
    return (Theme.objects.filter(referentiel=ref, parent=parent).aggregate(m=Max("ordre"))["m"] or 0) + 1


def copier_theme(source, ref, parent=None):
    """Copie un thème et ses sous-thèmes dans un autre référentiel (« lego ») : mêmes noms et traductions, mêmes KPI —
    les éléments pointent vers les KPI du catalogue, rien n'est recopié. Un KPI déjà dans le référentiel cible n'y est pas
    ajouté une seconde fois. Renvoie (thème créé, KPI ajoutés, KPI déjà présents)."""
    pris = set(Theme.objects.filter(referentiel=ref).values_list("code", flat=True))
    deja = set(ElementReferentiel.objects.filter(referentiel=ref).values_list("kpi_id", flat=True))
    ajoutes = presents = 0

    def copier(t, parent_cible, ordre):
        nonlocal ajoutes, presents
        nouveau = Theme.objects.create(referentiel=ref, parent=parent_cible, code=code_libre_theme(ref, t.code, t.nom, pris),
                                       nom=t.nom, traductions=dict(t.traductions or {}), ordre=ordre)
        for e in t.elements.order_by("ordre", "kpi_id"):
            if e.kpi_id in deja:
                presents += 1
                continue
            ElementReferentiel.objects.create(referentiel=ref, theme=nouveau, kpi_id=e.kpi_id, ordre=e.ordre,
                                              libelle=e.libelle, traductions=dict(e.traductions or {}), obligatoire=e.obligatoire)
            deja.add(e.kpi_id)
            ajoutes += 1
        for i, enfant in enumerate(t.enfants.order_by("ordre", "pk"), start=1):
            copier(enfant, nouveau, i)
        return nouveau

    if parent is not None and (parent.pk == source.pk or _sous(source, parent)):
        raise ValueError(libelle("referentiels.composition.copie_soi"))
    return copier(source, parent, ordre_theme_suivant(ref, parent)), ajoutes, presents


def _sous(theme, candidat):
    """Vrai si ``candidat`` est un sous-thème (à n'importe quelle profondeur) de ``theme``."""
    p = candidat.parent
    while p is not None:
        if p.pk == theme.pk:
            return True
        p = p.parent
    return False


def ordonner_elements(ref, theme, codes):
    """Ordre des KPI d'un thème (ou « sans thème ») : ceux de ``codes`` dans cet ordre, déplacés au besoin."""
    elements = {e.kpi_id: e for e in ElementReferentiel.objects.filter(referentiel=ref, kpi_id__in=codes)}
    for i, c in enumerate([c for c in codes if c in elements], start=1):
        e = elements[c]
        if (e.theme_id, e.ordre) != (theme.pk if theme else None, i):
            e.theme, e.ordre = theme, i
            e.save(update_fields=["theme", "ordre"])
