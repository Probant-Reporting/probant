"""Balayage des droits, complément de ``test_droits_balayage`` (lot V6).

Ce que le premier balayage ne couvrait pas :
- le compte désactivé (dans l'espace ou au registre commun) : une session ouverte avant la désactivation ne donne plus
  accès à rien, par aucune adresse ni aucune méthode ;
- le contributeur et le validateur sur TOUTES les adresses qui leur sont ouvertes (pas seulement celles de
  l'administration) : identifiants d'une organisation hors de leur périmètre forgés dans l'adresse, la chaîne de
  requête, le formulaire et le corps JSON ; rien de cette organisation n'est montré (pages, JSON, fichiers Excel et CSV)
  et rien n'y est écrit ;
- la table des pages ouvertes par rôle (GET), figée pour le contributeur et le validateur comme elle l'est déjà pour le
  lecteur et l'auditeur."""
import io
import json
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from espaces.models import Compte
from referentiel.models import Attribution, Niveau, Organisation, Utilisateur

from . import saisie as S
from .models import Alerte, DemandeForcage, Preuve, Reponse
from .test_droits_balayage import Balayage, instantane, routes

MARQUE = "Quuxville"  # nom de l'organisation hors périmètre : ne doit apparaître dans aucune réponse
SECRET = "Confidentiel-Quux"  # commentaire de sa valeur
# pages hors de l'outil, ouvertes sans connexion : connexion (mot de passe et compte d'entreprise), langue, supervision…
SANS_CONNEXION = {"login", "logout", "langue", "sante", "logo", "confidentialite", "entreprise_debut", "entreprise_retour"}


def texte(rep):
    """Texte lisible d'une réponse : page, JSON, CSV, ou contenu XML d'un classeur Excel (zip)."""
    corps = b"".join(rep.streaming_content) if getattr(rep, "streaming", False) else rep.content
    if corps[:2] == b"PK":
        try:
            z = zipfile.ZipFile(io.BytesIO(corps))
            return " ".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml"))
        except zipfile.BadZipFile:
            return ""
    return corps.decode("utf-8", "replace")


class BalayagePerimetre(Balayage):
    def setUp(self):
        super().setUp()
        # comme en production : seul l'administrateur gère les espaces (désormais, espaces/comptes.py ne nomme
        # gestionnaire qu'un administrateur de l'espace principal ; remis ici explicitement, quel que soit le jeu d'essai)
        Compte.objects.update(gestionnaire=False)
        Compte.objects.filter(pk=self.admin.pk).update(gestionnaire=True)
        self.p2 = Organisation.objects.create(nom="Pays 2", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e3 = Organisation.objects.create(nom=MARQUE, niveau_id=Niveau.ENTITY, parent=self.p2)
        S.enregistrer(self.admin, self.c, self.eff, self.e3, "77", False, SECRET)
        S.ajouter_preuve(self.admin, self.c, self.eff, self.e3,
                         SimpleUploadedFile("quux.pdf", b"%PDF-1.4\n%quux\n", content_type="application/pdf"))
        self.preuve_e3 = Preuve.objects.get(reponse__organisation=self.e3)
        self.valeurs.update({"org_id": self.e3.pk, "pk": self.preuve_e3.pk})

    def etat_e3(self):
        """Tout ce qui porte sur l'organisation hors périmètre, et toutes les attributions."""
        return {
            "reponses": sorted(map(repr, Reponse.objects.filter(organisation=self.e3).values_list())),
            "preuves": sorted(map(repr, Preuve.objects.filter(reponse__organisation=self.e3).values_list())),
            "forcages": sorted(map(repr, DemandeForcage.objects.filter(organisation=self.e3).values_list())),
            "alertes": sorted(map(repr, Alerte.objects.filter(organisation=self.e3).values_list())),
            "attributions": sorted(map(repr, Attribution.objects.values_list())),
            "organisation": repr(Organisation.objects.filter(pk=self.e3.pk).values_list().first()),
        }


class CompteDesactiveTests(BalayagePerimetre):
    """Une session ouverte, puis le compte désactivé : plus rien n'est accessible. Désactivé au registre commun : renvoi à
    la connexion ; désactivé dans cet espace seulement : renvoi à la connexion ou page « pas d'accès » (403), le compte
    pouvant encore servir dans un autre espace."""

    def balayer(self, pas_d_acces=False):
        for ns, nom, motif in routes():
            if nom is None or nom in SANS_CONNEXION:
                continue
            url = self.url(motif)
            if (ns, nom) == ("serveur_mcp", "point"):  # jeton, jamais de session
                continue
            for methode in ("get", "post"):
                rep = getattr(self.client, methode)(url, {"action": "enregistrer", "valeur": "1"})
                if pas_d_acces and rep.status_code == 403:
                    self.assertNotIn(MARQUE, texte(rep))
                    continue
                self.assertEqual(rep.status_code, 302, f"{methode.upper()} {ns}:{nom}")
                self.assertTrue(rep["Location"].startswith(reverse("login")), f"{methode.upper()} {ns}:{nom} → {rep['Location']}")

    def test_desactive_dans_l_espace(self):
        for u in (self.admin, self.contrib):
            self.client.force_login(u)
            Utilisateur.objects.filter(pk=u.pk).update(is_active=False)
            avant = instantane()
            self.balayer(pas_d_acces=True)
            self.assertEqual(instantane(), avant)
            Utilisateur.objects.filter(pk=u.pk).update(is_active=True)

    def test_desactive_au_registre_commun(self):
        self.client.force_login(self.admin)
        Compte.objects.filter(pk=self.admin.pk).update(actif=False)
        avant = instantane()
        self.balayer()
        self.assertEqual(instantane(), avant)


class IdentifiantsForgesTests(BalayagePerimetre):
    """Contributeur et validateur : chaque adresse, en GET et en POST, avec les identifiants de l'organisation hors de
    leur périmètre dans l'adresse, la chaîne de requête, le formulaire et le corps JSON."""

    def requetes(self, ns, nom, motif):
        e3, c = self.e3.pk, self.c.pk
        url = self.url(motif)
        q = {"org": e3, "organisation": e3, "orgs": e3, "organisations": e3, "campagne": c, "kpi": "EFF", "periode": self.c.periode_id}
        yield "get", url, None, None
        yield "get", url, q, None
        champs = {**q, "valeur": "999", "commentaire": "forgé", "texte": "forgé", "justification": "forgé",
                  "cles": f"EFF|{e3}", "preuve": self.preuve_e3.pk, "nom": "Forgé", "utilisateur": self.contrib.pk}
        for action in ("enregistrer", "valider", "brouillon", "supprimer", "forcer", "retirer_preuve", "attribuer", "telecharger"):
            yield "post", url, {**champs, "action": action}, None
        corps = {"cles": [f"EFF|{e3}"], "org": e3, "organisation": e3, "organisations": [e3], "kpi": "EFF", "valeur": "999",
                 "campagne": c, "utilisateur": self.contrib.pk, "kpis": ["EFF"], "version": 1, "visuels": [
                     {"id": "a", "type": "chiffre", "kpis": ["EFF"], "orgs": [e3], "organisations": [e3]}]}
        yield "post", url, json.dumps(corps), "application/json"

    def balayer(self, u):
        self.client.force_login(u)
        admin_seulement = {f"{ns}:{nom}" for ns, nom, _ in AutresRoles.admin_seulement(self)}
        avant = self.etat_e3()
        for ns, nom, motif in routes():
            if nom is None or nom in SANS_CONNEXION or f"{ns}:{nom}" in admin_seulement or (ns, nom) == ("serveur_mcp", "point"):
                continue
            for methode, url, donnees, type_ in self.requetes(ns, nom, motif):
                quoi = f"{u.username} {methode.upper()} {ns}:{nom} {str(donnees)[:60] if donnees else ''}"
                if methode == "get":
                    rep = self.client.get(url, donnees or {})
                elif type_:
                    rep = self.client.post(url, donnees, content_type=type_)
                else:
                    rep = self.client.post(url, donnees)
                self.assertLess(rep.status_code, 500, quoi)
                corps = texte(rep)
                self.assertNotIn(MARQUE, corps, quoi)
                self.assertNotIn(SECRET, corps, quoi)
                self.assertNotIn(b"%quux", corps.encode(), quoi)
            self.client.force_login(u)  # une page qui déconnecte (aucune ne devrait) ne fausse pas la suite
        self.assertEqual(self.etat_e3(), avant, u.username)

    def test_contributeur(self):
        self.balayer(self.contrib)

    def test_validateur(self):
        self.balayer(self.validateur)


class PagesOuvertesParRoleTests(BalayagePerimetre):
    """Table des pages qui s'ouvrent (GET sans refus 403) pour le contributeur et le validateur : toute nouvelle page
    ouverte à l'un d'eux doit être ajoutée ici, après vérification de son périmètre (balayage ci-dessus)."""

    COMMUNES = {
        "accueil", "saisie", "choix_reponse", "choisir_campagne", "pour_moi", "forcages", "tableau_de_bord", "visu", "visu_theme",
        "visu_kpi", "visu_tableau_nouveau", "visu_tableau", "visu_tableau_modifier", "visu_vue", "visu_vue_nouvelle",
        "visu_catalogue", "visu_vue_donnees", "visu_donnees", "visu_vue_creer", "visu_vue_enregistrer", "visu_vue_dupliquer",
        "visu_vue_supprimer", "visu_vue_partage", "visu_vues_ordre", "visu_vue_preferee", "visu_vue_excel", "visu_excel",
        "consolidation", "consolidation_excel", "apercu_texte", "corbeille_restaurer", "echanges", "echanges_exporter",
        "echanges_resume", "echanges_listes_page", "export_officiel", "echanges_listes", "echanges_supprimer_reglage",
        "echanges_ordre_modeles", "echanges_restaurer_modeles", "echanges_importer", "echanges_rejets", "echanges_tache_etat",
        "echanges_tache_arreter", "echanges_modele", "echanges_export_etat", "echanges_export_fichier", "coherence",
        "alerte", "alerte_ia", "mon_compte", "aide", "aide_image", "aide_guide",
    }

    def ouvertes(self, u):
        self.client.force_login(u)
        sortie = set()
        for ns, nom, motif in routes():
            if nom is None or nom in SANS_CONNEXION or ns != "collecte":
                continue
            if self.client.get(self.url(motif)).status_code not in (403, 405):  # 405 : envoi (POST) seulement
                sortie.add(nom)
        return sortie

    def test_contributeur(self):
        # la preuve, la case et l'alerte d'une autre organisation sont refusées (403) : hors de la table
        self.assertEqual(self.ouvertes(self.contrib) - self.COMMUNES, set())

    def test_validateur(self):
        self.assertEqual(self.ouvertes(self.validateur) - self.COMMUNES, {"relances"})


class AutresRoles:
    """Liste des adresses réservées à l'administrateur, reprise de ``test_droits_balayage.AutresRolesBalayageTests``."""

    @staticmethod
    def admin_seulement(test):
        from .test_droits_balayage import AutresRolesBalayageTests

        return AutresRolesBalayageTests.admin_seulement(test)

