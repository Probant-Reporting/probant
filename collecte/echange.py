"""Import des valeurs historiques d'un fichier (cahier des charges, section 4.6)."""
from collections import Counter

from django.db import transaction

from parametres.libelles import libelle
from referentiel.echange import Rapport, texte_cellule, ouvrir_classeur
from referentiel.models import KPI, Organisation, OrgAlias

from .models import VALEUR_MAX, Reponse, valeur_enregistree
from .periodes import campagne_annuelle
from espaces import contexte as ESP


def correspondance_organisations():
    d = {o.nom: o for o in Organisation.objects.all()}
    for a in OrgAlias.objects.select_related("organisation"):
        d.setdefault(a.libelle, a.organisation)
    return {k.strip(): v for k, v in d.items()}


@ESP.atomic
def importer_valeurs(chemin, onglet=None, annees=None, types=None, simulation=False):
    """Importe les colonnes ID KPI, Result, Organisation, Year de l'onglet donné, sinon du premier onglet qui les contient.

    - Les organisations sont reconnues par leur nom ou un alias ; les lignes non reconnues sont ignorées et comptées.
    - Les pourcentages des KPI saisis, stockés de 0 à 100 dans le fichier historique, sont convertis en fraction.
    - Les valeurs existantes saisies dans l'outil ne sont jamais écrasées.
    """
    wb = ouvrir_classeur(chemin)
    if onglet is None:
        onglet = next((ws.title for ws in wb.worksheets
                       if {"ID KPI", "Year"} <= {texte_cellule(h) for h in next(ws.iter_rows(max_row=1, values_only=True), ())}),
                      wb.sheetnames[0])
    rows = wb[onglet].iter_rows(values_only=True)
    entetes = [texte_cellule(h) for h in next(rows)]
    col = {}
    for i, h in enumerate(entetes):
        col.setdefault(h, i)  # première occurrence : le bloc consolidé
    orgs = correspondance_organisations()
    kpis = {k.code: k for k in KPI.objects.all()}
    rapport, ignores = Rapport(), Counter()
    campagnes, vus, a_creer = {}, set(), []
    existantes = set(Reponse.objects.filter(origine=Reponse.Origine.SAISIE).values_list("periode_id", "kpi_id", "organisation_id"))
    # nombres écrits en texte : lus dans la langue de l'en-tête « Result » (anglais), comme tout import de valeurs
    from .fichiers import lire_nombre_importe
    from .imports import langue_des_nombres, remarque_ambigu

    langue, _ = langue_des_nombres(entetes[col["Result"]])
    ambigus = 0
    for n, row in enumerate(rows, start=2):
        kid = texte_cellule(row[col["ID KPI"]])
        if not kid:
            continue
        try:
            annee = int(float(texte_cellule(row[col["Year"]])))
        except ValueError:
            continue
        if annees and annee not in annees:
            continue
        kpi = kpis.get(kid)
        if kpi is None:
            ignores[libelle("suivi.echange.kpi_inconnu")] += 1
            continue
        if types and kpi.type_saisie_id not in types:
            continue
        org = orgs.get(texte_cellule(row[col["Organisation"]]))
        if org is None:
            ignores[libelle("suivi.echange.organisation_inconnue", organisation=texte_cellule(row[col["Organisation"]]))] += 1
            continue
        try:
            v = lire_nombre_importe(row[col["Result"]], langue)
        except ValueError:
            v = None
        if v is None:
            ignores[libelle("suivi.echange.non_numerique")] += 1
            continue
        if not v.is_finite() or abs(v) >= VALEUR_MAX:
            ignores[libelle("suivi.echange.non_numerique_ou_grande")] += 1
            continue
        if kpi.est_pourcentage and kpi.comportement == "saisie":
            v = v / 100
        if annee not in campagnes:
            campagnes[annee], _ = campagne_annuelle(annee, statut="cloturee")
        if kpi.est_calcule and campagnes[annee].statut != "cloturee":
            # case calculée d'une période non clôturée : un chiffre importé tel quel y resterait « en sommeil » (le calcul
            # ne l'utilise que s'il est impossible) ; la forcer se fait dans l'outil (import de valeurs, panneau de saisie)
            ignores[libelle("suivi.echange.calcule_ouverte")] += 1
            continue
        cle = (annee, kid, org.id)
        if cle in vus:
            ignores[libelle("suivi.echange.doublon")] += 1
            continue
        vus.add(cle)
        if (campagnes[annee].periode_id, kid, org.id) in existantes:
            ignores[libelle("suivi.echange.deja_saisi")] += 1
            continue
        a_creer.append(Reponse(periode=campagnes[annee].periode, kpi=kpi, organisation=org, valeur=valeur_enregistree(v),
                               statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.IMPORT))
        ambigus += bool(remarque_ambigu(row[col["Result"]], langue))
    for motif, nb in ignores.most_common():
        rapport.avertissements.append(("ignoré", libelle("suivi.echange.ignorees", n=nb, motif=motif)))
    if ambigus:  # « 1,234 » : lu 1234 (anglais), jamais en silence
        rapport.avertissements.append(("ambigu", libelle("suivi.echange.ambigus", n=ambigus)))
    if simulation:
        rapport.crees = len(a_creer)
        transaction.set_rollback(True, using=ESP.alias_courant())
        return rapport
    anciens = Reponse.objects.filter(origine=Reponse.Origine.IMPORT, periode__in=[c.periode for c in campagnes.values()])
    if types:
        anciens = anciens.filter(kpi__type_saisie__in=types)
    anciens.delete()
    Reponse.objects.bulk_create(a_creer, batch_size=2000)
    rapport.crees = len(a_creer)
    return rapport
