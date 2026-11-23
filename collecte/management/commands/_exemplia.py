"""Démo par défaut : Exemplia, fabricant fictif d'emballages en carton (règle du projet).

Montre l'outil réglé pour une entreprise industrielle : 4 niveaux Groupe › Pays › Filiale › Site, 11 sites en France, en Espagne
et en Allemagne (usines, entrepôts, centre de tri, bureaux ; « Lager Hannover » fermé le 30/06/2025), et seulement la
norme volontaire VS (modules de base et complet, installés depuis la bibliothèque) ; les onze modèles ESRS sont installés à la fin, sans aucune valeur ni campagne. Exercices 2024 et 2025 remplis,
validés et clôturés : le classeur officiel de l'EFRAG s'exporte pour les deux années. Exercice 2026 ouvert (règle du projet), pour essayer la saisie, les validations et les relances : collecte en cours, avancement inégal
selon les sites (valeurs validées, brouillons, cases à saisir), alertes de cohérence à traiter, date limite proche.

Valeurs inventées mais cohérentes : les totaux de déchets découlent du tableau par code de déchet, les règles des
modèles sont respectées (électricité renouvelable ≤ achetée, femmes ≤ effectif…), les tendances racontent une histoire
(chaudière biomasse à Leipzig en 2025, panneaux solaires agrandis, fermeture d'Hannover). Aucune donnée réelle : noms
d'entreprise et de personnes inventés, e-mails @exemple.test, adresses fictives dans de vraies villes.

Sept langues : la démo se charge dans la langue de l'installation (ou ``--language``). Les textes qu'elle écrit sont dans
``_exemplia_textes.py`` (un jeu par langue), les traductions des libellés de la norme VS dans ``_exemplia_bibliotheque.py``.
Les chiffres, les statuts et les alertes ne dépendent jamais de la langue : les organisations s'y repèrent par leur clé
(le nom français), jamais par le nom affiché.
"""
import datetime
import zlib
from decimal import Decimal

from django.core.files.base import ContentFile
from django.utils import timezone

from collecte import paquets as PQ
from collecte import periodes as P
from collecte import tableaux as T
from collecte.calcul import recalculer
from collecte.models import Campagne, Journal, Preuve, Reponse
from parametres import niveaux as N
from parametres.couleurs import PALETTES
from parametres.models import Langue, NiveauHierarchique, TypeReponse
from referentiel.bibliotheque.definitions._vs_listes import CATEGORIES_SCOPE3, INFOS_INCHANGEES
from referentiel.models import KPI, Attribution, Niveau, Organisation, Referentiel, Utilisateur

from . import _demo_commun as DC
from . import _exemplia_bibliotheque as BIB
from ._exemplia_descriptions import DESCRIPTIONS_EN
from . import _exemplia_textes as TX

NOM = "Exemplia"
_P = PALETTES["foret"]
IDENTITE = dict(nom=NOM, titre="Probant", sous_titre="Exemplia · démo", sigle="EX", contact="l'équipe Développement durable",
                palette="foret", couleur_principale=_P["principale"], couleur_accent=_P["accent"], couleur_fond=_P["fond"],
                couleur_texte=_P["texte"], langue="fr", mise_en_place_terminee=True)  # en français ; ``identite(langue)`` pour les autres


def identite(langue):
    """Identité de l'installation de démo dans une langue : sous-titre et contact traduits, langue par défaut de
    l'installation = la langue demandée (la langue de référence des textes reste celle du modèle de base)."""
    with TX.regler(langue):
        return {**IDENTITE, "sous_titre": TX.texte("SOUS_TITRE"), "contact": TX.texte("CONTACT"), "langue": langue}
MODELES = ("vs_base.json", "vs_complet.json")
# Les onze modèles ESRS (CSRD), installés à la fin, sans valeur : voir ``installer_esrs``.
ESRS = ("esrs_2.json", "esrs_e1.json", "esrs_e2.json", "esrs_e3.json", "esrs_e4.json", "esrs_e5.json", "esrs_s1.json", "esrs_s2.json",
        "esrs_s3.json", "esrs_s4.json", "esrs_g1.json")
EXERCICES = (2024, 2025)  # clôturés
EN_COURS = 2026  # campagne ouverte
FERMETURE_HANNOVER = datetime.date(2025, 6, 30)

COMPTES = [  # identifiant, prénom, nom, rôle, langue
    ("admin", "Alice", "Admin (démo)", Utilisateur.Role.ADMIN, ""),
    ("validateur", "Victor", "Validateur (démo)", Utilisateur.Role.VALIDATEUR, ""),
    ("contributeur", "Camille", "Contributrice (démo)", Utilisateur.Role.CONTRIBUTEUR, ""),
    ("lecteur", "Louise", "Lectrice (démo)", Utilisateur.Role.LECTEUR, ""),
    ("auditeur", "Arthur", "Auditeur (démo)", Utilisateur.Role.AUDITEUR, ""),
    ("sophie.marchal", "Sophie", "Marchal", Utilisateur.Role.CONTRIBUTEUR, ""),
    ("nathan.roux", "Nathan", "Roux", Utilisateur.Role.CONTRIBUTEUR, ""),
    ("lucia.martin", "Lucía", "Martín", Utilisateur.Role.CONTRIBUTEUR, "es"),
    ("jonas.weber", "Jonas", "Weber", Utilisateur.Role.CONTRIBUTEUR, "de"),
    ("anna.schmidt", "Anna", "Schmidt", Utilisateur.Role.CONTRIBUTEUR, "de"),
    ("diego.santos", "Diego", "Santos", Utilisateur.Role.VALIDATEUR, "es"),
    ("lena.hoffmann", "Lena", "Hoffmann", Utilisateur.Role.VALIDATEUR, "de"),
]
SPOC_FILIALE = {"Exemplia Emballages France": "contributeur", "Exemplia Recyclage": "nathan.roux",
                "Exemplia Ibérica": "lucia.martin", "Exemplia Deutschland": "jonas.weber", "Exemplia Logistik": "anna.schmidt"}
VALIDATEUR_PAYS = {"France": "validateur", "Espagne": "diego.santos", "Allemagne": "lena.hoffmann"}

# ---------------------------------------------------------------- organisations
GROUPE = "Exemplia Groupe"
PAYS = {  # pays de l'arbre : (pays de la liste officielle, filiales)
    "France": ("France", ["Exemplia Emballages France", "Exemplia Recyclage"]),
    "Espagne": ("Spain", ["Exemplia Ibérica"]),
    "Allemagne": ("Germany", ["Exemplia Deutschland", "Exemplia Logistik"]),
}
# Sites : filiale, type, adresse, code postal, ville, coordonnées GPS, effectif fin 2024, fin 2025, et réglages propres
SITES = {
    "Siège de Lyon": ("Exemplia Emballages France", "bureau", "1 / rue de l'Exemple", "69007", "Lyon", "45.73010, 4.83120", 60, 63,
                      {"chaleur": 310_000, "ca": 0}),
    "Usine de Villefranche": ("Exemplia Emballages France", "usine", "Zone d'exemple / 2 rue de l'Exemple", "69400",
                              "Villefranche-sur-Saône", "45.98870, 4.72010", 180, 186, {"pv": (180_000, 420_000), "ca": 48}),
    "Usine de Roanne": ("Exemplia Emballages France", "usine", "3 / rue de l'Exemple", "42300", "Roanne", "46.03610, 4.06790", 130, 134,
                        {"gpl": 120, "ca": 33, "zone": ("proche", "ZONE_ROANNE")}),
    "Entrepôt de Mâcon": ("Exemplia Emballages France", "entrepot", "4 / rue de l'Exemple", "71000", "Mâcon", "46.30690, 4.82810", 35, 36, {}),
    "Centre de tri de Vénissieux": ("Exemplia Recyclage", "tri", "5 / rue de l'Exemple", "69200", "Vénissieux", "45.69720, 4.88590", 55, 57,
                                    {"ca": 9}),
    "Fábrica de Zaragoza": ("Exemplia Ibérica", "usine", "Calle Ejemplo 1", "50197", "Zaragoza", "41.64880, -0.88910", 150, 156,
                            {"pv": (260_000, 520_000), "ca": 36, "stress": True}),
    "Almacén de Valencia": ("Exemplia Ibérica", "entrepot", "Calle Ejemplo 2", "46023", "Valencia", "39.46920, -0.37590", 25, 26,
                            {"stress": True}),
    "Werk Leipzig": ("Exemplia Deutschland", "usine", "Musterstraße 1", "04129", "Leipzig", "51.33980, 12.37520", 160, 163,
                     {"biomasse": True, "ca": 41, "zone": ("proche", "ZONE_LEIPZIG")}),
    "Büro Frankfurt": ("Exemplia Deutschland", "bureau", "Musterstraße 2", "60325", "Frankfurt am Main", "50.11010, 8.66480", 18, 19,
                       {}),
    "Lager Hannover": ("Exemplia Logistik", "entrepot", "Musterstraße 3", "30179", "Hannover", "52.40480, 9.75020", 22, 0, {"ferme": True}),
    "Lager Dortmund": ("Exemplia Logistik", "entrepot", "Musterstraße 4", "44147", "Dortmund", "51.52530, 7.44670", 30, 48, {}),
}

# Profils par type de site (2024) : énergie (kWh, L), eau (m³), part de rejet des procédés, fugitives (tCO2e), femmes,
# CDI, accidents, heures de formation par salarié, scope 3 (tCO2e)
PROFILS = {
    "usine": dict(elec=21_000, gaz=38_000, fioul=1_500, gazole=140, essence=10, eau=190, rejet=0.62, fugitives=0.14, femmes=0.28,
                  cdi=0.91, accidents=0.028, formation=15, achats=62, immo=2.4, fret_amont=9, fret_aval=11, fin_vie=13, tri_part=0.85),
    "tri": dict(elec=45_000, gaz=14_000, fioul=0, gazole=1_100, essence=20, eau=95, rejet=0, fugitives=0.07, femmes=0.25,
                cdi=0.88, accidents=0.04, formation=11, achats=15, immo=0.6, fret_amont=5, fret_aval=0, fin_vie=0, tri_part=0.4),
    "entrepot": dict(elec=26_000, gaz=17_000, fioul=0, gazole=650, essence=15, eau=42, rejet=0, fugitives=0.17, femmes=0.2,
                     cdi=0.86, accidents=0.03, formation=9, achats=1.5, immo=0.9, fret_amont=6, fret_aval=26, fin_vie=0, tri_part=0.8),
    "bureau": dict(elec=6_500, gaz=4_000, fioul=0, gazole=250, essence=140, eau=33, rejet=0, fugitives=0.13, femmes=0.55,
                   cdi=0.95, accidents=0, formation=20, achats=2, immo=0.5, fret_amont=0, fret_aval=0, fin_vie=0, tri_part=0.9),
}
FE_ELEC = {"France": {2024: "0.052", 2025: "0.049", 2026: "0.047"}, "Espagne": {2024: "0.108", 2025: "0.101", 2026: "0.097"},
           "Allemagne": {2024: "0.381", 2025: "0.363", 2026: "0.352"}}
MIX_RESIDUEL = {"France": 0.035, "Espagne": 0.29, "Allemagne": 0.62}  # scope 2 méthode marché (kgCO2e/kWh non couvert)
PART_RENOUVELABLE = {"France": (0.40, 0.60, 0.66), "Espagne": (0.20, 0.35, 0.38), "Allemagne": (0.10, 0.30, 0.32)}  # 2024, 2025, 2026
# 2026 : chaque valeur d'un site reste à moins de 15 % de 2025 (ECART_2026_MAX, sous le seuil de 20 % de la campagne) ;
# les seuls écarts marqués sont ceux de ECARTS_2026
ECART_2026_MAX = 0.15
CROISSANCE_2026 = {"usine": 1.02, "tri": 1.03, "entrepot": 1.0, "bureau": 1.05}  # effectif fin 2026 / fin 2025
CONVENTION = {"France": 1.0, "Espagne": 1.0, "Allemagne": 0.7}
FACTEURS = {  # paramètres de calcul (niveau du groupe), identiques les deux années
    "CONV-GAZ-PCI": "0.901", "CONV-FIOUL": "9.97", "CONV-GAZOLE": "9.96", "CONV-ESSENCE": "8.94", "FE-GAZ": "0.227",
    "FE-FIOUL": "3.250", "FE-GAZOLE": "3.160", "FE-ESSENCE": "2.800", "FE-CHALEUR": "0.150", "FE-FROID": "0.020",
}
DECHET = {  # code abrégé -> valeur exacte de la liste officielle (VS-DECHET)
    "carton": "15 01 01 - Non-Hazardous - Paper and cardboard packaging", "plastique": "15 01 02 - Non-Hazardous - Plastic packaging",
    "bois": "15 01 03 - Non-Hazardous - Wooden packaging", "encres": "08 01 11 - Hazardous - Waste paint and varnish containing organic solvents or other hazardous substances",
    "huiles": "13 02 05 - Hazardous - Mineral-based non-chlorinated engine, gear and lubricating oils",
    "absorbants": "15 02 02 - Hazardous - Absorbents, filter materials (including oil filters not otherwise specified), wiping cloths, protective clothing contaminated by hazardous substances",
    "melange": "15 01 06 - Non-Hazardous - Mixed packaging", "refus": "19 12 12 - Non-Hazardous - Other wastes (including mixtures of materials) from mechanical treatment of wastes other than those mentioned in 19 12 11",
    "papier": "20 01 01 - Non-Hazardous - Paper and cardboard", "deee": "16 02 14 - Non-Hazardous - Discarded equipment other than those mentioned in 16 02 09 to 16 02 13",
}
DECHETS_TYPE = {  # type de site : [(code, tonnes par salarié, part recyclée, part préparée pour le réemploi)]
    "usine": [("carton", 9.5, 1.0, 0), ("plastique", 0.45, 0.7, 0), ("bois", 0.8, 0.2, 0.7), ("encres", 0.11, 0, 0),
              ("huiles", 0.03, 0.8, 0), ("melange", 0.6, 0.1, 0)],
    "tri": [("refus", 9.0, 0.35, 0), ("huiles", 0.05, 0.8, 0), ("absorbants", 0.04, 0, 0)],
    "entrepot": [("carton", 2.6, 1.0, 0), ("plastique", 0.7, 0.85, 0), ("bois", 1.2, 0.25, 0.65), ("melange", 0.3, 0.05, 0)],
    "bureau": [("papier", 0.12, 1.0, 0), ("melange", 0.18, 0.3, 0), ("deee", 0.01, 0.3, 0.5)],
}
POLLUANTS = {  # usines : polluant (valeur exacte de la liste) -> (air, eau, sol) en kg par salarié
    "Non-methane volatile organic compounds (NMVOC)": (62, None, None),
    "Nitrogen oxides (NOx/NO2)": (19, None, None),
    "Total organic carbon (TOC) (total C or COD/3)": (None, 8.5, None),
}

# ---------------------------------------------------------------- textes du groupe (Markdown, dans _exemplia_textes.py)
TEXTES = ("GEN-INTRO", "GEN-CONFORMITE", "GEN-NACE", "GEN-CERTIF-DESC", "ECO-CIRCULAIRE-DESC", "POL-URL", "STR-PRODUITS", "STR-MARCHES",
          "STR-RELATIONS", "STR-ENJEUX-DESC", "GOV-C2-DESC", "GOV-C2-CIBLES", "GOV-C2-RESPONSABLE", "GES-ACTIONS", "GES-PLAN-DESC",
          "CLI-ALEAS", "CLI-EXPOSITION", "CLI-HORIZONS", "CLI-EFFETS", "SOC-CODE-AUTRE-DESC")
TEXTES_SANS_LANGUE = {"GEN-NACE": "17.21\n22.22\n38.32", "POL-URL": "https://www.exemplia.example/environnement/rejets-{annee}"}
TEXTES_2024 = {"GES-PLAN-DESC": None}  # 2024 : plan encore en préparation (pas de description)


def niveaux():
    """Les 4 niveaux standard, le troisième appelé « Filiale » (base vide : aucune organisation, aucun KPI)."""
    N.creer_par_defaut()
    n = NiveauHierarchique.objects.get(code=Niveau.ENTITY)
    n.nom, n.nom_pluriel = "Filiale", "Filiales"
    # « Filiale » remplace « Entité » : les noms des sept langues sont à la démo (les autres niveaux gardent ceux de
    # ``creer_par_defaut``, qui a déjà posé l'espagnol, l'allemand, l'italien, le néerlandais et le portugais)
    n.traductions = {**n.traductions, "en": {"nom": "Subsidiary", "nom_pluriel": "Subsidiaries"},
                     "es": {"nom": "Filial", "nom_pluriel": "Filiales"},
                     "de": {"nom": "Tochtergesellschaft", "nom_pluriel": "Tochtergesellschaften"},
                     "it": {"nom": "Filiale", "nom_pluriel": "Filiali"},
                     "nl": {"nom": "Dochteronderneming", "nom_pluriel": "Dochterondernemingen"},
                     "pt": {"nom": "Filial", "nom_pluriel": "Filiais"}}
    n.save()
    # « Pays » : traductions de départ conservées (``parametres/0036``), l'anglais et l'espagnol de la démo par-dessus
    pays = NiveauHierarchique.objects.get(code=Niveau.COUNTRY)
    pays.traductions = {**pays.traductions, "en": {"nom": "Country", "nom_pluriel": "Countries"},
                        "es": {"nom": "País", "nom_pluriel": "Países"}}
    pays.save()


def langues():
    """Les sept langues de l'interface, actives pour les contenus : une personne qui change de langue voit les contenus
    traduits de la démo."""
    for i, (code, libelle) in enumerate((("fr", "Français"), ("en", "English"), ("es", "Español"), ("de", "Deutsch"), ("it", "Italiano"),
                                         ("nl", "Nederlands"), ("pt", "Português")), start=1):
        Langue.objects.update_or_create(code=code, defaults={"libelle": libelle, "ordre": i, "active": True})


def cles_organisations():
    """Toutes les clés (noms français) des organisations de la démo."""
    cles = [GROUPE]
    for pays, (_, filiales) in PAYS.items():
        cles += [pays, *filiales]
    return cles + list(SITES)


def cle(o):
    """Clé (nom français) d'une organisation de la démo, quelle que soit la langue dans laquelle elle a été créée."""
    return {TX.nom_organisation(k): k for k in cles_organisations()}.get(o.nom, o.nom)


def organisations():
    orgs = {}

    def creer(cle_org, niveau, parent, rang, actif=True, fermeture=None, type_site=""):
        nom = TX.nom_organisation(cle_org)
        o, _ = Organisation.objects.update_or_create(nom=nom, defaults={"niveau_id": niveau, "parent": parent, "rang": rang, "actif": actif,
                                                                        "type_site": type_site})
        if fermeture:
            Organisation.objects.filter(pk=o.pk).update(date_desactivation=fermeture)
            o.date_desactivation = fermeture
        orgs[cle_org] = o
        return o

    g = creer(GROUPE, Niveau.GROUP, None, 0)
    for i, (pays, (_, filiales)) in enumerate(PAYS.items()):
        p = creer(pays, Niveau.COUNTRY, g, i)
        for j, filiale in enumerate(filiales):
            f = creer(filiale, Niveau.ENTITY, p, j)
            for k, (site, (_, typ, *_, reglages)) in enumerate((s, v) for s, v in SITES.items() if v[0] == filiale):
                ferme = reglages.get("ferme")
                creer(site, Niveau.SITE, f, k, actif=not ferme, fermeture=FERMETURE_HANNOVER if ferme else None,
                      type_site={"entrepot": "entrepot", "bureau": "bureau"}.get(typ, "autre"))
    return orgs


# Catégories du scope 3 que la démo saisit par site (le modèle les propose au niveau de l'entreprise ; la fiche du KPI le
# permet) : les chiffres de la démo restent ceux de chaque site.
SCOPE3_PAR_SITE = ("GES-S3-ACHATS", "GES-S3-IMMO", "GES-S3-ENERGIE", "GES-S3-FRET-AMONT", "GES-S3-DECHETS",
                   "GES-S3-DEPLACEMENTS", "GES-S3-DOMICILE", "GES-S3-FRET-AVAL", "GES-S3-UTILISATION", "GES-S3-FIN-VIE")


def installer_modeles():
    """Les deux modèles VS de la bibliothèque, installés comme depuis l'écran (niveaux choisis automatiquement), puis dix
    catégories du scope 3 réglées au niveau du site."""
    for f in MODELES:
        a = PQ.analyser(PQ.fourni(f).paquet, fourni=True)
        PQ.appliquer(None, a)
    KPI.objects.filter(code__in=SCOPE3_PAR_SITE).update(granularite_id=Niveau.SITE)


def comptes(mot_de_passe):
    """Comptes de démo. Les cinq comptes de base n'ont pas de langue propre : ils suivent celle de l'installation. Les
    personnes d'un pays gardent la langue de leur pays."""
    return {ident: DC.compte(ident, prenom, nom, role, mot_de_passe, email=f"{ident}@exemple.test", equipe="", langue=langue)
            for ident, prenom, nom, role, langue in COMPTES}


def _filiale(o):
    while o and o.niveau_id != Niveau.ENTITY:
        o = o.parent
    return o


def _pays(o):
    while o and o.niveau_id != Niveau.COUNTRY:
        o = o.parent
    return o


def spoc(k, o, cpt):
    """Contributeur d'une case : SPOC de la filiale pour les sites ; au sommet, Sophie (social) ou Camille."""
    if o.niveau_id == Niveau.SITE:
        return cpt[SPOC_FILIALE[cle(_filiale(o))]]
    if o.niveau_id == Niveau.GROUP and k.code.startswith(("SOC-", "GOV-CA-")):
        return cpt["sophie.marchal"]
    return cpt["contributeur"]


def attributions(cpt, orgs, kpis):
    liens = []
    for k in kpis:
        for o in orgs.values():
            if o.actif and o.niveau_id == k.granularite_id:
                liens.append(Attribution(kpi=k, organisation=o, utilisateur=spoc(k, o, cpt), role=Attribution.Role.CONTRIBUTEUR))
        if k.granularite_id == Niveau.SITE:
            for pays, ident in VALIDATEUR_PAYS.items():
                liens.append(Attribution(kpi=k, organisation=orgs[pays], utilisateur=cpt[ident], role=Attribution.Role.VALIDATEUR))
    Attribution.objects.bulk_create(liens, ignore_conflicts=True, batch_size=2000)


# ---------------------------------------------------------------- valeurs
NA = object()  # marque d'une réponse N/A (avec son commentaire)


def _r(v, d=0):
    return Decimal(str(round(v, d)))


def _variation(site, an, base=1.0):
    """Petite variation reproductible d'une année sur l'autre, propre au site."""
    graine = sum(ord(c) for c in site)
    return base * (1 + ((graine * 37 + an * 11) % 9 - 4) / 100)


def _dechets(site, typ, eff, an):
    """Tableau des déchets par code (tonnes) et ses totaux."""
    lignes, total, dangereux, recycles, reemploi = [], 0.0, 0.0, 0.0, 0.0
    for code, par_salarie, recycle, reemp in DECHETS_TYPE[typ]:
        masse = round(par_salarie * eff * _variation(site + code, an), 1)
        if masse <= 0:
            continue
        r, e = round(masse * recycle, 1), round(masse * reemp, 1)
        lignes.append(f"| {DECHET[code]} | {masse} | {r} | {e} |")
        total, recycles, reemploi = total + masse, recycles + r, reemploi + e
        if " - Hazardous - " in DECHET[code]:
            dangereux += masse
    return lignes, round(total, 1), round(dangereux, 1), round(recycles, 1), round(reemploi, 1)


def _selon_an(an, *valeurs):
    """Valeur propre à l'exercice : une par exercice depuis 2024 (2024, 2025, 2026…) ; au-delà, la dernière."""
    return valeurs[min(an - 2024, len(valeurs) - 1)]


def effectifs(nom, an):
    """(effectif de fin d'exercice, effectif moyen) d'un site ; 0 après sa fermeture."""
    _filiale, typ, *_reste, eff24, eff25, reg = SITES[nom]
    if an == 2024:
        return eff24, eff24
    if an == 2025:
        return eff25, (eff24 + eff25) / 2
    eff = 0 if reg.get("ferme") else round(eff25 * CROISSANCE_2026[typ] * _variation(nom + "n", an))
    return eff, (eff25 + eff) / 2


def _borne(v, avant):
    """Valeur 2026 ramenée à moins de ECART_2026_MAX de sa valeur 2025 (même type : entier, Decimal)."""
    if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)) or not isinstance(avant, (int, float, Decimal)) or not avant:
        return v
    bas, haut = float(avant) * (1 - ECART_2026_MAX), float(avant) * (1 + ECART_2026_MAX)
    if bas <= float(v) <= haut:
        return v
    b = min(max(float(v), bas), haut)
    if isinstance(v, int):
        b = round(b)
        return b if abs(b - avant) <= ECART_2026_MAX * abs(avant) else avant  # petit nombre : celui de 2025
    return Decimal(str(b)).quantize(v) if isinstance(v, Decimal) else b


def _borne_2026(v, avant):
    """Toutes les valeurs numériques d'un site, (valeur, commentaire) compris, bornées par celles de 2025."""
    sortie = {}
    for code, x in v.items():
        a = avant.get(code)
        a = a[0] if isinstance(a, tuple) else a
        sortie[code] = (_borne(x[0], a), x[1]) if isinstance(x, tuple) else _borne(x, a)
    return sortie


def valeurs_site(nom, an):
    """{code: valeur} des KPI saisis au niveau du site pour l'exercice ``an`` (2024, 2025 ou 2026)."""
    filiale, typ, adresse, cp, ville, gps, eff24, eff25, reg = SITES[nom]
    pays = next(p for p, (_, fs) in PAYS.items() if filiale in fs)
    pr = PROFILS[typ]
    eff, eff_moyen = effectifs(nom, an)
    ferme_2025 = reg.get("ferme") and an == 2025
    activite = 0.5 if ferme_2025 else 0.0 if reg.get("ferme") and an > 2025 else 1.0  # Hannover : six mois en 2025, puis rien
    tendance = _selon_an(an, 1.0, 0.96, 0.93)  # efficacité énergétique
    base_eff = eff24
    elec = pr["elec"] * base_eff * activite * tendance * _variation(nom, an)
    gaz = pr["gaz"] * base_eff * activite * tendance * _variation(nom + "g", an)
    v = {
        "GEN-SITE-ADRESSE": adresse, "GEN-SITE-CP": cp, "GEN-SITE-VILLE": ville, "GEN-SITE-PAYS": PAYS[pays][0], "GEN-SITE-GPS": gps,
        "ECO-CA": _r(reg.get("ca", 0) * _selon_an(an, 1, 1.04, 1.07), 1),
        "SOC-EFFECTIF": eff,
    }
    if reg.get("biomasse") and an >= 2025:  # chaudière biomasse depuis mars 2025 : le gaz baisse, le bois arrive
        bois = _r(gaz * 0.8 / 1000, 1)
        v["NRJ-COMB-REN"] = (bois, TX.texte("BIOMASSE")) if an == 2025 else bois
        gaz *= 0.2
        v["GES-S1-AUTRES"] = _r(gaz * 0.00004 + 35, 1)  # CH4 et N2O de la combustion du bois
    else:
        v["NRJ-COMB-REN"] = Decimal(0)
        v["GES-S1-AUTRES"] = _r(reg.get("gpl", 0) * 0.23, 1)
    part_ren = _selon_an(an, *PART_RENOUVELABLE[pays])
    pv = _selon_an(an, *reg.get("pv", (0, 0)))
    v.update({
        "NRJ-ELEC": _r(elec), "NRJ-ELEC-REN": _r(elec * part_ren), "NRJ-ELEC-AUTO": _r(pv), "NRJ-GAZ": _r(gaz),
        "NRJ-FIOUL": _r(pr["fioul"] * base_eff / 180 * activite * _selon_an(an, 1, 0.7, 0.62)),  # baisse avant la sortie du fioul
        "GES-GAZOLE": _r(pr["gazole"] * base_eff * activite * _variation(nom + "d", an)),
        "GES-ESSENCE": _r(pr["essence"] * base_eff * activite * _variation(nom + "e", an)),
        "NRJ-COMB-AUTRES": _r(reg.get("gpl", 0), 1), "NRJ-CHALEUR": _r(reg.get("chaleur", 0) * tendance), "NRJ-FROID": Decimal(0),
        "GES-FUGITIVES": _r(pr["fugitives"] * base_eff * activite * _variation(nom + "f", an), 1),
    })
    if ferme_2025:
        v["NRJ-ELEC"] = (v["NRJ-ELEC"], TX.texte("FERME_ELEC"))
    # eau
    eau = pr["eau"] * base_eff * activite * _variation(nom + "w", an) * _selon_an(an, 1, 0.95, 0.92)
    rejet = eau * pr["rejet"]
    v["EAU-PRELEVEMENT"] = _r(eau)
    v["EAU-REJET-PROCESS"] = _r(rejet)
    v["EAU-STRESS"] = _r(eau - rejet) if reg.get("stress") else Decimal(0)
    # déchets (totaux tirés du tableau par code)
    lignes, total, dangereux, recycles, reemploi = _dechets(nom, typ, eff_moyen * activite, an)
    v["DEC-PAR-CODE"] = "\n".join(lignes)
    v.update({"DEC-TOTAL": _r(total, 1), "DEC-DANGEREUX": _r(dangereux, 1), "DEC-RECYCLES": _r(recycles, 1), "DEC-REEMPLOI": _r(reemploi, 1)})
    # pollution (usines soumises à déclaration)
    if typ == "usine":
        rangs = []
        for polluant, (air, eau_, sol) in POLLUANTS.items():
            f = _selon_an(an, 1, 0.93, 0.9) * _variation(nom + polluant, an)
            rangs.append("| " + " | ".join([polluant] + ["" if x is None else str(round(x * eff_moyen * f)) for x in (air, eau_, sol)]) + " |")
        if reg.get("biomasse") and an >= 2025:
            rangs.append(f"| Particulate matter (PM) | {round(5.5 * eff_moyen)} |  |  |")
        v["POL-REJETS"] = "\n".join(rangs)
    else:
        v["POL-REJETS"] = (NA, TX.texte("POL_NA"))
    # biodiversité
    zone = reg.get("zone")
    if zone:
        v["BIO-SITE-ZONE"] = "À proximité d'une zone sensible pour la biodiversité"
        v["BIO-SITE-ZONE-NOM"] = TX.texte(zone[1])
    else:
        v["BIO-SITE-ZONE"] = "Ni dans ni à proximité d'une zone sensible"
        v["BIO-SITE-ZONE-NOM"] = (NA, TX.texte("ZONE_NA"))
    # effectifs, santé et sécurité, formation
    femmes = round(eff * pr["femmes"] * _variation(nom + "h", an, 1))
    v.update({
        "SOC-EFF-FEMMES": femmes, "SOC-EFF-HOMMES": eff - femmes, "SOC-EFF-GENRE-AUTRE": 0, "SOC-EFF-GENRE-NC": 0,
        "SOC-EFF-CDI": round(eff * pr["cdi"]), "SOC-SAL-CONVENTION": round(eff * CONVENTION[pays]),
        "SOC-ACCIDENTS-ENREG": round(pr["accidents"] * eff_moyen * activite * _selon_an(an, 1.1, 0.85, 0.85)),
        "SOC-DECES": 0, "SOC-HEURES-FORM": _r(pr["formation"] * eff_moyen * activite * _variation(nom + "t", an)),
        "GOV-CORRUPTION": 0, "GOV-AMENDES": Decimal(0),
        "SOC-DEPARTS-CDI": round(eff_moyen * 0.085 * _variation(nom + "r", an)) + (eff24 if ferme_2025 else 0),
        "SOC-INDEPENDANTS": 1 if typ == "bureau" else 0, "SOC-INTERIMAIRES": round(eff * (0.08 if typ in ("usine", "entrepot") else 0.02)),
    })
    eff_encadrement = eff if an <= 2025 or not eff else effectifs(nom, 2025)[0]  # encadrement inchangé en 2026
    managers = max(1, round(eff_encadrement * 0.1)) if eff_encadrement else 0
    v["SOC-MANAGERS-FEMMES"] = round(managers * (pr["femmes"] + 0.08))
    v["SOC-MANAGERS-HOMMES"] = managers - v["SOC-MANAGERS-FEMMES"]
    if ferme_2025:
        v["SOC-EFFECTIF"] = (0, TX.texte("FERME_EFF"))
    # scope 3 (catégories saisies par site)
    s1_s2 = (gaz * 0.227 + elec * 0.1) / 1000
    v.update({
        "GES-S3-ACHATS": _r(pr["achats"] * base_eff * activite * _variation(nom + "1", an), 1),
        "GES-S3-IMMO": _r(pr["immo"] * base_eff * activite, 1), "GES-S3-ENERGIE": _r(s1_s2 * 0.21, 1),
        "GES-S3-FRET-AMONT": _r(pr["fret_amont"] * base_eff * activite * _variation(nom + "4", an), 1),
        "GES-S3-DECHETS": _r(total * 0.025, 1), "GES-S3-DEPLACEMENTS": _r(eff_moyen * activite * (0.6 if typ == "bureau" else 0.15), 1),
        "GES-S3-DOMICILE": _r(eff_moyen * activite * 0.85, 1),
        "GES-S3-FRET-AVAL": _r(pr["fret_aval"] * base_eff * activite * _variation(nom + "9", an), 1),
        "GES-S3-UTILISATION": Decimal(0), "GES-S3-FIN-VIE": _r(pr["fin_vie"] * base_eff * activite, 1),
    })
    if an > 2025:
        v = _borne_2026(v, valeurs_site(nom, 2025))
    return v


def _nombre(v):
    v = v[0] if isinstance(v, tuple) else v
    return float(v) if v is not None and v is not NA else 0.0


def totaux_sites(an):
    """Sommes utiles aux valeurs du groupe (cibles climat, scope 2 marché, effectif)."""
    t = {"s1": 0.0, "s2": 0.0, "mb": 0.0, "eff": 0, "achats": 0.0, "fret": 0.0}
    for nom, (filiale, *_rest) in SITES.items():
        v = valeurs_site(nom, an)
        pays = next(p for p, (_, fs) in PAYS.items() if filiale in fs)
        f = {k: float(x) for k, x in FACTEURS.items()}
        fe = float(FE_ELEC[pays][an])
        n = {k: _nombre(v[k]) for k in ("NRJ-ELEC", "NRJ-ELEC-REN", "NRJ-GAZ", "NRJ-FIOUL", "GES-GAZOLE", "GES-ESSENCE", "GES-FUGITIVES",
                                         "NRJ-CHALEUR", "GES-S3-ACHATS", "GES-S3-FRET-AMONT", "GES-S3-FRET-AVAL", "SOC-EFFECTIF")}
        t["s1"] += (n["NRJ-GAZ"] * f["FE-GAZ"] + n["NRJ-FIOUL"] * f["FE-FIOUL"] + n["GES-GAZOLE"] * f["FE-GAZOLE"]
                    + n["GES-ESSENCE"] * f["FE-ESSENCE"]) / 1000 + n["GES-FUGITIVES"]
        t["s2"] += (n["NRJ-ELEC"] * fe + n["NRJ-CHALEUR"] * f["FE-CHALEUR"]) / 1000
        t["mb"] += ((n["NRJ-ELEC"] - n["NRJ-ELEC-REN"]) * MIX_RESIDUEL[pays] + n["NRJ-CHALEUR"] * f["FE-CHALEUR"]) / 1000
        t["eff"] += int(n["SOC-EFFECTIF"])
        t["achats"] += n["GES-S3-ACHATS"]
        t["fret"] += n["GES-S3-FRET-AMONT"] + n["GES-S3-FRET-AVAL"]
    return t


def valeurs_groupe(an):
    """{code: valeur} des KPI saisis au sommet (informations de l'entreprise, politiques, cibles)."""
    t24, t = totaux_sites(2024), totaux_sites(an)
    ref = {"s1": round(t24["s1"] * 1.06, -1), "s2": round(t24["s2"] * 1.05, -1), "mb": round(t24["mb"] * 1.08, -1)}
    ouverts = sum(1 for _f, *_r, reg in SITES.values() if not (reg.get("ferme") and an > 2025))
    parametres = dict(annee=an, sites=ouverts, renouvellement=2022 if an == 2024 else 2025, recycle=_selon_an(an, 86, 88, 89))
    textes = {k: (TEXTES_SANS_LANGUE[k].format(**parametres) if k in TEXTES_SANS_LANGUE else TX.texte(k, **parametres)) for k in TEXTES}
    oui, non = TypeReponse.OUI, TypeReponse.NON
    cat = [c[1] for c in CATEGORIES_SCOPE3]
    v = {k: s for k, s in textes.items() if not (an == 2024 and k in TEXTES_2024)}
    v.update({
        "GEN-IDENT-TYPE": "LEI", "GEN-IDENT": "969500EXEMPLIADEMO42", "GEN-PERIMETRE": "Rapport établi sur une base consolidée",
        "GEN-FORME-JURIDIQUE": "Société à responsabilité limitée de droit privé",
        "GEN-FORME-AUTRE": (NA, TX.texte("FORME_AUTRE_NA")),
        "ECO-TOTAL-BILAN": Decimal(_selon_an(an, 142_300_000, 151_850_000, 158_400_000)), "GEN-PAYS-PRINCIPAL": "France", "GEN-CERTIF": oui,
        "GEN-FILIALES": "\n".join([
            f"| Exemplia Emballages France | 1 rue de l'Exemple, 69007 Lyon, {TX.nom_organisation('France')} |",
            f"| Exemplia Recyclage | 5 rue de l'Exemple, 69200 Vénissieux, {TX.nom_organisation('France')} |",
            f"| Exemplia Ibérica S.L. | Calle Ejemplo 1, 50197 Zaragoza, {TX.nom_organisation('Espagne')} |",
            f"| Exemplia Deutschland GmbH | Musterstraße 1, 04129 Leipzig, {TX.nom_organisation('Allemagne')} |",
            f"| Exemplia Logistik GmbH | Musterstraße 4, 44147 Dortmund, {TX.nom_organisation('Allemagne')} |"]),
        "GOV-B2-PRATIQUES": oui, "GOV-B2-CLIMAT": oui, "GOV-B2-POLLUTION": oui, "GOV-B2-EAU": oui, "GOV-B2-BIODIV": non if an == 2024 else oui,
        "GOV-B2-CIRCULAIRE": oui, "GOV-B2-PERSONNEL": oui, "GOV-B2-CHAINE": oui, "GOV-B2-COMMUNAUTES": non, "GOV-B2-CONSO": non,
        "GOV-B2-CONDUITE": oui, "GOV-B2-PUBLIC": oui, "GOV-B2-CIBLE": oui,
        "GES-S2-MB": _r(t["mb"], 1),
        "GES-S3-ACTIFS-AMONT": (NA, TX.texte("S3_ACTIFS_AMONT")),
        "GES-S3-TRANSFO": (NA, TX.texte("S3_TRANSFO")),
        "GES-S3-ACTIFS-AVAL": (NA, TX.texte("S3_ACTIFS_AVAL")), "GES-S3-FRANCHISES": (NA, TX.texte("S3_FRANCHISES")),
        "GES-S3-INVEST": (NA, TX.texte("S3_INVEST")),
        "POL-DECLARATION": oui, "POL-PUBLIC": oui, "BIO-SITES": oui, "ECO-CIRCULAIRE": oui,
        "ECO-MATIERES": "\n".join([
            f"| {TX.texte('MAT_RECYCLE')} | {_selon_an(an, 58_400, 60_900, 62_100)} | tonnes (t) |",
            f"| {TX.texte('MAT_KRAFT')} | {_selon_an(an, 9_200, 8_300, 7_600)} | tonnes (t) |",
            f"| {TX.texte('MAT_AMIDON')} | {_selon_an(an, 1_150, 1_180, 1_200)} | tonnes (t) |",
            f"| {TX.texte('MAT_ENCRES')} | {_selon_an(an, 210, 205, 200)} | tonnes (t) |",
            f"| {TX.texte('MAT_FILM')} | {_selon_an(an, 2_300, 1_650, 1_100)} | tonnes (t) |"]),
        "SOC-SALAIRE-MINIMUM": oui, "SOC-ECART-OBLIGATION": oui,
        "SOC-REMU-H-HOMMES": Decimal(_selon_an(an, "23.80", "24.40", "24.90")),
        "SOC-REMU-H-FEMMES": Decimal(_selon_an(an, "21.95", "22.70", "23.35")),
        # module complet
        "STR-ENJEUX": oui, "GES-CIBLES": oui, "GES-ANNEE-REF": 2023, "GES-ANNEE-CIBLE": 2030,
        "GES-S1-REF": _r(ref["s1"], 1), "GES-S1-CIBLE": _r(ref["s1"] * 0.58, 1), "GES-S2-LB-REF": _r(ref["s2"], 1),
        "GES-S2-LB-CIBLE": _r(ref["s2"] * 0.58, 1), "GES-S2-MB-REF": _r(ref["mb"], 1), "GES-S2-MB-CIBLE": _r(ref["mb"] * 0.3, 1),
        "GES-S3-CIBLES": "\n".join([f"| {cat[0]} | {round(t24['achats'] * 1.04, -2):.0f} | {round(t24['achats'] * 0.78, -2):.0f} |",
                                    f"| {cat[3]} | {round(t24['fret'] * 0.55, -1):.0f} | {round(t24['fret'] * 0.4, -1):.0f} |"]),
        "CLI-RISQUES": oui, "CLI-ADAPTATION": oui,
        "SOC-CODE-CONDUITE": oui, "SOC-CODE-ENFANTS": oui, "SOC-CODE-FORCE": oui, "SOC-CODE-TRAITE": oui, "SOC-CODE-DISCRIMINATION": oui,
        "SOC-CODE-ACCIDENTS": oui, "SOC-CODE-AUTRE": oui, "SOC-PLAINTES": oui,
        "SOC-INCIDENTS": non, "SOC-INCIDENT-ENFANTS": non, "SOC-INCIDENT-FORCE": non, "SOC-INCIDENT-TRAITE": non,
        "SOC-INCIDENT-DISCRIMINATION": non, "SOC-INCIDENT-AUTRE": non,
        "SOC-INCIDENT-AUTRE-DESC": (NA, TX.texte("INCIDENT_AUTRE")), "SOC-INCIDENTS-CHAINE": non,
        "SOC-INCIDENTS-CHAINE-DESC": (NA, TX.texte("INCIDENT_CHAINE")),
        "GOV-REV-SECTEURS": non, "GOV-REV-ARMES": Decimal(0), "GOV-REV-TABAC": Decimal(0), "GOV-REV-CHARBON": Decimal(0),
        "GOV-REV-PETROLE": Decimal(0), "GOV-REV-GAZ": Decimal(0), "GOV-REV-CHIMIE": Decimal(0),
        "GOV-ORGANE": oui, "GOV-CA-FEMMES": 2 if an == 2024 else 3, "GOV-CA-HOMMES": 5 if an == 2024 else 4,
    })
    if an == 2024:  # première année suivie dans l'outil ; plan de transition encore à adopter
        v["SOC-EFFECTIF-DEBUT"] = round(t24["eff"] * 0.97)
        v.update({"GES-PLAN-STATUT": "L'adoption d'un plan de transition est prévue", "GES-PLAN-ANNEE": 2025, "GES-PLAN-MOIS": 11,
                  "GES-PLAN-JOUR": 30})
    else:
        v["GEN-INFOS-INCHANGEES"] = "\n".join(f"| {INFOS_INCHANGEES[i][1]} |" for i in (4, 10))
        v["GEN-RAPPORT-LIEN"] = f"https://www.exemplia.example/rapport-durabilite-{an - 1}"
        v.update({"GES-PLAN-STATUT": "Un plan de transition a déjà été adopté",
                  "GES-PLAN-ANNEE": (NA, TX.texte("PLAN_ADOPTE")), "GES-PLAN-MOIS": (NA, TX.texte("PLAN_ADOPTE")),
                  "GES-PLAN-JOUR": (NA, TX.texte("PLAN_ADOPTE"))})
    return v


def valeur_pays(k, nom, an):
    return Decimal(FE_ELEC[nom][an]) if k.code == "FE-ELEC" else None


# ---------------------------------------------------------------- chargement
def _ouverte(o, an):
    """Organisation ouverte pendant l'exercice ``an`` : la règle du calcul (``calcul.ouverte``, dates d'ouverture et de
    fermeture). La démo n'a pas de site ouvert en cours de vie : aucune date d'ouverture n'y est posée."""
    from types import SimpleNamespace

    from collecte.calcul import ouverte

    return ouverte(o, SimpleNamespace(debut=datetime.date(an, 1, 1), fin=datetime.date(an, 12, 31)))


def _texte_ou_nombre(k, brut):
    """(valeur, texte) d'une réponse ; vérifie la valeur comme le ferait la saisie (liste, tableau)."""
    if k.est_numerique:
        return Decimal(str(brut)).quantize(Decimal(1).scaleb(-(k.decimales or 0))) if k.decimales is not None else Decimal(str(brut)), ""
    if k.est_tableau:
        return None, T.lire(str(brut), k.type_reponse)
    if k.choix and str(brut) not in k.choix:
        raise ValueError(f"{k.code} : « {brut} » n'est pas une réponse possible ({k.choix[:3]}…)")
    return None, str(brut)


def campagnes():
    """2024 et 2025, clôturées, pour chaque référentiel installé (une seule période par exercice : les réponses servent
    aux deux référentiels)."""
    par_an = {}
    for an in EXERCICES:
        for ref in Referentiel.objects.order_by("ordre", "code"):
            c, _ = P.campagne(ref, datetime.date(an, ref.mois_debut, 1))
            c.statut, c.seuil_ecart = Campagne.Statut.CLOTUREE, Decimal("0.2")
            c.date_ouverture, c.date_fin_saisie = datetime.date(an + 1, 1, 6), datetime.date(an + 1, 3, 31)
            c.save()
            par_an.setdefault(an, []).append(c)
    return par_an


def _kpis_saisis():
    return [k for k in KPI.objects.filter(actif=True, elements__isnull=False).distinct().select_related("type_saisie", "type_reponse")
            if not k.est_calcule]


def _valeur_brute(k, o, an, groupe, sites):
    """Valeur fictive d'une case (nombre, texte, (valeur, commentaire), NA) ; None : pas de valeur prévue."""
    if o.niveau_id == Niveau.SITE:
        return sites[cle(o)].get(k.code)
    if o.niveau_id == Niveau.COUNTRY:
        return valeur_pays(k, cle(o), an)
    if k.code in FACTEURS:
        return Decimal(FACTEURS[k.code])
    return groupe.get(k.code)


def _ecrire_journal(periode, journal):
    """Historique des saisies : création (valeur, puis statut brouillon) et, pour une case validée, validation ; aux dates
    données (bulk_create pose la date du jour)."""
    ids = {(r.kpi_id, r.organisation_id): r.pk for r in Reponse.objects.filter(periode=periode)}
    entrees = []
    for u, saisie, validation, k, o, v, na in journal:
        rid = str(ids[(k.pk, o.pk)])
        champ, apres = ("non_applicable", True) if na else (("texte" if k.est_texte or k.choix else "valeur"), v)
        entrees += [(Journal(utilisateur=u, action="creation", objet="Reponse", objet_id=rid, champ=champ, avant="", apres=str(apres)[:2000]), saisie),
                    (Journal(utilisateur=u, action="creation", objet="Reponse", objet_id=rid, champ="statut", avant="", apres="brouillon"), saisie)]
        if validation is not None:
            entrees.append((Journal(utilisateur=u, action="modification", objet="Reponse", objet_id=rid, champ="statut", avant="brouillon",
                                    apres="valide"), validation))
    crees = Journal.objects.bulk_create([e for e, _ in entrees], batch_size=2000)
    for e, (_, quand) in zip(crees, entrees):
        e.date = quand
    Journal.objects.bulk_update(crees, ["date"], batch_size=2000)


def historique(par_an, orgs, cpt, ecrire):
    """Toutes les cases saisies et validées par leur SPOC entre janvier et mars de l'année suivante, journal compris."""
    kpis = _kpis_saisis()
    manquantes = []
    for an, cs in par_an.items():
        periode = cs[0].periode
        groupe, sites = valeurs_groupe(an), {nom: valeurs_site(nom, an) for nom in SITES}
        reponses, journal = [], []
        debut = timezone.make_aware(datetime.datetime(an + 1, 1, 12, 9))
        for i, (k, o) in enumerate((k, o) for k in kpis for o in orgs.values() if o.niveau_id == k.granularite_id and _ouverte(o, an)):
            brut = _valeur_brute(k, o, an, groupe, sites)
            if brut is None:
                if any(e.obligatoire for e in k.elements.all()):
                    manquantes.append((an, k.code, cle(o)))
                continue
            commentaire = ""
            if isinstance(brut, tuple):
                brut, commentaire = brut
            na = brut is NA
            valeur, texte = (None, "") if na else _texte_ou_nombre(k, brut)
            u = spoc(k, o, cpt)
            saisie = debut + datetime.timedelta(days=(i * 7) % 55, hours=(i * 5) % 8, minutes=(i * 13) % 60)
            validation = saisie + datetime.timedelta(days=1 + i % 6, hours=2)
            reponses.append(Reponse(periode=periode, kpi=k, organisation=o, valeur=valeur, texte=texte, non_applicable=na,
                                    commentaire=commentaire, statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE,
                                    saisi_par=u, valide_par=u, date_validation=validation))
            journal.append((u, saisie, validation, k, o, texte or valeur, na))
        Reponse.objects.bulk_create(reponses, batch_size=2000)
        _ecrire_journal(periode, journal)
        for c in cs:
            recalculer(c)
        ecrire(f"Year {an}: {len(reponses)} values entered and validated, calculations redone")
    if manquantes:
        ecrire(f"Warning: {len(manquantes)} mandatory cells without a value, e.g. {manquantes[:5]}")
    return manquantes


JUSTIFICATIONS = {  # (KPI ou préfixe, clé de l'organisation) -> clé du texte (``_exemplia_textes``) ; None : toute organisation
    (None, "Lager Hannover"): "J_HANNOVER",
    (None, "Lager Dortmund"): "J_DORTMUND",
    ("FE-", None): "J_FE",
    ("GES-PLAN-", None): "J_PLAN",
    ("NRJ-GAZ", "Werk Leipzig"): "J_LEIPZIG_GAZ",
    ("GOV-CA-", None): "J_CA",
}


def _justification(alerte):
    for (code, org), texte in JUSTIFICATIONS.items():
        if (code is None or alerte.kpi_id.startswith(code)) and (org is None or cle(alerte.organisation) == org):
            return TX.texte(texte)
    return TX.texte("J_DEFAUT")


def alertes_traitees(par_an, cpt):
    """Contrôles de cohérence des exercices clôturés : chaque alerte justifiée par le contributeur, puis acceptée par le
    validateur du pays (l'administratrice au sommet), comme à la clôture d'une vraie campagne."""
    from collecte.coherence import controler
    from collecte.models import Alerte

    for an, cs in par_an.items():
        quand = timezone.make_aware(datetime.datetime(an + 1, 3, 24, 10))
        for c in cs:
            controler(c)
            for a in Alerte.objects.filter(campagne=c).select_related("kpi", "organisation"):
                pays = _pays(a.organisation)
                a.statut, a.justification = Alerte.Statut.ACCEPTEE, _justification(a)
                a.justifie_par, a.date_justification = spoc(a.kpi, a.organisation, cpt), quand
                a.traite_par = cpt[VALIDATEUR_PAYS[cle(pays)]] if pays else cpt["admin"]
                a.date_traitement = quand + datetime.timedelta(days=2)
                a.save()


PREUVES = [  # (exercice, KPI, organisation, nom du fichier, titre)
    (2025, "NRJ-ELEC", "Usine de Villefranche", "facture-electricite-2025-villefranche.pdf", "Récapitulatif annuel d'électricité 2025"),
    (2025, "NRJ-ELEC-REN", "Usine de Villefranche", "garanties-origine-2025.pdf", "Attestation de garanties d'origine 2025"),
    (2025, "NRJ-COMB-REN", "Werk Leipzig", "biomasse-livraisons-2025.pdf", "Livraisons de plaquettes forestières 2025"),
    (2025, "DEC-PAR-CODE", "Fábrica de Zaragoza", "registro-residuos-2025.pdf", "Registro de residuos 2025"),
    (2025, "SOC-ACCIDENTS-ENREG", "Usine de Roanne", "registre-accidents-2025.pdf", "Registre des accidents du travail 2025"),
    (2025, "GEN-CERTIF", GROUPE, "certificats-iso-14001.pdf", "Certificats ISO 14001 en vigueur"),
    (2024, "NRJ-GAZ", "Werk Leipzig", "gasrechnung-2024.pdf", "Gasrechnung 2024 (Jahresabrechnung)"),
    (2024, "EAU-PRELEVEMENT", "Fábrica de Zaragoza", "factura-agua-2024.pdf", "Factura anual de agua 2024"),
]


def _pdf(titre, organisation, exercice):
    """Petit PDF d'une page (document fictif de démonstration)."""
    def echapper(s):
        return s.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    lignes = [titre, TX.texte("PDF_EXERCICE", organisation=organisation, exercice=exercice), TX.texte("PDF_FICTIF")]
    flux = "BT /F1 16 Tf 60 780 Td " + " ".join(f"({echapper(l)}) Tj 0 -28 Td" for l in lignes) + " ET"
    objets = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
              "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
              "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
              f"<< /Length {len(flux.encode('latin-1'))} >>\nstream\n{flux}\nendstream"]
    sortie, positions = b"%PDF-1.4\n", []
    for i, o in enumerate(objets, start=1):
        positions.append(len(sortie))
        sortie += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(sortie)
    sortie += f"xref\n0 {len(objets) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{p:010d} 00000 n \n" for p in positions).encode()
    sortie += f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return sortie


def _fichier_et_titre(nom, titre):
    """Nom de fichier et titre d'un justificatif dans la langue courante (les justificatifs écrits dans la langue d'un pays
    gardent leur nom et leur titre)."""
    if nom in TX.TITRE_PREUVE:
        titre = TX.texte(TX.TITRE_PREUVE[nom])
        if TX.langue() != "fr":
            nom = TX.FICHIERS_ANGLAIS[nom]
    return nom, titre


def preuves(par_an, orgs):
    for an, kpi, org, nom, titre in PREUVES:
        r = Reponse.objects.filter(periode=par_an[an][0].periode, kpi_id=kpi, organisation=orgs[org]).first()
        if r is None:
            continue
        nom, titre = _fichier_et_titre(nom, titre)
        p = Preuve(reponse=r, depose_par=r.saisi_par)
        p.fichier.save(nom, ContentFile(_pdf(titre, r.organisation.nom, an), name=nom), save=False)
        p.save()
        Preuve.objects.filter(pk=p.pk).update(date_depot=r.date_validation)


# ---------------------------------------------------------------- exercice 2026 : campagne ouverte 
# Collecte en cours, avancement inégal : (part des cases saisies, part des cases saisies déjà validées) par organisation.
# Camille (« contributeur ») a encore à faire : rien à Roanne, Mâcon commencé, Villefranche à moitié validé ; Lager
# Dortmund (Anna) n'a pas commencé et a été relancée ; Almacén de Valencia non plus.
AVANCEMENT_2026 = {
    GROUPE: (0.7, 0.6), "France": (1.0, 1.0), "Espagne": (1.0, 0.0), "Allemagne": (0.0, 0.0),
    "Siège de Lyon": (1.0, 1.0), "Usine de Villefranche": (1.0, 0.5), "Usine de Roanne": (0.0, 0.0),
    "Entrepôt de Mâcon": (0.4, 0.0), "Centre de tri de Vénissieux": (1.0, 1.0), "Fábrica de Zaragoza": (0.85, 0.7),
    "Almacén de Valencia": (0.0, 0.0), "Werk Leipzig": (1.0, 1.0), "Büro Frankfurt": (0.6, 0.0), "Lager Dortmund": (0.0, 0.0),
}
# Écarts marqués avec 2025 (seuil de la campagne : 20 %) : facteur et commentaire du contributeur. Sans commentaire, la
# valeur reste en brouillon et l'alerte attend sur la page Cohérence.
ECARTS_2026 = {  # (clé de l'organisation, KPI) -> (facteur, clé du commentaire dans ``_exemplia_textes`` ou vide)
    ("Usine de Villefranche", "EAU-PRELEVEMENT"): (Decimal("1.38"), ""),
    ("Fábrica de Zaragoza", "GES-FUGITIVES"): (Decimal("1.6"), "ECART_FUITE"),
    ("Siège de Lyon", "NRJ-CHALEUR"): (Decimal("0.75"), "ECART_CHALEUR"),
}
# Alertes de cohérence 2026 (page Cohérence) : l'écart de Villefranche ci-dessus et les deux facteurs d'émission de
# l'électricité mis à jour (paramètre hérité modifié) ; celui de la France est déjà justifié, en attente du validateur.
JUSTIFIEES_2026 = {("FE-ELEC", "France"): "J_FE_ELEC_2026"}  # (KPI, clé de l'organisation) -> clé du texte
ALERTES_A_TRAITER_2026 = 2  # écart de Villefranche, facteur de l'Espagne
PREUVES_2026 = [  # (KPI, organisation, nom du fichier, titre)
    ("NRJ-ELEC", "Siège de Lyon", "factures-electricite-2026-lyon.pdf", "Factures d'électricité 2026 (janvier à octobre)"),
    ("SOC-ACCIDENTS-ENREG", "Werk Leipzig", "unfallregister-2026.pdf", "Unfallregister 2026"),
]
RELANCEE_2026 = "anna.schmidt"  # relancée par téléphone il y a trois jours (« Marquer relancé »)


def _tirage(*cles):
    """Nombre entre 0 et 1, le même à chaque chargement (crc32, pas ``hash`` : il change d'un lancement à l'autre)."""
    return zlib.crc32("|".join(str(c) for c in cles).encode("utf-8")) / 2 ** 32


def campagnes_en_cours():
    """Exercice 2026 ouvert pour chaque référentiel installé (une seule période) : saisie ouverte depuis trois semaines,
    date limite dans dix jours (dates relatives au jour du chargement, pour que la démo reste « en cours »)."""
    aujourd_hui = timezone.localdate()
    cs = []
    for ref in Referentiel.objects.order_by("ordre", "code"):
        c, _ = P.campagne(ref, datetime.date(EN_COURS, ref.mois_debut, 1))
        c.statut, c.seuil_ecart = Campagne.Statut.OUVERTE, Decimal("0.2")
        c.date_ouverture = aujourd_hui - datetime.timedelta(days=21)
        c.date_fin_saisie = aujourd_hui + datetime.timedelta(days=10)
        c.save()
        cs.append(c)
    return cs


def saisie_en_cours(cs, orgs, cpt, ecrire):
    """2026 : une partie des cases saisies par leur SPOC ces trois dernières semaines, validées ou en brouillon (voir
    AVANCEMENT_2026), avec les mêmes valeurs fictives que 2024 et 2025 prolongées d'un an ; puis calculs et contrôles
    de cohérence (alertes à traiter)."""
    periode = cs[0].periode
    groupe, sites = valeurs_groupe(EN_COURS), {nom: valeurs_site(nom, EN_COURS) for nom in SITES}
    maintenant = timezone.now()
    reponses, journal = [], []
    for k, o in ((k, o) for k in _kpis_saisis() for o in orgs.values() if o.niveau_id == k.granularite_id and _ouverte(o, EN_COURS)):
        cle_org = cle(o)
        part_saisie, part_validee = AVANCEMENT_2026.get(cle_org, (0.0, 0.0))
        if _tirage("saisie", k.code, cle_org) >= part_saisie:
            continue
        brut = _valeur_brute(k, o, EN_COURS, groupe, sites)
        if brut is None:
            continue
        commentaire = ""
        if isinstance(brut, tuple):
            brut, commentaire = brut
        na = brut is NA
        valeur, texte = (None, "") if na else _texte_ou_nombre(k, brut)
        ecart = ECARTS_2026.get((cle_org, k.code))
        if ecart and valeur is not None:
            valeur, commentaire = _texte_ou_nombre(k, valeur * ecart[0])[0], TX.texte(ecart[1]) if ecart[1] else ""
        valide = _tirage("validation", k.code, cle_org) < part_validee and not (ecart and not commentaire)
        u = spoc(k, o, cpt)
        saisie = maintenant - datetime.timedelta(days=1 + 19 * _tirage("jour", k.code, cle_org), hours=8 * _tirage("heure", k.code, cle_org))
        validation = min(saisie + datetime.timedelta(hours=2 + 30 * _tirage("delai", k.code, cle_org)), maintenant) if valide else None
        reponses.append(Reponse(periode=periode, kpi=k, organisation=o, valeur=valeur, texte=texte, non_applicable=na,
                                commentaire=commentaire, statut=Reponse.Statut.VALIDE if valide else Reponse.Statut.BROUILLON,
                                origine=Reponse.Origine.SAISIE, saisi_par=u, valide_par=u if valide else None, date_validation=validation))
        journal.append((u, saisie, validation, k, o, texte or valeur, na))
    Reponse.objects.bulk_create(reponses, batch_size=2000)
    _ecrire_journal(periode, journal)
    # brouillon : « mis à jour le » = date de sa saisie dans le journal (bulk_create pose l'heure du chargement)
    ids = {(r.kpi_id, r.organisation_id): r.pk for r in Reponse.objects.filter(periode=periode)}
    for u, saisie, validation, k, o, v, na in journal:
        if validation is None:
            Reponse.objects.filter(pk=ids[(k.pk, o.pk)]).update(date_maj=saisie)
    for c in cs:
        recalculer(c)
    from collecte.coherence import controler

    for c in cs:
        controler(c)
    from collecte.models import Alerte

    for (code, org), cle_texte in JUSTIFIEES_2026.items():  # justifiée par le contributeur, en attente du validateur
        for a in Alerte.objects.filter(campagne__in=cs, kpi_id=code, organisation=orgs[org], statut=Alerte.Statut.OUVERTE):
            a.statut, a.justification = Alerte.Statut.JUSTIFIEE, TX.texte(cle_texte)
            a.justifie_par, a.date_justification = spoc(a.kpi, a.organisation, cpt), maintenant - datetime.timedelta(days=2)
            a.save()
    validees = sum(1 for r in reponses if r.statut == Reponse.Statut.VALIDE)
    ecrire(f"Year {EN_COURS} (open): {len(reponses)} values entered, {validees} of them validated")
    return reponses


def preuves_en_cours(cs, orgs):
    for kpi, org, nom, titre in PREUVES_2026:
        r = Reponse.objects.filter(periode=cs[0].periode, kpi_id=kpi, organisation=orgs[org]).first()
        if r is None:
            continue
        nom, titre = _fichier_et_titre(nom, titre)
        p = Preuve(reponse=r, depose_par=r.saisi_par)
        p.fichier.save(nom, ContentFile(_pdf(titre, r.organisation.nom, EN_COURS), name=nom), save=False)
        p.save()
        Preuve.objects.filter(pk=p.pk).update(date_depot=r.date_validation or r.date_maj)


def relance_en_cours(cs, cpt):
    """Une relance notée à la main (téléphone) il y a trois jours par l'administratrice : la page Relances a un historique."""
    from collecte import relances as R
    from collecte.models import Relance

    personne = cpt[RELANCEE_2026]
    for af in R.a_faire(cs, destinataires=[personne.pk]):
        r = R.marquer(af, cpt["admin"])
        quand = timezone.now() - datetime.timedelta(days=3, hours=2)
        Relance.objects.filter(pk=r.pk).update(date=quand)
        Journal.objects.filter(action="relance_manuelle", objet_id=str(personne.pk)).update(date=quand)


def _poser_traductions(modele, pk, champ, par_langue):
    """Écrit les textes ``par_langue`` ({langue: texte}) dans les traductions de l'objet, sans toucher à ce qui existe déjà ;
    écriture directe (``update``), sans passer par ``save`` : ni recalcul, ni journal."""
    obj = modele.objects.filter(pk=pk).first()
    if obj is None:
        return
    trad = {lg: dict(d or {}) for lg, d in (obj.traductions or {}).items()}
    change = False
    for lg, texte in par_langue.items():
        if texte and not trad.setdefault(lg, {}).get(champ):
            trad[lg][champ] = texte
            change = True
    if change:
        modele.objects.filter(pk=pk).update(traductions=trad)


def _langues_bib(textes):
    return dict(zip(BIB.LANGUES, textes))


def traduire_bibliotheque():
    """Libellés de la norme VS dans les sept langues (voir ``_exemplia_bibliotheque``). Le modèle de la bibliothèque porte le
    français et l'anglais ; la démo ajoute les cinq autres langues pour les noms, puis reprend l'anglais, qui est le texte de
    la norme, là où une langue n'a rien (descriptions, noms officiels des listes) : le repli ne tombe jamais sur le français
    dans une autre langue que le français."""
    from parametres.models import Unite
    from referentiel.models import Theme

    for code, noms in BIB.KPI.items():
        _poser_traductions(KPI, code, "libelle", _langues_bib(noms))
    for theme in Theme.objects.all():
        if theme.code in BIB.THEMES:
            _poser_traductions(Theme, theme.pk, "nom", _langues_bib(BIB.THEMES[theme.code]))
    for code, (noms, descriptions) in BIB.REFERENTIELS.items():
        _poser_traductions(Referentiel, code, "nom", _langues_bib(noms))
        _poser_traductions(Referentiel, code, "description", _langues_bib(descriptions))
    for code, noms in BIB.TYPES.items():
        _poser_traductions(TypeReponse, code, "libelle", _langues_bib(noms))
    for code, code_kpi in BIB.TYPE_COMME_KPI.items():
        _poser_traductions(TypeReponse, code, "libelle", _langues_bib(BIB.KPI[code_kpi]))
    for code, noms in BIB.UNITES.items():
        _poser_traductions(Unite, code, "libelle", _langues_bib(noms))
        if code in BIB.SYMBOLES_EN_MOTS:  # symbole qui est un mot (« année », « cas »), pas une abréviation internationale
            _poser_traductions(Unite, code, "symbole", _langues_bib(noms))
    _completer_en_anglais()


def _completer_en_anglais(referentiels=None):
    """Listes de choix par position, puis, pour tout ce qui reste sans texte dans une langue, l'anglais. ``referentiels`` :
    codes des référentiels dont on complète les noms, thèmes, KPI et descriptions (les ESRS, installés après la norme VS) ;
    sinon tout. Sans effet sur ce qui a déjà un texte : on peut le rappeler."""
    from parametres.models import Unite
    from referentiel.models import Description, Theme

    for type_ in TypeReponse.objects.all():  # listes de choix : par position, puis anglais pour les longues listes
        trad = {lg: dict(d or {}) for lg, d in (type_.traductions or {}).items()}
        nb = len(type_.choix)
        en = list((trad.get("en") or {}).get("valeurs") or [])
        for i, lg in enumerate(BIB.LANGUES):
            if (trad.get(lg) or {}).get("valeurs"):
                continue
            if type_.code in BIB.VALEURS:
                valeurs = list(BIB.VALEURS[type_.code][i])
            elif en and nb:
                valeurs = list(en)
                if type_.code == "VS-PAYS":
                    for cle_pays, noms in BIB.PAYS.items():
                        if cle_pays in type_.choix:
                            valeurs[type_.choix.index(cle_pays)] = noms[i]
            else:
                continue
            trad.setdefault(lg, {})["valeurs"] = valeurs
        # colonnes d'un tableau : un libellé par langue, d'après le libellé anglais
        colonnes = type_.colonnes
        for c in colonnes or []:
            lib = c.get("libelle") if isinstance(c, dict) else None
            if isinstance(lib, dict) and lib.get("en") in BIB.COLONNES:
                for lg, texte in zip(BIB.LANGUES, BIB.COLONNES[lib["en"]]):
                    lib.setdefault(lg, texte)
            elif isinstance(lib, dict) and lib.get("en"):  # colonne d'un tableau ESRS : l'anglais, texte de la norme
                for lg in BIB.LANGUES:
                    lib.setdefault(lg, lib["en"])
        TypeReponse.objects.filter(pk=type_.pk).update(traductions=trad, colonnes=colonnes)
    # ce qui reste sans texte dans une langue reprend l'anglais (noms, descriptions)
    portee = {
        KPI: KPI.objects.filter(elements__referentiel__code__in=referentiels).distinct() if referentiels else KPI.objects.all(),
        Theme: Theme.objects.filter(referentiel__code__in=referentiels) if referentiels else Theme.objects.all(),
        Referentiel: Referentiel.objects.filter(code__in=referentiels) if referentiels else Referentiel.objects.all(),
        TypeReponse: TypeReponse.objects.all(), Unite: Unite.objects.all()}
    for modele, champs in ((KPI, ("libelle",)), (Theme, ("nom",)), (Referentiel, ("nom", "description")), (TypeReponse, ("libelle",)),
                           (Unite, ("libelle", "symbole"))):
        for obj in portee[modele]:
            en = (obj.traductions or {}).get("en") or {}
            for champ in champs:
                if en.get(champ):
                    _poser_traductions(modele, obj.pk, champ, {lg: en[champ] for lg in BIB.LANGUES})
    existantes = set(Description.objects.values_list("kpi_id", "categorie_id", "langue"))
    Description.objects.bulk_create([Description(kpi_id=k, categorie_id=c, langue="en", texte=t)
                                     for (k, c), t in DESCRIPTIONS_EN.items() if (k, c, "en") not in existantes
                                     and (k, c, "fr") in existantes])  # l'anglais qui manque au modèle fourni
    existantes = set(Description.objects.values_list("kpi_id", "categorie_id", "langue"))
    anglais = Description.objects.filter(langue="en")
    if referentiels:
        anglais = anglais.filter(kpi__in=portee[KPI])
    manquantes = [Description(kpi_id=k, categorie_id=c, langue=lg, texte=t)
                  for k, c, t in anglais.values_list("kpi_id", "categorie_id", "texte")
                  for lg in BIB.LANGUES if (k, c, lg) not in existantes]
    Description.objects.bulk_create(manquantes, batch_size=2000)


def installer_esrs():
    """Les onze modèles ESRS de la bibliothèque (CSRD), installés comme depuis l'écran, SANS aucune valeur et sans campagne :
    ils paraissent installés dans la bibliothèque et dans les Paramètres, prêts à être mis dans une campagne. À appeler quand
    tout le reste de la démo est fait : aucune campagne, saisie ni attribution de la démo ne les voit. Renvoie leurs codes."""
    codes = []
    for f in ESRS:
        paquet = PQ.fourni(f).paquet
        PQ.appliquer(None, PQ.analyser(paquet, fourni=True), sans_recalcul=True)  # aucune campagne ne demande ces KPI
        codes.append(paquet.code)
    return codes


def traduire_esrs(codes):
    """Noms et descriptions des onze modèles ESRS dans les sept langues (fichiers de langue ``referentiels.socle.<code>.*``,
    déjà complets dans les sept langues), puis l'anglais pour tout ce que les modèles ne portent qu'en français et en anglais
    (thèmes, KPI, listes, colonnes, descriptions) : le repli ne tombe jamais sur le français dans une autre langue."""
    from parametres import libelles as LB

    for code in codes:
        for champ in ("nom", "description"):
            _poser_traductions(Referentiel, code, champ, {
                lg: LB.table(lg).get(f"referentiels.socle.{code.lower()}.{champ}") for lg in ("fr", "en", *BIB.LANGUES)})
    _completer_en_anglais(codes)
    if TX.langue() != "fr":  # règles de cohérence des ESRS : un seul texte, celui de la langue de la démo ; faute de mieux, l'anglais
        from collecte.models import RegleCoherence
        from referentiel.bibliotheque import socles as S

        from referentiel.bibliotheque import traductions as TR
        from referentiel.bibliotheque.documentation import nom_regle

        for nom_fr, r in S.REGLES.items():
            if nom_fr not in TX.REGLES:
                nom_en = nom_regle(nom_fr)  # règles des anciens socles : nom anglais de la table de la documentation
                description_en = r[3][1] if isinstance(r[3], (tuple, list)) else nom_en
                # dans la langue de la démo si les traductions des ESRS ont la règle, sinon l'anglais
                RegleCoherence.objects.filter(nom=nom_fr).update(
                    nom=TR.traduire_nom("esrs", TX.langue(), nom_en) or nom_en,
                    description=TR.traduire_description("esrs", TX.langue(), description_en) or description_en)
        # Une règle que la norme VS et les ESRS ont en commun : la règle de la VS a déjà été traduite (``traduire_regles``), donc
        # l'installation des ESRS en a recréé une sous son nom français. Même contrôle : on ne garde que la règle traduite.
        RegleCoherence.objects.filter(nom__in=list(TX.REGLES)).delete()


def traduire_regles():
    """Nom et description des règles de cohérence dans la langue de la démo : une règle n'a pas de traductions, elle porte le
    texte de la langue de l'installation (les noms français sont les clés de ``TX.REGLES``)."""
    from collecte.models import RegleCoherence

    langue = TX.langue()
    if langue == "fr":
        return
    for nom_fr, textes in TX.REGLES.items():
        nom, description = textes[langue]
        RegleCoherence.objects.filter(nom=nom_fr).update(nom=nom, description=description)


def charger(mot_de_passe, ecrire, langue="fr"):
    """Toute la démo Exemplia (base vide, dans une transaction ouverte par l'appelant), dans la langue ``langue``."""
    with TX.regler(langue):
        return _charger(mot_de_passe, ecrire)


def _charger(mot_de_passe, ecrire):
    langues()
    niveaux()
    orgs = organisations()
    installer_modeles()
    traduire_bibliotheque()
    traduire_regles()
    cpt = comptes(mot_de_passe)
    kpis = [k for k in KPI.objects.filter(actif=True).select_related("type_saisie") if not k.est_calcule]
    attributions(cpt, orgs, kpis)
    par_an = campagnes()
    ecrire(f"Organisations: {len(orgs)} · KPIs: {KPI.objects.count()} · levels: {' › '.join(n.nom for n in N.tous())}")
    historique(par_an, orgs, cpt, ecrire)
    alertes_traitees(par_an, cpt)
    preuves(par_an, orgs)
    en_cours = campagnes_en_cours()
    saisie_en_cours(en_cours, orgs, cpt, ecrire)
    preuves_en_cours(en_cours, orgs)
    relance_en_cours(en_cours, cpt)
    esrs = installer_esrs()  # en dernier : aucune campagne, saisie ni attribution de la démo ne les voit
    traduire_esrs(esrs)
    ecrire(f"ESRS templates installed without values: {len(esrs)}")
    return orgs, cpt
