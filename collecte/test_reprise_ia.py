"""Correspondances proposées par l'IA dans l'assistant de reprise (vues_ia.reprise_ia) : bouton seulement quand la
prise et l'usage sont allumés et qu'un libellé reste à relier ; administrateur seulement ; ne part que les libellés pas
encore reliés et le catalogue (ni valeurs ni organisations) ; un code inventé est écarté ; rien n'est mémorisé."""
from django.urls import reverse

from parametres.aides_tests.ia import AvecIA

from .aides_tests.echanges import Base
from .models import CorrespondanceReprise, Journal
from .test_reprise import classeur

URL = reverse("collecte:admin_reprise")
URL_IA = reverse("collecte:admin_reprise_ia")


class RepriseIATests(AvecIA, Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def jusqu_aux_correspondances(self):
        fichier = classeur([["Indicateur", "Entité", 2022, 2023],
                            ["Effectif", "E1", 100, 104],
                            ["Effectif total fin d'année", "Entite deux", 40, 41]], "ancien.xlsx")
        rep = self.client.post(URL + "?etape=fichier", {"action": "deposer", "fichier": fichier, "source": "Ancien"}, follow=True)
        r = rep.context["r"]
        donnees = {"action": "suivant", "entete": r.entete + 1, "forme": r.forme, "valeurs": ["2022", "2023"]}
        donnees.update({f"role_{role}": t for role, t in r.colonnes.items()})
        self.client.post(URL + "?etape=colonnes", donnees)
        return self.client.get(URL + "?etape=correspondances")

    def test_bouton_seulement_prise_et_usage_allumes(self):
        rep = self.jusqu_aux_correspondances()
        self.assertNotContains(rep, 'data-ia-reprise="')
        self.allumer(ia_reprise=False)
        self.assertNotContains(self.client.get(URL + "?etape=correspondances"), 'data-ia-reprise="')
        self.allumer()
        self.assertContains(self.client.get(URL + "?etape=correspondances"), f'data-ia-reprise="{URL_IA}"')

    def test_propositions_et_ce_qui_part(self):
        self.jusqu_aux_correspondances()
        self.allumer()
        d = self.client.post(URL_IA, HTTP_X_REQUESTED_WITH="fetch").json()
        self.assertEqual(d["propositions"], [{"libelle": "Effectif total fin d'année", "code": "EFF", "affiche": "EFF – Effectif",
                                              "raison": "(fake) shared words"}])
        r = self.factice.demandes[0]
        self.assertIn("Effectif total fin d'année", r.donnees)
        self.assertNotIn('"label":"Effectif"', r.donnees)  # déjà relié (nom identique) : ne part pas
        for jamais in ("E1", "Entite deux", "104", "2023"):
            self.assertNotIn(jamais, r.donnees)
        self.assertFalse(CorrespondanceReprise.objects.exists())  # rien n'est mémorisé
        self.assertTrue(Journal.objects.filter(action="ia_appel", champ="reprise").exists())

    def test_code_invente_ecarte(self):
        self.jusqu_aux_correspondances()
        self.allumer()
        self.factice.reponse = {"matches": [{"id": 1, "code": "INVENTE", "reason": "sûr"}]}
        d = self.client.post(URL_IA, HTTP_X_REQUESTED_WITH="fetch").json()
        self.assertEqual(d["propositions"][0]["code"], "")

    def test_refus(self):
        self.allumer()
        self.assertIn("plus disponible", self.client.post(URL_IA).json()["erreur"])  # aucune reprise en cours
        self.allumer(ia_reprise=False)
        self.assertIn("pas disponible", self.client.post(URL_IA).json()["erreur"])
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.post(URL_IA).status_code, 403)
        self.assertEqual(self.factice.demandes, [])
