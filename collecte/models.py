"""Collecte : campagnes, réponses, preuves et journal (cahier des charges, sections 3 et 5)."""
import os
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from parametres import libelles as LB
from parametres.libelles import libelle
from parametres.models import Traduisible
from referentiel.models import KPI, Frequence, Organisation, Utilisateur


class Periode(Traduisible):
    """Période de collecte, dans un calendrier commun à tous les référentiels : année (exercice), semestre, trimestre
    ou mois. Une valeur se rattache à une période : la valeur mensuelle et la valeur annuelle d'un même KPI sont deux
    réponses distinctes (la seconde peut être cumulée à partir des mois). Voir ``collecte.periodes``."""

    TRADUITS = (("libelle", "Libellé"),)
    Type = Frequence

    type = models.CharField(max_length=10, choices=Frequence.choices)
    debut = models.DateField("début")
    fin = models.DateField("fin")
    libelle = models.CharField("libellé", max_length=40, help_text="Ex. « 2026 », « T1 2026 », « mars 2026 ».")
    # périmètre gelé : codes des KPI qui avaient une case dans la période quand elle a été
    # rouverte pour la première fois après sa clôture ; ``calcul.perimetre_calcul`` ne calcule plus que ceux-là (un KPI
    # ou un modèle ajouté depuis n'y crée pas de case). Vide (None) : jamais rouverte, périmètre d'aujourd'hui.
    perimetre_fige = models.JSONField("périmètre gelé à la réouverture", null=True, blank=True)
    # arbre des organisations de l'époque (règle du projet) : noté à la clôture de la période (toutes
    # ses campagnes clôturées), effacé par une réouverture « recalculer avec l'organisation d'aujourd'hui » ; une période
    # close ou rouverte « en gardant les chiffres » se calcule et s'affiche avec lui (``calcul.arbre_fige``). Forme :
    # {"v": 1, "o": [[id, parent, niveau, actif (0/1), date de désactivation, date d'ouverture], ...]}. Vide : arbre
    # d'aujourd'hui.
    arbre_fige = models.JSONField("arbre des organisations à la clôture", null=True, blank=True)
    # KPI figés par une campagne clôturée alors qu'une autre campagne de la période ne l'est pas (règle « Figer ses
    # chiffres », règle du projet, ``calcul.noter_figes_partiels``) : chacun avec l'arbre des
    # organisations du jour où il a été figé. Forme : {"v": 1, "arbres": [arbre comme ``arbre_fige``, ...],
    # "kpis": {code: rang de son arbre dans "arbres"}}. Vide : aucun KPI figé à part (comme avant).
    figes_partiels = models.JSONField("KPI figés par une campagne clôturée", null=True, blank=True)

    class Meta:
        verbose_name = "période"
        ordering = ["debut", "-fin"]
        constraints = [models.UniqueConstraint(fields=["type", "debut"], name="periode_unique")]

    def __str__(self):
        return self.tr("libelle")

    @property
    def annuelle(self):
        return self.type == Frequence.ANNEE


class Campagne(models.Model):
    class Statut(models.TextChoices):
        PREPARATION = "preparation", "En préparation"
        OUVERTE = "ouverte", "Saisie ouverte"
        REVUE = "revue", "Revue"  # clôture contributeurs : seul l'administrateur modifie
        CLOTUREE = "cloturee", "Clôturée"  # clôture définitive : figée pour tous

    referentiel = models.ForeignKey("referentiel.Referentiel", on_delete=models.PROTECT, related_name="campagnes",
                                    verbose_name="référentiel")
    periode = models.ForeignKey(Periode, on_delete=models.PROTECT, related_name="campagnes", verbose_name="période")
    exercice = models.PositiveIntegerField(help_text="Exercice de la période (année où il commence).")
    date_ouverture = models.DateField("ouverture de la saisie", null=True, blank=True)
    date_fin_saisie = models.DateField("fin de la saisie", null=True, blank=True)
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.PREPARATION)
    seuil_historique = models.DecimalField(
        "seuil hors historique", max_digits=5, decimal_places=2, default=Decimal("2"),
        help_text="Alerte si la valeur dépasse ce multiple de la médiane des exercices précédents, ou en est moins d'une fraction (2 = plus du double ou moins de la moitié).",
    )
    seuil_ecart = models.DecimalField(
        "seuil d'écart avec N-1", max_digits=6, decimal_places=4, null=True, blank=True,
        help_text="En fraction (0,2 = 20 %). Au-delà, le commentaire est obligatoire pour valider. Vide : pas de contrôle.",
    )
    # réouverture qui garde les chiffres de l'époque : rien n'est recalculé à la
    # réouverture ; ensuite, seules les organisations corrigées et leurs totaux au-dessus le sont (comme une correction
    # importée dans une campagne clôturée). Vaut jusqu'à la nouvelle clôture (remis à faux), ``calcul.figee``.
    chiffres_gardes = models.BooleanField("réouverte en gardant les chiffres de l'époque", default=False)

    class Meta:
        ordering = ["referentiel__ordre", "referentiel_id", "-periode__debut"]
        constraints = [models.UniqueConstraint(fields=["referentiel", "periode"], name="campagne_unique")]

    def __str__(self):
        return self.libelle

    @property
    def libelle(self):
        """« Exercice 2026 » pour une campagne annuelle, sinon la période (« mars 2026 »)."""
        if self.periode_id is None:
            return f"Exercice {self.exercice}"
        return f"Exercice {self.periode}" if self.periode.annuelle else str(self.periode)

    def _plusieurs_referentiels(self):
        if not hasattr(self, "_plusieurs"):
            from referentiel.models import Referentiel

            self._plusieurs = Referentiel.objects.filter(actif=True).count() > 1
        return self._plusieurs

    @property
    def nom_complet(self):
        """Avec le référentiel quand il y en a plusieurs actifs (« Énergie · mars 2026 »)."""
        if self._plusieurs_referentiels():
            return f"{self.referentiel} · {self.periode}"
        return self.libelle

    @property
    def titre(self):
        """Titre dans une phrase ou après un tiret, dans la langue de l'interface : ``titre_affiche`` (une seule règle)."""
        return self.titre_affiche

    # Noms à l'écran, dans la langue de l'interface (« Exercice 2026 », « Reporting year 2026 », « Ejercicio 2026 »).
    # ``libelle``, ``nom_complet`` et ``__str__`` restent tels quels : ils nomment aussi les fichiers exportés.
    @property
    def nom_affiche(self):
        if self.periode_id is None:
            return libelle("messages.campagne.exercice", annee=self.exercice)
        return libelle("messages.campagne.exercice", annee=self.periode) if self.periode.annuelle else str(self.periode)

    @property
    def nom_complet_affiche(self):
        if self._plusieurs_referentiels():
            return f"{self.referentiel} · {self.periode}"
        return self.nom_affiche

    @property
    def titre_affiche(self):
        """Nom en milieu de phrase ou après un tiret (« Saisie – exercice 2026 », « Dateneingabe – Berichtsjahr 2026 ») : la
        casse vient du libellé de chaque langue (``messages.campagne.exercice_titre``), jamais d'un passage en minuscules ;
        le nom d'un référentiel ou d'une période (saisi ou traduit) reste tel quel."""
        if self._plusieurs_referentiels():
            return self.nom_complet_affiche
        if self.periode_id is None:
            return libelle("messages.campagne.exercice_titre", annee=self.exercice)
        return libelle("messages.campagne.exercice_titre", annee=self.periode) if self.periode.annuelle else str(self.periode)

    def save(self, *args, **kwargs):
        """Sans référentiel ni période (ex. ``Campagne(exercice=2026)``) : campagne annuelle de l'exercice pour le premier
        référentiel annuel actif (créé au besoin)."""
        from . import periodes as P

        if self.referentiel_id is None:
            from referentiel.composition import referentiel_par_defaut
            from referentiel.models import Referentiel

            self.referentiel = (Referentiel.objects.filter(actif=True, frequence=Frequence.ANNEE).first()
                                or referentiel_par_defaut())
        if self.periode_id is None:
            import datetime

            r = self.referentiel
            self.periode = P.obtenir(r.frequence, datetime.date(self.exercice, r.mois_debut, 1), r.mois_debut)
        if not self.exercice:
            self.exercice = P.exercice_de(self.periode.debut, self.referentiel.mois_debut)
        super().save(*args, **kwargs)

    def clean(self):
        if self.periode_id and self.referentiel_id and self.periode.type != self.referentiel.frequence:
            raise ValidationError(libelle("messages.campagne.periode_incoherente", periode=self.periode, referentiel=self.referentiel,
                                          frequence=LB.choix_phrase(self.referentiel, "frequence")))

    @property
    def en_cours(self):
        """Ouverte ou en revue : les valeurs peuvent encore changer (recalculs)."""
        return self.statut in (self.Statut.OUVERTE, self.Statut.REVUE)

    @property
    def motif_lecture_seule(self):
        if self.statut == self.Statut.CLOTUREE:
            return libelle("messages.campagne.lecture_seule.cloturee")
        if self.statut == self.Statut.REVUE:
            return libelle("messages.campagne.lecture_seule.revue")
        if self.statut == self.Statut.PREPARATION:
            return libelle("messages.campagne.lecture_seule.preparation")
        return libelle("messages.campagne.lecture_seule.fermee")

    def saisie_ouverte(self, jour=None):
        """Vrai si les contributeurs peuvent saisir (les admins peuvent toujours)."""
        jour = jour or timezone.localdate()
        if self.statut != self.Statut.OUVERTE:
            return False
        if self.date_ouverture and jour < self.date_ouverture:
            return False
        if self.date_fin_saisie and jour > self.date_fin_saisie:
            return False
        return True


VALEUR_MAX = Decimal(10) ** 15  # plus grand nombre gardé exactement (SQLite range les décimaux en flottants : ~15 chiffres)
DECIMALES_GARDEES = Decimal("1E-10")  # ce que la base garde (Reponse.valeur)


def valeur_enregistree(v):
    """Valeur réduite aux décimales que la base garde, comme la saisie (``saisie.lire_nombre``) : la moitié en s'éloignant
    de zéro (et non au pair, l'arrondi par défaut de ``Decimal``), sans « -0 ». Pour la saisie, l'import, l'ancien import
    et les résultats de calcul enregistrés : la même valeur ne diffère jamais à la 10e décimale selon son chemin."""
    return v.quantize(DECIMALES_GARDEES, rounding=ROUND_HALF_UP) + 0


class Reponse(models.Model):
    class Statut(models.TextChoices):
        A_SAISIR = "a_saisir", "À saisir"
        BROUILLON = "brouillon", "Brouillon"
        VALIDE = "valide", "Validé"
        CALCULE = "calcule", "Calculé"
        INCOMPLET = "incomplet", "Incomplet"
        ERREUR = "erreur", "Erreur de calcul"

    class Origine(models.TextChoices):
        SAISIE = "saisie", "Saisie"
        IMPORT = "import", "Import"
        CALCUL = "calcul", "Calcul"
        AGREGATION = "agregation", "Agrégation"
        CUMUL = "cumul", "Cumul des périodes"  # année (ou trimestre…) obtenue à partir des mois
        FORCEE = "forcee", "Valeur forcée"  # KPI calculé : valeur donnée à la place du calcul, avec accord (DemandeForcage)

    periode = models.ForeignKey(Periode, on_delete=models.PROTECT, related_name="reponses", verbose_name="période")
    kpi = models.ForeignKey(KPI, on_delete=models.CASCADE, related_name="reponses")
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="reponses")
    valeur = models.DecimalField(max_digits=30, decimal_places=10, null=True, blank=True)
    texte = models.TextField(blank=True, help_text="Réponse oui / non ou liste ; sur un agrégat, le décompte des réponses.")
    non_applicable = models.BooleanField("N/A", default=False)
    commentaire = models.TextField(blank=True)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.BROUILLON)
    origine = models.CharField(max_length=10, choices=Origine.choices, default=Origine.SAISIE)
    message_calcul = models.CharField(max_length=300, blank=True)
    saisi_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    date_maj = models.DateTimeField("dernière mise à jour", auto_now=True)
    valide_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    date_validation = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "réponse"
        constraints = [models.UniqueConstraint(fields=["periode", "kpi", "organisation"], name="reponse_unique")]
        indexes = [models.Index(fields=["periode", "kpi"], name="reponse_periode_kpi")]

    def __str__(self):
        return f"{self.kpi_id} / {self.organisation} / {self.periode}"

    @property
    def est_calculee(self):
        return self.origine in (self.Origine.CALCUL, self.Origine.AGREGATION, self.Origine.CUMUL)


def chemin_preuve(instance, nom):
    """preuves/<période>/<organisation>/<KPI>/<fichier> (parametres/rangement.py) : un fichier déjà présent sous ce nom
    garde sa place, le nouveau reçoit un suffixe."""
    from parametres.rangement import chemin_preuve as chemin

    r = instance.reponse
    return chemin(r.periode.debut, r.periode.annuelle, r.organisation.code or r.organisation_id, r.kpi_id, nom)


# Début du contenu attendu selon l'extension (PDF : « %PDF- » dans le premier kilo-octet, comme le lisent les lecteurs)
PREUVE_SIGNATURES = {"pdf": ("PDF", None), "jpg": ("JPG", b"\xff\xd8\xff"), "jpeg": ("JPG", b"\xff\xd8\xff"),
                     "png": ("PNG", b"\x89PNG\r\n\x1a\n")}


def valider_fichier(f):
    ext = os.path.splitext(f.name)[1].lower().lstrip(".")
    if ext not in settings.PREUVE_EXTENSIONS:
        raise ValidationError(libelle("messages.preuve.formats"))
    if f.size > settings.PREUVE_TAILLE_MAX:
        from .fichiers import mo

        raise ValidationError(libelle("messages.preuve.trop_gros", taille=mo(settings.PREUVE_TAILLE_MAX)))
    if ext in PREUVE_SIGNATURES:  # le contenu doit être ce que l'extension annonce
        format_, signature = PREUVE_SIGNATURES[ext]
        f.seek(0)
        debut = f.read(1024)
        f.seek(0)
        if not (b"%PDF-" in debut if signature is None else debut.startswith(signature)):
            raise ValidationError(libelle("messages.preuve.contenu", format=format_))


class Preuve(models.Model):
    reponse = models.ForeignKey(Reponse, on_delete=models.CASCADE, related_name="preuves")
    fichier = models.FileField(upload_to=chemin_preuve, validators=[valider_fichier])
    nom_fichier = models.CharField(max_length=255, blank=True)
    taille = models.PositiveIntegerField(default=0)
    depose_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    date_depot = models.DateTimeField(auto_now_add=True)
    date_purge = models.DateField("date de purge (RGPD)", null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.fichier and not self.nom_fichier:
            self.nom_fichier = os.path.basename(self.fichier.name)
        if self.fichier:
            self.taille = self.fichier.size
        super().save(*args, **kwargs)


class DemandeForcage(models.Model):
    """Demande de remplacer le résultat calculé d'une case (KPI calculé) par une valeur donnée, avec sa justification.

    Faite par le responsable du résultat (personne attribuée au KPI calculé dans cette organisation), elle attend
    l'accord de l'administrateur ou d'un validateur de l'organisation ; faite par l'un d'eux, elle s'applique aussitôt.
    Une fois acceptée, la case garde la valeur forcée (origine « Valeur forcée ») : le calcul ne la remplace plus et elle
    remonte dans les totaux et les formules, jusqu'à ce qu'on revienne au calcul (demande « levée »). Les demandes
    restent après traitement (historique, audit)."""

    class Statut(models.TextChoices):
        EN_ATTENTE = "en_attente", "En attente d'accord"
        ACCEPTEE = "acceptee", "Acceptée"
        REFUSEE = "refusee", "Refusée"
        RETIREE = "retiree", "Retirée"  # retirée par la personne qui l'avait faite, avant d'être traitée
        LEVEE = "levee", "Levée (retour au calcul)"  # valeur forcée retirée ensuite : la case revient au calcul

    periode = models.ForeignKey(Periode, on_delete=models.PROTECT, related_name="demandes_forcage", verbose_name="période")
    kpi = models.ForeignKey(KPI, on_delete=models.CASCADE, related_name="demandes_forcage")
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="demandes_forcage")
    valeur = models.DecimalField(max_digits=30, decimal_places=10, null=True, blank=True)
    non_applicable = models.BooleanField("N/A", default=False)
    justification = models.TextField()
    valeur_calculee = models.DecimalField("résultat calculé", max_digits=30, decimal_places=10, null=True, blank=True,
                                          help_text="Ce que donnait le calcul au moment de la demande.")
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE)
    demandeur = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    date_demande = models.DateTimeField(auto_now_add=True)
    traite_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    date_traitement = models.DateTimeField(null=True, blank=True)
    motif = models.TextField(blank=True, help_text="Motif du refus ou du retour au calcul.")

    class Meta:
        verbose_name = "demande de valeur forcée"
        verbose_name_plural = "demandes de valeur forcée"
        ordering = ["-date_demande"]
        indexes = [models.Index(fields=["periode", "kpi", "organisation"], name="forcage_case"),
                   models.Index(fields=["statut"], name="forcage_statut")]

    def __str__(self):
        return f"{self.kpi_id} / {self.organisation} / {self.periode} : {self.get_statut_display()}"


class Journal(models.Model):
    """Historique non modifiable des changements."""

    date = models.DateTimeField(auto_now_add=True, db_index=True)
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=30)
    objet = models.CharField(max_length=30)
    objet_id = models.CharField(max_length=100)
    champ = models.CharField(max_length=60, blank=True)
    avant = models.TextField(blank=True)
    apres = models.TextField(blank=True)

    class Meta:
        verbose_name = "entrée de journal"
        verbose_name_plural = "journal"
        ordering = ["-date"]
        # page Journal : comptes par type (regroupement sur « action ») ; historique d'un seul objet (case, réglage,
        # référentiel : filtre sur « objet » et « objet_id »). Migration 0034.
        indexes = [
            models.Index(fields=["action"], name="journal_action_idx"),
            models.Index(fields=["objet", "objet_id"], name="journal_objet_idx"),
            # filtres par exercice et par organisation, périmètre de l'auditeur : lus dans l'index seul (migration 0036)
            models.Index(fields=["objet", "objet_id", "action", "date"], name="journal_objet_action_idx"),
        ]

    @classmethod
    def ecrire(cls, utilisateur, action, objet, champ="", avant="", apres=""):
        return cls.objects.create(
            utilisateur=utilisateur if getattr(utilisateur, "pk", None) else None,
            action=action, objet=objet.__class__.__name__, objet_id=str(objet.pk),
            champ=champ, avant="" if avant is None else str(avant), apres="" if apres is None else str(apres),
        )


class Relance(models.Model):
    """Une relance d'une personne : ce qui lui reste à saisir (cahier des charges, section 4.5). E-mail envoyé par
    l'outil, ou relance faite hors de l'outil (téléphone, messagerie) que l'équipe note avec « Marquer relancé »."""

    class Statut(models.TextChoices):
        ENVOYEE = "envoyee", "Envoyée"
        ECHEC = "echec", "Échec"
        MANUELLE = "manuelle", "Notée à la main"

    date = models.DateTimeField(auto_now_add=True, db_index=True)
    destinataire = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="relances")
    envoyee_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                    help_text="Vide : relance automatique.")
    campagnes = models.ManyToManyField(Campagne, related_name="relances")
    nb_a_saisir = models.PositiveIntegerField("à saisir", default=0)
    nb_brouillons = models.PositiveIntegerField("brouillons", default=0)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.ENVOYEE)
    erreur = models.TextField(blank=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "relance"

    @property
    def automatique(self):
        return self.envoyee_par_id is None

    @property
    def nombre(self):
        return self.nb_a_saisir + self.nb_brouillons


class RegleCoherence(models.Model):
    """Règle entre KPI réglée par l'administrateur, ex. « Femmes formées ≤ Effectif femmes » (onglet Cohérence)."""

    class Operateur(models.TextChoices):
        INF_EGAL = "<=", "≤ inférieur ou égal à"
        SUP_EGAL = ">=", "≥ supérieur ou égal à"
        EGAL = "=", "= égal à"
        INF = "<", "< inférieur à"
        SUP = ">", "> supérieur à"

    nom = models.CharField(max_length=200)
    description = models.TextField(blank=True, help_text="Explication affichée au contributeur quand la règle n'est pas respectée.")
    gauche = models.TextField("partie gauche", help_text="Formule, ex. [EFF-01]")
    operateur = models.CharField("opérateur", max_length=2, choices=Operateur.choices, default=Operateur.INF_EGAL)
    droite = models.TextField("partie droite", help_text="Formule, ex. [EFF-02]")
    tolerance = models.DecimalField("tolérance", max_digits=6, decimal_places=4, default=0,
                                    help_text="Écart relatif toléré (0,01 = 1 %), utile pour « égal à ».")
    niveau = models.ForeignKey("parametres.NiveauHierarchique", on_delete=models.PROTECT, db_column="niveau",
                               related_name="regles", verbose_name="niveau de contrôle")
    bloquante = models.BooleanField(default=False, help_text="Empêche de valider tant que la règle n'est pas respectée.")
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "règle de cohérence"
        verbose_name_plural = "règles de cohérence"
        ordering = ["nom"]

    def __str__(self):
        return self.nom

    @property
    def nom_affiche(self):
        """Nom dans la langue de la personne qui lit quand c'est celui d'une règle d'un modèle de la bibliothèque, sinon tel
        qu'enregistré (``regles_textes``)."""
        from .regles_textes import traduire

        return traduire(self.nom, "nom")

    @property
    def description_affichee(self):
        from .regles_textes import traduire

        return traduire(self.description, "description")


class Alerte(models.Model):
    """Donnée signalée comme incohérente (cahier des charges : évolution « tests de cohérence »)."""

    class Controle(models.TextChoices):
        ECART_N1 = "ecart_n1", "Écart avec N-1"
        HISTORIQUE = "historique", "Hors historique"
        FE = "fe_modifie", "Paramètre hérité modifié"
        RUPTURE = "rupture", "Rupture de série"
        FORMAT = "format", "Format"
        CALCUL = "calcul", "Calcul impossible"
        REGLE = "regle", "Règle entre KPI"
        DETAIL = "ecart_detail", "Écart avec le détail"

    class Gravite(models.TextChoices):
        BLOQUANTE = "bloquante", "Bloquante"
        ALERTE = "alerte", "Alerte"
        INFO = "info", "Info"

    class Statut(models.TextChoices):
        OUVERTE = "ouverte", "À traiter"
        JUSTIFIEE = "justifiee", "Justifiée"
        ACCEPTEE = "acceptee", "Acceptée"
        REJETEE = "rejetee", "Justification rejetée"
        CORRIGEE = "corrigee", "Corrigée"
        IGNOREE = "ignoree", "Ignorée"

    A_TRAITER = (Statut.OUVERTE, Statut.REJETEE)

    campagne = models.ForeignKey(Campagne, on_delete=models.CASCADE, related_name="alertes")
    kpi = models.ForeignKey(KPI, on_delete=models.CASCADE, related_name="alertes")
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="alertes")
    controle = models.CharField("contrôle", max_length=12, choices=Controle.choices)
    regle = models.ForeignKey(RegleCoherence, null=True, blank=True, on_delete=models.CASCADE, related_name="alertes")
    kpis_concernes = models.TextField(blank=True, help_text="ID des KPI d'une règle, séparés par des espaces")
    gravite = models.CharField(max_length=10, choices=Gravite.choices, default=Gravite.ALERTE)
    message = models.CharField(max_length=400)
    valeur = models.CharField(max_length=120, blank=True)
    reference = models.CharField("référence", max_length=200, blank=True)
    empreinte = models.CharField(max_length=200, blank=True, help_text="Valeurs contrôlées : si elles changent, l'alerte est réexaminée")
    textes = models.JSONField(default=dict, blank=True, help_text="Clés des libellés et paramètres du message, de la valeur et de la "
                              "référence : le texte est recomposé dans la langue de la personne qui lit (coherence.texte_alerte)")
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.OUVERTE)
    justification = models.TextField(blank=True)
    justifie_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    date_justification = models.DateTimeField(null=True, blank=True)
    traite_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    date_traitement = models.DateTimeField(null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "alerte de cohérence"
        ordering = ["-date_creation"]
        constraints = [models.UniqueConstraint(fields=["campagne", "kpi", "organisation", "controle", "regle"], name="alerte_unique")]
        indexes = [models.Index(fields=["campagne", "statut"])]

    @property
    def a_traiter(self):
        return self.statut in self.A_TRAITER


class NonSupprimes(models.Manager):
    """Gestionnaire par défaut des objets « supprimables » : ceux qui sont dans la corbeille n'existent plus pour l'outil
    (listes, exports, API, visualisation, comptes). ``tous`` les garde (annulation, purge)."""

    def get_queryset(self):
        return super().get_queryset().filter(supprime_le__isnull=True)


class Supprimable(models.Model):
    """Suppression réversible des objets courants faits par chacun : exports enregistrés, listes
    de KPI, vues de la Visualisation. Supprimer les met dans la corbeille (``supprime_le``) : le message « Supprimé : X.
    Annuler » les remet en place ; la personne qui a supprimé (ou un administrateur) peut les restaurer pendant
    ``jours_corbeille()`` jours (Paramètres › Hébergement, 30 par défaut), puis ils sont effacés pour de bon
    (``purger_corbeille``)."""

    JOURS_CORBEILLE = 30  # délai par défaut (``Instance.corbeille_jours``) ; repli quand le réglage est illisible

    supprime_le = models.DateTimeField("supprimé le", null=True, blank=True, db_index=True)
    supprime_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+", verbose_name="supprimé par")

    objects = NonSupprimes()
    tous = models.Manager()

    class Meta:
        abstract = True  # gestionnaire de base de Django (accès par clé étrangère, effacement en cascade) : sans filtre

    def supprimer(self, utilisateur):
        """Met l'objet dans la corbeille (rien n'est effacé) et purge ce qui y est depuis trop longtemps."""
        self.supprime_le, self.supprime_par = timezone.now(), utilisateur if getattr(utilisateur, "pk", None) else None
        type(self).tous.filter(pk=self.pk).update(supprime_le=self.supprime_le, supprime_par=self.supprime_par)
        purger_corbeille(type(self))

    def restaurable_par(self, utilisateur):
        """Vrai si l'objet est dans la corbeille depuis moins de ``jours_corbeille()`` jours et que la personne l'y a mis
        (ou est administrateur)."""
        if self.supprime_le is None or self.supprime_le < limite_corbeille():
            return False
        return bool(utilisateur.est_admin or (self.supprime_par_id and self.supprime_par_id == utilisateur.id))

    @property
    def efface_le(self):
        """Date à laquelle l'objet sera effacé pour de bon (Récemment supprimés)."""
        return self.supprime_le + timezone.timedelta(days=jours_corbeille()) if self.supprime_le else None

    def restaurer(self):
        self.supprime_le, self.supprime_par = None, None
        type(self).tous.filter(pk=self.pk).update(supprime_le=None, supprime_par=None)


def jours_corbeille():
    """Nombre de jours pendant lesquels un objet supprimé reste restaurable (Paramètres › Hébergement, de 1 à 365)."""
    from parametres.models import Instance

    try:
        n = Instance.courante().corbeille_jours
    except Exception:  # noqa: BLE001 - base pas encore migrée (démarrage) : le délai d'avant
        return Supprimable.JOURS_CORBEILLE
    return min(max(int(n or Supprimable.JOURS_CORBEILLE), 1), 365)


def limite_corbeille():
    """Ce qui a été supprimé avant cette date n'est plus restaurable (et sera effacé à la prochaine purge)."""
    return timezone.now() - timezone.timedelta(days=jours_corbeille())


def purger_corbeille(*modeles):
    """Efface pour de bon ce qui est dans la corbeille depuis plus de ``jours_corbeille()`` jours (tous les modèles
    supprimables par défaut). Renvoie le nombre d'objets effacés."""
    limite = limite_corbeille()
    n = 0
    for m in modeles or MODELES_SUPPRIMABLES:
        n += m.tous.filter(supprime_le__lt=limite).delete()[1].get(m._meta.label, 0)
    return n


class ReglageExport(Supprimable):
    """Export enregistré (page Import / Export) : réglages d'un export, personnels, ou partagés avec tous par l'administrateur."""

    nom = models.CharField(max_length=100)
    description = models.CharField(max_length=200, blank=True)
    parametres = models.JSONField(default=dict)
    proprietaire = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="reglages_export")
    partage = models.BooleanField("partagé avec tous", default=False)
    ordre = models.PositiveIntegerField(default=0, help_text="Position dans la liste (glisser-déposer)")
    date_creation = models.DateTimeField(auto_now_add=True)

    @property
    def nom_affiche(self):
        """Nom à afficher : traduit pour un modèle fourni resté tel quel (exports.texte_fourni)."""
        from .exports import texte_fourni

        return texte_fourni(self, "nom")

    @property
    def description_affichee(self):
        from .exports import texte_fourni

        return texte_fourni(self, "description")

    class Meta:
        verbose_name = "export enregistré"
        verbose_name_plural = "exports enregistrés"
        ordering = ["ordre", "nom"]

    def __str__(self):
        return self.nom


class SelectionKPI(Supprimable):
    """Sélection de KPI réutilisable (constructeur d'export, fichier à remplir) : personnelle, ou partagée avec tous par
    l'administrateur. Les contributeurs et validateurs en créent pour eux-mêmes, sans pouvoir les partager."""

    nom = models.CharField(max_length=100)
    description = models.CharField(max_length=200, blank=True)
    kpis = models.ManyToManyField("referentiel.KPI", related_name="selections", blank=True, verbose_name="KPI")
    proprietaire = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="selections_kpi")
    partage = models.BooleanField("partagée avec tous", default=False)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "sélection de KPI"
        verbose_name_plural = "sélections de KPI"
        ordering = ["nom", "pk"]

    def __str__(self):
        return self.nom

    def modifiable_par(self, utilisateur):
        """Une sélection partagée se modifie par l'administrateur ; une sélection personnelle par la personne qui l'a créée."""
        return utilisateur.est_admin if self.partage else self.proprietaire_id == utilisateur.id

    @classmethod
    def visibles(cls, utilisateur):
        return cls.objects.filter(models.Q(proprietaire=utilisateur) | models.Q(partage=True))


class TableauVisu(models.Model):
    """Ancien tableau de visualisation composé (avant la Visualisation v2), conservé pour la conversion et les
    redirections : chaque tableau est devenu une vue (VueVisu, migration 0023 ; VueVisu.ancien_tableau). Plus aucune
    interface ne le crée ni ne le modifie ; la table sera retirée par une migration ultérieure, après validation.

    ``tuiles`` : [{"type": …, "kpi": code, "source": "liste:<id>" ou "theme:<id>" (tableau), "titre": …, "largeur": 1 à 3}]."""

    class Tuile(models.TextChoices):
        CHIFFRE = "chiffre", "Chiffre clé"
        EVOLUTION = "evolution", "Évolution"
        ORGANISATIONS = "organisations", "Par organisation"
        REPARTITION = "repartition", "Répartition"
        TABLEAU = "tableau", "Tableau de KPI"

    LARGEUR_DEFAUT = {"chiffre": 1, "evolution": 2, "organisations": 2, "repartition": 1, "tableau": 3}

    nom = models.CharField(max_length=100)
    description = models.CharField(max_length=200, blank=True)
    tuiles = models.JSONField(default=list, blank=True)
    proprietaire = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="tableaux_visu")
    partage = models.BooleanField("partagé avec tous", default=False)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "tableau de visualisation"
        verbose_name_plural = "tableaux de visualisation"
        ordering = ["-partage", "nom", "pk"]

    def __str__(self):
        return self.nom

    def modifiable_par(self, utilisateur):
        """Un tableau partagé se modifie par l'administrateur ; un tableau personnel par la personne qui l'a créé."""
        return utilisateur.est_admin if self.partage else self.proprietaire_id == utilisateur.id

    @classmethod
    def visibles(cls, utilisateur):
        return cls.objects.filter(models.Q(proprietaire=utilisateur) | models.Q(partage=True))


class VueVisu(Supprimable):
    """Vue de la Visualisation : des visuels sur une grille, sous des filtres. Personnelle, ou partagée avec tous par
    l'administrateur. Remplace TableauVisu (converti par la migration 0023).

    ``filtres`` : {"periode", "comparaison", "org", "referentiel", "themes", "valeurs"} ; ``visuels`` : liste de
    visuels {"id", "type", "titre", "kpis", "source", "axe", "series", "largeur", "hauteur", "filtres", "options",
    "origine"} (format décrit et validé par ``collecte.visuels``)."""

    nom = models.CharField(max_length=100)
    description = models.CharField(max_length=200, blank=True)
    proprietaire = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="vues_visu")
    partage = models.BooleanField("partagée avec tous", default=False)
    ordre = models.PositiveIntegerField(default=0)  # ordre des vues partagées, réglé par l'admin
    filtres = models.JSONField(default=dict, blank=True)
    visuels = models.JSONField(default=list, blank=True)
    schema = models.PositiveSmallIntegerField(default=1)  # version du format JSON (conversions futures)
    version = models.PositiveIntegerField(default=1)  # verrou optimiste, +1 à chaque enregistrement
    ancien_tableau = models.PositiveIntegerField(null=True, blank=True, unique=True)  # id du TableauVisu converti
    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "vue de visualisation"
        verbose_name_plural = "vues de visualisation"
        ordering = ["-partage", "ordre", "nom", "pk"]

    def __str__(self):
        return self.nom

    def modifiable_par(self, utilisateur):
        """Une vue partagée se modifie par l'administrateur ; une vue personnelle par la personne qui l'a créée."""
        return utilisateur.est_admin if self.partage else self.proprietaire_id == utilisateur.id

    @classmethod
    def visibles(cls, utilisateur):
        return cls.objects.filter(models.Q(proprietaire=utilisateur) | models.Q(partage=True))


MODELES_SUPPRIMABLES = (ReglageExport, SelectionKPI, VueVisu)


class AccueilVisu(models.Model):
    """Vue d'accueil d'un rôle : la vue partagée qui s'ouvre sur /visualisation/ pour les personnes de ce rôle qui n'ont
    pas choisi leur vue par défaut. Une seule par rôle ; réglée par l'administrateur (menu de la vue, ou Paramètres ›
    Visualisation). Remplace la vue d'accueil « pour tous » (migration 0024 : elle l'est devenue pour les 5 rôles)."""

    ROLES = [r.value for r in Utilisateur.Role]  # admin, validateur, contributeur, lecteur, auditeur

    role = models.CharField("rôle", max_length=20, unique=True)
    vue = models.ForeignKey(VueVisu, on_delete=models.CASCADE, related_name="accueils")

    class Meta:
        verbose_name = "vue d'accueil d'un rôle"
        verbose_name_plural = "vues d'accueil des rôles"
        ordering = ["role"]

    def __str__(self):
        return f"{self.role} : {self.vue}"

    @staticmethod
    def role_de(utilisateur):
        """Rôle d'accueil d'une personne (un super-utilisateur compte comme administrateur)."""
        return "admin" if utilisateur.est_admin else utilisateur.role

    @classmethod
    def vue_de(cls, utilisateur):
        """Vue d'accueil du rôle de la personne, si elle la voit (vue partagée), sinon None."""
        a = cls.objects.select_related("vue").filter(role=cls.role_de(utilisateur), vue__partage=True,
                                                     vue__supprime_le__isnull=True).first()
        return a.vue if a else None

    @classmethod
    def roles_de(cls, vue):
        """Rôles dont la vue est la vue d'accueil, dans l'ordre des rôles."""
        roles = set(cls.objects.filter(vue=vue).values_list("role", flat=True))
        return [r for r in cls.ROLES if r in roles]


class PreferenceVisu(models.Model):
    """Préférences d'une personne sur la Visualisation (créées à la première écriture seulement)."""

    utilisateur = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preference_visu")
    vue_defaut = models.ForeignKey(VueVisu, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    ordre = models.JSONField(default=list, blank=True)  # ids des vues dans l'ordre de ses onglets

    class Meta:
        verbose_name = "préférence de visualisation"
        verbose_name_plural = "préférences de visualisation"

    def __str__(self):
        return libelle("messages.preference_visu.nom", utilisateur=self.utilisateur)


class ProfilReprise(models.Model):
    """Profil de reprise d'un ancien système (assistant de reprise, administrateur) : forme du fichier, colonnes, valeurs
    fixes, conversions d'unités et lecture des pourcentages, pour reprendre d'autres fichiers du même système. Les
    correspondances de KPI et d'organisations sont mémorisées par système source (CorrespondanceReprise)."""

    nom = models.CharField(max_length=100)
    source = models.CharField("système d'origine", max_length=100, default="Ancien système")
    reglages = models.JSONField(default=dict)
    proprietaire = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "profil de reprise"
        verbose_name_plural = "profils de reprise"
        ordering = ["nom", "pk"]

    def __str__(self):
        return self.nom


class CorrespondanceReprise(models.Model):
    """Libellé d'un ancien système relié à un KPI ou à une organisation de l'outil (ou ignoré), mémorisé pour les
    reprises suivantes du même système."""

    class Genre(models.TextChoices):
        KPI = "kpi", "KPI"
        ORGANISATION = "org", "Organisation"

    source = models.CharField("système d'origine", max_length=100)
    genre = models.CharField(max_length=3, choices=Genre.choices)
    libelle = models.CharField("libellé dans l'ancien système", max_length=300)
    kpi = models.ForeignKey("referentiel.KPI", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    organisation = models.ForeignKey("referentiel.Organisation", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    ignorer = models.BooleanField(default=False)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "correspondance de reprise"
        verbose_name_plural = "correspondances de reprise"
        constraints = [models.UniqueConstraint(fields=["source", "genre", "libelle"], name="correspondance_reprise_unique")]

    def __str__(self):
        return f"{self.source} · {self.libelle}"


class TacheImport(models.Model):
    """Gros import de valeurs écrit en arrière-plan (Import / Export, au-delà de ``IMPORT_ARRIERE_PLAN_LIGNES`` lignes) :
    la confirmation crée la tâche, un planificateur (``run_imports --schedule``) ou, à défaut, un fil du processus web
    l'exécute paquet par paquet (``collecte.imports_arriere_plan``). Le fichier déposé reste dans files/pending-imports
    jusqu'à la fin de la tâche. ``battement`` : signe de vie du processus qui l'exécute (une tâche dont le battement
    s'arrête est reprise une fois, puis marquée « interrompue »)."""

    class Statut(models.TextChoices):
        ATTENTE = "attente", "En attente"
        EN_COURS = "en_cours", "En cours"
        TERMINEE = "terminee", "Terminé"
        ARRETEE = "arretee", "Arrêté"
        INTERROMPUE = "interrompue", "Interrompu"
        ECHEC = "echec", "Échec"

    ACTIVES = (Statut.ATTENTE, Statut.EN_COURS)

    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    nom_fichier = models.CharField(max_length=255)
    chemin = models.CharField("fichier déposé", max_length=255)
    options = models.JSONField(default=dict, help_text="Choix de l'aperçu (campagne, validation, corrections) et langues.")
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.ATTENTE, db_index=True)
    etape = models.CharField(max_length=10, blank=True, help_text="« lecture » du fichier, puis « ecriture ».")
    lignes = models.PositiveIntegerField("lignes du fichier", default=0)
    lues = models.PositiveIntegerField("lignes lues", default=0)
    total = models.PositiveIntegerField("valeurs à écrire", default=0)
    faites = models.PositiveIntegerField("valeurs traitées", default=0)
    ecrites = models.PositiveIntegerField("valeurs écrites", default=0)
    arret_demande = models.BooleanField(default=False)
    reprises = models.PositiveSmallIntegerField(default=0)
    cree_le = models.DateTimeField(auto_now_add=True)
    debut = models.DateTimeField(null=True, blank=True)
    fin = models.DateTimeField(null=True, blank=True)
    battement = models.DateTimeField(null=True, blank=True)
    resultat = models.JSONField(default=dict, blank=True)
    erreur = models.TextField(blank=True)
    vu = models.BooleanField("résultat vu", default=False)

    class Meta:
        verbose_name = "import en arrière-plan"
        verbose_name_plural = "imports en arrière-plan"
        ordering = ["-cree_le", "-pk"]

    def __str__(self):
        return f"{self.nom_fichier} ({self.get_statut_display()})"

    @property
    def active(self):
        return self.statut in self.ACTIVES

    @property
    def pourcentage(self):
        """Avancement affiché (0 à 100) : lecture du fichier, puis écriture."""
        if self.etape == "ecriture":
            return 100 if not self.total else min(100, round(100 * self.faites / self.total))
        return 0 if not self.lignes else min(100, round(100 * self.lues / self.lignes))


class TacheExport(models.Model):
    """Gros export (Import / Export › Mes exports, fichier à remplir) fabriqué en arrière-plan, au-delà du seuil de
    Paramètres › Hébergement (``Instance.exports_fond_cellules``) : la demande crée la tâche, le planificateur des imports
    (``run_imports --schedule``) ou, à défaut, un fil du processus web fabrique le fichier avec les mêmes fonctions que le
    téléchargement immédiat (``collecte.exports_arriere_plan``). Le fichier est rangé dans files/exports (jamais
    sauvegardé), gardé ``Instance.exports_fond_jours`` jours. ``empreinte`` : droits et périmètre de la personne à la
    demande ; s'ils ont changé au téléchargement, le fichier est supprimé sans être donné. Trace technique : un lecteur
    ou un auditeur qui demande un gros export en crée une, comme il enregistre ses propres exports."""

    class Genre(models.TextChoices):
        EXPORT = "export", "Export"
        REMPLIR = "remplir", "Fichier à remplir"

    class Statut(models.TextChoices):
        ATTENTE = "attente", "En attente"
        EN_COURS = "en_cours", "En cours"
        PRET = "pret", "Prêt"
        VIDE = "vide", "Rien à remplir"
        ECHEC = "echec", "Échec"
        INTERROMPUE = "interrompue", "Interrompu"
        EXPIRE = "expire", "Expiré"

    ACTIVES = (Statut.ATTENTE, Statut.EN_COURS)
    FINIES_A_MONTRER = (Statut.VIDE, Statut.ECHEC, Statut.INTERROMPUE)  # montrées une fois, puis plus

    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    genre = models.CharField(max_length=10, choices=Genre.choices, default=Genre.EXPORT)
    titre = models.CharField("nom affiché", max_length=255)
    parametres = models.JSONField(default=dict, help_text="Réglages de l'export (ou choix du fichier à remplir) et langues.")
    empreinte = models.CharField("droits à la demande", max_length=64)
    cellules = models.PositiveBigIntegerField("cellules estimées", default=0)
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.ATTENTE, db_index=True)
    nom_fichier = models.CharField("nom du fichier téléchargé", max_length=255, blank=True)
    chemin = models.CharField("fichier fabriqué", max_length=255, blank=True)
    taille = models.PositiveBigIntegerField(default=0)
    reprises = models.PositiveSmallIntegerField(default=0)
    cree_le = models.DateTimeField(auto_now_add=True)
    debut = models.DateTimeField(null=True, blank=True)
    fin = models.DateTimeField(null=True, blank=True)
    battement = models.DateTimeField(null=True, blank=True)
    expire_le = models.DateTimeField(null=True, blank=True)
    telecharge_le = models.DateTimeField(null=True, blank=True)
    erreur = models.TextField(blank=True)
    vu = models.BooleanField("fin vue", default=False)

    class Meta:
        verbose_name = "export en arrière-plan"
        verbose_name_plural = "exports en arrière-plan"
        ordering = ["-cree_le", "-pk"]

    def __str__(self):
        return f"{self.titre} ({self.get_statut_display()})"

    @property
    def active(self):
        return self.statut in self.ACTIVES

    @property
    def titre_affiche(self):
        """Nom à afficher, dans la langue de qui lit quand c'est l'outil qui l'a composé à la demande (``titre_compose`` des
        paramètres : « Fichier à remplir – … », nom de la présentation d'un export sans nom tapé) ; un nom donné par la
        personne, ou une tâche d'avant, reste tel qu'enregistré (``titre``)."""
        from parametres.libelles import libelle

        c = (self.parametres or {}).get("titre_compose") or {}
        try:
            if c.get("remplir") == "tous":
                return libelle("suivi.echanges.exports.fond.remplir_tous")
            if c.get("remplir"):
                campagne = Campagne.objects.filter(pk=c["remplir"]).first()
                if campagne is not None:
                    return libelle("suivi.echanges.exports.fond.remplir", campagne=campagne.nom_complet_affiche)
            if c.get("presentation") or c.get("fourni"):
                from .exports import presentations

                nom = libelle(f"suivi.echanges.fourni.{c['fourni']}.nom") if c.get("fourni") else \
                    next((n for code, n, _ in presentations() if code == c["presentation"]), "")
                if nom:
                    annees = c.get("annees")
                    return libelle("suivi.echanges.exports.fond.nom_annees", nom=nom, annees=", ".join(map(str, annees))) if annees else nom
        except (TypeError, ValueError):  # paramètres abîmés : le nom enregistré
            pass
        return self.titre
