"""Dossier d'audit exportable (présentation « audit » d'Import / Export) : contenu des onglets, droits de chaque rôle, KPI
sensibles, lecture seule (aucune ligne écrite), gros périmètre en arrière-plan, sept langues, ouverture par openpyxl."""
import io
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from parametres.libelles import libelle
from parametres.models import Instance
from referentiel.models import KPI, Attribution, Utilisateur

from . import exports as E
from . import exports_arriere_plan as EAP
from . import fichiers as X
from . import imports_arriere_plan as AP
from . import saisie as S
from .aides_tests.lecture_seule import Base
from .models import Alerte, DemandeForcage, Journal, Preuve, ReglageExport, Reponse, TacheExport

D = Decimal
DEMANDE = {"action": "telecharger", "presentation": "audit", "exercices": ["courant"], "contenus": list(E.CODES_CONTENUS),
           "types": list(E.CODES_COMPORTEMENTS), "langue": "en"}
PDF = b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\n"


def classeur(rep):
    octets = b"".join(rep.streaming_content) if rep.streaming else rep.content
    return load_workbook(io.BytesIO(octets))


def lignes(ws):
    """[{en-tête: valeur}] des lignes de données d'un onglet dont la première ligne est l'en-tête."""
    tete = [c.value for c in ws[1]]
    return [dict(zip(tete, [c.value for c in r])) for r in ws.iter_rows(min_row=2)]


class AvecDossier(Base):
    def setUp(self):
        super().setUp()
        self.url = reverse("collecte:echanges_exporter")
        self.valideur = Utilisateur.objects.create(username="valideur", email="valideur@exemple.test",
                                                   role=Utilisateur.Role.VALIDATEUR)
        Attribution.objects.create(kpi=self.eff, organisation=self.e1, utilisateur=self.valideur, role=Attribution.Role.VALIDATEUR)
        S.valider(self.contrib, self.c, self.eff, self.e1)
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        self.preuve = Preuve.objects.create(reponse=r, fichier=ContentFile(PDF, name="facture.pdf"), nom_fichier="facture.pdf",
                                            taille=len(PDF), depose_par=self.contrib)
        self.alerte = Alerte.objects.create(
            campagne=self.c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.ECART_N1, gravite=Alerte.Gravite.ALERTE,
            message="Écart de 10 % avec N-1", statut=Alerte.Statut.JUSTIFIEE, justification="Embauches de l'été",
            justifie_par=self.contrib, date_justification=timezone.now(), traite_par=self.admin, date_traitement=timezone.now())
        self.autre_alerte = Alerte.objects.create(
            campagne=self.c, kpi=self.eff, organisation=self.e2, controle=Alerte.Controle.FORMAT, message="Format douteux")

    def demander(self, user, **donnees):
        self.client.force_login(user)
        return self.client.post(self.url, {**DEMANDE, "niveaux": E.N.codes(), **donnees})

    def classeur_de(self, user, **donnees):
        rep = self.demander(user, **donnees)
        self.assertEqual(rep.status_code, 200, rep.content[:200])
        return classeur(rep)

    def compteurs(self):
        return {m.__name__: m.objects.count() for m in (Reponse, Journal, Alerte, Preuve, DemandeForcage, TacheExport, ReglageExport,
                                                         Utilisateur, Attribution, KPI)}


class ContenuDossierTests(AvecDossier):
    def test_onglets_dans_l_ordre(self):
        wb = self.classeur_de(self.auditeur)
        self.assertEqual(wb.sheetnames, ["Read me", "Audit", "History", "Evidence"])

    def test_une_ligne_par_kpi_et_organisation_avec_les_traces(self):
        wb = self.classeur_de(self.auditeur)
        par = {(l["KPI ID"], l["Organisation code"]): l for l in lignes(wb["Audit"])}
        l = par[("EFF", self.e1.code)]
        self.assertEqual((l["Year"], l["Organisation"], l["Level"], l["Unit"]), (2026, "E1", "Entity", "ETP"))
        self.assertEqual(l["Value"], 110)
        self.assertEqual(l["Status"], "Validated")
        self.assertEqual(l["Entered by"], "Camille")  # le nom, comme l'onglet Historique
        self.assertEqual(l["Validated by"], "Camille")
        self.assertIsNotNone(l["Updated on"])
        self.assertIsNotNone(l["Validated on"])
        self.assertEqual(l["Comment"], "Embauches")
        self.assertEqual((l["Evidence files"], l["Evidence file names"]), (1, "facture.pdf (1 kB)"))
        self.assertEqual(l["Framework"], str(self.c.referentiel))
        self.assertEqual((l["Theme"], l["Sub-theme"]), ("Social", "Effectifs"))
        self.assertEqual(l["Overridden"], "No")
        self.assertEqual(l["Confidentiality"], "Not sensitive")
        # N-1 (2025) et écart : le moteur des autres exports
        self.assertEqual(l["Previous year value"], 100)
        self.assertAlmostEqual(l["Variance"], 0.1)
        # alerte, justification (qui, quand, texte) et décision
        self.assertEqual(l["Alerts"], 1)
        self.assertIn("Variance with N-1 · Warning · Justified", l["Alert details"])
        self.assertIn("Écart de 10 % avec N-1", l["Alert details"])
        self.assertIn("Camille", l["Justifications (who, when, text)"])
        self.assertIn("Embauches de l'été", l["Justifications (who, when, text)"])
        self.assertIn("admin@exemple.test", l["Decisions (who, when)"])
        autre = par[("EFF", self.e2.code)]
        self.assertEqual((autre["Alerts"], autre["Status"], autre["Entered by"]), (1, "Draft", "admin@exemple.test"))
        self.assertIsNone(autre["Validated by"] or None)
        self.assertEqual(autre["Justifications (who, when, text)"] or "", "")

    def test_valeur_forcee_et_sa_justification(self):
        calc = Reponse.objects.filter(periode=self.c.periode, kpi=self.calc, organisation=self.e1).first()
        if calc is None:
            calc = Reponse.objects.create(periode=self.c.periode, kpi=self.calc, organisation=self.e1, valeur=D(220), statut="calcule",
                                          origine="calcul")
        calc.valeur, calc.origine, calc.statut = D(300), Reponse.Origine.FORCEE, Reponse.Statut.VALIDE
        calc.save()
        DemandeForcage.objects.create(periode=self.c.periode, kpi=self.calc, organisation=self.e1, valeur=D(300),
                                      justification="Correction comptable", valeur_calculee=D(220),
                                      statut=DemandeForcage.Statut.ACCEPTEE, demandeur=self.contrib, traite_par=self.admin,
                                      date_traitement=timezone.now())
        wb = self.classeur_de(self.admin)
        l = {(x["KPI ID"], x["Organisation code"]): x for x in lignes(wb["Audit"])}[("DBL", self.e1.code)]
        self.assertEqual(l["Overridden"], "Yes")
        self.assertIn("Correction comptable", l["Override: justification, who and when"])
        self.assertIn("calculated result replaced: 220", l["Override: justification, who and when"])
        self.assertEqual(l["Source"], "Overridden value")

    def test_historique_des_cases(self):
        S.enregistrer(self.contrib, self.c, self.taux, self.e1, "40", False, "")
        wb = self.classeur_de(self.admin)
        h = lignes(wb["History"])
        self.assertTrue(h)
        valeur = [x for x in h if x["Field"] == "Valeur" or x["Field"] == "Value"]
        self.assertTrue(any(x["KPI ID"] == "EFF" and x["Organisation code"] == self.e1.code for x in h))
        self.assertTrue(all(x["Ref"].startswith("H-") for x in h))
        self.assertTrue(valeur)
        dates = [x["Date"] for x in h]
        self.assertEqual(dates, sorted(dates))  # de la plus ancienne à la plus récente
        # rien d'autre que les cases du fichier : pas de ligne d'administration
        self.assertTrue(all(x["Cell"] for x in h))

    def test_fichiers_de_preuve(self):
        wb = self.classeur_de(self.auditeur)
        (e,) = lignes(wb["Evidence"])
        self.assertEqual((e["KPI ID"], e["File name"], e["Size (bytes)"], e["Added by"]), ("EFF", "facture.pdf", len(PDF), "Camille"))
        self.assertIsNotNone(e["Added on"])

    def test_a_lire_version_date_perimetre_et_filtres(self):
        wb = self.classeur_de(self.auditeur)
        texte = "\n".join(str(c.value) for r in wb["Read me"].iter_rows() for c in r if c.value is not None)
        for attendu in ("Audit file", "Tool version", settings.VERSION, "Exported on", "auditeur@exemple.test", "Years", "2026",
                        "Organisation", "Read only", "Alerts", "Evidence sheet", "History sheet"):
            self.assertIn(attendu, texte)

    def test_nom_du_fichier(self):
        rep = self.demander(self.admin)
        self.assertIn("Audit-file_Year-2026", rep["Content-Disposition"])

    def test_filtre_par_organisation_et_exercice(self):
        wb = self.classeur_de(self.admin, organisations=[str(self.e2.pk)])
        self.assertEqual({l["Organisation code"] for l in lignes(wb["Audit"])}, {self.e2.code})
        self.assertEqual(lignes(wb["Evidence"]), [])  # la preuve est sur E1
        wb = self.classeur_de(self.admin, exercices=["2025"])
        self.assertEqual({l["Year"] for l in lignes(wb["Audit"])}, {2025})

    def test_csv_ne_donne_que_l_onglet_des_cases(self):
        rep = self.demander(self.admin, format="csv", csv="intl")
        texte = rep.content.decode("utf-8-sig")
        self.assertIn("KPI ID", texte.splitlines()[0])
        self.assertIn("facture.pdf", texte)

    def test_apercu_du_constructeur(self):
        self.client.force_login(self.admin)
        rep = self.client.post(reverse("collecte:echanges_resume"), {**DEMANDE, "niveaux": E.N.codes(), "apercu": "1"})
        self.assertEqual(rep.status_code, 200)
        d = rep.json()["apercu"]
        self.assertIn("Alert details", d["entetes"])
        self.assertGreater(d["total"], 0)


class DroitsDossierTests(AvecDossier):
    def test_chaque_role(self):
        attendu = {"admin": 200, "auditeur": 200, "valideur": 403, "contrib": 403, "lecteur": 403}
        comptes = {"admin": self.admin, "auditeur": self.auditeur, "valideur": self.valideur, "contrib": self.contrib,
                   "lecteur": self.lecteur}
        for role, code in attendu.items():
            with self.subTest(role=role):
                self.assertEqual(self.demander(comptes[role]).status_code, code)

    def test_pas_de_dossier_dans_le_constructeur_des_autres_roles(self):
        for user, present in ((self.admin, True), (self.auditeur, True), (self.valideur, False), (self.contrib, False)):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                page = self.client.get(self.url, {"nouveau": "1"})
                self.assertEqual(page.status_code, 200)
                self.assertEqual('value="audit"' in page.content.decode(), present)

    def test_apercu_et_arriere_plan_refuses_aux_autres_roles(self):
        for user in (self.valideur, self.contrib):
            self.client.force_login(user)
            rep = self.client.post(reverse("collecte:echanges_resume"), {**DEMANDE, "niveaux": E.N.codes(), "apercu": "1"})
            self.assertEqual(rep.status_code, 403)
        i = Instance.courante()
        i.exports_fond_cellules = 1
        i.save()
        avant = TacheExport.objects.count()
        self.assertEqual(self.demander(self.contrib).status_code, 403)
        self.assertEqual(TacheExport.objects.count(), avant)

    def test_export_enregistre_partage_ne_contourne_pas(self):
        """Un export enregistré en « audit » par l'administrateur, partagé : un contributeur qui le lance est refusé."""
        m = ReglageExport.objects.create(nom="Dossier", parametres={**DEMANDE, "niveaux": E.N.codes()}, proprietaire=self.admin,
                                         partage=True)
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(self.url, {"modele": m.pk, "telecharger": "1"}).status_code, 403)

    def test_auditeur_limite_a_une_organisation(self):
        self.auditeur.perimetre_lecture.add(self.e1)
        wb = self.classeur_de(self.auditeur)
        self.assertEqual({l["Organisation code"] for l in lignes(wb["Audit"]) if l["KPI ID"] == "EFF"}, {self.e1.code})
        textes = " ".join(str(l["Alert details"]) for l in lignes(wb["Audit"]))
        self.assertNotIn("Format douteux", textes)  # l'alerte de E2 n'est pas visible
        self.assertTrue(all(x["Organisation code"] != self.e2.code for x in lignes(wb["History"])))

    def test_kpi_sensible_comme_aux_ecrans(self):
        """Un KPI « Restreint » est lu à l'écran par l'auditeur : il est dans le fichier avec sa mention, et seulement chez
        qui a droit à la case ; le contributeur d'une autre case ne le voit pas (refus du dossier lui-même)."""
        KPI.objects.filter(pk="EFF").update(confidentialite=KPI.Confidentialite.RESTREINT)
        wb = self.classeur_de(self.auditeur)
        l = [x for x in lignes(wb["Audit"]) if x["KPI ID"] == "EFF"]
        self.assertTrue(l)
        self.assertEqual({x["Confidentiality"] for x in l}, {"Restricted"})
        self.assertEqual(self.demander(self.contrib).status_code, 403)


class LectureSeuleDossierTests(AvecDossier):
    def test_aucune_ecriture(self):
        avant = self.compteurs()
        etat = list(Alerte.objects.order_by("pk").values_list("pk", "statut", "date_maj", "justification"))
        for user in (self.admin, self.auditeur):
            for format_ in ("xlsx", "csv"):
                self.assertEqual(self.demander(user, format=format_).status_code, 200)
        self.assertEqual(self.compteurs(), avant)
        self.assertEqual(list(Alerte.objects.order_by("pk").values_list("pk", "statut", "date_maj", "justification")), etat)

    def test_ne_recalcule_pas_la_coherence(self):
        from . import coherence as CO

        with mock.patch.object(CO, "controler_a_l_ouverture", side_effect=AssertionError("écriture")), \
                mock.patch.object(Journal, "ecrire", side_effect=AssertionError("journal")):
            self.assertEqual(self.demander(self.auditeur).status_code, 200)

    def test_auditeur_n_a_pas_de_nouvelle_ecriture_permise(self):
        from . import lecture_seule as LS

        self.assertEqual(LS.ECRITURES_PERMISES & {"audit", "dossier_audit"}, set())
        self.assertIn("echanges_exporter", LS.ECRITURES_PERMISES)  # l'export existant, déjà permis


@mock.patch.object(EAP, "BATTEMENT", 0)
@mock.patch.object(AP, "planificateur_actif", lambda: False)
@mock.patch.object(EAP, "demarrer_fil", lambda code: None)
class ArrierePlanDossierTests(AvecDossier):
    def test_gros_perimetre_en_arriere_plan_meme_fichier(self):
        i = Instance.courante()
        i.exports_fond_cellules = 1
        i.save()
        self.client.force_login(self.auditeur)
        rep = self.client.post(self.url, {**DEMANDE, "niveaux": E.N.codes()})
        self.assertRedirects(rep, reverse("collecte:echanges") + "#exports-fond", fetch_redirect_response=False)
        t = TacheExport.objects.get()
        self.assertEqual(t.utilisateur, self.auditeur)
        avant = {m.__name__: m.objects.count() for m in (Reponse, Journal, Alerte, Preuve)}
        EAP.traiter_file()
        t.refresh_from_db()
        self.assertEqual(t.statut, TacheExport.Statut.PRET)
        self.assertEqual({m.__name__: m.objects.count() for m in (Reponse, Journal, Alerte, Preuve)}, avant)
        rep = self.client.get(reverse("collecte:echanges_export_fichier", args=[t.pk]))
        fond = classeur(rep)
        self.assertEqual(fond.sheetnames, ["Read me", "Audit", "History", "Evidence"])
        i.exports_fond_cellules = 0
        i.save()
        direct = self.classeur_de(self.auditeur)
        self.assertEqual([r for r in lignes(fond["Audit"])], [r for r in lignes(direct["Audit"])])
        self.assertEqual(lignes(fond["Evidence"]), lignes(direct["Evidence"]))

    def test_un_contributeur_ne_cree_pas_de_tache(self):
        i = Instance.courante()
        i.exports_fond_cellules = 1
        i.save()
        self.assertEqual(self.demander(self.valideur).status_code, 403)
        self.assertFalse(TacheExport.objects.exists())


class SeptLanguesDossierTests(AvecDossier):
    def test_en_tetes_et_onglets_traduits(self):
        vus = {}
        from parametres import langues as langues_
        codes = ["en", "fr", "es", "de", "it", "nl", "pt"]
        for code in codes:
            with self.subTest(langue=code), mock.patch.object(langues_, "codes_actifs", return_value=codes):
                wb = self.classeur_de(self.auditeur, langue=code)
                audit = wb[libelle("suivi.export.audit.onglet.cases", code)]
                tete = [c.value for c in audit[1]]
                for cle in ("forcee", "alertes", "justifications", "decisions", "confidentialite"):
                    self.assertIn(libelle(f"suivi.export.audit.col.{cle}", code), tete)
                self.assertIn(libelle("suivi.export.audit.onglet.historique", code), wb.sheetnames)
                self.assertIn(libelle("suivi.export.audit.onglet.preuves", code), wb.sheetnames)
                self.assertIn(X.t(code, "suivi.fichier.a_lire"), wb.sheetnames)
                vus[code] = tete
        self.assertEqual(len({tuple(t) for t in vus.values()}), 7)  # sept jeux d'en-têtes différents

    def test_cles_de_libelles_presentes_dans_les_sept_langues(self):
        import json
        from pathlib import Path

        racine = Path(__file__).resolve().parent.parent / "libelles"
        tables = {c: json.loads((racine / f"suivi.{c}.json").read_text(encoding="utf-8")) for c in ("en", "fr", "es", "de", "it", "nl", "pt")}
        cles = {k for k in tables["en"] if k.startswith("suivi.export.audit.") or k in (
            "suivi.export.presentation.audit", "suivi.export.presentation.audit_aide", "suivi.export.fichier.nom_audit")}
        self.assertGreater(len(cles), 40)
        for c, t in tables.items():
            self.assertEqual(cles - set(t), set(), c)
