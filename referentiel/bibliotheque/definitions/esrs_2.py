"""ESRS 2 Informations générales (ESRS révisées, règlement délégué (UE) 2026/1563) : le modèle que toute entreprise installe,
avec les modèles de ses sujets importants (méthode : note de conception de l'atelier, non publiée ; socle commun :
_esrs_communs.py ; exemple suivi : esrs_e3.py).

Inventaire : lignes « ESRS_2 » de esrs_coverage.csv (94 points des onglets « ESRS 2 » et « ESRS 2 GDR » de la liste de
l'EFRAG du 28/08/2026, plus deux exigences de l'ESRS 1 absentes de la liste : §83 et §123). Choix :

- presque tout est rédigé (BP, GOV, SBM, IRO) : un texte par point de la liste, saisi une fois pour l'entreprise (niveau
  « haut ») ; un « si » de la norme est un oui / non (« whether ») ; une date est un texte « AAAA-MM-JJ » (l'outil n'a pas
  de format date) ; les effets financiers sont rédigés, montants compris (note explicative de l'EFRAG §47) ;
- composition de l'organe (GOV-1 §12(a)) : femmes et hommes membres repris de la norme volontaire VS (C9, même
  définition), membres indépendants saisis ; part des indépendants et rapport femmes / hommes (AR 6) calculés ;
- SBM-1 §20(d) : un oui / non par secteur (le KPI unique GOV-REV-SECTEURS de la VS ne dit pas lequel) et les revenus de
  la VS (C8 · 63, même texte que l'ESRS 2) ;
- exigences générales GDR des sujets propres à l'entreprise (ESRS 2 §40, ESRS 1 §11) : bloc commun ``bloc_gdr`` (préfixe
  GEN-SPEC, prise en compte des parties prenantes comprise) et tableau des indicateurs propres ; chaque modèle de sujet
  (E1 à G1) applique les mêmes exigences avec son propre bloc ;
- politique des droits humains (GDR-P §43) : un oui / non, un oui / non par groupe de parties prenantes couvert (pas
  de liste à choix multiples) et un texte pour les informations du §42 ;
- ESRS 1 §83 (informations comparatives) : automatique, l'outil garde les valeurs N-1 ; ESRS 1 §123 (efforts pour obtenir
  les informations de la chaîne de valeur, trois premières années) : un texte.
"""
from referentiel.bibliotheque.outils import kpi

from . import _esrs_communs as C

SOURCE = C.SOURCE
COUVERTURE = C.COUVERTURE
UNITES = C.UNITES
TYPES_REPONSE = C.TYPES_REPONSE

PREFIXE = "GEN-SPEC"
ORGANE = ("Procès-verbaux et règlement intérieur de l'organe d'administration, de direction ou de surveillance, rapport sur "
          "le gouvernement d'entreprise.",
          "Minutes and terms of reference of the administrative, management or supervisory body, corporate governance report.")
MATERIALITE = ("Dossier de l'analyse de double matérialité (méthode, résultats, validation).",
               "File of the double materiality assessment (method, results, approval).")


def texte(code, nom, description, source=""):
    """Texte rédigé donné une fois pour l'entreprise. ``nom`` et ``description`` : couples (fr, en)."""
    return kpi(code, nom[0], nom[1], "", "Aucune", reponse="Texte", niveau=C.HAUT, description=description, source=source)


def oui_non(code, nom, description, source=""):
    """Oui / non donné une fois pour l'entreprise (un « whether » de la norme)."""
    return kpi(code, nom[0], nom[1], "", "Décompte", reponse="OuiNon", niveau=C.HAUT, description=description, source=source)


_SI_PROGRESSIF = ("Seulement si l'entreprise omet tous les points d'une ou plusieurs normes thématiques au titre des mesures "
                  "transitoires de l'ESRS 1 (§125(a), §126(a) ou §127(a)) ; répondre N/A sinon. ",
                  "Only if the company omits all disclosures of one or more topical standards under the phase-in provisions "
                  "of ESRS 1 (§125(a), §126(a) or §127(a)); answer N/A otherwise. ")


def progressif(code, nom, fr, en, oui=False):
    """Point du BP-2 (sujets omis au titre des mesures transitoires) : la condition commune, puis le texte propre."""
    return (oui_non if oui else texte)(code, nom, (_SI_PROGRESSIF[0] + fr, _SI_PROGRESSIF[1] + en))


_PHASE_EFFETS = (" Mesure transitoire (ESRS 1 §125(b)-(c), §126(b)-(c), §127(b)-(c)) : une entreprise de la première vague "
                 "peut omettre ces informations pour les exercices antérieurs à 2028 (informations quantitatives : antérieurs "
                 "à 2030) ; une autre entreprise, pour ses deux premiers exercices (informations quantitatives : quatre "
                 "premiers).",
                 " Phase-in (ESRS 1 §125(b)-(c), §126(b)-(c), §127(b)-(c)): a wave-one company may omit this information "
                 "for financial years before 2028 (quantitative information: before 2030); another company, for its first "
                 "two financial years (quantitative information: first four).")


KPIS = dict([
    # ------------------------------------------------------------------ BP-1 – base de préparation
    texte("GEN-PERIMETRE-ECART", ("Écart avec le périmètre des comptes consolidés : description et raisons",
                                  "Difference from the boundary of the consolidated financial statements: description and reasons"),
          ("Seulement si le périmètre des activités propres retenu dans l'état de durabilité diffère de celui des états "
           "financiers consolidés : décrire l'écart et ses raisons, par exemple une filiale exclue de la consolidation parce "
           "qu'elle n'est pas significative sur le plan financier (ESRS 2 §4(a), AR 1). Répondre N/A sinon.",
           "Only if the boundary of the own operations used in the sustainability statement differs from the one of the "
           "consolidated financial statements: describe the difference and its reasons, for example a subsidiary left out of "
           "consolidation because it is not financially material (ESRS 2 §4(a), AR 1). Answer N/A otherwise.")),
    texte("GEN-CHAINE-VALEUR", ("Couverture de la chaîne de valeur amont et aval", "Coverage of the upstream and downstream value chain"),
          ("Vue d'ensemble de la mesure dans laquelle l'état de durabilité couvre la chaîne de valeur amont et aval de "
           "l'entreprise (ESRS 2 §4(b)).",
           "Overview of the extent to which the sustainability statement covers the company's upstream and downstream value "
           "chain (ESRS 2 §4(b)).")),
    kpi("GEN-CONFORMITE-ESRS", "Conformité aux ESRS et version appliquée", "Compliance with the ESRS and version applied", "",
        "Décompte", reponse="ESRS-VERSION", niveau=C.HAUT,
        description=("Indiquer que l'état de durabilité est établi selon les ESRS applicables à la fin "
                     "de la période de reporting, et jeu de normes appliqué (ESRS 2 §5). Pour un exercice ouvert en 2026, le "
                     "règlement délégué (UE) 2026/1563 laisse le choix entre le premier jeu des ESRS, les ESRS révisées, ou le "
                     "premier jeu avec certains allègements des ESRS révisées, et demande de dire la version appliquée "
                     "(article 2) ; les ESRS révisées s'appliquent aux exercices ouverts à partir du 1er janvier 2027 "
                     "(article 3).",
                     "Statement that the sustainability statement is prepared in accordance with the ESRS applicable at the "
                     "end of the reporting period, and set of standards applied (ESRS 2 §5). For a financial year starting in "
                     "2026, Delegated Regulation (EU) 2026/1563 allows the first set of ESRS, the revised ESRS, or the first set "
                     "with certain reliefs of the revised ESRS, and asks to state the version applied (Article 2); the revised "
                     "ESRS apply to financial years starting on or after 1 January 2027 (Article 3).")),
    texte("GEN-DISPOSITIONS", ("Allègements, options et dispositions particulières de l'ESRS 1 appliqués",
                               "Reliefs, options and specific provisions of ESRS 1 applied"),
          ("Liste des allègements, options ou dispositions particulières de l'ESRS 1 que l'entreprise applique (ESRS 2 §6). "
           "Cas à examiner (AR 2) : acquisitions et cessions ; autres horizons de temps ; changements de préparation ou de "
           "présentation ; informations comparatives ajustées ; jugement important et incertitude importante ; omission "
           "d'informations ; activités exclues du calcul d'un indicateur ; périmètre partiel d'un indicateur faute de données "
           "fiables ; activités conjointes exclues des indicateurs environnementaux ; limites dues à un coût ou un effort "
           "excessif ; événements après la fin de la période ; erreurs des périodes antérieures. Répondre N/A si aucun n'est "
           "appliqué.",
           "List of the reliefs, options or specific provisions of ESRS 1 that the company applies (ESRS 2 §6). Cases to "
           "consider (AR 2): acquisitions and disposals; other time horizons; changes in preparation or presentation; adjusted "
           "comparative information; material judgement and significant uncertainty; omission of information; activities "
           "excluded from the calculation of a metric; partial boundary of a metric for lack of reliable data; joint "
           "operations excluded from environmental metrics; limitations due to undue cost or effort; events after the end of "
           "the period; prior-period errors. Answer N/A if none is applied.")),
    texte("GEN-DISPOSITIONS-INFOS", ("Informations exigées par les allègements et dispositions appliqués",
                                     "Information required by the reliefs and provisions applied"),
          ("Pour chaque allègement, option ou disposition particulière appliqué, les informations que l'ESRS 1 demande avec "
           "lui (ESRS 2 §6). Elles peuvent aussi être données à côté de l'information concernée (AR 2) : dire alors où. "
           "Répondre N/A si aucun n'est appliqué.",
           "For each relief, option or specific provision applied, the information that ESRS 1 requires with it (ESRS 2 §6). "
           "It can also be given next to the disclosure concerned (AR 2): then say where. Answer N/A if none is applied.")),
    texte("GEN-LIENS-ETATS-FIN", ("Liens avec les états financiers et différences d'hypothèses",
                                  "Connectivity with the financial statements and differences in assumptions"),
          ("Pour les montants qui figurent aussi dans les états financiers : le renvoi aux états financiers (ESRS 1 §114) ; "
           "pour les montants qui en sont un regroupement ou une partie : comment ils se rattachent aux montants les plus "
           "proches des états financiers (ESRS 1 §115) ; et les différences importantes entre les hypothèses de l'"
           "état de durabilité et celles des états financiers (ESRS 1 §116). Répondre N/A s'il n'y en a "
           "pas.",
           "For the amounts also presented in the financial statements: the cross-reference to the financial statements "
           "(ESRS 1 §114); for the amounts that are an aggregation or part of them: how they relate to the most relevant "
           "amounts of the financial statements (ESRS 1 §115); and any significant differences between the assumptions of "
           "the sustainability statement and those of the financial statements (ESRS 1 §116). Answer N/A if there are none."),
          ("Comptabilité, états financiers.", "Accounting, financial statements.")),
    # ------------------------------------------------------------------ BP-2 – mesures transitoires
    progressif("GEN-PROGRESSIF-IRO", ("Mesures transitoires : matérialité des sujets omis", "Phase-in: materiality of the topics omitted"),
               "Pour chaque sujet omis, dire si ses impacts, risques et opportunités ont été jugés importants par l'analyse "
               "de matérialité, et lesquels (ESRS 2 §8).",
               "For each topic omitted, say whether its impacts, risks and opportunities were assessed as material by the "
               "materiality assessment, and which ones (ESRS 2 §8)."),
    progressif("GEN-PROGRESSIF-SUJETS", ("Mesures transitoires : sujets importants omis", "Phase-in: material topics omitted"),
               "Sujets ou sous-sujets jugés importants dont les informations sont omises (ESRS 2 §9(a)).",
               "Topics or sub-topics assessed as material whose disclosures are omitted (ESRS 2 §9(a))."),
    progressif("GEN-PROGRESSIF-STRATEGIE", ("Mesures transitoires : impacts des sujets omis dans la stratégie",
                                            "Phase-in: impacts of the topics omitted in the strategy"),
               "Pour chaque sujet ou sous-sujet important omis, brève description de la façon dont le modèle d'affaires et "
               "la stratégie tiennent compte de ses impacts (ESRS 2 §9(a)).",
               "For each material topic or sub-topic omitted, short description of how the business model and the strategy "
               "take account of its impacts (ESRS 2 §9(a))."),
    progressif("GEN-PROGRESSIF-CIBLES", ("Mesures transitoires : cibles datées et progrès sur les sujets omis",
                                         "Phase-in: time-bound targets and progress on the topics omitted"),
               "Brève description des cibles datées fixées sur ces sujets et des progrès faits pour les atteindre (ESRS 2 "
               "§9(b)).",
               "Short description of the time-bound targets set on these topics and of the progress made towards them (ESRS 2 "
               "§9(b))."),
    progressif("GEN-PROGRESSIF-BIO-SCIENCE", ("Mesures transitoires : cibles sur la biodiversité fondées sur la science",
                                              "Phase-in: science-based biodiversity targets"),
               "Les cibles sur la biodiversité et les écosystèmes sont-elles fondées sur des preuves scientifiques "
               "concluantes (ESRS 2 §9(b)) ? Répondre N/A si la biodiversité n'est pas un sujet important omis ou n'a pas de "
               "cible.",
               "Are the targets on biodiversity and ecosystems based on conclusive scientific evidence (ESRS 2 §9(b))? Answer "
               "N/A if biodiversity is not a material topic omitted or has no target.", oui=True),
    progressif("GEN-PROGRESSIF-POLITIQUES", ("Mesures transitoires : politiques sur les sujets omis",
                                             "Phase-in: policies on the topics omitted"),
               "Brève description des politiques sur ces sujets (ESRS 2 §9(c)).",
               "Short description of the policies on these topics (ESRS 2 §9(c))."),
    progressif("GEN-PROGRESSIF-ACTIONS", ("Mesures transitoires : actions sur les sujets omis et leurs résultats",
                                          "Phase-in: actions on the topics omitted and their results"),
               "Brève description des actions menées pour repérer, suivre, prévenir, atténuer, faire cesser, réduire ou "
               "réparer les impacts négatifs réels ou potentiels de ces sujets, et de leurs résultats (ESRS 2 §9(d)).",
               "Short description of the actions taken to identify, monitor, prevent, mitigate, bring to an end, minimise or "
               "remediate the actual or potential negative impacts of these topics, and of their results (ESRS 2 §9(d))."),
    progressif("GEN-PROGRESSIF-INDICATEURS", ("Mesures transitoires : indicateurs sur les sujets omis",
                                              "Phase-in: metrics on the topics omitted"),
               "Indicateurs pertinents pour ces sujets, avec leurs valeurs (ESRS 2 §9(e)).",
               "Metrics relevant to these topics, with their values (ESRS 2 §9(e))."),
    oui_non("GEN-PROGRESSIF-OMIS", ("Autres informations omises au titre des mesures transitoires",
                                    "Other information omitted under the phase-in provisions"),
            ("L'entreprise omet-elle des informations au titre des autres mesures transitoires de l'ESRS 1 (§125(b)-(e), "
             "§126(b)-(e), §127(b)-(e) : effets financiers attendus, substances préoccupantes et extrêmement préoccupantes) ? "
             "La norme demande de le dire (ESRS 2 §10). Si oui, dire lesquelles dans la partie générale de l'état de durabilité ou dans "
             "l'index des exigences (AR 4). Le §10 ne vise que les points (b) à (e) ; les allègements propres "
             "à l'ESRS S1 (§125(f), §126(f), §127(f) : S1-6, S1-7 hors EEE, S1-10 à S1-12, S1-13 §37(d)-(e) et non-salariés, S1-14) "
             "se signalent de la même façon s'ils sont utilisés.",
             "Does the company omit information under the other phase-in provisions of ESRS 1 (§125(b)-(e), §126(b)-(e), "
             "§127(b)-(e): anticipated financial effects, substances of concern and of very high concern)? The standard asks to "
             "say so (ESRS 2 §10). If yes, say which in the general part of the statement or in the content index (AR 4). "
             "Paragraph 10 covers points (b) to (e) only; the reliefs specific to ESRS S1 (§125(f), §126(f), §127(f): S1-6, "
             "S1-7 outside the EEA, S1-10 to S1-12, S1-13 §37(d)-(e) and non-employees, S1-14) are reported in the same way "
             "if they are used.")),
    # ------------------------------------------------------------------ GOV-1 – rôle des organes
    kpi("GOV-CA-INDEPENDANTS", "Membres indépendants de l'organe de gouvernance", "Independent members of the governance body",
        "personnes", niveau=C.HAUT, temps="derniere",
        description=("Membres indépendants du conseil (organe d'administration ou de surveillance) en fin de période, "
                     "comptés parmi tous les membres de l'organe (ESRS 2 §12(a)).",
                     "Independent members of the board (administrative or supervisory body) at period end, counted among all "
                     "the members of the body (ESRS 2 §12(a))."),
        source=ORGANE),
    kpi("GOV-CA-AUTRES", "Membres de l'organe de gouvernance d'un autre genre ou au genre non déclaré",
        "Members of the governance body of another gender or whose gender is not reported", "personnes", niveau=C.HAUT,
        temps="derniere",
        description=("Membres du conseil (organe d'administration ou de surveillance) en fin de période qui ne sont comptés ni "
                     "parmi les femmes ni parmi les hommes : autre genre, ou genre non déclaré (ESRS 2 §12(a)). Saisir 0 s'il "
                     "n'y en a pas ; N/A compte aussi comme 0 dans le nombre de membres.",
                     "Members of the board (administrative or supervisory body) at period end who are counted neither among "
                     "the women nor among the men: another gender, or gender not reported (ESRS 2 §12(a)). Enter 0 if there "
                     "is none; N/A also counts as 0 in the number of members."),
        source=ORGANE),
    kpi("GOV-CA-MEMBRES", "Membres de l'organe de gouvernance, tous genres", "Members of the governance body, all genders",
        "personnes", "Somme", "Calculé", formule="[GOV-CA-FEMMES] + [GOV-CA-HOMMES] + [GOV-CA-AUTRES]",
        description=("Calculé par l'outil : femmes, hommes, et membres d'un autre genre ou au genre non déclaré, en fin de "
                     "période ; un nombre N/A d'autres membres compte comme 0. Dénominateur des parts du §12(a) (ESRS 2 "
                     "§12(a)).",
                     "Calculated by the tool: women, men, and members of another gender or whose gender is not reported, at "
                     "period end; an N/A number of other members counts as 0. Denominator of the shares of §12(a) (ESRS 2 "
                     "§12(a)).")),
    kpi("GOV-CA-PART-INDEP", "Part des membres indépendants de l'organe de gouvernance",
        "Share of independent members of the governance body", "", "Formule", "Calculé", reponse="Pourcentage",
        formule="[GOV-CA-INDEPENDANTS] / [GOV-CA-MEMBRES]",
        description=("Calculée par l'outil : membres indépendants divisés par tous les membres de l'organe (femmes, hommes, "
                     "autre genre ou genre non déclaré) en fin de période (ESRS 2 §12(a)).",
                     "Calculated by the tool: independent members divided by all the members of the body (women, men, another "
                     "gender or gender not reported) at period end (ESRS 2 §12(a)).")),
    kpi("GOV-CA-RATIO-FH", "Mixité de l'organe de gouvernance (rapport femmes / hommes)",
        "Gender diversity of the governance body (ratio of women to men)", "", "Formule", "Calculé", reponse="Pourcentage",
        formule="[GOV-CA-FEMMES] / [GOV-CA-HOMMES]",
        description=("Calculé par l'outil : nombre de femmes divisé par le nombre d'hommes membres de l'organe en fin de "
                     "période, comme le demande l'AR 6 (ESRS 2 §12(a)). 50 % = une femme pour deux hommes. Ce rapport ne compte "
                     "que les femmes et les hommes ; les membres d'un autre genre ou au genre non déclaré n'y entrent pas.",
                     "Calculated by the tool: number of female members divided by the number of male members of the body at "
                     "period end, as AR 6 requires (ESRS 2 §12(a)). 50% = one woman for two men. This ratio counts women and "
                     "men only; members of another gender or whose gender is not reported are not in it.")),
] + [
    kpi(f"GOV-CA-PART-{suffixe}", f"Part des {fr} dans l'organe de gouvernance", f"Share of {en} on the governance body", "",
        "Formule", "Calculé", reponse="Pourcentage", formule=f"[GOV-CA-{membres}] / [GOV-CA-MEMBRES]",
        description=(f"Calculée par l'outil : {fr_d} divisés par tous les membres de l'organe (femmes, hommes, autre genre ou "
                     f"genre non déclaré) en fin de période, le pourcentage par genre du §12(a) (ESRS 2 §12(a)). Le rapport "
                     f"femmes / hommes de l'AR 6, qui ne compte que les femmes et les hommes, est calculé à part.",
                     f"Calculated by the tool: {en_d} divided by all the members of the body (women, men, another gender or "
                     f"gender not reported) at period end, the percentage by gender of §12(a) (ESRS 2 §12(a)). The ratio of "
                     f"women to men of AR 6, which counts women and men only, is calculated separately."))
    for suffixe, membres, fr, en, fr_d, en_d in (
        ("FEMMES", "FEMMES", "femmes", "women", "femmes membres de l'organe", "women members of the body"),
        ("HOMMES", "HOMMES", "hommes", "men", "hommes membres de l'organe", "men members of the body"),
        ("AUTRES", "AUTRES", "membres d'un autre genre ou au genre non déclaré",
         "members of another gender or whose gender is not reported", "membres d'un autre genre ou au genre non déclaré",
         "members of another gender or whose gender is not reported"))
] + [
    texte("GOV-CA-REPRESENTATION", ("Représentation des salariés et autres travailleurs dans les organes",
                                    "Representation of employees and other workers in the bodies"),
          ("Si les salariés et autres travailleurs sont représentés dans les organes d'administration, de direction ou de "
           "surveillance : comment (nombre de sièges, mode de désignation) (ESRS 2 §12(a)). Répondre N/A sinon.",
           "If employees and other workers are represented in the administrative, management or supervisory bodies: how "
           "(number of seats, how they are appointed) (ESRS 2 §12(a)). Answer N/A otherwise.")),
    texte("GOV-CA-DIVERSITE", ("Autres aspects de la diversité des organes", "Other aspects of diversity of the bodies"),
          ("Répartition des membres des organes selon les autres aspects de la diversité que l'entreprise prend en compte "
           "(âge, nationalité, parcours…), en pourcentage (ESRS 2 §12(a)).",
           "Breakdown of the members of the bodies by the other aspects of diversity that the company takes into account (age, "
           "nationality, background…), as percentages (ESRS 2 §12(a)).")),
    texte("GOV-CA-COMPETENCES", ("Compétences des organes en matière de durabilité", "Sustainability expertise and skills of the bodies"),
          ("Expertise et compétences des organes, propres ou auxquelles ils ont accès, pour superviser et gérer les impacts, "
           "risques et opportunités importants, et comment ils s'assurent que ces compétences sont disponibles ou seront "
           "développées (ESRS 2 §12(b), AR 7).",
           "Expertise and skills of the bodies, held directly or accessible to them, to oversee and manage the material impacts, "
           "risks and opportunities, and how they make sure these skills are available or will be developed (ESRS 2 §12(b), "
           "AR 7).")),
    texte("GOV-CA-RESPONSABILITES", ("Personnes ou comités responsables des impacts, risques et opportunités",
                                     "Persons or committees responsible for impacts, risks and opportunities"),
          ("Identité et responsabilités des personnes, comités ou instances des organes chargés de gérer ou de superviser les "
           "impacts, risques et opportunités importants, telles qu'elles figurent dans les mandats et règlements ; indiquer "
           "ceux que les organes traitent eux-mêmes sans déléguer les décisions clés (ESRS 2 §12(c), AR 8).",
           "Identity and responsibilities of the persons, committees or bodies within the governance bodies in charge of "
           "managing or overseeing the material impacts, risks and opportunities, as set out in mandates and terms of "
           "reference; indicate those that the bodies address themselves without delegating key decisions (ESRS 2 §12(c), "
           "AR 8).")),
    texte("GOV-CA-SUIVI-CIBLES", ("Cibles : fixation et suivi par les organes", "Targets: setting and monitoring by the bodies"),
          ("Comment les organes gèrent ou supervisent la fixation des cibles liées aux impacts, risques et opportunités "
           "importants, et comment ils suivent les progrès vers ces cibles (ESRS 2 §12(d)).",
           "How the bodies manage or oversee the setting of targets related to the material impacts, risks and opportunities, "
           "and how they monitor progress towards them (ESRS 2 §12(d)).")),
    texte("GOV-CA-PRISE-EN-COMPTE", ("Prise en compte des impacts, risques et opportunités par les organes",
                                     "How the bodies take impacts, risks and opportunities into account"),
          ("Comment les organes tiennent compte des impacts, risques et opportunités importants dans la stratégie, les "
           "décisions sur les opérations majeures et la gestion des risques, et comment ils arbitrent entre eux s'ils le font "
           "(ESRS 2 §12(e)).",
           "How the bodies take the material impacts, risks and opportunities into account in the strategy, the decisions on "
           "major transactions and risk management, and how they weigh trade-offs between them if they do (ESRS 2 §12(e)).")),
    oui_non("GOV-CA-ARBITRAGES", ("Arbitrages examinés par les organes", "Trade-offs considered by the bodies"),
            ("Les organes ou les personnes concernées ont-ils examiné les arbitrages liés aux impacts, risques et opportunités "
             "importants (ESRS 2 §12(e)) ?",
             "Have the bodies or the persons concerned considered the trade-offs associated with the material impacts, risks "
             "and opportunities (ESRS 2 §12(e))?")),
    # ------------------------------------------------------------------ GOV-2 – rémunération
    oui_non("GOV-REMU-LIEN", ("Dispositifs incitatifs liés à la durabilité", "Incentive schemes linked to sustainability"),
            ("Les membres des organes d'administration, de direction ou de surveillance ont-ils des dispositifs incitatifs liés "
             "à des sujets de durabilité ? Les quatre informations qui suivent ne sont demandées que si oui (ESRS 2 §14).",
             "Do the members of the administrative, management or supervisory bodies have incentive schemes linked to "
             "sustainability topics? The four disclosures that follow are required only if yes (ESRS 2 §14).")),
    texte("GOV-REMU-DURABILITE", ("Lien entre la rémunération des organes et la durabilité",
                                  "Link between the remuneration of the bodies and sustainability"),
          ("Comment la rémunération des membres des organes est liée à des sujets de durabilité (ESRS 2 §14). Répondre N/A "
           "sans dispositif incitatif de ce type.",
           "How the remuneration of the members of the bodies is linked to sustainability topics (ESRS 2 §14). Answer N/A "
           "without such an incentive scheme.")),
    texte("GOV-REMU-DISPOSITIFS", ("Dispositifs incitatifs : caractéristiques principales", "Incentive schemes: key characteristics"),
          ("Description des caractéristiques principales des dispositifs incitatifs liés à la durabilité (ESRS 2 §14(a)). "
           "Répondre N/A sans dispositif de ce type.",
           "Description of the key characteristics of the incentive schemes linked to sustainability (ESRS 2 §14(a)). Answer "
           "N/A without such a scheme.")),
    texte("GOV-REMU-CRITERES", ("Dispositifs incitatifs : cibles ou indicateurs de durabilité utilisés",
                                "Incentive schemes: sustainability targets or metrics used"),
          ("Si la performance est évaluée par rapport à des cibles ou indicateurs de durabilité précis : lesquels (ESRS 2 "
           "§14(b)). Répondre N/A sinon.",
           "If performance is assessed against specific sustainability targets or metrics: which ones (ESRS 2 §14(b)). Answer "
           "N/A otherwise.")),
    kpi("GOV-REMU-PART-VARIABLE", "Part de la rémunération variable liée à des cibles de durabilité",
        "Share of variable remuneration linked to sustainability targets", "", "Aucune", reponse="Pourcentage", niveau=C.HAUT,
        temps="derniere",
        description=("Part de la rémunération variable des membres des organes qui dépend de cibles ou d'indicateurs de "
                     "durabilité (ESRS 2 §14(c)). Saisie en pourcentage, une fois pour l'entreprise : elle vient des "
                     "contrats et ne s'additionne pas. Répondre N/A sans dispositif de ce type.",
                     "Share of the variable remuneration of the members of the bodies that depends on sustainability targets or "
                     "metrics (ESRS 2 §14(c)). Entered as a percentage, once for the company: it comes from the contracts and "
                     "is not summed. Answer N/A without such a scheme."),
        source=("Politique de rémunération des mandataires, rapport sur les rémunérations.",
                "Remuneration policy of the directors, remuneration report.")),
    # ------------------------------------------------------------------ GOV-3, GOV-4
    texte("GOV-DILIGENCE", ("Déclaration sur la diligence raisonnable", "Statement on due diligence"),
          ("Où l'état de durabilité rend compte des aspects et étapes principaux de la diligence raisonnable appliquée aux "
           "sujets de durabilité (ESRS 2 §16) ; un tableau de correspondance entre les étapes et les informations publiées "
           "convient (AR 9).",
           "Where the sustainability statement reflects the main aspects and steps of the due diligence applied to "
           "sustainability topics (ESRS 2 §16); a table that maps the steps to the disclosures is suitable (AR 9).")),
    texte("GOV-CONTROLE-INTERNE", ("Gestion des risques et contrôle interne du reporting de durabilité",
                                   "Risk management and internal control over sustainability reporting"),
          ("Périmètre, caractéristiques et composantes principales des processus et systèmes de gestion des risques et de "
           "contrôle interne du reporting de durabilité, en tenant compte de l'exhaustivité et de l'intégrité des données et "
           "de la justesse des estimations (ESRS 2 §18, AR 10).",
           "Scope, main features and components of the risk management and internal control processes and systems over "
           "sustainability reporting, considering the completeness and integrity of the data and the accuracy of estimates "
           "(ESRS 2 §18, AR 10).")),
    # ------------------------------------------------------------------ SBM-1 – stratégie, modèle d'affaires, chaîne de valeur
    texte("STR-MODELE-AFFAIRES", ("Modèle d'affaires et chaîne de valeur", "Business model and value chain"),
          ("Description du modèle d'affaires, de la chaîne de valeur amont et aval et de la place de l'entreprise dans cette "
           "chaîne (ESRS 2 §20(a)).",
           "Description of the business model, of the upstream and downstream value chain and of the company's position in it "
           "(ESRS 2 §20(a)).")),
    texte("STR-PRODUITS-MARCHES", ("Produits, services et marchés importants, et leur rôle pour la durabilité",
                                   "Significant products, services and markets, and their role for sustainability"),
          ("Groupes importants de produits et services, marchés ou groupes de clients importants, leur contribution aux "
           "objectifs de durabilité de l'entreprise, et les changements importants de la période (produits, services, "
           "marchés ou clients ajoutés ou retirés) (ESRS 2 §20(b)(i)). Important : plus de 10 % du chiffre d'affaires, ou lié "
           "à des impacts importants réels ou potentiels (AR 13).",
           "Significant groups of products and services, significant markets or customer groups, their contribution to the "
           "company's sustainability objectives, and the significant changes of the period (products, services, markets or "
           "customers added or removed) (ESRS 2 §20(b)(i)). Significant: more than 10% of revenue, or connected with actual or "
           "potential material impacts (AR 13).")),
    texte("STR-PRODUITS-INTERDITS", ("Produits et services interdits sur certains marchés", "Products and services banned in certain markets"),
          ("Le cas échéant et s'ils sont importants, produits et services interdits sur certains marchés (ESRS 2 §20(b)(ii), "
           "AR 13). Répondre N/A sinon.",
           "Where applicable and significant, products and services banned in certain markets (ESRS 2 §20(b)(ii), AR 13). "
           "Answer N/A otherwise.")),
    texte("STR-SECTEURS", ("Secteurs d'activité importants", "Significant sectors of activity"),
          ("Secteurs importants des activités propres de l'entreprise (ESRS 2 §20(c), AR 11 à 13), selon la classification "
           "choisie : NACE, secteurs opérationnels des états financiers (IFRS 8) ou autre classification reconnue. Important : "
           "plus de 10 % du chiffre d'affaires, ou lié à des impacts importants.",
           "Significant sectors of the company's own operations (ESRS 2 §20(c), AR 11 to 13), in the classification chosen: "
           "NACE, operating segments of the financial statements (IFRS 8) or another recognised classification. Significant: "
           "more than 10% of revenue, or connected with material impacts.")),
    texte("STR-ACTIVITES-INTERNES", ("Activités internes au groupe importantes", "Significant activities internal to the group"),
          ("Activités internes au groupe, si elles sont importantes ou liées (ou susceptibles de l'être) à des impacts, "
           "risques et opportunités importants ; pour elles, seul le lien avec des impacts importants rend un secteur "
           "important (ESRS 2 §20(c), AR 13). Répondre N/A s'il n'y en a pas.",
           "Activities internal to the group, if they are significant or connected (or may be connected) to material impacts, "
           "risks and opportunities; for them, only the connection with material impacts makes a sector significant (ESRS 2 "
           "§20(c), AR 13). Answer N/A if there is none.")),
    oui_non("STR-ACTIF-FOSSILE", ("Active dans le secteur des combustibles fossiles", "Active in the fossil fuel sector"),
            ("L'entreprise est-elle active dans le secteur des combustibles fossiles (charbon, pétrole, gaz) : exploration, "
             "extraction, production, transformation, stockage, raffinage, distribution, transport ou commerce (ESRS 2 "
             "§20(d)(i), AR 14) ? Si oui, revenus du charbon, du pétrole et du gaz ci-dessous.",
             "Is the company active in the fossil fuel sector (coal, oil, gas): exploration, extraction, production, "
             "processing, storage, refining, distribution, transport or trade (ESRS 2 §20(d)(i), AR 14)? If yes, revenue from "
             "coal, oil and gas below.")),
    oui_non("STR-ACTIF-CHIMIE", ("Active dans la production de produits chimiques", "Active in chemicals production"),
            ("Des activités de l'entreprise relèvent-elles de la division 20.2 de la NACE (pesticides et autres produits "
             "agrochimiques) (ESRS 2 §20(d)(ii)) ? Si oui, revenus correspondants ci-dessous.",
             "Do activities of the company fall under Division 20.2 of NACE (pesticides and other agrochemical products) (ESRS 2 "
             "§20(d)(ii))? If yes, related revenue below.")),
    oui_non("STR-ACTIF-ARMES", ("Active dans le secteur des armes interdites", "Active in the prohibited weapons industry"),
            ("L'entreprise est-elle active dans le secteur des armes interdites (mines antipersonnel, armes à sous-munitions, "
             "armes chimiques ou biologiques) (ESRS 2 §20(d)(iii)) ? Si oui, revenus correspondants ci-dessous.",
             "Is the company active in the prohibited weapons industry (anti-personnel mines, cluster munitions, chemical or "
             "biological weapons) (ESRS 2 §20(d)(iii))? If yes, related revenue below.")),
    oui_non("STR-ACTIF-TABAC", ("Active dans la culture et la production de tabac", "Active in the cultivation and production of tobacco"),
            ("L'entreprise est-elle active dans la culture et la production de tabac (ESRS 2 §20(d)(iv)) ? Si oui, revenus "
             "correspondants ci-dessous.",
             "Is the company active in the cultivation and production of tobacco (ESRS 2 §20(d)(iv))? If yes, related revenue "
             "below.")),
    # ------------------------------------------------------------------ SBM-2 – parties prenantes
    texte("STR-PARTIES-PRENANTES", ("Dialogue avec les parties prenantes et parties prenantes clés",
                                    "Stakeholder engagement and key stakeholders"),
          ("Description résumée du dialogue avec les parties prenantes et des parties prenantes clés avec lesquelles "
           "l'entreprise a dialogué, selon les catégories de parties prenantes concernées de l'ESRS 1 (AR 23) (ESRS 2 §22(a)).",
           "Summarised description of the stakeholder engagement and of the key stakeholders the company engaged with, by the "
           "categories of affected stakeholders of ESRS 1 (AR 23) (ESRS 2 §22(a)).")),
    texte("STR-PP-ATTENTES", ("Intérêts et points de vue des parties prenantes clés", "Interests and views of key stakeholders"),
          ("Ce que l'entreprise comprend des intérêts et points de vue de ses parties prenantes clés en lien avec sa stratégie "
           "et son modèle d'affaires (ESRS 2 §22(b)).",
           "The company's understanding of the interests and views of its key stakeholders in relation to its strategy and "
           "business model (ESRS 2 §22(b)).")),
    texte("GOV-CA-INFO-PP", ("Information des organes sur les points de vue des parties prenantes",
                             "How the bodies are informed of stakeholders' views"),
          ("Comment les organes d'administration, de direction ou de surveillance sont informés des points de vue et intérêts "
           "des parties prenantes concernées clés, représentants des travailleurs compris, sur les impacts, risques et "
           "opportunités importants (ESRS 2 §22(c)).",
           "How the administrative, management or supervisory bodies are informed of the views and interests of the key "
           "affected stakeholders, workers' representatives included, on the material impacts, risks and opportunities "
           "(ESRS 2 §22(c)).")),
    # ------------------------------------------------------------------ SBM-3 – interaction avec la stratégie, effets financiers
    texte("STR-IRO-INTERACTION", ("Impacts, risques et opportunités importants et stratégie",
                                  "Material impacts, risks and opportunities and the strategy"),
          ("Description générale : comment les impacts importants naissent de la stratégie et du modèle d'affaires, quels "
           "effets les risques et opportunités ont sur le modèle d'affaires et la chaîne de valeur, et comment l'entreprise "
           "les a traités et prévoit de les traiter dans sa stratégie et ses décisions (ESRS 2 §24, AR 15).",
           "High-level description: how the material impacts originate from the strategy and business model, what effects the "
           "risks and opportunities have on the business model and value chain, and how the company has addressed and plans "
           "to address them in its strategy and decisions (ESRS 2 §24, AR 15).")),
    texte("STR-EFFETS-ACTUELS", ("Effets financiers actuels des risques et opportunités importants",
                                 "Current financial effects of material risks and opportunities"),
          ("Informations qualitatives et quantitatives (montants ou fourchettes, ou volumes) sur la façon dont les risques et "
           "opportunités importants ont affecté la situation financière, la performance financière et les flux de trésorerie "
           "de la période (ESRS 2 §25, §32, AR 16 à 20). Les informations quantitatives peuvent être omises dans les cas des "
           "§28 : l'expliquer dans le texte des informations non chiffrées.",
           "Qualitative and quantitative information (amounts or ranges, or volumes) on how the material risks and "
           "opportunities have affected the financial position, financial performance and cash flows of the period (ESRS 2 "
           "§25, §32, AR 16 to 20). Quantitative information can be left out in the cases of §28: explain it in the text on "
           "information not quantified.")),
    texte("STR-EFFETS-AJUSTEMENT", ("Risque d'ajustement important des valeurs comptables l'an prochain",
                                    "Risk of a material adjustment of carrying amounts next year"),
          ("Informations qualitatives et quantitatives sur les risques et opportunités pour lesquels il existe un risque "
           "important d'ajustement significatif, au cours du prochain exercice, de la valeur comptable des actifs et passifs "
           "des états financiers (ESRS 2 §26, AR 16). Répondre N/A s'il n'y en a pas.",
           "Qualitative and quantitative information on the risks and opportunities for which there is a significant risk of a "
           "material adjustment, within the next annual reporting period, to the carrying amounts of assets and liabilities of "
           "the financial statements (ESRS 2 §26, AR 16). Answer N/A if there is none.")),
    texte("STR-EFFETS-ATTENDUS", ("Effets financiers attendus des risques et opportunités importants",
                                  "Anticipated financial effects of material risks and opportunities"),
          ("Informations qualitatives et quantitatives sur l'évolution attendue de la situation financière, de la performance "
           "financière et des flux de trésorerie à court, moyen et long terme, compte tenu de la stratégie de gestion des "
           "risques et opportunités importants : plans d'investissement et de cession, sources de financement prévues "
           "(ESRS 2 §27, AR 17 à 21)." + _PHASE_EFFETS[0],
           "Qualitative and quantitative information on how the financial position, financial performance and cash flows are "
           "expected to change over the short, medium and long term, given the strategy to manage the material risks and "
           "opportunities: investment and disposal plans, planned sources of funding (ESRS 2 §27, AR 17 to 21)."
           + _PHASE_EFFETS[1])),
    texte("STR-EFFETS-HORIZONS", ("Horizons de temps des effets financiers attendus",
                                  "Time horizons of the anticipated financial effects"),
          ("Pour chaque risque ou opportunité, horizon de temps de l'évolution attendue : court terme (la durée de la période "
           "des états financiers), moyen terme (de la fin du court terme jusqu'à cinq ans) ou long terme (plus de cinq ans), "
           "comptés depuis la fin de la période de reporting (ESRS 2 §27 ; "
           "ESRS 1 §79)." + _PHASE_EFFETS[0],
           "For each risk or opportunity, time horizon of the expected change: short term (the length of the financial "
           "statements period), medium term (from the end of the short term up to five years) or long term (more than five "
           "years), counted from the end of the reporting period (ESRS 2 §27; "
           "ESRS 1 §79)." + _PHASE_EFFETS[1])),
    texte("STR-EFFETS-SANS-CHIFFRES", ("Effets financiers : raisons de l'absence d'informations quantitatives",
                                       "Financial effects: why quantitative information is not given"),
          ("Seulement si l'entreprise ne donne pas d'informations quantitatives sur les effets financiers actuels ou attendus "
           "d'un risque ou d'une opportunité (effets non identifiables séparément, incertitude de mesure trop élevée, ou, pour "
           "les effets attendus, compétences ou moyens insuffisants) : pourquoi (ESRS 2 §28, §29, §31(a)). Répondre N/A sinon.",
           "Only if the company gives no quantitative information on the current or anticipated financial effects of a risk "
           "or opportunity (effects not separately identifiable, measurement uncertainty too high, or, for anticipated effects, "
           "lack of skills or resources): why (ESRS 2 §28, §29, §31(a)). Answer N/A otherwise.")),
    texte("STR-EFFETS-COMBINES", ("Effets financiers non chiffrés : informations qualitatives et effets combinés",
                                  "Financial effects not quantified: qualitative information and combined effects"),
          ("Dans le même cas : informations qualitatives sur ces effets financiers, avec les postes, totaux et sous-totaux des "
           "états financiers touchés ou susceptibles de l'être, et informations quantitatives sur les effets combinés de ce "
           "risque ou de cette opportunité avec d'autres, sauf si elles ne seraient pas utiles (ESRS 2 §31(b), (c)). "
           "Répondre N/A sinon.",
           "In the same case: qualitative information on these financial effects, with the line items, totals and subtotals "
           "of the financial statements affected or likely to be, and quantitative information on the combined effects of "
           "this risk or opportunity with others, unless it would not be useful (ESRS 2 §31(b), (c)). Answer N/A otherwise.")),
    texte("STR-RESILIENCE", ("Résilience de la stratégie et du modèle d'affaires", "Resilience of the strategy and business model"),
          ("Informations qualitatives sur la capacité de la stratégie et du modèle d'affaires à gérer les risques importants, "
           "avec la façon dont l'analyse a été menée et les horizons de temps retenus (ESRS 2 §33).",
           "Qualitative information on the capacity of the strategy and business model to manage the material risks, with how "
           "the analysis was conducted and the time horizons considered (ESRS 2 §33).")),
    # ------------------------------------------------------------------ IRO-1 – processus d'analyse de matérialité
    texte("GEN-MAT-PROCESSUS", ("Processus d'identification et d'évaluation des impacts, risques et opportunités",
                                "Process to identify and assess impacts, risks and opportunities"),
          ("Description concise du processus et des étapes de décision suivis pour identifier les impacts, risques et "
           "opportunités et les sujets liés, et en évaluer la matérialité : couverture des activités propres et de la chaîne de "
           "valeur, méthodes, données d'entrée et hypothèses principales, critères qualitatifs ou seuils quantitatifs, "
           "dépendances (ESRS 2 §35(a), AR 22 à 24). L'outil ne fait pas l'analyse : il en recueille la description.",
           "Concise description of the process and decision-making steps followed to identify the impacts, risks and "
           "opportunities and the related topics, and to assess their materiality: coverage of the own operations and the value "
           "chain, key methods, inputs and assumptions, qualitative criteria or quantitative thresholds, dependencies (ESRS 2 "
           "§35(a), AR 22 to 24). The tool does not run the assessment: it collects its description."),
          source=MATERIALITE),
    texte("GEN-MAT-PRIORISATION", ("Évaluation et hiérarchisation des impacts", "How impacts are assessed and prioritised"),
          ("Comment les impacts ont été évalués et hiérarchisés selon leur gravité et leur probabilité, comment les actions "
           "pour prévenir, atténuer, faire cesser, réduire et réparer les impacts négatifs sont prises en compte, et comment "
           "les zones de risque accru liées à des activités, des relations d'affaires ou des zones géographiques ont été "
           "examinées (ESRS 2 §35(b), AR 24 à 26).",
           "How the impacts were assessed and prioritised by severity and likelihood, how actions to prevent, mitigate, bring "
           "to an end, minimise and remediate negative impacts are considered, and how areas of heightened risk related to "
           "activities, business relationships or geographies were considered (ESRS 2 §35(b), AR 24 to 26)."),
          source=MATERIALITE),
    oui_non("GEN-MAT-DILIGENCE", ("Analyse éclairée par la diligence raisonnable", "Assessment informed by due diligence"),
            ("L'évaluation des impacts, risques et opportunités importants s'appuie-t-elle sur le processus de diligence "
             "raisonnable de l'entreprise en matière de durabilité (ESRS 2 §35(c)) ?",
             "Is the assessment of the material impacts, risks and opportunities informed by the company's sustainability due "
             "diligence process (ESRS 2 §35(c))?")),
    texte("GEN-MAT-CONSULTATIONS", ("Consultation des parties prenantes et des experts dans l'analyse",
                                    "Consultation of stakeholders and experts in the assessment"),
          ("Si l'entreprise consulte des parties prenantes concernées et des experts externes pour comprendre ses impacts : "
           "comment ces consultations éclairent l'évaluation (ESRS 2 §35(c), AR 25). Répondre N/A sinon.",
           "If the company consults affected stakeholders and external experts to understand its impacts: how these "
           "consultations inform the assessment (ESRS 2 §35(c), AR 25). Answer N/A otherwise.")),
    texte("GEN-MAT-CHANGEMENTS", ("Changements importants du processus d'analyse", "Significant changes to the assessment process"),
          ("Changements importants du processus par rapport à la période précédente (ESRS 2 §35(d)). Répondre N/A s'il n'y "
           "en a pas.",
           "Significant changes to the process compared with the previous period (ESRS 2 §35(d)). Answer N/A if there is none.")),
    texte("GEN-MAT-DATE", ("Date de la dernière mise à jour de l'analyse de matérialité",
                           "Date of the last update of the materiality assessment"),
          ("Date à laquelle l'analyse de matérialité a été mise à jour pour la dernière fois, sous la forme AAAA-MM-JJ "
           "(ESRS 2 §35(e)).",
           "Date on which the materiality assessment was last updated, as YYYY-MM-DD (ESRS 2 §35(e)).")),
    # ------------------------------------------------------------------ IRO-2 – résultat de l'analyse et index
    texte("GEN-IRO-DESCRIPTION", ("Description des impacts, risques et opportunités importants",
                                  "Description of the material impacts, risks and opportunities"),
          ("Description concise des impacts importants, réels et potentiels, positifs et négatifs, et de la façon dont ils "
           "touchent ou peuvent toucher les personnes ou l'environnement, puis des risques et opportunités importants avec "
           "leurs dépendances ; dire où ils se situent dans les activités propres et la chaîne de valeur (ESRS 2 §37(a), "
           "AR 27, AR 28). Le tableau suivant les liste un par un.",
           "Concise description of the actual and potential, positive and negative material impacts and of how they affect "
           "or are likely to affect people or the environment, then of the material risks and opportunities with their "
           "dependencies; say where they are in the own operations and the value chain (ESRS 2 §37(a), AR 27, AR 28). The next "
           "table lists them one by one."),
          source=MATERIALITE),
    kpi("GEN-IRO-TAB", "Liste des impacts, risques et opportunités importants", "List of material impacts, risks and opportunities",
        "", "Aucune", reponse="ESRS-TAB-IRO", niveau=C.HAUT,
        description=("Une ligne par impact, risque ou opportunité important : intitulé court, nature (impact réel ou potentiel, "
                     "positif ou négatif, risque, opportunité), sujet des ESRS lié, place dans la chaîne de valeur, horizon de "
                     "temps (ESRS 2 §37(a)).",
                     "One row per material impact, risk or opportunity: short title, type (actual or potential, positive or "
                     "negative impact, risk, opportunity), related ESRS topic, place in the value chain, time horizon (ESRS 2 "
                     "§37(a))."),
        source=MATERIALITE),
    texte("GEN-CLIMAT-NON-MATERIEL", ("Raisons pour lesquelles le changement climatique n'est pas important",
                                      "Why climate change is not material"),
          ("Seulement si l'entreprise conclut que le changement climatique n'est pas un sujet important et omet donc tout "
           "l'ESRS E1 : sur quoi repose cette conclusion (ESRS 2 §37(b)). Répondre N/A sinon.",
           "Only if the company concludes that climate change is not material and so omits all of ESRS E1: the basis for this "
           "conclusion (ESRS 2 §37(b)). Answer N/A otherwise.")),
    texte("GEN-IRO-CHANGEMENTS", ("Changements des impacts, risques et opportunités importants",
                                  "Changes in the material impacts, risks and opportunities"),
          ("Changements des impacts, risques et opportunités importants par rapport à la période précédente (ESRS 2 §37(c)). "
           "Répondre N/A s'il n'y en a pas.",
           "Changes in the material impacts, risks and opportunities compared with the previous period (ESRS 2 §37(c)). Answer "
           "N/A if there is none.")),
    texte("GEN-INDEX-EXIGENCES", ("Index des exigences de publication appliquées", "Content index of the disclosure requirements applied"),
          ("Liste des exigences de publication appliquées pour établir l'état de durabilité, avec l'endroit où se trouve "
           "chaque information, en indiquant à part celles incorporées par référence ; un tableau des exigences avec pages ou "
           "paragraphes convient (ESRS 2 §37(d), AR 29).",
           "List of the disclosure requirements applied in preparing the sustainability statement, with where each disclosure "
           "is located, indicating separately those incorporated by reference; a table of the requirements with pages or "
           "paragraphs is suitable (ESRS 2 §37(d), AR 29).")),
    texte("GEN-INFOS-SUPPLEMENTAIRES", ("Liste des informations supplémentaires", "List of supplementary information"),
          ("Liste des informations « supplémentaires » publiées au titre de l'ESRS 1, section 8.2 (autre législation, autres "
           "normes ou cadres, informations non importantes demandées par un utilisateur) (ESRS 2 §37(e), AR 29). Répondre N/A "
           "s'il n'y en a pas.",
           "List of the ‘supplementary’ information disclosed under ESRS 1, section 8.2 (other legislation, other standards or "
           "frameworks, non-material information asked for by a user) (ESRS 2 §37(e), AR 29). Answer N/A if there is none.")),
    texte("GEN-RISQUE-TRAVAIL-FORCE", ("Exposition au risque de travail forcé et de travail des enfants",
                                       "Exposure to the risk of forced labour and child labour"),
          ("Seulement si l'entreprise est liée, par ses activités propres ou sa chaîne de valeur, à des impacts négatifs "
           "importants liés au travail forcé ou obligatoire ou au travail des enfants : son exposition à un risque accru "
           "d'incidents, par type d'opérations (usines, par exemple) ou par pays ou zone géographique (ESRS 2 §37(f)). "
           "Répondre N/A sinon.",
           "Only if the company is connected, through its own operations or its value chain, to material negative impacts "
           "related to forced or compulsory labour or child labour: its exposure to a heightened risk of incidents, by type of "
           "operations (manufacturing plants, for example) or by country or geography (ESRS 2 §37(f)). Answer N/A otherwise.")),
    texte("GEN-INDEX-DONNEES-UE", ("Tableau des points de données issus d'autres textes de l'UE",
                                   "Table of the datapoints derived from other EU legislation"),
          ("Tableau de tous les points de données issus d'autres textes de l'UE (appendice A de l'ESRS 2 : règlement SFDR, "
           "pilier 3, règlement sur les indices de référence, loi européenne sur le climat), avec l'endroit où chacun se trouve "
           "dans l'état de durabilité ou la mention « non important » (ESRS 2 §37(g)).",
           "Table of all the datapoints derived from other EU legislation (Appendix A of ESRS 2: SFDR, Pillar 3, Benchmark "
           "Regulation, European Climate Law), with where each one is in the sustainability statement or the mention ‘not "
           "material’ (ESRS 2 §37(g)).")),
    # ------------------------------------------------------------------ GDR – sujets sans politique, action ni cible
    texte("GEN-SANS-PAT", ("Sujets importants sans politique, action ou cible", "Material topics without policies, actions or targets"),
          ("Sujets liés à des impacts, risques ou opportunités importants pour lesquels l'entreprise n'a pas de politique, "
           "d'action ou de cible : la norme demande de le dire (ESRS 2 §39). Ils peuvent être signalés dans le tableau des "
           "impacts, risques et opportunités (AR 31). Répondre N/A s'il n'y en a pas.",
           "Topics related to material impacts, risks or opportunities for which the company has no policies, actions or "
           "targets: the standard asks to say so (ESRS 2 §39). They can be marked in the table of impacts, risks and "
           "opportunities (AR 31). Answer N/A if there is none.")),
    # ------------------------------------------------------------------ GDR – sujets propres à l'entreprise (ESRS 2 §40)
    *C.bloc_gdr(PREFIXE, ("des sujets propres à l'entreprise", "entity-specific matters"), social=True),
    kpi("GEN-SPEC-INDICATEURS", "Indicateurs propres à l'entreprise", "Entity-specific metrics", "", "Aucune",
        reponse="ESRS-TAB-INDICATEURS", niveau=C.HAUT,
        description=("Une ligne par indicateur défini par l'entreprise pour un sujet important que les ESRS ne couvrent pas, "
                     "ou pas assez finement : intitulé, valeur, unité, périmètre (ESRS 2 §48, AR 42 ; ESRS 1 §11). Un "
                     "indicateur à suivre par site peut aussi être ajouté comme KPI de l'installation.",
                     "One row per metric defined by the company for a material topic that the ESRS do not cover, or not with "
                     "enough granularity: title, value, unit, scope (ESRS 2 §48, AR 42; ESRS 1 §11). A metric to follow by "
                     "site can also be added as a KPI of the installation."),
        source=("Tableaux de bord de l'entreprise.", "Company dashboards.")),
    # ------------------------------------------------------------------ GDR-P §43 – politique des droits humains
    oui_non("GOV-DH-POLITIQUE", ("Politique générale des droits humains (ONU, OIT, OCDE)",
                                 "Overarching human rights policy (UN, ILO, OECD)"),
            ("L'entreprise a-t-elle une politique générale des droits humains qui s'engage à mettre en œuvre les Principes "
             "directeurs des Nations unies relatifs aux entreprises et aux droits de l'homme, la Déclaration de l'OIT relative "
             "aux principes et droits fondamentaux au travail et les Principes directeurs de l'OCDE à l'intention des "
             "entreprises multinationales (ESRS 2 §43, AR 34) ?",
             "Does the company have an overarching human rights policy that commits to implement the UN Guiding Principles on "
             "Business and Human Rights, the ILO Declaration on Fundamental Principles and Rights at Work and the OECD "
             "Guidelines for Multinational Enterprises (ESRS 2 §43, AR 34)?")),
    *[oui_non(code, (f"Politique des droits humains : {fr} {couvert}", f"Human rights policy: {en} covered"),
              (f"La politique générale des droits humains couvre-t-elle {fr_desc} (ESRS 2 §43) ? Répondre N/A sans "
               f"politique de ce type.",
               f"Does the overarching human rights policy cover {en_desc} (ESRS 2 §43)? Answer N/A without such a policy."))
      for code, fr, couvert, en, fr_desc, en_desc in (  # accord du participe avec le groupe couvert
          ("GOV-DH-PERSONNEL", "personnel de l'entreprise", "couvert", "own workforce", "le personnel de l'entreprise",
           "the own workforce"),
          ("GOV-DH-CHAINE", "travailleurs de la chaîne de valeur", "couverts", "workers in the value chain",
           "les travailleurs de la chaîne de valeur", "the workers in the value chain"),
          ("GOV-DH-COMMUNAUTES", "communautés affectées", "couvertes", "affected communities", "les communautés affectées",
           "the affected communities"),
          ("GOV-DH-CONSOMMATEURS", "consommateurs et utilisateurs finaux", "couverts", "consumers and end-users",
           "les consommateurs et utilisateurs finaux", "the consumers and end-users"))],
    texte("GOV-DH-POLIT-DESC", ("Politique des droits humains : contenu, périmètre et références",
                                "Human rights policy: contents, scope and references"),
          ("Pour cette politique, les informations demandées pour toute politique : contenu principal et changements, "
           "périmètre ou exclusions, normes ou initiatives de tiers, prise en compte des intérêts des parties prenantes ; "
           "citer aussi les autres groupes de parties prenantes couverts (ESRS 2 §43, §42). Répondre N/A sans politique de ce "
           "type.",
           "For this policy, the information required for any policy: key contents and changes, scope or exclusions, "
           "third-party standards or initiatives, consideration of the interests of stakeholders; also name the other "
           "stakeholder groups covered (ESRS 2 §43, §42). Answer N/A without such a policy.")),
    # ------------------------------------------------------------------ ESRS 1 §123 – chaîne de valeur, trois premières années
    texte("GEN-CHAINE-VALEUR-EFFORTS", ("Efforts pour obtenir les informations de la chaîne de valeur",
                                        "Efforts to obtain value chain information"),
          ("Pendant les trois premiers exercices de reporting, si toutes les informations nécessaires sur la chaîne de valeur "
           "ne sont pas disponibles : efforts faits pour les obtenir, raisons pour lesquelles elles n'ont pas toutes pu l'être, "
           "et plans pour les obtenir à l'avenir (ESRS 1 §123). Répondre N/A sinon.",
           "During the first three reporting years, if not all the necessary information on the value chain is available: "
           "efforts made to obtain it, reasons why not all of it could be obtained, and plans to obtain it in the future "
           "(ESRS 1 §123). Answer N/A otherwise.")),
])

REGLES = {}


def _gdr(dr, partie):
    """Partie du bloc GDR des sujets propres, avec la référence au paragraphe de l'ESRS 2 (« GDR-P · 42(a) »)."""
    return [(code, ref.replace(" · ESRS 2 §", " · ")) for code, ref in C.arbre_gdr(PREFIXE, dr, partie, social=True)]


SOCLE = C.socle("ESRS_2", "1.1", "2026-11-19", [
    ("BP_1", "BP-1 – Base de préparation de l'état de durabilité", "BP-1 – Basis for preparation of the sustainability statement", [
        ("GEN-PERIMETRE", "BP-1 · 4(a)"), ("GEN-PERIMETRE-ECART", "BP-1 · 4(a)"), ("GEN-CHAINE-VALEUR", "BP-1 · 4(b)"),
        ("GEN-CONFORMITE-ESRS", "BP-1 · 5"), ("GEN-DISPOSITIONS", "BP-1 · 6"), ("GEN-DISPOSITIONS-INFOS", "BP-1 · 6")]),
    ("BP_2", "BP-2 – Mesures transitoires utilisées", "BP-2 – Phase-in provisions used", [
        ("GEN-PROGRESSIF-IRO", "BP-2 · 8"), ("GEN-PROGRESSIF-SUJETS", "BP-2 · 9(a)"), ("GEN-PROGRESSIF-STRATEGIE", "BP-2 · 9(a)"),
        ("GEN-PROGRESSIF-CIBLES", "BP-2 · 9(b)"), ("GEN-PROGRESSIF-BIO-SCIENCE", "BP-2 · 9(b)"),
        ("GEN-PROGRESSIF-POLITIQUES", "BP-2 · 9(c)"), ("GEN-PROGRESSIF-ACTIONS", "BP-2 · 9(d)"),
        ("GEN-PROGRESSIF-INDICATEURS", "BP-2 · 9(e)"), ("GEN-PROGRESSIF-OMIS", "BP-2 · 10")]),
    ("ESRS1", "ESRS 1 – Chaîne de valeur et liens avec les états financiers",
     "ESRS 1 – Value chain and connectivity with the financial statements", [
        ("GEN-CHAINE-VALEUR-EFFORTS", "ESRS 1 · 123"), ("GEN-LIENS-ETATS-FIN", "ESRS 1 · 114-116")]),
    ("GOV_1", "GOV-1 – Rôle des organes d'administration, de direction et de surveillance",
     "GOV-1 – Role of the administrative, management and supervisory bodies", [
        ("GOV-CA-FEMMES", "GOV-1 · 12(a)"), ("GOV-CA-HOMMES", "GOV-1 · 12(a)"), ("GOV-CA-INDEPENDANTS", "GOV-1 · 12(a)"),
        ("GOV-CA-PART-INDEP", "GOV-1 · 12(a)"), ("GOV-CA-PART-FEMMES", "GOV-1 · 12(a)"),
        ("GOV-CA-PART-HOMMES", "GOV-1 · 12(a)"), ("GOV-CA-AUTRES", "GOV-1 · 12(a)"), ("GOV-CA-MEMBRES", "GOV-1 · 12(a)"),
        ("GOV-CA-PART-AUTRES", "GOV-1 · 12(a)"), ("GOV-CA-RATIO-FH", "GOV-1 · 12(a) ; AR 6"),
        ("GOV-CA-REPRESENTATION", "GOV-1 · 12(a)"), ("GOV-CA-DIVERSITE", "GOV-1 · 12(a)"), ("GOV-CA-COMPETENCES", "GOV-1 · 12(b)"),
        ("GOV-CA-RESPONSABILITES", "GOV-1 · 12(c)"), ("GOV-CA-SUIVI-CIBLES", "GOV-1 · 12(d)"),
        ("GOV-CA-PRISE-EN-COMPTE", "GOV-1 · 12(e)"), ("GOV-CA-ARBITRAGES", "GOV-1 · 12(e)")]),
    ("GOV_2", "GOV-2 – Performance de durabilité dans les dispositifs incitatifs",
     "GOV-2 – Sustainability-related performance in incentive schemes", [
        ("GOV-REMU-LIEN", "GOV-2 · 14"), ("GOV-REMU-DURABILITE", "GOV-2 · 14"), ("GOV-REMU-DISPOSITIFS", "GOV-2 · 14(a)"),
        ("GOV-REMU-CRITERES", "GOV-2 · 14(b)"), ("GOV-REMU-PART-VARIABLE", "GOV-2 · 14(c)")]),
    ("GOV_3", "GOV-3 – Déclaration sur la diligence raisonnable", "GOV-3 – Statement on due diligence", [
        ("GOV-DILIGENCE", "GOV-3 · 16")]),
    ("GOV_4", "GOV-4 – Gestion des risques et contrôle interne du reporting de durabilité",
     "GOV-4 – Risk management and internal controls over sustainability reporting", [
        ("GOV-CONTROLE-INTERNE", "GOV-4 · 18")]),
    ("SBM_1", "SBM-1 – Stratégie, modèle d'affaires et chaîne de valeur", "SBM-1 – Strategy, business model and value chain", [
        ("STR-MODELE-AFFAIRES", "SBM-1 · 20(a)"), ("STR-PRODUITS-MARCHES", "SBM-1 · 20(b)(i)"),
        ("STR-PRODUITS-INTERDITS", "SBM-1 · 20(b)(ii)"), ("STR-SECTEURS", "SBM-1 · 20(c)"), ("STR-ACTIVITES-INTERNES", "SBM-1 · 20(c)"),
        ("STR-ACTIF-FOSSILE", "SBM-1 · 20(d)(i)"), ("GOV-REV-CHARBON", "SBM-1 · 20(d)(i)"), ("GOV-REV-PETROLE", "SBM-1 · 20(d)(i)"),
        ("GOV-REV-GAZ", "SBM-1 · 20(d)(i)"), ("STR-ACTIF-CHIMIE", "SBM-1 · 20(d)(ii)"), ("GOV-REV-CHIMIE", "SBM-1 · 20(d)(ii)"),
        ("STR-ACTIF-ARMES", "SBM-1 · 20(d)(iii)"), ("GOV-REV-ARMES", "SBM-1 · 20(d)(iii)"),
        ("STR-ACTIF-TABAC", "SBM-1 · 20(d)(iv)"), ("GOV-REV-TABAC", "SBM-1 · 20(d)(iv)")]),
    ("SBM_2", "SBM-2 – Intérêts et points de vue des parties prenantes", "SBM-2 – Interests and views of stakeholders", [
        ("STR-PARTIES-PRENANTES", "SBM-2 · 22(a)"), ("STR-PP-ATTENTES", "SBM-2 · 22(b)"), ("GOV-CA-INFO-PP", "SBM-2 · 22(c)")]),
    ("SBM_3", "SBM-3 – Impacts, risques et opportunités importants, stratégie et effets financiers",
     "SBM-3 – Material impacts, risks and opportunities, strategy and financial effects", [
        ("STR-IRO-INTERACTION", "SBM-3 · 24"), ("STR-EFFETS-ACTUELS", "SBM-3 · 25"), ("STR-EFFETS-AJUSTEMENT", "SBM-3 · 26"),
        ("STR-EFFETS-ATTENDUS", "SBM-3 · 27"), ("STR-EFFETS-HORIZONS", "SBM-3 · 27"), ("STR-EFFETS-SANS-CHIFFRES", "SBM-3 · 31(a)"),
        ("STR-EFFETS-COMBINES", "SBM-3 · 31(b)-(c)"), ("STR-RESILIENCE", "SBM-3 · 33")]),
    ("IRO_1", "IRO-1 – Processus d'identification et d'évaluation des impacts, risques et opportunités",
     "IRO-1 – Process to identify and assess impacts, risks and opportunities", [
        ("GEN-MAT-PROCESSUS", "IRO-1 · 35(a)"), ("GEN-MAT-PRIORISATION", "IRO-1 · 35(b)"), ("GEN-MAT-DILIGENCE", "IRO-1 · 35(c)"),
        ("GEN-MAT-CONSULTATIONS", "IRO-1 · 35(c)"), ("GEN-MAT-CHANGEMENTS", "IRO-1 · 35(d)"), ("GEN-MAT-DATE", "IRO-1 · 35(e)")]),
    ("IRO_2", "IRO-2 – Impacts, risques et opportunités importants et exigences publiées",
     "IRO-2 – Material impacts, risks and opportunities and disclosure requirements included", [
        ("GEN-IRO-DESCRIPTION", "IRO-2 · 37(a)"), ("GEN-IRO-TAB", "IRO-2 · 37(a)"), ("GEN-CLIMAT-NON-MATERIEL", "IRO-2 · 37(b)"),
        ("GEN-IRO-CHANGEMENTS", "IRO-2 · 37(c)"), ("GEN-INDEX-EXIGENCES", "IRO-2 · 37(d)"),
        ("GEN-INFOS-SUPPLEMENTAIRES", "IRO-2 · 37(e)"), ("GEN-RISQUE-TRAVAIL-FORCE", "IRO-2 · 37(f)"),
        ("GEN-INDEX-DONNEES-UE", "IRO-2 · 37(g)")]),
    ("GDR", "GDR – Exigences générales : sujets sans politique, action ou cible",
     "GDR – General requirements: topics without policies, actions or targets", [("GEN-SANS-PAT", "GDR · 39")]),
    ("GDR_P", "GDR-P – Politiques sur les sujets propres à l'entreprise ; droits humains",
     "GDR-P – Policies on entity-specific matters; human rights", [
        *_gdr("GDR-P", "P"), ("GOV-DH-POLITIQUE", "GDR-P · 43"), ("GOV-DH-PERSONNEL", "GDR-P · 43"), ("GOV-DH-CHAINE", "GDR-P · 43"),
        ("GOV-DH-COMMUNAUTES", "GDR-P · 43"), ("GOV-DH-CONSOMMATEURS", "GDR-P · 43"), ("GOV-DH-POLIT-DESC", "GDR-P · 43")]),
    ("GDR_A", "GDR-A – Actions et ressources sur les sujets propres à l'entreprise",
     "GDR-A – Actions and resources on entity-specific matters", _gdr("GDR-A", "A")),
    ("GDR_M", "GDR-M – Indicateurs des sujets propres à l'entreprise", "GDR-M – Metrics of entity-specific matters", [
        ("GEN-SPEC-INDICATEURS", "GDR-M · 48"), *_gdr("GDR-M", "M")]),
    ("GDR_T", "GDR-T – Cibles sur les sujets propres à l'entreprise", "GDR-T – Targets on entity-specific matters", _gdr("GDR-T", "T")),
])
