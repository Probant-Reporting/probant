"""Norme volontaire VS (ex-VSME) – module de base (B1 à B11).

Source : règlement délégué (UE) 2026/1560 (norme volontaire de publication d'informations en matière de durabilité, qui
remplace la recommandation VSME 2025/1710) et modèle numérique 2.0.0 de l'EFRAG (classeur Excel, licence MIT), dont les
cellules de saisie ont servi d'inventaire (fichier de couverture). Chaque KPI est relié à sa cellule du classeur dans
referentiel/bibliotheque/formats/vs_efrag.py : l'export « Classeur officiel de l'EFRAG » le remplit une fois la collecte
terminée.

Les informations de l'entreprise (politiques, textes, identifiant) se saisissent au niveau le plus haut (niveau="haut") ;
les données mesurées (énergie, eau, déchets, effectifs, accidents) au niveau du site, et remontent par l'agrégation.
La liste des sites (B1) et leur situation vis-à-vis des zones sensibles (B5) viennent des KPI saisis par chaque site.
"""
from referentiel.bibliotheque import outils as O
from referentiel.bibliotheque.outils import ZERO, ZERO_EN, kpi

from ._vs_listes import DECHETS, INFOS_INCHANGEES, OMISSIONS, PAYS, POLLUANTS

# Documents de la norme (rubrique « Source documents » de la fiche du modèle) : titre, éditeur, version et dates tels que
# les documents eux-mêmes les donnent (un test de l'atelier les compare à son registre des références). Une date exacte non
# écrite dans le document : l'année seule.
SOURCE = [
    {"titre": "Commission Delegated Regulation (EU) 2026/1560 (Voluntary Standard VS)",
     "editeur": "European Commission", "version": "OJ L, 21 September 2026", "date": "2026-07-03",
     "url": "http://data.europa.eu/eli/reg_del/2026/1560/oj", "consulte_le": "2026-11-13",
     "licence": "EU law: reuse allowed with acknowledgement of the source (Commission Decision 2011/833/EU)"},
    {"titre": "Voluntary Standard: standard for voluntary use (EFRAG Knowledge Hub, interactive text)",
     "editeur": "EFRAG", "version": "Official Journal publication of 21 September 2026", "date": "2026-09-21",
     "url": "https://knowledgehub.efrag.org/interactive/voluntary-standard/standard-for-voluntary-use",
     "consulte_le": "2026-11-18", "licence": "(c) EFRAG; the standard is paraphrased here, never reproduced"},
    {"titre": "Voluntary Standard: non-mandatory EFRAG guidance (EFRAG Knowledge Hub, interactive text)",
     "editeur": "EFRAG", "version": "2026 EFRAG guidance", "date": "2026",
     "url": "https://knowledgehub.efrag.org/eng/interactive/voluntary-standard-non-mandatory-efrag-guidance/voluntary-standard-non-mandatory-efrag-guidance/2026-efrag-guidance",
     "consulte_le": "2026-11-18", "licence": "(c) EFRAG; the guidance is paraphrased here, never reproduced"},
    {"titre": "EFRAG VS Digital Template (workbook)",
     "editeur": "EFRAG", "version": "2.0.0, taxonomy 2026-10-16", "date": "2026-11-04",
     "url": "https://xbrl.efrag.org/downloads/vsme/", "consulte_le": "2026-11-13",
     "licence": "MIT, (c) 2025 EFRAG"},
    {"titre": "VS Digital Template and XBRL Taxonomy: Explanatory Note",
     "editeur": "EFRAG", "version": "4 November 2026", "date": "2026-11-04",
     "url": "https://xbrl.efrag.org/downloads/vsme/", "consulte_le": "2026-11-18",
     "licence": "(c) EFRAG; read for reference, not redistributed"},
]

UNITES = [  # code, symbole anglais, libellé (fr, en), nombre entier, décimales, famille
    ("MWh", "MWh", ("mégawattheure", "megawatt-hour"), False, 1, "Énergie"),
    ("€/h", "€/h", ("euro par heure", "euro per hour"), False, 2, "Monnaie"),
    ("année", "year", ("année", "year"), True, 0, "Durée"),
]

TYPES_REPONSE = [  # listes de choix : valeurs anglaises = valeurs exactes du classeur de l'EFRAG
    ("VS-IDENTIFIANT", ("Type d'identifiant de l'entreprise", "Entity identifier scheme"), "liste",
     {"fr": ["LEI", "DUNS", "EU ID", "PermID"], "en": ["LEI", "DUNS", "EU ID", "PermID"]}),
    ("VS-PERIMETRE", ("Base de présentation du rapport", "Basis for reporting"), "liste",
     {"fr": ["Rapport établi sur une base individuelle", "Rapport établi sur une base consolidée"],
      "en": ["Sustainability report prepared on an individual basis", "Sustainability report prepared on a consolidated basis"]}),
    ("VS-FORME-JURIDIQUE", ("Forme juridique", "Legal form"), "liste",
     {"fr": ["Société à responsabilité limitée de droit privé", "Entreprise individuelle", "Société de personnes", "Coopérative",
             "Autre (préciser la forme juridique)"],
      "en": ["private limited liability undertaking", "sole proprietorship", "partnership", "cooperative",
             "other (please specify the legal form in the row below)"]}),
    ("VS-PAYS", ("Pays", "Country"), "liste", {"fr": PAYS, "en": PAYS}),
    ("VS-POLLUANT", ("Polluant", "Pollutant"), "liste", {"fr": POLLUANTS, "en": POLLUANTS}),
    ("VS-DECHET", ("Code de déchet", "Waste code"), "liste", {"fr": DECHETS, "en": DECHETS}),
    ("VS-UNITE-MATIERE", ("Unité de matière", "Unit of material"), "liste",
     {"fr": ["kilogrammes (kg)", "tonnes (t)", "mètres cubes (m³)"], "en": ["kilograms (kg)", "metric tonnes (t)", "cubic meters (m3)"]}),
    ("VS-INFO-INCHANGEE", ("Rubrique de la norme", "Disclosure of the standard"), "liste",
     {"fr": [t[1] for t in INFOS_INCHANGEES], "en": [t[0] for t in INFOS_INCHANGEES]}),
    ("VS-OMISSION", ("Rubrique omise", "Omitted disclosure"), "liste", {"fr": [t[2] for t in OMISSIONS], "en": [t[1] for t in OMISSIONS]}),
    # tableaux (une ligne par élément ; collecte/tableaux.py)
    ("VS-TAB-FILIALES", ("Liste des filiales", "List of subsidiaries"), "tableau", [
        {"code": "nom", "libelle": {"fr": "Nom", "en": "Name"}, "type": "texte"},
        {"code": "adresse", "libelle": {"fr": "Adresse du siège", "en": "Registered address"}, "type": "texte"}]),
    ("VS-TAB-POLLUANTS", ("Rejets par polluant", "Emissions per pollutant"), "tableau", [
        {"code": "polluant", "libelle": {"fr": "Polluant", "en": "Pollutant"}, "type": "liste", "liste": "VS-POLLUANT"},
        {"code": "air", "libelle": {"fr": "Rejets dans l'air", "en": "Emissions to air"}, "type": "nombre", "unite": "kg"},
        {"code": "eau", "libelle": {"fr": "Rejets dans l'eau", "en": "Emissions to water"}, "type": "nombre", "unite": "kg"},
        {"code": "sol", "libelle": {"fr": "Rejets dans le sol", "en": "Emissions to soil"}, "type": "nombre", "unite": "kg"}]),
    ("VS-TAB-POLLUANTS-AUTRES", ("Rejets d'autres polluants", "Emissions of other pollutants"), "tableau", [
        {"code": "nom", "libelle": {"fr": "Polluant", "en": "Pollutant"}, "type": "texte"},
        {"code": "air", "libelle": {"fr": "Rejets dans l'air", "en": "Emissions to air"}, "type": "nombre", "unite": "kg"},
        {"code": "eau", "libelle": {"fr": "Rejets dans l'eau", "en": "Emissions to water"}, "type": "nombre", "unite": "kg"},
        {"code": "sol", "libelle": {"fr": "Rejets dans le sol", "en": "Emissions to soil"}, "type": "nombre", "unite": "kg"}]),
    ("VS-TAB-DECHETS", ("Déchets par code", "Waste by code"), "tableau", [
        {"code": "code", "libelle": {"fr": "Code de déchet", "en": "Waste code"}, "type": "liste", "liste": "VS-DECHET"},
        {"code": "masse", "libelle": {"fr": "Déchets générés", "en": "Waste generated"}, "type": "nombre", "unite": "t"},
        {"code": "recycle", "libelle": {"fr": "Dont envoyés au recyclage", "en": "Of which sent to recycling"}, "type": "nombre", "unite": "t"},
        {"code": "reemploi", "libelle": {"fr": "Dont préparés pour le réemploi", "en": "Of which prepared for reuse"}, "type": "nombre", "unite": "t"}]),
    ("VS-TAB-MATIERES", ("Flux de matières", "Material flows"), "tableau", [
        {"code": "matiere", "libelle": {"fr": "Matière", "en": "Material"}, "type": "texte"},
        {"code": "quantite", "libelle": {"fr": "Quantité utilisée", "en": "Quantity used"}, "type": "nombre"},
        {"code": "unite", "libelle": {"fr": "Unité", "en": "Unit"}, "type": "liste", "liste": "VS-UNITE-MATIERE"}]),
    ("VS-TAB-INFOS-INCHANGEES", ("Informations inchangées", "Unchanged disclosures"), "tableau", [
        {"code": "rubrique", "libelle": {"fr": "Rubrique inchangée", "en": "Unchanged disclosure"}, "type": "liste", "liste": "VS-INFO-INCHANGEE"}]),
    ("VS-TAB-OMISSIONS", ("Informations omises", "Omitted disclosures"), "tableau", [
        {"code": "rubrique", "libelle": {"fr": "Rubrique omise", "en": "Omitted disclosure"}, "type": "liste", "liste": "VS-OMISSION"}]),
    ("VS-ZONE-BIODIVERSITE", ("Situation vis-à-vis d'une zone sensible", "Position relative to a sensitive area"), "liste",
     {"fr": ["Dans une zone sensible pour la biodiversité", "À proximité d'une zone sensible pour la biodiversité",
             "Ni dans ni à proximité d'une zone sensible"],
      "en": ["Located in a biodiversity sensitive area", "Located near a biodiversity sensitive area",
             "Neither in nor near a biodiversity sensitive area"]}),
]

HAUT = "haut"
ZERO_FR_EN = (ZERO, ZERO_EN)


PETITE = (" Facultatif pour une entreprise de 10 salariés au plus : elle peut répondre N/A.",
          " Voluntary for a company with 10 employees or less: it can answer N/A.")
S3_NA = (O.S3_NA, O.S3_NA_EN)  # catégorie du scope 3 non significative : N/A (outils.S3_NA)
# Phrases propres à une norme : jamais dans la description d'un KPI que d'autres modèles placent aussi (la dispense des
# entreprises de 10 salariés au plus est dite dans la description du modèle).


def _d(fr, en, zero=False, petite=False):
    """Description (fr, en), avec la phrase « Saisir 0 s'il n'y en a pas » pour un KPI additionné, et celle des
    informations facultatives pour les entreprises de 10 salariés au plus (« [Voluntary for undertakings with 10
    employees or less] » dans la norme)."""
    return (fr + (ZERO if zero else "") + (PETITE[0] if petite else ""), en + (ZERO_EN if zero else "") + (PETITE[1] if petite else ""))


# Écart de rémunération : chaque norme son calcul (la VS, l'ESRS S1 et la transparence des rémunérations ont chacune leurs
# KPI) ; rémunérations horaires « Restreint », comme dans la transparence des rémunérations.
METHODE_ECART_VS = (
    " Méthode de la norme VS : l'écart se calcule dans le classeur de l'EFRAG à partir des deux rémunérations horaires "
    "(B10 §42(b)) ; l'ESRS S1 et la transparence des rémunérations ont leurs propres KPI et leur propre calcul. Donnée "
    "restreinte.",
    " Method of the Voluntary Standard VS: the gap is calculated in EFRAG's workbook from the two hourly pay figures "
    "(B10 §42(b)); ESRS S1 and pay transparency have their own KPIs and their own calculation. Restricted data.")

KPIS = dict([
    # ------------------------------------------------------------------ B1 – base de préparation, informations générales
    kpi("GEN-IDENT-TYPE", "Type d'identifiant de l'entreprise", "Entity identifier scheme", "", "Décompte", reponse="VS-IDENTIFIANT",
        niveau=HAUT, description=("Référentiel de l'identifiant unique de l'entreprise ; le LEI est recommandé par l'EFRAG.",
                                  "Scheme of the company's unique identifier; EFRAG recommends the LEI."),
        source=("Registre du LEI (GLEIF), D&B, registre du commerce.", "LEI register (GLEIF), D&B, business register.")),
    kpi("GEN-IDENT", "Identifiant de l'entreprise", "Entity identifier", "", "Aucune", reponse="Texte", niveau=HAUT,
        description=("Identifiant unique de l'entreprise dans le référentiel choisi (par exemple les 20 caractères du LEI). "
                     "Obligatoire pour convertir le rapport en XBRL.",
                     "Unique identifier of the company in the chosen scheme (for example the 20 characters of the LEI). "
                     "Required to convert the report to XBRL.")),
    kpi("GEN-INTRO", "Introduction et autres informations propres à l'entreprise", "Introduction and entity-specific information", "",
        "Aucune", reponse="Texte", niveau=HAUT,
        description=("Texte d'introduction du rapport, facultatif.", "Optional introduction text of the report.")),
    kpi("GEN-CONFORMITE", "Déclaration explicite de conformité", "Explicit statement of compliance", "", "Aucune", reponse="Texte",
        niveau=HAUT, description=("Phrase par laquelle l'entreprise déclare que le rapport est établi conformément à la norme "
                                  "volontaire, avec le module retenu.",
                                  "Sentence in which the company states that the report complies with the Voluntary Standard, "
                                  "with the module chosen.")),
    kpi("GEN-PERIMETRE", "Base de présentation du rapport", "Basis for reporting", "", "Décompte", reponse="VS-PERIMETRE", niveau=HAUT,
        description=("Rapport établi pour l'entreprise seule (base individuelle) ou pour le groupe (base consolidée).",
                     "Report prepared for the company alone (individual basis) or for the group (consolidated basis).")),
    kpi("GEN-FORME-JURIDIQUE", "Forme juridique", "Legal form", "", "Décompte", reponse="VS-FORME-JURIDIQUE", niveau=HAUT,
        description=("Forme juridique de l'entreprise déclarante.", "Legal form of the reporting company.")),
    kpi("GEN-FORME-AUTRE", "Forme juridique (si « autre »)", "Legal form (if “other”)", "", "Aucune", reponse="Texte", niveau=HAUT,
        description=("À remplir seulement si la forme juridique est « Autre ».", "Only if the legal form is “Other”.")),
    kpi("GEN-NACE", "Codes NACE de l'activité", "NACE codes of the activity", "", "Aucune", reponse="Texte", niveau=HAUT,
        description=("Code(s) NACE de l'activité, un par ligne, sous la forme 47.91 (le code seul suffit).",
                     "NACE code(s) of the activity, one per line, written as 47.91 (the code alone is enough)."),
        source=("Extrait du registre du commerce (code APE en France).", "Business register extract.")),
    kpi("ECO-TOTAL-BILAN", "Total du bilan", "Balance sheet total", "€", niveau=HAUT,
        description=("Total des actifs au bilan à la date de clôture, en euros.", "Total assets on the balance sheet at closing date, in euros."),
        source=("Comptes annuels.", "Annual accounts.")),
    kpi("GEN-PAYS-PRINCIPAL", "Pays des activités principales", "Country of primary operations", "", "Décompte", reponse="VS-PAYS",
        niveau=HAUT, description=("Pays où l'entreprise exerce ses activités principales et où se trouvent ses actifs importants.",
                                  "Country where the company has its primary operations and significant assets.")),
    kpi("GEN-CERTIF", "Certification ou label de durabilité obtenu", "Sustainability certification or label obtained", "",
        "Décompte", reponse="OuiNon", niveau=HAUT,
        description=("L'entreprise a-t-elle obtenu une ou plusieurs certifications ou labels liés à la durabilité ?",
                     "Has the company obtained one or more sustainability-related certifications or labels?")),
    kpi("GEN-CERTIF-DESC", "Description des certifications ou labels", "Description of certifications or labels", "", "Aucune",
        reponse="Texte", niveau=HAUT,
        description=("Brève description de chaque certification ou label, avec son organisme émetteur, sa date et sa note s'il y "
                     "en a une.", "Short description of each certification or label, with its issuer, its date and its rating if any.")),
    kpi("GEN-SITE-ADRESSE", "Adresse du site", "Address of the site", "", "Aucune", reponse="Texte",
        description=("Numéro et rue du site ; séparer le numéro de rue et le complément par « / » (pas de virgule).",
                     "Street number and street of the site; separate the street number and any addition with “/” (no comma).")),
    kpi("GEN-SITE-CP", "Code postal du site", "Postal code of the site", "", "Aucune", reponse="Texte",
        description=("Code postal du site.", "Postal code of the site.")),
    kpi("GEN-SITE-VILLE", "Ville du site", "City of the site", "", "Aucune", reponse="Texte",
        description=("Ville du site.", "City of the site.")),
    kpi("GEN-SITE-PAYS", "Pays du site", "Country of the site", "", "Décompte", reponse="VS-PAYS",
        description=("Pays du site ; sert aussi à la répartition des salariés par pays (B8).",
                     "Country of the site; also used for the breakdown of employees by country (B8).")),
    kpi("GEN-AUTRES", "Autres informations générales propres à l'entreprise", "Other general entity-specific information", "",
        "Aucune", reponse="Texte", niveau=HAUT, description=("Facultatif.", "Optional.")),
    kpi("GEN-SITE-GPS", "Coordonnées GPS du site", "GPS coordinates of the site", "", "Aucune", reponse="Texte",
        description=("Latitude et longitude en degrés décimaux, 5 décimales, séparées par une virgule (ex. 48.85661, 2.35222), "
                     "comme les donne un service de cartes. La norme demande la géolocalisation de chaque site.",
                     "Latitude and longitude in decimal degrees, 5 decimals, separated by a comma (e.g. 48.85661, 2.35222), as a "
                     "map service gives them. The standard asks for the geolocation of each site.")),
    kpi("GEN-FILIALES", "Liste des filiales", "List of subsidiaries", "", "Aucune", reponse="VS-TAB-FILIALES", niveau=HAUT,
        description=("Pour un rapport sur une base consolidée : une ligne par filiale, avec l'adresse de son siège.",
                     "For a report on a consolidated basis: one row per subsidiary, with its registered address."),
        source=("Organigramme juridique, comptes consolidés.", "Legal structure chart, consolidated accounts.")),
    kpi("GEN-INFOS-INCHANGEES", "Informations inchangées depuis le rapport précédent", "Disclosures unchanged since the previous report",
        "", "Aucune", reponse="VS-TAB-INFOS-INCHANGEES", niveau=HAUT,
        description=("Facultatif : les rubriques qui n'ont pas changé depuis le rapport précédent (une par ligne) ; le lien vers ce "
                     "rapport se donne ci-dessous.", "Optional: the disclosures that have not changed since the previous report "
                                                        "(one per row); the link to that report is given below."),
        source=("Rapport précédent.", "Previous report.")),
    kpi("GEN-RAPPORT-LIEN", "Lien vers le rapport précédent", "Link to the previous report", "", "Aucune", reponse="Texte", niveau=HAUT,
        description=("Adresse web du rapport précédent qui contient les informations inchangées.",
                     "Web address of the previous report that contains the unchanged disclosures.")),
    kpi("GEN-OMISSIONS", "Informations omises car classifiées ou sensibles", "Disclosures omitted as classified or sensitive", "",
        "Aucune", reponse="VS-TAB-OMISSIONS", niveau=HAUT,
        description=("Seulement si l'entreprise a omis une information parce qu'elle est classifiée ou sensible : une ligne par "
                     "rubrique omise. Sinon, laisser vide.",
                     "Only if the company has omitted information because it is classified or sensitive: one row per omitted "
                     "disclosure. Otherwise, leave empty."),
        source=("Direction générale, direction juridique.", "Management, legal department.")),
    kpi("GEN-COOP-PARTICIPATION", "Coopérative : participation à la gouvernance", "Cooperative: participation in governance", "",
        "Aucune", reponse="Texte", niveau=HAUT,
        description=("Pour une coopérative (guide facultatif de l'EFRAG) : participation effective des travailleurs, des usagers ou "
                     "d'autres parties à la gouvernance.", "For a cooperative (optional EFRAG guidance): effective participation of "
                                                         "workers, users or other parties in governance.")),
    kpi("GEN-COOP-INVEST", "Coopérative : investissements dans l'économie sociale", "Cooperative: investment in the social economy", "€",
        niveau=HAUT, description=("Investissements dans le capital ou les actifs d'entités de l'économie sociale (facultatif).",
                                  "Investment in the capital or assets of social economy entities (optional)."),
        source=("Comptabilité.", "Accounting.")),
    kpi("GEN-COOP-LIMITES", "Coopérative : limites à la distribution des bénéfices", "Cooperative: limits to profit distribution", "",
        "Aucune", reponse="Texte", niveau=HAUT,
        description=("Limites à la distribution des bénéfices liées au caractère mutualiste ou d'intérêt général (facultatif).",
                     "Limits to the distribution of profits linked to the mutual or general-interest nature (optional).")),
    # ------------------------------------------------------------------ B2 – pratiques, politiques, initiatives futures
    kpi("GOV-B2-PRATIQUES", "Pratiques, politiques ou initiatives pour la transition durable", "Practices, policies or initiatives for the sustainable transition",
        "", "Décompte", reponse="OuiNon", niveau=HAUT,
        description=("L'entreprise a-t-elle mis en place des pratiques, des politiques ou des initiatives futures pour la transition vers "
                     "une économie plus durable ? Si oui, cocher ci-dessous les enjeux concernés.",
                     "Has the company put in place practices, policies or future initiatives for the transition towards a more "
                     "sustainable economy? If yes, tick below the issues addressed.")),
] + [
    kpi(f"GOV-B2-{c}", f"Pratiques sur l'enjeu : {fr}", f"Practices on the issue: {en}", "", "Décompte", reponse="OuiNon", niveau=HAUT,
        description=(f"Une pratique, une politique ou une initiative de l'entreprise porte-t-elle sur l'enjeu « {fr} » ?",
                     f"Does a practice, policy or initiative of the company address the issue “{en}”?"))
    for c, fr, en in (("CLIMAT", "changement climatique", "climate change"), ("POLLUTION", "pollution", "pollution"),
                      ("EAU", "ressources hydriques et marines", "water and marine resources"),
                      ("BIODIV", "biodiversité et écosystèmes", "biodiversity and ecosystems"),
                      ("CIRCULAIRE", "économie circulaire et ressources", "circular economy and resource use"),
                      ("PERSONNEL", "personnel de l'entreprise", "own workforce"),
                      ("CHAINE", "travailleurs de la chaîne de valeur", "workers in the value chain"),
                      ("COMMUNAUTES", "communautés affectées", "affected communities"),
                      ("CONSO", "consommateurs et utilisateurs finaux", "consumers and end-users"),
                      ("CONDUITE", "conduite des affaires", "business conduct"))
] + [
    kpi("GOV-B2-PUBLIC", "Pratique ou politique accessible au public", "Practice or policy publicly available", "", "Décompte",
        reponse="OuiNon", niveau=HAUT,
        description=("Au moins une de ces pratiques, politiques ou initiatives est-elle accessible au public ?",
                     "Is at least one of these practices, policies or initiatives publicly available?")),
    kpi("GOV-B2-CIBLE", "Cible liée à une politique", "Target related to a policy", "", "Décompte", reponse="OuiNon", niveau=HAUT,
        description=("L'entreprise a-t-elle fixé une cible liée à l'une de ces politiques ?",
                     "Has the company set a target related to one of these policies?")),
    # ------------------------------------------------------------------ B3 – énergie et gaz à effet de serre
    kpi("NRJ-COMB-AUTRES", "Autres combustibles fossiles", "Other fossil fuels", "MWh",
        description=_d("Combustibles fossiles qui ne sont ni le gaz naturel, ni le fioul, ni les carburants des véhicules (GPL, "
                       "propane, charbon, gaz de procédé), en MWh selon le pouvoir calorifique inférieur.",
                       "Fossil fuels other than natural gas, heating oil and vehicle fuels (LPG, propane, coal, process gas), in "
                       "MWh on a net calorific value basis.", True),
        source=("Factures, bons de livraison.", "Invoices, delivery notes.")),
    kpi("NRJ-COMB-REN", "Combustibles renouvelables", "Renewable fuels", "MWh",
        description=_d("Bois, granulés, biogaz, biocarburants et autres combustibles issus de la biomasse brûlés sur le site, en "
                       "MWh selon le pouvoir calorifique inférieur.",
                       "Wood, pellets, biogas, biofuels and other biomass fuels burned on the site, in MWh on a net calorific value "
                       "basis.", True),
        source=("Factures, bons de livraison.", "Invoices, delivery notes.")),
    kpi("CONV-GAZ-PCI", "Rapport PCI / PCS du gaz naturel", "Net / gross calorific value ratio of natural gas", "", "Aucune", "FE",
        decimales=3,
        description=("Le gaz se facture en kWh PCS (pouvoir calorifique supérieur) ; la norme compte l'énergie en PCI (pouvoir "
                     "calorifique inférieur). Ce rapport convertit l'un en l'autre (environ 0,901 pour le gaz naturel).",
                     "Gas is billed in kWh of gross calorific value; the standard counts energy on a net calorific value basis. "
                     "This ratio converts one into the other (about 0.901 for natural gas)."),
        source=("Base Empreinte de l'ADEME.", "ADEME Base Empreinte.")),
    kpi("CONV-GAZOLE", "Contenu énergétique du gazole", "Energy content of diesel", "kWh/L", "Aucune", "FE", decimales=2,
        description=("Énergie contenue dans un litre de gazole, pour convertir les litres en kWh (environ 10 kWh/L).",
                     "Energy contained in one litre of diesel, to convert litres into kWh (about 10 kWh/L)."),
        source=("Base Empreinte de l'ADEME ou fournisseur.", "ADEME Base Empreinte or supplier.")),
    kpi("CONV-ESSENCE", "Contenu énergétique de l'essence", "Energy content of petrol", "kWh/L", "Aucune", "FE", decimales=2,
        description=("Énergie contenue dans un litre d'essence, pour convertir les litres en kWh (environ 9 kWh/L).",
                     "Energy contained in one litre of petrol, to convert litres into kWh (about 9 kWh/L)."),
        source=("Base Empreinte de l'ADEME ou fournisseur.", "ADEME Base Empreinte or supplier.")),
    kpi("NRJ-COMBUSTIBLES", "Énergie des combustibles", "Energy from fuels", "MWh", "Somme", "Calculé",
        formule="([NRJ-GAZ] * [CONV-GAZ-PCI] + [NRJ-FIOUL] * [CONV-FIOUL] + [GES-GAZOLE] * [CONV-GAZOLE] + [GES-ESSENCE] * [CONV-ESSENCE]) "
                "/ 1000 + [NRJ-COMB-AUTRES]",
        description=("Combustibles fossiles : gaz naturel (converti en PCI), fioul, carburants des véhicules et autres combustibles "
                     "fossiles, en MWh.",
                     "Fossil fuels: natural gas (converted to net calorific value), heating oil, vehicle fuels and other fossil "
                     "fuels, in MWh.")),
    kpi("NRJ-TOTAL-MWH", "Consommation totale d'énergie (MWh)", "Total energy consumption (MWh)", "MWh", "Somme", "Calculé",
        formule="([NRJ-ELEC] + [NRJ-ELEC-AUTO] + [NRJ-CHALEUR] + [NRJ-FROID]) / 1000 + [NRJ-COMBUSTIBLES] + [NRJ-COMB-REN]",
        description=_d("Électricité achetée et autoproduite, chaleur, vapeur et froid achetés, combustibles fossiles et renouvelables "
                       "(véhicules compris), en MWh. L'électricité produite sur place avec un combustible déjà compté ne s'ajoute pas.",
                       "Purchased and self-generated electricity, purchased heat, steam and cooling, fossil and renewable fuels (vehicles "
                       "included), in MWh. Electricity generated on site from a fuel already counted is not added.")),
    kpi("GES-S1-AUTRES", "Autres émissions directes (scope 1)", "Other direct emissions (scope 1)", "tCO2e", decimales=1,
        description=_d("Émissions directes que le calcul du scope 1 ne couvre pas : procédés industriels, autres combustibles "
                       "(GPL, charbon, biomasse pour le CH4 et le N2O), agriculture. Elles s'ajoutent au sous-total de la "
                       "combustion et des émissions fugitives pour donner le scope 1 brut.",
                       "Direct emissions not covered by the scope 1 calculation: industrial processes, other fuels (LPG, coal, "
                       "biomass for CH4 and N2O), agriculture. They are added to the subtotal of combustion and fugitive emissions to make "
                       "gross scope 1.", True),
        source=("Bilan des émissions de gaz à effet de serre.", "Greenhouse gas emissions inventory.")),
    kpi("GES-S2-MB", "Émissions indirectes liées à l'énergie (scope 2, méthode marché)", "Energy indirect emissions (scope 2, market-based)",
        "tCO2e", decimales=1, niveau=HAUT,
        description=_d("Émissions du scope 2 calculées avec les facteurs d'émission des contrats d'énergie : ceux de "
                       "l'électricité (garanties d'origine, contrats d'achat direct) et aussi ceux de la chaleur, de la vapeur "
                       "et du froid achetés, donnés par les fournisseurs ; pour l'énergie achetée sans attribut contractuel, le "
                       "facteur du mix résiduel.",
                       "Scope 2 emissions calculated with the emission factors of the energy contracts: those of electricity "
                       "(guarantees of origin, power purchase agreements) and also those of the purchased heat, steam and "
                       "cooling given by the suppliers; for purchased energy without a contractual instrument, the residual mix "
                       "factor.", True),
        source=("Bilan des émissions de gaz à effet de serre.", "Greenhouse gas emissions inventory.")),
] + [
    kpi(code, fr, en, "tCO2e", decimales=1, niveau=HAUT,
        description=(f"Émissions de la catégorie {n} du scope 3." + S3_NA[0], f"Emissions of scope 3 category {n}." + S3_NA[1]),
        source=("Bilan des émissions de gaz à effet de serre (outil de comptabilité carbone, prestataire).",
                "Greenhouse gas emissions inventory (carbon accounting tool, service provider)."))
    for code, n, fr, en in (("GES-S3-ACTIFS-AMONT", 8, "Scope 3 – actifs loués en amont (cat. 8)", "Scope 3 – upstream leased assets (cat. 8)"),
                            ("GES-S3-TRANSFO", 10, "Scope 3 – transformation des produits vendus (cat. 10)", "Scope 3 – processing of sold products (cat. 10)"),
                            ("GES-S3-ACTIFS-AVAL", 13, "Scope 3 – actifs loués en aval (cat. 13)", "Scope 3 – downstream leased assets (cat. 13)"),
                            ("GES-S3-FRANCHISES", 14, "Scope 3 – franchises (cat. 14)", "Scope 3 – franchises (cat. 14)"),
                            ("GES-S3-INVEST", 15, "Scope 3 – investissements (cat. 15)", "Scope 3 – investments (cat. 15)"))
] + [
    # ------------------------------------------------------------------ B4 – pollution
    kpi("POL-DECLARATION", "Déclaration des rejets de polluants exigée", "Reporting of pollutant emissions required", "", "Décompte",
        reponse="OuiNon", niveau=HAUT,
        description=("L'entreprise doit-elle déjà déclarer ses rejets de polluants dans l'air, l'eau ou le sol aux autorités "
                     "(droit de l'Union ou droit national), ou le fait-elle dans un système de management environnemental ?",
                     "Is the company already required to report its pollutant emissions to air, water or soil to the authorities "
                     "(EU or national law), or does it do so in an environmental management system?")),
    kpi("POL-PUBLIC", "Rejets de polluants déjà publiés", "Pollutant emissions already public", "", "Décompte", reponse="OuiNon",
        niveau=HAUT, description=("Ces informations sont-elles déjà accessibles au public ?", "Is this information already publicly available?")),
    kpi("POL-URL", "Lien vers la publication des rejets de polluants", "Link to the published pollutant emissions", "", "Aucune",
        reponse="Texte", niveau=HAUT,
        description=("Adresse web (URL) où ces informations sont publiées.", "Web address (URL) where this information is published.")),
    kpi("POL-REJETS", "Rejets par polluant", "Emissions per pollutant", "", "Aucune", reponse="VS-TAB-POLLUANTS",
        description=("Si l'entreprise doit déjà les déclarer (ou le fait dans un système de management environnemental) : une ligne "
                     "par polluant, avec ses rejets dans l'air, l'eau et le sol en kg sur la période.",
                     "If the company must already report them (or does so in an environmental management system): one row per "
                     "pollutant, with its emissions to air, water and soil in kg over the period."),
        source=("Déclaration annuelle des émissions (GEREP en France), registre E-PRTR.", "Annual emissions report, E-PRTR register.")),
    kpi("POL-REJETS-AUTRES", "Rejets d'autres polluants", "Emissions of other pollutants", "", "Aucune", reponse="VS-TAB-POLLUANTS-AUTRES",
        description=("Polluants absents de la liste européenne : une ligne par polluant, avec son nom et ses rejets en kg.",
                     "Pollutants that are not in the European list: one row per pollutant, with its name and emissions in kg."),
        source=("Déclaration annuelle des émissions.", "Annual emissions report.")),
        # ------------------------------------------------------------------ B5 – biodiversité
    kpi("BIO-SITES", "Sites dans ou près de zones sensibles pour la biodiversité", "Sites in or near biodiversity sensitive areas", "",
        "Décompte", reponse="OuiNon", niveau=HAUT,
        description=("L'entreprise a-t-elle des sites situés dans ou à proximité de zones sensibles pour la biodiversité (Natura 2000, "
                     "sites du patrimoine mondial, zones clés pour la biodiversité) ? Si oui, chaque site concerné l'indique.",
                     "Does the company have sites in or near biodiversity sensitive areas (Natura 2000, World Heritage sites, Key "
                     "Biodiversity Areas)? If yes, each site concerned says so.")),
    kpi("BIO-SITE-ZONE", "Situation du site vis-à-vis d'une zone sensible", "Position of the site relative to a sensitive area", "",
        "Décompte", reponse="VS-ZONE-BIODIVERSITE",
        description=("Le site est-il dans une zone sensible pour la biodiversité, à proximité, ou ni l'un ni l'autre ?",
                     "Is the site in a biodiversity sensitive area, near one, or neither?")),
    kpi("BIO-SITE-ZONE-NOM", "Nom de la zone sensible proche du site", "Name of the sensitive area near the site", "", "Aucune",
        reponse="Texte", description=("Nom de la zone sensible pour la biodiversité concernée.", "Name of the biodiversity sensitive area concerned.")),
    # ------------------------------------------------------------------ B6 – eau
    kpi("EAU-PRELEVEMENT", "Eau prélevée", "Water withdrawn", "m³",
        description=_d("Eau prélevée sur le site pendant la période (réseau, forage, cours d'eau).",
                       "Water withdrawn by the site during the period (mains, borehole, river).", True),
        source=("Factures d'eau, relevés de compteurs.", "Water bills, meter readings.")),
    kpi("EAU-REJET-PROCESS", "Eau rejetée par les procédés de production", "Water discharged from production processes", "m³",
        description=_d("Seulement pour un site dont les procédés de production consomment beaucoup d'eau (chaudières, séchage, "
                       "lavage, refroidissement, irrigation) : eau rejetée par ces procédés. 0 : pas de tels procédés.",
                       "Only for a site whose production processes use a lot of water (boilers, drying, washing, cooling, "
                       "irrigation): water discharged by these processes. 0: no such processes.", True, True),
        source=("Relevés de rejets, autorisation de rejet.", "Discharge readings, discharge permit.")),
    kpi("EAU-STRESS", "Eau consommée sur des sites en zone de stress hydrique", "Water consumed at sites in water-stress areas", "m³",
        description=_d("Eau consommée par le site s'il est situé dans une zone de stress hydrique (par exemple un stress hydrique "
                       "de base « élevé » ou plus dans l'outil Aqueduct du WRI), en mètres cubes : eau prélevée moins eau "
                       "rejetée par les procédés de production, comme la consommation d'eau de la norme VS (B6 §37). Les ESRS "
                       "ont leur propre KPI, qui déduit tous les rejets (E3 AR 4).",
                       "Water consumed by the site if it is in an area with water stress (for example a baseline water stress of "
                       "‘High’ or more in the WRI Aqueduct tool), in cubic metres: water withdrawn minus water discharged from "
                       "production processes, like the water consumption of the Voluntary Standard VS (B6 §37). The ESRS have "
                       "their own KPI, which deducts all discharges (E3 AR 4).", True),
        source=("Factures d'eau, outil Aqueduct.", "Water bills, Aqueduct tool.")),
    # ------------------------------------------------------------------ B7 – ressources, économie circulaire, déchets
    kpi("ECO-CIRCULAIRE", "Principes d'économie circulaire appliqués", "Circular economy principles applied", "", "Décompte",
        reponse="OuiNon", niveau=HAUT,
        description=("L'entreprise applique-t-elle des principes d'économie circulaire (réemploi, réparation, recyclage, "
                     "écoconception) ?" + PETITE[0],
                     "Does the company apply circular economy principles (reuse, repair, recycling, eco-design)?" + PETITE[1])),
    kpi("ECO-CIRCULAIRE-DESC", "Application des principes d'économie circulaire", "How circular economy principles are applied", "",
        "Aucune", reponse="Texte", niveau=HAUT,
        description=("Décrire comment l'entreprise applique ces principes.", "Describe how the company applies these principles.")),
    kpi("DEC-RECYCLES", "Déchets redirigés vers le recyclage", "Waste diverted to recycling", "t",
        description=_d("Déchets du site envoyés au recyclage, hors valorisation énergétique et remblayage.",
                       "Waste of the site sent to recycling, excluding energy recovery and backfilling.", True),
        source=("Bilans des prestataires.", "Service provider reports.")),
    kpi("DEC-REEMPLOI", "Déchets redirigés vers la préparation en vue du réemploi", "Waste diverted to preparation for reuse", "t",
        description=_d("Déchets du site préparés en vue du réemploi (contrôle, nettoyage, réparation).",
                       "Waste of the site prepared for reuse (checking, cleaning, repair).", True),
        source=("Bilans des prestataires.", "Service provider reports.")),
    kpi("DEC-PAR-CODE", "Déchets par code", "Waste by code", "", "Aucune", reponse="VS-TAB-DECHETS",
        description=("Facultatif, en plus des totaux : une ligne par code de déchet de la liste européenne, avec la masse générée et "
                     "ce qui a été envoyé au recyclage ou préparé pour le réemploi, en tonnes.",
                     "Optional, in addition to the totals: one row per waste code of the European list, with the mass generated "
                     "and what was sent to recycling or prepared for reuse, in tonnes."),
        source=("Registre des déchets, bordereaux de suivi.", "Waste register, waste transfer notes.")),
    kpi("ECO-MATIERES", "Flux de matières utilisées", "Material flows used", "", "Aucune", reponse="VS-TAB-MATIERES", niveau=HAUT,
        description=("Pour un secteur aux flux de matières importants (industrie, construction, emballage) : une ligne par matière "
                     "clé, avec la quantité utilisée sur l'année et son unité." + PETITE[0],
                     "For a sector with significant material flows (manufacturing, construction, packaging): one row per key "
                     "material, with the quantity used over the year and its unit." + PETITE[1]),
        source=("Achats, nomenclatures de production.", "Purchasing, bills of materials.")),
        # ------------------------------------------------------------------ B8 – effectifs
    kpi("SOC-EFF-HOMMES", "Effectif masculin en fin de période", "Male headcount at end of period", "salariés", temps="derniere",
        description=("Hommes inscrits à l'effectif en fin de période.", "Men on the payroll at the end of the period."),
        source=("Système d'information RH.", "HR information system.")),
    kpi("SOC-EFF-GENRE-AUTRE", "Effectif d'un autre genre en fin de période", "Headcount of other gender at end of period", "salariés",
        temps="derniere", description=("Salariés ayant déclaré un autre genre, en fin de période.",
                                       "Employees who declared another gender, at the end of the period."),
        source=("Système d'information RH.", "HR information system.")),
    kpi("SOC-EFF-GENRE-NC", "Effectif au genre non communiqué en fin de période", "Headcount with gender not reported at end of period",
        "salariés", temps="derniere", description=("Salariés dont le genre n'est pas communiqué, en fin de période.",
                                                   "Employees whose gender is not reported, at the end of the period."),
        source=("Système d'information RH.", "HR information system.")),
    # ------------------------------------------------------------------ B9 – santé et sécurité
    kpi("SOC-ACCIDENTS-ENREG", "Accidents du travail comptabilisables", "Recordable work-related accidents", "accidents",
        description=("Accidents liés au travail survenus à des salariés pendant la période et ayant entraîné un décès ou plus de "
                     "3 jours d'absence. Les accidents des non-salariés (intérimaires, indépendants) ne sont pas comptés ici.",
                     "Work-related accidents of employees during the period that resulted in death or more than 3 days of absence. "
                     "Accidents of non-employees (agency workers, self-employed people) are not counted here."),
        source=("Registre des accidents, déclarations d'accident.", "Accident register, accident reports.")),
    # ------------------------------------------------------------------ B10 – rémunération, négociation collective, formation
    kpi("SOC-SALAIRE-MINIMUM", "Rémunération au moins égale au salaire minimal", "Pay at or above the minimum wage", "", "Décompte",
        reponse="OuiNon", niveau=HAUT,
        description=("Tous les salariés perçoivent-ils une rémunération au moins égale au salaire minimal applicable (loi ou "
                     "convention collective) ?", "Do all employees receive pay at or above the applicable minimum wage (law or "
                                                 "collective agreement)?")),
    kpi("SOC-ECART-OBLIGATION", "Écart de rémunération déjà déclaré par obligation", "Pay gap already reported by obligation", "",
        "Décompte", reponse="OuiNon", niveau=HAUT,
        description=("L'entreprise doit-elle déjà déclarer l'écart de rémunération entre femmes et hommes (droit de l'Union ou "
                     "national) ? Si oui, elle donne les rémunérations horaires ci-dessous (le classeur de l'EFRAG calcule l'écart) ; "
                     "si non, elle répond N/A aux deux rémunérations.",
                     "Is the company already required to report the gender pay gap (EU or national law)? If yes, it gives the "
                     "hourly pay below (EFRAG's workbook calculates the gap); if not, it answers N/A to both.")),
    kpi("SOC-REMU-H-HOMMES", "Rémunération horaire brute moyenne des hommes", "Average gross hourly pay of male employees", "€/h",
        "Aucune", temps="derniere", niveau=HAUT, confidentialite="Restreint",
        description=("Rémunération brute annuelle des hommes (tous éléments de salaire compris) divisée par leurs heures travaillées."
                     + METHODE_ECART_VS[0],
                     "Annual gross pay of men (all pay elements included) divided by their hours worked." + METHODE_ECART_VS[1]),
        source=("Paie.", "Payroll.")),
    kpi("SOC-REMU-H-FEMMES", "Rémunération horaire brute moyenne des femmes", "Average gross hourly pay of female employees", "€/h",
        "Aucune", temps="derniere", niveau=HAUT, confidentialite="Restreint",
        description=("Rémunération brute annuelle des femmes (tous éléments de salaire compris) divisée par leurs heures travaillées."
                     + METHODE_ECART_VS[0],
                     "Annual gross pay of women (all pay elements included) divided by their hours worked." + METHODE_ECART_VS[1]),
        source=("Paie.", "Payroll.")),
    kpi("SOC-SAL-CONVENTION", "Salariés couverts par une convention collective", "Employees covered by collective bargaining agreements",
        "salariés", temps="derniere",
        description=("Salariés couverts par une convention ou un accord collectif, en fin de période (en effectif).",
                     "Employees covered by a collective agreement, at the end of the period (headcount)."),
        source=("Système d'information RH.", "HR information system.")),
    # ------------------------------------------------------------------ autres informations
    kpi("ENV-AUTRES", "Autres informations environnementales propres à l'entreprise", "Other environmental entity-specific information",
        "", "Aucune", reponse="Texte", niveau=HAUT, description=("Facultatif.", "Optional.")),
    kpi("SOC-AUTRES", "Autres informations sociales propres à l'entreprise", "Other social entity-specific information", "", "Aucune",
        reponse="Texte", niveau=HAUT, description=("Facultatif.", "Optional.")),
    kpi("GOV-AUTRES", "Autres informations de gouvernance propres à l'entreprise", "Other governance entity-specific information", "",
        "Aucune", reponse="Texte", niveau=HAUT, description=("Facultatif.", "Optional.")),
])

REGLES = {  # nom fr : (gauche, opérateur, droite, (description fr, en), nom en)
    "Effectif masculin ≤ effectif total": ("[SOC-EFF-HOMMES]", "<=", "[SOC-EFFECTIF]", (
        "L'effectif masculin ne peut pas dépasser l'effectif total.", "Male headcount cannot exceed total headcount."),
        "Male headcount ≤ total headcount"),
    "Salariés couverts par une convention ≤ effectif total": ("[SOC-SAL-CONVENTION]", "<=", "[SOC-EFFECTIF]", (
        "Les salariés couverts par une convention collective font partie de l'effectif total.",
        "Employees covered by collective agreements are part of the total headcount."), "Employees covered by agreements ≤ total headcount"),
    "Déchets recyclés ≤ déchets générés": ("[DEC-RECYCLES]", "<=", "[DEC-TOTAL]", (
        "Les déchets recyclés font partie des déchets générés.", "Recycled waste is part of the waste generated."),
        "Recycled waste ≤ waste generated"),
    "Déchets préparés pour le réemploi ≤ déchets générés": ("[DEC-REEMPLOI]", "<=", "[DEC-TOTAL]", (
        "Les déchets préparés pour le réemploi font partie des déchets générés.", "Waste prepared for reuse is part of the waste generated."),
        "Waste prepared for reuse ≤ waste generated"),
    "Eau rejetée par les procédés ≤ eau prélevée": ("[EAU-REJET-PROCESS]", "<=", "[EAU-PRELEVEMENT]", (
        "L'eau rejetée par les procédés ne peut pas dépasser l'eau prélevée.", "Water discharged by processes cannot exceed water withdrawn."),
        "Water discharged by processes ≤ water withdrawn"),
}

# Arbre : (code du thème, nom fr, nom en, contenu) ; KPI = code, (code, référence) ou (code, référence, obligatoire).
SOCLE = {
    "code": "VS_BASE",
    "fichier": "vs_base.json",
    "couleur": "#0B7A75",
    "version": "1.2",
    "date": "2026-11-19",
    "ordre": 10,
    "thematique": ("Normes de reporting", "Reporting standards"),
    "nom": ("Norme volontaire VS (ex-VSME) – module de base", "Voluntary Standard VS (formerly VSME) – Basic Module"),
    "description": (
        "Informations B1 à B11 de la norme volontaire européenne (règlement délégué 2026/1560, qui remplace la VSME), pour les "
        "entreprises de 1 000 salariés au plus ; s'exporte dans le classeur officiel de l'EFRAG (modèle numérique 2.0.0). "
        "B3, B6 et B7 sont facultatifs pour les entreprises de 10 salariés au plus (réponse N/A).",
        "Disclosures B1 to B11 of the European Voluntary Standard (Delegated Regulation 2026/1560, which replaces the VSME), for "
        "companies with up to 1,000 employees; exports to EFRAG's official workbook (Digital Template 2.0.0). B3, B6 and B7 are "
        "voluntary for companies with 10 employees or less (answer N/A)."),
    "arbre": [
        ("B1", "B1 – Base de préparation", "B1 – Basis for preparation", [
            ("GEN-IDENT-TYPE", "XBRL"), ("GEN-IDENT", "XBRL"), ("GEN-INTRO", "Introduction", False),
            ("GEN-CONFORMITE", "B1 · 27(a)"), ("GEN-PERIMETRE", "B1 · 27(c)"), ("GEN-FORME-JURIDIQUE", "B1 · 27(e)(i)"),
            ("GEN-FORME-AUTRE", "B1 · 27(e)(i)", False), ("GEN-NACE", "B1 · 27(e)(ii)"), ("ECO-TOTAL-BILAN", "B1 · 27(e)(iii)"),
            ("ECO-CA", "B1 · 27(e)(iv)"), ("SOC-EFFECTIF", "B1 · 27(e)(v)"), ("GEN-PAYS-PRINCIPAL", "B1 · 27(e)(vi)"),
            ("GEN-CERTIF", "B1 · 28"), ("GEN-CERTIF-DESC", "B1 · 28"),
            ("GEN-FILIALES", "B1 · 27(d)"),
            ("B1_SITES", "Sites", "Sites", [
                ("GEN-SITE-ADRESSE", "B1 · 27(e)(vii)"), ("GEN-SITE-CP", "B1 · 27(e)(vii)"), ("GEN-SITE-VILLE", "B1 · 27(e)(vii)"),
                ("GEN-SITE-PAYS", "B1 · 27(e)(vii)"), ("GEN-SITE-GPS", "B1 · 27(e)(vii)")]),
            ("GEN-INFOS-INCHANGEES", "18", False), ("GEN-RAPPORT-LIEN", "18", False), ("GEN-OMISSIONS", "B1 · 27(b)", False),
            ("B1_COOP", "Coopératives (guide facultatif)", "Cooperatives (optional guidance)", [
                ("GEN-COOP-PARTICIPATION", "B2 · guidance 15", False), ("GEN-COOP-INVEST", "B2 · guidance 15", False),
                ("GEN-COOP-LIMITES", "B2 · guidance 15", False)]),
            ("GEN-AUTRES", "B1", False),
        ]),
        ("B2", "B2 – Pratiques, politiques et initiatives futures", "B2 – Practices, policies and future initiatives", [
            ("GOV-B2-PRATIQUES", "B2 · 29-31")] + [(f"GOV-B2-{c}", "B2 · 29-31") for c in (
                "CLIMAT", "POLLUTION", "EAU", "BIODIV", "CIRCULAIRE", "PERSONNEL", "CHAINE", "COMMUNAUTES", "CONSO", "CONDUITE")] + [
            ("GOV-B2-PUBLIC", "B2 · 29-31"), ("GOV-B2-CIBLE", "B2 · 29-31")]),
        ("B3", "B3 – Énergie et émissions de gaz à effet de serre", "B3 – Energy and greenhouse gas emissions", [
            ("B3_ENERGIE", "Énergie", "Energy", [
                ("NRJ-TOTAL-MWH", "B3 · 32"), ("NRJ-ELEC", "B3 · 32"), ("NRJ-ELEC-REN", "B3 · 32"), ("NRJ-ELEC-AUTO", "B3 · 32"),
                ("NRJ-COMBUSTIBLES", "B3 · 32"), ("NRJ-GAZ", "B3 · 32"), ("NRJ-FIOUL", "B3 · 32"), ("GES-GAZOLE", "B3 · 32"),
                ("GES-ESSENCE", "B3 · 32"), ("NRJ-COMB-AUTRES", "B3 · 32"), ("NRJ-COMB-REN", "B3 · 32"), ("NRJ-CHALEUR", "B3 · 32"),
                ("NRJ-FROID", "B3 · 32")]),
            ("B3_GES", "Émissions de gaz à effet de serre", "Greenhouse gas emissions", [
                ("GES-S1", "B3 · 33"), ("GES-S1-AUTRES", "B3 · 33(a)"), ("GES-S2-LB", "B3 · 33"), ("GES-S2-MB", "B3 · 33 (guidance)", False)]),
            ("B3_SCOPE3", "Scope 3 par catégorie", "Scope 3 by category", [
                (c, "B3 · 49-52", False) for c in ("GES-S3-ACHATS", "GES-S3-IMMO", "GES-S3-ENERGIE", "GES-S3-FRET-AMONT",
                                                "GES-S3-DECHETS", "GES-S3-DEPLACEMENTS", "GES-S3-DOMICILE", "GES-S3-ACTIFS-AMONT",
                                                "GES-S3-FRET-AVAL", "GES-S3-TRANSFO", "GES-S3-UTILISATION", "GES-S3-FIN-VIE",
                                                "GES-S3-ACTIFS-AVAL", "GES-S3-FRANCHISES", "GES-S3-INVEST")]),
            ("B3_DONNEES", "Données de calcul", "Calculation data", [
                "GES-S1-FIXE", "GES-S1-MOBILE", "GES-FUGITIVES", "CONV-GAZ-PCI", "CONV-FIOUL", "CONV-GAZOLE", "CONV-ESSENCE", "FE-GAZ", "FE-FIOUL",
                "FE-GAZOLE", "FE-ESSENCE", "FE-ELEC", "FE-CHALEUR", "FE-FROID"]),
        ]),
        ("B4", "B4 – Pollution de l'air, de l'eau et des sols", "B4 – Pollution of air, water and soil", [
            ("POL-DECLARATION", "B4 · 34"), ("POL-PUBLIC", "B4 · 34"), ("POL-URL", "B4 · 34"), ("POL-REJETS", "B4 · 34"),
            ("POL-REJETS-AUTRES", "B4 · 34", False)]),
        ("B5", "B5 – Biodiversité", "B5 – Biodiversity", [
            ("BIO-SITES", "B5 · 35"), ("BIO-SITE-ZONE", "B5 · 35"), ("BIO-SITE-ZONE-NOM", "B5 · 35")]),
        ("B6", "B6 – Eau", "B6 – Water", [
            ("EAU-PRELEVEMENT", "B6 · 36"), ("EAU-REJET-PROCESS", "B6 · 37"), ("EAU-STRESS", "B6 · 37")]),
        ("B7", "B7 – Ressources, économie circulaire et déchets", "B7 – Resource use, circular economy and waste", [
            ("ECO-CIRCULAIRE", "B7 · 38"), ("ECO-CIRCULAIRE-DESC", "B7 · 38"), ("DEC-TOTAL", "B7 · 39(a)"),
            ("DEC-DANGEREUX", "B7 · 39(a)"), ("DEC-RECYCLES", "B7 · 39(b)"), ("DEC-REEMPLOI", "B7 · 39(b)"),
            ("DEC-PAR-CODE", "B7 · 39(a)", False), ("ECO-MATIERES", "B7 · 39(c)")]),
        ("B8", "B8 – Effectifs : caractéristiques générales", "B8 – Workforce: general characteristics", [
            ("SOC-EFF-CDI", "B8 · 40(a)"), ("SOC-EFF-HOMMES", "B8 · 40(b)"), ("SOC-EFF-FEMMES", "B8 · 40(b)"),
            ("SOC-EFF-GENRE-AUTRE", "B8 · 40(b)", False), ("SOC-EFF-GENRE-NC", "B8 · 40(b)", False)]),
        ("B9", "B9 – Effectifs : santé et sécurité", "B9 – Workforce: health and safety", [
            ("SOC-ACCIDENTS-ENREG", "B9 · 41(a)"), ("SOC-DECES", "B9 · 41(b)")]),
        ("B10", "B10 – Effectifs : rémunération, négociation collective et formation",
         "B10 – Workforce: remuneration, collective bargaining and training", [
            ("SOC-SALAIRE-MINIMUM", "B10 · 42(a)"), ("SOC-ECART-OBLIGATION", "B10 · 42(b)"), ("SOC-REMU-H-HOMMES", "B10 · 42(b)"),
            ("SOC-REMU-H-FEMMES", "B10 · 42(b)"), ("SOC-SAL-CONVENTION", "B10 · 42(c)"), ("SOC-HEURES-FORM", "B10 · 42(d)")]),
        ("B11", "B11 – Condamnations et amendes pour corruption", "B11 – Convictions and fines for corruption and bribery", [
            ("GOV-CORRUPTION", "B11 · 43"), ("GOV-AMENDES", "B11 · 43")]),
        ("AUTRES", "Autres informations propres à l'entreprise", "Other entity-specific information", [
            ("ENV-AUTRES", "", False), ("SOC-AUTRES", "", False), ("GOV-AUTRES", "", False)]),
    ],
    "regles": ["Électricité renouvelable achetée ≤ électricité achetée", "Effectif féminin ≤ effectif total",
               "Effectif masculin ≤ effectif total", "Salariés en CDI ≤ effectif total", "Déchets dangereux ≤ déchets générés",
               "Déchets recyclés ≤ déchets générés", "Déchets préparés pour le réemploi ≤ déchets générés",
               "Salariés couverts par une convention ≤ effectif total", "Eau rejetée par les procédés ≤ eau prélevée"],
}
