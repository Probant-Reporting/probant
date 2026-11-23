"""Paquet référentiel : analyse (aperçu avant import) du référentiel, des langues, niveaux et réglages."""
import re

from django.core.exceptions import ValidationError

from parametres import couleurs as CO
from parametres import langues as L
from parametres import niveaux as N
from parametres import rapprochement_unites as RU
from parametres.models import (CategorieDescription, ChampPersonnalise, Langue, TypeReponse, TypeSaisie, Unite,
                               valider_code_langue)
from referentiel.composition import code_referentiel
from referentiel.models import Frequence, Referentiel, valider_code_referentiel

from .. import fichiers as X

from .modele import PaquetInvalide, _t, texte_dans_langue
from .bibliotheque_json import comparer_versions
from .analyse_outils import (Analyse, Reglage, _code_libre, _differences_referentiel, _libelles_obj, _norm_textes,
                             _poser_textes, _poser_valeurs, _uuid, ajouts_type_reponse, unite_du_paquet)
from .analyse_kpis import _analyser_kpis, _analyser_regles, _analyser_themes


def analyser(p, choix=None, source="", fourni=False, catalogue=False):
    """Aperçu de l'import d'un paquet. ``choix`` : {"mode", "code", "niveau:<code>", "kpi:<code>", "code:<code>",
    "retirer_absents"} (formulaire de l'aperçu). ``catalogue`` : seuls les KPI (et leurs réglages) entrent au catalogue,
    sans référentiel (composition à partir d'un référentiel fourni)."""
    with L.session():
        a = Analyse(paquet=p, source=source, fourni=fourni)
        try:
            _analyser(a, choix or {}, catalogue)
        except PaquetInvalide as e:
            a.erreur = str(e)
        return a


def _analyser(a, choix, catalogue=False):
    p = a.paquet
    if catalogue:
        a.mode = "catalogue"
        _analyser_langues(a)
        _analyser_niveaux(a, choix)
        _analyser_reglages(a)
        _analyser_kpis(a, choix, {})
        _analyser_regles(a)
        return
    r = p.referentiel
    if r.get("_erreurs"):
        a.avertissements += r["_erreurs"]
    code = X.texte(r.get("code"))
    if not code:
        raise PaquetInvalide(_t("referentiels.paquets.code_manque"))
    try:
        valider_code_referentiel(code)
    except ValidationError as e:
        raise PaquetInvalide(_t("referentiels.paquets.code_invalide", code=code, erreurs=" ".join(e.messages)))
    if not any((r.get("nom") or {}).values()):
        raise PaquetInvalide(_t("referentiels.paquets.nom_manque"))
    _analyser_langues(a)
    _analyser_referentiel(a, choix)
    _analyser_niveaux(a, choix)
    _analyser_reglages(a)
    themes = _analyser_themes(a)
    _analyser_kpis(a, choix, themes)
    _analyser_regles(a)


def _memes_colonnes(a, b):
    """Deux définitions de colonnes de tableau équivalentes (codes, types, listes dans le même ordre)."""
    def cle(cols):
        return [(str(c.get("code")), c.get("type"), c.get("liste") or "") for c in (cols or []) if isinstance(c, dict)]
    return cle(a) == cle(b)


def _analyser_langues(a):
    p = a.paquet
    existantes = {l.code for l in Langue.objects.all()}
    utilisees = set()

    def voir(textes):
        utilisees.update(lg for lg, t in (textes or {}).items() if t)
    for k in p.kpis:
        voir(k.get("libelle"))
        for lg in (k.get("descriptions") or {}):
            utilisees.add(lg)
        voir((k.get("element") or {}).get("libelle"))
    for t in p.themes:
        voir(t.get("nom"))
    voir(p.referentiel.get("nom"))
    voir(p.referentiel.get("description"))
    libelles = {l["code"]: l.get("libelle") or l["code"] for l in p.langues}
    for lg in sorted(utilisees - existantes):
        try:
            valider_code_langue(lg)
        except ValidationError:
            a.avertissements.append(_t("referentiels.paquets.langue_ignoree", code_langue=lg))
            continue
        a.langues_creees.append((lg, libelles.get(lg, lg)))


def _analyser_referentiel(a, choix):
    """Nouveau référentiel, ou mise à jour : par défaut, celle du référentiel de même identifiant (une autre version du
    même) ; un référentiel qui a seulement le même code est un autre référentiel (nouveau code proposé), sauf si le paquet
    n'a pas d'identifiant (modèle rempli à la main) et porte le même nom."""
    p = a.paquet
    r = p.referentiel
    code = X.texte(r["code"])
    identifiant = X.texte(r.get("identifiant"))
    meme_id = Referentiel.objects.filter(identifiant=identifiant).first() if _uuid(identifiant) else None
    meme_code = Referentiel.objects.filter(code__iexact=code).first()
    a.candidat = meme_id or meme_code
    a.reconnu = meme_id is not None
    if meme_id is None and meme_code is not None and not _uuid(identifiant):
        a.reconnu = bool(_norm_textes(r.get("nom")) & _libelles_obj(meme_code, "nom"))
    a.code_propose = code if meme_code is None else code_referentiel(p.nom(p.langue_reference))
    mode = choix.get("mode") or ("mise_a_jour" if a.reconnu else "nouveau")
    if a.candidat is None or mode == "nouveau":
        nouveau = (X.texte(choix.get("code")) or a.code_propose) if meme_code is not None else code
        try:
            valider_code_referentiel(nouveau)
        except ValidationError as e:
            raise PaquetInvalide(_t("referentiels.paquets.code_nouveau_invalide", code=nouveau, erreurs=" ".join(e.messages)))
        if Referentiel.objects.filter(code__iexact=nouveau).exists():
            raise PaquetInvalide(_t("referentiels.paquets.code_existe", code=nouveau))
        a.mode, a.code = "nouveau", nouveau
    else:
        existant = a.candidat
        a.mode, a.code, a.existant = "mise_a_jour", existant.code, existant
        a.comparaison_version = comparer_versions(p.version, existant.version)
        a.referentiel_differences = _differences_referentiel(a, existant)
    if (r.get("frequence") or Frequence.ANNEE) not in Frequence.values:
        a.avertissements.append(_t("referentiels.paquets.frequence_inconnue"))
        r["frequence"] = Frequence.ANNEE
    if not 1 <= int(r.get("mois_debut") or 1) <= 12:
        a.avertissements.append(_t("referentiels.paquets.mois_hors"))
        r["mois_debut"] = 1
    couleur = (X.texte(r.get("couleur")) or "#1F5FAD").upper()
    r["couleur"] = couleur if CO.valide(couleur) else "#1F5FAD"


def _analyser_niveaux(a, choix):
    """Chaque niveau du paquet est relié à un niveau de l'installation : même code, sinon même nom ; un niveau qui ne se
    relie que par sa position (arbre différent) est rattaché automatiquement (règle de _niveaux_automatiques), sauf choix
    dans l'aperçu (``niveau:<code>`` = code local, ou « auto »). Un niveau cité sans onglet Niveaux et inconnu de
    l'installation n'est relié à rien : les KPI qui le citent sont rejetés."""
    p = a.paquet
    locaux = sorted(N.tous(), key=lambda n: n.rang)
    if not locaux:
        raise PaquetInvalide(_t("referentiels.paquets.aucun_niveau"))
    par_code = {n.code: n for n in locaux}
    utilises = {k.get("granularite") for k in p.kpis} | {r.get("niveau") for r in p.regles}
    niveaux_p = sorted(p.niveaux, key=lambda n: n.get("rang") or 0)
    connus = {n["code"] for n in niveaux_p}
    for c in sorted(x for x in utilises if x and x not in connus):  # niveau cité sans onglet Niveaux (modèle rempli à la main)
        n = next((x for x in locaux if c == x.code or X.normaliser(c) in _libelles_obj(x, "nom", "nom_pluriel")), None)
        if n is None:
            continue  # inconnu : « Granularité « … » inconnu(e) »
        niveaux_p.append({"code": c, "rang": n.rang, "nom": {p.langue_reference: n.nom}})
        p.niveaux.append(niveaux_p[-1])
    a.options_niveaux = [(n.code, n.nom) for n in locaux]
    for i, n in enumerate(niveaux_p):
        voulu = X.texte(choix.get(f"niveau:{n['code']}"))
        if n["code"] in par_code:
            local, motif = n["code"], "même code"
        else:
            noms = _norm_textes(n.get("nom")) | _norm_textes(n.get("nom_pluriel"))
            trouve = next((x for x in locaux if noms & _libelles_obj(x, "nom", "nom_pluriel")), None)
            if trouve:
                local, motif = trouve.code, "même nom"
            else:
                local, motif = "", "automatique"
        if voulu == "auto" and local:
            local, motif = "", "choisi : automatique"
        elif voulu in par_code and voulu != local:  # choisi dans l'aperçu
            local, motif = voulu, "choisi"
        a.niveaux.append((n, local, motif, n["code"] in utilises))


def _analyser_reglages(a):
    """Unités, types, catégories et champs du paquet : repris dans l'installation, sinon créés (code rendu unique)."""
    p, lg = a.paquet, a.paquet.langue_reference
    unites = list(Unite.objects.all())
    for u in p.unites:
        # symbole exact, code ou traduction exacte ; jamais une forme sans symboles (« €/h » n'est pas « h »)
        r = RU.rapprocher_unite((u.get("symbole") or {}).values(), unites, code=u["code"])
        local = r.unite
        if local:
            if r.casse:
                a.avertissements.append(_t("referentiels.paquets.unite_casse_reprise", texte=r.texte, symbole=r.casse))
            a.reglages.append(Reglage("unite", u["code"], texte_dans_langue(u.get("symbole"), lg, lg) or u["code"], "repris", local.code, local.symbole))
            continue
        if r.ecartee:
            a.avertissements.append(_t("referentiels.paquets.unite_casse_creee", texte=r.texte, symbole=r.ecartee))
        obj = unite_du_paquet(u, lg, len(unites) + 1)
        unites.append(obj)
        a.reglages.append(Reglage("unite", u["code"], obj.symbole, "cree", obj.code, obj.symbole, objet=obj))
    types = list(TypeSaisie.objects.all())
    for t in p.types_saisie:
        comp = t.get("comportement") or TypeSaisie.Comportement.SAISIE
        noms = _norm_textes(t.get("libelle")) | _norm_textes(t.get("abrege"))
        meme = [x for x in types if x.comportement == comp]
        local = (next((x for x in meme if x.code == t["code"]), None) or next((x for x in meme if noms & _libelles_obj(x, "libelle", "abrege")), None)
                 or (meme[0] if meme else None))
        if local:
            a.reglages.append(Reglage("type_saisie", t["code"], texte_dans_langue(t.get("libelle"), lg, lg) or t["code"], "repris", local.code, local.libelle))
            continue
        couleur = (X.texte(t.get("couleur")) or "#5B6B7F").upper()
        obj = TypeSaisie(code=_code_libre(TypeSaisie, t["code"], 20), libelle=texte_dans_langue(t.get("libelle"), lg, lg) or t["code"],
                         abrege=(texte_dans_langue(t.get("abrege"), lg, lg) or texte_dans_langue(t.get("libelle"), lg, lg) or t["code"])[:20],
                         couleur=couleur if CO.valide(couleur) else "#5B6B7F", comportement=comp, ordre=len(types) + 1)
        obj.deriver_couleurs()
        _poser_textes(obj, "libelle", t.get("libelle"), lg)
        _poser_textes(obj, "abrege", t.get("abrege"), lg)
        types.append(obj)
        a.reglages.append(Reglage("type_saisie", t["code"], obj.libelle, "cree", obj.code, obj.libelle, objet=obj))
    reponses = list(TypeReponse.objects.all())
    codes_locaux = {}  # code d'un type de réponse du paquet -> code dans l'installation (colonnes « liste » des tableaux)
    # les listes avant les tableaux : une colonne de tableau renvoie à une liste par son code, qui peut changer ici
    for t in sorted(p.types_reponse, key=lambda t: t.get("format") == TypeReponse.Format.TABLEAU):
        fmt = t.get("format") or TypeReponse.Format.NOMBRE
        fmt = TypeReponse.ANCIENS.get(fmt, fmt)  # paquet d'un ancien format
        cles = (t.get("valeurs") or {}).get(lg) or []
        colonnes = [dict(c, liste=codes_locaux.get(c.get("liste"), c.get("liste"))) if isinstance(c, dict) and c.get("liste") else c
                    for c in (t.get("colonnes") or [])] if fmt == TypeReponse.Format.TABLEAU else []
        meme = [x for x in reponses if x.format == fmt and (fmt != TypeReponse.Format.LISTE or list(x.valeurs) == list(cles))
                and (fmt != TypeReponse.Format.TABLEAU or _memes_colonnes(x.colonnes, colonnes))]
        noms = _norm_textes(t.get("libelle"))
        local = (next((x for x in meme if x.code == t["code"]), None) or next((x for x in meme if noms & _libelles_obj(x, "libelle")), None)
                 or (meme[0] if meme else None))
        if local:
            codes_locaux[t["code"]] = local.code
            a.reglages.append(Reglage("type_reponse", t["code"], texte_dans_langue(t.get("libelle"), lg, lg) or t["code"], "repris", local.code, local.libelle,
                                      ajouts=ajouts_type_reponse(local, t, lg) if a.fourni and local.code == t["code"][:20] else {}))
            continue
        obj = TypeReponse(code=_code_libre(TypeReponse, t["code"], 20), libelle=texte_dans_langue(t.get("libelle"), lg, lg) or t["code"],
                          format=fmt, valeurs=list(cles), colonnes=colonnes, ordre=len(reponses) + 1)
        codes_locaux[t["code"]] = obj.code
        _poser_textes(obj, "libelle", t.get("libelle"), lg)
        _poser_valeurs(obj, t.get("valeurs"), lg)
        reponses.append(obj)
        a.reglages.append(Reglage("type_reponse", t["code"], obj.libelle, "cree", obj.code, obj.libelle, objet=obj))
    categories = list(CategorieDescription.objects.all())
    for c in p.categories:
        noms = _norm_textes(c.get("libelle"))
        local = next((x for x in categories if x.code == c["code"]), None) or next((x for x in categories if noms & _libelles_obj(x, "libelle")), None)
        if local:
            a.reglages.append(Reglage("categorie", c["code"], texte_dans_langue(c.get("libelle"), lg, lg) or c["code"], "repris", local.code, local.libelle))
            continue
        obj = CategorieDescription(code=_code_libre(CategorieDescription, re.sub(r"[^A-Za-z0-9_]", "_", c["code"])[:30] or "categorie", 30),
                                   libelle=texte_dans_langue(c.get("libelle"), lg, lg) or c["code"], ordre=len(categories) + 1,
                                   affichee=c.get("affichee") is not False, obligatoire=False)
        _poser_textes(obj, "libelle", c.get("libelle"), lg)
        categories.append(obj)
        a.reglages.append(Reglage("categorie", c["code"], obj.libelle, "cree", obj.code, obj.libelle, objet=obj))
    champs = list(ChampPersonnalise.objects.all())
    for c in p.champs:
        type_ = c.get("type") or ChampPersonnalise.Type.TEXTE
        noms = _norm_textes(c.get("libelle"))
        meme = [x for x in champs if x.type == type_]
        local = next((x for x in meme if x.code == c["code"]), None) or next((x for x in meme if noms & _libelles_obj(x, "libelle")), None)
        if local:
            a.reglages.append(Reglage("champ", c["code"], texte_dans_langue(c.get("libelle"), lg, lg) or c["code"], "repris", local.code, local.libelle))
            continue
        obj = ChampPersonnalise(code=_code_libre(ChampPersonnalise, re.sub(r"[^A-Za-z0-9_]", "_", c["code"])[:30] or "champ", 30),
                                libelle=texte_dans_langue(c.get("libelle"), lg, lg) or c["code"], type=type_,
                                valeurs=list((c.get("valeurs") or {}).get(lg) or []), ordre=len(champs) + 1)
        _poser_textes(obj, "libelle", c.get("libelle"), lg)
        _poser_valeurs(obj, c.get("valeurs"), lg)
        champs.append(obj)
        a.reglages.append(Reglage("champ", c["code"], obj.libelle, "cree", obj.code, obj.libelle, objet=obj))
