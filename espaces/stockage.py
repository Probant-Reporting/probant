"""Fichiers déposés (preuves, logo, imports en cours) rangés dans le dossier de l'espace courant : MEDIA_ROOT pour
l'espace principal, espaces-donnees/<code>/fichiers pour les autres (hors de MEDIA_ROOT : la sauvegarde et la
restauration du principal ne les touchent jamais)."""
import errno
import os
import uuid

from django.core.files.storage import FileSystemStorage

from . import contexte as E


class StockageEspace(FileSystemStorage):
    @property
    def base_location(self):
        return str(E.dossier_medias())

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def _save(self, name, content):
        """Écrit d'abord un fichier caché à côté (« .<nom>.<n>.part »), puis le met en place d'un coup : un dépôt
        interrompu (disque plein, arrêt brutal) ne laisse jamais de fichier tronqué sous le nom d'une preuve ; en cas
        d'erreur, le fichier caché est effacé."""
        chemin = self.path(name)
        dossier = os.path.dirname(chemin)
        os.makedirs(dossier, exist_ok=True)
        tmp = os.path.join(dossier, f".{os.path.basename(chemin)}.{uuid.uuid4().hex[:8]}.part")
        try:
            with open(tmp, "xb") as f:
                for morceau in content.chunks():
                    f.write(morceau if isinstance(morceau, bytes) else morceau.encode("utf-8"))
                f.flush()
                os.fsync(f.fileno())
            while True:
                try:
                    os.link(tmp, chemin)  # jamais d'écrasement : le nom pris par un autre dépôt en donne un autre
                    break
                except FileExistsError:
                    name = self.get_available_name(name)
                    chemin = self.path(name)
                except OSError as e:
                    if e.errno not in (errno.EPERM, errno.EXDEV, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EMLINK):
                        raise
                    if os.path.exists(chemin):  # système de fichiers sans liens : renommage, après contrôle
                        name = self.get_available_name(name)
                        chemin = self.path(name)
                        continue
                    os.replace(tmp, chemin)
                    break
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        if self.file_permissions_mode is not None:
            os.chmod(chemin, self.file_permissions_mode)
        return os.path.relpath(chemin, self.location).replace("\\", "/")
