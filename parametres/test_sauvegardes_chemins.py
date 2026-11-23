"""Sauvegardes : chemins risqués que la suite ne parcourait pas — archive refusée
(pas une sauvegarde, autre outil, incomplète, version plus récente, restauration dans une transaction), fichiers d'une
archive qui sortiraient du dossier (« ../ »), historique des restaurations abîmé ou à l'ancien nom, planificateur des
sauvegardes automatiques (échéance, erreur qui n'arrête pas la boucle), heure mal écrite."""
import datetime
import io
import json
import zipfile
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from . import sauvegardes as SV
from .models import Instance
from .aides_tests.hebergement import DossiersTemporaires


def archive_zip(chemin, descriptif=None, fichiers=None):
    """Écrit une archive de test (descriptif, base JSON vide, fichiers {nom dans l'archive: contenu})."""
    with zipfile.ZipFile(chemin, "w") as z:
        if descriptif is not None:
            z.writestr(SV.DESCRIPTIF, json.dumps(descriptif))
        for nom, contenu in (fichiers or {}).items():
            z.writestr(nom, contenu)
    return chemin


def descriptif(**autres):
    return {"format": SV.FORMAT, "outil": SV.OUTIL, "version": "0.9.0", "migrations": SV.migrations_appliquees(),
            "espace": "principal", **autres}


class ArchivesRefuseesTests(DossiersTemporaires, TestCase):
    def test_pas_une_sauvegarde(self):
        faux = self.tmp / "faux.zip"
        faux.write_bytes(b"pas un zip")
        with self.assertRaises(SV.ErreurSauvegarde):
            SV.lire_descriptif(faux)
        with self.assertRaises(SV.ErreurSauvegarde):  # zip sans descriptif
            SV.lire_descriptif(archive_zip(self.tmp / "vide.zip", fichiers={"x.txt": "x"}))

    def test_autre_outil_ou_incomplete(self):
        autre = archive_zip(self.tmp / "autre.zip", {"format": 1, "outil": "autre-chose"}, {SV.BASE_JSON: "[]"})
        with self.assertRaises(SV.ErreurSauvegarde):
            SV.lire_descriptif(autre)
        sans_base = archive_zip(self.tmp / "sans-base.zip", descriptif())
        with self.assertRaises(SV.ErreurSauvegarde):
            SV.lire_descriptif(sans_base)
        ancien = archive_zip(self.tmp / "ancien.zip", fichiers={"sauvegarde.json": json.dumps(descriptif()), "base.json": "[]"})
        self.assertEqual(SV.lire_descriptif(ancien)["outil"], "probant")  # noms français d'avant la mise à jour

    def test_seul_le_nom_du_projet_est_lu(self):
        # une archive se reconnaît au seul nom « probant » : aucun autre nom n'est accepté
        self.assertEqual(SV.OUTILS_ACCEPTES, (SV.OUTIL,))
        nouvelle = archive_zip(self.tmp / "nouvelle.zip", descriptif(), {SV.BASE_JSON: "[]"})
        self.assertEqual(SV.lire_descriptif(nouvelle)["outil"], "probant")

    def test_version_plus_recente_refusee(self):
        d = descriptif(migrations=SV.migrations_appliquees() + [["collecte", "9999_version_future"]])
        futur = archive_zip(self.tmp / "futur.zip", d, {SV.BASE_JSON: "[]"})
        with self.assertRaises(SV.ErreurSauvegarde) as e:
            SV.restaurer(futur, sauvegarder_avant=False)
        self.assertIn("0.9.0", str(e.exception))

    def test_restauration_refusee_dans_une_transaction(self):
        bonne = archive_zip(self.tmp / "bonne.zip", descriptif(), {SV.BASE_JSON: "[]"})
        with self.assertRaises(SV.ErreurSauvegarde):  # un TestCase est une transaction : rien n'est touché
            SV.restaurer(bonne, sauvegarder_avant=False)

    def test_fichiers_hors_du_dossier_ignores(self):
        tampon = io.BytesIO()
        with zipfile.ZipFile(tampon, "w") as z:
            z.writestr(SV.FICHIERS_ARCHIVE + "preuves/ok.pdf", b"ok")
            z.writestr(SV.FICHIERS_ARCHIVE + "../dehors.txt", b"non")
            z.writestr(SV.FICHIERS_ARCHIVE + "preuves/../../dehors2.txt", b"non")
            z.writestr("fichiers/ancien.pdf", b"ancien")  # ancien nom du dossier
        with zipfile.ZipFile(tampon) as z:
            SV._restaurer_fichiers(z)
        media = self.tmp / "media"
        self.assertEqual((media / "preuves" / "ok.pdf").read_bytes(), b"ok")
        self.assertEqual((media / "ancien.pdf").read_bytes(), b"ancien")
        self.assertFalse((self.tmp / "dehors.txt").exists())
        self.assertFalse((self.tmp / "dehors2.txt").exists())


class HistoriqueTests(DossiersTemporaires, TestCase):
    def test_ancien_nom_et_lignes_abimees(self):
        SV.dossier().mkdir(parents=True, exist_ok=True)
        ancien = SV.dossier() / "restaurations.jsonl"
        lignes = [json.dumps({"date": "2026-10-01T10:00:00+02:00", "archive": "a.zip"}), "{pas du json",
                  json.dumps({"archive": "sans-date.zip"}), json.dumps({"date": "pas une date"}),
                  json.dumps({"date": "2026-10-02T10:00:00+02:00", "archive": "b.zip"})]
        ancien.write_text("\n".join(lignes), encoding="utf-8")
        h = SV.historique_restaurations()
        self.assertEqual([e["archive"] for e in h], ["b.zip", "a.zip"])  # la plus récente d'abord, lignes abîmées sautées
        self.assertTrue((SV.dossier() / SV.HISTORIQUE).is_file())
        self.assertFalse(ancien.exists())


class PlanificateurTests(DossiersTemporaires, TestCase):
    class Arret(Exception):
        pass

    def un_tour(self, **mocks):
        """Un tour de la boucle sans fin : ``time.sleep`` l'arrête ; renvoie la pause demandée."""
        pauses = []

        def dormir(s):
            pauses.append(s)
            raise self.Arret()

        from django.db import connections

        # la boucle ferme les connexions entre deux tours (serveur) : pas dans un test, qui tourne dans une transaction
        with mock.patch.object(SV.time, "sleep", dormir), mock.patch.object(SV, "registre_du_jour"), \
                mock.patch.object(SV.ESP, "codes_actifs", return_value=[SV.ESP.PRINCIPAL]), \
                mock.patch.object(connections, "close_all"):
            with mock.patch.multiple(SV, **mocks), self.assertRaises(self.Arret):
                SV.planifier()
        return pauses[0]

    def test_sauvegarde_a_l_echeance_puis_rotation(self):
        i = Instance.courante()
        i.sauvegarde_auto, i.sauvegarde_conserver = True, 3
        i.save()
        creer, tourner = mock.Mock(), mock.Mock()
        with mock.patch.object(SV, "echeance_suivante", return_value=timezone.localtime() - datetime.timedelta(minutes=1)):
            self.assertEqual(self.un_tour(creer=creer, tourner=tourner), 60)
        creer.assert_called_once_with("auto")
        tourner.assert_called_once_with(3)

    def test_pas_encore_l_heure_ou_desactivee(self):
        i = Instance.courante()
        i.sauvegarde_auto = True
        i.save()
        creer = mock.Mock()
        with mock.patch.object(SV, "echeance_suivante", return_value=timezone.localtime() + datetime.timedelta(hours=1)):
            self.un_tour(creer=creer, tourner=mock.Mock())
        i.sauvegarde_auto = False
        i.save()
        self.un_tour(creer=creer, tourner=mock.Mock())
        creer.assert_not_called()

    def test_une_erreur_n_arrete_pas_la_boucle(self):
        i = Instance.courante()
        i.sauvegarde_auto = True
        i.save()
        with mock.patch.object(SV, "echeance_suivante", return_value=timezone.localtime() - datetime.timedelta(minutes=1)), \
                self.assertLogs("reporting.sauvegarde", "ERROR"):
            pause = self.un_tour(creer=mock.Mock(side_effect=OSError("disque plein")), tourner=mock.Mock())
        self.assertEqual(pause, 600)  # on réessaiera dans 10 minutes


class EcheanceTests(TestCase):
    def test_heure_mal_ecrite(self):
        maintenant = timezone.make_aware(datetime.datetime(2026, 11, 2, 1, 0))
        self.assertEqual(SV.echeance_suivante("jour", "minuit", None, maintenant).strftime("%H:%M"), "02:30")
        self.assertEqual(SV.echeance_suivante("inconnue", "03:15", None, maintenant),
                         timezone.make_aware(datetime.datetime(2026, 11, 2, 3, 15)))
        apres = SV.echeance_suivante("6h", "03:00", maintenant - datetime.timedelta(days=2), maintenant)
        self.assertLess(apres, maintenant)  # échéance manquée (serveur arrêté) : rattrapée tout de suite
