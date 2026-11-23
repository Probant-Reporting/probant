"""Certificat de clôture (page à imprimer d'une campagne clôturée) : contenu, droits de chaque rôle, lecture seule (aucune ligne
écrite), stabilité de l'empreinte, sept langues, liens d'accès."""
import datetime
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

from parametres.libelles import libelle
from referentiel.models import KPI, Attribution, Utilisateur

from . import administration as A
from . import calcul as C
from . import certificat_cloture as CE
from . import saisie as S
from .aides_tests.lecture_seule import Base
from .models import Alerte, Campagne, DemandeForcage, Journal, Preuve, Reponse

D = Decimal
LANGUES = ("en", "fr", "es", "de", "it", "nl", "pt")
PDF = b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\n"


class AvecCertificat(Base):
    def setUp(self):
        super().setUp()
        self.valideur = Utilisateur.objects.create(username="valideur", email="valideur@exemple.test",
                                                   role=Utilisateur.Role.VALIDATEUR)
        Attribution.objects.create(kpi=self.eff, organisation=self.e1, utilisateur=self.valideur, role=Attribution.Role.VALIDATEUR)
        S.valider(self.contrib, self.c, self.eff, self.e1)
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        Preuve.objects.create(reponse=r, fichier=ContentFile(PDF, name="facture.pdf"), nom_fichier="facture.pdf", taille=len(PDF),
                              depose_par=self.contrib)
        self.alerte_ouverte = Alerte.objects.create(
            campagne=self.c, kpi=self.eff, organisation=self.e2, controle=Alerte.Controle.FORMAT, gravite=Alerte.Gravite.ALERTE,
            message="Format douteux")
        Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.ECART_N1,
                              message="Écart", statut=Alerte.Statut.JUSTIFIEE, justification="Embauches",
                              justifie_par=self.contrib, date_justification=timezone.now())
        Alerte.objects.create(campagne=self.c, kpi=self.taux, organisation=self.e1, controle=Alerte.Controle.HISTORIQUE,
                              message="Historique", statut=Alerte.Statut.CORRIGEE)
        A.changer_statut(self.admin, self.c, "cloturer")
        self.c.refresh_from_db()
        self.url = reverse("collecte:certificat_cloture", args=[self.c.pk])

    def page(self, user, langue="en", **kw):
        self.client.force_login(user)
        if langue:
            self.client.post(reverse("langue"), {"langue": langue})
        return self.client.get(self.url, **kw)

    def texte(self, user, **kw):
        rep = self.page(user, **kw)
        self.assertEqual(rep.status_code, 200)
        return rep.content.decode()

    def compteurs(self):
        return {m.__name__: m.objects.count() for m in (Reponse, Journal, Alerte, Preuve, DemandeForcage, Campagne, Utilisateur,
                                                         Attribution, KPI)}


class ContenuCertificatTests(AvecCertificat):
    def setUp(self):
        super().setUp()

    def test_contenu_en_anglais(self):
        t = self.texte(self.admin, langue="en")
        for attendu in ("Closing certificate", "2026", "Closed by", "admin@exemple.test", "This campaign has not been reopened.",
                        "Scope", "Entity", "Completion", "Evidence files", "Consistency alerts", "Fingerprint of the figures",
                        "Format douteux", "E2", "Issued on"):
            self.assertIn(attendu, t)
        self.assertNotIn("suivi.certificat.", t)

    def test_clotur_par_et_quand_viennent_du_journal(self):
        e = Journal.objects.get(objet="Campagne", objet_id=str(self.c.pk), action="cloturer")
        self.assertEqual(CE.cloture(self.c), (self.admin, e.date))
        d = CE.construire(self.admin, self.c)
        self.assertTrue(d["cloture_connue"])
        self.assertEqual(d["cloture_par"], "admin@exemple.test")

    def test_cloture_non_gardee_n_est_pas_inventee(self):
        Journal.objects.filter(objet="Campagne", objet_id=str(self.c.pk)).delete()
        d = CE.construire(self.admin, self.c)
        self.assertFalse(d["cloture_connue"])
        self.assertEqual((d["cloture_par"], d["cloture_le"]), ("", ""))
        self.assertIn("does not keep who closed this campaign", self.texte(self.admin))

    def test_perimetre_par_niveau(self):
        d = CE.construire(self.admin, self.c)
        self.assertEqual([(t, o) for _, t, o in d["par_niveau"]], [(1, 1), (1, 1), (2, 2)])
        self.assertEqual((d["nb_orgs"], d["nb_ouvertes"]), (4, 4))

    def test_organisation_non_ouverte_dans_la_periode(self):
        self.e2.date_ouverture = self.c.periode.fin + datetime.timedelta(days=30)
        self.e2.save()
        C.oublier_arbre(self.c.periode)  # l'arbre de la clôture est celui gardé : on relit celui d'aujourd'hui
        d = CE.construire(self.admin, self.c)
        self.assertEqual([(t, o) for _, t, o in d["par_niveau"]], [(1, 1), (1, 1), (2, 1)])
        self.assertEqual((d["nb_orgs"], d["nb_ouvertes"]), (4, 3))

    def test_remplissage_valeurs_preuves(self):
        d = CE.construire(self.admin, self.c)
        c = d["remplissage"]
        self.assertEqual((c.total, c.valide), (c.valide + c.brouillon + c.a_saisir, 1))
        self.assertEqual(d["preuves"], 1)
        v = d["valeurs"]
        self.assertEqual(v["saisies"], 3)  # EFF E1, EFF E2, TX E1
        self.assertEqual(v["validees"], 1)
        self.assertEqual(v["forcees"], 0)
        self.assertEqual(v["total"], v["saisies"] + v["calculees"] + v["forcees"])

    def test_forcee_et_na_comptees(self):
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e2)
        Reponse.objects.filter(pk=r.pk).update(origine=Reponse.Origine.FORCEE)
        Reponse.objects.create(periode=self.c.periode, kpi=self.taux, organisation=self.e2, non_applicable=True)
        v = CE.construire(self.admin, self.c)["valeurs"]
        self.assertEqual((v["forcees"], v["na"]), (1, 1))

    def test_alertes_traitees_justifiees_ouvertes(self):
        d = CE.construire(self.admin, self.c)
        n = d["alertes"]
        self.assertEqual((n["traitees"], n["justifiees"], n["ouvertes"], n["total"]), (1, 1, 1, 3))
        self.assertEqual([a["message"] for a in d["alertes_ouvertes"]], ["Format douteux"])
        self.assertEqual(d["alertes_en_plus"], 0)

    def test_liste_courte_des_alertes_ouvertes(self):
        for i in range(CE.MAX_ALERTES_LISTEES + 3):
            Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.REGLE,
                                  message=f"Règle {i}", empreinte=str(i))
        d = CE.construire(self.admin, self.c)
        self.assertEqual(len(d["alertes_ouvertes"]), CE.MAX_ALERTES_LISTEES)
        self.assertEqual(d["alertes_en_plus"], 4)

    def test_reouverture_et_mode(self):
        A.changer_statut(self.admin, self.c, "rouvrir", garder=True)
        A.changer_statut(self.admin, self.c, "cloturer")
        self.c.refresh_from_db()
        n, date, mode = CE.reouvertures(self.c)
        self.assertEqual((n, mode), (1, "gardes"))
        self.assertIsNotNone(date)
        t = self.texte(self.admin)
        self.assertIn("Reopened 1 time.", t)
        self.assertIn("figures of the time kept", t)

    def test_pas_de_reouverture_depuis_la_revue(self):
        c = Campagne.objects.create(exercice=2030, statut=Campagne.Statut.OUVERTE)
        A.changer_statut(self.admin, c, "revue")
        A.changer_statut(self.admin, c, "rouvrir_contributeurs")  # revue -> ouverte : pas une réouverture d'un exercice clos
        A.changer_statut(self.admin, c, "cloturer")
        self.assertEqual(CE.reouvertures(c)[0], 0)

    def test_autres_campagnes_de_la_periode_listees(self):
        d = CE.construire(self.admin, self.c)
        self.assertEqual(d["autres"], [])


class DroitsCertificatTests(AvecCertificat):
    def test_administrateur_et_auditeur_lisent(self):
        for u in (self.admin, self.auditeur):
            with self.subTest(u=u.username):
                self.assertEqual(self.page(u).status_code, 200)

    def test_autres_roles_refuses(self):
        for u in (self.contrib, self.valideur, self.lecteur):
            with self.subTest(u=u.username):
                self.assertEqual(self.page(u).status_code, 403)

    def test_campagne_inexistante_refusee_avant_d_etre_cherchee(self):
        url = reverse("collecte:certificat_cloture", args=[999999])
        for u in (self.contrib, self.valideur, self.lecteur):
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, 403, u.role)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_sans_connexion_renvoi_a_la_connexion(self):
        self.client.logout()
        rep = self.client.get(self.url)
        self.assertEqual(rep.status_code, 302)
        self.assertIn("/connexion/", rep.url)

    def test_auditeur_limite_a_des_organisations_certificat_partiel(self):
        """Limité à des organisations : certificat partiel, marqué comme tel (test_certificat_cloture_partiel.py)."""
        self.auditeur.perimetre_lecture.add(self.e1)
        rep = self.page(self.auditeur)
        self.assertEqual(rep.status_code, 200)
        self.assertIn("Partial certificate: 1 of 4 organisations", rep.content.decode())

    def test_campagne_pas_clôturée_introuvable(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:certificat_cloture", args=[self.c0.pk]))
        self.assertEqual(rep.status_code, 200)  # c0 est clôturée
        A.changer_statut(self.admin, self.c, "rouvrir")
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_bouton_sur_la_fiche_de_la_campagne_cloturee(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("langue"), {"langue": "en"})
        fiche = self.client.get(reverse("collecte:admin_campagne", args=[self.c.pk]), HTTP_X_REQUESTED_WITH="XMLHttpRequest").content.decode()
        self.assertIn(self.url, fiche)
        self.assertIn("Closing certificate", fiche)
        A.changer_statut(self.admin, self.c, "rouvrir")
        fiche = self.client.get(reverse("collecte:admin_campagne", args=[self.c.pk]), HTTP_X_REQUESTED_WITH="XMLHttpRequest").content.decode()
        self.assertNotIn(self.url, fiche)

    def test_lien_dans_l_historique_de_l_auditeur(self):
        self.client.force_login(self.auditeur)
        t = self.client.get(reverse("collecte:historique")).content.decode()
        self.assertIn(self.url, t)
        self.auditeur.perimetre_lecture.add(self.e1)  # limité : la liste reste (certificats partiels)
        self.client.force_login(self.auditeur)
        self.assertIn(self.url, self.client.get(reverse("collecte:historique")).content.decode())


class LectureSeuleCertificatTests(AvecCertificat):
    def test_aucune_ecriture(self):
        for u in (self.admin, self.auditeur):
            self.page(u)  # choisir la langue de l'interface s'écrit au journal : fait avant de compter
        avant = self.compteurs()
        etat = list(Reponse.objects.order_by("pk").values_list("pk", "valeur", "statut", "date_maj"))
        for u in (self.admin, self.auditeur, self.admin):
            self.page(u)
        self.assertEqual(self.compteurs(), avant)
        self.assertEqual(list(Reponse.objects.order_by("pk").values_list("pk", "valeur", "statut", "date_maj")), etat)

    def test_page_non_mise_en_cache(self):
        self.assertIn("no-store", self.page(self.admin)["Cache-Control"])


class EmpreinteTests(AvecCertificat):
    def test_empreinte_stable(self):
        a, n = CE.empreinte(self.c)
        self.assertEqual(CE.empreinte(self.c), (a, n))
        self.assertEqual(len(a), 64)
        self.assertGreater(n, 0)
        t = self.texte(self.admin)
        self.assertTrue(all(a[i:i + 16] in t for i in range(0, 64, 16)))

    def test_calcul_documente(self):
        """Le texte haché est celui de l'en-tête de ``certificat_cloture`` : un tableau JSON d'en-tête, puis une ligne par case."""
        codes = S.codes_campagne(self.c)
        retenus = None if codes is None else codes[1]
        lignes = []
        for r in Reponse.objects.filter(periode=self.c.periode).select_related("organisation"):
            if (retenus is not None and r.kpi_id not in retenus) or (r.valeur is None and not r.non_applicable and not r.texte):
                continue
            v = None if r.valeur is None else format(r.valeur.normalize(), "f")
            lignes.append([r.kpi_id, r.organisation.code, v, r.non_applicable, r.texte])
        lignes.sort(key=lambda x: (x[0], x[1]))
        p = self.c.periode
        morceaux = [json.dumps(["probant-certificat-1", self.c.referentiel_id, p.debut.isoformat(), p.fin.isoformat()],
                               separators=(",", ":"), ensure_ascii=False)]
        morceaux += [json.dumps(l, separators=(",", ":"), ensure_ascii=False) for l in lignes]
        attendu = hashlib.sha256("\n".join(morceaux).encode("utf-8")).hexdigest()
        self.assertEqual(CE.empreinte(self.c)[0], attendu)

    def test_une_valeur_changee_change_l_empreinte(self):
        avant = CE.empreinte(self.c)[0]
        Reponse.objects.filter(periode=self.c.periode, kpi=self.eff, organisation=self.e2).update(valeur=D("41"))
        self.assertNotEqual(CE.empreinte(self.c)[0], avant)

    def test_un_na_ou_un_texte_change_l_empreinte(self):
        avant = CE.empreinte(self.c)[0]
        Reponse.objects.filter(periode=self.c.periode, kpi=self.taux, organisation=self.e1).update(non_applicable=True)
        na = CE.empreinte(self.c)[0]
        self.assertNotEqual(na, avant)
        Reponse.objects.filter(periode=self.c.periode, kpi=self.taux, organisation=self.e1).update(texte="x")
        self.assertNotEqual(CE.empreinte(self.c)[0], na)

    def test_statut_auteur_et_dates_ne_changent_pas_l_empreinte(self):
        avant = CE.empreinte(self.c)[0]
        Reponse.objects.filter(periode=self.c.periode).update(statut=Reponse.Statut.BROUILLON, saisi_par=self.autre)
        self.assertEqual(CE.empreinte(self.c)[0], avant)

    def test_ecriture_decimale_sans_zeros_inutiles(self):
        self.assertEqual([CE._nombre_stable(x) for x in (D("110.0000000000"), D("0.50"), D("-0"), D("0E-10"), D("1E+2"), None)],
                         ["110", "0.5", "0", "0", "100", None])

    def test_case_vide_hors_empreinte(self):
        avant = CE.empreinte(self.c)
        Reponse.objects.create(periode=self.c.periode, kpi=self.taux, organisation=self.e2)
        self.assertEqual(CE.empreinte(self.c), avant)

    def test_autre_campagne_autre_empreinte(self):
        self.assertNotEqual(CE.empreinte(self.c)[0], CE.empreinte(self.c0)[0])


class SeptLanguesCertificatTests(AvecCertificat):
    def test_page_dans_chaque_langue(self):
        vus = set()
        for code in LANGUES:
            with self.subTest(langue=code):
                t = self.texte(self.admin, langue=code)
                self.assertNotIn("suivi.certificat.", t)
                self.assertIn(f'lang="{code}"', t)
                titre = libelle("suivi.certificat.titre", code)
                self.assertIn(titre, t)
                vus.add(titre)
        self.assertEqual(len(vus), 7)

    def test_cles_presentes_dans_les_sept_langues(self):
        racine = Path(__file__).resolve().parent.parent / "libelles"
        tables = {c: json.loads((racine / f"suivi.{c}.json").read_text(encoding="utf-8")) for c in LANGUES}
        cles = {k for k in tables["en"] if k.startswith("suivi.certificat.")}
        self.assertGreater(len(cles), 50)
        for c, t in tables.items():
            self.assertEqual(cles - set(t), set(), c)
        admin = {c: json.loads((racine / f"admin.{c}.json").read_text(encoding="utf-8")) for c in LANGUES}
        for c, t in admin.items():
            self.assertIn("admin.campagne.certificat", t, c)
            self.assertIn("admin.journal.certificats", t, c)
