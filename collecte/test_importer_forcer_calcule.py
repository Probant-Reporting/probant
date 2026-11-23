"""Import d'un chiffre sur une case calculée d'une période non clôturée : il devient une valeur forcée, seulement après la
confirmation de la personne, seulement pour qui peut forcer la case (mêmes droits, même journal, même page « Valeurs
forcées », recalcul immédiat des totaux et des périodes qui la citent). Période clôturée : inchangé (ignoré). Chiffres
importés d'avant cette règle (« en sommeil ») : signalés dans « À traiter », à forcer ou à retirer."""
import tempfile
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.test import override_settings
from django.urls import reverse

from referentiel.models import KPI, Attribution, Niveau, Organisation, Utilisateur

from . import forcage as FO
from . import imports as I
from . import imports_arriere_plan as AP
from . import saisie as S
from .calcul import recalculer
from .models import Campagne, DemandeForcage, Journal, Reponse, TacheImport
from .outils_tests import xlsx
from .aides_tests.saisie import Base

ENTETE = ["ID KPI", "Organisation", "Exercice", "Valeur", "Commentaire"]


class ForcerParImportBase(Base):
    """Cas minimal : DBL = [EFF] * 2 (somme au-dessus), W = [DBL@N-1] ; 2025 et 2026 non clôturés."""

    def setUp(self):
        super().setUp()
        Campagne.objects.filter(pk=self.c0.pk).update(statut=Campagne.Statut.OUVERTE)
        self.c0.refresh_from_db()
        self.w = KPI.objects.create(code="W", libelle="Double N-1", type_saisie_id="Calculé", formule="[DBL@N-1]",
                                    granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        for c, (v1, v2) in ((self.c0, ("10", "5")), (self.c, ("40", "50"))):
            S.enregistrer(self.admin, c, self.eff, self.e1, v1, False, "")
            S.enregistrer(self.admin, c, self.eff, self.e2, v2, False, "")
        for c in (self.c0, self.c):
            recalculer(c)
        self.assertEqual(self.v("W", self.e1), D(20))

    def v(self, code, org, campagne=None):
        r = Reponse.objects.filter(periode=(campagne or self.c).periode, kpi_id=code, organisation=org).first()
        return None if r is None else r.valeur

    def r(self, code, org, campagne=None):
        return Reponse.objects.get(periode=(campagne or self.c).periode, kpi_id=code, organisation=org)

    def fichier(self, *lignes):
        return xlsx([ENTETE, *lignes])


class AnalyseEtConfirmationTests(ForcerParImportBase):
    def test_apercu_annonce_le_forcage(self):
        a = I.analyser(self.admin, self.fichier(["DBL", "E1", 2025, 99, ""], ["EFF", "E2", 2025, 6, ""]))
        self.assertEqual([l.action for l in a.lignes], ["forcer", "modifier"])
        self.assertEqual((a.lignes[0].avant, a.lignes[0].apres), ("20,00", "99,00"))
        self.assertEqual(len(a.a_forcer), 1)
        self.assertEqual(len(a.a_ecrire), 1)  # les valeurs forcées sont comptées à part

    def test_rien_n_est_force_sans_confirmation(self):
        a, n, _ = I.appliquer(self.admin, self.fichier(["DBL", "E1", 2025, 99, ""], ["EFF", "E2", 2025, 6, ""]), "f.xlsx")
        self.assertEqual(n, 1)  # l'autre ligne est écrite
        self.assertEqual(a.non_forcees, 1)
        self.assertEqual((self.r("DBL", self.e1, self.c0).origine, self.v("DBL", self.e1, self.c0)), (Reponse.Origine.CALCUL, D(20)))
        self.assertFalse(DemandeForcage.objects.exists())
        self.assertEqual(I.etat_importees(a)["nb_non_forcees"], 1)

    def test_seules_les_lignes_confirmees_sont_forcees(self):
        f = self.fichier(["DBL", "E1", 2025, 99, ""], ["DBL", "E2", 2025, 77, ""])
        a = I.analyser(self.admin, f)
        f.seek(0)
        a, n, _ = I.appliquer(self.admin, f, "f.xlsx", forcer=[a.lignes[0].cle])  # la ligne de E2 n'était pas confirmée
        self.assertEqual((n, a.non_forcees), (1, 1))
        self.assertEqual(self.r("DBL", self.e1, self.c0).origine, Reponse.Origine.FORCEE)
        self.assertEqual(self.r("DBL", self.e2, self.c0).origine, Reponse.Origine.CALCUL)

    def test_oui_valeur_forcee_journal_et_recalcul_immediat(self):
        f = self.fichier(["DBL", "E1", 2025, 99, ""])
        cles = [l.cle for l in I.analyser(self.admin, f).a_forcer]
        f.seek(0)
        a, n, avert = I.appliquer(self.admin, f, "histo.xlsx", forcer=cles, par_paquets=True)
        self.assertEqual((n, avert), (1, []))
        r = self.r("DBL", self.e1, self.c0)
        self.assertEqual((r.origine, r.statut, r.valeur, r.valide_par, r.commentaire),
                         (Reponse.Origine.FORCEE, Reponse.Statut.VALIDE, D(99), self.admin, "Importée du fichier histo.xlsx."))
        d = DemandeForcage.objects.get()
        self.assertEqual((d.statut, d.valeur, d.valeur_calculee, d.demandeur), (DemandeForcage.Statut.ACCEPTEE, D(99), D(20), self.admin))
        self.assertEqual(set(Journal.objects.filter(action__startswith="forcage_").values_list("action", flat=True)),
                         {"forcage_demande", "forcage_accepte"})
        self.assertEqual(self.v("DBL", self.p, self.c0), D(109))  # total : 99 + 5 × 2
        self.assertEqual(self.v("W", self.e1), D(99))  # [DBL@N-1] de 2026 : à jour tout de suite
        self.assertEqual(self.v("W", self.p), D(109))
        self.assertEqual(I.etat_importees(a)["nb_forcees"], 1)
        S.enregistrer(self.admin, self.c0, self.eff, self.e1, "11", False, "")  # la valeur forcée tient
        self.assertEqual(self.v("DBL", self.e1, self.c0), D(99))

    def test_commentaire_de_la_ligne_comme_justification_et_na(self):
        f = self.fichier(["DBL", "E1", 2026, "N/A", "Site fermé"])
        cles = [l.cle for l in I.analyser(self.admin, f).a_forcer]
        f.seek(0)
        I.appliquer(self.admin, f, "f.xlsx", forcer=cles)
        r = self.r("DBL", self.e1)
        self.assertEqual((r.origine, r.non_applicable, r.commentaire), (Reponse.Origine.FORCEE, True, "Site fermé"))

    def test_valeur_identique_ignoree_et_valeur_forcee_identique_inchangee(self):
        a = I.analyser(self.admin, self.fichier(["DBL", "E1", 2026, 80, ""]))
        self.assertEqual((a.lignes[0].action, a.lignes[0].motif), ("ignore", "KPI calculé : l'outil le calcule."))
        FO.demander(self.admin, self.c, self.calc, self.e1, "81", False, "x")
        a = I.analyser(self.admin, self.fichier(["DBL", "E1", 2026, 81, ""]))
        self.assertEqual(a.lignes[0].action, "inchange")

    def test_periode_cloturee_inchangee(self):
        Campagne.objects.filter(pk=self.c0.pk).update(statut=Campagne.Statut.CLOTUREE)
        avant = self.v("DBL", self.e1, self.c0)
        f = self.fichier(["DBL", "E1", 2025, 99, ""])
        a = I.analyser(self.admin, f)
        self.assertEqual((a.lignes[0].action, a.lignes[0].motif), ("ignore", "KPI calculé : l'outil le calcule."))
        f.seek(0)
        _, n, _ = I.appliquer(self.admin, f, "f.xlsx", forcer=[a.lignes[0].cle])
        self.assertEqual((n, self.v("DBL", self.e1, self.c0), self.r("DBL", self.e1, self.c0).origine), (0, avant, Reponse.Origine.CALCUL))

    def test_tout_ou_rien_sans_paquets(self):
        f = self.fichier(["DBL", "E1", 2026, 99, ""], ["EFF", "E2", 2026, 51, ""])
        cles = [l.cle for l in I.analyser(self.admin, f).a_forcer]
        f.seek(0)
        with mock.patch.object(S, "enregistrer", side_effect=RuntimeError("panne")):
            with self.assertRaises(RuntimeError):
                I.appliquer(self.admin, f, "f.xlsx", forcer=cles)  # sans paquets : une seule transaction
        self.assertEqual((self.r("DBL", self.e1).origine, self.v("DBL", self.e1)), (Reponse.Origine.CALCUL, D(80)))
        self.assertFalse(DemandeForcage.objects.exists())


class DroitsTests(ForcerParImportBase):
    """Pas de forçage sans droit : lignes refusées avec un message, même si la confirmation est envoyée."""

    def setUp(self):
        super().setUp()
        Attribution.objects.create(kpi=self.calc, organisation=self.e1, utilisateur=self.contrib)  # responsable du résultat
        self.e3 = Organisation.objects.create(nom="E3", niveau_id=Niveau.ENTITY,
                                              parent=Organisation.objects.create(nom="Pays 2", niveau_id=Niveau.COUNTRY, parent=self.g))

    def test_contributeur_responsable_refuse_meme_avec_les_cles(self):
        f = self.fichier(["DBL", "E1", 2026, 99, ""])
        a = I.analyser(self.contrib, f)
        self.assertEqual(a.lignes[0].action, "rejet")
        self.assertTrue(a.lignes[0].motif.startswith("KPI calculé : seul un administrateur ou un validateur"))
        f.seek(0)
        a, n, _ = I.appliquer(self.contrib, f, "f.xlsx", forcer=[a.lignes[0].cle], par_paquets=True)
        self.assertEqual(n, 0)
        self.assertEqual(self.r("DBL", self.e1).origine, Reponse.Origine.CALCUL)
        self.assertFalse(DemandeForcage.objects.exists())  # pas même une demande

    def test_validateur_hors_de_ses_organisations_refuse(self):
        S.enregistrer(self.admin, self.c, self.eff, self.e3, "3", False, "")
        a = I.analyser(self.valid, self.fichier(["DBL", "E1", 2026, 99, ""], ["DBL", "E3", 2026, 99, ""]))
        self.assertEqual([l.action for l in a.lignes], ["forcer", "rejet"])  # validateur de « Pays », pas de « Pays 2 »

    def test_organisation_fermee_refusee_avec_son_motif(self):
        import datetime

        Organisation.objects.filter(pk=self.e1.pk).update(actif=False, date_desactivation=datetime.date(2026, 6, 30))
        a = I.analyser(self.admin, self.fichier(["DBL", "E1", 2026, 99, ""]))
        self.assertEqual((a.lignes[0].action, a.lignes[0].motif),
                         ("rejet", "KPI calculé : l'organisation est fermée, son résultat ne peut pas être forcé."))

    def test_lecteur_refuse(self):
        lecteur = Utilisateur.objects.create(username="lect", email="lect@exemple.test", role=Utilisateur.Role.LECTEUR)
        a = I.analyser(lecteur, self.fichier(["DBL", "E1", 2026, 99, ""]))
        self.assertEqual(a.lignes[0].action, "rejet")

    def test_droit_perdu_entre_apercu_et_import(self):
        f = self.fichier(["DBL", "E1", 2026, 99, ""])
        cles = [l.cle for l in I.analyser(self.valid, f).a_forcer]
        Attribution.objects.filter(utilisateur=self.valid).delete()
        f.seek(0)
        a, n, avert = I.appliquer(self.valid, f, "f.xlsx", forcer=cles)
        self.assertEqual(n, 0)
        self.assertEqual((a.lignes[0].action, avert), ("rejet", []))  # refusée à la nouvelle analyse
        self.assertEqual(self.r("DBL", self.e1).origine, Reponse.Origine.CALCUL)
        self.assertFalse(DemandeForcage.objects.exists())


class PageImportTests(ForcerParImportBase):
    def setUp(self):
        super().setUp()
        self.url = reverse("collecte:echanges_importer")
        Attribution.objects.create(kpi=self.calc, organisation=self.e1, utilisateur=self.contrib)

    def deposer(self, user, *lignes):
        self.client.force_login(user)
        return self.client.post(self.url, {"action": "verifier", "fichier": self.fichier(*lignes), "campagne": self.c.pk})

    def test_ecran_de_confirmation_puis_oui(self):
        rep = self.deposer(self.admin, ["DBL", "E1", 2026, 99, ""])
        html = rep.content.decode()
        self.assertIn('name="forcer" value="oui"', html)
        self.assertIn('name="forcer" value="non"', html)
        self.assertNotIn("checked", html.split('class="forcer-import"')[1].split("</fieldset>")[0])  # aucun choix d'avance
        self.assertIn("1 valeur pour un KPI calculé", html)
        rep = self.client.post(self.url, {"action": "confirmer", "forcer": "oui"})
        self.assertEqual(self.r("DBL", self.e1).origine, Reponse.Origine.FORCEE)
        self.assertIn("1 valeur d'un KPI calculé est désormais une valeur forcée.", rep.content.decode())

    def test_non_ou_sans_choix(self):
        for donnees in ({"forcer": "non"}, {}):
            self.deposer(self.admin, ["DBL", "E1", 2026, 99, ""])
            rep = self.client.post(self.url, {"action": "confirmer", **donnees})
            self.assertEqual(self.r("DBL", self.e1).origine, Reponse.Origine.CALCUL)
            self.assertIn("1 ligne d'un KPI calculé n'a pas été importée", rep.content.decode())

    def test_envoi_direct_du_formulaire_sans_droit(self):
        self.deposer(self.contrib, ["DBL", "E1", 2026, 99, ""])
        self.client.post(self.url, {"action": "confirmer", "forcer": "oui"})
        self.assertEqual(self.r("DBL", self.e1).origine, Reponse.Origine.CALCUL)
        self.client.post(self.url, {"action": "confirmer", "forcer": "oui"})  # sans aperçu : rien
        self.assertFalse(DemandeForcage.objects.exists())

    @override_settings(IMPORT_ARRIERE_PLAN_LIGNES=1)
    @mock.patch.object(AP, "BATTEMENT", 0)
    @mock.patch.object(AP, "planificateur_actif", lambda: False)
    def test_import_en_arriere_plan(self):
        self.deposer(self.admin, ["DBL", "E1", 2026, 99, ""], ["EFF", "E2", 2026, 51, ""])
        with mock.patch.object(AP, "demarrer_fil", lambda code: AP.traiter_file()):
            self.client.post(self.url, {"action": "confirmer", "forcer": "oui"})
        t = TacheImport.objects.latest("pk")
        self.assertEqual(t.statut, TacheImport.Statut.TERMINEE)
        self.assertEqual(t.resultat["nb_forcees"], 1)
        self.assertEqual((self.r("DBL", self.e1).origine, self.v("DBL", self.p)), (Reponse.Origine.FORCEE, D(201)))


class ChiffresEnSommeilTests(ForcerParImportBase):
    """Chiffres importés tels quels sur une case calculée d'une période non clôturée (données d'avant la règle)."""

    def setUp(self):
        super().setUp()
        Reponse.objects.filter(periode=self.c.periode, kpi_id="DBL", organisation=self.e1).update(
            origine=Reponse.Origine.IMPORT, statut=Reponse.Statut.VALIDE, valeur=D(7))

    def test_signales_dans_a_traiter(self):
        self.assertEqual([(r.kpi_id, r.organisation.nom) for r in FO.importees(self.c)], [("DBL", "E1")])
        self.client.force_login(self.admin)
        html = self.client.get(reverse("collecte:admin_accueil")).content.decode()
        self.assertIn("1 chiffre importé sur une case calculée n&#x27;est pas utilisé par le calcul", html)
        page = self.client.get(reverse("collecte:forcages") + f"?campagne={self.c.pk}").content.decode()
        self.assertIn('id="importees"', page)
        self.assertEqual(self.r("DBL", self.e1).valeur, D(7))  # rien n'est changé en silence

    def test_forcer(self):
        FO.forcer_importee(self.admin, self.c, self.calc, self.e1)
        r = self.r("DBL", self.e1)
        self.assertEqual((r.origine, r.valeur), (Reponse.Origine.FORCEE, D(7)))
        self.assertEqual(self.v("DBL", self.p), D(107))
        self.assertEqual(DemandeForcage.objects.get().valeur_calculee, None)
        self.assertEqual(FO.importees(self.c), [])

    def test_retirer(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("collecte:forcage_importee"), {"campagne": self.c.pk, "kpi": "DBL", "organisation": self.e1.pk,
                                                                "action": "retirer"})
        r = self.r("DBL", self.e1)
        self.assertEqual((r.origine, r.valeur), (Reponse.Origine.CALCUL, D(80)))
        self.assertTrue(Journal.objects.filter(action="import_calcule_retire").exists())

    def test_droits_par_role(self):
        lecteur = Utilisateur.objects.create(username="lect", email="lect@exemple.test", role=Utilisateur.Role.LECTEUR)
        auditeur = Utilisateur.objects.create(username="aud", email="aud@exemple.test", role=Utilisateur.Role.AUDITEUR)
        Attribution.objects.create(kpi=self.calc, organisation=self.e1, utilisateur=self.contrib)
        for u in (self.contrib, self.autre, lecteur, auditeur):
            self.client.force_login(u)
            for action in ("forcer", "retirer"):
                rep = self.client.post(reverse("collecte:forcage_importee"),
                                       {"campagne": self.c.pk, "kpi": "DBL", "organisation": self.e1.pk, "action": action})
                self.assertEqual(rep.status_code, 403, (u.username, action))
            with self.assertRaises(PermissionDenied):
                FO.retirer_importee(u, self.c, self.calc, self.e1)
        self.assertEqual(self.r("DBL", self.e1).origine, Reponse.Origine.IMPORT)
        self.client.force_login(self.valid)  # validateur de l'organisation : il peut forcer la case
        self.client.post(reverse("collecte:forcage_importee"), {"campagne": self.c.pk, "kpi": "DBL", "organisation": self.e1.pk,
                                                                "action": "forcer"})
        self.assertEqual(self.r("DBL", self.e1).origine, Reponse.Origine.FORCEE)


class CommandeImportValeursTests(ForcerParImportBase):
    def test_kpi_calcule_d_une_periode_ouverte_saute(self):
        from openpyxl import Workbook

        from .echange import importer_valeurs

        wb = Workbook()
        wb.active.append(["ID KPI", "Result", "Organisation", "Year"])
        wb.active.append(["DBL", 99, "E1", 2026])
        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / "h.xlsx"
            wb.save(chemin)
            rapport = importer_valeurs(str(chemin))
        self.assertEqual(rapport.crees, 0)
        self.assertEqual(self.r("DBL", self.e1).origine, Reponse.Origine.CALCUL)
