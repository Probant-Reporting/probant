"""Visualisation, comparaison N / N-1 : quand les organisations comptées ne sont pas les mêmes dans les deux périodes
(une organisation pas encore ouverte l'année comparée), une mention le dit ; le total ne change pas
(``visualisation.Source.perimetre_change``, à confirmer). Données inventées."""
import datetime

from referentiel.models import Organisation

from .aides_tests.visuels import AvecKpis

MENTION = "ne sont pas les mêmes"


class PerimetreChangeComparaisonTests(AvecKpis):
    def visuel(self):
        d = self.donnees(self.admin, {"type": "comparaison_n1", "kpis": ["EFF"]},
                         parametres={"org": str(self.p.id), "periode": str(self.c.periode.pk), "brouillons": "1"})
        return d["visuels"]["v1"]

    def test_temoin_meme_perimetre_sans_mention(self):
        v = self.visuel()
        self.assertFalse(any(MENTION in a for a in v["avertissements"]), v["avertissements"])

    def test_organisation_pas_ouverte_l_annee_comparee(self):
        avant = self.visuel()["series"]
        Organisation.objects.filter(pk=self.e2.pk).update(date_ouverture=datetime.date(2026, 1, 1))
        v = self.visuel()
        self.assertTrue(any(MENTION in a for a in v["avertissements"]), v["avertissements"])
        self.assertEqual(v["series"][0]["valeurs"], avant[0]["valeurs"])  # 2026 : total inchangé
