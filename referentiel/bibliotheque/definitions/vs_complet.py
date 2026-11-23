"""Norme volontaire VS (ex-VSME) – module complet (C1 à C9), à installer avec le module de base.

Même source que vs_base.py (règlement délégué (UE) 2026/1560, modèle numérique 2.0.0 de l'EFRAG). Le module complet
s'ajoute au module de base : l'export indique alors « Option B » dans le classeur officiel. Les KPI du module de base
dont il se sert (effectifs, émissions des scopes 1 et 2) ne sont pas redéfinis ici.
"""
from referentiel.bibliotheque.outils import kpi

from ._vs_listes import CATEGORIES_SCOPE3

from .vs_base import PETITE, SOURCE  # noqa: F401 (SOURCE : même norme d'origine)

TYPES_REPONSE = [
    ("VS-CATEGORIE-S3", ("Catégorie du scope 3", "Scope 3 category"), "liste",
     {"fr": [c[1] for c in CATEGORIES_SCOPE3], "en": [c[0] for c in CATEGORIES_SCOPE3]}),
    ("VS-TAB-CIBLES-S3", ("Cibles du scope 3 par catégorie", "Scope 3 targets by category"), "tableau", [
        {"code": "categorie", "libelle": {"fr": "Catégorie", "en": "Category"}, "type": "liste", "liste": "VS-CATEGORIE-S3"},
        {"code": "reference", "libelle": {"fr": "Émissions de l'année de référence", "en": "Base-year emissions"}, "type": "nombre",
         "unite": "tCO2e"},
        {"code": "cible", "libelle": {"fr": "Émissions visées l'année cible", "en": "Target-year emissions"}, "type": "nombre",
         "unite": "tCO2e"}]),
    ("VS-STATUT-PLAN", ("Statut du plan de transition", "Status of the transition plan"), "liste",
     {"fr": ["L'adoption d'un plan de transition est prévue", "Un plan de transition a déjà été adopté",
             "Aucun plan de transition n'est en place ni prévu"],
      "en": ["Adoption of a transition plan is planned in the future", "A transition plan has already been adopted",
             "A transition plan is not in place and it is not planned to be adopted"]}),
]

HAUT = "haut"


def oui_non(code, fr, en, description, niveau=HAUT):
    return kpi(code, fr, en, "", "Décompte", reponse="OuiNon", niveau=niveau, description=description)


def texte(code, fr, en, description):
    return kpi(code, fr, en, "", "Aucune", reponse="Texte", niveau=HAUT, description=description)


SOURCE_CIBLES = ("Stratégie climat ou plan de transition, bilan des émissions de l'année de référence.",
                 "Climate strategy or transition plan, base-year emissions inventory.")
SOURCE_ORGANE = ("Statuts, procès-verbaux, registre des mandataires sociaux.", "Articles of association, minutes, register of directors.")


def nombre_haut(code, fr, en, unite, description):
    """Nombre donné une fois pour l'entreprise (année, cible, membres de l'organe de gouvernance)."""
    # une année ne s'additionne pas d'une organisation à l'autre : agrégation « Aucune » (saisie au niveau le plus haut)
    return kpi(code, fr, en, unite, "Aucune" if unite == "année" else "Somme", niveau=HAUT,
               temps="derniere" if unite in ("personnes", "salariés", "année") else "",
               description=description, source=SOURCE_ORGANE if code.startswith("GOV-") else SOURCE_CIBLES)


KPIS = dict([
    # ------------------------------------------------------------------ C1 – stratégie
    texte("STR-PRODUITS", "Principaux groupes de produits et services", "Significant groups of products and services",
          ("Décrire les principaux groupes de produits et de services proposés.", "Describe the significant groups of products and services offered.")),
    texte("STR-MARCHES", "Principaux marchés", "Significant markets",
          ("Décrire les principaux marchés (par exemple entre entreprises, commerce de gros, de détail, pays).",
           "Describe the significant markets (for example business-to-business, wholesale, retail, countries).")),
    texte("STR-RELATIONS", "Principales relations d'affaires", "Main business relationships",
          ("Décrire les principales relations d'affaires (fournisseurs clés et leur nombre estimé, secteurs et pays, clients, "
           "canaux de distribution).",
           "Describe the main business relationships (key suppliers and their estimated number, sectors and countries, "
           "customers, distribution channels).")),
    oui_non("STR-ENJEUX", "Éléments de la stratégie liés à la durabilité", "Strategy elements related to sustainability",
            ("La stratégie comporte-t-elle des éléments clés liés à des enjeux de durabilité ?",
             "Does the strategy have key elements related to sustainability issues?")),
    texte("STR-ENJEUX-DESC", "Description des éléments de la stratégie liés à la durabilité",
          "Description of the strategy elements related to sustainability",
          ("Décrire ces éléments clés de la stratégie.", "Describe these key elements of the strategy.")),
    # ------------------------------------------------------------------ C2 – pratiques et politiques (description)
    texte("GOV-C2-DESC", "Description des pratiques, politiques et initiatives", "Description of practices, policies and initiatives",
          ("Brève description des pratiques, politiques et initiatives déclarées en B2 ; préciser si elles couvrent aussi les "
           "fournisseurs ou les clients.",
           "Short description of the practices, policies and initiatives reported in B2; say whether they also cover suppliers "
           "or customers.")),
    texte("GOV-C2-CIBLES", "Description des cibles liées aux politiques", "Description of the targets related to policies",
          ("Décrire les cibles fixées pour ces politiques.", "Describe the targets set for these policies.")),
    texte("GOV-C2-RESPONSABLE", "Responsable de plus haut niveau des pratiques et politiques",
          "Most senior level accountable for practices and policies",
          ("Personne ou organe de plus haut niveau responsable de la mise en œuvre (facultatif).",
           "Most senior person or body accountable for implementation (optional).")),
    # ------------------------------------------------------------------ C3 – cibles de réduction et transition climatique
    oui_non("GES-CIBLES", "Cibles de réduction des émissions de gaz à effet de serre", "Greenhouse gas reduction targets",
            ("L'entreprise a-t-elle fixé des cibles de réduction de ses émissions (scopes 1 et 2, et 3 le cas échéant) ?",
             "Has the company set reduction targets for its emissions (scopes 1 and 2, and 3 if any)?")),
    nombre_haut("GES-ANNEE-REF", "Année de référence des cibles", "Base year of the targets", "année",
                ("Année de référence des cibles de réduction.", "Base year of the reduction targets.")),
    nombre_haut("GES-ANNEE-CIBLE", "Année cible", "Target year", "année",
                ("Année à laquelle les cibles doivent être atteintes.", "Year by which the targets must be met.")),
] + [
    kpi(code, fr, en, "tCO2e", "Aucune", decimales=1, niveau=HAUT, temps="derniere", description=(dfr, den), source=SOURCE_CIBLES)
    for code, fr, en, dfr, den in (
        ("GES-S1-REF", "Scope 1 de l'année de référence", "Scope 1 in the base year",
         "Émissions du scope 1 de l'année de référence.", "Scope 1 emissions in the base year."),
        ("GES-S1-CIBLE", "Cible du scope 1", "Scope 1 target", "Émissions du scope 1 visées pour l'année cible.",
         "Scope 1 emissions targeted for the target year."),
        ("GES-S2-LB-REF", "Scope 2 (localisation) de l'année de référence", "Scope 2 (location-based) in the base year",
         "Émissions du scope 2, méthode localisation, de l'année de référence.", "Location-based scope 2 emissions in the base year."),
        ("GES-S2-LB-CIBLE", "Cible du scope 2 (localisation)", "Scope 2 (location-based) target",
         "Émissions du scope 2, méthode localisation, visées pour l'année cible.", "Location-based scope 2 emissions targeted for the target year."),
        ("GES-S2-MB-REF", "Scope 2 (marché) de l'année de référence", "Scope 2 (market-based) in the base year",
         "Émissions du scope 2, méthode marché, de l'année de référence (facultatif).", "Market-based scope 2 emissions in the base year (optional)."),
        ("GES-S2-MB-CIBLE", "Cible du scope 2 (marché)", "Scope 2 (market-based) target",
         "Émissions du scope 2, méthode marché, visées pour l'année cible (facultatif).",
         "Market-based scope 2 emissions targeted for the target year (optional)."))
] + [
    kpi("GES-S3-CIBLES", "Cibles du scope 3 par catégorie", "Scope 3 targets by category", "", "Aucune", reponse="VS-TAB-CIBLES-S3",
        niveau=HAUT, description=("Si l'entreprise s'est fixé des cibles pour le scope 3 : une ligne par catégorie, avec les "
                                  "émissions de l'année de référence et celles visées pour l'année cible.",
                                  "If the company has set scope 3 targets: one row per category, with the base-year emissions and "
                                  "those targeted for the target year."), source=SOURCE_CIBLES),
    texte("GES-ACTIONS", "Principales actions pour atteindre les cibles", "Main actions to achieve the targets",
          ("Lister les principales actions prévues pour atteindre les cibles.", "List the main actions planned to achieve the targets.")),
    kpi("GES-PLAN-STATUT", "Statut du plan de transition", "Status of the transition plan", "", "Décompte", reponse="VS-STATUT-PLAN",
        niveau=HAUT, description=("Un plan de transition pour l'atténuation du changement climatique est-il adopté, prévu ou ni "
                                  "l'un ni l'autre ? L'année prévue d'adoption se saisit à part. Qui répond : dans la norme "
                                  "volontaire VS, une entreprise d'un secteur à fort impact climatique (C3 §54-55) ; dans les "
                                  "ESRS, toute entreprise, un plan adopté étant un plan qui contient les principales "
                                  "caractéristiques de l'E1-1 §12(a) (E1-1 §13).",
                                  "Is a transition plan for climate change mitigation adopted, planned, or neither? The planned "
                                  "year of adoption is entered separately. Who answers: in the Voluntary Standard VS, a company in "
                                  "a high climate impact sector (C3 §54-55); in the ESRS, every company, an adopted plan being "
                                  "one that includes the key features of E1-1 §12(a) (E1-1 §13).")),
    texte("GES-PLAN-DESC", "Description du plan de transition", "Description of the transition plan",
          ("Décrire le plan de transition et comment il réduit les émissions (facultatif).",
           "Describe the transition plan and how it reduces emissions (optional).")),
    nombre_haut("GES-PLAN-ANNEE", "Année prévue d'adoption du plan de transition", "Planned year of adoption of the transition plan",
                "année", ("Si le plan n'est pas encore adopté : année prévue de son adoption.",
                          "If the plan is not adopted yet: year planned for its adoption.")),
    kpi("GES-PLAN-MOIS", "Mois prévu d'adoption du plan de transition", "Planned month of adoption of the transition plan", "",
        "Aucune", temps="derniere", niveau=HAUT, description=("Mois (1 à 12), avec l'année ci-dessus.", "Month (1 to 12), with the year above."),
        source=SOURCE_CIBLES),
    kpi("GES-PLAN-JOUR", "Jour prévu d'adoption du plan de transition", "Planned day of adoption of the transition plan", "",
        "Aucune", temps="derniere", niveau=HAUT, description=("Jour (1 à 31), avec le mois et l'année ci-dessus.",
                                                             "Day (1 to 31), with the month and year above."), source=SOURCE_CIBLES),
        # ------------------------------------------------------------------ C4 – risques climatiques
    oui_non("CLI-RISQUES", "Aléas et événements de transition climatiques identifiés", "Climate hazards and transition events identified",
            ("L'entreprise a-t-elle identifié des aléas climatiques et des événements liés à la transition climatique ?",
             "Has the company identified climate-related hazards and transition events?")),
    texte("CLI-ALEAS", "Aléas climatiques et événements de transition", "Climate hazards and transition events",
          ("Décrire les aléas climatiques et les événements liés à la transition climatique.",
           "Describe the climate-related hazards and transition events.")),
    texte("CLI-EXPOSITION", "Évaluation de l'exposition et de la sensibilité", "Assessment of exposure and sensitivity",
          ("Comment l'entreprise a évalué l'exposition et la sensibilité de ses actifs, activités et chaîne de valeur.",
           "How the company assessed the exposure and sensitivity of its assets, activities and value chain.")),
    texte("CLI-HORIZONS", "Horizons temporels des aléas et événements", "Time horizons of the hazards and events",
          ("Court terme : 1 an ; moyen terme : 2 à 5 ans ; long terme : plus de 5 ans.",
           "Short term: 1 year; medium term: 2 to 5 years; long term: more than 5 years.")),
    oui_non("CLI-ADAPTATION", "Actions d'adaptation au changement climatique", "Climate change adaptation actions",
            ("L'entreprise a-t-elle entrepris des actions d'adaptation pour ces aléas et événements ?",
             "Has the company taken adaptation actions for these hazards and events?")),
    texte("CLI-EFFETS", "Effets financiers potentiels des risques climatiques", "Potential financial effects of climate risks",
          ("Effets négatifs potentiels sur les performances financières ou les activités, à court, moyen ou long terme "
           "(facultatif).", "Potential adverse effects on financial performance or operations, in the short, medium or long term "
                           "(optional).")),
    # ------------------------------------------------------------------ C5 – caractéristiques complémentaires des effectifs
    kpi("SOC-DEPARTS-CDI", "Départs de salariés en CDI", "Leavers on permanent contracts", "salariés",
        description=("Salariés en CDI ayant quitté l'entreprise pendant la période (démission, licenciement, retraite, décès en "
                     "service), en nombre de personnes.",
                     "Employees on permanent contracts who left during the period (resignation, dismissal, retirement, death in "
                     "service), as a headcount."),
        source=("Système d'information RH.", "HR information system.")),
    kpi("SOC-EFFECTIF-DEBUT", "Effectif au début de la période", "Headcount at the start of the period", "salariés", "Aucune",
        temps="derniere", niveau=HAUT,
        description=("Seulement la première année suivie dans l'outil : salariés inscrits à l'effectif au début de la période. "
                     "Les années suivantes, l'effectif de fin de l'exercice précédent sert de point de départ au taux de rotation.",
                     "Only for the first year tracked in the tool: employees on the payroll at the start of the period. In the "
                     "following years, the headcount at the end of the previous year is the starting point of the turnover rate."),
        source=("Système d'information RH.", "HR information system.")),
    kpi("SOC-MANAGERS-FEMMES", "Femmes au niveau de la direction", "Women at management level", "salariés", temps="derniere",
        description=("Femmes au niveau de la direction, en fin de période (facultatif).", "Women at management level, at period end (optional)."),
        source=("Système d'information RH.", "HR information system.")),
    kpi("SOC-MANAGERS-HOMMES", "Hommes au niveau de la direction", "Men at management level", "salariés", temps="derniere",
        description=("Hommes au niveau de la direction, en fin de période (facultatif).", "Men at management level, at period end (optional)."),
        source=("Système d'information RH.", "HR information system.")),
    kpi("SOC-INDEPENDANTS", "Indépendants travaillant exclusivement pour l'entreprise", "Self-employed working exclusively for the company",
        "personnes", temps="derniere",
        description=("Travailleurs indépendants sans salarié qui travaillent exclusivement pour l'entreprise (facultatif).",
                     "Self-employed workers without employees working exclusively for the company (optional)."),
        source=("Achats, contrats de prestation.", "Purchasing, service contracts.")),
    kpi("SOC-INTERIMAIRES", "Intérimaires", "Temporary agency workers", "personnes", temps="derniere",
        description=("Travailleurs temporaires mis à disposition par des entreprises de travail temporaire (facultatif).",
                     "Temporary workers provided by employment agencies (optional)."),
        source=("Factures des agences d'intérim.", "Temporary agency invoices.")),
    # ------------------------------------------------------------------ C6 – politiques en matière de droits humains
    oui_non("SOC-CODE-CONDUITE", "Code de conduite ou politique des droits humains", "Code of conduct or human rights policy",
            ("L'entreprise a-t-elle un code de conduite ou une politique en matière de droits humains pour son personnel ?",
             "Does the company have a code of conduct or human rights policy for its own workforce?")),
] + [
    oui_non(f"SOC-CODE-{c}", f"Code de conduite : {fr}", f"Code of conduct: {en}",
            (f"Le code de conduite ou la politique couvre-t-il : {fr} ?", f"Does the code of conduct or policy cover: {en}?"))
    for c, fr, en in (("ENFANTS", "travail des enfants", "child labour"), ("FORCE", "travail forcé", "forced labour"),
                      ("TRAITE", "traite des êtres humains", "human trafficking"), ("DISCRIMINATION", "discrimination", "discrimination"),
                      ("ACCIDENTS", "prévention des accidents", "accident prevention"), ("AUTRE", "autre sujet", "other topic"))
] + [
    texte("SOC-CODE-AUTRE-DESC", "Autres sujets couverts par le code de conduite", "Other topics covered by the code of conduct",
          ("Préciser les autres sujets couverts.", "Specify the other topics covered.")),
    oui_non("SOC-PLAINTES", "Mécanisme de traitement des plaintes du personnel", "Complaints-handling mechanism for the workforce",
            ("L'entreprise dispose-t-elle d'un mécanisme de traitement des plaintes pour son personnel ?",
             "Does the company have a complaints-handling mechanism for its own workforce?")),
    # ------------------------------------------------------------------ C7 – incidents relatifs aux droits humains
    oui_non("SOC-INCIDENTS", "Incidents confirmés au sein du personnel", "Confirmed incidents in the own workforce",
            ("Y a-t-il eu des incidents confirmés (établis par une juridiction, l'OCDE ou une autorité) au sein du personnel ?",
             "Were there confirmed incidents (established by a court, the OECD or an authority) in the own workforce?")),
] + [
    oui_non(f"SOC-INCIDENT-{c}", f"Incident confirmé : {fr}", f"Confirmed incident: {en}",
            (f"Un incident confirmé porte-t-il sur : {fr} ?", f"Does a confirmed incident relate to: {en}?"))
    for c, fr, en in (("ENFANTS", "travail des enfants", "child labour"), ("FORCE", "travail forcé", "forced labour"),
                      ("TRAITE", "traite des êtres humains", "human trafficking"), ("DISCRIMINATION", "discrimination", "discrimination"),
                      ("AUTRE", "autre droit de l'homme", "other human right"))
] + [
    texte("SOC-INCIDENT-AUTRE-DESC", "Autres droits humains concernés par les incidents", "Other human rights concerned by the incidents",
          ("Préciser les autres droits humains concernés.", "Specify the other human rights concerned.")),
    texte("SOC-INCIDENTS-ACTIONS", "Actions menées après les incidents confirmés", "Actions taken after the confirmed incidents",
          ("Décrire les actions menées (facultatif).", "Describe the actions taken (optional).")),
    oui_non("SOC-INCIDENTS-CHAINE", "Incidents confirmés dans la chaîne de valeur", "Confirmed incidents in the value chain",
            ("L'entreprise a-t-elle connaissance d'incidents confirmés pendant la période impliquant des travailleurs de la chaîne "
             "de valeur, des communautés affectées, des consommateurs ou des utilisateurs finaux ?",
             "Is the company aware of confirmed incidents during the period involving value chain workers, affected communities, "
             "consumers or end-users?")),
    texte("SOC-INCIDENTS-CHAINE-DESC", "Description des incidents dans la chaîne de valeur", "Description of the incidents in the value chain",
          ("Préciser ces incidents.", "Specify these incidents.")),
    # ------------------------------------------------------------------ C8 – revenus de certaines activités
    oui_non("GOV-REV-SECTEURS", "Revenus de certaines activités", "Revenues from certain activities",
            ("L'entreprise tire-t-elle des revenus d'une des activités ci-dessous (armes interdites, tabac, combustibles fossiles, "
             "produits chimiques) ?", "Does the company derive revenues from one of the activities below (prohibited weapons, "
                                      "tobacco, fossil fuels, chemicals)?")),
] + [
    kpi(code, fr, en, "€", niveau=HAUT, description=(dfr, den), source=("Comptabilité.", "Accounting."))
    for code, fr, en, dfr, den in (
        ("GOV-REV-ARMES", "Revenus des armes interdites", "Revenue from prohibited weapons",
         "Mines antipersonnel, armes à sous-munitions, armes chimiques et biologiques.", "Anti-personnel mines, cluster munitions, chemical and biological weapons."),
        ("GOV-REV-TABAC", "Revenus du tabac", "Revenue from tobacco", "Culture et production de tabac.", "Cultivation and production of tobacco."),
        ("GOV-REV-CHARBON", "Revenus du charbon", "Revenue from coal", "Activités liées au charbon.", "Coal-related activities."),
        ("GOV-REV-PETROLE", "Revenus du pétrole", "Revenue from oil", "Activités liées au pétrole.", "Oil-related activities."),
        ("GOV-REV-GAZ", "Revenus du gaz", "Revenue from gas", "Activités liées au gaz.", "Gas-related activities."),
        ("GOV-REV-CHIMIE", "Revenus de la production de produits chimiques", "Revenue from chemicals production",
         "Fabrication de pesticides et d'autres produits agrochimiques (groupe NACE 20.2).",
         "Manufacture of pesticides and other agrochemical products (NACE group 20.2)."))
] + [
    # ------------------------------------------------------------------ C9 – mixité de l'organe de gouvernance
    oui_non("GOV-ORGANE", "Organe de gouvernance en place", "Governance body in place",
            ("L'entreprise a-t-elle un organe de gouvernance (conseil d'administration, conseil de surveillance) ?",
             "Does the company have a governance body (board of directors, supervisory board)?")),
    nombre_haut("GOV-CA-FEMMES", "Femmes membres de l'organe de gouvernance", "Female members of the governance body", "personnes",
                ("Femmes membres de l'organe de gouvernance en fin de période.", "Female members of the governance body at period end.")),
    nombre_haut("GOV-CA-HOMMES", "Hommes membres de l'organe de gouvernance", "Male members of the governance body", "personnes",
                ("Hommes membres de l'organe de gouvernance en fin de période.", "Male members of the governance body at period end.")),
])

# Informations facultatives pour les entreprises de 10 salariés au plus (« [Voluntary for undertakings with 10 employees or
# less] » dans la norme) : C1 · 46, C3 · 53, C4 · 56, C5 · 58, C6 · 61(a) et (c), C7 · 62(a) et (c).
# SOC-DEPARTS-CDI et SOC-PLAINTES sont aussi placés par l'ESRS S1 : leur description reste neutre, la dispense est dite dans
# la description du modèle (C5 taux de rotation, C6).
for _code in ("STR-PRODUITS", "STR-MARCHES", "STR-RELATIONS", "STR-ENJEUX", "GES-CIBLES", "CLI-RISQUES",
              "SOC-CODE-CONDUITE", "SOC-INCIDENTS", "SOC-INCIDENTS-CHAINE"):
    if _code in KPIS:
        _fr, _en = KPIS[_code]["description"]
        KPIS[_code]["description"] = (_fr + PETITE[0], _en + PETITE[1])

SOCLE = {
    "code": "VS_COMPLET",
    "fichier": "vs_complet.json",
    "couleur": "#7A4A0B",
    "version": "1.1",
    "date": "2026-11-18",
    "ordre": 11,
    "thematique": ("Normes de reporting", "Reporting standards"),
    "nom": ("Norme volontaire VS (ex-VSME) – module complet", "Voluntary Standard VS (formerly VSME) – Comprehensive Module"),
    "description": (
        "Informations C1 à C9 de la norme volontaire européenne, à ajouter au module de base (option B du classeur officiel de "
        "l'EFRAG) : stratégie, cibles climat, risques climatiques, effectifs, droits humains, revenus sensibles, mixité. C1, "
        "C3, C4, le taux de rotation (C5), C6 et C7 sont en grande partie facultatifs pour les entreprises de 10 salariés au "
        "plus (réponse N/A).",
        "Disclosures C1 to C9 of the European Voluntary Standard, added to the Basic Module (option B of EFRAG's official "
        "workbook): strategy, climate targets, climate risks, workforce, human rights, sensitive revenues, gender diversity. C1, "
        "C3, C4, the turnover rate (C5), C6 and C7 are largely voluntary for companies with 10 employees or less (answer N/A)."),
    "arbre": [
        ("C1", "C1 – Stratégie et modèle d'affaires", "C1 – Strategy and business model", [
            ("STR-PRODUITS", "C1 · 46(a)"), ("STR-MARCHES", "C1 · 46(b)"), ("STR-RELATIONS", "C1 · 46(c)"),
            ("STR-ENJEUX", "C1 · 46(d)"), ("STR-ENJEUX-DESC", "C1 · 46(d)")]),
        ("C2", "C2 – Description des pratiques, politiques et initiatives", "C2 – Description of practices, policies and initiatives", [
            ("GOV-C2-DESC", "C2 · 47"), ("GOV-C2-CIBLES", "C2 · 47"), ("GOV-C2-RESPONSABLE", "C2 · 48", False)]),
        ("C3", "C3 – Cibles de réduction et transition climatique", "C3 – GHG reduction targets and climate transition", [
            ("GES-CIBLES", "C3 · 53"), ("GES-ANNEE-REF", "C3 · 53(b)"), ("GES-ANNEE-CIBLE", "C3 · 53(a)"),
            ("GES-S1-REF", "C3 · 53(b)"), ("GES-S1-CIBLE", "C3 · 53(a)"), ("GES-S2-LB-REF", "C3 · 53(b)"),
            ("GES-S2-LB-CIBLE", "C3 · 53(a)"), ("GES-S2-MB-REF", "C3 · 53(b)", False), ("GES-S2-MB-CIBLE", "C3 · 53(a)", False),
            ("GES-S3-CIBLES", "C3 · 53, 49-52", False), ("GES-ACTIONS", "C3 · 53(e)"), ("GES-PLAN-STATUT", "C3 · 54-55"), ("GES-PLAN-DESC", "C3 · 54", False),
            ("GES-PLAN-ANNEE", "C3 · 55"), ("GES-PLAN-MOIS", "C3 · 55"), ("GES-PLAN-JOUR", "C3 · 55")]),
        ("C4", "C4 – Risques climatiques", "C4 – Climate risks", [
            ("CLI-RISQUES", "C4 · 56"), ("CLI-ALEAS", "C4 · 56(a)"), ("CLI-EXPOSITION", "C4 · 56(b)"), ("CLI-HORIZONS", "C4 · 56(c)"),
            ("CLI-ADAPTATION", "C4 · 56(d)"), ("CLI-EFFETS", "C4 · 57", False)]),
        ("C5", "C5 – Caractéristiques complémentaires des effectifs", "C5 – Additional workforce characteristics", [
            ("SOC-DEPARTS-CDI", "C5 · 58"), ("SOC-EFFECTIF-DEBUT", "C5 · 58", False), ("SOC-MANAGERS-FEMMES", "C5 · 59", False), ("SOC-MANAGERS-HOMMES", "C5 · 59", False),
            ("SOC-INDEPENDANTS", "C5 · 60", False), ("SOC-INTERIMAIRES", "C5 · 60", False)]),
        ("C6", "C6 – Politiques en matière de droits humains", "C6 – Human rights policies and processes", [
            ("SOC-CODE-CONDUITE", "C6 · 61(a)")] + [(f"SOC-CODE-{c}", "C6 · 61(b)") for c in (
                "ENFANTS", "FORCE", "TRAITE", "DISCRIMINATION", "ACCIDENTS", "AUTRE")] + [
            ("SOC-CODE-AUTRE-DESC", "C6 · 61(b)(vi)"), ("SOC-PLAINTES", "C6 · 61(c)")]),
        ("C7", "C7 – Incidents relatifs aux droits humains", "C7 – Human rights incidents", [
            ("SOC-INCIDENTS", "C7 · 62(a)")] + [(f"SOC-INCIDENT-{c}", "C7 · 62(a)") for c in (
                "ENFANTS", "FORCE", "TRAITE", "DISCRIMINATION", "AUTRE")] + [
            ("SOC-INCIDENT-AUTRE-DESC", "C7 · 62(a)(v)"), ("SOC-INCIDENTS-ACTIONS", "C7 · 62(b)", False),
            ("SOC-INCIDENTS-CHAINE", "C7 · 62(c)"), ("SOC-INCIDENTS-CHAINE-DESC", "C7 · 62(c)")]),
        ("C8", "C8 – Revenus de certaines activités", "C8 – Revenues from certain activities", [
            ("GOV-REV-SECTEURS", "C8 · 63"), ("GOV-REV-ARMES", "C8 · 63(a)"), ("GOV-REV-TABAC", "C8 · 63(b)"),
            ("GOV-REV-CHARBON", "C8 · 63(c)"), ("GOV-REV-PETROLE", "C8 · 63(c)"), ("GOV-REV-GAZ", "C8 · 63(c)"),
            ("GOV-REV-CHIMIE", "C8 · 63(d)")]),
        ("C9", "C9 – Mixité de l'organe de gouvernance", "C9 – Gender diversity of the governance body", [
            ("GOV-ORGANE", "C9 · 64"), ("GOV-CA-FEMMES", "C9 · 64"), ("GOV-CA-HOMMES", "C9 · 64")]),
    ],
    "regles": [],
}
