"""Écriture rapide des lignes d'un onglet en écriture seule (``fichiers.LignesRapides``) : le fichier produit est le même,
au caractère près, que celui qu'écrit openpyxl cellule par cellule (``ws.append(ligne_flux(...))``)."""
import datetime
import io
import zipfile
from decimal import Decimal

from django.test import SimpleTestCase
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import IllegalCharacterError

from . import fichiers as X

PARIS = timezone.get_fixed_timezone(60)
LIGNES = [
    (["Texte simple", "Élément « accentué » – €", "A & B < C > D", "  espaces autour ", "ligne 1\nligne 2\r\nfin", "\ttab",
      "=SOMME(A1)", "+33 1 23", "-5", "@x", "=", "#N/A", "#DIV/0!", "", None, "😀 émoji", 'guillemets "x" \'y\'', "x" * 40000],
     None),
    ([2021, 0, -3, 1.5, 1e-20, 123456789.123456789, Decimal("2788.4000"), Decimal("1E+3"), Decimal("0.1234567890123456789"),
      True, False, float("nan"), None, ""], {0: "0", 3: "#,##0.00", 6: '#,##0.0" %"', 12: "DD/MM/YYYY", 13: "#,##0"}),
    ([datetime.date(2026, 1, 1), datetime.datetime(2026, 3, 5, 14, 30, 15), datetime.datetime(2026, 3, 5, 14, 30, tzinfo=PARIS),
      datetime.time(8, 15), datetime.timedelta(hours=36), datetime.date(2026, 2, 1), None, datetime.date(2025, 12, 31)],
     {0: X.FORMAT_DATE, 1: "DD/MM/YYYY HH:MM", 2: "DD/MM/YYYY HH:MM", 6: "DD/MM/YYYY HH:MM", 7: "#,##0"}),
    ([None, None, "seule à la fin"], {0: "General"}),
    ([], None),
]


def _classeur(rapide, lignes=LIGNES):
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Données")
    ws.freeze_panes = "B2"
    tete = X.entetes_flux(ws, ["Un", "Deux", "Trois"], ["cle", "remplir", "info"])
    X.bulle(tete[1], "Bulle", hauteur=60)
    ws.append(tete)
    if rapide:
        flux = X.LignesRapides(ws, 2)
        for valeurs, formats in lignes:
            flux.ecrire(valeurs, formats)
        n = flux.nb
    else:
        for valeurs, formats in lignes:
            ws.append(X.ligne_flux(ws, valeurs, formats))
        n = len(lignes)
    X.table(ws, "Essai", 3, n, entetes=["Un", "Deux", "Trois"])
    wb.create_sheet("Suite").append(["après"])
    sortie = io.BytesIO()
    wb.save(sortie)
    return sortie.getvalue()


class LignesRapidesTests(SimpleTestCase):
    def test_meme_fichier_que_openpyxl(self):
        a, b = zipfile.ZipFile(io.BytesIO(_classeur(False))), zipfile.ZipFile(io.BytesIO(_classeur(True)))
        self.assertEqual(a.namelist(), b.namelist())
        for partie in a.namelist():
            if partie != "docProps/core.xml":  # date de création
                self.assertEqual(a.read(partie), b.read(partie), partie)

    def test_relecture(self):
        ws = load_workbook(io.BytesIO(_classeur(True)))["Données"]
        self.assertEqual(ws["A2"].value, "Texte simple")
        self.assertEqual(ws["G2"].value, "=SOMME(A1)")  # du texte, jamais une formule
        self.assertEqual(ws["G2"].data_type, "s")
        self.assertEqual(ws["D3"].number_format, "#,##0.00")
        self.assertEqual(ws["C4"].value, datetime.datetime(2026, 3, 5, 14, 30))  # heure de Paris
        self.assertEqual(ws["C5"].value, "seule à la fin")
        self.assertEqual(ws.tables["Essai"].ref, "A1:C6")

    def test_caractere_de_controle_retire_comme_openpyxl(self):
        """Un caractère de contrôle (venu d'un CSV importé, d'un copier-coller) faisait échouer tout l'export (erreur
        500) : il est retiré, de la même façon par les deux écritures ; tabulation et retours à la ligne restent."""
        lignes = [(["a\x01b", "\x00début", "fin\x1f", "tab\tligne\nok", "=\x02x"], {1: "@"}), (["x" * 32767 + "\x07"], None)]
        a, b = zipfile.ZipFile(io.BytesIO(_classeur(False, lignes))), zipfile.ZipFile(io.BytesIO(_classeur(True, lignes)))
        for partie in a.namelist():
            if partie != "docProps/core.xml":
                self.assertEqual(a.read(partie), b.read(partie), partie)
        ws = load_workbook(io.BytesIO(_classeur(True, lignes)))["Données"]
        self.assertEqual([c.value for c in ws[2]], ["ab", "début", "fin", "tab\tligne\nok", "=x"])
        self.assertEqual(ws["A3"].value, "x" * 32767)
        with self.assertRaises(IllegalCharacterError):  # openpyxl seul les refuse toujours : d'où le nettoyage
            Workbook().active.append(["a\x01b"])
