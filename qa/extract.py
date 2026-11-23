"""Extraction d'une base pour la répétition de migration, avec le code de la version en place (ancienne ou nouvelle).

Lancé par qa/migration_rehearsal.py : « python extract.py SORTIE.json » dans le dossier du code (avant : un
checkout de main ; après : la version à installer). Écrit, en JSON, une vue normalisée et comparable entre versions :
fiches des KPI, organisations, comptes, attributions, campagnes, réponses, preuves, journal, exports « Base de données »
(tous exercices) et « Cases restant à saisir ». Ce fichier contient des données réelles : il reste dans le dossier de
travail temporaire et n'est jamais commité.
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()

from collecte import exports as E  # noqa: E402
from collecte.models import Campagne, Journal, Preuve, Reponse  # noqa: E402
from referentiel.models import KPI, Attribution, Organisation, Utilisateur  # noqa: E402

NOUVELLE = KPI._meta.pk.name == "code"  # versions d'avant la mise à jour : la clé des KPI avait un autre nom


def texte(v):
    return "" if v is None else str(v)


def email(u):
    return u.email if u else ""


# ---------------------------------------------------------------- KPI
def fiches_kpi():
    sortie = {}
    sources = {}
    from referentiel.models import KPIFormule

    for f in KPIFormule.objects.all():
        sources.setdefault(f.kpi_calcule_id, []).append([f.kpi_source_id, f.decalage])
    if NOUVELLE:
        from referentiel.plans import Plan

        plan = Plan()
        descr = {}
        from referentiel.models import Description

        for d in Description.objects.filter(langue="fr"):
            descr.setdefault(d.kpi_id, {})[d.categorie_id] = d.texte
    for k in KPI.objects.all():
        if NOUVELLE:
            code = k.code
            theme, sous = plan.titres(code)
            ch = k.champs or {}
            d = descr.get(code, {})
            f = dict(nom=k.libelle, nom_en=(k.traductions or {}).get("en", {}).get("libelle", ""), theme=theme, sous_theme=sous,
                     type_saisie=k.type_saisie_id, type_reponse=k.type_reponse_id, unite=texte(k.unite_id),
                     description=d.get("description", ""), a_inclure=d.get("a_inclure", ""), a_exclure=d.get("a_exclure", ""),
                     source_donnees=d.get("source", ""), id_efrag=texte(ch.get("id_efrag", "")), csrd_2026=texte(ch.get("csrd_2026", "")),
                     audit_2025=texte(ch.get("audit_2025", "")), audit_2026=texte(ch.get("audit_2026", "")),
                     nouveau=bool(ch.get("nouveau", False)), origine=texte(ch.get("origine", "")),
                     a_verifier=texte(ch.get("a_verifier", "")), formule_texte=texte(ch.get("formule_texte", "")),
                     granularite=k.granularite_id, unite_entiere=bool(k.unite_id and getattr(k.unite, "entier", False)))
        else:
            code = k.pk
            f = dict(nom=k.nom_fr, nom_en=k.nom_en, theme=k.theme, sous_theme=k.sous_theme, type_saisie=k.type_saisie,
                     type_reponse=k.type_reponse, unite=k.unite, description=k.description, a_inclure=k.a_inclure,
                     a_exclure=k.a_exclure, source_donnees=k.source_donnees, id_efrag=k.id_efrag, csrd_2026=k.csrd_2026,
                     audit_2025=k.audit_2025, audit_2026=k.audit_2026, nouveau=k.nouveau, origine=k.origine,
                     a_verifier=k.a_verifier, formule_texte=k.formule_texte, granularite=k.granularite)
        f.update(formule=k.formule, decimales=k.decimales, agregation=k.methode_agregation, equipe=k.equipe_responsable,
                 preuve_obligatoire=k.preuve_obligatoire, confidentialite=k.confidentialite, ordre=k.ordre, actif=k.actif,
                 sources=sorted(sources.get(code, [])))
        sortie[code] = {c: (v if isinstance(v, (bool, int, list)) else texte(v)) for c, v in f.items()}
    return sortie


# ---------------------------------------------------------------- reste de la base
def exercice(c):
    return c.periode.annee if NOUVELLE and hasattr(c.periode, "annee") else (c.periode.debut.year if NOUVELLE else c.exercice)


def campagnes():
    sortie = {}
    for c in Campagne.objects.all():
        cle = str(c.periode) if NOUVELLE else str(c.exercice)
        sortie[cle] = [c.statut, texte(c.date_ouverture), texte(c.date_fin_saisie), texte(c.seuil_ecart), texte(c.seuil_historique)]
    return sortie


def reponses():
    lignes = []
    qs = Reponse.objects.select_related("periode" if NOUVELLE else "campagne", "saisi_par", "valide_par")
    for r in qs:
        periode = str(r.periode) if NOUVELLE else str(r.campagne.exercice)
        lignes.append([periode, r.kpi_id, r.organisation.nom, texte(r.valeur.normalize() if r.valeur is not None else None),
                       getattr(r, "texte", "") or "", r.non_applicable, r.commentaire, r.statut, r.origine, email(r.saisi_par),
                       email(r.valide_par), texte(r.date_validation), texte(r.date_maj)])
    return sorted(lignes)


def exports():
    admin = next(u for u in Utilisateur.objects.filter(is_active=True).order_by("pk") if u.est_admin)
    sortie = {}
    for nom in ("powerbi", "manquantes"):
        p = E.Parametres.depuis({**E.PRESETS[nom][2], "format": "csv"})
        if NOUVELLE:
            from parametres import langues as L

            with L.session(), L.activer("fr"):
                p.langue = "fr"
                lignes = E.collecter(admin, p)
                sortie[nom] = [E.entetes_base(p)] + [[texte(x) for x in E.ligne_base(l, p)] for l in lignes]
        else:
            lignes = E.collecter(admin, p)
            sortie[nom] = [E.entetes_base(p)] + [[texte(x) for x in E.ligne_base(l, p)] for l in lignes]
    return sortie


def tableaux_et_vues():
    """Tableaux de la Visualisation (avant la v2) et vues (après) : des nombres et des identifiants techniques seulement."""
    from django.apps import apps

    sortie = {"tableaux": [], "vues": []}
    try:
        # des tuiles abîmées (pas une liste) comptent pour une seule tuile, comme dans la migration 0023
        sortie["tableaux"] = sorted([t.pk, len(t.tuiles) if isinstance(t.tuiles, list) else int(bool(t.tuiles))]
                                    for t in apps.get_model("collecte", "TableauVisu").objects.all())
    except LookupError:
        pass
    try:
        sortie["vues"] = sorted([len(v.visuels or []), email(v.proprietaire), v.partage, v.ancien_tableau]
                                for v in apps.get_model("collecte", "VueVisu").objects.select_related("proprietaire"))
    except LookupError:
        pass
    return sortie


def perimetres_mois():
    """Nouvelle version (collecte/0035 ; étendue à toutes les périodes, collecte/0039) : pour
    chaque période (mois, trimestre, semestre, année) qui a une campagne non clôturée, les KPI qu'elle calcule
    ({"libellé": [...], "#<numéro>": [...]}). Les migrations 0035 et 0039 font retirer, au recalcul de ces périodes, les
    cases sans objet des autres KPI ; la répétition les reconnaît ainsi. Ancienne version : {}. Le nom de la fonction
    (et de la clé) reste celui d'origine : les rapports déjà écrits le citent."""
    try:
        from collecte.calcul import perimetre_calcul
        from collecte.models import Periode
    except ImportError:
        return {}
    sortie = {}
    for p in Periode.objects.filter(campagnes__isnull=False).exclude(campagnes__statut="cloturee").distinct():
        codes = perimetre_calcul(p)
        if codes is not None:
            sortie[str(p)] = sortie[f"#{p.pk}"] = sorted(codes)
    return sortie


def extraire():
    return {
        "perimetres_mois": perimetres_mois(),
        **tableaux_et_vues(),
        "version": "nouvelle" if NOUVELLE else "ancienne",
        "kpis": fiches_kpi(),
        "organisations": sorted([o.nom, o.niveau_id if NOUVELLE else o.niveau, o.parent.nom if o.parent_id else "", o.actif, o.rang]
                                for o in Organisation.objects.select_related("parent")),
        "comptes": sorted([u.email, u.role, u.is_active, u.first_name, u.last_name, u.equipe if hasattr(u, "equipe") else ""]
                          for u in Utilisateur.objects.all()),
        "attributions": sorted([a.kpi_id, a.organisation.nom, a.utilisateur.email, a.role]
                               for a in Attribution.objects.select_related("organisation", "utilisateur")),
        "campagnes": campagnes(),
        "reponses": reponses(),
        # chemin rangé (fichier.name) et présence du fichier : le chemin peut changer (rangement collecte/0029), pas le reste
        "preuves": sorted([p.reponse.kpi_id, p.reponse.organisation.nom, p.nom_fichier, p.taille, p.fichier.name,
                           p.fichier.storage.exists(p.fichier.name)]
                          for p in Preuve.objects.select_related("reponse__organisation")),
        "journal": Journal.objects.count(),
        "exports": exports(),
    }


if __name__ == "__main__":
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(extraire(), f, ensure_ascii=False, default=str)
