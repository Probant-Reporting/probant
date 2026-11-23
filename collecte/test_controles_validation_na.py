"""``saisie.controles_validation`` : un N/A dont le commentaire n'est fait que d'espaces (import, ancienne donnée) est
« sans commentaire », même règle que ``ecart_justifie`` (vide ou espaces = pas de commentaire)."""
from parametres.libelles import libelle

from . import saisie as S
from .models import Reponse
from .aides_tests.saisie import Base


class NaSansCommentaireTests(Base):
    def test_commentaire_fait_d_espaces(self):
        S.enregistrer(self.contrib, self.c, self.eff, self.e1, "", True, "Fermé cette année")
        r = S.reponse_de(self.c, self.eff, self.e1)
        self.assertNotIn(libelle("saisie.msg.commentaire_na"), S.controles_validation(r, self.c))
        Reponse.objects.filter(pk=r.pk).update(commentaire="   \n ")  # écrit hors de la saisie (qui retire les espaces)
        r.refresh_from_db()
        self.assertIn(libelle("saisie.msg.commentaire_na"), S.controles_validation(r, self.c))
        with self.assertRaises(Exception):
            S.valider(self.contrib, self.c, self.eff, self.e1)  # la validation est refusée
