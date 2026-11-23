"""Page « Santé de l'installation » (Administration › Paramètres › Santé) : une ligne par point, lisible par un
administrateur qui n'est pas technicien, avec un état « Bon », « À regarder » ou « En panne » et ce qu'il faut faire.

Les mesures sont celles de ``/sante/`` (``vues_hebergement.mesurer_sante`` : une seule écriture, jamais doublée ici) ;
s'y ajoutent ce que la supervision n'a pas à dire : âge de la sauvegarde, dernier e-mail envoyé, migrations en attente,
HTTPS de la requête.

Périmètre (règle unique : ``detail_installation_permis``) : l'administrateur d'un espace secondaire qui
n'est pas gestionnaire des espaces voit l'état de l'installation sans le nom des autres espaces ni les chemins du disque
(« détail pour l'IT » réservé au gestionnaire des espaces et à l'administrateur de l'espace principal). Les tâches de fond,
la sauvegarde et le dernier e-mail sont ceux de son espace."""
import datetime

from django.conf import settings
from django.db import DatabaseError, connections
from django.utils import timezone

from collecte import dates_courtes as DC
from espaces import contexte as ESP

from . import sauvegardes as SV
from .libelles import libelle

BON, A_REGARDER, PANNE = "bon", "regarder", "panne"
ORDRE = {PANNE: 0, A_REGARDER: 1, BON: 2}


def detail_installation_permis(utilisateur):
    """Seule règle de « qui voit le détail de l'installation » (noms et pannes des autres espaces, leurs tâches de fond,
    chemins du disque, adresses permises, identifiant SMTP) : un administrateur de l'espace principal, ou le gestionnaire
    des espaces (compte actif du registre commun), où qu'il soit. Lue par /sante/, la page Paramètres › Santé et le volet
    « Pour l'IT » de la page Hébergement. L'appel local sans proxy de la supervision de l'IT est
    décidé par /sante/ (``vues_hebergement._appel_local``), sans compte."""
    from espaces.models import Compte

    if utilisateur is None or not utilisateur.is_authenticated or not utilisateur.is_active:
        return False
    if ESP.code_courant() == ESP.PRINCIPAL and getattr(utilisateur, "est_admin", False):
        return True
    return Compte.objects.filter(pk=utilisateur.pk, gestionnaire=True, actif=True).exists()


def _quand(d):
    d = timezone.localtime(d) if timezone.is_aware(d) else d
    return libelle("admin.sante.date_heure", date=DC.date_courte(d), heure=d.strftime("%H:%M"))


def _ligne(cle, etat, constat, quoi="", detail=""):
    return {"cle": cle, "titre": libelle(f"admin.sante.{cle}.titre"), "etat": etat, "constat": constat, "quoi": quoi,
            "detail": detail}


def _migrations_en_attente(aliases):
    """Alias des bases dont des migrations ne sont pas appliquées (lecture seule, migrations renommées comprises)."""
    from collecte.mise_a_jour import base_a_jour
    from espaces.migrations_renommees import lecture_harmonisee

    en_attente = []
    with ESP.toutes_les_bases(), lecture_harmonisee():
        for alias in aliases:
            try:
                if not base_a_jour(connections[alias]):
                    en_attente.append(alias)
            except DatabaseError:
                continue  # base injoignable : dite par la ligne « Base de données »
    return en_attente


def _dernier_email():
    """(date du dernier e-mail envoyé, date du dernier échec) dans cet espace : relances et e-mail de test."""
    from collecte.models import Journal, Relance

    envoye = Relance.objects.filter(statut=Relance.Statut.ENVOYEE).values_list("date", flat=True).first()
    test = Journal.objects.filter(action="test_email").values_list("date", flat=True).first()
    if test and (envoye is None or test > envoye):
        envoye = test
    echec = Relance.objects.filter(statut=Relance.Statut.ECHEC).values_list("date", flat=True).first()
    return envoye, echec


def lignes(request):
    """[{cle, titre, etat, constat, quoi, detail}] : version, base, fichiers, sauvegarde, disque, e-mail, tâches de fond,
    migrations, HTTPS ; et vrai si le détail pour l'IT est permis."""
    from collecte.templatetags.collecte import depuis

    from .vues_hebergement import espace_disque, mesurer_sante

    permis = detail_installation_permis(request.user)
    ici = ESP.code_courant()
    mesure = mesurer_sante(None if permis else [ici])
    etat, alertes = mesure["etat"], mesure["alertes"]
    sortie = []

    # version
    version = settings.VERSION + (f" ({settings.VERSION_COMMIT[:12]})" if settings.VERSION_COMMIT else "")
    sortie.append(_ligne("version", BON, libelle("admin.sante.version.bon", version=version)))

    # base de données : registre commun et base de chaque espace ; base abîmée, restauration interrompue
    sqlite = ESP.connexion().vendor == "sqlite"
    genre = libelle("admin.sante.base.sqlite") if sqlite else "PostgreSQL"
    abimees = [a for a in alertes if a[0] in ("base_abimee", "restauration")]
    if etat["base"] != "ok":
        sortie.append(_ligne("base", PANNE, libelle("admin.sante.base.panne"), libelle("admin.sante.base.panne_quoi"),
                             etat["base"] if permis else ""))
    elif abimees:
        restauration = all(a[0] == "restauration" for a in abimees)
        sortie.append(_ligne("base", A_REGARDER if restauration else PANNE,
                             libelle("admin.sante.base.restauration" if restauration else "admin.sante.base.abimee"),
                             libelle("admin.sante.base.restauration_quoi" if restauration else "admin.sante.base.abimee_quoi"),
                             "; ".join(a[2] for a in abimees) if permis else ""))
    else:
        sortie.append(_ligne("base", BON, libelle("admin.sante.base.bon", genre=genre)))

    # dossier des fichiers (preuves, logo) modifiable
    if etat["stockage"] != "ok":
        sortie.append(_ligne("fichiers", PANNE, libelle("admin.sante.fichiers.panne"), libelle("admin.sante.fichiers.panne_quoi"),
                             etat["stockage"] if permis else ""))
    else:
        sortie.append(_ligne("fichiers", BON, libelle("admin.sante.fichiers.bon")))

    # sauvegarde de cet espace : la dernière, son âge, la sauvegarde automatique
    from .models import Instance

    try:
        derniere = SV.archives()[:1]
    except OSError:
        derniere = []
    auto = SV.etat_automatique(Instance.courante())
    if not derniere:
        sortie.append(_ligne("sauvegarde", A_REGARDER, libelle("admin.sante.sauvegarde.aucune"),
                             libelle("admin.sante.sauvegarde.aucune_quoi")))
    else:
        d = derniere[0].date
        constat = libelle("admin.sante.sauvegarde.derniere", quand=_quand(d), duree=depuis(d))
        if d > timezone.localtime() + datetime.timedelta(days=1):
            sortie.append(_ligne("sauvegarde", A_REGARDER, constat, libelle("admin.sante.sauvegarde.future_quoi")))
        elif not auto["active"]:
            sortie.append(_ligne("sauvegarde", A_REGARDER, constat + " " + libelle("admin.sante.sauvegarde.auto_non"),
                                 libelle("admin.sante.sauvegarde.auto_non_quoi")))
        elif auto["en_retard"]:
            sortie.append(_ligne("sauvegarde", A_REGARDER, constat + " " + libelle("admin.sante.sauvegarde.retard"),
                                 libelle("admin.sante.sauvegarde.retard_quoi")))
        else:
            sortie.append(_ligne("sauvegarde", BON, constat))

    # espace disque : le plus petit espace libre des dossiers des données, des fichiers et des sauvegardes
    disque = espace_disque()
    if disque is None:
        sortie.append(_ligne("disque", A_REGARDER, libelle("admin.sante.disque.illisible"), libelle("admin.sante.disque.quoi")))
    else:
        libre, dossier = disque
        minimum = settings.ALERTE_DISQUE_MO * 1024 * 1024
        texte = libelle("admin.sante.disque.libre", taille=SV.taille_lisible(libre))
        detail = str(dossier) if permis else ""
        if libre < minimum:
            sortie.append(_ligne("disque", PANNE, texte, libelle("admin.sante.disque.panne_quoi"), detail))
        elif libre < 10 * minimum:
            sortie.append(_ligne("disque", A_REGARDER, texte, libelle("admin.sante.disque.quoi"), detail))
        else:
            sortie.append(_ligne("disque", BON, texte))

    # e-mail : serveur réglé par l'IT, dernier envoi, dernier échec
    envoye, echec = _dernier_email()
    if not settings.EMAIL_HOST:
        sortie.append(_ligne("email", A_REGARDER, libelle("admin.sante.email.non"), libelle("admin.sante.email.non_quoi")))
    elif echec and (envoye is None or echec > envoye):
        sortie.append(_ligne("email", A_REGARDER, libelle("admin.sante.email.echec", quand=_quand(echec)),
                             libelle("admin.sante.email.echec_quoi")))
    else:
        constat = libelle("admin.sante.email.bon")
        constat += " " + (libelle("admin.sante.email.dernier", quand=_quand(envoye)) if envoye
                          else libelle("admin.sante.email.jamais"))
        sortie.append(_ligne("email", BON, constat))

    # tâches de fond : imports et gros exports bloqués, contrôle de la nuit
    bloquees = etat["background_imports"].get("stuck", 0) + etat["background_exports"].get("stuck", 0)
    controle = etat["controle_donnees"]
    messages = [etat[c]["message"] for c in ("background_imports", "background_exports") if etat[c].get("message")]
    if bloquees:
        sortie.append(_ligne("taches", A_REGARDER, libelle("admin.sante.taches.bloquees", n=bloquees),
                             libelle("admin.sante.taches.bloquees_quoi"), "; ".join(messages) if permis else ""))
    elif controle.get("etat") == "late":
        sortie.append(_ligne("taches", A_REGARDER, libelle("admin.sante.taches.controle_retard"),
                             libelle("admin.sante.taches.controle_retard_quoi")))
    else:
        sortie.append(_ligne("taches", BON, libelle("admin.sante.taches.bon")))

    # migrations en attente : base de cet espace et registre commun (tous les espaces pour le détail permis)
    aliases = [ESP.COMMUN] + [ESP.declarer(c) for c in (mesure["codes"] if permis else [ici])]
    attente = _migrations_en_attente(aliases)
    if attente:
        sortie.append(_ligne("migrations", PANNE, libelle("admin.sante.migrations.panne"), libelle("admin.sante.migrations.quoi"),
                             ", ".join(attente) if permis else ""))
    else:
        sortie.append(_ligne("migrations", BON, libelle("admin.sante.migrations.bon")))

    # HTTPS : réglé (DJANGO_HTTPS) et reçu par cette page
    if settings.HTTPS and request.is_secure():
        sortie.append(_ligne("https", BON, libelle("admin.sante.https.bon")))
    else:
        sortie.append(_ligne("https", A_REGARDER, libelle("admin.sante.https.non"), libelle("admin.sante.https.quoi")))
    return sortie, permis


def bilan(lignes_):
    """Phrase du haut : tout va bien, ou le nombre de points en panne et à regarder."""
    pannes = sum(1 for x in lignes_ if x["etat"] == PANNE)
    regarder = sum(1 for x in lignes_ if x["etat"] == A_REGARDER)
    if not pannes and not regarder:
        return BON, libelle("admin.sante.bilan.bon")
    if pannes:
        return PANNE, libelle("admin.sante.bilan.panne", n=pannes) + (
            " " + libelle("admin.sante.bilan.et_regarder", n=regarder) if regarder else "")
    return A_REGARDER, libelle("admin.sante.bilan.regarder", n=regarder)
