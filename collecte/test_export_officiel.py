"""Export vers le classeur officiel VS de l'EFRAG (modèle numérique 2.0.0) : moteur qui remplit le classeur sans rien en
perdre, correspondance KPI → cellule vérifiée sur le classeur livré, installation des modèles VS_BASE et VS_COMPLET,
export d'une période (valeurs, cases, listes, sites, pays, zones sensibles, NACE, formules remplacées), rapport, page,
et recalcul par LibreOffice quand il est installé (contrôles du classeur : OK, totaux)."""
import datetime
import io
import shutil
import subprocess
import tempfile
import warnings
import zipfile
from decimal import Decimal
from pathlib import Path

import openpyxl
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from openpyxl.utils import column_index_from_string, range_boundaries
from openpyxl.utils.cell import coordinate_from_string

from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import formats as FO
from referentiel.bibliotheque.definitions import vs_base, vs_complet
from referentiel.bibliotheque.formats import vs_efrag as V
from referentiel.models import KPI, Organisation, Utilisateur

from . import classeur_officiel as K
from . import export_officiel as X
from . import paquets as P
from .aides_tests.paquets import vider
from .models import Campagne, Journal, Periode, Reponse

MODELE = FO.DOSSIER / V.FICHIER


def classeur(donnees, valeurs=False):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(io.BytesIO(donnees), data_only=valeurs)


class MoteurTests(SimpleTestCase):
    """collecte.classeur_officiel : seules les cellules demandées changent ; le reste du fichier est identique."""

    def test_ecriture_sans_perte(self):
        ecritures = {(V.GI, "D3"): "Exemple & fils <SA>", (V.SOC, "D18"): 12, (V.ENV, "D22"): Decimal("12.50"),
                     (V.GOV, "H5"): True, (V.GI, "E517"): "Ligne 1\nLigne 2", (V.GI, "E393"): None}
        sortie = K.remplir(MODELE, ecritures)
        avant, apres = zipfile.ZipFile(MODELE), zipfile.ZipFile(io.BytesIO(sortie))
        modifiees = {i.filename for i in avant.infolist() if avant.read(i.filename) != apres.read(i.filename)}
        parties = K.parties_des_onglets(avant)
        self.assertEqual(modifiees, {"xl/workbook.xml"} | {parties[o] for o in (V.GI, V.SOC, V.ENV, V.GOV)})
        self.assertIn('fullCalcOnLoad="1"', apres.read("xl/workbook.xml").decode())
        wb = classeur(sortie)
        self.assertEqual(wb[V.GI]["D3"].value, "Exemple & fils <SA>")
        self.assertEqual((wb[V.SOC]["D18"].value, wb[V.ENV]["D22"].value, wb[V.GOV]["H5"].value), (12, 12.5, True))
        self.assertEqual(wb[V.GI]["E517"].value, "Ligne 1\nLigne 2")

    def test_formules_protegees(self):
        with self.assertRaisesMessage(K.CelluleInterdite, "D25"):
            K.remplir(MODELE, {(V.ENV, "D25"): 1})
        with self.assertRaises(KeyError):
            K.remplir(MODELE, {("Onglet inconnu", "A1"): 1})
        # formule remplacée exprès : la valeur prend sa place, la chaîne de calcul est retirée (Excel la reconstruit)
        sortie = zipfile.ZipFile(io.BytesIO(K.remplir(MODELE, {(V.ENV, "J14"): 25}, {(V.ENV, "J14")})))
        self.assertNotIn(K.CHAINE_CALCUL, sortie.namelist())
        self.assertNotIn("calcChain", sortie.read("[Content_Types].xml").decode() + sortie.read("xl/_rels/workbook.xml.rels").decode())
        self.assertEqual(classeur(K.remplir(MODELE, {(V.ENV, "J14"): 25}, {(V.ENV, "J14")}))[V.ENV]["J14"].value, 25)

    def test_cellule_et_ligne_absentes(self):
        xml = ('<worksheet><sheetData><row r="2" spans="1:3"><c r="A2" s="1"/><c r="C2"><v>3</v></c></row>'
               '<row r="5"><c r="B5"/></row></sheetData></worksheet>')
        xml, _ = K._ecrire_cellule(xml, "B2", 7, "x")
        self.assertIn('<c r="A2" s="1"/><c r="B2"><v>7</v></c><c r="C2"><v>3</v></c>', xml)
        xml, _ = K._ecrire_cellule(xml, "A4", "texte", "x")
        self.assertIn('</row><row r="4"><c r="A4" t="inlineStr"><is><t xml:space="preserve">texte</t></is></c></row><row r="5">', xml)
        xml, _ = K._ecrire_cellule(xml, "Z9", True, "x")
        self.assertTrue(xml.endswith('<row r="9"><c r="Z9" t="b"><v>1</v></c></row></sheetData></worksheet>'))


class CorrespondanceTests(SimpleTestCase):
    """Chaque cellule visée est une cellule de saisie du classeur livré (ou une formule remplacée exprès), et porte le nom
    Excel attendu : une nouvelle version du classeur qui déplace une ligne fait échouer ce test."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cls.wb = openpyxl.load_workbook(MODELE)
        cls.noms = {}
        for n, d in cls.wb.defined_names.items():
            for f, p in d.destinations:
                p = p.replace("$", "")
                cls.noms.setdefault(n, []).append((f, range_boundaries(p if ":" in p else p + ":" + p)))
        cls.codes_modeles = {c for m in (vs_base, vs_complet) for c, *_ in C.elements(m.SOCLE)}  # KPI placés dans un modèle VS

    def porte(self, nom, onglet, cellule):
        col, ligne = coordinate_from_string(cellule)
        c = column_index_from_string(col)
        return any(f == onglet and b[0] <= c <= b[2] and b[1] <= ligne <= b[3] for f, b in self.noms.get(nom, []))

    def test_version_du_classeur(self):
        self.assertEqual((self.wb["Introduction"]["C1"].value, self.wb["Introduction"]["C10"].value), (V.VERSION, V.TAXONOMIE))
        self.assertIn("MIT License", self.wb["Licence"]["A1"].value)

    def test_cellules(self):
        for cel in V.CELLULES:
            with self.subTest(cellule=f"{cel.onglet}!{cel.cellule}"):
                x = self.wb[cel.onglet][cel.cellule]
                v = x.value.text if hasattr(x.value, "text") else x.value
                formule = isinstance(v, str) and v.startswith("=")
                self.assertNotEqual(type(x).__name__, "MergedCell")
                self.assertEqual(formule, cel.remplace)
                if not cel.remplace:
                    self.assertTrue(not x.protection.locked or cel.verrouillee)
                if cel.nom:
                    self.assertTrue(self.porte(cel.nom, cel.onglet, cel.cellule), cel.nom)
                for code in cel.codes:
                    self.assertIn(code, self.codes_modeles)

    def test_tableaux(self):
        for b in V.BLOCS:
            for col in b.colonnes:
                for ligne in b.lignes:
                    x = self.wb[b.onglet][f"{col}{ligne}"]
                    formule = isinstance(x.value, str) and x.value.startswith("=")
                    self.assertEqual(formule, col in b.remplace, f"{b.onglet}!{col}{ligne}")  # GPS : formule remplacée exprès
                    self.assertTrue(formule or not x.protection.locked, f"{b.onglet}!{col}{ligne}")
            if b.nom:
                self.assertTrue(self.porte(b.nom, b.onglet, f"{b.colonnes[0]}{b.lignes[0]}"), b.nom)

    def test_listes_identiques_au_classeur(self):
        """Les valeurs anglaises des listes des modèles VS sont exactement celles du classeur (pays, statut du plan…)."""
        el = self.wb["Enumeration Lists"]
        colonnes = {"VS-PAYS": "C", "VS-IDENTIFIANT": "AB", "VS-FORME-JURIDIQUE": "J", "VS-STATUT-PLAN": "S"}
        for code, col in colonnes.items():
            valeurs = [el[f"{col}{r}"].value for r in range(2, 2 + len(V.VALEURS[code]))]
            self.assertEqual(valeurs, list(V.VALEURS[code]), code)


class ExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        vider()
        for f in ("vs_base.json", "vs_complet.json"):
            a = P.analyser(P.fourni(f).paquet, source=f, fourni=True)
            assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (f, a.erreur, a.compteurs)
            P.appliquer(None, a)
        cls.admin = Utilisateur.objects.create_user("admin", "admin@exemple.test", "x", role=Utilisateur.Role.ADMIN)
        groupe = Organisation.objects.create(nom="Exemple SA", niveau_id="Group")
        cls.groupe = groupe
        fr = Organisation.objects.create(nom="France", niveau_id="Country", parent=groupe)
        es = Organisation.objects.create(nom="Espagne", niveau_id="Country", parent=groupe)
        ent_fr = Organisation.objects.create(nom="Exemple France", niveau_id="Entity", parent=fr)
        ent_es = Organisation.objects.create(nom="Exemple Iberia", niveau_id="Entity", parent=es)
        cls.lyon = Organisation.objects.create(nom="Lyon", niveau_id="Site", parent=ent_fr)
        cls.paris = Organisation.objects.create(nom="Paris", niveau_id="Site", parent=ent_fr)
        cls.madrid = Organisation.objects.create(nom="Madrid", niveau_id="Site", parent=ent_es)
        cls.p2025 = Periode.objects.create(type="annee", debut=datetime.date(2025, 1, 1), fin=datetime.date(2025, 12, 31), libelle="2025")
        cls.p2026 = Periode.objects.create(type="annee", debut=datetime.date(2026, 1, 1), fin=datetime.date(2026, 12, 31), libelle="2026")
        from referentiel.models import Referentiel

        for ref in Referentiel.objects.all():
            Campagne.objects.create(referentiel=ref, periode=cls.p2026, exercice=2026, statut=Campagne.Statut.CLOTUREE)

        def r(org, code, valeur=None, texte="", periode=None, statut=Reponse.Statut.VALIDE):
            Reponse.objects.update_or_create(periode=periode or cls.p2026, kpi_id=code, organisation=org, defaults={
                "valeur": None if valeur is None else Decimal(str(valeur)), "texte": texte, "statut": statut})
        g = groupe
        for code, valeur in (("NRJ-TOTAL-MWH", "1234.5"), ("NRJ-ELEC", 800000), ("NRJ-ELEC-REN", 300000), ("NRJ-ELEC-AUTO", 20000),
                             ("NRJ-COMBUSTIBLES", "250.25"), ("GES-S1", "120.5"), ("GES-S2-LB", 30), ("GES-S3-ACHATS", 900),
                             ("ECO-CA", "12.5"), ("ECO-TOTAL-BILAN", 8000000), ("SOC-EFFECTIF", 120), ("SOC-EFF-CDI", 100),
                             ("SOC-EFF-HOMMES", 70), ("SOC-EFF-FEMMES", 50), ("SOC-ACCIDENTS-ENREG", 2), ("SOC-DECES", 0),
                             ("SOC-SAL-CONVENTION", 120), ("SOC-HEURES-FORM", 2400), ("EAU-PRELEVEMENT", 5000),
                             ("DEC-TOTAL", 40), ("DEC-DANGEREUX", 4), ("DEC-RECYCLES", 20), ("DEC-REEMPLOI", 2),
                             ("GOV-CORRUPTION", 0), ("GOV-AMENDES", 0), ("SOC-DEPARTS-CDI", 12)):
            r(g, code, valeur)
        r(g, "SOC-EFFECTIF", 110, periode=cls.p2025)
        for code, texte in (("GEN-IDENT-TYPE", "LEI"), ("GEN-IDENT", "EXEMPLIA000000000049"), ("GEN-CONFORMITE", "Rapport **conforme** à la norme volontaire."),
                            ("GEN-PERIMETRE", "Rapport établi sur une base consolidée"), ("GEN-FORME-JURIDIQUE", "Société à responsabilité limitée de droit privé"),
                            ("GEN-NACE", "47.91\n46.42\n99.99"), ("GEN-PAYS-PRINCIPAL", "France"), ("GEN-CERTIF", "Oui"),
                            ("GEN-CERTIF-DESC", "- ISO 14001\n- Label B"), ("GOV-B2-PRATIQUES", "Oui"), ("GOV-B2-CLIMAT", "Oui"),
                            ("GOV-B2-PUBLIC", "Non"), ("ECO-CIRCULAIRE", "Oui"), ("BIO-SITES", "Oui"), ("POL-DECLARATION", "Non"),
                            ("SOC-SALAIRE-MINIMUM", "Oui"), ("GES-PLAN-STATUT", "Un plan de transition a déjà été adopté"),
                            ("SOC-CODE-CONDUITE", "Oui"), ("SOC-CODE-ENFANTS", "Oui"), ("STR-PRODUITS", "Vente en ligne.")):
            r(g, code, texte=texte)
        # réponses en tableau (polluants et déchets par site, le reste au niveau du groupe)
        from referentiel.bibliotheque.definitions._vs_listes import DECHETS, INFOS_INCHANGEES, OMISSIONS, POLLUANTS

        from . import tableaux as T

        def tab(org, code, texte):
            r(org, code, texte=T.lire(texte, KPI.objects.get(code=code).type_reponse))
        cls.polluant, cls.dangereux = POLLUANTS[5], next(d for d in DECHETS if " - Hazardous - " in d)
        cls.non_dangereux = next(d for d in DECHETS if " - Non-Hazardous - " in d)
        tab(cls.lyon, "POL-REJETS", f"| {cls.polluant} | 10 | | |")
        tab(cls.madrid, "POL-REJETS", f"| {cls.polluant} | 5 | 2 | |")
        tab(cls.madrid, "POL-REJETS-AUTRES", "| Polluant maison | | | 0,5 |")
        tab(cls.lyon, "DEC-PAR-CODE", f"| {cls.dangereux} | 2 | 1 | |")
        tab(cls.paris, "DEC-PAR-CODE", f"| {cls.non_dangereux} | 3 | | 0,3 |")
        tab(g, "GEN-FILIALES", "| Exemple France | 1 rue A, Lyon |\n| Exemple Iberia | Calle B, Madrid |")
        tab(g, "GES-S3-CIBLES", "| 1. Biens et services achetés | 900 | 500 |")
        tab(g, "ECO-MATIERES", "| Carton | 12 | tonnes (t) |")
        tab(g, "GEN-INFOS-INCHANGEES", f"| {INFOS_INCHANGEES[5][1]} |")
        cls.info_inchangee = INFOS_INCHANGEES[5]
        r(g, "GEN-RAPPORT-LIEN", texte="https://exemple.test/rapport-2025")
        r(g, "NRJ-COMB-REN", 10)
        r(g, "GES-S1-AUTRES", 4.5)
        tab(g, "GEN-OMISSIONS", f"| {OMISSIONS[1][2]} |\n| {OMISSIONS[-1][2]} |")
        r(g, "GES-PLAN-MOIS", 6)
        r(cls.lyon, "GEN-SITE-GPS", texte="45.76404, 4.83566")
        r(cls.paris, "GEN-SITE-GPS", texte="pas des coordonnées")
        for site, (adresse, cp, ville, pays, effectif, zone) in {
                cls.lyon: ("12 / rue de la Paix", "69001", "Lyon", "France", 60, "À proximité d'une zone sensible pour la biodiversité"),
                cls.paris: ("3 avenue Foch", "75016", "Paris", "France", 40, ""),
                cls.madrid: ("Calle Mayor 1", "28013", "Madrid", "Spain", 20, "Dans une zone sensible pour la biodiversité")}.items():
            r(site, "GEN-SITE-ADRESSE", texte=adresse)
            r(site, "GEN-SITE-CP", texte=cp)
            r(site, "GEN-SITE-VILLE", texte=ville)
            r(site, "GEN-SITE-PAYS", texte=pays)
            r(site, "SOC-EFFECTIF", effectif)
            if zone:
                r(site, "BIO-SITE-ZONE", texte=zone)
                r(site, "BIO-SITE-ZONE-NOM", texte=f"Zone {site.nom}")

    def exporter(self, langue="fr"):
        donnees, rapport = X.exporter(V.CODE, self.groupe, self.p2026, langue, self.admin)
        return donnees, rapport, classeur(donnees)

    def test_installation_des_modeles(self):
        niveaux = dict(KPI.objects.values_list("code", "granularite_id"))
        for code, attendu in (("GEN-IDENT", "Group"), ("GOV-B2-CLIMAT", "Group"), ("STR-PRODUITS", "Group"), ("GEN-SITE-ADRESSE", "Site"),
                              ("BIO-SITE-ZONE", "Site"), ("SOC-EFF-HOMMES", "Site"), ("CONV-GAZOLE", "Group"), ("NRJ-TOTAL-MWH", "Site")):
            self.assertEqual(niveaux[code], attendu, code)
        self.assertTrue(KPI.objects.get(code="GEN-CONFORMITE").est_texte)
        self.assertEqual(len(KPI.objects.get(code="GEN-SITE-PAYS").type_reponse.valeurs), 256)

    def test_valeurs_ecrites(self):
        Reponse.objects.filter(kpi_id="DEC-PAR-CODE").delete()  # sans détail par code : les totaux de l'outil sont écrits
        _, rapport, wb = self.exporter()
        gi, env, soc, gov = (wb[o] for o in (V.GI, V.ENV, V.SOC, V.GOV))
        self.assertEqual(wb[V.LANGUE]["G7"].value, V.LANGUES["fr"])
        self.assertEqual((gi["D3"].value, gi["D4"].value, gi["E4"].value, gi["D5"].value), ("Exemple SA", "LEI", "EXEMPLIA000000000049", "EUR"))
        self.assertEqual([gi[c].value for c in ("D6", "D7", "D8", "D10", "D11", "D12")], ["2026", "1", "1", "2026", "12", "31"])
        self.assertEqual(gi["E125"].value, V.OPTION_B)  # module complet installé et actif
        self.assertEqual(gi["E126"].value, "Rapport conforme à la norme volontaire.")  # Markdown → texte
        self.assertEqual((gi["E175"].value, gi["E176"].value, gi["E283"].value),
                         ("Sustainability report prepared on a consolidated basis", "private limited liability undertaking", "France"))
        self.assertEqual((gi["E278"].value, gi["E279"].value, gi["E280"].value), (8000000, 12500000, 120))
        self.assertTrue(gi["E392"].value)
        self.assertEqual(gi["E393"].value, "• ISO 14001\n• Label B")
        self.assertEqual((gi["C508"].value, gi["D508"].value, gi["E508"].value, gi["N508"].value), (True, True, False, "False"))
        self.assertTrue(gi["E178"].value.startswith("NACE G - 47.91 ") and gi["E179"].value.startswith("NACE G - 46.42 "))
        self.assertIn("Code NACE « 99.99 » absent de la liste officielle", " ".join(rapport.messages))
        # énergie en MWh ; combustibles écrits à la place du lien vers le convertisseur
        self.assertEqual((env["G5"].value, env["G12"].value, env["J12"].value, env["G13"].value), (1234.5, 300, 500, 20))
        self.assertEqual((env["G14"].value, env["J14"].value, env["G10"].value), (10, 250.25, True))
        self.assertEqual((env["D22"].value, env["D23"].value, env["D30"].value, env["G29"].value), (125, 30, 900, True))
        self.assertEqual((env["D309"].value, env["G189"].value, env["G68"].value), ("YES", True, False))
        self.assertEqual((env["J416"].value, env["J417"].value, env["J422"].value, env["J423"].value, env["G416"].value),
                         (4, 36, 0.5, 0.05, "metric tonnes (t)"))
        self.assertEqual(env["D57"].value, "A transition plan has already been adopted")
        # effectifs, rotation (début = fin de l'exercice précédent), sécurité, corruption sans condamnation
        self.assertEqual((soc["D10"].value, soc["D18"].value, soc["D19"].value, soc["D133"].value, soc["D136"].value), (100, 70, 50, 2, "500"))
        self.assertEqual((soc["D158"].value, soc["D159"].value, soc["D160"].value), (12, 110, 120))
        self.assertEqual((soc["D142"].value, soc["D169"].value, soc["D171"].value), ("YES", "YES", True))
        self.assertEqual((gov["H5"].value, gov["H6"].value, gov["H7"].value), (False, None, None))
        self.assertEqual(gi["E523"].value, "Vente en ligne.")

    def test_sites_pays_zones(self):
        _, _, wb = self.exporter()
        gi, env, soc = wb[V.GI], wb[V.ENV], wb[V.SOC]
        # sites dans l'ordre de l'arbre (Espagne puis France), numérotés comme dans le classeur
        self.assertEqual([[gi[f"{c}{ligne}"].value for c in "CDEFG"] for ligne in (402, 403, 404)],
                         [[1, "Calle Mayor 1", "28013", "Madrid", "Spain"], [2, "12 / rue de la Paix", "69001", "Lyon", "France"],
                          [3, "3 avenue Foch", "75016", "Paris", "France"]])
        self.assertTrue(soc["E27"].value)
        self.assertEqual([(soc[f"C{ligne}"].value, soc[f"E{ligne}"].value) for ligne in (29, 30)], [("France", 100), ("Spain", 20)])
        self.assertEqual([[env[f"{c}{ligne}"].value for c in "CGJK"] for ligne in (191, 192)],
                         [[1, "Zone Madrid", True, False], [2, "Zone Lyon", False, True]])

    def test_tableaux_ecrits(self):
        _, rapport, wb = self.exporter()
        gi, env = wb[V.GI], wb[V.ENV]
        # polluants : même polluant sur deux sites additionné ; unité des tableaux en kg
        self.assertEqual([env[c].value for c in ("C72", "D74", "G74", "J74", "D75")], ["kilograms (kg)", self.polluant, 15, 2, None])
        self.assertEqual([env[c].value for c in ("D174", "K174")], ["Polluant maison", 0.5])
        # déchets par code : valeur exacte de la liste officielle (avec ses espaces), masse en kg, parts en fraction ; totaux
        # laissés au classeur (pas de valeur écrite à la place de ses formules)
        self.assertEqual(env["D316"].value.strip(), self.dangereux)
        self.assertTrue(env["D316"].value.startswith(" "))
        self.assertEqual([env[c].value for c in ("G316", "J316", "K316", "L316", "J317", "K317", "L317", "G416")],
                         ["kilograms (kg)", 2000, 0.5, 0, 3000, 0, 0.1, "kilograms (kg)"])
        self.assertTrue(str(env["J416"].value).startswith("="))
        self.assertNotIn("B7", dict(rapport.manquantes))  # totaux calculés par le classeur : pas « manquants »
        self.assertEqual([gi[c].value for c in ("D288", "E288", "D289")], ["Exemple France", "1 rue A, Lyon", "Exemple Iberia"])
        self.assertEqual((env["G30"].value, env["J30"].value), (900, 500))
        self.assertEqual([env[c].value for c in ("D432", "G432", "J432", "G430")], ["Carton", 12, "metric tonnes (t)", True])
        self.assertEqual((gi["E21"].value, gi["E22"].value, gi["E122"].value), (True, self.info_inchangee[1], "https://exemple.test/rapport-2025"))
        self.assertEqual((env["J13"].value, env["I60"].value), (None, "6"))  # J13 vide : combustible déjà compté
        self.assertEqual(env["J423"].value, 0.06)  # part réemployée tirée du tableau par code (0,3 t sur 5 t)
        # informations omises : la case de chaque rubrique cochée dans le sommaire
        toc = wb[V.SOMMAIRE]
        self.assertEqual((toc["D14"].value, toc["D65"].value, toc["D13"].value), (True, True, False))
        # GPS : « longitude,latitude » à la place de la formule du classeur ; coordonnées illisibles dites
        self.assertEqual(gi["H403"].value, "4.83566,45.76404")
        self.assertIn("Paris : coordonnées GPS « pas des coordonnées » non reprises", " ".join(rapport.messages))
        # en anglais, la rubrique inchangée s'écrit dans la langue d'affichage du classeur
        _, _, wb_en = self.exporter("en")
        self.assertEqual(wb_en[V.GI]["E22"].value, self.info_inchangee[0])

    def test_rapport_et_journal(self):
        Reponse.objects.filter(kpi_id="GES-S1", organisation=self.groupe).update(statut=Reponse.Statut.BROUILLON)
        _, rapport, _ = self.exporter("en")
        manquants = {m: noms for m, noms in rapport.manquantes}
        self.assertIn("Description des pratiques, politiques et initiatives", " ".join(manquants.get("C2", [])))  # noms dans la langue de l'interface
        self.assertNotIn("B3", manquants)  # énergie et émissions données
        self.assertIn("Scope 1 : combustion et émissions fugitives (sous-total)", rapport.non_validees)
        self.assertTrue(rapport.option_b)
        self.assertTrue(Journal.objects.filter(action="export_officiel", objet_id=str(self.groupe.pk)).exists())

    def test_option_a_sans_module_complet(self):
        from referentiel.models import Referentiel

        Referentiel.objects.filter(identifiant=X.identifiant_modele("VS_COMPLET")).update(actif=False)
        _, rapport, wb = self.exporter()
        self.assertEqual(wb[V.GI]["E125"].value, V.OPTION_A)
        self.assertFalse(any(m.startswith("C") for m, _ in rapport.manquantes))

    def test_page_export(self):
        self.client.force_login(self.admin)
        url = reverse("collecte:export_officiel")
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Classeur officiel de l&#x27;EFRAG")
        choix = {"format": V.CODE, "organisation": self.groupe.pk, "periode": self.p2026.pk, "langue": "fr"}
        verif = self.client.post(url, {**choix, "action": "verifier"})
        self.assertContains(verif, "Ce que contiendra le classeur")
        self.assertContains(verif, "Modules de base et complet (option B).")
        rep = self.client.post(url, {**choix, "action": "telecharger"})
        self.assertEqual(rep.status_code, 200)
        self.assertEqual(rep["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("vs_efrag_exemple-sa_2026_", rep["Content-Disposition"])
        self.assertEqual(classeur(b"".join(rep.streaming_content) if rep.streaming else rep.content)[V.GI]["D3"].value, "Exemple SA")
        contributeur = Utilisateur.objects.create_user("c", "c@exemple.test", "x", role=Utilisateur.Role.CONTRIBUTEUR)
        self.client.force_login(contributeur)
        self.assertIn(self.client.get(url).status_code, (302, 403))

    def test_recalcul_libreoffice(self):
        """Le classeur rempli, recalculé par LibreOffice, donne les totaux et les contrôles attendus (si LibreOffice est là)."""
        soffice = shutil.which("soffice")
        if not soffice:
            self.skipTest("LibreOffice absent")
        donnees, _, _ = self.exporter()
        with tempfile.TemporaryDirectory() as d:
            profil = Path(d) / "profil" / "user"
            profil.mkdir(parents=True)
            (profil / "registrymodifications.xcu").write_text(
                '<?xml version="1.0" encoding="UTF-8"?><oor:items xmlns:oor="http://openoffice.org/2001/registry" '
                'xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                '<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" oor:op="fuse">'
                '<value>0</value></prop></item></oor:items>', encoding="utf-8")
            (Path(d) / "export.xlsx").write_bytes(donnees)
            (Path(d) / "sortie").mkdir()
            subprocess.run([soffice, f"-env:UserInstallation=file://{d}/profil", "--headless", "--convert-to", "xlsx", "--outdir",
                            f"{d}/sortie", f"{d}/export.xlsx"], check=True, capture_output=True, timeout=240)
            wb = classeur((Path(d) / "sortie" / "export.xlsx").read_bytes(), valeurs=True)
        gi, env, soc, gov = (wb[o] for o in (V.GI, V.ENV, V.SOC, V.GOV))
        self.assertEqual((gi["F3"].value, gi["F4"].value, gi["F5"].value), ("OK", "OK", "OK"))
        self.assertEqual((env["D25"].value, env["K12"].value, env["K14"].value), (155, 800, 260.25))
        self.assertEqual(env["L12"].value, "OK")  # détail de l'énergie cohérent avec le total
        self.assertEqual(env["J423"].value, 0.06)  # part réemployée écrite à la place de la formule « 1 − J422 »
        self.assertEqual(wb[V.SOMMAIRE]["C14"].value, "INFORMATIONS CLASSIFIÉES OU SENSIBLES")  # filiales omises (B1 · 27(b))
        self.assertAlmostEqual(soc["D148"].value, 1.0)  # couverture par une convention : 120 / 120
        self.assertAlmostEqual(soc["D155"].value, 20.0)  # heures de formation par salarié : 2 400 / 120
        self.assertAlmostEqual(soc["D161"].value, 12 / 115)  # rotation : 12 / moyenne (110 + 120) / 2
        # totaux des déchets calculés par le classeur à partir du tableau par code (en kg : voir la cellule G416)
        self.assertEqual((env["J416"].value, env["J417"].value, env["J418"].value), (2000, 3000, 5000))
