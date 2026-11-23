"""Import / Export : exporter les données, importer des valeurs ; et, pour l'admin, Administration › Fichiers de configuration
(configuration en fichier : sauvegarde, mise à jour en masse, modèles)."""
import datetime
import os
import pickle
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from parametres import langues as L
from parametres import niveaux as N
from parametres import sauvegardes as SV
from parametres.libelles import libelle
from referentiel.models import KPI, Organisation, OrgAlias, Referentiel
from referentiel.plans import Plan

from . import configuration as C
from . import corbeille as CB
from . import exports as E
from . import exports_arriere_plan as EAP
from . import fichiers as X
from . import imports as I
from . import imports_arriere_plan as AP
from . import saisie as S
from .models import Campagne, ProfilReprise, RegleCoherence, ReglageExport, SelectionKPI, TacheExport, TacheImport
from .templatetags.collecte import avec_pourcent
from .reponses_script import reponse_erreur
from .views import groupes_campagnes
from .vues_communes import campagne_affichee, corps_json, exiger_admin, identifiant
from parametres.rangement import IMPORTS

EXTENSIONS = (".xlsx", ".xlsm", ".csv", ".txt")


def _niveaux():
    return [(n.code, n.nom) for n in N.tous()]


# ---------------------------------------------------------------- Mes exports (page d'arrivée)
@login_required
def accueil(request):
    """Import / Export › Mes exports : les exports enregistrés de la personne et ceux partagés par l'administrateur, chacun
    téléchargeable en un clic (fichier à jour) ; « Nouvel export » ouvre le constructeur."""
    modeles = list(_reglages_visibles(request.user).order_by("ordre", "nom"))
    for m in modeles:
        m.resume = E.Parametres.depuis(m.parametres).resume()
        m.modifiable = _modifiable(request.user, m)
    taches = EAP.a_montrer(request.user)
    if any(t.active for t in taches):
        EAP.entretien()  # serveur redémarré : reprise ou « interrompu », jamais « en cours » pour toujours
        if any(t.statut == TacheExport.Statut.ATTENTE for t in taches):
            EAP.lancer()  # sans planificateur, un fil de ce processus la prend
        taches = EAP.a_montrer(request.user)
    taches, retirees = EAP.retirer_droits_changes(request.user, taches)
    if retirees:
        messages.error(request, libelle("suivi.echanges.msg.export_fond_droits"))
    EAP.marquer_vues(taches)
    return render(request, "collecte/echanges/mes_exports.html", {
        "page": "echanges", "rubrique": "exports", "modeles": modeles, "taches_export": taches, "jours_export": EAP.jours(),
        "manquants": [n for n, _, _ in E.PRESETS.values() if n not in {m.nom for m in modeles}] if request.user.est_admin else [],
    })


# ---------------------------------------------------------------- exporter (nouvel export, ou réglages d'un export enregistré)
def _reglages_visibles(utilisateur):
    return ReglageExport.objects.filter(Q(proprietaire=utilisateur) | Q(partage=True)).select_related("proprietaire")


def _modifiable(utilisateur, r):
    """Un export partagé se règle par l'administrateur ; un export personnel par la personne qui l'a créé."""
    return utilisateur.est_admin if r.partage else r.proprietaire_id == utilisateur.id


@login_required
def exporter(request):
    modeles = list(_reglages_visibles(request.user).order_by("ordre", "nom"))
    pk = request.POST.get("modele") or request.GET.get("modele") or ""
    modele = next((m for m in modeles if str(m.pk) == pk), None)
    if request.method == "GET" and modele is None and not request.GET.get("nouveau"):
        return redirect("collecte:echanges")  # la liste « Mes exports » ; le constructeur s'ouvre par « Nouvel export » ou « Modifier »
    if request.method == "POST":
        p = E.Parametres.depuis(request.POST)
        action = request.POST.get("action")
        nom = request.POST.get("nom", "").strip()[:100]
        description = request.POST.get("description", "").strip()[:200]
        partage = request.user.est_admin and request.POST.get("partage") == "on"
        if action == "enregistrer" and modele and _modifiable(request.user, modele):
            modele.nom, modele.description, modele.parametres = nom or modele.nom, description, p.en_dict()
            modele.partage = partage if request.user.est_admin else modele.partage
            modele.save()
            messages.success(request, libelle("suivi.echanges.msg.export_maj", nom=modele.nom))
            _avertir_selection(request, modele, p)
            return redirect("collecte:echanges")
        if action in ("enregistrer", "copier"):
            if not nom:
                messages.error(request, libelle("suivi.echanges.msg.export_nom_requis"))
            else:
                if action == "copier" and modele and nom == modele.nom:
                    nom = libelle("suivi.echanges.msg.copie", nom=nom)
                fin = max((x.ordre for x in modeles), default=0) + 1
                m = ReglageExport.objects.create(nom=nom, description=description, parametres=p.en_dict(),
                                                 proprietaire=request.user, partage=partage, ordre=fin)
                messages.success(request, libelle("suivi.echanges.msg.export_enregistre_partage" if m.partage
                                                  else "suivi.echanges.msg.export_enregistre", nom=m.nom))
                _avertir_selection(request, m, p)
                return redirect("collecte:echanges")
        elif action == "telecharger":
            if not p.annees():
                messages.error(request, libelle("suivi.echanges.msg.exercice_requis"))
            elif not p.niveaux and not p.organisations:  # « Tout décocher » : un fichier vide, sans un mot, avant
                messages.error(request, libelle("suivi.echanges.msg.organisation_requise"))
            else:
                try:
                    nomme = bool(modele and p.en_dict() == E.Parametres.depuis(modele.parametres).en_dict())
                    return _telecharger_export(request, p, modele.nom_affiche if nomme else "", E.code_fourni(modele) if nomme else "")
                except E.ExportTropGros as e:  # plus de lignes qu'une feuille Excel n'en contient : on le dit, sans fichier
                    messages.error(request, str(e))
    else:
        depart = E.PRESETS.get(request.GET.get("depart", ""))  # nouvel export qui part d'un modèle fourni
        p = E.Parametres.depuis(modele.parametres) if modele else E.Parametres.depuis(depart[2]) if depart else E.Parametres()
        if modele is None and depart is None:
            p.presentation = "tableau"  # nouvel export : le tableau lisible parle à tous 
        if modele is None and SelectionKPI.visibles(request.user).filter(pk=request.GET.get("selection") or 0).exists() \
                if str(request.GET.get("selection", "")).isdecimal() else False:
            p.selection = request.GET["selection"]  # « Exporter ces KPI » depuis une sélection
        if modele and request.GET.get("telecharger"):
            try:
                return _telecharger_export(request, p, modele.nom_affiche, E.code_fourni(modele))
            except E.ExportTropGros as e:
                messages.error(request, str(e))
        if modele is None and depart is None and Referentiel.objects.filter(actif=True).count() > 1:
            choisie = campagne_affichee(request)  # nouvel export : « Quels KPI ? » préréglé sur le référentiel choisi (modifiable)
            if choisie is not None and choisie.referentiel.actif:
                p.referentiel = choisie.referentiel_id
    campagne = campagne_affichee(request)
    arbre = S.arbre_organisations()
    if request.user.est_admin:
        orgs = sorted((o for o in arbre.values() if o.actif), key=S.cle_arbre)
    else:
        orgs = [o for o, *_ in S.organisations_visibles(request.user, campagne)] if campagne else []
    if modele:
        modele.modifiable = _modifiable(request.user, modele)
    defaut = E.Parametres()
    return render(request, "collecte/echanges/exporter.html", {
        "page": "echanges", "rubrique": "exports", "p": p, "modele": modele,
        "options_modifiees": (p.contenus != defaut.contenus or p.types != defaut.types
                              or (p.langue and p.langue != L.courante())),
        # langue du fichier : par défaut celle de l'interface (un export pris en espagnol sortait en
        # français) ; si ce n'est pas une langue des contenus, « Langue de l'interface » est proposée et choisie
        "langues_export": L.actives(), "interface_hors_contenus": L.interface() not in L.codes_actifs(),
        "langue_export": p.langue if p.langue in L.codes_actifs() else (
            L.interface() if L.interface() in L.codes_actifs() else "" if not p.langue else L.courante()),
        "presentations": E.presentations(utilisateur=request.user), "contenus": E.contenus(), "types": E.types_export(), "niveaux": _niveaux(),
        "exercices": sorted(set(Campagne.objects.values_list("exercice", flat=True)), reverse=True), "campagne": campagne,
        "exercices_en_cours": {c.exercice for c in S.campagnes_en_cours()} or ({campagne.exercice} if campagne else set()),
        "types_periodes": [(t, l) for t, l in E.types_periodes() if t in set(Campagne.objects.values_list("periode__type", flat=True))],
        "periodes_choisies": set(p.periodes),
        "orgs": [(o, 4 + 22 * (len(S.cle_arbre(o)) - 1), " ".join(str(a.id) for a in o.ancetres())) for o in orgs],
        "referentiels": list(Referentiel.objects.filter(actif=True)),
        "exercices_choisis": set(p.exercices), "orgs_choisies": set(p.organisations),
        "phrase": p.phrase(), "ck": _choix_kpi(request.user, p.selection, p.kpis, p.themes, p.referentiel),
        "seuil_gros_export": f"{E.SEUIL_GROS_EXPORT:,}".replace(",", "\u202f"),
    })


def _telecharger_export(request, p, titre, fourni=""):
    """Le fichier tout de suite, comme toujours ; au-delà du seuil des gros exports (cellules estimées avant de lire les
    réponses), une tâche en arrière-plan et la page Mes exports. Lève ``ExportTropGros`` (limite d'une feuille Excel)."""
    adresse = request.build_absolute_uri(reverse("collecte:accueil"))
    if EAP.seuil():
        cellules = E.estimer_cellules(request.user, p)
        if EAP.en_arriere_plan(cellules):
            E.refuser_si_trop_gros(request.user, p)  # dit tout de suite, sans attendre la tâche
            nom = titre or next((n for c, n, _ in E.presentations() if c == p.presentation), "")
            annees = p.annees()
            if annees:
                nom = libelle("suivi.echanges.exports.fond.nom_annees", nom=nom, annees=", ".join(map(str, annees)))
            # nom composé par l'outil (aucun titre, ou un modèle fourni) : noté pour s'afficher dans la langue de qui lit
            # (``titre_affiche``) ; le nom d'un export enregistré par une personne reste tel qu'elle l'a écrit
            compose = {"titre_compose": {"presentation": p.presentation, "annees": list(annees or [])}} if not titre else \
                {"titre_compose": {"fourni": fourni, "annees": list(annees or [])}} if fourni else {}
            return _demander_en_arriere_plan(request, EAP.G.EXPORT, nom, {"reglages": p.en_dict(), "titre": titre,
                                                                         "adresse": adresse, **compose}, cellules)
    return E.exporter(request.user, p, titre, adresse)


def _demander_en_arriere_plan(request, genre, nom, parametres, cellules):
    """Crée la tâche du gros export et renvoie à Mes exports, où le fichier attend la personne."""
    try:
        EAP.creer(request.user, genre, nom, parametres, cellules)
        messages.info(request, libelle("suivi.echanges.msg.export_fond", nom=nom))
    except EAP.DejaEnCours as e:
        messages.error(request, libelle("suivi.echanges.msg.export_fond_deja", nom=e.tache.titre_affiche))
    return redirect(reverse("collecte:echanges") + "#exports-fond")


def _avertir_selection(request, export, p):
    """Un export partagé qui utilise une liste de KPI personnelle : les autres ne la voient pas."""
    s = p.selection_kpi()
    if export.partage and s is not None and not s.partage:
        messages.warning(request, libelle("suivi.echanges.msg.liste_personnelle", liste=s))


@login_required
@require_POST
def resume_export(request):
    """Constructeur d'export : la phrase qui résume les réglages et, sur demande, l'aperçu des 10 premières lignes."""
    p = E.Parametres.depuis(request.POST)
    reponse = {"phrase": p.phrase() if p.annees() else libelle("suivi.echanges.msg.exercice_requis")}
    if request.POST.get("apercu") == "1" and p.annees():
        entetes, lignes, total = E.apercu(request.user, p)
        reponse["apercu"] = {"entetes": [str(e) for e in entetes], "lignes": lignes, "total": total,
                             "gros": p.format == "xlsx" and total > E.SEUIL_GROS_EXPORT,  # conseiller le CSV (5 fois plus rapide)
                             # tableau en Excel : l'aperçu montre les données, le fichier les dispose autrement (onglets)
                             "note": libelle("suivi.echanges.export.apercu_tableau_note")
                             if p.presentation == "tableau" and p.format == "xlsx" else ""}
    return JsonResponse(reponse)


# ---------------------------------------------------------------- choix des KPI (export, fichier à remplir) et listes sauvegardées
def _kpis_choisissables(utilisateur):
    """KPI proposés : tout le catalogue actif pour l'admin, sinon les KPI de ses cases."""
    if utilisateur.est_admin:
        return list(KPI.objects.filter(actif=True))
    return list({k.code: k for k, _ in S.cellules(utilisateur)}.values())


def _choix_kpi(utilisateur, selection="", kpis=(), themes=(), referentiel=""):
    """Contexte du choix des KPI : « Tous les KPI », « Une liste sauvegardée » (SelectionKPI) ou « Choisir les KPI » (cases
    par thème, recherche, « Sauvegarder cette liste »). Un ancien filtre par thème s'affiche en KPI cochés."""
    listes = list(SelectionKPI.visibles(utilisateur).select_related("proprietaire").prefetch_related("kpis").order_by("nom"))
    for x in listes:
        x.codes = " ".join(sorted(k.code for k in x.kpis.all()))
        x.nb = len(x.codes.split()) if x.codes else 0
        x.modifiable = x.modifiable_par(utilisateur)
    proposes = _kpis_choisissables(utilisateur)
    choisis = set(kpis)
    if themes and not choisis:
        plan_ref = Plan(referentiel or None)
        choisis = {k.code for k in proposes
                   if (r := plan_ref.theme_racine(k.code)) is not None and str(r.pk) in set(themes)}
    plan = Plan()
    groupes = {}
    for k in sorted(proposes, key=lambda k: plan.position(k.code, k.ordre)):
        k.refs = " ".join(plan.appartenances.get(k.code, []))
        groupes.setdefault(plan.titres(k.code)[0] or libelle("suivi.echanges.kpi.hors_referentiel"), []).append(k)
    mode = "choix" if choisis else "liste" if selection and any(str(x.pk) == str(selection) for x in listes) else "tous"
    return {"listes": listes, "groupes": list(groupes.items()), "choisis": choisis, "mode": mode,
            "selection": str(selection or ""), "nb_proposes": len(proposes)}


@login_required
@require_POST
def listes_kpi(request):
    """Listes de KPI sauvegardées (choix des KPI) : « Sauvegarder cette liste » (crée, ou met à jour la liste de même nom de la
    personne) et « Supprimer la liste ». Réponse JSON."""
    if request.POST.get("action") == "supprimer":
        s = get_object_or_404(SelectionKPI.visibles(request.user), pk=identifiant(request.POST.get("id")))
        if not s.modifiable_par(request.user):
            raise PermissionDenied(libelle("suivi.echanges.msg.liste_partagee_supprime"))
        offre = CB.supprimer(request, s)  # corbeille : « Annuler » remet la liste en place
        return JsonResponse({"ok": True, "message": offre["texte"], "annulation": offre}, json_dumps_params={"ensure_ascii": False})
    nom = request.POST.get("nom", "").strip()[:100]
    permis = {k.code for k in _kpis_choisissables(request.user)}
    codes = sorted({c for c in request.POST.getlist("kpis") if c in permis})
    if not nom:
        return reponse_erreur(libelle("suivi.echanges.msg.liste_nom_requis"))
    if not codes:
        return reponse_erreur(libelle("suivi.echanges.msg.cocher_un_kpi"))
    s = (SelectionKPI.objects.filter(nom=nom, partage=True).first() if request.user.est_admin else None) \
        or SelectionKPI.objects.filter(nom=nom, proprietaire=request.user).first() \
        or SelectionKPI(nom=nom, proprietaire=request.user)
    if request.user.est_admin:
        s.partage = request.POST.get("partage") == "on"
    s.save()
    s.kpis.set(codes)
    n = len(codes)
    return JsonResponse({"ok": True, "id": s.pk, "nom": s.nom, "partage": s.partage, "kpis": codes,
                         "message": libelle("suivi.echanges.msg.liste_sauvegardee_partagee" if s.partage
                                            else "suivi.echanges.msg.liste_sauvegardee", nom=s.nom, n=n)})


@login_required
def page_listes(request):
    """Onglet « Listes de KPI » : les listes sauvegardées (les miennes et les partagées), les créer, les modifier, les
    supprimer, et s'en servir pour un export ou un fichier à remplir."""
    visibles = SelectionKPI.visibles(request.user)
    if request.method == "POST":
        if request.POST.get("action") == "supprimer":
            s = get_object_or_404(visibles, pk=identifiant(request.POST.get("id")))
            if not s.modifiable_par(request.user):
                raise PermissionDenied(libelle("suivi.echanges.msg.liste_partagee_supprime"))
            CB.supprimer(request, s, en_session=True)  # sans question : « Supprimé : X. Annuler » sur la page suivante
            return redirect("collecte:echanges_listes_page")
        pk = request.POST.get("id") or ""
        s = get_object_or_404(visibles, pk=pk) if pk else SelectionKPI(proprietaire=request.user)
        if pk and not s.modifiable_par(request.user):
            raise PermissionDenied(libelle("suivi.echanges.msg.liste_partagee_modifie"))
        nom = request.POST.get("nom", "").strip()[:100]
        permis = {k.code for k in _kpis_choisissables(request.user)}
        codes = sorted({c for c in request.POST.getlist("kpis") if c in permis})
        partage = request.POST.get("partage") == "on" if request.user.est_admin else s.partage
        homonyme = SelectionKPI.objects.filter(nom=nom).exclude(pk=s.pk).filter(
            Q(partage=True) if partage else Q(proprietaire=request.user, partage=False)).exists()
        # l'erreur s'affiche sous le champ concerné : le nom, ou la liste des KPI
        erreur_nom = (libelle("suivi.echanges.msg.liste_nom_requis") if not nom
                      else libelle("suivi.echanges.msg.liste_existe", nom=nom) if homonyme else "")
        erreur_kpi = "" if erreur_nom or codes else libelle("suivi.echanges.msg.cocher_un_kpi")
        erreur = erreur_nom or erreur_kpi
        if not erreur:
            s.nom, s.description, s.partage = nom, request.POST.get("description", "").strip()[:200], partage
            s.save()
            s.kpis.set(codes)
            messages.success(request, libelle("suivi.echanges.msg.liste_sauvegardee_partagee" if s.partage
                                              else "suivi.echanges.msg.liste_sauvegardee", nom=s.nom, n=len(codes)))
            return redirect("collecte:echanges_listes_page")
        edition = {"id": pk, "nom": nom, "description": request.POST.get("description", ""), "partage": partage,
                   "erreur_nom": erreur_nom, "erreur_kpi": erreur_kpi}
        ck = _choix_kpi(request.user, kpis=codes)
    else:
        pk = request.GET.get("liste", "")
        s = get_object_or_404(visibles, pk=pk) if pk.isdecimal() else None
        if s is not None and not s.modifiable_par(request.user):
            s = None
        edition = None
        if s is not None:
            edition = {"id": s.pk, "nom": s.nom, "description": s.description, "partage": s.partage}
        elif request.GET.get("nouvelle"):
            edition = {"id": "", "nom": "", "description": "", "partage": False}
        ck = _choix_kpi(request.user, kpis=[k.code for k in s.kpis.all()] if s is not None else ())
    # après une erreur aussi : sinon la liste des KPI à cocher disparaît
    ck["mode"] = "choix"
    listes = ck["listes"]  # nom et description seulement : ni nombre ni noms des KPI 
    return render(request, "collecte/echanges/listes.html", {
        "page": "echanges", "rubrique": "listes", "listes": listes, "edition": edition, "ck": ck})


@login_required
@require_POST
def ordre_modeles(request):
    """Nouvel ordre de la liste des exports enregistrés (glisser-déposer, admin). Corps JSON : {ids: [...]}."""
    exiger_admin(request)
    ids = [int(i) for i in (corps_json(request).get("ids") or []) if str(i).isdecimal()]
    for rang, pk in enumerate(ids, start=1):
        ReglageExport.objects.filter(pk=pk).update(ordre=rang)
    return JsonResponse({"ok": True, "message": libelle("suivi.echanges.msg.ordre_maj")})


@login_required
@require_POST
def supprimer_reglage(request, pk):
    r = get_object_or_404(ReglageExport, pk=pk)
    if not _modifiable(request.user, r):
        raise PermissionDenied(libelle("suivi.echanges.msg.export_suppression_admin" if r.partage
                                       else "suivi.echanges.msg.export_suppression_auteur"))
    CB.supprimer(request, r, en_session=True)  # sans question : « Supprimé : X. Annuler » sur la page suivante
    return redirect("collecte:echanges")


@login_required
@require_POST
def restaurer_modeles(request):
    """Recrée les exports fournis avec l'outil qui ont été supprimés."""
    exiger_admin(request)
    n = E.creer_modeles_fournis()
    messages.success(request, libelle("suivi.echanges.msg.exports_recrees", n=n))
    return redirect("collecte:echanges")


# ---------------------------------------------------------------- fichiers déposés (aperçu, puis confirmation)
def deposer_fichier(request, cle):
    """Garde le fichier le temps de l'aperçu ; renvoie (chemin, message d'erreur)."""
    f = request.FILES.get("fichier")
    if not f:
        return None, libelle("suivi.echanges.msg.choisir_fichier")
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in EXTENSIONS:
        return None, libelle("suivi.fichier.erreur.formats")
    if f.size > X.TAILLE_MAX:
        return None, libelle("suivi.fichier.erreur.trop_gros", mo=X.mo(X.TAILLE_MAX))
    oublier_fichier(request, cle)
    _purger()
    chemin = default_storage.save(f"{IMPORTS}/{uuid.uuid4().hex}{ext}", f)
    request.session[cle] = {"chemin": chemin, "nom": f.name}
    return chemin, ""


def _purger():
    """Supprime les fichiers d'aperçu abandonnés (ni confirmés ni annulés) depuis plus d'un jour."""
    if not default_storage.exists(IMPORTS):
        return
    limite = timezone.now() - datetime.timedelta(days=1)
    utilises = AP.fichiers_utilises()  # imports en arrière-plan en attente ou en cours : fichier gardé jusqu'à la fin
    for nom in default_storage.listdir(IMPORTS)[1]:
        if f"{IMPORTS}/{nom}" not in utilises and default_storage.get_modified_time(f"{IMPORTS}/{nom}") < limite:
            default_storage.delete(f"{IMPORTS}/{nom}")


def ouvrir_fichier(chemin):
    f = default_storage.open(chemin, "rb")
    f.name = chemin
    return f


def oublier_fichier(request, cle):
    info = request.session.pop(cle, None)
    if info and default_storage.exists(info["chemin"]):
        default_storage.delete(info["chemin"])
    if info and default_storage.exists(info["chemin"] + LU):
        default_storage.delete(info["chemin"] + LU)


# Lecture gardée d'un fichier déposé (reprise) : relire un gros classeur prend plusieurs secondes, à
# chaque page de l'assistant. La première lecture est rangée à côté du fichier (même nom + « .lu »), purgée avec lui.
LU = ".lu"


class _LectureSure(pickle.Unpickler):
    """Ne relit que des valeurs de cellule : textes, nombres, dates. Aucune autre classe n'est acceptée."""

    def find_class(self, module, name):
        if module == "datetime" and name in ("datetime", "date", "time", "timedelta"):
            return getattr(datetime, name)
        raise pickle.UnpicklingError(f"{module}.{name}")


def lecture_gardee(chemin):
    """{onglet: lignes} gardé pour ce fichier, ou None."""
    if not default_storage.exists(chemin + LU):
        return None
    try:
        with default_storage.open(chemin + LU, "rb") as f:
            return _LectureSure(f).load()
    except Exception:  # fichier abîmé ou d'une autre version : relu depuis l'original
        return None


def garder_lecture(chemin, onglets):
    from django.core.files.base import ContentFile

    try:
        if default_storage.exists(chemin + LU):
            default_storage.delete(chemin + LU)
        default_storage.save(chemin + LU, ContentFile(pickle.dumps(onglets, protocol=pickle.HIGHEST_PROTOCOL)))
    except Exception:  # valeur que la lecture sûre ne sait pas ranger, disque plein : sans conséquence, le fichier est relu
        pass


# ---------------------------------------------------------------- importer des valeurs
TOUS = I.TOUS  # « Référentiel : tous mes référentiels en cours » du fichier à remplir

@login_required
def importer(request):
    campagne = campagne_affichee(request)
    ctx = {"page": "echanges", "rubrique": "importer", "campagne": campagne, "groupes_campagnes": groupes_campagnes(request.user),
           "orgs": [o for o, *_ in S.organisations_visibles(request.user, campagne)] if campagne else [],
           "ck": _choix_kpi(request.user, request.GET.get("selection", "")), "reprise": request.GET.get("reprise") == "1",
           "plusieurs_en_cours": len(I.campagnes_en_cours_de(request.user)) > 1}
    cle = "import_valeurs"
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "annuler":
            oublier_fichier(request, cle)
            return redirect("collecte:echanges_importer")
        options = {"campagne_defaut": int(request.POST["campagne"]) if request.POST.get("campagne", "").isdecimal() else None,
                   "creer_campagnes": request.user.est_admin and request.POST.get("creer_campagnes") == "on"}
        if action == "verifier":
            chemin, erreur = deposer_fichier(request, cle)
            if erreur:
                messages.error(request, erreur)
                return redirect("collecte:echanges_importer")
            request.session[cle] |= {**options, "valider": request.POST.get("valider") == "on", "corrections": {},
                                     "apercu_le": timezone.now().isoformat()}  # rien d'écrasé de ce qui change après
            with ouvrir_fichier(chemin) as f:
                ctx["analyse"] = I.analyser(request.user, f, **options)
            # lignes de KPI calculés montrées « à forcer » : seules celles-là pourront l'être, après confirmation
            request.session[cle] = request.session[cle] | {"lignes": len(ctx["analyse"].lignes),
                                                           "a_forcer": [l.cle for l in ctx["analyse"].a_forcer]}
            ctx["ecarts"] = I.signaler_ecarts(ctx["analyse"])
            ctx["ecarts_seuils"] = ", ".join(avec_pourcent(x) for x in ctx["ecarts"][1])
            _garder_rejets(request, ctx["analyse"])
            ctx["info"] = request.session[cle]
        elif action == "corriger":  # lignes rejetées corrigées dans l'aperçu : nouvelle analyse, rien n'est enregistré
            info = request.session.get(cle)
            if not info or not default_storage.exists(info["chemin"]):
                messages.error(request, libelle("suivi.echanges.msg.fichier_expire"))
                return redirect("collecte:echanges_importer")
            corrections = dict(info.get("corrections") or {})
            for i in range(min(identifiant(request.POST.get("nb_rejets")), 500)):
                ligne = request.POST.get(f"cle_{i}", "")
                if not ligne:
                    continue
                corrections[ligne] = {champ: request.POST.get(f"{champ}_{i}", "").strip()
                                      for champ in ("kpi", "organisation", "periode", "valeur", "commentaire")}
                corrections[ligne]["na"] = "Oui" if request.POST.get(f"na_{i}") == "on" else ""
            info["corrections"] = corrections
            info["apercu_le"] = timezone.now().isoformat()  # le nouvel aperçu montre les valeurs d'aujourd'hui
            request.session[cle] = info
            with ouvrir_fichier(info["chemin"]) as f:
                ctx["analyse"] = I.analyser(request.user, f, info.get("campagne_defaut"), info.get("creer_campagnes", False),
                                            corrections=corrections)
            info["lignes"] = len(ctx["analyse"].lignes)
            info["a_forcer"] = [l.cle for l in ctx["analyse"].a_forcer]
            request.session[cle] = info
            ctx["ecarts"] = I.signaler_ecarts(ctx["analyse"])
            ctx["ecarts_seuils"] = ", ".join(avec_pourcent(x) for x in ctx["ecarts"][1])
            _garder_rejets(request, ctx["analyse"])
            ctx["info"] = info
            ctx["apres_correction"] = True
        elif action == "confirmer":
            info = request.session.get(cle)
            if not info or not default_storage.exists(info["chemin"]):
                messages.error(request, libelle("suivi.echanges.msg.fichier_expire"))
                return redirect("collecte:echanges_importer")
            # « Forcer ces valeurs » choisi dans l'aperçu : seules les lignes montrées à forcer ; sans ce choix, aucune
            info["forcer"] = list(info.get("a_forcer") or []) if request.POST.get("forcer") == "oui" else []
            request.session[cle] = info
            deja = AP.active_de(request.user)
            if deja is not None:  # un import à la fois par personne : l'aperçu reste, à confirmer quand le premier est fini
                messages.error(request, libelle("suivi.echanges.importer.fond.deja", nom=deja.nom_fichier))
                return redirect(f"{reverse('collecte:echanges_importer')}?tache={deja.pk}")
            if AP.en_arriere_plan(info.get("lignes") or 0):  # gros fichier : tâche en arrière-plan, la page peut être quittée
                try:
                    t = AP.creer(request.user, info, info["lignes"])
                except AP.DejaEnCours as e:
                    messages.error(request, libelle("suivi.echanges.importer.fond.deja", nom=e.tache.nom_fichier))
                    return redirect(f"{reverse('collecte:echanges_importer')}?tache={e.tache.pk}")
                request.session.pop(cle, None)  # le fichier reste : la tâche le lit, puis l'efface
                return redirect(f"{reverse('collecte:echanges_importer')}?tache={t.pk}")
            with ouvrir_fichier(info["chemin"]) as f:
                analyse, n, avertissements = I.appliquer(request.user, f, info["nom"], info.get("campagne_defaut"),
                                                         info.get("creer_campagnes", False), info.get("valider", False),
                                                         corrections=info.get("corrections") or None,
                                                         vu_le=_date_apercu(info), par_paquets=True, forcer=info["forcer"])
            oublier_fichier(request, cle)
            _garder_rejets(request, analyse)
            ctx.update(resultat=True, analyse=analyse, ecrites=n, avertissements=avertissements, info=info, **_etat_importees(request, analyse))
        elif action == "valider_import":  # « Valider ces N valeurs » après l'import : mêmes contrôles que la Saisie
            valider = request.session.pop("a_valider_import", [])
            campagnes = {c.pk: c for c in Campagne.objects.filter(pk__in={x[0] for x in valider})}
            kpis = {k.code: k for k in KPI.objects.filter(code__in={x[1] for x in valider})}
            orgs = {o.pk: o for o in Organisation.objects.filter(pk__in={x[2] for x in valider})}
            validees, gardees = 0, []
            for c_id, code, org_id in valider:
                c, k, o = campagnes.get(c_id), kpis.get(code), orgs.get(org_id)
                if c is None or k is None or o is None:
                    continue
                try:
                    S.valider(request.user, c, k, o)
                    validees += 1
                except (ValidationError, PermissionDenied) as e:
                    gardees.append(I.point_a_completer(c, k, o, " ".join(getattr(e, "messages", [str(e)]))))
            ctx.update(validation=True, validees=validees, gardees=gardees)
    else:
        t = _tache_a_montrer(request)
        if t is not None:
            ctx.update(_contexte_tache(request, t))
    ctx["nb_rejets"] = len(request.session.get("rejets_import", {}).get("lignes", [])) if "analyse" in ctx else 0
    if ctx.get("tache_resultat"):
        ctx["nb_rejets"] = len(ctx["tache"].resultat.get("rejets") or [])
    if "analyse" in ctx and not ctx.get("resultat"):
        ctx["seuil_arriere_plan"] = I.nombre_affiche(AP.seuil(), 0) if AP.en_arriere_plan(len(ctx["analyse"].lignes)) else ""
        ctx["rejets"] = request.session.get("rejets_import", {}).get("lignes", [])[:200]
        ctx["codes_kpi"] = list(KPI.objects.filter(actif=True).values_list("code", flat=True))
        ctx["noms_orgs"] = [o.nom for o in ctx["orgs"]] or list(Organisation.objects.filter(actif=True).values_list("nom", flat=True))
    return render(request, "collecte/echanges/importer.html", ctx)


# ---------------------------------------------------------------- imports en arrière-plan
def _tache_a_montrer(request):
    """Tâche à montrer sur la page d'import : celle de l'adresse (?tache=, la sienne seulement), sinon l'import en cours
    de la personne, sinon son dernier import fini dont elle n'a pas encore vu le résultat."""
    pk = identifiant(request.GET.get("tache"))
    t = TacheImport.objects.filter(pk=pk, utilisateur=request.user).first() if pk else None
    return t or AP.active_de(request.user) or AP.a_montrer(request.user)


def _avancement(t):
    """Texte de l'avancement : « Écriture : 34 000 / 100 000 lignes »."""
    n = lambda v: I.nombre_affiche(v, 0)  # noqa: E731
    if t.statut == TacheImport.Statut.ATTENTE:
        avant = TacheImport.objects.filter(statut__in=TacheImport.ACTIVES, cree_le__lt=t.cree_le).count()
        return libelle("suivi.echanges.importer.fond.attente", n=avant) if avant else libelle("suivi.echanges.importer.fond.demarrage")
    if t.arret_demande:
        return libelle("suivi.echanges.importer.fond.arret_demande", n=n(t.faites), total=n(t.total))
    if t.etape == "ecriture":
        return libelle("suivi.echanges.importer.fond.ecriture", n=n(t.faites), total=n(t.total))
    return libelle("suivi.echanges.importer.fond.lecture", n=n(t.lues), total=n(t.lignes))


def _surveiller(t):
    """Une tâche active : serveur redémarré (reprise ou « interrompu », jamais « en cours » pour toujours), et si elle
    attend sans planificateur, un fil de ce processus la prend."""
    if t.active:
        AP.entretien()
        if TacheImport.objects.filter(pk=t.pk, statut=TacheImport.Statut.ATTENTE).exists():
            AP.lancer()
        t.refresh_from_db()
    return t


def _contexte_tache(request, t):
    """Page d'import pendant (barre d'avancement) ou après (résultat, comme un import fait dans la page) un import en
    arrière-plan. Le résultat vu, la tâche ne revient plus d'elle-même sur la page (elle reste à ?tache=)."""
    if _surveiller(t).active:
        return {"tache": t, "tache_active": True, "avancement": _avancement(t)}
    r = t.resultat or {}
    if not t.vu:
        TacheImport.objects.filter(pk=t.pk).update(vu=True)
    ctx = {"tache": t, "info": {"nom": t.nom_fichier}}
    if "comptes" not in r:  # arrêtée avant le début, interrompue, échec : rien d'autre à montrer
        return ctx | {"tache_probleme": True}
    request.session["rejets_import"] = {"nom": t.nom_fichier, "lignes": r.get("rejets") or []}
    request.session["a_valider_import"] = r.get("validables") or []
    return ctx | {"resultat": True, "tache_resultat": True, "analyse": True, "ecrites": t.ecrites,
                  "avertissements": r.get("avertissements") or [], "nb_avertissements": r.get("nb_avertissements", 0),
                  **{c: r.get(c, 0) for c in ("nb_brouillon", "nb_validables", "nb_validees", "nb_historique", "nb_forcees",
                                              "nb_non_forcees")},
                  "a_completer": r.get("a_completer") or []}


@login_required
def tache_etat(request, pk):
    """Avancement d'un import en arrière-plan (JSON, lu toutes les 3 s par la page d'import) : requête légère."""
    t = _surveiller(get_object_or_404(TacheImport, pk=pk, utilisateur=request.user))
    return JsonResponse({"statut": t.statut, "etape": t.etape, "lues": t.lues, "lignes": t.lignes, "faites": t.faites,
                         "total": t.total, "pct": t.pourcentage, "texte": _avancement(t) if t.active else "",
                         "fini": not t.active, "arret_demande": t.arret_demande,
                         "url": f"{reverse('collecte:echanges_importer')}?tache={t.pk}"})


@login_required
@require_POST
def tache_arreter(request, pk):
    """« Arrêter » : tout de suite si l'import n'a pas commencé, sinon à la fin du paquet en cours."""
    t = get_object_or_404(TacheImport, pk=pk, utilisateur=request.user)
    if t.active:
        AP.arreter(t)
    return redirect(f"{reverse('collecte:echanges_importer')}?tache={t.pk}")


def _date_apercu(info):
    """Date de l'aperçu gardée en session (None pour un aperçu d'avant cette version : pas de contrôle)."""
    try:
        return datetime.datetime.fromisoformat(info["apercu_le"])
    except (KeyError, TypeError, ValueError):
        return None


def _etat_importees(request, analyse):
    """Après l'import : combien de valeurs sont validées, combien restent en brouillon (à valider : gardées en session
    pour « Valider ces N valeurs »), combien sont allées dans l'historique (campagnes clôturées)."""
    etat = I.etat_importees(analyse)
    request.session["a_valider_import"] = etat.pop("validables")
    return etat


def _garder_rejets(request, analyse):
    """Garde en session les lignes rejetées du dernier aperçu (ou import), pour le rapport à télécharger."""
    info = request.session.get("import_valeurs") or {}
    request.session["rejets_import"] = {"nom": info.get("nom", ""), "lignes": I.lignes_rejetees(analyse, request.user)}


@login_required
def rejets(request):
    """Lignes rejetées du dernier fichier déposé, au format du fichier à remplir, avec le motif : à corriger puis réimporter."""
    r = request.session.get("rejets_import")
    if not r or not r["lignes"]:
        messages.info(request, libelle("suivi.echanges.msg.aucun_rejet"))
        return redirect("collecte:echanges_importer")
    return I.fichier_rejets(request.user, r["lignes"], r["nom"], "csv" if request.GET.get("format") == "csv" else "xlsx")


@login_required
def modele(request):
    """Fichier à remplir, pré-rempli avec les cases de la personne (ou vierge), éventuellement limité à une sélection de KPI.
    Au-delà du seuil des gros exports, il est fabriqué en arrière-plan et retrouvé dans Mes exports."""
    q = request.POST if request.method == "POST" else request.GET  # POST : beaucoup de KPI cochés
    if q.get("choix_kpi", "liste") == "choix" and not q.getlist("kpis"):
        messages.error(request, libelle("suivi.echanges.msg.cocher_un_kpi_ou_tous"))
        return redirect("collecte:echanges_importer")
    tous = q.get("ref") == TOUS and not q.get("vierge")
    campagne = None if tous else campagne_affichee(request, q.get("campagne"))
    try:
        if EAP.seuil():
            cellules = I.estimer_cellules(request.user, q, campagne)
            if EAP.en_arriere_plan(cellules):
                choix = {k: v for k, v in q.lists() if k != "csrfmiddlewaretoken"}
                nom = libelle("suivi.echanges.exports.fond.remplir_tous") if tous else \
                    libelle("suivi.echanges.exports.fond.remplir", campagne=campagne.nom_complet)
                return _demander_en_arriere_plan(request, EAP.G.REMPLIR, nom, {
                    "choix": choix, "campagne": campagne and campagne.pk,
                    "titre_compose": {"remplir": "tous" if tous else campagne.pk}}, cellules)
        reponse = I.fichier_a_remplir(request.user, q, campagne)
    except E.ExportTropGros as e:
        messages.error(request, str(e))
        return redirect("collecte:echanges_importer")
    return _rien_a_remplir(request) if reponse is None else reponse


def _change(comptes):
    """Un onglet de la configuration déposée crée, modifie, désactive ou rejette au moins une ligne."""
    return any(n for code, _, n in comptes if code != "inchange")


def _rien_a_remplir(request):
    """Plutôt qu'un fichier vide : tout est déjà validé pour ces choix."""
    messages.info(request, libelle("suivi.echanges.msg.rien_a_remplir"))
    return redirect("collecte:echanges_importer")


# ---------------------------------------------------------------- Administration › Fichiers de configuration (admin)
@login_required
def configuration(request):
    """Configuration en fichier : la sauvegarder, la mettre à jour en masse (aperçu), modèles pour démarrer, reprise."""
    exiger_admin(request)
    telecharger = request.GET.get("telecharger")
    if telecharger in ("xlsx", "csv", "vierge"):
        return C.exporter("csv" if telecharger == "csv" else "xlsx", vierge=telecharger == "vierge")
    ctx = {"page": "administration", "rubrique": "fichiers", "nb": {
        "kpi": KPI.objects.count(), "kpi_actifs": KPI.objects.filter(actif=True).count(), "orgs": Organisation.objects.count(),
        "alias": OrgAlias.objects.count(), "regles": RegleCoherence.objects.count()},
        "sauvegarde": SV.etat_automatique(), "nb_profils": ProfilReprise.objects.count()}
    cle = "import_configuration"
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "annuler":
            oublier_fichier(request, cle)
            return redirect("collecte:admin_fichiers")
        if action == "verifier":
            chemin, erreur = deposer_fichier(request, cle)
            if erreur:
                messages.error(request, erreur)
                return redirect("collecte:admin_fichiers")
            request.session[cle] |= {"desactiver": request.POST.get("desactiver_absents") == "on"}
            with ouvrir_fichier(chemin) as f:
                a = C.analyser(f, request.session[cle]["desactiver"])
            ctx.update(analyse=a, info=request.session[cle],
                       apercus=[(nom, comptes, a.apercu(nom)) for nom, comptes in a.resume if _change(comptes)],
                       inchanges=[nom for nom, comptes in a.resume if not _change(comptes)])
        elif action == "confirmer":
            info = request.session.get(cle)
            if not info or not default_storage.exists(info["chemin"]):
                messages.error(request, libelle("suivi.echanges.msg.fichier_expire"))
                return redirect("collecte:admin_fichiers")
            with ouvrir_fichier(info["chemin"]) as f:
                analyse, n, exercices = C.appliquer(request.user, f, info["nom"], info.get("desactiver", False))
            oublier_fichier(request, cle)
            if analyse.erreur or analyse.nb_rejets:  # tout ou rien : l'aperçu, avec les lignes à corriger, rien d'enregistré
                ctx.update(analyse=analyse, info=info,
                           apercus=[(nom, comptes, analyse.apercu(nom)) for nom, comptes in analyse.resume if _change(comptes)],
                           inchanges=[nom for nom, comptes in analyse.resume if not _change(comptes)])
            else:
                ctx.update(resultat=True, analyse=analyse, ecrites=n, exercices=exercices, info=info)
    return render(request, "collecte/administration/fichiers.html", ctx)


# ---------------------------------------------------------------- gros exports en arrière-plan (Mes exports)
def _tache_export(request, pk):
    """La tâche de la personne (jamais celle d'une autre : 404), dans l'espace courant."""
    return get_object_or_404(TacheExport, pk=pk, utilisateur=request.user)


@login_required
@require_GET
def export_etat(request, pk):
    """État d'un gros export (JSON, lu toutes les 3 s par Mes exports) : fini ou non, et la ligne à afficher."""
    t = _tache_export(request, pk)
    if t.active:
        EAP.entretien()
        if TacheExport.objects.filter(pk=t.pk, statut=TacheExport.Statut.ATTENTE).exists():
            EAP.lancer()
        t.refresh_from_db()
    fini = not t.active
    if fini:
        EAP.marquer_vues([t])
    annonce = "" if not fini else libelle("suivi.echanges.exports.fond.annonce_pret", nom=t.titre_affiche) \
        if t.statut == TacheExport.Statut.PRET else libelle("suivi.echanges.exports.fond.annonce_fin", nom=t.titre_affiche)
    html = render(request, "collecte/echanges/_export_fond.html", {"t": t}).content.decode()
    return JsonResponse({"statut": t.statut, "fini": fini, "html": html, "annonce": annonce})


@login_required
@require_GET
def export_fichier(request, pk):
    """Télécharger un gros export : la personne qui l'a demandé, pendant sa durée de conservation, avec les droits et le
    périmètre de la demande (relus par les fonctions de la page) ; sinon le fichier est supprimé sans être donné."""
    from django.http import FileResponse

    t = _tache_export(request, pk)
    # droits changés : leur message, aussi pour un lien gardé d'un fichier déjà retiré pour ce motif (B3), et avant
    # l'absence du fichier (jamais « gardés 7 jours » quand la vraie raison est le changement des droits)
    if (t.statut == TacheExport.Statut.PRET and not EAP.droits_inchanges(t, request.user)) \
            or (t.statut == TacheExport.Statut.EXPIRE and t.erreur == "droits"):
        EAP.expirer(t, "droits")
        messages.error(request, libelle("suivi.echanges.msg.export_fond_droits"))
        return redirect("collecte:echanges")
    # fichier qui n'a pas suivi la base (restauration, copie des données) : la vraie raison, pas la durée de conservation
    if (t.statut == TacheExport.Statut.EXPIRE and t.erreur == EAP.FICHIER_ABSENT) or (
            t.statut == TacheExport.Statut.PRET and not (t.expire_le and t.expire_le <= timezone.now())
            and not default_storage.exists(t.chemin)):
        EAP.expirer(t, EAP.FICHIER_ABSENT)
        messages.error(request, libelle("suivi.echanges.msg.export_fond_absent"))
        return redirect("collecte:echanges")
    if t.statut != TacheExport.Statut.PRET or (t.expire_le and t.expire_le <= timezone.now()) \
            or not default_storage.exists(t.chemin):
        EAP.expirer(t)
        messages.error(request, libelle("suivi.echanges.msg.export_fond_expire", n=EAP.jours()))
        return redirect("collecte:echanges")
    if not EAP.droits_inchanges(t, request.user):
        EAP.expirer(t, "droits")
        messages.error(request, libelle("suivi.echanges.msg.export_fond_droits"))
        return redirect("collecte:echanges")
    TacheExport.objects.filter(pk=t.pk).update(telecharge_le=timezone.now())
    type_ = "text/csv; charset=utf-8" if t.nom_fichier.endswith(".csv") else \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    r = FileResponse(default_storage.open(t.chemin, "rb"), content_type=type_)
    r["Content-Disposition"] = f'attachment; filename="{t.nom_fichier}"'  # comme le téléchargement immédiat
    return r
