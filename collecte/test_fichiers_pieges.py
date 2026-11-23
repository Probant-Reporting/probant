"""Classeurs Excel piégés refusés AVANT d'être ouverts (collecte.fichiers.controler_classeur) : taille décompressée
démesurée, entrée au taux de compression aberrant, texte de cellule plus long que la limite d'Excel. Tous les imports
Excel passent par ``fichiers.lire`` (valeurs, configuration, traductions, reprise, référentiels) ou, pour les commandes,
par ``referentiel.echange.ouvrir_classeur``. Un vrai classeur de bonne taille passe toujours."""
import io
import zipfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook

from referentiel import echange as RE

from . import fichiers as X

GRAND_CLASSEUR = Path(settings.BASE_DIR) / "referentiel" / "bibliotheque" / "formats" / "vs_digital_template_2.0.0.xlsx"


def classeur(texte="bonjour"):
    wb = Workbook()
    wb.active["A1"] = texte
    f = io.BytesIO()
    wb.save(f)
    return f.getvalue()


def remplacer_entree(octets, nom, contenu):
    """Copie du classeur avec l'entrée ``nom`` remplacée (compressée au mieux)."""
    sortie = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(octets)) as zin, zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
        for i in zin.infolist():
            zout.writestr(i.filename, contenu if i.filename == nom else zin.read(i.filename))
    return sortie.getvalue()


def feuille(*textes):
    """Classeur valide dont la feuille contient ces textes (A1, A2…), écrits à la main : openpyxl ne les écrirait pas
    au-delà de la limite d'Excel."""
    lignes = b"".join(b'<row r="%d"><c r="A%d" t="inlineStr"><is><t>%s</t></is></c></row>' % (n, n, t.encode())
                      for n, t in enumerate(textes, 1))
    xml = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
           + lignes + b"</sheetData></worksheet>")
    return remplacer_entree(classeur(), "xl/worksheets/sheet1.xml", xml)


def piege(n=40_000_000):
    """Cellule de n caractères : petit sur disque (~40 Ko pour 40 millions), énorme une fois ouvert."""
    return feuille("A" * n)


def depose(octets, nom="valeurs.xlsx"):
    return SimpleUploadedFile(nom, octets)


class ClasseursPiegesTests(SimpleTestCase):
    def test_bombe_refusee_sans_etre_ouverte(self):
        octets = piege()
        self.assertLess(len(octets), 200_000)  # petit sur disque
        with mock.patch.object(X, "load_workbook") as ouvrir, \
                self.assertRaisesMessage(X.FichierInvalide, "ne peut pas lire"):  # taux aberrant (≈ 1 000)
            X.lire(depose(octets))
        ouvrir.assert_not_called()

    def test_taille_decompressee_au_dela_du_plafond(self):
        octets = classeur()
        with mock.patch.object(X, "DECOMPRESSE_MAX", 1000), mock.patch.object(X, "load_workbook") as ouvrir, \
                self.assertRaisesMessage(X.FichierInvalide, "trop volumineux une fois ouvert"):
            X.lire(depose(octets))
        ouvrir.assert_not_called()

    def test_texte_trop_long_au_taux_normal(self):
        """Texte de 300 000 caractères variés (taux de compression ordinaire) : refusé avant l'ouverture."""
        import random

        aleatoire = random.Random(1)
        long_ = "".join(aleatoire.choice("abcdefghijklmnopqrstuvwxyz ") for _ in range(300_000))
        with mock.patch.object(X, "load_workbook") as ouvrir, \
                self.assertRaisesMessage(X.FichierInvalide, "32\u202f767 caractères"):
            X.lire(depose(feuille("titre", long_)))
        ouvrir.assert_not_called()

    def test_texte_juste_au_dessus_de_la_limite_refuse_a_la_lecture(self):
        """33 000 caractères : passe le contrôle par morceaux (borne large), refusé cellule par cellule."""
        with self.assertRaisesMessage(X.FichierInvalide, "32\u202f767 caractères"):
            X.lire(depose(feuille("titre", "é" * 33_000)))
        onglets = X.lire(depose(feuille("titre", "é" * 32_767)))  # à la limite : accepté
        self.assertEqual(len(next(iter(onglets.values()))[1][0]), 32_767)

    def test_classeur_normal_de_grande_taille(self):
        """Un vrai classeur de grande taille (classeur officiel de l'EFRAG : 16 onglets, validations, formules) passe."""
        with open(GRAND_CLASSEUR, "rb") as f:
            onglets = X.lire(depose(f.read(), GRAND_CLASSEUR.name))
        self.assertGreater(sum(len(v) for v in onglets.values()), 1000)
        X.controler_classeur(GRAND_CLASSEUR)  # aussi par chemin (commandes d'import)
        RE.ouvrir_classeur(GRAND_CLASSEUR).close()

    def test_fichier_remis_au_debut(self):
        f = io.BytesIO(classeur())
        X.controler_classeur(f)
        self.assertEqual(f.tell(), 0)

    def test_pas_un_zip_laisse_a_openpyxl(self):
        with self.assertRaisesMessage(X.FichierInvalide, "ne peut pas lire"):
            X.lire(depose(b"pas un classeur"))

    def test_commandes_d_import(self):
        chemin = Path(self.enterContext(__import__("tempfile").TemporaryDirectory())) / "piege.xlsx"
        chemin.write_bytes(piege())
        with mock.patch.object(RE, "load_workbook") as ouvrir, self.assertRaises(X.FichierInvalide):
            RE.ouvrir_classeur(chemin)
        ouvrir.assert_not_called()

    def test_feuille_renommee(self):
        """openpyxl trouve la feuille par les relations, quel que soit son nom : une feuille renommée « sheet1.dat »
        est contrôlée comme les autres."""
        def renommer(octets):
            sortie = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(octets)) as zin, zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as zout:
                for i in zin.infolist():
                    contenu = zin.read(i.filename).replace(b"worksheets/sheet1.xml", b"worksheets/sheet1.dat")
                    zout.writestr(i.filename.replace("worksheets/sheet1.xml", "worksheets/sheet1.dat"), contenu)
            return sortie.getvalue()

        lisible = renommer(feuille("titre", "court"))
        self.assertIn("xl/worksheets/sheet1.dat", zipfile.ZipFile(io.BytesIO(lisible)).namelist())
        self.assertEqual(next(iter(X.lire(depose(lisible)).values()))[1], ["court"])  # openpyxl la lit bien
        import random

        aleatoire = random.Random(1)
        long_ = "".join(aleatoire.choice("abcdefghijklmnopqrstuvwxyz ") for _ in range(300_000))
        with mock.patch.object(X, "load_workbook") as ouvrir, \
                self.assertRaisesMessage(X.FichierInvalide, "32\u202f767 caractères"):
            X.lire(depose(renommer(feuille("titre", long_))))
        ouvrir.assert_not_called()

    def test_media_connu_non_lu_comme_texte(self):
        """Une grande image (longues suites d'octets sans « < ») ne passe pas pour un texte trop long."""
        image = b"\x89PNG\r\n\x1a\n" + bytes(range(1, 256)).replace(b"<", b"") * 2000
        self.assertGreater(len(image), X.SANS_BALISE_MAX)
        octets = io.BytesIO(classeur())
        with zipfile.ZipFile(octets, "a") as z:
            z.writestr("xl/media/image1.png", image)
        X.controler_classeur(io.BytesIO(octets.getvalue()))
        forge = io.BytesIO(classeur())  # même contenu sans signature d'image, sous un nom d'image : contrôlé
        with zipfile.ZipFile(forge, "a") as z:
            z.writestr("xl/media/image1.png", image[8:])
        with self.assertRaises(X.FichierInvalide):
            X.controler_classeur(io.BytesIO(forge.getvalue()))

    def test_suite_sans_balise(self):
        """Contrôle par morceaux : une longue suite coupée entre deux morceaux est bien vue."""
        xml = b"<a>" + b"x" * (X.SANS_BALISE_MAX - 10) + b"</a><b>" + b"y" * 5 + b"</b>"
        ok = remplacer_entree(classeur(), "xl/worksheets/sheet1.xml", xml)
        X.controler_classeur(io.BytesIO(ok))
        trop = remplacer_entree(classeur(), "xl/worksheets/sheet1.xml", b"<a>" + b"z" * (2 * 1024 * 1024 + 5) + b"</a>")
        with mock.patch.object(X, "TAUX_MAX", 10_000), self.assertRaises(X.FichierInvalide):
            X.controler_classeur(io.BytesIO(trop))


class MessageSelonLaLangueTests(TestCase):
    def test_nombre_du_message_selon_la_langue(self):
        """La limite est écrite avec le séparateur de milliers de la langue : « 32,767 » en anglais."""
        from parametres import langues as L

        for langue, attendu in (("en", "more than 32,767 characters"), ("es", "supera los 32.767 caracteres")):
            with self.subTest(langue=langue), L.session(), L.activer_interface(langue), \
                    self.assertRaisesMessage(X.FichierInvalide, attendu):
                X.lire(depose(feuille("titre", "é" * 33_000)))
