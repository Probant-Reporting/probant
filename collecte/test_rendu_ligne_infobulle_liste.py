"""Grille de saisie (``rendu_ligne``) : l'infobulle d'une réponse de liste est la réponse affichée dans la langue de
l'interface, comme la case. Avant : la valeur enregistrée (langue de référence), « Rouge » dans une interface anglaise."""
from django.urls import reverse

from parametres import langues as L
from parametres.models import TypeReponse
from referentiel.models import KPI, Attribution, Niveau

from .aides_tests.saisie import Base


class InfobulleListeTests(Base):
    def setUp(self):
        super().setUp()
        t = TypeReponse(code="Couleur", libelle="Couleur", format="liste", valeurs=["Rouge", "Bleu"])
        L.definir_valeurs(t, "en", ["Red", "Blue"], 2)
        t.save()
        self.k = KPI.objects.create(code="COUL", libelle="Couleur", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                    type_reponse=t, methode_agregation="Aucune")
        Attribution.objects.create(kpi=self.k, organisation=self.e1, utilisateur=self.contrib)
        self.enregistrer("Rouge", kpi=self.k)
        self.client.force_login(self.contrib)

    def test_infobulle_dans_la_langue_de_l_interface(self):
        s = self.client.session
        s[L.CLE_SESSION] = "en"
        s.save()
        html = self.client.get(reverse("collecte:saisie") + f"?campagne={self.c.pk}").content.decode()
        self.assertIn('title="Red"', html)
        self.assertNotIn('title="Rouge"', html)
