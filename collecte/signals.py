"""Recalcul automatique des KPI dépendants après une saisie (cahier des charges, section 5.2)."""
import threading
from contextlib import contextmanager

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from espaces.comptes import gestionnaire_change

from .models import Campagne, Reponse

_lot = threading.local()


@receiver(post_save, sender=Campagne, dispatch_uid="collecte.campagne_creee_perimetre")
def campagne_creee(sender, instance, created, raw=False, **kwargs):
    """Campagne créée sur une période close ou rouverte : son référentiel entre dans le périmètre noté de la période
    (``calcul.etendre_pour_campagne``), par tous les chemins de création (fiche, reprise, commandes)."""
    if created and not raw and instance.periode_id:
        from .calcul import arbre_fige, etendre_pour_campagne, figee, noter_figes_partiels

        etendre_pour_campagne(instance)
        # règle « Figer ses chiffres » : une campagne non clôturée créée sur une période close laisse aux
        # KPI des campagnes clôturées leurs chiffres, avec l'arbre de la clôture qu'ils suivaient
        if not figee(instance.periode):
            noter_figes_partiels(instance.periode, arbre_fige(instance.periode))


@receiver(gestionnaire_change, dispatch_uid="collecte.gestionnaire_change_journal")
def gestionnaire_change_journal(sender, acteur, compte, oui, **kwargs):
    """Gestionnaire des espaces nommé ou retiré (``espaces.comptes.changer_gestionnaire``, page Espaces ou fiche d'un
    compte), ou rôle perdu par qui n'est plus administrateur actif de l'espace principal
    (``espaces.comptes.appliquer``) : une ligne d'historique dans l'espace où l'on agit, dans la même transaction.
    ``acteur`` : la personne, son numéro (acteur de la requête) ou None (commande, système)."""
    from referentiel.models import Utilisateur

    from .models import Journal

    if isinstance(acteur, int):
        acteur = Utilisateur.objects.filter(pk=acteur).first()
    Journal.ecrire(acteur, "reglage_compte", compte, "gestionnaire", not oui, oui)


@receiver(post_delete, sender=Campagne, dispatch_uid="collecte.campagne_supprimee_figes")
def campagne_supprimee(sender, instance, **kwargs):
    """Campagne supprimée : les KPI figés de sa période sont tenus à jour (``calcul.noter_figes_partiels``)."""
    from .models import Periode
    from .calcul import noter_figes_partiels

    p = Periode.objects.filter(pk=instance.periode_id).first()
    if p is not None:
        noter_figes_partiels(p)


@contextmanager
def en_lot():
    """Pendant un import, les recalculs sont regroupés : un seul passage par période à la fin, au lieu d'un par ligne."""
    _lot.touches = {}
    try:
        yield
        touches = _lot.touches
    finally:
        _lot.touches = None
    for periode, kpi_ids, organisations in touches.values():
        apres_modification(periode, list(kpi_ids), organisations)


def apres_modification(periode, kpi_ids, organisations=None, recalcul=True):
    """Recalcule la période (et ce qui en dépend), puis met à jour les alertes de cohérence des campagnes en cours
    de cette période qui contiennent ces KPI. ``organisations`` : celles où ces KPI ont changé (tous les KPI sont refaits
    si une organisation fermée de leur lignée peut entrer dans les totaux ou en sortir : ``calcul.kpis_a_refaire``) ;
    seules les organisations dont une case peut changer sont recalculées (``calcul.organisations_touchees``)."""
    from .calcul import recalculer
    from .coherence import controler
    from .saisie import campagnes_des

    if recalcul:  # False : seul le statut a changé (``recalcul_apres_saisie``) ; les alertes sont relues quand même
        recalculer(periode, kpi_ids, organisations=organisations)
    for c in campagnes_des(periode, kpi_ids, en_cours=True):
        controler(c, kpi_ids)


def dans_un_lot():
    """Vrai pendant un lot d'import (``en_lot``) : les recalculs attendent la fin du lot."""
    return getattr(_lot, "touches", None) is not None


def signaler(reponse):
    """Note une réponse modifiée hors saisie (import d'historique) pour le recalcul de fin de lot."""
    touches = getattr(_lot, "touches", None)
    if touches is not None:
        periode, kpi_ids, organisations = touches.setdefault(reponse.periode_id, (reponse.periode, set(), set()))
        kpi_ids.add(reponse.kpi_id)
        organisations.add(reponse.organisation_id)


# champs d'une réponse que lit un calcul ; une écriture qui n'en touche aucun (validation, retour en brouillon : statut,
# auteur, dates) ne recalcule rien. Troisième passe du calcul : la validation d'un mois refaisait l'exercice
# qui le contient, rouvert « garder les chiffres de l'époque », et son chiffre publié bougeait sans aucune correction.
CHAMPS_CALCULES = frozenset({"valeur", "texte", "non_applicable", "origine", "periode", "periode_id", "kpi", "kpi_id",
                             "organisation", "organisation_id"})
# Champs d'un changement de statut seul (validation, retour en brouillon, preuve déposée sur une valeur validée) : ni les
# totaux enregistrés ni les alertes n'en dépendent, le recalcul referait ce qui est en base en tenant le verrou de toutes
# les périodes (sous charge, les autres enregistrements attendaient derrière ; test_recalcul_apres_saisie_statut.py).
CHAMPS_DU_STATUT = frozenset({"statut", "valide_par", "date_validation", "date_maj"})


@receiver(post_save, sender=Reponse)
def recalcul_apres_saisie(sender, instance, raw=False, update_fields=None, **kwargs):
    if raw or instance.origine != Reponse.Origine.SAISIE:
        return
    if update_fields is not None and set(update_fields) <= CHAMPS_DU_STATUT:
        return
    recalcul = update_fields is None or bool(CHAMPS_CALCULES & set(update_fields))
    if getattr(_lot, "touches", None) is not None:
        if recalcul:
            signaler(instance)
        return
    apres_modification(instance.periode, [instance.kpi_id], {instance.organisation_id}, recalcul=recalcul)
