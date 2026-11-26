"""Relances par e-mail (cahier des charges, section 4.5) : un seul e-mail par personne, avec la liste de tout ce qui lui
reste à saisir ou à valider, sans copie automatique.

- Destinataires : les contributeurs (SPOC), pour les cases qui leur sont attribuées et ne sont pas encore validées ; les
  KPI facultatifs du référentiel et les cases couvertes par une valeur saisie au-dessus ne sont jamais relancés.
- Manuelle : l'administrateur (toutes les personnes) ou le validateur (personnes de son périmètre, et seulement les cases de
  son périmètre) choisit une campagne ouverte et les personnes à relancer (page Relances, depuis le tableau de bord).
- Automatique (si activée dans la page Relances) : chaque jour d'échéance (ex. 7 et 2 jours avant la fin de saisie),
  toutes les personnes qui ont encore quelque chose à faire dans les campagnes ouvertes concernées, une fois par jour au
  plus (« python manage.py relances --auto », lancée chaque jour par l'image Docker).
Le message suit un modèle réglable (objet et texte, avec des variables) ; chaque envoi est tracé (historique et journal).
Sans serveur d'envoi (SMTP, réglé dans le fichier de réglages ou dans Paramètres › Hébergement) : rien ne part et rien
n'est noté comme envoyé ; on écrit à chaque personne à la main. Tout envoi passe par ``parametres.envoi_emails``.
"""
import logging
import string
from dataclasses import dataclass, field

from django.conf import settings
from django.core.mail import EmailMessage
from django.urls import reverse
from django.utils import timezone

from parametres import envoi_emails as EE
from parametres.libelles import libelle
from referentiel.models import Utilisateur

from . import saisie as S
from .models import Campagne, Journal, Relance, Reponse
from espaces import contexte as ESP

journal = logging.getLogger("reporting.relances")

NOMS_VARIABLES = ("prenom", "nom", "outil", "structure", "campagne", "date_fin", "jours_restants", "nombre", "a_saisir",
                  "brouillons", "liste", "lien", "contact")


def sujet_defaut(langue=None):
    """Objet du modèle d'origine, dans la langue en cours (variables {…} remplacées à l'envoi)."""
    return libelle("messages.relances.sujet_defaut", langue)


def message_defaut(langue=None):
    """Texte du modèle d'origine, dans la langue en cours (variables {…} remplacées à l'envoi)."""
    return libelle("messages.relances.message_defaut", langue)


def variables():
    """[(nom, description)] des variables du modèle, dans la langue en cours."""
    return [(nom, libelle(f"messages.relances.variable.{nom}")) for nom in NOMS_VARIABLES]


def __getattr__(nom):  # SUJET_DEFAUT, MESSAGE_DEFAUT, VARIABLES : lus à chaque accès, dans la langue en cours
    if nom == "SUJET_DEFAUT":
        return sujet_defaut()
    if nom == "MESSAGE_DEFAUT":
        return message_defaut()
    if nom == "VARIABLES":
        return variables()
    raise AttributeError(nom)


LIGNES_MAX = 150  # au-delà, la liste renvoie à la page « Pour moi »


class ModeleInvalide(Exception):
    pass


@dataclass
class AFaire:
    """Ce qui reste à une personne : [(campagne, [lignes non validées])]."""

    personne: Utilisateur
    campagnes: list = field(default_factory=list)
    # campagnes dont un KPI commun figure déjà sous une autre campagne du même e-mail : la relance les concerne aussi
    # (dernière relance de chaque campagne affichée), sans que la ligne soit répétée
    aussi: list = field(default_factory=list)

    @property
    def toutes_campagnes(self):
        return list(dict.fromkeys([c for c, _ in self.campagnes] + self.aussi))

    @property
    def lignes(self):
        return [l for _, ls in self.campagnes for l in ls]

    @property
    def a_saisir(self):
        return sum(1 for l in self.lignes if l.statut != Reponse.Statut.BROUILLON)

    @property
    def brouillons(self):
        return sum(1 for l in self.lignes if l.statut == Reponse.Statut.BROUILLON)

    @property
    def nombre(self):
        return len(self.lignes)


# ---------------------------------------------------------------- qui relancer
def peut_relancer(utilisateur):
    return utilisateur.is_authenticated and (utilisateur.est_admin or utilisateur.role == Utilisateur.Role.VALIDATEUR)


def campagnes_ouvertes(utilisateur):
    """Campagnes en saisie ouverte des référentiels de la personne : ce que couvre une relance « tous les référentiels
    ouverts » (même liste, dans le même ordre, pour la page Relances et la liste « À relancer » du tableau de bord)."""
    refs = S.referentiels_de(utilisateur)
    return [c for c in Campagne.objects.filter(statut=Campagne.Statut.OUVERTE).select_related("referentiel", "periode")
            if c.referentiel in refs]


def portee_par_defaut(ouvertes):
    """Portée proposée d'abord : un seul e-mail pour tous les référentiels ouverts s'il y en a plusieurs."""
    return "toutes" if len(ouvertes) > 1 else "campagne"


def a_faire(campagnes, par=None, destinataires=None, lignes=None):
    """Personnes actives qui ont encore quelque chose à saisir ou à valider dans ``campagnes`` : les cases dont elles sont
    le contributeur attribué (SPOC), comme dans « Pour moi » ; un validateur n'est relancé que pour ses propres cases. ``par`` : la personne qui relance ; un validateur ne voit que les cases de son
    périmètre. ``destinataires`` : limiter à ces identifiants. ``lignes`` : {campagne : lignes déjà construites pour
    ``par``} (``saisie.lignes(par, campagne)``, les mêmes cases), pour ne pas les recalculer. Triées par nom."""
    voulus = set(destinataires) if destinataires is not None else None
    par_personne, vues, aussi = {}, set(), {}
    for c in campagnes:
        # toutes les cases de la campagne (celles du périmètre pour un validateur), calculées une seule fois
        if lignes is not None and c in lignes:
            construites = lignes[c]
        else:
            construites = S.construire_lignes(c, S.cellules(par if par is not None and not par.est_admin else _TOUT, campagne=c), legere=True)
        restes = {}
        for l in construites:
            # couverte (valeur saisie au-dessus) ou KPI facultatif du référentiel : pas attendue, jamais relancée
            if l.statut == Reponse.Statut.VALIDE or not l.attendue:
                continue
            cle = (c.periode_id, l.kpi.code, l.organisation.id)
            if cle in vues:  # KPI commun à deux référentiels de même période : une seule case à remplir
                for p in l.spocs:
                    aussi.setdefault(p.pk, []).append(c)
                continue
            vues.add(cle)
            for p in l.spocs:  # contributeurs actifs attribués à la case
                if voulus is None or p.pk in voulus:
                    restes.setdefault(p.pk, (p, []))[1].append(l)
        for pk, (p, ls) in restes.items():
            par_personne.setdefault(pk, AFaire(p)).campagnes.append((c, ls))
    for pk, af in par_personne.items():
        af.aussi = [c for c in dict.fromkeys(aussi.get(pk, [])) if c not in {x for x, _ in af.campagnes}]
    return sorted(par_personne.values(), key=lambda x: (x.personne.last_name.lower(), x.personne.first_name.lower(), x.personne.email))


def restes_sans_spoc(campagnes, par=None, lignes=None):
    """Nombre de cases encore à saisir ou à valider dans ``campagnes`` sans aucun SPOC actif : personne n'est relancé pour
    elles (mêmes cases que ``a_faire``, une valeur commune à deux référentiels de même période comptée une fois)."""
    vues, n = set(), 0
    for c in campagnes:
        if lignes is not None and c in lignes:
            construites = lignes[c]
        else:
            construites = S.construire_lignes(c, S.cellules(par if par is not None and not par.est_admin else _TOUT, campagne=c), legere=True)
        for l in construites:
            if l.statut == Reponse.Statut.VALIDE or not l.attendue:
                continue
            cle = (c.periode_id, l.kpi.code, l.organisation.id)
            if cle in vues:
                continue
            vues.add(cle)
            n += not l.spocs
    return n


class _Tout:
    """« Utilisateur » qui voit toutes les cases attendues (relances de l'admin et relances automatiques)."""

    est_admin = True
    voit_tout = True
    lecture_seule = est_auditeur = est_lecteur = False

    def orgs_permises(self):
        return None


_TOUT = _Tout()


def dernieres_relances(ids, campagnes=None):
    """{identifiant de la personne : dernière relance envoyée ou notée à la main}. ``campagnes`` : seulement les relances qui portaient sur
    l'une de ces campagnes (celles affichées ; une relance d'une autre campagne ne dit rien de celle-ci). Même
    fonction pour la page Relances et le tableau de bord."""
    relances = Relance.objects.filter(destinataire_id__in=ids, statut__in=[Relance.Statut.ENVOYEE, Relance.Statut.MANUELLE])
    if campagnes is not None:
        relances = relances.filter(campagnes__in=[getattr(c, "pk", c) for c in campagnes]).distinct()
    sortie = {}
    for r in relances.order_by("date", "pk"):
        sortie[r.destinataire_id] = r
    return sortie


# ---------------------------------------------------------------- message
def _variable_inconnue(nom):
    return ModeleInvalide(libelle("messages.relances.modele.variable_inconnue", variable="{" + nom + "}",
                                  variables=", ".join("{" + v + "}" for v in NOMS_VARIABLES)))


class _Valeurs(dict):
    def __missing__(self, cle):
        raise _variable_inconnue(cle)


def verifier_modele(sujet, message):
    """Lève ModeleInvalide si une variable est inconnue ou une accolade mal fermée."""
    for texte in (sujet, message):
        try:
            for _, nom, spec, conv in string.Formatter().parse(texte):
                if nom is not None and (nom not in NOMS_VARIABLES or spec or conv):
                    raise _variable_inconnue(nom)
        except ValueError as e:
            raise ModeleInvalide(libelle("messages.relances.modele.accolade", erreur=e)) from e


REFERENCE = "fr"  # langue des champs relance_sujet / relance_message ; les autres sont dans relance_traductions


def modele(langue=None):
    """(objet, texte) du modèle pour une langue de l'interface (par défaut, celle en cours : celle de la personne relancée
    pendant ``rediger``). : un texte par langue ; un texte vide prend le texte français réglé,
    sinon le texte fourni dans cette langue."""
    from parametres import langues as L
    from parametres.models import Instance

    i = Instance.courante()
    lg = (langue or L.interface() or REFERENCE).split("-")[0]
    propre = (i.relance_traductions or {}).get(lg) or {} if lg != REFERENCE else {}
    return (propre.get("sujet") or i.relance_sujet or sujet_defaut(lg)), (propre.get("message") or i.relance_message or message_defaut(lg))


def modele_propre(langue):
    """(objet, texte) réglés pour cette langue, tels qu'enregistrés (vides : repli)."""
    from parametres.models import Instance

    i = Instance.courante()
    if langue == REFERENCE:
        return i.relance_sujet, i.relance_message
    propre = (i.relance_traductions or {}).get(langue) or {}
    return propre.get("sujet", ""), propre.get("message", "")


def _jours(date_fin, aujourdhui):
    n = (date_fin - aujourdhui).days
    if n in (0, 1):
        return libelle("messages.relances.jours.aujourdhui" if n == 0 else "messages.relances.jours.demain")
    return libelle("messages.relances.jours.dans", nombre=n) if n > 1 else libelle("messages.relances.jours.depassee")


def date_longue(d):
    """Date en toutes lettres dans la langue de l'interface active (celle du destinataire : ``rediger``), comme les pages :
    « 13 January 2027 », « 13. Januar 2027 » (jamais « 13/01/2027 », ambigu en anglais ; seconde recette, B6)."""
    from .templatetags.collecte import date_longue as longue

    return longue(d)


def liste_texte(af):
    """Liste par campagne (s'il y en a plusieurs), puis par organisation."""
    from parametres import langues as L

    lignes, n = [], 0
    with L.activer(af.personne.langue or None):
        for c, ls in af.campagnes:
            if len(af.campagnes) > 1:
                lignes.append(libelle("messages.relances.liste.campagne", titre=c.titre,  # campagne sans fin de saisie : « (sans date) »
                                      date=date_longue(c.date_fin_saisie) if c.date_fin_saisie else libelle("messages.relances.sans_date")))
            org = None
            for l in sorted(ls, key=lambda l: (S.cle_arbre(l.organisation), l.kpi.ordre, l.kpi.code)):
                n += 1
                if n > LIGNES_MAX:
                    break
                if l.organisation != org:
                    org = l.organisation
                    lignes.append(f"{org.nom}")
                etat = libelle("messages.relances.liste.brouillon" if l.statut == Reponse.Statut.BROUILLON
                               else "messages.relances.liste.a_saisir")
                lignes.append(libelle("messages.relances.liste.ligne", kpi=l.kpi.nom, code=l.kpi.code, etat=etat))
            lignes.append("")
    if af.nombre > LIGNES_MAX:
        lignes.append(libelle("messages.relances.liste.reste", n=af.nombre - LIGNES_MAX))
    return "\n".join(lignes).rstrip()


def adresse_outil(request=None):
    if request is not None:
        return request.build_absolute_uri(reverse("collecte:pour_moi"))
    return settings.URL_PUBLIQUE.rstrip("/") + reverse("collecte:pour_moi") if settings.URL_PUBLIQUE else reverse("collecte:pour_moi")


def langue_de(personne):
    """Nom, dans la langue de qui lit, de la langue dans laquelle le message part pour ``personne`` (« anglais »)."""
    from parametres import langues as L

    code = L.interface_de(L.preference(personne) or None)
    return libelle(f"commun.langue_nom.{code}")


def rediger(af, request=None, sujet=None, message=None):
    """(objet, texte) du message pour une personne, dans sa langue (interface et contenus : ``langues.pour``)."""
    from parametres import langues as L

    with L.pour(af.personne):
        return _rediger(af, request, sujet, message)


def _rediger(af, request=None, sujet=None, message=None):
    from parametres.models import Instance

    i = Instance.courante()
    defaut_sujet, defaut_message = modele()
    sujet, message = sujet or defaut_sujet, message or defaut_message
    aujourdhui = timezone.localdate()
    fin = min(c.date_fin_saisie for c, _ in af.campagnes if c.date_fin_saisie) if any(
        c.date_fin_saisie for c, _ in af.campagnes) else None
    valeurs = _Valeurs(
        prenom=af.personne.first_name or af.personne.email, nom=af.personne.last_name, outil=i.titre, structure=i.nom,
        campagne=", ".join(c.titre for c, _ in af.campagnes), date_fin=date_longue(fin) if fin else libelle("messages.relances.sans_date"),
        jours_restants=_jours(fin, aujourdhui) if fin else "", nombre=af.nombre, a_saisir=af.a_saisir, brouillons=af.brouillons,
        liste=liste_texte(af), lien=adresse_outil(request), contact=i.contact)
    return sujet.format_map(valeurs).replace("\n", " ").strip(), message.format_map(valeurs)


# ---------------------------------------------------------------- envoi
def envoi_actif():
    """Un serveur d'envoi (SMTP) est réglé : par l'IT dans le fichier de réglages, ou dans Paramètres › Hébergement
    (``parametres.envoi_emails``). Sans lui, rien ne part : aucune relance n'est envoyée ni notée comme envoyée ; on écrit
    à la main (page Relances, « Écrire à … »)."""
    return EE.envoi_actif()


def marquer(af, par):
    """Note qu'une personne a été relancée hors de l'outil (« Marquer relancé ») : même trace qu'un e-mail envoyé."""
    r = Relance.objects.create(destinataire=af.personne, envoyee_par=par, statut=Relance.Statut.MANUELLE,
                               nb_a_saisir=af.a_saisir, nb_brouillons=af.brouillons)
    r.campagnes.set(af.toutes_campagnes)
    Journal.ecrire(par, "relance_manuelle", af.personne, "à faire", "", str(af.nombre))
    return r


# cause d'un échec d'envoi, en clair (l'erreur technique reste dans Relance.erreur et dans le journal du serveur)
CAUSES_ECHEC = (
    (("MotDePasseIllisible",), "messages.relances.echec.mot_de_passe"),
    (("SMTPAuthenticationError",), "messages.relances.echec.identifiants"),
    (("SMTPRecipientsRefused",), "messages.relances.echec.destinataire"),
    (("SMTPSenderRefused",), "messages.relances.echec.expediteur"),
    (("ConnectionRefusedError", "ConnectionResetError", "ConnectionError", "TimeoutError", "timeout", "gaierror",
      "SMTPServerDisconnected", "SMTPConnectError", "OSError", "socket"), "messages.relances.echec.injoignable"),
)


def cause_echec(erreur):
    """« ConnectionRefusedError : [Errno 111]… » (ou l'exception elle-même) → « le serveur d'e-mails ne répond pas »."""
    nom = erreur.__class__.__name__ if isinstance(erreur, BaseException) else str(erreur or "").split(" ", 1)[0]
    for noms, cle in CAUSES_ECHEC:
        if nom in noms:
            return libelle(cle)
    return libelle("messages.relances.echec.refuse")


def envoyer(liste, par=None, request=None):
    """Envoie un e-mail par personne ; renvoie les relances créées (envoyées ou en échec). Aucune copie. Sans serveur
    d'envoi : rien n'est envoyé ni enregistré (liste vide)."""
    reglage = EE.reglage()
    if not reglage.actif:
        journal.warning("%s reminders not sent: e-mails not enabled (no SMTP server set)", "Manual" if par else "Automatic")
        return []
    sorties = []
    connexion = expediteur = erreur_connexion = None
    try:
        connexion, expediteur = EE.connexion_envoi()  # pas encore ouverte : chaque e-mail ouvre et ferme la sienne
    except EE.MotDePasseIllisible as e:
        erreur_connexion = e
    for af in liste:
        if not af.personne.email_joignable:  # sans adresse, ou adresse provisoire « …@….invalid »
            continue
        sujet, texte = rediger(af, request)
        r = Relance(destinataire=af.personne, envoyee_par=par if getattr(par, "pk", None) else None,
                    nb_a_saisir=af.a_saisir, nb_brouillons=af.brouillons)
        try:
            if erreur_connexion is not None:
                raise erreur_connexion
            EmailMessage(sujet, texte, expediteur, [af.personne.email_joignable], connection=connexion).send()
        except Exception as e:  # SMTP refusé, serveur injoignable… : noté, on continue avec les autres
            # réglé dans l'outil : seulement le nom de l'erreur et le code SMTP (jamais la réponse brute d'un serveur
            # choisi dans l'outil) ; réglé par l'IT : le détail, comme avant
            detail = EE.resume_technique(e) if reglage.source == EE.OUTIL else f"{e.__class__.__name__} : {e}"
            r.statut, r.erreur = Relance.Statut.ECHEC, detail[:500]
            journal.warning("Reminder to %s: failed (%s: %s)", af.personne.email, e.__class__.__name__, e)
        r.save()
        r.campagnes.set(af.toutes_campagnes)
        Journal.ecrire(par, "relance" if par else "relance_auto", af.personne, "à faire", "", str(af.nombre))
        sorties.append(r)
    envoyees = sum(1 for r in sorties if r.statut == Relance.Statut.ENVOYEE)
    journal.info("%s reminders: %s sent, %s failed", "Manual" if par else "Automatic", envoyees,
                 len(sorties) - envoyees)
    return sorties


# ---------------------------------------------------------------- relances automatiques
def jours_echeance(texte):
    """« 7,2 » → [7, 2]."""
    jours = []
    for x in (texte or "").replace(";", ",").split(","):
        x = x.strip()
        if x:
            if not x.isdecimal() or int(x) > 365:
                raise ModeleInvalide(libelle("messages.relances.jours_invalides"))
            jours.append(int(x))
    return sorted(set(jours), reverse=True)


def campagnes_a_relancer(aujourdhui=None):
    """Campagnes ouvertes dont la fin de saisie tombe dans un des jours d'échéance réglés."""
    from parametres.models import Instance

    aujourdhui = aujourdhui or timezone.localdate()
    jours = set(jours_echeance(Instance.courante().relance_jours))
    return [c for c in Campagne.objects.filter(statut=Campagne.Statut.OUVERTE, date_fin_saisie__isnull=False)
            .select_related("referentiel", "periode") if (c.date_fin_saisie - aujourdhui).days in jours]


def relancer_automatiquement(aujourdhui=None, simulation=False):
    """Relances du jour (si activées) ; une seule par personne et par jour. Renvoie la liste des personnes concernées.
    Sans serveur d'envoi (SMTP), elles sont sautées (avertissement dans le journal du serveur) : rien n'est noté ; la
    simulation dit tout de même qui serait relancé."""
    from parametres.models import Instance

    if not Instance.courante().relance_auto:
        return []
    if not simulation and not envoi_actif():
        journal.warning("Automatic reminders skipped: e-mails not enabled (no SMTP server set)")
        return []
    aujourdhui = aujourdhui or timezone.localdate()
    campagnes = campagnes_a_relancer(aujourdhui)
    if not campagnes:
        return []
    if simulation:
        return a_faire_du_jour(campagnes, aujourdhui)
    precedent = Instance.objects.filter(pk=Instance.courante().pk).values_list("derniere_relance_auto", flat=True).first()
    if not reserver_journee(aujourdhui):
        journal.info("Automatic reminders already sent today (space \"%s\"): skipped", ESP.code_courant())
        return []
    reussi = False
    try:
        liste = a_faire_du_jour(campagnes, aujourdhui)
        sorties = envoyer(liste)
        # personne à relancer, ou au moins une relance partie : journée gardée ; sinon (SMTP en panne pour tous), libérée
        reussi = not liste or any(r.statut == Relance.Statut.ENVOYEE for r in sorties)
    finally:
        if not reussi:  # exception ou aucun envoi réussi : un nouveau lancement le même jour (après réparation) renvoie
            liberer_journee(aujourdhui, precedent)
    return liste


def a_faire_du_jour(campagnes, aujourdhui):
    """Personnes à relancer, sans celles déjà relancées automatiquement avec succès ce jour-là."""
    deja = set(Relance.objects.filter(envoyee_par__isnull=True, date__date=aujourdhui, statut=Relance.Statut.ENVOYEE)
               .values_list("destinataire_id", flat=True))
    return [af for af in a_faire(campagnes) if af.personne.pk not in deja]


def reserver_journee(aujourdhui):
    """Réserve la journée des relances automatiques de l'espace courant par une mise à jour conditionnelle : seul le
    processus qui la réussit envoie (deux planificateurs lancés en même temps, redéploiement, deux instances). La
    simulation et les relances écrites depuis la page Relances ne passent pas par là."""
    from django.db.models import Q

    from parametres.models import Instance

    pk = Instance.courante().pk
    return bool(Instance.objects.filter(Q(derniere_relance_auto__isnull=True) | Q(derniere_relance_auto__lt=aujourdhui), pk=pk)
                .update(derniere_relance_auto=aujourdhui))


def liberer_journee(aujourdhui, precedent):
    """Rend la journée réservée par ``reserver_journee`` (valeur d'avant remise), seulement si elle porte encore ce
    jour-là : une réservation prise entre-temps pour un autre jour n'est pas écrasée."""
    from parametres.models import Instance

    Instance.objects.filter(pk=Instance.courante().pk, derniere_relance_auto=aujourdhui).update(derniere_relance_auto=precedent)
    journal.warning("Automatic reminders of %s not sent: the day stays open for a new attempt", aujourdhui)
