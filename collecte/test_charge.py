"""Campagne simulée avec beaucoup d'utilisateurs (essai de charge) : ce qui a été allégé
pour tenir la charge donne les mêmes résultats qu'avant, sur des données inventées."""
from decimal import Decimal as D

from django.core.exceptions import ValidationError
from django.urls import reverse

from referentiel.models import KPI, Attribution
from referentiel.plans import Plan

from . import saisie as S
from .calcul import Calculateur, catalogue_kpis, kpis_lus_avant
from .models import Reponse
from .aides_tests.saisie import Base

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class AllegementsTests(Base):
    def test_perimetre_restreint_a_quelques_kpi(self):
        # le panneau ne lit que les KPI des alertes affichées : même réponse que le périmètre complet, pour ces KPI
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.autre)
        for u in (self.contrib, self.autre, self.valid, self.admin):
            for codes in ({"EFF"}, {"TX"}, {"EFF", "TX"}, {"DBL"}, set()):
                complet = {(k.code, o.pk) for k, o in S.cellules(u, campagne=self.c) if k.code in codes}
                self.assertEqual({(k.code, o.pk) for k, o in S.cellules(u, campagne=self.c, kpi_ids=codes)}, complet, (u, codes))

    def test_place_d_un_seul_kpi(self):
        for code in ("EFF", "TX", "DBL", "INCONNU"):
            self.assertEqual(Plan(kpis=[code]).places(code), Plan().places(code))
            self.assertEqual(Plan(self.c.referentiel, kpis=[code]).referentiels_de(code), Plan(self.c.referentiel).referentiels_de(code))

    def test_catalogue_lu_avant_le_verrou(self):
        # prêté aux calculs de l'enregistrement tant qu'aucune fiche ne change ; relu sinon (formule changée entre-temps)
        with kpis_lus_avant():
            self.assertIs(catalogue_kpis()["DBL"], catalogue_kpis()["DBL"])
            self.enregistrer("10")
            self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.calc, organisation=self.e1).valeur, 20)
            dbl = KPI.objects.get(pk="DBL")
            dbl.formule = "[EFF] * 3"
            dbl.save()
            self.assertEqual(catalogue_kpis()["DBL"].formule, "[EFF] * 3")
            self.enregistrer("11")
            self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.calc, organisation=self.e1).valeur, 33)
        self.assertEqual(Calculateur(self.c).kpis["DBL"].formule, "[EFF] * 3")

    def test_import_par_paquets(self):
        # import de la page Import / Export : une transaction par paquet (le verrou d'écriture est rendu entre deux) ;
        # mêmes valeurs, mêmes totaux et même journal qu'en une fois ; une saisie faite entre deux paquets est gardée
        from unittest import mock

        from django.utils import timezone

        from . import imports as I
        from .models import Journal
        from .outils_tests import xlsx

        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.contrib)
        Attribution.objects.create(kpi=self.taux, organisation=self.e2, utilisateur=self.contrib)
        vu_le = timezone.now()
        lignes = [["ID KPI", "Organisation", "Valeur"], ["EFF", "E1", 10], ["TX", "E1", 20], ["EFF", "E2", 30], ["TX", "E2", 40]]
        reel = I._modifiees_depuis
        paquets = []

        def modifiees_depuis(*a, **k):  # l'administrateur saisit EFF / E2 entre le premier et le second paquet
            paquets.append(len(a[0]))
            if len(paquets) == 2:
                S.enregistrer(self.admin, self.c, self.eff, self.e2, "99", False, "")
            return reel(*a, **k)

        with mock.patch.object(I, "PAQUET_IMPORT", 2), mock.patch.object(I, "_modifiees_depuis", modifiees_depuis):
            _, n, avertissements = I.appliquer(self.contrib, xlsx(lignes), "f.xlsx", campagne_defaut=self.c.pk, vu_le=vu_le,
                                               par_paquets=True)
        self.assertEqual((paquets, n), ([2, 2], 3))
        self.assertEqual(len(avertissements), 1)  # EFF / E2 modifiée entre deux paquets : pas écrasée
        valeurs = {(r.kpi_id, r.organisation.nom): r.valeur for r in Reponse.objects.filter(periode=self.c.periode,
                                                                                              kpi__in=[self.eff, self.taux], origine="saisie")}
        self.assertEqual(valeurs, {("EFF", "E1"): 10, ("TX", "E1"): D("0.2"), ("EFF", "E2"): 99, ("TX", "E2"): D("0.4")})
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.p).valeur, 109)  # total
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.calc, organisation=self.e1).valeur, 20)
        self.assertEqual(Journal.objects.get(action="import_valeurs").apres, "f.xlsx : 3 valeur(s)")

    def test_valider_depuis_le_panneau_garde_la_saisie_si_refusee(self):
        # enregistrement et validation dans une même transaction : une validation refusée garde la saisie
        self.client.force_login(self.contrib)
        url = reverse("collecte:cellule", args=[self.c.pk, "EFF", self.e1.pk])
        S.enregistrer(self.contrib, self.c, self.eff, self.e1, "", True, "")  # N/A sans commentaire : validation refusée
        rep = self.client.post(url, {"action": "valider", "valeur": "", "non_applicable": "on",
                                     "version": S.version(S.reponse_de(self.c, self.eff, self.e1))}, **FETCH)
        self.assertEqual(rep.status_code, 200)
        r = S.reponse_de(self.c, self.eff, self.e1)
        self.assertEqual((r.non_applicable, r.statut), (True, Reponse.Statut.BROUILLON))
        rep = self.client.post(url, {"action": "valider", "valeur": "42", "version": S.version(r)}, **FETCH)
        r = S.reponse_de(self.c, self.eff, self.e1)
        self.assertEqual((r.valeur, r.statut, r.valide_par), (42, Reponse.Statut.VALIDE, self.contrib))
        with self.assertRaises(ValidationError):
            S.repasser_brouillon(self.contrib, self.c, self.taux, self.e1)  # rien à repasser en brouillon
