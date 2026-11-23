"""Socles retirés de la bibliothèque (règle du projet : ils servaient d'essai ; la bibliothèque ne
propose plus que la norme volontaire VS). Énergie, Gaz à effet de serre, Social et « ESRS – indicateurs quantitatifs
(simplifié) » ne sont plus fournis : aucun paquet JSON n'est écrit pour eux et aucune installation ne les voit dans la
bibliothèque.

Leurs définitions restent ici, inchangées (mêmes codes, identifiants, versions et dates), pour :
- les installations qui les avaient installés : leur référentiel reste entier et utilisable (KPI, valeurs, formules,
  historique) ; le contrôle des unités (``controle.unites_connues``) tient compte des unités qu'elles ont déjà ;
- les tests : jeux d'essai de la mécanique d'installation et état d'une installation qui les avait installés
  (``collecte/aides_tests/bibliotheque_essai.py``).

Leurs KPI et leurs règles restent dans le catalogue commun (``socles.KPIS``, ``socles.REGLES``) : la norme VS en réutilise
une partie, et un KPI garde une seule définition."""

# Arbre de chaque socle : (code du thème, nom fr, nom en, contenu) ; contenu = sous-thèmes et KPI (code, ou (code, code dans le
# référentiel, obligatoire)).
SOCLES_RETIRES = [
    {"code": "SOCLE_ENERGIE", "date": "2026-11-12", "fichier": "socle_energie.json", "couleur": "#E07A1F",
     "thematique": ("Climat et énergie", "Climate and energy"),  # rangement dans la bibliothèque (page Référentiels)
     "nom": ("Énergie (modèle)", "Energy (template)"),
     "description": ("Consommations d'énergie des sites par source, part renouvelable, intensité énergétique.",
                     "Site energy consumption by source, renewable share, energy intensity."),
     "arbre": [
         ("CONSO", "Consommations d'énergie", "Energy consumption", [
             ("ELEC", "Électricité", "Electricity", [("NRJ-ELEC", "E-1"), ("NRJ-ELEC-AUTO", "E-2")]),
             ("COMBUSTIBLES", "Combustibles", "Fuels", [("NRJ-GAZ", "E-3"), ("NRJ-FIOUL", "E-4")]),
             ("RESEAUX", "Chaleur et froid achetés", "Purchased heat and cooling", [("NRJ-CHALEUR", "E-5"), ("NRJ-FROID", "E-6")]),
             ("NRJ-TOTAL", "E-7"),
         ]),
         ("RENOUVELABLES", "Énergies renouvelables", "Renewable energy", [("NRJ-ELEC-REN", "E-8"), ("NRJ-PART-REN", "E-9")]),
         ("PERFORMANCE", "Performance énergétique", "Energy performance", [
             ("NRJ-SURFACE", "E-10"), ("NRJ-INTENSITE", "E-11"), ("NRJ-EVOL", "E-12"), ("NRJ-MANAGEMENT", "E-13", False)]),
         ("CONVERSION", "Facteurs de conversion", "Conversion factors", [("CONV-FIOUL", "E-14")]),
     ],
     "regles": ["Électricité renouvelable achetée ≤ électricité achetée"]},
    {"code": "SOCLE_GES", "date": "2026-11-12", "fichier": "socle_ges.json", "couleur": "#2E7D5B",
     "thematique": ("Climat et énergie", "Climate and energy"),  # rangement dans la bibliothèque (page Référentiels)
     "nom": ("Gaz à effet de serre – scopes 1, 2 et 3", "Greenhouse gases – scopes 1, 2 and 3"),
     "description": ("Émissions selon le GHG Protocol : scopes 1 et 2 calculés à partir des consommations et des facteurs d'émission, "
                     "scope 3 saisi par catégorie (résultats d'un bilan carbone), intensité carbone.",
                     "Emissions following the GHG Protocol: scopes 1 and 2 calculated from consumption and emission factors, scope 3 "
                     "entered by category (results of a carbon footprint), carbon intensity."),
     "arbre": [
         ("SCOPE1", "Scope 1 – émissions directes", "Scope 1 – direct emissions", [
             ("COMBUSTION_FIXE", "Combustion fixe", "Stationary combustion", ["NRJ-GAZ", "NRJ-FIOUL", ("GES-S1-FIXE", "Scope 1")]),
             ("COMBUSTION_MOBILE", "Combustion mobile", "Mobile combustion", ["GES-GAZOLE", "GES-ESSENCE", ("GES-S1-MOBILE", "Scope 1")]),
             ("FUGITIVES", "Émissions fugitives", "Fugitive emissions", [("GES-FUGITIVES", "Scope 1")]),
             ("GES-S1", "Scope 1"),
         ]),
         ("SCOPE2", "Scope 2 – énergie achetée", "Scope 2 – purchased energy", [
             "NRJ-ELEC", "NRJ-CHALEUR", "NRJ-FROID", ("GES-S2-LB", "Scope 2")]),
         ("SCOPE3", "Scope 3 – autres émissions indirectes", "Scope 3 – other indirect emissions", [
             ("GES-S3-ACHATS", "Cat. 1"), ("GES-S3-IMMO", "Cat. 2"), ("GES-S3-ENERGIE", "Cat. 3"), ("GES-S3-FRET-AMONT", "Cat. 4"),
             ("GES-S3-DECHETS", "Cat. 5"), ("GES-S3-DEPLACEMENTS", "Cat. 6"), ("GES-S3-DOMICILE", "Cat. 7"),
             ("GES-S3-FRET-AVAL", "Cat. 9"), ("GES-S3-UTILISATION", "Cat. 11"), ("GES-S3-FIN-VIE", "Cat. 12"),
             ("GES-S3-AUTRES", "Cat. 8, 10, 13-15"), ("GES-S3", "Scope 3")]),
         ("TOTAL", "Total et intensité", "Total and intensity", ["GES-TOTAL", "ECO-CA", "GES-INTENSITE", "GES-EVOL"]),
         ("FACTEURS", "Facteurs d'émission", "Emission factors", [
             "FE-GAZ", "FE-FIOUL", "FE-GAZOLE", "FE-ESSENCE", "FE-ELEC", "FE-CHALEUR", "FE-FROID"]),
     ],
     "regles": []},
    {"code": "SOCLE_SOCIAL", "date": "2026-11-12", "fichier": "socle_social.json", "couleur": "#6B4FA0",
     "thematique": ("Social", "Social"),  # rangement dans la bibliothèque (page Référentiels)
     "nom": ("Social (modèle)", "Social (template)"),
     "description": ("Effectifs, mouvements, formation, santé et sécurité, diversité et égalité.",
                     "Workforce, turnover, training, health and safety, diversity and equality."),
     "arbre": [
         ("EFFECTIFS", "Effectifs", "Workforce", ["SOC-EFFECTIF", "SOC-EFF-FEMMES", "SOC-PART-FEMMES", "SOC-EFF-CDI", "SOC-PART-CDI",
                                                   "SOC-ETP"]),
         ("MOUVEMENTS", "Mouvements", "Turnover", ["SOC-EMBAUCHES", "SOC-DEPARTS", "SOC-DEPARTS-VOL", "SOC-TAUX-DEPART"]),
         ("FORMATION", "Formation", "Training", ["SOC-HEURES-FORM", "SOC-SAL-FORMES", "SOC-FORM-PAR-SAL"]),
         ("SANTE_SECURITE", "Santé et sécurité", "Health and safety", ["SOC-HEURES-TRAV", "SOC-AT", "SOC-JOURS-PERDUS", "SOC-DECES",
                                                                       "SOC-TF", "SOC-TG"]),
         ("DIVERSITE", "Diversité et égalité", "Diversity and equality", ["SOC-HANDICAP", "SOC-PART-HANDICAP", "SOC-ECART-REMU",
                                                                         ("SOC-ACCORD-EGALITE", "", False)]),
     ],
     "regles": ["Effectif féminin ≤ effectif total", "Salariés en CDI ≤ effectif total", "Départs volontaires ≤ départs",
                "Salariés en situation de handicap ≤ effectif total"]},
    {"code": "SOCLE_ESRS", "date": "2026-11-12", "fichier": "socle_esrs.json", "couleur": "#1F5FAD",
     "thematique": ("Normes de reporting", "Reporting standards"),  # rangement dans la bibliothèque (page Référentiels)
     "nom": ("ESRS – indicateurs quantitatifs (simplifié)", "ESRS – quantitative metrics (simplified)"),
     "description": ("Sélection d'indicateurs chiffrés des normes ESRS (E1, E3, E5, S1, G1), rangés par exigence de publication, avec "
                     "les données qui servent à les calculer. Ne couvre ni les informations qualitatives ni l'analyse de double matérialité.",
                     "Selection of quantitative ESRS metrics (E1, E3, E5, S1, G1), grouped by disclosure requirement, with the data "
                     "used to calculate them. Qualitative information and the double materiality assessment are not covered."),
     "arbre": [
         ("E1", "E1 – Changement climatique", "E1 – Climate change", [
             ("E1_5", "E1-5 Consommation et mix énergétiques", "E1-5 Energy consumption and mix", [
                 ("NRJ-ELEC", "E1-5"), ("NRJ-ELEC-AUTO", "E1-5"), ("NRJ-ELEC-REN", "E1-5"), ("NRJ-GAZ", "E1-5"), ("NRJ-FIOUL", "E1-5"),
                 ("NRJ-CHALEUR", "E1-5"), ("NRJ-FROID", "E1-5"), ("CONV-FIOUL", "E1-5"), ("NRJ-TOTAL", "E1-5"), ("NRJ-PART-REN", "E1-5")]),
             ("E1_6", "E1-6 Émissions brutes de GES", "E1-6 Gross GHG emissions", [
                 ("GES-S1", "E1-6"), ("GES-S2-LB", "E1-6"), ("GES-S3", "E1-6"), ("GES-TOTAL", "E1-6"), ("GES-INTENSITE", "E1-6"),
                 ("E1_6_SCOPE3", "Scope 3 par catégorie", "Scope 3 by category", [
                     ("GES-S3-ACHATS", "E1-6"), ("GES-S3-IMMO", "E1-6"), ("GES-S3-ENERGIE", "E1-6"), ("GES-S3-FRET-AMONT", "E1-6"),
                     ("GES-S3-DECHETS", "E1-6"), ("GES-S3-DEPLACEMENTS", "E1-6"), ("GES-S3-DOMICILE", "E1-6"),
                     ("GES-S3-FRET-AVAL", "E1-6"), ("GES-S3-UTILISATION", "E1-6"), ("GES-S3-FIN-VIE", "E1-6"), ("GES-S3-AUTRES", "E1-6")]),
                 ("E1_6_DONNEES", "Données de calcul", "Calculation data", [
                     "GES-GAZOLE", "GES-ESSENCE", "GES-FUGITIVES", "GES-S1-FIXE", "GES-S1-MOBILE", "ECO-CA", "FE-GAZ", "FE-FIOUL",
                     "FE-GAZOLE", "FE-ESSENCE", "FE-ELEC", "FE-CHALEUR", "FE-FROID"]),
             ]),
         ]),
         ("E3", "E3 – Ressources aquatiques et marines", "E3 – Water and marine resources", [
             ("E3_4", "E3-4 Consommation d'eau", "E3-4 Water consumption", [("EAU-CONSO", "E3-4")])]),
         ("E5", "E5 – Utilisation des ressources et économie circulaire", "E5 – Resource use and circular economy", [
             ("E5_5", "E5-5 Flux de ressources sortants", "E5-5 Resource outflows", [
                 ("DEC-TOTAL", "E5-5"), ("DEC-DANGEREUX", "E5-5"), ("DEC-VALORISES", "E5-5"), ("DEC-PART-VALO", "E5-5")])]),
         ("S1", "S1 – Personnel de l'entreprise", "S1 – Own workforce", [
             ("S1_6", "S1-6 Caractéristiques des salariés", "S1-6 Characteristics of employees", [
                 ("SOC-EFFECTIF", "S1-6"), ("SOC-EFF-FEMMES", "S1-6"), ("SOC-EFF-CDI", "S1-6"), ("SOC-DEPARTS", "S1-6"),
                 ("SOC-TAUX-DEPART", "S1-6")]),
             ("S1_9", "S1-9 Indicateurs de diversité", "S1-9 Diversity metrics", [("SOC-PART-FEMMES", "S1-9")]),
             ("S1_12", "S1-12 Personnes handicapées", "S1-12 Persons with disabilities", [("SOC-HANDICAP", "S1-12"),
                                                                                           ("SOC-PART-HANDICAP", "S1-12")]),
             ("S1_13", "S1-13 Formation et développement des compétences", "S1-13 Training and skills development", [
                 ("SOC-HEURES-FORM", "S1-13"), ("SOC-FORM-PAR-SAL", "S1-13")]),
             ("S1_14", "S1-14 Santé et sécurité", "S1-14 Health and safety", [
                 ("SOC-HEURES-TRAV", "S1-14"), ("SOC-AT", "S1-14"), ("SOC-TF", "S1-14"), ("SOC-JOURS-PERDUS", "S1-14"),
                 ("SOC-DECES", "S1-14")]),
             ("S1_16", "S1-16 Rémunération", "S1-16 Remuneration", [("SOC-ECART-REMU", "S1-16")]),
         ]),
         ("G1", "G1 – Conduite des affaires", "G1 – Business conduct", [
             ("G1_4", "G1-4 Corruption", "G1-4 Corruption and bribery", [("GOV-CORRUPTION", "G1-4"), ("GOV-AMENDES", "G1-4")]),
             ("G1_6", "G1-6 Pratiques de paiement", "G1-6 Payment practices", [("GOV-DELAI-PAIEMENT", "G1-6")]),
         ]),
     ],
     "regles": ["Effectif féminin ≤ effectif total", "Salariés en CDI ≤ effectif total", "Salariés en situation de handicap ≤ effectif total",
                "Déchets dangereux ≤ déchets générés", "Déchets détournés ≤ déchets générés",
                "Électricité renouvelable achetée ≤ électricité achetée"]},
]
