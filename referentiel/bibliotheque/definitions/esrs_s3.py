"""ESRS S3 Communautés affectées (ESRS révisées, règlement délégué (UE) 2026/1563) : modèle du lot E, construit sur l'exemple
ESRS E3 (méthode : note de conception de l'atelier, non publiée ; socle commun : _esrs_communs.py ; briques des normes
sociales : _esrs_lot_e.py).

Inventaire : lignes « ESRS_S3 » de esrs_coverage.csv (15 points de la liste de l'EFRAG du 28/08/2026). Choix :

- aucun indicateur chiffré (S3-1 à S3-4, pas d'exigence GDR-M) : textes rédigés, oui / non et tableaux saisis une fois pour
  l'entreprise (niveau « haut ») ; bloc commun des exigences générales avec la prise en compte des parties prenantes (§42(d)) ;
- S3-2 §11 « si et comment » : un oui / non (dialogue direct) et un texte (comment), selon la note explicative de l'EFRAG
  §63 ;
- S3-2 §12 (peuples autochtones) : deux éléments conditionnels (droits particuliers dont le consentement libre, préalable et
  éclairé ; consultation sur le mode et les paramètres du dialogue, oui / non et texte) ; réponse N/A quand aucune
  communauté affectée n'est un peuple autochtone ;
- S3-3 §17 : incidents liés aux droits humains en texte, distinct du oui / non unique de la norme VS ; KPI de plaintes
  propre aux communautés (note explicative §137), ce n'est pas SOC-PLAINTES ;
- entrée progressive (ESRS 1 §125(a), §126(a), §127(a)) : une phrase par KPI.
"""
from . import _esrs_communs as C
from . import _esrs_lot_e as L

SOURCE = C.SOURCE
COUVERTURE = C.COUVERTURE
UNITES = C.UNITES
TYPES_REPONSE = C.TYPES_REPONSE

PREFIXE = "SOC-COMMU"
SUJET = ("les communautés affectées", "affected communities")
PHASE = L.PHASE_IN_SOCIAL

_propres = L.avec_phase_in([
    L.oui_non("SOC-COMMU-DIALOGUE-DIRECT", "Dialogue direct avec les communautés affectées",
              "Direct engagement with affected communities",
              ("L'entreprise dialogue-t-elle directement avec les communautés affectées, leurs représentants légitimes ou des "
               "intermédiaires crédibles ? Si oui, expliquer comment dans le texte « Dialogue avec les communautés affectées » "
               "(ESRS S3-2 §11).",
               "Does the company engage directly with affected communities, their legitimate representatives or credible "
               "proxies? If yes, explain how in the text « Engagement with affected communities » (ESRS S3-2 §11).")),
    L.texte("SOC-COMMU-POLIT-AUTOCHTONES", "Politiques sur les impacts sur les peuples autochtones",
            "Policies on impacts on indigenous peoples",
            ("Dispositions particulières des politiques pour prévenir et traiter les impacts sur les peuples autochtones "
             "(ESRS S3-1 §9). Écrire qu'il n'y en a pas, le cas échéant.",
             "Particular policy provisions for preventing and addressing impacts on indigenous peoples (ESRS S3-1 §9). Write "
             "that there are none, if that is the case.")),
    L.texte("SOC-COMMU-AUTOCHTONES-CLPE", "Droits des peuples autochtones, dont le consentement libre, préalable et éclairé",
            "Rights of indigenous peoples, including free, prior and informed consent",
            ("Seulement si des communautés affectées sont des peuples autochtones : comment l'entreprise tient compte de leurs "
             "droits particuliers dans son dialogue et les fait respecter, dont le droit au consentement libre, préalable et "
             "éclairé pour leurs biens culturels, intellectuels, religieux et spirituels, pour les activités qui touchent leurs "
             "terres et territoires, et pour les mesures législatives ou administratives qui les touchent (ESRS S3-2 §12). Par "
             "exemple : la procédure pour obtenir leur consentement et négocier de bonne foi en cas de déplacement ou "
             "d'occupation (S3 AR 3). Répondre N/A si aucune communauté affectée n'est un peuple autochtone.",
             "Only if affected communities are indigenous peoples: how the company takes into account and ensures respect of "
             "their particular rights in its engagement, including the right to free, prior and informed consent for their "
             "cultural, intellectual, religious and spiritual property, for activities affecting their lands and territories, "
             "and for legislative or administrative measures that affect them (ESRS S3-2 §12). For example: the process to "
             "obtain their consent and to ensure good-faith negotiations when relocation or occupation occurs (S3 AR 3). "
             "Answer N/A if no affected community is an indigenous people.")),
    L.oui_non("SOC-COMMU-AUTOCHTONES-CONS", "Peuples autochtones consultés sur le dialogue",
              "Indigenous peoples consulted on the engagement",
              ("Seulement si l'entreprise dialogue avec des peuples autochtones : les a-t-elle consultés sur le mode et les "
               "paramètres de ce dialogue (par exemple l'ordre du jour, la nature, le calendrier) ? (ESRS S3-2 §12). Répondre "
               "N/A s'il n'y a pas de dialogue avec des peuples autochtones.",
               "Only if the company engages with indigenous peoples: have they been consulted on the mode and parameters of "
               "the engagement (for example the agenda, nature and timing)? (ESRS S3-2 §12). Answer N/A if there is no "
               "engagement with indigenous peoples.")),
    L.texte("SOC-COMMU-AUTOCHT-CONS-DESC", "Consultation des peuples autochtones sur le dialogue",
            "How indigenous peoples were consulted on the engagement",
            ("Seulement si l'entreprise dialogue avec des peuples autochtones : comment ils ont été consultés sur le mode et "
             "les paramètres du dialogue (ESRS S3-2 §12). Répondre N/A s'il n'y a pas de dialogue avec des peuples autochtones.",
             "Only if the company engages with indigenous peoples: how they have been consulted on the mode and parameters of "
             "the engagement (ESRS S3-2 §12). Answer N/A if there is no engagement with indigenous peoples.")),
], PHASE)

KPIS = dict([
    *L.bloc(PREFIXE, SUJET, PHASE),
    *L.kpis_sociaux("S3"),
    *L.indicateurs_propres(PREFIXE, SUJET, PHASE),
    *_propres,
])

SOCLE = C.socle("ESRS_S3", "1.1", "2026-11-19", [
    ("S3_1", "S3-1 – Politiques relatives aux communautés affectées", "S3-1 – Policies related to affected communities", [
        *C.arbre_gdr(PREFIXE, "S3-1", "P", social=True),
        ("SOC-COMMU-POLIT-COUVERTURE", "S3-1 · 8"), ("SOC-COMMU-POLIT-AUTOCHTONES", "S3-1 · 9")]),
    ("S3_2", "S3-2 – Dialogue, canaux pour faire part de préoccupations et réparation",
     "S3-2 – Engagement, channels to raise concerns and remediation", [
         ("SOC-COMMU-DIALOGUE-DIRECT", "S3-2 · 11"), ("SOC-COMMU-DIALOGUE", "S3-2 · 11"), ("SOC-COMMU-VULNERABLES", "S3-2 · 11"),
         ("SOC-COMMU-AUTOCHTONES-CLPE", "S3-2 · 12"), ("SOC-COMMU-AUTOCHTONES-CONS", "S3-2 · 12"),
         ("SOC-COMMU-AUTOCHT-CONS-DESC", "S3-2 · 12"), ("SOC-COMMU-CANAUX", "S3-2 · 13"), ("SOC-COMMU-PLAINTES", "S3-2 · 13"),
         ("SOC-COMMU-REPARATION", "S3-2 · 14")]),
    ("S3_3", "S3-3 – Actions et ressources relatives aux communautés affectées",
     "S3-3 – Actions and resources related to affected communities", [
         *C.arbre_gdr(PREFIXE, "S3-3", "A"),
         ("SOC-COMMU-ACTIONS-IMPACTS", "S3-3 · 16(a)"), ("SOC-COMMU-ACTIONS-SUIVI", "S3-3 · 16(b)"),
         ("SOC-COMMU-INCIDENTS-DH", "S3-3 · 17")]),
    ("S3_4", "S3-4 – Cibles relatives aux communautés affectées", "S3-4 – Targets related to affected communities",
     [
         *C.arbre_gdr(PREFIXE, "S3-4", "T"), *L.arbre_indicateurs(PREFIXE, "S3-4")]),
])
