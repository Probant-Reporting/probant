"""Import de valeurs, KPI commun à deux campagnes de la même période. L'import préfère
toujours la campagne ouverte (avant : la première dans l'ordre des référentiels, même close). Deux ouvertes : ordre des
référentiels. Deux closes : comportement d'avant (correction réservée à l'administrateur). Une colonne « Référentiel »
remplie désigne sa campagne (fichier à remplir : celui de la campagne ouverte ; correction voulue d'une campagne close)."""
from parametres.libelles import libelle
from referentiel.models import ElementReferentiel, Referentiel

from . import imports as I
from .aides_tests.arbre_france import csv_
from .aides_tests.saisie import Base
from .models import Campagne


class KpiCommunImportTests(Base):
    def setUp(self):
        super().setUp()
        for k in (self.eff, self.taux):
            ElementReferentiel.objects.create(referentiel=self.c.referentiel, kpi=k)
        # référentiel voisin AVANT celui de la campagne ouverte dans l'ordre des référentiels
        Referentiel.objects.filter(pk=self.c.referentiel_id).update(ordre=50)
        self.autre_ref = Referentiel.objects.create(code="AUTRE", nom="Cadre voisin", ordre=0)
        ElementReferentiel.objects.create(referentiel=self.autre_ref, kpi=self.eff)
        self.voisine = Campagne.objects.create(referentiel=self.autre_ref, periode=self.c.periode,
                                               exercice=self.c.exercice, statut=Campagne.Statut.CLOTUREE)
        from referentiel.models import Attribution

        Attribution.objects.get_or_create(kpi=self.eff, organisation=self.e1, utilisateur=self.contrib)

    def ligne(self, u, ref=None):
        tetes = ["ID KPI", "Organisation", "Exercice", "Valeur"] + (["Référentiel"] if ref else [])
        valeurs = ["EFF", "E1", self.c.exercice, "55"] + ([ref] if ref else [])
        return I.analyser(u, csv_([tetes, valeurs])).lignes[0]

    def test_close_avant_dans_l_ordre_l_import_vise_l_ouverte(self):
        for u in (self.contrib, self.admin):
            with self.subTest(u=u.username):
                l = self.ligne(u)
                self.assertEqual(l.campagne.pk, self.c.pk)
                # la campagne ouverte refuse ce KPI : le motif dit pourquoi, plus « campagne close »
                self.assertEqual(l.motif, libelle("saisie.msg.kpi_commun_cloture", campagne=self.voisine.libelle,
                                                  referentiel="Cadre voisin"))

    def test_kpi_propre_a_l_ouverte_passe(self):
        l = I.analyser(self.contrib, csv_([["ID KPI", "Organisation", "Exercice", "Valeur"],
                                           ["TX", "E1", self.c.exercice, "30"]])).lignes[0]
        self.assertEqual(l.campagne.pk, self.c.pk)
        self.assertNotEqual(l.action, "rejet", l.motif)

    def test_deux_ouvertes_ordre_des_referentiels(self):
        Campagne.objects.filter(pk=self.voisine.pk).update(statut=Campagne.Statut.OUVERTE)
        self.assertEqual(self.ligne(self.contrib).campagne.pk, self.voisine.pk)

    def test_deux_closes_comportement_d_avant(self):
        Campagne.objects.filter(pk=self.c.pk).update(statut=Campagne.Statut.CLOTUREE)
        self.assertEqual(self.ligne(self.admin).campagne.pk, self.voisine.pk)
        self.assertEqual(self.ligne(self.contrib).motif, Campagne.objects.get(pk=self.voisine.pk).motif_lecture_seule)

    def test_colonne_referentiel_designe_sa_campagne(self):
        self.assertEqual(self.ligne(self.admin, ref="Cadre voisin").campagne.pk, self.voisine.pk)
        self.assertEqual(self.ligne(self.contrib, ref=str(self.c.referentiel)).campagne.pk, self.c.pk)
