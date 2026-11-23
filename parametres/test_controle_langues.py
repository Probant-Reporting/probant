"""Contrôle de la traduction : textes qui restaient en français dans une page anglaise ou espagnole
parce qu'ils ne passaient pas par les fichiers de langue (dates en toutes lettres, durée écoulée, tailles des sauvegardes,
listes de choix et libellés des formulaires venus des modèles, fichiers exportés par une personne dont la langue
d'interface n'est pas une langue des contenus)."""
import datetime
import io

from django.test import TestCase
from django.utils import timezone
from openpyxl import load_workbook

from collecte.templatetags.collecte import date_longue, depuis
from parametres import langues as L
from parametres import libelles as LB
from parametres.models import Instance
from parametres.sauvegardes import taille_lisible
from referentiel.models import KPI, Niveau, Organisation, Utilisateur


class TextesHorsFichiersTests(TestCase):
    def test_date_en_toutes_lettres(self):
        d = datetime.date(2026, 10, 29)
        attendu = {"fr": "29 octobre 2026", "en": "29 October 2026", "es": "29 de octubre de 2026"}
        for code, texte in attendu.items():
            with self.subTest(langue=code), L.activer_interface(code):
                self.assertEqual(date_longue(d), texte)
        self.assertEqual(date_longue(None), "")

    def test_duree_ecoulee(self):
        il_y_a = timezone.now() - datetime.timedelta(hours=3, minutes=5)
        for code, mot in {"fr": "heures", "en": "hours", "es": "horas"}.items():
            with self.subTest(langue=code), L.activer_interface(code):
                self.assertIn(mot, depuis(il_y_a))

    def test_tailles(self):
        for code, attendu in {"fr": ("0 o", "1,5 Ko", "2,0 Mo"), "en": ("0 B", "1.5 KB", "2.0 MB"),
                              "es": ("0 B", "1,5 KB", "2,0 MB")}.items():
            with self.subTest(langue=code), L.activer_interface(code):
                self.assertEqual((taille_lisible(0), taille_lisible(1536), taille_lisible(2 * 1024 ** 2)), attendu)

    def test_choix_et_libelles_des_formulaires(self):
        from collecte.administration import CompteForm
        from parametres.views import IdentiteForm
        from parametres.vues_hebergement import ReglagesSauvegardeForm

        with L.activer_interface("en"):
            f = ReglagesSauvegardeForm(instance=Instance.courante())
            self.assertIn("Every day", [t for _, t in f.fields["sauvegarde_frequence"].choices])
            self.assertEqual(str(f.fields["sauvegarde_frequence"].label), "Frequency")
            i = IdentiteForm(instance=Instance.courante())
            self.assertEqual(str(i.fields["titre"].label), "Tool name")
            self.assertEqual(str(i.fields["contact"].label), "Contact for sign-in problems")
            self.assertEqual(str(i.fields["titre"].help_text), "")  # le simulateur de la page remplace la phrase d'aide
            c = CompteForm(instance=Utilisateur())
            self.assertIn("Contributor", [t for _, t in c.fields["role"].choices])
        with L.activer_interface("es"):
            self.assertIn("Cada día", [t for _, t in ReglagesSauvegardeForm(instance=Instance.courante())
                                       .fields["sauvegarde_frequence"].choices])
        with L.activer_interface("fr"):
            self.assertIn("Chaque jour", [t for _, t in ReglagesSauvegardeForm(instance=Instance.courante())
                                          .fields["sauvegarde_frequence"].choices])

    def test_aide_des_types_de_saisie(self):
        from parametres.models import TypeSaisie

        t = TypeSaisie(code="X", libelle="X", abrege="X", comportement=TypeSaisie.Comportement.CALCUL)
        with L.activer_interface("fr"):
            self.assertEqual(t.aide, TypeSaisie.AIDES[TypeSaisie.Comportement.CALCUL])
        with L.activer_interface("en"):
            self.assertTrue(t.aide.startswith("Calculated with a formula"))
        with L.activer_interface("es"):
            self.assertTrue(t.aide.startswith("Se calcula"))

    def test_periodes_du_formulaire_de_campagne(self):
        from collecte.administration import rangs_par_frequence

        with L.activer_interface("es"):
            r = rangs_par_frequence()
        self.assertIn(("mois", 2, "febrero"), r)
        self.assertIn(("trimestre", 1, "T1"), r)
        with L.activer_interface("en"):
            r = rangs_par_frequence()
        self.assertIn(("mois", 2, "February"), r)
        self.assertIn(("semestre", 2, "H2"), r)

    def test_traduire_choix_garde_les_valeurs(self):
        from parametres.vues_hebergement import ReglagesSauvegardeForm

        with L.activer_interface("en"):
            f = ReglagesSauvegardeForm(instance=Instance.courante())
        self.assertEqual([v for v, _ in f.fields["sauvegarde_frequence"].choices],
                         [v for v, _ in Instance.FrequenceSauvegarde.choices])
        self.assertIs(LB.traduire_choix(f), f)


class ExportDansLaLangueDeLaPersonneTests(TestCase):
    """Espagnol sans traduction des contenus (pas une langue active) : le fichier est en espagnol, les noms des KPI
    suivent leur repli (langue par défaut)."""

    def setUp(self):
        from collecte import saisie as S
        from collecte.models import Campagne

        g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=g)
        c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE,
                                    date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        kpi = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                 methode_agregation="Somme")
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        S.enregistrer(self.admin, c, kpi, e1, "12", False, "")

    def exporter(self, langue, choisie=""):
        from collecte import exports as E

        self.admin.langue = langue
        with L.pour(self.admin):
            p = E.Parametres.depuis({"presentation": "base", "langue": choisie})
            wb = load_workbook(io.BytesIO(E.exporter(self.admin, p, titre="Essai").content))
        return wb

    def test_espagnol_sans_contenus_traduits(self):
        self.assertNotIn("es", L.codes_actifs())
        wb = self.exporter("es")
        self.assertEqual(wb.sheetnames[0], "Léame")
        valeurs = wb.worksheets[1]
        tete = [c.value for c in next(valeurs.iter_rows(max_row=1))]
        self.assertIn("Ejercicio", tete)
        self.assertIn("Effectif", [c.value for c in next(valeurs.iter_rows(min_row=2, max_row=2))])  # contenu : repli

    def test_francais_et_langue_choisie_inchanges(self):
        self.assertEqual(self.exporter("fr").sheetnames[0], "À lire")
        self.assertEqual(self.exporter("es", choisie="fr").sheetnames[0], "À lire")  # langue choisie dans l'export
