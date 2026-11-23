"""Première sauvegarde automatique d'une installation neuve (``sauvegardes.planifier``).

Constaté à l'essai de l'installation Docker : sans aucune archive « auto » (installation neuve, ou restaurée
depuis une archive qui n'en contient pas), l'échéance était calculée à partir de « maintenant » à chaque tour de la boucle,
donc toujours dans le futur : à 02:29 l'échéance était 02:30, à 02:30 elle devenait 02:30 le lendemain. La sauvegarde
automatique ne partait jamais, sans alerte (page Hébergement : « prochaine sauvegarde » toujours affichée, aucun retard)."""
import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from . import sauvegardes as SV
from .aides_tests.hebergement import DossiersTemporaires
from .models import Instance


class PremiereSauvegardeAutomatiqueTests(DossiersTemporaires, TestCase):
    class Arret(Exception):
        pass

    def tourner_la_boucle(self, debut, minutes, frequence="jour"):
        """Fait tourner le planificateur ``minutes`` tours d'une minute à partir de ``debut`` ; renvoie les heures des
        sauvegardes automatiques demandées (``creer`` écrit une archive « auto » vide, comme la vraie)."""
        horloge = [debut]
        vraie_localtime = timezone.localtime
        faites = []

        def localtime(valeur=None, *a, **k):
            return vraie_localtime(valeur, *a, **k) if valeur is not None else horloge[0]

        def creer(motif):
            faites.append(horloge[0])
            SV.dossier().mkdir(parents=True, exist_ok=True)
            (SV.dossier() / f"backup-{horloge[0]:%Y%m%d-%H%M%S}-{motif}.zip").write_bytes(b"")

        def dormir(secondes):
            if len(faites) > 50 or horloge[0] >= debut + datetime.timedelta(minutes=minutes):
                raise self.Arret()
            horloge[0] += datetime.timedelta(seconds=secondes)

        from django.db import connections

        with mock.patch.object(SV.timezone, "localtime", localtime), mock.patch.object(SV.time, "sleep", dormir), \
                mock.patch.object(SV, "registre_du_jour"), mock.patch.object(SV, "tourner"), \
                mock.patch.object(SV, "creer", creer), mock.patch.object(SV, "base_vide", return_value=False), \
                mock.patch.object(SV.ESP, "codes_actifs", return_value=[SV.ESP.PRINCIPAL]), \
                mock.patch.object(connections, "close_all"), self.assertRaises(self.Arret):
            SV.planifier()
        return faites

    def regler(self, heure, frequence="jour"):
        i = Instance.courante()
        i.sauvegarde_auto, i.sauvegarde_heure, i.sauvegarde_frequence = True, heure, frequence
        i.save()

    def test_installation_neuve_la_premiere_sauvegarde_part_a_l_heure(self):
        self.regler("02:30")
        debut = timezone.make_aware(datetime.datetime(2026, 11, 16, 20, 4, 7))  # installée le soir, aucune archive
        faites = self.tourner_la_boucle(debut, minutes=3 * 24 * 60)
        self.assertEqual([(f.day, f.hour, f.minute) for f in faites], [(17, 2, 30), (18, 2, 30), (19, 2, 30)])

    def test_toutes_les_6_heures_des_le_premier_creneau(self):
        self.regler("02:30", "6h")
        debut = timezone.make_aware(datetime.datetime(2026, 11, 16, 20, 4, 7))
        faites = self.tourner_la_boucle(debut, minutes=13 * 60)
        # créneaux 02:30, 08:30, 14:30, 20:30 : le premier est 20:30 le jour même
        self.assertEqual([(f.day, f.hour, f.minute) for f in faites], [(16, 20, 30), (17, 2, 30), (17, 8, 30)])
