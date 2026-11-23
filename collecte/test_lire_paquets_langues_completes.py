"""Fichier référentiel et classeur de configuration écrits dans CHAQUE langue complète de l'interface, puis relus : aucune
différence, aucun refus (noms d'onglets, en-têtes et valeurs reconnus)."""
import io
import re

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import load_workbook

from parametres import libelles as LB

from . import configuration as C
from . import fichiers as X
from . import paquets as P
from .aides_tests.paquets import Base


class FichiersToutesLanguesTests(Base):
    def test_fichier_referentiel_relu_sans_difference(self):
        for langue in LB.langues_disponibles():
            with self.subTest(langue=langue):
                flux = io.BytesIO()
                P.classeur(P.extraire(self.r1), langue=langue).save(flux)
                flux.seek(0)
                flux.name = "r1.xlsx"
                a = P.analyser(P.lire(flux))
                self.assertEqual(a.erreur, "")
                self.assertTrue(a.aucune_difference, (a.compteurs, [(l.code, l.statut, l.motif) for l in a.kpis]))

    def test_fichier_de_configuration_relu_sans_changement(self):
        for langue in LB.langues_disponibles():
            with self.subTest(langue=langue):
                rep = C.exporter(langue=langue)
                self.assertTrue(load_workbook(io.BytesIO(rep.content)).sheetnames)
                a = C.analyser(SimpleUploadedFile("conf.xlsx", rep.content))
                self.assertEqual(a.erreur, "")
                self.assertEqual({c.action for cs in a.onglets.values() for c in cs}, {"inchange"})

    def test_noms_d_onglets_distincts_dans_chaque_langue(self):
        """Dans chaque langue, deux onglets de fichiers d'administration n'ont jamais le même nom (après normalisation à la
        lecture), et chaque nom est un nom d'onglet Excel valable (31 caractères, sans [ ] : * ? / \\)."""
        for langue in LB.langues_disponibles():
            with self.subTest(langue=langue):
                vus = {}
                for fr in X.ONGLETS:
                    nom = X.nom_onglet(fr, langue)
                    self.assertLessEqual(len(nom), 31, (langue, nom))
                    self.assertIsNone(re.search(r"[\[\]:*?/\\]", nom), (langue, nom))
                    self.assertNotIn(X.normaliser(nom), vus, (langue, fr, vus.get(X.normaliser(nom)), nom))
                    vus[X.normaliser(nom)] = fr

    def test_un_nom_d_onglet_n_est_jamais_pris_pour_un_autre_dans_aucune_langue(self):
        """Toutes langues confondues (la lecture reconnaît toutes les langues), un nom d'onglet normalisé désigne un seul
        onglet : le classeur de configuration (« Référentiels ») ne passe pas pour un fichier référentiel (« Référentiel »)."""
        par_nom = {}
        for fr in X.ONGLETS:
            for langue in LB.langues_disponibles():
                nom = X.normaliser(X.nom_onglet(fr, langue))
                self.assertEqual(par_nom.setdefault(nom, fr), fr, (langue, nom, fr, par_nom[nom]))

    def test_classeur_de_configuration_reconnu_a_l_import_d_un_referentiel(self):
        """Un classeur de configuration écrit dans chaque langue, déposé dans l'import d'un référentiel, reçoit le message
        « classeur de configuration » (jamais « le code du référentiel manque » ni « pas un fichier référentiel »)."""
        for langue in LB.langues_disponibles():
            with self.subTest(langue=langue):
                rep = C.exporter(langue=langue)
                flux = io.BytesIO(rep.content)
                flux.name = "conf.xlsx"
                with self.assertRaises(P.PaquetInvalide) as ctx:
                    P.lire(flux)
                self.assertEqual(str(ctx.exception), P._t("referentiels.paquets.classeur_config"))
