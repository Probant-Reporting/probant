"""Liste « À traiter » : un seul bloc (gabarit ``collecte/administration/_a_traiter.html``), partagé par le Tableau de bord et
l'Administration › Vue d'ensemble. Les sujets communs aux deux pages (cases sans SPOC, organisations en retard, e-mails
pas configurés) sont écrits ici, une seule fois : mêmes titres, mêmes détails, mêmes mots dans les liens."""
from django.urls import reverse

from parametres.libelles import libelle


def point(code, titre, detail, action="", url="", sur_place=False):
    """Une ligne de la liste : titre en gras, détail, lien d'action à droite (aucun lien sans ``action``).
    ``sur_place`` : le lien montre les organisations en retard dans la page (tableau de bord), sans la quitter."""
    return {"code": code, "titre": titre, "detail": detail, "action": action, "url": url, "sur_place": sur_place}


def sans_spoc(n, avec_lien=True):
    """Cases sans SPOC ; le lien « Attribuer » est réservé à qui peut attribuer (l'administrateur)."""
    return point("sans_spoc", libelle("admin.a_traiter.sans_spoc", n=n), libelle("admin.a_traiter.sans_spoc_detail"),
                 libelle("admin.a_traiter.sans_spoc_action") if avec_lien else "", reverse("collecte:admin_attributions") if avec_lien else "")


def retards(n, campagne, attendu, url, sur_place=False):
    """Organisations en retard sur le rythme attendu de la campagne."""
    return point("retards", libelle("admin.a_traiter.retard", n=n),
                 libelle("admin.a_traiter.retard_detail", campagne=campagne.nom_complet_affiche, attendu=attendu),
                 libelle("admin.a_traiter.retard_action"), url, sur_place)


def emails(auto=False, avec_lien=True):
    """Envoi des e-mails pas encore configuré ; le lien « Hébergement » est réservé à l'administrateur."""
    return point("emails", libelle("admin.a_traiter.emails"),
                 libelle("admin.a_traiter.emails_detail_auto" if auto else "admin.a_traiter.emails_detail"),
                 libelle("admin.a_traiter.hebergement") if avec_lien else "", reverse("parametres:hebergement") if avec_lien else "")
