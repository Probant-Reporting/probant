"""Attributions d'un compte en lecture seule (règle du projet, « N4 »).

Un lecteur ou un auditeur ne saisit ni ne valide rien : quand un compte passe à l'un de ces rôles (fiche du compte, seule
porte qui change un rôle), ses attributions de contributeur et de validateur sont retirées dans la même transaction,
avec une ligne d'historique par changement de rôle (combien, lesquelles). Revenir au rôle d'avant ne les rétablit pas.
Rien n'est retiré en silence à la mise à jour d'une installation : les comptes en lecture seule qui ont encore des
attributions (créées avant cette règle) sont signalés dans « À traiter », avec une page pour les retirer
(``page``). Un compte désactivé, lui, garde ses attributions (« Remplacer une personne… » les transfère) : inchangé."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.urls import reverse

from espaces import contexte as ESP
from parametres.libelles import libelle
from referentiel.models import Attribution, Utilisateur

from .models import Journal
from .vues_communes import exiger_admin

ACTION = "retrait_attributions_role"  # action du journal (famille « SPOC »)
LONGUEUR_LISTES = 220  # caractères des deux listes dans la ligne d'historique (texte traduit à l'affichage : 300 au plus)


def nombres(utilisateur):
    """(contributeur, validateur) : attributions du compte."""
    if not utilisateur.pk:
        return 0, 0
    n = Attribution.objects.filter(utilisateur=utilisateur).aggregate(
        c=Count("pk", filter=Q(role=Attribution.Role.CONTRIBUTEUR)), v=Count("pk", filter=Q(role=Attribution.Role.VALIDATEUR)))
    return n["c"], n["v"]


def _liste(attributions, place):
    """« [KPI] Organisation, … » dans ``place`` caractères au plus ; « … (+N) » pour le reste ; « — » si vide."""
    morceaux, longueur = [], 0
    for i, a in enumerate(attributions):
        m = f"[{a.kpi_id}] {a.organisation.nom}"
        if morceaux and longueur + len(m) + 2 > place:
            morceaux.append(f"… (+{len(attributions) - i})")
            break
        morceaux.append(m)
        longueur += len(m) + 2
    return ", ".join(morceaux) or "—"


def texte_journal(attributions):
    """Ligne d'historique, en français (traduite à l'affichage, motif ``admin.journal.motif.attributions_retirees``)."""
    contrib = [a for a in attributions if a.role == Attribution.Role.CONTRIBUTEUR]
    valid = [a for a in attributions if a.role == Attribution.Role.VALIDATEUR]
    place_c = LONGUEUR_LISTES // 2 if valid else LONGUEUR_LISTES
    texte_c = _liste(contrib, place_c)
    texte_v = _liste(valid, LONGUEUR_LISTES - len(texte_c))
    return libelle("admin.journal.motif.attributions_retirees", "fr", nc=len(contrib), contrib=texte_c, nv=len(valid), valid=texte_v)


def retirer(acteur, utilisateur):
    """Retire toutes les attributions du compte (relues sous verrou), avec une ligne d'historique. Renvoie leur nombre.
    À appeler dans la transaction qui change le rôle."""
    with ESP.atomic():
        attributions = list(Attribution.objects.select_for_update().filter(utilisateur=utilisateur)
                            .select_related("organisation").order_by("role", "kpi_id", "organisation__nom", "pk"))
        if not attributions:
            return 0
        Attribution.objects.filter(pk__in=[a.pk for a in attributions]).delete()
        Journal.ecrire(acteur, ACTION, utilisateur, "attributions", texte_journal(attributions), "")
    return len(attributions)


def comptes_concernes():
    """Comptes en lecture seule (lecteur, auditeur ; jamais un superutilisateur) qui ont encore des attributions, avec
    leurs nombres : [(compte, contributeur, validateur)]."""
    qs = (Utilisateur.objects.filter(role__in=Utilisateur.ROLES_LECTURE, is_superuser=False, attributions__isnull=False)
          .annotate(nc=Count("attributions", filter=Q(attributions__role=Attribution.Role.CONTRIBUTEUR), distinct=True),
                    nv=Count("attributions", filter=Q(attributions__role=Attribution.Role.VALIDATEUR), distinct=True))
          .order_by("first_name", "last_name", "email"))
    return [(u, u.nc, u.nv) for u in qs]


def point_a_traiter():
    """Ligne de « À traiter » (Administration) ou None."""
    from . import a_traiter as AT

    n = Utilisateur.objects.filter(role__in=Utilisateur.ROLES_LECTURE, is_superuser=False, attributions__isnull=False).distinct().count()
    if not n:
        return None
    return AT.point("lecture_seule_attributions", libelle("admin.a_traiter.lecture_seule_attributions", n=n),
                    libelle("admin.a_traiter.lecture_seule_attributions_detail"),
                    libelle("admin.a_traiter.lecture_seule_attributions_action"), reverse("collecte:admin_attributions_lecture_seule"))


@login_required
def page(request):
    """Comptes en lecture seule qui ont encore des attributions : les voir, retirer celles d'un compte ou de tous (avec
    une ligne d'historique par compte). Réservée à l'administrateur, comme Comptes et Attributions."""
    exiger_admin(request)
    if request.method == "POST":
        choix = request.POST.get("compte", "")
        with ESP.atomic():
            comptes = [u for u, _, _ in comptes_concernes() if choix == "tous" or str(u.pk) == choix]
            n = sum(retirer(request.user, u) for u in comptes)
        if comptes:
            messages.success(request, libelle("admin.lecture_seule_attributions.retirees", n=n, comptes=len(comptes)))
        return redirect("collecte:admin_attributions_lecture_seule" if comptes_concernes() else "collecte:admin_accueil")
    return render(request, "collecte/administration/lecture_seule_attributions.html", {
        "page": "administration", "rubrique": "attributions", "comptes": comptes_concernes(),
        "titre_page": libelle("admin.lecture_seule_attributions.titre")})
