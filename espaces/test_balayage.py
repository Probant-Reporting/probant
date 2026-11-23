"""Balayage : chaque page de l'outil ouverte dans le second espace (/espace/essai/…), pour chaque rôle, répond comme dans
l'espace principal, sans aucune requête vers la base de l'autre espace (``FuiteEspace`` ferait échouer le test)."""
from decimal import Decimal

from django.test import Client
from django.urls import URLResolver, get_resolver

from collecte.models import Campagne, Reponse
from referentiel.models import KPI, Niveau, Organisation, Utilisateur

from . import contexte as E
from .essais import EspacesTestCase
from .aides_tests import creer
from collecte.aides_tests.espaces import jeu

EXCLUES = {"deconnexion/", "sante/"}


def pages():
    """Adresses de l'outil sans paramètre (le mode expert : sa page d'accueil seulement)."""
    def parcourir(motifs, prefixe=""):
        for m in motifs:
            if isinstance(m, URLResolver):
                if str(m.pattern).startswith("admin"):
                    continue
                yield from parcourir(m.url_patterns, prefixe + str(m.pattern))
            else:
                yield prefixe + str(m.pattern)
    return sorted({p for p in parcourir(get_resolver().url_patterns) if "<" not in p and "^" not in p} - EXCLUES) + ["admin/"]


class BalayageTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.comptes = {}
        for role in ("admin", "validateur", "contributeur", "lecteur", "auditeur"):
            cls.comptes[role] = creer(f"{role}@exemple.example", role)
            creer(f"{role}@exemple.example", role, "essai")
        for code, org, kpi in (("principal", "Siège", "KPI-A"), ("essai", "Siège", "KPI-A")):
            jeu(code, org, kpi)

    def balayer(self, role):
        c = Client(raise_request_exception=True)
        c.force_login(Utilisateur.objects.get(pk=self.comptes[role].pk))
        ecarts = []
        for p in pages():
            ici = c.get("/" + p)
            la = c.get("/espace/essai/" + p)
            if ici.status_code != la.status_code:
                ecarts.append(f"{p} : {ici.status_code} ici, {la.status_code} dans l'espace « essai »")
            if la.status_code in (301, 302) and la["Location"].startswith("/") and not la["Location"].startswith(
                    ("/espace/essai/", "/static/")):
                ecarts.append(f"{p} : redirigé hors de l'espace vers {la['Location']}")
        self.assertEqual(ecarts, [])
        self.assertGreater(len(pages()), 60)

    def test_administrateur(self):
        self.balayer("admin")

    def test_validateur(self):
        self.balayer("validateur")

    def test_contributeur(self):
        self.balayer("contributeur")

    def test_lecteur(self):
        self.balayer("lecteur")

    def test_auditeur(self):
        self.balayer("auditeur")

    def test_aucune_fuite_dans_le_principal(self):
        """Des données propres à chaque espace (organisation, KPI, valeur aux noms uniques) : aucune page d'un espace ne
        montre celles de l'autre. Témoin : chaque marqueur apparaît bien sur au moins une page de son propre espace (sinon
        l'absence ne prouverait rien)."""
        marqueurs = {}
        for code, prefixe in (("principal", "/"), ("essai", "/espace/essai/")):
            nom, kpi, libelle = f"Orgmarque{code.capitalize()}", f"KPIMARQUE{code.upper()}", f"Libellemarque{code.capitalize()}"
            with E.activer(code):
                org = Organisation.objects.create(nom=nom, niveau_id=Niveau.GROUP)
                KPI.objects.create(code=kpi, libelle=libelle, type_saisie_id="Saisi", granularite_id=Niveau.GROUP,
                                   methode_agregation="Somme")
                c = Campagne.objects.get()
                Reponse.objects.create(periode=c.periode, kpi_id=kpi, organisation=org, valeur=Decimal(1),
                                       origine=Reponse.Origine.SAISIE, statut=Reponse.Statut.VALIDE)
            marqueurs[code] = (prefixe, (nom, kpi, libelle))
        c = Client(raise_request_exception=True)
        c.force_login(Utilisateur.objects.get(pk=self.comptes["admin"].pk))
        textes = {code: [] for code in marqueurs}
        for code, (prefixe, _) in marqueurs.items():
            for p in pages():
                r = c.get(prefixe + p)
                type_ = r.get("Content-Type", "")
                if r.status_code == 200 and ("text/" in type_ or "json" in type_) and not getattr(r, "streaming", False):
                    textes[code].append((p, r.content.decode(errors="ignore")))
        fuites, absents = [], []
        for code, (_, propres) in marqueurs.items():
            autre = "essai" if code == "principal" else "principal"
            for m in propres:
                if not any(m in t for _, t in textes[code]):
                    absents.append(f"{m} introuvable dans l'espace « {code} »")
                fuites += [f"{m} (espace « {code} ») visible dans « {autre} » : {p}" for p, t in textes[autre] if m in t]
        self.assertEqual(absents, [])
        self.assertEqual(fuites, [])
