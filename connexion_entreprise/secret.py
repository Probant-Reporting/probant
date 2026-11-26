"""Secret du client (connexion d'entreprise) : chiffré avant d'être écrit en base, jamais réaffiché.

Chiffrement Fernet (bibliothèque ``cryptography`` : AES-128-CBC et HMAC-SHA256, horodaté) avec une clé tirée par HKDF
de la clé secrète de l'installation (``SECRET_KEY``). La base seule (copie, export PostgreSQL) ne donne pas le secret.
Clé secrète changée : les anciennes clés (``SECRET_KEY_FALLBACKS``) sont essayées ; sinon le secret est illisible
(``dechiffrer`` renvoie None) et l'écran demande de l'enregistrer de nouveau."""
import base64
import re

from django.conf import settings

MOTIF = re.compile(r"^[\x21-\x7e]{8,512}$")  # caractères visibles, sans espace


def _fernet(cle):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    brute = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"probant/connexion-entreprise",
                 info=b"secret-du-client").derive(str(cle).encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(brute))


def valide(texte):
    return bool(MOTIF.match(texte or ""))


def chiffrer(texte):
    return _fernet(settings.SECRET_KEY).encrypt(texte.encode("utf-8")).decode("ascii")


def dechiffrer(jeton):
    """Secret en clair, ou None (vide, ou chiffré avec une clé secrète que l'installation n'a plus)."""
    if not jeton:
        return None
    from cryptography.fernet import InvalidToken

    for cle in [settings.SECRET_KEY, *getattr(settings, "SECRET_KEY_FALLBACKS", [])]:
        try:
            return _fernet(cle).decrypt(jeton.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeError):
            continue
    return None
