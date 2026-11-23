"""Certificat de clôture : la page à imprimer d'une campagne clôturée.

Lecture seule : tout est relu à l'affichage, rien n'est écrit (ni en base, ni au journal) et rien n'est recalculé. Ce que la
page réunit : la campagne et son référentiel, qui l'a clôturée et quand (le journal, quand il garde la clôture), le périmètre
(organisations par niveau, ouvertes pendant la période), le taux de remplissage, le nombre de valeurs par état, les preuves,
les alertes de cohérence et une empreinte des chiffres.

Empreinte : un condensé SHA-256 des valeurs de la campagne, dans un ordre qui ne dépend ni de la base ni de la langue. Si un
seul chiffre change, l'empreinte change. Texte exact haché (UTF-8, une ligne par valeur, séparées par un saut de ligne) :

- ligne d'en-tête : tableau JSON ``["probant-certificat-1", code du référentiel, début de la période, fin de la période]`` ;
- une ligne par case qui porte quelque chose (valeur, texte ou N/A), rangées par code du KPI puis code de l'organisation :
  tableau JSON ``[code du KPI, code de l'organisation, valeur, N/A, texte]`` ; la valeur est le nombre décimal écrit sans
  zéros inutiles (``null`` sans valeur), le N/A est ``true`` ou ``false``, le texte est la réponse « liste », « oui / non »
  ou rédigée telle qu'enregistrée.

Le statut, l'auteur et les dates ne sont pas hachés : l'empreinte porte sur les chiffres, pas sur la vie de la saisie (la
page les montre à côté). Les KPI hachés sont ceux de la campagne : son référentiel et les sources de leurs formules
(``saisie.codes_campagne``).

Droits : l'administrateur et l'auditeur, comme le dossier d'audit.

Certificat partiel : un auditeur limité à des organisations reçoit un certificat marqué comme partiel. Son périmètre est
celui de tous les autres écrans pour lui, ``Utilisateur.orgs_permises`` (les organisations choisies et leurs descendantes) :
le remplissage et les alertes passent déjà par ``saisie.lignes`` et ``coherence.alertes_visibles`` avec son compte ; le
périmètre par niveau, les valeurs, les preuves et l'empreinte ne gardent que les organisations de cet ensemble. Un ancêtre
des organisations choisies n'en fait pas partie : aucun total au-dessus n'est compté ni haché (comme la Visualisation, qui
ne lui montre pas ces totaux). Seul chiffre de toute la campagne montré : le nombre d'organisations ouvertes pendant la
période (« N sur M »). L'empreinte d'un certificat partiel a une autre ligne d'en-tête :
``["probant-certificat-1-partiel", code du référentiel, début, fin, [codes des organisations du sommet couvert]]``, puis
les seules lignes des organisations permises ; elle diffère donc toujours de celle du certificat complet."""
import hashlib
import json
from collections import Counter
from decimal import Decimal

from django.core.exceptions import PermissionDenied

from parametres import libelles as LB
from parametres.libelles import libelle
from referentiel.models import KPI

from . import calcul as C
from . import dates_courtes as DC
from . import saisie as S
from .models import Alerte, Campagne, Journal, Preuve, Reponse

VERSION_EMPREINTE = "probant-certificat-1"
VERSION_EMPREINTE_PARTIELLE = "probant-certificat-1-partiel"
MAX_ALERTES_LISTEES = 10
ACTIONS_REOUVERTURE = ("rouvrir", "rouvrir_contributeurs")


def permis(utilisateur):
    """Administrateur ou auditeur (limité à des organisations : certificat partiel, ``organisations_permises``)."""
    return bool(utilisateur.est_admin or utilisateur.est_auditeur)


def exiger(utilisateur):
    if not permis(utilisateur):
        raise PermissionDenied(libelle("suivi.certificat.refus"))


def organisations_permises(utilisateur):
    """None : certificat complet (administrateur, auditeur sans limite) ; sinon les organisations de l'auditeur, la règle
    des autres écrans (``Utilisateur.orgs_permises``) : certificat partiel."""
    if utilisateur.est_admin:
        return None
    return utilisateur.orgs_permises()


def _nombre_stable(v):
    """Nombre décimal sans zéros inutiles (« 12.5 », « 3 », « 0 »)."""
    if v is None:
        return None
    t = format(Decimal(v).normalize(), "f")
    return "0" if t in ("-0", "") else t


def lignes_empreinte(campagne, permises=None):
    """Lignes de l'empreinte (voir l'en-tête du module) : [(code KPI, code organisation, valeur, N/A, texte)], rangées.
    ``permises`` : seulement ces organisations (certificat partiel)."""
    codes = S.codes_campagne(campagne)
    retenus = None if codes is None else codes[1]
    qs = Reponse.objects.filter(periode=campagne.periode)
    if permises is not None:
        qs = qs.filter(organisation_id__in=permises)
    qs = qs.values_list("kpi_id", "organisation__code", "valeur", "non_applicable", "texte")
    lignes = []
    for kpi, org, valeur, na, texte in qs.iterator(chunk_size=2000):
        if retenus is not None and kpi not in retenus:
            continue
        if valeur is None and not na and not texte:
            continue  # case vide : ne change rien aux chiffres
        lignes.append((kpi, org, _nombre_stable(valeur), bool(na), texte or ""))
    lignes.sort(key=lambda x: (x[0], x[1]))
    return lignes


def empreinte(campagne, permises=None, sommets=()):
    """(condensé SHA-256 en hexadécimal, nombre de valeurs hachées) des chiffres de la campagne. ``permises`` : certificat
    partiel, sur ces seules organisations ; ``sommets`` : codes des organisations du sommet couvert, dans l'en-tête."""
    lignes = lignes_empreinte(campagne, permises)
    h = hashlib.sha256()
    entete = [VERSION_EMPREINTE, campagne.referentiel_id, campagne.periode.debut.isoformat(), campagne.periode.fin.isoformat()]
    if permises is not None:
        entete = [VERSION_EMPREINTE_PARTIELLE] + entete[1:] + [sorted(sommets)]
    h.update(json.dumps(entete, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    for l in lignes:
        h.update(b"\n")
        h.update(json.dumps(list(l), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return h.hexdigest(), len(lignes)


def _qui(u):
    return (u.email or str(u)) if u else ""


def cloture(campagne):
    """(qui, quand) de la dernière clôture que garde le journal ; (None, None) s'il n'en garde pas."""
    e = Journal.objects.filter(objet="Campagne", objet_id=str(campagne.pk), action="cloturer").select_related("utilisateur") \
        .order_by("-date", "-pk").first()
    if e is None:
        return None, None
    return e.utilisateur, e.date


def reouvertures(campagne):
    """(nombre de réouvertures, date de la dernière, mode de la dernière : « gardes », « recalcules » ou vide)."""
    entrees = list(Journal.objects.filter(objet="Campagne", objet_id=str(campagne.pk),
                                          action__in=ACTIONS_REOUVERTURE + ("mode_reouverture",)).order_by("date", "pk"))
    ouvertures = [e for e in entrees if e.action in ACTIONS_REOUVERTURE and e.avant == Campagne.Statut.CLOTUREE]
    modes = [e for e in entrees if e.action == "mode_reouverture"]
    return len(ouvertures), (ouvertures[-1].date if ouvertures else None), (modes[-1].apres if modes else "")


def perimetre(campagne, permises=None):
    """([(niveau, organisations de l'arbre, ouvertes pendant la période)], total des deux) : l'arbre de la période (celui de sa
    clôture), ``calcul.ouverte`` pour « ouverte pendant la période ». ``permises`` : seulement ces organisations."""
    from parametres import langues as L

    lg = L.interface()
    toutes = S.arbre_organisations(campagne.periode)
    par_niveau = {}
    for o in toutes.values():
        if permises is not None and o.id not in permises:
            continue
        n = par_niveau.setdefault(o.niveau_id, [o.niveau, 0, 0])
        n[1] += 1
        n[2] += bool(C.ouverte(o, campagne.periode, toutes))
    lignes = sorted(par_niveau.values(), key=lambda x: x[0].rang)
    return ([(n.tr("nom_pluriel", lg) or n.tr("nom", lg), t, o) for n, t, o in lignes],
            (sum(t for _, t, _ in lignes), sum(o for _, _, o in lignes)))


def couverture(campagne, permises):
    """(organisations du sommet couvert, rangées dans l'arbre ; nombre d'organisations ouvertes pendant la période dans toute
    la campagne) : les organisations permises dont le parent ne l'est pas, dans l'arbre de la période."""
    toutes = S.arbre_organisations(campagne.periode)
    sommets = sorted((o for o in toutes.values() if o.id in permises and o.parent_id not in permises), key=S.cle_arbre)
    return sommets, sum(1 for o in toutes.values() if C.ouverte(o, campagne.periode, toutes))


def remplissage(utilisateur, campagne):
    """Compteur du Tableau de bord (``saisie.tableau_de_bord``) : cases attendues, validées, brouillons, à saisir, N/A.
    Périmètre de la personne (``saisie.lignes`` avec son compte)."""
    from referentiel.plans import Plan

    plan = Plan(campagne.referentiel)
    return S.tableau_de_bord(list(S.lignes(utilisateur, campagne, plan=plan, legere=True)), plan)["total"]


def valeurs(campagne, permises=None):
    """({état : nombre}, nombre de fichiers de preuve) pour les KPI de la campagne. ``permises`` : seulement ces
    organisations."""
    codes = S.codes_campagne(campagne)
    retenus = None if codes is None else codes[1]
    n = Counter()
    reponses = Reponse.objects.filter(periode=campagne.periode)
    preuves = Preuve.objects.filter(reponse__periode=campagne.periode)
    if permises is not None:
        reponses = reponses.filter(organisation_id__in=permises)
        preuves = preuves.filter(reponse__organisation_id__in=permises)
    for kpi, origine, statut, valeur, na, texte in reponses.values_list(
            "kpi_id", "origine", "statut", "valeur", "non_applicable", "texte").iterator(chunk_size=2000):
        if retenus is not None and kpi not in retenus:
            continue
        if valeur is None and not na and not texte:
            continue
        n["total"] += 1
        n["validees"] += statut == Reponse.Statut.VALIDE
        n["na"] += bool(na)
        if origine == Reponse.Origine.FORCEE:
            n["forcees"] += 1
        elif origine in (Reponse.Origine.CALCUL, Reponse.Origine.AGREGATION, Reponse.Origine.CUMUL):
            n["calculees"] += 1
        else:
            n["saisies"] += 1
    preuves = sum(1 for k in preuves.values_list("reponse__kpi_id", flat=True) if retenus is None or k in retenus)
    return n, preuves


def alertes(utilisateur, campagne):
    """({« traitees », « justifiees », « ouvertes », « total »}, alertes ouvertes les plus graves d'abord, nombre non listé).
    Ouverte : à traiter (ouverte ou justification rejetée) ; justifiée : justification en attente ou acceptée ; traitée :
    corrigée ou ignorée. Périmètre de la personne (``coherence.alertes_visibles``, règle de la page Cohérence)."""
    from . import coherence as CO

    A = Alerte.Statut
    liste = CO.alertes_visibles(utilisateur, campagne)
    n = Counter()
    ouvertes = []
    for a in liste:
        n["total"] += 1
        if a.statut in Alerte.A_TRAITER:
            n["ouvertes"] += 1
            ouvertes.append(a)
        elif a.statut in (A.JUSTIFIEE, A.ACCEPTEE):
            n["justifiees"] += 1
        else:
            n["traitees"] += 1
    ordre = {Alerte.Gravite.BLOQUANTE: 0, Alerte.Gravite.ALERTE: 1, Alerte.Gravite.INFO: 2}
    ouvertes.sort(key=lambda a: (ordre.get(a.gravite, 3), a.kpi_id, a.organisation.nom, a.pk))
    kpis = {k.code: k for k in KPI.objects.filter(code__in={a.kpi_id for a in ouvertes[:MAX_ALERTES_LISTEES]})}
    listees = [{"kpi": kpis.get(a.kpi_id), "code": a.kpi_id, "organisation": a.organisation,
                "gravite": LB.choix_valeur(Alerte, "gravite", a.gravite), "message": CO.texte_alerte(a, "message")}
               for a in ouvertes[:MAX_ALERTES_LISTEES]]
    return n, listees, max(0, len(ouvertes) - MAX_ALERTES_LISTEES)


def construire(utilisateur, campagne):
    """Tout ce que montre la page, pour une campagne clôturée (``exiger`` d'abord)."""
    from parametres import langues as L

    exiger(utilisateur)
    lg = L.interface()
    p = campagne.periode
    permises = organisations_permises(utilisateur)
    qui, quand = cloture(campagne)
    n_reouv, derniere, mode = reouvertures(campagne)
    codes = S.codes_campagne(campagne)
    par_niveau, (nb_orgs, nb_ouvertes) = perimetre(campagne, permises)
    compteur = remplissage(utilisateur, campagne)
    n_valeurs, n_preuves = valeurs(campagne, permises)
    n_alertes, ouvertes, en_plus = alertes(utilisateur, campagne)
    sommets, nb_campagne = couverture(campagne, permises) if permises is not None else ([], nb_ouvertes)
    condense, nb_hachees = empreinte(campagne, permises, [o.code for o in sommets])
    autres = [c for c in Campagne.objects.filter(periode=p).exclude(pk=campagne.pk).select_related("referentiel")]
    return {
        "campagne": campagne, "periode": p, "debut": DC.date_courte(p.debut, lg), "fin": DC.date_courte(p.fin, lg),
        "autres": [(c.referentiel, LB.choix_valeur_phrase(Campagne, "statut", c.statut)) for c in autres],
        "cloture_par": _qui(qui), "cloture_le": DC.date_heure_courte(quand, lg) if quand else "",
        "cloture_connue": quand is not None,
        "reouvertures": n_reouv, "derniere_reouverture": DC.date_heure_courte(derniere, lg) if derniere else "", "mode": mode,
        "par_niveau": par_niveau, "nb_orgs": nb_orgs, "nb_ouvertes": nb_ouvertes,
        "nb_kpi": (len(codes[0]) if codes is not None else KPI.objects.filter(actif=True).count()),
        "remplissage": compteur, "valeurs": n_valeurs, "preuves": n_preuves,
        "alertes": n_alertes, "alertes_ouvertes": ouvertes, "alertes_en_plus": en_plus,
        "empreinte": condense, "empreinte_blocs": [condense[i:i + 16] for i in range(0, len(condense), 16)],
        "nb_hachees": nb_hachees,
        # certificat partiel : « N sur M » (organisations ouvertes pendant la période) et le sommet couvert
        "partiel": permises is not None, "nb_campagne": nb_campagne, "sommets": [o.nom for o in sommets],
    }
