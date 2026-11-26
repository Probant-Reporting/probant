"""Paramètres › Connexion d'entreprise : le secret du client ne part jamais vers un autre fournisseur que celui pour lequel
il a été saisi. Autre adresse du fournisseur (émetteur ; sans la casse du protocole et du serveur ni la « / » finale,
le chemin tel quel) ou autre identifiant du client, sans nouveau secret : le secret est effacé, l'écran le dit,
l'historique note « effacé (fournisseur changé) », et la connexion d'entreprise s'éteint proprement : personne n'est
enfermé dehors (mot de passe permis à tous, sessions par mot de passe gardées), comme avec un secret illisible."""
from django.test import Client

from collecte.models import Journal
from parametres.libelles import libelle

from . import regles
from .aides_tests import BaseEntreprise
from .aides_tests.faux_fournisseur import CLIENT_ID, SECRET
from .models import ReglageEntreprise
from .secret import dechiffrer

URL = "/administration/parametres/connexion-entreprise/"


class FournisseurChangeTests(BaseEntreprise):
    def envoyer(self, **valeurs):
        c = Client()
        c.force_login(self.gestionnaire)
        donnees = {"action": "enregistrer", "actif": "on", "emetteur": self.faux.emetteur, "client_id": CLIENT_ID,
                   "secret": "", **valeurs}
        return c.post(URL, {k: v for k, v in donnees.items() if v is not None}, follow=True)

    def efface(self):
        return Journal.objects.filter(action="reglage_connexion_entreprise", champ="secret",
                                      apres=libelle("admin.connexion_entreprise.journal.secret_efface_fournisseur", langue="fr"))

    def test_autre_fournisseur_sans_secret_efface_et_eteint(self):
        cas = {"emetteur": {"emetteur": "https://autre-fournisseur.exemple.example/realms/essai"},
               "chemin": {"emetteur": self.faux.emetteur.replace("/realms/essai", "/realms/Essai")},
               "client": {"client_id": "un-autre-client"}}
        for nom, changement in cas.items():
            with self.subTest(nom):
                self.regler()
                Journal.objects.all().delete()
                self.assertTrue(regles.active())
                rep = self.envoyer(**changement)
                r = ReglageEntreprise.objects.get()
                self.assertEqual((r.secret_chiffre, r.secret_le, r.actif), ("", None, False))
                self.assertFalse(regles.active())
                self.assertContains(rep, libelle("admin.connexion_entreprise.secret_efface_fournisseur").split(":")[0])
                self.assertEqual(self.efface().count(), 1)
                textes = " ".join(f"{j.champ} {j.avant} {j.apres}" for j in Journal.objects.all())
                self.assertNotIn(SECRET, textes)
                self.assertEqual(self.faux.appels, [])  # aucun appel au nouveau fournisseur sans secret

    def test_personne_n_est_enferme_dehors(self):
        """Sans secret, la connexion d'entreprise est éteinte : mot de passe permis à tous, session par mot de passe
        d'un compte qui n'est pas de secours gardée, comme quand le secret est illisible."""
        self.regler()
        self.assertFalse(regles.mot_de_passe_permis(self.contrib.pk))
        self.envoyer(emetteur="https://autre-fournisseur.exemple.example/realms/essai")
        self.assertTrue(regles.mot_de_passe_permis(self.contrib.pk))
        self.assertTrue(regles.session_permise(self.contrib.pk, "mot_de_passe"))
        self.assertTrue(regles.assistants_permis(self.contrib.pk))
        # même règle pour un réglage allumé dont le secret manque (restauration, saisie directe) : éteinte
        self.regler(secret_chiffre="")
        self.assertFalse(regles.active())
        self.assertTrue(regles.mot_de_passe_permis(self.contrib.pk))
        self.assertTrue(regles.session_permise(self.contrib.pk, "mot_de_passe"))
        page = Client().get("/connexion/")
        self.assertEqual(page.status_code, 200)

    def test_nouveau_secret_dans_le_meme_envoi(self):
        self.regler(actif=False)
        self.envoyer(actif=None, client_id="un-autre-client", secret="secret-du-nouveau-client")
        r = ReglageEntreprise.objects.get()
        self.assertEqual(dechiffrer(r.secret_chiffre), "secret-du-nouveau-client")
        self.assertFalse(self.efface().exists())

    def test_meme_fournisseur_garde_le_secret(self):
        """Casse du protocole et du serveur, « / » finale : même fournisseur ; aucun appel, connexion éteinte ici."""
        self.regler(actif=False)
        emetteur = self.faux.emetteur.replace("http://", "HTTP://") + "/"
        rep = self.envoyer(actif=None, emetteur=emetteur, libelle_bouton="Autre libellé")
        self.assertNotContains(rep, libelle("admin.connexion_entreprise.secret_efface_fournisseur").split(":")[0])
        self.assertEqual(dechiffrer(ReglageEntreprise.objects.get().secret_chiffre), SECRET)
        self.assertFalse(self.efface().exists())
