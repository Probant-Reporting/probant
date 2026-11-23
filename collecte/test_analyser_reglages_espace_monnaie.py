"""Fichier de configuration et monnaie de référence : l'onglet « Réglages » porte la monnaie
de référence (code ISO) ; réimporté tel quel il n'écrit rien ; une autre monnaie de la liste la change (une ligne
d'historique) ; une monnaie hors de la liste refuse tout le fichier (tout ou rien) ; un fichier sans cet onglet ne change
rien. Anglais : onglet « Settings », en-têtes traduits."""
import io

from django.core.files.uploadedfile import SimpleUploadedFile

from parametres.models import Instance

from . import configuration as C
from .aides_tests import echanges as TE
from .models import Journal


class ReglagesTests(TE.Base):
    def fichier(self, monnaie=None, sans_onglet=False, langue="fr", code="monnaie"):
        wb = TE.classeur(C.exporter(langue=langue))
        nom = "Réglages" if langue == "fr" else "Settings"
        if sans_onglet:
            del wb[nom]
        elif monnaie is not None:
            wb[nom]["A2"] = code
            wb[nom]["C2"] = monnaie
        flux = io.BytesIO()
        wb.save(flux)
        return SimpleUploadedFile("config.xlsx", flux.getvalue())

    def test_onglet_exporte(self):
        ws = TE.classeur(C.exporter())["Réglages"]
        self.assertEqual([c.value for c in ws[1]], ["Code", "Libellé", "Valeur"])
        self.assertEqual([c.value for c in ws[2]], ["monnaie", "Monnaie de référence (code ISO 4217)", "EUR"])
        ws = TE.classeur(C.exporter(langue="en"))["Settings"]
        self.assertEqual([c.value for c in ws[1]], ["Code", "Label", "Value"])
        self.assertEqual(ws["B2"].value, "Reference currency (ISO 4217 code)")

    def test_reimporte_tel_quel_n_ecrit_rien(self):
        avant = Journal.objects.count()
        a, n, _ = C.appliquer(self.admin, self.fichier(), "config.xlsx")
        self.assertEqual((a.nb_rejets, n, a.importable), (0, 0, False))
        self.assertEqual(Journal.objects.count(), avant)

    def test_autre_monnaie(self):
        a, n, _ = C.appliquer(self.admin, self.fichier("usd"), "config.xlsx")
        self.assertEqual((a.nb_rejets, n), (0, 1))
        self.assertEqual(Instance.courante().monnaie, "USD")
        j = Journal.objects.get(champ="Monnaie de référence")
        self.assertEqual((j.avant, j.apres), ("EUR", "USD"))
        a, n, _ = C.appliquer(self.admin, self.fichier("£", langue="en"), "config.xlsx")  # symbole, fichier en anglais
        self.assertEqual(Instance.courante().monnaie, "GBP")

    def test_monnaie_hors_liste_refuse_tout(self):
        a, n, _ = C.appliquer(self.admin, self.fichier("Bitcoin"), "config.xlsx")
        self.assertEqual((a.nb_rejets, n), (1, 0))
        ligne = a.onglets["Réglages"][0]
        self.assertTrue(ligne.motif.startswith("La monnaie « Bitcoin » n'est pas dans la liste. Utilisez un de ces codes : EUR, USD"))
        self.assertEqual(Instance.courante().monnaie, "EUR")
        a, n, _ = C.appliquer(self.admin, self.fichier("USD", code="taux"), "config.xlsx")
        self.assertEqual((a.nb_rejets, n), (1, 0))
        self.assertEqual(Instance.courante().monnaie, "EUR")

    def test_cellule_vide_ou_onglet_absent(self):
        for f in (self.fichier(""), self.fichier(sans_onglet=True)):
            a, n, _ = C.appliquer(self.admin, f, "config.xlsx")
            self.assertEqual((a.nb_rejets, n), (0, 0))
        self.assertEqual(Instance.courante().monnaie, "EUR")
