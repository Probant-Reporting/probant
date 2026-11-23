"""Paramètres › Assistant IA (vues_ia.reglages) : administrateur seulement ; éteint par défaut ; pas d'allumage sans
clé ; chaque changement au journal ; limites bornées ; la page dit ce qui part et ce qui ne part jamais, usage par
usage, dans les trois langues ; coupée par l'IT : onglet caché et avertissement."""
import html

from django.test import TestCase
from django.urls import reverse

from collecte.models import Journal
from parametres import ia as IA
from parametres.aides_tests.ia import CLE, AvecIA
from parametres.models import Instance
from referentiel.models import Utilisateur

URL = reverse("parametres:ia")


def donnees(**autres):
    return {"ia_fournisseur": "factice", "ia_modele": "factice-1", "ia_appels_jour": 50, "ia_taille_max": 60000, "ia_delai": 60,
            **autres}


class ReglagesIATests(AvecIA, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def test_reserve_a_l_administrateur(self):
        for role in (Utilisateur.Role.VALIDATEUR, Utilisateur.Role.CONTRIBUTEUR, Utilisateur.Role.LECTEUR, Utilisateur.Role.AUDITEUR):
            u = Utilisateur.objects.create(username=role, email=f"{role}@exemple.test", role=role)
            self.client.force_login(u)
            self.assertEqual(self.client.get(URL).status_code, 403, role)
            self.assertEqual(self.client.post(URL, donnees(ia_active="on", api_key=CLE)).status_code, 403, role)
        self.assertFalse(IA.cle_presente())

    def test_eteint_par_defaut_et_pas_d_allumage_sans_cle(self):
        page = self.client.get(URL)
        self.assertContains(page, "Éteint. Rien ne sort de l'outil.")
        rep = self.client.post(URL, donnees(ia_active="on"))
        self.assertEqual(rep.status_code, 200)
        self.assertIn("Saisissez la clé pour allumer l'assistant.", html.unescape(rep.content.decode()))
        self.assertFalse(Instance.courante().ia_active)

    def test_allumer_avec_la_cle_journal_de_chaque_changement(self):
        rep = self.client.post(URL, donnees(ia_active="on", ia_expliquer_alertes="on", ia_appels_jour=20, api_key=CLE))
        self.assertEqual(rep.status_code, 302)
        i = Instance.courante()
        self.assertEqual((i.ia_active, i.ia_expliquer_alertes, i.ia_reprise, i.ia_appels_jour), (True, True, False, 20))
        self.assertTrue(IA.disponible("expliquer_alerte"))
        self.assertFalse(IA.disponible("reprise"))
        champs = set(Journal.objects.filter(action="reglage_ia").values_list("champ", flat=True))
        self.assertTrue({"ia_active", "ia_expliquer_alertes", "ia_appels_jour", "ia_fournisseur", "cle"} <= champs)
        self.assertContains(self.client.get(URL), "Allumé. Appels utilisés aujourd'hui dans cet espace : 0 sur 20.")
        # sans nouvelle clé, la clé enregistrée reste
        self.client.post(URL, donnees(ia_active="on"))
        self.assertEqual(IA._lire_cle(), CLE)

    def test_limites_bornees_et_modele_d_un_autre_fournisseur(self):
        rep = self.client.post(URL, donnees(ia_appels_jour=0, ia_delai=500))
        self.assertEqual(rep.status_code, 200)
        self.assertEqual(Instance.courante().ia_appels_jour, 50)
        self.client.post(URL, donnees(ia_modele="claude-opus-5-5"))
        self.assertEqual(Instance.courante().ia_modele, "factice-1")  # modèle ramené à celui du fournisseur choisi

    def test_la_page_dit_ce_qui_part(self):
        page = html.unescape(self.client.get(URL).content.decode())
        for texte in ("Envoyé", "Jamais envoyé", "Les noms des organisations", "Les valeurs et les commentaires du fichier",
                      "Les clés techniques de l'outil", "api.anthropic.com"):
            self.assertIn(texte, page)
        self.client.cookies["langue"] = "en"
        Utilisateur.objects.filter(pk=self.admin.pk).update(langue="en")
        page = self.client.get(URL).content.decode()
        self.assertIn("Never sent", page)
        self.assertIn("Organisation names", page)
        Utilisateur.objects.filter(pk=self.admin.pk).update(langue="es")
        self.assertIn("Nunca se envía", self.client.get(URL).content.decode())

    def test_bouton_retirer_hors_du_formulaire_principal(self):
        IA.enregistrer_cle(CLE)
        page = self.client.get(URL).content.decode()
        principal = page.split('class="page-ia"')[1].split("</form>")[0]
        self.assertIn('form="form-retirer-cle"', principal)  # Entrée dans un champ n'envoie jamais « Retirer la clé »
        self.assertNotIn('value="retirer_cle"', principal)
        self.assertIn('id="form-retirer-cle"', page)

    def test_coupee_par_l_it(self):
        with self.settings(IA_PRISE_PERMISE=False):
            page = self.client.get(reverse("parametres:identite")).content.decode()
            self.assertNotIn(f'href="{URL}"', page)
            self.assertContains(self.client.get(URL), "Votre équipe informatique a coupé l'assistant IA")
        self.assertIn(f'href="{URL}"', self.client.get(reverse("parametres:identite")).content.decode())
