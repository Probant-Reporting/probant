"""Seconde recette (B6) : la date de fin de saisie d'un e-mail de relance est écrite dans la langue du destinataire, en
toutes lettres (« 13 January 2027 », « 13. Januar 2027 ») comme les pages, et non « 13/01/2027 » dans toutes les langues
(ambigu en anglais)."""
import datetime

from collecte.periodes import MOIS
from collecte.models import Campagne

from . import relances as R
from .aides_tests.saisie import Base


class DateRelanceTests(Base):
    def setUp(self):
        super().setUp()
        Campagne.objects.filter(pk=self.c.pk).update(date_fin_saisie=datetime.date(2027, 1, 13))
        self.c.refresh_from_db()

    def texte(self, langue):
        self.contrib.langue = langue
        self.contrib.save(update_fields=["langue"])
        return R.rediger(R.a_faire([self.c], destinataires=[self.contrib.pk])[0])[1]

    def test_date_longue_dans_la_langue_du_destinataire(self):
        attendus = {"en": f"13 {MOIS['en'][0]} 2027", "de": f"13. {MOIS['de'][0]} 2027", "fr": f"13 {MOIS['fr'][0]} 2027",
                    "es": f"13 de {MOIS['es'][0]} de 2027"}
        for langue, attendu in attendus.items():
            with self.subTest(langue=langue):
                texte = self.texte(langue)
                self.assertIn(attendu, texte)
                self.assertNotIn("13/01/2027", texte)

    def test_liste_de_plusieurs_campagnes(self):
        autre = Campagne.objects.create(referentiel=self.c.referentiel, exercice=2027, statut=Campagne.Statut.OUVERTE,
                                        date_fin_saisie=datetime.date(2027, 3, 5))
        from referentiel.models import ElementReferentiel  # noqa: F401 - périmètre : tous les KPI du référentiel

        self.contrib.langue = "en"
        self.contrib.save(update_fields=["langue"])
        liste = R.a_faire([self.c, autre], destinataires=[self.contrib.pk])
        texte = R.rediger(liste[0])[1]
        self.assertNotIn("/2027", texte)
