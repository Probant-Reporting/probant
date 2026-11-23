"""Clé de la prise IA : un fichier par espace, lisible par l'outil seul, jamais en base, jamais réaffichée, jamais au
journal, jamais dans une sauvegarde ; une restauration ne l'efface ni ne l'écrase. Aussi : la clé secrète
(``.secret_key``) n'entre plus dans la sauvegarde quand l'IT range les fichiers déposés dans le dossier des données."""
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from collecte.models import Journal
from espaces import contexte as E
from espaces.essais import EspacesTestCase
from parametres import ia as IA
from parametres import sauvegardes as SV
from parametres.aides_tests.ia import CLE, AvecIA
from referentiel.models import Utilisateur


class CleTests(AvecIA, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def test_fichier_lisible_par_l_outil_seul_et_hors_base(self):
        IA.enregistrer_cle(CLE)
        chemin = IA.chemin_cle()
        self.assertEqual(chemin.name, "principal.key")
        self.assertEqual(oct(os.stat(chemin).st_mode & 0o777), "0o600")
        self.assertEqual(IA._lire_cle(), CLE)
        self.assertEqual([p.name for p in chemin.parent.iterdir()], ["principal.key"])  # aucun fichier temporaire laissé
        from django.apps import apps

        for app in ("collecte", "referentiel", "parametres"):  # aucune table ne la contient
            for m in apps.get_app_config(app).get_models():
                champs = [f.attname for f in m._meta.concrete_fields]
                self.assertNotIn(CLE, repr(list(m.objects.values_list(*champs))), m.__name__)

    def test_cle_invalide_refusee(self):
        for mauvaise in ("", "court", "avec des espaces dedans 0123456789", "x" * 401, "é" * 30):
            with self.subTest(cle=mauvaise), self.assertRaises(ValueError):
                IA.enregistrer_cle(mauvaise)
        self.assertFalse(IA.cle_presente())

    def test_jamais_reaffichee_ni_au_journal(self):
        rep = self.client.post(reverse("parametres:ia"), {"ia_active": "on", "ia_fournisseur": "factice", "ia_modele": "factice-1",
                                                          "ia_appels_jour": 50, "ia_taille_max": 60000, "ia_delai": 60,
                                                          "api_key": CLE})
        self.assertEqual(rep.status_code, 302)
        self.assertTrue(IA.cle_presente())
        page = self.client.get(reverse("parametres:ia")).content.decode()
        self.assertNotIn(CLE, page)
        self.assertNotIn(CLE[-6:], page)  # pas même la fin de la clé
        self.assertIn('type="password"', page)
        self.assertIn("Une clé est enregistrée depuis le", page)
        textes = " ".join(f"{j.champ} {j.avant} {j.apres}" for j in Journal.objects.all())
        self.assertNotIn(CLE, textes)
        self.assertIn("clé enregistrée", textes)
        # retirée : le fichier disparaît, le journal le dit (sans valeur), plus rien ne part
        self.client.post(reverse("parametres:ia"), {"action": "retirer_cle"})
        self.assertFalse(IA.cle_presente())
        self.assertFalse(IA.disponible())
        self.assertTrue(Journal.objects.filter(action="reglage_ia", champ="cle", apres="clé retirée").exists())

    def test_cle_cachee_des_rapports_d_erreur(self):
        from django.views.debug import SafeExceptionReporterFilter

        from parametres import vues_ia

        requete = self.client.post(reverse("parametres:ia"), {"api_key": "z" * 30}).wsgi_request
        self.assertEqual(getattr(requete, "sensitive_post_parameters", None), ("api_key",))
        filtre = SafeExceptionReporterFilter()
        self.assertEqual(filtre.get_post_parameters(requete)["api_key"], filtre.cleansed_substitute)
        self.assertTrue(vues_ia.reglages)


class SauvegardeTests(AvecIA, TestCase):
    """L'IT a mis les fichiers déposés dans le dossier des données lui-même : ni la clé IA ni la clé secrète ne partent
    dans l'archive, et la restauration ne les touche pas."""

    def test_ni_sauvegardee_ni_touchee_par_la_restauration(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        reglages = override_settings(DOSSIER_DONNEES=tmp, MEDIA_ROOT=tmp, IA_CLES_DIR=tmp / "ai-keys",
                                     SAUVEGARDES_DIR=tmp / "backups", ESPACES_DOSSIER=tmp / "spaces-data")
        reglages.enable()
        self.addCleanup(reglages.disable)
        IA.enregistrer_cle(CLE)
        (tmp / ".secret_key").write_text("cle-secrete-de-l-installation")
        (tmp / "preuves").mkdir()
        (tmp / "preuves" / "p.pdf").write_bytes(b"%PDF preuve")
        a = SV.creer("essai", format_base="json")
        with zipfile.ZipFile(a.chemin) as z:
            noms = z.namelist()
            contenu = b"".join(z.read(n) for n in noms)
        self.assertIn("files/preuves/p.pdf", noms)
        self.assertEqual([n for n in noms if "ai-keys" in n or "secret" in n], [])
        self.assertNotIn(CLE.encode(), contenu)
        piege = tmp / "piege.zip"
        with zipfile.ZipFile(a.chemin) as z, zipfile.ZipFile(piege, "w") as w:
            for info in z.infolist():
                w.writestr(info, z.read(info))
            w.writestr("files/ai-keys/principal.key", "sk-cle-piegee-0123456789abcdef")
        with zipfile.ZipFile(piege) as z:
            SV._restaurer_fichiers(z)
        self.assertEqual(IA._lire_cle(), CLE)  # ni écrasée ni effacée
        self.assertEqual((tmp / ".secret_key").read_text(), "cle-secrete-de-l-installation")


class EspacesCleTests(AvecIA, EspacesTestCase):
    def test_une_cle_par_espace(self):
        IA.enregistrer_cle(CLE)
        with E.activer("essai"):
            self.assertFalse(IA.cle_presente())
            self.assertEqual(IA.chemin_cle().name, "essai.key")
            IA.enregistrer_cle("sk-autre-espace-0123456789abcdef")
            self.assertEqual(IA._lire_cle(), "sk-autre-espace-0123456789abcdef")
        self.assertEqual(IA._lire_cle(), CLE)
