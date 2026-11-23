"""Paquet référentiel : analyse des thèmes, KPI, formules et règles de cohérence."""
import copy
import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Max

from parametres import langues as L
from parametres import libelles as LB
from parametres import monnaies as MO
from parametres import niveaux as N
from parametres.models import CategorieDescription, ChampPersonnalise, TypeReponse, TypeSaisie
from referentiel import formule as F
from referentiel.bibliotheque.traductions import LANGUES as LANGUES_AJOUTEES
from referentiel.models import KPI, ElementReferentiel, Theme, valider_code_kpi, verifier_formule

from .. import fichiers as X
from .. import reglages as R
from ..models import RegleCoherence

from .modele import AUTO, NUMERIQUES, _t, texte_affiche, texte_dans_langue
from .analyse_outils import (LigneKpi, _avertir, _differences_textes, _etiq, _niveau, _norm_textes, _objet_reglage,
                             _poser_textes, _reglage, textes_ajoutes)


def _analyser_themes(a):
    """Thèmes du paquet comparés à ceux du référentiel existant (mise à jour) ; {code: chemin lisible}."""
    p, lg = a.paquet, a.paquet.langue_reference
    existants = {t.code: t for t in Theme.objects.filter(referentiel=a.existant)} if a.existant else {}
    codes_ex = {t.pk: t.code for t in existants.values()}
    vus, par_code = set(), {}
    for t in p.themes:
        code = X.texte(t.get("code"))
        if not code or code in vus:
            a.avertissements.append(_t("referentiels.paquets.theme_code_manquant", theme=code or texte_dans_langue(t.get("nom"), lg, lg)))
            continue
        if len(code) > 40:
            a.avertissements.append(_t("referentiels.paquets.theme_code_long", theme=code))
            continue
        vus.add(code)
        par_code[code] = t
    # thèmes cités par les KPI sans être dans l'onglet Thèmes (modèle rempli à la main) : créés au sommet
    for k in p.kpis:
        e = k.get("element")
        nom = X.texte((e or {}).get("theme"))
        if not nom or nom in par_code:
            continue
        trouve = [c for c, t in par_code.items() if X.normaliser(nom) in _norm_textes(t.get("nom"))]
        if len(trouve) == 1:
            e["theme"] = trouve[0]
            continue
        code = re.sub(r"[^A-Za-z0-9]+", "_", nom).strip("_")[:36] or "Theme"
        while code in par_code:
            code += "_"
        par_code[code] = {"code": code, "parent": "", "nom": {lg: nom}, "ordre": None, "_cite": True}
        e["theme"] = code
    for code, t in par_code.items():
        parent, vus_ = X.texte(t.get("parent")), {code}
        p_ = parent
        while p_:
            if p_ not in par_code:
                a.avertissements.append(_t("referentiels.paquets.theme_parent_inconnu", theme=code, parent=p_))
                t["parent"] = parent = ""
                break
            if p_ in vus_:
                a.avertissements.append(_t("referentiels.paquets.theme_boucle", theme=code))
                t["parent"] = parent = ""
                break
            vus_.add(p_)
            p_ = X.texte(par_code[p_].get("parent"))
    ordres = {}
    for code, t in par_code.items():  # ordre parmi les frères : celui du fichier, sinon l'ordre des lignes
        cle = X.texte(t.get("parent"))
        ordres[cle] = ordres.get(cle, 0) + 1
        if t.get("ordre") in (None, ""):
            t["ordre"] = ordres[cle]
    chemins = {}

    def chemin(code):
        if code not in chemins:
            t = par_code[code]
            nom = texte_affiche(t.get("nom"), lg) or code
            chemins[code] = (chemin(t["parent"]) + " › " if X.texte(t.get("parent")) else "") + nom
        return chemins[code]
    lg_ref = L.reference()
    for code, t in par_code.items():
        ex = existants.get(code)
        ligne = {"code": code, "nom": chemin(code), "parent": X.texte(t.get("parent")), "donnees": t, "objet": ex, "differences": []}
        if ex is None:
            ligne["statut"] = "nouveau"
        else:
            diffs = _differences_textes(ex, "nom", t.get("nom"), _etiq("nom"), lg_ref)
            parent_ex = codes_ex.get(ex.parent_id, "") if ex.parent_id else ""
            if parent_ex != ligne["parent"]:
                diffs.append((_t("referentiels.paquets.diff.parent"), parent_ex or "—", ligne["parent"] or "—"))
            if t.get("ordre") not in (None, "") and int(t["ordre"]) != ex.ordre:
                diffs.append((_t("referentiels.paquets.diff.ordre"), ex.ordre, int(t["ordre"])))
            ligne["differences"], ligne["statut"] = diffs, "modifie" if diffs else "inchange"
        a.themes.append(ligne)
    a.themes_absents = [t for c, t in existants.items() if c not in par_code]
    return {c: chemin(c) for c in par_code}


def _valeur_champ(c, v):
    if c.type == ChampPersonnalise.Type.CASE:
        return bool(v) if isinstance(v, bool) else X.oui(v)
    if c.type == ChampPersonnalise.Type.LISTE:
        return L.cle_valeur(c, c.valeurs, X.texte(v))
    if c.type == ChampPersonnalise.Type.DATE and hasattr(v, "date"):
        return v.date().isoformat()
    return X.texte(v)


def _analyser_kpis(a, choix, chemins_themes):
    p, lg = a.paquet, a.paquet.langue_reference
    existants = {k.code: k for k in KPI.objects.prefetch_related("descriptions", "elements__referentiel")}
    minuscules = {c.lower(): c for c in existants}
    numerique = next((t.code for t in TypeReponse.objects.all() if t.format == TypeReponse.Format.NOMBRE), None)
    categories = {r.code: r.code_local for r in a.reglages if r.genre == "categorie"}
    champs = {r.code: r.code_local for r in a.reglages if r.genre == "champ"}
    objets_champs = {c.code: c for c in ChampPersonnalise.objects.all()}
    objets_champs.update({r.code_local: r.objet for r in a.reglages if r.genre == "champ" and r.objet is not None})
    elements_ref = {e.kpi_id: e for e in ElementReferentiel.objects.filter(referentiel=a.existant).select_related("theme")} if a.existant else {}
    codes_themes_ex = {t.pk: t.code for t in Theme.objects.filter(referentiel=a.existant)} if a.existant else {}
    from ..models import Reponse

    avec_reponses = set(Reponse.objects.filter(kpi_id__in=[X.texte(k.get("code")) for k in p.kpis]).values_list("kpi_id", flat=True).distinct())
    # renommages connus d'avance (choix de l'aperçu, codes à la casse près) : les formules comparées les utilisent
    for k in p.kpis:
        code = X.texte(k.get("code"))
        local = existants.get(code) or existants.get(minuscules.get(code.lower(), ""))
        if local is None:
            continue
        if X.texte(choix.get(f"kpi:{code}")) == "renommer" and X.texte(choix.get(f"code:{code}")):
            a.renommages[code] = X.texte(choix[f"code:{code}"])
        elif local.code != code:
            a.renommages[code] = local.code
    vus, ordres_themes = {}, {}
    ordre_catalogue = KPI.objects.aggregate(m=Max("ordre"))["m"] or 0
    for k in p.kpis:
        code = X.texte(k.get("code"))
        e = k.get("element")
        ligne = LigneKpi(code=code, nom=texte_affiche(k.get("libelle"), lg) or code, donnees=k, dans_referentiel=e is not None,
                         theme=chemins_themes.get(X.texte((e or {}).get("theme")), _t("referentiels.contenu.lot.sans_theme")) if e is not None else "")
        a.kpis.append(ligne)
        motif = _controle_kpi(k, code, vus)
        if motif:
            ligne.statut, ligne.motif = "rejet", motif
            continue
        cible, motif = _cible(a, k, code, numerique)
        if motif:
            ligne.statut, ligne.motif = "rejet", motif
            continue
        valeurs_champs = {}
        for c, v in (k.get("champs") or {}).items():
            local_c = champs.get(c)
            if local_c and local_c in objets_champs:
                vc = _valeur_champ(objets_champs[local_c], v)
                if vc not in (None, "", False):
                    valeurs_champs[local_c] = vc
        for lg_d, textes in (k.get("descriptions") or {}).items():
            for cat, t in (textes or {}).items():
                if t and categories.get(cat):
                    ligne.descriptions.setdefault(lg_d, {})[categories[cat]] = t
        if e is not None:
            theme = X.texte(e.get("theme"))
            ordres_themes[theme] = ordres_themes.get(theme, 0) + 1
            ligne.element = {"theme": theme, "ordre": int(e["ordre"]) if e.get("ordre") not in (None, "") else ordres_themes[theme],
                             "libelle": e.get("libelle") or {},
                             "obligatoire": e.get("obligatoire") is not False}
        local = existants.get(code)
        local_ci = existants.get(minuscules.get(code.lower(), "")) if local is None else None
        if local is None and local_ci is None:  # nouveau au catalogue
            ordre_catalogue += 1
            cible.ordre, cible.champs = ordre_catalogue, valeurs_champs
            ligne.cible, ligne.statut, ligne.choix, ligne.code_final = cible, "nouveau", "creer", code
            continue
        local = local or local_ci
        ligne.local = local
        if cible.niveau_auto:  # sans niveau dans le paquet : le KPI de l'installation garde le sien
            cible.granularite_id, cible.niveau_auto = local.granularite_id, False
        ligne.aussi_dans = [x.referentiel for x in local.elements.all() if x.referentiel_id != a.code]
        if a.fourni and local.unite and cible.unite and MO.autre_monnaie_seule(local.unite.symbole, cible.unite.symbole):
            # modèle de la bibliothèque écrit dans une autre monnaie de référence : la monnaie d'un KPI déjà dans
            # l'installation n'est jamais réécrite (valeurs saisies, calculées ou aucune) ; seuls les KPI nouveaux la prennent
            cible.unite_modele, cible.unite = cible.unite, local.unite
            a.unites_gardees.append(local.code)
            _avertir(a, _t("admin.monnaies.unite_gardee", code=local.code, symbole=local.unite.symbole))
        ligne.diff_kpi = _differences_kpi(local, cible, k, valeurs_champs, ligne.descriptions, a)
        ligne.element_local = elements_ref.get(local.code) if local_ci is None else None
        if ligne.element is not None and ligne.element_local is not None:
            ligne.diff_place = _differences_element(ligne.element_local, ligne.element, codes_themes_ex, chemins_themes)
        if ligne.element_local is not None:  # mise à jour d'un KPI du référentiel
            ligne.statut = "modifie" if ligne.differences else "inchange"
            ligne.options = [("mettre_a_jour", _t("referentiels.paquets.choix.mettre_a_jour")), ("garder", _t("referentiels.paquets.choix.garder"))] if ligne.differences else []
            ligne.choix = "mettre_a_jour" if ligne.differences else "garder"
        elif not ligne.diff_kpi and local_ci is None:  # déjà au catalogue, à l'identique : réutilisé
            ligne.statut, ligne.choix = "inchange", "reutiliser"
        else:
            ligne.statut, ligne.choix = "conflit", "reutiliser"
            ligne.options = [(c, _t(f"referentiels.paquets.choix.{c}")) for c in ("reutiliser", "renommer", "ignorer")]
            if local_ci is not None:
                ligne.motif = _t("referentiels.paquets.meme_code_casse", code=local_ci.code)
        voulu = X.texte(choix.get(f"kpi:{code}"))
        if voulu in dict(ligne.options):
            ligne.choix = voulu
        if a.fourni and ligne.statut == "inchange":
            _ajouts_fournis(ligne, local, k)
        ligne.nouveau_code = X.texte(choix.get(f"code:{code}")) or _code_kpi_libre(code, existants, a)
        if ligne.choix in ("reutiliser", "garder", "ignorer"):
            ligne.code_final = local.code
            if local.code != code:
                a.renommages[code] = local.code
            else:
                a.renommages.pop(code, None)
        elif ligne.choix == "mettre_a_jour":
            ligne.code_final = local.code
            if not ligne.diff_kpi:
                continue
            maj = copy.copy(local)
            for champ in ("type_saisie", "type_reponse", "unite", "granularite_id", "decimales", "methode_agregation",
                          "agregation_temps", "formule", "saisie_au_dessus", "preuve_obligatoire", "confidentialite", "actif"):
                setattr(maj, champ, getattr(cible, champ))
            if cible.na_donne:  # absente d'un fichier d'avant cette case : la case de l'installation est gardée
                maj.na_compte_zero = cible.na_compte_zero
            maj.libelle = cible.libelle or local.libelle
            maj.traductions = {**(local.traductions or {}), **{l_: {**((local.traductions or {}).get(l_) or {}), **v}
                                                              for l_, v in (cible.traductions or {}).items()}}
            maj.champs = {**local.champs, **valeurs_champs}
            maj.agregation_temps_choisie = True
            if local.code in avec_reponses and maj.type_reponse.format != local.type_reponse.format:
                ligne.statut, ligne.motif = "rejet", _t("referentiels.paquets.type_reponse_change", avant=LB.choix(local.type_reponse, "format"),
                                                        apres=LB.choix(maj.type_reponse, "format"))
                continue
            if local.code in avec_reponses and (maj.unite_id or None) != (local.unite_id or None):
                # unité figée par les réponses saisies ou importées : la ligne est rejetée, le KPI reste tel quel
                n = R.nb_reponses_saisies(local.code)
                if n:
                    sans = _t("referentiels.paquets.sans_unite")
                    ligne.statut, ligne.motif = "rejet", _t("referentiels.paquets.unite_change", n=n,
                                                            avant=local.unite.symbole if local.unite else sans,
                                                            apres=maj.unite.symbole if maj.unite else sans)
                    continue
            ligne.cible = maj
        elif ligne.choix == "renommer":
            nouveau = ligne.nouveau_code
            try:
                valider_code_kpi(nouveau)
            except ValidationError as ex:
                ligne.statut, ligne.motif = "rejet", _t("referentiels.paquets.nouveau_code_invalide", code=nouveau, erreurs=" ".join(ex.messages))
                continue
            autres = {l.code_final.lower() for l in a.kpis if l is not ligne and l.code_final}
            if nouveau.lower() in minuscules or nouveau.lower() in autres:
                ligne.statut, ligne.motif = "rejet", _t("referentiels.paquets.nouveau_code_existe", code=nouveau)
                continue
            ordre_catalogue += 1
            cible.code, cible.ordre, cible.champs = nouveau, ordre_catalogue, valeurs_champs
            cible.unite = getattr(cible, "unite_modele", cible.unite)  # KPI nouveau : la monnaie de référence
            ligne.cible, ligne.code_final = cible, nouveau
            a.renommages[code] = nouveau
    _niveaux_automatiques(a, existants)
    # formules (et règles) : codes renommés, références connues après import, numériques, sans boucle
    _controler_formules(a, existants)
    if a.existant is not None:
        # absents de la nouvelle version (ou présents seulement comme sources de formules) ; une ligne rejetée ne retire rien
        gardes = {l.code_final for l in a.kpis if l.place} | {l.code for l in a.kpis if l.statut == "rejet" and l.dans_referentiel}
        a.retires = [x for c, x in sorted(elements_ref.items(), key=lambda x: (x[1].ordre, x[0])) if c not in gardes]
        a.retirer_absents = bool(choix.get("retirer_absents")) and bool(a.retires)


def _ajouts_fournis(ligne, local, k):
    """Nom qu'un modèle de la bibliothèque ajoute à un KPI déjà installé à l'identique (repris d'un autre modèle, ou même
    version) dans la langue de référence de l'installation, quand son champ porte le texte d'une autre langue."""
    libelle = textes_ajoutes(local, "libelle", k.get("libelle"), L.reference())
    if libelle:
        ligne.ajouts["libelle"] = libelle


def _niveaux_automatiques(a, existants):
    """Niveau de saisie des KPI nouveaux que le paquet ne rattache pas (modèle de la bibliothèque, fichier sans granularité) :
    paramètre hérité (facteur d'émission) au niveau le plus haut, repris en dessous ; KPI saisi au niveau le plus bas, ses
    valeurs remontent par l'agrégation, sauf niveau conseillé par le modèle (« haut » : une seule réponse pour l'entreprise,
    politique ou texte rédigé ; « pays » ; « entite » : une réponse par entité juridique) ; KPI calculé au niveau le plus haut de ses sources non héritées (le moteur ne calcule
    pas un KPI sous le niveau d'une de ses sources), le plus bas s'il n'en a pas. Un KPI déjà dans l'installation garde le sien."""
    locaux = sorted(N.tous(), key=lambda n: n.rang)
    if not locaux:
        return
    rangs = {n.code: n.rang for n in locaux}
    haut, bas = locaux[0].code, locaux[-1].code
    lignes = {}
    for l in a.kpis:
        if l.statut == "rejet":
            continue
        if l.cible is not None and l.code_final:
            lignes[l.code_final] = l.cible
        elif l.local is not None:
            lignes.setdefault(l.local.code, l.local)

    def kpi(code):
        return lignes.get(code) or existants.get(code)
    en_cours = set()

    def niveau_pays():
        """Niveau « Pays » de l'installation (code Country, ou nom pays / country / país dans une langue) ; sinon, dans un
        arbre de trois niveaux ou plus, le deuxième (filiales, souvent une par pays) ; sinon le plus haut."""
        import unicodedata

        def simple(t):
            return unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().strip().lower()
        for n in locaux:
            noms = {simple(n.code), simple(n.nom)} | {simple(v.get("nom")) for v in (n.traductions or {}).values() if isinstance(v, dict)}
            if noms & {"country", "pays", "pais", "countries"}:
                return n.code
        return locaux[1].code if len(locaux) >= 3 else haut

    def niveau_entite():
        """Niveau « Entité juridique » de l'installation (une déclaration par employeur) : code Entity ou Filiale (niveaux
        de départ et modèles de l'assistant), ou nom entité / filiale / société / legal entity / subsidiary dans une langue ;
        sinon, dans un arbre de trois niveaux ou plus, celui juste au-dessus du plus bas (les sites) ; sinon le plus haut."""
        import unicodedata

        from parametres.niveaux import NOMS_MODELES

        def simple(t):
            return unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().strip().lower()
        connus = {"entity", "filiale", "legal entity", "entite juridique", "societe", "company", "companies", "subsidiary",
                  "subsidiaries", "employer", "employeur"}
        for code in ("Entity", "Filiale"):
            for nom, pluriel in NOMS_MODELES[code].values():
                connus |= {simple(nom), simple(pluriel)}
        for n in locaux:
            noms = {simple(n.code), simple(n.nom)} | {simple(v.get("nom")) for v in (n.traductions or {}).values() if isinstance(v, dict)}
            if noms & connus:
                return n.code
        return locaux[-2].code if len(locaux) >= 3 else haut

    def niveau(k):
        if k.granularite_id and not getattr(k, "niveau_auto", False):
            return k.granularite_id
        conseil = getattr(k, "niveau_conseille", "")  # « haut », « pays » ou « bas » : niveau conseillé par le modèle
        if k.est_herite:
            k.granularite_id = niveau_pays() if conseil == "pays" else haut
        elif not k.est_calcule:
            k.granularite_id = (haut if conseil == "haut" else niveau_pays() if conseil == "pays"
                                else niveau_entite() if conseil == "entite" else bas)
        else:
            en_cours.add(k.code)
            sources = []
            for c in F.codes_cites(F.renommer(k.formule, a.renommages)):
                s = kpi(c)
                if s is None or s.code in en_cours or s.est_herite:
                    continue
                n = niveau(s)
                if n in rangs:
                    sources.append(n)
            en_cours.discard(k.code)
            k.granularite_id = min(sources, key=rangs.get) if sources else bas
        k.niveau_auto = False
        k.niveau_choisi_auto = True
        return k.granularite_id
    for l in a.kpis:
        if l.statut != "rejet" and l.cible is not None and getattr(l.cible, "niveau_auto", False):
            niveau(l.cible)
    for l in a.kpis:
        if l.statut != "rejet" and l.cible is not None and getattr(l.cible, "niveau_choisi_auto", False):
            l.niveau_auto = True


def _controle_kpi(k, code, vus):
    """Motif de rejet d'une ligne KPI avant toute comparaison (erreurs de cellule, code, nom), ou ""."""
    if k.get("_erreurs"):
        return " ; ".join(k["_erreurs"])
    if code.lower() in vus:
        return _t("referentiels.paquets.code_deux_fois", code=vus[code.lower()])
    vus[code.lower()] = code
    try:
        valider_code_kpi(code)
    except ValidationError as e:
        return " ".join(e.messages)
    if not any((k.get("libelle") or {}).values()):
        return _t("referentiels.config.nom_manquant")
    return ""


def _cible(a, k, code, numerique):
    """KPI tel que le paquet le décrit, avec les réglages de l'installation (en mémoire) ; (KPI, motif de rejet)."""
    lg = a.paquet.langue_reference
    type_saisie = (_reglage(a, "type_saisie", k.get("type_saisie")) if X.texte(k.get("type_saisie"))
                   else _type_saisie_par_defaut(bool(X.texte(k.get("formule")))))
    refs = [("type_saisie", type_saisie, k.get("type_saisie")),
            ("type_reponse", _reglage(a, "type_reponse", k.get("type_reponse")) if X.texte(k.get("type_reponse")) else numerique,
             k.get("type_reponse")),
            ("granularite", _niveau(a, X.texte(k.get("granularite"))) if X.texte(k.get("granularite")) else AUTO, k.get("granularite"))]
    manque = [_t(f"referentiels.paquets.inconnu.{lib}", valeur=X.texte(brut)) if X.texte(brut) else _t(f"referentiels.paquets.manquant.{lib}")
              for lib, v, brut in refs if not v]
    if manque:
        return None, " ; ".join(manque) + "."
    (_, type_saisie, _), (_, type_reponse, _), (_, granularite, _) = refs
    niveau_auto = granularite == AUTO  # sans niveau (modèle de la bibliothèque, colonne vide) : choisi par _niveaux_automatiques
    if niveau_auto:
        granularite = None
    texte_unite = X.texte(k.get("unite"))
    unite = _reglage(a, "unite", texte_unite) if texte_unite and texte_unite.lower() not in ("—", "-", "aucune", "sans") else None
    cible = KPI(code=code, libelle="", granularite_id=granularite)
    cible.niveau_auto = niveau_auto
    cible.niveau_conseille = X.texte(k.get("niveau_conseille")).lower()  # « pays » : facteur qui dépend du pays
    cible.type_saisie = _objet_reglage(a, "type_saisie", type_saisie)
    cible.type_reponse = _objet_reglage(a, "type_reponse", type_reponse)
    cible.unite = _objet_reglage(a, "unite", unite) if unite else None
    _poser_textes(cible, "libelle", k.get("libelle"), lg)
    cible.libelle = cible.libelle[:300]
    cible.decimales = int(k["decimales"]) if k.get("decimales") not in (None, "") else (cible.unite.decimales if cible.unite else 2)
    cible._decimales_coherentes()  # unité « nombre entier » : 0 décimale
    A = KPI.Agregation
    cible.methode_agregation = k.get("methode_agregation") or (
        A.AUCUNE if cible.est_herite else A.FORMULE if cible.est_calcule else A.SOMME if cible.est_numerique else A.DECOMPTE)
    cible.agregation_temps = k.get("agregation_temps") or cible.agregation_temps_par_defaut()
    cible.agregation_temps_choisie = True
    cible.formule = F.renommer(X.texte(k.get("formule")), a.renommages)
    # « Une source N/A compte comme 0 » : celle du fichier ; absente (fichier d'avant cette case), d'après la formule
    cible.na_donne = k.get("na_compte_zero") is not None
    cible.na_compte_zero = bool(k["na_compte_zero"]) if cible.na_donne else cible.na_compte_zero_par_defaut()
    cible.na_compte_zero_choisi = True
    cible.saisie_au_dessus = bool(k.get("saisie_au_dessus"))
    cible.preuve_obligatoire = bool(k.get("preuve_obligatoire"))
    cible.confidentialite = k.get("confidentialite") or KPI.Confidentialite.NON_SENSIBLE
    cible.actif = k.get("actif") is not False
    cible._agregation_temps_coherente()
    erreurs = cible.erreurs_regles()
    if erreurs:
        return None, " ".join(str(m) for m in erreurs.values())
    return cible, ""


def _type_saisie_par_defaut(formule):
    """Type de saisie d'une ligne qui n'en donne pas (modèle « système existant ») : calculé s'il y a une formule, sinon saisi."""
    voulu = TypeSaisie.Comportement.CALCUL if formule else TypeSaisie.Comportement.SAISIE
    return TypeSaisie.objects.filter(comportement=voulu).order_by("ordre", "code").values_list("code", flat=True).first()


def _code_kpi_libre(code, existants, a):
    pris = {c.lower() for c in existants} | {l.code_final.lower() for l in a.kpis if l.code_final} | {k.get("code", "").lower() for k in a.paquet.kpis}
    i = 2
    while f"{code}-{i}".lower() in pris:
        i += 1
    return f"{code}-{i}"[:30]


def _differences_kpi(local, cible, k, valeurs_champs, descriptions, a):
    lg_ref = L.reference()
    diffs = _differences_textes(local, "libelle", k.get("libelle"), _etiq("nom"), lg_ref, fourni=a.fourni)

    def nom(o):
        return "—" if o is None else (getattr(o, "symbole", None) or getattr(o, "libelle", None) or getattr(o, "nom", None) or str(o))
    if not hasattr(a, "_caches"):
        libelles = {c.code: c.libelle for c in CategorieDescription.objects.all()}
        libelles.update({r.code_local: r.libelle_local for r in a.reglages if r.genre == "categorie"})
        a._caches = {"niveaux": {n.code: n for n in N.tous()}, "categories": libelles}
    niveaux = a._caches["niveaux"]
    for lib, avant, apres in [(_t("referentiels.paquets.diff.type_saisie"), local.type_saisie, cible.type_saisie),
                              (_t("referentiels.paquets.diff.type_reponse"), local.type_reponse, cible.type_reponse),
                              (_t("referentiels.paquets.diff.unite"), local.unite, cible.unite)]:
        if (avant.pk if avant else None) != (apres.pk if apres else None):
            diffs.append((lib, nom(avant), nom(apres)))
    if local.granularite_id != cible.granularite_id:
        diffs.append((_t("referentiels.paquets.diff.granularite"), nom(niveaux.get(local.granularite_id)), nom(niveaux.get(cible.granularite_id))))
    oui, non = _t("commun.oui"), _t("commun.non")
    for lib, avant, apres in [(_t("referentiels.paquets.diff.decimales"), local.decimales, cible.decimales),
                              (_t("referentiels.paquets.diff.agregation"), local.methode_agregation, cible.methode_agregation),
                              (_t("referentiels.paquets.diff.agregation_temps"), LB.choix(local, "agregation_temps"), LB.choix(cible, "agregation_temps")),
                              (_t("referentiels.paquets.diff.formule"), local.formule, cible.formule),
                              (_t("referentiels.paquets.diff.saisie_au_dessus"), local.saisie_au_dessus, cible.saisie_au_dessus),
                              (_t("referentiels.paquets.diff.na_zero"), local.na_compte_zero,
                               cible.na_compte_zero if getattr(cible, "na_donne", True) else local.na_compte_zero),
                              (_t("referentiels.paquets.diff.preuve"), local.preuve_obligatoire, cible.preuve_obligatoire),
                              (_t("referentiels.paquets.diff.confidentialite"), local.confidentialite, cible.confidentialite),
                              (_t("referentiels.paquets.diff.actif"), local.actif, cible.actif)]:
        if avant != apres:
            diffs.append((lib, oui if avant is True else non if avant is False else avant, oui if apres is True else non if apres is False else apres))
    textes = {(d.langue, d.categorie_id): d.texte for d in local.descriptions.all()}
    libelles = a._caches["categories"]
    for lg, d in descriptions.items():
        for cat, t in d.items():
            if a.fourni and lg in LANGUES_AJOUTEES and (lg, cat) not in textes:  # traduction apportée par un modèle : un ajout
                continue
            if t != textes.get((lg, cat), ""):
                diffs.append((f"{libelles.get(cat, cat)} {L.suffixe(lg)}", X.court(textes.get((lg, cat), ""), 70), X.court(t, 70)))
    for c, v in valeurs_champs.items():
        if local.champs.get(c) != v:
            diffs.append((_t("referentiels.paquets.diff.champ", code=c), local.champs.get(c, "—"), v))
    return diffs


def _differences_element(e, element, codes_themes_ex, chemins):
    diffs = []
    avant = codes_themes_ex.get(e.theme_id, "") if e.theme_id else ""
    if avant != element["theme"]:
        sans_theme = _t("referentiels.contenu.lot.sans_theme")
        diffs.append((_t("referentiels.paquets.diff.theme_dans_ref"), e.theme.tr("nom") if e.theme_id else sans_theme, chemins.get(element["theme"], sans_theme)))
    if element["ordre"] != e.ordre:
        diffs.append((_t("referentiels.paquets.diff.ordre_dans_theme"), e.ordre, element["ordre"]))
    diffs += _differences_textes(e, "libelle", element["libelle"], _t("referentiels.paquets.diff.libelle_dans_ref"), L.reference())
    if element["obligatoire"] != e.obligatoire:
        diffs.append((_t("referentiels.paquets.diff.obligatoire"), _t("commun.oui") if e.obligatoire else _t("commun.non"),
                      _t("commun.oui") if element["obligatoire"] else _t("commun.non")))
    return diffs


def _controler_formules(a, existants):
    """Formules des KPI à écrire : codes renommés, puis références, nombres et boucles ; un rejet peut en entraîner
    d'autres (un KPI calculé dont une source nouvelle est rejetée)."""
    while True:
        ecrits = [l for l in a.kpis if l.statut != "rejet" and l.cible is not None]
        connus = set(existants) | {l.code_final for l in ecrits}
        non_numeriques = {c for c, k in existants.items() if not k.est_numerique}
        graphe = {c: F.codes_cites(k.formule, "N") for c, k in existants.items() if k.est_calcule and k.formule}
        for l in ecrits:
            l.cible.formule = F.renommer(X.texte(l.donnees.get("formule")), a.renommages)
            graphe[l.code_final] = F.codes_cites(l.cible.formule, "N") if l.cible.est_calcule else set()
            if l.cible.est_numerique:
                non_numeriques.discard(l.code_final)
            else:
                non_numeriques.add(l.code_final)
        rejets = 0
        # un KPI de l'installation cité dans une formule (après l'import) ne devient pas oui / non ou liste : sa ligne est
        # refusée (« Ce KPI est utilisé dans la formule de … »), avant les formules qui le citent
        cites = R.citations({l.code_final: l.cible.formule if l.cible.est_calcule else "" for l in ecrits})
        for l in ecrits:
            local = existants.get(l.code_final)
            if local is not None and local.est_numerique and not l.cible.est_numerique:
                motif = R.motif_cite_en_formule(l.cible.format, cites.get(l.code_final))
                if motif:
                    l.statut, l.motif = "rejet", motif
                    rejets += 1
        if rejets:
            continue
        for l in ecrits:
            k = l.cible
            if not k.est_calcule or not k.formule.strip():
                continue
            try:
                verifier_formule(l.code_final, k.formule, kpis_existants=connus, graphe=graphe, non_numeriques=non_numeriques)
            except ValidationError as e:
                l.statut, l.motif = "rejet", _t("referentiels.paquets.formule_erreur", erreurs=" ".join(e.messages))
                rejets += 1
        if not rejets:
            return


def _analyser_regles(a):
    """Règles du paquet face à celles de l'installation. Une règle = une condition : une règle dont la condition (parties
    normalisées, opérateur, tolérance, niveau) est déjà celle d'une règle de l'installation n'est pas recréée, quel que
    soit son nom (même contrôle installé par deux modèles, nom traduit ou changé par l'administrateur) ; le nom ne sert
    qu'à reconnaître la règle à mettre à jour."""
    from ..regles_textes import condition_de, texte_regle, textes_regle, traduire

    p = a.paquet
    existantes = {r.nom: r for r in RegleCoherence.objects.all()}
    conditions = {}
    for r in existantes.values():
        conditions.setdefault(condition_de(r), r)
    connus = set(KPI.objects.values_list("code", flat=True)) | {l.code_final for l in a.kpis if l.statut != "rejet" and l.cible is not None}
    non_numeriques = set(KPI.objects.exclude(type_reponse__format__in=NUMERIQUES).values_list("code", flat=True))
    non_numeriques |= {l.code_final for l in a.kpis if l.cible is not None and not l.cible.est_numerique}
    for r in p.regles:
        nom = texte_regle(r, "nom", p.langue_reference)[:200]
        ligne = {"nom": nom, "nom_final": nom, "statut": "nouveau", "differences": [], "motif": "", "objet": None}
        a.regles.append(ligne)
        if r.get("_erreurs"):
            ligne["statut"], ligne["motif"] = "rejet", " ; ".join(r["_erreurs"])
            continue
        obj = RegleCoherence(nom=nom, description=texte_regle(r, "description", p.langue_reference), gauche=F.renommer(X.texte(r.get("gauche")), a.renommages),
                             operateur=r.get("operateur") or "<=", droite=F.renommer(X.texte(r.get("droite")), a.renommages),
                             tolerance=Decimal(str(r.get("tolerance") or 0)), bloquante=bool(r.get("bloquante")), actif=r.get("actif") is not False)
        obj.niveau_id = _niveau(a, X.texte(r.get("niveau"))) if X.texte(r.get("niveau")) else None
        if obj.niveau_id in (None, AUTO):  # sans niveau : celui du premier KPI cité à gauche (importé ou déjà dans l'installation)
            obj.niveau_id = _niveau_regle(a, obj.gauche)
        try:
            if not obj.niveau_id:
                raise ValidationError(_t("referentiels.paquets.niveau_manquant"))
            for cote in (obj.gauche, obj.droite):
                if not cote.strip():
                    raise ValidationError(_t("referentiels.paquets.regle_parties"))
                verifier_formule("__regle__", cote, kpis_existants=connus, non_numeriques=non_numeriques)
        except ValidationError as e:
            ligne["statut"], ligne["motif"] = "rejet", " ".join(e.messages)
            continue
        # règle existante : sous le nom de la langue de référence de l'installation ; à la mise à jour d'un modèle, aussi
        # sous un autre nom du paquet (modèle installé par une version d'avant, qui enregistrait le nom français dans une
        # installation anglaise : la règle était « ignorée : même contrôle qu'elle-même ») ; le nom enregistré est gardé
        ex = existantes.get(nom)
        if ex is None and a.mode == "mise_a_jour":
            ex = next((existantes[n[:200]] for n in textes_regle(r, "nom", p.langue_reference).values() if n[:200] in existantes), None)
        if ex is not None:
            obj.nom = ligne["nom_final"] = ex.nom
        jumelle = conditions.get(condition_de(obj))
        meme_controle = _t("referentiels.paquets.regle_meme_controle", nom=traduire(jumelle.nom)) if jumelle is not None else ""
        if ex is None:
            if jumelle is not None:  # même contrôle déjà présent sous un autre nom : rien de recréé
                ligne.update(statut="ignore", motif=meme_controle)
                continue
            ligne["objet"] = obj
            conditions[condition_de(obj)] = obj  # deux règles du paquet sur la même condition : la première seulement
            continue
        diffs = [(_t(f"referentiels.paquets.regle.{c}"), getattr(ex, c), getattr(obj, c))
                 for c in ("description", "gauche", "operateur", "droite", "tolerance", "niveau_id", "bloquante", "actif")
                 if getattr(ex, c) != getattr(obj, c)]
        if not diffs:
            ligne["statut"] = "inchange"
        elif a.mode == "catalogue":  # composition : la règle de l'installation est gardée telle quelle
            ligne.update(statut="ignore", differences=diffs, motif=_t("referentiels.paquets.regle_existe"))
        elif a.mode == "mise_a_jour":
            obj.pk = ex.pk
            ligne.update(statut="modifie", differences=diffs, objet=obj)
        elif jumelle is not None:  # même nom, même contrôle (autre explication…) : rien de recréé
            ligne.update(statut="ignore", differences=diffs, motif=meme_controle)
        else:  # même nom, autre contenu, autre référentiel : la règle du paquet est ajoutée sous un autre nom
            nom_final, i = f"{nom} ({a.code})"[:200], 2
            while nom_final in existantes:
                nom_final, i = f"{nom} ({a.code} {i})"[:200], i + 1
            obj.nom = nom_final
            ligne.update(statut="renomme", nom_final=nom_final, differences=diffs, objet=obj)


def _niveau_regle(a, gauche):
    try:
        cites = [r.kpi for r in F.references(gauche)]
    except F.FormuleInvalide:
        return None
    niveaux = {l.code_final: l.cible.granularite_id for l in a.kpis if l.cible is not None and l.statut != "rejet"}
    for l in a.kpis:
        if l.local is not None and l.statut != "rejet":
            niveaux.setdefault(l.code_final or l.local.code, l.local.granularite_id)
    for c in cites:
        if c in niveaux:
            return niveaux[c]
    base = dict(KPI.objects.filter(code__in=cites).values_list("code", "granularite_id"))
    return next((base[c] for c in cites if c in base), None)
