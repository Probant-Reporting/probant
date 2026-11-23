"""Gros exports fabriqués en arrière-plan (collecte/exports_arriere_plan.py) : sous le seuil rien ne
change ; au-dessus, la demande répond tout de suite, le fichier est identique au téléchargement immédiat, une tâche n'est
prise qu'une fois, reprise après un arrêt, le fichier n'est donné qu'à la personne qui l'a demandé et seulement avec les
droits de la demande, il expire, il n'est jamais sauvegardé ; lecteur et auditeur n'écrivent rien de fonctionnel."""
import datetime
import io
import os
import threading
import unittest
import zipfile
from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.db import connection, connections
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from parametres import sauvegardes as SV
from parametres.aides_tests.hebergement import DossiersTemporaires
from parametres.models import Instance
from parametres.rangement import EXPORTS
from referentiel.models import Attribution, Utilisateur

from . import exports as E
from . import exports_arriere_plan as EAP
from . import imports_arriere_plan as AP
from . import saisie as S
from .models import Journal, TacheExport
from .aides_tests.lecture_seule import Base
from .test_droits_balayage import instantane

T = TacheExport.Statut
FIGE = timezone.make_aware(datetime.datetime(2026, 11, 14, 10, 30))
EXPORT_BASE = {"action": "telecharger", "presentation": "base", "exercices": ["courant"], "contenus": list(E.CODES_CONTENUS),
               "types": list(E.CODES_COMPORTEMENTS)}


def seuil(cellules, jours=7):
    i = Instance.courante()
    i.exports_fond_cellules, i.exports_fond_jours = cellules, jours
    i.save()


def contenu(rep):
    return b"".join(rep.streaming_content) if rep.streaming else rep.content


def cellules(octets):
    """{onglet: [[valeurs]]} d'un classeur : comparaison cellule par cellule."""
    wb = load_workbook(io.BytesIO(octets))
    return {ws.title: [[c.value for c in ligne] for ligne in ws.iter_rows()] for ws in wb.worksheets}


@mock.patch.object(EAP, "BATTEMENT", 0)
@mock.patch.object(AP, "planificateur_actif", lambda: False)
@mock.patch.object(EAP, "demarrer_fil", lambda code: None)  # jamais de vrai fil pendant les tests (base de test partagée)
class ExportsArrierePlanTests(Base):
    def setUp(self):
        super().setUp()
        for org, v in ((self.e1, "12"), (self.e2, "30")):
            S.enregistrer(self.admin, self.c, self.eff, org, v, False, "")
        S.enregistrer(self.contrib, self.c, self.taux, self.e1, "40", False, "commentaire")
        self.url = reverse("collecte:echanges_exporter")
        self.niveaux = E.N.codes()

    def demander(self, user=None, **donnees):
        self.client.force_login(user or self.admin)
        return self.client.post(self.url, {**EXPORT_BASE, "niveaux": self.niveaux, **donnees})

    def fichier_de(self, t):
        t.refresh_from_db()
        with default_storage.open(t.chemin, "rb") as f:
            return f.read()

    # -- seuil ---------------------------------------------------------------------------------------------------------
    def test_sous_le_seuil_rien_ne_change(self):
        for s in (0, 100_000):  # 0 : jamais ; 100 000 (défaut) : ce petit export reste immédiat
            seuil(s)
            rep = self.demander()
            self.assertEqual(rep.status_code, 200)
            self.assertIn("spreadsheetml", rep["Content-Type"])
        self.assertFalse(TacheExport.objects.exists())
        self.assertEqual(Instance().exports_fond_cellules, 100_000)  # valeur par défaut d'une installation
        self.assertEqual(Instance().exports_fond_jours, 7)

    def test_estimation_compte_avant_de_fabriquer(self):
        p = E.Parametres.depuis({**EXPORT_BASE, "niveaux": self.niveaux})
        with mock.patch.object(E, "collecter", side_effect=AssertionError("lu avant de décider")):
            n = E.estimer_cellules(self.admin, p)
        lignes = len(E.collecter(self.admin, p))
        self.assertGreaterEqual(n, lignes * len(E.entetes_base(p)))  # borne haute pour qui voit tout
        self.assertEqual(p.langue, "")  # réglages rendus tels quels
        self.assertLess(E.estimer_cellules(self.contrib, p), n)  # périmètre limité : ses organisations seulement

    # -- la demande répond tout de suite ; le fichier attend dans Mes exports -----------------------------------------------
    def test_demande_immediate_puis_fichier_dans_mes_exports(self):
        seuil(1)
        with mock.patch.object(E, "collecter", side_effect=AssertionError("fabriqué dans la requête")):
            rep = self.demander()
        self.assertRedirects(rep, reverse("collecte:echanges") + "#exports-fond", fetch_redirect_response=False)
        t = TacheExport.objects.get()
        self.assertEqual((t.statut, t.genre, t.utilisateur, t.titre), (T.ATTENTE, "export", self.admin, "Base de données – 2026"))
        page = self.client.get(reverse("collecte:echanges"))
        self.assertContains(page, "Fichiers volumineux")
        self.assertContains(page, "est un fichier volumineux : il est préparé sur le serveur")
        self.assertContains(page, 'role="progressbar"')
        self.assertContains(page, "En attente")
        self.assertContains(page, f'data-suivi-export="{reverse("collecte:echanges_export_etat", args=[t.pk])}"')
        d = self.client.get(reverse("collecte:echanges_export_etat", args=[t.pk])).json()
        self.assertEqual((d["fini"], d["statut"]), (False, "attente"))
        EAP.traiter_file()
        d = self.client.get(reverse("collecte:echanges_export_etat", args=[t.pk])).json()
        self.assertTrue(d["fini"])
        self.assertIn("est prêt à télécharger", d["annonce"])
        self.assertIn("Télécharger", d["html"])
        t.refresh_from_db()
        self.assertEqual(t.statut, T.PRET)
        self.assertTrue(t.chemin.startswith(f"{EXPORTS}/") and t.chemin.endswith(".xlsx"))
        self.assertEqual(t.expire_le - t.fin, datetime.timedelta(days=7))
        page = self.client.get(reverse("collecte:echanges"))
        self.assertContains(page, "Prêt ·")
        self.assertContains(page, "disponible jusqu'au")
        rep = self.client.get(reverse("collecte:echanges_export_fichier", args=[t.pk]))
        self.assertEqual(rep.status_code, 200)
        self.assertEqual(rep["Content-Disposition"], f'attachment; filename="{t.nom_fichier}"')
        self.assertEqual(contenu(rep), self.fichier_de(t))
        self.assertFalse(Journal.objects.filter(action__icontains="export").exists())  # un export n'est jamais au journal

    def test_fichier_identique_au_telechargement_immediat(self):
        """Même fichier, cellule par cellule (et partie par partie du classeur, hors date de création), pour chaque
        présentation, en Excel et en CSV, pour l'admin et pour un contributeur."""
        cas = [(self.admin, {"presentation": "base"}), (self.admin, {"presentation": "revue"}),
               (self.admin, {"presentation": "tableau"}), (self.admin, {"presentation": "base", "format": "csv"}),
               (self.contrib, {"presentation": "base"}), (self.contrib, {"presentation": "revue", "format": "csv"})]
        for user, reglages in cas:
            with self.subTest(user=user.username, **reglages), mock.patch("django.utils.timezone.now", return_value=FIGE):
                seuil(0)
                immediat = self.demander(user, **reglages)
                self.assertEqual(immediat.status_code, 200)
                seuil(1)
                self.demander(user, **reglages)
                t = TacheExport.objects.get(statut=T.ATTENTE)
                EAP.traiter_file()
                fond = self.fichier_de(t)
                self.assertEqual(t.nom_fichier, immediat["Content-Disposition"].split('"')[1])
                if reglages.get("format") == "csv":
                    self.assertEqual(fond, immediat.content)
                else:
                    self.assertEqual(cellules(fond), cellules(immediat.content))
                    a, b = zipfile.ZipFile(io.BytesIO(immediat.content)), zipfile.ZipFile(io.BytesIO(fond))
                    self.assertEqual(a.namelist(), b.namelist())
                    for partie in a.namelist():
                        if partie != "docProps/core.xml":
                            self.assertEqual(a.read(partie), b.read(partie), partie)
                TacheExport.objects.all().delete()

    def test_fichier_a_remplir_identique(self):
        url = reverse("collecte:echanges_modele")
        for user, choix in ((self.admin, {"campagne": self.c.pk}), (self.contrib, {"campagne": self.c.pk, "format": "csv"}),
                            (self.admin, {"ref": "tous"})):
            with self.subTest(user=user.username, **choix), mock.patch("django.utils.timezone.now", return_value=FIGE):
                self.client.force_login(user)
                seuil(0)
                immediat = self.client.get(url, choix)
                self.assertEqual(immediat.status_code, 200)
                seuil(1)
                rep = self.client.get(url, choix)
                self.assertRedirects(rep, reverse("collecte:echanges") + "#exports-fond", fetch_redirect_response=False)
                t = TacheExport.objects.get(statut=T.ATTENTE)
                self.assertEqual(t.genre, "remplir")
                EAP.traiter_file()
                fond = self.fichier_de(t)
                if choix.get("format") == "csv":
                    self.assertEqual(fond, immediat.content)
                else:
                    self.assertEqual(cellules(fond), cellules(immediat.content))
                TacheExport.objects.all().delete()

    def test_rien_a_remplir(self):
        seuil(1)
        S.valider(self.contrib, self.c, self.taux, self.e1)
        S.enregistrer(self.contrib, self.c, self.eff, self.e1, "12", False, "")
        S.valider(self.contrib, self.c, self.eff, self.e1)
        self.client.force_login(self.contrib)
        self.client.get(reverse("collecte:echanges_modele"), {"campagne": self.c.pk, "a_faire": "on"})
        t = EAP.executer(EAP.prendre())
        self.assertEqual((t.statut, t.chemin), (T.VIDE, ""))
        self.assertContains(self.client.get(reverse("collecte:echanges")), "Rien à remplir")
        self.assertNotContains(self.client.get(reverse("collecte:echanges")), "Rien à remplir")  # montré une fois

    # -- une tâche n'est prise qu'une fois ; reprise après un arrêt -------------------------------------------------------
    def test_prise_par_un_seul_processus(self):
        seuil(1)
        self.demander()
        self.demander(self.contrib)
        premiere, seconde = TacheExport.objects.order_by("pk")
        vue_par_a = EAP.candidate()  # le processus A lit la tâche…
        self.assertEqual(EAP.prendre().pk, premiere.pk)  # … le processus B la prend avant lui
        self.assertFalse(EAP.prise(vue_par_a))  # A ne l'obtient pas
        self.assertIsNone(EAP.prendre())  # une à la fois par espace : la seconde attend
        self.assertFalse(EAP.prise(seconde))
        self.assertEqual(TacheExport.objects.get(pk=seconde.pk).statut, T.ATTENTE)

    def test_un_a_la_fois_par_personne(self):
        seuil(1)
        self.demander()
        rep = self.client.post(self.url, {**EXPORT_BASE, "niveaux": self.niveaux, "presentation": "revue"}, follow=True)
        self.assertContains(rep, "Un fichier est déjà en préparation pour vous")
        self.assertEqual(TacheExport.objects.count(), 1)
        with self.assertRaises(EAP.DejaEnCours):
            EAP.creer(self.admin, "export", "x", {}, 10)

    def test_reprise_apres_arret_puis_interrompu(self):
        seuil(1)
        self.demander()
        t = EAP.prendre()
        vieux = timezone.now() - datetime.timedelta(seconds=EAP.PERIME + 5)
        TacheExport.objects.filter(pk=t.pk).update(battement=vieux)  # processus arrêté net (redémarrage)
        EAP.entretien()
        t.refresh_from_db()
        self.assertEqual((t.statut, t.reprises), (T.ATTENTE, 1))  # reprise une fois depuis le début
        t = EAP.prendre()
        TacheExport.objects.filter(pk=t.pk).update(battement=vieux)
        EAP.entretien()
        t.refresh_from_db()
        self.assertEqual(t.statut, T.INTERROMPUE)  # jamais « en cours » pour toujours
        page = self.client.get(reverse("collecte:echanges"))
        self.assertContains(page, "Arrêté par un redémarrage du serveur")
        t = TacheExport.objects.create(utilisateur=self.admin, titre="x", statut=T.EN_COURS, battement=timezone.now())
        EAP.entretien()
        self.assertEqual(TacheExport.objects.get(pk=t.pk).statut, T.EN_COURS)  # battement récent : on n'y touche pas

    def test_echec_avec_son_motif(self):
        seuil(1)
        self.demander()
        with mock.patch.object(E, "collecter", side_effect=RuntimeError("disque plein")):
            t = EAP.executer(EAP.prendre())
        self.assertEqual((t.statut, t.chemin), (T.ECHEC, ""))
        self.assertIn("disque plein", t.erreur)
        self.assertContains(self.client.get(reverse("collecte:echanges")), "Le fichier n'a pas pu être préparé")

    def test_limite_d_excel(self):
        seuil(1)
        with mock.patch.object(E, "MAX_LIGNES_EXCEL", E.LIGNES_ENTETE_EXCEL + 1):
            rep = self.demander(follow=True)  # admin : borne des lignes comptée avant, refus tout de suite, sans tâche
            self.assertContains(rep, "Choisissez le format CSV")
            self.assertFalse(TacheExport.objects.exists())
            self.demander(self.contrib)  # périmètre limité : constaté pendant la fabrication, dit dans Mes exports
            t = EAP.executer(EAP.prendre())
        self.assertEqual(t.statut, T.ECHEC)
        self.assertIn("Choisissez le format CSV", t.erreur)

    # -- le fichier n'est donné qu'à la personne qui l'a demandé, avec les droits de la demande ------------------------------
    def pret(self, user, **reglages):
        seuil(1)
        self.demander(user, **reglages)
        return EAP.executer(EAP.prendre())

    def test_autre_personne_jamais(self):
        t = self.pret(self.admin)
        for autre in (self.contrib, self.auditeur, self.autre):
            self.client.force_login(autre)
            self.assertEqual(self.client.get(reverse("collecte:echanges_export_fichier", args=[t.pk])).status_code, 404, autre)
            self.assertEqual(self.client.get(reverse("collecte:echanges_export_etat", args=[t.pk])).status_code, 404, autre)
            self.assertNotContains(self.client.get(reverse("collecte:echanges")), "id=\"exports-fond\"")
        self.client.logout()
        self.assertEqual(self.client.get(reverse("collecte:echanges_export_fichier", args=[t.pk])).status_code, 302)
        self.assertTrue(default_storage.exists(t.chemin))

    def test_droits_changes_entre_la_demande_et_le_telechargement(self):
        cas = [
            ("attribution retirée", self.contrib, lambda: Attribution.objects.filter(utilisateur=self.contrib, kpi=self.taux).delete()),
            ("rôle changé", self.contrib, lambda: Utilisateur.objects.filter(pk=self.contrib.pk).update(role=Utilisateur.Role.LECTEUR)),
            ("périmètre de consultation", self.auditeur, lambda: self.auditeur.perimetre_lecture.add(self.e1)),
            ("admin devenu validateur", self.admin, lambda: Utilisateur.objects.filter(pk=self.admin.pk).update(role=Utilisateur.Role.VALIDATEUR)),
        ]
        for motif, user, changer in cas:
            with self.subTest(motif):
                t = self.pret(user)
                self.assertEqual(t.statut, T.PRET)
                changer()
                self.client.force_login(Utilisateur.objects.get(pk=user.pk))
                rep = self.client.get(reverse("collecte:echanges_export_fichier", args=[t.pk]))
                self.assertIn(rep.status_code, (302, 403))  # refusé (un lecteur n'ouvre plus Import / Export : 403)
                t.refresh_from_db()
                if rep.status_code == 302:
                    self.assertEqual(rep["Location"], reverse("collecte:echanges"))
                    self.assertEqual((t.statut, t.erreur), (T.EXPIRE, "droits"))  # fichier supprimé sans être donné
                    self.assertFalse(default_storage.exists(t.chemin))
                    self.assertContains(self.client.get(reverse("collecte:echanges")), "Vos accès ont changé depuis votre demande")
                TacheExport.objects.all().delete()

    def test_droits_inchanges_le_fichier_est_donne(self):
        t = self.pret(self.contrib)
        Attribution.objects.create(kpi=self.eff, organisation=self.g, utilisateur=self.autre)  # les droits d'un autre
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(reverse("collecte:echanges_export_fichier", args=[t.pk])).status_code, 200)

    # -- expiration, ménage, sauvegardes --------------------------------------------------------------------------------
    def test_expiration_et_menage(self):
        t = self.pret(self.admin)
        TacheExport.objects.filter(pk=t.pk).update(expire_le=timezone.now() - datetime.timedelta(seconds=1))
        rep = self.client.get(reverse("collecte:echanges_export_fichier", args=[t.pk]), follow=True)
        self.assertContains(rep, "Ce fichier n&#x27;est plus disponible (les fichiers volumineux sont gardés 7 jours)")
        self.assertFalse(default_storage.exists(t.chemin))
        t2 = self.pret(self.admin)
        TacheExport.objects.filter(pk=t2.pk).update(expire_le=timezone.now() - datetime.timedelta(seconds=1))
        orphelin = default_storage.save(f"{EXPORTS}/orphelin.xlsx", ContentFile(b"x"))  # restauration, arrêt brutal
        recent = default_storage.save(f"{EXPORTS}/recent.xlsx", ContentFile(b"x"))
        vieux = (timezone.now() - datetime.timedelta(hours=EAP.ORPHELIN_HEURES, minutes=5)).timestamp()
        os.utime(default_storage.path(orphelin), (vieux, vieux))
        TacheExport.objects.create(utilisateur=self.admin, titre="ancien", statut=T.EXPIRE,
                                   fin=timezone.now() - datetime.timedelta(days=EAP.CONSERVER_JOURS + 1))
        EAP.entretien(menage=True)
        self.assertEqual(TacheExport.objects.get(pk=t2.pk).statut, T.EXPIRE)
        self.assertFalse(default_storage.exists(t2.chemin))
        self.assertFalse(default_storage.exists(orphelin))
        self.assertTrue(default_storage.exists(recent))  # peut-être en cours d'écriture : gardé
        self.assertFalse(TacheExport.objects.filter(titre="ancien").exists())

    def test_duree_de_conservation_reglable(self):
        seuil(1, jours=2)
        self.demander()
        t = EAP.executer(EAP.prendre())
        self.assertEqual(t.expire_le - t.fin, datetime.timedelta(days=2))
        self.assertContains(self.client.get(reverse("collecte:echanges")), "chaque fichier vous attend ici 2 jours")

    # -- lecteur et auditeur --------------------------------------------------------------------------------------------
    def test_auditeur_n_ecrit_rien_de_fonctionnel(self):
        seuil(1)
        avant = {k: v for k, v in instantane().items() if k != "TacheExport"}
        self.demander(self.auditeur)
        t = TacheExport.objects.get()  # sa trace technique, à lui
        self.assertEqual(t.utilisateur, self.auditeur)
        EAP.executer(EAP.prendre())
        self.assertEqual(self.client.get(reverse("collecte:echanges_export_fichier", args=[t.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("collecte:echanges_export_etat", args=[t.pk])).status_code, 200)
        self.assertEqual({k: v for k, v in instantane().items() if k != "TacheExport"}, avant)
        for url in (reverse("collecte:echanges_export_fichier", args=[t.pk]), reverse("collecte:echanges_export_etat", args=[t.pk])):
            self.assertEqual(self.client.post(url).status_code, 403)  # aucun envoi
        self.client.force_login(self.lecteur)
        self.assertEqual(self.client.post(self.url, {**EXPORT_BASE, "niveaux": self.niveaux}).status_code, 403)
        self.assertEqual(self.client.get(reverse("collecte:echanges_export_fichier", args=[t.pk])).status_code, 403)
        self.assertEqual(TacheExport.objects.count(), 1)

    # -- qui exécute ----------------------------------------------------------------------------------------------------
    def test_fil_de_secours_sans_planificateur(self):
        seuil(1)
        with mock.patch.object(EAP, "demarrer_fil") as fil:
            self.demander()
            fil.assert_called_once()
        with mock.patch.object(AP, "planificateur_actif", lambda: True), mock.patch.object(EAP, "demarrer_fil") as fil:
            EAP.lancer()
            fil.assert_not_called()  # le planificateur donne signe de vie : il prendra la tâche

    def test_commande_run_imports(self):
        seuil(1)
        self.demander()
        call_command("run_imports", stdout=open(os.devnull, "w"))
        self.assertEqual(TacheExport.objects.get().statut, T.PRET)

    # -- réglage (Paramètres › Hébergement) -------------------------------------------------------------------------------
    def test_reglage_dans_hebergement(self):
        url = reverse("parametres:hebergement")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(url), "Gros exports")
        rep = self.client.post(url, {"action": "reglage_exports_fond", "exports_fond_cellules": "250000", "exports_fond_jours": "3"},
                               follow=True)
        self.assertContains(rep, "Les exports de plus de 250 000 cellules sont préparés sur le serveur et gardés 3 jours")
        i = Instance.courante()
        self.assertEqual((i.exports_fond_cellules, i.exports_fond_jours), (250_000, 3))
        self.assertEqual(Journal.objects.filter(action="reglage_exports_fond").count(), 2)
        for cellules_, jours in (("-1", "3"), ("abc", "3"), ("1000", "0"), ("1000", "31"), ("100000001", "3")):
            rep = self.client.post(url, {"action": "reglage_exports_fond", "exports_fond_cellules": cellules_, "exports_fond_jours": jours})
            self.assertContains(rep, "Saisissez", msg_prefix=f"{cellules_}/{jours}")
        self.assertEqual(Instance.courante().exports_fond_cellules, 250_000)
        self.client.post(url, {"action": "reglage_exports_fond", "exports_fond_cellules": "0", "exports_fond_jours": "7"})
        self.assertEqual(Instance.courante().exports_fond_cellules, 0)
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.post(url, {"action": "reglage_exports_fond", "exports_fond_cellules": "5"}).status_code, 403)


class SauvegardeSansGrosExportsTests(DossiersTemporaires, TransactionTestCase):  # la copie SQLite se fait hors transaction
    databases = {"default", "commun"}

    def test_fichiers_jamais_sauvegardes(self):
        self.assertIn(EXPORTS, SV.EXCLUS)
        u = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        preuve = default_storage.save("evidence/2026/x/preuve.pdf", ContentFile(b"%PDF"))
        export = default_storage.save(f"{EXPORTS}/gros.xlsx", ContentFile(b"gros export"))
        TacheExport.objects.create(utilisateur=u, titre="Gros", statut=T.PRET, chemin=export)
        with zipfile.ZipFile(SV.creer("manuelle").chemin) as z:
            noms = z.namelist()
        self.assertIn(f"files/{preuve}", noms)  # les preuves, oui
        self.assertFalse([n for n in noms if f"/{EXPORTS}/" in n])  # les gros exports, jamais (refaits sur demande)
        self.assertTrue(default_storage.exists(export))


class PriseSimultaneeTests(TransactionTestCase):
    """Deux processus prennent la file au même instant : un seul obtient la tâche. Vrais fils et vraies connexions sous
    PostgreSQL ; la base SQLite des tests (en mémoire, cache partagé) répond « table verrouillée » au lieu d'attendre (le
    test déterministe ci-dessus, ``test_prise_par_un_seul_processus``, y couvre la même mise à jour conditionnelle)."""
    databases = {"default", "commun"}

    @unittest.skipUnless(connection.vendor == "postgresql", "vrais fils : PostgreSQL (voir l'en-tête)")
    def test_deux_processus_une_seule_prise(self):
        u = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        for _ in range(3):
            t = TacheExport.objects.create(utilisateur=u, titre="x")
            depart, pris = threading.Barrier(4), []
            vu = EAP.candidate()

            def prendre():
                try:
                    depart.wait(5)
                    pris.append(EAP.prise(vu))
                finally:
                    connections.close_all()
            fils = [threading.Thread(target=prendre) for _ in range(4)]
            for f in fils:
                f.start()
            for f in fils:
                f.join(30)
            self.assertEqual(sorted(pris), [False, False, False, True])
            TacheExport.objects.filter(pk=t.pk).update(statut=T.PRET)
