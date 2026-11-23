"""Hébergement (phase 8) : sauvegarde puis restauration sans perte (SQLite et JSON), rotation, refus, page Hébergement
(sauvegarde à télécharger, e-mail de test), page de santé, réglages de sécurité en production, version, pages d'erreur,
tailles de fichiers réglables. Le test « machine vierge » (image Docker) tourne avec TESTER_DOCKER=1."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.core import mail
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from collecte.models import Journal
from referentiel.models import Utilisateur

from . import sauvegardes as SV
from .models import Instance
from .aides_tests.hebergement import DossiersTemporaires, MDP, RACINE, environnement_propre, reglages
from collecte.outils_tests import html_de


class PageHebergement(DossiersTemporaires, TransactionTestCase):  # la copie SQLite se fait hors transaction
    def setUp(self):
        super().setUp()
        self.admin = Utilisateur.objects.create_user("admin", email="admin@exemple.test", password=MDP, role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def test_reservee_a_l_admin(self):
        c = Utilisateur.objects.create_user("c", email="c@exemple.test", password=MDP, role=Utilisateur.Role.CONTRIBUTEUR)
        self.client.force_login(c)
        self.assertEqual(self.client.get(reverse("parametres:hebergement")).status_code, 403)
        self.assertEqual(self.client.get(reverse("parametres:sauvegarde_telecharger", args=["sauvegarde-20261001-000000.zip"])).status_code, 403)

    def test_origine_des_archives_traduite(self):
        """Les motifs « before-update », « before-restore », « uploaded » (et leurs anciens noms français) s'affichent
        avec leur libellé, pas avec le code brut (constat de la relecture de la documentation)."""
        for motif in ("before-update", "avant-restauration"):
            SV.creer(motif)
        rep = self.client.get(reverse("parametres:hebergement"))
        self.assertContains(rep, "avant une mise à jour")
        self.assertNotContains(rep, "<td>before-update</td>")
        self.assertNotContains(rep, "<td>before-restore</td>")

    def test_sauvegarder_et_telecharger(self):
        rep = self.client.get(reverse("parametres:hebergement"))
        self.assertContains(rep, "Aucune sauvegarde")
        self.assertContains(rep, settings.VERSION)
        rep = self.client.post(reverse("parametres:hebergement"), {"action": "sauvegarder"})
        a = SV.archives()[0]
        self.assertRedirects(rep, f"{reverse('parametres:hebergement')}?telecharger={a.nom}", fetch_redirect_response=False)
        self.assertEqual(a.motif, "manuelle")
        rep = self.client.get(rep["Location"])
        self.assertContains(rep, "data-telecharger-auto")
        # Télécharger et Restaurer… dans une même cellule (l'un sous l'autre sur téléphone, sans défilement horizontal)
        self.assertContains(rep, '<span class="actions-sauvegarde">', count=1)
        rep = self.client.get(reverse("parametres:sauvegarde_telecharger", args=[a.nom]))
        self.assertEqual(rep["Content-Type"], "application/zip")
        self.assertIn("attachment", rep["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(b"".join(rep.streaming_content))) as z:
            self.assertTrue({"database.sqlite3", "database.json"} & set(z.namelist()))
        self.assertEqual(list(Journal.objects.filter(action__in=["sauvegarde", "telechargement_sauvegarde"]).values_list("action", flat=True)
                              .order_by("date")), ["sauvegarde", "telechargement_sauvegarde"])
        self.assertEqual(self.client.get(reverse("parametres:sauvegarde_telecharger", args=["sauvegarde-20200101-000000.zip"])).status_code, 404)

    def test_reglages_de_la_sauvegarde_automatique(self):
        rep = self.client.post(reverse("parametres:hebergement"), {"action": "reglages_sauvegarde", "sauvegarde_auto": "on",
                               "sauvegarde_frequence": "6h", "sauvegarde_heure": "03:15", "sauvegarde_conserver": "30"})
        self.assertEqual(rep.status_code, 302)
        i = Instance.courante()
        self.assertEqual((i.sauvegarde_auto, i.sauvegarde_frequence, i.sauvegarde_heure, i.sauvegarde_conserver), (True, "6h", "03:15", 30))
        self.assertTrue(Journal.objects.filter(action="reglage_sauvegarde", champ="sauvegarde_frequence").exists())
        rep = self.client.post(reverse("parametres:hebergement"), {"action": "reglages_sauvegarde", "sauvegarde_frequence": "jour",
                               "sauvegarde_heure": "25:00", "sauvegarde_conserver": "0"})
        self.assertContains(rep, "heure au format HH:MM, par exemple")
        self.assertContains(rep, "entre 1 et 365")
        rep = self.client.get(reverse("parametres:hebergement"))
        self.assertContains(rep, "Toutes les 6 heures")
        self.assertContains(rep, "Ce qu'elle ne contient pas")

    def test_restaurer_depuis_l_outil_avec_confirmation(self):
        Utilisateur.objects.create_user("avant", email="avant@exemple.test", password=MDP)
        a = SV.creer("manuelle")
        Utilisateur.objects.create_user("apres", email="apres@exemple.test", password=MDP)
        url = reverse("parametres:sauvegarde_restaurer", args=[a.nom])
        rep = self.client.get(url)
        self.assertContains(rep, "La sauvegarde remplace tout ce qui a été fait depuis")
        self.assertContains(rep, "La restauration vous déconnecte")
        self.assertContains(rep, "Comptes")
        rep = self.client.post(url, {"compris": "on", "confirmation": "oui"})  # mot de confirmation manquant : rien ne change
        self.assertContains(rep, "saisissez RESTAURER")
        self.assertTrue(Utilisateur.objects.filter(username="apres").exists())
        rep = self.client.post(url, {"compris": "on", "confirmation": "restaurer"})
        suite = reverse("parametres:hebergement") + f"?restauree={a.nom}"
        self.assertRedirects(rep, reverse("login") + "?" + urlencode({"next": suite}), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)  # toujours déconnecté après une restauration
        self.assertFalse(Utilisateur.objects.filter(username="apres").exists())
        self.assertTrue(Utilisateur.objects.filter(username="avant").exists())
        self.assertTrue([x for x in SV.archives() if x.motif == "before-restore"])
        self.assertTrue(Journal.objects.filter(action="restauration").exists())
        h = SV.historique_restaurations()
        self.assertEqual((len(h), h[0]["archive"], h[0]["origine"]), (1, a.nom, "outil"))
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("parametres:hebergement")), "Historique des restaurations (1)")

    def test_restauration_annoncee_sur_la_page_de_connexion(self):
        """Sauvegarde faite, puis nouvelle connexion (sa session n'est pas dans la sauvegarde, comme sous PostgreSQL ou
        avec une sauvegarde plus ancienne), puis restauration : la page de connexion dit « Restauration réussie », la date
        de l'état retrouvé et avec quel compte se reconnecter, dans la carte et relié au champ E-mail (lecteur d'écran) ;
        après la reconnexion, Hébergement affiche la confirmation détaillée."""
        a = SV.creer("manuelle")
        self.client.logout()
        self.assertTrue(self.client.login(username="admin", password=MDP))  # nouvelle session, absente de la sauvegarde
        rep = self.client.post(reverse("parametres:sauvegarde_restaurer", args=[a.nom]), {"compris": "on", "confirmation": "RESTAURER"},
                               follow=True)
        self.assertEqual(rep.redirect_chain[-1][0].split("?")[0], reverse("login"))
        self.assertContains(rep, "Restauration réussie.</strong> L&#x27;outil est revenu à l&#x27;état du ")
        self.assertContains(rep, "reconnectez-vous avec un compte administrateur de cette sauvegarde")
        self.assertNotContains(rep, f"({a.nom})")  # la date, pas le nom du fichier
        self.assertContains(rep, 'id="message-connexion"')
        self.assertContains(rep, 'aria-describedby="message-connexion"')
        self.assertEqual(rep.content.decode().count("Restauration réussie"), 1)  # rendu une seule fois (dans la carte)
        self.assertNotIn("_auth_user_id", self.client.session)
        suite = reverse("parametres:hebergement") + f"?restauree={a.nom}"
        self.assertContains(rep, f'name="next" value="{suite}"')
        rep = self.client.post(reverse("login"), {"username": "admin", "password": MDP, "next": suite}, follow=True)
        self.assertContains(rep, f"Sauvegarde {a.nom} restaurée")
        self.assertNotContains(rep, "Restauration réussie")  # le message n'est montré qu'une fois

    def test_deposer_une_sauvegarde(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        rep = self.client.post(reverse("parametres:sauvegarde_deposer"), {"fichier": SimpleUploadedFile("x.zip", b"pas un zip")}, follow=True)
        self.assertContains(rep, "n&#x27;est pas une sauvegarde")
        contenu = SV.creer("manuelle").chemin.read_bytes()
        rep = self.client.post(reverse("parametres:sauvegarde_deposer"), {"fichier": SimpleUploadedFile("s.zip", contenu)})
        deposee = next(x for x in SV.archives() if x.motif == "uploaded")
        self.assertRedirects(rep, reverse("parametres:sauvegarde_restaurer", args=[deposee.nom]), fetch_redirect_response=False)

    def test_email_de_test(self):
        rep = self.client.get(reverse("parametres:hebergement"))
        self.assertContains(rep, "pas encore configuré")
        rep = self.client.post(reverse("parametres:hebergement"), {"action": "tester_email", "destinataire": "it@exemple.test"}, follow=True)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["it@exemple.test"])
        self.assertIn("e-mail de test", mail.outbox[0].subject)
        with override_settings(EMAIL_HOST="smtp.exemple.test"):
            rep = self.client.post(reverse("parametres:hebergement"), {"action": "tester_email", "destinataire": "it@exemple.test"}, follow=True)
            self.assertContains(rep, "E-mail de test envoyé à it@exemple.test")
        self.assertEqual(Journal.objects.filter(action="test_email").count(), 2)

    def test_email_de_test_par_le_faux_serveur(self):
        """qa/fake_smtp.py reçoit pour de vrai, en SMTP, l'e-mail de test (outil de recette des relances)."""
        import importlib.util
        import threading

        spec = importlib.util.spec_from_file_location("faux_smtp", RACINE / "qa" / "fake_smtp.py")
        faux = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(faux)
        fichier = str(self.tmp / "emails.json")
        serveur = faux.FauxSMTP(("127.0.0.1", 0), fichier, silencieux=True)
        threading.Thread(target=serveur.serve_forever, daemon=True).start()
        self.addCleanup(serveur.server_close)
        self.addCleanup(serveur.shutdown)
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST="127.0.0.1",
                               EMAIL_PORT=serveur.server_address[1], EMAIL_USE_TLS=False, EMAIL_USE_SSL=False,
                               EMAIL_HOST_USER="", EMAIL_HOST_PASSWORD=""):
            rep = self.client.post(reverse("parametres:hebergement"), {"action": "tester_email", "destinataire": "it@exemple.test"}, follow=True)
        self.assertContains(rep, "E-mail de test envoyé à it@exemple.test")
        recus = json.loads(Path(fichier).read_text(encoding="utf-8"))
        self.assertEqual([r["destinataires"] for r in recus], [["it@exemple.test"]])
        self.assertIn("e-mail de test", recus[0]["sujet"])
        self.assertIn("peut envoyer des messages", recus[0]["texte"])


class Sante(TestCase):
    def test_base_vide_sans_assistant_ni_connexion(self):
        self.assertFalse(Utilisateur.objects.exists())
        rep = self.client.get(reverse("parametres:sante"))
        self.assertEqual(rep.status_code, 200)
        d = rep.json()
        self.assertEqual((d["etat"], d["base"], d["version"]), ("ok", "ok", settings.VERSION))
        self.assertIn("no-cache", rep["Cache-Control"])

    def test_stockage_non_modifiable(self):
        with override_settings(MEDIA_ROOT="/proc/inexistant/media"), self.assertLogs("django.request", "ERROR"):
            rep = self.client.get(reverse("parametres:sante"))
        self.assertEqual(rep.status_code, 503)
        self.assertEqual(rep.json()["stockage"], "not writable")


class Pages(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create_user("admin", email="admin@exemple.test", password=MDP, role=Utilisateur.Role.ADMIN)

    def test_version_affichee(self):
        self.assertContains(self.client.get(reverse("login")), f"version {settings.VERSION}")

    def test_connexion_sans_message(self):
        """Sans message à afficher, le champ E-mail n'est relié à rien (pas d'aria-describedby vers un bloc absent)."""
        rep = self.client.get(reverse("login"))
        self.assertNotRegex(rep.content.decode(), r"<(input|form)[^>]*aria-describedby")  # le script de l'outil peut en parler
        self.assertNotContains(rep, 'id="message-connexion"')

    def test_page_introuvable_en_francais(self):
        self.client.force_login(self.admin)
        rep = self.client.get("/page-qui-n-existe-pas/")
        self.assertEqual(rep.status_code, 404)
        self.assertContains(rep, "Page introuvable", status_code=404)

    def test_tailles_reglables(self):
        from collecte.fichiers import mo
        from collecte.models import valider_fichier
        from django.core.exceptions import ValidationError

        self.assertEqual((mo(5 * 1024 * 1024), mo(1536 * 1024)), ("5", "1,5"))
        with override_settings(PREUVE_TAILLE_MAX=2 * 1024 * 1024):
            with self.assertRaisesMessage(ValidationError, "dépasse 2 Mo"):
                valider_fichier(ContentFile(b"x" * (2 * 1024 * 1024 + 1), name="gros.pdf"))
            valider_fichier(ContentFile(b"%PDF-" + b"x" * 1024, name="petit.pdf"))

    def test_demarrage_depuis_une_ancienne_version(self):
        """Mise à jour d'une base d'avant l'outil générique (tables des paramètres absentes) : la sauvegarde automatique
        d'avant migration ne doit pas échouer (répétition de la mise à jour d'une installation existante)."""
        with tempfile.TemporaryDirectory() as tmp:
            env = environnement_propre()
            env.update(DOSSIER_DONNEES=tmp, DJANGO_SECRET_KEY="essai-" + "x" * 40)
            lancer = lambda *a: subprocess.run([sys.executable, "manage.py", *a], cwd=RACINE, env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(lancer("migrate", "--noinput").returncode, 0)
            self.assertEqual(lancer("migrate", "parametres", "zero", "--noinput").returncode, 0)  # comme une base de main
            r = lancer("demarrage")
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            self.assertIn("automatic backup before", r.stdout)
            self.assertTrue(list((Path(tmp) / "backups").glob("*-before-update.zip")))

    def test_demarrage(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DOSSIER_DONNEES=Path(tmp), MEDIA_ROOT=Path(tmp) / "media",
                                                                      SAUVEGARDES_DIR=Path(tmp) / "sauvegardes"):
            sortie = io.StringIO()
            call_command("demarrage", stdout=sortie)
            self.assertIn(f"version {settings.VERSION}", sortie.getvalue())
            self.assertTrue((Path(tmp) / "sauvegardes").is_dir())


class ReglagesProduction(TestCase):
    databases = {"default", "commun", "espace_essai"}  # makemigrations --check lit l'historique de chaque base

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_https(self):
        env = {"DOSSIER_DONNEES": self.tmp, "DJANGO_HTTPS": "1", "DOMAINE": "reporting.example.com"}
        d = reglages(env, "print(json.dumps([s.DEBUG, s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, s.SECURE_SSL_REDIRECT, "
                          "s.SECURE_HSTS_SECONDS, s.SECURE_HSTS_INCLUDE_SUBDOMAINS, s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS, "
                          "s.SECURE_PROXY_SSL_HEADER, s.X_FRAME_OPTIONS, s.SECURE_CONTENT_TYPE_NOSNIFF]))")
        self.assertEqual(d, [False, True, True, True, 31536000, True, ["reporting.example.com", "localhost", "127.0.0.1"],
                             ["https://reporting.example.com"], ["HTTP_X_FORWARDED_PROTO", "https"], "DENY", True])
        r = subprocess.run([sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"], cwd=RACINE,
                           env={**{k: v for k, v in os.environ.items() if not k.startswith("DJANGO_")}, **env},
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no issues", r.stdout)

    def test_http_sans_redirection(self):
        d = reglages({"DOSSIER_DONNEES": self.tmp}, "print(json.dumps([s.DEBUG, getattr(s, 'SECURE_SSL_REDIRECT', False), "
                     "s.SESSION_COOKIE_SECURE, s.ALLOWED_HOSTS, s.EMAIL_BACKEND]))")
        self.assertEqual(d, [False, False, False, ["localhost", "127.0.0.1"], "django.core.mail.backends.console.EmailBackend"])

    def test_cle_secrete_generee_une_fois(self):
        code = "print(json.dumps(s.SECRET_KEY))"
        c1 = reglages({"DOSSIER_DONNEES": self.tmp}, code)
        c2 = reglages({"DOSSIER_DONNEES": self.tmp}, code)
        self.assertEqual(c1, c2)
        self.assertGreaterEqual(len(c1), 50)
        self.assertEqual(oct(os.stat(Path(self.tmp) / ".secret_key").st_mode & 0o777), "0o600")
        self.assertEqual(reglages({"DOSSIER_DONNEES": self.tmp, "DJANGO_SECRET_KEY": "fournie-par-l-it"}, code), "fournie-par-l-it")

    def test_base_et_smtp_par_variables(self):
        env = {"DOSSIER_DONNEES": self.tmp, "DATABASE_URL": "postgres://probant:mot%40passe@db:5433/probant",
               "SMTP_HOTE": "smtp.example.com", "SMTP_PORT": "465", "SMTP_SECURITE": "ssl",
               "TAILLE_MAX_PREUVE_MO": "8", "TAILLE_MAX_IMPORT_MO": ""}  # vide : valeur par défaut
        d = reglages(env, "b = s.DATABASES['default']; print(json.dumps([b['ENGINE'], b['NAME'], b['USER'], b['PASSWORD'], "
                          "b['HOST'], b['PORT'], s.EMAIL_BACKEND, s.EMAIL_PORT, s.EMAIL_USE_SSL, s.EMAIL_USE_TLS, s.PREUVE_TAILLE_MAX, s.IMPORT_TAILLE_MAX]))")
        self.assertEqual(d, ["django.db.backends.postgresql", "probant", "probant", "mot@passe", "db", "5433",
                             "django.core.mail.backends.smtp.EmailBackend", 465, True, False, 8 * 1024 * 1024, 10 * 1024 * 1024])
        d = reglages({"DOSSIER_DONNEES": self.tmp}, "b = s.DATABASES['default']; print(json.dumps([b['ENGINE'], str(b['NAME'])]))")
        self.assertEqual(d, ["django.db.backends.sqlite3", str(Path(self.tmp) / "db.sqlite3")])

    def test_utilisateur_postgresql_par_defaut_probant(self):
        """Sans DATABASE_URL, les variables POSTGRES_* : l'utilisateur par défaut porte le nom du projet, comme
        l'utilisateur et la base du service « db » de docker-compose.yml et l'adresse donnée en exemple dans .env.example."""
        d = reglages({"DOSSIER_DONNEES": self.tmp, "POSTGRES_DB": "probant"},
                     "b = s.DATABASES['default']; print(json.dumps([b['NAME'], b['USER'], b['HOST']]))")
        self.assertEqual(d, ["probant", "probant", "db"])
        compose = (Path(settings.BASE_DIR) / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("POSTGRES_DB: probant\n", compose)
        self.assertIn("POSTGRES_USER: probant\n", compose)
        self.assertIn("pg_isready -U probant -d probant", compose)
        exemple = (Path(settings.BASE_DIR) / ".env.example").read_text(encoding="utf-8")
        self.assertIn("DATABASE_URL=postgres://probant:PASSWORD@db:5432/probant", exemple)
        self.assertIn("POSTGRES_USER (default probant)", exemple)

    def test_aucune_migration_en_attente(self):
        """La mise à jour applique les migrations au démarrage : un changement de modèle sans sa migration ne serait
        jamais appliqué chez les installations existantes."""
        sortie = io.StringIO()
        try:
            call_command("makemigrations", "--check", "--dry-run", stdout=sortie, stderr=sortie)
        except SystemExit:
            self.fail("Migration manquante (python3 manage.py makemigrations) :\n" + sortie.getvalue())
        self.assertIn("No changes detected", sortie.getvalue())

    def test_hebergeur_cle_en_main(self):
        """Clever Cloud : dossier des données relatif au projet (dossier persistant monté), base de l'add-on PostgreSQL."""
        d = reglages({"DOSSIER_DONNEES": "data", "DJANGO_SECRET_KEY": "fournie", "POSTGRESQL_ADDON_URI": "postgresql://u:p@pg.exemple:5432/b"},
                     "print(json.dumps([str(s.DOSSIER_DONNEES), str(s.MEDIA_ROOT), s.DATABASES['default']['HOST']]))")
        self.assertEqual(d, [str(RACINE / "data"), str(RACINE / "data" / "files"), "pg.exemple"])


@unittest.skipUnless(os.environ.get("TESTER_DOCKER") == "1", "test Docker : TESTER_DOCKER=1 python manage.py test parametres.test_hebergement")
class InstallationMachineVierge(TestCase):
    def test_installer_en_une_commande(self):
        r = subprocess.run(["bash", str(RACINE / "docker" / "test_installation.sh")], capture_output=True, text=True, timeout=1800)
        self.assertEqual(r.returncode, 0, r.stdout[-4000:] + r.stderr[-2000:])
        self.assertIn("PASSED", r.stdout)


class HebergementTests(DossiersTemporaires, TransactionTestCase):
    URL = reverse("parametres:hebergement")

    def setUp(self):
        super().setUp()
        self.admin = Utilisateur.objects.create_user("admin", email="admin@exemple.test", password=MDP, role=Utilisateur.Role.ADMIN,
                                                     langue="fr")
        self.client.force_login(self.admin)

    def test_une_colonne_et_volet_it_dans_le_flux(self):
        html = html_de(self.client, self.URL)
        self.assertNotIn("colonne-apercu", html)  # plus de colonne collée sur le côté
        ordre = [html.index(f'id="{i}"') for i in ("titre-etat", "sauvegarde-automatique", "sauvegarder-maintenant",
                                                    "sauvegardes-disponibles", "emails", "controle-donnees", "reglage-corbeille", "pour-it")]
        self.assertEqual(ordre, sorted(ordre))
        self.assertIn('<details class="bloc volet-it" id="pour-it">', html)
        # rien de retiré : réglages, sauvegarde, dépôt d'un .zip, historique, test d'e-mail, contrôle, commandes de l'IT
        for trace in ('value="reglages_sauvegarde"', 'value="sauvegarder"', 'name="fichier"', "Historique des restaurations (0)",
                      'value="tester_email"', 'value="controler"', 'value="reglage_corbeille"', "manage.py restore", "SMTP_HOST",
                      "/sante/", "check_data", "Ce qu'elle ne contient pas"):
            self.assertIn(trace, html)

    def test_etat_une_ligne_par_point_a_traiter(self):
        rep = self.client.get(self.URL)
        self.assertEqual(rep.status_code, 200)
        bilan = rep.context["bilan"]
        self.assertEqual([p["ancre"] for p in bilan["points"]], ["sauvegarder-maintenant", "emails"])
        html = rep.content.decode()
        self.assertEqual(html.count('<li class="encart encart-avertissement compact">'), 2)
        self.assertIn('Aucune sauvegarde pour l&#x27;instant.</strong> <a href="#sauvegarder-maintenant">Créer la première</a>', html)
        self.assertNotIn("Tout va bien.", html)
        self.assertNotIn('class="alerte"', html)  # plus d'encart jaune sans icône
        self.assertIn('<div class="encart encart-avertissement" role="status">', html)  # e-mails non configurés : orange, avec icône

    @override_settings(EMAIL_HOST="smtp.exemple.test")
    def test_tout_va_bien(self):
        self.client.post(self.URL, {"action": "sauvegarder"})
        self.client.post(self.URL, {"action": "controler"})
        mail.outbox.clear()
        rep = self.client.get(self.URL)
        self.assertEqual(rep.context["bilan"]["points"], [])
        self.assertEqual(len(rep.context["bilan"]["ok"]), 4)
        self.assertContains(rep, "<strong>Tout va bien.</strong> Dernière sauvegarde le ")
        self.assertContains(rep, "E-mails configurés (smtp.exemple.test).")
        self.assertNotContains(rep, '<li class="encart encart-avertissement')
        self.assertNotContains(rep, '<div class="encart encart-avertissement"')

    def test_sauvegarde_automatique_desactivee(self):
        Instance.objects.filter(pk=Instance.courante().pk).update(sauvegarde_auto=False)
        rep = self.client.get(self.URL)
        self.assertIn("sauvegarde-automatique", [p["ancre"] for p in rep.context["bilan"]["points"]])
        self.assertContains(rep, "La sauvegarde automatique est désactivée.")
