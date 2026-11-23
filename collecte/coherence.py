"""Cohérence des données : contrôles automatiques et règles entre KPI (onglet Cohérence).

Contrôles automatiques (non bloquants), sur les KPI du référentiel de la campagne et sur sa période :
- écart avec la période de comparaison (N-1 ou période précédente, réglage du référentiel) au-delà du seuil de la
  campagne, sans commentaire ;
- valeur hors historique : plus de « seuil » fois la médiane de la même période des années précédentes, ou moins de 1/seuil ;
- facteur d'émission modifié par rapport à la période de comparaison ;
- rupture de série : 0 alors que l'historique est positif, N/A alors qu'il y avait une valeur (et inversement) ;
- format : valeur négative, décimales sur un comptage ;
- calcul impossible (division par zéro…), pour l'admin et les validateurs ;
- écart avec le détail : une valeur saisie au-dessus de la granularité (saisie aux niveaux supérieurs) différente de la
  somme des organisations du dessous, quand ce détail est complet.
Règles entre KPI : réglées par l'admin ; une règle « bloquante » empêche de valider.

Chaque alerte garde son statut (justifiée, acceptée…) tant que les valeurs contrôlées ne changent pas ;
elle passe « corrigée » d'elle-même quand le contrôle redevient bon.
"""
import statistics
from collections import namedtuple
from decimal import Decimal

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from parametres import langues as L
from parametres import libelles as LB
from parametres.libelles import choix as _choix
from parametres.libelles import libelle
from referentiel import formule as F

from . import regles_textes as RT
from . import saisie as S
from .calcul import NA, Calculateur, arbre_ouverture, ouverte
from .models import Alerte, Campagne, Journal, RegleCoherence, Reponse
from .periodes import Calendrier
from .templatetags.collecte import arrondi, avec_pourcent, formater, nombre
from espaces import contexte as ESP

C = Alerte.Controle


class Texte(str):
    """Texte enregistré avec l'alerte (constat, valeur, référence), dans la langue par défaut de l'installation (exports,
    anciennes versions), qui garde dans ``spec`` de quoi le recomposer dans la langue de la personne qui lit la page
    (``composer``) : l'alerte est calculée une fois, puis lue par des personnes qui n'ont pas la même langue."""

    spec = None


def _texte(chaine, spec):
    t = Texte(chaine)
    t.spec = spec
    return t


def _spec(v):
    """Paramètre d'un libellé, enregistrable en JSON : texte recomposable, objet traduit (période, type de saisie :
    relu à l'affichage), sinon le texte tel quel."""
    from django.db.models import Model

    if isinstance(v, Texte) and v.spec is not None:
        return v.spec
    if v is None:
        return ""
    if isinstance(v, Model):
        return {"objet": v._meta.label_lower, "pk": v.pk}
    return str(v)


def _t(cle, n=None, **valeurs):
    """Texte d'une alerte dans la langue par défaut de l'installation, recomposable dans une autre (``Texte``)."""
    return _texte(libelle(cle, L.defaut(), n, **valeurs), {"cle": cle, "n": n, "v": {k: _spec(v) for k, v in valeurs.items()}})


def _f(v, kpi):
    """Valeur au format du KPI (« 84,90 t »), recomposable : l'unité suit la langue de la personne qui lit."""
    if isinstance(v, Decimal):
        return _texte(formater(v, kpi), {"val": str(v), "kpi": kpi.pk})
    return formater(v, kpi)


def _empreinte(v):
    """Empreinte d'une valeur contrôlée : ce qui fait rouvrir une alerte justifiée quand la valeur change."""
    return "N/A" if v is NA else str(v.normalize())


def _paresseux(fonction, *args):
    """``fonction(*args)`` calculée au premier appel seulement, puis gardée (texte d'une valeur qui n'est écrit que si
    une détection le cite : la plupart des réponses contrôlées n'en ont aucune)."""
    resultat = []

    def valeur():
        if not resultat:
            resultat.append(fonction(*args))
        return resultat[0]

    return valeur


def _unite(kpi):
    """Unité d'un KPI dans un texte d'alerte : l'objet (son symbole suit la langue de la personne qui lit), sinon le texte."""
    return kpi.unite if kpi.unite_id and not kpi.est_pourcentage else kpi.symbole


def _objet(etiquette, pk, alerte=None):
    """Objet cité par un texte d'alerte (KPI, période, type de saisie), lu une fois par requête (état des langues)."""
    from django.apps import apps

    if alerte is not None and etiquette == "referentiel.kpi" and pk == alerte.kpi_id:
        return alerte.kpi
    e = L.etat()
    cache = e.__dict__.setdefault("_objets_alertes", {})
    if (etiquette, pk) not in cache:
        try:
            modele = apps.get_model(etiquette)
        except LookupError:
            modele = None
        cache[(etiquette, pk)] = modele.objects.filter(pk=pk).first() if modele is not None else None
    return cache[(etiquette, pk)]


def composer(spec, alerte=None):
    """Texte d'un ``Texte.spec`` dans la langue de l'interface en cours (libellés) et des contenus (unités, périodes)."""
    if spec is None or isinstance(spec, str):
        return spec or ""
    if "cle" in spec:  # le nom d'une règle d'un modèle de la bibliothèque suit la langue de la personne qui lit
        return libelle(spec["cle"], None, spec.get("n"), **{k: RT.traduire(v) if k == "regle" and isinstance(v, str) else composer(v, alerte)
                                                             for k, v in (spec.get("v") or {}).items()})
    if "val" in spec:
        kpi = _objet("referentiel.kpi", spec.get("kpi"), alerte)
        try:
            v = Decimal(spec["val"])
        except ArithmeticError:
            return spec["val"]
        return formater(v, kpi) if kpi is not None else nombre(v, 2)
    if "pct" in spec or "fois" in spec:  # écart en %, rapport : au format de la langue de la personne qui lit
        try:
            return _ecrire_pct(Decimal(spec["pct"])) if "pct" in spec else _ecrire_fois(Decimal(spec["fois"]))
        except ArithmeticError:
            return spec.get("pct", spec.get("fois"))
    if "objet" in spec:
        o = _objet(spec["objet"], spec.get("pk"), alerte)
        return str(o) if o is not None else ""
    return ""


def texte_alerte(alerte, champ):
    """« message », « valeur » ou « reference » d'une alerte, dans la langue de la personne qui lit ; le texte enregistré
    s'il n'a pas de quoi être recomposé (ancienne alerte « calcul impossible »)."""
    spec = (alerte.textes or {}).get(champ)
    if spec:
        try:
            return composer(spec, alerte)
        except Exception:  # noqa: BLE001 - texte abîmé : le texte enregistré, jamais d'erreur à l'affichage
            pass
    return getattr(alerte, champ)


def seuils():
    """Seuils des contrôles automatiques, réglés dans Paramètres › Seuils de suivi : écart toléré sur un paramètre
    hérité et avec le détail (fractions), années comparées et valeurs passées nécessaires pour « hors historique »."""
    from parametres.models import Instance

    i = Instance.courante()
    return i.tolerance_fe, i.tolerance_detail, i.historique_annees, i.historique_minimum


def _ecrire_pct(x, langue=None):
    signe = "+" if x > 0 else ""
    return avec_pourcent(f"{signe}{nombre(x * 100, 0, langue)}", langue)


def _ecrire_fois(x, langue=None):
    return nombre(x, 1, langue) if arrondi(x, 1) < 10 else nombre(x, 0, langue)


def _pct(x):
    """Écart en pourcentage (« +12 % »), recomposable : écrit au format de la langue de la personne qui lit (le texte
    enregistré est dans la langue par défaut de l'installation, comme le reste de l'alerte)."""
    return _texte(_ecrire_pct(x, L.defaut()), {"pct": str(x)})


def _fois(x):
    """Rapport lisible : « 2,6 » sous 10, « 83 » au-delà, « 3 480 000 » avec séparateur de milliers ; recomposable comme
    ``_pct``."""
    return _texte(_ecrire_fois(x, L.defaut()), {"fois": str(x)})


def constat_historique(v, mediane, kpi, nb, annuelle):
    """Constat en clair d'une valeur hors historique : « 42 h, contre environ 3 480 h d'habitude (médiane des 5 exercices
    précédents) : 83 fois moins. » Le rapport n'est donné que pour une valeur positive (0 ou une valeur négative : pas de
    « fois », qui diviserait par zéro ou n'aurait pas de sens)."""
    base = _t("saisie.coherence.constat.historique_" + ("exercices" if annuelle else "annees"), nb,
              valeur=_f(v, kpi), mediane=_f(mediane, kpi))
    if v > 0 and mediane > 0:
        if v >= mediane:
            return _t("saisie.coherence.constat.fois_plus", base=base, fois=_fois(v / mediane))
        return _t("saisie.coherence.constat.fois_moins", base=base, fois=_fois(mediane / v))
    return _t("saisie.coherence.constat.sans_rapport", base=base)


def constat_lisible(alerte):
    """Constat d'une alerte à afficher (liste, panneau, page Cohérence). Les alertes enregistrées avant l'étape 4 gardent
    leur ancien message tant que le contrôle n'est pas relancé : « 0,0 × la médiane des 5 exercices
    précédents. », « +68 % par rapport à N-1, sans commentaire. ». Elles sont réécrites ici en clair, à partir de leur
    valeur et de leur référence, sans recontrôle ni écriture en base ; les autres messages sont rendus tels quels.
    Une alerte qui garde ses clés de libellés (``textes``) est recomposée dans la langue de la personne qui lit."""
    if (alerte.textes or {}).get("message"):
        return texte_alerte(alerte, "message")
    m, ref = alerte.message, alerte.reference
    if alerte.controle == C.HISTORIQUE and " × la médiane " in m and alerte.valeur and ref.startswith("médiane : "):
        rapport, reste = m.split(" × la ", 1)
        reste = reste.rstrip(".").replace(" (même période)", ", à la même période")  # « médiane des 5 exercices précédents »
        base = libelle("saisie.coherence.constat.historique_ancien", valeur=alerte.valeur, mediane=ref.removeprefix("médiane : "), reste=reste)
        try:
            r = Decimal(rapport.strip().replace(",", "."))
        except ArithmeticError:
            r = None
        # « fois plus » d'après le rapport enregistré (arrondi à 0,1) ; sous 1 (« 0,0 », « 0,1 »), l'arrondi ne permet pas
        # un « fois moins » juste : rien n'est ajouté
        if r is not None and r >= 1:
            return libelle("saisie.coherence.constat.fois_plus", base=base, fois=_ecrire_fois(r))
        return libelle("saisie.coherence.constat.sans_rapport", base=base)
    if alerte.controle == C.ECART_N1 and m.endswith(", sans commentaire.") and " par rapport à " in m and alerte.valeur \
            and " : " in ref:
        periode, valeur = ref.split(" : ", 1)
        return libelle("saisie.coherence.constat.ecart_ancien", valeur=alerte.valeur, reference=valeur, periode=periode,
                  ecart=m.split(" par rapport à ", 1)[0])
    return m


def _detection(kpi, org, controle, message, valeur="", reference="", gravite=Alerte.Gravite.ALERTE, empreinte="", regle=None, kpis=""):
    textes = {champ: t.spec for champ, t in (("message", message), ("valeur", valeur), ("reference", reference))
              if isinstance(t, Texte) and t.spec is not None}
    return {"kpi": kpi, "org": org, "controle": controle, "message": message[:400], "valeur": valeur[:120], "reference": reference[:200],
            "gravite": gravite, "empreinte": empreinte[:200], "regle": regle, "kpis_concernes": kpis, "textes": textes}


# ---------------------------------------------------------------- contrôles automatiques
# KPI d'une réponse avec son type de saisie, son type de réponse et son unité (lus pour chaque réponse : est_calcule,
# est_numerique, formater) : select_related("kpi") seul ne reprend pas ceux du KPIManager
AVEC_KPI = ("kpi__type_saisie", "kpi__type_reponse", "kpi__unite")

def perimetre(campagne):
    """Codes des KPI contrôlés pour la campagne (son référentiel et les sources de ses formules) ; None : tous."""
    if not hasattr(campagne, "_perimetre"):
        codes = S.codes_campagne(campagne)
        campagne._perimetre = None if codes is None else codes[1]
    return campagne._perimetre


# réponse contrôlée : ce que les contrôles lisent d'une réponse (``S.ecart_justifie`` lit son commentaire)
_Controlee = namedtuple("_Controlee", "kpi organisation valeur non_applicable commentaire kpi_id organisation_id")


def controles_automatiques(campagne, kpi_ids=None, calc=None):
    """Détections sur les valeurs saisies ou importées de la période de la campagne. ``calc`` : calculateur de la
    période déjà ouvert (partagé avec les règles entre KPI : les saisies de la période ne sont lues qu'une fois)."""
    from referentiel.models import KPI, Organisation

    p = campagne.periode
    # contrôles numériques : les réponses oui / non et liste n'ont ni écart, ni historique, ni format. Le filtre sur le
    # KPI est fait une fois par KPI, et chaque KPI, chaque organisation n'est lu qu'une fois (objets partagés par leurs
    # réponses) : relire KPI, types et organisation avec chacune des 70 000 réponses d'une grosse campagne prenait
    # 11 s. Même résultat que la lecture réponse par réponse (test_controles_automatiques_volume).
    kpis = KPI.objects.all()
    codes = perimetre(campagne)
    if codes is not None:
        kpis = kpis.filter(pk__in=codes)
    if kpi_ids is not None:
        kpis = kpis.filter(pk__in=kpi_ids)
    kpis = {k.pk: k for k in kpis if k.actif and not k.est_calcule and k.est_numerique}
    lues = list(Reponse.objects.filter(periode=p, origine__in=[Reponse.Origine.SAISIE, Reponse.Origine.IMPORT], kpi_id__in=list(kpis))
                .filter(Q(valeur__isnull=False) | Q(non_applicable=True)).order_by("pk")
                .values_list("kpi_id", "organisation_id", "valeur", "non_applicable", "commentaire"))
    orgs = Organisation.objects.in_bulk({o for _, o, *_ in lues})
    # organisations ouvertes pendant la période, comme les calculs et les règles 
    arbre = arbre_ouverture(p)  # celui de la clôture pour un exercice clos ou rouvert « garder »
    reponses = [_Controlee(kpis[k], orgs[o], v, na, c, k, o) for k, o, v, na, c in lues
                if o in arbre and ouverte(arbre[o], p, arbre)]
    comp = S.periode_comparaison(campagne)
    tolerance_fe, tolerance_detail, nb_annees, minimum = seuils()
    passees = Calendrier().precedentes(p, nb_annees)  # même période des années précédentes
    ids = {r.kpi_id for r in reponses}
    historique, reference = {}, {}
    # seules les cases contrôlées sont lues (même KPI et même organisation qu'une réponse saisie ou importée de la
    # période) ; la période de comparaison, le plus souvent l'exercice précédent, est prise dans la même lecture quand
    # elle fait partie de l'historique
    controlee = Exists(Reponse.objects.filter(periode=p, origine__in=[Reponse.Origine.SAISIE, Reponse.Origine.IMPORT],
                                              kpi_id=OuterRef("kpi_id"), organisation_id=OuterRef("organisation_id")))
    dans_historique = comp is not None and comp.pk in {q.pk for q in passees}
    for k, o, per, v, na in Reponse.objects.filter(controlee, periode__in=passees, kpi_id__in=ids).values_list(
            "kpi_id", "organisation_id", "periode_id", "valeur", "non_applicable"):
        historique.setdefault((k, o), {})[per] = NA if na else v
        if dans_historique and per == comp.pk:
            reference[(k, o)] = NA if na else v
    if comp is not None and not dans_historique:
        for k, o, v, na in Reponse.objects.filter(controlee, periode=comp, kpi_id__in=ids).values_list(
                "kpi_id", "organisation_id", "valeur", "non_applicable"):
            reference[(k, o)] = NA if na else v
    # valeurs passées qui ne comptent pas (organisation pas ouverte dans cette période, KPI qui n'y était pas demandé) :
    # ni référence de l'écart, ni historique (``saisie.cases_comparables``, la règle de la saisie et du calcul)
    par_periode, periodes = {}, {q.pk: q for q in passees}
    for cle, h in historique.items():
        for per in h:
            par_periode.setdefault(per, set()).add(cle)
    if comp is not None:
        periodes[comp.pk] = comp
        par_periode.setdefault(comp.pk, set()).update(reference)
    comparables = {per: S.cases_comparables(periodes[per], paires) for per, paires in par_periode.items()}
    historique = {cle: {per: v for per, v in h.items() if cle in comparables[per]} for cle, h in historique.items()}
    reference = {cle: v for cle, v in reference.items() if comp is not None and cle in comparables[comp.pk]}
    detections = []
    for r in reponses:
        k, o = r.kpi, r.organisation
        v = NA if r.non_applicable else r.valeur
        h = historique.get((r.kpi_id, r.organisation_id), {})
        n1 = reference.get((r.kpi_id, r.organisation_id))
        empreinte = _paresseux(_empreinte, v)  # comme le texte : seulement si une détection la garde
        texte = _paresseux(_f, v, k)  # valeur au format du KPI, écrite seulement si une détection la cite
        passees_valeurs = [x for x in h.values() if x is not NA and x is not None]
        # rupture de série
        if v is NA and n1 not in (None, NA):
            detections.append(_detection(k, o, C.RUPTURE, _t("saisie.coherence.msg.rupture_na", periode=p, comparaison=comp),
                                         "N/A", _t("saisie.coherence.ref.periode", periode=comp, valeur=_f(n1, k)), empreinte=empreinte()))
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
                                             texte(), _t("saisie.coherence.ref.detail", valeur=_f(detail, k)),
                                             empreinte=f"{empreinte()}|{detail.normalize()}"))
        if n1 is NA:
            detections.append(_detection(k, o, C.RUPTURE, _t("saisie.coherence.msg.rupture_valeur", periode=p, comparaison=comp),
                                         texte(), _t("saisie.coherence.ref.periode", periode=comp, valeur="N/A"), empreinte=empreinte()))
        elif v == 0 and passees_valeurs and all(x > 0 for x in passees_valeurs):
            detections.append(_detection(k, o, C.RUPTURE, _t("saisie.coherence.msg.rupture_zero"), texte(),
                                         _t("saisie.coherence.ref.periode", periode=comp, valeur=_f(n1, k)) if n1 is not None else "",
                                         empreinte=empreinte()))
        # format
        if v < 0:
            detections.append(_detection(k, o, C.FORMAT, _t("saisie.coherence.msg.negative"), texte(), empreinte=empreinte()))
        elif k.est_entier and v != v.to_integral_value():
            detections.append(_detection(k, o, C.FORMAT, _t("saisie.coherence.msg.decimal_comptage", unite=_unite(k)), texte(),
                                         empreinte=empreinte()))
        # paramètre hérité (facteur d'émission) modifié
        if k.est_herite:
            e = S.ecart(v, n1) if n1 is not NA else None  # sans N-1, N-1 nul ou N/A : pas d'écart
            if e is not None and abs(e) > tolerance_fe:
                detections.append(_detection(k, o, C.FE, _t("saisie.coherence.msg.fe_modifie", type=k.type_saisie, comparaison=comp,
                                                            ecart=_pct(e)),
                                             texte(), _t("saisie.coherence.ref.periode", periode=comp, valeur=_f(n1, k)), empreinte=empreinte()))
            continue
        # écart avec N-1 (le commentaire vaut justification)
        ecart_signale = False
        if not S.ecart_justifie(r):
            e = S.ecart(v, n1) if n1 is not NA else None  # sans N-1, N-1 nul ou N/A : pas d'écart
            if S.depasse_seuil(e, campagne.seuil_ecart):
                ecart_signale = True
                detections.append(_detection(k, o, C.ECART_N1, _t("saisie.coherence.msg.ecart_n1", valeur=texte(), reference=_f(n1, k),
                                                                   comparaison=comp, ecart=_pct(e)),
                                             texte(), _t("saisie.coherence.ref.periode", periode=comp, valeur=_f(n1, k)), empreinte=empreinte()))
        # hors historique
        if not ecart_signale and len(passees_valeurs) >= minimum and campagne.seuil_historique:
            mediane = Decimal(str(statistics.median(passees_valeurs)))
            s = campagne.seuil_historique
            if mediane > 0 and (v > mediane * s or v < mediane / s):
                detections.append(_detection(
                    k, o, C.HISTORIQUE, constat_historique(v, mediane, k, len(passees_valeurs), p.annuelle),
                    texte(), _t("saisie.coherence.ref.mediane", valeur=_f(mediane, k)), empreinte=empreinte()))
    return detections


def controles_calcul(campagne):
    """Calculs impossibles (division par zéro, formule invalide) : information pour l'admin."""
    qs = Reponse.objects.filter(periode=campagne.periode, statut=Reponse.Statut.ERREUR).select_related(*AVEC_KPI, "organisation")
    codes = perimetre(campagne)
    sortie = []
    for r in qs:
        if r.kpi.actif and (codes is None or r.kpi_id in codes):
            message, empreinte = message_calcul(r.message_calcul)
            sortie.append(_detection(r.kpi, r.organisation, C.CALCUL, message, gravite=Alerte.Gravite.INFO, empreinte=empreinte))
    return sortie


def spec_texte(texte, langue=None, profondeur=0):
    """``Texte.spec`` d'un texte rédigé par un libellé (motif d'un calcul impossible, écrit par le calcul dans la langue de
    l'installation) : la clé et ses paramètres, retrouvés depuis le texte (``libelles.retrouver``), les paramètres
    eux-mêmes faits d'un libellé aussi (« Erreur : {detail} ») ; None si le texte ne vient d'aucun libellé connu."""
    trouve = LB.retrouver(texte, langue or L.defaut()) if texte else None
    if trouve is None:
        return None
    cle, valeurs = trouve
    v = {k: (spec_texte(x, langue, profondeur + 1) if profondeur < 2 else None) or x for k, x in valeurs.items()}
    n = int(v["n"]) if isinstance(v.get("n"), str) and v["n"].isdigit() else None
    return {"cle": cle, "n": n, "v": v}


def message_calcul(texte):
    """(message, empreinte) d'une alerte « calcul impossible » : message recomposable dans la
    langue de la personne qui lit (``Texte`` et sa ``spec``) et empreinte qui ne dépend d'aucune langue (clé et
    paramètres) ; un motif qui ne vient d'aucun libellé garde son texte, comme avant."""
    if not texte:
        return _t("saisie.coherence.msg.calcul_impossible"), ""
    spec = spec_texte(texte)
    if spec is None:
        return texte, texte
    return _texte(texte, spec), empreinte_calcul(spec)


def empreinte_calcul(spec):
    """Empreinte d'un motif de calcul impossible : clé et paramètres (aucune langue) ; sert aussi à la migration 0040."""
    import hashlib
    import json

    return "calc:" + hashlib.sha256(json.dumps(spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ---------------------------------------------------------------- règles entre KPI
def evaluer(calc, texte, org, periode=None):
    """Valeur d'une expression pour une organisation sur une période : Decimal, NA ou None si une source manque."""
    periode = periode or calc.periode

    def resoudre(ref):
        q = calc.calendrier.resoudre(periode, ref.decalage)
        return calc.valeur(ref.kpi, org.id, q) if q is not None else None

    try:
        return F.evaluer(F.analyser(texte), resoudre)
    except (F.ValeurManquante, F.ErreurCalcul, F.FormuleInvalide):
        return None


def respecte(regle, g, d):
    # comparer ce que la base garde (10 décimales) : en mémoire, [X] + [X] + [X] avec X = 1 / 3 valait 0,9999… ≠ 1
    g, d = (round(v, 10) if isinstance(v, Decimal) else v for v in (g, d))
    tol = abs(d) * regle.tolerance if d else regle.tolerance
    return {"<=": g <= d + tol, ">=": g >= d - tol, "=": abs(g - d) <= tol, "<": g < d + tol, ">": g > d - tol}[regle.operateur]


def kpi_d_affichage(calc_kpis, texte, autre=""):
    """KPI dont le format sert à afficher un côté de règle : son premier KPI, sinon celui de l'autre côté (« [TXF] <= 0.3 » :
    0,3 s'affiche comme le taux, en pourcentage)."""
    for t in (texte, autre):
        try:
            refs = F.references(t)
        except F.FormuleInvalide:
            refs = []
        if refs:
            return calc_kpis.get(refs[0].kpi)
    return None


def afficher(v, kpi):
    """Valeur d'un côté de règle : au format du KPI s'il est en pourcentage (×100, « % »), sinon à 2 décimales, avec le
    séparateur de milliers de l'outil (« 1 131,00 »)."""
    from .templatetags.collecte import formater, nombre

    if kpi is not None and kpi.est_pourcentage:
        return formater(v, kpi)
    return nombre(v, 2)


def kpis_de(regle):
    try:
        return list(dict.fromkeys(r.kpi for r in F.references(regle.gauche) + F.references(regle.droite)))
    except F.FormuleInvalide:
        return []


def doublons(regles):
    """{pk d'une règle en double : règle gardée} parmi ``regles`` : une règle = une condition (``regles_textes.condition``).
    Deux règles qui contrôlent la même chose sous deux noms (même contrôle installé par deux modèles, nom traduit) ne
    donnent qu'une alerte : celle de la règle gardée, la bloquante s'il y en a une, sinon la plus ancienne."""
    groupes = {}
    for r in regles:
        groupes.setdefault(RT.condition_de(r), []).append(r)
    sortie = {}
    for g in groupes.values():
        if len(g) > 1:
            gardee = min(g, key=lambda r: (not r.bloquante, r.pk or 0))
            sortie.update({r.pk: gardee for r in g if r is not gardee})
    return sortie


def sans_doublons(regles):
    doubles = doublons(regles)
    return [r for r in regles if r.pk not in doubles]


def controles_regles(campagne, calc=None, regles=None, orgs=None):
    calc = calc or Calculateur(campagne)
    regles = regles if regles is not None else sans_doublons(list(RegleCoherence.objects.filter(actif=True)))
    codes = perimetre(campagne)
    detections = []
    for regle in regles:
        ids = kpis_de(regle)
        if not ids or ids[0] not in calc.kpis or (codes is not None and ids[0] not in codes):
            continue  # la règle se contrôle dans les campagnes qui contiennent son premier KPI
        kpi = calc.kpis[ids[0]]
        arbre = calc.orgs_de(calc.periode)  # arbre de la période (celui de sa clôture si elle est close ou gardée)
        for org in orgs or arbre.values():
            # organisations ouvertes pendant la période, comme les calculs : un site fermé
            # en juin est encore contrôlé sur sa dernière année
            org = arbre.get(org.id)
            if org is None or org.niveau_id != regle.niveau_id or not ouverte(org, calc.periode, arbre):
                continue
            g, d = evaluer(calc, regle.gauche, org), evaluer(calc, regle.droite, org)
            if g is None or d is None or g is NA or d is NA or respecte(regle, g, d):
                continue
            kg = kpi_d_affichage(calc.kpis, regle.gauche, regle.droite)
            kd = kpi_d_affichage(calc.kpis, regle.droite, regle.gauche)
            detections.append(_detection(
                kpi, org, C.REGLE, _t("saisie.coherence.msg.regle_non_respectee", regle=regle.nom),
                afficher(g, kg), _t("saisie.coherence.ref.regle", operateur=_choix(regle, "operateur", L.defaut()).split(" ")[0],
                                    valeur=afficher(d, kd)),
                gravite=Alerte.Gravite.BLOQUANTE if regle.bloquante else Alerte.Gravite.ALERTE,
                empreinte=f"{g}|{d}", regle=regle, kpis=" ".join(ids)))
    return detections


def regles_bloquantes_en_echec(campagne, kpi, org, caches=frozenset()):
    """Motifs qui empêchent de valider la cellule (règles bloquantes qui citent ce KPI). ``caches`` : KPI dont la valeur
    ne doit pas sortir (serveur MCP, KPI sensibles non donnés aux assistants) : une règle qui en cite un donne un motif
    générique, sans son nom, ses valeurs ni son explication."""
    regles = sans_doublons([r for r in RegleCoherence.objects.filter(actif=True, bloquante=True, niveau_id=org.niveau_id)
                            if kpi.pk in kpis_de(r)])
    if not regles:
        return []
    return [libelle("saisie.coherence.erreur.bloquante_sensible") if caches and set(kpis_de(d["regle"])) & set(caches)
            else libelle("saisie.coherence.erreur.bloquante", regle=d["regle"].nom_affiche, valeur=d["valeur"],
                         reference=composer(d["textes"].get("reference")) or d["reference"])
            + (f" {d['regle'].description_affichee}" if d["regle"].description else "")
            for d in controles_regles(campagne, regles=regles, orgs=[org])]


# ---------------------------------------------------------------- alertes visibles et à justifier
def visible(alerte, cases):
    """Vrai si l'alerte porte sur une des cases (KPI, organisation) : sa case, ou pour une règle entre KPI, la case
    d'un des KPI qu'elle cite dans la même organisation. Les calculs impossibles sont traités à part."""
    if alerte.controle == C.REGLE:
        return any((k, alerte.organisation_id) in cases for k in alerte.kpis_concernes.split())
    return (alerte.kpi_id, alerte.organisation_id) in cases


def relier(alertes):
    """Alertes reliées à leur KPI (avec son type et son unité : la valeur et la référence d'une alerte s'affichent à
    son format, ``texte_alerte``), leur organisation, leur règle et les comptes qui les ont traitées, chaque objet lu
    une fois et partagé par ses alertes : un ``select_related`` relisait le KPI et ses traductions avec chacune des
    6 000 alertes d'une grosse campagne. Mêmes objets, mêmes valeurs."""
    from referentiel.models import KPI, Organisation, Utilisateur

    def lus(modele, *champs):
        ids = {getattr(a, c) for a in alertes for c in champs} - {None}
        return modele.objects.in_bulk(ids) if ids else {}

    kpis, orgs, regles = lus(KPI, "kpi_id"), lus(Organisation, "organisation_id"), lus(RegleCoherence, "regle_id")
    comptes = lus(Utilisateur, "justifie_par_id", "traite_par_id")
    for a in alertes:
        a.kpi, a.organisation = kpis[a.kpi_id], orgs[a.organisation_id]
        a.regle = regles.get(a.regle_id) if a.regle_id else None
        a.justifie_par = comptes.get(a.justifie_par_id) if a.justifie_par_id else None
        a.traite_par = comptes.get(a.traite_par_id) if a.traite_par_id else None
    return alertes


def alertes_visibles(utilisateur, campagne, cases=None, personnel=False, qs=None):
    """Admin : toutes (sur « Pour moi », ``personnel`` : celles de ses cases). Contributeur : ses cases. Validateur :
    son périmètre (et les calculs impossibles qu'il peut voir). Règle de la page Cohérence, la seule.
    ``cases`` : {(KPI, organisation)} du périmètre s'il est déjà connu (sinon relu) ; ``qs`` : alertes à trier."""
    if qs is None:
        qs = relier(list(Alerte.objects.filter(campagne=campagne)))
    if utilisateur.voit_tout and not personnel and utilisateur.orgs_permises() is None:
        return list(qs)
    if cases is None:
        cases = {(k.pk, o.pk) for k, o in S.cellules(utilisateur, personnel, campagne=campagne)}
    if not cases:  # rien dans le périmètre : aucune alerte visible (sans requête)
        return []
    orgs_calc = {o for _, o in cases}
    # une alerte visible porte toujours sur une organisation des cases (sa case, une case d'un KPI de sa règle dans la même
    # organisation, ou un calcul impossible d'une organisation des cases) : les autres ne sont pas lues (échelle, P-A9)
    if hasattr(qs, "filter"):  # (``peut_voir`` passe une liste d'une alerte)
        qs = qs.filter(organisation_id__in=orgs_calc)
    visibles, voit, arbre = [], {}, None
    for a in qs:
        if a.controle == C.CALCUL:
            if a.organisation_id not in orgs_calc:
                continue
            # même règle que le panneau de saisie, posée une fois par organisation, sur l'arbre déjà relié (les
            # ancêtres ne sont pas relus en base) : avant, deux à trois requêtes par calcul impossible
            if a.organisation_id not in voit:
                arbre = arbre or S.arbre_organisations()
                voit[a.organisation_id] = S.voit_calcules(utilisateur, arbre.get(a.organisation_id, a.organisation))
            if voit[a.organisation_id]:
                visibles.append(a)
        elif visible(a, cases):
            visibles.append(a)
    return visibles


def date_etat(alerte):
    """Date du dernier changement d'état d'une alerte (colonne « Depuis le » de la page Cohérence) : décision de
    l'administrateur, sinon justification, sinon création (justifier ou accepter met la date à jour)."""
    return max((d for d in (alerte.date_traitement, alerte.date_justification, alerte.date_creation) if d is not None), default=None)


def justifiable(alerte):
    """Vrai si l'alerte peut, par sa nature, recevoir une justification : pas un calcul impossible (une information pour
    l'administrateur, rien à justifier). Seule règle, lue par le panneau de saisie, la fiche de l'alerte et
    ``traiter`` (donc par l'outil MCP ``justify_alert``) ; ``motif_non_justifiable`` en donne l'explication (la fiche et l'outil MCP l'acceptaient). Une alerte justifiée avant la mise à jour reste telle quelle."""
    return alerte.controle != C.CALCUL


def motif_non_justifiable(alerte):
    """Explication, la même partout, quand ``justifiable`` est faux ; "" sinon."""
    return "" if justifiable(alerte) else libelle("saisie.coherence.alerte.calcul_non_justifiable")


def motif_justification_refusee(utilisateur, alerte, statut_campagne=None):
    """Seule règle qui décide si la personne peut justifier l'alerte, par sa nature et par l'état de sa campagne ; renvoie
    l'explication du refus (la même sur la fiche, dans le panneau de saisie et pour l'outil MCP ``justify_alert``), ""
    si la justification est permise. Calcul impossible : ``motif_non_justifiable``. Campagne clôturée (clôture
    définitive) : « administrateur seulement » : ni le contributeur ni le validateur ne
    justifient plus, l'administrateur finit sa revue ; une campagne en revue garde le comportement d'avant. Une
    justification déjà enregistrée reste telle quelle. ``statut_campagne`` : le statut relu sous verrou par ``traiter``."""
    if not justifiable(alerte):
        return motif_non_justifiable(alerte)
    statut = statut_campagne or alerte.campagne.statut
    if statut == Campagne.Statut.CLOTUREE and not utilisateur.est_admin:
        return libelle("saisie.coherence.alerte.campagne_cloturee")
    return ""


def a_justifier(alerte):
    """Vrai si l'alerte attend une justification : à traiter (ouverte ou rejetée) et justifiable (pas un calcul
    impossible). Même filtre, en base, dans ``alertes_a_traiter`` (``A_JUSTIFIER``)."""
    return alerte.a_traiter and justifiable(alerte)


A_JUSTIFIER = Q(statut__in=Alerte.A_TRAITER) & ~Q(controle=C.CALCUL)  # a_justifier, pour une requête


def explicable_par_ia(alerte, caches=None):
    """Vrai si « Expliquer avec l'IA » peut porter sur l'alerte : pas un calcul impossible (une information, rien à
    justifier, et son message de calcul cite des organisations, qui ne partent jamais chez le fournisseur ;
    docs/ai_socket.md, 6 a) ; pas une alerte qui cite un KPI sensible ou un de ses dérivés tant que le réglage
    « Les KPI sensibles peuvent être envoyés à l'assistant IA » est éteint (``caches`` : ``sensibles.caches_ia()``, lu
    ici s'il n'est pas donné)."""
    from .sensibles import alerte_sensible, caches_ia

    if alerte.controle == C.CALCUL:
        return False
    return not alerte_sensible(alerte, caches_ia() if caches is None else caches)


def alertes_a_traiter(utilisateur, campagne, cases=None, personnel=False):
    """Alertes que la personne peut justifier dans la campagne : visibles, à traiter (ouvertes ou rejetées),
    alertes de règle et alertes posées sur une organisation parente comprises, calculs impossibles exclus (ce sont
    des informations, personne ne peut les justifier). Source unique de « ce qui reste » : bandeau de Saisie, Pour
    moi, « Je réponds à » et tuile « À traiter » de la page Cohérence."""
    qs = Alerte.objects.filter(A_JUSTIFIER, campagne=campagne).select_related(*AVEC_KPI, "organisation")
    return alertes_visibles(utilisateur, campagne, cases, personnel, qs)


def peut_voir(utilisateur, alerte, cases=None):
    """Vrai si la personne voit l'alerte (et sa fiche) : la règle de la page Cohérence, seule. Une alerte déjà
    traitée (justifiée, acceptée…) reste visible. ``cases`` : {(KPI, organisation)} du périmètre, s'il est déjà lu."""
    return bool(alertes_visibles(utilisateur, alerte.campagne, cases=cases, qs=[alerte]))


def peut_justifier(utilisateur, alerte, cases=None):
    """Vrai si la personne peut justifier l'alerte : elle la voit, et son statut le permet (à traiter ou déjà justifiée)."""
    return (not utilisateur.lecture_seule and alerte.statut in TRANSITIONS["justifier"][0]
            and not motif_justification_refusee(utilisateur, alerte) and peut_voir(utilisateur, alerte, cases))


# ---------------------------------------------------------------- mise à jour des alertes
@ESP.atomic
def controler(campagne, kpi_ids=None):
    """Recalcule les détections et met les alertes à jour. kpi_ids : limiter aux KPI touchés par une saisie."""
    with L.session():  # langues lues une fois (hors requête : commandes, tests)
        return _controler(campagne, kpi_ids)


def controler_a_l_ouverture(campagne):
    """``controler`` pour l'ouverture de la page Cohérence, sans verrou quand rien ne change : les détections sont
    calculées hors transaction (lecture seule) et comparées aux alertes enregistrées ; seulement s'il y a une différence,
    ``controler`` prend le verrou et la transaction, et refait détections et comparaison sous verrou (une saisie a pu
    changer les valeurs entre-temps : rien n'est écrit d'après une lecture dépassée). Résultat identique à ``controler``.
    Avant, chaque ouverture verrouillait toutes les périodes pendant la détection (PostgreSQL : 5 s à gros volume, les
    saisies et recalculs attendaient)."""
    with L.session():
        detections, regles = _detections(campagne, None)
        a_creer, a_sauver, a_corriger = _mise_a_jour(campagne, None, detections, regles)
    if not (a_creer or a_sauver or a_corriger):
        return len(detections)
    return controler(campagne)


def _detections(campagne, kpi_ids):
    """(détections, règles contrôlées) : lecture seule. Textes bruts écrits dans la langue de l'installation, quelle que
    soit la langue de la personne qui lance le contrôle : chacun lit l'alerte recomposée
    dans sa langue, et un contrôle lancé dans une autre langue ne réécrit plus les alertes."""
    with L.activer_interface(L.defaut()):
        return _detections_installation(campagne, kpi_ids)


def _detections_installation(campagne, kpi_ids):
    regles = list(RegleCoherence.objects.filter(actif=True))
    if kpi_ids is not None:
        regles = [r for r in regles if set(kpis_de(r)) & set(kpi_ids)]
    calc = Calculateur(campagne) if regles else None  # un seul calculateur pour l'écart avec le détail et les règles
    detections = controles_automatiques(campagne, kpi_ids, calc)
    if kpi_ids is None:
        detections += controles_calcul(campagne)
    if regles:  # une règle en double (même condition qu'une autre) n'est pas contrôlée : une seule alerte par contrôle
        detections += controles_regles(campagne, calc, regles=sans_doublons(regles))
    return detections, regles


def _mise_a_jour(campagne, kpi_ids, detections, regles):
    """Ce qu'il faut écrire pour que les alertes suivent les détections, sans rien écrire : (alertes à créer, alertes
    modifiées à enregistrer, alertes à passer « corrigée »)."""
    existantes = Alerte.objects.filter(campagne=campagne)
    if kpi_ids is not None:
        existantes = existantes.filter(kpi_id__in=kpi_ids, controle__in=[c for c in C.values if c not in (C.REGLE, C.CALCUL)]) | \
            existantes.filter(regle__in=regles)
    par_cle = {(a.kpi_id, a.organisation_id, a.controle, a.regle_id): a for a in existantes}
    vues, a_creer, a_sauver = set(), [], []
    for d in detections:
        cle = (d["kpi"].pk, d["org"].pk, d["controle"], d["regle"].pk if d["regle"] else None)
        vues.add(cle)
        a = par_cle.get(cle)
        if a is None:
            a_creer.append(Alerte(campagne=campagne, kpi=d["kpi"], organisation=d["org"], controle=d["controle"], regle=d["regle"],
                                  kpis_concernes=d["kpis_concernes"], gravite=d["gravite"], message=d["message"], valeur=d["valeur"],
                                  reference=d["reference"], empreinte=d["empreinte"], textes=d["textes"]))
            continue
        champs = ("message", "valeur", "reference", "gravite", "statut", "empreinte", "textes")
        avant = [getattr(a, f) for f in champs]
        change = a.empreinte != d["empreinte"]
        if not (a.textes and a.textes == d["textes"]):  # mêmes clés et paramètres : le texte brut reste (aucune écriture)
            a.message, a.valeur, a.reference = d["message"], d["valeur"], d["reference"]
        a.gravite, a.textes = d["gravite"], d["textes"]
        if a.statut == Alerte.Statut.CORRIGEE or (change and a.statut != Alerte.Statut.OUVERTE):
            a.statut = Alerte.Statut.OUVERTE  # la valeur a changé : la justification précédente ne vaut plus
        a.empreinte = d["empreinte"]
        if [getattr(a, f) for f in champs] != avant and a not in a_sauver:  # rien de changé : pas d'écriture
            a_sauver.append(a)
    # alertes d'une règle en double (son contrôle est fait par la règle gardée, qui a sa propre alerte) : celles à traiter
    # passent « corrigée » (ouvertes ou rejetées : Alerte.A_TRAITER) ; une alerte déjà justifiée ou décidée garde son statut
    # et sa justification
    doubles = doublons(regles)
    a_corriger = [a for cle, a in par_cle.items() if cle not in vues and a.statut != Alerte.Statut.CORRIGEE
                  and not (a.regle_id in doubles and a.statut not in Alerte.A_TRAITER)]
    return a_creer, a_sauver, a_corriger


def _controler(campagne, kpi_ids):
    # un contrôle à la fois, avec le même verrou que le recalcul (calcul._recalculer) : deux ouvertures simultanées de la
    # page créaient la même alerte deux fois (PostgreSQL ; sous SQLite, les transactions se suivent déjà)
    list(type(campagne.periode).objects.select_for_update().order_by("pk").values_list("pk", flat=True))
    detections, regles = _detections(campagne, kpi_ids)
    a_creer, a_sauver, a_corriger = _mise_a_jour(campagne, kpi_ids, detections, regles)
    for a in a_sauver:
        a.save()
    Alerte.objects.bulk_create(a_creer, batch_size=1000)
    for a in a_corriger:
        a.statut = Alerte.Statut.CORRIGEE
        a.save(update_fields=["statut", "date_maj"])
    return len(detections)


# ---------------------------------------------------------------- traitement d'une alerte
TRANSITIONS = {
    "justifier": (Alerte.A_TRAITER + (Alerte.Statut.JUSTIFIEE,), Alerte.Statut.JUSTIFIEE),
    "accepter": ((Alerte.Statut.JUSTIFIEE,), Alerte.Statut.ACCEPTEE),
    "rejeter": ((Alerte.Statut.JUSTIFIEE,), Alerte.Statut.REJETEE),
    "ignorer": (Alerte.A_TRAITER + (Alerte.Statut.JUSTIFIEE,), Alerte.Statut.IGNOREE),
    "rouvrir": ((Alerte.Statut.ACCEPTEE, Alerte.Statut.IGNOREE, Alerte.Statut.REJETEE), Alerte.Statut.OUVERTE),
}


def traiter(utilisateur, alerte, action, texte=""):
    """Fait passer l'alerte à son nouveau statut. L'alerte est relue dans la transaction (verrouillée sous PostgreSQL)
    et seuls les champs de la décision sont écrits, par une mise à jour conditionnelle au statut relu : deux personnes
    qui décident en même temps à partir de la même page ne peuvent pas toutes deux « réussir », et la décision n'écrase
    pas ce qu'un contrôle a mis à jour entre-temps (message, valeur). Le second reçoit « déjà traitée »."""
    from django.core.exceptions import PermissionDenied, ValidationError

    if action not in TRANSITIONS:
        raise ValidationError(libelle("saisie.erreur.action_inconnue"))
    if action in ("accepter", "rejeter", "ignorer", "rouvrir") and not utilisateur.est_admin:
        raise PermissionDenied(libelle("saisie.erreur.reserve_admin"))
    departs, arrivee = TRANSITIONS[action]
    if action == "justifier" and motif_justification_refusee(utilisateur, alerte):  # même règle et même motif partout
        raise ValidationError(motif_justification_refusee(utilisateur, alerte))
    if alerte.statut not in departs:
        raise ValidationError(libelle("saisie.coherence.erreur.action_impossible", statut=_choix(alerte, "statut")))
    texte = (texte or "").strip()
    if action in ("justifier", "rejeter") and not texte:
        raise ValidationError(libelle("saisie.coherence.erreur.ecrire_explication" if action == "justifier"
                                      else "saisie.coherence.erreur.motif_rejet"))
    with ESP.atomic():
        fraiche = Alerte.objects.select_for_update().filter(pk=alerte.pk).first()
        if fraiche is None or fraiche.statut not in departs:
            raise ValidationError(libelle("saisie.coherence.erreur.deja_traitee"))
        if action == "justifier":  # alerte et statut de la campagne relus sous verrou (clôture pendant la saisie du texte)
            statut = Campagne.objects.select_for_update().filter(pk=fraiche.campagne_id).values_list("statut", flat=True).first()
            motif = motif_justification_refusee(utilisateur, fraiche, statut)
            if motif:
                raise ValidationError(motif)
        avant = fraiche.statut
        champs = {"statut": arrivee}
        if action == "justifier":
            champs.update(justification=texte, justifie_par=utilisateur, date_justification=timezone.now())
        else:
            champs.update(traite_par=utilisateur, date_traitement=timezone.now())
            if texte:
                champs["justification"] = (fraiche.justification + "\n" + _t("saisie.coherence.admin_ajout", texte=texte)).strip()
        if not Alerte.objects.filter(pk=alerte.pk, statut=avant).update(**champs):
            raise ValidationError(libelle("saisie.coherence.erreur.deja_traitee"))
        for nom, valeur in champs.items():
            setattr(alerte, nom, valeur)
        Journal.ecrire(utilisateur, f"alerte_{action}", alerte, "statut", avant, f"{arrivee}" + (f" : {texte}" if texte else ""))
    return alerte
