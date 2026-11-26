"""Page « Santé de l'installation » (Administration › Paramètres › Santé) : une ligne par point, lisible par un
administrateur qui n'est pas technicien, avec un état « Bon », « À regarder » ou « En panne » et ce qu'il faut faire.

Les mesures sont celles de ``/sante/`` (``vues_hebergement.mesurer_sante`` : une seule écriture, jamais doublée ici) ;
s'y ajoutent ce que la supervision n'a pas à dire : âge de la sauvegarde, dernier e-mail envoyé, migrations en attente,
HTTPS de la requête.

Les mêmes lignes sont la source des alertes par e-mail (``alertes.py``) : chaque ligne dit si elle alerte (``alerte`` :
le cas, ou "" pour un état qui n'alerte pas) et sa portée (``portee`` : toute l'installation ou l'espace mesuré) ; il
n'y a pas de seconde liste de contrôles.

Périmètre (règle unique : ``detail_installation_permis``) : l'administrateur d'un espace secondaire qui
n'est pas gestionnaire des espaces voit l'état de l'installation sans le nom des autres espaces ni les chemins du disque
(« détail pour l'IT » réservé au gestionnaire des espaces et à l'administrateur de l'espace principal). Les tâches de fond,
la sauvegarde et le dernier e-mail sont ceux de son espace."""
import datetime
from pathlib import PurePath

from django.conf import settings
from django.db import DatabaseError, connections
from django.utils import timezone

from collecte import dates_courtes as DC
from espaces import contexte as ESP

from . import sauvegardes as SV
from .libelles import libelle

BON, A_REGARDER, PANNE = "bon", "regarder", "panne"
ORDRE = {PANNE: 0, A_REGARDER: 1, BON: 2}
INSTALLATION, ESPACE = "installation", "espace"  # portée d'une ligne (clé des alertes : avec ou sans l'espace)


def detail_installation_permis(utilisateur):
    """Seule règle de « qui voit le détail de l'installation » (noms et pannes des autres espaces, leurs tâches de fond,
    chemins du disque, adresses permises, identifiant SMTP) : un administrateur de l'espace principal, ou le gestionnaire
    des espaces (compte actif du registre commun), où qu'il soit. Lue par /sante/, la page Paramètres › Santé et le volet
    « Pour l'IT » de la page Hébergement. L'appel local sans proxy de la supervision de l'IT est
    décidé par /sante/ (``vues_hebergement._appel_local``), sans compte. Règle pour LIRE : ÉCRIRE un réglage de toute
    l'installation exige un gestionnaire des espaces (``espaces.comptes.est_gestionnaire``)."""
    from espaces.comptes import est_gestionnaire

    if utilisateur is None or not utilisateur.is_authenticated or not utilisateur.is_active:
        return False
    if ESP.code_courant() == ESP.PRINCIPAL and getattr(utilisateur, "est_admin", False):
        return True
    return est_gestionnaire(utilisateur)


def quand(d):
    d = timezone.localtime(d) if timezone.is_aware(d) else d
    return libelle("admin.sante.date_heure", date=DC.date_courte(d), heure=d.strftime("%H:%M"))


def ligne_sante(cle, etat, constat, quoi="", detail="", alerte="", portee=ESPACE, titre=None):
    """Une ligne de la page. ``alerte`` : le cas qui part dans les alertes par e-mail (vide : cet état n'alerte pas)."""
    return {"cle": cle, "titre": titre if titre is not None else libelle(f"admin.sante.{cle}.titre"), "etat": etat,
            "constat": constat, "quoi": quoi, "detail": detail, "alerte": alerte, "portee": portee}


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


def _ligne_autorites():
    """Ligne « Autorités de certification ajoutées » : celles en service (sujet, date d'expiration), « À regarder » si
    l'une expire dans moins de 30 jours ou a expiré, si un fichier est écarté, ou si le fichier réuni n'est pas en
    service dans ce processus. None : rien n'est ajouté (``EXTRA_CA_CERTS`` vide, ou dossier vide de l'image). Lu dans
    les réglages, préparés au démarrage par ``config/autorites_certificats.py`` (aucune application n'importe config)."""
    bilan = settings.AUTORITES_BILAN
    if not bilan.demande:
        return None
    en_service = settings.AUTORITES_EN_SERVICE and bool(bilan.autorites)

    def elements(liste):
        return "; ".join(libelle("admin.sante.autorites.element", sujet=a.sujet, date=DC.date_courte(a.expire.date()))
                         for a in liste)

    if en_service:
        constat = [libelle("admin.sante.autorites.bon", liste=elements(bilan.autorites))]
    elif bilan.autorites:
        constat = [libelle("admin.sante.autorites.hors_service")]
    else:
        constat = [libelle("admin.sante.autorites.aucune")]
    quoi = ""
    a_regarder = [a for a in bilan.autorites if a.a_regarder()]
    if a_regarder:
        # sujets seulement : leur date est déjà dans la phrase d'avant, sauf si rien n'est en service
        liste = elements(a_regarder) if not en_service else "; ".join(a.sujet for a in a_regarder)
        constat.append(libelle("admin.sante.autorites.expirent", liste=liste))
        quoi = libelle("admin.sante.autorites.expirent_quoi")
    if bilan.ecartes:
        # le nom du fichier seulement (le dossier est celui des autorités) ; le journal du démarrage donne le chemin
        constat.append(libelle("admin.sante.autorites.ecartes", liste="; ".join(
            libelle("admin.sante.autorites.ecarte", fichier=PurePath(f).name,
                    raison=libelle(f"admin.sante.autorites.raison.{r}"))
            for f, r in bilan.ecartes)))
        quoi = quoi or libelle("admin.sante.autorites.ecartes_quoi")
    if bilan.autorites and not en_service:
        quoi = quoi or libelle("admin.sante.autorites.hors_service_quoi")
    etat = BON if en_service and not a_regarder and not bilan.ecartes else A_REGARDER
    fichiers = ", ".join(dict.fromkeys(a.fichier for a in bilan.autorites))
    return ligne_sante("autorites", etat, " ".join(constat), quoi, fichiers)


def _ligne_copie():
    """Ligne « Copie externe » : rien dans la version tout-en-un (fonction absente) ; sans destination, un conseil (état
    « Bon », jamais une alerte : aucune installation ne change à la mise à jour) ; un échec de copie est un problème
    signalé (``alertes.signaler``, même titre), montré avec les problèmes signalés : pas de seconde ligne."""
    from espaces.models import ProblemeSignale

    from . import copie_externe as CE

    s = CE.resume_etat()
    if s["etat"] == "absente":
        return []
    try:
        if ProblemeSignale.objects.filter(cle=CE.CLE_ALERTE).exists():
            return []
    except DatabaseError:
        pass
    cle = "copie_externe"
    if s["etat"] == "aucune":
        return [ligne_sante(cle, BON, libelle("admin.sante.copie_externe.aucune"), libelle("admin.sante.copie_externe.aucune_quoi"),
                            portee=INSTALLATION)]
    if s["etat"] == "a_confirmer":
        return [ligne_sante(cle, A_REGARDER, libelle("admin.sante.copie_externe.a_confirmer"),
                            libelle("admin.sante.copie_externe.a_confirmer_quoi"), portee=INSTALLATION)]
    if s["etat"] == "echec":
        return [ligne_sante(cle, PANNE, libelle("admin.copie.alerte.constat", n=s["attente"]),
                            libelle(f"admin.copie.cause.{s['echec']}", delai=CE.DELAI_COPIE), portee=INSTALLATION)]
    if s["etat"] == "retard":
        return [ligne_sante(cle, A_REGARDER, libelle("admin.sante.copie_externe.retard", n=s["attente"]),
                            libelle("admin.sante.copie_externe.retard_quoi"), alerte="retard", portee=INSTALLATION)]
    constat = (libelle("admin.sante.copie_externe.ok", quand=quand(s["reussie_le"])) if s["reussie_le"]
               else libelle("admin.sante.copie_externe.ok_jamais"))
    constat += " " + (libelle("admin.sante.copie_externe.attente", n=s["attente"]) if s["attente"]
                      else libelle("admin.sante.copie_externe.tout"))
    return [ligne_sante(cle, BON, constat, portee=INSTALLATION)]


def _sauvegarde_illisible(archive):
    """La sauvegarde la plus récente ne se lit pas : son descriptif ne s'ouvre pas (lu à chaque fois, rapide), ou le
    contrôle de la nuit (``check_data``, qui relit tout le fichier) l'a trouvée abîmée."""
    from collecte import controle_donnees as CD

    try:
        SV.lire_descriptif(archive.chemin)
    except SV.ErreurSauvegarde:
        return True
    r = CD.dernier() or {}
    return any(c.get("check") == "backup_unreadable" and any(str(e).startswith(f"{archive.nom}:") for e in c.get("examples", []))
               for c in r.get("problems", []))


def _erreurs_du_controle():
    """(nombre d'erreurs, date) du dernier contrôle de la nuit de l'espace, hors sauvegarde (ligne « Dernière
    sauvegarde ») et hors constats déjà signalés ailleurs (« À traiter »)."""
    from collecte import controle_donnees as CD

    r = CD.dernier()
    if not r:
        return 0, None
    n = sum(c.get("count", 0) for c in CD.a_signaler(r)
            if c.get("severity") == CD.ERREUR and not str(c.get("check", "")).startswith("backup_"))
    return n, CD.date_de(r)


def lignes(request):
    """[{cle, titre, etat, constat, quoi, detail, alerte, portee}] : version, base, fichiers, sauvegarde, disque, e-mail,
    tâches de fond, migrations, problèmes signalés, HTTPS ; et vrai si le détail pour l'IT est permis."""
    permis = detail_installation_permis(request.user)
    return constats(permis, https=bool(settings.HTTPS and request.is_secure())), permis


def constats(permis, https=None, codes=None):
    """Les lignes de la page Santé, sans requête : ``https`` vrai ou faux pour la ligne HTTPS (None : pas de ligne, les
    alertes n'ont pas de requête) ; ``codes`` : les espaces mesurés (par défaut tous si ``permis``, sinon l'espace
    courant). Lu par la page et par les alertes par e-mail (``alertes.py``, chaque espace avec ``codes=[code]``)."""
    from collecte.templatetags.collecte import depuis

    from . import taches_fond
    from .vues_hebergement import espace_disque, mesurer_sante

    ici = ESP.code_courant()
    if codes is None:
        codes = None if permis else [ici]
    mesure = mesurer_sante(codes)
    etat, alertes = mesure["etat"], mesure["alertes"]
    sortie = []

    # version
    version = settings.VERSION + (f" ({settings.VERSION_COMMIT[:12]})" if settings.VERSION_COMMIT else "")
    sortie.append(ligne_sante("version", BON, libelle("admin.sante.version.bon", version=version)))

    # base de la démo sur un serveur, comptes au mot de passe public (demo_serveur.py) : ligne seulement si c'est vrai
    from .demo_serveur import ligne as ligne_demo

    sortie += [x for x in [ligne_demo()] if x]

    # base de données : registre commun et base de chaque espace ; base abîmée, restauration interrompue (elle se termine
    # seule en une minute : n'alerte pas)
    sqlite = ESP.connexion().vendor == "sqlite"
    genre = libelle("admin.sante.base.sqlite") if sqlite else "PostgreSQL"
    abimees = [a for a in alertes if a[0] in ("base_abimee", "restauration")]
    if etat["base"] != "ok":
        sortie.append(ligne_sante("base", PANNE, libelle("admin.sante.base.panne"), libelle("admin.sante.base.panne_quoi"),
                             etat["base"] if permis else "", alerte="panne"))
    elif abimees:
        restauration = all(a[0] == "restauration" for a in abimees)
        sortie.append(ligne_sante("base", A_REGARDER if restauration else PANNE,
                             libelle("admin.sante.base.restauration" if restauration else "admin.sante.base.abimee"),
                             libelle("admin.sante.base.restauration_quoi" if restauration else "admin.sante.base.abimee_quoi"),
                             "; ".join(a[2] for a in abimees) if permis else "", alerte="" if restauration else "abimee"))
    else:
        sortie.append(ligne_sante("base", BON, libelle("admin.sante.base.bon", genre=genre)))

    # dossier des fichiers (preuves, logo) modifiable
    if etat["stockage"] != "ok":
        sortie.append(ligne_sante("fichiers", PANNE, libelle("admin.sante.fichiers.panne"), libelle("admin.sante.fichiers.panne_quoi"),
                             etat["stockage"] if permis else "", alerte="panne"))
    else:
        sortie.append(ligne_sante("fichiers", BON, libelle("admin.sante.fichiers.bon")))

    # sauvegarde de cet espace : la dernière, son âge, la sauvegarde automatique (échec noté par le planificateur)
    from .models import Instance

    dossier_lisible = True
    try:
        derniere = SV.archives()[:1]
    except OSError:
        derniere, dossier_lisible = [], False
    auto = SV.etat_automatique(Instance.courante())
    echec = SV.echec_auto() if auto["active"] else None
    if echec is not None and auto["derniere"] is not None and echec <= auto["derniere"]:
        echec = None  # une sauvegarde automatique a réussi depuis
    constat = (libelle("admin.sante.sauvegarde.derniere", quand=quand(derniere[0].date), duree=depuis(derniere[0].date))
               if derniere else "")
    if echec is not None:
        sortie.append(ligne_sante("sauvegarde", PANNE, " ".join(filter(None, [libelle("admin.sante.sauvegarde.echec", quand=quand(echec)),
                                                                            constat])),
                             libelle("admin.sante.sauvegarde.echec_quoi"), alerte="echec"))
    elif not dossier_lisible:
        sortie.append(ligne_sante("sauvegarde", PANNE, libelle("admin.sante.sauvegarde.dossier_illisible"),
                             libelle("admin.sante.sauvegarde.dossier_illisible_quoi"), alerte="illisible"))
    elif not derniere:
        sortie.append(ligne_sante("sauvegarde", A_REGARDER, libelle("admin.sante.sauvegarde.aucune"),
                             libelle("admin.sante.sauvegarde.aucune_quoi")))
    else:
        d = derniere[0].date
        if _sauvegarde_illisible(derniere[0]):
            sortie.append(ligne_sante("sauvegarde", PANNE, constat + " " + libelle("admin.sante.sauvegarde.illisible"),
                                 libelle("admin.sante.sauvegarde.illisible_quoi"), alerte="illisible"))
        elif d > timezone.localtime() + datetime.timedelta(days=1):
            sortie.append(ligne_sante("sauvegarde", A_REGARDER, constat, libelle("admin.sante.sauvegarde.future_quoi"), alerte="future"))
        elif not auto["active"]:
            sortie.append(ligne_sante("sauvegarde", A_REGARDER, constat + " " + libelle("admin.sante.sauvegarde.auto_non"),
                                 libelle("admin.sante.sauvegarde.auto_non_quoi")))
        elif auto["en_retard"]:
            sortie.append(ligne_sante("sauvegarde", A_REGARDER, constat + " " + libelle("admin.sante.sauvegarde.retard"),
                                 libelle("admin.sante.sauvegarde.retard_quoi"), alerte="retard"))
        else:
            sortie.append(ligne_sante("sauvegarde", BON, constat))

    # copie externe des sauvegardes (copie_externe.py) : réglage de toute l'installation
    sortie.extend(_ligne_copie())

    # espace disque : le plus petit espace libre des dossiers des données, des fichiers et des sauvegardes
    disque = espace_disque()
    if disque is None:
        sortie.append(ligne_sante("disque", A_REGARDER, libelle("admin.sante.disque.illisible"), libelle("admin.sante.disque.quoi"),
                             portee=INSTALLATION))
    else:
        libre, dossier = disque
        minimum = settings.ALERTE_DISQUE_MO * 1024 * 1024
        texte = libelle("admin.sante.disque.libre", taille=SV.taille_lisible(libre))
        detail = str(dossier) if permis else ""
        if libre < minimum:
            sortie.append(ligne_sante("disque", PANNE, texte, libelle("admin.sante.disque.panne_quoi"), detail, alerte="panne",
                                 portee=INSTALLATION))
        elif libre < 10 * minimum:
            sortie.append(ligne_sante("disque", A_REGARDER, texte, libelle("admin.sante.disque.quoi"), detail, alerte="bas",
                                 portee=INSTALLATION))
        else:
            sortie.append(ligne_sante("disque", BON, texte, portee=INSTALLATION))

    # e-mail : serveur réglé (par l'IT dans le fichier de réglages, ou dans l'outil : envoi_emails), dernier envoi,
    # dernier échec ; le détail dit d'où viennent les réglages
    from . import envoi_emails as EE

    envoye, echec_email = _dernier_email()
    r = EE.reglage()
    origine = (libelle("admin.sante.email.origine_it") if r.source == EE.ENVIRONNEMENT
               else libelle("admin.sante.email.origine_outil", hote=f"{r.hote}:{r.port}")) if permis and r.actif else ""
    if not r.actif:
        sortie.append(ligne_sante("email", A_REGARDER, libelle("admin.sante.email.non"), libelle("admin.sante.email.non_quoi")))
    elif r.mot_de_passe_illisible:
        sortie.append(ligne_sante("email", A_REGARDER, libelle("admin.sante.email.mdp_illisible"),
                             libelle("admin.sante.email.mdp_illisible_quoi"), origine, alerte="mdp_illisible", portee=INSTALLATION))
    elif echec_email and (envoye is None or echec_email > envoye):
        sortie.append(ligne_sante("email", A_REGARDER, libelle("admin.sante.email.echec", quand=quand(echec_email)),
                             libelle("admin.sante.email.echec_quoi"), origine, alerte="echec"))
    else:
        constat = libelle("admin.sante.email.bon")
        constat += " " + (libelle("admin.sante.email.dernier", quand=quand(envoye)) if envoye
                          else libelle("admin.sante.email.jamais"))
        sortie.append(ligne_sante("email", BON, constat, detail=origine))

    # autorités de certification ajoutées par l'IT (EXTRA_CA_CERTS) : détail pour l'IT, et seulement s'il y en a
    if permis:
        autorites = _ligne_autorites()
        if autorites:
            sortie.append(autorites)

    # tâches de fond : une tâche planifiée arrêtée (toute l'installation), imports et gros exports bloqués, contrôle de
    # la nuit en retard ou qui a trouvé des erreurs
    arretees = taches_fond.arretees()
    bloquees = etat["background_imports"].get("stuck", 0) + etat["background_exports"].get("stuck", 0)
    controle = etat["controle_donnees"]
    messages = [etat[c]["message"] for c in ("background_imports", "background_exports") if etat[c].get("message")]
    erreurs, date_controle = (0, None) if controle.get("etat") in ("late", "never") else _erreurs_du_controle()
    if arretees:
        noms = ", ".join(libelle(f"admin.sante.taches.nom.{t}") for t in arretees)
        sortie.append(ligne_sante("taches", PANNE, libelle("admin.sante.taches.arretees", n=len(arretees), taches=noms),
                             libelle("admin.sante.taches.arretees_quoi"), ", ".join(arretees) if permis else "",
                             alerte="arretees", portee=INSTALLATION))
    elif bloquees:
        sortie.append(ligne_sante("taches", A_REGARDER, libelle("admin.sante.taches.bloquees", n=bloquees),
                             libelle("admin.sante.taches.bloquees_quoi"), "; ".join(messages) if permis else "", alerte="bloquees"))
    elif controle.get("etat") == "late":
        sortie.append(ligne_sante("taches", A_REGARDER, libelle("admin.sante.taches.controle_retard"),
                             libelle("admin.sante.taches.controle_retard_quoi"), alerte="controle_retard"))
    elif erreurs:
        sortie.append(ligne_sante("taches", A_REGARDER, libelle("admin.sante.taches.controle_erreurs", n=erreurs,
                                                           quand=quand(date_controle) if date_controle else ""),
                             libelle("admin.sante.taches.controle_erreurs_quoi"), alerte="controle_erreurs"))
    else:
        sortie.append(ligne_sante("taches", BON, libelle("admin.sante.taches.bon")))

    # migrations en attente : base de cet espace et registre commun (tous les espaces pour le détail permis)
    aliases = [ESP.COMMUN] + [ESP.declarer(c) for c in (mesure["codes"] if permis else [ici])]
    attente = _migrations_en_attente(aliases)
    if attente:
        sortie.append(ligne_sante("migrations", PANNE, libelle("admin.sante.migrations.panne"), libelle("admin.sante.migrations.quoi"),
                             ", ".join(attente) if permis else "", alerte="panne"))
    else:
        sortie.append(ligne_sante("migrations", BON, libelle("admin.sante.migrations.bon")))

    # problèmes signalés par une autre partie de l'outil (alertes.signaler) : ceux de toute l'installation et ceux des
    # espaces mesurés
    from . import alertes as AL

    sortie += AL.lignes_signalees(mesure["codes"], permis)

    # HTTPS : réglé (DJANGO_HTTPS) et reçu par cette page
    if https is None:
        pass
    elif https:
        sortie.append(ligne_sante("https", BON, libelle("admin.sante.https.bon")))
    else:
        sortie.append(ligne_sante("https", A_REGARDER, libelle("admin.sante.https.non"), libelle("admin.sante.https.quoi")))
    return sortie


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
