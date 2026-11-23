"""Règle unique d'arrondi des valeurs affichées (pages, Visualisation, fichiers) : module neutre, sans dépendance, que
``templatetags.collecte`` et ``visuels.formes`` importent tous les deux."""
import math
from decimal import ROUND_HALF_UP, Decimal, localcontext


def arrondi(v, decimales=0):
    """Arrondi comme Excel : 0,5 s'arrondit en s'éloignant de zéro (2,5 → 3 ; 0,125 → 0,13 ; -2,5 → -3), et non au pair.

    - Un nombre à virgule flottante passe d'abord par son texte à 15 chiffres significatifs, comme Excel (0.125 en binaire
      n'est pas tout à fait 0,125 ; 0,1 + 0,235 donne 0.33499999999999996, qu'Excel lit 0,335 et arrondit à 0,34).
    - Calcul en décimal avec assez de chiffres pour les très grands nombres (jamais laissé sans arrondi).
    - Jamais de « -0 » : une petite valeur négative arrondie à zéro donne 0 (-0,001 → 0,00).
    - Une valeur non finie (infini, NaN) est rendue telle quelle, en décimal.
    """
    if isinstance(v, float):
        d = Decimal(format(v, ".15g")) if math.isfinite(v) else Decimal(v)
    else:
        d = v if isinstance(v, Decimal) else Decimal(str(v))
    if not d.is_finite():
        return d
    n = int(decimales or 0)
    with localcontext() as c:  # assez de chiffres pour les très grands nombres
        c.prec = max(28, d.adjusted() + n + 3)
        d = d.quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP)
        return abs(d) if d == 0 else d


# Années (unité « année » : année de référence, année cible, année d'adoption d'un plan) : jamais de séparateur de milliers,
# dans aucune langue ni aucun écran ou fichier (2028, jamais « 2,028 » ni « 2 028 »). Une unité est une année quand son code
# ou l'un de ses symboles (langue de référence ou traduction) est l'un de ces mots, au singulier : « années » (durée,
# ancienneté) n'en est pas une.
SYMBOLES_ANNEE = frozenset({"année", "annee", "year", "año", "jahr", "anno", "jaar", "ano"})


def est_annee(unite):
    """Vrai si l'unité (objet ``Unite``, ou None) compte des années du calendrier."""
    if unite is None:
        return False
    textes = [getattr(unite, "code", ""), getattr(unite, "symbole", "")]
    textes += [d.get("symbole", "") for d in (getattr(unite, "traductions", None) or {}).values() if isinstance(d, dict)]
    return any(isinstance(t, str) and t.strip().lower() in SYMBOLES_ANNEE for t in textes)


def sans_milliers(kpi):
    """Vrai si les valeurs du KPI s'écrivent sans séparateur de milliers (unité « année »). Règle unique : grille de saisie,
    Consolidation, Visualisation, fichiers exportés, dossier d'audit."""
    return bool(getattr(kpi, "unite_id", None)) and not kpi.est_pourcentage and est_annee(kpi.unite)


def chiffres(v, decimales=0, milliers=True):
    """Nombre arrondi (``arrondi``) écrit « 1,234.50 » (séparateurs anglais, à remplacer par ceux de la langue), ou
    « 1234.50 » sans séparateur de milliers (``milliers=False``) ; jamais « -0 »."""
    n = int(decimales or 0)
    texte = f"{arrondi(v, n):{',' if milliers else ''}.{n}f}"
    if texte.startswith("-") and not texte.strip("-0.,"):  # petite valeur négative arrondie à zéro : « 0,00 », pas « -0,00 »
        texte = texte[1:]
    return texte


def format_excel(decimales, milliers=True):
    """Format Excel d'un nombre à ``decimales`` chiffres après la virgule, avec ou sans séparateur de milliers."""
    d = int(decimales or 0)
    return ("#,##0" if milliers else "0") + ("." + "0" * d if d else "")
