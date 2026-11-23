"""Gros volumes : pas de requête à plus de paramètres que SQLite n'en accepte, pas de requête par ligne."""
import sqlite3
from decimal import Decimal

from django.db import connection
from django.db.models import Q
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from parametres import langues as L
from referentiel.models import Attribution, Niveau, Organisation, Utilisateur

from . import coherence as CO
from . import saisie as S
from .lots import par_lots
from .models import Campagne, Preuve, Reponse
from .aides_tests.vitesse import Base, requetes

D = Decimal


class LimiteSQLite:
    """Abaisse la limite de paramètres de SQLite le temps d'un test (32 766 par défaut : trop long à atteindre)."""

    def abaisser(self, n):
        if connection.vendor != "sqlite":
            self.skipTest("limite propre à SQLite")
        connection.ensure_connection()
        self._ancienne = connection.connection.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
        connection.connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, n)
        self.addCleanup(connection.connection.setlimit, sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, self._ancienne)


class ParLots(TestCase):
    def test_decoupe(self):
        self.assertEqual(list(par_lots(range(5), 2)), [[0, 1], [2, 3], [4]])
        self.assertEqual(list(par_lots([], 2)), [])


class LignesSansPlafond(LimiteSQLite, Base):
    """construire_lignes ne passe plus les identifiants des réponses en paramètres (prefetch des preuves)."""

    def setUp(self):
        super().setUp()
        self.admin.is_superuser = True
        self.admin.save()
        self.entites = self.entites + [Organisation.objects.create(nom=f"X{i}", niveau_id=Niveau.ENTITY, parent=self.p) for i in range(50)]
        self.ajouter_kpis(3)  # 3 KPI x 54 entités : 162 réponses de 2026
        r = Reponse.objects.filter(periode=self.c.periode).first()
        Preuve.objects.bulk_create([Preuve(reponse=r, fichier="preuves/a.pdf", nom_fichier="a.pdf"),
                                    Preuve(reponse=r, fichier="preuves/b.pdf", nom_fichier="b.pdf")])  # sans save() : pas de fichier réel
        self.avec_preuves = (r.kpi_id, r.organisation_id)

    def paires(self):
        return [(k, o) for k in self.kpis for o in self.entites]

    def test_lignes_et_preuves_sous_limite_basse(self):
        # limite abaissée AVANT toute requête de ce genre (sqlite3 garde les requêtes préparées en cache, sans revérifier la limite)
        self.abaisser(100)
        with self.assertRaises(Exception):  # témoin : la limite basse est bien appliquée
            list(Reponse.objects.filter(pk__in=list(range(1, 200))))
        lignes = S.construire_lignes(self.campagne(), self.paires())  # 162 réponses > 100 : l'ancien prefetch plantait
        obtenu = {(l.kpi.code, l.organisation.id): l.nb_preuves for l in lignes}
        self.assertEqual(len(obtenu), 162)
        self.assertEqual(obtenu.pop(self.avec_preuves), 2)
        self.assertEqual(set(obtenu.values()), {0})

    def test_lignes_reponse_du_tableau_inchangee(self):
        lignes = S.construire_lignes(self.campagne(), self.paires())
        self.assertTrue(all(l.reponse is not None for l in lignes))

    def test_requetes_independantes_du_volume(self):
        avant = len(requetes(lambda: S.construire_lignes(self.campagne(), self.paires()[:30])))
        apres = len(requetes(lambda: S.construire_lignes(self.campagne(), self.paires())))
        self.assertEqual(avant, apres)

    def test_tableau_de_bord_repond_sous_limite_basse(self):
        self.client.force_login(self.admin)
        self.abaisser(100)
        self.assertEqual(self.client.get(reverse("collecte:tableau_de_bord")).status_code, 200)


class SuppressionParLots(LimiteSQLite, Base):
    def test_supprimer_par_pk_sous_limite_basse(self):
        from .lots import supprimer_par_pk

        self.ajouter_kpis(30)  # 30 x 4 x 2 = 240 réponses
        pks = list(Reponse.objects.filter(periode=self.c.periode).values_list("pk", flat=True))
        self.assertEqual(len(pks), 120)
        self.abaisser(60)
        with self.assertRaises(Exception):  # témoin
            Reponse.objects.filter(pk__in=pks).delete()
        supprimer_par_pk(Reponse, pks, taille=20)
        self.assertEqual(Reponse.objects.filter(periode=self.c.periode).count(), 0)
        self.assertEqual(Reponse.objects.filter(periode=self.c0.periode).count(), 120)


class RequetesPages(Base):
    """Pages : le nombre de requêtes ne dépend pas du nombre de lignes affichées."""

    def setUp(self):
        super().setUp()
        self.admin.is_superuser = True
        self.admin.save()
        self.client.force_login(self.admin)

    def _requetes_page(self, nom):
        with CaptureQueriesContext(connection) as ctx:
            rep = self.client.get(reverse(nom))
        self.assertEqual(rep.status_code, 200)
        return len(ctx.captured_queries)

    def test_journal_sans_requete_par_ligne(self):
        from .models import Journal

        def ajouter(n):
            self.ajouter_kpis(n)
            for r in Reponse.objects.filter(periode=self.c.periode).select_related("kpi"):
                Journal.ecrire(self.admin, "modification", r, "valeur", "1", "2")
        ajouter(2)
        self._requetes_page("collecte:admin_journal")  # premier appel : caches de la session
        avant = self._requetes_page("collecte:admin_journal")
        ajouter(6)
        apres = self._requetes_page("collecte:admin_journal")
        self.assertEqual(avant, apres)


class PageCampagnes(Base):
    def test_comptage_des_saisies_par_periode(self):
        from django.db.models import Count

        self.admin.is_superuser = True
        self.admin.save()
        self.client.force_login(self.admin)
        self.ajouter_kpis(3)  # 3 x 4 valeurs importées par période
        rep = self.client.get(reverse("collecte:admin_campagnes"))
        self.assertEqual(rep.status_code, 200)
        nb = {c.periode_id: c.nb_saisies for _, cs, _ in rep.context["groupes"] for c in cs}
        self.assertEqual(nb[self.c.periode_id], 12)
        self.assertEqual(nb[self.c0.periode_id], 12)
        # même nombre que l'ancienne jointure
        ancien = {c.periode_id: c.nb_saisies for c in Campagne.objects.annotate(nb_saisies=Count(
            "periode__reponses", filter=Q(periode__reponses__origine__in=[Reponse.Origine.SAISIE, Reponse.Origine.IMPORT])))}
        self.assertEqual(nb, {k: ancien[k] for k in nb})

    def test_requetes_constantes(self):
        self.admin.is_superuser = True
        self.admin.save()
        self.client.force_login(self.admin)
        self.client.get(reverse("collecte:admin_campagnes"))
        with CaptureQueriesContext(connection) as a:
            self.client.get(reverse("collecte:admin_campagnes"))
        self.ajouter_kpis(5)
        Campagne.objects.create(exercice=2027, statut=Campagne.Statut.OUVERTE)
        with CaptureQueriesContext(connection) as b:
            self.client.get(reverse("collecte:admin_campagnes"))
        self.assertEqual(len(a.captured_queries), len(b.captured_queries))

    def test_plan_utilise_un_index(self):
        if connection.vendor != "sqlite":
            self.skipTest("EXPLAIN QUERY PLAN propre à SQLite")
        from django.db.models import Count

        qs = (Reponse.objects.filter(periode_id__in=[1, 2], origine__in=[Reponse.Origine.SAISIE, Reponse.Origine.IMPORT])
              .order_by().values_list("periode_id").annotate(n=Count("pk")))
        sql, params = qs.query.sql_with_params()
        with connection.cursor() as cur:
            cur.execute("EXPLAIN QUERY PLAN " + sql, params)
            plan = " ".join(str(r[3]) for r in cur.fetchall())
        self.assertIn("USING", plan)
        self.assertNotIn("SCAN collecte_reponse ", plan + " ")  # pas de parcours complet de la table


class ApercuImportLeger(Base):
    """L'aperçu d'un import ne charge que les réponses des KPI cités par le fichier, pas toute la période."""

    def test_reponses_lues_limitees_au_fichier(self):
        from django.db.models.signals import post_init

        from . import imports as I

        self.ajouter_kpis(10)  # 10 KPI x 4 entités : 40 réponses en 2026
        charge = []
        recepteur = lambda sender, instance, **kw: charge.append(instance.pk)  # noqa: E731
        post_init.connect(recepteur, sender=Reponse, weak=False)
        self.addCleanup(post_init.disconnect, recepteur, sender=Reponse)
        lignes = [["ID KPI", "Organisation", "Période", "Valeur"]] + [["K3", o.nom, "2026", 7] for o in self.entites[:2]]
        # casse différente : la ligne est résolue comme dans la boucle (« k4 » pour « K4 »)
        lignes.append(["k4", self.entites[0].nom, "2026", 7])
        with L.session():
            a = I.analyser(self.admin, None, onglets={"Données": lignes})
        self.assertEqual(len([l for l in a.lignes if l.campagne == self.c]), 3)
        self.assertEqual([l.action for l in a.lignes], ["modifier"] * 3)  # les valeurs existantes ont bien été vues
        self.assertEqual({l.avant for l in a.lignes}, {"300 salariés"})
        self.assertLessEqual(len(charge), 8)  # K3 et K4 x 4 entités, et non 40


class ExportTableauVitesse(Base):
    def test_niveau_des_kpi_sans_requete_par_kpi(self):
        from . import exports as E

        def lire():
            lignes = E.collecter(self.admin, E.Parametres(presentation="tableau"))
            return [E.sans_objet(l.kpi, l.org) for l in lignes]
        self.ajouter_kpis(2)
        avant = len(requetes(lire))
        self.ajouter_kpis(6)
        self.assertEqual(avant, len(requetes(lire)))


class GardeFouExcel(Base):
    """Un export Excel « une ligne par valeur » qui dépasse une feuille est refusé avant d'être construit."""

    def setUp(self):
        super().setUp()
        self.admin.is_superuser = True
        self.admin.save()
        self.ajouter_kpis(3)  # 3 KPI x 4 entités x 2 périodes : 24 réponses

    def parametres(self, **kw):
        from . import exports as E

        return E.Parametres(exercices=["2025", "2026"], **kw)

    def test_refus_avant_de_collecter(self):
        from unittest import mock

        from . import exports as E

        with mock.patch.object(E, "MAX_LIGNES_EXCEL", 30), mock.patch.object(E, "LIGNES_ENTETE_EXCEL", 10), \
                mock.patch.object(E, "collecter", side_effect=AssertionError("collecté")):
            with self.assertRaises(E.ExportTropGros) as cm:
                E.exporter(self.admin, self.parametres(presentation="base"))
        self.assertIn("CSV", str(cm.exception))
        self.assertIn("30", str(cm.exception))

    def test_borne_par_une_requete_count(self):
        from . import exports as E

        p = self.parametres(presentation="base")
        comptes = [q for q in requetes(lambda: E._borne_lignes(self.admin, p)) if q.startswith("SELECT COUNT(*)")]
        self.assertEqual(len(comptes), 1)  # un seul comptage, aucune réponse lue
        self.assertEqual(E._borne_lignes(self.admin, p), 24)
        self.assertEqual(E._borne_lignes(self.admin, self.parametres(presentation="base", kpis=["K0"])), 8)

    def test_borne_jamais_au_dessus_des_lignes_exportees(self):
        """La borne ne compte que des réponses qui seront exportées : organisations cochées, statuts, types, périmètre
        de la personne. Sinon un export d'une organisation, ou d'un contributeur, serait refusé à tort."""
        from . import exports as E

        contributeur = Utilisateur.objects.create(username="contrib", email="c@exemple.test",
                                                  role=Utilisateur.Role.CONTRIBUTEUR)
        for k in self.kpis:
            Attribution.objects.create(utilisateur=contributeur, kpi=k, organisation=self.entites[0],
                                       role=Attribution.Role.CONTRIBUTEUR)
        cas = [(self.admin, {}), (self.admin, {"organisations": [self.entites[0].id]}),
               (self.admin, {"contenus": ["valide", "calcule"]}), (self.admin, {"contenus": ["brouillon"]}),
               (self.admin, {"types": ["calcul"]}), (self.admin, {"niveaux": ["country"]}),
               (contributeur, {}), (self.auditeur, {})]
        for qui, kw in cas:
            with self.subTest(qui=qui.username, **kw):
                p = self.parametres(presentation="base", **kw)
                self.assertLessEqual(E._borne_lignes(qui, p), len(E.collecter(qui, p)))
        une = self.parametres(presentation="base", organisations=[self.entites[0].id])
        self.assertEqual(E._borne_lignes(self.admin, une), 6)  # 3 KPI x 2 périodes, pas 24
        self.assertEqual(E._borne_lignes(self.admin, self.parametres(presentation="base", contenus=["valide", "calcule"])), 12)
        self.assertEqual(E._borne_lignes(contributeur, self.parametres(presentation="base")), 0)  # périmètre limité

    def test_export_d_une_organisation_sous_la_limite_accepte(self):
        """24 réponses dans la base, 6 dans l'organisation exportée : sous la limite de 20 lignes, l'export passe."""
        from unittest import mock

        from . import exports as E

        p = self.parametres(presentation="base", organisations=[self.entites[0].id])
        with mock.patch.object(E, "MAX_LIGNES_EXCEL", 30), mock.patch.object(E, "LIGNES_ENTETE_EXCEL", 10):
            E._exporter(self.admin, p)

    def test_refus_apres_collecte_quand_le_filtre_n_est_pas_en_sql(self):
        from unittest import mock

        from . import exports as E

        p = self.parametres(presentation="revue", referentiel="X")  # filtre non exprimable : pas de borne SQL
        self.assertEqual(E._borne_lignes(self.admin, p), 0)
        with mock.patch.object(E, "MAX_LIGNES_EXCEL", 30), mock.patch.object(E, "LIGNES_ENTETE_EXCEL", 10), \
                mock.patch.object(E, "collecter", return_value=[0] * 25):
            with self.assertRaises(E.ExportTropGros):
                E._exporter(self.admin, p)

    def test_csv_et_tableau_non_concernes_et_dessous_de_la_limite(self):
        from unittest import mock

        from . import exports as E

        with mock.patch.object(E, "MAX_LIGNES_EXCEL", 30), mock.patch.object(E, "LIGNES_ENTETE_EXCEL", 10):
            for kw in ({"presentation": "base", "format": "csv"}, {"presentation": "tableau"}):
                E._refuser_trop_gros(10 ** 6, self.parametres(**kw))
            E._refuser_trop_gros(20, self.parametres(presentation="base"))  # 20 + 10 = 30 : tient
            with self.assertRaises(E.ExportTropGros):
                E._refuser_trop_gros(21, self.parametres(presentation="base"))

    def test_page_affiche_le_message_sans_fichier(self):
        from unittest import mock

        from . import exports as E

        self.client.force_login(self.admin)
        with mock.patch.object(E, "MAX_LIGNES_EXCEL", 5), mock.patch.object(E, "LIGNES_ENTETE_EXCEL", 1):
            rep = self.client.post(reverse("collecte:echanges_exporter"), {
                "action": "telecharger", "format": "xlsx", "presentation": "base", "exercices": ["2025", "2026"],
                "niveaux": E.N.codes(), "contenus": ["valide", "brouillon", "calcule"],
                "types": list(E.CODES_COMPORTEMENTS)}, follow=True)  # cases cochées comme dans le formulaire
        self.assertEqual(rep.status_code, 200)
        self.assertNotIn("spreadsheetml", rep.get("Content-Type", ""))
        self.assertIn("CSV", " ".join(str(m) for m in rep.context["messages"]))


class AlertesSansRequeteParLigne(Base):
    """Les alertes affichées (lignes de saisie, « à traiter ») chargent leur KPI avec la requête, pas une fois par alerte."""

    def ajouter_alertes(self, n):
        from .models import Alerte

        self.ajouter_kpis(n)
        Alerte.objects.bulk_create([
            Alerte(campagne=self.c, kpi=k, organisation=o, controle="ecart_n1", message="Écart", valeur="300", reference="100",
                   textes={"message": {"val": "300", "kpi": k.code}, "valeur": {"val": "300", "kpi": k.code}})
            for k in self.kpis[-n:] for o in self.entites])

    def test_lignes_de_saisie(self):
        def n():
            return len(requetes(lambda: [CO.texte_alerte(a, "valeur") for l in S.construire_lignes(
                self.campagne(), [(k, o) for k in self.kpis for o in self.entites]) for a in l.alertes]))
        self.ajouter_alertes(2)
        n()
        avant = n()
        self.ajouter_alertes(6)
        self.assertEqual(avant, n())

    def test_alertes_a_traiter_validateur(self):
        v = Utilisateur.objects.create(username="val", email="val@exemple.test", role=Utilisateur.Role.VALIDATEUR)
        self.ajouter_alertes(2)

        def attribuer(kpis):
            Attribution.objects.bulk_create([Attribution(utilisateur=v, kpi=k, organisation=o, role=Attribution.Role.VALIDATEUR)
                                             for k in kpis for o in self.entites])

        def n():
            return len(requetes(lambda: [CO.texte_alerte(a, "valeur") for a in CO.alertes_a_traiter(v, self.campagne())]))
        attribuer(self.kpis)
        n()
        avant = n()
        self.ajouter_alertes(6)
        attribuer(self.kpis[2:])
        self.assertEqual(avant, n())
