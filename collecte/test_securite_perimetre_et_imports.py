"""Sécurité : rapport des rejets limité au périmètre, imports bornés, cellules Excel neutralisées,
redirections locales, preuves vérifiées, noms de comptes échappés."""
import io
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from . import exports as E
from . import fichiers as X
from . import imports as I
from . import saisie as S
from .models import Reponse
from .aides_tests.echanges import Base
from .aides_tests.aller_retour import Base as BaseEchanges

D = Decimal


def csv_(lignes, nom="valeurs.csv"):
    return SimpleUploadedFile(nom, ("\n".join(";".join(map(str, l)) for l in lignes) + "\n").encode())


class RapportRejetsPerimetreTests(Base):
    """S1 : une ligne rejetée hors du périmètre ne montre ni la valeur N-1 ni le statut de la case."""

    def setUp(self):
        super().setUp()
        Reponse.objects.create(periode=self.c0.periode, kpi=self.eff, organisation=self.e2, valeur=D(2648), statut="valide",
                               origine="import")

    def test_hors_perimetre_sans_n1_ni_statut(self):
        a = I.analyser(self.contrib, csv_([["ID KPI", "Organisation", "Exercice", "Valeur"], ["EFF", "E2", 2026, 1]]))
        self.assertEqual([l.action for l in a.lignes], ["rejet"])
        self.assertIn("périmètre", a.lignes[0].motif)
        (d,) = I.lignes_rejetees(a, self.contrib)
        self.assertEqual((d["n1"], d["statut"]), ("", ""))
        # l'admin, lui, voit la case : la comparaison reste utile
        self.assertEqual(I.lignes_rejetees(a, self.admin)[0]["n1"], "2648")

    def test_dans_le_perimetre_n1_garde(self):
        a = I.analyser(self.contrib, csv_([["ID KPI", "Organisation", "Exercice", "Valeur"], ["EFF", "E1", 2026, 7],
                                           ["EFF", "E1", 2026, 8]]))
        (d,) = I.lignes_rejetees(a, self.contrib)  # doublon de sa propre case
        self.assertEqual(d["n1"], "100")
        self.assertTrue(d["statut"])

    def test_rapport_telecharge_par_le_contributeur(self):
        self.client.force_login(self.contrib)
        self.client.post(reverse("collecte:echanges_importer"),
                         {"action": "verifier", "fichier": csv_([["ID KPI", "Organisation", "Exercice", "Valeur"], ["EFF", "E2", 2026, 1]])})
        rep = self.client.get(reverse("collecte:echanges_rejets") + "?format=csv")
        self.assertEqual(rep.status_code, 200)
        self.assertNotIn("2648", rep.content.decode("utf-8-sig"))
        self.client.post(reverse("collecte:echanges_importer"), {"action": "annuler"})


class ImportBorneTests(Base):
    """S2 : un import de contributeur est borné (nombre de lignes, rejets gardés) ; l'admin n'est pas limité."""

    def test_trop_de_lignes(self):
        lignes = [["ID KPI", "Organisation", "Exercice", "Valeur"]] + [["EFF", "E1", 2026, i] for i in range(6)]
        with mock.patch.object(I, "LIGNES_MAX", 5):
            a = I.analyser(self.contrib, csv_(lignes))
            self.assertIn("Ce fichier a plus de 5 lignes, le maximum pour un import", a.erreur)
            self.assertEqual(a.lignes, [])
            self.assertFalse(I.analyser(self.admin, csv_(lignes)).erreur)
            self.assertFalse(I.analyser(self.contrib, csv_(lignes[:6])).erreur)

    def test_rejets_gardes_bornes(self):
        lignes = [["ID KPI", "Organisation", "Exercice", "Valeur"]] + [["EFF", "E2", 2026, i] for i in range(8)]
        with mock.patch.object(I, "REJETS_GARDES", 3):
            self.assertEqual(len(I.lignes_rejetees(I.analyser(self.contrib, csv_(lignes)), self.contrib)), 3)
            a = I.analyser(self.admin, csv_(lignes))  # admin : doublons rejetés, tous gardés
            self.assertEqual(len(I.lignes_rejetees(a, self.admin)), 7)

    def test_lignes_repetees_decrites_une_fois(self):
        lignes = [["ID KPI", "Organisation", "Exercice", "Valeur"]] + [["EFF", "E1", 2026, 1]] * 40
        a = I.analyser(self.contrib, csv_(lignes))
        a3 = I.analyser(self.contrib, csv_(lignes[:3]))
        with CaptureQueriesContext(connection) as peu:
            I.lignes_rejetees(a3, self.contrib)
        with CaptureQueriesContext(connection) as beaucoup:
            r = I.lignes_rejetees(a, self.contrib)
        self.assertEqual(len(r), 39)
        self.assertEqual(r[-1]["n1"], "100")
        self.assertEqual(len(beaucoup), len(peu))  # ni un plan ni une lecture par ligne répétée


class FormulesNeutraliseesTests(Base):
    """S3 : un texte saisi qui commence par = + - @ reste du texte dans tous les classeurs exportés."""

    def cellules_formule(self, wb):
        return [(ws.title, c.coordinate, c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row
                if c.data_type == "f"]

    def test_commentaire_et_noms_dans_les_exports(self):
        S.enregistrer(self.contrib, self.c, self.eff, self.e1, "110", False, "=1+1")
        self.e2.nom = "=E2"
        self.e2.save()
        self.eff.libelle = "=Effectif"
        self.eff.save()
        for presentation in ("revue", "tableau", "base"):
            p = E.Parametres.depuis({"presentation": presentation, "exercices": ["courant"], "n1": True,
                                     "contenus": ["valide", "brouillon", "a_saisir"]})
            wb = load_workbook(io.BytesIO(E.exporter(self.admin, p).content))
            self.assertEqual(self.cellules_formule(wb), [], presentation)
            textes = {c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row if isinstance(c.value, str)}
            if presentation == "revue":
                self.assertIn("=1+1", textes)

    def test_autres_classeurs(self):
        from . import configuration as C

        self.e2.nom = "=E2"
        self.e2.save()
        self.eff.libelle = "=Effectif"
        self.eff.save()
        classeurs = {"configuration": load_workbook(io.BytesIO(C.exporter().content)),
                     "modele": load_workbook(io.BytesIO(I.modele(self.admin, self.c, I.lignes_modele(self.admin, self.c)).content))}
        for nom, wb in classeurs.items():
            pieges = [x for x in self.cellules_formule(wb) if str(x[2]).startswith(("=E2", "=Effectif"))]
            self.assertEqual(pieges, [], nom)

    def test_ecrire_cellule(self):
        wb = Workbook()
        ws = wb.active
        self.assertEqual(X.ecrire_cellule(ws, 1, 1, "=HYPERLINK(\"x\")").data_type, "s")
        self.assertEqual(X.ecrire_cellule(ws, 1, 2, "-3 %").data_type, "s")
        self.assertEqual(X.ecrire_cellule(ws, 1, 3, 12).data_type, "n")
        self.assertEqual(X.ecrire_cellule(ws, 1, 4, "Texte").value, "Texte")


class RedirectionLocaleTests(Base):
    """S6 : après le choix de campagne, retour sur une page de l'outil seulement."""

    def test_suivant_ne_quitte_pas_l_outil(self):
        self.client.force_login(self.admin)
        url = reverse("collecte:choisir_campagne", args=[self.c.pk])
        for piege in ("http://testserver//example.org/connexion/", "//example.org/", "http://example.org/",
                      "http://testserver/\\example.org/", "/\\example.org/", "http://testserver///example.org"):
            rep = self.client.get(url, {"suivant": piege})
            self.assertEqual(rep.status_code, 302, rep.content[:300])
            lieu = rep["Location"]
            self.assertTrue(lieu.startswith("/") and not lieu.startswith(("//", "/\\")), (piege, lieu))
        lieu = self.client.get(url, {"suivant": "http://testserver/saisie/?campagne=3&vue=kpi"})["Location"]
        self.assertEqual(lieu, "/saisie/?vue=kpi")


class NomsComptesEchappesTests(Base):
    """S8 : un nom de compte ne ferme pas la balise des comptes du sélecteur de SPOC."""

    def test_nom_piege(self):
        import json
        import re

        self.autre.first_name = "</script><p id=marqueur>x</p>"
        self.autre.save()
        self.client.force_login(self.admin)
        for url in (reverse("collecte:saisie"), reverse("collecte:admin_attributions")):
            html = self.client.get(url).content.decode()
            self.assertFalse("<p id=marqueur>" in html, url)
            bloc = re.search(r'<script id="comptes" type="application/json">(.*?)</script>', html, re.S)
            self.assertIsNotNone(bloc, url)
            noms = [c["nom"] for c in json.loads(bloc.group(1))]
            self.assertTrue(any(n.startswith("</script><p id=marqueur>") for n in noms), noms)


class PreuvesContenuTests(Base):
    """S7 : une preuve doit être ce que son extension annonce (signature du fichier)."""

    def test_signatures(self):
        from django.core.exceptions import ValidationError
        from django.core.files.base import ContentFile

        from .models import valider_fichier

        for nom, contenu in (("note.pdf", b"du texte brut"), ("photo.png", b"GIF89a..."), ("photo.jpg", b"\x89PNG\r\n\x1a\n"),
                             ("vide.pdf", b"")):
            with self.assertRaisesMessage(ValidationError, "ne correspond pas", msg_prefix=nom):
                valider_fichier(ContentFile(contenu, name=nom))
        for nom, contenu in (("a.pdf", b"%PDF-1.7\n"), ("b.PDF", b"\xef\xbb\xbf%PDF-1.4"), ("c.png", b"\x89PNG\r\n\x1a\n...."),
                             ("d.jpg", b"\xff\xd8\xff\xe0..."), ("e.JPEG", b"\xff\xd8\xff\xdb")):
            f = ContentFile(contenu, name=nom)
            valider_fichier(f)
            self.assertEqual(f.tell(), 0)  # relu depuis le début à l'enregistrement

    def test_depot_refuse_par_la_page(self):
        self.client.force_login(self.contrib)
        from .models import Preuve

        url = reverse("collecte:cellule", args=[self.c.pk, "EFF", self.e1.pk])
        self.client.post(url, {"action": "preuve", "fichier": SimpleUploadedFile("note.pdf", b"texte", content_type="application/pdf")})
        self.assertFalse(Preuve.objects.exists())


class SantePubliqueTests(Base):
    """S10 : /sante/ ne donne que l'état à un visiteur ; le détail reste pour l'admin et le contrôle local (Docker)."""

    def test_detail_selon_le_visiteur(self):
        from django.conf import settings

        url = reverse("parametres:sante")
        anonyme = self.client.get(url, REMOTE_ADDR="203.0.113.7")
        self.assertEqual((anonyme.status_code, anonyme.json()), (200, {"etat": "ok"}))
        proxy = self.client.get(url, REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.7")  # proxy sur la machine
        self.assertEqual(proxy.json(), {"etat": "ok"})
        local = self.client.get(url, REMOTE_ADDR="127.0.0.1").json()  # contrôle de santé de Docker, install.sh
        self.assertEqual((local["version"], local["base"], local["stockage"]), (settings.VERSION, "ok", "ok"))
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(url, REMOTE_ADDR="203.0.113.7").json(), {"etat": "ok"})
        self.client.force_login(self.admin)
        self.assertIn("derniere_sauvegarde", self.client.get(url, REMOTE_ADDR="203.0.113.7").json())


class ModeExpertLectureTests(Base):
    """S5 : le mode expert (admin de Django) montre les tables sans permettre de les modifier (aucune trace dans le
    journal de l'outil, campagne clôturée figée) ; désormais, toutes les tables."""

    def test_reponse_en_lecture_seule(self):
        self.admin.is_staff = self.admin.is_superuser = True
        self.admin.save()
        self.client.force_login(self.admin)
        r = Reponse.objects.get(periode=self.c0.periode, kpi=self.eff, organisation=self.e1)
        url = reverse("admin:collecte_reponse_change", args=[r.pk])
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)  # consultable
        self.assertNotContains(page, 'name="valeur"')
        self.client.post(url, {"periode": r.periode_id, "kpi": r.kpi_id, "organisation": r.organisation_id, "valeur": "999999",
                               "statut": "valide", "origine": "import", "commentaire": "", "texte": "",
                               "preuves-TOTAL_FORMS": "0", "preuves-INITIAL_FORMS": "0"})
        r.refresh_from_db()
        self.assertEqual(r.valeur, D(100))
        self.assertEqual(self.client.get(reverse("admin:collecte_reponse_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:collecte_reponse_delete", args=[r.pk])).status_code, 403)

    def test_tout_le_mode_expert_en_lecture_seule(self):
        """Plus aucune table modifiable par le mode expert (KPI, organisations, comptes,
        attributions, campagnes…), ni action en masse ; les groupes de Django, inutilisés, n'y figurent plus."""
        from django.contrib import admin
        from django.contrib.auth.models import Group

        self.admin.is_staff = self.admin.is_superuser = True
        self.admin.save()
        self.client.force_login(self.admin)
        self.assertFalse(admin.site.is_registered(Group))
        self.assertGreaterEqual(len(admin.site._registry), 11)
        for modele, modele_admin in admin.site._registry.items():
            nom = f"admin:{modele._meta.app_label}_{modele._meta.model_name}"
            with self.subTest(modele=modele.__name__):
                liste = self.client.get(reverse(f"{nom}_changelist"))
                self.assertEqual(liste.status_code, 200)
                self.assertNotContains(liste, 'name="action"')  # ni suppression ni action en masse
                self.assertNotContains(liste, 'name="_save"')  # pas de liste modifiable
                self.assertEqual(self.client.get(reverse(f"{nom}_add")).status_code, 403)
                objet = modele._default_manager.first()
                if objet is None:
                    continue
                fiche = self.client.get(reverse(f"{nom}_change", args=[objet.pk]))
                self.assertEqual(fiche.status_code, 200)  # consultable
                self.assertNotContains(fiche, 'name="_save"')
                self.assertEqual(self.client.post(reverse(f"{nom}_change", args=[objet.pk]), {}).status_code, 403)
                self.assertEqual(self.client.get(reverse(f"{nom}_delete", args=[objet.pk])).status_code, 403)
        mdp = reverse("admin:auth_user_password_change", args=[self.contrib.pk])  # nom fixé par UserAdmin
        self.assertEqual(self.client.post(mdp, {"password1": "Nouveau-mot-2026!", "password2": "Nouveau-mot-2026!"}).status_code, 403)


class ConnexionLimiteeTests(Base):
    """S4 : après 5 échecs pour un même identifiant depuis une même adresse, connexion refusée 15 minutes (message
    neutre, événement au journal du serveur) ; une autre adresse n'est pas bloquée ; la réussite remet à zéro."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache, caches

        cache.clear()
        caches["connexion"].clear()  # compteur des essais de connexion (cache dédié)
        self.contrib.set_password("bon-mot-de-passe-2026")
        self.contrib.save()
        self.url = reverse("login")

    def essai(self, mdp, ip="203.0.113.7", identifiant="contrib@exemple.test", **entetes):
        return self.client.post(self.url, {"username": identifiant, "password": mdp}, REMOTE_ADDR=ip, **entetes)

    def test_blocage_apres_cinq_echecs(self):
        for _ in range(4):
            self.assertContains(self.essai("faux"), "E-mail ou mot de passe incorrect")
        self.assertEqual(self.essai("bon-mot-de-passe-2026").status_code, 302)  # réussite : compteur remis à zéro
        self.client.logout()
        with self.assertLogs("referentiel.connexion", "WARNING") as journal:
            for _ in range(5):
                self.essai("faux")
        self.assertIn("contrib@exemple.test", journal.output[0])
        bloque = self.essai("bon-mot-de-passe-2026")
        self.assertEqual(bloque.status_code, 200)
        self.assertContains(bloque, "Trop d'essais de connexion")
        self.assertEqual(self.essai("bon-mot-de-passe-2026", ip="198.51.100.4").status_code, 302)  # autre adresse
        self.client.logout()
        # identifiant inconnu : même message (ne dit pas si le compte existe)
        for _ in range(6):
            r = self.essai("faux", identifiant="personne@exemple.test")
        self.assertContains(r, "Trop d'essais de connexion")

    @override_settings(HTTPS=True)  # l'en-tête n'est lu que derrière un proxy HTTPS (DJANGO_HTTPS=1)
    def test_derriere_un_proxy(self):
        """Derrière Caddy, l'adresse du visiteur est la dernière de X-Forwarded-For (ajoutée par le proxy)."""
        for _ in range(5):
            self.essai("faux", ip="172.18.0.3", HTTP_X_FORWARDED_FOR="203.0.113.7")
        self.assertContains(self.essai("bon-mot-de-passe-2026", ip="172.18.0.3", HTTP_X_FORWARDED_FOR="203.0.113.7"),
                            "Trop d'essais")
        r = self.essai("bon-mot-de-passe-2026", ip="172.18.0.3", HTTP_X_FORWARDED_FOR="203.0.113.7, 198.51.100.4")
        self.assertEqual(r.status_code, 302)  # autre visiteur, même proxy ; l'en-tête forgé en tête ne compte pas

    def test_admin_django_aussi(self):
        self.contrib.is_staff = True
        self.contrib.save()
        for _ in range(5):
            self.client.post(reverse("admin:login"), {"username": "contrib", "password": "faux"}, REMOTE_ADDR="203.0.113.7")
        r = self.client.post(reverse("admin:login"), {"username": "contrib", "password": "bon-mot-de-passe-2026"},
                             REMOTE_ADDR="203.0.113.7")
        self.assertEqual(r.status_code, 200)  # refusé

    def test_mots_de_passe_trop_simples(self):
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            validate_password("20262026202620", self.contrib)
        with self.assertRaises(ValidationError):
            validate_password("contrib@exemple", self.contrib)
        validate_password("Lune-Orage-47-Sable", self.contrib)


class PagesSuiviSansCacheTests(BaseEchanges):
    """P8 : Saisie, Pour moi et Tableau de bord ne sont pas gardées en cache (retour arrière : statuts à jour)."""

    def test_en_tetes(self):
        from django.urls import reverse

        self.client.force_login(self.contrib)
        for nom in ("saisie", "pour_moi", "tableau_de_bord"):
            rep = self.client.get(reverse(f"collecte:{nom}"))
            self.assertEqual(rep.status_code, 200, nom)
            self.assertIn("no-store", rep.get("Cache-Control", ""), nom)
            self.assertIn("private", rep.get("Cache-Control", ""), nom)
