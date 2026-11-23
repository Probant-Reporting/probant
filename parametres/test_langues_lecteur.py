"""Langue de la personne qui lit : journal, nombres, relances, en-têtes de fichiers (français, anglais, espagnol)."""
from django.test import TestCase

from collecte import relances as R


class TraductionTests(TestCase):
    """(10) nombres selon la langue et point décimal accepté ; (11) un modèle de relance par langue, repli sur le
    français ; (13) fichiers à réimporter avec des en-têtes en anglais ou en espagnol ; (14) journal lu dans sa langue."""

    def setUp(self):
        from parametres import niveaux as N
        from referentiel.models import Utilisateur

        N.creer_par_defaut()
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)

    def test_nombres_selon_la_langue(self):
        from collecte.templatetags.collecte import nombre

        self.assertEqual(nombre(1234.5, 1, "fr"), "1\u202f234,5")
        self.assertEqual(nombre(1234.5, 1, "en"), "1,234.5")
        self.assertEqual(nombre(1234.5, 1, "es"), "1.234,5")
        self.assertEqual(nombre(-0.001, 2, "en"), "0.00")

    def test_saisie_virgule_ou_point(self):
        from collecte.saisie import texte_nombre as T

        for texte, langue, attendu in (("1 234,5", "fr", "1234.5"), ("12.5", "fr", "12.5"), ("1,234.5", "en", "1234.5"),
                                       ("1,234", "en", "1234"), ("1,5", "en", "1.5"), ("1.234,5", "es", "1234.5"),
                                       ("12.5", "es", "12.5"), ("1.234.567", "es", "1234567"), ("1,234", "fr", "1.234")):
            self.assertEqual(T(texte, langue), attendu, (texte, langue))

    def test_relance_par_langue_avec_repli_sur_le_francais(self):
        from parametres.models import Instance

        self.assertTrue(R.modele("en")[0].startswith("{outil}"))  # texte fourni, en anglais
        i = Instance.courante()
        i.relance_sujet, i.relance_message = "Rappel {campagne}", "Bonjour {prenom}"
        i.relance_traductions = {"en": {"sujet": "Reminder {campagne}", "message": "Hello {prenom}"}}
        i.save()
        self.assertEqual(R.modele("en"), ("Reminder {campagne}", "Hello {prenom}"))
        self.assertEqual(R.modele("es"), ("Rappel {campagne}", "Bonjour {prenom}"))  # repli : le français réglé
        self.assertEqual(R.modele("fr"), ("Rappel {campagne}", "Bonjour {prenom}"))

    def test_page_relances_enregistre_chaque_langue(self):
        from django.urls import reverse

        from parametres.models import Instance

        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:relances"))
        self.assertContains(rep, 'name="sujet_en"')
        self.assertContains(rep, 'name="message_es"')
        self.client.post(reverse("collecte:relances"), {"action": "modele", "sujet": R.sujet_defaut("fr"), "message": R.message_defaut("fr"),
                                                        "sujet_en": "Reminder", "message_en": "Hello {prenom}", "sujet_es": "",
                                                        "message_es": "", "relance_jours": "7,2"})
        i = Instance.courante()
        self.assertEqual((i.relance_sujet, i.relance_traductions), ("", {"en": {"sujet": "Reminder", "message": "Hello {prenom}"}}))
        rep = self.client.post(reverse("collecte:relances"), {"action": "modele", "sujet": "x", "message": "y", "sujet_es": "{inconnue}",
                                                              "relance_jours": "7"})
        self.assertEqual(rep.status_code, 200)  # variable inconnue dans la version espagnole : refusé
        self.assertEqual(Instance.courante().relance_traductions, {"en": {"sujet": "Reminder", "message": "Hello {prenom}"}})

    def test_traductions_en_tetes_anglais_et_espagnol(self):
        import io

        from openpyxl import Workbook

        from parametres import traductions_fichier as TF
        from parametres.models import TypeSaisie

        for entetes in (["Key", "Section", "Item", "Source text", "Translation (EN)"],
                        ["Clave", "Sección", "Elemento", "Texto de partida", "Traducción (EN)"]):
            wb = Workbook()
            ws = wb.active
            ws.append(entetes)
            t = TypeSaisie.objects.first()
            cle = next(iter(TF._elements("en")))
            ws.append([cle, "", "", "", "Nouveau texte"])
            f = io.BytesIO()
            wb.save(f)
            f.seek(0)
            f.name = "traductions.xlsx"
            analyses, erreur = TF.analyser(f, ["en"])
            self.assertEqual(erreur, "", entetes)
            self.assertEqual([a.code for a in analyses], ["en"])
            self.assertEqual(len(analyses[0].changements), 1, entetes)
            self.assertIsNotNone(t)

    def test_reprise_en_tetes_espagnols(self):
        from collecte import reprise as RP

        for role, entete in (("valeur", "Valor"), ("organisation", "Entidad"), ("periode", "Año"), ("kpi_nom", "Indicador")):
            self.assertIn(RP._norm(entete), {RP._norm(s) for s in RP.SYNONYMES[role]})

    def test_journal_dans_la_langue_de_qui_lit(self):
        from django.urls import reverse

        from parametres.models import Instance

        from collecte.models import Journal

        Journal.ecrire(self.admin, "reglage_relances", Instance.courante(), "modèle", "personnalisé", "texte fourni")
        self.admin.langue = "en"
        self.admin.save()
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:admin_journal") + "?vue=admin")
        self.assertContains(rep, "provided text")
        self.assertContains(rep, "customised")
        self.assertNotContains(rep, "texte fourni")
