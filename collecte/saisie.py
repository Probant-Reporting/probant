"""Page contributeur : périmètre, droits et règles de saisie (cahier des charges, sections 4.4 et 5.1 à 5.4).

Une cellule est un couple KPI × organisation pour une campagne (un référentiel et une période) ; sa réponse est celle
du KPI × organisation × période, partagée par toutes les campagnes de cette période qui contiennent le KPI. Les fonctions de ce module
vérifient les droits côté serveur et lèvent ``ValidationError`` ou ``PermissionDenied``
avec un message en français affichable tel quel.
"""
import gc
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import partial
from pathlib import Path

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from parametres import langues as L
from parametres.libelles import libelle
from referentiel.models import KPI, Attribution, ElementReferentiel, Organisation, Referentiel, Utilisateur, porteurs_orphelins
from referentiel.plans import Plan

from . import dates_courtes as DC
from .fichiers import sans_controle
from .models import DECIMALES_GARDEES, VALEUR_MAX, Campagne, Journal, Preuve, Reponse, valeur_enregistree, valider_fichier
from .templatetags.collecte import arrondi
from espaces import contexte as ESP

CENT = Decimal(100)
CHAMPS_SUIVIS = ("valeur", "texte", "non_applicable", "commentaire", "statut")


# ---------------------------------------------------------------- périmètre
def codes_perimetre(referentiel=None, periode=None):
    """(KPI des éléments, KPI des éléments et de toutes les sources de leurs formules) d'un référentiel, ou de tous
    les référentiels actifs ; None s'ils ne contiennent aucun KPI (tout le catalogue est alors collecté).
    ``periode`` : seulement les éléments que le référentiel y demande (« demandé depuis »,
    ``demande_depuis.filtre_demande``, la seule règle) ; les sources de leurs formules restent demandées avec eux."""
    from .demande_depuis import avec_sources, filtre_demande

    if referentiel is None:
        base = ElementReferentiel.objects.filter(referentiel__actif=True)
    else:
        base = ElementReferentiel.objects.filter(referentiel=referentiel)
    dans = set(base.filter(filtre_demande(periode)).values_list("kpi_id", flat=True))
    if not dans:
        # référentiel encore vide alors qu'un autre référentiel contient des KPI : il ne demande rien (pas tout le
        # catalogue) ; sans aucun référentiel actif qui contienne des KPI (installation neuve) : tout le catalogue ;
        # éléments tous demandés après la période : rien
        if (referentiel is not None and ElementReferentiel.objects.filter(referentiel__actif=True).exists()) or \
                (periode is not None and base.exists()):
            return set(), set()
        return None
    return dans, avec_sources(dans)


def codes_campagne(campagne):
    """``codes_perimetre`` du référentiel de la campagne dans sa période (« demandé depuis »), limité au périmètre gelé
    de sa période (exercice clos ou rouvert, ``calcul.perimetre_gele``, la fonction qui borne aussi le calcul) : ce qui
    est offert à la saisie et ce qui est calculé coïncident."""
    from .calcul import perimetre_gele

    codes = codes_perimetre(campagne.referentiel, campagne.periode)
    gele = perimetre_gele(campagne.periode)
    if gele is None:
        return codes
    if codes is None:
        return set(gele), set(gele)
    return codes[0] & gele, codes[1] & gele


def kpis_collectes(referentiel=None, periode=None):
    """KPI saisis ou paramètres hérités (facteurs d'émission) actifs : les KPI calculés n'apparaissent jamais.

    Ce sont ceux des référentiels actifs (ou du référentiel donné), plus ceux qu'il faut pour calculer leurs formules ;
    un KPI du catalogue qui n'est dans aucun référentiel n'est pas demandé. Sans référentiel actif qui contienne des KPI
    (installation neuve), tout le catalogue est collecté. ``periode`` : ceux que le référentiel y demande (« demandé
    depuis »)."""
    from .demande_depuis import filtre_demande

    qs = KPI.objects.filter(actif=True).exclude(type_saisie__comportement="calcul")
    codes = codes_perimetre(referentiel, periode)
    if codes is None:
        return qs
    dans, utiles = codes
    elements = ElementReferentiel.objects.filter(**({"referentiel": referentiel} if referentiel else {"referentiel__actif": True}))
    elements = elements.filter(filtre_demande(periode))
    return qs.filter(Q(code__in=elements.values("kpi_id")) | Q(code__in=sorted(utiles - dans)))


def frequences(campagne):
    """Fréquences de saisie des KPI (lues une fois par campagne)."""
    if not hasattr(campagne, "_frequences"):
        from .calcul import frequences_de_saisie

        campagne._frequences = frequences_de_saisie()
    return campagne._frequences


def cumule(campagne, kpi):
    """Vrai si, dans cette campagne, le KPI s'obtient à partir de périodes plus courtes (ex. l'année à partir des mois) :
    il se saisit dans le référentiel plus fréquent, et apparaît ici en lecture seule."""
    from .calcul import cumule as cumule_

    return cumule_(kpi, campagne.periode, frequences(campagne))


def arbre_organisations(periode=None, code=None):
    """{id: Organisation} avec les parents déjà reliés (pas de requête en remontant l'arbre)
    et la profondeur dans l'arbre (``prof`` : 0 au sommet, pour le retrait à l'affichage).
    Avec ``periode`` : l'arbre que suit la période (``calcul.arbre_periode`` : celui de sa clôture si elle est close ou
    rouverte en gardant les chiffres de l'époque; sinon celui d'aujourd'hui) ; avec ``code``,
    celui que suit ce KPI (un KPI figé par une campagne clôturée suit l'arbre du jour où il a été figé)."""
    toutes = {o.id: o for o in Organisation.objects.select_related("niveau")}
    if periode is not None:
        from .calcul import arbre_periode

        toutes = arbre_periode(periode, toutes, code)
    for o in toutes.values():
        o.parent = toutes.get(o.parent_id)
    for o in toutes.values():
        o.prof = len(cle_arbre(o)) - 1
    return toutes


def cellules(utilisateur, personnel=False, campagne=None, kpi_ids=None):
    """Couples (KPI, organisation) visibles et saisissables par l'utilisateur.

    - administrateur : toutes les cellules attendues (KPI collecté actif × organisation active de sa granularité ; pour un
      paramètre hérité, aussi les organisations qui le portent faute d'ancêtre de son niveau, CALC-09) ;
    - contributeur : ses attributions ;
    - validateur : les cellules des organisations qui lui sont attribuées, et de leurs descendantes.
    personnel=True : seulement ce qui est attribué à la personne (page « Pour moi »), même pour un admin.
    ``campagne`` : seulement les KPI de son référentiel (et les sources de leurs formules), sans ceux qui s'y obtiennent
    à partir de périodes plus courtes ; sinon les KPI de tous les référentiels actifs.
    ``kpi_ids`` : seulement ces KPI (même résultat pour eux, sans lire tout le catalogue : panneau de saisie).
    """
    from parametres import niveaux as N

    voit_tout = utilisateur.voit_tout and not personnel  # admin, et lecteur ou auditeur (dans leurs organisations consultées)
    qs = kpis_collectes(campagne.referentiel, campagne.periode) if campagne else kpis_collectes()
    if campagne is not None:  # exercice clos ou rouvert : rien hors de son périmètre gelé (comme le calcul)
        from .calcul import perimetre_gele

        gele = perimetre_gele(campagne.periode)
        if gele is not None:
            qs = qs.filter(code__in=sorted(gele))
    if kpi_ids is not None:
        qs = qs.filter(code__in=list(kpi_ids))
    if not voit_tout:  # seuls comptent les KPI de ses attributions : pas tout le catalogue à chaque page (même résultat)
        qs = qs.filter(code__in=Attribution.objects.filter(utilisateur=utilisateur).values("kpi_id"))
    kpis = {k.code: k for k in qs}
    if campagne is not None:
        kpis = {c: k for c, k in kpis.items() if not cumule(campagne, k)}
    # exercice clos ou rouvert en gardant les chiffres : arbre de sa clôture (une organisation créée depuis n'y a pas de
    # case) ; un KPI figé par une campagne clôturée de la période suit l'arbre du jour où il l'a été 
    partiels = None
    if campagne is not None:
        from .calcul import figes_partiels, ouverte

        partiels = figes_partiels(campagne.periode)
    rangs = N.rangs()
    permises = utilisateur.orgs_permises() if voit_tout else None
    contextes = {}

    def contexte(k):
        """(toutes, orgs, par_niveau, orphelins) de l'arbre que suit le KPI ``k`` (lus une fois par arbre)."""
        cle = partiels["kpis"].get(k.code) if partiels else None
        if cle not in contextes:
            toutes = arbre_organisations(campagne.periode if campagne is not None else None, None if cle is None else k.code)
            if campagne is not None:  # pas encore ouverte pendant la période (date d'ouverture) : rien à y saisir
                orgs = {i: o for i, o in toutes.items() if o.actif and ouverte(o, campagne.periode, toutes)}
            else:
                orgs = {i: o for i, o in toutes.items() if o.actif}
            par_niveau = {}
            for o in orgs.values():
                if permises is None or o.id in permises:
                    par_niveau.setdefault(o.niveau_id, []).append(o)
            contextes[cle] = (toutes, orgs, par_niveau, {}, {})
        return contextes[cle]

    def ou_se_saisit(k):
        """Organisations (actives, consultées) où le KPI se saisit : celles de son niveau ; pour un paramètre hérité, aussi
        celles qui le portent faute d'ancêtre de ce niveau (CALC-09)."""
        toutes, _, par_niveau, orphelins, _ = contexte(k)
        if not k.est_herite:
            return par_niveau.get(k.granularite_id, [])
        if k.granularite_id not in orphelins:
            orphelins[k.granularite_id] = porteurs_orphelins(k.granularite_id, [o for os_ in par_niveau.values() for o in os_],
                                                             rangs, toutes)
        return par_niveau.get(k.granularite_id, []) + orphelins[k.granularite_id]

    if voit_tout:
        return [(k, o) for k in kpis.values() for o in ou_se_saisit(k)]

    def lignee(k, o):
        """L'organisation et ses ancêtres (identifiants), lue une fois par organisation (et par arbre) : un validateur d'un
        pays a une attribution par KPI, chacune parcourt toutes les organisations du niveau du KPI (échelle, P-A9 : 370 000
        appels)."""
        toutes, _, _, _, lignees = contexte(k)
        ids = lignees.get(o.id)
        if ids is None:
            ids, x = set(), o
            while x:
                ids.add(x.id)
                x = toutes.get(x.parent_id)
            lignees[o.id] = ids
        return ids

    vues = set()
    attributions = Attribution.objects.filter(utilisateur=utilisateur, kpi_id__in=kpis).values_list("kpi_id", "organisation_id", "role")
    for kpi_id, org_id, role in attributions:
        kpi = kpis[kpi_id]
        orgs = contexte(kpi)[1]
        if role == Attribution.Role.CONTRIBUTEUR:
            if org_id in orgs and kpi.se_saisit_a(orgs[org_id], rangs):
                vues.add((kpi_id, org_id))
        else:
            for o in ou_se_saisit(kpi):
                if org_id in lignee(kpi, o):
                    vues.add((kpi_id, o.id))
    return [(kpis[k], contexte(kpis[k])[1][o]) for k, o in vues]


def au_dessus(kpi, org, rangs=None):
    """Vrai si la cellule est au-dessus de la granularité d'un KPI qui accepte la saisie aux niveaux supérieurs : on y
    saisit une valeur quand le détail manque (sinon elle montre le total calculé)."""
    if not kpi.saisissable_au_dessus or org.niveau_id == kpi.granularite_id:
        return False
    if rangs is None:
        from parametres import niveaux as N

        rangs = N.rangs()
    return rangs.get(org.niveau_id, 0) < rangs.get(kpi.granularite_id, 0)


def saisies_au_dessus(periode, kpi_ids=None):
    """{(KPI, organisation)} des valeurs saisies ou importées au-dessus de la granularité sur la période."""
    qs = Reponse.objects.filter(periode=periode, kpi__saisie_au_dessus=True, kpi__type_saisie__comportement="saisie",
                                origine__in=[Reponse.Origine.SAISIE, Reponse.Origine.IMPORT])
    if kpi_ids is not None:
        qs = qs.filter(kpi_id__in=kpi_ids)
    qs = qs.filter(Q(valeur__isnull=False) | ~Q(texte="") | Q(non_applicable=True)).exclude(organisation__niveau=F("kpi__granularite"))
    return set(qs.values_list("kpi_id", "organisation_id"))


def couvertes(periode, paires):
    """{(KPI, organisation): organisation du dessus} des cellules qui ne sont plus attendues : une valeur a été saisie
    pour ce KPI à un niveau supérieur (le détail n'est pas disponible). Elles restent saisissables."""
    paires = list(paires)
    dessus = saisies_au_dessus(periode, {k.code for k, _ in paires}) if paires else set()
    if not dessus:
        return {}
    sortie, kpis_dessus = {}, {k for k, _ in dessus}
    for k, o in paires:
        if k.code not in kpis_dessus:  # aucune valeur au-dessus pour ce KPI : rien à chercher dans les ancêtres
            continue
        a = o.parent
        while a is not None:
            if (k.code, a.id) in dessus:
                sortie[(k.code, o.id)] = a
                break
            a = a.parent
    return sortie


def role_sur(utilisateur, kpi, org):
    """« admin », « validateur », « contributeur » ou None si la cellule est hors périmètre.
    Au-dessus de la granularité (saisie aux niveaux supérieurs) : l'admin et les validateurs de l'organisation."""
    if utilisateur.est_admin:
        return "admin"
    if utilisateur.lecture_seule:  # lecteur, auditeur : voient, ne modifient rien
        permises = utilisateur.orgs_permises()
        return "lecture" if kpi.actif and org.actif and (permises is None or org.id in permises) else None
    if au_dessus(kpi, org) and kpi.actif and org.actif:
        return "validateur" if voit_calcules(utilisateur, org) else None
    if kpi.est_calcule or not kpi.actif or not org.actif or not kpi.se_saisit_a(org):
        return None
    ids = {org.id} | {a.id for a in org.ancetres()}
    roles = set(Attribution.objects.filter(utilisateur=utilisateur, kpi=kpi, organisation_id__in=ids).values_list("role", "organisation_id"))
    if any(r == Attribution.Role.VALIDATEUR for r, _ in roles):
        return "validateur"
    if (Attribution.Role.CONTRIBUTEUR, org.id) in roles:
        return "contributeur"
    return None


# ---------------------------------------------------------------- droits
@dataclass
class Droits:
    voir: bool = False
    modifier: bool = False
    repasser_brouillon: bool = False
    motif: str = ""
    lien: str = ""  # adresse proposée avec le motif (fiche de l'organisation, contenu du référentiel, pour un administrateur)
    lien_cle: str = "saisie.msg.modifier_ouverture"  # libellé du lien
    hors_periode: bool = False  # la case ne compte pas dans cette période (organisation pas ouverte, KPI pas demandé) : le panneau
    # le dit dans un encadré, sans statut « À saisir » ni point « À vérifier » quand rien n'y est enregistré


def voit_calcules(utilisateur, org):
    """Admin : partout. Lecteur, auditeur : dans leurs organisations consultées. Validateur : résultats des organisations
    qui lui sont attribuées et de leurs descendantes."""
    if utilisateur.voit_tout:
        permises = utilisateur.orgs_permises()
        return permises is None or org.id in permises
    ids = {org.id} | {a.id for a in org.ancetres()}
    return Attribution.objects.filter(utilisateur=utilisateur, role=Attribution.Role.VALIDATEUR, organisation_id__in=ids).exists()


def responsable_resultat(utilisateur, kpi, org):
    """Vrai si la personne est attribuée à ce KPI calculé dans cette organisation : elle voit le résultat et peut demander
    une valeur forcée (collecte/forcage.py)."""
    return Attribution.objects.filter(utilisateur=utilisateur, kpi=kpi, organisation=org, role=Attribution.Role.CONTRIBUTEUR).exists()


def resultats_responsable(utilisateur, campagne):
    """[(KPI, organisation)] des KPI calculés de la campagne dont la personne est responsable du résultat (attribution
    sur un KPI calculé), organisations actives : ils ne sont pas à saisir, mais elle peut y demander une valeur forcée."""
    paires, arbres, partiels = [], {}, None
    for a in (Attribution.objects.filter(utilisateur=utilisateur, role=Attribution.Role.CONTRIBUTEUR, kpi__actif=True,
                                         kpi__type_saisie__comportement="calcul", organisation__actif=True)
              .select_related("kpi__type_saisie", "kpi__type_reponse", "kpi__unite", "organisation__niveau")):
        from .calcul import arbre_ouverture, figes_partiels, ouverte

        # pas encore ouverte pendant la période (date d'ouverture ; ni son parent ; ni absente de l'arbre
        # de l'époque d'un exercice clos, ou du jour où le KPI a été figé par une campagne clôturée) : rien à suivre
        if partiels is None:
            partiels = figes_partiels(campagne.periode) or {"kpis": {}}
        cle = partiels["kpis"].get(a.kpi_id)
        if cle not in arbres:
            arbres[cle] = arbre_ouverture(campagne.periode, None if cle is None else a.kpi_id)
        arbre = arbres[cle]
        o = arbre.get(a.organisation_id)
        if dans_la_campagne(campagne, a.kpi) and o is not None and ouverte(o, campagne.periode, arbre):
            paires.append((a.kpi, a.organisation))
    return paires


def est_calculee(kpi, org, reponse=None, campagne=None, rangs=None):
    """Vrai si la cellule n'est pas saisissable : KPI calculé, organisation au-dessus de la granularité (agrégat), ou
    valeur obtenue à partir de périodes plus courtes dans cette campagne (cumul). Exceptions : au-dessus de la
    granularité d'un KPI qui accepte la saisie aux niveaux supérieurs, la cellule se saisit (hors cumul) ; sous la
    granularité, un paramètre hérité se saisit dans l'organisation qui le porte faute d'ancêtre de son niveau (CALC-09).
    ``rangs`` : {code du niveau : rang}, s'il est déjà lu."""
    if au_dessus(kpi, org, rangs):
        return campagne is not None and cumule(campagne, kpi)
    return (kpi.est_calcule or not kpi.se_saisit_a(org, rangs) or bool(reponse and reponse.est_calculee)
            or (campagne is not None and cumule(campagne, kpi)))


def facultatifs(campagne):
    """Codes des KPI facultatifs dans le référentiel de la campagne (élément non obligatoire) : la case reste visible et
    saisissable, mais elle ne compte nulle part (taux de remplissage, retards, ce qui reste à faire, relances, cases
    restant à saisir, rapport de revue). Lu une fois par objet campagne."""
    if not hasattr(campagne, "_facultatifs"):
        campagne._facultatifs = set(ElementReferentiel.objects.filter(referentiel_id=campagne.referentiel_id, obligatoire=False)
                                    .values_list("kpi_id", flat=True))
    return campagne._facultatifs


def facultatif_partout(campagnes, kpi):
    """Vrai si le KPI n'est attendu dans aucune de ces campagnes (de la même période) : facultatif dans chaque référentiel
    qui le collecte (exports : une case par période, quel que soit le nombre de référentiels)."""
    concernees = [c for c in campagnes if dans_la_campagne(c, kpi)]
    return bool(concernees) and all(kpi.code in facultatifs(c) for c in concernees)


def dans_la_campagne(campagne, kpi):
    """Le KPI fait partie de ce que collecte la campagne : son référentiel ou les sources de ses formules (tout le
    catalogue si aucun référentiel ne contient de KPI). Calculé une fois par objet campagne."""
    if not hasattr(campagne, "_perimetre_saisie"):
        codes = codes_campagne(campagne)
        campagne._perimetre_saisie = None if codes is None else codes[1]
    return campagne._perimetre_saisie is None or kpi.pk in campagne._perimetre_saisie


def motif_cloturee_ailleurs(campagne, kpi):
    """Motif de refus quand une AUTRE campagne clôturée de la même période collecte ce KPI (deux référentiels, un KPI
    commun) : la valeur est unique pour la période, la modifier changerait une campagne figée.
    Chaîne vide sinon. Les campagnes voisines clôturées sont lues une fois par objet campagne."""
    if not hasattr(campagne, "_voisines_cloturees"):
        campagne._voisines_cloturees = list(Campagne.objects.filter(
            periode_id=campagne.periode_id, statut=Campagne.Statut.CLOTUREE).exclude(pk=campagne.pk).select_related("referentiel", "periode"))
    for autre in campagne._voisines_cloturees:
        if dans_la_campagne(autre, kpi):
            return libelle("saisie.msg.kpi_commun_cloture", campagne=autre.libelle, referentiel=autre.referentiel.nom)
    return ""


def organisation_pas_ouverte(utilisateur, campagne, org, valeur=False):
    """(motif, lien) quand l'organisation n'est pas ouverte pendant la période de la campagne (date d'ouverture, la
    sienne ou celle d'un ancêtre, après la période : ``calcul.ouverte``) ; ("", "") sinon. Règle du projet : l'écriture est refusée partout (écran, import, assistants) ; le motif dit pourquoi et propose à un
    administrateur de modifier la date d'ouverture (lien vers la fiche de l'organisation qui la porte), aux autres
    rôles de s'adresser à un administrateur. L'arbre est lu une fois par objet campagne (import : une ligne par case).

    Exercice clos ou rouvert en gardant les chiffres de l'époque : l'arbre de sa clôture. Une
    organisation qui n'y est pas (créée depuis la clôture) n'a pas de case dans cette période : motif dédié (sans lien :
    aucune date ne la ferait entrer dans l'arbre de l'époque).

    ``valeur`` : la case garde une valeur enregistrée (date posée après coup) : le motif dit qu'elle ne compte dans aucun
    total, au lieu de « rien à saisir »."""
    from .calcul import appliquer_arbre, arbre_ouverture, arbre_suivi, ouverture_effective, ouverte

    periode = campagne.periode if campagne.periode_id else getattr(campagne, "periode_a_creer", None)
    if not hasattr(campagne, "_arbre_ouverture"):
        fige = arbre_suivi(periode) if campagne.periode_id else None
        campagne._arbre_ouverture = arbre_ouverture() if fige is None else appliquer_arbre(fige, arbre_ouverture())
        campagne._ids_epoque = None if fige is None else {e[0] for e in fige["o"]}
    arbre = campagne._arbre_ouverture
    if campagne._ids_epoque is not None and org.pk not in campagne._ids_epoque:
        return libelle("saisie.msg.org_absente_arbre", organisation=org.nom, periode=str(campagne.periode)), ""
    o = arbre.get(org.pk)
    if o is None or periode is None or ouverte(o, periode, arbre):
        return "", ""
    date, porteuse = ouverture_effective(o, arbre)
    if date is None:
        # fermée : désactivée sans date de désactivation, ou avant le début de la période (``calcul.ouverte``). Même
        # règle qu'une organisation pas encore ouverte : avant, l'import, le serveur MCP et la
        # case ouverte par son adresse y écrivaient une valeur qui ne comptait dans aucun total
        valeurs = {"organisation": org.nom, "periode": str(campagne.periode) if campagne.periode_id else periode.libelle}
        if utilisateur.est_admin:
            from django.urls import reverse

            return libelle("saisie.msg.org_fermee_admin", **valeurs), reverse("collecte:admin_organisation", args=[org.pk])
        return libelle("saisie.msg.org_fermee", **valeurs), ""
    nom = Organisation.objects.filter(pk=porteuse.pk).values_list("nom", flat=True).first() or org.nom
    valeurs = {"organisation": nom, "date": DC.date_courte(date),
               "periode": str(campagne.periode) if campagne.periode_id else periode.libelle}
    cle = "saisie.msg.org_pas_ouverte_valeur" if valeur else "saisie.msg.org_pas_ouverte"
    if utilisateur.est_admin:
        from django.urls import reverse

        return libelle(cle + "_admin", **valeurs), reverse("collecte:admin_organisation", args=[porteuse.pk])
    return libelle(cle, **valeurs), ""


def a_une_valeur(reponse):
    """Vrai si la réponse porte quelque chose : une valeur, un texte ou un N/A (pas un simple commentaire)."""
    return reponse is not None and (reponse.valeur is not None or bool(reponse.texte) or reponse.non_applicable)


def motif_pas_demande(utilisateur, campagne, kpi):
    """(motif, lien) quand le référentiel de la campagne contient le KPI mais ne le demande pas dans cette période
    (« demandé depuis » plus tard, ou hors du périmètre noté à la clôture) ; ("", "") sinon (KPI d'aucun élément du
    référentiel : motif ``kpi_hors_referentiel``). Même forme que ``organisation_pas_ouverte`` : le motif dit pourquoi
    (avec « demandé depuis » quand c'est le cas) et propose à un administrateur d'ouvrir le contenu du référentiel, aux
    autres rôles de s'adresser à un administrateur. Seulement pour une campagne enregistrée (import : période à créer)."""
    if not campagne.pk or not campagne.periode_id:
        return "", ""
    element = ElementReferentiel.objects.filter(referentiel_id=campagne.referentiel_id, kpi=kpi).first()
    if element is None:
        return "", ""
    from .demande_depuis import libelle_depuis

    periode = campagne.periode
    valeurs = {"kpi": kpi.nom, "periode": str(periode), "referentiel": campagne.referentiel.nom}
    suffixe = "_admin" if utilisateur.est_admin else ""
    if element.demande_depuis is not None and element.demande_depuis > periode.debut:
        cle = "saisie.msg.kpi_pas_demande_depuis"
        valeurs["depuis"] = libelle_depuis(campagne.referentiel, element.demande_depuis)
    else:
        cle = "saisie.msg.kpi_pas_demande"
    lien = ""
    if utilisateur.est_admin:
        from django.urls import reverse

        lien = reverse("parametres:referentiel_contenu", args=[campagne.referentiel.code])
    return libelle(cle + suffixe, **valeurs), lien


def droits(utilisateur, campagne, kpi, org, reponse=None):
    if not dans_la_campagne(campagne, kpi):  # adresse forgée : pas de valeur hors du référentiel de la campagne
        motif, lien = motif_pas_demande(utilisateur, campagne, kpi)
        # pas demandé dans cette période : la personne qui a un rôle sur la case lit la raison (rien à modifier) ; les
        # autres, comme pour toute case hors de leur périmètre
        if motif and (voit_calcules(utilisateur, org) or role_sur(utilisateur, kpi, org) is not None):
            return Droits(voir=True, motif=motif, lien=lien, lien_cle="saisie.msg.ouvrir_contenu_referentiel", hors_periode=True)
        return Droits(motif=libelle("saisie.msg.kpi_hors_referentiel"))
    if est_calculee(kpi, org, reponse, campagne):
        if voit_calcules(utilisateur, org) or (kpi.est_calcule and responsable_resultat(utilisateur, kpi, org)):
            if not kpi.est_calcule and kpi.se_saisit_a(org) and cumule(campagne, kpi):
                return Droits(voir=True, motif=libelle("saisie.msg.valeur_cumul"))
            return Droits(voir=True, motif=libelle("saisie.msg.valeur_calculee"))
        return Droits(motif=libelle("saisie.msg.hors_perimetre"))
    role = role_sur(utilisateur, kpi, org)
    if role is None:
        return Droits(motif=libelle("saisie.msg.hors_perimetre"))
    if role == "lecture":
        return Droits(voir=True, motif=libelle("saisie.msg.lecture_seule"))
    if campagne.statut == Campagne.Statut.CLOTUREE:  # clôture définitive : figée, même pour l'admin
        return Droits(voir=True, motif=campagne.motif_lecture_seule)
    autre = motif_cloturee_ailleurs(campagne, kpi)  # valeur commune à une campagne clôturée de la période : figée aussi ici
    if autre:
        return Droits(voir=True, motif=autre)
    pas_ouverte, lien = organisation_pas_ouverte(utilisateur, campagne, org, valeur=a_une_valeur(reponse))
    if pas_ouverte:  # pas encore ouverte pendant la période : la valeur ne compterait nulle part 
        return Droits(voir=True, motif=pas_ouverte, lien=lien, hors_periode=True)
    if role == "admin":
        return Droits(voir=True, modifier=True, repasser_brouillon=True)
    ouverte = campagne.saisie_ouverte()
    motif = "" if ouverte else campagne.motif_lecture_seule
    return Droits(voir=True, modifier=ouverte, repasser_brouillon=ouverte or role == "validateur", motif=motif)


def exiger(d, attribut):
    if not getattr(d, attribut):
        raise PermissionDenied(d.motif or libelle("saisie.msg.action_non_autorisee"))


# ---------------------------------------------------------------- lecture
def reponse_de(campagne, kpi, org):
    return Reponse.objects.filter(periode=campagne.periode, kpi=kpi, organisation=org).first()


def periode_comparaison(campagne):
    """Période de référence de l'écart : la période précédente ou la même période l'an dernier (réglage du référentiel).
    Pour une campagne annuelle, c'est toujours l'exercice précédent. None si elle n'existe pas."""
    from referentiel.models import MOIS_PAR_FREQUENCE

    from .models import Periode
    from .periodes import ajouter_mois

    if not hasattr(campagne, "_comparaison"):
        p = campagne.periode
        mois = MOIS_PAR_FREQUENCE[p.type] if campagne.referentiel.comparaison == Referentiel.Comparaison.P1 else 12
        campagne._comparaison = Periode.objects.filter(type=p.type, debut=ajouter_mois(p.debut, -mois)).first()
    return campagne._comparaison


def cases_comparables(periode, paires):
    """Couples (KPI, organisation) de ``paires`` dont la valeur de ``periode`` peut servir de comparaison (N-1, période
    précédente, années passées de la page Cohérence). Seule règle, pour tout ce qui lit une valeur d'une autre période
    pour l'afficher ou la comparer : grille de saisie, panneau d'une case, contrôle d'écart
    à la validation, imports, fichier à remplir, exports avec la colonne N-1, page Cohérence et ses alertes, serveur
    MCP. Une valeur gardée dans la période comparée n'y compte pas quand :

    - l'organisation n'y était pas ouverte, dans l'arbre de cette période (``calcul.ouverte``, ``calcul.arbre_ouverture``
      : celui de sa clôture pour un exercice clos ou rouvert « garder ») ; c'est la règle du calcul (``Calculateur
      .lisible`` : rien ne se lit dans une période où l'organisation n'est pas ouverte) ; avant, une date d'ouverture
      posée après coup laissait la valeur d'avant bloquer la validation (« l'écart avec N-1 dépasse 20 % ») et créer
      une alerte « +900 % » ;
    - le KPI est hors du périmètre noté à la clôture de cette période (``calcul.perimetre_gele`` : aucune case n'y est
      offerte ni calculée pour lui).
    La date « demandé depuis » seule ne retire pas la comparaison : une valeur saisie ou reprise dans une période qui
    ne demandait pas encore le KPI reste lue par le calcul ([X@N-1]) et montrée en N-1 (test existant
    ``test_texte_redige.test_reponse_n1_en_repere`` : KPI ajouté avec la date par défaut, l'exercice en cours, et
    valeur 2025 reprise) ; à trancher.
    Les totaux de la Visualisation et de la Consolidation suivent déjà ``ouverte`` (``visualisation.Source.present``)."""
    if periode is None or not paires:
        return set()
    from .calcul import arbre_ouverture, figes_partiels, ouverte, perimetre_gele

    partiels = figes_partiels(periode) or {"kpis": {}}  # KPI figés par une campagne clôturée : leur arbre
    arbres = {}
    gele = perimetre_gele(periode)
    ouvertes = {}

    def demande(k):
        return gele is None or k in gele

    def ouverte_(k, o):
        a = partiels["kpis"].get(k)
        if a not in arbres:
            arbres[a] = arbre_ouverture(periode, None if a is None else k)
        arbre = arbres[a]
        if (a, o) not in ouvertes:
            ouvertes[(a, o)] = o in arbre and ouverte(arbre[o], periode, arbre)
        return ouvertes[(a, o)]

    codes = {k for k, _ in paires}
    gardes = {k for k in codes if demande(k)}
    return {(k, o) for k, o in paires if k in gardes and ouverte_(k, o)}


def valeurs_n1(campagne, paires):
    """{(kpi_id, org_id): Reponse} de la période de comparaison (N-1 ou période précédente), pour les seules cases
    comparables (``cases_comparables``)."""
    prec = periode_comparaison(campagne)
    if prec is None:
        return {}
    kpi_ids = {k for k, _ in paires}
    org_ids = {o for _, o in paires}  # pré-filtre : seulement les organisations affichées (le filtre exact reste ci-dessous)
    qs = Reponse.objects.filter(periode=prec, kpi_id__in=kpi_ids, organisation_id__in=org_ids)
    trouvees = {(r.kpi_id, r.organisation_id): r for r in qs if (r.kpi_id, r.organisation_id) in paires}
    comparables = cases_comparables(prec, set(trouvees))
    return {cle: r for cle, r in trouvees.items() if cle in comparables}


def reponse_n1(campagne, kpi, org):
    """Réponse de la période de comparaison pour une case, ou None (pas de période, pas de réponse, ou case non
    comparable : ``cases_comparables``). Panneau, contrôle d'écart, serveur MCP."""
    cle = (kpi.code, org.id)
    return valeurs_n1(campagne, {cle}).get(cle)


def ecart(valeur, n1):
    """Écart relatif avec N-1 (fraction), ou None si non calculable."""
    if valeur is None or n1 is None or n1 == 0:
        return None
    return (valeur - n1) / abs(n1)


def depasse_seuil(e, seuil):
    """Vrai si l'écart ``e`` (fraction, ``ecart``) va au-delà du seuil de la campagne, en valeur absolue ; jamais sans
    écart ni sans seuil. Règle commune à la saisie, la page Cohérence, l'import, les exports et l'affichage."""
    return e is not None and seuil is not None and abs(e) > seuil


def ecart_justifie(reponse):
    """Vrai si le commentaire de la réponse justifie son écart : un commentaire vide ou fait seulement d'espaces ne le
    justifie pas (même règle pour la saisie et la page Cohérence)."""
    return bool((reponse.commentaire or "").strip())


def historique(kpi, org):
    """Réponses de toutes les périodes, de la plus récente à la plus ancienne."""
    return Reponse.objects.filter(kpi=kpi, organisation=org).select_related("periode", "saisi_par").order_by("-periode__debut", "periode__fin")


def campagnes_de(periode, kpi_id, en_cours=False):
    """Campagnes de la période dont le périmètre contient le KPI (par ordre des référentiels)."""
    return campagnes_des(periode, [kpi_id], en_cours)


def campagnes_des(periode, kpi_ids, en_cours=False):
    """Campagnes de la période dont le périmètre contient au moins un des KPI (par ordre des référentiels), le
    périmètre de chaque campagne n'étant calculé qu'une fois (fin d'import : des centaines de KPI touchés)."""
    qs = Campagne.objects.filter(periode=periode).select_related("referentiel", "periode")
    if en_cours:
        qs = qs.filter(statut__in=[Campagne.Statut.OUVERTE, Campagne.Statut.REVUE])
    kpi_ids = set(kpi_ids)
    sortie = []
    for c in qs:
        codes = codes_campagne(c)
        if codes is None or kpi_ids & codes[1]:
            sortie.append(c)
    return sortie


def campagne_de(reponse):
    """Campagne où l'on voit la réponse : la première de sa période qui contient le KPI, sinon la première de la période."""
    return next(iter(campagnes_de(reponse.periode, reponse.kpi_id)), None) or Campagne.objects.filter(periode=reponse.periode).first()


def statut_affiche(reponse):
    return reponse.statut if reponse else Reponse.Statut.A_SAISIR


# ---------------------------------------------------------------- saisie
def version(reponse):
    """Repère de la réponse telle qu'elle est affichée (date de dernière mise à jour) : sert à détecter qu'une autre
    personne l'a modifiée entre l'ouverture de la case et l'enregistrement."""
    return reponse.date_maj.isoformat() if reponse is not None and reponse.pk else ""


def reponse_verrouillee(campagne, kpi, org):
    """Réponse de la case, créée au besoin, verrouillée jusqu'à la fin de la transaction : deux enregistrements simultanés
    de la même case passent l'un après l'autre (le second devient une mise à jour, jamais une erreur). Renvoie
    (réponse, créée)."""
    reponse, creee = Reponse.objects.get_or_create(periode=campagne.periode, kpi=kpi, organisation=org,
                                                   defaults={"statut": Reponse.Statut.A_SAISIR})
    return Reponse.objects.select_for_update().get(pk=reponse.pk), creee


def debut_conflit():
    """Début du message de conflit de version (reconnu par le panneau : le message le reprend, paramètre {debut})."""
    return libelle("saisie.msg.conflit_debut")


def verifier_version(reponse, attendue, creee=False):
    """Refuse d'écraser une saisie faite par quelqu'un d'autre depuis l'ouverture de la case (``attendue`` : version
    affichée ; None : pas de contrôle, ex. import ou action technique)."""
    if attendue is None or reponse.est_calculee or (creee and not attendue):
        return
    if version(reponse) == attendue or (not attendue and reponse.valeur is None and not reponse.texte
                                         and not reponse.non_applicable and not reponse.commentaire):
        return
    qui = reponse.saisi_par or libelle("saisie.msg.autre_personne")
    texte = reponse.texte
    if texte and reponse.kpi.est_texte:  # réponse rédigée : son début seulement, en texte brut
        from .markdown import extrait

        texte = extrait(texte)
    valeur = "N/A" if reponse.non_applicable else (texte or (valeur_pour_saisie(reponse, reponse.kpi) or libelle("saisie.msg.vide")))
    quand = timezone.localtime(reponse.date_maj)
    raise ValidationError(libelle("saisie.msg.conflit", debut=debut_conflit(), qui=qui, date=DC.date_courte(quand), heure=f"{quand:%H:%M}",
                                  valeur=valeur))


def lire_reponse(texte, kpi):
    """(valeur, texte) d'une saisie : nombre pour un KPI numérique ; pour un oui / non ou une liste, la valeur de référence
    (stockée) d'une réponse écrite dans n'importe quelle langue de l'installation ; pour un texte rédigé, le texte (Markdown)
    tel qu'il est écrit, limité à ``markdown.TEXTE_MAX`` caractères ; pour un tableau, le tableau vérifié et normalisé."""
    if kpi.est_numerique:
        return lire_nombre(texte, kpi), ""
    if kpi.est_tableau:  # tableau : vérifié colonne par colonne, enregistré en tableau Markdown (collecte/tableaux.py)
        from . import tableaux

        return None, tableaux.lire(lire_texte_redige(texte), kpi.type_reponse)
    if kpi.est_texte:
        return None, lire_texte_redige(texte)
    t = (texte or "").strip()
    if not t:
        return None, ""
    cle = L.cle_valeur(kpi.type_reponse, kpi.choix, t)
    if cle:
        return None, cle
    affiches = [a for _, a in kpi.choix_traduits()]
    if kpi.format == "oui_non":  # « oui » et « non » de chaque langue de l'interface (``fichiers.oui_non``)
        from .fichiers import oui_non

        lu = oui_non(t)
        if lu is not None:
            return None, "Oui" if lu else "Non"
        raise ValidationError(libelle("saisie.msg.repondre_oui_non", oui=affiches[0], non=affiches[1]))
    raise ValidationError(libelle("saisie.msg.choisir_valeur", valeurs=", ".join(affiches)))


def lire_texte_redige(texte):
    """Réponse rédigée enregistrée (retours à la ligne gardés, caractères de contrôle retirés) ; refus clair au-delà de
    ``markdown.TEXTE_MAX`` caractères (rien n'est coupé en silence)."""
    from . import markdown as MD
    from .templatetags.collecte import nombre

    t = MD.normaliser(texte if isinstance(texte, str) else "" if texte is None else str(texte))
    if len(t) > MD.TEXTE_MAX:
        raise ValidationError(libelle("saisie.msg.texte_trop_long", max=nombre(MD.TEXTE_MAX, 0), n=nombre(len(t), 0)))
    return t


def motif_signe_pourcent(kpi):
    """Refus d'un « % » écrit pour un KPI qui n'est pas un pourcentage (il serait lu comme un simple nombre)."""
    unite = kpi.symbole if kpi.unite_id else ""
    return libelle("saisie.msg.pas_pourcentage_unite", unite=unite) if unite else libelle("saisie.msg.pas_pourcentage")


# Langue des nombres écrits en texte d'un fichier importé (``nombres_lus_en``) : pendant la lecture d'une ligne, elle
# remplace la langue de l'écran, pour toutes les lectures de nombres (cellule « Valeur », colonnes d'un tableau)
_langue_nombres = threading.local()


def langue_ecran():
    """Langue dans laquelle se lit un nombre tapé à l'écran (``langues.saisie``) : aussi celle d'un fichier importé dont
    l'en-tête « Valeur » ne dit pas la langue (``imports.langue_des_nombres``)."""
    return L.saisie()


@contextmanager
def nombres_lus_en(langue):
    """Pendant le bloc, ``texte_nombre`` sans langue donnée lit les nombres dans ``langue`` (la langue d'un fichier
    importé, ``imports.langue_des_nombres``) ; None : la règle de l'écran (``langues.saisie``)."""
    avant = getattr(_langue_nombres, "code", None)
    _langue_nombres.code = langue
    try:
        yield
    finally:
        _langue_nombres.code = avant


def texte_nombre(texte, langue=None):
    """Saisie d'un nombre ramenée à l'écriture « 1234.5 », dans toutes les langues : espaces
    tolérés ; virgule ou point décimal acceptés ; avec les deux, le dernier est la décimale (1,234.5 · 1.234,5) ; un
    séparateur répété est celui des milliers (1.234.567 · 1,234,567) ; en anglais, « 1,234 » se lit mille deux cent
    trente-quatre (virgule des milliers), ailleurs 1,234 (virgule décimale). Un groupe de milliers commence par un
    chiffre de 1 à 9, comme dans la règle du séparateur ambigu : « 0,205 » est toujours zéro virgule deux cent cinq (lu
    205 en anglais auparavant, en silence) ; « 0,205,123 » et « 0,205.5 » ne sont pas des nombres. Même lecture dans le
    navigateur (``lireNombre``, _app/01_socle.js). Langue : ``langue``, sinon celle du fichier en cours d'import
    (``nombres_lus_en``), sinon celle dans laquelle le formulaire envoyé a été affiché (``langues.saisie``), sinon celle
    de l'interface. C'est aussi la lecture d'un nombre écrit en texte dans un fichier importé (``fichiers.lire_nombre_importe``)."""
    import re

    from collecte.templatetags.collecte import separateurs

    langue = langue or getattr(_langue_nombres, "code", None) or L.saisie()
    t = re.sub(r"[\s\u00a0\u202f\u2009']", "", texte or "")
    if "," in t and "." in t:
        mille = "," if t.rfind(".") > t.rfind(",") else "."
        if not re.match(r"[-+]?0\d*" + re.escape(mille), t):  # « 0,205.5 » : groupe de milliers après un zéro, pas un nombre
            t = t.replace(mille, "")
    elif (t.count(",") > 1 or t.count(".") > 1) and re.fullmatch(r"[-+]?[1-9]\d{0,2}([.,]\d{3})+%?", t):
        t = t.replace(",", "").replace(".", "")
    elif "," in t and separateurs(langue)[1] == "." and re.fullmatch(r"[-+]?[1-9]\d{0,2},\d{3}%?", t):
        t = t.replace(",", "")
    return t.replace(",", ".")


# Séparateur ambigu : un seul séparateur, virgule ou point, suivi d'exactement 3 chiffres, après une
# partie entière de 1 à 3 chiffres non nulle (« 1,234 », « 12.500 » ; pas « 0,125 », « 1,23 », « 1 234,5 », « 1,234.5 »).
# Mille deux cent trente-quatre, ou un virgule deux cent trente-quatre ? Le panneau de saisie pose la question avant
# d'enregistrer (même règle dans _app/03_envoi.js, ``separateurAmbigu``) ; l'aperçu d'un import le signale. La lecture, elle, ne
# change pas (texte_nombre, fichiers.lire_decimal).
SEPARATEUR_AMBIGU = re.compile(r"[-+]?[1-9]\d{0,2}[.,]\d{3}")


def separateur_ambigu(texte):
    """Vrai pour un texte saisi dont le séparateur peut se lire milliers ou décimale (``SEPARATEUR_AMBIGU``). Un nombre
    (cellule numérique d'Excel) n'est jamais ambigu."""
    return isinstance(texte, str) and bool(SEPARATEUR_AMBIGU.fullmatch(texte.strip()))


def lectures_ambigues(texte, langue=None):
    """Les deux lectures d'une saisie ambiguë, écrites comme la langue affiche les nombres : (milliers, décimale), par
    exemple « 1,234 » → (« 1 234 », « 1,234 ») en français, (« 1,234 », « 1.234 ») en anglais. None si non ambiguë."""
    if not separateur_ambigu(texte):
        return None
    t = texte.strip()
    signe = "-" if t.startswith("-") else ""
    entier, decimales = re.split(r"[.,]", t.lstrip("+-"))
    from .templatetags.collecte import nombre

    return (signe + nombre(Decimal(entier + decimales), 0, langue), signe + nombre(Decimal(f"{entier}.{decimales}"), 3, langue))


COMMENTAIRE_MAX = 5_000  # caractères d'un commentaire (vérifié au serveur : saisie, imports)
NOMBRE_SAISI = re.compile(r"[-+]?(\d+(\.\d*)?|\.\d+)", re.ASCII)


def lire_nombre(texte, kpi, bornes=True):
    """Convertit la saisie (virgule ou point, espaces tolérés). Pourcentage saisi entre 0 et 100, stocké en fraction.
    ``bornes=False`` : pas de borne 0 à 100 (valeur forcée d'un pourcentage calculé, une évolution peut valoir -12 % ou 150 %).
    Seule l'écriture usuelle d'un nombre est lue (pas « 1e3 », « 1_000 », ni chiffres d'un autre alphabet) ; la valeur est
    arrondie à ce que la base garde, pour que la même saisie renvoyée ne soit pas vue comme un changement."""
    texte = texte_nombre((texte or "").strip())
    if texte.endswith("%"):
        texte = texte[:-1]
        if texte and not kpi.est_pourcentage:
            raise ValidationError(motif_signe_pourcent(kpi))
    if not texte:
        return None
    if not NOMBRE_SAISI.fullmatch(texte) or len(texte) > 60:
        raise ValidationError(libelle("saisie.msg.nombre_attendu"))
    try:
        v = Decimal(texte)
    except InvalidOperation:
        raise ValidationError(libelle("saisie.msg.nombre_attendu"))
    if not v.is_finite():
        raise ValidationError(libelle("saisie.msg.nombre_attendu"))
    if abs(v) >= VALEUR_MAX:  # au-delà, la base ne garde plus le nombre exactement : refus clair plutôt qu'une erreur 500
        raise ValidationError(libelle("saisie.msg.nombre_trop_grand"))
    if kpi.est_entier and v != v.to_integral_value():  # comptage : pas de décimale 
        raise ValidationError(libelle("saisie.msg.entier_attendu", unite=kpi.symbole))
    if kpi.est_pourcentage:
        if bornes and not 0 <= v <= 100:
            raise ValidationError(libelle("saisie.msg.pourcentage_bornes"))
        v = v / CENT
    if v.as_tuple().exponent < DECIMALES_GARDEES.as_tuple().exponent:  # plus de décimales que la base n'en garde
        v = valeur_enregistree(v)
    return v + 0  # « + 0 » : pas de « -0 »


def valeur_pour_saisie(reponse, kpi, langue=None):
    """Valeur stockée présentée dans le champ de saisie (pourcentage en 0-100 ; texte d'un oui / non ou d'une liste),
    avec la décimale de ``langue`` (par défaut, la langue de l'interface)."""
    if reponse is not None and not kpi.est_numerique:
        return reponse.texte
    if reponse is None or reponse.valeur is None:
        return ""
    v = reponse.valeur * CENT if kpi.est_pourcentage else reponse.valeur
    v = v.normalize()
    from collecte.templatetags.collecte import separateurs

    return format(v, "f").replace(".", separateurs(langue)[1])  # décimale de la langue, sans séparateur de milliers


def _journaliser(utilisateur, reponse, avant):
    for champ in CHAMPS_SUIVIS:
        a, b = avant.get(champ), getattr(reponse, champ)
        if a != b:
            Journal.ecrire(utilisateur, "creation" if not avant else "modification", reponse, champ, a, b)


def _etat(reponse):
    return {c: getattr(reponse, c) for c in CHAMPS_SUIVIS} if reponse.pk else {}


@ESP.atomic
def enregistrer(utilisateur, campagne, kpi, org, valeur, non_applicable, commentaire, version_vue=None, auto=False):
    """Enregistre en brouillon. Une réponse validée modifiée repasse en brouillon (section 5.1).
    ``version_vue`` : version de la réponse quand la case a été ouverte ; si quelqu'un l'a modifiée depuis, l'enregistrement
    est refusé (pas d'écrasement silencieux).
    ``auto`` : enregistrement automatique du panneau de saisie (brouillon tapé). Mêmes contrôles et
    même journal (une ligne par champ réellement changé, rien si rien n'a changé ; le journal ne fait que grandir) ; en plus,
    une valeur validée n'est jamais modifiée ainsi (elle ne repasse en brouillon que sur « Enregistrer la modification »)."""
    reponse = reponse_de(campagne, kpi, org)
    exiger(droits(utilisateur, campagne, kpi, org, reponse), "modifier")
    if non_applicable and not (reponse is not None and reponse.non_applicable):  # un N/A déjà posé reste modifiable (commentaire)
        from parametres.models import Instance

        if not Instance.courante().peut_repondre_na(utilisateur):
            raise ValidationError(libelle("saisie.msg.na_interdit"))
    valeur, texte = (None, "") if non_applicable else lire_reponse(valeur, kpi)
    commentaire = sans_controle(commentaire or "").strip()  # un caractère de contrôle collé ne passe pas (exports Excel)
    if len(commentaire) > COMMENTAIRE_MAX and commentaire != (reponse.commentaire if reponse is not None else ""):
        from .templatetags.collecte import nombre

        raise ValidationError(libelle("saisie.msg.commentaire_trop_long", max=nombre(COMMENTAIRE_MAX, 0), n=nombre(len(commentaire), 0)))
    if reponse is not None:
        reponse = Reponse.objects.select_for_update().get(pk=reponse.pk)
        verifier_version(reponse, version_vue)
        if auto and reponse.statut == Reponse.Statut.VALIDE:
            raise ValidationError(libelle("saisie.auto.valide"))
    if reponse is not None and reponse.est_calculee:  # total calculé au-dessus de la granularité : rien n'est encore saisi ici
        if valeur is None and not texte and not non_applicable and not commentaire:
            return reponse
    if reponse is None:
        if valeur is None and not texte and not non_applicable and not commentaire:
            return Reponse(periode=campagne.periode, kpi=kpi, organisation=org, statut=Reponse.Statut.A_SAISIR)  # rien à enregistrer
        reponse, creee = reponse_verrouillee(campagne, kpi, org)  # créée par quelqu'un d'autre à la même seconde : mise à jour
        verifier_version(reponse, version_vue, creee)
        avant = {} if creee else _etat(reponse)
    else:
        avant = _etat(reponse)
    change = not avant or (avant["valeur"], avant["texte"], avant["non_applicable"], avant["commentaire"]) != (
        valeur, texte, non_applicable, commentaire)
    if not change:
        return reponse
    reponse.valeur, reponse.texte, reponse.non_applicable, reponse.commentaire = valeur, texte, non_applicable, commentaire
    reponse.origine = Reponse.Origine.SAISIE
    reponse.saisi_par = utilisateur
    reponse.message_calcul = ""
    if valeur is None and not texte and not non_applicable:
        reponse.statut = Reponse.Statut.A_SAISIR
    else:
        reponse.statut = Reponse.Statut.BROUILLON
    reponse.valide_par, reponse.date_validation = None, None
    reponse.save()
    _journaliser(utilisateur, reponse, avant)
    return reponse


def controles_validation(reponse, campagne, n1=None, caches=frozenset()):
    """Liste des motifs qui empêchent de valider (vide si la validation est possible). ``caches`` : KPI dont la valeur
    ne doit pas sortir (``coherence.regles_bloquantes_en_echec``)."""
    kpi = reponse.kpi
    motifs = []
    if reponse.valeur is None and not reponse.texte and not reponse.non_applicable:
        motifs.append(libelle("saisie.msg.saisir_ou_na"))
    if reponse.non_applicable and not ecart_justifie(reponse):  # vide ou espaces : pas de commentaire
        motifs.append(libelle("saisie.msg.commentaire_na"))
    if kpi.preuve_obligatoire and not reponse.non_applicable and not reponse.preuves.exists():
        motifs.append(libelle("saisie.msg.preuve_obligatoire"))
    if campagne.seuil_ecart is not None and kpi.est_numerique and not reponse.non_applicable and not ecart_justifie(reponse):
        if n1 is None:
            r1 = reponse_n1(campagne, kpi, reponse.organisation)  # case non comparable : pas d'écart (``cases_comparables``)
            n1 = r1.valeur if r1 and not r1.non_applicable else None
        if depasse_seuil(ecart(reponse.valeur, n1), campagne.seuil_ecart):
            motifs.append(libelle("saisie.msg.ecart_depasse", comparaison=libelle_comparaison(campagne),
                                  seuil=f"{campagne.seuil_ecart * CENT:.0f}"))
    if not reponse.non_applicable and reponse.valeur is not None:
        from .coherence import regles_bloquantes_en_echec

        motifs += regles_bloquantes_en_echec(campagne, kpi, reponse.organisation, caches)
    return motifs


@ESP.atomic
def valider(utilisateur, campagne, kpi, org, caches=frozenset()):
    """``caches`` : KPI dont la valeur ne doit pas sortir dans un motif de refus (serveur MCP, KPI sensibles)."""
    reponse = reponse_de(campagne, kpi, org)
    exiger(droits(utilisateur, campagne, kpi, org, reponse), "modifier")
    if reponse is None:
        raise ValidationError(libelle("saisie.msg.saisir_ou_na"))
    # verrouillée jusqu'à la fin : une saisie simultanée attend, la validation porte sur la valeur relue ici (PostgreSQL)
    reponse = Reponse.objects.select_for_update().get(pk=reponse.pk)
    if reponse.statut == Reponse.Statut.VALIDE:
        return reponse
    motifs = controles_validation(reponse, campagne, caches=caches)
    if motifs:
        raise ValidationError(motifs)
    avant = _etat(reponse)
    reponse.statut = Reponse.Statut.VALIDE
    reponse.valide_par, reponse.date_validation = utilisateur, timezone.now()
    reponse.save(update_fields=["statut", "valide_par", "date_validation", "date_maj"])
    _journaliser(utilisateur, reponse, avant)
    return reponse


@ESP.atomic
def repasser_brouillon(utilisateur, campagne, kpi, org):
    reponse = reponse_de(campagne, kpi, org)
    exiger(droits(utilisateur, campagne, kpi, org, reponse), "repasser_brouillon")
    if reponse is not None:
        reponse = Reponse.objects.select_for_update().get(pk=reponse.pk)
    if reponse is None or reponse.statut != Reponse.Statut.VALIDE:
        raise ValidationError(libelle("saisie.msg.seule_validee_brouillon"))
    avant = _etat(reponse)
    reponse.statut = Reponse.Statut.BROUILLON
    reponse.valide_par, reponse.date_validation = None, None
    reponse.save(update_fields=["statut", "valide_par", "date_validation", "date_maj"])
    _journaliser(utilisateur, reponse, avant)
    return reponse


@ESP.atomic
def remettre_a_saisir(utilisateur, campagne, kpi, org, version_vue=None):
    """Ramène une case au stade « à saisir » (demande) : la valeur, la réponse et le N/A sont effacés, le
    commentaire et les preuves restent ; une valeur validée perd sa validation. Même droit que modifier la valeur ; noté au
    journal ; les totaux et les calculs qui la citent sont refaits (signal après enregistrement)."""
    reponse = reponse_de(campagne, kpi, org)
    exiger(droits(utilisateur, campagne, kpi, org, reponse), "modifier")
    if reponse is not None:
        reponse = Reponse.objects.select_for_update().get(pk=reponse.pk)
        verifier_version(reponse, version_vue)
    if reponse is None or reponse.est_calculee or (reponse.valeur is None and not reponse.texte and not reponse.non_applicable):
        raise ValidationError(libelle("saisie.msg.rien_a_effacer"))
    avant = _etat(reponse)
    reponse.valeur, reponse.texte, reponse.non_applicable = None, "", False
    reponse.statut = Reponse.Statut.A_SAISIR
    reponse.origine = Reponse.Origine.SAISIE
    reponse.saisi_par = utilisateur
    reponse.valide_par, reponse.date_validation = None, None
    reponse.message_calcul = ""
    reponse.save()
    _journaliser(utilisateur, reponse, avant)
    return reponse


@ESP.atomic
def ajouter_preuve(utilisateur, campagne, kpi, org, fichier):
    reponse = reponse_de(campagne, kpi, org)
    exiger(droits(utilisateur, campagne, kpi, org, reponse), "modifier")
    valider_fichier(fichier)
    if reponse is not None:  # verrouillée : une validation simultanée ne passe pas à côté de la preuve ajoutée
        reponse = Reponse.objects.select_for_update().get(pk=reponse.pk)
    else:
        reponse, creee = reponse_verrouillee(campagne, kpi, org)
        if creee:
            reponse.origine, reponse.saisi_par = Reponse.Origine.SAISIE, utilisateur
            reponse.save(update_fields=["origine", "saisi_par", "date_maj"])
    preuve = Preuve(reponse=reponse, fichier=fichier, nom_fichier=fichier.name[:255], depose_par=utilisateur)
    try:
        preuve.save()
        Journal.ecrire(utilisateur, "depot_preuve", reponse, "preuve", "", preuve.nom_fichier)
        _apres_modification_preuves(utilisateur, reponse)
    except BaseException:  # base qui refuse l'écriture (disque plein…) : le fichier déjà écrit ne reste pas orphelin
        if preuve.fichier.name and preuve.fichier.storage.exists(preuve.fichier.name):
            preuve.fichier.storage.delete(preuve.fichier.name)
        raise
    return preuve


@ESP.atomic
def retirer_preuve(utilisateur, preuve, campagne=None):
    reponse = Reponse.objects.select_for_update().get(pk=preuve.reponse_id)
    campagne = campagne if campagne is not None and campagne.periode_id == reponse.periode_id else campagne_de(reponse)
    exiger(droits(utilisateur, campagne, reponse.kpi, reponse.organisation, reponse), "modifier")
    nom = preuve.nom_fichier
    chemin = preuve.fichier.path if preuve.fichier.name else None  # chemin figé : l'espace courant peut changer ensuite
    preuve.delete()
    # le fichier n'est effacé qu'une fois la suppression enregistrée : une base qui refuse l'écriture (disque plein,
    # arrêt brutal) garde la preuve avec son fichier
    if chemin:
        effacer = partial(Path(chemin).unlink, missing_ok=True)
        transaction.on_commit(effacer, using=ESP.alias_courant())
    Journal.ecrire(utilisateur, "retrait_preuve", reponse, "preuve", nom, "")
    _apres_modification_preuves(utilisateur, reponse)


def _apres_modification_preuves(utilisateur, reponse):
    """Toute modification d'une réponse validée la repasse en brouillon (section 5.1)."""
    if reponse.statut == Reponse.Statut.VALIDE:
        avant = _etat(reponse)
        reponse.statut = Reponse.Statut.BROUILLON
        reponse.valide_par, reponse.date_validation = None, None
        reponse.save(update_fields=["statut", "valide_par", "date_validation", "date_maj"])
        _journaliser(utilisateur, reponse, avant)


# ---------------------------------------------------------------- liste
@dataclass
class Ligne:
    kpi: KPI
    organisation: Organisation
    reponse: Reponse | None
    n1: Reponse | None
    statut: str = ""
    ecart: Decimal | None = None
    nb_preuves: int = 0
    spocs: list = field(default_factory=list)
    calculee: bool = False
    alertes: list = field(default_factory=list)
    au_dessus: bool = False  # saisie possible au-dessus de la granularité (facultative)
    couverte: Organisation | None = None  # valeur saisie à ce niveau supérieur : la cellule n'est plus attendue
    autres_refs: list = field(default_factory=list)  # autres référentiels collectés qui contiennent le KPI (valeur commune)
    facultatif: bool = False  # KPI facultatif dans le référentiel de la campagne : saisissable, jamais compté ni relancé

    @property
    def attendue(self):
        """Compte dans le taux de remplissage, les retards, ce qui reste à faire et les relances."""
        return not self.calculee and not self.au_dessus and self.couverte is None and not self.facultatif

    @property
    def saisie_ici(self):
        """Valeur saisie ou importée au-dessus de la granularité (elle remplace le total calculé)."""
        r = self.reponse
        return self.au_dessus and r is not None and not r.est_calculee and (r.valeur is not None or bool(r.texte) or r.non_applicable)

    @property
    def cle(self):
        return f"{self.kpi.code}|{self.organisation.id}"

    non_applicable: bool | None = None  # ligne légère (sans la réponse) : N/A lu en base ; None : lu sur la réponse

    @property
    def na(self):
        if self.non_applicable is not None:
            return self.non_applicable
        return bool(self.reponse and self.reponse.non_applicable)


def ordre(plan):
    """Clé de tri des lignes : place du KPI dans le plan (référentiel, thèmes, ordre), puis l'organisation. La place
    d'un KPI est lue une fois par KPI (100 000 lignes à trier pour 300 KPI)."""
    places = {}

    def cle(l):
        k = l.kpi
        p = places.get(k.code)
        if p is None:
            p = places[k.code] = plan.position(k.code, k.ordre)
        return p, l.organisation.rang, l.organisation.nom
    return cle


def construire_lignes(campagne, paires, calculees=(), plan=None, cases_visibles=None, legere=False):
    """Lignes avec réponse, N-1, écart, preuves et SPOC. ``calculees`` : paires en lecture seule.
    Alertes à traiter de chaque ligne : celles de sa case, et celles des règles entre KPI qui citent son KPI dans la
    même organisation. ``cases_visibles`` : {(KPI, organisation)} du périmètre de la personne (None : admin, tout est
    visible) ; une ligne ne montre que les alertes que la personne voit aussi sur la page Cohérence.
    ``legere`` : lignes pour compter seulement (``lignes_legeres``)."""
    if legere:
        return lignes_legeres(campagne, paires, calculees, plan)
    with sans_ramasse_miettes():  # des milliers d'objets qui restent en vie (Pour moi d'un validateur : 9 000 lignes, P-A9)
        return _construire_lignes(campagne, paires, calculees, plan, cases_visibles)


def _construire_lignes(campagne, paires, calculees, plan, cases_visibles):
    toutes = list(paires) + list(calculees)
    cles = {(k.code, o.id) for k, o in toutes}
    kpi_ids = {k for k, _ in cles}
    org_ids = {o for _, o in cles}  # pré-filtre : seulement les organisations affichées (le filtre exact reste ci-dessous)
    reponses = {}
    for r in Reponse.objects.filter(periode=campagne.periode, kpi_id__in=kpi_ids, organisation_id__in=org_ids).annotate(_nb_preuves=Count("preuves")):
        if (r.kpi_id, r.organisation_id) in cles:
            reponses[(r.kpi_id, r.organisation_id)] = r
    n1 = valeurs_n1(campagne, cles)
    spocs = {}
    for a in Attribution.objects.filter(kpi_id__in=kpi_ids, organisation_id__in=org_ids,
                                        role=Attribution.Role.CONTRIBUTEUR).select_related("utilisateur"):
        if (a.kpi_id, a.organisation_id) in cles and a.utilisateur.is_active and not a.utilisateur.lecture_seule:  # jamais SPOC
            spocs.setdefault((a.kpi_id, a.organisation_id), []).append(a.utilisateur)
    from .models import Alerte

    from .coherence import AVEC_KPI, visible

    alertes = {}
    qs = (Alerte.objects.filter(campagne=campagne, statut__in=Alerte.A_TRAITER).exclude(controle=Alerte.Controle.CALCUL).select_related(*AVEC_KPI)
          .filter(Q(kpi_id__in=kpi_ids) | Q(controle=Alerte.Controle.REGLE))
          # seule l'organisation d'une ligne retient une alerte (sa case, ou une règle dans la même organisation) : les
          # alertes des autres organisations ne sont plus lues (« Pour moi » d'un validateur : 5 400 lues, 400 gardées)
          .filter(organisation_id__in=org_ids))
    for a in qs if cles else ():
        if cases_visibles is not None and not visible(a, cases_visibles):
            continue
        for k in (a.kpis_concernes.split() if a.controle == Alerte.Controle.REGLE else [a.kpi_id]):
            if (k, a.organisation_id) in cles:
                alertes.setdefault((k, a.organisation_id), []).append(a)
    resultat = []
    lecture = {(k.code, o.id) for k, o in calculees}
    dessus = couvertes(campagne.periode, paires)
    fac = facultatifs(campagne)
    from parametres import niveaux as N

    rangs = N.rangs()
    for k, o in toutes:
        c = (k.code, o.id)
        r, p = reponses.get(c), n1.get(c)
        e = None
        if r and p and k.est_numerique and not r.non_applicable and not p.non_applicable:  # pas d'écart sur un décompte
            e = ecart(r.valeur, p.valeur)
        resultat.append(Ligne(k, o, r, p, statut_affiche(r), e, r._nb_preuves if r else 0,
                              sorted(spocs.get(c, []), key=str), c in lecture, alertes.get(c, []),
                              au_dessus(k, o, rangs) and c not in lecture, dessus.get(c),
                              facultatif=k.code in fac and c not in lecture))
    plan = plan or Plan(campagne.referentiel)
    # référentiels qui collectent aussi cette période (une campagne dont la période la recoupe) : un référentiel
    # historique sans campagne sur l'exercice en cours n'est pas signalé (« aussi dans… »)
    periode = campagne.periode
    avec_campagnes = set(Campagne.objects.filter(periode__debut__lte=periode.fin, periode__fin__gte=periode.debut)
                         .values_list("referentiel_id", flat=True).distinct())
    for l in resultat:
        l.autres_refs = [r for r in plan.referentiels_de(l.kpi.code) if r.pk != campagne.referentiel_id and r.pk in avec_campagnes]
    if len(resultat) > 1:
        resultat.sort(key=ordre(plan))
    return resultat


_verrou_gc = threading.Lock()
_gc_suspendu = {"n": 0, "actif": False}


@contextmanager
def sans_ramasse_miettes():
    """Ramasse-miettes de Python suspendu le temps de fabriquer beaucoup d'objets qui restent tous en vie (100 000 lignes) :
    sinon il reparcourt plusieurs fois tous les objets du processus pendant la fabrication (la moitié du temps à 680
    organisations). Aucun cycle n'est créé ; il reprend à la sortie, comme avant. Plusieurs fils (gunicorn --threads) : il
    reprend quand le dernier sort, et seulement s'il était actif à l'entrée du premier."""
    with _verrou_gc:
        if _gc_suspendu["n"] == 0:
            _gc_suspendu["actif"] = gc.isenabled()
            gc.disable()
        _gc_suspendu["n"] += 1
    try:
        yield
    finally:
        with _verrou_gc:
            _gc_suspendu["n"] -= 1
            if _gc_suspendu["n"] == 0 and _gc_suspendu["actif"]:
                gc.enable()


def lignes_legeres(campagne, paires, calculees=(), plan=None):
    """Mêmes lignes que ``construire_lignes``, dans le même ordre, pour les pages qui ne font que compter (Tableau de bord,
    « À traiter » de l'Administration, Relances, visuel « taux de remplissage ») : statut, N/A, SPOC actifs, case
    calculée, saisie au-dessus, couverte, facultative. Sans la réponse elle-même (``reponse`` vaut None, ``na`` est lu
    en base), sans N-1 ni écart, sans preuves, sans alertes, sans « aussi dans… » : rien de cela n'y est lu. Les
    réponses et les SPOC sont lus en tuples, sans objets (à 680 organisations : 100 000 lignes par campagne)."""
    with sans_ramasse_miettes():
        return _lignes_legeres(campagne, paires, calculees, plan)


def _lignes_legeres(campagne, paires, calculees, plan):
    toutes = list(paires) + list(calculees)
    kpi_ids = {k.code for k, _ in toutes}
    org_ids = {o.id for _, o in toutes}
    # {KPI : {organisation : …}} : une case se retrouve sans fabriquer de couple à chaque ligne ; les réponses et les
    # attributions des autres couples (KPI d'une ligne × organisation d'une autre) sont lues mais jamais demandées
    etats, spocs = {}, {}
    if toutes:
        for kpi_id, org_id, statut, na in (Reponse.objects.filter(periode=campagne.periode, kpi_id__in=kpi_ids, organisation_id__in=org_ids)
                                           .values_list("kpi_id", "organisation_id", "statut", "non_applicable")):
            etats.setdefault(kpi_id, {})[org_id] = (statut, na)
        from referentiel.models import Utilisateur

        attributions = list(Attribution.objects.filter(kpi_id__in=kpi_ids, organisation_id__in=org_ids, role=Attribution.Role.CONTRIBUTEUR,
                                                       utilisateur__is_active=True)
                            .exclude(utilisateur__is_superuser=False, utilisateur__role__in=Utilisateur.ROLES_LECTURE)  # jamais SPOC
                            .values_list("kpi_id", "organisation_id", "utilisateur_id"))
        personnes = Utilisateur.objects.in_bulk({u for _, _, u in attributions})
        for kpi_id, org_id, u in attributions:
            spocs.setdefault(kpi_id, {}).setdefault(org_id, []).append(personnes[u])
    lecture = {(k.code, o.id) for k, o in calculees}
    dessus = couvertes(campagne.periode, paires)
    fac = facultatifs(campagne)
    from parametres import niveaux as N

    rangs = N.rangs()
    resultat, dessus_de, vide, rien = [], {}, (Reponse.Statut.A_SAISIR, False), {}
    for k, o in toutes:
        code, oid = k.code, o.id
        statut, na = etats.get(code, rien).get(oid, vide)
        ici = dessus_de.get((code, o.niveau_id))  # au-dessus de la granularité : ne dépend que du KPI et du niveau
        if ici is None:
            ici = dessus_de[(code, o.niveau_id)] = au_dessus(k, o, rangs)
        p = spocs.get(code, rien).get(oid, ())
        lu = bool(lecture) and (code, oid) in lecture
        resultat.append(Ligne(k, o, None, None, statut, None, 0, sorted(p, key=str) if len(p) > 1 else list(p), lu, [],
                              ici and not lu, dessus.get((code, oid)) if dessus else None,
                              facultatif=code in fac and not lu, non_applicable=na))
    if len(resultat) > 1:
        resultat.sort(key=ordre(plan or Plan(campagne.referentiel)))
    return resultat


def lignes(utilisateur, campagne, org=None, personnel=False, calculees=False, plan=None, legere=False):
    """Lignes d'une page : toutes, celles d'une organisation, ou « Pour moi » (personnel).

    calculees=True ajoute, pour l'organisation choisie, les KPI calculés, agrégés et cumulés (lecture seule),
    si l'utilisateur peut les voir, et les KPI qui s'y saisissent au-dessus de leur granularité (facultatifs). Les KPI sont ceux du référentiel de la campagne (et les sources de leurs
    formules), dans l'ordre de son ``plan``.
    ``legere`` : lignes pour compter seulement (``lignes_legeres``).
    """
    plan = plan or Plan(campagne.referentiel)
    toutes = cellules(utilisateur, personnel, campagne)
    visibles = None if utilisateur.voit_tout and utilisateur.orgs_permises() is None else {(k.code, o.id) for k, o in toutes}
    paires = [(k, o) for k, o in toutes if org is None or o.id == org.id]
    lecture = []
    if org is not None and voit_calcules(utilisateur, org):
        if calculees:
            codes = codes_campagne(campagne)
            qs = (Reponse.objects.filter(periode=campagne.periode, organisation=org, kpi__actif=True,
                                         origine__in=[Reponse.Origine.CALCUL, Reponse.Origine.AGREGATION, Reponse.Origine.CUMUL,
                                                      Reponse.Origine.FORCEE])
                  .select_related("kpi__type_saisie", "kpi__type_reponse", "kpi__unite"))
            lecture = [(r.kpi, org) for r in qs if codes is None or r.kpi_id in codes[1]]
        # saisie aux niveaux supérieurs : la cellule se saisit (elle montre le total calculé tant que rien n'y est saisi) ;
        # affichée même sans les calculés
        from parametres import niveaux as N

        rangs = N.rangs()
        dessus = [k for k in kpis_collectes(campagne.referentiel, campagne.periode) if au_dessus(k, org, rangs) and not cumule(campagne, k)
                  and dans_la_campagne(campagne, k)]
        codes_dessus = {k.code for k in dessus}
        lecture = [(k, o) for k, o in lecture if k.code not in codes_dessus]
        paires += [(k, org) for k in dessus]
    return construire_lignes(campagne, paires, lecture, plan, visibles, legere=legere)


def ligne(utilisateur, campagne, kpi, org):
    """Une seule ligne (mise à jour d'une ligne du tableau après une saisie), avec les alertes que la personne voit."""
    calc = est_calculee(kpi, org, reponse_de(campagne, kpi, org), campagne)
    visibles = None
    if not (utilisateur.voit_tout and utilisateur.orgs_permises() is None):  # la case est dans son périmètre si elle lui est attribuée (au niveau de saisie)
        dans = not calc and not au_dessus(kpi, org) and role_sur(utilisateur, kpi, org) is not None
        visibles = {(kpi.code, org.id)} if dans else set()
    return construire_lignes(campagne, [] if calc else [(kpi, org)], [(kpi, org)] if calc else [], cases_visibles=visibles,
                             plan=Plan(campagne.referentiel, kpis=[kpi.code]))[0]


def progression(liste):
    """(validées, total) : N/A validé compte comme une réponse (section 4.5)."""
    saisies = [l for l in liste if l.attendue]
    return sum(1 for l in saisies if l.statut == Reponse.Statut.VALIDE), len(saisies)


def campagne_courante(referentiel=None):
    """Campagne affichée par défaut : la plus récente en saisie ouverte (premier référentiel d'abord), sinon en revue,
    sinon la plus récente."""
    qs = Campagne.objects.select_related("referentiel", "periode")
    if referentiel is not None:
        qs = qs.filter(referentiel=referentiel)
    return (qs.filter(statut=Campagne.Statut.OUVERTE).first() or qs.filter(statut=Campagne.Statut.REVUE).first() or qs.first())


def referentiels_de(utilisateur):
    """Référentiels actifs auxquels la personne répond, dans l'ordre : tous ceux qui ont une campagne pour l'administrateur,
    sinon ceux qui contiennent au moins un KPI de ses cases (attributions, organisations du validateur)."""
    if not hasattr(utilisateur, "_referentiels"):
        refs = Referentiel.objects.filter(actif=True, campagnes__isnull=False).distinct().order_by("ordre", "code")
        if not utilisateur.voit_tout:
            codes = {k.code for k, _ in cellules(utilisateur)}
            refs = refs.filter(elements__kpi_id__in=codes).distinct()
        utilisateur._referentiels = list(refs)
    return utilisateur._referentiels


def campagnes_proposees(utilisateur, referentiel):
    """Campagnes d'un référentiel proposées à la personne (sans celles en préparation, sauf pour l'administrateur),
    de la plus récente à la plus ancienne."""
    qs = Campagne.objects.filter(referentiel=referentiel).select_related("referentiel", "periode")
    if not utilisateur.est_admin:
        qs = qs.exclude(statut=Campagne.Statut.PREPARATION)
    return list(qs)


def campagne_par_defaut(utilisateur):
    """Première campagne en saisie ouverte (puis en revue) parmi les référentiels de la personne, sinon la campagne
    courante."""
    refs = referentiels_de(utilisateur)
    for statut in (Campagne.Statut.OUVERTE, Campagne.Statut.REVUE):
        for r in refs:
            c = Campagne.objects.filter(referentiel=r, statut=statut).select_related("referentiel", "periode").first()
            if c is not None:
                return c
    return (campagne_courante(refs[0]) if refs else None) or campagne_courante()


def campagnes_en_cours():
    """Campagnes ouvertes ou en revue, par référentiel puis de la plus récente à la plus ancienne."""
    return list(Campagne.objects.filter(statut__in=[Campagne.Statut.OUVERTE, Campagne.Statut.REVUE])
                .select_related("referentiel", "periode"))


def libelle_comparaison(campagne):
    """« N-1 », ou la période de comparaison (« février 2026 ») pour un référentiel comparé à la période précédente."""
    p = periode_comparaison(campagne)
    if campagne.periode.annuelle:
        return "N-1"
    return str(p) if p is not None else ("P-1" if campagne.referentiel.comparaison == Referentiel.Comparaison.P1 else "N-1")


def lecture_seule(utilisateur, campagne):
    """Vrai si la personne ne peut plus rien saisir dans la campagne : clôturée (même pour l'administrateur), en revue
    ou date de fin de saisie passée (pour les contributeurs et les validateurs)."""
    return (campagne.statut == Campagne.Statut.CLOTUREE or utilisateur.lecture_seule
            or (not utilisateur.est_admin and not campagne.saisie_ouverte()))


@dataclass
class Reste:
    """Ce qui reste à faire sur un périmètre (une organisation, une liste, tout le périmètre d'une personne dans une
    campagne) : cases attendues, validées (N/A validé compris) et alertes à justifier. ``par_org`` : {organisation:
    Reste} dans l'ordre de l'arbre quand il est connu. Même calcul pour le bandeau de Saisie, Pour moi et « Je réponds
    à » : les chiffres ne se contredisent pas d'une page à l'autre."""
    total: int = 0
    valide: int = 0
    alertes: int = 0
    par_org: dict = field(default_factory=dict)
    hors_selecteur: bool = False  # organisation absente du sélecteur (inactive) : comptée, jamais proposée (« Aller à »)

    @property
    def valeurs(self):
        """Valeurs à saisir ou à valider."""
        return self.total - self.valide

    @property
    def fini(self):
        return not self.valeurs and not self.alertes

    @property
    def taux(self):
        return float(arrondi(100 * self.valide / self.total, 1)) if self.total else 0

    @property
    def a_montrer(self):
        """Vrai s'il y a quelque chose à dire (des cases attendues ou une alerte)."""
        return bool(self.total or self.alertes)

    @property
    def nb_orgs(self):
        """Organisations où il reste quelque chose."""
        return sum(1 for r in self.par_org.values() if not r.fini)

    @property
    def nb_orgs_valeurs(self):
        return sum(1 for r in self.par_org.values() if r.valeurs)

    @property
    def nb_orgs_alertes(self):
        return sum(1 for r in self.par_org.values() if r.alertes)

    def ici(self, org):
        return self.par_org.get(org) or Reste()

    def ailleurs(self, org):
        """Ce qui reste dans les autres organisations du périmètre."""
        return sum((Reste(r.total, r.valide, r.alertes, {o: r}) for o, r in self.par_org.items() if o != org), Reste())

    def suivante(self, sauf=None):
        """Première organisation (ordre de l'arbre) où il reste des valeurs, sinon des alertes ; None si tout est fait
        (ou s'il ne reste que des alertes sur des organisations absentes du sélecteur)."""
        autres = [(o, r) for o, r in self.par_org.items() if o != sauf and not r.hors_selecteur]
        return next((o for o, r in autres if r.valeurs), None) or next((o for o, r in autres if r.alertes), None)

    def __add__(self, autre):
        par_org = dict(self.par_org)
        for o, r in autre.par_org.items():
            par_org[o] = par_org[o] + r if o in par_org else r
        return Reste(self.total + autre.total, self.valide + autre.valide, self.alertes + autre.alertes, par_org,
                     self.hors_selecteur and autre.hors_selecteur)

    def __radd__(self, autre):  # sum() sans valeur de départ
        return self if autre == 0 else autre + self

    def _cumuler(self):
        self.total = sum(r.total for r in self.par_org.values())
        self.valide = sum(r.valide for r in self.par_org.values())
        self.alertes = sum(r.alertes for r in self.par_org.values())
        return self


def reste(liste, alertes=()):
    """Reste d'une liste de lignes (cases attendues seulement) et des alertes à justifier de ce périmètre
    (``coherence.alertes_a_traiter``), rangées par l'organisation de l'alerte."""
    r = Reste()
    for l in liste:
        if l.attendue:
            x = r.par_org.setdefault(l.organisation, Reste())
            x.total += 1
            x.valide += l.statut == Reponse.Statut.VALIDE
    for a in alertes:
        r.par_org.setdefault(a.organisation, Reste()).alertes += 1
    return r._cumuler()


def reste_par_org(organisations):
    """Reste de tout le périmètre à partir des organisations du sélecteur (``organisations_visibles``), dans l'ordre
    de l'arbre ; puis les alertes posées sur des organisations absentes du sélecteur (``alertes_hors``), comptées
    « ailleurs » sans être proposées."""
    par_org = {o: Reste(t, v, a) for o, t, v, a in organisations}
    for o, n in getattr(organisations, "alertes_hors", {}).items():
        par_org[o] = Reste(alertes=n, hors_selecteur=True)
    return Reste(par_org=par_org)._cumuler()


class Selecteur(list):
    """Organisations du sélecteur [(organisation, cellules à saisir, validées, alertes à justifier)], et
    ``alertes_hors`` : {organisation: alertes à justifier} des organisations qui n'y figurent pas (administrateur : une
    organisation inactive). Elles comptent dans « ce qui reste » comme sur la page Cohérence."""
    alertes_hors = {}


def organisations_visibles(utilisateur, campagne):
    """Organisations du sélecteur, dans l'ordre de l'arbre : [(organisation, cellules à saisir, validées, alertes à
    justifier)].

    Admin : toutes les organisations actives. Validateur : aussi les organisations qui lui sont attribuées
    (pour voir leurs agrégats). Une organisation où une alerte attend y figure toujours."""
    from .coherence import alertes_a_traiter

    paires = cellules(utilisateur, campagne=campagne)
    alertes, orgs_alertes = {}, {}
    for a in alertes_a_traiter(utilisateur, campagne, cases={(k.code, o.id) for k, o in paires}):
        alertes[a.organisation_id] = alertes.get(a.organisation_id, 0) + 1
        orgs_alertes[a.organisation_id] = a.organisation
    dessus = couvertes(campagne.periode, paires)
    paires = [(k, o) for k, o in paires if (k.code, o.id) not in dessus]
    fac = facultatifs(campagne)  # facultatifs : l'organisation reste proposée, mais ils ne comptent pas
    # validées : lues pour les seuls KPI et organisations des cases (pas toutes les réponses de la période : échelle, P-A9)
    valides = set(Reponse.objects.filter(periode=campagne.periode, statut=Reponse.Statut.VALIDE, kpi_id__in={k.code for k, _ in paires},
                                         organisation_id__in={o.id for _, o in paires})
                  .values_list("kpi_id", "organisation_id")) if paires else set()
    totaux = {}
    for k, o in paires:
        t = totaux.setdefault(o, [0, 0])
        if k.code not in fac:
            t[0] += 1
            t[1] += (k.code, o.id) in valides
    arbre = arbre_organisations(campagne.periode)  # exercice clos ou rouvert « garder » : rattachements de l'époque
    if utilisateur.voit_tout:
        permises = utilisateur.orgs_permises()
        autres = [o for o in arbre.values() if o.actif and (permises is None or o.id in permises)]
    else:
        ids = Attribution.objects.filter(utilisateur=utilisateur, role=Attribution.Role.VALIDATEUR).values_list("organisation_id", flat=True)
        autres = [arbre[i] for i in set(ids) if i in arbre and arbre[i].actif]
    from .calcul import ouverte

    # pas encore ouverte pendant la période (date d'ouverture) : pas proposée, sauf alerte qui attend
    autres = [o for o in autres if ouverte(o, campagne.periode, arbre)]
    autres += [arbre[i] for i in alertes if i in arbre and arbre[i].actif]
    for o in autres:
        totaux.setdefault(o, [0, 0])
    resultat = Selecteur((o, t, v, alertes.get(o.id, 0)) for o, (t, v) in sorted(totaux.items(), key=lambda x: cle_arbre(x[0])))
    dans = {o.id for o in totaux}
    resultat.alertes_hors = {orgs_alertes[i]: n for i, n in alertes.items() if i not in dans}
    return resultat


def cle_arbre(org):
    """Clé de tri qui range chaque organisation sous son parent, quel que soit le nombre de niveaux."""
    chemin, o = [], org
    while o:
        chemin.append((o.rang, o.nom))
        o = o.parent
    return tuple(reversed(chemin))


# ---------------------------------------------------------------- tableau de bord
@dataclass
class Compteur:
    total: int = 0
    valide: int = 0
    brouillon: int = 0
    a_saisir: int = 0
    na: int = 0

    def ajouter(self, l):
        self.total += 1
        if l.statut == Reponse.Statut.VALIDE:
            self.valide += 1
        elif l.statut == Reponse.Statut.BROUILLON:
            self.brouillon += 1
        else:
            self.a_saisir += 1
        if l.na:
            self.na += 1

    def ajouter_cases(self, statut, na, n):
        """Ajoute ``n`` cases de même statut et même N/A (comme ``n`` appels à ``ajouter``)."""
        self.total += n
        if statut == Reponse.Statut.VALIDE:
            self.valide += n
        elif statut == Reponse.Statut.BROUILLON:
            self.brouillon += n
        else:
            self.a_saisir += n
        if na:
            self.na += n

    def fusionner(self, autre):
        """Ajoute les cases d'un autre compteur (les compteurs s'additionnent)."""
        self.total += autre.total
        self.valide += autre.valide
        self.brouillon += autre.brouillon
        self.a_saisir += autre.a_saisir
        self.na += autre.na

    def pct(self, n):
        return float(arrondi(100 * n / self.total, 1)) if self.total else 0

    @property
    def taux(self):
        return self.pct(self.valide)

    @property
    def pct_brouillon(self):
        return self.pct(self.brouillon)


def tableau_de_bord(liste, plan=None):
    """Taux de remplissage global, par référentiel (éléments obligatoires), par organisation (cellules de
    l'organisation et de ses descendantes), par thème du plan et par SPOC.
    ``par_org_propre`` : {organisation : compteur de ses seules cases} (le retard d'une organisation se juge sur
    ses propres cases ; une ligne calculée ou saisie au-dessus n'est pas attendue, donc pas comptée).
    Taux = réponses validées (N/A compris) ÷ cellules attendues (section 4.5). Les KPI facultatifs ne comptent nulle part :
    ``facultatifs`` les compte à part (« Facultatifs remplis : x / y »)."""
    plan = plan or Plan()
    saisies = sorted((l for l in liste if l.attendue), key=ordre(plan))
    total, par_org_propre, par_theme = Compteur(), {}, {}
    facultatives = Compteur()
    for l in liste:
        if l.facultatif and not l.calculee and not l.au_dessus and l.couverte is None:
            facultatives.ajouter(l)
    par_ref = {r.code: (r, Compteur()) for r in plan.referentiels}
    # cases comptées par (KPI, statut, N/A), par (organisation, statut, N/A) et par (SPOC, statut, N/A) : un comptage par
    # ligne, sans objet à hacher ; puis les compteurs du thème et des référentiels de chaque KPI, des cases propres de
    # chaque organisation, de chaque SPOC. Le total d'une organisation est la somme des cases propres de son sous-arbre
    # (les compteurs s'additionnent). Thèmes et organisations gardent l'ordre de leur première ligne.
    par_kpi, par_case_org, par_case_spoc = {}, {}, {}
    propres, spocs, orgs, personnes, titres = {}, {}, {}, {}, {}
    for l in saisies:
        o, code, etat = l.organisation, l.kpi.code, (l.statut, l.na)
        if o.id not in propres:
            propres[o.id] = Compteur()
            a = o
            while a:
                orgs.setdefault(a.id, a)
                a = a.parent
        if code not in titres:
            titres[code] = plan.titres(code)[0]
            par_theme.setdefault(titres[code], Compteur())
        cle = (code, etat)
        par_kpi[cle] = par_kpi.get(cle, 0) + 1
        cle = (o.id, etat)
        par_case_org[cle] = par_case_org.get(cle, 0) + 1
        for u in l.spocs or [None]:
            p = u.pk if u is not None else None
            if p not in spocs:
                spocs[p], personnes[p] = Compteur(), u
            cle = (p, etat)
            par_case_spoc[cle] = par_case_spoc.get(cle, 0) + 1
    for (code, (statut, na)), n in par_kpi.items():
        total.ajouter_cases(statut, na, n)
        par_theme[titres[code]].ajouter_cases(statut, na, n)
        for r in plan.appartenances.get(code, []):
            if r in par_ref and (r, code) not in plan.facultatifs:
                par_ref[r][1].ajouter_cases(statut, na, n)
    for (i, (statut, na)), n in par_case_org.items():
        propres[i].ajouter_cases(statut, na, n)
    for (p, (statut, na)), n in par_case_spoc.items():
        spocs[p].ajouter_cases(statut, na, n)
    par_org = {}
    for i, c in propres.items():
        par_org_propre[orgs[i]] = c
        a = orgs[i]
        while a:
            par_org.setdefault(a.id, Compteur()).fusionner(c)
            a = a.parent
    return {
        "total": total,
        "facultatifs": facultatives,
        "par_referentiel": [x for x in par_ref.values() if x[1].total],
        "par_org": sorted(((orgs[i], c) for i, c in par_org.items()), key=lambda x: cle_arbre(x[0])),
        "par_org_propre": par_org_propre,
        "par_theme": list(par_theme.items()),
        "par_spoc": sorted(((personnes[i], c) for i, c in spocs.items()),
                           key=lambda x: (x[0] is not None, str(x[0] or ""))),  # « Sans SPOC » en tête
    }


# ---------------------------------------------------------------- attributions (SPOC)
ACTIONS_JOURNAL_ATTRIBUTION = {  # (donnée, retirée) : action du journal selon le rôle de l'attribution
    Attribution.Role.CONTRIBUTEUR: ("attribution", "retrait_attribution"),
    Attribution.Role.VALIDATEUR: ("attribution_validateur", "retrait_validateur"),
}


def peut_valider_attribue(utilisateur):
    """Vrai si la personne peut recevoir une attribution de validateur : compte actif, rôle validateur ou administrateur
    (jamais un contributeur, un lecteur, un auditeur)."""
    return utilisateur.is_active and (utilisateur.est_admin or utilisateur.role == Utilisateur.Role.VALIDATEUR)


def controler_attribution_validateur(kpi, org, rangs=None):
    """Message si une attribution de validateur n'a pas de sens sur (KPI, organisation), sinon "" : KPI calculé (rien à
    valider) ou organisation sous le niveau de saisie du KPI (elle ne couvrirait aucune case : ``cellules``)."""
    from parametres import niveaux as N

    if kpi.est_calcule:
        return libelle("messages.attribution.validateur_calcule", kpi=kpi.code)
    rangs = rangs if rangs is not None else N.rangs()
    if rangs.get(org.niveau_id, 0) > rangs.get(kpi.granularite_id, 0):
        return libelle("messages.attribution.validateur_niveau", kpi=kpi.code, niveau=kpi.granularite)
    return ""


@ESP.atomic
def attribuer(admin, paires, utilisateur, retirer=False, role=Attribution.Role.CONTRIBUTEUR):
    """Attribue (ou retire) un contributeur ou un validateur sur des cellules. Réservé à l'administrateur (section 4.3).

    Validateur : la personne, relue sous verrou, doit être active et validateur ou
    administrateur ; l'attribution vaut pour le KPI dans l'organisation et celles du dessous (``cellules``).
    Renvoie le nombre de cellules modifiées. Retirer une attribution ne supprime pas les réponses."""
    if not admin.est_admin:
        raise PermissionDenied(libelle("saisie.msg.seul_admin_attribue"))
    if role not in ACTIONS_JOURNAL_ATTRIBUTION:
        raise ValidationError(libelle("saisie.erreur.action_inconnue"))
    action_don, action_retrait = ACTIONS_JOURNAL_ATTRIBUTION[role]
    if role == Attribution.Role.VALIDATEUR and not retirer:
        # relu sous verrou : un changement de rôle (passage en lecture seule) attend la fin de cette transaction
        utilisateur = Utilisateur.objects.select_for_update().get(pk=utilisateur.pk)
        if not peut_valider_attribue(utilisateur):
            raise ValidationError(libelle("messages.attribution.pas_validateur", nom=str(utilisateur)))
        from parametres import niveaux as N

        rangs = N.rangs()
        for kpi, org in paires:
            motif = controler_attribution_validateur(kpi, org, rangs)
            if motif:
                raise ValidationError(motif)
    n = 0
    for kpi, org in paires:
        if retirer:
            supprimees, _ = Attribution.objects.filter(kpi=kpi, organisation=org, utilisateur=utilisateur, role=role).delete()
            if supprimees:
                Journal.ecrire(admin, action_retrait, kpi, role, f"{org.nom} : {utilisateur.email}", "")
                n += 1
            continue
        a = Attribution(kpi=kpi, organisation=org, utilisateur=utilisateur, role=role)
        a.clean()
        _, cree = Attribution.objects.get_or_create(kpi=kpi, organisation=org, utilisateur=utilisateur, role=role)
        if cree:
            Journal.ecrire(admin, action_don, kpi, role, "", f"{org.nom} : {utilisateur.email}")
            n += 1
    return n
