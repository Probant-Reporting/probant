"""Paquet référentiel : constantes, ``PaquetInvalide`` et ``Paquet`` (contenu d'un paquet)."""
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from parametres import langues as L
from parametres import libelles as LB
from referentiel.models import Frequence, Referentiel

_t = LB.libelle  # textes de l'interface (libelles/referentiels.*.json) ; ``libelle`` sert déjà de nom de variable plus bas

FORMAT = "Fichier référentiel"
AUTO = "__auto__"  # niveau de saisie choisi par l'outil (règle automatique)
VERSION_FORMAT = 1
BIBLIOTHEQUE = Path(settings.BASE_DIR) / "referentiel" / "bibliotheque"
NUMERIQUES = ("nombre", "pourcentage")


class PaquetInvalide(Exception):
    pass


@dataclass
class Paquet:
    """Contenu d'un paquet. Les textes traduisibles sont des {langue: texte} ; les références (unité, types, niveau,
    thème) sont des codes du paquet, résolus dans l'installation à l'import."""

    referentiel: dict
    langue_reference: str = "fr"
    langues: list = field(default_factory=list)  # [{"code", "libelle"}]
    niveaux: list = field(default_factory=list)  # [{"code", "rang", "nom": {}, "nom_pluriel": {}}]
    unites: list = field(default_factory=list)  # [{"code", "symbole": {}, "libelle": {}, "entier", "decimales", "famille"}]
    types_saisie: list = field(default_factory=list)  # [{"code", "libelle": {}, "abrege": {}, "couleur", "comportement"}]
    types_reponse: list = field(default_factory=list)  # [{"code", "libelle": {}, "format", "valeurs": {langue: [...]}}]
    categories: list = field(default_factory=list)  # [{"code", "libelle": {}, "ordre", "affichee", "obligatoire"}]
    champs: list = field(default_factory=list)  # [{"code", "libelle": {}, "type", "valeurs": {langue: [...]}}]
    themes: list = field(default_factory=list)  # [{"code", "parent", "nom": {}, "ordre"}], parents d'abord
    kpis: list = field(default_factory=list)  # voir _kpi_vers_dict ; "element" : place dans le référentiel ou None
    regles: list = field(default_factory=list)  # [{"nom", "description", "gauche", "operateur", "droite", "tolerance", ...}]
    exporte_le: str = ""
    exporte_de: str = ""
    # Documents sur lesquels s'appuie un modèle de la bibliothèque (rubrique « Source documents ») : [{"titre", "editeur",
    # "version", "date", "url", "consulte_le", "licence"}]. Porté par le paquet seulement (rien en base) : un référentiel
    # installé les affiche par le paquet fourni de même identifiant. Vide pour un export ou un fichier importé.
    documents: list = field(default_factory=list)

    @property
    def code(self):
        return self.referentiel.get("code", "")

    def nom(self, langue=None):
        if langue is None:
            return self._texte_affiche("nom")
        return texte_dans_langue(self.referentiel.get("nom"), langue, self.langue_reference)

    def _texte_affiche(self, champ):
        """Nom ou description à l'écran : dans la langue de l'interface si le paquet l'a ; pour un modèle de la
        bibliothèque, sa traduction des fichiers de langue (``referentiels.socle.<code>.*``, l'espagnol par exemple) ;
        sinon la langue des contenus, puis la langue de référence du paquet."""
        textes = self.referentiel.get(champ) or {}
        interface = L.interface()
        if textes.get(interface):
            return textes[interface]
        if self.referentiel.get("origine") == "fourni":
            t = LB.table(interface).get(f"referentiels.socle.{self.code.lower()}.{champ}")
            if isinstance(t, str) and t:
                return t
        return texte_affiche(textes, self.langue_reference)

    def noms_connus(self):
        """{langue: nom} du référentiel : ceux du paquet, plus, pour un modèle de la bibliothèque, ses traductions des
        fichiers de langue (``referentiels.socle.<code>.nom``) dans les langues qui manquent au paquet."""
        noms = {lg: t for lg, t in (self.referentiel.get("nom") or {}).items() if t}
        if self.referentiel.get("origine") == "fourni":
            for lg in L.langues_interface():
                t = LB.table(lg).get(f"referentiels.socle.{self.code.lower()}.nom")
                if isinstance(t, str) and t:
                    noms.setdefault(lg, t)
        return noms

    @property
    def frequence_phrase(self):
        """Fréquence au milieu d'une phrase (la casse vient du libellé de la langue : ``choix.phrase.*``)."""
        try:
            return LB.choix_valeur_phrase(Referentiel, "frequence", Frequence(self.referentiel.get("frequence") or Frequence.ANNEE).value)
        except ValueError:
            return ""

    @property
    def frequence(self):
        try:
            return LB.choix_valeur(Referentiel, "frequence", Frequence(self.referentiel.get("frequence") or Frequence.ANNEE).value)
        except ValueError:
            return ""

    @property
    def description(self):
        return self._texte_affiche("description")

    @property
    def thematique(self):
        """Thématique d'un modèle de la bibliothèque (« Climat et énergie », « Social »…) : son rangement sur la page
        Référentiels. Vide pour un fichier qui n'en donne pas."""
        return self._texte_affiche("thematique")

    @property
    def documents_affiches(self):
        return documents_affiches(self.documents)

    @property
    def nb_elements(self):
        return sum(1 for k in self.kpis if k.get("element") is not None)

    @property
    def version(self):
        return self.referentiel.get("version") or "1.0"

    @property
    def date_version(self):
        """Date de la version (``referentiel.date_version``, AAAA-MM-JJ), ou None si le fichier n'en donne pas."""
        import datetime

        try:
            return datetime.date.fromisoformat(str(self.referentiel.get("date_version") or "").strip())
        except ValueError:
            return None


def texte_affiche(textes, repli):
    """Texte d'un {langue: texte} d'un paquet montré à l'écran : même repli que les contenus de l'installation (langue de
    l'interface, langue par défaut, langue de référence, autres langues actives : ``langues.langues_candidates``), puis
    l'anglais, puis la langue de référence du paquet. Partout où un écran lit le paquet directement (choix des KPI,
    aperçu, résumé d'installation, recherche de la bibliothèque)."""
    textes = textes or {}
    for lg in (*L.langues_candidates(None), "en", repli):
        if textes.get(lg):
            return textes[lg]
    return next((t for t in textes.values() if t), "")


def documents_affiches(documents):
    """Documents sources d'un modèle prêts à afficher : les mêmes dictionnaires, avec ``date_texte`` (jour en date courte
    de la langue, ou l'année seule quand le document n'écrit pas de date exacte) et ``consulte_texte`` (date courte)."""
    import datetime

    from collecte.dates_courtes import date_courte

    def jour(texte):
        try:
            return date_courte(datetime.date.fromisoformat(texte)) if len(texte) == 10 else texte
        except ValueError:
            return texte
    return [{**d, "date_texte": jour(str(d.get("date") or "")), "consulte_texte": jour(str(d.get("consulte_le") or ""))}
            for d in documents or []]


def texte_dans_langue(textes, langue, repli):
    """Texte d'un {langue: texte} dans la langue demandée, sinon dans la langue de repli, sinon le premier."""
    textes = textes or {}
    return textes.get(langue) or textes.get(repli) or next((t for t in textes.values() if t), "")
