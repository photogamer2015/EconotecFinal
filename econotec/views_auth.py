"""
Vistas de autenticación personalizadas para Econotec.

El login además de pedir usuario/contraseña, pide la SEDE en la que
trabajará el usuario durante la sesión (Guayaquil o Quito).

La sede se guarda en `request.session['sede_actual']` y queda disponible
en todas las vistas a través del context_processor `roles`.
"""
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.html import escape
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods


SEDES_VALIDAS = {'guayaquil', 'quito'}
CAPTCHA_SESSION_KEY = 'login_captcha_answer'
LOGIN_2FA_SESSION_KEY = 'login_2fa_pending'
LOGIN_EMAIL_SETUP_SESSION_KEY = 'login_email_setup_pending'
LOGIN_2FA_EXPIRACION_MINUTOS = 10
LOGIN_2FA_MAX_INTENTOS = 10
EMAIL_COLOR_PRINCIPAL = '#f97618'
EMAIL_COLOR_PRINCIPAL_OSCURO = '#d7642f'
EMAIL_COLOR_FONDO = '#f4ece8'
EMAIL_COLOR_TARJETA = '#fff8f3'
EMAIL_COLOR_TEXTO = '#1f2937'
EMAIL_COLOR_TEXTO_SUAVE = '#6b7280'
EMAIL_COLOR_BORDE = '#ead8d1'


def _nuevo_captcha_login(request):
    """Genera una suma simple y guarda la respuesta esperada en la sesión."""
    numero_a = secrets.randbelow(9) + 1
    numero_b = secrets.randbelow(9) + 1
    request.session[CAPTCHA_SESSION_KEY] = numero_a + numero_b
    return {
        'captcha_numero_a': numero_a,
        'captcha_numero_b': numero_b,
    }


def _captcha_login_valido(request):
    esperado = request.session.get(CAPTCHA_SESSION_KEY)
    respuesta = (request.POST.get('captcha_respuesta') or '').strip()

    if esperado is None or not respuesta:
        return False

    try:
        return int(respuesta) == int(esperado)
    except (TypeError, ValueError):
        return False


def _generar_codigo_2fa():
    return f'{secrets.randbelow(1000000):06d}'


def _hash_codigo_2fa(codigo):
    return salted_hmac('econotec.login_2fa', codigo).hexdigest()


def _email_enmascarado(email):
    if not email or '@' not in email:
        return ''

    usuario, dominio = email.split('@', 1)
    if len(usuario) <= 2:
        usuario_visible = usuario[:1] + '*'
    else:
        usuario_visible = usuario[:2] + '*' * max(2, len(usuario) - 2)
    return f'{usuario_visible}@{dominio}'


def _email_en_modo_consola():
    return settings.EMAIL_BACKEND == 'django.core.mail.backends.console.EmailBackend'


def _mensaje_codigo_2fa(email, reenviado=False):
    email_destino = _email_enmascarado(email)
    if _email_en_modo_consola():
        return f'Modo desarrollo: el código está en la terminal del servidor. Destino: {email_destino}.'

    prefijo = 'Enviamos un nuevo código' if reenviado else 'Enviamos un código de verificación'
    return f'{prefijo} a {email_destino}.'


def _mensaje_codigo_registro_correo(email):
    email_destino = _email_enmascarado(email)
    if _email_en_modo_consola():
        return f'Modo desarrollo: el código está en la terminal del servidor. Destino: {email_destino}.'

    return f'Enviamos un código a {email_destino} para confirmar el correo.'


def _mensaje_intentos_restantes(restantes):
    etiqueta = 'intento' if restantes == 1 else 'intentos'
    return f'Código incorrecto. Te quedan {restantes} {etiqueta}.'


def _mensaje_codigo_email_texto(user, linea_codigo, codigo, aviso_seguridad):
    return (
        f'Hola {user.get_username()},\n\n'
        f'{linea_codigo} {codigo}\n\n'
        f'Este código vence en {LOGIN_2FA_EXPIRACION_MINUTOS} minutos. '
        f'{aviso_seguridad}'
    )


def _mensaje_codigo_email_html(user, titulo, etiqueta, linea_codigo, codigo, aviso_seguridad):
    usuario = escape(user.get_username())
    titulo = escape(titulo)
    etiqueta = escape(etiqueta)
    linea_codigo = escape(linea_codigo)
    codigo = escape(codigo)
    aviso_seguridad = escape(aviso_seguridad)

    return f"""<!doctype html>
<html lang="es">
  <body style="margin:0;padding:0;background:{EMAIL_COLOR_FONDO};font-family:Arial,Helvetica,sans-serif;color:{EMAIL_COLOR_TEXTO};">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
      Tu código Econotec vence en {LOGIN_2FA_EXPIRACION_MINUTOS} minutos.
    </div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{EMAIL_COLOR_FONDO};padding:28px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;background:{EMAIL_COLOR_TARJETA};border:1px solid {EMAIL_COLOR_BORDE};border-radius:18px;overflow:hidden;box-shadow:0 14px 35px rgba(31,41,55,0.10);">
            <tr>
              <td style="background:{EMAIL_COLOR_TEXTO};padding:26px 30px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td style="vertical-align:middle;">
                      <div style="display:inline-block;width:44px;height:44px;line-height:44px;border-radius:14px;background:{EMAIL_COLOR_PRINCIPAL};color:#ffffff;text-align:center;font-weight:800;font-size:24px;margin-right:12px;">E</div>
                      <span style="color:#ffffff;font-size:24px;font-weight:800;vertical-align:middle;">Econotec</span>
                    </td>
                    <td align="right" style="vertical-align:middle;">
                      <span style="display:inline-block;background:rgba(249,118,24,0.14);border:1px solid rgba(249,118,24,0.45);color:#ffd9c2;border-radius:999px;padding:8px 12px;font-size:13px;font-weight:700;">{etiqueta}</span>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:32px 30px 10px 30px;">
                <p style="margin:0 0 10px 0;color:{EMAIL_COLOR_TEXTO_SUAVE};font-size:15px;font-weight:700;text-transform:uppercase;letter-spacing:0;">Verificación segura</p>
                <h1 style="margin:0;color:{EMAIL_COLOR_TEXTO};font-size:28px;line-height:1.25;font-weight:800;">{titulo}</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:8px 30px 0 30px;">
                <p style="margin:0 0 18px 0;color:{EMAIL_COLOR_TEXTO};font-size:18px;line-height:1.55;">Hola <strong>{usuario}</strong>,</p>
                <p style="margin:0;color:{EMAIL_COLOR_TEXTO_SUAVE};font-size:17px;line-height:1.55;">{linea_codigo}</p>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 30px;">
                <div style="background:#ffffff;border:2px solid {EMAIL_COLOR_PRINCIPAL};border-radius:16px;padding:24px;text-align:center;">
                  <div style="color:{EMAIL_COLOR_PRINCIPAL_OSCURO};font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:0;margin-bottom:10px;">Código de verificación</div>
                  <div style="color:{EMAIL_COLOR_TEXTO};font-size:38px;line-height:1;font-weight:900;letter-spacing:8px;font-family:'Courier New',Courier,monospace;">{codigo}</div>
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:0 30px 30px 30px;">
                <div style="background:#fff1e8;border:1px solid #ffd1b8;border-radius:14px;padding:16px 18px;color:{EMAIL_COLOR_TEXTO};font-size:16px;line-height:1.5;">
                  <strong style="color:{EMAIL_COLOR_PRINCIPAL_OSCURO};">Vence en {LOGIN_2FA_EXPIRACION_MINUTOS} minutos.</strong>
                  {aviso_seguridad}
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 30px;background:#ffffff;border-top:1px solid {EMAIL_COLOR_BORDE};">
                <p style="margin:0;color:{EMAIL_COLOR_TEXTO_SUAVE};font-size:13px;line-height:1.55;">
                  Este mensaje fue enviado automáticamente por Econotec. Por seguridad, no compartas este código con nadie.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def _enviar_codigo_2fa(user, codigo):
    linea_codigo = 'Tu código de verificación para ingresar a Econotec es:'
    aviso_seguridad = 'Si no intentaste iniciar sesión, ignora este correo.'
    send_mail(
        subject='Código de acceso Econotec',
        message=_mensaje_codigo_email_texto(user, linea_codigo, codigo, aviso_seguridad),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
        html_message=_mensaje_codigo_email_html(
            user,
            'Código de acceso',
            'Acceso seguro',
            linea_codigo,
            codigo,
            aviso_seguridad,
        ),
    )


def _enviar_codigo_registro_correo(user, email, codigo):
    linea_codigo = 'Tu código para registrar este correo en Econotec es:'
    aviso_seguridad = 'Si no intentaste registrar este correo, ignora este mensaje.'
    send_mail(
        subject='Verifica tu correo Econotec',
        message=_mensaje_codigo_email_texto(user, linea_codigo, codigo, aviso_seguridad),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
        html_message=_mensaje_codigo_email_html(
            user,
            'Verifica tu correo',
            'Registrar correo',
            linea_codigo,
            codigo,
            aviso_seguridad,
        ),
    )


def _iniciar_doble_factor(request, user, sede, destino):
    codigo = _generar_codigo_2fa()
    vence_en = timezone.now() + timedelta(minutes=LOGIN_2FA_EXPIRACION_MINUTOS)

    request.session.pop(LOGIN_EMAIL_SETUP_SESSION_KEY, None)
    request.session[LOGIN_2FA_SESSION_KEY] = {
        'user_id': user.pk,
        'sede': sede,
        'next': destino,
        'codigo_hash': _hash_codigo_2fa(codigo),
        'vence_en': vence_en.isoformat(),
        'intentos': 0,
        'email': user.email,
    }
    _enviar_codigo_2fa(user, codigo)


def _iniciar_registro_correo(request, user, sede, destino):
    request.session.pop(LOGIN_2FA_SESSION_KEY, None)
    request.session[LOGIN_EMAIL_SETUP_SESSION_KEY] = {
        'user_id': user.pk,
        'sede': sede,
        'next': destino,
        'email': '',
        'codigo_hash': '',
        'vence_en': '',
        'intentos': 0,
    }


def _guardar_codigo_registro_correo(request, pendiente, user, email):
    codigo = _generar_codigo_2fa()
    vence_en = timezone.now() + timedelta(minutes=LOGIN_2FA_EXPIRACION_MINUTOS)
    pendiente.update({
        'email': email,
        'codigo_hash': _hash_codigo_2fa(codigo),
        'vence_en': vence_en.isoformat(),
        'intentos': 0,
    })
    request.session[LOGIN_EMAIL_SETUP_SESSION_KEY] = pendiente
    _enviar_codigo_registro_correo(user, email, codigo)


def _codigo_pendiente_vencido(pendiente):
    vence_en = pendiente.get('vence_en') or ''
    if not vence_en:
        return True

    vence_en = timezone.datetime.fromisoformat(vence_en)
    if timezone.is_naive(vence_en):
        vence_en = timezone.make_aware(vence_en, timezone.get_current_timezone())
    return timezone.now() > vence_en


def _normalizar_email(email):
    return (email or '').strip().lower()


def _validar_email_para_usuario(user, email):
    email = _normalizar_email(email)
    try:
        validate_email(email)
    except ValidationError:
        return email, 'Ingresa un correo válido.'

    User = get_user_model()
    if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
        return email, 'Ese correo ya está registrado en otro usuario.'

    return email, None


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

        if not _captcha_login_valido(request):
            error = 'Resuelve correctamente la suma de seguridad.'
        else:
            request.session.pop(CAPTCHA_SESSION_KEY, None)
            if sede not in SEDES_VALIDAS:
                error = 'Debes seleccionar una sede para iniciar sesión.'
            else:
                user = authenticate(request, username=username, password=password)
                if user is None:
                    error = 'Usuario o contraseña incorrectos.'
                elif not user.is_active:
                    error = 'Esta cuenta está inactiva. Contacta al administrador.'
                elif not user.email:
                    _iniciar_registro_correo(request, user, sede, _destino_seguro(request))
                    messages.success(
                        request,
                        'Registra tu correo una sola vez para activar el doble factor.'
                    )
                    return redirect('login_registrar_correo')
                else:
                    try:
                        _iniciar_doble_factor(request, user, sede, _destino_seguro(request))
                    except Exception:
                        request.session.pop(LOGIN_2FA_SESSION_KEY, None)
                        error = 'No se pudo enviar el código al correo. Intenta nuevamente o contacta al administrador.'
                    else:
                        messages.success(
                            request,
                            _mensaje_codigo_2fa(user.email)
                        )
                        return redirect('login_2fa')

    contexto_captcha = _nuevo_captcha_login(request)

    return render(request, 'login.html', {
        'error': error,
        'sede_seleccionada': (request.POST.get('sede') if request.method == 'POST' else ''),
        'username_previo': (request.POST.get('username') if request.method == 'POST' else ''),
        'next': request.POST.get('next') or request.GET.get('next') or '',
        **contexto_captcha,
    })


def logout_view(request):
    """Cierra la sesión y limpia la sede."""
    auth_logout(request)
    return redirect('login')


@never_cache
@require_http_methods(['GET', 'POST'])
def registrar_correo_doble_factor(request):
    """
    Permite registrar el correo una sola vez cuando el usuario aún no tiene uno.
    El correo se guarda solo después de verificar un código enviado ahí.
    """
    if request.user.is_authenticated and request.session.get('sede_actual'):
        return redirect(_destino_seguro(request))

    pendiente = request.session.get(LOGIN_EMAIL_SETUP_SESSION_KEY)
    if not pendiente:
        messages.error(request, 'Primero ingresa usuario, contraseña, sede y captcha.')
        return redirect('login')

    User = get_user_model()
    try:
        user = User.objects.get(pk=pendiente.get('user_id'), is_active=True)
    except User.DoesNotExist:
        request.session.pop(LOGIN_EMAIL_SETUP_SESSION_KEY, None)
        messages.error(request, 'No se pudo continuar. Inicia sesión nuevamente.')
        return redirect('login')

    if user.email:
        try:
            _iniciar_doble_factor(
                request,
                user,
                pendiente['sede'],
                pendiente.get('next') or reverse('econotec:bienvenida'),
            )
        except Exception:
            messages.error(request, 'No se pudo enviar el código al correo. Intenta nuevamente.')
            return redirect('login')

        messages.success(
            request,
            _mensaje_codigo_2fa(user.email)
        )
        return redirect('login_2fa')

    error = None

    if request.method == 'POST':
        accion = request.POST.get('accion') or 'enviar_codigo'

        if accion == 'cambiar':
            pendiente.update({
                'email': '',
                'codigo_hash': '',
                'vence_en': '',
                'intentos': 0,
            })
            request.session[LOGIN_EMAIL_SETUP_SESSION_KEY] = pendiente
            return redirect('login_registrar_correo')

        if accion in {'enviar_codigo', 'reenviar'}:
            email_post = pendiente.get('email') if accion == 'reenviar' else request.POST.get('email')
            email_confirmacion = (
                pendiente.get('email')
                if accion == 'reenviar'
                else request.POST.get('email_confirmacion')
            )
            email, error = _validar_email_para_usuario(user, email_post)

            if not error and _normalizar_email(email_confirmacion) != email:
                error = 'Los correos no coinciden.'

            if not error:
                try:
                    _guardar_codigo_registro_correo(request, pendiente, user, email)
                except Exception:
                    error = 'No se pudo enviar el código a ese correo. Revisa el correo e intenta nuevamente.'
                else:
                    messages.success(
                        request,
                        _mensaje_codigo_registro_correo(email)
                    )
                    return redirect('login_registrar_correo')

        elif accion == 'verificar':
            if not pendiente.get('codigo_hash') or not pendiente.get('email'):
                error = 'Primero registra un correo para recibir el código.'
            elif _codigo_pendiente_vencido(pendiente):
                request.session.pop(LOGIN_EMAIL_SETUP_SESSION_KEY, None)
                messages.error(request, 'El código venció. Inicia sesión nuevamente para recibir otro.')
                return redirect('login')
            else:
                codigo = (request.POST.get('codigo') or '').strip()
                intentos = int(pendiente.get('intentos') or 0) + 1
                pendiente['intentos'] = intentos
                request.session[LOGIN_EMAIL_SETUP_SESSION_KEY] = pendiente

                codigo_ok = (
                    len(codigo) == 6
                    and codigo.isdigit()
                    and constant_time_compare(
                        _hash_codigo_2fa(codigo),
                        pendiente.get('codigo_hash') or '',
                    )
                )

                if codigo_ok:
                    user.email = pendiente['email']
                    user.save(update_fields=['email'])
                    sede = pendiente['sede']
                    destino = pendiente.get('next') or reverse('econotec:bienvenida')
                    request.session.pop(LOGIN_EMAIL_SETUP_SESSION_KEY, None)
                    auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                    request.session['sede_actual'] = sede
                    etiqueta = 'Guayaquil' if sede == 'guayaquil' else 'Quito'
                    messages.success(
                        request,
                        f'Correo registrado y sesión iniciada en sede {etiqueta}.'
                    )
                    return redirect(destino)

                if intentos >= LOGIN_2FA_MAX_INTENTOS:
                    request.session.pop(LOGIN_EMAIL_SETUP_SESSION_KEY, None)
                    messages.error(request, 'Demasiados intentos incorrectos. Inicia sesión nuevamente.')
                    return redirect('login')

                restantes = LOGIN_2FA_MAX_INTENTOS - intentos
                error = _mensaje_intentos_restantes(restantes)

    return render(request, 'login_registrar_correo.html', {
        'error': error,
        'email_propuesto': pendiente.get('email') or '',
        'email_enmascarado': _email_enmascarado(pendiente.get('email') or ''),
        'codigo_enviado': bool(pendiente.get('codigo_hash')),
        'expiracion_minutos': LOGIN_2FA_EXPIRACION_MINUTOS,
        'max_intentos': LOGIN_2FA_MAX_INTENTOS,
    })


@never_cache
@require_http_methods(['GET', 'POST'])
def verificar_doble_factor(request):
    """
    Verifica el código enviado por correo antes de abrir la sesión definitiva.
    """
    if request.user.is_authenticated and request.session.get('sede_actual'):
        return redirect(_destino_seguro(request))

    pendiente = request.session.get(LOGIN_2FA_SESSION_KEY)
    if not pendiente:
        messages.error(request, 'Primero ingresa usuario, contraseña, sede y captcha.')
        return redirect('login')

    User = get_user_model()
    try:
        user = User.objects.get(pk=pendiente.get('user_id'), is_active=True)
    except User.DoesNotExist:
        request.session.pop(LOGIN_2FA_SESSION_KEY, None)
        messages.error(request, 'No se pudo continuar con la verificación. Inicia sesión nuevamente.')
        return redirect('login')

    vence_en = timezone.datetime.fromisoformat(pendiente['vence_en'])
    if timezone.is_naive(vence_en):
        vence_en = timezone.make_aware(vence_en, timezone.get_current_timezone())

    if timezone.now() > vence_en:
        request.session.pop(LOGIN_2FA_SESSION_KEY, None)
        messages.error(request, 'El código venció. Inicia sesión nuevamente para recibir otro.')
        return redirect('login')

    error = None

    if request.method == 'POST':
        accion = request.POST.get('accion') or 'verificar'

        if accion == 'reenviar':
            try:
                _iniciar_doble_factor(
                    request,
                    user,
                    pendiente['sede'],
                    pendiente.get('next') or reverse('econotec:bienvenida'),
                )
            except Exception:
                error = 'No se pudo reenviar el código. Intenta nuevamente.'
            else:
                messages.success(
                    request,
                    _mensaje_codigo_2fa(user.email, reenviado=True)
                )
                return redirect('login_2fa')
        else:
            codigo = (request.POST.get('codigo') or '').strip()
            intentos = int(pendiente.get('intentos') or 0) + 1
            pendiente['intentos'] = intentos
            request.session[LOGIN_2FA_SESSION_KEY] = pendiente

            codigo_ok = (
                len(codigo) == 6
                and codigo.isdigit()
                and constant_time_compare(
                    _hash_codigo_2fa(codigo),
                    pendiente.get('codigo_hash') or '',
                )
            )

            if codigo_ok:
                sede = pendiente['sede']
                destino = pendiente.get('next') or reverse('econotec:bienvenida')
                request.session.pop(LOGIN_2FA_SESSION_KEY, None)
                auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                request.session['sede_actual'] = sede
                etiqueta = 'Guayaquil' if sede == 'guayaquil' else 'Quito'
                messages.success(request, f'Sesión iniciada en sede {etiqueta}.')
                return redirect(destino)

            if intentos >= LOGIN_2FA_MAX_INTENTOS:
                request.session.pop(LOGIN_2FA_SESSION_KEY, None)
                messages.error(request, 'Demasiados intentos incorrectos. Inicia sesión nuevamente.')
                return redirect('login')

            restantes = LOGIN_2FA_MAX_INTENTOS - intentos
            error = _mensaje_intentos_restantes(restantes)

    return render(request, 'login_2fa.html', {
        'error': error,
        'email_enmascarado': _email_enmascarado(pendiente.get('email') or user.email),
        'expiracion_minutos': LOGIN_2FA_EXPIRACION_MINUTOS,
        'max_intentos': LOGIN_2FA_MAX_INTENTOS,
    })
