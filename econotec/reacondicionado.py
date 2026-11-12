"""
Reacondicionamiento de equipos y chatarrización de Donados / Compras.

- Un equipo chatarrizado (desde Bodegaje) o un equipo donado o comprado se
  puede reacondicionar. Al hacerlo entra al «Inventario reacondicionado»: un
  `InventarioItem` con `linea='reacondicionado'`, con las mismas sedes y
  categorías que el inventario de producto.
- Un donado o comprado también se puede chatarrizar. Eso solo guarda la fecha
  en `fecha_chatarrizacion`: el estado (Donado / Equipo a comprar), el valor
  pagado y su egreso no se tocan.
"""
from datetime import date

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import IngresoEquipo, InventarioItem, SalidaEquipo


ESTADOS_ADMINISTRATIVOS = ('donado', 'equipo_a_comprar')

# Tipo del ingreso → (categoría, tipo) del inventario. Cuando la categoría
# tiene varios tipos y no se puede saber cuál es (impresora láser o de
# inyección, consola de mesa o portátil), el tipo queda vacío para que el
# administrador lo elija en la ventana.
TIPO_INGRESO_A_INVENTARIO = {
    'impresora': ('impresora', ''),
    'laptop': ('computadora', 'laptops'),
    'pc': ('computadora', 'pc'),
    'cpu': ('computadora', 'pc'),
    'monitor': ('otros-equipos-materiales', 'otros-equipos-materiales'),
    'celular': ('celular', 'celular'),
    'tablet': ('tablet', 'tablet'),
    'consola': ('consola', ''),
    'mando': ('mando', 'mando'),
    'maquina_coser': ('otros-equipos-materiales', 'otros-equipos-materiales'),
    'otro': ('otros-equipos-materiales', 'otros-equipos-materiales'),
}


class ReacondicionarError(Exception):
    """Error de validación con un mensaje listo para mostrar al usuario."""


def _catalogo():
    from .views import (
        INVENTARIO_CATEGORIAS, INVENTARIO_SEDES, INVENTARIO_UBICACIONES_POR_SEDE,
    )
    return INVENTARIO_CATEGORIAS, INVENTARIO_SEDES, INVENTARIO_UBICACIONES_POR_SEDE


def contexto_modal_reacondicionar():
    """Opciones de la ventana «Reacondicionar equipo» (sedes, tipos y ubicaciones)."""
    categorias, sedes, ubicaciones = _catalogo()
    sugerencias = {}
    for tipo_ingreso, (categoria, tipo) in TIPO_INGRESO_A_INVENTARIO.items():
        sugerencias[tipo_ingreso] = {
            'valor': f'{categoria}|{tipo}' if tipo else '',
            'categoria': categorias[categoria]['nombre'],
            'opciones': ' o '.join(nombre for _slug, nombre in categorias[categoria]['tipos']),
        }
    return {
        'reacondicionar_config': {
            'sedes': [{'valor': slug, 'nombre': nombre} for slug, nombre in sedes.items()],
            'ubicaciones': {
                sede: [{'valor': valor, 'nombre': nombre} for valor, nombre in opciones]
                for sede, opciones in ubicaciones.items()
            },
            'categorias': [
                {
                    'nombre': info['nombre'],
                    'tipos': [
                        {'valor': f'{slug}|{tipo_slug}', 'nombre': tipo_nombre}
                        for tipo_slug, tipo_nombre in info['tipos']
                    ],
                }
                for slug, info in categorias.items()
            ],
            'sugerencias': sugerencias,
        },
    }


def _chatarrizado_en_bodegaje(ingreso):
    try:
        salida = ingreso.salida
    except SalidaEquipo.DoesNotExist:
        return False
    return salida.estado_reparacion == 'chatarrerizacion'


def puede_reacondicionarse(ingreso):
    """Chatarrizado en Bodegaje, o Donado / Equipo a comprar, y aún sin reacondicionar."""
    if ingreso.inventario_reacondicionado:
        return False
    return ingreso.estado in ESTADOS_ADMINISTRATIVOS or _chatarrizado_en_bodegaje(ingreso)


def equipos_en_chatarrizacion():
    """Filas de «Equipos en Chatarrización»: los de Bodegaje y los Donados / Compras.

    Cada fila trae el ingreso, la fecha de chatarrización, de dónde vino y,
    si ya se reacondicionó, su ficha del inventario.
    """
    filas = {}
    salidas = (
        SalidaEquipo.objects
        .filter(estado_reparacion='chatarrerizacion')
        .select_related('ingreso', 'ingreso__cliente', 'ingreso__item_reacondicionado')
    )
    for salida in salidas:
        filas[salida.ingreso_id] = {
            'ingreso': salida.ingreso,
            'salida': salida,
            'fecha': salida.fecha_retiro_real,
            'origen': 'Bodegaje',
        }
    administrativos = (
        IngresoEquipo.objects
        .filter(estado__in=ESTADOS_ADMINISTRATIVOS, fecha_chatarrizacion__isnull=False)
        .select_related('cliente', 'item_reacondicionado')
    )
    for ingreso in administrativos:
        filas.setdefault(ingreso.pk, {
            'ingreso': ingreso,
            'salida': None,
            'fecha': ingreso.fecha_chatarrizacion,
            'origen': 'Donado' if ingreso.estado == 'donado' else 'Equipo comprado',
        })
    resultado = list(filas.values())
    for fila in resultado:
        fila['reacondicionado'] = fila['ingreso'].inventario_reacondicionado
    resultado.sort(key=lambda fila: fila['fecha'] or date.min, reverse=True)
    return resultado


def _texto(datos, campo, largo):
    return ' '.join((datos.get(campo) or '').split())[:largo]


@transaction.atomic
def reacondicionar_equipo(ingreso_pk, datos, user):
    """Crea la ficha del Inventario reacondicionado para el equipo indicado."""
    categorias, sedes, ubicaciones = _catalogo()
    ingreso = (
        IngresoEquipo.objects.select_for_update()
        .filter(pk=ingreso_pk)
        .first()
    )
    if not ingreso:
        raise ReacondicionarError('El equipo ya no existe.')
    if ingreso.inventario_reacondicionado:
        raise ReacondicionarError(
            f'{ingreso.codigo_equipo} ya está en el Inventario reacondicionado '
            f'({ingreso.inventario_reacondicionado.codigo}).'
        )
    if not puede_reacondicionarse(ingreso):
        raise ReacondicionarError(
            'Solo se reacondicionan equipos chatarrizados, donados o comprados.'
        )

    sede = (datos.get('sede') or '').strip()
    if sede not in sedes:
        raise ReacondicionarError('Elige la sede: Guayaquil o Quito.')

    ubicaciones_validas = [valor for valor, _nombre in ubicaciones[sede]]
    ubicacion = (datos.get('ubicacion') or '').strip()
    if len(ubicaciones_validas) == 1:
        ubicacion = ubicaciones_validas[0]
    if ubicacion not in ubicaciones_validas:
        raise ReacondicionarError('Elige la ubicación de Guayaquil: Norte o Centro.')

    categoria_slug, _sep, tipo_slug = (datos.get('tipo_inventario') or '').partition('|')
    categoria = categorias.get(categoria_slug)
    if not categoria or tipo_slug not in dict(categoria['tipos']):
        raise ReacondicionarError('Elige el tipo de equipo.')

    marca = _texto(datos, 'marca', 100)
    modelo = _texto(datos, 'modelo', 100)
    if not marca or not modelo:
        raise ReacondicionarError('La marca y el modelo son obligatorios.')
    serie = _texto(datos, 'serie', 120)
    observacion = (datos.get('observacion') or '').strip()

    item = InventarioItem(
        linea='reacondicionado',
        ingreso_origen=ingreso,
        sede=sede,
        categoria=categoria_slug,
        tipo=tipo_slug,
        producto=f'{ingreso.tipo_equipo_display} {marca} {modelo}'.strip()[:160],
        marca=marca,
        modelo=modelo,
        serie=serie,
        estado='disponible',
        cantidad=1,
        ubicacion=ubicacion,
        observacion=observacion,
        registrado_por=user,
    )
    try:
        with transaction.atomic():
            item.save()
    except IntegrityError:
        raise ReacondicionarError(
            f'{ingreso.codigo_equipo} ya está en el Inventario reacondicionado.'
        )
    return ingreso, item


@transaction.atomic
def chatarrizar_administrativo(ingreso_pk):
    """Marca un Donado / Equipo a comprar como chatarrizado sin tocar su estado ni su egreso."""
    ingreso = (
        IngresoEquipo.objects.select_for_update()
        .filter(pk=ingreso_pk)
        .first()
    )
    if not ingreso or ingreso.estado not in ESTADOS_ADMINISTRATIVOS:
        raise ReacondicionarError('Solo se chatarrizan aquí los equipos donados o comprados.')
    if ingreso.inventario_reacondicionado:
        raise ReacondicionarError(f'{ingreso.codigo_equipo} ya fue reacondicionado.')
    if ingreso.fecha_chatarrizacion:
        raise ReacondicionarError(f'{ingreso.codigo_equipo} ya está en chatarrización.')
    hoy = timezone.localdate()
    # update() directo: no pasa por save(), así no se recalcula nada del ingreso.
    IngresoEquipo.objects.filter(pk=ingreso.pk).update(
        fecha_chatarrizacion=hoy,
        actualizado=timezone.now(),
    )
    ingreso.fecha_chatarrizacion = hoy
    return ingreso
