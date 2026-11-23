"""Pages Import / Export (étape 4) : accueil par besoin, constructeur d'export en 5 questions (résumé, aperçu), sélections de
KPI réutilisables (personnelles ou partagées par l'admin), dans l'export et le fichier à remplir."""
import io

from django.test import SimpleTestCase
from django.urls import reverse
from openpyxl import load_workbook

from referentiel.models import Utilisateur

from . import exports as E
from . import imports as I
from .models import ReglageExport, SelectionKPI
from .aides_tests.echanges import Base
from . import saisie as S
from .aides_tests.revue_admin import Base as BaseAdmin
from collecte.outils_tests import html_de
from referentiel.models import Attribution


class MesExportsTests(Base):
    """Import / Export s'ouvre sur « Mes exports » : la liste, un clic pour télécharger ; le constructeur sur demande."""

    def test_liste_d_arrivee(self):
        url = reverse("collecte:echanges")
        self.client.force_login(self.contrib)
        rep = self.client.get(url)
        revue = ReglageExport.objects.get(nom="Rapport de revue de l'exercice")  # « Relire avant validation » : export partagé
        self.assertContains(rep, f"?modele={revue.pk}&amp;telecharger=1")
        self.assertContains(rep, 'aria-label="Télécharger « Rapport de revue de l')
        self.assertContains(rep, "Voir les réglages")  # partagé : le contributeur ne le modifie pas
        self.assertContains(rep, "Nouvel export")
        self.assertNotContains(rep, 'data-ordre-modeles="')  # l'ordre se règle par l'admin
        for absent in ("Configuration complète", "Pour qui", reverse("collecte:admin_reprise")):
            self.assertNotContains(rep, absent)
        self.client.force_login(self.admin)
        rep = self.client.get(url)
        self.assertContains(rep, 'data-ordre-modeles="')
        self.assertContains(rep, 'aria-label="Modifier « Rapport de revue de l')

    def test_modeles_fournis_dans_la_langue_de_la_page(self):
        """Les modèles fournis restés tels quels s'affichent dans la langue de la personne ; un modèle renommé garde
        le texte écrit par l'administrateur."""
        csv = ReglageExport.objects.get(nom="CSV pour Power BI")
        self.client.force_login(self.contrib)
        self.client.post(reverse("langue"), {"langue": "en"})
        rep = self.client.get(reverse("collecte:echanges")).content.decode()
        self.assertIn("CSV for Power BI", rep)
        self.assertNotIn("CSV pour Power BI", rep)
        self.assertNotIn("Ce qui manque encore pour l'exercice en cours", rep)
        self.assertIn("CSV for Power BI", self.client.get(reverse("collecte:echanges_exporter") + f"?modele={csv.pk}").content.decode())
        ReglageExport.objects.filter(pk=csv.pk).update(nom="Mon CSV")
        rep = self.client.get(reverse("collecte:echanges")).content.decode()
        self.assertIn("Mon CSV", rep)
        self.assertIn("Base de données en CSV standard", rep)  # description de l'ancien modèle fourni, gardée telle quelle
        self.client.post(reverse("langue"), {"langue": "es"})
        self.assertIn("Casillas pendientes", self.client.get(reverse("collecte:echanges")).content.decode())

    def test_constructeur_sur_demande(self):
        self.client.force_login(self.contrib)
        url = reverse("collecte:echanges_exporter")
        self.assertRedirects(self.client.get(url), reverse("collecte:echanges"))  # plus d'export ouvert d'office
        self.assertRedirects(self.client.get(url + "?modele=999999"), reverse("collecte:echanges"))
        rep = self.client.post(url, {"action": "copier", "nom": "Mes effectifs", "presentation": "base", "exercices": ["courant"]})
        self.assertRedirects(rep, reverse("collecte:echanges"))  # enregistré : retour à la liste
        self.assertContains(self.client.get(reverse("collecte:echanges")), "Mes effectifs")



class OngletListesTests(Base):
    """Onglet « Listes de KPI » : créer une liste (nom + KPI cochés), la modifier, la supprimer, s'en servir pour un export
    ou un fichier à remplir ; une liste partagée reste en lecture seule pour les autres."""

    def test_creer_modifier_supprimer(self):
        self.client.force_login(self.contrib)
        url = reverse("collecte:echanges_listes_page")
        rep = self.client.get(url)
        self.assertContains(rep, "Aucune liste pour l")
        self.assertContains(rep, 'aria-current="page">Listes de KPI')
        rep = self.client.get(url + "?nouvelle=1")
        self.assertContains(rep, "Créer une liste de KPI")
        self.assertContains(rep, 'name="kpis" value="EFF"')
        self.assertNotContains(rep, 'value="DBL"')
        rep = self.client.post(url, {"nom": "Effectifs", "kpis": ["EFF", "DBL"], "partage": "on"}, follow=True)
        s = SelectionKPI.objects.get(nom="Effectifs")
        self.assertEqual((list(s.kpis.values_list("code", flat=True)), s.partage), (["EFF"], False))
        self.assertContains(rep, "Liste « Effectifs » enregistrée (1 KPI)")
        # ni « Exporter » ni « Fichier à remplir » : la liste se choisit dans l'export 
        self.assertNotContains(rep, f"?nouveau=1&amp;selection={s.pk}")
        self.assertNotContains(rep, f"importer/?selection={s.pk}")
        self.assertContains(rep, f"?liste={s.pk}")
        self.assertContains(self.client.get(url + f"?liste={s.pk}"), "Modifier la liste « Effectifs »")
        self.client.post(url, {"id": s.pk, "nom": "Effectifs RH", "kpis": ["EFF", "TX"]})
        s.refresh_from_db()
        self.assertEqual((s.nom, sorted(s.kpis.values_list("code", flat=True))), ("Effectifs RH", ["EFF", "TX"]))
        rep = self.client.post(url, {"nom": "Effectifs RH", "kpis": ["EFF"]})  # même nom qu'une autre liste
        self.assertContains(rep, "existe déjà")
        self.assertContains(self.client.post(url, {"nom": "Vide"}), "Cochez au moins un KPI")
        self.client.post(url, {"action": "supprimer", "id": s.pk})
        self.assertFalse(SelectionKPI.objects.filter(pk=s.pk).exists())

    def test_liste_partagee_en_lecture_seule(self):
        s = SelectionKPI.objects.create(nom="Social", proprietaire=self.admin, partage=True)
        s.kpis.set(["EFF"])
        self.client.force_login(self.contrib)
        url = reverse("collecte:echanges_listes_page")
        rep = self.client.get(url)
        self.assertContains(rep, "Social")
        self.assertNotContains(rep, f"?liste={s.pk}")
        self.assertEqual(self.client.post(url, {"id": s.pk, "nom": "X", "kpis": ["EFF"]}).status_code, 403)
        self.assertEqual(self.client.post(url, {"action": "supprimer", "id": s.pk}).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(url, {"id": s.pk, "nom": "Social", "kpis": ["EFF", "TX"], "partage": "on"})
        self.assertTrue(SelectionKPI.objects.get(pk=s.pk).partage)


class FichiersConfigurationTests(Base):
    """Administration › Fichiers de configuration : la configuration en fichier et la reprise, réservées à l'admin."""

    def test_rubrique_admin(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:admin_fichiers"))
        # une tâche principale en trois étapes, puis la liste « Autres fichiers »
        for titre in ("Modifier les réglages en masse", "Téléchargez le classeur", "Modifiez-le dans Excel", "Importez-le",
                      "Autres fichiers", "Modèle vierge", "KPI seuls (CSV)", "Référentiels", "Traductions",
                      "un ancien système"):
            self.assertContains(rep, titre)
        self.assertContains(rep, 'class="actif">Fichiers de configuration</a>')  # sous-navigation de l'administration
        self.assertContains(rep, reverse("parametres:hebergement"))  # sauvegarde complète de la base
        self.assertContains(self.client.get(reverse("collecte:admin_accueil")), reverse("collecte:admin_fichiers"))
        self.assertContains(self.client.get(reverse("collecte:admin_reprise")), 'class="actif">Fichiers de configuration</a>')

    def test_menu_compact_des_rubriques(self):
        """Téléphone : un bouton « Rubrique : <actuelle> » (masqué sans script) commande la liste des rubriques ; les
        pages des paramètres ont le même menu « Page : <actuelle> »."""
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:admin_fichiers"))
        self.assertContains(rep, 'aria-expanded="false" aria-controls="rubriques-admin" hidden>Rubrique : Fichiers de configuration')
        self.assertContains(rep, '<nav class="sous-onglets" id="rubriques-admin"')
        self.assertContains(self.client.get(reverse("collecte:admin_accueil")), "Rubrique : Vue d&#x27;ensemble")
        rep = self.client.get(reverse("parametres:hebergement"))
        self.assertContains(rep, "Rubrique : Paramètres")
        self.assertContains(rep, 'aria-controls="pages-parametres" hidden>Page : Hébergement')
        rep = self.client.get(reverse("collecte:referentiel"))  # trois onglets des référentiels : toujours affichés
        self.assertContains(rep, "Rubrique : Référentiels")
        self.assertNotContains(rep, "Page : ")

    def test_reservee_a_l_admin(self):
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(reverse("collecte:admin_fichiers")).status_code, 403)
        self.assertEqual(self.client.get(reverse("collecte:admin_reprise")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("collecte:echanges")), "Fichiers de configuration")

    def test_anciennes_adresses_redirigees(self):
        self.client.force_login(self.admin)
        rep = self.client.get("/import-export/configuration/?telecharger=vierge")
        self.assertRedirects(rep, reverse("collecte:admin_fichiers") + "?telecharger=vierge", fetch_redirect_response=False)
        rep = self.client.get("/import-export/reprise/?etape=fichier")
        self.assertRedirects(rep, reverse("collecte:admin_reprise") + "?etape=fichier", fetch_redirect_response=False)


class ChoixDesKpiTests(Base):
    """Choix des KPI intégré à l'export et au fichier à remplir : tous, une liste sauvegardée, ou cochés un à un ; « Garder
    cette liste » (personnelle, ou partagée par l'admin). L'ancien onglet Sélections renvoie à Mes exports."""

    def test_contributeur_garde_une_liste_de_ses_kpi(self):
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:echanges_exporter") + "?nouveau=1")
        self.assertContains(rep, 'name="kpis" value="EFF"')
        self.assertNotContains(rep, 'value="DBL"')  # hors de ses cases
        url = reverse("collecte:echanges_listes")
        j = self.client.post(url, {"action": "garder", "nom": "Effectifs", "kpis": ["EFF", "DBL"], "partage": "on"}).json()
        s = SelectionKPI.objects.get(nom="Effectifs")
        self.assertEqual((j["kpis"], s.partage, s.proprietaire), (["EFF"], False, self.contrib))  # seul l'admin partage
        self.client.post(url, {"action": "garder", "nom": "Effectifs", "kpis": ["EFF", "TX"]})  # même nom : mise à jour
        self.assertEqual(sorted(SelectionKPI.objects.get(pk=s.pk).kpis.values_list("code", flat=True)), ["EFF", "TX"])
        self.assertEqual(self.client.post(url, {"action": "garder", "nom": "Vide"}).status_code, 400)  # au moins un KPI
        self.assertEqual(self.client.post(url, {"action": "garder", "kpis": ["EFF"]}).status_code, 400)  # un nom
        self.assertContains(self.client.get(reverse("collecte:echanges_importer")), "Effectifs · 2 KPI")
        self.assertRedirects(self.client.get("/import-export/selections/"), reverse("collecte:echanges_listes_page"))
        self.client.post(url, {"action": "supprimer", "id": s.pk})
        self.assertFalse(SelectionKPI.objects.filter(pk=s.pk).exists())

    def test_liste_partagee_par_l_admin_lecture_seule_pour_les_autres(self):
        s = SelectionKPI.objects.create(nom="Social", proprietaire=self.admin, partage=True)
        s.kpis.set(["EFF", "TX"])
        SelectionKPI.objects.create(nom="Perso admin", proprietaire=self.admin)
        url = reverse("collecte:echanges_listes")
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:echanges_exporter") + "?nouveau=1")
        self.assertContains(rep, "Social · 2 KPI · partagée")
        self.assertNotContains(rep, "Perso admin")  # personnelle : invisible pour les autres
        self.assertEqual(self.client.post(url, {"action": "supprimer", "id": s.pk}).status_code, 403)
        self.client.post(url, {"action": "garder", "nom": "Social", "kpis": ["EFF"]})  # même nom : sa propre copie
        self.assertEqual(SelectionKPI.objects.filter(nom="Social").count(), 2)
        self.assertEqual(s.kpis.count(), 2)
        self.client.force_login(self.admin)
        self.client.post(url, {"action": "garder", "nom": "Social", "kpis": ["DBL"], "partage": "on"})  # l'admin la met à jour
        self.assertEqual(list(SelectionKPI.objects.get(pk=s.pk).kpis.values_list("code", flat=True)), ["DBL"])

    def test_kpi_coches_un_a_un(self):
        p = E.Parametres.depuis({"exercices": ["2026"], "choix_kpi": "choix", "kpis": ["EFF", "INCONNU"], "selection": "1"})
        self.assertEqual((p.kpis, p.selection), (["EFF"], ""))  # code inconnu écarté ; la liste ignorée
        self.assertEqual({l.kpi.code for l in E.collecter(self.admin, p)}, {"EFF"})
        self.assertIn("1 KPI choisi", p.phrase())
        self.assertEqual(E.Parametres.depuis({"choix_kpi": "tous", "kpis": ["EFF"]}).kpis, [])
        self.client.force_login(self.contrib)
        rep = self.client.post(reverse("collecte:echanges_modele"), {"campagne": self.c.pk, "choix_kpi": "choix", "kpis": ["TX"]})
        ws = load_workbook(io.BytesIO(rep.content))["Saisie"]
        self.assertEqual({ws.cell(r, 2).value for r in range(1, ws.max_row + 1)} & {"EFF", "TX"}, {"TX"})
        m = ReglageExport.objects.create(nom="Effectif", parametres=p.en_dict())  # export enregistré : les KPI cochés gardés
        self.assertEqual(E.Parametres.depuis(m.parametres).kpis, ["EFF"])

    def test_export_et_fichier_a_remplir_limites_a_la_selection(self):
        s = SelectionKPI.objects.create(nom="Effectif", proprietaire=self.admin, partage=True)
        s.kpis.set(["EFF"])
        p = E.Parametres.depuis({"exercices": ["2026"], "selection": str(s.pk)})
        self.assertEqual({l.kpi.code for l in E.collecter(self.admin, p)}, {"EFF"})
        self.assertIn("liste « Effectif »", p.phrase())
        self.assertEqual(E.Parametres.depuis({"selection": "99999"}).selection, "")  # sélection inconnue : ignorée
        # export enregistré qui utilise la sélection ; la sélection supprimée, il reprend tous les KPI
        m = ReglageExport.objects.create(nom="Effectif", parametres=p.en_dict(), partage=True)
        self.assertEqual({l.kpi.code for l in E.collecter(self.admin, E.Parametres.depuis(m.parametres))}, {"EFF"})
        s.delete()
        self.assertEqual({l.kpi.code for l in E.collecter(self.admin, E.Parametres.depuis(m.parametres))} >= {"EFF", "TX"}, True)
        s = SelectionKPI.objects.create(nom="Taux", proprietaire=self.contrib)
        s.kpis.set(["TX"])
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:echanges_modele"), {"campagne": self.c.pk, "selection": s.pk})
        ws = load_workbook(io.BytesIO(rep.content))["Saisie"]
        self.assertEqual({ws.cell(r, 2).value for r in range(1, ws.max_row + 1)} & {"EFF", "TX"}, {"TX"})
        self.assertEqual(len(I.lignes_modele(self.contrib, self.c, selection=s)), 1)

    def test_anciens_exports_enregistres_toujours_valables(self):
        for m in ReglageExport.objects.all():  # réglages d'avant les sélections (sans clé « selection »)
            self.assertNotIn("selection", m.parametres)
            p = E.Parametres.depuis(m.parametres)
            self.assertEqual(p.selection, "")
            self.assertTrue(p.phrase())


class ConstructeurTests(Base):
    def test_cinq_questions_resume_et_apercu(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:echanges_exporter") + "?nouveau=1&depart=revue")
        for q in ("Quels KPI ?", "Quelles organisations ?", "Quelle période ?", "Quel fichier ?", "Plus d'options", "En résumé",
                  "Aperçu des 10 premières lignes", "Mes exports"):
            self.assertContains(rep, q)
        contenu = rep.content.decode()
        self.assertLess(contenu.index("Quels KPI ?"), contenu.index("Quelles organisations ?"))  # ordre des questions
        self.assertLess(contenu.index("Quelle période ?"), contenu.index("Quel fichier ?"))
        self.assertEqual(rep.context["p"].presentation, "revue")  # nouvel export parti du rapport de revue
        self.assertNotContains(rep, "Modèle d'export")
        url = reverse("collecte:echanges_resume")
        j = self.client.post(url, {"presentation": "base", "exercices": ["2026"], "contenus": ["valide", "brouillon"],
                                   "niveaux": ["Entity"], "format": "csv"}).json()
        self.assertTrue(j["phrase"].startswith("Base de données CSV : valeurs validées et brouillons, exercice 2026"), j["phrase"])
        self.assertNotIn("apercu", j)
        j = self.client.post(url, {"presentation": "base", "exercices": ["2026"], "contenus": ["valide", "brouillon"], "apercu": "1",
                                   "types": ["saisie", "herite", "calcul"], "niveaux": ["Group", "Country", "Entity"]}).json()
        a = j["apercu"]
        self.assertEqual(a["entetes"][:4], ["Exercice", "Période", "Début de période", "ID KPI"])
        self.assertEqual(len(a["lignes"]), min(10, a["total"]))
        self.assertGreater(a["total"], 0)
        self.assertIn("aucune organisation", self.client.post(url, {"exercices": ["2026"], "niveaux": []}).json()["phrase"])

    def test_gros_export_conseille_le_csv(self):
        """Au-delà de 50 000 lignes, le constructeur conseille le CSV (environ 5 fois plus rapide) :
        une aide sous le format, et un avertissement dans l'aperçu quand le format choisi est Excel."""
        from unittest import mock

        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:echanges_exporter") + "?nouveau=1")
        self.assertContains(rep, "Très gros export (plus de 50\u202f000 lignes")
        url = reverse("collecte:echanges_resume")
        corps = {"presentation": "base", "exercices": ["2026"], "contenus": ["valide", "brouillon"], "apercu": "1",
                 "types": ["saisie", "herite", "calcul"], "niveaux": ["Group", "Country", "Entity"]}
        self.assertFalse(self.client.post(url, {**corps, "format": "xlsx"}).json()["apercu"]["gros"])  # petite démo
        with mock.patch.object(E, "SEUIL_GROS_EXPORT", 1):
            self.assertTrue(self.client.post(url, {**corps, "format": "xlsx"}).json()["apercu"]["gros"])
            self.assertFalse(self.client.post(url, {**corps, "format": "csv"}).json()["apercu"]["gros"])  # déjà en CSV

    def test_export_partage_avec_une_selection_personnelle_averti(self):
        s = SelectionKPI.objects.create(nom="À moi", proprietaire=self.admin)
        s.kpis.set(["EFF"])
        self.client.force_login(self.admin)
        rep = self.client.post(reverse("collecte:echanges_exporter"), {
            "action": "copier", "nom": "Partagé", "partage": "on", "selection": s.pk, "presentation": "base",
            "exercices": ["courant"]}, follow=True)
        self.assertContains(rep, "est personnelle")
        self.assertEqual(ReglageExport.objects.get(nom="Partagé").parametres["selection"], str(s.pk))

    def test_exporter_ces_kpi_depuis_une_selection(self):
        s = SelectionKPI.objects.create(nom="Mienne", proprietaire=self.contrib)
        s.kpis.set(["EFF"])
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:echanges_exporter") + f"?nouveau=1&selection={s.pk}")
        self.assertEqual(rep.context["p"].selection, str(s.pk))
        autre = Utilisateur.objects.create(username="x", email="x@exemple.test")
        self.client.force_login(autre)  # sélection personnelle d'un autre : ignorée
        rep = self.client.get(reverse("collecte:echanges_exporter") + f"?nouveau=1&selection={s.pk}")
        self.assertEqual(rep.context["p"].selection, "")


class ListesDansLExportTests(Base):
    """Les listes de KPI se retrouvent dans l'export : l'option « Une liste sauvegardée » est toujours proposée ; sans liste,
    un message dit comment en créer une (retour d'essai)."""

    def test_option_toujours_proposee(self):
        self.client.force_login(self.admin)
        url = reverse("collecte:echanges_exporter") + "?nouveau=1"
        h = self.client.get(url).content.decode()
        self.assertIn("data-puce-liste>", h)
        self.assertNotIn("data-aucune-liste hidden", h)  # aucune liste : le message s'affiche
        s = SelectionKPI.objects.create(nom="Mes KPI", proprietaire=self.admin)
        s.kpis.set(["EFF"])
        h = self.client.get(url).content.decode()
        self.assertIn("data-aucune-liste hidden", h)
        self.assertIn("Mes KPI", h)


class ListeDansUnLibelleTests(SimpleTestCase):
    """Une liste de noms passée à une phrase traduite n'est échappée qu'une fois : « chiffre d'affaires » ne s'affiche
    plus « chiffre d&#x27;affaires » (retour d'essai)."""

    def test_echappe_une_seule_fois(self):
        from django.template import Context, Template

        t = Template('{% load collecte %}{% libelle "suivi.echanges.listes.resume_apercu" n=2 apercu=noms|liste %}')
        html = t.render(Context({"noms": ["Chiffre d'affaires", "Effectif <total>"]}))
        self.assertNotIn("&amp;#x27;", html)
        self.assertNotIn("&amp;lt;", html)
        self.assertIn("Chiffre d&#x27;affaires", html)  # une seule fois : le navigateur affiche l'apostrophe
        self.assertIn("&lt;total&gt;", html)  # toujours échappé


class NavigationEtDefautTests(Base):
    def test_contributeur_ouvre_import_export_sur_importer(self):
        self.client.force_login(self.contrib)
        self.assertContains(self.client.get(reverse("collecte:saisie")), f'href="{reverse("collecte:echanges_importer")}"')
        self.assertEqual(self.client.get(reverse("collecte:echanges")).status_code, 200)  # « Mes exports » reste ouvert
        self.client.force_login(self.admin)
        html = self.client.get(reverse("collecte:saisie")).content.decode()
        self.assertIn(f'href="{reverse("collecte:echanges")}"', html)

    def test_nouvel_export_propose_le_tableau_lisible(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:echanges_exporter") + "?nouveau=1")
        self.assertEqual(rep.context["p"].presentation, "tableau")
        rep = self.client.get(reverse("collecte:echanges_exporter") + "?nouveau=1&depart=powerbi")
        self.assertEqual(rep.context["p"].presentation, "base")  # un modèle fourni garde sa présentation


class ImportExportAllegeTests(BaseAdmin):
    def test_listes_de_kpi_sans_resume_ni_raccourcis(self):
        s = SelectionKPI.objects.create(nom="Essentiels", proprietaire=self.admin)
        s.kpis.set(["EFF"])
        html = html_de(self.client, reverse("collecte:echanges_listes_page"))
        self.assertIn("Essentiels", html)
        self.assertNotIn("1 KPI : Effectif", html)  # ni nombre ni noms des KPI sous le nom
        self.assertNotIn("Fichier à remplir", html)
        self.assertNotIn("?nouveau=1&amp;selection=", html)  # plus de bouton « Exporter »
        self.assertNotIn("Une liste regroupe", html)
        self.assertIn("Modifier", html)

    def test_nouvel_export_sans_phrases_ni_suppression_de_liste(self):
        SelectionKPI.objects.create(nom="Essentiels", proprietaire=self.admin).kpis.set(["EFF"])
        html = html_de(self.client, reverse("collecte:echanges_exporter") + "?nouveau=1")
        self.assertNotIn("Téléchargez le fichier tout de suite", html)
        self.assertNotIn("Quand vous cochez ou décochez une organisation", html)
        self.assertNotIn("data-supprimer-liste", html)
        self.assertIn("se mettent à jour seuls", html)
        self.assertIn("data-coller-codes", html)  # coller des codes KPI

    def test_mes_exports_sans_phrase(self):
        html = html_de(self.client, reverse("collecte:echanges"))
        self.assertNotIn("Chaque export garde ses réglages", html)


class ExportHistoriqueTests(BaseAdmin):
    def setUp(self):
        super().setUp()
        for org in (self.e1, self.e2):
            Attribution.objects.create(kpi=self.kpi, organisation=org, utilisateur=self.contrib)
        S.enregistrer(self.contrib, self.c, self.kpi, self.e1, "1234.5", False, "")
        S.enregistrer(self.contrib, self.c, self.kpi, self.e2, "7", False, "")

    def classeur(self, url):
        rep = self.client.get(url)
        self.assertEqual(rep.status_code, 200)
        self.assertIn("attachment;", rep["Content-Disposition"])
        self.assertIn("Historique_", rep["Content-Disposition"])
        ws = load_workbook(io.BytesIO(rep.content)).active
        return [[c.value for c in r] for r in ws.iter_rows()]

    def test_lien_garde_les_filtres(self):
        html = html_de(self.client, reverse("collecte:admin_journal") + f"?org={self.e1.id}")
        self.assertIn(f"org={self.e1.id}", html.split("export-journal")[1].split(">")[0])
        self.assertIn("export=xlsx", html)

    def test_export_filtre_et_nombres(self):
        lignes = self.classeur(reverse("collecte:admin_journal") + f"?org={self.e1.id}&export=xlsx")
        self.assertEqual(lignes[0], ["N°", "Date", "Auteur", "Action", "Élément", "Code KPI", "Code organisation", "Période",
                                     "Champ", "Avant", "Après"])
        objets = {ligne[4] for ligne in lignes[1:]}
        self.assertEqual(objets, {"Effectif · E1 · 2025"})  # le filtre de l'organisation suit dans le fichier
        valeurs = [ligne[10] for ligne in lignes[1:] if ligne[8] == "Valeur"]
        self.assertEqual(valeurs, [1234.5])  # un vrai nombre, pas « 1 234,5 »

    def test_identifiants_pour_l_auditeur(self):
        """Chaque ligne a son numéro, le code du KPI, celui de l'organisation et la période ;
        la recherche de la page retrouve une ligne par son numéro."""
        from collecte.models import Journal

        lignes = self.classeur(reverse("collecte:admin_journal") + f"?org={self.e1.id}&export=xlsx")
        numeros = [ligne[0] for ligne in lignes[1:]]
        self.assertEqual(len(set(numeros)), len(numeros))
        self.assertEqual({(ligne[5], ligne[6], ligne[7]) for ligne in lignes[1:]}, {(self.kpi.code, self.e1.code, "2025")})
        e = Journal.objects.get(pk=int(numeros[0][2:]))
        self.assertEqual(e.objet, "Reponse")
        seule = self.classeur(reverse("collecte:admin_journal") + f"?q={numeros[0]}&export=xlsx")
        self.assertEqual([ligne[0] for ligne in seule[1:]], [numeros[0]])

    def test_auditeur_limite_a_son_perimetre(self):
        aud = Utilisateur.objects.create(username="aud", email="aud@exemple.test", role=Utilisateur.Role.AUDITEUR)
        aud.perimetre_lecture.set([self.e2])
        self.client.force_login(aud)
        lignes = self.classeur(reverse("collecte:historique") + "?export=xlsx")
        self.assertEqual({ligne[4] for ligne in lignes[1:]}, {"Effectif · E2 · 2025"})

    def test_reserve_a_l_admin(self):
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(reverse("collecte:admin_journal") + "?export=xlsx").status_code, 403)
