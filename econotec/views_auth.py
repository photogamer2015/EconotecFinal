"""
Vistas de autenticación personalizadas para Econotec.

El login además de pedir usuario/contraseña, pide la SEDE en la que
trabajará el usuario durante la sesión (Guayaquil o Quito).

La sede se guarda en `request.session['sede_actual']` y queda disponible
en todas las vistas a través del context_processor `roles`.
"""
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods


SEDES_VALIDAS = {'guayaquil', 'quito'}


def _destino_seguro(request):
    """
    Devuelve la URL a la que redirigir tras el login.

    Respeta ?next= SOLO si apunta a una ruta interna del propio sitio
    (evita open-redirects). Si no hay next válido, va a la bienvenida.
    Esto es lo que permite que, al escanear el QR del equipo, el técnico
    vuelva directamente a la hoja del equipo después de iniciar sesión.
    """
    siguiente = request.POST.get('next') or request.GET.get('next') or ''
    if siguiente and url_has_allowed_host_and_scheme(
        url=siguiente,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return siguiente
    return reverse('econotec:bienvenida')


@never_cache
@require_http_methods(['GET', 'POST'])
def login_con_sede(request):
    """
    Login que además del usuario y contraseña pide la sede.
    La sede queda guardada en la sesión hasta que cierre sesión.
    """
    # Si ya está logueado y tiene sede seleccionada, mandarlo a su destino
    # (respeta ?next= para que el QR del equipo lleve a la hoja directamente).
    if request.user.is_authenticated and request.session.get('sede_actual'):
        return redirect(_destino_seguro(request))

    error = None

    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        sede = (request.POST.get('sede') or '').strip().lower()

        if sede not in SEDES_VALIDAS:
            error = 'Debes seleccionar una sede para iniciar sesión.'
        else:
            user = authenticate(request, username=username, password=password)
            if user is None:
                error = 'Usuario o contraseña incorrectos.'
            elif not user.is_active:
                error = 'Esta cuenta está inactiva. Contacta al administrador.'
            else:
                auth_login(request, user)
                request.session['sede_actual'] = sede
                # Mensaje opcional para confirmar sede
                etiqueta = 'Guayaquil' if sede == 'guayaquil' else 'Quito'
                messages.success(
                    request,
                    f'Sesión iniciada en sede {etiqueta}.'
                )
                return redirect(_destino_seguro(request))

    return render(request, 'login.html', {
        'error': error,
        'sede_seleccionada': (request.POST.get('sede') if request.method == 'POST' else ''),
        'username_previo': (request.POST.get('username') if request.method == 'POST' else ''),
        'next': request.POST.get('next') or request.GET.get('next') or '',
    })


def logout_view(request):
    """Cierra la sesión y limpia la sede."""
    auth_logout(request)
    return redirect('login')
