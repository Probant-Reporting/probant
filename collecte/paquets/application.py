"""Paquet référentiel : application des choix de l'aperçu (import)."""
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db.models import Max
from django.utils import timezone

from parametres import langues as L
from parametres.libelles import libelle as texte_libelle
from parametres.models import Langue
from referentiel.echange import enregistrer_descriptions, reconstruire_toutes_dependances
from referentiel.models import KPI, ElementReferentiel, Frequence, Referentiel, Theme

from .. import dates_courtes as DC
from .. import fichiers as X
from ..statistiques_postgresql import statistiques_a_jour
from ..models import Journal
from espaces import contexte as ESP

from .modele import PaquetInvalide
from .bibliotheque_json import comparer_versions
from .excel_ecriture import CHAMPS_REFERENTIEL
from .analyse_outils import _etiq, _poser_textes, _uuid, poser_ajouts, poser_ajouts_type_reponse


# ================================================================= application
@dataclass
class Resultat:
    referentiel: object = None
    kpis_crees: int = 0
    kpis_modifies: int = 0
    elements: int = 0
    retires: int = 0
    themes: int = 0
    reglages: int = 0
    regles: int = 0
    langues: int = 0
    campagnes: list = field(default_factory=list)


def appliquer(utilisateur, a, nom_source="", sans_recalcul=False):
    """Enregistre l'aperçu ``a`` (analysé juste avant, avec les choix). Renvoie un Resultat. Les campagnes non clôturées sont
    ensuite recalculées et contrôlées ; ``sans_recalcul`` (démo : onze modèles installés sans aucune campagne qui les demande)
    saute cette étape, qui ne changerait rien."""
    if a.erreur:
        raise PaquetInvalide(a.erreur)
    with L.session(), ESP.atomic():
        res = _appliquer(utilisateur, a, nom_source)
    if not sans_recalcul and (res.kpis_crees or res.kpis_modifies or res.elements or res.retires):
        from ..calcul import recalculer
        from ..coherence import controler
        from ..models import Campagne

        faites = set()
        for camp in Campagne.objects.exclude(statut=Campagne.Statut.CLOTUREE).select_related("referentiel", "periode"):
            if camp.periode_id not in faites:
                recalculer(camp)
                faites.add(camp.periode_id)
            controler(camp)
            res.campagnes.append(camp.nom_complet)
    return res


def _appliquer(utilisateur, a, nom_source):
    res = Resultat()
    ordre = Langue.objects.aggregate(m=Max("ordre"))["m"] or 0
    for code, libelle in a.langues_creees:
        ordre += 1
        Langue.objects.create(code=code, libelle=libelle, ordre=ordre, active=False)
        res.langues += 1
    for r in a.reglages_crees:
        r.objet.save()
        res.reglages += 1
    _appliquer_ajouts_reglages(a)
    ref = themes = None
    if a.mode != "catalogue":
        ref = res.referentiel = _appliquer_referentiel(utilisateur, a, nom_source)
        themes = _appliquer_themes(a, ref, res)
    _appliquer_kpis(utilisateur, a, ref, res)
    reconstruire_toutes_dependances()
    if ref is not None:
        _appliquer_elements(utilisateur, a, ref, themes, res)
        _poser_depuis(utilisateur, a, ref)
    for r in a.regles_a_ecrire:
        r["objet"].save()
        res.regles += 1
    if ref is not None:
        champs = ["mis_a_jour_le"]
        if a.mode == "mise_a_jour" and comparer_versions(a.paquet.version, ref.version) != 0:
            Journal.ecrire(utilisateur, "reglage_referentiels", ref, "version", ref.version, a.paquet.version)
            ref.version = a.paquet.version
            champs.append("version")
        ref.mis_a_jour_le = timezone.now()  # installé ou mis à jour depuis la bibliothèque ou un fichier
        ref.save(update_fields=champs)
        Journal.ecrire(utilisateur, "import_paquet", ref, "fichier référentiel", "", (
            f"{nom_source or a.source} : {res.kpis_crees} KPI créés, {res.kpis_modifies} modifiés, {res.elements} places, "
            f"{res.themes} thèmes, {res.reglages} réglages, {res.regles} règles" + (f", {res.retires} retirés" if res.retires else "")))
    # PostgreSQL : ANALYZE après la validation (onze modèles ESRS : des centaines de KPI, descriptions et places sur des
    # tables presque vides ; test : collecte/test_statistiques_a_jour_bibliotheque_postgresql.py)
    statistiques_a_jour()
    return res


def _appliquer_referentiel(utilisateur, a, nom_source):
    p, lg, rd = a.paquet, a.paquet.langue_reference, a.paquet.referentiel
    origine = Referentiel.Origine.FOURNI if a.fourni else Referentiel.Origine.IMPORTE
    # dans la langue de la personne qui importe, date courte de cette langue (avant : en français, jj/mm/aaaa en dur)
    fichier, jour = nom_source or a.source, DC.date_courte(timezone.localdate())
    provenance = (texte_libelle("referentiels.provenance.bibliotheque", nom=p.nom(lg)) if a.fourni else
                  texte_libelle("referentiels.provenance.fichier_de", fichier=fichier, origine=p.exporte_de, date=jour) if p.exporte_de
                  else texte_libelle("referentiels.provenance.fichier", fichier=fichier, date=jour))[:200]
    if a.mode == "nouveau":
        identifiant = _uuid(rd.get("identifiant"))
        if identifiant is None or Referentiel.objects.filter(identifiant=identifiant).exists():
            import uuid

            identifiant = uuid.uuid4()
        ref = Referentiel(code=a.code, identifiant=identifiant, couleur=rd["couleur"], frequence=rd.get("frequence") or Frequence.ANNEE,
                          mois_debut=int(rd.get("mois_debut") or 1), comparaison=rd.get("comparaison") or Referentiel.Comparaison.N1,
                          version=X.texte(rd.get("version")) or "1.0", date_version=rd.get("date_version") or None,
                          origine=origine, provenance=provenance,
                          ordre=(Referentiel.objects.aggregate(m=Max("ordre"))["m"] or 0) + 1)
        _poser_textes(ref, "nom", rd.get("nom"), lg)
        _poser_textes(ref, "description", rd.get("description"), lg)
        ref.nom = ref.nom[:150]
        ref.save()
        Journal.ecrire(utilisateur, "reglage_referentiels", ref, "référentiel", "", f"{ref.nom} ({ref.code}) importé, version {ref.version}")
        return ref
    ref = a.existant
    if a.referentiel_differences:
        for cle, libelle, genre in CHAMPS_REFERENTIEL:
            if cle in ("code", "identifiant", "origine") or (cle == "nom" and a.fourni):
                continue
            if genre == "textes":
                _poser_textes(ref, cle, rd.get(cle), lg)
            elif any(d[0] == _etiq(cle) for d in a.referentiel_differences):
                setattr(ref, cle, int(rd[cle]) if cle == "mois_debut" else rd[cle])
        ref.nom = ref.nom[:150]
        if ref.origine != Referentiel.Origine.CREE:
            ref.provenance = provenance
        ref.save()
        for lib, avant, apres in a.referentiel_differences:
            Journal.ecrire(utilisateur, "reglage_referentiels", ref, lib[:60], avant, apres)
    return ref


def _appliquer_themes(a, ref, res):
    """Thèmes créés ou modifiés, puis rattachés à leur parent ; {code: thème}."""
    lg = a.paquet.langue_reference
    themes = {t.code: t for t in Theme.objects.filter(referentiel=ref)}
    for t in a.themes:
        d, obj = t["donnees"], themes.get(t["code"])
        if t["statut"] == "inchange" and obj is not None:
            continue
        obj = obj or Theme(referentiel=ref, code=t["code"], nom="")
        _poser_textes(obj, "nom", d.get("nom"), lg)
        obj.nom = (obj.nom or t["code"])[:150]
        obj.ordre = int(d["ordre"]) if d.get("ordre") not in (None, "") else obj.ordre
        if obj.pk is None:
            obj.parent = None
        obj.save()
        themes[t["code"]] = obj
        res.themes += 1
    for t in a.themes:
        obj, parent = themes[t["code"]], themes.get(t["parent"]) if t["parent"] else None
        if obj.parent_id != (parent.pk if parent else None):
            obj.parent = parent
            obj.save(update_fields=["parent"])
    return themes


def _appliquer_kpis(utilisateur, a, ref, res):
    for l in a.kpis:
        if l.ajouts and l.local is not None and l.choix in ("reutiliser", "garder"):
            _appliquer_ajouts(l)
        if not l.ecrit or l.cible is None:
            continue
        k = l.cible
        super(KPI, k).save()  # dépendances reconstruites une seule fois ensuite
        for lg_d, textes in l.descriptions.items():
            enregistrer_descriptions(k, textes, lg_d)
        if l.choix in ("creer", "renommer"):
            res.kpis_crees += 1
            Journal.ecrire(utilisateur, "reglage_kpi", k, "KPI", "", f"créé par l'import du fichier « {a.paquet.nom()} »")
        else:
            res.kpis_modifies += 1
            for lib, avant, apres in l.diff_kpi:
                Journal.ecrire(utilisateur, "reglage_kpi", k, lib[:60], avant, apres)


def _appliquer_ajouts_reglages(a):
    """Types de réponse repris d'un autre modèle de la bibliothèque : textes ajoutés (``ajouts_type_reponse``), écriture
    directe, sans rien remplacer."""
    from parametres.models import TypeReponse

    types = {t["code"]: t for t in a.paquet.types_reponse}
    for r in a.reglages:
        if r.action != "repris" or not r.ajouts or r.genre != "type_reponse":
            continue
        local = TypeReponse.objects.filter(code=r.code_local).first()
        if local is None:
            continue
        poser_ajouts_type_reponse(local, r.ajouts, types.get(r.code) or {})
        TypeReponse.objects.filter(pk=local.pk).update(libelle=local.libelle, traductions=local.traductions, colonnes=local.colonnes)


def _appliquer_ajouts(l):
    """Nom qu'un modèle de la bibliothèque ajoute à un KPI déjà installé (``analyse_kpis._ajouts_fournis``) : écriture
    directe du texte, sans recalcul (la définition du KPI ne change pas)."""
    k = l.local
    if l.ajouts.get("libelle"):
        poser_ajouts(k, "libelle", l.ajouts["libelle"], l.donnees.get("libelle"), L.reference())
        k.libelle = k.libelle[:300]
        KPI.objects.filter(pk=k.pk).update(libelle=k.libelle, traductions=k.traductions)


def _poser_depuis(utilisateur, a, ref):
    """KPI nouveaux dans le référentiel : « demandé depuis » choisi dans l'aperçu (``a.depuis`` ; vide : la période en
    cours, déjà posée à la création), avec l'historique de ``demande_depuis.changer``."""
    valeur, codes = getattr(a, "depuis", ""), getattr(a, "elements_crees", [])
    if not valeur or not codes:
        return
    from ..demande_depuis import changer, lire_choix

    try:
        changer(utilisateur, ref, codes, lire_choix(ref, valeur))
    except ValidationError as e:
        raise PaquetInvalide(" ".join(e.messages))


def _appliquer_elements(utilisateur, a, ref, themes, res):
    """Place des KPI dans le référentiel ; KPI absents de la nouvelle version retirés si on l'a demandé."""
    lg = a.paquet.langue_reference
    existants = {e.kpi_id: e for e in ElementReferentiel.objects.filter(referentiel=ref)}
    a.elements_crees = []
    for l in a.kpis:
        if not l.place or l.element is None or l.choix == "garder":
            continue
        e, el = existants.get(l.code_final), l.element
        theme = themes.get(el["theme"]) if el["theme"] else None
        if e is None:
            e = ElementReferentiel(referentiel=ref, kpi_id=l.code_final)
            a.elements_crees.append(l.code_final)
        elif not l.diff_place:
            continue
        e.theme, e.ordre, e.obligatoire = theme, el["ordre"], el["obligatoire"]
        _poser_textes(e, "libelle", el["libelle"], lg)
        e.libelle = e.libelle[:300]
        e.save()
        res.elements += 1
    if a.retirer_absents:
        for e in a.retires:
            Journal.ecrire(utilisateur, "reglage_kpi", e.kpi, "Référentiel", f"{ref}", "(retiré : absent de la nouvelle version)")
            e.delete()
            res.retires += 1
