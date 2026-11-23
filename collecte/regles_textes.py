"""Règles de cohérence : condition d'une règle (pour reconnaître un même contrôle sous deux noms) et textes des règles
des modèles de la bibliothèque dans la langue de la personne qui lit.

Une règle (``RegleCoherence``) n'a pas de traductions : son nom et son explication sont enregistrés dans une seule langue,
celle de l'installation au moment où le modèle a été installé (ou celle de la démo). Les règles des modèles fournis ont
pourtant leurs textes en français et en anglais (définitions de ``referentiel/bibliotheque``, 4e et 5e éléments d'une
règle, catalogue commun compris ; table anglaise ``catalogue_anglais.T`` pour une explication écrite en français seulement). Un texte enregistré qui est l'un de ces
textes, dans n'importe quelle langue, s'affiche dans la langue de l'interface, puis en anglais, puis en français (langue de
référence de la bibliothèque) ; un texte changé par l'administrateur (il n'est plus celui du modèle) s'affiche tel quel.

Une règle renommée par l'outil à l'installation (« Nom (CODE) », même nom et autre contenu qu'une règle existante) garde
son suffixe ; seul le nom avant le suffixe est traduit.

Forme attendue des textes d'une règle d'un modèle (définitions) : ``(gauche, opérateur, droite, description, nom_en)`` où
``description`` est un couple (français, anglais) ou un dictionnaire {langue: texte}, et ``nom_en`` le nom anglais ou un
dictionnaire {langue: nom}. Dans un paquet de la bibliothèque (``socles.paquet``), ``nom`` et ``description`` d'une règle
sont le texte de la langue de référence du paquet (le français : lu tel quel par les versions d'avant) et les autres
langues sont dans ``traductions`` {langue: {champ: texte}} ; un paquet exporté d'une installation n'a qu'un texte ; un
``nom`` écrit {langue: texte} est lu aussi (``textes_regle``). À l'installation, la règle reçoit le texte de la langue de
référence de l'installation s'il existe (``texte_regle``).
"""
import re
from functools import lru_cache

from parametres import langues as L

REFERENCE = "fr"  # langue de référence des modèles de la bibliothèque
SUFFIXE = re.compile(r"^(?P<nom>.+?) \((?P<suffixe>[^()]+)\)$")


# ---------------------------------------------------------------- condition d'une règle
def formule_normalisee(texte):
    """Formule d'une partie de règle sans espaces. La casse est gardée : les codes des KPI y sont sensibles (« [abc] » et
    « [ABC] » sont deux KPI) et la syntaxe des formules n'a aucun mot dont la casse serait libre."""
    return re.sub(r"\s+", "", texte or "")


def condition(gauche, operateur, droite, tolerance, niveau_id):
    """Clé d'une condition : deux règles qui ont la même sont un seul contrôle, quel que soit leur nom."""
    from decimal import Decimal, InvalidOperation

    try:
        t = Decimal(str(tolerance or 0)).normalize()
    except (InvalidOperation, ValueError):
        t = tolerance
    return formule_normalisee(gauche), operateur or "<=", formule_normalisee(droite), t, niveau_id or ""


def condition_de(regle):
    return condition(regle.gauche, regle.operateur, regle.droite, regle.tolerance, regle.niveau_id)


# ---------------------------------------------------------------- textes des règles des modèles fournis
def _textes(valeur, francais=""):
    """{langue: texte} d'un texte de définition : couple (fr, en), dictionnaire, ou texte seul (français)."""
    if isinstance(valeur, dict):
        return {lg: t for lg, t in valeur.items() if isinstance(t, str) and t}
    if isinstance(valeur, (tuple, list)):
        return {lg: t for lg, t in zip((REFERENCE, "en"), valeur) if isinstance(t, str) and t}
    return {REFERENCE: valeur} if isinstance(valeur, str) and valeur else ({REFERENCE: francais} if francais else {})


def _ajouter(index, textes):
    """Range un {langue: texte} sous chacun de ses textes ; un même texte déjà rangé (autre source) reçoit les langues qui
    lui manquent."""
    textes = {lg: t for lg, t in textes.items() if isinstance(t, str) and t.strip()}
    if not textes:
        return
    commun = next((index[_cle(t)] for t in textes.values() if _cle(t) in index), None)
    if commun is None:
        commun = dict(textes)
    else:
        for lg, t in textes.items():
            commun.setdefault(lg, t)
    for t in commun.values():
        index[_cle(t)] = commun


@lru_cache(maxsize=1)
def catalogue():
    """{"nom" | "description": {texte normalisé: {langue: texte}}} des règles des modèles de la bibliothèque, lu une fois
    par processus : les définitions (modèles fournis et retirés de l'offre) et les paquets JSON de la bibliothèque dont les
    règles portent leurs textes par langue."""
    import json

    from referentiel.bibliotheque import documentation as DOC
    from referentiel.bibliotheque import socles as S

    from .paquets import modele

    sortie = {"nom": {}, "description": {}}
    for chemin in sorted(modele.BIBLIOTHEQUE.glob("*.json")):
        try:
            d = json.loads(chemin.read_text(encoding="utf-8"))
            regles, langue = d.get("regles") or [], d.get("langue_reference") or REFERENCE
        except (OSError, ValueError, AttributeError):
            continue
        for r in regles if isinstance(regles, list) else []:
            for champ in ("nom", "description"):
                textes = textes_regle(r, champ, langue)
                if len(textes) > 1:  # un texte seul ne traduit rien
                    _ajouter(sortie[champ], textes)
    for nom, r in S.REGLES.items():
        noms = {REFERENCE: nom}
        en = r[4] if len(r) > 4 else ""  # nom anglais : 5e élément de la règle (catalogue commun et modèles)
        noms.update(_textes(en) if isinstance(en, dict) else {"en": en} if en else {})
        descriptions = _textes(r[3])
        if isinstance(r[3], str) and r[3]:
            try:
                descriptions.setdefault("en", DOC.tr(r[3]))
            except KeyError:
                pass
        for champ, textes in (("nom", noms), ("description", descriptions)):
            _ajouter(sortie[champ], textes)
    return sortie


def _cle(texte):
    return re.sub(r"\s+", " ", texte or "").strip().casefold()


def _dans_la_langue(textes, langue=None):
    """Texte d'un {langue: texte} : langue de l'interface (et ses replis, comme les contenus), puis anglais, puis la langue
    de référence de la bibliothèque."""
    for lg in (*L.langues_candidates(langue), "en", REFERENCE):
        if textes.get(lg):
            return textes[lg]
    return next(iter(textes.values()), "")


def traduire(texte, champ="nom", langue=None):
    """Texte enregistré d'une règle (``champ`` : « nom » ou « description ») dans la langue de la personne qui lit s'il est
    celui d'une règle d'un modèle de la bibliothèque, sinon tel quel."""
    if not texte or not isinstance(texte, str):
        return texte or ""
    cat = catalogue()[champ]
    textes = cat.get(_cle(texte))
    if textes:
        return _dans_la_langue(textes, langue)
    m = SUFFIXE.match(texte) if champ == "nom" else None
    if m and cat.get(_cle(m["nom"])):
        return f"{_dans_la_langue(cat[_cle(m['nom'])], langue)} ({m['suffixe']})"
    return texte


def texte_paquet(valeur, langue_paquet):
    """Nom ou description d'une règle lu dans un paquet (texte, ou {langue: texte}) : le texte enregistré dans l'installation,
    dans sa langue de référence, sinon celle du paquet, sinon le premier."""
    if isinstance(valeur, dict):
        textes = {lg: t for lg, t in valeur.items() if isinstance(t, str) and t.strip()}
        return (textes.get(L.reference()) or textes.get(langue_paquet) or next(iter(textes.values()), "")).strip()
    return valeur.strip() if isinstance(valeur, str) else ""


def textes_regle(regle, champ, langue_paquet):
    """{langue: texte} du nom ou de l'explication (``champ``) d'une règle d'un paquet. Forme d'un paquet de la bibliothèque
    (``socles.paquet``) : ``nom`` et ``description`` dans la langue de référence du paquet, les autres langues dans
    ``traductions`` {langue: {champ: texte}}, comme les textes traduits des objets de l'outil ; un ``nom`` déjà écrit
    {langue: texte} est lu aussi. Un paquet exporté d'une installation, ou d'une version d'avant, n'a qu'un texte."""
    if not isinstance(regle, dict):
        return {}
    valeur = regle.get(champ)
    if isinstance(valeur, dict):
        textes = {lg: t.strip() for lg, t in valeur.items() if isinstance(t, str) and t.strip()}
    else:
        textes = {langue_paquet: valeur.strip()} if isinstance(valeur, str) and valeur.strip() else {}
    traductions = regle.get("traductions")
    for lg, d in (traductions.items() if isinstance(traductions, dict) else ()):
        t = d.get(champ) if isinstance(d, dict) else None
        if isinstance(lg, str) and isinstance(t, str) and t.strip():
            textes.setdefault(lg, t.strip())
    return textes


def texte_regle(regle, champ, langue_paquet):
    """Texte enregistré dans l'installation pour le nom ou l'explication d'une règle d'un paquet : celui de la langue de
    référence de l'installation s'il existe, sinon celui de la langue du paquet (``textes_regle``)."""
    return texte_paquet(textes_regle(regle, champ, langue_paquet), langue_paquet)
