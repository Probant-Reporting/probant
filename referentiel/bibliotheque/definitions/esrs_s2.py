"""ESRS S2 Travailleurs de la chaîne de valeur (ESRS révisées, règlement délégué (UE) 2026/1563) : modèle du lot E, construit
sur l'exemple ESRS E3 (méthode : note de conception de l'atelier, non publiée ; socle commun : _esrs_communs.py ; briques des
normes sociales : _esrs_lot_e.py).

Inventaire : lignes « ESRS_S2 » de esrs_coverage.csv (15 points de la liste de l'EFRAG du 28/08/2026). Choix :

- aucun indicateur chiffré : la norme ne demande que des politiques, du dialogue, des actions, des incidents et des cibles
  (S2-1 à S2-4) ; pas d'exigence GDR-M. Tout est saisi une fois pour l'entreprise (niveau « haut ») : textes rédigés,
  oui / non, tableaux des actions et des cibles ;
- les exigences générales (ESRS 2 GDR-P, GDR-A, GDR-T) : bloc commun avec la prise en compte des parties prenantes
  (§42(d)) ; le §39 de l'ESRS 2 (dire qu'il n'y a pas de politique, d'action ou de cible) est le oui / non de chaque bloc ;
- S2-1 §11 : un oui / non par sujet (traite des êtres humains, travail forcé, travail des enfants), comme la norme S1 ;
- S2-2 §15 : les canaux (texte) et le mécanisme de plaintes (oui / non) ; un KPI de plaintes propre à chaque groupe de
  parties prenantes (note explicative de l'EFRAG §137) : ce n'est pas SOC-PLAINTES (le personnel de l'entreprise) ;
- S2-3 §19 : les incidents liés aux droits humains sont un texte, distinct du oui / non unique de la norme VS
  (SOC-INCIDENTS-CHAINE couvre ensemble la chaîne de valeur, les communautés et les consommateurs) : revue des doublons ;
- conditionnel (S2-2 §14(a) et (b), S2-3 §18(b)) : élément obligatoire, réponse N/A si la condition n'est pas remplie,
  condition écrite dans la description ; entrée progressive (ESRS 1 §125(a), §126(a), §127(a)) : une phrase par KPI.
"""
from . import _esrs_communs as C
from . import _esrs_lot_e as L

SOURCE = C.SOURCE
COUVERTURE = C.COUVERTURE
UNITES = C.UNITES
TYPES_REPONSE = C.TYPES_REPONSE

PREFIXE = "SOC-CHAINE"
SUJET = ("les travailleurs de la chaîne de valeur", "workers in the value chain")
NORME = "ESRS S2"
PHASE = L.PHASE_IN_SOCIAL

_propres = L.avec_phase_in([
    L.oui_non("SOC-CHAINE-TRAITE", "Les politiques de la chaîne de valeur couvrent la traite des êtres humains",
              "Value chain policies address trafficking in human beings",
              ("Les politiques de l'entreprise sur les travailleurs de la chaîne de valeur traitent-elles de la traite des êtres "
               "humains ? (ESRS S2-1 §11).",
               "Do the company's policies on workers in the value chain address trafficking in human beings? (ESRS S2-1 §11).")),
    L.oui_non("SOC-CHAINE-TRAVAIL-FORCE", "Les politiques de la chaîne de valeur couvrent le travail forcé ou obligatoire",
              "Value chain policies address forced or compulsory labour",
              ("Les politiques de l'entreprise sur les travailleurs de la chaîne de valeur traitent-elles du travail forcé ou "
               "obligatoire ? (ESRS S2-1 §11).",
               "Do the company's policies on workers in the value chain address forced or compulsory labour? (ESRS S2-1 §11).")),
    L.oui_non("SOC-CHAINE-TRAVAIL-ENFANTS", "Les politiques de la chaîne de valeur couvrent le travail des enfants",
              "Value chain policies address child labour",
              ("Les politiques de l'entreprise sur les travailleurs de la chaîne de valeur traitent-elles du travail des "
               "enfants ? (ESRS S2-1 §11).",
               "Do the company's policies on workers in the value chain address child labour? (ESRS S2-1 §11).")),
    L.oui_non("SOC-CHAINE-CODE-FOURNIS", "Code de conduite des fournisseurs", "Supplier code of conduct",
              ("L'entreprise a-t-elle un code de conduite pour ses fournisseurs ? (ESRS S2-1 §12). Les informations sur les "
               "relations avec les fournisseurs (ESRS G1-2) peuvent y renvoyer.",
               "Does the company have a supplier code of conduct? (ESRS S2-1 §12). The information on supplier relationships "
               "(ESRS G1-2) can refer to it.")),
    L.texte("SOC-CHAINE-ACCORDS-CADRES", "Accords-cadres mondiaux sur les droits humains des travailleurs de la chaîne de valeur",
            "Global framework agreements on human rights of value chain workers",
            ("Accords-cadres mondiaux ou autres résultats obtenus avec des représentants des travailleurs de la chaîne de valeur "
             "sur le respect des droits humains (ESRS S2-2 §14(b)). Répondre N/A s'il n'y en a pas.",
             "Global framework agreements or other outcomes reached with representatives of workers in the value chain on "
             "respecting human rights (ESRS S2-2 §14(b)). Answer N/A if there are none.")),
], PHASE)

KPIS = dict([
    *L.bloc(PREFIXE, SUJET, PHASE),
    *L.kpis_sociaux("S2"),
    *L.indicateurs_propres(PREFIXE, SUJET, PHASE),
    *_propres,
])

SOCLE = C.socle("ESRS_S2", "1.1", "2026-11-19", [
    ("S2_1", "S2-1 – Politiques relatives aux travailleurs de la chaîne de valeur",
     "S2-1 – Policies related to workers in the value chain", [
         *C.arbre_gdr(PREFIXE, "S2-1", "P", social=True),
         ("SOC-CHAINE-POLIT-COUVERTURE", "S2-1 · 10"),
         ("SOC-CHAINE-TRAITE", "S2-1 · 11"), ("SOC-CHAINE-TRAVAIL-FORCE", "S2-1 · 11"), ("SOC-CHAINE-TRAVAIL-ENFANTS", "S2-1 · 11"),
         ("SOC-CHAINE-CODE-FOURNIS", "S2-1 · 12")]),
    ("S2_2", "S2-2 – Dialogue, canaux pour faire part de préoccupations et réparation",
     "S2-2 – Engagement, channels to raise concerns and remediation", [
         ("SOC-CHAINE-DIALOGUE", "S2-2 · 14"), ("SOC-CHAINE-VULNERABLES", "S2-2 · 14(a)"),
         ("SOC-CHAINE-ACCORDS-CADRES", "S2-2 · 14(b)"), ("SOC-CHAINE-CANAUX", "S2-2 · 15"), ("SOC-CHAINE-PLAINTES", "S2-2 · 15"),
         ("SOC-CHAINE-REPARATION", "S2-2 · 16")]),
    ("S2_3", "S2-3 – Actions et ressources relatives aux travailleurs de la chaîne de valeur",
     "S2-3 – Actions and resources related to workers in the value chain", [
         *C.arbre_gdr(PREFIXE, "S2-3", "A"),
         ("SOC-CHAINE-ACTIONS-IMPACTS", "S2-3 · 18(a)"), ("SOC-CHAINE-ACTIONS-SUIVI", "S2-3 · 18(b)"),
         ("SOC-CHAINE-INCIDENTS-DH", "S2-3 · 19")]),
    ("S2_4", "S2-4 – Cibles relatives aux travailleurs de la chaîne de valeur",
     "S2-4 – Targets related to workers in the value chain", [
         *C.arbre_gdr(PREFIXE, "S2-4", "T"), *L.arbre_indicateurs(PREFIXE, "S2-4")]),
])
