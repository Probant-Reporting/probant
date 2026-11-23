"""Chaque écriture d'un assistant au journal (« appel_mcp »), lectures et refus comptés par jour (« appels_mcp ») ; les changements faits par un appel écrits par les fonctions
habituelles et affichés « via MCP » dans l'Historique (page et export) ; l'auditeur les lit, rien de plus."""
from django.test import Client
from django.urls import reverse

from collecte.models import Journal, Reponse

from .aides_tests import BaseMCP
from .models import AppelMCP, JournalMCP


class JournalViaMcpTests(BaseMCP):
    def test_chaque_appel_au_journal_avec_son_issue(self):
        """Écriture réussie : une ligne « appel_mcp » (outil, arguments, issue) ; lecture, refus, argument faux : comptés
        dans la ligne du jour de la personne (« appels_mcp », serveur_mcp/test_terminer_journal_volume.py)."""
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        self.outil("contributeur", "list_campaigns")
        self.outil("contributeur", "get_value", self.case(org=self.e2))  # refusé : hors périmètre
        self.requete(self.jetons["contributeur"], "tools/call", {"name": "get_value", "arguments": {"inconnu": 1}})
        self.outil("contributeur", "save_value", {**self.case(), "value": "130", "version": r.date_maj.isoformat()})
        lignes = list(Journal.objects.filter(action="appel_mcp").order_by("pk"))
        self.assertEqual([(e.champ, e.apres, e.utilisateur_id) for e in lignes], [("save_value", "ok", self.contrib.pk)])
        jour = Journal.objects.get(action="appels_mcp", utilisateur=self.contrib)
        self.assertTrue(jour.apres.startswith("lectures : 1 ; refus : 2 ; "), jour.apres)
        self.assertEqual(list(AppelMCP.objects.order_by("pk").values_list("statut", flat=True))[-4:], ["ok", "refus", "refus", "ok"])

    def test_changements_marques_via_mcp_et_ecrits_par_la_saisie(self):
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        _, res, d = self.outil("contributeur", "save_value", {**self.case(), "value": "130", "comment": "Via assistant",
                                                              "version": r.date_maj.isoformat()})
        self.assertFalse(res["isError"], d)
        changements = Journal.objects.filter(objet="Reponse", objet_id=str(r.pk), action="modification")
        self.assertEqual(set(changements.values_list("champ", flat=True)), {"valeur", "commentaire"})
        marquees = set(JournalMCP.objects.values_list("journal_id", flat=True))
        self.assertTrue(set(changements.values_list("pk", flat=True)) <= marquees)
        # une saisie faite sur la page n'est pas marquée
        Client().force_login(self.contrib)
        from collecte import saisie as S

        S.enregistrer(self.contrib, self.c, self.eff, self.e1, "131", False, "Via la page")
        derniere = Journal.objects.filter(objet="Reponse", objet_id=str(r.pk), champ="valeur").latest("pk")
        self.assertNotIn(derniere.pk, set(JournalMCP.objects.values_list("journal_id", flat=True)))

    def test_historique_affiche_via_mcp_page_et_export(self):
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        self.outil("contributeur", "save_value", {**self.case(), "value": "130", "version": r.date_maj.isoformat()})
        c = Client()
        c.force_login(self.admin)
        page = c.get(reverse("collecte:admin_journal")).content.decode()
        self.assertIn("(via MCP)", page)
        page = c.get(reverse("collecte:admin_journal") + "?famille=mcp").content.decode()
        self.assertIn("save_value", page.lower())
        export = c.get(reverse("collecte:admin_journal") + "?export=xlsx")
        from collecte.aides_tests.echanges import classeur

        ws = classeur(export).worksheets[-1]
        actions = {ws.cell(i, 4).value for i in range(1, ws.max_row + 1)}
        self.assertTrue(any(a and "(via MCP)" in a for a in actions), actions)

    def test_historique_d_une_case_par_l_outil(self):
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        self.outil("contributeur", "save_value", {**self.case(), "value": "130", "version": r.date_maj.isoformat()})
        _, _, d = self.outil("auditeur", "get_cell_history", self.case())
        self.assertTrue(any(x["via_mcp"] for x in d["changes"]))
        self.assertEqual(d["other_periods"][0]["value"], "100")  # exercice clôturé
        _, _, d = self.outil("contributeur", "get_cell_history", self.case())
        self.assertNotIn("changes", d)  # le journal : page Historique, administrateur et auditeur seulement
