"""
Avisos dentro del CRM.

Regla general: todo cambio que haga cualquier usuario le llega a los administradores
(menos al que hizo el cambio). Además, al ejecutivo le llega lo que le afecta directamente
(un lead que le asignaron, un mensaje de su cliente, un seguimiento que le agendaron).
"""
from django.contrib.auth import get_user_model
from django.db.models import Q

from .models import Notificacion, Rol

User = get_user_model()
Tipo = Notificacion.Tipo


def nombre(u):
    if not u:
        return "El sistema"
    return u.get_full_name() or u.username


def administradores():
    return User.objects.filter(is_active=True).filter(Q(is_superuser=True) | Q(crm_perfil__rol=Rol.ADMIN)).distinct()


def _crear(destinatarios, actor, tipo, texto, url=""):
    vistos, objs = set(), []
    for d in destinatarios:
        if d is None or d.pk in vistos or (actor is not None and d.pk == actor.pk) or not d.is_active:
            continue
        vistos.add(d.pk)
        objs.append(Notificacion(destinatario=d, actor=actor, tipo=tipo, texto=texto[:400], url=url[:300]))
    Notificacion.objects.bulk_create(objs)
    return len(objs)


def notificar(actor, tipo, texto, url="", tambien=()):
    """Avisa a los administradores y, si se indica, a otros usuarios (p. ej. el responsable)."""
    return _crear(list(administradores()) + list(tambien), actor, tipo, texto, url)


def notificar_usuarios(usuarios, actor, tipo, texto, url=""):
    """Avisa solo a los usuarios indicados (sin copiar a los administradores)."""
    return _crear(usuarios, actor, tipo, texto, url)


def aviso_general(actor, texto, url=""):
    """Aviso para todo el equipo."""
    from .roles import usuarios_crm

    return _crear(usuarios_crm(), actor, Tipo.AVISO, texto, url)


def no_leidas(user):
    return Notificacion.objects.filter(destinatario=user, leida=False)
