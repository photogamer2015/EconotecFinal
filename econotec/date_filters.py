from datetime import date, timedelta

from django.utils import timezone


PRESETS_FECHA = {
    'hoy',
    'ayer',
    'ultimos_7',
    'ultimos_14',
    'ultimos_30',
    'esta_semana',
    'este_mes',
    'mes_pasado',
}


def _parse_date(value):
    value = (value or '').strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _month_bounds(day):
    first = day.replace(day=1)
    if first.month == 12:
        next_month = first.replace(year=first.year + 1, month=1)
    else:
        next_month = first.replace(month=first.month + 1)
    return first, next_month - timedelta(days=1)


def _preset_range(preset, today=None):
    today = today or timezone.localdate()
    if preset == 'hoy':
        return today, today
    if preset == 'ayer':
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    if preset == 'ultimos_7':
        return today - timedelta(days=6), today
    if preset == 'ultimos_14':
        return today - timedelta(days=13), today
    if preset == 'ultimos_30':
        return today - timedelta(days=29), today
    if preset == 'esta_semana':
        return today - timedelta(days=today.weekday()), today
    if preset == 'este_mes':
        return today.replace(day=1), today
    if preset == 'mes_pasado':
        first_this_month = today.replace(day=1)
        last_prev_month = first_this_month - timedelta(days=1)
        return _month_bounds(last_prev_month)
    return None, None


def obtener_rango_fecha(request):
    preset = (request.GET.get('fecha_preset') or '').strip()
    if preset not in PRESETS_FECHA:
        preset = ''

    desde = _parse_date(request.GET.get('fecha_desde'))
    hasta = _parse_date(request.GET.get('fecha_hasta'))

    if preset and not desde and not hasta:
        desde, hasta = _preset_range(preset)

    if desde and hasta and desde > hasta:
        desde, hasta = hasta, desde

    return desde, hasta, preset


def aplicar_rango_fecha(qs, campo, desde, hasta):
    if desde:
        qs = qs.filter(**{f'{campo}__gte': desde})
    if hasta:
        qs = qs.filter(**{f'{campo}__lte': hasta})
    return qs


def _fecha_corta(day):
    return day.strftime('%d/%m/%Y')


def resumen_rango_fecha(desde, hasta, etiqueta='Fecha'):
    if desde and hasta:
        if desde == hasta:
            return f'{etiqueta}: {_fecha_corta(desde)}'
        return f'{etiqueta}: {_fecha_corta(desde)} - {_fecha_corta(hasta)}'
    if desde:
        return f'{etiqueta}: desde {_fecha_corta(desde)}'
    if hasta:
        return f'{etiqueta}: hasta {_fecha_corta(hasta)}'
    return f'{etiqueta}: sin filtro'


def contexto_rango_fecha(desde, hasta, preset='', etiqueta='Fecha'):
    return {
        'fecha_desde': desde.isoformat() if desde else '',
        'fecha_hasta': hasta.isoformat() if hasta else '',
        'fecha_preset': preset or '',
        'fecha_resumen': resumen_rango_fecha(desde, hasta, etiqueta=etiqueta),
        'fecha_rango_activo': bool(desde or hasta),
    }
