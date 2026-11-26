"""Comptes en lecture seule (lecteur, auditeur) : ce qu'ils peuvent ouvrir, et la garantie qu'ils n'écrivent rien.

- Lecteur : Visualisation et Tableau de bord (et son compte).
- Auditeur : tout ce qu'il faut pour conduire un audit, en lecture : Saisie (valeurs, statuts, qui a saisi et validé,
  commentaires, preuves), Cohérence (alertes et justifications), Historique (journal des modifications, et historique
  des connexions désormais), certificat de clôture (page à imprimer), Import / Export (télécharger les exports),
  Visualisation, Tableau de bord.
- Aucun des deux ne saisit, ne valide, ne justifie, n'importe ni ne règle quoi que ce soit : toute requête qui écrit
  (POST…) est refusée ici, avant la vue, sauf ce qui ne touche que leurs préférences (mot de passe, vues et listes
  de KPI personnels, exports enregistrés pour eux) ou ne fait que lire (télécharger un export, aperçu).
- Un gros export demandé par un auditeur (au-delà du seuil de Paramètres › Hébergement) crée une tâche
  (``TacheExport``) : trace technique à lui, comme ses exports enregistrés ; aucune donnée de l'outil ne change et rien
  n'est écrit au journal des modifications (``collecte/exports_arriere_plan.py``).
"""
from django.core.exceptions import PermissionDenied
from django.urls import Resolver404, resolve

from parametres import libelles as LB
from parametres.libelles import libelle

PAGES_LECTEUR = {
    "accueil", "tableau_de_bord", "consolidation", "consolidation_excel", "choix_reponse", "choisir_campagne", "mon_compte",
    "visu", "visu_theme", "visu_kpi", "visu_tableau", "visu_tableau_nouveau", "visu_tableau_modifier",
    # Visualisation (vues)
    "visu_vue", "visu_vue_nouvelle", "visu_catalogue", "visu_vue_donnees", "visu_donnees", "visu_vue_creer",
    "visu_vue_enregistrer", "visu_vue_dupliquer", "visu_vue_supprimer", "visu_vue_partage", "visu_vues_ordre",
    "visu_vue_preferee", "visu_vue_excel", "visu_excel",
    # Données et confidentialité
    "confidentialite",
    "aide", "aide_guide", "aide_image",  # guides par rôle (collecte/aide.py) : lecture seule, aucune donnée
    "corbeille_restaurer",  # « Annuler » après la suppression d'une de ses vues, listes ou exports (corbeille.py)
}
PAGES_AUDITEUR = PAGES_LECTEUR | {
    "saisie", "cellule", "preuve", "coherence", "alerte", "historique",
    "historique_connexions",  # historique des connexions, en lecture (vues_connexions.py)
    "certificat_cloture",  # page à imprimer d'une campagne clôturée, en lecture (vues_certificat.py ; partiel pour un auditeur limité)
    "echanges", "echanges_exporter", "echanges_resume", "echanges_listes_page", "echanges_listes", "echanges_supprimer_reglage",
    # gros export fabriqué en arrière-plan : son état et son fichier (lectures ; collecte/exports_arriere_plan.py)
    "echanges_export_etat", "echanges_export_fichier",
}
# écritures permises : préférences de la personne (son mot de passe, ses vues, ses listes et ses exports à elle) et
# envois qui ne font que lire (télécharger un export, son aperçu)
ECRITURES_PERMISES = {
    "mon_compte",
    "echanges_exporter", "echanges_resume", "echanges_listes_page", "echanges_listes", "echanges_supprimer_reglage",
    # Visualisation : envois qui ne font que lire (données, Excel) et préférences (vues personnelles, ordre, défaut ;
    # chaque vue contrôle elle-même qu'une vue partagée n'est jamais modifiée). « visu_vue_partage » n'en fait pas partie.
    "visu_donnees", "visu_excel", "visu_vue_creer", "visu_vue_enregistrer", "visu_vue_dupliquer", "visu_vue_supprimer",
    "visu_vues_ordre", "visu_vue_preferee",
    "corbeille_restaurer",  # ne remet en place que ce que la personne a elle-même supprimé (corbeille.restaurer)
}
# hors de l'outil : connexion (par mot de passe ou par le compte d'entreprise), déconnexion, langue de l'interface
LIBRES = {"logout", "login", "langue", "entreprise_debut", "entreprise_retour"}
# ouvertes à tous, même sans connexion : logo de l'identité, état pour la supervision de l'IT (même réponse qu'à un visiteur)
PARAMETRES_LIBRES = {"logo", "sante"}


class LectureSeuleMiddleware:
    """Refuse au lecteur et à l'auditeur les pages qui ne sont pas pour eux, et toute écriture hors de leurs préférences."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        u = getattr(request, "user", None)
        if u is not None and u.is_authenticated and getattr(u, "lecture_seule", False) \
                and not request.path.startswith(("/static/", "/media/")):
            refus = motif_refus(u, request)
            if refus:
                raise PermissionDenied(refus)
        return self.get_response(request)


def motif_refus(utilisateur, request):
    """Motif du refus, ou « » si la requête est permise."""
    try:
        r = resolve(request.path_info)
    except Resolver404:
        return ""  # page inconnue : la vue « introuvable » répondra
    return motif_refus_page(utilisateur, r.namespace, r.url_name or "", request.method)


def motif_refus_page(utilisateur, namespace, nom, methode):
    """Motif du refus d'une page (espace de noms et nom de l'adresse) pour une méthode HTTP, ou « » si elle est permise.
    La même règle sert aux pages (``motif_refus``) et aux outils du serveur MCP (serveur_mcp/outils.py : chaque outil
    nomme la page qui fait la même chose)."""
    if nom in LIBRES:
        return ""
    if namespace == "parametres" and nom in PARAMETRES_LIBRES:
        return ""
    pages = PAGES_AUDITEUR if utilisateur.est_auditeur else PAGES_LECTEUR
    if namespace != "collecte" or nom not in pages:
        return libelle("messages.lecture_seule.page_interdite", role=LB.choix_phrase(utilisateur, "role"))
    if methode not in ("GET", "HEAD", "OPTIONS") and nom not in ECRITURES_PERMISES:
        return libelle("messages.lecture_seule.ecriture_interdite")
    return ""
