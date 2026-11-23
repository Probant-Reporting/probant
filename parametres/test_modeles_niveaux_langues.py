"""Modèles de niveaux de l'assistant de mise en place (étape « Organisation ») dans les sept langues de l'interface.

Avant : les quatre modèles (« Groupe › Pays › Entité › Site », « Holding › Filiale »…) étaient écrits en
français, dans le choix proposé comme dans les niveaux créés, quelles que soient la langue de l'écran et celle de
l'installation, et les niveaux créés n'avaient aucune traduction."""
import importlib

from django.test import TestCase
from django.urls import reverse

from referentiel.models import Utilisateur

from . import mise_en_place as M
from . import niveaux as N
from .models import Instance, NiveauHierarchique

SEPT = {"en", "fr", "es", "de", "it", "nl", "pt"}


def etape(n):
    return reverse("parametres:mise_en_place_etape", args=[n])


class TableTests(TestCase):
    def test_chaque_niveau_dans_les_sept_langues(self):
        for code, langues in N.NOMS_MODELES.items():
            self.assertEqual(set(langues), SEPT, code)
            for lg, (nom, pluriel) in langues.items():
                self.assertTrue(nom.strip() and pluriel.strip(), (code, lg))
        for cle, codes in N.MODELES_NIVEAUX:
            self.assertTrue(set(codes) <= set(N.NOMS_MODELES), cle)

    def test_memes_textes_que_les_niveaux_de_depart(self):
        """Group, Country, Entity, Site : une installation neuve, dans n'importe quelle langue, reconnaît son modèle."""
        depart = importlib.import_module("parametres.migrations.0036_traductions_de_depart_sept_langues").NIVEAUX
        for code, rang, nom, pluriel, *_ in N.PAR_DEFAUT:
            self.assertEqual(N.NOMS_MODELES[code]["fr"], (nom, pluriel))
            self.assertEqual(N.NOMS_MODELES[code]["en"], (code, N.PLURIELS_EN[code]))
            for lg, textes in depart[code][2].items():
                self.assertEqual(N.NOMS_MODELES[code][lg], textes, (code, lg))


class AssistantTests(TestCase):
    def setUp(self):
        N.creer_par_defaut()
        self.admin = Utilisateur.objects.create_user("admin", "admin@exemple.test", "Essai-modeles-2026", role="admin",
                                                     is_superuser=True, is_staff=True)
        i = Instance.courante()
        i.mise_en_place_etape = 4
        i.save()
        self.client.force_login(self.admin)

    def choisir(self, langue_ecran):
        Utilisateur.objects.filter(pk=self.admin.pk).update(langue=langue_ecran)
        return self.client.get(etape(4))

    def test_choix_dans_la_langue_de_l_ecran(self):
        attendus = {"en": "Holding › Subsidiary › Site", "de": "Holding › Tochtergesellschaft › Standort",
                    "it": "Holding › Controllata › Sede", "nl": "Holding › Dochteronderneming › Locatie",
                    "pt": "Holding › Filial › Local", "es": "Holding › Filial › Centro", "fr": "Holding › Filiale › Site"}
        for lg, texte in attendus.items():
            rep = self.choisir(lg)
            self.assertContains(rep, texte, msg_prefix=lg)
        self.assertNotContains(self.choisir("de"), "Filiale")

    def test_niveaux_crees_dans_la_langue_de_l_installation_et_traduits(self):
        i = Instance.courante()
        i.langue_reference = "en"
        i.save()
        self.client.post(etape(4), {"action": "niveaux", "modele": "holding-filiale-site"})
        niveaux = list(NiveauHierarchique.objects.order_by("rang"))
        self.assertEqual([(n.code, n.nom, n.nom_pluriel) for n in niveaux],
                         [("Holding", "Holding", "Holding"), ("Filiale", "Subsidiary", "Subsidiaries"), ("Site", "Site", "Sites")])
        filiale = niveaux[1]
        self.assertEqual(filiale.traductions["fr"], {"nom": "Filiale", "nom_pluriel": "Filiales"})
        self.assertEqual(filiale.traductions["de"], {"nom": "Tochtergesellschaft", "nom_pluriel": "Tochtergesellschaften"})
        self.assertNotIn("en", filiale.traductions)  # la langue de référence est dans le nom lui-même
        self.assertEqual(set(filiale.traductions), SEPT - {"en"})

    def test_installation_neuve_reconnait_son_modele(self):
        """Niveaux de départ (Groupe › Pays › Entité › Site) : le modèle est coché, quelle que soit la langue de l'écran."""
        for lg in ("fr", "en", "de"):
            rep = self.choisir(lg)
            self.assertContains(rep, 'value="groupe-pays-entite-site" checked', msg_prefix=lg)

    def test_modele_reconnu_apres_application(self):
        self.client.post(etape(4), {"action": "niveaux", "modele": "holding-filiale"})
        rep = self.choisir("it")
        self.assertContains(rep, 'value="holding-filiale" checked')

    def test_definitions_dans_la_langue_de_reference(self):
        defs = M.definitions_niveaux({"modele": "groupe-pays-site"})
        self.assertEqual([d[:3] for d in defs], [("Group", "Groupe", "Groupe"), ("Country", "Pays", "Pays"), ("Site", "Site", "Sites")])
