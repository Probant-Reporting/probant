"""ESRS E4 Biodiversité et écosystèmes (ESRS révisées, règlement délégué (UE) 2026/1563) : modèle construit sur l'exemple
ESRS E3 (méthode : note de conception de l'atelier, non publiée ; socle commun : _esrs_communs.py).

Inventaire : lignes « ESRS_E4 » de esrs_coverage.csv (12 points de la liste de l'EFRAG du 28/08/2026) et une ligne du
règlement absente de la liste (E4 AR 9, voir plus bas). Choix :

- politiques, actions et cibles : bloc commun des exigences générales de l'ESRS 2 (``bloc_gdr``), saisi une fois pour
  l'entreprise (niveau « haut ») ; les exigences propres à E4 qui s'y ajoutent (E4 AR 3 sur les politiques, AR 6 sur les
  actions) sont écrites dans la description du texte concerné ;
- plan de transition (E4-1 §11) : un oui / non (condition du paragraphe : plan en place et rendu public) et un texte ;
- politiques de traçabilité et de sites dans ou près d'une zone sensible (E4-2 §13), compensations (E4-3 §15, E4-4 §17) :
  textes de l'entreprise ;
- E4-5 §19 (lieux liés à des impacts, risques ou opportunités importants) : une réponse par site, comme l'ESRS E4 AR 8 le
  permet (pas de liste exhaustive exigée) : un oui / non « site concerné », puis, pour un site concerné, deux textes
  (zones sensibles, nom et type ; activités liées aux impacts négatifs) ; un texte de l'entreprise pour les lieux qui ne
  sont pas des sites de l'arbre ;
- E4-5 §20 : aucun indicateur n'est défini par la norme (note explicative de l'EFRAG §127-128) : un tableau des
  indicateurs de l'entreprise (valeur, unité, périmètre), et les deux textes de méthode et d'évolution (GDR-M) ;
- E4 AR 9 (hors de la liste de l'EFRAG, note explicative §129) : « l'entreprise indique lesquels de ses impacts importants
  concernent la dégradation des terres, la désertification ou l'imperméabilisation des sols, et les activités qui touchent
  des espèces ou écosystèmes menacés » : deux oui / non, ligne « REG_E4_AR9 » de l'inventaire ;
- mesure transitoire (ESRS 1 §125(a), §126(a), §127(a)) : écrite dans la description de chaque KPI du modèle.
"""
from referentiel.bibliotheque.outils import kpi

from . import _esrs_communs as C

SOURCE = C.SOURCE
COUVERTURE = C.COUVERTURE
UNITES = C.UNITES
TYPES_REPONSE = C.TYPES_REPONSE

PREFIXE = "BIO"
SITES = ("Étude d'impact, autorisations d'exploiter, cartes des zones protégées, registres de l'exploitation du site.",
         "Impact assessment, operating permits, maps of protected areas, site operating records.")
PHASE = (" Mesure transitoire : une entreprise de la première vague peut omettre toute l'ESRS E4 pour les exercices ouverts avant "
         "2027, et toute autre entreprise pour ses deux premiers exercices de reporting (ESRS 1 §125(a), §126(a), §127(a)).",
         " Phase-in: a wave-one company may omit the whole of ESRS E4 for financial years starting before 2027, and any other "
         "company for its first two financial years of reporting (ESRS 1 §125(a), §126(a), §127(a)).")


def _d(fr, en):
    """Description (fr, en) avec la mesure transitoire de l'ESRS E4."""
    return fr + PHASE[0], en + PHASE[1]


def _ajouter(liste, code, fr, en):
    """Ajoute une phrase (fr, en) à la description d'un KPI du bloc commun (exigence propre à E4)."""
    for c, d in liste:
        if c == code:
            d["description"] = (d["description"][0] + fr, d["description"][1] + en)
            return
    raise KeyError(code)


def _bloc():
    liste = C.bloc_gdr(PREFIXE, ("la biodiversité et les écosystèmes", "biodiversity and ecosystems",
                                  "à la biodiversité et aux écosystèmes"))
    _ajouter(liste, "BIO-POLIT-CONTENU",
             " Préciser, si c'est le cas, si les politiques traitent les pratiques durables d'usage des terres ou d'agriculture, "
             "les pratiques durables sur les océans et les mers, et la déforestation (E4 AR 3).",
             " Say, where applicable, whether the policies address sustainable land or agricultural practices, sustainable "
             "oceans or seas practices, and deforestation (E4 AR 3).")
    _ajouter(liste, "BIO-ACT-DESC",
             " Les actions tiennent compte du droit des peuples autochtones au consentement libre, préalable et éclairé (E4 AR 6).",
             " The actions take into account the right of indigenous peoples to free, prior and informed consent (E4 AR 6).")
    for _, d in liste:  # mesure transitoire de toute la norme
        d["description"] = (d["description"][0] + PHASE[0], d["description"][1] + PHASE[1])
    return liste


KPIS = dict([
    *_bloc(),
    # ------------------------------------------------------------------ E4-1 – plan de transition
    kpi("BIO-PLAN", "Plan de transition pour la biodiversité en place et public",
        "Biodiversity transition plan in place and made public", "", "Décompte", reponse="OuiNon", niveau=C.HAUT,
        description=_d("L'entreprise a-t-elle un plan de transition qui transforme son modèle d'affaires et sa stratégie pour "
                       "contribuer à arrêter et inverser la perte de biodiversité (cadre mondial de Kunming-Montréal), et en a-t-elle "
                       "rendu publiques les caractéristiques clés ? « Rendu public » : accessible avant ou à la publication de l'"
                       "état de durabilité, par exemple sur son site ou dans ses rapports. Un plan climat qui intègre la "
                       "biodiversité peut convenir. Si oui, décrire le plan ci-dessous (E4-1 §11, E4 AR 1, AR 2).",
                       "Does the company have a transition plan that transforms its business model and strategy to contribute to "
                       "halting and reversing biodiversity loss (Kunming-Montreal Global Biodiversity Framework), and has it made "
                       "the key features public? ‘Made public’: available before or at the release of the sustainability "
                       "statement, for example on its website or in its reports. A climate plan that integrates biodiversity may "
                       "do. If yes, describe the plan below (E4-1 §11, E4 AR 1, AR 2).")),
    kpi("BIO-PLAN-TRANSITION", "Caractéristiques clés du plan de transition pour la biodiversité",
        "Key features of the biodiversity transition plan", "", "Aucune", reponse="Texte", niveau=C.HAUT,
        description=_d("Seulement si le plan existe et est public : ses caractéristiques clés (E4-1 §11). Un plan de ce type "
                       "contient en général des cibles, des actions clés, un plan financier et la gouvernance, et explique "
                       "comment la stratégie et le modèle d'affaires évolueront ; il peut traiter les synergies et les arbitrages "
                       "avec les autres plans de transition (E4 AR 1). Répondre N/A s'il n'y a pas de plan public.",
                       "Only if the plan exists and is public: its key features (E4-1 §11). Such a plan usually contains targets, "
                       "key actions, financial planning and governance, and explains how the strategy and business model will "
                       "evolve; it can address synergies and trade-offs with other transition plan objectives (E4 AR 1). Answer "
                       "N/A if there is no public plan.")),
    # ------------------------------------------------------------------ E4-2 – politiques (en plus du bloc commun)
    kpi("BIO-POLIT-TRACABILITE", "Politiques sur la biodiversité : traçabilité dans la chaîne de valeur",
        "Biodiversity policies: traceability in the value chain", "", "Aucune", reponse="Texte", niveau=C.HAUT,
        description=_d("Comment les politiques sur la biodiversité et les écosystèmes soutiennent la traçabilité des produits, "
                       "composants et matières premières qui ont, ou pourraient avoir, des impacts importants sur la biodiversité "
                       "dans la chaîne de valeur (E4-2 §13(a)). Répondre N/A s'il n'y a pas de politique sur ce point.",
                       "How the biodiversity and ecosystems policies support the traceability of the products, components and raw "
                       "materials that have, or could have, material impacts on biodiversity in the value chain (E4-2 §13(a)). "
                       "Answer N/A if there is no policy on this point.")),
    kpi("BIO-POLIT-SITES", "Politiques sur la biodiversité : sites dans ou près d'une zone sensible",
        "Biodiversity policies: sites in or near sensitive areas", "", "Aucune", reponse="Texte", niveau=C.HAUT,
        description=_d("Ce que les politiques sur la biodiversité et les écosystèmes prévoient pour les sites des activités propres "
                       "situés dans ou près d'une zone sensible pour la biodiversité (E4-2 §13(b)). Un site hors d'une zone est « "
                       "près » d'elle selon sa zone d'influence, que l'entreprise définit par exemple avec des distances tampons "
                       "propres à son activité (E4 AR 5). Répondre N/A si aucun site n'est concerné.",
                       "What the biodiversity and ecosystems policies provide for the sites of the own operations in or near a "
                       "biodiversity-sensitive area (E4-2 §13(b)). A site outside an area is ‘near’ it according to its area of "
                       "influence, which the company defines for example with buffer distances specific to its type of activity "
                       "(E4 AR 5). Answer N/A if no site is concerned.")),
    # ------------------------------------------------------------------ E4-3 et E4-4 – compensations
    kpi("BIO-COMPENSATIONS", "Compensations de biodiversité utilisées", "Biodiversity offsets used", "", "Aucune", reponse="Texte",
        niveau=C.HAUT,
        description=_d("Les compensations de biodiversité utilisées dans les actions : leur but, leurs effets financiers en "
                       "valeur monétaire, la surface, le type et les critères de qualité retenus, et les normes qu'elles "
                       "respectent (E4-3 §15). Une compensation est un résultat de conservation mesurable qui compense les "
                       "impacts négatifs inévitables, en plus de la prévention et de l'atténuation (glossaire). Écrire les montants "
                       "et les surfaces dans le texte. Répondre N/A s'il n'y en a pas.",
                       "The biodiversity offsets used in the actions: their aim, the financing effects in monetary terms, the area, "
                       "type and quality criteria applied, and the standards they comply with (E4-3 §15). An offset is a measurable "
                       "conservation outcome that compensates for unavoidable negative impacts, in addition to prevention and "
                       "mitigation (glossary). Write the amounts and areas in the text. Answer N/A if there are none.")),
    kpi("BIO-CIBLES-COMPENSATIONS", "Compensations de biodiversité utilisées dans les cibles",
        "Use of biodiversity offsets in the targets", "", "Aucune", reponse="Texte", niveau=C.HAUT,
        description=_d("Seulement si l'entreprise utilise des compensations de biodiversité pour fixer ses cibles : comment "
                       "elle les a utilisées (E4-4 §17). Répondre N/A sinon.",
                       "Only if the company uses biodiversity offsets in setting its targets: how it used them (E4-4 §17). Answer "
                       "N/A otherwise.")),
    # ------------------------------------------------------------------ E4-5 – lieux, zones sensibles, activités (§19)
    kpi("BIO-LIEUX-DESC", "Lieux des activités propres liés à des enjeux de biodiversité importants",
        "Locations of the own operations linked to material biodiversity matters", "", "Aucune", reponse="Texte", niveau=C.HAUT,
        description=_d("Les lieux des activités propres auxquels se rapportent les impacts, risques ou opportunités importants "
                       "liés à la biodiversité et aux écosystèmes, quand ils ne sont pas des sites de l'arbre des organisations "
                       "(E4-5 §19(a), E4 AR 8). Les sites de l'arbre répondent chacun par le oui / non « site concerné ». Pas de "
                       "liste exhaustive : l'entreprise peut regrouper les sites qui touchent la même zone sensible ou subissent "
                       "des impacts, risques ou opportunités semblables, sans masquer d'information importante. Répondre N/A si "
                       "tous les lieux sont des sites de l'arbre.",
                       "The locations of the own operations to which the material biodiversity and ecosystems impacts, risks or "
                       "opportunities relate, when they are not sites of the organisation tree (E4-5 §19(a), E4 AR 8). Each site of "
                       "the tree answers with the yes / no ‘site concerned’. No exhaustive list is needed: the company may group "
                       "the sites that affect the same sensitive area or have similar impacts, risks or opportunities, as long as "
                       "this does not hide material information. Answer N/A if all the locations are sites of the tree.")),
    kpi("BIO-SITE-IRO", "Site lié à un impact, risque ou opportunité important pour la biodiversité",
        "Site linked to a material biodiversity impact, risk or opportunity", "", "Décompte", reponse="OuiNon",
        description=_d("Le site est-il un lieu auquel se rapportent des impacts, risques ou opportunités importants liés à la "
                       "biodiversité et aux écosystèmes (E4-5 §19(a), E4 AR 8) ? Si oui, remplir les deux textes suivants.",
                       "Is the site a location to which material biodiversity and ecosystems impacts, risks or opportunities "
                       "relate (E4-5 §19(a), E4 AR 8)? If yes, fill in the next two texts.")),
    kpi("BIO-SITE-ZONE-IMPACT", "Zones sensibles touchées par le site (nom et type)",
        "Sensitive areas affected by the site (name and type)", "", "Aucune", reponse="Texte",
        description=_d("Pour un site concerné : la liste des zones sensibles pour la biodiversité liées à ses impacts négatifs "
                       "importants, avec le nom et le type de chaque zone (E4-5 §19(b)). Zones sensibles : zones protégées (Natura "
                       "2000, sites du patrimoine mondial naturel, sites Ramsar…), zones clés pour la biodiversité, zones marines "
                       "d'importance écologique ou biologique, habitats d'espèces de la liste rouge de l'UICN (glossaire). Répondre "
                       "N/A si le site n'est pas concerné ou n'a pas d'impact négatif important sur une zone sensible.",
                       "For a site concerned: the list of the biodiversity-sensitive areas related to its material negative "
                       "impacts, with the name and type of each area (E4-5 §19(b)). Sensitive areas: protected areas (Natura 2000, "
                       "UNESCO natural world heritage sites, Ramsar sites…), Key Biodiversity Areas, ecologically or biologically "
                       "significant marine areas, habitats of species of the IUCN Red List (glossary). Answer N/A if the site is not "
                       "concerned or has no material negative impact on a sensitive area."), source=SITES),
    kpi("BIO-SITE-ACTIVITES", "Activités du site liées à des impacts négatifs sur des zones sensibles",
        "Activities of the site linked to negative impacts on sensitive areas", "", "Aucune", reponse="Texte",
        description=_d("Pour un site qui a un impact négatif important sur une zone sensible : les activités du site liées à cet "
                       "impact (E4-5 §19(c)). Répondre N/A sinon.",
                       "For a site that has a material negative impact on a sensitive area: the activities of the site that are "
                       "linked to this impact (E4-5 §19(c)). Answer N/A otherwise."), source=SITES),
    # ------------------------------------------------------------------ E4-5 – indicateurs (§20) et AR 9
    kpi("BIO-INDICATEURS", "Indicateurs sur les impacts importants sur la biodiversité",
        "Metrics on the material impacts on biodiversity", "", "Aucune", reponse="ESRS-TAB-INDICATEURS", niveau=C.HAUT,
        description=_d("Une ligne par indicateur de l'entreprise sur ses impacts importants sur la biodiversité et les écosystèmes : "
                       "nom, valeur, unité, périmètre (E4-5 §20). La norme ne définit aucun indicateur. Selon le sujet important, "
                       "ils portent sur les facteurs de changement, l'état des espèces, l'état et l'étendue des écosystèmes ou les "
                       "services écosystémiques (E4 AR 10). Les données de terrain ou de télédétection sont les meilleures ; à défaut, "
                       "des estimations à partir des facteurs de pression (E4 AR 11). Préciser dans le texte de méthode la "
                       "fréquence de suivi, l'état et l'année de référence (E4 AR 12).",
                       "One row per company metric on its material impacts on biodiversity and ecosystems: name, value, unit, scope "
                       "(E4-5 §20). The standard defines no metric. Depending on the material sub-topic, they cover drivers of "
                       "change, the state of species, the condition and extent of ecosystems or ecosystem services (E4 AR 10). "
                       "Primary data from the field or remote sensing is best; otherwise estimates from pressure data (E4 AR 11). "
                       "Say in the methods text the monitoring frequency, the baseline condition and the baseline year (E4 AR 12)."),
        source=("Suivi écologique, relevés de terrain, imagerie satellite, études d'impact.",
                "Ecological monitoring, field surveys, satellite imagery, impact assessments.")),
    kpi("BIO-IMPACT-SOLS", "Impacts importants liés à la dégradation des terres, la désertification ou l'imperméabilisation des sols",
        "Material impacts related to land degradation, desertification or soil sealing", "", "Décompte", reponse="OuiNon",
        niveau=C.HAUT,
        description=_d("Parmi les impacts importants décrits dans l'analyse des impacts, risques et opportunités, certains "
                       "concernent-ils la dégradation des terres, la désertification ou l'imperméabilisation des sols (E4 AR 9, "
                       "pour E4-5 §20) ? Si oui, le texte des impacts importants (ESRS 2 IRO-2) le dit.",
                       "Among the material impacts described in the assessment of impacts, risks and opportunities, do any concern "
                       "land degradation, desertification or soil sealing (E4 AR 9, for E4-5 §20)? If yes, the text on the material "
                       "impacts (ESRS 2 IRO-2) says so.")),
    kpi("BIO-IMPACT-ESPECES", "Activités touchant des espèces ou des écosystèmes menacés",
        "Operations that affect threatened species or ecosystems", "", "Décompte", reponse="OuiNon", niveau=C.HAUT,
        description=_d("Parmi les impacts importants, certains concernent-ils des activités qui touchent des espèces ou des "
                       "écosystèmes menacés (E4 AR 9, pour E4-5 §20) ? Espèces menacées : espèces en danger de la liste rouge "
                       "européenne ou de la liste rouge de l'UICN ; écosystèmes menacés : écosystèmes en danger critique, en danger "
                       "ou vulnérables de la liste rouge des écosystèmes de l'UICN (glossaire). Si oui, le texte des impacts "
                       "importants (ESRS 2 IRO-2) le dit.",
                       "Among the material impacts, do any concern operations that affect threatened species or ecosystems (E4 AR "
                       "9, for E4-5 §20)? Threatened species: endangered species of the European Red List or the IUCN Red List of "
                       "Threatened Species; threatened ecosystems: ecosystems classed as critically endangered, endangered or "
                       "vulnerable in the IUCN Red List of Ecosystems (glossary). If yes, the text on the material impacts (ESRS 2 "
                       "IRO-2) says so.")),
])

SOCLE = C.socle("ESRS_E4", "1.1", "2026-11-19", [
    ("E4_1", "E4-1 – Plan de transition pour la biodiversité et les écosystèmes",
     "E4-1 – Biodiversity and ecosystems transition plan", [("BIO-PLAN", "E4-1 · 11"), ("BIO-PLAN-TRANSITION", "E4-1 · 11")]),
    ("E4_2", "E4-2 – Politiques relatives à la biodiversité et aux écosystèmes",
     "E4-2 – Policies related to biodiversity and ecosystems", [
         *C.arbre_gdr(PREFIXE, "E4-2", "P"), ("BIO-POLIT-TRACABILITE", "E4-2 · 13(a)"), ("BIO-POLIT-SITES", "E4-2 · 13(b)")]),
    ("E4_3", "E4-3 – Actions et ressources relatives à la biodiversité et aux écosystèmes",
     "E4-3 – Actions and resources related to biodiversity and ecosystems", [
         *C.arbre_gdr(PREFIXE, "E4-3", "A"), ("BIO-COMPENSATIONS", "E4-3 · 15")]),
    ("E4_4", "E4-4 – Cibles relatives à la biodiversité et aux écosystèmes",
     "E4-4 – Targets related to biodiversity and ecosystems", [
         *C.arbre_gdr(PREFIXE, "E4-4", "T"), ("BIO-CIBLES-COMPENSATIONS", "E4-4 · 17")]),
    ("E4_5", "E4-5 – Indicateurs relatifs aux changements de la biodiversité et des écosystèmes",
     "E4-5 – Metrics related to biodiversity and ecosystems change", [
         ("BIO-LIEUX-DESC", "E4-5 · 19(a)"), ("BIO-SITE-IRO", "E4-5 · 19(a)"), ("BIO-SITE-ZONE-IMPACT", "E4-5 · 19(b)"),
         ("BIO-SITE-ACTIVITES", "E4-5 · 19(c)"), ("BIO-INDICATEURS", "E4-5 · 20"), ("BIO-IMPACT-SOLS", "E4-5 · 20 ; AR 9"),
         ("BIO-IMPACT-ESPECES", "E4-5 · 20 ; AR 9"), *C.arbre_gdr(PREFIXE, "E4-5", "M")]),
])
