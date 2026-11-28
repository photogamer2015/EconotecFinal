"""Roles del CRM a partir de los roles de Econotec.

  • Administrador (superusuario de Econotec)  → ve y configura todo.
  • Supervisora comercial (se marca en CRM → Usuarios y roles) → ve a todo el equipo.
  • Asesoras (incluida la Asistente de caja) → solo sus clientes, chats, actividades y seguimientos.
  • Técnicos → no entran al CRM (el botón no aparece).
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q

from econotec.permisos import GRUPOS_ASESOR_COMERCIAL, es_asesor

from .models import Perfil, Rol


def _perfil(user):
    perfil = getattr(user, "crm_perfil", None)
    if perfil is None:
        perfil, _ = Perfil.objects.get_or_create(user=user)
    return perfil


def rol_de(user):
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return Rol.ADMIN
    perfil = _perfil(user)
    if perfil.rol == Rol.GERENTE:
        return Rol.GERENTE
    if es_asesor(user):
        return Rol.EJECUTIVO
    return None


def puede_entrar(user):
    """Entran al CRM el administrador, la supervisora y las asesoras."""
    return rol_de(user) is not None


def es_admin(user):
    return rol_de(user) == Rol.ADMIN


def es_supervisor(user):
    """Admin o supervisora: ven a todo el equipo."""
    return rol_de(user) in (Rol.ADMIN, Rol.GERENTE)


def usuarios_crm():
    """Usuarios activos que pueden usar el CRM (para asignar responsables)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return (
        User.objects.filter(is_active=True)
        .filter(Q(is_superuser=True) | Q(groups__name__in=GRUPOS_ASESOR_COMERCIAL) | Q(crm_perfil__rol=Rol.GERENTE))
        .distinct()
        .order_by("first_name", "username")
    )


def asesoras_qs():
    """Asesoras que atienden clientes (no administradores)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return (
        User.objects.filter(is_active=True, is_superuser=False, groups__name__in=GRUPOS_ASESOR_COMERCIAL)
        .distinct()
        .order_by("first_name", "username")
    )


def crm_requerido(view):
    """Inicio de sesión de Econotec + rol con acceso al CRM."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not puede_entrar(request.user):
            raise PermissionDenied("Tu usuario no tiene acceso al CRM.")
        return view(request, *args, **kwargs)

    return wrapper


def rol_requerido(*roles):
    def deco(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if rol_de(request.user) not in roles:
                raise PermissionDenied("No tienes permiso para esta sección.")
            return view(request, *args, **kwargs)

        return wrapper

    return deco


def oportunidades_visibles(user, qs=None):
    from .models import Oportunidad

    qs = qs if qs is not None else Oportunidad.objects.all()
    if es_supervisor(user):
        return qs
    return qs.filter(responsable=user) if puede_entrar(user) else qs.none()


def actividades_visibles(user, qs=None):
    from .models import Actividad

    qs = qs if qs is not None else Actividad.objects.all()
    if es_supervisor(user):
        return qs
    if not puede_entrar(user):
        return qs.none()
    return qs.filter(Q(usuario=user) | Q(oportunidad__responsable=user)).distinct()


def seguimientos_visibles(user, qs=None):
    from .models import Seguimiento

    qs = qs if qs is not None else Seguimiento.objects.all()
    if es_supervisor(user):
        return qs
    return qs.filter(responsable=user) if puede_entrar(user) else qs.none()


def conversaciones_visibles(user, qs=None):
    from .models import Conversacion

    qs = qs if qs is not None else Conversacion.objects.all()
    if es_supervisor(user):
        return qs
    if not puede_entrar(user):
        return qs.none()
    return qs.filter(Q(asignado=user) | Q(contacto__oportunidades__responsable=user)).distinct()


def puede_ver_oportunidad(user, op):
    return es_supervisor(user) or (puede_entrar(user) and op.responsable_id == user.id)
