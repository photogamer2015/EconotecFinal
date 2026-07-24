from django.utils import timezone
from django.db.models import Q


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


def _hora_bitacora(dt):
    local = timezone.localtime(dt)
    hora = local.hour % 12 or 12
    return f'{hora}:{local.minute:02d}'


def _periodo_bitacora(dt):
    return 'AM' if timezone.localtime(dt).hour < 12 else 'PM'


def _fecha_bitacora(dt):
    return timezone.localtime(dt).strftime('%d/%m/%Y')


def _texto_limpio_bitacora(texto, max_len=170):
    texto = ' '.join((texto or '').split())
    if len(texto) <= max_len:
        return texto
    return texto[:max_len - 1].rstrip() + '…'


def _equipo_bitacora(ingreso):
    partes = [
        ingreso.tipo_equipo_display,
        ingreso.marca,
        ingreso.modelo_serie_detalle,
    ]
    return ' '.join(p for p in partes if p).strip()


def _texto_salida_bitacora(salida):
    ingreso = salida.ingreso
    equipo = _equipo_bitacora(ingreso)
    reporte = _texto_limpio_bitacora(ingreso.reporte_tecnico)

    if reporte:
        base = reporte.rstrip('.')
    else:
        base = f'Trabajo registrado en {equipo}'.strip()

    if salida.estado_reparacion in ('pendiente_retiro', 'retirado'):
        return f'{base} #{ingreso.codigo_equipo} lista, cliente notificado.'
    if salida.estado_reparacion in ('garantia', 'garantia_fallos_adicionales'):
        return f'{base} #{ingreso.codigo_equipo} salida por garantía.'
    if salida.estado_reparacion == 'cliente_no_acepta':
        return f'{base} #{ingreso.codigo_equipo} cliente no quiso reparar.'
    if salida.estado_reparacion == 'no_reparable':
        return f'{base} #{ingreso.codigo_equipo} no se pudo reparar.'
    return f'{base} #{ingreso.codigo_equipo} {salida.get_estado_reparacion_display()}.'


def _filtro_fecha(campo, dia=None, fecha_inicio=None, fecha_fin=None):
    if dia is not None:
        return {f'{campo}__date': dia}
    filtros = {}
    if fecha_inicio is not None:
        filtros[f'{campo}__date__gte'] = fecha_inicio
    if fecha_fin is not None:
        filtros[f'{campo}__date__lte'] = fecha_fin
    return filtros


def eventos_bitacora_usuario(user, dia=None, fecha_inicio=None, fecha_fin=None):
    if dia is None and fecha_inicio is None and fecha_fin is None:
        dia = timezone.localdate()

    from .models import Abono, BitacoraTecnico, IngresoEquipo, SalidaEquipo

    eventos = []
    eventos_guardados = (
        BitacoraTecnico.objects
        .select_related('ingreso', 'salida', 'abono')
        .filter(user=user, **_filtro_fecha('momento', dia, fecha_inicio, fecha_fin))
        .order_by('momento', 'pk')
    )
    ingresos_con_evento_por_tipo = {}
    salidas_con_evento = set()
    abonos_con_evento = set()

    for evento in eventos_guardados:
        if evento.ingreso_id:
            ingresos_con_evento_por_tipo.setdefault(evento.tipo, set()).add(evento.ingreso_id)
        if evento.salida_id:
            salidas_con_evento.add(evento.salida_id)
        if evento.abono_id:
            abonos_con_evento.add(evento.abono_id)

        eventos.append({
            'momento': evento.momento,
            'texto': evento.texto,
            'tipo': evento.tipo,
            'codigo': evento.codigo,
        })

    ingresos_con_evento = set()
    for tipos in ingresos_con_evento_por_tipo.values():
        ingresos_con_evento.update(tipos)

    salidas = (
        SalidaEquipo.objects
        .select_related('ingreso', 'ingreso__cliente', 'tecnico_reparo', 'registrado_por')
        .filter(**_filtro_fecha('creado', dia, fecha_inicio, fecha_fin))
        .filter(Q(tecnico_reparo=user) | Q(registrado_por=user))
        .exclude(pk__in=salidas_con_evento)
        .order_by('creado', 'pk')
    )
    ingresos_con_salida = set()
    for salida in salidas:
        ingresos_con_salida.add(salida.ingreso_id)
        eventos.append({
            'momento': salida.creado,
            'texto': _texto_salida_bitacora(salida),
            'tipo': 'salida',
            'codigo': salida.ingreso.codigo_equipo,
        })

    ingresos = (
        IngresoEquipo.objects
        .select_related('cliente', 'tecnico_encargado', 'registrado_por')
        .filter(**_filtro_fecha('creado', dia, fecha_inicio, fecha_fin))
        .filter(Q(registrado_por=user) | Q(tecnico_encargado=user))
        .exclude(pk__in=ingresos_con_salida)
        .exclude(pk__in=ingresos_con_evento)
        .order_by('creado', 'pk')
    )
    for ingreso in ingresos:
        equipo = _equipo_bitacora(ingreso)
        if ingreso.sede == 'ventas':
            texto = f'Venta de producto registrada: {equipo} #{ingreso.codigo_equipo}.'
        elif ingreso.registrado_por_id == user.id:
            texto = f'Recepción y registro de {equipo} #{ingreso.codigo_equipo} para {ingreso.cliente.nombres}.'
        else:
            texto = f'Equipo asignado para revisión: {equipo} #{ingreso.codigo_equipo}.'
        eventos.append({
            'momento': ingreso.creado,
            'texto': texto,
            'tipo': 'ingreso',
            'codigo': ingreso.codigo_equipo,
        })

    reportes = (
        IngresoEquipo.objects
        .select_related('cliente')
        .filter(reporte_por=user, **_filtro_fecha('reporte_actualizado', dia, fecha_inicio, fecha_fin))
        .exclude(pk__in=ingresos_con_salida)
        .exclude(pk__in=ingresos_con_evento_por_tipo.get('reporte', set()))
        .order_by('reporte_actualizado', 'pk')
    )
    for ingreso in reportes:
        reporte = _texto_limpio_bitacora(ingreso.reporte_tecnico)
        if not reporte:
            continue
        eventos.append({
            'momento': ingreso.reporte_actualizado,
            'texto': f'Actualización de reporte técnico en {_equipo_bitacora(ingreso)} #{ingreso.codigo_equipo}: {reporte}.',
            'tipo': 'reporte',
            'codigo': ingreso.codigo_equipo,
        })

    reportes_valor = (
        IngresoEquipo.objects
        .select_related('cliente')
        .filter(valor_pendiente_reporte_por=user, **_filtro_fecha('valor_pendiente_reporte_actualizado', dia, fecha_inicio, fecha_fin))
        .exclude(pk__in=ingresos_con_evento_por_tipo.get('valor_pendiente', set()))
        .order_by('valor_pendiente_reporte_actualizado', 'pk')
    )
    for ingreso in reportes_valor:
        motivo = _texto_limpio_bitacora(ingreso.valor_pendiente_reporte)
        if not motivo:
            continue
        eventos.append({
            'momento': ingreso.valor_pendiente_reporte_actualizado,
            'texto': f'Reporte de valor acordado pendiente en #{ingreso.codigo_equipo}: {motivo}.',
            'tipo': 'valor_pendiente',
            'codigo': ingreso.codigo_equipo,
        })

    abonos = (
        Abono.objects
        .select_related('ingreso', 'ingreso__cliente')
        .filter(registrado_por=user, **_filtro_fecha('creado', dia, fecha_inicio, fecha_fin))
        .exclude(pk__in=abonos_con_evento)
        .order_by('creado', 'pk')
    )
    for abono in abonos:
        eventos.append({
            'momento': abono.creado,
            'texto': f'Registro de abono {abono.numero_recibo} por ${abono.monto:.2f} en #{abono.ingreso.codigo_equipo}.',
            'tipo': 'abono',
            'codigo': abono.ingreso.codigo_equipo,
        })

    eventos.sort(key=lambda e: (e['momento'], e['texto']))
    return eventos


def _eventos_json(eventos, incluir_fecha=False):
    from .models import BitacoraTecnico

    tipos = dict(BitacoraTecnico.TIPO_ACCION)
    eventos_json = []
    for evento in eventos:
        dato = {
            'hora_inicio': _hora_bitacora(evento['momento']),
            'periodo_inicio': _periodo_bitacora(evento['momento']),
            'texto': evento['texto'],
            'tipo': evento['tipo'],
            'tipo_label': tipos.get(evento['tipo'], evento['tipo']),
            'codigo': evento['codigo'],
        }
        if incluir_fecha:
            dato['fecha'] = _fecha_bitacora(evento['momento'])
        eventos_json.append(dato)
    return eventos_json


def construir_bitacora_usuario(user, dia=None):
    dia = dia or timezone.localdate()
    eventos = eventos_bitacora_usuario(user, dia=dia)
    fecha_txt = dia.strftime('%d/%m/%Y')
    nombre = nombre_corto_usuario(user)
    encabezado = '\n'.join(['Reporte del día', f'Técnico: {nombre}', f'Fecha: {fecha_txt}'])

    if not eventos:
        return {
            'fecha': fecha_txt,
            'total': 0,
            'tiene_datos': False,
            'encabezado': encabezado,
            'detalle': '',
            'texto': encabezado,
            'eventos': [],
        }

    lineas = []
    for evento in eventos:
        hora_inicio = _hora_bitacora(evento['momento'])
        periodo_inicio = _periodo_bitacora(evento['momento'])
        lineas.append(f'{hora_inicio} {periodo_inicio} - {evento["texto"]}')

    detalle = '\n'.join(lineas)
    return {
        'fecha': fecha_txt,
        'total': len(eventos),
        'tiene_datos': True,
        'encabezado': encabezado,
        'detalle': detalle,
        'texto': f'{encabezado}\n\n{detalle}',
        'eventos': _eventos_json(eventos),
    }


def construir_bitacora_usuario_rango(user, fecha_inicio, fecha_fin):
    eventos = eventos_bitacora_usuario(
        user,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
    )
    periodo_txt = f'{fecha_inicio.strftime("%d/%m/%Y")} - {fecha_fin.strftime("%d/%m/%Y")}'
    nombre = nombre_corto_usuario(user)
    encabezado = '\n'.join(['Reporte del período', f'Técnico: {nombre}', f'Período: {periodo_txt}'])

    if not eventos:
        return {
            'fecha': periodo_txt,
            'total': 0,
            'tiene_datos': False,
            'encabezado': encabezado,
            'detalle': '',
            'texto': encabezado,
            'eventos': [],
        }

    lineas = []
    for evento in eventos:
        fecha = _fecha_bitacora(evento['momento'])
        hora_inicio = _hora_bitacora(evento['momento'])
        periodo_inicio = _periodo_bitacora(evento['momento'])
        lineas.append(f'{fecha} {hora_inicio} {periodo_inicio} - {evento["texto"]}')

    detalle = '\n'.join(lineas)
    return {
        'fecha': periodo_txt,
        'total': len(eventos),
        'tiene_datos': True,
        'encabezado': encabezado,
        'detalle': detalle,
        'texto': f'{encabezado}\n\n{detalle}',
        'eventos': _eventos_json(eventos, incluir_fecha=True),
    }
