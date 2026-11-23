"""Prise IA et KPI sensibles (règle du projet, P2) : réglage de l'espace « Les KPI sensibles peuvent
être envoyés à l'assistant IA », éteint par défaut. Éteint, aucune valeur d'un KPI « Restreint » ou « Confidentiel », ni
d'un KPI calculé qui en dérive de proche en proche (même définition que pour les assistants MCP :
``collecte.sensibles.sensibles_et_derives``), ne part chez le fournisseur, par aucun des trois usages :

- expliquer une alerte : pas de bouton sur une alerte qui cite un tel KPI (sa case, ou un côté d'une règle), refus côté
  serveur sans rien envoyer ; les autres alertes partent comme avant, sans ces nombres ;
- correspondances de la reprise : les KPI sensibles et leurs dérivés sont retirés de la liste des KPI envoyée ;
- traductions : le nom et les descriptions de ces KPI ne partent pas.

Base : valeurs sensibles reconnaissables (nombres uniques) ; ce qui « part » est lu dans les requêtes reçues par le
fournisseur factice. Réglage allumé : comportement d'avant. Données inventées uniquement."""
import re

from django.urls import reverse

from parametres.aides_tests.ia import AvecIA
from parametres.models import CategorieDescription, Instance, Langue
from referentiel.models import KPI, Description, Niveau

from . import saisie as S
from .aides_tests import echanges
from .aides_tests.coherence import FETCH, BasePanneau
from .coherence import controler
from .models import Alerte, Journal, RegleCoherence, Reponse
from .test_appeler_ia_sans_noms import envoye
from .test_reprise import classeur

BOUTON = 'data-ia-expliquer="'
SECRETS = ("271828", "161803", "57721", "31415")  # SEC 2026, SEC passé, RES 2026, RES passé
CACHES = {"SEC", "RES", "CPY", "DEUX"}  # sensibles et calculés qui en dérivent
NOM_SECRET = "Salaire Xylophone du dirigeant"
DESC_SECRET = "Prime Quokka versée au dirigeant"


def plat(texte):
    return re.sub(r"[\s  .,'’]", "", texte)


def cite_cache(a):
    return a.kpi_id in CACHES or any(k in CACHES for k in a.kpis_concernes.split())


class AlertesSensiblesTests(AvecIA, BasePanneau):
    def setUp(self):
        super().setUp()
        self.sec = KPI.objects.create(code="SEC", libelle=NOM_SECRET, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      methode_agregation="Somme", confidentialite=KPI.Confidentialite.CONFIDENTIEL)
        self.res = KPI.objects.create(code="RES", libelle="Indemnité restreinte", type_saisie_id="Saisi",
                                      granularite_id=Niveau.ENTITY, methode_agregation="Somme",
                                      confidentialite=KPI.Confidentialite.RESTREINT)
        KPI.objects.create(code="CPY", libelle="Copie", type_saisie_id="Calculé", formule="[SEC] * 1",
                           granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        KPI.objects.create(code="DEUX", libelle="Copie de copie", type_saisie_id="Calculé", formule="[CPY] + 0",
                           granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        for c in self.anciennes:
            for k, v in ((self.sec, 161803), (self.res, 31415)):
                Reponse.objects.create(periode=c.periode, kpi=k, organisation=self.e1, valeur=v, statut=Reponse.Statut.VALIDE,
                                       origine=Reponse.Origine.IMPORT)
        # règles : un côté sensible (direct, ou par un KPI dérivé) ; une règle sans KPI sensible
        RegleCoherence.objects.create(nom="Effectif et salaire", gauche="[EFF]", operateur=">=", droite="[SEC]",
                                      niveau_id=Niveau.ENTITY, description="Voir la paie.")
        RegleCoherence.objects.create(nom="Formés et copie", gauche="[FORM]", operateur=">=", droite="[DEUX]",
                                      niveau_id=Niveau.ENTITY)
        RegleCoherence.objects.create(nom="Formés au plus l'effectif", gauche="[FORM]", operateur="<=", droite="[EFF]",
                                      niveau_id=Niveau.ENTITY)
        self.saisir(self.eff, 260)  # écart avec N-1 sur un KPI non sensible
        self.saisir(self.form, 400)  # règle « formés au plus l'effectif » non respectée
        S.enregistrer(self.admin, self.c, self.sec, self.e1, "271828", False, "")  # écart avec N-1, règles
        S.enregistrer(self.admin, self.c, self.res, self.e1, "57721", False, "")
        controler(self.c)
        self.alertes_c = list(Alerte.objects.filter(campagne=self.c).exclude(controle=Alerte.Controle.CALCUL))
        self.allumer()

    def expliquer(self, a):
        return self.client.post(reverse("collecte:alerte_ia", args=[a.pk]), **FETCH)

    def test_reglage_eteint_par_defaut(self):
        self.assertFalse(Instance._meta.get_field("ia_kpi_sensibles").default)
        self.assertFalse(Instance.courante().ia_kpi_sensibles)

    def test_jeu_de_donnees(self):
        sensibles = [a for a in self.alertes_c if cite_cache(a)]
        autres = [a for a in self.alertes_c if not cite_cache(a)]
        self.assertTrue(any(a.kpi_id == "SEC" for a in sensibles))
        self.assertTrue(any(a.kpi_id == "RES" for a in sensibles))
        self.assertTrue(any(a.regle and "DEUX" in a.kpis_concernes.split() for a in sensibles))  # dérivé de proche en proche
        self.assertTrue(any(a.regle and a.kpi_id not in CACHES for a in sensibles))  # règle posée sur EFF qui cite SEC
        self.assertTrue(autres)

    def test_eteint_aucun_nombre_sensible_ne_part_ni_bouton(self):
        self.client.force_login(self.admin)
        envoyees = 0
        for a in self.alertes_c:
            with self.subTest(alerte=(a.controle, a.kpi_id, a.regle_id)):
                avant = len(self.factice.demandes)
                fiche = self.client.get(reverse("collecte:alerte", args=[a.pk])).content.decode()
                rep = self.expliquer(a)
                if cite_cache(a):
                    self.assertNotIn(BOUTON, fiche)
                    self.assertEqual(rep.status_code, 403)
                    self.assertEqual(len(self.factice.demandes), avant)
                else:
                    self.assertIn(BOUTON, fiche)
                    self.assertEqual(rep.status_code, 200)
                    self.assertEqual(len(self.factice.demandes), avant + 1)
                    envoyees += 1
        self.assertTrue(envoyees)
        for d in self.factice.demandes:
            texte = plat(envoye(d))
            for s in SECRETS:
                self.assertNotIn(s, texte)
            self.assertNotIn(NOM_SECRET.replace(" ", ""), texte)
        self.assertEqual(Journal.objects.filter(action="ia_appel").count(), envoyees)

    def test_eteint_panneau_sans_bouton_sur_une_alerte_sensible(self):
        self.client.force_login(self.admin)
        for kpi in (self.eff, self.form, self.sec, self.res):
            panneau = self.client.get(self.url(kpi, self.e1), **FETCH).json()["html"]
            for a in self.alertes_c:
                url = reverse("collecte:alerte_ia", args=[a.pk])
                if cite_cache(a):
                    self.assertNotIn(url, panneau, (kpi.code, a.controle, a.kpi_id))
        panneau = self.client.get(self.url(self.form, self.e1), **FETCH).json()["html"]
        libre = next(a for a in self.alertes_c if a.regle and not cite_cache(a))
        self.assertIn(reverse("collecte:alerte_ia", args=[libre.pk]), panneau)  # une alerte non sensible garde son bouton

    def test_allume_comportement_d_avant(self):
        i = Instance.courante()
        i.ia_kpi_sensibles = True
        i.save()
        self.client.force_login(self.admin)
        a = next(a for a in self.alertes_c if a.kpi_id == "SEC" and a.controle == Alerte.Controle.ECART_N1)
        self.assertIn(BOUTON, self.client.get(reverse("collecte:alerte", args=[a.pk])).content.decode())
        self.assertEqual(self.expliquer(a).status_code, 200)
        texte = plat(envoye(self.factice.demandes[-1]))
        self.assertIn("271828", texte)
        self.assertIn("161803", texte)
        regle = next(a for a in self.alertes_c if a.regle and a.kpi_id == "EFF" and "SEC" in a.kpis_concernes.split())
        self.assertEqual(self.expliquer(regle).status_code, 200)
        self.assertIn("271828", plat(envoye(self.factice.demandes[-1])))


class RepriseTraductionsSensiblesTests(AvecIA, echanges.Base):
    def setUp(self):
        super().setUp()
        self.sec = KPI.objects.create(code="SEC", libelle=NOM_SECRET, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      methode_agregation="Somme", confidentialite=KPI.Confidentialite.RESTREINT)
        KPI.objects.create(code="CPY", libelle="Copie Ornithorynque", type_saisie_id="Calculé", formule="[SEC] * 1",
                           granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        cat = CategorieDescription.objects.first() or CategorieDescription.objects.create(code="description", libelle="Description")
        Description.objects.create(kpi=self.sec, categorie=cat, langue="fr", texte=DESC_SECRET)
        Description.objects.create(kpi=self.eff, categorie=cat, langue="fr", texte="Personnes présentes au 31/12")
        Langue.objects.get_or_create(code="es", defaults={"libelle": "Español", "ordre": 3})
        self.allumer()
        self.client.force_login(self.admin)

    def traduire(self):
        for section in ("kpi", "descriptions", "themes", "libelles"):
            self.client.post(reverse("parametres:traductions_ia", args=["es"]), {"section": section})
        return " ".join(envoye(d) for d in self.factice.demandes)

    def reprise(self):
        url = reverse("collecte:admin_reprise")
        fichier = classeur([["Indicateur", "Entité", 2023], ["Effectif total fin d'année", "E1", 104]], "ancien.xlsx")
        r = self.client.post(url + "?etape=fichier", {"action": "deposer", "fichier": fichier, "source": "Ancien"},
                             follow=True).context["r"]
        donnees = {"action": "suivant", "entete": r.entete + 1, "forme": r.forme, "valeurs": ["2023"]}
        donnees.update({f"role_{role}": t for role, t in r.colonnes.items()})
        self.client.post(url + "?etape=colonnes", donnees)
        self.client.get(url + "?etape=correspondances")
        self.assertEqual(self.client.post(reverse("collecte:admin_reprise_ia"), **FETCH).status_code, 200)
        return envoye(self.factice.demandes[-1])

    def test_eteint_traductions_sans_kpi_sensible(self):
        texte = self.traduire()
        self.assertIn("Effectif", texte)
        self.assertIn("Personnes présentes", texte)
        for s in (NOM_SECRET, DESC_SECRET, "Copie Ornithorynque"):
            self.assertNotIn(s, texte)

    def test_eteint_reprise_sans_kpi_sensible(self):
        texte = self.reprise()
        self.assertIn('"code":"EFF"', texte)
        for s in (NOM_SECRET, "Copie Ornithorynque", '"code":"SEC"', '"code":"CPY"'):
            self.assertNotIn(s, texte)

    def test_allume_comportement_d_avant(self):
        Instance.objects.filter(pk=1).update(ia_kpi_sensibles=True)
        texte = self.traduire() + self.reprise()
        for s in (NOM_SECRET, DESC_SECRET, "Copie Ornithorynque", '"code":"SEC"'):
            self.assertIn(s, texte)
