"""Périodes et fréquences : calendrier commun, campagnes par référentiel et période (plusieurs ouvertes), formules
[ID@P-1] et [ID@N-1], agrégation dans le temps (mois → année), exports et imports par période, migration des
campagnes annuelles."""
import datetime
import io
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from referentiel.composition import composer
from referentiel.models import KPI, Attribution, Niveau, Organisation, Referentiel, Utilisateur

from . import exports as E
from . import imports as I
from . import periodes as P
from . import saisie as S
from .calcul import Calculateur, recalculer
from .models import Alerte, Campagne, Periode, Reponse
from .outils_tests import xlsx
from .aides_tests.arbre_valeurs import Base as BaseArbre

D = Decimal
FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class CalendrierTests(TestCase):
    def test_libelles_et_lecture(self):
        self.assertEqual(P.libelle("annee", datetime.date(2026, 1, 1)), "2026")
        self.assertEqual(P.libelle("annee", datetime.date(2026, 4, 1), 4), "2026/27")
        self.assertEqual(P.libelle("trimestre", datetime.date(2026, 4, 1)), "T2 2026")
        self.assertEqual(P.libelle("trimestre", datetime.date(2026, 4, 1), 4, "en"), "Q1 2026/27")
        self.assertEqual(P.libelle("semestre", datetime.date(2026, 7, 1)), "S2 2026")
        self.assertEqual(P.libelle("mois", datetime.date(2026, 3, 1)), "mars 2026")
        self.assertEqual(P.libelle("mois", datetime.date(2026, 3, 1), langue="en"), "March 2026")
        lus = {t: P.lire(t) for t in ("2026", "mars 2026", "March 2026", "03/2026", "2026-03", "T2 2026", "Q2 2026", "S1 2026",
                                      "Exercice 2025", datetime.date(2026, 3, 15))}
        self.assertEqual(lus["2026"], ("annee", datetime.date(2026, 1, 1)))
        self.assertEqual(lus["Exercice 2025"], ("annee", datetime.date(2025, 1, 1)))
        for t in ("mars 2026", "March 2026", "03/2026", "2026-03", datetime.date(2026, 3, 15)):
            self.assertEqual(lus[t], ("mois", datetime.date(2026, 3, 1)), t)
        self.assertEqual(lus["T2 2026"], ("trimestre", datetime.date(2026, 4, 1)))
        self.assertEqual(lus["Q2 2026"], lus["T2 2026"])
        self.assertEqual(lus["S1 2026"], ("semestre", datetime.date(2026, 1, 1)))
        self.assertIsNone(P.lire("n'importe quoi"))

    def test_decalages_et_composition(self):
        mars = P.obtenir("mois", datetime.date(2026, 3, 1))
        fev = P.obtenir("mois", datetime.date(2026, 2, 1))
        mars25 = P.obtenir("mois", datetime.date(2025, 3, 1))
        annee = P.annuelle(2026)
        self.assertEqual((mars.fin, annee.fin), (datetime.date(2026, 3, 31), datetime.date(2026, 12, 31)))
        self.assertEqual(mars.traductions["en"]["libelle"], "March 2026")
        cal = P.Calendrier()
        self.assertEqual((cal.resoudre(mars, "P-1"), cal.resoudre(mars, "N-1"), cal.resoudre(mars, "2025")), (fev, mars25, mars25))
        self.assertIsNone(cal.resoudre(fev, "P-1"))  # janvier 2026 n'existe pas
        self.assertEqual(cal.libelle_cible(fev, "P-1"), "janvier 2026")
        self.assertEqual(len(cal.contenues(annee, "mois")), 12)
        self.assertEqual(cal.englobantes(mars), [annee])


class Base(TestCase):
    """« Reporting » annuel (EFF, ELEC) et « Énergie » mensuel (ELEC, ELEC_M, ELEC_A) : ELEC se saisit chaque mois,
    son année en découle."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)

        def kpi(code, type_saisie="Saisi", formule="", **autres):
            return KPI.objects.create(code=code, libelle=code, type_saisie_id=type_saisie, granularite_id=Niveau.ENTITY,
                                      methode_agregation="Formule" if formule else "Somme", formule=formule, **autres)
        self.eff, self.elec = kpi("EFF"), kpi("ELEC")
        self.mom = kpi("ELEC_M", "Calculé", "([ELEC] - [ELEC@P-1]) / [ELEC@P-1]", type_reponse_id="Pourcentage")
        self.yoy = kpi("ELEC_A", "Calculé", "([ELEC] - [ELEC@N-1]) / [ELEC@N-1]", type_reponse_id="Pourcentage")
        self.rse = Referentiel.objects.create(code="RSE", nom="Reporting", ordre=1)
        self.nrg = Referentiel.objects.create(code="NRG", nom="Énergie", ordre=2, frequence="mois", comparaison="P-1")
        composer({"EFF": ["Social"], "ELEC": ["Environnement"]}, self.rse)
        composer({"ELEC": ["Consommations"], "ELEC_M": ["Consommations"], "ELEC_A": ["Consommations"]}, self.nrg)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
        for k in (self.eff, self.elec):
            for o in (self.e1, self.e2):
                Attribution.objects.create(kpi=k, organisation=o, utilisateur=self.contrib)
        fin = timezone.localdate() + datetime.timedelta(days=30)
        self.annee, _ = P.campagne(self.rse, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=fin)
        self.mois = {}
        for an in (2025, 2026):
            for m in range(1, 13):
                statut = Campagne.Statut.OUVERTE if (an, m) == (2026, 3) else Campagne.Statut.CLOTUREE
                self.mois[(an, m)], _ = P.campagne(self.nrg, datetime.date(an, m, 1), statut=statut, date_fin_saisie=fin)
        self.client.force_login(self.admin)

    def saisir_mois(self, an, m, org, v):
        Reponse.objects.update_or_create(periode=self.mois[(an, m)].periode, kpi=self.elec, organisation=org,
                                         defaults={"valeur": D(v), "statut": Reponse.Statut.VALIDE, "origine": Reponse.Origine.IMPORT})


class CampagnesTests(Base):
    def test_deux_campagnes_ouvertes_et_perimetres(self):
        self.assertEqual({c.pk for c in S.campagnes_en_cours()}, {self.annee.pk, self.mois[(2026, 3)].pk})
        mars = self.mois[(2026, 3)]
        self.assertEqual(sorted({k.code for k, _ in S.cellules(self.admin, campagne=self.annee)}), ["EFF"])  # ELEC : cumul des mois
        self.assertEqual(sorted({k.code for k, _ in S.cellules(self.admin, campagne=mars)}), ["ELEC"])
        S.enregistrer(self.contrib, mars, self.elec, self.e1, "120", False, "")
        S.enregistrer(self.contrib, self.annee, self.eff, self.e1, "10", False, "")
        self.assertEqual(Reponse.objects.get(kpi=self.elec, organisation=self.e1, periode=mars.periode).valeur, D(120))
        self.assertFalse(S.droits(self.contrib, self.annee, self.elec, self.e1).modifier)  # année : lecture seule (cumul)
        # sélecteur de campagne : chaque page suit la campagne choisie
        rep = self.client.get(reverse("collecte:saisie") + f"?campagne={mars.pk}&org={self.e1.pk}")
        self.assertEqual(rep.context["campagne"], mars)
        self.assertContains(rep, '<select name="ref"')  # sélecteurs Référentiel puis Période
        self.assertContains(rep, ">Énergie</option>")
        self.assertContains(rep, "<span>Énergie · mars 2026</span>")  # titre : ouvre le panneau « Je réponds à »
        self.assertContains(rep, "février 2026")  # comparaison à la période précédente (réglage du référentiel)
        self.assertEqual(self.client.get(reverse("collecte:pour_moi")).context["campagne"], mars)  # mémorisée
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:pour_moi") + f"?campagne={self.annee.pk}")
        self.assertEqual([o["campagne"].pk for o in rep.context["onglets"]], [self.annee.pk, mars.pk])  # un onglet par campagne en cours
        tdb = self.client.get(reverse("collecte:tableau_de_bord")).context["avancement"]
        self.assertEqual({c.pk for c, _ in tdb}, {self.annee.pk, mars.pk})
        html = self.client.get(reverse("collecte:cellule", args=[mars.pk, "ELEC", self.e1.pk]), **FETCH).json()["html"]
        self.assertIn("mars 2026", html)

    def test_administration_des_campagnes(self):
        rep = self.client.get(reverse("collecte:admin_campagnes"))
        self.assertContains(rep, "Mensuelle")
        self.assertContains(rep, "mars 2026")
        html = self.client.get(reverse("collecte:admin_campagne_nouvelle") + "?referentiel=NRG", **FETCH).json()["html"]
        self.assertIn('data-frequence="mois"', html)
        res = self.client.post(reverse("collecte:admin_campagne_nouvelle"), {
            "referentiel": "NRG", "exercice": 2027, "toutes": "on", "seuil_historique": "2", "action": "enregistrer"}, **FETCH).json()
        self.assertTrue(res["ok"], res["html"])
        self.assertEqual(Campagne.objects.filter(referentiel=self.nrg, exercice=2027).count(), 12)
        res = self.client.post(reverse("collecte:admin_campagne_nouvelle"), {
            "referentiel": "NRG", "exercice": 2027, "rang": 5, "action": "enregistrer"}, **FETCH).json()
        self.assertIn("existe déjà", res["html"])
        # ouvrir une campagne mensuelle pendant que l'année est ouverte : permis
        avril = Campagne.objects.get(referentiel=self.nrg, periode__debut=datetime.date(2027, 4, 1))
        res = self.client.post(reverse("collecte:admin_campagne", args=[avril.pk]), {"action": "ouvrir"}, **FETCH).json()
        self.assertTrue(res["ok"], res["html"])
        self.assertEqual(len(S.campagnes_en_cours()), 3)
        # la fréquence d'un référentiel qui a des campagnes ne change plus
        donnees = {"action": "enregistrer"}
        for r in Referentiel.objects.all():
            donnees |= {f"nom__{r.code}": r.nom, f"couleur__{r.code}": r.couleur, f"actif__{r.code}": "on",
                        f"frequence__{r.code}": r.frequence, f"mois_debut__{r.code}": r.mois_debut, f"comparaison__{r.code}": r.comparaison}
        donnees["frequence__NRG"] = "trimestre"
        self.assertContains(self.client.post(reverse("parametres:referentiels"), donnees, follow=True), "a déjà des campagnes")
        donnees["frequence__NRG"] = "mois"
        donnees["comparaison__NRG"] = "N-1"
        self.client.post(reverse("parametres:referentiels"), donnees)
        self.assertEqual(Referentiel.objects.get(pk="NRG").comparaison, "N-1")


class CalculDansLeTempsTests(Base):
    def test_formules_p1_et_n1_sur_des_mois(self):
        self.saisir_mois(2026, 2, self.e1, 100)
        self.saisir_mois(2025, 3, self.e1, 80)
        self.saisir_mois(2026, 3, self.e1, 120)
        calc = Calculateur(self.mois[(2026, 3)])
        self.assertEqual(calc.valeur("ELEC_M", self.e1.id), D("0.2"))  # (120 - 100) / 100 : mois précédent
        self.assertEqual(calc.valeur("ELEC_A", self.e1.id), D("0.5"))  # (120 - 80) / 80 : même mois l'an dernier
        self.saisir_mois(2026, 1, self.e1, 90)
        calc = Calculateur(self.mois[(2026, 1)])
        self.assertIsNone(calc.valeur("ELEC_M", self.e1.id))  # décembre 2025 sans valeur
        self.assertIn("décembre 2025", calc.message("ELEC_M", self.e1.id))
        # une saisie de février recalcule l'évolution de mars (formule [ELEC@P-1])
        r = S.enregistrer(self.admin, self.mois[(2026, 3)], self.elec, self.e1, "150", False, "")
        self.assertEqual(Reponse.objects.get(kpi=self.mom, organisation=self.e1, periode=r.periode).valeur, D("0.5"))

    def test_agregation_mois_vers_annee(self):
        c25 = Campagne.objects.create(referentiel=self.rse, exercice=2025, statut=Campagne.Statut.CLOTUREE)
        for m in range(1, 13):
            self.saisir_mois(2025, m, self.e1, 10 * m)
            self.saisir_mois(2025, m, self.e2, 1)
        a = Calculateur(c25)
        self.assertEqual(a.valeur("ELEC", self.e1.id), D(780))  # somme des 12 mois
        self.assertEqual(a.valeur("ELEC", self.p.id), D(792))  # puis somme des entités
        self.elec.agregation_temps = "moyenne"
        self.elec.save()
        self.assertEqual(Calculateur(c25).valeur("ELEC", self.e1.id), D(65))
        self.elec.agregation_temps = "derniere"
        self.elec.save()
        self.assertEqual(Calculateur(c25).valeur("ELEC", self.e1.id), D(120))
        self.elec.agregation_temps = "somme"
        self.elec.save()
        recalculer(c25)
        r = Reponse.objects.get(kpi=self.elec, organisation=self.e1, periode=c25.periode)
        self.assertEqual((r.valeur, r.origine, r.statut), (D(780), Reponse.Origine.CUMUL, Reponse.Statut.CALCULE))
        # un mois manquant : année incomplète ; une valeur annuelle importée reste prioritaire
        Reponse.objects.filter(kpi=self.elec, organisation=self.e2, periode=self.mois[(2025, 6)].periode).delete()
        a = Calculateur(c25)
        self.assertIsNone(a.valeur("ELEC", self.e2.id))
        self.assertIn("juin 2025", a.message("ELEC", self.e2.id))
        Reponse.objects.update_or_create(periode=c25.periode, kpi=self.elec, organisation=self.e2,
                                         defaults={"valeur": D(11), "origine": Reponse.Origine.IMPORT, "statut": Reponse.Statut.VALIDE})
        self.assertEqual(Calculateur(c25).valeur("ELEC", self.e2.id), D(11))
        # « aucune » : l'année se saisit séparément
        self.elec.agregation_temps = "aucune"
        self.elec.save()
        self.assertIn(self.elec.code, {k.code for k, _ in S.cellules(self.admin, campagne=self.annee)})

    def test_saisie_d_un_mois_met_a_jour_l_annee_ouverte(self):
        for m in range(1, 13):
            if m != 3:
                self.saisir_mois(2026, m, self.e1, 10)
        S.enregistrer(self.admin, self.mois[(2026, 3)], self.elec, self.e1, "15", False, "")
        r = Reponse.objects.get(kpi=self.elec, organisation=self.e1, periode=self.annee.periode)
        self.assertEqual((r.valeur, r.origine), (D(125), Reponse.Origine.CUMUL))
        html = self.client.get(reverse("collecte:cellule", args=[self.annee.pk, "ELEC", self.e1.pk]), **FETCH).json()["html"]
        self.assertIn("Composantes dans le temps", html)
        self.assertIn("mars 2026", html)

    def test_comparaison_et_coherence_selon_le_referentiel(self):
        self.saisir_mois(2026, 2, self.e1, 100)
        self.saisir_mois(2025, 3, self.e1, 100)
        mars = self.mois[(2026, 3)]
        mars.seuil_ecart = D("0.2")
        mars.save()
        S.enregistrer(self.admin, mars, self.elec, self.e1, "150", False, "")
        a = Alerte.objects.get(campagne=mars, kpi=self.elec, organisation=self.e1, controle=Alerte.Controle.ECART_N1)
        self.assertIn("février 2026", a.message)  # comparé au mois précédent
        self.assertTrue(any("février 2026" in m for m in S.controles_validation(S.reponse_de(mars, self.elec, self.e1), mars)))


class EchangesTests(Base):
    def setUp(self):
        super().setUp()
        self.saisir_mois(2026, 2, self.e1, 100)
        Reponse.objects.create(periode=self.annee.periode, kpi=self.eff, organisation=self.e1, valeur=D(10), statut="valide")

    def test_export_par_periode(self):
        p = E.Parametres.depuis({"presentation": "base", "exercices": ["2026"], "contenus": ["valide", "brouillon"]})
        ws = load_workbook(io.BytesIO(E.exporter(self.admin, p).content))["Valeurs"]
        tete = [c.value for c in ws[1]]
        lignes = {(r[tete.index("ID KPI")], r[tete.index("Période")]) for r in ws.iter_rows(min_row=2, values_only=True)}
        self.assertEqual(lignes, {("EFF", "2026"), ("ELEC", "février 2026")})
        p = E.Parametres.depuis({"presentation": "base", "exercices": ["2026"], "periodes": ["mois"], "contenus": ["valide"]})
        ws = load_workbook(io.BytesIO(E.exporter(self.admin, p).content))["Valeurs"]
        self.assertEqual([r[tete.index("ID KPI")] for r in ws.iter_rows(min_row=2, values_only=True)], ["ELEC"])
        p = E.Parametres.depuis({"presentation": "tableau", "exercices": ["2026"], "contenus": ["valide"]})
        self.assertEqual(load_workbook(io.BytesIO(E.exporter(self.admin, p).content)).sheetnames, ["À lire", "2026", "février 2026"])

    def test_import_avec_colonne_periode(self):
        f = xlsx(onglet=None, lignes=[["ID KPI", "Organisation", "Période", "Valeur"],
                  ["ELEC", "E1", "mars 2026", 130], ["ELEC", "E2", "March 2026", 5], ["EFF", "E1", "2026", 12],
                  ["ELEC", "E1", "2026", 999], ["ELEC", "E1", "juin 2031", 1], ["ELEC", "E1", "bientôt", 1]])
        a = I.analyser(self.admin, f)
        resume = [(l.kpi_id, l.periode, l.action) for l in a.lignes]
        self.assertEqual(resume[:4], [("ELEC", "mars 2026", "creer"), ("ELEC", "mars 2026", "creer"), ("EFF", "2026", "modifier"),
                                      ("ELEC", "2026", "rejet")])
        self.assertIn("cumul de périodes plus courtes", a.lignes[3].motif)
        self.assertIn("Aucune campagne pour juin 2031", a.lignes[4].motif)
        self.assertIn("Période illisible", a.lignes[5].motif)
        f.seek(0)
        I.appliquer(self.admin, f, "fichier.xlsx")
        mars = self.mois[(2026, 3)].periode
        self.assertEqual(Reponse.objects.get(kpi=self.elec, organisation=self.e1, periode=mars).valeur, D(130))
        # modèle d'import d'une campagne mensuelle : colonne Période
        rep = self.client.get(reverse("collecte:echanges_modele") + f"?campagne={self.mois[(2026, 3)].pk}")
        ws = load_workbook(io.BytesIO(rep.content))["Saisie"]
        n = next(r for r in range(1, 15) if ws.cell(r, 2).value == "ID KPI")
        tete = [c.value for c in ws[n]]
        self.assertEqual({r[tete.index("Période")] for r in ws.iter_rows(min_row=n + 1, values_only=True) if r[1]}, {"mars 2026"})

    def test_classeur_de_configuration(self):
        from . import configuration as C

        wb = load_workbook(io.BytesIO(C.exporter().content))
        tete = [c.value for c in wb["Référentiels"][1]]
        self.assertIn("Fréquence", tete)
        ligne = next(r for r in wb["Référentiels"].iter_rows(min_row=2, values_only=True) if r[0] == "NRG")
        self.assertEqual((ligne[tete.index("Fréquence")], ligne[tete.index("Comparaison")]), ("Mensuelle", "Période précédente"))
        self.assertIn("Agrégation dans le temps", [c.value for c in wb["KPI"][1]])
        flux = io.BytesIO()
        wb.save(flux)
        a = C.analyser(SimpleUploadedFile("config.xlsx", flux.getvalue()))
        self.assertEqual({c.action for cs in a.onglets.values() for c in cs}, {"inchange"})


class MigrationTests(TransactionTestCase):
    """Bascule d'une base d'avant les périodes : une campagne par exercice devient la campagne annuelle du référentiel."""

    avant = [("collecte", "0012_themes_des_modeles_export"), ("referentiel", "0007_retrait_themes_kpi")]
    apres = [("collecte", "0015_periodes_fin"), ("referentiel", "0008_frequences")]

    def tearDown(self):
        # remettre toutes les migrations (les tests en transaction qui suivent ont besoin du schéma à jour)
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_campagnes_et_reponses_rattachees_a_une_periode(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.avant)
        apps = executor.loader.project_state(self.avant).apps
        Org, KPIx = apps.get_model("referentiel", "Organisation"), apps.get_model("referentiel", "KPI")
        Camp, Rep, Ref = apps.get_model("collecte", "Campagne"), apps.get_model("collecte", "Reponse"), apps.get_model("referentiel", "Referentiel")
        Ref.objects.create(code="RSE", nom="Reporting", ordre=1)
        # réglages créés par les migrations de données : absents si un test en transaction a vidé la base avant
        c6 = dict(couleur="#000000", couleur_fond="#FFFFFF", couleur_texte="#000000")
        apps.get_model("parametres", "NiveauHierarchique").objects.get_or_create(
            code=Niveau.ENTITY, defaults=dict(rang=2, nom="Entité", nom_pluriel="Entités", couleur_pale="#FFFFFF", **c6))
        apps.get_model("parametres", "TypeSaisie").objects.get_or_create(code="Saisi", defaults=dict(libelle="Saisie", abrege="S", **c6))
        apps.get_model("parametres", "TypeReponse").objects.get_or_create(code="Numérique", defaults=dict(libelle="Numérique", devise=""))
        o = Org.objects.create(nom="E1", niveau_id=Niveau.ENTITY)
        k = KPIx.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, type_reponse_id="Numérique")
        c25 = Camp.objects.create(exercice=2025, statut="cloturee", date_fin_exercice=datetime.date(2025, 12, 31))
        c26 = Camp.objects.create(exercice=2026, statut="ouverte", seuil_ecart=D("0.2"), date_fin_exercice=datetime.date(2026, 12, 31))
        Rep.objects.create(campagne=c25, kpi=k, organisation=o, valeur=D(90), statut="valide", origine="import")
        Rep.objects.create(campagne=c26, kpi=k, organisation=o, valeur=D(100), statut="brouillon")
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.apres)
        apps = executor.loader.project_state(self.apres).apps
        Camp, Rep = apps.get_model("collecte", "Campagne"), apps.get_model("collecte", "Reponse")
        camps = {c.exercice: c for c in Camp.objects.select_related("periode")}
        self.assertEqual({e: (c.referentiel_id, c.periode.type, c.periode.libelle, str(c.periode.debut), c.statut) for e, c in camps.items()},
                         {2025: ("RSE", "annee", "2025", "2025-01-01", "cloturee"), 2026: ("RSE", "annee", "2026", "2026-01-01", "ouverte")})
        self.assertEqual(camps[2026].seuil_ecart, D("0.2"))
        self.assertEqual(sorted((r.periode.libelle, r.valeur, r.statut) for r in Rep.objects.select_related("periode")),
                         [("2025", D(90), "valide"), ("2026", D(100), "brouillon")])
        self.assertEqual(apps.get_model("referentiel", "Referentiel").objects.get(pk="RSE").frequence, "annee")


class JeuTroisNiveauxMensuelTests(TestCase):
    def test_energie_mensuelle_et_annee_agregee(self):
        from .aides_tests import jeu_trois_niveaux as J

        J.charger()
        nrg = Referentiel.objects.get(pk="ENERGIE")
        self.assertEqual(nrg.frequence, "mois")
        mois_2025 = Campagne.objects.filter(referentiel=nrg, exercice=2025)
        self.assertEqual((mois_2025.count(), set(mois_2025.values_list("statut", flat=True))), (12, {Campagne.Statut.CLOTUREE}))
        self.assertEqual(Campagne.objects.filter(referentiel=nrg, statut=Campagne.Statut.OUVERTE).count(), 1)
        self.assertTrue(Campagne.objects.filter(referentiel_id="REPORTING", exercice=2026, statut=Campagne.Statut.OUVERTE).exists())
        lyon = Organisation.objects.get(nom="Lyon")
        mois = Reponse.objects.filter(kpi_id="ENR-01", organisation=lyon, periode__type="mois", periode__debut__year=2025)
        annee = Reponse.objects.get(kpi_id="ENR-01", organisation=lyon, periode__type="annee", periode__debut__year=2025)
        self.assertEqual(mois.count(), 12)
        self.assertEqual((annee.valeur, annee.origine), (sum(r.valeur for r in mois), Reponse.Origine.CUMUL))
        fe = Reponse.objects.get(kpi_id="FE-ELEC", organisation__nom="Essai Holding", periode__type="annee", periode__debut__year=2025)
        dec = Reponse.objects.get(kpi_id="FE-ELEC", organisation__nom="Essai Holding", periode__type="mois", periode__debut="2025-12-01")
        self.assertEqual(fe.valeur, dec.valeur)  # facteur d'émission : dernière valeur de l'année
        mars = Periode.objects.get(type="mois", debut="2026-03-01")
        self.assertIsNotNone(Reponse.objects.get(kpi_id="ENR-03", organisation=lyon, periode=mars).valeur)  # [ENR-01@P-1]


# ---------------------------------------------------------------- 1. [X@AAAA] et exercice décalé
class ExerciceDecaleTests(BaseArbre):
    """Exercice de juillet à juin : [A@2021] dans février 2023 (exercice 2022/23) lit février 2022 (exercice 2021/22),
    même rang dans l'exercice, comme [A@N-1] ; [A@2022] lit février 2023 lui-même (avant : février 2022, année civile)."""

    def setUp(self):
        super().setUp()
        self.mensuel = Referentiel.objects.create(code="FLUX", nom="Flux", ordre=1, frequence="mois", mois_debut=7)
        self.annuel = Referentiel.objects.create(code="ANNU", nom="Annuel", ordre=2, frequence="annee", mois_debut=7)
        self.kpi("A", agregation_temps=KPI.AgregationTemps.AUCUNE)
        self.kpi("X21", "Calculé", "[A@2021]", agregation_temps=KPI.AgregationTemps.AUCUNE)
        self.kpi("X22", "Calculé", "[A] - [A@2022]", agregation_temps=KPI.AgregationTemps.AUCUNE)
        composer({"A": ["Flux"], "X21": ["Flux"], "X22": ["Flux"]}, self.mensuel)
        composer({"A": ["Flux"], "X21": ["Flux"], "X22": ["Flux"]}, self.annuel)
        ouv = Campagne.Statut.OUVERTE
        self.f22 = P.campagne(self.mensuel, datetime.date(2022, 2, 1), statut=ouv)[0].periode  # exercice 2021/22
        self.f23 = P.campagne(self.mensuel, datetime.date(2023, 2, 1), statut=ouv)[0].periode  # exercice 2022/23
        self.a21 = P.campagne(self.annuel, datetime.date(2021, 7, 1), statut=ouv)[0].periode  # 2021/22
        self.a22 = P.campagne(self.annuel, datetime.date(2022, 7, 1), statut=ouv)[0].periode  # 2022/23

    def test_calendrier(self):
        cal = P.Calendrier()
        self.assertEqual((cal.mois_debut(self.f23), cal.exercice(self.f23)), (7, 2022))
        self.assertEqual(cal.resoudre(self.f23, "2021"), self.f22)
        self.assertEqual(cal.resoudre(self.f23, "2022"), self.f23)  # son propre exercice
        self.assertEqual(cal.resoudre(self.f23, "N-1"), self.f22)  # même règle que [A@N-1]
        self.assertEqual(cal.resoudre(self.a22, "2021"), self.a21)  # année : inchangé
        self.assertEqual(cal.resoudre(self.a22, "2022"), self.a22)
        self.assertEqual(cal.libelle_cible(self.a22, "2019"), "2019/20")  # période absente : libellé de l'exercice

    def test_janvier_inchange(self):
        cal_ref = Referentiel.objects.create(code="CIV", nom="Civil", ordre=3, frequence="trimestre", mois_debut=1)
        t = P.campagne(cal_ref, datetime.date(2023, 4, 1), statut=Campagne.Statut.OUVERTE)[0].periode
        t22 = P.obtenir("trimestre", datetime.date(2022, 4, 1))
        cal = P.Calendrier()
        self.assertEqual((cal.exercice(t), cal.resoudre(t, "2022")), (2023, t22))

    def test_calcul_et_propagation(self):
        self.mettre("A", self.e1, self.f22, 10)
        self.mettre("A", self.e1, self.f23, 25)
        recalculer(self.f23)
        self.assertEqual(self.lire("X21", self.e1, self.f23).valeur, D(10))  # février 2022
        self.assertEqual(self.lire("X22", self.e1, self.f23).valeur, D(0))  # février 2023 lui-même
        # une saisie de février 2022 refait la formule de février 2023 qui le cite par [A@2021]
        a = Reponse.objects.get(periode=self.f22, kpi_id="A", organisation=self.e1)
        a.valeur = D(12)
        a.save()
        self.assertEqual(self.lire("X21", self.e1, self.f23).valeur, D(12))
        # une saisie de février 2023 refait [A] - [A@2022] (l'exercice de la période elle-même)
        b = Reponse.objects.get(periode=self.f23, kpi_id="A", organisation=self.e1)
        b.valeur = D(30)
        b.save()
        self.assertEqual(self.lire("X22", self.e1, self.f23).valeur, D(0))

    def test_message_periode_absente(self):
        KPI.objects.filter(code="X21").update(formule="[A@2019]")
        KPI.objects.get(code="X21").save()
        self.mettre("A", self.e1, self.f23, 1)
        calc = Calculateur(self.f23)
        self.assertIsNone(calc.valeur("X21", self.e1.id))
        self.assertIn("février 2020", calc.message("X21", self.e1.id))  # même rang de l'exercice 2019/20
