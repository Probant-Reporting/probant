"""Une période mensuelle ne calcule que les KPI du périmètre de ses campagnes
(``calcul.perimetre_calcul``, ``calcul.prevoir``).

Avant, un mois écrivait une case (le plus souvent « incomplet ») pour chaque KPI du catalogue à chaque niveau au-dessus
de sa granularité : 2,3 millions de lignes sur 3,07 millions au premier audit de volume. Aucune valeur réellement
calculée ne doit changer : seules les lignes sans objet disparaissent. Cas écrits à la main, puis équivalence sur des
cas générés (graines fixes) entre le moteur avec et sans la décision.

Données inventées uniquement."""
import datetime
import os
import sys
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.db import transaction
from django.test import TestCase

from referentiel.composition import composer
from referentiel.models import KPI, Niveau, Organisation, Referentiel

from . import calcul as C
from . import periodes as P
from .models import Campagne, Reponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "qa"))

D = Decimal


class PerimetreMoisTests(TestCase):
    """Référentiel annuel {A, B, S, Z} ; référentiel mensuel {M, MC}. MC = [M] + [S@P-1] (S : source, donc dans le
    périmètre du mois) ; Z = [A] + [M] (annuel seulement)."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.g)
        for code in ("A", "B", "S", "M"):
            KPI.objects.create(code=code, libelle=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                               methode_agregation="Somme")
        KPI.objects.create(code="MC", libelle="MC", type_saisie_id="Calculé", formule="[M] + [S@P-1]",
                           granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        KPI.objects.create(code="Z", libelle="Z", type_saisie_id="Calculé", formule="[A] + [M]",
                           granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        self.ra = Referentiel.objects.create(code="RA", nom="Annuel", ordre=1)
        self.rm = Referentiel.objects.create(code="RM", nom="Mensuel", ordre=2, frequence="mois")
        composer({"A": ["T"], "B": ["T"], "S": ["T"], "Z": ["T"]}, self.ra)
        composer({"M": ["T"], "MC": ["T"]}, self.rm)
        self.annee, _ = P.campagne(self.ra, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE)
        self.mois = {m: P.campagne(self.rm, datetime.date(2026, m, 1), statut=Campagne.Statut.OUVERTE)[0] for m in (1, 2)}

    def kpis_du_mois(self, m):
        return set(Reponse.objects.filter(periode=self.mois[m].periode).values_list("kpi_id", flat=True))

    def test_perimetre(self):
        self.assertEqual(C.perimetre_calcul(self.mois[1].periode), {"M", "MC", "S"})
        # l'année gardait tous les KPI (règle limitée aux mois) : ses campagnes et celles des
        # mois qu'elle contient (test_perimetre_calcul_periodes.py)
        self.assertEqual(C.perimetre_calcul(self.annee.periode), {"A", "B", "S", "Z", "M", "MC"})

    def test_le_mois_n_ecrit_que_les_kpi_de_son_perimetre(self):
        C.recalculer(self.mois[1])
        self.assertEqual(self.kpis_du_mois(1), {"M", "MC", "S"})  # avant : aussi A, B et Z (« incomplet »)
        C.recalculer(self.annee)
        self.assertTrue({"A", "B", "Z"} <= set(Reponse.objects.filter(periode=self.annee.periode)
                                               .values_list("kpi_id", flat=True)))

    def test_recalcul_apres_une_saisie_n_ecrit_pas_les_dependants_hors_perimetre(self):
        Reponse.objects.create(periode=self.mois[2].periode, kpi_id="M", organisation=self.e1, valeur=D(4),
                               origine=Reponse.Origine.SAISIE)  # signal : recalcul de M et de ses dépendants (MC, Z)
        self.assertNotIn("Z", self.kpis_du_mois(2))  # avant : Z écrit dans le mois
        self.assertEqual(Reponse.objects.get(periode=self.mois[2].periode, kpi_id="MC", organisation=self.e1).statut,
                         Reponse.Statut.INCOMPLET)  # S de janvier manque

    def test_lignes_deja_ecrites_sans_objet_au_recalcul_complet(self):
        p = self.mois[1].periode
        Reponse.objects.bulk_create([
            Reponse(periode=p, kpi_id="A", organisation=self.g, origine=Reponse.Origine.AGREGATION,
                    statut=Reponse.Statut.INCOMPLET, message_calcul="Incomplet : E1, E2"),
            Reponse(periode=p, kpi_id="Z", organisation=self.e1, origine=Reponse.Origine.CALCUL,
                    statut=Reponse.Statut.INCOMPLET, commentaire="Note gardée"),
        ])
        C.recalculer(self.mois[1])
        self.assertFalse(Reponse.objects.filter(periode=p, kpi_id="A").exists())
        z = Reponse.objects.get(periode=p, kpi_id="Z")  # un commentaire : la case reste, vide (comme toute case sans objet)
        self.assertEqual((z.origine, z.statut, z.commentaire), (Reponse.Origine.SAISIE, Reponse.Statut.A_SAISIR, "Note gardée"))

    def test_mois_cloture_garde_ses_lignes(self):
        p = self.mois[1].periode
        Reponse.objects.bulk_create([Reponse(periode=p, kpi_id="A", organisation=self.g, origine=Reponse.Origine.AGREGATION,
                                             statut=Reponse.Statut.INCOMPLET)])
        Campagne.objects.filter(pk=self.mois[1].pk).update(statut=Campagne.Statut.CLOTUREE)
        C.recalculer(self.mois[1])
        self.assertTrue(Reponse.objects.filter(periode=p, kpi_id="A").exists())  # période figée : rien n'y change

    def test_migration_pose_le_menage_fait_a_la_fin_de_migrate(self):
        """Base existante : la migration ``collecte/0035`` pose le recalcul des campagnes non clôturées ; la fin de
        « migrate » le fait avec le code installé : les cases sans objet des mois ouverts partent, les mois clôturés
        restent tels quels."""
        from importlib import import_module

        from django.apps import apps as django_apps

        from referentiel.models import TravailApresMiseAJour

        from .mise_a_jour import MOTIFS_EN, faire_les_travaux

        Campagne.objects.filter(pk=self.mois[2].pk).update(statut=Campagne.Statut.CLOTUREE)
        Reponse.objects.bulk_create([Reponse(periode=self.mois[m].periode, kpi_id="A", organisation=self.g,
                                             origine=Reponse.Origine.AGREGATION, statut=Reponse.Statut.INCOMPLET)
                                     for m in (1, 2)])
        migration = import_module("collecte.migrations.0035_menage_mois_hors_perimetre")
        migration.poser_recalcul(django_apps, None)
        self.assertIn(TravailApresMiseAJour.objects.get(code="recalcul").motif, MOTIFS_EN)  # message anglais pour l'IT
        self.assertEqual(faire_les_travaux(), ["recalcul"])
        self.assertFalse(Reponse.objects.filter(periode=self.mois[1].periode, kpi_id="A").exists())
        self.assertTrue(Reponse.objects.filter(periode=self.mois[2].periode, kpi_id="A").exists())

    def test_installation_sans_kpi_dans_les_referentiels(self):
        from referentiel.models import ElementReferentiel

        ElementReferentiel.objects.all().delete()
        self.assertIsNone(C.perimetre_calcul(self.mois[1].periode))  # tout le catalogue est collecté, tout est calculé


# fréquences des référentiels dont une période reçoit le périmètre : les siennes et celles des périodes qu'elle contient
# (chaque période d'un cas généré a une campagne de son référentiel)
CONTENUES = {"mois": ("mois",), "trimestre": ("trimestre", "mois"), "annee": ("annee", "trimestre", "mois")}


def perimetre_attendu(cas, type_="mois"):
    """Périmètre des périodes ``type_`` d'un cas généré, calculé à part : KPI des référentiels de cette fréquence et des
    fréquences plus fines (les périodes qu'elle contient), pour une période plus longue qu'un mois les KPI hors de tout
    référentiel, et sources de leurs formules, de proche en proche (lu dans le texte des formules) ; None : tout le
    catalogue (aucun KPI dans aucun référentiel)."""
    import re

    if not any(k["freqs"] for k in cas["kpis"]):
        return None
    sources = {k["code"]: set(re.findall(r"\[\s*(K\d+)", k["formula"])) for k in cas["kpis"]}
    utiles = {k["code"] for k in cas["kpis"] if set(CONTENUES[type_]) & set(k["freqs"])}
    if type_ != "mois":  # périodes plus longues : aussi les KPI hors de tout référentiel (calcul.perimetre_calcul, point 2)
        utiles |= {k["code"] for k in cas["kpis"] if not k["freqs"]}
    pile = list(utiles)
    while pile:
        for s in sources.get(pile.pop(), ()):
            if s not in utiles:
                utiles.add(s)
                pile.append(s)
    return utiles


def ancienne_saisie(cle, avec, sans, perimetre):
    """Seule autre différence admise : l'ancienne saisie d'un KPI devenu calculé (avant le passage en « Calculé »),
    dans un mois où ce KPI est hors du périmètre. Sans la décision, la formule la remplaçait (le plus souvent par
    « incomplet ») ; avec, la case n'est plus calculée et la saisie reste telle quelle : rien ne la lit (ni formule, ni
    cumul, ni export, ni Saisie : tous s'en tiennent au périmètre)."""
    type_, _, kpi, _ = cle
    perimetre = perimetre.get(type_) if isinstance(perimetre, dict) else perimetre
    return (perimetre is not None and kpi not in perimetre and avec[4] == "saisie"
            and sans[4] in ("calcul", "agregation"))


class PerimetreMoisEquivalenceTests(TestCase):
    """Sur des cas générés avec des mois (``qa/calculation_fuzz.py`` : arbres, organisations fermées, formules [X@P-1],
    [X@N-1], [X@AAAA], cumuls des mois dans l'année, imports, valeurs forcées, campagnes clôturées, saisies après coup,
    organisations fermées ou rattachées ailleurs), chaque état successif du moteur avec la règle du périmètre par campagne et sans elle :
    toute ligne écrite avec la décision est identique à celle écrite sans ; les lignes qui disparaissent sont toutes des
    cases calculées, agrégées ou cumulées d'un mois, d'un KPI hors du périmètre de ses campagnes. Graines fixes."""

    CAS = int(os.environ.get("PROBANT_PERIMETRE_MOIS_CAS", 6))

    def test_aucune_valeur_calculee_ne_change(self):
        import calculation_fuzz as CF

        faits, graine, disparues, gardees, pleines = 0, 0, 0, 0, 0
        while faits < self.CAS:
            graine += 1
            cas = CF.generate(graine)
            if "mois" not in cas["frequencies"]:
                continue
            faits += 1
            with self.subTest(graine=graine):
                etats = {}
                for avec in (False, True):
                    with transaction.atomic():
                        if avec:
                            CF._executer(cas, etats.setdefault(avec, []))
                        else:
                            with mock.patch.object(C, "perimetre_calcul", return_value=None):
                                CF._executer(cas, etats.setdefault(avec, []))
                        transaction.set_rollback(True)
                perimetre = {t: perimetre_attendu(cas, t) for t in CONTENUES}
                for (etape, sans), (_, avec) in zip(etats[False], etats[True]):
                    self.assertEqual(set(avec) - set(sans), set(), f"graine {graine}, {etape} : lignes en plus")
                    for cle, ligne in avec.items():
                        if ligne != sans[cle] and ancienne_saisie(cle, ligne, sans[cle], perimetre):
                            gardees += 1
                            continue
                        self.assertEqual(ligne, sans[cle], f"graine {graine}, {etape}, {cle}")
                    for cle in set(sans) - set(avec):
                        type_, _, kpi, _ = cle  # toute période, plus seulement les mois
                        self.assertIn(sans[cle][4], ("calcul", "agregation", "cumul"), f"graine {graine}, {cle}")
                        self.assertTrue(perimetre[type_] is not None and kpi not in perimetre[type_], f"graine {graine}, {cle}")
                        disparues += 1
                        pleines += sans[cle][0] != "incomplet"
        self.assertGreater(disparues, 0)  # le test n'est pas vide : des lignes sans objet ont bien disparu
        if os.environ.get("PROBANT_PERIMETRE_MOIS_CAS"):
            print(f"\nlignes sans objet évitées : {disparues} (dont {pleines} avec une valeur, N/A ou erreur) ; "
                  f"anciennes saisies gardées : {gardees}")

