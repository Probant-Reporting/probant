"""Visualisation v2 : un constructeur par forme (séries, tableaux, résumés)."""
from collections import Counter
from decimal import Decimal

from django.urls import reverse

from .. import saisie as S
from .. import visualisation as V

from .formes import (LIGNES_TABLEAU, MAX_BARRES_ORGS, MAX_CATEGORIES, MAX_KPIS_TABLEAU, MAX_ORGS_COLONNES, MAX_SERIES,
                     MAX_SOMMETS_CHIFFRE, cellule, ecart, etat_point, formater, lib, meme_unite, nombre,
                     pourcent_texte, texte_lu, texte_point, valeur_json)
from .filtres import _plan_de


# ---------------------------------------------------------------- briques des constructeurs
def cat_periode(q, courante=None):
    return {"cle": f"p{q.pk}", "libelle": str(q), "periode": q.pk, "courante": q == courante}


def cat_org(o, c):
    return {"cle": f"o{o.id}", "libelle": o.nom, "org": o.id, "descend": bool(c.source.enfants(o))}


def cat_kpi(k):
    return {"cle": f"k{k.code}", "libelle": k.nom, "kpi": k.code, "fiche": reverse("collecte:visu_kpi", args=[k.code])}


def serie(cle, libelle, points, kpis, **autres):
    """Série à dessiner : nombres (pourcentage de 0 à 100), textes lus et états, alignés sur les catégories.
    ``kpis`` : le KPI de toute la série, ou une liste (un KPI par catégorie)."""
    ks = kpis if isinstance(kpis, list) else [kpis] * len(points)
    return {"cle": cle, "libelle": libelle, "valeurs": [valeur_json(p, k) for p, k in zip(points, ks)],
            "textes": [texte_point(p, k) for p, k in zip(points, ks)], "etats": [etat_point(p) for p in points], **autres}


def serie_brute(cle, libelle, nombres, textes, etats=None, **autres):
    return {"cle": cle, "libelle": libelle, "valeurs": nombres, "textes": textes,
            "etats": etats or ["valide" if n is not None else "vide" for n in nombres], **autres}


def cellule_ecart(texte, e, sens):
    """Cellule d'un écart relatif : le texte de la page (« ▲ +4,2 % ») ; pour l'Excel, le nombre de 0 à 100 (négatif
    pour une baisse), son sens écrit par le format."""
    return cellule(texte, round(e * 100, 4) if e is not None else None, d=1, p=True, sens=sens, ecart=True)


def rogner(periodes, series_points):
    """Retire les premières périodes où aucune série n'a rien (avant le début de l'historique)."""
    debut = 0
    for i in range(len(periodes)):
        if any(pts[i] is not None and (pts[i].valeur is not None or pts[i].en_attente) for pts in series_points):
            break
        debut = i + 1
    if debut >= len(periodes):
        debut = max(len(periodes) - 1, 0)
    return periodes[debut:], [pts[debut:] for pts in series_points]


def tableau_generique(entete_axe, categories, series):
    """Tableau de données d'un graphique : une ligne par catégorie, une colonne par série (textes du serveur ; nombres
    exacts pour l'Excel). L'état d'une ligne est celui de sa première série."""
    lignes = []
    for i, cat in enumerate(categories):
        cellules = [cellule(cat["libelle"])]
        for s in series:
            n = s["valeurs"][i] if i < len(s["valeurs"]) else None
            etat = s["etats"][i] if i < len(s["etats"]) else "vide"
            t = s["textes"][i] if i < len(s["textes"]) else "–"
            if etat == "provisoire":
                t = f"{t} ({lib('visu.etat.provisoire')})"
            c = cellule(t, n, etat=etat)
            if "decimales" in s:
                c["d"], c["p"] = s["decimales"], s.get("pourcentage", False)
            if n is not None and s.get("symbole") and not c.get("p"):
                c["s"] = s["symbole"]
            if n is not None and s.get("ecart"):
                c["ecart"] = True
            cellules.append(c)
        lignes.append({"cellules": cellules, "etat": series[0]["etats"][i] if series and i < len(series[0]["etats"]) else "",
                       "org": cat.get("org"), "lien": cat.get("fiche")})
    return {"entetes": [entete_axe] + [s["libelle"] for s in series], "lignes": lignes}


def _formats(series, kpi):
    for s in series:
        s.setdefault("decimales", kpi.decimales)
        s.setdefault("pourcentage", kpi.est_pourcentage)
        if kpi.est_numerique and not kpi.est_pourcentage and kpi.symbole:
            s.setdefault("symbole", kpi.symbole)
    return series


def _oc(c):
    oc = c.orgs_comparees or {}
    return oc.get("mode", "dessous"), oc.get("niveau"), oc.get("ids")


def _org_pour_comparer(c):
    return None if c.tout else c.org


def _noter(c, code, org, periode, p):
    if p is not None and periode is not None and periode == c.periode_vue():
        c._comptes[(code, org.id, c.brouillons)] = p


# ---------------------------------------------------------------- les 9 constructeurs
def _chiffre(v, c, kpis, codes_src):
    k = kpis[0]
    orgs = c.racines[:MAX_SOMMETS_CHIFFRE] if c.tout else [c.org]
    if c.tout and len(c.racines) > MAX_SOMMETS_CHIFFRE:
        c.avertissements_visuel.append(lib("visu.visuel.par_sommet"))
    lignes = []
    for o in orgs:
        if o is None:
            continue
        p = c.point(k.code, o, c.periode)
        if p is None:
            continue
        n1 = c.point(k.code, o, c.prec) if c.prec else None
        e_txt, sens, e = ecart(p, n1)
        tendance = None
        if k.est_numerique and not c.tout:
            pers = c.periodes_serie(c.periode)
            vals = [valeur_json(c.source.point(k.code, o, q), k) for q in pers]
            if sum(x is not None for x in vals) >= 2:
                tendance = {"valeurs": vals, "libelles": [str(q) for q in pers]}
        lignes.append({"org": o.nom, "org_id": o.id, "texte": texte_point(p, k), "etat": etat_point(p),
                       "valeur": valeur_json(p, k),
                       "comparaison": {"libelle": str(c.prec), "texte": texte_point(n1, k), "etat": etat_point(n1)} if c.prec else None,
                       "ecart": {"texte": e_txt, "sens": sens}, "tendance": tendance,
                       "_n1": n1, "_e": e})
    if not lignes:
        return {"etat": "vide", "message": lib("visu.visuel.rien")}
    entetes = [lib("visu.visuel.organisation"), str(c.periode)] + ([str(c.prec), lib("visu.visuel.ecart")] if c.prec else [])
    tab = []
    for l in lignes:
        cel = [cellule(l["org"]), cellule(l["texte"] + (f" ({lib('visu.etat.provisoire')})" if l["etat"] == "provisoire" else ""),
                                          l["valeur"], k, l["etat"])]
        n1, e = l.pop("_n1"), l.pop("_e")
        if c.prec:
            cel += [cellule(l["comparaison"]["texte"], valeur_json(n1, k), k, etat_point(n1)), cellule_ecart(l["ecart"]["texte"], e, l["ecart"]["sens"])]
        tab.append({"cellules": cel, "etat": l["etat"], "org": l["org_id"]})
    return {"chiffre": {"lignes": lignes, "par_sommet": c.tout, "numerique": k.est_numerique},
            "tableau": {"entetes": entetes, "lignes": tab}}


def _barres(v, c, kpis, codes_src):
    k0 = kpis[0]
    axe = v.get("axe") or ("periodes" if len(kpis) == 1 else "kpis")
    org = c.org_unique()
    autres = 0
    if axe == "periodes":
        pers = c.periodes_serie(c.periode)
        pts = [[c.point(k.code, org, q) for q in pers] for k in kpis]
        pers, pts = rogner(pers, pts)
        cats = [cat_periode(q, c.periode) for q in pers]
        series = [serie(k.code, k.nom, p, k) for k, p in zip(kpis, pts)]
        entete = lib("visu.visuel.periode")
    elif axe == "organisations":
        mode, niveau, ids = _oc(c)
        orgs = c.source.organisations_comparees(k0.code, _org_pour_comparer(c), mode, niveau, ids, c.periode)
        autres = max(len(orgs) - MAX_CATEGORIES, 0)
        orgs = orgs[:MAX_CATEGORIES]
        cats = [cat_org(o, c) for o in orgs]
        series = [serie(k.code, k.nom, [c.point(k.code, o, c.periode) for o in orgs], k) for k in kpis]
        entete = lib("visu.visuel.organisation")
    else:
        axe = "kpis"
        cats = [cat_kpi(k) for k in kpis]
        series = [serie("n", str(c.periode), [c.point(k.code, org, c.periode) for k in kpis], list(kpis))]
        if c.prec:
            series.append(serie("cmp", str(c.prec), [c.point(k.code, org, c.prec) for k in kpis], list(kpis), role="comparaison"))
        entete = lib("visu.visuel.kpi")
    _formats(series, k0)
    return {"axe": axe, "categories": cats, "series": series, "autres": autres,
            "tableau": tableau_generique(entete, cats, series)}


def _parts_cent(series, nb):
    """Valeurs en parts (de 0 à 100) de chaque catégorie, à partir des nombres du serveur."""
    for i in range(nb):
        total = sum(s["valeurs"][i] or 0 for s in series)
        for s in series:
            n = s["valeurs"][i]
            s.setdefault("parts", [None] * nb)
            s["parts"][i] = round(n / total * 100, 4) if n is not None and total else None


def _barres_empilees(v, c, kpis, codes_src):
    k = kpis[0]
    org = c.org_unique()
    totaux, totaux_excel = [], []  # textes de la page ; cellules de l'Excel (le nombre, au format de l'unité)
    autres = 0
    if len(kpis) == 1 and k.est_numerique:  # séries : les organisations en dessous ; le total : celui du moteur
        mode, niveau, ids = _oc(c)
        orgs = c.source.organisations_comparees(k.code, _org_pour_comparer(c), mode, niveau, ids, c.periode)
        nommees, reste = (orgs[:MAX_SERIES - 1], orgs[MAX_SERIES - 1:]) if len(orgs) > MAX_SERIES else (orgs, [])
        pers = c.periodes_serie(c.periode)
        pts = [[c.point(k.code, o, q) for q in pers] for o in nommees]
        pers, pts = rogner(pers, pts or [[None] * len(pers)])
        pts = pts if nommees else []
        series = [serie(f"o{o.id}", o.nom, p, k, org=o.id) for o, p in zip(nommees, pts)]
        if reste:
            nombres, textes = [], []
            for q in pers:
                vals = [x.nombre for x in (c.source.point(k.code, o, q) for o in reste) if x is not None and x.nombre is not None]
                s = sum(vals, Decimal(0)) if vals else None
                nombres.append(float(s) if s is not None else None)
                textes.append(formater(s, k) if s is not None else "–")
            series.append(serie_brute("autres", lib("visu.visuel.autres", n=len(reste)), nombres, textes, autres=True))
            autres = len(reste)
        cats = [cat_periode(q, c.periode) for q in pers]
        pts_total = [c.point(k.code, org, q) for q in pers]
        totaux = [texte_point(p, k) for p in pts_total]
        totaux_excel = [cellule(t, valeur_json(p, k), k) for t, p in zip(totaux, pts_total)]
        entete, axe = lib("visu.visuel.periode"), "periodes"
    elif len(kpis) == 1:  # oui / non, liste : décompte des réponses
        axe = "organisations" if v.get("axe") == "organisations" else "periodes"
        if axe == "periodes":
            pers = c.periodes_serie(c.periode)
            points = [c.point(k.code, org, q) for q in pers]
            pers, (points,) = rogner(pers, [points])
            cats = [cat_periode(q, c.periode) for q in pers]
            entete = lib("visu.visuel.periode")
        else:
            mode, niveau, ids = _oc(c)
            orgs = c.source.organisations_comparees(k.code, _org_pour_comparer(c), mode, niveau, ids,
                                                    arbre_de=c.periode)[:MAX_CATEGORIES]
            points = [c.point(k.code, o, c.periode) for o in orgs]
            cats = [cat_org(o, c) for o in orgs]
            entete = lib("visu.visuel.organisation")
        comptes = [V.decompte(p.valeur) if p is not None and p.valeur is not None and not p.na else Counter() for p in points]
        reponses = [x for x in k.choix if any(cp.get(x) for cp in comptes)]
        reponses += sorted({x for cp in comptes for x in cp if x not in reponses})
        if len(reponses) > MAX_SERIES:
            reste = reponses[MAX_SERIES - 1:]
            reponses = reponses[:MAX_SERIES - 1]
            comptes = [Counter({**{r: cp.get(r, 0) for r in reponses}, "\0autres": sum(cp.get(r, 0) for r in reste)}) for cp in comptes]
            autres = len(reste)
        series = []
        for r in reponses + (["\0autres"] if autres else []):
            nombres = [cp.get(r) or None for cp in comptes]
            libelle = lib("visu.visuel.autres_reponses", n=autres) if r == "\0autres" else k.reponse_affichee(r)
            series.append(serie_brute(f"r{len(series)}", libelle, [float(n) if n else None for n in nombres],
                                      [lib("visu.visuel.organisations_nb", n=n) if n else "–" for n in nombres],
                                      decimales=0, pourcentage=False))
        totaux = [lib("visu.visuel.organisations_nb", n=sum(cp.values())) if cp else "–" for cp in comptes]
        totaux_excel = [cellule(t, sum(cp.values()) if cp else None, d=0) for t, cp in zip(totaux, comptes)]
    else:  # plusieurs KPI de même unité : le total est la somme faite ici, par le serveur
        axe = "organisations" if v.get("axe") == "organisations" else "periodes"
        if axe == "periodes":
            pers = c.periodes_serie(c.periode)
            pts = [[c.point(x.code, org, q) for q in pers] for x in kpis]
            pers, pts = rogner(pers, pts)
            cats = [cat_periode(q, c.periode) for q in pers]
            entete = lib("visu.visuel.periode")
        else:
            mode, niveau, ids = _oc(c)
            orgs = c.source.organisations_comparees(k.code, _org_pour_comparer(c), mode, niveau, ids, c.periode)[:MAX_CATEGORIES]
            pts = [[c.point(x.code, o, c.periode) for o in orgs] for x in kpis]
            cats = [cat_org(o, c) for o in orgs]
            entete = lib("visu.visuel.organisation")
        series = [serie(x.code, x.nom, p, x) for x, p in zip(kpis, pts)]
        for i in range(len(cats)):
            vals = [p[i].nombre for p in pts if p[i] is not None and p[i].nombre is not None]
            somme = sum(vals, Decimal(0)) if vals else None
            totaux.append(formater(somme, k) if vals else "–")
            totaux_excel.append(cellule(totaux[-1], (float(somme * 100) if k.est_pourcentage else float(somme)) if vals else None, k))
    _formats(series, k)
    if (v.get("options") or {}).get("cent_pour_cent"):
        _parts_cent(series, len(cats))
    tab = tableau_generique(entete, cats, series)
    tab["entetes"].append(lib("visu.visuel.total"))
    for ligne, t in zip(tab["lignes"], totaux_excel):
        ligne["cellules"].append(t)
    return {"axe": axe, "categories": cats, "series": series, "totaux": totaux, "autres": autres, "tableau": tab}


def _courbe(v, c, kpis, codes_src):
    k0 = kpis[0]
    pers = c.periodes_serie(c.periode)
    if v.get("series") == "organisations" and len(kpis) == 1:
        mode, niveau, ids = _oc(c)
        orgs = c.source.organisations_comparees(k0.code, _org_pour_comparer(c), mode, niveau, ids, c.periode)[:MAX_SERIES]
        pts = [[c.point(k0.code, o, q) for q in pers] for o in orgs]
        pers, pts = rogner(pers, pts or [[None] * len(pers)])
        series = [serie(f"o{o.id}", o.nom, p, k0, org=o.id) for o, p in zip(orgs, pts if orgs else [])]
    else:
        org = c.org_unique()
        pts = [[c.point(k.code, org, q) for q in pers] for k in kpis]
        pers, pts = rogner(pers, pts)
        series = [serie(k.code, k.nom, p, k) for k, p in zip(kpis, pts)]
    cats = [cat_periode(q, c.periode) for q in pers]
    _formats(series, k0)
    return {"axe": "periodes", "categories": cats, "series": series,
            "tableau": tableau_generique(lib("visu.visuel.periode"), cats, series)}


def _anneau(v, c, kpis, codes_src):
    k = kpis[0]
    org = c.org_unique()
    parts = []  # (catégorie, nombre exact, texte de la valeur, état)
    if len(kpis) == 1 and k.est_numerique:  # parts des organisations en dessous (règle de Source.repartition)
        mode, niveau, ids = _oc(c)
        lignes = [(o, p) for o, p, _ in c.source.comparaison(k.code, _org_pour_comparer(c), c.periode, None, mode, niveau, ids)
                  if p.nombre is not None and p.nombre > 0]
        for o, p in lignes:
            _noter(c, k.code, o, c.periode, p)
        nommees, reste = lignes[:V.NB_REPARTITION], lignes[V.NB_REPARTITION:]
        parts = [(cat_org(o, c), p.nombre, formater(p.nombre, k), etat_point(p)) for o, p in nommees]
        if reste:
            s = sum((p.nombre for _, p in reste), Decimal(0))
            parts.append(({"cle": "autres", "libelle": lib("visu.visuel.autres", n=len(reste)), "autres": True}, s, formater(s, k), "valide"))
        total = sum((x[1] for x in parts), Decimal(0))
        total_texte = formater(total, k) if parts else "–"
    elif len(kpis) == 1:  # oui / non, liste : nombre d'organisations de chaque réponse
        p = c.point(k.code, org, c.periode)
        compte = V.decompte(p.valeur) if p and p.valeur is not None and not p.na else Counter()
        ordre = [x for x in k.choix if compte.get(x)] + sorted(x for x in compte if x not in k.choix)
        if len(ordre) > MAX_SERIES:
            reste = ordre[MAX_SERIES - 1:]
            ordre = ordre[:MAX_SERIES - 1]
        else:
            reste = []
        for i, x in enumerate(ordre):
            parts.append(({"cle": f"r{i}", "libelle": k.reponse_affichee(x)}, Decimal(compte[x]),
                          lib("visu.visuel.organisations_nb", n=compte[x]), etat_point(p)))
        if reste:
            n = sum(compte[x] for x in reste)
            parts.append(({"cle": "autres", "libelle": lib("visu.visuel.autres_reponses", n=len(reste)), "autres": True},
                          Decimal(n), lib("visu.visuel.organisations_nb", n=n), etat_point(p)))
        total = Decimal(sum(compte.values()))
        total_texte = lib("visu.visuel.organisations_nb", n=int(total)) if compte else "–"
    else:  # plusieurs KPI additionnables de même unité
        for x in kpis:
            p = c.point(x.code, org, c.periode)
            if p is not None and p.nombre is not None and p.nombre > 0:
                parts.append((cat_kpi(x), p.nombre, formater(p.nombre, x), etat_point(p)))
        total = sum((x[1] for x in parts), Decimal(0))
        total_texte = formater(total, k) if parts else "–"
    if not parts or total <= 0:
        return {"etat": "vide", "message": lib("visu.visuel.rien")}
    cats = [x[0] for x in parts]
    pourcents = [x[1] / total * 100 for x in parts]
    numerique = k.est_numerique
    s = serie_brute("parts", str(c.periode), [float(x[1]) for x in parts],
                    [f"{x[2]} · {pourcent_texte(nombre(pc, 1))}" for x, pc in zip(parts, pourcents)], [x[3] for x in parts],
                    decimales=k.decimales if numerique else 0, pourcentage=False,
                    **({"symbole": k.symbole} if numerique and k.symbole and not k.est_pourcentage else {}))
    s["parts"] = [float(pc) for pc in pourcents]
    tab = tableau_generique(lib("visu.visuel.organisation") if len(kpis) == 1 and numerique else
                            lib("visu.visuel.reponse") if len(kpis) == 1 else lib("visu.visuel.kpi"), cats, [s])
    tab["entetes"].append(lib("visu.visuel.part"))
    for ligne, pc in zip(tab["lignes"], pourcents):
        ligne["cellules"].append(cellule(pourcent_texte(nombre(pc, 1)), float(round(pc, 4)), d=1, p=True))
    total_excel = cellule(total_texte, float(total), k) if numerique else cellule(total_texte, float(total), d=0)
    tab["lignes"].append({"cellules": [cellule(lib("visu.visuel.total")), total_excel, cellule(pourcent_texte("100"), 100.0, d=1, p=True)],
                          "etat": "", "total": True})
    return {"categories": cats, "series": [s], "total": total_texte, "autres": sum(1 for x in cats if x.get("autres")),
            "tableau": tab}


def _tableau(v, c, kpis, codes_src):
    codes = [k.code for k in kpis] if v.get("kpis") else list(codes_src or [])
    codes = [x for x in codes if x in c.source.kpis and c.source.kpis[x].actif
             and not c.source.kpis[x].est_texte]  # réponse rédigée : pas de visuel 
    if len(codes) > MAX_KPIS_TABLEAU:
        c.avertissements_visuel.append(lib("visu.avert.trop_de_kpis", max=MAX_KPIS_TABLEAU))
        codes = codes[:MAX_KPIS_TABLEAU]
    org = c.org_unique()
    options = v.get("options") or {}
    lignes = []
    if options.get("colonnes") == "organisations":
        # organisations du dessous dans l'arbre de la période (celui de sa clôture pour un exercice clos ou gardé)
        orgs = c.source.enfants(None if c.tout else org, c.periode)[:MAX_ORGS_COLONNES] or ([org] if org else [])
        entetes = [lib("visu.visuel.kpi")] + [o.nom for o in orgs]
        for code in codes:
            k = c.source.kpis[code]
            pts = [c.point(code, o, c.periode) for o in orgs]
            if all(p is None for p in pts):
                continue
            lignes.append({"cellules": [cellule(k.nom, code=code)] + [cellule(texte_lu(p, k), valeur_json(p, k), k, etat_point(p)) for p in pts],
                           "etat": etat_point(pts[0]), "lien": reverse("collecte:visu_kpi", args=[code]), "kpi": code})
    else:
        cases = options.get("cases") or ["valeur", "comparaison", "ecart"]
        entetes = [lib("visu.visuel.kpi")]
        if "valeur" in cases:
            entetes.append(str(c.periode) if c.periode else lib("visu.visuel.valeur"))
        if "comparaison" in cases and c.prec:
            entetes.append(str(c.prec))
        if "ecart" in cases and c.prec:
            entetes.append(lib("visu.visuel.ecart"))
        for code in codes:
            k = c.source.kpis[code]
            p = c.point(code, org, c.periode)
            if p is None:
                continue  # hors du périmètre de la personne
            n1 = c.point(code, org, c.prec) if c.prec else None
            cel = [cellule(k.nom, code=code)]
            if "valeur" in cases:
                cel.append(cellule(texte_lu(p, k), valeur_json(p, k), k, etat_point(p)))
            if "comparaison" in cases and c.prec:
                cel.append(cellule(texte_lu(n1, k), valeur_json(n1, k), k, etat_point(n1)))
            if "ecart" in cases and c.prec:
                t, sens, e = ecart(p, n1)
                cel.append(cellule_ecart(t, e, sens))
            ligne = {"cellules": cel, "etat": etat_point(p), "lien": reverse("collecte:visu_kpi", args=[code]), "kpi": code}
            if "tendance" in cases and k.est_numerique:
                pers = c.periodes_serie(c.periode)
                vals = [valeur_json(c.source.point(code, org, q), k) for q in pers]
                if sum(x is not None for x in vals) >= 2:
                    ligne["tendance"] = vals
            lignes.append(ligne)
    if not lignes:
        return {"etat": "vide", "message": lib("visu.visuel.rien")}
    return {"tableau": {"entetes": entetes, "lignes": lignes}, "total": len(lignes), "affichees": LIGNES_TABLEAU,
            "nb_kpis": len(codes)}


def _organisations(v, c, kpis, codes_src):
    k = kpis[0]
    options = v.get("options") or {}
    mode, niveau, ids = _oc(c)
    lignes = c.source.comparaison(k.code, _org_pour_comparer(c), c.periode, c.prec, mode, niveau, ids)
    for o, p, n1 in lignes:
        _noter(c, k.code, o, c.periode, p)
    tri = options.get("tri") or "valeur"
    if tri == "arbre":
        lignes.sort(key=lambda x: S.cle_arbre(x[0]))
    elif tri == "nom":
        lignes.sort(key=lambda x: x[0].nom.lower())
    if not lignes:
        return {"etat": "vide", "message": lib("visu.visuel.rien")}
    maximum = options.get("max") or MAX_BARRES_ORGS
    autres = max(len(lignes) - maximum, 0)
    lignes = lignes[:maximum]
    cats = [cat_org(o, c) for o, _, _ in lignes]
    series = [serie("n", str(c.periode), [p for _, p, _ in lignes], k)]
    if c.prec and options.get("repere", True):
        series.append(serie("cmp", str(c.prec), [n for _, _, n in lignes], k, role="repere"))
    _formats(series, k)
    tab = tableau_generique(lib("visu.visuel.organisation"), cats, series)
    if c.prec:
        tab["entetes"].append(lib("visu.visuel.ecart"))
        for ligne, (_, p, n1) in zip(tab["lignes"], lignes):
            t, sens, e = ecart(p, n1)
            ligne["cellules"].append(cellule_ecart(t, e, sens))
    return {"axe": "organisations", "categories": cats, "series": series, "autres": autres,
            "liste": not k.est_numerique, "rendu": "echarts" if k.est_numerique else "html", "tableau": tab}


def _comparaison_n1(v, c, kpis, codes_src):
    k0 = kpis[0]
    org = c.org_unique()
    if len(kpis) == 1:
        mode, niveau, ids = _oc(c)
        lignes = c.source.comparaison(k0.code, _org_pour_comparer(c), c.periode, c.prec, mode, niveau, ids)[:MAX_CATEGORIES]
        for o, p, _ in lignes:
            _noter(c, k0.code, o, c.periode, p)
        cats = [cat_org(o, c) for o, _, _ in lignes]
        n, n1 = [p for _, p, _ in lignes], [x for _, _, x in lignes]
        ks = k0
        entete = lib("visu.visuel.organisation")
    else:
        cats = [cat_kpi(k) for k in kpis]
        n = [c.point(k.code, org, c.periode) for k in kpis]
        n1 = [c.point(k.code, org, c.prec) for k in kpis]
        ks = list(kpis)
        entete = lib("visu.visuel.kpi")
    if not cats:
        return {"etat": "vide", "message": lib("visu.visuel.rien")}
    # organisations comptées différentes d'une période à l'autre (ouverte, fermée, déplacée) : dit, total inchangé
    # (à confirmer)
    comparees = [o for o, _, _ in lignes] if len(kpis) == 1 else [org]
    if c.prec and any(c.source.perimetre_change(o, c.periode, c.prec) for o in comparees):
        c.avertissements_visuel.append(lib("visu.visuel.perimetres_differents", periode=str(c.periode), comparaison=str(c.prec)))
    ecarts = [ecart(a, b) for a, b in zip(n, n1)]
    if meme_unite(kpis):
        mode_aff = "valeurs"
        series = _formats([serie("n", str(c.periode), n, ks), serie("cmp", str(c.prec), n1, ks, role="comparaison")], k0)
    else:
        mode_aff = "ecart"
        series = [serie_brute("ecart", lib("visu.visuel.ecart"), [round(e[2] * 100, 4) if e[2] is not None else None for e in ecarts],
                              [e[0] or "–" for e in ecarts], decimales=1, pourcentage=True, ecart=True)]
    tab = tableau_generique(entete, cats, series)
    if mode_aff == "valeurs":
        tab["entetes"].append(lib("visu.visuel.ecart"))
        for ligne, e in zip(tab["lignes"], ecarts):
            ligne["cellules"].append(cellule_ecart(e[0], e[2], e[1]))
    return {"axe": "organisations" if len(kpis) == 1 else "kpis", "mode": mode_aff, "categories": cats, "series": series,
            "sens": [e[1] for e in ecarts], "tableau": tab}


def remplissage_compteurs(c, campagne, par):
    """[(clé, libellé, Compteur, org)] du taux de remplissage : mêmes règles que le Tableau de bord
    (``saisie.lignes`` puis ``saisie.tableau_de_bord``)."""
    plan = _plan_de(c, campagne.referentiel)
    tdb = S.tableau_de_bord(S.lignes(c.utilisateur, campagne, plan=plan, legere=True), plan)
    if par == "total":
        return [("total", lib("visu.visuel.total"), tdb["total"], None)], tdb
    if par == "themes":
        noms = {t.tr("nom") for t in c.themes if t.parent_id is None}
        items = [(f"t{i}", titre, cpt, None) for i, (titre, cpt) in enumerate(tdb["par_theme"]) if not noms or titre in noms]
        return items, tdb
    par_org = dict(tdb["par_org"])
    org = None if c.tout else c.org
    if org is None:
        orgs = [o for o in par_org if o.parent_id is None or o.parent_id not in {x.id for x in par_org}]
    else:
        orgs = [o for o in par_org if o.id == org.id] + [o for o in par_org if o.parent_id == org.id]
    orgs = sorted(orgs, key=lambda o: (org is not None and o.id != org.id, S.cle_arbre(o)))[:MAX_CATEGORIES]
    return [(f"o{o.id}", o.nom, par_org[o], o) for o in orgs], tdb


def _remplissage(v, c, kpis, codes_src):
    campagne = c.campagne
    par = (v.get("options") or {}).get("remplissage_par") or "organisations"
    items, tdb = remplissage_compteurs(c, campagne, par)
    if not items:
        return {"etat": "vide", "message": lib("visu.visuel.rien")}
    cats = []
    for cle, libelle, cpt, o in items:
        cat = {"cle": cle, "libelle": libelle, "taux": pourcent_texte(nombre(Decimal(str(cpt.taux)), 1)),
               "taux_texte": lib("visu.remplissage.taux", taux=pourcent_texte(nombre(Decimal(str(cpt.taux)), 1))), "cases": cpt.total}
        if o is not None:
            cat.update(org=o.id, descend=bool(c.source.enfants(o)))
        cats.append(cat)

    def s(cle, attr, etat):
        nombres = [getattr(x[2], attr) for x in items]
        textes = [f"{lib('visu.remplissage.cases', n=n, nombre=nombre(n, 0))} ({pourcent_texte(nombre(Decimal(str(x[2].pct(n))), 1))})" for n, x in zip(nombres, items)]
        return serie_brute(cle, lib(f"visu.remplissage.{cle}"), [float(n) for n in nombres], textes, [etat] * len(items),
                           decimales=0, pourcentage=False)
    # l'état de chaque case est dit par le nom de la série (validées, brouillons, à saisir), pas par un état de valeur
    series = [s("validees", "valide", "valide"), s("brouillons", "brouillon", "valide"), s("a_saisir", "a_saisir", "valide")]
    tab = tableau_generique(lib("visu.visuel.organisation") if par == "organisations" else lib("visu.filtres.themes") if par == "themes"
                            else "", cats, series)
    tab["entetes"].append(lib("visu.type.remplissage"))
    for ligne, cat, x in zip(tab["lignes"], cats, items):
        ligne["cellules"].append(cellule(cat["taux"], float(x[2].taux), d=1, p=True))
    return {"axe": par, "categories": cats, "series": series, "campagne": str(campagne), "campagne_id": campagne.pk,
            "taux_total": pourcent_texte(nombre(Decimal(str(tdb['total'].taux)), 1)), "tableau": tab}


CONSTRUCTEURS = {"chiffre": _chiffre, "barres": _barres, "barres_empilees": _barres_empilees, "courbe": _courbe,
                 "anneau": _anneau, "tableau": _tableau, "organisations": _organisations,
                 "comparaison_n1": _comparaison_n1, "remplissage": _remplissage}
