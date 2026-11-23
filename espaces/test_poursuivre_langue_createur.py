"""Langue de la personne dans un nouvel espace : l'assistant de mise en place d'un espace créé
par un administrateur dont le compte est en français s'ouvrait en anglais, la copie de son compte dans le nouvel espace
n'ayant pas de langue (la langue est rangée dans chaque copie du compte, pas dans le registre commun ; ``recopier_langue``
ne tenait à jour que les copies existantes). La copie du créateur reprend sa langue ; un compte existant rattaché à un
autre espace (même e-mail) aussi.

Données inventées uniquement."""
from django.test import Client, override_settings

from parametres import langues as L
from referentiel.models import Utilisateur

from . import contexte as E
from .aides_tests import DossierTemporaire, creer
from .essais import EspacesTestCase


class LangueCreateurTests(DossierTemporaire, EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gestionnaire = creer("gestion@exemple.example", "admin", langue="fr")

    @override_settings(LANGUE_PAR_DEFAUT="en")  # comme une installation réelle (les essais sont en français)
    def test_assistant_du_nouvel_espace_dans_la_langue_du_createur(self):
        client = Client()
        client.force_login(Utilisateur.objects.get(pk=self.gestionnaire.pk))
        r = client.post("/administration/espaces/nouveau/", {"nom": "Achats France", "code": "achats", "identite": "on"})
        self.assertEqual(r.status_code, 302)
        with E.activer("achats"):
            self.assertEqual(Utilisateur.objects.get(pk=self.gestionnaire.pk).langue, "fr")
            self.assertEqual(L.interface_de(""), "en")  # l'espace neuf, lui, est en anglais par défaut
            # (l'assistant propose de choisir les langues de l'espace ; la personne garde la sienne)
        r = client.get("/espace/achats/mise-en-place/2/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '<html lang="fr"')

    def test_compte_existant_rattache_garde_sa_langue(self):
        from .creation import creer as creer_espace

        creer_espace("Achats France", "achats", Utilisateur.objects.get(pk=self.gestionnaire.pk))
        autre = creer("camille@exemple.example", "contributeur", langue="es")
        with E.activer("achats"):
            copie = Utilisateur(username="camille-achats", email="camille@exemple.example", role="contributeur")
            copie.save()
            self.assertEqual(copie.pk, autre.pk)
            self.assertEqual(Utilisateur.objects.get(pk=autre.pk).langue, "es")
