"""Jeu d'essai à trois niveaux (Holding › Filiale › Site) : l'ancienne seconde démo, retirée de la commande de démo
(règle du projet : il ne reste que la démo Exemplia), gardée pour les tests qui vérifient ce qu'elle seule
montrait : niveaux propres à l'installation, site rattaché directement à la holding (rattachement souple), deux
référentiels qui partagent des KPI (un annuel, un mensuel depuis 2025 dont les mois se cumulent dans l'année), un troisième
composé sans recopier de KPI, champ personnalisé, liste de choix, contenus en anglais et en espagnol, campagnes 2021 à
2025 clôturées et 2026 ouverte.

``charger()`` le charge dans une base vide comme le faisait l'ancienne option de ``load_demo`` (même marqueur de base de démo :
une ancienne base de cette démo est reconnue, et la démo Exemplia refuse de s'y charger sans --reset). Aucune donnée
réelle : noms inventés, e-mails @exemple.test, valeurs tirées au hasard (reproductibles)."""
import datetime
import random
from decimal import Decimal

from django.db import models
from django.utils import timezone

from collecte import periodes as P
from collecte import saisie as S
from collecte.calcul import frequences_de_saisie, recalculer
from collecte.coherence import controler
from collecte.management.commands import _demo_commun as DC
from collecte.management.commands import charger_demo as CD
from collecte.models import Campagne, Journal, RegleCoherence, Reponse
from parametres import langues as L
from parametres import niveaux as N
from parametres import referentiel as PR
from parametres.models import (CategorieDescription, ChampPersonnalise, Langue, NiveauHierarchique, TypeReponse,
                               TypeSaisie, Unite)
from referentiel.bibliotheque.controle import UNITES_REGLEES_A_LA_MAIN
from referentiel.composition import copier_theme, placer, theme_par_chemin
from referentiel.echange import enregistrer_descriptions
from referentiel.models import KPI, Attribution, Organisation, Referentiel, Theme, Utilisateur

MOT_DE_PASSE = CD.MOT_DE_PASSE
CLIENT = "essai"  # marqueur de base de démo

IDENTITE = dict(nom="Essai", titre="Probant", sous_titre="Essai · jeu d'essai", sigle="ES", contact="l'équipe Développement durable",
                palette="ocean", couleur_principale="#1F5FAD", couleur_accent="#0F9D9A", couleur_fond="#F2F4F7",
                couleur_texte="#1E2A38", langue="fr", mise_en_place_terminee=True)
NIVEAUX = [  # code, nom, pluriel, couleur (fond et texte des étiquettes dérivés)
    ("Holding", "Holding", "Holding", "#1D3F6E"),
    ("Filiale", "Filiale", "Filiales", "#E07A1F"),
    ("Site", "Site", "Sites", "#0F9D9A"),
]
ARBRE = {  # holding › filiales › sites ; « Valence » est inactif
    "Essai Holding": {
        "Essai France": ["Lyon", "Lille"],
        "Essai Deutschland": ["Berlin", "Hambourg"],
        "Essai Iberia": ["Madrid", "Barcelone", ("Valence", False)],
    }
}
SITES_SOUS_HOLDING = ["Siège Essai"]
UNITES = UNITES_REGLEES_A_LA_MAIN  # code, symbole, libellé, nombre entier, décimales, famille
TYPES_REPONSE = [  # code, libellé, format, valeurs possibles
    ("OuiNon", "Oui / non", "oui_non", []),
    ("Certification", "Certification", "liste", ["Certifié", "En cours", "Non engagé"]),
]
CHAMPS = [("gri", "Référence GRI", "texte", [])]
GRI = {"ENR-01": "GRI 302-1", "ENR-02": "GRI 302-1", "EAU-01": "GRI 303-5", "GES-01": "GRI 305-2", "DEC-01": "GRI 306-3",
       "SEC-01": "GRI 403-9", "SOC-01": "GRI 2-7", "SOC-04": "GRI 404-1"}
DESCRIPTIONS = {
    "ENR-01": {"description": "Électricité achetée et consommée sur le site pendant l'exercice.",
               "a_inclure": "Bureaux, entrepôts, bornes de recharge.", "source": "Factures du fournisseur d'énergie."},
    "EAU-01": {"description": "Eau du réseau consommée sur le site.", "source": "Relevés des compteurs."},
    "SOC-06": {"description": "Une politique d'emploi des personnes en situation de handicap est-elle écrite et diffusée ?"},
    "ENV-01": {"description": "Statut de la certification ISO 14001 (management environnemental) du site au 31/12."},
}
KPIS = [
    # code, nom, type de saisie, unité, niveau, agrégation, formule, type de réponse, équipe
    ("ENR-01", "Électricité consommée", "Saisi", "kWh", "Site", "Somme", "", "Numérique", "Services généraux"),
    ("ENR-02", "Gaz naturel consommé", "Saisi", "kWh", "Site", "Somme", "", "Numérique", "Services généraux"),
    ("EAU-01", "Eau consommée", "Saisi", "m³", "Site", "Somme", "", "Numérique", "Services généraux"),
    ("ENV-01", "Certification ISO 14001 du site", "Saisi", "", "Site", "Décompte", "", "Certification",
     "Services généraux"),
    ("FE-ELEC", "Facteur d'émission de l'électricité", "FE", "kgCO2eq/kWh", "Holding", "Aucune", "", "Numérique",
     "Développement durable"),
    ("GES-01", "Émissions liées à l'électricité", "Calculé", "kgCO2eq", "Site", "Somme", "[ENR-01] * [FE-ELEC]",
     "Numérique", "Développement durable"),
    ("DEC-01", "Déchets produits", "Saisi", "t", "Site", "Somme", "", "Numérique", "Services généraux"),
    ("SEC-01", "Accidents du travail avec arrêt", "Saisi", "accidents", "Site", "Somme", "", "Numérique", "Ressources humaines"),
    ("SOC-01", "Effectif total au 31/12", "Saisi", "salariés", "Filiale", "Somme", "", "Numérique", "Ressources humaines"),
    ("SOC-02", "Effectif féminin au 31/12", "Saisi", "salariés", "Filiale", "Somme", "", "Numérique", "Ressources humaines"),
    ("SOC-03", "Part de femmes dans l'effectif", "Calculé", "", "Filiale", "Formule", "[SOC-02] / [SOC-01]", "Pourcentage",
     "Ressources humaines"),
    ("SOC-04", "Heures de formation", "Saisi", "h", "Filiale", "Somme", "", "Numérique", "Ressources humaines"),
    ("SOC-05", "Heures de formation par salarié", "Calculé", "h", "Filiale", "Formule", "[SOC-04] / [SOC-01]", "Numérique",
     "Ressources humaines"),
    ("SOC-06", "Politique handicap formalisée", "Saisi", "", "Filiale", "Décompte", "", "OuiNon", "Ressources humaines"),
    ("ECO-01", "Chiffre d'affaires", "Saisi", "M€", "Holding", "Aucune", "", "Numérique", "Finance"),
    ("GES-02", "Intensité carbone (électricité)", "Calculé", "tCO2eq/M€", "Holding", "Aucune",
     "[GES-01] / 1000 / [ECO-01]", "Numérique", "Développement durable"),
    ("ENR-03", "Évolution de l'électricité sur un mois", "Calculé", "", "Site", "Formule", "([ENR-01] - [ENR-01@P-1]) / [ENR-01@P-1]",
     "Pourcentage", "Services généraux"),
    ("ENR-04", "Évolution de l'électricité sur un an (même période)", "Calculé", "", "Site", "Formule",
     "([ENR-01] - [ENR-01@N-1]) / [ENR-01@N-1]", "Pourcentage", "Services généraux"),
]
# Électricité, gaz, facteur d'émission et certification se saisissent chaque mois (référentiel « Énergie », depuis 2025) ;
# leurs valeurs annuelles en découlent : somme des mois, dernière valeur pour le facteur et la certification.
MOIS_DEPUIS = 2025
POIDS_MOIS = [1.25, 1.15, 1.05, 0.95, 0.85, 0.8, 0.8, 0.8, 0.9, 1.0, 1.15, 1.3]  # saisonnalité : plus en hiver
REGLES = [
    ("Effectif féminin ≤ effectif total", "[SOC-02]", "<=", "[SOC-01]", "0", True,
     "L'effectif féminin ne peut pas dépasser l'effectif total de la filiale."),
]
COMPTES = [  # identifiant, prénom, nom, rôle
    ("admin", "Alice", "Admin (démo)", Utilisateur.Role.ADMIN),
    ("validateur", "Victor", "Validateur (démo)", Utilisateur.Role.VALIDATEUR),
    ("contributeur", "Camille", "Contributrice (démo)", Utilisateur.Role.CONTRIBUTEUR),
    ("lecteur", "Louise", "Lectrice (démo)", Utilisateur.Role.LECTEUR),
    ("auditeur", "Arthur", "Auditeur (démo)", Utilisateur.Role.AUDITEUR),
    ("jonas.weber", "Jonas", "Weber", Utilisateur.Role.CONTRIBUTEUR),
    ("lucia.martin", "Lucía", "Martín", Utilisateur.Role.CONTRIBUTEUR),
    ("anna.schmidt", "Anna", "Schmidt", Utilisateur.Role.VALIDATEUR),
    ("diego.santos", "Diego", "Santos", Utilisateur.Role.VALIDATEUR),
]
LANGUES_COMPTES = {"lucia.martin": "es", "diego.santos": "es", "jonas.weber": "en", "anna.schmidt": "en"}
SPOC = {"Essai France": "contributeur", "Essai Deutschland": "jonas.weber", "Essai Iberia": "lucia.martin"}  # par filiale
VALIDATEURS = {"Essai France": "validateur", "Essai Deutschland": "anna.schmidt", "Essai Iberia": "diego.santos"}
SANS_SPOC = {("SEC-01", "Barcelone"), ("DEC-01", "Hambourg"), ("SOC-04", "Essai Iberia")}  # cases encore à attribuer
TAILLE = {"Essai Holding": 4, "Essai France": 1.6, "Essai Deutschland": 1.2, "Essai Iberia": 0.9, "Siège Essai": 0.3,
          "Lyon": 0.9, "Lille": 0.6, "Berlin": 0.8, "Hambourg": 0.5, "Madrid": 0.6, "Barcelone": 0.4, "Valence": 0.2}
AVANCEMENT = {"Essai Holding": 0.8, "Siège Essai": 0.9, "Essai France": 0.85, "Lyon": 0.8, "Lille": 0.7,
              "Essai Deutschland": 0.6, "Berlin": 0.55, "Hambourg": 0.4, "Essai Iberia": 0.35, "Madrid": 0.3, "Barcelone": 0.2}
PARTS = {"SOC-02": "SOC-01"}  # effectif féminin ≤ effectif total


def niveaux():
    """Remplace les niveaux par ceux du jeu d'essai (base vide : aucune organisation, aucun KPI)."""
    NiveauHierarchique.objects.all().delete()
    for rang, (code, nom, pluriel, couleur) in enumerate(NIVEAUX, start=1):
        n = NiveauHierarchique(code=code, rang=rang, nom=nom, nom_pluriel=pluriel, couleur=couleur)
        n.deriver_couleurs()
        n.save()


def organisations():
    orgs = {}

    def creer(nom, niveau, parent, rang, actif=True):
        o, _ = Organisation.objects.update_or_create(nom=nom, defaults={"niveau_id": niveau, "parent": parent, "rang": rang, "actif": actif})
        orgs[nom] = o
        return o

    for holding, filiales in ARBRE.items():
        h = creer(holding, "Holding", None, 0)
        for i, (filiale, sites) in enumerate(filiales.items()):
            f = creer(filiale, "Filiale", h, i)
            for j, s in enumerate(sites):
                nom, actif = s if isinstance(s, tuple) else (s, True)
                creer(nom, "Site", f, j, actif)
        for k, nom in enumerate(SITES_SOUS_HOLDING, start=len(filiales)):
            creer(nom, "Site", h, k)
    return orgs


def referentiel():
    """Unités, types de réponse (oui / non, liste) et champ personnalisé du jeu d'essai, en plus des types d'installation."""
    DC.unites_et_types(UNITES, TYPES_REPONSE)  # unités d'installation reprises, les autres ajoutées
    for i, (code, libelle, type_, valeurs) in enumerate(CHAMPS, start=1):
        ChampPersonnalise.objects.update_or_create(code=code, defaults=dict(libelle=libelle, type=type_, valeurs=valeurs, ordre=i))


# ---------------------------------------------------------------- référentiels
REFERENTIELS = [  # code, nom, description, couleur, fréquence, comparaison
    ("REPORTING", "Reporting Essai", "Rapport de durabilité annuel du groupe Essai.", "#1F5FAD", "annee", "N-1"),
    ("ENERGIE", "Énergie", "Suivi mensuel de l'énergie et du carbone pour la direction des services généraux.", "#E07A1F",
     "mois", "N-1"),
]
PLACES = {  # référentiel → [(chemin de thèmes, KPI, obligatoire)], dans l'ordre
    "REPORTING": [
        (["Environnement", "Énergie et climat", "Électricité"], "ENR-01", True),
        (["Environnement", "Énergie et climat", "Électricité"], "FE-ELEC", True),
        (["Environnement", "Énergie et climat", "Électricité"], "GES-01", True),
        (["Environnement", "Énergie et climat", "Électricité"], "GES-02", True),
        (["Environnement", "Énergie et climat"], "ENR-02", True),
        (["Environnement", "Eau et déchets"], "EAU-01", True),
        (["Environnement", "Eau et déchets"], "DEC-01", True),
        (["Environnement"], "ENV-01", True),
        (["Social", "Santé et sécurité"], "SEC-01", True),
        (["Social", "Effectifs"], "SOC-01", True), (["Social", "Effectifs"], "SOC-02", True),
        (["Social", "Effectifs"], "SOC-03", True),
        (["Social", "Formation"], "SOC-04", True), (["Social", "Formation"], "SOC-05", True),
        (["Social", "Inclusion"], "SOC-06", True),
        (["Économie"], "ECO-01", True),
    ],
    "ENERGIE": [
        (["Consommations"], "ENR-01", True), (["Consommations"], "ENR-02", True),
        (["Consommations"], "ENR-03", True), (["Consommations"], "ENR-04", True),
        (["Émissions"], "FE-ELEC", True), (["Émissions"], "GES-01", True),
        (["Management de l'énergie"], "ENV-01", False),
    ],
}
THEMES = {  # nom : (anglais, espagnol)
    "Environnement": ("Environment", "Medio ambiente"), "Social": ("Social", "Social"), "Économie": ("Economy", "Economía"),
    "Énergie et climat": ("Energy and climate", "Energía y clima"), "Électricité": ("Electricity", "Electricidad"),
    "Eau et déchets": ("Water and waste", "Agua y residuos"), "Santé et sécurité": ("Health and safety", "Salud y seguridad"),
    "Effectifs": ("Headcount", "Plantilla"), "Formation": ("Training", "Formación"), "Inclusion": ("Inclusion", "Inclusión"),
    "Consommations": ("Consumption", "Consumos"), "Émissions": ("Emissions", "Emisiones"),
    "Management de l'énergie": ("Energy management", "Gestión de la energía"),
}
NOMS_REFERENTIELS = {"REPORTING": ("Essai sustainability reporting", "Informe de sostenibilidad Essai"), "ENERGIE": ("Energy", "Energía")}
# « Tableau de bord direction » : composé (« lego ») à partir des deux autres référentiels, sans recopier de KPI
COMPOSITION = [("ENERGIE", "Consommations"), ("ENERGIE", "Émissions"), ("REPORTING", "Social"), ("REPORTING", "Économie")]


def referentiels():
    """Les deux référentiels du jeu d'essai : arbre de thèmes et place de chaque KPI (sans les recopier)."""
    cache = {}
    for i, (code, nom, description, couleur, frequence, comparaison) in enumerate(REFERENTIELS, start=1):
        ref, _ = Referentiel.objects.update_or_create(code=code, defaults={
            "nom": nom, "description": description, "couleur": couleur, "ordre": i, "frequence": frequence, "comparaison": comparaison})
        for ordre, (chemin, kpi, obligatoire) in enumerate(PLACES[code], start=1):
            placer(KPI.objects.get(pk=kpi), ref, theme_par_chemin(ref, chemin, cache), ordre, obligatoire=obligatoire)


def composer():
    """Compose « Tableau de bord direction » avec des thèmes des deux autres référentiels : les mêmes KPI (une seule valeur
    saisie), rangés autrement."""
    ref, _ = Referentiel.objects.update_or_create(code="DIRECTION", defaults={
        "nom": "Tableau de bord direction", "couleur": "#0F9D9A", "ordre": 3,
        "description": "Indicateurs clés pour le comité de direction, repris des référentiels « Reporting » et Énergie.",
        "traductions": {"en": {"nom": "Management dashboard"}, "es": {"nom": "Cuadro de mando de la dirección"}}})
    for code, nom in COMPOSITION:
        copier_theme(Theme.objects.get(referentiel_id=code, nom=nom, parent=None), ref)
    return ref


def kpis():
    for ordre, (code, nom, type_saisie, unite, niveau, agregation, formule, reponse, equipe) in enumerate(KPIS, start=1):
        k, _ = KPI.objects.update_or_create(code=code, defaults=dict(
            libelle=nom, type_saisie_id=type_saisie, unite_id=unite or None, granularite_id=niveau,
            methode_agregation=agregation, formule=formule, type_reponse_id=reponse, equipe_responsable=equipe, ordre=ordre,
            champs={"gri": GRI[code]} if code in GRI else {},
            decimales=1 if reponse == "Pourcentage" or "/" in unite or unite == "h" else 0))
        enregistrer_descriptions(k, DESCRIPTIONS.get(code, {}))


# ---------------------------------------------------------------- traductions (anglais, espagnol)
LANGUES = [("fr", "Français"), ("en", "English"), ("es", "Español")]
NOMS = {  # code : (anglais, espagnol)
    "ENR-01": ("Electricity consumed", "Electricidad consumida"), "ENR-02": ("Natural gas consumed", "Gas natural consumido"),
    "EAU-01": ("Water consumed", "Agua consumida"), "ENV-01": ("ISO 14001 certification of the site", "Certificación ISO 14001 del centro"),
    "FE-ELEC": ("Electricity emission factor", "Factor de emisión de la electricidad"),
    "GES-01": ("Emissions from electricity", "Emisiones de la electricidad"), "DEC-01": ("Waste generated", "Residuos generados"),
    "SEC-01": ("Lost-time work accidents", "Accidentes de trabajo con baja"), "SOC-01": ("Total headcount at 31/12", "Plantilla total a 31/12"),
    "SOC-02": ("Female headcount at 31/12", "Plantilla femenina a 31/12"), "SOC-06": ("Formal disability policy", "Política de discapacidad formalizada"),
    "SOC-03": ("Share of women in headcount", ""), "SOC-04": ("Training hours", ""), "ECO-01": ("Revenue", ""),
    "ENR-03": ("Month-on-month change in electricity", "Evolución mensual de la electricidad"),
    "ENR-04": ("Year-on-year change in electricity (same period)", "Evolución anual de la electricidad (mismo periodo)"),
}
DESCRIPTIONS_ES = {
    "ENR-01": {"description": "Electricidad comprada y consumida en el centro durante el ejercicio.",
               "a_inclure": "Oficinas, almacenes, puntos de recarga.", "source": "Facturas del proveedor de energía."},
    "SOC-06": {"description": "¿Existe una política escrita y difundida de empleo de personas con discapacidad?"},
    "ENV-01": {"description": "Estado de la certificación ISO 14001 (gestión ambiental) del centro a 31/12."},
}
DESCRIPTIONS_EN = {"SOC-06": {"description": "Is a policy on employing people with disabilities written down and shared?"}}
THEMES = {"Environnement": ("Environment", "Medio ambiente"), "Social": ("Social", "Social"), "Économie": ("Economy", "Economía")}
LIBELLES = [  # modèle, code, champ, anglais, espagnol
    (NiveauHierarchique, "Holding", "nom", "Holding", "Holding"), (NiveauHierarchique, "Holding", "nom_pluriel", "Holding", "Holding"),
    (NiveauHierarchique, "Filiale", "nom", "Subsidiary", "Filial"), (NiveauHierarchique, "Filiale", "nom_pluriel", "Subsidiaries", "Filiales"),
    (NiveauHierarchique, "Site", "nom", "Site", "Centro"), (NiveauHierarchique, "Site", "nom_pluriel", "Sites", "Centros"),
    (TypeSaisie, "Saisi", "libelle", "Input", "Introducido"), (TypeSaisie, "Saisi", "abrege", "Input", "Entrada"),
    (TypeSaisie, "Calculé", "libelle", "Calculated", "Calculado"), (TypeSaisie, "Calculé", "abrege", "Calc.", "Cálculo"),
    (TypeSaisie, "FE", "libelle", "Emission factor", "Factor de emisión"),
    (TypeReponse, "OuiNon", "libelle", "Yes / no", "Sí / no"), (TypeReponse, "Certification", "libelle", "Certification", "Certificación"),
    (Unite, "salariés", "symbole", "employees", "empleados"), (Unite, "accidents", "symbole", "accidents", "accidentes"),
    (Unite, "kWh", "libelle", "kilowatt-hour", "kilovatio hora"), (Unite, "m³", "libelle", "cubic metre", "metro cúbico"),
    (Unite, "t", "libelle", "tonne", "tonelada"),
    (CategorieDescription, "description", "libelle", "Description", "Descripción"),
    (CategorieDescription, "a_inclure", "libelle", "Include", "Incluir"), (CategorieDescription, "a_exclure", "libelle", "Exclude", "Excluir"),
    (CategorieDescription, "source", "libelle", "Data source", "Fuente de los datos"),
    (ChampPersonnalise, "gri", "libelle", "GRI reference", "Referencia GRI"),
]
VALEURS = {"OuiNon": (["Yes", "No"], ["Sí", "No"]),
           "Certification": (["Certified", "In progress", "Not engaged"], ["Certificado", "En curso", "No comprometido"])}


OUI_NON_AUTRES_LANGUES = {  # type « Oui / non » de la démo : libellé et valeurs en allemand, italien, néerlandais, portugais
    "de": ("Ja / Nein", ["Ja", "Nein"]), "it": ("Sì / no", ["Sì", "No"]), "nl": ("Ja / nee", ["Ja", "Nee"]),
    "pt": ("Sim / não", ["Sim", "Não"])}
SITE_AUTRES_LANGUES = {  # niveau « Site » de la démo (ses propres niveaux remplacent ceux de l'outil) : nom, pluriel
    "de": ("Standort", "Standorte"), "it": ("Sede", "Sedi"), "nl": ("Locatie", "Locaties"), "pt": ("Local", "Locais")}


def langues():
    """Français (référence et défaut), anglais et espagnol actifs."""
    for i, (code, libelle) in enumerate(LANGUES, start=1):
        Langue.objects.update_or_create(code=code, defaults={"libelle": libelle, "ordre": i, "active": True})


def traductions():
    """Quelques KPI, définitions, thèmes et libellés traduits en anglais et en espagnol (le reste se replie sur le français)."""
    with L.session():
        for code, (en, es) in NOMS.items():
            k = KPI.objects.get(pk=code)
            L.definir(k, "libelle", "en", en)
            L.definir(k, "libelle", "es", es)
            k.save(update_fields=["traductions"])
        for code, textes in DESCRIPTIONS_ES.items():
            enregistrer_descriptions(KPI.objects.get(pk=code), textes, "es")
        for code, textes in DESCRIPTIONS_EN.items():
            enregistrer_descriptions(KPI.objects.get(pk=code), textes, "en")
        objets = {}
        for t in Theme.objects.filter(nom__in=THEMES):
            o = objets.setdefault((Theme, t.pk), t)
            L.definir(o, "nom", "en", THEMES[t.nom][0])
            L.definir(o, "nom", "es", THEMES[t.nom][1])
        for code, (en, es) in NOMS_REFERENTIELS.items():
            o = objets.setdefault((Referentiel, code), Referentiel.objects.get(pk=code))
            L.definir(o, "nom", "en", en)
            L.definir(o, "nom", "es", es)
        for modele, code, champ, en, es in LIBELLES:
            o = objets.setdefault((modele, code), modele.objects.get(pk=code))
            L.definir(o, champ, "en", en)
            L.definir(o, champ, "es", es)
        for code, (en, es) in VALEURS.items():
            o = objets.setdefault((TypeReponse, code), TypeReponse.objects.get(pk=code))
            L.definir_valeurs(o, "en", en, len(en))
            L.definir_valeurs(o, "es", es, len(es))
        oui_non = objets[(TypeReponse, "OuiNon")]
        for langue, (libelle, valeurs) in OUI_NON_AUTRES_LANGUES.items():
            L.definir(oui_non, "libelle", langue, libelle)
            L.definir_valeurs(oui_non, langue, valeurs, len(valeurs))
        site = objets[(NiveauHierarchique, "Site")]
        for langue, (nom, pluriel) in SITE_AUTRES_LANGUES.items():
            L.definir(site, "nom", langue, nom)
            L.definir(site, "nom_pluriel", langue, pluriel)
        for o in objets.values():
            o.save(update_fields=["traductions"])


def comptes(mot_de_passe):
    return {ident: DC.compte(ident, prenom, nom, role, mot_de_passe, email=f"{ident}@exemple.test", equipe="",
                             langue=LANGUES_COMPTES.get(ident, ""))
            for ident, prenom, nom, role in COMPTES}


def filiale_de(o):
    while o and o.niveau_id != "Filiale":
        o = o.parent
    return o


def attributions(comptes, orgs, kpis_collectes):
    """Un SPOC par filiale (ses sites compris) ; le siège et la holding à Camille ; un validateur par filiale."""
    liens = []
    for k in kpis_collectes:
        for o in orgs.values():
            if o.actif and o.niveau_id == k.granularite_id and (k.pk, o.nom) not in SANS_SPOC:
                f = filiale_de(o)
                liens.append(Attribution(kpi=k, organisation=o, utilisateur=comptes[SPOC.get(f.nom if f else "", "contributeur")],
                                         role=Attribution.Role.CONTRIBUTEUR))
    for filiale, ident in VALIDATEURS.items():
        for k in kpis_collectes:
            if k.granularite_id != "Holding":
                liens.append(Attribution(kpi=k, organisation=orgs[filiale], utilisateur=comptes[ident], role=Attribution.Role.VALIDATEUR))
    Attribution.objects.bulk_create(liens, ignore_conflicts=True)


def regles():
    for nom, gauche, op, droite, tol, bloquante, description in REGLES:
        RegleCoherence.objects.update_or_create(nom=nom, defaults={
            "gauche": gauche, "operateur": op, "droite": droite, "tolerance": Decimal(tol), "niveau_id": "Filiale",
            "bloquante": bloquante, "description": description, "actif": True})


# ---------------------------------------------------------------- KPI qualitatifs (réponses rédigées en Markdown)
# 3 KPI « texte rédigé » dans un thème « Politique et engagements » du premier référentiel, au
# sommet de l'arbre et au niveau suivant ; réponses fictives sur toutes les années, pour voir la fonction tout de suite.
THEME_REDIGE = ("POLITIQUE", "Politique et engagements", {"en": {"nom": "Policy and commitments"}, "es": {"nom": "Política y compromisos"}})
KPIS_REDIGES = [  # code, rang du niveau (1 = sommet), nom (fr, en, es), description (fr, en, es)
    ("QUAL-01", 1, ("Décrire la politique environnementale et ses engagements", "Describe the environmental policy and its commitments",
                    "Describir la política medioambiental y sus compromisos"),
     ("Politique en vigueur au 31/12 : engagements, objectifs chiffrés, gouvernance. Mise en forme possible (titres, listes, liens).",
      "Policy in force at 31/12: commitments, quantified targets, governance. Formatting allowed (headings, lists, links).",
      "Política vigente a 31/12: compromisos, objetivos cuantificados, gobernanza. Se puede dar formato (títulos, listas, enlaces).")),
    ("QUAL-02", 2, ("Décrire les actions de l'année pour réduire les consommations d'énergie",
                    "Describe the actions taken this year to reduce energy consumption",
                    "Describir las acciones del año para reducir el consumo de energía"),
     ("Actions engagées ou terminées dans l'exercice, avec leur effet attendu ; renvoyer aux preuves si besoin.",
      "Actions started or completed during the year, with their expected effect; refer to the evidence if needed.",
      "Acciones iniciadas o terminadas en el ejercicio, con su efecto esperado; remitir a las pruebas si es necesario.")),
    ("QUAL-03", 2, ("Présenter les faits marquants de l'année pour les équipes", "Present the highlights of the year for the teams",
                    "Presentar los hechos destacados del año para los equipos"),
     ("Formation, dialogue social, santé et sécurité : quelques lignes sur ce qui a marqué l'exercice.",
      "Training, social dialogue, health and safety: a few lines on what marked the year.",
      "Formación, diálogo social, salud y seguridad: unas líneas sobre lo más destacado del ejercicio.")),
]
TEXTES_REDIGES = {  # quelques réponses fictives par KPI ({annee} : exercice ; {org} : organisation)
    "QUAL-01": [
        "## Politique environnementale {annee}\n\nNotre politique, revue en **comité de direction**, couvre :\n\n"
        "- la réduction des consommations d'énergie de **5 %** par an ;\n- le tri et la valorisation des déchets ;\n"
        "- l'achat d'électricité d'origine *renouvelable*.\n\nDocument complet : [charte publiée](https://example.org/charte)",
        "## Engagements {annee}\n\n1. Publier un bilan annuel des émissions.\n2. Former les équipes aux éco-gestes.\n"
        "3. Suivre les fournisseurs principaux.\n\n> Politique validée en **mars {annee}**, sans changement majeur.",
    ],
    "QUAL-02": [
        "Pour **{org}** en {annee} :\n\n- remplacement de l'éclairage par des **LED** ;\n- réglage des consignes de chauffage ;\n"
        "- extinction automatique des postes la nuit.\n\nEffet attendu : *environ 8 %* d'énergie en moins.",
        "### Actions {annee}\n\n| Action | État |\n|---|---|\n| Audit énergétique | Terminé |\n| Isolation des combles | En cours |\n\n"
        "Suite prévue l'an prochain.",
        "Peu d'actions nouvelles à **{org}** cette année : le plan engagé en {annee} se poursuit.",
    ],
    "QUAL-03": [
        "## Faits marquants {annee}\n\n- **Formation** : nouveau parcours pour les managers.\n- **Sécurité** : campagne de "
        "prévention des chutes.\n- *Dialogue social* : accord sur le télétravail.",
        "Année stable pour **{org}** : effectifs constants, deux sessions d'accueil des nouveaux arrivants, "
        "baromètre interne en hausse.",
    ],
}


def kpis_rediges(comptes, orgs):
    """Thème « Politique et engagements » (premier référentiel actif) et ses 3 KPI à réponse rédigée ; la contributrice de
    démo en est le SPOC (organisations de leur niveau), l'administrateur valide."""
    from parametres.models import TypeReponse
    from referentiel.echange import enregistrer_descriptions
    from referentiel.models import ElementReferentiel, Theme

    ref = Referentiel.objects.filter(actif=True).order_by("ordre", "code").first()
    niveaux = N.tous()
    t = TypeReponse.objects.filter(format=TypeReponse.Format.TEXTE).first() or TypeReponse.objects.create(
        code="TexteRedige", libelle="Texte rédigé", format=TypeReponse.Format.TEXTE, ordre=99,
        traductions={"en": {"libelle": "Written text"}, "es": {"libelle": "Texto redactado"}})
    saisi = TypeSaisie.objects.filter(comportement=TypeSaisie.Comportement.SAISIE).first()
    if ref is None or not niveaux or saisi is None:
        return
    code, nom, traductions = THEME_REDIGE
    Theme.objects.filter(referentiel=ref, parent=None).update(ordre=models.F("ordre") + 1)
    theme, _ = Theme.objects.update_or_create(referentiel=ref, code=code, defaults=dict(nom=nom, ordre=0, traductions=traductions))
    ordre = (KPI.objects.order_by("-ordre").values_list("ordre", flat=True).first() or 0) + 1
    for i, (code, rang, (fr, en, es), description) in enumerate(KPIS_REDIGES):
        niveau = niveaux[min(rang, len(niveaux)) - 1]
        k, _ = KPI.objects.update_or_create(code=code, defaults=dict(
            libelle=fr, traductions={"en": {"libelle": en}, "es": {"libelle": es}}, type_saisie=saisi, type_reponse=t,
            granularite=niveau, methode_agregation=KPI.Agregation.AUCUNE, equipe_responsable="CSR Team", ordre=ordre + i))
        for langue, texte in zip(("fr", "en", "es"), description):
            enregistrer_descriptions(k, {"description": texte}, langue)
        ElementReferentiel.objects.update_or_create(referentiel=ref, kpi=k, defaults=dict(theme=theme, ordre=i, obligatoire=True))
        spoc = comptes.get("contributeur")
        if spoc is not None:
            Attribution.objects.bulk_create([Attribution(kpi=k, organisation=o, utilisateur=spoc, role=Attribution.Role.CONTRIBUTEUR)
                                             for o in orgs.values() if o.actif and o.niveau_id == niveau.code], ignore_conflicts=True)


def texte_redige(k, o, exercice):
    """Réponse rédigée fictive, stable pour une organisation et une année."""
    modeles = TEXTES_REDIGES.get(k.pk) or ["Réponse rédigée pour **{org}** ({annee})."]
    r = random.Random(f"{k.pk}|{o.pk}|{exercice}")
    return r.choice(modeles).format(annee=exercice, org=o.nom)


SOMMES = {}  # {KPI total : [KPI dont il est la somme]} (aucun dans les démos actuelles)
PARTS_VALEURS = dict(PARTS)  # {part : total} : une part reste inférieure à son total
PROFILS = {  # unité : (minimum, maximum, décimales)
    "tco2eq": (50, 4000, 1), "kgco2eq": (5000, 900000, 0), "mwh": (100, 15000, 1), "kwh": (10000, 900000, 0),
    "employees": (40, 1500, 0), "fte": (40, 1500, 1), "members": (2, 40, 0), "m€": (5, 900, 1), "k€": (50, 9000, 0),
    "€": (20000, 4000000, 0), "hours": (500, 40000, 0), "days": (5, 300, 0), "years": (2, 15, 1), "accidents": (0, 25, 0),
    "deaths": (0, 1, 0), "complaints": (5, 400, 0), "incidents": (0, 30, 0), "warehouses": (1, 6, 0), "m³": (200, 40000, 0),
    "m²": (5000, 300000, 0), "parcels": (100000, 9000000, 0), "kg": (500, 90000, 0), "t": (20, 6000, 1), "l": (1000, 120000, 0),
    "km": (10000, 900000, 0),
}
COMMENTAIRES_ECART = [
    "Ouverture d'un nouvel entrepôt en cours d'année.",
    "Changement de méthode de calcul conseillé par l'auditeur.",
    "Hausse d'activité liée aux ventes de fin d'année.",
    "Données N-1 incomplètes, corrigées cette année.",
    "Réorganisation du périmètre (fusion de deux équipes).",
]

VUES = [
    ("Comité de direction", "Les chiffres clés et l'avancement de la collecte.", ["admin", "lecteur", "auditeur"], None, [
        ("chiffre", ["ENR-01"], 3, {}, {}, {}), ("chiffre", ["EAU-01"], 3, {}, {}, {}), ("chiffre", ["DEC-01"], 3, {}, {}, {}),
        ("chiffre", ["SOC-01"], 3, {}, {}, {}), ("remplissage", [], 6, {}, {}, {}), ("organisations", ["ENR-01"], 6, {}, {}, {}),
        ("tableau", ["ENR-01", "ENR-02", "EAU-01", "DEC-01", "SOC-01"], 12, {}, {}, {})]),
    ("Énergie et climat", "Électricité, gaz et émissions des sites.", [], None, [
        ("courbe", ["ENR-01", "ENR-02"], 6, {}, {}, {}), ("anneau", ["ENR-01"], 6, {}, {}, {}),
        ("comparaison_n1", ["ENR-01"], 6, {}, {}, {}), ("anneau", ["ENV-01"], 6, {}, {}, {})]),
    ("Mon périmètre", "L'avancement de ma collecte et les KPI que je saisis ou valide, site par site.", ["contributeur", "validateur"],
     "Essai France", [
        ("chiffre", ["SOC-01"], 4, {}, {}, {}), ("chiffre", ["SOC-02"], 4, {}, {}, {}), ("chiffre", ["SOC-04"], 4, {}, {}, {}),
        ("remplissage", [], 6, {}, {}, {}), ("organisations", ["ENR-01"], 6, {}, CD.SITES, {}),
        ("courbe", ["EAU-01"], 12, {}, CD.SITES, {"series": "organisations"})]),
]


# ---------------------------------------------------------------- chargement
class Chargeur:
    """Campagnes, valeurs passées et saisies en cours (méthodes reprises de l'ancienne commande de démo)."""

    def __init__(self, ecrire=None):
        self.ecrire = ecrire or (lambda texte: None)
        self.hasard = random.Random(2026)

    # -- campagnes et valeurs ---------------------------------------------------
    def campagnes(self):
        """Campagnes annuelles du premier référentiel : 2021 à 2025 clôturées, 2026 ouverte."""
        aujourd_hui = timezone.localdate()
        passees = []
        for ex in range(2021, 2026):
            c, _ = P.campagne_annuelle(ex)
            for champ, v in {"statut": Campagne.Statut.CLOTUREE, "date_ouverture": datetime.date(ex + 1, 1, 5),
                             "date_fin_saisie": datetime.date(ex + 1, 3, 31), "seuil_ecart": Decimal("0.2") if ex >= 2024 else None}.items():
                setattr(c, champ, v)
            c.save()
            passees.append(c)
        c2026, _ = P.campagne_annuelle(2026)
        c2026.statut, c2026.seuil_ecart = Campagne.Statut.OUVERTE, Decimal("0.2")
        c2026.date_ouverture = aujourd_hui - datetime.timedelta(days=21)
        c2026.date_fin_saisie = aujourd_hui + datetime.timedelta(days=60)
        c2026.save()
        return passees, c2026

    # valeurs plausibles : (minimum, maximum, décimales) selon l'unité
    def _profil(self, k):
        u = (k.unite.symbole if k.unite_id else "").lower()
        if k.est_pourcentage:
            return (0.05, 0.95, 4)
        if k.est_herite or "/" in u and "co2" in u:
            return (0.05, 3.0, 3)
        if u.startswith("/"):
            return (0.3 * float(u[1:] or 10), float(u[1:] or 10), 1)
        return PROFILS.get(u, (10, 2000, 0))

    def reponse(self, k, o, exercice):
        """(valeur, texte) : un nombre, la réponse d'un oui / non ou d'une liste (stable d'une année sur l'autre), ou un
        texte rédigé (Markdown)."""
        if k.est_numerique:
            return self.valeur(k, o, exercice), ""
        if k.est_texte:
            return None, texte_redige(k, o, exercice)
        r = random.Random(f"{k.pk}|{o.pk}")
        choix = k.choix
        base = r.randrange(len(choix))
        bouge = random.Random(f"{k.pk}|{o.pk}|{exercice}").random() < 0.15  # parfois la réponse change
        return None, choix[(base + (1 if bouge else 0)) % len(choix)]

    def parts(self):
        """{KPI: (KPI dont la somme est son total)} : ceux de PARTS, et le numérateur A de chaque pourcentage calculé
        « [A] / [B] » (même unité ; B saisi, ou somme calculée « [X] + [Y]… » de KPI saisis). Une part reste ainsi une
        part : pas de « part des déchets détournés » à 2 000 %, que le contrôle des données signalerait."""
        if getattr(self, "_parts", None) is None:
            import re

            self._parts = {k: (t,) for k, t in PARTS_VALEURS.items()}
            sommes = set(SOMMES) | {i for v in SOMMES.values() for i in v}  # effectifs : déjà cohérents
            saisis, tous = self.kpi_par_id, {k.pk: k for k in KPI.objects.select_related("type_saisie", "type_reponse")}
            ref = r"\s*\[([^\]@]+)\]\s*"
            for k in sorted(tous.values(), key=lambda k: k.pk):
                m = re.fullmatch(f"{ref}/{ref}", k.formule or "")
                if not (m and k.est_calcule and k.est_pourcentage):
                    continue
                a, b = saisis.get(m.group(1)), tous.get(m.group(2))
                if b is not None and b.est_calcule and re.fullmatch(f"{ref}(\\+{ref})*", b.formule or ""):
                    termes = [saisis.get(c) for c in re.findall(r"\[([^\]@]+)\]", b.formule)]
                else:
                    termes = [saisis.get(b.pk) if b is not None else None]
                deja = set(self._parts) | {t for v in self._parts.values() for t in v}
                if (a and all(termes) and a not in termes and all(t.unite_id == a.unite_id and t.granularite_id == a.granularite_id for t in termes)
                        and not a.est_pourcentage and not ({a.pk} | {t.pk for t in termes}) & sommes and a.pk not in deja
                        and not {t.pk for t in termes} & set(self._parts)):
                    self._parts[a.pk] = tuple(t.pk for t in termes)  # pas de chaîne ni de boucle
        return self._parts

    def valeur(self, k, o, exercice):
        """Valeur reproductible : base propre à la case × taille de l'organisation × tendance annuelle × bruit.

        Les effectifs respectent les règles de cohérence de la démo (total = CDI + CDD, formés ≤ total)."""
        if k.pk in SOMMES:
            return sum(self.valeur(self.kpi_par_id[i], o, exercice) for i in SOMMES[k.pk])
        parts = self.parts()
        if k.pk in parts:  # les termes N/A du total comptent pour 0
            total = sum((self.valeur(self.kpi_par_id[t], o, exercice) for t in parts[k.pk] if not self.est_na(self.kpi_par_id[t], o)),
                        Decimal(0))
            return Decimal(round(total * Decimal(str(random.Random(f"part|{k.pk}|{o.pk}|{exercice}").uniform(0.3, 0.8)))))
        r = random.Random(f"{k.pk}|{o.pk}")
        mini, maxi, dec = self._profil(k)
        base = r.uniform(mini, maxi)
        pourcent = k.est_pourcentage
        fe = k.est_herite
        score = (k.unite.symbole if k.unite_id else "").startswith("/")  # note sur 10, 100… : pas d'effet de taille
        if not (pourcent or fe or score):
            base *= TAILLE.get(o.nom, 0.5)
        tendance = 0 if fe else r.uniform(-0.06, 0.08)
        bruit = 0 if fe else random.Random(f"{k.pk}|{o.pk}|{exercice}").uniform(-0.04, 0.04)  # un FE ne bouge pas
        v = base * (1 + tendance) ** (exercice - 2021) * (1 + bruit)
        if pourcent:
            v = min(max(v, 0.0), 1.0)
        return Decimal(str(round(v, dec)))

    def est_na(self, k, o):
        return random.Random(f"na|{k.pk}|{o.pk}").random() < 0.03

    def cellules(self, orgs, exercice=None):
        """Cellules d'une campagne annuelle ; sans les KPI saisis chaque mois depuis MOIS_DEPUIS (leur année en découle)."""
        kpis = [k for k in S.kpis_collectes() if not (exercice and exercice >= MOIS_DEPUIS and k.pk in self.mensuels)]
        return [(k, o) for k in kpis for o in orgs.values() if o.actif and o.niveau_id == k.granularite_id]

    def historique(self, passees, orgs):
        """2021 à 2025 : toutes les cellules remplies (import d'un fichier historique simulé), puis calculs et agrégats."""
        self.kpi_par_id = {k.pk: k for k, _ in self.cellules(orgs)}
        for c in passees:
            cellules = self.cellules(orgs, c.exercice)
            Reponse.objects.bulk_create([
                Reponse(periode=c.periode, kpi=k, organisation=o, valeur=None if self.est_na(k, o) else self.reponse(k, o, c.exercice)[0],
                        texte="" if self.est_na(k, o) else self.reponse(k, o, c.exercice)[1],
                        non_applicable=self.est_na(k, o), statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.IMPORT,
                        commentaire="Non concerné sur ce périmètre." if self.est_na(k, o) else "")
                for k, o in cellules], ignore_conflicts=True, batch_size=2000)
            recalculer(c)
            self.ecrire(f"Year {c.exercice}: {len(cellules)} values entered, calculations redone")

    def saisies(self, c2026, comptes, orgs):
        """2026 : collecte en cours, avancement inégal selon les pays ; brouillons, validations, écarts, N/A."""
        h = random.Random(2026)
        spocs = {}
        for a in Attribution.objects.filter(role=Attribution.Role.CONTRIBUTEUR).select_related("utilisateur"):
            spocs.setdefault((a.kpi_id, a.organisation_id), a.utilisateur)
        maintenant = timezone.now()
        reponses, journal = [], []
        for k, o in self.cellules(orgs, 2026):
            u = spocs.get((k.pk, o.pk))
            if u is None or h.random() > AVANCEMENT.get(o.nom, 0.4):
                continue
            na = self.est_na(k, o)
            v, texte = (None, "") if na else self.reponse(k, o, 2026)
            commentaire = "Non concerné sur ce périmètre." if na else ""
            ecart_fort = False
            if not na and k.est_numerique and not k.est_herite and h.random() < 0.08:  # variation marquée par rapport à N-1
                facteur = Decimal(str(round(h.uniform(1.3, 1.7), 2)))
                v = min(v * facteur, Decimal(1)) if k.est_pourcentage else v * facteur
                v = round(v, self._profil(k)[2])
                ecart_fort = True
                if h.random() < 0.5:
                    commentaire = h.choice(COMMENTAIRES_ECART)
            bloque = (ecart_fort and not commentaire) or (k.preuve_obligatoire and not na)
            valide = not bloque and h.random() < 0.72
            quand = maintenant - datetime.timedelta(days=h.uniform(0, 20), hours=h.uniform(0, 8))
            reponses.append(Reponse(periode=c2026.periode, kpi=k, organisation=o, valeur=v, texte=texte, non_applicable=na, commentaire=commentaire,
                                    statut=Reponse.Statut.VALIDE if valide else Reponse.Statut.BROUILLON, origine=Reponse.Origine.SAISIE,
                                    saisi_par=u, valide_par=u if valide else None, date_validation=quand if valide else None))
            journal.append((u, quand, k, o, texte or v, na, valide))
        Reponse.objects.bulk_create(reponses, ignore_conflicts=True, batch_size=2000)
        ids = {(r.kpi_id, r.organisation_id): r.pk for r in Reponse.objects.filter(periode=c2026.periode)}
        entrees = []
        for u, quand, k, o, v, na, valide in journal:
            rid = str(ids[(k.pk, o.pk)])
            champ, apres = ("non_applicable", True) if na else ("valeur", v)
            entrees.append((Journal(utilisateur=u, action="creation", objet="Reponse", objet_id=rid, champ=champ, avant="", apres=str(apres)), quand))
            entrees.append((Journal(utilisateur=u, action="creation", objet="Reponse", objet_id=rid, champ="statut", avant="", apres="brouillon"), quand))
            if valide:
                entrees.append((Journal(utilisateur=u, action="modification", objet="Reponse", objet_id=rid, champ="statut",
                                        avant="brouillon", apres="valide"), quand + datetime.timedelta(minutes=5)))
        crees = Journal.objects.bulk_create([e for e, _ in entrees], batch_size=2000)
        for e, (_, quand) in zip(crees, entrees):
            e.date = quand
        Journal.objects.bulk_update(crees, ["date"], batch_size=2000)
        recalculer(c2026)
        controler(c2026)
        nb_val = sum(1 for r in reponses if r.statut == Reponse.Statut.VALIDE)
        self.ecrire(f"Year 2026: {len(reponses)} entries, {nb_val} of them validated")


    def energie_mensuelle(self, orgs, passees):
        """Référentiel mensuel « Énergie » : une campagne par mois depuis janvier 2025, clôturées jusqu'au mois d'avant le
        dernier ; le dernier mois écoulé est ouvert, à moitié saisi. Les valeurs annuelles s'en déduisent (cumul)."""
        ref = Referentiel.objects.filter(frequence="mois").first()
        spocs = {(a.kpi_id, a.organisation_id): a.utilisateur
                 for a in Attribution.objects.filter(role=Attribution.Role.CONTRIBUTEUR).select_related("utilisateur")}
        cellules = [(k, o) for k in S.kpis_collectes(ref) for o in orgs.values() if o.actif and o.niveau_id == k.granularite_id]
        aujourd_hui = timezone.localdate()
        dernier = min(P.ajouter_mois(aujourd_hui.replace(day=1), -1), datetime.date(2026, 12, 1))
        debut, mois = datetime.date(MOIS_DEPUIS, 1, 1), []
        while debut <= dernier:
            mois.append(debut)
            debut = P.ajouter_mois(debut, 1)
        h, reponses, campagnes = random.Random(2027), [], []
        for d in mois:
            ouvert = d == dernier
            lendemain = P.ajouter_mois(d, 1)
            c, _ = P.campagne(ref, d, statut=Campagne.Statut.OUVERTE if ouvert else Campagne.Statut.CLOTUREE,
                              date_ouverture=lendemain, date_fin_saisie=lendemain + datetime.timedelta(days=14 if not ouvert else 40),
                              seuil_ecart=Decimal("0.3"))
            campagnes.append(c)
            for k, o in cellules:
                u = spocs.get((k.pk, o.pk))
                if ouvert and (u is None or h.random() > 0.55):
                    continue
                v, texte = self.reponse(k, o, d.year)
                if v is not None and not k.est_herite:  # part du mois dans l'année, selon la saison
                    poids = POIDS_MOIS[d.month - 1] / sum(POIDS_MOIS)
                    bruit = random.Random(f"{k.pk}|{o.pk}|{d}").uniform(-0.03, 0.03)
                    v = Decimal(str(round(float(v) * poids * (1 + bruit), self._profil(k)[2])))
                valide = not ouvert or h.random() < 0.6
                reponses.append(Reponse(periode=c.periode, kpi=k, organisation=o, valeur=v, texte=texte,
                                        statut=Reponse.Statut.VALIDE if valide else Reponse.Statut.BROUILLON, origine=Reponse.Origine.SAISIE,
                                        saisi_par=u, valide_par=u if valide else None,
                                        date_validation=timezone.now() if valide else None))
        Reponse.objects.bulk_create(reponses, ignore_conflicts=True, batch_size=2000)
        for c in campagnes:  # dans l'ordre : chaque mois peut citer le précédent ([ENR-01@P-1])
            recalculer(c, propager=False)
        for c in passees:
            if c.exercice >= MOIS_DEPUIS:
                recalculer(c, propager=False)  # année clôturée : cumul des mois
        controler(campagnes[-1])
        self.ecrire(f"Energy: {len(campagnes)} monthly campaigns, {len(reponses)} values entered")


def charger(mot_de_passe=MOT_DE_PASSE, ecrire=None):
    """Tout le jeu d'essai dans une base vide (comme l'ancienne option de ``load_demo``)."""
    from parametres.models import Instance

    from espaces import contexte as ESP

    Instance.objects.update_or_create(pk=1, defaults=IDENTITE)
    ch = Chargeur(ecrire)
    with ESP.atomic():
        PR.creer_par_defaut()
        PR.couleurs_types_par_defaut()
        langues()
        niveaux()
        referentiel()
        orgs = organisations()
        kpis()
        referentiels()
        traductions()
        composer()  # « Tableau de bord direction » : thèmes repris des deux autres référentiels
        cpt = comptes(mot_de_passe)
        attributions(cpt, orgs, list(S.kpis_collectes()))
        kpis_rediges(cpt, orgs)
        passees, c2026 = ch.campagnes()
        regles()
        ch.mensuels = {k for k, f in frequences_de_saisie().items() if f == "mois"}
        ch.historique(passees, orgs)
        if ch.mensuels:
            ch.energie_mensuelle(orgs, passees)
        ch.saisies(c2026, cpt, orgs)
        Reponse.objects.filter(statut=Reponse.Statut.VALIDE, date_validation__isnull=False,
                               date_maj__gt=models.F("date_validation")).update(date_maj=models.F("date_validation"))
        CD.vues_demo(CLIENT, VUES)
        CD.listes_demo()
        CD.marquer_demo(CLIENT)
        from collecte.calcul import geler_periodes_closes

        geler_periodes_closes()
    return orgs, cpt
