"""Valeurs forcées des KPI calculés : remplacer le résultat d'un calcul par une valeur donnée, avec une justification.

- Le responsable du résultat (personne attribuée au KPI calculé dans l'organisation) fait une demande : valeur (ou N/A)
  et justification. Elle attend l'accord de l'administrateur ou d'un validateur de l'organisation, qui l'accepte ou la
  refuse (avec un motif). Faite par l'un d'eux, elle s'applique aussitôt.
- Acceptée, la case prend la valeur forcée (origine « Valeur forcée », validée) : le calcul ne la remplace plus et elle
  remonte dans les totaux et les formules qui l'utilisent. L'administrateur ou un validateur peut revenir au calcul.
- Chaque étape est écrite dans le journal ; les demandes restent après traitement.
"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from parametres.libelles import libelle

from . import saisie as S
from .models import Campagne, DemandeForcage, Journal, Reponse
from espaces import contexte as ESP


def _possible(utilisateur, campagne, kpi, org):
    return (kpi.est_calcule and kpi.actif and org.actif and not utilisateur.lecture_seule
            and campagne.statut != Campagne.Statut.CLOTUREE and S.dans_la_campagne(campagne, kpi)
            and not S.motif_cloturee_ailleurs(campagne, kpi))


def _exiger_non_fige(campagne, kpi):
    """Valeur commune à une autre campagne clôturée de la même période : jamais forcée ni rendue au calcul d'ici."""
    motif = S.motif_cloturee_ailleurs(campagne, kpi)
    if motif:
        raise PermissionDenied(motif)


def peut_trancher(utilisateur, campagne, kpi, org):
    """Accepter, refuser, forcer directement ou revenir au calcul : l'administrateur (campagne non clôturée), un
    validateur de l'organisation (saisie ouverte)."""
    if not _possible(utilisateur, campagne, kpi, org):
        return False
    if utilisateur.est_admin:
        return True
    return campagne.saisie_ouverte() and S.voit_calcules(utilisateur, org)


def peut_demander(utilisateur, campagne, kpi, org):
    """Demander une valeur forcée : le responsable du résultat pendant la saisie, et ceux qui peuvent trancher."""
    if peut_trancher(utilisateur, campagne, kpi, org):
        return True
    return _possible(utilisateur, campagne, kpi, org) and campagne.saisie_ouverte() and S.responsable_resultat(utilisateur, kpi, org)


def en_attente(periode, kpi, org):
    return DemandeForcage.objects.filter(periode=periode, kpi=kpi, organisation=org,
                                         statut=DemandeForcage.Statut.EN_ATTENTE).select_related("demandeur").first()


def appliquee(periode, kpi, org):
    """Demande acceptée qui a donné la valeur forcée actuelle de la case (None si la case n'est pas forcée)."""
    return DemandeForcage.objects.filter(periode=periode, kpi=kpi, organisation=org,
                                         statut=DemandeForcage.Statut.ACCEPTEE).select_related("demandeur", "traite_par").first()


def demandes_a_traiter(utilisateur, campagnes=None):
    """Demandes en attente que la personne peut trancher (toutes pour l'administrateur ; celles des organisations de ses
    attributions de validateur pour un validateur)."""
    qs = (DemandeForcage.objects.filter(statut=DemandeForcage.Statut.EN_ATTENTE)
          .select_related("kpi", "organisation", "periode", "demandeur"))
    if campagnes is not None:
        qs = qs.filter(periode__in=[c.periode_id for c in campagnes])
    if utilisateur.lecture_seule:
        return []
    if utilisateur.est_admin:
        return list(qs)
    return [d for d in qs if S.voit_calcules(utilisateur, d.organisation)]


def _affiche(valeur, na):
    return "N/A" if na else "" if valeur is None else str(valeur)


@ESP.atomic
def demander(utilisateur, campagne, kpi, org, valeur, non_applicable, justification):
    """Enregistre une demande (elle remplace une demande encore en attente sur la même case). Faite par quelqu'un qui
    peut trancher, elle est acceptée aussitôt."""
    _exiger_non_fige(campagne, kpi)
    if not peut_demander(utilisateur, campagne, kpi, org):
        raise PermissionDenied(libelle("saisie.forcage.msg.non_autorise"))
    justification = (justification or "").strip()
    v = None if non_applicable else S.lire_nombre(valeur, kpi, bornes=False)
    if v is None and not non_applicable:
        raise ValidationError(libelle("saisie.msg.saisir_ou_na"))
    if not justification:
        raise ValidationError(libelle("saisie.forcage.msg.justification"))
    r = S.reponse_de(campagne, kpi, org)
    # résultat du calcul gardé avec la demande (un chiffre importé tel quel n'en est pas un)
    calculee = r.valeur if r is not None and r.origine not in (Reponse.Origine.FORCEE, Reponse.Origine.IMPORT) else None
    if r is not None and r.origine == Reponse.Origine.FORCEE:
        precedente = appliquee(campagne.periode, kpi, org)
        calculee = precedente.valeur_calculee if precedente else None
    DemandeForcage.objects.filter(periode=campagne.periode, kpi=kpi, organisation=org,  # mise à jour conditionnelle :
                                  statut=DemandeForcage.Statut.EN_ATTENTE).update(  # n'écrase pas une décision concurrente
        statut=DemandeForcage.Statut.RETIREE, traite_par=utilisateur, date_traitement=timezone.now())
    d = DemandeForcage.objects.create(periode=campagne.periode, kpi=kpi, organisation=org, valeur=v, non_applicable=non_applicable,
                                      justification=justification, valeur_calculee=calculee, demandeur=utilisateur)
    Journal.ecrire(utilisateur, "forcage_demande", d, "valeur", _affiche(calculee, False), _affiche(v, non_applicable))
    if peut_trancher(utilisateur, campagne, kpi, org):
        accepter(utilisateur, campagne, d)
    return d


def _exiger_trancher(utilisateur, campagne, demande):
    """Relit la demande dans la transaction, verrouillée (PostgreSQL) : deux personnes qui décident en même temps à
    partir de la même page ne peuvent pas toutes deux « réussir » (journal contradictoire, case forcée malgré le refus).
    Renvoie la demande relue."""
    if not peut_trancher(utilisateur, campagne, demande.kpi, demande.organisation):
        raise PermissionDenied(libelle("saisie.forcage.msg.non_autorise"))
    fraiche = DemandeForcage.objects.select_for_update().filter(pk=demande.pk).first()
    if fraiche is None or fraiche.statut != DemandeForcage.Statut.EN_ATTENTE:
        raise ValidationError(libelle("saisie.forcage.msg.deja_traitee"))
    return fraiche


def _prendre(utilisateur, demande, statut, appelant=None, **champs):
    """Passe la demande de « en attente » à ``statut`` par une mise à jour conditionnelle (aussi sûre sous SQLite, qui
    ignore le verrou) ; ValidationError si quelqu'un l'a traitée entre-temps."""
    maintenant = timezone.now()
    if not DemandeForcage.objects.filter(pk=demande.pk, statut=DemandeForcage.Statut.EN_ATTENTE).update(
            statut=statut, traite_par=utilisateur, date_traitement=maintenant, **champs):
        raise ValidationError(libelle("saisie.forcage.msg.deja_traitee"))
    for objet in {id(o): o for o in (demande, appelant) if o is not None}.values():  # l'objet de l'appelant suit
        objet.statut, objet.traite_par, objet.date_traitement = statut, utilisateur, maintenant
        for nom, valeur in champs.items():
            setattr(objet, nom, valeur)


@ESP.atomic
def accepter(utilisateur, campagne, demande):
    """La case prend la valeur demandée (validée) ; les KPI qui en dépendent sont recalculés."""
    _exiger_non_fige(campagne, demande.kpi)
    demande, appelant = _exiger_trancher(utilisateur, campagne, demande), demande
    _prendre(utilisateur, demande, DemandeForcage.Statut.ACCEPTEE, appelant)
    kpi, org = demande.kpi, demande.organisation
    for autre in (DemandeForcage.objects.filter(periode=demande.periode, kpi=kpi, organisation=org, statut=DemandeForcage.Statut.ACCEPTEE)
                  .exclude(pk=demande.pk)):
        autre.statut, autre.motif = DemandeForcage.Statut.LEVEE, libelle("saisie.forcage.motif.remplacee")
        autre.save(update_fields=["statut", "motif"])
    r = S.reponse_de(campagne, kpi, org) or Reponse(periode=demande.periode, kpi=kpi, organisation=org)
    avant = _affiche(r.valeur, r.non_applicable)
    r.valeur, r.texte, r.non_applicable, r.message_calcul = demande.valeur, "", demande.non_applicable, ""
    r.origine, r.statut = Reponse.Origine.FORCEE, Reponse.Statut.VALIDE
    r.saisi_par, r.valide_par, r.date_validation = demande.demandeur, utilisateur, timezone.now()
    r.commentaire = demande.justification
    r.save()
    Journal.ecrire(utilisateur, "forcage_accepte", r, "valeur", avant, _affiche(r.valeur, r.non_applicable))
    from .signals import apres_modification, dans_un_lot, signaler

    if dans_un_lot():  # import de valeurs : même recalcul ciblé, une fois en fin de paquet
        signaler(r)
    else:
        apres_modification(demande.periode, [kpi.code], {org.id})
    return r


@ESP.atomic
def refuser(utilisateur, campagne, demande, motif):
    demande, appelant = _exiger_trancher(utilisateur, campagne, demande), demande
    motif = (motif or "").strip()
    if not motif:
        raise ValidationError(libelle("saisie.forcage.msg.motif"))
    _prendre(utilisateur, demande, DemandeForcage.Statut.REFUSEE, appelant, motif=motif)
    Journal.ecrire(utilisateur, "forcage_refuse", demande, "motif", "", motif)
    return demande


@ESP.atomic
def retirer(utilisateur, campagne, demande):
    """La personne qui a fait la demande la retire tant qu'elle n'est pas traitée."""
    if demande.demandeur_id != utilisateur.pk or demande.statut != DemandeForcage.Statut.EN_ATTENTE:
        raise PermissionDenied(libelle("saisie.forcage.msg.non_autorise"))
    _prendre(utilisateur, demande, DemandeForcage.Statut.RETIREE)  # acceptée ou refusée entre-temps : « déjà traitée »
    Journal.ecrire(utilisateur, "forcage_retire", demande, "statut", "", demande.statut)
    return demande


def importees(campagne):
    """Chiffres importés tels quels sur des cases calculées de la période d'une campagne non clôturée (données d'avant
    la règle « un import sur une case calculée devient une valeur forcée », ou commande ``import_valeurs``) : le calcul
    ne les utilise que s'il est impossible. Hors KPI figés par une autre campagne clôturée de la période (chiffres
    officiels). [Reponse] ; rien n'est changé ici."""
    if campagne.statut == Campagne.Statut.CLOTUREE:
        return []
    qs = (Reponse.objects.filter(periode=campagne.periode, origine=Reponse.Origine.IMPORT, kpi__type_saisie__comportement="calcul")
          .select_related("kpi__unite", "kpi__type_reponse", "organisation", "saisi_par").order_by("kpi_id", "organisation__nom"))
    return [r for r in qs if S.dans_la_campagne(campagne, r.kpi) and not S.motif_cloturee_ailleurs(campagne, r.kpi)]


def _importee_verrouillee(utilisateur, campagne, kpi, org):
    """Relit sous verrou la case importée ; refuse sans le droit de forcer ou si elle a changé depuis la page."""
    _exiger_non_fige(campagne, kpi)
    if not peut_trancher(utilisateur, campagne, kpi, org):
        raise PermissionDenied(libelle("saisie.forcage.msg.non_autorise"))
    r = Reponse.objects.select_for_update().filter(periode=campagne.periode, kpi=kpi, organisation=org).first()
    if r is None or r.origine != Reponse.Origine.IMPORT:
        raise ValidationError(libelle("saisie.forcage.msg.importee_changee"))
    return r


@ESP.atomic
def forcer_importee(utilisateur, campagne, kpi, org):
    """Chiffre importé sur une case calculée : devient une valeur forcée (même mécanisme que le panneau)."""
    r = _importee_verrouillee(utilisateur, campagne, kpi, org)
    valeur = "" if r.non_applicable or r.valeur is None else format(r.valeur * 100 if kpi.est_pourcentage else r.valeur, "f")
    justification = r.commentaire or libelle("saisie.forcage.importee_justification")
    return demander(utilisateur, campagne, kpi, org, valeur, r.non_applicable, justification)


@ESP.atomic
def retirer_importee(utilisateur, campagne, kpi, org):
    """Chiffre importé sur une case calculée : retiré, la case reprend le résultat du calcul (journal, recalcul ciblé)."""
    r = _importee_verrouillee(utilisateur, campagne, kpi, org)
    avant = _affiche(r.valeur, r.non_applicable)
    r.origine, r.statut, r.valide_par, r.date_validation = Reponse.Origine.CALCUL, Reponse.Statut.CALCULE, None, None
    r.save()
    Journal.ecrire(utilisateur, "import_calcule_retire", r, "valeur", avant, "")
    from .signals import apres_modification

    apres_modification(campagne.periode, [kpi.code], {org.id})
    return S.reponse_de(campagne, kpi, org)


@ESP.atomic
def revenir_au_calcul(utilisateur, campagne, kpi, org, motif=""):
    """La case forcée reprend le résultat du calcul."""
    _exiger_non_fige(campagne, kpi)
    if not peut_trancher(utilisateur, campagne, kpi, org):
        raise PermissionDenied(libelle("saisie.forcage.msg.non_autorise"))
    r = S.reponse_de(campagne, kpi, org)
    if r is None or r.origine != Reponse.Origine.FORCEE:
        raise ValidationError(libelle("saisie.forcage.msg.pas_forcee"))
    avant = _affiche(r.valeur, r.non_applicable)
    r.origine, r.statut, r.valide_par, r.date_validation = Reponse.Origine.CALCUL, Reponse.Statut.CALCULE, None, None
    r.commentaire = ""
    r.save()
    d = appliquee(campagne.periode, kpi, org)
    if d is not None:
        d.statut, d.motif = DemandeForcage.Statut.LEVEE, (motif or "").strip()
        d.save(update_fields=["statut", "motif"])
    Journal.ecrire(utilisateur, "forcage_leve", r, "valeur", avant, "")
    from .signals import apres_modification

    apres_modification(campagne.periode, [kpi.code], {org.id})
    return S.reponse_de(campagne, kpi, org)
