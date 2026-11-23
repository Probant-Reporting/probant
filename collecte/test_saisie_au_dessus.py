"""Saisie aux niveaux supérieurs quand le détail manque (option du KPI)."""
from decimal import Decimal

from django.core.exceptions import PermissionDenied

from . import relances as RL
from . import saisie as S
from .coherence import controler
from .models import Alerte, Reponse
from .aides_tests.saisie import Base

D = Decimal


class SaisieAuDessusTests(Base):
    def setUp(self):
        super().setUp()
        self.eff.saisie_au_dessus = True
        self.eff.save()

    def reponse(self, org, kpi=None):
        return Reponse.objects.get(periode=self.c.periode, kpi=kpi or self.eff, organisation=org)

    def test_sans_option_refuse(self):
        self.eff.saisie_au_dessus = False
        self.eff.save()
        with self.assertRaises(PermissionDenied):
            self.enregistrer("100", user=self.admin, org=self.p)

    def test_valeur_saisie_remplace_le_total_et_remonte(self):
        self.enregistrer("100", user=self.admin, org=self.p)
        r = self.reponse(self.p)
        self.assertEqual((r.origine, r.valeur, r.statut), (Reponse.Origine.SAISIE, D(100), Reponse.Statut.BROUILLON))
        self.assertEqual(self.reponse(self.g).valeur, D(100))  # le groupe reprend la valeur du pays sans le détail
        self.assertEqual(self.reponse(self.g, self.calc).valeur, D(200))  # KPI calculé : formule refaite avec la valeur saisie

    def test_organisations_du_dessous_plus_attendues(self):
        self.enregistrer("100", user=self.admin, org=self.p)
        lignes = S.lignes(self.admin, self.c)
        eff = {l.organisation.nom: l for l in lignes if l.kpi.code == "EFF"}
        self.assertEqual({n: l.couverte for n, l in eff.items()}, {"E1": self.p, "E2": self.p})
        self.assertEqual(S.progression(lignes), (0, 2))  # seul le taux reste attendu (E1, E2)
        self.assertEqual([(l.kpi.code, l.organisation.nom) for p in RL.a_faire([self.c]) for _, ls in p.campagnes for l in ls],
                         [("TX", "E1")])
        self.enregistrer("40")  # le détail reste saisissable
        self.assertEqual(self.reponse(self.e1).valeur, D(40))

    def test_droits(self):
        S.enregistrer(self.valid, self.c, self.eff, self.p, "100", False, "")  # validateur du pays
        with self.assertRaises(PermissionDenied):
            self.enregistrer("100", org=self.p)  # contributeur : seulement son entité
        lignes = S.lignes(self.valid, self.c, org=self.p, calculees=True)
        l = next(l for l in lignes if l.kpi.code == "EFF")
        self.assertTrue(l.au_dessus and l.saisie_ici and not l.calculee and not l.attendue)

    def test_revenir_au_total_calcule(self):
        self.enregistrer("40")
        self.enregistrer("100", user=self.admin, org=self.p)
        self.enregistrer("", user=self.admin, org=self.p)
        r = self.reponse(self.p)
        self.assertEqual((r.origine, r.valeur, r.statut), (Reponse.Origine.AGREGATION, None, Reponse.Statut.INCOMPLET))
        self.assertIn("E2", r.message_calcul)
        # un total calculé non modifié n'est pas transformé en saisie
        self.assertEqual(self.enregistrer("", user=self.admin, org=self.p).origine, Reponse.Origine.AGREGATION)

    def test_ecart_avec_le_detail(self):
        self.enregistrer("40")
        self.enregistrer("50", org=self.e2, user=self.admin)
        self.enregistrer("100", user=self.admin, org=self.p)
        controler(self.c)
        a = Alerte.objects.get(controle=Alerte.Controle.DETAIL)
        self.assertEqual((a.organisation, a.kpi), (self.p, self.eff))
        self.enregistrer("90", user=self.admin, org=self.p)
        controler(self.c)
        self.assertEqual(Alerte.objects.get(controle=Alerte.Controle.DETAIL).statut, Alerte.Statut.CORRIGEE)

    def test_panneau(self):
        self.client.force_login(self.admin)
        from django.urls import reverse

        rep = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "EFF", self.p.pk]))
        self.assertContains(rep, "Total calculé à partir du détail")
        rep = self.client.post(reverse("collecte:cellule", args=[self.c.pk, "EFF", self.p.pk]),
                               {"action": "enregistrer", "valeur": "100"}, follow=True)
        self.assertContains(rep, "remplace ce total")
        self.client.post(reverse("collecte:cellule", args=[self.c.pk, "EFF", self.p.pk]), {"action": "revenir_total"})
        self.assertEqual(self.reponse(self.p).origine, Reponse.Origine.AGREGATION)

    def test_alerte_au_dessus_droits_de_la_page_coherence(self):
        """le validateur saisit au niveau du pays, mais l'alerte « écart avec le détail » posée sur le pays n'est
        pas dans ses cases (règle de la page Cohérence) : le panneau la montre, sans champ d'explication ni lien vers une
        fiche refusée ; un envoi forgé est refusé. L'administrateur la justifie dans le panneau."""
        from django.urls import reverse

        FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}
        self.enregistrer("40")
        self.enregistrer("50", org=self.e2, user=self.admin)
        S.enregistrer(self.valid, self.c, self.eff, self.p, "100", False, "")
        controler(self.c)
        a = Alerte.objects.get(controle=Alerte.Controle.DETAIL)
        url = reverse("collecte:cellule", args=[self.c.pk, "EFF", self.p.pk])
        self.client.force_login(self.valid)
        html = self.client.get(url, **FETCH).json()["html"]
        self.assertIn("diffère de la somme", html)
        self.assertNotIn("Expliquer pourquoi la valeur est juste", html)
        self.assertNotIn(reverse("collecte:alerte", args=[a.pk]), html)  # jamais « Accès refusé » depuis le panneau
        self.assertIn("L'administrateur traite cette alerte.", html)
        rep = self.client.post(url, {"action": "justifier", "alerte": a.pk, "justification": "Arrondis"}, **FETCH)
        self.assertEqual(rep.status_code, 403)
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.OUVERTE)
        self.client.force_login(self.admin)
        self.assertIn("Expliquer pourquoi la valeur est juste", self.client.get(url, **FETCH).json()["html"])
        res = self.client.post(url, {"action": "justifier", "alerte": a.pk, "justification": "Arrondis"}, **FETCH).json()
        self.assertTrue(res["ok"])
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.JUSTIFIEE)
