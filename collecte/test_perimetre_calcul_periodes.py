"""Règle du projet : la règle (« une période ne calcule que les KPI de ses campagnes »)
vaut aussi pour les années, les semestres et les trimestres (``calcul.perimetre_calcul``).

Cas écrits à la main : périmètre d'une année (ses campagnes, et celles des périodes qu'elle contient : cumuls des mois),
KPI d'un autre référentiel sans campagne, période sans aucune campagne (tous les KPI, comme avant), trimestre, année
rouverte (périmètre gelé : un KPI créé depuis n'y est pas calculé), ménage des lignes déjà écrites (migration
``collecte/0039``). Données inventées uniquement."""
import datetime
from decimal import Decimal

from django.test import TestCase

from referentiel.composition import composer
from referentiel.models import KPI, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import periodes as P
from .models import Campagne, Reponse

D = Decimal


class PerimetrePeriodesTests(TestCase):
    """Référentiel annuel RA {A, B, S, Z} ; mensuel RM {M, MC} ; annuel RX {X} sans campagne en 2026 ; trimestriel RQ {Q}.
    MC = [M] + [S@P-1] ; Z = [A] + [M]."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.g)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        for code in ("A", "B", "S", "M", "X", "Q"):
            KPI.objects.create(code=code, libelle=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                               methode_agregation="Somme")
        KPI.objects.create(code="MC", libelle="MC", type_saisie_id="Calculé", formule="[M] + [S@P-1]",
                           granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        KPI.objects.create(code="Z", libelle="Z", type_saisie_id="Calculé", formule="[A] + [M]",
                           granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        self.ra = Referentiel.objects.create(code="RA", nom="Annuel", ordre=1)
        self.rm = Referentiel.objects.create(code="RM", nom="Mensuel", ordre=2, frequence="mois")
        self.rx = Referentiel.objects.create(code="RX", nom="Autre", ordre=3)
        self.rq = Referentiel.objects.create(code="RQ", nom="Trimestriel", ordre=4, frequence="trimestre")
        composer({"A": ["T"], "B": ["T"], "S": ["T"], "Z": ["T"]}, self.ra)
        composer({"M": ["T"], "MC": ["T"]}, self.rm)
        composer({"X": ["T"]}, self.rx)
        composer({"Q": ["T"]}, self.rq)
        self.annee = P.campagne(self.ra, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE)[0]
        self.mois = {m: P.campagne(self.rm, datetime.date(2026, m, 1), statut=Campagne.Statut.OUVERTE)[0] for m in (1, 2, 3)}

    def kpis(self, periode):
        return set(Reponse.objects.filter(periode=periode).values_list("kpi_id", flat=True))

    def test_perimetre_d_une_annee(self):
        # ses campagnes (RA, et les sources de leurs formules) et celles des mois qu'elle contient (RM : cumuls)
        self.assertEqual(C.perimetre_calcul(self.annee.periode), {"A", "B", "S", "Z", "M", "MC"})

    def test_l_annee_n_ecrit_pas_les_kpi_d_un_autre_referentiel(self):
        C.recalculer(self.annee)
        self.assertEqual(self.kpis(self.annee.periode), {"A", "B", "S", "Z", "M", "MC"})  # avant : aussi X et Q

    def test_cumul_des_mois_garde_dans_l_annee(self):
        for m in (1, 2, 3):
            Reponse.objects.create(periode=self.mois[m].periode, kpi_id="M", organisation=self.e1, valeur=D(m),
                                   origine=Reponse.Origine.IMPORT)
        C.recalculer(self.annee)
        r = Reponse.objects.get(periode=self.annee.periode, kpi_id="M", organisation=self.e1)
        self.assertEqual(r.origine, Reponse.Origine.CUMUL)  # incomplet : avril à décembre manquent, mais la case est là

    def test_annee_sans_campagne_qui_contient_des_mois(self):
        mois27 = P.campagne(self.rm, datetime.date(2027, 1, 1), statut=Campagne.Statut.OUVERTE)[0]
        annee27 = P.annuelle(2027)
        self.assertFalse(annee27.campagnes.exists())
        self.assertEqual(C.perimetre_calcul(annee27), {"M", "MC", "S"})
        self.assertEqual(C.perimetre_calcul(mois27.periode), {"M", "MC", "S"})

    def test_periode_sans_aucune_campagne_inchangee(self):
        self.assertIsNone(C.perimetre_calcul(P.annuelle(2031)))  # ni campagne ni période contenue : tous les KPI, comme avant

    def test_trimestre(self):
        t1 = P.campagne(self.rq, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE)[0]
        self.assertEqual(t1.periode.type, "trimestre")
        self.assertEqual(C.perimetre_calcul(t1.periode), {"Q", "M", "MC", "S"})
        self.assertEqual(C.perimetre_calcul(self.annee.periode), {"A", "B", "S", "Z", "M", "MC", "Q"})

    def test_les_mois_gardent_la_regle_d3(self):
        self.assertEqual(C.perimetre_calcul(self.mois[1].periode), {"M", "MC", "S"})


class AnneeRouverteTests(TestCase):
    """Un KPI créé après la clôture d'un exercice n'apparaît pas dans l'exercice rouvert (recalculé), même ajouté à son
    référentiel : le périmètre de l'année est gelé à sa réouverture (KPI qui y avaient une case)."""

    def setUp(self):
        from .administration import changer_statut

        self.changer_statut = changer_statut
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        KPI.objects.create(code="EFF", libelle="EFF", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")
        self.ref = Referentiel.objects.create(code="RAP", nom="Rapport", ordre=1)
        composer({"EFF": ["T"]}, self.ref)
        self.c = P.campagne(self.ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE)[0]
        Reponse.objects.create(periode=self.c.periode, kpi_id="EFF", organisation=self.e1, valeur=D(3),
                               origine=Reponse.Origine.SAISIE)
        C.recalculer(self.c)
        changer_statut(self.admin, self.c, "cloturer")

    def test_kpi_cree_depuis_absent_de_l_annee_rouverte_et_recalculee(self):
        KPI.objects.create(code="NEW", libelle="NEW", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")
        composer({"NEW": ["T"]}, self.ref)
        self.changer_statut(self.admin, self.c, "rouvrir", garder=False)  # recalculée avec les réglages d'aujourd'hui
        self.c.periode.refresh_from_db()
        self.assertEqual(self.c.periode.perimetre_fige, ["EFF"])
        self.assertFalse(Reponse.objects.filter(periode=self.c.periode, kpi_id="NEW").exists())
        C.recalculer(self.c)  # recalcul complet pendant la revue : toujours pas
        self.assertFalse(Reponse.objects.filter(periode=self.c.periode, kpi_id="NEW").exists())
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi_id="EFF", organisation=self.g).valeur, D(3))

    def test_campagne_jamais_close_sans_perimetre_gele(self):
        c26 = P.campagne(self.ref, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE)[0]
        self.assertIsNone(c26.periode.perimetre_fige)
        KPI.objects.create(code="NEW", libelle="NEW", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")
        composer({"NEW": ["T"]}, self.ref)
        C.recalculer(c26)
        self.assertTrue(Reponse.objects.filter(periode=c26.periode, kpi_id="NEW").exists())  # année en cours : il y entre


class MenagePeriodesTests(TestCase):
    """Base existante : la migration ``collecte/0039`` pose le recalcul des campagnes non clôturées ; la fin de
    « migrate » le fait : les cases sans objet des années ouvertes partent (vides, calculées) ; celles des exercices clos
    restent telles quelles (aucun chiffre publié ne change)."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        for code in ("A", "X"):
            KPI.objects.create(code=code, libelle=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                               methode_agregation="Somme")
        ra = Referentiel.objects.create(code="RA", nom="Annuel", ordre=1)
        composer({"A": ["T"]}, ra)
        composer({"X": ["T"]}, Referentiel.objects.create(code="RX", nom="Autre", ordre=2))
        self.ouverte = P.campagne(ra, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE)[0]
        self.close = P.campagne(ra, datetime.date(2025, 1, 1), statut=Campagne.Statut.CLOTUREE)[0]
        lignes = []
        for c in (self.ouverte, self.close):
            lignes += [Reponse(periode=c.periode, kpi_id="X", organisation=self.g, origine=Reponse.Origine.AGREGATION,
                               statut=Reponse.Statut.INCOMPLET, message_calcul="Incomplet : E1")]
        lignes.append(Reponse(periode=self.ouverte.periode, kpi_id="X", organisation=self.e1, valeur=D(5),
                              origine=Reponse.Origine.SAISIE, statut=Reponse.Statut.BROUILLON))
        Reponse.objects.bulk_create(lignes)

    def test_migration_pose_le_menage_fait_a_la_fin_de_migrate(self):
        from importlib import import_module

        from django.apps import apps as django_apps

        from referentiel.models import TravailApresMiseAJour

        from .mise_a_jour import MOTIFS_EN, faire_les_travaux

        migration = import_module("collecte.migrations.0039_menage_periodes_hors_perimetre")
        migration.poser_recalcul(django_apps, None)
        self.assertIn(TravailApresMiseAJour.objects.get(code="recalcul").motif, MOTIFS_EN)  # message anglais pour l'IT
        self.assertEqual(faire_les_travaux(), ["recalcul"])
        self.assertFalse(Reponse.objects.filter(periode=self.ouverte.periode, kpi_id="X", organisation=self.g).exists())
        # la saisie reste (jamais effacée) ; l'exercice clos garde sa case telle qu'elle a été publiée
        self.assertTrue(Reponse.objects.filter(periode=self.ouverte.periode, kpi_id="X", organisation=self.e1).exists())
        self.assertTrue(Reponse.objects.filter(periode=self.close.periode, kpi_id="X", organisation=self.g).exists())
