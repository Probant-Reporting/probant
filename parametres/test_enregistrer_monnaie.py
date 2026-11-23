"""Réglage « Monnaie de référence » (Paramètres › Unités et formats) : l'euro par défaut, une
liste fermée (code ISO), une ligne d'historique, la page dit qu'aucun KPI existant ne change ni aucune valeur n'est
convertie, et signale les KPI dont l'unité monétaire n'est pas dans la monnaie de référence (sans rien changer)."""
from django.test import TestCase
from django.urls import reverse

from collecte.models import Journal
from parametres.models import Instance, Unite
from referentiel.models import KPI, Niveau, Utilisateur

URL = reverse("parametres:referentiel") + "?section=unites"


class MonnaieTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Utilisateur.objects.create_user("admin", "admin@exemple.test", "x", role=Utilisateur.Role.ADMIN)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_euro_par_defaut(self):
        self.assertEqual(Instance.courante().monnaie, "EUR")
        rep = self.client.get(URL)
        self.assertContains(rep, '<option value="EUR" selected>euro (€, EUR)</option>', html=True)
        self.assertContains(rep, "Les KPI qui existent déjà gardent leur unité. L'outil ne convertit aucune valeur et "
                                 "n'utilise aucun taux de change.")
        self.assertContains(rep, 'aria-describedby="aide-monnaie"')

    def test_enregistrer(self):
        rep = self.client.post(URL, {"action": "monnaie", "monnaie": "GBP"}, follow=True)
        self.assertContains(rep, "Monnaie de référence enregistrée : livre sterling (£, GBP).")
        self.assertEqual(Instance.courante().monnaie, "GBP")
        j = Journal.objects.get(champ="Monnaie de référence")
        self.assertEqual((j.avant, j.apres, j.utilisateur_id), ("EUR", "GBP", self.admin.pk))
        self.client.post(URL, {"action": "monnaie", "monnaie": "GBP"})  # sans changement : rien au journal
        self.assertEqual(Journal.objects.filter(champ="Monnaie de référence").count(), 1)

    def test_texte_libre_refuse(self):
        rep = self.client.post(URL, {"action": "monnaie", "monnaie": "DOGE"})
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, "Choisissez une monnaie dans la liste.")
        self.assertEqual(Instance.courante().monnaie, "EUR")
        self.assertFalse(Journal.objects.filter(champ="Monnaie de référence").exists())

    def test_kpi_dans_une_autre_monnaie_signale(self):
        u = Unite.objects.create(code="k$", symbole="k$", libelle="millier de dollars", famille="Monnaie")
        KPI.objects.create(code="ACHATS", libelle="Achats", type_saisie_id="Saisi", granularite_id=Niveau.SITE, unite=u)
        rep = self.client.get(URL)
        self.assertContains(rep, "1 KPI utilise une unité dans une autre monnaie que euro (€, EUR) : k$. Rien ne change pour lui.")
        self.client.post(URL, {"action": "monnaie", "monnaie": "USD"})
        self.assertNotContains(self.client.get(URL), "autre monnaie")
        self.assertEqual(KPI.objects.get(pk="ACHATS").unite_id, "k$")
