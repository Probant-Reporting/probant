"""Paramètres de l'installation : identité (nom, logo, couleurs), langues des contenus, niveaux de l'arbre et référentiel
réglable (unités, types, catégories, champs). Une installation = un client."""
import os
import re
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from . import couleurs as CO
from .libelles import libelle
from .rangement import LOGO

CODE_LANGUE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")  # fr, en, es, pt-BR…
LOGO_TAILLE_MAX = 1024 * 1024
LOGO_SIGNATURES = {".png": (b"\x89PNG",), ".jpg": (b"\xff\xd8",), ".jpeg": (b"\xff\xd8",), ".webp": (b"RIFF",)}


def valider_logo(f):
    """PNG, JPG ou WebP, 1 Mo maximum ; le contenu doit correspondre à l'extension (pas de SVG : il peut contenir du script)."""
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in LOGO_SIGNATURES:
        raise ValidationError(libelle("messages.logo.formats"))
    if f.size > LOGO_TAILLE_MAX:
        raise ValidationError(libelle("messages.logo.trop_gros"))
    debut = f.read(12)
    f.seek(0)
    if not debut.startswith(LOGO_SIGNATURES[ext]) or (ext == ".webp" and debut[8:12] != b"WEBP"):
        raise ValidationError(libelle("messages.logo.invalide"))


def valider_couleur(v):
    if not CO.valide(v):
        raise ValidationError(libelle("messages.couleur.format"))


def valider_code_langue(v):
    if not CODE_LANGUE.match(v or ""):
        raise ValidationError(libelle("messages.langue.code"))


class Langue(models.Model):
    """Langue des contenus (noms des KPI, descriptions, libellés). L'interface reste en français (phase 9)."""

    code = models.CharField(max_length=10, primary_key=True, validators=[valider_code_langue])
    libelle = models.CharField("libellé", max_length=40, help_text="Nom de la langue dans cette langue, ex. « Español ».")
    ordre = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True, help_text="Proposée aux utilisateurs, dans les fiches KPI et les exports.")

    class Meta:
        verbose_name = "langue"
        ordering = ["ordre", "code"]

    def __str__(self):
        return self.libelle


class Traduisible(models.Model):
    """Élément dont certains textes se traduisent. Le champ lui-même porte le texte dans la langue de référence de
    l'installation ; ``traductions`` porte les autres langues : {"en": {"libelle": "…"}, "es": {…}}. Les valeurs d'une liste
    de choix restent stockées telles quelles (clés des réponses) ; leurs traductions sont rangées par position."""

    TRADUITS = ()  # (champ, libellé) des textes traduisibles

    traductions = models.JSONField(default=dict, blank=True, help_text="{langue: {champ: texte}}, hors langue de référence")

    class Meta:
        abstract = True

    def tr(self, champ, langue=None):
        """Texte dans la langue demandée (par défaut, celle de l'utilisateur), avec repli."""
        from . import langues

        return langues.traduire(self, champ, langue)


def gamme_fixe_de(palette, couleurs):
    """Gamme fixée d'une palette enregistrée, si les 4 couleurs sont encore les siennes."""
    p = PaletteEnregistree.depuis_code(palette) if palette and palette.startswith("p") else None
    return p.gamme if p and p.gamme and tuple(c.upper() for c in p.couleurs) == couleurs else None


def _sauvegarde_heure_defaut():  # valeurs de départ : variables de l'IT (SAUVEGARDE_HEURE, SAUVEGARDE_CONSERVER)
    return settings.SAUVEGARDE_HEURE


def _sauvegarde_conserver_defaut():
    return settings.SAUVEGARDE_CONSERVER

def langue_par_defaut():
    """Langue par défaut d'une nouvelle installation : ``DEFAULT_LANGUAGE`` (anglais si absent, français pour les tests)."""
    from django.conf import settings

    return settings.LANGUE_PAR_DEFAUT


class Instance(models.Model):
    """La structure qui utilise l'outil. Une seule ligne (clé 1), créée à la première lecture."""

    nom = models.CharField("nom de la structure", max_length=100, default="Ma structure")
    titre = models.CharField("nom de l'outil", max_length=60, default="Probant",
                             help_text="Affiché en haut à gauche et dans l'onglet du navigateur.")
    sous_titre = models.CharField("sous-titre", max_length=100, blank=True, help_text="Sous le nom de l'outil (facultatif).")
    sigle = models.CharField("sigle", max_length=4, default="KPI", help_text="Lettres du pastille-logo quand aucun logo n'est déposé.")
    logo = models.FileField(upload_to=LOGO + "/", blank=True, validators=[valider_logo])  # fichiers/reglages/logo/
    contact = models.CharField("contact en cas de problème de connexion", max_length=100, default="l'administrateur de l'outil",
                               help_text="Affiché sur la page de connexion : « contactez … ».")
    palette = models.CharField(max_length=20, default=CO.PALETTE_PAR_DEFAUT, help_text="Palette de départ ; « perso » si modifiée.")
    couleur_principale = models.CharField("couleur principale", max_length=7, validators=[valider_couleur],
                                          default=CO.PALETTES[CO.PALETTE_PAR_DEFAUT]["principale"])
    couleur_accent = models.CharField("couleur d'accent", max_length=7, validators=[valider_couleur],
                                      default=CO.PALETTES[CO.PALETTE_PAR_DEFAUT]["accent"])
    couleur_fond = models.CharField("couleur de fond", max_length=7, validators=[valider_couleur],
                                    default=CO.PALETTES[CO.PALETTE_PAR_DEFAUT]["fond"])
    couleur_texte = models.CharField("couleur du texte", max_length=7, validators=[valider_couleur],
                                     default=CO.PALETTES[CO.PALETTE_PAR_DEFAUT]["texte"])
    langue = models.CharField("langue par défaut", max_length=10, default=langue_par_defaut,
                              help_text="Langue des contenus pour qui n'a pas choisi la sienne, et langue de repli.")
    langue_reference = models.CharField("langue de référence", max_length=10, default="fr",
                                        help_text="Langue des textes de référence (libellés saisis sans précision de langue).")
    mise_en_place_etape = models.PositiveSmallIntegerField("étape de la mise en place", default=0,
                                                           help_text="Assistant de premier lancement : étape en cours (0 = pas commencé).")
    mise_en_place_terminee = models.BooleanField("mise en place terminée", default=False)
    # relances par e-mail (collecte/relances.py) : modèle du message (vide = texte fourni) et relances automatiques
    relance_sujet = models.CharField("objet de la relance", max_length=200, blank=True)
    relance_message = models.TextField("message de la relance", blank=True)
    # même modèle dans les autres langues de l'interface : {"en": {"sujet", "message"}, "es": …} ;
    # un texte vide prend le texte français ci-dessus, puis le texte fourni dans la langue de la personne
    relance_traductions = models.JSONField("modèle de la relance dans les autres langues", default=dict, blank=True)
    relance_auto = models.BooleanField("relances automatiques", default=False,
                                       help_text="Chaque jour d'échéance, toutes les personnes qui ont encore quelque chose à saisir.")
    relance_jours = models.CharField("jours avant la fin de saisie", max_length=40, default="7,2",
                                     help_text="Ex. « 7,2 » : relance 7 jours puis 2 jours avant la fin de la saisie.")
    # jour réservé par le dernier envoi des relances automatiques (mise à jour conditionnelle, collecte/relances.py) :
    # deux planificateurs lancés en même temps (redéploiement, deux instances) n'envoient qu'une fois
    derniere_relance_auto = models.DateField("dernier jour de relances automatiques", null=True, blank=True, editable=False)
    class FrequenceSauvegarde(models.TextChoices):
        H6 = "6h", "Toutes les 6 heures"
        H12 = "12h", "Toutes les 12 heures"
        JOUR = "jour", "Chaque jour"
        SEMAINE = "semaine", "Chaque semaine"

    sauvegarde_auto = models.BooleanField("sauvegarde automatique", default=True)
    sauvegarde_frequence = models.CharField("fréquence", max_length=8, choices=FrequenceSauvegarde.choices,
                                            default=FrequenceSauvegarde.JOUR)
    sauvegarde_heure = models.CharField("heure de départ", max_length=5, default=_sauvegarde_heure_defaut,
                                        help_text="HH:MM : heure de la sauvegarde quotidienne, ou de la première de la journée.")
    sauvegarde_conserver = models.PositiveSmallIntegerField("sauvegardes gardées", default=_sauvegarde_conserver_defaut,
                                                           help_text="Au-delà, les plus anciennes sont supprimées.")
    # corbeille (collecte/corbeille.py) : exports, listes de KPI et vues supprimés restent restaurables ce nombre de
    # jours, puis sont effacés pour de bon (Paramètres › Hébergement)
    corbeille_jours = models.PositiveSmallIntegerField(
        "jours dans la corbeille", default=30, validators=[MinValueValidator(1), MaxValueValidator(365)],
        help_text="Un export, une liste de KPI ou une vue supprimés restent restaurables ce nombre de jours, puis sont effacés.")
    # historique des connexions (referentiel.HistoriqueConnexion, Paramètres › Hébergement) : une connexion reste dans
    # l'historique ce nombre de jours, puis le ménage de la nuit l'efface (données personnelles : durée à régler)
    connexions_jours = models.PositiveSmallIntegerField(
        "jours de l'historique des connexions", default=180, validators=[MinValueValidator(1), MaxValueValidator(730)],
        help_text="Une connexion reste dans l'historique ce nombre de jours, puis elle est effacée.")
    # conservation des preuves des KPI sensibles (collecte/conservation.py, Paramètres › Hébergement) : nombre de mois après
    # la fin de la période, une fois la campagne clôturée, au-delà duquel une preuve est proposée à la suppression
    # (Administration › Preuves à supprimer). Vide : pas de durée, rien n'est jamais proposé. Rien n'est supprimé seul.
    preuves_sensibles_mois = models.PositiveSmallIntegerField(
        "durée de conservation des preuves des KPI sensibles (mois)", null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(240)],
        help_text="Vide : pas de durée, aucune preuve n'est proposée à la suppression.")
    # gros exports fabriqués en arrière-plan (collecte/exports_arriere_plan.py, Paramètres › Hébergement) : au-delà de ce
    # nombre de cellules estimé (lignes × colonnes), l'export ou le fichier à remplir est fabriqué en tâche de fond et
    # retrouvé dans Import / Export › Mes exports, gardé ``exports_fond_jours`` jours. 0 : jamais en arrière-plan.
    exports_fond_cellules = models.PositiveIntegerField(
        "gros export : cellules au-delà desquelles il est fabriqué en arrière-plan", default=100_000,
        validators=[MaxValueValidator(100_000_000)],
        help_text="Lignes × colonnes, estimé avant de fabriquer le fichier ; 0 : jamais en arrière-plan.")
    exports_fond_jours = models.PositiveSmallIntegerField(
        "gros export : jours de conservation du fichier", default=7, validators=[MinValueValidator(1), MaxValueValidator(30)],
        help_text="Le fichier fabriqué en arrière-plan reste téléchargeable ce nombre de jours, puis il est effacé.")
    # rôles qui peuvent répondre « Non applicable (N/A) » (Paramètres › Seuils de suivi) ;
    # l'administrateur le peut toujours. Codes de rôle séparés par des virgules.
    na_roles = models.CharField("rôles qui peuvent répondre N/A", max_length=60, default="admin,validateur,contributeur",
                                help_text="Codes de rôle séparés par des virgules ; l'administrateur peut toujours répondre N/A.")
    # seuils de suivi (Paramètres › Seuils de suivi) : retard au tableau de bord et contrôles de cohérence
    tolerance_retard = models.PositiveSmallIntegerField(
        "écart toléré avant de signaler un retard", default=10, validators=[MinValueValidator(0), MaxValueValidator(50)],
        help_text="En points de taux : une organisation est en retard quand le taux de ses propres KPI est plus bas que "
                  "le rythme attendu moins cet écart.")
    historique_annees = models.PositiveSmallIntegerField(
        "années comparées", default=5, validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Contrôle « hors historique » : nombre d'années précédentes, à la même période, prises en compte.")
    historique_minimum = models.PositiveSmallIntegerField(
        "valeurs passées nécessaires", default=3, validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Le contrôle « hors historique » ne se fait qu'avec au moins ce nombre de valeurs passées.")
    tolerance_fe = models.DecimalField(
        "écart toléré sur un paramètre hérité", max_digits=6, decimal_places=4, default=Decimal("0.01"),
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="Fraction (0,01 = 1 %) : au-delà, alerte « paramètre hérité modifié » (facteur d'émission…).")
    tolerance_detail = models.DecimalField(
        "écart toléré avec le détail", max_digits=6, decimal_places=4, default=Decimal("0.005"),
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="Fraction (0,005 = 0,5 %) : arrondis tolérés entre une valeur saisie au-dessus et la somme du détail.")
    # Visualisation (Paramètres › Identité et Paramètres › Visualisation)
    couleurs_graphiques = models.JSONField(
        "couleurs des graphiques", default=dict, blank=True,
        help_text="{\"series\": 8 couleurs, \"autres\": couleur} ; vide : la palette fournie (couleurs.VIZ).")
    vues_personnelles_max = models.PositiveSmallIntegerField(
        "vues personnelles par personne", default=10, validators=[MinValueValidator(1), MaxValueValidator(500)],
        help_text="Au-delà, une personne ne peut plus créer ni dupliquer de vue (elle garde celles qu'elle a).")
    # page « Données et confidentialité » : texte de l'entreprise (responsable du traitement, DPO…), en Markdown, ajouté
    # sous ce que l'outil garde (collecte/confidentialite.py) ; vide : rien n'est ajouté
    texte_confidentialite = models.TextField(
        "texte de l'entreprise sur les données personnelles", blank=True,
        help_text="Markdown ; affiché sur la page « Données et confidentialité » (responsable du traitement, DPO…).")
    # prise IA (Paramètres › Assistant IA, docs/ai_socket.md) : éteinte par défaut, chaque usage aussi ; la clé n'est
    # jamais en base (fichier du dossier des données, parametres/ia.py)
    ia_active = models.BooleanField("assistant IA allumé", default=False)
    ia_fournisseur = models.CharField("fournisseur", max_length=20, default="claude")
    ia_modele = models.CharField("modèle", max_length=60, default="claude-fable-5-2")
    ia_appels_jour = models.PositiveIntegerField(
        "appels par jour", default=50, validators=[MinValueValidator(1), MaxValueValidator(5000)],
        help_text="Au-delà, les demandes sont refusées jusqu'au lendemain (un appel en échec compte).")
    ia_taille_max = models.PositiveIntegerField(
        "caractères envoyés au plus par appel", default=60000, validators=[MinValueValidator(2000), MaxValueValidator(400000)])
    ia_delai = models.PositiveSmallIntegerField(
        "délai d'attente (secondes)", default=60, validators=[MinValueValidator(10), MaxValueValidator(110)])
    ia_expliquer_alertes = models.BooleanField("expliquer une alerte de cohérence", default=False)
    ia_reprise = models.BooleanField("proposer les correspondances d'une reprise", default=False)
    ia_traductions = models.BooleanField("proposer des traductions", default=False)
    # KPI « Restreint » ou « Confidentiel » et KPI calculés qui en dérivent (collecte/sensibles.py) : éteint, rien d'eux ne
    # part par aucun usage (règle du projet ; à l'inverse des assistants MCP, éteint par défaut)
    ia_kpi_sensibles = models.BooleanField("KPI sensibles envoyés à l'assistant IA", default=False)
    # monnaie des montants des modèles de la bibliothèque installés ou mis à jour (parametres/monnaies.py) ; l'euro par
    # défaut : aucune installation existante ne change. Aucune conversion de valeur.
    monnaie = models.CharField("monnaie de référence", max_length=3, default="EUR",
                               help_text="Code ISO 4217 d'une monnaie de la liste de parametres/monnaies.py.")
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "paramètres de l'installation"
        verbose_name_plural = "paramètres de l'installation"

    def __str__(self):
        return self.nom

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def courante(cls):
        return cls.objects.get_or_create(pk=1)[0]

    def peut_repondre_na(self, utilisateur):
        """Vrai si cette personne peut répondre « N/A » : l'administrateur toujours, les autres selon ``na_roles``."""
        return bool(utilisateur.est_admin or utilisateur.role in {r.strip() for r in (self.na_roles or "").split(",")})

    @property
    def logo_disponible(self):
        """Logo déposé dont le fichier existe encore (une base restaurée sans ses fichiers garde le nom du logo) :
        sinon la pastille du sigle, plutôt qu'une image cassée."""
        try:
            return bool(self.logo) and self.logo.storage.exists(self.logo.name)
        except OSError:
            return False

    def gamme(self):
        couleurs = (self.couleur_principale.upper(), self.couleur_accent.upper(), self.couleur_fond.upper(), self.couleur_texte.upper())
        return CO.gamme(*couleurs, self.palette, gamme_fixe_de(self.palette, couleurs))

    def css(self):
        return CO.css(self.gamme())

    def palette_graphiques(self):
        """(8 couleurs des séries, couleur « Autres », réglée par l'admin) : la palette réglée, sinon celle fournie."""
        return CO.palette_graphiques(self.couleurs_graphiques)


class PaletteEnregistree(models.Model):
    """Palette propre à l'installation (Paramètres › Identité › « Enregistrer cette palette »). ``gamme`` : toutes les
    variables fixées à l'identique (charte d'une marque) ; vide : dérivées des 4 couleurs comme les palettes fournies."""

    nom = models.CharField(max_length=40)
    principale = models.CharField(max_length=7, validators=[valider_couleur])
    accent = models.CharField(max_length=7, validators=[valider_couleur])
    fond = models.CharField(max_length=7, validators=[valider_couleur])
    texte = models.CharField(max_length=7, validators=[valider_couleur])
    gamme = models.JSONField(default=dict, blank=True)
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nom"]
        verbose_name = "palette enregistrée"

    def __str__(self):
        return self.nom

    @property
    def code(self):
        return f"p{self.pk}"

    @property
    def couleurs(self):
        return (self.principale, self.accent, self.fond, self.texte)

    @classmethod
    def depuis_code(cls, code):
        if code and code.startswith("p") and code[1:].isdecimal():
            return cls.objects.filter(pk=int(code[1:])).first()
        return None


class NiveauHierarchique(Traduisible):
    """Un niveau de l'arbre des organisations (Groupe, Pays, Filiale, Site…). Rang 1 = sommet ; 1 à 8 niveaux.

    Le code, fixé à la création, sert de clé : renommer un niveau ne change rien aux données.
    """

    TRADUITS = (("nom", "Nom"), ("nom_pluriel", "Nom au pluriel"))

    MAXIMUM = 8

    code = models.CharField(max_length=20, primary_key=True)
    rang = models.PositiveSmallIntegerField(help_text="1 = sommet de l'arbre")
    nom = models.CharField(max_length=60)
    nom_pluriel = models.CharField("nom au pluriel", max_length=60)
    couleur = models.CharField(max_length=7, validators=[valider_couleur], help_text="Couleur du niveau (pastilles, traits de l'arbre)")
    couleur_fond = models.CharField("fond des étiquettes", max_length=7, validators=[valider_couleur])
    couleur_texte = models.CharField("texte des étiquettes", max_length=7, validators=[valider_couleur])
    couleur_pale = models.CharField("fond des cartes", max_length=7, validators=[valider_couleur])

    class Meta:
        verbose_name = "niveau de l'organisation"
        verbose_name_plural = "niveaux de l'organisation"
        ordering = ["rang"]

    def __str__(self):
        return self.tr("nom")

    def deriver_couleurs(self):
        """Fond, texte et teinte pâle déduits de la couleur du niveau (texte lisible sur le fond : WCAG AA)."""
        self.couleur_fond, self.couleur_texte, self.couleur_pale = CO.couleurs_niveau(self.couleur)


# ---------------------------------------------------------------- référentiel réglable (fiche KPI)
class Unite(Traduisible):
    """Unité d'un KPI (kWh, tCO2eq, salariés…). Le code, fixé à la création, sert de clé dans les fichiers."""

    TRADUITS = (("symbole", "Symbole"), ("libelle", "Libellé"))
    FACULTATIFS = ("symbole",)  # souvent identique dans toutes les langues (kWh, t) : pas compté « à traduire »

    code = models.CharField(max_length=60, primary_key=True)
    symbole = models.CharField(max_length=60, help_text="Affiché à côté des valeurs, ex. « kWh ».")
    libelle = models.CharField("libellé", max_length=100, blank=True, help_text="Nom en toutes lettres, ex. « kilowattheure ».")
    entier = models.BooleanField("nombre entier", default=False, help_text="Comptage : une valeur décimale est signalée.")
    decimales = models.PositiveSmallIntegerField("décimales par défaut", default=2)
    famille = models.CharField(max_length=40, blank=True, help_text="Pour regrouper les unités : énergie, masse, émissions…")
    ordre = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "unité"
        ordering = ["ordre", "symbole"]

    def __str__(self):
        return self.tr("symbole")


class TypeSaisie(Traduisible):
    """Comment la valeur d'un KPI est obtenue. Le comportement règle le moteur de calcul ; le reste est libre."""

    TRADUITS = (("libelle", "Libellé"), ("abrege", "Étiquette"))

    class Comportement(models.TextChoices):
        SAISIE = "saisie", "Saisie"
        CALCUL = "calcul", "Calcul par formule"
        HERITE = "herite", "Paramètre hérité"

    AIDES = {
        Comportement.SAISIE: "Un contributeur saisit la valeur ; elle peut s'additionner aux niveaux supérieurs.",
        Comportement.CALCUL: "Obtenu par une formule à partir d'autres KPI ; jamais saisi.",
        Comportement.HERITE: "Saisi une fois en haut, puis repris tel quel par les organisations en dessous.",
    }

    code = models.CharField(max_length=20, primary_key=True)
    libelle = models.CharField("libellé", max_length=60)
    abrege = models.CharField("étiquette courte", max_length=20, help_text="Affichée dans les listes, ex. « FE ».")
    couleur = models.CharField(max_length=7, validators=[valider_couleur])
    couleur_fond = models.CharField("fond de l'étiquette", max_length=7, validators=[valider_couleur])
    couleur_texte = models.CharField("texte de l'étiquette", max_length=7, validators=[valider_couleur])
    comportement = models.CharField(max_length=10, choices=Comportement.choices, default=Comportement.SAISIE)
    ordre = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "type de saisie"
        verbose_name_plural = "types de saisie"
        ordering = ["ordre", "code"]

    def __str__(self):
        return self.tr("libelle")

    @property
    def aide(self):
        """Explication du comportement, dans la langue de l'interface (AIDES : texte français de référence)."""
        from .libelles import libelle

        return libelle(f"messages.type_saisie.aide.{self.comportement}") if self.comportement in self.AIDES else ""

    def deriver_couleurs(self):
        self.couleur_fond, self.couleur_texte, _ = CO.couleurs_niveau(self.couleur)


class TypeReponse(Traduisible):
    """Forme de la réponse : nombre, pourcentage, oui / non, liste de choix, texte rédigé (Markdown) ou tableau (lignes de longueur variable). Entier, monnaie… : portés par l'unité."""

    TRADUITS = (("libelle", "Libellé"),)

    class Format(models.TextChoices):
        NOMBRE = "nombre", "Nombre"
        POURCENTAGE = "pourcentage", "Pourcentage"
        OUI_NON = "oui_non", "Oui / non"
        LISTE = "liste", "Liste de choix"
        TEXTE = "texte", "Texte rédigé"
        TABLEAU = "tableau", "Tableau"

    NUMERIQUES = {Format.NOMBRE, Format.POURCENTAGE}
    ANCIENS = {"entier": "nombre", "montant": "nombre"}  # anciens formats (fichiers, paquets) : l'unité les porte
    OUI, NON = "Oui", "Non"

    code = models.CharField(max_length=20, primary_key=True)
    libelle = models.CharField("libellé", max_length=60)
    format = models.CharField(max_length=12, choices=Format.choices, default=Format.NOMBRE)
    valeurs = models.JSONField("valeurs possibles", default=list, blank=True, help_text="Liste de choix : une valeur par ligne.")
    colonnes = models.JSONField("colonnes", default=list, blank=True,
                                help_text="Tableau : colonnes [{code, libelle: {langue: texte}, type: nombre / texte / liste, "
                                          "liste: code d'un type liste, unite}] (voir collecte/tableaux.py).")
    ordre = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "type de réponse"
        verbose_name_plural = "types de réponse"
        ordering = ["ordre", "code"]

    def __str__(self):
        return self.tr("libelle")

    @property
    def numerique(self):
        return self.format in self.NUMERIQUES

    @property
    def est_liste(self):
        return self.format == self.Format.LISTE

    @property
    def est_texte(self):
        """Réponse rédigée (Markdown) ou tableau (enregistré en tableau Markdown) : ni nombre, ni choix ; n'entre dans aucun
        calcul ni aucune agrégation."""
        return self.format in (self.Format.TEXTE, self.Format.TABLEAU)

    @property
    def est_tableau(self):
        """Réponse en tableau : lignes de longueur variable, colonnes définies par ``colonnes`` (collecte/tableaux.py)."""
        return self.format == self.Format.TABLEAU

    @property
    def colonnes_libelles(self):
        """Noms des colonnes d'un tableau dans la langue courante (avec l'unité), pour les aperçus."""
        from collecte.tableaux import colonnes

        return [c.libelle() for c in colonnes(self)]

    @property
    def colonnes_texte(self):
        """Colonnes d'un tableau, une par ligne, pour la page Unités et formats : « code ; libellé ; type ; liste ou unité »
        (libellé dans la langue de référence)."""
        from . import langues as L

        lignes = []
        for c in self.colonnes or []:
            if not isinstance(c, dict):
                continue
            lib = c.get("libelle")
            lib = (lib.get(L.reference()) or next(iter(lib.values()), "")) if isinstance(lib, dict) else (lib or "")
            lignes.append(" ; ".join([str(c.get("code") or ""), lib, str(c.get("type") or ""), str(c.get("liste") or c.get("unite") or "")]).rstrip(" ;"))
        return "\n".join(lignes)

    @property
    def choix(self):
        """Réponses possibles d'un oui / non ou d'une liste (vide pour un nombre ou un texte rédigé)."""
        if self.format == self.Format.OUI_NON:
            return [self.OUI, self.NON]
        return list(self.valeurs) if self.format == self.Format.LISTE else []

    def choix_traduits(self, langue=None):
        """[(clé stockée, texte affiché)] des réponses possibles, dans la langue demandée."""
        from . import langues

        return langues.valeurs(self, self.choix, langue)


def type_reponse_par_defaut():
    """Type de réponse proposé pour un nouveau KPI : le premier type « nombre » (code), s'il en existe un."""
    return TypeReponse.objects.filter(format=TypeReponse.Format.NOMBRE).values_list("code", flat=True).first()


class CategorieDescription(Traduisible):
    """Rubrique de la définition d'un KPI : description, à inclure, à exclure, source…"""

    TRADUITS = (("libelle", "Libellé"),)

    code = models.CharField(max_length=30, primary_key=True)
    libelle = models.CharField("libellé", max_length=80)
    ordre = models.PositiveIntegerField(default=0)
    affichee = models.BooleanField("affichée au contributeur", default=True)
    obligatoire = models.BooleanField(default=False, help_text="À remplir pour enregistrer une fiche KPI.")

    class Meta:
        verbose_name = "catégorie de description"
        verbose_name_plural = "catégories de description"
        ordering = ["ordre", "code"]

    def __str__(self):
        return self.tr("libelle")


class ChampPersonnalise(Traduisible):
    """Information propre à une structure sur ses KPI (ID d'un standard, périmètre d'audit…), hors du cœur de l'outil."""

    TRADUITS = (("libelle", "Libellé"),)

    class Type(models.TextChoices):
        CASE = "case", "Case à cocher"
        TEXTE = "texte", "Texte"
        LISTE = "liste", "Liste de choix"
        DATE = "date", "Date"

    code = models.CharField(max_length=30, primary_key=True)
    libelle = models.CharField("libellé", max_length=80)
    type = models.CharField(max_length=10, choices=Type.choices, default=Type.TEXTE)
    valeurs = models.JSONField("valeurs possibles", default=list, blank=True, help_text="Liste de choix : une valeur par ligne.")
    ordre = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "champ personnalisé"
        verbose_name_plural = "champs personnalisés"
        ordering = ["ordre", "code"]

    def __str__(self):
        return self.tr("libelle")

    @property
    def est_liste(self):
        return self.type == self.Type.LISTE

    def valeurs_traduites(self, langue=None):
        from . import langues

        return langues.valeurs(self, self.valeurs, langue)
