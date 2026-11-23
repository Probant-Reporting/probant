"""Transparence des rémunérations – écarts de rémunération entre femmes et hommes (directive (UE) 2023/970, article 9).

Source : texte de la directive au Journal officiel (L 132 du 17/05/2023), en français et en anglais, lu :
article 3 (définitions), article 9 (déclaration des écarts), article 10 (évaluation conjointe), articles 5 à 7
(obligations de transparence au quotidien). Aucune modification ni rectificatif à cette date ; la transposition française
n'est pas votée : la version 1.0 suit la directive seule, la loi française donnera une version 1.1 si elle précise une
méthode.

Choix de construction (règle du projet) :

- la directive demande une déclaration par employeur : les données se saisissent au niveau de l'entité juridique
  (niveau conseillé « entite » : niveau Entité ou Filiale de l'installation) ;
- les écarts moyens ne sont jamais saisis : chaque entité saisit ses moyennes et ses effectifs, l'outil en tire des
  totaux (moyenne × effectif) additionnés vers le haut, et recalcule l'écart à chaque niveau sur ces totaux (agrégation
  « Formule ») : l'écart du groupe est juste, ce n'est pas une moyenne des écarts ;
- les médianes et les quartiles ne se calculent pas à partir de totaux : saisis par l'entité, sans valeur au-dessus
  (agrégation « Aucune ») ;
- les rémunérations moyennes sont des données « Restreint » (KPI sensibles : collecte/sensibles.py).
"""
from referentiel.bibliotheque.outils import kpi

SOURCE = [  # titre, éditeur, version et dates : ceux du document (comparés au registre des références par un test de l'atelier)
    {"titre": "Directive (EU) 2023/970 (pay transparency)",
     "editeur": "European Parliament and Council of the European Union", "version": "OJ L 132, 17/05/2023", "date": "2023-05-10",
     "url": "https://eur-lex.europa.eu/eli/dir/2023/970/oj", "consulte_le": "2026-11-17",
     "licence": "EU law: reuse allowed with acknowledgement of the source (Commission Decision 2011/833/EU)"},
]

ENTITE = "entite"
SENSIBLE = "Restreint"

# Phrases répétées
NA_NON_SOUMIS = (" Un employeur qui ne déclare pas cette année répond N/A, à cette donnée comme à toutes les autres données de "
                 "paie (sinon le total du groupe serait faux).",
                 " An employer that does not report this year answers N/A, here and for all the other pay data (otherwise "
                 "the group total would be wrong).")
METHODE = (" Méthode de calcul : celle fixée par le droit national (par exemple pour les salariés à temps partiel).",
           " Calculation method: the one set by national law (for example for part-time workers).")
DONNEE_CALCUL = ("Donnée de calcul, calculée par l'outil : elle s'additionne d'une entité à l'autre, pour que l'écart du groupe "
                 "soit recalculé sur les totaux.",
                 "Calculation data, calculated by the tool: it adds up from one entity to the next, so that the group gap is "
                 "recalculated from the totals.")
PAIE = ("Paie.", "Payroll.")


def _d(fr, en, na=False, methode=False):
    """Description (fr, en), avec les phrases du N/A d'un employeur qui ne déclare pas et de la méthode nationale."""
    return (fr + (METHODE[0] if methode else "") + (NA_NON_SOUMIS[0] if na else ""),
            en + (METHODE[1] if methode else "") + (NA_NON_SOUMIS[1] if na else ""))


def _ecart(moy_h, moy_f):
    """Formule d'un écart en part de la moyenne des hommes : (H − F) / H, chaque moyenne recalculée depuis ses totaux."""
    return f"({moy_h} - {moy_f}) / ({moy_h})"


TYPES_REPONSE = [
    ("SOC-TAB-ECART-CAT", ("Écarts par catégorie de travailleurs", "Gaps by category of workers"), "tableau", [
        {"code": "categorie", "libelle": {"fr": "Catégorie de travailleurs", "en": "Category of workers"}, "type": "texte"},
        {"code": "femmes", "libelle": {"fr": "Femmes", "en": "Women"}, "type": "nombre", "unite": "salariés"},
        {"code": "hommes", "libelle": {"fr": "Hommes", "en": "Men"}, "type": "nombre", "unite": "salariés"},
        {"code": "ecart_base", "libelle": {"fr": "Écart sur le salaire de base (%)", "en": "Gap in basic wage or salary (%)"},
         "type": "nombre"},
        {"code": "ecart_variable", "libelle": {"fr": "Écart sur la part variable (%)", "en": "Gap in variable components (%)"},
         "type": "nombre"}]),
]

UNITES = [  # code, symbole anglais, libellé (fr, en), nombre entier, décimales, famille
    ("€/h", "€/h", ("euro par heure", "euro per hour"), False, 2, "Monnaie"),
]


def _quartile(n, fr_rang, en_rang):
    """Part des femmes (saisie) et des hommes (calculée) dans le quartile n."""
    f, h = f"SOC-QUARTILE-{n}-F", f"SOC-QUARTILE-{n}-H"
    return [
        kpi(f, f"Part des femmes dans le quartile {n} ({fr_rang})", f"Share of women in pay quartile {n} ({en_rang})", "",
            "Aucune", reponse="Pourcentage", temps="derniere", niveau=ENTITE,
            description=_d("Rangez les travailleurs du plus bas au plus haut niveau de rémunération et coupez la liste en quatre "
                           f"groupes de même taille. Part des femmes dans le groupe {n} ({fr_rang}).",
                           "Rank the workers from the lowest to the highest pay level and cut the list into four groups of the "
                           f"same size. Share of women in group {n} ({en_rang}).", na=True, methode=True),
            source=PAIE),
        kpi(h, f"Part des hommes dans le quartile {n} ({fr_rang})", f"Share of men in pay quartile {n} ({en_rang})", "",
            "Aucune", type_="Calculé", reponse="Pourcentage", formule=f"1 - [{f}]",
            description=("Calculée par l'outil : 100 % moins la part des femmes du même quartile. Pas de valeur au-dessus de "
                         "l'entité : les quartiles d'un groupe ne se déduisent pas de ceux de ses entités.",
                         "Calculated by the tool: 100% minus the share of women in the same quartile. No value above the "
                         "entity: the quartiles of a group cannot be derived from those of its entities.")),
    ]


KPIS = dict([
    # ------------------------------------------------------------------ déclaration
    kpi("SOC-ECART-DECL-SOUMIS", "Employeur tenu de déclarer cette année", "Employer required to report this year", "",
        "Décompte", reponse="OuiNon", temps="derniere", niveau=ENTITE,
        description=("Oui si l'employeur doit déclarer ses écarts de rémunération pour cette année. Seuils de la directive : "
                     "250 travailleurs ou plus, chaque année (premier rapport en 2027 sur l'année 2026) ; 150 à 249, tous les "
                     "trois ans (premier rapport en 2027) ; 100 à 149, tous les trois ans (premier rapport en 2031). Moins de "
                     "100 : déclaration volontaire, sauf si le droit national l'impose. Le droit national fixe les dates exactes.",
                     "Yes if the employer must report its pay gaps for this year. Thresholds of the directive: 250 workers or "
                     "more, every year (first report in 2027 on the year 2026); 150 to 249, every three years (first report in "
                     "2027); 100 to 149, every three years (first report in 2031). Fewer than 100: voluntary, unless national "
                     "law requires it. National law sets the exact dates.")),
    # ------------------------------------------------------------------ données de paie (saisies par l'entité)
    kpi("SOC-REMU-NB-F", "Femmes prises en compte dans les écarts", "Women included in the pay gap calculation", "salariés",
        temps="derniere", niveau=ENTITE,
        description=_d("Nombre de travailleuses de l'employeur prises en compte dans le calcul des rémunérations moyennes : "
                       "tous les contrats, temps partiel, contrats à durée déterminée et intérimaires compris quand le droit "
                       "national les rattache à l'employeur.",
                       "Number of female workers of the employer included in the calculation of average pay: all contracts, "
                       "including part-time and fixed-term workers, and agency workers when national law assigns them to the "
                       "employer.", na=True),
        source=PAIE),
    kpi("SOC-REMU-NB-H", "Hommes pris en compte dans les écarts", "Men included in the pay gap calculation", "salariés",
        temps="derniere", niveau=ENTITE,
        description=_d("Nombre de travailleurs masculins de l'employeur pris en compte dans le calcul des rémunérations "
                       "moyennes, sur le même périmètre que les femmes.",
                       "Number of male workers of the employer included in the calculation of average pay, on the same "
                       "perimeter as women.", na=True),
        source=PAIE),
    kpi("SOC-REMU-MOY-AN-F", "Rémunération annuelle brute moyenne des femmes", "Average gross annual pay of women", "€",
        "Aucune", temps="derniere", niveau=ENTITE, confidentialite=SENSIBLE,
        description=_d("Moyenne de la rémunération brute annuelle des femmes prises en compte : salaire de base et tous les "
                       "autres éléments, en espèces ou en nature (primes, part variable, avantages).",
                       "Average gross annual pay of the women included: basic wage or salary and all other components, in cash "
                       "or in kind (bonuses, variable pay, benefits).", na=True, methode=True),
        source=PAIE),
    kpi("SOC-REMU-MOY-AN-H", "Rémunération annuelle brute moyenne des hommes", "Average gross annual pay of men", "€",
        "Aucune", temps="derniere", niveau=ENTITE, confidentialite=SENSIBLE,
        description=_d("Moyenne de la rémunération brute annuelle des hommes pris en compte, avec les mêmes éléments que pour "
                       "les femmes.",
                       "Average gross annual pay of the men included, with the same components as for women.",
                       na=True, methode=True),
        source=PAIE),
    kpi("SOC-REMU-MOY-HOR-F", "Rémunération horaire brute moyenne des femmes", "Average gross hourly pay of women", "€/h",
        "Aucune", temps="derniere", niveau=ENTITE, confidentialite=SENSIBLE,
        description=_d("Moyenne de la rémunération brute horaire des femmes prises en compte (rémunération annuelle de chacune "
                       "rapportée à ses heures rémunérées).",
                       "Average gross hourly pay of the women included (the annual pay of each one divided by her paid hours).",
                       na=True, methode=True),
        source=PAIE),
    kpi("SOC-REMU-MOY-HOR-H", "Rémunération horaire brute moyenne des hommes", "Average gross hourly pay of men", "€/h",
        "Aucune", temps="derniere", niveau=ENTITE, confidentialite=SENSIBLE,
        description=_d("Moyenne de la rémunération brute horaire des hommes pris en compte (rémunération annuelle de chacun "
                       "rapportée à ses heures rémunérées).",
                       "Average gross hourly pay of the men included (the annual pay of each one divided by his paid hours).",
                       na=True, methode=True),
        source=PAIE),
    kpi("SOC-REMU-VAR-NB-F", "Femmes qui reçoivent une part variable", "Women who receive variable pay", "salariés",
        temps="derniere", niveau=ENTITE,
        description=_d("Nombre de femmes prises en compte qui ont reçu une part variable ou complémentaire pendant l'année "
                       "(primes, commissions, intéressement…). Saisir 0 s'il n'y en a pas.",
                       "Number of the women included who received a complementary or variable component during the year "
                       "(bonuses, commissions, profit-sharing…). Enter 0 if there is none.", na=True),
        source=PAIE),
    kpi("SOC-REMU-VAR-NB-H", "Hommes qui reçoivent une part variable", "Men who receive variable pay", "salariés",
        temps="derniere", niveau=ENTITE,
        description=_d("Nombre d'hommes pris en compte qui ont reçu une part variable ou complémentaire pendant l'année. "
                       "Saisir 0 s'il n'y en a pas.",
                       "Number of the men included who received a complementary or variable component during the year. Enter 0 "
                       "if there is none.", na=True),
        source=PAIE),
    kpi("SOC-REMU-VAR-MOY-F", "Part variable annuelle moyenne des femmes qui en reçoivent une",
        "Average annual variable pay of women who receive it", "€", "Aucune", temps="derniere", niveau=ENTITE,
        confidentialite=SENSIBLE,
        description=_d("Moyenne des parts variables ou complémentaires brutes de l'année, sur les seules femmes qui en ont reçu "
                       "une. N/A si aucune femme n'en a reçu.",
                       "Average gross complementary or variable components of the year, over the women who received one only. "
                       "N/A if no woman received one.", na=True, methode=True),
        source=PAIE),
    kpi("SOC-REMU-VAR-MOY-H", "Part variable annuelle moyenne des hommes qui en reçoivent une",
        "Average annual variable pay of men who receive it", "€", "Aucune", temps="derniere", niveau=ENTITE,
        confidentialite=SENSIBLE,
        description=_d("Moyenne des parts variables ou complémentaires brutes de l'année, sur les seuls hommes qui en ont reçu "
                       "une. N/A si aucun homme n'en a reçu.",
                       "Average gross complementary or variable components of the year, over the men who received one only. "
                       "N/A if no man received one.", na=True, methode=True),
        source=PAIE),
    # ------------------------------------------------------------------ données de calcul (totaux additionnés)
    kpi("SOC-REMU-TOT-AN-F", "Total des rémunérations annuelles des femmes", "Total annual pay of women", "€",
        type_="Calculé", formule="[SOC-REMU-MOY-AN-F] * [SOC-REMU-NB-F]", description=DONNEE_CALCUL),
    kpi("SOC-REMU-TOT-AN-H", "Total des rémunérations annuelles des hommes", "Total annual pay of men", "€",
        type_="Calculé", formule="[SOC-REMU-MOY-AN-H] * [SOC-REMU-NB-H]", description=DONNEE_CALCUL),
    kpi("SOC-REMU-TOT-HOR-F", "Somme des rémunérations horaires des femmes", "Sum of the hourly pay of women", "€/h",
        type_="Calculé", formule="[SOC-REMU-MOY-HOR-F] * [SOC-REMU-NB-F]", description=DONNEE_CALCUL),
    kpi("SOC-REMU-TOT-HOR-H", "Somme des rémunérations horaires des hommes", "Sum of the hourly pay of men", "€/h",
        type_="Calculé", formule="[SOC-REMU-MOY-HOR-H] * [SOC-REMU-NB-H]", description=DONNEE_CALCUL),
    kpi("SOC-REMU-VAR-TOT-F", "Total des parts variables des femmes", "Total variable pay of women", "€",
        type_="Calculé", formule="[SOC-REMU-VAR-MOY-F] * [SOC-REMU-VAR-NB-F]", description=DONNEE_CALCUL),
    kpi("SOC-REMU-VAR-TOT-H", "Total des parts variables des hommes", "Total variable pay of men", "€",
        type_="Calculé", formule="[SOC-REMU-VAR-MOY-H] * [SOC-REMU-VAR-NB-H]", description=DONNEE_CALCUL),
    # ------------------------------------------------------------------ écarts (article 9.1 a à d)
    kpi("SOC-ECART-MOY-HOR", "Écart de rémunération moyen (horaire)", "Gender pay gap (hourly)", "", "Formule",
        type_="Calculé", reponse="Pourcentage",
        formule=_ecart("[SOC-REMU-TOT-HOR-H] / [SOC-REMU-NB-H]", "[SOC-REMU-TOT-HOR-F] / [SOC-REMU-NB-F]"),
        description=("Calculé par l'outil : écart entre la rémunération horaire moyenne des hommes et celle des femmes, en part "
                     "de celle des hommes. Positif quand les femmes sont moins payées. Recalculé à chaque niveau sur les "
                     "totaux : l'écart du groupe n'est pas la moyenne des écarts des entités. Méthode de la directive "
                     "(UE) 2023/970, par employeur ; la norme VS et l'ESRS S1 ont leurs propres KPI et leur propre calcul.",
                     "Calculated by the tool: difference between the average hourly pay of men and that of women, as a share "
                     "of men's. Positive when women are paid less. Recalculated at each level from the totals: the group gap "
                     "is not the average of the entities' gaps. Method of Directive (EU) 2023/970, per employer; the Voluntary "
                     "Standard VS and ESRS S1 have their own KPIs and their own calculation.")),
    kpi("SOC-ECART-MOY-AN", "Écart de rémunération moyen (annuel)", "Gender pay gap (annual)", "", "Formule",
        type_="Calculé", reponse="Pourcentage",
        formule=_ecart("[SOC-REMU-TOT-AN-H] / [SOC-REMU-NB-H]", "[SOC-REMU-TOT-AN-F] / [SOC-REMU-NB-F]"),
        description=("Calculé par l'outil, comme l'écart horaire, à partir des rémunérations annuelles moyennes.",
                     "Calculated by the tool, like the hourly gap, from the average annual pay.")),
    kpi("SOC-ECART-MED-HOR", "Écart de rémunération médian (horaire)", "Median gender pay gap (hourly)", "", "Aucune",
        reponse="Pourcentage", temps="derniere", niveau=ENTITE,
        description=_d("Écart entre la rémunération horaire médiane des hommes et celle des femmes, en part de celle des hommes "
                       "(la médiane partage les travailleurs en deux moitiés : l'une gagne plus, l'autre moins). Saisi par "
                       "l'entité : la médiane d'un groupe ne se déduit pas de celles de ses entités.",
                       "Difference between the median hourly pay of men and that of women, as a share of men's (the median "
                       "splits the workers into two halves: one earns more, the other less). Entered by the entity: the median "
                       "of a group cannot be derived from those of its entities.", na=True, methode=True),
        source=PAIE),
    kpi("SOC-ECART-MED-AN", "Écart de rémunération médian (annuel)", "Median gender pay gap (annual)", "", "Aucune",
        reponse="Pourcentage", temps="derniere", niveau=ENTITE,
        description=_d("Comme l'écart médian horaire, à partir des rémunérations annuelles.",
                       "Like the hourly median gap, from the annual pay.", na=True, methode=True),
        source=PAIE),
    kpi("SOC-ECART-VAR-MOY", "Écart moyen sur la part variable", "Gender pay gap in variable pay", "", "Formule",
        type_="Calculé", reponse="Pourcentage",
        formule=_ecart("[SOC-REMU-VAR-TOT-H] / [SOC-REMU-VAR-NB-H]", "[SOC-REMU-VAR-TOT-F] / [SOC-REMU-VAR-NB-F]"),
        description=("Calculé par l'outil : écart entre la part variable moyenne des hommes et celle des femmes qui en reçoivent "
                     "une, en part de celle des hommes. Recalculé à chaque niveau sur les totaux.",
                     "Calculated by the tool: difference between the average variable pay of the men and of the women who "
                     "receive it, as a share of men's. Recalculated at each level from the totals.")),
    kpi("SOC-ECART-VAR-MED", "Écart médian sur la part variable", "Median gender pay gap in variable pay", "", "Aucune",
        reponse="Pourcentage", temps="derniere", niveau=ENTITE,
        description=_d("Écart entre la part variable médiane des hommes et celle des femmes qui en reçoivent une, en part de "
                       "celle des hommes. Saisi par l'entité.",
                       "Difference between the median variable pay of the men and of the women who receive it, as a share of "
                       "men's. Entered by the entity.", na=True, methode=True),
        source=PAIE),
    # ------------------------------------------------------------------ part variable (article 9.1 e)
    kpi("SOC-REMU-VAR-PART-F", "Part des femmes qui reçoivent une part variable", "Share of women who receive variable pay", "",
        "Formule", type_="Calculé", reponse="Pourcentage", formule="[SOC-REMU-VAR-NB-F] / [SOC-REMU-NB-F]",
        description=("Calculée par l'outil, à chaque niveau.", "Calculated by the tool, at each level.")),
    kpi("SOC-REMU-VAR-PART-H", "Part des hommes qui reçoivent une part variable", "Share of men who receive variable pay", "",
        "Formule", type_="Calculé", reponse="Pourcentage", formule="[SOC-REMU-VAR-NB-H] / [SOC-REMU-NB-H]",
        description=("Calculée par l'outil, à chaque niveau.", "Calculated by the tool, at each level.")),
    # ------------------------------------------------------------------ quartiles (article 9.1 f)
    *_quartile(1, "le plus bas", "lowest"),
    *_quartile(2, "inférieur", "lower middle"),
    *_quartile(3, "supérieur", "upper middle"),
    *_quartile(4, "le plus haut", "highest"),
    # ------------------------------------------------------------------ catégories de travailleurs (9.1 g et 10)
    kpi("SOC-ECART-CATEGORIES", "Écarts par catégorie de travailleurs", "Gender pay gap by category of workers", "", "Aucune",
        reponse="SOC-TAB-ECART-CAT", temps="aucune", niveau=ENTITE,
        description=_d("Une ligne par catégorie de travailleurs (personnes qui font le même travail ou un travail de même valeur, "
                       "regroupées par l'employeur selon des critères neutres : compétences, efforts, responsabilités, "
                       "conditions de travail). Pour chaque catégorie : nombre de femmes et d'hommes, écart sur le salaire de "
                       "base et écart sur la part variable, en % de la rémunération moyenne des hommes.",
                       "One row per category of workers (people who do the same work or work of equal value, grouped by the "
                       "employer on neutral criteria: skills, effort, responsibility, working conditions). For each category: "
                       "number of women and men, gap in basic wage or salary and gap in variable components, as a % of the "
                       "average pay of men.", na=True),
        source=("Paie et classification des emplois.", "Payroll and job classification.")),
    kpi("SOC-ECART-CAT-5PCT", "Écart d'au moins 5 % dans une catégorie", "Gap of at least 5% in a category", "",
        "Décompte", reponse="OuiNon", temps="derniere", niveau=ENTITE,
        description=_d("Oui si l'écart de rémunération moyen entre femmes et hommes atteint 5 % ou plus dans au moins une "
                       "catégorie de travailleurs.",
                       "Yes if the average pay gap between women and men is 5% or more in at least one category of workers.",
                       na=True)),
    kpi("SOC-EVAL-CONJOINTE-REQUISE", "Évaluation conjointe des rémunérations requise", "Joint pay assessment required", "",
        "Décompte", reponse="OuiNon", temps="derniere", niveau=ENTITE,
        description=_d("Oui si un écart d'au moins 5 % dans une catégorie n'est ni justifié par des critères objectifs et "
                       "neutres, ni corrigé dans les six mois qui suivent la déclaration : l'employeur doit alors mener une "
                       "évaluation conjointe avec les représentants du personnel.",
                       "Yes if a gap of at least 5% in a category is neither justified by objective, gender-neutral criteria nor "
                       "remedied within six months of the report: the employer must then carry out a joint pay assessment with "
                       "the workers' representatives.", na=True)),
    kpi("SOC-EVAL-CONJOINTE-MENEE", "Évaluation conjointe menée et communiquée", "Joint pay assessment carried out and shared",
        "", "Décompte", reponse="OuiNon", temps="derniere", niveau=ENTITE,
        description=_d("Oui si l'évaluation conjointe a été menée avec les représentants du personnel, puis mise à la "
                       "disposition des travailleurs et transmise à l'autorité de contrôle. N/A si elle n'est pas requise.",
                       "Yes if the joint pay assessment was carried out with the workers' representatives, then made available "
                       "to the workers and sent to the monitoring body. N/A if it is not required.", na=True)),
    # ------------------------------------------------------------------ validation et communication (9.6 à 9.9)
    kpi("SOC-ECART-CONFIRME", "Exactitude confirmée par la direction", "Accuracy confirmed by management", "",
        "Décompte", reponse="OuiNon", temps="derniere", niveau=ENTITE,
        description=_d("Oui si la direction a confirmé l'exactitude des informations, après consultation des représentants du "
                       "personnel (qui ont accès à la méthode de calcul).",
                       "Yes if management confirmed the accuracy of the information, after consulting the workers' "
                       "representatives (who have access to the calculation method).", na=True)),
    kpi("SOC-ECART-TRANSMIS", "Informations transmises à l'autorité", "Information sent to the authority", "",
        "Décompte", reponse="OuiNon", temps="derniere", niveau=ENTITE,
        description=_d("Oui si toutes les informations de la déclaration (écarts, part variable, quartiles, catégories) ont été "
                       "transmises à l'autorité nationale chargée de les recueillir.",
                       "Yes if all the information of the report (gaps, variable pay, quartiles, categories) was sent to the "
                       "national authority in charge of collecting it.", na=True)),
    kpi("SOC-ECART-CAT-DIFFUSE", "Écarts par catégorie communiqués aux travailleurs",
        "Gaps by category shared with the workers", "", "Décompte", reponse="OuiNon", temps="derniere", niveau=ENTITE,
        description=_d("Oui si les écarts par catégorie de travailleurs ont été communiqués à tous les travailleurs et à leurs "
                       "représentants.",
                       "Yes if the gaps by category of workers were shared with all the workers and their representatives.",
                       na=True)),
    kpi("SOC-ECART-PUBLIE", "Écarts publiés par l'employeur", "Gaps published by the employer", "",
        "Décompte", reponse="OuiNon", temps="derniere", niveau=ENTITE,
        description=("Facultatif. Oui si l'employeur publie aussi ses écarts (sauf ceux par catégorie), par exemple sur son "
                     "site internet.",
                     "Optional. Yes if the employer also publishes its gaps (except those by category), for example on its "
                     "website.")),
    # ------------------------------------------------------------------ transparence au quotidien (articles 5 à 7)
    kpi("SOC-REMU-INFO-CANDIDATS", "Rémunération de départ indiquée aux candidats", "Starting pay given to applicants", "",
        "Décompte", reponse="OuiNon", temps="derniere", niveau=ENTITE,
        description=("Oui si les candidats reçoivent, avant l'entretien (par exemple dans l'offre d'emploi), la rémunération de "
                     "départ du poste ou sa fourchette, et les règles de la convention collective qui s'y appliquent.",
                     "Yes if applicants receive, before the interview (for example in the job vacancy notice), the starting "
                     "pay of the position or its range, and the rules of the collective agreement that apply to it.")),
    kpi("SOC-REMU-HISTO-NON-DEMANDE", "Aucune question sur la rémunération passée", "No question on pay history", "",
        "Décompte", reponse="OuiNon", temps="derniere", niveau=ENTITE,
        description=("Oui si les recruteurs ne demandent jamais aux candidats leur rémunération actuelle ou passée.",
                     "Yes if recruiters never ask applicants about their current or previous pay.")),
    kpi("SOC-REMU-CRITERES-ACCES", "Critères de rémunération accessibles aux travailleurs",
        "Pay criteria accessible to the workers", "", "Décompte", reponse="OuiNon", temps="derniere", niveau=ENTITE,
        description=("Oui si les travailleurs ont facilement accès aux critères, objectifs et neutres, qui fixent leur "
                     "rémunération, leur niveau de rémunération et sa progression. Un État peut dispenser les employeurs de "
                     "moins de 50 travailleurs de la partie sur la progression.",
                     "Yes if the workers have easy access to the objective, gender-neutral criteria that set their pay, their "
                     "pay level and its progression. A Member State can exempt employers with fewer than 50 workers from the "
                     "part on progression.")),
    kpi("SOC-REMU-INFO-DROIT", "Travailleurs informés de leur droit à l'information", "Workers informed of their right to information",
        "", "Décompte", reponse="OuiNon", temps="derniere", niveau=ENTITE,
        description=("Oui si, cette année, tous les travailleurs ont été informés de leur droit à connaître leur niveau de "
                     "rémunération et les niveaux moyens, par sexe, de leur catégorie, et de la façon de le demander (réponse "
                     "écrite dans les deux mois).",
                     "Yes if, this year, all the workers were informed of their right to know their pay level and the average "
                     "pay levels, by sex, of their category, and of how to ask for it (written answer within two months).")),
])

REGLES = {  # nom fr : (gauche, opérateur, droite, (description fr, en), nom en)
    "Femmes avec part variable ≤ femmes prises en compte": ("[SOC-REMU-VAR-NB-F]", "<=", "[SOC-REMU-NB-F]", (
        "Les femmes qui reçoivent une part variable font partie des femmes prises en compte.",
        "Women who receive variable pay are part of the women included."), "Women with variable pay ≤ women included"),
    "Hommes avec part variable ≤ hommes pris en compte": ("[SOC-REMU-VAR-NB-H]", "<=", "[SOC-REMU-NB-H]", (
        "Les hommes qui reçoivent une part variable font partie des hommes pris en compte.",
        "Men who receive variable pay are part of the men included."), "Men with variable pay ≤ men included"),
}

# Arbre : (code du thème, nom fr, nom en, contenu) ; KPI = code, (code, référence) ou (code, référence, obligatoire).
SOCLE = {
    "code": "TRANSPARENCE_REMU",
    "fichier": "transparence_remunerations.json",
    "couleur": "#9C3D63",
    "version": "1.2",
    "date": "2026-11-19",
    "ordre": 20,
    "thematique": ("Social", "Social"),
    "nom": ("Transparence des rémunérations – écarts entre femmes et hommes", "Pay transparency – gender pay gap reporting"),
    "description": (
        "Déclaration des écarts de rémunération entre femmes et hommes demandée par la directive européenne 2023/970, une par "
        "employeur (saisie au niveau de l'entité) : écarts moyens et médians, part variable, quartiles, écarts par catégorie, "
        "évaluation conjointe et obligations de transparence. Les écarts moyens sont recalculés pour le groupe sur les "
        "totaux ; les médianes et les quartiles restent propres à chaque entité.",
        "Gender pay gap reporting required by the European directive 2023/970, one report per employer (entered at entity "
        "level): mean and median gaps, variable pay, quartiles, gaps by category, joint pay assessment and transparency "
        "obligations. Mean gaps are recalculated for the group from the totals; medians and quartiles stay specific to each "
        "entity."),
    "arbre": [
        ("DECLARATION", "Déclaration de l'année", "Reporting year", [
            ("SOC-ECART-DECL-SOUMIS", "Art. 9(2) to 9(5)", False)]),
        ("PAIE", "Données de paie", "Pay data", [
            ("SOC-REMU-NB-F", "Art. 9(1)"), ("SOC-REMU-NB-H", "Art. 9(1)"),
            ("SOC-REMU-MOY-HOR-F", "Art. 3(1)(b)-(c)"), ("SOC-REMU-MOY-HOR-H", "Art. 3(1)(b)-(c)"),
            ("SOC-REMU-MOY-AN-F", "Art. 3(1)(b)-(c)"), ("SOC-REMU-MOY-AN-H", "Art. 3(1)(b)-(c)"),
            ("SOC-REMU-VAR-NB-F", "Art. 9(1)(e)"), ("SOC-REMU-VAR-NB-H", "Art. 9(1)(e)"),
            ("SOC-REMU-VAR-MOY-F", "Art. 9(1)(b)"), ("SOC-REMU-VAR-MOY-H", "Art. 9(1)(b)")]),
        ("ECARTS", "Écarts de rémunération", "Pay gaps", [
            ("SOC-ECART-MOY-HOR", "Art. 9(1)(a)"), ("SOC-ECART-MOY-AN", "Art. 9(1)(a)"),
            ("SOC-ECART-MED-HOR", "Art. 9(1)(c)"), ("SOC-ECART-MED-AN", "Art. 9(1)(c)"),
            ("SOC-ECART-VAR-MOY", "Art. 9(1)(b)"), ("SOC-ECART-VAR-MED", "Art. 9(1)(d)"),
            ("SOC-REMU-VAR-PART-F", "Art. 9(1)(e)"), ("SOC-REMU-VAR-PART-H", "Art. 9(1)(e)")]),
        ("QUARTILES", "Quartiles de rémunération", "Pay quartiles", [
            (f"SOC-QUARTILE-{n}-{s}", "Art. 9(1)(f)") for n in (1, 2, 3, 4) for s in ("F", "H")]),
        ("CATEGORIES", "Catégories de travailleurs et évaluation conjointe", "Categories of workers and joint pay assessment", [
            ("SOC-ECART-CATEGORIES", "Art. 9(1)(g)"), ("SOC-ECART-CAT-5PCT", "Art. 10(1)(a)"),
            ("SOC-EVAL-CONJOINTE-REQUISE", "Art. 10(1)"), ("SOC-EVAL-CONJOINTE-MENEE", "Art. 10(3)")]),
        ("COMMUNICATION", "Validation et communication", "Approval and communication", [
            ("SOC-ECART-CONFIRME", "Art. 9(6)"), ("SOC-ECART-TRANSMIS", "Art. 9(7)"), ("SOC-ECART-CAT-DIFFUSE", "Art. 9(9)"),
            ("SOC-ECART-PUBLIE", "Art. 9(7)", False)]),
        ("PRATIQUES", "Transparence au quotidien", "Everyday transparency", [
            ("SOC-REMU-INFO-CANDIDATS", "Art. 5(1)"), ("SOC-REMU-HISTO-NON-DEMANDE", "Art. 5(2)"),
            ("SOC-REMU-CRITERES-ACCES", "Art. 6(1)"), ("SOC-REMU-INFO-DROIT", "Art. 7(3)")]),
        ("CALCUL", "Données de calcul", "Calculation data", [
            "SOC-REMU-TOT-HOR-F", "SOC-REMU-TOT-HOR-H", "SOC-REMU-TOT-AN-F", "SOC-REMU-TOT-AN-H",
            "SOC-REMU-VAR-TOT-F", "SOC-REMU-VAR-TOT-H"]),
    ],
    "regles": ["Femmes avec part variable ≤ femmes prises en compte", "Hommes avec part variable ≤ hommes pris en compte"],
}
