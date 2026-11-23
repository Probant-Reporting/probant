"""Tableau lisible en formules Excel (option « Valeurs calculées : en formules Excel ») : formules fidèles au moteur,
valeurs avec une bulle quand une formule ne redonnerait pas le chiffre de l'outil, recalcul hors de l'outil (LibreOffice,
s'il est installé), option du constructeur d'export. Données inventées."""
import datetime
import io
import os
import shutil
import subprocess
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from parametres.referentiel import unite_depuis_symbole as U
from referentiel.models import KPI, Niveau, Organisation, Utilisateur

from . import exports as E
from . import formules_excel as FX
from .calcul import recalculer
from .models import Campagne, ReglageExport, Reponse

D = Decimal


def classeur(reponse, data_only=False):
    return load_workbook(io.BytesIO(reponse.content), data_only=data_only)


class Grille:
    """Onglet du tableau lisible lu par KPI et organisation."""

    def __init__(self, ws):
        self.ws = ws
        self.tete = next(r for r in range(1, 20) if ws.cell(r, 1).value == "ID KPI")
        self.cols = {ws.cell(self.tete, c).value: c for c in range(4, ws.max_column + 1)}
        self.rangs = {ws.cell(r, 1).value: r for r in range(self.tete + 1, ws.max_row + 1)}

    def case(self, kpi, org):
        return self.ws.cell(self.rangs[kpi], self.cols[org])

    def ref(self, kpi, org):
        return self.case(kpi, org).coordinate


class Donnees(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        # fermée mi-2025 : compte en 2025, pas en 2026 (même si une valeur 2026 traîne en base)
        self.e3 = Organisation.objects.create(nom="E3", niveau_id=Niveau.ENTITY, parent=self.p, actif=False,
                                              date_desactivation=datetime.date(2025, 6, 30))
        self.s1 = Organisation.objects.create(nom="S1", niveau_id=Niveau.SITE, parent=self.e1)
        self.c0 = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.CLOTUREE)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE,
                                         date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        k = lambda code, **kw: KPI.objects.create(code=code, libelle=code, granularite_id=kw.pop("g", Niveau.ENTITY), **kw)  # noqa: E731
        k("EFF", type_saisie_id="Saisi", methode_agregation="Somme", unite=U("ETP"), decimales=0)
        k("FEM", type_saisie_id="Saisi", methode_agregation="Somme", unite=U("ETP"), decimales=0)
        k("TXF", type_saisie_id="Calculé", formule="[FEM] / [EFF]", methode_agregation="Formule", type_reponse_id="Pourcentage",
          unite=U("%"), decimales=1)
        k("ACC", type_saisie_id="Saisi", methode_agregation="Somme")
        k("HRS", type_saisie_id="Saisi", methode_agregation="Somme")
        k("TF", type_saisie_id="Calculé", formule="[ACC] / [HRS] * 1000000", methode_agregation="Formule", decimales=2)
        k("DBL", type_saisie_id="Calculé", formule="[EFF] * 2", methode_agregation="Somme")
        k("EVO", type_saisie_id="Calculé", formule="[EFF] - [EFF@N-1]", methode_agregation="Aucune")
        k("OPT", type_saisie_id="Saisi", methode_agregation="Somme")
        k("NAZ", type_saisie_id="Calculé", formule="[EFF] + [OPT]", methode_agregation="Aucune", na_compte_zero=True)
        k("CONSO", type_saisie_id="Saisi", methode_agregation="Somme", g=Niveau.SITE, unite=U("L"))
        k("FE", type_saisie_id="FE", unite=U("kgCO2eq/L"), decimales=3)
        k("CO2", type_saisie_id="Calculé", formule="[CONSO] * [FE]", methode_agregation="Somme", g=Niveau.SITE)
        valeurs = {  # (KPI, organisation): valeur 2026 ; None : N/A
            ("EFF", self.e1): 110, ("EFF", self.e2): 40, ("FEM", self.e1): 55, ("FEM", self.e2): 10,
            ("ACC", self.e1): 3, ("HRS", self.e1): 200000, ("ACC", self.e2): 0, ("HRS", self.e2): 0,
            ("OPT", self.e1): 5, ("OPT", self.e2): None, ("CONSO", self.s1): D("1200.5"), ("FE", self.e1): D("2.681"),
            ("EFF", self.e3): 7,
        }
        for (code, org), v in valeurs.items():
            Reponse.objects.create(periode=self.c.periode, kpi_id=code, organisation=org, valeur=None if v is None else D(v),
                                   non_applicable=v is None, statut="valide", origine="saisie")
        for org, v in ((self.e1, 100), (self.e2, 45), (self.e3, 6)):
            Reponse.objects.create(periode=self.c0.periode, kpi_id="EFF", organisation=org, valeur=D(v), statut="valide",
                                   origine="saisie")
        recalculer(self.c0)
        recalculer(self.c)
        # valeur forcée (avec accord) : remplace le calcul de DBL pour E2
        r = Reponse.objects.get(periode=self.c.periode, kpi_id="DBL", organisation=self.e2)
        r.valeur, r.origine = D(85), Reponse.Origine.FORCEE
        r.save()
        recalculer(self.c)

    def exporter(self, valeurs="formules", **reglages):
        p = E.Parametres.depuis({"presentation": "tableau", "exercices": ["2026"], "valeurs": valeurs, **reglages})
        return E.exporter(self.admin, p)


class FormulesTests(Donnees):
    def test_formules_fideles_au_moteur(self):
        ws = classeur(self.exporter())["2026"]
        t = Grille(ws)
        r = t.ref
        # KPI calculé : sa formule, en cases de la même colonne ; division : 0 / 0 = 0, autre division par zéro = erreur
        txf = t.case("TXF", "E1")
        self.assertEqual(txf.value, f"=IF(AND({r('FEM', 'E1')}=0,{r('EFF', 'E1')}=0),0,{r('FEM', 'E1')}/{r('EFF', 'E1')})")
        self.assertEqual(txf.number_format, "#,##0.0%")  # pourcentage en fraction, format % d'Excel
        self.assertEqual(t.case("FEM", "E1").value, 55)  # source : la valeur saisie
        self.assertEqual(t.case("TF", "E2").value,
                         f"=IF(AND({r('ACC', 'E2')}=0,{r('HRS', 'E2')}=0),0,{r('ACC', 'E2')}/{r('HRS', 'E2')})*1000000")
        # agrégation « Formule » : la formule sur les totaux de la même colonne
        self.assertIn(r("FEM", "Groupe"), t.case("TXF", "Groupe").value)
        # total : SUM des organisations enfants ouvertes pendant la période (E3, fermée en 2025, n'y est pas)
        self.assertEqual(t.case("EFF", "Pays").value, f"=SUM({r('EFF', 'E1')},{r('EFF', 'E2')})")
        self.assertEqual(t.case("EFF", "Groupe").value, f"=SUM({r('EFF', 'Pays')})")
        self.assertEqual(t.case("DBL", "Pays").value, f"=SUM({r('DBL', 'E1')},{r('DBL', 'E2')})")
        # facteur d'émission hérité : la case de l'organisation qui le porte
        self.assertEqual(t.case("CO2", "S1").value, f"={r('CONSO', 'S1')}*{r('FE', 'E1')}")
        self.assertEqual(t.case("CO2", "E1").value, f"=SUM({r('CO2', 'S1')})")
        # source N/A comptée comme 0 (fiche KPI) : N(case) ; la case N/A reste du texte
        self.assertEqual(t.case("NAZ", "E2").value, f"={r('EFF', 'E2')}+N({r('OPT', 'E2')})")
        self.assertEqual(t.case("OPT", "E2").value, "N/A")
        self.assertEqual(t.case("OPT", "Pays").value, f"=SUM({r('OPT', 'E1')},{r('OPT', 'E2')})")  # SUM ignore N/A

    def test_valeurs_avec_une_bulle_qui_dit_pourquoi(self):
        wb = classeur(self.exporter())
        t = Grille(wb["2026"])
        forcee = t.case("DBL", "E2")
        self.assertEqual(forcee.value, 85)
        self.assertIn("valeur forcée", forcee.comment.text)
        evo = t.case("EVO", "E1")
        self.assertEqual(evo.value, 10)  # 110 - 100 : [EFF@N-1] cite une autre période
        self.assertIn("autre période", evo.comment.text)
        lire = "\n".join(str(c.value) for row in wb["À lire"].iter_rows() for c in row if c.value)
        self.assertIn("Formules Excel", lire)
        self.assertIn("IF(AND(a=0,b=0),0,a/b)", lire)
        self.assertIn("valeur forcée : 1", lire)
        self.assertIn("En fraction, au format pourcentage d'Excel", lire)

    def test_source_absente_puis_ajoutee(self):
        t = Grille(classeur(self.exporter(kpis=["TXF"], choix_kpi="choix"))["2026"])
        self.assertEqual(set(t.rangs) & {"TXF", "FEM", "EFF"}, {"TXF"})
        case = t.case("TXF", "E1")
        self.assertEqual(case.value, 0.5)
        self.assertIn("pas dans l'export", case.comment.text)
        t = Grille(classeur(self.exporter(kpis=["TXF"], choix_kpi="choix", sources="on"))["2026"])
        self.assertTrue({"TXF", "FEM", "EFF"} <= set(t.rangs))
        self.assertTrue(t.case("TXF", "E1").value.startswith("=IF(AND("))

    def test_chiffres_par_defaut_et_formats_concernes(self):
        p = E.Parametres()
        self.assertEqual(p.valeurs, "chiffres")
        self.assertFalse(E.Parametres.depuis({"presentation": "base", "valeurs": "formules"}).formules())
        self.assertFalse(E.Parametres.depuis({"presentation": "tableau", "format": "csv", "valeurs": "formules"}).formules())
        self.assertTrue(E.Parametres.depuis({"presentation": "tableau", "valeurs": "formules"}).formules())
        self.assertEqual(E.Parametres.depuis({"valeurs": "autre"}).valeurs, "chiffres")
        ws = classeur(self.exporter("chiffres"))["2026"]
        self.assertFalse([c for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=")])
        t = Grille(ws)
        self.assertEqual((t.case("TXF", "E1").value, t.case("TXF", "E1").number_format), (50, '#,##0.0" %"'))
        # base de données : jamais de formule (Power BI lit les valeurs enregistrées dans le fichier)
        base = E.exporter(self.admin, E.Parametres.depuis({"presentation": "base", "exercices": ["2026"], "valeurs": "formules"}))
        ws = classeur(base)["Valeurs"]
        self.assertFalse([c for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=")])

    def test_evaluation_comme_excel(self):
        self.assertEqual(FX._diviser(0.0, 0.0, zero=True), 0.0)
        self.assertEqual(FX._diviser(1.0, 0.0, zero=True), "#DIV/0!")
        self.assertEqual(FX._diviser("N/A", 2.0, zero=True), "#VALUE!")
        self.assertEqual(FX._diviser(None, None, zero=True), 0.0)  # case vide = 0 dans Excel
        self.assertTrue(FX.egal(0.1 + 0.2, D("0.3")))
        self.assertFalse(FX.egal(0.31, D("0.3")))
        self.assertFalse(FX.egal("#DIV/0!", D("0")))
        self.assertEqual(FX._par("A1+B1", 1, 2, False), "(A1+B1)")
        self.assertEqual(FX._par("A1-B1", 1, 1, True), "(A1-B1)")  # a-(b-c) garde ses parenthèses
        self.assertEqual(FX._par("-A1", 3, 1, False), "(-A1)")

    def test_jamais_une_formule_fausse(self):
        """Un chiffre enregistré que les cases de l'onglet ne redonnent pas (période clôturée, réglages changés) : valeur."""
        Reponse.objects.filter(periode=self.c.periode, kpi_id="EFF", organisation=self.p).update(valeur=D(999))
        t = Grille(classeur(self.exporter())["2026"])
        self.assertEqual(t.case("EFF", "Pays").value, 999)
        self.assertIn("ne redonne pas", t.case("EFF", "Pays").comment.text)
        # le total du dessus (150) ne vaut pas la somme des cases (999) : chiffre aussi, jamais une formule fausse
        self.assertEqual(t.case("EFF", "Groupe").value, 150)
        self.assertIn("ne redonne pas", t.case("EFF", "Groupe").comment.text)
        self.assertEqual(t.case("EFF", "E1").value, 110)

    def test_constructeur_et_export_enregistre(self):
        self.client.force_login(self.admin)
        url = reverse("collecte:echanges_exporter")
        page = self.client.get(url + "?nouveau=1").content.decode()
        self.assertIn('name="valeurs" value="formules"', page)
        self.assertIn("En formules Excel", page)
        self.assertIn('aria-describedby="aide-valeurs-calculees"', page)
        self.client.post(url, {"action": "copier", "nom": "Audit", "presentation": "tableau", "format": "xlsx",
                               "exercices": ["2026"], "valeurs": "formules", "sources": "on", "niveaux": E.N.codes(),
                               "contenus": ["valide", "brouillon", "calcule"], "types": list(E.CODES_COMPORTEMENTS)})
        m = ReglageExport.objects.get(nom="Audit")
        self.assertEqual((m.parametres["valeurs"], m.parametres["sources"]), ("formules", True))
        self.assertIn("formules Excel", E.Parametres.depuis(m.parametres).phrase())
        rep = self.client.get(url + f"?modele={m.pk}&telecharger=1")
        t = Grille(classeur(rep)["2026"])
        self.assertTrue(t.case("DBL", "Pays").value.startswith("=SUM("))
        # un export enregistré avant l'option reste en chiffres
        ancien = ReglageExport.objects.create(nom="Ancien", parametres={"presentation": "tableau", "exercices": ["2026"]})
        self.assertEqual(E.Parametres.depuis(ancien.parametres).valeurs, "chiffres")


def _soffice():
    return shutil.which("soffice") or shutil.which("libreoffice")


class RecalculTests(Donnees):
    """Formules recalculées hors de l'outil (LibreOffice en ligne de commande) : mêmes chiffres que l'outil."""

    def test_recalcul_libreoffice(self):
        soffice = _soffice()
        if not soffice:
            self.skipTest("LibreOffice absent")
        chiffres = classeur(self.exporter("chiffres"), data_only=True)["2026"]
        with tempfile.TemporaryDirectory() as dossier:
            source = os.path.join(dossier, "formules.xlsx")
            with open(source, "wb") as f:
                f.write(self.exporter().content)
            sortie = os.path.join(dossier, "recalcul")
            profil = "file://" + os.path.join(dossier, "profil")  # profil à part : plusieurs tests en parallèle
            subprocess.run([soffice, f"-env:UserInstallation={profil}", "--headless", "--calc", "--convert-to", "xlsx",
                            "--outdir", sortie, source], check=True, capture_output=True, timeout=180)
            formules = load_workbook(source)["2026"]
            recalcule = load_workbook(os.path.join(sortie, "formules.xlsx"), data_only=True)["2026"]
        n = 0
        for row in formules.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    n += 1
                    attendu = chiffres.cell(c.row, c.column)
                    v = attendu.value / 100 if attendu.number_format.endswith('" %"') else attendu.value
                    self.assertAlmostEqual(recalcule.cell(c.row, c.column).value, v, places=9, msg=f"{c.coordinate} {c.value}")
        self.assertGreater(n, 15)
