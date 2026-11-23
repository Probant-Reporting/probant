"""Assistant de reprise d'un ancien système (administrateur) : charger l'historique de valeurs d'un autre système (logiciel de reporting, Excel
maison, export d'un autre logiciel).

Le fichier est lu tel quel ; l'assistant repère la ligne d'en-têtes et la forme du tableau (une ligne par valeur, années,
organisations ou KPI en colonnes), propose le rôle de chaque colonne, relie les libellés de l'ancien système aux KPI et
aux organisations de l'outil (correspondances mémorisées par système), propose les conversions d'unités et la lecture
des pourcentages. Les valeurs sont alors réécrites en lignes standard (ID KPI, Organisation, Période, Valeur,
Commentaire, Ligne d'origine) et passent par l'import de valeurs habituel : aperçu, campagnes passées créées (clôturées),
valeurs d'historique (origine « import ») sans remplacer une valeur saisie dans l'outil, rapport des lignes rejetées,
journal. Les réglages se gardent dans un profil pour reprendre d'autres fichiers du même système.
"""
import datetime
import difflib
import functools
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation

from parametres.libelles import libelle
from referentiel.models import KPI, Organisation, OrgAlias

from . import fichiers as X
from . import periodes as P
from . import saisie as S
from .models import CorrespondanceReprise

CODES_FORMES = ("longue", "annees", "organisations", "kpis")


def formes():
    """[(code, nom, explication)] des formes de tableau, dans la langue de la personne."""
    return [(c, libelle(f"admin.reprise.forme.{c}"), libelle(f"admin.reprise.forme.{c}_aide")) for c in CODES_FORMES]


def nom_role(role):
    """Nom d'un rôle de colonne (KPI (code), Organisation, Valeur…), dans la langue de la personne."""
    return libelle(f"admin.reprise.role.{role}")


def sens_colonnes(forme):
    """Ce que désigne une colonne de valeurs pour cette forme (« une année (ou une période) »…) ; vide pour « longue »."""
    return libelle(f"admin.reprise.sens.{forme}") if forme in ("annees", "organisations", "kpis") else ""
ROLES_PAR_FORME = {
    "longue": ["kpi_code", "kpi_nom", "organisation", "periode", "valeur", "unite", "commentaire"],
    "annees": ["kpi_code", "kpi_nom", "organisation", "unite", "commentaire"],
    "organisations": ["kpi_code", "kpi_nom", "periode", "unite", "commentaire"],
    "kpis": ["organisation", "periode", "commentaire"],
}
# en-têtes reconnus pour chaque rôle (comparés sans accents, casse ni ponctuation)
SYNONYMES = {
    "kpi_code": ["id", "code", "id kpi", "kpi id", "code kpi", "indicator id", "code indicateur", "id indicateur",
                 "ref", "référence", "reference", "kpi code", "metric id"],
    "kpi_nom": ["indicateur", "kpi", "indicator", "libellé", "libelle", "nom", "intitulé", "label", "metric", "nom du kpi",
                "nom de l'indicateur", "indicator name", "donnée", "question"],
    "organisation": ["organisation", "organization", "entité", "entite", "entity", "site", "société", "societe", "filiale",
                     "périmètre", "perimetre", "business unit", "bu", "établissement", "etablissement", "pays", "country"],
    "periode": ["année", "annee", "exercice", "year", "période", "periode", "period", "date", "mois", "month", "fy",
                "fiscal year", "campagne"],
    "valeur": ["valeur", "value", "résultat", "resultat", "result", "montant", "quantité", "quantite", "donnée chiffrée",
               "data", "réponse", "reponse", "answer", "total"],
    "unite": ["unité", "unite", "unit", "uom", "unités"],
    "commentaire": ["commentaire", "comment", "remarque", "note", "notes", "commentaires", "comments", "observation"],
}
# espagnol (fichiers à reprendre aussi en anglais et en espagnol)
for _role, _mots in {
    "kpi_code": ["codigo", "código", "id indicador", "codigo indicador", "código del indicador", "referencia"],
    "kpi_nom": ["indicador", "nombre", "nombre del indicador", "etiqueta", "dato", "pregunta"],
    "organisation": ["organizacion", "organización", "entidad", "sociedad", "filial", "perimetro", "perímetro", "pais", "país",
                     "establecimiento", "centro"],
    "periode": ["año", "ano", "ejercicio", "periodo", "período", "fecha", "mes", "año fiscal", "campaña"],
    "valeur": ["valor", "resultado", "importe", "cantidad", "respuesta", "dato numérico"],
    "unite": ["unidad", "unidades"],
    "commentaire": ["comentario", "comentarios", "observacion", "observación", "observaciones", "nota", "notas"],
}.items():
    SYNONYMES[_role] += [m for m in _mots if m not in SYNONYMES[_role]]
SOURCE_PAR_DEFAUT = "Ancien système"
NON_APPLICABLE = {"na", "n a", "n/a", "n.a.", "nonapplicable", "non applicable", "not applicable", "no aplica", "no aplicable"}
VIDES = {"", "-", "–", "—", "nc", "n.c.", "nd", "n.d."}


@dataclass
class Reglages:
    """Réglages de l'assistant (gardés en session, et dans un profil de reprise)."""

    source: str = SOURCE_PAR_DEFAUT
    onglet: str = ""
    entete: int = 0  # index de la ligne d'en-têtes (0 = première ligne)
    forme: str = "longue"
    colonnes: dict = field(default_factory=dict)  # {rôle: en-tête}
    exclues: list = field(default_factory=list)  # en-têtes écartés des colonnes de valeurs (formes larges)
    fixes: dict = field(default_factory=dict)  # {"organisation": id, "periode": "2023"} quand aucune colonne ne les donne
    dates: str = "exercice"  # une date désigne l'exercice (son année) ou le mois
    conversions: dict = field(default_factory=dict)  # {"CODE|unité du fichier": "facteur"}
    pourcentages: dict = field(default_factory=dict)  # {"CODE": "fraction" (0,35 = 35 %) ou "cent" (35 = 35 %)}

    @classmethod
    def depuis(cls, d):
        noms = cls.__dataclass_fields__
        return cls(**{k: v for k, v in (d or {}).items() if k in noms})

    def en_dict(self):
        return asdict(self)


# ---------------------------------------------------------------- textes
def _norm(texte):
    """« Électricité (MWh) » → « electricite mwh » : comparaison souple, mots gardés."""
    return _norm_texte(str(texte or ""))


@functools.lru_cache(maxsize=50_000)  # un gros fichier répète les mêmes libellés des centaines de milliers de fois
def _norm_texte(texte):
    t = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9%]+", " ", t).split())


_NON_APPLICABLE_NORM = frozenset(_norm(x) for x in NON_APPLICABLE)


def libelle_et_unite(entete):
    """« Électricité (MWh) » → (« Électricité », « MWh ») ; sans parenthèses finales : (en-tête, "")."""
    t = X.texte(entete)
    m = re.fullmatch(r"(.+?)\s*[\(\[]([^()\[\]]{1,20})[\)\]]\s*", t)
    return (m.group(1).strip(), m.group(2).strip()) if m else (t, "")


def entetes(lignes, entete):
    """En-têtes de la ligne ``entete`` ; une cellule vide devient « Colonne C »."""
    ligne = lignes[entete] if 0 <= entete < len(lignes) else []
    largeur = max((len(l) for l in lignes[entete:entete + 50]), default=0)
    sortie, vus = [], {}
    for j in range(largeur):
        t = X.texte(ligne[j]) if j < len(ligne) else ""
        t = t or f"Colonne {X.get_column_letter(j + 1)}"
        if t in vus:  # en-têtes en double : rendus distincts
            vus[t] += 1
            t = f"{t} ({vus[t]})"
        else:
            vus[t] = 1
        sortie.append(t)
    return sortie


def est_periode(v):
    """Une cellule qui désigne une année ou une période (« 2023 », « FY2023 », « T1 2024 », « mars 2024 »)."""
    if isinstance(v, (datetime.date, datetime.datetime)):
        return True
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return 1990 <= v <= 2100 and float(v).is_integer()
    t = X.texte(v)
    if not t or len(t) > 20 or not re.search(r"(19|20)\d\d", t):
        return False
    return P.lire(t) is not None


# ---------------------------------------------------------------- détection
def detecter_entete(lignes):
    """Index de la ligne d'en-têtes : la première des 20 premières lignes assez remplie (titres, lignes vides et
    remarques au-dessus sont ignorés)."""
    remplies = [sum(1 for v in l if X.texte(v)) for l in lignes[:60]]
    largeur = max(remplies, default=0)
    if largeur == 0:
        return 0
    for i, n in enumerate(remplies[:20]):
        if n >= max(2, largeur * 0.5):
            textes = sum(1 for v in lignes[i] if isinstance(v, str) and X.texte(v)) + sum(1 for v in lignes[i] if est_periode(v))
            if textes >= n * 0.6:
                return i
    return 0


class Contexte:
    """Ce que l'outil connaît, lu une fois : KPI, organisations, correspondances mémorisées du système source."""

    def __init__(self, source):
        self.source = source or SOURCE_PAR_DEFAUT
        self.kpis = {k.code: k for k in KPI.objects.select_related("unite", "type_reponse")}
        self.kpis_min = {c.lower(): c for c in self.kpis}
        self.noms_kpi = {}  # nom normalisé → code
        for k in self.kpis.values():
            for t in [k.libelle] + [v.get("libelle", "") for v in (k.traductions or {}).values()]:
                if t:  # avec et sans l'unité entre parenthèses (« Consommation d'eau (m³) »)
                    self.noms_kpi.setdefault(_norm(t), k.code)
                    self.noms_kpi.setdefault(_norm(libelle_et_unite(t)[0]), k.code)
        self.orgs = {o.id: o for o in Organisation.objects.select_related("niveau")}
        self.noms_org = {}
        for o in self.orgs.values():
            for t in (o.nom, o.nom_court, o.code):
                if t:
                    self.noms_org.setdefault(_norm(t), o.id)
        for a in OrgAlias.objects.all():
            self.noms_org.setdefault(_norm(a.libelle), a.organisation_id)
        self.memoire = {"kpi": {}, "org": {}}
        for c in CorrespondanceReprise.objects.filter(source=self.source):
            self.memoire[c.genre][_norm(c.libelle)] = c

    def est_kpi(self, t):
        t = X.texte(t)
        noms = {_norm(t), _norm(libelle_et_unite(t)[0])}
        return bool(t) and (t.lower() in self.kpis_min or bool(noms & (set(self.noms_kpi) | set(self.memoire["kpi"]))))

    def est_org(self, t):
        n = _norm(t)
        return bool(n) and (n in self.noms_org or n in self.memoire["org"])


def detecter(lignes, entete, ctx):
    """(forme, {rôle: en-tête}) proposés pour la ligne d'en-têtes ``entete``."""
    tetes = entetes(lignes, entete)
    brutes = lignes[entete] if entete < len(lignes) else []
    periodes = sum(1 for v in brutes if est_periode(v))
    orgs = sum(1 for t in tetes if ctx.est_org(t))
    kpis = sum(1 for t in tetes if ctx.est_kpi(t))
    forme = "annees" if periodes >= 2 else "organisations" if orgs >= 2 else "kpis" if kpis >= 2 else "longue"
    colonnes = proposer_colonnes(lignes, entete, forme, ctx)
    return forme, colonnes


def proposer_colonnes(lignes, entete, forme, ctx):
    """{rôle: en-tête} : d'abord par le nom de l'en-tête, puis par le contenu des colonnes restantes."""
    tetes = entetes(lignes, entete)
    roles = ROLES_PAR_FORME[forme]
    donnees = [l for l in lignes[entete + 1:entete + 200] if any(X.texte(v) for v in l)]
    largeur = forme != "longue"
    pris, sortie = set(), {}
    ambigus = {"nom", "code", "id", "total", "data", "kpi"}
    for exact in (True, False):  # l'en-tête exact d'abord, puis son premier mot (« Valeur déclarée », « Unité de mesure »)
        for role in roles:
            if role in sortie:
                continue
            acceptes = {_norm(s) for s in SYNONYMES[role]}
            for j, t in enumerate(tetes):
                if j in pris or (largeur and est_periode(lignes[entete][j] if j < len(lignes[entete]) else None)):
                    continue
                mot = _norm(t).split(" ")[0]
                if (_norm(t) in acceptes) if exact else (mot in acceptes and mot not in ambigus and len(_norm(t)) < 30):
                    sortie[role] = t
                    pris.add(j)
                    break

    def colonne(j):
        return [X.texte(l[j]) for l in donnees if j < len(l) and X.texte(l[j])]
    def brutes(j):
        return [l[j] for l in donnees if j < len(l) and X.texte(l[j])]
    for role, test in (("kpi_code", lambda v: X.texte(v).lower() in ctx.kpis_min), ("organisation", ctx.est_org),
                       ("kpi_nom", ctx.est_kpi), ("periode", est_periode)):
        if role not in roles or role in sortie:
            continue
        for j, t in enumerate(tetes):
            valeurs = brutes(j)
            if j not in pris and valeurs and sum(1 for v in valeurs if test(v)) >= max(1, len(valeurs) * 0.5):
                sortie[role] = t
                pris.add(j)
                break
    if "kpi_code" not in sortie and "kpi_nom" in roles and "kpi_nom" not in sortie:  # première colonne de texte
        for j, t in enumerate(tetes):
            valeurs = colonne(j)
            if j not in pris and valeurs and sum(1 for v in valeurs if X.lire_nombre_importe_ou_none(v) is None) >= len(valeurs) * 0.8:
                sortie["kpi_nom"] = t
                pris.add(j)
                break
    if "valeur" in roles and "valeur" not in sortie:  # colonne la plus numérique
        meilleure = max(((sum(1 for v in colonne(j) if X.lire_nombre_importe_ou_none(v) is not None), j) for j in range(len(tetes))
                         if j not in pris), default=(0, None))
        if meilleure[0]:
            sortie["valeur"] = tetes[meilleure[1]]
    return sortie


def colonnes_de_valeurs(lignes, r):
    """En-têtes des colonnes de valeurs d'une forme large : celles qui ne jouent aucun rôle (pour « Années en colonnes »,
    celles qui désignent une période), moins les colonnes écartées."""
    if r.forme == "longue":
        return []
    tetes = entetes(lignes, r.entete)
    brutes = lignes[r.entete] if r.entete < len(lignes) else []
    roles = set(r.colonnes.values())
    sortie = []
    for j, t in enumerate(tetes):
        if t in roles or t.startswith("Colonne ") and not any(X.texte(l[j]) for l in lignes[r.entete + 1:] if j < len(l)):
            continue
        if r.forme == "annees" and not est_periode(brutes[j] if j < len(brutes) else t):
            continue
        if t in r.exclues:  # colonne décochée : elle n'est pas reprise (elle l'était quand même avant la mise à jour)
            continue
        sortie.append(t)
    return sortie


# ---------------------------------------------------------------- extraction
@dataclass
class Element:
    """Une valeur de l'ancien fichier, avant correspondances et conversions."""

    origine: str
    kpi: str  # libellé du KPI dans l'ancien système (code ou nom)
    kpi_nom: str
    organisation: str
    periode: object
    valeur: object
    unite: str = ""
    commentaire: str = ""


def extraire(lignes, r):
    """Éléments (une valeur chacun) lus selon la forme et les colonnes ; les cellules de valeur vides sont sautées."""
    tetes = entetes(lignes, r.entete)
    j = {role: tetes.index(t) for role, t in r.colonnes.items() if t in tetes}
    brutes = lignes[r.entete] if r.entete < len(lignes) else []
    org_fixe = ""
    if r.fixes.get("organisation"):
        o = Organisation.objects.filter(pk=r.fixes["organisation"]).first()
        org_fixe = o.nom if o else ""
    periode_fixe = r.fixes.get("periode", "")
    valeurs = [(tetes.index(t), t) for t in colonnes_de_valeurs(lignes, r)]
    sortie = []
    for n, l in enumerate(lignes[r.entete + 1:], start=r.entete + 2):
        def cell(role):
            return l[j[role]] if role in j and j[role] < len(l) else None
        if not any(X.texte(v) for v in l):
            continue
        code, nom = X.texte(cell("kpi_code")), X.texte(cell("kpi_nom"))
        base = dict(kpi=code or nom, kpi_nom=nom if code else "", organisation=X.texte(cell("organisation")) or org_fixe,
                    periode=cell("periode") if "periode" in j else periode_fixe, unite=X.texte(cell("unite")),
                    commentaire=X.texte(cell("commentaire")))
        if r.forme == "longue":
            if X.texte(cell("valeur")).lower() not in VIDES:
                sortie.append(Element(origine=f"ligne {n}", valeur=cell("valeur"), **base))
            continue
        for col, entete in valeurs:
            v = l[col] if col < len(l) else None
            if X.texte(v).lower() in VIDES:
                continue
            e = Element(origine=f"ligne {n} · {entete}", valeur=v, **base)
            if r.forme == "annees":
                e.periode = brutes[col] if col < len(brutes) and brutes[col] not in (None, "") else entete
            elif r.forme == "organisations":
                e.organisation = entete
            else:
                e.kpi, e.unite = libelle_et_unite(entete)
                e.kpi_nom = ""
            sortie.append(e)
    return sortie


# ---------------------------------------------------------------- correspondances
@dataclass
class Proposition:
    libelle: str
    nb: int
    exemple: str = ""  # nom à côté du code, unité…
    cible: str = ""  # code du KPI ou identifiant de l'organisation
    ignorer: bool = False
    comment: str = ""  # texte affiché : mémorisé, code identique, nom identique, nom proche…
    sur: bool = True  # proposition sûre (sinon : à vérifier)
    memorise: bool = False  # vient de la mémoire des correspondances de ce système


def proposer_kpis(elements, ctx):
    """Une proposition par libellé de KPI distinct de l'ancien fichier."""
    comptes, exemples = {}, {}
    for e in elements:
        if e.kpi:
            comptes[e.kpi] = comptes.get(e.kpi, 0) + 1
            exemples.setdefault(e.kpi, e.kpi_nom or (libelle("admin.reprise.exemple_unite", unite=e.unite) if e.unite else ""))
    noms = list(ctx.noms_kpi)
    sortie = []
    for lib, nb in comptes.items():
        p = Proposition(lib, nb, exemples.get(lib, ""))
        n = _norm(lib)
        m = ctx.memoire["kpi"].get(n)
        jetons = {t.lower() for t in re.split(r"[\s\-–:;,/|]+", lib) if t} & set(ctx.kpis_min)
        if m is not None:
            p.cible, p.ignorer, p.comment, p.memorise = (m.kpi_id or ""), m.ignorer, libelle("admin.reprise.prop.memorise"), True
        elif lib.lower() in ctx.kpis_min:
            p.cible, p.comment = ctx.kpis_min[lib.lower()], libelle("admin.reprise.prop.code_identique")
        elif n in ctx.noms_kpi:
            p.cible, p.comment = ctx.noms_kpi[n], libelle("admin.reprise.prop.nom_identique")
        elif _norm(libelle_et_unite(lib)[0]) in ctx.noms_kpi:
            p.cible, p.comment = ctx.noms_kpi[_norm(libelle_et_unite(lib)[0])], libelle("admin.reprise.prop.nom_identique_sans_unite")
        elif len(jetons) == 1:
            p.cible, p.comment = ctx.kpis_min[jetons.pop()], libelle("admin.reprise.prop.code_dans_libelle")
        else:
            proches = difflib.get_close_matches(n, noms, n=1, cutoff=0.8)
            if proches:
                ratio = difflib.SequenceMatcher(None, n, proches[0]).ratio()
                p.cible, p.comment, p.sur = ctx.noms_kpi[proches[0]], libelle("admin.reprise.prop.nom_proche", pourcentage=f"{ratio * 100:.0f}"), False
            else:
                p.comment, p.sur = libelle("admin.reprise.prop.a_choisir"), False
        sortie.append(p)
    return sorted(sortie, key=lambda p: (p.sur, p.libelle.lower()))


def proposer_orgs(elements, ctx):
    comptes = {}
    for e in elements:
        if e.organisation:
            comptes[e.organisation] = comptes.get(e.organisation, 0) + 1
    noms = list(ctx.noms_org)
    sortie = []
    for lib, nb in comptes.items():
        p = Proposition(lib, nb)
        n = _norm(lib)
        m = ctx.memoire["org"].get(n)
        if m is not None:
            p.cible, p.ignorer, p.comment, p.memorise = (str(m.organisation_id) if m.organisation_id else ""), m.ignorer, libelle("admin.reprise.prop.memorise"), True
        elif n in ctx.noms_org:
            p.cible, p.comment = str(ctx.noms_org[n]), libelle("admin.reprise.prop.nom_ou_alias_identique")
        elif len(debut := {o for nom, o in ctx.noms_org.items() if nom.startswith(n + " ") or n.startswith(nom + " ")}) == 1:
            p.cible, p.comment, p.sur = str(debut.pop()), libelle("admin.reprise.prop.nom_approchant"), False
        else:
            proches = difflib.get_close_matches(n, noms, n=1, cutoff=0.8)
            if proches:
                ratio = difflib.SequenceMatcher(None, n, proches[0]).ratio()
                p.cible, p.comment, p.sur = str(ctx.noms_org[proches[0]]), libelle("admin.reprise.prop.nom_proche", pourcentage=f"{ratio * 100:.0f}"), False
            else:
                p.comment, p.sur = libelle("admin.reprise.prop.a_choisir"), False
        sortie.append(p)
    return sorted(sortie, key=lambda p: (p.sur, p.libelle.lower()))


def memoriser(source, genre, choix):
    """Mémorise les correspondances choisies : {libellé: (cible, ignorer)} ; cible = code du KPI ou id d'organisation."""
    source = source or SOURCE_PAR_DEFAUT
    for texte, (cible, ignorer) in choix.items():
        champs = {"kpi_id": None, "organisation_id": None, "ignorer": bool(ignorer)}
        if not ignorer and cible:
            champs["kpi_id" if genre == "kpi" else "organisation_id"] = cible
        elif not ignorer:
            CorrespondanceReprise.objects.filter(source=source, genre=genre, libelle=texte[:300]).delete()  # à choisir
            continue
        CorrespondanceReprise.objects.update_or_create(source=source, genre=genre, libelle=texte[:300], defaults=champs)


# ---------------------------------------------------------------- unités et pourcentages
# unité normalisée → (grandeur, facteur vers l'unité de base de la grandeur)
UNITES = {
    "wh": ("energie", Decimal("0.001")), "kwh": ("energie", Decimal(1)), "mwh": ("energie", Decimal(1000)),
    "gwh": ("energie", Decimal(1000000)), "twh": ("energie", Decimal(1000000000)), "gj": ("energie", Decimal("277.7777777778")),
    "mj": ("energie", Decimal("0.2777777778")),
    "g": ("masse", Decimal("0.001")), "kg": ("masse", Decimal(1)), "t": ("masse", Decimal(1000)), "tonne": ("masse", Decimal(1000)),
    "tonnes": ("masse", Decimal(1000)), "kt": ("masse", Decimal(1000000)),
    "gco2e": ("co2", Decimal("0.001")), "kgco2e": ("co2", Decimal(1)), "tco2e": ("co2", Decimal(1000)),
    "ktco2e": ("co2", Decimal(1000000)),
    "l": ("volume", Decimal("0.001")), "litre": ("volume", Decimal("0.001")), "litres": ("volume", Decimal("0.001")),
    "hl": ("volume", Decimal("0.1")), "m3": ("volume", Decimal(1)),
    "eur": ("monnaie", Decimal(1)), "keur": ("monnaie", Decimal(1000)), "meur": ("monnaie", Decimal(1000000)),
    "m": ("distance", Decimal("0.001")), "km": ("distance", Decimal(1)),
    "h": ("duree", Decimal(1)), "heure": ("duree", Decimal(1)), "heures": ("duree", Decimal(1)), "j": ("duree", Decimal(8)),
}


def norm_unite(u):
    t = unicodedata.normalize("NFKD", str(u or "").replace("€", "eur").replace("³", "3").replace("²", "2"))
    t = t.encode("ascii", "ignore").decode().lower().replace(" ", "")
    t = re.sub(r"^(kt|t|kg|g)?eqco2", r"\1co2e", t).replace("co2eq", "co2e")  # teqCO2, kgCO2eq → tco2e, kgco2e
    return {"k€": "keur", "m€": "meur", "€": "eur", "tco2": "tco2e", "kgco2": "kgco2e"}.get(t, t)


def facteur(de, vers):
    """Facteur pour passer de l'unité ``de`` à l'unité ``vers`` (MWh → kWh : 1000) ; 1 si identiques, None si inconnu."""
    a, b = norm_unite(de), norm_unite(vers)
    if a == b:
        return Decimal(1)
    if a in UNITES and b in UNITES and UNITES[a][0] == UNITES[b][0]:
        return (UNITES[a][1] / UNITES[b][1]).normalize()
    return None


def conversions_a_regler(elements, ctx, r):
    """[(clé, KPI, unité du fichier, facteur proposé)] pour chaque couple dont l'unité diffère de celle du KPI, et
    [(KPI, lecture proposée, exemples)] pour les KPI en pourcentage (KPI reliés par les correspondances)."""
    relies = correspondances(ctx, elements)[0]
    unites, pourcents = {}, {}
    for e in elements:
        k = ctx.kpis.get(relies.get(e.kpi) or "")
        if k is None:
            continue
        if k.est_pourcentage:
            v = X.lire_nombre_importe_ou_none(e.valeur)
            if v is not None:
                pourcents.setdefault(k.code, (k, [], e.unite))[1].append(v)
            continue
        if e.unite and k.est_numerique and norm_unite(e.unite) != norm_unite(k.symbole):
            unites.setdefault(f"{k.code}|{e.unite}", (k, e.unite))
    sortie_u = []
    for cle, (k, u) in sorted(unites.items()):
        f = r.conversions.get(cle)
        proposee = facteur(u, k.symbole)
        sortie_u.append((cle, k, u, f if f is not None else ("" if proposee is None else format(proposee, "f"))))
    sortie_p = []
    for code, (k, vals, unite) in sorted(pourcents.items()):
        lecture = r.pourcentages.get(code) or lecture_pourcentage(vals, unite)
        sortie_p.append((k, lecture, ", ".join(X.texte(X.nombre(v)) for v in vals[:4])))
    return sortie_u, sortie_p


def lecture_pourcentage(valeurs, unite=""):
    """« fraction » si les valeurs s'écrivent de 0 à 1 (0,35 pour 35 %), sinon « cent » (35 pour 35 %)."""
    if norm_unite(unite) == "%":
        return "cent"
    if valeurs and all(abs(v) <= Decimal("1.5") for v in valeurs) and any(v != v.to_integral() for v in valeurs):
        return "fraction"
    return "cent"


# ---------------------------------------------------------------- transformation en lignes standard
ENTETES_STANDARD = ["ID KPI", "Organisation", "Période", "Valeur", "Commentaire", "Ligne d'origine"]


@dataclass
class Transformation:
    onglets: dict
    nb_elements: int = 0
    ignorees: int = 0
    non_reliees_kpi: set = field(default_factory=set)
    non_reliees_org: set = field(default_factory=set)


def correspondances(ctx, elements):
    """({libellé KPI: code ou None si ignoré}, {libellé organisation: nom ou None si ignorée}) : mémoire, sinon proposition
    sûre ; un libellé absent n'est pas relié."""
    kpis, orgs = {}, {}
    for p in proposer_kpis(elements, ctx):
        if p.ignorer:
            kpis[p.libelle] = None
        elif p.cible and (p.sur or p.memorise):
            kpis[p.libelle] = p.cible
    for p in proposer_orgs(elements, ctx):
        if p.ignorer:
            orgs[p.libelle] = None
        elif p.cible and (p.sur or p.memorise):
            o = ctx.orgs.get(int(p.cible))
            if o is not None:
                orgs[p.libelle] = o.nom
    return kpis, orgs


def transformer(elements, r, ctx):
    """Lignes standard pour l'import de valeurs : correspondances, conversions d'unités, pourcentages de 0 à 100,
    périodes lisibles. Les libellés ignorés sont écartés ; ceux qui ne sont reliés à rien restent (rejetés à l'aperçu)."""
    kpis, orgs = correspondances(ctx, elements)
    t = Transformation({"Reprise": [list(ENTETES_STANDARD)]}, len(elements))
    lignes = t.onglets["Reprise"]
    lectures = {}
    par_code = {}  # valeurs lues de chaque KPI en pourcentage, en un seul passage (un gros fichier a des dizaines de milliers de lignes)
    for x in elements:
        code = kpis.get(x.kpi)
        if code and getattr(ctx.kpis.get(code), "est_pourcentage", False):
            par_code.setdefault(code, []).append(x.valeur)
    for e in elements:
        k = ctx.kpis.get(kpis.get(e.kpi) or "") if e.kpi in kpis else None
        if (e.kpi in kpis and kpis[e.kpi] is None) or (e.organisation in orgs and orgs[e.organisation] is None):
            t.ignorees += 1
            continue
        if k is not None and k.est_pourcentage and k.code not in lectures:
            vals = [X.lire_nombre_importe_ou_none(v) for v in par_code.get(k.code, ())]
            lectures[k.code] = r.pourcentages.get(k.code) or lecture_pourcentage([v for v in vals if v is not None], e.unite)
        if k is None:
            t.non_reliees_kpi.add(e.kpi)
        if e.organisation not in orgs:
            t.non_reliees_org.add(e.organisation)
        lignes.append([k.code if k else e.kpi, orgs.get(e.organisation, e.organisation), _periode(e.periode, r),
                       _valeur(e, k, r, lectures), e.commentaire or None, e.origine])
    return t


def _periode(v, r):
    if isinstance(v, datetime.datetime):
        v = v.date()
    if isinstance(v, datetime.date):
        return str(v.year) if r.dates == "exercice" else f"{v.month:02d}/{v.year}"
    if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer():
        return str(int(v))
    return X.texte(v)


def _valeur(e, k, r, lectures):
    if isinstance(e.valeur, str) and _norm(X.texte(e.valeur)) in _NON_APPLICABLE_NORM:
        return "N/A"
    if k is None or not k.est_numerique:
        return e.valeur
    v = X.lire_nombre_importe_ou_none(e.valeur)
    if v is None:
        return e.valeur  # texte : rejeté à l'aperçu (« Valeur non numérique »)
    lu = v
    if k.est_pourcentage:
        v = v * 100 if lectures.get(k.code) == "fraction" else v
    elif e.unite and norm_unite(e.unite) != norm_unite(k.symbole):
        f = r.conversions.get(f"{k.code}|{e.unite}")
        f = decimal_lu(f) if f not in (None, "") else facteur(e.unite, k.symbole)
        if f is not None:
            v = v * f
    # texte au séparateur ambigu (« 1,234 ») sans conversion : passé tel quel à l'import, qui le lit de la même façon
    # (langue de l'écran) et le signale dans l'aperçu, au lieu d'un nombre déjà lu en silence
    if v == lu and S.separateur_ambigu(e.valeur):
        return e.valeur
    return v


def decimal_lu(t):
    try:
        return Decimal(str(t).replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None


def retoucher_motifs(analyse, transformation):
    """Motifs de l'aperçu plus parlants pour une reprise : libellé non relié (étape Correspondances)."""
    for l in analyse.lignes:
        if l.action != "rejet":
            continue
        if l.kpi is None and l.kpi_id in transformation.non_reliees_kpi:
            l.motif = libelle("admin.reprise.motif.kpi_non_relie", kpi=l.kpi_id)
        elif l.org is None and l.organisation in transformation.non_reliees_org:
            l.motif = (libelle("admin.reprise.motif.org_non_reliee", organisation=l.organisation)
                       if l.organisation else libelle("admin.reprise.motif.org_manquante"))


def proposer_dates(lignes, r):
    """« mois » si la colonne des périodes contient des dates de plusieurs mois d'une même année, sinon « exercice »."""
    tetes = entetes(lignes, r.entete)
    t = r.colonnes.get("periode")
    if t not in tetes:
        return "exercice"
    j = tetes.index(t)
    mois = {}
    for l in lignes[r.entete + 1:]:
        v = l[j] if j < len(l) else None
        if isinstance(v, (datetime.date, datetime.datetime)):
            mois.setdefault(v.year, set()).add(v.month)
    return "mois" if any(len(m) > 1 for m in mois.values()) else "exercice"


def apercu_lignes(lignes, entete, avant=2, apres=6):
    """Lignes autour de la ligne d'en-têtes, pour la montrer à l'écran : [(numéro, [cellules en texte], est l'en-tête)]."""
    debut = max(0, entete - avant)
    largeur = max((len(l) for l in lignes[debut:entete + apres + 1]), default=0)
    return [(i + 1, [X.texte(l[j]) if j < len(l) else "" for j in range(largeur)], i == entete)
            for i, l in enumerate(lignes[debut:entete + apres + 1], start=debut)]


# ---------------------------------------------------------------- vérification du fichier et modèle d'adaptation
def colonnes_a_ecarter(lignes, r, ctx):
    """Colonnes d'une forme large qui ne sont pas des valeurs : ni une organisation (ou un KPI) reconnue, ni des nombres
    (« Thème », « Formule », « Description »). Elles sont écartées d'office ; la personne peut les reprendre."""
    if r.forme not in ("organisations", "kpis"):
        return []
    tetes = entetes(lignes, r.entete)
    position = {t: j for j, t in enumerate(tetes)}
    donnees = [l for l in lignes[r.entete + 1:r.entete + 200] if any(X.texte(v) for v in l)]
    reconnu = ctx.est_org if r.forme == "organisations" else lambda t: ctx.est_kpi(libelle_et_unite(t)[0]) or ctx.est_kpi(t)
    sortie = []
    for t in colonnes_de_valeurs(lignes, Reglages.depuis({**r.en_dict(), "exclues": []})):
        if reconnu(t):
            continue
        valeurs = [l[position[t]] for l in donnees if position[t] < len(l) and X.texte(l[position[t]])]
        nombres = sum(1 for v in valeurs if X.lire_nombre_importe_ou_none(v) is not None or _norm(v) in _NON_APPLICABLE_NORM)
        if not valeurs or nombres < len(valeurs) * 0.5:
            sortie.append(t)
    return sortie


def annee_de_l_onglet(nom):
    """« 2025 Data » → « 2025 » : l'année que porte le nom de l'onglet, quand aucune colonne ne la donne."""
    m = re.findall(r"(?<!\d)((?:19|20)\d\d)(?!\d)", nom or "")
    return m[0] if len(set(m)) == 1 else ""


@dataclass
class Verification:
    """Ce que l'outil a compris d'un fichier déposé, avant toute reprise."""

    verdict: str = "ok"  # « ok » : repris tel quel ; « points » : des points à régler ; « non » : format non reconnu
    forme: str = ""
    points: list = field(default_factory=list)  # [(niveau « ok », « attention » ou « bloquant », titre, détail)]
    nb_kpi: int = 0
    nb_kpi_reconnus: int = 0
    nb_org: int = 0
    nb_org_reconnues: int = 0
    nb_valeurs: int = 0

    @property
    def reste_a_relier(self):
        return (self.nb_kpi - self.nb_kpi_reconnus) + (self.nb_org - self.nb_org_reconnues)


def verifier(lignes, r, ctx, manques=()):
    """Verdict et points de la vérification d'un fichier lu avec les réglages ``r`` ; ``manques`` : ce qui empêche de
    le lire (messages de l'étape, bloquants)."""
    v = Verification(forme=dict((c, n) for c, n, _ in formes()).get(r.forme, r.forme))
    for m in manques:
        v.points.append(("bloquant", libelle("admin.reprise.verif.manque"), m))
    if manques:
        v.verdict = "non"
        return v
    elements = extraire(lignes, r)
    v.nb_valeurs = len(elements)
    if not elements:
        v.verdict = "non"
        v.points.append(("bloquant", libelle("admin.reprise.verif.manque"), libelle("admin.reprise.verif.aucune_valeur")))
        return v

    def relie(p):
        return p.ignorer or bool(p.cible and (p.sur or p.memorise))

    kpis, orgs = proposer_kpis(elements, ctx), proposer_orgs(elements, ctx)
    v.nb_kpi, v.nb_kpi_reconnus = len(kpis), sum(1 for p in kpis if relie(p))
    v.nb_org, v.nb_org_reconnues = len(orgs), sum(1 for p in orgs if relie(p))
    colonnes_kpi = " · ".join(f"« {r.colonnes[c]} »" for c in ("kpi_code", "kpi_nom") if c in r.colonnes)
    v.points.append(("ok" if v.nb_kpi_reconnus == v.nb_kpi else "attention", libelle("admin.reprise.verif.kpi"),
                     libelle("admin.reprise.verif.kpi_detail", colonnes=colonnes_kpi or libelle("admin.reprise.verif.en_colonnes"),
                             n=v.nb_kpi, reconnus=v.nb_kpi_reconnus)))
    origine_org = (f"« {r.colonnes['organisation']} »" if "organisation" in r.colonnes else libelle("admin.reprise.verif.en_colonnes")
                   if r.forme == "organisations" else libelle("admin.reprise.verif.fixe"))
    v.points.append(("ok" if v.nb_org_reconnues == v.nb_org else "attention", libelle("admin.reprise.verif.org"),
                     libelle("admin.reprise.verif.org_detail", colonnes=origine_org, n=v.nb_org, reconnues=v.nb_org_reconnues)))
    if r.forme == "annees":
        annees = sorted({_periode(e.periode, r) for e in elements})
        v.points.append(("ok", libelle("admin.reprise.verif.annee"), libelle("admin.reprise.verif.annee_colonnes", liste=", ".join(annees[:8]))))
    elif "periode" in r.colonnes:
        v.points.append(("ok", libelle("admin.reprise.verif.annee"), libelle("admin.reprise.verif.annee_colonne", colonne=r.colonnes["periode"])))
    else:
        v.points.append(("attention", libelle("admin.reprise.verif.annee"), libelle("admin.reprise.verif.annee_fixe", annee=r.fixes.get("periode", ""))))
    if "unite" in r.colonnes:
        v.points.append(("ok", libelle("admin.reprise.verif.unite"), libelle("admin.reprise.verif.unite_colonne", colonne=r.colonnes["unite"])))
    if r.exclues:
        v.points.append(("attention", libelle("admin.reprise.verif.ecartees", n=len(r.exclues)),
                         libelle("admin.reprise.verif.ecartees_detail", liste=", ".join(f"« {t} »" for t in r.exclues[:6])
                                 + (" …" if len(r.exclues) > 6 else ""))))
    textes = sum(1 for e in elements if isinstance(e.valeur, str) and X.lire_nombre_importe_ou_none(e.valeur) is None
                 and _norm(e.valeur) not in _NON_APPLICABLE_NORM and _norm(e.valeur) not in {"oui", "non", "yes", "no", "si"})
    if textes:
        v.points.append(("attention", libelle("admin.reprise.verif.textes", n=textes), libelle("admin.reprise.verif.textes_detail")))
    if any(niveau != "ok" for niveau, _, _ in v.points):
        v.verdict = "points"
    return v


def modele_adaptation(annees):
    """Modèle d'adaptation : un classeur au format « une colonne par année », déjà rempli avec les KPI saisis (code,
    nom, unité) et, pour chacun, les organisations de son niveau de saisie. Il reste à coller les valeurs ; déposé dans
    l'assistant, il est reconnu sans réglage (codes de l'outil)."""
    wb = X.classeur()
    ws = wb.create_sheet(libelle("admin.reprise.modele.onglet")[:31])
    tetes = [libelle(f"admin.reprise.modele.col.{c}") for c in ("code_kpi", "kpi", "unite", "code_org", "organisation")] + [str(a) for a in annees]
    X.ajouter(ws, tetes)
    X.entetes(ws)
    orgs = {}
    for o in Organisation.objects.filter(actif=True).order_by("nom"):
        orgs.setdefault(o.niveau_id, []).append(o)
    kpis = KPI.objects.filter(actif=True).select_related("unite", "type_saisie", "type_reponse").order_by("code")
    for k in kpis:
        if k.est_calcule or getattr(k, "est_texte", False):  # ni les calculs (l'outil les refait), ni les textes rédigés
            continue
        for o in orgs.get(k.granularite_id, []):
            X.ajouter(ws, [k.code, k.nom, k.symbole or "", o.code, o.nom] + [None] * len(annees))
    X.largeurs(ws, [16, 48, 12, 18, 30] + [14] * len(annees))
    ws.freeze_panes = "F2"
    ws.auto_filter.ref = ws.dimensions
    aide = wb.create_sheet(libelle("admin.reprise.modele.onglet_aide")[:31])
    for cle in ("aide_1", "aide_2", "aide_3", "aide_4"):
        X.ajouter(aide, [libelle(f"admin.reprise.modele.{cle}")])
    X.largeurs(aide, [110])
    return X.reponse_excel(wb, X.nom_fichier(libelle("admin.reprise.modele.fichier")))

