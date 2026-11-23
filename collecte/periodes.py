"""Périodes de collecte : calendrier commun (années, semestres, trimestres, mois), libellés et décalages.

Une période se définit par son type et sa date de début ; la fin s'en déduit. Les années, semestres et trimestres
partent du mois de début d'exercice du référentiel ; les mois sont ceux du calendrier. Une même période sert à tous les
référentiels de cette fréquence.

Décalages des formules : [ID@P-1] = période précédente du même type, [ID@N-1] = même période douze mois plus tôt,
[ID@2021] = même période (même rang dans l'exercice) de l'exercice qui commence en 2021 : avec
un exercice de juillet à juin, février 2023 (exercice 2022/23) avec [ID@2021] lit février 2022 (exercice 2021/22).
Pour un exercice de janvier, c'est l'année civile, comme avant.
"""
import datetime
import re
import unicodedata

from referentiel.models import MOIS_PAR_FREQUENCE, Frequence

RANG = {Frequence.MOIS: 1, Frequence.TRIMESTRE: 2, Frequence.SEMESTRE: 3, Frequence.ANNEE: 4}  # plus petit = plus fin
MOIS = {
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"],
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"],
    "pt": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"],
    "nl": ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december"],
}
PREFIXES = {Frequence.TRIMESTRE: {"fr": "T", "es": "T", "it": "T", "pt": "T", "nl": "K"},  # sinon « Q »
            Frequence.SEMESTRE: {"fr": "S", "es": "S", "it": "S", "pt": "S"}}  # sinon « H »


# ---------------------------------------------------------------- dates
def ajouter_mois(d, n):
    """Premier jour du mois, ``n`` mois après (ou avant) celui de ``d``."""
    a, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return datetime.date(a, m + 1, 1)


def fin_de(type_, debut):
    return ajouter_mois(debut, MOIS_PAR_FREQUENCE[type_]) - datetime.timedelta(days=1)


def exercice_de(debut, mois_debut=1):
    """Exercice (année où il commence) qui contient la date."""
    return debut.year if debut.month >= mois_debut else debut.year - 1


def debuts(type_, exercice, mois_debut=1):
    """Débuts des périodes d'un type dans un exercice (12 mois, 4 trimestres…)."""
    n = MOIS_PAR_FREQUENCE[type_]
    return [ajouter_mois(datetime.date(exercice, mois_debut, 1), i * n) for i in range(12 // n)]


def rang_dans_exercice(type_, debut, mois_debut=1):
    """1 pour le premier trimestre (semestre, mois) de l'exercice."""
    ex = exercice_de(debut, mois_debut)
    return (debut.year * 12 + debut.month - ex * 12 - mois_debut) // MOIS_PAR_FREQUENCE[type_] + 1


def libelle(type_, debut, mois_debut=1, langue="fr"):
    """« 2026 » (ou « 2026/27 » si l'exercice ne commence pas en janvier), « S1 2026 », « T1 2026 », « mars 2026 »."""
    if type_ == Frequence.MOIS:
        return f"{MOIS.get(langue, MOIS['en'])[debut.month - 1]} {debut.year}"
    ex = exercice_de(debut, mois_debut)
    an = str(ex) if mois_debut == 1 else f"{ex}/{str(ex + 1)[-2:]}"
    if type_ == Frequence.ANNEE:
        return an
    prefixe = PREFIXES[type_].get(langue, "Q" if type_ == Frequence.TRIMESTRE else "H")
    return f"{prefixe}{rang_dans_exercice(type_, debut, mois_debut)} {an}"


# ---------------------------------------------------------------- périodes en base
def obtenir(type_, debut, mois_debut=1):
    """La période (créée au besoin, avec son libellé dans la langue de référence et ses traductions)."""
    from parametres import langues as L

    from .models import Periode

    debut = debut.replace(day=1)
    p = Periode.objects.filter(type=type_, debut=debut).first()
    if p is None:
        ref = L.reference()
        p = Periode(type=type_, debut=debut, fin=fin_de(type_, debut), libelle=libelle(type_, debut, mois_debut, ref))
        for lg in L.codes_actifs():
            t = libelle(type_, debut, mois_debut, lg)
            if lg != ref and t != p.libelle:
                p.traductions.setdefault(lg, {})["libelle"] = t
        p.save()
    return p


def annuelle(exercice, mois_debut=1):
    return obtenir(Frequence.ANNEE, datetime.date(exercice, mois_debut, 1), mois_debut)


class Calendrier:
    """Périodes existantes, lues une fois : retrouver une période décalée sans requête."""

    def __init__(self):
        from .models import Periode

        self.par_cle = {(p.type, p.debut): p for p in Periode.objects.all()}
        self._mois = None  # mois de début d'exercice des référentiels, lus à la première demande

    def _lire_mois(self):
        from referentiel.models import Referentiel

        from .models import Campagne

        par_periode, par_frequence = {}, {}
        for pid, m in (Campagne.objects.order_by("referentiel__ordre", "referentiel_id")
                       .values_list("periode_id", "referentiel__mois_debut")):
            par_periode.setdefault(pid, []).append(m)
        for f, m in Referentiel.objects.order_by("-actif", "ordre", "pk").values_list("frequence", "mois_debut"):
            par_frequence.setdefault(f, []).append(m)
        self._mois = par_periode, par_frequence

    def mois_debut(self, p):
        """Mois de début de l'exercice auquel appartient la période : celui d'une année est son mois ; pour une période
        plus courte, celui des référentiels de ses campagnes (le premier dans l'ordre des référentiels), sinon celui des
        référentiels de sa fréquence, s'il tombe juste (un trimestre d'avril ne peut pas être celui d'un exercice de
        février) ; à défaut, janvier (ou le premier mois aligné)."""
        if p.type == Frequence.ANNEE:
            return p.debut.month
        if self._mois is None:
            self._lire_mois()
        n = MOIS_PAR_FREQUENCE[p.type]
        par_periode, par_frequence = self._mois
        for m in par_periode.get(getattr(p, "pk", None), []) + par_frequence.get(p.type, []):
            if (p.debut.month - m) % n == 0:
                return m
        return (p.debut.month - 1) % n + 1

    def exercice(self, p):
        """Exercice de la période (année où il commence) : 2022 pour février 2023 dans un exercice de juillet."""
        return exercice_de(p.debut, self.mois_debut(p))

    def trouver(self, type_, debut):
        return self.par_cle.get((type_, debut))

    def decalee(self, p, mois):
        return self.trouver(p.type, ajouter_mois(p.debut, mois))

    def precedente(self, p):
        return self.decalee(p, -MOIS_PAR_FREQUENCE[p.type])

    def suivante(self, p):
        return self.decalee(p, MOIS_PAR_FREQUENCE[p.type])

    def meme_n1(self, p):
        return self.decalee(p, -12)

    def cible(self, p, decalage):
        """(type, début) de la période visée par un décalage de formule : « N », « N-1 », « P-1 » ou une année
        (l'exercice qui commence cette année-là)."""
        if decalage == "N":
            return p.type, p.debut
        mois = {"N-1": -12, "P-1": -MOIS_PAR_FREQUENCE[p.type]}.get(decalage)
        if mois is None:  # [ID@2021] : même rang dans l'exercice qui commence en 2021
            mois = 12 * (int(decalage) - self.exercice(p))
        return p.type, ajouter_mois(p.debut, mois)

    def resoudre(self, p, decalage):
        """Période visée par un décalage de formule (None si elle n'existe pas)."""
        if decalage == "N":
            return p
        try:
            return self.trouver(*self.cible(p, decalage))
        except (ValueError, OverflowError):  # année hors du calendrier (formule ancienne) : la période n'existe pas
            return None

    def libelle_cible(self, p, decalage):
        """Libellé de la période visée, même si elle n'existe pas (« 2020 », « février 2026 »)."""
        q = self.resoudre(p, decalage)
        if q is not None:
            return str(q)
        try:
            return libelle(*self.cible(p, decalage), self.mois_debut(p))
        except (ValueError, OverflowError):  # année hors du calendrier
            return str(decalage)

    def contenues(self, p, type_):
        """Débuts des périodes du type ``type_`` qui composent ``p`` (ex. les 12 mois d'une année)."""
        n = MOIS_PAR_FREQUENCE[type_]
        return [ajouter_mois(p.debut, i * n) for i in range(MOIS_PAR_FREQUENCE[p.type] // n)]

    def englobantes(self, p):
        """Périodes plus longues existantes qui contiennent ``p`` (le trimestre, l'année…)."""
        return [q for q in self.par_cle.values() if RANG[q.type] > RANG[p.type] and q.debut <= p.debut and q.fin >= p.fin]

    def precedentes(self, p, nombre):
        """Mêmes périodes des ``nombre`` années précédentes qui existent (historique)."""
        return [q for q in (self.decalee(p, -12 * i) for i in range(1, nombre + 1)) if q is not None]


def plus_fine(a, b):
    """Vrai si la fréquence ``a`` est plus fine que ``b`` (mois < trimestre < semestre < année)."""
    return RANG[a] < RANG[b]


# ---------------------------------------------------------------- lecture d'une période écrite dans un fichier
def _norm(t):
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


NOMS_MOIS = {_norm(n): i + 1 for noms in MOIS.values() for i, n in enumerate(noms)}
NOMS_MOIS.update({_norm(n)[:3]: i + 1 for noms in MOIS.values() for i, n in enumerate(noms)})


def lire(valeur, mois_debut=1):
    """(type, début) d'une période écrite dans une cellule : « 2026 », « 2026/27 », « S1 2026 », « T2 2026 », « Q2 2026 »,
    « mars 2026 », « March 2026 », « 03/2026 », « 2026-03 » ou une date (son mois). None si illisible.

    Une période déjà en base est reconnue par son libellé, dans toutes les langues."""
    from .models import Periode

    if isinstance(valeur, datetime.datetime):
        valeur = valeur.date()
    if isinstance(valeur, datetime.date):
        return Frequence.MOIS, valeur.replace(day=1)
    if isinstance(valeur, (int, float)) and 1900 < int(valeur) < 3000:
        valeur = str(int(valeur))
    t = _norm(valeur or "")
    if not t:
        return None
    for p in Periode.objects.all():
        if t in {_norm(p.libelle)} | {_norm(v.get("libelle", "")) for v in (p.traductions or {}).values()}:
            return p.type, p.debut
    m = re.fullmatch(r"(?:exercice |year |fy ?)?(\d{4})(?:[/-](\d{2}))?", t)
    if m:
        an, suite = int(m.group(1)), m.group(2)
        if suite and int(suite) != (an + 1) % 100 and 1 <= int(suite) <= 12:
            return Frequence.MOIS, datetime.date(an, int(suite), 1)  # 2026-03
        return Frequence.ANNEE, datetime.date(an, mois_debut, 1)  # 2026, 2026/27
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{4})", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return Frequence.MOIS, datetime.date(int(m.group(2)), int(m.group(1)), 1)
    m = re.fullmatch(r"([tqk])([1-4]) (\d{4})", t)
    if m:
        return Frequence.TRIMESTRE, ajouter_mois(datetime.date(int(m.group(3)), mois_debut, 1), 3 * (int(m.group(2)) - 1))
    m = re.fullmatch(r"([sh])([12]) (\d{4})", t)
    if m:
        return Frequence.SEMESTRE, ajouter_mois(datetime.date(int(m.group(3)), mois_debut, 1), 6 * (int(m.group(2)) - 1))
    m = re.fullmatch(r"([a-z]+)\.? (\d{4})", t)
    if m and m.group(1) in NOMS_MOIS:
        return Frequence.MOIS, datetime.date(int(m.group(2)), NOMS_MOIS[m.group(1)], 1)
    return None



# ---------------------------------------------------------------- campagnes
def campagne(referentiel, debut, **defaults):
    """Campagne du référentiel pour la période qui commence à ``debut`` (créée au besoin, avec ``defaults``).
    Renvoie (campagne, créée)."""
    from .models import Campagne

    p = obtenir(referentiel.frequence, debut, referentiel.mois_debut)
    return Campagne.objects.get_or_create(referentiel=referentiel, periode=p, defaults={
        "exercice": exercice_de(p.debut, referentiel.mois_debut), **defaults})


def campagne_annuelle(exercice, referentiel=None, **defaults):
    """Campagne d'un exercice pour un référentiel annuel (par défaut le premier référentiel annuel actif, créé au besoin).
    Renvoie (campagne, créée)."""
    from referentiel.composition import referentiel_par_defaut
    from referentiel.models import Referentiel

    if referentiel is None:
        referentiel = (Referentiel.objects.filter(actif=True, frequence=Frequence.ANNEE).first()
                       or referentiel_par_defaut())
    return campagne(referentiel, datetime.date(exercice, referentiel.mois_debut, 1), **defaults)

