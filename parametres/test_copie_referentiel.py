"""Dupliquer un référentiel et le rendre inactif / le réactiver en un clic (demande retenue)."""
from django.test import TestCase
from django.urls import reverse

from collecte.models import Journal
from referentiel.models import KPI, ElementReferentiel, Niveau, Referentiel, Theme, Utilisateur


class CopieReferentielTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN,
                                                is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)
        self.ref = Referentiel.objects.create(code="CSRD", nom="Reporting 2026", couleur="#123456", frequence="mois",
                                              mois_debut=7, comparaison="P-1", traductions={"en": {"nom": "Reporting 2026 EN"}})
        self.env = Theme.objects.create(referentiel=self.ref, code="E", nom="Environnement", ordre=1)
        self.energie = Theme.objects.create(referentiel=self.ref, code="E1", nom="Énergie", parent=self.env, ordre=1)
        for i, (code, theme, obligatoire) in enumerate((("A", self.energie, True), ("B", self.env, False))):
            k = KPI.objects.create(code=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
            ElementReferentiel.objects.create(referentiel=self.ref, kpi=k, theme=theme, ordre=i, obligatoire=obligatoire,
                                              libelle=f"Libellé {code}")

    def test_copie(self):
        page = self.client.get(reverse("parametres:referentiel_copier", args=["CSRD"]))
        self.assertContains(page, "Reporting 2026 (copie)")
        r = self.client.post(reverse("parametres:referentiel_copier", args=["CSRD"]), {"nom": "Reporting 2027", "code": "CSRD27"})
        self.assertRedirects(r, reverse("parametres:referentiel_contenu", args=["CSRD27"]), fetch_redirect_response=False)
        c = Referentiel.objects.get(code="CSRD27")
        self.assertEqual((c.nom, c.couleur, c.frequence, c.mois_debut, c.comparaison, c.actif), ("Reporting 2027", "#123456", "mois", 7, "P-1", True))
        self.assertNotIn("nom", c.traductions.get("en", {}))  # le nom traduit de l'original ne suit pas le nouveau nom
        self.assertEqual(sorted(c.themes.values_list("code", "parent__code")), [("E", None), ("E1", "E")])
        elements = {e.kpi_id: e for e in c.elements.select_related("theme")}
        self.assertEqual((elements["A"].theme.code, elements["A"].obligatoire, elements["A"].libelle), ("E1", True, "Libellé A"))
        self.assertEqual((elements["B"].theme.code, elements["B"].obligatoire), ("E", False))
        self.assertEqual(KPI.objects.count(), 2)  # mêmes KPI du catalogue : rien n'est dupliqué
        self.assertTrue(Referentiel.objects.get(code="CSRD").actif)
        self.assertEqual(c.campagnes.count(), 0)
        self.assertTrue(Journal.objects.filter(objet="Referentiel", objet_id="CSRD27").exists())

    def test_copie_et_original_inactif(self):
        self.client.post(reverse("parametres:referentiel_copier", args=["CSRD"]), {"nom": "Reporting 2027", "desactiver": "on"})
        self.assertFalse(Referentiel.objects.get(code="CSRD").actif)
        self.assertTrue(Referentiel.objects.filter(nom="Reporting 2027", actif=True).exists())

    def test_code_deja_pris(self):
        r = self.client.post(reverse("parametres:referentiel_copier", args=["CSRD"]), {"nom": "X", "code": "csrd"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "CSRD")
        self.assertEqual(Referentiel.objects.count(), 1)

    def test_rendre_inactif_puis_reactiver(self):
        self.client.post(reverse("parametres:referentiels"), {"action": "desactiver", "code": "CSRD"})
        self.assertFalse(Referentiel.objects.get(code="CSRD").actif)
        self.assertEqual(ElementReferentiel.objects.filter(referentiel_id="CSRD").count(), 2)  # contenu gardé
        self.client.post(reverse("parametres:referentiels"), {"action": "reactiver", "code": "CSRD"})
        self.assertTrue(Referentiel.objects.get(code="CSRD").actif)
        accueil = self.client.get(reverse("parametres:referentiels"))
        self.assertContains(accueil, reverse("parametres:referentiel_copier", args=["CSRD"]))
        self.assertContains(accueil, 'value="desactiver"')

    def test_reserve_a_l_administrateur(self):
        u = Utilisateur.objects.create(username="c", email="c@exemple.test", role=Utilisateur.Role.CONTRIBUTEUR)
        self.client.force_login(u)
        self.assertIn(self.client.get(reverse("parametres:referentiel_copier", args=["CSRD"])).status_code, (302, 403, 404))
        self.client.post(reverse("parametres:referentiels"), {"action": "desactiver", "code": "CSRD"})
        self.assertTrue(Referentiel.objects.get(code="CSRD").actif)


class HistoriqueEtNouvelleVersionTests(TestCase):
    """Référentiel historique jusqu'à 2025 et nouvelle version à partir de 2026 (demande retenue) :
    les campagnes à partir d'un exercice passent à la copie, et des KPI se retirent d'après une liste collée."""

    def setUp(self):
        from collecte.periodes import campagne

        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN,
                                                is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)
        self.ref = Referentiel.objects.create(code="REPORTING", nom="Reporting", frequence="annee")
        for code in ("A", "B", "N1", "N2"):
            k = KPI.objects.create(code=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
            ElementReferentiel.objects.create(referentiel=self.ref, kpi=k)
        import datetime

        for annee in (2024, 2025, 2026):
            campagne(self.ref, datetime.date(annee, 1, 1))

    def test_campagnes_a_partir_d_un_exercice(self):
        url = reverse("parametres:referentiel_copier", args=["REPORTING"])
        self.assertContains(self.client.get(url), "2024, 2025, 2026")
        r = self.client.post(url, {"nom": "Référentiel 2026", "code": "R2026", "campagnes_des": "2026"}, follow=True)
        self.assertContains(r, "1 campagne (à partir de 2026) passe à « Référentiel 2026 ».")
        self.assertEqual(sorted(Referentiel.objects.get(code="REPORTING").campagnes.values_list("exercice", flat=True)), [2024, 2025])
        self.assertEqual(list(Referentiel.objects.get(code="R2026").campagnes.values_list("exercice", flat=True)), [2026])
        self.assertTrue(Referentiel.objects.get(code="REPORTING").actif)  # l'historique reste consultable

    def test_exercice_invalide(self):
        r = self.client.post(reverse("parametres:referentiel_copier", args=["REPORTING"]), {"nom": "X", "campagnes_des": "26a"})
        self.assertContains(r, "Saisissez une année, par exemple 2026")
        self.assertEqual(Referentiel.objects.count(), 1)

    def test_retirer_par_liste_apercu_puis_confirmation(self):
        url = reverse("parametres:referentiel_liste", args=["REPORTING"])
        self.assertEqual(self.client.get(url).status_code, 200)
        r = self.client.post(url, {"codes": "N1\nN2\tZZ", "mode": "retirer", "action": "apercu"})
        self.assertContains(r, "2 KPI seront retirés")
        self.assertContains(r, "ZZ")
        self.assertEqual(self.ref.elements.count(), 4)  # rien avant la confirmation
        self.client.post(url, {"codes": "N1\nN2\tZZ", "mode": "retirer", "action": "confirmer"})
        self.assertEqual(sorted(self.ref.elements.values_list("kpi_id", flat=True)), ["A", "B"])
        self.assertEqual(KPI.objects.count(), 4)  # restent au catalogue

    def test_garder_seulement_la_liste(self):
        self.client.post(reverse("parametres:referentiel_liste", args=["REPORTING"]),
                         {"codes": "A, N1; N2", "mode": "garder", "action": "confirmer"})
        self.assertEqual(sorted(self.ref.elements.values_list("kpi_id", flat=True)), ["A", "N1", "N2"])

    def test_liste_reservee_a_l_administrateur(self):
        u = Utilisateur.objects.create(username="c", email="c@exemple.test", role=Utilisateur.Role.CONTRIBUTEUR)
        self.client.force_login(u)
        self.client.post(reverse("parametres:referentiel_liste", args=["REPORTING"]), {"codes": "A", "action": "confirmer"})
        self.assertEqual(self.ref.elements.count(), 4)
