"""Visualisation v2 : périmètre de la personne (rien hors périmètre ne part vers le navigateur), garde et validation des vues."""
import json
import re

from django.utils.crypto import salted_hmac

from .. import visualisation as V

from .formes import (AXES, HAUTEURS, ID_VISUEL, LARGEURS, MAX_CATEGORIES, MAX_KPIS_TABLEAU, MAX_PERIODES, MAX_VISUELS,
                     MIN_PERIODES, OPTIONS, SERIES, SPECIAUX, TAILLE_MAX, TYPES, lib, nouvel_id)
from .filtres import codes_source_fixes, nettoyer_filtres


# ---------------------------------------------------------------- validation d'une définition
SOURCE = re.compile(r"^(liste:\d{1,10}|theme:\d{1,10}|filtre_theme)$")
CASES = ("valeur", "comparaison", "ecart", "tendance")


def codes_visibles(utilisateur):
    """KPI actifs que la personne voit quelque part (règle des KPI proposés de l'ancien éditeur)."""
    return Perimetre(utilisateur).codes


# ---------------------------------------------------------------- rien de hors périmètre vers le navigateur
# La définition d'une vue partagée (ou d'une vue personnelle dont le périmètre a changé) peut citer des KPI et des
# organisations que la personne ne voit pas. Rien de cela ne part vers le navigateur (page, JSON, Excel, phrases) :
# un visuel entièrement hors du périmètre n'y est pas du tout (on dit seulement combien : « N visuels de cette vue ne
# vous concernent pas »), et un visuel gardé y arrive sans ses KPI ni ses organisations hors périmètre, ni son origine
# (tableau converti). À l'enregistrement d'une vue, le serveur remet tout ce que la page n'a pas reçu (aucune perte).
class Perimetre:
    """Ce que la personne voit : ``codes``, les KPI actifs visibles quelque part ; ``orgs``, les organisations actives
    de son périmètre ; ``complet`` : elle voit tout (administrateur, lecteur ou auditeur sans organisations choisies)."""

    def __init__(self, utilisateur, source=None):
        self.complet = bool(utilisateur.voit_tout and utilisateur.orgs_permises() is None)
        source = source if source is not None else V.Source(utilisateur, [])
        self.orgs = {o.id for o in source.organisations()}
        self.actifs = {c for c, k in source.kpis.items() if k.actif}
        if not self.orgs:
            self.codes = set()
        elif source.paires is None:
            self.codes = set(self.actifs)
        else:
            self.codes = {c for c in self.actifs if any(source.voit(c, o) for o in self.orgs)}

    def voit_code(self, code):
        return self.complet or code in self.codes

    def voit_org(self, org_id):
        return self.complet or org_id in self.orgs


def _identifiant(x):
    return isinstance(x, int) and not isinstance(x, bool)


def filtres_publics(filtres, perim):
    """Filtres d'une vue tels que la page les reçoit : sans organisation hors du périmètre (la vue montre alors le
    sommet du périmètre, et le dit)."""
    f = dict(filtres) if isinstance(filtres, dict) else {}
    if _identifiant(f.get("org")) and not perim.voit_org(f["org"]):
        del f["org"]
    return f


def publique(v, perim):
    """Définition d'un visuel telle que la page la reçoit : sans clé interne (« _… ») ni origine (tableau converti) ;
    pour qui ne voit pas tout, sans ses KPI ni ses organisations hors périmètre."""
    d = {k: x for k, x in v.items() if not k.startswith("_") and k != "origine"}
    if perim.complet:
        return d
    d["kpis"] = [c for c in v.get("kpis") or [] if perim.voit_code(c)]
    f = filtres_publics(v.get("filtres"), perim)
    oc = f.get("orgs_comparees")
    if isinstance(oc, dict) and isinstance(oc.get("ids"), list):
        f["orgs_comparees"] = {**oc, "ids": [i for i in oc["ids"] if perim.voit_org(i)]}
    d["filtres"] = f
    return d


def est_masque(v, perim, codes_src=None):
    """Visuel entièrement hors du périmètre de la personne (jamais pour qui voit tout) : aucun de ses KPI n'est visible
    (et l'un d'eux existe encore : un KPI seulement supprimé dit « plus disponible ») ; pour un tableau d'une liste ou
    d'un thème (``codes_src``), aucun de leurs KPI n'est visible. La règle ne dépend pas des filtres : le serveur la
    refait à l'enregistrement pour garder ces visuels tels quels."""
    if perim.complet or not isinstance(v, dict):
        return False
    kpis = [c for c in v.get("kpis") or [] if isinstance(c, str)]
    if kpis:
        return not any(perim.voit_code(c) for c in kpis) and any(c in perim.actifs for c in kpis)
    return bool(codes_src) and not any(perim.voit_code(c) for c in codes_src)


def masques(visuels, utilisateur, perim):
    """[(rang, visuel)] des visuels entièrement hors du périmètre de la personne, dans une définition enregistrée."""
    if perim.complet:
        return []
    plans, sortie = {}, []
    for i, x in enumerate(visuels or []):
        src = codes_source_fixes(utilisateur, x.get("source"), plans) if isinstance(x, dict) and not x.get("kpis") else None
        if est_masque(x, perim, src):
            sortie.append((i, x))
    return sortie


def projeter(visuels, utilisateur, perim):
    """(visuels publics, nombre de visuels hors périmètre retirés) d'une définition enregistrée : ce que la personne
    peut recevoir, ou garder dans une copie (« Dupliquer »)."""
    caches = {i for i, _ in masques(visuels, utilisateur, perim)}
    publics = [publique(x, perim) for i, x in enumerate(visuels or []) if isinstance(x, dict) and i not in caches]
    return publics, len(caches)


def _empreinte(*morceaux):
    """Empreinte opaque (HMAC de l'installation, 16 caractères) d'un élément qui ne part pas vers la page."""
    return salted_hmac("collecte.visuels.garde", "\x1f".join(str(m) for m in morceaux)).hexdigest()[:16]


def garde(filtres, visuels, utilisateur, perim, caches=None):
    """Empreintes de ce que la page ne reçoit pas d'une vue enregistrée : visuels entièrement hors du périmètre, KPI et
    organisations hors périmètre des autres visuels, organisation des filtres de la vue. La page les renvoie telles
    quelles à l'enregistrement : le serveur sait ainsi exactement quoi garder, même si le périmètre a changé entre-temps.
    Une empreinte ne se relit pas (aucun code ni identifiant) ; vide pour qui voit tout. ``caches`` : rangs des visuels
    hors périmètre s'ils sont déjà connus (données de la page), sinon ``masques``."""
    if perim.complet:
        return []
    e = []
    f = filtres if isinstance(filtres, dict) else {}
    if _identifiant(f.get("org")) and not perim.voit_org(f["org"]):
        e.append(_empreinte("f", f["org"]))
    caches = {i for i, _ in masques(visuels, utilisateur, perim)} if caches is None else caches
    for i, x in enumerate(visuels or []):
        if not isinstance(x, dict):
            continue
        vid = x.get("id")
        if i in caches:
            e.append(_empreinte("v", vid))
            continue
        e += [_empreinte("k", vid, c) for c in x.get("kpis") or [] if isinstance(c, str) and not perim.voit_code(c)]
        fx = x.get("filtres") if isinstance(x.get("filtres"), dict) else {}
        if _identifiant(fx.get("org")) and not perim.voit_org(fx["org"]):
            e.append(_empreinte("o", vid, fx["org"]))
        oc = fx.get("orgs_comparees")
        if isinstance(oc, dict) and isinstance(oc.get("ids"), list):
            e += [_empreinte("i", vid, o) for o in oc["ids"] if _identifiant(o) and not perim.voit_org(o)]
    return e


GARDE = re.compile(r"^[0-9a-f]{16}$")


def lire_garde(valeur):
    """Empreintes renvoyées par la page (``garde``) ; None si elle n'en a pas envoyé (le serveur les recalcule)."""
    if not isinstance(valeur, list):
        return None
    return {x for x in valeur[:5000] if isinstance(x, str) and GARDE.match(x)}


def non_recus(visuels, g):
    """[(rang, visuel)] des visuels enregistrés que la page n'a pas reçus, d'après ses empreintes ``g``."""
    return [(i, x) for i, x in enumerate(visuels or []) if isinstance(x, dict) and _empreinte("v", x.get("id")) in g]


def _completer(v, s, g):
    """Remet dans le visuel envoyé ``v`` ce que la page n'a pas reçu du visuel enregistré ``s`` (même identifiant) :
    son origine (tableau converti) et, d'après les empreintes ``g``, ses KPI et organisations hors périmètre."""
    if isinstance(s.get("origine"), dict):
        v["origine"] = s["origine"]
    vid = s.get("id")
    hors = [c for c in s.get("kpis") or [] if isinstance(c, str) and c not in v["kpis"] and _empreinte("k", vid, c) in g]
    v["kpis"] = v["kpis"] + hors
    fs = s.get("filtres") if isinstance(s.get("filtres"), dict) else {}
    fv = dict(v.get("filtres") or {})
    if _identifiant(fs.get("org")) and "org" not in fv and _empreinte("o", vid, fs["org"]) in g:
        fv["org"] = fs["org"]
    ocs, ocv = fs.get("orgs_comparees"), fv.get("orgs_comparees")
    if isinstance(ocs, dict) and isinstance(ocv, dict) and ocs.get("mode") == ocv.get("mode") == "choisies":
        ids = list(ocv.get("ids") or [])
        ids += [o for o in ocs.get("ids") or [] if _identifiant(o) and o not in ids and _empreinte("i", vid, o) in g]
        fv["orgs_comparees"] = {**ocv, "ids": ids}
    v["filtres"] = fv
    return v


def fusionner(stockes, envoyes, utilisateur, perim, g=None):
    """Visuels à enregistrer d'une vue déjà enregistrée : ceux envoyés par la page (déjà validés), plus tout ce qu'elle
    n'a pas reçu, gardé tel quel (aucune perte) : les visuels entièrement hors du périmètre de la personne, remis à
    leur place, et, dans chaque visuel envoyé qui existait déjà (même identifiant), ses KPI et organisations hors
    périmètre et son origine. ``g`` : empreintes renvoyées par la page (``garde``) ; None : celles d'aujourd'hui."""
    stockes = [x for x in stockes or [] if isinstance(x, dict)]
    g = set(garde(None, stockes, utilisateur, perim)) if g is None else g
    caches = non_recus(stockes, g)
    ids_caches = {x.get("id") for _, x in caches}
    par_id = {x.get("id"): x for x in stockes}
    pris = ids_caches | {v["id"] for v in envoyes}
    sortie = []
    for v in envoyes:
        v = dict(v)
        if v["id"] in ids_caches:  # identifiant déjà porté par un visuel qu'elle n'a pas reçu : un autre
            v["id"] = nouvel_id()
            while v["id"] in pris:
                v["id"] = nouvel_id()
            pris.add(v["id"])
        elif v["id"] in par_id:
            v = _completer(v, par_id[v["id"]], g)
        sortie.append(v)
    for i, x in caches:
        sortie.insert(min(i, len(sortie)), x)
    return sortie


def fusionner_filtres(stockes, envoyes, perim, g=None):
    """Filtres d'une vue à enregistrer : ceux envoyés par la page, plus l'organisation enregistrée hors du périmètre de
    la personne (la page ne l'a pas reçue) quand la page n'en fixe pas d'autre."""
    f = dict(envoyes or {})
    s = stockes if isinstance(stockes, dict) else {}
    if not _identifiant(s.get("org")) or f.get("org") is not None:
        return f
    if (_empreinte("f", s["org"]) in g) if g is not None else not perim.voit_org(s["org"]):
        f["org"] = s["org"]
    return f


def _filtres_visuel(f, n, erreurs):
    sortie = {}
    if not isinstance(f, dict):
        return sortie
    for cle, v in f.items():
        ok = False
        if cle == "periode":
            ok = v in ("auto", "je_reponds_a") or (isinstance(v, int) and not isinstance(v, bool))
        elif cle == "comparaison":
            ok = v in ("n1", "p1", "aucune")
        elif cle == "org":
            ok = v == "tout" or (isinstance(v, int) and not isinstance(v, bool))
        elif cle == "valeurs":
            ok = v in ("validees", "brouillons")
        elif cle == "nb_periodes":
            ok = isinstance(v, int) and not isinstance(v, bool) and MIN_PERIODES <= v <= MAX_PERIODES
        elif cle == "orgs_comparees" and isinstance(v, dict):
            mode = v.get("mode")
            ok = mode in ("dessous", "niveau", "choisies")
            propre = {"mode": mode}
            if mode == "niveau":
                ok = ok and isinstance(v.get("niveau"), str) and 0 < len(v["niveau"]) <= 20
                propre["niveau"] = v.get("niveau")
            if mode == "choisies":
                ids = v.get("ids")
                ok = ok and isinstance(ids, list) and len(ids) <= 100 and all(isinstance(i, int) and not isinstance(i, bool) for i in ids)
                propre["ids"] = ids
            v = propre
        if ok:
            sortie[cle] = v
        else:
            erreurs.append(lib("visu.erreur.option", n=n, option=str(cle)[:40]))
    return sortie


def _options(o, n, erreurs):
    sortie = {}
    if not isinstance(o, dict):
        return sortie
    for cle, v in o.items():
        permis = OPTIONS.get(cle)
        if permis is None:
            ok = False
        elif permis is bool:
            ok = isinstance(v, bool)
        elif permis is int:
            ok = isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= MAX_CATEGORIES
        elif permis is list:
            ok = isinstance(v, list) and all(x in CASES for x in v)
        else:
            ok = v in permis
        if ok:
            sortie[cle] = v
        else:
            erreurs.append(lib("visu.erreur.option", n=n, option=str(cle)[:40]))
    return sortie


def valider_visuel(x, n, codes_ok, ids_vus, erreurs_vue):
    """Un visuel propre, ou None ; les erreurs (en clair, dans la langue de la personne) vont dans ``erreurs_vue``."""
    erreurs = []
    if not isinstance(x, dict):
        erreurs_vue.append({"visuel": "", "message": lib("visu.erreur.forme", n=n, type="?")})
        return None
    vid = x.get("id")
    if vid in (None, ""):
        vid = nouvel_id()
        while vid in ids_vus:
            vid = nouvel_id()
    if not isinstance(vid, str) or not ID_VISUEL.match(vid) or vid in ids_vus:
        erreurs_vue.append({"visuel": str(vid)[:24], "message": lib("visu.erreur.identifiant", n=n)})
        return None
    ids_vus.add(vid)
    t = x.get("type")
    if not isinstance(t, str) or (t not in TYPES and t not in SPECIAUX):
        erreurs_vue.append({"visuel": vid, "message": lib("visu.erreur.forme", n=n, type=str(t)[:30])})
        return None
    kpis = x.get("kpis") or []
    if not isinstance(kpis, list) or not all(isinstance(k, str) and 0 < len(k) <= 30 for k in kpis):
        erreurs.append(lib("visu.erreur.option", n=n, option="kpis"))
        kpis = []
    kpis = list(dict.fromkeys(kpis))
    maximum = TYPES[t]["max"] if t in TYPES else MAX_KPIS_TABLEAU
    if len(kpis) > maximum and t != "indisponible":
        erreurs.append(lib("visu.erreur.trop_de_kpis", n=n, max=maximum))
    for code in kpis:
        if code not in codes_ok:
            erreurs.append(lib("visu.erreur.kpi_invisible", n=n, code=code))
    source = x.get("source") or ""
    if not isinstance(source, str) or (source and not SOURCE.match(source)):
        erreurs.append(lib("visu.erreur.source", n=n))
        source = ""
    axe, series = x.get("axe") or "", x.get("series") or ""
    if axe not in AXES:
        erreurs.append(lib("visu.erreur.option", n=n, option="axe"))
    if series not in SERIES:
        erreurs.append(lib("visu.erreur.option", n=n, option="series"))
    largeur = x.get("largeur")
    defaut = TYPES.get(t, {"largeur": 6})
    v = {"id": vid, "type": t, "titre": str(x.get("titre") or "")[:150], "kpis": kpis, "source": source,
         "axe": axe if axe in AXES else "", "series": series if series in SERIES else "",
         "largeur": largeur if largeur in LARGEURS else defaut["largeur"],
         "hauteur": x.get("hauteur") if x.get("hauteur") in HAUTEURS else "m",
         "filtres": _filtres_visuel(x.get("filtres") or {}, n, erreurs),
         "options": _options(x.get("options") or {}, n, erreurs)}
    # « origine » (tableau converti) ne vient jamais de la page : le serveur la garde (``fusionner``)
    for e in erreurs:
        erreurs_vue.append({"visuel": vid, "message": e})
    return v


def plafond_visuels(vue=None):
    """Visuels permis dans une vue : ``MAX_VISUELS`` ; une vue qui en a déjà plus (ancien tableau converti) reste
    modifiable : elle peut en perdre, pas en gagner."""
    return max(MAX_VISUELS, len(vue.visuels or []) if vue is not None else 0)


def valider_vue(donnees, utilisateur, anciens=(), complet=True, plafond=MAX_VISUELS, gardes=0):
    """(définition propre, erreurs) d'une vue envoyée par la page : {"nom", "description", "filtres", "visuels"}.
    ``anciens`` : codes de KPI déjà présents dans la vue enregistrée (un KPI disparu depuis reste, il s'affichera
    « plus disponible ») ; ``complet=False`` : seules les clés présentes sont validées (enregistrement partiel) ;
    ``plafond`` : visuels permis (``plafond_visuels``), dont ``gardes`` que la page n'a pas reçus (hors périmètre)."""
    erreurs = []
    if not isinstance(donnees, dict):
        return {}, [{"visuel": "", "message": lib("visu.vue.json_invalide")}]
    propre = {}
    if complet or "nom" in donnees:
        nom = str(donnees.get("nom") or "").strip()[:100]
        if not nom:
            erreurs.append({"visuel": "", "message": lib("visu.vue.nom_requis")})
        propre["nom"] = nom
    if complet or "description" in donnees:
        propre["description"] = str(donnees.get("description") or "").strip()[:200]
    if complet or "filtres" in donnees:
        propre["filtres"] = nettoyer_filtres(donnees.get("filtres") or {}, erreurs)
    if complet or "visuels" in donnees:
        visuels = donnees.get("visuels") or []
        if not isinstance(visuels, list):
            erreurs.append({"visuel": "", "message": lib("visu.vue.json_invalide")})
            visuels = []
        if len(visuels) + gardes > plafond:
            cle = "visu.vue.trop_de_visuels" if plafond <= MAX_VISUELS else "visu.vue.trop_de_visuels_ancienne"
            erreurs.append({"visuel": "", "message": lib(cle, max=MAX_VISUELS, n=plafond)})
            visuels = visuels[:max(plafond - gardes, 0)]
        demandes = {c for x in visuels if isinstance(x, dict) and isinstance(x.get("kpis"), list) for c in x["kpis"] if isinstance(c, str)}
        codes_ok = (codes_visibles(utilisateur) & demandes if demandes else set()) | set(anciens)
        ids = set()
        propre["visuels"] = [v for i, x in enumerate(visuels, start=1) if (v := valider_visuel(x, i, codes_ok, ids, erreurs))]
    return propre, erreurs


def lire_json(corps):
    """Corps JSON d'une requête (200 Ko au plus) : (données, erreur)."""
    if len(corps or b"") > TAILLE_MAX:
        return None, lib("visu.vue.trop_grande", max=TAILLE_MAX // 1024)
    try:
        return json.loads(corps or b"{}"), None
    except (ValueError, UnicodeDecodeError, RecursionError):  # RecursionError : imbrication démesurée ([[[[…]]]])
        return None, lib("visu.vue.json_invalide")
