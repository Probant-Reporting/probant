"""Conservation des preuves des KPI sensibles : Administration › Preuves à supprimer.

La mention « confidentialité » de la fiche KPI (``KPI.confidentialite``) sert à la conservation ou à la suppression des
preuves (RGPD ou autre). Sont **sensibles** les KPI « Restreint » et « Confidentiel » ; « Non sensible » n'a aucun effet.

Règle (hypothèses à valider, voir le rapport) :
- la durée est un réglage de l'installation, en mois (``Instance.preuves_sensibles_mois``, Paramètres › Hébergement) ;
  vide : pas de durée, rien n'est jamais proposé ;
- une preuve est « à supprimer » quand sa période est finie depuis plus que cette durée ET que toutes les campagnes de
  cette période qui contiennent le KPI sont clôturées. Date de référence : la **fin de la période** (stockée, objective,
  jamais modifiée par une réouverture) ; la date de clôture de la campagne n'est pas enregistrée (seulement au journal) ;
  la clôture reste une condition : tant qu'une campagne est ouverte ou en revue, ses preuves servent encore ;
- « à supprimer depuis » : premier jour du mois qui suit la fin de la période, plus la durée ;
- rien n'est supprimé seul : l'administrateur supprime, une par une ou en groupe, après confirmation.

Une suppression ici est **réelle** : la ligne et le fichier sont détruits (pas la corbeille, ``collecte/corbeille.py``,
réservée aux objets que l'on peut restaurer). Le fichier n'est effacé qu'une fois la suppression enregistrée. La valeur
de la case n'est pas touchée (la campagne est clôturée : figée). Les sauvegardes déjà faites gardent le fichier jusqu'à
leur remplacement par la rotation (``Instance.sauvegarde_conserver``), et une restauration le remet : le texte de
confirmation le dit. Journal : action ``purge_preuve``, objet = la réponse, champ « preuve », avant = nom du fichier (comme
le dépôt et le retrait déjà journalisés), après = le motif ; ni contenu du fichier ni nom de la personne qui l'avait
déposée.
"""
import datetime
from functools import partial
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from espaces import contexte as ESP
from parametres.libelles import libelle
from parametres.models import Instance
from referentiel.models import KPI

from . import saisie as S
from .models import Campagne, Journal, Preuve
from .periodes import ajouter_mois

SENSIBLES = (KPI.Confidentialite.RESTREINT, KPI.Confidentialite.CONFIDENTIEL)
MAX_MOIS = 240
MAX_LIGNES = 500  # lignes affichées (et supprimables d'un coup) ; les plus anciennes d'abord
ACTION_JOURNAL = "purge_preuve"


def mois_reglage():
    """Durée de conservation en mois, ou None (pas de durée : rien n'est jamais proposé)."""
    try:
        n = Instance.courante().preuves_sensibles_mois
    except Exception:  # noqa: BLE001 - base pas encore migrée (démarrage)
        return None
    return n if n and 1 <= n <= MAX_MOIS else None


def echeance(periode, mois):
    """Premier jour où la preuve d'une période est à supprimer : mois qui suit la fin de la période, plus la durée."""
    return ajouter_mois(periode.fin + datetime.timedelta(days=1), mois)


def a_supprimer(mois=None, aujourdhui=None):
    """Preuves des KPI sensibles à supprimer, les plus anciennes d'abord : une ligne par preuve
    {preuve, reponse, kpi, organisation, periode, campagne, echeance, jours}. Liste vide sans durée réglée."""
    mois = mois or mois_reglage()
    if not mois:
        return []
    aujourdhui = aujourdhui or timezone.localdate()
    candidates = (Preuve.objects.filter(reponse__kpi__confidentialite__in=SENSIBLES,
                                        reponse__periode__fin__lt=ajouter_mois(aujourdhui, 1 - mois))
                  .select_related("reponse__kpi", "reponse__organisation", "reponse__periode"))
    campagnes, perimetres, sortie = {}, {}, []
    for p in candidates:
        r = p.reponse
        date = echeance(r.periode, mois)
        if date > aujourdhui:
            continue
        if r.periode_id not in campagnes:
            campagnes[r.periode_id] = list(Campagne.objects.filter(periode_id=r.periode_id).select_related("referentiel", "periode"))
        contenant = []
        for c in campagnes[r.periode_id]:
            if c.referentiel_id not in perimetres:
                perimetres[c.referentiel_id] = S.codes_perimetre(c.referentiel)
            codes = perimetres[c.referentiel_id]
            if codes is None or r.kpi_id in codes[1]:
                contenant.append(c)
        if not contenant or any(c.statut != Campagne.Statut.CLOTUREE for c in contenant):
            continue  # une campagne qui contient le KPI n'est pas clôturée : la preuve sert encore
        sortie.append({"preuve": p, "reponse": r, "kpi": r.kpi, "organisation": r.organisation, "periode": r.periode,
                       "campagne": contenant[0], "echeance": date, "jours": (aujourdhui - date).days})
    return sorted(sortie, key=lambda l: (l["echeance"], l["preuve"].pk))


def nombre():
    """Nombre de preuves à supprimer (rappel « À traiter » de l'Administration)."""
    return len(a_supprimer())


@ESP.atomic
def supprimer(utilisateur, ids):
    """Détruit les preuves ``ids`` qui sont encore à supprimer au moment du clic (les autres sont ignorées : une
    campagne rouverte, une durée allongée, une preuve déjà retirée). Renvoie (supprimées, ignorées)."""
    mois = mois_reglage()
    dues = {l["preuve"].pk: l for l in a_supprimer(mois)} if mois else {}
    demandees = list(dict.fromkeys(ids))
    n = 0
    for pk in demandees:
        ligne = dues.get(pk)
        if ligne is None:
            continue
        preuve, reponse = ligne["preuve"], ligne["reponse"]
        nom = preuve.nom_fichier
        chemin = preuve.fichier.path if preuve.fichier.name else None  # chemin figé : l'espace courant peut changer ensuite
        preuve.delete()
        if chemin:  # le fichier n'est effacé qu'une fois la suppression enregistrée
            effacer = partial(Path(chemin).unlink, missing_ok=True)
            transaction.on_commit(effacer, using=ESP.alias_courant())
        Journal.ecrire(utilisateur, ACTION_JOURNAL, reponse, "preuve", nom,
                       f"Durée de conservation dépassée : {mois} mois après la fin de la période {reponse.periode}")
        n += 1
    return n, len(demandees) - n


def _identifiants(valeurs):
    sortie = []
    for v in valeurs:
        if v.isascii() and v.isdigit() and len(v) < 10:
            sortie.append(int(v))
    return sortie


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def page(request):
    """Administration › Preuves à supprimer : liste filtrée côté serveur ; POST : suppression d'une ou plusieurs preuves."""
    from .vues_communes import exiger_admin

    exiger_admin(request)
    if request.method == "POST":
        n, ignorees = supprimer(request.user, _identifiants(request.POST.getlist("preuves")))
        if n:
            messages.success(request, libelle("admin.preuves.supprimees", n=n))
        if ignorees:
            messages.warning(request, libelle("admin.preuves.ignorees", n=ignorees))
        return redirect(reverse("collecte:admin_preuves"))
    mois = mois_reglage()
    toutes = a_supprimer(mois)
    q = request.GET.get("q", "").strip().lower()
    orgs, camps, kpis = (request.GET.getlist(c) for c in ("org", "campagne", "kpi"))

    def garde(l):
        texte = f"{l['kpi'].code} {l['kpi'].nom} {l['organisation'].nom} {l['preuve'].nom_fichier}".lower()
        return ((not q or q in texte) and (not orgs or str(l["organisation"].pk) in orgs)
                and (not camps or str(l["campagne"].pk) in camps) and (not kpis or l["kpi"].code in kpis))

    lignes = [l for l in toutes if garde(l)]

    def choix(cle):  # [(valeur, libellé, nombre)] sur tout ce qui est à supprimer, pour le panneau du filtre
        vus = {}
        for l in toutes:
            v, t = cle(l)
            vus.setdefault(v, [t, 0])[1] += 1
        return sorted(((v, t, n) for v, (t, n) in vus.items()), key=lambda x: x[1].lower())

    instance = Instance.courante()
    filtre = bool(q or orgs or camps or kpis)
    from .templatetags.collecte import entier

    return render(request, "collecte/administration/preuves.html", {
        "page": "administration", "rubrique": "journal", "mois": mois, "total": len(toutes), "filtre": filtre,
        "lignes": lignes[:MAX_LIGNES], "nb_lignes": len(lignes), "coupe": len(lignes) > MAX_LIGNES, "max_lignes": MAX_LIGNES,
        "q": request.GET.get("q", "").strip(), "orgs_choisies": orgs, "camps_choisies": camps, "kpis_choisis": kpis,
        "choix_orgs": choix(lambda l: (str(l["organisation"].pk), l["organisation"].nom)),
        "choix_camps": choix(lambda l: (str(l["campagne"].pk), l["campagne"].nom_complet_affiche)),
        "choix_kpis": choix(lambda l: (l["kpi"].code, f"{l['kpi'].code} · {l['kpi'].nom}")),
        "compte": libelle("commun.filtres.compte", n=len(lignes), nombre=entier(len(lignes)), total=entier(len(toutes))) if filtre else "",
        "sauvegardes": max(instance.sauvegarde_conserver, 1),
    })
