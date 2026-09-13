"""Límite de peticiones de autenticación persistente y atómico."""
import hashlib
from datetime import datetime, timezone as datetime_timezone
from django.db.models import F
from django.utils import timezone
from .models import LimiteAcceso


def consumir_intento(identificador, limite, ventana=900):
    ahora = timezone.now()
    bloque = int(ahora.timestamp()) // ventana
    clave = hashlib.sha256(f'{bloque}:{identificador}'.encode()).hexdigest()
    LimiteAcceso.objects.filter(expira__lte=ahora).delete()
    LimiteAcceso.objects.get_or_create(clave=clave, defaults={
        'expira': datetime.fromtimestamp((bloque + 1) * ventana, tz=datetime_timezone.utc),
    })
    # El límite se comprueba en el mismo UPDATE que incrementa el contador.
    permitido = LimiteAcceso.objects.filter(clave=clave, intentos__lt=limite).update(intentos=F('intentos') + 1)
    return bool(permitido)
