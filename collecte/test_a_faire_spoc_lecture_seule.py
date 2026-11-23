"""``relances.a_faire`` et ``restes_sans_spoc`` (cases des « SPOC ») : un compte en lecture seule n'est jamais le contributeur
d'une case (vie d'un groupe, quatrième année, « reminder_to_reader »).

Un contributeur devient lecteur (nouveau poste) avant qu'on ait nommé quelqu'un à sa place. Avant : il restait le SPOC de
ses cases ; la page Relances lui proposait une relance pour des cases qu'il ne peut pas remplir, et ces cases n'étaient
pas comptées « sans contributeur » (personne ne les voyait orphelines). « Remplacer une personne… » refuse déjà de
donner des attributions à un compte en lecture seule."""
from referentiel.models import Utilisateur

from . import relances as R
from .aides_tests.saisie import Base


class SpocLectureSeuleTests(Base):
    def test_contributeur_devenu_lecteur_ni_relance_ni_compte_comme_spoc(self):
        avant = {af.personne.pk for af in R.a_faire([self.c])}
        self.assertIn(self.contrib.pk, avant)
        orphelines = R.restes_sans_spoc([self.c])
        Utilisateur.objects.filter(pk=self.contrib.pk).update(role=Utilisateur.Role.LECTEUR)
        self.assertNotIn(self.contrib.pk, {af.personne.pk for af in R.a_faire([self.c])})
        self.assertGreater(R.restes_sans_spoc([self.c]), orphelines)  # ses cases : à attribuer, signalées à l'administrateur

    def test_auditeur_de_meme(self):
        Utilisateur.objects.filter(pk=self.contrib.pk).update(role=Utilisateur.Role.AUDITEUR)
        self.assertNotIn(self.contrib.pk, {af.personne.pk for af in R.a_faire([self.c])})
