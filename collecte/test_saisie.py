"""Page contributeur : saisie, N/A, écart N-1, preuves, statuts, droits (cahier des charges, sections 4.4 et 5.1 à 5.4)."""
import datetime
import json
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Attribution, Niveau, Organisation, Utilisateur

from . import reglages as R
from . import saisie as S
from .models import Campagne, Journal, Preuve, Reponse
from .aides_tests.saisie import Base, PDF, fichier
from .aides_tests.echanges import Base as BaseEchanges
from . import imports as I
from .aides_tests.aller_retour import Base as BaseAllerRetour

D = Decimal


class SaisieTests(Base):
    # -- périmètre ---------------------------------------------------------
    def test_perimetre_par_role(self):
        self.assertEqual({(k.code, o.nom) for k, o in S.cellules(self.contrib)}, {("EFF", "E1"), ("TX", "E1")})
        self.assertEqual({(k.code, o.nom) for k, o in S.cellules(self.valid)}, {("EFF", "E1"), ("EFF", "E2")})
        self.assertEqual(len(S.cellules(self.admin)), 4)  # 2 KPI saisis × 2 entités ; le KPI calculé n'apparaît pas
        self.assertEqual(S.cellules(self.autre), [])

    def test_hors_perimetre_refuse(self):
        with self.assertRaises(PermissionDenied):
            self.enregistrer("10", user=self.autre)
        with self.assertRaises(PermissionDenied):
            self.enregistrer("10", org=self.e2)

    # -- valeur, pourcentage, statuts -----------------------------------------
    def test_saisie_brouillon_puis_validation(self):
        r = self.enregistrer("1 234,5")
        self.assertEqual((r.valeur, r.statut, r.origine), (D("1234.5"), Reponse.Statut.BROUILLON, Reponse.Origine.SAISIE))
        r = S.valider(self.contrib, self.c, self.eff, self.e1)
        self.assertEqual((r.statut, r.valide_par), (Reponse.Statut.VALIDE, self.contrib))
        self.assertTrue(Journal.objects.filter(objet="Reponse", objet_id=str(r.pk), champ="statut", apres="valide").exists())

    def test_valeur_vide_reste_a_saisir_et_ne_se_valide_pas(self):
        r = self.enregistrer("", com="en attente")
        self.assertEqual(r.statut, Reponse.Statut.A_SAISIR)
        with self.assertRaises(ValidationError):
            S.valider(self.contrib, self.c, self.eff, self.e1)

    def test_pas_de_saisie_hors_du_referentiel_de_la_campagne(self):
        """Une adresse forgée vers une campagne dont le référentiel ne contient pas le KPI est refusée (avant : la
        valeur s'enregistrait sur une période où le KPI n'est pas collecté)."""
        from referentiel.models import ElementReferentiel, Referentiel

        autre = Referentiel.objects.create(code="AUTRE", nom="Autre")
        ElementReferentiel.objects.create(referentiel=autre, kpi=self.taux)
        c = Campagne.objects.create(referentiel=autre, periode=self.c.periode, statut=Campagne.Statut.OUVERTE)
        self.assertFalse(S.droits(self.contrib, c, self.eff, self.e1).voir)
        self.assertTrue(S.droits(self.contrib, c, self.taux, self.e1).modifier)
        self.client.force_login(self.contrib)
        url = reverse("collecte:cellule", args=[c.pk, self.eff.pk, self.e1.pk])
        self.assertEqual(self.client.post(url, {"action": "valider", "valeur": "1"}).status_code, 403)

    def test_nombre_trop_grand_refuse_clairement(self):
        """Plus de 15 chiffres avant la virgule : message clair au lieu d'une erreur 500 à l'enregistrement ; un KPI
        calculé dont le résultat dépasse passe en erreur nommée au lieu de faire échouer la saisie."""
        with self.assertRaisesMessage(ValidationError, "Ce nombre est trop grand"):
            self.enregistrer("999999999999999999999")
        self.assertEqual(self.enregistrer("999999999999999").valeur, D("999999999999999"))  # DBL = EFF × 2 dépasse
        dbl = Reponse.objects.get(periode=self.c.periode, kpi=self.calc, organisation=self.e1)
        self.assertEqual((dbl.valeur, dbl.statut), (None, Reponse.Statut.ERREUR))
        self.assertIn("trop grand", dbl.message_calcul)

    def test_valeur_non_numerique(self):
        with self.assertRaises(ValidationError):
            self.enregistrer("douze")

    def test_pourcentage_entre_0_et_100_stocke_en_fraction(self):
        r = self.enregistrer("25", kpi=self.taux)
        self.assertEqual(r.valeur, D("0.25"))
        self.assertEqual(S.valeur_pour_saisie(r, self.taux), "25")
        with self.assertRaises(ValidationError):
            self.enregistrer("120", kpi=self.taux)

    def test_modification_d_une_reponse_validee_repasse_en_brouillon(self):
        self.enregistrer("10")
        S.valider(self.contrib, self.c, self.eff, self.e1)
        r = self.enregistrer("10")  # inchangé : reste validé
        self.assertEqual(r.statut, Reponse.Statut.VALIDE)
        r = self.enregistrer("11")
        self.assertEqual((r.statut, r.valide_par), (Reponse.Statut.BROUILLON, None))
        self.assertTrue(Journal.objects.filter(champ="valeur", avant__startswith="10", apres="11").exists())

    def test_saisie_declenche_le_recalcul(self):
        self.enregistrer("7")
        self.assertEqual(Reponse.objects.get(kpi=self.calc, organisation=self.e1, periode=self.c.periode).valeur, D(14))

    # -- N/A et commentaire ----------------------------------------------------
    def test_na_exige_un_commentaire_et_se_valide(self):
        r = self.enregistrer("10", na=True)
        self.assertIsNone(r.valeur)
        self.assertTrue(r.non_applicable)
        with self.assertRaisesMessage(ValidationError, "commentaire"):
            S.valider(self.contrib, self.c, self.eff, self.e1)
        self.enregistrer("", na=True, com="Pas de salarié sur ce périmètre")
        self.assertEqual(S.valider(self.contrib, self.c, self.eff, self.e1).statut, Reponse.Statut.VALIDE)

    def test_ecart_n1_au_dela_du_seuil_exige_un_commentaire(self):
        Reponse.objects.create(periode=self.c0.periode, kpi=self.eff, organisation=self.e1, valeur=D(100), origine=Reponse.Origine.IMPORT)
        self.c.seuil_ecart = D("0.2")
        self.c.save()
        self.enregistrer("150")
        ligne = next(l for l in S.lignes(self.contrib, self.c) if l.kpi == self.eff)
        self.assertEqual(ligne.ecart, D("0.5"))
        self.assertEqual(ligne.n1.valeur, D(100))
        with self.assertRaisesMessage(ValidationError, "écart"):
            S.valider(self.contrib, self.c, self.eff, self.e1)
        self.enregistrer("150", com="Acquisition d'une filiale")
        self.assertEqual(S.valider(self.contrib, self.c, self.eff, self.e1).statut, Reponse.Statut.VALIDE)

    def test_ecart_sous_le_seuil_ou_sans_seuil(self):
        Reponse.objects.create(periode=self.c0.periode, kpi=self.eff, organisation=self.e1, valeur=D(100), origine=Reponse.Origine.IMPORT)
        self.enregistrer("300")
        S.valider(self.contrib, self.c, self.eff, self.e1)  # pas de seuil réglé : pas de contrôle
        self.c.seuil_ecart = D("0.2")
        self.c.save()
        self.enregistrer("110", kpi=self.eff)
        self.assertEqual(S.valider(self.contrib, self.c, self.eff, self.e1).statut, Reponse.Statut.VALIDE)

    # -- preuves ----------------------------------------------------------------
    def test_preuve_obligatoire_bloque_la_validation(self):
        self.eff.preuve_obligatoire = True
        self.eff.save()
        self.enregistrer("10")
        with self.assertRaisesMessage(ValidationError, "preuve"):
            S.valider(self.contrib, self.c, self.eff, self.e1)
        p = S.ajouter_preuve(self.contrib, self.c, self.eff, self.e1, fichier())
        self.assertEqual((p.nom_fichier, p.taille), ("preuve.pdf", len(PDF)))
        self.assertEqual(S.valider(self.contrib, self.c, self.eff, self.e1).statut, Reponse.Statut.VALIDE)
        S.retirer_preuve(self.contrib, p)  # retirer une preuve modifie la réponse : retour en brouillon
        r = Reponse.objects.get(pk=p.reponse_id)
        self.assertEqual(r.statut, Reponse.Statut.BROUILLON)
        self.assertFalse(r.preuves.exists())

    def test_preuve_non_requise_si_na(self):
        self.eff.preuve_obligatoire = True
        self.eff.save()
        self.enregistrer("", na=True, com="Non concerné")
        self.assertEqual(S.valider(self.contrib, self.c, self.eff, self.e1).statut, Reponse.Statut.VALIDE)

    def test_formats_et_taille_des_preuves(self):
        with self.assertRaisesMessage(ValidationError, "format de fichier n'est pas accepté"):
            S.ajouter_preuve(self.contrib, self.c, self.eff, self.e1, fichier("tableau.xlsx", b"x", "application/octet-stream"))
        with self.assertRaisesMessage(ValidationError, "5 Mo"):
            S.ajouter_preuve(self.contrib, self.c, self.eff, self.e1, fichier("gros.pdf", b"0" * (5 * 1024 * 1024 + 1)))
        S.ajouter_preuve(self.contrib, self.c, self.eff, self.e1, fichier("photo.JPG", b"\xff\xd8\xff\xe0jpg", "image/jpeg"))
        S.ajouter_preuve(self.contrib, self.c, self.eff, self.e1, fichier("scan.png", b"\x89PNG\r\n\x1a\npng", "image/png"))
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        self.assertEqual(r.preuves.count(), 2)
        self.assertEqual(r.statut, Reponse.Statut.A_SAISIR)  # une preuve seule ne fait pas une réponse

    # -- retour en brouillon et date de fin ---------------------------------------
    def test_retour_en_brouillon_et_lecture_seule_apres_la_date_de_fin(self):
        self.enregistrer("10")
        S.valider(self.contrib, self.c, self.eff, self.e1)
        S.repasser_brouillon(self.contrib, self.c, self.eff, self.e1)
        S.valider(self.contrib, self.c, self.eff, self.e1)
        self.c.date_fin_saisie = timezone.localdate() - datetime.timedelta(days=1)
        self.c.save()
        for action in (lambda: self.enregistrer("12"), lambda: S.repasser_brouillon(self.contrib, self.c, self.eff, self.e1)):
            with self.assertRaises(PermissionDenied):
                action()
        S.repasser_brouillon(self.valid, self.c, self.eff, self.e1)  # le validateur le peut à tout moment
        self.enregistrer("12", user=self.admin)  # l'admin saisit même après la date de fin
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1).valeur, D(12))

    def test_progression(self):
        self.enregistrer("10")
        S.valider(self.contrib, self.c, self.eff, self.e1)
        self.assertEqual(S.progression(S.lignes(self.contrib, self.c)), (1, 2))


class PageContributeurTests(Base):
    """Parcours par l'interface web."""

    FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}

    def setUp(self):
        super().setUp()
        self.client.force_login(self.contrib)
        self.url = reverse("collecte:cellule", args=[self.c.pk, "EFF", self.e1.id])

    def test_connexion_obligatoire(self):
        self.client.logout()
        self.assertRedirects(self.client.get(reverse("collecte:saisie")), "/connexion/?next=/saisie/", fetch_redirect_response=False)

    def test_accueil_selon_le_role(self):
        self.assertRedirects(self.client.get("/"), reverse("collecte:pour_moi"), fetch_redirect_response=False)
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get("/"), reverse("collecte:saisie"), fetch_redirect_response=False)

    def test_un_onglet_saisie_deux_vues(self):
        """Saisie et Pour moi fusionnés : un seul onglet « Saisie », deux vues (une organisation à la fois,
        tout ce qui m'est attribué) ; l'onglet et l'accueil rouvrent la dernière vue choisie."""
        saisie, flux = reverse("collecte:saisie"), reverse("collecte:pour_moi")
        for chemin, actuelle in ((saisie, saisie), (flux, flux)):
            html = self.client.get(chemin).content.decode()
            self.assertNotIn("Pour moi", html)
            # plus de boutons de vue ; « Tout ce qui m'est attribué » en tête du sélecteur d'organisation
            self.assertNotIn('aria-label="Vue de la saisie"', html)
            self.assertIn(f'<a href="{flux}" class="{"actuelle" if actuelle == flux else ""}"', html)
            self.assertIn("Tout ce qui m'est attribué", html)
            self.assertIn(f'<a href="{actuelle}" aria-current="page" class="actif">', html)  # l'onglet rouvre cette vue
            self.assertRedirects(self.client.get("/"), actuelle, fetch_redirect_response=False)
        # l'administrateur commence par une organisation à la fois, puis garde son choix
        self.client.force_login(self.admin)
        self.assertIn(f'<a href="{saisie}"', self.client.get(reverse("collecte:tableau_de_bord")).content.decode())
        self.client.get(flux)
        self.assertRedirects(self.client.get("/"), flux, fetch_redirect_response=False)
        self.assertIn(f'<a href="{flux}"', self.client.get(reverse("collecte:tableau_de_bord")).content.decode())

    def test_auditeur_une_seule_vue(self):
        """L'auditeur (lecture seule) n'a que « une organisation à la fois » : pas de bascule, l'onglet y mène."""
        auditeur = Utilisateur.objects.create(username="audit", email="audit@exemple.test", role=Utilisateur.Role.AUDITEUR)
        self.client.force_login(auditeur)
        html = self.client.get(reverse("collecte:saisie")).content.decode()
        self.assertNotIn('aria-label="Vue de la saisie"', html)
        self.assertNotIn(reverse("collecte:pour_moi"), html)
        self.assertRedirects(self.client.get("/"), reverse("collecte:saisie"), fetch_redirect_response=False)

    def test_saisie_une_organisation_a_la_fois(self):
        Reponse.objects.create(periode=self.c0.periode, kpi=self.eff, organisation=self.e1, valeur=D(80), origine=Reponse.Origine.IMPORT)
        self.enregistrer("100")
        rep = self.client.get(reverse("collecte:saisie") + f"?org={self.e1.id}")
        self.assertEqual([o for o, *_ in rep.context["orgs"]], [self.e1])  # le contributeur n'a que E1
        self.assertContains(rep, "Effectif")
        self.assertContains(rep, ">100,00<")  # valeur sans unité…
        self.assertContains(rep, ">ETP<")     # …et unité dans sa propre colonne
        self.assertContains(rep, "+25,0\u202f%")
        self.assertNotContains(rep, "Double")  # KPI calculé invisible pour un contributeur

    def test_parcours_du_contributeur(self):
        """Ce qui reste à faire en tête, colonnes utiles seulement, puis « Tout est fait » une fois tout validé."""
        rep = self.client.get(reverse("collecte:saisie") + f"?org={self.e1.id}")
        self.assertContains(rep, 'href="#liste" data-commencer')
        self.assertContains(rep, "à saisir")
        for colonne in ("<th>SPOC</th>", ">Preuves</th>", ">Type</th>"):
            self.assertNotContains(rep, colonne)
        self.assertNotContains(rep, 'class="tout-fait"')
        for kpi, v in ((self.eff, "100"), (self.taux, "50")):
            self.enregistrer(v, kpi=kpi)
            S.valider(self.contrib, self.c, kpi, self.e1)
        rep = self.client.get(reverse("collecte:saisie") + f"?org={self.e1.id}")
        self.assertContains(rep, 'class="tout-fait"')
        self.assertNotContains(rep, 'href="#liste" data-commencer')
        # une alerte de cohérence attend une justification : pas encore « tout est fait »
        from .models import Alerte

        alerte = Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.ECART_N1, message="Écart")
        rep = self.client.get(reverse("collecte:saisie") + f"?org={self.e1.id}")
        self.assertContains(rep, "alerte de cohérence à traiter")
        self.assertNotContains(rep, 'class="tout-fait"')
        alerte.statut = Alerte.Statut.JUSTIFIEE
        alerte.save()
        self.assertContains(self.client.get(reverse("collecte:saisie") + f"?org={self.e1.id}"), 'class="tout-fait"')
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:saisie") + f"?org={self.e1.id}")
        self.assertContains(rep, "<th>SPOC</th>")
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:saisie") + f"?org={self.e2.id}")
        self.assertEqual({l.organisation for _, ss in rep.context["sections"] for _, ls in ss for l in ls}, {self.e2})

    def test_remettre_a_saisir(self):
        """Demande : ramener une case au stade « à saisir » (pas seulement en brouillon). La valeur et le N/A
        s'effacent, le commentaire reste ; une valeur validée perd sa validation ; noté au journal ; le calcul suit."""
        self.enregistrer("100", com="Source : paie")
        S.valider(self.contrib, self.c, self.eff, self.e1)
        dbl = Reponse.objects.get(periode=self.c.periode, kpi=self.calc, organisation=self.e1)
        self.assertEqual(dbl.valeur, D(200))
        rep = self.client.get(self.url, **self.FETCH).json()["html"]
        self.assertIn('value="a_saisir"', rep)
        self.assertIn("data-confirmer=", rep)
        rep = self.client.post(self.url, {"action": "a_saisir"}, **self.FETCH).json()
        self.assertIn("la case est de nouveau à saisir", rep["html"])
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        self.assertEqual((r.statut, r.valeur, r.non_applicable, r.commentaire, r.valide_par), (Reponse.Statut.A_SAISIR, None, False, "Source : paie", None))
        self.assertTrue(Journal.objects.filter(objet_id=r.pk, champ="statut", apres=Reponse.Statut.A_SAISIR).exists())
        dbl.refresh_from_db()
        self.assertIsNone(dbl.valeur)  # le KPI calculé qui la cite est refait
        # un brouillon N/A aussi ; plus rien à effacer ensuite
        self.enregistrer("", na=True, com="Pas de salariés")
        S.remettre_a_saisir(self.contrib, self.c, self.eff, self.e1)
        r.refresh_from_db()
        self.assertEqual((r.statut, r.non_applicable), (Reponse.Statut.A_SAISIR, False))
        with self.assertRaises(ValidationError):
            S.remettre_a_saisir(self.contrib, self.c, self.eff, self.e1)
        self.assertNotIn('value="a_saisir"', self.client.get(self.url, **self.FETCH).json()["html"])
        # même droit que modifier la valeur : hors périmètre ou campagne close, refusé
        self.enregistrer("5")
        with self.assertRaises(PermissionDenied):
            S.remettre_a_saisir(self.autre, self.c, self.eff, self.e1)
        Campagne.objects.filter(pk=self.c.pk).update(statut=Campagne.Statut.CLOTUREE)
        self.c.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            S.remettre_a_saisir(self.admin, self.c, self.eff, self.e1)

    def test_admin_voit_les_kpi_calcules_en_lecture_seule(self):
        self.enregistrer("7")
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:saisie") + f"?org={self.e1.id}&calc=1")
        self.assertContains(rep, "Double")
        calc = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "DBL", self.e1.id]), **self.FETCH).json()["html"]
        self.assertIn("Composantes du calcul", calc)
        self.assertIn("14,00", calc)
        self.assertNotIn('name="valeur"', calc)
        rep = self.client.get(reverse("collecte:saisie") + f"?org={self.p.id}&calc=1")  # agrégats au niveau pays
        self.assertContains(rep, "Consolidé")  # « Agrégé » renommé 

    def test_pour_moi_et_tableau_de_bord(self):
        composer({"EFF": ["Social"], "TX": ["Social"], "DBL": ["Social"]})
        self.enregistrer("10")
        S.valider(self.contrib, self.c, self.eff, self.e1)
        rep = self.client.get(reverse("collecte:pour_moi"))
        self.assertEqual(rep.context["compteur"].total, 2)
        self.assertContains(rep, "E1")
        self.assertContains(self.client.get(reverse("collecte:pour_moi") + "?groupe=theme"), "Social")
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("collecte:pour_moi")).context["compteur"].total, 0)  # rien d'attribué à l'admin
        rep = self.client.get(reverse("collecte:tableau_de_bord"))
        tdb = rep.context
        self.assertEqual((tdb["total"].valide, tdb["total"].total), (1, 4))
        par_org = dict(tdb["par_org"])
        self.assertEqual((par_org[self.e1].valide, par_org[self.e1].total), (1, 2))
        self.assertEqual(par_org[self.g].total, 4)  # le groupe compte toutes les cellules rattachées
        par_spoc = dict(tdb["par_spoc"])
        self.assertEqual(par_spoc[self.contrib].total, 2)
        self.assertEqual(par_spoc[None].total, 2)  # cellules de E2 sans SPOC
        self.assertContains(rep, "Sans SPOC")

    def test_panneau_saisie_sans_quitter_la_page(self):
        Reponse.objects.create(periode=self.c0.periode, kpi=self.eff, organisation=self.e1, valeur=D(80), commentaire="Fichier historique",
                               origine=Reponse.Origine.IMPORT)
        html = self.client.get(self.url, **self.FETCH).json()["html"]
        self.assertIn("Historique par exercice", html)
        self.assertIn("2025", html)
        res = self.client.post(self.url, {"action": "valider", "valeur": "90", "commentaire": ""}, **self.FETCH).json()
        self.assertTrue(res["ok"])
        self.assertIn("Saisie validée", res["html"])
        cle = f"EFF|{self.e1.id}"
        self.assertIn("statut-valide", res["lignes"][cle])  # la ligne du tableau est mise à jour
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        self.assertEqual((r.valeur, r.statut), (D(90), Reponse.Statut.VALIDE))

    def test_panneau_erreur_conserve_la_saisie(self):
        res = self.client.post(self.url, {"action": "enregistrer", "valeur": "abc", "commentaire": "à garder"}, **self.FETCH).json()
        self.assertFalse(res["ok"])
        self.assertIn("pas un nombre. Saisissez un nombre.", res["html"])
        self.assertIn("à garder", res["html"])
        self.assertFalse(Reponse.objects.exists())

    def test_panneau_question_avant_fermeture(self):
        """le formulaire de la case est gardé ; la question à trois choix est prête, cachée, nommée (alertdialog)."""
        html = self.client.get(self.url, **self.FETCH).json()["html"]
        self.assertIn("data-garde", html)
        self.assertNotIn("data-non-enregistre", html)
        self.assertIn('role="alertdialog" aria-modal="true" aria-labelledby="question-fermeture-titre"', html)
        self.assertIn('data-texte-lien="Ouvrir le lien sans enregistrer"', html)  # question venue d'un lien du panneau
        self.assertNotIn("aria-invalid", html)
        self.assertNotIn("erreurs-saisie", html)
        self.assertIn("Cette saisie n'est pas enregistrée", html)
        self.assertNotIn("{#", html)  # aucun commentaire de gabarit affiché tel quel
        for choix in ("Enregistrer le brouillon et fermer", "Fermer sans enregistrer", "Continuer la saisie"):
            self.assertIn(choix, html)
        self.assertNotIn("Vous devez la valider à nouveau", html)
        # valeur validée : enregistrer la modification la repasse en brouillon, la question le dit (E2)
        self.enregistrer("90")
        S.valider(self.contrib, self.c, self.eff, self.e1)
        html = self.client.get(self.url, **self.FETCH).json()["html"]
        self.assertIn("Enregistrer la modification et fermer", html)
        self.assertIn("Vous devez la valider à nouveau", html)
        self.assertNotIn("Enregistrer le brouillon et fermer", html)
        # case en lecture seule ou calculée : rien à perdre, pas de question
        self.client.force_login(self.admin)
        calc = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "DBL", self.e1.id]), **self.FETCH).json()["html"]
        self.assertNotIn("data-question", calc)
        self.c.statut = Campagne.Statut.CLOTUREE
        self.c.save()
        self.assertNotIn("data-question", self.client.get(self.url, **self.FETCH).json()["html"])

    def test_panneau_non_enregistre_seulement_si_la_saisie_n_est_pas_en_base(self):
        """Le repère « Pas encore enregistré » vient du serveur quand il a refusé la saisie et qu'elle n'est pas en base."""
        res = self.client.post(self.url, {"action": "enregistrer", "valeur": "abc", "commentaire": "à garder", "version": ""}, **self.FETCH).json()
        self.assertEqual((res["ok"], res["enregistre"]), (False, False))
        self.assertIn("data-non-enregistre", res["html"])
        self.assertIn(">Pas encore enregistré<", res["html"])
        # lecteur d'écran : la valeur refusée est marquée invalide et décrite par le motif, lu avec le champ qui a le focus
        self.assertIn('id="erreurs-saisie"', res["html"])
        self.assertIn("Non enregistré", res["html"])  # rien n'est en base : l'étiquette le dit
        self.assertNotIn("Bloque la validation", res["html"])
        self.assertNotIn("Remplacer par ma saisie", res["html"])  # pas de conflit de version
        self.assertRegex(res["html"], r'id="valeur"[^>]*aria-invalid="true" aria-describedby="erreurs-saisie"')
        self.assertRegex(res["html"], r'id="commentaire"[^>]*aria-describedby="erreurs-saisie"')
        res = self.client.post(self.url, {"action": "enregistrer", "valeur": "12", "commentaire": "", "version": ""}, **self.FETCH).json()
        self.assertEqual((res["ok"], res["enregistre"]), (True, True))
        self.assertNotIn("data-non-enregistre", res["html"])
        self.assertNotIn("Pas encore enregistré", res["html"])
        # « Valider » refusé (N/A sans commentaire) : le brouillon, lui, est en base ; rien n'est « non enregistré »
        version = S.version(S.reponse_de(self.c, self.eff, self.e1))
        res = self.client.post(self.url, {"action": "valider", "non_applicable": "on", "commentaire": "", "version": version}, **self.FETCH).json()
        self.assertEqual((res["ok"], res["enregistre"]), (False, True))
        self.assertIn("Si vous cochez N/A, saisissez un commentaire.", res["html"])
        self.assertIn("Bloque la validation", res["html"])
        self.assertNotIn("Non enregistré", res["html"])
        self.assertNotIn("data-non-enregistre", res["html"])
        self.assertIn('aria-describedby="erreurs-saisie"', res["html"])  # le motif est lu avec le commentaire
        self.assertNotIn("aria-invalid", res["html"])  # la valeur elle-même n'est pas en cause
        r = S.reponse_de(self.c, self.eff, self.e1)
        self.assertEqual((r.non_applicable, r.statut), (True, Reponse.Statut.BROUILLON))
        # page complète (sans JavaScript) : même repère après un refus
        rep = self.client.post(self.url, {"action": "enregistrer", "valeur": "abc", "commentaire": "", "version": S.version(r)})
        self.assertContains(rep, "data-non-enregistre")

    def test_phrase_sous_valider(self):
        """E14 : une phrase sous « Valider » dit ce qu'il engage, lue avec le bouton ; pas de phrase sans bouton « Valider ».
         plus affichée à l'écran (jugée inutile), gardée pour les lecteurs d'écran."""
        phrase = "Valider confirme que votre saisie est complète, et un administrateur peut encore la rouvrir."
        html = self.client.get(self.url, **self.FETCH).json()["html"]
        self.assertIn(f'<p class="aide-valider visuellement-cache" id="aide-valider">{phrase}</p>', html)
        self.assertIn('value="valider" aria-describedby="aide-valider"', html)
        self.assertEqual(html.count(phrase), 1)  # pas d'info-bulle en double pour les lecteurs d'écran
        self.assertLessEqual(len(phrase.split()), 20)
        self.assertContains(self.client.get(self.url), phrase)  # pleine page aussi
        self.c.statut = Campagne.Statut.REVUE
        self.c.save()
        self.assertNotIn(phrase, self.client.get(self.url, **self.FETCH).json()["html"])

    def test_accessibilite_evitement_titres_et_pastilles(self):
        """Étape 6 : lien « Aller au contenu » en tête du bandeau vers <main id="contenu">, vrais titres de section (h2 sur
        Saisie et Pour moi), pastilles de filtre avec
        aria-pressed et zone d'annonce du nombre de lignes hors du bandeau relu après chaque enregistrement."""
        composer({"EFF": ["Social"], "TX": ["Social"]})
        html = self.client.get(reverse("collecte:saisie")).content.decode()
        evitement = html.index('<a class="lien-evitement" href="#contenu">Aller au contenu</a>')
        self.assertLess(html.index('<header class="haut">'), evitement)
        self.assertLess(evitement, html.index('<div class="barre-haut">'))  # premier arrêt du clavier
        self.assertIn('<main id="contenu" tabindex="-1">', html)
        # second lien, juste après : « Aller aux KPI » (la liste peut recevoir le focus)
        liste = html.index('<a class="lien-evitement" href="#liste">Aller aux KPI</a>')
        self.assertLess(evitement, liste)
        self.assertLess(liste, html.index('<div class="barre-haut">'))
        self.assertIn('<div id="liste" tabindex="-1">', html)
        self.assertIn('<h2 class="titre-section">Social</h2>', html)
        self.assertIn('data-filtre-statut="" aria-pressed="true"', html)
        for statut in ("valide", "brouillon", "a_saisir"):
            self.assertIn(f'data-filtre-statut="{statut}" aria-pressed="false"', html)
        # l'annonce est après la fin du bloc #resume (remplacé à chaque enregistrement), pas dedans
        self.assertEqual(html.count('id="annonce-filtres"'), 1)
        self.assertLess(html.index('<div class="progression"'), html.index('id="annonce-filtres"'))
        self.assertIn('<p id="annonce-filtres" class="visuellement-cache" role="status" aria-live="polite"></p>', html)
        pour_moi = self.client.get(reverse("collecte:pour_moi") + "?tous=0").content.decode()
        self.assertIn('<h2 class="titre-section">', pour_moi)
        self.assertIn('<a class="lien-evitement" href="#liste">Aller aux KPI</a>', pour_moi)
        # rien d'attribué : pas de liste, pas de lien vers elle
        self.client.force_login(Utilisateur.objects.create(username="sans_kpi", email="sans_kpi@exemple.test"))
        for page in ("collecte:saisie", "collecte:pour_moi"):
            self.assertNotContains(self.client.get(reverse(page)), 'href="#liste"')
        # « Tous mes référentiels » (h3 sous le h2 de chaque référentiel) : test_navigateur_saisie, deux référentiels

    def test_ecart_sous_la_valeur_au_dela_du_seuil(self):
        """E13 : au-delà du seuil, l'écart avec N-1 est répété sous la valeur (affiché sur tablette et téléphone, où sa
        colonne est masquée) ; rien en deçà du seuil ni sans seuil."""
        composer({"EFF": ["Social"]})
        Reponse.objects.create(periode=self.c0.periode, kpi=self.eff, organisation=self.e1, valeur=D(100), origine=Reponse.Origine.IMPORT)
        self.enregistrer("150")
        page = self.client.get(reverse("collecte:saisie") + f"?org={self.e1.id}")
        self.assertNotContains(page, 'class="ecart-sous"')  # pas de seuil réglé
        self.c.seuil_ecart = D("0.2")
        self.c.save()
        html = self.client.get(reverse("collecte:saisie") + f"?org={self.e1.id}").content.decode()
        self.assertIn('<div class="ecart-sous"><span class="visuellement-cache">Écart avec N-1 au-delà du seuil de la campagne : </span>', html)
        self.assertIn('<span class="ecart-fort"><span class="ecart-fleche" aria-hidden="true">▲</span>+50,0\u202f%</span>', html)
        self.enregistrer("110")
        self.assertNotContains(self.client.get(reverse("collecte:saisie") + f"?org={self.e1.id}"), 'class="ecart-sous"')

    def test_pleine_page_zone_a_toucher(self):
        """« Pleine page » a sa zone à toucher de 24 px (.lien-pleine-page). Les libellés visibles d'Import / Export et
        d'Administration (E15) se vérifient dans le navigateur (test_navigateur_saisie)."""
        panneau = self.client.get(self.url, **self.FETCH).json()["html"]
        self.assertIn('class="discret lien-pleine-page"', panneau)

    def test_page_complete_sans_javascript(self):
        rep = self.client.post(self.url, {"action": "valider", "valeur": "90", "commentaire": ""}, follow=True)
        self.assertContains(rep, "Saisie validée")
        rep = self.client.post(self.url, {"action": "enregistrer", "valeur": "abc", "commentaire": "à garder"})
        self.assertContains(rep, "pas un nombre. Saisissez un nombre.")
        self.assertContains(rep, "à garder")

    def test_depot_telechargement_et_retrait_de_preuve(self):
        self.client.post(self.url, {"action": "preuve", "fichier": fichier()}, **self.FETCH)
        p = Preuve.objects.get()
        self.assertEqual(b"".join(self.client.get(reverse("collecte:preuve", args=[p.pk])).streaming_content), PDF)
        self.client.force_login(self.autre)
        self.assertEqual(self.client.get(reverse("collecte:preuve", args=[p.pk])).status_code, 403)
        self.client.force_login(self.contrib)
        res = self.client.post(self.url, {"action": "retirer_preuve", "preuve": p.pk}, **self.FETCH).json()
        self.assertIn("Preuve supprimée", res["html"])
        self.assertFalse(Preuve.objects.exists())

    def test_cellule_interdite_hors_perimetre(self):
        self.assertEqual(self.client.get(reverse("collecte:cellule", args=[self.c.pk, "EFF", self.e2.id])).status_code, 403)
        self.assertEqual(self.client.get(reverse("collecte:cellule", args=[self.c.pk, "DBL", self.e1.id])).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)


class EtatsDuPerimetreTests(Base):
    """« Ce qui reste » (S.Reste) : même calcul sur Saisie, Pour moi, « Je réponds à » et la page Cohérence ; « Tout est
    fait » seulement quand tout le périmètre de la personne est fini, valeurs et alertes à justifier comprises."""

    def setUp(self):
        super().setUp()
        composer({"EFF": ["Social"], "TX": ["Social"]})

    def valider(self, kpi, org, v="10", user=None, **autres):
        user = user or self.contrib
        S.enregistrer(user, self.c, kpi, org, v, autres.get("na", False), autres.get("com", ""))
        S.valider(user, self.c, kpi, org)

    def saisie(self, user, **params):
        self.client.force_login(user)
        return self.client.get(reverse("collecte:saisie"), {"campagne": self.c.pk, **params})

    def alerte(self, kpi=None, org=None, **autres):
        from .models import Alerte

        return Alerte.objects.create(campagne=self.c, kpi=kpi or self.eff, organisation=org or self.e1,
                                     controle=autres.pop("controle", Alerte.Controle.FORMAT), message="Valeur négative.", **autres)

    def onglet(self, user):
        self.client.force_login(user)
        rep = self.client.get(reverse("collecte:pour_moi"), {"campagne": self.c.pk})
        return rep, next(o for o in rep.context["onglets"] if o["campagne"] == self.c)

    def je_reponds_a(self, user):
        self.client.force_login(user)
        rep = self.client.get(reverse("collecte:choix_reponse"), HTTP_X_REQUESTED_WITH="fetch")  # panneau de la barre du haut
        return rep, next((r, fermee) for b in rep.context["blocs"] for c, r, fermee in b["en_cours"] if c == self.c)

    def test_tout_est_fait_seulement_quand_tout_le_perimetre_est_fini(self):
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.contrib)
        rep = self.saisie(self.contrib, org=self.e1.id)
        b = rep.context["bandeau"]
        self.assertEqual(b["code"], "ici")  # A : il reste ici, et ailleurs
        self.assertEqual(b["ligne_ailleurs"], "Dans les autres organisations de votre périmètre, il reste 1 valeur dans 1 organisation.")
        self.assertNotContains(rep, "Aller à E2")  # pas de lien en ligne : le sélecteur d'organisation suffit
        self.valider(self.eff, self.e1)
        self.valider(self.taux, self.e1, "50")
        rep = self.saisie(self.contrib, org=self.e1.id)
        self.assertEqual(rep.context["bandeau"]["code"], "ailleurs")  # C : fini ici, il reste à E2
        self.assertNotContains(rep, 'class="tout-fait"')
        self.assertNotContains(rep, "<b>Tout est fait.</b>")
        self.assertContains(rep, "Il reste <b>1</b> valeur dans 1 organisation.")
        self.assertContains(rep, f'<a class="bouton" href="?org={self.e2.id}&amp;campagne={self.c.pk}">Aller à E2</a>')
        self.assertIn("Aller à E2", rep.context["bandeau"]["annonce"])
        self.valider(self.eff, self.e2)
        rep = self.saisie(self.contrib, org=self.e1.id)
        self.assertEqual(rep.context["bandeau"]["code"], "fini")  # E : tout le périmètre
        self.assertContains(rep, 'class="tout-fait"')
        self.assertContains(rep, "3 valeurs validées sur 3")
        # une alerte à justifier ailleurs : plus « Tout est fait » (D)
        self.alerte(org=self.e2)
        rep = self.saisie(self.contrib, org=self.e1.id)
        self.assertEqual(rep.context["bandeau"]["code"], "alertes_ailleurs")
        self.assertContains(rep, "Il reste <b>1</b> alerte à traiter dans 1 organisation.")
        self.assertNotContains(rep, 'class="tout-fait"')

    def test_alertes_ici_avant_le_compteur(self):
        """État B : testé avant le nombre de cases, une organisation sans case attendue peut avoir une alerte."""
        self.valider(self.eff, self.e1)
        self.valider(self.taux, self.e1, "50")
        a = self.alerte()
        rep = self.saisie(self.contrib, org=self.e1.id)
        self.assertEqual(rep.context["bandeau"]["code"], "alertes_ici")
        self.assertContains(rep, "tout est saisi · <b>1</b> alerte de cohérence à traiter")
        # « Justifier » ouvre la première ligne en alerte (data-justifier) ; sans JavaScript, la page Cohérence filtrée
        self.assertContains(rep, f"?campagne={self.c.pk}&amp;statut=a_traiter&amp;org={self.e1.id}\" data-justifier>Justifier</a>")
        # validateur : E1 n'a plus de case attendue (valeur saisie au niveau du pays) mais garde son alerte
        a.delete()
        self.eff.saisie_au_dessus = True
        self.eff.save()
        S.enregistrer(self.admin, self.c, self.eff, self.p, "100", False, "")
        self.alerte(org=self.e1)
        orgs = {o: (t, v, n) for o, t, v, n in S.organisations_visibles(self.valid, self.c)}
        self.assertEqual(orgs[self.e1], (0, 0, 1))
        rep = self.saisie(self.valid, org=self.e1.id)
        b = rep.context["bandeau"]
        self.assertEqual((b["code"], b["ici"].total, b["ici"].alertes), ("alertes_ici", 0, 1))
        self.assertContains(rep, "<b>1</b> alerte de cohérence à traiter")
        self.assertNotContains(rep, "tout est saisi")

    def test_organisation_par_defaut_ou_il_reste_quelque_chose(self):
        """sans organisation choisie, la première où il reste des valeurs, sinon des alertes ; un choix mémorisé tient."""
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.contrib)
        self.valider(self.eff, self.e1)
        self.valider(self.taux, self.e1, "50")
        self.client.force_login(self.contrib)
        session = self.client.session
        session["org"] = self.e1.id  # ancienne clé, écrite avant la mise à jour à chaque visite : ignorée
        session.save()
        self.assertEqual(self.saisie(self.contrib).context["org"], self.e2)
        self.assertNotIn("org_choisie", self.client.session)  # choix automatique : gardé pour cette campagne seulement
        self.assertEqual(self.client.session["org_par_campagne"], {str(self.c.pk): self.e2.id})
        self.saisie(self.contrib, org=self.e1.id)
        self.assertEqual(self.client.get(reverse("collecte:saisie")).context["org"], self.e1)  # choix mémorisé
        self.valider(self.eff, self.e2)
        self.alerte(org=self.e2)
        self.client.logout()
        self.assertEqual(self.saisie(self.contrib).context["org"], self.e2)  # plus de valeur : l'organisation de l'alerte

    def test_alerte_de_regle_dont_le_contributeur_ne_possede_que_le_2e_kpi(self):
        from .models import Alerte, RegleCoherence

        form = KPI.objects.create(code="FORM", libelle="Formés", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                  methode_agregation="Somme")
        composer({"FORM": ["Social"]})
        RegleCoherence.objects.create(nom="Formés ≤ effectif", gauche="[FORM]", operateur="<=", droite="[EFF]", niveau_id=Niveau.ENTITY)
        self.valider(form, self.e1, "120", user=self.admin)
        self.valider(self.eff, self.e1, "100")
        self.valider(self.taux, self.e1, "50")
        a = Alerte.objects.get(controle=Alerte.Controle.REGLE)
        self.assertEqual((a.kpi_id, a.kpis_concernes), ("FORM", "FORM EFF"))
        # mêmes chiffres partout, avant toute ouverture de la page Cohérence
        rep = self.saisie(self.contrib, org=self.e1.id)
        self.assertEqual((rep.context["bandeau"]["code"], rep.context["etat"].alertes), ("alertes_ici", 1))
        self.assertNotContains(rep, 'class="tout-fait"')
        self.assertContains(rep, 'data-alerte="1"')  # la ligne de son KPI montre l'alerte de la règle
        rep, o = self.onglet(self.contrib)
        self.assertEqual((o["etat"].valeurs, o["etat"].alertes, rep.context["bandeau"]["code"]), (0, 1, "alertes_ici"))
        rep, (r, fermee) = self.je_reponds_a(self.contrib)
        self.assertEqual((r.valeurs, r.alertes, fermee), (0, 1, False))
        self.assertContains(rep, "1 alerte à traiter")
        self.assertNotContains(rep, "tout est fait")
        rep = self.client.get(reverse("collecte:coherence"), {"campagne": self.c.pk})
        self.assertEqual(dict((c, n) for c, _, n in rep.context["statuts"])["a_traiter"], 1)
        self.assertContains(rep, "À traiter")
        # le panneau de la case du 2e KPI montre la règle
        html = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "EFF", self.e1.id]), HTTP_X_REQUESTED_WITH="fetch").json()["html"]
        self.assertIn("Formés ≤ effectif", html)

    def test_meme_nombre_d_alertes_sur_les_quatre_surfaces(self):
        """Pour les 3 rôles : bandeau de Saisie (tout le périmètre), Pour moi, « Je réponds à », tuile « À justifier » de
        la page Cohérence ; les calculs impossibles n'y comptent pas, alerte posée sur une organisation parente comprise."""
        from .models import Alerte

        self.alerte()  # E1 : contributeur, validateur, admin
        self.alerte(kpi=self.eff, org=self.e2)  # E2 : validateur et admin
        self.alerte(kpi=self.eff, org=self.p, controle=Alerte.Controle.DETAIL)  # au-dessus de la granularité : admin
        self.alerte(kpi=self.eff, org=self.e1, controle=Alerte.Controle.CALCUL, gravite=Alerte.Gravite.INFO)  # information
        self.alerte(kpi=self.taux, org=self.e1, statut=Alerte.Statut.JUSTIFIEE)  # déjà justifiée
        for user, attendu in ((self.contrib, 1), (self.valid, 2), (self.admin, 3)):
            with self.subTest(role=user.role):
                rep = self.saisie(user, org=self.e1.id)
                self.assertEqual(rep.context["etat"].alertes, attendu)
                rep, (r, _) = self.je_reponds_a(user)
                self.assertEqual(r.alertes, attendu)
                if user != self.admin:  # l'admin n'a rien d'attribué : Pour moi compte ses seules cases
                    rep, o = self.onglet(user)
                    self.assertEqual(o["etat"].alertes, attendu)
                # même source que la tuile « À justifier » de la page Cohérence (vérifiée sur une vraie règle ci-dessus :
                # son ouverture relance le contrôle, qui corrigerait ces alertes d'essai)
                from . import coherence as CO

                self.assertEqual(len(CO.alertes_a_traiter(user, self.c)), attendu)
        # tuile « À justifier » de la page Cohérence : campagne clôturée (son ouverture ne relance pas le contrôle)
        Campagne.objects.filter(pk=self.c.pk).update(statut=Campagne.Statut.CLOTUREE)
        for user, attendu in ((self.contrib, 1), (self.valid, 2), (self.admin, 3)):
            with self.subTest(role=user.role, surface="Cohérence"):
                self.client.force_login(user)
                rep = self.client.get(reverse("collecte:coherence"), {"campagne": self.c.pk})
                self.assertEqual(dict((c, n) for c, _, n in rep.context["statuts"])["a_traiter"], attendu)
                self.assertEqual(self.saisie(user, org=self.e1.id).context["etat"].alertes, attendu)

    def test_somme_par_organisation_egale_au_perimetre(self):
        """reste(lignes de chaque organisation) additionnés = reste_par_org, alerte au-dessus de la granularité comprise."""
        from . import coherence as CO
        from .models import Alerte

        self.eff.saisie_au_dessus = True
        self.eff.save()
        self.valider(self.eff, self.e1)
        self.alerte(org=self.p, controle=Alerte.Controle.DETAIL)
        self.alerte(org=self.e2)
        for user in (self.admin, self.valid, self.contrib):
            with self.subTest(role=user.role):
                orgs = S.organisations_visibles(user, self.c)
                total = S.reste_par_org(orgs)
                alertes = CO.alertes_a_traiter(user, self.c)
                parts = [S.reste(S.lignes(user, self.c, org=o, calculees=True), [a for a in alertes if a.organisation_id == o.id])
                         for o, *_ in orgs]
                somme = sum(parts, S.Reste())
                self.assertEqual((somme.total, somme.valide, somme.alertes), (total.total, total.valide, total.alertes))
                for o, *_ in orgs:
                    self.assertEqual((somme.ici(o).total, somme.ici(o).alertes), (total.ici(o).total, total.ici(o).alertes))
        self.assertEqual(S.reste_par_org(S.organisations_visibles(self.admin, self.c)).ici(self.p).alertes, 1)

    def test_coherence_calculs_impossibles_a_part(self):
        """La tuile « À justifier » de la page Cohérence a le nombre du bandeau ; les calculs impossibles sont à part."""
        from .models import Alerte

        self.alerte()
        self.alerte(kpi=self.calc, controle=Alerte.Controle.CALCUL, gravite=Alerte.Gravite.INFO)
        Campagne.objects.filter(pk=self.c.pk).update(statut=Campagne.Statut.CLOTUREE)  # pas de nouveau contrôle à l'ouverture
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:coherence"), {"campagne": self.c.pk})
        self.assertEqual(dict((c, n) for c, _, n in rep.context["statuts"])["a_traiter"], 1)
        self.assertEqual([a.controle for a in rep.context["alertes"]], [Alerte.Controle.FORMAT])
        self.assertNotIn(Alerte.Controle.CALCUL, [c for c, _, _ in rep.context["par_controle"]])
        self.assertContains(rep, "1 calcul impossible : information pour l'administrateur. Il n'y a rien à justifier.")
        rep = self.client.get(reverse("collecte:coherence"), {"campagne": self.c.pk, "controle": "calcul"})
        self.assertEqual([a.controle for a in rep.context["alertes"]], [Alerte.Controle.CALCUL])
        self.assertEqual(self.saisie(self.admin, org=self.e1.id).context["etat"].alertes, 1)

    def test_admin_avec_les_calcules_memes_chiffres(self):
        self.valider(self.eff, self.e1)
        self.alerte()
        sans = self.saisie(self.admin, org=self.e1.id, calc="0").context
        avec = self.saisie(self.admin, org=self.e1.id, calc="1").context
        self.assertTrue(avec["calculees"])
        for cle in ("code", "annonce"):
            self.assertEqual(sans["bandeau"][cle], avec["bandeau"][cle])
        self.assertEqual(vars(sans["compteur"]), vars(avec["compteur"]))
        self.assertEqual((sans["etat"].total, sans["etat"].alertes), (avec["etat"].total, avec["etat"].alertes))

    def test_valeur_na_validee_compte_comme_faite(self):
        self.valider(self.eff, self.e1, "", na=True, com="Pas d'effectif ici")
        self.valider(self.taux, self.e1, "50")
        rep = self.saisie(self.contrib, org=self.e1.id)
        self.assertEqual(rep.context["bandeau"]["code"], "fini")
        self.assertEqual((rep.context["etat"].valide, rep.context["etat"].total), (2, 2))

    def test_saisie_fermee(self):
        """État F : campagne en revue, date de fin passée, campagne clôturée ; Saisie, Pour moi et « Je réponds à »."""
        self.valider(self.eff, self.e1)
        hier = timezone.localdate() - datetime.timedelta(days=1)
        cas = [("revue", {"statut": Campagne.Statut.REVUE}, {self.contrib, self.valid}),
               ("date passée", {"date_fin_saisie": hier}, {self.contrib, self.valid}),
               ("clôturée", {"statut": Campagne.Statut.CLOTUREE}, {self.contrib, self.valid, self.admin})]
        for nom, champs, fermes in cas:
            Campagne.objects.filter(pk=self.c.pk).update(statut=Campagne.Statut.OUVERTE,
                                                          date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
            Campagne.objects.filter(pk=self.c.pk).update(**champs)
            for user in (self.contrib, self.valid, self.admin):
                with self.subTest(cas=nom, role=user.role):
                    rep = self.saisie(user, org=self.e1.id)
                    b = rep.context["bandeau"]
                    if user in fermes:
                        self.assertEqual(b["code"], "fermee")
                        if user == self.admin:  # les chiffres de l'organisation affichée, nommée ; le reste ailleurs
                            self.assertContains(rep, '<span class="a-faire-org">E1 :</span> <b>saisie fermée</b>, <b>1</b> valeur non validée.')
                            self.assertEqual(b["annonce"], "E1 : saisie fermée, 1 valeur non validée. "
                                                           "Dans les autres organisations de votre périmètre, il reste 2 valeurs non validées dans 1 organisation.")
                            b2 = self.saisie(user, org=self.p.id).context["bandeau"]  # aucune case au niveau du pays
                            self.assertTrue(b2["annonce"].startswith("Pays : saisie fermée, rien à saisir ici. Dans les autres organisations de votre périmètre, il reste 3 valeurs"))
                        else:
                            self.assertContains(rep, "Saisie fermée</b> : <b>1</b> valeur non validée")
                        self.assertNotContains(rep, "Aller à")
                        self.assertNotContains(rep, 'href="#liste" data-commencer')
                        self.assertNotContains(rep, ">Justifier</a>")  # aucune alerte à traiter
                    else:
                        self.assertNotEqual(b["code"], "fermee")
                    if user != self.admin:
                        rep, o = self.onglet(user)
                        self.assertEqual(o["lecture_seule"], user in fermes)
                        self.assertEqual(rep.context["bandeau"]["code"] == "fermee", user in fermes)
                    if nom != "clôturée":  # « Je réponds à » ne garde dans « en cours » que les campagnes ouvertes ou en revue
                        rep, (r, fermee) = self.je_reponds_a(user)
                        self.assertEqual(fermee, user in fermes)
                        self.assertEqual("saisie fermée" in rep.content.decode(), user in fermes)
                        # le statut de la campagne ne contredit pas l'état : jamais « saisie ouverte » à côté de « saisie fermée »
                        self.assertEqual("saisie ouverte" in rep.content.decode(), nom != "revue" and user not in fermes)
                        self.assertEqual("fin de saisie passée" in rep.content.decode(), nom == "date passée" and user in fermes)

    def test_saisie_fermee_garde_les_alertes_a_justifier(self):
        """État F : la justification reste possible après la fermeture ; même nombre d'alertes dans le bandeau, l'onglet,
        « Je réponds à » et la vue d'ensemble de Pour moi."""
        self.valider(self.eff, self.e1)
        self.alerte()
        Campagne.objects.filter(pk=self.c.pk).update(statut=Campagne.Statut.REVUE)
        for user in (self.contrib, self.valid):
            with self.subTest(role=user.role):
                rep = self.saisie(user, org=self.e1.id)
                b = rep.context["bandeau"]
                self.assertEqual((b["code"], b["fermees"].alertes), ("fermee", 1))
                self.assertIn("1 alerte à traiter dans 1 organisation", b["annonce"])  # tout le périmètre : où elle est
                self.assertContains(rep, "<b>1</b> alerte à traiter dans 1 organisation.")
                self.assertContains(rep, f'?campagne={self.c.pk}&amp;statut=a_traiter" data-justifier>Justifier</a>')
                self.assertNotContains(rep, "Aller à")
                rep, o = self.onglet(user)
                self.assertEqual((o["etat"].alertes, rep.context["bandeau"]["fermees"].alertes), (1, 1))
                self.assertEqual(rep.context["reste_tous"].alertes, 1)
                self.assertIn("1 alerte à traiter", rep.context["bandeau"]["annonce"])
                rep, (r, fermee) = self.je_reponds_a(user)
                self.assertEqual((r.alertes, fermee), (1, True))
                self.assertContains(rep, "saisie fermée")
                self.assertContains(rep, "1 alerte à traiter")
        Campagne.objects.filter(pk=self.c.pk).update(statut=Campagne.Statut.CLOTUREE)
        b = self.saisie(self.admin, org=self.e1.id).context["bandeau"]
        self.assertEqual(b["annonce"], "E1 : saisie fermée, 1 valeur non validée, 1 alerte à traiter. "
                                       "Dans les autres organisations de votre périmètre, il reste 2 valeurs non validées dans 1 organisation.")

    def test_alertes_ici_avec_ailleurs(self):
        """État B : l'aide et la ligne « Ailleurs » (avec « Aller à ») sont deux lignes ; les alertes disent où elles sont."""
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.contrib)
        self.valider(self.eff, self.e1)
        self.valider(self.taux, self.e1, "50")
        self.alerte()
        self.alerte(kpi=self.taux)
        self.alerte(org=self.e2)
        rep = self.saisie(self.contrib, org=self.e1.id)
        b = rep.context["bandeau"]
        ailleurs = "Dans les autres organisations de votre périmètre, il reste 1 valeur dans 1 organisation, 1 alerte à traiter dans 1 organisation."
        self.assertEqual((b["code"], b["ligne_ailleurs"]), ("alertes_ici", ailleurs))
        self.assertContains(rep, "Valeurs inhabituelles : corriger, ou expliquer pourquoi c'est juste.</span>")
        self.assertContains(rep, f'{ailleurs}</span>')
        self.assertNotContains(rep, 'Aller à E2</a>')

    def test_ailleurs_dit_ou_sont_les_alertes_et_annonce_en_majuscule(self):
        """État C : les alertes d'ailleurs disent dans combien d'organisations ; Pour moi (sans préfixe d'organisation) :
        la phrase annoncée commence par une majuscule."""
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.contrib)
        self.valider(self.eff, self.e1)
        self.valider(self.taux, self.e1, "50")
        self.alerte(org=self.e2)
        rep = self.saisie(self.contrib, org=self.e1.id)
        b = rep.context["bandeau"]
        self.assertEqual(b["code"], "ailleurs")
        self.assertIn("Il reste 1 valeur dans 1 organisation et 1 alerte à traiter dans 1 organisation.", b["annonce"])
        self.assertContains(rep, "et <b>1</b> alerte à traiter dans 1 organisation.")
        self.valider(self.eff, self.e2)
        self.alerte(org=self.e2)  # l'enregistrement relance les contrôles
        rep, _ = self.onglet(self.contrib)
        b = rep.context["bandeau"]
        self.assertEqual(b["code"], "alertes_ici")
        self.assertTrue(b["annonce"].startswith("Tout est saisi, 1 alerte"), b["annonce"])

    def test_tout_est_fait_et_etats_ailleurs_libelles(self):
        """« Tout est fait » dit qu'il porte sur toutes les organisations ; « fini ici » ne met en gras que le nom."""
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.contrib)
        self.valider(self.eff, self.e1)
        self.valider(self.taux, self.e1, "50")
        rep = self.saisie(self.contrib, org=self.e1.id)
        self.assertContains(rep, '<span class="a-faire-org">E1 :</span> plus rien à faire ici.')
        self.valider(self.eff, self.e2)
        rep = self.saisie(self.contrib, org=self.e1.id)
        self.assertContains(rep, "3 valeurs validées sur 3 dans vos 2 organisations pour")
        self.assertEqual(rep.context["bandeau"]["annonce"], "Tout est fait : 3 valeurs validées sur 3 dans vos 2 organisations.")

    def test_alerte_sur_une_organisation_inactive(self):
        """Admin : une alerte posée sur une organisation inactive compte dans le bandeau comme sur la page Cohérence,
        sans être proposée (« Aller à »)."""
        from . import coherence as CO

        for k in (self.eff, self.taux):
            self.valider(k, self.e1, "50", user=self.admin)
        self.alerte(org=self.e2)
        Organisation.objects.filter(pk=self.e2.pk).update(actif=False)
        rep = self.saisie(self.admin, org=self.e1.id)
        b = rep.context["bandeau"]
        self.assertEqual(rep.context["etat"].alertes, len(CO.alertes_a_traiter(self.admin, self.c)))
        self.assertEqual(rep.context["etat"].alertes, 1)
        self.assertEqual((b["code"], b["suivante"]), ("alertes_ailleurs", None))
        self.assertNotIn("Aller à", b["annonce"])
        self.assertContains(rep, f'href="{reverse("collecte:coherence")}?campagne={self.c.pk}&amp;statut=a_traiter">Justifier</a>')
        rep, (r, _) = self.je_reponds_a(self.admin)
        self.assertEqual(r.alertes, 1)

    def test_pour_moi_et_je_reponds_a_sans_rien_a_faire_quand_une_alerte_attend(self):
        self.valider(self.eff, self.e1)
        self.valider(self.taux, self.e1, "50")
        rep, o = self.onglet(self.contrib)
        self.assertTrue(o["etat"].fini)
        rep, (r, _) = self.je_reponds_a(self.contrib)
        self.assertContains(rep, "tout est fait")
        self.alerte()
        rep, o = self.onglet(self.contrib)
        self.assertFalse(o["etat"].fini)
        self.assertNotContains(rep, "rien à faire")
        self.assertNotContains(rep, 'class="tout-fait"')
        rep, (r, _) = self.je_reponds_a(self.contrib)
        self.assertContains(rep, "1 alerte à traiter")
        for texte in ("tout est validé", "tout est fait", "rien à saisir"):
            self.assertNotContains(rep, texte)

    def test_ligne_non_attendue_hors_de_la_chaine(self):
        self.eff.saisie_au_dessus = True
        self.eff.save()
        rep = self.saisie(self.admin, org=self.p.id)
        self.assertContains(rep, 'data-attendue="0"')  # saisie possible au-dessus : facultative, hors de « Valider et suivant »


class AttributionTests(Base):
    """Choix du SPOC dans la page (bulles), à l'unité ou en masse."""

    def poster(self, cles, utilisateur, retirer=False):
        return self.client.post(reverse("collecte:attribuer"), data=json.dumps(
            {"cles": cles, "utilisateur": utilisateur.id, "retirer": retirer, "campagne": self.c.pk}), content_type="application/json")

    def test_attribution_en_masse_et_retrait(self):
        self.client.force_login(self.admin)
        cles = [f"EFF|{self.e2.id}", f"TX|{self.e2.id}"]
        res = self.poster(cles, self.autre).json()
        self.assertEqual(res["message"], f"{self.autre} attribué à 2 cellules.")
        self.assertEqual(Attribution.objects.filter(utilisateur=self.autre).count(), 2)
        self.assertIn("avatar", res["lignes"][cles[0]])
        self.assertEqual({k.code for k, _ in S.cellules(self.autre)}, {"EFF", "TX"})
        self.poster(cles[:1], self.autre, retirer=True)
        self.assertEqual(Attribution.objects.filter(utilisateur=self.autre).count(), 1)
        self.assertTrue(Journal.objects.filter(action="retrait_attribution").exists())

    def test_regles_d_attribution(self):
        self.client.force_login(self.admin)
        # KPI calculé : la personne devient responsable du résultat (valeur forcée sur demande, collecte/forcage.py)
        self.assertEqual(self.poster([f"DBL|{self.e1.id}"], self.autre).status_code, 200)
        self.assertEqual(self.poster([f"EFF|{self.p.id}"], self.autre).status_code, 400)   # pas au niveau de granularité
        self.client.force_login(self.contrib)
        self.assertEqual(self.poster([f"EFF|{self.e2.id}"], self.autre).status_code, 403)  # réservé à l'admin
        self.assertEqual(list(Attribution.objects.filter(utilisateur=self.autre).values_list("kpi_id", flat=True)), ["DBL"])

    def test_bulles_et_liste_de_comptes_pour_l_admin(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:saisie") + f"?org={self.e1.id}")
        self.assertContains(rep, 'class="bouton-spoc"')
        self.assertContains(rep, "contrib@exemple.test")  # liste des comptes du sélecteur
        self.client.force_login(self.contrib)
        self.assertNotContains(self.client.get(reverse("collecte:saisie")), 'class="bouton-spoc"')


class ReferentielPageTests(Base):
    """Réglage du référentiel dans l'outil : fiche, type saisie / calcul, formule, ordre."""

    FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def fiche(self, kpi, **changes):
        donnees = {c: getattr(kpi, "granularite_id" if c == "granularite" else c) for c in R.CHAMPS_FICHE}
        donnees.update(changes)
        return {c: v for c, v in donnees.items() if v is not False and v is not None}

    def test_reserve_a_l_admin(self):
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(reverse("collecte:referentiel")).status_code, 403)
        self.assertEqual(self.client.get(reverse("collecte:referentiel_kpi", args=["EFF"])).status_code, 403)

    def test_liste_et_interactions(self):
        rep = self.client.get(reverse("collecte:referentiel"))
        self.assertContains(rep, "Double")
        self.assertContains(rep, "Sert à calculer 1 KPI : voir la liste")  # menu des KPI liés
        html = self.client.get(reverse("collecte:referentiel_kpi", args=["EFF"]), **self.FETCH).json()["html"]
        self.assertIn("Utilisé dans", html)
        self.assertIn("Double", html)

    def test_passer_un_kpi_de_saisi_a_calcule(self):
        url = reverse("collecte:referentiel_kpi", args=["TX"])
        res = self.client.post(url, self.fiche(self.taux, type_saisie="Calculé", formule="[EFF] / 100"), **self.FETCH).json()
        self.assertTrue(res["ok"], res["html"])
        self.taux.refresh_from_db()
        self.assertEqual(self.taux.type_saisie_id, "Calculé")
        self.assertEqual(list(self.taux.sources.values_list("kpi_source_id", flat=True)), ["EFF"])
        self.assertNotIn("TX", {k.code for k, _ in S.cellules(self.contrib)})  # plus à saisir
        self.assertTrue(Journal.objects.filter(action="reglage_kpi", champ="type_saisie").exists())

    def test_confirmation_si_reponses_dans_la_campagne_ouverte(self):
        self.enregistrer("10")
        url = reverse("collecte:referentiel_kpi", args=["EFF"])
        res = self.client.post(url, self.fiche(self.eff, granularite=Niveau.COUNTRY), **self.FETCH).json()
        self.assertFalse(res["ok"])
        self.assertIn("Confirmer", res["html"])
        res = self.client.post(url, self.fiche(self.eff, granularite=Niveau.COUNTRY, confirmer="on"), **self.FETCH).json()
        self.assertTrue(res["ok"])
        self.assertIn("recalculées", res["html"])

    def test_formule_invalide_refusee_et_test_de_formule(self):
        url = reverse("collecte:referentiel_kpi", args=["DBL"])
        res = self.client.post(url, self.fiche(self.calc, formule="[INCONNU] * 2"), **self.FETCH).json()
        self.assertFalse(res["ok"])
        self.assertIn("KPI inconnu", res["html"])
        self.enregistrer("7")
        res = self.client.post(url, {**self.fiche(self.calc), "action": "tester", "formule": "[EFF] * 3", "campagne_test": self.c.pk},
                               **self.FETCH).json()
        self.assertIn("21", res["html"])  # 7 × 3 pour E1
        self.calc.refresh_from_db()
        self.assertEqual(self.calc.formule, "[EFF] * 2")  # le test n'enregistre rien

    def test_creation_d_un_kpi(self):
        res = self.client.post(reverse("collecte:referentiel_kpi_nouveau"), {
            **self.fiche(self.eff), "code": "NOUV", "nom__fr": "Nouveau", "type_saisie": "Saisi"}, **self.FETCH).json()
        self.assertTrue(res["ok"], res["html"])
        self.assertEqual(KPI.objects.get(pk="NOUV").libelle, "Nouveau")


class RevuePageParPageTests(BaseEchanges):
    """Décisions de la revue page par page : ce qu'engage « Valider » écrit sous le bouton de fin d'import,
    sections de Pour moi repliées au-delà d'environ 200 lignes."""

    def test_phrase_sous_valider_ces_valeurs(self):
        from .outils_tests import xlsx

        self.client.force_login(self.contrib)
        url = reverse("collecte:echanges_importer")
        self.client.post(url, {"action": "verifier", "fichier": xlsx([["ID KPI", "Organisation", "Valeur"], ["EFF", "E1", 130]]),
                               "campagne": self.c.pk})
        html = self.client.post(url, {"action": "confirmer"}).content.decode()
        phrase = "Valider confirme que ces valeurs sont complètes, et un administrateur peut encore les rouvrir."
        self.assertIn(f'<p class="aide-valider" id="aide-valider-import">{phrase}</p></form>', html)  # sous le bouton
        self.assertIn('value="valider_import" aria-describedby="aide-valider-import"', html)
        self.assertEqual(html.count(phrase), 1)

    def test_sections_ouvertes_jusqu_a_la_limite(self):
        from .views import _sections_ouvertes

        def groupe(*tailles):
            return [(f"S{i}", [("", list(range(t)))]) for i, t in enumerate(tailles)]

        self.assertIsNone(_sections_ouvertes([groupe(100, 100)]))  # 200 lignes : tout reste ouvert
        self.assertEqual(_sections_ouvertes([groupe(150, 40, 30, 5)]), [2])  # 190 lignes montrées, la suite repliée
        self.assertEqual(_sections_ouvertes([groupe(250, 10)]), [1])  # la première section est toujours ouverte
        self.assertEqual(_sections_ouvertes([groupe(120), groupe(60, 50), groupe(10)]), [1, 1, 0])  # un groupe par référentiel

    def test_pour_moi_long_replie_les_dernieres_sections(self):
        from unittest import mock

        from referentiel.models import Attribution

        for k in (self.eff, self.taux):
            Attribution.objects.create(kpi=k, organisation=self.e2, utilisateur=self.contrib)
        self.client.force_login(self.contrib)
        url = reverse("collecte:pour_moi") + f"?campagne={self.c.pk}&tous=0"
        html = self.client.get(url).content.decode()
        self.assertEqual(html.count('<details class="section" open>'), 2)  # liste courte : tout est ouvert
        self.assertIn(">Tout replier</button>", html)
        with mock.patch("collecte.views.LIGNES_OUVERTES", 3):  # E1 (2 lignes) ouverte, E2 (2 lignes) repliée
            html = self.client.get(url).content.decode()
        self.assertEqual((html.count('<details class="section" open>'), html.count('<details class="section">')), (1, 1))
        self.assertLess(html.index('<details class="section" open>'), html.index('<details class="section">'))
        self.assertIn(">Tout déplier</button>", html)


class SaisieSignePourcentTests(BaseAllerRetour):
    """P10 : dans le panneau, « 12 % » sur un KPI en kWh n'est plus enregistré 12."""

    def test_refus_hors_pourcentage(self):
        for texte in ("12%", "12 %"):
            with self.assertRaisesMessage(ValidationError, "pas un pourcentage"):
                S.lire_nombre(texte, self.nrj)
        self.assertEqual(S.lire_nombre("12,5 %", self.taux), D("0.125"))
        self.assertIsNone(S.lire_nombre("%", self.nrj))

    def test_modele_valide_les_pourcentages_de_0_a_100(self):
        import io

        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(I.modele(self.contrib, self.c, I.lignes_modele(self.contrib, self.c)).content))
        ws = next(w for w in wb.worksheets if w.data_validations.dataValidation)
        tete = next(r for r in ws.iter_rows(values_only=True) if r and "Valeur" in r)
        n = next(i for i, r in enumerate(ws.iter_rows(values_only=True), start=1) if r and "TX" in r)
        cellule = f"{ws.cell(1, tete.index('Valeur') + 1).column_letter}{n}"
        regles = [dv for dv in ws.data_validations.dataValidation if cellule in dv.sqref]
        self.assertEqual([(dv.formula1, dv.formula2) for dv in regles], [("0", "100")])


class EnvoisDuScriptTests(BaseAllerRetour):
    """P5 : session expirée ; P6 : motif du refus. Le script des pages reçoit un motif lisible en JSON."""

    FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}

    def url(self):
        from django.urls import reverse

        return reverse("collecte:cellule", args=[self.c.pk, self.eff.pk, self.e1.pk])

    def test_session_expiree(self):
        rep = self.client.post(self.url(), {"action": "enregistrer", "valeur": "42"}, **self.FETCH)
        self.assertEqual(rep.status_code, 401)
        self.assertTrue(rep.json()["session_expiree"])
        self.assertIn("session a expiré", rep.json()["erreur"])
        self.assertEqual(self.client.get(self.url(), **self.FETCH).status_code, 401)  # ouvrir une case
        rep = self.client.get(self.url())  # page complète : redirection vers la connexion, comme avant
        self.assertEqual(rep.status_code, 302)
        self.assertIn("/connexion/", rep["Location"])

    def test_motif_du_refus_apres_fermeture(self):
        self.client.force_login(self.contrib)
        self.c.statut = Campagne.Statut.REVUE
        self.c.save()
        rep = self.client.post(self.url(), {"action": "enregistrer", "valeur": "11", "version": ""}, **self.FETCH)
        self.assertEqual(rep.status_code, 403)
        self.assertEqual(rep.json()["erreur"], self.c.motif_lecture_seule)
        rep = self.client.post(self.url(), {"action": "enregistrer", "valeur": "11", "version": ""})
        self.assertEqual(rep.status_code, 403)
        self.assertContains(rep, "Accès refusé", status_code=403)  # page habituelle sans script
