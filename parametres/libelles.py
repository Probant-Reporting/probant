"""Libellés de l'interface dans des fichiers de langue : tout le site, une zone par fichier (docs/translation.md).

Fichiers : ``libelles/<zone>.<langue>.json`` (ex. ``libelles/visualisation.fr.json``, ``libelles/cadre.es.json``), des
clés à plat (« visu.vue.nouvelle ») qui commencent par le préfixe de leur zone (``parametres.zones_langue``), avec des paramètres
``{nom}`` et, pour un texte qui dépend d'un nombre, le pluriel ``{"one": …, "other": …}`` (0 et 1 au singulier si la clé
``format.zero_singulier`` de la langue vaut « 1 », comme le français et le filtre ``pluriel`` ; sinon 1 seul). Une langue
est proposée seulement si ses fichiers ont exactement les clés, paramètres et balises de l'anglais (``controle_libelles``,
``langues_disponibles``) ; une zone sans fichier dans une langue se replie sur l'anglais.

- ``libelle(cle, langue=None, n=None, **valeurs)`` : le texte, avec repli : langue demandée (par défaut la langue de
  l'interface, celle de la personne : ``parametres.langues.interface``) → langue par défaut de l'installation →
  français ; la clé elle-même si elle n'existe nulle part (visible, jamais d'erreur).
- ``libelles(prefixe, langue=None)`` : {clé: texte ou {"one", "other"}} des clés qui commencent par ``prefixe``, avec le
  même repli (dictionnaire passé au JavaScript, qui fait lui-même le remplacement des paramètres et le pluriel).
- Gabarits : ``{% libelle "visu.vue.renommer" %}`` (``{% libelle "visu.deplace" titre=x n=3 %}``,
  ``{% libelle "cadre.deconnexion" as texte %}`` pour un attribut) ; ``{{ objet|choix:"statut" }}`` : valeur d'une liste de choix
  d'un modèle (clés ``choix.<modèle>.<champ>.<valeur>``, repli sur le libellé du modèle).

Les fichiers sont lus une fois (``lru_cache``) ; la langue de l'interface vient de ``parametres.langues``.
"""
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from . import langues as L

REPLI = "en"  # texte absent d'une langue : en anglais, la langue de base 
DOSSIERS = ("libelles",)
PARAMETRE = re.compile(r"\{(\w+)\}")


def fichiers(langue):
    base = Path(settings.BASE_DIR)
    return sorted(p for d in DOSSIERS for p in (base / d).glob(f"*.{langue}.json"))


@lru_cache(maxsize=None)
def table(langue):
    """{clé: texte ou {"one", "other"}} de tous les fichiers de cette langue ({} si aucun). Un fichier abîmé (JSON invalide,
    pas un objet) d'une langue autre que l'anglais et le français est ignoré (la langue n'est alors plus proposée :
    ``langues_disponibles``) ; pour ces deux-là, l'erreur est levée."""
    from . import controle_libelles as C

    sortie = {}
    for p in fichiers(langue):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                raise ValueError("not a JSON object")
        except ValueError:
            if (langue or "").split("-")[0] in C.ESSENTIELLES:
                raise
            logging.getLogger("parametres").warning("Language file %s is not valid: ignored", p.name)
            continue
        sortie.update({k: v for k, v in d.items() if C.forme_valide(v)})
    return sortie


@lru_cache(maxsize=None)
def langues_disponibles():
    """Langues proposées : celles dont les fichiers de libellés sont complets (``controle_libelles.est_complete`` : toutes
    les zones, mêmes clés, paramètres et balises que l'anglais). Une langue incomplète n'est jamais proposée, sans réglage
    à la main. Lues une fois par processus comme ``table`` (elles ne changent qu'avec une mise à jour de l'outil) : relire
    le dossier à chaque nombre affiché ralentissait les longs traitements hors requête (import en arrière-plan, commandes)
    d'un facteur trois."""
    from . import controle_libelles as C

    return sorted((c for c in C.langues_presentes() if c == REPLI or C.est_complete(c)), key=lambda c: (c != REPLI, c))


def candidates(langue=None):
    vues = []
    try:
        demandees = (langue or L.interface(), L.defaut(), REPLI)
    except Exception:  # noqa: BLE001 - base pas encore prête (migrations) : langue par défaut des installations
        demandees = (langue, settings.LANGUE_PAR_DEFAUT, REPLI)
    proposees = langues_disponibles()  # une langue incomplète ne sert jamais, même pour quelques clés
    for l in demandees:
        for x in (l, (l or "").split("-")[0]):  # « pt-BR » se replie sur « pt »
            if x and x not in vues and (x in proposees or x == REPLI):
                vues.append(x)
    return vues


def langue_effective(langue=None):
    """Première langue de repli qui a des libellés (pour ``lang`` et les nombres)."""
    return next((l for l in candidates(langue) if table(l)), REPLI)


def zero_singulier(langue):
    """Vrai si 0 et 1 prennent le singulier (français) : réglage de la langue, clé « format.zero_singulier » ("1" ou "0")."""
    for l in (langue, (langue or "").split("-")[0], REPLI):
        t = table(l).get("format.zero_singulier") if l else None
        if t is not None:
            return t == "1"
    return False


def forme(texte, n, langue):
    """Texte d'un pluriel {"one", "other"} pour ``n``."""
    if not isinstance(texte, dict):
        return texte
    if n is None:
        return texte.get("other") or texte.get("one") or ""
    try:
        a = abs(float(n))
    except (TypeError, ValueError):
        a = 2
    singulier = a < 2 if zero_singulier(langue) else a == 1
    return texte.get("one" if singulier else "other") or texte.get("other") or ""


def remplacer(texte, valeurs):
    return PARAMETRE.sub(lambda m: str(valeurs[m.group(1)]) if m.group(1) in valeurs else m.group(0), texte)


def gabarit(cle, langue=None, n=None):
    """Texte du fichier pour ``cle`` (forme du pluriel choisie), paramètres non remplacés ; la clé si elle n'existe pas."""
    for l in candidates(langue):
        t = table(l).get(cle)
        if t is not None:
            return forme(t, n, l)
    return cle


def libelle(cle, langue=None, n=None, **valeurs):
    for l in candidates(langue):
        t = table(l).get(cle)
        if t is not None:
            if n is not None:
                valeurs.setdefault("n", n)
            return remplacer(forme(t, n, l), valeurs)
    return cle


def libelles(prefixe="", langue=None):
    sortie = {}
    for l in reversed(candidates(langue)):  # la langue demandée en dernier : elle l'emporte
        sortie.update({k: v for k, v in table(l).items() if k.startswith(prefixe)})
    return sortie


# ---------------------------------------------------------------- texte affiché → code (motif enregistré au journal)
CODE = "§"  # début d'un motif enregistré par son code (``coder``), recomposé à l'affichage (``recomposer``)
CODE_MAX = 1500  # caractères d'un motif codé ; au-delà, le texte tel quel


@lru_cache(maxsize=16)
def _gabarits_inverses(langue):
    """({texte sans paramètre: clé}, [(expression, clé)]) des libellés d'une langue (formes du pluriel comprises), les
    plus longs d'abord : un texte affiché retrouve sa clé et ses paramètres. Fait une fois par langue et par processus."""
    exacts, motifs = {}, []
    for cle, v in table(langue).items():
        for t in (v.values() if isinstance(v, dict) else (v,)):
            if not isinstance(t, str) or not t or "\n" in t or len(t) > 600:
                continue
            morceaux = PARAMETRE.split(t)
            if len(morceaux) == 1:
                exacts.setdefault(t, cle)
                continue
            if not "".join(morceaux[0::2]).strip():
                continue  # que des paramètres : reconnaîtrait n'importe quel texte
            vus, expr = set(), []
            for i, m in enumerate(morceaux):
                if i % 2 == 0:
                    expr.append(re.escape(m))
                else:
                    expr.append(f"(?P={m})" if m in vus else f"(?P<{m}>.+?)")
                    vus.add(m)
            motifs.append((len("".join(morceaux[0::2])), re.compile("^" + "".join(expr) + "$", re.S), cle))
    motifs.sort(key=lambda x: -x[0])
    return exacts, [(e, c) for _, e, c in motifs]


def retrouver(texte, langue=None):
    """(clé, paramètres) du libellé qui a produit ``texte`` dans la langue courante (ou ``langue``), ou None."""
    # langue donnée : lue dans les fichiers seulement (aucune lecture en base : sert aussi dans une migration)
    l = langue if langue in langues_disponibles() else (candidates()[0] if not langue else REPLI)
    exacts, motifs = _gabarits_inverses(l)
    if texte in exacts:
        return exacts[texte], {}
    for expr, cle in motifs:
        m = expr.match(texte)
        if m:
            return cle, m.groupdict()
    return None


def coder(messages, langue=None):
    """Motifs affichés (textes dans la langue de la personne) → texte enregistré qui ne dépend d'aucune langue :
    « § » suivi de la liste JSON [[clé, paramètres] ou [texte inconnu]] ; recomposé à l'affichage (``recomposer``)."""
    sortie = []
    for t in messages:
        trouve = retrouver(t, langue)
        sortie.append([trouve[0], {k: v[:300] for k, v in trouve[1].items()}] if trouve else [t[:500]])
    code = CODE + json.dumps(sortie, ensure_ascii=False, separators=(",", ":"))
    return code if len(code) <= CODE_MAX else " ".join(messages)[:500]


def recomposer(texte, langue=None):
    """Texte d'un motif codé (``coder``) dans la langue de la personne qui lit ; tout autre texte, tel quel."""
    if not isinstance(texte, str) or not texte.startswith(CODE + "["):
        return texte
    try:
        parties = json.loads(texte[len(CODE):])
        return " ".join(libelle(p[0], langue, **p[1]) if len(p) == 2 else str(p[0]) for p in parties)
    except (ValueError, TypeError, IndexError, KeyError, AttributeError):
        return texte


# ---------------------------------------------------------------- listes de choix des modèles (statuts, rôles…)
OPERATEURS = {"<=": "inf_egal", ">=": "sup_egal", "=": "egal", "<": "inf", ">": "sup"}


def cle_valeur(valeur):
    """« Non sensible » → « non_sensible », « N-1 » → « n_1 », « <= » → « inf_egal » (partie finale d'une clé)."""
    import unicodedata

    v = str(valeur)
    if v in OPERATEURS:
        return OPERATEURS[v]
    v = unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", v).strip("_") or "vide"


def cle_choix(modele, champ, valeur):
    nom = modele if isinstance(modele, str) else modele._meta.model_name
    return f"choix.{nom}.{champ}.{cle_valeur(valeur)}"


def choix_valeur(modele, champ, valeur, langue=None):
    """Libellé d'une valeur de liste de choix d'un modèle (``Reponse``, "statut", "valide") ; repli : libellé du modèle."""
    cle = cle_choix(modele, champ, valeur)
    texte = libelle(cle, langue)
    if texte != cle:
        return texte
    if not isinstance(modele, str):
        return str(dict(modele._meta.get_field(champ).flatchoices).get(valeur, valeur))
    return str(valeur)


def choix_valeur_phrase(modele, champ, valeur, langue=None):
    """Libellé d'une valeur de liste de choix au milieu d'une phrase (« (clôturée) », « (abgeschlossen) ») : la casse vient
    du libellé de chaque langue (clés « choix.phrase.<modèle>.<champ>.<valeur> »), jamais d'un passage en minuscules du
    libellé seul (qui abîme un nom allemand : « Erfassung offen »). Sans cette clé : le libellé seul, tel quel."""
    cle = cle_choix(modele, champ, valeur).replace("choix.", "choix.phrase.", 1)
    texte = libelle(cle, langue)
    return texte if texte != cle else choix_valeur(modele, champ, valeur, langue)


def choix_phrase(objet, champ, langue=None):
    """Comme ``choix``, pour un libellé au milieu d'une phrase ou entre parenthèses."""
    return choix_valeur_phrase(objet.__class__, champ, getattr(objet, champ), langue)


def traduire_choix(form):
    """Listes de choix d'un formulaire de modèle dans la langue de l'interface (fréquence, rôle, agrégation…) : Django
    les prend telles qu'écrites dans le modèle, en français. Clés « choix.<modèle>.<champ>.<valeur> » ; repli : modèle."""
    modele = form._meta.model
    for nom, champ in form.fields.items():
        try:
            mf = modele._meta.get_field(nom)
        except Exception:
            continue
        if getattr(mf, "choices", None) and hasattr(champ, "choices") and not hasattr(champ, "queryset"):
            champ.choices = [(v, choix_valeur(modele, nom, v) if v not in ("", None) else t) for v, t in champ.choices]
    return form


def choix(objet, champ, langue=None):
    """Libellé de la valeur d'un champ à choix d'un objet : ``choix(user, "role")`` (à la place de get_role_display)."""
    return choix_valeur(objet.__class__, champ, getattr(objet, champ), langue)  # __class__ : aussi request.user
