"""« restore --shared » sous PostgreSQL : les lignes du registre sont rechargées avec leur numéro ; les séquences doivent
repasser au-dessus, sinon la création suivante d'un espace ou d'un accès reprend un numéro déjà pris (constaté lors du
retour arrière d'une mise à jour : registre restauré dans une base neuve, puis IntegrityError au démarrage)."""
import unittest

from django.conf import settings
from django.db import connections

from django.test import TransactionTestCase

from . import sauvegardes as SV
from .aides_tests.hebergement import DossiersTemporaires
from espaces.models import AccesEspace, Espace, Installation, MarqueEspace

POSTGRES = settings.DATABASES["default"]["ENGINE"].endswith("postgresql")


@unittest.skipUnless(POSTGRES, "séquences : PostgreSQL seulement")
class SequencesDuRegistre(DossiersTemporaires, TransactionTestCase):
    databases = {"default", "commun"}

    def setUp(self):
        super().setUp()
        Installation.objects.create(identifiant="installation-essai")
        MarqueEspace.objects.create(code="principal", installation="installation-essai")
        p = Espace.objects.create(code="principal", nom="Principal", etat=Espace.Etat.ACTIF)
        archive = Espace.objects.create(code="ancien", nom="Ancien", etat=Espace.Etat.ARCHIVE, rang=1)
        for e in (p, archive):
            AccesEspace.objects.create(compte_id=999001, espace=e, role="lecteur")

    def test_creation_apres_restauration_du_registre(self):
        chemin = SV.creer_registre("essai")
        # registre neuf (démarrage sur une base vide) : séquences au début
        with connections["commun"].cursor() as c:
            for table in ("espaces_espace", "espaces_accesespace"):
                c.execute(f"ALTER SEQUENCE {table}_id_seq RESTART WITH 1")
        SV.restaurer_registre(chemin)
        e = Espace.objects.create(code="qualite", nom="Qualité", etat=Espace.Etat.ARCHIVE, rang=5)
        a = AccesEspace.objects.create(compte_id=999002, espace=e, role="lecteur")
        self.assertGreater(e.pk, max(Espace.objects.exclude(pk=e.pk).values_list("pk", flat=True)))
        self.assertGreater(a.pk, max(AccesEspace.objects.exclude(pk=a.pk).values_list("pk", flat=True)))
