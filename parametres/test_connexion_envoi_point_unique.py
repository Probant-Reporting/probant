"""Un seul point de passage pour tous les envois d'e-mails (``parametres/envoi_emails.py``) : aucun autre module de
l'outil ne lit les réglages d'envoi de Django (``settings.EMAIL_*``, ``DEFAULT_FROM_EMAIL``), n'appelle ``send_mail``,
``mail_admins`` ni ``get_connection``, et chaque ``EmailMessage`` reçoit la connexion du point de passage."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

RACINE = Path(settings.BASE_DIR)
DOSSIERS = ["collecte", "parametres", "referentiel", "espaces", "serveur_mcp", "config"]
PERMIS = {"parametres/envoi_emails.py", "config/settings.py"}
REGLES = [
    (re.compile(r"settings\.(EMAIL_\w+|DEFAULT_FROM_EMAIL|SERVER_EMAIL)"), "réglage d'envoi lu hors du point de passage"),
    (re.compile(r"\b(send_mail|send_mass_mail|mail_admins|mail_managers|get_connection)\("), "envoi hors du point de passage"),
    (re.compile(r"\b(EmailMessage|EmailMultiAlternatives)\("), "EmailMessage sans la connexion du point de passage"),
]


def arguments(texte, debut):
    """Texte entre la parenthèse ouvrante qui finit ``texte[:debut]`` et sa parenthèse fermante (parenthèses imbriquées)."""
    niveau = 1
    for i in range(debut, len(texte)):
        niveau += {"(": 1, ")": -1}.get(texte[i], 0)
        if niveau == 0:
            return texte[debut:i]
    return texte[debut:]


def fautes_du_texte(texte):
    sortie = []
    for motif, explication in REGLES:
        for m in motif.finditer(texte):
            if m.group(0).startswith("Email") and "connection=" in arguments(texte, m.end()):
                continue
            if m.group(0).startswith("Email") and texte[max(0, m.start() - 7):m.start()].endswith("import "):
                continue
            sortie.append((texte.count("\n", 0, m.start()) + 1, explication, m.group(0)[:60]))
    return sortie


class PointUniqueTests(SimpleTestCase):
    def test_aucun_envoi_hors_du_point_de_passage(self):
        fautes = []
        for d in DOSSIERS:
            for f in sorted((RACINE / d).rglob("*.py")):
                rel = f.relative_to(RACINE).as_posix()
                if rel in PERMIS or "/migrations/" in rel or "/aides_tests/" in rel or f.name.startswith("test_"):
                    continue
                for ligne, explication, extrait in fautes_du_texte(f.read_text(encoding="utf-8")):
                    fautes.append(f"{rel}:{ligne} : {explication} ({extrait})")
        self.assertEqual(fautes, [])

    def test_les_regles_reconnaissent_les_fautes(self):
        for faute in ("x = settings.EMAIL_HOST", "settings.DEFAULT_FROM_EMAIL", "send_mail(a, b, None, [c])",
                      "EmailMessage(s, t, de, [a]).send()", "EmailMessage(libelle(x, y=z), t,\n de, [a]).send()", "get_connection()"):
            self.assertTrue(fautes_du_texte(faute), faute)
        for bon in ("EmailMessage(libelle(x, y=z), t, de,\n [a], connection=c).send()", "from django.core.mail import EmailMessage"):
            self.assertFalse(fautes_du_texte(bon), bon)
