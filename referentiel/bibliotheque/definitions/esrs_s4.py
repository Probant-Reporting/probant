"""ESRS S4 Consommateurs et utilisateurs finaux (ESRS révisées, règlement délégué (UE) 2026/1563) : modèle du lot E, construit
sur l'exemple ESRS E3 (méthode : note de conception de l'atelier, non publiée ; socle commun : _esrs_communs.py ; briques des
normes sociales : _esrs_lot_e.py).

Inventaire : lignes « ESRS_S4 » de esrs_coverage.csv (12 points de la liste de l'EFRAG du 28/08/2026). Choix :

- aucun indicateur chiffré (S4-1 à S4-4, pas d'exigence GDR-M) : textes rédigés, oui / non et tableaux saisis une fois pour
  l'entreprise (niveau « haut ») ; bloc commun des exigences générales avec la prise en compte des parties prenantes (§42(d)) ;
- S4-2 §12 : les canaux (texte) et le mécanisme de plaintes (oui / non) ; KPI de plaintes propre aux consommateurs (note
  explicative de l'EFRAG §137), ce n'est pas SOC-PLAINTES ;
- S4-3 §16 : incidents liés aux droits humains en texte, distinct du oui / non unique de la norme VS ;
- l'usage détourné ou illégal des produits et services par les consommateurs est hors du champ de la norme (S4 §7) : rien à
  collecter ; entrée progressive (ESRS 1 §125(a), §126(a), §127(a)) : une phrase par KPI.
"""
from . import _esrs_communs as C
from . import _esrs_lot_e as L

SOURCE = C.SOURCE
COUVERTURE = C.COUVERTURE
UNITES = C.UNITES
TYPES_REPONSE = C.TYPES_REPONSE

PREFIXE = "SOC-CONSO"
SUJET = ("les consommateurs et utilisateurs finaux", "consumers and end-users")
PHASE = L.PHASE_IN_SOCIAL

KPIS = dict([
    *L.bloc(PREFIXE, SUJET, PHASE),
    *L.kpis_sociaux("S4"),
    *L.indicateurs_propres(PREFIXE, SUJET, PHASE),
])

SOCLE = C.socle("ESRS_S4", "1.1", "2026-11-19", [
    ("S4_1", "S4-1 – Politiques relatives aux consommateurs et utilisateurs finaux",
     "S4-1 – Policies related to consumers and end-users", [
         *C.arbre_gdr(PREFIXE, "S4-1", "P", social=True), ("SOC-CONSO-POLIT-COUVERTURE", "S4-1 · 9")]),
    ("S4_2", "S4-2 – Dialogue, canaux pour faire part de préoccupations et réparation",
     "S4-2 – Engagement, channels to raise concerns and remediation", [
         ("SOC-CONSO-DIALOGUE", "S4-2 · 11"), ("SOC-CONSO-VULNERABLES", "S4-2 · 11"), ("SOC-CONSO-CANAUX", "S4-2 · 12"),
         ("SOC-CONSO-PLAINTES", "S4-2 · 12"), ("SOC-CONSO-REPARATION", "S4-2 · 13")]),
    ("S4_3", "S4-3 – Actions et ressources relatives aux consommateurs et utilisateurs finaux",
     "S4-3 – Actions and resources related to consumers and end-users", [
         *C.arbre_gdr(PREFIXE, "S4-3", "A"),
         ("SOC-CONSO-ACTIONS-IMPACTS", "S4-3 · 15(a)"), ("SOC-CONSO-ACTIONS-SUIVI", "S4-3 · 15(b)"),
         ("SOC-CONSO-INCIDENTS-DH", "S4-3 · 16")]),
    ("S4_4", "S4-4 – Cibles relatives aux consommateurs et utilisateurs finaux",
     "S4-4 – Targets related to consumers and end-users", [
         *C.arbre_gdr(PREFIXE, "S4-4", "T"), *L.arbre_indicateurs(PREFIXE, "S4-4")]),
])
