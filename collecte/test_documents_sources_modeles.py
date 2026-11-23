"""Documents sources des modèles de la bibliothèque (rubrique « Source documents ») : forme de la fiche ``SOURCE`` (liste de
documents, ancienne forme d'un seul dictionnaire toujours lue), contrôle, paquet JSON, et affichage dans l'outil (cartes,
écrans d'installation, en-tête d'un référentiel installé, documentation générée). Rien n'est enregistré en base."""
import copy
import json

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import translation

from referentiel.bibliotheque import documentation as DOC
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque import sources
from referentiel.models import Referentiel, Utilisateur

from . import paquets as P
from .aides_tests.paquets import vider

CHEMIN_INTERNE = "refer" + "ences/"  # dossier de l'atelier, jamais cité par un texte publié
DOCUMENT = {"titre": "Titre officiel", "editeur": "Éditeur", "version": "v1", "date": "2026-07-03", "url": "https://exemple.test/doc",
            "consulte_le": "2026-11-18", "licence": "Droit de l'Union"}
ANCIENNE_FORME = {"titre": "Norme", "editeur": "Éditeur", "version": "2026", "url": "https://exemple.test/", "consulte_le": "2026-11-13",
                  "licence": "Paraphrase"}


class FormeDeLaFicheTests(SimpleTestCase):
    def test_une_liste_de_documents_et_l_ancienne_forme_sont_lues(self):
        self.assertEqual(sources.documents([DOCUMENT]), [DOCUMENT])
        ancien = sources.documents(ANCIENNE_FORME)
        self.assertEqual(len(ancien), 1)
        self.assertEqual((ancien[0]["titre"], ancien[0]["date"]), ("Norme", ""))
        self.assertEqual(sources.documents(None), [])
        self.assertEqual(sources.erreurs([DOCUMENT]), [])
        self.assertEqual(sources.erreurs(ANCIENNE_FORME), [], "l'ancienne forme reste valide, sans date du document")

    def test_la_liste_exige_la_date_du_document_ou_l_annee(self):
        sans_date = {k: v for k, v in DOCUMENT.items() if k != "date"}
        self.assertTrue(any("date" in e for e in sources.erreurs([sans_date])))
        self.assertEqual(sources.erreurs([{**DOCUMENT, "date": "2026"}]), [], "l'année seule est admise")
        self.assertTrue(sources.erreurs([{**DOCUMENT, "date": "03/07/2026"}]), "ni jj/mm/aaaa ni date supposée au format libre")
        self.assertTrue(sources.erreurs([{**DOCUMENT, "date": "2026-13-01"}]))

    def test_dates_dans_le_futur_adresse_et_texte_de_l_atelier_refuses(self):
        self.assertTrue(sources.erreurs([{**DOCUMENT, "consulte_le": "2999-01-01"}]))
        self.assertTrue(sources.erreurs([{**DOCUMENT, "date": "2999-01-01"}]))
        self.assertTrue(sources.erreurs([{**DOCUMENT, "url": CHEMIN_INTERNE + "vs/doc.html"}]))
        self.assertTrue(sources.erreurs([{**DOCUMENT, "licence": "copie gardée dans l'atelier"}]))
        self.assertTrue(sources.erreurs([{**DOCUMENT, "inconnue": "x"}]))
        self.assertTrue(sources.erreurs([]), "une fiche vide est refusée")


class PaquetEtAffichageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Utilisateur.objects.create_user("admin", "admin@exemple.test", "x", role=Utilisateur.Role.ADMIN)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_chaque_modele_fourni_porte_ses_documents_dans_son_paquet(self):
        for f in P.bibliotheque():
            with self.subTest(f.paquet.code):
                self.assertTrue(f.paquet.documents, "au moins un document source")
                for d in f.paquet.documents_affiches:
                    self.assertTrue(d["titre"] and d["editeur"] and d["version"] and d["date"] and d["consulte_le"])
                    self.assertTrue(d["url"].startswith("http"))
                    self.assertNotIn(CHEMIN_INTERNE, json.dumps(d))

    def test_l_export_d_un_referentiel_ne_gagne_pas_de_rubrique_documents(self):
        p = copy.deepcopy(P.fourni("vs_base.json").paquet)
        p.documents = []
        self.assertNotIn('"documents"', P.vers_json(p))
        self.assertIn('"documents"', P.vers_json(P.fourni("vs_base.json").paquet))
        relu = P.depuis_json(P.vers_json(P.fourni("vs_base.json").paquet))
        self.assertEqual(relu.documents, P.fourni("vs_base.json").paquet.documents)

    def test_un_paquet_ancien_sans_documents_reste_lisible(self):
        d = json.loads(P.vers_json(P.fourni("vs_base.json").paquet))
        d.pop("documents")
        self.assertEqual(P.depuis_dict(d).documents, [])

    def test_dates_du_document_en_date_courte_ou_annee_seule(self):
        docs = P.documents_affiches([DOCUMENT, {**DOCUMENT, "date": "2026"}])
        with translation.override("fr"):
            self.assertEqual(docs[1]["date_texte"], "2026")
        for cle, iso in (("date_texte", "2026-07-03"), ("consulte_texte", "2026-11-18")):
            self.assertNotEqual(docs[0][cle], iso, "date courte de la langue, pas la forme d'échange")
            self.assertIn("2026", docs[0][cle])

    def test_les_cartes_et_les_ecrans_d_installation_montrent_les_documents(self):
        vider()
        for url in (reverse("parametres:installer_modeles"), reverse("parametres:referentiels"),
                    reverse("parametres:installer_kpi", args=["ESRS_E1"]), reverse("parametres:installer_kpi", args=["VS_BASE"])):
            with self.subTest(url):
                html = self.client.get(url).content.decode()
                self.assertIn('class="documents-source"', html)
        html = self.client.get(reverse("parametres:installer_kpi", args=["ESRS_E1"])).content.decode()
        self.assertIn("Explanatory Note: Revised ESRS", html)
        self.assertIn("EFRAG", html)
        self.assertNotIn(CHEMIN_INTERNE, html)

    def test_l_en_tete_d_un_referentiel_installe_montre_les_documents_sans_rien_enregistrer(self):
        vider()
        a = P.analyser(P.fourni("transparence_remunerations.json").paquet, source="essai", fourni=True)
        P.appliquer(None, a)
        ref = Referentiel.objects.get(code="TRANSPARENCE_REMU")
        champs_avant = [f.name for f in Referentiel._meta.get_fields()]
        for onglet in ("referentiel_contenu", "referentiel_reglages", "referentiel_partage"):
            with self.subTest(onglet):
                html = self.client.get(reverse(f"parametres:{onglet}", args=[ref.code])).content.decode()
                self.assertIn("Directive (EU) 2023/970", html)
                self.assertIn("https://eur-lex.europa.eu/eli/dir/2023/970/oj", html)
        self.assertEqual(champs_avant, [f.name for f in Referentiel._meta.get_fields()], "aucun champ de plus en base")

    def test_la_documentation_generee_a_sa_rubrique(self):
        texte = DOC.documentation()
        self.assertEqual(texte.count("\nSource documents:\n"), len(S.SOCLES))
        self.assertIn("| Document | Publisher | Version | Document date | Read on | Licence |", texte)
        self.assertNotIn(CHEMIN_INTERNE, texte)
