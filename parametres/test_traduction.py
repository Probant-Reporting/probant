"""Traduction de tout le site (docs/translation.md) : fichiers de langue par zone (mêmes clés et mêmes paramètres en
français, anglais et espagnol), zones disjointes qui couvrent tous les gabarits, aucun texte français en dur dans les
zones déjà traduites, choix de la langue (barre du haut, Mon compte), e-mails dans la langue du destinataire."""
import json
import re
from pathlib import Path

from django.conf import settings
from django.template import Context, Template
from django.test import TestCase

from collecte.models import Campagne, Journal, Reponse
from parametres import langues as L
from parametres import controle_libelles as C
from parametres import libelles as LB
from parametres import zones_langue as Z
from parametres.models import Instance, Langue
from referentiel.models import Utilisateur

BASE = Path(settings.BASE_DIR)
DOSSIER = BASE / "libelles"
LANGUES = ("fr", "en", "es")
BALISES_PERMISES = {"strong", "b", "em", "code", "br"}
BALISE = re.compile(r"</?([a-zA-Z]+)[^>]*>")


def lire(zone, langue):
    return json.loads((DOSSIER / f"{zone}.{langue}.json").read_text(encoding="utf-8"))


def parametres(texte):
    textes = texte.values() if isinstance(texte, dict) else [texte]
    return {m for t in textes for m in LB.PARAMETRE.findall(t)}


def balises(texte):
    textes = texte.values() if isinstance(texte, dict) else [texte]
    return sorted(m for t in textes for m in BALISE.findall(t))


def gabarits():
    """Tous les gabarits et scripts de l'interface (chemins relatifs à la racine)."""
    motifs = ("templates/**/*.html", "*/templates/**/*.html", "*/templates/**/*.js", "static/js/*.js")
    return sorted({str(p.relative_to(BASE)) for m in motifs for p in BASE.glob(m)})


class FichiersDeLangueTests(TestCase):
    def test_un_fichier_par_zone_et_par_langue(self):
        for zone in Z.ZONES:
            for langue in LANGUES:
                with self.subTest(zone=zone, langue=langue):
                    self.assertTrue((DOSSIER / f"{zone}.{langue}.json").exists())
        for p in DOSSIER.glob("*.json"):
            zone, langue, _ = p.name.split(".")
            with self.subTest(fichier=p.name):
                self.assertIn(zone, Z.ZONES)
                self.assertRegex(langue, r"^[a-z]{2,3}(-[A-Z]{2})?$")

    def test_cles_de_la_zone_bien_formees(self):
        for p in DOSSIER.glob("*.json"):
            zone = p.name.split(".")[0]
            d = json.loads(p.read_text(encoding="utf-8"))
            with self.subTest(fichier=p.name):
                self.assertIsInstance(d, dict)
                for cle, texte in d.items():
                    self.assertRegex(cle, r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
                    self.assertTrue(cle.startswith(Z.prefixes(zone)), f"{cle} : préfixe hors de la zone {zone}")
                    self.assertTrue(isinstance(texte, str) or (isinstance(texte, dict) and set(texte) == {"one", "other"}), cle)
                    self.assertTrue(set(balises(texte)) <= BALISES_PERMISES, f"{cle} : balise non permise")
                    self.assertFalse(parametres(texte) & {"langue", "cle"}, f"{cle} : paramètre réservé (argument de libelle())")

    def test_memes_cles_et_memes_parametres(self):
        """Fichier vide : zone pas encore traduite dans cette langue (repli sur le français). Sinon : les mêmes clés que
        le fichier français, avec les mêmes paramètres, la même forme (pluriel ou non) et les mêmes balises."""
        for zone in Z.ZONES:
            fr = lire(zone, "fr")
            for langue in (c for c in C.langues_presentes() if c != "fr"):
                autre = C.lire(zone, langue)
                if not autre:
                    continue
                with self.subTest(zone=zone, langue=langue):
                    self.assertEqual(sorted(set(fr) - set(autre)), [], "clés manquantes")
                    self.assertEqual(sorted(set(autre) - set(fr)), [], "clés en trop")
                    for cle, texte in fr.items():
                        self.assertEqual(parametres(autre[cle]), parametres(texte), cle)
                        self.assertEqual(isinstance(autre[cle], dict), isinstance(texte, dict), cle)
                        self.assertEqual(balises(autre[cle]), balises(texte), cle)
                        self.assertTrue(autre[cle], f"{cle} : texte vide")

    def test_cadre_traduit_dans_les_trois_langues(self):
        self.assertEqual(set(lire("cadre", "en")), set(lire("cadre", "fr")))
        self.assertEqual(set(lire("cadre", "es")), set(lire("cadre", "fr")))
        self.assertEqual(L.langues_interface()[:1], ["en"])
        self.assertTrue({"fr", "en", "es"} <= set(L.langues_interface()))

    def test_listes_de_choix_des_modeles_toutes_traduites(self):
        """Chaque valeur d'un champ à choix (statuts, rôles…) a sa clé « choix.* », et le français reprend le modèle."""
        from django.apps import apps
        from django.db import models

        fr = lire("cadre", "fr")
        for m in apps.get_models():
            if m._meta.app_label not in ("referentiel", "collecte", "parametres"):
                continue
            for f in m._meta.get_fields():
                if isinstance(f, models.Field) and f.choices:
                    for valeur, texte in f.flatchoices:
                        cle = LB.cle_choix(m, f.name, valeur)
                        with self.subTest(cle=cle):
                            self.assertEqual(fr.get(cle), str(texte))


class ZonesTests(TestCase):
    def test_chaque_gabarit_dans_une_seule_zone(self):
        for g in gabarits():
            with self.subTest(gabarit=g):
                self.assertEqual(len(Z.zones_du_fichier(g)), 1, Z.zones_du_fichier(g))

    def test_motifs_existent_et_fichiers_python_dans_une_seule_zone(self):
        for zone, (_, _, motifs) in Z.ZONES.items():
            for m in motifs:
                with self.subTest(zone=zone, motif=m):
                    self.assertTrue(list(BASE.glob(m)), "aucun fichier")
        for p in BASE.glob("*/**/*.py"):
            r = str(p.relative_to(BASE))
            with self.subTest(fichier=r):
                self.assertLessEqual(len(Z.zones_du_fichier(r)), 1)

    def test_prefixes_disjoints(self):
        vus = {}
        for zone, (_, prefixes, _) in Z.ZONES.items():
            for p in prefixes:
                self.assertNotIn(p, vus, f"{p} : zones {vus.get(p)} et {zone}")
                vus[p] = zone
        self.assertTrue(set(Z.TRADUITES) <= set(Z.ZONES))


# ---------------------------------------------------------------- aucun texte français en dur
# mots permis tels quels (identiques dans toutes les langues)
PERMIS = {"KPI", "N/A", "GHG", "ID", "PDF", "JPG", "PNG", "CSV", "XLSX", "Excel", "SMTP", "HTTPS", "URL", "IA", "Power", "BI",
          "N-1", "P-1"}
ATTRIBUTS = r"title|alt|placeholder|aria-label|aria-description|aria-roledescription|aria-valuetext|label|data-confirmer|" \
            r"data-attente|data-toast|data-texte-lien|data-copier-annonce|data-titre"
LITTERAL = re.compile(r"""(?<![\w])(["'])((?:(?!\1).)*)\1""")


def _mots(texte):
    texte = re.sub(r"&[#\w]+;", " ", texte)
    return [m for m in re.findall(r"[^\W\d_][^\W\d_'’-]*", texte) if len(m) >= 2 and m not in PERMIS]


def _litteral_humain(texte):
    """Littéral d'une étiquette (« Exporter », "d/m/Y à H:i") plutôt qu'une clé, une adresse ou une classe."""
    if re.fullmatch(r"[a-z0-9_.:/#?=&%-]*", texte):
        return False
    return bool(_mots(texte)) and bool(re.search(r"[A-ZÀ-ÖØ-Þ]|[à-öø-ÿ]|\s", texte))


def textes_en_dur(source):
    """Textes affichés écrits en dur dans un gabarit (heuristique) : texte entre les balises, attributs lus (title,
    aria-label, placeholder…), littéraux d'étiquette dans {% %} et {{ }}. Une ligne qui contient « libelle-ok » est
    ignorée (texte technique, documenté)."""
    s = "\n".join(l for l in source.splitlines() if "libelle-ok" not in l)
    s = re.sub(r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}", " ", s, flags=re.S)
    s = re.sub(r"{#.*?#}", " ", s, flags=re.S)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    trouves = []
    for balise in re.findall(r"{%.*?%}|{{.*?}}", s, flags=re.S):
        nom = re.match(r"{%\s*(\w+)", balise)
        if nom and nom.group(1) in ("load", "extends", "url", "static", "block", "endblock", "if", "elif"):
            continue  # pas affichés : chemins, adresses, valeurs comparées
        litteraux = [m.group(2) for m in LITTERAL.finditer(balise)]
        if nom and nom.group(1) == "include" and litteraux:
            litteraux = litteraux[1:]  # le nom du gabarit
        trouves += [t for t in litteraux if _litteral_humain(t)]
    s = re.sub(r"{%.*?%}|{{.*?}}", " ", s, flags=re.S)
    for m in re.finditer(rf'\s(?:{ATTRIBUTS})\s*=\s*"([^"]*)"', s):
        if _mots(m.group(1)):
            trouves.append(m.group(1).strip())
    for morceau in re.sub(r"<[^>]*>", "\n", s).split("\n"):
        if _mots(morceau):
            trouves.append(morceau.strip())
    return trouves


def litteraux_js_en_dur(source):
    """Phrases en dur dans un script : littéral qui commence par une majuscule ou contient un accent, avec des espaces."""
    s = "\n".join(l for l in source.splitlines() if "libelle-ok" not in l and not l.strip().startswith("//"))
    sortie = []
    for m in re.finditer(r"""(["'`])((?:\\.|(?!\1).)*)\1""", s):
        t = m.group(2)
        if " " in t and len(_mots(t)) >= 2 and re.search(r"^[A-ZÀ-Ý]|[à-öø-ÿ]", t) and "${" not in t[:2]:
            sortie.append(t)
    return sortie


class AucunTexteEnDurTests(TestCase):
    def test_detecteur(self):
        self.assertEqual(textes_en_dur('<p>Bonjour</p><a title="Fermer">{% libelle "cadre.x" %}</a>'), ["Fermer", "Bonjour"])
        self.assertEqual(textes_en_dur('{% include "a.html" with titre="Exporter" %}{{ d|default:"Aucun élément" }}'),
                         ["Exporter", "Aucun élément"])
        self.assertEqual(textes_en_dur('{% if page == "saisie" %}<b>KPI</b> · N/A{% elif m == "Décompte" %}{% endif %}{# Texte #}'), [])
        self.assertEqual(textes_en_dur('<script>alert("Oui")</script><p class="x">{{ a }} – {{ b }}</p>'), [])
        self.assertEqual(litteraux_js_en_dur('toast("Valeur enregistrée.");\nq("form[data-x] [name=a]");'), ["Valeur enregistrée."])

    def test_zones_traduites_sans_texte_en_dur(self):
        for zone in Z.TRADUITES:
            for p in Z.fichiers_de(zone, BASE):
                if p.suffix not in (".html", ".js"):
                    continue
                source = p.read_text(encoding="utf-8")
                trouves = textes_en_dur(source) if p.suffix == ".html" else litteraux_js_en_dur(source)
                with self.subTest(zone=zone, fichier=str(p.relative_to(BASE))):
                    self.assertEqual(trouves, [])


# ---------------------------------------------------------------- choix de la langue
class ChoixLangueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.u = Utilisateur.objects.create_user("a@example.org", "a@example.org", "mdp-essai-2026", role="contributeur")
        cls.lecteur = Utilisateur.objects.create_user("l@example.org", "l@example.org", "mdp-essai-2026", role="lecteur")

    def test_visiteur_choisit_la_langue_de_la_page_de_connexion(self):
        r = self.client.get("/connexion/")
        self.assertContains(r, '<html lang="fr">')
        self.assertContains(r, "Se connecter")
        self.assertContains(r, 'name="langue" value="es" lang="es"')
        r = self.client.post("/langue/", {"langue": "en", "suivant": "/connexion/"})
        self.assertRedirects(r, "/connexion/", fetch_redirect_response=False)
        r = self.client.get("/connexion/")
        self.assertContains(r, '<html lang="en">')
        self.assertContains(r, ">Sign in</button>")
        self.client.post("/langue/", {"langue": "es", "suivant": "/connexion/"})
        self.assertContains(self.client.get("/connexion/"), "Contraseña")

    def test_choix_garde_dans_le_compte(self):
        self.client.force_login(self.u)
        self.client.post("/langue/", {"langue": "es", "suivant": "/pour-moi/"})
        self.u.refresh_from_db()
        self.assertEqual(self.u.langue, "es")
        self.assertTrue(Journal.objects.filter(action="reglage_compte", champ="langue", apres="es").exists())
        r = self.client.get("/mon-compte/")
        self.assertContains(r, '<html lang="es">')
        self.assertContains(r, "Cambiar mi contraseña")
        self.assertContains(r, "Colaborador")  # rôle traduit (choix.utilisateur.role)
        # nouvelle session : la langue du compte
        self.client.logout()
        self.client.force_login(self.u)
        self.assertContains(self.client.get("/mon-compte/"), '<html lang="es">')

    def test_mon_compte_regle_la_langue(self):
        self.client.force_login(self.u)
        r = self.client.post("/mon-compte/", {"action": "langue", "langue": "en"}, follow=True)
        self.assertContains(r, "Language saved.")
        self.assertContains(r, "Change my password")
        self.u.refresh_from_db()
        self.assertEqual(self.u.langue, "en")
        r = self.client.post("/mon-compte/", {"action": "langue", "langue": ""}, follow=True)
        self.assertContains(r, '<html lang="fr">')
        self.client.post("/mon-compte/", {"action": "langue", "langue": "xx"})
        self.u.refresh_from_db()
        self.assertEqual(self.u.langue, "")

    def test_messages_de_django_dans_la_langue(self):
        self.client.force_login(self.u)
        self.client.post("/langue/", {"langue": "en", "suivant": "/"})
        r = self.client.post("/mon-compte/", {"old_password": "faux", "new_password1": "a", "new_password2": "a"})
        self.assertContains(r, "The current password is incorrect.")  # message de l'outil, dans la langue 

    def test_lecteur_peut_changer_de_langue(self):
        self.client.force_login(self.lecteur)
        r = self.client.post("/langue/", {"langue": "en", "suivant": "/tableau-de-bord/"})
        self.assertEqual(r.status_code, 302)
        self.lecteur.refresh_from_db()
        self.assertEqual(self.lecteur.langue, "en")

    def test_code_inconnu_et_adresse_externe_ignores(self):
        r = self.client.post("/langue/", {"langue": "xx", "suivant": "https://example.com/piege"})
        self.assertEqual(r["Location"], "/")
        self.assertNotIn(L.CLE_SESSION, self.client.session)
        self.assertEqual(self.client.get("/langue/").status_code, 405)

    def test_contenus_suivent_si_la_langue_est_active(self):
        """La langue choisie règle aussi les contenus quand c'est une langue active des contenus ; sinon, repli."""
        Langue.objects.get_or_create(code="fr", defaults={"libelle": "Français"})
        Langue.objects.update_or_create(code="en", defaults={"libelle": "English", "active": True})
        self.client.force_login(self.u)
        self.client.post("/langue/", {"langue": "en", "suivant": "/"})
        captures = {}
        from django.test import RequestFactory

        rf = RequestFactory().get("/")
        rf.session = {L.CLE_SESSION: "en"}
        rf.user = self.u

        def vue(request):
            captures["contenus"], captures["interface"] = L.courante(), L.interface()
            from django.http import HttpResponse
            return HttpResponse("")

        L.LangueMiddleware(vue)(rf)
        self.assertEqual(captures, {"contenus": "en", "interface": "en"})
        rf.session = {L.CLE_SESSION: "es"}  # pas une langue des contenus : contenus dans la langue de l'installation
        L.LangueMiddleware(vue)(rf)
        self.assertEqual(captures, {"contenus": "fr", "interface": "es"})

    def test_langue_par_defaut_de_l_installation(self):
        i = Instance.courante()
        i.langue = "es"
        i.save()
        self.assertContains(self.client.get("/connexion/"), '<html lang="es">')
        i.langue = "ja"  # langue des contenus sans fichiers d'interface : anglais, la langue de base
        i.save()
        self.assertContains(self.client.get("/connexion/"), '<html lang="en">')


class OutilsTests(TestCase):
    def test_interface_de(self):
        self.assertEqual(L.interface_de("es"), "es")
        self.assertEqual(L.interface_de("en-GB"), "en")
        self.assertEqual(L.interface_de("ja"), "fr")
        self.assertEqual(L.interface_de(""), "fr")

    def test_pour_une_personne(self):
        u = Utilisateur(email="x@example.org", langue="en")
        with L.pour(u):
            self.assertEqual(LB.libelle("cadre.menu.saisie"), "Data entry")
        self.assertEqual(LB.libelle("cadre.menu.saisie"), "Saisie")
        with L.activer_interface("es"):
            self.assertEqual(LB.libelle("cadre.deconnexion"), "Cerrar sesión")

    def test_choix(self):
        c = Campagne(statut=Campagne.Statut.CLOTUREE)
        self.assertEqual(LB.choix(c, "statut"), "Clôturée")
        self.assertEqual(LB.choix(c, "statut", "en"), "Closed")
        self.assertEqual(LB.choix_valeur(Reponse, "statut", "brouillon", "es"), "Borrador")
        self.assertEqual(LB.choix_valeur(Reponse, "statut", "inconnu"), "inconnu")
        with L.activer_interface("en"):
            t = Template('{% load collecte %}{{ c|choix:"statut" }}|{{ "valide"|statut_libelle }}')
            self.assertEqual(t.render(Context({"c": c})), "Closed|Validated")

    def test_etiquettes(self):
        t = Template('{% load collecte %}{% libelle_html "cadre.connexion.aide" contact=c %}')
        self.assertIn("<strong>&lt;i&gt;x&lt;/i&gt;</strong>", t.render(Context({"c": "<i>x</i>"})))
        t = Template('{% load collecte %}{% libelle "cadre.connexion.trop_essais" contact=c %}')
        sortie = t.render(Context({"c": "O'Brien <x>"}))
        self.assertIn("Trop d'essais", sortie)  # apostrophe du fichier gardée (attributs entre guillemets doubles)
        self.assertIn("O&#x27;Brien &lt;x&gt;", sortie)  # paramètre échappé
        t = Template('{% load collecte %}{% libelle "cadre.deconnexion" as d %}[{{ d }}]{% libelles_js %}')
        sortie = t.render(Context())
        self.assertIn("[Se déconnecter]", sortie)
        self.assertIn('id="libelles-js"', sortie)
        self.assertIn('"commun.enregistrer": "Enregistrer"', sortie)

    def test_email_de_relance_dans_la_langue_du_destinataire(self):
        """Les relances se rédigent dans la langue de la personne (interface et contenus)."""
        from collecte import relances as RL

        vues = []
        u = Utilisateur(email="r@example.org", first_name="Ana", langue="es")

        class AF:
            personne = u
            campagnes = []
            nombre = a_saisir = brouillons = 0

        original = RL._rediger
        RL._rediger = lambda *a, **k: vues.append(L.interface()) or ("", "")
        try:
            RL.rediger(AF())
        finally:
            RL._rediger = original
        self.assertEqual(vues, ["es"])


class ZoneMessagesTests(TestCase):
    """Zone « messages » (Python seulement) : e-mails de relance, erreurs de validation, calculs, formules, droits."""

    def test_erreurs_de_validation_sans_texte_en_dur(self):
        ecrit = re.compile(r"""ValidationError\(\s*(?:\{[^}]*:\s*)?f?["']""")
        for p in Z.fichiers_de("messages", BASE):
            for i, ligne in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if "libelle-ok" not in ligne:
                    with self.subTest(fichier=p.name, ligne=i):
                        self.assertIsNone(ecrit.search(ligne), ligne.strip())

    def test_modele_de_relance_et_variables_dans_la_langue(self):
        from collecte import relances as R

        self.assertEqual(R.SUJET_DEFAUT, lire("messages", "fr")["messages.relances.sujet_defaut"])
        self.assertEqual([v for v, _ in R.VARIABLES], list(R.NOMS_VARIABLES))
        self.assertTrue(all(texte and not texte.startswith("messages.") for _, texte in R.VARIABLES))
        self.assertTrue(R.MESSAGE_DEFAUT.startswith("Bonjour {prenom},"))


class PastilleTypeSaisieTests(TestCase):
    """La pastille du type de saisie (« Saisie », « Calcul ») suit la langue : étiquette courte traduite en anglais pour
    une installation neuve (migration 0016) et par défaut (``creer_par_defaut``)."""

    def test_pastille_en_anglais(self):
        from collecte.templatetags.collecte import etiquette_type
        from parametres.models import TypeSaisie

        saisi, calcule = TypeSaisie.objects.get(code="Saisi"), TypeSaisie.objects.get(code="Calculé")
        self.assertIn(">Saisie</span>", etiquette_type(saisi))
        with L.activer("en"):
            self.assertIn('title="Input">Input</span>', etiquette_type(saisi))
            self.assertIn(">Calc.</span>", etiquette_type(calcule))

    def test_installation_existante_inchangee(self):
        """Une base qui a déjà des KPI garde ses étiquettes (comme 0015) ; une étiquette déjà réglée n'est jamais écrasée."""
        import importlib

        from django.apps import apps
        from parametres.models import TypeSaisie
        from referentiel.models import KPI, Niveau

        m = importlib.import_module("parametres.migrations.0016_types_saisie_abrege_en")
        TypeSaisie.objects.filter(code="Saisi").update(traductions={"en": {"libelle": "Input"}})
        TypeSaisie.objects.filter(code="Calculé").update(traductions={"en": {"abrege": "Comp."}})
        m.traduire(apps, None)
        self.assertEqual(TypeSaisie.objects.get(code="Calculé").traductions["en"]["abrege"], "Comp.")
        self.assertEqual(TypeSaisie.objects.get(code="Saisi").traductions["en"]["abrege"], "Input")
        TypeSaisie.objects.filter(code="Saisi").update(traductions={"en": {"libelle": "Input"}})
        KPI.objects.create(code="K1", libelle="K", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        m.traduire(apps, None)
        self.assertNotIn("abrege", TypeSaisie.objects.get(code="Saisi").traductions["en"])
