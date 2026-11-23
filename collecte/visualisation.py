"""Visualisation : lecture des valeurs pour les graphiques et les tableaux (onglet Visualisation).

Règles :
- Périmètre : celui des exports. L'administrateur voit tout ; le validateur, les organisations qui lui sont attribuées et leurs
  descendantes ; le contributeur, ses cases. Le lecteur et l'auditeur voient tout, ou les organisations choisies pour eux
  (et leurs descendantes).
- Par défaut, seules les valeurs validées comptent : un total (agrégat, formule, cumul dans le temps) est refait par le
  moteur de calcul à partir des seules valeurs validées (``CalculateurValide``) ; s'il lui manque une source validée, il
  n'a pas de valeur et s'affiche « en attente de validation ».
- « Inclure les brouillons » : les valeurs de l'outil (celles des exports, brouillons compris) ; une valeur qui diffère de
  son calcul sur les seules valeurs validées est « provisoire ».
- Une période figée (toutes ses campagnes clôturées) montre ses totaux tels qu'enregistrés (ceux des exports), sans les
  refaire avec les réglages d'aujourd'hui (organisation désactivée depuis, formule changée, valeur importée).
- N-1 : même période l'an dernier. Évolution : les périodes du même type qui précèdent (6 années, 12 mois…).
"""
import datetime
from collections import Counter, namedtuple
from dataclasses import dataclass
from decimal import Decimal

from parametres.libelles import libelle
from referentiel.formule import NA
from referentiel.models import KPI, Frequence, KPIFormule

from . import calcul as C
from . import exports as E
from . import periodes as P
from . import saisie as S
from .models import Campagne, Reponse

NB_EVOLUTION = {Frequence.ANNEE: 6, Frequence.SEMESTRE: 6, Frequence.TRIMESTRE: 8, Frequence.MOIS: 12}
NB_REPARTITION = 6  # parts nommées ; le reste est regroupé dans « Autres »


class CalculateurValide(C.Calculateur):
    """Même calcul que l'outil, à partir des seules valeurs validées (et des KPI utiles à la page, avec les sources de
    leurs formules) : un total dont une source est en brouillon ou manque n'a pas de valeur."""

    def __init__(self, codes=None, **kw):
        super().__init__(None, **kw)
        self.codes = sources(codes) if codes is not None else None

    def reponses_saisies(self, periode):
        qs = super().reponses_saisies(periode).filter(statut=Reponse.Statut.VALIDE)
        return qs if self.codes is None else qs.filter(kpi_id__in=self.codes)

    def reponses_periode(self, periode):
        qs = super().reponses_periode(periode)
        return qs if self.codes is None else qs.filter(kpi_id__in=self.codes)

    def presence(self, periode):
        """Valeurs validées de TOUS les KPI de la période (``Calculateur.presence``) : une organisation fermée pendant la
        période qui a une valeur d'un autre KPI que ceux de la page compte dans les totaux, et les rend incomplets sans
        valeur pour eux, comme dans la Saisie et les exports (troisième passe du calcul)."""
        if self.codes is None:
            return super().presence(periode)
        if not hasattr(self, "_presences"):
            self._presences = {}
        if periode.pk not in self._presences:
            valeurs, imports, forcees = {}, set(), set()
            qs = C.Calculateur.reponses_saisies(self, periode).filter(statut=Reponse.Statut.VALIDE)
            for kpi_id, org_id, val, texte, na, origine in qs.values_list("kpi_id", "organisation_id", "valeur", "texte",
                                                                          "non_applicable", "origine"):
                valeurs[(kpi_id, org_id)] = NA if na else val if val is not None else (texte or None)
                if origine == Reponse.Origine.IMPORT:
                    imports.add((kpi_id, org_id))
                elif origine == Reponse.Origine.FORCEE:
                    forcees.add((kpi_id, org_id))
            self._presences[periode.pk] = (valeurs, imports, forcees)
        return self._presences[periode.pk]

    def attend_validation(self, kpi, e, p):
        """Vrai si l'organisation ``e`` (ou une organisation en dessous) a une valeur saisie, importée ou forcée pas encore
        validée qui la fait compter dans ce total : le total est alors « en attente de validation » (règle du module :
        une source validée manque), comme la Saisie, qui compte toutes les valeurs, dit « Incomplet ». Règle « Tout
        brouillon compte » (règle du projet, qui remplace l'ancienne règle limitée au KPI et aux sources
        de sa formule) :

        - une valeur pas encore validée de N'IMPORTE QUEL KPI sur la période (la règle de présence de l'outil,
          ``Calculateur.avec_valeurs`` : un site fermé qui a une valeur sur la période compte dans les totaux) ;
        - pour un KPI cumulé depuis des périodes plus courtes, de même dans ses périodes plus courtes
          (``avec_valeurs_courtes``) ;
        - comme avant, une valeur pas encore validée d'une source de sa formule dans les périodes plus courtes dont
          cette source se cumule.
        Sans elle, un site fermé pendant la période qui n'avait que des brouillons sortait du total sans un mot (comportement des versions antérieures)."""
        if not hasattr(self, "_attentes"):
            self._attentes = {}
        cle = (kpi.code, p.pk)
        if cle not in self._attentes:
            tous = set()

            def monter(q, organisations):
                orgs = self.orgs_de(q, kpi.code)
                for o in organisations:
                    x = orgs.get(o)
                    while x is not None and x.id not in tous:
                        tous.add(x.id)
                        x = orgs.get(x.parent_id)

            def courtes(code):
                f = self.frequences[code]
                return [q for q in (self.calendrier.trouver(f, d) for d in self.calendrier.contenues(p, f)) if q]

            # tout KPI, sur la période (et sur les périodes plus courtes d'un KPI cumulé)
            for q in [p] + (courtes(kpi.code) if self.cumule(kpi, p) else []):
                monter(q, {o for os_ in self._non_validees(q).values() for o in os_})
            for code in self._sources_meme_periode(kpi.code) - {kpi.code}:  # sources cumulées : leurs périodes courtes
                k = self.kpis.get(code)
                if k is not None and self.cumule(k, p):
                    for q in courtes(code):
                        monter(q, self._non_validees(q).get(code, ()))
            self._attentes[cle] = tous
        return e.id in self._attentes[cle]

    def _cumul(self, kpi, org, p):
        """Cumul des périodes plus courtes, sauf quand l'organisation a, sur la période elle-même, une valeur pas encore
        validée de ce KPI : la Saisie montre cette valeur (elle remplace le cumul), la valeur validée l'attend (avant, le
        cumul des périodes courtes validées passait pour la valeur validée, quatrième passe du calcul)."""
        if org.id in self._non_validees(p).get(kpi.code, ()):
            return None
        return super()._cumul(kpi, org, p)

    def _sources_meme_periode(self, code):
        """Le KPI et les sources de sa formule de la même période (décalage « N »), de proche en proche ; graphe lu une
        fois par calculateur."""
        if not hasattr(self, "_graphe_n"):
            self._graphe_n = {}
            for c, s in KPIFormule.objects.filter(decalage="N").values_list("kpi_calcule_id", "kpi_source_id"):
                self._graphe_n.setdefault(c, set()).add(s)
        vus, pile = set(), [code]
        while pile:
            k = pile.pop()
            if k not in vus:
                vus.add(k)
                pile.extend(self._graphe_n.get(k, ()))
        return vus

    def _non_validees(self, periode):
        """{KPI: {organisations}} des valeurs saisies, importées ou forcées pas encore validées de la période (une requête
        par période). Comme ``avec_valeurs`` : une ancienne saisie d'un KPI devenu calculé, dans une période non figée,
        n'est pas une valeur."""
        if not hasattr(self, "_non_valides"):
            self._non_valides = {}
        if periode.pk not in self._non_valides:
            d = {}
            qs = C.Calculateur.reponses_saisies(self, periode).exclude(statut=Reponse.Statut.VALIDE)
            for kpi_id, org_id, val, texte, na, origine in qs.values_list("kpi_id", "organisation_id", "valeur", "texte",
                                                                          "non_applicable", "origine"):
                if not na and val is None and not texte:
                    continue
                k = self.kpis.get(kpi_id)
                if not self.fige_pour(periode, kpi_id) and k is not None and k.est_calcule and origine == Reponse.Origine.SAISIE:
                    continue
                d.setdefault(kpi_id, set()).add(org_id)
            self._non_valides[periode.pk] = d
        return self._non_valides[periode.pk]

    def enregistrees(self, periode):
        """Mêmes réponses enregistrées que le moteur (``Calculateur.enregistrees``), lues KPI par KPI à la première
        demande d'une de ses cases : une page de la Visualisation ne lit que quelques KPI d'une période figée, et relire
        toute la période (tous les KPI utiles et leurs sources) prenait près d'une seconde sur une grosse base."""
        if periode.pk not in self._enregistrees:
            self._enregistrees[periode.pk] = EnregistreesParKpi(self.reponses_periode(periode))
        return self._enregistrees[periode.pk]


class EnregistreesParKpi:
    """{(KPI, organisation): (origine, valeur, texte, N/A)} d'une période, comme ``Calculateur.enregistrees``, dont les
    réponses d'un KPI ne sont lues (une requête) qu'à la première demande d'une de ses cases. Au-delà de ``PAR_KPI_MAX``
    KPI demandés, tout le reste de la période est lu d'un coup (une page qui montre beaucoup de KPI : une requête de plus,
    pas une par KPI)."""

    PAR_KPI_MAX = 20
    CHAMPS = ("organisation_id", "origine", "valeur", "texte", "non_applicable")

    def __init__(self, qs):
        self.qs, self.par_kpi, self.complet = qs, {}, False

    def get(self, cle, defaut=None):
        kpi_id, org_id = cle
        if kpi_id not in self.par_kpi and not self.complet:
            if len(self.par_kpi) < self.PAR_KPI_MAX:
                self.par_kpi[kpi_id] = {o: (origine, val, texte, na)
                                        for o, origine, val, texte, na in self.qs.filter(kpi_id=kpi_id).values_list(*self.CHAMPS)}
            else:
                for k, o, origine, val, texte, na in self.qs.exclude(kpi_id__in=list(self.par_kpi)).values_list("kpi_id", *self.CHAMPS):
                    self.par_kpi.setdefault(k, {})[o] = (origine, val, texte, na)
                self.complet = True
        return self.par_kpi.get(kpi_id, {}).get(org_id, defaut)


def sources(codes):
    """Les KPI donnés et toutes les sources de leurs formules (de proche en proche)."""
    directes = {}
    for c, s in KPIFormule.objects.values_list("kpi_calcule_id", "kpi_source_id"):
        directes.setdefault(c, set()).add(s)
    vus, pile = set(), list(codes)
    while pile:
        k = pile.pop()
        if k not in vus:
            vus.add(k)
            pile.extend(directes.get(k, ()))
    return vus


@dataclass
class Point:
    """Valeur d'un KPI pour une organisation et une période, telle que la visualisation la montre."""

    valeur: object = None  # Decimal, NA, texte (oui / non, liste) ou Decompte ; None : pas de valeur à montrer
    provisoire: bool = False  # dépend d'au moins une valeur en brouillon (montrée avec « Inclure les brouillons »)
    en_attente: bool = False  # une valeur existe dans l'outil, mais pas encore validée (masquée)

    @property
    def nombre(self):
        """La valeur si c'est un nombre (ni N/A, ni réponse oui / non ou liste), sinon None."""
        return self.valeur if isinstance(self.valeur, Decimal) else None

    @property
    def na(self):
        return self.valeur is NA


def decompte(v):
    """Décompte des réponses oui / non ou liste : un Decompte, un texte « Oui : 3 · Non : 2 » (agrégat enregistré) ou
    une réponse seule (« Oui »)."""
    if isinstance(v, Counter):
        return Counter(v)
    if not isinstance(v, str) or not v:
        return Counter()
    total = Counter()
    for morceau in v.split(" · "):
        nom, _, n = morceau.rpartition(" : ")
        if nom and n.isdecimal():
            total[nom] += int(n)
        else:
            total[morceau] += 1
    return total


# réponse enregistrée telle que ``valeur_officielle`` la lit
Officielle = namedtuple("Officielle", "non_applicable texte valeur")


def valeur_officielle(r, kpi):
    if r is None:
        return None
    if r.non_applicable:
        return NA
    if not kpi.est_numerique:
        return r.texte or None
    return r.valeur


def _egales(a, b, kpi):
    if a is None or b is None:
        return False
    if a is NA or b is NA:
        return a is b
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return abs(a - b) <= Decimal("1e-8") * max(Decimal(1), abs(b))
    return decompte(a) == decompte(b)



valeurs_egales = _egales  # même comparaison pour le serveur MCP (lecteur : valeurs validées seulement)


def ecart(point, n1):
    """Écart relatif (fraction) entre deux points numériques, ou None."""
    return S.ecart(point.nombre, n1.nombre) if point and n1 else None


class Source:
    """Valeurs vues par une personne : périmètre, validées seulement (par défaut) ou brouillons compris."""

    def __init__(self, utilisateur, codes=None, brouillons=False):
        self.utilisateur, self.brouillons = utilisateur, brouillons
        self.calendrier = P.Calendrier()
        self.arbre = S.arbre_organisations()
        self.kpis = {k.code: k for k in KPI.objects.select_related("unite", "type_reponse", "type_saisie", "granularite")}
        self.codes = set(codes) if codes is not None else None
        self.calc = CalculateurValide(self.codes, calendrier=self.calendrier)
        self._officielles = {}
        self._presentes = {}
        self._demandes = {}
        self._sous = {}
        self.orgs_permises, self.paires, self.resultats = perimetre(utilisateur, self.arbre)

    # -- périmètre ---------------------------------------------------------------
    def voit(self, code, org_id):
        if self.orgs_permises is not None and org_id not in self.orgs_permises:
            return False
        if self.paires is None:
            return True
        return (code, org_id) in self.paires or org_id in self.resultats

    def organisations(self, periode=None, code=None):
        """Organisations du périmètre (dans l'ordre de l'arbre) : actives ; avec ``periode``, celles ouvertes pendant la
        période (``present`` : la règle des totaux), fermées depuis comprises. Un site fermé en 2026 compte dans les
        totaux de 2025 et figure dans ses exports : il est listé sous son parent pour 2025, sinon le total n'est plus la
        somme des lignes montrées dessous. ``code`` : dans l'arbre que suit ce KPI (un KPI figé
        par une campagne clôturée suit celui du jour où il a été figé)."""
        if self.paires is None:
            ids = set(self.arbre)
        else:
            ids = {o for _, o in self.paires} | set(self.resultats)
        if self.orgs_permises is not None:
            ids &= self.orgs_permises
        garder = (lambda i: self.arbre[i].actif) if periode is None else (lambda i: self.present(i, periode, code))
        return sorted((self.arbre[i] for i in ids if i in self.arbre and garder(i)), key=S.cle_arbre)

    def racines(self):
        """Organisations du périmètre dont le parent n'en fait pas partie : le sommet de ce que la personne voit."""
        orgs = self.organisations()
        ids = {o.id for o in orgs}
        return [o for o in orgs if o.parent_id not in ids]

    def enfants(self, org, periode=None, code=None):
        """Organisations du périmètre juste en dessous (les racines pour ``None``). Avec ``periode`` : dans l'arbre de
        cette période (``present`` : celui de sa clôture pour un exercice clos ou rouvert en gardant les chiffres de
        l'époque; avec ``code``, celui que suit ce KPI), seulement les organisations ouvertes
        pendant la période : le détail montré sous un total est celui que le total additionne."""
        if periode is None:
            if org is None:
                return self.racines()
            return [o for o in self.organisations() if o.parent_id == org.id]
        cle = ("sous", self.calc._cle(periode, code))
        if cle not in self._sous:  # lu une fois par arbre : {parent de l'époque: [organisations]}
            arbre = self.calc.orgs_de(periode, code)
            orgs = self.organisations(periode, code)
            ids, sous, racines = {o.id for o in orgs}, {}, []
            for o in orgs:
                p = arbre[o.id].parent_id
                sous.setdefault(p, []).append(o)
                if p not in ids:
                    racines.append(o)
            self._sous[cle] = (sous, racines)
        sous, racines = self._sous[cle]
        return list(racines if org is None else sous.get(org.id, []))

    def present(self, org_id, periode, code=None):
        """Vrai si l'organisation est dans l'arbre de la période et ouverte pendant celle-ci (``calcul.ouverte``, la même
        règle que les totaux) : sinon elle n'a aucun point dans cette période (pas d'anciennes valeurs d'une organisation
        pas encore ouverte, ni d'une organisation créée après la clôture d'un exercice). ``code`` : dans l'arbre que suit
        ce KPI (``calcul.Calculateur.orgs_de``)."""
        if periode is None:
            return True
        cle = (org_id, self.calc._cle(periode, code))
        if cle not in self._presentes:
            arbre = self.calc.orgs_de(periode, code)
            o = arbre.get(org_id)
            self._presentes[cle] = o is not None and C.ouverte(o, periode, arbre)
        return self._presentes[cle]

    def demande(self, code, periode):
        """Vrai si la période a une case pour ce KPI : ``calcul.perimetre_calcul``, la règle des cases écrites (KPI que
        les référentiels de ses campagnes y demandent, « demandé depuis » compris, borné par le périmètre gelé d'un
        exercice clos ou rouvert, ``calcul.perimetre_gele``). Hors de ce périmètre, aucun point : un KPI pas demandé dans
        un exercice n'y apparaît ni en ligne d'un tableau ni en « Incomplet » (la Consolidation
        montrait une colonne pour un KPI demandé depuis l'exercice suivant). Lu une fois par période."""
        if periode is None:
            return True
        if periode.pk not in self._demandes:
            self._demandes[periode.pk] = C.perimetre_calcul(periode)
        codes = self._demandes[periode.pk]
        return codes is None or code in codes

    # -- valeurs -------------------------------------------------------------------
    def officielles(self, periode):
        """{(KPI, organisation): réponse enregistrée} de la période, réduite à ce que lit ``valeur_officielle`` (N/A,
        texte, valeur) : lire chaque réponse en objet complet prenait plusieurs secondes sur une grosse base."""
        if periode.pk not in self._officielles:
            qs = Reponse.objects.filter(periode=periode)
            if self.codes is not None:
                qs = qs.filter(kpi_id__in=self.codes)
            self._officielles[periode.pk] = {(k, o): Officielle(na, texte, v) for k, o, na, texte, v in qs.values_list(
                "kpi_id", "organisation_id", "non_applicable", "texte", "valeur")}
        return self._officielles[periode.pk]

    def point(self, code, org, periode):
        """Point du KPI pour l'organisation et la période ; None hors du périmètre ou sans période."""
        if periode is None or org is None or not self.voit(code, org.id) or not self.present(org.id, periode, code) \
                or not self.demande(code, periode):
            return None
        kpi = self.kpis[code]
        valide = self.calc.valeur(code, org.id, periode)
        if not self.brouillons and valide is not None:
            return Point(valide)  # la valeur enregistrée n'est pas lue : elle ne change rien au point
        officielle = valeur_officielle(self.officielles(periode).get((code, org.id)), kpi)
        if not self.brouillons:
            return Point(en_attente=officielle is not None)
        if officielle is None:
            return Point(valide)
        return Point(officielle, provisoire=not _egales(valide, officielle, kpi))

    def n1(self, periode):
        return self.calendrier.meme_n1(periode) if periode else None

    def perimetre_change(self, org, periode, prec):
        """Vrai si les organisations comptées sous ``org`` (elle comprise ; ouvertes pendant la période, dans l'arbre de
        chaque période : ``calcul.ouverte``, ``orgs_de``) ne sont pas les mêmes dans ``periode`` et ``prec`` : un total
        sans une organisation comparé à un total avec elle (constaté « +54 % » sur une démo). Seulement dit sur la
        comparaison (« périmètres différents », à confirmer) : les totaux ne
        changent pas."""
        if org is None or periode is None or prec is None:
            return False
        return self._comptees(org.id, periode) != self._comptees(org.id, prec)

    def _comptees(self, org_id, periode):
        cle = ("comptees", org_id, periode.pk)
        if cle not in self._sous:
            arbre = self.calc.orgs_de(periode)
            enfants = self._sous.get(("enfants", periode.pk))
            if enfants is None:
                enfants = self._sous[("enfants", periode.pk)] = {}
                for o in arbre.values():
                    enfants.setdefault(o.parent_id, []).append(o.id)
            vues, pile = set(), [org_id]
            while pile:
                x = pile.pop()
                if x in vues or x not in arbre or not C.ouverte(arbre[x], periode, arbre):
                    continue
                vues.add(x)
                pile.extend(enfants.get(x, ()))
            self._sous[cle] = frozenset(vues)
        return self._sous[cle]

    def serie(self, code, org, periode, nombre=None):
        """[(période, Point)] des périodes du même type, de la plus ancienne à ``periode`` (celles qui existent)."""
        if periode is None:
            return []
        nombre = nombre or NB_EVOLUTION.get(periode.type, 6)
        pas = 12 // {Frequence.ANNEE: 1, Frequence.SEMESTRE: 2, Frequence.TRIMESTRE: 4, Frequence.MOIS: 12}[periode.type]
        sortie = []
        for i in range(nombre - 1, -1, -1):
            q = self.calendrier.decalee(periode, -pas * i) if i else periode
            if q is not None:
                sortie.append((q, self.point(code, org, q)))
        while sortie and (sortie[0][1] is None or sortie[0][1].valeur is None and not sortie[0][1].en_attente):
            sortie.pop(0)  # rien avant le début de l'historique
        return sortie

    def existe_a(self, code, org):
        """Vrai si le KPI a une valeur possible au niveau de l'organisation : au niveau de sa granularité ou au-dessus
        (rang inférieur ou égal), ou partout pour un paramètre hérité."""
        kpi = self.kpis.get(code)
        if kpi is None:
            return False
        if kpi.est_herite:
            return True
        rang_kpi = kpi.granularite.rang if kpi.granularite_id else None
        rang_org = org.niveau.rang if org.niveau_id else None
        return rang_kpi is None or rang_org is None or rang_org <= rang_kpi

    def descendantes(self, org, periode=None, code=None):
        """Organisations actives du périmètre sous ``org`` (toutes profondeurs ; tout le périmètre pour ``None``). Avec
        ``periode`` : dans l'arbre de cette période (ou que suit le KPI ``code``), ouvertes pendant celle-ci (voir
        ``enfants``)."""
        orgs = self.organisations(periode, code)
        if org is None:
            return orgs
        arbre = self.calc.orgs_de(periode, code) if periode is not None else self.arbre
        sortie = []
        for o in orgs:
            p, vus = arbre.get(arbre[o.id].parent_id), {o.id}
            while p is not None and p.id != org.id and p.id not in vus:
                vus.add(p.id)
                p = arbre.get(p.parent_id)
            if p is not None and p.id == org.id:
                sortie.append(o)
        return sortie

    def organisations_comparees(self, code, org, mode="dessous", niveau=None, ids=None, periode=None, arbre_de=None):
        """Organisations à comparer pour un KPI : celles juste en dessous de ``org`` (``mode="dessous"``), tout un
        niveau sous ``org`` (``"niveau"``, code du niveau) ou des organisations choisies (``"choisies"``, ``ids``).
        Seulement les organisations actives du périmètre, à un niveau où le KPI existe (correctif : un KPI saisi au
        niveau Groupe n'a rien à comparer en dessous). Avec ``periode`` : de la plus grande valeur à la plus petite,
        celles sans valeur à la fin, puis dans l'ordre de l'arbre ; sinon dans l'ordre de l'arbre. Les organisations du
        dessous sont celles de l'arbre de la période (``periode``, ou ``arbre_de`` sans tri) : celui de sa clôture pour un
        exercice clos ou rouvert en gardant les chiffres de l'époque."""
        tree = periode or arbre_de
        if mode == "niveau" and niveau:
            orgs = [o for o in self.descendantes(org, tree, code) if o.niveau_id == niveau]
        elif mode == "choisies":
            voulues = {int(i) for i in (ids or []) if str(i).isdecimal()}
            orgs = [o for o in self.organisations() if o.id in voulues]
        else:
            orgs = self.enfants(org, tree, code)
        orgs = [o for o in orgs if self.existe_a(code, o) and self.voit(code, o.id)]
        if periode is None:
            return orgs
        points = {o.id: self.point(code, o, periode) for o in orgs}
        return sorted(orgs, key=lambda o: (points[o.id] is None or points[o.id].nombre is None,
                                           -(points[o.id].nombre or 0) if points[o.id] else 0, S.cle_arbre(o)))

    def comparaison(self, code, org, periode, prec=False, mode="dessous", niveau=None, ids=None):
        """[(organisation, Point, Point de comparaison)] des organisations comparées (juste en dessous par défaut), de la
        plus grande valeur à la plus petite (celles sans valeur à la fin). ``prec`` : période de comparaison (N-1 par
        défaut ; None : aucune)."""
        prec = self.n1(periode) if prec is False else prec
        lignes = []
        for o in self.organisations_comparees(code, org, mode, niveau, ids, periode):
            p = self.point(code, o, periode)
            if p is None:
                continue
            lignes.append((o, p, self.point(code, o, prec) if prec else None))
        return lignes

    def repartition(self, code, org, periode):
        """Parts d'un total : [(libellé, valeur, part, organisation ou None)] et le total ; [] si le KPI ne s'y prête pas.
        Somme : la part de chaque organisation juste en dessous (les plus grandes, puis « Autres »). Oui / non, liste :
        le nombre d'organisations de chaque réponse."""
        kpi = self.kpis[code]
        if not kpi.est_numerique:
            p = self.point(code, org, periode)
            compte = decompte(p.valeur) if p and p.valeur is not None and not p.na else Counter()
            if not compte:
                return [], None
            ordre = [c for c in kpi.choix if compte.get(c)] + sorted(c for c in compte if c not in kpi.choix)
            total = sum(compte.values())
            parts = [(kpi.reponse_affichee(c), Decimal(compte[c]), Decimal(compte[c]) / total, None) for c in ordre]
            if len(parts) > 8:  # 8 couleurs au plus, jamais recyclées : le reste dans « Autres réponses »
                reste = sum((v for _, v, _, _ in parts[7:]), Decimal(0))
                parts = parts[:7] + [(libelle("visu.visuel.autres_reponses", n=len(parts) - 7), reste, reste / total, None)]
            return parts, Decimal(total)
        if kpi.est_pourcentage or kpi.methode_agregation != KPI.Agregation.SOMME:
            return [], None
        lignes = [(o, p.nombre) for o, p, _ in self.comparaison(code, org, periode, prec=None) if p.nombre is not None and p.nombre > 0]
        total = sum((v for _, v in lignes), Decimal(0))
        if not lignes or total <= 0:
            return [], None
        parts = [(str(o), v, v / total, o) for o, v in lignes[:NB_REPARTITION]]
        reste = sum((v for _, v in lignes[NB_REPARTITION:]), Decimal(0))
        if reste:
            n = len(lignes) - NB_REPARTITION
            parts.append((libelle("visu.visuel.autres", n=n), reste, reste / total, None))
        return parts, total


def perimetre(utilisateur, arbre):
    """(organisations permises ou None, cases visibles ou None, organisations dont on voit les résultats)."""
    if utilisateur.lecture_seule:
        return utilisateur.orgs_permises(), None, set()
    paires, resultats = E.perimetre(utilisateur, arbre)
    return None, paires, resultats or set()


# ---------------------------------------------------------------- périodes proposées
def periodes(calendrier=None, referentiel=None):
    """Périodes qui ont une campagne (d'un référentiel actif, ou du référentiel donné), de la plus récente à la plus
    ancienne (années d'abord, à fin égale), avec l'année qui contient chacune (ses valeurs s'y cumulent)."""
    calendrier = calendrier or P.Calendrier()
    vues = {}
    qs = Campagne.objects.select_related("periode", "referentiel").filter(referentiel__actif=True)
    if referentiel is not None:
        qs = qs.filter(referentiel=referentiel)
    for c in qs:
        vues[c.periode.pk] = c.periode
        annee = (calendrier.trouver(Frequence.ANNEE, datetime.date(c.exercice, c.referentiel.mois_debut, 1))
                 if c.periode.type != Frequence.ANNEE else None)
        if annee is not None:
            vues.setdefault(annee.pk, annee)  # l'année qui contient la période (valeurs cumulées)
    return sorted(vues.values(), key=lambda p: (-p.fin.toordinal(), P.RANG[p.type] * -1))


def periode_par_defaut(liste):
    """L'année la plus récente dont la campagne est en revue ou clôturée (chiffres complets) ; sinon la période la
    plus récente ainsi finie (le dernier mois clos d'un référentiel mensuel) ; sinon la plus récente."""
    finies = set(Campagne.objects.filter(statut__in=[Campagne.Statut.REVUE, Campagne.Statut.CLOTUREE])
                 .values_list("periode_id", flat=True))
    return (next((p for p in liste if p.type == Frequence.ANNEE and p.pk in finies), None)
            or next((p for p in liste if p.pk in finies), None) or (liste or [None])[0])
