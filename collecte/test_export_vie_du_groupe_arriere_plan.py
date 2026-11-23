"""Vie d'un groupe (qa/group_life) : au-delà du seuil des gros exports, « Télécharger » crée une tâche et renvoie à Mes
exports. Le personnage suit alors la tâche comme la page (état, puis téléchargement) et compare le fichier au
téléchargement immédiat, au lieu de signaler à tort « unexpected_status » / « export_no_file » (constaté en grande
taille, plus de 100 000 cellules)."""
from unittest import mock

from qa.group_life.actors import Actor, Log

from . import exports as E
from . import exports_arriere_plan as EAP
from . import imports_arriere_plan as AP
from . import saisie as S
from .aides_tests.lecture_seule import Base
from .models import TacheExport
from parametres.models import Instance


@mock.patch.object(EAP, "BATTEMENT", 0)
@mock.patch.object(AP, "planificateur_actif", lambda: False)
@mock.patch.object(EAP, "demarrer_fil", lambda code: None)  # pas de vrai fil : le personnage fait la tâche lui-même
class ExportArrierePlanVieDuGroupe(Base):

    def test_le_personnage_suit_la_tache_puis_telecharge(self):
        S.enregistrer(self.admin, self.c, self.eff, self.e1, "12", False, "")
        Instance.objects.filter(pk=Instance.courante().pk).update(exports_fond_cellules=1)
        log = Log()
        a = Actor(self.admin.username, log)
        data = a.export(presentation="base", format="xlsx", exercices=["courant"], contenus=list(E.CODES_CONTENUS),
                        types=list(E.CODES_COMPORTEMENTS), niveaux=list(E.N.codes()))
        self.assertEqual(log.anomalies, [])
        self.assertTrue(data and data[:2] == b"PK")
        t = TacheExport.objects.get()
        self.assertEqual(t.statut, TacheExport.Statut.PRET)
        self.assertIsNotNone(t.telecharge_le)  # téléchargé par Mes exports
        self.assertEqual(Instance.courante().exports_fond_cellules, 1)  # seuil remis après la comparaison


class ComparaisonDesExports(Base):
    """Le fichier porte l'heure de sa fabrication à la minute (« Exporté le … ») : deux exports faits de part et d'autre
    d'un changement de minute sont le même export ; une valeur différente reste une différence (échec vu sur GitHub)."""

    def test_heure_de_fabrication_ignoree_mais_pas_les_valeurs(self):
        from qa.group_life.actors import same_export, xlsx_bytes

        avant = xlsx_bytes([["Exporté le", "16/11/2026 13:56 · admin"], ["Effectif", 12]])
        apres = xlsx_bytes([["Exporté le", "16/11/2026 13:57 · admin"], ["Effectif", 12]])
        autre = xlsx_bytes([["Exporté le", "16/11/2026 13:57 · admin"], ["Effectif", 13]])
        self.assertTrue(same_export(avant, apres))
        self.assertFalse(same_export(avant, autre))
        self.assertTrue(same_export("Exporté le;2026-11-16 13:56\nEffectif;12".encode(),
                                    "Exporté le;2026-11-16 13:57\nEffectif;12".encode()))
