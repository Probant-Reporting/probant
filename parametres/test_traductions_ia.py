"""Traductions proposées par l'IA (vues_ia.traductions_ia) : bouton seulement quand la prise et l'usage sont allumés et
qu'un texte reste vide ; administrateur seulement ; ne partent que les textes de départ vides de la section, sans les
clés techniques ; un numéro non envoyé est écarté ; rien n'est enregistré sans le bouton de la page."""
from django.test import TestCase
from django.urls import reverse

from collecte.models import Journal
from parametres import langues as L
from parametres.aides_tests.ia import AvecIA
from parametres.models import Langue
from referentiel.models import KPI, Niveau, Utilisateur


class TraductionsIATests(AvecIA, TestCase):
    def setUp(self):
        super().setUp()
        Langue.objects.get_or_create(code="es", defaults={"libelle": "Español", "ordre": 3})
        self.k1 = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        self.k2 = KPI.objects.create(code="NRJ", libelle="Énergie consommée", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        self.k2.traductions = {"es": {"libelle": "Energía consumida"}}
        self.k2.save()
        self.admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)
        self.page = reverse("parametres:traductions", args=["es"]) + "?section=kpi"
        self.url = reverse("parametres:traductions_ia", args=["es"])

    def test_bouton_seulement_prise_et_usage_allumes(self):
        self.assertNotContains(self.client.get(self.page), 'data-ia-traductions="')
        self.allumer(ia_traductions=False)
        self.assertNotContains(self.client.get(self.page), 'data-ia-traductions="')
        self.allumer()
        self.assertContains(self.client.get(self.page), f'data-ia-traductions="{self.url}"')

    def test_propositions_sans_rien_enregistrer(self):
        self.allumer()
        d = self.client.post(self.url, {"section": "kpi"}).json()
        self.assertEqual(d["propositions"], [{"cle": "kpi|EFF", "texte": "[sp] Effectif"}])
        r = self.factice.demandes[0]
        self.assertIn('"source_language":"French"', r.donnees)
        self.assertIn('"text":"Effectif"', r.donnees)
        self.assertNotIn("kpi|", r.donnees)  # clés techniques jamais envoyées
        self.assertNotIn("Énergie", r.donnees)  # déjà traduit : ne part pas
        self.assertEqual(L.texte(KPI.objects.get(code="EFF"), "libelle", "es"), "")  # rien d'enregistré
        self.assertTrue(Journal.objects.filter(action="ia_appel", champ="traduction", objet="Langue", objet_id="es").exists())

    def test_numero_non_envoye_ecarte(self):
        self.allumer()
        self.factice.reponse = {"translations": [{"id": 7, "text": "Intrus"}, {"id": 1, "text": "Plantilla"}]}
        d = self.client.post(self.url, {"section": "kpi"}).json()
        self.assertEqual(d["propositions"], [{"cle": "kpi|EFF", "texte": "Plantilla"}])

    def test_refus(self):
        self.allumer(ia_traductions=False)
        self.assertIn("pas disponible", self.client.post(self.url, {"section": "kpi"}).json()["erreur"])
        self.assertEqual(self.client.post(reverse("parametres:traductions_ia", args=[L.reference()])).status_code, 404)
        contrib = Utilisateur.objects.create(username="c", email="c@exemple.test")
        self.client.force_login(contrib)
        self.assertEqual(self.client.post(self.url, {"section": "kpi"}).status_code, 403)
        self.assertEqual(self.factice.demandes, [])
