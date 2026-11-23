"""Corbeille : suppression sans question des exports enregistrés, listes de KPI et vues de la
Visualisation, « Annuler » pendant 30 jours (la personne qui a supprimé, ou un administrateur), purge ensuite ; et tri
des listes par le serveur (Cohérence, Historique)."""
import datetime
import json
from io import StringIO

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from referentiel.models import Utilisateur

from .models import AccueilVisu, Alerte, Journal, ReglageExport, SelectionKPI, VueVisu, purger_corbeille
from .aides_tests.lecture_seule import Base

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class SuppressionExportTests(Base):
    def setUp(self):
        super().setUp()
        self.r = ReglageExport.objects.create(nom="Mon export", proprietaire=self.contrib, parametres={})

    def test_supprimer_puis_annuler(self):
        self.client.force_login(self.contrib)
        rep = self.client.post(reverse("collecte:echanges_supprimer_reglage", args=[self.r.pk]), follow=True)
        # sans question : l'export disparaît partout, le message « Annuler » est sur la page suivante (une fois)
        self.assertFalse(ReglageExport.objects.filter(pk=self.r.pk).exists())
        self.assertTrue(ReglageExport.tous.filter(pk=self.r.pk, supprime_par=self.contrib).exists())
        url = reverse("collecte:corbeille_restaurer", args=["export", self.r.pk])
        self.assertContains(rep, f'action="{url}"')
        self.assertContains(rep, "Mon export")
        self.assertNotContains(rep, 'class="nom-export">Mon export')  # plus dans la liste
        self.assertNotContains(self.client.get(reverse("collecte:echanges")), f'action="{url}"')  # une seule fois
        self.assertEqual(self.client.get(reverse("collecte:echanges_exporter") + f"?modele={self.r.pk}").status_code, 302)
        self.assertTrue(Journal.objects.filter(action="suppression_corbeille", objet="ReglageExport", objet_id=str(self.r.pk)).exists())
        # « Annuler » : de retour, noté au Journal
        rep = self.client.post(url, {"suivant": reverse("collecte:echanges")})
        self.assertRedirects(rep, reverse("collecte:echanges"))
        self.assertTrue(ReglageExport.objects.filter(pk=self.r.pk).exists())
        self.assertTrue(Journal.objects.filter(action="restauration_corbeille", objet="ReglageExport").exists())
        # le Journal nomme l'export, même supprimé
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:admin_journal") + "?vue=admin&famille=corbeille")
        self.assertContains(rep, "Mon export")

    def test_qui_peut_restaurer(self):
        self.r.supprimer(self.contrib)
        url = reverse("collecte:corbeille_restaurer", args=["export", self.r.pk])
        self.client.force_login(self.autre)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.admin)  # un administrateur peut restaurer
        self.assertEqual(self.client.post(url, **FETCH).json()["ok"], True)
        self.assertTrue(ReglageExport.objects.filter(pk=self.r.pk).exists())
        self.assertEqual(self.client.post(url).status_code, 404)  # plus dans la corbeille

    def test_apres_30_jours_plus_restaurable_puis_efface(self):
        self.r.supprimer(self.contrib)
        ReglageExport.tous.filter(pk=self.r.pk).update(supprime_le=timezone.now() - datetime.timedelta(days=31))
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.post(reverse("collecte:corbeille_restaurer", args=["export", self.r.pk])).status_code, 403)
        sortie = StringIO()
        call_command("purge_deleted", stdout=sortie)
        self.assertIn("1 deleted item(s)", sortie.getvalue())
        self.assertFalse(ReglageExport.tous.filter(pk=self.r.pk).exists())

    def test_une_suppression_purge_les_anciennes(self):
        vieux = ReglageExport.objects.create(nom="Vieux", proprietaire=self.contrib, parametres={})
        vieux.supprimer(self.contrib)
        ReglageExport.tous.filter(pk=vieux.pk).update(supprime_le=timezone.now() - datetime.timedelta(days=40))
        self.r.supprimer(self.contrib)
        self.assertFalse(ReglageExport.tous.filter(pk=vieux.pk).exists())
        self.assertTrue(ReglageExport.tous.filter(pk=self.r.pk).exists())
        self.assertEqual(purger_corbeille(), 0)

    def test_type_inconnu(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post("/corbeille/campagne/1/restaurer/").status_code, 404)


class SuppressionListeTests(Base):
    def setUp(self):
        super().setUp()
        self.s = SelectionKPI.objects.create(nom="Essentiels", proprietaire=self.contrib)
        self.s.kpis.set(["EFF", "TX"])

    def test_dans_le_choix_des_kpi_puis_annuler(self):
        self.client.force_login(self.contrib)
        rep = self.client.post(reverse("collecte:echanges_listes"), {"action": "supprimer", "id": self.s.pk}).json()
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["annulation"]["url"], reverse("collecte:corbeille_restaurer", args=["liste", self.s.pk]))
        self.assertEqual(rep["annulation"]["bouton"], "Annuler")
        self.assertFalse(SelectionKPI.visibles(self.contrib).exists())
        self.assertNotContains(self.client.get(reverse("collecte:echanges_listes_page")), "Essentiels")
        # pas de message en double sur la page suivante : le script l'a déjà affiché
        self.assertNotContains(self.client.get(reverse("collecte:echanges")), f'action="{rep["annulation"]["url"]}"')
        rep = self.client.post(rep["annulation"]["url"], **FETCH).json()
        self.assertEqual((rep["id"], rep["nom"], rep["kpis"]), (self.s.pk, "Essentiels", ["EFF", "TX"]))
        self.assertTrue(SelectionKPI.visibles(self.contrib).exists())

    def test_page_des_listes_sans_question(self):
        self.client.force_login(self.contrib)
        page = self.client.get(reverse("collecte:echanges_listes_page"))
        self.assertNotContains(page, "<form method=\"post\" data-confirmer")
        rep = self.client.post(reverse("collecte:echanges_listes_page"), {"action": "supprimer", "id": self.s.pk}, follow=True)
        self.assertContains(rep, reverse("collecte:corbeille_restaurer", args=["liste", self.s.pk]))
        self.assertEqual(SelectionKPI.tous.get(pk=self.s.pk).kpis.count(), 2)  # rien d'effacé


class SuppressionVueTests(Base):
    VISUELS = [{"type": "chiffre", "kpis": ["EFF"]}]

    def test_vue_partagee_d_accueil(self):
        v = VueVisu.objects.create(nom="Comité", proprietaire=self.admin, partage=True, visuels=self.VISUELS)
        AccueilVisu.objects.create(role="contributeur", vue=v)
        self.client.force_login(self.admin)
        rep = self.client.post(reverse("collecte:visu_vue_supprimer", args=[v.pk])).json()
        self.assertEqual(rep["annulation"]["url"], reverse("collecte:corbeille_restaurer", args=["vue", v.pk]))
        self.assertIn(rep["annulation"]["url"], self.client.get(rep["url"]).content.decode())  # page suivante
        self.assertIsNone(AccueilVisu.vue_de(self.contrib))  # plus la vue d'accueil tant qu'elle est supprimée
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(reverse("collecte:visu_vue", args=[v.pk])).status_code, 404)
        self.client.force_login(self.admin)
        rep = self.client.post(reverse("collecte:corbeille_restaurer", args=["vue", v.pk]))
        self.assertRedirects(rep, reverse("collecte:visu_vue", args=[v.pk]), fetch_redirect_response=False)
        self.assertEqual(AccueilVisu.vue_de(self.contrib), v)  # de nouveau la vue d'accueil

    def test_lecteur_supprime_et_restaure_sa_vue(self):
        v = VueVisu.objects.create(nom="Moi", proprietaire=self.lecteur, visuels=self.VISUELS)
        autre = VueVisu.objects.create(nom="Autre", proprietaire=self.auditeur, visuels=self.VISUELS)
        autre.supprimer(self.auditeur)
        self.client.force_login(self.lecteur)
        self.assertEqual(self.client.post(reverse("collecte:visu_vue_supprimer", args=[v.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse("collecte:corbeille_restaurer", args=["vue", v.pk])).status_code, 302)
        self.assertTrue(VueVisu.objects.filter(pk=v.pk).exists())
        # ce qu'une autre personne a supprimé : non
        self.assertEqual(self.client.post(reverse("collecte:corbeille_restaurer", args=["vue", autre.pk])).status_code, 403)

    def test_limite_des_vues_ne_compte_pas_la_corbeille(self):
        from parametres.models import Instance

        i = Instance.courante()
        i.vues_personnelles_max = 1
        i.save()
        v = VueVisu.objects.create(nom="Une", proprietaire=self.contrib, visuels=self.VISUELS)
        v.supprimer(self.contrib)
        self.client.force_login(self.contrib)
        rep = self.client.post(reverse("collecte:visu_vue_creer"), json.dumps({"nom": "Deux", "visuels": self.VISUELS}),
                               content_type="application/json")
        self.assertEqual(rep.status_code, 201)


class TriServeurTests(Base):
    def test_coherence_triee_avant_de_couper(self):
        for nom, kpi, org in (("b", self.eff, self.e2), ("a", self.taux, self.e1)):
            Alerte.objects.create(campagne=self.c, kpi=kpi, organisation=org, controle=Alerte.Controle.FORMAT, message=nom)
        self.client.force_login(self.admin)
        url = reverse("collecte:coherence") + f"?campagne={self.c.pk}&statut=toutes"
        noms = lambda rep: [a.organisation.nom for a in rep.context["alertes"]]  # noqa: E731
        self.assertEqual(noms(self.client.get(url + "&tri-alertes=organisation")), ["E1", "E2"])
        self.assertEqual(noms(self.client.get(url + "&tri-alertes=-organisation")), ["E2", "E1"])
        rep = self.client.get(url + "&tri-alertes=-kpi")
        self.assertEqual([a.kpi_id for a in rep.context["alertes"]], ["TX", "EFF"])  # Taux, puis Effectif
        self.assertContains(rep, 'id="alertes" data-triable')
        self.assertContains(rep, 'data-tri-col="organisation"')

    def test_historique_par_date_et_par_auteur(self):
        Journal.ecrire(self.contrib, "reglage_identite", self.admin, "", "", "1")
        Journal.ecrire(self.admin, "reglage_identite", self.admin, "", "", "2")
        Journal.ecrire(None, "reglage_identite", self.admin, "", "", "3")
        Journal.objects.filter(apres="1").update(date=timezone.now() - datetime.timedelta(days=2))
        Journal.objects.filter(apres="2").update(date=timezone.now() - datetime.timedelta(days=1))
        self.client.force_login(self.admin)
        url = reverse("collecte:admin_journal") + "?vue=admin"
        ordre = lambda q: [e.apres for e in self.client.get(url + q).context["entrees"]]  # noqa: E731
        self.assertEqual(ordre(""), ["3", "2", "1"])  # le plus récent d'abord
        self.assertEqual(ordre("&tri-journal=date"), ["1", "2", "3"])
        self.assertEqual(ordre("&tri-journal=auteur"), ["2", "1", "3"])  # admin, Camille, puis le système
        rep = self.client.get(url)
        self.assertContains(rep, 'aria-sort="descending"')
        self.assertContains(rep, "tri-journal=date")  # le lien « Date » remet dans l'autre sens

    def test_tableaux_triables_marques(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:admin_comptes"))
        self.assertContains(rep, 'id="table-comptes" data-triable')
        self.assertContains(rep, 'data-tri-col="connexion"')
        rep = self.client.get(reverse("collecte:tableau_de_bord") + f"?campagne={self.c.pk}")
        self.assertContains(rep, 'data-triable data-tri-arbre')
        self.assertContains(rep, 'id="table-spoc" data-triable')
        self.assertContains(rep, 'data-tri-col="taux"')
        self.assertNotContains(self.client.get(reverse("collecte:tableau_de_bord") + f"?campagne={self.c.pk}&tri=taux"),
                               "data-triable data-tri-arbre")
        self.assertEqual(Utilisateur.objects.filter(pk=self.admin.pk).count(), 1)
