"""Serveur MCP : réglages de l'espace, jetons personnels, appels d'outils et marque « via MCP » du journal (docs/mcp.md).

Tout vit dans la base de l'espace courant : un jeton ne sert que dans l'espace où il a été créé."""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class ReglageMCP(models.Model):
    """Réglages de l'espace (Administration › Paramètres › Assistants). Une seule ligne (clé 1), créée à la première
    lecture. Éteint par défaut."""

    actif = models.BooleanField("assistants permis", default=False)
    ecriture = models.BooleanField("assistants qui modifient", default=False,
                                   help_text="Saisir, valider, justifier, relancer ; sinon lecture seule.")
    appels_minute = models.PositiveSmallIntegerField("appels par minute et par personne", default=60,
                                                     validators=[MinValueValidator(1), MaxValueValidator(600)])
    duree_max_jours = models.PositiveSmallIntegerField("durée de vie maximale d'un jeton (jours)", default=90,
                                                       validators=[MinValueValidator(1), MaxValueValidator(365)])
    # (Q11a, Q11b) : un lecteur lit les valeurs par un assistant (outils de lecture, dans son
    # périmètre, jamais d'écriture) ; les KPI marqués « Restreint » ou « Confidentiel » donnés aux assistants (oui : mêmes
    # droits que les pages ; non : jamais renvoyés ni écrits par aucun outil)
    lecteur_lit = models.BooleanField("un lecteur lit par un assistant", default=False)
    kpi_sensibles = models.BooleanField("KPI sensibles donnés aux assistants", default=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "réglages des assistants (MCP)"
        verbose_name_plural = "réglages des assistants (MCP)"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def courant(cls):
        return cls.objects.get_or_create(pk=1)[0]


class JetonMCP(models.Model):
    """Jeton personnel : montré une fois, gardé haché (SHA-256), avec une date d'expiration. Il n'a aucun droit propre :
    chaque requête relit le compte de son propriétaire. Jamais dans une sauvegarde (parametres/sauvegardes.py)."""

    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jetons_mcp")
    nom = models.CharField(max_length=80)
    empreinte = models.CharField(max_length=64, unique=True)  # SHA-256 du jeton, en hexadécimal
    debut = models.CharField(max_length=12)  # premiers caractères, pour le reconnaître dans une liste
    cree_le = models.DateTimeField(auto_now_add=True)
    expire_le = models.DateTimeField()
    revoque_le = models.DateTimeField(null=True, blank=True)
    revoque_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    derniere_utilisation = models.DateTimeField(null=True, blank=True)
    # empreinte du mot de passe (haché) du propriétaire à la création : un mot de passe changé par n'importe quel chemin,
    # même sans enregistrement du compte (copie remise d'accord avec le registre), rend le jeton invalide (jetons.py)
    mdp_empreinte = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        verbose_name = "jeton d'assistant (MCP)"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.nom} ({self.debut}…)"


class AppelMCP(models.Model):
    """Un appel d'outil : sert à la limite de débit (appels de la personne sur 60 secondes, lus en base : partagé par
    tous les processus) et relie les lignes du journal écrites pendant l'appel (``JournalMCP``). Le jeton est noté par
    son numéro et son début, sans clé étrangère : les jetons ne sont pas sauvegardés, les appels le sont."""

    class Statut(models.TextChoices):
        EN_COURS = "en_cours", "En cours"
        OK = "ok", "Réussi"
        REFUS = "refus", "Refusé"
        ERREUR = "erreur", "Erreur"

    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    jeton_id = models.BigIntegerField(null=True)
    jeton_debut = models.CharField(max_length=12, blank=True)
    outil = models.CharField(max_length=60)
    date = models.DateTimeField(auto_now_add=True)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.EN_COURS)
    duree_ms = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "appel d'outil (MCP)"
        indexes = [models.Index(fields=["utilisateur", "date"], name="appelmcp_debit")]


class JournalMCP(models.Model):
    """Ligne du journal (``collecte.Journal``) écrite pendant un appel d'outil : l'historique l'affiche « via MCP ».
    Numéro de la ligne sans clé étrangère : aucune colonne ajoutée à une table existante, rien de changé à la purge."""

    journal_id = models.BigIntegerField(unique=True)
    appel = models.ForeignKey(AppelMCP, on_delete=models.CASCADE, related_name="lignes")

    class Meta:
        verbose_name = "ligne du journal via MCP"
