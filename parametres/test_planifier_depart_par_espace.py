"""Départ de la première sauvegarde automatique, par espace (``sauvegardes.planifier``).

Le départ (référence de l'échéance tant qu'un espace n'a aucune archive « auto ») était fixé une fois, au démarrage du
planificateur, pour tous les espaces : un espace créé plusieurs jours après, ou dont la sauvegarde automatique est activée
plusieurs jours après, sauvegardait tout de suite au lieu d'attendre l'heure réglée. Il est désormais noté par espace, la
première fois que le planificateur le voit actif sans archive « auto »."""
import datetime
from unittest import mock

from django.db import connections
from django.test import TestCase
from django.utils import timezone

from . import sauvegardes as SV
from .aides_tests.hebergement import DossiersTemporaires
from .models import Instance


class DepartParEspaceTests(DossiersTemporaires, TestCase):
    class Arret(Exception):
        pass

    def tourner_la_boucle(self, debut, minutes, a_l_heure=None, codes=None):
        """Planificateur sur ``minutes`` tours d'une minute ; ``a_l_heure`` : {datetime: fonction} appelée une fois quand
        l'horloge atteint cette heure ; ``codes(horloge)`` : espaces actifs à cet instant. Renvoie les heures des
        sauvegardes automatiques."""
        horloge = [debut]
        a_faire = dict(a_l_heure or {})
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
            for quand in [q for q in a_faire if q <= horloge[0]]:
                a_faire.pop(quand)()

        def codes_actifs():
            return codes(horloge[0]) if codes else [SV.ESP.PRINCIPAL]

        with mock.patch.object(SV.timezone, "localtime", localtime), mock.patch.object(SV.time, "sleep", dormir), \
                mock.patch.object(SV, "registre_du_jour"), mock.patch.object(SV, "tourner"), \
                mock.patch.object(SV, "creer", creer), mock.patch.object(SV, "base_vide", return_value=False), \
                mock.patch.object(SV.ESP, "codes_actifs", side_effect=codes_actifs), \
                mock.patch.object(connections, "close_all"), self.assertRaises(self.Arret):
            SV.planifier()
        return faites

    def regler(self, active, heure="02:30", frequence="jour"):
        i = Instance.courante()
        i.sauvegarde_auto, i.sauvegarde_heure, i.sauvegarde_frequence = active, heure, frequence
        i.save()

    def test_sauvegarde_activee_plusieurs_jours_apres_le_demarrage(self):
        self.regler(False)
        debut = timezone.make_aware(datetime.datetime(2026, 11, 16, 20, 4, 7))
        activation = timezone.make_aware(datetime.datetime(2026, 11, 19, 14, 0))
        faites = self.tourner_la_boucle(debut, minutes=4 * 24 * 60, a_l_heure={activation: lambda: self.regler(True)})
        self.assertEqual([(f.day, f.hour, f.minute) for f in faites], [(20, 2, 30)])  # pas le 19 à 14:00

    def test_espace_cree_plusieurs_jours_apres_le_demarrage(self):
        self.regler(True)
        debut = timezone.make_aware(datetime.datetime(2026, 11, 16, 20, 4, 7))
        creation = timezone.make_aware(datetime.datetime(2026, 11, 19, 14, 0))
        faites = self.tourner_la_boucle(debut, minutes=4 * 24 * 60,
                                        codes=lambda t: [SV.ESP.PRINCIPAL] if t >= creation else [])
        self.assertEqual([(f.day, f.hour, f.minute) for f in faites], [(20, 2, 30)])

    def test_desactivee_puis_reactivee_sans_archive_repart_de_la_reactivation(self):
        self.regler(True)
        debut = timezone.make_aware(datetime.datetime(2026, 11, 16, 20, 4, 7))
        arret = timezone.make_aware(datetime.datetime(2026, 11, 16, 22, 0))
        reprise = timezone.make_aware(datetime.datetime(2026, 11, 19, 14, 0))
        faites = self.tourner_la_boucle(debut, minutes=4 * 24 * 60,
                                        a_l_heure={arret: lambda: self.regler(False), reprise: lambda: self.regler(True)})
        self.assertEqual([(f.day, f.hour, f.minute) for f in faites], [(20, 2, 30)])
