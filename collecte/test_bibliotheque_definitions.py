"""Modèles de la bibliothèque écrits dans referentiel/bibliotheque/definitions/ : contrôle avant génération (règles de la
fiche KPI, textes bilingues, sources des formules, couverture de la norme), paquet bilingue avec liste de choix et texte
rédigé, niveau conseillé « haut », installation dans une base vide, découverte des fichiers."""
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TestCase

from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import definitions as D
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.outils import kpi
from referentiel.models import KPI, Description, ElementReferentiel, Referentiel

from . import paquets as P
from .aides_tests.paquets import vider

LISTE = ("TST-REGIME", ("Régime de travail", "Working arrangement"), "liste",
         {"fr": ["Temps plein", "Temps partiel"], "en": ["Full time", "Part time"]})
KPIS = dict([
    kpi("TST-EFFECTIF", "Effectif test", "Test headcount", "salariés", description=("Salariés en fin de période.", "Employees at period end."),
        source=("Paie.", "Payroll.")),
    kpi("TST-FEMMES", "Femmes test", "Test women", "salariés", description=("Femmes en fin de période.", "Women at period end."),
        source=("Paie.", "Payroll.")),
    kpi("TST-PART", "Part des femmes test", "Test share of women", "", "Formule", "Calculé", "Pourcentage",
        "[TST-FEMMES] / [TST-EFFECTIF]", description=("Femmes ÷ effectif.", "Women ÷ headcount.")),
    kpi("TST-POLITIQUE", "Politique test", "Test policy", "", "Décompte", reponse="OuiNon", niveau="haut",
        description=("Une politique existe-t-elle ?", "Is there a policy?")),
    kpi("TST-PRATIQUES", "Pratiques test", "Test practices", "", "Aucune", reponse="Texte", niveau="haut",
        description=("Décrire les pratiques.", "Describe the practices.")),
    kpi("TST-REGIME", "Régime test", "Test arrangement", "", "Décompte", reponse="TST-REGIME",
        description=("Régime principal.", "Main arrangement."), source=("SIRH.", "HRIS.")),
])
REGLES = {"Femmes test ≤ effectif test": ("[TST-FEMMES]", "<=", "[TST-EFFECTIF]", ("Les femmes font partie de l'effectif.",
                                                                                    "Women are part of the headcount."), "Test women ≤ test headcount")}
SOCLE = {
    "code": "TEST_DEF", "fichier": "test_def.json", "couleur": "#336699", "version": "1.0", "date": "2026-11-13", "module": "test_def",
    "source": {"titre": "Norme d'essai", "editeur": "Essai", "version": "2026", "url": "https://exemple.test", "consulte_le": "2026-11-13",
               "licence": "Paraphrase."},
    "thematique": ("Essai", "Test"), "nom": ("Modèle d'essai", "Test template"), "description": ("Pour les tests.", "For tests."),
    "arbre": [("SOC", "Social", "Social", [("TST-EFFECTIF", "T1 §1"), ("TST-FEMMES", "T1 §2"), ("TST-PART", "T1 §3"),
                                           ("TST-REGIME", "T1 §4", False)]),
              ("GOUV", "Gouvernance", "Governance", [("TST-POLITIQUE", "T2 §1"), ("TST-PRATIQUES", "T2 §2")])],
    "regles": ["Femmes test ≤ effectif test"],
}
COUVERTURE = """reference,requirement,datapoint,status,kpi_codes,note
T1 §1,mandatory,Headcount,covered,TST-EFFECTIF,
T1 §2,mandatory,Women and share of women,covered,TST-FEMMES TST-PART,
T1 §4,voluntary,Working arrangement,covered,TST-REGIME,
T2 §1,mandatory,Policy and practices,covered,TST-POLITIQUE TST-PRATIQUES,
T3 §1,mandatory,Double materiality,out_of_scope,,Outside the scope of the tool.
"""


def catalogue():
    return {**S.KPIS, **KPIS}


class ControleTests(SimpleTestCase):
    def controler(self, socle=SOCLE, kpis=None, couverture=COUVERTURE, libelles=False):
        """Modèle d'essai contrôlé ; ses noms ne sont pas dans les fichiers de langue (contrôle des libellés écarté, sauf
        ``libelles``)."""
        with tempfile.TemporaryDirectory() as d, mock.patch.object(C, "controler_libelles", wraps=C.controler_libelles if libelles else None):
            chemin = Path(d) / "test_def_coverage.csv"
            if couverture is not None:
                chemin.write_text(couverture, encoding="utf-8")
            return C.controler(socle, kpis=kpis or catalogue(), regles={**S.REGLES, **REGLES}, types_reponse=S.TYPES_REPONSE + [LISTE],
                               couverture=chemin)

    def test_noms_dans_les_fichiers_de_langue(self):
        erreurs = " | ".join(self.controler(libelles=True).erreurs)
        for lg in ("fr", "en", "es"):
            self.assertIn(f"libelles/referentiels.{lg}.json : clé « referentiels.socle.test_def.nom » absente", erreurs)

    def test_modele_correct(self):
        r = self.controler()
        self.assertEqual(r.erreurs, [])
        self.assertEqual((r.chiffres["kpi"], r.chiffres["calcules"], r.chiffres["textes"], r.chiffres["facultatifs"]), (6, 1, 1, 1))
        self.assertEqual(r.chiffres["couverture"]["taux"], 80)

    def test_bibliotheque_actuelle_sans_erreur(self):
        conflits, rapports = C.controler_tout()
        self.assertEqual(conflits, [])
        self.assertEqual({r.code: r.erreurs for r in rapports if r.erreurs}, {})

    def test_regles_de_la_fiche_kpi(self):
        mauvais = dict(KPIS)
        mauvais["TST-PART"] = {**KPIS["TST-PART"], "agregation": "Somme"}  # somme d'un pourcentage
        mauvais["TST-PRATIQUES"] = {**KPIS["TST-PRATIQUES"], "agregation": "Décompte"}  # texte rédigé agrégé
        mauvais["TST-EFFECTIF"] = {**KPIS["TST-EFFECTIF"], "formule": "[TST-FEMMES]"}  # formule sur un KPI saisi
        mauvais["TST-POLITIQUE"] = {**KPIS["TST-POLITIQUE"], "temps": "somme", "niveau": "sommet"}
        mauvais["TST-REGIME"] = {**KPIS["TST-REGIME"], "unite": "kWh"}
        erreurs = " | ".join(self.controler(kpis={**S.KPIS, **mauvais}).erreurs)
        for attendu in ("TST-PART : « Somme »", "TST-PRATIQUES : un texte rédigé", "TST-EFFECTIF : formule sur un KPI",
                        "TST-POLITIQUE : un oui / non", "TST-POLITIQUE : niveau conseillé", "TST-REGIME : pas d'unité"):
            self.assertIn(attendu, erreurs)

    def test_formules_et_textes(self):
        k = dict(KPIS)
        k["TST-PART"] = {**KPIS["TST-PART"], "formule": "[TST-FEMMES] / [NRJ-ELEC]"}  # source hors du modèle
        k["TST-FEMMES"] = {**KPIS["TST-FEMMES"], "en": "", "description": "Texte français seul."}
        k["TST-EFFECTIF"] = {**KPIS["TST-EFFECTIF"], "description": ""}
        k["TST-POLITIQUE"] = {**KPIS["TST-POLITIQUE"], "type": "Calculé", "formule": "[TST-PRATIQUES]", "reponse": "Numérique"}
        erreurs = " | ".join(self.controler(kpis={**S.KPIS, **k}).erreurs)
        for attendu in ("TST-PART : sources de la formule absentes du modèle (les placer dans l'arbre) : NRJ-ELEC",
                        "TST-FEMMES : nom français et anglais", "TST-FEMMES : description en couple", "TST-EFFECTIF : définition",
                        "TST-POLITIQUE : formule refusée"):
            self.assertIn(attendu, erreurs)

    def test_couverture(self):
        cv = COUVERTURE.replace("T1 §4,voluntary,Working arrangement,covered,TST-REGIME,", "T1 §4,mandatory,Working arrangement,covered,TST-REGIME,")
        cv += "T4,mandatory,Water,todo,,\nT5,mandatory,Waste,partial,TST-INCONNU,\nT5,maybe,Waste again,done,,\nT6,mandatory,X,covered,TST-EFFECTIF,a, b\n"
        erreurs = " | ".join(self.controler(couverture=cv).erreurs)
        for attendu in ("TST-REGIME répond à une exigence obligatoire mais est facultatif", "« T4 » encore à traiter",
                        "TST-INCONNU n'est pas dans l'arbre", "« T5 » partial sans explication", "« T5 » listée deux fois",
                        "requirement « maybe »", "status « done »", "ligne 10 : trop de colonnes"):
            self.assertIn(attendu, erreurs)
        self.assertIn("fichier de couverture absent", " ".join(self.controler(couverture=None).erreurs))

    def test_en_tete(self):
        socle = {**SOCLE, "code": "modeles", "couleur": "bleu", "nom": ("Seulement français", ""), "source": {"titre": "x"}}
        erreurs = " | ".join(self.controler(socle=socle).erreurs)
        for attendu in ("code du modèle invalide", "couleur invalide", "nom : il faut un couple", "SOURCE incomplète"):
            self.assertIn(attendu, erreurs)


class PaquetDefinitionTests(TestCase):
    def paquet(self):
        with mock.patch.dict(S.KPIS, KPIS), mock.patch.dict(S.REGLES, REGLES), mock.patch.dict(S.FORMATS, {"TST-REGIME": "liste"}), \
                mock.patch.object(S, "TYPES_REPONSE", S.TYPES_REPONSE + [LISTE]):
            return S.paquet(SOCLE)

    def test_paquet_bilingue_liste_et_texte(self):
        p = self.paquet()
        k = {x["code"]: x for x in p.kpis}
        self.assertEqual(k["TST-EFFECTIF"]["descriptions"], {"fr": {"description": "Salariés en fin de période.", "source": "Paie."},
                                                             "en": {"description": "Employees at period end.", "source": "Payroll."}})
        self.assertEqual((k["TST-PRATIQUES"]["agregation_temps"], k["TST-REGIME"]["agregation_temps"]), ("aucune", "derniere"))
        self.assertEqual(k["TST-POLITIQUE"]["niveau_conseille"], "haut")
        self.assertEqual(k["TST-REGIME"]["element"]["obligatoire"], False)
        liste = next(t for t in p.types_reponse if t["code"] == "TST-REGIME")
        self.assertEqual(liste["valeurs"], {"fr": ["Temps plein", "Temps partiel"], "en": ["Full time", "Part time"]})
        self.assertEqual(p.regles[0]["description"], "Les femmes font partie de l'effectif.")

    def test_installation_dans_une_base_vide(self):
        """Arbre par défaut Groupe › Pays › Entité › Site : politique et texte au Groupe (« haut »), le reste au Site."""
        vider()
        p = P.depuis_json(P.vers_json(self.paquet()))  # aller-retour par le JSON, comme un fichier de la bibliothèque
        a = P.analyser(p, source="test_def.json", fourni=True)
        self.assertEqual(a.erreur, "")
        self.assertEqual((a.compteurs["rejet"], a.compteurs["conflit"]), (0, 0))
        P.appliquer(None, a)
        ref = Referentiel.objects.get(code="TEST_DEF")
        self.assertEqual(ElementReferentiel.objects.filter(referentiel=ref).count(), 6)
        niveaux = dict(KPI.objects.filter(code__startswith="TST-").values_list("code", "granularite_id"))
        self.assertEqual(niveaux, {"TST-EFFECTIF": "Site", "TST-FEMMES": "Site", "TST-PART": "Site", "TST-REGIME": "Site",
                                   "TST-POLITIQUE": "Group", "TST-PRATIQUES": "Group"})
        self.assertTrue(KPI.objects.get(code="TST-PRATIQUES").est_texte)
        self.assertTrue(KPI.objects.get(code="TST-REGIME").type_reponse.est_liste)
        self.assertEqual(set(Description.objects.filter(kpi_id="TST-EFFECTIF").values_list("langue", flat=True)), {"fr", "en"})
        self.assertTrue(P.analyser(p, fourni=True).aucune_difference)


class DecouverteTests(SimpleTestCase):
    def test_fichiers_du_dossier(self):
        """Un fichier par modèle ; ceux qui commencent par « _ » sont ignorés ; rangement par SOCLE["ordre"] puis par nom."""
        with tempfile.TemporaryDirectory() as d:
            dossier = Path(d) / "defs_essai"
            dossier.mkdir()
            (dossier / "__init__.py").write_text("")
            (dossier / "b_modele.py").write_text('SOCLE = {"code": "B", "ordre": 1}\n')
            (dossier / "a_modele.py").write_text('SOCLE = {"code": "A"}\n')
            (dossier / "_brouillon.py").write_text("raise RuntimeError\n")
            import sys
            sys.path.insert(0, d)
            try:
                modules = D.charger("defs_essai", dossier)
            finally:
                sys.path.remove(d)
                for nom in [n for n in sys.modules if n.startswith("defs_essai")]:
                    del sys.modules[nom]
        self.assertEqual([m.SOCLE["code"] for m in modules], ["B", "A"])
        self.assertEqual(D.couverture(modules[0], dossier).name, "b_modele_coverage.csv")


class ExempleDuSkillTests(SimpleTestCase):
    """L'exemple du skill de la bibliothèque, que l'assistant copie pour un nouveau
    modèle, reste valide : contrôle sans erreur ni avertissement, paquet constructible (sauté quand le fichier est absent)."""

    def test_exemple_valide(self):
        import importlib.util

        from django.conf import settings

        dossier = Path(settings.BASE_DIR) / ".claude" / "skills" / "library-template" / "reference"
        if not (dossier / "example_template.py").is_file():  # sauté quand le fichier est absent
            self.skipTest("exemple du skill library-template absent")
        spec = importlib.util.spec_from_file_location("example_template", dossier / "example_template.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertFalse(set(m.KPIS) & set(S.KPIS), "l'exemple ne redéfinit aucun KPI de la bibliothèque")
        socle = dict(m.SOCLE, module="example_template", source=m.SOURCE)
        with mock.patch.object(C, "controler_libelles"):  # l'exemple n'a pas de noms dans les fichiers de langue
            r = C.controler(socle, kpis={**S.KPIS, **m.KPIS}, regles={**S.REGLES, **m.REGLES},
                            types_reponse=S.TYPES_REPONSE + m.TYPES_REPONSE, couverture=dossier / "example_template_coverage.csv",
                            propres=set(m.KPIS))
        self.assertEqual((r.erreurs, r.avertissements), ([], []))
        self.assertEqual(r.chiffres["couverture"]["out_of_scope"], 1)
        with mock.patch.dict(S.KPIS, m.KPIS), mock.patch.dict(S.REGLES, m.REGLES), \
                mock.patch.dict(S.FORMATS, {t[0]: t[2] for t in m.TYPES_REPONSE}), \
                mock.patch.object(S, "TYPES_REPONSE", S.TYPES_REPONSE + m.TYPES_REPONSE):
            p = S.paquet(socle)
        self.assertEqual(len(p.kpis), 7)
        self.assertEqual({k["code"] for k in p.kpis if k.get("niveau_conseille") == "haut"},
                         {"EX-POLITIQUE-TELETRAVAIL", "EX-DESCRIPTION-TELETRAVAIL"})
