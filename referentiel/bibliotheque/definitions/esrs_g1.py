"""ESRS G1 Conduite des affaires (ESRS révisées, règlement délégué (UE) 2026/1563) : modèle du lot E, construit sur l'exemple
ESRS E3 (méthode : note de conception de l'atelier, non publiée ; socle commun : _esrs_communs.py ; briques du lot :
_esrs_lot_e.py).

Inventaire : lignes « ESRS_G1 » de esrs_coverage.csv (23 points de la liste de l'EFRAG du 28/08/2026, plus GDR-M). Choix :

- politiques, actions et cibles : bloc commun des exigences générales de l'ESRS 2 (``bloc``), saisi une fois pour
  l'entreprise (niveau « haut ») ; G1-1 §7, G1-2 §9, G1-5 §15-16 et G1-6 §18(a) : textes rédigés et oui / non ; indicateurs :
  GDR-M (méthodes, évolutions) en deux textes ;
- G1-4 : condamnations pour corruption, KPI de la norme VS (B11 §43) repris tel quel (décisions pénales définitives, G1
  AR 5) ; sanctions administratives (G1 AR 5, deuxième phrase) : KPI nouveau ; total « condamnations et sanctions »
  calculé. Amendes : KPI GOV-AMENDES de la norme VS repris tel quel (le guide officiel de la VS, §141, et la G1 AR 6 ont
  la même définition : amendes versées au Trésor public et comptabilisées dans les états financiers de la période ; sa
  description dit désormais cette définition) ;
- G1-5 : montant total des contributions politiques directes et indirectes, en nature comprises (une déclaration par
  employeur : niveau « entité »), répartition par pays par l'arbre des organisations, par type de bénéficiaire en texte ;
- G1-6 : pratiques de paiement. Les délais de paiement standard sont saisis une fois pour l'entreprise ; la part des
  paiements conformes est calculée sur le nombre de factures payées (unité « factures » du socle commun), exacte à chaque
  niveau de l'arbre ; procédures judiciaires en cours : stock en fin de période. Les achats sont hors du périmètre du
  produit, mais la norme les demande au titre de la conduite des affaires : question posée au propriétaire du produit ;
- entrée progressive (ESRS 1 §126(a)) : une phrase par KPI.
"""
from referentiel.bibliotheque.outils import ZERO, ZERO_EN, kpi

from . import _esrs_communs as C
from . import _esrs_lot_e as L

SOURCE = C.SOURCE
COUVERTURE = C.COUVERTURE
UNITES = C.UNITES
TYPES_REPONSE = C.TYPES_REPONSE

PREFIXE = "GOV-CONDUITE"
SUJET = ("la conduite des affaires", "business conduct")
PHASE = L.PHASE_IN_G1
JURIDIQUE = ("Direction juridique, conformité, registre des décisions de justice.", "Legal department, compliance, register of court decisions.")
COMPTA = ("Comptabilité, direction juridique.", "Accounting, legal department.")


def _d(fr, en):
    """Description d'une donnée additionnée, avec la phrase « Saisir 0 s'il n'y en a pas »."""
    return fr + ZERO, en + ZERO_EN


_propres = L.avec_phase_in([
    # ------------------------------------------------------------------ G1-1 – politiques
    L.oui_non("GOV-POLIT-ANTICORRUPTION", "Politiques anticorruption conformes à la Convention des Nations unies",
              "Anti-corruption and anti-bribery policies consistent with the UN Convention",
              ("L'entreprise a-t-elle des politiques de lutte contre la corruption conformes à la Convention des Nations unies "
               "contre la corruption ? (ESRS G1-1 §7(a)). Corruption : la définition générique du glossaire des ESRS s'applique, "
               "pas celle d'une loi locale (G1 AR 1).",
               "Does the company have anti-corruption and anti-bribery policies consistent with the United Nations Convention "
               "against Corruption? (ESRS G1-1 §7(a)). Corruption and bribery: the generic definition of the ESRS glossary "
               "applies, not the one of a local law (G1 AR 1).")),
    L.oui_non("GOV-POLIT-LANCEURS", "Politiques de protection des lanceurs d'alerte", "Whistle-blower protection policies",
              ("L'entreprise a-t-elle des politiques de protection des lanceurs d'alerte ? (ESRS G1-1 §7(b)). Une entreprise "
               "soumise à la loi nationale qui transpose la directive (UE) 2019/1937, ou à une exigence équivalente, peut répondre "
               "Oui en disant qu'elle y est soumise (G1 AR 2).",
               "Does the company have policies on the protection of whistle-blowers? (ESRS G1-1 §7(b)). A company subject to the "
               "national law transposing Directive (EU) 2019/1937, or to an equivalent requirement, can answer Yes by stating "
               "that it is subject to it (G1 AR 2).")),
    L.texte("GOV-FONCTIONS-RISQUE", "Fonctions les plus exposées à la corruption", "Functions most at risk of corruption or bribery",
            ("Fonctions ou postes de l'entreprise les plus exposés à la corruption, du fait de leurs tâches et de leurs "
             "responsabilités : par exemple ceux qui travaillent dans des pays à risque élevé ou en lien avec des autorités "
             "publiques et des gouvernements (ESRS G1-1 §7(c), G1 AR 3).",
             "Functions or roles within the company that are most at risk of corruption or bribery because of their tasks and "
             "responsibilities: for example those operating in high-risk countries or interacting with public authorities and "
             "governments (ESRS G1-1 §7(c), G1 AR 3).")),
    # ------------------------------------------------------------------ G1-2 – actions : fournisseurs, corruption
    L.texte("GOV-FOURNIS-RELATIONS", "Gestion des relations avec les fournisseurs", "Management of relationships with suppliers",
            ("Comment l'entreprise gère ses relations avec ses fournisseurs (ESRS G1-2 §9(a)). Les trois points suivants ont "
             "chacun leur élément : prise en compte de la durabilité dans le choix, formation de l'équipe achats, dialogue avec "
             "les fournisseurs. Un renvoi au code de conduite des fournisseurs (ESRS S2-1 §12) est possible (G1 AR 4).",
             "How the company manages its relationships with suppliers (ESRS G1-2 §9(a)). The three points below each have their "
             "own item: sustainability in supplier selection, training of the procurement team, engagement with suppliers. A "
             "reference to the supplier code of conduct (ESRS S2-1 §12) is possible (G1 AR 4).")),
    L.texte("GOV-FOURNIS-SELECTION", "Durabilité dans le choix des fournisseurs", "Sustainability in the selection of suppliers",
            ("Seulement si l'entreprise tient compte de la performance de durabilité pour choisir ses fournisseurs : comment "
             "(ESRS G1-2 §9(a)(i)). Répondre N/A si elle n'en tient pas compte.",
             "Only if the company takes sustainability performance into account in selecting its suppliers: how it does so "
             "(ESRS G1-2 §9(a)(i)). Answer N/A if it does not.")),
    L.oui_non("GOV-ACHATS-FORMATION", "Formation à la durabilité de l'équipe achats", "Sustainability training of the procurement team",
              ("L'équipe achats reçoit-elle une formation à la durabilité ? (ESRS G1-2 §9(a)(ii)). Répondre Non s'il n'y en a pas. "
               "Les détails vont dans le texte « Gestion des relations avec les fournisseurs ».",
               "Does the procurement team receive training on sustainability? (ESRS G1-2 §9(a)(ii)). Answer No if there is none. "
               "Give the details in the text « Management of relationships with suppliers ».")),
    L.texte("GOV-FOURNIS-ENGAGEMENT", "Dialogue avec les fournisseurs sur leur performance de durabilité",
            "Engagement with suppliers on their sustainability performance",
            ("Comment l'entreprise dialogue avec ses fournisseurs pour améliorer leur performance de durabilité "
             "(ESRS G1-2 §9(a)(iii)).",
             "How the company engages with suppliers to improve their sustainability performance (ESRS G1-2 §9(a)(iii)).")),
    L.texte("GOV-CORRUPTION-PROCEDURES", "Procédures contre la corruption", "Procedures against corruption and bribery",
            ("Procédures de l'entreprise pour prévenir, détecter, instruire et traiter les soupçons ou les incidents de "
             "corruption (ESRS G1-2 §9(b)).",
             "The company's procedures to prevent, detect, investigate and respond to allegations or incidents related to "
             "corruption or bribery (ESRS G1-2 §9(b)).")),
    L.texte("GOV-CORRUPTION-FORMATION", "Formation anticorruption des fonctions exposées",
            "Anti-corruption training of functions at risk",
            ("Formation à la lutte contre la corruption donnée aux fonctions les plus exposées, y compris aux membres des "
             "organes d'administration, de direction et de surveillance (ESRS G1-2 §9(b)(i)).",
             "Anti-corruption and anti-bribery training given to the functions or roles most at risk, including the members of "
             "the administrative, management and supervisory bodies (ESRS G1-2 §9(b)(i)).")),
    L.texte("GOV-CORRUPTION-MANQUEMENTS", "Actions après des manquements aux règles anticorruption",
            "Actions taken on breaches of anti-corruption procedures",
            ("Actions menées pour traiter les manquements aux procédures et aux normes de lutte contre la corruption "
             "(ESRS G1-2 §9(b)(ii)). Écrire qu'il n'y a pas eu de manquement, le cas échéant.",
             "Any actions taken to address breaches in procedures and standards of anti-corruption and anti-bribery (ESRS G1-2 "
             "§9(b)(ii)). Write that there was no breach, if that is the case.")),
    # ------------------------------------------------------------------ G1-4 – condamnations, sanctions et amendes
    kpi("GOV-SANCTIONS-CORRUP", "Sanctions administratives pour corruption", "Administrative sanctions for corruption or bribery",
        "cas", niveau=C.ENTITE,
        description=_d("Nombre de décisions définitives rendues pendant la période par des autorités administratives ou de "
                       "régulation contre l'entreprise ou une personne pour des faits de corruption (ESRS G1-4 §12, G1 AR 5). Les "
                       "condamnations des tribunaux pénaux se comptent dans « Condamnations pour corruption ».",
                       "Number of final decisions issued during the period by administrative or regulatory authorities against the "
                       "company or an individual in respect of corruption or bribery (ESRS G1-4 §12, G1 AR 5). Convictions of "
                       "criminal courts are counted in « Convictions for corruption or bribery »."),
        source=JURIDIQUE),
    kpi("GOV-CONDAMN-SANCTIONS", "Condamnations et sanctions pour corruption", "Convictions and sanctions for corruption or bribery",
        "cas", "Somme", "Calculé", formule="[GOV-CORRUPTION] + [GOV-SANCTIONS-CORRUP]",
        description=("Calculé par l'outil : condamnations pénales définitives plus sanctions administratives définitives pour "
                     "corruption pendant la période (ESRS G1-4 §12, G1 AR 5).",
                     "Calculated by the tool: final criminal convictions plus final administrative sanctions for corruption or "
                     "bribery during the period (ESRS G1-4 §12, G1 AR 5).")),
    # ------------------------------------------------------------------ G1-5 – influence politique
    kpi("GOV-CONTRIBUTIONS-POLIT", "Contributions politiques financières et en nature", "Financial and in-kind political contributions",
        "€", niveau=C.ENTITE,
        description=_d("Valeur totale des contributions politiques financières et en nature faites pendant la période, "
                       "directement et indirectement (ESRS G1-5 §14). Contribution politique : soutien financier ou en nature "
                       "donné directement à des partis politiques, à leurs élus ou à des personnes qui se présentent à une "
                       "élection (dons, prêts, parrainages, avances, billets d'événements de collecte de fonds ; publicité, "
                       "locaux, impression, matériel, mandat ou emploi) (G1 AR 7). Indirecte : faite par un intermédiaire "
                       "(lobbyiste, association caritative) ou soutien à un groupe de réflexion ou à une organisation "
                       "professionnelle liés à un parti ou à une cause (G1 AR 8). Évaluer les contributions en nature à leur "
                       "valeur monétaire. La répartition par pays vient de l'arbre des organisations." + C.MONNAIE[0],
                       "Total monetary value of financial and in-kind political contributions made during the period, directly and "
                       "indirectly (ESRS G1-5 §14). Political contribution: financial or in-kind support given directly to "
                       "political parties, their elected representatives or persons seeking political office (donations, loans, "
                       "sponsorships, advance payments, tickets to fundraising events; advertising, use of facilities, printing, "
                       "equipment, board membership or employment) (G1 AR 7). Indirect: made through an intermediary (lobbyist, "
                       "charity) or support to a think tank or trade association linked to a party or cause (G1 AR 8). Value "
                       "in-kind contributions at their monetary value. The breakdown by country comes from the organisation "
                       "tree." + C.MONNAIE[1]),
        source=COMPTA),
    L.texte("GOV-CONTRIBUTIONS-DETAIL", "Contributions politiques par type de bénéficiaire", "Political contributions by type of recipient",
            ("Répartition des contributions politiques par type de bénéficiaire (parti, élu, candidat ; pour les contributions "
             "indirectes, intermédiaire, groupe de réflexion, organisation professionnelle) (ESRS G1-5 §14, G1 AR 7 et 8). "
             "Écrire les montants.",
             "Breakdown of the political contributions by type of recipient or beneficiary (party, elected representative, "
             "candidate; for indirect contributions, intermediary, think tank, trade association) (ESRS G1-5 §14, G1 AR 7 and "
             "8). Write the amounts.")),
    L.texte("GOV-LOBBYING", "Sujets et positions de l'activité de lobbying", "Main topics and positions of lobbying activities",
            ("Principaux sujets traités par les activités de lobbying de l'entreprise et principales positions défendues, avec "
             "l'explication du lien entre ces activités et ses impacts, risques et opportunités importants (ESRS G1-5 §15).",
             "Main issues covered by the company's lobbying activities and main positions taken, with an explanation of how "
             "these activities interact with its material impacts, risks and opportunities (ESRS G1-5 §15).")),
    L.texte("GOV-NOMINATIONS-PUBLIC", "Membres des organes issus de l'administration publique",
            "Members of the bodies appointed from public administration",
            ("Nominations faites pendant la période de membres des organes d'administration, de direction et de surveillance "
             "qui ont occupé un poste comparable dans l'administration publique (régulateurs compris) pendant les deux années "
             "précédentes. Pour juger si un poste est comparable, tenir compte du niveau de responsabilité et de l'étendue des "
             "activités (ESRS G1-5 §16, G1 AR 9). Écrire qu'il n'y en a pas, le cas échéant.",
             "Appointments during the period of members of the administrative, management and supervisory bodies who held a "
             "comparable position in public administration (regulators included) in the two preceding years. To judge whether a "
             "position is comparable, consider the level of responsibility and the scope of the activities (ESRS G1-5 §16, G1 AR "
             "9). Write that there were none, if that is the case.")),
    # ------------------------------------------------------------------ G1-6 – pratiques de paiement
    L.texte("GOV-PAIEMENT-CONDITIONS", "Conditions de paiement standard par catégorie de fournisseurs",
            "Standard payment terms by main category of suppliers",
            ("Description des conditions de paiement standard de l'entreprise, en nombre de jours, par grande catégorie de "
             "fournisseurs ; préciser celles qui s'appliquent aux petites et moyennes entreprises (PME) si elles diffèrent "
             "(ESRS G1-6 §18(a)).",
             "Description of the company's standard payment terms, in number of days, by main category of suppliers; specify "
             "those that apply to small and medium-sized undertakings (SMEs) if they differ (ESRS G1-6 §18(a)).")),
    kpi("GOV-PAIEMENT-JOURS", "Conditions de paiement standard, en jours", "Standard payment terms, in days", "jours", "Aucune",
        temps="derniere", niveau=C.HAUT,
        description=("Nombre de jours des conditions de paiement standard appliquées aux fournisseurs (ESRS G1-6 §18(a)). Si les "
                     "conditions diffèrent selon les catégories, saisir celles de la catégorie principale et décrire les autres "
                     "dans le texte « Conditions de paiement standard par catégorie de fournisseurs ». Ce n'est pas le délai "
                     "réel moyen de paiement.",
                     "Number of days of the standard payment terms applied to suppliers (ESRS G1-6 §18(a)). If the terms differ by "
                     "category, enter those of the main category and describe the others in the text « Standard payment terms by "
                     "main category of suppliers ». It is not the actual average payment time."),
        source=("Conditions générales d'achat, politique de paiement, comptabilité fournisseurs.",
                "General terms of purchase, payment policy, accounts payable.")),
    kpi("GOV-PAIEMENT-JOURS-PME", "Conditions de paiement standard des PME, en jours", "Standard payment terms for SME suppliers, in days",
        "jours", "Aucune", temps="derniere", niveau=C.HAUT,
        description=("Seulement si les conditions de paiement standard des PME fournisseurs diffèrent de celles des autres "
                     "fournisseurs : nombre de jours (ESRS G1-6 §18(a)). Répondre N/A si elles sont les mêmes.",
                     "Only if the standard payment terms of SME suppliers differ from those of other suppliers: number of days "
                     "(ESRS G1-6 §18(a)). Answer N/A if they are the same."),
        source=("Conditions générales d'achat, politique de paiement, comptabilité fournisseurs.",
                "General terms of purchase, payment policy, accounts payable.")),
    kpi("GOV-FACTURES", "Factures fournisseurs payées", "Supplier invoices paid", "factures", niveau=C.ENTITE,
        description=_d("Nombre de factures de fournisseurs payées pendant la période. Avec « Factures payées dans les délais », "
                       "il donne à l'outil la part des paiements conformes aux conditions standard (ESRS G1-6 §18(b)). La norme ne dit pas si la part se calcule sur le nombre ou sur la valeur des paiements ; l'outil "
                       "donne les deux : en nombre de factures ici, en valeur avec les montants payés.",
                       "Number of supplier invoices paid during the period. Together with « Invoices paid within the standard "
                       "terms », it gives the tool the share of payments aligned with the standard terms (ESRS G1-6 §18(b)). The "
                       "standard does not say whether the share is based on the number or on the value of the payments; the tool "
                       "gives both: by number of invoices here, by value with the amounts paid."),
        source=("Comptabilité fournisseurs : liste des factures payées de la période.",
                "Accounts payable: list of the invoices paid in the period.")),
    kpi("GOV-FACTURES-A-TEMPS", "Factures payées dans les délais", "Invoices paid within the standard terms", "factures",
        niveau=C.ENTITE,
        description=_d("Parmi les factures payées pendant la période, nombre de celles payées dans les conditions de paiement "
                       "standard de l'entreprise (ESRS G1-6 §18(b)).",
                       "Among the invoices paid during the period, the number paid within the company's standard payment terms "
                       "(ESRS G1-6 §18(b))."),
        source=("Comptabilité fournisseurs : date d'échéance et date de paiement de chaque facture.",
                "Accounts payable: due date and payment date of each invoice.")),
    kpi("GOV-PAIEMENT-PART-CONFORME", "Part des paiements conformes aux conditions standard, en nombre de factures",
        "Share of payments aligned with the standard terms, by number of invoices", "", "Formule", "Calculé", "Pourcentage",
        "[GOV-FACTURES-A-TEMPS] / [GOV-FACTURES]", decimales=1,
        description=("Calculée par l'outil : factures payées dans les délais rapportées aux factures payées (ESRS G1-6 §18(b), "
                     "G1 AR 10). Si les retards de paiement aux PME sont un sujet important pour l'entreprise, ajouter un "
                     "indicateur propre à l'entreprise (ESRS 1 §11).",
                     "Calculated by the tool: invoices paid within the standard terms divided by invoices paid (ESRS G1-6 §18(b), "
                     "G1 AR 10). If late payment to SMEs is a material topic for the company, add an entity-specific metric "
                     "(ESRS 1 §11).")),
    kpi("GOV-FACTURES-MONTANT", "Montant des factures fournisseurs payées", "Amount of supplier invoices paid", "€",
        niveau=C.ENTITE,
        description=_d("Montant total des factures de fournisseurs payées pendant la période. Avec « Montant des factures payées "
                       "dans les délais », il donne à l'outil la part des paiements conformes aux conditions standard en valeur "
                       "(ESRS G1-6 §18(b))." + C.MONNAIE[0],
                       "Total amount of the supplier invoices paid during the period. Together with « Amount of invoices paid "
                       "within the standard terms », it gives the tool the share of payments aligned with the standard terms by "
                       "value (ESRS G1-6 §18(b))." + C.MONNAIE[1]),
        source=("Comptabilité fournisseurs : montants des factures payées de la période.",
                "Accounts payable: amounts of the invoices paid in the period.")),
    kpi("GOV-FACTURES-MONTANT-A-TEMPS", "Montant des factures payées dans les délais",
        "Amount of invoices paid within the standard terms", "€", niveau=C.ENTITE,
        description=_d("Parmi les factures payées pendant la période, montant de celles payées dans les conditions de paiement "
                       "standard de l'entreprise (ESRS G1-6 §18(b))." + C.MONNAIE[0],
                       "Among the invoices paid during the period, the amount of those paid within the company's standard "
                       "payment terms (ESRS G1-6 §18(b))." + C.MONNAIE[1]),
        source=("Comptabilité fournisseurs : date d'échéance, date et montant de chaque paiement.",
                "Accounts payable: due date, payment date and amount of each payment.")),
    kpi("GOV-PAIEMENT-PART-CONFORME-VAL", "Part des paiements conformes aux conditions standard, en valeur",
        "Share of payments aligned with the standard terms, by value", "", "Formule", "Calculé", "Pourcentage",
        "[GOV-FACTURES-MONTANT-A-TEMPS] / [GOV-FACTURES-MONTANT]", decimales=1,
        description=("Calculée par l'outil : montant des factures payées dans les délais rapporté au montant des factures payées "
                     "(ESRS G1-6 §18(b)). La norme ne dit pas si la part se mesure en nombre ou en valeur : l'outil donne les "
                     "deux, l'entreprise dit dans ses méthodes laquelle elle publie, ou publie les deux.",
                     "Calculated by the tool: amount of the invoices paid within the standard terms divided by the amount of the "
                     "invoices paid (ESRS G1-6 §18(b)). The standard does not say whether the share is measured by number or by "
                     "value: the tool gives both, the company says in its methods which one it discloses, or discloses both.")),
    kpi("GOV-PAIEMENT-CONTENTIEUX", "Procédures judiciaires en cours pour retard de paiement",
        "Outstanding legal proceedings for late payment", "cas", temps="derniere", niveau=C.ENTITE,
        description=_d("Nombre de procédures judiciaires en cours à la fin de la période pour des retards de paiement "
                       "(ESRS G1-6 §18(c)).",
                       "Number of legal proceedings outstanding at the end of the period for late payments (ESRS G1-6 §18(c))."),
        source=JURIDIQUE),
], PHASE)

KPIS = dict([
    *L.bloc(PREFIXE, SUJET, PHASE, social=False, indicateurs=True),
    *_propres,
])

REGLES = {  # nom fr : (gauche, opérateur, droite, (description fr, en), nom en)
    "Factures payées dans les délais ≤ factures payées": (
        "[GOV-FACTURES-A-TEMPS]", "<=", "[GOV-FACTURES]",
        ("Les factures payées dans les délais font partie des factures payées.",
         "The invoices paid within the standard terms are part of the invoices paid."),
        "Invoices paid within the terms ≤ invoices paid"),
    "Montant payé dans les délais ≤ montant payé": (
        "[GOV-FACTURES-MONTANT-A-TEMPS]", "<=", "[GOV-FACTURES-MONTANT]",
        ("Le montant des factures payées dans les délais fait partie du montant des factures payées.",
         "The amount of the invoices paid within the standard terms is part of the amount of the invoices paid."),
        "Amount paid within the terms ≤ amount paid"),
}

SOCLE = C.socle("ESRS_G1", "1.1", "2026-11-19", [
    ("G1_1", "G1-1 – Politiques relatives à la conduite des affaires", "G1-1 – Policies related to business conduct", [
        *C.arbre_gdr(PREFIXE, "G1-1", "P"),
        ("GOV-POLIT-ANTICORRUPTION", "G1-1 · 7(a)"), ("GOV-POLIT-LANCEURS", "G1-1 · 7(b)"), ("GOV-FONCTIONS-RISQUE", "G1-1 · 7(c)")]),
    ("G1_2", "G1-2 – Actions relatives à la conduite des affaires", "G1-2 – Actions related to business conduct", [
        *C.arbre_gdr(PREFIXE, "G1-2", "A"),
        ("GOV-FOURNIS-RELATIONS", "G1-2 · 9(a)"), ("GOV-FOURNIS-SELECTION", "G1-2 · 9(a)(i)"), ("GOV-ACHATS-FORMATION", "G1-2 · 9(a)(ii)"),
        ("GOV-FOURNIS-ENGAGEMENT", "G1-2 · 9(a)(iii)"), ("GOV-CORRUPTION-PROCEDURES", "G1-2 · 9(b)"),
        ("GOV-CORRUPTION-FORMATION", "G1-2 · 9(b)(i)"), ("GOV-CORRUPTION-MANQUEMENTS", "G1-2 · 9(b)(ii)")]),
    ("G1_3", "G1-3 – Cibles relatives à la conduite des affaires", "G1-3 – Targets related to business conduct",
     C.arbre_gdr(PREFIXE, "G1-3", "T")),
    ("G1_4", "G1-4 – Corruption : condamnations, sanctions et amendes", "G1-4 – Corruption or bribery: convictions, sanctions and fines", [
        ("GOV-CONDAMN-SANCTIONS", "G1-4 · 12"), ("GOV-CORRUPTION", "G1-4 · 12"), ("GOV-SANCTIONS-CORRUP", "G1-4 · 12"),
        ("GOV-AMENDES", "G1-4 · 12")]),
    ("G1_5", "G1-5 – Influence politique et lobbying", "G1-5 – Political influence, including lobbying activities", [
        ("GOV-CONTRIBUTIONS-POLIT", "G1-5 · 14"), ("GOV-CONTRIBUTIONS-DETAIL", "G1-5 · 14"), ("GOV-LOBBYING", "G1-5 · 15"),
        ("GOV-NOMINATIONS-PUBLIC", "G1-5 · 16")]),
    ("G1_6", "G1-6 – Pratiques de paiement", "G1-6 – Payment practices", [
        ("GOV-PAIEMENT-CONDITIONS", "G1-6 · 18(a)"), ("GOV-PAIEMENT-JOURS", "G1-6 · 18(a)"), ("GOV-PAIEMENT-JOURS-PME", "G1-6 · 18(a)"),
        ("GOV-PAIEMENT-PART-CONFORME", "G1-6 · 18(b)"), ("GOV-FACTURES", "G1-6 · 18(b)"), ("GOV-FACTURES-A-TEMPS", "G1-6 · 18(b)"),
        ("GOV-PAIEMENT-PART-CONFORME-VAL", "G1-6 · 18(b)"), ("GOV-FACTURES-MONTANT", "G1-6 · 18(b)"),
        ("GOV-FACTURES-MONTANT-A-TEMPS", "G1-6 · 18(b)"),
        ("GOV-PAIEMENT-CONTENTIEUX", "G1-6 · 18(c)")]),
    ("G1_M", "G1-4 à G1-6 – Méthodes et évolutions des indicateurs", "G1-4 to G1-6 – Methods and changes of the metrics",
     C.arbre_gdr(PREFIXE, "G1-4 à G1-6", "M")),
], regles=["Factures payées dans les délais ≤ factures payées", "Montant payé dans les délais ≤ montant payé"])
