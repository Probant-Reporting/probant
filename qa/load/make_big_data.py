"""Build a large fictitious database, to measure the pages and actions at the size of a big group.

    DATA_DIR=/folder/big python3 qa/load/make_big_data.py [--sites 600] [--journal-rows 1200000] [--months 22] [--seed 1]
        [--only setup|answers|journal]

Generic: it depends on no client. It starts from an EMPTY database (never from a real installation) and builds,
mostly by bulk insertion, a fictitious group "Grandgroupe":

  organisations   1 group, 12 countries, about 66 subsidiaries, --sites sites (600 by default: about 680 in all, 4 levels
                  Group > Country > Entity > Site); a few sites closed in 2024, a few closed during 2026
  accounts        the 5 demo accounts (admin, validateur, contributeur, lecteur, auditeur, password "demo-probant-2026") and
                  195 generated: contrib000-149, valid000-029, lect000-009 (some limited to one country), audit000-004,
                  adm000-004; all written in the registry of the spaces (espaces.comptes.reconcilier)
  assignments     one contributor for 4 sites, one contributor per subsidiary, one validator per country (valid000-011),
                  other validators on subsidiaries; a few cells without a contributor
  annual          framework "GROUPE" of about 320 KPIs: inputs at site and subsidiary level (numbers, yes / no, lists,
                  optional ones), emission factors at group level (inherited), about 80 calculated KPIs (a headcount cited
                  by 30 ratios, factors cited by 20 emissions, changes on N-1), 10 KPIs outside any framework, 5 inactive;
                  campaigns 2023, 2024, 2025 closed (everything validated) and 2026 open (about half entered)
  monthly         framework "MENSUEL" of 40 site KPIs, --months months from January 2025, the last month open
  alerts          consistency check of 2025 (accepted) and of the open campaigns (some justified), 2 rules between KPIs
  evidence        Preuve records on validated answers (no file on the disk: the pages only list them)
  history         --journal-rows lines in the history (journal), dated from 2023 to 2026, most of them on answers

Steps (all by default; --only runs one, to restart after a failure): setup (settings, tree, accounts, KPIs,
frameworks, assignments, campaigns), answers (answers, calculations, alerts, evidence), journal (history).
Refuses to run without DATA_DIR / DATABASE_URL / SQLITE_FILE, and refuses a database that is not empty. The full size
takes about 20 minutes (calculations dominate); --sites 60 --months 3 --journal-rows 20000 makes a small version.
Same seed, same data.
"""
import argparse
import datetime
import os
import random
import sys
import time
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from collecte import periodes as P
from collecte.calcul import recalculer
from collecte.coherence import controler
from collecte.management.commands import _demo_commun as DC
from collecte.models import Alerte, Campagne, Journal, Preuve, RegleCoherence, Reponse
from espaces import comptes as EC
from espaces import contexte as ESP
from parametres import niveaux as N
from parametres import referentiel as PR
from parametres.models import Instance, Langue
from referentiel.models import (KPI, Attribution, ElementReferentiel, Niveau, Organisation, Referentiel, Theme,
                                Utilisateur)

T0 = time.time()
MOT_DE_PASSE = "demo-probant-2026"
EXERCICES = (2023, 2024, 2025, 2026)  # 2026 : campagne ouverte
PAYS = ["Alba", "Borea", "Caldera", "Delta", "Estria", "Fjordia", "Galicia Nova", "Hesperia", "Istria", "Jutland Sud",
        "Kalmar", "Lusitania"]
UNITES = [("kWh", "kWh", "kilowattheure", False, 0, "Énergie"), ("m³", "m³", "mètre cube", False, 0, "Volume"),
          ("t", "t", "tonne", False, 1, "Masse"), ("kgCO2eq", "kgCO2eq", "kilogramme équivalent CO2", False, 0, "Émissions"),
          ("kgCO2eq/u", "kgCO2eq/u", "facteur d'émission", False, 3, "Émissions"), ("h", "h", "heure", False, 0, "Durée"),
          ("pers", "pers.", "personnes", True, 0, "Effectif"), ("k€", "k€", "millier d'euros", False, 1, "Monnaie")]
TYPES_REPONSE = [("OuiNon", "Oui / non", "oui_non", []), ("Niveau3", "Niveau", "liste", ["Faible", "Moyen", "Élevé"])]
N_SITE, N_ENTITE, N_FE, N_RATIOS, N_EMISSIONS, N_EVOLUTIONS = 180, 40, 10, 30, 20, 10
N_MENSUELS = 40


def log(*a):
    print(f"[{time.time() - T0:6.0f}s]", *a, flush=True)


def aleatoire(o, etape):
    return random.Random(f"{o.seed}-{etape}")


# ---------------------------------------------------------------- étape « setup »
def reglages():
    Instance.objects.update_or_create(pk=1, defaults=dict(
        nom="Grandgroupe", titre="Probant", sous_titre="Grandgroupe · large-volume test", sigle="GG", langue="fr",
        mise_en_place_terminee=True))
    PR.creer_par_defaut()
    N.creer_par_defaut()
    for i, (code, libelle) in enumerate((("fr", "Français"), ("en", "English"), ("es", "Español")), start=1):
        Langue.objects.update_or_create(code=code, defaults={"libelle": libelle, "ordre": i, "active": True})
    DC.unites_et_types(UNITES, TYPES_REPONSE)


def arbre(o):
    """Groupe › 12 pays › filiales (5 ou 6 par pays) › sites (répartis entre les filiales). Insertion en masse."""
    h = aleatoire(o, "arbre")
    groupe = Organisation(nom="Grandgroupe", code="GG", niveau_id=Niveau.GROUP, rang=0)
    groupe.save()
    pays = [Organisation(nom=p, code=f"P{i:02d}", niveau_id=Niveau.COUNTRY, parent=groupe, rang=i) for i, p in enumerate(PAYS)]
    Organisation.objects.bulk_create(pays)
    entites = []
    for i, p in enumerate(pays):
        for j in range(5 + i % 2):
            entites.append(Organisation(nom=f"{p.nom} filiale {j + 1}", code=f"E{i:02d}{j}", niveau_id=Niveau.ENTITY, parent=p, rang=j))
    Organisation.objects.bulk_create(entites)
    sites = []
    for n in range(o.sites):
        e = entites[n % len(entites)]
        rang = n // len(entites)
        site = Organisation(nom=f"{e.nom} · site {rang + 1:02d}", code=f"S{n:04d}", niveau_id=Niveau.SITE, parent=e, rang=rang,
                            type_site=h.choice(["entrepot", "bureau", "autre"]))
        if n % 97 == 13:  # fermé en 2024 : hors des calculs à partir de 2025
            site.actif, site.date_desactivation = False, datetime.date(2024, 3, 31)
        elif n % 89 == 7:  # fermé pendant 2026 : encore dans les calculs de 2026 (ouverte pendant la période)
            site.actif, site.date_desactivation = False, datetime.date(2026, 6, 30)
        sites.append(site)
    Organisation.objects.bulk_create(sites, batch_size=1000)
    log("organisations", Organisation.objects.count(), "(sites:", len(sites), ", inactive:", sum(not s.actif for s in sites), ")")


def comptes(o):
    cpt = {ident: DC.compte(ident, prenom, nom, role, MOT_DE_PASSE, email=f"{ident}@exemple.test")
           for ident, prenom, nom, role in [("admin", "Alice", "Admin (démo)", Utilisateur.Role.ADMIN),
                                            ("validateur", "Victor", "Validateur (démo)", Utilisateur.Role.VALIDATEUR),
                                            ("contributeur", "Camille", "Contributrice (démo)", Utilisateur.Role.CONTRIBUTEUR),
                                            ("lecteur", "Louise", "Lectrice (démo)", Utilisateur.Role.LECTEUR),
                                            ("auditeur", "Arthur", "Auditeur (démo)", Utilisateur.Role.AUDITEUR)]}
    mdp = cpt["admin"].password  # même mot de passe que les comptes de démo, haché une seule fois
    # numéros donnés ici, à la suite : seul le registre des espaces attribue les numéros des comptes (un compte créé
    # par bulk_create ne passe pas par lui ; sous PostgreSQL, la séquence de la table reste à 1)
    from espaces.models import Compte

    numero = max(Utilisateur.objects.order_by("-pk").values_list("pk", flat=True).first() or 0,
                 Compte.objects.order_by("-pk").values_list("pk", flat=True).first() or 0)
    nouveaux = []
    for prefixe, n, role in [("contrib", 150, "contributeur"), ("valid", 30, "validateur"), ("lect", 10, "lecteur"),
                             ("audit", 5, "auditeur"), ("adm", 5, "admin")]:
        nouveaux += [Utilisateur(pk=numero + len(nouveaux) + i + 1, username=f"{prefixe}{i:03d}", email=f"{prefixe}{i:03d}@exemple.test", role=role, password=mdp,
                                 first_name=prefixe.capitalize(), last_name=f"{i:03d}", is_staff=role == "admin",
                                 is_superuser=role == "admin", equipe=f"Équipe {i % 12}", doit_changer_mdp=False)
                     for i in range(n)]
    Utilisateur.objects.bulk_create(nouveaux)
    pays = list(Organisation.objects.filter(niveau_id=Niveau.COUNTRY).order_by("rang"))
    for i in range(0, 10, 3):  # un lecteur sur trois limité à un pays
        Utilisateur.objects.get(username=f"lect{i:03d}").perimetre_lecture.set([pays[i % len(pays)]])
    Utilisateur.objects.get(username="audit000").perimetre_lecture.set([pays[1]])
    # bulk_create saute les signaux qui recopient un compte dans le registre des espaces : sans cela, les nouveaux
    # comptes ne pourraient pas se connecter (espaces/comptes.py)
    EC.reconcilier()
    EC.remettre_sequence()  # PostgreSQL : le prochain compte créé dans l'outil prend le numéro suivant
    log("accounts", Utilisateur.objects.count())


def nouveau_kpi(code, libelle, type_saisie, niveau, agregation, unite=None, formule="", type_reponse="Numérique", ordre=0,
                actif=True, decimales=0, **autres):
    k = KPI(code=code, libelle=libelle, type_saisie_id=type_saisie, granularite_id=niveau, methode_agregation=agregation,
            unite_id=unite, formule=formule, type_reponse_id=type_reponse, ordre=ordre, actif=actif, decimales=decimales,
            equipe_responsable="Équipe " + code[:3], **autres)
    k.save()  # save : dépendances des formules (KPIFormule)
    return k


def kpis():
    """Référentiel annuel (catalogue) et mensuel. Codes : A-xxx saisis au site, B-xx saisis à la filiale, FE-xx facteurs
    (groupe, hérités), R-xx ratios sur l'effectif A-000 (KPI à nombreux dépendants), E-xx émissions, V-xx évolutions sur
    N-1, P-xx parts à la filiale, G-xx intensités au groupe, H-xx hors référentiel, I-xx inactifs, M-xx mensuels."""
    unites = ["kWh", "m³", "t", "h", "k€"]
    sortie = {"site": [], "entite": [], "fe": [], "calc": [], "hors": [], "inactifs": [], "mensuels": [], "facultatifs": set()}
    ordre = 0

    def suivant():
        nonlocal ordre
        ordre += 1
        return ordre

    sortie["site"].append(nouveau_kpi("A-000", "Effectif du site", "Saisi", Niveau.SITE, "Somme", "pers", ordre=suivant()))
    for i in range(1, N_SITE):
        if i % 45 == 0:
            k = nouveau_kpi(f"A-{i:03d}", f"Certification {i}", "Saisi", Niveau.SITE, "Décompte", type_reponse="OuiNon", ordre=suivant())
        elif i % 59 == 0:
            k = nouveau_kpi(f"A-{i:03d}", f"Niveau de risque {i}", "Saisi", Niveau.SITE, "Décompte", type_reponse="Niveau3", ordre=suivant())
        else:
            k = nouveau_kpi(f"A-{i:03d}", f"Consommation {i}", "Saisi", Niveau.SITE, "Somme", unites[i % len(unites)], ordre=suivant(),
                            saisie_au_dessus=i == 7)
        sortie["site"].append(k)
        if i % 18 == 5:
            sortie["facultatifs"].add(k.code)
    sortie["entite"].append(nouveau_kpi("B-00", "Chiffre d'affaires de la filiale", "Saisi", Niveau.ENTITY, "Somme", "k€", ordre=suivant()))
    for i in range(1, N_ENTITE):
        sortie["entite"].append(nouveau_kpi(f"B-{i:02d}", f"Indicateur de filiale {i}", "Saisi", Niveau.ENTITY, "Somme",
                                            unites[i % len(unites)], ordre=suivant()))
    for i in range(N_FE):
        sortie["fe"].append(nouveau_kpi(f"FE-{i:02d}", f"Facteur d'émission {i}", "FE", Niveau.GROUP, "Aucune", "kgCO2eq/u",
                                        ordre=suivant(), decimales=3))
    calc = sortie["calc"]
    for i in range(N_RATIOS):  # 30 KPI citent l'effectif : un changement de A-000 les refait tous
        calc.append(nouveau_kpi(f"R-{i:02d}", f"Ratio {i} par personne", "Calculé", Niveau.SITE, "Formule",
                                formule=f"[A-{i + 1:03d}] / [A-000]", ordre=suivant(), decimales=2))
    for i in range(N_EMISSIONS):
        calc.append(nouveau_kpi(f"E-{i:02d}", f"Émissions {i}", "Calculé", Niveau.SITE, "Somme", "kgCO2eq",
                                formule=f"[A-{i + 40:03d}] * [FE-{i % N_FE:02d}]", ordre=suivant()))
    calc.append(nouveau_kpi("E-TOT", "Émissions totales", "Calculé", Niveau.SITE, "Somme", "kgCO2eq",
                            formule=" + ".join(f"[E-{i:02d}]" for i in range(N_EMISSIONS)), ordre=suivant(), na_compte_zero=True))
    for i in range(N_EVOLUTIONS):
        calc.append(nouveau_kpi(f"V-{i:02d}", f"Évolution {i} sur un an", "Calculé", Niveau.SITE, "Formule", type_reponse="Pourcentage",
                                formule=f"([A-{i + 60:03d}] - [A-{i + 60:03d}@N-1]) / [A-{i + 60:03d}@N-1]", ordre=suivant(), decimales=1))
    for i in range(1, 11):
        calc.append(nouveau_kpi(f"P-{i:02d}", f"Part {i} du chiffre d'affaires", "Calculé", Niveau.ENTITY, "Formule",
                                type_reponse="Pourcentage", formule=f"[B-{i:02d}] / [B-00]", ordre=suivant(), decimales=1))
    for i in range(N_EMISSIONS // 2):
        calc.append(nouveau_kpi(f"G-{i:02d}", f"Intensité {i}", "Calculé", Niveau.GROUP, "Aucune",
                                formule=f"[E-{i:02d}] / [B-00]", ordre=suivant(), decimales=2))
    for i in range(10):
        sortie["hors"].append(nouveau_kpi(f"H-{i:02d}", f"Hors référentiel {i}", "Saisi", Niveau.SITE, "Somme", "kWh", ordre=suivant()))
    for i in range(5):
        sortie["inactifs"].append(nouveau_kpi(f"I-{i:02d}", f"Ancien indicateur {i}", "Saisi", Niveau.SITE, "Somme", "kWh",
                                              ordre=suivant(), actif=False))
    for i in range(N_MENSUELS):
        sortie["mensuels"].append(nouveau_kpi(f"M-{i:02d}", f"Suivi mensuel {i}", "Saisi", Niveau.SITE, "Somme", "kWh", ordre=suivant()))
    return sortie


def referentiels(ks):
    annuel = Referentiel.objects.create(code="GROUPE", nom="Reporting du groupe", frequence="annee", comparaison="N-1", ordre=1)
    mensuel = Referentiel.objects.create(code="MENSUEL", nom="Suivi mensuel", frequence="mois", comparaison="N-1", ordre=2)
    themes = {}
    for ref, noms in ((annuel, ["Social", "Environnement", "Énergie", "Gouvernance", "Économie"]), (mensuel, ["Énergie", "Eau"])):
        for i, nom in enumerate(noms):
            racine = Theme.objects.create(referentiel=ref, code=f"T{i}", nom=nom, ordre=i)
            themes[(ref.code, i)] = [Theme.objects.create(referentiel=ref, parent=racine, code=f"T{i}-{j}", nom=f"{nom} {j + 1}", ordre=j)
                                     for j in range(3)]
    elements = []
    annuels = ks["site"] + ks["entite"] + ks["fe"] + ks["calc"] + ks["inactifs"]
    for n, k in enumerate(annuels):
        t = themes[("GROUPE", n % 5)][n % 3]
        elements.append(ElementReferentiel(referentiel=annuel, kpi=k, theme=t, ordre=n, obligatoire=k.code not in ks["facultatifs"]))
    for n, k in enumerate(ks["mensuels"]):
        elements.append(ElementReferentiel(referentiel=mensuel, kpi=k, theme=themes[("MENSUEL", n % 2)][n % 3], ordre=n))
    ElementReferentiel.objects.bulk_create(elements, batch_size=1000)
    RegleCoherence.objects.create(nom="Consommation 2 ≤ consommation 1", gauche="[A-002]", operateur="<=", droite="[A-001] * 3",
                                  tolerance=Decimal("0"), niveau_id=Niveau.SITE, bloquante=False, description="Contrôle fictif.")
    RegleCoherence.objects.create(nom="Indicateur 2 ≤ chiffre d'affaires", gauche="[B-02]", operateur="<=", droite="[B-00]",
                                  tolerance=Decimal("0"), niveau_id=Niveau.ENTITY, bloquante=False, description="Contrôle fictif.")
    log("frameworks: GROUPE", len(annuels), "KPIs, MENSUEL", len(ks["mensuels"]), "KPIs; catalogue", KPI.objects.count())


def attributions(o, ks):
    h = aleatoire(o, "attributions")
    u = {x.username: x for x in Utilisateur.objects.all()}
    contribs = [u[f"contrib{i:03d}"] for i in range(150)]
    sites = list(Organisation.objects.filter(niveau_id=Niveau.SITE, actif=True).order_by("parent_id", "rang"))
    entites = list(Organisation.objects.filter(niveau_id=Niveau.ENTITY).order_by("parent_id", "rang"))
    pays = list(Organisation.objects.filter(niveau_id=Niveau.COUNTRY).order_by("rang"))
    groupe = Organisation.objects.get(niveau_id=Niveau.GROUP)
    liens = []
    site_kpis = [k for k in ks["site"] + ks["hors"] + ks["mensuels"]]
    for j, s in enumerate(sites):
        c = u["contributeur"] if j < 3 else contribs[(j // 4) % len(contribs)]
        for k in site_kpis:
            if h.random() < 0.004:  # quelques cases sans contributeur
                continue
            liens.append(Attribution(kpi=k, organisation=s, utilisateur=c, role="contributeur"))
    for j, e in enumerate(entites):
        for k in ks["entite"]:
            liens.append(Attribution(kpi=k, organisation=e, utilisateur=contribs[(j * 7) % len(contribs)], role="contributeur"))
    for k in ks["fe"]:
        liens.append(Attribution(kpi=k, organisation=groupe, utilisateur=u["contributeur"], role="contributeur"))
    for k in ks["calc"][:5]:  # responsables du résultat de quelques KPI calculés (valeur forcée)
        liens.append(Attribution(kpi=k, organisation=sites[0], utilisateur=u["contributeur"], role="contributeur"))
    validables = [k for k in ks["site"] + ks["entite"] + ks["mensuels"]]
    for i, p in enumerate(pays):
        for k in validables:
            liens.append(Attribution(kpi=k, organisation=p, utilisateur=u[f"valid{i:03d}"], role="validateur"))
    for k in validables:
        liens.append(Attribution(kpi=k, organisation=pays[0], utilisateur=u["validateur"], role="validateur"))
    for i in range(12, 30):  # autres validateurs : une filiale chacun
        for k in validables:
            liens.append(Attribution(kpi=k, organisation=entites[i * 3 % len(entites)], utilisateur=u[f"valid{i:03d}"], role="validateur"))
    Attribution.objects.bulk_create(liens, batch_size=5000, ignore_conflicts=True)
    log("assignments", Attribution.objects.count())


def campagnes(o):
    annuel, mensuel = Referentiel.objects.get(code="GROUPE"), Referentiel.objects.get(code="MENSUEL")
    for an in EXERCICES:
        ouverte = an == EXERCICES[-1]
        P.campagne(annuel, datetime.date(an, 1, 1), statut=Campagne.Statut.OUVERTE if ouverte else Campagne.Statut.CLOTUREE,
                   date_ouverture=datetime.date(an, 10, 1) if ouverte else datetime.date(an + 1, 1, 6),
                   date_fin_saisie=datetime.date(an + 1, 2, 28) if ouverte else datetime.date(an + 1, 3, 31), seuil_ecart=Decimal("0.3"))
    for d in mois(o):
        ouverte = d == mois(o)[-1]
        P.campagne(mensuel, d, statut=Campagne.Statut.OUVERTE if ouverte else Campagne.Statut.CLOTUREE,
                   date_ouverture=P.ajouter_mois(d, 1), date_fin_saisie=P.ajouter_mois(d, 1) + datetime.timedelta(days=40),
                   seuil_ecart=Decimal("0.3"))
    log("campaigns", Campagne.objects.count())


def mois(o):
    d, sortie = datetime.date(2025, 1, 1), []
    while len(sortie) < o.months:
        sortie.append(d)
        d = P.ajouter_mois(d, 1)
    return sortie


def etape_setup(o):
    if Organisation.objects.exists() or KPI.objects.exists() or Campagne.objects.exists() or Utilisateur.objects.exists():
        sys.exit("This database is not empty: start from an empty DATA_DIR (or an empty PostgreSQL database).")
    with ESP.atomic():
        reglages()
        arbre(o)
        comptes(o)
        ks = kpis()
        referentiels(ks)
        attributions(o, ks)
        campagnes(o)


# ---------------------------------------------------------------- étape « answers »
def valeur(h, base, an):
    """Valeur d'une année : la base, une tendance et un peu de bruit ; parfois un écart fort (alertes d'écart avec N-1)."""
    v = base * (1 + 0.03 * (an - 2023)) * h.uniform(0.9, 1.1)
    if h.random() < 0.01:
        v *= h.choice([0.4, 2.2])
    return Decimal(str(round(v, 2)))


def ouverte_en(s, debut):
    return s.actif or (s.date_desactivation and s.date_desactivation >= debut)


def etape_answers(o):
    if not KPI.objects.filter(code="A-000").exists():
        sys.exit("Run the step setup first.")
    if Reponse.objects.exists():
        sys.exit("Answers already exist: the step answers was already run.")
    h = aleatoire(o, "answers")
    u = {x.username: x for x in Utilisateur.objects.all()}
    sites = list(Organisation.objects.filter(niveau_id=Niveau.SITE).order_by("pk"))
    entites = list(Organisation.objects.filter(niveau_id=Niveau.ENTITY).order_by("pk"))
    groupe = Organisation.objects.get(niveau_id=Niveau.GROUP)
    spoc = {(a.kpi_id, a.organisation_id): a.utilisateur_id for a in Attribution.objects.filter(role="contributeur")}
    ks = KPI.objects.select_related("type_reponse", "type_saisie")
    saisis_site = [k for k in ks if k.granularite_id == Niveau.SITE and k.code[0] in "AHI"]
    saisis_entite = [k for k in ks if k.code.startswith("B-")]
    facteurs = [k for k in ks if k.code.startswith("FE-")]
    mensuels = [k for k in ks if k.code.startswith("M-")]
    bases = {}

    def base(k, org):
        if (k.code, org.pk) not in bases:
            bases[(k.code, org.pk)] = h.uniform(50, 50000)
        return bases[(k.code, org.pk)]

    def reponse(periode, k, org, an, ouverte, debut):
        if ouverte:
            tirage = h.random()
            if tirage < 0.45:
                statut = "valide"
            elif tirage < 0.6:
                statut = "brouillon"
            else:
                return None  # à saisir
        else:
            statut = "valide"
        auteur = spoc.get((k.code, org.pk)) or u["admin"].pk
        r = Reponse(periode=periode, kpi=k, organisation=org, statut=statut, origine="saisie", saisi_par_id=auteur)
        if statut == "valide":
            r.valide_par_id, r.date_validation = auteur, timezone.make_aware(datetime.datetime(debut.year + 1 if not ouverte else 2026, 2, 1, 9))
        if k.code.startswith("FE-"):
            r.valeur = Decimal(str(round(0.05 + 0.01 * int(k.code[3:]) + (an - 2023) * 0.002, 4)))
        elif h.random() < 0.03:
            r.non_applicable, r.commentaire = True, "Sans objet sur ce site."
        elif k.type_reponse.format == "oui_non":
            r.texte = h.choice(["Oui", "Non"])
        elif k.type_reponse.format == "liste":
            r.texte = h.choice(k.type_reponse.valeurs)
        else:
            r.valeur = valeur(h, base(k, org), an)
        return r

    annuel = Referentiel.objects.get(code="GROUPE")
    for c in Campagne.objects.filter(referentiel=annuel).select_related("periode").order_by("exercice"):
        an, ouverte, debut = c.exercice, c.statut == Campagne.Statut.OUVERTE, c.periode.debut
        lot = []
        for k in saisis_site:
            if (not k.actif and an > 2023) or (k.code.startswith("H-") and an < 2025):
                continue
            for s in sites:
                if ouverte_en(s, debut):
                    r = reponse(c.periode, k, s, an, ouverte, debut)
                    if r:
                        lot.append(r)
        for k in saisis_entite:
            for e in entites:
                r = reponse(c.periode, k, e, an, ouverte, debut)
                if r:
                    lot.append(r)
        for k in facteurs:
            lot.append(reponse(c.periode, k, groupe, an, False, debut))  # facteurs toujours donnés
        if ouverte:  # saisie au-dessus de la granularité : une filiale donne le total de ses sites pour A-007
            e = entites[0]
            lot = [r for r in lot if not (r.kpi_id == "A-007" and r.organisation.parent_id == e.pk)]
            lot.append(Reponse(periode=c.periode, kpi_id="A-007", organisation=e, valeur=Decimal("12345"), statut="brouillon",
                               origine="saisie", saisi_par=u["validateur"]))
        Reponse.objects.bulk_create(lot, batch_size=5000)
        log(f"{an}: {len(lot)} answers entered")
    mensuel = Referentiel.objects.get(code="MENSUEL")
    for c in Campagne.objects.filter(referentiel=mensuel).select_related("periode").order_by("periode__debut"):
        ouverte, debut = c.statut == Campagne.Statut.OUVERTE, c.periode.debut
        lot = []
        for k in mensuels:
            for s in sites:
                if ouverte_en(s, debut):
                    r = reponse(c.periode, k, s, debut.year, ouverte, debut)
                    if r:
                        r.valeur = Decimal(str(round(base(k, s) / 12 * h.uniform(0.8, 1.2), 2))) if r.valeur is not None else None
                        lot.append(r)
        Reponse.objects.bulk_create(lot, batch_size=5000)
    log("monthly answers", Reponse.objects.filter(kpi__in=mensuels).count())
    # calculs : chaque période une fois, de la plus ancienne à la plus récente (les formules @N-1 lisent l'année d'avant)
    faites = set()
    for c in Campagne.objects.select_related("periode", "referentiel").order_by("periode__debut", "periode__fin"):
        if c.periode_id in faites:
            continue
        faites.add(c.periode_id)
        t = time.time()
        recalculer(c, propager=False)
        if c.periode.annuelle or c.statut == Campagne.Statut.OUVERTE:
            log(f"calculated {c.periode} in {time.time() - t:.0f}s")
    log("calculations done:", Reponse.objects.count(), "answers")
    alertes(o, u)
    preuves(o)


def alertes(o, u):
    h = aleatoire(o, "alertes")
    quand = timezone.make_aware(datetime.datetime(2026, 3, 20, 10))
    a_controler = list(Campagne.objects.filter(exercice=2025, referentiel_id="GROUPE"))
    a_controler += list(Campagne.objects.filter(statut=Campagne.Statut.OUVERTE))
    for c in a_controler:
        t = time.time()
        controler(c)
        qs = Alerte.objects.filter(campagne=c)
        if c.statut == Campagne.Statut.CLOTUREE:
            qs.update(statut=Alerte.Statut.ACCEPTEE, justification="Écart vérifié avec le site : valeur confirmée.",
                      justifie_par=u["contrib000"], date_justification=quand, traite_par=u["valid000"], date_traitement=quand)
        else:
            ids = [pk for pk in qs.values_list("pk", flat=True) if h.random() < 0.3]
            Alerte.objects.filter(pk__in=ids).update(statut=Alerte.Statut.JUSTIFIEE, justification="Changement d'activité sur le site.",
                                                     justifie_par=u["contrib001"], date_justification=timezone.now())
        log(f"alerts of {c}: {qs.count()} in {time.time() - t:.0f}s")


def preuves(o):
    """Enregistrements de preuves sans fichier sur le disque : une sur 25 des réponses validées des sites (annuel)."""
    h = aleatoire(o, "preuves")
    ids = list(Reponse.objects.filter(statut="valide", origine="saisie", kpi__granularite_id=Niveau.SITE, periode__type="annee")
               .values_list("pk", "saisi_par_id", "periode__debut"))
    lot = []
    for pk, auteur, debut in ids:
        if h.random() < 0.04:
            nom = f"justificatif-{pk}.pdf"
            lot.append(Preuve(reponse_id=pk, fichier=f"preuves/{debut.year}/{nom}", nom_fichier=nom, taille=h.randint(20_000, 900_000),
                              depose_par_id=auteur))
    Preuve.objects.bulk_create(lot, batch_size=5000)
    log("evidence records", Preuve.objects.count())


# ---------------------------------------------------------------- étape « journal »
def etape_journal(o):
    if not Reponse.objects.exists():
        sys.exit("Run the step answers first.")
    h = aleatoire(o, "journal")
    rep = list(Reponse.objects.filter(origine__in=["saisie", "import"]).values_list("pk", "periode__debut"))
    rep_calc = list(Reponse.objects.filter(origine__in=["calcul", "agregation"]).values_list("pk", "periode__debut")[:300_000])
    uids = list(Utilisateur.objects.values_list("pk", flat=True))
    camps = [str(pk) for pk in Campagne.objects.values_list("pk", flat=True)]
    kpis = list(KPI.objects.values_list("pk", flat=True))
    debut = datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc)
    duree = int((datetime.datetime(2026, 11, 10, tzinfo=datetime.timezone.utc) - debut).total_seconds())
    saisies = [("creation", "valeur"), ("modification", "valeur"), ("modification", "statut"), ("creation", "statut"),
               ("modification", "commentaire"), ("depot_preuve", "fichier"), ("alerte_justifier", "justification")]
    autres = [("reglage_kpi", "KPI"), ("reglage_campagne", "Campagne"), ("relance", "Utilisateur"), ("attribution", "KPI"),
              ("sauvegarde", "Instance")]
    vendor = connection.vendor
    cur = connection.cursor()
    lot_taille = 50_000
    for debut_lot in range(0, o.journal_rows, lot_taille):
        rows = []
        for _ in range(min(lot_taille, o.journal_rows - debut_lot)):
            tirage = h.random()
            if tirage < 0.80:  # saisie : l'entrée suit la période de la réponse (janvier à mars de l'année suivante)
                pk, d = h.choice(rep)
                action, champ = saisies[h.randrange(len(saisies))]
                quand = datetime.datetime(min(d.year + 1, 2026), 1, 5, tzinfo=datetime.timezone.utc) + datetime.timedelta(seconds=h.randrange(0, 86400 * 80))
                objet, oid, avant, apres = "Reponse", str(pk), str(h.randint(1, 5000)), str(h.randint(1, 5000))
            elif tirage < 0.95:  # recalcul
                pk, d = h.choice(rep_calc)
                action, champ, objet, oid = "valeur_recalculee", "valeur", "Reponse", str(pk)
                quand = debut + datetime.timedelta(seconds=h.randrange(0, duree))
                avant, apres = str(h.randint(1, 90000)), str(h.randint(1, 90000))
            else:
                action, objet = autres[h.randrange(len(autres))]
                oid = {"KPI": h.choice(kpis), "Campagne": h.choice(camps), "Utilisateur": str(h.choice(uids)), "Instance": "1"}[objet]
                champ, avant, apres = "reglage", "", "réglage fictif"
                quand = debut + datetime.timedelta(seconds=h.randrange(0, duree))
            dt = quand.strftime("%Y-%m-%d %H:%M:%S.%f") + ("+00:00" if vendor == "postgresql" else "")
            rows.append((dt, h.choice(uids), action, objet, oid, champ, avant, apres))
        cur.executemany("INSERT INTO collecte_journal (date, utilisateur_id, action, objet, objet_id, champ, avant, apres) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", rows)
        log("history", debut_lot + len(rows), "lines")
    # pas d'ANALYZE : l'outil n'en lance jamais, la mesure doit voir les plans d'une vraie installation SQLite


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", choices=["setup", "answers", "journal"], help="run one step only")
    ap.add_argument("--sites", type=int, default=600, help="number of sites (default 600: about 680 organisations in all)")
    ap.add_argument("--journal-rows", type=int, default=1_200_000, help="lines of the history to insert (default 1,200,000)")
    ap.add_argument("--months", type=int, default=22, help="months of the monthly framework, from January 2025 (default 22)")
    ap.add_argument("--seed", type=int, default=1, help="seed of the random numbers (same seed, same data)")
    o = ap.parse_args()
    if not (os.environ.get("DATA_DIR") or os.environ.get("DATABASE_URL") or os.environ.get("SQLITE_FILE")):
        sys.exit("Set DATA_DIR (an empty folder) or DATABASE_URL: this script writes millions of fictitious rows.")
    if o.months < 1 or o.sites < 12:
        sys.exit("--months must be at least 1 and --sites at least 12.")
    call_command("migrate", verbosity=0)
    if o.only in (None, "setup"):
        etape_setup(o)
    if o.only in (None, "answers"):
        etape_answers(o)
    if o.only in (None, "journal"):
        etape_journal(o)
    log("done:", Organisation.objects.count(), "organisations,", Utilisateur.objects.count(), "accounts,", KPI.objects.count(),
        "KPIs,", Reponse.objects.count(), "answers,", Alerte.objects.count(), "alerts,", Preuve.objects.count(), "evidence records,",
        Journal.objects.count(), "history lines")


if __name__ == "__main__":
    main()
