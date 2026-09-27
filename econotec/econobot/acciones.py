"""Acciones cortas sobre un equipo existente.

- Cambio de estado y reporte técnico → vista `tecnico_hoja` (Hoja del Técnico).
- Valor acordado → vista `ingreso_valor_acordado_editar` (módulo Pagos).
- Salida física de la oficina → vista `salida_marcar_retirada`.
"""
import re
from decimal import Decimal

from django.urls import reverse

from .. import views as vistas
from .. import views_pagos, views_tecnico
from ..forms import CobroBodegajeForm, ValorAcordadoPagoForm
from ..models import IngresoEquipo, SalidaEquipo, SUBESTADO_EN_REPARACION
from ..qr_utils import token_para_ingreso
from . import texto as tx
from .enviar import enviar
from .equipos import descripcion_equipo
from .flujo import Flujo, Pregunta
from .formularios import (
    completar_monto_2, errores_pago, post_pago, preguntas_pago, resumen_pago,
)
from .respuesta import enlace, opcion, respuesta


# ─────────────────────────────────────────────────────────────────────
# Cambio de estado / reporte técnico
# ─────────────────────────────────────────────────────────────────────

ESTADOS_TALLER = [
    ('ingresado', 'Ingresado / En diagnóstico'),
    ('en_reparacion', 'En reparación'),
]
SUBESTADOS = [(valor, etiqueta) for valor, etiqueta in SUBESTADO_EN_REPARACION if valor]


def motivo_sin_cambio_estado(ingreso):
    if ingreso is None:
        return 'No encontré ese equipo. Revisa el código (por ejemplo G1031).'
    if getattr(ingreso, 'salida', None) is not None:
        salida = ingreso.salida
        return (f'{ingreso.codigo_equipo} ya está finalizado («{salida.estado_operativo_display}»). '
                'Para devolverlo al taller hay que hacerlo desde la edición del equipo.')
    if ingreso.estado not in ('ingresado', 'en_reparacion'):
        return (f'{ingreso.codigo_equipo} está como «{ingreso.get_estado_display()}». Ese estado se cambia '
                'desde la edición del equipo para no perder su información.')
    return ''


class FlujoEstado(Flujo):
    nombre = 'estado'
    titulo = 'Cambio de estado'
    verbo_confirmar = 'Guardar cambio'
    pregunta_confirmacion = '¿Guardo el cambio? Responde «sí» para guardar.'
    alias = {
        'estado': 'nuevo_estado', 'detalle': 'subestado', 'reporte': 'reporte',
        'reporte del tecnico': 'reporte',
    }

    def iniciar(self, ingreso, nuevo_estado='', subestado='', reporte=None, solo_reporte=False):
        d = self.datos
        d['ingreso_pk'] = ingreso.pk
        if solo_reporte:
            # Solo cambia el reporte: el estado y su detalle se envían tal cual están.
            d['nuevo_estado'] = ingreso.estado
            d['subestado'] = ingreso.subestado_reparacion or ''
            d['_solo_reporte'] = True
        if nuevo_estado:
            d['nuevo_estado'] = nuevo_estado
        if subestado:
            d['subestado'] = subestado
        if reporte is not None:
            d['reporte'] = reporte
        elif not solo_reporte:
            d['reporte'] = ingreso.reporte_tecnico or ''
        return []

    def ingreso(self):
        pk = self.datos.get('ingreso_pk')
        return self.cache('ingreso', lambda: IngresoEquipo.objects.select_related('cliente').filter(pk=pk).first())

    def preguntas(self):
        ingreso = self.ingreso()
        if ingreso is None:
            return []
        d = self.datos
        p = [Pregunta('nuevo_estado', 'Nuevo estado', f'¿A qué estado pasa {ingreso.codigo_equipo}?',
                      tipo='opcion', opciones=ESTADOS_TALLER)]
        if d.get('nuevo_estado') == 'en_reparacion':
            p.append(Pregunta('subestado', 'Detalle', '¿Qué detalle de reparación aplica?',
                              tipo='opcion', opciones=SUBESTADOS))
        actual = (ingreso.reporte_tecnico or '').strip()
        texto = '¿Qué reporte técnico escribo?'
        if actual:
            texto += (f'\nReporte actual: «{actual[:200]}»\nLo que escribas lo reemplaza; empieza con «agregar:» '
                      'para sumarlo al final.')
        p.append(Pregunta('reporte', 'Reporte del técnico', texto, tipo='texto_largo'))
        return p

    def interpretar_especial(self, pregunta, mensaje):
        if pregunta.clave != 'reporte':
            return None
        crudo = (mensaje or '').strip()
        agregado = re.match(r'^\s*(?:\+|agregar|agrega|anadir|añadir|añade|anade|sumar)\s*:?\s*', crudo, re.IGNORECASE)
        if agregado:
            extra = crudo[agregado.end():].strip()
            if not extra:
                return None, 'Escribe el texto que agrego después de «agregar:».'
            actual = (self.ingreso().reporte_tecnico or '').strip()
            return (f'{actual}\n{extra}' if actual else extra), None
        if tx.limpiar(crudo) in ('mantener', 'mantener el reporte actual', 'igual', 'el mismo'):
            return (self.ingreso().reporte_tecnico or ''), None
        return None

    def errores(self):
        return {}

    def resumen(self):
        ingreso = self.ingreso()
        d = self.datos
        estado = dict(ESTADOS_TALLER).get(d.get('nuevo_estado'), '—')
        if d.get('nuevo_estado') == 'en_reparacion':
            estado += ' — ' + dict(SUBESTADOS).get(d.get('subestado'), '—')
        lineas = [f'📝 {ingreso.codigo_equipo} — {descripcion_equipo(ingreso)} ({ingreso.cliente.nombres})']
        if not d.get('_solo_reporte'):
            lineas.append(f'• Estado actual: {ingreso.estado_visual_display}'
                          + (f' — {ingreso.subestado_visual_display}' if ingreso.subestado_visual_display else ''))
            lineas.append(f'• Nuevo estado: {estado}')
        reporte = (d.get('reporte') or '').strip()
        lineas.append(f'• Reporte del técnico: {reporte[:240] if reporte else "(sin reporte)"}')
        return '\n'.join(lineas)

    def ejecutar(self):
        ingreso = IngresoEquipo.objects.select_related('cliente').filter(pk=self.datos.get('ingreso_pk')).first()
        motivo = motivo_sin_cambio_estado(ingreso)
        if motivo:
            return respuesta(motivo, [enlace('Abrir el equipo', 'ingreso_detalle', pk=ingreso.pk)] if ingreso else [],
                             hecho=True)
        d = self.datos
        datos = {
            'reporte_tecnico': d.get('reporte', ingreso.reporte_tecnico or ''),
            'valor_pendiente_reporte': ingreso.valor_pendiente_reporte or '',
            'estado_movil': d.get('nuevo_estado'),
            'subestado_reparacion': d.get('subestado', '') if d.get('nuevo_estado') == 'en_reparacion' else '',
            'accion': 'guardar',
        }
        resultado = enviar(self.request, views_tecnico.tecnico_hoja, token=token_para_ingreso(ingreso.pk), datos=datos)
        ingreso.refresh_from_db()
        if resultado.destino_nombre != 'tecnico_hoja' or ingreso.estado != d.get('nuevo_estado'):
            detalle = ' '.join(resultado.errores + resultado.mensajes_de('warning')) or 'El sistema no aceptó el cambio.'
            return respuesta(f'No pude guardar el cambio: {detalle}',
                             [enlace('Abrir el equipo', 'ingreso_detalle', pk=ingreso.pk)], hecho=True)
        estado = ingreso.estado_visual_display + (
            f' — {ingreso.subestado_visual_display}' if ingreso.subestado_visual_display else '')
        texto = (f'✅ Reporte técnico de {ingreso.codigo_equipo} actualizado.' if d.get('_solo_reporte')
                 else f'✅ {ingreso.codigo_equipo} ahora está: {estado}.')
        return respuesta(texto, [enlace('Ver equipo', 'ingreso_detalle', pk=ingreso.pk)], [
            opcion(f'Finalizar {ingreso.codigo_equipo}', f'finalizar {ingreso.codigo_equipo}'),
            opcion(f'Ver {ingreso.codigo_equipo}', f'ver {ingreso.codigo_equipo}'),
        ], hecho=True, ultimo_equipo=ingreso.pk)


# ─────────────────────────────────────────────────────────────────────
# Valor acordado
# ─────────────────────────────────────────────────────────────────────

def motivo_sin_valor(ingreso):
    if ingreso is None:
        return 'No encontré ese equipo. Revisa el código (por ejemplo G1031).'
    if not views_pagos._puede_editar_valor_acordado_en_pagos(ingreso):
        return (f'El valor acordado de {ingreso.codigo_equipo} no se edita desde Pagos '
                f'(estado «{ingreso.estado_visual_display}»).')
    return ''


class FlujoValor(Flujo):
    nombre = 'valor'
    titulo = 'Valor acordado'
    verbo_confirmar = 'Guardar valor'
    pregunta_confirmacion = '¿Guardo el valor acordado? Responde «sí» para guardar.'
    alias = {'valor': 'valor', 'valor acordado': 'valor'}

    def iniciar(self, ingreso, valor=''):
        self.datos['ingreso_pk'] = ingreso.pk
        if valor:
            self.datos['valor'] = valor
        return []

    def ingreso(self):
        pk = self.datos.get('ingreso_pk')
        return self.cache('ingreso', lambda: IngresoEquipo.objects.select_related('cliente').filter(pk=pk).first())

    def preguntas(self):
        ingreso = self.ingreso()
        if ingreso is None:
            return []
        actual = tx.dinero_legible(ingreso.valor_acordado) if ingreso.valor_acordado is not None else 'pendiente'
        return [Pregunta('valor', 'Valor acordado',
                         f'¿Cuál es el valor acordado de {ingreso.codigo_equipo}? (actual: {actual})', tipo='dinero')]

    def errores(self):
        if 'valor' not in self.datos:
            return {}
        formulario = ValorAcordadoPagoForm({'valor_acordado': self.datos['valor']})
        formulario.is_valid()
        return {'valor': [str(e) for e in formulario.errors.get('valor_acordado', [])]}

    def resumen(self):
        ingreso = self.ingreso()
        actual = tx.dinero_legible(ingreso.valor_acordado) if ingreso.valor_acordado is not None else 'Pendiente'
        return (f'📝 {ingreso.codigo_equipo} — {descripcion_equipo(ingreso)} ({ingreso.cliente.nombres})\n'
                f'• Valor actual: {actual}\n• Nuevo valor acordado: {tx.dinero_legible(self.datos.get("valor"))}')

    def ejecutar(self):
        ingreso = IngresoEquipo.objects.filter(pk=self.datos.get('ingreso_pk')).first()
        motivo = motivo_sin_valor(ingreso)
        if motivo:
            return respuesta(motivo, hecho=True)
        resultado = enviar(self.request, views_pagos.ingreso_valor_acordado_editar, pk=ingreso.pk,
                           datos={'valor_acordado': self.datos.get('valor', '')})
        ingreso.refresh_from_db()
        if resultado.errores or resultado.mensajes_de('warning'):
            return respuesta('No pude guardar el valor: ' + ' '.join(resultado.errores + resultado.mensajes_de('warning')),
                             hecho=True)
        texto = (f'✅ Valor acordado de {ingreso.codigo_equipo}: {tx.dinero_legible(ingreso.valor_acordado)}. '
                 f'Saldo actual: {tx.dinero_legible(ingreso.diferencia)}.')
        if resultado.mensajes_de('info'):
            texto = f'El valor acordado de {ingreso.codigo_equipo} ya era {tx.dinero_legible(ingreso.valor_acordado)}; no cambió nada.'
        return respuesta(texto, [enlace('Ver pagos del equipo', 'ingreso_abonos', pk=ingreso.pk)], [
            opcion(f'Finalizar {ingreso.codigo_equipo}', f'finalizar {ingreso.codigo_equipo}'),
            opcion(f'Ver {ingreso.codigo_equipo}', f'ver {ingreso.codigo_equipo}'),
        ], hecho=True, ultimo_equipo=ingreso.pk)


# ─────────────────────────────────────────────────────────────────────
# Salida física de la oficina (el cliente retiró su equipo)
# ─────────────────────────────────────────────────────────────────────

def motivo_sin_retiro(ingreso):
    if ingreso is None:
        return 'No encontré ese equipo. Revisa el código (por ejemplo G1031).'
    salida = getattr(ingreso, 'salida', None)
    if salida is None:
        return (f'{ingreso.codigo_equipo} todavía no está finalizado. Primero finalízalo '
                f'(escribe «finalizar {ingreso.codigo_equipo}») y luego confirma su salida.')
    if salida.cliente_ya_retiro:
        return f'{ingreso.codigo_equipo} ya consta fuera de la oficina desde el {salida.fecha_retiro_real:%d/%m/%Y}.'
    saldo = ingreso.diferencia
    if saldo > 0:
        return (f'{ingreso.codigo_equipo} tiene un saldo pendiente de {tx.dinero_legible(saldo)}. '
                'Debe pagarse antes de confirmar la salida de la oficina.')
    return ''


class FlujoRetiro(Flujo):
    nombre = 'retiro'
    titulo = 'Confirmar salida física'
    verbo_confirmar = 'Confirmar salida'
    pregunta_confirmacion = '¿Confirmas que el equipo ya salió de la oficina? Responde «sí» para guardar.'
    alias = {'bodegaje': 'bodegaje'}

    def iniciar(self, ingreso):
        self.datos['ingreso_pk'] = ingreso.pk
        return []

    def salida(self):
        pk = self.datos.get('ingreso_pk')
        return self.cache('salida', lambda: SalidaEquipo.objects.select_related('ingreso', 'ingreso__cliente')
                          .filter(ingreso_id=pk).first())

    def bodegaje(self):
        """Bodegaje pendiente de decisión, el mismo que muestra la web al confirmar la salida."""
        salida = self.salida()

        def calcular():
            if salida is None:
                return {'monto': Decimal('0.00'), 'dias': 0}
            ingreso = salida.ingreso
            return {'monto': ingreso.bodegaje_pendiente, 'dias': ingreso.bodegaje_dias_pendiente}
        return self.cache('bodegaje', calcular)

    def al_capturar(self, clave, valor):
        if clave == 'bodegaje__monto_1':
            completar_monto_2('bodegaje', self.datos, self.bodegaje()['monto'])
        return []

    def preguntas(self):
        salida = self.salida()
        if salida is None:
            return []
        bod = self.bodegaje()
        p = []
        if bod['monto'] > 0:
            monto = tx.dinero_legible(bod['monto'])
            p.append(Pregunta(
                'bodegaje', 'Bodegaje',
                f'{salida.ingreso.codigo_equipo} acumula {monto} de bodegaje ({bod["dias"]} día'
                f'{"s" if bod["dias"] != 1 else ""}). ¿Se cobra o se perdona?',
                tipo='opcion', opciones=[('cobrar', f'Cobrar {monto}'), ('perdonar', 'Perdonar (no cobrar)')],
            ))
            if self.datos.get('bodegaje') == 'cobrar':
                p += preguntas_pago('bodegaje', self.datos, 'bodegaje', bod['monto'])
        return p

    def post(self):
        cobrar = self.datos.get('bodegaje') == 'cobrar' and self.bodegaje()['monto'] > 0
        datos = {
            'aplicar_bodegaje': 'on' if cobrar else '',
            'next': reverse('econotec:salida_retiros_lista'),
        }
        if cobrar:
            datos.update(post_pago('bodegaje', self.datos))
        return datos

    def errores(self):
        if self.datos.get('bodegaje') != 'cobrar':
            return {}
        formulario = CobroBodegajeForm(self.post(), monto_esperado=self.bodegaje()['monto'])
        formulario.is_valid()
        return errores_pago('bodegaje', formulario.errors)

    def resumen(self):
        salida = self.salida()
        ingreso = salida.ingreso
        bod = self.bodegaje()
        lineas = [f'📝 Salida física de {ingreso.codigo_equipo} — {descripcion_equipo(ingreso)} ({ingreso.cliente.nombres})',
                  f'• Resultado: {salida.get_estado_reparacion_display()} · Finalizado el {salida.fecha_salida:%d/%m/%Y}',
                  '• Saldo del cliente: $0,00']
        if bod['monto'] > 0:
            if self.datos.get('bodegaje') == 'cobrar':
                lineas.append(f'• Bodegaje: se cobran {tx.dinero_legible(bod["monto"])} ({resumen_pago("bodegaje", self.datos)})')
            else:
                lineas.append(f'• Bodegaje: {tx.dinero_legible(bod["monto"])} perdonado (no se cobra)')
        return '\n'.join(lineas)

    def ejecutar(self):
        ingreso = IngresoEquipo.objects.select_related('cliente').filter(pk=self.datos.get('ingreso_pk')).first()
        motivo = motivo_sin_retiro(ingreso)
        if motivo:
            return respuesta(motivo, hecho=True)
        salida = ingreso.salida
        resultado = enviar(self.request, vistas.salida_marcar_retirada, pk=salida.pk, datos=self.post())
        salida.refresh_from_db()
        if not salida.cliente_ya_retiro:
            detalle = ' '.join(resultado.errores) or 'El sistema no confirmó la salida.'
            return respuesta(f'No pude confirmar la salida: {detalle}',
                             [enlace('Ver equipos listos', 'salida_lista')], hecho=True)
        lineas = ['✅ ' + m for m in resultado.mensajes_de('success')] or [
            f'✅ Salida de la oficina confirmada para {ingreso.codigo_equipo}.']
        lineas += resultado.mensajes_de('info', 'warning')
        return respuesta('\n'.join(lineas), [
            enlace('Ver salidas físicas confirmadas', 'salida_retiros_lista'),
            enlace('Ver equipo', 'ingreso_detalle', pk=ingreso.pk),
        ], [opcion(f'Ver {ingreso.codigo_equipo}', f'ver {ingreso.codigo_equipo}')],
            hecho=True, ultimo_equipo=ingreso.pk)
