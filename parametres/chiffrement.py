"""Chiffrement d'un petit secret gardé en base (mot de passe du serveur d'envoi des e-mails, secrets de la copie externe)
avec le secret de l'installation (``SECRET_KEY``), sans dépendance nouvelle.

Construction : « chiffrer puis sceller ». Flux pseudo-aléatoire HMAC-SHA256 en mode compteur (nonce aléatoire de
16 octets, un bloc de 32 octets par compteur), combiné au texte par OU exclusif ; puis sceau HMAC-SHA256 sur la version,
le nonce et le texte chiffré. Les deux clés dérivent du secret de l'installation par deux sels différents
(``salted_hmac``). Le sceau est vérifié avant tout déchiffrement, en temps constant.

Usage : chaque texte chiffré est lié à son usage (``USAGES`` : le champ qui le garde). Le nom de l'usage entre dans le
sceau et dans le sel du flux : un secret recopié d'un champ à un autre ne se déchiffre pas (``Illisible``).

Lecture : avec ``SECRET_KEY``, puis chaque clé de ``SECRET_KEY_FALLBACKS`` (changement de secret préparé par l'IT). Sinon
(secret changé ou perdu, registre restauré sur un autre serveur, valeur abîmée) : ``Illisible``, jamais un texte faux.
"""
import base64
import binascii
import hmac
import secrets

from django.conf import settings
from django.utils.crypto import salted_hmac

VERSION = "v1"
SEL_FLUX = "probant.secret-chiffre.flux.v1"
SEL_SCEAU = "probant.secret-chiffre.sceau.v1"
TAILLE_NONCE, TAILLE_SCEAU = 16, 32
MOT_DE_PASSE_SMTP = "envoi_emails.mot_de_passe"
SECRET_COPIE = "copie_externe.secret"
CLE_PRIVEE_COPIE = "copie_externe.cle_privee"
USAGES = frozenset({MOT_DE_PASSE_SMTP, SECRET_COPIE, CLE_PRIVEE_COPIE})


class Illisible(ValueError):
    """Valeur chiffrée qui ne se lit pas avec le secret de cette installation."""


def _usage(usage):
    if usage not in USAGES:
        raise ValueError(f"unknown usage of an encrypted secret: {usage!r}")
    return usage


def _flux(nonce, n, secret, usage):
    blocs = (salted_hmac(f"{SEL_FLUX}:{usage}", nonce + i.to_bytes(4, "big"), secret=secret, algorithm="sha256").digest()
             for i in range((n + 31) // 32))
    return b"".join(blocs)[:n]


def _sceau(nonce, chiffre, secret, usage):
    lie = usage.encode("ascii")
    return salted_hmac(SEL_SCEAU, VERSION.encode("ascii") + len(lie).to_bytes(2, "big") + lie + nonce + chiffre,
                       secret=secret, algorithm="sha256").digest()


def _ou_exclusif(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def chiffrer(texte, usage, secret=None):
    """« v1$<base64> » : nonce, texte chiffré, sceau, pour ``usage`` (``USAGES``). Deux appels avec le même texte
    donnent deux valeurs différentes."""
    usage = _usage(usage)
    secret = secret or settings.SECRET_KEY
    clair = texte.encode("utf-8")
    nonce = secrets.token_bytes(TAILLE_NONCE)
    chiffre = _ou_exclusif(clair, _flux(nonce, len(clair), secret, usage))
    corps = base64.urlsafe_b64encode(nonce + chiffre + _sceau(nonce, chiffre, secret, usage)).decode("ascii")
    return f"{VERSION}${corps}"


def dechiffrer(valeur, usage):
    """Texte d'origine, ou ``Illisible`` (aussi pour un texte chiffré pour un autre usage)."""
    usage = _usage(usage)
    try:
        version, corps = str(valeur).split("$", 1)
        brut = base64.urlsafe_b64decode(corps.encode("ascii"))
    except (ValueError, binascii.Error, UnicodeError):
        raise Illisible from None
    if version != VERSION or len(brut) < TAILLE_NONCE + TAILLE_SCEAU:
        raise Illisible
    nonce, chiffre, sceau = brut[:TAILLE_NONCE], brut[TAILLE_NONCE:-TAILLE_SCEAU], brut[-TAILLE_SCEAU:]
    for secret in [settings.SECRET_KEY, *getattr(settings, "SECRET_KEY_FALLBACKS", [])]:
        if hmac.compare_digest(_sceau(nonce, chiffre, secret, usage), sceau):
            try:
                return _ou_exclusif(chiffre, _flux(nonce, len(chiffre), secret, usage)).decode("utf-8")
            except UnicodeDecodeError:
                raise Illisible from None
    raise Illisible
