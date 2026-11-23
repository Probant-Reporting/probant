"""Arbre de la page Organisations (Administration) : repères des branches. Une organisation qui a des descendants porte
le bouton « replier » ; celle dont tous les descendants sont du niveau le plus bas porte ``data-que-bas`` (« Sans les
sites » la replie) ; une organisation qui a un descendant au-dessus du niveau le plus bas, ou qui n'a aucun descendant,
ne le porte pas."""
import re

from django.test import TestCase
from django.urls import reverse

from referentiel.models import Niveau, Organisation, Utilisateur


class ReperesDesBranchesTests(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.vide = Organisation.objects.create(nom="Pays vide", niveau_id=Niveau.COUNTRY, parent=self.g)
        # niveau le plus bas des niveaux d'installation : « Site »
        self.e1 = Organisation.objects.create(nom="S1", niveau_id=Niveau.SITE, parent=self.p)
        self.e2 = Organisation.objects.create(nom="S2", niveau_id=Niveau.SITE, parent=self.p)
        self.siege = Organisation.objects.create(nom="Siège", niveau_id=Niveau.SITE, parent=self.g)  # site sous le groupe
        admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(admin)

    def lignes(self):
        html = self.client.get(reverse("collecte:admin_organisations")).content.decode()
        sortie = {}
        for m in re.finditer(r'<tr class="ligne [^>]*data-id="(\d+)"[^>]*>(.*?)</tr>', html, flags=re.S):
            sortie[int(m.group(1))] = ('data-que-bas="1"' in m.group(0).split(">", 1)[0], 'class="replier-org"' in m.group(2))
        return sortie

    def test_reperes(self):
        lignes = self.lignes()
        # (que_bas, bouton replier)
        self.assertEqual(lignes[self.g.pk], (False, True))  # a un pays sous lui : pas « que des sites »
        self.assertEqual(lignes[self.p.pk], (True, True))  # seulement des sites
        self.assertEqual(lignes[self.vide.pk], (False, False))  # aucun descendant
        for site in (self.e1, self.e2, self.siege):
            self.assertEqual(lignes[site.pk], (False, False), site.nom)
