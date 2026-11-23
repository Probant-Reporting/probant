"""Socle commun des modèles ESRS révisées (règlement délégué (UE) 2026/1563) : un modèle par norme (ESRS 2, E1 à E5, S1 à
S4, G1), qui partagent ce fichier. Le nom commence par « _ » : ``definitions.charger`` ne le prend pas pour un modèle.

Ce que chaque fichier ``esrs_<norme>.py`` reprend d'ici (méthode et décisions : note de conception de l'atelier, non publiée) :

- ``SOURCE`` : la liste des trois documents (règlement, liste des points de données de l'EFRAG, note explicative), avec leurs dates ;
- ``socle(code, …)`` : en-tête du modèle (fichier, couleur, ordre, nom, description, thématique) depuis ``MODELES`` ; les
  noms et descriptions sont aussi dans libelles/referentiels.<langue>.json (les sept langues) : les changer aux deux
  endroits ;
- ``COUVERTURE`` : l'inventaire maître ``esrs_coverage.csv`` (une ligne par point de données, colonne ``template``) ;
- ``UNITES`` et ``TYPES_REPONSE`` : unités et listes partagées (une même définition dans plusieurs fichiers ne crée pas
  de conflit) ;
- ``bloc_gdr(…)`` : les KPI des exigences générales de l'ESRS 2 (GDR-P politiques, GDR-A actions, GDR-T cibles, GDR-M
  indicateurs) pour un sujet, mêmes textes d'un sujet à l'autre, et ``arbre_gdr(…)`` pour les placer.

Conventions (à suivre dans chaque modèle ESRS) :

- code d'un KPI : la donnée, pas la norme (``EAU-REJET``, pas ``E3-4-16D``), préfixe de la famille (``EAU-``, ``GES-``,
  ``NRJ-``, ``DEC-``, ``POL-``, ``BIO-``, ``SOC-``, ``GOV-``, ``GEN-``, ``STR-``, ``CLI-``, ``ECO-``), 30 caractères au plus ;
  bloc GDR d'un sujet : préfixe du sujet + ``-POLITIQUES``, ``-POLIT-…``, ``-ACTIONS``, ``-ACT-…``, ``-CIBLES``, ``-CIB-…``,
  ``-SUIVI-SS-CIBLE``, ``-METHODES``, ``-EVOLUTION`` ; code d'un type de réponse : 20 caractères au plus ;
- un KPI réutilisé (VS, transparence des rémunérations, catalogue) n'est jamais redéfini : son code est placé dans
  l'arbre ; réutiliser seulement si définition, périmètre, unité et période sont les mêmes (revue des doublons :
  revue des doublons de l'atelier) ;
- textes : anglais d'abord, puis français (couples (fr, en) dans le code) ; la description cite le paragraphe ; un texte
  rédigé, une politique, une cible : niveau « haut » ; une donnée mesurée : niveau du site (aucun niveau) ; une donnée
  d'employeur (montants, rémunérations) : niveau « entite » ;
- référence dans l'arbre : « <DR> · <paragraphe> » (``"E3-4 · 16(a)"``) ; une exigence générale : « E3-1 · ESRS 2 §42(a) » ;
- chaque ligne du modèle dans ``esrs_coverage.csv`` passe de la proposition à la réalité (``kpi_codes`` exacts, ``note``) ;
  ``python3 manage.py bibliotheque --validate --template <CODE> --warnings`` doit passer.
"""
from referentiel.bibliotheque.outils import ZERO, ZERO_EN  # noqa: F401 (repris par les modèles ESRS)

HAUT = "haut"
ENTITE = "entite"
COUVERTURE = "esrs_coverage.csv"  # inventaire maître, filtré par la colonne « template » (controle._controler_couverture)

# Montants : la monnaie des états financiers (ESRS 1 AR 50), pas forcément l'euro. Un KPI de montant porte l'unité « € » du
# catalogue (comme la norme volontaire VS) ; à l'installation, elle devient la même unité dans la monnaie de référence de
# l'espace (`parametres/monnaies.py`) ; les colonnes de montant des tableaux n'ont pas d'unité.
MONNAIE = (" Montant dans la monnaie des états financiers (ESRS 1 AR 50) : l'unité suit la monnaie de référence de l'espace "
           "(Référentiels › Unités et formats), à régler avant d'installer le modèle ; aucune valeur n'est convertie.",
           " Amount in the currency of the financial statements (ESRS 1 AR 50): the unit follows the reference currency of the "
           "space (Frameworks › Units and formats), to set before you install the template; no value is converted.")
MONNAIE_TABLEAU = (" Montants dans la monnaie des états financiers (ESRS 1 AR 50).",
                   " Amounts in the currency of the financial statements (ESRS 1 AR 50).")

SOURCE = [  # titre, éditeur, version et dates : ceux du document (comparés au registre des références par un test de l'atelier)
    {"titre": "Commission Delegated Regulation (EU) 2026/1563 of 3 July 2026 amending Delegated Regulation (EU) 2023/2772 "
              "(revised ESRS: ESRS 1, ESRS 2, E1 to E5, S1 to S4, G1, glossary)",
     "editeur": "European Commission", "version": "OJ L, 21 September 2026", "date": "2026-07-03",
     "url": "http://data.europa.eu/eli/reg_del/2026/1563/oj", "consulte_le": "2026-11-18",
     "licence": "EU law: reuse allowed with acknowledgement of the source (Commission Decision 2011/833/EU)"},
    {"titre": "Draft List of Datapoints effective from 2026, Revised ESRS Delegated Act of 3 July 2026, clean version (workbook)",
     "editeur": "EFRAG", "version": "Draft, version of 28 August 2026", "date": "2026-08-28",
     "url": "https://www.efrag.org/", "consulte_le": "2026-11-18",
     "licence": "(c) EFRAG; non-authoritative draft, reproduction and use rights restricted; consulted only to check "
                "that the inventory is complete, nothing of it is reproduced in the templates"},
    {"titre": "Explanatory Note: Revised ESRS, Draft List of Datapoints and Draft XBRL Taxonomy 2026",
     "editeur": "EFRAG", "version": "28 August 2026", "date": "2026-08-28",
     "url": "https://www.efrag.org/", "consulte_le": "2026-11-18",
     "licence": "(c) EFRAG; read for reference only, nothing of it is reproduced in the templates"},
]

THEMATIQUE = ("Normes de reporting", "Reporting standards")
_REGLEMENT = (" Construit d'après le règlement délégué (UE) 2026/1563 du 3 juillet 2026.",
              " Built from Delegated Regulation (EU) 2026/1563 of 3 July 2026.")
_SUJET = (" À installer si le sujet est important, avec le modèle ESRS 2.",
          " Install it if the topic is material, with the ESRS 2 template.")


def _desc(fr, en, sujet=True):
    return (fr + (_SUJET[0] if sujet else "") + _REGLEMENT[0], en + (_SUJET[1] if sujet else "") + _REGLEMENT[1])


# En-têtes des onze modèles (les noms et descriptions sont aussi dans libelles/referentiels.<langue>.json, sept langues).
MODELES = {
    "ESRS_2": dict(fichier="esrs_2.json", couleur="#4A4F5C", ordre=30,
                   nom=("ESRS 2 – Informations générales", "ESRS 2 – General disclosures"),
                   description=_desc("Informations générales de l'ESRS 2 révisée : base de préparation, gouvernance, stratégie, "
                                     "analyse de matérialité, et exigences générales sur les politiques, actions, indicateurs "
                                     "et cibles des sujets propres à l'entreprise. À installer avec les modèles des sujets "
                                     "importants.",
                                     "General disclosures of the revised ESRS 2: basis for preparation, governance, strategy, "
                                     "materiality assessment, and the general requirements on policies, actions, metrics and "
                                     "targets of entity-specific matters. Install it with the templates of the material "
                                     "topics.", sujet=False)),
    "ESRS_E1": dict(fichier="esrs_e1.json", couleur="#A23B2A", ordre=31,
                    nom=("ESRS E1 – Changement climatique", "ESRS E1 – Climate change"),
                    description=_desc("Norme ESRS E1 révisée : plan de transition, risques climatiques, politiques, actions et "
                                      "cibles, énergie, émissions de gaz à effet de serre des scopes 1, 2 et 3, absorptions et "
                                      "crédits carbone, prix interne du carbone, effets financiers attendus.",
                                      "Revised ESRS E1: transition plan, climate risks, policies, actions and targets, energy, "
                                      "scope 1, 2 and 3 greenhouse gas emissions, removals and carbon credits, internal carbon "
                                      "pricing, anticipated financial effects.")),
    "ESRS_E2": dict(fichier="esrs_e2.json", couleur="#7B6A1F", ordre=32,
                    nom=("ESRS E2 – Pollution", "ESRS E2 – Pollution"),
                    description=_desc("Norme ESRS E2 révisée : politiques, actions et cibles sur la pollution, rejets de "
                                      "polluants dans l'air, l'eau et les sols, microplastiques, substances préoccupantes et "
                                      "extrêmement préoccupantes.",
                                      "Revised ESRS E2: policies, actions and targets on pollution, emissions of pollutants to "
                                      "air, water and soil, microplastics, substances of concern and of very high concern.")),
    "ESRS_E3": dict(fichier="esrs_e3.json", couleur="#1C6E9E", ordre=33,
                    nom=("ESRS E3 – Eau", "ESRS E3 – Water"),
                    description=_desc("Norme ESRS E3 révisée : politiques, actions et cibles sur l'eau, consommation, "
                                      "prélèvement, rejet, recyclage et stockage de l'eau.",
                                      "Revised ESRS E3: policies, actions and targets on water, water consumption, withdrawal, "
                                      "discharge, recycling and storage.")),
    "ESRS_E4": dict(fichier="esrs_e4.json", couleur="#3E7D2E", ordre=34,
                    nom=("ESRS E4 – Biodiversité et écosystèmes", "ESRS E4 – Biodiversity and ecosystems"),
                    description=_desc("Norme ESRS E4 révisée : plan de transition pour la biodiversité, politiques, actions et "
                                      "cibles, compensations, sites liés aux zones sensibles et indicateurs.",
                                      "Revised ESRS E4: biodiversity transition plan, policies, actions and targets, offsets, "
                                      "sites linked to sensitive areas and metrics.")),
    "ESRS_E5": dict(fichier="esrs_e5.json", couleur="#8A5A2B", ordre=35,
                    nom=("ESRS E5 – Utilisation des ressources et économie circulaire",
                         "ESRS E5 – Resource use and circular economy"),
                    description=_desc("Norme ESRS E5 révisée : politiques, actions et cibles sur les ressources et l'économie "
                                      "circulaire, matières entrantes, durabilité et recyclabilité des produits, déchets par "
                                      "mode de traitement.",
                                      "Revised ESRS E5: policies, actions and targets on resource use and circular economy, "
                                      "resource inflows, durability and recyclability of products, waste by treatment.")),
    "ESRS_S1": dict(fichier="esrs_s1.json", couleur="#6A3D8F", ordre=36,
                    nom=("ESRS S1 – Personnel de l'entreprise", "ESRS S1 – Own workforce"),
                    description=_desc("Norme ESRS S1 révisée : politiques, dialogue, actions et cibles sur le personnel, "
                                      "effectifs, non-salariés, négociation collective, mixité de la direction, salaires "
                                      "décents, protection sociale, handicap, formation, santé et sécurité, congés familiaux, "
                                      "rémunération, incidents.",
                                      "Revised ESRS S1: policies, engagement, actions and targets on the own workforce, "
                                      "headcount, non-employees, collective bargaining, gender diversity of top management, "
                                      "adequate wages, social protection, disability, training, health and safety, family "
                                      "leave, remuneration, incidents.")),
    "ESRS_S2": dict(fichier="esrs_s2.json", couleur="#8E3F75", ordre=37,
                    nom=("ESRS S2 – Travailleurs de la chaîne de valeur", "ESRS S2 – Workers in the value chain"),
                    description=_desc("Norme ESRS S2 révisée : politiques, dialogue, mécanismes de plainte, actions, incidents "
                                      "et cibles sur les travailleurs de la chaîne de valeur.",
                                      "Revised ESRS S2: policies, engagement, grievance mechanisms, actions, incidents and "
                                      "targets on workers in the value chain.")),
    "ESRS_S3": dict(fichier="esrs_s3.json", couleur="#B0533A", ordre=38,
                    nom=("ESRS S3 – Communautés affectées", "ESRS S3 – Affected communities"),
                    description=_desc("Norme ESRS S3 révisée : politiques, dialogue (peuples autochtones compris), mécanismes de "
                                      "plainte, actions, incidents et cibles sur les communautés affectées.",
                                      "Revised ESRS S3: policies, engagement (indigenous peoples included), grievance "
                                      "mechanisms, actions, incidents and targets on affected communities.")),
    "ESRS_S4": dict(fichier="esrs_s4.json", couleur="#3F5FA0", ordre=39,
                    nom=("ESRS S4 – Consommateurs et utilisateurs finaux", "ESRS S4 – Consumers and end-users"),
                    description=_desc("Norme ESRS S4 révisée : politiques, dialogue, mécanismes de plainte, actions, incidents "
                                      "et cibles sur les consommateurs et utilisateurs finaux.",
                                      "Revised ESRS S4: policies, engagement, grievance mechanisms, actions, incidents and "
                                      "targets on consumers and end-users.")),
    "ESRS_G1": dict(fichier="esrs_g1.json", couleur="#2F6B62", ordre=40,
                    nom=("ESRS G1 – Conduite des affaires", "ESRS G1 – Business conduct"),
                    description=_desc("Norme ESRS G1 révisée : politiques anticorruption et de protection des lanceurs d'alerte, "
                                      "relations avec les fournisseurs, condamnations et amendes, influence politique, "
                                      "pratiques de paiement.",
                                      "Revised ESRS G1: anti-corruption and whistle-blower policies, supplier relationships, "
                                      "convictions and fines, political influence, payment practices.")),
}


def socle(code, version, date, arbre, regles=()):
    """En-tête d'un modèle ESRS (SOCLE) : fichier, couleur, ordre, nom, description et thématique viennent de MODELES."""
    m = MODELES[code]
    return {"code": code, "fichier": m["fichier"], "couleur": m["couleur"], "version": version, "date": date,
            "ordre": m["ordre"], "thematique": THEMATIQUE, "nom": m["nom"], "description": m["description"],
            "arbre": arbre, "regles": list(regles), "traductions": "esrs"}


# ------------------------------------------------------------------ unités nouvelles (les autres : catalogue commun)
UNITES = [  # code (= symbole), symbole anglais, libellé (fr, en), nombre entier, décimales, famille
    ("kg", "kg", ("kilogramme", "kilogram"), False, 0, "Masse"),
    ("factures", "invoices", ("factures", "invoices"), True, 0, "Comptage"),
]


# ------------------------------------------------------------------ listes de choix et tableaux partagés
def liste_choix(code, nom, fr, en):
    assert len(code) <= 20 and len(fr) == len(en), code
    return (code, nom, "liste", {"fr": list(fr), "en": list(en)})


def colonne(code, fr, en, type_="texte", liste="", unite=""):
    c = {"code": code, "libelle": {"fr": fr, "en": en}, "type": type_}
    if liste:
        c["liste"] = liste
    if unite:
        c["unite"] = unite
    return c


def tableau(code, nom, colonnes):
    assert len(code) <= 20, code
    return (code, nom, "tableau", colonnes)


OUI_NON = liste_choix("ESRS-OUI-NON", ("Oui / non (tableau)", "Yes / no (table)"), ("Oui", "Non"), ("Yes", "No"))
OUI_NON_SO = liste_choix("ESRS-OUI-NON-SO", ("Oui / non / sans objet", "Yes / no / not applicable"), ("Oui", "Non", "Sans objet"),
                    ("Yes", "No", "Not applicable"))
HORIZON = liste_choix("ESRS-HORIZON", ("Horizon de temps", "Time horizon"),  # ESRS 1 §79
                 ("Court terme (période de reporting)", "Moyen terme (jusqu'à 5 ans)", "Long terme (plus de 5 ans)"),
                 ("Short term (reporting period)", "Medium term (up to 5 years)", "Long term (more than 5 years)"))
STATUT_ACTION = liste_choix("ESRS-STATUT-ACTION", ("État d'une action", "Status of an action"),
                       ("Réalisée dans la période", "En cours", "Prévue"), ("Taken in the period", "Under way", "Planned"))
NATURE_CIBLE = liste_choix("ESRS-NATURE-CIBLE", ("Cible absolue ou relative", "Absolute or relative target"),
                      ("Absolue", "Relative"), ("Absolute", "Relative"))

COLONNES_ACTIONS = [
    colonne("action", "Action clé", "Key action"),
    colonne("statut", "État", "Status", "liste", "ESRS-STATUT-ACTION"),
    colonne("horizon", "Horizon", "Timeframe", "liste", "ESRS-HORIZON"),
    colonne("perimetre", "Périmètre", "Scope"),
    # montants dans la monnaie des états financiers (ESRS 1 AR 50) : pas d'unité imposée, la description le dit
    colonne("capex", "Dépenses d'investissement de la période", "Capital expenditure of the period", "nombre"),
    colonne("opex", "Dépenses d'exploitation de la période", "Operating expenditure of the period", "nombre"),
    colonne("futur_bas", "Ressources futures, estimation basse", "Future resources, low estimate", "nombre"),
    colonne("futur_haut", "Ressources futures, estimation haute", "Future resources, high estimate", "nombre"),
    colonne("conditions", "Dépend de conditions préalables", "Depends on preconditions", "liste", "ESRS-OUI-NON"),
]


def type_actions(code, nom, colonnes_en_plus=()):
    """Tableau des actions clés d'un sujet (ESRS 2 §45-46), avec les colonnes propres au sujet (E3 : zones de stress
    hydrique)."""
    return tableau(code, nom, COLONNES_ACTIONS + list(colonnes_en_plus))


TYPES_REPONSE = [
    OUI_NON, OUI_NON_SO, HORIZON, STATUT_ACTION, NATURE_CIBLE,
    # jeux de normes possibles (règlement 2026/1563, article 2 : pour un exercice ouvert en 2026, premier jeu, ESRS révisées
    # ou premier jeu avec certains allègements des ESRS révisées) et usage volontaire
    liste_choix("ESRS-VERSION", ("Version des ESRS appliquée", "Version of the ESRS applied"),
           ("ESRS révisées (règlement délégué 2026/1563)", "Premier jeu des ESRS (règlement délégué 2023/2772)",
            "Premier jeu des ESRS avec les allègements de l'article 2(1)(b) du règlement délégué 2026/1563",
            "Pas entièrement conforme / usage volontaire des ESRS"),
           ("Revised ESRS (Delegated Regulation 2026/1563)", "First set of ESRS (Delegated Regulation 2023/2772)",
            "First set of ESRS with the reliefs of Article 2(1)(b) of Delegated Regulation 2026/1563",
            "Not fully compliant / voluntary use of the ESRS")),
    liste_choix("ESRS-RISQUE-CLIMAT", ("Nature d'un risque climatique", "Type of climate-related risk"),
           ("Risque physique", "Risque de transition"), ("Physical risk", "Transition risk")),
    liste_choix("ESRS-SCOPE-CIBLE", ("Scope d'une cible de GES", "Scope of a GHG target"),
           ("Scope 1", "Scope 2 (méthode localisation)", "Scope 2 (méthode marché)", "Scope 3", "Scopes combinés"),
           ("Scope 1", "Scope 2 (location-based)", "Scope 2 (market-based)", "Scope 3", "Scopes combined")),
    liste_choix("ESRS-FORME-CIBLE-GES", ("Cible de GES absolue ou en intensité", "Absolute or intensity GHG target"),
           ("Absolue (tCO2e)", "Intensité"), ("Absolute (tCO2e)", "Intensity")),
    liste_choix("ESRS-NATURE-IRO", ("Nature d'un impact, risque ou opportunité", "Type of impact, risk or opportunity"),
           ("Impact négatif réel", "Impact négatif potentiel", "Impact positif réel", "Impact positif potentiel", "Risque",
            "Opportunité"),
           ("Actual negative impact", "Potential negative impact", "Actual positive impact", "Potential positive impact",
            "Risk", "Opportunity")),
    liste_choix("ESRS-SUJET", ("Sujet des ESRS", "ESRS topic"),  # ESRS 1, appendice A
           ("Changement climatique (E1)", "Pollution (E2)", "Eau (E3)", "Biodiversité et écosystèmes (E4)",
            "Utilisation des ressources et économie circulaire (E5)", "Personnel de l'entreprise (S1)",
            "Travailleurs de la chaîne de valeur (S2)", "Communautés affectées (S3)", "Consommateurs et utilisateurs finaux (S4)",
            "Conduite des affaires (G1)", "Sujet propre à l'entreprise"),
           ("Climate change (E1)", "Pollution (E2)", "Water (E3)", "Biodiversity and ecosystems (E4)",
            "Resource use and circular economy (E5)", "Own workforce (S1)", "Workers in the value chain (S2)",
            "Affected communities (S3)", "Consumers and end-users (S4)", "Business conduct (G1)", "Entity-specific matter")),
    liste_choix("ESRS-CHAINE-POSITION", ("Place dans la chaîne de valeur", "Place in the value chain"),
           ("Activités propres", "Chaîne de valeur amont", "Chaîne de valeur aval", "Plusieurs"),
           ("Own operations", "Upstream value chain", "Downstream value chain", "Several")),
    # tableaux (une ligne par élément ; collecte/tableaux.py : texte court sur une ligne, nombre, valeur d'une liste)
    type_actions("ESRS-TAB-ACTIONS", ("Actions clés", "Key actions")),
    tableau("ESRS-TAB-CIBLES", ("Cibles", "Targets"), [
        colonne("cible", "Cible", "Target"), colonne("indicateur", "Indicateur", "Metric"),
        colonne("nature", "Absolue ou relative", "Absolute or relative", "liste", "ESRS-NATURE-CIBLE"),
        colonne("unite", "Unité", "Unit"),
        colonne("annee_ref", "Année de référence", "Base year", "nombre"),
        colonne("valeur_ref", "Valeur de référence", "Baseline value", "nombre"),
        colonne("annee_etape", "Année d'étape", "Milestone year", "nombre"),
        colonne("valeur_etape", "Valeur d'étape", "Milestone value", "nombre"),
        colonne("annee_cible", "Année cible", "Target year", "nombre"),
        colonne("valeur_cible", "Valeur cible", "Target value", "nombre"),
        colonne("loi", "Imposée par la loi", "Required by law", "liste", "ESRS-OUI-NON"),
        colonne("science", "Fondée sur des preuves scientifiques concluantes", "Based on conclusive scientific evidence", "liste",
             "ESRS-OUI-NON-SO"),
        colonne("perimetre", "Périmètre", "Scope")]),
    tableau("ESRS-TAB-INDICATEURS", ("Indicateurs propres à l'entreprise", "Entity-specific metrics"), [
        colonne("indicateur", "Indicateur", "Metric"), colonne("valeur", "Valeur", "Value", "nombre"), colonne("unite", "Unité", "Unit"),
        colonne("perimetre", "Périmètre", "Scope")]),
    tableau("ESRS-TAB-IRO", ("Impacts, risques et opportunités", "Impacts, risks and opportunities"), [
        colonne("iro", "Impact, risque ou opportunité", "Impact, risk or opportunity"),
        colonne("nature", "Nature", "Type", "liste", "ESRS-NATURE-IRO"), colonne("sujet", "Sujet", "Topic", "liste", "ESRS-SUJET"),
        colonne("chaine", "Place dans la chaîne de valeur", "Place in the value chain", "liste", "ESRS-CHAINE-POSITION"),
        colonne("horizon", "Horizon", "Time horizon", "liste", "ESRS-HORIZON")]),
    tableau("ESRS-TAB-RISQ-CLIM", ("Risques climatiques importants", "Material climate-related risks"), [
        colonne("risque", "Risque", "Risk"), colonne("nature", "Nature", "Type", "liste", "ESRS-RISQUE-CLIMAT")]),
    tableau("ESRS-TAB-CIBLES-GES", ("Cibles de réduction des émissions de GES", "GHG emission reduction targets"), [
        colonne("cible", "Cible", "Target"), colonne("scope", "Scope", "Scope", "liste", "ESRS-SCOPE-CIBLE"),
        colonne("forme", "Absolue ou en intensité", "Absolute or intensity", "liste", "ESRS-FORME-CIBLE-GES"),
        colonne("unite", "Unité", "Unit"),
        colonne("annee_ref", "Année de référence", "Base year", "nombre"),
        colonne("valeur_ref", "Valeur de référence", "Baseline value", "nombre"),
        colonne("annee_etape", "Année d'étape", "Milestone year", "nombre"),
        colonne("valeur_etape", "Valeur d'étape", "Milestone value", "nombre"),
        colonne("annee_cible", "Année cible", "Target year", "nombre"),
        colonne("valeur_cible", "Valeur cible", "Target value", "nombre"),
        colonne("part_scope", "Part de ce scope dans une cible combinée (%)", "Share of this scope in a combined target (%)",
             "nombre"),
        colonne("couverture", "Part de l'inventaire du scope couverte (%)", "Share of the scope inventory covered (%)", "nombre"),
        colonne("gaz", "Gaz couverts", "Gases covered"), colonne("perimetre", "Entités et zones couvertes", "Entities and areas covered")]),
    tableau("ESRS-TAB-LEVIERS", ("Réductions par levier de décarbonation", "Reductions by decarbonisation lever"), [
        colonne("levier", "Levier de décarbonation", "Decarbonisation lever"), colonne("action", "Action", "Action"),
        colonne("obtenue", "Réduction obtenue", "Achieved reduction", "nombre", unite="tCO2e"),
        colonne("attendue", "Réduction attendue", "Expected reduction", "nombre", unite="tCO2e"),
        colonne("horizon", "Horizon", "Time horizon", "liste", "ESRS-HORIZON")]),
    tableau("ESRS-TAB-PROJETS", ("Projets d'absorption et de stockage", "Removal and storage projects"), [
        colonne("projet", "Projet", "Project"), colonne("nature", "Nature (fondée sur la nature, technologique)",
                                                    "Type (nature-based, technological)"),
        colonne("absorptions", "Absorptions et stockage", "Removals and storage", "nombre", unite="tCO2e")]),
    tableau("ESRS-TAB-PRIX-CO2", ("Prix interne du carbone par dispositif", "Internal carbon price by scheme"), [
        colonne("dispositif", "Dispositif", "Scheme"), colonne("usage", "Usage", "Use"),
        colonne("prix", "Prix moyen par tonne de CO2e", "Average price per tonne of CO2e", "nombre")]),
    tableau("ESRS-TAB-HORIZONS", ("Montants par horizon de temps", "Amounts by time horizon"), [
        colonne("horizon", "Horizon", "Time horizon", "liste", "ESRS-HORIZON"),
        colonne("bas", "Montant (ou bas de la fourchette)", "Amount (or low end of the range)", "nombre"),
        colonne("haut", "Haut de la fourchette", "High end of the range", "nombre"),
        colonne("commentaire", "Commentaire", "Comment")]),
    tableau("ESRS-TAB-CLASSE-NRJ", ("Montants par classe énergétique", "Amounts by energy-efficiency class"), [
        colonne("classe", "Classe énergétique (DPE ou kWh/m²)", "Energy-efficiency class (EPC or kWh/m²)"),
        colonne("montant", "Valeur comptable", "Carrying amount", "nombre")]),
    tableau("ESRS-TAB-SVHC", ("Substances extrêmement préoccupantes par classe de danger",
                               "Substances of very high concern by hazard class"), [
        colonne("classe", "Classe de danger (CLP)", "Hazard class (CLP)"),
        colonne("achetees", "Achetées", "Procured", "nombre", unite="t"),
        colonne("fabriquees", "Fabriquées", "Manufactured", "nombre", unite="t"),
        colonne("mises_marche", "Mises sur le marché", "Placed on the market", "nombre", unite="t"),
        colonne("utilisees", "Utilisées", "Used", "nombre", unite="t"),
        colonne("rejetees", "Rejetées dans l'environnement", "Released into the environment", "nombre", unite="t")]),
    tableau("ESRS-TAB-MATIERES", ("Poids des matières clés", "Weight of key materials"), [
        colonne("matiere", "Matière clé", "Key material"), colonne("poids", "Poids", "Weight", "nombre", unite="t")]),
    tableau("ESRS-TAB-RECYCLAB", ("Recyclabilité des produits clés", "Recyclability of key products"), [
        colonne("produit", "Produit clé", "Key product"),
        colonne("taux_produit", "Taux de recyclabilité du produit (%)", "Designed recyclability rate of the product (%)", "nombre"),
        colonne("taux_emballage", "Taux de recyclabilité de l'emballage (%)", "Designed recyclability rate of the packaging (%)",
             "nombre")]),
]


# ------------------------------------------------------------------ exigences générales de l'ESRS 2 (GDR) par sujet
SOURCE_ACTIONS = ("Plans d'action, budget, comptabilité (dépenses d'investissement et d'exploitation).",
                  "Action plans, budget, accounting (capital and operating expenditure).")
SOURCE_CIBLES = ("Stratégie, feuilles de route et tableaux de bord de l'entreprise.",
                 "Company strategy, roadmaps and dashboards.")


def contracter(preposition, groupe):
    """Préposition « à » ou « de » suivie d'un groupe nominal français avec son article, contractée comme le veut la
    langue : « à le personnel » donne « au personnel », « à les communautés » « aux communautés », « de le » « du », « de
    les » « des » ; « à l'eau », « à la pollution » ne changent pas. Seul le premier article est vu : un sujet coordonné
    (« les ressources et l'économie circulaire ») donne sa forme complète au bloc (troisième élément de ``sujet``)."""
    formes = {"à": {"le": "au", "les": "aux"}, "de": {"le": "du", "les": "des"}}[preposition]
    article, _, reste = groupe.partition(" ")
    if article in formes and reste:
        return f"{formes[article]} {reste}"
    return f"{preposition} {groupe}"


def bloc_gdr(prefixe, sujet, social=False, indicateurs=True, type_actions_sujet="ESRS-TAB-ACTIONS"):
    """KPI des exigences générales de l'ESRS 2 pour un sujet : politiques (§42, §39), actions (§45-46), cibles (§51-52) et,
    si le sujet a des indicateurs, méthodes et évolutions des indicateurs (§49). ``sujet`` : (fr avec article, en), par
    exemple ("l'eau", "water"), ou (fr, en, fr après « à ») quand la contraction automatique ne suffit pas (sujet
    coordonné : « aux ressources et à l'économie circulaire »). ``social`` : ajoute la prise en compte des parties
    prenantes (§42(d)). Rend la liste des KPI (couples (code, définition) de ``outils.kpi``) ; ``arbre_gdr`` les place."""
    from referentiel.bibliotheque.outils import kpi

    fr, en = sujet[0], sujet[1]
    a_fr = sujet[2] if len(sujet) > 2 else contracter("à", fr)  # « liés à … » : « au », « aux », « à la », « à l' »

    def oui_non(suffixe, nom, desc):
        return kpi(f"{prefixe}-{suffixe}", nom[0], nom[1], "", "Décompte", reponse="OuiNon", niveau=HAUT, description=desc)

    def texte(suffixe, nom, desc):
        return kpi(f"{prefixe}-{suffixe}", nom[0], nom[1], "", "Aucune", reponse="Texte", niveau=HAUT, description=desc)

    def kpi_tableau(suffixe, nom, type_, desc):
        source = SOURCE_ACTIONS if suffixe.startswith("ACT") else SOURCE_CIBLES
        return kpi(f"{prefixe}-{suffixe}", nom[0], nom[1], "", "Aucune", reponse=type_, niveau=HAUT, description=desc,
                   source=source)

    sortie = [
        oui_non("POLITIQUES", (f"Politiques adoptées sur {fr}", f"Policies adopted on {en}"),
                (f"L'entreprise a-t-elle adopté des politiques pour gérer ses impacts, risques et opportunités importants liés "
                 f"{a_fr} ? Sinon, répondre Non : la norme demande de le dire (ESRS 2 §39).",
                 f"Has the company adopted policies to manage its material impacts, risks and opportunities on {en}? If not, "
                 f"answer No: the standard asks to say so (ESRS 2 §39).")),
        texte("POLIT-CONTENU", (f"Politiques sur {fr} : contenu et changements", f"Policies on {en}: contents and changes"),
              ("Pour chaque politique : son contenu principal, ses objectifs généraux et les impacts, risques ou opportunités "
               "importants qu'elle traite ; décrire les changements faits pendant la période (ESRS 2 §42(a)).",
               "For each policy: its key contents, its general objectives and the material impacts, risks or opportunities it "
               "addresses; describe the changes made during the period (ESRS 2 §42(a)).")),
        texte("POLIT-PERIMETRE", (f"Politiques sur {fr} : périmètre et exclusions", f"Policies on {en}: scope and exclusions"),
              ("Pour chaque politique : son périmètre ou ses exclusions (activités propres, chaîne de valeur amont et aval, "
               "zones géographiques et, s'ils sont définis, groupes de parties prenantes concernés) (ESRS 2 §42(b)).",
               "For each policy: its scope or exclusions (own operations, upstream and downstream value chain, geographies "
               "and, if defined, the affected stakeholder groups) (ESRS 2 §42(b)).")),
        texte("POLIT-REFERENCES", (f"Politiques sur {fr} : normes ou initiatives de tiers",
                                   f"Policies on {en}: third-party standards or initiatives"),
              ("Normes ou initiatives de tiers que l'entreprise s'engage à respecter par ses politiques (ESRS 2 §42(c)). "
               "Répondre N/A si aucune politique n'y renvoie.",
               "Third-party standards or initiatives that the company commits to respect through its policies (ESRS 2 "
               "§42(c)). Answer N/A if no policy refers to one.")),
    ]
    if social:
        sortie.append(texte("POLIT-PARTIES", (f"Politiques sur {fr} : intérêts des parties prenantes concernées",
                                              f"Policies on {en}: interests of affected stakeholders"),
                            ("Comment les intérêts des parties prenantes concernées ont été pris en compte pour fixer chaque "
                             "politique, s'ils l'ont été (ESRS 2 §42(d)).",
                             "How the interests of affected stakeholders were considered in setting each policy, if they were "
                             "(ESRS 2 §42(d)).")))
    sortie += [
        oui_non("ACTIONS", (f"Actions clés sur {fr}", f"Key actions on {en}"),
                (f"L'entreprise a-t-elle mené ou prévu des actions clés pour gérer ses impacts, risques et opportunités "
                 f"importants liés {a_fr} ? Sinon, répondre Non (ESRS 2 §39).",
                 f"Has the company taken or planned key actions to manage its material impacts, risks and opportunities on "
                 f"{en}? If not, answer No (ESRS 2 §39).")),
        texte("ACT-DESC", (f"Actions clés sur {fr} : description, périmètre et résultats attendus",
                           f"Key actions on {en}: description, scope and expected outcomes"),
              ("Actions clés menées pendant la période et prévues, avec leur calendrier, leur périmètre (activités propres, "
               "chaîne de valeur, filiales, zones géographiques, parties prenantes) et leurs résultats attendus, et comment "
               "elles servent les objectifs des politiques (ESRS 2 §45).",
               "Key actions taken during the period and planned, with their timeframe, their scope (own operations, value "
               "chain, subsidiaries, geographies, stakeholders) and their expected outcomes, and how they serve the policy "
               "objectives (ESRS 2 §45).")),
        kpi_tableau("ACT-TAB", (f"Actions clés sur {fr} : calendrier et ressources financières",
                            f"Key actions on {en}: timeframe and financial resources"), type_actions_sujet,
                ("Une ligne par action clé : état, horizon, périmètre, dépenses d'investissement et d'exploitation de la "
                 "période, fourchette des ressources futures, et si l'action dépend de conditions préalables (ESRS 2 §45-46). "
                 "Les montants seulement quand des ressources importantes y sont consacrées." + MONNAIE_TABLEAU[0],
                 "One row per key action: status, timeframe, scope, capital and operating expenditure of the period, range of "
                 "future resources, and whether the action depends on preconditions (ESRS 2 §45-46). Amounts only when "
                 "significant resources are allocated." + MONNAIE_TABLEAU[1])),
        texte("ACT-MOYENS", (f"Actions clés sur {fr} : nature des ressources, conditions et postes comptables",
                             f"Key actions on {en}: type of resources, preconditions and line items"),
              ("Quand des ressources financières importantes sont consacrées aux actions : leur nature (actuelles et futures), "
               "les conditions préalables dont les actions dépendent (aide financière, politiques publiques, marché) et les "
               "postes ou notes des états financiers qui contiennent les montants (ESRS 2 §46).",
               "When significant financial resources are allocated to the actions: their type (current and future), the "
               "preconditions the actions depend on (financial support, public policy, market) and the line items or notes "
               "of the financial statements that contain the amounts (ESRS 2 §46).")),
        oui_non("CIBLES", (f"Cibles mesurables sur {fr}", f"Measurable targets on {en}"),
                (f"L'entreprise a-t-elle fixé des cibles mesurables, datées et axées sur les résultats pour {fr} ? Sinon, "
                 f"répondre Non et décrire ci-dessous comment elle suit l'efficacité de ses politiques et actions (ESRS 2 §52).",
                 f"Has the company set measurable, time-bound and outcome-oriented targets on {en}? If not, answer No and "
                 f"describe below how it tracks the effectiveness of its policies and actions (ESRS 2 §52).")),
        kpi_tableau("CIB-TAB", (f"Cibles sur {fr} : valeurs, années et périmètre", f"Targets on {en}: values, years and scope"),
                "ESRS-TAB-CIBLES",
                ("Une ligne par cible : indicateur et unité, cible absolue ou relative, valeur et année de référence, étape, "
                 "valeur et année cibles, imposée par la loi ou non, fondée ou non sur des preuves scientifiques concluantes "
                 "(sujets environnementaux), périmètre (ESRS 2 §51).",
                 "One row per target: metric and unit, absolute or relative target, baseline value and year, milestone, target "
                 "value and year, whether it is required by law, whether it is based on conclusive scientific evidence "
                 "(environmental topics), scope (ESRS 2 §51).")),
        texte("CIB-DESC", (f"Cibles sur {fr} : lien avec les politiques, étapes, méthodes et scénarios",
                           f"Targets on {en}: link to policies, milestones, methods and scenarios"),
              ("Pour chaque cible : son lien avec les objectifs des politiques et les actions, les étapes ou cibles "
               "intermédiaires, les méthodes et hypothèses importantes et, le cas échéant, les scénarios, les principales "
               "sources de données et la compatibilité avec les objectifs nationaux, européens ou internationaux (ESRS 2 "
               "§51(a), (e), (f), (h)).",
               "For each target: its link to the policy objectives and actions, the milestones or interim targets, the methods "
               "and significant assumptions and, where applicable, the scenarios, the key data sources and the compatibility "
               "with national, EU or international policy goals (ESRS 2 §51(a), (e), (f), (h)).")),
        texte("SUIVI-SS-CIBLE", (f"Suivi de l'efficacité sans cible sur {fr}", f"Tracking of effectiveness without targets on {en}"),
              ("Seulement si aucune cible mesurable n'est fixée : si et comment l'entreprise suit malgré tout l'efficacité de "
               "ses politiques et actions (ESRS 2 §52). Répondre N/A si des cibles sont fixées.",
               "Only if no measurable target is set: whether and how the company still tracks the effectiveness of its "
               "policies and actions (ESRS 2 §52). Answer N/A if targets are set.")),
    ]
    if indicateurs:
        sortie += [
            texte("METHODES", (f"Indicateurs sur {fr} : méthodes, sources, chaîne de valeur et contexte",
                               f"Metrics on {en}: methods, sources, value chain data and context"),
                  ("Pour chaque indicateur : unité, méthode de calcul et sources, méthode d'estimation avec ses hypothèses et "
                   "limites importantes ; pour un indicateur de la chaîne de valeur, part des données indirectes ou "
                   "approchées et améliorations prévues ; informations de contexte (ESRS 2 §49(a) à (c)).",
                   "For each metric: unit, calculation method and sources, estimation method with its significant "
                   "assumptions and limitations; for a value chain metric, reliance on indirect sources or proxies and the "
                   "planned improvements; contextual information (ESRS 2 §49(a) to (c)).")),
            texte("EVOLUTION", (f"Indicateurs sur {fr} : évolutions importantes et progrès",
                                f"Metrics on {en}: significant changes and progress"),
                  ("Évolutions importantes des résultats par rapport aux périodes précédentes, progrès vers les cibles et "
                   "effet des acquisitions ou cessions importantes (ESRS 2 §49(d)).",
                   "Significant changes in performance compared with the previous periods, progress towards the targets and "
                   "effect of major acquisitions or disposals (ESRS 2 §49(d)).")),
        ]
    return sortie


def arbre_gdr(prefixe, dr, partie, social=False):
    """KPI d'une partie du bloc GDR, avec leur référence, à placer dans un thème de l'arbre. ``dr`` : l'exigence de la
    norme (``"E3-1"``) ; ``partie`` : « P » (politiques), « A » (actions), « T » (cibles) ou « M » (indicateurs)."""
    parties = {
        "P": [("POLITIQUES", "ESRS 2 §39"), ("POLIT-CONTENU", "ESRS 2 §42(a)"), ("POLIT-PERIMETRE", "ESRS 2 §42(b)"),
              ("POLIT-REFERENCES", "ESRS 2 §42(c)")] + ([("POLIT-PARTIES", "ESRS 2 §42(d)")] if social else []),
        "A": [("ACTIONS", "ESRS 2 §39"), ("ACT-DESC", "ESRS 2 §45"), ("ACT-TAB", "ESRS 2 §45-46"), ("ACT-MOYENS", "ESRS 2 §46")],
        "T": [("CIBLES", "ESRS 2 §39"), ("CIB-TAB", "ESRS 2 §51"), ("CIB-DESC", "ESRS 2 §51"), ("SUIVI-SS-CIBLE", "ESRS 2 §52")],
        "M": [("METHODES", "ESRS 2 §49(a)-(c)"), ("EVOLUTION", "ESRS 2 §49(d)")],
    }
    return [(f"{prefixe}-{s}", f"{dr} · {ref}") for s, ref in parties[partie]]
