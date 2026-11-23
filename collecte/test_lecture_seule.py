"""Rôles en lecture seule : le lecteur (Visualisation, Tableau de bord) et l'auditeur (tout ce qu'il faut pour un audit),
qui ne saisissent, ne valident, ne justifient et ne règlent jamais rien ; périmètre limité à des organisations."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from referentiel.models import Utilisateur

from . import exports as E
from . import saisie as S
from . import visualisation as V
from .models import Alerte, Journal, Preuve, Reponse, VueVisu
from .aides_tests.lecture_seule import Base


class LecteurTests(Base):
    def test_visualisation_et_tableau_de_bord_seulement(self):
        self.client.force_login(self.lecteur)
        self.assertRedirects(self.client.get("/"), reverse("collecte:visu"))
        self.assertEqual(self.client.get(reverse("collecte:visu_kpi", args=["DBL"])).status_code, 200)  # voit tous les KPI
        self.assertEqual(self.client.get(reverse("collecte:tableau_de_bord")).status_code, 200)
        for page in ("saisie", "pour_moi", "coherence", "echanges", "echanges_importer", "historique", "admin_accueil"):
            self.assertEqual(self.client.get(reverse(f"collecte:{page}")).status_code, 403, page)
        self.assertEqual(self.client.get(self.cellule()).status_code, 403)
        rep = self.client.get(reverse("collecte:visu"))
        self.assertNotContains(rep, f'href="{reverse("collecte:saisie")}"')  # onglets : Tableau de bord et Visualisation
        self.assertContains(rep, f'href="{reverse("collecte:tableau_de_bord")}"')
        # ses propres vues : permises (elles ne touchent aucune donnée), jamais partagées
        self.client.post(reverse("collecte:visu_vue_creer"), '{"nom": "Comité", "partage": true, "visuels": [{"type": "chiffre", "kpis": ["EFF"]}]}',
                         content_type="application/json")
        t = VueVisu.objects.get(nom="Comité")
        self.assertEqual((t.proprietaire, t.partage), (self.lecteur, False))

    def test_rien_ne_s_ecrit(self):
        self.client.force_login(self.lecteur)
        avant = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1).valeur
        rep = self.client.post(self.cellule(), {"action": "enregistrer", "valeur": "999"})
        self.assertEqual(rep.status_code, 403)
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1).valeur, avant)
        self.assertEqual(self.client.post(reverse("collecte:echanges_importer"), {"action": "confirmer"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("collecte:admin_comptes")).status_code, 403)


class AuditeurTests(Base):
    def test_lit_tout_en_lecture(self):
        p = Preuve.objects.create(reponse=Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1),
                                  fichier=SimpleUploadedFile("facture.pdf", b"%PDF-1.4 essai"))
        self.client.force_login(self.auditeur)
        self.assertRedirects(self.client.get("/"), reverse("collecte:saisie"))
        rep = self.client.get(reverse("collecte:saisie") + f"?campagne={self.c.pk}&org={self.e2.pk}")
        self.assertEqual(rep.status_code, 200)  # toutes les organisations, comme l'admin
        self.assertEqual({o.nom for o, *_ in S.organisations_visibles(self.auditeur, self.c)} >= {"E1", "E2", "Pays"}, True)
        rep = self.client.get(self.cellule(), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(rep.status_code, 200)
        d = S.droits(self.auditeur, self.c, self.eff, self.e1)
        self.assertEqual((d.voir, d.modifier, d.repasser_brouillon), (True, False, False))
        self.assertEqual(self.client.get(reverse("collecte:preuve", args=[p.pk])).status_code, 200)
        self.assertContains(self.client.get(reverse("collecte:historique")), "Historique")
        self.assertEqual(self.client.get(reverse("collecte:coherence")).status_code, 200)
        self.assertEqual(self.client.get(reverse("collecte:echanges")).status_code, 200)
        rep = self.client.post(reverse("collecte:echanges_exporter"), {"action": "telecharger", "presentation": "base", "exercices": ["courant"],
                                                                     "niveaux": E.N.codes()})
        self.assertEqual(rep.status_code, 200)  # télécharger un export : une lecture
        self.assertIn("spreadsheetml", rep["Content-Type"])
        self.assertIsNone(E.perimetre(self.auditeur, S.arbre_organisations())[0])  # tout le périmètre des exports

    def test_ne_modifie_rien(self):
        self.client.force_login(self.auditeur)
        nb_journal, nb_alertes = Journal.objects.count(), Alerte.objects.count()
        for action in ("enregistrer", "valider", "brouillon", "justifier"):
            self.assertEqual(self.client.post(self.cellule(), {"action": action, "valeur": "1"}).status_code, 403, action)
        self.assertEqual(self.client.get(reverse("collecte:echanges_importer")).status_code, 403)
        self.assertEqual(self.client.get(reverse("collecte:pour_moi")).status_code, 403)
        self.client.get(reverse("collecte:coherence"))  # l'ouvrir ne recalcule pas les alertes
        self.assertEqual((Journal.objects.count(), Alerte.objects.count()), (nb_journal, nb_alertes))
        self.assertTrue(S.lecture_seule(self.auditeur, self.c))

    def test_perimetre_limite_a_des_organisations(self):
        self.auditeur.perimetre_lecture.add(self.e1)
        u = Utilisateur.objects.get(pk=self.auditeur.pk)
        self.assertEqual({o.nom for _, o in S.cellules(u)}, {"E1"})
        self.assertEqual([o.nom for o in V.Source(u, ["EFF"]).organisations()], ["E1"])
        paires, resultats = E.perimetre(u, S.arbre_organisations())
        self.assertEqual(({o for _, o in paires}, resultats), ({self.e1.pk}, {self.e1.pk}))
        self.client.force_login(u)
        self.assertEqual(self.client.get(self.cellule(org=self.e2)).status_code, 403)


class ComptesTests(Base):
    def test_creer_un_lecteur_limite(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:admin_compte_nouveau"))
        self.assertContains(rep, "Lecteur")
        self.assertContains(rep, "Auditeur")
        self.client.post(reverse("collecte:admin_compte_nouveau"), {
            "first_name": "Dana", "last_name": "Direction", "email": "dana@exemple.test", "role": "lecteur",
            "perimetre_lecture": [self.p.pk], "is_active": "on"})
        u = Utilisateur.objects.get(email="dana@exemple.test")
        self.assertEqual((u.role, u.is_staff, list(u.perimetre_lecture.all())), ("lecteur", False, [self.p]))
        self.assertEqual(u.orgs_permises(), {self.p.pk, self.e1.pk, self.e2.pk})
        # un lecteur ou un auditeur n'est jamais proposé comme SPOC, ni attribué
        self.assertNotIn("dana@exemple.test", self.client.get(reverse("collecte:admin_attributions")).content.decode())
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            S.attribuer(self.admin, [(self.eff, self.e1)], u)


class VuesVisualisationTests(Base):
    """Visualisation v2 : les vues personnelles sont des préférences (permises), le partage ne l'est jamais."""

    def test_noms_d_adresse(self):
        from . import lecture_seule as LS

        for nom in ("visu_vue", "visu_vue_donnees", "visu_catalogue", "visu_vue_excel", "visu_vue_partage"):
            self.assertIn(nom, LS.PAGES_LECTEUR)
        self.assertNotIn("visu_vue_partage", LS.ECRITURES_PERMISES)
        for nom in ("visu_donnees", "visu_excel", "visu_vue_creer", "visu_vue_enregistrer", "visu_vues_ordre", "visu_vue_preferee"):
            self.assertIn(nom, LS.ECRITURES_PERMISES)

    def test_partage_refuse_avant_la_vue(self):
        from .models import VueVisu

        v = VueVisu.objects.create(nom="Perso", proprietaire=self.lecteur)
        for u in (self.lecteur, self.auditeur):
            self.client.force_login(u)
            rep = self.client.post(reverse("collecte:visu_vue_partage", args=[v.pk]), '{"partage": true}', content_type="application/json")
            self.assertEqual(rep.status_code, 403)
        v.refresh_from_db()
        self.assertFalse(v.partage)


class PagesLibresTests(Base):
    def test_sante_repond_pareil_a_tout_le_monde(self):
        """/sante/ (supervision de l'IT) : même réponse pour un lecteur ou un auditeur connecté que sans connexion."""
        url, externe = reverse("parametres:sante"), {"HTTP_X_FORWARDED_FOR": "203.0.113.5"}  # appel de la supervision
        self.assertEqual(self.client.get(url, **externe).json(), {"etat": "ok"})
        for u in (self.lecteur, self.auditeur):
            self.client.force_login(u)
            rep = self.client.get(url, **externe)
            self.assertEqual((rep.status_code, rep.json()), (200, {"etat": "ok"}), u.username)
            self.client.logout()
