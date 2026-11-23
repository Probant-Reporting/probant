"""Paquet référentiel : sous-paquet, composition depuis un paquet, sélection et installation."""
import copy

from parametres import langues as L
from parametres import niveaux as N
from referentiel import formule as F
from referentiel.models import ElementReferentiel, Frequence, Theme

from .. import fichiers as X
from ..models import Journal
from espaces import contexte as ESP

from .modele import PaquetInvalide, texte_dans_langue
from .analyse_outils import _poser_textes
from .analyse import analyser
from .application import _appliquer


# ================================================================= composition depuis un référentiel fourni
def sous_paquet(p, codes_themes=(), codes_kpi=()):
    """KPI d'un paquet à faire entrer au catalogue pour composer avec une partie de ce paquet : ceux des thèmes donnés
    (sous-thèmes compris) et les KPI donnés, plus les sources de leurs formules ; aucun n'a de place (pas de référentiel)."""
    enfants = {}
    for t in p.themes:
        enfants.setdefault(X.texte(t.get("parent")), []).append(t["code"])
    themes, pile = set(), list(codes_themes)
    while pile:
        c = pile.pop()
        if c not in themes:
            themes.add(c)
            pile.extend(enfants.get(c, []))
    par_code = {k["code"]: k for k in p.kpis}
    voulus = {k["code"] for k in p.kpis if (k.get("element") or {}).get("theme") in themes} | set(codes_kpi)
    pile = list(voulus)
    while pile:
        for c in F.codes_cites(par_code.get(pile.pop(), {}).get("formule", "")):
            if c in par_code and c not in voulus:
                voulus.add(c)
                pile.append(c)
    sous = copy.deepcopy(p)
    sous.kpis = [dict(k, element=None) for k in sous.kpis if k["code"] in voulus]
    sous.themes = []
    sous.regles = [r for r in sous.regles if (F.codes_cites(r.get("gauche", "")) | F.codes_cites(r.get("droite", ""))) <= voulus]
    return sous, themes


def composer_depuis_paquet(utilisateur, p, ref, parent=None, code_theme=None, code_kpi=None, fourni=True):
    """Glisser un thème (avec ses sous-thèmes) ou un KPI d'un référentiel fourni dans ``ref`` : les KPI entrent au catalogue
    (un KPI de même code déjà présent est réutilisé : une seule valeur), puis prennent place sous ``parent``. Renvoie
    (KPI ajoutés au référentiel, KPI déjà présents, KPI créés au catalogue, rejets)."""
    from referentiel.composition import code_libre_theme, ordre_suivant, ordre_theme_suivant

    sous, themes = sous_paquet(p, [code_theme] if code_theme else [], [code_kpi] if code_kpi else [])
    with L.session(), ESP.atomic():
        a = analyser(sous, source=p.nom(), fourni=fourni, catalogue=True)
        if a.erreur:
            raise PaquetInvalide(a.erreur)
        res = _appliquer(utilisateur, a, p.nom())
        codes = {l.code: l.code_final for l in a.kpis if l.statut != "rejet" and l.choix != "ignorer"}
        rejets = [f"{l.code} : {l.motif}" for l in a.kpis if l.statut == "rejet"]
        deja = set(ElementReferentiel.objects.filter(referentiel=ref).values_list("kpi_id", flat=True))
        ajoutes = presents = 0
        lg = p.langue_reference

        def placer_kpi(k, theme, ordre):
            nonlocal ajoutes, presents
            code = codes.get(k["code"])
            if code is None:
                return
            if code in deja:
                presents += 1
                return
            el = k.get("element") or {}
            e = ElementReferentiel(referentiel=ref, theme=theme, kpi_id=code, ordre=ordre,
                                   obligatoire=el.get("obligatoire") is not False)
            _poser_textes(e, "libelle", el.get("libelle"), lg)
            e.save()
            deja.add(code)
            ajoutes += 1

        if code_kpi:
            k = next(k for k in p.kpis if k["code"] == code_kpi)
            placer_kpi(k, parent, ordre_suivant(ref, parent))
        else:
            pris = set(Theme.objects.filter(referentiel=ref).values_list("code", flat=True))
            par_parent = {}
            for t in p.themes:
                par_parent.setdefault(X.texte(t.get("parent")), []).append(t)

            def copier(t, parent_cible, ordre):
                nom = texte_dans_langue(t.get("nom"), L.reference(), lg) or t["code"]
                nouveau = Theme(referentiel=ref, parent=parent_cible, code=code_libre_theme(ref, t["code"], nom, pris), nom="", ordre=ordre)
                _poser_textes(nouveau, "nom", t.get("nom"), lg)
                nouveau.nom = nouveau.nom[:150] or t["code"]
                nouveau.save()
                for i, k in enumerate(sorted((k for k in p.kpis if (k.get("element") or {}).get("theme") == t["code"]),
                                             key=lambda k: k["element"].get("ordre") or 0), start=1):
                    placer_kpi(k, nouveau, i)
                for i, enfant in enumerate(sorted(par_parent.get(t["code"], []), key=lambda x: x.get("ordre") or 0), start=1):
                    copier(enfant, nouveau, i)
            source = next(t for t in p.themes if t["code"] == code_theme)
            copier(source, parent, ordre_theme_suivant(ref, parent))
        Journal.ecrire(utilisateur, "reglage_referentiels", ref, "composition", "",
                       f"{ajoutes} KPI ajoutés depuis « {p.nom()} »" + (f", {res.kpis_crees} créés au catalogue" if res.kpis_crees else ""))
    return ajoutes, presents, res.kpis_crees, rejets


# ================================================================= installation d'un modèle : KPI cochés
def selection(p, codes):
    """Partie d'un paquet limitée aux KPI ``codes`` (cochés), plus les sources de leurs formules qui sont dans le paquet
    (ajoutées automatiquement, avec leur place dans le référentiel) ; thèmes vides retirés, règles gardées si tous leurs
    KPI sont retenus. Renvoie (sous-paquet, [(code ajouté, [KPI calculés qui l'utilisent])]) ; le référentiel garde son
    identifiant (reconnu comme installé depuis la bibliothèque)."""
    par_code = {X.texte(k.get("code")): k for k in p.kpis}
    coches = {c for c in codes if c in par_code}
    retenus, pile, utilise_par = set(coches), list(coches), {}
    while pile:
        c = pile.pop()
        for s in F.codes_cites(par_code[c].get("formule") or ""):
            if s not in par_code or s == c:
                continue
            if s not in coches:
                utilise_par.setdefault(s, set()).add(c)
            if s not in retenus:
                retenus.add(s)
                pile.append(s)
    sous = copy.deepcopy(p)
    sous.kpis = [k for k in sous.kpis if X.texte(k.get("code")) in retenus]
    parents = {X.texte(t.get("code")): X.texte(t.get("parent")) for t in p.themes}
    gardes = set()
    for k in sous.kpis:
        t = X.texte((k.get("element") or {}).get("theme"))
        while t and t not in gardes:
            gardes.add(t)
            t = parents.get(t, "")
    sous.themes = [t for t in sous.themes if X.texte(t.get("code")) in gardes]
    sous.regles = [r for r in sous.regles if (F.codes_cites(r.get("gauche") or "") | F.codes_cites(r.get("droite") or "")) <= retenus]
    ajoutes = [(X.texte(k.get("code")), sorted(utilise_par[X.texte(k.get("code"))])) for k in p.kpis
               if X.texte(k.get("code")) in utilise_par]
    return sous, ajoutes


def analyser_installation(p, codes, nom="", frequence="", mois_debut=None, code="", existant=None, nouvelle_version=False, choix=None):
    """Aperçu de l'installation des KPI ``codes`` d'un modèle de la bibliothèque : nouveau référentiel (nom, fréquence,
    début d'exercice et code de l'écran de résumé), ou complément du référentiel ``existant`` déjà installé depuis ce
    modèle (KPI ajoutés, rien retiré, rien d'autre de changé ; ``nouvelle_version`` : les définitions, thèmes et réglages du
    référentiel suivent aussi la version de la bibliothèque). Renvoie (analyse, KPI ajoutés automatiquement)."""
    from referentiel.models import ElementReferentiel as E

    presents = set(E.objects.filter(referentiel=existant).values_list("kpi_id", flat=True)) if existant else set()
    sous, ajoutes = selection(p, set(codes) | presents)
    ajoutes = [(c, par) for c, par in ajoutes if c not in presents]
    r = sous.referentiel
    if existant is None:
        # nom proposé à l'écran (dans la langue de l'interface) gardé : toutes les traductions du paquet et des fichiers de
        # langue restent ; nom changé par l'administrateur : il vaut pour sa langue, les autres traductions restent
        noms = sous.noms_connus()
        nom = (nom or "")[:150]
        if nom and nom not in noms.values() and nom != p.nom():
            noms[L.courante()] = nom
        r["nom"] = noms
        if frequence in Frequence.values:
            r["frequence"] = frequence
        if mois_debut and 1 <= int(mois_debut) <= 12:
            r["mois_debut"] = int(mois_debut)
        if code:
            r["code"] = code
        a = analyser(sous, {**(choix or {}), "mode": "nouveau", **({"code": code} if code else {})}, source=p.nom(), fourni=True)
        return a, ajoutes
    choix = {**(choix or {}), "mode": "mise_a_jour"}
    if not nouvelle_version:
        choix.update({f"kpi:{c}": "garder" for c in presents})
    a = analyser(sous, choix, source=p.nom(), fourni=True)
    a.retirer_absents = False
    if not a.erreur and not nouvelle_version:  # complément : le référentiel et ses thèmes restent tels quels
        a.referentiel_differences = []
        for t in a.themes:
            if t["statut"] == "modifie":
                t["statut"], t["differences"] = "inchange", []
    return a, ajoutes



def resume_niveaux(a):
    """KPI créés dont l'outil a choisi le niveau : {famille: [(niveau, nombre)]}, familles « saisis », « parametres »
    (hérités) et « calcules », niveaux du plus haut au plus bas."""
    niveaux = {n.code: n for n in N.tous()}
    compte = {}
    for l in a.kpis:
        if not l.niveau_auto or not l.ecrit or l.cible is None:
            continue
        k = l.cible
        famille = "parametres" if k.est_herite else "calcules" if k.est_calcule else "saisis"
        compte.setdefault(famille, {}).setdefault(k.granularite_id, 0)
        compte[famille][k.granularite_id] += 1
    return {f: [(niveaux.get(c), n) for c, n in sorted(d.items(), key=lambda x: niveaux[x[0]].rang if x[0] in niveaux else 99)]
            for f, d in compte.items()}
