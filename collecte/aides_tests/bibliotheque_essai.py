"""Bibliothèque d'essai : les modèles fournis avec l'outil (norme VS) et les quatre socles retirés de l'offre
(Énergie, Gaz à effet de serre, Social, ESRS simplifié ; ``referentiel/bibliotheque/socles_retires.py``).

Les socles retirés restent des jeux d'essai de la mécanique d'installation (KPI à cocher, sources ajoutées, niveaux
choisis, mise à jour, composition…) et l'état d'une installation qui les avait installés. Leurs paquets sont écrits une
fois par processus dans un dossier temporaire, avec une copie des paquets de la bibliothèque ; ``BibliothequeEssai``
(classe de test) ou ``avec_socles_retires()`` (bloc ``with``) font lire ce dossier à la place de
``referentiel/bibliotheque``. Hors de ces blocs, la bibliothèque est celle des installations : la norme VS seulement."""
import atexit
import contextlib
import shutil
import tempfile
from pathlib import Path
from unittest import mock

_DOSSIER = None


def paquet_retire(code):
    """Paquet d'un socle retiré, tel que la bibliothèque le fournissait (même identifiant, même version, même date)."""
    from referentiel.bibliotheque import socles as S
    from referentiel.bibliotheque.socles_retires import SOCLES_RETIRES

    return S.paquet(next(s for s in SOCLES_RETIRES if s["code"] == code))


def dossier():
    """Dossier de la bibliothèque d'essai (créé au premier appel, effacé à la fin du processus)."""
    global _DOSSIER
    if _DOSSIER is None:
        from collecte.paquets import modele, vers_json
        from referentiel.bibliotheque.socles_retires import SOCLES_RETIRES

        d = Path(tempfile.mkdtemp(prefix="bibliotheque_essai_"))
        atexit.register(shutil.rmtree, d, True)
        for chemin in modele.BIBLIOTHEQUE.glob("*.json"):
            shutil.copy(chemin, d / chemin.name)
        for s in SOCLES_RETIRES:
            (d / s["fichier"]).write_text(vers_json(paquet_retire(s["code"])) + "\n", encoding="utf-8")
        _DOSSIER = d
    return _DOSSIER


@contextlib.contextmanager
def avec_socles_retires():
    """La bibliothèque lue par l'outil (pages, installation, commande ``paquet --library``) devient la bibliothèque
    d'essai le temps du bloc."""
    d = dossier()
    with mock.patch("collecte.paquets.bibliotheque_json.BIBLIOTHEQUE", d), mock.patch("collecte.paquets.modele.BIBLIOTHEQUE", d), \
            mock.patch("collecte.paquets.BIBLIOTHEQUE", d):
        yield d


class BibliothequeEssai:
    """À placer avant TestCase : toute la classe (setUpTestData et setUp compris) lit la bibliothèque d'essai."""

    @classmethod
    def setUpClass(cls):
        pile = contextlib.ExitStack()
        pile.enter_context(avec_socles_retires())
        cls.addClassCleanup(pile.close)
        super().setUpClass()
