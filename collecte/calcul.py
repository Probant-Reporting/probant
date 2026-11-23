"""Moteur de calcul : KPI calculés, agrégation par granularité et dans le temps (cahier des charges, sections 5.2 et 5.3).

Règles :
- Une valeur se rattache à une période (année, semestre, trimestre, mois : ``collecte.periodes``).
- Saisi / facteur d'émission : valeur saisie au niveau de sa granularité.
- Au-dessus de la granularité, selon la méthode d'agrégation du KPI :
    Somme    -> somme des organisations enfants directes actives (celles qui ne sont pas sous la granularité) ;
                N/A exclus ; tous N/A -> N/A ; un enfant sans valeur -> résultat incomplet.
    Formule  -> la formule est recalculée au niveau supérieur, sur les sources déjà agrégées.
    Décompte -> réponses oui / non ou liste : nombre de réponses de chaque valeur parmi les organisations
                rattachées (mêmes règles que la somme pour N/A et réponses manquantes).
    Aucune   -> pas de valeur.
- Dans le temps : un KPI collecté plus souvent dans un autre référentiel actif (ex. tous les mois) donne la valeur des
  périodes plus longues (le trimestre, l'année) selon son agrégation dans le temps : somme, moyenne ou dernière valeur
  des périodes qui la composent ; une période manquante rend le résultat incomplet. « Aucune » : la valeur se saisit à
  chaque fréquence. Une valeur saisie ou importée directement sur la période longue reste prioritaire (historique).
  Un KPI calculé refait sa formule sur chaque période, à partir des sources de cette période.
- Saisie aux niveaux supérieurs (option du KPI) : une valeur saisie ou importée directement au-dessus de la granularité
  remplace le total calculé et remonte telle quelle ; sans elle, le total est calculé comme d'habitude.
- En dessous de sa granularité, un paramètre hérité (facteur d'émission) est repris de l'organisation ancêtre de ce niveau ;
  sans ancêtre de ce niveau (rattachement souple : un site rattaché directement à un pays), l'organisation la plus haute
  de la lignée sous ce niveau porte sa propre valeur, saisie dans sa propre case (CALC-09).
- Formules : [ID] même période, [ID@P-1] période précédente, [ID@N-1] même période l'an dernier, [ID@2021] même
  période de l'exercice qui commence en 2021 (même rang dans l'exercice ; exercice décalé). Une période qui n'existe pas (aucune campagne) n'a pas de valeur.
- Le comportement vient du type de saisie (saisie, calcul, paramètre hérité), réglable dans Référentiels › Unités et formats ;
  une réponse oui / non ou liste n'entre jamais dans une formule.
- Les niveaux sont réglables (rang 1 = sommet) ; une organisation se rattache à n'importe quel niveau supérieur.
- Une source N/A rend le résultat N/A, sauf si la fiche du KPI coche « Une source N/A compte comme 0 » (cochée pour les
  formules qui ne sont qu'une somme) : elle compte alors comme 0, le détail du calcul le dit (« FUG : N/A, compté
  comme 0 »), et le résultat n'est N/A que si toutes les sources le sont. Une source manquante rend le résultat
  incomplet ; une division par zéro donne une erreur de calcul ; une réponse oui / non ou liste dans une formule aussi.
- Pour un exercice passé dont les valeurs calculées ont été importées (historique importé),
  la valeur importée est utilisée quand le calcul n'est pas possible.
- Arbre de l'époque : une période close, ou rouverte en gardant les chiffres de l'époque, se
  calcule avec l'arbre des organisations noté à sa clôture (parents, niveaux, organisations, états) ; toute autre période
  avec l'arbre d'aujourd'hui ; chaque période lue par un calcul suit le sien. Règle détaillée : section « arbre des
  organisations de l'époque » plus bas (``arbre_periode``, ``Calculateur.orgs_de``, ``lignes_arbre``).
"""
import datetime
import threading
from collections import Counter, defaultdict
from contextlib import contextmanager
from decimal import Decimal

from django.db.models import Count, Max, Q
from django.db.models.base import ModelState

from parametres import langues as L
from parametres import niveaux as N
from parametres.libelles import libelle
from referentiel import formule as F
from referentiel.models import (MOIS_PAR_FREQUENCE, KPI, ElementReferentiel, Frequence, KPIFormule, Organisation, Referentiel,
                                porteur_herite, porteurs_orphelins)

from . import periodes as P
from .lots import par_lots, supprimer_par_pk
from .models import VALEUR_MAX, Campagne, Reponse, valeur_enregistree
from espaces import contexte as ESP

NA = F.NA
_lus = threading.local()


def _jeton_kpis():
    """Repère de l'état du catalogue : nombre de KPI et dernière modification d'une fiche."""
    return tuple(KPI.objects.order_by().aggregate(n=Count("code"), d=Max("date_maj")).values())


@contextmanager
def kpis_lus_avant():
    """Lit le catalogue des KPI avant une transaction d'écriture et le prête aux calculs qu'elle déclenche. SQLite prend
    le verrou d'écriture dès le début de la transaction (une écriture à la fois) : relire les 800 fiches en le tenant,
    à chaque enregistrement, faisait attendre tous les autres (essai de charge). Si une
    fiche change entre-temps (repère différent une fois le verrou pris), le calcul relit le catalogue."""
    precedent = getattr(_lus, "kpis", None)
    _lus.kpis = (ESP.alias_courant(), _jeton_kpis(), {k.code: k for k in KPI.objects.all()})
    try:
        yield
    finally:
        _lus.kpis = precedent


def catalogue_kpis():
    """{code : KPI} : celui lu par ``kpis_lus_avant`` s'il est encore à jour, sinon relu."""
    lus = getattr(_lus, "kpis", None)
    if lus is not None and lus[0] == ESP.alias_courant() and lus[1] == _jeton_kpis():
        return dict(lus[2])
    return {k.code: k for k in KPI.objects.all()}


class _Message:
    """Message de calcul écrit seulement quand on le lit (``Calculateur.message``) : un recalcul évalue des dizaines de
    milliers de cases intermédiaires (tout l'arbre sous le groupe) dont le message n'est jamais lu ; les écrire tous
    prenait un cinquième du temps d'une saisie à gros volume."""
    __slots__ = ("cle", "valeurs")

    def __init__(self, cle, **valeurs):
        self.cle, self.valeurs = cle, valeurs

    def texte(self):
        return libelle(self.cle, **self.valeurs)


class Decompte(Counter):
    """Nombre de réponses de chaque valeur (oui / non, liste) parmi les organisations rattachées."""

    def texte(self, ordre=()):
        valeurs = [v for v in ordre if self[v]] + sorted(v for v in self if v not in ordre and self[v])
        return " · ".join(f"{v} : {self[v]}" for v in valeurs)

    @classmethod
    def lire(cls, texte):
        """Décompte enregistré en texte (« Oui : 3 · Non : 2 ») ; une réponse seule compte pour une."""
        total = cls()
        for morceau in (texte or "").split(" · "):
            nom, _, n = morceau.rpartition(" : ")
            if nom and n.isdecimal():
                total[nom] += int(n)
            elif morceau:
                total[morceau] += 1
        return total


def nom_ref(ref):
    """« FUG », ou « FUG@N-1 » pour une autre période."""
    return ref.kpi if ref.decalage == "N" else f"{ref.kpi}@{ref.decalage}"


def message_na_zero(codes):
    """« FUG : N/A, compté comme 0 » : sources N/A comptées comme 0 dans une formule (case de la fiche KPI)."""
    return libelle("messages.calcul.na_zero", n=len(codes), codes=", ".join(codes))


def frequences_de_saisie():
    """{code du KPI: fréquence la plus fine des référentiels actifs qui le contiennent}."""
    d = {}
    for kid, f in ElementReferentiel.objects.filter(referentiel__actif=True).values_list("kpi_id", "referentiel__frequence"):
        if kid not in d or P.plus_fine(f, d[kid]):
            d[kid] = f
    return d


def periode_de(cible):
    """Période d'une campagne (ou la période elle-même)."""
    return cible.periode if isinstance(cible, Campagne) else cible


def figee(periode):
    """Vrai si toutes les campagnes de la période sont clôturées, ou si l'une d'elles est rouverte en gardant les chiffres
    de l'époque (``Campagne.chiffres_gardes`` ; le mode vaut pour la période, même avec une
    autre campagne créée ensuite, ``chiffres_gardes``) : aucun recalcul automatique ; une correction n'y refait
    que l'organisation corrigée et ses totaux au-dessus, les autres cases sont lues telles qu'enregistrées."""
    statuts = list(Campagne.objects.filter(periode=periode).values_list("statut", "chiffres_gardes"))
    return bool(statuts) and (all(st == Campagne.Statut.CLOTUREE for st, _ in statuts)
                              or any(st != Campagne.Statut.CLOTUREE and g for st, g in statuts))


def chiffres_gardes(periode):
    """Vrai si une campagne de la période est rouverte en gardant les chiffres de l'époque et pas encore
    reclôturée : le mode vaut pour toute la période, quelles que soient ses autres campagnes
    (une campagne créée ensuite sur la même période, en préparation ou ouverte, ne fait pas recalculer les totaux
    publiés) ; seul un recalcul ciblé (une correction) y écrit. Le mode cesse à la reclôture de cette campagne, ou à
    une réouverture « recalculer » d'une campagne de la période (``administration.changer_statut``, écrite au journal)."""
    return Campagne.objects.filter(periode=periode, chiffres_gardes=True).exclude(statut=Campagne.Statut.CLOTUREE).exists()


def perimetre_calcul(periode):
    """KPI dont la période écrit les cases calculées, agrégées ou cumulées ; None : tous. Règle exacte (pour les mois, étendue aux années, semestres et trimestres) :

    1. Référentiels de la période : ceux de ses propres campagnes ; pour une période plus longue qu'un mois, aussi ceux
       des campagnes des périodes plus courtes qu'elle contient (les mois et trimestres de l'année) : l'année reçoit ainsi
       les cumuls des KPI collectés chaque mois, et les formules du référentiel mensuel refaites sur l'année.
    2. Périmètre = KPI de ces référentiels et toutes les sources de leurs formules, de proche en proche
       (``saisie.codes_perimetre`` : [X], [X@N-1], [X@P-1] et [X@AAAA] y comptent comme sources) ; pour une période plus
       longue qu'un mois, aussi les KPI du catalogue qui ne sont dans aucun référentiel (et leurs sources) : personne ne
       les collecte, mais un KPI calculé hors de tout référentiel (ratio d'un tableau de bord) était calculé sur l'année
       avant et peut être lu par la Visualisation ; un KPI d'un autre référentiel, lui, n'y entre que par une campagne.
    3. Mois sans campagne : rien (inchangée). Période plus longue sans aucune campagne, ni en elle ni dans les
       périodes qu'elle contient : None, tous les KPI (comme avant : rien ne la demande, rien n'y change).
       Aucun référentiel ne contient de KPI (installation neuve) : None.
    4. Période close ou rouverte (``perimetre_gele``, la même fonction que pour les cases offertes à la saisie) : le
       périmètre est en plus limité aux KPI qui y avaient une case à la clôture ou à la réouverture, plus, une fois
       la période rouverte, ceux dont la date « demandé depuis » a été avancée explicitement jusqu'à elle (``demande_depuis.entrees_explicites``) ; un KPI ajouté sans ce choix, pendant la clôture ou la
       réouverture, ou un modèle installé ensuite n'y crée pas de case, ni à saisir, ni calculée. Cas voisin : un
       KPI facultatif sans aucune case à la clôture n'est pas offert après la réouverture (règle à confirmer).
    Chaque référentiel n'y compte que les KPI qu'il demande dans la période de sa campagne (« demandé depuis »,
    ``saisie.codes_perimetre``).

    Les autres KPI n'y ont rien à saisir ni à montrer ; leurs cases « incomplet » faisaient baisser le taux de
    remplissage d'un exercice rouvert et l'essentiel de la table (2,3 millions de lignes sur 3,07 au premier audit de
    volume, pour les mois). Rien ne les lit : une formule cite une source, donc un KPI du périmètre ; une case qui manque
    dans une autre période se recalcule à la lecture (``Calculateur.valeur``) ; les exports, la Saisie et les contrôles de
    cohérence s'en tiennent déjà au périmètre des campagnes. Seule la lecture compte ici : ce périmètre ne décide que des
    cases écrites."""
    if periode is None:
        return None
    from .saisie import codes_perimetre

    campagnes = Campagne.objects.filter(periode=periode)
    if periode.type != Frequence.MOIS:
        contenues = (Campagne.objects.filter(periode__debut__gte=periode.debut, periode__fin__lte=periode.fin)
                     .exclude(periode=periode))
        if not campagnes.exists() and not contenues.exists():
            return None  # aucune campagne, ni en elle ni dedans : tous les KPI (comme avant)
        campagnes = campagnes | contenues
    utiles = set()
    refs = Referentiel.objects.in_bulk(list(campagnes.values_list("referentiel_id", flat=True).distinct()))
    dates = set(ElementReferentiel.objects.filter(referentiel_id__in=refs, demande_depuis__isnull=False)
                .values_list("referentiel_id", flat=True).distinct())
    paires = set()
    for c in campagnes.select_related("periode"):  # un référentiel sans date « demandé depuis » : une seule lecture
        paires.add((c.referentiel_id, c.periode if c.referentiel_id in dates else None))
    for ref_id, p in sorted(paires, key=lambda x: (x[0], x[1].debut if x[1] else datetime.date.min)):
        codes = codes_perimetre(refs[ref_id], p)  # ce que le référentiel demande dans cette période (« demandé depuis »)
        if codes is None:  # aucun référentiel ne contient de KPI (installation neuve) : tout le catalogue
            return None
        utiles |= codes[1]
    if periode.type != Frequence.MOIS:  # KPI hors de tout référentiel, et leurs sources (point 2)
        orphelins = set(KPI.objects.exclude(code__in=ElementReferentiel.objects.values("kpi_id")).values_list("code", flat=True))
        if orphelins:
            graphe = defaultdict(set)
            for c, src in KPIFormule.objects.values_list("kpi_calcule_id", "kpi_source_id"):
                graphe[c].add(src)
            pile = list(orphelins)
            while pile:
                for src in graphe.get(pile.pop(), ()):
                    if src not in orphelins:
                        orphelins.add(src)
                        pile.append(src)
            utiles |= orphelins
    fige = perimetre_gele(periode)
    if fige is not None:
        utiles &= fige
    return utiles


def perimetre_gele(periode):
    """KPI auxquels une période close ou rouverte est limitée (relecture et recette du même
    jour) ; None : aucune limite (période jamais close). Seule fonction de la règle, pour le calcul
    (``perimetre_calcul``) ET pour tout ce qui liste les cases d'une campagne (``saisie.codes_campagne`` : grille,
    case par l'adresse directe, taux de remplissage, tableau de bord, relances, fichier à remplir, exports, imports,
    contrôles de cohérence) : ce qui est offert à la saisie et ce qui est calculé coïncident.

    C'est ``Periode.perimetre_fige``, noté quand la période est close pour la première fois (``geler_a_la_cloture`` :
    les KPI qu'elle demandait et ceux qui y ont une case ; pour les exercices déjà clos d'une installation mise à jour,
    noté une fois par la mise à jour, sans rien changer à ce qu'ils demandaient), sinon à la première réouverture
    (``geler_perimetre``, période close avant cette version et jamais gelée). Il ne grandit que par un geste explicite,
    écrit au journal : une date « demandé depuis » avancée jusqu'à la période (``demande_depuis.entrees_explicites`` : comptée tant qu'une campagne de la période n'est pas clôturée, puis notée
    à la clôture suivante ; rien ne bouge tant que la période est close) ; une campagne créée sur la période
    (``etendre_pour_campagne``). Un KPI ajouté au référentiel sans ce choix (l'exercice en cours par défaut), par
    l'import du classeur de configuration ou par un modèle installé n'y entre pas. Relu en base à chaque appel (un
    objet période gardé d'avant la clôture ne l'a pas)."""
    if periode is None:
        return None
    fige = (type(periode).objects.filter(pk=periode.pk).values_list("perimetre_fige", flat=True).first() if periode.pk
            else getattr(periode, "perimetre_fige", None))
    if fige is None:
        return None
    if periode.pk and Campagne.objects.filter(periode_id=periode.pk).exclude(statut=Campagne.Statut.CLOTUREE).exists():
        from .demande_depuis import entrees_explicites

        return frozenset(fige) | frozenset(entrees_explicites(periode))
    return frozenset(fige)


def geler_a_la_cloture(periode):
    """Quand toutes les campagnes de la période sont clôturées et que son périmètre n'est pas encore noté : le note, avec
    les KPI que la période demandait (``perimetre_calcul`` ; tout le catalogue s'il n'est pas limité) et ceux qui y ont
    une case. Rien ne change pour la période (même périmètre qu'avant la clôture) ; un KPI ajouté ensuite n'y crée plus
    de case. Renvoie vrai si le périmètre a été noté.

    L'arbre des organisations est noté au même moment (``noter_arbre``), s'il ne l'est pas déjà : une deuxième clôture
    après une réouverture « garder » garde celui de la première ; après une réouverture « recalculer », il a été effacé
    et celui de ce jour est noté."""
    if not Campagne.objects.filter(periode=periode).exists() or \
            Campagne.objects.filter(periode=periode).exclude(statut=Campagne.Statut.CLOTUREE).exists():
        return False
    if arbre_fige(periode) is None:
        noter_arbre(periode)
    if periode.perimetre_fige is not None:
        # reclôture : les KPI entrés pendant la réouverture par leur date « demandé depuis » restent dans le périmètre
        # noté ; rien d'autre ne change
        from .demande_depuis import entrees_explicites

        fige = type(periode).objects.filter(pk=periode.pk).values_list("perimetre_fige", flat=True).first() or []
        plus = entrees_explicites(periode) - set(fige)
        if plus:
            periode.perimetre_fige = sorted(set(fige) | plus)
            type(periode).objects.filter(pk=periode.pk).update(perimetre_fige=periode.perimetre_fige)
        return False
    demandes = perimetre_calcul(periode)
    if demandes is None:
        demandes = set(KPI.objects.values_list("code", flat=True))
    cases = set(Reponse.objects.filter(periode=periode).order_by().values_list("kpi_id", flat=True).distinct())
    periode.perimetre_fige = sorted(set(demandes) | cases)
    periode.save(update_fields=["perimetre_fige"])
    return True


def geler_periodes_closes():
    """Mise à jour (travail après « migrate », ``collecte/0041``) : note le périmètre de chaque période déjà close et
    jamais gelée, tel qu'elle le demande aujourd'hui (aucun chiffre ne change). Renvoie le nombre de périodes notées."""
    from .models import Periode

    return sum(geler_a_la_cloture(p) for p in Periode.objects.filter(perimetre_fige__isnull=True,
                                                                    campagnes__isnull=False).distinct())


def etendre_pour_campagne(campagne, utilisateur=None):
    """Campagne créée sur une période dont le périmètre est noté (exercice clos ou rouvert) : geste explicite, les KPI
    de son référentiel (et les sources de leurs formules) entrent dans le périmètre de la période ; une ligne au journal
    (sinon une campagne d'un second référentiel créée pour un exercice passé, une reprise d'historique par exemple,
    n'aurait aucune case)."""
    from .models import Journal
    from .saisie import codes_perimetre

    p = type(campagne.periode).objects.get(pk=campagne.periode_id)
    if p.perimetre_fige is None:
        return
    codes = codes_perimetre(campagne.referentiel, p)  # ce que son référentiel demande dans la période (« demandé depuis »)
    demandes = set(KPI.objects.values_list("code", flat=True)) if codes is None else codes[1]
    nouveaux = sorted(demandes - set(p.perimetre_fige))
    if not nouveaux:
        return
    p.perimetre_fige = sorted(set(p.perimetre_fige) | set(nouveaux))
    p.save(update_fields=["perimetre_fige"])
    Journal.ecrire(utilisateur, "perimetre_periode", campagne, "kpi_perimetre", "", ", ".join(nouveaux))


def geler_perimetre(periode):
    """À la première réouverture d'une période close : note les KPI qui y ont une case
    (saisie, importée, calculée…) telle qu'elle a été publiée ; ``perimetre_calcul`` n'en sortira plus. Rien si déjà
    noté (une deuxième réouverture garde le périmètre de la première)."""
    if periode.perimetre_fige is not None:
        return
    periode.perimetre_fige = sorted(set(Reponse.objects.filter(periode=periode).values_list("kpi_id", flat=True)))
    periode.save(update_fields=["perimetre_fige"])


def cumule(kpi, periode, frequences):
    """Vrai si la valeur du KPI sur cette période s'obtient à partir de périodes plus courtes (ex. l'année à partir des mois)."""
    f = frequences.get(kpi.code)
    return (not kpi.est_calcule and not kpi.est_texte and kpi.agregation_temps != KPI.AgregationTemps.AUCUNE and f is not None
            and P.plus_fine(f, periode.type))


def ouverte(org, periode, orgs=None):
    """Vrai si l'organisation était ouverte pendant la période : (pas de date d'ouverture, ou date d'ouverture au plus
    tard le dernier jour de la période) et (active, ou désactivée après le début de la période). Un site fermé compte
    dans les totaux des années où il était ouvert ; un site ne compte qu'à partir de sa date
    d'ouverture (vide : ouverte depuis toujours). Sans date de désactivation connue, une
    organisation inactive ne compte pas. Seule fonction qui porte la règle : calculs, « incomplet », contrôles de
    cohérence, cases à saisir d'une campagne (``saisie.cellules``) et tout ce qui en découle (relances, taux de
    remplissage, fichier à remplir, exports, détail d'un total, serveur MCP).

    Une organisation n'est pas ouverte avant son parent : la date d'ouverture d'un ancêtre
    postérieure à la période la ferme aussi (sinon ses sites restaient à saisir sans compter dans aucun total). Seule la
    date d'ouverture se propage : sans aucune date d'ouverture, rien ne change (un parent désactivé garde ses règles
    d'avant). ``orgs`` : {identifiant: organisation} de l'arbre, pour remonter sans requête ; sans lui, les parents sont
    lus par la clé étrangère (une requête par organisation non encore chargée)."""
    debut = getattr(org, "date_ouverture", None)
    if debut is not None and periode is not None and debut > periode.fin:
        return False
    if not org.actif:
        d = getattr(org, "date_desactivation", None)
        if not (d and periode is not None and d >= periode.debut):
            return False
    if periode is None:
        return True
    x, vus = org, {org.id}
    while getattr(x, "parent_id", None) is not None:
        x = orgs.get(x.parent_id) if orgs is not None else x.parent
        if x is None or x.id in vus:  # garde-fou : parent absent de l'arbre donné, ou boucle
            return True
        vus.add(x.id)
        if getattr(x, "date_ouverture", None) is not None and x.date_ouverture > periode.fin:
            return False
    return True


def ouverture_effective(org, orgs=None):
    """(date, organisation qui la porte) : la plus tardive des dates d'ouverture de l'organisation et de ses ancêtres
    (celle qui compte, ``ouverte``) ; (None, None) sans aucune date."""
    date, porteuse, x, vus = None, None, org, set()
    while x is not None and x.id not in vus:
        vus.add(x.id)
        d = getattr(x, "date_ouverture", None)
        if d is not None and (date is None or d > date):
            date, porteuse = d, x
        pid = getattr(x, "parent_id", None)
        x = None if pid is None else (orgs.get(pid) if orgs is not None else x.parent)
    return date, porteuse


def arbre_ouverture(periode=None, code=None):
    """{identifiant: organisation} réduit à ce que lit ``ouverte`` (une requête), pour remonter les parents sans requête.
    Avec ``periode`` : l'arbre de cette période (``arbre_periode`` : celui de sa clôture si elle est close ou rouverte en
    gardant les chiffres de l'époque ; avec ``code``, celui du jour où ce KPI a été figé par une campagne clôturée)."""
    orgs = {o.id: o for o in Organisation.objects.only("id", "parent_id", "niveau_id", "actif", "date_desactivation",
                                                       "date_ouverture")}
    return orgs if periode is None else arbre_periode(periode, orgs, code)


# ---------------------------------------------------------------- arbre des organisations de l'époque
# Règle du projet : un exercice clos, puis rouvert en gardant les chiffres de l'époque, se calcule
# toujours avec l'arbre des organisations tel qu'il était à sa clôture. Règle exacte :
# - Ce qui est noté (``noter_arbre``, ``Periode.arbre_fige``) : quand toutes les campagnes de la période sont clôturées
#   (``geler_a_la_cloture``, comme le périmètre), pour chaque organisation existante, son parent, son niveau, son état
#   (active, date de désactivation, date d'ouverture) : tout ce que lisent ``ouverte``, ``enfants``, ``_avec_detail``,
#   ``porteur`` et ``orphelins``. Une deuxième clôture (après une réouverture « garder ») garde l'arbre de la première ;
#   une réouverture « recalculer avec l'organisation d'aujourd'hui » l'efface (``oublier_arbre``) et la clôture suivante
#   note l'arbre de ce jour. Exercices clos avant cette version : arbre du jour de la mise à jour (``noter_arbres_clos``).
# - Qui le suit (``arbre_periode``) : une période figée (``figee`` : close, ou rouverte en gardant les chiffres) dont
#   l'arbre est noté ; toute autre période suit l'arbre d'aujourd'hui. Chaque période lue par un calcul suit le sien
#   ([X@N-1], cumuls depuis les mois : ``Calculateur.orgs_de``).
# - Lecture : l'organisation d'aujourd'hui (nom, code, rang d'affichage) avec le parent, le niveau et l'état de l'époque.
#   Une organisation créée depuis la clôture n'y est pas (aucune case, ne compte pas, saisie refusée :
#   ``saisie.organisation_pas_ouverte``) ; une organisation supprimée depuis n'y est plus (ses valeurs sont parties
#   avec elle) et ses enfants de l'époque remontent au premier ancêtre de l'époque qui existe encore ; un niveau
#   supprimé depuis : celui d'aujourd'hui.
def arbre_du_jour():
    """L'arbre d'aujourd'hui, sous la forme notée (``Periode.arbre_fige``) ; une requête."""
    def jour(d):
        return d.isoformat() if d else None

    lignes = [[i, p, n, int(a), jour(d), jour(o)] for i, p, n, a, d, o in Organisation.objects.order_by("id").values_list(
        "id", "parent_id", "niveau_id", "actif", "date_desactivation", "date_ouverture")]
    return {"v": 1, "o": lignes}


def noter_arbre(periode):
    """Note l'arbre d'aujourd'hui sur la période (``Periode.arbre_fige``) ; une requête de lecture, une écriture."""
    periode.arbre_fige = arbre_du_jour()
    type(periode).objects.filter(pk=periode.pk).update(arbre_fige=periode.arbre_fige)


def oublier_arbre(periode):
    """Réouverture « recalculer avec l'organisation d'aujourd'hui » : l'arbre noté est effacé (la clôture suivante note
    celui de ce jour-là)."""
    periode.arbre_fige = None
    type(periode).objects.filter(pk=periode.pk).update(arbre_fige=None)


def arbre_fige(periode):
    """Arbre noté de la période (relu en base : un objet période gardé d'avant la clôture ne l'a pas), ou None."""
    if periode is None or not getattr(periode, "pk", None):
        return None
    return type(periode).objects.filter(pk=periode.pk).values_list("arbre_fige", flat=True).first()


def arbre_suivi(periode, code=None):
    """Arbre noté que la période suit (période figée dont l'arbre est noté), ou None : arbre d'aujourd'hui. Avec
    ``code`` : pour ce KPI ; un KPI figé par une campagne clôturée (``figes_partiels``) suit l'arbre du jour où il a été
    figé, que la période soit entièrement close ou non (règle « Figer ses chiffres »)."""
    if periode is None or not getattr(periode, "pk", None):
        return None
    if code is not None:
        d = figes_partiels(periode)
        if d and code in d["kpis"]:
            return d["arbres"][d["kpis"][code]]
    if not figee(periode):
        return None
    return arbre_fige(periode)


def appliquer_arbre(fige, orgs):
    """{identifiant: organisation} de l'époque : pour chaque organisation de l'arbre noté qui existe encore dans ``orgs``
    (organisations d'aujourd'hui), une copie avec le parent, le niveau et l'état de l'époque (les objets de ``orgs`` ne
    changent pas). Voir la règle en tête de cette section."""
    from parametres.models import NiveauHierarchique

    epoque = {e[0]: e for e in fige.get("o", ())}
    niveaux = {}
    for o in orgs.values():
        n = o._state.fields_cache.get("niveau")
        if n is not None:
            niveaux[o.niveau_id] = n
    manquants = {e[2] for e in epoque.values()} - set(niveaux)
    connus = set(niveaux)
    if manquants:
        for n in NiveauHierarchique.objects.filter(code__in=manquants):
            niveaux[n.code] = n
            connus.add(n.code)
    dates = {}

    def jour(t):
        if t is None:
            return None
        if t not in dates:
            dates[t] = datetime.date.fromisoformat(t)
        return dates[t]

    sortie = {}
    for oid, (_, pid, niv, actif, desac, ouv) in epoque.items():
        o = orgs.get(oid)
        if o is None:  # supprimée depuis la clôture
            continue
        vus = {oid}
        while pid is not None and pid not in orgs and pid in epoque and pid not in vus:  # parent supprimé depuis
            vus.add(pid)
            pid = epoque[pid][1]
        if pid is not None and pid not in orgs:
            pid = None
        if niv not in connus:  # niveau supprimé depuis : celui d'aujourd'hui
            niv = o.niveau_id
        # copie légère (pas de copy.copy : 700 organisations par période lue, à chaque page) : mêmes champs, état neuf
        etat = ModelState()
        etat.db, etat.adding = o._state.db, False
        etat.fields_cache = {"niveau": niveaux[niv]} if niv in niveaux else {}
        c = object.__new__(Organisation)
        c.__dict__ = {**o.__dict__, "_state": etat, "parent_id": pid, "niveau_id": niv, "actif": bool(actif),
                      "date_desactivation": jour(desac), "date_ouverture": jour(ouv)}
        sortie[oid] = c
    for c in sortie.values():  # parents déjà reliés dans l'arbre de l'époque (sans requête en remontant)
        c._state.fields_cache["parent"] = sortie.get(c.parent_id)
    return sortie


def arbre_periode(periode, orgs=None, code=None):
    """Arbre des organisations à utiliser pour la période : celui de sa clôture si elle est close ou rouverte en gardant
    les chiffres de l'époque (``arbre_suivi``), sinon ``orgs`` (par défaut toutes les organisations d'aujourd'hui, avec
    leur niveau). Seule fonction de la règle pour le calcul ET les pages (cases à saisir, détail d'un total,
    Consolidation, Visualisation, exports, fichier à remplir, contrôles de cohérence) : le total affiché est toujours
    la somme du détail affiché. ``code`` : l'arbre de ce KPI (un KPI figé par une campagne clôturée suit l'arbre du jour
    où il a été figé, ``figes_partiels``)."""
    if orgs is None:
        orgs = {o.id: o for o in Organisation.objects.select_related("niveau")}
    fige = arbre_suivi(periode, code)
    return orgs if fige is None else appliquer_arbre(fige, orgs)


def arbre_commun(periode, codes):
    """Code d'un KPI dont l'arbre vaut pour tous les KPI ``codes`` sur la période (même arbre noté, ou aucun), à passer
    à ``arbre_periode`` ; None si aucun n'est figé à part. Pour une page qui montre plusieurs KPI sur les mêmes lignes
    (Consolidation, format officiel) : quand leurs arbres diffèrent (un KPI figé par une campagne clôturée avant un
    changement de l'arbre, à côté d'un KPI de la campagne ouverte), les lignes suivent l'arbre de la période."""
    d = figes_partiels(periode)
    if not d:
        return None
    rangs = {d["kpis"].get(c) for c in codes}
    if len(rangs) != 1 or None in rangs:
        return None
    return next(c for c in codes if c in d["kpis"])


def noter_arbres_clos():
    """Mise à jour (travail après « migrate », ``collecte/0043``) : note l'arbre d'aujourd'hui sur chaque période figée
    (close, ou rouverte en gardant les chiffres) dont l'arbre n'est pas encore noté ; rien n'est recalculé. Renvoie le
    nombre de périodes notées."""
    from .models import Periode

    n = 0
    for p in Periode.objects.filter(arbre_fige__isnull=True, campagnes__isnull=False).distinct():
        if figee(p):
            noter_arbre(p)
            n += 1
    return n


# ---------------------------------------------------------------- KPI figés par une campagne clôturée
# Règle « Figer ses chiffres » (règle du projet) : deux campagnes sur une même période (deux
# référentiels), l'une clôturée, l'autre non. Les KPI que demande une campagne clôturée (``saisie.codes_campagne`` : ses
# KPI et les sources de leurs formules, ceux-là mêmes dont la règle du KPI commun bloque la saisie dans l'autre campagne,
# ``saisie.motif_cloturee_ailleurs``) gardent leurs chiffres : rien ne les réécrit tant que la période n'est pas
# entièrement close (changement de l'arbre, désactivation, recalcul à la mise à jour, « Recalculer », saisie ailleurs),
# comme dans une période figée ; ils se lisent tels qu'enregistrés et s'affichent avec l'arbre du jour où ils ont été
# figés. Seule exception, comme dans une campagne clôturée : une correction importée d'un KPI figé refait
# l'organisation corrigée et ses totaux au-dessus, dans cet arbre-là. Un KPI que seule la campagne ouverte demande suit
# l'arbre d'aujourd'hui et se recalcule comme avant. Ce qui est noté (``Periode.figes_partiels``) : chaque KPI figé et
# l'arbre du jour où il l'a été ; tenu à jour à chaque clôture ou réouverture d'une campagne de la période
# (``noter_figes_partiels``). Une période entièrement close garde ce qui est noté : ces KPI y suivent leur arbre, les
# autres celui de la clôture de la période (``arbre_fige``).
def figes_partiels(periode):
    """{"v", "arbres", "kpis"} noté sur la période (relu en base : un objet période gardé d'avant ne l'a pas), ou None."""
    if periode is None or not getattr(periode, "pk", None):
        return None
    return type(periode).objects.filter(pk=periode.pk).values_list("figes_partiels", flat=True).first()


def kpis_figes(periode):
    """Codes des KPI figés par une campagne clôturée de la période (``figes_partiels``) ; vide si aucun."""
    d = figes_partiels(periode)
    return frozenset(d["kpis"]) if d else frozenset()


def noter_figes_partiels(periode, arbre=None):
    """À la clôture ou à la réouverture d'une campagne : tient à jour les KPI figés de la période. Rien ne change si la
    période est figée (entièrement close, ou rouverte en gardant les chiffres) : ses KPI figés gardent leur arbre. Sinon,
    les KPI que demande une campagne clôturée de la période (``saisie.codes_campagne``) sont figés : ceux déjà notés
    gardent leur arbre, les nouveaux reçoivent ``arbre`` (par défaut celui d'aujourd'hui ; à une réouverture
    « recalculer » d'une période close, celui de sa clôture, qu'ils suivaient) ; un KPI qu'aucune campagne clôturée ne
    demande plus (campagne rouverte) n'est plus figé. Renvoie vrai si la note a changé."""
    from .saisie import codes_campagne

    if figee(periode):
        return False
    ancien = figes_partiels(periode)
    demandes = set()
    for c in Campagne.objects.filter(periode=periode, statut=Campagne.Statut.CLOTUREE).select_related("referentiel", "periode"):
        codes = codes_campagne(c)
        demandes |= set(KPI.objects.values_list("code", flat=True)) if codes is None else set(codes[1])
    arbres = list(ancien["arbres"]) if ancien else []
    kpis = {k: i for k, i in (ancien["kpis"].items() if ancien else ()) if k in demandes}
    nouveaux = sorted(demandes - set(kpis))
    if nouveaux:
        a = arbre if arbre is not None else arbre_du_jour()
        if a not in arbres:
            arbres.append(a)
        for k in nouveaux:
            kpis[k] = arbres.index(a)
    utiles = sorted(set(kpis.values()))  # arbres encore suivis par un KPI, dans l'ordre
    nouveau = None
    if kpis:
        nouveau = {"v": 1, "arbres": [arbres[i] for i in utiles], "kpis": {k: utiles.index(i) for k, i in sorted(kpis.items())}}
    if nouveau == ancien:
        return False
    periode.figes_partiels = nouveau
    type(periode).objects.filter(pk=periode.pk).update(figes_partiels=nouveau)
    return True


def importes_en_attente(periode):
    """{(KPI, organisation)} des chiffres importés tels quels sur des cases calculées de la période que le calcul ne lit
    pas encore comme chiffres officiels : la période n'est pas figée et le KPI n'est pas figé par une campagne clôturée
    (``Calculateur._valeur`` ne les utilise alors que si le calcul est impossible). Lu avant une clôture
    (``rendre_officiels``)."""
    if figee(periode):
        return set()
    figes = kpis_figes(periode)
    return {(k, o) for k, o in Reponse.objects.filter(periode=periode, origine=Reponse.Origine.IMPORT,
                                                      kpi__type_saisie__comportement="calcul")
            .values_list("kpi_id", "organisation_id") if k not in figes}


def rendre_officiels(periode, avant):
    """Après la clôture d'une campagne (« le calcul doit être à jour ») : les chiffres importés
    ``avant`` (``importes_en_attente`` lu avant la clôture) dont le KPI est désormais figé deviennent les chiffres
    officiels de la période ; les périodes non figées qui les lisent ([X@N-1], [X@P-1], [X@AAAA] ; une année rouverte
    « garder » pour ses seules cases touchées) sont recalculées aussitôt, pour ces KPI, ces organisations et ce qui en
    dépend. La période clôturée elle-même n'est jamais réécrite (un total au-dessus garde le chiffre calculé pendant
    qu'elle était ouverte). Avant, la période qui lisait le chiffre gardait l'ancien résultat jusqu'à son prochain
    recalcul, puis changeait sans qu'aucune donnée ait changé. Renvoie le nombre de cases écrites."""
    if not avant:
        return 0
    figes = None if figee(periode) else kpis_figes(periode)
    devenus = [(k, o) for k, o in avant if figes is None or k in figes]
    if not devenus:
        return 0
    kpis, orgs = sorted({k for k, _ in devenus}), {o for _, o in devenus}
    n = recalculer(periode, kpis, organisations=orgs, lecteurs_seulement=True)
    if figes is not None:
        # période encore ouverte (une autre campagne n'est pas clôturée) : ses KPI non figés qui citent ces chiffres
        # les lisent aussitôt aussi ; les KPI figés (chiffres gardés) ne sont jamais réécrits
        lecteurs = kpis_dependants(kpis, annee=P.Calendrier().exercice(periode)) - set(figes)
        if lecteurs:
            n += recalculer(periode, sorted(lecteurs), organisations=orgs)
    return n


def noter_figes_partiels_existants():
    """Mise à jour (travail après « migrate », ``collecte/0047``) : pour chaque période non figée dont une campagne est
    déjà clôturée à côté d'une campagne qui ne l'est pas, rien n'a été noté à l'époque : ses KPI figés sont notés avec
    l'arbre d'aujourd'hui (jusqu'ici ils étaient recalculés avec lui : leurs chiffres enregistrés en viennent). Rien
    n'est recalculé. Renvoie le nombre de périodes notées."""
    from .models import Periode

    n = 0
    for p in Periode.objects.filter(figes_partiels__isnull=True, campagnes__statut=Campagne.Statut.CLOTUREE).distinct():
        if Campagne.objects.filter(periode=p).exclude(statut=Campagne.Statut.CLOTUREE).exists() and noter_figes_partiels(p):
            n += 1
    return n


class _PeriodeCourte:
    """Période courte qui n'existe pas encore en base (mois sans campagne) : ses dates, pour ``ouverte``."""

    pk = None

    def __init__(self, debut, fin):
        self.debut, self.fin = debut, fin


class Calculateur:
    def __init__(self, cible, calendrier=None, frequences=None):
        self.periode = periode_de(cible)
        self.calendrier = calendrier or P.Calendrier()
        self.frequences = frequences if frequences is not None else frequences_de_saisie()
        self.kpis = catalogue_kpis()
        self.orgs = {o.id: o for o in Organisation.objects.select_related("niveau")}
        self.rangs = N.rangs()
        self._enfants = {}
        self._arbres = {}
        self._saisies = {}
        self._imports = {}
        self._forcees = {}
        self._valorisees = {}
        self._figees = {}
        self._enregistrees = {}
        self._cache = {}
        self._details = {}
        self._porteurs = {}
        self._orphelins = {}
        self._arbres_periode = {}
        self._partiels = {}  # {pk de la période: ``figes_partiels`` (KPI figés par une campagne clôturée) ou None}
        self._refs_courtes = None  # {fréquence: ([référentiels actifs], un élément daté)} (« demandé depuis »)
        self._demandes_courtes = {}
        self.messages = {}
        self.erreurs = set()  # (KPI, organisation, période) en erreur : formule illisible, division par zéro…
        # période figée recalculée pour une correction importée : (KPI, organisations) des seules cases
        # refaites ; toute autre case de la période est lue telle qu'enregistrée (``refaire_seulement``)
        self.refaites = None
        # période non figée dont une campagne est clôturée, corrigée par une correction importée d'un KPI figé :
        # {KPI figé: organisations refaites} ; tout autre KPI figé de la période est lu tel qu'enregistré
        self.refaites_gelees = {}

    # -- données saisies ----------------------------------------------------
    def saisies(self, periode):
        if periode.pk not in self._saisies:
            d = {}
            qs = self.reponses_saisies(periode)
            imports, forcees = set(), set()
            for kpi_id, org_id, val, texte, na, origine in qs.values_list("kpi_id", "organisation_id", "valeur", "texte",
                                                                          "non_applicable", "origine"):
                d[(kpi_id, org_id)] = NA if na else val if val is not None else (texte or None)  # texte : oui / non, liste
                if origine == Reponse.Origine.IMPORT:
                    imports.add((kpi_id, org_id))
                elif origine == Reponse.Origine.FORCEE:
                    forcees.add((kpi_id, org_id))
            self._saisies[periode.pk] = d
            self._imports[periode.pk] = imports
            self._forcees[periode.pk] = forcees
        return self._saisies[periode.pk]

    def _imports_de(self, periode):
        self.saisies(periode)
        return self._imports[periode.pk]

    def avec_valeurs(self, periode, code=None):
        """Organisations qui ont au moins une valeur saisie ou importée sur la période, et leurs ancêtres (dans l'arbre
        que suit le KPI ``code`` sur la période, ``orgs_de``)."""
        cle = ("v", self._cle(periode, code))
        if cle not in self._valorisees:
            tous = set()
            # une ancienne saisie d'un KPI devenu calculé, dans une période non figée (KPI non figé à part), n'est pas
            # une valeur : le recalcul la remplace (sinon le total changeait entre le premier et le second recalcul)
            valeurs, imports, forcees = self.presence(periode)
            obsoletes = set() if self.figee(periode) else {
                (k, o) for (k, o) in valeurs if k in self.kpis and self.kpis[k].est_calcule
                and (k, o) not in imports and (k, o) not in forcees and k not in self.gelees(periode)}
            orgs = self.orgs_de(periode, code)
            for (k, o), v in valeurs.items():
                x = orgs.get(o) if v is not None and (k, o) not in obsoletes else None
                while x is not None and x.id not in tous:
                    tous.add(x.id)
                    x = orgs.get(x.parent_id)
            self._valorisees[cle] = tous
        return self._valorisees[cle]

    def presence(self, periode):
        """({(KPI, organisation): valeur}, imports, forcées) des réponses saisies, importées ou forcées de la période, de
        TOUS les KPI : ce qui dit qu'une organisation fermée a des valeurs sur la période (``avec_valeurs``). Un
        calculateur limité à quelques KPI (``visualisation.CalculateurValide``) le relit sans cette limite."""
        self.saisies(periode)
        return self._saisies[periode.pk], self._imports[periode.pk], self._forcees[periode.pk]

    def avec_valeurs_courtes(self, periode, f, code=None):
        """``avec_valeurs`` des périodes de fréquence ``f`` (existantes) contenues dans la période : une organisation
        fermée pendant l'année qui a saisi dans ses mois y a des valeurs."""
        cle = ("c", periode.pk, f, code)
        if cle not in self._valorisees:
            tous = set()
            for debut in self.calendrier.contenues(periode, f):
                q = self.calendrier.trouver(f, debut)
                if q is not None:
                    tous |= self.avec_valeurs(q, code)
            self._valorisees[cle] = tous
        return self._valorisees[cle]

    def forcees(self, periode):
        """{(KPI, organisation)} des valeurs forcées de la période (KPI calculés, avec accord)."""
        self.saisies(periode)
        return self._forcees[periode.pk]

    def reponses_saisies(self, periode):
        """Réponses saisies, importées ou forcées de la période, d'où partent les calculs."""
        return Reponse.objects.filter(periode=periode, origine__in=[Reponse.Origine.SAISIE, Reponse.Origine.IMPORT,
                                                                    Reponse.Origine.FORCEE])

    def reponses_periode(self, periode):
        return Reponse.objects.filter(periode=periode)

    def figee(self, periode):
        if periode.pk not in self._figees:
            self._figees[periode.pk] = figee(periode)
        return self._figees[periode.pk]

    def _figes_partiels(self, periode):
        if periode is None or periode.pk is None:
            return None
        if periode.pk not in self._partiels:
            self._partiels[periode.pk] = figes_partiels(periode)
        return self._partiels[periode.pk]

    def gelees(self, periode):
        """{KPI figé par une campagne clôturée de la période: rang de son arbre} (``figes_partiels``) ; vide si aucun."""
        d = self._figes_partiels(periode)
        return d["kpis"] if d else {}

    def fige_pour(self, periode, code):
        """Vrai si le KPI garde ses chiffres sur la période : période figée, ou KPI figé par une campagne clôturée de la
        période (règle « Figer ses chiffres »)."""
        return self.figee(periode) or code in self.gelees(periode)

    def _cle(self, periode, code):
        """Clé de l'arbre que suit le KPI ``code`` sur la période (caches par arbre) : l'identifiant de la période, ou
        (identifiant, rang de l'arbre noté) pour un KPI figé par une campagne clôturée."""
        pk = periode.pk if periode is not None else None
        if code is not None and pk is not None:
            i = self.gelees(periode).get(code)
            if i is not None:
                return (pk, i)
        return pk

    def orgs_de(self, periode, code=None):
        """{identifiant: organisation} de l'arbre que suit la période : celui de sa clôture si elle est figée et que son
        arbre est noté (``arbre_periode``), sinon celui d'aujourd'hui (``self.orgs``). Lu une fois par période. Avec
        ``code`` : un KPI figé par une campagne clôturée suit l'arbre du jour où il a été figé (``figes_partiels``)."""
        if periode is None:
            return self.orgs
        cle = self._cle(periode, code)
        if cle != periode.pk:
            if cle not in self._arbres_periode:
                d = self._figes_partiels(periode)
                self._arbres_periode[cle] = appliquer_arbre(d["arbres"][cle[1]], self.orgs)
            return self._arbres_periode[cle]
        if periode.pk not in self._arbres_periode:
            fige = arbre_fige(periode) if self.figee(periode) else None
            self._arbres_periode[periode.pk] = self.orgs if fige is None else appliquer_arbre(fige, self.orgs)
        return self._arbres_periode[periode.pk]

    def enregistrees(self, periode):
        """{(KPI, organisation): (origine, valeur, texte, N/A)} des réponses de la période (période figée)."""
        if periode.pk not in self._enregistrees:
            self._enregistrees[periode.pk] = {
                (k, o): (origine, val, texte, na) for k, o, origine, val, texte, na in self.reponses_periode(periode)
                .values_list("kpi_id", "organisation_id", "origine", "valeur", "texte", "non_applicable")}
        return self._enregistrees[periode.pk]

    def _figee(self, kpi_id, org_id, p):
        """(trouvée, valeur) : dans une période figée, autre que celle du calcul, la valeur enregistrée fait foi (celle
        des exports), au lieu d'un recalcul avec les réglages d'aujourd'hui (organisations désactivées, formule changée,
        valeur calculée importée d'un fichier historique)."""
        r = self.enregistrees(p).get((kpi_id, org_id))
        if r is None:
            return False, None
        origine, val, texte, na = r
        if origine in (Reponse.Origine.SAISIE, Reponse.Origine.IMPORT, Reponse.Origine.FORCEE):
            v = self.saisies(p).get((kpi_id, org_id))  # mêmes règles que les saisies (visualisation : validées seulement)
            return v is not None, v
        if na:
            return True, NA
        if val is not None and not texte:
            return True, val
        if texte:
            kpi = self.kpis.get(kpi_id)
            return True, Decompte.lire(texte) if origine == Reponse.Origine.AGREGATION and kpi and not kpi.est_numerique else texte
        self._msg(kpi_id, org_id, p, _Message("messages.calcul.incomplete_cloturee"))
        return True, None

    def arbre(self, kpi):
        if kpi.code not in self._arbres:
            self._arbres[kpi.code] = F.analyser(kpi.formule)
        return self._arbres[kpi.code]

    def porteur(self, kpi, org, periode=None):
        """Organisation dont la valeur d'un paramètre hérité (facteur d'émission) vaut pour ``org``, sous sa granularité :
        son ancêtre de ce niveau ; sans ancêtre de ce niveau (rattachement souple, ex. un site rattaché directement à un
        pays), la plus haute organisation de sa lignée sous ce niveau, qui porte sa propre case (CALC-09,
        ``referentiel.models.porte_herite``). Dans l'arbre que suit la période (par défaut, celle du calculateur)."""
        orgs = self.orgs_de(periode or self.periode, kpi.code)
        cle = (kpi.granularite_id, org.id, id(orgs))
        if cle not in self._porteurs:
            self._porteurs[cle] = porteur_herite(orgs.get(org.id, org), kpi.granularite_id, self.rangs, orgs)
        return self._porteurs[cle]

    def orphelins(self, niveau, code=None):
        """Identifiants des organisations ouvertes pendant la période du calculateur qui portent elles-mêmes les paramètres
        hérités du niveau ``niveau`` (dans l'arbre que suit la période, ou le KPI ``code``)."""
        cle = (niveau, self._cle(self.periode, code))
        if cle not in self._orphelins:
            orgs = self.orgs_de(self.periode, code)
            actives = [o for o in orgs.values() if ouverte(o, self.periode, orgs)]
            self._orphelins[cle] = {o.id for o in porteurs_orphelins(niveau, actives, self.rangs, orgs)}
        return self._orphelins[cle]

    # -- calcul ----------------------------------------------------------------
    def valeur(self, kpi_id, org_id, periode=None):
        """Decimal, NA, ou None (pas de valeur) ; texte ou Decompte pour une réponse oui / non ou liste.
        Les causes sont dans self.messages, par (KPI, organisation, identifiant de la période)."""
        periode = periode or self.periode
        cle = (kpi_id, org_id, periode.pk)
        if cle not in self._cache:
            self._cache[cle] = None  # garde-fou contre une boucle
            if self.periode is not None and periode.pk == self.periode.pk:
                # période du calcul : recalculée, sauf, dans une période figée corrigée, hors des cases refaites ;
                # un KPI figé par une campagne clôturée s'y lit tel qu'enregistré, hors des cases qu'une correction de
                # ce KPI refait (règle « Figer ses chiffres »)
                if self.refaites is not None:
                    refaite = kpi_id in self.refaites[0] and org_id in self.refaites[1]
                    trouvee, v = (False, None) if refaite else self._figee(kpi_id, org_id, periode)
                elif kpi_id in self.gelees(periode) and not self.figee(periode) and \
                        org_id not in self.refaites_gelees.get(kpi_id, ()):
                    trouvee, v = self._figee(kpi_id, org_id, periode)
                else:
                    trouvee, v = False, None
            elif not self.lisible(kpi_id, org_id, periode):
                # autre période où l'organisation n'est pas ouverte : rien ne s'y lit (une valeur gardée d'avant la
                # date d'ouverture ne compte nulle part) ; source manquante, comme pour une organisation créée depuis
                trouvee, v = True, None
            else:
                trouvee, v = self._figee(kpi_id, org_id, periode) if self.fige_pour(periode, kpi_id) else (False, None)
            if not trouvee:
                v = self._valeur(kpi_id, org_id, periode)
                if isinstance(v, Decimal) and v.is_finite() and abs(v) >= VALEUR_MAX:
                    # hors de ce que la base garde : erreur nommée, dès le calcul (sinon les formules qui citent la case
                    # utiliseraient une valeur que la case elle-même ne montre pas)
                    self.messages[cle] = libelle("messages.calcul.trop_grand")
                    self.erreurs.add(cle)
                    v = None
            self._cache[cle] = v
        return self._cache[cle]

    def lisible(self, kpi_id, org_id, periode):
        """Vrai si la case se lit depuis une autre période (formule [X@N-1], [X@P-1], [X@AAAA]) : l'organisation est
        ouverte pendant cette période, dans l'arbre qu'elle suit (``ouverte``) ; ou c'est un paramètre hérité sous sa
        granularité, lu chez son porteur (qui doit l'être à son tour). Une valeur gardée
        d'avant la date d'ouverture entrait dans un chiffre publié par [X@N-1]."""
        arbre = self.orgs_de(periode, kpi_id)
        org, kpi = arbre.get(org_id), self.kpis.get(kpi_id)
        if org is None or kpi is None:
            return True  # inconnue, ou absente de l'arbre de l'époque : ``_valeur`` n'y trouve rien
        if ouverte(org, periode, arbre):
            return True
        if kpi.est_herite and self.rangs[org.niveau_id] > self.rangs[kpi.granularite_id]:
            return self.porteur(kpi, org, periode) is not org
        return False

    def message(self, kpi_id, org_id, periode=None):
        cle = (kpi_id, org_id, (periode or self.periode).pk)
        texte = self.messages.get(cle, "")
        if isinstance(texte, _Message):  # écrit seulement quand on le lit (voir _Message)
            texte = self.messages[cle] = texte.texte()
        return texte

    def _msg(self, kpi_id, org_id, periode, texte):
        self.messages.setdefault((kpi_id, org_id, periode.pk), texte)

    def cumule(self, kpi, periode):
        return cumule(kpi, periode, self.frequences)

    def _valeur(self, kpi_id, org_id, p):
        kpi, org = self.kpis.get(kpi_id), self.orgs_de(p, kpi_id).get(org_id)
        if kpi is None or org is None:  # organisation inconnue, ou absente de l'arbre de l'époque (créée depuis)
            return None
        if kpi.est_calcule and (kpi_id, org_id) in self.forcees(p):  # valeur forcée (accord) : elle remplace le calcul
            return self.saisies(p).get((kpi_id, org_id))
        if self.fige_pour(p, kpi_id) and (kpi_id, org_id) in self._imports_de(p):
            # période clôturée : un chiffre importé (publié dans un fichier historique, repris tel quel) est le chiffre officiel,
            # celui qu'utilisent les formules et les totaux qui le citent (le total affiché = somme des chiffres affichés)
            v = self.saisies(p).get((kpi_id, org_id))
            if v is not None:
                return v
        rang_k, rang_o = self.rangs[kpi.granularite_id], self.rangs[org.niveau_id]
        propre = rang_o == rang_k  # la case se saisit ici
        if rang_o > rang_k:  # sous la granularité (rang 1 = sommet)
            if not kpi.est_herite:
                self._msg(kpi_id, org_id, p, _Message("messages.calcul.kpi_absent_du_niveau", kpi=kpi_id, niveau=org.niveau.nom))
                return None
            porteur = self.porteur(kpi, org, p)
            if porteur is not org:  # repris de l'ancêtre de ce niveau (ou de l'organisation du dessus qui le porte)
                return self.valeur(kpi_id, porteur.id, p)
            propre = True  # aucun ancêtre de ce niveau : l'organisation porte sa propre valeur (CALC-09)
        if not kpi.est_calcule:
            if propre:
                v = self.saisies(p).get((kpi_id, org_id))
                if v is None and self.cumule(kpi, p):
                    return self._cumul(kpi, org, p)
                if v is None:
                    self._msg(kpi_id, org_id, p, _Message("messages.calcul.valeur_non_saisie", kpi=kpi_id, organisation=org.nom))
                return v
            if kpi.saisissable_au_dessus:  # valeur saisie ici quand le détail manque : elle remplace le total
                v = self.saisies(p).get((kpi_id, org_id))
                if v is not None:
                    return v
                if self.cumule(kpi, p):  # sans le détail de l'année : les mois saisis ici (ou leurs totaux)
                    v = self._agreger(kpi, org, p)
                    if v is None:
                        v = self._cumul(kpi, org, p)
                        if v is not None:
                            self.messages.pop((kpi_id, org_id, p.pk), None)
                    return v
            v = self._agreger(kpi, org, p)
            if v is None:  # total publié dans un fichier historique, repris tel quel : il vaut quand le détail manque (comme
                importee = self.saisies(p).get((kpi_id, org_id))  # pour un KPI calculé, plus bas)
                if importee is not None and (kpi_id, org_id) in self._imports[p.pk]:
                    return importee
            return v
        # KPI calculé
        if rang_o == rang_k or kpi.methode_agregation == KPI.Agregation.FORMULE:
            v = self._formule(kpi, org, p)
        elif kpi.methode_agregation == KPI.Agregation.SOMME:
            v = self._agreger(kpi, org, p)
            if v is None and self._sources_au_dessus(kpi):  # détail manquant mais sources saisies ici : formule refaite ici
                v = self._formule(kpi, org, p)
                if v is not None:
                    self.messages.pop((kpi_id, org_id, p.pk), None)
        else:
            v = None
        if v is None:  # valeur importée (historique importé) ; une saisie d'avant le passage en « Calculé » ne compte
            importee = self.saisies(p).get((kpi_id, org_id))  # que dans une période figée
            if importee is not None and ((kpi_id, org_id) in self._imports[p.pk] or self.fige_pour(p, kpi_id)):
                return importee
        return v

    def _sources_au_dessus(self, kpi):
        """Vrai si une source de la formule accepte la saisie aux niveaux supérieurs."""
        try:
            refs = F.references(kpi.formule)
        except F.FormuleInvalide:
            return False
        return any(self.kpis[r.kpi].saisissable_au_dessus for r in refs if r.kpi in self.kpis)

    def case_courte(self, kpi, org, f, debut, q):
        """Vrai si la période courte (``q``, ou celle de fréquence ``f`` qui commence à ``debut`` quand elle n'existe pas
        encore) a une case pour l'organisation : organisation ouverte pendant cette période, dans l'arbre qu'elle suit
        (``ouverte``, ``orgs_de``). Le cumul ne porte que sur ces périodes (README : « a closed site counts in the years
        when it was open », « a site counts only from its opening date ») ; un site fermé
        le 30/06, ou ouvert le 15/03, laissait son année « Incomplet » pour toujours (et sortait du total du pays)."""
        courte = q if q is not None else _PeriodeCourte(debut, P.ajouter_mois(debut, MOIS_PAR_FREQUENCE[f]) - datetime.timedelta(days=1))
        arbre = self.orgs_de(q, kpi.code)
        o = arbre.get(org.id)
        return o is not None and ouverte(o, courte, arbre) and self.demande_courte(kpi.code, f, courte)

    def demande_courte(self, code, f, courte):
        """Vrai si la période courte ``courte`` (fréquence ``f``, un mois par exemple) entre dans le cumul d'une période
        plus longue pour ce KPI. Règle exacte (corrigée au second tour du même jour) :

        - la période courte est demandée si AU MOINS UN référentiel actif demande le KPI dans SA période qui la
          contient : pour un référentiel de fréquence ``f`` (ou plus fine), la période courte elle-même (qu'elle ait
          déjà une campagne ou non, comme avant) ; pour un référentiel moins fréquent (trimestriel, semestriel,
          annuel), son trimestre, semestre ou exercice qui la contient, en entier (« demandé depuis » au plus tard le
          premier jour de cette période, ``demande_depuis.filtre_demande``), et seulement s'il a une campagne sur
          cette période (comme pour le périmètre d'une période, ``perimetre_calcul`` : un référentiel annuel sans
          campagne cette année-là ne la demande pas) ;
        - « demande le KPI » : le KPI est un élément du référentiel ou une source, de proche en proche, d'une formule
          d'un de ses éléments (``saisie.codes_perimetre``, la règle des cases offertes) ;
        - une période courte demandée par aucun référentiel est sautée : un KPI demandé depuis juillet par le seul
          référentiel mensuel ne rend pas l'année incomplète faute de janvier à juin (règle d'hier, à confirmer) ; mais s'il est aussi dans un référentiel annuel qui le demande toute l'année, janvier à juin restent
          demandés (avant ce second tour, seule la fréquence du mois était lue : 60, « calculé », sans message) ;
        - aucun élément daté dans les référentiels actifs : tout est demandé (comme avant « demandé depuis »)."""
        if self._refs_courtes is None:
            refs = list(Referentiel.objects.filter(actif=True).order_by("pk"))
            datee = ElementReferentiel.objects.filter(referentiel__actif=True, demande_depuis__isnull=False).exists()
            campagnes = set(Campagne.objects.values_list("referentiel_id", "periode__type", "periode__debut")) if datee else set()
            self._refs_courtes = (refs, datee, campagnes)
        refs, datee, campagnes = self._refs_courtes
        if not datee:  # aucun élément daté : demandé partout (comme avant)
            return True
        from .saisie import codes_perimetre

        for ref in refs:
            if P.plus_fine(f, ref.frequence):  # référentiel moins fréquent : sa période qui contient la courte, en entier
                n = MOIS_PAR_FREQUENCE[ref.frequence]
                ex = P.exercice_de(courte.debut, ref.mois_debut or 1)
                debut = next((d for d in P.debuts(ref.frequence, ex, ref.mois_debut or 1)
                              if d <= courte.debut < P.ajouter_mois(d, n)), courte.debut)
                if (ref.pk, ref.frequence, debut) not in campagnes:  # aucune campagne : il ne demande pas cette période
                    continue
            else:
                debut = courte.debut
            cle = (ref.pk, debut)
            if cle not in self._demandes_courtes:
                self._demandes_courtes[cle] = codes_perimetre(ref, _PeriodeCourte(debut, None))
            codes = self._demandes_courtes[cle]
            if codes is None or code in codes[1]:  # None : aucun référentiel ne contient de KPI (tout le catalogue)
                return True
        return False

    def _cumul(self, kpi, org, p):
        """Valeur d'une période longue à partir des périodes courtes qui la composent (agrégation dans le temps) : celles
        où la case existe (``case_courte``)."""
        f = self.frequences[kpi.code]
        valeurs, manquantes = [], []
        for debut in self.calendrier.contenues(p, f):
            q = self.calendrier.trouver(f, debut)
            if not self.case_courte(kpi, org, f, debut, q):
                continue
            v = self.valeur(kpi.code, org.id, q) if q is not None else None
            if v is None:
                manquantes.append(str(q) if q is not None else P.libelle(f, debut))
            else:
                valeurs.append(v)
        if manquantes:
            self._msg(kpi.code, org.id, p, _Message("messages.calcul.incomplet_periodes",
                                                   periodes=", ".join(manquantes[:4]) + (" …" if len(manquantes) > 4 else "")))
            return None
        if not valeurs:  # aucune période courte n'a de case : rien à cumuler (la valeur se saisit sur la période)
            self._msg(kpi.code, org.id, p, _Message("messages.calcul.valeur_non_saisie", kpi=kpi.code, organisation=org.nom))
            return None
        mode = kpi.agregation_temps
        if mode == KPI.AgregationTemps.DERNIERE or not kpi.est_numerique:
            return valeurs[-1]
        pleines = [v for v in valeurs if v is not NA]
        if not pleines:
            return NA
        total = sum(pleines, Decimal(0))
        return total / len(pleines) if mode == KPI.AgregationTemps.MOYENNE else total

    def _formule(self, kpi, org, p):
        if not kpi.formule.strip():
            self._msg(kpi.code, org.id, p, _Message("messages.calcul.pas_de_formule"))
            return None

        sources_na, sources_pleines = [], []

        def resoudre(ref):
            q = self.calendrier.resoudre(p, ref.decalage)
            v = self.valeur(ref.kpi, org.id, q) if q is not None else None
            if v is None:
                # d'après la référence, et non l'objet période (« q is p ») : une même case donnait « A » ou « A (2026) »
                # pour [A@2026] selon le chemin par lequel elle était calculée (directement, ou citée par une autre case)
                if ref.decalage == "N":
                    self._msg(kpi.code, org.id, p, _Message("messages.calcul.source_manquante", kpi=ref.kpi))
                else:
                    self._msg(kpi.code, org.id, p, _Message("messages.calcul.source_manquante_periode", kpi=ref.kpi,
                                                           periode=self.calendrier.libelle_cible(p, ref.decalage)))
            elif v is NA:
                sources_na.append(ref)
            else:
                sources_pleines.append(ref)
            return v

        try:
            arbre = self.arbre(kpi)
            v = F.evaluer(arbre, resoudre, na_zero=kpi.na_compte_zero)
            na = list(dict.fromkeys(sources_na))
            if na and v is not NA:  # case « Une source N/A compte comme 0 » : dit dans le détail du calcul
                self._msg(kpi.code, org.id, p, message_na_zero(list(dict.fromkeys(map(nom_ref, na)))))
            elif na and sources_pleines:  # N/A d'un terme d'un total, sans la case : le total est N/A (dit en clair)
                termes = F.refs_additives(arbre)
                noms = list(dict.fromkeys(nom_ref(r) for r in na if r in termes))
                if noms:
                    self._msg(kpi.code, org.id, p, _Message("messages.calcul.na_parce_que", n=len(noms), sources=", ".join(noms)))
            return v
        except F.ValeurManquante:
            return None
        except F.ErreurCalcul as e:
            self.messages[(kpi.code, org.id, p.pk)] = libelle("messages.calcul.erreur", detail=e)
            self.erreurs.add((kpi.code, org.id, p.pk))
            return None
        except F.FormuleInvalide as e:
            self.messages[(kpi.code, org.id, p.pk)] = libelle("messages.calcul.formule_invalide", detail=e)
            self.erreurs.add((kpi.code, org.id, p.pk))
            return None

    def enfants(self, org_id, periode=None, code=None):
        """Enfants directs ouverts pendant la période (par défaut, celle du calculateur), dans l'arbre que suit la
        période, ou le KPI ``code`` (``orgs_de``)."""
        periode = periode or self.periode
        cle = self._cle(periode, code)
        if cle not in self._enfants:
            par_parent = defaultdict(list)
            orgs = self.orgs_de(periode, code)
            for o in orgs.values():
                if o.parent_id and ouverte(o, periode, orgs):
                    par_parent[o.parent_id].append(o)
            self._enfants[cle] = par_parent
        return self._enfants[cle].get(org_id, [])

    def _avec_detail(self, rang, periode=None, code=None):
        """Organisations du niveau de ce rang, et celles au-dessus d'elles (en descendant par les organisations ouvertes
        pendant la période), dans l'arbre que suit la période, ou le KPI ``code``."""
        periode = periode or self.periode
        cle = (rang, self._cle(periode, code))
        if cle not in self._details:
            vus = set()
            orgs = self.orgs_de(periode, code)
            for o in orgs.values():
                if ouverte(o, periode, orgs) and self.rangs[o.niveau_id] == rang:
                    x = o
                    while x is not None and x.id not in vus:
                        vus.add(x.id)
                        x = orgs.get(x.parent_id) if ouverte(x, periode, orgs) else None
            self._details[cle] = vus
        return self._details[cle]

    def compte_sans_valeur(self, kpi, e, p, detail=None):
        """Vrai si l'enfant ``e``, sans valeur pour ce KPI sur la période ``p``, compte quand même dans le total de son
        parent (qu'il rend alors incomplet) : une organisation du niveau du KPI en dessous (``_avec_detail``), et active,
        ou avec une valeur sur la période (n'importe quel KPI, elle ou en dessous), ou, pour un KPI cumulé depuis des
        périodes plus courtes, une valeur dans l'une d'elles. Seule règle, pour la somme (``_agreger``) et pour le détail
        d'un total (``vues_cellule._detail_agregat`` : troisième, un site fermé qui rendait le total
        incomplet n'y figurait pas). ``detail`` : ``_avec_detail`` du rang du KPI, déjà lu."""
        if detail is None:
            detail = self._avec_detail(self.rangs[kpi.granularite_id], p, kpi.code)
        if e.id not in detail:
            return False
        if e.actif or e.id in self.avec_valeurs(p, kpi.code) or self.attend_validation(kpi, e, p):
            return True
        return self.cumule(kpi, p) and e.id in self.avec_valeurs_courtes(p, self.frequences[kpi.code], kpi.code)

    def attend_validation(self, kpi, e, p):
        """Vrai si l'organisation ``e`` (ou une organisation en dessous) a une valeur pas encore validée qui la fait
        compter dans ce total (règle « Tout brouillon compte » : de n'importe quel KPI sur la période) :
        une source validée manque à ce total. Toujours faux ici : l'outil compte toutes les valeurs (``avec_valeurs``) ;
        un calcul sur les seules valeurs validées (``visualisation.CalculateurValide``) le redéfinit, pour qu'un site
        fermé en brouillon rende le total « en attente » au lieu d'en sortir sans un mot."""
        return False

    def _agreger(self, kpi, org, p):
        if kpi.methode_agregation not in (KPI.Agregation.SOMME, KPI.Agregation.DECOMPTE):
            return None
        # enfants directs ; ceux rattachés sous la granularité du KPI n'ont pas de valeur propre
        rang_k = self.rangs[kpi.granularite_id]
        enfants = [e for e in self.enfants(org.id, p, kpi.code) if self.rangs[e.niveau_id] <= rang_k]
        valeurs = [self.valeur(kpi.code, e.id, p) for e in enfants]
        # un enfant sans aucune organisation du niveau du KPI en dessous (pays tout juste créé, sites rattachés
        # directement) n'a rien à saisir : sans valeur, il ne rend pas le total incomplet
        detail = self._avec_detail(rang_k, p, kpi.code)
        # une organisation fermée pendant la période compte avec ses valeurs, mais sans valeur elle ne rend pas le
        # total incomplet (fermée avant d'avoir rien saisi)
        # une organisation fermée pendant la période n'est écartée que si elle n'y a aucune valeur (fermée avant d'avoir
        # rien saisi) ; si elle a saisi d'autres KPI, une valeur manquante rend le total incomplet (rien n'est perdu en silence)
        # pour un KPI cumulé depuis les mois, ses valeurs des mois de la période en sont (un site
        # fermé le 30/06 à qui manquait juin sortait du total sans un mot)
        gardes = [(e, v) for e, v in zip(enfants, valeurs) if v is not None or self.compte_sans_valeur(kpi, e, p, detail)]
        if not gardes:  # rien à additionner : dit pourquoi (organisations fermées sans valeur, ou aucune organisation)
            fermees = [e.nom for e, v in zip(enfants, valeurs) if v is None and not e.actif]
            self._msg(kpi.code, org.id, p, _Message("messages.calcul.incomplet_organisations", organisations=", ".join(fermees))
                      if fermees else _Message("messages.calcul.sans_organisation"))
            return None
        enfants, valeurs = [e for e, _ in gardes], [v for _, v in gardes]
        if any(v is None for v in valeurs):
            manquants = [e.nom for e, v in zip(enfants, valeurs) if v is None]
            self._msg(kpi.code, org.id, p, _Message("messages.calcul.incomplet_organisations", organisations=", ".join(manquants)))
            return None
        reponses = [v for v in valeurs if v is not NA]
        if not reponses:
            return NA
        if kpi.methode_agregation == KPI.Agregation.DECOMPTE:
            total = Decompte()
            for v in reponses:
                total.update(v if isinstance(v, Counter) else {str(v): 1})
            return total
        return sum(reponses, Decimal(0))


# ---------------------------------------------------------------- écriture
def dependances_inverses():
    """{(KPI source, décalage): {KPI calculés qui le citent ainsi}}."""
    inverse = defaultdict(set)
    for c, s, d in KPIFormule.objects.values_list("kpi_calcule_id", "kpi_source_id", "decalage"):
        inverse[(s, d)].add(c)
    return inverse


def kpis_dependants(kpi_ids, decalage="N", inverse=None, annee=None):
    """KPI à recalculer quand les KPI donnés changent : sur la même période, eux-mêmes et tous leurs dépendants ;
    avec ``decalage`` « P-1 » ou « N-1 », ceux qui les citent ainsi (sur la période suivante) et leurs dépendants.
    ``annee`` : exercice de la période recalculée ; une formule qui cite cet exercice ([ID@2026] dans une période de 2026/27)
    cite la période elle-même, comme [ID] : elle en dépend aussi.
    ``inverse`` : table de ``dependances_inverses`` (sinon lue en base)."""
    inverse = dependances_inverses() if inverse is None else inverse
    depart = list(kpi_ids) if decalage == "N" else {c for k in kpi_ids for c in inverse.get((k, decalage), ())}
    meme_periode = ("N",) if annee is None else ("N", str(annee))
    vus, pile = set(), list(depart)
    while pile:
        k = pile.pop()
        if k in vus:
            continue
        vus.add(k)
        for d in meme_periode:
            pile.extend(inverse.get((k, d), ()))
    return vus


def cellules_calculees(kpi, orgs, rangs, cumul=False, orphelins=()):
    """Organisations où le KPI a une valeur calculée, agrégée ou cumulée dans le temps, avec l'origine correspondante.

    ``rangs`` : {code du niveau: rang}, rang 1 = sommet ; « au-dessus » = rang plus petit.
    ``cumul`` : la valeur de la période vient de périodes plus courtes (voir ``cumule``).
    ``orphelins`` : identifiants des organisations qui portent elles-mêmes ce paramètre hérité, faute d'ancêtre de son
    niveau (CALC-09) : leur case se cumule comme celles du niveau.
    """
    if kpi.est_texte and not kpi.est_calcule:  # texte rédigé : n'entre dans aucun calcul ni agrégation 
        return
    rang_k = rangs[kpi.granularite_id]
    for o in orgs:
        r = rangs[o.niveau_id]
        if kpi.est_calcule:
            if r == rang_k:
                yield o, Reponse.Origine.CALCUL
            elif r < rang_k and kpi.methode_agregation != KPI.Agregation.AUCUNE:
                yield o, Reponse.Origine.AGREGATION
        elif (r == rang_k or o.id in orphelins) and cumul:
            yield o, Reponse.Origine.CUMUL
        elif r < rang_k and kpi.methode_agregation in (KPI.Agregation.SOMME, KPI.Agregation.DECOMPTE):
            yield o, Reponse.Origine.AGREGATION


def _lisible(r):
    """Valeur d'une réponse pour le journal : « N/A », la réponse oui / non ou liste, ou le nombre sans zéros inutiles."""
    if r.non_applicable:
        return "N/A"
    if r.texte or r.valeur is None:
        return r.texte
    return format(r.valeur.normalize(), "f")


# recalcul ciblé des périodes ouvertes après une saisie (``organisations_touchees``) ; False : toutes leurs organisations
# (seulement pour la référence du test d'équivalence, ``collecte/test_calcul_cible.py``)
CIBLAGE_PERIODES_OUVERTES = True
MAX_ORGS_FILTRE_SQL = 500  # au-delà, les organisations ciblées se filtrent en Python (limite de paramètres de SQLite)


def lignes_arbre(periode=None, code=None):
    """{identifiant: (parent, active)} de l'arbre que suit la période (``arbre_suivi`` : celui de sa clôture dans une
    période figée dont l'arbre est noté ; sinon, ou sans période, celui d'aujourd'hui), pour le recalcul ciblé. Avec
    ``code`` : l'arbre de ce KPI (un KPI figé par une campagne clôturée suit celui du jour où il a été figé)."""
    fige = arbre_suivi(periode, code) if periode is not None else None
    if fige is None:
        return {o: (p, actif) for o, p, actif in Organisation.objects.values_list("id", "parent_id", "actif")}
    return {o.id: (o.parent_id, o.actif) for o in appliquer_arbre(fige, {
        o.id: o for o in Organisation.objects.only("id", "parent_id", "niveau_id", "actif")}).values()}


def organisations_touchees(kpi_ids, organisations, lignes=None):
    """Organisations dont une case calculée, agrégée ou cumulée peut changer quand les KPI ``kpi_ids`` changent dans les
    organisations ``organisations`` (une saisie, un import, une valeur forcée) ; None : toutes (recalcul complet).

    Ce qui fait dépendre une case d'une autre organisation, cas par cas (``Calculateur``) :
    - formule ([X], [X@P-1], [X@N-1], [X@AAAA]), cumul dans le temps (mois -> année), valeur forcée, valeur importée,
      valeur figée d'une période clôturée, saisie au-dessus de la granularité, formule refaite au-dessus
      (``_sources_au_dessus``) : toujours la même organisation, sur cette période ou une autre ;
    - agrégation (somme, décompte, formule refaite sur les totaux) : une case dépend de ses enfants, donc de toute
      l'organisation en dessous : un changement remonte aux ancêtres (chaîne des parents, ouverts ou non : un
      sur-ensemble des organisations ouvertes pendant la période) ;
    - organisation fermée pendant la période comptée seulement si elle a des valeurs (``avec_valeurs``) : dépend des
      saisies de l'organisation et de ses descendants, et ne joue que dans le total de ses ancêtres : déjà compris ;
    - N/A compté comme 0, décompte, arrondi, nombre trop grand : propres à la case ;
    - paramètre hérité (facteur d'émission) : sous sa granularité, une organisation reprend la valeur de son porteur
      (``porteur_herite`` : un ancêtre, ou elle-même) ; un porteur n'a jamais de valeur agrégée, seulement la sienne
      (saisie ou cumul de ses propres saisies), qui ne change que si sa propre saisie change : quand un KPI donné est un
      paramètre hérité, le changement descend à tous les descendants des organisations modifiées (puis leurs formules
      remontent aux ancêtres de ces descendants : déjà compris). Un KPI calculé n'est jamais hérité (un seul
      comportement par KPI) : les dépendants calculés ne descendent pas.
    Règle : organisations modifiées + leurs ancêtres (+ leurs descendants si l'un des KPI donnés est un paramètre
    hérité), dans l'arbre que suit chaque période refaite (``lignes`` : ``lignes_arbre`` ; celui de la clôture dans une
    période figée ; par défaut celui d'aujourd'hui ; quand les périodes refaites suivent des
    arbres différents, ``cibles_par_periode`` refait chacune dans le sien, le long des lectures). S'y ajoutent, dans ``prevoir``, les cases qui manquent encore
    ailleurs (jamais calculées). Une organisation fermée qui entre dans les totaux ou en sort change les totaux de tous
    les KPI au-dessus d'elle : ``kpis_a_refaire``. Structure de l'arbre, ouverture des organisations, niveaux,
    référentiels, formules : inchangés par une saisie (leurs changements passent par le recalcul complet). Dans le doute
    (KPI ou organisations non donnés, organisation inconnue), None : recalcul complet."""
    if kpi_ids is None or organisations is None:
        return None
    parents = ({o: p for o, (p, _) in lignes.items()} if lignes is not None
               else dict(Organisation.objects.values_list("id", "parent_id")))
    organisations = set(organisations)
    if not organisations or not organisations <= set(parents):
        return None
    touchees = set()
    for o in organisations:
        while o is not None and o not in touchees:
            touchees.add(o)
            o = parents.get(o)
    if KPI.objects.filter(code__in=list(kpi_ids), type_saisie__comportement="herite").exists():
        enfants = defaultdict(list)
        for o, p in parents.items():
            if p is not None:
                enfants[p].append(o)
        pile, vus = list(organisations), set()
        while pile:
            o = pile.pop()
            if o in vus:
                continue
            vus.add(o)
            touchees.add(o)
            pile.extend(enfants.get(o, ()))
    return None if len(touchees) >= len(parents) else touchees


def cibles_par_arbre(kpi_ids, organisations, arbres):
    """Borne large, gardée pour son test : n'est plus appelée par le recalcul. Elle ne
    distingue pas la période corrigée des périodes qui la lisent : dans un exercice rouvert « garder », elle refaisait
    le parent d'aujourd'hui d'une organisation corrigée qui ne l'était pas à l'époque (chiffre publié réécrit, contraire
    aux chiffres de l'époque et à la correction ciblée). Le recalcul suit ``cibles_par_periode``, période par période, le long des lectures.

    ``organisations_touchees`` quand les périodes refaites ne suivent pas toutes le même arbre (période figée : arbre
    de sa clôture ; les autres : celui d'aujourd'hui). ``arbres`` : liste de ``lignes_arbre`` ; renvoie la liste des
    organisations à refaire dans chacun (None : toutes).

    Une case lit la même organisation dans une autre période ([X@N-1], [X@P-1], [X@AAAA], cumul, valeur figée) : une
    organisation touchée dans un arbre l'est donc dans tous, et ses totaux sont ceux de ses ancêtres dans l'arbre de la
    période refaite. Règle : dans chaque arbre, ``organisations_touchees`` des organisations modifiées (ancêtres, et
    descendants pour un paramètre hérité : un porteur dont la valeur change la donne à ses descendants de cet arbre),
    plus toute organisation touchée dans un autre arbre et ses ancêtres dans celui-ci ; de proche en proche jusqu'à ce
    que rien ne s'ajoute. Avec un seul arbre (cas courant), c'est ``organisations_touchees``. Exemple : 2024 rouvert « garder », E2 déplacée depuis, une correction de E2 en 2024 laissait faux en 2025 le
    total de son pays de l'époque refait par une formule [X@N-1], et le CO2 de E2 qui lit le facteur de ce pays."""
    if kpi_ids is None or organisations is None:
        return [None] * len(arbres)
    organisations = set(organisations)
    propres = []
    for a in arbres:
        base = [o for o in organisations if o in a]
        t = organisations_touchees(kpi_ids, base, a) if base else set()
        propres.append(set(a) if t is None else set(t))
    if len({id(a) for a in arbres}) <= 1:
        return [None if len(t) >= len(a) else t for t, a in zip(propres, arbres)]
    touchees = set().union(*propres)
    while True:
        res = []
        for t, a in zip(propres, arbres):
            t = set(t)
            for o in touchees:
                while o is not None and o in a and o not in t:
                    t.add(o)
                    o = a[o][0]
            res.append(t)
        plus = set().union(*res)
        if plus <= touchees:
            break
        touchees |= plus
    return [None if len(t) >= len(a) else t for t, a in zip(res, arbres)]


def cibles_par_periode(sources, departs, lignes, herite=False):
    """Organisations à refaire dans une période (arbre ``lignes``, ``lignes_arbre`` de cette période) ; ensemble
    explicite, jamais None. Règle exacte du recalcul ciblé (qui remplace dans
    ``_recalculer`` la fermeture entre arbres de ``cibles_par_arbre``, trop large dans une période figée) :

    - période corrigée : ``sources`` = les organisations corrigées ; elles et leurs ancêtres DANS L'ARBRE DE CETTE
      PÉRIODE (celui de l'époque si elle est figée), plus leurs descendants si l'un des KPI changés est un paramètre
      hérité (``organisations_touchees``). Un parent d'aujourd'hui qui ne l'était pas à l'époque n'y est jamais refait
      son chiffre publié ne bouge pas) ;
    - toute autre période refaite (cumul d'une période plus longue, [X@N-1], [X@P-1], [X@AAAA]) : ``sources`` = les
      organisations touchées dans les périodes qu'elle lit ; une case n'y lit jamais que la même organisation dans
      l'autre période, donc ce sont elles, et leurs ancêtres dans l'arbre de CETTE période (ses totaux) ; pour un
      paramètre hérité changé, aussi les descendants, dans cet arbre, des organisations corrigées (``departs`` : un
      porteur dont le cumul change le donne à ses descendants de cette période).
    Une organisation absente de l'arbre (créée depuis la clôture, supprimée) n'y a pas de case : écartée."""
    base = {o for o in sources if o in lignes}
    if herite and departs:
        enfants = defaultdict(list)
        for o, (p, _) in lignes.items():
            if p is not None:
                enfants[p].append(o)
        pile, vus = [o for o in departs if o in lignes], set()
        while pile:
            o = pile.pop()
            if o not in vus:
                vus.add(o)
                base.add(o)
                pile.extend(enfants.get(o, ()))
    touchees = set()
    for o in base:
        while o is not None and o not in touchees and o in lignes:
            touchees.add(o)
            o = lignes[o][0]
    return touchees


def kpis_a_refaire(kpi_ids, organisations, periode, lignes=None):
    """KPI à refaire sur ``periode`` après un changement des KPI ``kpi_ids`` dans les organisations ``organisations`` :
    eux (et leurs dépendants, ``kpis_dependants``), ou tous les KPI quand le changement peut faire entrer ou sortir une
    organisation désactivée des totaux de ses ancêtres. Une organisation fermée pendant la période ne compte dans le total
    de son parent que si elle (ou une organisation en dessous) a une valeur sur la période, de n'importe quel KPI
    (``Calculateur.avec_valeurs``) : sa première valeur (ou la dernière effacée) change aussi les totaux des autres KPI
    au-dessus d'elle. Avant, seuls les KPI saisis et leurs dépendants étaient refaits : ces totaux restaient faux jusqu'au
    recalcul suivant de leur KPI (``collecte/test_calcul_correctifs.py``). Repéré largement (dans le
    doute, tout est refait) : une organisation désactivée de la lignée dont la branche n'a pas plus de valeurs que de
    cases changées. ``lignes`` : arbre de la période (``lignes_arbre``), lu sinon."""
    if kpi_ids is None or organisations is None:
        return kpi_ids
    lignes = lignes_arbre(periode) if lignes is None else lignes
    fermees, vus = set(), set()
    for o in organisations:
        while o is not None and o not in vus:
            vus.add(o)
            p, actif = lignes.get(o, (None, True))
            if not actif:
                fermees.add(o)
            o = p
    if not fermees:
        return kpi_ids
    enfants = defaultdict(list)
    for o, (p, _) in lignes.items():
        if p is not None:
            enfants[p].append(o)
    calcules = [k for k, c in KPI.objects.values_list("code", "type_saisie__comportement") if c == "calcul"]
    changees = len(kpi_ids) * len(organisations)
    for e in fermees:
        branche, pile = set(), [e]
        while pile:
            x = pile.pop()
            if x not in branche:
                branche.add(x)
                pile.extend(enfants.get(x, ()))
        # valeurs de la branche, comme ``avec_valeurs`` (sans les anciennes saisies d'un KPI devenu calculé : en compter
        # moins fait seulement tout refaire plus souvent)
        valeurs = Reponse.objects.filter(periode=periode, origine__in=[Reponse.Origine.SAISIE, Reponse.Origine.IMPORT,
                                                                       Reponse.Origine.FORCEE])
        valeurs = valeurs.filter(Q(non_applicable=True) | Q(valeur__isnull=False) | ~Q(texte=""))
        valeurs = valeurs.exclude(origine=Reponse.Origine.SAISIE, kpi_id__in=calcules)
        n = sum(valeurs.filter(organisation_id__in=lot).count() for lot in par_lots(sorted(branche)))
        if n <= changees:
            return list(KPI.objects.values_list("code", flat=True))
    return kpi_ids


def prevoir(calc, kpi_ids=None, organisations=None):
    """Ce que le recalcul de la période du calculateur enregistrerait, sans rien écrire (``_ecrire`` l'applique ; le
    contrôle de cohérence de la base, ``collecte.controle_donnees``, le compare à ce qui est enregistré).

    ``organisations`` : identifiants des seules organisations à refaire (``organisations_touchees``) ; None : toutes.
    Les cases des autres organisations ne changent pas ; celles qui manquent encore (jamais calculées) sont calculées.
    Dans une période figée (correction importée dans une campagne clôturée), toute case qui n'est pas
    refaite est lue telle qu'enregistrée : le total d'une organisation corrigée reste la somme des chiffres affichés.

    Renvoie (cellules, sans_objet) : cellules = [(réponse existante ou None, KPI, organisation, champs, remplacée)] des
    cases calculées, agrégées ou cumulées à écrire (``remplacée`` : ancienne saisie d'un KPI devenu calculé) ;
    sans_objet = réponses calculées que les réglages d'aujourd'hui ne produisent plus (période non figée)."""
    periode = calc.periode
    cibles = set(calc.kpis) if kpi_ids is None else kpis_dependants(kpi_ids, annee=calc.calendrier.exercice(periode))
    ouvertes_par_arbre = {}

    def orgs_du_kpi(kid):
        """Organisations ouvertes pendant la période dans l'arbre que suit le KPI : celui de l'époque dans une période
        figée, ou pour un KPI figé par une campagne clôturée."""
        cle = calc._cle(periode, kid)
        if cle not in ouvertes_par_arbre:
            arbre = calc.orgs_de(periode, kid)
            ouvertes_par_arbre[cle] = [o for o in arbre.values() if ouverte(o, periode, arbre)]
        return ouvertes_par_arbre[cle]

    presentes = None if organisations is None else set(
        Reponse.objects.filter(periode=periode, kpi_id__in=cibles).values_list("kpi_id", "organisation_id"))
    qs = Reponse.objects.filter(periode=periode, kpi_id__in=cibles)
    if organisations is not None and len(organisations) <= MAX_ORGS_FILTRE_SQL:
        qs = qs.filter(organisation_id__in=organisations)
    existantes = {(r.kpi_id, r.organisation_id): r for r in qs
                  if organisations is None or r.organisation_id in organisations}
    figee_ici = calc.figee(periode)  # correction importée dans une campagne clôturée : rien d'autre n'y change
    if figee_ici and organisations is not None:
        calc.refaites = (set(cibles), set(organisations))
    # KPI figés par une campagne clôturée de la période (règle « Figer ses chiffres ») : rien ne les écrit,
    # ni case nouvelle, ni case sans objet ; seule une correction de l'un d'eux refait ses cases ciblées
    gelees = {} if figee_ici else calc.gelees(periode)
    perimetre = perimetre_calcul(periode)  # mois : KPI du périmètre de ses campagnes seulement
    cellules, sans_objet = [], []
    for kid in cibles:
        kpi = calc.kpis.get(kid)
        if kpi is None or not kpi.actif:
            continue
        gelee = kid in gelees
        if gelee and kid not in calc.refaites_gelees:
            continue
        produites = set()
        cumul = calc.cumule(kpi, periode)
        orphelins = calc.orphelins(kpi.granularite_id, kid) if cumul and kpi.est_herite else ()
        # hors du périmètre d'un mois : aucune case ; celles déjà écrites (avant la règle du périmètre, ou KPI retiré du
        # référentiel) sont sans objet, comme une agrégation retirée (période non figée)
        produire = perimetre is None or kid in perimetre
        for org, origine in cellules_calculees(kpi, orgs_du_kpi(kid), calc.rangs, cumul, orphelins) if produire else ():
            produites.add(org.id)
            if gelee and org.id not in calc.refaites_gelees[kid]:
                continue  # KPI figé : seules les cases de la correction sont refaites
            if presentes is not None and org.id not in organisations and (kid, org.id) in presentes:
                continue  # hors des organisations ciblées, case déjà là : inchangée
            r = existantes.get((kid, org.id))
            saisie = r is not None and r.origine == Reponse.Origine.SAISIE and (r.valeur is not None or r.texte or r.non_applicable)
            if r is not None and (r.origine in (Reponse.Origine.IMPORT, Reponse.Origine.FORCEE)
                                  or saisie and (not kpi.est_calcule or figee_ici or gelee)):
                continue  # valeur importée ou forcée, ou saisie sur la période elle-même : jamais écrasée
            v = calc.valeur(kid, org.id)
            msg = calc.message(kid, org.id)
            # statut d'erreur noté par le calculateur (et non deviné d'après le texte, qui dépend de la langue)
            statut = Reponse.Statut.CALCULE if v is not None else (
                Reponse.Statut.ERREUR if (kid, org.id, periode.pk) in calc.erreurs else Reponse.Statut.INCOMPLET)
            texte = ""
            if isinstance(v, Decompte):  # oui / non, liste : nombre de réponses, et leur détail en texte
                v, texte = Decimal(sum(v.values())), v.texte(kpi.choix)
            elif isinstance(v, str):  # oui / non, liste cumulés dans le temps (dernière valeur)
                v, texte = None, v
            if isinstance(v, Decimal) and v.is_finite() and abs(v) >= VALEUR_MAX:
                # résultat hors de ce que la base garde (somme ou formule sur de très grands nombres) : erreur nommée
                v, statut = None, Reponse.Statut.ERREUR
                msg = libelle("messages.calcul.trop_grand")
            champs = dict(
                valeur=None if v is None or v is NA else valeur_enregistree(v), texte=texte,
                non_applicable=v is NA, statut=statut, origine=origine, message_calcul=msg[:300],
            )
            cellules.append((r, kid, org, champs, saisie))  # saisie : KPI devenu calculé, la formule remplace l'ancienne saisie
        if not figee_ici and not gelee:  # cellules calculées que le réglage d'aujourd'hui ne produit plus (agrégation…)
            # aussi celles d'une organisation fermée avant la période (désactivée après coup) : sinon son ancien total
            # restait dans la campagne en cours et dans les exports (cas au hasard, graine 3513)
            sans_objet += [r for (k, o), r in existantes.items()
                           if k == kid and r.est_calculee and o not in produites and o in calc.orgs]
    return cellules, sans_objet


def _ecrire(calc, kpi_ids=None, organisations=None):
    """Enregistre les valeurs calculées, agrégées et cumulées de la période du calculateur."""
    periode = calc.periode
    cellules, sans_objet = prevoir(calc, kpi_ids, organisations)
    a_creer, a_maj, remplacees = [], [], []
    for r, kid, org, champs, remplacee in cellules:
        if remplacee:  # KPI devenu calculé : la formule remplace l'ancienne saisie (gardée au journal)
            remplacees.append((r, _lisible(r)))
        if r is None:
            a_creer.append(Reponse(periode=periode, kpi_id=kid, organisation=org, **champs))
        elif any(getattr(r, c) != val for c, val in champs.items()):
            for c, val in champs.items():
                setattr(r, c, val)
            a_maj.append(r)
    Reponse.objects.bulk_create(a_creer, batch_size=1000)
    Reponse.objects.bulk_update(a_maj, ["valeur", "texte", "non_applicable", "statut", "origine", "message_calcul"], batch_size=1000)
    if remplacees:
        from .models import Journal

        for r, avant in remplacees:
            Journal.ecrire(None, "valeur_recalculee", r, "valeur", avant, _lisible(r))
    n = len(a_creer) + len(a_maj)
    if sans_objet:
        from .models import Preuve

        avec_preuve = set()
        for lot in par_lots([r.pk for r in sans_objet]):  # par lots : SQLite refuse plus de 32 766 paramètres
            avec_preuve.update(Preuve.objects.filter(reponse_id__in=lot).values_list("reponse_id", flat=True))
        gardees = [r for r in sans_objet if r.commentaire.strip() or r.pk in avec_preuve]
        for r in gardees:  # commentaire ou preuve : la cellule reste, vide, à saisir
            r.valeur, r.texte, r.non_applicable, r.message_calcul = None, "", False, ""
            r.statut, r.origine = Reponse.Statut.A_SAISIR, Reponse.Origine.SAISIE
        Reponse.objects.bulk_update(gardees, ["valeur", "texte", "non_applicable", "statut", "origine", "message_calcul"],
                                    batch_size=1000)
        pk_gardees = {r.pk for r in gardees}
        supprimer_par_pk(Reponse, [r.pk for r in sans_objet if r.pk not in pk_gardees])
        n += len(sans_objet)
    return n


def _ecrire_installation(calc, kpi_ids=None, organisations=None):
    """``_ecrire`` avec les messages de calcul (enregistrés avec les valeurs) dans la langue de l'installation, quelle que
    soit la langue de la personne qui a déclenché le recalcul. L'état des langues est lu une fois (hors requête, chaque
    message le relirait en base : deux requêtes par case incomplète, l'essentiel du temps d'un recalcul en commande)."""
    with L.session(), L.activer_interface(L.defaut()):
        return _ecrire(calc, kpi_ids, organisations)


@ESP.atomic
def recalculer(cible, kpi_ids=None, propager=True, organisations=None, lecteurs_seulement=False):
    """Recalcule et enregistre les valeurs calculées, agrégées et cumulées d'une campagne (ou d'une période).

    kpi_ids=None : tout recalculer. Sinon : les KPI donnés et leurs dépendants.
    ``propager`` : refaire aussi les périodes qui en dépendent et ne sont pas figées (toutes leurs campagnes clôturées) :
    les périodes plus longues qui la contiennent (cumuls) ; puis, depuis la période et chacune de ces périodes plus
    longues, la période suivante pour les formules [ID@P-1], la même période l'année suivante pour [ID@N-1] et la même
    période des autres exercices pour [ID@AAAA] (AAAA : l'exercice de la période, celui qui commence cette année-là).
    Les valeurs importées ne sont jamais écrasées. Renvoie le nombre de cellules écrites.
    ``organisations`` (avec ``kpi_ids``) : organisations où ces KPI ont changé (saisie, import, valeur forcée) ; tous les
    KPI sont refaits si une organisation fermée de leur lignée peut entrer dans les totaux ou en sortir
    (``kpis_a_refaire``) ; seules ces organisations, leurs ancêtres et, pour un paramètre hérité, leurs descendants sont
    refaits (``organisations_touchees``), sur toutes les périodes refaites. Dans une période figée (correction importée
    dans une campagne clôturée), les autres cases sont lues telles qu'enregistrées.
    ``lecteurs_seulement`` (avec ``kpi_ids`` et ``organisations``) : la période elle-même n'est pas réécrite, seules
    les périodes qui la lisent le sont (``rendre_officiels``, à la clôture).
    """
    # langues lues une fois : hors requête (commandes, tests), chaque message de calcul les relisait en base (10 fois
    # plus lent) ; dans une requête, elles le sont déjà (parametres.langues.LangueMiddleware)
    with L.session():
        return _recalculer(cible, kpi_ids, propager, organisations, lecteurs_seulement)


def _recalculer(cible, kpi_ids, propager, organisations=None, lecteurs_seulement=False):
    periode = periode_de(cible)
    # un recalcul à la fois (saisies simultanées, PostgreSQL) : le suivant attend, puis voit la saisie du précédent.
    # Toutes les périodes, toujours dans le même ordre : un recalcul réécrit aussi d'autres périodes (l'année qui
    # contient le mois saisi, celles qui le citent par [ID@P-1], [ID@N-1]…) ; deux saisies dans deux mois écrivaient la
    # même année en même temps (total faux, ou erreur à la création de la même case). Sous SQLite, les transactions
    # « immediate » se suivent déjà.
    list(type(periode).objects.select_for_update().order_by("pk").values_list("pk", flat=True))
    calendrier, frequences = P.Calendrier(), frequences_de_saisie()
    # arbre de chaque période refaite : celui de sa clôture dans une période figée dont l'arbre est noté,
    # sinon celui d'aujourd'hui (clé None) ; lu une fois par période, sous le verrou
    suivis, arbres = {}, {}

    def lignes(q):
        if q is not None and q.pk not in suivis:
            suivis[q.pk] = arbre_suivi(q) is not None
        cle = q.pk if q is not None and suivis[q.pk] else None
        if cle not in arbres:
            arbres[cle] = lignes_arbre(q if cle is not None else None)
        return arbres[cle]

    figee_ici = figee(periode)
    if organisations is None and chiffres_gardes(periode):
        # rouverte en gardant les chiffres de l'époque : pas de recalcul d'ensemble (réglage changé,
        # organisation déplacée, « recalculer ») ; seule une correction (organisations données) y écrit
        return 0
    if figee_ici and organisations is not None:
        # une organisation absente de l'arbre de l'époque (créée depuis) n'a pas de case dans la période figée : rien à
        # y refaire pour elle (sa saisie y est refusée, ``saisie.organisation_pas_ouverte``)
        organisations = [o for o in organisations if o in lignes(periode)]
        if not organisations:
            return 0
    changes = None if kpi_ids is None else list(kpi_ids)
    kpi_ids = kpis_a_refaire(kpi_ids, organisations, periode, lignes(periode))  # lu sous le verrou
    # recalcul ciblé (``cibles_par_periode``) : pour chaque période refaite, les seules
    # organisations dont une case peut changer, dans l'arbre de CETTE période. Période corrigée : l'organisation
    # corrigée et ses ancêtres de son arbre (celui de l'époque si elle est figée : ; un parent
    # d'aujourd'hui qui ne l'était pas à l'époque garde son chiffre publié) ; toute autre période : les organisations
    # touchées dans les périodes qu'elle lit (même organisation : [X@N-1], [X@P-1], [X@AAAA], cumul), avec leurs
    # ancêtres dans son arbre à elle. Dans une période figée, les autres cases sont lues telles qu'enregistrées.
    ciblees = kpi_ids is not None and organisations is not None
    herite = ciblees and KPI.objects.filter(code__in=list(kpi_ids), type_saisie__comportement="herite").exists()
    depart_orgs = frozenset(organisations) if ciblees else None
    touchees = {}  # {pk de la période: organisations touchées (ensemble explicite)} ; seulement si ``ciblees``

    def depuis(q, sources):
        """Organisations à refaire dans ``q`` quand elle lit les organisations ``sources`` (``cibles_par_periode``)."""
        return cibles_par_periode(sources, depart_orgs, lignes(q), herite)

    figees, gardees = {periode.pk: figee_ici}, {}

    def libre(q):
        if q.pk not in figees:
            figees[q.pk] = figee(q)
        return not figees[q.pk]

    def pour_ecrire(q):
        """Argument ``organisations`` de l'écriture de ``q`` : None (toutes) hors ciblage, ou pour une période libre
        entièrement touchée (``CIBLAGE_PERIODES_OUVERTES`` faux : référence du test d'équivalence) ; jamais None dans
        une période figée corrigée (sinon tout y serait recalculé)."""
        if not ciblees:
            return None
        t = touchees.get(q.pk, set())
        if libre(q) and (not CIBLAGE_PERIODES_OUVERTES or len(t) >= len(lignes(q))):
            return None
        return t

    if ciblees:
        touchees[periode.pk] = set(depuis(periode, depart_orgs))
    # KPI figés par une campagne clôturée de la période (règle « Figer ses chiffres ») : seule une
    # correction de l'un d'eux (correction importée dans la campagne clôturée) en refait les cases, comme dans une
    # période figée : l'organisation corrigée et ses ancêtres dans l'arbre du jour où le KPI a été figé (plus ses
    # descendants pour un paramètre hérité), pour les KPI figés changés et ceux qui en dépendent (tous les KPI figés si
    # une organisation fermée de la lignée peut entrer dans les totaux ou en sortir, ``kpis_a_refaire``) ; toute autre
    # écriture les laisse tels qu'enregistrés
    calc = None if lecteurs_seulement else Calculateur(periode, calendrier, frequences)
    gelees_ici = {} if figee_ici or calc is None else calc.gelees(periode)
    if ciblees and gelees_ici and any(k in gelees_ici for k in changes):
        corriges = [k for k in changes if k in gelees_ici]
        arbres_k = {}

        def lignes_k(k):
            i = gelees_ici[k]
            if i not in arbres_k:
                arbres_k[i] = lignes_arbre(periode, k)
            return arbres_k[i]

        ids_g = kpis_a_refaire(corriges, organisations, periode, lignes_k(corriges[0]))
        ids_g = kpis_dependants(ids_g, annee=calendrier.exercice(periode)) & set(gelees_ici)
        for k in sorted(ids_g):
            calc.refaites_gelees[k] = cibles_par_periode(depart_orgs, depart_orgs, lignes_k(k), herite)
            touchees[periode.pk] |= calc.refaites_gelees[k]
        kpi_ids = sorted(set(kpi_ids) | ids_g)
    # ``lecteurs_seulement`` : la période lue n'est pas réécrite (``rendre_officiels``), seules celles qui la lisent
    n = 0 if calc is None else _ecrire_installation(
        calc, kpi_ids, pour_ecrire(periode) if figee_ici or CIBLAGE_PERIODES_OUVERTES else None)
    if not propager:
        return n

    def refaisable(q, x):
        """Vrai si ``q`` est refaite quand elle lit la période ``x`` : période libre ; période rouverte en gardant les
        chiffres de l'époque seulement pour un recalcul ciblé dont une organisation touchée dans ``x`` existe
        dans son arbre (jamais toute la période) ; jamais une période close."""
        if libre(q):
            return True
        if q.pk not in gardees:
            gardees[q.pk] = chiffres_gardes(q)
        return gardees[q.pk] and ciblees and bool(depuis(q, touchees[x.pk]))

    def lire(q, x):
        """``q`` lit ``x`` : ses organisations touchées s'y ajoutent."""
        if ciblees:
            touchees.setdefault(q.pk, set()).update(depuis(q, touchees[x.pk]))

    reecrites = [periode]
    for q in calendrier.englobantes(periode):
        if refaisable(q, periode):
            lire(q, periode)
            n += _ecrire_installation(Calculateur(q, calendrier, frequences), kpi_ids, pour_ecrire(q))
            reecrites.append(q)
    # KPI refaits sur la période : ceux donnés et leurs dépendants (un KPI calculé changé change aussi les périodes
    # qui le citent par [ID@N-1], [ID@P-1] ou [ID@AAAA]) ; puis, de proche en proche, les périodes non figées qui citent
    # une période refaite (stock du mois = stock du mois d'avant + entrées : tous les mois suivants)
    inverse = dependances_inverses()
    depart = set(KPI.objects.values_list("code", flat=True)) if kpi_ids is None else kpis_dependants(
        kpi_ids, inverse=inverse, annee=calendrier.exercice(periode))
    refaits = {x.pk: set(depart) for x in reecrites}  # KPI déjà refaits, par période
    suites, pile = {}, [(x, depart) for x in reecrites]  # période à refaire : (période, KPI à refaire), chacune une fois
    lectures = set()  # (période lue, période qui la lit) : pour refermer les organisations touchées
    par_pk = {x.pk: x for x in reecrites}
    while pile:
        x, ids_x = pile.pop()
        cibles = [("P-1", calendrier.suivante(x)), ("N-1", calendrier.decalee(x, 12))]
        # [ID@AAAA] : même période (même rang) des autres exercices ; q la cite par l'exercice de x vu depuis q
        # (exercice de q + écart en années), soit l'exercice qui commence en AAAA 
        cibles += [(str(calendrier.exercice(q) + (x.debut.year - q.debut.year)), q) for q in calendrier.par_cle.values()
                   if q.type == x.type and q.debut.month == x.debut.month and q.pk != x.pk]
        for decalage, q in cibles:
            if q is None or not refaisable(q, x):
                continue
            ids = kpis_dependants(ids_x, decalage, inverse, annee=calendrier.exercice(q)) - refaits.setdefault(q.pk, set())
            if ids:
                lectures.add((x.pk, q.pk))
                par_pk[q.pk] = q
                lire(q, x)
                refaits[q.pk] |= ids
                suites.setdefault(q.pk, (q, set()))[1].update(ids)
                pile.append((q, ids))
    while ciblees:  # organisations touchées refermées le long des lectures (une période lue a pu grandir après coup)
        plus = False
        for xp, qp in lectures:
            t = depuis(par_pk[qp], touchees[xp])
            if not t <= touchees[qp]:
                touchees[qp] |= t
                plus = True
        if not plus:
            break
    for q, ids in suites.values():
        n += _ecrire_installation(Calculateur(q, calendrier, frequences), ids, pour_ecrire(q))
    return n


def recalculer_en_cours():
    """Refait les calculs et les alertes de cohérence de toutes les campagnes non clôturées (une fois par période) :
    après un changement qui touche tous les totaux (organisation désactivée, rattachée ailleurs, créée…)."""
    from .coherence import controler

    faites = set()
    with L.session():  # langues lues une fois (voir _ecrire_installation)
        for c in Campagne.objects.exclude(statut=Campagne.Statut.CLOTUREE).select_related("referentiel", "periode"):
            if c.periode_id not in faites:
                recalculer(c)  # rien dans une période rouverte en gardant les chiffres de l'époque (``_recalculer``)
                faites.add(c.periode_id)
            controler(c)


@contextmanager
def si_frequences_changent():
    """Autour d'un changement de référentiels (activé, désactivé, KPI ajoutés ou retirés) : si la fréquence de collecte
    d'un KPI change (un référentiel mensuel en plus ou en moins), ses cumuls dans le temps aussi : tout est refait."""
    avant = frequences_de_saisie()
    yield
    if frequences_de_saisie() != avant:
        recalculer_en_cours()
