"""Visualisation v2 : règles des formes (compatibles, par défaut, suggestions ; § 5.2 et 5.3 de la spécification)."""

from .formes import MAX_KPIS_GRAPHIQUE, MAX_KPIS_TABLEAU, TYPES, additionnable, lib, meme_unite


# ---------------------------------------------------------------- compatibilités, forme par défaut, suggestions
def _raison_dessous(c, kpi):
    """None s'il y a des organisations à comparer sous l'organisation choisie ; sinon la raison."""
    org = c.org_unique() if not c.tout else None
    oc = c.orgs_comparees or {}
    if c.source.organisations_comparees(kpi.code, org, oc.get("mode", "dessous"), oc.get("niveau"), oc.get("ids")):
        return None
    if not c.source.enfants(org) and oc.get("mode", "dessous") == "dessous":
        return lib("visu.raison.pas_dessous_org", org=org.nom if org else lib("visu.filtres.tout_perimetre"))
    return lib("visu.raison.pas_dessous", niveau=kpi.granularite.tr("nom") if kpi.granularite_id else "")


def compatibles(v, c, kpis):
    """{forme: True ou la raison pour laquelle elle est grisée}, selon les KPI (format, agrégation, niveau de saisie)
    et les filtres (organisations en dessous, périodes, comparaison, campagne)."""
    n = len(kpis)
    numeriques = all(k.est_numerique for k in kpis)
    pourcentage = any(k.est_pourcentage for k in kpis)
    unite_ok = meme_unite(kpis)
    deux_periodes = len(c.periodes_serie(c.periode, 2)) >= 2
    dessous = {}

    def sous(k):
        if k.code not in dessous:
            dessous[k.code] = _raison_dessous(c, k)
        return dessous[k.code]

    r = {}
    aucun = lib("visu.raison.aucun_kpi")
    trop = lambda m: lib("visu.raison.trop_de_kpis", max=m)  # noqa: E731
    # chiffre clé
    r["chiffre"] = aucun if n == 0 else lib("visu.raison.un_kpi") if n > 1 else True
    # barres
    if n == 0:
        r["barres"] = aucun
    elif not numeriques:
        r["barres"] = lib("visu.raison.reponses_barres")
    elif n > MAX_KPIS_GRAPHIQUE:
        r["barres"] = trop(MAX_KPIS_GRAPHIQUE)
    elif not unite_ok:
        r["barres"] = lib("visu.raison.unites_differentes")
    elif v.get("axe") == "organisations" and sous(kpis[0]):
        r["barres"] = sous(kpis[0])
    else:
        r["barres"] = True
    # barres empilées
    if n == 0:
        r["barres_empilees"] = aucun
    elif n == 1:
        k = kpis[0]
        if not k.est_numerique:
            r["barres_empilees"] = True if v.get("axe") != "organisations" or not sous(k) else sous(k)
        elif k.est_pourcentage:
            r["barres_empilees"] = lib("visu.raison.pourcentage_empile")
        elif not additionnable(k):
            r["barres_empilees"] = lib("visu.raison.non_additionnable")
        else:
            r["barres_empilees"] = sous(k) or True
    elif not numeriques:
        r["barres_empilees"] = lib("visu.raison.reponses_barres")
    elif pourcentage:
        r["barres_empilees"] = lib("visu.raison.pourcentage_empile")
    elif n > MAX_KPIS_GRAPHIQUE:
        r["barres_empilees"] = trop(MAX_KPIS_GRAPHIQUE)
    elif not unite_ok:
        r["barres_empilees"] = lib("visu.raison.unites_differentes")
    else:
        r["barres_empilees"] = True
    # courbe
    if n == 0:
        r["courbe"] = aucun
    elif not numeriques:
        r["courbe"] = lib("visu.raison.reponses_courbe")
    elif n > MAX_KPIS_GRAPHIQUE:
        r["courbe"] = trop(MAX_KPIS_GRAPHIQUE)
    elif not unite_ok:
        r["courbe"] = lib("visu.raison.unites_differentes")
    elif not deux_periodes:
        r["courbe"] = lib("visu.raison.une_periode")
    elif v.get("series") == "organisations" and sous(kpis[0]):
        r["courbe"] = sous(kpis[0])
    else:
        r["courbe"] = True
    # anneau
    if n == 0:
        r["anneau"] = aucun
    elif n == 1:
        k = kpis[0]
        if k.est_pourcentage:
            r["anneau"] = lib("visu.raison.pourcentage_non_additionnable")
        elif k.est_numerique and not additionnable(k):
            r["anneau"] = lib("visu.raison.non_additionnable")
        elif k.est_numerique:
            r["anneau"] = sous(k) or True
        else:
            r["anneau"] = True
    elif not numeriques:
        r["anneau"] = lib("visu.raison.reponses_barres")
    elif pourcentage:
        r["anneau"] = lib("visu.raison.pourcentage_non_additionnable")
    elif n > MAX_KPIS_GRAPHIQUE:
        r["anneau"] = trop(MAX_KPIS_GRAPHIQUE)
    elif not unite_ok:
        r["anneau"] = lib("visu.raison.unites_differentes")
    else:
        r["anneau"] = True
    # tableau
    r["tableau"] = True if n or v.get("source") else aucun
    if n > MAX_KPIS_TABLEAU:
        r["tableau"] = trop(MAX_KPIS_TABLEAU)
    # comparaison des organisations
    r["organisations"] = aucun if n == 0 else lib("visu.raison.un_kpi") if n > 1 else (sous(kpis[0]) or True)
    # N et N-1
    if n == 0:
        r["comparaison_n1"] = aucun
    elif not numeriques:
        r["comparaison_n1"] = lib("visu.raison.reponses_n1")
    elif c.prec is None:
        r["comparaison_n1"] = lib("visu.raison.pas_comparaison")
    elif n > TYPES["comparaison_n1"]["max"]:
        r["comparaison_n1"] = trop(TYPES["comparaison_n1"]["max"])
    elif n == 1:
        r["comparaison_n1"] = sous(kpis[0]) or True
    else:
        r["comparaison_n1"] = True
    # taux de remplissage
    r["remplissage"] = True if c.campagne is not None else lib("visu.raison.pas_campagne")
    return r


def par_defaut(kpis, c, source=""):
    """Définition résolue d'un visuel « auto » (§ 5.3) : forme, axe, séries, largeur."""
    n = len(kpis)
    d = {"axe": "", "series": ""}
    if source or n > 4 or (n > 1 and not (meme_unite(kpis) and all(k.est_numerique for k in kpis))):
        d["type"] = "tableau"
    elif n == 0:
        d["type"] = "remplissage"
    elif n == 1:
        k = kpis[0]
        if not k.est_numerique and not _raison_dessous(c, k):
            d["type"] = "anneau"
        else:
            d["type"] = "chiffre"
    elif len(c.periodes_serie(c.periode, 2)) >= 2:
        d.update(type="courbe", series="kpis")
    else:
        d.update(type="barres", axe="kpis")
    d["largeur"] = TYPES[d["type"]]["largeur"]
    d["hauteur"] = TYPES[d["type"]]["hauteur"]
    return d


def suggestions(v, c, kpis, compat=None):
    """Autres formes proposées sous un visuel, dans l'ordre de la spécification, sans les formes grisées."""
    compat = compat or compatibles(v, c, kpis)
    if not kpis:
        ordre = ["tableau"] if v.get("source") else []
    elif not all(k.est_numerique for k in kpis):
        ordre = ["anneau", "barres_empilees", "tableau"]
    elif len(kpis) == 1 and _raison_dessous(c, kpis[0]):
        ordre = ["courbe", "barres", "comparaison_n1"]
    elif len(kpis) == 1 and additionnable(kpis[0]):
        ordre = ["organisations", "courbe", "anneau", "comparaison_n1", "barres_empilees"]
    elif len(kpis) == 1:
        ordre = ["organisations", "courbe", "comparaison_n1"]
    else:
        ordre = ["courbe", "barres", "barres_empilees", "comparaison_n1", "tableau"]
    return [t for t in ordre if t != v.get("type") and compat.get(t) is True]
