"""Visualisation v2 : points d'accès JSON internes à la page (session et protection CSRF ; pas une API publique) et
exports Excel. Les données passent toutes par ``collecte.visuels`` (périmètre de la personne).

Droits (§ 11 de la spécification) : chacun crée, modifie, renomme, duplique, ordonne et supprime ses vues
personnelles (lecteur et auditeur compris : ce sont des préférences) ; seul l'administrateur partage une vue, modifie ou
supprime une vue partagée, règle l'ordre des vues partagées pour tous et la vue d'accueil. Les changements des vues
partagées sont notés dans le Journal (« modifications d'administration »).

Périmètre : la définition d'une vue ne part vers la page que réduite à ce que la personne voit
(``definition_publique``) ; les réponses des envois ne la contiennent pas ; « Dupliquer » ne copie que ce qu'elle voit ;
« Enregistrer » garde tel quel ce que la page n'a pas reçu (``visuels.fusionner``)."""
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from parametres.models import NiveauHierarchique
from referentiel.models import KPI, Referentiel
from referentiel.plans import Plan

from . import visuels as VS
from . import visuels_excel as VX
from .contexte import choix_reponse
from . import corbeille as CB
from .models import AccueilVisu, Journal, PreferenceVisu, SelectionKPI, VueVisu
from .reponses_script import reponse_erreur
from .vues_communes import corps_envoye
from espaces import contexte as ESP


# ---------------------------------------------------------------- outils
def reponse(donnees, statut=200):
    return JsonResponse(donnees, status=statut, json_dumps_params={"ensure_ascii": False}, safe=False)


def erreurs(liste, statut=400):
    if isinstance(liste, str):
        liste = [{"visuel": "", "message": liste}]
    return reponse_erreur(liste[0]["message"] if liste else "", status=statut, erreurs=liste)  # « erreurs » : une par visuel


def refus():
    return erreurs(VS.lib("visu.erreur.droits"), 403)


def campagne_choisie(request):
    return choix_reponse(request).get("campagne_choisie")


def lire(request):
    """Corps JSON d'un envoi (200 Ko au plus) ; (données, réponse d'erreur)."""
    corps = corps_envoye(request)
    if corps is None:  # formulaire au lieu de JSON
        return None, erreurs(VS.lib("visu.vue.json_invalide"))
    d, e = VS.lire_json(corps)
    if e:
        return None, erreurs(e, 413 if len(corps or b"") > VS.TAILLE_MAX else 400)
    if not isinstance(d, dict):
        return None, erreurs(VS.lib("visu.vue.json_invalide"))
    return d, None


def vue_visible(request, pk):
    return get_object_or_404(VueVisu.visibles(request.user), pk=pk)


def preference(utilisateur, creer=False):
    p = PreferenceVisu.objects.filter(utilisateur=utilisateur).first()
    if p is None and creer:
        p = PreferenceVisu.objects.create(utilisateur=utilisateur)
    return p


def vues_ordonnees(utilisateur, pref=None):
    """Vues visibles dans l'ordre des onglets de la personne : son ordre à elle, puis les autres (partagées d'abord,
    dans l'ordre réglé par l'admin, puis par nom)."""
    vues = list(VueVisu.visibles(utilisateur).select_related("proprietaire"))
    pref = pref if pref is not None else preference(utilisateur)
    rang = {pk: i for i, pk in enumerate(pref.ordre if pref else [])}
    return sorted(vues, key=lambda v: (rang.get(v.pk, len(rang)), not v.partage, v.ordre, v.nom.lower(), v.pk))


def vue_json(v, utilisateur, pref=None, accueils=None):
    """Une vue sans sa définition : la définition ne part vers la page qu'à travers ``definition_publique`` (rien de hors
    du périmètre de la personne). ``accueil`` : rôles dont elle est la vue d'accueil (``accueils`` : {vue: [rôles]})."""
    accueils = accueils if accueils is not None else accueils_par_vue()
    return {"id": v.pk, "nom": v.nom, "description": v.description, "partage": v.partage, "accueil": accueils.get(v.pk, []),
            "modifiable": v.modifiable_par(utilisateur), "personnelle": v.proprietaire_id == utilisateur.id and not v.partage,
            "version": v.version, "defaut": bool(pref and pref.vue_defaut_id == v.pk),
            "url": reverse("collecte:visu_vue", args=[v.pk])}


# ---------------------------------------------------------------- vues d'accueil par rôle
def accueils_par_vue():
    """{id de vue : [rôles dont elle est la vue d'accueil]}, dans l'ordre des rôles."""
    sortie = {}
    for role, vue_id in sorted(AccueilVisu.objects.filter(vue__supprime_le__isnull=True).values_list("role", "vue_id"),
                               key=lambda x: _rang_role(x[0])):
        sortie.setdefault(vue_id, []).append(role)
    return sortie


def _rang_role(role):
    return AccueilVisu.ROLES.index(role) if role in AccueilVisu.ROLES else len(AccueilVisu.ROLES)


def nom_role(role):
    return VS.lib(f"visu.role.{role}")


def definir_accueil(utilisateur, role, vue):
    """La vue d'accueil du rôle devient ``vue`` (partagée), ou aucune (None) ; noté dans le Journal. Vrai si changé."""
    actuelle = AccueilVisu.objects.select_related("vue").filter(role=role, vue__supprime_le__isnull=True).first()  # corbeille : gardée pour « Annuler »
    if (actuelle.vue_id if actuelle else None) == (vue.pk if vue else None):
        return False
    champ = f"{VS.lib('visu.journal.accueil')} ({nom_role(role)})"[:60]
    avant = actuelle.vue.nom if actuelle else ""
    if vue is None:
        actuelle.delete()
        Journal.ecrire(utilisateur, "vue_partagee", actuelle.vue, champ, avant, "")
    else:
        AccueilVisu.objects.update_or_create(role=role, defaults={"vue": vue})
        Journal.ecrire(utilisateur, "vue_partagee", vue, champ, avant, vue.nom)
    return True


def regler_accueil(utilisateur, vue, roles):
    """``vue`` devient la vue d'accueil des ``roles`` (une seule par rôle : elle remplace la précédente) et cesse de
    l'être pour les autres rôles. Chaque changement est noté dans le Journal."""
    with ESP.atomic():
        for role in AccueilVisu.ROLES:
            if role in roles:
                definir_accueil(utilisateur, role, vue)
            elif AccueilVisu.objects.filter(role=role, vue=vue).exists():
                definir_accueil(utilisateur, role, None)


def message_accueil(vue):
    roles = AccueilVisu.roles_de(vue)
    if not roles:
        return VS.lib("visu.vue.accueil_aucun", nom=vue.nom)
    return VS.lib("visu.vue.accueil_ok", nom=vue.nom, roles=", ".join(nom_role(r) for r in sorted(roles, key=_rang_role)))


def definition_publique(v, utilisateur, d, perim):
    """Définition d'une vue enregistrée telle que la page la reçoit (``d`` : ses données, calculées pour la personne) :
    les visuels qu'elle voit, sans KPI ni organisation hors de son périmètre ; combien d'autres ne la concernent pas ;
    les empreintes opaques de ce qui est gardé à l'enregistrement (``garde``)."""
    caches = {i for i, x in enumerate(v.visuels or []) if isinstance(x, dict) and x.get("id") not in d["visuels"]}
    return {"filtres": VS.filtres_publics(v.filtres, perim), "visuels": [d["visuels"][i]["definition"] for i in d["ordre"]],
            "masques": d["etat"]["masques"], "garde": VS.garde(v.filtres, v.visuels, utilisateur, perim, caches)}


def verrou_vues(utilisateur):
    """Verrou de la ligne du propriétaire, à prendre dans la transaction avant de relire le nombre de ses vues
    personnelles et d'en ajouter une (création, duplication, restauration depuis la corbeille) : deux ajouts
    simultanés ne dépassent pas la limite. PostgreSQL : verrou de ligne ; SQLite : les
    transactions « immediate » sérialisent déjà les écritures."""
    from django.contrib.auth import get_user_model

    get_user_model().objects.select_for_update().filter(pk=utilisateur.pk).first()


def limite_vues(utilisateur):
    """Message si la personne a déjà autant de vues personnelles que permis (Paramètres › Visualisation ; les vues
    partagées ne comptent pas), sinon « ». Une personne déjà au-dessus garde ses vues : elle n'en crée plus. Avant un
    ajout, lu sous ``verrou_vues``."""
    from parametres.models import Instance

    maximum = Instance.courante().vues_personnelles_max
    if VueVisu.objects.filter(proprietaire=utilisateur, partage=False).count() >= maximum:
        return VS.lib("visu.vue.limite_perso", n=maximum)
    return ""


def journaliser(utilisateur, vue, champ, avant="", apres=""):
    """Journal des vues partagées seulement (les vues personnelles sont des préférences)."""
    Journal.ecrire(utilisateur, "vue_partagee", vue, VS.lib(f"visu.journal.{champ}"), avant, apres)


def sans_auto(propre, errs):
    """Une forme « auto » n'est jamais enregistrée : la page la fait résoudre par le serveur avant d'enregistrer."""
    for i, v in enumerate(propre.get("visuels") or [], start=1):
        if v.get("type") == "auto":
            errs.append({"visuel": v["id"], "message": VS.lib("visu.erreur.forme", n=i, type="auto")})
    return errs


def _codes(visuels):
    return {c for v in visuels or [] for c in v.get("kpis") or []}


# ---------------------------------------------------------------- catalogue (panneau des KPI)
@login_required
@require_GET
def catalogue(request):
    """KPI que la personne voit (code, nom traduit, unité, format, agrégation, rang de granularité, places dans les
    référentiels), arbres des thèmes, listes de KPI et autres visuels. Chargé à l'entrée en modification."""
    codes = VS.codes_visibles(request.user)
    plan = Plan()
    kpis = sorted(KPI.objects.filter(code__in=codes).select_related("granularite"), key=lambda k: plan.position(k.code, k.ordre))
    refs = list(Referentiel.objects.filter(actif=True).order_by("ordre", "code"))
    sortie_kpis, rediges = [], 0
    for k in kpis:
        if k.est_texte:  # réponse rédigée : ni chiffre ni graphique, pas proposée 
            rediges += 1
            continue
        places = [{"ref": r.code, "themes": [t.pk for t in chemin]} for r, chemin, _ in plan.places(k.code)]
        sortie_kpis.append({"code": k.code, "nom": k.nom, "unite": k.symbole, "format": k.format,
                            "agregation": k.methode_agregation, "rang": k.granularite.rang if k.granularite_id else None,
                            "niveau": k.granularite.tr("nom") if k.granularite_id else "", "places": places})
    arbres = []
    for r in refs:
        arbres.append({"code": r.code, "nom": str(r), "themes": [{"id": t.pk, "nom": t.tr("nom"), "prof": prof, "parent": t.parent_id}
                                                              for t, prof in plan.arbre(r)]})
    listes = [{"id": x.pk, "nom": x.nom, "partage": x.partage, "kpis": [c for c in x.kpis.values_list("code", flat=True) if c in codes]}
              for x in SelectionKPI.visibles(request.user).order_by("nom")]
    return reponse({"kpis": sortie_kpis, "rediges": rediges, "referentiels": arbres, "listes": listes,
                    "autres": [{"type": "remplissage", "nom": VS.lib("visu.type.remplissage")}]})


# ---------------------------------------------------------------- données
@login_required
@require_GET
def vue_donnees(request, pk):
    v = vue_visible(request, pk)
    return reponse(VS.donnees(request.user, v.filtres, v.visuels, request.GET, campagne_choisie(request)))


@login_required
@require_POST
def donnees(request):
    """Données d'une définition non enregistrée (aperçu en modification, vues automatiques) : ne fait que lire."""
    d, e = lire(request)
    if e:
        return e
    anciens = set()
    if str(d.get("vue") or "").isdecimal():
        v = VueVisu.visibles(request.user).filter(pk=d["vue"]).first()
        anciens = _codes(v.visuels) if v else set()
    propre, errs = VS.valider_vue({"nom": "-", "filtres": d.get("filtres") or {}, "visuels": d.get("visuels") or []},
                                  request.user, anciens)
    if errs:
        return erreurs(errs)
    parametres = d.get("parametres") if isinstance(d.get("parametres"), dict) else {}
    return reponse(VS.donnees(request.user, propre["filtres"], propre["visuels"], parametres, campagne_choisie(request)))


# ---------------------------------------------------------------- vues : créer, enregistrer, dupliquer, supprimer
@login_required
@require_POST
def vue_creer(request):
    d, e = lire(request)
    if e:
        return e
    propre, errs = VS.valider_vue(d, request.user)
    if sans_auto(propre, errs):
        return erreurs(errs)
    partage = bool(d.get("partage")) and request.user.est_admin and not request.user.lecture_seule
    with ESP.atomic():
        if not partage:  # compte relu sous verrou : deux créations simultanées ne dépassent pas la limite
            verrou_vues(request.user)
            if limite := limite_vues(request.user):
                return erreurs(limite)
        v = VueVisu.objects.create(proprietaire=request.user, partage=partage, **propre)
        if partage:
            journaliser(request.user, v, "creation", "", v.nom)
    return reponse({"vue": vue_json(v, request.user), "message": VS.lib("visu.vue.creee", nom=v.nom)}, 201)


@login_required
@require_POST
def vue_enregistrer(request, pk):
    v = vue_visible(request, pk)
    if not v.modifiable_par(request.user):
        return refus()
    d, e = lire(request)
    if e:
        return e
    if d.get("version") != v.version:
        return erreurs([{"visuel": "", "message": VS.lib("visu.vue.conflit")}], 409)
    # ce que la page n'a pas reçu (hors du périmètre de la personne) est gardé tel quel : d'après les empreintes
    # renvoyées par la page (« garde »), sinon d'après le périmètre d'aujourd'hui
    perim = VS.Perimetre(request.user)
    g = VS.lire_garde(d.get("garde"))
    g = set(VS.garde(v.filtres, v.visuels, request.user, perim)) if g is None else g
    propre, errs = VS.valider_vue(d, request.user, _codes(v.visuels), complet=False, plafond=VS.plafond_visuels(v),
                                  gardes=len(VS.non_recus(v.visuels, g)))
    if sans_auto(propre, errs):
        return erreurs(errs)
    with ESP.atomic():
        v = VueVisu.objects.select_for_update().get(pk=v.pk)
        if v.version != d.get("version"):
            return erreurs([{"visuel": "", "message": VS.lib("visu.vue.conflit")}], 409)
        if "visuels" in propre:
            propre["visuels"] = VS.fusionner(v.visuels, propre["visuels"], request.user, perim, g)
        if "filtres" in propre:
            propre["filtres"] = VS.fusionner_filtres(v.filtres, propre["filtres"], perim, g)
        avant = v.nom
        for cle, valeur in propre.items():
            setattr(v, cle, valeur)
        v.version += 1
        v.save()
        if v.partage:
            journaliser(request.user, v, "modification", avant, v.nom)
    return reponse({"vue": vue_json(v, request.user, preference(request.user)), "message": VS.lib("visu.vue.enregistree", nom=v.nom)})


@login_required
@require_POST
def vue_dupliquer(request, pk):
    """Copie personnelle, faite par le serveur à partir de la définition enregistrée : seulement ce que la personne voit
    (les visuels hors de son périmètre ne sont pas copiés, et le message le dit)."""
    v = vue_visible(request, pk)
    if limite := limite_vues(request.user):  # dit tout de suite, sans projeter la vue
        return erreurs(limite)
    perim = VS.Perimetre(request.user)
    visuels, retires = VS.projeter(v.visuels, request.user, perim)
    nom = VS.lib("visu.vue.copie_de", nom=v.nom)[:100]
    with ESP.atomic():
        verrou_vues(request.user)  # compte relu sous verrou, comme la création
        if limite := limite_vues(request.user):
            return erreurs(limite)
        copie = VueVisu.objects.create(nom=nom, description=v.description, proprietaire=request.user, partage=False,
                                       filtres=VS.filtres_publics(v.filtres, perim), visuels=visuels, schema=v.schema)
    message = VS.lib("visu.vue.dupliquee", nom=copie.nom)
    if retires:
        message += " " + VS.lib("visu.vue.dupliquee_sans", n=retires)
    return reponse({"vue": vue_json(copie, request.user), "message": message,
                    "url": reverse("collecte:visu_vue", args=[copie.pk]) + "?modifier=1"}, 201)


@login_required
@require_POST
def vue_supprimer(request, pk):
    v = vue_visible(request, pk)
    if not v.modifiable_par(request.user):
        return refus()
    # corbeille (collecte/corbeille.py) : la page suivante propose « Annuler » ; suppression notée au Journal
    offre = CB.supprimer(request, v, en_session=True)
    return reponse({"supprimee": pk, "message": offre["texte"], "annulation": offre, "url": reverse("collecte:visu")})


@login_required
@require_POST
def vue_partage(request, pk):
    """Partager avec tous, ou ne plus partager (administrateur, sur ses vues ou une vue déjà partagée)."""
    v = vue_visible(request, pk)
    if not request.user.est_admin or request.user.lecture_seule or not (v.partage or v.proprietaire_id == request.user.id):
        return refus()
    d, e = lire(request)
    if e:
        return e
    partage = bool(d.get("partage"))
    if partage != v.partage:
        v.partage = partage
        if not partage:
            regler_accueil(request.user, v, set())  # une vue personnelle n'est la vue d'accueil de personne
            if v.proprietaire_id is None:
                v.proprietaire = request.user
        v.version += 1
        v.save()
        journaliser(request.user, v, "partage", "non" if partage else "oui", "oui" if partage else "non")
    cle = "visu.vue.partagee_ok" if partage else "visu.vue.privee_ok"
    return reponse({"vue": vue_json(v, request.user), "message": VS.lib(cle, nom=v.nom)})


@login_required
@require_POST
def vues_ordre(request):
    """Ordre des onglets de la personne ; pour l'administrateur (``partagees``), aussi l'ordre des vues partagées pour tous."""
    d, e = lire(request)
    if e:
        return e
    ordre = d.get("ordre")
    if not isinstance(ordre, list) or len(ordre) > 500 or not all(type(i) is int for i in ordre):
        return erreurs(VS.lib("visu.vue.json_invalide"))
    visibles = set(VueVisu.visibles(request.user).values_list("pk", flat=True))
    ordre = [i for i in dict.fromkeys(ordre) if i in visibles]
    pref = preference(request.user, creer=True)
    pref.ordre = ordre
    pref.save(update_fields=["ordre"])
    if d.get("partagees") and request.user.est_admin and not request.user.lecture_seule:
        partagees = [i for i in ordre if VueVisu.objects.filter(pk=i, partage=True).exists()]
        for rang, pk in enumerate(partagees):
            VueVisu.objects.filter(pk=pk).update(ordre=rang)
    return reponse({"ordre": ordre, "message": VS.lib("visu.vue.ordre_ok")})


@login_required
@require_POST
def vue_preferee(request, pk):
    """Ma vue par défaut (``defaut``) ; pour l'administrateur et une vue partagée, les rôles dont elle est la vue d'accueil
    (``accueil`` : liste de rôles ; vrai : tous les rôles ; faux : aucun)."""
    v = vue_visible(request, pk)
    d, e = lire(request)
    if e:
        return e
    message = ""
    if "accueil" in d:
        if not request.user.est_admin or request.user.lecture_seule or not v.partage:
            return refus()
        roles = AccueilVisu.ROLES if d["accueil"] is True else [] if d["accueil"] in (False, None) else d["accueil"]
        if not isinstance(roles, list) or not all(r in AccueilVisu.ROLES for r in roles):
            return erreurs(VS.lib("visu.vue.json_invalide"))
        regler_accueil(request.user, v, set(roles))
        message = message_accueil(v)
    if "defaut" in d:
        pref = preference(request.user, creer=True)
        pref.vue_defaut = v if d["defaut"] else (None if pref.vue_defaut_id == v.pk else pref.vue_defaut)
        pref.save(update_fields=["vue_defaut"])
        message = VS.lib("visu.vue.defaut_ok", nom=v.nom) if d["defaut"] else message
    return reponse({"vue": vue_json(v, request.user, preference(request.user)), "message": message})


# ---------------------------------------------------------------- Excel
@login_required
@require_GET
def vue_excel(request, pk):
    v = vue_visible(request, pk)
    visuel = request.GET.get("visuel", "")
    visuels = [x for x in v.visuels if x.get("id") == visuel] if visuel else v.visuels
    if visuel and not visuels:
        raise Http404("Visuel inconnu.")
    d = VS.donnees(request.user, v.filtres, visuels, request.GET, campagne_choisie(request))
    if visuel and visuel not in d["visuels"]:
        raise Http404("Visuel inconnu.")  # hors du périmètre de la personne : comme s'il n'existait pas
    return VX.reponse(v.nom, d, [visuel] if visuel and isinstance(visuel, str) else None)


@login_required
@require_POST
def excel(request):
    """Excel d'une définition non enregistrée (vue automatique, aperçu) : ne fait que lire."""
    d, e = lire(request)
    if e:
        return e
    propre, errs = VS.valider_vue({"nom": d.get("nom") or VS.lib("visu.titre"), "filtres": d.get("filtres") or {},
                                   "visuels": d.get("visuels") or []}, request.user)
    if errs:
        return erreurs(errs)
    parametres = d.get("parametres") if isinstance(d.get("parametres"), dict) else {}
    donnees_ = VS.donnees(request.user, propre["filtres"], propre["visuels"], parametres, campagne_choisie(request))
    visuel = d.get("visuel")
    return VX.reponse(propre["nom"], donnees_, [visuel] if visuel and isinstance(visuel, str) else None)


# ---------------------------------------------------------------- page
def viz_claires():
    """Rangs des couleurs des graphiques réglées par l'admin à moins de 3:1 sur le fond des cartes (0 à 7 : séries,
    8 : « Autres ») ; vide avec la palette fournie."""
    from parametres import couleurs as CO
    from parametres.models import Instance

    i = Instance.courante()
    return CO.series_claires(i.couleurs_graphiques, i.gamme()["surface"])


def formes():
    return [{"code": c, "nom": VS.lib(f"visu.type.{c}"), "rendu": x["rendu"], "largeur": x["largeur"], "max": x["max"]}
            for c, x in VS.TYPES.items()]


def contexte_page(request, vue, d, ctx, auto=None, modifier=False):
    """Contexte de la page (passé au script en ``json_script``) : vues et droits, filtres, libellés, formes, adresses."""
    from parametres import libelles as LB

    from django.utils import timezone

    from . import dates_courtes as DC

    u = request.user
    pref = preference(u)
    vues = vues_ordonnees(u, pref)
    langue = LB.langue_effective()
    jour = timezone.localdate()
    accueils = accueils_par_vue()
    if vue is not None:
        v = {**vue_json(vue, u, pref, accueils), **definition_publique(vue, u, d, ctx.perim)}
    else:
        v = {"id": None, "nom": auto["nom"], "description": auto.get("description", ""), "partage": False, "accueil": [],
             "modifiable": False, "personnelle": False, "version": 0, "defaut": False, "url": request.get_full_path(),
             "auto": auto.get("genre", ""), "filtres": VS.filtres_publics(auto.get("filtres"), ctx.perim),
             "visuels": [d["visuels"][i]["definition"] for i in d["ordre"]], "masques": 0, "garde": []}
    plafond = VS.plafond_visuels(vue)
    admin = u.est_admin and not u.lecture_seule
    noms = {x.pk: x.nom for x in vues}
    par_role = {r: i for i, rs in accueils.items() for r in rs}
    return {
        "vue": v,
        "vues": [vue_json(x, u, pref, accueils) for x in vues],
        "droits": {"admin": admin, "lecture_seule": u.lecture_seule, "modifier": modifier,
                   "modifiable": bool(vue.modifiable_par(u)) if vue else True},
        # vues d'accueil par rôle (fenêtre « Vue d'accueil » de l'administrateur) : le rôle, son nom, sa vue d'accueil
        "roles": [{"code": r, "nom": nom_role(r), "vue": par_role.get(r), "vue_nom": noms.get(par_role.get(r), "")}
                  for r in AccueilVisu.ROLES] if admin else [],
        "tableaux_convertis": VueVisu.visibles(u).exclude(ancien_tableau=None).exists(),
        "niveaux": [{"code": n.code, "nom": n.tr("nom_pluriel"), "rang": n.rang} for n in NiveauHierarchique.objects.order_by("rang")],
        "urls_visuel": {"fiche": reverse("collecte:visu_kpi", args=["CODE"]).replace("CODE", "{code}")},
        "options": VS.options_filtres(ctx),
        "libelles": {**LB.libelles("visu.", langue), **LB.libelles("format.", langue)},
        "langue": langue,
        # date des images exportées : celle de l'installation (fuseau TIME_ZONE), en date courte de la langue, comme
        # l'Excel (``visuels_excel``) ; ni l'horloge ni le format du navigateur
        "aujourdhui": {"iso": jour.isoformat(), "texte": DC.date_courte(jour, langue)},
        "formes": formes(),
        "outil": str(getattr(request, "instance_nom", "") or ""),
        "urls": {
            "visu": reverse("collecte:visu"), "catalogue": reverse("collecte:visu_catalogue"),
            "donnees": reverse("collecte:visu_donnees"), "excel": reverse("collecte:visu_excel"),
            "creer": reverse("collecte:visu_vue_creer"), "ordre": reverse("collecte:visu_vues_ordre"),
            "vue": reverse("collecte:visu_vue", args=[0]).replace("/0/", "/{id}/"),
            "nouvelle": reverse("collecte:visu_vue_nouvelle"),
        },
        # couleurs des graphiques réglées par l'admin trop claires (sous 3:1) : leurs valeurs sont toujours écrites
        "viz_claires": viz_claires(),
        # visuels : ce que la page peut avoir (sans ceux qui ne concernent pas la personne, gardés à l'enregistrement) ;
        # plafond : toute la vue (une vue convertie d'un ancien tableau peut dépasser max_visuels)
        "limites": {"visuels": max(plafond - v["masques"], 0), "plafond": plafond, "max_visuels": VS.MAX_VISUELS,
                    "kpis": VS.MAX_KPIS_GRAPHIQUE, "lignes": VS.LIGNES_TABLEAU},
    }


def rendre_page(request, vue=None, auto=None, extra=None):
    """Page Visualisation : une vue enregistrée, ou une vue automatique (``auto`` : {"nom", "genre", "filtres",
    "visuels"}). Les données de la vue ouverte sont dans la page : l'arrivée ne coûte aucune requête de plus."""
    from django.shortcuts import render

    from parametres.contexte import version_css
    from parametres.models import Instance

    filtres = vue.filtres if vue else (auto.get("filtres") or {})
    visuels = vue.visuels if vue else auto.get("visuels") or []
    d, ctx = VS.donnees_et_contexte(request.user, filtres, visuels, request.GET, campagne_choisie(request))
    if auto and auto.get("filtrer"):  # vue automatique d'un KPI : seulement les formes compatibles
        d["ordre"] = [i for i in d["ordre"] if d["visuels"][i]["etat"] != "incompatible"]
    if auto and auto.get("avertissement"):  # nouvelle vue : plus de vue personnelle possible
        d["avertissements"].append(auto["avertissement"])
    nouvelle = vue is None and auto.get("genre") == "nouvelle"
    # une vue automatique se modifie comme un brouillon : « Enregistrer la vue » en fait une vue personnelle
    modifier = nouvelle or (request.GET.get("modifier") == "1" and (vue is None or vue.modifiable_par(request.user)))
    contexte = contexte_page(request, vue, d, ctx, auto, modifier)
    contexte["outil"] = Instance.courante().titre
    noscript = [d["visuels"][i] for i in d["ordre"]]
    return render(request, "collecte/visualisation/page.html", {
        "page": "visualisation", "contexte_visu": contexte, "donnees_visu": d, "vue": vue, "auto": auto,
        "noscript": noscript, "vues": contexte["vues"], "options": contexte["options"], "f": d["filtres"],
        "langue": contexte["langue"], "modifier": modifier, "version_js": version_css("js/visualisation.js"),
        **(extra or {}),
    })


@login_required
@require_GET
def page_vue(request, pk=None):
    return rendre_page(request, vue_visible(request, pk))


@login_required
@require_GET
def page_nouvelle(request):
    """Nouvelle vue : grille vide en modification, non enregistrée (« Enregistrer la vue » la crée) ; avec ?depart=1,
    la Vue de départ proposée par l'outil."""
    if request.GET.get("depart") == "1":
        return rendre_page(request, auto=vue_de_depart(request.user, campagne_choisie(request)))
    return rendre_page(request, auto={"nom": VS.lib("visu.vue.nouvelle"), "genre": "nouvelle", "filtres": {}, "visuels": [],
                                      "avertissement": limite_vues(request.user)})  # dit avant de composer


def vue_de_depart(utilisateur, campagne):
    """« Vue de départ », proposée sans être enregistrée : 4 chiffres clés (les premiers KPI numériques du référentiel
    « Je réponds à » qui ont une valeur dans le périmètre), le taux de remplissage, la comparaison des organisations du
    premier KPI additionnable, le tableau du premier thème."""
    from referentiel.models import Theme

    ref = campagne.referentiel if campagne else Referentiel.objects.filter(actif=True).order_by("ordre", "code").first()
    visuels = []
    if ref is not None:
        plan = Plan(ref)
        codes = VS.codes_du_plan(plan)
        visibles = VS.codes_visibles(utilisateur)
        kpis = {k.code: k for k in KPI.objects.filter(code__in=[c for c in codes if c in visibles])}
        numeriques = [c for c in codes if c in kpis and kpis[c].est_numerique]
        from . import visualisation as V

        source = V.Source(utilisateur, numeriques[:60])
        periode = V.periode_par_defaut(V.periodes(source.calendrier, ref) or V.periodes(source.calendrier))
        racines = source.racines()
        # les 4 premiers KPI qui ont une valeur, et le premier d'entre eux qui s'additionne : la recherche s'arrête dès
        # qu'ils sont trouvés (avant : les 60 premiers KPI étaient tous calculés)
        chiffres, additionnable = [], None
        for c in numeriques[:60]:
            if len(chiffres) >= 4 and additionnable is not None:
                break
            if not (periode and any((p := source.point(c, o, periode)) is not None and p.valeur is not None for o in racines)):
                continue
            if len(chiffres) < 4:
                chiffres.append(c)
            if additionnable is None and VS.additionnable(kpis[c]) and racines and any(
                    source.organisations_comparees(c, racines[0])):
                additionnable = c
        for c in chiffres:
            visuels.append({"id": f"d{len(visuels) + 1}", "type": "chiffre", "kpis": [c], "largeur": 3})
        visuels.append({"id": "d5", "type": "remplissage", "kpis": [], "largeur": 6})
        if additionnable:
            visuels.append({"id": "d6", "type": "organisations", "kpis": [additionnable], "largeur": 6})
        theme = Theme.objects.filter(referentiel=ref, parent=None).order_by("ordre", "id").first()
        if theme is not None:
            visuels.append({"id": "d7", "type": "tableau", "kpis": [], "source": f"theme:{theme.pk}", "largeur": 12})
    propre, _ = VS.valider_vue({"nom": VS.lib("visu.vue.depart"), "visuels": visuels}, utilisateur)
    return {"nom": VS.lib("visu.vue.depart"), "genre": "depart", "description": VS.lib("visu.vue.depart_aide"),
            "filtres": {}, "visuels": propre.get("visuels", [])}
