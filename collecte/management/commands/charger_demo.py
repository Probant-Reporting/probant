"""Données fictives de démonstration (Codespaces, poste de développement) : Exemplia, fabricant fictif d'emballages
4 niveaux Groupe › Pays › Filiale › Site, la norme volontaire VS (modules de base et
complet) et les onze modèles ESRS installés sans valeur ni campagne ; exercices 2024 et 2025 clôturés, exercice 2026 ouvert et en partie saisi (voir
_exemplia.py). La seconde démo, à 3 niveaux, est retirée désormais : son contenu reste un jeu d'essai des
tests (collecte/aides_tests/jeu_trois_niveaux.py). Option --espaces : un second espace « Achats » (_achats.py).
Aucune donnée réelle : noms inventés, e-mails @exemple.test, adresses fictives.
Langue : la démo suit la langue de l'installation (``DEFAULT_LANGUAGE``, anglais par défaut) ; ``--language`` en choisit une autre
parmi les sept langues de l'interface. Les contenus existent dans les sept langues ; les textes écrits par les personnes fictives
(commentaires, justifications, textes rédigés) sont dans la langue choisie.
"""
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import models

from collecte.models import Campagne, Journal, Reponse
from collecte.statistiques_postgresql import statistiques_a_jour
from parametres import referentiel as PR
from referentiel.models import KPI, Organisation, Utilisateur

from . import _exemplia as EXEMPLIA
from . import _exemplia_textes as TX
from espaces import contexte as ESP

MOT_DE_PASSE = "demo-probant-2026"
COMPTES = [
    # identifiant, prénom, nom, rôle
    ("admin", "Alice", "Admin (démo)", Utilisateur.Role.ADMIN),
    ("validateur", "Victor", "Validateur (démo)", Utilisateur.Role.VALIDATEUR),
    ("contributeur", "Camille", "Contributrice (démo)", Utilisateur.Role.CONTRIBUTEUR),
    ("lecteur", "Louise", "Lectrice (démo)", Utilisateur.Role.LECTEUR),
    ("auditeur", "Arthur", "Auditeur (démo)", Utilisateur.Role.AUDITEUR),
]
# Marqueur de base de démonstration : une ligne du journal posée par la commande elle-même (aucun changement de modèle ;
# le journal n'est jamais vidé et suit la base dans ses sauvegardes). La commande ne touche une base que si elle est vide
# ou porte ce marqueur ; sinon elle refuse (--force-on-existing-data pour passer outre, en connaissance de cause).
MARQUEUR = "demo_chargee"
REFUS = ("This database is not a demo database (no demo marker): the demo would create or reset the demo accounts "
         "(admin, validateur…) with the public password \"{mdp}\", admin being a superuser, and overwrite real accounts "
         "with the same user names. Use an empty database (another DATA_DIR or SQLITE_FILE), or add "
         "--force-on-existing-data if you are sure.")


def langue_installation():
    """Langue de la démo par défaut : celle de l'installation (``DEFAULT_LANGUAGE``), parmi les sept langues de l'interface ;
    une autre (ex. « pt-br ») est ramenée à sa langue de base, puis à l'anglais."""
    code = (settings.LANGUE_PAR_DEFAUT or "en").lower()
    for essai in (code, code.split("-")[0]):
        if essai in TX.LANGUES:
            return essai
    return "en"


def base_de_demo():
    """Vrai si la base de l'espace courant a été faite par cette commande : marqueur posé, ou (bases de démo d'avant le
    marqueur) compte « admin@exemple.test » dont le mot de passe est encore le mot de passe public de la
    démo. Une vraie base n'a pas ce compte : « exemple.test » est un domaine réservé aux essais, et un compte qui aurait
    gardé un mot de passe public serait déjà ouvert à tous."""
    if Journal.objects.filter(action=MARQUEUR).exists():
        return True
    admin = Utilisateur.objects.filter(username="admin", email="admin@exemple.test").first()
    return bool(admin and admin.check_password(MOT_DE_PASSE))


def base_vide():
    """Rien d'une vraie installation : ni organisation, ni KPI, ni campagne, ni compte."""
    return not (Organisation.objects.exists() or KPI.objects.exists() or Campagne.objects.exists()
                or Utilisateur.objects.exists())


def marquer_demo(client):
    if not Journal.objects.filter(action=MARQUEUR).exists():
        from parametres.models import Instance

        Journal.ecrire(None, MARQUEUR, Instance.courante(), "client", "", client)


def espaces_demo_vides():
    """--reinitialiser (développement) : espaces supplémentaires de la démo supprimés (base et fichiers) et registre
    vidé ; l'espace principal est vidé ensuite par le flush habituel."""
    import shutil

    from django.db import connections

    from espaces.models import AccesEspace, Compte, Espace

    with ESP.toutes_les_bases():
        for e in Espace.objects.exclude(code=ESP.PRINCIPAL):
            alias = ESP.declarer(e.code)
            c = connections[alias]
            if c.vendor == "postgresql":
                with c.cursor() as cur:
                    cur.execute(f'DROP SCHEMA IF EXISTS "espace_{e.code}" CASCADE')
            c.close()
            shutil.rmtree(ESP.dossier_espace(e.code), ignore_errors=True)
            e.delete()
        AccesEspace.objects.all().delete()
        Compte.objects.all().delete()


class Command(BaseCommand):
    help = "Loads fictitious demo data (organisations, KPIs, accounts, campaigns, entries)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", "--reinitialiser", dest="reinitialiser", action="store_true", help="Empty the whole database before reloading the demo (development only, DJANGO_DEBUG=1).")
        parser.add_argument("--client", choices=["exemplia"], default="exemplia",
                            help="exemplia, the only demo: fictitious manufacturer, 4 levels, Voluntary Standard VS, "
                                 "2024 and 2025 closed, 2026 open")
        parser.add_argument("--language", dest="langue", choices=TX.LANGUES, default=None,
                            help="Language of the demo (interface of the demo accounts and texts written by the fictitious people): "
                                 "en, fr, es, de, it, nl or pt. Default: the language of the installation (DEFAULT_LANGUAGE).")
        parser.add_argument("--spaces", "--espaces", dest="espaces", action="store_true",
                            help="Two spaces: the main space (renamed \"Sustainability\") and a \"Achats\" (purchasing) space (docs/spaces.md)")
        parser.add_argument("--force-on-existing-data", "--forcer-donnees-existantes", dest="forcer", action="store_true",
                            help="Load or reset the demo even if the database is not empty and has no demo marker "
                                 "(demo accounts with the public password; real accounts with the same user names are overwritten).")

    def handle(self, reinitialiser, client, **o):
        if not ESP.est_principal():
            raise CommandError("The demo is loaded from the main space (without SPACE=…).")
        if reinitialiser and settings.DEBUG:
            espaces_demo_vides()
        self.forcer = bool(o.get("forcer"))
        self.langue = o.get("langue") or langue_installation()
        self._handle(reinitialiser, client)
        if o.get("espaces"):
            self.espaces_demo()

    def espaces_demo(self):
        """Second espace « Achats » (petit jeu fictif) ; l'espace principal s'appelle « Sustainability »."""
        from espaces.creation import creer, poursuivre
        from espaces.models import Espace

        from . import _achats as ACHATS

        Espace.objects.update_or_create(code=ESP.PRINCIPAL, defaults={"nom": "Sustainability", "etat": Espace.Etat.ACTIF})
        admin = Utilisateur.objects.get(username="admin")
        e = Espace.objects.filter(code="achats").first()
        if e is None:
            e = creer("Achats", "achats", admin, reprendre_identite=True)
        elif e.etat == Espace.Etat.CREATION:
            e = poursuivre(e, admin)
        with ESP.activer("achats"):
            if KPI.objects.exists():
                if not (getattr(self, "forcer", False) or base_de_demo()):
                    raise CommandError("Space \"achats\": " + REFUS.format(mdp=MOT_DE_PASSE))
                ACHATS.comptes(MOT_DE_PASSE)
                marquer_demo("achats")
                self.stdout.write("Space \"Achats\" already loaded: demo accounts reset.")
            else:
                with ESP.atomic():
                    ACHATS.charger(MOT_DE_PASSE, self.stdout.write)
                    marquer_demo("achats")
        self.stdout.write(self.style.SUCCESS(
            "Two spaces: \"Sustainability\" (/) and \"Achats\" (/espace/achats/). admin: administrator of both; contributeur: "
            "contributor in Sustainability, validator in Achats; acheteur: Achats only; lecteur: Sustainability only."))

    def _handle(self, reinitialiser, client):
        from parametres.models import Instance

        self.client = client
        identite = EXEMPLIA.identite(self.langue)
        if reinitialiser:
            if not settings.DEBUG:
                raise CommandError("--reset is refused outside development mode (DJANGO_DEBUG=1).")
            call_command("flush", interactive=False, verbosity=0, database=ESP.alias_courant())
            from collecte.exports import creer_modeles_fournis

            creer_modeles_fournis()  # le flush efface aussi les modèles d'export et les niveaux créés par les migrations
        elif Campagne.objects.exists():
            if not (getattr(self, "forcer", False) or base_de_demo()):
                raise CommandError(REFUS.format(mdp=MOT_DE_PASSE))
            if Instance.courante().nom != identite["nom"]:
                raise CommandError(f"This database contains the demo \"{Instance.courante().nom}\": one installation = one client. "
                                   f"Add --reset to replace it, or use another database (SQLITE_FILE).")
            self.comptes_du_client(client)  # comptes de démo toujours utilisables
            marquer_demo(client)  # base de démo d'avant le marqueur : reconnue désormais sans le mot de passe
            self.stdout.write("Demo data already present (use --reset to start again from scratch). "
                              f"Demo accounts reset: password {MOT_DE_PASSE}.")
            return
        elif Organisation.objects.exists() or KPI.objects.exists():
            raise CommandError("The database already contains organisations or KPIs: add --reset to load the demo.")
        elif not base_vide() and not (getattr(self, "forcer", False) or base_de_demo()):
            raise CommandError(REFUS.format(mdp=MOT_DE_PASSE))
        Instance.objects.update_or_create(pk=1, defaults=identite)
        with ESP.atomic():
            PR.creer_par_defaut()  # types de saisie et de réponse, catégories de description d'installation
            PR.couleurs_types_par_defaut()  # démo : couleurs des types distinctes des états brouillon et validé
            EXEMPLIA.charger(MOT_DE_PASSE, self.stdout.write, self.langue)
            self.fin_de_chargement(client)
            # PostgreSQL : statistiques du planificateur relevées après la validation (test :
            # collecte/test_charger_demo_statistiques_postgresql.py)
            statistiques_a_jour()

    def fin_de_chargement(self, client):
        # « mis à jour le » jamais après « validé le » pour une valeur validée (date_maj se pose seule à
        # l'enregistrement : un auditeur y lirait une modification faite après la validation)
        Reponse.objects.filter(statut=Reponse.Statut.VALIDE, date_validation__isnull=False,
                               date_maj__gt=models.F("date_validation")).update(date_maj=models.F("date_validation"))
        with TX.regler(self.langue):
            vues_demo(client)
            listes_demo()
        marquer_demo(client)
        from collecte.calcul import geler_periodes_closes

        geler_periodes_closes()  # exercices clos de la démo : périmètre noté, comme une clôture dans l'outil
        self.stdout.write(self.style.SUCCESS(
            f"Demo loaded in language \"{self.langue}\". Accounts: {', '.join(c[0] for c in COMPTES)}; password: {MOT_DE_PASSE}"))

    def comptes_du_client(self, client):
        return EXEMPLIA.comptes(MOT_DE_PASSE)


# ---------------------------------------------------------------- Visualisation : vues partagées de démo
SITES = {"orgs_comparees": {"mode": "niveau", "niveau": "Site"}}  # les sites sous l'organisation de la vue
VUES = {  # client : [(clé du nom, clé de la description (``_exemplia_textes``), vue d'accueil de ces rôles, organisation de la vue, visuels)]
    # visuel : (forme, KPI, largeur, réglages, filtres du visuel, autres clés)
    "exemplia": [
        ("VUE1_NOM", "VUE1_DESC", ["admin", "lecteur", "auditeur"], None, [
            ("chiffre", ["NRJ-TOTAL-MWH"], 3, {}, {}, {}), ("chiffre", ["GES-S1"], 3, {}, {}, {}), ("chiffre", ["GES-S2-LB"], 3, {}, {}, {}),
            ("chiffre", ["SOC-EFFECTIF"], 3, {}, {}, {}), ("remplissage", [], 6, {}, {}, {}), ("organisations", ["NRJ-TOTAL-MWH"], 6, {}, {}, {}),
            ("tableau", ["NRJ-TOTAL-MWH", "GES-S1", "GES-S2-LB", "EAU-PRELEVEMENT", "DEC-TOTAL", "SOC-EFFECTIF"], 12, {}, {}, {})]),
        ("VUE2_NOM", "VUE2_DESC", [], None, [
            ("courbe", ["NRJ-ELEC", "NRJ-GAZ"], 6, {}, {}, {}), ("anneau", ["NRJ-TOTAL-MWH"], 6, {}, {}, {}),
            ("comparaison_n1", ["GES-S1"], 6, {}, {}, {}), ("barres_empilees", ["GES-S2-LB"], 6, {}, {}, {})]),
        ("VUE3_NOM", "VUE3_DESC", ["contributeur", "validateur"], None, [
            ("chiffre", ["SOC-EFFECTIF"], 3, {}, {}, {}), ("chiffre", ["NRJ-ELEC"], 3, {}, {}, {}), ("chiffre", ["DEC-TOTAL"], 3, {}, {}, {}),
            ("chiffre", ["EAU-PRELEVEMENT"], 3, {}, {}, {}), ("remplissage", [], 6, {}, {}, {}), ("organisations", ["NRJ-ELEC"], 6, {}, SITES, {}),
            ("courbe", ["DEC-TOTAL"], 12, {}, SITES, {"series": "organisations"})]),
    ],
}


def vues_demo(client, vues=None):
    """Vues partagées de démo, créées par l'admin de démo : « Comité de direction » (vue d'accueil des admins, lecteurs
    et auditeurs), « Énergie et climat », et « Mon périmètre » (vue d'accueil des contributeurs et des validateurs, des
    visuels que chacun voit dans son périmètre ; aucune organisation fixée désormais : fixée sur France, elle
    ne montrait rien à la contributrice de démo, qui n'y a aucun droit). Seuls les KPI présents sont repris. ``vues`` : celles d'un jeu d'essai
    (par défaut, celles de la démo ``client``)."""
    from collecte.models import AccueilVisu, VueVisu

    admin = Utilisateur.objects.filter(username="admin").first()
    existants = set(KPI.objects.values_list("code", flat=True))
    for rang, (nom, description, roles, org, visuels) in enumerate(VUES.get(client, []) if vues is None else vues):
        if vues is None:  # vues de la démo : textes de la langue courante
            nom, description = TX.texte(nom), TX.texte(description)
        liste = []
        for i, (forme, kpis, largeur, reglages, filtres, autres) in enumerate(visuels, start=1):
            kpis = [k for k in kpis if k in existants]
            if kpis or forme == "remplissage":
                liste.append({"id": f"demo{rang + 1}-{i}", "type": forme, "titre": "", "kpis": kpis, "source": "", "axe": "",
                              "series": "", "largeur": largeur, "hauteur": "m", "filtres": filtres, "options": reglages, **autres})
        o = Organisation.objects.filter(nom=org).first() if org else None
        vue, _ = VueVisu.objects.update_or_create(nom=nom, partage=True, defaults={
            "description": description, "proprietaire": admin, "ordre": rang, "visuels": liste,
            "filtres": {"org": o.pk} if o else {}})
        for role in roles:
            AccueilVisu.objects.update_or_create(role=role, defaults={"vue": vue})


def listes_demo():
    """Deux listes de KPI partagées par l'administrateur (Import / Export › Listes de KPI), pour montrer qu'on retrouve
    ses listes dans l'export et le fichier à remplir : les premiers KPI saisis de chacun des deux premiers thèmes."""
    from collecte.models import SelectionKPI
    from referentiel.models import Theme, Utilisateur

    admin = Utilisateur.objects.filter(username="admin").first()
    if admin is None:
        return
    for theme in Theme.objects.filter(parent=None).order_by("referentiel__ordre", "ordre")[:2]:
        kpis = list(KPI.objects.filter(elements__theme__in=[theme, *theme.enfants.all()], actif=True)
                    .order_by("ordre", "code").values_list("code", flat=True).distinct()[:8])
        if kpis:
            s, _ = SelectionKPI.objects.get_or_create(nom=TX.texte("ESSENTIELS", theme=theme.tr("nom", TX.langue())[:80]), proprietaire=admin,
                                                      defaults={"partage": True})
            s.kpis.set(kpis)
