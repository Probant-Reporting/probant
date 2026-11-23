"""ESRS E5 Utilisation des ressources et économie circulaire (ESRS révisées, règlement délégué (UE) 2026/1563) : modèle
construit sur l'exemple ESRS E3 (méthode : note de conception de l'atelier, non publiée ; socle commun : _esrs_communs.py).

Inventaire : lignes « ESRS_E5 » de esrs_coverage.csv (18 points de la liste de l'EFRAG du 28/08/2026, plus GDR-M). Choix :

- politiques, actions et cibles : bloc commun des exigences générales de l'ESRS 2 (``bloc_gdr``), saisi une fois pour
  l'entreprise (niveau « haut ») ;
- E5-1 §9, E5-4 §13(a), E5-5 §15(a), (b) et §16(a) : textes de l'entreprise ; E5-5 §15(c) : un tableau, une ligne par
  produit clé, avec les deux taux de recyclabilité en % (produit, emballage ; E5 AR 3) ;
- matières entrantes (E5-4 §13(b) à (d)) : poids total des matières clés et poids des ressources secondaires, saisis
  par site et additionnés, part des ressources secondaires calculée ; poids de chaque matière clé : tableau (la norme
  permet le poids ou la part : le poids, la part s'en déduit du total) ; différent de ECO-MATIERES de la norme volontaire VS
  (toute unité, secteurs aux flux importants) : revue des doublons de l'atelier, cas D11 ;
- déchets (E5-5 §16, §17) : saisis par site, en tonnes, additionnés. Le total (DEC-TOTAL), les déchets dangereux
  (DEC-DANGEREUX), recyclés et préparés pour le réemploi (DEC-RECYCLES, DEC-REEMPLOI) sont ceux de la norme volontaire VS (même
  définition, même unité, même période : revue des doublons) ; on saisit en plus les autres opérations de valorisation, les
  trois opérations d'élimination, la destination inconnue et, pour les déchets dangereux, la part détournée et la part
  éliminée. Les déchets détournés de l'élimination (réemploi + recyclage + autres valorisations) et éliminés (incinération +
  décharge + autres éliminations) sont calculés, ainsi que les treize parts en % du total des déchets générés (le
  pourcentage est calculé à chaque niveau de l'arbre, jamais saisi). DEC-VALORISES du catalogue n'est pas repris : il compte
  toute incinération avec valorisation énergétique, la norme seulement celle qui remplit la condition R1 (E5 AR 6) ;
- règles de cohérence : détournés + éliminés + destination inconnue = générés ; parts dangereuses ≤ parts ; ressources
  secondaires ≤ matières clés ; les deux règles de la norme volontaire VS (recyclés, réemploi ≤ générés) sont reprises
  telles quelles (même nom, même définition).
"""
from referentiel.bibliotheque.outils import ZERO, ZERO_EN, kpi

from . import _esrs_communs as C
from . import _esrs_lot_e as L
from .vs_base import REGLES as REGLES_VS

SOURCE = C.SOURCE
COUVERTURE = C.COUVERTURE
UNITES = C.UNITES
TYPES_REPONSE = C.TYPES_REPONSE

PREFIXE = "ECO-CIRC"
DECHETS = ("Registre des déchets, bordereaux de suivi, bilans des prestataires.",
           "Waste register, waste transfer notes, service provider reports.")
ORIGINE = (" Poids du déchet dans son état d'origine, sans retraitement comme un poids sec (E5 AR 5).",
           " Weight of the waste in its original state, with no further manipulation such as a dry weight (E5 AR 5).")


def _d(fr, en, zero=True):
    """Description (fr, en) d'un poids de déchets : état d'origine (E5 AR 5), puis la phrase « Saisir 0 s'il n'y en a pas »."""
    return (fr + ORIGINE[0] + (ZERO if zero else ""), en + ORIGINE[1] + (ZERO_EN if zero else ""))


def _part(code, fr, en, formule, fr_desc, en_desc, para):
    """Part en % du total des déchets générés, calculée (agrégation « Formule » : recalculée à chaque niveau de l'arbre)."""
    return kpi(code, fr, en, "", "Formule", "Calculé", "Pourcentage", formule,
               description=(f"Calculée par l'outil : {fr_desc} divisés par le total des déchets générés (E5-5 {para}).",
                            f"Calculated by the tool: {en_desc} divided by the total waste generated (E5-5 {para})."))


KPIS = dict([
    *C.bloc_gdr(PREFIXE, ("les ressources et l'économie circulaire", "resource use and circular economy",
                          "aux ressources et à l'économie circulaire")),
    # ------------------------------------------------------------------ E5-1 – politiques
    kpi("ECO-CIRC-ECOCONCEPTION", "Principes d'économie circulaire et d'écoconception dans les produits et services clés",
        "Circular economy principles and eco-design in key products and services", "", "Aucune", reponse="Texte", niveau=C.HAUT,
        description=("Seulement si l'entreprise intègre des principes d'économie circulaire ou des exigences d'écoconception dans "
                     "ses produits clés et ses services d'économie circulaire : expliquer comment (E5-1 §9). Principes d'économie "
                     "circulaire : éliminer les déchets et la pollution dès la conception, faire circuler produits et matières à "
                     "leur plus haute valeur par l'entretien, le réemploi et la remise à neuf, régénérer la nature (glossaire). "
                     "Produit clé : produit central pour la création de valeur ou la stratégie, défini par l'évaluation de la "
                     "direction (glossaire). Répondre N/A sinon.",
                     "Only if the company integrates circular economy principles or eco-design requirements in its key products and "
                     "circular economy services: explain how (E5-1 §9). Circular economy principles: eliminate waste and pollution "
                     "by design, circulate products and materials at their highest value through maintenance, reuse and "
                     "refurbishment, regenerate nature (glossary). Key product: a product central to value creation or strategy, "
                     "defined by managerial assessment (glossary). Answer N/A otherwise.")),
    # ------------------------------------------------------------------ E5-4 – matières entrantes
    kpi("ECO-CIRC-MATIERES-DESC", "Matières clés, matières premières critiques et stratégiques",
        "Key materials, critical and strategic raw materials", "", "Aucune", reponse="Texte", niveau=C.HAUT,
        description=("Une description courte de chaque matière clé utilisée, avec son rôle et son importance pour les activités, et "
                     "les matières premières critiques ou stratégiques qu'elle contient (E5-4 §13(a), E5 AR 1, AR 2). Matière "
                     "clé : matière, substance, composant ou produit essentiel à la capacité de fabriquer ou de fournir, retenu "
                     "par l'évaluation de la direction (volume, coût, criticité, enjeux externes) (glossaire). Distinguer matière "
                     "technique et matière biologique si cela aide à comprendre les impacts, risques ou opportunités ; indiquer les "
                     "matières premières critiques et stratégiques du règlement (UE) 2024/1252 (annexes I et II), par exemple une "
                     "batterie qui contient du lithium.",
                     "A short description of each key material used, with its role and relevance in the operations, and the "
                     "critical or strategic raw materials it contains (E5-4 §13(a), E5 AR 1, AR 2). Key material: a material, "
                     "substance, component or product essential to the ability to manufacture or deliver, identified by managerial "
                     "assessment (volume, cost, criticality, external factors) (glossary). Tell technical material from biological "
                     "material if it helps to understand the impacts, risks or opportunities; point out the critical and strategic "
                     "raw materials of Regulation (EU) 2024/1252 (Annexes I and II), for example a battery that contains lithium.")),
    kpi("ECO-CIRC-MATIERES-POIDS", "Poids total des matières clés", "Total weight of key materials", "t", decimales=1,
        description=("Poids de toutes les matières clés entrées dans les activités du site pendant la période, en tonnes (E5-4 "
                     "§13(b)). Sert aussi de total pour la part des ressources secondaires." + ZERO,
                     "Weight of all the key materials that entered the operations of the site during the period, in tonnes (E5-4 "
                     "§13(b)). Also the total for the share of secondary resources." + ZERO_EN),
        source=("Achats, nomenclatures de production, bilans matières.", "Purchasing, bills of materials, material balances.")),
    kpi("ECO-CIRC-MATIERES-TAB", "Poids de chaque matière clé", "Weight of each key material", "", "Aucune",
        reponse="ESRS-TAB-MATIERES",
        description=("Une ligne par matière clé : son poids en tonnes sur la période (E5-4 §13(c)). La norme permet le poids ou la "
                     "part du poids total : on saisit le poids, la part s'en déduit du poids total des matières clés. Le total "
                     "du tableau doit être le poids total des matières clés.",
                     "One row per key material: its weight in tonnes over the period (E5-4 §13(c)). The standard allows the weight "
                     "or the share of the total weight: enter the weight, the share follows from the total weight of key "
                     "materials. The total of the table must be the total weight of key materials."),
        source=("Achats, nomenclatures de production, bilans matières.", "Purchasing, bills of materials, material balances.")),
    kpi("ECO-CIRC-SECONDAIRES", "Poids des ressources secondaires utilisées", "Weight of secondary resources used", "t", decimales=1,
        description=("Poids des ressources secondaires entrées dans les activités du site pendant la période, en tonnes, parmi les "
                     "matières clés (E5-4 §13(d)). Ressource secondaire : matière déjà utilisée, récupérée de flux de déchets ou "
                     "d'autres sources, et réintroduite dans les cycles de production, par exemple matière recyclée, produit ou "
                     "composant réemployé, réparé, remis à neuf ou refabriqué (glossaire)." + ZERO,
                     "Weight of the secondary resources that entered the operations of the site during the period, in tonnes, among "
                     "the key materials (E5-4 §13(d)). Secondary resource: a material previously used, recovered from waste streams "
                     "or other sources, and reintroduced into production cycles, for example recycled material, reused, repaired, "
                     "refurbished or remanufactured product or component (glossary)." + ZERO_EN),
        source=("Achats, fiches de matière recyclée, bilans matières.", "Purchasing, recycled-content sheets, material balances.")),
    kpi("ECO-CIRC-PART-SECONDAIRES", "Part des ressources secondaires dans les matières clés",
        "Share of secondary resources in key materials", "", "Formule", "Calculé", "Pourcentage",
        "[ECO-CIRC-SECONDAIRES] / [ECO-CIRC-MATIERES-POIDS]",
        description=("Calculée par l'outil : poids des ressources secondaires divisé par le poids total des matières clés (E5-4 "
                     "§13(d), présentation en part).",
                     "Calculated by the tool: weight of secondary resources divided by the total weight of key materials (E5-4 "
                     "§13(d), presentation as a share).")),
    # ------------------------------------------------------------------ E5-5 – produits
    kpi("ECO-CIRC-DURABILITE", "Durabilité attendue des produits clés", "Expected durability of key products", "", "Aucune",
        reponse="Texte", niveau=C.HAUT,
        description=("Pour chaque produit clé : sa durabilité attendue, en information qualitative ou chiffrée (E5-5 §15(a)). Si "
                     "elle est chiffrée, écrire la mesure et son unité, par exemple une durée de vie en années ou en cycles, et "
                     "comment elle est établie. Produit clé : voir le glossaire. Répondre N/A s'il n'y a pas de produit clé.",
                     "For each key product: its expected durability, as qualitative or quantitative information (E5-5 §15(a)). If "
                     "quantitative, write the measure and its unit, for example a lifetime in years or cycles, and how it is "
                     "established. Key product: see the glossary. Answer N/A if there is no key product.")),
    kpi("ECO-CIRC-REPARABILITE", "Réparabilité des produits clés", "Repairability of key products", "", "Aucune", reponse="Texte",
        niveau=C.HAUT,
        description=("Pour chaque produit clé : dans quelle mesure il est réparable, en information qualitative ou chiffrée (E5-5 "
                     "§15(b)). Si elle est chiffrée, écrire la mesure et son unité, par exemple un indice de réparabilité, et "
                     "comment elle est établie. Répondre N/A s'il n'y a pas de produit clé.",
                     "For each key product: the extent to which it is repairable, as qualitative or quantitative information (E5-5 "
                     "§15(b)). If quantitative, write the measure and its unit, for example a repairability index, and how it is "
                     "established. Answer N/A if there is no key product.")),
    kpi("ECO-CIRC-RECYCLABILITE", "Taux de recyclabilité prévu des produits clés et de leurs emballages",
        "Designed recyclability rate of key products and their packaging", "", "Aucune", reponse="ESRS-TAB-RECYCLAB",
        niveau=C.HAUT,
        description=("Une ligne par produit clé : le taux de recyclabilité prévu à la conception du produit et celui de son "
                     "emballage, en pourcentage de 0 à 100 (E5-5 §15(c), E5 AR 3). Taux d'un produit = poids total des matières "
                     "recyclables incorporées dans le produit ÷ poids total du produit × 100 ; même calcul pour l'emballage, avec "
                     "le poids de l'emballage. Répondre N/A s'il n'y a pas de produit clé.",
                     "One row per key product: the recyclability rate designed into the product and that of its packaging, as a "
                     "percentage from 0 to 100 (E5-5 §15(c), E5 AR 3). Rate of a product = total weight of recyclable materials "
                     "incorporated in the product ÷ total weight of the product × 100; same calculation for the packaging, with "
                     "the weight of the packaging. Answer N/A if there is no key product."),
        source=("Fiches produit, nomenclatures, études de recyclabilité.", "Product sheets, bills of materials, recyclability studies.")),
    # ------------------------------------------------------------------ E5-5 – déchets
    kpi("DEC-FLUX-DESC", "Flux de déchets", "Waste streams", "", "Aucune", reponse="Texte", niveau=C.HAUT,
        description=("Une description des flux de déchets des activités propres : pour chaque flux, un nom (par exemple selon la "
                     "liste européenne des déchets, décision 2000/532/CE) et les matières clés qu'il contient (biomasse, métaux, "
                     "minéraux non métalliques, plastiques, textiles, matières premières critiques, terres rares…) (E5-5 §16(a), "
                     "E5 AR 4). Écrire aussi quelles sont les « autres opérations de valorisation » utilisées (E5 AR 6).",
                     "A description of the waste streams of the own operations: for each stream, a name (for example from the "
                     "European List of Waste, Decision 2000/532/EC) and the key materials it contains (biomass, metals, "
                     "non-metallic minerals, plastics, textiles, critical raw materials, rare earths…) (E5-5 §16(a), E5 AR 4). "
                     "Also write what the ‘other recovery operations’ used are (E5 AR 6).")),
    kpi("DEC-AUTRE-VALO", "Déchets envoyés vers d'autres opérations de valorisation", "Waste sent to other recovery operations", "t",
        decimales=1,
        description=_d("Déchets du site envoyés vers des opérations de valorisation autres que la préparation en vue du réemploi "
                       "et le recyclage, pendant la période, en tonnes (E5-5 §16(c)(iii), E5 AR 6). Opérations de valorisation : "
                       "annexe II de la directive 2008/98/CE sur les déchets. L'incinération avec valorisation énergétique n'en est "
                       "une que si elle remplit la condition R1 de cette annexe ; sinon, c'est de l'incinération (élimination). "
                       "Dire lesquelles dans la description des flux de déchets.",
                       "Waste of the site sent to recovery operations other than preparation for reuse and recycling, during the "
                       "period, in tonnes (E5-5 §16(c)(iii), E5 AR 6). Recovery operations: Annex II to Directive 2008/98/EC on "
                       "waste. Incineration with energy recovery is one only if it meets condition R1 of that Annex; otherwise it "
                       "is incineration (disposal). Say which ones in the description of the waste streams."), source=DECHETS),
    kpi("DEC-DETOURNES", "Déchets détournés de l'élimination (réemploi, recyclage, autres valorisations)",
        "Waste diverted from disposal (reuse, recycling, other recovery)", "t", "Somme", "Calculé",
        formule="[DEC-REEMPLOI] + [DEC-RECYCLES] + [DEC-AUTRE-VALO]",
        description=("Calculés par l'outil : déchets préparés en vue du réemploi, recyclés et envoyés vers d'autres opérations de "
                     "valorisation (E5-5 §16(c)).",
                     "Calculated by the tool: waste prepared for reuse, recycled and sent to other recovery operations (E5-5 "
                     "§16(c)).")),
    kpi("DEC-DETOURNES-DANG", "Déchets dangereux détournés de l'élimination", "Hazardous waste diverted from disposal", "t",
        decimales=1,
        description=_d("Partie des déchets détournés de l'élimination (réemploi, recyclage, autres valorisations) qui est dangereuse, "
                       "pendant la période, en tonnes (E5-5 §16(c)). Déchet dangereux : il présente une ou plusieurs des propriétés "
                       "dangereuses de l'annexe III de la directive 2008/98/CE (glossaire).",
                       "Part of the waste diverted from disposal (reuse, recycling, other recovery) that is hazardous, during the "
                       "period, in tonnes (E5-5 §16(c)). Hazardous waste: it displays one or more of the hazardous properties of "
                       "Annex III to Directive 2008/98/EC (glossary)."), source=DECHETS),
    kpi("DEC-INCINERATION", "Déchets incinérés (élimination)", "Waste incinerated (disposal)", "t", decimales=1,
        description=_d("Déchets du site envoyés à l'incinération qui n'est pas une opération de valorisation, pendant la période, en "
                       "tonnes (E5-5 §16(d)(i)). L'incinération avec valorisation énergétique qui remplit la condition R1 de "
                       "l'annexe II de la directive 2008/98/CE se compte dans les autres opérations de valorisation (E5 AR 6).",
                       "Waste of the site sent to incineration that is not a recovery operation, during the period, in tonnes "
                       "(E5-5 §16(d)(i)). Incineration with energy recovery that meets condition R1 of Annex II to Directive "
                       "2008/98/EC is counted in other recovery operations (E5 AR 6)."), source=DECHETS),
    kpi("DEC-DECHARGE", "Déchets mis en décharge", "Waste sent to landfill", "t", decimales=1,
        description=_d("Déchets du site mis en décharge (site d'élimination par dépôt sur ou dans le sol) pendant la période, en "
                       "tonnes (E5-5 §16(d)(ii)).",
                       "Waste of the site sent to landfill (a waste disposal site for deposit onto or into land) during the "
                       "period, in tonnes (E5-5 §16(d)(ii))."), source=DECHETS),
    kpi("DEC-AUTRE-ELIM", "Déchets envoyés vers d'autres opérations d'élimination", "Waste sent to other disposal operations", "t",
        decimales=1,
        description=_d("Déchets du site éliminés autrement que par incinération ou mise en décharge, pendant la période, en tonnes "
                       "(E5-5 §16(d)(iii), E5 AR 7). Opérations d'élimination : annexe I de la directive 2008/98/CE sur les déchets.",
                       "Waste of the site disposed of otherwise than by incineration or landfill, during the period, in tonnes "
                       "(E5-5 §16(d)(iii), E5 AR 7). Disposal operations: Annex I to Directive 2008/98/EC on waste."),
        source=DECHETS),
    kpi("DEC-ELIMINES", "Déchets dirigés vers l'élimination", "Waste directed to disposal", "t", "Somme", "Calculé",
        formule="[DEC-INCINERATION] + [DEC-DECHARGE] + [DEC-AUTRE-ELIM]",
        description=("Calculés par l'outil : déchets incinérés (élimination), mis en décharge et envoyés vers d'autres opérations "
                     "d'élimination (E5-5 §16(d)).",
                     "Calculated by the tool: waste incinerated (disposal), sent to landfill and sent to other disposal operations "
                     "(E5-5 §16(d)).")),
    kpi("DEC-ELIMINES-DANG", "Déchets dangereux dirigés vers l'élimination", "Hazardous waste directed to disposal", "t", decimales=1,
        description=_d("Partie des déchets dirigés vers l'élimination (incinération, décharge, autres éliminations) qui est "
                       "dangereuse, pendant la période, en tonnes (E5-5 §16(d)). Déchet dangereux : il présente une ou plusieurs "
                       "des propriétés dangereuses de l'annexe III de la directive 2008/98/CE (glossaire).",
                       "Part of the waste directed to disposal (incineration, landfill, other disposal) that is hazardous, during "
                       "the period, in tonnes (E5-5 §16(d)). Hazardous waste: it displays one or more of the hazardous properties of "
                       "Annex III to Directive 2008/98/EC (glossary)."), source=DECHETS),
    kpi("DEC-INCONNUE", "Déchets de destination finale inconnue", "Waste with unknown final destination", "t", decimales=1,
        description=_d("Déchets du site dont la destination finale n'est pas connue, pendant la période, en tonnes (E5-5 §16(e)).",
                       "Waste of the site whose final destination is not known, during the period, in tonnes (E5-5 §16(e))."),
        source=DECHETS),
    kpi("DEC-RADIOACTIFS", "Déchets radioactifs générés", "Radioactive waste generated", "t", decimales=3,
        description=_d("Poids total des déchets radioactifs générés par le site pendant la période, en tonnes (E5-5 §17). Déchet "
                       "radioactif : au sens de l'article 3, point 7, de la directive 2011/70/Euratom.",
                       "Total weight of the radioactive waste generated by the site during the period, in tonnes (E5-5 §17). "
                       "Radioactive waste: as defined in Article 3(7) of Directive 2011/70/Euratom."),
        source=("Registre des déchets radioactifs, déclarations à l'autorité compétente.",
                "Radioactive waste register, declarations to the competent authority.")),
    # ------------------------------------------------------------------ E5-5 – parts des déchets (calculées)
    _part("DEC-PART-DETOURNES", "Part des déchets détournés de l'élimination (réemploi, recyclage, autres valorisations)",
          "Share of waste diverted from disposal (reuse, recycling, other recovery)",
          "[DEC-DETOURNES] / [DEC-TOTAL]", "déchets détournés de l'élimination", "waste diverted from disposal", "§16(c)"),
    _part("DEC-PART-DET-DANG", "Part des déchets détournés de l'élimination : dangereux",
          "Share of waste diverted from disposal: hazardous", "[DEC-DETOURNES-DANG] / [DEC-TOTAL]",
          "déchets dangereux détournés de l'élimination", "hazardous waste diverted from disposal", "§16(c)"),
    _part("DEC-PART-DET-NON-DANG", "Part des déchets détournés de l'élimination : non dangereux",
          "Share of waste diverted from disposal: non-hazardous", "([DEC-DETOURNES] - [DEC-DETOURNES-DANG]) / [DEC-TOTAL]",
          "déchets non dangereux détournés de l'élimination (détournés moins dangereux détournés)",
          "non-hazardous waste diverted from disposal (diverted minus hazardous diverted)", "§16(c)"),
    _part("DEC-PART-REEMPLOI", "Part des déchets préparés en vue du réemploi", "Share of waste prepared for reuse",
          "[DEC-REEMPLOI] / [DEC-TOTAL]", "déchets préparés en vue du réemploi", "waste prepared for reuse", "§16(c)(i)"),
    _part("DEC-PART-RECYCLAGE", "Part des déchets recyclés", "Share of waste recycled", "[DEC-RECYCLES] / [DEC-TOTAL]",
          "déchets recyclés", "waste recycled", "§16(c)(ii)"),
    _part("DEC-PART-AUTRE-VALO", "Part des déchets envoyés vers d'autres opérations de valorisation",
          "Share of waste sent to other recovery operations", "[DEC-AUTRE-VALO] / [DEC-TOTAL]",
          "déchets envoyés vers d'autres opérations de valorisation", "waste sent to other recovery operations", "§16(c)(iii)"),
    _part("DEC-PART-ELIMINES", "Part des déchets dirigés vers l'élimination", "Share of waste directed to disposal",
          "[DEC-ELIMINES] / [DEC-TOTAL]", "déchets dirigés vers l'élimination", "waste directed to disposal", "§16(d)"),
    _part("DEC-PART-ELIM-DANG", "Part des déchets dirigés vers l'élimination : dangereux",
          "Share of waste directed to disposal: hazardous", "[DEC-ELIMINES-DANG] / [DEC-TOTAL]",
          "déchets dangereux dirigés vers l'élimination", "hazardous waste directed to disposal", "§16(d)"),
    _part("DEC-PART-ELIM-NON-DANG", "Part des déchets dirigés vers l'élimination : non dangereux",
          "Share of waste directed to disposal: non-hazardous", "([DEC-ELIMINES] - [DEC-ELIMINES-DANG]) / [DEC-TOTAL]",
          "déchets non dangereux dirigés vers l'élimination (éliminés moins dangereux éliminés)",
          "non-hazardous waste directed to disposal (disposal minus hazardous disposal)", "§16(d)"),
    _part("DEC-PART-INCINERATION", "Part des déchets incinérés (élimination)", "Share of waste incinerated (disposal)",
          "[DEC-INCINERATION] / [DEC-TOTAL]", "déchets incinérés (élimination)", "waste incinerated (disposal)", "§16(d)(i)"),
    _part("DEC-PART-DECHARGE", "Part des déchets mis en décharge", "Share of waste sent to landfill", "[DEC-DECHARGE] / [DEC-TOTAL]",
          "déchets mis en décharge", "waste sent to landfill", "§16(d)(ii)"),
    _part("DEC-PART-AUTRE-ELIM", "Part des déchets envoyés vers d'autres opérations d'élimination",
          "Share of waste sent to other disposal operations", "[DEC-AUTRE-ELIM] / [DEC-TOTAL]",
          "déchets envoyés vers d'autres opérations d'élimination", "waste sent to other disposal operations", "§16(d)(iii)"),
    _part("DEC-PART-INCONNUE", "Part des déchets de destination finale inconnue", "Share of waste with unknown final destination",
          "[DEC-INCONNUE] / [DEC-TOTAL]", "déchets de destination finale inconnue", "waste with unknown final destination", "§16(e)"),
])

# Entrée progressive de l'ESRS 1 §126(a) (toutes les normes thématiques avant 2027 pour les petites entreprises de la
# première vague) : même phrase que dans G1, ajoutée à chaque KPI propre au modèle ; les KPI repris de la norme VS ou
# du catalogue ne la portent pas (une seule définition, qui se lirait aussi dans une installation VS seule).
KPIS = dict(L.avec_phase_in(KPIS.items(), L.PHASE_IN_G1))

REGLES = {  # nom fr : (gauche, opérateur, droite, (description fr, en), nom en)
    # les deux règles de la norme volontaire VS, reprises telles quelles (même nom, même définition)
    "Déchets recyclés ≤ déchets générés": REGLES_VS["Déchets recyclés ≤ déchets générés"],
    "Déchets préparés pour le réemploi ≤ déchets générés": REGLES_VS["Déchets préparés pour le réemploi ≤ déchets générés"],
    # « ≤ » et non « = » : un déchet généré pendant la période et encore stocké sur le site à la clôture n'a pas encore de
    # destination ; l'égalité donnait une fausse alerte
    "Déchets détournés + éliminés + destination inconnue ≤ déchets générés": (
        "[DEC-DETOURNES] + [DEC-ELIMINES] + [DEC-INCONNUE]", "<=", "[DEC-TOTAL]",
        ("Les déchets détournés, éliminés ou de destination inconnue font partie des déchets générés ; l'écart éventuel est "
         "celui des déchets encore stockés sur le site à la fin de la période.",
         "Waste diverted, directed to disposal or with an unknown destination is part of the waste generated; any difference is "
         "the waste still stored on the site at the end of the period."),
        "Waste diverted + disposed of + unknown destination ≤ waste generated"),
    "Déchets dangereux détournés ≤ déchets détournés": (
        "[DEC-DETOURNES-DANG]", "<=", "[DEC-DETOURNES]",
        ("Les déchets dangereux détournés de l'élimination font partie des déchets détournés.",
         "Hazardous waste diverted from disposal is part of the waste diverted."),
        "Hazardous waste diverted ≤ waste diverted"),
    "Déchets dangereux éliminés ≤ déchets éliminés": (
        "[DEC-ELIMINES-DANG]", "<=", "[DEC-ELIMINES]",
        ("Les déchets dangereux dirigés vers l'élimination font partie des déchets dirigés vers l'élimination.",
         "Hazardous waste directed to disposal is part of the waste directed to disposal."),
        "Hazardous waste directed to disposal ≤ waste directed to disposal"),
    "Déchets dangereux détournés + éliminés ≤ déchets dangereux": (
        "[DEC-DETOURNES-DANG] + [DEC-ELIMINES-DANG]", "<=", "[DEC-DANGEREUX]",
        ("Les déchets dangereux détournés ou éliminés font partie des déchets dangereux générés.",
         "Hazardous waste diverted or directed to disposal is part of the hazardous waste generated."),
        "Hazardous waste diverted + disposed of ≤ hazardous waste generated"),
    "Ressources secondaires ≤ poids des matières clés": (
        "[ECO-CIRC-SECONDAIRES]", "<=", "[ECO-CIRC-MATIERES-POIDS]",
        ("Les ressources secondaires utilisées font partie des matières clés.",
         "The secondary resources used are part of the key materials."),
        "Secondary resources ≤ weight of key materials"),
}

SOCLE = C.socle("ESRS_E5", "1.1", "2026-11-19", [
    ("E5_1", "E5-1 – Politiques relatives aux ressources et à l'économie circulaire",
     "E5-1 – Policies related to resource use and circular economy", [
         *C.arbre_gdr(PREFIXE, "E5-1", "P"), ("ECO-CIRC-ECOCONCEPTION", "E5-1 · 9")]),
    ("E5_2", "E5-2 – Actions et ressources relatives aux ressources et à l'économie circulaire",
     "E5-2 – Actions and resources related to resource use and circular economy", C.arbre_gdr(PREFIXE, "E5-2", "A")),
    ("E5_3", "E5-3 – Cibles relatives aux ressources et à l'économie circulaire",
     "E5-3 – Targets related to resource use and circular economy", C.arbre_gdr(PREFIXE, "E5-3", "T")),
    ("E5_4", "E5-4 – Entrées de ressources", "E5-4 – Resource inflows", [
        ("ECO-CIRC-MATIERES-DESC", "E5-4 · 13(a)"), ("ECO-CIRC-MATIERES-POIDS", "E5-4 · 13(b)"),
        ("ECO-CIRC-MATIERES-TAB", "E5-4 · 13(c)"), ("ECO-CIRC-SECONDAIRES", "E5-4 · 13(d)"),
        ("ECO-CIRC-PART-SECONDAIRES", "E5-4 · 13(d)")]),
    ("E5_5", "E5-5 – Sorties de ressources", "E5-5 – Resource outflows", [
        ("ECO-CIRC-DURABILITE", "E5-5 · 15(a)"), ("ECO-CIRC-REPARABILITE", "E5-5 · 15(b)"),
        ("ECO-CIRC-RECYCLABILITE", "E5-5 · 15(c)"), ("DEC-FLUX-DESC", "E5-5 · 16(a)"), ("DEC-TOTAL", "E5-5 · 16(b)"),
        ("DEC-REEMPLOI", "E5-5 · 16(c)(i)"), ("DEC-RECYCLES", "E5-5 · 16(c)(ii)"), ("DEC-AUTRE-VALO", "E5-5 · 16(c)(iii)"),
        ("DEC-DETOURNES", "E5-5 · 16(c)"), ("DEC-DETOURNES-DANG", "E5-5 · 16(c)"), ("DEC-INCINERATION", "E5-5 · 16(d)(i)"),
        ("DEC-DECHARGE", "E5-5 · 16(d)(ii)"), ("DEC-AUTRE-ELIM", "E5-5 · 16(d)(iii)"), ("DEC-ELIMINES", "E5-5 · 16(d)"),
        ("DEC-ELIMINES-DANG", "E5-5 · 16(d)"), ("DEC-DANGEREUX", "E5-5 · 16(c), (d) (contrôle des parts dangereuses)"), ("DEC-INCONNUE", "E5-5 · 16(e)"),
        ("DEC-RADIOACTIFS", "E5-5 · 17"),
        ("DEC-PART-DETOURNES", "E5-5 · 16(c)"), ("DEC-PART-DET-DANG", "E5-5 · 16(c)"), ("DEC-PART-DET-NON-DANG", "E5-5 · 16(c)"),
        ("DEC-PART-REEMPLOI", "E5-5 · 16(c)(i)"), ("DEC-PART-RECYCLAGE", "E5-5 · 16(c)(ii)"),
        ("DEC-PART-AUTRE-VALO", "E5-5 · 16(c)(iii)"), ("DEC-PART-ELIMINES", "E5-5 · 16(d)"),
        ("DEC-PART-ELIM-DANG", "E5-5 · 16(d)"), ("DEC-PART-ELIM-NON-DANG", "E5-5 · 16(d)"),
        ("DEC-PART-INCINERATION", "E5-5 · 16(d)(i)"), ("DEC-PART-DECHARGE", "E5-5 · 16(d)(ii)"),
        ("DEC-PART-AUTRE-ELIM", "E5-5 · 16(d)(iii)"), ("DEC-PART-INCONNUE", "E5-5 · 16(e)"),
        *C.arbre_gdr(PREFIXE, "E5-5", "M")]),
], regles=list(REGLES))
