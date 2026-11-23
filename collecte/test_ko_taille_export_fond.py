"""Taille d'un gros export prêt (Mes exports, ``_export_fond.html``) : en Ko sous 1 Mo (un fichier de 17 Ko ne s'affiche plus
« 0 Mo »), en Mo au-delà, au format de la langue."""
import datetime

from django.template.loader import render_to_string
from django.test import TestCase
from django.utils import timezone

from parametres import langues as L
from referentiel.models import Utilisateur

from .models import TacheExport
from .templatetags.collecte import ko


class TailleExportFondTests(TestCase):
    def ligne(self, taille, langue):
        u = Utilisateur.objects.create(username=f"u{taille}{langue}", email=f"u{taille}{langue}@exemple.test")
        t = TacheExport.objects.create(utilisateur=u, titre="Gros", statut=TacheExport.Statut.PRET, taille=taille,
                                       expire_le=timezone.now() + datetime.timedelta(days=7))
        with L.activer_interface(langue):
            return render_to_string("collecte/echanges/_export_fond.html", {"t": t})

    def test_ko_sous_un_mo(self):
        self.assertIn("Prêt · 17 Ko ·", self.ligne(17 * 1024, "fr"))
        self.assertIn("Ready · 17 KB ·", self.ligne(17 * 1024, "en"))
        self.assertIn("Prêt · 1 Ko ·", self.ligne(300, "fr"))  # jamais « 0 »
        self.assertIn("Prêt · 1,5 Mo ·", self.ligne(1572864, "fr"))
        self.assertIn("Ready · 1.5 MB ·", self.ligne(1572864, "en"))

    def test_filtre_ko(self):
        self.assertEqual([ko(n) for n in (0, 1, 1024, 1025, 17 * 1024, 1024 * 1024 - 1)], [0, 1, 1, 2, 17, 1024])
