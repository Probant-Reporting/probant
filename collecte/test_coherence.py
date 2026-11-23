"""Onglet Cohérence : contrôles automatiques, règles entre KPI, traitement des alertes, droits."""
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from referentiel.models import Niveau

from . import coherence as CO
from . import saisie as S
from .aides_tests.coherence import BaseCoherence, BasePanneau
from .models import Alerte, Campagne, RegleCoherence, Reponse
from .templatetags.collecte import formater
import datetime

from .aides_tests.arbre_valeurs import Base
from .vues_coherence import tester_regle
from referentiel.models import KPI, Organisation, Utilisateur

D = Decimal
FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class CoherenceTests(BaseCoherence):
    # -- contrôles automatiques -------------------------------------------------
    def test_ecart_n1_corrige_par_un_commentaire(self):
        self.saisir(self.eff, 150)
        a = self.alertes(controle="ecart_n1").get()
        self.assertIn("+50\u202f%", a.message)
        self.saisir(self.eff, 150, com="Rachat d'une filiale")
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.CORRIGEE)

    def test_hors_historique(self):
        self.c.seuil_ecart = None
        self.c.save()
        self.saisir(self.eff, 260)
        a = self.alertes(controle="historique").get()
        # constat en clair : la valeur, l'ordre de grandeur habituel et le rapport (plus de « × la médiane »)
        self.assertIn("260", a.message)
        self.assertIn("contre environ 100", a.message)
        self.assertIn("d'habitude (médiane des 5 exercices précédents) : 2,6 fois plus.", a.message)
        self.assertNotIn("×", a.message)
        self.saisir(self.eff, 110)
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.CORRIGEE)

    def test_seuils_de_coherence_reglables(self):
        """Paramètres › Seuils de suivi : sans assez de valeurs passées, pas de contrôle « hors historique » ; l'écart
        toléré sur un paramètre hérité change l'alerte « paramètre hérité modifié »."""
        from parametres.models import Instance

        self.c.seuil_ecart = None
        self.c.save()
        Instance.courante()
        Instance.objects.filter(pk=1).update(historique_minimum=10, historique_annees=10)
        self.saisir(self.eff, 260)
        self.assertFalse(self.alertes(controle="historique").exists())
        Instance.objects.filter(pk=1).update(tolerance_fe=Decimal("0.9"))
        self.saisir(self.fe, "2,1")
        self.assertFalse(self.alertes(controle="fe_modifie").exists())

    def test_facteur_modifie_format_et_rupture(self):
        self.saisir(self.fe, "2,1")
        self.assertTrue(self.alertes(controle="fe_modifie").exists())
        self.saisir(self.eff, "-3")  # comptage négatif : signalé (une décimale, elle, est refusée)
        self.assertTrue(self.alertes(controle="format", kpi=self.eff).exists())
        self.saisir(self.form, "", com="Pas de formation cette année", na=True)
        self.assertTrue(self.alertes(controle="rupture", kpi=self.form).exists())
        self.saisir(self.form, 0)
        self.assertIn("à 0", self.alertes(controle="rupture", kpi=self.form, statut="ouverte").get().message)

    # -- règles entre KPI ----------------------------------------------------------
    def test_regle_bloquante_empeche_de_valider(self):
        RegleCoherence.objects.create(nom="Formés ≤ effectif", gauche="[FORM]", operateur="<=", droite="[EFF]", niveau_id=Niveau.ENTITY,
                                      bloquante=True)
        self.saisir(self.eff, 100)
        self.saisir(self.form, 120)
        a = self.alertes(controle="regle").get()
        self.assertEqual(a.gravite, Alerte.Gravite.BLOQUANTE)
        self.assertEqual(a.kpis_concernes, "FORM EFF")
        with self.assertRaisesMessage(ValidationError, "Formés ≤ effectif"):
            S.valider(self.contrib, self.c, self.form, self.e1)
        self.saisir(self.form, 50)
        self.assertEqual(S.valider(self.contrib, self.c, self.form, self.e1).statut, Reponse.Statut.VALIDE)
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.CORRIGEE)

    def test_regle_avec_tolerance(self):
        r = RegleCoherence(nom="égalité", gauche="[FORM]", operateur="=", droite="[EFF]", tolerance=D("0.01"))
        self.assertTrue(CO.respecte(r, D(100), D("100.9")))
        self.assertFalse(CO.respecte(r, D(100), D(102)))

    # -- traitement --------------------------------------------------------------------
    def test_justifier_accepter_et_reouverture_si_la_valeur_change(self):
        self.saisir(self.eff, 160)
        a = self.alertes(controle="ecart_n1").get()
        with self.assertRaises(ValidationError):
            CO.traiter(self.contrib, a, "justifier", "")
        CO.traiter(self.contrib, a, "justifier", "Ouverture d'un site")
        self.assertEqual(a.statut, Alerte.Statut.JUSTIFIEE)
        with self.assertRaises(PermissionDenied):
            CO.traiter(self.contrib, a, "accepter")
        CO.traiter(self.admin, a, "accepter")
        CO.controler(self.c)  # valeur inchangée : la décision tient
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.ACCEPTEE)
        Reponse.objects.filter(periode=self.c.periode, kpi=self.eff).update(valeur=D(170))
        CO.controler(self.c)  # nouvelle valeur : l'alerte est à revoir
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.OUVERTE)

    # -- pages et droits ----------------------------------------------------------------
    def test_page_et_perimetre(self):
        self.saisir(self.eff, 160)
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:coherence"))
        self.assertContains(rep, "Écart avec N-1")
        self.assertContains(rep, "en 2025 : +60\u202f%.")  # « 160 salariés, contre 100 salariés en 2025 : +60 %. »
        a = self.alertes(controle="ecart_n1").get()
        res = self.client.post(reverse("collecte:alerte", args=[a.pk]), {"action": "justifier", "texte": "Ouverture d'un site"}, **FETCH).json()
        self.assertTrue(res["ok"])
        self.client.force_login(self.autre)
        self.assertNotContains(self.client.get(reverse("collecte:coherence")), "+60 %")
        self.assertEqual(self.client.get(reverse("collecte:alerte", args=[a.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("collecte:regles")).status_code, 403)
        # la page Saisie signale l'alerte sur la ligne (une alerte justifiée n'est plus « à traiter »)
        self.saisir(self.fe, "2,1")
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:saisie") + f"?org={self.e1.id}")
        self.assertContains(rep, "badge-alerte")
        self.assertContains(rep, 'data-filtre-statut="alerte"')  # filtre « Cohérence »
        self.assertContains(rep, 'data-alerte="1"')
        self.assertContains(self.client.get(reverse("collecte:pour_moi")), 'data-filtre-statut="alerte"')

    def test_creer_et_tester_une_regle(self):
        self.saisir(self.eff, 100)
        self.saisir(self.form, 120)
        self.client.force_login(self.admin)
        donnees = {"nom": "Formés ≤ effectif", "gauche": "[FORM]", "operateur": "<=", "droite": "[EFF]", "tolerance": "0",
                   "niveau": "Entity", "actif": "on"}
        res = self.client.post(reverse("collecte:regle_nouvelle"), {**donnees, "action": "tester"}, **FETCH).json()
        self.assertIn("Non respectée", res["html"])
        self.assertFalse(RegleCoherence.objects.exists())  # le test n'enregistre rien
        res = self.client.post(reverse("collecte:regle_nouvelle"), {**donnees, "action": "enregistrer"}, **FETCH).json()
        self.assertTrue(res["ok"], res["html"])
        self.assertTrue(self.alertes(controle="regle").exists())
        res = self.client.post(reverse("collecte:regle_nouvelle"), {**donnees, "gauche": "[INCONNU]", "action": "enregistrer"}, **FETCH).json()
        self.assertIn("KPI inconnu", res["html"])
        self.assertContains(self.client.get(reverse("collecte:regles")), "« Formés »")

    def test_tolerance_entre_0_et_100_pourcent(self):
        # une tolérance (écart relatif) négative ou au-delà de 1 (= 100 %) est refusée, sans rien enregistrer
        self.client.force_login(self.admin)
        donnees = {"nom": "R test", "gauche": "[FORM]", "operateur": "<=", "droite": "[EFF]", "niveau": "Entity",
                   "bloquante": "on", "actif": "on", "action": "enregistrer"}
        for tolerance in ("-5", "-0.01", "1.5"):
            res = self.client.post(reverse("collecte:regle_nouvelle"), {**donnees, "tolerance": tolerance}, **FETCH).json()
            self.assertFalse(res["ok"], tolerance)
            self.assertIn("Saisissez une tolérance de 0 à 1", res["html"])
        self.assertFalse(RegleCoherence.objects.exists())
        res = self.client.post(reverse("collecte:regle_nouvelle"), {**donnees, "tolerance": "1"}, **FETCH).json()
        self.assertTrue(res["ok"], res["html"])
        self.assertIn('min="0"', res["html"])

    def test_mettre_une_regle_en_pause(self):
        r = RegleCoherence.objects.create(nom="Formés ≤ effectif", gauche="[FORM]", operateur="<=", droite="[EFF]", niveau_id=Niveau.ENTITY)
        self.saisir(self.eff, 100)
        self.saisir(self.form, 120)
        self.client.force_login(self.admin)
        self.client.post(reverse("collecte:regle_basculer", args=[r.pk]))
        r.refresh_from_db()
        self.assertFalse(r.actif)
        self.assertEqual(self.alertes(controle="regle").get().statut, Alerte.Statut.CORRIGEE)
        self.assertContains(self.client.get(reverse("collecte:regles")), "Inactive")
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.post(reverse("collecte:regle_basculer", args=[r.pk])).status_code, 403)


class JustifierDansLePanneauTests(BasePanneau):
    """Étape 4 : une alerte se justifie dans le panneau de saisie (« Expliquer pourquoi la valeur est juste »), comme sur la
    page Cohérence, avec la règle de droits de cette page ; constat en clair ; 0 et valeurs négatives sans
    erreur ; écart avec N-1 renvoyé au commentaire ; alertes apparues signalées (E6)."""

    def test_justifier_dans_le_panneau(self):
        from .models import Journal

        a = self.historique()
        self.client.force_login(self.contrib)
        html = self.client.get(self.url(), **FETCH).json()["html"]
        self.assertIn("Expliquer pourquoi la valeur est juste", html)
        self.assertIn('name="justification"', html)
        self.assertIn("2,6 fois plus", html)  # constat en clair dans l'encadré « À vérifier »
        rep = self.justifier(a, "Rachat d'une filiale en mars")
        res = rep.json()
        self.assertTrue(res["ok"])
        a.refresh_from_db()
        self.assertEqual((a.statut, a.justification, a.justifie_par), (Alerte.Statut.JUSTIFIEE, "Rachat d'une filiale en mars", self.contrib))
        self.assertTrue(Journal.objects.filter(action="alerte_justifier", utilisateur=self.contrib).exists())
        self.assertIn("Explication enregistrée", res["html"])
        self.assertIn('role="status" tabindex="-1" data-message-justif', res["html"])
        self.assertIn("Rachat d&#x27;une filiale en mars", res["html"])  # l'explication reste lisible dans le panneau
        self.assertNotIn('name="justification"', res["html"])  # plus rien à justifier
        self.assertIn(f'pa-statut-justifiee" data-alerte-point="{a.pk}"', res["html"])  # même couleur que sur la page Cohérence
        ligne = res["lignes"][f"EFF|{self.e1.id}"]
        self.assertNotIn("badge-alerte", ligne)  # la ligne de la liste n'est plus « à vérifier »
        self.assertEqual(res["nouvelles_alertes"], [])
        # l'équipe responsable a une justification à trancher (Administration › À traiter)
        self.client.force_login(self.admin)
        titres = [t["titre"] for t in self.client.get(reverse("collecte:admin_accueil")).context["a_traiter"]]
        self.assertIn("1 justification à trancher", titres)

    def test_texte_vide_erreur_sous_le_champ(self):
        self.saisir(self.form, 120)  # brouillon : aucune règle, mais un motif de validation éventuel reste affiché
        a = self.historique()
        res = self.justifier(a, "   ").json()
        self.assertFalse(res["ok"])
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.OUVERTE)
        self.assertIn(f'id="justif-{a.pk}-erreur">Saisissez une explication.', res["html"])
        self.assertRegex(res["html"], rf'id="justif-{a.pk}"[^>]*aria-invalid="true" aria-describedby="justif-{a.pk}-erreur"')
        self.assertNotIn('id="erreurs-saisie"', res["html"])  # l'erreur n'est pas un refus de la saisie
        self.assertIn("2,6 fois plus", res["html"])  # l'encadré garde ses points et son constat
        self.assertEqual(S.reponse_de(self.c, self.eff, self.e1).valeur, D(260))  # la saisie n'est pas touchée

    def test_alerte_d_une_autre_case_404(self):
        a = self.historique()
        self.assertEqual(self.justifier(a, "Texte", utilisateur=self.admin, kpi=self.form).status_code, 404)
        self.assertEqual(self.justifier(a, "Texte", utilisateur=self.admin, org=self.e2).status_code, 404)
        self.client.force_login(self.admin)
        rep = self.client.post(self.url(), {"action": "justifier", "alerte": "abc", "justification": "x"}, **FETCH)
        self.assertEqual(rep.status_code, 404)
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.OUVERTE)

    def test_refus_selon_les_droits_de_la_page_coherence(self):
        """un contributeur qui voit la case par un autre KPI ne justifie pas une alerte hors de ses cases."""
        a = self.historique()
        self.assertTrue(CO.peut_justifier(self.contrib, a))
        self.assertFalse(CO.peut_voir(self.autre, a))
        self.assertFalse(CO.peut_justifier(self.autre, a))
        self.assertEqual(self.justifier(a, "Texte", utilisateur=self.autre).status_code, 403)  # case hors périmètre
        CO.traiter(self.admin, a, "ignorer")
        self.assertFalse(CO.peut_justifier(self.contrib, a))  # statut qui ne le permet plus
        res = self.justifier(a, "Texte").json()
        self.assertFalse(res["ok"])
        self.assertIn("Action impossible", res["html"])
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.IGNOREE)

    def test_fiche_d_une_alerte_traitee_toujours_visible(self):
        a = self.historique()
        self.justifier(a, "Inventaire refait")
        a.refresh_from_db()
        CO.traiter(self.admin, a, "accepter")
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:alerte", args=[a.pk]))
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, "Inventaire refait")
        html = self.client.get(self.url(), **FETCH).json()["html"]
        self.assertIn(reverse("collecte:alerte", args=[a.pk]), html)  # lien vers la fiche, jamais « Accès refusé »
        self.assertNotIn('name="justification"', html)

    def test_zero_et_valeur_negative_sans_erreur(self):
        """0 ou −5 après des années positives : le contrôle ne plante pas et ne donne pas de rapport (« fois »)."""
        self.c.seuil_ecart = None
        self.c.save()
        self.saisir(self.eff, 0)
        h = self.alertes(controle="historique").get()
        self.assertEqual(h.message, f"{formater(D(0), self.eff)}, contre environ {formater(D(100), self.eff)} d'habitude "
                                    "(médiane des 5 exercices précédents).")
        self.assertTrue(self.alertes(controle="rupture", kpi=self.eff).exists())
        self.saisir(self.eff, -5)
        h.refresh_from_db()
        self.assertNotIn("fois", h.message)
        self.assertTrue(self.alertes(controle="format", kpi=self.eff).exists())
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(self.url(), **FETCH).status_code, 200)

    def test_decimale_d_un_comptage_refusee(self):
        """Unité « nombre entier » (comptage) : 12,5 est refusé à la saisie ; rien n'est
        enregistré, le message le dit ; 12 est accepté. Le contrôle de cohérence « Nombre décimal pour un comptage » reste
        pour une valeur venue d'ailleurs (classeur de configuration qui change l'unité, par exemple)."""
        self.c.seuil_ecart = None
        self.c.save()
        self.assertTrue(self.eff.est_entier)
        self.client.force_login(self.contrib)
        res = self.client.post(self.url(), {"action": "enregistrer", "valeur": "12,5", "commentaire": ""}, **FETCH).json()
        self.assertFalse(res["ok"])
        self.assertIn("Saisissez un nombre entier", res["html"])
        self.assertIsNone(S.reponse_de(self.c, self.eff, self.e1))
        res = self.client.post(self.url(), {"action": "enregistrer", "valeur": "12", "commentaire": ""}, **FETCH).json()
        self.assertTrue(res["ok"])
        self.assertEqual(S.reponse_de(self.c, self.eff, self.e1).valeur, D("12"))

    def test_constat_fois_moins(self):
        self.assertEqual(CO.constat_historique(D(42), D(3480), self.eff, 5, "exercices précédents"),
                         f"{formater(D(42), self.eff)}, contre environ {formater(D(3480), self.eff)} d'habitude "
                         "(médiane des 5 exercices précédents) : 83 fois moins.")
        self.assertIn(": 2,6 fois plus.", CO.constat_historique(D(260), D(100), self.eff, 5, "exercices précédents"))
        self.assertIn(": 10 fois plus.", CO.constat_historique(D("998"), D(100), self.eff, 5, "exercices précédents"))

    def test_rupture_apres_une_annee_na(self):
        Reponse.objects.filter(periode=self.anciennes[-1].periode, kpi=self.form).update(valeur=None, non_applicable=True)
        self.saisir(self.form, 40)
        a = self.alertes(controle="rupture", kpi=self.form).get()
        self.assertIn("était N/A", a.message)
        res = self.justifier(a, "Formations reprises", kpi=self.form).json()
        self.assertTrue(res["ok"])
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.JUSTIFIEE)

    def test_pas_de_justification_pour_un_calcul_impossible(self):
        a = Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.CALCUL,
                                  gravite=Alerte.Gravite.INFO, message="Division par zéro.")
        self.client.force_login(self.admin)
        html = self.client.get(self.url(), **FETCH).json()["html"]
        self.assertIn("Division par zéro.", html)
        self.assertNotIn("C'est juste", html)
        self.assertEqual(self.justifier(a, "Texte", utilisateur=self.admin).status_code, 403)

    def test_commentaire_propose_et_justification_rejetee_sans_decision_admin(self):
        """le commentaire de la saisie est proposé dans le champ, rien n'est justifié sans clic ; une justification
        rejetée est reproposée sans la décision de l'admin, montrée à part."""
        self.c.seuil_ecart = None
        self.c.save()
        self.saisir(self.eff, 260, com="Valeur vérifiée.")
        a = self.alertes(controle="historique").get()
        self.client.force_login(self.contrib)
        html = self.client.get(self.url(), **FETCH).json()["html"]
        self.assertRegex(html, rf'<textarea id="justif-{a.pk}"[^>]*>Valeur vérifiée.</textarea>')
        self.assertIn("Proposé à partir du commentaire", html)
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.OUVERTE)  # proposé seulement
        CO.traiter(self.contrib, a, "justifier", "Nouvel entrepôt")
        CO.traiter(self.admin, a, "rejeter", "Joindre le bail")
        html = self.client.get(self.url(), **FETCH).json()["html"]
        self.assertRegex(html, rf'<textarea id="justif-{a.pk}"[^>]*>Nouvel entrepôt</textarea>')
        self.assertNotIn("— Admin", html)
        self.assertIn("Explication rejetée par l'administrateur : Joindre le bail", html)

    def test_ecart_n1_renvoie_au_commentaire_puis_valeur_inhabituelle(self):
        """l'écart avec N-1 s'explique dans le commentaire ; une fois commenté, la « valeur inhabituelle » peut
        apparaître (nouvelles_alertes, E6)."""
        self.client.force_login(self.contrib)
        res = self.client.post(self.url(), {"action": "enregistrer", "valeur": "260", "commentaire": ""}, **FETCH).json()
        ecart = self.alertes(controle="ecart_n1").get()
        self.assertEqual(res["nouvelles_alertes"], [ecart.pk])
        self.assertIn("contre 100", ecart.message)
        self.assertIn("data-vers-commentaire", res["html"])
        self.assertIn(f"{formater(D(260), self.eff)}, contre {formater(D(100), self.eff)} en 2025", res["html"])
        self.assertNotIn(f'id="justif-{ecart.pk}"', res["html"])  # pas de second endroit pour l'expliquer
        res = self.client.post(self.url(), {"action": "enregistrer", "valeur": "260", "commentaire": "Rachat d'une filiale"},
                               **FETCH).json()
        ecart.refresh_from_db()
        self.assertEqual(ecart.statut, Alerte.Statut.CORRIGEE)
        h = self.alertes(controle="historique").get()
        self.assertEqual(res["nouvelles_alertes"], [h.pk])
        self.assertIn(f'id="justif-{h.pk}"', res["html"])
        self.assertRegex(res["html"], rf'<textarea id="justif-{h.pk}"[^>]*>Rachat d&#x27;une filiale</textarea>')
        # validée, l'écart prévient qu'une modification repasse en brouillon
        Alerte.objects.all().delete()
        self.client.post(self.url(), {"action": "enregistrer", "valeur": "300", "commentaire": ""}, **FETCH)
        Reponse.objects.filter(periode=self.c.periode, kpi=self.eff).update(statut=Reponse.Statut.VALIDE)
        html = self.client.get(self.url(), **FETCH).json()["html"]
        self.assertIn("La valeur repasse en brouillon", html)

    def test_ecart_et_badge_de_la_meme_couleur(self):
        """E7 : l'écart au-delà du seuil (à expliquer) et le badge « À vérifier » de la ligne sont en orange ; « À
        traiter » aussi. Le rouge reste aux erreurs et aux blocages."""
        import re
        from pathlib import Path

        from django.conf import settings

        css = (Path(settings.BASE_DIR) / "static" / "css" / "outil.css").read_text()

        def couleur(selecteur):
            m = re.search(r"(?m)^" + re.escape(selecteur) + r"[^{]*\{[^}]*?(?<![-\w])color:\s*([^;]+);", css)
            return m and m.group(1).strip()

        self.assertEqual(couleur(".ecart-fort"), "var(--orange-texte)")
        self.assertEqual(couleur(".badge-alerte"), "var(--orange-texte)")
        self.assertEqual(couleur(".statut-alerte-ouverte"), "var(--orange-texte)")
        # page Cohérence : le nombre d'alertes à justifier est dans le panneau du champ de filtre, en texte
        # doux : jamais en rouge, et plus de tuile ; l'orange reste sur « À traiter » dans la liste
        self.assertEqual(couleur(".choix-panneau .nb-choix"), "var(--texte-doux)")
        self.assertNotIn("carte-controle", css)
        # panneau : un point qui bloque la validation a sa puce en rouge (pas dans la couleur principale) ; une alerte
        # justifiée a la même couleur d'état que sur la page Cohérence
        self.assertRegex(css, r"\.pa-bloque \.pa-pastille \{ background: var\(--erreur\); \}")
        self.assertEqual(couleur(".pa-statut-justifiee .pa-etiquette"), couleur(".statut-alerte-justifiee"))

    def test_ligne_constat_visible(self):
        """Le message de l'alerte se lit dans la liste (pas seulement dans une infobulle)."""
        self.historique()
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:saisie") + f"?org={self.e1.id}")
        self.assertContains(rep, f'<div class="constat-ligne"><span>{formater(D(260), self.eff)}, contre environ')
        self.assertContains(rep, "À vérifier</span>")
        self.assertRegex(rep.content.decode(), r'aria-label="Effectif – E1 : à vérifier, 260[^"]*2,6 fois plus : ouvrir \(Entrée\)"')

    def test_aucune_balise_de_gabarit_affichee(self):
        """Un commentaire {# … #} sur deux lignes s'affiche en clair (Django ne le reconnaît que sur une ligne) : aucun
        gabarit n'en contient, et le bandeau « alertes à justifier » de Saisie et de Pour moi n'en montre pas."""
        import re
        from pathlib import Path

        from django.conf import settings

        fautifs = [f"{f.relative_to(settings.BASE_DIR)}:{n}" for f in Path(settings.BASE_DIR).glob("**/templates/**/*.html")
                   for n, ligne in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
                   if re.search(r"\{#(?!.*#\})", ligne)]
        self.assertEqual(fautifs, [])
        for k, v in ((self.form, 50), (self.fe, "2,5")):
            self.saisir(k, v)
        self.historique()
        for k in (self.eff, self.form, self.fe):
            S.valider(self.contrib, self.c, k, self.e1)
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:saisie") + f"?org={self.e1.id}")
        self.assertContains(rep, 'data-etat="alertes_ici"')
        for page in (rep, self.client.get(reverse("collecte:pour_moi"))):
            self.assertNotContains(page, "{#")
            self.assertNotContains(page, "{%")

    def test_lecture_seule_ecart_n1_justifiable(self):
        """saisie fermée (campagne en revue, ou date de fin passée), un brouillon avec un écart avec N-1 sans
        commentaire se justifie dans le panneau, comme sur la page Cohérence (pas de motif « Bloque la validation »)."""
        import datetime

        self.saisir(self.eff, 260)
        a = self.alertes(controle="ecart_n1").get()
        for statut, fin in ((Campagne.Statut.REVUE, None), (Campagne.Statut.OUVERTE, datetime.date(2026, 1, 1))):
            self.c.statut, self.c.date_fin_saisie = statut, fin
            self.c.save()
            self.client.force_login(self.contrib)
            html = self.client.get(self.url(), **FETCH).json()["html"]
            self.assertIn(f'id="justif-{a.pk}"', html)
            self.assertNotIn("Bloque la validation", html)
            self.assertNotIn("data-vers-commentaire", html)
        # en lecture seule, les autres motifs restent affichés (seul l'écart avec N-1 devient une alerte à justifier)
        self.eff.preuve_obligatoire = True
        self.eff.save()
        html = self.client.get(self.url(), **FETCH).json()["html"]
        self.assertIn("Ce KPI exige une preuve. Ajoutez un fichier pour valider.", html)
        self.assertIn(f'id="justif-{a.pk}"', html)
        self.eff.preuve_obligatoire = False
        self.eff.save()
        self.assertTrue(self.justifier(a, "Rachat d'une filiale").json()["ok"])
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.JUSTIFIEE)

    def test_ancien_message_reecrit_a_l_affichage(self):
        """une alerte enregistrée avant cette version garde son message en base, mais la ligne, le panneau et la
        page Cohérence l'affichent en clair (ni « × la médiane », ni « par rapport à N-1, sans commentaire »)."""
        h = self.historique(v=42)
        Alerte.objects.filter(pk=h.pk).update(message="0,4 × la médiane des 5 exercices précédents.", textes={})
        h.refresh_from_db()
        lisible = f"{h.valeur}, contre environ {formater(D(100), self.eff)} d'habitude (médiane des 5 exercices précédents)."
        self.assertEqual(CO.constat_lisible(h), lisible)
        self.client.force_login(self.contrib)
        liste = self.client.get(reverse("collecte:saisie") + f"?org={self.e1.id}").content.decode()
        panneau = self.client.get(self.url(), **FETCH).json()["html"]
        fiche = self.client.get(reverse("collecte:alerte", args=[h.pk])).content.decode()
        for html in (liste, panneau, fiche):
            self.assertNotIn("× la médiane", html)
            self.assertIn("d&#x27;habitude (médiane des 5 exercices précédents).", html)
        e = Alerte(campagne=self.c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.ECART_N1,
                   message="+160 % par rapport à N-1, sans commentaire.", valeur="260 salariés", reference="2025 : 100 salariés")
        self.assertEqual(CO.constat_lisible(e), "260 salariés, contre 100 salariés en 2025 : +160 %.")
        # ancien message au-dessus de la médiane : le rapport enregistré est repris (« 20 fois plus »), sans parenthèses
        # imbriquées pour une période non annuelle
        g = Alerte(campagne=self.c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.HISTORIQUE,
                   message="20,0 × la médiane des 5 années précédentes (même période).", valeur="120 accidents",
                   reference="médiane : 6 accidents")
        self.assertEqual(CO.constat_lisible(g), "120 accidents, contre environ 6 accidents d'habitude "
                                                "(médiane des 5 années précédentes, à la même période) : 20 fois plus.")
        self.assertEqual(CO._fois(D(3480000)), "3\u202f480\u202f000")

    def test_alerte_corrigee_entre_temps(self):
        """L'explication envoyée pour une alerte corrigée entre-temps (la valeur a changé) : rien n'est enregistré, un
        message le dit (role=status, qui reçoit le focus), au lieu d'un panneau muet."""
        a = self.historique()
        self.saisir(self.eff, 110)
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.CORRIGEE)
        res = self.justifier(a, "Inventaire").json()
        self.assertFalse(res["ok"])
        self.assertIn('class="encart encart-info" role="status" tabindex="-1" data-message-justif><strong class="encart-titre">Cette alerte n&#x27;a plus lieu', res["html"])
        a.refresh_from_db()
        self.assertEqual((a.statut, a.justification), (Alerte.Statut.CORRIGEE, ""))

    def test_alerte_rouverte_propose_le_commentaire(self):
        """Une alerte rouverte parce que la valeur a changé ne reprend pas son ancienne explication (qui ne vaut plus) :
        le commentaire est proposé ; une explication rejetée est reprise, et l'aide le dit."""
        self.c.seuil_ecart = None
        self.c.save()
        self.saisir(self.eff, 260, com="Rachat")
        a = self.alertes(controle="historique").get()
        CO.traiter(self.contrib, a, "justifier", "Ancienne explication")
        self.saisir(self.eff, 280, com="Rachat")
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.OUVERTE)
        self.client.force_login(self.contrib)
        html = self.client.get(self.url(), **FETCH).json()["html"]
        self.assertRegex(html, rf'<textarea id="justif-{a.pk}"[^>]*>Rachat</textarea>')
        CO.traiter(self.contrib, a, "justifier", "Nouvelle explication")
        CO.traiter(self.admin, a, "rejeter", "Préciser")
        html = self.client.get(self.url(), **FETCH).json()["html"]
        self.assertRegex(html, rf'aria-describedby="justif-{a.pk}-aide">Nouvelle explication</textarea>')
        self.assertIn("Reprise de l'explication rejetée", html)

    def test_aussi_a_justifier_dans_un_autre_referentiel(self):
        """la même case à justifier dans un autre référentiel de la même période ; on le signale."""
        from referentiel.models import Referentiel

        a = self.historique()
        autre = Referentiel.objects.create(code="AUTRE", nom="Autre référentiel", ordre=3)
        c2 = Campagne.objects.create(referentiel=autre, exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.assertEqual(c2.periode_id, self.c.periode_id)
        Alerte.objects.create(campagne=c2, kpi=self.eff, organisation=self.e1, controle=a.controle, message=a.message)
        self.client.force_login(self.contrib)
        html = self.client.get(self.url(), **FETCH).json()["html"]
        self.assertIn("Aussi à traiter dans « Autre référentiel »", html)

    def test_pleine_page_sans_javascript(self):
        """Pleine page (sans JavaScript) : le champ d'explication est là ; envoyé, la page revient avec le message ;
        vide, l'erreur s'affiche sous le champ sans perdre la page."""
        a = self.historique()
        self.client.force_login(self.contrib)
        self.assertContains(self.client.get(self.url()), "Expliquer pourquoi la valeur est juste")
        rep = self.client.post(self.url(), {"action": "justifier", "alerte": a.pk, "justification": ""})
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, "Saisissez une explication.")
        rep = self.client.post(self.url(), {"action": "justifier", "alerte": a.pk, "justification": "Inventaire"}, follow=True)
        self.assertContains(rep, "Explication enregistrée")
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.JUSTIFIEE)


class AlertesDansLaLangueDuLecteurTests(TestCase):
    """Le texte d'une alerte est recomposé dans la langue de la personne qui lit la page (constat, référence, valeur),
    pas figé dans la langue de l'installation au moment du contrôle."""

    setUp, saisir, alertes = CoherenceTests.setUp, CoherenceTests.saisir, CoherenceTests.alertes

    def test_constat_et_reference_traduits_a_l_affichage(self):
        from parametres import langues as L
        from parametres.libelles import libelle

        self.c.seuil_ecart = None
        self.c.save()
        self.saisir(self.eff, 260)
        self.saisir(self.form, 0)
        historique = self.alertes(controle="historique", kpi=self.eff).get()
        zero = self.alertes(controle="rupture", kpi=self.form).get()
        self.assertIn("fois plus", CO.constat_lisible(historique))  # français, comme avant
        with L.activer_interface("en"):
            self.assertEqual(CO.constat_lisible(zero), libelle("saisie.coherence.msg.rupture_zero"))
            self.assertNotIn("Valeur à 0", CO.constat_lisible(zero))
            en = CO.constat_lisible(historique)
            self.assertIn(libelle("saisie.coherence.constat.fois_plus", base="", fois="2.6").strip(" :"), en)
            self.assertNotIn("habitude", en)
            self.assertTrue(CO.texte_alerte(historique, "reference").startswith(libelle("saisie.coherence.ref.mediane", valeur="")))
        with L.activer_interface("es"):
            self.assertNotIn("habitude", CO.constat_lisible(historique))

    def test_page_coherence_en_anglais(self):
        self.saisir(self.form, 0)
        self.client.force_login(self.admin)
        self.client.post(reverse("langue"), {"langue": "en"})
        rep = self.client.get(reverse("collecte:coherence") + f"?campagne={self.c.pk}")
        self.assertEqual(rep.status_code, 200)
        page = rep.content.decode()
        self.assertIn("<h1>Data consistency", page)  # la page est bien celle de la cohérence, en anglais
        self.assertNotIn("Valeur à 0", page)


# ---------------------------------------------------------------- 3. règles de cohérence : organisations ouvertes
class CoherenceOrganisationsOuvertesTests(Base):
    """E1 fermé le 30/06/2026 : encore contrôlé sur 2026 (règle entre KPI, essai, contrôles automatiques) ; E2 fermé en
    2024 : plus contrôlé en 2026."""

    def setUp(self):
        super().setUp()
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.kpi("A")
        self.kpi("B")
        self.regle = RegleCoherence.objects.create(nom="A ≤ B", gauche="[A]", operateur="<=", droite="[B]", niveau_id=Niveau.ENTITY)
        for o, fin in ((self.e1, datetime.date(2026, 6, 30)), (self.e2, datetime.date(2024, 12, 31))):
            self.mettre("A", o, self.c.periode, 10)
            self.mettre("B", o, self.c.periode, -5)  # négatif : contrôle automatique (format)
            o.actif, o.date_desactivation = False, fin
            o.save()
        self.e3 = Organisation.objects.create(nom="E3", niveau_id=Niveau.ENTITY, parent=self.p)  # pour garder le pays ouvert
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)

    def test_regle_et_controles(self):
        CO.controler(self.c)
        regles = Alerte.objects.filter(campagne=self.c, controle=Alerte.Controle.REGLE).exclude(statut=Alerte.Statut.CORRIGEE)
        self.assertEqual([a.organisation for a in regles], [self.e1])
        formats = Alerte.objects.filter(campagne=self.c, controle=Alerte.Controle.FORMAT).exclude(statut=Alerte.Statut.CORRIGEE)
        self.assertEqual([a.organisation for a in formats], [self.e1])
        self.assertEqual([x["org"] for x in tester_regle(self.regle, self.c)], [self.e1, self.e3])  # essai de la règle
        bloquants = CO.regles_bloquantes_en_echec(self.c, KPI.objects.get(code="A"), self.e1)
        self.assertEqual(bloquants, [])  # règle non bloquante

    def test_alerte_d_une_organisation_fermee_consultable(self):
        CO.controler(self.c)
        a = Alerte.objects.get(campagne=self.c, controle=Alerte.Controle.REGLE, organisation=self.e1)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("collecte:coherence") + f"?campagne={self.c.pk}"), "A ≤ B")
        self.assertEqual(self.client.get(reverse("collecte:alerte", args=[a.pk])).status_code, 200)

    def test_essai_d_une_formule(self):
        from .reglages import tester_formule

        x = self.kpi("X", "Calculé", "[A] * 2")
        noms = [r["org"] for r in tester_formule(x, "[A] * 2", self.c)]
        self.assertEqual(noms, [self.e1, self.e3])
