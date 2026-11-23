"""« Demandé depuis » à chaque porte d'entrée (règle du projet) : contenu du référentiel (une ligne et
en groupe, aperçu avant d'enregistrer, refus), fiche d'un nouveau KPI, page « Choisir les KPI », import d'un fichier
référentiel ou d'un modèle de la bibliothèque, classeur de configuration ; droits (administrateur seulement).

Données inventées uniquement."""
import datetime
import io
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from referentiel.models import KPI, ElementReferentiel, Utilisateur

from . import demande_depuis as DD
from .administration import changer_statut
from .models import Journal
from .test_demande_depuis_perimetre import J25, J26, Base


class ContenuTests(Base):
    def setUp(self):
        super().setUp()
        self.nouveau()
        self.nouveau("AUT")
        for code in ("NEW", "AUT"):
            ElementReferentiel(referentiel=self.ref, kpi_id=code, ordre=9).save()  # 2026 par défaut
        self.client.force_login(self.admin)

    def action(self, **corps):
        rep = self.client.post(reverse("parametres:referentiel_contenu_action", args=[self.ref.code]), json.dumps(corps),
                               content_type="application/json")
        return rep.status_code, rep.json()

    def test_colonne_et_choix(self):
        rep = self.client.get(reverse("parametres:referentiel_contenu", args=[self.ref.code]))
        self.assertContains(rep, 'data-depuis-ligne="NEW"')
        self.assertContains(rep, "data-lot-depuis")
        self.assertContains(rep, 'value="2025-01-01"')

    def test_en_groupe_apercu_puis_enregistre(self):
        code, r = self.action(action="lot", operation="depuis", codes=["NEW", "AUT"], depuis="2025-01-01")
        self.assertIn("confirmer", r)  # aperçu : 2025 (clos) : 2 KPI à la réouverture, 4 cases
        self.assertIn("2025", r["confirmer"])
        self.assertEqual(self.element().demande_depuis, J26)  # rien d'écrit
        code, r = self.action(action="lot", operation="depuis", codes=["NEW", "AUT"], depuis="2025-01-01", confirmer=True)
        self.assertTrue(r["ok"], r)
        self.assertEqual({e.demande_depuis for e in ElementReferentiel.objects.filter(kpi_id__in=["NEW", "AUT"])}, {J25})
        self.assertEqual(Journal.objects.filter(champ="Demandé depuis (RAP)").count(), 2)

    def test_recul_refuse_avec_un_message(self):
        changer_statut(self.admin, self.camp(2025), "rouvrir", garder=False)
        DD.changer(self.admin, self.ref, ["NEW"], J25)
        from . import saisie as S

        S.enregistrer(self.admin, self.camp(2025), KPI.objects.get(pk="NEW"), self.e1, "4", False, "")
        code, r = self.action(action="lot", operation="depuis", codes=["NEW"], depuis="", confirmer=True)
        self.assertEqual(code, 400)
        self.assertIn("NEW", r["message"])
        self.assertEqual(self.element().demande_depuis, J25)

    def test_choix_hors_des_periodes_refuse(self):
        code, r = self.action(action="lot", operation="depuis", codes=["NEW"], depuis="2019-03-04", confirmer=True)
        self.assertEqual(code, 400)

    def test_droits_seul_l_administrateur(self):
        for role in (Utilisateur.Role.VALIDATEUR, Utilisateur.Role.CONTRIBUTEUR, Utilisateur.Role.LECTEUR, Utilisateur.Role.AUDITEUR):
            u = Utilisateur.objects.create(username=f"u-{role}", email=f"{role}@exemple.test", role=role)
            self.client.force_login(u)
            rep = self.client.post(reverse("parametres:referentiel_contenu_action", args=[self.ref.code]),
                                   json.dumps({"action": "lot", "operation": "depuis", "codes": ["NEW"], "depuis": "2025-01-01",
                                               "confirmer": True}), content_type="application/json")
            self.assertIn(rep.status_code, (302, 403), role)
        self.assertEqual(self.element().demande_depuis, J26)


class FicheEtChoisirTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_fiche_demande_et_enregistre(self):
        rep = self.client.get(reverse("collecte:referentiel_kpi_nouveau") + f"?place={self.ref.code}|")
        self.assertContains(rep, f'name="ajout_depuis__{self.ref.code}"')
        self.assertContains(rep, 'value="2025-01-01"')
        self.nouveau()  # même chemin que la fiche (enregistrer_places), sans tout le formulaire
        from .reglages import enregistrer_places

        class Form:
            elements, cleaned_data = [], {"ajout_place": f"{self.ref.code}|"}
            data = {f"ajout_depuis__{self.ref.code}": "2025-01-01"}
        enregistrer_places(self.admin, Form(), KPI.objects.get(pk="NEW"))
        self.assertEqual(self.element().demande_depuis, J25)
        Form.data = {}
        self.nouveau("DEF")
        Form.cleaned_data = {"ajout_place": f"{self.ref.code}|"}
        enregistrer_places(self.admin, Form(), KPI.objects.get(pk="DEF"))
        self.assertEqual(self.element("DEF").demande_depuis, J26)  # défaut : la période en cours

    def test_page_choisir(self):
        from referentiel.models import Referentiel

        autre = Referentiel.objects.create(code="SRC", nom="Source", ordre=3)
        self.nouveau()
        ElementReferentiel(referentiel=autre, kpi_id="NEW", ordre=1).save()
        url = reverse("parametres:referentiel_choisir", args=[self.ref.code])
        self.assertContains(self.client.get(url + "?source=SRC"), 'name="depuis"')
        self.client.post(url, {"source": "SRC", "kpi": ["NEW"], "depuis": "2024-01-01"})
        self.assertEqual(self.element().demande_depuis, datetime.date(2024, 1, 1))

    def test_ajout_par_la_page_du_referentiel_defaut(self):
        self.nouveau()
        self.client.post(reverse("parametres:referentiels"), {"action": "ajouter_kpi", "ref": self.ref.code, "kpi": "NEW"})
        self.assertEqual(self.element().demande_depuis, J26)


class ClasseurDeConfigurationTests(Base):
    def classeur(self, modifier):
        from openpyxl import load_workbook

        from . import configuration as C

        wb = load_workbook(io.BytesIO(C.exporter().content))
        ws = wb["Éléments"]
        tete = [c.value for c in ws[1]]
        modifier(ws, tete)
        flux = io.BytesIO()
        wb.save(flux)
        return C, flux.getvalue()

    def test_export_et_aller_retour(self):
        from openpyxl import load_workbook

        self.nouveau()
        ElementReferentiel(referentiel=self.ref, kpi_id="NEW", ordre=9).save()
        C, contenu = self.classeur(lambda ws, tete: None)
        ws = load_workbook(io.BytesIO(contenu))["Éléments"]
        tete = [c.value for c in ws[1]]
        self.assertIn("Demandé depuis", tete)
        dates = {ws.cell(r, tete.index("ID KPI") + 1).value: ws.cell(r, tete.index("Demandé depuis") + 1).value
                 for r in range(2, ws.max_row + 1)}
        self.assertIn(dates["EFF"], (None, ""))  # sans date : depuis le début
        self.assertIn(str(dates["NEW"])[:10], ("2026-01-01", "01/01/2026"))
        a = C.analyser(SimpleUploadedFile("conf.xlsx", contenu))
        self.assertTrue(all(c.action == "inchange" for c in a.onglets["Éléments"]),
                        [(c.cle, c.action, c.motif) for c in a.onglets["Éléments"]])

    def test_avance_par_le_fichier_et_recul_refuse(self):
        self.nouveau()
        ElementReferentiel(referentiel=self.ref, kpi_id="NEW", ordre=9).save()

        def poser(valeur):
            def modifier(ws, tete):
                for r in range(2, ws.max_row + 1):
                    if ws.cell(r, tete.index("ID KPI") + 1).value == "NEW":
                        ws.cell(r, tete.index("Demandé depuis") + 1, valeur)
            return modifier
        C, contenu = self.classeur(poser(datetime.date(2025, 1, 1)))
        C.appliquer(self.admin, SimpleUploadedFile("conf.xlsx", contenu), "conf.xlsx")
        self.assertEqual(self.element().demande_depuis, J25)
        self.assertTrue(Journal.objects.filter(champ="Demandé depuis (RAP)").exists())
        # 2025 clos : le KPI n'y est pas encore entré, reculer ne retire rien (accepté) ; rouvert avec une valeur : refusé
        changer_statut(self.admin, self.camp(2025), "rouvrir", garder=False)
        from . import saisie as S

        S.enregistrer(self.admin, self.camp(2025), KPI.objects.get(pk="NEW"), self.e1, "4", False, "")
        C, contenu = self.classeur(poser(datetime.date(2026, 1, 1)))
        a = C.analyser(SimpleUploadedFile("conf.xlsx", contenu))
        ligne = next(c for c in a.onglets["Éléments"] if c.cle.endswith("NEW"))
        self.assertTrue(ligne.motif)
        C.appliquer(self.admin, SimpleUploadedFile("conf.xlsx", contenu), "conf.xlsx")
        self.assertEqual(self.element().demande_depuis, J25)


class ImportDeFichierTests(Base):
    def test_kpi_nouveau_d_un_modele_suit_le_choix(self):
        from . import paquets as PQ

        self.nouveau()
        ElementReferentiel(referentiel=self.ref, kpi_id="NEW", ordre=9).save()
        p = PQ.extraire(self.ref)
        ElementReferentiel.objects.filter(kpi_id="NEW").delete()
        a = PQ.analyser(p, source="rap.json")
        a.depuis = "2025-01-01"
        PQ.appliquer(self.admin, a, "rap.json")
        self.assertEqual(self.element().demande_depuis, J25)
        self.assertTrue(Journal.objects.filter(champ="Demandé depuis (RAP)", objet_id="NEW").exists())
