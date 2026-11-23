"""Administration › Comptes › Historique des connexions (referentiel/historique_connexions.py) : qui s'est connecté et
quand, dans cet espace, avec le résultat (réussie, échec, bloquée par la limite d'essais). Filtres appliqués par le
serveur (comme l'Historique) : recherche (nom, e-mail, empreinte d'un identifiant inconnu), résultat, période. Lecture
seule, pour l'administrateur de l'espace (comme Comptes) et, depuis la, pour l'auditeur, qui
n'a pas le menu Administration : il y arrive par son « Historique » (``historique/connexions/``, même vue, mêmes
filtres, sans lien vers le réglage de la durée). Périmètre de l'auditeur : celui de la vue « Modifications
d'administration » de l'Historique, donc seulement sans limite d'organisations (``auditeur_permis``)."""
import datetime

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from parametres.libelles import libelle
from parametres.models import Instance
from referentiel import historique_connexions as HC
from referentiel.models import HistoriqueConnexion

from .templatetags.collecte import entier
from .vues_communes import exiger_admin

LIMITE = 300  # lignes montrées (la recherche et les filtres trouvent le reste)
PERIODES = ("1", "7", "30")  # jours ; vide : tout ce qui est gardé
RESULTATS = [c for c, _ in HistoriqueConnexion.Resultat.choices]


def auditeur_permis(utilisateur):
    """Vrai si l'auditeur lit l'historique des connexions : sans limite d'organisations, comme la vue « Modifications
    d'administration » de l'Historique (l'historique des connexions porte sur tous les comptes de l'espace)."""
    return utilisateur.est_auditeur and utilisateur.orgs_permises() is None


@login_required
def historique(request):
    auditeur = request.user.est_auditeur
    if not auditeur:
        exiger_admin(request)
    elif not auditeur_permis(request.user):
        raise PermissionDenied(libelle("admin.connexions.auditeur_limite"))
    total = HC.recentes()
    q = request.GET.get("q", "").strip()[:150]
    resultats = [r for r in dict.fromkeys(request.GET.getlist("resultat")) if r in RESULTATS]
    periode = request.GET.get("periode", "")
    periode = periode if periode in PERIODES else ""
    qs = total.select_related("utilisateur")
    if periode:
        qs = qs.filter(date__gte=timezone.now() - datetime.timedelta(days=int(periode)))
    if q:
        # empreinte d'un identifiant inconnu : tapée telle quelle (« 3fa9c1d2 »), ou l'identifiant lui-même
        qs = qs.filter(Q(utilisateur__first_name__icontains=q) | Q(utilisateur__last_name__icontains=q)
                       | Q(utilisateur__email__icontains=q) | Q(utilisateur__username__icontains=q)
                       | Q(empreinte=q.lower()) | Q(empreinte=HC.empreinte(q)))
    par_resultat = dict(qs.values_list("resultat").annotate(n=Count("pk")).order_by())
    if resultats:
        qs = qs.filter(resultat__in=resultats)
    lignes = list(qs[:LIMITE])
    filtre = bool(q or resultats or periode)
    nb_filtre, nb_total = (qs.count(), total.count()) if filtre else (0, 0)
    return render(request, "collecte/administration/connexions.html", {
        "page": "historique" if auditeur else "administration", "rubrique": "comptes", "lignes": lignes,
        "url_page": request.path, "q": q, "periode": periode,
        "resultats_choisis": resultats, "filtre": filtre, "limite": len(lignes) == LIMITE,
        "choix_resultats": [(c, libelle(f"admin.connexions.resultat.{c}"), par_resultat.get(c, 0)) for c in RESULTATS],
        "choix_periodes": [(p, libelle("admin.connexions.periode.jours", n=int(p))) for p in PERIODES],
        "compte": libelle("commun.filtres.compte", n=nb_filtre, nombre=entier(nb_filtre), total=entier(nb_total)) if filtre else "",
        "jours": Instance.courante().connexions_jours, "rien": not total.exists(),
    })
