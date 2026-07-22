from django.utils import timezone


def nombre_corto_usuario(user):
    if not user:
        return 'Técnico'
    return (user.first_name or user.username or 'Técnico').strip()


def registrar_bitacora(
    user,
    tipo,
    texto,
    *,
    ingreso=None,
    salida=None,
    abono=None,
    codigo='',
    momento=None,
    dedupe_key=None,
    metadata=None,
):
    """
    Guarda una entrada permanente de bitacora para acciones reales del sistema.

    Si se envia dedupe_key, evita duplicados para acciones que pueden reintentarse
    en el navegador o por redireccionamientos.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return None

    texto = ' '.join((texto or '').split())
    if not texto:
        return None

    from .models import BitacoraTecnico

    if not codigo:
        if ingreso is not None:
            codigo = ingreso.codigo_equipo
        elif salida is not None and salida.ingreso_id:
            codigo = salida.ingreso.codigo_equipo
        elif abono is not None and abono.ingreso_id:
            codigo = abono.ingreso.codigo_equipo

    defaults = {
        'user': user,
        'usuario_nombre': nombre_corto_usuario(user),
        'momento': momento or timezone.now(),
        'tipo': tipo or 'otro',
        'texto': texto,
        'codigo': codigo or '',
        'ingreso': ingreso,
        'salida': salida,
        'abono': abono,
        'metadata': metadata or {},
    }

    if dedupe_key:
        evento, _ = BitacoraTecnico.objects.get_or_create(
            dedupe_key=dedupe_key,
            defaults=defaults,
        )
        return evento

    return BitacoraTecnico.objects.create(**defaults)
