"""Textes de départ d'une installation dans les sept langues (parametres/0036, règle du projet) : niveaux,
types de saisie et de réponse, catégories et unités fournis. Les données créées par les migrations ne passent par aucun
fichier de langue : l'allemand, l'italien, le néerlandais et le portugais montraient le français."""
import importlib

from django.apps import apps
from django.test import TestCase

from parametres import langues as L
from parametres import niveaux as N
from parametres import referentiel as PR
from parametres.models import CategorieDescription, Instance, NiveauHierarchique, TypeReponse, TypeSaisie, Unite

MIGRATION = importlib.import_module("parametres.migrations.0036_traductions_de_depart_sept_langues")
NOUVELLES = ("de", "it", "nl", "pt")
SEPT = ("en", "es", *NOUVELLES)


def texte(objet, langue, champ):
    return ((objet.traductions or {}).get(langue) or {}).get(champ)


class FournisTraduitsTests(TestCase):
    def test_niveaux_fournis_dans_toutes_les_langues(self):
        for n in NiveauHierarchique.objects.filter(code__in=("Group", "Country", "Entity", "Site")):
            for langue in SEPT:
                self.assertTrue(texte(n, langue, "nom"), (n.code, langue))
                self.assertTrue(texte(n, langue, "nom_pluriel"), (n.code, langue))
        site = NiveauHierarchique.objects.get(code="Site")
        self.assertEqual([texte(site, lg, "nom") for lg in NOUVELLES], ["Standort", "Sede", "Locatie", "Local"])

    def test_types_de_saisie_fournis(self):
        for t in TypeSaisie.objects.filter(code__in=("Saisi", "Calculé", "FE")):
            for langue in SEPT:
                self.assertTrue(texte(t, langue, "libelle"), (t.code, langue))
                self.assertTrue(texte(t, langue, "abrege"), (t.code, langue))
        self.assertEqual(texte(TypeSaisie.objects.get(code="Calculé"), "de", "libelle"), "Berechnet")
        self.assertEqual(texte(TypeSaisie.objects.get(code="FE"), "pt", "libelle"), "Fator de emissão")

    def test_types_de_reponse_et_categories_fournis(self):
        for modele, codes in ((TypeReponse, ("Numérique", "Pourcentage", "TexteRedige")),
                              (CategorieDescription, ("description", "a_inclure", "a_exclure", "source"))):
            for o in modele.objects.filter(code__in=codes):
                for langue in SEPT:
                    self.assertTrue(texte(o, langue, "libelle"), (o.code, langue))
        self.assertEqual(texte(TypeReponse.objects.get(code="TexteRedige"), "nl", "libelle"), "Uitgeschreven tekst")

    def test_unites_fournies_traduites_meme_en_anglais_et_espagnol(self):
        for code in MIGRATION.UNITES:
            u = Unite.objects.get(code=code)
            for langue in SEPT:
                self.assertTrue(texte(u, langue, "libelle"), (code, langue))
        self.assertEqual(texte(Unite.objects.get(code="salariés"), "de", "symbole"), "Beschäftigte")
        self.assertIsNone(texte(Unite.objects.get(code="kWh"), "de", "symbole"))  # un symbole universel ne se traduit pas

    def test_l_interface_montre_les_mots_de_la_langue(self):
        for langue, attendu in (("de", "Standort"), ("it", "Sede"), ("nl", "Locatie"), ("pt", "Local"), ("es", "Centro")):
            self.assertEqual(L.traduire(NiveauHierarchique.objects.get(code="Site"), "nom", langue), attendu)
        self.assertEqual(L.traduire(TypeSaisie.objects.get(code="Saisi"), "abrege", "it"), "Inserim.")


class MigrationAdditiveTests(TestCase):
    def test_complete_sans_ecraser_et_sans_toucher_un_texte_renomme(self):
        site = NiveauHierarchique.objects.get(code="Site")
        site.traductions = {"en": {"nom": "Site", "nom_pluriel": "Sites"}, "de": {"nom": "Werk"}}  # « Werk » saisi : gardé
        site.save()
        pays = NiveauHierarchique.objects.get(code="Country")
        pays.nom, pays.traductions = "Région", {}  # renommé par l'administrateur : jamais touché
        pays.save()
        saisi = TypeSaisie.objects.get(code="Saisi")
        saisi.traductions = {}
        saisi.save()
        MIGRATION.traduire(apps, None)
        site = NiveauHierarchique.objects.get(code="Site")
        self.assertEqual(texte(site, "de", "nom"), "Werk")
        self.assertEqual(texte(site, "de", "nom_pluriel"), "Standorte")  # le champ absent est complété
        self.assertEqual(texte(site, "en", "nom"), "Site")  # l'anglais existant n'est pas modifié
        self.assertEqual(NiveauHierarchique.objects.get(code="Country").traductions, {})
        self.assertEqual(texte(TypeSaisie.objects.get(code="Saisi"), "pt", "libelle"), "Introduzido")

    def test_deuxieme_passage_ne_change_rien(self):
        avant = {(m.__name__, o.pk): o.traductions for m in (NiveauHierarchique, TypeSaisie, TypeReponse, CategorieDescription, Unite)
                 for o in m.objects.all()}
        MIGRATION.traduire(apps, None)
        apres = {(m.__name__, o.pk): o.traductions for m in (NiveauHierarchique, TypeSaisie, TypeReponse, CategorieDescription, Unite)
                 for o in m.objects.all()}
        self.assertEqual(avant, apres)

    def test_langue_de_reference_jamais_ecrite_dans_les_traductions(self):
        i = Instance.courante()
        i.langue_reference = "de"
        i.save()
        NiveauHierarchique.objects.filter(code="Site").update(traductions={})
        MIGRATION.traduire(apps, None)
        self.assertNotIn("de", NiveauHierarchique.objects.get(code="Site").traductions)  # le champ porte déjà cette langue
        self.assertIn("it", NiveauHierarchique.objects.get(code="Site").traductions)


class InstallationVideeTests(TestCase):
    def test_niveaux_et_types_recrees_par_defaut_sont_traduits(self):
        NiveauHierarchique.objects.all().delete()
        TypeSaisie.objects.all().delete()
        TypeReponse.objects.all().delete()
        CategorieDescription.objects.all().delete()
        N.creer_par_defaut()
        PR.creer_par_defaut()
        for langue in SEPT:
            self.assertTrue(texte(NiveauHierarchique.objects.get(code="Entity"), langue, "nom"), langue)
            self.assertTrue(texte(TypeSaisie.objects.get(code="FE"), langue, "libelle"), langue)
            self.assertTrue(texte(TypeReponse.objects.get(code="Pourcentage"), langue, "libelle"), langue)
            self.assertTrue(texte(CategorieDescription.objects.get(code="source"), langue, "libelle"), langue)
