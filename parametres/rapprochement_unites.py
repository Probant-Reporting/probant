"""Reconnaître une unité citée par un fichier (référentiel, modèle de la bibliothèque, classeur de configuration) parmi
les unités de l'installation, ou parmi celles d'un paquet : une seule règle pour toutes les portes d'entrée.

Une unité se reconnaît par son symbole exact (après normalisation Unicode NFKC et retrait des espaces : « m3 » = « m³ »,
« t CO2e » = « tCO₂e »), par son code, ou par une traduction exacte de son symbole ou de son libellé ; jamais par une
forme qui retire des symboles ou la ponctuation (« €/h » n'est pas « h », « m » n'est pas « M€ »). Un écart de casse seul
(« kwh » et « kWh ») est rapproché, avec un avertissement, sauf quand la casse peut changer le sens (première lettre
m/M, k/K, g/G, p/P, t/T, écritures du catalogue qui ne diffèrent que par la casse, plusieurs unités possibles) : l'unité
du fichier est alors créée à part (« MW » n'est pas « mW »).

Module sans base de données : il sert aussi au contrôle des modèles de la bibliothèque (``bibliotheque --validate``)."""
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

# première lettre d'un symbole dont la casse change le sens : milli / méga, kilo / kelvin, gramme / giga, pico / péta,
# tonne / téra (règle du projet pour m, k, g, p ; t ajouté, à confirmer)
PREFIXES_CASSE = frozenset("mkgpt")


def symbole_normalise(symbole):
    """Écriture d'un symbole sans ce qui ne change pas son sens : exposants et indices (« m³ » = « m3 », « CO₂ » = « CO2 »),
    espaces. Les majuscules comptent (mW n'est pas MW)."""
    return "".join(unicodedata.normalize("NFKC", symbole or "").split())


def casse_seule(a, b):
    """Deux écritures qui ne diffèrent, après ``symbole_normalise``, que par la casse (« kwh » et « kWh ») ; deux écritures
    équivalentes (« m3 » et « m³ ») ne le sont pas : rien n'a changé de casse."""
    na, nb = symbole_normalise(a), symbole_normalise(b)
    return na != nb and na.casefold() == nb.casefold()


@lru_cache(maxsize=1)
def familles_catalogue():
    """Écritures (normalisées, casse comprise) du catalogue groupées par casse ignorée, seulement quand le catalogue en a
    plusieurs : la casse y change le sens (« mL » millilitre, « ML » mégalitre)."""
    from .catalogue_unites import THEMES

    familles = {}
    for _, _, unites in THEMES:
        for symbole, *_ in unites:
            n = symbole_normalise(symbole)
            familles.setdefault(n.casefold(), set()).add(n)
    return {cle: frozenset(ecritures) for cle, ecritures in familles.items() if len(ecritures) > 1}


def casse_sans_risque(a, b):
    """Vrai si ``a`` et ``b`` ne diffèrent que par la casse, et que cette casse ne peut pas en changer le sens : même
    première lettre quand elle est m, k, g, p ou t (en minuscule ou en majuscule), et pas deux unités du catalogue."""
    if not casse_seule(a, b):
        return False
    na, nb = symbole_normalise(a), symbole_normalise(b)
    if na[:1] != nb[:1] and na[:1].lower() in PREFIXES_CASSE:
        return False
    return na.casefold() not in familles_catalogue()


def ecritures(u):
    """(code, [symboles], [libellés]) d'une unité de l'installation (objet ``Unite``) ou d'un paquet (dict : ``code``,
    ``symbole`` et ``libelle`` par langue) ; référence et traductions."""
    if isinstance(u, dict):
        return (u.get("code") or "", [s for s in (u.get("symbole") or {}).values() if s],
                [s for s in (u.get("libelle") or {}).values() if s])
    traductions = [d for d in (getattr(u, "traductions", None) or {}).values() if isinstance(d, dict)]
    symboles = [s for s in [u.symbole, *(d.get("symbole") for d in traductions)] if s]
    libelles = [s for s in [getattr(u, "libelle", ""), *(d.get("libelle") for d in traductions)] if s]
    return u.code or "", symboles, libelles


@dataclass(frozen=True)
class Rapprochement:
    unite: object = None  # unité reconnue, ou None : à créer
    casse: str = ""  # symbole de l'unité reconnue malgré un écart de casse seul (avertissement à donner)
    texte: str = ""  # texte du fichier rapproché malgré la casse, ou écarté pour la casse
    ecartee: str = ""  # symbole d'une unité écartée parce que la casse peut en changer le sens (unité créée à part)


def rapprocher_unite(textes, unites, code=None, casse=True):
    """Unité de ``unites`` (objets ``Unite`` ou dicts d'un paquet, dans l'ordre de préférence) reconnue pour ``textes``
    (symbole d'une cellule, ou symboles d'une unité d'un paquet dans ses langues). ``code`` : code de l'unité du paquet,
    préféré quand l'unité de ce code a aussi le même symbole. ``casse`` : False pour ne rapprocher aucun écart de casse.
    Renvoie un ``Rapprochement`` (``unite`` None : rien de reconnu, l'unité est à créer)."""
    textes = [t for t in (str(x).strip() for x in textes if x) if t] or ([code] if code else [])
    normes = {symbole_normalise(t) for t in textes}
    if not normes:
        return Rapprochement()
    liste = [(u, *ecritures(u)) for u in unites]

    def par_symbole(c, symboles):
        return bool(normes & ({symbole_normalise(s) for s in symboles} | {symbole_normalise(c)}))

    def par_libelle(libelles):
        return bool(normes & {symbole_normalise(s) for s in libelles})

    if code:
        for u, c, symboles, libelles in liste:
            if c == code and (par_symbole(c, symboles) or par_libelle(libelles)):
                return Rapprochement(u)
    for u, c, symboles, _ in liste:
        if par_symbole(c, symboles):
            return Rapprochement(u)
    for u, _, _, libelles in liste:
        if par_libelle(libelles):
            return Rapprochement(u)
    if not casse:
        return Rapprochement()
    candidats = []  # (unité, symbole local, texte du fichier) qui ne diffèrent que par la casse
    for u, c, symboles, _ in liste:
        paires = [(s, t) for s in dict.fromkeys([*symboles, c]) for t in textes if s and casse_seule(t, s)]
        if paires:
            candidats.append((u, paires))
    if not candidats:
        return Rapprochement()
    u, paires = candidats[0]
    if len(candidats) == 1 and all(casse_sans_risque(t, s) for s, t in paires):
        return Rapprochement(u, casse=paires[0][0], texte=paires[0][1])
    return Rapprochement(ecartee=paires[0][0], texte=paires[0][1])
