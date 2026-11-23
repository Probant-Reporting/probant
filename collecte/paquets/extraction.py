"""Paquet référentiel : extraction (installation → paquet)."""
from django.utils import timezone

from parametres import langues as L
from parametres import niveaux as N
from parametres.models import CategorieDescription, ChampPersonnalise, Instance, Langue, TypeReponse, TypeSaisie, Unite
from referentiel import formule as F
from referentiel.models import KPI, ElementReferentiel, KPIFormule, Theme

from .. import fichiers as X
from ..configuration import langues_fichier
from ..models import RegleCoherence

from .modele import Paquet


# ================================================================= extraction (installation → paquet)
def _textes(obj, champ, langues):
    ref = L.reference()
    return {lg: t for lg in langues if (t := L.texte(obj, champ, lg, ref))}


def _valeurs(obj, langues, avec_cles=True):
    """Valeurs d'une liste par langue : dans la langue de référence, les clés enregistrées dans les réponses ; dans les
    autres, leur traduction par position."""
    ref = L.reference()
    sortie = {ref: list(obj.valeurs)} if avec_cles and obj.valeurs else {}
    for lg in langues:
        if lg != ref and (tl := X.sans_fin_vide(L.valeurs_langue(obj, lg))):
            sortie[lg] = tl
    return sortie


def themes_ordonnes(ref):
    """Thèmes d'un référentiel dans l'ordre de l'arbre (parents d'abord)."""
    par_parent = {}
    for t in Theme.objects.filter(referentiel=ref):
        par_parent.setdefault(t.parent_id, []).append(t)
    sortie = []

    def parcourir(parent):
        for t in sorted(par_parent.get(parent, []), key=lambda t: (t.ordre, t.pk)):
            sortie.append(t)
            parcourir(t.pk)
    parcourir(None)
    return sortie


def _sources(codes):
    """Codes des KPI utilisés (directement ou non) par les formules de ``codes``."""
    graphe = {}
    for c, s in KPIFormule.objects.values_list("kpi_calcule_id", "kpi_source_id"):
        graphe.setdefault(c, set()).add(s)
    vus, pile = set(codes), list(codes)
    while pile:
        for s in graphe.get(pile.pop(), ()):
            if s not in vus:
                vus.add(s)
                pile.append(s)
    return vus - set(codes)


def _kpi_vers_dict(k, langues, element=None, themes_codes=None):
    descriptions = {}
    for d in k.descriptions.all():
        if d.texte:
            descriptions.setdefault(d.langue, {})[d.categorie_id] = d.texte
    d = {"code": k.code, "libelle": _textes(k, "libelle", langues), "type_saisie": k.type_saisie_id, "type_reponse": k.type_reponse_id,
         "unite": k.unite_id or "", "decimales": k.decimales, "granularite": k.granularite_id, "methode_agregation": k.methode_agregation,
         "agregation_temps": k.agregation_temps, "formule": k.formule,
         "saisie_au_dessus": k.saisie_au_dessus, "na_compte_zero": k.na_compte_zero, "preuve_obligatoire": k.preuve_obligatoire,
         "confidentialite": k.confidentialite, "actif": k.actif, "descriptions": descriptions,
         "champs": {c: v for c, v in sorted(k.champs.items()) if v not in ("", None)}, "element": None}
    if element is not None:
        d["element"] = {"theme": themes_codes.get(element.theme_id, "") if element.theme_id else "", "ordre": element.ordre,
                        "libelle": _textes(element, "libelle", langues),
                        "obligatoire": element.obligatoire}
    return d


def extraire(ref):
    """Paquet d'un référentiel de l'installation."""
    with L.session():
        return _extraire(ref)


def _extraire(ref):
    langues = langues_fichier()
    themes = themes_ordonnes(ref)
    rang = {t.pk: i for i, t in enumerate(themes)}
    codes_themes = {t.pk: t.code for t in themes}
    elements = sorted(ElementReferentiel.objects.filter(referentiel=ref).select_related("theme"),
                      key=lambda e: (rang.get(e.theme_id, -1), e.ordre, e.kpi_id))
    dans = [e.kpi_id for e in elements]
    kpis = {k.code: k for k in KPI.objects.filter(code__in=set(dans) | _sources(dans)).prefetch_related("descriptions")}
    hors = set(kpis) - set(dans)
    lignes = [_kpi_vers_dict(kpis[e.kpi_id], langues, e, codes_themes) for e in elements]
    lignes += [_kpi_vers_dict(kpis[c], langues) for c in sorted(hors, key=lambda c: (kpis[c].ordre, c))]
    tous = set(kpis)
    regles = []
    for r in RegleCoherence.objects.all():
        cites = F.codes_cites(r.gauche) | F.codes_cites(r.droite)
        if cites and cites <= tous and cites & set(dans):
            regles.append({"nom": r.nom, "description": r.description, "gauche": r.gauche, "operateur": r.operateur,
                           "droite": r.droite, "tolerance": str(X.nombre(r.tolerance)), "niveau": r.niveau_id,
                           "bloquante": r.bloquante, "actif": r.actif})
    ks = [kpis[c] for c in kpis]
    unites = {k.unite_id for k in ks if k.unite_id}
    types_saisie = {k.type_saisie_id for k in ks}
    types_reponse = {k.type_reponse_id for k in ks}
    for tr in TypeReponse.objects.filter(code__in=set(types_reponse), format=TypeReponse.Format.TABLEAU):  # listes des colonnes
        types_reponse |= {c.get("liste") for c in tr.colonnes or [] if isinstance(c, dict) and c.get("liste")}
    champs = {c for k in ks for c, v in k.champs.items() if v not in ("", None)}
    i = Instance.courante()
    return Paquet(
        referentiel={"code": ref.code, "identifiant": str(ref.identifiant), "nom": _textes(ref, "nom", langues), "description": _textes(ref, "description", langues),
                     "couleur": ref.couleur, "frequence": ref.frequence, "mois_debut": ref.mois_debut, "comparaison": ref.comparaison,
                     "version": ref.version, "date_version": ref.date_version.isoformat() if ref.date_version else "",
                     "origine": ref.origine},
        langue_reference=langues[0],
        langues=[{"code": l.code, "libelle": l.libelle} for l in sorted(Langue.objects.all(), key=lambda l: langues.index(l.code))],
        niveaux=niveaux_installation(langues),
        unites=[{"code": u.code, "symbole": _textes(u, "symbole", langues), "libelle": _textes(u, "libelle", langues),
                 "entier": u.entier, "decimales": u.decimales, "famille": u.famille} for u in Unite.objects.filter(code__in=unites)],
        types_saisie=[{"code": t.code, "libelle": _textes(t, "libelle", langues), "abrege": _textes(t, "abrege", langues),
                       "couleur": t.couleur, "comportement": t.comportement} for t in TypeSaisie.objects.filter(code__in=types_saisie)],
        types_reponse=[{"code": t.code, "libelle": _textes(t, "libelle", langues), "format": t.format,
                        "valeurs": _valeurs(t, langues), **({"colonnes": t.colonnes} if t.colonnes else {})}
                       for t in TypeReponse.objects.filter(code__in=types_reponse)],
        categories=[{"code": c.code, "libelle": _textes(c, "libelle", langues), "ordre": c.ordre, "affichee": c.affichee,
                     "obligatoire": c.obligatoire} for c in CategorieDescription.objects.all()],
        champs=[{"code": c.code, "libelle": _textes(c, "libelle", langues), "type": c.type, "valeurs": _valeurs(c, langues)}
                for c in ChampPersonnalise.objects.filter(code__in=champs)],
        themes=[{"code": t.code, "parent": codes_themes.get(t.parent_id, "") if t.parent_id else "", "nom": _textes(t, "nom", langues),
                 "ordre": t.ordre} for t in themes],
        kpis=lignes, regles=regles,
        exporte_le=timezone.localtime().strftime("%d/%m/%Y %H:%M"), exporte_de=i.nom,
    )


def niveaux_installation(langues=None):
    """Niveaux de l'arbre de l'installation, sous la forme d'un paquet (onglet Niveaux)."""
    langues = langues or langues_fichier()
    return [{"code": n.code, "rang": n.rang, "nom": _textes(n, "nom", langues), "nom_pluriel": _textes(n, "nom_pluriel", langues)}
            for n in N.tous()]
