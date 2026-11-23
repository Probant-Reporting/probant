"""Visualisation v2 : construction des visuels d'une vue, données et options des filtres."""
from django.urls import reverse

from referentiel.models import Referentiel

from .formes import TYPES, journal, lib, meme_unite, unite
from .filtres import codes_source, libelle_source
from .contexte import Contexte
from .compatibilites import compatibles, par_defaut, suggestions
from .perimetre import est_masque, publique
from .constructeurs import CONSTRUCTEURS


# ---------------------------------------------------------------- titres, résumé, assemblage
def titre_auto(v, c, kpis):
    if v.get("titre"):
        return v["titre"]
    t = v.get("type")
    if t == "remplissage":
        return lib("visu.type.remplissage")
    if t == "tableau" and v.get("source") and not v.get("kpis"):
        return libelle_source(c, v["source"]) or lib("visu.type.tableau")
    if len(kpis) == 1:
        return kpis[0].nom
    if kpis:
        return ", ".join(k.nom for k in kpis[:3]) + (" …" if len(kpis) > 3 else "")
    return lib(f"visu.type.{t}")


def sous_titre(v, c, kpis):
    t = v.get("type")
    morceaux = []
    if t == "remplissage":
        if c.campagne is not None:
            morceaux.append(lib("visu.remplissage.campagne", campagne=c.campagne.nom_affiche))
    else:
        org = c.org_unique() if not c.tout else None
        nom = org.nom if org else lib("visu.filtres.tout_perimetre")
        compare = t in ("organisations", "comparaison_n1", "anneau", "barres_empilees") or v.get("axe") == "organisations" \
            or v.get("series") == "organisations"
        if compare and len(kpis) <= 1 and (not kpis or kpis[0].est_numerique or t in ("organisations", "comparaison_n1")):
            morceaux.append(lib("visu.visuel.sous_titre_sous", org=nom))
        else:
            morceaux.append(nom)
        if c.periode is not None:
            morceaux.append(f"{c.periode} / {c.prec}" if t == "comparaison_n1" and c.prec else str(c.periode))
        if kpis and meme_unite(kpis) and kpis[0].symbole and kpis[0].est_numerique:
            morceaux.append(kpis[0].symbole)
    if c.fixes:
        morceaux.append(lib("visu.filtres.propres", liste=" · ".join(c.fixes)))
    return " · ".join(morceaux)


def resume(payload):
    """Phrase des lecteurs d'écran (``aria-label`` du graphique) : la forme, le titre, puis les valeurs lues."""
    tete = f"{lib('visu.type.' + payload['type']) if payload['type'] in TYPES else ''}, {payload.get('titre', '')}"
    if payload.get("sous_titre"):
        tete += f" ({payload['sous_titre']})"
    if payload.get("etat") != "ok":
        return f"{tete} : {payload.get('message', '')}"
    if payload["type"] == "chiffre":
        morceaux = []
        for l in payload["chiffre"]["lignes"]:
            m = f"{l['org']} {l['texte']}"
            if l.get("comparaison"):
                m += f", {l['comparaison']['libelle']} {l['comparaison']['texte']}"
            if l["ecart"]["texte"]:
                m += f", {l['ecart']['texte']}"
            morceaux.append(m)
        return f"{tete} : {' ; '.join(morceaux)}."
    if payload["type"] == "tableau":
        return f"{tete} : {lib('visu.kpi.nb', n=payload.get('total', 0))}."
    cats, series = payload.get("categories") or [], payload.get("series") or []
    if not series:
        return tete + "."
    morceaux = []
    for i, cat in enumerate(cats[:12]):
        vals = []
        for sr in series[:3]:
            t = sr["textes"][i] if i < len(sr["textes"]) else "–"
            if sr["etats"][i] == "provisoire":
                t += f" ({lib('visu.etat.provisoire')})"
            vals.append(t if len(series) == 1 else f"{sr['libelle']} {t}")
        morceaux.append(f"{cat['libelle']} {', '.join(vals)}")
    fin = " …" if len(cats) > 12 or payload.get("autres") else ""
    return f"{tete} : {' ; '.join(morceaux)}{fin}."


def sans_rien_a_dessiner(series):
    """Vrai si aucune série n'a de valeur, ni N/A ni valeur en attente : le graphique ne serait que des axes vides."""
    return bool(series) and all(n is None for s in series for n in s.get("valeurs") or []) \
        and all(e == "vide" for s in series for e in s.get("etats") or [])


def source_masquable(v):
    """Source d'un tableau sans KPI choisis dont les KPI ne dépendent pas des filtres (« liste:<id> », « theme:<id> ») :
    elle sert à dire s'il est entièrement hors du périmètre (``est_masque``) ; None sinon."""
    if not isinstance(v, dict) or v.get("kpis") or v.get("type") not in ("tableau", "auto"):
        return None
    source = v.get("source") or ""
    return source if isinstance(source, str) and source.startswith(("liste:", "theme:")) else None


def construire(v, ctx, codes_src):
    """Données d'un visuel ; None s'il est entièrement hors du périmètre de la personne (``est_masque``)."""
    t = v.get("type")
    if est_masque(v, ctx.perim, codes_src.get(v["id"]) if source_masquable(v) else None):
        return None
    base = {"id": v["id"], "type": t, "rendu": TYPES.get(t, {}).get("rendu", "html"), "titre": v.get("titre") or "",
            "sous_titre": "", "fiche": "", "unite": None, "largeur": v.get("largeur"), "hauteur": v.get("hauteur"),
            "options": v.get("options") or {}, "etat": "ok", "message": "", "categories": [], "series": [], "autres": 0,
            "tableau": None, "resume": "", "avertissements": [], "suggestions": [], "compatibles": {},
            "definition": publique(v, ctx.perim)}
    if t == "indisponible" or (t not in TYPES and t != "auto"):
        base.update(etat="indisponible", message=lib("visu.visuel.forme_inconnue"), titre=base["titre"] or lib("visu.type.indisponible"))
        base["resume"] = resume(base)
        return base
    c = ctx.pour_visuel(v)
    c.avertissements_visuel = base["avertissements"]
    kpis, hors, rediges = [], 0, 0
    for code in v.get("kpis") or []:
        k = c.source.kpis.get(code)
        if k is None or not k.actif or not ctx.perim.voit_code(code):
            hors += 1  # supprimé, désactivé ou hors de son périmètre : jamais nommé
        elif k.est_texte:  # réponse rédigée : ni chiffre ni graphique (elle se lit dans la Saisie et les exports)
            rediges += 1
        else:
            kpis.append(k)
    if v.get("kpis") and not kpis and rediges:
        base.update(etat="indisponible", message=lib("visu.visuel.kpi_redige"),
                    titre=base["titre"] or (lib(f"visu.type.{t}") if t in TYPES else lib("visu.type.indisponible")))
        base["resume"] = resume(base)
        return base
    if rediges:
        base["avertissements"].append(lib("visu.avert.kpi_rediges", n=rediges))
    if v.get("kpis") and not kpis:
        base.update(etat="indisponible", message=lib("visu.visuel.kpi_indisponible"),
                    titre=base["titre"] or (lib(f"visu.type.{t}") if t in TYPES else lib("visu.type.indisponible")))
        base["resume"] = resume(base)
        return base
    if hors:
        base["avertissements"].append(lib("visu.avert.hors_perimetre", n=hors))
    src = codes_src.get(v["id"])
    if v.get("source") and not v.get("kpis") and src is None:
        base.update(etat="indisponible", message=lib("visu.visuel.source_disparue"), titre=base["titre"] or lib("visu.type.tableau"))
        base["resume"] = resume(base)
        return base
    if t == "auto":
        v = {**v, **par_defaut(kpis, c, v.get("source"))}
        t = v["type"]
        base.update(type=t, rendu=TYPES[t]["rendu"], largeur=v["largeur"], hauteur=v["hauteur"], definition=publique(v, ctx.perim))
    compat = compatibles(v, c, kpis)
    base.update(titre=titre_auto(v, c, kpis), sous_titre=sous_titre(v, c, kpis), compatibles=compat,
                suggestions=suggestions(v, c, kpis, compat))
    if len(kpis) == 1:
        base["fiche"] = reverse("collecte:visu_kpi", args=[kpis[0].code])
    if kpis:
        base["unite"] = unite(kpis[0])
    if c.tout and t not in ("chiffre", "organisations", "remplissage") and len(c.racines) > 1:
        base["avertissements"].append(lib("visu.visuel.par_sommet"))
    if c.periode is None and t != "remplissage":
        base.update(etat="vide", message=lib("visu.etat.aucune_periode"))
    elif compat.get(t) is not True:
        base.update(etat="incompatible", message=compat.get(t) or "")
    else:
        base.update(CONSTRUCTEURS[t](v, c, kpis, src))
        if base["etat"] == "ok" and base["rendu"] == "echarts" and sans_rien_a_dessiner(base.get("series")):
            # aucune valeur pour ces filtres (KPI encore jamais saisi…) : un message plutôt que des axes vides
            base.update(etat="vide", message=lib("visu.visuel.rien"))
    base["resume"] = resume(base)
    return base


def erreur_visuel(v, perim):
    return {"id": v.get("id"), "type": v.get("type"), "rendu": "html", "titre": v.get("titre") or lib("visu.visuel"),
            "sous_titre": "", "etat": "erreur", "message": lib("visu.visuel.erreur"), "categories": [], "series": [],
            "tableau": None, "avertissements": [], "suggestions": [], "compatibles": {}, "definition": publique(v, perim),
            "largeur": v.get("largeur"), "hauteur": v.get("hauteur"), "options": v.get("options") or {},
            "resume": lib("visu.visuel.erreur")}


def donnees(utilisateur, filtres, visuels, parametres=None, campagne_choisie=None):
    """Données de tous les visuels d'une vue (déjà validés), avec une seule ``Source`` pour l'union de leurs KPI :
    {"filtres", "etat", "visuels": {id: données}, "ordre": [ids], "avertissements"}."""
    from parametres import langues as L

    with L.session():  # langues lues une fois (hors requête : commandes, tests)
        return _donnees(utilisateur, filtres, visuels, parametres, campagne_choisie)[0]


def donnees_et_contexte(utilisateur, filtres, visuels, parametres=None, campagne_choisie=None):
    """Comme ``donnees``, avec le ``Contexte`` (options des filtres de la page)."""
    from parametres import langues as L

    with L.session():
        return _donnees(utilisateur, filtres, visuels, parametres, campagne_choisie)


def _donnees(utilisateur, filtres, visuels, parametres, campagne_choisie):
    ctx = Contexte(utilisateur, filtres, parametres, campagne_choisie)
    codes, codes_src = set(), {}
    for v in visuels:
        codes |= set(v.get("kpis") or [])
        if v.get("source") and v.get("type") in ("tableau", "auto"):
            codes_src[v["id"]] = codes_source(ctx, v["source"])
            codes |= set(codes_src[v["id"]] or [])
    ctx.preparer(codes)
    sortie, ordre, masques = {}, [], 0
    for v in visuels:
        try:
            payload = construire(v, ctx, codes_src)
        except Exception:  # noqa: BLE001 - un visuel en erreur n'empêche pas les autres de s'afficher
            journal.exception("Visual %s not computed", v.get("id"))
            payload = erreur_visuel(v, ctx.perim)
        if payload is None:
            masques += 1
            continue
        sortie[v["id"]] = payload
        ordre.append(v["id"])
    return {"filtres": ctx.filtres_json(), "etat": ctx.etat_json(masques), "visuels": sortie, "ordre": ordre,
            "avertissements": ctx.avertissements}, ctx


def options_filtres(ctx):
    """Choix des filtres de la page : périodes groupées par exercice, comparaisons, organisations du périmètre (en
    arbre), référentiels actifs, thèmes du référentiel choisi."""
    from referentiel.models import Frequence

    annees = [p for p in ctx.periodes if p.type == Frequence.ANNEE]
    groupes = {}
    for p in ctx.periodes:
        annee = p if p.type == Frequence.ANNEE else next((a for a in annees if a.debut <= p.debut and a.fin >= p.fin), None)
        groupes.setdefault(str(annee) if annee else str(p.debut.year), []).append({"id": p.pk, "libelle": str(p)})
    haut = min((o.prof for o in ctx.organisations), default=0)
    refs = list(Referentiel.objects.filter(actif=True).order_by("ordre", "code"))
    themes = []
    for r in ([ctx.referentiel] if ctx.referentiel else refs):
        for t, prof in ctx.plan.arbre(r):
            themes.append({"id": t.pk, "nom": t.tr("nom"), "prof": prof, "ref": r.code if not ctx.referentiel else ""})
    cc = ctx.campagne_choisie
    return {
        "periodes": [{"groupe": g, "periodes": ps} for g, ps in groupes.items()],
        "periode_auto": str(ctx.periode_auto) if ctx.periode_auto else "",
        "periode_je_reponds_a": str(cc.periode) if cc else "",
        "organisations": [{"id": o.id, "nom": o.nom, "prof": o.prof - haut, "niveau_id": o.niveau_id} for o in ctx.organisations],
        "tout": len(ctx.racines) > 1,
        "referentiels": [{"code": r.code, "nom": str(r)} for r in refs],
        "je_reponds_a": str(cc.referentiel) if cc else "",
        "themes": themes,
    }
