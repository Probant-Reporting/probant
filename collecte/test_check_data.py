"""Contrôle de cohérence de la base (commande check_data) : chaque invariant violé exprès est détecté, une base
saine ne donne aucun problème, rien n'est modifié ; résultat gardé (fichier JSON), visible dans /sante/, Paramètres ›
Hébergement et « À traiter » ; planification de chaque nuit. Données inventées."""
import datetime
import io
import json
import shutil
import tempfile
import zipfile
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from referentiel.models import KPI, Attribution, ElementReferentiel, KPIFormule, Niveau, Organisation, Utilisateur

from . import controle_donnees as CD
from .calcul import recalculer
from .models import Periode, Preuve, Reponse
from .outils_tests import RetourSerialiseIndependantDeLOrdre
from .aides_tests.arbre import Arbre


class Base(Arbre):
    """Arbre de test (Groupe > Pays > E1, E2 ; Pays 2 > E3), 2025 clôturé et 2026 ouvert ; EFF saisi par entité (somme),
    DBL = [EFF] * 2 calculé, TX pourcentage saisi ; dossiers des fichiers et des sauvegardes temporaires."""

    databases = {"default", "commun"}

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.reglages = override_settings(MEDIA_ROOT=self.tmp / "files", SAUVEGARDES_DIR=self.tmp / "backups")
        self.reglages.enable()
        self.kpi("EFF")
        self.kpi("DBL", "Calculé", "[EFF] * 2")
        self.kpi("TX", agg="Aucune", type_reponse_id="Pourcentage")
        for c in (self.c0, self.c):
            for k in ("EFF", "DBL", "TX"):
                ElementReferentiel.objects.get_or_create(referentiel=c.referentiel, kpi_id=k)
            for o, v in ((self.e1, 10), (self.e2, 20), (self.e3, 5)):
                self.saisir("EFF", o, v, camp=c)
                self.saisir("TX", o, "0.25", camp=c)
            recalculer(c)

    def tearDown(self):
        self.reglages.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def constats(self):
        r = CD.controler()
        return {c["check"]: c for c in r["problems"]}, r

    def assertTrouve(self, code, gravite, n=None):
        constats, _ = self.constats()
        self.assertIn(code, constats, constats)
        self.assertEqual(constats[code]["severity"], gravite)
        if n is not None:
            self.assertEqual(constats[code]["count"], n, constats[code])
        return constats[code]


class BaseSaine(Base):
    def test_aucun_probleme(self):
        constats, r = self.constats()
        self.assertEqual((r["errors"], r["warnings"]), (0, 0), constats)
        self.assertEqual(set(constats), {"backup_none"})  # pas encore de sauvegarde : pour information
        self.assertEqual(r["space"], "principal")

    def test_ne_modifie_rien(self):
        Reponse.objects.filter(kpi_id="DBL", organisation=self.e1, periode=self.c.periode).update(valeur=D(999))
        avant = sorted(Reponse.objects.values_list("id", "valeur", "statut", "origine", "texte", "non_applicable"))
        self.constats()
        self.assertEqual(sorted(Reponse.objects.values_list("id", "valeur", "statut", "origine", "texte", "non_applicable")), avant)

    def test_rapide(self):
        _, r = self.constats()
        self.assertLess(r["seconds"], 10)
        self.assertEqual(set(r["durations"]), {nom for nom, _ in CD.CONTROLES})


class Calculs(Base):
    def test_case_calculee_modifiee(self):
        Reponse.objects.filter(kpi_id="DBL", organisation=self.e1, periode=self.c.periode).update(valeur=D(999))
        c = self.assertTrouve("calculated_mismatch", CD.ERREUR, 1)
        self.assertIn("2026 · DBL · E1: stored 999 (calcule), expected 20 (calcule)", c["examples"])

    def test_total_faux_et_case_manquante(self):
        Reponse.objects.filter(kpi_id="EFF", organisation=self.g, periode=self.c.periode).update(valeur=D(1))
        Reponse.objects.filter(kpi_id="DBL", organisation=self.p, periode=self.c.periode).delete()
        c = self.assertTrouve("calculated_mismatch", CD.ERREUR, 2)
        self.assertIn("2026 · DBL · Pays: missing (expected 60)", c["examples"])

    def test_case_vide_pas_encore_ecrite_n_est_pas_un_probleme(self):
        """Campagne créée sans recalcul (reprise) : une case calculée vide attendue mais absente = la même chose."""
        Reponse.objects.filter(kpi_id="EFF", organisation=self.e3, periode=self.c.periode).delete()
        recalculer(self.c)
        Reponse.objects.filter(kpi_id__in=["EFF", "DBL"], organisation__in=[self.p2, self.g], periode=self.c.periode).delete()
        constats, r = self.constats()
        self.assertNotIn("calculated_mismatch", constats)

    def test_case_que_les_reglages_ne_produisent_plus(self):
        KPI.objects.filter(code="DBL").update(methode_agregation=KPI.Agregation.AUCUNE)  # sans recalcul
        c = self.assertTrouve("calculated_mismatch", CD.ERREUR, 3)  # Pays, Pays 2, Groupe
        self.assertTrue(all("no longer produced" in e for e in c["examples"]))

    def test_periode_cloturee_signalee_seulement(self):
        Reponse.objects.filter(kpi_id="EFF", organisation=self.g, periode=self.c0.periode).update(valeur=D(1))
        constats, r = self.constats()
        self.assertNotIn("calculated_mismatch", constats)
        self.assertEqual(constats["calculated_mismatch_closed"]["severity"], CD.INFO)
        self.assertEqual(r["errors"], 0)

    def test_arrondis_de_stockage_toleres(self):
        """SQLite garde ~15 chiffres significatifs : 154130.6082191780 relu pour 154130.6082191781 n'est pas un écart."""
        Reponse.objects.filter(kpi_id="DBL", organisation=self.e1, periode=self.c.periode).update(valeur=D("20.0000000001"))
        self.assertNotIn("calculated_mismatch", self.constats()[0])
        Reponse.objects.filter(kpi_id="DBL", organisation=self.e1, periode=self.c.periode).update(valeur=D("20.001"))
        self.assertIn("calculated_mismatch", self.constats()[0])


class Reponses(Base):
    def test_kpi_supprime(self):
        # contrainte de clé étrangère différée (vérifiée à la validation de la transaction, jamais faite ici) : comme une
        # base restaurée ou modifiée hors de l'outil
        r = Reponse.objects.create(periode=self.c.periode, kpi_id="FANTOME", organisation=self.e1, valeur=D(1),
                                   origine=Reponse.Origine.SAISIE, statut=Reponse.Statut.BROUILLON)
        try:
            c = self.assertTrouve("orphan_answers", CD.ERREUR, 1)
            self.assertIn("KPI no longer exists", c["examples"][0])
        finally:
            r.delete()

    def test_periode_sans_campagne(self):
        p = Periode.objects.create(type="annee", debut=datetime.date(2030, 1, 1), fin=datetime.date(2030, 12, 31), libelle="2030")
        Reponse.objects.create(periode=p, kpi_id="EFF", organisation=self.e1, valeur=D(1), origine=Reponse.Origine.SAISIE)
        c = self.assertTrouve("orphan_answers", CD.AVERTISSEMENT, 1)
        self.assertIn("2030 · EFF · E1", c["examples"][0])

    def test_doublons(self):
        if connection.vendor == "postgresql":  # contrainte retirée le temps du test (transaction annulée à la fin)
            with connection.cursor() as cur:
                cur.execute("SET CONSTRAINTS ALL IMMEDIATE")  # clés étrangères différées vérifiées avant de toucher la table
                cur.execute('ALTER TABLE "collecte_reponse" DROP CONSTRAINT "reponse_unique"')
                cur.execute("SET CONSTRAINTS ALL DEFERRED")
            Reponse.objects.create(periode=self.c.periode, kpi_id="EFF", organisation=self.e1, valeur=D(11))
        else:  # SQLite : contrainte dans la définition de la table ; le contrôle reste un filet (base d'ailleurs)
            vrai = CD._doublons
            CD._doublons = lambda: list(vrai()) + [(self.c.periode_id, "EFF", self.e1.id, 2)]
            self.addCleanup(setattr, CD, "_doublons", vrai)
        c = self.assertTrouve("duplicate_answers", CD.ERREUR, 1)
        self.assertEqual(c["examples"], ["2026 · EFF · E1: 2 answers"])

    def test_statuts_incoherents(self):
        R = Reponse
        R.objects.filter(kpi_id="EFF", organisation=self.e1, periode=self.c.periode).update(
            valeur=None, statut=R.Statut.VALIDE)  # validé sans valeur ni N/A
        R.objects.filter(kpi_id="EFF", organisation=self.e2, periode=self.c.periode).update(origine=R.Origine.CALCUL, statut=R.Statut.CALCULE)
        R.objects.filter(kpi_id="DBL", organisation=self.e3, periode=self.c.periode).update(statut=R.Statut.BROUILLON)
        R.objects.filter(kpi_id="TX", organisation=self.e3, periode=self.c.periode).update(non_applicable=True)
        c = self.assertTrouve("inconsistent_status", CD.ERREUR, 4)
        textes = " | ".join(c["examples"])
        for attendu in ("E1: validated without a value or N/A", "EFF · E2: calculated origin on an entered KPI",
                        "DBL · E3: calculated cell with status \"brouillon\"", "TX · E3: N/A with a value"):
            self.assertIn(attendu, textes)

    def test_pourcentage_hors_bornes(self):
        Reponse.objects.filter(kpi_id="TX", organisation=self.e1, periode=self.c.periode).update(valeur=D(25))
        c = self.assertTrouve("percentage_out_of_range", CD.AVERTISSEMENT, 1)
        self.assertIn("2026 · TX · E1: 2500 %", c["examples"][0])

    def test_kpi_calcule_importe_tel_quel(self):
        Reponse.objects.filter(kpi_id="DBL", organisation=self.e1, periode=self.c.periode).update(
            origine=Reponse.Origine.IMPORT, statut=Reponse.Statut.VALIDE, valeur=D(7))
        c = self.assertTrouve("imported_calculated_open", CD.AVERTISSEMENT, 1)
        self.assertIn("2026 · DBL · E1: imported as is (7)", c["examples"][0])
        Reponse.objects.filter(kpi_id="DBL", organisation=self.e1, periode=self.c0.periode).update(
            origine=Reponse.Origine.IMPORT, statut=Reponse.Statut.VALIDE)  # période clôturée : le chiffre officiel
        self.assertEqual(self.assertTrouve("imported_calculated_open", CD.AVERTISSEMENT)["count"], 1)


class Attributions(Base):
    def test_compte_inactif_lecture_seule_et_organisation_fermee(self):
        parti = Utilisateur.objects.create(username="parti", email="parti@exemple.test", is_active=False)
        lecteur = Utilisateur.objects.create(username="lecteur", email="lecteur@exemple.test", role=Utilisateur.Role.LECTEUR)
        actif = Utilisateur.objects.create(username="actif", email="actif@exemple.test")
        Attribution.objects.create(kpi_id="EFF", organisation=self.e1, utilisateur=parti)
        Attribution.objects.create(kpi_id="EFF", organisation=self.e2, utilisateur=lecteur)
        Attribution.objects.create(kpi_id="EFF", organisation=self.e3, utilisateur=actif)
        Organisation.objects.filter(pk=self.e3.pk).update(actif=False, date_desactivation=datetime.date(2025, 6, 30))
        constats, _ = self.constats()
        self.assertEqual(constats["assignments_inactive_account"]["count"], 2)
        self.assertEqual(constats["assignments_inactive_account"]["severity"], CD.AVERTISSEMENT)
        self.assertEqual(constats["assignments_closed_organisation"]["severity"], CD.INFO)  # fermée en 2025 : plus demandée
        Organisation.objects.filter(pk=self.e3.pk).update(date_desactivation=datetime.date(2026, 3, 31))
        self.assertNotIn("assignments_closed_organisation", self.constats()[0])  # ouverte pendant 2026 : encore demandée

    def test_sans_campagne_ouverte_rien_a_dire(self):
        parti = Utilisateur.objects.create(username="parti", email="parti@exemple.test", is_active=False)
        Attribution.objects.create(kpi_id="EFF", organisation=self.e1, utilisateur=parti)
        self.c.statut = self.c.Statut.CLOTUREE
        self.c.save()
        self.assertNotIn("assignments_inactive_account", self.constats()[0])


class Preuves(Base):
    def test_fichier_manquant_et_fichier_orphelin(self):
        r = Reponse.objects.get(kpi_id="EFF", organisation=self.e1, periode=self.c.periode)
        present = self.tmp / "files" / "evidence" / "2026" / "E1" / "EFF" / "facture.pdf"
        present.parent.mkdir(parents=True)
        present.write_bytes(b"%PDF-1.4 essai")
        Preuve.objects.bulk_create([Preuve(reponse=r, fichier="evidence/2026/E1/EFF/facture.pdf", nom_fichier="facture.pdf"),
                                    Preuve(reponse=r, fichier="evidence/2026/E1/EFF/perdue.pdf", nom_fichier="perdue.pdf")])
        orphelin = self.tmp / "files" / "evidence" / "2025" / "E2" / "EFF" / "oubliee.png"
        orphelin.parent.mkdir(parents=True)
        orphelin.write_bytes(b"\x89PNG\r\n\x1a\n")
        constats, _ = self.constats()
        self.assertEqual(constats["evidence_missing"]["examples"], ["EFF · E1: evidence/2026/E1/EFF/perdue.pdf"])
        self.assertEqual(constats["evidence_missing"]["severity"], CD.ERREUR)
        self.assertEqual(constats["evidence_orphan_files"]["examples"], ["evidence/2025/E2/EFF/oubliee.png"])
        self.assertEqual(constats["evidence_orphan_files"]["severity"], CD.AVERTISSEMENT)


class Formules(Base):
    def test_formule_cassee(self):
        KPI.objects.filter(code="DBL").update(formule="[INCONNU] * 2")  # sans passer par la fiche
        constats, _ = self.constats()
        self.assertEqual(constats["broken_formulas"]["severity"], CD.AVERTISSEMENT)
        self.assertIn("DBL", constats["broken_formulas"]["examples"][0])
        self.assertIn("DBL: missing INCONNU; extra EFF", constats["formula_dependencies"]["examples"])

    def test_dependances_pas_a_jour(self):
        KPI.objects.filter(code="DBL").update(formule="[EFF] * 2 + [EFF@N-1]")
        c = self.assertTrouve("formula_dependencies", CD.ERREUR, 1)
        self.assertEqual(c["examples"], ["DBL: missing EFF@N-1"])
        KPIFormule.objects.create(kpi_calcule_id="EFF", kpi_source_id="TX")  # dépendance d'un KPI saisi
        self.assertEqual(self.assertTrouve("formula_dependencies", CD.ERREUR)["count"], 2)


class ArbreDesOrganisations(Base):
    def test_boucle(self):
        Organisation.objects.filter(pk=self.g.pk).update(parent=self.e1)
        c = self.assertTrouve("tree", CD.ERREUR)
        textes = " | ".join(c["examples"])
        self.assertIn("Groupe: loop in the tree", textes)
        self.assertIn("Groupe: top-level", textes)

    def test_niveaux_incoherents(self):
        Organisation.objects.filter(pk=self.e2.pk).update(parent=self.e1)  # entité sous une entité
        Organisation.objects.filter(pk=self.p.pk).update(actif=False)  # E1 collectée sous un pays qui ne l'est plus
        Organisation.objects.create(nom="Sans parent", niveau_id=Niveau.SITE)
        textes = " | ".join(self.assertTrouve("tree", CD.ERREUR)["examples"])
        self.assertIn("E2 (Entité): attached to E1 (Entité), which is not at a higher level", textes)
        self.assertIn("E1: collected but attached to Pays, which is not collected any more", textes)
        self.assertIn("Sans parent: not attached to any organisation", textes)


class Sauvegarde(Base):
    def archive(self, nom, contenu=None, abimee=False):
        d = self.tmp / "backups"
        d.mkdir(parents=True, exist_ok=True)
        if abimee:
            (d / nom).write_bytes(b"PK\x03\x04 pas un zip")
            return
        with zipfile.ZipFile(d / nom, "w") as z:
            z.writestr("backup.json", json.dumps(contenu or {"format": 1, "outil": "probant", "espace": "principal"}))
            z.writestr("database.sqlite3", b"base")

    def test_derniere_sauvegarde_lisible(self):
        self.archive("backup-20261030-023000-auto.zip", abimee=True)  # ancienne : seule la plus récente compte
        self.archive("backup-20261031-023000-auto.zip")
        self.assertEqual(self.constats()[1]["errors"], 0)

    def test_derniere_sauvegarde_abimee(self):
        self.archive("backup-20261031-023000-auto.zip", abimee=True)
        c = self.assertTrouve("backup_unreadable", CD.ERREUR)
        self.assertIn("backup-20261031-023000-auto.zip", c["examples"][0])

    def test_sans_fichier_de_base(self):
        d = self.tmp / "backups"
        d.mkdir(parents=True)
        with zipfile.ZipFile(d / "backup-20261031-023000.zip", "w") as z:
            z.writestr("backup.json", json.dumps({"format": 1, "outil": "probant"}))
        self.assertTrouve("backup_unreadable", CD.ERREUR)


class Resultats(Base):
    def test_commande_json_et_fichier_garde(self):
        sortie = io.StringIO()
        call_command("check_data", "--json", stdout=sortie)
        r = json.loads(sortie.getvalue())
        self.assertEqual((r["errors"], r["warnings"], r["space"]), (0, 0, "principal"))
        self.assertEqual(CD.dernier()["date"], r["date"])
        self.assertTrue((self.tmp / "backups" / "data-checks.json").is_file())
        sortie = io.StringIO()
        call_command("controler_donnees", stdout=sortie)  # nom français
        self.assertIn("0 error(s), 0 warning(s)", sortie.getvalue())
        self.assertEqual(len(CD.resultats()), 2)

    def test_code_de_sortie_et_sortie_lisible(self):
        Reponse.objects.filter(kpi_id="DBL", organisation=self.e1, periode=self.c.periode).update(valeur=D(999))
        sortie = io.StringIO()
        with self.assertRaises(SystemExit) as e:
            call_command("check_data", "--no-save", stdout=sortie)
        self.assertEqual(e.exception.code, 1)
        self.assertIn("[ERROR] calculated_mismatch", sortie.getvalue())
        self.assertEqual(CD.resultats(), [])  # --no-save

    def test_derniers_resultats_seulement(self):
        for i in range(CD.GARDES + 3):
            CD.enregistrer({"date": f"2026-10-{i + 1:02d}T03:30:00+01:00", "errors": 0, "warnings": 0, "problems": []})
        self.assertEqual(len(CD.resultats()), CD.GARDES)
        self.assertEqual(CD.dernier()["date"], "2026-10-13T03:30:00+01:00")

    def test_etats(self):
        self.assertEqual(CD.etat()["etat"], "never")
        maintenant = timezone.now()
        CD.enregistrer({"date": (maintenant - datetime.timedelta(hours=3)).isoformat(), "errors": 0, "warnings": 0, "problems": []})
        self.assertEqual(CD.etat()["etat"], "ok")
        CD.enregistrer({"date": (maintenant - datetime.timedelta(hours=2)).isoformat(), "errors": 0, "warnings": 1,
                        "problems": [{"check": "tree", "severity": "warning", "count": 1, "examples": []}]})
        self.assertEqual(CD.etat()["etat"], "problems")
        self.assertEqual(CD.etat(maintenant + datetime.timedelta(hours=47))["etat"], "late")
        (self.tmp / "backups" / "data-checks.json").write_text("{pas du json", encoding="utf-8")
        self.assertEqual(CD.etat()["etat"], "never")  # fichier illisible : comme jamais fait, sans erreur

    def test_planification(self):
        """Un tour du planificateur : un espace jamais contrôlé l'est tout de suite ; le lendemain avant l'heure, rien."""
        def un_tour():
            with mock.patch.object(CD.time, "sleep", side_effect=KeyboardInterrupt), \
                    mock.patch("django.db.connections.close_all"), self.assertNoLogs("reporting.controle", "ERROR"), \
                    self.assertRaises(KeyboardInterrupt):
                CD.planifier("03:30")

        un_tour()
        self.assertEqual(len(CD.resultats()), 1)
        un_tour()
        self.assertEqual(len(CD.resultats()), 1)  # déjà fait depuis la dernière échéance
        vieux = CD.dernier()
        vieux["date"] = (timezone.now() - datetime.timedelta(days=2)).isoformat()
        CD.fichier().write_text(json.dumps({"results": [vieux]}), encoding="utf-8")
        un_tour()  # échéance manquée (serveur arrêté) : rattrapée tout de suite
        self.assertEqual(len(CD.resultats()), 2)


class Affichage(Base):
    def setUp(self):
        super().setUp()
        self.admin.role = Utilisateur.Role.ADMIN
        self.admin.save()
        self.client.force_login(self.admin)

    def probleme(self):
        Reponse.objects.filter(kpi_id="DBL", organisation=self.e1, periode=self.c.periode).update(valeur=D(999))
        CD.controler_et_enregistrer()

    def test_sante_jamais_en_erreur_pour_les_donnees(self):
        d = self.client.get(reverse("parametres:sante")).json()
        self.assertEqual((d["etat"], d["controle_donnees"]["etat"]), ("ok", "never"))
        self.probleme()
        rep = self.client.get(reverse("parametres:sante"))
        self.assertEqual(rep.status_code, 200)
        d = rep.json()
        self.assertEqual(d["etat"], "ok")
        self.assertEqual((d["controle_donnees"]["etat"], d["controle_donnees"]["erreurs"]), ("problems", 1))
        self.assertIn("derniere_sauvegarde", d)  # clés existantes inchangées
        self.client.logout()
        public = self.client.get(reverse("parametres:sante"), HTTP_X_FORWARDED_FOR="203.0.113.9").json()
        self.assertEqual(public, {"etat": "ok"})  # sans connexion, de l'extérieur : l'état seul, comme avant

    def test_hebergement_et_a_traiter(self):
        html = self.client.get(reverse("parametres:hebergement")).content.decode()
        self.assertIn('id="controle-donnees"', html)
        self.assertIn("Pas encore fait", html)
        self.probleme()
        html = self.client.get(reverse("parametres:hebergement")).content.decode()
        self.assertIn("1 case calculée différente d&#x27;un recalcul", html)
        self.assertIn("2026 · DBL · E1: stored 999", html)
        accueil = self.client.get(reverse("collecte:admin_accueil")).content.decode()
        self.assertIn("Contrôle des données : 1 point à corriger", accueil)
        self.assertIn("#controle-donnees", accueil)

    def test_controler_maintenant(self):
        rep = self.client.post(reverse("parametres:hebergement"), {"action": "controler"})
        self.assertRedirects(rep, reverse("parametres:hebergement") + "#controle-donnees", fetch_redirect_response=False)
        self.assertEqual(CD.dernier()["errors"], 0)
        html = self.client.get(reverse("parametres:hebergement")).content.decode()
        self.assertIn("Aucun problème trouvé.", html)

    def test_anglais_et_espagnol(self):
        self.probleme()
        for langue, attendu in (("en", "1 calculated cell differs from a recalculation"),
                                ("es", "1 celda calculada distinta de un recálculo")):
            self.admin.langue = langue
            self.admin.save()
            self.assertContains(self.client.get(reverse("parametres:hebergement")), attendu)

    def test_reserve_a_l_admin(self):
        c = Utilisateur.objects.create(username="c", email="c@exemple.test", role=Utilisateur.Role.CONTRIBUTEUR)
        self.client.force_login(c)
        self.assertEqual(self.client.post(reverse("parametres:hebergement"), {"action": "controler"}).status_code, 403)
        self.assertEqual(CD.resultats(), [])


class LectureSeule(RetourSerialiseIndependantDeLOrdre, TransactionTestCase):
    """Hors transaction (commande, nuit) : SQLite en transaction différée (les réglages de l'outil ouvrent en IMMEDIATE,
    qui bloquerait les saisies pendant le contrôle), PostgreSQL en lecture seule ; tout est annulé à la fin."""

    databases = {"default", "commun"}
    # base remise dans son état d'origine à la fin (et non vidée) ; l'indépendance de l'ordre des tests (types de contenu
    # recréés par un vidage précédent) est assurée par RetourSerialiseIndependantDeLOrdre
    serialized_rollback = True

    def test_transaction(self):
        from espaces import contexte as ESP

        cx = ESP.connexion()
        avant = getattr(cx, "transaction_mode", None)
        with CD._lecture_seule():
            self.assertTrue(cx.in_atomic_block)
            if cx.vendor == "sqlite":
                self.assertEqual(cx.transaction_mode, "DEFERRED")
            else:
                with cx.cursor() as c:
                    c.execute("SHOW transaction_read_only")
                    self.assertEqual(c.fetchone()[0], "on")
            Organisation.objects.count()
        self.assertEqual(getattr(cx, "transaction_mode", None), avant)
        self.assertFalse(cx.in_atomic_block)
