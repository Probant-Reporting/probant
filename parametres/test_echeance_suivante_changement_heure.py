"""Sauvegarde automatique aux changements d'heure (``sauvegardes.echeance_suivante``) : une seule sauvegarde la nuit où
l'heure recule (02:00 à 03:00 se joue deux fois) et la nuit où elle avance (02:00 à 03:00 n'existe pas), avec l'heure par
défaut 02:30, dans le fuseau par défaut (Europe/Brussels).

Avant : la nuit où l'heure recule, la sauvegarde de 02:30 (heure d'été) était prise pour une sauvegarde « datée dans le
futur » entre 02:00 et 02:25 (heure d'hiver) : les heures locales étaient comparées sans leur décalage. La prochaine
échéance rendue était alors 02:30 le jour même (page Hébergement) ; une sauvegarde partie en retard (après un échec, le
planificateur réessaie dix minutes plus tard) pouvait être refaite une seconde fois."""
import datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from django.utils import timezone

from . import sauvegardes as SV

BRUXELLES = ZoneInfo("Europe/Brussels")
UTC = datetime.timezone.utc


def nuit(jour_utc, heure, frequence="jour"):
    """Simule le planificateur minute par minute pendant une nuit : renvoie les heures locales des sauvegardes faites.
    La date d'une archive est relue depuis son nom (heure locale sans décalage, ``Archive.date``)."""
    faites = []
    derniere = timezone.make_aware(datetime.datetime(jour_utc.year, jour_utc.month, jour_utc.day - 1, 2, 30, 5))
    t = datetime.datetime(jour_utc.year, jour_utc.month, jour_utc.day, 0, 0, tzinfo=UTC) - datetime.timedelta(hours=1)
    for _ in range(5 * 60):
        maintenant = timezone.localtime(t)
        if SV.echeance_suivante(frequence, heure, derniere, maintenant) <= maintenant:
            faites.append(maintenant)
            nom = f"backup-{maintenant:%Y%m%d-%H%M%S}-auto.zip"  # comme ``creer``
            derniere = timezone.make_aware(datetime.datetime.strptime(SV._horodatage(nom), "%Y%m%d-%H%M%S"))
        t += datetime.timedelta(minutes=1)
    return faites


class ChangementsDHeure(SimpleTestCase):
    def setUp(self):
        timezone.activate(BRUXELLES)
        self.addCleanup(timezone.deactivate)

    def test_heure_qui_recule_une_seule_sauvegarde(self):
        faites = nuit(datetime.date(2026, 10, 25), "02:30")
        self.assertEqual(len(faites), 1, faites)
        self.assertEqual((faites[0].hour, faites[0].minute, faites[0].utcoffset()), (2, 30, datetime.timedelta(hours=2)))

    def test_heure_qui_avance_une_seule_sauvegarde(self):
        faites = nuit(datetime.date(2026, 3, 29), "02:30")
        self.assertEqual(len(faites), 1, faites)
        self.assertEqual((faites[0].hour, faites[0].minute), (3, 0))  # 02:30 n'existe pas : dès 03:00

    def test_sauvegarde_de_la_premiere_02_30_pas_dans_le_futur(self):
        derniere = timezone.make_aware(datetime.datetime(2026, 10, 25, 2, 30, 10))  # heure d'été (nom de l'archive)
        maintenant = datetime.datetime(2026, 10, 25, 2, 5, fold=1, tzinfo=BRUXELLES)  # heure d'hiver, 35 min plus tard
        self.assertEqual(SV.echeance_suivante("jour", "02:30", derniere, maintenant),
                         datetime.datetime(2026, 10, 26, 2, 30, tzinfo=BRUXELLES))

    def test_horloge_vraiment_remise_en_arriere_toujours_reconnue(self):
        derniere = timezone.make_aware(datetime.datetime(2026, 10, 20, 2, 30))
        maintenant = datetime.datetime(2026, 10, 19, 10, 0, tzinfo=BRUXELLES)
        self.assertEqual(SV.echeance_suivante("jour", "02:30", derniere, maintenant),
                         datetime.datetime(2026, 10, 20, 2, 30, tzinfo=BRUXELLES))
