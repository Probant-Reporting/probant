"""Import / export du référentiel au format historique : colonnes par langue (nom, définitions et thèmes traduits).

Demande retenue : chaque texte du référentiel en français, en anglais et en espagnol ; le classeur fourni
porte les trois langues (« nom_es », « description_en », « description_es », « theme_es »…)."""
import tempfile

from django.test import TestCase
from openpyxl import Workbook, load_workbook

from parametres import langues as L
from referentiel.echange import CHAMPS_KPI, colonne_langue, entete, exporter_kpi, importer_kpi
from referentiel.models import KPI, Niveau, Theme

EXTRA = ["nom_es", "description_en", "description_es", "a_inclure_en", "a_inclure_es", "theme_en", "theme_es",
         "sous_theme_en", "sous_theme_es"]


def classeur(dossier, lignes, extra=EXTRA):
    wb = Workbook()
    ws = wb.active
    ws.title = "KPI"
    ws.append([entete(c) for c in CHAMPS_KPI] + extra)
    for d in lignes:
        ws.append([d.get(c, "") for c in CHAMPS_KPI + extra])
    chemin = f"{dossier}/referentiel.xlsx"
    wb.save(chemin)
    return chemin


def ligne(code, **autres):
    return {"code": code, "type_saisie": "Saisi", "nom_fr": "Déchets recyclés (t)", "nom_en": "Waste recycled (t)",
            "nom_es": "Residuos reciclados (t)", "type_reponse": "Numérique", "granularite": Niveau.SITE,
            "methode_agregation": "Somme", "confidentialite": "Non sensible", "actif": "Oui",
            "theme": "05 Déchets", "theme_en": "05 Waste", "theme_es": "05 Residuos",
            "sous_theme": "05.08 Détail", "sous_theme_en": "05.08 Detail", "sous_theme_es": "05.08 Detalle",
            "description": "Masse de déchets recyclés.", "description_en": "Mass of waste recycled.",
            "description_es": "Masa de residuos reciclados.", "a_inclure": "Carton.", "a_inclure_en": "Cardboard.",
            "a_inclure_es": "Cartón.", **autres}


class ColonnesParLangueTests(TestCase):
    def setUp(self):
        from parametres.models import Langue

        Langue.objects.get_or_create(code="es", defaults=dict(libelle="Español", ordre=3))

    def test_lecture_des_entetes(self):
        self.assertEqual(colonne_langue("description_es"), ("description", "es"))
        self.assertEqual(colonne_langue("sous_theme_en"), ("sous_theme", "en"))
        self.assertIsNone(colonne_langue("nom_en"))  # colonne historique
        self.assertIsNone(colonne_langue("formule"))
        self.assertIsNone(colonne_langue("description"))

    def test_import_trois_langues(self):
        self.assertIn("es", L.codes_actifs())
        with tempfile.TemporaryDirectory() as d:
            r = importer_kpi(classeur(d, [ligne("W1")]))
        self.assertEqual(r.erreurs, [])
        k = KPI.objects.get(code="W1")
        self.assertEqual((L.texte(k, "libelle", "fr"), L.texte(k, "libelle", "en"), L.texte(k, "libelle", "es")),
                         ("Déchets recyclés (t)", "Waste recycled (t)", "Residuos reciclados (t)"))
        self.assertEqual(k.texte_description("description", "fr", repli=False), "Masse de déchets recyclés.")
        self.assertEqual(k.texte_description("description", "en", repli=False), "Mass of waste recycled.")
        self.assertEqual(k.texte_description("description", "es", repli=False), "Masa de residuos reciclados.")
        self.assertEqual(k.texte_description("a_inclure", "es", repli=False), "Cartón.")
        haut = Theme.objects.get(nom="05 Déchets")
        bas = Theme.objects.get(nom="05.08 Détail")
        self.assertEqual((L.texte(haut, "nom", "en"), L.texte(haut, "nom", "es")), ("05 Waste", "05 Residuos"))
        self.assertEqual((L.texte(bas, "nom", "en"), L.texte(bas, "nom", "es")), ("05.08 Detail", "05.08 Detalle"))

    def test_langue_pas_encore_active_gardee(self):
        from parametres.models import Langue

        Langue.objects.filter(code="es").update(active=False)
        with tempfile.TemporaryDirectory() as d:
            importer_kpi(classeur(d, [ligne("W1")]))
        k = KPI.objects.get(code="W1")
        self.assertEqual(L.texte(k, "libelle", "es"), "Residuos reciclados (t)")
        self.assertEqual(k.texte_description("description", "es", repli=False), "Masa de residuos reciclados.")

    def test_reimport_change_une_traduction_et_vide_ne_retire_rien(self):
        with tempfile.TemporaryDirectory() as d:
            importer_kpi(classeur(d, [ligne("W1")]))
            r = importer_kpi(classeur(d, [ligne("W1")]))
            self.assertEqual((r.modifies, r.inchanges), (0, 1))
            r = importer_kpi(classeur(d, [ligne("W1", description_es="Masa reciclada.", theme_es="05 Desechos",
                                                a_inclure_en="")]))
            self.assertEqual((r.erreurs, r.modifies), ([], 1))
        k = KPI.objects.get(code="W1")
        self.assertEqual(k.texte_description("description", "es", repli=False), "Masa reciclada.")
        self.assertEqual(k.texte_description("a_inclure", "en", repli=False), "Cardboard.")  # cellule vide : gardé
        self.assertEqual(L.texte(Theme.objects.get(nom="05 Déchets"), "nom", "es"), "05 Desechos")

    def test_sans_colonnes_par_langue_rien_ne_change(self):
        with tempfile.TemporaryDirectory() as d:
            importer_kpi(classeur(d, [ligne("W1")]))
            r = importer_kpi(classeur(d, [ligne("W1")], extra=[]))
        self.assertEqual((r.erreurs, r.modifies), ([], 0))
        k = KPI.objects.get(code="W1")
        self.assertEqual(k.texte_description("description", "es", repli=False), "Masa de residuos reciclados.")

    def test_export_puis_reimport(self):
        with tempfile.TemporaryDirectory() as d:
            importer_kpi(classeur(d, [ligne("W1")]))
            chemin = f"{d}/export.xlsx"
            exporter_kpi(chemin)
            ws = load_workbook(chemin, read_only=True)["KPI"]
            lignes = list(ws.iter_rows(values_only=True))
            entetes, valeurs = list(lignes[0]), dict(zip(lignes[0], lignes[1]))
            for c in ("nom_es", "description_en", "description_es", "theme_es", "sous_theme_es"):
                self.assertIn(c, entetes)
            self.assertEqual(valeurs["description_es"], "Masa de residuos reciclados.")
            self.assertEqual(valeurs["sous_theme_es"], "05.08 Detalle")
            r = importer_kpi(chemin)
        self.assertEqual((r.erreurs, r.modifies, r.inchanges), ([], 0, 1))
