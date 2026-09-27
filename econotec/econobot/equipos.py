"""Búsqueda de equipos por código y datos útiles para el chat."""
from ..models import IngresoEquipo, SEDE_PREFIJOS

SEDE_POR_PREFIJO = {prefijo: sede for sede, prefijo in SEDE_PREFIJOS.items()}


def ingreso_por_codigo(codigo):
    """G1031 → IngresoEquipo de Guayaquil número 1031 (o None)."""
    if not codigo or len(codigo) < 2:
        return None
    sede = SEDE_POR_PREFIJO.get(codigo[0].upper())
    try:
        numero = int(codigo[1:])
    except ValueError:
        return None
    if not sede:
        return None
    return (
        IngresoEquipo.objects
        .select_related('cliente', 'tecnico_encargado', 'registrado_por')
        .filter(sede=sede, numero_equipo=numero)
        .first()
    )


def salida_de(ingreso):
    return getattr(ingreso, 'salida', None) if ingreso is not None else None


def descripcion_equipo(ingreso):
    partes = [ingreso.tipo_equipo_display, ingreso.marca, ingreso.modelo_serie]
    return ' '.join(p for p in partes if p).strip()
