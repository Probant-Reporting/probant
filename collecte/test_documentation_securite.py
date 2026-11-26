"""Documents pour l'IT et la sécurité d'un client (docs/it_request.md, docs/security_overview.md et leurs versions
françaises) : ils existent, le guide d'installation et le README public y renvoient, et les chiffres qu'ils donnent
sont ceux du code (blocage des connexions, durée des sessions, durées de conservation par défaut, politique de
sécurité des contenus, longueur minimale du mot de passe). Un réglage qui change sans le document fait échouer ce test."""
import re
from pathlib import Path

from django.conf import settings
from django.conf import global_settings
from django.contrib.auth.password_validation import MinimumLengthValidator
from django.test import SimpleTestCase

from collecte.politique_contenus import politique
from parametres.models import Instance
from referentiel import connexion as CX

RACINE = Path(settings.BASE_DIR)
EN, FR = "docs/security_overview.md", "docs/fr/dossier_securite.md"
DEMANDE_EN, DEMANDE_FR = "docs/it_request.md", "docs/fr/demande_it.md"


def lire(chemin):
    return (RACINE / chemin).read_text(encoding="utf-8")


def questions(texte):
    """Numéros des lignes du questionnaire (« | 12 | … »)."""
    return [int(n) for n in re.findall(r"^\| (\d+) \|", texte, re.M)]


class DocumentsSecuriteTests(SimpleTestCase):
    def test_liens_depuis_le_guide_et_le_readme_public(self):
        self.assertIn("(it_request.md)", lire("docs/installation.md"))
        self.assertIn("(security_overview.md)", lire("docs/installation.md"))
        self.assertIn("(demande_it.md)", lire("docs/fr/installation.md"))
        self.assertIn("(dossier_securite.md)", lire("docs/fr/installation.md"))
        if (RACINE / "publication/public/README.md").is_file():  # absent de l'arbre publié (copié à la racine)
            readme = lire("publication/public/README.md")
            self.assertIn("(docs/it_request.md)", readme)
            self.assertIn("(docs/security_overview.md)", readme)

    def test_questionnaire_complet_dans_les_deux_langues(self):
        en, fr = questions(lire(EN)), questions(lire(FR))
        self.assertEqual(en, list(range(1, len(en) + 1)))
        self.assertEqual(en, fr)
        self.assertTrue(25 <= len(en) <= 40, len(en))

    def test_blocage_des_connexions(self):
        minutes = CX.DUREE // 60
        en, fr = lire(EN), lire(FR)
        for attendu in (f"{CX.ESSAIS_MAX} failures for the same username", f"{CX.ESSAIS_MAX_ADRESSE} failures from the same",
                        f"{CX.ESSAIS_MAX_COMPTE} failures on the same account", f"for {minutes} minutes after one"):
            self.assertIn(attendu, en)
        for attendu in (f"{CX.ESSAIS_MAX} échecs pour un même identifiant", f"{CX.ESSAIS_MAX_ADRESSE} échecs depuis",
                        f"{CX.ESSAIS_MAX_COMPTE} échecs sur un même compte", f"pendant {minutes} minutes après"):
            self.assertIn(attendu, fr)

    def test_sessions_et_durees_de_conservation(self):
        heures = settings.SESSION_COOKIE_AGE // 3600
        historique = Instance._meta.get_field("connexions_jours").default
        corbeille = Instance._meta.get_field("corbeille_jours").default
        en, fr = lire(EN), lire(FR)
        self.assertIn(f"a session ends after {heures} hours", en)
        self.assertIn(f"une session se termine au bout de {heures} heures", fr)
        self.assertIn(f"{historique} days by default", en)
        self.assertIn(f"{historique} jours par défaut", fr)
        self.assertIn(f"{corbeille} days by default", en)
        self.assertIn(f"{corbeille} jours par défaut", fr)
        self.assertIn("14 backups by default", en)
        self.assertIn("14 sauvegardes par défaut", fr)
        self.assertIn("14 backups by default", lire(DEMANDE_EN))
        self.assertIn("14 sauvegardes par défaut", lire(DEMANDE_FR))
        self.assertEqual(settings.SAUVEGARDE_CONSERVER, 14)

    def test_mots_de_passe(self):
        self.assertEqual(global_settings.PASSWORD_HASHERS[0], "django.contrib.auth.hashers.PBKDF2PasswordHasher")
        longueur = MinimumLengthValidator().min_length
        self.assertIn("MinimumLengthValidator", str(settings.AUTH_PASSWORD_VALIDATORS))
        self.assertIn(f"at least {longueur} characters", lire(EN))
        self.assertIn(f"au moins {longueur} caractères", lire(FR))

    def test_en_tetes_du_navigateur(self):
        p = politique("x")
        for directive in ("frame-ancestors 'none'", "style-src-attr 'unsafe-inline'"):
            self.assertIn(directive, p)
            self.assertIn(directive, lire(EN))
            self.assertIn(directive, lire(FR))
        self.assertNotIn("unsafe-eval", p)
        self.assertEqual(settings.X_FRAME_OPTIONS, "DENY")
        self.assertEqual(settings.SECURE_REFERRER_POLICY, "same-origin")
        self.assertEqual(settings.SECURE_CROSS_ORIGIN_OPENER_POLICY, "same-origin")
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")

    def test_connexion_d_entreprise(self):
        """Ce que le dossier de sécurité dit de la connexion d'entreprise est ce que fait connexion_entreprise/ : refus
        répétés depuis une adresse, durée d'une demande en cours, taille et délai des appels au fournisseur, signatures
        asymétriques seulement ; et le questionnaire répond « oui, OpenID Connect » depuis que l'application existe."""
        from connexion_entreprise import flux, oidc, sortant

        en, fr = lire(EN), lire(FR)
        self.assertIn("connexion_entreprise", settings.INSTALLED_APPS)
        minutes = CX.DUREE // 60
        self.assertIn(f"After {flux.REFUS_MAX} refused company sign-ins in {minutes} minutes", en)
        self.assertIn(f"Après {flux.REFUS_MAX} connexions d'entreprise refusées en {minutes} minutes", fr)
        self.assertIn(f"a single-use `state` ({flux.DUREE_FLUX // 60} minutes)", en)
        self.assertIn(f"un `state` à usage unique ({flux.DUREE_FLUX // 60} minutes)", fr)
        self.assertEqual(sortant.TAILLE_MAX, 1024 * 1024)
        self.assertIn("JSON of 1 MB at most", en)
        self.assertIn("JSON de 1 Mo au plus", fr)
        delai = int(settings.CONNEXION_ENTREPRISE_DELAI)
        self.assertIn(f"{delai} seconds at most for each call (`COMPANY_SIGN_IN_TIMEOUT`)", en)
        self.assertIn(f"{delai} secondes au plus pour chaque appel (`COMPANY_SIGN_IN_TIMEOUT`)", fr)
        self.assertEqual({a[:2] for a in oidc.ALGORITHMES}, {"RS", "PS", "ES"})  # jamais HS (clé partagée) ni « none »
        self.assertIn("(RS, PS, and ES algorithms)", en)
        self.assertIn("(algorithmes RS, PS et ES)", fr)
        self.assertIn("| 12 | Single sign-on (SAML, OpenID Connect), LDAP, or Active Directory? | Yes, OpenID Connect", en)
        self.assertIn("| 12 | Authentification unique (SAML, OpenID Connect), LDAP ou Active Directory ? | Oui, OpenID Connect", fr)

    def test_mises_a_jour_automatiques(self):
        """Ce que les documents disent des mises à jour automatiques est ce que font le script de la machine
        (auto-update.sh, install.sh) et l'outil (parametres/mise_a_jour_auto.py) : attente par défaut, délais proposés,
        heure de la minuterie, hôtes joints par le serveur (jamais par le conteneur), identité de la signature."""
        from parametres import mise_a_jour_auto as MA

        script = lire("auto-update.sh")
        installeur = lire("install.sh")
        guide_en, guide_fr = lire("docs/installation.md"), lire("docs/fr/installation.md")
        self.assertEqual(MA.DELAI_DEFAUT, 3)
        self.assertIn(f"{MA.DELAI_DEFAUT} days after\n  its publication by default", lire(EN))
        self.assertIn(f"{MA.DELAI_DEFAUT} jours après sa publication par défaut", lire(FR))
        self.assertEqual(MA.DELAIS, (0, 1, 3, 7, 14))
        self.assertIn("0, 1, 3, 7 or 14 days (3 by default)", guide_en)
        self.assertIn("0, 1, 3, 7 ou 14 jours (3 par défaut)", guide_fr)
        self.assertIn("delay=0|delay=1|delay=3|delay=7|delay=14)", script)  # la même liste fermée côté machine
        self.assertIn('AUTO_TIME="04:00"', installeur)
        self.assertIn("RandomizedDelaySec=3600", installeur)
        self.assertIn("every night at about 04:00, time of the server, with a random\n  delay of up to 1 hour", guide_en)
        self.assertEqual(MA.SILENCE.days, 3)
        self.assertIn("has not run for 3 days", guide_en)
        self.assertIn("n'a pas tourné depuis 3 jours", guide_fr)
        hotes = ("github.com", "raw.githubusercontent.com", "ghcr.io", "pkg-containers.githubusercontent.com",
                 "tuf-repo-cdn.sigstore.dev")
        for hote in hotes:
            for texte in (lire(EN), lire(FR), lire(DEMANDE_EN), lire(DEMANDE_FR), guide_en, guide_fr):
                self.assertIn(f"`{hote}`", texte)
        self.assertIn('SOURCE="${PROBANT_TEST_SOURCE:-https://' + hotes[0] + '/Probant-Reporting/probant}"', script)
        self.assertIn('IMAGE_NAME="${PROBANT_TEST_IMAGE:-ghcr.io/probant-reporting/probant}"', script)
        self.assertRegex(script, r'COSIGN_IMAGE="ghcr\.io/sigstore/cosign/cosign:v[0-9.]+@sha256:[0-9a-f]{64}"')
        self.assertIn('ISSUER="https://token.actions.githubusercontent.com"', script)
        self.assertIn("/\\\\.github/workflows/image\\\\.yml@refs/tags/[vV]", script)
        for texte in (guide_en, guide_fr):
            self.assertIn("https://token.actions.githubusercontent.com", texte)
            self.assertIn("ghcr.io/sigstore/cosign/cosign", texte)
