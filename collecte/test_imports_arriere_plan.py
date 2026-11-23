"""Gros imports de valeurs en arrière-plan (collecte/imports_arriere_plan.py) : même résultat qu'en une fois, barre
d'avancement, « Arrêter », reprise après un redémarrage, un import à la fois, supervision."""
import datetime
import os
import tempfile
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

from django.core.files.storage import default_storage
from django.core.management import call_command
from django.db import transaction
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from referentiel.models import Attribution

from . import imports as I
from . import imports_arriere_plan as AP
from . import saisie as S
from .models import Journal, Reponse, TacheImport
from .outils_tests import xlsx
from .aides_tests.saisie import Base

T = TacheImport.Statut
_planificateur_actif = AP.planificateur_actif  # la vraie (les tests la remplacent : aucun planificateur)


def instantane():
    """Toutes les valeurs de la base (saisies, totaux, calculs, historique), sans les dates."""
    return {(r.periode.debut, r.periode.type, r.kpi_id, r.organisation.nom): (r.valeur, r.texte, r.non_applicable, r.statut,
                                                                              r.origine, r.commentaire, r.saisi_par_id)
            for r in Reponse.objects.select_related("periode", "organisation")}


@override_settings(IMPORT_ARRIERE_PLAN_LIGNES=3)
@mock.patch.object(AP, "BATTEMENT", 0)
@mock.patch.object(AP, "planificateur_actif", lambda: False)
@mock.patch.object(AP, "demarrer_fil", lambda code: None)  # jamais de vrai fil pendant les tests (base de test partagée)
class ImportArrierePlanTests(Base):
    def setUp(self):
        super().setUp()
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.contrib)
        Attribution.objects.create(kpi=self.taux, organisation=self.e2, utilisateur=self.contrib)
        self.url = reverse("collecte:echanges_importer")
        self.lignes = [["ID KPI", "Organisation", "Exercice", "Valeur", "Commentaire"],
                       ["EFF", "E1", 2026, 10, "a"], ["TX", "E1", 2026, 20, ""], ["EFF", "E2", 2026, 30, ""],
                       ["TX", "E2", 2026, 40, "b"], ["EFF", "Nulle part", 2026, 5, ""], ["TX", "E1", 2026, "beaucoup", ""]]

    def deposer(self, user=None, lignes=None, **donnees):
        self.client.force_login(user or self.contrib)
        return self.client.post(self.url, {"action": "verifier", "fichier": xlsx(lignes or self.lignes),
                                           "campagne": self.c.pk, **donnees})

    def lancer(self, executer=True):
        """Confirme l'aperçu : la tâche est créée ; ``executer`` : le fil de secours l'exécute (ici, tout de suite)."""
        with mock.patch.object(AP, "demarrer_fil", (lambda code: AP.traiter_file()) if executer else (lambda code: None)):
            rep = self.client.post(self.url, {"action": "confirmer"})
        t = TacheImport.objects.latest("pk")
        self.assertRedirects(rep, f"{self.url}?tache={t.pk}", fetch_redirect_response=False)
        return t

    # -- même résultat qu'un import fait dans la page -------------------------------------------------------------------
    def test_meme_resultat_qu_en_une_fois(self):
        lignes = self.lignes + [["EFF", "E1", 2025, 7, ""], ["EFF", "E2", 2020, 8, "histo"], ["TX", "E2", 2020, "N/A", ""]]
        options = {"creer_campagnes": "on", "valider": "on"}
        S.enregistrer(self.contrib, self.c, self.eff, self.e2, "3", False, "")
        with transaction.atomic():  # en une fois (seuil au-dessus du fichier)
            with override_settings(IMPORT_ARRIERE_PLAN_LIGNES=1000):
                self.deposer(self.admin, lignes, **options)
                rep = self.client.post(self.url, {"action": "confirmer"})
            self.assertContains(rep, "Import terminé")
            attendu, ecrites = instantane(), rep.context["ecrites"]
            rejets = self.client.session["rejets_import"]["lignes"]
            journal = list(Journal.objects.filter(action="import_valeurs").values_list("apres", flat=True))
            transaction.set_rollback(True)
        self.assertFalse(Reponse.objects.filter(origine=Reponse.Origine.IMPORT).exists())
        with mock.patch.object(I, "PAQUET_IMPORT", 2):  # en arrière-plan, par paquets de 2 lignes
            self.deposer(self.admin, lignes, **options)
            t = self.lancer()
        t.refresh_from_db()
        self.assertEqual((t.statut, t.ecrites, t.faites, t.total), (T.TERMINEE, ecrites, 7, 7))
        self.assertEqual(instantane(), attendu)
        self.assertEqual(list(Journal.objects.filter(action="import_valeurs").values_list("apres", flat=True)), journal)
        rep = self.client.get(f"{self.url}?tache={t.pk}")
        self.assertContains(rep, "Import terminé")
        self.assertEqual(self.client.session["rejets_import"]["lignes"], rejets)
        self.assertFalse(default_storage.exists(t.chemin))  # fichier effacé à la fin, comme aujourd'hui

    def test_sous_le_seuil_rien_ne_change(self):
        with override_settings(IMPORT_ARRIERE_PLAN_LIGNES=1000):
            rep = self.deposer()
            self.assertNotContains(rep, "l'import se fait en arrière-plan")
            rep = self.client.post(self.url, {"action": "confirmer"})
        self.assertContains(rep, "Import terminé")
        self.assertFalse(TacheImport.objects.exists())

    # -- ce que voit la personne ----------------------------------------------------------------------------------------
    def test_barre_d_avancement_page_quittee_puis_retrouvee(self):
        rep = self.deposer()
        self.assertContains(rep, "l'import se fait en arrière-plan")
        t = self.lancer(executer=False)
        self.assertEqual(t.statut, T.ATTENTE)
        self.assertEqual(Journal.objects.get(action="import_arriere_plan").apres, "fichier.xlsx : 6 ligne(s)")
        self.assertTrue(default_storage.exists(t.chemin))  # gardé jusqu'à la fin de la tâche
        with mock.patch.object(AP, "demarrer_fil") as fil:
            rep = self.client.get(self.url)  # page quittée puis retrouvée : l'import en cours s'affiche de lui-même
            fil.assert_called_once()  # sans planificateur, le serveur web le prend
        self.assertContains(rep, 'role="progressbar"')
        self.assertContains(rep, 'aria-valuenow="0"')
        self.assertContains(rep, "Arrêter l'import")
        self.assertContains(rep, "Import en attente – fichier.xlsx")
        with mock.patch.object(AP, "demarrer_fil"):
            d = self.client.get(reverse("collecte:echanges_tache_etat", args=[t.pk])).json()
        self.assertEqual((d["statut"], d["fini"], d["texte"]), ("attente", False, "Démarrage de l'import…"))
        TacheImport.objects.filter(pk=t.pk).update(statut=T.EN_COURS, etape="ecriture", faites=200, total=500, battement=timezone.now())
        d = self.client.get(reverse("collecte:echanges_tache_etat", args=[t.pk])).json()
        self.assertEqual((d["pct"], d["texte"]), (40, "Import : 200 / 500 lignes"))
        rep = self.client.get(self.url)
        self.assertContains(rep, 'aria-valuetext="Import : 200 / 500 lignes"')
        TacheImport.objects.filter(pk=t.pk).update(statut=T.ATTENTE, etape="", faites=0, total=0)
        AP.traiter_file()
        d = self.client.get(reverse("collecte:echanges_tache_etat", args=[t.pk])).json()
        self.assertTrue(d["fini"])
        rep = self.client.get(d["url"])
        self.assertContains(rep, "Import terminé – fichier.xlsx")
        self.assertEqual(rep.context["ecrites"], 4)
        self.assertContains(rep, "Télécharger les lignes rejetées (2)")
        fichier = self.client.get(reverse("collecte:echanges_rejets"))
        self.assertEqual(fichier.status_code, 200)
        self.assertTrue(TacheImport.objects.get().vu)
        self.assertNotContains(self.client.get(self.url), "Import terminé")  # vu : la page revient aux deux étapes
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.taux, organisation=self.e2).valeur, D("0.4"))

    def test_resultat_dans_a_traiter_et_pour_moi(self):
        self.deposer(self.admin)
        t = self.lancer()
        rep = self.client.get(reverse("collecte:admin_accueil"))
        self.assertContains(rep, "Import fini : fichier.xlsx")
        self.assertContains(rep, f"?tache={t.pk}")
        self.client.get(f"{self.url}?tache={t.pk}")
        self.assertNotContains(self.client.get(reverse("collecte:admin_accueil")), "Import fini")
        self.assertContains(self.client.get(reverse("collecte:admin_journal")), "a lancé un import en arrière-plan")
        self.deposer()
        t = self.lancer(executer=False)
        self.assertContains(self.client.get(reverse("collecte:pour_moi")), "Votre import « fichier.xlsx » est en cours (0 %)")

    # -- arrêter ----------------------------------------------------------------------------------------------------------
    def test_arreter_entre_deux_paquets(self):
        self.deposer()
        t = self.lancer(executer=False)
        reel = AP.Suivi.ecriture

        def ecriture(suivi, faites, total, ecrites):  # « Arrêter » cliqué pendant le premier paquet
            reel(suivi, faites, total, ecrites)
            if faites:
                self.client.post(reverse("collecte:echanges_tache_arreter", args=[t.pk]))

        with mock.patch.object(I, "PAQUET_IMPORT", 1), mock.patch.object(AP.Suivi, "ecriture", ecriture):
            AP.traiter_file()
        t.refresh_from_db()
        self.assertEqual((t.statut, t.ecrites, t.faites, t.total), (T.ARRETEE, 1, 1, 4))
        self.assertEqual(Reponse.objects.filter(periode=self.c.periode, organisation__in=[self.e1, self.e2],
                                                kpi__in=[self.eff, self.taux]).count(), 1)  # ce qui est écrit reste écrit
        self.assertEqual(Journal.objects.get(action="import_valeurs").apres, "fichier.xlsx : 1 valeur(s) (arrêté avant la fin)")
        self.assertTrue(Journal.objects.filter(action="import_arrete").exists())
        rep = self.client.get(self.url)
        self.assertContains(rep, "Import arrêté – fichier.xlsx")
        self.assertContains(rep, "Import arrêté à votre demande après 1 lignes sur 4")
        self.assertEqual(rep.context["nb_brouillon"], 1)  # seule la ligne écrite compte
        self.assertFalse(default_storage.exists(t.chemin))

    def test_arreter_avant_le_debut(self):
        self.deposer()
        t = self.lancer(executer=False)
        rep = self.client.post(reverse("collecte:echanges_tache_arreter", args=[t.pk]))
        t.refresh_from_db()
        self.assertEqual(t.statut, T.ARRETEE)
        self.assertFalse(default_storage.exists(t.chemin))
        self.assertContains(self.client.get(rep.url), "Import arrêté avant son début : rien n'a été écrit.")
        AP.traiter_file()
        self.assertFalse(Reponse.objects.filter(periode=self.c.periode, kpi=self.taux).exists())

    def test_on_n_arrete_que_les_siens(self):
        self.deposer()
        t = self.lancer(executer=False)
        self.client.force_login(self.autre)
        self.assertEqual(self.client.post(reverse("collecte:echanges_tache_arreter", args=[t.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("collecte:echanges_tache_etat", args=[t.pk])).status_code, 404)
        self.assertNotContains(self.client.get(f"{self.url}?tache={t.pk}"), "role=\"progressbar\"")

    # -- robustesse -------------------------------------------------------------------------------------------------------
    def test_un_import_a_la_fois_par_personne(self):
        self.deposer()
        t = self.lancer(executer=False)
        self.deposer()  # un aperçu reste possible
        rep = self.client.post(self.url, {"action": "confirmer"}, follow=True)
        self.assertContains(rep, "Vous avez déjà un import en cours (fichier.xlsx)")
        self.assertEqual(TacheImport.objects.count(), 1)
        with override_settings(IMPORT_ARRIERE_PLAN_LIGNES=1000):  # même un petit fichier attend la fin du premier
            self.deposer()
            self.client.post(self.url, {"action": "confirmer"})
        self.assertFalse(Reponse.objects.filter(periode=self.c.periode, kpi=self.taux).exists())
        with self.assertRaises(AP.DejaEnCours):
            AP.creer(self.contrib, {"chemin": t.chemin, "nom": "x.xlsx"}, 10)

    def test_redemarrage_reprise_une_fois_puis_interrompu(self):
        self.deposer()
        t = self.lancer(executer=False)
        vieux = timezone.now() - datetime.timedelta(seconds=AP.PERIME + 5)
        TacheImport.objects.filter(pk=t.pk).update(statut=T.EN_COURS, battement=vieux, faites=100, ecrites=90, total=400)
        with self.assertLogs("collecte.imports", "WARNING") as journal:
            AP.entretien()  # serveur redémarré pendant l'import : reprise depuis le début du fichier
        self.assertIn("started again from the beginning of the file", journal.output[0])
        t.refresh_from_db()
        self.assertEqual((t.statut, t.reprises), (T.ATTENTE, 1))
        TacheImport.objects.filter(pk=t.pk).update(statut=T.EN_COURS, battement=vieux)
        with self.assertLogs("collecte.imports", "ERROR") as journal:
            AP.entretien()  # une seconde fois : interrompu, avec un message clair (jamais « en cours » pour toujours)
        self.assertIn("interrupted (server restart?) after 100 of 400 values", journal.output[0])
        t.refresh_from_db()
        self.assertEqual(t.statut, T.INTERROMPUE)
        self.assertFalse(default_storage.exists(t.chemin))
        self.assertTrue(Journal.objects.filter(action="import_interrompu").exists())
        rep = self.client.get(self.url)
        self.assertContains(rep, "Import interrompu – fichier.xlsx")
        self.assertContains(rep, "L'import s'est arrêté après 90 valeurs écrites sur 400")

    def test_reprise_n_ecrit_rien_deux_fois(self):
        self.deposer()
        t = self.lancer(executer=False)
        with mock.patch.object(I, "PAQUET_IMPORT", 1):  # première fois : deux lignes écrites, puis le serveur s'arrête
            reel = AP.Suivi.ecriture

            def ecriture(suivi, faites, total, ecrites):
                reel(suivi, faites, total, ecrites)
                if faites == 2:
                    raise SystemExit  # processus arrêté net

            with mock.patch.object(AP.Suivi, "ecriture", ecriture), self.assertRaises(SystemExit):
                AP.traiter_file()
        TacheImport.objects.filter(pk=t.pk).update(battement=timezone.now() - datetime.timedelta(seconds=AP.PERIME + 5))
        with self.assertLogs("collecte.imports", "WARNING"):
            AP.traiter_file()  # entretien : reprise, puis exécution
        t.refresh_from_db()
        self.assertEqual((t.statut, t.reprises, t.ecrites, t.faites, t.total), (T.TERMINEE, 1, 4, 4, 4))
        self.assertContains(self.client.get(self.url), "a repris depuis le début du fichier")
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.taux, organisation=self.e2).valeur, D("0.4"))

    def test_echec_jamais_en_cours_pour_toujours(self):
        self.deposer()
        t = self.lancer(executer=False)
        default_storage.delete(t.chemin)
        with self.assertLogs("collecte.imports", "ERROR") as journal:  # pour l'IT, en anglais
            AP.traiter_file()
        self.assertIn("failed", journal.output[0])
        t.refresh_from_db()
        self.assertEqual(t.statut, T.ECHEC)
        self.assertContains(self.client.get(self.url), "Import impossible – fichier.xlsx")

    def test_fichier_garde_tant_que_la_tache_le_lit(self):
        from .vues_echanges import _purger

        self.deposer()
        t = self.lancer(executer=False)
        vieux = (timezone.now() - datetime.timedelta(days=3)).timestamp()
        os.utime(default_storage.path(t.chemin), (vieux, vieux))
        _purger()
        self.assertTrue(default_storage.exists(t.chemin))
        TacheImport.objects.filter(pk=t.pk).update(statut=T.ARRETEE)
        _purger()
        self.assertFalse(default_storage.exists(t.chemin))

    # -- qui exécute ------------------------------------------------------------------------------------------------------
    def test_planificateur_ou_fil_de_secours(self):
        with tempfile.TemporaryDirectory() as d, override_settings(DOSSIER_DONNEES=Path(d)), \
                mock.patch.object(AP, "planificateur_actif", _planificateur_actif), mock.patch.object(AP, "demarrer_fil") as fil:
            AP.lancer()
            fil.assert_called_once()  # aucun planificateur : un fil du serveur web
            AP.signe_de_vie_planificateur()
            fil.reset_mock()
            AP.lancer()
            fil.assert_not_called()  # le planificateur donne signe de vie : il prendra la tâche

    def test_commande_run_imports(self):
        self.deposer()
        t = self.lancer(executer=False)
        call_command("run_imports", stdout=open(os.devnull, "w"))
        t.refresh_from_db()
        self.assertEqual((t.statut, t.ecrites), (T.TERMINEE, 4))

    def test_prise_par_un_seul_processus(self):
        self.deposer()
        t = self.lancer(executer=False)
        self.assertEqual(AP.prendre().pk, t.pk)
        self.assertIsNone(AP.prendre())  # déjà en cours : personne d'autre ne la prend, ni une autre tâche

    def test_sante_signale_une_tache_bloquee(self):
        self.deposer()
        t = self.lancer(executer=False)
        self.client.force_login(self.admin)
        d = self.client.get("/sante/").json()
        self.assertEqual((d["background_imports"]["waiting"], d["background_imports"]["stuck"]), (1, 0))
        TacheImport.objects.filter(pk=t.pk).update(cree_le=timezone.now() - datetime.timedelta(seconds=AP.ATTENTE_MAX + 5))
        rep = self.client.get("/sante/")
        self.assertEqual(rep.status_code, 200)  # dit, jamais en 503
        d = rep.json()
        self.assertEqual(d["background_imports"]["stuck"], 1)
        self.assertIn("background import stuck", d["avertissement"])
