"""Fichiers du lien entre l'outil et la tâche de mise à jour automatique de la machine (``mise_a_jour_auto.py``).

Le fichier ``result`` est écrit par la machine : pour l'outil, une entrée non sûre. Format strict, taille bornée, rien
d'exécuté, rien de montré tel quel ; un fichier hors format est ignoré en entier. Le fichier ``choice`` est écrit par
l'outil, relu sous verrou avant d'écrire, en 0600."""
import datetime
import os
import stat
import threading

from django.test import SimpleTestCase, override_settings

from parametres import mise_a_jour_auto as MA

VALIDE = ("format=1\ntask=systemd\ntime=04:00\nchecked=2026-11-25T03:12:00Z\nsince=2026-11-24T03:10:00Z\nstate=updated\n"
          "installed=1.0.2\ninstalled_digest=sha256:" + "b" * 64 + "\nprevious=1.0.1\n")


class AnalyseResultatTests(SimpleTestCase):
    def test_fichier_valide(self):
        r = MA.analyser_resultat(VALIDE.encode())
        self.assertEqual(r["state"], "updated")
        self.assertEqual(r["installed"], "1.0.2")
        self.assertEqual(r["checked"], datetime.datetime(2026, 11, 25, 3, 12, tzinfo=datetime.timezone.utc))

    def test_fichiers_malveillants_ignores_en_entier(self):
        cas = {
            "trop gros": VALIDE + "x" * 5000,
            "clé inconnue": VALIDE + "command=rm -rf /\n",
            "clé répétée": VALIDE + "state=failed\n",
            "état inconnu": VALIDE.replace("state=updated", "state=pwned"),
            "raison inconnue": VALIDE + "reason=<script>\n",
            "balise dans une version": VALIDE.replace("installed=1.0.2", "installed=1.0.2<b>"),
            "texte libre": VALIDE.replace("installed=1.0.2", "installed=Call 555-0100 now"),
            "version trop longue": VALIDE.replace("installed=1.0.2", "installed=1.0." + "9" * 20),
            "empreinte fausse": VALIDE.replace("sha256:" + "b" * 64, "sha256:zz"),
            "date impossible": VALIDE.replace("2026-11-25T03:12:00Z", "2026-13-45T03:12:00Z"),
            "caractère de contrôle": VALIDE.replace("task=systemd", "task=systemd\x1b[2J"),
            "retour chariot": VALIDE.replace("\n", "\r\n"),
            "octet nul": VALIDE + "\x00",
            "espaces": VALIDE.replace("state=updated", "state = updated"),
            "sans état": VALIDE.replace("state=updated\n", ""),
            "sans format": VALIDE.replace("format=1\n", ""),
            "autre format": VALIDE.replace("format=1", "format=2"),
            "unicode": VALIDE.replace("previous=1.0.1", "previous=１.０.１"),
        }
        for nom, texte in cas.items():
            with self.subTest(nom):
                with self.assertRaises(MA.ResultatInvalide):
                    MA.analyser_resultat(texte.encode())
        with self.assertRaises(MA.ResultatInvalide):
            MA.analyser_resultat(b"format=1\nstate=off\nchecked=2026-11-25T03:12:00Z\n\xff\xfe")

    def test_chaque_etat_et_raison_de_la_liste_a_son_texte(self):
        """Aucun texte de la machine n'est montré : chaque état et chaque raison passe par une clé de libellé."""
        from parametres.libelles import libelle

        for etat in MA.ETATS:
            self.assertNotEqual(libelle(f"admin.maj_auto.etat.{etat}"), f"admin.maj_auto.etat.{etat}")
        for raison in MA.RAISONS:
            self.assertNotEqual(libelle(f"admin.maj_auto.raison.{raison}"), f"admin.maj_auto.raison.{raison}")


class FichiersTests(SimpleTestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.reglage = override_settings(DOSSIER_DONNEES=self.tmp)
        self.reglage.enable()
        self.addCleanup(self.reglage.disable)

    def chemin(self, nom):
        return MA.dossier() / nom

    def test_lecture_bornee_lien_fifo_et_dossier_refuses(self):
        MA.dossier().mkdir(parents=True)
        cible = os.path.join(self.tmp, "ailleurs")
        with open(cible, "w") as f:
            f.write(VALIDE)
        os.symlink(cible, self.chemin(MA.RESULTAT))
        self.assertEqual(MA.lire_resultat(), (None, True), "jamais un lien symbolique")
        os.unlink(self.chemin(MA.RESULTAT))
        os.mkfifo(self.chemin(MA.RESULTAT))  # une file ne bloque pas la page
        fini = []
        t = threading.Thread(target=lambda: fini.append(MA.lire_resultat()))
        t.start()
        t.join(5)
        self.assertEqual(fini, [(None, True)])
        os.unlink(self.chemin(MA.RESULTAT))
        self.chemin(MA.RESULTAT).mkdir()
        self.assertEqual(MA.lire_resultat(), (None, True))
        self.chemin(MA.RESULTAT).rmdir()
        self.chemin(MA.RESULTAT).write_bytes(VALIDE.encode() + b"x" * 10_000_000)
        self.assertEqual(MA.lire_resultat(), (None, True))
        self.chemin(MA.RESULTAT).write_text(VALIDE)
        r, invalide = MA.lire_resultat()
        self.assertFalse(invalide)
        self.assertEqual(r["state"], "updated")

    def test_sans_fichier(self):
        self.assertEqual(MA.lire_resultat(), (None, False))
        self.assertEqual(MA.lire_choix(), {"mode": "off", "delai": 3, "ecrit": False})

    def test_choix_ecrit_en_0600_et_relu(self):
        self.assertEqual(MA.ecrire_choix("automatic", 3), [("mode", "", "automatic"), ("delai", "", 3)])
        mode = stat.S_IMODE(os.stat(self.chemin(MA.CHOIX)).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(MA.dossier()).st_mode), 0o700)
        self.assertEqual(MA.lire_choix(), {"mode": "automatic", "delai": 3, "ecrit": True})
        texte = self.chemin(MA.CHOIX).read_text()
        self.assertIn("mode=automatic\ndelay=3\n", texte)
        self.assertEqual(MA.ecrire_choix("notify", 3), [("mode", "automatic", "notify")])
        self.assertEqual(MA.ecrire_choix("notify", 3), [])
        self.assertEqual(MA.ecrire_choix("automatic", 0, seulement_si_absent=True), [], "un choix existe : gardé")
        self.assertEqual(MA.lire_choix()["mode"], "notify")
        self.assertEqual([p.name for p in MA.dossier().iterdir() if p.name.endswith(".tmp")], [])

    def test_valeurs_hors_liste_refusees(self):
        for mode, delai in (("on", 3), ("automatic", 2), ("automatic\nmode=off", 3), ("off", -1)):
            with self.subTest((mode, delai)):
                with self.assertRaises(ValueError):
                    MA.ecrire_choix(mode, delai)
        self.assertFalse(self.chemin(MA.CHOIX).exists())

    def test_choix_ecrits_en_meme_temps(self):
        """Deux enregistrements simultanés : le fichier est toujours entier (remplacé d'un bloc, sous verrou), et
        l'historique de chacun part de ce que l'autre avait écrit."""
        MA.ecrire_choix("off", 0)
        changements = []

        def ecrire(mode, delai):
            for _ in range(20):
                changements.append(MA.ecrire_choix(mode, delai))

        fils = [threading.Thread(target=ecrire, args=a) for a in (("automatic", 7), ("notify", 1))]
        for f in fils:
            f.start()
        for f in fils:
            f.join()
        self.assertIn(MA.lire_choix(), ({"mode": "automatic", "delai": 7, "ecrit": True}, {"mode": "notify", "delai": 1, "ecrit": True}))
        for c in changements:
            for champ, avant, apres in c:
                self.assertNotEqual(avant, apres)
