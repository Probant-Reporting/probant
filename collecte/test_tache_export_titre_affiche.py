"""Nom d'un gros export (Import / Export › Mes exports) : un nom composé par l'outil (« Fichier à remplir – … », nom de la
présentation quand la personne n'a rien tapé) s'affiche dans la langue de qui lit, pas figé dans celle de la demande ; un
nom donné par la personne reste tel qu'elle l'a écrit. Les exports enregistrés gardaient déjà ce comportement
(``exports.texte_fourni``).

Données inventées uniquement."""
from unittest import mock

from django.urls import reverse

from parametres import langues as L
from parametres.libelles import libelle
from parametres.models import Instance

from . import exports as E
from . import exports_arriere_plan as EAP
from . import imports_arriere_plan as AP
from . import saisie as S
from .aides_tests.lecture_seule import Base
from .models import ReglageExport, TacheExport

EXPORT_BASE = {"action": "telecharger", "presentation": "base", "exercices": ["courant"], "contenus": list(E.CODES_CONTENUS),
               "types": list(E.CODES_COMPORTEMENTS)}


@mock.patch.object(AP, "planificateur_actif", lambda: False)
@mock.patch.object(EAP, "demarrer_fil", lambda code: None)  # jamais de vrai fil pendant les tests
class TitreAfficheTests(Base):
    def setUp(self):
        super().setUp()
        i = Instance.courante()
        i.exports_fond_cellules = 1  # tout export est « volumineux »
        i.save()
        S.enregistrer(self.admin, self.c, self.eff, self.e2, "30", False, "")
        self.client.force_login(self.admin)

    def titre_dans(self, tache, langue):
        with L.activer_interface(langue):
            return tache.titre_affiche

    def test_fichier_a_remplir_dans_la_langue_de_qui_lit(self):
        with L.activer_interface("fr"):
            self.client.get(reverse("collecte:echanges_modele"), {"campagne": self.c.pk})
        t = TacheExport.objects.get()
        self.assertTrue(t.titre.startswith("Fichier à remplir"))  # figé à la demande, en français
        self.assertTrue(self.titre_dans(t, "en").startswith("File to fill in – "))
        self.assertTrue(self.titre_dans(t, "de").startswith("Auszufüllende Datei – "))
        with L.activer_interface("en"):
            self.assertIn(self.c.nom_complet_affiche, self.titre_dans(t, "en"))

    def test_export_sans_titre_prend_le_nom_de_la_presentation(self):
        self.client.post(reverse("collecte:echanges_exporter"), {**EXPORT_BASE, "niveaux": E.N.codes()})
        t = TacheExport.objects.get()
        fr, en = self.titre_dans(t, "fr"), self.titre_dans(t, "en")
        self.assertEqual(en.split(" – ")[0], next(n for c, n, _ in E.presentations("en") if c == "base"))
        self.assertNotEqual(fr, en)

    def telecharger_modele(self, reglage):
        with L.activer_interface("fr"):
            self.client.get(reverse("collecte:echanges_exporter"), {"modele": reglage.pk, "telecharger": 1})
        return TacheExport.objects.get()

    def test_nom_donne_par_la_personne_reste_tel_quel(self):
        r = ReglageExport.objects.create(nom="Mon fichier d'automne", parametres={**EXPORT_BASE, "niveaux": E.N.codes()},
                                         proprietaire=self.admin)
        t = self.telecharger_modele(r)
        self.assertTrue(t.titre.startswith("Mon fichier d'automne"))
        for langue in ("fr", "en", "de"):
            self.assertTrue(self.titre_dans(t, langue).startswith("Mon fichier d'automne"), langue)

    def test_modele_fourni_se_lit_dans_la_langue_de_qui_regarde(self):
        E.creer_modeles_fournis()
        r = ReglageExport.objects.get(nom=E.PRESETS["tableau"][0])
        t = self.telecharger_modele(r)
        self.assertTrue(t.titre.startswith("Tableau de l'exercice avec N-1"))
        self.assertTrue(self.titre_dans(t, "en").startswith(libelle("suivi.echanges.fourni.tableau.nom", "en")), "en")
        self.assertNotEqual(self.titre_dans(t, "en"), self.titre_dans(t, "fr"))

    def test_tache_d_avant_sans_composition_garde_son_titre(self):
        t = TacheExport.objects.create(utilisateur=self.admin, genre="export", titre="Ancien nom", parametres={}, empreinte="x")
        self.assertEqual(self.titre_dans(t, "en"), "Ancien nom")
