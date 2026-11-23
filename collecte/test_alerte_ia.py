"""« Expliquer avec l'IA » (vues_ia.alerte_ia) : aucun bouton tant que la prise ou l'usage est éteint ; droits de la
page Cohérence (une alerte qu'on voit) et rôles qui écrivent seulement ; ce qui part (ni nom d'organisation, ni
commentaire) ; la réponse est une proposition échappée, marquée IA, rien n'est enregistré ; un appel au journal."""
import json

from django.urls import reverse

from parametres.aides_tests.ia import AvecIA
from referentiel.models import Utilisateur

from .aides_tests.coherence import FETCH, BasePanneau
from .models import Alerte, Journal

BOUTON = 'data-ia-expliquer="'  # l'attribut d'un bouton (le script de chaque page cite le sélecteur)


class ExpliquerAlerteTests(AvecIA, BasePanneau):
    def setUp(self):
        super().setUp()
        self.a = self.historique(260)
        self.lecteur = Utilisateur.objects.create(username="lec", email="lec@exemple.test", role=Utilisateur.Role.LECTEUR)
        self.auditeur = Utilisateur.objects.create(username="aud", email="aud@exemple.test", role=Utilisateur.Role.AUDITEUR)

    def panneau(self, u):
        self.client.force_login(u)
        return self.client.get(self.url(), **FETCH).json()["html"]

    def fiche(self, u):
        self.client.force_login(u)
        return self.client.get(reverse("collecte:alerte", args=[self.a.pk])).content.decode()

    def expliquer(self, u, alerte=None, **donnees):
        self.client.force_login(u)
        return self.client.post(reverse("collecte:alerte_ia", args=[(alerte or self.a).pk]), donnees, **FETCH)

    def test_aucun_bouton_tant_que_la_prise_ou_l_usage_est_eteint(self):
        for reglage in ({"cle": False}, {"ia_active": False}, {"ia_expliquer_alertes": False}):
            with self.subTest(reglage=reglage):
                self.allumer(**reglage)
                if not reglage.get("cle", True):
                    from parametres import ia as IA

                    IA.retirer_cle()
                self.assertNotIn(BOUTON, self.panneau(self.contrib))
                self.assertNotIn(BOUTON, self.fiche(self.admin))
        self.allumer()
        with self.settings(IA_PRISE_PERMISE=False):
            self.assertNotIn(BOUTON, self.panneau(self.contrib))
        self.assertEqual(self.factice.demandes, [])

    def test_bouton_pour_les_roles_qui_ecrivent_jamais_pour_le_lecteur_ni_l_auditeur(self):
        self.allumer()
        self.assertIn(BOUTON, self.panneau(self.contrib))
        self.assertIn(BOUTON, self.fiche(self.admin))
        self.assertIn(f'data-ia-cible="justif-{self.a.pk}"', self.panneau(self.contrib))  # « Reprendre » vers son champ
        self.assertNotIn(BOUTON, self.panneau(self.auditeur))
        self.assertNotIn(BOUTON, self.fiche(self.auditeur))
        for u in (self.lecteur, self.auditeur):
            self.assertEqual(self.expliquer(u).status_code, 403, u.role)
        self.assertEqual(self.factice.demandes, [])
        self.assertFalse(Journal.objects.filter(action="ia_appel").exists())

    def test_alerte_hors_perimetre_refusee(self):
        self.allumer()
        self.assertEqual(self.expliquer(self.autre).status_code, 403)
        self.assertEqual(self.factice.demandes, [])

    def test_proposition_echappee_marquee_et_rien_d_enregistre(self):
        self.allumer()
        self.factice.reponse = {"explanation": "<img src=x onerror=alert(1)> Vérifiez l'unité.", "checks": ["<b>gras</b>"],
                                "statut": "acceptee"}
        avant = (self.a.statut, self.a.justification)
        rep = self.expliquer(self.contrib, cible=f"justif-{self.a.pk}")
        self.assertEqual(rep.status_code, 200)
        d = rep.json()
        self.assertTrue(d["ok"])
        self.assertIn("Proposé par l'IA (Fake provider (tests))", d["html"])
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", d["html"])
        self.assertNotIn("<img", d["html"])
        self.assertNotIn("<b>", d["html"])
        self.assertIn(f'data-ia-utiliser="justif-{self.a.pk}"', d["html"])
        self.a.refresh_from_db()
        self.assertEqual((self.a.statut, self.a.justification), avant)  # la réponse n'a rien changé
        j = Journal.objects.get(action="ia_appel")
        self.assertEqual((j.utilisateur, j.objet, j.objet_id, j.champ), (self.contrib, "Alerte", str(self.a.pk), "expliquer_alerte"))

    def test_ce_qui_part(self):
        self.allumer()
        self.saisir(self.eff, 260, com="Commentaire très personnel de Camille")
        self.expliquer(self.contrib)
        r = self.factice.demandes[0]
        donnees = json.loads(r.donnees[7:-8])
        self.assertEqual(donnees["kpi"]["name"], "Effectif")
        self.assertEqual(donnees["answer_language"], "French")
        self.assertEqual(len(donnees["previous_values"]), 5)
        self.assertEqual(donnees["organisation_level"], "Entité")
        texte = r.systeme + r.donnees
        for jamais in ("E1", "Pays", "Groupe", "Commentaire très personnel", "contrib@exemple.test", "Camille"):
            self.assertNotIn(jamais, texte)

    def test_refus_et_erreur_restent_a_l_ecran(self):
        self.allumer(ia_appels_jour=1)
        self.factice.erreur = "quota"
        d = self.expliquer(self.contrib).json()
        self.assertFalse(d["ok"])
        self.assertIn('role="alert"', d["html"])
        self.assertIn("Le fournisseur limite le nombre de demandes", d["html"])
        d = self.expliquer(self.contrib).json()
        self.assertIn("Limite du jour atteinte (1 appel)", d["html"])  # plafond : refusé avant envoi
        self.assertEqual(len(self.factice.demandes), 1)

    def test_sans_script_retour_a_la_fiche(self):
        self.allumer()
        self.client.force_login(self.contrib)
        rep = self.client.post(reverse("collecte:alerte_ia", args=[self.a.pk]))
        self.assertRedirects(rep, reverse("collecte:alerte", args=[self.a.pk]), fetch_redirect_response=False)
        self.assertEqual(self.factice.demandes, [])
        self.assertEqual(self.client.get(reverse("collecte:alerte_ia", args=[self.a.pk])).status_code, 405)

    def test_regle_entre_kpi(self):
        from .models import RegleCoherence

        self.allumer()
        RegleCoherence.objects.create(nom="Formés ≤ Effectif", gauche="[FORM]", operateur="<=", droite="[EFF]", niveau_id="Entity")
        self.saisir(self.form, 300)
        self.saisir(self.eff, 100)
        a = Alerte.objects.filter(controle="regle").first()
        self.assertIsNotNone(a)
        self.expliquer(self.admin, alerte=a)
        donnees = json.loads(self.factice.demandes[0].donnees[7:-8])
        self.assertEqual(donnees["rule"]["name"], "Formés ≤ Effectif")
        self.assertEqual([x["kpi"] for x in donnees["rule"]["left"]], ["Formés"])

    def test_champ_cible_limite_a_l_explication_de_l_alerte(self):
        self.allumer()
        d = self.expliquer(self.contrib, cible="id_password").json()
        self.assertNotIn("data-ia-utiliser", d["html"])  # « Reprendre » ne vise jamais un autre champ de la page
