"""Classeur de configuration : onglets Référentiels, Thèmes (en arbre) et Éléments (place de chaque KPI dans chaque
référentiel). Rien n'est supprimé par un import : un élément absent du fichier reste ; on retire un KPI d'un
référentiel dans l'outil (Référentiels › Gérer les référentiels ou fiche KPI).

Ancien format (KPI avec colonnes « Thème » et « Sous-thème », sans onglet Éléments) : les KPI sont rangés dans le
référentiel par défaut, sous les thèmes de ces noms (créés au besoin).
"""
import copy

from parametres import couleurs as CO
from parametres.libelles import libelle
from referentiel.composition import chemin_noms, placer, referentiel_par_defaut, theme_par_chemin
from referentiel.models import ElementReferentiel, Frequence, Referentiel, Theme, valider_code_referentiel

from . import fichiers as X

COLONNES_REFERENTIEL = [("code", "Code", 12, "texte"), ("nom", "Nom", 32, "texte"), ("description", "Description", 40, "texte"),
                        ("couleur", "Couleur", 10, "texte"), ("ordre", "Ordre", 7, "entier"), ("actif", "Actif", 7, "bool"),
                        ("frequence", "Fréquence", 13, Frequence), ("mois_debut", "Mois de début d'exercice", 10, "entier"),
                        ("comparaison", "Comparaison", 30, Referentiel.Comparaison)]
COLONNES_THEME = [("referentiel", "Référentiel", 12, "texte"), ("code", "Code", 30, "texte"), ("parent", "Parent", 30, "texte"),
                  ("nom", "Nom", 36, "texte"), ("ordre", "Ordre", 7, "entier")]
COLONNES_ELEMENT = [("referentiel", "Référentiel", 12, "texte"), ("kpi", "ID KPI", 12, "texte"), ("theme", "Thème", 30, "texte"),
                    ("ordre", "Ordre", 7, "entier"),
                    ("libelle", "Libellé dans le référentiel", 40, "texte"), ("obligatoire", "Obligatoire", 10, "bool"),
                    # « demandé depuis » : début de la première période ; vide : inchangé (nouveau KPI : la
                    # période en cours) ; « — » : depuis le début
                    ("demande_depuis", "Demandé depuis", 14, "jour")]
TRADUITS = {"Référentiels": ("nom", "description"), "Thèmes": ("nom",), "Éléments": ("libelle",)}


def colonnes(nom, langues):
    from .configuration import traduire_colonnes

    base = {"Référentiels": COLONNES_REFERENTIEL, "Thèmes": COLONNES_THEME, "Éléments": COLONNES_ELEMENT}[nom]
    return traduire_colonnes(base, TRADUITS[nom], langues)


def _lire(nom, lignes, cle, a, autres=None):
    from .configuration import alias_reference, lire_onglet

    cols = colonnes(nom, a.langues)
    alias = alias_reference(cols, TRADUITS[nom], a.langues) | (autres or {})
    return cols, (lire_onglet(lignes, cols, cle, alias) if lignes is not None else None)


# ---------------------------------------------------------------- analyse
def analyser_referentiels(a, lignes):
    """Référentiels après import ({code: objet}) : création, nom et description (par langue), couleur, ordre, actif."""
    from .configuration import Changement, appliquer_champs, appliquer_traductions

    existants = {r.code: r for r in Referentiel.objects.all()}
    a.referentiels = dict(existants)
    cols, donnees = _lire("Référentiels", lignes, "code", a)
    if donnees is None:
        return
    changements, vus = [], {}
    for n, d in donnees:
        code = X.texte(d["code"])
        ch = Changement(n, code)
        changements.append(ch)
        if code in vus:
            ch.motif = libelle("referentiels.config.code_deux_fois", ligne=vus[code])
            continue
        vus[code] = n
        try:
            valider_code_referentiel(code)
        except Exception as e:  # ValidationError
            ch.motif = " ".join(getattr(e, "messages", [str(e)]))
            continue
        existe = code in existants
        r = copy.copy(existants[code]) if existe else Referentiel(code=code, ordre=len(a.referentiels) + 1)
        if not appliquer_champs(r, d, cols, ch, existe, ignorer=("code",)):
            continue
        appliquer_traductions(r, d, cols, ch, existe)
        if not r.nom:
            ch.motif = libelle("referentiels.config.nom_manquant")
            continue
        r.couleur = (r.couleur or "#1F5FAD").upper()
        if not CO.valide(r.couleur):
            ch.motif = libelle("referentiels.config.couleur_format")
            continue
        if not 1 <= (r.mois_debut or 0) <= 12:
            ch.motif = libelle("referentiels.config.mois_debut")
            continue
        if existe and (r.frequence, r.mois_debut) != (existants[code].frequence, existants[code].mois_debut) \
                and existants[code].campagnes.exists():
            ch.motif = libelle("referentiels.config.campagnes_existent")
            continue
        ch.objet, ch.action = r, "creer" if not existe else ("modifier" if ch.champs else "inchange")
        a.referentiels[code] = r
    a.onglets["Référentiels"] = changements


def _cle_referentiel(a, texte):
    """Code d'un référentiel cité par son code ou son nom (langue de référence ou traduction)."""
    t = X.texte(texte)
    if t in a.referentiels:
        return t
    n = X.normaliser(t)
    for code, r in a.referentiels.items():
        noms = [r.nom] + [v.get("nom", "") for v in (r.traductions or {}).values()]
        if n and n in {X.normaliser(x) for x in noms if x}:
            return code
    return None


def analyser_themes(a, lignes):
    """Thèmes après import ({(référentiel, code): objet}) : création, nom (par langue), parent, ordre."""
    from .configuration import Changement, appliquer_champs, appliquer_traductions

    existants = {(t.referentiel_id, t.code): t for t in Theme.objects.all()}
    a.themes = dict(existants)
    a.parents_themes = {cle: (t.referentiel_id, existants_par_id(existants).get(t.parent_id)) for cle, t in existants.items()}
    cols, donnees = _lire("Thèmes", lignes, "code", a)
    if donnees is None:
        return
    changements, vus = [], {}
    for n, d in donnees:
        ref, code = _cle_referentiel(a, d.get("referentiel")), X.texte(d["code"])
        ch = Changement(n, f"{ref or X.texte(d.get('referentiel'))} · {code}")
        changements.append(ch)
        if ref is None:
            ch.motif = libelle("referentiels.config.referentiel_inconnu_onglet", referentiel=X.texte(d.get("referentiel")))
            continue
        if (ref, code) in vus:
            ch.motif = libelle("referentiels.config.code_deux_fois_ref", ligne=vus[(ref, code)])
            continue
        vus[(ref, code)] = n
        if len(code) > 40:
            ch.motif = libelle("referentiels.config.code_trop_long")
            continue
        existe = (ref, code) in existants
        t = copy.copy(existants[(ref, code)]) if existe else Theme(referentiel_id=ref, code=code)
        if not appliquer_champs(t, d, cols, ch, existe, ignorer=("code", "referentiel", "parent")):
            continue
        appliquer_traductions(t, d, cols, ch, existe)
        if not t.nom:
            ch.motif = libelle("referentiels.config.nom_manquant")
            continue
        parent = X.texte(d.get("parent")) if "parent" in d else (a.parents_themes.get((ref, code), (ref, None))[1] or "")
        avant = a.parents_themes.get((ref, code), (ref, None))[1] or ""
        if existe and parent != avant:
            ch.champs.append(("Parent", avant or "—", parent or "—"))
        a.parents_themes[(ref, code)] = (ref, parent or None)
        ch.objet, ch.action = t, "creer" if not existe else ("modifier" if ch.champs else "inchange")
        a.themes[(ref, code)] = t
    # parents : connus dans le même référentiel, sans boucle
    for ch in changements:
        if ch.action == "rejet" or ch.objet is None:
            continue
        ref, code = ch.objet.referentiel_id, ch.objet.code
        p, vus_ = a.parents_themes[(ref, code)][1], {code}
        while p:
            if (ref, p) not in a.themes:
                ch.action, ch.motif = "rejet", libelle("referentiels.config.parent_inconnu", theme=p)
                break
            if p in vus_:
                ch.action, ch.motif = "rejet", libelle("referentiels.config.boucle")
                break
            vus_.add(p)
            p = a.parents_themes.get((ref, p), (ref, None))[1]
    a.onglets["Thèmes"] = changements


def existants_par_id(existants):
    return {t.pk: t.code for t in existants.values()}


def analyser_elements(a, lignes, kpis_apres):
    """Place des KPI dans les référentiels : thème, ordre, code et libellé propres, obligatoire."""
    from .configuration import Changement, appliquer_champs, appliquer_traductions

    existants = {(e.referentiel_id, e.kpi_id): e for e in ElementReferentiel.objects.select_related("theme")}
    cols, donnees = _lire("Éléments", lignes, "kpi", a, {"kpi": ["KPI", "Code KPI", "ID KPI"]})
    a.elements_fichier = set()
    if donnees is None:
        return
    changements, vus = [], {}
    for n, d in donnees:
        ref, kid = _cle_referentiel(a, d.get("referentiel")), X.texte(d["kpi"])
        ch = Changement(n, f"{ref or X.texte(d.get('referentiel'))} · {kid}")
        changements.append(ch)
        if ref is None:
            ch.motif = libelle("referentiels.config.referentiel_inconnu", referentiel=X.texte(d.get("referentiel")))
            continue
        if kid not in kpis_apres:
            ch.motif = libelle("referentiels.config.kpi_inconnu", kpi=kid)
            continue
        if (ref, kid) in vus:
            ch.motif = libelle("referentiels.config.kpi_deux_fois", ligne=vus[(ref, kid)])
            continue
        vus[(ref, kid)] = n
        existe = (ref, kid) in existants
        e = copy.copy(existants[(ref, kid)]) if existe else ElementReferentiel(referentiel_id=ref, kpi_id=kid)
        theme = X.texte(d.get("theme")) if "theme" in d else (e.theme.code if existe and e.theme_id else "")
        if theme and (ref, theme) not in a.themes:
            par_nom = [c for (r, c), t in a.themes.items() if r == ref and X.normaliser(t.nom) == X.normaliser(theme)]
            if len(par_nom) != 1:
                ch.motif = libelle("referentiels.config.theme_inconnu", theme=theme)
                continue
            theme = par_nom[0]
        avant = e.theme.code if existe and e.theme_id else ""
        if existe and theme != avant:
            ch.champs.append(("Thème", avant or "Sans thème", theme or "Sans thème"))
        e._theme_code = theme
        avant_depuis = e.demande_depuis
        if not appliquer_champs(e, d, cols, ch, existe, ignorer=("referentiel", "kpi", "theme")):
            continue
        if e.demande_depuis != avant_depuis or (not existe and "demande_depuis" in d and X.texte(d["demande_depuis"])):
            ch.motif = _motif_depuis(e, existe, avant_depuis)
            if ch.motif:
                continue
            e.depuis_choisi = True  # date du fichier : choix explicite (même « — »)
        appliquer_traductions(e, d, cols, ch, existe)
        ch.objet, ch.action = e, "creer" if not existe else ("modifier" if ch.champs else "inchange")
        a.elements_fichier.add((ref, kid))
    a.onglets["Éléments"] = changements


def _motif_depuis(e, existe, avant):
    """Colonne « Demandé depuis » : mêmes règles que l'écran (``demande_depuis.Prevision``) ; motif de refus, ou vide.
    La date d'un référentiel qui a des campagnes est le début de l'une de ses périodes (ou de la période en cours) ; un
    recul qui retirerait des cases, même vides, se fait dans le contenu du référentiel (confirmation à l'écran)."""
    from .demande_depuis import Prevision, depuis_par_defaut
    from .models import Campagne

    ref = Referentiel.objects.filter(pk=e.referentiel_id).first()
    if ref is None or not Campagne.objects.filter(referentiel=ref).exists():
        return ""
    d = e.demande_depuis
    if d is not None and d != depuis_par_defaut(ref.pk) and not Campagne.objects.filter(referentiel=ref, periode__debut=d).exists():
        return libelle("referentiels.depuis.choix_inconnu")
    if not existe:
        return ""
    p = Prevision(ref, [e.kpi_id], d)
    if p.refus:
        return " ".join(p.refus)
    if p.a_confirmer:
        return libelle("referentiels.depuis.fichier_confirmer", code=e.kpi_id)
    return ""


def place_ancienne(a, ch, d, existe):
    """Colonnes « Thème » / « Sous-thème » d'un ancien classeur : place du KPI dans le référentiel par défaut."""
    if "ancien:theme" not in d and "ancien:sous_theme" not in d:
        return
    noms = [X.texte(d.get("ancien:theme")), X.texte(d.get("ancien:sous_theme"))]
    noms = [x for x in noms if x]
    ref = next((r for r in a.referentiels.values() if r.actif), None)
    avant = []
    if existe and ref is not None and ref.pk:
        e = ElementReferentiel.objects.filter(referentiel_id=ref.pk, kpi_id=ch.cle).select_related("theme__parent").first()
        avant = chemin_noms(e) if e else None
    if avant != noms:
        if existe:
            ch.champs.append(("Thème", " › ".join(avant or []) or "—", " › ".join(noms) or "—"))
        ch.place_ancienne = noms


# ---------------------------------------------------------------- application
def appliquer_referentiels(a):
    for c in a.onglets.get("Référentiels", []):
        if c.action in ("creer", "modifier"):
            c.objet.save()


def appliquer_themes(a):
    """Thèmes créés ou modifiés, les parents d'abord ; puis les rattachements."""
    a_ecrire = [c for c in a.onglets.get("Thèmes", []) if c.action in ("creer", "modifier")]
    for c in a_ecrire:
        t = c.objet
        t.parent = None if not t.pk else t.parent
        t.save()
    enregistres = {(t.referentiel_id, t.code): t for t in Theme.objects.all()}
    for c in a_ecrire:
        t = c.objet
        ref, parent = a.parents_themes[(t.referentiel_id, t.code)]
        t.parent = enregistres.get((ref, parent)) if parent else None
        t.save(update_fields=["parent"])


def appliquer_elements(a, utilisateur):
    from .models import Journal

    themes = {(t.referentiel_id, t.code): t for t in Theme.objects.all()}
    for c in a.onglets.get("Éléments", []):
        if c.action in ("creer", "modifier"):
            e = c.objet
            e.theme = themes.get((e.referentiel_id, e._theme_code)) if e._theme_code else None
            e.save()
            for lib, avant, apres in c.champs:
                Journal.ecrire(utilisateur, "reglage_kpi", e.kpi, f"{lib} ({e.referentiel_id})", avant, apres)


def appliquer_places_anciennes(a, kpis):
    """KPI d'un ancien classeur (colonnes Thème / Sous-thème) : rangés dans le référentiel par défaut."""
    a_placer = [c for c in a.onglets.get("KPI", []) if c.action in ("creer", "modifier") and getattr(c, "place_ancienne", None) is not None]
    if not a_placer:
        return
    ref, cache = referentiel_par_defaut(), {}
    for c in a_placer:
        if (ref.pk, c.cle) not in getattr(a, "elements_fichier", set()):
            placer(kpis[c.cle], ref, theme_par_chemin(ref, c.place_ancienne, cache))


# ---------------------------------------------------------------- export
def onglets(langues, vierge=False):
    """[(nom, colonnes, lignes)] des onglets Référentiels, Thèmes et Éléments."""
    from .configuration import lignes_traduites

    refs = [] if vierge else list(Referentiel.objects.all())
    themes = [] if vierge else list(Theme.objects.select_related("referentiel", "parent"))
    par_parent = {}
    for t in themes:
        par_parent.setdefault((t.referentiel_id, t.parent_id), []).append(t)
    ordonnes = []

    def parcourir(ref, parent):
        for t in sorted(par_parent.get((ref, parent), []), key=lambda t: (t.ordre, t.id)):
            ordonnes.append(t)
            parcourir(ref, t.id)
    for r in refs:
        parcourir(r.code, None)
    elements = [] if vierge else sorted(ElementReferentiel.objects.select_related("referentiel", "theme", "kpi"),
                                        key=lambda e: (e.referentiel.ordre, e.referentiel_id, ordonnes.index(e.theme) if e.theme else -1,
                                                       e.ordre, e.kpi_id))
    sortie = []
    cols = colonnes("Référentiels", langues)
    sortie.append(("Référentiels", cols, lignes_traduites(refs, cols)))
    cols = colonnes("Thèmes", langues)
    lignes = []
    for t, ligne in zip(ordonnes, lignes_traduites(ordonnes, cols)):
        ligne[[c for c, *_ in cols].index("referentiel")] = t.referentiel_id
        ligne[[c for c, *_ in cols].index("parent")] = t.parent.code if t.parent else ""
        lignes.append(ligne)
    sortie.append(("Thèmes", cols, lignes))
    cols = colonnes("Éléments", langues)
    noms = [c for c, *_ in cols]
    lignes = []
    for e, ligne in zip(elements, lignes_traduites(elements, cols)):
        ligne[noms.index("referentiel")], ligne[noms.index("kpi")] = e.referentiel_id, e.kpi_id
        ligne[noms.index("theme")] = e.theme.code if e.theme else ""
        lignes.append(ligne)
    sortie.append(("Éléments", cols, lignes))
    return sortie

