"""« Pour moi » d'un validateur à large périmètre (échelle, P-A9) : 7,9 s et 10,9 Mo sur la grosse base.

Deux changements, deux preuves, sur le jeu tiré au hasard (graine fixe) des lignes légères (``LignesLegeresTests`` :
tous les états d'une case, tous les rôles et périmètres) :
1. Les sections repliées d'une longue liste partent sans leurs lignes ; le script les demande aussitôt (?reste=1).
   La page, complétée par cette demande, montre exactement les mêmes sections (titres, ordre, ouvertes ou non) et les
   mêmes lignes, octet pour octet, que la liste entière (?complet=1, l'ancienne page) ; tout ce qui est hors de la liste
   (résumé, compteurs, bandeau, filtres) est identique ; mêmes droits pour chaque rôle.
2. Construction : les alertes visibles et le sélecteur d'organisations lisent moins de lignes en base ; mêmes
   résultats que les anciennes fonctions, recopiées ci-dessous telles qu'elles étaient (commit 539519f)."""
import re
from unittest import mock

from django.test import TestCase

from collecte import coherence as CO
from collecte import saisie as S
from collecte import views as V
from collecte.models import Reponse
from collecte import test_lignes_legeres_compteurs as LL  # (le module, pas la classe : ses tests ne tournent pas deux fois)
from referentiel.models import Attribution, Utilisateur


# ---------------------------------------------------------------- anciennes fonctions (539519f), pour comparer
def alertes_visibles_avant(utilisateur, campagne, cases=None, personnel=False, qs=None):
    from collecte.models import Alerte

    if qs is None:
        qs = Alerte.objects.filter(campagne=campagne).select_related(*CO.AVEC_KPI, "organisation", "regle", "justifie_par", "traite_par")
    if utilisateur.voit_tout and not personnel and utilisateur.orgs_permises() is None:
        return list(qs)
    if cases is None:
        cases = {(k.pk, o.pk) for k, o in S.cellules(utilisateur, personnel, campagne=campagne)}
    if not cases:
        return []
    orgs_calc = {o for _, o in cases}
    visibles = []
    for a in qs:
        if a.controle == CO.C.CALCUL:
            if a.organisation_id in orgs_calc and S.voit_calcules(utilisateur, a.organisation):
                visibles.append(a)
        elif CO.visible(a, cases):
            visibles.append(a)
    return visibles


def organisations_visibles_avant(utilisateur, campagne):
    paires = S.cellules(utilisateur, campagne=campagne)
    alertes, orgs_alertes = {}, {}
    from collecte.models import Alerte

    qs = Alerte.objects.filter(CO.A_JUSTIFIER, campagne=campagne).select_related(*CO.AVEC_KPI, "organisation")
    for a in alertes_visibles_avant(utilisateur, campagne, {(k.code, o.id) for k, o in paires}, False, qs):
        alertes[a.organisation_id] = alertes.get(a.organisation_id, 0) + 1
        orgs_alertes[a.organisation_id] = a.organisation
    dessus = S.couvertes(campagne.periode, paires)
    paires = [(k, o) for k, o in paires if (k.code, o.id) not in dessus]
    fac = S.facultatifs(campagne)
    valides = set(Reponse.objects.filter(periode=campagne.periode, statut=Reponse.Statut.VALIDE).values_list("kpi_id", "organisation_id"))
    totaux = {}
    for k, o in paires:
        t = totaux.setdefault(o, [0, 0])
        if k.code not in fac:
            t[0] += 1
            t[1] += (k.code, o.id) in valides
    arbre = S.arbre_organisations()
    if utilisateur.voit_tout:
        permises = utilisateur.orgs_permises()
        autres = [o for o in arbre.values() if o.actif and (permises is None or o.id in permises)]
    else:
        ids = Attribution.objects.filter(utilisateur=utilisateur, role=Attribution.Role.VALIDATEUR).values_list("organisation_id", flat=True)
        autres = [arbre[i] for i in set(ids) if i in arbre and arbre[i].actif]
    autres += [arbre[i] for i in alertes if i in arbre and arbre[i].actif]
    for o in autres:
        totaux.setdefault(o, [0, 0])
    resultat = [(o.id, t, v, alertes.get(o.id, 0)) for o, (t, v) in sorted(totaux.items(), key=lambda x: S.cle_arbre(x[0]))]
    dans = {o.id for o in totaux}
    return resultat, {orgs_alertes[i].id: n for i, n in alertes.items() if i not in dans}


# ---------------------------------------------------------------- lecture de la liste d'une page
VIDE = '<p class="chargement-section" data-a-charger'  # section partie sans ses lignes (le script de la page cite aussi l'attribut)
SECTION = re.compile(r'\n<details class="section"([^>]*)>(.*?)\n</details>', re.S)


def liste(html):
    """Le contenu de #liste : [(attributs de la section, contenu)] (le contenu d'une section vide porte data-a-charger)."""
    debut = html.index('<div id="liste"')
    return SECTION.findall(html[debut:])


def hors_liste(html):
    """La page sans sa liste (de #liste à la fin) ni ses jetons : résumé, compteurs, bandeau, filtres."""
    return LL.sans_jetons(html[:html.index('<div id="liste"')]).replace("&amp;complet=1", "")  # (adresse de retour du choix de langue)


def completer(page, fragment):
    """La page dont les sections vides (data-a-charger) sont remplacées par celles de la demande (?reste=1), comme le
    fait le script (même identifiant, même titre ; ouverte ou non comme dans la page)."""
    arrivees = {re.search(r'data-section="([^"]+)"', a).group(1): (a, c) for a, c in liste_fragment(fragment)}
    sortie = []
    for attributs, contenu in liste(page):
        m = re.search(r'data-a-charger="([^"]+)"', contenu)
        if m:
            a, c = arrivees.pop(m.group(1))
            titre = re.search(r"<summary>.*?</summary>", contenu, re.S).group(0)
            assert titre == re.search(r"<summary>.*?</summary>", c, re.S).group(0)
            attributs, contenu = re.sub(r' data-section="[^"]+"', "", a), c
        sortie.append((attributs, contenu))
    assert not arrivees, arrivees
    return sortie


def liste_fragment(html):
    return SECTION.findall("\n" + html)


class SectionsAChargerTests(TestCase):
    setUpTestData = classmethod(LL.LignesLegeresTests.setUpTestData.__func__)

    def urls(self):
        for groupe in ("organisation", "theme"):
            for c in (self.c, self.c2, self.cm):
                yield f"/pour-moi/?campagne={c.pk}&groupe={groupe}&tous=0"
            yield f"/pour-moi/?groupe={groupe}&tous=1"

    def get(self, url, statut=200):
        r = self.client.get(url, secure=True)
        self.assertEqual(r.status_code, statut, url)
        return r

    def test_page_completee_identique_a_la_liste_entiere(self):
        repliees = 0
        with mock.patch.object(V, "LIGNES_OUVERTES", 3):  # petite limite : des sections repliées pour chaque personne
            for u in self.personnes:
                if u.lecture_seule:
                    continue
                self.client.force_login(u)
                for url in self.urls():
                    with self.subTest(personne=u.username, url=url):
                        page = self.get(url)
                        html = page.content.decode()
                        entiere = self.get(url + "&complet=1").content.decode()
                        self.assertNotIn(VIDE, entiere)
                        self.assertEqual(hors_liste(html), hors_liste(entiere))
                        if VIDE not in html:
                            self.assertEqual(liste(html), liste(entiere))
                            continue
                        repliees += 1
                        url_reste = "/pour-moi/" + page.context["url_reste"]
                        self.assertIn(f'data-url-reste="{page.context["url_reste"].replace("&", "&amp;")}"', html)
                        for attributs, contenu in liste(html):  # une section vide n'a aucune ligne
                            if VIDE in contenu:
                                self.assertNotIn('class="ligne', contenu)
                        fragment = self.get(url_reste).content.decode()
                        self.assertEqual(completer(html, fragment), liste(entiere))
        self.assertGreater(repliees, 10)  # garde du test : le cas des sections à charger est bien vu

    def test_liste_entiere_identique_sans_sections_repliees(self):
        """« ?complet=1 » rend la liste d'avant : ses sections et ses lignes sont celles d'une liste qui tient sans repli
        (même construction), seul l'attribut « open » des sections repliées diffère."""
        self.client.force_login(self.v_pays)
        for url in self.urls():
            with mock.patch.object(V, "LIGNES_OUVERTES", 3):
                entiere = liste(self.get(url + "&complet=1").content.decode())
            with mock.patch.object(V, "LIGNES_OUVERTES", 10 ** 6):
                sans_repli = liste(self.get(url).content.decode())
            self.assertEqual([c for _, c in entiere], [c for _, c in sans_repli], url)

    def test_demande_avec_les_sections_ouvertes_de_la_page(self):
        """La demande dit combien de sections la page a ouvertes : la liste qui grandit entre-temps ne décale rien."""
        self.client.force_login(self.v_pays)
        url = f"/pour-moi/?campagne={self.c.pk}&groupe=organisation&tous=0"
        with mock.patch.object(V, "LIGNES_OUVERTES", 3):
            page = self.get(url)
            url_reste = "/pour-moi/" + page.context["url_reste"]
            n = page.context["nb_ouvertes"]
        fragment = self.get(url_reste).content.decode()  # limite normale : la page aurait ouvert plus de sections
        rangs = [int(x.split("-")[1]) for x in re.findall(r'data-section="([^"]+)"', fragment)]
        self.assertEqual(rangs[0], n)
        self.assertEqual(rangs, list(range(n, n + len(rangs))))
        # valeur incomprise : la demande refait son propre calcul, sans erreur
        self.get(url_reste.replace("ouvertes=", "ouvertes=x"))

    def test_memes_droits(self):
        """Lecteur : la page et la demande renvoient ailleurs de la même façon ; chaque personne ne reçoit que ses lignes."""
        with mock.patch.object(V, "LIGNES_OUVERTES", 3):
            for u in self.personnes:
                self.client.force_login(u)
                url = f"/pour-moi/?campagne={self.c.pk}&groupe=organisation&tous=0"
                entiere = self.client.get(url + "&complet=1", secure=True)
                reste = self.client.get(url + "&reste=1&ouvertes=0", secure=True)
                with self.subTest(personne=u.username):
                    self.assertEqual(reste.status_code, entiere.status_code)
                    if entiere.status_code != 200:
                        self.assertEqual(reste.get("Location"), entiere.get("Location"))
                        continue
                    cles = lambda h: re.findall(r'<tr class="ligne[^"]*"[^>]*data-cle="([^"]+)"', h)  # noqa: E731
                    self.assertEqual(sorted(cles(reste.content.decode())), sorted(cles(entiere.content.decode())))


class ConstructionTests(TestCase):
    setUpTestData = classmethod(LL.LignesLegeresTests.setUpTestData.__func__)

    def test_alertes_visibles_comme_avant(self):
        from collecte.models import Alerte

        vues = 0
        for u in self.personnes:
            for c in (self.c, self.c2, self.cm):
                for personnel in (False, True):
                    with self.subTest(personne=u.username, campagne=c.pk, personnel=personnel):
                        avant = [a.pk for a in alertes_visibles_avant(u, c, personnel=personnel)]
                        self.assertEqual([a.pk for a in CO.alertes_visibles(u, c, personnel=personnel)], avant)
                        qs = Alerte.objects.filter(CO.A_JUSTIFIER, campagne=c).select_related(*CO.AVEC_KPI, "organisation")
                        self.assertEqual([a.pk for a in CO.alertes_a_traiter(u, c, personnel=personnel)],
                                         [a.pk for a in alertes_visibles_avant(u, c, None, personnel, qs)])
                        vues += len(avant)
                        for a in Alerte.objects.filter(campagne=c):  # une alerte à la fois (fiche d'une alerte)
                            self.assertEqual(CO.peut_voir(u, a), bool(alertes_visibles_avant(u, c, qs=[a])))
        self.assertGreater(vues, 0)

    def test_selecteur_d_organisations_comme_avant(self):
        for u in self.personnes:
            for c in (self.c, self.c2, self.cm):
                with self.subTest(personne=u.username, campagne=c.pk):
                    nouveau = S.organisations_visibles(u, c)
                    lignes, hors = organisations_visibles_avant(u, c)
                    self.assertEqual([(o.id, t, v, n) for o, t, v, n in nouveau], lignes)
                    self.assertEqual({o.id: n for o, n in nouveau.alertes_hors.items()}, hors)

    def test_cellules_d_un_validateur(self):
        """La lignée lue une fois par organisation : mêmes cases qu'en la relisant à chaque fois."""
        for u in (self.v_pays, self.v_filiale, Utilisateur.objects.get(username="contrib0")):
            for c in (self.c, self.c2, self.cm, None):
                nouveau = sorted((k.code, o.id) for k, o in S.cellules(u, campagne=c))
                arbre = S.arbre_organisations()
                with mock.patch.object(S, "arbre_organisations", lambda: arbre):
                    attendu = set()
                    kpis = {k.code: k for k in S.kpis_collectes(c.referentiel if c else None)}
                    from parametres import niveaux as N

                    rangs = N.rangs()
                    for kpi_id, org_id, role in Attribution.objects.filter(utilisateur=u).values_list("kpi_id", "organisation_id", "role"):
                        k = kpis.get(kpi_id)
                        if k is None or (c is not None and S.cumule(c, k)):
                            continue
                        if role == Attribution.Role.CONTRIBUTEUR:
                            if org_id in arbre and arbre[org_id].actif and k.se_saisit_a(arbre[org_id], rangs):
                                attendu.add((kpi_id, org_id))
                            continue
                        for o in arbre.values():  # ancienne règle : toute organisation du niveau dont la lignée contient org_id
                            if not o.actif or not (o.niveau_id == k.granularite_id or (k.est_herite and o in S.porteurs_orphelins(
                                    k.granularite_id, [x for x in arbre.values() if x.actif], rangs, arbre))):
                                continue
                            x, lignee = o, set()
                            while x:
                                lignee.add(x.id)
                                x = arbre.get(x.parent_id)
                            if org_id in lignee:
                                attendu.add((kpi_id, o.id))
                self.assertEqual(nouveau, sorted(attendu), (u.username, c))
