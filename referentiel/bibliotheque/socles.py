"""Catalogue commun de la bibliothèque (choix C8 : le référentiel d'un client n'est pas distribué) : unités, types, KPI et
règles partagés par les modèles, et assemblage des modèles de ``definitions/`` (un fichier par modèle).

Source des paquets JSON de ce dossier : ``python manage.py bibliotheque`` les régénère, avec docs/library.md.
Un KPI commun à plusieurs modèles est défini une seule fois ici : il est identique dans chaque paquet, si bien qu'installer
plusieurs modèles le réutilise (une seule valeur saisie) au lieu de créer un conflit. Désormais, la
bibliothèque ne propose que la norme volontaire VS ; les quatre premiers socles (Énergie, Gaz à effet de serre, Social,
ESRS simplifié) sont dans ``socles_retires.py``, et leurs KPI restent dans ce catalogue (la VS en réutilise une partie).

Contenu proposé, à valider : codes, définitions, unités et formules. Les modèles ne disent pas à quel niveau de l'arbre
chaque KPI se saisit : l'outil le choisit à l'installation, d'après l'arbre de l'organisation (paramètre hérité au niveau le
plus haut, KPI saisi au plus bas, KPI calculé au niveau de ses sources) ; il se règle ensuite dans la fiche du KPI, ou en lot
dans le contenu du référentiel.
"""
import uuid

from .catalogue_anglais import anglais as _anglais
from .outils import S3_NA, ZERO, ZERO_EN, kpi  # noqa: F401 (kpi : nom historique, repris par les définitions)
from .outils import langue as _langue

VERSION = "1.0"
ESPACE = uuid.UUID("6f1c2a52-3d1e-4c35-9a52-0b6f0e7c5d10")  # identifiants stables des socles (uuid5 de leur code)

UNITES = [  # code (= symbole), symbole anglais, libellé (fr, en), nombre entier, décimales, famille
    ("kWh", "kWh", ("kilowattheure", "kilowatt-hour"), False, 0, "Énergie"),
    ("L", "L", ("litre", "litre"), False, 0, "Volume"),
    ("m³", "m³", ("mètre cube", "cubic metre"), False, 0, "Volume"),
    ("m²", "m²", ("mètre carré", "square metre"), False, 0, "Surface"),
    ("t", "t", ("tonne", "tonne"), False, 1, "Masse"),
    ("tCO2e", "tCO2e", ("tonne équivalent CO2", "tonne of CO2 equivalent"), False, 1, "Émissions"),
    ("kgCO2e/kWh", "kgCO2e/kWh", ("kilogramme équivalent CO2 par kWh", "kilogram of CO2e per kWh"), False, 3, "Facteur d'émission"),
    ("kgCO2e/L", "kgCO2e/L", ("kilogramme équivalent CO2 par litre", "kilogram of CO2e per litre"), False, 3, "Facteur d'émission"),
    ("kWh/L", "kWh/L", ("kilowattheure par litre", "kilowatt-hour per litre"), False, 2, "Conversion"),
    ("kWh/m²", "kWh/m²", ("kilowattheure par mètre carré", "kilowatt-hour per square metre"), False, 1, "Intensité"),
    ("tCO2e/M€", "tCO2e/M€", ("tonne équivalent CO2 par million d'euros", "tonne of CO2e per million euros"), False, 1, "Intensité"),
    ("M€", "M€", ("million d'euros", "million euros"), False, 1, "Monnaie"),
    ("€", "€", ("euro", "euro"), False, 0, "Monnaie"),
    ("salariés", "employees", ("salariés", "employees"), True, 0, "Effectif"),
    ("ETP", "FTE", ("équivalent temps plein", "full-time equivalent"), False, 1, "Effectif"),
    ("h", "h", ("heure", "hour"), False, 0, "Durée"),
    ("jours", "days", ("jours", "days"), True, 0, "Durée"),
    ("accidents", "accidents", ("accidents", "accidents"), True, 0, "Comptage"),
    ("personnes", "people", ("personnes", "people"), True, 0, "Comptage"),
    ("cas", "cases", ("cas", "cases"), True, 0, "Comptage"),
]
TYPES_SAISIE = [  # code, libellé (fr, en), étiquette (fr, en), couleur, comportement
    ("Saisi", ("Saisi", "Input"), ("Saisie", "Input"), "#5A6B85", "saisie"),
    ("Calculé", ("Calculé", "Calculated"), ("Calcul", "Calc."), "#2B4596", "calcul"),
    ("FE", ("Facteur d'émission", "Emission factor"), ("FE", "EF"), "#B04BC4", "herite"),
]
TYPES_REPONSE = [  # code, libellé (fr, en), format, valeurs : traduction anglaise (oui / non), {"fr": [...], "en": [...]} (liste)
    # ou colonnes [{code, libelle: {fr, en}, type: nombre / texte / liste, liste, unite}] (tableau, voir collecte/tableaux.py)
    ("Numérique", ("Numérique", "Number"), "nombre", []),
    ("Pourcentage", ("Pourcentage", "Percentage"), "pourcentage", []),
    ("OuiNon", ("Oui / non", "Yes / no"), "oui_non", ["Yes", "No"]),
    ("Texte", ("Texte rédigé", "Written text"), "texte", []),
]
CATEGORIES = [("description", ("Description", "Description")), ("a_inclure", ("À inclure", "Include")),
              ("a_exclure", ("À exclure", "Exclude")), ("source", ("Source des données", "Data source"))]
SOURCE_FE = "Base Empreinte de l'ADEME, DEFRA, AIE ou base nationale équivalente ; garder la même source d'une année sur l'autre."
SOURCE_S3 = "Bilan des émissions de gaz à effet de serre (outil de comptabilité carbone, prestataire)."
KPIS = dict([
    # ---------------------------------------------------------------- énergie
    kpi("NRJ-ELEC", "Électricité achetée consommée", "Purchased electricity consumed", "kWh",
        description="Électricité achetée (réseau ou contrat) et consommée sur le site pendant la période." + ZERO,
        inclure="Bureaux, entrepôts, magasins, bornes de recharge situées sur le site.",
        exclure="Électricité produite et consommée sur place (voir NRJ-ELEC-AUTO).",
        source="Factures ou espace client du fournisseur, relevés de compteurs."),
    kpi("NRJ-ELEC-AUTO", "Électricité renouvelable produite et autoconsommée", "Self-generated renewable electricity consumed", "kWh",
        description="Électricité produite sur le site (panneaux photovoltaïques, éolien…) et consommée sur place." + ZERO,
        source="Compteur de production, rapport de l'installateur."),
    kpi("NRJ-ELEC-REN", "Électricité achetée d'origine renouvelable", "Purchased renewable electricity", "kWh",
        description="Partie de l'électricité achetée couverte par une offre verte avec garanties d'origine ou par un contrat "
                    "d'achat direct (PPA)." + ZERO, source="Attestation du fournisseur (garanties d'origine)."),
    kpi("NRJ-GAZ", "Gaz naturel consommé", "Natural gas consumed", "kWh",
        description="Gaz naturel consommé sur le site (chauffage, process, restauration), en kWh PCS comme sur les factures." + ZERO,
        source="Factures du fournisseur, relevés de compteurs."),
    kpi("NRJ-FIOUL", "Fioul consommé", "Heating oil consumed", "L",
        description="Fioul domestique consommé pour le chauffage ou les groupes électrogènes, en litres." + ZERO,
        source="Bons de livraison, jaugeages des cuves."),
    # chaleur et vapeur : l'énergie finale de la VS compte la vapeur reçue (guide de la VS §24, scope 2
    # « heat, steam or cooling »), l'E1 aussi (§27(e), AR 18(g)) ; le froid a son propre KPI
    kpi("NRJ-CHALEUR", "Chaleur et vapeur achetées", "Purchased heat and steam", "kWh",
        description="Chaleur et vapeur achetées ou reçues, consommées par le site : réseau de chaleur urbain, vapeur d'un site "
                    "voisin, chaleur ou vapeur fatale reçue du procédé industriel d'un tiers." + ZERO,
        source="Factures du réseau de chaleur ou du fournisseur de vapeur."),
    kpi("NRJ-FROID", "Froid acheté (réseau de froid)", "Purchased cooling (district cooling)", "kWh",
        description="Froid livré par un réseau de froid urbain." + ZERO, source="Factures du réseau de froid."),
    kpi("CONV-FIOUL", "Contenu énergétique du fioul", "Energy content of heating oil", "kWh/L", "Aucune", "FE", decimales=2,
        description="Énergie contenue dans un litre de fioul, pour convertir les litres en kWh (environ 10 kWh/L).",
        source="Base Empreinte de l'ADEME ou fournisseur."),
    kpi("NRJ-TOTAL", "Consommation totale d'énergie", "Total energy consumption", "kWh", "Somme", "Calculé",
        formule="[NRJ-ELEC] + [NRJ-ELEC-AUTO] + [NRJ-GAZ] + [NRJ-FIOUL] * [CONV-FIOUL] + [NRJ-CHALEUR] + [NRJ-FROID]",
        description="Somme des énergies consommées sur le site, en kWh (le fioul est converti avec son contenu énergétique)."),
    kpi("NRJ-PART-REN", "Part d'électricité renouvelable", "Share of renewable electricity", "", "Formule", "Calculé",
        "Pourcentage", "([NRJ-ELEC-REN] + [NRJ-ELEC-AUTO]) / ([NRJ-ELEC] + [NRJ-ELEC-AUTO])", decimales=1,
        description="Électricité renouvelable (achetée avec garanties d'origine ou autoconsommée) rapportée à toute l'électricité consommée."),
    kpi("NRJ-SURFACE", "Surface des bâtiments", "Building floor area", "m²", temps="derniere",
        description="Surface de plancher occupée en fin de période.", source="Baux, plans, gestion immobilière."),
    kpi("NRJ-INTENSITE", "Intensité énergétique par m²", "Energy intensity per m²", "kWh/m²", "Formule", "Calculé",
        formule="[NRJ-TOTAL] / [NRJ-SURFACE]", description="Consommation totale d'énergie rapportée à la surface des bâtiments."),
    kpi("NRJ-EVOL", "Évolution de la consommation d'énergie", "Change in energy consumption", "", "Formule", "Calculé",
        "Pourcentage", "([NRJ-TOTAL] - [NRJ-TOTAL@N-1]) / [NRJ-TOTAL@N-1]", decimales=1,
        description="Variation de la consommation totale par rapport à la même période de l'exercice précédent."),
    kpi("NRJ-MANAGEMENT", "Système de management de l'énergie ou audit énergétique à jour",
        "Energy management system or up-to-date energy audit", "", "Décompte", reponse="OuiNon",
        description="L'entité est-elle certifiée ISO 50001 ou a-t-elle réalisé un audit énergétique de moins de quatre ans ?"),
    # ---------------------------------------------------------------- gaz à effet de serre
    kpi("GES-GAZOLE", "Gazole consommé par les véhicules", "Diesel used by vehicles", "L",
        description="Gazole des véhicules et engins détenus ou loués en longue durée par l'entité." + ZERO,
        source="Cartes carburant, factures."),
    kpi("GES-ESSENCE", "Essence consommée par les véhicules", "Petrol used by vehicles", "L",
        description="Essence des véhicules détenus ou loués en longue durée par l'entité." + ZERO, source="Cartes carburant, factures."),
    kpi("GES-FUGITIVES", "Émissions fugitives (fluides frigorigènes)", "Fugitive emissions (refrigerants)", "tCO2e", decimales=1,
        description="Recharges de fluides frigorigènes (climatisation, froid) multipliées par leur pouvoir de réchauffement global." + ZERO,
        source="Registre des interventions et bordereaux du frigoriste."),
    kpi("FE-GAZ", "Facteur d'émission du gaz naturel", "Natural gas emission factor", "kgCO2e/kWh", "Aucune", "FE", decimales=3,
        description="kgCO2e émis par kWh PCS de gaz naturel brûlé.", source=SOURCE_FE),
    kpi("FE-FIOUL", "Facteur d'émission du fioul", "Heating oil emission factor", "kgCO2e/L", "Aucune", "FE", decimales=3,
        description="kgCO2e émis par litre de fioul domestique brûlé.", source=SOURCE_FE),
    kpi("FE-GAZOLE", "Facteur d'émission du gazole", "Diesel emission factor", "kgCO2e/L", "Aucune", "FE", decimales=3,
        description="kgCO2e émis par litre de gazole.", source=SOURCE_FE),
    kpi("FE-ESSENCE", "Facteur d'émission de l'essence", "Petrol emission factor", "kgCO2e/L", "Aucune", "FE", decimales=3,
        description="kgCO2e émis par litre d'essence.", source=SOURCE_FE),
    kpi("FE-ELEC", "Facteur d'émission de l'électricité (réseau du pays)", "Grid electricity emission factor (location-based)",
        "kgCO2e/kWh", "Aucune", "FE", decimales=3,
        description="Facteur moyen du réseau électrique du pays de l'entité (méthode « location-based »).", source=SOURCE_FE,
        niveau="pays"),  # dépend du pays : une valeur par pays 
    kpi("FE-CHALEUR", "Facteur d'émission de la chaleur et de la vapeur achetées", "Purchased heat and steam emission factor",
        "kgCO2e/kWh", "Aucune", "FE", decimales=3,
        description="Facteur de la chaleur ou de la vapeur achetées par le site (réseau de chaleur, fournisseur de vapeur) ; si le site achète les deux, facteur moyen pondéré par les quantités.",
        source="Gestionnaire du réseau, arrêté national."),
    kpi("FE-FROID", "Facteur d'émission du froid acheté", "Purchased cooling emission factor", "kgCO2e/kWh", "Aucune", "FE",
        decimales=3, description="Facteur du réseau de froid qui alimente le site.", source="Gestionnaire du réseau, arrêté national."),
    kpi("GES-S1-FIXE", "Émissions de la combustion fixe", "Stationary combustion emissions", "tCO2e", "Somme", "Calculé",
        formule="([NRJ-GAZ] * [FE-GAZ] + [NRJ-FIOUL] * [FE-FIOUL]) / 1000", decimales=1,
        description="Gaz naturel et fioul brûlés sur le site, multipliés par leur facteur d'émission."),
    kpi("GES-S1-MOBILE", "Émissions de la combustion mobile", "Mobile combustion emissions", "tCO2e", "Somme", "Calculé",
        formule="([GES-GAZOLE] * [FE-GAZOLE] + [GES-ESSENCE] * [FE-ESSENCE]) / 1000", decimales=1,
        description="Carburants des véhicules de l'entité, multipliés par leur facteur d'émission."),
    kpi("GES-S1", "Scope 1 : combustion et émissions fugitives (sous-total)",
        "Scope 1: combustion and fugitive emissions (subtotal)", "tCO2e", "Somme", "Calculé",
        formule="[GES-S1-FIXE] + [GES-S1-MOBILE] + [GES-FUGITIVES]", decimales=1,
        description=("Sous-total calculé : combustion fixe et mobile, et émissions fugitives. Les autres émissions directes "
                     "(procédés, autres combustibles, agriculture) se saisissent à part et s'y ajoutent pour donner le scope 1 "
                     "brut.",
                     "Calculated subtotal: stationary and mobile combustion, and fugitive emissions. The other direct emissions "
                     "(processes, other fuels, agriculture) are entered separately and added to it to make gross scope 1.")),
    kpi("GES-S2-LB", "Émissions indirectes liées à l'énergie (scope 2, location-based)",
        "Energy indirect emissions (scope 2, location-based)", "tCO2e", "Somme", "Calculé",
        formule="([NRJ-ELEC] * [FE-ELEC] + [NRJ-CHALEUR] * [FE-CHALEUR] + [NRJ-FROID] * [FE-FROID]) / 1000", decimales=1,
        description="Électricité, chaleur, vapeur et froid achetés, multipliés par le facteur moyen de leur réseau."),
    # Scope 3 : les quinze catégories au niveau de l'entreprise, comme les cinq de la norme VS (VS §51 : catégories
    # significatives selon l'évaluation de l'entreprise, N/A pour une catégorie qui ne l'est pas) ; réglable dans la fiche
    kpi("GES-S3-ACHATS", "Scope 3 – biens et services achetés (cat. 1)", "Scope 3 – purchased goods and services (cat. 1)", "tCO2e",
        decimales=1, description="Émissions liées à la production des biens et services achetés." + S3_NA, source=SOURCE_S3, niveau="haut"),
    kpi("GES-S3-IMMO", "Scope 3 – biens immobilisés (cat. 2)", "Scope 3 – capital goods (cat. 2)", "tCO2e", decimales=1,
        description="Émissions liées à la fabrication des équipements, bâtiments et véhicules acquis." + S3_NA, source=SOURCE_S3, niveau="haut"),
    kpi("GES-S3-ENERGIE", "Scope 3 – énergie, amont (cat. 3)", "Scope 3 – fuel- and energy-related activities (cat. 3)", "tCO2e",
        decimales=1, description="Extraction, production et transport des énergies consommées, pertes en ligne." + S3_NA,
        source=SOURCE_S3, niveau="haut"),
    kpi("GES-S3-FRET-AMONT", "Scope 3 – transport et distribution amont (cat. 4)", "Scope 3 – upstream transportation and distribution (cat. 4)",
        "tCO2e", decimales=1, description="Transport des marchandises achetées jusqu'aux sites de l'entreprise." + S3_NA,
        source=SOURCE_S3, niveau="haut"),
    kpi("GES-S3-DECHETS", "Scope 3 – déchets générés (cat. 5)", "Scope 3 – waste generated in operations (cat. 5)", "tCO2e", decimales=1,
        description="Traitement des déchets produits par les sites." + S3_NA, source=SOURCE_S3, niveau="haut"),
    kpi("GES-S3-DEPLACEMENTS", "Scope 3 – déplacements professionnels (cat. 6)", "Scope 3 – business travel (cat. 6)", "tCO2e",
        decimales=1, description="Trains, avions, voitures de location et nuits d'hôtel des déplacements professionnels." + S3_NA,
        source=SOURCE_S3, niveau="haut"),
    kpi("GES-S3-DOMICILE", "Scope 3 – trajets domicile-travail (cat. 7)", "Scope 3 – employee commuting (cat. 7)", "tCO2e",
        decimales=1, description="Trajets des salariés entre leur domicile et leur lieu de travail." + S3_NA, source=SOURCE_S3, niveau="haut"),
    kpi("GES-S3-FRET-AVAL", "Scope 3 – transport et distribution aval (cat. 9)", "Scope 3 – downstream transportation and distribution (cat. 9)",
        "tCO2e", decimales=1, description="Transport des produits vendus jusqu'aux clients." + S3_NA, source=SOURCE_S3, niveau="haut"),
    kpi("GES-S3-UTILISATION", "Scope 3 – utilisation des produits vendus (cat. 11)", "Scope 3 – use of sold products (cat. 11)", "tCO2e",
        decimales=1, description="Énergie consommée par les produits vendus pendant leur durée de vie." + S3_NA, source=SOURCE_S3, niveau="haut"),
    kpi("GES-S3-FIN-VIE", "Scope 3 – fin de vie des produits vendus (cat. 12)",
        "Scope 3 – end-of-life treatment of sold products (cat. 12)", "tCO2e", decimales=1,
        description="Traitement des produits vendus et de leurs emballages en fin de vie." + S3_NA, source=SOURCE_S3, niveau="haut"),
    kpi("GES-S3-AUTRES", "Scope 3 – autres catégories (8, 10, 13, 14, 15)", "Scope 3 – other categories (8, 10, 13, 14, 15)", "tCO2e",
        decimales=1, description="Actifs loués, transformation des produits vendus, franchises, investissements." + ZERO,
        source=SOURCE_S3),
    kpi("GES-S3", "Autres émissions indirectes (scope 3)", "Other indirect emissions (scope 3)", "tCO2e", "Somme", "Calculé",
        formule="[GES-S3-ACHATS] + [GES-S3-IMMO] + [GES-S3-ENERGIE] + [GES-S3-FRET-AMONT] + [GES-S3-DECHETS] + [GES-S3-DEPLACEMENTS] "
                "+ [GES-S3-DOMICILE] + [GES-S3-FRET-AVAL] + [GES-S3-UTILISATION] + [GES-S3-FIN-VIE] + [GES-S3-AUTRES]",
        decimales=1, description="Somme des catégories du scope 3."),
    kpi("GES-TOTAL", "Émissions totales de GES (scopes 1, 2 et 3)", "Total GHG emissions (scopes 1, 2 and 3)", "tCO2e",
        "Somme", "Calculé", formule="[GES-S1] + [GES-S2-LB] + [GES-S3]", decimales=1, description="Scopes 1, 2 (location-based) et 3."),
    kpi("ECO-CA", "Chiffre d'affaires net", "Net revenue", "M€", decimales=1,
        description="Chiffre d'affaires net de la période, en millions d'euros.", source="Comptes consolidés, contrôle de gestion."),
    kpi("GES-INTENSITE", "Intensité carbone par million d'euros de chiffre d'affaires", "GHG intensity per net revenue", "tCO2e/M€", "Formule", "Calculé",
        formule="[GES-TOTAL] / [ECO-CA]", decimales=1,
        description="Émissions totales rapportées au chiffre d'affaires net."),
    kpi("GES-EVOL", "Évolution des émissions totales", "Change in total emissions", "", "Formule", "Calculé", "Pourcentage",
        "([GES-TOTAL] - [GES-TOTAL@N-1]) / [GES-TOTAL@N-1]", decimales=1,
        description="Variation des émissions totales par rapport à la même période de l'exercice précédent."),
    # ---------------------------------------------------------------- social
    kpi("SOC-EFFECTIF", "Effectif total en fin de période", "Total headcount at end of period", "salariés", temps="derniere",
        description="Salariés inscrits à l'effectif en fin de période, tous contrats (CDI, CDD, alternance), en nombre de personnes.",
        exclure="Intérimaires, stagiaires, prestataires.", source="Système d'information RH, paie."),
    kpi("SOC-EFF-FEMMES", "Effectif féminin en fin de période", "Female headcount at end of period", "salariés",
        temps="derniere", description="Femmes inscrites à l'effectif en fin de période.", source="Système d'information RH."),
    kpi("SOC-EFF-CDI", "Salariés en contrat permanent en fin de période", "Permanent employees at end of period", "salariés",
        temps="derniere", description="Salariés en contrat à durée indéterminée en fin de période.", source="Système d'information RH."),
    kpi("SOC-ETP", "Effectif moyen en équivalent temps plein", "Average full-time equivalent headcount", "ETP", temps="moyenne",
        description="Moyenne des effectifs mensuels, chaque salarié compté au prorata de son temps de travail.", source="Paie."),
    kpi("SOC-PART-FEMMES", "Part des femmes dans l'effectif", "Share of women in headcount", "", "Formule", "Calculé",
        "Pourcentage", "[SOC-EFF-FEMMES] / [SOC-EFFECTIF]", decimales=1, description="Effectif féminin rapporté à l'effectif total."),
    kpi("SOC-PART-CDI", "Part des salariés en contrat permanent", "Share of permanent employees", "", "Formule", "Calculé",
        "Pourcentage", "[SOC-EFF-CDI] / [SOC-EFFECTIF]", decimales=1, description="Salariés en CDI rapportés à l'effectif total."),
    kpi("SOC-EMBAUCHES", "Embauches", "New hires", "salariés",
        description="Entrées dans l'effectif pendant la période (CDI et CDD).", source="Système d'information RH."),
    kpi("SOC-DEPARTS", "Départs", "Leavers", "salariés",
        description="Sorties de l'effectif pendant la période, quel qu'en soit le motif (démission, licenciement, fin de contrat, "
                    "retraite…).", source="Système d'information RH."),
    kpi("SOC-DEPARTS-VOL", "Départs volontaires (démissions)", "Voluntary leavers (resignations)", "salariés",
        description="Démissions et ruptures à l'initiative du salarié pendant la période.", source="Système d'information RH."),
    kpi("SOC-TAUX-DEPART", "Taux de départ", "Employee turnover rate", "", "Formule", "Calculé", "Pourcentage",
        "[SOC-DEPARTS] / [SOC-EFFECTIF]", decimales=1, description="Départs de la période rapportés à l'effectif de fin de période."),
    kpi("SOC-HEURES-FORM", "Heures de formation", "Training hours", "h",
        description="Heures de formation suivies par les salariés pendant la période, toutes modalités (présentiel, à distance).",
        source="Plan de développement des compétences, outil de formation."),
    kpi("SOC-SAL-FORMES", "Salariés ayant suivi au moins une formation", "Employees trained at least once", "salariés",
        temps="aucune", description="Personnes formées au moins une fois pendant la période (chacune comptée une fois).",
        source="Outil de formation."),
    kpi("SOC-FORM-PAR-SAL", "Heures de formation par salarié", "Training hours per employee", "h", "Formule", "Calculé",
        formule="[SOC-HEURES-FORM] / [SOC-EFFECTIF]", decimales=1, description="Heures de formation rapportées à l'effectif total."),
    kpi("SOC-HEURES-TRAV", "Heures travaillées", "Hours worked", "h",
        description="Heures réellement travaillées par les salariés pendant la période.", source="Paie, gestion des temps."),
    kpi("SOC-AT", "Accidents du travail avec arrêt", "Lost-time work accidents", "accidents",
        description="Accidents du travail reconnus ayant entraîné au moins un jour d'arrêt.", exclure="Accidents de trajet.",
        source="Déclarations d'accidents du travail, service santé et sécurité."),
    kpi("SOC-JOURS-PERDUS", "Jours perdus pour accident du travail", "Days lost due to work accidents", "jours",
        description="Jours calendaires d'arrêt consécutifs aux accidents du travail.", source="Service santé et sécurité, paie."),
    kpi("SOC-DECES", "Décès liés au travail", "Work-related fatalities", "personnes",
        description=("Décès de salariés survenus pendant la période à la suite d'un accident du travail ou d'une maladie liée au "
                     "travail comptabilisables (somme des deux), sous réserve des restrictions légales. Les décès de "
                     "non-salariés ne sont pas comptés ici.",
                     "Deaths of employees during the period as a result of recordable work-related accidents or recordable "
                     "work-related ill health (sum of both), subject to legal restrictions. Deaths of non-employees are not "
                     "counted here."),
        source="Service santé et sécurité."),
    kpi("SOC-TF", "Taux de fréquence des accidents du travail", "Lost-time injury frequency rate", "", "Formule", "Calculé",
        formule="[SOC-AT] * 1000000 / [SOC-HEURES-TRAV]", decimales=2,
        description="Accidents du travail avec arrêt par million d'heures travaillées."),
    kpi("SOC-TG", "Taux de gravité des accidents du travail", "Accident severity rate", "", "Formule", "Calculé",
        formule="[SOC-JOURS-PERDUS] * 1000 / [SOC-HEURES-TRAV]", decimales=2, description="Jours perdus par millier d'heures travaillées."),
    kpi("SOC-HANDICAP", "Salariés en situation de handicap", "Employees with disabilities", "salariés", temps="derniere",
        description="Salariés ayant déclaré leur situation de handicap, en fin de période.", source="Système d'information RH."),
    kpi("SOC-PART-HANDICAP", "Part des salariés en situation de handicap", "Share of employees with disabilities", "",
        "Formule", "Calculé", "Pourcentage", "[SOC-HANDICAP] / [SOC-EFFECTIF]", decimales=1,
        description="Salariés en situation de handicap rapportés à l'effectif total."),
    kpi("SOC-ECART-REMU", "Écart de rémunération entre femmes et hommes", "Gender pay gap", "", "Aucune",
        reponse="Pourcentage", temps="derniere", decimales=1,
        description="(Rémunération horaire moyenne des hommes − celle des femmes) ÷ celle des hommes.", source="Paie."),
    kpi("SOC-ACCORD-EGALITE", "Accord ou plan d'action égalité professionnelle en vigueur",
        "Gender equality agreement or action plan in force", "", "Décompte", reponse="OuiNon",
        description="Un accord ou un plan d'action en faveur de l'égalité entre les femmes et les hommes s'applique-t-il dans l'entité ?"),
    # ---------------------------------------------------------------- environnement (ESRS E3, E5) et gouvernance (G1)
    kpi("EAU-CONSO", "Consommation d'eau", "Water consumption", "m³",
        description="Eau prélevée (réseau, forage, cours d'eau) moins l'eau rejetée ; à défaut, eau prélevée sur le réseau." + ZERO,
        source="Factures d'eau, relevés de compteurs."),
    kpi("DEC-TOTAL", "Déchets générés", "Total waste generated", "t", decimales=1,
        description="Déchets produits par le site pendant la période, toutes filières." + ZERO,
        source="Registre des déchets, bordereaux et bilans des prestataires."),
    kpi("DEC-DANGEREUX", "Déchets dangereux générés", "Hazardous waste generated", "t", decimales=1,
        description="Partie des déchets classée dangereuse (huiles, solvants, DEEE, batteries…)." + ZERO,
        source="Bordereaux de suivi des déchets dangereux."),
    kpi("DEC-VALORISES", "Déchets détournés de l'élimination", "Waste diverted from disposal", "t", decimales=1,
        description="Déchets réemployés, recyclés ou valorisés (hors incinération sans valorisation et mise en décharge)." + ZERO,
        source="Bilans des prestataires."),
    kpi("DEC-PART-VALO", "Part des déchets détournés de l'élimination", "Share of waste diverted from disposal", "", "Formule",
        "Calculé", "Pourcentage", "[DEC-VALORISES] / [DEC-TOTAL]", decimales=1,
        description="Déchets réemployés, recyclés ou valorisés rapportés aux déchets générés."),
    kpi("GOV-CORRUPTION", "Condamnations pour corruption", "Convictions for corruption or bribery", "cas",
        description="Condamnations définitives pour corruption active ou passive prononcées pendant la période.",
        source="Direction juridique, conformité."),
    kpi("GOV-AMENDES", "Amendes pour corruption", "Fines for corruption or bribery", "€",
        description=("Montant des sanctions pécuniaires obligatoires imposées par un tribunal ou une autorité administrative ou de "
                     "régulation pour violation des lois anticorruption, versées à un Trésor public et comptabilisées dans les "
                     "états financiers de la période (norme volontaire VS : B11 §43 et guide §141 ; ESRS G1-4 §12 et G1 AR 6, "
                     "même définition)." + ZERO,
                     "Amount of the mandatory monetary penalties imposed by a court or an administrative or regulatory authority "
                     "for violation of anti-corruption and anti-bribery laws, paid to a public treasury and recognised in the "
                     "financial statements of the period (Voluntary Standard VS: B11 §43 and guidance §141; ESRS G1-4 §12 and "
                     "G1 AR 6, same definition)." + ZERO_EN),
        source=("Comptabilité, direction juridique.", "Accounting, legal department.")),
    kpi("GOV-DELAI-PAIEMENT", "Délai moyen de paiement des fournisseurs", "Average supplier payment time", "jours", "Aucune",
        temps="derniere", description="Nombre moyen de jours entre la date de facture et le paiement des fournisseurs.",
        source="Comptabilité fournisseurs."),
])

# Textes du catalogue écrits en français seulement : chaque KPI reçoit ses textes dans les deux langues (français, anglais),
# comme ceux des modèles de definitions/ ; la traduction anglaise est dans catalogue_anglais.T.
for _d in KPIS.values():
    for _cat, _ in (("description", ""), ("a_inclure", ""), ("a_exclure", ""), ("source", "")):
        if isinstance(_d.get(_cat), str) and _d[_cat]:
            _d[_cat] = (_d[_cat], _anglais(_d[_cat]))

REGLES = {  # nom : (gauche, opérateur, droite, (description fr, en), nom en) ; niveau : celui du KPI de gauche
    "Électricité renouvelable achetée ≤ électricité achetée": (
        "[NRJ-ELEC-REN]", "<=", "[NRJ-ELEC]",
        ("L'électricité renouvelable achetée fait partie de l'électricité achetée.",
         "Purchased renewable electricity is part of purchased electricity."),
        "Renewable electricity purchased ≤ electricity purchased"),
    "Effectif féminin ≤ effectif total": (
        "[SOC-EFF-FEMMES]", "<=", "[SOC-EFFECTIF]",
        ("L'effectif féminin ne peut pas dépasser l'effectif total.", "The female headcount cannot exceed the total headcount."),
        "Female headcount ≤ total headcount"),
    "Salariés en CDI ≤ effectif total": (
        "[SOC-EFF-CDI]", "<=", "[SOC-EFFECTIF]",
        ("Les salariés en CDI font partie de l'effectif total.", "Employees on permanent contracts are part of the total headcount."),
        "Employees on permanent contracts ≤ total headcount"),
    "Départs volontaires ≤ départs": (
        "[SOC-DEPARTS-VOL]", "<=", "[SOC-DEPARTS]",
        ("Les départs volontaires font partie des départs.", "Voluntary leavers are part of the leavers."),
        "Voluntary leavers ≤ leavers"),
    "Salariés en situation de handicap ≤ effectif total": (
        "[SOC-HANDICAP]", "<=", "[SOC-EFFECTIF]",
        ("Les salariés en situation de handicap font partie de l'effectif total.",
         "Employees with disabilities are part of the total headcount."),
        "Employees with disabilities ≤ total headcount"),
    "Déchets dangereux ≤ déchets générés": (
        "[DEC-DANGEREUX]", "<=", "[DEC-TOTAL]",
        ("Les déchets dangereux font partie des déchets générés.", "Hazardous waste is part of the waste generated."),
        "Hazardous waste ≤ waste generated"),
    "Déchets détournés ≤ déchets générés": (
        "[DEC-VALORISES]", "<=", "[DEC-TOTAL]",
        ("Les déchets détournés de l'élimination font partie des déchets générés.",
         "Waste diverted from disposal is part of the waste generated."),
        "Waste diverted ≤ waste generated"),
}

# Modèles de la bibliothèque : ceux de definitions/ (un fichier par modèle), ajoutés par _fusionner. Les quatre premiers
# socles (Énergie, Gaz à effet de serre, Social, ESRS simplifié) sont sortis de l'offre : socles_retires.py.
SOCLES = []


# ---------------------------------------------------------------- modèles d'un fichier chacun (definitions/)
def _fusionner():
    """Ajoute les modèles de ``definitions/`` (un fichier par modèle) : leurs unités, types de réponse, KPI et règles
    rejoignent le catalogue commun. Une même clé définie deux fois différemment est notée dans CONFLITS (refus de
    générer, voir controle.py), jamais écrasée : un KPI partagé reste défini une seule fois."""
    from . import definitions as D
    from .socles_retires import SOCLES_RETIRES

    conflits = []

    def ajouter(cible, cle, valeur, quoi, module):
        if cle in cible and cible[cle] != valeur:
            conflits.append(f"{module} : {quoi} « {cle} » déjà défini autrement (le réutiliser tel quel ou choisir un autre code)")
        else:
            cible[cle] = valeur
    unites = {u[0]: u for u in UNITES}
    reponses = {t[0]: t for t in TYPES_REPONSE}
    modeles = D.charger()
    for m in modeles:
        nom = m.__name__.rsplit(".", 1)[-1]
        for u in getattr(m, "UNITES", []):
            ajouter(unites, u[0], tuple(u), "unité", nom)
        for t in getattr(m, "TYPES_REPONSE", []):
            ajouter(reponses, t[0], tuple(t), "type de réponse", nom)
        for code, d in getattr(m, "KPIS", {}).items():
            ajouter(KPIS, code, d, "KPI", nom)
        for cle, r in getattr(m, "REGLES", {}).items():
            ajouter(REGLES, cle, r, "règle", nom)
        socle = dict(m.SOCLE, module=nom, source=getattr(m, "SOURCE", {}))
        if any(s["code"] == socle["code"] or s["fichier"] == socle["fichier"] for s in SOCLES + SOCLES_RETIRES):
            # un code retiré reste réservé : même code = même identifiant, les installations y verraient une mise à jour
            conflits.append(f"{nom} : code ou fichier de modèle déjà pris ({socle['code']}, {socle['fichier']})")
        else:
            SOCLES.append(socle)
    UNITES[:] = list(unites.values())
    TYPES_REPONSE[:] = list(reponses.values())
    return conflits


from .sources import documents as documents_sources  # noqa: E402

CONFLITS = _fusionner()
FORMATS = {t[0]: t[2] for t in TYPES_REPONSE}  # code du type de réponse -> format (nombre, pourcentage, oui_non, liste, texte)


def _textes(fr, en):
    return {k: v for k, v in (("fr", fr), ("en", en)) if v}


def est_theme(noeud):
    return isinstance(noeud, tuple) and len(noeud) == 4 and isinstance(noeud[3], list)


def _valeurs_reponse(v):
    """Valeurs d'un type de réponse dans le paquet : traduction anglaise du oui / non (liste) ou liste de choix par langue."""
    if isinstance(v, dict):
        return {lg: list(x) for lg, x in v.items() if x}
    return {"en": list(v)} if v else {}


def paquet(socle):
    """Paquet d'un socle (même forme que l'export d'un référentiel)."""
    from collecte.paquets import Paquet

    themes, elements = [], []

    def parcourir(noeuds, parent):
        ordre_themes, ordre_kpi = 0, 0
        for n in noeuds:
            if est_theme(n):
                ordre_themes += 1
                code, fr, en, contenu = n
                themes.append({"code": code, "parent": parent, "nom": _textes(fr, en), "ordre": ordre_themes})
                parcourir(contenu, code)
            else:
                ordre_kpi += 1
                t = (n,) if isinstance(n, str) else tuple(n)
                code, obligatoire = t[0], t[2] if len(t) > 2 else True  # t[1] : référence dans la norme (documentation)
                elements.append((code, {"theme": parent, "ordre": ordre_kpi, "libelle": {},
                                        "obligatoire": obligatoire}))
    parcourir(socle["arbre"], "")
    codes = [c for c, _ in elements]
    assert len(codes) == len(set(codes)), f"{socle['code']} : KPI placé deux fois"
    kpis = []
    for code, element in elements:
        d = KPIS[code]
        descriptions = {}
        for lg in ("fr", "en"):
            textes = {cat: _langue(d[cat], lg) for cat, _ in CATEGORIES if _langue(d.get(cat), lg)}
            if textes:
                descriptions[lg] = textes
        kpis.append({"code": code, "libelle": _textes(d["fr"], d["en"]), "type_saisie": d["type"], "type_reponse": d["reponse"],
                     "unite": d["unite"], "decimales": d["decimales"] if d["decimales"] is not None else (
                         1 if d["reponse"] == "Pourcentage" else next((u[4] for u in UNITES if u[0] == d["unite"]), 0)),
                     "methode_agregation": d["agregation"],
                     "agregation_temps": d["temps"] or temps_par_defaut(d), "formule": d["formule"], "preuve_obligatoire": False,
                     "confidentialite": d.get("confidentialite") or "Non sensible", "actif": True, "descriptions": descriptions,
                     "champs": {}, "element": element, **({"niveau_conseille": d["niveau"]} if d.get("niveau") else {})})
    utilises = {k["unite"] for k in kpis}
    regles = []
    for nom in socle["regles"]:
        gauche, op, droite, description = REGLES[nom][:4]
        # « nom » et « description » : le texte français (langue de référence du paquet, lu tel quel par les versions
        # d'avant) ; les autres langues dans « traductions » {langue: {champ: texte}}, comme les textes traduits des objets de
        # l'outil. L'installation enregistre le texte de sa langue de référence (regles_textes.texte_regle) et chaque écran
        # l'affiche dans la langue de la personne qui lit (regles_textes.traduire).
        anglais = {k: v for k, v in (("nom", REGLES[nom][4] if len(REGLES[nom]) > 4 else ""),
                                     ("description", _langue(description, "en"))) if v}
        regles.append({"nom": nom, "description": _langue(description, "fr"), "gauche": gauche, "operateur": op, "droite": droite,
                       "tolerance": "0", "bloquante": False, "actif": True, **({"traductions": {"en": anglais}} if anglais else {})})
    p = Paquet(
        referentiel={"code": socle["code"], "identifiant": str(uuid.uuid5(ESPACE, socle["code"])), "nom": _textes(*socle["nom"]),
                     "description": _textes(*socle["description"]), "thematique": _textes(*socle["thematique"]),
                     "couleur": socle["couleur"], "frequence": "annee", "mois_debut": 1,
                     "comparaison": "N-1", "version": socle.get("version", VERSION), "date_version": socle.get("date", ""),
                     "origine": "fourni"},
        langue_reference="fr", langues=[{"code": "fr", "libelle": "Français"}, {"code": "en", "libelle": "English"}],
        niveaux=[],  # aucun niveau : rattachement choisi par l'outil à l'installation
        unites=[{"code": c, "symbole": _textes(c, en), "libelle": _textes(*lib), "entier": entier, "decimales": dec, "famille": fam}
                for c, en, lib, entier, dec, fam in UNITES if c in utilises],
        types_saisie=[{"code": c, "libelle": _textes(*lib), "abrege": _textes(*ab), "couleur": coul, "comportement": comp}
                      for c, lib, ab, coul, comp in TYPES_SAISIE if c in {k["type_saisie"] for k in kpis}],
        types_reponse=[{"code": c, "libelle": _textes(*lib), "format": fmt, **(
                           {"valeurs": {}, "colonnes": v} if fmt == "tableau" else {"valeurs": _valeurs_reponse(v)})}
                       for c, lib, fmt, v in TYPES_REPONSE if c in reponses_utilisees(kpis)],
        categories=[{"code": c, "libelle": _textes(*lib), "ordre": i, "affichee": True, "obligatoire": False}
                    for i, (c, lib) in enumerate(CATEGORIES, start=1)],
        champs=[], themes=themes, kpis=kpis, regles=regles, exporte_le="", exporte_de="Bibliothèque de l'outil",
        documents=documents_sources(socle.get("source")),
    )
    if socle.get("traductions"):  # famille de modèles traduite dans les cinq autres langues (traductions/<famille>.<langue>.json)
        from .traductions import ajouter

        ajouter(p, socle["traductions"])
    return p


def reponses_utilisees(kpis):
    """Types de réponse des KPI d'un paquet, et les listes auxquelles renvoient les colonnes de leurs tableaux."""
    codes = {k["type_reponse"] for k in kpis}
    for c, _, fmt, v in TYPES_REPONSE:
        if c in codes and fmt == "tableau":
            codes |= {col.get("liste") for col in v if col.get("liste")}
    return codes


def temps_par_defaut(d):
    """Agrégation dans le temps par défaut : comme KPI.agregation_temps_par_defaut (texte rédigé : saisi à chaque fréquence)."""
    fmt = FORMATS.get(d["reponse"], "nombre")
    if fmt in ("texte", "tableau"):
        return "aucune"
    if fmt in ("oui_non", "liste") or d["type"] == "FE":
        return "derniere"
    return "moyenne" if fmt == "pourcentage" else "somme"
