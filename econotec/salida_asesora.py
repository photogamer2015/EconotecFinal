"""A qué asesora pertenece una salida de la oficina (salida de retiro).

Al confirmar la salida se elige la asesora que la hizo; esa salida le cuenta
en su perfil y en el ranking de asesoras del administrador. El dato viaja en
el POST como `asesora_salida` (pk de la asesora).
"""
from .forms import _queryset_asesores
from .permisos import es_asesor

CAMPO = 'asesora_salida'


def asesoras_para_salida():
    """Usuarias activas con rol de asesora (incluida la asistente de caja)."""
    return _queryset_asesores()


def asesora_de_la_salida(request):
    """(asesora, error) según lo elegido en el POST.

    Si no se eligió nadie y quien confirma es una asesora, la salida es suya.
    """
    valor = (request.POST.get(CAMPO) or '').strip()
    if valor:
        asesora = asesoras_para_salida().filter(pk=valor).first() if valor.isdigit() else None
        if asesora is None:
            return None, 'La asesora elegida para la salida no es válida. Elige otra.'
        return asesora, None
    if es_asesor(request.user):
        return request.user, None
    return None, 'Elige a qué asesora pertenece esta salida de la oficina.'


def nombre(asesora):
    return asesora.get_full_name() or asesora.username
