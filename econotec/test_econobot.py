"""Pruebas de EconoBot: el chat usa las mismas vistas y reglas que la web."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Abono, Cliente, IngresoEquipo, NotificacionAsesora, SalidaEquipo


FIRMA_PNG = (
    'data:image/png;base64,'
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgF/TV5CiwAAAABJRU5ErkJggg=='
)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EconoBotTests(TestCase):
    def setUp(self):
        User = get_user_model()
        asesores = Group.objects.create(name='Asesores')
        tecnicos = Group.objects.create(name='Tecnicos')
        self.asesora = User.objects.create_user(username='Kimberly', email='kimberly@example.com')
        self.asesora.groups.add(asesores)
        self.tecnico = User.objects.create_user(username='Yandri', email='yandri@example.com')
        self.tecnico.groups.add(tecnicos)
        self.sin_rol = User.objects.create_user(username='Invitado', email='invitado@example.com')
        self.cliente = Cliente.objects.create(
            cedula='1207342716', nombres='Yandri Guevara', whatsapp='0939746169',
            correo='cliente@example.com', sector='norte',
        )
        self.entrar(self.tecnico)

    # ── Utilidades ───────────────────────────────────────────────────
    def entrar(self, usuario, sede='guayaquil'):
        self.client.force_login(usuario)
        sesion = self.client.session
        sesion['sede_actual'] = sede
        sesion.save()

    def chat(self, mensaje='', firma=None, request_id=None, esperado=200):
        cuerpo = {'message': mensaje}
        if firma is not None:
            cuerpo['signature'] = firma
        if request_id:
            cuerpo['request_id'] = request_id
        respuesta = self.client.post(reverse('econotec:econobot_mensaje'), cuerpo, content_type='application/json')
        self.assertEqual(respuesta.status_code, esperado, respuesta.content)
        return respuesta.json()

    def conversar(self, *mensajes):
        datos = None
        for mensaje in mensajes:
            datos = self.chat(mensaje)
        return datos

    def crear_ingreso(self, **datos):
        base = {
            'sede': 'guayaquil', 'asesor_comercial': 'Kimberly', 'fecha_ingreso': date.today(),
            'cliente': self.cliente, 'tipo_equipo': 'laptop', 'marca': 'HP', 'modelo_serie': 'Elitebook',
            'accesorios_entregados': 'Cargador', 'problema_reportado': 'No enciende',
            'valor_acordado': Decimal('25.00'), 'tecnico_encargado': self.tecnico, 'estado': 'en_reparacion',
            'subestado_reparacion': 'en_reparacion', 'registrado_por': self.tecnico,
            'reporte_tecnico': 'Se revisó la placa.',
        }
        base.update(datos)
        return IngresoEquipo.objects.create(**base)

    def crear_salida(self, ingreso, **datos):
        base = {
            'ingreso': ingreso, 'fecha_salida': date.today(), 'estado_reparacion': 'pendiente_retiro',
            'tecnico_reparo': self.tecnico, 'valor_final_cobrado': Decimal('0.00'), 'metodo_pago_final': 'sin_pago',
        }
        base.update(datos)
        return SalidaEquipo.objects.create(**base)

    # ── Acceso ───────────────────────────────────────────────────────
    def test_requiere_sesion_y_rol(self):
        self.client.logout()
        respuesta = self.client.post(reverse('econotec:econobot_mensaje'), {'message': 'hola'},
                                     content_type='application/json')
        self.assertEqual(respuesta.status_code, 401)
        self.client.force_login(self.sin_rol)
        respuesta = self.client.post(reverse('econotec:econobot_mensaje'), {'message': 'hola'},
                                     content_type='application/json')
        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(self.client.get(reverse('econotec:econobot_estado')).status_code, 403)

    def test_solo_acepta_post_json_valido(self):
        self.assertEqual(self.client.get(reverse('econotec:econobot_mensaje')).status_code, 405)
        respuesta = self.client.post(reverse('econotec:econobot_mensaje'), 'no es json', content_type='application/json')
        self.assertEqual(respuesta.status_code, 400)
        self.chat('', esperado=400)
        self.chat('x' * 2001, esperado=400)
        self.chat('', firma='data:image/jpeg;base64,AAAA', esperado=400)

    def test_widget_y_accesos_visibles_para_roles_con_permiso(self):
        respuesta = self.client.get(reverse('econotec:bienvenida'))
        self.assertContains(respuesta, 'id="econobot"')
        self.assertContains(respuesta, 'econobot-nav-link')
        self.assertContains(respuesta, 'card-box-econobot')
        self.assertContains(respuesta, 'econobot/econobot.js')
        # La mascota de EconoBot: cara en los accesos y figura completa en la bienvenida del chat.
        self.assertContains(respuesta, 'econobot/econobot-rostro.webp', count=4)
        self.assertContains(respuesta, 'econobot/econobot-mascota.webp')
        self.client.force_login(self.sin_rol)
        respuesta = self.client.get(reverse('econotec:bienvenida'))
        self.assertNotContains(respuesta, 'id="econobot"')
        self.assertNotContains(respuesta, 'econobot-nav-link')

    def test_saludo_y_ayuda(self):
        datos = self.chat('hola')
        self.assertIn('EconoBot', datos['reply'])
        self.assertTrue(any(o['value'] == 'registrar equipo' for o in datos['options']))
        self.assertFalse(datos['pending'])

    def test_conocimiento_usa_reglas_reales(self):
        datos = self.chat('¿Qué es el bodegaje?')
        self.assertIn('día 5', datos['reply'])
        self.assertIn('$1,00', datos['reply'])
        datos = self.chat('¿cómo registro un abono?')
        self.assertIn('Ingresar abono', datos['reply'])

    # ── Registro de un equipo ────────────────────────────────────────
    def test_registra_equipo_cliente_nuevo_por_chat(self):
        datos = self.chat('registrar equipo')
        self.assertTrue(datos['pending'])
        self.assertIn('cédula', datos['reply'])
        datos = self.conversar(
            '0923456789', 'María López', '0991234567', 'omitir', 'norte', 'laptop', 'HP', 'Pavilion 15',
            'omitir', 'sí', 'cargador', 'No enciende', '1', 'Kimberly', 'sí', '45', 'no', '10', 'efectivo', 'no',
        )
        self.assertIn('Revisa los datos', datos['reply'])
        self.assertIn('G1000', datos['reply'])
        self.assertEqual(IngresoEquipo.objects.count(), 0, 'No debe guardar nada antes de confirmar.')

        datos = self.chat('sí')
        self.assertIn('registré el equipo G1000', datos['reply'])
        self.assertFalse(datos['pending'])
        ingreso = IngresoEquipo.objects.get()
        self.assertEqual(ingreso.cliente.cedula, '0923456789')
        self.assertEqual(ingreso.cliente.nombres, 'María López')
        self.assertEqual((ingreso.marca, ingreso.modelo_serie), ('HP', 'Pavilion 15'))
        self.assertEqual(ingreso.accesorios_entregados, 'cargador')
        self.assertEqual(ingreso.valor_acordado, Decimal('45.00'))
        self.assertEqual(ingreso.abono_anticipo, Decimal('10.00'))
        self.assertEqual(ingreso.anticipo_metodo, 'efectivo')
        self.assertEqual(ingreso.tecnico_encargado, self.tecnico)
        self.assertEqual(ingreso.asesor_comercial, 'Kimberly')
        self.assertEqual(ingreso.registrado_por, self.tecnico)
        self.assertEqual(ingreso.estado, 'ingresado')
        self.assertFalse(ingreso.firma_cliente)
        self.assertTrue(any(e['url'] == reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk})
                            for e in datos['links']))

    def test_registro_con_cliente_existente_firma_y_reparacion(self):
        self.entrar(self.asesora)
        datos = self.chat(f'registrar equipo {self.cliente.cedula} impresora')
        self.assertIn('Cliente encontrado', datos['reply'])
        datos = self.conversar(
            'Epson', 'L3150', 'omitir', 'no', 'No imprime', 'en reparación', 'repuestos', 'Yandri', 'no', 'no', 'no',
            'sí',
        )
        self.assertEqual(datos.get('widget'), 'firma')
        datos = self.chat('', firma=FIRMA_PNG)
        self.assertIn('Revisa los datos', datos['reply'])
        datos = self.chat('sí')
        self.assertIn('registré el equipo', datos['reply'])
        ingreso = IngresoEquipo.objects.get()
        self.assertEqual(ingreso.cliente, self.cliente)
        self.assertEqual(ingreso.tipo_equipo, 'impresora')
        self.assertEqual(ingreso.estado, 'en_reparacion')
        self.assertEqual(ingreso.subestado_reparacion, 'espera_repuesto')
        self.assertEqual(ingreso.asesor_comercial, 'Kimberly')
        self.assertIsNone(ingreso.valor_acordado)
        self.assertTrue(ingreso.firma_cliente)
        self.assertEqual(ingreso.firma_cliente_imagen, FIRMA_PNG)
        self.assertEqual(Cliente.objects.count(), 1)

    def test_equipo_repetido_responde_no_y_lo_registra_asi(self):
        anterior = self.crear_ingreso(tipo_equipo='impresora', marca='Epson', modelo_serie='L3150', serie='X5Y-001')
        self.chat(f'registrar equipo {self.cliente.cedula} impresora')
        datos = self.conversar('Epson', 'L3150', 'omitir', 'no', 'No imprime')
        self.assertIn(f'ya se encuentra registrado para este cliente en la hoja {anterior.codigo_equipo}', datos['reply'])
        self.assertIn('Si deseas hacer la diferencia, ingresa el número de serie', datos['reply'])
        datos = self.conversar('no', '1', 'Kimberly', 'no', 'no', 'no', 'no')
        self.assertIn('Revisa los datos', datos['reply'])
        self.assertIn(f'Mismo equipo de este cliente (hoja {anterior.codigo_equipo})', datos['reply'])
        datos = self.chat('sí')
        self.assertIn('registré el equipo', datos['reply'])
        self.assertIn(f'es el mismo equipo de este cliente que ya se encuentra en la hoja {anterior.codigo_equipo}', datos['reply'])
        nuevo = IngresoEquipo.objects.exclude(pk=anterior.pk).get()
        self.assertEqual((nuevo.cliente, nuevo.modelo_serie, nuevo.serie), (self.cliente, 'L3150', ''))

    def test_equipo_repetido_responde_si_y_serie_es_opcional(self):
        anterior = self.crear_ingreso(tipo_equipo='impresora', marca='Epson', modelo_serie='L3150', serie='X5Y-001')
        self.chat(f'registrar equipo {self.cliente.cedula} impresora')
        self.conversar('Epson', 'L3150', 'omitir', 'no', 'No imprime')
        datos = self.chat('sí')
        self.assertIn('Número de serie de este equipo', datos['reply'])
        self.assertIn('omitir', datos['reply'])
        datos = self.conversar('omitir', '1', 'Kimberly', 'no', 'no', 'no', 'no')
        self.assertIn('Revisa los datos', datos['reply'])
        self.assertIn(f'Mismo equipo de este cliente (hoja {anterior.codigo_equipo})', datos['reply'])
        datos = self.chat('sí')
        self.assertIn('registré el equipo', datos['reply'])
        self.assertIn('es el mismo equipo de este cliente', datos['reply'])
        nuevo = IngresoEquipo.objects.exclude(pk=anterior.pk).get()
        self.assertEqual((nuevo.modelo_serie, nuevo.serie), ('L3150', ''))

    def test_equipo_repetido_responde_si_no_acepta_la_misma_serie(self):
        anterior = self.crear_ingreso(tipo_equipo='impresora', marca='Epson', modelo_serie='L3150', serie='X5Y-001')
        self.chat(f'registrar equipo {self.cliente.cedula} impresora')
        self.conversar('Epson', 'L3150', 'omitir', 'no', 'No imprime')
        datos = self.chat('sí')
        self.assertIn('Número de serie de este equipo', datos['reply'])
        datos = self.chat('x5y 001')
        self.assertIn(f'ya pertenece a la hoja {anterior.codigo_equipo}', datos['reply'])
        self.assertEqual(IngresoEquipo.objects.count(), 1)
        datos = self.conversar('X5Y-002', '1', 'Kimberly', 'no', 'no', 'no', 'no')
        self.assertIn('Revisa los datos', datos['reply'])
        self.assertIn('Serie X5Y-002', datos['reply'])
        self.assertIn(f'Se diferencia de la hoja {anterior.codigo_equipo} por su número de serie', datos['reply'])
        datos = self.chat('sí')
        self.assertIn('registré el equipo', datos['reply'])
        self.assertIn('Equipo registrado con número de serie X5Y-002: se diferencia', datos['reply'])
        nuevo = IngresoEquipo.objects.exclude(pk=anterior.pk).get()
        self.assertEqual((nuevo.cliente, nuevo.modelo_serie, nuevo.serie), (self.cliente, 'L3150', 'X5Y-002'))

    def test_cancelar_y_atras_no_guardan_nada(self):
        self.conversar('registrar equipo', '0923456789')
        datos = self.chat('atrás')
        self.assertIn('cédula', datos['reply'])
        datos = self.chat('cancelar')
        self.assertIn('cancelé', datos['reply'])
        self.assertFalse(datos['pending'])
        self.assertEqual(IngresoEquipo.objects.count(), 0)
        self.assertEqual(Cliente.objects.count(), 1)

    def test_consulta_lateral_no_rompe_el_registro(self):
        ingreso = self.crear_ingreso()
        self.conversar('registrar equipo', '0923456789', 'María López', '0991234567', 'omitir', 'norte')
        datos = self.chat(f'ver {ingreso.codigo_equipo}')
        self.assertIn(ingreso.codigo_equipo, datos['reply'])
        self.assertIn('Sigues con', datos['reply'])
        self.assertTrue(datos['pending'])
        datos = self.chat('continuar')
        self.assertIn('tipo de equipo', datos['reply'])

    # ── Finalizar ────────────────────────────────────────────────────
    def test_finaliza_equipo_reparado_con_la_vista_original(self):
        ingreso = self.crear_ingreso()
        datos = self.chat(f'finalizar {ingreso.codigo_equipo}')
        self.assertTrue(datos['pending'])
        datos = self.conversar('1', 'mantener', 'no')
        # Igual que en la web: con saldo pendiente se elige la asesora que lo cobrará.
        self.assertIn('asesora', datos['reply'])
        datos = self.chat('Kimberly')
        self.assertIn('Finalización de', datos['reply'])
        self.assertFalse(SalidaEquipo.objects.exists())
        datos = self.chat('sí')
        self.assertIn('quedó finalizado', datos['reply'])
        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        self.assertEqual(salida.estado_reparacion, 'pendiente_retiro')
        self.assertEqual(salida.tecnico_reparo, self.tecnico)
        self.assertTrue(NotificacionAsesora.objects.filter(ingreso=ingreso, asesora=self.asesora).exists())
        ingreso.refresh_from_db()
        self.assertEqual(ingreso.reporte_tecnico, 'Se revisó la placa.')
        self.assertIsNone(salida.fecha_retiro_real)

    def test_finalizar_sin_valor_acordado_lo_pide_y_registra_ambos(self):
        ingreso = self.crear_ingreso(valor_acordado=None)
        self.chat(f'finalizar {ingreso.codigo_equipo} reparado')
        datos = self.conversar('30', 'Cambio de pantalla', 'no')
        self.assertIn('asesora', datos['reply'])
        datos = self.chat('Kimberly')
        self.assertIn('Valor acordado (se registrará primero): $30,00', datos['reply'])
        self.chat('sí')
        ingreso.refresh_from_db()
        self.assertEqual(ingreso.valor_acordado, Decimal('30.00'))
        self.assertEqual(ingreso.reporte_tecnico, 'Cambio de pantalla')
        self.assertTrue(SalidaEquipo.objects.filter(ingreso=ingreso, estado_reparacion='pendiente_retiro').exists())

    def test_finalizar_no_reparable_usa_la_edicion_del_equipo(self):
        ingreso = self.crear_ingreso(valor_acordado=None)
        self.chat(f'finalizar {ingreso.codigo_equipo}')
        datos = self.conversar('no se pudo reparar', 'mantener', 'no')
        self.assertIn('No se pudo reparar', datos['reply'])
        datos = self.chat('sí')
        self.assertIn('quedó finalizado', datos['reply'])
        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        self.assertEqual(salida.estado_reparacion, 'no_reparable')
        ingreso.refresh_from_db()
        self.assertEqual((ingreso.marca, ingreso.modelo_serie, ingreso.asesor_comercial),
                         ('HP', 'Elitebook', 'Kimberly'))

    def test_no_finaliza_dos_veces(self):
        ingreso = self.crear_ingreso()
        self.crear_salida(ingreso)
        datos = self.chat(f'finalizar {ingreso.codigo_equipo}')
        self.assertIn('ya está finalizado', datos['reply'])
        self.assertFalse(datos['pending'])

    # ── Salida física ────────────────────────────────────────────────
    def test_confirma_salida_fisica_sin_saldo(self):
        ingreso = self.crear_ingreso(valor_acordado=Decimal('0.00'))
        salida = self.crear_salida(ingreso)
        datos = self.chat(f'confirmar salida {ingreso.codigo_equipo}')
        self.assertIn('Salida física de', datos['reply'])
        datos = self.chat('sí')
        self.assertIn('Salida de la oficina confirmada', datos['reply'])
        salida.refresh_from_db()
        self.assertEqual(salida.fecha_retiro_real, date.today())
        self.assertEqual(salida.estado_reparacion, 'retirado')

    def test_salida_fisica_bloqueada_con_saldo(self):
        ingreso = self.crear_ingreso(valor_acordado=Decimal('40.00'))
        salida = self.crear_salida(ingreso)
        datos = self.chat(f'confirmar salida {ingreso.codigo_equipo}')
        self.assertIn('saldo pendiente', datos['reply'])
        self.assertFalse(datos['pending'])
        salida.refresh_from_db()
        self.assertIsNone(salida.fecha_retiro_real)

    def test_salida_fisica_cobra_bodegaje(self):
        ingreso = self.crear_ingreso(valor_acordado=Decimal('0.00'))
        salida = self.crear_salida(ingreso, fecha_salida=date.today() - timedelta(days=6))
        datos = self.chat(f'confirmar salida {ingreso.codigo_equipo}')
        self.assertIn('bodegaje', datos['reply'])
        datos = self.conversar('cobrar', 'efectivo')
        self.assertIn('se cobran $2,00', datos['reply'])
        self.chat('sí')
        salida.refresh_from_db()
        self.assertIsNotNone(salida.fecha_retiro_real)
        self.assertTrue(salida.bodegaje_aplicado_al_pago)
        self.assertEqual(salida.bodegaje_monto_congelado, Decimal('2.00'))
        self.assertEqual(Abono.objects.get(ingreso=ingreso).monto, Decimal('2.00'))

    # ── Estado, reporte y valor ──────────────────────────────────────
    def test_cambia_estado_y_reporte_con_la_hoja_del_tecnico(self):
        ingreso = self.crear_ingreso(estado='ingresado', subestado_reparacion='')
        datos = self.chat(f'cambiar estado {ingreso.codigo_equipo} a en reparación')
        self.assertIn('detalle', datos['reply'])
        datos = self.conversar('repuestos')
        self.assertIn('Nuevo estado: En reparación — En reparación - Repuestos', datos['reply'])
        self.chat('sí')
        ingreso.refresh_from_db()
        self.assertEqual((ingreso.estado, ingreso.subestado_reparacion), ('en_reparacion', 'espera_repuesto'))
        self.assertEqual(ingreso.reporte_tecnico, 'Se revisó la placa.')

        self.conversar(f'reporte {ingreso.codigo_equipo}', 'agregar: Se pidió el repuesto.', 'sí')
        ingreso.refresh_from_db()
        self.assertEqual(ingreso.reporte_tecnico, 'Se revisó la placa.\nSe pidió el repuesto.')
        self.assertEqual(ingreso.subestado_reparacion, 'espera_repuesto')

    def test_pregunta_de_estado_solo_muestra_la_ficha(self):
        ingreso = self.crear_ingreso()
        datos = self.chat(f'¿en qué estado está {ingreso.codigo_equipo}?')
        self.assertIn('Estado: En reparación', datos['reply'])
        self.assertFalse(datos['pending'])

    def test_valor_acordado(self):
        ingreso = self.crear_ingreso(valor_acordado=None)
        datos = self.chat(f'valor acordado {ingreso.codigo_equipo} 35,50')
        self.assertIn('Nuevo valor acordado: $35,50', datos['reply'])
        self.chat('sí')
        ingreso.refresh_from_db()
        self.assertEqual(ingreso.valor_acordado, Decimal('35.50'))

    # ── Consultas ────────────────────────────────────────────────────
    def test_consultas_de_equipos_y_clientes(self):
        en_taller = self.crear_ingreso()
        finalizado = self.crear_ingreso(marca='Lenovo')
        self.crear_salida(finalizado)
        datos = self.chat(en_taller.codigo_equipo)
        self.assertIn('Yandri Guevara', datos['reply'])
        self.assertTrue(any(o['value'] == f'finalizar {en_taller.codigo_equipo}' for o in datos['options']))
        datos = self.chat(f'cliente {self.cliente.cedula}')
        self.assertIn('Yandri Guevara', datos['reply'])
        self.assertIn(finalizado.codigo_equipo, datos['reply'])
        datos = self.chat('equipos finalizados')
        self.assertIn(finalizado.codigo_equipo, datos['reply'])
        self.assertNotIn(en_taller.codigo_equipo + ' —', datos['reply'])
        datos = self.chat('equipos en taller')
        self.assertIn(en_taller.codigo_equipo, datos['reply'])
        datos = self.chat('buscar lenovo')
        self.assertIn(finalizado.codigo_equipo, datos['reply'])
        self.assertIn('Resumen', self.chat('resumen')['reply'])
        self.assertIn('Alertas', self.chat('alertas')['reply'])

    def test_enviar_acta_pide_confirmacion(self):
        ingreso = self.crear_ingreso()
        self.crear_salida(ingreso)
        datos = self.chat(f'enviar acta {ingreso.codigo_equipo}')
        self.assertIn('cliente@example.com', datos['reply'])
        self.assertEqual(len(mail.outbox), 0)
        datos = self.chat('sí')
        self.assertIn('Acta enviada', datos['reply'])
        self.assertEqual(len(mail.outbox), 1)

    def test_request_id_evita_repetir_una_accion(self):
        ingreso = self.crear_ingreso(valor_acordado=Decimal('0.00'))
        self.crear_salida(ingreso)
        self.chat(f'confirmar salida {ingreso.codigo_equipo}')
        primero = self.chat('sí', request_id='abc-123')
        repetido = self.chat('sí', request_id='abc-123')
        self.assertEqual(primero, repetido)
        self.assertEqual(SalidaEquipo.objects.filter(fecha_retiro_real__isnull=False).count(), 1)

    def test_estado_para_retomar(self):
        self.chat('registrar equipo')
        datos = self.client.get(reverse('econotec:econobot_estado')).json()
        self.assertTrue(datos['pending'])
        self.assertEqual(datos['flow'], 'Registro de equipo')
        self.assertIn('cédula', datos['resume']['reply'])

    # ── Frases naturales ─────────────────────────────────────────────
    def test_frases_naturales(self):
        ingreso = self.crear_ingreso()
        datos = self.chat('Hola, quiero registrar un equipo')
        self.assertTrue(datos['pending'])
        self.assertIn('cédula', datos['reply'])
        self.chat('cancelar')

        datos = self.chat('finalizar equipo')
        self.assertIn('¿Qué equipo finalizo?', datos['reply'])
        self.assertFalse(datos['pending'])
        datos = self.chat(ingreso.codigo_equipo)
        self.assertTrue(datos['pending'])
        self.assertIn(f'Vamos a finalizar {ingreso.codigo_equipo}', datos['reply'])
        self.chat('cancelar')

        self.assertIn('en el taller', self.chat('¿cuántos equipos hay en taller?')['reply'])
        self.assertIn('En reparación', self.chat('¿qué significa en reparación?')['reply'])
        datos = self.chat('abrir pagos')
        self.assertEqual(datos['links'][0]['url'], reverse('econotec:pagos_lista'))
        self.assertIn('solo para administradores', self.chat('abrir egresos')['reply'])
        self.assertIn('No entendí', self.chat('xyzzy qwerty uiop asdf ghjk')['reply'])

    def test_datos_juntos_en_un_mensaje(self):
        self.conversar('registrar equipo', '0923456789')
        datos = self.chat('nombre: Ana Ruiz; whatsapp: 0998887766; correo: ana@example.com')
        self.assertIn('sector', datos['reply'])
        datos = self.conversar('omitir', 'marca: Lenovo; modelo: IdeaPad 3; equipo: laptop')
        self.assertIn('serie', datos['reply'].lower())
