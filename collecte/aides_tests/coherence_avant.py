"""Construction d'avant l'optimisation à gros volume, gardée telle quelle pour les tests d'équivalence : contrôles
automatiques qui relisent KPI et organisation avec chaque réponse, alertes lues avec ``select_related``. Les tests
comparent la construction actuelle à celle-ci sur des données tirées au hasard (graine fixe) : mêmes détections, mêmes
alertes visibles par rôle. Ne pas modifier : copie de ``collecte/coherence.py`` au commit 539519f."""
import statistics
from decimal import Decimal

from collecte import saisie as S
from collecte.calcul import NA, Calculateur, ouverte
from collecte.coherence import (AVEC_KPI, C, _detection, _f, _pct, _t, _unite, constat_historique, perimetre, seuils,
                                visible)
from collecte.models import Alerte, Reponse
from collecte.periodes import Calendrier


def controles_automatiques(campagne, kpi_ids=None):
    """Détections sur les valeurs saisies ou importées de la période de la campagne."""
    p = campagne.periode
    qs = Reponse.objects.filter(periode=p, origine__in=[Reponse.Origine.SAISIE, Reponse.Origine.IMPORT]).select_related(*AVEC_KPI, "organisation")
    codes = perimetre(campagne)
    if codes is not None:
        qs = qs.filter(kpi_id__in=codes)
    if kpi_ids is not None:
        qs = qs.filter(kpi_id__in=kpi_ids)
    # contrôles numériques : les réponses oui / non et liste n'ont ni écart, ni historique, ni format
    # organisations ouvertes pendant la période, comme les calculs et les règles 
    reponses = [r for r in qs if r.kpi.actif and not r.kpi.est_calcule and r.kpi.est_numerique and (r.valeur is not None or r.non_applicable)
                and ouverte(r.organisation, p)]
    comp = S.periode_comparaison(campagne)
    tolerance_fe, tolerance_detail, nb_annees, minimum = seuils()
    passees = Calendrier().precedentes(p, nb_annees)  # même période des années précédentes
    ids = {r.kpi_id for r in reponses}
    historique, reference = {}, {}
    for k, o, per, v, na in Reponse.objects.filter(periode__in=passees, kpi_id__in=ids).values_list(
            "kpi_id", "organisation_id", "periode_id", "valeur", "non_applicable"):
        historique.setdefault((k, o), {})[per] = NA if na else v
    if comp is not None:
        for k, o, v, na in Reponse.objects.filter(periode=comp, kpi_id__in=ids).values_list("kpi_id", "organisation_id", "valeur", "non_applicable"):
            reference[(k, o)] = NA if na else v
    detections = []
    calc = None
    for r in reponses:
        k, o = r.kpi, r.organisation
        v = NA if r.non_applicable else r.valeur
        h = historique.get((k.pk, o.pk), {})
        n1 = reference.get((k.pk, o.pk))
        empreinte = "N/A" if v is NA else str(v.normalize())
        texte = _f(v, k)
        passees_valeurs = [x for x in h.values() if x is not NA and x is not None]
        # rupture de série
        if v is NA and n1 not in (None, NA):
            detections.append(_detection(k, o, C.RUPTURE, _t("saisie.coherence.msg.rupture_na", periode=p, comparaison=comp),
                                         "N/A", _t("saisie.coherence.ref.periode", periode=comp, valeur=_f(n1, k)), empreinte=empreinte))
            continue
        if v is NA:
            continue
        # écart avec le détail (valeur saisie au-dessus de la granularité)
        if k.saisissable_au_dessus and k.methode_agregation == k.Agregation.SOMME and o.niveau_id != k.granularite_id:
            calc = calc or Calculateur(p)
            detail = calc._agreger(k, o, p)
            if detail is not None and detail is not NA and abs(v - detail) > abs(detail) * tolerance_detail:
                message = (_t("saisie.coherence.msg.detail_ecart", ecart=_pct((v - detail) / abs(detail))) if detail
                           else _t("saisie.coherence.msg.detail"))
                detections.append(_detection(k, o, C.DETAIL, message,
                                             texte, _t("saisie.coherence.ref.detail", valeur=_f(detail, k)),
                                             empreinte=f"{empreinte}|{detail.normalize()}"))
        if n1 is NA:
            detections.append(_detection(k, o, C.RUPTURE, _t("saisie.coherence.msg.rupture_valeur", periode=p, comparaison=comp),
                                         texte, _t("saisie.coherence.ref.periode", periode=comp, valeur="N/A"), empreinte=empreinte))
        elif v == 0 and passees_valeurs and all(x > 0 for x in passees_valeurs):
            detections.append(_detection(k, o, C.RUPTURE, _t("saisie.coherence.msg.rupture_zero"), texte,
                                         _t("saisie.coherence.ref.periode", periode=comp, valeur=_f(n1, k)) if n1 is not None else "",
                                         empreinte=empreinte))
        # format
        if v < 0:
            detections.append(_detection(k, o, C.FORMAT, _t("saisie.coherence.msg.negative"), texte, empreinte=empreinte))
        elif k.est_entier and v != v.to_integral_value():
            detections.append(_detection(k, o, C.FORMAT, _t("saisie.coherence.msg.decimal_comptage", unite=_unite(k)), texte,
                                         empreinte=empreinte))
        # paramètre hérité (facteur d'émission) modifié
        if k.est_herite:
            e = S.ecart(v, n1) if n1 is not NA else None  # sans N-1, N-1 nul ou N/A : pas d'écart
            if e is not None and abs(e) > tolerance_fe:
                detections.append(_detection(k, o, C.FE, _t("saisie.coherence.msg.fe_modifie", type=k.type_saisie, comparaison=comp,
                                                            ecart=_pct(e)),
                                             texte, _t("saisie.coherence.ref.periode", periode=comp, valeur=_f(n1, k)), empreinte=empreinte))
            continue
        # écart avec N-1 (le commentaire vaut justification)
        ecart_signale = False
        if not S.ecart_justifie(r):
            e = S.ecart(v, n1) if n1 is not NA else None  # sans N-1, N-1 nul ou N/A : pas d'écart
            if S.depasse_seuil(e, campagne.seuil_ecart):
                ecart_signale = True
                detections.append(_detection(k, o, C.ECART_N1, _t("saisie.coherence.msg.ecart_n1", valeur=texte, reference=_f(n1, k),
                                                                   comparaison=comp, ecart=_pct(e)),
                                             texte, _t("saisie.coherence.ref.periode", periode=comp, valeur=_f(n1, k)), empreinte=empreinte))
        # hors historique
        if not ecart_signale and len(passees_valeurs) >= minimum and campagne.seuil_historique:
            mediane = Decimal(str(statistics.median(passees_valeurs)))
            s = campagne.seuil_historique
            if mediane > 0 and (v > mediane * s or v < mediane / s):
                detections.append(_detection(
                    k, o, C.HISTORIQUE, constat_historique(v, mediane, k, len(passees_valeurs), p.annuelle),
                    texte, _t("saisie.coherence.ref.mediane", valeur=_f(mediane, k)), empreinte=empreinte))
    return detections


def alertes_visibles(utilisateur, campagne, cases=None, personnel=False, qs=None):
    """Admin : toutes (sur « Pour moi », ``personnel`` : celles de ses cases). Contributeur : ses cases. Validateur :
    son périmètre (et les calculs impossibles qu'il peut voir). Règle de la page Cohérence, la seule.
    ``cases`` : {(KPI, organisation)} du périmètre s'il est déjà connu (sinon relu) ; ``qs`` : alertes à trier."""
    if qs is None:
        # KPI avec son type et son unité : la valeur et la référence d'une alerte s'affichent à son format (texte_alerte)
        qs = Alerte.objects.filter(campagne=campagne).select_related(*AVEC_KPI, "organisation", "regle", "justifie_par", "traite_par")
    if utilisateur.voit_tout and not personnel and utilisateur.orgs_permises() is None:
        return list(qs)
    if cases is None:
        cases = {(k.pk, o.pk) for k, o in S.cellules(utilisateur, personnel, campagne=campagne)}
    if not cases:  # rien dans le périmètre : aucune alerte visible (sans requête)
        return []
    orgs_calc = {o for _, o in cases}
    visibles = []
    for a in qs:
        if a.controle == C.CALCUL:
            if a.organisation_id in orgs_calc and S.voit_calcules(utilisateur, a.organisation):
                visibles.append(a)
        elif visible(a, cases):
            visibles.append(a)
    return visibles
