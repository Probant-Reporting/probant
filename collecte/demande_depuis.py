"""« Demandé depuis » : à partir de quelle période un référentiel demande un KPI (règle du projet :
« à la création d'un KPI, demander s'il doit être ajouté aux années précédentes ; dans la gestion des KPI, pouvoir
régler quels KPI sont arrivés quand »).

Règle exacte (à confirmer pour les points marqués) :

1. Chaque KPI d'un référentiel (``ElementReferentiel.demande_depuis``) porte le début de la première période où il est
   demandé. Vide : depuis le début (tous les éléments des installations existantes ; aucune date n'est devinée).
2. Le référentiel demande le KPI dans une période qui commence à cette date ou après (``filtre_demande`` : la seule
   règle, lue par ``saisie.codes_perimetre`` ; elle borne donc la grille, la case par l'adresse directe, le taux de
   remplissage, le tableau de bord, les relances, le fichier à remplir, les exports, les imports, les contrôles de
   cohérence, la Visualisation, le serveur MCP ET le calcul, ``calcul.perimetre_calcul``). Les sources des formules
   d'un KPI demandé restent demandées avec lui (un avertissement le dit quand l'une n'est demandée que plus tard).
3. Exercice clos (toutes les campagnes de la période clôturées) : son périmètre noté reste la vérité ; rien ne bouge
   tant qu'il est clos (ni case, ni total, ni taux de remplissage ; à confirmer). Un KPI dont la date a été avancée
   explicitement jusqu'à lui y entre à la réouverture (``entrees_explicites``, ajoutées par ``calcul.perimetre_gele``
   aux périodes rouvertes), dans les deux modes (« garder » : ses cases sont à saisir, les totaux suivent les
   saisies) ; la clôture suivante l'ajoute au périmètre noté (``calcul.geler_a_la_cloture``). Un élément sans date
   n'entre jamais dans un exercice clos où il n'était pas : c'est le comportement d'avant.
4. Création d'un élément sans choix explicite, par n'importe quelle porte : l'exercice en cours (``depuis_par_defaut``) ;
   un exercice rouvert n'est pas l'exercice en cours (l'administrateur peut le choisir).
5. Reculer la date (vers le futur) : refusé si une période qui perdrait le KPI est close, ou y a une valeur saisie ou
   importée, un N/A, un commentaire ou une preuve ; sinon demandé avec confirmation (cases vides d'une campagne en
   cours). Avancer (vers le passé) : l'écran annonce avant d'enregistrer les périodes touchées et le nombre de cases.
"""
import datetime

from django.core.exceptions import ValidationError
from django.db.models import Q

from parametres.libelles import libelle
from referentiel.models import ElementReferentiel, Frequence, KPIFormule

from .models import Campagne, Journal, Reponse
from espaces import contexte as ESP

CHAMP_JOURNAL = "Demandé depuis ({ref})"


class Confirmation(Exception):
    """Le changement retire le KPI de cases vides d'une campagne en cours : à confirmer (message à reposer)."""


# ---------------------------------------------------------------------------------------------------------- la règle
def filtre_demande(periode, prefixe=""):
    """Q des éléments de référentiel demandés dans la période (vide ou date de début de la période et avant). La seule
    écriture de la règle ; ``prefixe`` pour la lire au travers d'une relation (« elements__ »)."""
    if periode is None:
        return Q()
    return Q(**{f"{prefixe}demande_depuis__isnull": True}) | Q(**{f"{prefixe}demande_depuis__lte": periode.debut})


def graphe_formules():
    """{KPI calculé : {sources}}, toutes décalages confondus."""
    graphe = {}
    for c, src in KPIFormule.objects.values_list("kpi_calcule_id", "kpi_source_id"):
        graphe.setdefault(c, set()).add(src)
    return graphe


def avec_sources(codes, graphe=None):
    """Les KPI et toutes les sources de leurs formules, de proche en proche."""
    graphe = graphe_formules() if graphe is None else graphe
    utiles, pile = set(codes), list(codes)
    while pile:
        for src in graphe.get(pile.pop(), ()):
            if src not in utiles:
                utiles.add(src)
                pile.append(src)
    return utiles


def campagnes_et_contenues(periode):
    """Campagnes de la période et, pour une période plus longue qu'un mois, celles des périodes qu'elle contient."""
    qs = Campagne.objects.filter(periode=periode)
    if periode.type != Frequence.MOIS:
        qs = qs | Campagne.objects.filter(periode__debut__gte=periode.debut, periode__fin__lte=periode.fin)
    return qs.distinct()


def entrees_explicites(periode):
    """KPI (et sources de leurs formules) dont la date « demandé depuis », posée explicitement, couvre la période par un
    référentiel de ses campagnes (ou des périodes qu'elle contient) : ils entrent dans le périmètre noté d'une période
    rouverte (``calcul.perimetre_gele``) et dans celui de la clôture suivante (``calcul.geler_a_la_cloture``)."""
    paires = set(campagnes_et_contenues(periode).values_list("referentiel_id", "periode__debut"))
    dans = set()
    for ref, debut in paires:
        dans |= set(ElementReferentiel.objects.filter(referentiel_id=ref, demande_depuis__isnull=False,
                                                      demande_depuis__lte=debut).values_list("kpi_id", flat=True))
    return avec_sources(dans) if dans else set()


def depuis_par_defaut(referentiel_id):
    """« L'exercice en cours » d'un référentiel, le choix le plus prudent (aucun exercice passé ne change) : le début de
    la plus ancienne période de ses campagnes dont le périmètre n'est pas noté (jamais close : en préparation, ouverte,
    en revue) ; si toutes ses périodes sont closes ou rouvertes : le lendemain de la fin de la dernière (la période
    suivante) ; sans campagne : vide (rien à protéger)."""
    if referentiel_id is None:
        return None
    periodes = list(Campagne.objects.filter(referentiel_id=referentiel_id).values_list("periode__debut", "periode__fin",
                                                                                       "periode__perimetre_fige"))
    if not periodes:
        return None
    vivantes = [d for d, f, fige in periodes if fige is None]
    if vivantes:
        return min(vivantes)
    return max(f for d, f, fige in periodes) + datetime.timedelta(days=1)


# --------------------------------------------------------------------------------------------------- lecture, écran
def etat_campagne(c):
    """« clos », « rouvert » (périmètre noté, campagne non clôturée) ou « en_cours »."""
    if c.statut == Campagne.Statut.CLOTUREE:
        return "clos"
    return "rouvert" if c.periode.perimetre_fige is not None else "en_cours"


def libelle_depuis(referentiel, depuis, periodes=None):
    """Texte d'une date « demandé depuis » : le libellé de la période du référentiel qui commence ce jour-là
    (« 2025 », « mars 2026 »), sinon la date ; vide : « Depuis le début »."""
    if depuis is None:
        return libelle("referentiels.depuis.debut")
    if periodes is None:
        periodes = {c.periode.debut: c.periode for c in Campagne.objects.filter(referentiel=referentiel).select_related("periode")}
    p = periodes.get(depuis)
    if p is not None:
        return str(p)
    from . import periodes as P

    return P.libelle(referentiel.frequence, depuis, referentiel.mois_debut, langue=_langue())


def phrase_depuis(referentiel, depuis, periodes=None):
    """Complément de phrase d'une date « demandé depuis » : « à partir de 2025 », « depuis le début » (le libellé seul,
    ``libelle_depuis``, sert aux listes et aux colonnes ; dans une phrase il ferait « à partir de Depuis le début »)."""
    if depuis is None:
        return libelle("referentiels.depuis.phrase.debut")
    return libelle("referentiels.depuis.phrase.a_partir", depuis=libelle_depuis(referentiel, depuis, periodes))


def _langue():
    from parametres import langues as L

    return L.courante()


def choix(referentiel, tous=False):
    """Choix offerts à l'écran : [(valeur, libellé)], « Période en cours » d'abord (valeur vide, le défaut), puis les
    périodes des campagnes du référentiel plus anciennes qu'elle (``tous`` : aussi les suivantes, pour la gestion des
    KPI), de la plus récente à la plus ancienne, avec leur état."""
    defaut = depuis_par_defaut(referentiel.pk)
    campagnes = sorted(Campagne.objects.filter(referentiel=referentiel).select_related("periode"),
                       key=lambda c: c.periode.debut, reverse=True)
    sortie = [("", libelle("referentiels.depuis.en_cours_choix", periode=libelle_depuis(referentiel, defaut))
               if defaut else libelle("referentiels.depuis.en_cours_seul"))]
    for c in campagnes:
        if defaut is not None and c.periode.debut >= defaut and not (tous and c.periode.debut != defaut):
            continue
        sortie.append((c.periode.debut.isoformat(), libelle(f"referentiels.depuis.etat.{etat_campagne(c)}", periode=str(c.periode))))
    return sortie


def choix_refuses(referentiel, elements):
    """{code : [valeurs de ``choix(tous=True)`` que l'enregistrement refuserait pour ce KPI]} : le choix ferait sortir le
    KPI d'une période close, ou ayant une valeur saisie ou importée, un N/A, un commentaire ou une preuve (règle 5 du
    haut du module, celle de ``Prevision`` ; le serveur la relit toujours à l'enregistrement : cette liste n'est qu'une
    aide pour griser les choix impossibles). Valeur vide : l'exercice en cours."""
    campagnes = list(Campagne.objects.filter(referentiel=referentiel).select_related("periode"))
    defaut = depuis_par_defaut(referentiel.pk)
    options = {"": defaut}
    options.update({c.periode.debut.isoformat(): c.periode.debut for c in campagnes})
    codes = [e.kpi_id for e in elements]
    periodes = {c.periode_id for c in campagnes}
    avec = set()
    if codes and periodes:
        qs = Reponse.objects.filter(kpi_id__in=codes, periode_id__in=periodes)
        avec = set(qs.filter(origine__in=[Reponse.Origine.SAISIE, Reponse.Origine.IMPORT]).filter(
            Q(valeur__isnull=False) | ~Q(texte="") | Q(non_applicable=True)).values_list("kpi_id", "periode_id"))
        avec |= set(qs.filter(Q(non_applicable=True) | ~Q(commentaire="") | Q(preuves__isnull=False)).values_list("kpi_id", "periode_id"))
    sortie = {}
    for e in elements:
        refuses = []
        for valeur, nouveau in options.items():
            if nouveau is None:
                continue
            for c in campagnes:  # les périodes que ce choix ferait perdre au KPI
                if (e.demande_depuis is None or c.periode.debut >= e.demande_depuis) and c.periode.debut < nouveau:
                    if etat_campagne(c) == "clos" or (e.kpi_id, c.periode_id) in avec:
                        refuses.append(valeur)
                        break
        sortie[e.kpi_id] = refuses
    return sortie


def lire_choix(referentiel, valeur):
    """Date d'un choix envoyé par l'écran (vide : l'exercice en cours) ; ValidationError si ce n'est pas une période du
    référentiel."""
    valeur = (valeur or "").strip()
    if not valeur:
        return depuis_par_defaut(referentiel.pk)
    try:
        d = datetime.date.fromisoformat(valeur)
    except ValueError:
        raise ValidationError(libelle("referentiels.depuis.choix_inconnu"))
    if not Campagne.objects.filter(referentiel=referentiel, periode__debut=d).exists() and d != depuis_par_defaut(referentiel.pk):
        raise ValidationError(libelle("referentiels.depuis.choix_inconnu"))
    return d


# ------------------------------------------------------------------------------------------------------- prévision
class _Simulation(Exception):
    pass


def _presences(referentiel, campagnes, dates=None):
    """{campagne : codes offerts (``saisie.codes_campagne``, KPI et sources ; None : tout le catalogue)} ; avec ``dates``
    ({code : date}), celles-ci posées le temps de la lecture puis annulées : la prévision lit la même fonction que la
    saisie et le calcul, sans en écrire une seconde."""
    from .saisie import codes_campagne

    def lire():
        sortie = {}
        for c in campagnes:
            codes = codes_campagne(c)
            sortie[c.pk] = None if codes is None else codes[1]
        return sortie

    if dates is None:
        return lire()
    resultat = {}
    try:
        with ESP.atomic():
            for code, d in dates.items():
                ElementReferentiel.objects.filter(referentiel=referentiel, kpi_id=code).update(demande_depuis=d)
            resultat = lire()
            raise _Simulation
    except _Simulation:
        pass
    return resultat


def _avec_valeur(code, periode):
    """Vrai si le KPI a dans la période une valeur saisie ou importée, un N/A, un commentaire ou une preuve."""
    qs = Reponse.objects.filter(kpi_id=code, periode=periode)
    return (qs.filter(origine__in=[Reponse.Origine.SAISIE, Reponse.Origine.IMPORT]).filter(
        Q(valeur__isnull=False) | ~Q(texte="") | Q(non_applicable=True)).exists()
        or qs.filter(Q(non_applicable=True) | ~Q(commentaire="") | Q(preuves__isnull=False)).exists())


def _nb_cases(kpi, periode):
    """Cases à saisir que le KPI crée dans la période : organisations actives de son niveau ouvertes pendant la période
    (arbre de la période) ; 0 pour un KPI calculé."""
    if kpi.est_calcule:
        return 0
    from .calcul import ouverte
    from .saisie import arbre_organisations

    toutes = arbre_organisations(periode)
    return sum(1 for o in toutes.values() if o.actif and o.niveau_id == kpi.granularite_id and ouverte(o, periode, toutes))


class Prevision:
    """Effet d'un changement de « demandé depuis » sur des KPI d'un référentiel, avant d'enregistrer.

    ``lignes`` : [(campagne, état, effet, [codes], cases)], effet parmi « entre » (cases à saisir maintenant),
    « reouverture » (exercice clos : entrera à sa réouverture), « sort » (cases vides retirées, à confirmer) ;
    ``refus`` : [textes] (le changement est refusé) ; ``avertissements`` : [textes] (sources des formules)."""

    def __init__(self, referentiel, codes, nouveau):
        self.referentiel, self.nouveau = referentiel, nouveau
        self.elements = list(ElementReferentiel.objects.filter(referentiel=referentiel, kpi_id__in=codes).select_related("kpi"))
        self.codes = [e.kpi_id for e in self.elements]
        self.changes = [e for e in self.elements if e.demande_depuis != nouveau]
        campagnes = list(Campagne.objects.filter(referentiel=referentiel).select_related("periode").order_by("periode__debut"))
        avant = _presences(referentiel, campagnes)
        apres = _presences(referentiel, campagnes, {e.kpi_id: nouveau for e in self.changes})
        self.lignes, self.refus, self.a_confirmer = [], [], False
        for c in campagnes:
            etat = etat_campagne(c)
            av, ap = avant[c.pk], apres[c.pk]
            entrent, sortent, plus_tard = [], [], []
            for e in self.changes:
                dedans_av = av is None or e.kpi_id in av
                dedans_ap = ap is None or e.kpi_id in ap
                if dedans_ap and not dedans_av:
                    entrent.append(e)
                elif dedans_av and not dedans_ap:
                    sortent.append(e)
                elif (etat == "clos" and not dedans_av and nouveau is not None and c.periode.debut >= nouveau
                      and (e.demande_depuis is None or c.periode.debut < e.demande_depuis)):
                    plus_tard.append(e)  # pas encore couverte par l'ancienne date : entrera à la réouverture
            if entrent:
                self.lignes.append((c, etat, "entre", [e.kpi_id for e in entrent], sum(_nb_cases(e.kpi, c.periode) for e in entrent)))
            if plus_tard:
                self.lignes.append((c, etat, "reouverture", [e.kpi_id for e in plus_tard],
                                    sum(_nb_cases(e.kpi, c.periode) for e in plus_tard)))
            if sortent:
                self.lignes.append((c, etat, "sort", [e.kpi_id for e in sortent], 0))
                for e in sortent:
                    if etat == "clos":
                        self.refus.append(libelle("referentiels.depuis.refus_clos", code=e.kpi_id, periode=str(c.periode)))
                    elif _avec_valeur(e.kpi_id, c.periode):
                        self.refus.append(libelle("referentiels.depuis.refus_valeurs", code=e.kpi_id, periode=str(c.periode)))
                    else:
                        self.a_confirmer = True
        self.avertissements = self._sources()

    def _sources(self):
        """Un KPI calculé demandé plus tôt qu'une de ses sources du même référentiel : la source a des cases dès la date
        du KPI calculé (elle le sert). Lu dans les deux sens : KPI calculés changés, et sources changées."""
        if self.nouveau is None and not self.changes:
            return []
        graphe = graphe_formules()
        dates = dict(ElementReferentiel.objects.filter(referentiel=self.referentiel).values_list("kpi_id", "demande_depuis"))
        for e in self.changes:
            dates[e.kpi_id] = self.nouveau
        textes = set()

        def plus_tot(a, b):  # a demandé strictement avant b
            return b is not None and (a is None or a < b)

        changes = {e.kpi_id for e in self.changes}
        for calc, sources in graphe.items():
            if calc not in dates:
                continue
            for src in avec_sources(sources, graphe):
                if src in dates and (calc in changes or src in changes) and plus_tot(dates[calc], dates[src]):
                    textes.add(libelle("referentiels.depuis.avertissement_source", calcule=calc, source=src,
                                       depuis_calcule=phrase_depuis(self.referentiel, dates[calc]),
                                       depuis_source=phrase_depuis(self.referentiel, dates[src])))
        return sorted(textes)

    def resume(self):
        """Phrase de l'aperçu : périodes touchées et nombre de cases."""
        if not self.lignes:
            return libelle("referentiels.depuis.aucun_effet")
        morceaux = []
        for c, etat, effet, codes, cases in self.lignes:
            morceaux.append(libelle(f"referentiels.depuis.effet.{effet}", periode=str(c.periode), n=len(codes), cases=cases))
        return " ".join(morceaux)


def changer(utilisateur, referentiel, codes, nouveau, confirmer=False, prevision=None):
    """Pose « demandé depuis » sur des KPI d'un référentiel. Relit tout sous verrou (l'aperçu peut dater) : refus
    (ValidationError), cases vides retirées sans ``confirmer`` (``Confirmation``). Une ligne d'historique par KPI ; les
    campagnes non clôturées touchées sont recalculées (une période rouverte en gardant les chiffres de l'époque ne
    recalcule que les saisies, ``calcul.recalculer``) ; un KPI qui entre dans une période rouverte y a aussi une ligne
    « a ajouté un KPI au périmètre d'une période rouverte ». Renvoie la prévision appliquée."""
    from .calcul import recalculer

    with ESP.atomic():
        list(ElementReferentiel.objects.select_for_update().filter(referentiel=referentiel, kpi_id__in=codes))
        p = Prevision(referentiel, codes, nouveau)
        if not p.elements:
            raise ValidationError(libelle("referentiels.vues.cocher_un"))
        if p.refus:
            raise ValidationError(" ".join(p.refus[:5]) + (" …" if len(p.refus) > 5 else ""))
        if p.a_confirmer and not confirmer:
            raise Confirmation(libelle("referentiels.depuis.confirmer", effet=p.resume()))
        periodes = {}
        bornes = {nouveau} | {e.demande_depuis for e in p.changes}  # dates d'avant et d'après (None : depuis le début)
        for e in p.changes:
            avant = libelle_depuis(referentiel, e.demande_depuis, periodes)
            e.demande_depuis = nouveau
            e.save(update_fields=["demande_depuis"])
            Journal.ecrire(utilisateur, "reglage_kpi", e.kpi, CHAMP_JOURNAL.format(ref=referentiel.code), avant,
                           libelle_depuis(referentiel, nouveau, periodes))
        a_refaire = {}
        for c, etat, effet, codes_, cases in p.lignes:
            if effet in ("entre", "sort") and etat != "clos":
                a_refaire[c.pk] = c
                if etat == "rouvert" and effet == "entre":
                    for code in codes_:
                        Journal.ecrire(utilisateur, "perimetre_periode", c, "kpi_perimetre", "", code)
        for c in a_refaire.values():
            recalculer(c)
        if p.changes:
            _recalculer_cumuls(referentiel, bornes)
    return p


def _recalculer_cumuls(referentiel, bornes):
    """Référentiel de toute fréquence (un annuel décide aussi des mois de son exercice) : le cumul d'une période plus longue (l'année depuis les mois) ne porte
    que sur les mois où le KPI est demandé (``calcul.Calculateur.demande_courte``) ; les périodes
    plus longues non figées qui chevauchent les mois dont la demande change sont recalculées, même sans campagne de ce
    référentiel touchée (un mois sans campagne encore). Une période figée (close, ou rouverte en gardant les chiffres de
    l'époque) ne change pas."""
    from referentiel.models import MOIS_PAR_FREQUENCE

    from .calcul import figee, recalculer
    from .models import Periode

    # un référentiel moins fréquent (l'annuel) décide aussi des mois ou trimestres demandés dans sa période
    # (``demande_courte``) : les périodes plus longues que la plus fine des fréquences actives sont à refaire (troisième
    # passe du calcul : avancer la date de l'annuel laissait le semestre cumulé des trimestres à l'ancien total)
    from referentiel.models import Referentiel

    frequences = set(Referentiel.objects.filter(actif=True).values_list("frequence", flat=True)) | {referentiel.frequence}
    plus_fine = min(MOIS_PAR_FREQUENCE[f] for f in frequences)
    if plus_fine >= MOIS_PAR_FREQUENCE[Frequence.ANNEE]:
        return
    debut = min((d for d in bornes if d is not None), default=None) if None not in bornes else datetime.date.min
    fin = max((d for d in bornes if d is not None), default=None)
    if debut is None or fin is None:
        return
    plus_longues = [t for t, n in MOIS_PAR_FREQUENCE.items() if n > plus_fine]
    for q in Periode.objects.filter(type__in=plus_longues, fin__gte=debut, debut__lt=fin).order_by("debut"):
        if campagnes_et_contenues(q).exists() and not figee(q):
            recalculer(q)


def poser_a_la_creation(utilisateur, element, valeur):
    """Choix fait à la création d'un KPI (fiche, page du référentiel, choisir les KPI, aperçu d'un import) : vide = l'exercice
    en cours, déjà posé par la création ; sinon la période choisie, avec l'aperçu et l'historique de ``changer`` (une
    avance vers le passé ne demande jamais de confirmation)."""
    d = lire_choix(element.referentiel, valeur)
    if d == element.demande_depuis:
        return None
    return changer(utilisateur, element.referentiel, [element.kpi_id], d)
