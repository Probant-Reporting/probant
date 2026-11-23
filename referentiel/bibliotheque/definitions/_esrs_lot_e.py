"""Briques du lot E des ESRS révisées (règlement délégué (UE) 2026/1563) : ESRS S2, S3, S4 et G1. Le nom commence par « _ » :
``definitions.charger`` ne le prend pas pour un modèle.

Les trois normes sociales S2, S3 et S4 ont la même structure (politiques, dialogue et plaintes, actions et incidents,
cibles) : leurs KPI communs sont écrits une seule fois (``kpis_sociaux``) avec les paragraphes et les exemples de chaque
norme. Ce fichier ne change rien au socle commun ``_esrs_communs.py`` ; il le complète pour ces quatre modèles :

- ``bloc`` : bloc des exigences générales de l'ESRS 2 (``C.bloc_gdr``, qui contracte « à les » en « aux ») avec la phrase
  sur l'entrée progressive ;
- ``texte``, ``oui_non`` : KPI rédigés ou oui / non, au niveau de l'entreprise.
"""
from referentiel.bibliotheque.outils import kpi

from . import _esrs_communs as C

# Entrée progressive (ESRS 1 §125 à 127, règlement 2026/1563) : une phrase dans la description de chaque KPI du modèle.
PHASE_IN_SOCIAL = (
    "Entrée progressive : les entreprises de la première vague peuvent l'omettre pour les exercices avant 2027, en donnant "
    "les informations de l'ESRS 2 §7 à 10 (BP-2), les autres entreprises pour leurs deux premiers exercices de reporting "
    "(ESRS 1 §125(a), §126(a) et §127(a)).",
    "Phase-in: wave-one companies may omit it for financial years before 2027, subject to the disclosures of ESRS 2 §7 to 10 "
    "(BP-2), other companies for their first two financial years of reporting (ESRS 1 §125(a), §126(a) and §127(a)).")
PHASE_IN_G1 = (
    "Entrée progressive : les entreprises de la première vague qui, à la date de clôture, ne dépassent pas un chiffre "
    "d'affaires net de 450 millions d'euros ou un effectif moyen de 1 000 salariés sur l'exercice peuvent l'omettre pour les "
    "exercices avant 2027, en donnant les informations de l'ESRS 2 §7 à 10 (BP-2) (ESRS 1 §126(a)).",
    "Phase-in: wave-one companies that, at the balance sheet date, do not exceed a net turnover of EUR 450 million or an "
    "average of 1,000 employees during the financial year may omit it for financial years before 2027, subject to the "
    "disclosures of ESRS 2 §7 to 10 (BP-2) (ESRS 1 §126(a)).")


def texte(code, fr, en, description, source=None):
    """Texte rédigé, une réponse pour l'entreprise."""
    return kpi(code, fr, en, "", "Aucune", reponse="Texte", niveau=C.HAUT, description=description,
               **({"source": source} if source else {}))


def oui_non(code, fr, en, description):
    """Oui / non, une réponse pour l'entreprise."""
    return kpi(code, fr, en, "", "Décompte", reponse="OuiNon", niveau=C.HAUT, description=description)


def avec_phase_in(kpis, phrase):
    """Ajoute la phrase sur l'entrée progressive à la description de chaque KPI (couples (code, définition))."""
    sortie = []
    for code, d in kpis:
        fr, en = d["description"]
        sortie.append((code, {**d, "description": (f"{fr} {phrase[0]}", f"{en} {phrase[1]}")}))
    return sortie


def bloc(prefixe, sujet, phrase, social=True, indicateurs=False):
    """Bloc des exigences générales de l'ESRS 2 pour un sujet, avec la phrase d'entrée progressive. S2 à S4 n'ont pas
    d'indicateurs propres (pas de GDR-M) ; G1 en a (G1-4 à G1-6)."""
    kpis = C.bloc_gdr(prefixe, sujet, social=social, indicateurs=indicateurs)
    return avec_phase_in(kpis, phrase)


# ------------------------------------------------------------------ S2, S3, S4 : ce que les trois normes ont en commun
# Chaque norme : son préfixe, la façon de nommer les personnes concernées (français : avec article, « des », « aux » ;
# anglais), ses paragraphes et ses numéros d'exigences d'application (AR), ses exemples.
SOCIAL = {
    "S2": dict(
        norme="ESRS S2", dr=("S2-1", "S2-2", "S2-3", "S2-4"), prefixe="SOC-CHAINE", des="des travailleurs de la chaîne de valeur",
        sujet=("les travailleurs de la chaîne de valeur", "workers in the value chain"),
        a=("aux travailleurs de la chaîne de valeur", "workers in the value chain"),
        tous=("tous les travailleurs de la chaîne de valeur", "all workers in the value chain"),
        precis=("des groupes précis", "specific groups"),
        vuln=("des travailleurs vulnérables de la chaîne de valeur", "vulnerable workers in the value chain"),
        marg=("vulnérables ou marginalisés", "vulnerable or marginalised"),
        ex_pol=("par exemple une tranche d'âge, ou les travailleurs d'une usine ou d'un pays",
                "for example an age group, or the workers of one factory or country"),
        ex_vuln=("par exemple les travailleuses, les travailleurs migrants, les travailleurs en situation de handicap",
                 "for example women workers, migrant workers, workers with disabilities"),
        ex_tension=("par exemple dans les achats ou les ventes", "for example in procurement or sales"),
        par=dict(pol=10, eng=14, vuln="14(a)", canaux=15, plaintes=15, rep=16, act="18(a)", suivi="18(b)", inc=19),
        ar=dict(eng=2, canaux=3, act=4, transition=5, inc="6 à 9", inc_def=6, inc_agg=8),
        dial_note=("", ""), inc_note=("", ""),
    ),
    "S3": dict(
        norme="ESRS S3", dr=("S3-1", "S3-2", "S3-3", "S3-4"), prefixe="SOC-COMMU", des="des communautés affectées",
        sujet=("les communautés affectées", "affected communities"),
        a=("aux communautés affectées", "affected communities"),
        tous=("toutes les communautés affectées", "all affected communities"),
        precis=("des communautés précises", "specific communities"),
        vuln=("des communautés affectées vulnérables", "vulnerable affected communities"),
        marg=("vulnérables ou marginalisées", "vulnerable or marginalised"),
        ex_pol=("par exemple une communauté de peuples autochtones ou une communauté qui vit autour d'un site",
                "for example a community of indigenous peoples or a community living around a site"),
        ex_vuln=("par exemple les femmes, les filles, les migrants, les personnes en situation de handicap",
                 "for example women, girls, migrants, persons with disabilities"),
        ex_tension=("par exemple les pratiques d'aménagement et d'acquisition de terres, ou d'exploitation et de financement de "
                    "matières premières",
                    "for example practices in planning and land acquisition, or in the exploitation and financing of raw "
                    "materials"),
        par=dict(pol=8, eng=11, vuln=11, canaux=13, plaintes=13, rep=14, act="16(a)", suivi="16(b)", inc=17),
        ar=dict(eng=2, canaux=4, act=5, transition=6, inc="7 à 11", inc_def=7, inc_agg=10),
        dial_note=(" Seulement si l'entreprise dialogue directement avec elles (voir l'élément oui / non précédent) ; répondre "
                   "N/A sinon.",
                   " Only if the company engages directly with them (see the previous yes / no item); answer N/A otherwise."),
        inc_note=(" Tenir compte des litiges juridiques sur les droits fonciers et sur le consentement libre, préalable et "
                  "éclairé des peuples autochtones (S3 AR 8).",
                  " Consider any legal disputes on land rights and on the free, prior and informed consent of indigenous "
                  "peoples (S3 AR 8)."),
    ),
    "S4": dict(
        norme="ESRS S4", dr=("S4-1", "S4-2", "S4-3", "S4-4"), prefixe="SOC-CONSO", des="des consommateurs et utilisateurs finaux",
        sujet=("les consommateurs et utilisateurs finaux", "consumers and end-users"),
        a=("aux consommateurs et utilisateurs finaux", "consumers and end-users"),
        tous=("tous les consommateurs et utilisateurs finaux", "all consumers and end-users"),
        precis=("des groupes précis", "specific groups"),
        vuln=("des consommateurs et utilisateurs finaux vulnérables", "vulnerable consumers and end-users"),
        marg=("vulnérables ou marginalisés", "vulnerable or marginalised"),
        ex_pol=("par exemple une tranche d'âge", "for example an age group"),
        ex_vuln=("par exemple les personnes en situation de handicap, les enfants",
                 "for example persons with disabilities, children"),
        ex_tension=("par exemple les pratiques de marketing, de vente et d'usage des données",
                    "for example practices related to marketing, sales and data use"),
        par=dict(pol=9, eng=11, vuln=11, canaux=12, plaintes=12, rep=13, act="15(a)", suivi="15(b)", inc=16),
        ar=dict(eng=2, canaux=3, act=4, transition=None, inc="5 à 8", inc_def=5, inc_agg=7),
        dial_note=("", ""), inc_note=("", ""),
    ),
}


def kpis_sociaux(cle, phrase=PHASE_IN_SOCIAL):
    """KPI que S2, S3 et S4 ont en commun, avec les paragraphes de la norme ``cle`` (« S2 », « S3 » ou « S4 »). Rend
    (liste de KPI, dict des codes par rôle pour l'arbre)."""
    p = SOCIAL[cle]
    n, pre, par, ar = p["norme"], p["prefixe"], p["par"], p["ar"]
    sj, a, en, des = p["sujet"][0], p["a"][0], p["sujet"][1], p["des"]

    def ref(i, x):
        """Référence citée dans une description : « ESRS S2-2 §14 »."""
        return f"{n}-{i} §{x}"

    ref_pol, ref_eng, ref_act = ref(1, par["pol"]), ref(2, par["eng"]), ref(3, par["act"])
    s = [
        texte(f"{pre}-POLIT-COUVERTURE", f"Politiques : {p['tous'][0]} ou {p['precis'][0]}",
              f"Policies: {p['tous'][1]} or {p['precis'][1]}",
              (f"Pour chaque politique : couvre-t-elle {p['tous'][0]} ou seulement {p['precis'][0]} ({p['ex_pol'][0]}) ? "
               f"Nommer les groupes concernés ({ref_pol}).",
               f"For each policy: does it cover {p['tous'][1]} or only {p['precis'][1]} ({p['ex_pol'][1]})? Name the groups "
               f"concerned ({ref_pol}).")),
        texte(f"{pre}-DIALOGUE", f"Dialogue avec {sj}", f"Engagement with {en}",
              (f"Comment l'entreprise dialogue directement avec {sj}, leurs représentants légitimes ou des intermédiaires "
               f"crédibles, et comment leurs points de vue éclairent ses décisions et ses actions pour gérer les impacts "
               f"réels et potentiels pendant l'année ({ref_eng}). Le dialogue peut prendre des formes variées : séances "
               f"d'information, consultation, participation ({n} AR {ar['eng']}).{p['dial_note'][0]}",
               f"How the company engages directly with {en}, their legitimate representatives or credible proxies, and how "
               f"their perspectives inform its decisions and activities to manage actual and potential impacts during the "
               f"year ({ref_eng}). Engagement can take different forms, such as information sessions, consultation or "
               f"participation ({n} AR {ar['eng']}).{p['dial_note'][1]}")),
        texte(f"{pre}-VULNERABLES", f"Points de vue {p['vuln'][0]}", f"Perspectives of {p['vuln'][1]}",
              (f"Seulement si l'entreprise agit pour comprendre les points de vue {des} qui peuvent être particulièrement {p['marg'][0]} "
               f"({p['ex_vuln'][0]}) : comment elle les recueille ({ref(2, par['vuln'])}). Répondre N/A si elle ne le fait pas.",
               f"Only if the company takes action to understand the perspectives of {en} who may be particularly "
               f"{p['marg'][1]} ({p['ex_vuln'][1]}): how it gains insight into them ({ref(2, par['vuln'])}). Answer N/A if it "
               f"takes no such action.")),
        texte(f"{pre}-CANAUX", f"Canaux ouverts {a} pour faire part de leurs préoccupations",
              f"Channels for {en} to raise concerns",
              (f"Canaux dont disposent {sj} pour porter leurs préoccupations ou leurs besoins directement à l'attention de "
               f"l'entreprise et les faire traiter, et comment l'entreprise évalue leur efficacité ({ref(2, par['canaux'])}). "
               f"Les critères d'efficacité des mécanismes de plainte non judiciaires du principe 31 des principes directeurs de "
               f"l'ONU peuvent servir ({n} AR {ar['canaux']}). Si l'entreprise protège contre les représailles les personnes "
               f"qui utilisent ces canaux et l'a déclaré dans la conduite des affaires (ESRS G1-1), elle peut y renvoyer.",
               f"Channels available to {en} to bring their concerns or needs directly to the company and have them addressed, "
               f"and how the company assesses their effectiveness ({ref(2, par['canaux'])}). The effectiveness criteria for "
               f"non-judicial grievance mechanisms of principle 31 of the UN Guiding Principles can be used ({n} AR "
               f"{ar['canaux']}). If the company protects the people who use these channels against retaliation and has "
               f"disclosed it under business conduct (ESRS G1-1), it can refer to that disclosure.")),
        oui_non(f"{pre}-PLAINTES", f"Mécanisme de traitement des plaintes pour {sj}", f"Grievance mechanism for {en}",
                (f"L'entreprise a-t-elle mis en place un mécanisme de traitement des plaintes que {sj} peuvent utiliser ? "
                 f"({ref(2, par['plaintes'])}). Décrire les canaux dans le texte « Canaux ouverts {a} pour faire part de leurs "
                 f"préoccupations ».",
                 f"Has the company put in place a grievance mechanism that {en} can use? ({ref(2, par['plaintes'])}). Describe "
                 f"the channels in the text « Channels for {en} to raise concerns ».")),
        texte(f"{pre}-REPARATION", f"Approche de la réparation pour {sj}", f"Approach to remediation for {en}",
              (f"Approche générale et processus pour réparer, ou coopérer à la réparation, quand l'entreprise a causé un impact "
               f"négatif important sur {sj} ou y a contribué ({ref(2, par['rep'])}).",
               f"General approach and processes to provide or cooperate in remediation where the company has caused or "
               f"contributed to a material negative impact on {en} ({ref(2, par['rep'])}).")),
        texte(f"{pre}-ACTIONS-IMPACTS", f"Actions contre les impacts négatifs importants sur {sj}",
              f"Actions on material negative impacts on {en}",
              (f"Actions clés menées, prévues ou en cours pour prévenir, atténuer, faire cesser, limiter et réparer les "
               f"impacts négatifs importants sur {sj}, y compris la façon d'agir quand ces actions entrent en tension avec "
               f"d'autres contraintes de l'activité ({p['ex_tension'][0]}) ({ref_act}). Les leviers d'influence et les actions "
               f"collectives (initiatives de plusieurs parties prenantes ou d'un secteur) en font partie ({n} AR {ar['act']})."
               + (f" Présenter les mesures contre les effets de la transition vers une économie bas carbone de façon à montrer "
                  f"le lien entre les sujets ({n} AR {ar['transition']})." if ar["transition"] else ""),
               f"Key actions taken, planned or under way to prevent, mitigate, bring to an end, minimise and remediate "
               f"material negative impacts on {en}, including the approach when these actions are in tension with other "
               f"business pressures ({p['ex_tension'][1]}) ({ref_act}). Leverage and collective actions (multi-stakeholder or "
               f"industry initiatives) are included ({n} AR {ar['act']})."
               + (f" Present the measures against the effects of the transition to a low-carbon economy in a way that shows "
                  f"the link between topics ({n} AR {ar['transition']})." if ar["transition"] else ""))),
        texte(f"{pre}-ACTIONS-SUIVI", f"Suivi de l'efficacité des actions sur {sj}", f"Effectiveness tracking of actions on {en}",
              (f"Seulement si des actions sur les impacts négatifs importants sont déclarées : comment l'entreprise suit et "
               f"évalue l'efficacité de ces actions pour les personnes concernées ({ref(3, par['suivi'])}). Si elle l'explique "
               f"dans les cibles (ESRS 2 GDR-T) ou dans un indicateur propre à l'entreprise (ESRS 2 GDR-M), un renvoi suffit. "
               f"Répondre N/A si aucune action sur les impacts "
               f"négatifs n'est déclarée.",
               f"Only if actions on material negative impacts are reported: how the company tracks and assesses the "
               f"effectiveness of these actions in delivering outcomes for the people concerned ({ref(3, par['suivi'])}). If it "
               f"explains this in the targets (ESRS 2 GDR-T) or in an entity-specific metric (ESRS 2 GDR-M), a reference is "
               f"enough. Answer N/A if no action on "
               f"negative impacts is reported.")),
        texte(f"{pre}-INCIDENTS-DH", f"Incidents liés aux droits humains concernant {sj}",
              f"Human rights incidents connected to {en}",
              (f"Incidents liés aux droits humains concernant {sj} relevés pendant la période ({ref(3, par['inc'])}), dans "
               f"le respect de la réglementation sur la vie privée. Ne déclarer que les cas établis et vérifiés : étayés par "
               f"des faits objectifs, et constatés par un tribunal, l'OCDE ou une autorité administrative ({n} AR "
               f"{ar['inc_def']}). Cela couvre les procédures judiciaires et non judiciaires et les autres incidents "
               f"que l'entreprise a enregistrés. Il est permis de regrouper les cas par type d'incident ou par personnes "
               f"concernées ({n} AR {ar['inc_agg']}).{p['inc_note'][0]} Écrire qu'il n'y en a pas, le cas échéant.",
               f"Human rights incidents connected to {en} identified during the period ({ref(3, par['inc'])}), subject to the "
               f"relevant privacy rules. Report only substantiated and verified instances: backed by objective, factual "
               f"information, and found by a court, the OECD or an administrative authority ({n} AR {ar['inc_def']}). This "
               f"covers judicial and non-judicial proceedings and other incidents the company registered. You may group the "
               f"cases by type of incident or by people concerned ({n} AR {ar['inc_agg']}).{p['inc_note'][1]} Write that there "
               f"were none, if that is the case.")),
    ]
    return avec_phase_in(s, phrase)


# ------------------------------------------------------------------ S2, S3, S4 : indicateurs propres à l'entreprise
def indicateurs_propres(prefixe, sujet, phrase):
    """S2 à S4 ne prescrivent aucun indicateur ; une entreprise qui suit le sujet avec ses propres indicateurs les publie
    selon l'ESRS 2 GDR-M (ESRS 2 §48 et AR 42 : « such as for ESRS S2-S4 topical standards that do not prescribe specific
    metrics »). Un tableau des indicateurs et les deux textes GDR-M du bloc commun, placés facultatifs (``arbre_indicateurs``)."""
    fr, en = sujet
    tableau = kpi(f"{prefixe}-INDICATEURS", f"Indicateurs propres à l'entreprise sur {fr}", f"Entity-specific metrics on {en}", "",
                  "Aucune", reponse="ESRS-TAB-INDICATEURS", niveau=C.HAUT,
                  description=("Seulement si l'entreprise suit ce sujet avec ses propres indicateurs (la norme n'en prescrit "
                               "pas) : une ligne par indicateur, avec sa valeur, son unité et son périmètre (ESRS 2 §48, AR 42). "
                               "Laisser vide sinon.",
                               "Only if the company tracks this topic with its own metrics (the standard prescribes none): one "
                               "row per metric, with its value, unit and scope (ESRS 2 §48, AR 42). Leave empty otherwise."),
                  source=C.SOURCE_CIBLES)
    gdr_m = [k for k in C.bloc_gdr(prefixe, sujet, indicateurs=True) if k[0].endswith(("-METHODES", "-EVOLUTION"))]
    return avec_phase_in([tableau, *gdr_m], phrase)


def arbre_indicateurs(prefixe, dr):
    """Place facultative des indicateurs propres (S2 à S4) : le tableau et les deux textes GDR-M."""
    return [(f"{prefixe}-INDICATEURS", f"{dr} · ESRS 2 §48, AR 42", False),
            *[(code, ref, False) for code, ref in C.arbre_gdr(prefixe, dr, "M")]]
