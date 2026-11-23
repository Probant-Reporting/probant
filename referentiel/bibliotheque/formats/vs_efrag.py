"""Classeur officiel de la norme volontaire VS (ex-VSME) : modèle numérique 2.0.0 de l'EFRAG (licence MIT, © 2025 EFRAG).

Correspondance entre les KPI des modèles VS_BASE et VS_COMPLET et les cellules de saisie du classeur. Règles tirées de la
note explicative de l'EFRAG et du classeur lui-même :

- on n'écrit que dans les cellules de saisie (déverrouillées, sans formule) ; le classeur calcule le reste (totaux, taux,
  écart de rémunération, contrôles « OK / MISSING VALUE », statut COMPLETE / INCOMPLETE) quand on l'ouvre ;
- exception permise par la note : une cellule calculée à partir d'aides que l'on n'utilise pas reçoit la valeur finale
  (énergie des combustibles, totaux de déchets, pourcentages de déchets détournés) : ``remplace=True`` ;
- une cellule vide n'est pas publiée : une valeur absente dans l'outil laisse la cellule telle quelle ;
- les listes attendent leurs valeurs anglaises exactes (quelle que soit la langue d'affichage), les cases à cocher VRAI /
  FAUX ; les cases « jaunes » (« L'entreprise a-t-elle… ? ») ne sont pas publiées mais ouvrent les informations : on les
  coche quand l'information existe ;
- unités : énergie en MWh, émissions en tCO2e, pourcentages en fraction (0,25 = 25 %) ; montants dans la devise du
  rapport (cellule D5) : la monnaie de référence de l'espace (parametres/monnaies.py, l'euro par défaut). Un montant
  n'est écrit que si l'unité de son KPI est celle du modèle dans cette monnaie (« M$ » pour « M€ » en dollars) ; sinon la
  cellule reste vide et le rapport le dit : aucune conversion, jamais un chiffre dans une autre monnaie ou à une autre
  échelle.

Chaque cellule est repérée par son adresse et, quand elle en a un, par son nom Excel (celui de l'élément XBRL) : le test
vérifie les deux sur le classeur livré, si bien qu'une nouvelle version du classeur qui déplace une ligne est détectée.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from ..definitions import vs_base, vs_complet
from ..definitions._vs_listes import INFOS_INCHANGEES, OMISSIONS

CODE = "vs_efrag"
FICHIER = "vs_digital_template_2.0.0.xlsx"
VERSION = "2.0.0"
TAXONOMIE = "https://xbrl.efrag.org/taxonomy/vs/2026-10-16/vs-all.xsd"
REFERENTIELS = ("VS_BASE", "VS_COMPLET")
NOM = {"fr": "Classeur officiel de l'EFRAG (norme volontaire VS)", "en": "EFRAG official workbook (Voluntary Standard VS)",
       "es": "Libro oficial del EFRAG (norma voluntaria VS)"}
LANGUES = {"en": "English - Official [en]", "fr": "French - Reviewed translation by French Standard Setter [fr]",
           "es": "Spanish - Reviewed translation by Spanish Standard Setter [es]"}
GI, ENV, SOC, GOV, LANGUE = ("General Information", "Environmental Disclosures", "Social Disclosures", "Governance Disclosures",
                             "Language Selection")
SOMMAIRE = "Table of Contents & Validation"  # cases « information classifiée ou sensible » (colonne D)
OPTION_A, OPTION_B = "Option A (Basic Module only)", "Option B (Basic Module and Comprehensive Module)"
OUI, NON = "YES", "NO"  # liste enum_ListYesNo
VRAI, FAUX = "True", "False"  # liste enum_list_true_false
LIGNES_SITES = (402, 501)  # B1 – liste des sites (ID en C, déjà numérotés 1 à 100)
LIGNES_PAYS = (29, 128)  # B8 – salariés par pays du contrat
LIGNES_BIODIVERSITE = (191, 290)  # B5 – sites dans ou près d'une zone sensible
LIGNES_NACE = (178, 277)  # B1 – codes NACE
LIGNES_FILIALES = (288, 387)  # B1 – filiales (ID en C, déjà numérotés)
LIGNES_INCHANGEES = (22, 121)  # B1 – informations inchangées depuis le rapport précédent
LIGNES_POLLUANTS = (74, 173)  # B4 – rejets par polluant de la liste européenne
LIGNES_AUTRES_POLLUANTS = (174, 184)  # B4 – autres polluants
LIGNES_DECHETS = (316, 415)  # B7 – déchets par code
LIGNES_MATIERES = (432, 531)  # B7 – flux de matières
LANGUES_INCHANGEES = {"en": 0, "fr": 1, "es": 2}  # colonne de INFOS_INCHANGEES selon la langue d'affichage du classeur

# valeurs anglaises (exactes du classeur) des listes de choix des modèles VS, par code du type de réponse
VALEURS = {t[0]: t[3]["en"] for t in vs_base.TYPES_REPONSE + vs_complet.TYPES_REPONSE if t[2] == "liste"}


def _montants():
    """{code d'un KPI : unité en euros dans le modèle} des KPI de montant des modèles VS (paquets livrés)."""
    import json

    from . import DOSSIER

    sortie = {}
    for nom in ("vs_base.json", "vs_complet.json"):
        p = json.loads((DOSSIER.parent / nom).read_text(encoding="utf-8"))
        sortie.update({k["code"]: k["unite"] for k in p["kpis"] if "€" in (k.get("unite") or "")})
    return sortie


MONTANTS = _montants()


@dataclass
class Cellule:
    module: str  # B1…C9 : rubrique de la norme (rapport d'export)
    onglet: str
    cellule: str
    valeur: object  # constante, ou fonction(contexte) -> valeur (None : rien à écrire)
    codes: tuple = ()  # KPI dont vient la valeur
    nom: str = ""  # nom Excel (élément XBRL) attendu sur la cellule, s'il y en a un
    remplace: bool = False  # la cellule porte une formule que l'on remplace par la valeur finale
    obligatoire: bool = True  # pour le rapport : valeur attendue quand le module est déclaré
    verrouillee: bool = False  # cellule de saisie verrouillée par erreur dans le classeur 2.0.0 (« autres informations »)
    sauf_si: str = ""  # tableau qui, rempli, fait calculer la cellule par le classeur : elle n'est alors pas « manquante »


@dataclass
class Bloc:
    """Tableau à lignes variables (sites, pays, zones sensibles, codes NACE) : fonction(contexte) -> {cellule: valeur}."""
    module: str
    onglet: str
    remplir: object
    codes: tuple = ()
    lignes: tuple = (0, 0)
    colonnes: tuple = ()
    nom: str = ""  # nom Excel du tableau
    remplace: tuple = ()  # colonnes dont les cellules portent une formule que l'on remplace (coordonnées GPS)


@dataclass
class Resultat:
    ecritures: dict = field(default_factory=dict)  # {(onglet, cellule): valeur}
    formules: set = field(default_factory=set)  # {(onglet, cellule)} dont la formule est remplacée
    remplies: list = field(default_factory=list)  # [(module, onglet, cellule, codes)]
    manquantes: list = field(default_factory=list)  # [(module, codes)] : valeur attendue absente
    messages: list = field(default_factory=list)  # [(clé du texte, valeurs)] : remarques (valeur non reprise, tableau tronqué…)


# ---------------------------------------------------------------- fonctions de valeur
def _fois(v, facteur):
    return None if v is None else Decimal(v) * Decimal(str(facteur))


def nombre(code, facteur=1):
    return lambda c: _fois(c.nombre(code), facteur)


def positif(code):
    """Nombre seulement s'il dépasse 0 (le classeur refuse 0 là où il demande « si l'entreprise en a »)."""
    return lambda c: c.nombre(code) if (c.nombre(code) or 0) > 0 else None


def case(code):
    return lambda c: c.oui(code)


def oui_non(code):
    return lambda c: None if c.oui(code) is None else (OUI if c.oui(code) else NON)


def vrai_faux(code):
    return lambda c: None if c.oui(code) is None else (VRAI if c.oui(code) else FAUX)


def texte(code):
    return lambda c: c.texte(code)


def liste(code, type_reponse):
    def valeur(c):
        i = c.choix(code)
        return VALEURS[type_reponse][i] if i is not None and i < len(VALEURS[type_reponse]) else None
    return valeur


def sans_detail(code_tableau, valeur):
    """Valeur écrite seulement si le tableau de détail est vide (sinon le classeur calcule lui-même la cellule)."""
    return lambda c: None if c.tableau(code_tableau) else valeur(c)


def annee(code):
    return lambda c: None if c.nombre(code) is None else str(int(c.nombre(code)))


def une_valeur(*codes):
    """Case « l'entreprise a-t-elle… ? » cochée dès qu'une des valeurs existe (sinon la case reste telle quelle)."""
    return lambda c: True if any(c.nombre(k) is not None or c.texte(k) for k in codes) else None


def somme(*codes, facteur=1):
    """Somme : le premier KPI est exigé, les suivants comptent 0 s'ils n'ont pas de valeur."""
    def valeur(c):
        v = c.nombre(codes[0])
        return None if v is None else _fois(v + sum((c.nombre(k) or 0) for k in codes[1:]), facteur)
    return valeur


def difference(code_total, code_part, facteur=1):
    def valeur(c):
        t, p = c.nombre(code_total), c.nombre(code_part)
        return None if t is None or p is None else _fois(t - p, facteur)
    return valeur


def part(code_part, code_total):
    def valeur(c):
        t, p = c.nombre(code_total), c.nombre(code_part)
        return None if not t or p is None else p / t
    return valeur


# ---------------------------------------------------------------- cellules
SCOPE3 = ("GES-S3-ACHATS", "GES-S3-IMMO", "GES-S3-ENERGIE", "GES-S3-FRET-AMONT", "GES-S3-DECHETS", "GES-S3-DEPLACEMENTS",
          "GES-S3-DOMICILE", "GES-S3-ACTIFS-AMONT", "GES-S3-FRET-AVAL", "GES-S3-TRANSFO", "GES-S3-UTILISATION", "GES-S3-FIN-VIE",
          "GES-S3-ACTIFS-AVAL", "GES-S3-FRANCHISES", "GES-S3-INVEST")
B2_ENJEUX = ("CLIMAT", "POLLUTION", "EAU", "BIODIV", "CIRCULAIRE", "PERSONNEL", "CHAINE", "COMMUNAUTES", "CONSO", "CONDUITE")
C6_CONTENUS = ("ENFANTS", "FORCE", "TRAITE", "DISCRIMINATION", "ACCIDENTS", "AUTRE")
C7_INCIDENTS = ("ENFANTS", "FORCE", "TRAITE", "DISCRIMINATION", "AUTRE")

CELLULES = [
    # informations sur le rapport (obligatoires pour la conversion en XBRL)
    Cellule("Rapport", LANGUE, "G7", lambda c: LANGUES.get(c.langue, LANGUES["en"]), nom="template_selected_display_language"),
    Cellule("Rapport", GI, "D3", lambda c: c.nom_entreprise, nom="template_reporting_entity_name"),
    Cellule("Rapport", GI, "D4", liste("GEN-IDENT-TYPE", "VS-IDENTIFIANT"), ("GEN-IDENT-TYPE",), "template_reporting_entity_identifier_scheme"),
    Cellule("Rapport", GI, "E4", texte("GEN-IDENT"), ("GEN-IDENT",), "template_reporting_entity_identifier"),
    Cellule("Rapport", GI, "D5", lambda c: c.monnaie),  # code ISO 4217 (liste enum_ListOfCurrencies du classeur)
    Cellule("Rapport", GI, "D6", lambda c: str(c.debut.year)),
    Cellule("Rapport", GI, "D7", lambda c: str(c.debut.month)),
    Cellule("Rapport", GI, "D8", lambda c: str(c.debut.day)),
    Cellule("Rapport", GI, "D10", lambda c: str(c.fin.year)),
    Cellule("Rapport", GI, "D11", lambda c: str(c.fin.month)),
    Cellule("Rapport", GI, "D12", lambda c: str(c.fin.day)),
    Cellule("Rapport", GI, "C17", texte("GEN-INTRO"), ("GEN-INTRO",), "IntroductionAndOrEntitySpecificInformation", obligatoire=False),
    Cellule("B1", GI, "E21", lambda c: True if c.tableau("GEN-INFOS-INCHANGEES") else None, ("GEN-INFOS-INCHANGEES",),
            "ReportContainsDisclosuresFromThePreviousReportingPeriodThatRemainUnchanged", obligatoire=False),
    Cellule("B1", GI, "E122", texte("GEN-RAPPORT-LIEN"), ("GEN-RAPPORT-LIEN",), "LinkToPreviousReportContainingDisclosuresThatRemainUnchanged",
            obligatoire=False),
    # B1
    Cellule("B1", GI, "E125", lambda c: OPTION_B if c.option_b else OPTION_A, nom="BasisForPreparation"),
    Cellule("B1", GI, "E126", texte("GEN-CONFORMITE"), ("GEN-CONFORMITE",), "ExplicitStatementOfCompliance"),
    Cellule("B1", GI, "E175", liste("GEN-PERIMETRE", "VS-PERIMETRE"), ("GEN-PERIMETRE",), "BasisForReporting"),
    Cellule("B1", GI, "E176", liste("GEN-FORME-JURIDIQUE", "VS-FORME-JURIDIQUE"), ("GEN-FORME-JURIDIQUE",), "UndertakingsLegalForm"),
    Cellule("B1", GI, "E177", texte("GEN-FORME-AUTRE"), ("GEN-FORME-AUTRE",), "OtherUndertakingsLegalForm", obligatoire=False),
    Cellule("B1", GI, "E278", nombre("ECO-TOTAL-BILAN"), ("ECO-TOTAL-BILAN",), "Assets"),
    Cellule("B1", GI, "E279", nombre("ECO-CA", 1_000_000), ("ECO-CA",), "Turnover"),
    Cellule("B1", GI, "E280", nombre("SOC-EFFECTIF"), ("SOC-EFFECTIF",), "NumberOfEmployees"),
    Cellule("B1", GI, "E281", "At the end of the reporting period", nom="EmployeeCountingMethodology"),
    Cellule("B1", GI, "E282", "Headcount", nom="TypeOfNumberOfEmployees"),
    Cellule("B1", GI, "E283", liste("GEN-PAYS-PRINCIPAL", "VS-PAYS"), ("GEN-PAYS-PRINCIPAL",),
            "CountryOfPrimaryOperationsAndLocationOfSignificantAssets"),
    Cellule("B1", GI, "E392", case("GEN-CERTIF"), ("GEN-CERTIF",)),
    Cellule("B1", GI, "E393", texte("GEN-CERTIF-DESC"), ("GEN-CERTIF-DESC",), "DescriptionOfSustainabilityRelatedCertificationsOrLabels",
            obligatoire=False),
    Cellule("B1", GI, "C531", texte("GEN-AUTRES"), ("GEN-AUTRES",), "DisclosureOfAnyOtherGeneralAndOrEntitySpecificInformation",
            obligatoire=False, verrouillee=True),
    # B2
    Cellule("B2", GI, "C508", case("GOV-B2-PRATIQUES"), ("GOV-B2-PRATIQUES",)),
] + [
    Cellule("B2", GI, f"{col}508", case(f"GOV-B2-{e}"), (f"GOV-B2-{e}",), "SustainabilityIssueAddressedByPracticePolicyAndOrFutureInitiative",
            obligatoire=False)
    for col, e in zip("DEFGHIJKLM", B2_ENJEUX)
] + [
    Cellule("B2", GI, "N508", vrai_faux("GOV-B2-PUBLIC"), ("GOV-B2-PUBLIC",), obligatoire=False),
    Cellule("B2", GI, "O508", vrai_faux("GOV-B2-CIBLE"), ("GOV-B2-CIBLE",), obligatoire=False),
    Cellule("B2", GI, "D512", texte("GEN-COOP-PARTICIPATION"), ("GEN-COOP-PARTICIPATION",), obligatoire=False),
    Cellule("B2", GI, "D513", nombre("GEN-COOP-INVEST"), ("GEN-COOP-INVEST",), "FinancialInvestmentInTheCapitalOrAssetsOfSocialEconomyEntities",
            obligatoire=False),
    Cellule("B2", GI, "D514", texte("GEN-COOP-LIMITES"), ("GEN-COOP-LIMITES",), obligatoire=False),
    # C2 (suite de B2 en option B) et C1
    Cellule("C2", GI, "E517", texte("GOV-C2-DESC"), ("GOV-C2-DESC",), "DescriptionOfPracticesPoliciesAndOrFutureInitiatives"),
    Cellule("C2", GI, "E518", texte("GOV-C2-CIBLES"), ("GOV-C2-CIBLES",), "DescriptionOfATargetRelatedToAPolicy"),
    Cellule("C2", GI, "E519", texte("GOV-C2-RESPONSABLE"), ("GOV-C2-RESPONSABLE",),
            "MostSeniorLevelInTheUndertakingAccountableForImplementationOfPracticesPoliciesAndFutureInitiatives", obligatoire=False),
    Cellule("C1", GI, "E523", texte("STR-PRODUITS"), ("STR-PRODUITS",), "DescriptionOfSignificantGroupsOfProductsAndOrServicesOffered"),
    Cellule("C1", GI, "E524", texte("STR-MARCHES"), ("STR-MARCHES",), "DescriptionOfSignificantMarketsTheUndertakingOperatesIn"),
    Cellule("C1", GI, "E525", texte("STR-RELATIONS"), ("STR-RELATIONS",), "DescriptionOfMainBusinessRelationships"),
    Cellule("C1", GI, "E526", case("STR-ENJEUX"), ("STR-ENJEUX",)),
    Cellule("C1", GI, "E527", texte("STR-ENJEUX-DESC"), ("STR-ENJEUX-DESC",),
            "DescriptionOfKeyElementsOfStrategyThatRelatesToOrAffectsSustainabilityIssues", obligatoire=False),
    # B3 – énergie (MWh)
    Cellule("B3", ENV, "G5", nombre("NRJ-TOTAL-MWH"), ("NRJ-TOTAL-MWH",), "TotalEnergyConsumption"),
    Cellule("B3", ENV, "G10", une_valeur("NRJ-ELEC", "NRJ-COMBUSTIBLES"), ("NRJ-ELEC",), obligatoire=False),
    Cellule("B3", ENV, "G12", nombre("NRJ-ELEC-REN", Decimal("0.001")), ("NRJ-ELEC-REN",), "BreakdownOfEnergyConsumptionTable",
            obligatoire=False),
    # ligne « électricité » : chaleur, vapeur et froid achetés compris (guide de l'EFRAG, § 24), comptés non renouvelables
    Cellule("B3", ENV, "J12", lambda c: None if c.nombre("NRJ-ELEC") is None else _fois(
        c.nombre("NRJ-ELEC") - (c.nombre("NRJ-ELEC-REN") or 0) + (c.nombre("NRJ-CHALEUR") or 0) + (c.nombre("NRJ-FROID") or 0),
        Decimal("0.001")), ("NRJ-ELEC", "NRJ-ELEC-REN", "NRJ-CHALEUR", "NRJ-FROID"), "BreakdownOfEnergyConsumptionTable",
        obligatoire=False),
    Cellule("B3", ENV, "G13", nombre("NRJ-ELEC-AUTO", Decimal("0.001")), ("NRJ-ELEC-AUTO",), "BreakdownOfEnergyConsumptionTable",
            obligatoire=False),
    # J13 (électricité autoproduite non renouvelable) reste vide : son combustible est déjà compté (guide, § 19)
    Cellule("B3", ENV, "G14", lambda c: (c.nombre("NRJ-COMB-REN") or Decimal(0)) if c.nombre("NRJ-COMBUSTIBLES") is not None
            else c.nombre("NRJ-COMB-REN"), ("NRJ-COMB-REN",), "EnergyConsumptionFromFuels_RenewableEnergyMember", remplace=True,
            obligatoire=False),
    Cellule("B3", ENV, "J14", nombre("NRJ-COMBUSTIBLES"), ("NRJ-COMBUSTIBLES",), "EnergyConsumptionFromFuels_NonRenewableEnergyMember",
            remplace=True, obligatoire=False),
    # B3 – émissions (tCO2e) ; C3 – cibles (année de référence, année cible)
    Cellule("B3", ENV, "D22", somme("GES-S1", "GES-S1-AUTRES"), ("GES-S1", "GES-S1-AUTRES"), "EstimatedAbsoluteGreenhouseGasEmissionsTable"),
    Cellule("B3", ENV, "D23", nombre("GES-S2-LB"), ("GES-S2-LB",), "GrossLocationBasedScope2GreenhouseGasEmissions"),
    Cellule("B3", ENV, "D24", nombre("GES-S2-MB"), ("GES-S2-MB",), "GrossMarketBasedScope2GreenhouseGasEmissions", obligatoire=False),
    Cellule("B3", ENV, "G29", une_valeur(*SCOPE3), SCOPE3, obligatoire=False),
] + [
    Cellule("B3", ENV, f"D{30 + i}", nombre(code), (code,), obligatoire=False)  # sans nom : le total du scope 3 (D45) est l'élément XBRL
    for i, code in enumerate(SCOPE3)
] + [
    Cellule("C3", ENV, "J19", case("GES-CIBLES"), ("GES-CIBLES",)),
    Cellule("C3", ENV, "G21", annee("GES-ANNEE-REF"), ("GES-ANNEE-REF",), "BaselineYearMember"),
    Cellule("C3", ENV, "J21", annee("GES-ANNEE-CIBLE"), ("GES-ANNEE-CIBLE",), "GreenhouseGasEmissionReductionTargetYear"),
    Cellule("C3", ENV, "G22", nombre("GES-S1-REF"), ("GES-S1-REF",), "EstimatedAbsoluteGreenhouseGasEmissionsTable"),
    Cellule("C3", ENV, "J22", nombre("GES-S1-CIBLE"), ("GES-S1-CIBLE",), "EstimatedAbsoluteGreenhouseGasEmissionsTable"),
    Cellule("C3", ENV, "G23", nombre("GES-S2-LB-REF"), ("GES-S2-LB-REF",), "GrossLocationBasedScope2GreenhouseGasEmissions_BaselineYearMember"),
    Cellule("C3", ENV, "J23", nombre("GES-S2-LB-CIBLE"), ("GES-S2-LB-CIBLE",), "GrossLocationBasedScope2GreenhouseGasEmissions_TargetYearMember"),
    Cellule("C3", ENV, "G24", nombre("GES-S2-MB-REF"), ("GES-S2-MB-REF",), "GrossMarketBasedScope2GreenhouseGasEmissions_BaselineYearMember",
            obligatoire=False),
    Cellule("C3", ENV, "J24", nombre("GES-S2-MB-CIBLE"), ("GES-S2-MB-CIBLE",), "GrossMarketBasedScope2GreenhouseGasEmissions_TargetYearMember",
            obligatoire=False),
    Cellule("C3", ENV, "C52", texte("GES-ACTIONS"), ("GES-ACTIONS",), "DisclosureOfListOfMainActionsTheEntitySeeksInOrderToAchieveItsTargets"),
    Cellule("C3", ENV, "D57", liste("GES-PLAN-STATUT", "VS-STATUT-PLAN"), ("GES-PLAN-STATUT",),
            "StatusOfImplementationOfATransitionPlanInRelationToClimateChangeMitigation", obligatoire=False),
    Cellule("C3", ENV, "D58", texte("GES-PLAN-DESC"), ("GES-PLAN-DESC",),
            "DescriptionOfATransitionPlanForClimateChangeMitigationIncludingAnExplanationOfHowItIsContributingToReduceGhgEmissions", obligatoire=False),
    Cellule("C3", ENV, "I59", annee("GES-PLAN-ANNEE"), ("GES-PLAN-ANNEE",), obligatoire=False),
    Cellule("C3", ENV, "I60", annee("GES-PLAN-MOIS"), ("GES-PLAN-MOIS",), obligatoire=False),
    Cellule("C3", ENV, "I61", annee("GES-PLAN-JOUR"), ("GES-PLAN-JOUR",), obligatoire=False),
    # B4
    Cellule("B4", ENV, "G68", case("POL-DECLARATION"), ("POL-DECLARATION",)),
    Cellule("B4", ENV, "G69", vrai_faux("POL-PUBLIC"), ("POL-PUBLIC",), obligatoire=False),
    Cellule("B4", ENV, "G70", texte("POL-URL"), ("POL-URL",), "URLOrLinkToThePubliclyAvailableDisclosure", obligatoire=False),
    Cellule("B4", ENV, "C72", lambda c: "kilograms (kg)" if c.tableau("POL-REJETS") or c.tableau("POL-REJETS-AUTRES") else None,
            ("POL-REJETS", "POL-REJETS-AUTRES"), obligatoire=False),
    # B5
    Cellule("B5", ENV, "G189", case("BIO-SITES"), ("BIO-SITES",)),
    # B6 (m³)
    Cellule("B6", ENV, "D296", nombre("EAU-PRELEVEMENT"), ("EAU-PRELEVEMENT",), "TotalAmountOfWaterWithdrawnFromAllSites"),
    # procédés consommant beaucoup d'eau : seulement si de l'eau en est rejetée (0 = pas de tels procédés)
    Cellule("B6", ENV, "D301", lambda c: True if (c.nombre("EAU-REJET-PROCESS") or 0) > 0 else None, ("EAU-REJET-PROCESS",),
            obligatoire=False),
    Cellule("B6", ENV, "D302", positif("EAU-REJET-PROCESS"), ("EAU-REJET-PROCESS",), "WaterDischargeFromUndertakingProductionProcesses",
            obligatoire=False),
    Cellule("B6", ENV, "D304", nombre("EAU-STRESS"), ("EAU-STRESS",), "AmountOfWaterConsumedAtSitesLocatedInAreasWithWaterStress",
            obligatoire=False),
    # B7 (déchets en tonnes : totaux et pourcentages remplacent les calculs du tableau par code de déchet)
    Cellule("B7", ENV, "D309", oui_non("ECO-CIRCULAIRE"), ("ECO-CIRCULAIRE",), "UndertakingAppliesCircularEconomyPrinciples"),
    Cellule("B7", ENV, "D310", texte("ECO-CIRCULAIRE-DESC"), ("ECO-CIRCULAIRE-DESC",), "DescriptionOfHowCircularEconomyPrinciplesAreApplied",
            obligatoire=False),
    # Sans détail par code : les totaux de l'outil (tonnes) à la place des calculs du tableau. Avec le détail : le classeur
    # calcule ses totaux. Sa formule lit l'unité en G438 au lieu de G416 (classeur 2.0.0) et compte alors en kg : le
    # détail est donc écrit en kg et l'unité des totaux mise à « kilograms (kg) », pour des totaux justes.
    Cellule("B7", ENV, "G416", lambda c: ("kilograms (kg)" if c.tableau("DEC-PAR-CODE") else "metric tonnes (t)")
            if c.nombre("DEC-TOTAL") is not None or c.tableau("DEC-PAR-CODE") else None, ("DEC-TOTAL",), obligatoire=False),
    Cellule("B7", ENV, "J416", sans_detail("DEC-PAR-CODE", nombre("DEC-DANGEREUX")), ("DEC-DANGEREUX",), "TotalHazardousWasteGeneratedMass",
            remplace=True, sauf_si="DEC-PAR-CODE"),
    Cellule("B7", ENV, "J417", sans_detail("DEC-PAR-CODE", difference("DEC-TOTAL", "DEC-DANGEREUX")), ("DEC-TOTAL", "DEC-DANGEREUX"),
            "TotalNonHazardousWasteGeneratedMass", remplace=True, sauf_si="DEC-PAR-CODE"),
    Cellule("B7", ENV, "J422", sans_detail("DEC-PAR-CODE", part("DEC-RECYCLES", "DEC-TOTAL")), ("DEC-RECYCLES", "DEC-TOTAL"), remplace=True, sauf_si="DEC-PAR-CODE"),
    # part préparée pour le réemploi (masse) : la formule du classeur (1 − part recyclée) est remplacée par la vraie part
    Cellule("B7", ENV, "J423", lambda c: _part_reemploi(c), ("DEC-REEMPLOI", "DEC-TOTAL"), remplace=True),
    Cellule("B7", ENV, "G430", lambda c: True if c.tableau("ECO-MATIERES") else None, ("ECO-MATIERES",), obligatoire=False),
    # C4
    Cellule("C4", ENV, "E536", case("CLI-RISQUES"), ("CLI-RISQUES",)),
    Cellule("C4", ENV, "E537", texte("CLI-ALEAS"), ("CLI-ALEAS",), "DescriptionOfClimateRelatedHazardsAndClimateRelatedTransitionEvents"),
    Cellule("C4", ENV, "E538", texte("CLI-EXPOSITION"), ("CLI-EXPOSITION",),
            "DisclosureOfHowItHasAssessedTheExposureAndSensitivityOfItsAssetsActivitiesAndValueChainToTheseHazardsAndTransitionEvents"),
    Cellule("C4", ENV, "E539", texte("CLI-HORIZONS"), ("CLI-HORIZONS",), "TimeHorizonsOfAnyClimateRelatedHazardsAndTransitionEventsIdentified"),
    Cellule("C4", ENV, "E540", oui_non("CLI-ADAPTATION"), ("CLI-ADAPTATION",),
            "DisclosureOfWhetherItHasUndertakenClimateChangeAdaptationActionsForAnyClimateRelatedHazardsAndTransitionEvents"),
    Cellule("C4", ENV, "E541", texte("CLI-EFFETS"), ("CLI-EFFETS",), "PotentialAdverseEffectsOfClimateRisksThatMayAffectItsFinancialPerformanceOrBusinessOperationsInTheShortMediumOrLongTermIndicatingWhetherItAssessesTheRisksToBeHighMediumOrLow",
            obligatoire=False),
    Cellule("B1", ENV, "C545", texte("ENV-AUTRES"), ("ENV-AUTRES",), "DisclosureOfAnyOtherEnvironmentalAndOrEntitySpecificEnvironmentalDisclosures",
            obligatoire=False, verrouillee=True),
    # B8
    Cellule("B8", SOC, "D10", nombre("SOC-EFF-CDI"), ("SOC-EFF-CDI",), "NumberOfPermanentContractEmployees"),
    Cellule("B8", SOC, "D18", nombre("SOC-EFF-HOMMES"), ("SOC-EFF-HOMMES",), "NumberOfMaleEmployees"),
    Cellule("B8", SOC, "D19", nombre("SOC-EFF-FEMMES"), ("SOC-EFF-FEMMES",), "NumberOfFemaleEmployees"),
    Cellule("B8", SOC, "D20", nombre("SOC-EFF-GENRE-AUTRE"), ("SOC-EFF-GENRE-AUTRE",), "NumberOfOtherGenderEmployees", obligatoire=False),
    Cellule("B8", SOC, "D21", nombre("SOC-EFF-GENRE-NC"), ("SOC-EFF-GENRE-NC",), "NumberOfNonReportedGenderEmployees", obligatoire=False),
    # B9 (taux pour 500 salariés à temps plein = par million d'heures, comme le taux de fréquence)
    Cellule("B9", SOC, "D133", nombre("SOC-ACCIDENTS-ENREG"), ("SOC-ACCIDENTS-ENREG",), "NumberOfRecordableWorkRelatedAccidentsInTheReportingPeriod"),
    Cellule("B9", SOC, "D136", lambda c: "500" if c.nombre("SOC-ACCIDENTS-ENREG") is not None else None, ("SOC-ACCIDENTS-ENREG",),
            obligatoire=False),
    Cellule("B9", SOC, "D139", nombre("SOC-DECES"), ("SOC-DECES",),
            "SumOfFatalitiesAsAResultOfRecordableWorkRelatedAccidentsAndRecordableWorkRelatedIllHealth"),
    # B10
    Cellule("B10", SOC, "D142", oui_non("SOC-SALAIRE-MINIMUM"), ("SOC-SALAIRE-MINIMUM",),
            "EmployeesReceivePayEqualOrAboveMinimumWageDeterminedByNationalLawOrCollectiveAgreement"),
    Cellule("B10", SOC, "D143", case("SOC-ECART-OBLIGATION"), ("SOC-ECART-OBLIGATION",)),
    Cellule("B10", SOC, "D144", nombre("SOC-REMU-H-HOMMES"), ("SOC-REMU-H-HOMMES",), obligatoire=False),
    Cellule("B10", SOC, "D145", nombre("SOC-REMU-H-FEMMES"), ("SOC-REMU-H-FEMMES",), obligatoire=False),
    Cellule("B10", SOC, "D147", nombre("SOC-SAL-CONVENTION"), ("SOC-SAL-CONVENTION",)),
    Cellule("B10", SOC, "D153", nombre("SOC-HEURES-FORM"), ("SOC-HEURES-FORM",)),
    Cellule("B10", SOC, "D154", nombre("SOC-EFFECTIF"), ("SOC-EFFECTIF",)),
    # C5 (rotation : départs de salariés en CDI, effectif au début = fin de l'exercice précédent)
    Cellule("C5", SOC, "D158", nombre("SOC-DEPARTS-CDI"), ("SOC-DEPARTS-CDI",)),
    Cellule("C5", SOC, "D159", lambda c: (c.precedent("SOC-EFFECTIF") if c.precedent("SOC-EFFECTIF") is not None
                                          else c.nombre("SOC-EFFECTIF-DEBUT")) if c.nombre("SOC-DEPARTS-CDI") is not None else None,
            ("SOC-EFFECTIF", "SOC-EFFECTIF-DEBUT"), obligatoire=False),
    Cellule("C5", SOC, "D160", lambda c: c.nombre("SOC-EFFECTIF") if c.nombre("SOC-DEPARTS-CDI") is not None else None, ("SOC-EFFECTIF",),
            obligatoire=False),
    Cellule("C5", SOC, "D162", nombre("SOC-MANAGERS-FEMMES"), ("SOC-MANAGERS-FEMMES",), obligatoire=False),
    Cellule("C5", SOC, "D163", nombre("SOC-MANAGERS-HOMMES"), ("SOC-MANAGERS-HOMMES",), obligatoire=False),
    Cellule("C5", SOC, "D165", nombre("SOC-INDEPENDANTS"), ("SOC-INDEPENDANTS",),
            "TotalNumberOfSelfEmployedWorkersWithoutPersonnelThatAreWorkingExclusivelyForTheUndertaking", obligatoire=False),
    Cellule("C5", SOC, "D166", nombre("SOC-INTERIMAIRES"), ("SOC-INTERIMAIRES",),
            "TotalNumberOfTemporaryWorkersProvidedByUndertakingsPrimarilyEngagedInEmploymentActivities", obligatoire=False),
    # C6
    Cellule("C6", SOC, "D169", oui_non("SOC-CODE-CONDUITE"), ("SOC-CODE-CONDUITE",), "UndertakingHasACodeOfConductOrHumanRightsPolicyForItsOwnWorkforce"),
] + [
    Cellule("C6", SOC, f"D{171 + i}", case(f"SOC-CODE-{c}"), (f"SOC-CODE-{c}",), obligatoire=False) for i, c in enumerate(C6_CONTENUS)
] + [
    Cellule("C6", SOC, "D177", texte("SOC-CODE-AUTRE-DESC"), ("SOC-CODE-AUTRE-DESC",),
            "SpecificationOfOtherTypesOfContentCoveredByTheCodeOfConductOrHumanRightsPolicy", obligatoire=False),
    Cellule("C6", SOC, "D178", oui_non("SOC-PLAINTES"), ("SOC-PLAINTES",), "UndertakingHasAComplaintHandlingMechanismForItsOwnWorkforce"),
    # C7
    Cellule("C7", SOC, "D181", oui_non("SOC-INCIDENTS"), ("SOC-INCIDENTS",), "UndertakingHasConfirmedHumanRightsIncidentsInItsOwnWorkforce"),
] + [
    Cellule("C7", SOC, f"D{183 + i}", case(f"SOC-INCIDENT-{c}"), (f"SOC-INCIDENT-{c}",), obligatoire=False)
    for i, c in enumerate(C7_INCIDENTS)
] + [
    Cellule("C7", SOC, "D188", texte("SOC-INCIDENT-AUTRE-DESC"), ("SOC-INCIDENT-AUTRE-DESC",),
            "SpecificationOfOtherHumanRightsRelatedToTheConfirmedIncident", obligatoire=False),
    Cellule("C7", SOC, "D189", texte("SOC-INCIDENTS-ACTIONS"), ("SOC-INCIDENTS-ACTIONS",),
            "DescriptionOfActionsTakeToAddressTheConfirmedIncidents", obligatoire=False),
    Cellule("C7", SOC, "D190", oui_non("SOC-INCIDENTS-CHAINE"), ("SOC-INCIDENTS-CHAINE",),
            "UndertakingIsAwareOfAnyConfirmedIncidentsInvolvingWorkersInTheValueChainAffectedCommunitiesConsumersAndEndUsers"),
    Cellule("C7", SOC, "D191", texte("SOC-INCIDENTS-CHAINE-DESC"), ("SOC-INCIDENTS-CHAINE-DESC",),
            "SpecificationOfAnyConfirmedIncidentInvolvingWorkersInTheValueChainAffectedCommunitiesConsumersAndEndUsers", obligatoire=False),
    Cellule("B1", SOC, "C197", texte("SOC-AUTRES"), ("SOC-AUTRES",), "DisclosureOfAnyOtherSocialAndOrEntitySpecificSocialDisclosures",
            obligatoire=False),
    # B11 (condamnations et amendes : seulement s'il y en a)
    Cellule("B11", GOV, "H5", lambda c: (c.nombre("GOV-CORRUPTION") or 0) > 0 or (c.nombre("GOV-AMENDES") or 0) > 0
            if c.nombre("GOV-CORRUPTION") is not None or c.nombre("GOV-AMENDES") is not None else None, ("GOV-CORRUPTION", "GOV-AMENDES")),
    Cellule("B11", GOV, "H6", positif("GOV-CORRUPTION"), ("GOV-CORRUPTION",), "TotalNumberOfConvictionsForTheViolationOfAntiCorruptionAndAntiBriberyLaws",
            obligatoire=False),
    Cellule("B11", GOV, "H7", positif("GOV-AMENDES"), ("GOV-AMENDES",), "TotalAmountOfFinesForTheViolationOfAnticorruptionAndAntibriberyLaws",
            obligatoire=False),
    # C8
    Cellule("C8", GOV, "H10", case("GOV-REV-SECTEURS"), ("GOV-REV-SECTEURS",)),
] + [
    Cellule("C8", GOV, cel, nombre(code), (code,), nom, obligatoire=False)
    for cel, code, nom in (("H12", "GOV-REV-ARMES", "RevenueDerivedFromTheProhibitedWeaponsIndustryAntiPersonnelMinesClusterMunitionsChemicalWeaponsAndBiologicalWeapons"),
                           ("H13", "GOV-REV-TABAC", "RevenueDerivedFromCultivationAndProductionOfTobacco"),
                           ("H14", "GOV-REV-CHARBON", "RevenueDerivedFromCoal"), ("H15", "GOV-REV-PETROLE", "RevenueDerivedFromOil"),
                           ("H16", "GOV-REV-GAZ", "RevenueDerivedFromGas"), ("H18", "GOV-REV-CHIMIE", "RevenueDerivedFromChemicalProduction"))
] + [
    # C9
    Cellule("C9", GOV, "H22", case("GOV-ORGANE"), ("GOV-ORGANE",)),
    Cellule("C9", GOV, "H23", nombre("GOV-CA-FEMMES"), ("GOV-CA-FEMMES",)),
    Cellule("C9", GOV, "H24", nombre("GOV-CA-HOMMES"), ("GOV-CA-HOMMES",)),
    Cellule("B1", GOV, "C30", texte("GOV-AUTRES"), ("GOV-AUTRES",), "DisclosureOfAnyOtherGovernanceAndOrEntitySpecificGovernanceDisclosures",
            obligatoire=False),
]


# ---------------------------------------------------------------- tableaux à lignes variables
def _sites(c):
    """B1 : une ligne par site (adresse, code postal, ville, pays) ; l'ID de la colonne C est celui du classeur (1, 2…)."""
    sortie = {}
    for i, s in enumerate(c.sites[:LIGNES_SITES[1] - LIGNES_SITES[0] + 1]):
        ligne = LIGNES_SITES[0] + i
        pays = s.choix("GEN-SITE-PAYS")
        for col, v in (("D", s.texte("GEN-SITE-ADRESSE")), ("E", s.texte("GEN-SITE-CP")), ("F", s.texte("GEN-SITE-VILLE")),
                       ("G", VALEURS["VS-PAYS"][pays] if pays is not None else None), ("H", _gps(c, s))):
            if v is not None:
                sortie[f"{col}{ligne}"] = v
    return sortie


def _gps(c, site):
    """« longitude,latitude » (format du classeur) à partir de « latitude, longitude » saisi (ordre des services de cartes)."""
    t = site.texte("GEN-SITE-GPS")
    if not t:
        return None
    morceaux = [m for m in t.replace(";", ",").replace(" ", ",").split(",") if m]
    try:
        lat, lon = (Decimal(m) for m in morceaux)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError
    except (ValueError, ArithmeticError):
        c.message("suivi.officiel.msg.gps", site=str(site.organisation), valeur=t[:40])
        return None
    return f"{lon:.5f},{lat:.5f}"


def _biodiversite(c):
    """B5 : les sites dans ou près d'une zone sensible, repérés par leur ID de la liste des sites (B1)."""
    sortie, n = {}, 0
    for i, s in enumerate(c.sites[:LIGNES_SITES[1] - LIGNES_SITES[0] + 1]):  # l'ID renvoie à une ligne de la liste des sites
        zone = s.choix("BIO-SITE-ZONE")
        if zone not in (0, 1) or n > LIGNES_BIODIVERSITE[1] - LIGNES_BIODIVERSITE[0]:
            continue
        ligne = LIGNES_BIODIVERSITE[0] + n
        n += 1
        sortie[f"C{ligne}"] = i + 1
        if s.texte("BIO-SITE-ZONE-NOM"):
            sortie[f"G{ligne}"] = s.texte("BIO-SITE-ZONE-NOM")
        sortie[f"J{ligne}"], sortie[f"K{ligne}"] = zone == 0, zone == 1
    return sortie


def _pays(c):
    """B8 : salariés par pays du contrat (somme des effectifs des sites de chaque pays) ; case « plus d'un pays »."""
    par_pays = {}
    for s in c.sites:
        pays, effectif = s.choix("GEN-SITE-PAYS"), s.nombre("SOC-EFFECTIF")
        if pays is not None and effectif is not None:
            par_pays[pays] = par_pays.get(pays, Decimal(0)) + Decimal(effectif)
    if not par_pays:
        return {}
    sortie = {"E27": len(par_pays) > 1}
    if len(par_pays) > 1:
        tries = sorted(par_pays.items(), key=lambda x: (-x[1], VALEURS["VS-PAYS"][x[0]]))
        for i, (pays, n) in enumerate(tries[:LIGNES_PAYS[1] - LIGNES_PAYS[0] + 1]):
            sortie[f"C{LIGNES_PAYS[0] + i}"] = VALEURS["VS-PAYS"][pays]
            sortie[f"E{LIGNES_PAYS[0] + i}"] = n
    return sortie


def _part_reemploi(c):
    """Part des déchets préparée pour le réemploi : depuis le tableau par code de déchet s'il est rempli, sinon depuis les
    totaux de l'outil."""
    lignes = c.tableau("DEC-PAR-CODE")
    if lignes:
        masse = sum((l.get("masse") or 0) for l in lignes)
        return sum((l.get("reemploi") or 0) for l in lignes) / masse if masse else None
    return part("DEC-REEMPLOI", "DEC-TOTAL")(c)


def _omissions(c):
    """B1 · 27(b) : une case cochée, dans le sommaire du classeur, par rubrique omise comme classifiée ou sensible (les
    rubriques du module complet seulement en option B)."""
    sortie = {}
    for l in c.tableau("GEN-OMISSIONS"):
        r = l.get("rubrique")
        if r is not None and r < len(OMISSIONS) and (OMISSIONS[r][0] < 45 or c.option_b):
            sortie[f"D{OMISSIONS[r][0]}"] = True
    return sortie


def _filiales(c):
    """B1 : une ligne par filiale (nom, adresse du siège) ; l'ID de la colonne C est celui du classeur."""
    sortie = {}
    for i, l in enumerate(c.tableau("GEN-FILIALES")[:LIGNES_FILIALES[1] - LIGNES_FILIALES[0] + 1]):
        ligne = LIGNES_FILIALES[0] + i
        for col, v in (("D", l.get("nom")), ("E", l.get("adresse"))):
            if v:
                sortie[f"{col}{ligne}"] = v
    return sortie


def _inchangees(c):
    """B1 : rubriques inchangées depuis le rapport précédent, dans la langue d'affichage du classeur (ses valeurs de liste
    sont des libellés traduits)."""
    col = LANGUES_INCHANGEES.get(c.langue, 0)
    rangs = [l["rubrique"] for l in c.tableau("GEN-INFOS-INCHANGEES") if l.get("rubrique") is not None]
    return {f"E{LIGNES_INCHANGEES[0] + i}": INFOS_INCHANGEES[r][col]
            for i, r in enumerate(rangs[:LIGNES_INCHANGEES[1] - LIGNES_INCHANGEES[0] + 1]) if r < len(INFOS_INCHANGEES)}


def _rejets(c, code, lignes, nom_colonne, valeur_nom):
    sortie, n = {}, 0
    for l in c.tableau(code):
        nom = valeur_nom(l.get(nom_colonne))
        if not nom or n > lignes[1] - lignes[0]:
            continue
        ligne = lignes[0] + n
        n += 1
        sortie[f"D{ligne}"] = nom
        for col, cle in (("G", "air"), ("J", "eau"), ("K", "sol")):
            if l.get(cle) is not None:
                sortie[f"{col}{ligne}"] = l[cle]
    return sortie


def _polluants(c):
    """B4 : rejets par polluant de la liste européenne (kg), additionnés sur tous les sites."""
    return _rejets(c, "POL-REJETS", LIGNES_POLLUANTS, "polluant",
                   lambda i: VALEURS["VS-POLLUANT"][i] if i is not None and i < len(VALEURS["VS-POLLUANT"]) else None)


def _autres_polluants(c):
    """B4 : polluants hors de la liste européenne (nom libre), en kg."""
    return _rejets(c, "POL-REJETS-AUTRES", LIGNES_AUTRES_POLLUANTS, "nom", lambda v: v)


def _dechets(c):
    """B7 : déchets par code de la liste européenne, en kg (voir la cellule G416) ; parts recyclée et réemployée en fraction."""
    officielle = {v.strip(): v for v in c.liste_officielle("enum_ListTypeOfWastes")}
    sortie, n = {}, 0
    for l in c.tableau("DEC-PAR-CODE"):
        i = l.get("code")
        if i is None or i >= len(VALEURS["VS-DECHET"]) or n > LIGNES_DECHETS[1] - LIGNES_DECHETS[0]:
            continue
        ligne = LIGNES_DECHETS[0] + n
        n += 1
        sortie[f"D{ligne}"] = officielle.get(VALEURS["VS-DECHET"][i], VALEURS["VS-DECHET"][i])
        sortie[f"G{ligne}"] = "kilograms (kg)"
        masse = l.get("masse")
        if masse is not None:  # les deux parts sont exigées par le contrôle de la ligne : 0 quand rien n'est déclaré
            sortie[f"J{ligne}"] = masse * 1000
            for col, cle in (("K", "recycle"), ("L", "reemploi")):
                sortie[f"{col}{ligne}"] = l[cle] / masse if l.get(cle) is not None and masse else 0
    return sortie


def _matieres(c):
    """B7 : flux de matières clés (nom, quantité, unité)."""
    sortie, n = {}, 0
    for l in c.tableau("ECO-MATIERES"):
        if not l.get("matiere") or n > LIGNES_MATIERES[1] - LIGNES_MATIERES[0]:
            continue
        ligne = LIGNES_MATIERES[0] + n
        n += 1
        sortie[f"D{ligne}"] = l["matiere"]
        if l.get("quantite") is not None:
            sortie[f"G{ligne}"] = l["quantite"]
        u = l.get("unite")
        if u is not None and u < len(VALEURS["VS-UNITE-MATIERE"]):
            sortie[f"J{ligne}"] = VALEURS["VS-UNITE-MATIERE"][u]
    return sortie


def _cibles_scope3(c):
    """C3 : valeurs de l'année de référence (G) et de l'année cible (J) de chaque catégorie du scope 3 (lignes 30 à 44)."""
    sortie = {}
    for l in c.tableau("GES-S3-CIBLES"):
        i = l.get("categorie")
        if i is None or i > 14:
            continue
        for col, cle in (("G", "reference"), ("J", "cible")):
            if l.get(cle) is not None:
                sortie[f"{col}{30 + i}"] = l[cle]
    return sortie


def _nace(c):
    """B1 : codes NACE saisis (« 47.91 », un par ligne) → valeurs de la liste officielle (« NACE G - 47.91 … »)."""
    sortie = {}
    codes = [x.strip().rstrip(".") for x in (c.texte("GEN-NACE") or "").replace(";", "\n").replace(",", "\n").split("\n") if x.strip()]
    liste_officielle = c.liste_officielle("enum_ListNACETechnicalName")
    for i, code in enumerate(codes[:LIGNES_NACE[1] - LIGNES_NACE[0] + 1]):
        trouve = next((v for v in liste_officielle if f" - {code} " in v or v.endswith(f" - {code}")), None)
        if trouve:
            sortie[f"E{LIGNES_NACE[0] + i}"] = trouve
        else:
            c.message("suivi.officiel.msg.nace", code=code)
    return sortie


BLOCS = [
    Bloc("B1", GI, _nace, ("GEN-NACE",), LIGNES_NACE, ("E",), "NaceSectorClassificationCodes"),
    Bloc("B1", GI, _sites, ("GEN-SITE-ADRESSE", "GEN-SITE-CP", "GEN-SITE-VILLE", "GEN-SITE-PAYS", "GEN-SITE-GPS"), LIGNES_SITES,
         ("D", "E", "F", "G", "H"), "ListOfSitesTable", remplace=("H",)),
    Bloc("B1", GI, _filiales, ("GEN-FILIALES",), LIGNES_FILIALES, ("D", "E"), "ListOfSubsidiaryTable"),
    Bloc("B1", SOMMAIRE, _omissions, ("GEN-OMISSIONS",), (OMISSIONS[0][0], OMISSIONS[-1][0]), ("D",)),
    Bloc("B1", GI, _inchangees, ("GEN-INFOS-INCHANGEES",), LIGNES_INCHANGEES, ("E",),
         "ListOfDisclosuresForWhichNoChangesAreReportedComparedToThePreviousPeriodReporting"),
    Bloc("B4", ENV, _polluants, ("POL-REJETS",), LIGNES_POLLUANTS, ("D", "G", "J", "K"), "AmountOfEmissionsTable"),
    Bloc("B4", ENV, _autres_polluants, ("POL-REJETS-AUTRES",), LIGNES_AUTRES_POLLUANTS, ("D", "G", "J", "K"), "AmountOfOtherPollutantEmissionTable"),
    Bloc("B7", ENV, _dechets, ("DEC-PAR-CODE",), LIGNES_DECHETS, ("D", "G", "J", "K", "L"), "TypeOfWasteAxis"),
    Bloc("B7", ENV, _matieres, ("ECO-MATIERES",), LIGNES_MATIERES, ("D", "G", "J"),
         "BreakdownOfAnnualMassFlowOfRelevantMaterialsUsedByTheUndertakingHypercube"),
    Bloc("C3", ENV, _cibles_scope3, ("GES-S3-CIBLES",), (30, 44), ("G", "J"), ""),
    Bloc("B5", ENV, _biodiversite, ("BIO-SITE-ZONE", "BIO-SITE-ZONE-NOM"), LIGNES_BIODIVERSITE, ("C", "G", "J", "K"),
         "SitesInBiodiversitySensitiveAreasTable"),
    Bloc("B8", SOC, _pays, ("GEN-SITE-PAYS", "SOC-EFFECTIF"), LIGNES_PAYS, ("C", "E"), "CountryOfEmploymentContractAxis"),
]



def construire(c):
    """Écritures du classeur pour le contexte ``c`` (valeurs de la période, voir collecte/export_officiel.py)."""
    r = Resultat()
    for cel in CELLULES:
        valeur = cel.valeur(c) if callable(cel.valeur) else cel.valeur
        if isinstance(valeur, (int, float, Decimal)) and not isinstance(valeur, bool):
            ecarts = [(k, c.unite_hors_monnaie(k, MONTANTS[k])) for k in cel.codes if k in MONTANTS]
            ecarts = [(k, u) for k, u in ecarts if u is not None]
            if ecarts:  # montant dans une autre monnaie (ou à une autre échelle) que celle du rapport : rien d'écrit
                for k, u in ecarts:
                    c.message("suivi.officiel.msg.monnaie", kpi=k, unite=u, monnaie=c.monnaie)
                continue
        if valeur is None:
            if (cel.obligatoire and cel.codes and (cel.module.startswith("B") or c.option_b) and c.connait(cel.codes)
                    and not (cel.sauf_si and c.tableau(cel.sauf_si))):
                r.manquantes.append((cel.module, cel.codes))
            continue
        r.ecritures[(cel.onglet, cel.cellule)] = valeur
        if cel.remplace:
            r.formules.add((cel.onglet, cel.cellule))
        r.remplies.append((cel.module, cel.onglet, cel.cellule, cel.codes))
    for bloc in BLOCS:
        for cellule, valeur in bloc.remplir(c).items():
            r.ecritures[(bloc.onglet, cellule)] = valeur
            if cellule.rstrip("0123456789") in bloc.remplace:
                r.formules.add((bloc.onglet, cellule))
            r.remplies.append((bloc.module, bloc.onglet, cellule, bloc.codes))
    if len(c.sites) > LIGNES_SITES[1] - LIGNES_SITES[0] + 1:
        c.message("suivi.officiel.msg.sites", n=len(c.sites), max=LIGNES_SITES[1] - LIGNES_SITES[0] + 1)
    r.messages = list(c.messages)
    return r
