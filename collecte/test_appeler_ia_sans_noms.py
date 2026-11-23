"""Prise IA : aucun nom d'organisation ni de personne de la base ne part chez le fournisseur (docs/ai_socket.md, 6 a,
IA3), pour chaque type d'alerte et chaque usage. Jeu de données aux noms reconnaissables ; ce qui « part » est lu dans
les requêtes reçues par le fournisseur factice (instructions, bloc de données, tout le reste de la requête).

Un calcul impossible n'a rien à justifier et son message de calcul cite des organisations (« Valeur non saisie : EFF /
<organisation> », « Incomplet : <organisations> ») : pas de bouton « Expliquer avec l'IA », et la demande est refusée
côté serveur, sans rien envoyer."""
import dataclasses

from django.urls import reverse

from parametres.aides_tests.ia import AvecIA
from parametres.models import Langue
from parametres.referentiel import unite_depuis_symbole as U
from referentiel.models import KPI, Niveau

from . import saisie as S
from .aides_tests import echanges
from .aides_tests.coherence import FETCH, BasePanneau
from .coherence import controler
from .models import Alerte, Journal, RegleCoherence
from .test_reprise import classeur

ORGS = {"g": "Zorglubia Holding", "p": "Quetzalie Pays", "e1": "Usine Brontosaure", "e2": "Atelier Pterodactyle"}
PERSONNES = {"contrib": ("Hortense", "Vermicelle"), "autre": ("Barnabé", "Tournesolo"), "admin": ("Clotilde", "Pimprenelle")}


def renommer(test):
    """Noms reconnaissables pour les organisations et les comptes de la base du test ; renvoie les textes à chercher."""
    for attr, nom in ORGS.items():
        o = getattr(test, attr)
        o.nom = nom
        o.save()
    jamais = set(ORGS.values())
    for attr, (prenom, nom) in PERSONNES.items():
        u = getattr(test, attr)
        u.first_name, u.last_name, u.email = prenom, nom, f"{prenom.lower()}.{nom.lower()}@exemple.test"
        u.save()
        jamais |= {prenom, nom, u.email, u.username}
    jamais.discard("admin")  # identifiant trop commun (« administrator » dans les consignes) : prénom et nom suffisent
    return jamais


def envoye(requete):
    """Tout ce qu'une requête porte, en un texte (sauf la clé)."""
    return " ".join(str(v) for k, v in dataclasses.asdict(requete).items() if k != "cle")


class AlertesSansNomsTests(AvecIA, BasePanneau):
    def setUp(self):
        super().setUp()
        self.jamais = renommer(self)
        self.allumer()

    def produire_chaque_type(self):
        """Une alerte réelle de chaque contrôle, produite par les contrôles de l'outil."""
        RegleCoherence.objects.create(nom="Formés au plus le dixième de l'effectif", gauche="[FORM]", operateur="<=",
                                      droite="[EFF] / 10", niveau_id=Niveau.ENTITY)
        self.saisir(self.eff, 260)  # écart avec N-1 (seuil 20 %)
        self.c.seuil_ecart = None
        self.c.save()
        self.saisir(self.form, 400)  # hors historique (médiane 50) et règle non respectée
        self.saisir(self.fe, "2,1")  # paramètre hérité modifié
        self.saisir(self.eff, "-3")  # format (comptage négatif)
        self.saisir(self.form, "", com="Rien cette année", na=True)  # rupture de série
        det = KPI.objects.create(code="DET", libelle="Déchets", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                 methode_agregation="Somme", unite=U("t"), saisie_au_dessus=True)
        for org, v in ((self.e1, 10), (self.e2, 20), (self.p, 100)):
            S.enregistrer(self.admin, self.c, det, org, str(v), False, "")  # écart avec le détail
        KPI.objects.create(code="DIV", libelle="Ratio", type_saisie_id="Calculé", formule="[EFF] / ([EFF] - [EFF])",
                           granularite_id=Niveau.ENTITY)
        S.enregistrer(self.admin, self.c, self.eff, self.e2, "5", False, "")  # recalcul : division par zéro
        controler(self.c)
        # calcul impossible au message tel que le calculateur l'écrit pour une valeur manquante (cite l'organisation)
        Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.CALCUL,
                              gravite=Alerte.Gravite.INFO, message=f"Valeur non saisie : EFF / {self.e1.nom}")

    def test_aucun_nom_dans_ce_qui_part_pour_chaque_type_d_alerte(self):
        self.produire_chaque_type()
        self.client.force_login(self.admin)
        vus = set()
        for a in Alerte.objects.filter(campagne=self.c).exclude(controle=Alerte.Controle.CALCUL):
            avant = len(self.factice.demandes)
            rep = self.client.post(reverse("collecte:alerte_ia", args=[a.pk]), **FETCH)
            self.assertEqual(rep.status_code, 200, a.controle)
            self.assertEqual(len(self.factice.demandes), avant + 1, a.controle)
            texte = envoye(self.factice.demandes[-1])
            for nom in self.jamais:
                self.assertNotIn(nom, texte, f"{a.controle} : {nom}")
            vus.add(a.controle)
        attendus = set(Alerte.Controle.values) - {Alerte.Controle.CALCUL}
        self.assertEqual(vus, attendus)  # chaque type d'alerte a été essayé

    def test_calcul_impossible_ni_bouton_ni_envoi(self):
        self.produire_chaque_type()
        calculs = list(Alerte.objects.filter(campagne=self.c, controle=Alerte.Controle.CALCUL))
        self.assertTrue(any(self.e1.nom in a.message for a in calculs))
        self.assertTrue(any("zéro" in a.message for a in calculs))  # aussi un vrai calcul impossible, produit par l'outil
        self.client.force_login(self.admin)
        for a in calculs:
            fiche = self.client.get(reverse("collecte:alerte", args=[a.pk])).content.decode()
            self.assertNotIn('data-ia-expliquer="', fiche)
            self.assertEqual(self.client.post(reverse("collecte:alerte_ia", args=[a.pk]), **FETCH).status_code, 403)
        panneau = self.client.get(self.url(self.eff, self.e1), **FETCH).json()["html"]
        for a in calculs:
            self.assertNotIn(reverse("collecte:alerte_ia", args=[a.pk]), panneau)
        self.assertEqual(self.factice.demandes, [])
        self.assertFalse(Journal.objects.filter(action="ia_appel").exists())


class RepriseSansNomsTests(AvecIA, echanges.Base):
    def test_aucun_nom_dans_ce_qui_part(self):
        jamais = renommer(self)
        self.allumer()
        self.client.force_login(self.admin)
        url = reverse("collecte:admin_reprise")
        fichier = classeur([["Indicateur", "Entité", "Responsable", 2023],
                            ["Effectif total fin d'année", ORGS["e1"], "Hortense Vermicelle", 104],
                            ["Effectif total fin d'année", ORGS["e2"], "Barnabé Tournesolo", 41]], "ancien.xlsx")
        r = self.client.post(url + "?etape=fichier", {"action": "deposer", "fichier": fichier, "source": "Ancien"},
                             follow=True).context["r"]
        donnees = {"action": "suivant", "entete": r.entete + 1, "forme": r.forme, "valeurs": ["2023"]}
        donnees.update({f"role_{role}": t for role, t in r.colonnes.items()})
        self.client.post(url + "?etape=colonnes", donnees)
        self.client.get(url + "?etape=correspondances")
        self.assertEqual(self.client.post(reverse("collecte:admin_reprise_ia"), **FETCH).status_code, 200)
        self.assertEqual(len(self.factice.demandes), 1)
        texte = envoye(self.factice.demandes[0])
        self.assertIn("Effectif total fin d'année", texte)
        for nom in jamais:
            self.assertNotIn(nom, texte, nom)


class TraductionsSansNomsTests(AvecIA, echanges.Base):
    def test_aucun_nom_dans_ce_qui_part(self):
        jamais = renommer(self)
        Langue.objects.get_or_create(code="es", defaults={"libelle": "Español", "ordre": 3})
        self.allumer()
        self.client.force_login(self.admin)
        for section in ("kpi", "descriptions", "themes", "libelles"):
            self.client.post(reverse("parametres:traductions_ia", args=["es"]), {"section": section})
        self.assertTrue(self.factice.demandes)
        for r in self.factice.demandes:
            texte = envoye(r)
            for nom in jamais:
                self.assertNotIn(nom, texte, nom)
