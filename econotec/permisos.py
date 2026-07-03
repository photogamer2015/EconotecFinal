"""
Helpers de permisos para Econotec.

ROLES DEL SISTEMA:
─────────────────────────────────────────────────────────────────────────
| Rol              | Acceso                                             |
─────────────────────────────────────────────────────────────────────────
| Admin            | TODO el sistema (incl. Reg. Administrativo)        |
| Técnico          | Ingresos, Salidas, Clientes, Historial, Pagos,     |
|                  | Ranking de Técnicos                                |
| Asesor Comercial | Ingresos, Salidas, Clientes, Historial, Pagos      |
|                  | (SIN Ranking de Técnicos)                          |
─────────────────────────────────────────────────────────────────────────

Los superusuarios siempre tienen acceso total, sin importar el grupo.

Para que un usuario tenga un rol, agrégalo al grupo correspondiente
desde /admin/auth/group/. Los nombres de grupo aceptados están en
las listas GRUPOS_* abajo.
"""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


# ─────────────────────────────────────────────────────────
# Lista blanca de nombres de grupo válidos por rol
# ─────────────────────────────────────────────────────────
GRUPOS_ADMIN            = ['Administradores', 'Admin']
GRUPOS_TECNICO          = ['Tecnicos', 'Tecnico']
GRUPOS_ASESOR_COMERCIAL = ['Asesores Comerciales', 'Asesor Comercial', 'Asesores', 'Asesor']


# ─────────────────────────────────────────────────────────
# Funciones de verificación de rol
# ─────────────────────────────────────────────────────────
def es_admin(user):
    """¿Es superusuario o pertenece a un grupo Administrador?
    Los admin tienen acceso a TODO el sistema."""
    if not user.is_authenticated:
        return False
    # Solo consideramos superusuarios como administradores del sistema.
    # Esto evita que miembros del grupo 'Administradores' no-superusers
    # vean el panel administrativo o el Registro Administrativo.
    return bool(user.is_superuser)


def es_tecnico(user):
    """¿Pertenece al grupo Técnico?
    Accede a: Ingresos, Salidas, Clientes, Historial, Pagos, Ranking."""
    if not user.is_authenticated:
        return False
    return user.groups.filter(name__in=GRUPOS_TECNICO).exists()


def es_asesor(user):
    """¿Pertenece al grupo Asesor Comercial?
    Accede a: Ingresos, Salidas, Clientes, Historial, Pagos.
    NO puede ver el Ranking de Técnicos."""
    if not user.is_authenticated:
        return False
    return user.groups.filter(name__in=GRUPOS_ASESOR_COMERCIAL).exists()


# alias para compatibilidad
es_asesor_comercial = es_asesor


# ─────────────────────────────────────────────────────────
# Funciones combinadas
# ─────────────────────────────────────────────────────────
def puede_gestionar_equipos(user):
    """Puede entrar a Ingreso, Salida, Clientes e Historial.
    → Admin, Técnico o Asesor Comercial."""
    return es_admin(user) or es_tecnico(user) or es_asesor(user)


def puede_gestionar_pagos(user):
    """Puede entrar al módulo de Pagos.
    → Admin, Técnico o Asesor Comercial."""
    return es_admin(user) or es_tecnico(user) or es_asesor(user)


def puede_ver_ranking(user):
    """Puede ver el Ranking de Técnicos.
    → Solo Admin."""
    return es_admin(user)


# ─────────────────────────────────────────────────────────
# Decoradores
# ─────────────────────────────────────────────────────────
def admin_requerido(view_func):
    """Solo Administradores (o superusuarios)."""
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not es_admin(request.user):
            messages.error(
                request,
                'No tienes permiso para esta acción. '
                'Solo los administradores pueden acceder a esta sección.'
            )
            return redirect('econotec:bienvenida')
        return view_func(request, *args, **kwargs)
    return _wrapped


def tecnico_requerido(view_func):
    """Admin, Técnico o Asesor Comercial — para Ingresos, Salidas, Clientes, Historial, Pagos."""
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not puede_gestionar_equipos(request.user):
            messages.error(
                request,
                'No tienes permiso para acceder a esta sección. '
                'Pide a un administrador que te asigne un rol.'
            )
            return redirect('econotec:bienvenida')
        return view_func(request, *args, **kwargs)
    return _wrapped


def asesor_requerido(view_func):
    """Admin, Técnico o Asesor Comercial — para el módulo de Pagos."""
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not puede_gestionar_pagos(request.user):
            messages.error(
                request,
                'No tienes permiso para gestionar pagos. '
                'Pide a un administrador que te asigne un rol.'
            )
            return redirect('econotec:bienvenida')
        return view_func(request, *args, **kwargs)
    return _wrapped


def ranking_requerido(view_func):
    """Solo Admin y Técnico — para el Ranking de Técnicos."""
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not puede_ver_ranking(request.user):
            messages.error(
                request,
                'No tienes permiso para ver el Ranking de Técnicos.'
            )
            return redirect('econotec:bienvenida')
        return view_func(request, *args, **kwargs)
    return _wrapped
