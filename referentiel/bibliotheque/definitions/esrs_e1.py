"""ESRS E1 Changement climatique (ESRS révisées, règlement délégué (UE) 2026/1563) : lot B de la famille ESRS, construit
sur le modèle de esrs_e3.py (méthode : note de conception de l'atelier, non publiée ; socle commun : _esrs_communs.py).

Inventaire : lignes « ESRS_E1 » de esrs_coverage.csv (87 points de la liste de l'EFRAG du 28/08/2026, plus trois exigences
du règlement absentes de la liste : GDR-M et §30(b), §30(c), AR 24(g)). Choix :

- politiques, actions et cibles : bloc commun des exigences générales de l'ESRS 2 (``bloc_gdr``), saisi une fois pour
  l'entreprise ; tableaux propres au climat : cibles de réduction des GES (scope, absolue ou en intensité, part d'un scope
  dans une cible combinée, couverture de l'inventaire, gaz), réductions par levier de décarbonation, projets d'absorption,
  prix interne du carbone, montants par horizon de temps (E1-11) ;
- énergie (E1-7) : la chaîne de la norme volontaire VS (B3) est reprise telle quelle (mêmes KPI, une seule saisie) ; l'ESRS
  ajoute la répartition fossile / nucléaire / renouvelable de l'énergie achetée et la répartition des combustibles
  fossiles. Deux parts sont calculées par différence, de façon prudente (E1 AR 18(i)) : l'énergie achetée d'origine
  fossile (achetée − nucléaire − renouvelable) et les « autres sources fossiles » (autres combustibles fossiles de la VS −
  charbon − autres produits pétroliers). Les trois parts de l'énergie totale et les cinq parts de l'énergie fossile
  s'additionnent donc toujours exactement ; une règle de cohérence signale une part négative ;
- GES (E1-8) : scope 1 brut = scope 1 de la VS (combustion et fugitives) + autres émissions directes de la VS ; scope 2
  (localisation) de la VS ; scope 2 (marché) de la VS (facultatif dans la VS, obligatoire ici) ; scope 3 = les quinze
  catégories (dix du catalogue commun, cinq de la VS) et leur total ; part du SEQE-UE recalculée à chaque niveau ;
  répartition groupe consolidé / hors groupe (§30(c)) : part hors groupe saisie pour l'entreprise, part du groupe
  calculée ; émissions biogéniques à part ;
- aucun indicateur d'intensité des GES : l'E1-8 révisée n'en demande plus (seules les cibles peuvent être en intensité,
  colonne du tableau des cibles) ; pas de total des scopes 1, 2 et 3 non plus ;
- mesures transitoires (ESRS 1 §125 à 127) : une phrase dans la description des KPI de l'E1-11 concernés ; la mesure
  générale (toutes les normes thématiques omises avant 2027 par certaines entreprises de la première vague, §126(a)) vaut
  pour tout le modèle.

Réutilisations et refus (texte des deux normes à l'appui) : revue des doublons de l'atelier, section du lot B.
"""
from referentiel.bibliotheque.outils import ZERO, ZERO_EN, kpi

from . import _esrs_communs as C
from . import _esrs_lot_e as L

SOURCE = C.SOURCE
COUVERTURE = C.COUVERTURE
UNITES = C.UNITES
TYPES_REPONSE = C.TYPES_REPONSE

PREFIXE = "CLI"
HAUT, ENTITE = C.HAUT, C.ENTITE

# ------------------------------------------------------------------ sources des données
S_PLAN = ("Plan de transition, stratégie climat, décisions de l'organe d'administration.",
          "Transition plan, climate strategy, decisions of the administrative body.")
S_RISQUES = ("Cartographie des risques, analyse de scénarios climatiques, études de vulnérabilité des sites.",
             "Risk map, climate scenario analysis, vulnerability studies of the sites.")
S_COMPTA = ("Comptabilité, états financiers, contrôle de gestion.", "Accounting, financial statements, management control.")
S_ENERGIE = ("Contrats et attestations des fournisseurs d'énergie (mix énergétique, garanties d'origine), factures.",
             "Contracts and certificates of the energy suppliers (energy mix, guarantees of origin), invoices.")
S_COMBUSTIBLES = ("Factures, bons de livraison, compteurs.", "Invoices, delivery notes, meters.")
S_PRODUCTION = ("Compteurs de production, contrats de vente d'énergie.", "Production meters, energy sale contracts.")
S_GES = ("Bilan des émissions de gaz à effet de serre.", "Greenhouse gas emissions inventory.")
S_SEQE = ("Déclarations d'émissions vérifiées du SEQE-UE (registre de l'Union).",
          "Verified emissions reports of the EU ETS (Union Registry).")
S_CREDITS = ("Contrats d'achat, certificats d'annulation des registres de crédits carbone.",
             "Purchase contracts, cancellation certificates of the carbon credit registries.")

# Mesures transitoires de l'E1-11 (ESRS 1 §125(b)-(c), §126(b)-(c), §127(b)-(c)) ; 39(a)(b) et 40(a)(b) n'en ont pas.
PHASE_QUANTI = (" Mesure transitoire (ESRS 1 §125 à 127) : une entreprise de la première vague peut omettre ce montant pour "
                "les exercices antérieurs à 2030, une autre entreprise pour ses quatre premiers exercices de reporting.",
                " Phase-in (ESRS 1 §125-127): a wave-one company may omit this amount for financial years before 2030, another "
                "company for its first four financial years of reporting.")
PHASE_METHODE = (" Mesure transitoire (ESRS 1 §125 à 127) : une entreprise de la première vague peut omettre cette information "
                 "pour les exercices antérieurs à 2028, une autre entreprise pour ses deux premiers exercices de reporting.",
                 " Phase-in (ESRS 1 §125-127): a wave-one company may omit this information for financial years before 2028, "
                 "another company for its first two financial years of reporting.")
SECTEURS = (" Seulement pour une entreprise qui a des activités dans les secteurs à fort impact climatique (sections A à H et "
            "L de la NACE, glossaire) ; sinon, répondre N/A.",
            " Only for a company with operations in high climate impact sectors (NACE sections A to H and L, glossary); "
            "otherwise, answer N/A.")
HORIZONS = (" Une ligne par horizon de temps (court, moyen, long terme), un montant ou une fourchette (E1 AR 29), dans la "
            "monnaie des états financiers (ESRS 1 AR 50).",
            " One row per time horizon (short, medium, long term), a single amount or a range (E1 AR 29), in the currency of "
            "the financial statements (ESRS 1 AR 50).")


def _d(fr, en, zero=False, suite=("", "")):
    """Description (fr, en), avec la phrase « Saisir 0 s'il n'y en a pas » pour une donnée additionnée et une suite
    (condition, mesure transitoire)."""
    return (fr + (ZERO if zero else "") + suite[0], en + (ZERO_EN if zero else "") + suite[1])


def texte(code, fr, en, description, source=""):
    return kpi(code, fr, en, "", "Aucune", reponse="Texte", niveau=HAUT, description=description, source=source)


def oui_non(code, fr, en, description):
    return kpi(code, fr, en, "", "Décompte", reponse="OuiNon", niveau=HAUT, description=description)


def tableau(code, fr, en, type_, description, source):
    return kpi(code, fr, en, "", "Aucune", reponse=type_, niveau=HAUT, description=description, source=source)


KPIS = dict([
    *C.bloc_gdr(PREFIXE, ("le changement climatique", "climate change")),  # « liés au changement climatique »
    # ------------------------------------------------------------------ E1-1 – plan de transition
    texte("CLI-PLAN-TRANSITION", "Plan de transition pour l'atténuation : principales caractéristiques",
          "Transition plan for climate change mitigation: key features",
          ("Principales caractéristiques du plan : cibles de réduction des GES, leviers de décarbonation, actions clés, "
           "investissements et financements nécessaires, approbation par les organes d'administration, de direction ou de "
           "surveillance, et intégration dans la stratégie de l'entreprise. Dire comment la stratégie et le modèle d'affaires "
           "sont ou seront compatibles avec la limitation du réchauffement à 1,5 °C et la neutralité climatique de l'Union en "
           "2050, en renvoyant aux informations des E1-5 et E1-6 ; dire si le plan couvre aussi l'adaptation (ESRS E1, §12(a) ; "
           "AR 1, AR 2).",
           "Key features of the plan: GHG emission reduction targets, decarbonisation levers, key actions, investments and "
           "funding needed, approval by the administrative, management and supervisory bodies, and how the plan is embedded "
           "in the company's strategy. Say how the strategy and business model are or will be compatible with limiting "
           "global warming to 1.5 °C and with EU climate neutrality by 2050, with references to the E1-5 and E1-6 "
           "disclosures; say whether the plan also covers adaptation (ESRS E1, §12(a); AR 1, AR 2)."), S_PLAN),
] + [
    kpi(code, f"Dépenses d'investissement liées au {fr_c}", f"CapEx related to {en_c}", "€", niveau=ENTITE,
        description=_d(f"Dépenses d'investissement de la période dans des activités économiques liées au {fr_c} "
                       "(ESRS E1, §12(b)). Activités visées par la note du règlement : extraction de charbon et de lignite, "
                       "extraction de pétrole brut et activités de soutien, cokéfaction et raffinage, production et "
                       "distribution d'électricité, production de vapeur ou de chaleur au charbon ou au fioul, commerce de "
                       "gros de combustibles solides et liquides (NACE B.05, B.06, B.09.1, C.19, D.35.1, D.35.3, D.46.81). "
                       "Seulement si l'entreprise a de telles dépenses ; sinon, répondre N/A.",
                       f"Capital expenditure of the period in economic activities related to {en_c} (ESRS E1, "
                       "§12(b)). Activities named in the footnote of the regulation: mining of coal and lignite, extraction "
                       "of crude petroleum and support activities, coke and refined petroleum products, electric power "
                       "generation and distribution, coal-fired or oil-fired steam or heat supply, wholesale of solid and "
                       "liquid fuels (NACE B.05, B.06, B.09.1, C.19, D.35.1, D.35.3, D.46.81). Only if the company has "
                       "such expenditure; otherwise, answer N/A.", suite=C.MONNAIE),
        source=S_COMPTA)
    for code, fr_c, en_c in (("CLI-CAPEX-CHARBON", "charbon", "coal"), ("CLI-CAPEX-PETROLE", "pétrole", "oil"),
                             ("CLI-CAPEX-GAZ", "gaz", "gas"))
] + [
    texte("CLI-PLAN-HYPOTHESES", "Plan de transition : hypothèses clés et dépendances",
          "Transition plan: key assumptions and dependencies",
          ("Hypothèses clés du plan (évolution de la réglementation, capacité à changer la chaîne de valeur…) et dépendances "
           "dont il dépend (déploiement de technologies, main-d'œuvre disponible, ressources financières futures) (ESRS E1, "
           "§12(c) ; AR 3).",
           "Key assumptions of the plan (changes in regulation, ability to change the value chain…) and the dependencies it "
           "relies on (deployment of technologies, availability of workforce, future financial resources) (ESRS E1, §12(c); "
           "AR 3)."), S_PLAN),
    texte("CLI-PLAN-VERROUILLAGE", "Plan de transition : émissions verrouillées des actifs et produits clés",
          "Transition plan: locked-in emissions of key assets and products",
          ("Évaluation qualitative : comment les émissions de GES potentiellement verrouillées par les principaux actifs "
           "physiques et produits peuvent compromettre le plan et créer un risque de transition, selon leur ampleur (ESRS E1, "
           "§12(d) ; AR 4).",
           "Qualitative assessment: how the GHG emissions potentially locked in by the key physical assets and products may "
           "put the plan at risk and drive transition risk, according to their size (ESRS E1, §12(d); AR 4)."), S_PLAN),
    texte("CLI-PLAN-AVANCEMENT", "Plan de transition : avancement de la mise en œuvre",
          "Transition plan: progress in implementation",
          ("Avancement de la mise en œuvre du plan, avec des éléments chiffrés et qualitatifs : ressources engagées (montants), "
           "actions menées, réductions d'émissions obtenues ou attendues et, le cas échéant, indicateurs sectoriels de suivi "
           "des cibles (ESRS E1, §12(e) ; AR 5).",
           "Progress in implementing the plan, with quantitative and qualitative elements: resources deployed (amounts), "
           "actions taken, emission reductions achieved or expected and, where applicable, sector-specific metrics to track "
           "the targets (ESRS E1, §12(e); AR 5)."), S_PLAN),
    # ------------------------------------------------------------------ E1-2 – risques climatiques et scénarios
    tableau("CLI-RISQUES-TAB", "Risques climatiques importants : risque physique ou de transition",
            "Material climate-related risks: physical or transition risk", "ESRS-TAB-RISQ-CLIM",
            ("Une ligne par risque climatique important identifié par l'analyse de matérialité (ESRS 2 IRO-2) : le risque, et "
             "s'il est classé comme risque physique ou comme risque de transition (ESRS E1, §15).",
             "One row per material climate-related risk identified by the materiality assessment (ESRS 2 IRO-2): the risk, "
             "and whether it is classified as a physical risk or a transition risk (ESRS E1, §15)."), S_RISQUES),
    texte("CLI-METHODE-ALEAS", "Méthode d'évaluation de l'exposition aux aléas climatiques",
          "Method to assess exposure to climate-related hazards",
          ("Éléments clés de la méthode qui évalue comment les actifs et les activités (activités propres, chaîne de valeur "
           "amont et aval) peuvent être exposés et sensibles aux aléas climatiques à court, moyen et long terme : aléas "
           "identifiés, sélection des actifs, localisation, probabilité, ampleur et durée (ESRS E1, §16(a) ; AR 6).",
           "Key elements of the method that assesses how the assets and business activities (own operations, upstream and "
           "downstream value chain) may be exposed and sensitive to climate-related hazards over the short, medium and long "
           "term: hazards identified, screening of assets, locations, likelihood, magnitude and duration (ESRS E1, §16(a); "
           "AR 6)."), S_RISQUES),
    texte("CLI-METHODE-TRANSITION", "Méthode d'évaluation de l'exposition aux événements de transition",
          "Method to assess exposure to transition events",
          ("Éléments clés de la méthode qui évalue comment les actifs et les activités (activités propres, chaîne de valeur "
           "amont et aval) peuvent être exposés et sensibles aux événements et tendances de la transition climatique "
           "(réglementation, technologie, marché, réputation) à court, moyen et long terme (ESRS E1, §16(b) ; AR 6).",
           "Key elements of the method that assesses how the assets and business activities (own operations, upstream and "
           "downstream value chain) may be exposed and sensitive to climate-related transition events and trends (policy, "
           "technology, market, reputation) over the short, medium and long term (ESRS E1, §16(b); AR 6)."), S_RISQUES),
    oui_non("CLI-SCENARIOS-UTILISES", "Analyse de scénarios climatiques utilisée", "Climate-related scenario analysis used",
            ("L'entreprise utilise-t-elle une analyse de scénarios climatiques pour identifier et évaluer ses risques "
             "climatiques ? Si non, répondre N/A aux questions suivantes de l'E1-2 sur les scénarios (ESRS E1, §17 ; AR 6).",
             "Does the company use climate-related scenario analysis to identify and assess its climate-related risks? If "
             "not, answer N/A to the next E1-2 questions on scenarios (ESRS E1, §17; AR 6).")),
    texte("CLI-SCENARIOS", "Scénarios climatiques appliqués", "Climate-related scenarios applied",
          ("Seulement si une analyse de scénarios est utilisée : la gamme des scénarios climatiques appliqués (noms, sources, "
           "par exemple ceux du GIEC ou de l'AIE) (ESRS E1, §17(a)).",
           "Only if scenario analysis is used: the range of climate-related scenarios applied (names, sources, for example "
           "IPCC or IEA scenarios) (ESRS E1, §17(a)).")),
    oui_non("CLI-SCEN-EMISSIONS-ELEVEES", "Scénario à émissions élevées utilisé pour les risques physiques",
            "High-emission scenario used for physical risks",
            ("Seulement si une analyse de scénarios est utilisée : au moins un scénario à émissions élevées a-t-il servi à "
             "évaluer les risques physiques (ESRS E1, §17(a)(i)) ?",
             "Only if scenario analysis is used: was at least one high-emission scenario used to assess the physical risks "
             "(ESRS E1, §17(a)(i))?")),
    oui_non("CLI-SCEN-1-5", "Scénario compatible avec 1,5 °C utilisé pour les risques de transition",
            "1.5 °C scenario used for transition risks",
            ("Seulement si une analyse de scénarios est utilisée : au moins un scénario compatible avec la limitation du "
             "réchauffement à 1,5 °C, sans dépassement ou avec un dépassement limité, a-t-il servi à évaluer les risques de "
             "transition (ESRS E1, §17(a)(ii)) ?",
             "Only if scenario analysis is used: was at least one scenario in line with limiting global warming to 1.5 °C, "
             "with no or limited overshoot, used to assess the transition risks (ESRS E1, §17(a)(ii))?")),
    texte("CLI-SCEN-TEMPERATURE", "Scénarios : projections de température et pertinence",
          "Scenarios: temperature projections and relevance",
          ("Seulement si une analyse de scénarios est utilisée : projection de la température moyenne mondiale associée à "
           "chaque scénario, et pourquoi ces scénarios sont jugés pertinents (ESRS E1, §17(a)(iii)).",
           "Only if scenario analysis is used: the global average temperature projection of each scenario, and why these "
           "scenarios are considered relevant (ESRS E1, §17(a)(iii)).")),
    texte("CLI-SCEN-PERIMETRE", "Scénarios : périmètre des activités analysées", "Scenarios: scope of operations",
          ("Seulement si une analyse de scénarios est utilisée : périmètre retenu (sites, unités d'affaires, chaîne de "
           "valeur) (ESRS E1, §17(b)).",
           "Only if scenario analysis is used: the scope of operations used (operating locations, business units, value "
           "chain) (ESRS E1, §17(b)).")),
    texte("CLI-SCEN-HYPOTHESES", "Scénarios : hypothèses clés", "Scenarios: key assumptions",
          ("Seulement si une analyse de scénarios est utilisée : hypothèses clés (politiques publiques, tendances "
           "macroéconomiques, variables nationales ou régionales, consommation et mix énergétiques, évolution des "
           "technologies) (ESRS E1, §17(c)).",
           "Only if scenario analysis is used: key assumptions (public policies, macroeconomic trends, national or regional "
           "variables, energy use and mix, technology developments) (ESRS E1, §17(c)).")),
    kpi("CLI-SCEN-ANNEE", "Année de l'analyse de scénarios", "Year of the scenario analysis", "année", "Aucune",
        temps="derniere", niveau=HAUT,
        description=("Seulement si une analyse de scénarios est utilisée : année où elle a été réalisée (ESRS E1, §17(d)).",
                     "Only if scenario analysis is used: year when it was carried out (ESRS E1, §17(d))."),
        source=S_RISQUES),
    # ------------------------------------------------------------------ E1-3 – résilience
    texte("CLI-RESILIENCE", "Résilience climatique : résultats de l'analyse", "Climate resilience: results of the analysis",
          ("Résultats de l'analyse de la résilience de la stratégie et du modèle d'affaires face aux risques climatiques, "
           "à la date de clôture : conséquences pour la stratégie et le modèle d'affaires, usage des résultats de l'analyse "
           "de scénarios s'il y en a une, contribution du plan de transition et des actions d'atténuation et d'adaptation "
           "(ESRS E1, §19(a) ; AR 7 à AR 9).",
           "Results of the analysis of the resilience of the strategy and business model to climate-related risks, at the "
           "reporting date: implications for the strategy and business model, use of the results of the scenario analysis "
           "if any, contribution of the transition plan and of the mitigation and adaptation actions (ESRS E1, §19(a); "
           "AR 7 to AR 9)."), S_RISQUES),
    texte("CLI-RESILIENCE-INCERTITUDES", "Résilience climatique : principales incertitudes",
          "Climate resilience: significant areas of uncertainty",
          ("Principales zones d'incertitude de l'évaluation de la résilience climatique (ESRS E1, §19(b) ; AR 7, AR 8).",
           "Significant areas of uncertainty in the assessment of climate resilience (ESRS E1, §19(b); AR 7, AR 8).")),
    texte("CLI-RESILIENCE-ADAPTATION", "Résilience climatique : capacité d'adaptation par horizon",
          "Climate resilience: capacity to adapt by time horizon",
          ("Capacité à ajuster ou adapter la stratégie et le modèle d'affaires au changement climatique à court, moyen et "
           "long terme : ressources financières disponibles, possibilité de réaffecter, moderniser ou fermer des actifs, effet "
           "des investissements en cours et prévus (ESRS E1, §19(c) ; AR 10).",
           "Capacity to adjust or adapt the strategy and business model to climate change over the short, medium and long "
           "term: available financial resources, ability to redeploy, upgrade or decommission assets, effect of current and "
           "planned investments (ESRS E1, §19(c); AR 10).")),
    # ------------------------------------------------------------------ E1-5 – actions par levier
    texte("CLI-ACTIONS-LEVIERS", "Actions d'atténuation par levier de décarbonation",
          "Mitigation actions by decarbonisation lever",
          ("Actions clés d'atténuation, menées et prévues, regroupées par levier de décarbonation (efficacité énergétique, "
           "efficacité matière, changement de combustible, électrification, énergie renouvelable, changement de produit ou de "
           "procédé…) (ESRS E1, §22(a)).",
           "Key mitigation actions, taken and planned, grouped by decarbonisation lever (energy efficiency, material "
           "efficiency, fuel switching, electrification, renewable energy, change of product or process…) (ESRS E1, "
           "§22(a)).")),
    tableau("CLI-LEVIERS-TAB", "Réductions des émissions de GES par levier de décarbonation",
            "GHG emission reductions by decarbonisation lever", "ESRS-TAB-LEVIERS",
            ("Une ligne par levier (ou par action d'un levier) : réduction des émissions de GES obtenue et réduction "
             "attendue, en tCO2e, avec l'horizon (ESRS E1, §22(b) ; présentation possible avec les cibles, AR 15).",
             "One row per lever (or per action of a lever): GHG emission reduction achieved and expected, in tCO2e, with the "
             "time horizon (ESRS E1, §22(b); possible presentation with the targets, AR 15)."), S_PLAN),
    # ------------------------------------------------------------------ E1-6 – cibles de réduction des GES
    texte("CLI-ZERO-NET-RESIDUEL", "Cible de zéro émission nette : neutralisation des émissions résiduelles",
          "Net-zero target: neutralisation of residual emissions",
          ("Seulement si l'entreprise publie une cible de zéro émission nette à côté de ses cibles de réduction : comment "
           "elle prévoit de neutraliser durablement ses émissions résiduelles. Sinon, répondre N/A (ESRS E1, AR 11 pour §23).",
           "Only if the company discloses a net-zero target next to its reduction targets: how it intends to permanently "
           "neutralise its residual emissions. Otherwise, answer N/A (ESRS E1, AR 11 for §23).")),
    tableau("CLI-CIBLES-GES-TAB", "Cibles de réduction des émissions de GES", "GHG emission reduction targets",
            "ESRS-TAB-CIBLES-GES",
            ("Les cibles absolues des scopes 1 et 2 qui ont une seule année de référence et une seule année cible se saisissent "
             "dans « Cibles absolues des scopes 1 et 2 » ci-dessus, sans les répéter ici ; ce tableau reçoit les autres "
             "cibles, et une ligne pour l'étape, la part couverte ou les gaz d'une cible absolue quand il y en a. Une ligne "
             "par cible et par scope : scope (1, 2 selon la méthode localisation ou marché, 3, ou scopes combinés), "
             "cible absolue (tCO2e) ou en intensité (unité d'activité physique ou économique), année et valeur de référence, "
             "étapes, année et valeur cibles. Pour une cible combinée : la part de chaque scope (une ligne par scope). Si le "
             "périmètre de la cible (zones, gaz, entités) diffère de celui de l'inventaire de l'E1-8 : la part de chaque scope "
             "couverte et les gaz couverts. Les cibles sont brutes : ni absorptions, ni crédits carbone, ni émissions évitées. "
             "Une cible seulement en intensité donne aussi ses valeurs absolues pour l'année cible et les étapes (ESRS E1, "
             "§24(a)-(b) ; AR 12 à AR 16).",
             "Absolute scope 1 and 2 targets with a single base year and a single target year are entered in “Absolute scope 1 "
             "and 2 targets” above, without repeating them here; this table takes the other targets, and a row for the "
             "milestone, the share covered or the gases of an absolute target when there are any. One row per target and per "
             "scope: scope (1, 2 location-based or market-based, 3, or combined scopes), absolute "
             "target (tCO2e) or intensity target (unit of physical activity or economic output), base year and baseline "
             "value, milestones, target year and value. For a combined target: the share of each scope (one row per scope). "
             "If the scope of the target (areas, gases, entities) differs from the E1-8 inventory: the share of each scope "
             "covered and the gases covered. Targets are gross: no removals, carbon credits or avoided emissions. A target "
             "set only in intensity also gives its absolute values for the target year and the milestones (ESRS E1, "
             "§24(a)-(b); AR 12 to AR 16)."), S_PLAN),
    oui_non("CLI-CIBLES-SCIENCE", "Cibles de GES fondées sur la science et compatibles avec 1,5 °C",
            "GHG targets science-based and compatible with 1.5 °C",
            ("Les cibles de réduction des émissions de GES sont-elles fondées sur la science et compatibles avec la limitation "
             "du réchauffement à 1,5 °C (ESRS E1, §24(c) ; AR 17) ?",
             "Are the GHG emission reduction targets science-based and compatible with limiting global warming to 1.5 °C "
             "(ESRS E1, §24(c); AR 17)?")),
    texte("CLI-CIBLES-REFERENCE", "Cibles de GES : cadre, méthode et comparaison avec 1,5 °C",
          "GHG targets: framework, method and comparison with 1.5 °C",
          ("Cadre et méthode qui ont servi à fixer les cibles, scénarios climatiques et politiques sous-jacents, et comparaison "
           "des valeurs cibles avec une valeur de référence alignée sur 1,5 °C (scopes 1 et 2, et scope 3 s'il a une cible), "
           "issue d'une trajectoire sectorielle si elle existe ou intersectorielle ; validation par un tiers le cas échéant. "
           "Une cible non compatible avec 1,5 °C s'explique ici (ESRS E1, §24(c) ; AR 2(a), AR 17).",
           "Framework and method used to set the targets, underlying climate and policy scenarios, and comparison of the "
           "target values with a 1.5 °C-aligned reference value (scopes 1 and 2, and scope 3 if it has a target), from a "
           "sector-specific pathway if one exists, otherwise cross-sector; validation by a third party if any. A target that "
           "is not compatible with 1.5 °C is explained here (ESRS E1, §24(c); AR 2(a), AR 17).")),
    oui_non("CLI-CIBLES-SECTORIEL", "Cibles de GES issues d'une trajectoire sectorielle de décarbonation",
            "GHG targets derived from a sectoral decarbonisation pathway",
            ("Le cadre et la méthode qui ont fixé les cibles de GES s'appuient-ils sur une trajectoire de décarbonation propre "
             "au secteur (ESRS E1, §24(c)) ?",
             "Are the framework and method used to set the GHG targets derived from a sectoral decarbonisation pathway "
             "(ESRS E1, §24(c))?")),
    texte("CLI-CIBLES-EVOLUTIONS", "Cibles de GES : évolutions futures prises en compte",
          "GHG targets: future developments considered",
          ("Parmi les hypothèses critiques des cibles : comment l'entreprise a pris en compte les évolutions futures "
           "(volumes de ventes, préférences et demande des clients, réglementation, nouvelles technologies) et leur effet "
           "possible sur ses émissions et sur ses réductions d'émissions (ESRS E1, §24(c)).",
           "Among the critical assumptions of the targets: how the company has considered future developments (sales volumes, "
           "customer preferences and demand, regulation, new technologies) and their possible effect on its emissions and "
           "on its emission reductions (ESRS E1, §24(c)).")),
    # ------------------------------------------------------------------ E1-7 – énergie
    kpi("NRJ-ACHAT-NUCLEAIRE", "Énergie achetée d'origine nucléaire", "Purchased energy from nuclear sources", "MWh",
        description=_d("Part d'origine nucléaire de l'électricité, de la chaleur, de la vapeur et du froid achetés et consommés "
                       "par le site pendant la période, en MWh, selon le mix énergétique du fournisseur ou, à défaut, du "
                       "réseau (ESRS E1, §26(b) ; AR 18).",
                       "Nuclear part of the electricity, heat, steam and cooling purchased and consumed by the site during "
                       "the period, in MWh, according to the energy mix of the supplier or, failing that, of the grid "
                       "(ESRS E1, §26(b); AR 18).", True),
        source=S_ENERGIE),
    kpi("NRJ-ACHAT-RENOUV", "Énergie achetée d'origine renouvelable", "Purchased energy from renewable sources", "MWh",
        description=_d("Part d'origine renouvelable de l'électricité, de la chaleur, de la vapeur et du froid achetés et "
                       "consommés par le site pendant la période, en MWh. Approche prudente : avec la méthode marché, "
                       "seulement l'énergie dont l'origine renouvelable est prévue au contrat (contrat d'achat direct, offre "
                       "verte standardisée, garanties d'origine) ; dire dans les méthodes si la part vient de la méthode marché "
                       "ou localisation (ESRS E1, §26(c) ; AR 18(i)).",
                       "Renewable part of the electricity, heat, steam and cooling purchased and consumed by the site during "
                       "the period, in MWh. Conservative approach: with the market-based method, only energy whose renewable "
                       "origin is defined in the contract (power purchase agreement, standardised green tariff, guarantees of "
                       "origin); say in the methods whether the share comes from the market-based or location-based method "
                       "(ESRS E1, §26(c); AR 18(i)).", True),
        source=S_ENERGIE),
    kpi("NRJ-ACHAT-FOSSILE", "Énergie achetée d'origine fossile", "Purchased energy from fossil sources", "MWh", "Somme",
        "Calculé", formule="([NRJ-ELEC] + [NRJ-CHALEUR] + [NRJ-FROID]) / 1000 - [NRJ-ACHAT-NUCLEAIRE] - [NRJ-ACHAT-RENOUV]",
        description=("Calculée par l'outil : électricité, chaleur, vapeur et froid achetés, moins leurs parts nucléaire et "
                     "renouvelable, en MWh. Approche prudente : tout ce qui n'est pas démontré nucléaire ou renouvelable "
                     "compte comme fossile (ESRS E1, §27(e) ; AR 18(i)).",
                     "Calculated by the tool: purchased electricity, heat, steam and cooling, minus their nuclear and renewable "
                     "parts, in MWh. Conservative approach: everything that is not shown to be nuclear or renewable counts as "
                     "fossil (ESRS E1, §27(e); AR 18(i)).")),
    kpi("NRJ-FOSSILE", "Consommation d'énergie d'origine fossile", "Energy consumption from fossil sources", "MWh", "Somme",
        "Calculé", formule="[NRJ-COMBUSTIBLES] + [NRJ-ACHAT-FOSSILE]",
        description=("Calculée par l'outil : combustibles fossiles et énergie achetée d'origine fossile, "
                     "en MWh (ESRS E1, §26(a)). Avec l'énergie nucléaire et l'énergie renouvelable, elle donne la "
                     "consommation totale.",
                     "Calculated by the tool: fossil fuels and purchased energy from fossil sources, in "
                     "MWh (ESRS E1, §26(a)). With nuclear and renewable energy, it makes up the total consumption.")),
    kpi("NRJ-RENOUVELABLE", "Consommation d'énergie d'origine renouvelable", "Energy consumption from renewable sources",
        "MWh", "Somme", "Calculé", formule="[NRJ-COMB-REN] + [NRJ-ELEC-AUTO] / 1000 + [NRJ-ACHAT-RENOUV]",
        description=("Calculée par l'outil : combustibles renouvelables, électricité renouvelable produite et autoconsommée "
                     "et énergie achetée d'origine renouvelable, en MWh (ESRS E1, §26(c) ; AR 18).",
                     "Calculated by the tool: renewable fuels, self-generated renewable electricity consumed and purchased "
                     "energy from renewable sources, in MWh (ESRS E1, §26(c); AR 18).")),
    kpi("NRJ-CHARBON", "Combustibles : charbon et produits du charbon", "Fuel consumption from coal and coal products",
        "MWh",
        description=_d("Charbon, lignite, coke et autres produits du charbon brûlés sur le site pendant la période, en MWh "
                       "selon le pouvoir calorifique inférieur. Ils font partie des « Autres combustibles fossiles » saisis dans "
                       "les données de calcul (ESRS E1, §27(a)).",
                       "Coal, lignite, coke and other coal products burned on the site during the period, in MWh on a net "
                       "calorific value basis. They are part of the “Other fossil fuels” entered in the calculation data (ESRS "
                       "E1, §27(a)).", True, SECTEURS),
        source=S_COMBUSTIBLES),
    kpi("NRJ-PETROLE-AUTRES", "Autres produits pétroliers brûlés", "Other petroleum products burned", "MWh",
        description=_d("Produits pétroliers autres que le fioul et les carburants des véhicules (GPL, propane, butane, "
                       "kérosène, fioul lourd…) brûlés sur le site pendant la période, en MWh selon le pouvoir calorifique "
                       "inférieur. Ils font partie des « Autres combustibles fossiles » saisis dans les données de calcul (ESRS "
                       "E1, §27(b)).",
                       "Petroleum products other than heating oil and vehicle fuels (LPG, propane, butane, kerosene, heavy "
                       "fuel oil…) burned on the site during the period, in MWh on a net calorific value basis. They are part "
                       "of the “Other fossil fuels” entered in the calculation data (ESRS E1, §27(b)).", True, SECTEURS),
        source=S_COMBUSTIBLES),
    kpi("NRJ-PETROLE", "Combustibles : pétrole brut et produits pétroliers",
        "Fuel consumption from crude oil and petroleum products", "MWh", "Somme", "Calculé",
        formule="([NRJ-FIOUL] * [CONV-FIOUL] + [GES-GAZOLE] * [CONV-GAZOLE] + [GES-ESSENCE] * [CONV-ESSENCE]) / 1000 "
                "+ [NRJ-PETROLE-AUTRES]",
        description=("Calculée par l'outil : fioul, gazole et essence convertis en MWh, plus les autres produits pétroliers "
                     "(ESRS E1, §27(b)). Seulement pour les secteurs à fort impact climatique.",
                     "Calculated by the tool: heating oil, diesel and petrol converted into MWh, plus the other petroleum "
                     "products (ESRS E1, §27(b)). Only for high climate impact sectors.")),
    kpi("NRJ-GAZ-MWH", "Combustibles : gaz naturel", "Fuel consumption from natural gas", "MWh", "Somme", "Calculé",
        formule="[NRJ-GAZ] * [CONV-GAZ-PCI] / 1000",
        description=("Calculée par l'outil : gaz naturel facturé en kWh PCS, converti en MWh selon le pouvoir calorifique "
                     "inférieur (ESRS E1, §27(c) ; AR 18(b)). Seulement pour les secteurs à fort impact climatique.",
                     "Calculated by the tool: natural gas billed in kWh of gross calorific value, converted into MWh on a net "
                     "calorific value basis (ESRS E1, §27(c); AR 18(b)). Only for high climate impact sectors.")),
    kpi("NRJ-FOSSILE-AUTRES", "Combustibles : autres sources fossiles", "Fuel consumption from other fossil sources", "MWh",
        "Somme", "Calculé", formule="[NRJ-COMB-AUTRES] - [NRJ-CHARBON] - [NRJ-PETROLE-AUTRES]",
        description=("Calculée par l'outil : « Autres combustibles fossiles » des données de calcul, moins le charbon et les "
                     "autres produits pétroliers ; par exemple gaz de procédé, hydrogène qui n'est pas entièrement "
                     "renouvelable (ESRS E1, §27(d) ; AR 18(h)). Seulement pour les secteurs à fort impact climatique.",
                     "Calculated by the tool: “Other fossil fuels” of the calculation data, minus coal and the other "
                     "petroleum products; for example process gas, hydrogen that is not fully renewable (ESRS E1, §27(d); "
                     "AR 18(h)). Only for high climate impact sectors.")),
    kpi("NRJ-PROD-NON-REN", "Production d'énergie non renouvelable", "Non-renewable energy production", "MWh",
        description=_d("Énergie produite par le site à partir de sources non renouvelables pendant la période (électricité, "
                       "chaleur, vapeur, froid), qu'elle soit consommée sur place ou vendue, en MWh. Seulement si "
                       "l'entreprise produit de l'énergie ; sinon, répondre N/A (ESRS E1, §28).",
                       "Energy produced by the site from non-renewable sources during the period (electricity, heat, steam, "
                       "cooling), whether consumed on site or sold, in MWh. Only if the company produces energy; otherwise, "
                       "answer N/A (ESRS E1, §28).", True),
        source=S_PRODUCTION),
    kpi("NRJ-PROD-REN", "Production d'énergie renouvelable", "Renewable energy production", "MWh",
        description=_d("Énergie produite par le site à partir de sources renouvelables pendant la période (panneaux "
                       "photovoltaïques, éolien, biomasse…), qu'elle soit consommée sur place ou vendue, en MWh. Seulement si "
                       "l'entreprise produit de l'énergie ; sinon, répondre N/A (ESRS E1, §28).",
                       "Energy produced by the site from renewable sources during the period (solar panels, wind, "
                       "biomass…), whether consumed on site or sold, in MWh. Only if the company produces energy; otherwise, "
                       "answer N/A (ESRS E1, §28).", True),
        source=S_PRODUCTION),
    # ------------------------------------------------------------------ E1-8 – émissions brutes de GES
    kpi("GES-S1-BRUT", "Émissions brutes de GES du scope 1", "Gross scope 1 GHG emissions", "tCO2e", "Somme", "Calculé",
        formule="[GES-S1] + [GES-S1-AUTRES]", decimales=1,
        description=("Calculées par l'outil : combustion fixe et mobile et émissions fugitives, plus les autres émissions "
                     "directes (procédés, autres combustibles, agriculture), en tCO2e, sans absorptions, crédits ni quotas "
                     "et sans le CO2 biogénique (ESRS E1, §30(a)(i) ; AR 20, AR 21).",
                     "Calculated by the tool: stationary and mobile combustion and fugitive emissions, plus the other direct "
                     "emissions (processes, other fuels, agriculture), in tCO2e, without removals, credits or allowances and "
                     "without biogenic CO2 (ESRS E1, §30(a)(i); AR 20, AR 21).")),
    kpi("GES-S1-SEQE", "Émissions du scope 1 couvertes par le SEQE-UE", "Scope 1 emissions covered by the EU ETS", "tCO2e",
        decimales=1,
        description=_d("Émissions des installations du site soumises au système d'échange de quotas d'émission de l'Union "
                       "(SEQE-UE) pendant la période, en tCO2e, calculées selon la méthode du SEQE-UE et sur la même période "
                       "que le scope 1. Saisir 0 pour un site sans installation soumise au SEQE-UE (ESRS E1, §30(a)(i) ; "
                       "AR 21, AR 22).",
                       "Emissions of the site's installations covered by the EU Emissions Trading System (EU ETS) during the "
                       "period, in tCO2e, calculated with the EU ETS method and over the same period as scope 1. Enter 0 for "
                       "a site without an installation under the EU ETS (ESRS E1, §30(a)(i); AR 21, AR 22)."),
        source=S_SEQE),
    kpi("GES-PART-SEQE", "Part du scope 1 couverte par le SEQE-UE", "Share of scope 1 emissions from the EU ETS", "",
        "Formule", "Calculé", "Pourcentage", "[GES-S1-SEQE] / [GES-S1-BRUT]",
        description=("Calculée par l'outil à chaque niveau : émissions couvertes par le SEQE-UE rapportées aux émissions brutes "
                     "du scope 1 (ESRS E1, §30(a)(i) ; AR 22(c)).",
                     "Calculated by the tool at every level: emissions covered by the EU ETS divided by gross scope 1 "
                     "emissions (ESRS E1, §30(a)(i); AR 22(c)).")),
] + [
    kpi(f"{code}-HORS-GROUPE", f"{fr} hors du groupe consolidé", f"{en} outside the consolidated accounting group", "tCO2e",
        decimales=1, niveau=HAUT,
        description=_d(f"Partie de ces émissions ({fr_d}) qui ne vient pas du groupe consolidé pour les comptes (société mère et "
                       "filiales consolidées) mais d'autres activités comprises dans l'inventaire selon l'approche de "
                       "consolidation retenue (par exemple une coentreprise sous contrôle opérationnel), en tCO2e. Saisir 0 si "
                       "tout l'inventaire vient du groupe consolidé (ESRS E1, §30(c) ; AR 19).",
                       f"Part of these emissions ({en_d}) that does not come from the consolidated accounting group (parent and "
                       "consolidated subsidiaries) but from other operations included in the inventory under the "
                       "consolidation approach chosen (for example a joint venture under operational control), in tCO2e. "
                       "Enter 0 if the whole inventory comes from the consolidated group (ESRS E1, §30(c); AR 19)."),
        source=S_GES)
    for code, fr, en, fr_d, en_d in (
        ("GES-S1", "Scope 1", "Scope 1", "scope 1 brut", "gross scope 1"),
        ("GES-S2-LB", "Scope 2 (méthode localisation)", "Scope 2 (location-based)", "scope 2 selon la méthode localisation",
         "location-based scope 2"),
        ("GES-S2-MB", "Scope 2 (méthode marché)", "Scope 2 (market-based)", "scope 2 selon la méthode marché",
         "market-based scope 2"))
] + [
    kpi(f"{code}-GROUPE", f"{fr} du groupe consolidé", f"{en} of the consolidated accounting group", "tCO2e", "Somme",
        "Calculé", formule=f"[{total}] - [{code}-HORS-GROUPE]", decimales=1,
        description=(f"Calculées par l'outil : {fr_d} moins la partie hors du groupe consolidé pour les comptes, en tCO2e "
                     "(ESRS E1, §30(c)(i)).",
                     f"Calculated by the tool: {en_d} minus the part outside the consolidated accounting group, in tCO2e "
                     "(ESRS E1, §30(c)(i))."))
    for code, total, fr, en, fr_d, en_d in (
        ("GES-S1", "GES-S1-BRUT", "Scope 1", "Scope 1", "émissions brutes du scope 1", "gross scope 1 emissions"),
        ("GES-S2-LB", "GES-S2-LB", "Scope 2 (méthode localisation)", "Scope 2 (location-based)",
         "émissions du scope 2 selon la méthode localisation", "location-based scope 2 emissions"),
        ("GES-S2-MB", "GES-S2-MB", "Scope 2 (méthode marché)", "Scope 2 (market-based)",
         "émissions du scope 2 selon la méthode marché", "market-based scope 2 emissions"))
] + [
    kpi("GES-S3-TOTAL", "Émissions brutes de GES du scope 3", "Gross scope 3 GHG emissions", "tCO2e", "Somme", "Calculé",
        formule="[GES-S3-ACHATS] + [GES-S3-IMMO] + [GES-S3-ENERGIE] + [GES-S3-FRET-AMONT] + [GES-S3-DECHETS] "
                "+ [GES-S3-DEPLACEMENTS] + [GES-S3-DOMICILE] + [GES-S3-ACTIFS-AMONT] + [GES-S3-FRET-AVAL] + [GES-S3-TRANSFO] "
                "+ [GES-S3-UTILISATION] + [GES-S3-FIN-VIE] + [GES-S3-ACTIFS-AVAL] + [GES-S3-FRANCHISES] + [GES-S3-INVEST]",
        decimales=1,
        description=("Calculées par l'outil : somme des catégories importantes du scope 3, en tCO2e. Saisir les émissions de "
                     "chaque catégorie importante (selon leur ampleur et les critères du GHG Protocol) ; une catégorie qui "
                     "n'est pas importante reçoit N/A : elle compte pour 0 dans ce total (case « une source N/A compte comme 0 » "
                     "de la fiche, cochée à l'installation) et n'est pas publiée comme nulle (ESRS E1, §30(a)(iii) ; AR 24, "
                     "AR 26).",
                     "Calculated by the tool: sum of the significant scope 3 categories, in tCO2e. Enter the emissions of "
                     "each significant category (by size and the GHG Protocol criteria); a category that is not significant "
                     "gets N/A: it counts as 0 in this total (“an N/A source counts as 0” box of the KPI sheet, ticked at "
                     "installation) and is not disclosed as zero (ESRS E1, §30(a)(iii); AR 24, AR 26).")),
    kpi("GES-S3-CLOUD", "Scope 3 – dont informatique en nuage et centres de données",
        "Scope 3 – of which cloud computing and data centre services", "tCO2e", decimales=1, niveau=HAUT,
        description=_d("Partie de la catégorie 1 du scope 3 (biens et services achetés) due aux services d'informatique en "
                       "nuage et de centres de données achetés, en tCO2e. Seulement si elle s'applique ; sinon, répondre N/A "
                       "(ESRS E1, AR 24(g) ; AR 26).",
                       "Part of scope 3 category 1 (purchased goods and services) due to purchased cloud computing and data "
                       "centre services, in tCO2e. Only if applicable; otherwise, answer N/A (ESRS E1, AR 24(g); AR 26)."),
        source=S_GES),
    kpi("GES-BIOGENIQUE", "Émissions directes de CO2 biogénique", "Direct biogenic CO2 emissions", "tCO2e", decimales=1,
        description=_d("CO2 émis par la combustion ou la biodégradation de biomasse sur le site pendant la période (bois, "
                       "granulés, biogaz, biocarburants), en tonnes, à part du scope 1 ; le CH4 et le N2O de ces combustions "
                       "restent dans le scope 1 (ESRS E1, §31 ; AR 20(e)).",
                       "CO2 emitted by the combustion or biodegradation of biomass on the site during the period (wood, "
                       "pellets, biogas, biofuels), in tonnes, separately from scope 1; the CH4 and N2O of these combustions "
                       "stay in scope 1 (ESRS E1, §31; AR 20(e)).", True),
        source=S_GES),
    texte("CLI-METHODE-GES", "Émissions de GES et énergie : approche de mesure",
          "GHG emissions and energy: measurement approach",
          ("Approche de mesure des émissions : périmètre et approche de consolidation (contrôle financier par défaut, ou part "
           "du capital, ou contrôle opérationnel), normes suivies (GHG Protocol, ISO 14064-1), potentiels de réchauffement "
           "global utilisés, facteurs d'émission et leurs sources, instruments contractuels du scope 2 selon la méthode "
           "marché, méthode du SEQE-UE, mise à jour du scope 3 ; pour l'énergie, méthode (marché ou localisation) de la part "
           "renouvelable de l'énergie achetée et traitement de la vapeur achetée (ESRS E1, §30(b) ; AR 18(i), AR 19, AR 20, "
           "AR 23, AR 24).",
           "Measurement approach of the emissions: boundary and consolidation approach (financial control by default, or "
           "equity share, or operational control), standards followed (GHG Protocol, ISO 14064-1), global warming potentials "
           "used, emission factors and their sources, contractual instruments of market-based scope 2, EU ETS method, update "
           "of scope 3; for energy, method (market-based or location-based) of the renewable share of purchased energy and "
           "treatment of purchased steam (ESRS E1, §30(b); AR 18(i), AR 19, AR 20, AR 23, AR 24).")),
    # ------------------------------------------------------------------ E1-9 – absorptions et crédits carbone
    oui_non("CLI-ABSORPTIONS", "Projets d'absorption et de stockage de GES", "GHG removal and storage projects",
            ("L'entreprise a-t-elle mis en œuvre des projets d'absorption et de stockage de GES, dans ses activités propres ou "
             "en y contribuant dans sa chaîne de valeur ? Si non, répondre N/A aux questions suivantes sur les projets "
             "(ESRS E1, §33 ; AR 27).",
             "Has the company implemented GHG removal and storage projects, in its own operations or by contributing to them "
             "in its value chain? If not, answer N/A to the next questions on the projects (ESRS E1, §33; AR 27).")),
    texte("CLI-ABSORPTIONS-PROJETS", "Projets d'absorption et de stockage : description",
          "GHG removal and storage projects: description",
          ("Brève description de chaque projet d'absorption et de stockage de GES, fondé sur la nature ou technologique "
           "(ESRS E1, §33(a) ; AR 27).",
           "Short description of each GHG removal and storage project, nature-based or technological (ESRS E1, §33(a); "
           "AR 27).")),
    tableau("CLI-ABSORPTIONS-TAB", "Absorptions et stockage de GES par projet", "GHG removals and storage by project",
            "ESRS-TAB-PROJETS",
            ("Une ligne par projet : absorptions et stockage de GES qu'il a produits pendant la période, en tCO2e, selon une "
             "méthode reconnue (par exemple le règlement (UE) 2024/3012), sans les absorptions vendues sous forme de crédits "
             "carbone (ESRS E1, §33(b) ; AR 27).",
             "One row per project: GHG removals and storage it produced during the period, in tCO2e, with a recognised method "
             "(for example Regulation (EU) 2024/3012), without the removals sold as carbon credits (ESRS E1, §33(b); AR 27)."),
            ("Suivi des projets, certificats de la méthode de certification.", "Project monitoring, certification records.")),
    texte("CLI-ABSORPTIONS-PERMANENCE", "Absorptions : gestion du risque de non-permanence",
          "Removals: management of the risk of non-permanence",
          ("Comment le risque de non-permanence est géré : hypothèses, détection et suivi des fuites et des inversions "
           "(ESRS E1, §33(c) ; AR 27).",
           "How the risk of non-permanence is managed: assumptions, detection and monitoring of leakage and reversals "
           "(ESRS E1, §33(c); AR 27).")),
    kpi("GES-INVERSIONS", "Inversions d'absorptions de GES", "Reversals of GHG removals", "tCO2e", decimales=1, niveau=HAUT,
        description=_d("GES absorbés et stockés qui ont été rejetés à nouveau pendant la période (incendie, fuite…), en tCO2e ; "
                       "ils réduisent d'autant le CO2 absorbé et stocké. Seulement s'il y a des projets d'absorption ; sinon, "
                       "répondre N/A (ESRS E1, §33(d)).",
                       "GHG removed and stored that were released again during the period (fire, leakage…), in tCO2e; they "
                       "reduce the CO2 removed and stored by the same amount. Only if there are removal projects; otherwise, "
                       "answer N/A (ESRS E1, §33(d))."),
        source=("Suivi des projets d'absorption.", "Monitoring of the removal projects.")),
    kpi("GES-CREDITS-ANNULES", "Crédits carbone vérifiés et annulés", "Carbon credits verified and cancelled", "tCO2e",
        decimales=1, niveau=HAUT,
        description=_d("Crédits carbone de projets situés hors des activités propres et de la chaîne de valeur, vérifiés selon "
                       "une norme de qualité reconnue et annulés pendant la période, en tCO2e (ESRS E1, §34(a) ; AR 28).",
                       "Carbon credits from projects outside the own operations and value chain, verified against a "
                       "recognised quality standard and cancelled during the period, in tCO2e (ESRS E1, §34(a); AR 28).",
                       True),
        source=S_CREDITS),
    kpi("GES-CREDITS-A-ANNULER", "Crédits carbone achetés pas encore annulés", "Carbon credits purchased not yet cancelled",
        "tCO2e", decimales=1, niveau=HAUT,
        description=_d("Crédits carbone achetés pendant la période et pas encore annulés à la date de clôture, en tCO2e "
                       "(ESRS E1, §34(b)). Pour des crédits achetés par un contrat qui couvre plusieurs années, compter la "
                       "somme des crédits restant à annuler sur la durée du contrat (AR 28(c)) ; un contrat signé pour des "
                       "achats futurs ne compte pas tant que les crédits ne sont pas achetés.",
                       "Carbon credits purchased during the period and not cancelled yet at the reporting date, in tCO2e "
                       "(ESRS E1, §34(b)). For credits purchased under a contract that covers several years, count the sum of "
                       "the credits still to be cancelled over the duration of the contract (AR 28(c)); a contract signed for "
                       "future purchases does not count until the credits are purchased.", True),
        source=S_CREDITS),
    kpi("GES-PART-CREDITS-ABSORPTION", "Part des crédits carbone issus de projets d'absorption",
        "Share of carbon credits from removal projects", "", "Aucune", reponse="Pourcentage", temps="derniere", niveau=HAUT,
        description=("Part, en volume, des crédits carbone de l'entreprise qui viennent de projets d'absorption (et non de "
                     "réduction d'émissions) (ESRS E1, §34(c)). Dire dans le texte suivant s'ils viennent de puits fondés "
                     "sur la nature ou technologiques. Répondre N/A s'il n'y a pas de crédits carbone.",
                     "Share, by volume, of the company's carbon credits that come from removal projects (and not from "
                     "emission reduction projects) (ESRS E1, §34(c)). Say in the next text whether they come from "
                     "nature-based or technological sinks. Answer N/A if there are no carbon credits."),
        source=S_CREDITS),
    texte("CLI-CREDITS-PUITS", "Crédits carbone : puits fondés sur la nature ou technologiques",
          "Carbon credits: nature-based or technological sinks",
          ("Pour les crédits issus de projets d'absorption : viennent-ils de puits fondés sur la nature ou technologiques "
           "(ESRS E1, §34(c)) ? Répondre N/A s'il n'y en a pas.",
           "For the credits from removal projects: do they come from nature-based or technological sinks (ESRS E1, §34(c))? "
           "Answer N/A if there are none.")),
    oui_non("CLI-NEUTRALITE", "Allégations publiques de neutralité en GES fondées sur des crédits carbone",
            "Public claims of GHG neutrality based on carbon credits",
            ("L'entreprise a-t-elle fait des allégations publiques de neutralité en GES qui s'appuient sur des crédits "
             "carbone ? Si non, répondre N/A aux deux questions suivantes (ESRS E1, §35).",
             "Has the company made public claims of GHG neutrality that involve carbon credits? If not, answer N/A to the "
             "next two questions (ESRS E1, §35).")),
    texte("CLI-NEUTRALITE-CIBLES", "Allégations de neutralité et atteinte des cibles de GES",
          "Neutrality claims and achievement of the GHG targets",
          ("Si et comment ces allégations et le recours aux crédits carbone n'empêchent ni ne compromettent l'atteinte des "
           "cibles de réduction des émissions de GES (ESRS E1, §35(a)).",
           "Whether and how these claims and the reliance on carbon credits neither hinder nor undermine the achievement of "
           "the GHG emission reduction targets (ESRS E1, §35(a)).")),
    texte("CLI-CREDITS-QUALITE", "Crédits carbone : crédibilité et intégrité", "Carbon credits: credibility and integrity",
          ("Crédibilité et intégrité des crédits carbone utilisés ou prévus : normes de qualité reconnues et autres éléments "
           "utiles (ESRS E1, §35(b)).",
           "Credibility and integrity of the carbon credits used or planned: recognised quality standards and other useful "
           "elements (ESRS E1, §35(b)).")),
    # ------------------------------------------------------------------ E1-10 – prix interne du carbone
    oui_non("CLI-PRIX-CARBONE", "Prix interne du carbone appliqué", "Internal carbon pricing applied",
            ("L'entreprise applique-t-elle un prix interne du carbone dans ses décisions ? Si non, répondre Non ; la question "
             "suivante reçoit N/A (ESRS E1, §37(a)).",
             "Does the company apply internal carbon pricing in its decisions? If not, answer No; the next question gets N/A "
             "(ESRS E1, §37(a)).")),
    texte("CLI-PRIX-CARBONE-DESC", "Prix interne du carbone : usages et cohérence avec les états financiers",
          "Internal carbon pricing: uses and consistency with the financial statements",
          ("Comment le prix interne du carbone sert aux décisions (investissements, prix de transfert, analyse de "
           "scénarios…), et cohérence des prix utilisés avec ceux des tests de dépréciation des états financiers (ESRS E1, "
           "§37(a)).",
           "How internal carbon pricing is used in decisions (investments, transfer pricing, scenario analysis…), and "
           "consistency of the prices used with those of the impairment tests of the financial statements (ESRS E1, "
           "§37(a)).")),
    tableau("CLI-PRIX-CARBONE-TAB", "Prix moyen du carbone par dispositif interne",
            "Average carbon price by internal pricing scheme", "ESRS-TAB-PRIX-CO2",
            ("Une ligne par dispositif de prix interne du carbone (prix fictif, redevance interne…) : son usage et son prix "
             "moyen par tonne de GES, dans la monnaie des états financiers (ESRS E1, §37(b) ; ESRS 1 AR 50). Laisser vide "
             "sans prix interne.",
             "One row per internal carbon pricing scheme (shadow price, internal fee…): its use and its average price per "
             "tonne of GHG, in the currency of the financial statements (ESRS E1, §37(b); ESRS 1 AR 50). Leave empty without "
             "internal pricing."),
            ("Procédures d'investissement, contrôle de gestion.", "Investment procedures, management control.")),
    # ------------------------------------------------------------------ E1-11 – effets financiers attendus
    tableau("CLI-ACTIFS-RISQUE-PHYS", "Actifs exposés à un risque physique important", "Assets at material physical risk",
            "ESRS-TAB-HORIZONS",
            _d("Valeur comptable des actifs exposés à un risque physique important, avant les actions d'adaptation, à la date "
               "de clôture et cohérente avec les états financiers (ESRS E1, §39(a) ; AR 29).",
               "Carrying amount of the assets at material physical risk, before adaptation actions, at the reporting date and "
               "consistent with the financial statements (ESRS E1, §39(a); AR 29).", suite=HORIZONS), S_COMPTA),
    kpi("CLI-PART-ACTIFS-ADAPT", "Part des actifs à risque physique couverte par l'adaptation",
        "Share of assets at physical risk addressed by adaptation", "", "Aucune", reponse="Pourcentage", temps="derniere",
        niveau=HAUT,
        description=("Part de la valeur comptable des actifs exposés à un risque physique important que des actions "
                     "d'adaptation couvrent à la date de clôture (ESRS E1, §39(b) ; AR 29).",
                     "Share of the carrying amount of the assets at material physical risk addressed by adaptation actions at "
                     "the reporting date (ESRS E1, §39(b); AR 29)."),
        source=S_COMPTA),
    tableau("CLI-CA-RISQUE-PHYS", "Chiffre d'affaires des activités exposées à un risque physique important",
            "Net revenue from activities at material physical risk", "ESRS-TAB-HORIZONS",
            _d("Chiffre d'affaires net de la période des activités exposées à un risque physique important ; dire dans le "
               "commentaire s'il est évalué avant ou après les actions d'atténuation (ESRS E1, §39(c) ; AR 29, AR 30).",
               "Net revenue of the period from business activities at material physical risk; say in the comment whether it "
               "is assessed before or after mitigation actions (ESRS E1, §39(c); AR 29, AR 30).",
               suite=(HORIZONS[0] + PHASE_QUANTI[0], HORIZONS[1] + PHASE_QUANTI[1])), S_COMPTA),
    tableau("CLI-ACTIFS-RISQUE-TRANS", "Actifs exposés à un risque de transition important",
            "Assets at material transition risk", "ESRS-TAB-HORIZONS",
            _d("Valeur comptable des actifs exposés à un risque de transition important, à la date de clôture ; dire dans le "
               "commentaire si elle est évaluée avant ou après les actions d'atténuation (ESRS E1, §40(a) ; AR 29, AR 30).",
               "Carrying amount of the assets at material transition risk, at the reporting date; say in the comment whether it "
               "is assessed before or after mitigation actions (ESRS E1, §40(a); AR 29, AR 30).", suite=HORIZONS), S_COMPTA),
    tableau("CLI-ACTIFS-ECHOUES", "Actifs potentiellement échoués (scénario 1,5 °C)",
            "Potential stranded assets (1.5 °C scenario)", "ESRS-TAB-HORIZONS",
            ("Fourchette estimée des actifs potentiellement échoués, de l'année de reporting jusqu'au moyen et au long terme, "
             "selon un scénario compatible avec la limitation du réchauffement à 1,5 °C : une ligne pour le moyen terme, une "
             "pour le long terme, dans la monnaie des états financiers (ESRS E1, §40(a) ; AR 29, AR 30 ; ESRS 1 AR 50).",
             "Estimated range of potential stranded assets, from the reporting year until the medium and long term, based on a "
             "scenario aligned with limiting global warming to 1.5 °C: one row for the medium term, one for the long term, in "
             "the currency of the financial statements (ESRS E1, §40(a); AR 29, AR 30; ESRS 1 AR 50)."), S_COMPTA),
    kpi("CLI-PART-ACTIFS-ATTEN", "Part des actifs à risque de transition couverte par l'atténuation",
        "Share of assets at transition risk addressed by mitigation", "", "Aucune", reponse="Pourcentage", temps="derniere",
        niveau=HAUT,
        description=("Part de la valeur comptable des actifs exposés à un risque de transition important que des actions "
                     "d'atténuation couvrent (ESRS E1, §40(b) ; AR 29).",
                     "Share of the carrying amount of the assets at material transition risk addressed by mitigation actions "
                     "(ESRS E1, §40(b); AR 29)."),
        source=S_COMPTA),
    tableau("CLI-IMMO-GARANTIES", "Biens immobiliers donnés en garantie de prêts, par classe énergétique",
            "Real estate used as loan collateral, by energy-efficiency class", "ESRS-TAB-CLASSE-NRJ",
            _d("Une ligne par classe énergétique (classe du diagnostic de performance énergétique ou tranche de consommation en "
               "kWh/m²) : valeur comptable des biens immobiliers de l'entreprise donnés en garantie de prêts. Pour un "
               "établissement financier, ce sont aussi les prêts garantis par des biens immobiliers, ventilés selon la classe "
               "énergétique du bien donné en garantie (modèle 2 du pilier 3, article 449 bis du règlement (UE) n° 575/2013, "
               "auquel renvoie la note du §40(c)). Si la classe ne "
               "peut pas être obtenue sans coût ou effort excessif, une ligne « estimations internes » avec la valeur "
               "comptable des biens dont la consommation est estimée (ESRS E1, §40(c) ; AR 29(e)).",
               "One row per energy-efficiency class (Energy Performance Certificate label or range of energy consumption in "
               "kWh/m²): carrying amount of the company's real estate assets used as loan collateral. For a financial "
               "institution, this also covers the loans collateralised by real estate, broken down by the energy-efficiency "
               "class of the collateral (Pillar 3 template 2, Article 449a of Regulation (EU) No 575/2013, to which the "
               "footnote of §40(c) refers). If the class cannot be "
               "obtained without undue cost or effort, a row “internal estimates” with the carrying amount of the assets "
               "whose consumption is estimated (ESRS E1, §40(c); AR 29(e)).",
               suite=(C.MONNAIE_TABLEAU[0] + PHASE_QUANTI[0], C.MONNAIE_TABLEAU[1] + PHASE_QUANTI[1])),
            ("Comptabilité des immobilisations, contrats de prêt, diagnostics de performance énergétique.",
             "Fixed asset accounting, loan agreements, Energy Performance Certificates.")),
    kpi("CLI-PASSIFS-POTENTIELS", "Passifs potentiels liés à la transition climatique non comptabilisés",
        "Potential climate transition liabilities not recognised", "€", niveau=HAUT,
        description=_d("Estimation des passifs liés à la transition climatique qui ne remplissent pas encore les critères de "
                       "comptabilisation à la date de clôture mais pourraient devoir être comptabilisés plus tard ; renvoyer "
                       "aux états financiers s'ils les mentionnent (ESRS E1, §40(d) ; AR 31).",
                       "Estimated liabilities related to the climate transition that do not meet the accounting recognition "
                       "criteria at the reporting date but may have to be recognised later; refer to the financial "
                       "statements if they mention them (ESRS E1, §40(d); AR 31).",
                       suite=(C.MONNAIE[0] + PHASE_QUANTI[0], C.MONNAIE[1] + PHASE_QUANTI[1])),
        source=S_COMPTA),
    tableau("CLI-CA-RISQUE-TRANS", "Chiffre d'affaires des activités exposées à un risque de transition important",
            "Net revenue from activities at material transition risk", "ESRS-TAB-HORIZONS",
            _d("Chiffre d'affaires net de la période des activités exposées à un risque de transition important ; dire dans le "
               "commentaire s'il est évalué avant ou après les actions d'atténuation (ESRS E1, §40(e) ; AR 29, AR 30).",
               "Net revenue of the period from business activities at material transition risk; say in the comment whether it "
               "is assessed before or after mitigation actions (ESRS E1, §40(e); AR 29, AR 30).",
               suite=(HORIZONS[0] + PHASE_QUANTI[0], HORIZONS[1] + PHASE_QUANTI[1])), S_COMPTA),
    tableau("CLI-CA-CLIENTS-FOSSILES", "Chiffre d'affaires réalisé avec des clients du charbon, du pétrole et du gaz",
            "Net revenue from customers in coal, oil and gas activities", "ESRS-TAB-HORIZONS",
            _d("Chiffre d'affaires net de la période réalisé avec des clients dont l'activité est liée au charbon, au pétrole "
               "ou au gaz, s'il y en a ; sinon, laisser vide (ESRS E1, §40(e) ; AR 29, AR 30).",
               "Net revenue of the period from customers operating in coal-, oil- or gas-related activities, if any; otherwise, "
               "leave empty (ESRS E1, §40(e); AR 29, AR 30).",
               suite=(HORIZONS[0] + PHASE_QUANTI[0], HORIZONS[1] + PHASE_QUANTI[1])), S_COMPTA),
    texte("CLI-EFFETS-METHODE", "Effets financiers attendus : méthode de calcul", "Anticipated financial effects: method",
          _d("Méthode qui chiffre les montants des risques physiques et de transition (E1-11) : périmètre du calcul, hypothèses "
             "critiques, paramètres et limites, et, si utile, localisation des actifs exposés à un risque physique important "
             "regroupée de façon fidèle (ESRS E1, §41 ; AR 29, AR 32).",
             "Method that quantifies the amounts of the physical and transition risks (E1-11): scope of the calculation, "
             "critical assumptions, parameters and limitations, and, where relevant, the location of the assets at material "
             "physical risk, aggregated faithfully (ESRS E1, §41; AR 29, AR 32).", suite=PHASE_METHODE)),
    oui_non("CLI-EFFETS-SCENARIOS", "Effets financiers chiffrés à partir de l'évaluation des risques de transition",
            "Financial effects quantified from the transition risk assessment",
            _d("Le calcul des effets financiers attendus s'appuie-t-il sur le processus qui identifie et évalue les risques de "
               "transition (par exemple l'analyse de scénarios) (ESRS E1, §41) ?",
               "Does the calculation of the anticipated financial effects rely on the process that identifies and assesses "
               "the transition risks (for example scenario analysis) (ESRS E1, §41)?", suite=PHASE_METHODE)),
    tableau("CLI-ACTIFS-OPPORTUNITES", "Actifs liés aux opportunités climatiques", "Assets related to climate opportunities",
            "ESRS-TAB-HORIZONS",
            _d("Montant des actifs des activités liées aux opportunités climatiques identifiées (ESRS E1, §42 ; AR 29).",
               "Amount of the assets of business activities related to the identified climate-related opportunities (ESRS E1, "
               "§42; AR 29).", suite=(HORIZONS[0] + PHASE_QUANTI[0], HORIZONS[1] + PHASE_QUANTI[1])), S_COMPTA),
    tableau("CLI-CA-OPPORTUNITES", "Chiffre d'affaires lié aux opportunités climatiques",
            "Revenue related to climate opportunities", "ESRS-TAB-HORIZONS",
            _d("Chiffre d'affaires net de la période des activités liées aux opportunités climatiques identifiées (ESRS E1, "
               "§42 ; AR 29).",
               "Net revenue of the period from business activities related to the identified climate-related opportunities "
               "(ESRS E1, §42; AR 29).", suite=(HORIZONS[0] + PHASE_QUANTI[0], HORIZONS[1] + PHASE_QUANTI[1])), S_COMPTA),
])

# Entrée progressive de l'ESRS 1 §126(a) (toutes les normes thématiques avant 2027 pour les petites entreprises de la
# première vague) : même phrase que dans G1, ajoutée à chaque KPI propre au modèle ; les KPI repris de la norme VS ou
# du catalogue ne la portent pas (une seule définition, qui se lirait aussi dans une installation VS seule).
KPIS = dict(L.avec_phase_in(KPIS.items(), L.PHASE_IN_G1))

REGLES = {  # nom fr : (gauche, opérateur, droite, (description fr, en), nom en) ; niveau : celui du KPI de gauche
    "Énergie achetée nucléaire et renouvelable ≤ énergie achetée": (
        "[NRJ-ACHAT-NUCLEAIRE] + [NRJ-ACHAT-RENOUV]", "<=", "([NRJ-ELEC] + [NRJ-CHALEUR] + [NRJ-FROID]) / 1000",
        ("Les parts nucléaire et renouvelable de l'énergie achetée ne dépassent pas l'électricité, la chaleur, la vapeur et le "
         "froid achetés (en MWh) : sinon, la part fossile calculée serait négative. La vapeur est comptée avec la chaleur.",
         "The nuclear and renewable parts of purchased energy do not exceed the purchased electricity, heat, steam and cooling "
         "(in MWh): otherwise, the calculated fossil part would be negative. Steam is counted with heat."),
        "Purchased nuclear and renewable energy ≤ purchased energy"),
    "Charbon et autres produits pétroliers ≤ autres combustibles fossiles": (
        "[NRJ-CHARBON] + [NRJ-PETROLE-AUTRES]", "<=", "[NRJ-COMB-AUTRES]",
        ("Le charbon et les autres produits pétroliers font partie des « Autres combustibles fossiles » : sinon, les autres "
         "sources fossiles calculées seraient négatives.",
         "Coal and the other petroleum products are part of the “Other fossil fuels”: otherwise, the calculated other fossil "
         "sources would be negative."),
        "Coal and other petroleum products ≤ other fossil fuels"),
    "Production d'énergie renouvelable ≥ électricité renouvelable autoconsommée": (
        "[NRJ-PROD-REN]", ">=", "[NRJ-ELEC-AUTO] / 1000",
        ("L'électricité renouvelable produite et consommée sur place fait partie de l'énergie renouvelable produite (en MWh).",
         "Renewable electricity generated and consumed on site is part of the renewable energy produced (in MWh)."),
        "Renewable energy production ≥ self-generated renewable electricity consumed"),
    "Scope 1 couvert par le SEQE-UE ≤ scope 1 brut": (
        "[GES-S1-SEQE]", "<=", "[GES-S1-BRUT]",
        ("Les émissions couvertes par le SEQE-UE font partie des émissions brutes du scope 1.",
         "Emissions covered by the EU ETS are part of gross scope 1 emissions."),
        "Scope 1 covered by the EU ETS ≤ gross scope 1"),
    "Scope 1 hors du groupe consolidé ≤ scope 1 brut": (
        "[GES-S1-HORS-GROUPE]", "<=", "[GES-S1-BRUT]",
        ("La partie hors du groupe consolidé fait partie des émissions brutes du scope 1.",
         "The part outside the consolidated group is part of gross scope 1 emissions."),
        "Scope 1 outside the consolidated group ≤ gross scope 1"),
    "Scope 2 (localisation) hors du groupe consolidé ≤ scope 2 (localisation)": (
        "[GES-S2-LB-HORS-GROUPE]", "<=", "[GES-S2-LB]",
        ("La partie hors du groupe consolidé fait partie des émissions du scope 2 selon la méthode localisation.",
         "The part outside the consolidated group is part of location-based scope 2 emissions."),
        "Location-based scope 2 outside the consolidated group ≤ location-based scope 2"),
    "Scope 2 (marché) hors du groupe consolidé ≤ scope 2 (marché)": (
        "[GES-S2-MB-HORS-GROUPE]", "<=", "[GES-S2-MB]",
        ("La partie hors du groupe consolidé fait partie des émissions du scope 2 selon la méthode marché.",
         "The part outside the consolidated group is part of market-based scope 2 emissions."),
        "Market-based scope 2 outside the consolidated group ≤ market-based scope 2"),
    "Informatique en nuage ≤ scope 3 catégorie 1": (
        "[GES-S3-CLOUD]", "<=", "[GES-S3-ACHATS]",
        ("Les émissions des services d'informatique en nuage et de centres de données font partie de la catégorie 1 du "
         "scope 3 (biens et services achetés).",
         "Emissions of cloud computing and data centre services are part of scope 3 category 1 (purchased goods and "
         "services)."),
        "Cloud computing ≤ scope 3 category 1"),
}

# Données de calcul : KPI de la norme volontaire VS (B3), placés pour que les formules se calculent (une seule saisie).
NRJ_SAISIES = ["NRJ-ELEC", "NRJ-CHALEUR", "NRJ-FROID", "NRJ-GAZ", "NRJ-FIOUL", "GES-GAZOLE", "GES-ESSENCE",
               "NRJ-COMB-AUTRES"]
FACTEURS = ["CONV-GAZ-PCI", "CONV-FIOUL", "CONV-GAZOLE", "CONV-ESSENCE", "FE-GAZ", "FE-FIOUL", "FE-GAZOLE", "FE-ESSENCE",
            "FE-ELEC", "FE-CHALEUR", "FE-FROID"]
SCOPE3 = [("GES-S3-ACHATS", 1), ("GES-S3-IMMO", 2), ("GES-S3-ENERGIE", 3), ("GES-S3-FRET-AMONT", 4), ("GES-S3-DECHETS", 5),
          ("GES-S3-DEPLACEMENTS", 6), ("GES-S3-DOMICILE", 7), ("GES-S3-ACTIFS-AMONT", 8), ("GES-S3-FRET-AVAL", 9),
          ("GES-S3-TRANSFO", 10), ("GES-S3-UTILISATION", 11), ("GES-S3-FIN-VIE", 12), ("GES-S3-ACTIFS-AVAL", 13),
          ("GES-S3-FRANCHISES", 14), ("GES-S3-INVEST", 15)]
# Cibles absolues des scopes 1 et 2 : KPI de la norme volontaire VS (C3 §53), même définition que l'E1-6 §24(a) pour une
# cible absolue par scope (une année de référence, une année cible) ; le tableau des cibles reçoit les autres cibles.
CIBLES_ABSOLUES = ["GES-ANNEE-REF", "GES-ANNEE-CIBLE", "GES-S1-REF", "GES-S1-CIBLE", "GES-S2-LB-REF", "GES-S2-LB-CIBLE",
                   "GES-S2-MB-REF", "GES-S2-MB-CIBLE"]
# KPI repris de la norme volontaire VS et du catalogue commun (jamais redéfinis ici)
REPRIS = (NRJ_SAISIES + FACTEURS + [c for c, _ in SCOPE3] + [
    "GES-PLAN-STATUT", "GES-PLAN-ANNEE", *CIBLES_ABSOLUES, "NRJ-TOTAL-MWH", "NRJ-COMBUSTIBLES", "NRJ-COMB-REN", "NRJ-ELEC-AUTO", "GES-S1", "GES-S1-AUTRES",
    "GES-S1-FIXE", "GES-S1-MOBILE", "GES-FUGITIVES", "GES-S2-LB", "GES-S2-MB"])


def _gdr(dr, partie, extra=None):
    """Partie du bloc GDR ; ``extra`` : renvoi d'une référence en plus pour un code (« ; E1-5 · 22 »)."""
    extra = extra or {}
    return [(code, ref + extra.get(code, "")) for code, ref in C.arbre_gdr(PREFIXE, dr, partie)]


SOCLE = C.socle("ESRS_E1", "1.1", "2026-11-19", [
    ("E1_1", "E1-1 – Plan de transition pour l'atténuation du changement climatique",
     "E1-1 – Transition plan for climate change mitigation", [
         ("CLI-PLAN-TRANSITION", "E1-1 · 12(a)"), ("CLI-CAPEX-CHARBON", "E1-1 · 12(b)"), ("CLI-CAPEX-PETROLE", "E1-1 · 12(b)"),
         ("CLI-CAPEX-GAZ", "E1-1 · 12(b)"), ("CLI-PLAN-HYPOTHESES", "E1-1 · 12(c)"), ("CLI-PLAN-VERROUILLAGE", "E1-1 · 12(d)"),
         ("CLI-PLAN-AVANCEMENT", "E1-1 · 12(e)"), ("GES-PLAN-STATUT", "E1-1 · 13"), ("GES-PLAN-ANNEE", "E1-1 · 13")]),
    ("E1_2", "E1-2 – Risques climatiques et analyse de scénarios", "E1-2 – Climate-related risks and scenario analysis", [
        ("CLI-RISQUES-TAB", "E1-2 · 15"), ("CLI-METHODE-ALEAS", "E1-2 · 16(a)"), ("CLI-METHODE-TRANSITION", "E1-2 · 16(b)"),
        ("CLI-SCENARIOS-UTILISES", "E1-2 · 17"), ("CLI-SCENARIOS", "E1-2 · 17(a)"),
        ("CLI-SCEN-EMISSIONS-ELEVEES", "E1-2 · 17(a)(i)"), ("CLI-SCEN-1-5", "E1-2 · 17(a)(ii)"),
        ("CLI-SCEN-TEMPERATURE", "E1-2 · 17(a)(iii)"), ("CLI-SCEN-PERIMETRE", "E1-2 · 17(b)"),
        ("CLI-SCEN-HYPOTHESES", "E1-2 · 17(c)"), ("CLI-SCEN-ANNEE", "E1-2 · 17(d)")]),
    ("E1_3", "E1-3 – Résilience face au changement climatique", "E1-3 – Resilience in relation to climate change", [
        ("CLI-RESILIENCE", "E1-3 · 19(a)"), ("CLI-RESILIENCE-INCERTITUDES", "E1-3 · 19(b)"),
        ("CLI-RESILIENCE-ADAPTATION", "E1-3 · 19(c)")]),
    ("E1_4", "E1-4 – Politiques d'atténuation et d'adaptation", "E1-4 – Policies on climate change mitigation and adaptation",
     _gdr("E1-4", "P")),
    ("E1_5", "E1-5 – Actions et ressources pour l'atténuation et l'adaptation",
     "E1-5 – Actions and resources on climate change mitigation and adaptation", [
         *_gdr("E1-5", "A"), ("CLI-ACTIONS-LEVIERS", "E1-5 · 22(a)"), ("CLI-LEVIERS-TAB", "E1-5 · 22(a)-(b)")]),
    ("E1_6", "E1-6 – Cibles relatives au changement climatique", "E1-6 – Targets related to climate change", [
        *_gdr("E1-6", "T"), ("CLI-ZERO-NET-RESIDUEL", "E1-6 · AR 11"),
        ("E1_6_ABSOLUES", "Cibles absolues des scopes 1 et 2", "Absolute scope 1 and 2 targets", [
            (code, "E1-6 · 24(a)") for code in CIBLES_ABSOLUES]),  # N/A sans cible absolue de ce scope
        ("CLI-CIBLES-GES-TAB", "E1-6 · 24(a)-(b)"),
        ("CLI-CIBLES-SCIENCE", "E1-6 · 24(c)"), ("CLI-CIBLES-REFERENCE", "E1-6 · 24(c), AR 17"),
        ("CLI-CIBLES-SECTORIEL", "E1-6 · 24(c)"), ("CLI-CIBLES-EVOLUTIONS", "E1-6 · 24(c)")]),
    ("E1_7", "E1-7 – Consommation d'énergie et mix énergétique", "E1-7 – Energy consumption and mix", [
        ("NRJ-TOTAL-MWH", "E1-7 · 26"), ("NRJ-FOSSILE", "E1-7 · 26(a)"), ("NRJ-COMBUSTIBLES", "E1-7 · 26(a)"),
        ("NRJ-ACHAT-NUCLEAIRE", "E1-7 · 26(b)"), ("NRJ-RENOUVELABLE", "E1-7 · 26(c)"), ("NRJ-COMB-REN", "E1-7 · 26(c)"),
        ("NRJ-ELEC-AUTO", "E1-7 · 26(c)"), ("NRJ-ACHAT-RENOUV", "E1-7 · 26(c)"),
        ("E1_7_FOSSILE", "Énergie fossile par source (secteurs à fort impact climatique)",
         "Fossil energy by source (high climate impact sectors)", [
             ("NRJ-CHARBON", "E1-7 · 27(a)"), ("NRJ-PETROLE", "E1-7 · 27(b)"), ("NRJ-PETROLE-AUTRES", "E1-7 · 27(b)"),
             ("NRJ-GAZ-MWH", "E1-7 · 27(c)"), ("NRJ-FOSSILE-AUTRES", "E1-7 · 27(d)"), ("NRJ-ACHAT-FOSSILE", "E1-7 · 27(e)")]),
        ("NRJ-PROD-NON-REN", "E1-7 · 28"), ("NRJ-PROD-REN", "E1-7 · 28")]),
    ("E1_8", "E1-8 – Émissions brutes de GES des scopes 1, 2 et 3", "E1-8 – Gross scope 1, 2, 3 GHG emissions", [
        ("GES-S1-BRUT", "E1-8 · 30(a)(i)"), ("GES-S1-AUTRES", "E1-8 · 30(a)(i)"),
        ("GES-S1-HORS-GROUPE", "E1-8 · 30(c)(ii)"), ("GES-S1-GROUPE", "E1-8 · 30(c)(i)"),
        ("GES-S1-SEQE", "E1-8 · 30(a)(i)"), ("GES-PART-SEQE", "E1-8 · 30(a)(i)"),
        ("GES-S2-LB", "E1-8 · 30(a)(ii)"), ("GES-S2-LB-HORS-GROUPE", "E1-8 · 30(c)(ii)"), ("GES-S2-LB-GROUPE", "E1-8 · 30(c)(i)"),
        ("GES-S2-MB", "E1-8 · 30(a)(ii)"), ("GES-S2-MB-HORS-GROUPE", "E1-8 · 30(c)(ii)"), ("GES-S2-MB-GROUPE", "E1-8 · 30(c)(i)"),
        ("GES-S3-TOTAL", "E1-8 · 30(a)(iii)"),
        ("E1_8_S3", "Scope 3 par catégorie", "Scope 3 by category", [
            *[(code, f"E1-8 · 30(a)(iii), cat. {n}") for code, n in SCOPE3], ("GES-S3-CLOUD", "E1-8 · AR 24(g)")]),
        ("GES-BIOGENIQUE", "E1-8 · 31"), ("CLI-METHODE-GES", "E1-8 · 30(b)"), *_gdr("E1-8", "M")]),
    ("E1_9", "E1-9 – Absorptions de GES et crédits carbone", "E1-9 – GHG removals and carbon credits", [
        ("CLI-ABSORPTIONS", "E1-9 · 33"), ("CLI-ABSORPTIONS-PROJETS", "E1-9 · 33(a)"), ("CLI-ABSORPTIONS-TAB", "E1-9 · 33(b)"),
        ("CLI-ABSORPTIONS-PERMANENCE", "E1-9 · 33(c)"), ("GES-INVERSIONS", "E1-9 · 33(d)"),
        ("GES-CREDITS-ANNULES", "E1-9 · 34(a)"), ("GES-CREDITS-A-ANNULER", "E1-9 · 34(b)"),
        ("GES-PART-CREDITS-ABSORPTION", "E1-9 · 34(c)"), ("CLI-CREDITS-PUITS", "E1-9 · 34(c)"),
        ("CLI-NEUTRALITE", "E1-9 · 35"), ("CLI-NEUTRALITE-CIBLES", "E1-9 · 35(a)"), ("CLI-CREDITS-QUALITE", "E1-9 · 35(b)")]),
    ("E1_10", "E1-10 – Prix interne du carbone", "E1-10 – Internal carbon pricing", [
        ("CLI-PRIX-CARBONE", "E1-10 · 37(a)"), ("CLI-PRIX-CARBONE-DESC", "E1-10 · 37(a)"),
        ("CLI-PRIX-CARBONE-TAB", "E1-10 · 37(b)")]),
    ("E1_11", "E1-11 – Effets financiers attendus des risques et opportunités climatiques",
     "E1-11 – Anticipated financial effects of climate-related risks and opportunities", [
         ("CLI-ACTIFS-RISQUE-PHYS", "E1-11 · 39(a)"), ("CLI-PART-ACTIFS-ADAPT", "E1-11 · 39(b)"),
         ("CLI-CA-RISQUE-PHYS", "E1-11 · 39(c)"), ("CLI-ACTIFS-RISQUE-TRANS", "E1-11 · 40(a)"),
         ("CLI-ACTIFS-ECHOUES", "E1-11 · 40(a)"), ("CLI-PART-ACTIFS-ATTEN", "E1-11 · 40(b)"),
         ("CLI-IMMO-GARANTIES", "E1-11 · 40(c)"), ("CLI-PASSIFS-POTENTIELS", "E1-11 · 40(d)"),
         ("CLI-CA-RISQUE-TRANS", "E1-11 · 40(e)"), ("CLI-CA-CLIENTS-FOSSILES", "E1-11 · 40(e)"),
         ("CLI-EFFETS-METHODE", "E1-11 · 41"), ("CLI-EFFETS-SCENARIOS", "E1-11 · 41"),
         ("CLI-ACTIFS-OPPORTUNITES", "E1-11 · 42"), ("CLI-CA-OPPORTUNITES", "E1-11 · 42")]),
    ("E1_DONNEES", "Données de calcul", "Calculation data", [
        ("E1_DONNEES_NRJ", "Énergie consommée par le site", "Energy consumed by the site", [
            (code, "E1-7 · 26") for code in NRJ_SAISIES]),
        ("E1_DONNEES_GES", "Sous-totaux du scope 1", "Scope 1 subtotals", [
            ("GES-S1", "E1-8 · 30(a)(i)"), ("GES-S1-FIXE", "E1-8 · 30(a)(i)"), ("GES-S1-MOBILE", "E1-8 · 30(a)(i)"),
            ("GES-FUGITIVES", "E1-8 · 30(a)(i)")]),
        ("E1_DONNEES_FACTEURS", "Facteurs de conversion et d'émission", "Conversion and emission factors", FACTEURS)]),
], regles=list(REGLES))
