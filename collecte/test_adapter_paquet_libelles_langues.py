"""Unités réécrites dans la monnaie de référence (``parametres.monnaies.adapter_paquet``) : l'unité créée à l'installation
d'un modèle porte son libellé dans chaque langue de l'interface, comme l'unité en euros du catalogue (avant : français et
anglais seulement)."""
from django.test import TestCase

from parametres import monnaies as MO
from parametres.libelles import langues_disponibles
from parametres.models import Instance, Unite

from . import paquets as P


class LibellesSeptLanguesTests(TestCase):
    def test_unites_en_dollars_dans_toutes_les_langues(self):
        i = Instance.courante()
        i.monnaie = "USD"
        i.save()
        a = P.analyser(P.fourni("vs_base.json").paquet, fourni=True)
        P.appliquer(None, a, sans_recalcul=True)
        langues = langues_disponibles()
        self.assertEqual(len(langues), 7)
        for code_modele, symbole in (("€", "$"), ("M€", "M$"), ("€/h", "$/h")):
            u = Unite.objects.get(symbole=symbole)
            for lg in langues:
                attendu = MO.libelle_unite(code_modele, "USD", lg)
                texte = u.libelle if lg == "fr" else (u.traductions.get(lg) or {}).get("libelle")
                self.assertEqual(texte, attendu, (symbole, lg))
