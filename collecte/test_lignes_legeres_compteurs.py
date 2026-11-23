"""Lignes légères (``saisie.lignes_legeres``) : les mêmes chiffres que l'ancienne construction, page par page.

Jeu tiré au hasard avec une graine fixe, qui couvre tous les états d'une case : à saisir, brouillon, validé, N/A
(brouillon ou validé), facultatif, hors périmètre (KPI dans aucun référentiel), KPI inactif, KPI calculé, cumul des mois,
paramètre hérité porté faute d'ancêtre, saisie au-dessus de la granularité (cases couvertes), organisation fermée
pendant la période ou avant, contributeur inactif, case sans contributeur, KPI commun à deux référentiels de la même
période ; et tous les périmètres : administrateur, validateurs, contributeurs, lecteurs (tout, un pays), auditeur.

Pour chaque personne et chaque campagne ouverte : les lignes (clé, statut, N/A, attendue, SPOC…), les compteurs du
tableau de bord, le suivi (retards, sans SPOC), les relances (personnes, cases, « aussi »), puis les pages elles-mêmes
(Tableau de bord, Administration, Relances, visuel « remplissage ») rendues avec l'ancienne construction (lignes
complètes) et avec la nouvelle : même HTML, même JSON."""
import datetime
import random
import re
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from collecte import periodes as P
from collecte import relances as R
from collecte import saisie as S
from collecte import visuels as VS
from collecte.aides_tests.visuels import vue
from collecte.calcul import recalculer
from collecte.coherence import controler
from collecte.models import Alerte, Campagne, Reponse
from collecte.views import suivi
from parametres.models import TypeReponse
from parametres.referentiel import unite_depuis_symbole as U
from referentiel.models import KPI, Attribution, ElementReferentiel, Niveau, Organisation, Referentiel, Theme, Utilisateur
from referentiel.plans import Plan

GRAINE = 20261113
ANCIENNE = S.construire_lignes


def ancienne_construction(campagne, paires, calculees=(), plan=None, cases_visibles=None, legere=False):
    """Lignes complètes, quel que soit ``legere`` : la construction d'avant les lignes légères."""
    return ANCIENNE(campagne, paires, calculees, plan, cases_visibles)


def tableau_de_bord_avant(liste, plan=None):
    """``saisie.tableau_de_bord`` tel qu'il était avant (f6503ba), recopié tel quel : la référence des compteurs."""
    plan = plan or Plan()
    saisies = sorted((l for l in liste if l.attendue), key=S.ordre(plan))
    total, par_org, par_org_propre, par_theme, par_spoc = S.Compteur(), {}, {}, {}, {}
    facultatives = S.Compteur()
    for l in liste:
        if l.facultatif and not l.calculee and not l.au_dessus and l.couverte is None:
            facultatives.ajouter(l)
    par_ref = {r.code: (r, S.Compteur()) for r in plan.referentiels}
    for l in saisies:
        total.ajouter(l)
        par_org_propre.setdefault(l.organisation, S.Compteur()).ajouter(l)
        o = l.organisation
        while o:
            par_org.setdefault(o, S.Compteur()).ajouter(l)
            o = o.parent
        par_theme.setdefault(plan.titres(l.kpi.code)[0], S.Compteur()).ajouter(l)
        for code in plan.appartenances.get(l.kpi.code, []):
            if code in par_ref and (code, l.kpi.code) not in plan.facultatifs:
                par_ref[code][1].ajouter(l)
        for u in l.spocs or [None]:
            par_spoc.setdefault(u, S.Compteur()).ajouter(l)
    return {
        "total": total,
        "facultatifs": facultatives,
        "par_referentiel": [x for x in par_ref.values() if x[1].total],
        "par_org": sorted(par_org.items(), key=lambda x: S.cle_arbre(x[0])),
        "par_org_propre": par_org_propre,
        "par_theme": list(par_theme.items()),
        "par_spoc": sorted(par_spoc.items(), key=lambda x: (x[0] is not None, str(x[0] or ""))),
    }


def comme_avant():
    """Les pages calculées comme avant : lignes complètes et ancien tableau de bord."""
    return mock.patch.multiple(S, construire_lignes=ancienne_construction, tableau_de_bord=tableau_de_bord_avant)


def cle_ligne(l):
    return (l.kpi.code, l.organisation.id, l.statut, l.na, l.attendue, l.calculee, l.au_dessus,
            l.couverte.id if l.couverte else None, l.facultatif, [u.pk for u in l.spocs])


def compteur(c):
    return (c.total, c.valide, c.brouillon, c.a_saisir, c.na)


def resume_tdb(t):
    return {"total": compteur(t["total"]), "facultatifs": compteur(t["facultatifs"]),
            "par_referentiel": [(r.code, compteur(c)) for r, c in t["par_referentiel"]],
            "par_org": [(o.id, compteur(c)) for o, c in t["par_org"]],
            "par_org_propre": [(o.id, compteur(c)) for o, c in t["par_org_propre"].items()],
            "par_theme": [(titre, compteur(c)) for titre, c in t["par_theme"]],
            "par_spoc": [(u.pk if u else None, compteur(c)) for u, c in t["par_spoc"]]}


def resume_relances(liste):
    return [(af.personne.pk, [(c.pk, [(l.kpi.code, l.organisation.id, l.statut) for l in ls]) for c, ls in af.campagnes],
             [c.pk for c in af.aussi], af.a_saisir, af.brouillons) for af in liste]


def sans_jetons(html):
    """HTML sans ce qui change à chaque rendu (jeton CSRF, nonce)."""
    html = re.sub(r'nonce="[^"]*"', "", html)
    return re.sub(r"\b[A-Za-z0-9]{64}\b", "<jeton>", html)  # jeton CSRF (champ caché, balise meta), masqué à chaque rendu


class LignesLegeresTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        h = random.Random(GRAINE)
        aujourdhui = timezone.localdate()
        # arbre : groupe, 2 pays, 4 filiales, 3 sites par filiale ; un site fermé pendant 2026, un fermé en 2024 ;
        # un site rattaché directement au groupe (porte le paramètre hérité faute de pays)
        cls.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        pays = [Organisation.objects.create(nom=f"Pays {i}", niveau_id=Niveau.COUNTRY, parent=cls.g, rang=i) for i in range(2)]
        cls.pays = pays
        filiales = [Organisation.objects.create(nom=f"Filiale {i}", niveau_id=Niveau.ENTITY, parent=pays[i % 2], rang=i) for i in range(4)]
        sites = [Organisation.objects.create(nom=f"Site {i}", niveau_id=Niveau.SITE, parent=filiales[i % 4], rang=i) for i in range(12)]
        sites.append(Organisation.objects.create(nom="Site du siège", niveau_id=Niveau.SITE, parent=cls.g, rang=20))
        Organisation.objects.filter(pk=sites[5].pk).update(actif=False, date_desactivation=datetime.date(2026, 6, 30))
        Organisation.objects.filter(pk=sites[6].pk).update(actif=False, date_desactivation=datetime.date(2024, 3, 31))
        oui_non, _ = TypeReponse.objects.get_or_create(code="OuiNonEssai", defaults={"libelle": "Oui / non", "format": "oui_non"})
        kwh = U("kWh")

        def kpi(code, niveau, type_saisie="Saisi", **autres):
            return KPI.objects.create(code=code, libelle=f"KPI {code}", type_saisie_id=type_saisie, granularite_id=niveau,
                                      methode_agregation=autres.pop("agregation", "Somme"), unite=autres.pop("unite", kwh), **autres)

        site_kpis = [kpi(f"S{i}", Niveau.SITE) for i in range(6)]
        site_kpis.append(kpi("OUI", Niveau.SITE, type_reponse=oui_non, agregation="Décompte", unite=None))
        dessus = kpi("DESSUS", Niveau.SITE, saisie_au_dessus=True)  # saisie possible à la filiale
        fil = [kpi(f"F{i}", Niveau.ENTITY) for i in range(3)]
        fe = kpi("FE", Niveau.COUNTRY, type_saisie="FE", agregation="Aucune")
        calc = [kpi("C0", Niveau.SITE, type_saisie="Calculé", formule="[S0] * [FE]"),
                kpi("C1", Niveau.ENTITY, type_saisie="Calculé", formule="[F1] / [F0]", agregation="Formule")]
        inactif = kpi("INACTIF", Niveau.SITE, actif=False)
        kpi("HORS", Niveau.SITE)  # dans aucun référentiel : jamais demandé
        mensuel = kpi("MOIS", Niveau.SITE)  # mensuel et annuel : cumul des mois dans l'année
        commun = kpi("COMMUN", Niveau.SITE)  # dans les deux référentiels annuels
        ann = Referentiel.objects.create(code="ANN", nom="Annuel", frequence="annee", ordre=1)
        ann2 = Referentiel.objects.create(code="ANN2", nom="Annuel bis", frequence="annee", ordre=2)
        men = Referentiel.objects.create(code="MEN", nom="Mensuel", frequence="mois", ordre=3)
        themes = [Theme.objects.create(referentiel=ann, code=f"T{i}", nom=f"Thème {i}", ordre=i) for i in range(3)]
        n = 0
        for k in site_kpis + [dessus] + fil + [fe] + calc + [inactif, mensuel, commun]:
            n += 1
            ElementReferentiel.objects.create(referentiel=ann, kpi=k, theme=themes[n % 3], ordre=n,
                                              obligatoire=k.code not in ("S5", "F2"))  # deux facultatifs
        t2 = Theme.objects.create(referentiel=ann2, code="T", nom="Bis", ordre=0)
        ElementReferentiel.objects.create(referentiel=ann2, kpi=commun, theme=t2, ordre=1)
        ElementReferentiel.objects.create(referentiel=ann2, kpi=site_kpis[1], theme=t2, ordre=2)
        tm = Theme.objects.create(referentiel=men, code="T", nom="Mois", ordre=0)
        ElementReferentiel.objects.create(referentiel=men, kpi=mensuel, theme=tm, ordre=1)
        fin = aujourdhui + datetime.timedelta(days=20)
        cls.c25, _ = P.campagne(ann, datetime.date(2025, 1, 1), statut=Campagne.Statut.CLOTUREE, seuil_ecart=Decimal("0.2"))
        cls.c, _ = P.campagne(ann, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE, seuil_ecart=Decimal("0.2"),
                              date_ouverture=aujourdhui - datetime.timedelta(days=60), date_fin_saisie=fin)
        cls.c2, _ = P.campagne(ann2, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE,
                               date_ouverture=aujourdhui - datetime.timedelta(days=60), date_fin_saisie=fin)
        cls.cm, _ = P.campagne(men, datetime.date(2026, 2, 1), statut=Campagne.Statut.OUVERTE,
                               date_ouverture=aujourdhui - datetime.timedelta(days=10), date_fin_saisie=fin)
        # comptes : les mots de passe ne servent pas (force_login)
        def compte(nom, role, **autres):
            return Utilisateur.objects.create(username=nom, email=f"{nom}@exemple.test", role=role, first_name=nom.capitalize(), **autres)

        cls.admin = compte("admin", Utilisateur.Role.ADMIN, is_staff=True, is_superuser=True)
        contribs = [compte(f"contrib{i}", Utilisateur.Role.CONTRIBUTEUR) for i in range(3)]
        contribs.append(compte("parti", Utilisateur.Role.CONTRIBUTEUR, is_active=False))  # inactif : jamais SPOC
        cls.contribs = contribs
        cls.v_pays = compte("valpays", Utilisateur.Role.VALIDATEUR)
        cls.v_filiale = compte("valfiliale", Utilisateur.Role.VALIDATEUR)
        cls.lecteur = compte("lecteur", Utilisateur.Role.LECTEUR)
        cls.lecteur_pays = compte("lecteurpays", Utilisateur.Role.LECTEUR)
        cls.lecteur_pays.perimetre_lecture.set([pays[1]])
        cls.auditeur = compte("auditeur", Utilisateur.Role.AUDITEUR)
        cls.auditeur.perimetre_lecture.set([pays[0]])
        liens = []
        saisis_site = site_kpis + [dessus, mensuel, commun, inactif]
        for s in sites:
            for k in saisis_site:
                if h.random() < 0.85:  # quelques cases sans contributeur
                    liens.append(Attribution(kpi=k, organisation=s, utilisateur=h.choice(contribs), role="contributeur"))
                if h.random() < 0.15:  # deux contributeurs sur une case
                    liens.append(Attribution(kpi=k, organisation=s, utilisateur=h.choice(contribs), role="contributeur"))
        for f in filiales:
            for k in fil:
                liens.append(Attribution(kpi=k, organisation=f, utilisateur=h.choice(contribs), role="contributeur"))
        for p in pays:
            liens.append(Attribution(kpi=fe, organisation=p, utilisateur=contribs[0], role="contributeur"))
        liens.append(Attribution(kpi=fe, organisation=sites[-1], utilisateur=contribs[1], role="contributeur"))
        liens.append(Attribution(kpi=calc[0], organisation=sites[0], utilisateur=contribs[2], role="contributeur"))
        for k in saisis_site + fil:
            liens.append(Attribution(kpi=k, organisation=pays[0], utilisateur=cls.v_pays, role="validateur"))
            liens.append(Attribution(kpi=k, organisation=filiales[1], utilisateur=cls.v_filiale, role="validateur"))
        Attribution.objects.bulk_create(liens, ignore_conflicts=True)

        def etat(periode, k, o):
            tirage = h.random()
            if tirage < 0.25:
                return None  # à saisir
            statut = "valide" if tirage < 0.6 else "brouillon"
            na = h.random() < 0.15
            valeur = None if na or k.type_reponse.format == "oui_non" else Decimal(h.randint(1, 900))
            texte = h.choice(["Oui", "Non"]) if not na and k.type_reponse.format == "oui_non" else ""
            return Reponse(periode=periode, kpi=k, organisation=o, statut=statut, non_applicable=na, valeur=valeur, texte=texte,
                           origine=h.choice(["saisie", "import"]))

        reponses = []
        for c in (cls.c25, cls.c, cls.cm):
            for o in sites + filiales + pays + [cls.g]:
                for k in (saisis_site if o.niveau_id == Niveau.SITE else fil if o.niveau_id == Niveau.ENTITY else
                          [fe] if o.niveau_id == Niveau.COUNTRY else []):
                    if c is cls.cm and k is not mensuel:
                        continue
                    r = etat(c.periode, k, o)
                    if r is not None:
                        reponses.append(r)
            if c is not cls.cm:
                reponses.append(Reponse(periode=c.periode, kpi=fe, organisation=sites[-1], valeur=Decimal("0.5"), statut="valide"))
        # valeur saisie à la filiale pour DESSUS : ses sites ne sont plus attendus (couverts)
        reponses = [r for r in reponses if not (r.kpi_id == "DESSUS" and r.periode_id == cls.c.periode_id
                                                and r.organisation.parent_id == filiales[0].pk)]
        reponses.append(Reponse(periode=cls.c.periode, kpi=dessus, organisation=filiales[0], valeur=Decimal(50), statut="brouillon"))
        Reponse.objects.bulk_create(reponses)
        for c in (cls.c25, cls.c, cls.cm):
            recalculer(c, propager=False)
        controler(cls.c)
        Alerte.objects.filter(campagne=cls.c, pk__in=list(Alerte.objects.filter(campagne=cls.c).values_list("pk", flat=True))[::3]) \
            .update(statut=Alerte.Statut.JUSTIFIEE, justification="Vérifié.")
        cls.personnes = [cls.admin, *contribs[:3], cls.v_pays, cls.v_filiale, cls.lecteur, cls.lecteur_pays, cls.auditeur]

    def test_jeu_couvre_tous_les_etats(self):
        etats = set()
        for c in (self.c, self.c2, self.cm):
            for l in S.lignes(self.admin, c):
                etats |= {l.statut, ("na", l.na), ("facultatif", l.facultatif), ("couverte", l.couverte is not None),
                          ("sans SPOC", not l.spocs), ("deux SPOC", len(l.spocs) > 1)}
        for attendu in (Reponse.Statut.A_SAISIR, Reponse.Statut.BROUILLON, Reponse.Statut.VALIDE, ("na", True),
                        ("facultatif", True), ("couverte", True), ("sans SPOC", True), ("deux SPOC", True)):
            self.assertIn(attendu, etats)
        self.assertTrue(Alerte.objects.filter(campagne=self.c, statut=Alerte.Statut.JUSTIFIEE).exists())
        self.assertTrue(Alerte.objects.filter(campagne=self.c, statut=Alerte.Statut.OUVERTE).exists())

    def test_memes_lignes_et_memes_compteurs(self):
        for u in self.personnes:
            for c in (self.c, self.c2, self.cm):
                with self.subTest(personne=u.username, campagne=str(c)):
                    plan = Plan(c.referentiel)
                    complètes = S.lignes(u, c, plan=plan)
                    legeres = S.lignes(u, c, plan=plan, legere=True)
                    self.assertEqual([cle_ligne(l) for l in legeres], [cle_ligne(l) for l in complètes])
                    t_avant, t_apres = tableau_de_bord_avant(complètes, plan), S.tableau_de_bord(legeres, plan)
                    self.assertEqual(resume_tdb(S.tableau_de_bord(complètes, plan)), resume_tdb(t_avant))
                    self.assertEqual(resume_tdb(t_apres), resume_tdb(t_avant))
                    self.assertEqual(suivi(c, t_apres), suivi(c, t_avant))
                    self.assertEqual(S.progression(legeres), S.progression(complètes))

    def test_memes_relances(self):
        ouvertes = [self.c, self.c2, self.cm]
        for u in [self.admin, self.v_pays, self.v_filiale, None]:
            for cibles in (ouvertes, [self.c]):
                with self.subTest(personne=getattr(u, "username", "automatique"), cibles=len(cibles)):
                    with comme_avant():
                        avant, sans_avant = R.a_faire(cibles, par=u), R.restes_sans_spoc(cibles, par=u)
                    apres, sans_apres = R.a_faire(cibles, par=u), R.restes_sans_spoc(cibles, par=u)
                    self.assertEqual(resume_relances(apres), resume_relances(avant))
                    self.assertEqual(sans_apres, sans_avant)
                    self.assertTrue(avant)

    def pages(self, u):
        """HTML des pages qui comptent, et JSON du visuel « remplissage », pour la personne ``u``."""
        self.client.force_login(u)
        sortie = {}
        urls = [f"/tableau-de-bord/?campagne={c.pk}" for c in (self.c, self.c2, self.cm)] + [f"/tableau-de-bord/?campagne={self.c.pk}&tri=taux"]
        if u.est_admin or u.role == Utilisateur.Role.VALIDATEUR:
            urls += [f"/tableau-de-bord/relances/?campagne={self.c.pk}", f"/tableau-de-bord/relances/?campagne={self.c.pk}&portee=campagne"]
        if u.est_admin:
            urls.append("/administration/")
        for url in urls:
            r = self.client.get(url, secure=True)
            self.assertEqual(r.status_code, 200, url)
            sortie[url] = sans_jetons(r.content.decode())
        for par in ("total", "themes", "organisations"):
            for org in (None, self.pays[0]):
                visuels = vue({"type": "remplissage", "options": {"remplissage_par": par}})
                propre, erreurs = VS.valider_vue({"nom": "Essai", "visuels": visuels}, u)
                self.assertEqual(erreurs, [])
                parametres = {"periode": str(self.c.periode.pk), **({"org": str(org.pk)} if org else {})}
                sortie[f"visuel {par} {org}"] = VS.donnees(u, {}, propre["visuels"], parametres, campagne_choisie=self.c)
        return sortie

    def test_memes_pages(self):
        for u in self.personnes:
            with self.subTest(personne=u.username):
                with comme_avant():
                    avant = self.pages(u)
                apres = self.pages(u)
                self.assertEqual(list(apres), list(avant))
                for cle in avant:
                    self.assertEqual(apres[cle], avant[cle], cle)

    def test_ancienne_construction_bien_utilisee(self):
        """Garde du test : sous le remplacement, les pages reçoivent bien des lignes complètes (réponse lue)."""
        vues = []

        def espion(*a, **kw):
            sortie = ancienne_construction(*a, **kw)
            vues.extend(sortie)
            return sortie

        with mock.patch.object(S, "construire_lignes", espion):
            self.client.force_login(self.admin)
            self.client.get(f"/tableau-de-bord/?campagne={self.c.pk}", secure=True)
        self.assertTrue(any(l.reponse is not None for l in vues))
        self.assertTrue(all(l.non_applicable is None for l in vues))


class RamasseMiettesTests(TestCase):
    """``sans_ramasse_miettes`` : suspendu pendant la fabrication des lignes, rétabli à la sortie, tel qu'il était."""

    def test_retabli_a_la_sortie_meme_imbrique_ou_en_erreur(self):
        import gc

        self.assertTrue(gc.isenabled())
        with S.sans_ramasse_miettes():
            self.assertFalse(gc.isenabled())
            with S.sans_ramasse_miettes():
                self.assertFalse(gc.isenabled())
            self.assertFalse(gc.isenabled())  # le premier n'est pas encore sorti
        self.assertTrue(gc.isenabled())
        with self.assertRaises(ValueError), S.sans_ramasse_miettes():
            raise ValueError
        self.assertTrue(gc.isenabled())

    def test_reste_suspendu_s_il_l_etait_avant(self):
        import gc

        gc.disable()
        try:
            with S.sans_ramasse_miettes():
                pass
            self.assertFalse(gc.isenabled())
        finally:
            gc.enable()
