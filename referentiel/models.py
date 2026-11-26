"""Référentiel : utilisateurs, organisations, catalogue des KPI, formules, référentiels (arbre de thèmes, éléments) et
attributions (cahier des charges, section 3)."""
import re
import uuid

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from parametres import langues as L
from parametres.libelles import libelle
from parametres.models import Traduisible, type_reponse_par_defaut, valider_couleur

from . import formule as F
from espaces import contexte as ESP


class Frequence(models.TextChoices):
    """Fréquence d'un référentiel, et type des périodes de collecte (calendrier commun : collecte.Periode)."""

    ANNEE = "annee", "Annuelle"
    SEMESTRE = "semestre", "Semestrielle"
    TRIMESTRE = "trimestre", "Trimestrielle"
    MOIS = "mois", "Mensuelle"


MOIS_PAR_FREQUENCE = {Frequence.ANNEE: 12, Frequence.SEMESTRE: 6, Frequence.TRIMESTRE: 3, Frequence.MOIS: 1}


class Niveau:
    """Codes des 4 niveaux créés à l'installation (démo, tests). Les niveaux se règlent dans Paramètres › Niveaux."""

    GROUP, COUNTRY, ENTITY, SITE = "Group", "Country", "Entity", "Site"


# ---------------------------------------------------------------- utilisateurs
class Utilisateur(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrateur"
        VALIDATEUR = "validateur", "Validateur"
        CONTRIBUTEUR = "contributeur", "Contributeur"
        LECTEUR = "lecteur", "Lecteur"  # consulte la Visualisation et le Tableau de bord ; ne saisit rien
        AUDITEUR = "auditeur", "Auditeur"  # lit tout ce qu'il faut pour un audit (saisies, preuves, historique) ; ne modifie rien

    ROLES_LECTURE = [Role.LECTEUR, Role.AUDITEUR]  # comptes qui ne saisissent rien (jamais SPOC)

    email = models.EmailField("e-mail", unique=True)
    role = models.CharField("rôle", max_length=20, choices=Role.choices, default=Role.CONTRIBUTEUR)
    equipe = models.CharField("équipe", max_length=100, blank=True)
    langue = models.CharField(max_length=10, blank=True, default="",
                              help_text="Langue des contenus (noms des KPI, descriptions…) ; vide = langue par défaut de l'installation.")
    doit_changer_mdp = models.BooleanField("doit changer son mot de passe", default=False,
                                           help_text="Mot de passe provisoire donné par l'admin : à remplacer à la prochaine connexion.")
    perimetre_lecture = models.ManyToManyField(
        "Organisation", blank=True, related_name="lecteurs", verbose_name="organisations consultées",
        help_text="Lecteur et auditeur : organisations qu'ils voient (avec celles qui leur sont rattachées) ; vide = toutes.")

    class Meta:
        verbose_name = "utilisateur"

    @property
    def est_admin(self):
        return self.is_superuser or self.role == self.Role.ADMIN

    # requêtes communes (méthodes de classe, pas un gestionnaire propre : le gestionnaire des comptes figure dans les
    # migrations) ; ``qs`` : comptes de départ (par défaut tous, ex. ceux d'une autre base avec .using())
    @classmethod
    def ecrivains(cls, qs=None):
        """Comptes qui écrivent : tous sauf lecteurs et auditeurs (un superutilisateur écrit toujours)."""
        return (cls.objects.all() if qs is None else qs).exclude(is_superuser=False, role__in=cls.ROLES_LECTURE)

    @classmethod
    def admins(cls, qs=None):
        """Administrateurs (rôle administrateur ou superutilisateur), actifs ou non."""
        return (cls.objects.all() if qs is None else qs).filter(models.Q(role=cls.Role.ADMIN) | models.Q(is_superuser=True))

    @property
    def lecture_seule(self):
        """Lecteur ou auditeur : ne saisit, ne valide, ne justifie et ne règle jamais rien."""
        return not self.is_superuser and self.role in (self.Role.LECTEUR, self.Role.AUDITEUR)

    @property
    def est_auditeur(self):
        return not self.is_superuser and self.role == self.Role.AUDITEUR

    @property
    def est_lecteur(self):
        return not self.is_superuser and self.role == self.Role.LECTEUR

    @property
    def est_contributeur(self):
        return not self.is_superuser and self.role == self.Role.CONTRIBUTEUR

    @property
    def email_joignable(self):
        """Adresse à laquelle on peut écrire : vide pour une adresse provisoire en « .invalid » (domaine réservé, jamais
        distribué ; ex. « prenom.nom@a-completer.invalid » d'une reprise de données), traitée comme une adresse absente."""
        e = (self.email or "").strip()
        return "" if e.lower().rpartition("@")[2].endswith(".invalid") or e.lower().endswith("@invalid") else e

    @property
    def voit_tout(self):
        """Voit toutes les cases comme l'administrateur (dans son périmètre de consultation) : admin, lecteur, auditeur."""
        return self.est_admin or self.lecture_seule

    def orgs_permises(self):
        """Identifiants des organisations que voit un lecteur ou un auditeur (celles choisies et leurs descendantes) ;
        None : toutes (et pour les autres rôles, dont le périmètre vient de leurs attributions)."""
        if not self.lecture_seule or not self.pk:
            return None
        if not hasattr(self, "_orgs_permises"):
            choisies = set(self.perimetre_lecture.values_list("id", flat=True))
            if not choisies:
                self._orgs_permises = None
            else:
                parents = dict(Organisation.objects.values_list("id", "parent_id"))
                permises = set()
                for i in parents:
                    o, vues = i, set()
                    while o is not None and o not in vues:
                        if o in choisies:
                            permises.add(i)
                            break
                        vues.add(o)
                        o = parents.get(o)
                self._orgs_permises = permises
        return self._orgs_permises

    def __str__(self):
        return self.get_full_name() or self.email or self.username


# ---------------------------------------------------------------- organisations
class Organisation(models.Model):
    class TypeSite(models.TextChoices):
        ENTREPOT = "entrepot", "Entrepôt"
        BUREAU = "bureau", "Bureau"
        AUTRE = "autre", "Autre"

    nom = models.CharField(max_length=150, unique=True)
    code = models.CharField("code", max_length=30, unique=True, blank=True,
                            help_text="Identifiant stable dans les exports (Power BI) : ne change pas quand on renomme.")
    nom_court = models.CharField("nom court", max_length=60, blank=True)
    niveau = models.ForeignKey("parametres.NiveauHierarchique", on_delete=models.PROTECT, db_column="niveau",
                               related_name="organisations")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="enfants")
    rang = models.PositiveIntegerField(default=0, help_text="Ordre d'affichage")
    type_site = models.CharField("type de site", max_length=10, choices=TypeSite.choices, blank=True)
    actif = models.BooleanField(default=True)
    date_desactivation = models.DateField("date de désactivation", null=True, blank=True)
    # ouverte depuis : l'organisation ne compte qu'à partir de cette date ; vide : ouverte
    # depuis toujours (comportement d'avant, celui de toute organisation existante à la mise à jour)
    date_ouverture = models.DateField("ouverte depuis", null=True, blank=True)

    class Meta:
        ordering = ["rang", "nom"]

    def __str__(self):
        return self.nom

    def save(self, *args, **kwargs):
        self.code = normaliser_code(self.code)
        if not self.code:  # code tiré du nom à la création ; il ne suit plus les renommages
            pris = set(Organisation.objects.exclude(pk=self.pk).values_list("code", flat=True))
            self.code = code_libre(self.nom, pris)
        if self.actif:  # une date de fermeture n'existe que pour une organisation désactivée
            self.date_desactivation = None
        super().save(*args, **kwargs)

    def clean(self):
        """Rattachement souple : le parent est à n'importe quel niveau supérieur ; le sommet n'a pas de parent."""
        if not self.niveau_id:
            return
        niveau = self.niveau
        if niveau.rang == 1 and self.parent_id:
            raise ValidationError({"parent": libelle("messages.organisation.sommet", niveau=niveau.nom)})
        if niveau.rang > 1:
            if not self.parent:
                raise ValidationError({"parent": libelle("messages.organisation.rattachement_requis")})
            if self.parent.niveau.rang >= niveau.rang:
                raise ValidationError({"parent": libelle("messages.organisation.rattachement_niveau", niveau=niveau.nom)})
        if self.pk and self.enfants.filter(niveau__rang__lte=niveau.rang).exists():
            raise ValidationError({"niveau": libelle("messages.organisation.niveau_enfants")})

    def ancetres(self):
        o = self.parent
        while o:
            yield o
            o = o.parent


def normaliser_code(texte):
    """« fr log » → « FR-LOG » : majuscules sans accents, chiffres, « - », « _ » et « . » ; 30 caractères au plus."""
    import re
    import unicodedata

    t = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9_.]+", "-", t).strip("-")[:30]


def code_libre(nom, pris):
    """Code d'organisation tiré du nom, rendu unique par un suffixe (« -2 », « -3 »…)."""
    base = normaliser_code(nom)[:26] or "ORG"
    code, n = base, 1
    while code in pris:
        n += 1
        code = f"{base}-{n}"
    return code


# ---------------------------------------------------------------- paramètres hérités sans ancêtre de leur niveau
def porte_herite(org, niveau, rangs=None, parent=False):
    """Vrai si ``org`` porte elle-même les paramètres hérités (facteurs d'émission) du niveau ``niveau`` : elle est sous
    ce niveau et aucune organisation de ce niveau ne la contient (rattachement souple : un site rattaché directement à
    un pays). Elle a alors sa propre case pour ces paramètres, et les calculs du dessous la lisent (CALC-09). Une
    organisation sous une autre qui porte déjà ce paramètre ne le porte pas : elle le reprend d'elle.
    ``rangs`` : {code du niveau : rang} (relu sinon) ; ``parent`` : le parent s'il est déjà connu (None : pas de parent),
    sinon ``org.parent``."""
    if rangs is None:
        from parametres import niveaux as N

        rangs = N.rangs()
    r = rangs.get(niveau)
    if r is None or org.niveau_id == niveau or rangs.get(org.niveau_id, 0) <= r:
        return False
    p = org.parent if parent is False else parent
    return p is None or rangs.get(p.niveau_id, 0) < r


def porteurs_orphelins(niveau, orgs, rangs, parents=None):
    """Organisations de ``orgs`` qui portent elles-mêmes les paramètres hérités du niveau ``niveau`` (``porte_herite``).
    ``parents`` : {identifiant : organisation} pour retrouver les parents sans requête (sinon ``o.parent``)."""
    return [o for o in orgs if porte_herite(o, niveau, rangs, parents.get(o.parent_id) if parents is not None else False)]


def porteur_herite(org, niveau, rangs, parents=None):
    """Organisation dont la valeur d'un paramètre hérité du niveau ``niveau`` vaut pour ``org``, qui est sous ce niveau :
    son ancêtre de ce niveau ; sans ancêtre de ce niveau, la plus haute organisation de sa lignée sous ce niveau (celle
    qui le porte, ``porte_herite`` : parfois ``org`` elle-même). ``parents`` : {identifiant : organisation} (sinon
    ``o.parent``)."""
    r, x = rangs[niveau], org
    while True:
        p = parents.get(x.parent_id) if parents is not None else x.parent
        if p is not None and p.niveau_id == niveau:
            return p
        if p is None or rangs.get(p.niveau_id, 0) < r:
            return x
        x = p


class OrgAlias(models.Model):
    """Libellés externes (fichiers historiques, autres systèmes) rattachés à une organisation, pour les imports."""

    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="alias")
    source = models.CharField(max_length=50, default="Fichier")
    libelle = models.CharField("libellé", max_length=200)
    id_externe = models.CharField("ID externe", max_length=50, blank=True)

    class Meta:
        verbose_name = "alias d'organisation"
        verbose_name_plural = "alias d'organisations"
        constraints = [models.UniqueConstraint(fields=["source", "libelle"], name="alias_unique")]

    def __str__(self):
        return f"{self.libelle} ({self.source})"


# ---------------------------------------------------------------- KPI
CODE_KPI = re.compile(r"^[^\[\]@\s]{1,30}$")  # sans crochet, @ ni espace : le code s'écrit tel quel dans les formules


def valider_code_kpi(v):
    if not CODE_KPI.match(v or ""):
        raise ValidationError(libelle("messages.kpi.code_invalide"))


class KPIQuerySet(models.QuerySet):
    def select_for_update(self, nowait=False, skip_locked=False, of=(), no_key=False):
        # PostgreSQL refuse de verrouiller le côté facultatif d'une jointure (unité vide) : on ne verrouille que le KPI
        # (update_or_create, get_or_create).
        return super().select_for_update(nowait=nowait, skip_locked=skip_locked, of=of or ("self",), no_key=no_key)


class KPIManager(models.Manager.from_queryset(KPIQuerySet)):
    """Les KPI arrivent avec leur type de saisie, de réponse et leur unité (une seule requête)."""

    def get_queryset(self):
        return super().get_queryset().select_related("type_saisie", "type_reponse", "unite")


class KPI(Traduisible):
    class Agregation(models.TextChoices):
        SOMME = "Somme", "Somme"
        FORMULE = "Formule", "Formule"
        DECOMPTE = "Décompte", "Décompte"
        AUCUNE = "Aucune", "Aucune"

    class AgregationTemps(models.TextChoices):
        """Valeur d'une période longue (année) à partir des périodes plus courtes (mois) quand le KPI se collecte plus
        souvent dans un autre référentiel."""

        SOMME = "somme", "Somme des périodes"
        MOYENNE = "moyenne", "Moyenne des périodes"
        DERNIERE = "derniere", "Dernière valeur"
        AUCUNE = "aucune", "Aucune : saisie séparée à chaque fréquence"

    class Confidentialite(models.TextChoices):
        NON_SENSIBLE = "Non sensible", "Non sensible"
        RESTREINT = "Restreint", "Restreint"
        CONFIDENTIEL = "Confidentiel", "Confidentiel"

    code = models.CharField(max_length=30, primary_key=True, validators=[valider_code_kpi],
                            help_text="Choisi à la création, puis figé : il sert dans les formules et les fichiers.")
    type_saisie = models.ForeignKey("parametres.TypeSaisie", on_delete=models.PROTECT, db_column="type_saisie",
                                    related_name="kpis", verbose_name="type de saisie")
    libelle = models.CharField("nom", max_length=300, blank=True, help_text="Nom dans la langue de référence ; les autres langues "
                               "sont dans les traductions.")
    formule = models.TextField(blank=True, help_text="Ex. : [ACC-01] / [HEU-01] * 1000000 ; [ID@N-1] = même période l'an dernier ; "
                                                   "[ID@P-1] = période précédente")
    unite = models.ForeignKey("parametres.Unite", on_delete=models.PROTECT, null=True, blank=True, db_column="unite",
                              related_name="kpis", verbose_name="unité")
    type_reponse = models.ForeignKey("parametres.TypeReponse", on_delete=models.PROTECT, db_column="type_reponse",
                                     related_name="kpis", verbose_name="type de réponse", default=type_reponse_par_defaut)
    decimales = models.PositiveSmallIntegerField("décimales affichées", default=2)
    granularite = models.ForeignKey("parametres.NiveauHierarchique", on_delete=models.PROTECT, db_column="granularite",
                                    related_name="kpis", verbose_name="granularité")
    methode_agregation = models.CharField("agrégation", max_length=10, choices=Agregation.choices, default=Agregation.AUCUNE)
    agregation_temps = models.CharField(
        "agrégation dans le temps", max_length=10, choices=AgregationTemps.choices, default=AgregationTemps.SOMME,
        help_text="Si le KPI se collecte aussi plus souvent (ex. tous les mois) dans un autre référentiel : comment les "
                  "périodes courtes donnent la valeur de la période longue (ex. l'année).")
    saisie_au_dessus = models.BooleanField(
        "saisie possible aux niveaux supérieurs", default=False,
        help_text="Quand le détail manque, une valeur peut être saisie directement à un niveau supérieur : elle remplace le "
                  "total calculé et les organisations du dessous ne sont plus attendues.")
    na_compte_zero = models.BooleanField(
        "une source N/A compte comme 0", default=False,
        help_text="KPI calculé : une source N/A (non applicable) compte comme 0, pour un total ; le résultat n'est N/A que si "
                  "toutes les sources le sont. Sinon, une source N/A rend le résultat N/A (ratios, moyennes). Proposé coché "
                  "à la création pour une formule qui n'est qu'une somme (+ et − seulement).")
    equipe_responsable = models.CharField("équipe responsable", max_length=100, blank=True)
    preuve_obligatoire = models.BooleanField("preuve obligatoire", default=False)
    confidentialite = models.CharField("confidentialité", max_length=15, choices=Confidentialite.choices, default=Confidentialite.NON_SENSIBLE)
    champs = models.JSONField("champs personnalisés", default=dict, blank=True,
                              help_text="{code du champ: valeur} (Paramètres › Référentiel › Champs personnalisés)")
    ordre = models.PositiveIntegerField(default=0)
    actif = models.BooleanField(default=True)
    date_maj = models.DateTimeField("dernière mise à jour", auto_now=True)

    objects = KPIManager()

    TRADUITS = (("libelle", "Nom"),)

    class Meta:
        verbose_name = "KPI"
        verbose_name_plural = "KPI"
        ordering = ["ordre", "code"]
        base_manager_name = "objects"  # reponse.kpi arrive aussi avec ses types

    def __str__(self):
        return f"[{self.code}] {self.nom}"

    @property
    def nom(self):
        """Nom dans la langue courante (celle de l'utilisateur, ou de l'export), avec repli."""
        return self.tr("libelle")


    # -- comportement (types réglables dans Paramètres › Référentiel) -------
    @property
    def comportement(self):
        return self.type_saisie.comportement if self.type_saisie_id else None

    @property
    def est_calcule(self):
        return self.comportement == "calcul"

    @property
    def est_herite(self):
        """Paramètre saisi en haut et repris en dessous (facteur d'émission)."""
        return self.comportement == "herite"

    @property
    def saisissable_au_dessus(self):
        """Vrai si une valeur peut se saisir au-dessus de la granularité (KPI saisi dont l'option est cochée)."""
        return self.saisie_au_dessus and self.comportement == "saisie"

    def se_saisit_a(self, org, rangs=None):
        """Vrai si le KPI a une case à saisir pour ``org`` : l'organisation est de son niveau de saisie ou, pour un
        paramètre hérité, elle le porte elle-même faute d'ancêtre de ce niveau (``porte_herite``, CALC-09). La saisie
        au-dessus de la granularité (option du KPI) se traite à part."""
        if org.niveau_id == self.granularite_id:
            return True
        return bool(self.type_saisie_id and self.est_herite and porte_herite(org, self.granularite_id, rangs))

    @property
    def format(self):
        return self.type_reponse.format if self.type_reponse_id else "nombre"

    @property
    def est_pourcentage(self):
        return self.format == "pourcentage"

    @property
    def est_numerique(self):
        return self.format in ("nombre", "pourcentage")

    @property
    def est_texte(self):
        """Réponse rédigée en Markdown (format « texte rédigé ») ou tableau (enregistré en tableau Markdown) : n'entre dans aucun calcul, aucune agrégation."""
        return self.format in ("texte", "tableau")

    @property
    def est_tableau(self):
        return self.format == "tableau"

    @property
    def est_entier(self):
        return bool(self.unite_id and self.unite.entier)

    @property
    def choix(self):
        """Réponses possibles d'un KPI oui / non ou liste (vide pour un nombre)."""
        return self.type_reponse.choix if self.type_reponse_id else []

    @property
    def symbole(self):
        """Unité affichée : « % » pour un pourcentage, sinon le symbole de l'unité."""
        if self.est_pourcentage:
            return "%"
        if self.unite_id:
            return self.unite.tr("symbole")
        return ""

    def choix_traduits(self, langue=None):
        """[(clé stockée, texte affiché)] des réponses possibles d'un oui / non ou d'une liste."""
        return self.type_reponse.choix_traduits(langue) if self.type_reponse_id else []

    def reponse_affichee(self, texte, langue=None):
        """Réponse oui / non ou liste dans la langue courante ; un décompte « Oui : 2 · Non : 1 » est traduit morceau par morceau."""
        if not texte or not self.type_reponse_id or self.est_texte:
            return texte
        traduits = dict(self.choix_traduits(langue))
        if texte in traduits:
            return traduits[texte]
        morceaux = []
        for m in texte.split(" · "):
            cle, sep, n = m.rpartition(" : ")
            morceaux.append(f"{traduits.get(cle, cle)} : {n}" if sep else traduits.get(m, m))
        return " · ".join(morceaux)

    def texte_description(self, categorie, langue=None, repli=True):
        """Texte d'une catégorie de description (« description », « a_inclure »…) dans la langue demandée
        (la langue courante par défaut), avec repli sur les autres langues ; vide si absent."""
        textes = {d.langue: d.texte for d in self.descriptions.all() if d.categorie_id == categorie}
        if not repli:
            return textes.get(langue or L.courante(), "")
        for l in L.langues_candidates(langue):
            if textes.get(l):
                return textes[l]
        return next(iter(textes.values()), "")

    # -- validation -------------------------------------------------------
    def clean(self):
        self._agregation_temps_coherente()
        erreurs = self.erreurs_regles()
        if self.est_calcule and self.formule.strip() and "formule" not in erreurs:
            try:
                verifier_formule(self.code, self.formule)
            except ValidationError as e:
                erreurs["formule"] = e.messages
        if erreurs:
            raise ValidationError(erreurs)

    def erreurs_regles(self):
        """Règles de configuration, hors contrôle des références de la formule."""
        erreurs = {}
        if not (self.type_saisie_id and self.type_reponse_id):
            return erreurs
        A = self.Agregation
        if self.est_calcule:
            if self.actif and not self.formule.strip():
                erreurs["formule"] = libelle("messages.kpi.calcule_sans_formule")
            if not self.est_numerique:
                erreurs["type_reponse"] = libelle("messages.kpi.calcule_non_numerique")
        elif self.formule.strip():
            erreurs["formule"] = libelle("messages.kpi.formule_sans_calcule")
        if self.est_herite and self.methode_agregation != A.AUCUNE:
            erreurs["methode_agregation"] = libelle("messages.kpi.agregation.herite", type=self.type_saisie.tr("libelle"))
        elif self.methode_agregation == A.FORMULE and not self.est_calcule:
            erreurs["methode_agregation"] = libelle("messages.kpi.agregation.formule_reservee")
        elif self.est_texte and self.methode_agregation != A.AUCUNE:
            erreurs["methode_agregation"] = libelle("messages.kpi.agregation.texte_redige")
        elif self.methode_agregation == A.SOMME and not self.est_numerique:
            erreurs["methode_agregation"] = libelle("messages.kpi.agregation.somme_texte")
        elif self.methode_agregation == A.SOMME and self.est_pourcentage:
            erreurs["methode_agregation"] = libelle("messages.kpi.agregation.somme_pourcentage")
        elif self.methode_agregation == A.DECOMPTE and self.est_numerique:
            erreurs["methode_agregation"] = libelle("messages.kpi.agregation.decompte_nombre")
        return erreurs

    def agregation_temps_par_defaut(self):
        """Somme pour un nombre, moyenne pour un pourcentage, dernière valeur pour un oui / non, une liste ou un paramètre
        hérité (facteur d'émission)."""
        A = self.AgregationTemps
        if not self.est_numerique or (self.type_saisie_id and self.est_herite):
            return A.DERNIERE
        return A.MOYENNE if self.est_pourcentage else A.SOMME

    def _agregation_temps_coherente(self):
        """À la création, sans choix explicite (démo, import), l'agrégation dans le temps suit le type du KPI ; une réponse
        oui / non ou liste ne s'additionne jamais dans le temps : la somme ou la moyenne devient « dernière valeur »."""
        if not self.type_reponse_id:
            return
        if self._state.adding and not getattr(self, "agregation_temps_choisie", False) and self.agregation_temps == self.AgregationTemps.SOMME:
            self.agregation_temps = self.agregation_temps_par_defaut()
        if self.est_texte:  # un texte rédigé ne se reprend pas d'une période à l'autre : saisi à chaque fréquence
            self.agregation_temps = self.AgregationTemps.AUCUNE
        elif not self.est_numerique and self.agregation_temps in (self.AgregationTemps.SOMME, self.AgregationTemps.MOYENNE):
            self.agregation_temps = self.AgregationTemps.DERNIERE

    def na_compte_zero_par_defaut(self):
        """Proposé à la création : une source N/A compte comme 0 dans un KPI calculé dont la formule n'est qu'une somme
        (+ et − seulement) ; un ratio ou une moyenne garde la règle « une source N/A rend le résultat N/A »."""
        return bool(self.type_saisie_id and self.est_calcule and F.additive(self.formule or ""))

    def _na_compte_zero_coherent(self):
        """À la création, sans choix explicite (import, démo, bibliothèque), la case suit la formule (``na_compte_zero_choisi``
        : choix fait dans la fiche ou donné par le fichier importé)."""
        if self._state.adding and not getattr(self, "na_compte_zero_choisi", False) and not self.na_compte_zero:
            self.na_compte_zero = self.na_compte_zero_par_defaut()

    def _decimales_coherentes(self):
        """Une unité « nombre entier » (comptage) n'a pas de décimales : le KPI s'affiche toujours à 0 décimale. Renvoie
        vrai si les décimales ont changé."""
        if self.decimales and self.unite_id and self.unite.entier:
            self.decimales = 0
            return True
        return False

    def _texte_redige_coherent(self):
        """Texte rédigé : ni unité, ni décimales, ni « N/A compte comme 0 », ni saisie au-dessus de
        la granularité (rien ne s'additionne). Renvoie vrai si les décimales ont changé."""
        if not (self.type_reponse_id and self.est_texte):
            return False
        self.unite, self.na_compte_zero, self.saisie_au_dessus = None, False, False
        change, self.decimales = self.decimales != 0, 0
        return change

    def deduire_reglages(self):
        """Réglages déduits des autres, appliqués avant tout enregistrement (fiche, imports, bibliothèque, démo). Renvoie
        vrai si les décimales ont changé (unité entière, texte rédigé)."""
        self._agregation_temps_coherente()
        self._na_compte_zero_coherent()
        if self._texte_redige_coherent():
            return True
        return self._decimales_coherentes()

    def save(self, *args, **kwargs):
        if self.deduire_reglages() and kwargs.get("update_fields") is not None and "decimales" not in kwargs["update_fields"]:
            kwargs["update_fields"] = [*kwargs["update_fields"], "decimales"]
        with ESP.atomic():
            super().save(*args, **kwargs)
            self.reconstruire_dependances()

    def reconstruire_dependances(self):
        self.sources.all().delete()
        if not self.est_calcule or not self.formule.strip():
            return
        try:
            refs = F.references(self.formule)
        except F.FormuleInvalide:
            return
        KPIFormule.objects.bulk_create(
            [KPIFormule(kpi_calcule=self, kpi_source_id=r.kpi, decalage=r.decalage) for r in refs]
        )


class Description(models.Model):
    """Texte d'une catégorie de description pour un KPI (Paramètres › Référentiel › Catégories de description)."""

    kpi = models.ForeignKey(KPI, on_delete=models.CASCADE, related_name="descriptions")
    categorie = models.ForeignKey("parametres.CategorieDescription", on_delete=models.PROTECT, related_name="textes",
                                  verbose_name="catégorie")
    langue = models.CharField(max_length=10, default="fr")
    texte = models.TextField()

    class Meta:
        verbose_name = "description de KPI"
        verbose_name_plural = "descriptions de KPI"
        constraints = [models.UniqueConstraint(fields=["kpi", "categorie", "langue"], name="description_unique")]

    def __str__(self):
        return f"{self.kpi_id} · {self.categorie_id} · {self.langue}"


# ---------------------------------------------------------------- référentiels (arbre de thèmes et éléments)
CODE_REFERENTIEL = re.compile(r"^[A-Za-z0-9_-]{1,30}$")


# adresses de la rubrique Référentiels (/administration/referentiels/<code>/) : un référentiel de ce code y serait caché
CODES_REFERENTIEL_RESERVES = ("ajouter", "nouveau", "modeles")


def valider_code_referentiel(v):
    if not CODE_REFERENTIEL.match(v or ""):
        raise ValidationError(libelle("messages.referentiel.code_invalide"))
    if v in CODES_REFERENTIEL_RESERVES:
        raise ValidationError(libelle("messages.referentiel.code_reserve", code=v))


class Referentiel(Traduisible):
    """Un cadre de reporting (ESRS, GRI, énergie, interne…) : un arbre de thèmes et des éléments qui pointent vers le
    catalogue unique des KPI. Un même KPI peut figurer dans plusieurs référentiels : une seule valeur est saisie."""

    TRADUITS = (("nom", "Nom"), ("description", "Description"))

    class Comparaison(models.TextChoices):
        N1 = "N-1", "Même période de l'exercice précédent"
        P1 = "P-1", "Période précédente"

    class Origine(models.TextChoices):
        CREE = "cree", "Créé dans l'outil"
        IMPORTE = "importe", "Importé (paquet)"
        FOURNI = "fourni", "Fourni (bibliothèque)"

    code = models.CharField(max_length=30, primary_key=True, validators=[valider_code_referentiel],
                            help_text="Fixé à la création : il sert dans les fichiers.")
    nom = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    couleur = models.CharField(max_length=7, default="#1F5FAD", validators=[valider_couleur])
    ordre = models.PositiveIntegerField(default=0)
    actif = models.BooleanField(default=True, help_text="Un référentiel inactif disparaît des filtres et ne déclenche plus de collecte.")
    frequence = models.CharField("fréquence", max_length=10, choices=Frequence.choices, default=Frequence.ANNEE,
                                 help_text="Une campagne par période : année, semestre, trimestre ou mois.")
    mois_debut = models.PositiveSmallIntegerField("mois de début d'exercice", default=1,
                                                  validators=[MinValueValidator(1), MaxValueValidator(12)],
                                                  help_text="1 = janvier. Les semestres et trimestres en partent.")
    comparaison = models.CharField("comparaison", max_length=3, choices=Comparaison.choices, default=Comparaison.N1,
                                   help_text="Valeur de référence pour l'écart affiché et les contrôles de cohérence.")
    version = models.CharField(max_length=20, default="1.0", help_text="Ex. « 1.0 », « 2026.1 » : comparée à la réimportation d'un paquet.")
    origine = models.CharField(max_length=10, choices=Origine.choices, default=Origine.CREE)
    provenance = models.CharField(max_length=200, blank=True, help_text="D'où il vient : bibliothèque, fichier, installation d'origine.")
    date_version = models.DateField("date de la version", null=True, blank=True,
                                    help_text="Date du contenu de cette version : donnée par la bibliothèque ou le fichier importé, "
                                              "ou posée quand la version change dans l'outil.")
    mis_a_jour_le = models.DateTimeField("installé ou mis à jour le", null=True, blank=True,
                                         help_text="Dernière installation ou mise à jour depuis la bibliothèque ou un fichier référentiel.")
    identifiant = models.UUIDField(default=uuid.uuid4, unique=True, editable=False,
                                   help_text="Identité stable, transmise par les paquets : reconnaît une nouvelle version du même référentiel.")

    class Meta:
        verbose_name = "référentiel"
        ordering = ["ordre", "code"]

    def __str__(self):
        return self.tr("nom")

    # libellés affichés de l'origine (« fichier référentiel » plutôt que l'ancien mot « paquet », gardé dans les choix du
    # modèle pour ne pas changer le schéma)
    LIBELLES_ORIGINE = {"cree": "Créé dans l'outil", "importe": "Importé (fichier référentiel)", "fourni": "Fourni (bibliothèque)"}


class Theme(Traduisible):
    """Thème d'un référentiel, en arbre de profondeur libre (thème › sous-thème › rubrique…)."""

    TRADUITS = (("nom", "Nom"),)

    referentiel = models.ForeignKey(Referentiel, on_delete=models.CASCADE, related_name="themes")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="enfants")
    code = models.CharField(max_length=40, help_text="Unique dans le référentiel : il sert dans les fichiers.")
    nom = models.CharField(max_length=150)
    ordre = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "thème"
        ordering = ["referentiel", "ordre", "id"]
        constraints = [models.UniqueConstraint(fields=["referentiel", "code"], name="theme_code_unique")]

    def __str__(self):
        return self.tr("nom")

    def clean(self):
        if self.parent_id:
            if self.parent.referentiel_id != self.referentiel_id:
                raise ValidationError({"parent": libelle("messages.theme.parent_autre_referentiel")})
            p = self.parent
            while p:
                if p.pk == self.pk:
                    raise ValidationError({"parent": libelle("messages.theme.parent_soi_meme")})
                p = p.parent


class ElementReferentiel(Traduisible):
    """Place d'un KPI du catalogue dans un référentiel : thème, ordre, code et libellé propres (facultatifs), obligatoire."""

    TRADUITS = (("libelle", "Libellé dans le référentiel"),)

    referentiel = models.ForeignKey(Referentiel, on_delete=models.CASCADE, related_name="elements")
    theme = models.ForeignKey(Theme, null=True, blank=True, on_delete=models.SET_NULL, related_name="elements",
                              verbose_name="thème")
    kpi = models.ForeignKey("KPI", on_delete=models.CASCADE, related_name="elements")
    ordre = models.PositiveIntegerField(default=0)
    libelle = models.CharField("libellé dans le référentiel", max_length=300, blank=True,
                               help_text="Facultatif : sinon le nom du KPI.")
    obligatoire = models.BooleanField(default=True, help_text="Décocher pour une information facultative dans ce référentiel.")
    # « Demandé depuis » (règle du projet, ``collecte.demande_depuis``) : début de la première période
    # où le référentiel demande ce KPI. Vide : depuis le début (installations existantes ; le périmètre noté d'un
    # exercice clos reste la vérité). À la création, l'exercice en cours (``depuis_par_defaut``) sauf choix explicite.
    demande_depuis = models.DateField("demandé depuis", null=True, blank=True)

    class Meta:
        verbose_name = "élément de référentiel"
        verbose_name_plural = "éléments de référentiel"
        ordering = ["referentiel", "ordre", "kpi"]
        constraints = [models.UniqueConstraint(fields=["referentiel", "kpi"], name="element_unique")]

    def __str__(self):
        return f"{self.referentiel_id} · {self.kpi_id}"

    def save(self, *args, **kwargs):
        """Création sans « demandé depuis » choisi, par n'importe quelle porte (fiche, contenu, import, modèle de la
        bibliothèque, classeur de configuration) : l'exercice en cours, le plus prudent (aucun exercice passé ne change).
        ``depuis_choisi`` : la valeur posée (même vide) est un choix explicite."""
        if self._state.adding and self.demande_depuis is None and not getattr(self, "depuis_choisi", False):
            from collecte.demande_depuis import depuis_par_defaut

            self.demande_depuis = depuis_par_defaut(self.referentiel_id)
        super().save(*args, **kwargs)


class KPIFormule(models.Model):
    """Dépendance d'un KPI calculé vers un KPI source. Générée automatiquement depuis la formule."""

    kpi_calcule = models.ForeignKey(KPI, on_delete=models.CASCADE, related_name="sources")
    kpi_source = models.ForeignKey(KPI, on_delete=models.PROTECT, related_name="utilise_par", db_constraint=False)
    decalage = models.CharField("décalage", max_length=4, default="N")

    class Meta:
        verbose_name = "dépendance de formule"
        verbose_name_plural = "dépendances de formules"
        constraints = [models.UniqueConstraint(fields=["kpi_calcule", "kpi_source", "decalage"], name="dependance_unique")]


def verifier_formule(id_kpi, texte, kpis_existants=None, graphe=None, non_numeriques=None):
    """Vérifie syntaxe, références existantes, réponses numériques et absence de boucle. Lève ValidationError.

    ``non_numeriques`` : codes des KPI à réponse oui / non ou liste (exclus des formules) ; lus en base si absent."""
    try:
        refs = F.references(texte)
    except F.FormuleInvalide as e:
        raise ValidationError(str(e))
    ids = {r.kpi for r in refs}
    if kpis_existants is None:
        kpis_existants = set(KPI.objects.filter(code__in=ids).values_list("code", flat=True))
    inconnus = sorted(ids - set(kpis_existants) - {id_kpi})
    if inconnus:
        raise ValidationError(libelle("messages.formule.kpi_inconnus", n=len(inconnus), codes=", ".join(inconnus)))
    if non_numeriques is None:
        non_numeriques = set(KPI.objects.filter(code__in=ids).exclude(
            type_reponse__format__in=["nombre", "pourcentage"]).values_list("code", flat=True))
    texte_seul = sorted(ids & set(non_numeriques))
    if texte_seul:
        raise ValidationError(libelle("messages.formule.sources_texte", codes=", ".join(texte_seul)))
    if id_kpi in {r.kpi for r in refs if r.decalage == "N"}:
        raise ValidationError(libelle("messages.formule.auto_reference"))
    # boucle : depuis les sources de même exercice, peut-on revenir au KPI ?
    if graphe is None:
        graphe = {}
        for c, s in KPIFormule.objects.filter(decalage="N").values_list("kpi_calcule_id", "kpi_source_id"):
            graphe.setdefault(c, set()).add(s)
    pile, vus = [r.kpi for r in refs if r.decalage == "N"], set()
    while pile:
        n = pile.pop()
        if n == id_kpi:
            raise ValidationError(libelle("messages.formule.boucle"))
        if n not in vus:
            vus.add(n)
            pile.extend(graphe.get(n, ()))


# ---------------------------------------------------------------- attributions
class Attribution(models.Model):
    class Role(models.TextChoices):
        CONTRIBUTEUR = "contributeur", "Contributeur"
        VALIDATEUR = "validateur", "Validateur"

    kpi = models.ForeignKey(KPI, on_delete=models.CASCADE, related_name="attributions")
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="attributions")
    utilisateur = models.ForeignKey(Utilisateur, on_delete=models.CASCADE, related_name="attributions")
    role = models.CharField("rôle", max_length=15, choices=Role.choices, default=Role.CONTRIBUTEUR)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["kpi", "organisation", "utilisateur", "role"], name="attribution_unique")]

    def clean(self):
        """Un KPI calculé s'attribue aussi : la personne est responsable du résultat (elle ne le saisit pas, mais peut demander
        une valeur forcée, accordée par l'administrateur ou un validateur, voir collecte/forcage.py)."""
        if self.utilisateur_id and self.utilisateur.lecture_seule:
            raise ValidationError(libelle("messages.attribution.lecture_seule"))
        if self.kpi_id and self.organisation_id and self.role == self.Role.CONTRIBUTEUR and not self.kpi.se_saisit_a(self.organisation):
            raise ValidationError(libelle("messages.attribution.niveau", niveau=self.kpi.granularite))


# ---------------------------------------------------------------- travaux après une mise à jour
class TravailApresMiseAJour(models.Model):
    """Travail à faire une seule fois après une mise à jour de l'outil, avec le code de la version installée : une
    migration le pose (sans appeler le code de l'outil, qui peut avoir changé depuis), la fin de « migrate » le fait dès
    que la base est entièrement à jour, puis l'efface (``collecte.mise_a_jour``). Ex. « recalcul » : refaire les calculs
    des campagnes non clôturées quand une règle de calcul change (les périodes clôturées restent figées)."""

    code = models.CharField(max_length=40, primary_key=True)
    motif = models.CharField(max_length=300, blank=True)
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "travail après une mise à jour"
        verbose_name_plural = "travaux après une mise à jour"

    def __str__(self):
        return self.motif or self.code


# ---------------------------------------------------------------- historique des connexions
class HistoriqueConnexion(models.Model):
    """Une connexion à l'outil, réussie, manquée ou refusée par la limite d'essais (referentiel/connexion.py). Gardée dans
    la base de l'espace où elle a lieu (sauvegardée et restaurée avec lui, comme le journal), le temps réglé dans
    Paramètres › Hébergement (``Instance.connexions_jours``), puis effacée par le ménage de la nuit. Le strict nécessaire :
    la date, le compte (s'il a une copie dans cet espace), le résultat. Jamais de mot de passe, jamais d'adresse réseau,
    jamais l'identifiant tapé : seulement son empreinte (``empreinte``, HMAC tronqué), qui permet de voir des essais
    répétés avec le même identifiant sans le montrer (un mot de passe tapé par erreur dans le champ de l'identifiant).
    ``methode`` : mot de passe ou compte d'entreprise (connexion_entreprise/) ; ``motif`` : cause courte d'un refus du
    compte d'entreprise (jamais de jeton ni de réponse du fournisseur)."""

    class Resultat(models.TextChoices):
        REUSSIE = "reussie", "Réussie"
        ECHEC = "echec", "Manquée"
        BLOQUEE = "bloquee", "Bloquée : trop d'essais"

    class Methode(models.TextChoices):
        MOT_DE_PASSE = "mot_de_passe", "Mot de passe"
        ENTREPRISE = "entreprise", "Compte d'entreprise"

    date = models.DateTimeField(auto_now_add=True, db_index=True)
    utilisateur = models.ForeignKey(Utilisateur, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    resultat = models.CharField(max_length=10, choices=Resultat.choices)
    empreinte = models.CharField(max_length=16, blank=True)
    methode = models.CharField(max_length=12, choices=Methode.choices, default=Methode.MOT_DE_PASSE)
    motif = models.CharField(max_length=16, blank=True)

    class Meta:
        verbose_name = "connexion"
        verbose_name_plural = "historique des connexions"
        ordering = ["-date"]
        indexes = [models.Index(fields=["utilisateur", "date"], name="connexion_utilisateur_idx")]
