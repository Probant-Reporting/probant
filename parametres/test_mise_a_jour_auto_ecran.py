"""Bloc « Mises à jour automatiques » de Paramètres › Hébergement (``mise_a_jour_auto.py``) : le choix (automatique,
prévenir seulement, éteint, délai) se règle seulement par un gestionnaire des espaces (ici le premier administrateur
de l'espace principal ; un administrateur qui n'est pas gestionnaire : ``test_est_gestionnaire_reglages_installation``) ; l'administrateur d'un autre espace voit l'état seul ; lecteur, auditeur,
contributeur et validateur n'écrivent rien. Hors image Docker (hébergement géré, version tout-en-un) : pas disponible.
L'état vient du fichier écrit par la machine, montré par des textes de l'outil seulement."""
import datetime
import html
import os
import re
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from collecte.models import Journal
from espaces import contexte as E
from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from espaces.models import Compte
from parametres import langues as L
from parametres import mise_a_jour_auto as MA
from parametres.libelles import libelle
from parametres.test_detail_installation_permis import connecter

URL = "/administration/parametres/hebergement/"
DOCKER = mock.patch.dict(os.environ, {"DANS_DOCKER": "1"})


def texte(page):
    """Texte visible d'une page (balises retirées, entités rendues) : une phrase s'y cherche entière."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", page)))


def resultat(**valeurs):
    v = {"format": "1", "task": "systemd", "time": "04:00", "checked": timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
         "state": "up_to_date", "installed": "1.0.2", **valeurs}
    return "".join(f"{k}={x}\n" for k, x in v.items() if x is not None)


class EcranTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")
        cls.autres = {r: creer(f"{r}@exemple.example", r) for r in ("lecteur", "auditeur", "contributeur", "validateur")}

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        r = override_settings(DOSSIER_DONNEES=self.tmp)
        r.enable()
        self.addCleanup(r.disable)
        DOCKER.start()
        self.addCleanup(DOCKER.stop)

    def ecrire(self, texte):
        MA.dossier().mkdir(parents=True, exist_ok=True)
        (MA.dossier() / MA.RESULTAT).write_text(texte, encoding="utf-8")

    def page(self, client, prefixe=""):
        return client.get(f"{prefixe}{URL}").content.decode()

    def test_formulaire_pour_qui_voit_le_detail_et_tache_absente(self):
        page = self.page(connecter(self.admin))
        self.assertIn('id="mise-a-jour-auto"', page)
        for mode in MA.MODES:
            self.assertIn(f'value="{mode}"', page)
        self.assertIn('name="delai"', page)
        self.assertIn("./install.sh --auto-update on", page)  # tâche pas posée : la commande à demander à l'IT
        self.assertIn('value="off" id="id_mode_2" checked', page)  # sans choix : éteint

    def test_enregistrer_le_choix(self):
        c = connecter(self.admin)
        rep = c.post(URL, {"action": "reglage_mise_a_jour_auto", "mode": "notify", "delai": "7"})
        self.assertEqual(rep.status_code, 302)
        self.assertTrue(rep["Location"].endswith("#mise-a-jour-auto"))
        self.assertEqual(MA.lire_choix(), {"mode": "notify", "delai": 7, "ecrit": True})
        lignes = set(Journal.objects.filter(action="reglage_mise_a_jour_auto").values_list("champ", "avant", "apres"))
        self.assertEqual(lignes, {("mode", "", "notify"), ("delai", "", "7")})
        page = self.page(c)
        self.assertIn('value="notify" id="id_mode_1" checked', page)
        with L.activer_interface("fr"):
            self.assertIn(libelle("admin.maj_auto.enregistre.notify"), texte(page))

    def test_valeurs_hors_liste_refusees(self):
        c = connecter(self.admin)
        for donnees in ({"mode": "on", "delai": "3"}, {"mode": "automatic", "delai": "2"},
                        {"mode": "automatic\nmode=off", "delai": "3"}, {"mode": "automatic"}):
            with self.subTest(donnees):
                rep = c.post(URL, {"action": "reglage_mise_a_jour_auto", **donnees})
                self.assertEqual(rep.status_code, 200)
                self.assertFalse((MA.dossier() / MA.CHOIX).exists())
        self.assertFalse(Journal.objects.filter(action="reglage_mise_a_jour_auto").exists())

    def test_administrateur_d_un_autre_espace_lecture_seule(self):
        MA.ecrire_choix("automatic", 3)
        c = connecter(self.admin_essai, "essai")
        page = self.page(c, "/espace/essai")
        self.assertIn('id="mise-a-jour-auto"', page)
        self.assertNotIn('name="mode"', page)
        with L.activer_interface("fr"):
            self.assertIn(libelle("admin.maj_auto.mode.automatic"), page)
        rep = c.post(f"/espace/essai{URL}", {"action": "reglage_mise_a_jour_auto", "mode": "off", "delai": "0"})
        self.assertEqual(rep.status_code, 403)
        self.assertEqual(MA.lire_choix()["mode"], "automatic")

    def test_gestionnaire_des_espaces_regle_depuis_un_autre_espace(self):
        Compte.objects.filter(pk=self.admin_essai.pk).update(gestionnaire=True)
        c = connecter(self.admin_essai, "essai")
        rep = c.post(f"/espace/essai{URL}", {"action": "reglage_mise_a_jour_auto", "mode": "automatic", "delai": "1"})
        self.assertEqual(rep.status_code, 302)
        self.assertEqual(MA.lire_choix()["delai"], 1)
        with E.activer("essai"):
            self.assertTrue(Journal.objects.filter(action="reglage_mise_a_jour_auto").exists())

    def test_roles_sans_droit_n_ecrivent_rien(self):
        for role, u in self.autres.items():
            c = connecter(u)
            self.assertEqual(c.get(URL).status_code, 403, role)
            rep = c.post(URL, {"action": "reglage_mise_a_jour_auto", "mode": "automatic", "delai": "0"})
            self.assertEqual(rep.status_code, 403, role)
        self.assertFalse(MA.dossier().exists())

    def test_hors_docker_pas_disponible(self):
        DOCKER.stop()
        with mock.patch.dict(os.environ, {"DANS_DOCKER": ""}):
            c = connecter(self.admin)
            page = self.page(c)
            with L.activer_interface("fr"):
                self.assertIn(libelle("admin.maj_auto.non_disponible"), texte(page))
            self.assertNotIn('name="mode"', page)
            rep = c.post(URL, {"action": "reglage_mise_a_jour_auto", "mode": "automatic", "delai": "0"}, follow=True)
            with L.activer_interface("fr"):
                self.assertIn(libelle("admin.maj_auto.indisponible"), texte(rep.content.decode()))
            self.assertFalse(MA.dossier().exists())
        DOCKER.start()

    def test_dernier_passage_montre_par_les_textes_de_l_outil(self):
        self.ecrire(resultat(state="rolled_back", reason="health", restored="yes", available="1.0.3"))
        page = self.page(connecter(self.admin))
        with L.activer_interface("fr"):
            for cle, valeurs in (("admin.maj_auto.etat.rolled_back", {"nouvelle": "1.0.3", "version": "1.0.2"}),
                                 ("admin.maj_auto.raison.health", {}), ("admin.maj_auto.restauree", {}),
                                 ("admin.maj_auto.tache.posee_heure", {"heure": "04:00"})):
                self.assertIn(libelle(cle, **valeurs), texte(page), cle)
        self.assertNotIn("./install.sh --auto-update on", page)

    def test_fichier_malveillant_ignore_rien_de_montre(self):
        self.ecrire(resultat(installed="1.0.2<script>alert(1)</script>"))
        page = self.page(connecter(self.admin))
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("alert(1)", page)
        with L.activer_interface("fr"):
            self.assertIn(libelle("admin.maj_auto.invalide"), texte(page))

    def test_tache_qui_ne_tourne_plus(self):
        vieux = (timezone.now() - datetime.timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.ecrire(resultat(checked=vieux))
        e = MA.etat_ecran()
        self.assertTrue(e["posee"])
        self.assertTrue(e["silence"])
        self.ecrire(resultat())
        self.assertFalse(MA.etat_ecran()["silence"])
