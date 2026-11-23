"""Guides : une règle « Bloquante » empêche de valider ; aucune phrase ne dit qu'une alerte ne bloque jamais."""
import json
import re
from pathlib import Path
from unittest import TestCase

from . import aide as AI

RACINE = Path(__file__).resolve().parent.parent


def etiquette_bloquante(langue):
    return json.loads((RACINE / "libelles" / f"cadre.{langue}.json").read_text(encoding="utf-8"))["choix.alerte.gravite.bloquante"]


class GuidesAlerteBloquanteTests(TestCase):
    def test_les_guides_nomment_la_regle_bloquante_qui_empeche_de_valider(self):
        for guide in ("contributor", "validator", "auditor"):
            for langue in AI.LANGUES_GUIDES:
                texte = AI.chemin_guide(guide, langue).read_text(encoding="utf-8")
                self.assertIn(f"**{etiquette_bloquante(langue)}**", texte, f"{guide} {langue}")

    def test_aucun_guide_ne_dit_qu_une_alerte_ne_bloque_jamais(self):
        faux = re.compile(r"never blocks|ne bloque jamais|nunca bloquea|blockiert nie|non blocca mai|blokkeert nooit|nunca bloqueia", re.I)
        for guide in AI.GUIDES:
            for langue in AI.LANGUES_GUIDES:
                texte = AI.chemin_guide(guide, langue).read_text(encoding="utf-8")
                self.assertIsNone(faux.search(texte), f"{guide} {langue}")
