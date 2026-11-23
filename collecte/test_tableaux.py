"""Réponses en forme de tableau (format « tableau ») : lecture et vérification colonne par colonne,
enregistrement en tableau Markdown normalisé, lignes et fusion, saisie depuis le panneau (éditeur, brouillon), affichage
court, règles de la fiche KPI, paquets (colonnes, liste renommée à l'installation), définition des colonnes refusée."""
import io
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from parametres.models import TypeReponse
from referentiel.models import KPI, Attribution, Niveau

from . import paquets as P
from . import saisie as S
from . import tableaux as T
from .aides_tests.referentiels import Base as BaseReferentiels
from .aides_tests.saisie import Base
from .models import Reponse
from .templatetags import collecte as TT

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


def classeur(rep):
    from openpyxl import load_workbook

    return load_workbook(io.BytesIO(rep.content))
COLONNES = [
    {"code": "polluant", "libelle": {"fr": "Polluant", "en": "Pollutant"}, "type": "liste", "liste": "ESSAI-POLLUANT"},
    {"code": "air", "libelle": {"fr": "Rejets dans l'air", "en": "Emissions to air"}, "type": "nombre", "unite": "kg"},
    {"code": "note", "libelle": {"fr": "Remarque", "en": "Note"}, "type": "texte"},
]


def creer_types():
    liste = TypeReponse.objects.create(code="ESSAI-POLLUANT", libelle="Polluant d'essai", format="liste",
                                       valeurs=["Ammoniac", "Benzène"], traductions={"en": {"valeurs": ["Ammonia", "Benzene"]}})
    tableau = TypeReponse.objects.create(code="ESSAI-TAB", libelle="Rejets d'essai", format="tableau", colonnes=COLONNES)
    return liste, tableau


class LectureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.liste, cls.tab = creer_types()

    def test_normalisation(self):
        saisi = ("| Pollutant | Air | Note |\n|---|---|---|\n| Ammonia | 1 234,5 | a \\| b |\n|  |  |  |\n"
                 "| Benzène | 12 | |")
        md = T.lire(saisi, self.tab)
        self.assertEqual(md.split("\n"), ["| Polluant | Rejets dans l'air (kg) | Remarque |", "| --- | ---: | --- |",
                                          "| Ammoniac | 1234.5 | a \\| b |", "| Benzène | 12 |  |"])
        self.assertEqual(T.lire(md, self.tab), md)  # relu à l'identique : pas de faux changement
        self.assertEqual(T.lignes(md, self.tab), [{"polluant": "Ammoniac", "air": Decimal("1234.5"), "note": "a | b"},
                                                  {"polluant": "Benzène", "air": Decimal("12"), "note": None}])
        self.assertEqual((T.lire("", self.tab), T.resume(md)), ("", 2))
        # sans en-tête (lignes seules), cellules manquantes complétées
        self.assertEqual(T.lignes(T.lire("| Benzene | 3 |", self.tab), self.tab), [{"polluant": "Benzène", "air": Decimal("3"), "note": None}])

    def test_refus_qui_nomment_la_ligne_et_la_colonne(self):
        with self.assertRaises(ValidationError) as e:
            T.lire("| Polluant | Air | Note |\n|---|---|---|\n| Mercure | douze | x |\n| Ammoniac | 1 | 2 | 3 |", self.tab)
        textes = " ".join(e.exception.messages)
        self.assertIn("Ligne 1, Polluant : « Mercure » n'est pas dans la liste.", textes)
        self.assertIn("Ligne 1, Rejets dans l'air (kg) : saisissez un nombre.", textes)
        self.assertIn("Ligne 2 : plus de cellules que de colonnes dans le tableau (3).", textes)
        sans = TypeReponse.objects.create(code="ESSAI-VIDE", libelle="Vide", format="tableau", colonnes=[])
        with self.assertRaisesMessage(ValidationError, "pas de colonnes"):
            T.lire("| a |", sans)
        with self.assertRaisesMessage(ValidationError, "au plus 500 lignes"):
            T.lire("\n".join(f"| Ammoniac | {i} | |" for i in range(501)), self.tab)

    def test_fusion(self):
        a = T.lignes(T.lire("| Ammoniac | 10 | |\n| Benzène | 1 | |", self.tab), self.tab)
        b = T.lignes(T.lire("| Ammoniac | 5 | |", self.tab), self.tab)
        self.assertEqual(T.fusionner([a, b], self.tab), [{"polluant": "Ammoniac", "air": Decimal("15"), "note": None},
                                                         {"polluant": "Benzène", "air": Decimal("1"), "note": None}])

    def test_definition_des_colonnes(self):
        self.assertEqual(T.erreurs_colonnes(COLONNES, {"ESSAI-POLLUANT"}), [])
        erreurs = " ".join(T.erreurs_colonnes([{"code": "a", "type": "nombre"}, {"code": "a", "type": "date"},
                                               {"code": "b", "type": "liste", "liste": "INCONNUE"}, "x"], {"ESSAI-POLLUANT"}))
        for attendu in ("Colonne 2 : donnez un code", "Colonne 2 : le type est l'un de", "la liste « INCONNUE » n'existe pas",
                        "La colonne 4 est illisible"):
            self.assertIn(attendu, erreurs)
        self.assertIn("au moins une colonne", " ".join(T.erreurs_colonnes([], set())))


class SaisieTests(Base):
    def setUp(self):
        super().setUp()
        self.liste, self.tab = creer_types()
        self.rejets = KPI.objects.create(code="REJ", libelle="Rejets", type_saisie_id="Saisi", granularite_id=self.eff.granularite_id,
                                         type_reponse=self.tab, methode_agregation="Aucune")
        Attribution.objects.create(kpi=self.rejets, organisation=self.e1, utilisateur=self.contrib)
        self.url = reverse("collecte:cellule", args=[self.c.pk, "REJ", self.e1.pk])
        self.client.force_login(self.contrib)

    def test_regles_de_la_fiche(self):
        self.assertTrue(self.rejets.est_tableau and self.rejets.est_texte and not self.rejets.est_numerique)
        self.rejets.methode_agregation = "Décompte"
        self.assertIn("methode_agregation", self.rejets.erreurs_regles())

    def test_panneau_et_enregistrement(self):
        html = self.client.get(self.url, **FETCH).json()["html"]
        for attendu in ("data-editeur-tableau", 'data-col>Polluant</th>', "Rejets dans l&#x27;air (kg)", '<option value="Ammoniac">',
                        "data-modele-ligne", "Ajouter une ligne"):
            self.assertIn(attendu, html)
        rep = self.client.post(self.url, {"action": "enregistrer", "version": "", "valeur": "| Polluant | Air | Note |\n|-|-|-|\n| Benzene | 2,5 | |",
                                          "commentaire": ""}, **FETCH).json()
        self.assertTrue(rep["ok"], rep)
        r = Reponse.objects.get(kpi=self.rejets, organisation=self.e1)
        self.assertEqual(r.texte.split("\n")[2], "| Benzène | 2.5 |  |")
        self.assertIn("1 ligne", "".join(rep["lignes"].values()))  # liste de la Saisie : nombre de lignes
        html = self.client.get(self.url, **FETCH).json()["html"]
        self.assertIn('value="Benzène"', html)  # la ligne revient dans l'éditeur
        # refus : la ligne en cause est dite, rien n'est enregistré
        rep = self.client.post(self.url, {"action": "enregistrer", "version": S.version(r), "valeur": "| Plomb | 1 | |", "commentaire": ""},
                               **FETCH).json()
        self.assertFalse(rep["ok"])
        self.assertIn("« Plomb » n&#x27;est pas dans la liste", rep["html"])
        self.assertEqual(Reponse.objects.get(pk=r.pk).texte.split("\n")[2], "| Benzène | 2.5 |  |")

    def test_affichage_court(self):
        r = Reponse(kpi=self.rejets, texte=T.lire("| Ammoniac | 1 | |\n| Benzène | 2 | |", self.tab))
        self.assertEqual(TT.valeur(r, self.rejets), "2 lignes")
        self.assertEqual(TT.valeur(Reponse(kpi=self.rejets, texte=""), self.rejets), "–")


class PaquetTests(TestCase):
    def test_colonnes_et_liste_renommee(self):
        """Une liste du paquet dont le code est déjà pris par une autre liste est créée sous un autre code : la colonne du
        tableau suit ce nouveau code."""
        from referentiel.models import ElementReferentiel, Referentiel

        liste, tab = creer_types()
        from parametres import niveaux as N

        k = KPI.objects.create(code="REJ", libelle="Rejets", type_saisie_id="Saisi", type_reponse=tab, methode_agregation="Aucune",
                               granularite_id=N.le_plus_bas().code)
        ref = Referentiel.objects.create(code="R", nom="R")
        ElementReferentiel.objects.create(referentiel=ref, kpi=k)
        p = P.extraire(ref)
        types = {t["code"]: t for t in p.types_reponse}
        self.assertEqual(set(types), {"ESSAI-TAB", "ESSAI-POLLUANT"})  # la liste de la colonne voyage avec le tableau
        self.assertEqual(types["ESSAI-TAB"]["colonnes"], COLONNES)
        d = json.loads(P.vers_json(p))
        # autre installation : une liste « ESSAI-POLLUANT » existe déjà avec d'autres valeurs ; le KPI REJ n'existe pas
        Reponse.objects.all().delete()
        ElementReferentiel.objects.all().delete()
        Referentiel.objects.all().delete()
        k.delete()
        tab.delete()
        liste.valeurs = ["Autre"]
        liste.save()
        a = P.analyser(P.depuis_dict(d))
        self.assertEqual(a.erreur, "")
        P.appliquer(None, a)
        nouveau = KPI.objects.get(code="REJ").type_reponse
        code_liste = nouveau.colonnes[0]["liste"]
        self.assertNotEqual(code_liste, "ESSAI-POLLUANT")
        self.assertEqual(TypeReponse.objects.get(code=code_liste).valeurs, ["Ammoniac", "Benzène"])
        with self.assertRaisesMessage(P.PaquetInvalide, "types_reponse[1].colonnes"):
            d["types_reponse"][0]["colonnes"] = "pas une liste"
            P.depuis_dict(d)


class ExportsImportsTests(BaseReferentiels):
    """Une réponse en tableau traverse les exports (base de données : Markdown brut ; fichiers à lire : lignes lisibles),
    le fichier à remplir (relu et vérifié à l'import) et compte comme une case dans le taux de remplissage."""

    def setUp(self):
        super().setUp()
        from referentiel.composition import composer

        self.liste, self.tab = creer_types()
        self.rej = KPI.objects.create(code="REJ", libelle="Rejets", type_saisie_id="Saisi", type_reponse=self.tab,
                                      granularite_id=Niveau.ENTITY, methode_agregation="Aucune")
        composer({"REJ": ["Social"]}, self.rse)
        Attribution.objects.create(kpi=self.rej, organisation=self.e1, utilisateur=self.contrib)

    def saisir(self, texte="| Ammonia | 1 234,5 | sur site |\n| Benzène | 2 | |"):
        return S.enregistrer(self.contrib, self.c, self.rej, self.e1, texte, False, "")

    def test_exports(self):
        from . import exports as E

        self.saisir()
        md = Reponse.objects.get(kpi=self.rej, organisation=self.e1).texte
        p = E.Parametres.depuis({"presentation": "base", "exercices": ["courant"]})
        wb = classeur(E.exporter(self.admin, p))
        lignes = list(wb["Valeurs"].iter_rows(values_only=True))
        rej = next(l for l in lignes[1:] if l[lignes[0].index("ID KPI")] == "REJ")
        self.assertEqual(rej[lignes[0].index("Valeur")], md)  # Markdown brut : relisible par l'import
        for presentation in ("tableau", "revue"):
            with self.subTest(presentation=presentation):
                p = E.Parametres.depuis({"presentation": presentation, "exercices": ["courant"], "contenus": ["valide", "brouillon", "a_saisir"]})
                wb = classeur(E.exporter(self.admin, p))
                textes = [c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row if isinstance(c.value, str)]
                self.assertNotIn(md, textes)  # jamais le Markdown brut dans un fichier à lire
                self.assertTrue(any("Ammoniac" in t and "1234.5" in t.replace(" ", "").replace(",", ".") for t in textes), textes)

    def test_fichier_a_remplir_et_reimport(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from . import imports as I

        self.saisir()
        wb = classeur(I.modele(self.contrib, self.c, I.lignes_modele(self.contrib, self.c)))
        ws = wb["Saisie"]
        n = next(r for r in range(1, 15) if ws.cell(r, 2).value == "ID KPI")
        tete = [c.value for c in ws[n]]
        ligne = next(r for r in range(n + 1, ws.max_row + 1) if ws.cell(r, 2).value == "REJ")
        valeur = ws.cell(ligne, tete.index("Valeur") + 1)
        self.assertTrue(valeur.value.startswith("| Polluant |"))
        valeur.value = "| Polluant | Air | Note |\n|---|---|---|\n| Benzene | 7 | |"
        flux = io.BytesIO()
        wb.save(flux)
        I.appliquer(self.contrib, SimpleUploadedFile("rempli.xlsx", flux.getvalue()), "rempli.xlsx")
        r = Reponse.objects.get(kpi=self.rej, organisation=self.e1, periode=self.c.periode)
        self.assertEqual(r.texte.split("\n")[2:], ["| Benzène | 7 |  |"])  # normalisé comme depuis le panneau
        # une valeur hors liste : ligne refusée avec la raison, rien n'est changé
        valeur.value = "| Mercure | 1 | |"
        flux = io.BytesIO()
        wb.save(flux)
        a = I.analyser(self.contrib, SimpleUploadedFile("faux.xlsx", flux.getvalue()))
        rej = next(l for l in a.lignes if l.kpi_id == "REJ")
        self.assertIn("Mercure", rej.motif)

    def test_tableau_de_bord_compte_la_case(self):
        self.client.force_login(self.contrib)
        url = reverse("collecte:tableau_de_bord") + f"?campagne={self.c.pk}"
        avant = dict(self.client.get(url).context["avancement"])[self.c]
        self.saisir()
        S.valider(self.contrib, self.c, self.rej, self.e1)
        apres = dict(self.client.get(url).context["avancement"])[self.c]
        self.assertEqual((apres.total, apres.valide), (avant.total, avant.valide + 1))
