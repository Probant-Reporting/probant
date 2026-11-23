"""Ligne de la grille de saisie écrite en Python (``collecte/rendu_ligne.py``, échelle, lot D) : le même HTML, au
caractère près, que l'ancien gabarit ``_ligne.html`` (recopié dans ``aides_tests/ligne_avant.html``).

Jeu de ``test_lignes_legeres_compteurs`` (graine fixe : tous les états d'une case, calculés, saisie au-dessus, cases
couvertes, facultatifs, KPI commun à deux référentiels, mois, alertes ; tous les rôles), complété au hasard à graine fixe :
noms de KPI, d'organisations et de personnes avec des caractères à échapper, textes de réponse, preuves, alertes
bloquantes, une case à cinq SPOC. Chaque ligne de chaque personne (toutes les lignes, « Pour moi », une organisation avec
les calculés) est comparée en français, anglais et espagnol ; puis les pages Saisie et « Pour moi » (dont la suite de la
liste, ?reste=1) et la ligne relue après une saisie, rendues avec l'ancien gabarit et avec la nouvelle écriture."""
import random
from pathlib import Path
from unittest import mock

from django.template import engines
from django.test import Client, RequestFactory, TestCase

from collecte import rendu_ligne as RL
from collecte import saisie as S
from collecte import test_lignes_legeres_compteurs as LL
from collecte import views as V
from collecte.models import Alerte, Preuve, Reponse
from parametres import langues as L
from referentiel.models import KPI, Attribution, Organisation, Utilisateur

GRAINE = 20261114
GABARIT_AVANT = engines["django"].from_string((Path(__file__).parent / "aides_tests" / "ligne_avant.html").read_text(encoding="utf-8"))
PIEGE = "<b>\"Énergie\"</b> & l'eau"


def ligne_avant(l, c):
    """Ancienne construction : le gabarit ``_ligne.html`` avec les variables que la page lui donnait."""
    return GABARIT_AVANT.render({"l": l, "admin": c.admin, "user": c.user, "campagne": c.campagne,
                                 "comparaison": c.comparaison, "montrer_org": c.montrer_org})


class LigneGrilleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        LL.LignesLegeresTests.setUpTestData.__func__(cls)
        h = random.Random(GRAINE)
        for k in h.sample(list(KPI.objects.all()), 5):
            KPI.objects.filter(pk=k.pk).update(libelle=f"{k.libelle} {PIEGE}")
        for o in h.sample(list(Organisation.objects.all()), 4):
            Organisation.objects.filter(pk=o.pk).update(nom=f"{o.nom} <i>&</i>")
        Utilisateur.objects.filter(pk=cls.contribs[1].pk).update(first_name='Zoé "<z>"', last_name="L'Été & co")
        reps = list(Reponse.objects.filter(periode__in=[cls.c.periode, cls.c25.periode, cls.cm.periode]))
        for r in h.sample(reps, len(reps) // 8):
            Reponse.objects.filter(pk=r.pk).update(texte=h.choice(['Oui', '<"&>', "Non & peut-être"]))
        Preuve.objects.bulk_create([Preuve(reponse=r, fichier=f"preuves/essai{i}.pdf", nom_fichier=f"essai{i}.pdf")
                                    for i, r in enumerate(h.sample(reps, 25)) for _ in range(h.randint(1, 3))])
        alertes = list(Alerte.objects.filter(campagne=cls.c))
        Alerte.objects.filter(pk__in=[a.pk for a in h.sample(alertes, max(1, len(alertes) // 3))]).update(gravite="bloquante")
        # une case à deux alertes : la plus récente (montrée la première) non bloquante, l'autre bloquante
        site = Organisation.objects.get(nom__startswith="Site 0")
        Alerte.objects.filter(campagne=cls.c, kpi_id="S1", organisation=site).delete()
        for controle, gravite in (("historique", "bloquante"), ("ecart_n1", "alerte")):
            Alerte.objects.create(campagne=cls.c, kpi_id="S1", organisation=site, controle=controle, gravite=gravite, message="Essai")
        nouveaux = [Utilisateur.objects.create(username=f"spoc{i}", email=f"spoc{i}@exemple.test", first_name=f"Spoc {i}",
                                               role=Utilisateur.Role.CONTRIBUTEUR) for i in range(5)]
        a = Attribution.objects.filter(role="contributeur", kpi_id="S0").first()
        Attribution.objects.bulk_create([Attribution(kpi_id=a.kpi_id, organisation_id=a.organisation_id, utilisateur=u,
                                                     role="contributeur") for u in nouveaux])

    def lignes_de(self, u, c):
        yield "toutes", S.lignes(u, c)
        yield "pour moi", S.lignes(u, c, personnel=True)
        for o in S.organisations_visibles(u, c)[:3]:
            org = o[0]
            yield f"org {org.pk}", S.lignes(u, c, org=org, calculees=True)

    def test_meme_html_que_l_ancien_gabarit(self):
        vues, etats = 0, set()
        for langue in ("fr", "en", "es"):
            with L.activer(langue):  # tout en français ; en anglais et en espagnol, trois personnes et une campagne
                for u in self.personnes if langue == "fr" else (self.admin, self.contribs[1], self.v_pays):
                    for c in (self.c, self.c2, self.cm, self.c25) if langue == "fr" else (self.c,):
                        comparaison = S.libelle_comparaison(c)
                        for nom, lignes in self.lignes_de(u, c):
                            constantes = [RL.Constantes(u.est_admin, u, c, comparaison, montrer) for montrer in (False, True)]
                            for i, l in enumerate(lignes):
                                montrer_org = bool(i % 2)  # une ligne sur deux avec l'organisation (« Pour moi »)
                                cst = constantes[i % 2]
                                with self.subTest(langue=langue, personne=u.username, campagne=str(c), lignes=nom,
                                                  montrer_org=montrer_org, cle=l.cle):
                                    self.assertEqual(RL.ligne(l, cst), ligne_avant(l, cst))
                                vues += 1
                                etats |= {("alertes", bool(l.alertes)), ("calculee", l.calculee), ("au_dessus", l.au_dessus),
                                          ("couverte", l.couverte is not None), ("facultatif", l.facultatif),
                                          ("preuves", bool(l.nb_preuves)), ("spocs>3", len(l.spocs) > 3),
                                          ("aussi", bool(l.autres_refs)), ("ecart", l.ecart is not None), l.statut,
                                          ("bloquante après une autre", [a.gravite for a in l.alertes][1:2] == ["bloquante"]
                                           and l.alertes[0].gravite != "bloquante")}
        self.assertGreater(vues, 2500)
        for attendu in (("alertes", True), ("calculee", True), ("au_dessus", True), ("couverte", True), ("facultatif", True),
                        ("preuves", True), ("spocs>3", True), ("aussi", True), ("ecart", True), "a_saisir", "brouillon", "valide",
                        ("bloquante après une autre", True)):
            self.assertIn(attendu, etats)

    def pages(self, u):
        self.client = Client()  # session neuve : « Tous mes référentiels » mémorisé ne passe pas d'un rendu à l'autre
        self.client.force_login(u)
        org = S.organisations_visibles(u, self.c)
        urls = ["/pour-moi/", "/pour-moi/?groupe=theme", "/pour-moi/?complet=1", "/pour-moi/?reste=1",
                "/pour-moi/?groupe=theme&reste=1", "/pour-moi/?tous=1", "/pour-moi/?tous=1&reste=1"]
        if org:
            urls += [f"/saisie/?campagne={self.c.pk}&org={org[0][0].pk}", f"/saisie/?campagne={self.c.pk}&org={org[-1][0].pk}&calc=1"]
        sortie = {}
        for url in urls:
            r = self.client.get(url, secure=True)
            self.assertIn(r.status_code, (200, 302, 403), url)  # « Pour moi » refusé au lecteur et à l'auditeur
            sortie[url] = LL.sans_jetons(r.content.decode())
        return sortie

    def test_memes_pages_que_l_ancien_gabarit(self):
        for u in self.personnes:
            with self.subTest(personne=u.username):
                with mock.patch.object(RL, "ligne", ligne_avant):
                    avant = self.pages(u)
                apres = self.pages(u)
                for url in avant:
                    self.assertEqual(apres[url], avant[url], url)
                self.assertTrue(any('<tr class="ligne' in h for h in avant.values()) or not S.lignes(u, self.c, personnel=True))

    def test_ligne_relue_apres_une_saisie(self):
        fabrique = RequestFactory()
        for u in self.personnes:
            for l in S.lignes(u, self.c)[::7][:12]:
                for page in ("pour_moi", "saisie"):
                    with self.subTest(personne=u.username, cle=l.cle, page=page):
                        requete = fabrique.get("/", HTTP_X_PAGE=page)
                        requete.user = u
                        cle, html = V.ligne_html(requete, self.c, l.kpi, l.organisation)
                        with mock.patch.object(RL, "ligne", ligne_avant):
                            self.assertEqual(V.ligne_html(requete, self.c, l.kpi, l.organisation), (cle, html))

    def test_libelles_lus_une_fois_par_page_dans_la_langue_de_la_page(self):
        """Les constantes vivent le temps d'un rendu : une autre langue, une autre page, d'autres libellés."""
        l = S.lignes(self.admin, self.c)[0]
        with L.activer("en"):
            en = RL.ligne(l, RL.Constantes(True, self.admin, self.c, "N-1", False))
        with L.activer("fr"):
            fr = RL.ligne(l, RL.Constantes(True, self.admin, self.c, "N-1", False))
        self.assertNotEqual(en, fr)
