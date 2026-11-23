"""« Demandé depuis » (Contenu du référentiel) : la liste ne propose que les choix possibles pour les KPI cochés (les
autres sont grisés avec leur raison), et les messages sont des phrases bien formées (« depuis le début », pas
« à partir de Depuis le début »).

Données inventées uniquement."""
import re

from django.urls import reverse

from referentiel.composition import placer
from referentiel.models import KPI, ElementReferentiel

from . import demande_depuis as DD
from .test_demande_depuis_perimetre import J25, Base


class ChoixPossiblesTests(Base):
    def refus(self, code):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("parametres:referentiel_contenu", args=[self.ref.code]))
        m = re.search(r'data-element="%s".*?data-depuis-refus="([^"]*)"' % code, rep.content.decode(), re.S)
        self.assertIsNotNone(m, "attribut data-depuis-refus absent")
        return set(m.group(1).split()) - {"-"}

    def test_kpi_depuis_le_debut_ne_peut_pas_sortir_d_un_exercice_clos(self):
        # EFF n'a pas de date : 2024 et 2025 (clos) le perdraient en avançant la date à 2025 ou à l'exercice en cours
        self.assertEqual(self.refus("EFF"), {"2025-01-01", "2026-01-01", "_"})

    def test_kpi_recent_peut_tout_choisir(self):
        self.nouveau()
        placer(KPI.objects.get(pk="NEW"), self.ref, None)  # 2026
        self.assertEqual(self.refus("NEW"), set())

    def test_la_liste_reste_complete_pour_le_serveur(self):
        # la liste n'est qu'une aide : le serveur refuse toujours l'action impossible
        with self.assertRaises(Exception):
            DD.changer(self.admin, self.ref, ["EFF"], J25, confirmer=True)
        self.assertIsNone(ElementReferentiel.objects.get(referentiel=self.ref, kpi_id="EFF").demande_depuis)


class MessagesTests(Base):
    def test_avertissement_depuis_le_debut_est_une_phrase(self):
        from referentiel.composition import placer as placer_

        self.nouveau("SRC")
        self.nouveau("CAL", type_saisie_id="Calculé", formule="[EFF] + [SRC]", methode_agregation="Formule")
        placer_(KPI.objects.get(pk="SRC"), self.ref, None)  # 2026
        placer_(KPI.objects.get(pk="CAL"), self.ref, None)  # 2026
        p = DD.Prevision(self.ref, ["CAL"], None)
        texte = " ".join(p.avertissements)
        self.assertTrue(texte)
        self.assertNotRegex(texte, r"(?i)(à partir de|from|ab|desde|dal|vanaf|a partir de) (depuis le début|since the start)")
        self.assertRegex(texte.lower(), r"depuis le début|since the start")
