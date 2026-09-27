"""Finalizar un equipo por chat («Equipo listo / finalizado»).

- Resultados normales (pendiente de retiro, revisión, garantía, cortesía):
  se envían a la vista original `salida_registrar`, igual que el botón
  «Registrar equipo listo / finalizado».
- «No se pudo reparar» y «Cliente no quiso reparar»: se envían a
  `ingreso_editar` con el formulario completo del equipo, igual que
  «Editar estado» en la web (así se aplican las mismas reglas de cobro).
"""
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .. import views as vistas
from .. import views_pagos
from ..alertas import whatsapp_link_equipo_listo
from ..forms import ClienteForm, IngresoEquipoForm, SalidaEquipoForm, _queryset_asesores
from ..models import IngresoEquipo, SalidaEquipo, SEDES_EQUIPOS
from . import texto as tx
from .enviar import enviar, solicitud_interna
from .equipos import descripcion_equipo, ingreso_por_codigo
from .flujo import Flujo, Pregunta
from .formularios import (
    errores_pago, etiqueta_de, opciones_tecnicos, post_pago, preguntas_pago, completar_monto_2,
    resumen_pago, usuario_es_tecnico_de_lista, valores_de_formulario,
)
from .respuesta import enlace, enlace_url, opcion, respuesta


NEGATIVOS = [
    ('no_reparable', '❌ No se pudo reparar'),
    ('cliente_no_acepta', '🚫 Cliente no quiso reparar'),
]
ESTADO_INGRESO_NEGATIVO = {
    'no_reparable': IngresoEquipoForm.ESTADO_NO_SE_PUDO_REPARAR,
    'cliente_no_acepta': IngresoEquipoForm.ESTADO_NO_QUISO_REPARAR,
}
# Datos del equipo que una finalización nunca debe alterar.
CAMPOS_INTACTOS = (
    'numero_factura', 'asesor_comercial', 'tecnico_encargado', 'fecha_ingreso', 'tipo_equipo',
    'tipo_equipo_otro', 'marca', 'modelo_serie', 'serie', 'accesorios_entregados', 'problema_reportado',
)

ALIAS = {
    'equipo': 'equipo', 'codigo': 'equipo',
    'resultado': 'resultado', 'estado': 'resultado',
    'valor acordado': 'valor_acordado',
    'tecnico': 'tecnico_reparo', 'tecnico que reparo': 'tecnico_reparo',
    'reporte': 'reporte_tecnico', 'reporte del tecnico': 'reporte_tecnico', 'trabajo realizado': 'reporte_tecnico',
    'cobro adicional': 'aplica_adicional', 'valor adicional': 'valor_adicional',
    'motivo': 'motivo_adicional', 'motivo del cobro': 'motivo_adicional',
    'valor de revision': 'valor_revision', 'revision': 'valor_revision',
    'valor por fallos': 'valor_fallos', 'fallos adicionales': 'valor_fallos',
    'pago ahora': 'pago_ahora', 'paga ahora': 'pago_ahora',
    'asesora': 'asesora', 'asesor': 'asesora',
    'fecha': 'fecha_salida', 'fecha de finalizacion': 'fecha_salida',
    'observaciones': 'observaciones', 'observacion': 'observaciones',
    'confirmar pagos': 'confirmar_pagos',
}


def _decimal(valor):
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0')


def motivo_no_finalizable(ingreso):
    """Explica por qué un equipo no puede finalizarse por chat, o ''."""
    if ingreso is None:
        return 'No encontré ese equipo. Revisa el código (por ejemplo G1031).'
    if ingreso.sede not in SEDES_EQUIPOS:
        return f'{ingreso.codigo_equipo} es una venta de producto; no lleva finalización de reparación.'
    if ingreso.estado in ('donado', 'equipo_a_comprar'):
        return (f'{ingreso.codigo_equipo} está como «{ingreso.get_estado_display()}» y se gestiona desde el '
                'Registro Administrativo; no usa la finalización de reparación.')
    salida = getattr(ingreso, 'salida', None)
    if salida is not None:
        return (f'{ingreso.codigo_equipo} ya está finalizado como «{salida.estado_operativo_display}» '
                f'desde el {salida.fecha_salida:%d/%m/%Y}. Si necesitas cambiar algo, usa «Editar finalización».')
    return ''


class FlujoFinalizar(Flujo):
    nombre = 'finalizar'
    titulo = 'Finalizar equipo'
    verbo_confirmar = 'Finalizar equipo'
    pregunta_confirmacion = '¿Finalizo el equipo con estos datos? Responde «sí» para guardar.'
    alias = ALIAS

    def iniciar(self, ingreso):
        self.datos['ingreso_pk'] = ingreso.pk
        self.datos.setdefault('fecha_salida', timezone.localdate().isoformat())
        if usuario_es_tecnico_de_lista(self.user):
            self.datos.setdefault('tecnico_reparo', str(self.user.pk))
        return []

    # ── Datos del equipo ─────────────────────────────────────────────
    def ingreso(self):
        pk = self.datos.get('ingreso_pk')
        return self.cache('ingreso', lambda: IngresoEquipo.objects.select_related('cliente').filter(pk=pk).first())

    def negativo(self):
        return self.datos.get('resultado') in ESTADO_INGRESO_NEGATIVO

    def opciones_resultado(self):
        ingreso = self.ingreso()
        if ingreso is None:
            return []
        formulario = SalidaEquipoForm(instance=SalidaEquipo(ingreso=ingreso))
        opciones = [(valor, etiqueta) for valor, etiqueta in formulario.fields['estado_reparacion'].choices if valor]
        if ingreso.estado in ('ingresado', 'en_reparacion') and not (
                ingreso.equipo_garantia_id or ingreso.equipo_garantia_manual):
            opciones += NEGATIVOS
        return opciones

    def pagos_previos(self):
        ingreso = self.ingreso()
        if ingreso is None:
            return Decimal('0')
        abonos = sum((a.monto for a in ingreso.abonos.all()), Decimal('0.00'))
        diagnostico = ingreso.valor_diagnostico or Decimal('0.00') if ingreso.diagnostico_inmediato == 'si' else Decimal('0.00')
        return (ingreso.abono_anticipo or Decimal('0.00')) + abonos + diagnostico

    def interpretar_especial(self, pregunta, mensaje):
        if pregunta.clave == 'reporte_tecnico':
            t = tx.limpiar(mensaje)
            if t in ('mantener', 'mantener el reporte actual', 'mantener reporte', 'igual', 'el mismo'):
                return (self.ingreso().reporte_tecnico or ''), None
            if tx.es_omitir(mensaje):
                return (self.ingreso().reporte_tecnico or ''), None
        if pregunta.clave in ('tecnico_reparo',) and tx.limpiar(mensaje) in ('yo', 'a mi', 'mi'):
            if usuario_es_tecnico_de_lista(self.user):
                return str(self.user.pk), None
            return None, 'No apareces en la lista de técnicos. Elige al técnico por su nombre o número.'
        return None

    def al_capturar(self, clave, valor):
        if clave == 'final__monto_1':
            completar_monto_2('final', self.datos, self.datos.get('pago_ahora'))
        if clave == 'aplica_adicional' and valor == 'no':
            for c in ('valor_adicional', 'motivo_adicional', 'pago_ahora'):
                self.datos.pop(c, None)
        return []

    # ── Preguntas ────────────────────────────────────────────────────
    def preguntas(self):
        d = self.datos
        ingreso = self.ingreso()
        if ingreso is None:
            return []
        p = [Pregunta('resultado', 'Resultado', f'¿Cómo termina {ingreso.codigo_equipo} ({descripcion_equipo(ingreso)})?',
                      tipo='opcion', opciones=self.opciones_resultado())]
        resultado = d.get('resultado')
        negativo = self.negativo()
        if resultado and not negativo and ingreso.valor_acordado is None:
            p.append(Pregunta('valor_acordado', 'Valor acordado',
                              'Este equipo aún no tiene valor acordado y el sistema lo exige para finalizarlo. '
                              '¿Cuál es el valor acordado?', tipo='dinero'))
        p.append(Pregunta('tecnico_reparo', 'Técnico que reparó', '¿Qué técnico reparó el equipo?',
                          tipo='opcion', opciones=opciones_tecnicos()))
        actual = (ingreso.reporte_tecnico or '').strip()
        p.append(Pregunta(
            'reporte_tecnico', 'Reporte del técnico',
            ('¿Qué se le hizo al equipo? (reporte del técnico)'
             + (f'\nReporte actual: «{tx.norm(actual)[:160]}». Escribe «mantener» para dejarlo igual.' if actual else '')),
            tipo='texto_largo', opcional=True,
            sugerencias=['Mantener el reporte actual'] if actual else [],
        ))
        if resultado == 'pendiente_retiro' or negativo:
            p.append(Pregunta('aplica_adicional', '¿Cobro adicional?',
                              '¿Se acordó con el cliente un cobro adicional? (normalmente no)', tipo='sino'))
            if d.get('aplica_adicional') == 'si':
                p.append(Pregunta('valor_adicional', 'Valor adicional', '¿Cuál es el valor adicional acordado?',
                                  tipo='dinero'))
                p.append(Pregunta('motivo_adicional', 'Motivo del cobro adicional',
                                  '¿Por qué se cobra ese valor adicional?', tipo='texto_largo'))
                if negativo:
                    p.append(Pregunta('pago_ahora', 'Pago recibido ahora',
                                      '¿Cuánto paga el cliente ahora? Escribe 0 si paga después.', tipo='dinero'))
                    if _decimal(d.get('pago_ahora')) > 0:
                        p += preguntas_pago('final', d, 'pago', d.get('pago_ahora'))
        if resultado == 'revision':
            p.append(Pregunta('valor_revision', 'Valor de revisión',
                              '¿Cuál es el valor acordado por la revisión? (mínimo $1,00)', tipo='dinero'))
        if resultado == 'garantia_fallos_adicionales':
            p.append(Pregunta('valor_fallos', 'Valor por fallos adicionales',
                              '¿Cuál es el valor acordado por los fallos adicionales?', tipo='dinero'))
        if resultado and self.necesita_asesora():
            p.append(Pregunta(
                'asesora', 'Asesora a notificar',
                '⚠️ Quedará un saldo pendiente. ¿A qué asesora notifico para que lo cobre antes del retiro?',
                tipo='opcion', opciones=[(str(u.pk), tx.nombre_usuario(u)) for u in _queryset_asesores()],
            ))
        if negativo and self.pagos_previos() > 0:
            p.append(Pregunta(
                'confirmar_pagos', 'Confirmación de pagos previos',
                f'El cliente ya tiene {tx.dinero_legible(self.pagos_previos())} en pagos registrados (anticipo, '
                'abonos o diagnóstico). Al finalizar así, el sistema recalcula esos valores igual que en la web. '
                '¿Confirmas el cambio?', tipo='sino',
            ))
        return p

    # ── Formularios reales ───────────────────────────────────────────
    def reporte(self):
        ingreso = self.ingreso()
        valor = self.datos.get('reporte_tecnico')
        return (ingreso.reporte_tecnico or '') if valor is None else valor

    def campos_salida(self, prefijo=''):
        d = self.datos
        resultado = d.get('resultado', '')
        aplica = d.get('aplica_adicional') == 'si' and (resultado == 'pendiente_retiro' or self.negativo())
        pago = d.get('pago_ahora') if (self.negativo() and aplica) else None
        metodo_final = 'cortesia' if resultado == 'cortesia' else 'sin_pago'
        campos = {
            'fecha_salida': d.get('fecha_salida') or timezone.localdate().isoformat(),
            'estado_reparacion': resultado,
            'tecnico_reparo': d.get('tecnico_reparo', ''),
            'reporte_tecnico': self.reporte(),
            'observaciones': d.get('observaciones', ''),
            'valor_acordado_revision': d.get('valor_revision', '') if resultado == 'revision' else '',
            'aplica_valor_acordado_adicional': 'si' if aplica else 'no',
            'valor_acordado_adicional': d.get('valor_adicional', '') if aplica else '',
            'motivo_valor_acordado_adicional': d.get('motivo_adicional', '') if aplica else '',
            'valor_final_cobrado': (
                d.get('valor_fallos', '0') if resultado == 'garantia_fallos_adicionales'
                else (pago or '0')
            ),
            'metodo_pago_final': metodo_final,
            'numero_recibo': '',
            'banco': '', 'banco_otro': '', 'tarjeta_app': '', 'comprobante_url': '',
            'monto_1': '', 'metodo_1': '', 'banco_1': '', 'monto_2': '', 'metodo_2': '', 'banco_2': '',
            'factura_realizada': 'no', 'factura_nombres': '', 'factura_cedula': '', 'factura_correo': '',
            'asesora_notificacion': d.get('asesora', ''),
            'mensaje_notificacion': '',
        }
        if pago and _decimal(pago) > 0:
            campos.update(post_pago('final', d))
        return {prefijo + clave: valor for clave, valor in campos.items()}

    def post_negativo(self):
        ingreso = IngresoEquipo.objects.select_related('cliente').get(pk=self.datos['ingreso_pk'])
        post = valores_de_formulario(ClienteForm(prefix='cli', instance=ingreso.cliente))
        post.update(valores_de_formulario(
            IngresoEquipoForm(prefix='ing', instance=ingreso, permitir_finalizacion_rapida=True)
        ))
        post['ing-estado'] = ESTADO_INGRESO_NEGATIVO[self.datos['resultado']]
        post.update(self.campos_salida('salida-'))
        if self.datos.get('confirmar_pagos') == 'si':
            post['confirmar_finalizacion_con_pago'] = '1'
        return post

    def validar_negativo(self, post):
        """Misma validación que `ingreso_editar`, sin guardar nada."""
        ingreso = IngresoEquipo.objects.select_related('cliente').get(pk=self.datos['ingreso_pk'])
        cli_form = ClienteForm(post, prefix='cli', instance=ingreso.cliente)
        ing_form = IngresoEquipoForm(post, prefix='ing', instance=ingreso, permitir_finalizacion_rapida=True)
        errores = {}
        if not cli_form.is_valid() or not ing_form.is_valid():
            for formulario in (cli_form, ing_form):
                for nombre, lista in formulario.errors.items():
                    errores.setdefault('__all__', []).extend(f'{nombre}: {e}' for e in lista)
            return errores, None
        alterados = (set(ing_form.changed_data) & set(CAMPOS_INTACTOS)) | set(cli_form.changed_data)
        if alterados:
            errores['__all__'] = ['No pude reproducir el formulario del equipo sin cambiar otros datos '
                                  f'({", ".join(sorted(alterados))}). Finalízalo desde «Editar estado».']
            return errores, None
        preview = ing_form.save(commit=False)
        salida_form = vistas._form_salida_rapida(solicitud_interna(self.request, post), self.user, ingreso=preview)
        salida_form.is_valid()
        return dict(salida_form.errors), salida_form

    def formulario_positivo(self):
        ingreso = IngresoEquipo.objects.select_related('cliente').get(pk=self.datos['ingreso_pk'])
        valor = self.datos.get('valor_acordado')
        if ingreso.valor_acordado is None and valor not in (None, ''):
            # Solo en memoria: se valida el saldo tal como quedará al registrar el valor primero.
            ingreso.valor_acordado = _decimal(valor)
        return SalidaEquipoForm(self.campos_salida(), instance=SalidaEquipo(ingreso=ingreso))

    def errores_salida(self):
        return self.cache('errores_salida', self._errores_salida)

    def _errores_salida(self):
        if self.negativo():
            errores, _ = self.validar_negativo(self.post_negativo())
            return errores
        formulario = self.formulario_positivo()
        formulario.is_valid()
        return dict(formulario.errors)

    def necesita_asesora(self):
        if self.datos.get('asesora'):
            return True
        return self.cache('necesita_asesora', lambda: 'asesora_notificacion' in self.errores_salida())

    def errores(self):
        return self.cache('errores', self._calcular_errores)

    def _calcular_errores(self):
        crudos = self.errores_salida()
        mapa = {
            'estado_reparacion': 'resultado', 'tecnico_reparo': 'tecnico_reparo',
            'reporte_tecnico': 'reporte_tecnico', 'valor_acordado_revision': 'valor_revision',
            'valor_acordado_adicional': 'valor_adicional', 'motivo_valor_acordado_adicional': 'motivo_adicional',
            'asesora_notificacion': 'asesora', 'fecha_salida': 'fecha_salida', 'observaciones': 'observaciones',
            '__all__': '__all__',
        }
        errores = {}
        for nombre, lista in crudos.items():
            if nombre == 'valor_final_cobrado':
                clave = 'valor_fallos' if self.datos.get('resultado') == 'garantia_fallos_adicionales' else 'pago_ahora'
            elif nombre == 'asesora_notificacion' and not self.datos.get('asesora'):
                continue  # Se pregunta cuando corresponde; no es un error del usuario.
            else:
                clave = mapa.get(nombre)
            if clave:
                errores.setdefault(clave, []).extend(str(e) for e in lista)
        errores.update(errores_pago('final', crudos))
        if self.datos.get('confirmar_pagos') == 'no':
            errores.setdefault('confirmar_pagos', []).append(
                'Sin esa confirmación no puedo finalizarlo así. Responde «sí» o escribe «cancelar».')
        valor = self.datos.get('valor_acordado')
        if valor is not None and _decimal(valor) < 0:
            errores.setdefault('valor_acordado', []).append('El valor acordado no puede ser negativo.')
        return errores

    # ── Resumen y guardado ───────────────────────────────────────────
    def resumen(self):
        d = self.datos
        ingreso = self.ingreso()
        resultado = etiqueta_de(self.opciones_resultado(), d.get('resultado'))
        lineas = [f'📝 Finalización de {ingreso.codigo_equipo} — {descripcion_equipo(ingreso)} '
                  f'({ingreso.cliente.nombres}):']
        lineas.append(f'• Resultado: {resultado}')
        if d.get('valor_acordado') is not None and ingreso.valor_acordado is None:
            lineas.append(f'• Valor acordado (se registrará primero): {tx.dinero_legible(d["valor_acordado"])}')
        lineas.append(f'• Técnico que reparó: {etiqueta_de(opciones_tecnicos(), d.get("tecnico_reparo"))}')
        reporte = self.reporte().strip()
        lineas.append(f'• Reporte: {reporte[:220] if reporte else "(sin reporte)"}')
        if d.get('aplica_adicional') == 'si':
            lineas.append(f'• Cobro adicional: {tx.dinero_legible(d.get("valor_adicional"))} — {d.get("motivo_adicional", "")}')
            if self.negativo():
                pago = _decimal(d.get('pago_ahora'))
                lineas.append('• Pago ahora: ' + (
                    f'{tx.dinero_legible(pago)} ({resumen_pago("final", d)})' if pago > 0 else 'No paga ahora'))
        if d.get('resultado') == 'revision':
            lineas.append(f'• Valor de revisión: {tx.dinero_legible(d.get("valor_revision"))}')
        if d.get('resultado') == 'garantia_fallos_adicionales':
            lineas.append(f'• Valor por fallos adicionales: {tx.dinero_legible(d.get("valor_fallos"))}')
        if d.get('asesora'):
            asesoras = [(str(u.pk), tx.nombre_usuario(u)) for u in _queryset_asesores()]
            lineas.append(f'• Se notificará a: {etiqueta_de(asesoras, d["asesora"])} (saldo pendiente)')
        lineas.append(f'• Fecha de finalización: {tx.fecha_legible(d.get("fecha_salida"))}')
        if d.get('observaciones'):
            lineas.append(f'• Observaciones: {d["observaciones"]}')
        lineas.append('El equipo quedará registrado dentro de la oficina hasta confirmar su salida física.')
        return '\n'.join(lineas)

    def ejecutar(self):
        from .flujo import siguiente
        ingreso = self.ingreso()
        motivo = motivo_no_finalizable(IngresoEquipo.objects.filter(pk=self.datos.get('ingreso_pk')).first())
        if motivo:
            return respuesta(motivo, hecho=True)
        self.olvidar_cache()
        errores = {clave: lista for clave, lista in self.errores().items() if lista}
        claves = {p.clave for p in self.preguntas()}
        if any(clave in claves for clave in errores):
            return siguiente(self, ['Antes de guardar hay que corregir un dato:'])
        if errores:
            return respuesta(
                'No puedo finalizarlo por chat: ' + ' '.join(sum(errores.values(), [])),
                [enlace('Abrir el equipo', 'ingreso_detalle', pk=ingreso.pk)],
                [opcion('Cancelar', 'cancelar')],
            )

        punto = transaction.savepoint()
        if self.negativo():
            resultado = enviar(self.request, vistas.ingreso_editar, pk=ingreso.pk, datos=self.post_negativo())
        else:
            if ingreso.valor_acordado is None:
                valor = enviar(self.request, views_pagos.ingreso_valor_acordado_editar, pk=ingreso.pk,
                               datos={'valor_acordado': self.datos.get('valor_acordado', '')})
                ingreso.refresh_from_db()
                if ingreso.valor_acordado is None:
                    transaction.savepoint_rollback(punto)
                    detalle = ' '.join(valor.errores + valor.mensajes_de('warning')) or 'El valor no se aceptó.'
                    return respuesta(f'No pude registrar el valor acordado: {detalle} No se guardó nada.')
            resultado = enviar(self.request, vistas.salida_registrar, ingreso_pk=ingreso.pk,
                               datos=self.campos_salida())
        if resultado.destino_nombre != 'salida_listo_aviso':
            transaction.savepoint_rollback(punto)
            detalle = ' '.join(resultado.errores + resultado.mensajes_de('warning')) or 'El sistema no aceptó los datos.'
            return respuesta(
                f'No pude finalizar {ingreso.codigo_equipo}: {detalle} No se guardó nada.',
                [enlace('Abrir el equipo', 'ingreso_detalle', pk=ingreso.pk)],
                [opcion('✅ Intentar de nuevo', 'sí'), opcion('Cancelar', 'cancelar')],
            )
        transaction.savepoint_commit(punto)
        salida = SalidaEquipo.objects.select_related('ingreso', 'ingreso__cliente', 'tecnico_reparo').get(
            pk=resultado.destino_kwargs['pk'])
        return exito_finalizacion(salida, resultado)


def exito_finalizacion(salida, resultado):
    ingreso = salida.ingreso
    ingreso.refresh_from_db()
    lineas = [
        f'✅ Listo: {ingreso.codigo_equipo} quedó finalizado como «{salida.get_estado_reparacion_display()}».',
        f'Técnico que reparó: {salida.tecnico_reparo_nombre or "—"}',
    ]
    saldo = ingreso.diferencia
    if saldo > 0:
        lineas.append(f'Saldo pendiente del cliente: {tx.dinero_legible(saldo)}. No podrá retirar el equipo hasta pagarlo.')
    else:
        lineas.append('El cliente no tiene saldo pendiente.')
    lineas.append('El equipo sigue en la oficina hasta que confirmes su salida física.')
    enlaces = [
        enlace('Ver aviso y confirmar ubicación', 'salida_listo_aviso', pk=salida.pk),
        enlace_url('Avisar al cliente por WhatsApp', whatsapp_link_equipo_listo(salida)),
        enlace('Acta de finalización (PDF)', 'salida_pdf', pk=salida.pk, tipo='nueva'),
        enlace('Ver equipo', 'ingreso_detalle', pk=ingreso.pk),
    ]
    opciones = []
    if (ingreso.cliente.correo or '').strip() and getattr(settings, 'SALIDA_EMAIL_AUTOMATICO', True):
        opciones.append(opcion('📧 Enviar acta por correo', f'enviar acta {ingreso.codigo_equipo}'))
    if saldo <= 0:
        opciones.append(opcion('🚚 Confirmar salida física', f'confirmar salida {ingreso.codigo_equipo}'))
    opciones.append(opcion(f'Ver {ingreso.codigo_equipo}', f'ver {ingreso.codigo_equipo}'))
    return respuesta('\n'.join(lineas), enlaces, opciones, hecho=True, ultimo_equipo=ingreso.pk)
