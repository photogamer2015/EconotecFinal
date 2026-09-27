"""Registro de un equipo nuevo por chat.

Reúne los mismos datos de la «Solicitud de Ingreso», los valida con
ClienteForm e IngresoEquipoForm y, al confirmar, los envía a la vista
original `ingreso_registrar`. El equipo, el cliente, la bitácora y el
correo se crean exactamente igual que desde la página.
"""
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone

from .. import views as vistas
from ..alertas import whatsapp_link_hoja_ingreso
from ..forms import ClienteForm, IngresoEquipoForm
from ..models import (
    Cliente, IngresoEquipo, SECTORES, SEDE_PREFIJOS, SUBESTADO_EN_REPARACION, TIPOS_EQUIPO,
)
from . import texto as tx
from .enviar import enviar
from .flujo import Flujo, Pregunta
from .formularios import (
    a_texto, errores_pago, etiqueta_de, opciones_asesores, opciones_tecnicos, post_pago,
    preguntas_pago, completar_monto_2, resumen_pago, usuario_es_asesor_de_lista,
    usuario_es_tecnico_de_lista, valores_de_formulario,
)
from .respuesta import enlace, enlace_url, opcion, respuesta


ESTADOS = [
    ('ingresado', 'Ingresado / En diagnóstico'),
    ('en_reparacion', 'En reparación'),
    ('garantia', 'Garantía'),
    ('cortesia', 'Cortesía'),
    ('donado', 'Donado'),
    ('equipo_a_comprar', 'Equipo a comprar'),
]
SUBESTADOS = [(valor, etiqueta) for valor, etiqueta in SUBESTADO_EN_REPARACION if valor]
ESTADOS_NORMALES = ('ingresado', 'en_reparacion')
ESTADOS_SIN_ANTICIPO = ('cortesia', 'donado', 'equipo_a_comprar')
ESTADOS_ADMINISTRATIVOS = ('donado', 'equipo_a_comprar')
CAMPOS_CLIENTE = ('cedula', 'nombres', 'whatsapp', 'correo', 'sector', 'sector_otro')

ALIAS = {
    'cedula': 'cedula', 'ruc': 'cedula', 'cedula o ruc': 'cedula', 'documento': 'cedula',
    'nombre': 'nombres', 'nombres': 'nombres', 'cliente': 'nombres', 'nombre del cliente': 'nombres',
    'nombres del cliente': 'nombres',
    'whatsapp': 'whatsapp', 'wsp': 'whatsapp', 'celular': 'whatsapp', 'telefono': 'whatsapp',
    'correo': 'correo', 'email': 'correo', 'mail': 'correo',
    'sector': 'sector', 'sector otro': 'sector_otro',
    'equipo': 'tipo_equipo', 'tipo': 'tipo_equipo', 'tipo de equipo': 'tipo_equipo',
    'tipo otro': 'tipo_equipo_otro', 'otro equipo': 'tipo_equipo_otro',
    'marca': 'marca', 'modelo': 'modelo_serie', 'serie': 'serie', 'numero de serie': 'serie',
    'serial': 'serie',
    'accesorios': 'accesorios_entregados', 'trajo accesorios': 'trajo_accesorios',
    'problema': 'problema_reportado', 'problema reportado': 'problema_reportado', 'falla': 'problema_reportado',
    'dano': 'problema_reportado',
    'estado': 'estado', 'detalle': 'subestado_reparacion', 'detalle de reparacion': 'subestado_reparacion',
    'motivo': 'motivo_garantia', 'motivo de garantia': 'motivo_garantia',
    'equipo anterior': 'equipo_garantia',
    'asesor': 'asesor_comercial', 'asesora': 'asesor_comercial', 'asesora comercial': 'asesor_comercial',
    'asesor comercial': 'asesor_comercial', 'vendedora': 'asesor_comercial',
    'tecnico': 'tecnico_encargado', 'tecnico encargado': 'tecnico_encargado', 'tecnico recibido': 'tecnico_encargado',
    'fecha': 'fecha_ingreso', 'fecha de ingreso': 'fecha_ingreso',
    'factura': 'numero_factura', 'numero de factura': 'numero_factura',
    'valor': 'valor_acordado', 'valor acordado': 'valor_acordado', 'precio': 'valor_acordado',
    'valor de compra': 'valor_acordado', 'tiene valor acordado': 'valor_acordado_estado',
    'diagnostico': 'diagnostico_inmediato', 'diagnostico inmediato': 'diagnostico_inmediato',
    'valor del diagnostico': 'valor_diagnostico', 'valor diagnostico': 'valor_diagnostico',
    'abono': 'abono_anticipo', 'anticipo': 'abono_anticipo', 'abono / anticipo': 'abono_anticipo',
    'firma': 'firma_cliente_opcion', 'firma del cliente': 'firma_cliente_opcion',
    'reingreso': 'reingreso', 'reingreso del mismo equipo': 'reingreso',
}


def _decimal(valor):
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0')


class FlujoIngreso(Flujo):
    nombre = 'ingreso'
    titulo = 'Registro de equipo'
    verbo_confirmar = 'Registrar equipo'
    pregunta_confirmacion = '¿Registro el equipo con estos datos? Responde «sí» para guardar.'
    alias = ALIAS

    # ── Inicio ───────────────────────────────────────────────────────
    def iniciar(self, mensaje=''):
        d = self.datos
        d.setdefault('fecha_ingreso', timezone.localdate().isoformat())
        if usuario_es_tecnico_de_lista(self.user):
            d.setdefault('tecnico_encargado', str(self.user.pk))
        if usuario_es_asesor_de_lista(self.user):
            d.setdefault('asesor_comercial', tx.nombre_usuario(self.user))
        avisos = []
        cedula = tx.cedula_en(mensaje)
        if cedula:
            d['cedula'] = cedula
            avisos += self.al_capturar('cedula', cedula)
        tipo = self._tipo_en(mensaje)
        if tipo:
            d['tipo_equipo'] = tipo
        return avisos

    @staticmethod
    def _tipo_en(mensaje):
        t = tx.limpiar(mensaje)
        palabras = {
            'laptop': 'laptop', 'laptops': 'laptop', 'portatil': 'laptop', 'notebook': 'laptop',
            'impresora': 'impresora', 'celular': 'celular', 'telefono': 'celular', 'iphone': 'celular',
            'tablet': 'tablet', 'ipad': 'tablet', 'consola': 'consola', 'play': 'consola',
            'playstation': 'consola', 'xbox': 'consola', 'nintendo': 'consola', 'mando': 'mando',
            'control': 'mando', 'monitor': 'monitor', 'cpu': 'cpu', 'pc': 'pc', 'computadora': 'pc',
        }
        for palabra in t.split():
            if palabra in palabras:
                return palabras[palabra]
        if 'maquina de coser' in t:
            return 'maquina_coser'
        return ''

    # ── Datos relacionados ───────────────────────────────────────────
    def cliente_existente(self):
        pk = self.datos.get('_cliente_pk')
        if not pk:
            return None
        return self.cache('cliente', lambda: Cliente.objects.filter(pk=pk).first())

    def equipos_previos(self):
        cliente = self.cliente_existente()
        if not cliente:
            return []
        return self.cache('previos', lambda: [
            (str(eq.pk), f'{eq.codigo_equipo} — {eq.tipo_equipo_display} {eq.marca} {eq.modelo_serie}')
            for eq in cliente.ingresos.order_by('-creado')[:12]
        ])

    def duplicado(self):
        cliente = self.cliente_existente()
        if not cliente or not self.datos.get('modelo_serie'):
            return None
        return self.cache('duplicado', lambda: vistas._equipo_duplicado_para_cliente(
            cliente, {
                'tipo_equipo': self.datos.get('tipo_equipo', ''),
                'tipo_equipo_otro': self.datos.get('tipo_equipo_otro', ''),
                'marca': self.datos.get('marca', ''),
                'modelo_serie': self.datos.get('modelo_serie', ''),
            },
        ))

    def al_capturar(self, clave, valor):
        d = self.datos
        avisos = []
        if clave == 'cedula':
            anterior = d.get('_cliente_pk')
            cliente = Cliente.objects.filter(cedula=valor).first()
            # Si cambia la cédula se descartan los datos traídos del cliente anterior.
            for campo in d.pop('_precargados', []):
                d.pop(campo, None)
            d.pop('_cliente_pk', None)
            d.pop('reingreso', None)
            if cliente:
                d['_cliente_pk'] = cliente.pk
                precargados = []
                for campo in CAMPOS_CLIENTE[1:]:
                    if campo not in d:
                        d[campo] = getattr(cliente, campo) or ''
                        precargados.append(campo)
                d['_precargados'] = precargados
                total = cliente.ingresos.count()
                ultimos = ', '.join(eq.codigo_equipo for eq in cliente.ingresos.order_by('-creado')[:3])
                avisos.append(
                    f'Cliente encontrado: {cliente.nombres}. Usaré sus datos registrados '
                    f'(WhatsApp: {cliente.whatsapp or "—"}, correo: {cliente.correo or "—"}).'
                    + (f' Tiene {total} equipo{"s" if total != 1 else ""} registrado{"s" if total != 1 else ""} ({ultimos}).' if total else '')
                    + ' Si algo cambió, corrígelo con «whatsapp: …» o «correo: …».'
                )
            elif anterior:
                avisos.append('Es una cédula nueva: registraré un cliente nuevo.')
        elif clave == 'accesorios_entregados':
            d['trajo_accesorios'] = 'si'
        elif clave == 'trajo_accesorios' and valor == 'no':
            d.pop('accesorios_entregados', None)
        elif clave == 'valor_acordado' and d.get('estado') in ESTADOS_NORMALES + (None,):
            d['valor_acordado_estado'] = 'si'
        elif clave == 'valor_acordado_estado' and valor == 'no':
            d.pop('valor_acordado', None)
        elif clave == 'valor_diagnostico':
            d['diagnostico_inmediato'] = 'si'
        elif clave == 'diagnostico_inmediato' and valor == 'no':
            d.pop('valor_diagnostico', None)
        elif clave == 'firma_cliente_opcion' and valor == 'no':
            d.pop('firma_cliente_imagen', None)
        elif clave in ('modelo_serie', 'marca', 'tipo_equipo'):
            d.pop('reingreso', None)
        elif clave == 'anticipo__monto_1':
            completar_monto_2('anticipo', d, d.get('abono_anticipo'))
        elif clave == 'diagnostico__monto_1':
            completar_monto_2('diagnostico', d, d.get('valor_diagnostico'))
        elif clave == 'compra__monto_1':
            completar_monto_2('compra', d, d.get('valor_acordado'))
        return avisos

    def interpretar_especial(self, pregunta, mensaje):
        if pregunta.clave == 'cedula':
            valor = tx.solo_digitos(tx.solo_espacios_numericos(mensaje))
            if len(valor) < 6:
                return None, 'Escribe la cédula o RUC completo (solo números).'
            return valor, None
        if pregunta.clave == 'whatsapp':
            if tx.es_omitir(mensaje):
                return '', None
            valor = tx.solo_digitos(tx.solo_espacios_numericos(mensaje))
            if len(valor) < 7:
                return None, 'Escribe el número completo (solo números) o «omitir».'
            return valor, None
        if pregunta.clave in ('asesor_comercial', 'tecnico_encargado') and tx.limpiar(mensaje) in ('yo', 'a mi', 'mi'):
            if pregunta.clave == 'tecnico_encargado' and usuario_es_tecnico_de_lista(self.user):
                return str(self.user.pk), None
            if pregunta.clave == 'asesor_comercial' and usuario_es_asesor_de_lista(self.user):
                return tx.nombre_usuario(self.user), None
            return None, 'No apareces en esa lista. Elige a la persona por su nombre o número.'
        if pregunta.clave == 'firma_cliente_imagen' and tx.es_no(mensaje):
            self.datos['firma_cliente_opcion'] = 'no'
            return '', None
        return None

    # ── Preguntas ────────────────────────────────────────────────────
    def preguntas(self):
        d = self.datos
        p = []
        p.append(Pregunta('cedula', 'Cédula / RUC', '¿Cuál es la cédula o RUC del cliente?', tipo='digitos'))
        if not d.get('_cliente_pk'):
            p.append(Pregunta('nombres', 'Nombres del cliente', '¿Nombres y apellidos del cliente?', libre=True))
        p.append(Pregunta('whatsapp', 'WhatsApp', '¿Número de WhatsApp del cliente?', tipo='digitos', opcional=True))
        p.append(Pregunta('correo', 'Correo', '¿Correo del cliente? Ahí le llegará su comprobante.',
                          tipo='correo', opcional=True))
        p.append(Pregunta('sector', 'Sector', '¿De qué sector es el cliente?', tipo='opcion',
                          opciones=SECTORES, opcional=True))
        if d.get('sector') == 'otro':
            p.append(Pregunta('sector_otro', 'Sector (otro)', '¿Qué sector? Escríbelo.', libre=True))
        p.append(Pregunta('tipo_equipo', 'Tipo de equipo', '¿Qué tipo de equipo es?', tipo='opcion',
                          opciones=TIPOS_EQUIPO))
        if d.get('tipo_equipo') == 'otro':
            p.append(Pregunta('tipo_equipo_otro', 'Tipo (otro)', '¿Qué equipo es? Especifícalo.', libre=True))
        p.append(Pregunta('marca', 'Marca', '¿Marca del equipo?', libre=True))
        p.append(Pregunta('modelo_serie', 'Modelo', '¿Modelo del equipo?', libre=True))
        p.append(Pregunta('serie', 'Serie', '¿Número de serie?', opcional=True, libre=True))
        p.append(Pregunta('trajo_accesorios', 'Trajo accesorios',
                          '¿El cliente dejó accesorios (cargador, cable, control…)?', tipo='sino'))
        if d.get('trajo_accesorios') == 'si':
            p.append(Pregunta('accesorios_entregados', 'Accesorios', '¿Qué accesorios dejó?', libre=True))
        p.append(Pregunta('problema_reportado', 'Problema reportado',
                          '¿Qué problema reporta el cliente?', tipo='texto_largo'))
        if self.duplicado():
            dup = self.duplicado()
            p.append(Pregunta(
                'reingreso', 'Reingreso del mismo equipo',
                f'⚠️ Este cliente ya tiene registrado el mismo equipo ({dup.codigo_equipo} — '
                f'{dup.tipo_equipo_display} {dup.marca} {dup.modelo_serie}). '
                '¿Es un reingreso del mismo equipo? Si respondes «sí» se registrará como un ingreso nuevo '
                'y se conservará el historial anterior.',
                tipo='sino',
            ))
        p.append(Pregunta('estado', 'Estado', '¿En qué estado ingresa el equipo?', tipo='opcion',
                          opciones=ESTADOS))
        estado = d.get('estado')
        if estado == 'en_reparacion':
            p.append(Pregunta('subestado_reparacion', 'Detalle de reparación',
                              '¿Qué detalle de reparación aplica?', tipo='opcion', opciones=SUBESTADOS))
        if estado == 'garantia':
            p.append(Pregunta('motivo_garantia', 'Motivo de garantía',
                              '¿Cuál es el motivo de la garantía?', tipo='texto_largo'))
            if self.equipos_previos():
                p.append(Pregunta('equipo_garantia', 'Equipo anterior',
                                  '¿A qué equipo anterior del cliente aplica la garantía?', tipo='opcion',
                                  opciones=self.equipos_previos(), opcional=True))
        p.append(Pregunta('asesor_comercial', 'Asesora comercial', '¿Qué asesora atendió al cliente?',
                          tipo='opcion', opciones=opciones_asesores()))
        p.append(Pregunta('tecnico_encargado', 'Técnico que recibe', '¿Qué técnico recibe el equipo?',
                          tipo='opcion', opciones=opciones_tecnicos()))
        if estado in ESTADOS_NORMALES:
            p.append(Pregunta('valor_acordado_estado', '¿Tiene valor acordado?',
                              '¿Ya tienes el valor acordado de la reparación?', tipo='sino'))
            if d.get('valor_acordado_estado') == 'si':
                p.append(Pregunta('valor_acordado', 'Valor acordado',
                                  '¿Cuál es el valor acordado? (mínimo $1,00)', tipo='dinero'))
            p.append(Pregunta('diagnostico_inmediato', 'Diagnóstico inmediato',
                              '¿Se cobró un diagnóstico inmediato?', tipo='sino'))
            if d.get('diagnostico_inmediato') == 'si':
                p.append(Pregunta('valor_diagnostico', 'Valor del diagnóstico',
                                  '¿Cuánto se cobró por el diagnóstico?', tipo='dinero'))
                if _decimal(d.get('valor_diagnostico')) > 0:
                    p += preguntas_pago('diagnostico', d, 'diagnóstico', d.get('valor_diagnostico'))
        if estado == 'equipo_a_comprar':
            p.append(Pregunta('valor_acordado', 'Valor de compra',
                              '¿Cuánto se paga por el equipo (valor de compra)?', tipo='dinero'))
            if _decimal(d.get('valor_acordado')) > 0:
                p += preguntas_pago('compra', d, 'valor de compra', d.get('valor_acordado'))
        if estado and estado not in ESTADOS_SIN_ANTICIPO:
            p.append(Pregunta('abono_anticipo', 'Abono / anticipo',
                              '¿El cliente dejó abono o anticipo? Escribe el monto o «no».', tipo='dinero',
                              sugerencias=['No']))
            if _decimal(d.get('abono_anticipo')) > 0:
                p += preguntas_pago('anticipo', d, 'abono / anticipo', d.get('abono_anticipo'))
        if estado and estado not in ESTADOS_ADMINISTRATIVOS:
            p.append(Pregunta('firma_cliente_opcion', 'Firma del cliente',
                              '¿El cliente va a firmar la solicitud de ingreso?', tipo='sino'))
            if d.get('firma_cliente_opcion') == 'si':
                p.append(Pregunta('firma_cliente_imagen', 'Firma',
                                  'Pídele al cliente que firme en el recuadro y pulsa «Guardar firma».',
                                  tipo='firma'))
        return p

    # ── Formularios reales ───────────────────────────────────────────
    def sede(self):
        return (self.request.session.get('sede_actual') or '').strip().lower()

    def post(self):
        d = self.datos
        activos = {p.clave for p in self.preguntas()}
        cliente = self.cliente_existente()
        base_cliente = ClienteForm(prefix='cli', instance=cliente) if cliente else ClienteForm(prefix='cli')
        post = valores_de_formulario(base_cliente)
        for campo in CAMPOS_CLIENTE:
            if campo in d:
                post['cli-' + campo] = d[campo]
        if 'sector' in d and d.get('sector') != 'otro':
            post['cli-sector_otro'] = ''

        inicial = {
            'fecha_ingreso': timezone.localdate(),
            'diagnostico_inmediato': 'no',
            'valor_diagnostico': '0.00',
            'valor_acordado': '',
            'abono_anticipo': '0.00',
        }
        base_ingreso = IngresoEquipoForm(prefix='ing', initial=inicial, permitir_finalizacion_rapida=True)
        post.update(valores_de_formulario(base_ingreso))
        directos = (
            'tipo_equipo', 'tipo_equipo_otro', 'marca', 'modelo_serie', 'serie', 'problema_reportado',
            'estado', 'subestado_reparacion', 'motivo_garantia', 'equipo_garantia', 'asesor_comercial',
            'tecnico_encargado', 'valor_acordado_estado', 'valor_acordado', 'diagnostico_inmediato',
            'valor_diagnostico', 'abono_anticipo', 'firma_cliente_opcion', 'firma_cliente_imagen',
        )
        for campo in directos:
            if campo in d and campo in activos:
                post['ing-' + campo] = d[campo]
        post['ing-fecha_ingreso'] = d.get('fecha_ingreso') or a_texto(timezone.localdate())
        post['ing-numero_factura'] = d.get('numero_factura', '')
        post['ing-accesorios_entregados'] = (
            d.get('accesorios_entregados', '') if d.get('trajo_accesorios') == 'si' else 'Ninguno'
        )
        firma = d.get('firma_cliente_imagen') if d.get('firma_cliente_opcion') == 'si' else ''
        post['ing-firma_cliente_imagen'] = firma or ''
        post['ing-firma_cliente'] = 'true' if firma else 'false'
        estado = d.get('estado')
        if estado == 'equipo_a_comprar':
            post['ing-valor_acordado_estado'] = 'si'
            post['ing-valor_acordado'] = d.get('valor_acordado', '')
            post.update(post_pago('compra', d, 'ing-'))
        if estado in ESTADOS_NORMALES and d.get('diagnostico_inmediato') == 'si' and _decimal(d.get('valor_diagnostico')) > 0:
            post.update(post_pago('diagnostico', d, 'ing-'))
        if estado not in ESTADOS_SIN_ANTICIPO and _decimal(d.get('abono_anticipo')) > 0:
            post.update(post_pago('anticipo', d, 'ing-'))
        if d.get('reingreso') == 'si':
            post['confirmar_mismo_equipo_cliente'] = '1'
        post['trajo_accesorios'] = d.get('trajo_accesorios', '')
        return post

    def formularios(self, post):
        cliente = Cliente.objects.filter(cedula=post.get('cli-cedula', '')).first() if post.get('cli-cedula') else None
        cli_form = ClienteForm(post, prefix='cli', instance=cliente)
        ing_form = IngresoEquipoForm(post, prefix='ing', permitir_finalizacion_rapida=True)
        return cli_form, ing_form

    def errores(self):
        return self.cache('errores', self._calcular_errores)

    def _calcular_errores(self):
        d = self.datos
        cli_form, ing_form = self.formularios(self.post())
        cli_form.is_valid()
        ing_form.is_valid()
        crudos = {}
        for nombre, lista in cli_form.errors.items():
            crudos.setdefault(nombre, []).extend(lista)
        for nombre, lista in ing_form.errors.items():
            crudos.setdefault(nombre, []).extend(lista)
        errores = {}
        for nombre, lista in crudos.items():
            clave = nombre
            if nombre == 'accesorios_entregados' and d.get('trajo_accesorios') != 'si':
                clave = 'trajo_accesorios'
            if nombre == 'firma_cliente_opcion':
                clave = 'firma_cliente_imagen' if d.get('firma_cliente_opcion') == 'si' else 'firma_cliente_opcion'
            if nombre == '__all__':
                clave = '__all__'
            errores.setdefault(clave, []).extend(str(e) for e in lista)
        for grupo in ('anticipo', 'diagnostico', 'compra'):
            errores.update(errores_pago(grupo, ing_form.errors))
        if d.get('reingreso') == 'no' and self.duplicado():
            errores.setdefault('modelo_serie', []).append(
                f'Ese modelo coincide con {self.duplicado().codigo_equipo} del mismo cliente. '
                'Corrige el modelo o, si es el mismo equipo, confirma el reingreso.'
            )
        return errores

    # ── Resumen y guardado ───────────────────────────────────────────
    def resumen(self):
        d = self.datos
        cliente = self.cliente_existente()
        sede = self.sede()
        estado = d.get('estado')
        tipo = etiqueta_de(TIPOS_EQUIPO, d.get('tipo_equipo'))
        if d.get('tipo_equipo') == 'otro' and d.get('tipo_equipo_otro'):
            tipo = d['tipo_equipo_otro']
        lineas = ['📝 Revisa los datos del ingreso:']
        lineas.append(f'• Cliente: {d.get("nombres") or (cliente.nombres if cliente else "—")} — '
                      f'Cédula {d.get("cedula", "—")} ({"ya registrado" if cliente else "cliente nuevo"})')
        sector = etiqueta_de(SECTORES, d.get('sector'))
        if d.get('sector') == 'otro' and d.get('sector_otro'):
            sector = d['sector_otro']
        lineas.append(f'• WhatsApp: {d.get("whatsapp") or "—"} · Correo: {d.get("correo") or "—"} · Sector: {sector}')
        lineas.append(f'• Equipo: {tipo} {d.get("marca", "")} — Modelo {d.get("modelo_serie", "—")}'
                      + (f' · Serie {d["serie"]}' if d.get('serie') else ''))
        lineas.append('• Accesorios: ' + (d.get('accesorios_entregados') or 'Ninguno'
                                           if d.get('trajo_accesorios') == 'si' else 'Ninguno'))
        lineas.append(f'• Problema: {d.get("problema_reportado", "—")}')
        texto_estado = etiqueta_de(ESTADOS, estado)
        if estado == 'en_reparacion':
            texto_estado += f' — {etiqueta_de(SUBESTADOS, d.get("subestado_reparacion"))}'
        if estado == 'garantia':
            texto_estado += f' — Motivo: {d.get("motivo_garantia", "—")}'
            if d.get('equipo_garantia'):
                texto_estado += f' ({etiqueta_de(self.equipos_previos(), d["equipo_garantia"])})'
        if d.get('reingreso') == 'si':
            texto_estado += ' · Reingreso confirmado'
        lineas.append(f'• Estado: {texto_estado}')
        lineas.append(f'• Asesora: {d.get("asesor_comercial") or "—"} · Técnico: '
                      f'{etiqueta_de(opciones_tecnicos(), d.get("tecnico_encargado"))} · Fecha: '
                      f'{tx.fecha_legible(d.get("fecha_ingreso"))}'
                      + (f' · Factura N° {d["numero_factura"]}' if d.get('numero_factura') else ''))
        if estado in ESTADOS_NORMALES:
            valor = tx.dinero_legible(d.get('valor_acordado')) if d.get('valor_acordado_estado') == 'si' else 'Pendiente'
            lineas.append(f'• Valor acordado: {valor}')
            if d.get('diagnostico_inmediato') == 'si':
                lineas.append(f'• Diagnóstico inmediato: {tx.dinero_legible(d.get("valor_diagnostico"))}'
                              f' ({resumen_pago("diagnostico", d)})')
            else:
                lineas.append('• Diagnóstico inmediato: No')
        if estado == 'equipo_a_comprar':
            lineas.append(f'• Valor de compra: {tx.dinero_legible(d.get("valor_acordado"))} ({resumen_pago("compra", d)})')
        if estado not in ESTADOS_SIN_ANTICIPO:
            anticipo = _decimal(d.get('abono_anticipo'))
            lineas.append('• Abono / anticipo: ' + (
                f'{tx.dinero_legible(anticipo)} ({resumen_pago("anticipo", d)})' if anticipo > 0 else 'No'))
        if estado not in ESTADOS_ADMINISTRATIVOS:
            lineas.append('• Firma del cliente: ' + ('Sí (capturada)' if d.get('firma_cliente_imagen') else 'No firma'))
        if sede in SEDE_PREFIJOS:
            codigo = f'{SEDE_PREFIJOS[sede]}{IngresoEquipo.siguiente_numero_equipo(sede)}'
            lineas.append(f'Se registrará como {codigo} en {sede.capitalize()}.')
        return '\n'.join(lineas)

    def ejecutar(self):
        from .flujo import siguiente
        if self.sede() not in ('guayaquil', 'quito'):
            return respuesta('Tu sesión no tiene una sede asignada. Cierra sesión y vuelve a entrar eligiendo la sede.')
        self.olvidar_cache()
        errores = {clave: lista for clave, lista in self.errores().items() if lista}
        claves = {p.clave for p in self.preguntas()}
        if any(clave in claves for clave in errores):
            return siguiente(self, ['Antes de guardar hay que corregir un dato:'])
        if errores:
            detalle = ' '.join(f'{clave.replace("_", " ")}: {" ".join(lista)}' for clave, lista in errores.items())
            return respuesta(
                f'El sistema reporta un problema que debe revisarse en el formulario: {detalle}',
                [enlace('Abrir Nueva Solicitud de Ingreso', 'ingreso_registrar')],
                [opcion('Cancelar', 'cancelar')],
            )
        resultado = enviar(self.request, vistas.ingreso_registrar, datos=self.post())
        if resultado.destino_nombre != 'ingreso_detalle':
            detalle = ' '.join(resultado.errores) or 'El sistema no aceptó los datos.'
            return respuesta(
                f'No pude registrar el equipo: {detalle} No se guardó nada. '
                'Puedes corregir un dato con «campo: valor» o abrir el formulario.',
                [enlace('Abrir Nueva Solicitud de Ingreso', 'ingreso_registrar')],
                [opcion('✅ Intentar de nuevo', 'sí'), opcion('Cancelar', 'cancelar')],
            )
        ingreso = IngresoEquipo.objects.select_related('cliente').get(pk=resultado.destino_kwargs['pk'])
        return exito_ingreso(self.request, ingreso, resultado)


def exito_ingreso(request, ingreso, resultado):
    lineas = [
        f'✅ Listo: registré el equipo {ingreso.codigo_equipo} para {ingreso.cliente.nombres}.',
        f'{ingreso.tipo_equipo_display} {ingreso.marca} {ingreso.modelo_serie} · Estado: {ingreso.estado_visual_display}',
    ]
    for aviso in resultado.mensajes_de('info', 'warning'):
        lineas.append(aviso)
    correo = (ingreso.cliente.correo or '').strip()
    if correo and getattr(settings, 'INGRESO_EMAIL_AUTOMATICO', True):
        lineas.append(f'📧 El comprobante con el PDF se enviará a {correo}.')
    enlaces = [
        enlace('Ver equipo', 'ingreso_detalle', pk=ingreso.pk),
        enlace('Imprimir hoja', 'ingreso_imprimir', pk=ingreso.pk, tipo='nueva'),
        enlace('Descargar PDF', 'ingreso_pdf', pk=ingreso.pk, tipo='nueva'),
        enlace('Imprimir QR', 'ingreso_imprimir_qr', pk=ingreso.pk, tipo='nueva'),
        enlace_url('Enviar hoja por WhatsApp', whatsapp_link_hoja_ingreso(request, ingreso)),
    ]
    return respuesta('\n'.join(lineas), enlaces, [
        opcion(f'Ver {ingreso.codigo_equipo}', f'ver {ingreso.codigo_equipo}'),
        opcion('Registrar otro equipo', 'registrar equipo'),
    ], hecho=True, ultimo_equipo=ingreso.pk)
