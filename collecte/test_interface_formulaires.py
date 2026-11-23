"""Formulaires d'administration vus de l'écran : seuil d'écart d'une campagne borné comme celui des Paramètres, message
de l'outil (et non celui de Django) pour un nom d'organisation déjà pris."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from parametres import langues as L
from referentiel.models import Niveau, Organisation, Utilisateur

from .administration import CampagneForm, OrganisationForm
from .models import Campagne

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class SeuilEcartCampagneTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def envoyer(self, pct):
        return self.client.post(reverse("collecte:admin_campagne_nouvelle"),
                                {"exercice": 2030, "seuil_pct": pct, "action": "enregistrer"}, **FETCH).json()

    def test_seuil_au_dela_de_100_refuse(self):
        res = self.envoyer("500")
        self.assertFalse(res["ok"])
        self.assertFalse(Campagne.objects.filter(exercice=2030).exists())
        self.assertIn("100", res["html"])  # même message que Paramètres › Seuils de suivi (Django : « inférieure ou égale à 100 »)

    def test_bornes_comme_les_parametres(self):
        from parametres.views import SeuilsForm

        # mêmes bornes que les écarts tolérés de Paramètres › Seuils de suivi
        for nom_page, nom_campagne in (("tolerance_fe_pct", "seuil_pct"),):
            page = SeuilsForm.base_fields[nom_page]
            campagne = CampagneForm.base_fields[nom_campagne]
            self.assertEqual((campagne.min_value, campagne.max_value), (page.min_value, page.max_value))

    def test_attribut_du_champ_et_valeurs_limites(self):
        champ = CampagneForm().fields["seuil_pct"]
        self.assertEqual(champ.widget.attrs.get("max"), 100)
        for pct in ("0", "100"):
            res = self.envoyer(pct)
            self.assertTrue(res["ok"], res)
            Campagne.objects.filter(exercice=2030).delete()
        self.assertFalse(self.envoyer("-1")["ok"])
        res = self.envoyer("20")
        self.assertTrue(res["ok"], res)
        self.assertEqual(Campagne.objects.get(exercice=2030).seuil_ecart, Decimal("0.2"))


class NomOrganisationDejaPrisTests(TestCase):
    def setUp(self):
        Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)

    def erreur_nom(self, langue):
        with L.activer_interface(langue):
            form = OrganisationForm({"nom": "Groupe", "niveau": Niveau.GROUP, "actif": "on", "rang": 1})
            self.assertFalse(form.is_valid())
            return " ".join(form.errors["nom"])

    def test_message_de_l_outil_dans_les_trois_langues(self):
        attendu = {"fr": "Une autre organisation porte déjà ce nom.", "en": "Another organisation already has this name.",
                   "es": "Otra organización ya tiene este nombre."}
        for langue, debut in attendu.items():
            message = self.erreur_nom(langue)
            self.assertTrue(message.startswith(debut), f"{langue} : {message}")
            self.assertNotIn("Un objet", message)
            self.assertNotIn("with this", message)
