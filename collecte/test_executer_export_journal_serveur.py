"""Journal du serveur d'un gros export (``exports_arriere_plan.executer``) : l'état est écrit en anglais dans un message en
anglais (« … ready in 1 s »), jamais avec le code français de la base (« pret ») ; la base garde son code."""
from unittest import mock

from django.urls import reverse

from . import exports as E
from . import exports_arriere_plan as EAP
from . import imports_arriere_plan as AP
from . import saisie as S
from .aides_tests.lecture_seule import Base
from .models import TacheExport
from .test_exports_arriere_plan import EXPORT_BASE, seuil


@mock.patch.object(EAP, "BATTEMENT", 0)
@mock.patch.object(AP, "planificateur_actif", lambda: False)
@mock.patch.object(EAP, "demarrer_fil", lambda code: None)
class JournalServeurExportTests(Base):
    def demander(self):
        S.enregistrer(self.admin, self.c, self.eff, self.e1, "12", False, "")
        seuil(1)
        self.client.force_login(self.admin)
        self.client.post(reverse("collecte:echanges_exporter"), {**EXPORT_BASE, "niveaux": E.N.codes()})

    def test_etat_en_anglais_dans_le_message(self):
        self.demander()
        with self.assertLogs("collecte.exports", level="INFO") as cm:
            EAP.traiter_file()
        fin = [m for m in cm.output if " in " in m and "bytes" in m]
        self.assertEqual(len(fin), 1, cm.output)
        self.assertRegex(fin[0], r'Background export #\d+ \(space "[^"]*"\) ready in \d+ s \(\d+ bytes\)')
        self.assertNotIn("pret", fin[0])
        self.assertEqual(TacheExport.objects.get().statut, TacheExport.Statut.PRET)  # la base garde son code

    def test_etat_d_un_echec_en_anglais(self):
        self.demander()
        with mock.patch.object(EAP, "fabriquer", side_effect=RuntimeError("panne")), self.assertLogs("collecte.exports", level="INFO") as cm:
            EAP.traiter_file()
        fin = [m for m in cm.output if " in " in m and "bytes" in m]
        self.assertEqual(len(fin), 1, cm.output)
        self.assertIn(" failed in ", fin[0])
        self.assertNotIn("echec", fin[0])
