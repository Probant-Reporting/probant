"""Démo du second espace, « Achats » (``charger_demo --espaces``) : un petit jeu fictif pour montrer un autre département
dans la même installation, avec sa propre base, sa propre identité et des rôles différents pour les mêmes personnes.

Arbre Groupe › Pays (France, Spain, Italy), un référentiel annuel « Suivi achats » de 9 KPI (montant, fournisseurs,
part locale, délai de paiement, charte, litiges, audit oui / non, catégorie principale en liste, une part calculée),
campagne 2025 clôturée et 2026 ouverte. Aucune donnée réelle : valeurs tirées au hasard (reproductibles)."""
import datetime
import random
from decimal import Decimal

from django.utils import timezone

from collecte import periodes as P
from collecte.calcul import recalculer
from collecte.models import Campagne, Reponse
from parametres import couleurs as CO
from parametres.models import Instance
from referentiel.composition import placer, theme_par_chemin
from referentiel.models import KPI, Attribution, Niveau, Organisation, Referentiel, Utilisateur

from . import _demo_commun as DC

PALETTE = CO.PALETTES["foret"]
IDENTITE = dict(titre="Suivi achats", sous_titre="Achats responsables", sigle="ACH", contact="l'équipe Achats",
                palette="foret", couleur_principale=PALETTE["principale"], couleur_accent=PALETTE["accent"],
                couleur_fond=PALETTE["fond"], couleur_texte=PALETTE["texte"], mise_en_place_terminee=True,
                mise_en_place_etape=8)
UNITES = [  # code, symbole, libellé, nombre entier, décimales, famille
    ("k€", "k€", "millier d'euros", False, 0, "Monnaie"), ("fournisseurs", "fournisseurs", "fournisseurs", True, 0, "Comptage"),
    ("jours", "jours", "jours", False, 0, "Durée"), ("litiges", "litiges", "litiges", True, 0, "Comptage"),
]
CATEGORIES = ["Transport et logistique", "Emballages", "Informatique", "Marketing"]
TYPES_REPONSE = [("OuiNon", "Oui / non", "oui_non", []), ("CategorieAchats", "Catégorie d'achats", "liste", CATEGORIES)]
KPIS = [  # code, nom, type de saisie, unité, réponse, agrégation, formule, thème
    ("ACH-01", "Montant des achats", "Saisi", "k€", "Numérique", "Somme", "", "Volumes"),
    ("ACH-02", "Fournisseurs actifs", "Saisi", "fournisseurs", "Numérique", "Somme", "", "Volumes"),
    ("ACH-03", "Part des achats locaux", "Saisi", "", "Pourcentage", "Moyenne", "", "Achats responsables"),
    ("ACH-05", "Fournisseurs signataires de la charte", "Saisi", "fournisseurs", "Numérique", "Somme", "", "Achats responsables"),
    ("ACH-09", "Part des fournisseurs signataires de la charte", "Calculé", "", "Pourcentage", "Formule", "[ACH-05] / [ACH-02]",
     "Achats responsables"),
    ("ACH-07", "Audit fournisseurs réalisé dans l'année", "Saisi", "", "OuiNon", "Décompte", "", "Achats responsables"),
    ("ACH-04", "Délai moyen de paiement des fournisseurs", "Saisi", "jours", "Numérique", "Moyenne", "", "Relation fournisseurs"),
    ("ACH-06", "Litiges fournisseurs", "Saisi", "litiges", "Numérique", "Somme", "", "Relation fournisseurs"),
    ("ACH-08", "Catégorie principale d'achats", "Saisi", "", "CategorieAchats", "Aucune", "", "Relation fournisseurs"),
]
PAYS = ["France", "Spain", "Italy"]
TAILLE = {"France": 1.0, "Spain": 0.55, "Italy": 0.4}
AVANCEMENT = {"France": 1.0, "Spain": 0.6, "Italy": 0.0}  # 2026 : France complète, Spain en cours, Italy pas commencée
COMPTES = [  # identifiant, prénom, nom, rôle dans l'espace Achats (même compte et même mot de passe que dans l'espace principal)
    ("admin", "Alice", "Admin (démo)", Utilisateur.Role.ADMIN),
    ("contributeur", "Camille", "Contributrice (démo)", Utilisateur.Role.VALIDATEUR),  # contributrice dans l'espace principal
    ("acheteur", "Adrien", "Acheteur (démo)", Utilisateur.Role.CONTRIBUTEUR),  # seulement dans Achats
]


def identite():
    i = Instance.courante()
    for champ, valeur in IDENTITE.items():
        setattr(i, champ, valeur)
    i.save()


def comptes(mot_de_passe):
    return {ident: DC.compte(ident, prenom, nom, role, mot_de_passe) for ident, prenom, nom, role in COMPTES}


def reglages():
    DC.unites_et_types(UNITES, TYPES_REPONSE)


def organisations():
    g, _ = Organisation.objects.update_or_create(nom="Exemplia Groupe", defaults={"niveau_id": Niveau.GROUP, "rang": 0})
    orgs = {g.nom: g}
    for i, pays in enumerate(PAYS):
        orgs[pays], _ = Organisation.objects.update_or_create(nom=pays, defaults={"niveau_id": Niveau.COUNTRY, "parent": g, "rang": i})
    return orgs


def referentiel():
    ref, _ = Referentiel.objects.update_or_create(code="ACHATS", defaults={
        "nom": "Suivi achats", "description": "Indicateurs annuels des achats responsables, par pays.", "couleur": PALETTE["principale"],
        "ordre": 1, "frequence": "annee", "comparaison": "N-1"})
    cache = {}
    for ordre, (code, nom, saisie, unite, reponse, agregation, formule, theme) in enumerate(KPIS, start=1):
        k, _ = KPI.objects.update_or_create(code=code, defaults=dict(
            libelle=nom, type_saisie_id=saisie, unite_id=unite or None, granularite_id=Niveau.COUNTRY, methode_agregation=agregation,
            formule=formule, type_reponse_id=reponse, equipe_responsable="Achats", ordre=ordre,
            decimales=1 if reponse == "Pourcentage" else 0))
        placer(k, ref, theme_par_chemin(ref, [theme], cache), ordre, obligatoire=code != "ACH-08")
    return ref


def campagnes():
    c2025, _ = P.campagne_annuelle(2025)
    c2025.statut, c2025.date_ouverture, c2025.date_fin_saisie = Campagne.Statut.CLOTUREE, datetime.date(2026, 1, 5), datetime.date(2026, 3, 31)
    c2025.save()
    aujourd_hui = timezone.localdate()
    c2026, _ = P.campagne_annuelle(2026)
    c2026.statut, c2026.seuil_ecart = Campagne.Statut.OUVERTE, Decimal("0.2")
    c2026.date_ouverture, c2026.date_fin_saisie = aujourd_hui - datetime.timedelta(days=14), aujourd_hui + datetime.timedelta(days=45)
    c2026.save()
    return c2025, c2026


def attributions(comptes, orgs):
    liens = []
    for k in KPI.objects.filter(type_saisie_id="Saisi"):
        for pays in PAYS:
            liens.append(Attribution(kpi=k, organisation=orgs[pays], utilisateur=comptes["acheteur"], role=Attribution.Role.CONTRIBUTEUR))
            liens.append(Attribution(kpi=k, organisation=orgs[pays], utilisateur=comptes["contributeur"], role=Attribution.Role.VALIDATEUR))
    Attribution.objects.bulk_create(liens, ignore_conflicts=True)


def _reponse(code, pays, exercice):
    r = random.Random(f"{code}|{pays}|{exercice}")
    t, tendance = TAILLE[pays], 1 + 0.04 * (exercice - 2025)
    if code == "ACH-01":
        return Decimal(round(r.uniform(9000, 12000) * t * tendance)), ""
    if code == "ACH-02":
        return Decimal(round(r.uniform(380, 450) * t)), ""
    if code == "ACH-05":
        return Decimal(round(float(_reponse("ACH-02", pays, exercice)[0]) * r.uniform(0.35, 0.6) * tendance)), ""
    if code == "ACH-03":
        return Decimal(str(round(r.uniform(0.35, 0.7), 4))), ""
    if code == "ACH-04":
        return Decimal(round(r.uniform(38, 58))), ""
    if code == "ACH-06":
        return Decimal(r.randint(0, 9)), ""
    if code == "ACH-07":
        return None, "Oui" if r.random() < 0.7 else "Non"
    return None, CATEGORIES[random.Random(f"{code}|{pays}").randrange(len(CATEGORIES))]


def valeurs(c2025, c2026, comptes, orgs):
    saisis = list(KPI.objects.filter(type_saisie_id="Saisi"))
    Reponse.objects.bulk_create([
        Reponse(periode=c2025.periode, kpi=k, organisation=orgs[p], valeur=_reponse(k.pk, p, 2025)[0], texte=_reponse(k.pk, p, 2025)[1],
                statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.IMPORT) for k in saisis for p in PAYS], ignore_conflicts=True)
    h = random.Random(2026)
    u = comptes["acheteur"]
    nouvelles = []
    for p in PAYS:
        for k in saisis:
            if h.random() >= AVANCEMENT[p]:
                continue
            valide = p == "France" or h.random() < 0.5
            v, texte = _reponse(k.pk, p, 2026)
            nouvelles.append(Reponse(periode=c2026.periode, kpi=k, organisation=orgs[p], valeur=v, texte=texte, saisi_par=u,
                                     statut=Reponse.Statut.VALIDE if valide else Reponse.Statut.BROUILLON, origine=Reponse.Origine.SAISIE,
                                     valide_par=u if valide else None, date_validation=timezone.now() if valide else None))
    Reponse.objects.bulk_create(nouvelles, ignore_conflicts=True)
    recalculer(c2025)
    recalculer(c2026)
    return len(nouvelles)


def charger(mot_de_passe, sortie):
    """Tout le jeu « Achats » dans l'espace courant (base vide)."""
    from parametres import referentiel as PR

    identite()
    PR.creer_par_defaut()
    reglages()
    orgs = organisations()
    referentiel()
    c = comptes(mot_de_passe)
    attributions(c, orgs)
    c2025, c2026 = campagnes()
    n = valeurs(c2025, c2026, c, orgs)
    sortie(f"Space \"Achats\": {len(orgs)} organisations, {KPI.objects.count()} KPIs, 2025 campaign closed, "
           f"2026 open ({n} entries)")
