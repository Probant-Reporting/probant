"""KPI qualitatifs : format de réponse « texte rédigé » (Markdown). Rendu sûr (injections), fiche
KPI, saisie (panneau, aperçu, limite de longueur), listes (extrait), calculs (jamais), exports et imports, configuration,
visualisation."""
import csv
import io
import json

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse
from openpyxl import load_workbook

from parametres.models import TypeReponse
from referentiel.models import KPI, Attribution, Niveau, verifier_formule

from . import calcul as CA
from . import exports as E
from . import imports as I
from . import markdown as MD
from . import saisie as S
from .models import Journal, Reponse
from .aides_tests.referentiels import Base

TEXTE = "## Politique\n\nNotre **charte** couvre :\n\n- l'énergie\n- les *déchets*\n\nVoir [la charte](https://example.org/c?a=1&b=2)."


def classeur(rep):
    return load_workbook(io.BytesIO(rep.content))


BALISES_PERMISES = {"p", "br", "strong", "em", "del", "code", "pre", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "hr", "a",
                    "div", "table", "thead", "tbody", "tr", "th", "td"}
ATTRIBUTS_PERMIS = {"href", "target", "rel", "start", "scope", "class", "data-label"}  # data-label : libellé de colonne échappé (cartes sur téléphone)


def verifier_html_sur(test, h):
    """Le HTML produit, lu comme un navigateur : seulement les balises et attributs du rendu ; liens http(s) ou mailto."""
    from html.parser import HTMLParser

    class Lecteur(HTMLParser):
        def handle_starttag(self, tag, attrs):
            test.assertIn(tag, BALISES_PERMISES, h)
            for nom, valeur in attrs:
                test.assertIn(nom, ATTRIBUTS_PERMIS, h)
                if nom == "href":
                    test.assertTrue(valeur.lower().startswith(("http://", "https://", "mailto:")), h)
                    test.assertNotRegex(valeur, r"[\s\"<>]", h)
                if nom == "class":
                    test.assertEqual(valeur, "md-tableau", h)
                if nom == "rel":
                    test.assertEqual(valeur, "noopener noreferrer", h)

    Lecteur().feed(h)


class RenduMarkdownTests(SimpleTestCase):
    def test_sous_ensemble(self):
        h = MD.rendu(TEXTE)
        self.assertIn("<h5>Politique</h5>", h)  # « ## » sous le niveau de titre de la page (h4 pour « # »)
        self.assertIn("<strong>charte</strong>", h)
        self.assertIn("<ul><li>l&#x27;énergie</li><li>les <em>déchets</em></li></ul>", h)
        self.assertIn('<a href="https://example.org/c?a=1&amp;b=2" target="_blank" rel="noopener noreferrer">la charte</a>', h)
        self.assertIn("<ol><li>un</li><li>deux</li></ol>", MD.rendu("1. un\n2. deux"))
        self.assertIn('<ol start="3">', MD.rendu("3) trois\n4) quatre"))
        self.assertIn("<blockquote><p>cité</p></blockquote>", MD.rendu("> cité"))
        self.assertIn("<p>ligne 1<br>ligne 2</p><p>paragraphe</p>", MD.rendu("ligne 1\nligne 2\n\nparagraphe"))
        self.assertIn("<code>a*b*c</code>", MD.rendu("`a*b*c`"))
        self.assertIn('<th scope="col">A</th>', MD.rendu("| A | B |\n|---|---|\n| 1 | 2 |"))
        self.assertIn('<td data-label="B">2</td>', MD.rendu("| A | B |\n|---|---|\n| 1 | 2 |"))
        self.assertIn("<del>barré</del>", MD.rendu("~~barré~~"))
        self.assertEqual(MD.rendu("mot_avec_soulignes et snake_case"), "<p>mot_avec_soulignes et snake_case</p>")
        self.assertEqual(MD.rendu(""), "")

    def test_injections(self):
        """Aucun HTML écrit ne passe ; liens http(s) et mailto seulement ; pas d'image chargée ; pas d'attribut d'événement."""
        vecteurs = [
            "<script>alert(1)</script>",
            "<img src=x onerror=alert(1)>",
            "<a href=\"javascript:alert(1)\">x</a>",
            "[x](javascript:alert(1))",
            "[x](JaVaScRiPt:alert(1))",
            "[x](javascript&#58;alert(1))",
            "[x](&#106;avascript:alert(1))",
            "[x](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)",
            "[x](vbscript:msgbox(1))",
            "[x](//evil.example/)",
            "[x](/relatif)",
            "[x](\" onmouseover=\"alert(1))",
            "[x](https://ok.example/\"onmouseover=\"alert(1))",
            "![img](https://evil.example/pixel.png)",
            "![x](javascript:alert(1))",
            "**<svg onload=alert(1)>**",
            "`<script>`",
            "```\n<script>alert(1)</script>\n```",
            "| <b onclick=x> | b |\n|---|---|\n| <iframe src=x> | c |",
            "&lt;script&gt;alert(1)&lt;/script&gt;",
            "> <style>body{display:none}</style>",
            "# <h1 onclick=alert(1)>titre</h1>",
            "[clic](https://ok.example/ \"titre\" onclick=alert(1))",
            "\x00<script>alert(1)</script>",
        ]
        for v in vecteurs:
            with self.subTest(v=v):
                verifier_html_sur(self, str(MD.rendu(v)))
        # une image devient un lien (jamais chargée)
        self.assertIn('<a href="https://evil.example/pixel.png" target="_blank" rel="noopener noreferrer">img</a>',
                      MD.rendu("![img](https://evil.example/pixel.png)"))
        self.assertIn('href="mailto:rse@exemple.test"', MD.rendu("[écrire](mailto:rse@exemple.test)"))
        self.assertEqual(MD.rendu("[x](javascript:alert(1))"), "<p>[x](javascript:alert(1))</p>")  # parenthèse : pas un lien
        self.assertEqual(MD.rendu("[x](javascript:void)"), "<p>x</p>")  # le texte reste, sans lien

    def test_extrait_et_texte_brut(self):
        self.assertEqual(MD.texte_brut(TEXTE), "Politique Notre charte couvre : l'énergie les déchets Voir la charte.")
        long = "mot " * 60
        e = MD.extrait(long)
        self.assertTrue(e.endswith("…") and len(e) <= MD.EXTRAIT + 1)
        self.assertEqual(MD.extrait("| A | B |\n|---|---|\n| 1 | 2 |"), "A · B 1 · 2")
        self.assertEqual(MD.extrait("<b>x</b>"), "<b>x</b>")  # texte brut : échappé à l'affichage, comme tout texte

    def test_normaliser(self):
        self.assertEqual(MD.normaliser("\r\n  a  \r\nb\x07\n\n"), "  a\nb")
        self.assertEqual(MD.normaliser(" \n \n"), "")


class TexteRedigeBase(Base):
    def setUp(self):
        super().setUp()
        self.type_texte = TypeReponse.objects.get(format="texte")
        self.pol = KPI.objects.create(code="POL", libelle="Décrire la politique", type_saisie_id="Saisi", type_reponse=self.type_texte,
                                      granularite_id=Niveau.ENTITY, methode_agregation="Aucune", decimales=2)
        from referentiel.composition import composer

        composer({"POL": ["Social"]}, self.rse)
        Attribution.objects.create(kpi=self.pol, organisation=self.e1, utilisateur=self.contrib)


class TypeEtFicheTests(TexteRedigeBase):
    def test_type_fourni_par_la_migration(self):
        self.assertEqual(self.type_texte.code, "TexteRedige")
        self.assertEqual(self.type_texte.libelle, "Texte rédigé")
        self.assertEqual(self.type_texte.traductions["en"]["libelle"], "Written text")
        self.assertEqual(self.type_texte.traductions["es"]["libelle"], "Texto redactado")
        self.assertTrue(self.type_texte.est_texte)
        self.assertEqual(self.type_texte.choix, [])

    def test_reglages_imposes(self):
        k = KPI.objects.get(code="POL")
        self.assertTrue(k.est_texte)
        self.assertFalse(k.est_numerique)
        self.assertEqual((k.decimales, k.unite_id, k.agregation_temps, k.na_compte_zero, k.saisie_au_dessus), (0, None, "aucune", False, False))
        k.methode_agregation = KPI.Agregation.DECOMPTE
        self.assertIn("methode_agregation", k.erreurs_regles())
        k.methode_agregation = KPI.Agregation.SOMME
        self.assertIn("methode_agregation", k.erreurs_regles())
        k.type_saisie_id = "Calculé"
        k.methode_agregation, k.formule = KPI.Agregation.AUCUNE, "1"
        self.assertIn("type_reponse", k.erreurs_regles())  # un KPI calculé est toujours un nombre

    def test_formule_qui_cite_un_texte_refusee(self):
        with self.assertRaisesMessage(ValidationError, "liste ou texte rédigé, pas un nombre : POL"):
            verifier_formule("X", "[POL] + 1")

    def test_fiche_kpi_propose_le_format(self):
        rep = self.client.get(reverse("collecte:referentiel_kpi", args=["POL"]))
        self.assertContains(rep, 'data-format="texte" selected')
        self.assertContains(rep, "data-aide-redige>")  # aide visible pour ce format
        self.assertContains(rep, 'data-agregation-temps="aucune"')

    def test_catalogue_des_formats(self):
        rep = self.client.get(reverse("parametres:referentiel") + "?section=types-reponse")
        self.assertContains(rep, "Les 6 formats possibles")
        self.assertContains(rep, "<h3>Texte rédigé</h3>")
        self.assertContains(rep, "<strong>Politique</strong>")  # aperçu rendu

    def test_format_fige_par_les_reponses(self):
        from . import reglages as R

        S.enregistrer(self.contrib, self.c, self.pol, self.e1, "Texte", False, "")
        self.assertTrue(R.motif_format_fige("POL", self.type_texte, TypeReponse.objects.get(code="Numérique")))


class SaisieTexteTests(TexteRedigeBase):
    def test_enregistrer_valider_et_remplissage(self):
        r = S.enregistrer(self.contrib, self.c, self.pol, self.e1, TEXTE.replace("\n", "\r\n") + "  \n\n", False, "")
        self.assertEqual((r.texte, r.valeur, r.statut), (TEXTE, None, Reponse.Statut.BROUILLON))
        S.valider(self.contrib, self.c, self.pol, self.e1)
        self.assertEqual(Reponse.objects.get(pk=r.pk).statut, Reponse.Statut.VALIDE)
        self.assertTrue(Journal.objects.filter(objet="Reponse", objet_id=str(r.pk), champ="texte", apres=TEXTE).exists())
        # vide (espaces seulement) : à saisir
        r = S.enregistrer(self.contrib, self.c, self.pol, self.e1, "   \n  ", False, "")
        self.assertEqual(r.statut, Reponse.Statut.A_SAISIR)
        # N/A : avec un commentaire
        S.enregistrer(self.contrib, self.c, self.pol, self.e1, "", True, "Pas de politique écrite")
        S.valider(self.contrib, self.c, self.pol, self.e1)

    def test_limite_de_longueur(self):
        S.enregistrer(self.contrib, self.c, self.pol, self.e1, "a" * MD.TEXTE_MAX, False, "")
        with self.assertRaises(ValidationError) as e:
            S.enregistrer(self.contrib, self.c, self.pol, self.e1, "a" * (MD.TEXTE_MAX + 1), False, "")
        self.assertTrue(e.exception.messages[0].startswith("Texte trop long : 20\u202f001 caractères pour 20\u202f000 au plus."))
        self.assertEqual(Reponse.objects.get(kpi=self.pol, organisation=self.e1, periode=self.c.periode).texte, "a" * MD.TEXTE_MAX)

    def test_panneau_apercu_et_liste(self):
        self.client.force_login(self.contrib)
        url = reverse("collecte:cellule", args=[self.c.pk, "POL", self.e1.pk])
        rep = self.client.get(url)
        self.assertContains(rep, 'class="zone-md"')
        self.assertContains(rep, 'role="toolbar"')
        self.assertContains(rep, 'aria-label="Gras"')
        self.assertContains(rep, f'maxlength="{MD.TEXTE_MAX}"')
        rep = self.client.post(url, {"action": "enregistrer", "valeur": TEXTE + "\n\n<script>alert(1)</script>", "commentaire": "",
                                     "version": ""}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertTrue(rep.json()["ok"])
        r = Reponse.objects.get(kpi=self.pol, organisation=self.e1, periode=self.c.periode)
        self.assertIn("<script>", r.texte)  # gardé tel quel (Markdown brut), jamais rendu en HTML
        # pleine page relue : texte dans la zone, échappé
        rep = self.client.get(url)
        self.assertContains(rep, "&lt;script&gt;alert(1)&lt;/script&gt;</textarea>")
        self.assertNotContains(rep, "<script>alert(1)")
        # aperçu : rendu du serveur
        rep = self.client.post(reverse("collecte:apercu_texte"), {"texte": "**gras** <script>x</script>"})
        self.assertEqual(rep.json()["html"], "<p><strong>gras</strong> &lt;script&gt;x&lt;/script&gt;</p>")
        # liste de la Saisie et Pour moi : un extrait en texte brut, pas le Markdown
        for page in ("collecte:saisie", "collecte:pour_moi"):
            rep = self.client.get(reverse(page) + f"?campagne={self.c.pk}&org={self.e1.pk}")
            self.assertContains(rep, "Politique Notre charte couvre")
            self.assertNotContains(rep, "## Politique")

    def test_lecture_seule_montre_le_rendu(self):
        from .models import Campagne

        S.enregistrer(self.admin, self.c, self.pol, self.e1, TEXTE, False, "")
        Campagne.objects.filter(pk=self.c.pk).update(statut=Campagne.Statut.CLOTUREE)  # clôturée : figée pour tous
        rep = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "POL", self.e1.pk]))
        self.assertContains(rep, "<strong>charte</strong>")
        self.assertNotContains(rep, 'class="zone-md"')

    def test_reponse_n1_en_repere(self):
        from .models import Campagne

        c0 = Campagne.objects.create(referentiel=self.rse, exercice=2025, statut=Campagne.Statut.CLOTUREE)
        Reponse.objects.create(periode=c0.periode, kpi=self.pol, organisation=self.e1, texte="Texte **2025**", statut="valide")
        rep = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "POL", self.e1.pk]))
        self.assertContains(rep, 'class="n1-redigee"')
        self.assertContains(rep, "Texte <strong>2025</strong>")


class CalculsEtControlesTests(TexteRedigeBase):
    def test_aucun_calcul_meme_mal_regle(self):
        S.enregistrer(self.contrib, self.c, self.pol, self.e1, TEXTE, False, "")
        KPI.objects.filter(code="POL").update(methode_agregation="Décompte", agregation_temps="derniere")  # réglage forcé en base
        CA.recalculer(self.c)
        self.assertFalse(Reponse.objects.filter(kpi=self.pol).exclude(organisation=self.e1).exists())
        from . import controle_donnees as CD

        resultat = CD.controler()  # contrôle de cohérence de la base : aucun contrôle en échec, aucune erreur
        self.assertEqual([c["check"] for c in resultat["problems"] if c["count"] and c["check"] == "check_failed"], [])
        self.assertEqual(resultat["errors"], 0, resultat["problems"])

    def test_formules_a_corriger_et_coherence(self):
        from . import coherence as CO
        from . import formules as FO

        S.enregistrer(self.contrib, self.c, self.pol, self.e1, TEXTE, False, "")
        CO.controler(self.c)
        self.assertFalse(self.c.alertes.filter(kpi=self.pol).exists())
        self.assertEqual(FO.nombre(), 0)  # « Formules à corriger » : rien
        self.assertEqual(self.client.get(reverse("collecte:admin_formules")).status_code, 200)


class ExportsEtImportsTests(TexteRedigeBase):
    def setUp(self):
        super().setUp()
        S.enregistrer(self.contrib, self.c, self.pol, self.e1, "- point un\n- point deux", False, "")

    def test_base_de_donnees_et_csv(self):
        p = E.Parametres.depuis({"presentation": "base", "exercices": ["courant"]})
        wb = classeur(E.exporter(self.admin, p))
        lignes = list(wb["Valeurs"].iter_rows(values_only=True))
        tete = lignes[0]
        pol = next(l for l in lignes[1:] if l[tete.index("ID KPI")] == "POL")
        self.assertEqual(pol[tete.index("Valeur")], "- point un\n- point deux")  # Markdown brut
        p = E.Parametres.depuis({"presentation": "base", "format": "csv", "csv": "fr", "exercices": ["courant"]})
        texte = E.exporter(self.admin, p).content.decode("utf-8-sig")
        lignes = list(csv.reader(io.StringIO(texte), delimiter=";"))
        tete = lignes[0]
        pol = next(l for l in lignes[1:] if l[tete.index("ID KPI")] == "POL")
        self.assertEqual(pol[tete.index("Valeur")], "'- point un\n- point deux")  # entre guillemets ; « - » neutralisé
        self.assertIn('"\'- point un\r\n- point deux"', texte.replace("\n- point deux", "\r\n- point deux"))

    def test_tableau_et_revue(self):
        """La réponse rédigée part dans l'onglet « Réponses rédigées », en texte simple et en pleine
        largeur ; elle n'élargit plus les colonnes chiffrées (le tableau garde ses colonnes de 14, la revue un extrait)."""
        for presentation in ("tableau", "revue"):
            with self.subTest(presentation=presentation):
                p = E.Parametres.depuis({"presentation": presentation, "exercices": ["courant"],
                                         "contenus": ["valide", "brouillon", "a_saisir"]})
                wb = classeur(E.exporter(self.admin, p))
                ws = wb["Réponses rédigées"]
                cell = next(c for row in ws.iter_rows() for c in row if c.value == "• point un\n• point deux")
                self.assertTrue(cell.alignment.wrap_text)
                self.assertEqual(cell.data_type, "s")
                self.assertGreaterEqual(ws.column_dimensions[cell.column_letter].width, 60)
                textes = [c.value for row in wb.worksheets[1].iter_rows() for c in row if isinstance(c.value, str)]
                self.assertNotIn("- point un\n- point deux", textes)  # jamais le Markdown brut dans un fichier à lire
                if presentation == "revue":  # un extrait sur une ligne, colonnes de largeur normale
                    ws = wb["2026"]
                    self.assertIn("point un point deux", [c.value for row in ws.iter_rows() for c in row])
                    self.assertLess(max(ws.column_dimensions[l].width for l in "CE"), 20)

    def test_formules_excel_texte_reste_texte(self):
        p = E.Parametres.depuis({"presentation": "tableau", "exercices": ["courant"], "valeurs": "formules"})
        wb = classeur(E.exporter(self.admin, p))
        valeurs = [c.value for row in wb["Réponses rédigées"].iter_rows() for c in row]
        self.assertIn("• point un\n• point deux", valeurs)

    def test_fichier_a_remplir_et_reimport(self):
        wb = classeur(I.modele(self.contrib, self.c, I.lignes_modele(self.contrib, self.c)))
        ws = wb["Saisie"]
        n = next(r for r in range(1, 15) if ws.cell(r, 2).value == "ID KPI")
        tete = [c.value for c in ws[n]]
        ligne = next(r for r in range(n + 1, ws.max_row + 1) if ws.cell(r, 2).value == "POL")
        valeur = ws.cell(ligne, tete.index("Valeur") + 1)
        self.assertEqual(valeur.value, "- point un\n- point deux")
        self.assertTrue(valeur.alignment.wrap_text)
        self.assertFalse(valeur.protection.locked)
        regles = [dv for dv in ws.data_validations.dataValidation if valeur.coordinate in dv.sqref]
        self.assertEqual([(dv.type, dv.formula1) for dv in regles], [("textLength", str(MD.TEXTE_MAX))])
        valeur.value = "# Nouveau\n\nTexte **modifié**"
        flux = io.BytesIO()
        wb.save(flux)
        a, n, _ = I.appliquer(self.contrib, SimpleUploadedFile("rempli.xlsx", flux.getvalue()), "rempli.xlsx")
        self.assertEqual(Reponse.objects.get(kpi=self.pol, organisation=self.e1, periode=self.c.periode).texte, "# Nouveau\n\nTexte **modifié**")
        # trop long : refus clair
        valeur.value = "a" * (MD.TEXTE_MAX + 1)
        flux = io.BytesIO()
        wb.save(flux)
        a = I.analyser(self.contrib, SimpleUploadedFile("long.xlsx", flux.getvalue()))
        pol = next(l for l in a.lignes if l.kpi_id == "POL")
        self.assertIn("Texte trop long", pol.motif)

    def test_configuration_et_paquet(self):
        from . import configuration as C
        from . import paquets as PQ

        wb = classeur(C.exporter())
        lignes = [r for r in wb["Types de réponse"].iter_rows(min_row=2, values_only=True)]
        self.assertTrue(any("TexteRedige" in r and "Texte rédigé" in r for r in lignes), lignes)
        flux = io.BytesIO()
        wb.save(flux)
        a = C.analyser(SimpleUploadedFile("config.xlsx", flux.getvalue()))
        self.assertFalse(a.erreur)
        self.assertEqual({c.action for cs in a.onglets.values() for c in cs}, {"inchange"})  # relu à l'identique
        p = PQ.extraire(self.rse)
        self.assertIn("texte", {t["format"] for t in p.types_reponse})


class VisualisationTests(TexteRedigeBase):
    def test_exclu_des_visuels(self):
        S.enregistrer(self.contrib, self.c, self.pol, self.e1, TEXTE, False, "")
        rep = self.client.get(reverse("collecte:visu_catalogue"))
        donnees = json.loads(rep.content)
        self.assertNotIn("POL", [k["code"] for k in donnees["kpis"]])
        self.assertEqual(donnees["rediges"], 1)
        from . import visuels as VS

        d = VS.donnees(self.admin, {}, [{"id": "a", "type": "chiffre", "kpis": ["POL"], "largeur": 3, "hauteur": "m", "filtres": {},
                                         "options": {}, "titre": "", "source": "", "axe": "", "series": ""}])
        v = d["visuels"]["a"]
        self.assertEqual(v["etat"], "indisponible")
        self.assertIn("Réponse rédigée", v["message"])
        rep = self.client.get(reverse("collecte:visu_kpi", args=["POL"]))
        self.assertEqual(rep.status_code, 200)

    def test_tableau_de_bord_compte_la_case(self):
        self.client.force_login(self.contrib)
        url = reverse("collecte:tableau_de_bord") + f"?campagne={self.c.pk}"
        avant = dict(self.client.get(url).context["avancement"])[self.c]
        S.enregistrer(self.contrib, self.c, self.pol, self.e1, TEXTE, False, "")
        S.valider(self.contrib, self.c, self.pol, self.e1)
        apres = dict(self.client.get(url).context["avancement"])[self.c]
        self.assertEqual((apres.total, apres.valide), (avant.total, avant.valide + 1))
