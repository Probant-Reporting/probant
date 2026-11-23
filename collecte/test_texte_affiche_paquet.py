"""Textes d'un modèle de la bibliothèque à l'écran et à l'installation (``paquets.texte_affiche``,
``analyser_installation``, ``Paquet.noms_connus``).

Défauts corrigés :
- écran de choix de l'installation en allemand ou en espagnol : thèmes et KPI en français (langue de référence du paquet)
  alors que la Saisie, pour les mêmes KPI, retombe sur la langue par défaut de l'installation (anglais ici) ;
- nom du référentiel perdu dans les autres langues : installé depuis une interface anglaise, « ESRS E1 – Climate change »
  remplaçait toutes les traductions (le nom proposé à l'écran n'était pas reconnu comme celui du modèle) ;
- résumé de l'installation : noms des niveaux dans la langue de référence (« Groupe ») dans une interface anglaise."""
from django.test import TestCase

from parametres import langues as L
from parametres import niveaux as N
from parametres.models import Instance
from referentiel.models import KPI, Referentiel

from . import paquets as P
from .aides_tests.paquets import vider

E1 = "esrs_e1.json"


class TexteAffichePaquetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        vider()
        i = Instance.courante()
        i.langue = "en"  # langue par défaut de l'installation (langue de référence : français)
        i.save()

    def setUp(self):
        self.p = P.fourni(E1).paquet

    def test_repli_comme_les_contenus(self):
        with L.activer("de"):
            self.assertEqual(P.texte_affiche({"fr": "Changement climatique", "en": "Climate change"}, "fr"), "Climate change")
            self.assertEqual(P.texte_affiche({"fr": "Changement climatique", "de": "Klimawandel"}, "fr"), "Klimawandel")
        with L.activer("fr"):
            self.assertEqual(P.texte_affiche({"fr": "Changement climatique", "en": "Climate change"}, "fr"), "Changement climatique")

    def test_ecran_de_choix_comme_la_saisie(self):
        from parametres.vues_installation import _arbre_a_cocher

        k = next(k for k in self.p.kpis if k["libelle"].get("en"))
        saisie = KPI(code=k["code"], libelle=k["libelle"]["fr"],
                     traductions={lg: {"libelle": t} for lg, t in k["libelle"].items() if lg != "fr"})
        with L.activer("de"):  # les modèles ESRS portent l'allemand : l'écran de choix l'affiche, comme la saisie
            _, _, lignes = _arbre_a_cocher(self.p, set(), set(), set())
            self.assertEqual(lignes[k["code"]]["nom"], saisie.tr("libelle"))
            self.assertEqual(lignes[k["code"]]["nom"], k["libelle"]["de"])

    def installer(self, langue, nom=None):
        with L.activer(langue):
            a, _ = P.analyser_installation(self.p, [k["code"] for k in self.p.kpis], nom=self.p.nom() if nom is None else nom)
            P.appliquer(None, a)
        return Referentiel.objects.get(code="ESRS_E1")

    def test_nom_propose_garde_toutes_les_traductions(self):
        ref = self.installer("en")
        self.assertEqual(ref.nom, "ESRS E1 – Changement climatique")
        self.assertEqual(ref.traductions["en"]["nom"], "ESRS E1 – Climate change")
        self.assertEqual(ref.traductions["de"]["nom"], "ESRS E1 – Klimawandel")  # fichiers de langue du modèle

    def test_nom_change_vaut_pour_sa_langue(self):
        ref = self.installer("en", nom="Our climate framework")
        self.assertEqual(ref.nom, "ESRS E1 – Changement climatique")
        self.assertEqual(ref.traductions["en"]["nom"], "Our climate framework")
        self.assertEqual(ref.traductions["de"]["nom"], "ESRS E1 – Klimawandel")

    def test_niveaux_du_resume_dans_la_langue_de_l_interface(self):
        from parametres.vues_installation import _phrases_niveaux

        with L.activer("en"):
            a, _ = P.analyser_installation(self.p, [k["code"] for k in self.p.kpis], nom=self.p.nom())
            niveaux = sorted(N.tous(), key=lambda n: n.rang)
            phrase, detail = _phrases_niveaux(a, niveaux)
            haut = niveaux[0]
            self.assertNotEqual(str(haut), haut.nom)  # le niveau a bien un nom anglais
            self.assertIn(str(haut), phrase + detail)
            self.assertNotIn(haut.nom, phrase + detail)
