"""Suites de la corbeille : « Récemment supprimés » dans Mon compte et pour l'administrateur,
délai de la corbeille réglable (Paramètres › Hébergement), ménage de la nuit (sessions terminées, corbeille)."""
import datetime
import logging
from io import StringIO

from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from espaces import contexte as ESP
from parametres.libelles import libelle
from parametres.models import Instance

from . import controle_donnees as CD
from .models import Journal, ReglageExport, SelectionKPI, VueVisu, jours_corbeille, purger_corbeille
from .aides_tests.lecture_seule import Base

COMPTE = reverse("collecte:mon_compte")


class RecemmentSupprimesTests(Base):
    def setUp(self):
        super().setUp()
        self.export = ReglageExport.objects.create(nom="Mon export", proprietaire=self.contrib, parametres={})
        self.liste = SelectionKPI.objects.create(nom="Ma liste", proprietaire=self.contrib)
        self.vue = VueVisu.objects.create(nom="Vue du lecteur", proprietaire=self.lecteur)

    def test_mon_compte_liste_et_restaure_sur_place(self):
        self.client.force_login(self.contrib)
        rep = self.client.get(COMPTE)
        self.assertContains(rep, 'id="recemment-supprimes"')
        self.assertContains(rep, "Rien de supprimé récemment")  # état vide : une phrase, avec le délai
        self.assertContains(rep, "pendant 30 jours")
        self.export.supprimer(self.contrib)
        self.liste.supprimer(self.contrib)
        ReglageExport.objects.create(nom="Export d'un autre", proprietaire=self.autre, parametres={}).supprimer(self.autre)
        rep = self.client.get(COMPTE)
        self.assertContains(rep, "Mon export")
        self.assertContains(rep, "Ma liste")
        self.assertContains(rep, "Export enregistré")
        self.assertContains(rep, "encore 30 jours")
        self.assertNotContains(rep, "Export d&#x27;un autre")  # seulement ce que la personne a supprimé
        self.assertNotContains(rep, "Export d'un autre")
        self.assertNotContains(rep, reverse("collecte:admin_supprimes"))  # lien de l'administrateur
        url = reverse("collecte:corbeille_restaurer", args=["export", self.export.pk])
        self.assertContains(rep, f'action="{url}"')
        rep = self.client.post(url, {"suivant": COMPTE + "#recemment-supprimes", "rester": "1"}, follow=True)
        self.assertRedirects(rep, COMPTE + "#recemment-supprimes", fetch_redirect_response=False)
        self.assertContains(rep, "Restauré : « Mon export »")
        self.assertTrue(ReglageExport.objects.filter(pk=self.export.pk, proprietaire=self.contrib).exists())  # à sa place
        self.assertNotContains(rep, f'action="{url}"')
        self.assertTrue(Journal.objects.filter(action="restauration_corbeille", objet="ReglageExport").exists())

    def test_plus_restaurable_n_est_plus_liste(self):
        self.export.supprimer(self.contrib)
        ReglageExport.tous.filter(pk=self.export.pk).update(supprime_le=timezone.now() - datetime.timedelta(days=31))
        self.client.force_login(self.contrib)
        self.assertNotContains(self.client.get(COMPTE), "Mon export")

    def test_lecture_seule_ses_vues(self):
        self.vue.supprimer(self.lecteur)
        self.export.supprimer(self.contrib)
        self.client.force_login(self.lecteur)
        rep = self.client.get(COMPTE)
        self.assertContains(rep, "Vue du lecteur")
        self.assertNotContains(rep, "Mon export")
        # « Restaurer » depuis Mon compte : permis (ce qu'il a lui-même supprimé), on reste sur Mon compte
        rep = self.client.post(reverse("collecte:corbeille_restaurer", args=["vue", self.vue.pk]),
                               {"suivant": COMPTE, "rester": "1"})
        self.assertRedirects(rep, COMPTE, fetch_redirect_response=False)
        self.assertTrue(VueVisu.objects.filter(pk=self.vue.pk).exists())
        self.assertContains(self.client.get(COMPTE), "une de vos vues")  # état vide propre à la lecture seule
        self.assertEqual(self.client.get(reverse("collecte:admin_supprimes")).status_code, 403)

    def test_page_de_l_administrateur(self):
        self.export.supprimer(self.contrib)
        self.vue.supprimer(self.lecteur)
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(reverse("collecte:admin_supprimes")).status_code, 403)
        self.client.force_login(self.admin)
        page = reverse("collecte:admin_supprimes")
        # trouvable depuis l'Historique, Paramètres › Hébergement et Mon compte
        self.assertContains(self.client.get(reverse("collecte:admin_journal")), f'href="{page}"')
        self.assertContains(self.client.get(reverse("collecte:admin_journal")), "Récemment supprimés (2)")
        self.assertContains(self.client.get(reverse("parametres:hebergement")), f'href="{page}"')
        self.assertContains(self.client.get(COMPTE), f'href="{page}"')
        rep = self.client.get(page)
        self.assertContains(rep, "Mon export")
        self.assertContains(rep, "Vue du lecteur")
        self.assertContains(rep, f"Supprimé par {self.contrib}")
        self.assertContains(rep, f"Supprimé par {self.lecteur}")
        rep = self.client.post(reverse("collecte:corbeille_restaurer", args=["vue", self.vue.pk]), {"suivant": page, "rester": "1"})
        self.assertRedirects(rep, page, fetch_redirect_response=False)
        self.assertTrue(VueVisu.objects.filter(pk=self.vue.pk, proprietaire=self.lecteur).exists())  # chez son propriétaire
        self.export.restaurer()
        self.assertContains(self.client.get(page), "Rien de supprimé depuis 30 jours")

    def test_rester_ne_suit_pas_une_adresse_exterieure(self):
        self.vue.supprimer(self.lecteur)
        self.client.force_login(self.lecteur)
        rep = self.client.post(reverse("collecte:corbeille_restaurer", args=["vue", self.vue.pk]),
                               {"suivant": "https://exemple.test/", "rester": "1"})
        self.assertRedirects(rep, reverse("collecte:visu_vue", args=[self.vue.pk]), fetch_redirect_response=False)


class DelaiCorbeilleTests(Base):
    def setUp(self):
        super().setUp()
        self.export = ReglageExport.objects.create(nom="Mon export", proprietaire=self.contrib, parametres={})

    def test_reglage_dans_hebergement(self):
        self.client.force_login(self.admin)
        url = reverse("parametres:hebergement")
        rep = self.client.get(url)
        self.assertContains(rep, 'id="reglage-corbeille"')
        self.assertContains(rep, 'name="corbeille_jours"')
        for faux in ("0", "366", "abc"):
            rep = self.client.post(url, {"action": "reglage_corbeille", "corbeille_jours": faux})
            self.assertEqual(rep.status_code, 200, faux)
            self.assertContains(rep, "entre 1 et 365")
        self.assertEqual(Instance.courante().corbeille_jours, 30)
        rep = self.client.post(url, {"action": "reglage_corbeille", "corbeille_jours": "7"})
        self.assertRedirects(rep, url + "#reglage-corbeille", fetch_redirect_response=False)
        self.assertEqual((Instance.courante().corbeille_jours, jours_corbeille()), (7, 7))
        j = Journal.objects.get(action="reglage_corbeille")
        self.assertEqual((j.champ, j.avant, j.apres), ("corbeille_jours", "30", "7"))
        self.client.post(url, {"action": "reglage_corbeille", "corbeille_jours": "7"})  # sans changement : rien au journal
        self.assertEqual(Journal.objects.filter(action="reglage_corbeille").count(), 1)
        # la ligne se lit dans l'Historique (famille Hébergement)
        rep = self.client.get(reverse("collecte:admin_journal") + "?vue=admin&famille=hebergement")
        self.assertContains(rep, "a réglé le délai de la corbeille")
        # un compte non administrateur ne règle rien
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.post(url, {"action": "reglage_corbeille", "corbeille_jours": "100"}).status_code, 403)

    def test_delai_utilise_par_restauration_purge_et_textes(self):
        i = Instance.courante()
        i.corbeille_jours = 7
        i.save()
        self.export.supprimer(self.contrib)
        ReglageExport.tous.filter(pk=self.export.pk).update(supprime_le=timezone.now() - datetime.timedelta(days=8))
        self.client.force_login(self.contrib)
        url = reverse("collecte:corbeille_restaurer", args=["export", self.export.pk])
        rep = self.client.post(url)
        self.assertEqual(rep.status_code, 403)
        self.assertIn("pendant 7 jours", libelle("messages.corbeille.non_restaurable", n=jours_corbeille()))  # motif du refus
        self.assertContains(self.client.get(COMPTE), "pendant 7 jours")
        self.assertContains(self.client.get(reverse("collecte:confidentialite")), "7 jours après la suppression")
        sortie = StringIO()
        call_command("purge_deleted", stdout=sortie)
        self.assertIn("1 deleted item(s) erased for good (kept 7 days)", sortie.getvalue())
        self.assertFalse(ReglageExport.tous.filter(pk=self.export.pk).exists())

    def test_delai_plus_long_garde_plus_longtemps(self):
        i = Instance.courante()
        i.corbeille_jours = 90
        i.save()
        self.export.supprimer(self.contrib)
        ReglageExport.tous.filter(pk=self.export.pk).update(supprime_le=timezone.now() - datetime.timedelta(days=60))
        self.assertEqual(purger_corbeille(), 0)
        self.assertTrue(self.export.__class__.tous.get(pk=self.export.pk).restaurable_par(self.contrib))
        self.client.force_login(self.contrib)
        self.assertContains(self.client.get(COMPTE), "encore 30 jours")


class MenageNocturneTests(Base):
    def _session(self, expire):
        s = SessionStore()
        s["x"] = 1
        s.create()
        Session.objects.filter(session_key=s.session_key).update(expire_date=expire)
        return s.session_key

    def test_sessions_terminees_effacees_les_autres_gardees(self):
        vieille = self._session(timezone.now() - datetime.timedelta(hours=1))
        valide = self._session(timezone.now() + datetime.timedelta(hours=1))
        with self.assertLogs("reporting.controle", logging.INFO) as journal:
            sessions, elements = CD.menage_nocturne([ESP.PRINCIPAL])
        self.assertGreaterEqual(sessions, 1)
        self.assertFalse(Session.objects.filter(session_key=vieille).exists())
        self.assertTrue(Session.objects.filter(session_key=valide).exists())
        self.assertTrue(any("Nightly clean-up" in l and "expired session(s)" in l for l in journal.output))

    def test_corbeille_purgee_la_nuit(self):
        e = ReglageExport.objects.create(nom="Vieux", proprietaire=self.contrib, parametres={})
        e.supprimer(self.contrib)
        ReglageExport.tous.filter(pk=e.pk).update(supprime_le=timezone.now() - datetime.timedelta(days=40))
        self.assertEqual(CD.menage_nocturne([ESP.PRINCIPAL])[1], 1)
        self.assertFalse(ReglageExport.tous.filter(pk=e.pk).exists())

    def test_planificateur_fait_le_menage_au_lancement(self):
        from unittest import mock

        from django.db import connections

        appels = []

        class Fin(Exception):
            pass

        def dormir(_):
            raise Fin

        with mock.patch.object(CD, "menage_nocturne", side_effect=lambda codes: appels.append(codes)), \
                mock.patch.object(CD, "controler_et_enregistrer", return_value=None), \
                mock.patch.object(connections, "close_all"), mock.patch.object(CD.time, "sleep", side_effect=dormir):
            with self.assertRaises(Fin):
                CD.planifier("03:30")
        self.assertEqual(len(appels), 1)
