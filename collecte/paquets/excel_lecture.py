"""Paquet référentiel : lecture du classeur Excel."""
from parametres import langues as L
from parametres.models import CategorieDescription, ChampPersonnalise, Langue
from referentiel.models import Referentiel

from .. import fichiers as X

from .modele import Paquet, PaquetInvalide, _t
from ..configuration import langues_fichier
from .extraction import _textes, _valeurs
from .bibliotheque_json import depuis_json
from .excel_ecriture import (AUTRES_LIGNES_REFERENTIEL, CHAMPS_REFERENTIEL, COL_LANGUES, COL_REGLES, COL_THEMES,
                             REGLAGES, SUFFIXE, _kpi_specs, codes_references)
from .analyse_outils import _etiq


# ================================================================= Excel : lecture
def _en_tetes(ligne):
    """[(index, base normalisée, langue ou None)] d'une ligne d'en-têtes."""
    sortie = []
    for j, h in enumerate(ligne):
        t = X.texte(h)
        if not t:
            continue
        m = SUFFIXE.match(t)
        sortie.append((j, X.normaliser(m.group("base")) if m else X.normaliser(t), m.group("langue") if m else None))
    return sortie


def _code_langue(texte, langues):
    for c in langues:
        if c.lower() == texte.lower():
            return c
    return texte.lower() if "-" not in texte else texte.split("-")[0].lower() + "-" + texte.split("-")[1].upper()


def _lire_table(lignes, specs, cle, langues, ref):
    """[(numéro de ligne, {clé: valeur})] d'un onglet tabulaire ; textes traduits en {langue: texte}. None si la ligne
    d'en-têtes (avec la colonne ``cle``) est introuvable."""
    from ..configuration import depuis_cellule

    noms = {}
    for c, entete, _, genre in specs:
        genre = "texte" if isinstance(genre, str) and genre.startswith("ref:") else genre
        for alias in X.entetes_acceptes(entete) + [c.split(":", 1)[-1]] + (ALIAS.get(c) or []):
            noms.setdefault(X.normaliser(alias), (c, genre))
    for i, ligne in enumerate(lignes[:15]):
        trouves = {}
        for j, base, langue in _en_tetes(ligne):
            if base in noms:
                c, genre = noms[base]
                trouves.setdefault(c, []).append((j, _code_langue(langue, langues) if langue else None, genre))
        if cle in trouves:
            break
    else:
        return None
    sortie = []
    for n, row in enumerate(lignes[i + 1:], start=i + 2):
        def brut(j):
            return row[j] if j < len(row) else None
        if not any(X.texte(v) for v in row):
            continue
        d = {}
        for c, colonnes in trouves.items():
            for j, langue, genre in colonnes:
                v = brut(j)
                if genre in ("textes", "valeurs"):
                    t = X.texte(v)
                    if t:
                        lg = langue or ref
                        d.setdefault(c, {})[lg] = [x.strip() for x in t.replace("\n", ";").split(";")] if genre == "valeurs" else t
                    else:
                        d.setdefault(c, {})
                    continue
                try:
                    d[c] = depuis_cellule(v, genre if genre != "texte" else "texte")
                except ValueError as e:
                    d.setdefault("_erreurs", []).append(_t("referentiels.paquets.erreur_cellule", champ=dict((x[0], x[1]) for x in specs).get(c, c), erreur=str(e)))
        if X.texte(d.get(cle)) if not isinstance(d.get(cle), dict) else d.get(cle):
            sortie.append((n, d))
    return sortie


ALIAS = {"code": ["ID", "Code KPI"], "libelle": ["Nom du KPI", "Indicateur"], "theme": ["Thème (code)"], "granularite": ["Niveau de saisie", "Niveau"],
         "dans_referentiel": ["Dans le référentiel ?"]}


def lire(fichier):
    """Paquet d'un classeur Excel (ou d'un fichier JSON). Lève PaquetInvalide avec un message lisible."""
    nom = (getattr(fichier, "name", "") or "").lower()
    if nom.endswith(".json"):
        try:
            texte = fichier.read().decode("utf-8-sig")
        except UnicodeDecodeError:  # pas de l'UTF-8 : refusé avec un message, jamais une erreur 500
            raise PaquetInvalide(_t("referentiels.paquets.json_illisible", erreur="UTF-8"))
        return depuis_json(texte)
    try:
        onglets = X.lire(fichier)
    except X.FichierInvalide as e:
        raise PaquetInvalide(str(e))
    par_nom = X.onglets_en_francais({X.normaliser(n): lignes for n, lignes in onglets.items()})
    if "referentiel" not in par_nom:
        if "referentiels" in par_nom:
            raise PaquetInvalide(_t("referentiels.paquets.classeur_config"))
        raise PaquetInvalide(_t("referentiels.paquets.pas_un_fichier"))
    with L.session():
        return _lire(par_nom)


def _lire(par_nom):
    from ..configuration import depuis_cellule

    infos, langues_vues = {}, []
    # libellé d'une ligne dans n'importe quelle langue de l'interface (le français, l'anglais, l'espagnol, l'allemand…) → français
    en_francais = {X.normaliser(X.entete(t, lg)): X.normaliser(t)
                   for t in [l for _, l, _ in CHAMPS_REFERENTIEL] + list(AUTRES_LIGNES_REFERENTIEL)
                   for lg in X.langues_disponibles()}
    for ligne in par_nom["referentiel"][1:]:
        if not ligne or not X.texte(ligne[0]):
            continue
        cle, v = X.texte(ligne[0]), ligne[1] if len(ligne) > 1 else None
        m = SUFFIXE.match(cle)
        if m:
            langues_vues.append(m.group("langue"))
            base = X.normaliser(m.group("base"))
            infos.setdefault(en_francais.get(base, base), {})[m.group("langue")] = X.texte(v)
        else:
            infos[en_francais.get(X.normaliser(cle), X.normaliser(cle))] = v
    ref_lg = X.texte(infos.get("languedereference")) or (langues_vues[0].lower() if langues_vues else L.reference())
    lignes_langues = par_nom.get("langues")
    langues = []
    if lignes_langues:
        for _, d in _lire_table(lignes_langues, COL_LANGUES, "code", [], ref_lg) or []:
            langues.append({"code": X.texte(d.get("code")), "libelle": X.texte(d.get("libelle")) or X.texte(d.get("code"))})
    codes_langues = [l["code"] for l in langues]
    for lg in langues_vues:
        c = _code_langue(lg, codes_langues + [x.code for x in Langue.objects.all()])
        if c not in codes_langues:
            langues.append({"code": c, "libelle": L.libelle(c)})
            codes_langues.append(c)
    ref_lg = _code_langue(ref_lg, codes_langues)
    referentiel = {}
    erreurs = []
    for cle, libelle, genre in CHAMPS_REFERENTIEL:
        n = X.normaliser(libelle)
        if genre == "textes":
            referentiel[cle] = {_code_langue(lg, codes_langues): t for lg, t in (infos.get(n) or {}).items() if t}
            if n in infos and not isinstance(infos[n], dict):  # « Nom » sans langue : langue de référence
                referentiel[cle] = {ref_lg: X.texte(infos[n])}
            continue
        if genre == "origine":  # pour information (l'import fixe l'origine) : code, libellé ou ancien libellé
            t = X.normaliser(infos.get(n))
            referentiel[cle] = next((c for c, l in list(Referentiel.LIBELLES_ORIGINE.items()) + list(Referentiel.Origine.choices)
                                     if t in (X.normaliser(c), X.normaliser(l))), None)
            continue
        try:
            referentiel[cle] = depuis_cellule(infos.get(n), genre)
        except ValueError as e:
            erreurs.append(_t("referentiels.paquets.erreur_cellule_ref", champ=_etiq(cle), erreur=str(e)))
    referentiel["code"] = X.texte(referentiel.get("code"))
    referentiel["version"] = X.texte(infos.get("version")) or "1.0"
    p = Paquet(referentiel=referentiel, langue_reference=ref_lg, langues=langues,
               exporte_le=X.texte(infos.get("exportele")), exporte_de=X.texte(infos.get("exportede")))
    for onglet, attr, specs in REGLAGES[:-1]:
        lignes = par_nom.get(X.normaliser(onglet))
        cle = specs[0][0]
        for _, d in (_lire_table(lignes, specs, cle, codes_langues, ref_lg) or []) if lignes else []:
            d.pop("_erreurs", None)
            d["code"] = X.texte(d["code"])
            getattr(p, attr).append(d)
    for t in p.types_reponse + p.champs:
        t["valeurs"] = t.get("valeurs") or {}
    langues_loc = langues_fichier()
    if not p.categories:  # onglet absent (modèle rempli à la main) : catégories de l'installation
        p.categories = [{"code": c.code, "libelle": _textes(c, "libelle", langues_loc), "ordre": c.ordre, "affichee": c.affichee,
                         "obligatoire": c.obligatoire} for c in CategorieDescription.objects.all()]
    if not p.champs:
        p.champs = [{"code": c.code, "libelle": _textes(c, "libelle", langues_loc), "type": c.type, "valeurs": _valeurs(c, langues_loc)}
                    for c in ChampPersonnalise.objects.all()]
    lignes = par_nom.get("themes")
    for n, d in (_lire_table(lignes, COL_THEMES, "code", codes_langues, ref_lg) or []) if lignes else []:
        p.themes.append({"code": X.texte(d.get("code")), "parent": X.texte(d.get("parent")), "ordre": d.get("ordre"),
                         "nom": d.get("nom") or {}, "_ligne": n})
    lignes = par_nom.get("kpi")
    codes = codes_references(p)  # « Groupe », « Saisie », « kWh » → codes du paquet (anciens fichiers : codes)
    if lignes:
        for n, d in _lire_table(lignes, _kpi_specs(p), "code", codes_langues, ref_lg) or []:
            k = _kpi_depuis_ligne(p, n, d)
            for champ, genre in (("granularite", "niveau"), ("type_saisie", "type_saisie"), ("type_reponse", "type_reponse"),
                                 ("unite", "unite")):
                k[champ] = codes[genre](k[champ])
            p.kpis.append(k)
    lignes = par_nom.get(X.normaliser("Règles de cohérence"))
    for n, d in (_lire_table(lignes, COL_REGLES, "nom", codes_langues, ref_lg) or []) if lignes else []:
        p.regles.append({"nom": X.texte(d.get("nom")), "description": X.texte(d.get("description")), "gauche": X.texte(d.get("gauche")),
                         "operateur": d.get("operateur") or "<=", "droite": X.texte(d.get("droite")),
                         "tolerance": str(d.get("tolerance") or 0), "niveau": codes["niveau"](d.get("niveau")),
                         "bloquante": bool(d.get("bloquante")), "actif": d.get("actif") is not False, "_erreurs": d.get("_erreurs", []),
                         "_ligne": n})
    p.referentiel["_erreurs"] = erreurs
    return p


def _kpi_depuis_ligne(p, n, d):
    dans = d.get("dans_referentiel")
    k = {"code": X.texte(d.get("code")), "libelle": d.get("libelle") or {}, "type_saisie": X.texte(d.get("type_saisie")),
         "type_reponse": X.texte(d.get("type_reponse")), "unite": X.texte(d.get("unite")), "decimales": d.get("decimales"),
         "granularite": X.texte(d.get("granularite")), "methode_agregation": d.get("methode_agregation") or "",
         "agregation_temps": d.get("agregation_temps") or "", "formule": X.texte(d.get("formule")),
         "saisie_au_dessus": d.get("saisie_au_dessus"), "na_compte_zero": d.get("na_compte_zero"),
         "preuve_obligatoire": d.get("preuve_obligatoire"), "confidentialite": d.get("confidentialite") or "",
         "actif": d.get("actif"), "descriptions": {}, "champs": {}, "_ligne": n, "_erreurs": d.get("_erreurs", [])}
    for c, v in d.items():
        if c.startswith("desc:"):
            for lg, t in (v or {}).items():
                if t:
                    k["descriptions"].setdefault(lg, {})[c[5:]] = t
        elif c.startswith("champ:") and v not in (None, ""):
            k["champs"][c[6:]] = v
    k["element"] = None if dans is False else {
        "theme": X.texte(d.get("theme")), "ordre": d.get("ordre"),
        "libelle": d.get("libelle_local") or {}, "obligatoire": d.get("obligatoire") is not False}
    return k
