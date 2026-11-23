"""Signature des archives.

Avant : n'importe quelle archive au bon format se restaurait depuis l'outil, y compris une archive téléchargée puis
modifiée (comptes, rôles, valeurs) et déposée de nouveau par un administrateur. Après : l'outil signe chaque archive
(HMAC, clé dérivée du secret de l'installation) ; la page Hébergement (liste et dépôt) refuse une archive sans signature
valide ; l'IT peut toujours la restaurer en ligne de commande avec « restore … --unsigned » (archives d'avant cette
version, d'un autre serveur)."""
import io
import json
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from referentiel.models import Utilisateur

from . import sauvegardes as SV
from .aides_tests.hebergement import MDP, DossiersTemporaires


def recopier(source, cible, changer=None, ajouter=None, sauter=(), doublon=None):
    """Copie de l'archive ``source`` dans ``cible`` : ``changer`` {nom: fonction(octets) -> octets}, ``ajouter``
    {nom: octets}, ``sauter`` noms omis, ``doublon`` (nom, octets) ajouté une seconde fois sous le même nom."""
    import warnings

    with zipfile.ZipFile(source) as src, zipfile.ZipFile(cible, "w") as z, warnings.catch_warnings():
        warnings.simplefilter("ignore")  # « Duplicate name »
        for n in src.namelist():
            if n in sauter:
                continue
            data = src.read(n)
            z.writestr(n, (changer or {}).get(n, lambda x: x)(data))
        for n, data in (ajouter or {}).items():
            z.writestr(n, data)
        if doublon:
            z.writestr(*doublon)
    return cible


def sans_signature(data):
    d = json.loads(data)
    d.pop(SV.SIGNATURE, None)
    return json.dumps(d).encode()


class Signature(DossiersTemporaires, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.admin = Utilisateur.objects.create_user("admin", email="admin@exemple.test", password=MDP,
                                                     role=Utilisateur.Role.ADMIN)
        self.a = SV.creer("essai", "json")

    def archive(self, nom, **options):
        return recopier(self.a.chemin, SV.dossier() / f"backup-20261101-0000{nom}.zip", **options)

    def test_archive_signee_par_l_outil(self):
        d = json.loads(zipfile.ZipFile(self.a.chemin).read("backup.json"))
        self.assertEqual(d[SV.SIGNATURE]["algorithme"], "hmac-sha256")
        self.assertTrue(SV.signature_valide(self.a.chemin))
        self.assertTrue(SV.signature_valide(SV.creer("essai", "sqlite" if SV.ESP.connexion().vendor == "sqlite" else "json").chemin))

    def test_toute_modification_casse_la_signature(self):
        def compte_admin(data):
            objets = json.loads(data)
            next(o for o in objets if o["model"] == "referentiel.utilisateur")["fields"]["email"] = "pirate@exemple.test"
            return json.dumps(objets).encode()

        def descriptif(cle, valeur):
            def f(data):
                d = json.loads(data)
                d[cle] = valeur
                return json.dumps(d).encode()
            return f

        cas = {
            "10": {"changer": {"database.json": compte_admin}},
            "11": {"ajouter": {"files/evidence/x.pdf": b"%PDF ajout"}},
            "12": {"changer": {"backup.json": descriptif("espace", "autre")}},
            "13": {"changer": {"backup.json": descriptif("migrations", [])}},
            "14": {"changer": {"backup.json": sans_signature}},  # archive d'avant cette version
            "15": {"doublon": ("database.json", b"[]")},
            "16": {"sauter": ("database.json",), "ajouter": {"database.sqlite3": b"x"}},
        }
        for nom, options in cas.items():
            with self.subTest(nom):
                self.assertFalse(SV.signature_valide(self.archive(nom, **options)))
        intacte = self.archive("17")
        self.assertTrue(SV.signature_valide(intacte))  # recopiée sans changement : toujours valide
        pas_un_zip = SV.dossier() / "backup-20261101-000018.zip"
        pas_un_zip.write_bytes(b"pas un zip")
        self.assertFalse(SV.signature_valide(pas_un_zip))

    def test_secret_de_l_installation(self):
        with override_settings(SECRET_KEY="un-autre-serveur-" + "x" * 40):
            self.assertFalse(SV.signature_valide(self.a.chemin))  # autre serveur
        from django.conf import settings

        ancien = settings.SECRET_KEY
        with override_settings(SECRET_KEY="nouvelle-cle-" + "y" * 40, SECRET_KEY_FALLBACKS=[ancien]):
            self.assertTrue(SV.signature_valide(self.a.chemin))  # clé changée, l'ancienne gardée en secours

    def test_page_hebergement_refuse_une_archive_non_signee(self):
        non_signee = self.archive("20", changer={"backup.json": sans_signature})
        self.client.force_login(self.admin)
        url = reverse("parametres:sauvegarde_restaurer", args=[non_signee.name])
        rep = self.client.get(url, follow=True)
        self.assertContains(rep, "pas été faite par cette installation")
        Utilisateur.objects.create_user("apres", email="apres@exemple.test", password=MDP)
        rep = self.client.post(url, {"compris": "on", "confirmation": "RESTAURER"}, follow=True)
        self.assertContains(rep, "pas été faite par cette installation")
        self.assertTrue(Utilisateur.objects.filter(username="apres").exists())  # rien n'a changé
        self.assertFalse(SV.historique_restaurations())

    def test_depot_d_une_archive_non_signee_ou_modifiee_refuse(self):
        self.client.force_login(self.admin)
        avant = {x.nom for x in SV.archives()}
        for nom in ("21", "22"):
            options = ({"changer": {"backup.json": sans_signature}} if nom == "21"
                       else {"ajouter": {"files/evidence/x.pdf": b"%PDF ajout"}})
            contenu = self.archive(nom, **options).read_bytes()
            rep = self.client.post(reverse("parametres:sauvegarde_deposer"),
                                   {"fichier": SimpleUploadedFile("s.zip", contenu)}, follow=True)
            self.assertContains(rep, "pas été faite par cette installation")
        self.assertFalse([x for x in SV.archives() if x.motif == "uploaded"])
        self.assertTrue({x.nom for x in SV.archives()} >= avant)
        # l'archive intacte, elle, entre toujours
        rep = self.client.post(reverse("parametres:sauvegarde_deposer"),
                               {"fichier": SimpleUploadedFile("s.zip", self.a.chemin.read_bytes())})
        deposee = next(x for x in SV.archives() if x.motif == "uploaded")
        self.assertRedirects(rep, reverse("parametres:sauvegarde_restaurer", args=[deposee.nom]),
                             fetch_redirect_response=False)

    def test_commande_unsigned_pour_l_it(self):
        non_signee = self.archive("30", changer={"backup.json": sans_signature})
        Utilisateur.objects.create_user("apres", email="apres@exemple.test", password=MDP)
        with self.assertRaises(CommandError) as e:
            call_command("restore", non_signee.name, "--yes", "--no-backup-before", stdout=io.StringIO())
        self.assertIn("--unsigned", str(e.exception))
        self.assertTrue(Utilisateur.objects.filter(username="apres").exists())  # rien n'a changé
        sortie = io.StringIO()
        call_command("restore", non_signee.name, "--yes", "--no-backup-before", "--unsigned", stdout=sortie)
        self.assertIn("restored because of --unsigned", sortie.getvalue())
        self.assertFalse(Utilisateur.objects.filter(username="apres").exists())
        # une archive signée se restaure sans l'option, comme avant
        call_command("restore", self.a.nom, "--yes", "--no-backup-before", stdout=io.StringIO())

    def test_reprise_d_une_restauration_non_signee_interrompue(self):
        """Restauration lancée par l'IT avec --unsigned puis interrompue (arrêt brutal) : le démarrage la termine."""
        non_signee = self.archive("40", changer={"backup.json": sans_signature})
        Utilisateur.objects.create_user("apres", email="apres@exemple.test", password=MDP)
        SV._ecrire_atomique(SV.dossier() / SV.EN_COURS, json.dumps({
            "archive": str(non_signee), "avant": "", "par": "", "origine": "commande", "autre_espace": False,
            "reconstruire": False, "date": "2026-11-17T10:00:00+01:00", "pid": 0}))
        self.assertEqual(SV.reprendre_restauration(), (non_signee.name, ""))
        self.assertFalse(Utilisateur.objects.filter(username="apres").exists())
        self.assertIsNone(SV.restauration_en_cours())
