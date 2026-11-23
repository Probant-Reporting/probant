"""Assistant de mise en place : les valeurs par défaut de l'identité (nom de la structure, contact) suivent la langue de la
personne qui installe, ou la langue par défaut choisie à l'étape des langues ; un texte déjà choisi n'est jamais touché."""
from django.test import TestCase
from django.urls import reverse

from .libelles import libelle
from .models import Instance

MDP = "Essai-mise-en-place-2026"
ADMIN = {"prenom": "Alice", "nom": "Exemple", "email": "admin@exemple.test", "mot_de_passe": MDP, "confirmation": MDP}
LANGUES = ("fr", "en", "es", "de", "it", "nl", "pt")


def etape(n):
    return reverse("parametres:mise_en_place_etape", args=[n])


class DefautsSelonLaLangueTests(TestCase):
    def installer(self, langue):
        self.client.post(reverse("langue"), {"langue": langue})
        self.assertRedirects(self.client.post(reverse("parametres:mise_en_place"), ADMIN), etape(2))
        return Instance.courante()

    def test_nom_et_contact_dans_la_langue_de_l_installateur(self):
        i = self.installer("de")
        self.assertEqual(i.nom, libelle("referentiels.mep.defaut.nom", langue="de"))
        self.assertEqual(i.contact, libelle("referentiels.mep.defaut.contact", langue="de"))
        self.assertNotIn("l'administrateur", i.contact)
        self.assertNotEqual(i.nom, "Ma structure")

    def test_les_sept_langues_ont_leurs_valeurs(self):
        textes = {libelle("referentiels.mep.defaut.nom", langue=l) for l in LANGUES}
        contacts = {libelle("referentiels.mep.defaut.contact", langue=l) for l in LANGUES}
        self.assertEqual((len(textes), len(contacts)), (7, 7))

    def test_la_page_de_l_etape_2_les_montre_dans_la_langue(self):
        self.installer("en")
        rep = self.client.get(etape(2))
        self.assertContains(rep, libelle("referentiels.mep.defaut.nom", langue="en"))
        self.assertNotContains(rep, "Ma structure")
        self.assertNotContains(rep, "l'administrateur de l'outil")

    def test_une_valeur_choisie_n_est_jamais_remplacee(self):
        i = self.installer("fr")
        i.nom = "Exemple SA"
        i.save(update_fields=["nom"])
        from . import mise_en_place as M

        M.localiser_defauts(i, "de")
        i.refresh_from_db()
        self.assertEqual(i.nom, "Exemple SA")
        self.assertEqual(i.contact, libelle("referentiels.mep.defaut.contact", langue="de"))  # encore la valeur par défaut

    def test_langue_par_defaut_choisie_a_l_etape_des_langues(self):
        i = self.installer("fr")
        self.assertEqual(i.nom, libelle("referentiels.mep.defaut.nom", langue="fr"))
        corps = {"defaut": "en", "libelle__fr": "Français", "libelle__en": "English", "active__fr": "on", "active__en": "on"}
        self.client.post(etape(3), corps)
        i.refresh_from_db()
        self.assertEqual(i.nom, libelle("referentiels.mep.defaut.nom", langue="en"))
