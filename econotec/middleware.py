from django.utils import timezone
from .models import UsuarioActividad
from datetime import timedelta

class ActividadUsuarioMiddleware:
    """
    Middleware para rastrear la última conexión de los usuarios.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # get_or_create es seguro aquí
            actividad, created = UsuarioActividad.objects.get_or_create(user=request.user)
            
            # Solo actualizar la BD si pasó al menos 1 minuto desde la última vez,
            # para no saturar la base de datos en cada click.
            if created or (timezone.now() - actividad.ultima_conexion) > timedelta(minutes=1):
                actividad.ultima_conexion = timezone.now()
                actividad.save(update_fields=['ultima_conexion'])
        
        response = self.get_response(request)
        return response


class RespuestasPrivadasMiddleware:
    """Evita almacenar páginas y APIs autenticadas, incluido el cierre de sesión."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.utils.cache import add_never_cache_headers
        privada = request.user.is_authenticated
        if privada:
            from django.conf import settings
            from django.contrib.auth import logout
            ahora = timezone.now().timestamp()
            limite = request.session.get('_econotec_session_deadline')
            if limite is None:
                request.session['_econotec_session_deadline'] = ahora + settings.SESSION_COOKIE_AGE
            elif not isinstance(limite, (int, float)) or ahora >= limite:
                logout(request)
        response = self.get_response(request)
        if privada or request.user.is_authenticated or request.path.startswith(('/login/', '/logout/')):
            add_never_cache_headers(response)
        return response


class LimiteAutenticacionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.http import HttpResponse
        from django.utils.cache import add_never_cache_headers
        from .seguridad import consumir_intento
        rutas = {'/login/', '/login/registrar-correo/', '/login/verificar-codigo/', '/admin/login/'}
        if request.method == 'POST' and request.path in rutas:
            # No confiar en X-Forwarded-For enviado por el navegador.
            permitido = consumir_intento('ip:' + request.META.get('REMOTE_ADDR', ''), 120)
            nombre = (request.POST.get('username') or '').strip().casefold()[:150]
            if permitido and nombre and request.path in {'/login/', '/admin/login/'}:
                permitido = consumir_intento('cuenta:' + nombre, 20)
            if not permitido:
                response = HttpResponse('Demasiados intentos de acceso. Espera 15 minutos y vuelve a intentarlo.', status=429)
                response['Retry-After'] = '900'
                add_never_cache_headers(response)
                return response
        return self.get_response(request)
