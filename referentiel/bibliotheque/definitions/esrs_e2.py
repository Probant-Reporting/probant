"""ESRS E2 Pollution (ESRS révisées, règlement délégué (UE) 2026/1563) : modèle construit sur l'exemple ESRS E3 (méthode :
note de conception de l'atelier, non publiée ; socle commun : _esrs_communs.py).

Inventaire : lignes « ESRS_E2 » de esrs_coverage.csv (20 points de la liste de l'EFRAG du 28/08/2026, plus GDR-M). Choix :

- politiques, actions et cibles : bloc commun des exigences générales de l'ESRS 2 (``bloc_gdr``), saisi une fois pour
  l'entreprise (niveau « haut ») ;
- E2-4 §15 (rejets de polluants dans l'air, l'eau et le sol) : deux tableaux saisis au site, de même forme que ceux de la
  norme volontaire VS (liste européenne des polluants, puis polluants hors liste ; kg par milieu), mais des KPI distincts :
  la VS ne les demande qu'à l'entreprise qui doit déjà les déclarer, l'ESRS demande les rejets importants (évaluation de
  la direction, accidents compris) : revue des doublons de l'atelier, cas D8 ;
- E2-4 §16 (microplastiques primaires) : deux nombres au site, additionnés (kg) ;
- E2-5 (substances préoccupantes et extrêmement préoccupantes) : données de l'entité juridique (niveau « entite »), additionnées.
  §18 (fabricants, formulateurs, importeurs de substances) : quatre quantités pour les substances préoccupantes, quatre
  pour les substances extrêmement préoccupantes ; §19 (utilisateurs de substances) : quantité utilisée, et la quantité
  rejetée du §18(d) (même grandeur : une entreprise relève du §18 ou du §19, jamais des deux, E2 AR 4) ; un tableau par
  classe de danger pour les substances extrêmement préoccupantes (E2 AR 5 : une substance compte dans chacune de ses
  classes ; les totaux sont saisis à part, sans double compte) ; §20 : deux textes (noms des substances au-dessus de
  0,1 % en poids dans les articles) ;
- aucun KPI calculé : les totaux de E2-5 ne se déduisent pas du tableau par classe (double compte) ;
- règle de cohérence : les substances extrêmement préoccupantes font partie des substances préoccupantes (glossaire).
"""
from referentiel.bibliotheque.outils import kpi

from . import _esrs_communs as C
from . import _esrs_lot_e as L

SOURCE = C.SOURCE
COUVERTURE = C.COUVERTURE
UNITES = C.UNITES
TYPES_REPONSE = C.TYPES_REPONSE

PREFIXE = "POL"
SITES = ("Déclaration annuelle des émissions, mesures et bilans du site.", "Annual emissions report, measurements and balances of the site.")
ENTITE = ("Registre des substances chimiques, déclarations REACH, comptabilité matières de l'entité.",
          "Chemical substances register, REACH registrations, material accounts of the entity.")

# Phrases communes (fr, en) : champ du §18 et mesures transitoires de l'ESRS 1 §125 à 127
CHAMP_18 = (" Seulement pour une entité qui fabrique, formule ou importe des substances (secteur chimique, E2 AR 4) : saisir 0 "
            "s'il n'y en a pas ; toute autre entité répond N/A.",
            " Only for an entity that manufactures, formulates or imports substances (chemical sector, E2 AR 4): enter 0 if "
            "there is none; any other entity answers N/A.")
CHAMP_19 = (" Seulement pour une entité hors du champ du §18 qui utilise des substances (E2 AR 4) : saisir 0 s'il n'y en a pas ; "
            "toute autre entité répond N/A.",
            " Only for an entity outside the scope of §18 that uses substances (E2 AR 4): enter 0 if there is none; any other "
            "entity answers N/A.")
PHASE_SOC = (" Mesure transitoire : ces quantités peuvent être omises pour les exercices ouverts avant 2030 par une entreprise de "
             "la première vague, et pour les trois premiers exercices de reporting par toute autre entreprise (ESRS 1 §125(d), "
             "§126(d), §127(d)).",
             " Phase-in: these amounts may be omitted for financial years starting before 2030 by a wave-one company, and for the "
             "first three financial years of reporting by any other company (ESRS 1 §125(d), §126(d), §127(d)).")
PHASE_ARTICLES = (" Mesure transitoire : une entreprise qui ne fait qu'utiliser des articles contenant ces substances peut omettre "
                  "cette information avant 2028 (première vague) ou pour son premier exercice de reporting (autres entreprises) "
                  "(ESRS 1 §125(e), §126(e), §127(e)).",
                  " Phase-in: a company that only uses articles containing these substances may omit this information before 2028 "
                  "(wave one) or for its first financial year of reporting (other companies) (ESRS 1 §125(e), §126(e), §127(e)).")


def _d(fr, en, *plus):
    """Description (fr, en) : le texte, puis les phrases communes données (couples (fr, en))."""
    return fr + "".join(p[0] for p in plus), en + "".join(p[1] for p in plus)


SOC_DEF = ("Substances préoccupantes : substances extrêmement préoccupantes et substances classées dans les catégories de danger "
           "les plus graves du règlement CLP (cancérogénicité, mutagénicité, toxicité pour la reproduction, perturbation "
           "endocrinienne, persistance et bioaccumulation, sensibilisation, danger pour le milieu aquatique ou la couche "
           "d'ozone, toxicité d'organe cible) ; liste complète dans le glossaire des ESRS.",
           "Substances of concern: substances of very high concern and substances classified in the most serious hazard "
           "categories of the CLP regulation (carcinogenicity, mutagenicity, reproductive toxicity, endocrine disruption, "
           "persistence and bioaccumulation, sensitisation, hazard to the aquatic environment or the ozone layer, target "
           "organ toxicity); full list in the glossary of the ESRS.")
SVHC_DEF = ("Substances extrêmement préoccupantes : substances qui répondent aux critères de l'article 57 du règlement REACH et "
            "sont identifiées selon son article 59(1) (liste des candidates à l'autorisation).",
            "Substances of very high concern: substances that meet the criteria of Article 57 of the REACH regulation and are "
            "identified under its Article 59(1) (candidate list).")


def _soc(code, fr, en, verbe, para, source=ENTITE):
    """Substances préoccupantes (§18) : quantité en tonnes, additionnée, au niveau de l'entité."""
    return kpi(code, fr, en, "t", niveau=C.ENTITE, decimales=3,
               description=_d(f"Poids total des substances préoccupantes {verbe[0]} par l'entité pendant la période, en tonnes, "
                              f"sous forme pure ou en mélange (E2-5 §{para}, E2 AR 5, AR 6). " + SOC_DEF[0],
                              f"Total weight of substances of concern {verbe[1]} by the entity during the period, in tonnes, on "
                              f"their own or in mixtures (E2-5 §{para}, E2 AR 5, AR 6). " + SOC_DEF[1], CHAMP_18, PHASE_SOC),
               source=source)


def _svhc(code, fr, en, verbe, para, champ=CHAMP_18):
    """Substances extrêmement préoccupantes : total sans double compte (E2 AR 5), en tonnes, au niveau de l'entité."""
    return kpi(code, fr, en, "t", niveau=C.ENTITE, decimales=3,
               description=_d(f"Poids total des substances extrêmement préoccupantes {verbe[0]} par l'entité pendant la période, "
                              f"en tonnes (E2-5 §{para}, E2 AR 5, AR 6). Une substance qui entre dans plusieurs classes de danger "
                              f"ne compte qu'une fois dans ce total (pas de double compte). " + SVHC_DEF[0],
                              f"Total weight of substances of very high concern {verbe[1]} by the entity during the period, in "
                              f"tonnes (E2-5 §{para}, E2 AR 5, AR 6). A substance that falls in several hazard classes is counted "
                              f"once in this total (no double counting). " + SVHC_DEF[1], champ),
               source=ENTITE)


KPIS = dict([
    *C.bloc_gdr(PREFIXE, ("la pollution", "pollution")),
    # ------------------------------------------------------------------ E2-4 – pollution de l'air, de l'eau et du sol
    kpi("POL-EMISSIONS", "Rejets importants de polluants de la liste européenne", "Material emissions of pollutants of the European list",
        "", "Aucune", reponse="VS-TAB-POLLUANTS",
        description=("Une ligne par polluant de la liste européenne (registre E-PRTR) dont les rejets sont importants pour "
                     "l'entreprise : ses rejets dans l'air, l'eau et le sol en kg sur la période, accidents de l'environnement "
                     "compris (E2-4 §15, E2 AR 1, AR 2). Un rejet est important selon l'évaluation de la direction, qui tient "
                     "compte des activités et du secteur ; les seuils de rejet de l'annexe II du règlement (UE) 2024/1244 peuvent "
                     "aider. Les gaz à effet de serre relèvent de l'ESRS E1. Répondre N/A s'il n'y a aucun rejet important.",
                     "One row per pollutant of the European list (E-PRTR register) whose emissions are material to the company: "
                     "its emissions to air, water and soil in kg over the period, environmental accidents included (E2-4 §15, E2 "
                     "AR 1, AR 2). An emission is material by managerial assessment, which considers the activities and the sector; "
                     "the release thresholds of Annex II to Regulation (EU) 2024/1244 can help. Greenhouse gases belong to ESRS "
                     "E1. Answer N/A if there is no material emission."),
        source=SITES),
    kpi("POL-EMISSIONS-AUTRES", "Rejets importants d'autres polluants", "Material emissions of other pollutants", "", "Aucune",
        reponse="VS-TAB-POLLUANTS-AUTRES",
        description=("Une ligne par polluant absent de la liste européenne dont les rejets sont importants : son nom et ses "
                     "rejets dans l'air, l'eau et le sol en kg sur la période, accidents de l'environnement compris (E2-4 §15, "
                     "E2 AR 1). Les polluants que l'entreprise mesure ou suit servent à évaluer quels rejets sont importants "
                     "(E2 AR 2) : seuls les rejets importants se déclarent ici. Les transferts de polluants de l'eau vers une station de "
                     "traitement externe, quand ils sont importants, se décrivent comme information propre à l'entreprise "
                     "(E2 AR 3). Répondre N/A s'il n'y en a pas.",
                     "One row per pollutant that is not in the European list and whose emissions are material: its name and its "
                     "emissions to air, water and soil in kg over the period, environmental accidents included (E2-4 §15, E2 "
                     "AR 1). The pollutants that the company measures or monitors are an input to assess which emissions are "
                     "material (E2 AR 2): only material emissions are reported here. Transfers of water pollutants to an external treatment plant, "
                     "when they are material, are described as an entity-specific disclosure (E2 AR 3). Answer N/A if there are "
                     "none."),
        source=SITES),
    kpi("POL-MICROPLASTIQUES", "Microplastiques primaires fabriqués ou utilisés", "Primary microplastics manufactured or used", "kg",
        decimales=2,
        description=_d("Poids des microplastiques primaires fabriqués par l'entreprise ou utilisés dans ses produits pendant la "
                       "période, en kilogrammes (E2-4 §16, E2 AR 1). Un microplastique primaire est une microparticule de polymère "
                       "synthétique produite et ajoutée volontairement à un produit (billes, paillettes, stabilisants).",
                       "Weight of primary microplastics manufactured by the company or used in its products during the period, in "
                       "kilograms (E2-4 §16, E2 AR 1). A primary microplastic is a synthetic polymer microparticle that is "
                       "intentionally produced and added to a product (microbeads, glitter, stabilisers).", (C.ZERO, C.ZERO_EN)),
        source=("Nomenclatures de production, fiches techniques des matières, déclarations REACH.",
                "Bills of materials, material technical sheets, REACH registrations.")),
    kpi("POL-MICROPLASTIQUES-REJETS", "Microplastiques primaires rejetés dans l'environnement",
        "Primary microplastics released into the environment", "kg", decimales=2,
        description=_d("Poids des microplastiques primaires rejetés directement dans l'environnement pendant la période, en "
                       "kilogrammes (E2-4 §16, E2 AR 1), à déclarer séparément des microplastiques fabriqués ou utilisés.",
                       "Weight of primary microplastics released directly into the environment during the period, in kilograms "
                       "(E2-4 §16, E2 AR 1), disclosed separately from the microplastics manufactured or used.",
                       (C.ZERO, C.ZERO_EN)),
        source=SITES),
    # ------------------------------------------------------------------ E2-5 – substances préoccupantes (§18)
    _soc("POL-SOC-ACHETEES", "Substances préoccupantes achetées", "Substances of concern procured", ("achetées", "procured"), "18(a)"),
    _soc("POL-SOC-FABRIQUEES", "Substances préoccupantes fabriquées", "Substances of concern manufactured",
         ("fabriquées", "manufactured"), "18(b)"),
    _soc("POL-SOC-MISES-MARCHE", "Substances préoccupantes mises sur le marché", "Substances of concern placed on the market",
         ("mises sur le marché", "placed on the market"), "18(c)"),
    _soc("POL-SOC-REJETEES", "Substances préoccupantes rejetées directement dans l'environnement",
         "Substances of concern directly released into the environment",
         ("rejetées directement dans l'environnement (air, eau, sol), fuites et déversements accidentels compris",
          "directly released into the environment (air, water, soil), unintentional leaks and spills included"), "18(d)"),
    # ------------------------------------------------------------------ E2-5 – substances extrêmement préoccupantes (§18, §19)
    _svhc("POL-SVHC-ACHETEES", "Substances extrêmement préoccupantes achetées", "Substances of very high concern procured",
          ("achetées sous forme pure ou en mélange", "procured on their own or in mixtures"), "18(a)"),
    _svhc("POL-SVHC-FABRIQUEES", "Substances extrêmement préoccupantes fabriquées", "Substances of very high concern manufactured",
          ("fabriquées sous forme pure ou en mélange", "manufactured on their own or in mixtures"), "18(b)"),
    _svhc("POL-SVHC-MISES-MARCHE", "Substances extrêmement préoccupantes mises sur le marché",
          "Substances of very high concern placed on the market",
          ("mises sur le marché sous forme pure ou en mélange", "placed on the market on their own or in mixtures"), "18(c)"),
    kpi("POL-SVHC-REJETEES", "Substances extrêmement préoccupantes rejetées directement dans l'environnement",
        "Substances of very high concern directly released into the environment", "t", niveau=C.ENTITE, decimales=3,
        description=_d("Poids total des substances extrêmement préoccupantes rejetées directement dans l'environnement (air, "
                       "eau, sol) par l'entité pendant la période, en tonnes, fuites et déversements accidentels compris (E2-5 "
                       "§18(d) pour un fabricant, formulateur ou importeur, §19(b) pour un utilisateur : c'est la même grandeur "
                       "et une entreprise relève de l'un ou de l'autre, E2 AR 4, AR 5, AR 6). Pas de double compte entre classes "
                       "de danger. " + SVHC_DEF[0],
                       "Total weight of substances of very high concern directly released into the environment (air, water, soil) "
                       "by the entity during the period, in tonnes, unintentional leaks and spills included (E2-5 §18(d) for a "
                       "manufacturer, formulator or importer, §19(b) for a user: it is the same quantity and a company is one or the "
                       "other, E2 AR 4, AR 5, AR 6). No double counting between hazard classes. " + SVHC_DEF[1],
                       (" Seulement pour une entité qui fabrique, formule, importe ou utilise des substances : saisir 0 s'il n'y en a "
                        "pas ; toute autre entité répond N/A.",
                        " Only for an entity that manufactures, formulates, imports or uses substances: enter 0 if there is none; "
                        "any other entity answers N/A.")),
        source=ENTITE),
    _svhc("POL-SVHC-UTILISEES", "Substances extrêmement préoccupantes utilisées", "Substances of very high concern used",
          ("utilisées pendant la production et la fourniture de services", "used during production and during the delivery of "
                                                                         "services"), "19(a)", CHAMP_19),
    kpi("POL-SVHC-TAB", "Substances extrêmement préoccupantes par classe de danger", "Substances of very high concern by hazard class",
        "", "Aucune", reponse="ESRS-TAB-SVHC", niveau=C.ENTITE,
        description=("Une ligne par classe de danger du règlement CLP : poids en tonnes des substances extrêmement préoccupantes "
                     "achetées, fabriquées, mises sur le marché, utilisées et rejetées dans l'environnement pendant la période "
                     "(E2-5 §18, §19, E2 AR 5). Une substance se compte dans chacune de ses classes de danger : les colonnes "
                     "d'une même ligne ne s'additionnent pas d'une ligne à l'autre. Les totaux sans double compte se saisissent "
                     "dans les KPI de poids total. Même champ que les totaux (§18 ou §19, E2 AR 4) ; toute autre entité répond N/A.",
                     "One row per hazard class of the CLP regulation: weight in tonnes of the substances of very high concern "
                     "procured, manufactured, placed on the market, used and released into the environment during the period "
                     "(E2-5 §18, §19, E2 AR 5). A substance is counted in each of its hazard classes: the rows must not be added "
                     "up. The totals without double counting are entered in the total weight KPIs. Same scope as the totals (§18 "
                     "or §19, E2 AR 4); any other entity answers N/A."),
        source=ENTITE),
    # ------------------------------------------------------------------ E2-5 – substances dans les articles (§20)
    kpi("POL-SVHC-ARTICLES-ACHETES", "Substances extrêmement préoccupantes au-dessus de 0,1 % dans les articles achetés",
        "Substances of very high concern above 0.1 % in procured articles", "", "Aucune", reponse="Texte", niveau=C.HAUT,
        description=_d("Noms des substances extrêmement préoccupantes présentes à plus de 0,1 % en poids dans les composants ou "
                       "articles achetés (E2-5 §20(a), article 33 du règlement REACH, E2 AR 7). Pour un fabricant, un importateur ou "
                       "un utilisateur d'articles qui en contiennent. Répondre N/A si aucun article n'en contient. L'information "
                       "peut renvoyer à celle déjà déclarée au titre d'une autre loi.",
                       "Names of the substances of very high concern present at more than 0.1 % by weight in the procured "
                       "components or articles (E2-5 §20(a), Article 33 of the REACH regulation, E2 AR 7). For a manufacturer, an "
                       "importer or a user of articles that contain them. Answer N/A if no article contains any. The information "
                       "may refer to what is already reported under another law.", PHASE_ARTICLES)),
    kpi("POL-SVHC-ARTICLES-VENDUS", "Substances extrêmement préoccupantes au-dessus de 0,1 % dans les articles mis sur le marché",
        "Substances of very high concern above 0.1 % in articles placed on the market", "", "Aucune", reponse="Texte",
        niveau=C.HAUT,
        description=_d("Noms des substances extrêmement préoccupantes présentes à plus de 0,1 % en poids dans les composants ou "
                       "articles mis sur le marché (E2-5 §20(b), article 33 du règlement REACH, E2 AR 7). Pour un fabricant, un "
                       "importateur ou un utilisateur d'articles qui en contiennent. Répondre N/A si aucun article n'en contient. "
                       "L'information peut renvoyer à celle déjà déclarée au titre d'une autre loi.",
                       "Names of the substances of very high concern present at more than 0.1 % by weight in the components or "
                       "articles placed on the market (E2-5 §20(b), Article 33 of the REACH regulation, E2 AR 7). For a "
                       "manufacturer, an importer or a user of articles that contain them. Answer N/A if no article contains any. "
                       "The information may refer to what is already reported under another law.", PHASE_ARTICLES)),
])

# Entrée progressive de l'ESRS 1 §126(a) (toutes les normes thématiques avant 2027 pour les petites entreprises de la
# première vague) : même phrase que dans G1, ajoutée à chaque KPI propre au modèle ; les KPI repris de la norme VS ou
# du catalogue ne la portent pas (une seule définition, qui se lirait aussi dans une installation VS seule).
KPIS = dict(L.avec_phase_in(KPIS.items(), L.PHASE_IN_G1))

REGLES = {  # nom fr : (gauche, opérateur, droite, (description fr, en), nom en)
    "Substances extrêmement préoccupantes achetées ≤ substances préoccupantes achetées": (
        "[POL-SVHC-ACHETEES]", "<=", "[POL-SOC-ACHETEES]",
        ("Les substances extrêmement préoccupantes font partie des substances préoccupantes.",
         "Substances of very high concern are part of the substances of concern."),
        "SVHC procured ≤ substances of concern procured"),
    "Substances extrêmement préoccupantes fabriquées ≤ substances préoccupantes fabriquées": (
        "[POL-SVHC-FABRIQUEES]", "<=", "[POL-SOC-FABRIQUEES]",
        ("Les substances extrêmement préoccupantes font partie des substances préoccupantes.",
         "Substances of very high concern are part of the substances of concern."),
        "SVHC manufactured ≤ substances of concern manufactured"),
    "Substances extrêmement préoccupantes mises sur le marché ≤ substances préoccupantes mises sur le marché": (
        "[POL-SVHC-MISES-MARCHE]", "<=", "[POL-SOC-MISES-MARCHE]",
        ("Les substances extrêmement préoccupantes font partie des substances préoccupantes.",
         "Substances of very high concern are part of the substances of concern."),
        "SVHC placed on the market ≤ substances of concern placed on the market"),
    "Substances extrêmement préoccupantes rejetées ≤ substances préoccupantes rejetées": (
        "[POL-SVHC-REJETEES]", "<=", "[POL-SOC-REJETEES]",
        ("Les substances extrêmement préoccupantes font partie des substances préoccupantes.",
         "Substances of very high concern are part of the substances of concern."),
        "SVHC released ≤ substances of concern released"),
}

SOCLE = C.socle("ESRS_E2", "1.1", "2026-11-19", [
    ("E2_1", "E2-1 – Politiques relatives à la pollution", "E2-1 – Policies related to pollution", C.arbre_gdr(PREFIXE, "E2-1", "P")),
    ("E2_2", "E2-2 – Actions et ressources relatives à la pollution", "E2-2 – Actions and resources related to pollution",
     C.arbre_gdr(PREFIXE, "E2-2", "A")),
    ("E2_3", "E2-3 – Cibles relatives à la pollution", "E2-3 – Targets related to pollution", C.arbre_gdr(PREFIXE, "E2-3", "T")),
    ("E2_4", "E2-4 – Pollution de l'air, de l'eau et du sol", "E2-4 – Pollution of air, water and soil", [
        ("POL-EMISSIONS", "E2-4 · 15"), ("POL-EMISSIONS-AUTRES", "E2-4 · 15"), ("POL-MICROPLASTIQUES", "E2-4 · 16"),
        ("POL-MICROPLASTIQUES-REJETS", "E2-4 · 16"), *C.arbre_gdr(PREFIXE, "E2-4", "M")]),
    ("E2_5", "E2-5 – Substances préoccupantes et extrêmement préoccupantes",
     "E2-5 – Substances of concern and substances of very high concern", [
         ("POL-SOC-ACHETEES", "E2-5 · 18(a)"), ("POL-SOC-FABRIQUEES", "E2-5 · 18(b)"), ("POL-SOC-MISES-MARCHE", "E2-5 · 18(c)"),
         ("POL-SOC-REJETEES", "E2-5 · 18(d)"), ("POL-SVHC-ACHETEES", "E2-5 · 18(a)"), ("POL-SVHC-FABRIQUEES", "E2-5 · 18(b)"),
         ("POL-SVHC-MISES-MARCHE", "E2-5 · 18(c)"), ("POL-SVHC-REJETEES", "E2-5 · 18(d), 19(b)"),
         ("POL-SVHC-UTILISEES", "E2-5 · 19(a)"), ("POL-SVHC-TAB", "E2-5 · 18, 19 ; AR 5"),
         ("POL-SVHC-ARTICLES-ACHETES", "E2-5 · 20(a)"), ("POL-SVHC-ARTICLES-VENDUS", "E2-5 · 20(b)")]),
], regles=list(REGLES))
