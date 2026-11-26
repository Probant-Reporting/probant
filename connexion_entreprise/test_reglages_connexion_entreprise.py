"""Paramètres › Connexion d'entreprise : réservé aux gestionnaires des espaces (dans chaque espace) ; secret chiffré,
jamais réaffiché, jamais au journal, dans une sauvegarde d'espace, l'archive du registre ni l'export de configuration ;
« Vérifier le fournisseur » dit ce qui manque ; allumer exige un réglage complet et un fournisseur qui répond ; adresse
de retour affichée ; adresse du fournisseur en https seulement hors essais."""
import io
import zipfile

from django.test import Client, override_settings
from django.urls import reverse
from django.utils.html import escape

from collecte.models import Journal
from espaces import contexte as E
from espaces.aides_tests import creer
from parametres import sauvegardes as SV
from parametres.libelles import libelle

from . import regles
from .aides_tests import BaseEntreprise
from .aides_tests.faux_fournisseur import CLIENT_ID, SECRET
from .models import LienEntreprise, ReglageEntreprise
from .secret import dechiffrer

URL = "/administration/parametres/connexion-entreprise/"


class ReglagesTests(BaseEntreprise):
    def client_de(self, u, espace="principal"):
        c = Client()
        c.force_login(u)
        return c

    def envoyer(self, c=None, **valeurs):
        c = c or self.client_de(self.gestionnaire)
        donnees = {"action": "enregistrer", "actif": "on", "emetteur": self.faux.emetteur, "client_id": CLIENT_ID,
                   "secret": SECRET, **valeurs}
        return c.post(URL, {k: v for k, v in donnees.items() if v is not None})

    def test_reserve_aux_gestionnaires_dans_chaque_espace(self):
        lecteur = creer("lecteur@exemple.example", "lecteur")
        auditeur = creer("auditeur@exemple.example", "auditeur")
        validateur = creer("valid@exemple.example", "validateur")
        for u in (self.contrib, self.admin, lecteur, auditeur, validateur):
            c = self.client_de(u)
            self.assertEqual(c.get(URL).status_code, 403, u.email)
            self.assertEqual(self.envoyer(c).status_code, 403, u.email)
            self.assertNotContains(c.get(reverse("parametres:identite") if u == self.admin else "/mon-compte/"),
                                   URL)  # onglet absent
        self.assertFalse(ReglageEntreprise.objects.exists())
        self.assertEqual(Client().get(URL).status_code, 302)
        c = self.client_de(self.gestionnaire)
        self.assertEqual(c.get(URL).status_code, 200)
        self.assertContains(c.get(reverse("parametres:identite")), f'href="{URL}"')
        # dans un autre espace : même réglage (de l'installation), même règle
        creer("gestion@exemple.example", "admin", "essai")
        self.assertEqual(c.get("/espace/essai" + URL).status_code, 200)
        self.assertEqual(self.client_de(self.admin).get("/espace/essai" + URL).status_code, 403)

    def test_allumer_puis_secret_jamais_reaffiche_ni_ecrit_en_clair(self):
        with self.assertLogs("connexion_entreprise", "WARNING"):
            r = self.envoyer()
        self.assertEqual(r.status_code, 302)
        self.assertTrue(regles.active())
        rg = ReglageEntreprise.objects.get()
        self.assertNotIn(SECRET, rg.secret_chiffre)
        self.assertEqual(dechiffrer(rg.secret_chiffre), SECRET)
        page = self.client_de(self.gestionnaire).get(URL)
        self.assertNotContains(page, SECRET)
        self.assertContains(page, 'name="secret" value=""')
        self.assertContains(page, "http://testserver/connexion/entreprise/retour/")  # adresse de retour à recopier
        textes = " ".join(" ".join(map(str, x)) for x in Journal.objects.values_list("champ", "avant", "apres"))
        self.assertNotIn(SECRET, textes)
        self.assertIn("enregistré", textes)
        self.assertTrue(Journal.objects.filter(action="reglage_connexion_entreprise", champ="actif").exists())
        # garder le secret : champ vide ; le remplacer : noté « remplacé »
        self.envoyer(secret="")
        self.assertEqual(dechiffrer(ReglageEntreprise.objects.get().secret_chiffre), SECRET)
        self.envoyer(secret="un-autre-secret-2026")
        self.assertEqual(dechiffrer(ReglageEntreprise.objects.get().secret_chiffre), "un-autre-secret-2026")
        self.assertTrue(Journal.objects.filter(champ="secret", apres="remplacé").exists())

    def test_secret_cache_des_rapports_d_erreur(self):
        from django.views.debug import SafeExceptionReporterFilter

        requete = self.envoyer(actif=None).wsgi_request
        self.assertEqual(requete.sensitive_post_parameters, ("secret",))
        self.assertEqual(SafeExceptionReporterFilter().get_post_parameters(requete)["secret"],
                         SafeExceptionReporterFilter().cleansed_substitute)

    def test_ni_sauvegarde_ni_registre_ni_export_de_configuration(self):
        import shutil
        import tempfile
        from pathlib import Path

        from collecte import configuration

        tmp = Path(tempfile.mkdtemp())  # archives dans un dossier à ce test : aucune trace pour les autres tests
        self.addCleanup(shutil.rmtree, tmp, True)
        reglages = override_settings(SAUVEGARDES_DIR=tmp / "backups")
        reglages.enable()
        self.addCleanup(reglages.disable)
        self.regler()
        archive = SV.creer("essai", format_base="json")
        with zipfile.ZipFile(archive.chemin) as z:
            contenu = b"".join(z.read(n) for n in z.namelist())
        registre = SV.creer_registre("essai")
        with zipfile.ZipFile(registre) as z:
            contenu += b"".join(z.read(n) for n in z.namelist())
        with zipfile.ZipFile(io.BytesIO(configuration.exporter("xlsx").content)) as z:  # classeur : décompressé
            contenu += b"".join(z.read(n) for n in z.namelist())
        chiffre = ReglageEntreprise.objects.get().secret_chiffre.encode()
        for interdit in (SECRET.encode(), chiffre, b"reglageentreprise", b"lienentreprise"):
            self.assertNotIn(interdit, contenu)

    def test_secret_illisible_apres_changement_de_cle_secrete(self):
        self.regler()
        with override_settings(SECRET_KEY="une-autre-cle-secrete-de-l-installation-2026-xxxxxxxxxxxx"):
            self.assertIsNone(dechiffrer(ReglageEntreprise.objects.get().secret_chiffre))
            self.assertFalse(regles.active())  # éteinte : le mot de passe sert de nouveau à tous
            self.assertContains(self.client_de(self.gestionnaire).get(URL), libelle("admin.connexion_entreprise.secret_illisible")
                                .split(" (")[0])
        # ancienne clé gardée parmi les clés de secours (SECRET_KEY_FALLBACKS) : lisible
        from django.conf import settings

        ancienne = settings.SECRET_KEY
        with override_settings(SECRET_KEY="nouvelle-cle-2026-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", SECRET_KEY_FALLBACKS=[ancienne]):
            self.assertEqual(dechiffrer(ReglageEntreprise.objects.get().secret_chiffre), SECRET)

    def test_allumer_exige_un_fournisseur_qui_repond(self):
        r = self.envoyer(client_id="", secret="")
        self.assertContains(r, libelle("admin.connexion_entreprise.manque.client_id"))
        self.assertContains(r, libelle("admin.connexion_entreprise.manque.secret"))
        self.assertFalse(ReglageEntreprise.objects.get().actif)
        self.assertEqual(self.faux.appels, [])  # incomplet : le fournisseur n'est même pas appelé
        r = self.envoyer(emetteur="http://127.0.0.1:9/realms/essai")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(regles.active())
        self.assertFalse(ReglageEntreprise.objects.get().actif)
        self.assertContains(r, escape(libelle("admin.connexion_entreprise.cause.injoignable")))

    def test_verifier_le_fournisseur_sans_rien_enregistrer(self):
        c = self.client_de(self.gestionnaire)
        r = c.post(URL, {"action": "essayer", "emetteur": self.faux.emetteur, "client_id": CLIENT_ID})
        self.assertContains(r, libelle("admin.connexion_entreprise.essai.decouverte"))
        self.assertContains(r, libelle("admin.connexion_entreprise.essai.cles"))
        self.assertContains(r, libelle("admin.connexion_entreprise.manque.secret"))
        self.assertFalse(ReglageEntreprise.objects.exists())
        # émetteur différent de celui que donne le fournisseur
        self.faux.decouverte = {"issuer": "https://autre.example/realms/essai"}
        r = c.post(URL, {"action": "essayer", "emetteur": self.faux.emetteur})
        self.assertContains(r, escape(libelle("admin.connexion_entreprise.cause.emetteur")))
        # fournisseur sans PKCE S256
        self.faux.decouverte = {"code_challenge_methods_supported": ["plain"]}
        r = c.post(URL, {"action": "essayer", "emetteur": self.faux.emetteur})
        self.assertContains(r, escape(libelle("admin.connexion_entreprise.cause.exigences")))

    @override_settings(CONNEXION_ENTREPRISE_LOCAL=False)
    def test_https_seulement_hors_essais(self):
        for adresse in ("http://login.exemple.example/realms/x", "ftp://login.exemple.example", "https://user:mdp@login.exemple.example",
                        "https://login.exemple.example/x?a=1", "javascript:alert(1)"):
            r = self.envoyer(emetteur=adresse)
            self.assertEqual(r.status_code, 400, adresse)
            self.assertContains(r, libelle("admin.connexion_entreprise.erreur.emetteur"), status_code=400)
        self.assertFalse(ReglageEntreprise.objects.exists())

    def test_retirer_le_secret_eteint(self):
        self.regler()
        c = self.client_de(self.gestionnaire)
        c.post(URL, {"action": "retirer_secret"})
        rg = ReglageEntreprise.objects.get()
        self.assertEqual((rg.secret_chiffre, rg.actif), ("", False))
        self.assertTrue(Journal.objects.filter(champ="secret", apres="retiré").exists())

    def test_oublier_un_lien(self):
        self.regler()
        self.parcours()
        self.assertEqual(LienEntreprise.objects.count(), 1)
        c = self.client_de(self.gestionnaire)
        c.post(URL, {"action": "oublier_lien", "email": "CONTRIB@exemple.example"})
        self.assertFalse(LienEntreprise.objects.exists())
        self.faux.claims = {"sub": "nouvelle-personne"}  # la prochaine connexion crée un nouveau lien
        c2, _ = self.parcours()
        self.assertEqual(LienEntreprise.objects.get().sujet, "nouvelle-personne")

    def test_un_seul_reglage_pour_tous_les_espaces(self):
        self.regler(libelle_bouton="Compte Exemple")
        with E.activer("essai"):
            pass
        self.assertContains(Client().get("/espace/essai/connexion/"), "Compte Exemple")
        self.assertContains(Client().get("/connexion/"), "Compte Exemple")
        self.assertEqual(ReglageEntreprise.objects.using("commun").count(), 1)
