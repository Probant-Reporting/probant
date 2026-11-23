"""Export Excel d'une vue de la Visualisation (``visuels_excel.onglet_donnees``), cellule par cellule, pour chaque type de
visuel : une valeur est un nombre, avec son format de nombre Excel (unité et pourcentage dans le format, pas dans le
texte) ; l'écart aussi, son sens (▲ ▼ =) porté par le format. Avant : « 61,6 % », « ▼ −21,9 % »,
« 5 596,0 h » ou « 3 226 249 kWh » arrivaient en texte dans les colonnes de comparaison, d'écart et de total.

Données inventées uniquement."""
import io
import re
from decimal import Decimal

from openpyxl import load_workbook

from . import saisie as S
from . import visuels_excel as VX
from .aides_tests.visuels import AvecKpis
from .models import Reponse

D = Decimal
CHIFFRE = re.compile(r"\d")


class OngletDonneesTests(AvecKpis):
    def setUp(self):
        super().setUp()
        Reponse.objects.create(periode=self.c0.periode, kpi=self.taux, organisation=self.e1, valeur=D("0.616"),
                               statut="valide", origine="import")
        Reponse.objects.create(periode=self.c0.periode, kpi=self.taux, organisation=self.e2, valeur=D("0.5"),
                               statut="valide", origine="import")
        S.enregistrer(self.admin, self.c, self.taux, self.e2, "48,1", False, "")
        for o, v, r in ((self.e1, 6, "Oui"), (self.e2, 7, "Oui")):
            S.enregistrer(self.admin, self.c, self.eff2, o, str(v), False, "")
            Reponse.objects.create(periode=self.c.periode, kpi=self.oui, organisation=o, texte=r, statut="valide",
                                   origine="import")
        from . import calcul as C

        C.recalculer(self.c0)
        C.recalculer(self.c)

    def classeur(self, *visuels, org=None):
        d = self.donnees(self.admin, *visuels, filtres={"valeurs": "brouillons", "org": (org or self.g).pk,
                                                         "periode": self.c.periode.pk})
        flux = io.BytesIO()
        VX.classeur("Essai", d).save(flux)
        return load_workbook(io.BytesIO(flux.getvalue())), d

    def verifier_cellules(self, wb, nom):
        """Aucune colonne de valeur (ni la première, libellés, ni la dernière, « État ») ne contient de texte avec un
        chiffre : chaque valeur, comparaison, écart, part ou total chiffré est un nombre."""
        donnees = [ws for ws in wb.worksheets[1:]]
        self.assertTrue(donnees, nom)
        for ws in donnees:
            for row in ws.iter_rows(min_row=2, min_col=2, max_col=max(ws.max_column - 1, 2)):
                for c in row:
                    with self.subTest(visuel=nom, onglet=ws.title, cellule=c.coordinate):
                        if isinstance(c.value, str):
                            self.assertIsNone(CHIFFRE.search(c.value), c.value)

    def test_chaque_type_de_visuel(self):
        visuels = {
            "chiffre %": {"type": "chiffre", "kpis": ["TX"]},
            "chiffre unité": {"type": "chiffre", "kpis": ["EFF"]},
            "barres périodes": {"type": "barres", "kpis": ["EFF"], "axe": "periodes"},
            "barres KPI": {"type": "barres", "kpis": ["EFF", "EFF2"]},
            "barres organisations": {"type": "barres", "kpis": ["TX"], "axe": "organisations"},
            "barres empilées organisations": {"type": "barres_empilees", "kpis": ["EFF"]},
            "barres empilées oui / non": {"type": "barres_empilees", "kpis": ["OUI"], "axe": "organisations"},
            "barres empilées deux KPI": {"type": "barres_empilees", "kpis": ["EFF", "EFF2"]},
            "courbe": {"type": "courbe", "kpis": ["TX"]},
            "anneau": {"type": "anneau", "kpis": ["EFF"]},
            "anneau oui / non": {"type": "anneau", "kpis": ["OUI"]},
            "tableau": {"type": "tableau", "kpis": ["EFF", "TX", "EFF2"]},
            "tableau organisations": {"type": "tableau", "kpis": ["EFF", "TX"], "options": {"colonnes": "organisations"}},
            "organisations": {"type": "organisations", "kpis": ["TX"]},
            "comparaison N-1 valeurs": {"type": "comparaison_n1", "kpis": ["EFF", "EFF2"]},
            "comparaison N-1 écarts": {"type": "comparaison_n1", "kpis": ["EFF", "TX"]},
            "remplissage": {"type": "remplissage", "kpis": []},
        }
        for nom, v in visuels.items():
            wb, d = self.classeur(v, org=self.e2 if v["type"] == "chiffre" else None)
            self.assertNotEqual(d["visuels"]["v1"].get("etat"), "erreur", nom)
            self.verifier_cellules(wb, nom)

    def test_formats_unite_pourcentage_et_ecart(self):
        wb, d = self.classeur({"type": "chiffre", "kpis": ["TX"]}, org=self.e2)
        ws = wb.worksheets[1]
        entetes = [c.value for c in ws[1]]
        ligne = [c for c in ws[2]]
        valeur, comparaison, ecart = (ligne[entetes.index(x)] for x in ("2026", "2025", d["visuels"]["v1"]["tableau"]["entetes"][3]))
        for c in (valeur, comparaison):
            self.assertIsInstance(c.value, (int, float))
            self.assertIn("%", c.number_format)
        self.assertIsInstance(ecart.value, (int, float))
        self.assertIn("▲", ecart.number_format)
        self.assertIn("▼", ecart.number_format)
        self.assertLess(ecart.value, 0)  # baisse : le nombre est négatif, le format l'écrit « ▼ »
        wb, _ = self.classeur({"type": "chiffre", "kpis": ["EFF"]})
        ws = wb.worksheets[1]
        self.assertIn('ETP"', ws.cell(2, 2).number_format)
        self.assertIn('ETP"', ws.cell(2, 3).number_format)

    def test_total_des_barres_empilees_nombre_avec_unite(self):
        wb, _ = self.classeur({"type": "barres_empilees", "kpis": ["EFF", "EFF2"]})
        ws = wb.worksheets[1]
        total = [c.value for c in ws[1]].index("Total") + 1
        cellules = [ws.cell(r, total) for r in range(2, ws.max_row + 1) if ws.cell(r, total).value is not None]
        self.assertTrue(cellules)
        for c in cellules:
            self.assertIsInstance(c.value, (int, float))
            self.assertIn('ETP"', c.number_format)
