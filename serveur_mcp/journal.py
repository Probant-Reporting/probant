"""Appels d'outils au journal (« via MCP ») et limite de débit (docs/mcp.md, 1.6 et 1.7).

- ``commencer`` : sous verrou sur le compte, compte ses appels des 60 dernières secondes ; au-delà de la limite, refus
  (``Debit``) ; sinon l'appel est noté (``AppelMCP``) : deux appels au même moment ne prennent pas tous deux la dernière
  place, et le compte est partagé par tous les processus du serveur.
- Pendant l'appel, chaque ligne écrite dans ``collecte.Journal`` (par les fonctions habituelles : ``enregistrer``,
  ``valider``, ``traiter``, ``envoyer``) est notée (``noter_ecriture``, signal branché dans ``apps.py``).
- ``terminer`` : les lignes de l'appel reliées à lui (``JournalMCP``) : l'historique les affiche « via MCP ». Un appel
  réussi d'un outil d'écriture : une ligne « appel_mcp » au journal (personne, jeton, outil, arguments coupés, issue),
  gardée pour toujours. Une lecture ou un appel refusé : compté dans la ligne du jour de la personne (« appels_mcp »),
  mise à jour sur place, au lieu d'une ligne par appel (jusqu'à 86 400 par jour et par personne au réglage par défaut,
  qui noyaient l'historique des données) ; elle dit aussi les écritures refusées et les numéros des jetons utilisés.
  Une écriture refusée laisse en plus une ligne par personne, par jour et par outil d'écriture (« refus_mcp »), mise à
  jour sur place : nombre de refus, jetons, heure et motif du dernier refus, ses arguments (essai d'un jeton volé :
  au plus une ligne par outil d'écriture, par personne et par jour).
- Les appels notés pour le débit sont purgés au-delà de la fenêtre de 60 secondes, sauf ceux qui ont écrit.
"""
import contextvars
import datetime
import json
import re
import time
from contextlib import contextmanager

from django.utils import timezone

from collecte.models import Journal
from espaces import contexte as ESP
from parametres import libelles as LB
from referentiel.models import Utilisateur

from .models import AppelMCP, JetonMCP, JournalMCP

ARGUMENTS_MAX = 1000  # caractères des arguments notés au journal
FENETRE = datetime.timedelta(seconds=60)

_lignes = contextvars.ContextVar("mcp_lignes_journal", default=None)


class Debit(Exception):
    """Trop d'appels : ``attente`` secondes avant le prochain appel permis."""

    def __init__(self, attente):
        super().__init__(attente)
        self.attente = attente


def noter_ecriture(sender, instance, created, **kwargs):
    lignes = _lignes.get()
    if created and lignes is not None:
        lignes.append(instance.pk)


def commencer(utilisateur, jeton, outil, limite):
    """Note le début d'un appel, ou lève ``Debit`` si la personne a déjà fait ``limite`` appels en 60 secondes."""
    with ESP.atomic():
        Utilisateur.objects.select_for_update().filter(pk=utilisateur.pk).first()  # un appel de la personne à la fois ici
        depuis = timezone.now() - FENETRE
        recents = list(AppelMCP.objects.filter(utilisateur=utilisateur, date__gte=depuis).order_by("date")
                       .values_list("date", flat=True)[:limite])
        if len(recents) >= limite:
            attente = max(1, int((recents[0] + FENETRE - timezone.now()).total_seconds()) + 1)
            raise Debit(attente)
        # purge : les appels de la personne sortis de la fenêtre ne servent plus au débit (le journal garde le compte du
        # jour) ; gardés seulement ceux qui ont écrit quelque chose (leurs lignes du journal restent « via MCP »)
        AppelMCP.objects.filter(utilisateur=utilisateur, date__lt=depuis, lignes__isnull=True).delete()
        appel = AppelMCP.objects.create(utilisateur=utilisateur, jeton_id=jeton.pk, jeton_debut=jeton.debut, outil=outil[:60])
        JetonMCP.objects.filter(pk=jeton.pk).update(derniere_utilisation=timezone.now())
    return appel


@contextmanager
def suivre():
    """Pendant le bloc, note les lignes du journal écrites (numéros) ; renvoie la liste."""
    lignes = []
    jeton = _lignes.set(lignes)
    try:
        yield lignes
    finally:
        _lignes.reset(jeton)


def resume_arguments(arguments):
    try:
        texte = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        texte = str(arguments)
    return texte if len(texte) <= ARGUMENTS_MAX else texte[:ARGUMENTS_MAX - 1] + "…"


RESUME = ("lectures : {lectures} ; refus : {refus} ; dernier appel : {heure} ; écritures refusées : {ecritures} ; "
          "jetons : {jetons}")  # modèle « admin.journal.motif.appels_mcp »
_RESUME = re.compile(r"^lectures : (\d+) ; refus : (\d+) ; dernier appel : [^;]* ?(?:; écritures refusées : (\d+) ; "
                     r"jetons : ([\d, ]*))?$")
REFUS = "refus : {refus} ; jetons : {jetons} ; dernier refus : {heure} : {motif}"  # « admin.journal.motif.refus_mcp »
_REFUS = re.compile(r"^refus : (\d+) ; jetons : ([\d, ]*) ; ")
JETONS_NOTES = 20  # numéros de jetons gardés dans une ligne (10 jetons actifs par personne au plus)


def _jetons(texte, jeton):
    """Numéros des jetons d'une ligne (« 3, 5 ») avec ``jeton`` ajouté, dans l'ordre du premier usage, bornés."""
    nums = [n for n in (texte or "").replace(" ", "").split(",") if n.isdigit()]
    if jeton is not None and str(jeton.pk) not in nums:
        nums.append(str(jeton.pk))
    return ", ".join(nums[-JETONS_NOTES:])


def terminer(appel, utilisateur, jeton, arguments, statut, issue, lignes, debut, ecriture=False):
    """Fin d'un appel : marque « via MCP » des lignes écrites pendant l'appel ; au journal, une ligne « appel_mcp » pour
    un appel réussi d'un outil d'écriture (personne, jeton, outil, arguments, issue), gardée pour toujours ; sinon
    (lecture, appel refusé ou en erreur) le compte du jour de la personne (``compter``), et pour une écriture refusée,
    sa ligne du jour pour cet outil (``noter_refus_ecriture``)."""
    with ESP.atomic():
        if ecriture and statut == AppelMCP.Statut.OK:
            Journal.objects.create(utilisateur=utilisateur, action="appel_mcp", objet="JetonMCP", objet_id=str(jeton.pk),
                                   champ=appel.outil, avant=resume_arguments(arguments), apres=issue[:2000])
        else:
            ecriture_refusee = ecriture and statut == AppelMCP.Statut.REFUS
            compter(utilisateur, lecture=statut == AppelMCP.Statut.OK, jeton=jeton, ecriture_refusee=ecriture_refusee)
            if ecriture_refusee:
                noter_refus_ecriture(utilisateur, jeton, appel.outil, arguments, issue)
        existantes = set(Journal.objects.filter(pk__in=lignes).values_list("pk", flat=True)) if lignes else set()
        JournalMCP.objects.bulk_create([JournalMCP(journal_id=i, appel=appel) for i in sorted(existantes)], ignore_conflicts=True)
        AppelMCP.objects.filter(pk=appel.pk).update(statut=statut, duree_ms=min(int((time.monotonic() - debut) * 1000), 2**31 - 1))


def compter(utilisateur, lecture, jeton=None, ecriture_refusee=False):
    """Ligne du jour de la personne (action « appels_mcp », champ : la date) : nombre de lectures et d'appels refusés
    (écritures refusées comprises, et comptées aussi à part), heure du dernier appel, numéros des jetons utilisés, mise
    à jour sur place. Relue sous verrou sur le compte : deux appels au même moment ne perdent aucun compte. Dans une
    transaction (``terminer``)."""
    Utilisateur.objects.select_for_update().filter(pk=utilisateur.pk).first()
    maintenant = timezone.localtime()
    ligne = (Journal.objects.select_for_update()
             .filter(action="appels_mcp", objet="Utilisateur", objet_id=str(utilisateur.pk), champ=maintenant.date().isoformat())
             .order_by("pk").first())
    m = _RESUME.match(ligne.apres) if ligne is not None else None
    lectures, refus = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    ecritures, jetons = (int(m.group(3) or 0), m.group(4) or "") if m else (0, "")
    lectures, refus = lectures + (1 if lecture else 0), refus + (0 if lecture else 1)
    texte = RESUME.format(lectures=lectures, refus=refus, heure=f"{maintenant:%H:%M}",
                          ecritures=ecritures + (1 if ecriture_refusee else 0), jetons=_jetons(jetons, jeton))
    if ligne is None:
        Journal.objects.create(utilisateur=utilisateur, action="appels_mcp", objet="Utilisateur", objet_id=str(utilisateur.pk),
                               champ=maintenant.date().isoformat(), apres=texte)
    else:
        Journal.objects.filter(pk=ligne.pk).update(apres=texte)


def noter_refus_ecriture(utilisateur, jeton, outil, arguments, issue):
    """Ligne du jour de la personne pour un outil d'écriture refusé (action « refus_mcp », champ : l'outil) : nombre de
    refus, jetons, heure et motif du dernier refus ; ``avant`` : ses arguments (coupés, comme « appel_mcp »). Une ligne
    par personne, par jour et par outil, mise à jour sur place, sous le verrou du compte pris par ``compter``."""
    maintenant = timezone.localtime()
    debut_jour = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)
    ligne = (Journal.objects.select_for_update()
             .filter(action="refus_mcp", objet="Utilisateur", objet_id=str(utilisateur.pk), champ=outil[:60],
                     date__gte=debut_jour).order_by("pk").first())
    m = _REFUS.match(ligne.apres) if ligne is not None else None
    refus, jetons = (int(m.group(1)), m.group(2)) if m else (0, "")
    motif = issue.removeprefix("refusé : ").removeprefix("introuvable : ")
    if not motif.startswith(LB.CODE):  # motif codé (``libelles.coder``, déjà borné) : recomposé dans la langue de qui lit
        motif = " ".join(motif.split())[:500]
    texte = REFUS.format(refus=refus + 1, jetons=_jetons(jetons, jeton), heure=f"{maintenant:%H:%M}", motif=motif)
    if ligne is None:
        Journal.objects.create(utilisateur=utilisateur, action="refus_mcp", objet="Utilisateur", objet_id=str(utilisateur.pk),
                               champ=outil[:60], avant=resume_arguments(arguments), apres=texte)
    else:
        Journal.objects.filter(pk=ligne.pk).update(avant=resume_arguments(arguments), apres=texte)


def via_mcp(ids):
    """Numéros, parmi ``ids``, des lignes du journal écrites par un appel d'outil (affichées « via MCP »)."""
    ids = [int(i) for i in ids]
    sortie = set()
    for i in range(0, len(ids), 5000):  # par paquets : sous le plafond de paramètres de SQLite (export de 20 000 lignes)
        sortie |= set(JournalMCP.objects.filter(journal_id__in=ids[i:i + 5000]).values_list("journal_id", flat=True))
    return sortie
