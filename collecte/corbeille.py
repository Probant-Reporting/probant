"""Corbeille : suppression réversible des objets courants faits par chacun.

Les exports enregistrés, les listes de KPI et les vues de la Visualisation se suppriment sans question : l'objet va dans
la corbeille (``Supprimable.supprime_le``), disparaît partout (gestionnaire par défaut) et le message « Supprimé : X.
Annuler » permet de le remettre en place. La personne qui l'a supprimé, ou un administrateur, peut le restaurer pendant
``models.jours_corbeille()`` jours (Paramètres › Hébergement, 30 par défaut) ; ensuite il est effacé pour de bon
(``models.purger_corbeille`` : à chaque suppression, au démarrage, chaque nuit et par la commande ``purge_deleted``).
Suppressions et restaurations vont au Journal.

Ce qui est encore restaurable se retrouve aussi dans Mon compte › Récemment supprimés (ce que la
personne a supprimé ; ses vues seulement pour un compte en lecture seule) et, pour l'administrateur, sur la page
Administration › Historique › Récemment supprimés (``tous_supprimes`` : ce que chacun a supprimé, qui et quand).

Restaurer une vue personnelle compte comme une création : refusée, avec le message de la
création, quand son propriétaire a déjà le maximum de vues personnelles (Paramètres › Visualisation), compte relu sous le
verrou de la ligne du propriétaire (``vues_visu.verrou_vues``).

Les suppressions partagées ou irréversibles (campagnes, comptes, organisations, référentiels) gardent la confirmation.

Le message d'annulation :
- après une suppression suivie d'un rechargement de page (formulaire, Visualisation), il est gardé dans la session
  (``CLE_SESSION``) et affiché une fois par ``templates/base.html`` (balise ``annulation_proposee``) ;
- après une suppression faite par le script de la page (réponse JSON), le script l'affiche lui-même
  (``proposerAnnulation`` de ``_app/01_socle.js``).
"""
import math

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from espaces import contexte as ESP
from espaces.requetes import est_script, reponse_erreur
from parametres.libelles import libelle

from .models import Journal, ReglageExport, SelectionKPI, VueVisu, jours_corbeille, limite_corbeille

TYPES = {"export": ReglageExport, "liste": SelectionKPI, "vue": VueVisu}
CLE_SESSION = "annulation"


def code_de(objet):
    return next(c for c, m in TYPES.items() if isinstance(objet, m))


def nom_de(objet):
    return objet.nom_affiche if isinstance(objet, ReglageExport) else objet.nom


def supprimer(request, objet, en_session=False):
    """Met ``objet`` dans la corbeille, le note au Journal et renvoie l'offre d'annulation {texte, url, bouton} ;
    ``en_session`` : la page qui s'ouvre ensuite l'affiche (suppression suivie d'un rechargement)."""
    nom = nom_de(objet)
    objet.supprimer(request.user)
    Journal.ecrire(request.user, "suppression_corbeille", objet, "", nom, "")
    offre = {"texte": libelle("messages.corbeille.supprime", nom=nom), "bouton": libelle("commun.defaire"),
             "url": reverse("collecte:corbeille_restaurer", args=[code_de(objet), objet.pk])}
    if en_session:
        request.session[CLE_SESSION] = offre
    return offre


def offre_en_attente(request):
    """L'offre d'annulation gardée pour cette page (une seule fois), ou None."""
    session = getattr(request, "session", None)
    return session.pop(CLE_SESSION, None) if session is not None and CLE_SESSION in session else None


def elements(utilisateur=None):
    """Ce qui est encore restaurable, le plus récemment supprimé d'abord : ce que ``utilisateur`` a lui-même supprimé
    (un compte en lecture seule ne voit donc que ses vues, et pour l'auditeur ses exports et listes de KPI : seuls objets
    qu'il peut supprimer), ou tout (``None`` : page de l'administrateur). Une ligne par objet :
    {code, objet, nom, type, supprime_le, efface_le, jours_restants, par, url}."""
    limite, maintenant = limite_corbeille(), timezone.now()
    lignes = []
    for code, modele in TYPES.items():
        qs = modele.tous.filter(supprime_le__gte=limite).select_related("supprime_par")
        if utilisateur is not None:
            qs = qs.filter(supprime_par=utilisateur)
        for o in qs:
            efface = o.efface_le
            lignes.append({"code": code, "objet": o, "nom": nom_de(o), "type": libelle(f"messages.corbeille.type.{code}"),
                           "supprime_le": o.supprime_le, "efface_le": efface, "par": o.supprime_par,
                           "jours_restants": max(math.ceil((efface - maintenant).total_seconds() / 86400), 1),
                           "url": reverse("collecte:corbeille_restaurer", args=[code, o.pk])})
    return sorted(lignes, key=lambda l: l["supprime_le"], reverse=True)


def _limite_des_vues(objet):
    """Message de la création si ``objet`` est une vue personnelle et que son propriétaire a déjà le maximum de vues
    personnelles, « » sinon. Dans la transaction de la restauration : compte relu sous le verrou du propriétaire."""
    if not isinstance(objet, VueVisu) or objet.partage or objet.proprietaire_id is None:
        return ""
    from .vues_visu import limite_vues, verrou_vues

    verrou_vues(objet.proprietaire)
    return limite_vues(objet.proprietaire)


@login_required
def tous_supprimes(request):
    """Administration › Historique › Récemment supprimés : tout ce qui est encore restaurable, dans cet espace, qui l'a
    supprimé et quand ; « Restaurer » remet l'objet à sa place (chez son propriétaire) et reste sur la page."""
    from .vues_communes import exiger_admin

    exiger_admin(request)
    return render(request, "collecte/administration/supprimes.html", {
        "page": "administration", "rubrique": "journal", "supprimes": elements(), "jours": jours_corbeille(),
    })


def _destination(request, objet):
    suivant = request.POST.get("suivant", "")  # la page où l'on était (liste des exports, des listes de KPI)
    if request.POST.get("rester") and suivant and url_has_allowed_host_and_scheme(suivant, {request.get_host()}, request.is_secure()):
        return suivant  # Récemment supprimés (Mon compte, Administration) : on reste sur la liste
    if isinstance(objet, VueVisu):  # la vue remise en place s'ouvre
        return reverse("collecte:visu_vue", args=[objet.pk])
    if suivant and url_has_allowed_host_and_scheme(suivant, {request.get_host()}, request.is_secure()):
        return suivant
    if isinstance(objet, SelectionKPI):
        return reverse("collecte:echanges_listes_page")
    return reverse("collecte:echanges")


@login_required
@require_POST
def restaurer(request, type_, pk):
    """« Annuler » après une suppression : remet l'objet en place (la personne qui l'a supprimé, ou un administrateur,
    pendant ``jours_corbeille()`` jours). Réponse JSON pour le script de la page, sinon retour à la page de l'objet."""
    modele = TYPES.get(type_)
    if modele is None:
        raise Http404
    objet = get_object_or_404(modele.tous.exclude(supprime_le=None), pk=pk)
    if not objet.restaurable_par(request.user):
        raise PermissionDenied(libelle("messages.corbeille.non_restaurable", n=jours_corbeille()))
    with ESP.atomic():
        refus = _limite_des_vues(objet)
        if not refus:
            objet = get_object_or_404(modele.tous.select_for_update().exclude(supprime_le=None), pk=pk)  # relu sous verrou
            objet.restaurer()
            nom = nom_de(objet)
            Journal.ecrire(request.user, "restauration_corbeille", objet, "", "", nom)
    if refus:  # la vue reste dans la corbeille ; le message de la création
        if est_script(request):
            return reponse_erreur(refus, status=400)
        messages.error(request, refus)
        suivant = request.POST.get("suivant", "")
        ok = suivant and url_has_allowed_host_and_scheme(suivant, {request.get_host()}, request.is_secure())
        return redirect(suivant if ok else reverse("collecte:visu"))
    request.session.pop(CLE_SESSION, None)
    message = libelle("messages.corbeille.restaure", nom=nom)
    url = _destination(request, objet)
    if est_script(request):
        donnees = {"ok": True, "message": message, "url": url, "id": objet.pk, "nom": nom}
        if isinstance(objet, SelectionKPI):
            donnees.update(kpis=sorted(objet.kpis.values_list("code", flat=True)), partage=objet.partage)
        return JsonResponse(donnees, json_dumps_params={"ensure_ascii": False})
    messages.success(request, message)
    return redirect(url)
