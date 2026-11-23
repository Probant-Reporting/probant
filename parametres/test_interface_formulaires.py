"""Réglages vus de l'écran : avertissement de lisibilité à l'enregistrement de l'identité (sans refuser), nombre de
sauvegardes gardées, traductions de départ des catégories de description (données créées par les migrations)."""
import importlib

from django.apps import apps
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from referentiel.models import Utilisateur

from .models import CategorieDescription, Instance, TypeSaisie

COULEURS_ILLISIBLES = {"couleur_principale": "#FFFF00", "couleur_texte": "#FFFFFF"}


class AvertissementLisibiliteTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)
        self.url = reverse("parametres:identite")

    def donnees(self, **autres):
        i = Instance.courante()
        return {"nom": i.nom, "titre": i.titre, "sous_titre": i.sous_titre, "sigle": i.sigle, "contact": i.contact, "palette": "perso",
                "couleur_principale": i.couleur_principale, "couleur_accent": i.couleur_accent, "couleur_fond": i.couleur_fond,
                "couleur_texte": i.couleur_texte, **autres}

    def messages(self, rep):
        return [(m.level_tag, str(m)) for m in get_messages(rep.wsgi_request)]

    def test_couleurs_illisibles_enregistrees_avec_avertissement(self):
        rep = self.client.post(self.url, self.donnees(**COULEURS_ILLISIBLES))
        self.assertEqual(rep.status_code, 302)  # rien n'est refusé : c'est le choix de l'administrateur
        self.assertEqual(Instance.courante().couleur_texte, "#FFFFFF")
        niveau, texte = self.messages(rep)[0]
        self.assertEqual(niveau, "warning")
        self.assertIn("sous le minimum", texte)
        self.assertNotIn("{", texte)
        self.assertContains(self.client.get(self.url), "data-alerte-contraste")  # l'encart de la page reste affiché

    def test_singulier_pluriel_et_conseil_neutre(self):
        """« 1 contrôle … est », « 3 contrôles … sont », dans les trois langues ; le conseil renvoie à l'encart
        « Lisibilité des couleurs » sans supposer qu'il faut foncer le texte (faux pour l'apparence sombre)."""
        from .libelles import libelle

        attendus = {"fr": ("1 contrôle de lisibilité sur 14 est", "3 contrôles de lisibilité sur 14 sont", "Lisibilité des couleurs"),
                    "en": ("1 of 14 readability checks is", "3 of 14 readability checks are", "Colour legibility"),
                    "es": ("1 de 14 controles de legibilidad está ", "3 de 14 controles de legibilidad están", "Legibilidad de los colores")}
        for langue, (un, trois, encart) in attendus.items():
            with self.subTest(langue=langue):
                texte_un = libelle("admin.identite.avertissement_contraste", langue, n=1, total=14)
                self.assertIn(un, texte_un)
                self.assertIn(trois, libelle("admin.identite.avertissement_contraste", langue, n=3, total=14))
                self.assertIn(encart, texte_un)
                for faux in ("foncés", "darker", "oscuros"):
                    self.assertNotIn(faux, texte_un)

    def test_couleurs_lisibles_sans_avertissement(self):
        rep = self.client.post(self.url, self.donnees(couleur_principale="#1F5FAD", couleur_texte="#1E2A38"))
        self.assertEqual([n for n, _ in self.messages(rep)], ["success"])


class NombreDeSauvegardesGardeesTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)
        self.url = reverse("parametres:hebergement")

    def envoyer(self, n):
        return self.client.post(self.url, {"action": "reglages_sauvegarde", "sauvegarde_auto": "on", "sauvegarde_frequence": "jour",
                                           "sauvegarde_heure": "02:30", "sauvegarde_conserver": n})

    def test_zero_refuse_avec_message_et_valeur_inchangee(self):
        avant = Instance.courante().sauvegarde_conserver
        rep = self.envoyer(0)
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, "entre 1 et 365")
        self.assertEqual(Instance.courante().sauvegarde_conserver, avant)

    def test_champ_sans_zero(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('name="sauvegarde_conserver"', html)
        champ = html[html.index('name="sauvegarde_conserver"') - 40:][:200]
        self.assertIn('min="1"', champ)
        self.assertIn('max="365"', champ)
        self.assertEqual(self.envoyer(7).status_code, 302)
        self.assertEqual(Instance.courante().sauvegarde_conserver, 7)


class TraductionsDeDepartTests(TestCase):
    """Données créées par les migrations : elles ne passent par aucun fichier de langue, un contrôle de textes ne les voit
    pas (« À inclure » restait en français dans une page anglaise)."""

    def test_categories_fournies_traduites(self):
        for code in ("description", "a_inclure", "a_exclure", "source"):
            c = CategorieDescription.objects.get(code=code)
            for langue in ("en", "es"):
                self.assertTrue((c.traductions.get(langue) or {}).get("libelle"), f"{code} sans traduction {langue}")

    def test_types_de_saisie_fournis_traduits(self):
        for t in TypeSaisie.objects.filter(code__in=("Saisi", "Calculé", "FE")):
            for langue in ("en", "es"):
                self.assertTrue((t.traductions.get(langue) or {}).get("libelle"), f"{t.code} sans traduction {langue}")

    def test_migration_complete_sans_ecraser(self):
        migration = importlib.import_module("parametres.migrations.0027_categories_traduites")
        inclure = CategorieDescription.objects.get(code="a_inclure")
        inclure.traductions = {}
        inclure.save()
        exclure = CategorieDescription.objects.get(code="a_exclure")
        exclure.libelle, exclure.traductions = "À ne pas compter", {}  # renommée par l'administrateur : jamais touchée
        exclure.save()
        source = CategorieDescription.objects.get(code="source")
        source.traductions = {"en": {"libelle": "Origin of the data"}}  # traduction saisie : gardée
        source.save()
        migration.traduire(apps, None)
        self.assertEqual(CategorieDescription.objects.get(code="a_inclure").traductions["en"]["libelle"], "To include")
        self.assertEqual(CategorieDescription.objects.get(code="a_inclure").traductions["es"]["libelle"], "Incluir")
        self.assertEqual(CategorieDescription.objects.get(code="a_exclure").traductions, {})
        s = CategorieDescription.objects.get(code="source").traductions
        self.assertEqual((s["en"]["libelle"], s["es"]["libelle"]), ("Origin of the data", "Fuente de los datos"))
