"""Journal d'administration (``administration.libeller_journal``) : le résumé d'une installation de modèle ou d'un import
de référentiel (« 45 KPI créés, 0 modifiés… », écrit en français) s'affiche dans la langue de la personne qui lit, et les
réglages des assistants sont nommés (avant : « ReglageMCP 1 »)."""
from django.test import TestCase

from parametres import langues as L
from referentiel.models import Referentiel
from serveur_mcp.models import ReglageMCP

from .administration import libeller_journal
from .models import Journal


class JournalImportPaquetTests(TestCase):
    def test_resume_traduit_et_reglages_des_assistants_nommes(self):
        ref = Referentiel.objects.create(code="R1", nom="R1")
        texte = "vs_base.json : 45 KPI créés, 0 modifiés, 45 places, 10 thèmes, 2 réglages, 9 règles"
        e1 = Journal.ecrire(None, "import_paquet", ref, "fichier référentiel", "", texte)
        e2 = Journal.ecrire(None, "import_paquet", ref, "fichier référentiel", "", texte + ", 3 retirés")
        e3 = Journal.ecrire(None, "reglage_mcp", ReglageMCP.courant(), "mcp_actif", False, True)
        with L.activer("en"):
            libeller_journal([e1, e2, e3])
        self.assertEqual(e1.apres_lisible, "vs_base.json: 45 KPIs created, 0 changed, 45 placed, 10 themes, 2 settings, 9 rules")
        self.assertTrue(e2.apres_lisible.endswith("9 rules, 3 removed"))
        self.assertEqual(e3.libelle_objet, "Assistant settings (MCP)")
        with L.activer("fr"):
            libeller_journal([e1])
        self.assertEqual(e1.apres_lisible, texte)
