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
