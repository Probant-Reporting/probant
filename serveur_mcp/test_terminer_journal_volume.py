"""Volume du journal des assistants : chaque écriture faite par un assistant reste au journal, une ligne par appel, pour
toujours ; les lectures et les appels refusés ne vont plus au journal ligne à ligne, mais dans une ligne par personne et
par jour (« appels_mcp »), mise à jour sur place (nombre de lectures, de refus, heure du dernier appel). Les appels notés
pour la limite de débit (``AppelMCP``) sont purgés au-delà de la fenêtre utile, sauf ceux liés à une écriture."""
import datetime
import re

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from collecte.models import Journal, Reponse

from . import journal as J
from .aides_tests import BaseMCP
from .models import AppelMCP, JournalMCP


class VolumeDuJournalTests(BaseMCP):
    def resume(self, u):
        return Journal.objects.get(action="appels_mcp", utilisateur=u)

    def nombres(self, ligne):
        # (depuis la relecture de sécurité : écritures refusées et numéros des jetons à la fin, test_terminer_refus_ecriture)
        m = re.fullmatch(r"lectures : (\d+) ; refus : (\d+) ; dernier appel : \d\d:\d\d ; écritures refusées : \d+ ; jetons : [\d, ]+",
                         ligne.apres)
        self.assertIsNotNone(m, ligne.apres)
        return int(m.group(1)), int(m.group(2))

    def test_lectures_et_refus_une_ligne_par_personne_et_par_jour(self):
        avant = Journal.objects.count()
        for _ in range(30):
            self.outil("contributeur", "list_campaigns")
        self.outil("contributeur", "get_value", self.case(org=self.e2))  # refusé : hors périmètre
        self.requete(self.jetons["contributeur"], "tools/call", {"name": "get_value", "arguments": {"inconnu": 1}})
        self.requete(self.jetons["contributeur"], "tools/call", {"name": "outil_inconnu"})
        self.outil("auditeur", "list_campaigns")
        self.assertEqual(Journal.objects.count() - avant, 2)  # une ligne pour chacune des deux personnes
        self.assertFalse(Journal.objects.filter(action="appel_mcp").exists())
        ligne = self.resume(self.contrib)
        self.assertEqual(self.nombres(ligne), (30, 3))
        self.assertEqual(ligne.champ, timezone.localdate().isoformat())
        self.assertEqual(self.nombres(self.resume(self.auditeur)), (1, 0))
        # le lendemain : une nouvelle ligne, celle de la veille ne change plus
        hier = (timezone.localdate() - datetime.timedelta(days=1)).isoformat()
        Journal.objects.filter(pk=ligne.pk).update(champ=hier)
        self.outil("contributeur", "list_campaigns")
        lignes = Journal.objects.filter(action="appels_mcp", utilisateur=self.contrib).order_by("pk")
        self.assertEqual([self.nombres(x) for x in lignes], [(30, 3), (1, 0)])

    def test_ecritures_une_ligne_par_appel_pour_toujours(self):
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        _, res, d = self.outil("contributeur", "save_value", {**self.case(), "value": "130", "version": r.date_maj.isoformat()})
        self.assertFalse(res["isError"], d)
        refus = self.outil("contributeur", "save_value", {**self.case(campagne=self.c0), "value": "5", "version": ""})[1]
        self.assertTrue(refus["isError"])
        appels = Journal.objects.filter(action="appel_mcp", utilisateur=self.contrib)
        self.assertEqual([(e.champ, e.apres) for e in appels], [("save_value", "ok")])
        self.assertIn('"value": "130"', appels.get().avant)
        self.assertEqual(self.nombres(self.resume(self.contrib)), (0, 1))  # l'écriture refusée : comptée
        marquees = set(JournalMCP.objects.values_list("journal_id", flat=True))
        self.assertTrue(marquees)
        # purge des appels de la limite de débit : au-delà de la fenêtre, sauf ceux liés à une écriture
        for _ in range(5):
            self.outil("contributeur", "list_campaigns")
        AppelMCP.objects.update(date=timezone.now() - J.FENETRE - datetime.timedelta(seconds=5))
        self.outil("contributeur", "list_campaigns")
        restes = list(AppelMCP.objects.filter(utilisateur=self.contrib).values_list("outil", flat=True).order_by("pk"))
        self.assertEqual(restes, ["save_value", "list_campaigns"])
        self.assertEqual(set(JournalMCP.objects.values_list("journal_id", flat=True)), marquees)  # « via MCP » gardé
        self.assertEqual(AppelMCP.objects.filter(utilisateur=self.contrib, date__gte=timezone.now() - J.FENETRE).count(), 1)

    def test_historique_page_et_export(self):
        self.outil("contributeur", "list_campaigns")
        self.outil("contributeur", "get_value", self.case(org=self.e2))
        c = Client()
        c.force_login(self.admin)
        page = c.get(reverse("collecte:admin_journal") + "?famille=mcp").content.decode()
        self.assertIn("lectures : 1 ; refus : 1", page)
        export = c.get(reverse("collecte:admin_journal") + "?famille=mcp&export=xlsx")
        from collecte.aides_tests.echanges import classeur

        ws = classeur(export).worksheets[-1]
        textes = {str(ws.cell(i, j).value) for i in range(1, ws.max_row + 1) for j in range(1, ws.max_column + 1)}
        self.assertTrue(any("lectures : 1 ; refus : 1" in t for t in textes), textes)
        self.admin.langue = "en"  # affichée dans la langue de la personne qui lit
        self.admin.save(update_fields=["langue"])
        page = c.get(reverse("collecte:admin_journal") + "?famille=mcp").content.decode()
        self.assertIn("reads: 1; refused: 1; last call: ", page)
