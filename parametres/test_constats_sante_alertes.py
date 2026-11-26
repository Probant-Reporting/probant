"""Lignes de la page Santé (``sante_installation.constats``), source unique des alertes par e-mail : chaque cas dit s'il
alerte. Cas ajoutés pour les alertes, visibles aussi sur la page et dans /sante/ : sauvegarde automatique échouée
(notée par le planificateur), dernière sauvegarde illisible, tâche de fond arrêtée (signe de vie), contrôle de la nuit
qui a trouvé des erreurs."""
import datetime
import os
import time
from unittest import mock

from django.utils import timezone

from espaces.essais import EspacesTestCase
from parametres import sante_installation as SI
from parametres import sauvegardes as SV
from parametres import taches_fond as TF
from parametres.aides_tests.alertes import DossierAlertes, disque_plein

ACTIVE = {"active": True, "derniere": None, "prochaine": timezone.now(), "en_retard": False}


def ligne(cle, **k):
    return next(x for x in SI.constats(True, **k) if x["cle"] == cle)


class ConstatsTests(DossierAlertes, EspacesTestCase):
    allumer = False

    def test_sans_probleme_aucune_ligne_n_alerte(self):
        lignes = SI.constats(True, https=False)
        self.assertEqual([x["cle"] for x in lignes if x["alerte"]], [])
        self.assertEqual(next(x for x in lignes if x["cle"] == "sauvegarde")["etat"], SI.A_REGARDER)  # aucune : n'alerte pas
        self.assertEqual(next(x for x in lignes if x["cle"] == "https")["etat"], SI.A_REGARDER)  # dépend de la requête

    def test_sans_requete_pas_de_ligne_https(self):
        self.assertNotIn("https", [x["cle"] for x in SI.constats(True)])

    def test_disque(self):
        with disque_plein():
            x = ligne("disque")
        self.assertEqual((x["etat"], x["alerte"], x["portee"]), (SI.PANNE, "panne", SI.INSTALLATION))

    def test_sauvegarde_automatique_echouee_puis_reussie(self):
        """Le planificateur note l'échec (hors de la base), la page le dit en panne ; la réussite suivante l'efface."""
        from parametres.models import Instance

        i = Instance.courante()
        i.sauvegarde_auto = True
        i.save()
        SV.dossier().mkdir(parents=True, exist_ok=True)

        class Arret(Exception):
            pass

        def dormir(_):
            raise Arret()

        from django.db import connections

        with mock.patch.object(SV, "creer", side_effect=OSError("No space left on device")), \
                mock.patch.object(SV, "registre_du_jour"), mock.patch.object(SV, "base_vide", return_value=False), \
                mock.patch.object(SV.ESP, "codes_actifs", return_value=[SV.ESP.PRINCIPAL]), \
                mock.patch.object(SV, "echeance_suivante", return_value=timezone.localtime() - datetime.timedelta(minutes=1)), \
                mock.patch.object(connections, "close_all"), mock.patch.object(SV.time, "sleep", dormir), \
                self.assertLogs("reporting.sauvegarde", "ERROR"), self.assertRaises(Arret):
            SV.planifier()
        self.assertIsNotNone(SV.echec_auto())
        x = ligne("sauvegarde")
        self.assertEqual((x["etat"], x["alerte"]), (SI.PANNE, "echec"))
        self.assertIn("La dernière sauvegarde automatique a échoué", x["constat"])
        self.assertTrue((TF.dossier() / "backup").is_file())  # signe de vie de la tâche posé au départ de la boucle

        def creer(motif):
            (SV.dossier() / f"backup-{timezone.localtime():%Y%m%d-%H%M%S}-{motif}.zip").write_bytes(b"")

        with mock.patch.object(SV, "creer", creer), mock.patch.object(SV, "tourner"), \
                mock.patch.object(SV, "registre_du_jour"), mock.patch.object(SV, "base_vide", return_value=False), \
                mock.patch.object(SV.ESP, "codes_actifs", return_value=[SV.ESP.PRINCIPAL]), \
                mock.patch.object(SV, "echeance_suivante", return_value=timezone.localtime() - datetime.timedelta(minutes=1)), \
                mock.patch.object(connections, "close_all"), mock.patch.object(SV.time, "sleep", dormir), self.assertRaises(Arret):
            SV.planifier()
        self.assertIsNone(SV.echec_auto())

    def test_echec_ancien_suivi_d_une_reussite_n_alerte_plus(self):
        SV.noter_echec_auto(OSError())
        plus_tard = dict(ACTIVE, derniere=timezone.now() + datetime.timedelta(minutes=5))
        with mock.patch.object(SV, "etat_automatique", return_value=plus_tard):
            self.assertNotEqual(ligne("sauvegarde")["alerte"], "echec")

    def test_echec_sans_sauvegarde_automatique_allumee_ignore(self):
        from parametres.models import Instance

        Instance.objects.update(sauvegarde_auto=False)
        SV.noter_echec_auto(OSError())
        self.assertEqual(ligne("sauvegarde")["alerte"], "")  # aucune sauvegarde, automatiques éteintes : n'alerte pas

    def test_derniere_sauvegarde_illisible(self):
        SV.dossier().mkdir(parents=True, exist_ok=True)
        (SV.dossier() / f"backup-{timezone.localtime():%Y%m%d-%H%M%S}-manuelle.zip").write_bytes(b"pas un zip")
        x = ligne("sauvegarde")
        self.assertEqual((x["etat"], x["alerte"]), (SI.PANNE, "illisible"))
        self.assertIn("ne se lit pas", x["constat"])

    def test_derniere_sauvegarde_abimee_selon_le_controle_de_la_nuit(self):
        from collecte import controle_donnees as CD

        import json
        import zipfile

        SV.dossier().mkdir(parents=True, exist_ok=True)
        nom = f"backup-{timezone.localtime():%Y%m%d-%H%M%S}-manuelle.zip"
        with zipfile.ZipFile(SV.dossier() / nom, "w") as z:  # descriptif lisible : seul le contrôle complet la trouve abîmée
            z.writestr(SV.DESCRIPTIF, json.dumps({"format": SV.FORMAT, "outil": SV.OUTIL}))
            z.writestr(SV.BASE_JSON, "[]")
        a = SV.archive(nom)
        self.assertEqual(ligne("sauvegarde")["alerte"], "")
        CD.enregistrer({"date": timezone.now().isoformat(), "space": "principal", "errors": 1, "warnings": 0, "infos": 0,
                        "problems": [{"check": "backup_unreadable", "severity": "error", "count": 1,
                                      "examples": [f"{a.nom}: damaged file in the archive: base.sqlite3"], "message": ""}]})
        x = ligne("sauvegarde")
        self.assertEqual((x["etat"], x["alerte"]), (SI.PANNE, "illisible"))
        self.assertEqual(ligne("taches")["alerte"], "")  # pas compté deux fois dans les erreurs du contrôle

    def test_tache_de_fond_arretee(self):
        self.assertEqual(TF.arretees(), [])  # jamais lancée ici : rien n'est dit
        TF.battre("reminders")
        TF.battre("data_check")
        self.assertEqual(TF.arretees(), [])
        vieux = time.time() - TF.SEUIL - 60
        os.utime(TF.dossier() / "reminders", (vieux, vieux))
        self.assertEqual(TF.arretees(), ["reminders"])
        x = ligne("taches")
        self.assertEqual((x["etat"], x["alerte"], x["portee"]), (SI.PANNE, "arretees", SI.INSTALLATION))
        self.assertIn("relances", x["constat"])

    def test_signe_de_vie_toutes_les_minutes(self):
        with mock.patch.object(TF, "PAS", 0.05):
            TF.demarrer("imports")
            vieux = time.time() - TF.SEUIL - 60
            os.utime(TF.dossier() / "imports", (vieux, vieux))
            time.sleep(0.3)
        self.assertEqual(TF.arretees(), [])

    def test_controle_de_la_nuit_avec_des_erreurs(self):
        from collecte import controle_donnees as CD

        CD.enregistrer({"date": timezone.now().isoformat(), "space": "principal", "errors": 3, "warnings": 2, "infos": 0,
                        "problems": [{"check": "orphan_answers", "severity": "error", "count": 3, "examples": [], "message": ""},
                                     {"check": "tree", "severity": "warning", "count": 2, "examples": [], "message": ""}]})
        x = ligne("taches")
        self.assertEqual((x["etat"], x["alerte"]), (SI.A_REGARDER, "controle_erreurs"))
        self.assertIn("3 erreurs", x["constat"])

    def test_controle_avec_avertissements_seulement_n_alerte_pas(self):
        from collecte import controle_donnees as CD

        CD.enregistrer({"date": timezone.now().isoformat(), "space": "principal", "errors": 0, "warnings": 2, "infos": 0,
                        "problems": [{"check": "tree", "severity": "warning", "count": 2, "examples": [], "message": ""}]})
        self.assertEqual(ligne("taches")["alerte"], "")

    def test_controle_en_retard(self):
        from collecte import controle_donnees as CD

        CD.enregistrer({"date": (timezone.now() - datetime.timedelta(days=3)).isoformat(), "space": "principal", "errors": 1,
                        "warnings": 0, "infos": 0, "problems": []})
        self.assertEqual(ligne("taches")["alerte"], "controle_retard")

    def test_restauration_interrompue_n_alerte_pas(self):
        with mock.patch.object(SV, "restauration_en_cours", return_value=True):
            x = ligne("base")
        self.assertEqual((x["etat"], x["alerte"]), (SI.A_REGARDER, ""))  # se termine seule en une minute

    def test_mot_de_passe_smtp_a_saisir_de_nouveau(self):
        from django.test import override_settings

        with override_settings(SECRET_KEY="secret-d-un-autre-serveur-0123456789-abcdefghijkl"):
            x = ligne("email")
        self.assertEqual((x["alerte"], x["portee"]), ("mdp_illisible", SI.INSTALLATION))

    def test_relance_en_echec(self):
        from collecte.models import Relance
        from referentiel.models import Utilisateur

        u = Utilisateur.objects.create(username="c", email="c@exemple.example")
        Relance.objects.create(destinataire=u, statut=Relance.Statut.ECHEC)
        self.assertEqual(ligne("email")["alerte"], "echec")

    def test_meme_ligne_sur_la_page(self):
        """La page lit les mêmes lignes (``lignes`` appelle ``constats``) : un cas qui alerte se voit à l'écran."""
        from django.test import RequestFactory

        from referentiel.models import Utilisateur

        u = Utilisateur.objects.create(username="adm", email="adm@exemple.example", role="admin")
        r = RequestFactory().get("/")
        r.user = u
        with disque_plein():
            page, _ = SI.lignes(r)
            self.assertEqual([(x["cle"], x["etat"]) for x in page if x["alerte"]],
                             [(x["cle"], x["etat"]) for x in SI.constats(True) if x["alerte"]])
