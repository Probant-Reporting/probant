"""ESRS S1 Personnel de l'entreprise (ESRS révisées, règlement délégué (UE) 2026/1563), construit sur le modèle de
esrs_e3.py (méthode : note de conception de l'atelier, non publiée ; socle commun : _esrs_communs.py).

Inventaire : lignes « ESRS_S1 » de esrs_coverage.csv (52 points de la liste de l'EFRAG du 28/08/2026, plus la somme des
décès de S1-13 §37(b) et GDR-M). Choix :

- politiques, actions et cibles : bloc commun des exigences générales de l'ESRS 2 (``bloc_gdr``, avec la prise en compte
  des parties prenantes, §42(d)), saisi une fois pour l'entreprise ; les textes propres à S1 (dialogue, canaux,
  réparation, actions sur les impacts négatifs, protection sociale) aussi ;
- effectifs : en nombre de personnes et en fin de période (option fixée, S1 AR 8 et AR 13 : à dire dans le texte des
  méthodes) ; les KPI de la norme volontaire VS (B8, C5) et du catalogue sont repris quand leur définition est la même ;
  la ventilation par pays ou par région (S1-5 §20(b), S1-7, S1-9) est donnée par l'arbre des organisations, sans KPI
  par pays ;
- taux et parts : jamais saisis, calculés depuis des effectifs ou des nombres additionnés (agrégation « Formule ») :
  justes à chaque niveau de l'arbre ; taux d'accidents par million d'heures travaillées (S1 AR 25) ;
- écart de rémunération femmes / hommes : calculé depuis les rémunérations horaires moyennes de la VS (B10, même
  définition que S1 AR 31-32, saisies pour toute l'entreprise) ; ni l'écart saisi du catalogue (SOC-ECART-REMU) ni ceux
  de la transparence des rémunérations (autre population, par employeur) ne sont repris ;
- ratio de la rémunération totale annuelle : rémunération la plus haute (« Confidentiel » : une seule personne) et
  médiane (« Restreint »), saisies pour toute l'entreprise ; ratio calculé ;
- non-salariés (S1-6, S1-13) : KPI distincts de ceux de la VS (indépendants travaillant exclusivement pour l'entreprise) ;
  mise en place progressive (ESRS 1 §125-127) dite dans la description, rien d'automatique.
Revue des doublons (réutilisations confirmées ou refusées, avec la raison) : document de l'atelier.
"""
from referentiel.bibliotheque.outils import ZERO, ZERO_EN, kpi

from . import _esrs_communs as C
from . import _esrs_lot_e as L

SOURCE = C.SOURCE
COUVERTURE = C.COUVERTURE
UNITES = C.UNITES
TYPES_REPONSE = C.TYPES_REPONSE

PREFIXE = "SOC-PERSO"
RH = ("Système d'information RH, paie.", "HR information system, payroll.")
PAIE = ("Paie.", "Payroll.")
SST = ("Registre des accidents, déclarations, service santé et sécurité.",
       "Accident register, accident reports, health and safety department.")
NON_SAL = ("Contrats des indépendants, relevés et factures des entreprises de travail temporaire.",
           "Contracts of self-employed people, statements and invoices of employment agencies.")
ENTITE, HAUT = C.ENTITE, C.HAUT
CONFIDENTIEL, RESTREINT = "Confidentiel", "Restreint"

# Mise en place progressive (ESRS 1 §125(f), §126(f), §127(f)) : une phrase à la fin de la description, rien d'automatique.
PROGRESSIF = (" Mise en place progressive (ESRS 1 §125(f) à §127(f)) : peut être omis pour les exercices antérieurs à 2027 "
              "(entreprises de la première vague) ou pour le premier exercice de reporting (autres entreprises).",
              " Phase-in (ESRS 1 §125(f) to §127(f)): may be omitted for financial years before 2027 (wave-one undertakings) or "
              "for the first year of reporting (other undertakings).")
PROGRESSIF_NON_SAL = (" Mise en place progressive pour les non-salariés (ESRS 1 §125(f) à §127(f)) : peut être omis pour les "
                      "exercices antérieurs à 2027 (entreprises de la première vague) ou pour le premier exercice de reporting "
                      "(autres entreprises).",
                      " Phase-in for non-employees (ESRS 1 §125(f) to §127(f)): may be omitted for financial years before 2027 "
                      "(wave-one undertakings) or for the first year of reporting (other undertakings).")
PROGRESSIF_HORS_EEE = (" Mise en place progressive pour les salariés hors de l'Espace économique européen (ESRS 1 §125(f) à "
                       "§127(f)) : ils peuvent être laissés de côté pour les exercices antérieurs à 2027 (entreprises de la "
                       "première vague) ou pour le premier exercice de reporting (autres entreprises).",
                       " Phase-in for employees outside the European Economic Area (ESRS 1 §125(f) to §127(f)): they may be "
                       "left out for financial years before 2027 (wave-one undertakings) or for the first year of reporting "
                       "(other undertakings).")


def _d(fr, en, zero=False, phase=None):
    """Description (fr, en), avec « Saisir 0 s'il n'y en a pas » pour une donnée additionnée et la phrase de mise en place
    progressive."""
    return (fr + (ZERO if zero else "") + (phase[0] if phase else ""), en + (ZERO_EN if zero else "") + (phase[1] if phase else ""))


def _texte(code, fr, en, desc, source=""):
    return kpi(code, fr, en, "", "Aucune", reponse="Texte", niveau=HAUT, description=desc, **({"source": source} if source else {}))


def _oui_non(code, fr, en, desc):
    return kpi(code, fr, en, "", "Décompte", reponse="OuiNon", niveau=HAUT, description=desc)


def _effectif(code, fr, en, desc, unite="salariés", source=RH, niveau="", temps="derniere"):
    """Effectif (nombre de personnes) en fin de période, saisi au site sauf mention contraire, additionné."""
    return kpi(code, fr, en, unite, temps=temps, niveau=niveau, description=desc, source=source)


def _part(code, fr, en, formule, desc):
    """Part calculée, recalculée à chaque niveau depuis les nombres additionnés (agrégation « Formule »)."""
    return kpi(code, fr, en, "", "Formule", "Calculé", "Pourcentage", formule, decimales=1, description=desc)


def _taux(code, fr, en, formule, desc):
    """Taux par million d'heures travaillées (S1 AR 25) : un indice sans unité, recalculé à chaque niveau."""
    return kpi(code, fr, en, "", "Formule", "Calculé", formule=formule, decimales=2, description=desc)


KPIS = dict([
    *C.bloc_gdr(PREFIXE, ("le personnel de l'entreprise", "the own workforce"), social=True),  # « liés au personnel »
    # ------------------------------------------------------------------ S1-1 – politiques
    _texte("SOC-PERSO-POLIT-COUVERTURE", "Politiques sur le personnel : tout le personnel ou certains groupes",
           "Own workforce policies: whole workforce or specific groups",
           ("Pour chaque politique : dire si elle couvre tout le personnel de l'entreprise ou seulement certains groupes (par "
            "exemple les salariés d'une usine ou d'un pays, ou les travailleurs indépendants) (ESRS S1, §10).",
            "For each policy: say whether it covers all the own workforce or only specific groups (for example the employees "
            "of one plant or one country, or self-employed people) (ESRS S1, §10).")),
    # ------------------------------------------------------------------ S1-2 – dialogue, canaux, réparation
    _texte("SOC-PERSO-DIALOGUE", "Dialogue avec le personnel et ses représentants",
           "Engagement with the own workforce and its representatives",
           ("Comment l'entreprise dialogue directement avec son personnel ou avec les représentants des travailleurs (réunions "
            "d'information, consultation, participation, fréquence), et comment le point de vue du personnel oriente ses "
            "décisions et ses activités pour gérer les impacts sur lui pendant l'année (ESRS S1, §13, AR 2).",
            "How the company engages directly with its own workforce or with workers' representatives (information sessions, "
            "consultation, participation, frequency), and how the views of the workforce inform its decisions and activities "
            "to manage the impacts on it during the year (ESRS S1, §13, AR 2).")),
    _texte("SOC-PERSO-VULNERABLES", "Point de vue des travailleurs vulnérables ou marginalisés",
           "Views of vulnerable or marginalised workers",
           ("Si l'entreprise agit pour les connaître : comment elle recueille le point de vue des personnes de son personnel "
            "particulièrement exposées aux impacts ou marginalisées (par exemple les femmes, les migrants, les personnes "
            "handicapées) (ESRS S1, §13(a)). Répondre N/A si elle ne le fait pas.",
            "If the company takes action to understand them: how it gains insight into the views of the people in its own "
            "workforce who are particularly vulnerable to impacts or marginalised (for example women, migrants, persons with "
            "disabilities) (ESRS S1, §13(a)). Answer N/A if it does not.")),
    _texte("SOC-PERSO-ACCORDS-CADRES", "Accords-cadres mondiaux sur les droits humains du personnel",
           "Global framework agreements on the human rights of the own workforce",
           ("Accords-cadres mondiaux ou autres résultats obtenus avec les représentants des travailleurs sur le respect des "
            "droits humains du personnel (ESRS S1, §13(b)). Répondre N/A s'il n'y en a pas.",
            "Global framework agreements or other outcomes reached with workers' representatives on the respect of the human "
            "rights of the own workforce (ESRS S1, §13(b)). Answer N/A if there is none.")),
    _texte("SOC-PERSO-CANAUX", "Canaux du personnel pour faire part de ses préoccupations, et leur efficacité",
           "Channels for the own workforce to raise concerns, and their effectiveness",
           ("Canaux dont dispose le personnel pour porter directement ses préoccupations ou ses besoins à l'attention de "
            "l'entreprise et les faire traiter, et comment l'entreprise évalue leur efficacité (par exemple avec les critères "
            "du principe 31 des Principes directeurs des Nations unies) (ESRS S1, §14, AR 3). L'existence d'un mécanisme de "
            "plainte se déclare à part.",
            "Channels available to the own workforce to bring its concerns or needs directly to the company's attention and "
            "have them addressed, and how the company assesses their effectiveness (for example with the criteria of "
            "Principle 31 of the UN Guiding Principles) (ESRS S1, §14, AR 3). Whether a grievance mechanism exists is "
            "answered separately.")),
    _texte("SOC-PERSO-REPARATION", "Démarche de réparation envers le personnel", "Approach to remedy for the own workforce",
           ("Démarche générale et procédures de l'entreprise pour réparer, ou contribuer à réparer, un impact négatif important "
            "qu'elle a causé ou auquel elle a contribué sur des personnes de son personnel (ESRS S1, §15).",
            "General approach and processes of the company to provide or cooperate in remedy when it has caused or "
            "contributed to a material negative impact on people in its own workforce (ESRS S1, §15).")),
    # ------------------------------------------------------------------ S1-3 – actions sur les impacts négatifs
    _texte("SOC-PERSO-ACTIONS-IMPACTS", "Actions sur les impacts négatifs importants sur le personnel",
           "Actions on material negative impacts on the own workforce",
           ("Actions clés menées, prévues ou en cours pour prévenir, atténuer, faire cesser, réduire et réparer les impacts "
            "négatifs importants sur le personnel, y compris quand ces actions entrent en tension avec d'autres contraintes "
            "économiques ; mesures liées à la transition climatique (par exemple reclassements internes lors de la fermeture "
            "d'une usine) (ESRS S1, §17(a), AR 4, AR 5).",
            "Key actions taken, planned or under way to prevent, mitigate, bring to an end, minimise and remediate material "
            "negative impacts on the own workforce, including when these actions are in tension with other business "
            "pressures; measures linked to the climate transition (for example internal redeployment when a plant closes) "
            "(ESRS S1, §17(a), AR 4, AR 5).")),
    _texte("SOC-PERSO-ACTIONS-SUIVI", "Suivi de l'efficacité des actions pour le personnel",
           "Tracking of the effectiveness of the actions for the own workforce",
           ("Comment l'entreprise suit et évalue l'efficacité de ces actions pour obtenir des résultats pour son personnel "
            "(ESRS S1, §17(b)). Si ce suivi est déjà décrit avec les cibles ou les indicateurs (ESRS 2 GDR-T, GDR-M), un renvoi "
            "suffit.",
            "How the company tracks and assesses the effectiveness of these actions in delivering outcomes for its own "
            "workforce (ESRS S1, §17(b)). If this tracking is already described with the targets or the metrics (ESRS 2 "
            "GDR-T, GDR-M), a reference is enough.")),
    # ------------------------------------------------------------------ S1-5 – caractéristiques des salariés
    _effectif("SOC-EFF-CDI-F", "Femmes en contrat permanent en fin de période", "Permanent female employees at end of period",
              _d("Salariées en contrat permanent (définition du droit du pays où elles travaillent) à la fin de la période, en "
                 "nombre de personnes (ESRS S1, §20(c)(i), AR 7, AR 10).",
                 "Female employees on a permanent contract (definition of the law of the country where they work) at the end "
                 "of the period, as a headcount (ESRS S1, §20(c)(i), AR 7, AR 10).", zero=True)),
    _effectif("SOC-EFF-CDI-H", "Hommes en contrat permanent en fin de période", "Permanent male employees at end of period",
              _d("Salariés masculins en contrat permanent (définition du droit du pays où ils travaillent) à la fin de la "
                 "période, en nombre de personnes (ESRS S1, §20(c)(i), AR 7, AR 10). Les autres genres se déduisent du total "
                 "des contrats permanents.",
                 "Male employees on a permanent contract (definition of the law of the country where they work) at the end of "
                 "the period, as a headcount (ESRS S1, §20(c)(i), AR 7, AR 10). Other genders are the rest of the permanent "
                 "total.", zero=True)),
    _effectif("SOC-EFF-TEMPORAIRES", "Salariés en contrat temporaire en fin de période", "Temporary employees at end of period",
              _d("Salariés en contrat temporaire (à durée déterminée, définition du droit du pays où ils travaillent) à la fin "
                 "de la période, en nombre de personnes, tous genres (ESRS S1, §20(c)(ii), AR 7, AR 10).",
                 "Employees on a temporary (fixed-term) contract (definition of the law of the country where they work) at the "
                 "end of the period, as a headcount, all genders (ESRS S1, §20(c)(ii), AR 7, AR 10).", zero=True)),
    _effectif("SOC-EFF-TEMP-F", "Femmes en contrat temporaire en fin de période", "Temporary female employees at end of period",
              _d("Salariées en contrat temporaire à la fin de la période, en nombre de personnes (ESRS S1, §20(c)(ii)).",
                 "Female employees on a temporary contract at the end of the period, as a headcount (ESRS S1, §20(c)(ii)).",
                 zero=True)),
    _effectif("SOC-EFF-TEMP-H", "Hommes en contrat temporaire en fin de période", "Temporary male employees at end of period",
              _d("Salariés masculins en contrat temporaire à la fin de la période, en nombre de personnes (ESRS S1, §20(c)(ii)).",
                 "Male employees on a temporary contract at the end of the period, as a headcount (ESRS S1, §20(c)(ii)).",
                 zero=True)),
    _effectif("SOC-EFF-HEURES-NON-GARANTIES", "Salariés sans nombre d'heures garanti en fin de période",
              "Non-guaranteed hours employees at end of period",
              _d("Salariés sans garantie d'un nombre minimal ou fixe d'heures de travail (contrats « zéro heure », salariés sur "
                 "appel, occasionnels) à la fin de la période, en nombre de personnes ; selon le droit du pays, ils sont aussi "
                 "comptés en contrat permanent ou temporaire (ESRS S1, §20(c)(iii), AR 10).",
                 "Employees without a guaranteed minimum or fixed number of working hours (zero-hour contracts, on-call and "
                 "casual employees) at the end of the period, as a headcount; depending on national law, they are also "
                 "counted as permanent or temporary (ESRS S1, §20(c)(iii), AR 10).", zero=True)),
    # dénominateur du taux de rotation : effectif moyen de tous les salariés (AR 11 « average employee headcount »),
    # il remplace l'effectif moyen en contrat permanent
    _effectif("SOC-EFF-MOYEN", "Effectif moyen des salariés", "Average employee headcount",
              _d("Nombre moyen de salariés sur la période, tous contrats (par exemple la moyenne des effectifs de fin de mois), "
                 "en nombre de personnes : dénominateur du taux de rotation (ESRS S1, §20(d), AR 11).",
                 "Average number of employees over the period, all contracts (for example the average of the month-end "
                 "headcounts), as a headcount: denominator of the turnover rate (ESRS S1, §20(d), AR 11)."),
              temps="moyenne"),
    kpi("SOC-ROTATION-CDI", "Taux de rotation des salariés en contrat permanent", "Turnover rate of permanent employees", "",
        "Formule", "Calculé", "Pourcentage", "[SOC-DEPARTS-CDI] / [SOC-EFF-MOYEN]", decimales=1,
        description=("Calculé par l'outil : départs de salariés en contrat permanent (démission, licenciement, retraite, décès en "
                     "activité) divisés par l'effectif moyen de tous les salariés, comme le demande l'AR 11 (ESRS S1, §20(d), "
                     "AR 11). Recalculé à chaque niveau sur les totaux.",
                     "Calculated by the tool: leavers on permanent contracts (resignation, dismissal, retirement, death in "
                     "service) divided by the average headcount of all employees, as AR 11 requires (ESRS S1, §20(d), AR 11). "
                     "Recalculated at each level from the totals.")),
    _texte("SOC-EFF-ECART-COMPTES", "Écart entre l'effectif déclaré et les états financiers",
           "Difference between the reported headcount and the financial statements",
           ("Seulement si l'effectif total déclaré ne concorde pas avec le chiffre le plus représentatif des états financiers "
            "(par exemple un effectif moyen ou en équivalent temps plein) : explication de l'écart (ESRS S1, §20(e)). Répondre "
            "N/A sinon.",
            "Only if the total headcount reported does not match the most representative number in the financial statements "
            "(for example an average or full-time equivalent figure): explanation of the difference (ESRS S1, §20(e)). Answer "
            "N/A otherwise.")),
    # ------------------------------------------------------------------ S1-6 – non-salariés
    _effectif("SOC-NON-SALARIES", "Non-salariés du personnel en fin de période", "Non-employees in the own workforce at end of period",
              _d("Personnes du personnel de l'entreprise qui ne sont pas ses salariés, à la fin de la période, en nombre de "
                 "personnes : travailleurs indépendants qui fournissent du travail à l'entreprise par contrat, et personnes "
                 "mises à disposition par des entreprises de travail temporaire (NACE N78) (ESRS S1, §7, §22, AR 13). Tous les "
                 "indépendants qui fournissent du travail sont comptés, pas seulement ceux qui travaillent exclusivement pour "
                 "l'entreprise. S1-6 ne se publie que si les non-salariés sont liés à des impacts, risques ou opportunités "
                 "importants (ESRS S1, §1(b), AR 12) ; le nombre sert aussi à la part du personnel couverte par la santé et "
                 "la sécurité (§37(a)) : le saisir dès qu'il est connu. Une réponse N/A (mesure transitoire, non-salariés "
                 "non suivis) fait porter cette part et le taux d'accidents du personnel sur les seuls salariés.",
                 "People in the company's own workforce who are not its employees, at the end of the period, as a headcount: "
                 "self-employed people who supply labour to the company under contract, and people provided by employment "
                 "agencies (NACE N78) (ESRS S1, §7, §22, AR 13). All self-employed people who supply labour are counted, not "
                 "only those who work exclusively for the company. S1-6 is disclosed only if non-employees are connected to "
                 "material impacts, risks or opportunities (ESRS S1, §1(b), AR 12); the number is also used for the share of "
                 "the own workforce covered by health and safety (§37(a)): enter it as soon as it is known. An N/A answer "
                 "(phase-in, non-employees not tracked) makes this share and the accident rate of the own workforce cover "
                 "employees only.",
                 zero=True, phase=PROGRESSIF),
              unite="personnes", source=NON_SAL),
    # ------------------------------------------------------------------ S1-7 – négociation collective et dialogue social
    # La part se lit sur les sites qui ont répondu ET sur tout leur effectif : un site qui répondrait N/A aux salariés couverts
    # sortirait du numérateur (somme : N/A exclus) mais pas du dénominateur (part faussée, 60 % au lieu de 75 %). Pendant la
    # mise en place progressive hors de l'EEE, la consigne est donc de saisir le nombre (la VS le demande pour tous les
    # salariés) et de lire la part de l'EEE sur les organisations de l'EEE.
    _part("SOC-PART-CONVENTION", "Part des salariés couverts par une convention collective",
          "Share of employees covered by collective bargaining agreements", "[SOC-SAL-CONVENTION] / [SOC-EFFECTIF]",
          _d("Calculée par l'outil : salariés couverts par une convention collective divisés par l'effectif total, en nombre "
             "de personnes (ESRS S1, §24(a), AR 14). Lue par pays (pays de l'Espace économique européen où l'entreprise emploie "
             "beaucoup de salariés, §24(b)) ou par région hors de l'Espace (§24(c)) dans les vues par organisation. Chaque "
             "site saisit le nombre de ses salariés couverts, y compris hors de l'EEE pendant la mise en place progressive : "
             "une réponse N/A sortirait ses salariés couverts du calcul mais pas son effectif, et la part serait fausse ; la "
             "part de l'EEE se lit alors sur les organisations de l'EEE.",
             "Calculated by the tool: employees covered by collective bargaining agreements divided by the total headcount "
             "(ESRS S1, §24(a), AR 14). Read by country (countries of the European Economic Area with significant employment, "
             "§24(b)) or by region outside the Area (§24(c)) in the views by organisation. Every site enters the number of "
             "its covered employees, outside the EEA too during the phase-in: an N/A answer would take its covered "
             "employees out of the calculation but not its headcount, and the share would be wrong; the EEA share is then "
             "read on the EEA organisations.", phase=PROGRESSIF_HORS_EEE)),
    _oui_non("SOC-CONVENTION-EEE", "Conventions collectives dans l'Espace économique européen",
             "Collective bargaining agreements in the European Economic Area",
             ("L'entreprise a-t-elle une ou plusieurs conventions collectives dans l'Espace économique européen ? Si oui, la "
              "part des salariés couverts par pays se lit dans les vues par organisation (ESRS S1, §24(b)).",
              "Does the company have one or more collective bargaining agreements in the European Economic Area? If yes, the "
              "share of employees covered by country is read in the views by organisation (ESRS S1, §24(b)).")),
    _effectif("SOC-SAL-REPRESENTES", "Salariés des établissements dotés de représentants des travailleurs",
              "Employees in establishments with workers' representatives",
              _d("Salariés qui travaillent, à la fin de la période, dans un établissement (usine, agence, siège…) où les "
                 "salariés sont représentés par des représentants des travailleurs (syndicaux ou élus), en nombre de "
                 "personnes (ESRS S1, §25(a), AR 16).",
                 "Employees who work, at the end of the period, in an establishment (plant, branch, headquarters…) where the "
                 "employees are represented by workers' representatives (trade union or elected), as a headcount (ESRS S1, "
                 "§25(a), AR 16).", zero=True)),
    _part("SOC-PART-REPRESENTES", "Part des salariés couverts par des représentants des travailleurs",
          "Share of employees covered by workers' representatives", "[SOC-SAL-REPRESENTES] / [SOC-EFFECTIF]",
          ("Calculée par l'outil : salariés des établissements dotés de représentants des travailleurs divisés par l'effectif "
           "total (ESRS S1, §25(a), AR 16). La norme la demande pour chaque pays de l'Espace économique européen où "
           "l'entreprise emploie beaucoup de salariés : la lire par pays dans les vues par organisation.",
           "Calculated by the tool: employees in establishments with workers' representatives divided by the total headcount "
           "(ESRS S1, §25(a), AR 16). The standard asks for it for each country of the European Economic Area with significant "
           "employment: read it by country in the views by organisation.")),
    _oui_non("SOC-COMITE-EUROPEEN", "Accord pour un comité d'entreprise européen", "Agreement for a European works council",
             ("Existe-t-il un accord avec les salariés pour leur représentation par un comité d'entreprise européen, un comité "
              "de société européenne (SE) ou de société coopérative européenne (SCE) (ESRS S1, §25(b)) ?",
              "Is there an agreement with the employees for their representation by a European Works Council, a Societas "
              "Europaea (SE) or a Societas Cooperativa Europaea (SCE) works council (ESRS S1, §25(b))?")),
    # ------------------------------------------------------------------ S1-8 – mixité de la direction
    _effectif("SOC-DIRECTION-F", "Femmes de la direction générale", "Women in top management",
              ("Femmes de la direction générale à la fin de la période, en nombre de personnes. Direction générale : les deux "
               "niveaux sous les organes d'administration et de surveillance, ou la définition propre de l'entreprise, à "
               "donner dans le texte des méthodes (ESRS S1, §27, AR 17).",
               "Women in top management at the end of the period, as a headcount. Top management: the two levels below the "
               "administrative and supervisory bodies, or the company's own definition, to be given in the methods text "
               "(ESRS S1, §27, AR 17)."),
              unite="personnes", niveau=HAUT),
    _effectif("SOC-DIRECTION-H", "Hommes de la direction générale", "Men in top management",
              ("Hommes de la direction générale à la fin de la période, en nombre de personnes, avec la même définition que "
               "pour les femmes (ESRS S1, §27, AR 17).",
               "Men in top management at the end of the period, as a headcount, with the same definition as for women "
               "(ESRS S1, §27, AR 17)."),
              unite="personnes", niveau=HAUT),
    _effectif("SOC-DIRECTION-AUTRE", "Membres de la direction générale d'un autre genre ou au genre non communiqué",
              "Top management members of another gender or with gender not reported",
              _d("Membres de la direction générale d'un autre genre ou dont le genre n'est pas communiqué, à la fin de la "
                 "période, en nombre de personnes (ESRS S1, §27) : ils comptent dans le total qui sert aux parts.",
                 "Top management members of another gender or whose gender is not reported, at the end of the period, as a "
                 "headcount (ESRS S1, §27): they count in the total used for the shares.", zero=True),
              unite="personnes", niveau=HAUT),
    _part("SOC-DIRECTION-PART-F", "Part des femmes dans la direction générale", "Share of women in top management",
          "[SOC-DIRECTION-F] / ([SOC-DIRECTION-F] + [SOC-DIRECTION-H] + [SOC-DIRECTION-AUTRE])",
          ("Calculée par l'outil : femmes de la direction générale divisées par l'ensemble de ses membres (ESRS S1, §27).",
           "Calculated by the tool: women in top management divided by all its members (ESRS S1, §27).")),
    _part("SOC-DIRECTION-PART-H", "Part des hommes dans la direction générale", "Share of men in top management",
          "[SOC-DIRECTION-H] / ([SOC-DIRECTION-F] + [SOC-DIRECTION-H] + [SOC-DIRECTION-AUTRE])",
          ("Calculée par l'outil : hommes de la direction générale divisés par l'ensemble de ses membres (ESRS S1, §27).",
           "Calculated by the tool: men in top management divided by all its members (ESRS S1, §27).")),
    # ------------------------------------------------------------------ S1-9 – salaires décents
    _oui_non("SOC-SALAIRE-DECENT", "Tous les salariés perçoivent un salaire décent", "All employees are paid an adequate wage",
             ("Tous les salariés perçoivent-ils un salaire décent ? On compare, pays par pays, le salaire le plus bas (hors "
              "stagiaires et apprentis : salaire de base et primes fixes garanties à tous) à une référence qui ne peut pas être "
              "inférieure, dans l'Union, au salaire fixé par convention collective ou au salaire minimum légal (directive (UE) "
              "2022/2041) et, hors de l'Union, au salaire minimum adéquat ou à une estimation du salaire vital (principes de "
              "l'OIT) (ESRS S1, §29, AR 18 à AR 20). Un salaire décent n'est pas forcément le salaire minimum.",
              "Are all employees paid an adequate wage? Compare, country by country, the lowest wage (interns and apprentices "
              "excluded: basic wage plus fixed payments guaranteed to all) with a benchmark that cannot be lower, in the EU, "
              "than the wage set by collective bargaining or the statutory minimum wage (Directive (EU) 2022/2041) and, outside "
              "the EU, than the adequate minimum wage or a living wage estimate (ILO principles) (ESRS S1, §29, AR 18 to AR 20). "
              "An adequate wage is not necessarily the minimum wage.")),
    _texte("SOC-SALAIRE-DECENT-REF", "Références de salaire décent et pays concernés", "Adequate wage benchmarks and their countries",
           ("Référence ou références utilisées pour juger si un salaire est décent, avec les pays pour lesquels chacune est "
            "utilisée (ESRS S1, §29, AR 20).",
            "Benchmark or benchmarks used to decide whether a wage is adequate, with the countries for which each one is used "
            "(ESRS S1, §29, AR 20)."),
           source=("Conventions collectives, salaires minimaux légaux, estimations du salaire vital.",
                   "Collective agreements, statutory minimum wages, living wage estimates.")),
    _effectif("SOC-SAL-SOUS-DECENT", "Salariés qui ne perçoivent pas un salaire décent", "Employees not paid an adequate wage",
              _d("Salariés dont le salaire est inférieur à la référence de salaire décent de leur pays, à la fin de la période, "
                 "en nombre de personnes (ESRS S1, §29, AR 19).",
                 "Employees whose wage is below the adequate wage benchmark of their country, at the end of the period, as a "
                 "headcount (ESRS S1, §29, AR 19).", zero=True), source=PAIE),
    _part("SOC-PART-SOUS-DECENT", "Part des salariés qui ne perçoivent pas un salaire décent",
          "Share of employees not paid an adequate wage", "[SOC-SAL-SOUS-DECENT] / [SOC-EFFECTIF]",
          ("Calculée par l'outil : salariés sous la référence de salaire décent divisés par l'effectif total (ESRS S1, §29). La "
           "norme la demande pour chaque pays concerné : la lire par pays dans les vues par organisation.",
           "Calculated by the tool: employees below the adequate wage benchmark divided by the total headcount (ESRS S1, §29). "
           "The standard asks for it for each country concerned: read it by country in the views by organisation.")),
    # ------------------------------------------------------------------ S1-10 – protection sociale
    *[_texte(f"SOC-PROTECTION-{code}", f"Pays sans protection sociale : {fr}", f"Countries without social protection: {en}",
             _d(f"Seulement si des salariés n'ont pas de protection sociale, par un régime public ou par des avantages offerts "
                f"par l'entreprise : pays où {fr_evt} {fr_couvert} par la protection sociale existante (ESRS S1, §31({p})). "
                "Répondre « Aucun » si tous les salariés sont couverts.",
                f"Only if employees lack social protection, through public programmes or benefits offered by the company: "
                f"countries where {en_evt} is not covered by the existing social protection (ESRS S1, §31({p})). Answer "
                "‘None’ if all employees are covered.", phase=PROGRESSIF))
      for code, fr, en, fr_evt, fr_couvert, en_evt, p in (  # accord : « n'est pas couverte », « ne sont pas couverts »
          ("MALADIE", "maladie", "sickness", "la perte de revenu pour maladie", "n'est pas couverte",
           "loss of income due to sickness", "a"),
          ("CHOMAGE", "chômage", "unemployment", "le chômage survenu pendant l'emploi dans l'entreprise", "n'est pas couvert",
           "unemployment starting while working for the company", "b"),
          ("ACCIDENT", "accident du travail et invalidité", "employment injury and disability",
           "l'accident du travail et l'invalidité acquise", "ne sont pas couverts", "employment injury and acquired disability",
           "c"),
          ("MATERNITE", "congé de maternité", "maternity leave", "le congé de maternité", "n'est pas couvert", "maternity leave",
           "d"))],
    # ------------------------------------------------------------------ S1-12 – formation et développement des compétences
    _effectif("SOC-SAL-ENTRETIENS", "Salariés ayant eu un entretien formel de performance et de carrière",
              "Employees with a formal performance and career review",
              _d("Salariés qui ont participé pendant la période à un entretien formalisé de performance et d'évolution de "
                 "carrière (au moins une fois par an, sur des critères connus du salarié et de son responsable), chacun compté "
                 "une fois (ESRS S1, §35(a), AR 22).",
                 "Employees who took part during the period in a formalised performance and career development review (at "
                 "least once a year, on criteria known to the employee and the manager), each counted once (ESRS S1, §35(a), "
                 "AR 22).", zero=True, phase=PROGRESSIF), temps="aucune"),
    _part("SOC-PART-ENTRETIENS", "Part des salariés ayant eu un entretien de performance et de carrière",
          "Share of employees with a performance and career review", "[SOC-SAL-ENTRETIENS] / [SOC-EFFECTIF]",
          ("Calculée par l'outil : salariés ayant eu un entretien divisés par l'effectif total de S1-5, en nombre de personnes "
           "(ESRS S1, §35(a), AR 22).",
           "Calculated by the tool: employees with a review divided by the total headcount of S1-5 (ESRS S1, §35(a), AR 22).")),
    # ------------------------------------------------------------------ S1-13 – santé et sécurité
    _effectif("SOC-SST-COUVERTS", "Personnel couvert par le système de management de la santé et de la sécurité",
              "Own workforce covered by the health and safety management system",
              _d("Personnes du personnel (salariés et non-salariés) couvertes à la fin de la période par le système de "
                 "management de la santé et de la sécurité au travail de l'entreprise, fondé sur des obligations légales ou des "
                 "normes ou lignes directrices reconnues, en nombre de personnes (ESRS S1, §37(a), AR 24).",
                 "People in the own workforce (employees and non-employees) covered at the end of the period by the company's "
                 "occupational health and safety management system, based on legal requirements or recognised standards or "
                 "guidelines, as a headcount (ESRS S1, §37(a), AR 24).", zero=True),
              unite="personnes", source=SST),
    kpi("SOC-PERSONNEL", "Personnel de l'entreprise (salariés et non-salariés)", "Own workforce (employees and non-employees)",
        "personnes", "Somme", "Calculé", formule="[SOC-EFFECTIF] + [SOC-NON-SALARIES]",
        description=("Calculé par l'outil : effectif des salariés plus non-salariés du personnel, en fin de période ; un nombre "
                     "de non-salariés N/A compte comme 0 (ESRS S1, §7, §37(a)).",
                     "Calculated by the tool: employee headcount plus non-employees in the own workforce, at period end; an N/A "
                     "number of non-employees counts as 0 (ESRS S1, §7, §37(a)).")),
    _part("SOC-PART-SST", "Part du personnel couverte par le système de santé et de sécurité",
          "Share of the own workforce covered by the health and safety management system",
          "[SOC-SST-COUVERTS] / [SOC-PERSONNEL]",
          ("Calculée par l'outil : personnes couvertes divisées par le personnel (salariés et non-salariés), en nombre de "
           "personnes (ESRS S1, §37(a), AR 24). Si le nombre de non-salariés est N/A, la part porte sur les salariés.",
           "Calculated by the tool: people covered divided by the own workforce (employees and non-employees), as a headcount "
           "(ESRS S1, §37(a), AR 24). If the number of non-employees is N/A, the share covers employees.")),
    kpi("SOC-DECES-MALADIE", "Décès dus à une maladie liée au travail (salariés)", "Fatalities from work-related ill health (employees)",
        "personnes", description=_d(
            "Salariés décédés pendant la période d'une maladie liée au travail comptabilisable (maladie causée ou aggravée par "
            "le travail), sous réserve des restrictions légales (ESRS S1, §37(b)(ii)). Ils font partie des décès liés au "
            "travail des salariés.",
            "Employees who died during the period from recordable work-related ill health (illness caused or made worse by "
            "work), subject to legal restrictions (ESRS S1, §37(b)(ii)). They are part of the work-related fatalities of "
            "employees.", zero=True), source=SST),
    kpi("SOC-DECES-NON-SAL", "Décès dus à un accident du travail (non-salariés)", "Fatalities from work-related accidents (non-employees)",
        "personnes", description=_d(
            "Non-salariés du personnel décédés pendant la période des suites d'un accident du travail comptabilisable, sous "
            "réserve des restrictions légales (ESRS S1, §37(b)(i)).",
            "Non-employees in the own workforce who died during the period as a result of a recordable work-related accident, "
            "subject to legal restrictions (ESRS S1, §37(b)(i)).", zero=True, phase=PROGRESSIF_NON_SAL), source=SST),
    kpi("SOC-DECES-SITE", "Décès dus à un accident du travail (autres travailleurs sur les sites)",
        "Fatalities from work-related accidents (other workers on the sites)", "personnes", description=_d(
            "Travailleurs qui ne font pas partie du personnel (sous-traitants, par exemple) mais travaillent sur les sites de "
            "l'entreprise, décédés pendant la période des suites d'un accident du travail comptabilisable, sous réserve des "
            "restrictions légales (ESRS S1, §37(b)(i)).",
            "Workers who are not part of the own workforce (subcontractors, for example) but work on the company's sites, who "
            "died during the period as a result of a recordable work-related accident, subject to legal restrictions (ESRS "
            "S1, §37(b)(i)).", zero=True), source=SST),
    kpi("SOC-DECES-ACCIDENTS", "Décès dus à un accident du travail (personnel et travailleurs sur les sites)",
        "Fatalities from work-related accidents (own workforce and workers on the sites)", "personnes", "Somme", "Calculé",
        formule="[SOC-DECES] - [SOC-DECES-MALADIE] + [SOC-DECES-NON-SAL] + [SOC-DECES-SITE]",
        description=("Calculés par l'outil : décès liés au travail des salariés moins ceux dus à une maladie, plus les décès par "
                     "accident des non-salariés et des autres travailleurs sur les sites (ESRS S1, §37(b)(i)).",
                     "Calculated by the tool: work-related fatalities of employees minus those from ill health, plus the "
                     "accident fatalities of non-employees and of other workers on the sites (ESRS S1, §37(b)(i)).")),
    kpi("SOC-DECES-TOUS", "Décès liés au travail, tous travailleurs", "Work-related fatalities, all workers", "personnes", "Somme",
        "Calculé", formule="[SOC-DECES] + [SOC-DECES-NON-SAL] + [SOC-DECES-SITE]",
        description=("Calculés par l'outil : somme demandée par la norme, décès par accident du travail (personnel et autres "
                     "travailleurs sur les sites) et décès des salariés par maladie liée au travail (ESRS S1, §37(b)).",
                     "Calculated by the tool: the sum the standard asks for, fatalities from work-related accidents (own "
                     "workforce and other workers on the sites) and fatalities of employees from work-related ill health "
                     "(ESRS S1, §37(b)).")),
    kpi("SOC-ACCIDENTS-NON-SAL", "Accidents du travail comptabilisables (non-salariés)",
        "Recordable work-related accidents (non-employees)", "accidents", description=_d(
            "Accidents liés au travail des non-salariés du personnel survenus pendant la période et ayant entraîné un décès ou "
            "plus de trois jours d'absence (ESRS S1, §37(c), AR 25, AR 26 ; glossaire).",
            "Work-related accidents of non-employees in the own workforce during the period that resulted in death or more "
            "than three days of absence (ESRS S1, §37(c), AR 25, AR 26; glossary).", zero=True, phase=PROGRESSIF_NON_SAL),
        source=SST),
    kpi("SOC-ACCIDENTS-TOUS", "Accidents du travail comptabilisables (personnel)", "Recordable work-related accidents (own workforce)",
        "accidents", "Somme", "Calculé", formule="[SOC-ACCIDENTS-ENREG] + [SOC-ACCIDENTS-NON-SAL]",
        description=("Calculés par l'outil : accidents des salariés plus accidents des non-salariés ; les accidents mortels en "
                     "font partie (ESRS S1, §37(c), AR 26).",
                     "Calculated by the tool: accidents of employees plus accidents of non-employees; fatal accidents are "
                     "included (ESRS S1, §37(c), AR 26).")),
    kpi("SOC-HEURES-NON-SAL", "Heures travaillées par les non-salariés", "Hours worked by non-employees", "h", description=_d(
        "Heures travaillées par les non-salariés du personnel pendant la période ; à défaut, estimées sur la durée normale du "
        "travail, congés payés déduits (ESRS S1, §37(c), AR 25).",
        "Hours worked by non-employees in the own workforce during the period; if not known, estimated from normal working "
        "hours, paid leave deducted (ESRS S1, §37(c), AR 25).", zero=True, phase=PROGRESSIF_NON_SAL), source=NON_SAL),
    kpi("SOC-HEURES-PERSONNEL", "Heures travaillées par le personnel (salariés et non-salariés)",
        "Hours worked by the own workforce (employees and non-employees)", "h", "Somme", "Calculé",
        formule="[SOC-HEURES-TRAV] + [SOC-HEURES-NON-SAL]",
        description=("Calculées par l'outil : heures travaillées par les salariés plus celles des non-salariés ; des heures de "
                     "non-salariés N/A comptent comme 0 (ESRS S1, §37(c), AR 25).",
                     "Calculated by the tool: hours worked by employees plus those of non-employees; N/A hours of "
                     "non-employees count as 0 (ESRS S1, §37(c), AR 25).")),
    _taux("SOC-TAUX-ACC-SALARIES", "Taux d'accidents du travail comptabilisables des salariés, par million d'heures travaillées",
          "Rate of recordable work-related accidents of employees, per million hours worked",
          "[SOC-ACCIDENTS-ENREG] * 1000000 / [SOC-HEURES-TRAV]",
          ("Calculé par l'outil : accidents comptabilisables des salariés par million d'heures travaillées par les salariés "
           "(ESRS S1, §37(c), AR 25). Recalculé à chaque niveau sur les totaux.",
           "Calculated by the tool: recordable accidents of employees per million hours worked by employees (ESRS S1, §37(c), "
           "AR 25). Recalculated at each level from the totals.")),
    _taux("SOC-TAUX-ACC-NON-SAL", "Taux d'accidents du travail comptabilisables des non-salariés, par million d'heures travaillées",
          "Rate of recordable work-related accidents of non-employees, per million hours worked",
          "[SOC-ACCIDENTS-NON-SAL] * 1000000 / [SOC-HEURES-NON-SAL]",
          ("Calculé par l'outil : accidents comptabilisables des non-salariés par million d'heures travaillées par les "
           "non-salariés (ESRS S1, §37(c), AR 25).",
           "Calculated by the tool: recordable accidents of non-employees per million hours worked by non-employees (ESRS S1, "
           "§37(c), AR 25).")),
    _taux("SOC-TAUX-ACCIDENTS", "Taux d'accidents du travail comptabilisables du personnel, par million d'heures travaillées",
          "Rate of recordable work-related accidents of the own workforce, per million hours worked",
          "[SOC-ACCIDENTS-TOUS] * 1000000 / [SOC-HEURES-PERSONNEL]",
          ("Calculé par l'outil : accidents comptabilisables du personnel (salariés et non-salariés) divisés par le total des "
           "heures travaillées par le personnel, multiplié par 1 000 000 : nombre d'accidents par million d'heures, environ "
           "500 personnes à temps plein pendant un an (ESRS S1, §37(c), AR 25). Recalculé à chaque niveau sur les totaux.",
           "Calculated by the tool: recordable accidents of the own workforce (employees and non-employees) divided by the "
           "total hours worked by the own workforce, multiplied by 1,000,000: accidents per million hours, about 500 "
           "full-time people over one year (ESRS S1, §37(c), AR 25). Recalculated at each level from the totals.")),
    kpi("SOC-MALADIES-PRO", "Cas de maladie liée au travail comptabilisables (salariés)",
        "Cases of recordable work-related ill health (employees)", "cas", description=_d(
            "Cas de maladie liée au travail des salariés ayant entraîné un décès ou une absence, connus pendant la période "
            "(signalés par la personne, un organisme d'indemnisation ou un professionnel de santé, ou repérés par la "
            "surveillance médicale) ; les troubles musculo-squelettiques en font partie, sous réserve des restrictions "
            "légales (ESRS S1, §37(d), AR 27).",
            "Cases of work-related ill health of employees that resulted in death or absence, known during the period "
            "(reported by the person, a compensation agency or a healthcare professional, or found by medical surveillance); "
            "musculoskeletal disorders are included, subject to legal restrictions (ESRS S1, §37(d), AR 27).",
            zero=True, phase=PROGRESSIF), source=SST),
    kpi("SOC-JOURS-PERDUS-AT-MP", "Jours perdus pour accident du travail et maladie liée au travail (salariés)",
        "Days lost to work-related accidents and ill health (employees)", "jours", description=_d(
            "Jours d'absence des salariés dus aux accidents du travail et aux maladies liées au travail comptabilisables, en "
            "jours calendaires, du premier jour complet au dernier jour d'absence, week-ends et jours fériés compris (ESRS S1, "
            "§37(e), AR 28).",
            "Days of absence of employees due to recordable work-related accidents and ill health, in calendar days, from the "
            "first full day to the last day of absence, weekends and public holidays included (ESRS S1, §37(e), AR 28).",
            zero=True, phase=PROGRESSIF), source=SST),
    # ------------------------------------------------------------------ S1-14 – équilibre vie professionnelle et vie privée
    _effectif("SOC-SAL-CONGES-FAMILLE", "Salariés ayant droit à des congés familiaux", "Employees entitled to family-related leave",
              _d("Salariés qui ont droit, par la loi, une politique de l'entreprise, un accord, leur contrat ou une convention "
                 "collective, à des congés familiaux (maternité, paternité, parental, proche aidant), à la fin de la période, en "
                 "nombre de personnes (ESRS S1, §39, AR 29, AR 30). Les types de congés concernés se précisent dans le texte des "
                 "méthodes.",
                 "Employees who are entitled, by law, a company policy, an agreement, their contract or a collective "
                 "agreement, to family-related leave (maternity, paternity, parental, carers' leave), at the end of the "
                 "period, as a headcount (ESRS S1, §39, AR 29, AR 30). The types of leave concerned are given in the methods "
                 "text.", zero=True, phase=PROGRESSIF)),
    _part("SOC-PART-CONGES-FAMILLE", "Part des salariés ayant droit à des congés familiaux",
          "Share of employees entitled to family-related leave", "[SOC-SAL-CONGES-FAMILLE] / [SOC-EFFECTIF]",
          ("Calculée par l'outil : salariés ayant droit à des congés familiaux divisés par l'effectif total (ESRS S1, §39).",
           "Calculated by the tool: employees entitled to family-related leave divided by the total headcount (ESRS S1, §39).")),
    # ------------------------------------------------------------------ S1-15 – rémunération
    # Rémunérations horaires propres à S1 : la VS ne les demande qu'à une entreprise déjà tenue de déclarer l'écart (B10
    # §42(b), N/A sinon) et précise sa moyenne dans son guide ; S1 les demande toujours, avec sa propre définition (AR 31,
    # AR 32) : pas de réutilisation des KPI de la VS, chaque norme son calcul.
    *[kpi(f"SOC-S1-REMU-H-{suffixe}", fr, en, "€/h", "Aucune", temps="derniere", niveau=HAUT, confidentialite=RESTREINT,
          description=(f"Niveau moyen de la rémunération horaire brute de {fr_d} de l'entreprise (ESRS S1, §41(a), AR 31) : "
                       "salaire de base ordinaire et toute autre rémunération offerte à tous les salariés, en espèces ou en "
                       "nature, reçue directement ou indirectement de l'employeur au titre de l'emploi (éléments "
                       "complémentaires ou variables) (AR 32). Méthode de l'ESRS S1, saisie une fois pour toute l'entreprise ; "
                       "dire dans le texte des méthodes comment la moyenne est calculée (AR 34). La norme volontaire VS et la "
                       "transparence des rémunérations ont leurs propres KPI et leur propre calcul. Donnée restreinte."
                       + C.MONNAIE[0],
                       f"Average gross hourly pay level of {en_d} of the company (ESRS S1, §41(a), AR 31): ordinary basic "
                       "salary and any other remuneration made available to all employees, in cash or in kind, received "
                       "directly or indirectly from the employer in respect of the employment (complementary or variable "
                       "components) (AR 32). Method of ESRS S1, entered once for the whole company; say in the methods text "
                       "how the average is calculated (AR 34). The Voluntary Standard VS and pay transparency have their own "
                       "KPIs and their own calculation. Restricted data." + C.MONNAIE[1]),
          source=PAIE)
      for suffixe, fr, en, fr_d, en_d in (
          ("HOMMES", "Rémunération horaire brute moyenne de tous les salariés hommes",
           "Average gross hourly pay level of all male employees", "tous les salariés hommes", "all male employees"),
          ("FEMMES", "Rémunération horaire brute moyenne de toutes les salariées femmes",
           "Average gross hourly pay level of all female employees", "toutes les salariées femmes", "all female employees"))],
    kpi("SOC-ECART-REMU-H", "Écart de rémunération entre femmes et hommes (horaire, tous les salariés)",
        "Gender pay gap (hourly, all employees)", "", "Formule", "Calculé", "Pourcentage",
        "([SOC-S1-REMU-H-HOMMES] - [SOC-S1-REMU-H-FEMMES]) / [SOC-S1-REMU-H-HOMMES]", decimales=1,
        description=("Calculé par l'outil, jamais saisi : écart entre la rémunération horaire brute moyenne des hommes et celle "
                     "des femmes, en part de celle des hommes, sur tous les salariés de l'entreprise ; positif quand les femmes "
                     "sont moins payées (ESRS S1, §41(a), AR 31 à AR 33). Écart non ajusté. Les rémunérations horaires "
                     "moyennes des hommes et des femmes sont saisies pour toute l'entreprise : l'écart se calcule à ce niveau. "
                     "Méthode de l'ESRS S1, sur ses propres rémunérations horaires : ni l'écart de la norme VS (B10 §42(b), "
                     "calculé dans le classeur de l'EFRAG), ni l'écart par employeur de la transparence des rémunérations.",
                     "Calculated by the tool, never entered: difference between the average gross hourly pay of men and that "
                     "of women, as a share of men's, over all the company's employees; positive when women are paid less "
                     "(ESRS S1, §41(a), AR 31 to AR 33). Unadjusted gap. The average hourly pay of men and of women is entered "
                     "for the whole company: the gap is calculated at that level. Method of ESRS S1, on its own hourly "
                     "pay figures: neither the gap of the Voluntary Standard VS (B10 §42(b), calculated in EFRAG's workbook) "
                     "nor the per-employer gap of pay transparency.")),
    kpi("SOC-REMU-PLUS-HAUTE", "Rémunération totale annuelle de la personne la mieux payée",
        "Annual total remuneration of the highest-paid individual", "€", "Aucune", temps="derniere", niveau=HAUT,
        confidentialite=CONFIDENTIEL,
        description=("Rémunération totale annuelle de la personne la mieux payée de l'entreprise : salaire de base, avantages en "
                     "espèces (primes, commissions, intéressement), avantages en nature (voiture, assurance santé…) et juste "
                     "valeur des intéressements à long terme de l'année (options, actions de performance…) (ESRS S1, §41(b), "
                     "AR 35). Donnée confidentielle : elle désigne une seule personne." + C.MONNAIE[0],
                     "Annual total remuneration of the company's highest-paid individual: base salary, cash benefits (bonuses, "
                     "commissions, profit-sharing), benefits in kind (car, health insurance…) and fair value of the year's "
                     "long-term incentives (stock options, performance shares…) (ESRS S1, §41(b), AR 35). Confidential data: "
                     "it points to one person." + C.MONNAIE[1]),
        source=PAIE),
    kpi("SOC-REMU-MEDIANE", "Rémunération totale annuelle médiane des salariés (hors la mieux payée)",
        "Median annual total remuneration of employees (excluding the highest-paid)", "€", "Aucune", temps="derniere",
        niveau=HAUT, confidentialite=RESTREINT,
        description=("Rémunération totale annuelle médiane de tous les salariés, sans la personne la mieux payée, avec les mêmes "
                     "éléments de rémunération : la moitié des salariés gagne plus, l'autre moitié moins (ESRS S1, §41(b), "
                     "AR 35). Une médiane ne se déduit pas de celles des entités : saisie pour toute l'entreprise." + C.MONNAIE[0],
                     "Median annual total remuneration of all employees, without the highest-paid individual, with the same pay "
                     "components: half of the employees earn more, half earn less (ESRS S1, §41(b), AR 35). A median cannot be "
                     "derived from those of the entities: entered for the whole company." + C.MONNAIE[1]),
        source=PAIE),
    kpi("SOC-RATIO-REMU", "Ratio de la rémunération totale annuelle", "Annual total remuneration ratio", "", "Formule", "Calculé",
        formule="[SOC-REMU-PLUS-HAUTE] / [SOC-REMU-MEDIANE]", decimales=1,
        description=("Calculé par l'outil : rémunération totale annuelle de la personne la mieux payée divisée par la médiane des "
                     "autres salariés ; un nombre de fois, sans unité (ESRS S1, §41(b), AR 35).",
                     "Calculated by the tool: annual total remuneration of the highest-paid individual divided by the median of "
                     "the other employees; a number of times, without unit (ESRS S1, §41(b), AR 35).")),
    # ------------------------------------------------------------------ S1-16 – incidents
    kpi("SOC-DISCRIMINATIONS", "Incidents de discrimination avérés", "Substantiated incidents of discrimination", "cas",
        description=_d("Incidents de discrimination au travail (genre, origine raciale ou ethnique, nationalité, religion ou "
                       "convictions, handicap, âge, orientation "
                       "sexuelle ou autre, harcèlement compris) avérés et constatés pendant la période : procédures judiciaires "
                       "ou non judiciaires et autres incidents, établis par des faits vérifiables et constatés par une "
                       "juridiction, l'OCDE ou une autorité administrative, sous réserve des règles de protection de la vie "
                       "privée (ESRS S1, §43(a), AR 37).",
                       "Incidents of discrimination at work (gender, racial or ethnic origin, nationality, religion or belief, "
                       "disability, "
                       "age, sexual orientation or other, harassment included) substantiated and identified during the period: "
                       "judicial or non-judicial proceedings and other incidents, evidenced by verifiable facts and formally "
                       "found by a court, the OECD or an administrative authority, subject to privacy rules (ESRS S1, §43(a), "
                       "AR 37).", zero=True),
        source=("Direction juridique, ressources humaines, mécanisme de plainte.", "Legal department, human resources, grievance mechanism.")),
    kpi("SOC-INCIDENTS-DH", "Incidents avérés touchant les droits humains du personnel (hors discriminations)",
        "Substantiated human rights incidents (own workforce, excluding discrimination)", "cas",
        description=_d("Incidents avérés de non-respect des droits humains reconnus au niveau international touchant le personnel, "
                       "constatés pendant la période, hors discriminations (comptées à part) : procédures judiciaires ou non "
                       "judiciaires et autres incidents, établis et constatés comme pour les discriminations (ESRS S1, §43(b), "
                       "AR 36).",
                       "Substantiated incidents of not respecting internationally recognised human rights connected to the own "
                       "workforce, identified during the period, excluding discrimination (counted separately): judicial or "
                       "non-judicial proceedings and other incidents, substantiated and found as for discrimination (ESRS S1, "
                       "§43(b), AR 36).", zero=True),
        source=("Direction juridique, ressources humaines, mécanisme de plainte.", "Legal department, human resources, grievance mechanism.")),
    kpi("SOC-AMENDES-DH", "Amendes, sanctions et indemnités pour ces incidents",
        "Fines, penalties and compensation for these incidents", "€", niveau=ENTITE,
        description=_d("Total des amendes, sanctions et dommages et intérêts imposés par des procédures judiciaires ou non "
                       "judiciaires pour des incidents de discrimination ou d'atteinte aux droits humains, comptabilisés dans les "
                       "états financiers de la période (ESRS S1, §43(c), AR 41)." + C.MONNAIE[0],
                       "Total fines, penalties and compensation for damages imposed through judicial or non-judicial proceedings "
                       "for incidents of discrimination or other human rights incidents, recognised in the financial statements "
                       "of the period (ESRS S1, §43(c), AR 41)." + C.MONNAIE[1], zero=True),
        source=("Comptabilité, direction juridique.", "Accounting, legal department.")),
])

# Entrée progressive de l'ESRS 1 §126(a) (toutes les normes thématiques avant 2027 pour les petites entreprises de la
# première vague) : même phrase que dans G1, ajoutée à chaque KPI propre au modèle ; les KPI repris de la norme VS ou
# du catalogue ne la portent pas (une seule définition, qui se lirait aussi dans une installation VS seule).
KPIS = dict(L.avec_phase_in(KPIS.items(), L.PHASE_IN_G1))

REGLES = {  # nom fr : (gauche, opérateur, droite, (description fr, en), nom en)
    "Femmes et hommes en contrat permanent ≤ salariés en contrat permanent": (
        "[SOC-EFF-CDI-F] + [SOC-EFF-CDI-H]", "<=", "[SOC-EFF-CDI]",
        ("Les femmes et les hommes en contrat permanent font partie des salariés en contrat permanent.",
         "Permanent female and male employees are part of the permanent employees."),
        "Permanent women and men ≤ permanent employees"),
    "Femmes et hommes en contrat temporaire ≤ salariés en contrat temporaire": (
        "[SOC-EFF-TEMP-F] + [SOC-EFF-TEMP-H]", "<=", "[SOC-EFF-TEMPORAIRES]",
        ("Les femmes et les hommes en contrat temporaire font partie des salariés en contrat temporaire.",
         "Temporary female and male employees are part of the temporary employees."),
        "Temporary women and men ≤ temporary employees"),
    "Contrats permanents et temporaires ≤ effectif total": (
        "[SOC-EFF-CDI] + [SOC-EFF-TEMPORAIRES]", "<=", "[SOC-EFFECTIF]",
        ("Un salarié est compté une seule fois, en contrat permanent ou temporaire.",
         "An employee is counted once, as permanent or temporary."),
        "Permanent and temporary employees ≤ total headcount"),
    "Salariés sans heures garanties ≤ effectif total": (
        "[SOC-EFF-HEURES-NON-GARANTIES]", "<=", "[SOC-EFFECTIF]",
        ("Les salariés sans nombre d'heures garanti font partie de l'effectif total.",
         "Non-guaranteed hours employees are part of the total headcount."),
        "Non-guaranteed hours employees ≤ total headcount"),
    "Salariés couverts par des représentants ≤ effectif total": (
        "[SOC-SAL-REPRESENTES]", "<=", "[SOC-EFFECTIF]",
        ("Les salariés des établissements dotés de représentants font partie de l'effectif total.",
         "Employees in establishments with workers' representatives are part of the total headcount."),
        "Employees covered by representatives ≤ total headcount"),
    "Salariés sous le salaire décent ≤ effectif total": (
        "[SOC-SAL-SOUS-DECENT]", "<=", "[SOC-EFFECTIF]",
        ("Les salariés qui ne perçoivent pas un salaire décent font partie de l'effectif total.",
         "Employees not paid an adequate wage are part of the total headcount."),
        "Employees below the adequate wage ≤ total headcount"),
    "Salariés ayant droit aux congés familiaux ≤ effectif total": (
        "[SOC-SAL-CONGES-FAMILLE]", "<=", "[SOC-EFFECTIF]",
        ("Les salariés qui ont droit à des congés familiaux font partie de l'effectif total.",
         "Employees entitled to family-related leave are part of the total headcount."),
        "Employees entitled to family leave ≤ total headcount"),
    "Personnes couvertes par la santé et la sécurité ≤ personnel": (
        "[SOC-SST-COUVERTS]", "<=", "[SOC-PERSONNEL]",
        ("Les personnes couvertes par le système de santé et de sécurité font partie du personnel (salariés et non-salariés).",
         "People covered by the health and safety management system are part of the own workforce (employees and "
         "non-employees)."),
        "People covered by health and safety ≤ own workforce"),
    "Décès par maladie liée au travail ≤ décès liés au travail des salariés": (
        "[SOC-DECES-MALADIE]", "<=", "[SOC-DECES]",
        ("Les décès des salariés dus à une maladie liée au travail font partie de leurs décès liés au travail.",
         "Fatalities of employees from work-related ill health are part of their work-related fatalities."),
        "Fatalities from ill health ≤ work-related fatalities of employees"),
    "Décès par maladie liée au travail ≤ cas de maladie liée au travail": (
        "[SOC-DECES-MALADIE]", "<=", "[SOC-MALADIES-PRO]",
        ("Un décès dû à une maladie liée au travail est aussi un cas comptabilisable de maladie liée au travail. Un décès "
         "de la période peut venir d'un cas connu une année précédente (S1 AR 27) : l'alerte se justifie alors.",
         "A fatality from work-related ill health is also a recordable case of work-related ill health. A fatality of the "
         "period can come from a case known in a previous year (S1 AR 27): the alert is then justified."),
        "Fatalities from ill health ≤ cases of ill health"),
}
# Règles reprises d'autres modèles (même définition) : effectifs de la norme VS et du catalogue commun.
REGLES_REPRISES = ["Effectif féminin ≤ effectif total", "Effectif masculin ≤ effectif total",
                   "Salariés couverts par une convention ≤ effectif total", "Salariés en situation de handicap ≤ effectif total"]


def _arbre_gdr(dr, partie):
    return C.arbre_gdr(PREFIXE, dr, partie, social=True)


SOCLE = C.socle("ESRS_S1", "1.1", "2026-11-19", [
    ("S1_1", "S1-1 – Politiques relatives au personnel", "S1-1 – Policies related to own workforce", [
        *_arbre_gdr("S1-1", "P"), ("SOC-PERSO-POLIT-COUVERTURE", "S1-1 · 10"),
        ("SOC-CODE-TRAITE", "S1-1 · 11"), ("SOC-CODE-FORCE", "S1-1 · 11"), ("SOC-CODE-ENFANTS", "S1-1 · 11")]),
    ("S1_2", "S1-2 – Dialogue, canaux pour faire part de préoccupations et réparation",
     "S1-2 – Engagement, channels to raise concerns and remedy", [
        ("SOC-PERSO-DIALOGUE", "S1-2 · 13"), ("SOC-PERSO-VULNERABLES", "S1-2 · 13(a)"),
        ("SOC-PERSO-ACCORDS-CADRES", "S1-2 · 13(b)"), ("SOC-PERSO-CANAUX", "S1-2 · 14"), ("SOC-PLAINTES", "S1-2 · 14"),
        ("SOC-PERSO-REPARATION", "S1-2 · 15")]),
    ("S1_3", "S1-3 – Actions et ressources relatives au personnel", "S1-3 – Actions and resources related to own workforce", [
        *_arbre_gdr("S1-3", "A"), ("SOC-PERSO-ACTIONS-IMPACTS", "S1-3 · 17(a)"), ("SOC-PERSO-ACTIONS-SUIVI", "S1-3 · 17(b)")]),
    ("S1_4", "S1-4 – Cibles relatives au personnel", "S1-4 – Targets related to own workforce", _arbre_gdr("S1-4", "T")),
    ("S1_5", "S1-5 – Caractéristiques des salariés", "S1-5 – Characteristics of the employees", [
        ("SOC-EFFECTIF", "S1-5 · 20(a)-(b)"), ("SOC-EFF-FEMMES", "S1-5 · 20(a)"), ("SOC-EFF-HOMMES", "S1-5 · 20(a)"),
        ("SOC-EFF-GENRE-AUTRE", "S1-5 · 20(a)"), ("SOC-EFF-GENRE-NC", "S1-5 · 20(a)"),
        ("SOC-EFF-CDI", "S1-5 · 20(c)(i)"), ("SOC-EFF-CDI-F", "S1-5 · 20(c)(i)"), ("SOC-EFF-CDI-H", "S1-5 · 20(c)(i)"),
        ("SOC-EFF-TEMPORAIRES", "S1-5 · 20(c)(ii)"), ("SOC-EFF-TEMP-F", "S1-5 · 20(c)(ii)"), ("SOC-EFF-TEMP-H", "S1-5 · 20(c)(ii)"),
        ("SOC-EFF-HEURES-NON-GARANTIES", "S1-5 · 20(c)(iii)"),
        ("SOC-DEPARTS-CDI", "S1-5 · 20(d)"), ("SOC-EFF-MOYEN", "S1-5 · 20(d)"), ("SOC-ROTATION-CDI", "S1-5 · 20(d)"),
        ("SOC-EFF-ECART-COMPTES", "S1-5 · 20(e)")]),
    ("S1_6", "S1-6 – Caractéristiques des non-salariés du personnel", "S1-6 – Characteristics of non-employees in the own workforce", [
        ("SOC-NON-SALARIES", "S1-6 · 22")]),
    ("S1_7", "S1-7 – Négociation collective et dialogue social", "S1-7 – Collective bargaining coverage and social dialogue", [
        ("SOC-SAL-CONVENTION", "S1-7 · 24(a)"), ("SOC-PART-CONVENTION", "S1-7 · 24(a)-(c)"),
        ("SOC-CONVENTION-EEE", "S1-7 · 24(b)"), ("SOC-SAL-REPRESENTES", "S1-7 · 25(a)"), ("SOC-PART-REPRESENTES", "S1-7 · 25(a)"),
        ("SOC-COMITE-EUROPEEN", "S1-7 · 25(b)")]),
    ("S1_8", "S1-8 – Mixité de la direction générale", "S1-8 – Gender diversity in top management", [
        ("SOC-DIRECTION-F", "S1-8 · 27"), ("SOC-DIRECTION-H", "S1-8 · 27"), ("SOC-DIRECTION-AUTRE", "S1-8 · 27"),
        ("SOC-DIRECTION-PART-F", "S1-8 · 27"), ("SOC-DIRECTION-PART-H", "S1-8 · 27")]),
    ("S1_9", "S1-9 – Salaires décents", "S1-9 – Adequate wages", [
        ("SOC-SALAIRE-DECENT", "S1-9 · 29"), ("SOC-SALAIRE-DECENT-REF", "S1-9 · 29"), ("SOC-SAL-SOUS-DECENT", "S1-9 · 29"),
        ("SOC-PART-SOUS-DECENT", "S1-9 · 29")]),
    ("S1_10", "S1-10 – Protection sociale", "S1-10 – Social protection", [
        ("SOC-PROTECTION-MALADIE", "S1-10 · 31(a)"), ("SOC-PROTECTION-CHOMAGE", "S1-10 · 31(b)"),
        ("SOC-PROTECTION-ACCIDENT", "S1-10 · 31(c)"), ("SOC-PROTECTION-MATERNITE", "S1-10 · 31(d)")]),
    ("S1_11", "S1-11 – Personnes handicapées", "S1-11 – Persons with disabilities", [
        ("SOC-HANDICAP", "S1-11 · 33"), ("SOC-PART-HANDICAP", "S1-11 · 33")]),
    ("S1_12", "S1-12 – Formation et développement des compétences", "S1-12 – Training and skills development metrics", [
        ("SOC-SAL-ENTRETIENS", "S1-12 · 35(a)"), ("SOC-PART-ENTRETIENS", "S1-12 · 35(a)"),
        ("SOC-HEURES-FORM", "S1-12 · 35(b)"), ("SOC-FORM-PAR-SAL", "S1-12 · 35(b)")]),
    ("S1_13", "S1-13 – Santé et sécurité", "S1-13 – Health and safety metrics", [
        ("SOC-SST-COUVERTS", "S1-13 · 37(a)"), ("SOC-PERSONNEL", "S1-13 · 37(a)"), ("SOC-PART-SST", "S1-13 · 37(a)"),
        ("SOC-DECES", "S1-13 · 37(b)"), ("SOC-DECES-MALADIE", "S1-13 · 37(b)(ii)"), ("SOC-DECES-NON-SAL", "S1-13 · 37(b)(i)"),
        ("SOC-DECES-SITE", "S1-13 · 37(b)(i)"), ("SOC-DECES-ACCIDENTS", "S1-13 · 37(b)(i)"), ("SOC-DECES-TOUS", "S1-13 · 37(b)"),
        ("SOC-ACCIDENTS-ENREG", "S1-13 · 37(c)"), ("SOC-ACCIDENTS-NON-SAL", "S1-13 · 37(c)"), ("SOC-ACCIDENTS-TOUS", "S1-13 · 37(c)"),
        ("SOC-HEURES-TRAV", "S1-13 · AR 25"), ("SOC-HEURES-NON-SAL", "S1-13 · AR 25"), ("SOC-HEURES-PERSONNEL", "S1-13 · AR 25"),
        ("SOC-TAUX-ACC-SALARIES", "S1-13 · 37(c)"), ("SOC-TAUX-ACC-NON-SAL", "S1-13 · 37(c)"), ("SOC-TAUX-ACCIDENTS", "S1-13 · 37(c)"),
        ("SOC-MALADIES-PRO", "S1-13 · 37(d)"), ("SOC-JOURS-PERDUS-AT-MP", "S1-13 · 37(e)")]),
    ("S1_14", "S1-14 – Équilibre entre vie professionnelle et vie privée", "S1-14 – Work-life balance metrics", [
        ("SOC-SAL-CONGES-FAMILLE", "S1-14 · 39"), ("SOC-PART-CONGES-FAMILLE", "S1-14 · 39")]),
    ("S1_15", "S1-15 – Rémunération", "S1-15 – Remuneration metrics", [
        ("SOC-S1-REMU-H-HOMMES", "S1-15 · AR 31"), ("SOC-S1-REMU-H-FEMMES", "S1-15 · AR 31"), ("SOC-ECART-REMU-H", "S1-15 · 41(a)"),
        ("SOC-REMU-PLUS-HAUTE", "S1-15 · 41(b)"), ("SOC-REMU-MEDIANE", "S1-15 · 41(b)"), ("SOC-RATIO-REMU", "S1-15 · 41(b)")]),
    ("S1_16", "S1-16 – Discriminations et autres incidents touchant les droits humains",
     "S1-16 – Incidents of discrimination and other human rights incidents", [
        ("SOC-DISCRIMINATIONS", "S1-16 · 43(a)"), ("SOC-INCIDENTS-DH", "S1-16 · 43(b)"), ("SOC-AMENDES-DH", "S1-16 · 43(c)")]),
    ("S1_M", "Indicateurs du personnel : méthodes et évolutions", "Own workforce metrics: methods and changes",
     _arbre_gdr("S1", "M")),
], regles=[*REGLES, *REGLES_REPRISES])
