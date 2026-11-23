"""Starting state of the fictitious group: tree, frameworks, KPIs, accounts, assignments.

This is the only part of the scenario that writes directly in the database (the brief allows it for the starting tree).
Everything that happens afterwards goes through the pages of the tool (``actors.py``).

Fictitious data only: invented names, e-mails @exemple.test, values drawn from a fixed seed.
"""
# Commentaires en anglais, comme le reste de qa/ (outil de recette).
import random
from dataclasses import dataclass, field

from parametres import niveaux as N
from parametres.models import Instance, TypeReponse
from parametres.referentiel import unite_depuis_symbole as U
from referentiel.composition import placer, theme_par_chemin
from referentiel.models import KPI, Attribution, Niveau, Organisation, Referentiel, Utilisateur

PASSWORD = "Group-life-2026"

SIZES = {
    # countries, entities per country, sites per entity (min, max)
    "micro": (2, 1, (2, 2)),  # the version of the test suite
    "tiny": (2, 2, (2, 2)),
    "small": (3, 3, (3, 5)),
    "large": (8, 6, (8, 12)),
}
COUNTRIES = ["Atlantis", "Borduria", "Carpania", "Daralia", "Elbonia", "Freedonia", "Genovia", "Hesperia", "Illyria",
             "Jotunia"]

ANNUAL = "GROUPREP"  # annual framework
MONTHLY = "ENERGY"  # monthly framework, switched on in year 2
YEARS = (2023, 2024, 2025)

# code, name, input type, unit, level, aggregation, formula, answer type, evidence required
KPIS = [
    ("ELEC", "Electricity consumed", "Saisi", "kWh", Niveau.SITE, "Somme", "", "Numérique", True),
    ("GAS", "Natural gas consumed", "Saisi", "kWh", Niveau.SITE, "Somme", "", "Numérique", False),
    ("WATER", "Water consumed", "Saisi", "m³", Niveau.SITE, "Somme", "", "Numérique", False),
    ("WASTE", "Waste produced", "Saisi", "t", Niveau.SITE, "Somme", "", "Numérique", False),
    ("ACC", "Lost-time accidents", "Saisi", "accidents", Niveau.SITE, "Somme", "", "Numérique", False),
    ("CERT", "ISO 14001 certified site", "Saisi", "", Niveau.SITE, "Décompte", "", "GL-YESNO", False),
    ("WTAB", "Waste by type", "Saisi", "", Niveau.SITE, "Aucune", "", "GL-WASTETAB", False),
    ("FE", "Electricity emission factor", "FE", "kgCO2eq/kWh", Niveau.GROUP, "Aucune", "", "Numérique", False),
    ("CO2", "Emissions from electricity", "Calculé", "kgCO2eq", Niveau.SITE, "Somme", "[ELEC] * [FE]", "Numérique", False),
    ("EVOL", "Change in electricity on N-1", "Calculé", "", Niveau.SITE, "Formule", "([ELEC] - [ELEC@N-1]) / [ELEC@N-1]",
     "Pourcentage", False),
    ("HEAD", "Headcount at year end", "Saisi", "employees", Niveau.ENTITY, "Somme", "", "Numérique", False),
    ("WOMEN", "Women at year end", "Saisi", "employees", Niveau.ENTITY, "Somme", "", "Numérique", False),
    ("PCTW", "Share of women", "Calculé", "", Niveau.ENTITY, "Formule", "[WOMEN] / [HEAD]", "Pourcentage", False),
    ("TRAIN", "Training hours", "Saisi", "h", Niveau.ENTITY, "Somme", "", "Numérique", False),
    ("REV", "Revenue", "Saisi", "M€", Niveau.GROUP, "Aucune", "", "Numérique", False),
    ("INTENS", "Carbon intensity", "Calculé", "kgCO2eq/M€", Niveau.GROUP, "Aucune", "[CO2] / [REV]", "Numérique", False),
]
THEMES = {"ELEC": ["Environment", "Energy"], "GAS": ["Environment", "Energy"], "WATER": ["Environment", "Water and waste"],
          "WASTE": ["Environment", "Water and waste"], "WTAB": ["Environment", "Water and waste"], "ACC": ["Social", "Safety"],
          "CERT": ["Environment"], "FE": ["Environment", "Energy"], "CO2": ["Environment", "Energy"], "EVOL": ["Environment", "Energy"], "HEAD": ["Social", "Headcount"],
          "WOMEN": ["Social", "Headcount"], "PCTW": ["Social", "Headcount"], "TRAIN": ["Social", "Training"],
          "REV": ["Economy"], "INTENS": ["Economy"]}
MONTHLY_KPIS = ["ELEC", "GAS"]
UNITS = [("kWh", "kWh", "kilowatt-hour", False, 0, "Energy"), ("m³", "m³", "cubic metre", False, 0, "Volume"),
         ("t", "t", "tonne", False, 1, "Mass"), ("accidents", "accidents", "accidents", True, 0, "Count"),
         ("kgCO2eq", "kgCO2eq", "kg CO2 equivalent", False, 0, "Emissions"),
         ("kgCO2eq/kWh", "kgCO2eq/kWh", "emission factor", False, 3, "Emissions"),
         ("employees", "employees", "employees", True, 0, "Headcount"), ("h", "h", "hour", False, 0, "Time"),
         ("M€", "M€", "million euros", False, 1, "Money"), ("kgCO2eq/M€", "kgCO2eq/M€", "carbon intensity", False, 1, "Emissions")]


@dataclass
class World:
    """What the scenario needs to know about the starting state (ids and names, never objects kept across requests)."""
    size: str
    seed: int
    prefix: str = "gl-"
    sites: list = field(default_factory=list)  # organisation ids, lowest level
    entities: list = field(default_factory=list)
    countries: list = field(default_factory=list)
    group: int = 0
    contributor_of: dict = field(default_factory=dict)  # entity id -> username
    validator_of: dict = field(default_factory=dict)  # country id -> username
    users: dict = field(default_factory=dict)  # username -> role

    def rng(self, *salt):
        return random.Random(f"{self.seed}:{':'.join(map(str, salt))}")


def _types_and_units():
    from collecte.management.commands import _demo_commun as DC

    DC.unites_et_types(UNITS, [("GL-YESNO", "Yes / no", "oui_non", [])])
    TypeReponse.objects.update_or_create(code="GL-WASTETYPE", defaults=dict(
        libelle="Waste type", format="liste", valeurs=["Paper", "Plastic", "Metal", "Other"], ordre=20))
    TypeReponse.objects.update_or_create(code="GL-WASTETAB", defaults=dict(
        libelle="Waste table", format="tableau", ordre=21, colonnes=[
            {"code": "type", "libelle": {"fr": "Type", "en": "Type"}, "type": "liste", "liste": "GL-WASTETYPE"},
            {"code": "mass", "libelle": {"fr": "Masse", "en": "Mass"}, "type": "nombre", "unite": "t"},
            {"code": "note", "libelle": {"fr": "Note", "en": "Note"}, "type": "texte"}]))


def _kpis():
    for order, (code, name, typ, unit, level, agg, formula, answer, evidence) in enumerate(KPIS, start=1):
        KPI.objects.update_or_create(code=code, defaults=dict(
            libelle=name, type_saisie_id=typ, unite=U(unit) if unit else None, granularite_id=level, methode_agregation=agg,
            formule=formula, type_reponse_id=answer, preuve_obligatoire=evidence, ordre=order,
            decimales=1 if answer == "Pourcentage" else (U(unit).decimales if unit else 0)))


def _frameworks():
    annual, _ = Referentiel.objects.update_or_create(code=ANNUAL, defaults=dict(
        nom="Group annual report", frequence="annee", comparaison="N-1", ordre=1, actif=True))
    monthly, _ = Referentiel.objects.update_or_create(code=MONTHLY, defaults=dict(
        nom="Monthly energy", frequence="mois", comparaison="N-1", ordre=2, actif=False))
    cache = {}
    for order, (code, *_rest) in enumerate(KPIS, start=1):
        placer(KPI.objects.get(pk=code), annual, theme_par_chemin(annual, THEMES[code], cache), order)
    for order, code in enumerate(MONTHLY_KPIS, start=1):
        placer(KPI.objects.get(pk=code), monthly, theme_par_chemin(monthly, ["Energy"], cache), order)
    Referentiel.objects.exclude(code__in=[ANNUAL, MONTHLY]).delete()


def _account(username, role, first, last):
    u = Utilisateur(username=username, email=f"{username}@exemple.test", role=role, first_name=first, last_name=last)
    u.is_staff = u.is_superuser = role == Utilisateur.Role.ADMIN
    u.set_password(PASSWORD)
    u.save()
    return u


def build(size="small", seed=1, prefix="gl-", group_name="Fictitious Group"):
    """Builds the starting state in the current space (empty database). Returns a ``World``. ``prefix``: start of the
    user names (accounts are shared by the spaces of an installation: another prefix for a second space)."""
    countries_n, entities_n, (smin, smax) = SIZES[size]
    w = World(size=size, seed=seed, prefix=prefix)
    R = w.rng("tree")
    N.creer_par_defaut()
    inst = Instance.courante()
    inst.nom, inst.mise_en_place_terminee = "Fictitious group", True
    inst.save()
    _types_and_units()
    _kpis()
    _frameworks()
    g = Organisation.objects.create(nom=group_name, niveau_id=Niveau.GROUP)
    w.group = g.pk
    accounts = {f"{prefix}admin": (Utilisateur.Role.ADMIN, "Ada", "Admin"), f"{prefix}reader": (Utilisateur.Role.LECTEUR, "Rita", "Reader"),
                f"{prefix}auditor": (Utilisateur.Role.AUDITEUR, "Otto", "Auditor"),
                f"{prefix}group": (Utilisateur.Role.CONTRIBUTEUR, "Gus", "Group")}
    users = {name: _account(name, *spec) for name, spec in accounts.items()}
    links = []
    for ci in range(countries_n):
        c = Organisation.objects.create(nom=f"{prefix}{COUNTRIES[ci]}", niveau_id=Niveau.COUNTRY, parent=g, rang=ci)
        w.countries.append(c.pk)
        vname = f"{prefix}val-{ci + 1}"
        users[vname] = _account(vname, Utilisateur.Role.VALIDATEUR, "Val", COUNTRIES[ci])
        w.validator_of[c.pk] = vname
        for ei in range(entities_n):
            e = Organisation.objects.create(nom=f"{prefix}{COUNTRIES[ci]} Entity {ei + 1}", niveau_id=Niveau.ENTITY, parent=c, rang=ei)
            w.entities.append(e.pk)
            cname = f"{prefix}con-{ci + 1}-{ei + 1}"
            users[cname] = _account(cname, Utilisateur.Role.CONTRIBUTEUR, "Con", f"{COUNTRIES[ci]} {ei + 1}")
            w.contributor_of[e.pk] = cname
            for si in range(R.randint(smin, smax)):
                s = Organisation.objects.create(nom=f"{prefix}{COUNTRIES[ci]} {ei + 1} Site {si + 1:02d}", niveau_id=Niveau.SITE,
                                                parent=e, rang=si, type_site="autre")
                w.sites.append(s.pk)
    kpis = {k.code: k for k in KPI.objects.all()}
    orgs = {o.pk: o for o in Organisation.objects.all()}
    for e_id, cname in w.contributor_of.items():
        u = users[cname]
        for code, k in kpis.items():
            if k.est_calcule:
                continue
            if k.granularite_id == Niveau.SITE:
                for s in orgs[e_id].enfants.all():
                    links.append(Attribution(kpi=k, organisation=s, utilisateur=u))
            elif k.granularite_id == Niveau.ENTITY:
                links.append(Attribution(kpi=k, organisation=orgs[e_id], utilisateur=u))
    for code in ("FE", "REV"):
        links.append(Attribution(kpi=kpis[code], organisation=g, utilisateur=users[f"{prefix}group"]))
    for c_id, vname in w.validator_of.items():
        for code, k in kpis.items():
            if not k.est_calcule and k.granularite_id != Niveau.GROUP:
                links.append(Attribution(kpi=k, organisation=orgs[c_id], utilisateur=users[vname], role=Attribution.Role.VALIDATEUR))
    Attribution.objects.bulk_create(links, ignore_conflicts=True)
    w.users = {name: u.role for name, u in users.items()}
    return w
