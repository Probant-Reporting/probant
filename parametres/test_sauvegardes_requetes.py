"""Sauvegarde JSON : le nombre de requêtes ne dépend pas du nombre de lignes (``sauvegardes.requete_export``). Avant,
le sérialiseur relisait l'utilisateur de chaque ligne du journal (clé naturelle) et les liens plusieurs-à-plusieurs de
chaque objet : une requête par ligne (15 minutes pour 4 millions de lignes du journal sous PostgreSQL). L'archive
reste identique, octet pour octet, à celle de l'ancienne lecture ligne par ligne."""
import io
import json

from django.core import serializers
from django.db import connections
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from collecte.models import Campagne, Journal, Relance
from espaces import contexte as ESP
from referentiel.models import Utilisateur

from . import sauvegardes as SV


def ancien_export(flux):
    """L'export d'avant (une requête par ligne), pour comparer le contenu."""
    objets = (o for m in SV.modeles_sauvegardes(SV.modeles_de_la_base())
              for o in m._base_manager.order_by(m._meta.pk.name).iterator())
    serializers.serialize("json", objets, stream=flux, use_natural_foreign_keys=True, cls=SV.EncodeurExact)


class RequetesDeLaSauvegardeJson(TestCase):
    def setUp(self):
        self.utilisateurs = [Utilisateur.objects.create(username=f"u{i}", email=f"u{i}@exemple.test") for i in range(3)]
        self.campagnes = [Campagne.objects.create(exercice=2020 + i) for i in range(3)]

    def ajouter(self, n):
        """n lignes du journal (chacune avec un utilisateur) et n relances (chacune liée à deux campagnes)."""
        Journal.objects.bulk_create([Journal(utilisateur=self.utilisateurs[i % 3], action="essai", objet="Campagne",
                                             objet_id=str(i), apres=str(i)) for i in range(n)])
        for i in range(n):
            r = Relance.objects.create(destinataire=self.utilisateurs[i % 3], envoyee_par=self.utilisateurs[0])
            r.campagnes.set(self.campagnes[:2])

    def exporter(self):
        flux = io.StringIO()
        with CaptureQueriesContext(connections[ESP.alias_courant()]) as requetes:
            SV.exporter_json(flux)
        return len(requetes.captured_queries), flux.getvalue()

    def test_requetes_independantes_du_nombre_de_lignes(self):
        self.ajouter(5)
        peu, _ = self.exporter()
        self.ajouter(60)
        beaucoup, contenu = self.exporter()
        self.assertEqual(peu, beaucoup)
        lignes = [o for o in json.loads(contenu) if o["model"] == "collecte.journal"]
        self.assertEqual(len(lignes), 65)
        self.assertEqual(lignes[0]["fields"]["utilisateur"], ["u0"])  # clé naturelle : le nom du compte
        relances = [o for o in json.loads(contenu) if o["model"] == "collecte.relance"]
        self.assertEqual({frozenset(o["fields"]["campagnes"]) for o in relances}, {frozenset(c.pk for c in self.campagnes[:2])})

    def test_archive_identique_a_l_ancienne_lecture(self):
        self.ajouter(12)
        Journal.objects.create(utilisateur=None, action="sans", objet="Campagne", objet_id="0")  # sans utilisateur
        ancien = io.StringIO()
        ancien_export(ancien)
        self.assertEqual(self.exporter()[1], ancien.getvalue())
