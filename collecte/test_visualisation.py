"""Visualisation : valeurs validées seulement ou brouillons compris, périmètre, graphiques, pages par thème et par KPI."""
from decimal import Decimal

from django.urls import reverse


from . import saisie as S
from . import visualisation as V
from .aides_tests.echanges import Base
from .visuels import ecart, texte_point
from .aides_tests.visualisation import AvecTheme

D = Decimal


class MoteurTests(Base):
    """Par défaut, seules les valeurs validées comptent ; un total qui dépend d'un brouillon attend sa validation."""

    def test_validees_seulement_puis_brouillons(self):
        p26, p25 = self.c.periode, self.c0.periode
        s = V.Source(self.admin, ["EFF", "DBL"])
        self.assertEqual(s.point("EFF", self.e1, p25).valeur, D(100))  # validée (import)
        en_cours = s.point("EFF", self.p, p26)
        self.assertEqual((en_cours.valeur, en_cours.en_attente), (None, True))  # total de deux brouillons : en attente
        s = V.Source(self.admin, ["EFF", "DBL"], brouillons=True)
        p = s.point("EFF", self.p, p26)
        self.assertEqual((p.valeur, p.provisoire), (D(150), True))
        self.assertTrue(s.point("DBL", self.e1, p26).provisoire)  # formule sur un brouillon
        S.valider(self.contrib, self.c, self.eff, self.e1)
        s = V.Source(self.admin, ["EFF", "DBL"])
        self.assertTrue(s.point("EFF", self.p, p26).en_attente)  # E2 reste en brouillon
        self.assertEqual(s.point("DBL", self.e1, p26).valeur, D(220))  # sa source est validée
        S.valider(self.admin, self.c, self.eff, self.e2)
        s = V.Source(self.admin, ["EFF"])
        self.assertEqual(s.point("EFF", self.p, p26).valeur, D(150))
        p = V.Source(self.admin, ["EFF"], brouillons=True).point("EFF", self.p, p26)
        self.assertEqual((p.valeur, p.provisoire), (D(150), False))  # tout est validé : rien de provisoire

    def test_perimetre_du_contributeur(self):
        s = V.Source(self.contrib, ["EFF"], brouillons=True)
        self.assertEqual([o.nom for o in s.organisations()], ["E1"])
        self.assertIsNone(s.point("EFF", self.e2, self.c.periode))
        self.assertIsNone(s.point("EFF", self.p, self.c.periode))  # pas de résultat agrégé hors de ses cases
        self.assertEqual(s.point("EFF", self.e1, self.c.periode).valeur, D(110))

    def test_graphiques(self):
        """Textes communs (valeur, écart avec N-1 : collecte.visuels) ; le reste est dessiné par ECharts (voir test_visuels)."""
        S.valider(self.contrib, self.c, self.eff, self.e1)
        S.valider(self.admin, self.c, self.eff, self.e2)
        s = V.Source(self.admin, ["EFF"])
        point = s.point("EFF", self.e1, self.c.periode)
        n1 = s.point("EFF", self.e1, s.n1(self.c.periode))
        self.assertEqual((texte_point(point, self.eff), *ecart(point, n1)[:2]), ("110 ETP", "▲ +10,0\u202f%", "hausse"))  # espace fine insécable, comme dans les pages
        self.assertEqual([o.nom for o, _, _ in s.comparaison("EFF", self.p, self.c.periode)], ["E1", "E2"])
        parts, total = s.repartition("EFF", self.p, self.c.periode)
        self.assertEqual(([x[0] for x in parts], total), (["E1", "E2"], D(150)))
        self.assertEqual(s.repartition("TX", self.p, self.c.periode), ([], None))  # un pourcentage ne se répartit pas

    def test_organisations_comparees_au_niveau_du_kpi(self):
        """Un KPI saisi au niveau du groupe n'a rien à comparer en dessous (correctif du constat 4)."""
        from referentiel.models import KPI, Niveau

        KPI.objects.create(code="GRP", libelle="Score", type_saisie_id="Saisi", granularite_id=Niveau.GROUP, methode_agregation="Aucune")
        s = V.Source(self.admin, ["GRP", "EFF"])
        self.assertEqual(s.organisations_comparees("GRP", self.g), [])
        self.assertEqual([o.nom for o in s.organisations_comparees("EFF", self.g)], ["Pays"])
        self.assertEqual([o.nom for o in s.organisations_comparees("EFF", self.g, "niveau", Niveau.ENTITY)], ["E1", "E2"])
        self.assertEqual([o.nom for o in s.organisations_comparees("EFF", None, "choisies", ids=[self.e2.pk])], ["E2"])


class PagesTests(AvecTheme):
    """Pages de la Visualisation v2 : vue par défaut, vues automatiques d'un thème et d'un KPI."""

    def test_accueil_theme_kpi(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:visu"))
        self.assertContains(rep, "Vue de départ")  # aucune vue : la vue proposée par l'outil
        self.assertContains(rep, 'id="visu-donnees"')
        rep = self.client.get(reverse("collecte:visu_theme", args=[self.theme.pk]) + f"?org={self.e1.pk}")
        self.assertContains(rep, "Social")
        self.assertContains(rep, "100 ETP")  # 2025 par défaut : la dernière année clôturée
        self.assertContains(rep, "Valeurs validées seulement")
        rep = self.client.get(reverse("collecte:visu_kpi", args=["EFF"]) + f"?periode={self.c.periode.pk}&org={self.p.pk}&brouillons=1")
        for texte in ("150 ETP", "provisoire", "Brouillons compris", "Définition et mode de calcul", "somme des organisations rattachées"):
            self.assertContains(rep, texte)
        rep = self.client.get(reverse("collecte:visu_kpi", args=["TX"]) + f"?org={self.p.pk}")
        donnees = rep.context["donnees_visu"]
        self.assertNotIn("anneau", [v["type"] for v in donnees["visuels"].values() if v["id"] in donnees["ordre"]])  # incompatible : retiré

    def test_vue_par_defaut(self):
        """Ordre : sa vue par défaut, puis la vue d'accueil de son rôle, puis sa première vue, puis la Vue de départ."""
        from .models import AccueilVisu, PreferenceVisu, VueVisu

        comite = VueVisu.objects.create(nom="Comité", partage=True, proprietaire=self.admin)
        perimetre = VueVisu.objects.create(nom="Mon périmètre", partage=True, proprietaire=self.admin)
        perso = VueVisu.objects.create(nom="Perso", proprietaire=self.contrib)
        AccueilVisu.objects.create(role="admin", vue=comite)
        AccueilVisu.objects.create(role="contributeur", vue=perimetre)
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(reverse("collecte:visu")).context["vue"], perimetre)  # vue d'accueil de son rôle
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("collecte:visu")).context["vue"], comite)
        self.client.force_login(self.contrib)
        PreferenceVisu.objects.create(utilisateur=self.contrib, vue_defaut=perso)
        self.assertEqual(self.client.get(reverse("collecte:visu")).context["vue"], perso)  # sa vue par défaut d'abord
        AccueilVisu.objects.filter(role="contributeur").delete()
        PreferenceVisu.objects.all().delete()
        PreferenceVisu.objects.create(utilisateur=self.contrib, ordre=[perso.pk, comite.pk])
        self.assertEqual(self.client.get(reverse("collecte:visu")).context["vue"], perso)  # première de ses onglets
        perimetre.partage = False  # une vue qui n'est plus partagée n'est la vue d'accueil de personne
        perimetre.save()
        AccueilVisu.objects.create(role="contributeur", vue=perimetre)
        self.assertEqual(self.client.get(reverse("collecte:visu")).context["vue"], perso)
        VueVisu.objects.filter(pk=perso.pk).delete()
        PreferenceVisu.objects.all().delete()
        self.assertEqual(self.client.get(reverse("collecte:visu")).context["vue"], comite)  # première vue (partagée)
        VueVisu.objects.all().delete()
        self.assertContains(self.client.get(reverse("collecte:visu")), "Vue de départ")

    def test_contributeur(self):
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(reverse("collecte:visu_kpi", args=["EFF"])).status_code, 200)
        self.assertEqual(self.client.get(reverse("collecte:visu_kpi", args=["DBL"])).status_code, 404)  # hors de ses cases
        rep = self.client.get(reverse("collecte:visu_theme", args=[self.theme.pk]))
        self.assertContains(rep, "Effectif")
        self.assertNotContains(rep, ">Double<")


class RedirectionsTests(AvecTheme):
    """Les anciennes adresses des tableaux mènent à leur vue (favoris conservés)."""

    def test_anciennes_adresses(self):
        import importlib

        from django.apps import apps

        from .models import TableauVisu, VueVisu

        t = TableauVisu.objects.create(nom="Ancien", proprietaire=self.admin, tuiles=[{"type": "chiffre", "kpi": "EFF"}])
        perso = TableauVisu.objects.create(nom="Perso", proprietaire=self.contrib, tuiles=[])
        importlib.import_module("collecte.migrations.0023_tableaux_en_vues").tableaux_en_vues(apps, None)
        v = VueVisu.objects.get(ancien_tableau=t.pk)
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:visu_tableau", args=[t.pk]) + "?periode=5&org=2&brouillons=1")
        self.assertRedirects(rep, reverse("collecte:visu_vue", args=[v.pk]) + "?periode=5&org=2&brouillons=1", fetch_redirect_response=False)
        rep = self.client.get(reverse("collecte:visu_tableau_modifier", args=[t.pk]))
        self.assertRedirects(rep, reverse("collecte:visu_vue", args=[v.pk]) + "?modifier=1", fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("collecte:visu_tableau_nouveau")), reverse("collecte:visu_vue_nouvelle"),
                             fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("collecte:visu_tableau_nouveau") + f"?theme={self.theme.pk}"),
                             reverse("collecte:visu_theme", args=[self.theme.pk]) + "?modifier=1", fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("collecte:visu_tableau", args=[perso.pk])).status_code, 404)  # pas le sien
        self.assertEqual(self.client.get(reverse("collecte:visu_tableau", args=[99999])).status_code, 404)

    def test_kpi_disparu(self):
        from .models import VueVisu

        v = VueVisu.objects.create(nom="Ancien", proprietaire=self.admin, visuels=[{"id": "a", "type": "chiffre", "kpis": ["EFF"]},
                                                                                  {"id": "b", "type": "chiffre", "kpis": ["SUPPRIME"]}])
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("collecte:visu_vue", args=[v.pk])), "plus disponible")
