"""Pruebas del reporte del día de EconoBot (saludo, resumen y PDF)."""
import base64
import re
import zlib
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .econobot import reporte_dia
from .models import Abono, Cliente, IngresoEquipo, SalidaEquipo
from .tareas_diarias import enviar_cierres_del_dia


def texto_pdf(contenido):
    """Texto de las páginas de un PDF de reportlab (flujos A85 + Flate)."""
    partes = []
    for bloque in re.findall(rb'stream\r?\n(.*?)\s*endstream', contenido, re.S):
        datos = bloque.strip()
        if datos.endswith(b'~>'):
            datos = base64.a85decode(datos[:-2], adobe=False)
        try:
            partes.append(zlib.decompress(datos).decode('latin-1'))
        except zlib.error:
            continue
    return '\n'.join(partes)


class ReporteDiaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        tecnicos = Group.objects.create(name='Tecnicos')
        asesores = Group.objects.create(name='Asesores')
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri Alberto')
        self.tecnico.groups.add(tecnicos)
        self.asesora = User.objects.create_user(username='Kimberly')
        self.asesora.groups.add(asesores)
        self.sin_rol = User.objects.create_user(username='Invitado')
        self.cliente = Cliente.objects.create(
            cedula='1207342716', nombres='María Pérez', whatsapp='0939746169', sector='norte',
        )
        self.client.force_login(self.tecnico)

    def crear_ingreso(self, creado=None, **datos):
        base = {
            'sede': 'guayaquil', 'asesor_comercial': 'Kimberly', 'fecha_ingreso': timezone.localdate(),
            'cliente': self.cliente, 'tipo_equipo': 'laptop', 'marca': 'HP', 'modelo_serie': 'Elitebook',
            'accesorios_entregados': 'Cargador', 'problema_reportado': 'No enciende',
            'valor_acordado': Decimal('25.00'), 'tecnico_encargado': self.tecnico, 'estado': 'ingresado',
            'registrado_por': self.tecnico,
        }
        base.update(datos)
        ingreso = IngresoEquipo.objects.create(**base)
        if creado is not None:
            IngresoEquipo.objects.filter(pk=ingreso.pk).update(creado=creado)
            ingreso.refresh_from_db()
        return ingreso

    def reporte(self, **params):
        respuesta = self.client.get(reverse('econotec:econobot_reporte_dia'), params)
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        return respuesta.json()

    # ── Saludo y contenido ───────────────────────────────────────────
    def test_saluda_por_nombre_y_lista_lo_registrado_hoy_con_estado(self):
        reparando = self.crear_ingreso(estado='en_reparacion', subestado_reparacion='espera_repuesto')
        diagnostico = self.crear_ingreso(marca='Lenovo')
        datos = self.reporte()

        self.assertTrue(datos['reply'].startswith('Hola, ¿qué tal, Yandri? 👋'))
        self.assertEqual(datos['date'], timezone.localdate().isoformat())
        self.assertIn('Registraste 2 equipos:', datos['reply'])
        self.assertIn(f'{reparando.codigo_equipo} — Laptop HP Elitebook · María Pérez · '
                      'En reparación (En reparación - Repuestos)', datos['reply'])
        self.assertIn(f'{diagnostico.codigo_equipo} — Laptop Lenovo Elitebook · María Pérez · '
                      'Ingresado / En diagnóstico', datos['reply'])
        self.assertEqual(datos['links'], [{
            'label': '📄 Ver reporte del día en PDF',
            'url': f"{reverse('econotec:econobot_reporte_dia_pdf')}?fecha={timezone.localdate().isoformat()}",
            'kind': 'nueva',
        }])
        self.assertNotIn('Soy EconoBot', datos['reply'])

    def test_estado_pendiente_de_retiro_cuando_ya_tiene_salida(self):
        ingreso = self.crear_ingreso(estado='entregado')
        SalidaEquipo.objects.create(
            ingreso=ingreso, fecha_salida=date.today(), estado_reparacion='pendiente_retiro',
            tecnico_reparo=self.tecnico, valor_final_cobrado=Decimal('0.00'), metodo_pago_final='sin_pago',
        )
        self.assertIn('Pendiente de retiro (Reparado - pendiente de retiro)', self.reporte()['reply'])

    def test_solo_cuenta_lo_que_registro_el_usuario(self):
        propio = self.crear_ingreso()
        ajeno = self.crear_ingreso(registrado_por=self.asesora)
        asignado = self.crear_ingreso(registrado_por=self.asesora, tecnico_encargado=self.tecnico)
        respuesta = self.reporte()['reply']

        self.assertIn(propio.codigo_equipo, respuesta)
        self.assertNotIn(ajeno.codigo_equipo, respuesta)
        self.assertNotIn(asignado.codigo_equipo, respuesta)
        self.assertIn('Registraste 1 equipo:', respuesta)

    def test_no_cuenta_dias_anteriores(self):
        ayer = self.crear_ingreso(creado=timezone.now() - timedelta(days=1))
        datos = self.reporte()

        self.assertNotIn(ayer.codigo_equipo, datos['reply'])
        self.assertIn('Todavía no tienes nada hoy', datos['reply'])
        self.assertEqual(datos['links'], [])

    def test_el_dia_se_corta_a_medianoche_de_ecuador(self):
        dia = date(2026, 11, 26)
        zona = timezone.get_current_timezone()
        antes = self.crear_ingreso(creado=timezone.make_aware(datetime.combine(dia - timedelta(days=1), time(23, 50)), zona))
        primero = self.crear_ingreso(creado=timezone.make_aware(datetime.combine(dia, time(0, 5)), zona))
        ultimo = self.crear_ingreso(creado=timezone.make_aware(datetime.combine(dia, time(23, 55)), zona))
        despues = self.crear_ingreso(creado=timezone.make_aware(datetime.combine(dia + timedelta(days=1), time(0, 1)), zona))

        self.assertEqual(str(zona), 'America/Guayaquil')
        self.assertEqual([i.pk for i in reporte_dia.registrados_hoy(self.tecnico, dia)], [primero.pk, ultimo.pk])
        self.assertNotIn(antes.pk, [i.pk for i in reporte_dia.registrados_hoy(self.tecnico, dia)])
        self.assertNotIn(despues.pk, [i.pk for i in reporte_dia.registrados_hoy(self.tecnico, dia)])

    def test_no_incluye_ventas(self):
        venta = self.crear_ingreso(sede='ventas')
        self.assertNotIn(venta.codigo_equipo, self.reporte()['reply'])

    def test_presentacion_cuando_el_chat_esta_vacio(self):
        self.assertIn('Soy EconoBot, tu asistente de Econotec.', self.reporte(presentar='1')['reply'])

    def test_sin_nombre_usa_el_usuario(self):
        self.client.force_login(self.asesora)
        self.assertTrue(self.reporte()['reply'].startswith('Hola, ¿qué tal, Kimberly? 👋'))

    def test_lista_larga_remite_al_pdf(self):
        for _ in range(reporte_dia.MAX_LINEAS_CHAT + 2):
            self.crear_ingreso()
        respuesta = self.reporte()['reply']
        self.assertIn(f'Registraste {reporte_dia.MAX_LINEAS_CHAT + 2} equipos:', respuesta)
        self.assertIn('… y 2 más. El PDF los muestra todos.', respuesta)

    # ── Chat ─────────────────────────────────────────────────────────
    def chat(self, mensaje):
        respuesta = self.client.post(reverse('econotec:econobot_mensaje'), {'message': mensaje},
                                     content_type='application/json')
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        return respuesta.json()

    def test_pedir_el_reporte_desde_el_chat(self):
        ingreso = self.crear_ingreso()
        for mensaje in ('mi reporte de hoy', '¿Qué hice hoy?', 'lo que he hecho hoy', 'mis ingresos de hoy'):
            with self.subTest(mensaje=mensaje):
                datos = self.chat(mensaje)
                self.assertTrue(datos['reply'].startswith('📋 Tu reporte de hoy'), datos['reply'])
                self.assertIn(ingreso.codigo_equipo, datos['reply'])
                self.assertIn({'label': f'Ver {ingreso.codigo_equipo}', 'value': f'ver {ingreso.codigo_equipo}'},
                              datos['options'])

    def test_ingresos_de_hoy_sigue_siendo_de_todo_el_taller(self):
        ajeno = self.crear_ingreso(registrado_por=self.asesora)
        datos = self.chat('ingresos de hoy')
        self.assertIn('Últimos equipos ingresados', datos['reply'])
        self.assertIn(ajeno.codigo_equipo, datos['reply'])

    # ── PDF ──────────────────────────────────────────────────────────
    def test_pdf_del_reporte(self):
        ingreso = self.crear_ingreso(estado='en_reparacion', subestado_reparacion='en_reparacion')
        ajeno = self.crear_ingreso(registrado_por=self.asesora)
        respuesta = self.client.get(reverse('econotec:econobot_reporte_dia_pdf'))

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')
        self.assertTrue(respuesta['Content-Disposition'].startswith('inline; filename="reporte_del_dia_'))
        self.assertTrue(respuesta.content.startswith(b'%PDF-'))
        texto = texto_pdf(respuesta.content)
        self.assertIn('REPORTE DEL D', texto)
        self.assertIn(ingreso.codigo_equipo, texto)
        self.assertIn('En reparaci', texto)
        self.assertNotIn(ajeno.codigo_equipo, texto)

    def test_pdf_con_muchos_equipos_usa_varias_paginas(self):
        for _ in range(45):
            self.crear_ingreso()
        respuesta = self.client.get(reverse('econotec:econobot_reporte_dia_pdf'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertGreaterEqual(respuesta.content.count(b'/Type /Page\n') + respuesta.content.count(b'/Type /Page '), 2)

    def test_pdf_sin_equipos(self):
        respuesta = self.client.get(reverse('econotec:econobot_reporte_dia_pdf'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('No registraste equipos, ni finalizaste, ni cobraste en esta fecha.', texto_pdf(respuesta.content))

    # ── Acceso ───────────────────────────────────────────────────────
    def test_acceso(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('econotec:econobot_reporte_dia')).status_code, 401)
        respuesta = self.client.get(reverse('econotec:econobot_reporte_dia_pdf'))
        self.assertEqual(respuesta.status_code, 302)

        self.client.force_login(self.sin_rol)
        self.assertEqual(self.client.get(reverse('econotec:econobot_reporte_dia')).status_code, 403)
        self.assertEqual(self.client.get(reverse('econotec:econobot_reporte_dia_pdf')).status_code, 403)

    def test_plantilla_entrega_la_ruta_del_reporte(self):
        respuesta = self.client.get(reverse('econotec:ingreso_lista'))
        self.assertContains(respuesta, f'data-reporte="{reverse("econotec:econobot_reporte_dia")}"')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', SISTEMA_URL='https://econosystem.cc')
class ReporteRolPersonalCierreTests(TestCase):
    """Finalizados y cobros del día, reporte del personal (admin) y cierre automático."""

    def setUp(self):
        User = get_user_model()
        tecnicos = Group.objects.create(name='Tecnicos')
        asesores = Group.objects.create(name='Asesores')
        self.admin = User.objects.create_superuser(username='jefe', email='jefe@example.com', password='x')
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri', email='yandri@example.com')
        self.tecnico.groups.add(tecnicos)
        self.asesora = User.objects.create_user(username='kimberly', first_name='Kimberly', email='kim@example.com')
        self.asesora.groups.add(asesores)
        self.cliente = Cliente.objects.create(cedula='0912345678', nombres='Luis Mora', whatsapp='0991111111')
        self.hoy = timezone.localdate()

    def ingreso(self, **datos):
        base = {
            'sede': 'guayaquil', 'asesor_comercial': 'Kimberly', 'fecha_ingreso': self.hoy, 'cliente': self.cliente,
            'tipo_equipo': 'laptop', 'marca': 'Dell', 'modelo_serie': 'Latitude', 'accesorios_entregados': '-',
            'problema_reportado': 'No carga', 'valor_acordado': Decimal('80.00'), 'estado': 'ingresado',
            'registrado_por': self.asesora,
        }
        base.update(datos)
        return IngresoEquipo.objects.create(**base)

    def finalizar(self, ingreso, **datos):
        base = {
            'ingreso': ingreso, 'fecha_salida': self.hoy, 'estado_reparacion': 'pendiente_retiro',
            'tecnico_reparo': self.tecnico, 'valor_final_cobrado': Decimal('0.00'), 'metodo_pago_final': 'sin_pago',
            'registrado_por': self.tecnico,
        }
        base.update(datos)
        return SalidaEquipo.objects.create(**base)

    def chat(self, mensaje):
        respuesta = self.client.post(reverse('econotec:econobot_mensaje'), {'message': mensaje},
                                     content_type='application/json')
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        return respuesta.json()

    # ── Lo que hizo cada uno ─────────────────────────────────────────
    def test_tecnico_ve_los_equipos_que_finalizo_hoy(self):
        hoy_ = self.ingreso(fecha_ingreso=self.hoy - timedelta(days=5))
        self.finalizar(hoy_)
        otro_dia = self.ingreso()
        self.finalizar(otro_dia, fecha_salida=self.hoy - timedelta(days=1))
        de_otro = self.ingreso()
        self.finalizar(de_otro, tecnico_reparo=self.admin)

        datos = reporte_dia.datos_dia(self.tecnico)
        self.assertEqual([i.pk for i in datos['finalizados']], [hoy_.pk])
        self.client.force_login(self.tecnico)
        texto = self.client.get(reverse('econotec:econobot_reporte_dia')).json()['reply']
        self.assertIn('🔧 Finalizaste 1 equipo:', texto)
        self.assertIn(f'{hoy_.codigo_equipo} — Laptop Dell Latitude · Luis Mora · Pendiente de retiro', texto)
        self.assertNotIn(otro_dia.codigo_equipo, texto)
        self.assertNotIn(de_otro.codigo_equipo, texto)
        self.assertNotIn('Registraste', texto)

    def test_cobros_que_registro_hoy_con_total_por_metodo(self):
        con_anticipo = self.ingreso(abono_anticipo=Decimal('20.00'), anticipo_metodo='efectivo')
        Abono.objects.create(ingreso=con_anticipo, fecha=self.hoy, monto=Decimal('15.00'), metodo='transferencia',
                             banco='pichincha', registrado_por=self.asesora)
        Abono.objects.create(ingreso=con_anticipo, fecha=self.hoy, monto=Decimal('99.00'), metodo='efectivo',
                             registrado_por=self.tecnico)
        Abono.objects.create(ingreso=con_anticipo, fecha=self.hoy - timedelta(days=1), monto=Decimal('7.00'),
                             metodo='efectivo', registrado_por=self.asesora)
        otro = self.ingreso(registrado_por=self.tecnico)
        self.finalizar(otro, valor_final_cobrado=Decimal('45.00'), metodo_pago_final='tarjeta',
                       registrado_por=self.asesora)

        datos = reporte_dia.datos_dia(self.asesora)
        self.assertEqual([c['concepto'] for c in datos['cobros']], ['Anticipo', 'Abono', 'Pago al finalizar'])
        self.assertEqual(datos['total_cobrado'], Decimal('80.00'))
        self.assertEqual({clave: monto for clave, _n, monto in datos['por_metodo']},
                         {'efectivo': Decimal('20.00'), 'transferencia': Decimal('15.00'), 'tarjeta': Decimal('45.00')})

        self.client.force_login(self.asesora)
        texto = self.client.get(reverse('econotec:econobot_reporte_dia')).json()['reply']
        self.assertIn('💵 Registraste 3 cobros por $80.00:', texto)
        self.assertIn(f'{con_anticipo.codigo_equipo} · Abono · $15.00 · Transferencia · Banco Pichincha', texto)
        self.assertIn('Por método: Transferencia $15.00 · Efectivo $20.00 · Tarjeta $45.00', texto)
        self.assertNotIn('$99.00', texto)
        self.assertNotIn('$7.00', texto)

    def test_mi_reporte_de_ayer(self):
        viejo = self.ingreso(registrado_por=self.tecnico)
        IngresoEquipo.objects.filter(pk=viejo.pk).update(creado=timezone.now() - timedelta(days=1))
        self.client.force_login(self.tecnico)
        datos = self.chat('mi reporte de ayer')
        self.assertTrue(datos['reply'].startswith(f'📋 Tu reporte del {reporte_dia.fecha_larga(reporte_dia.ayer())}'))
        self.assertIn(viejo.codigo_equipo, datos['reply'])
        self.assertIn(f'?fecha={reporte_dia.ayer().isoformat()}', datos['links'][0]['url'])
        self.assertNotIn(viejo.codigo_equipo, self.chat('mi reporte de hoy')['reply'])

    def test_pdf_de_otra_fecha_y_fecha_invalida(self):
        viejo = self.ingreso(registrado_por=self.tecnico)
        IngresoEquipo.objects.filter(pk=viejo.pk).update(creado=timezone.now() - timedelta(days=1))
        self.client.force_login(self.tecnico)
        url = reverse('econotec:econobot_reporte_dia_pdf')
        self.assertIn(viejo.codigo_equipo, texto_pdf(self.client.get(url, {'fecha': reporte_dia.ayer().isoformat()}).content))
        for fecha in ('', 'abc', (self.hoy + timedelta(days=3)).isoformat()):
            with self.subTest(fecha=fecha):
                respuesta = self.client.get(url, {'fecha': fecha})
                self.assertEqual(respuesta.status_code, 200)
                self.assertIn(f'reporte_del_dia_{self.hoy:%Y-%m-%d}.pdf', respuesta['Content-Disposition'])

    def test_pdf_incluye_finalizados_y_cobros(self):
        ingreso = self.ingreso(abono_anticipo=Decimal('12.50'), anticipo_metodo='efectivo')
        self.finalizar(ingreso, tecnico_reparo=self.asesora)
        self.client.force_login(self.asesora)
        texto = texto_pdf(self.client.get(reverse('econotec:econobot_reporte_dia_pdf')).content)
        self.assertIn('Equipos finalizados como t', texto)
        self.assertIn('Cobros registrados \\(1\\)', texto)
        self.assertIn('$12.50', texto)
        self.assertIn('Por m', texto)

    # ── Reporte del personal (admin) ─────────────────────────────────
    def test_reporte_del_personal_para_admin(self):
        ingreso = self.ingreso(abono_anticipo=Decimal('30.00'), anticipo_metodo='efectivo')
        self.finalizar(self.ingreso(registrado_por=self.tecnico))
        self.client.force_login(self.admin)
        datos = self.chat('reporte del personal')

        self.assertTrue(datos['reply'].startswith('👥 Reporte del personal de hoy'))
        self.assertIn('• Kimberly: registró 1 · finalizó 0 · cobró $30.00 (1 cobro)', datos['reply'])
        self.assertIn('• Yandri: registró 1 · finalizó 1 · sin cobros', datos['reply'])
        self.assertIn('Total: 2 registrados · 1 finalizado · $30.00 cobrados', datos['reply'])
        self.assertEqual(datos['links'][0]['url'],
                         f"{reverse('econotec:econobot_reporte_personal_pdf')}?fecha={self.hoy.isoformat()}")
        self.assertIn({'label': '📅 Reporte del personal de ayer', 'value': 'reporte del personal de ayer'},
                      datos['options'])

        pdf = self.client.get(reverse('econotec:econobot_reporte_personal_pdf'))
        self.assertEqual(pdf.status_code, 200)
        texto = texto_pdf(pdf.content)
        self.assertIn('REPORTE DEL PERSONAL', texto)
        self.assertIn('Resumen por persona', texto)
        self.assertIn(ingreso.codigo_equipo, texto)

    def test_reporte_del_personal_de_ayer_sin_movimientos(self):
        self.client.force_login(self.admin)
        datos = self.chat('reporte del personal de ayer')
        self.assertTrue(datos['reply'].startswith(f'👥 Reporte del personal del {reporte_dia.fecha_larga(reporte_dia.ayer())}'))
        self.assertIn('Nadie registró, finalizó ni cobró equipos ese día.', datos['reply'])

    def test_reporte_del_personal_solo_admin(self):
        self.client.force_login(self.asesora)
        self.assertIn('solo para el administrador', self.chat('reporte del personal')['reply'])
        self.assertEqual(self.client.get(reverse('econotec:econobot_reporte_personal_pdf')).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('econotec:econobot_reporte_personal_pdf')).status_code, 302)

    def test_boton_del_personal_solo_para_admin(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('econotec:ingreso_lista')), 'data-admin="1"')
        self.client.force_login(self.asesora)
        self.assertContains(self.client.get(reverse('econotec:ingreso_lista')), 'data-admin=""')

    def test_reporte_del_equipo_sigue_siendo_el_reporte_tecnico(self):
        self.client.force_login(self.tecnico)
        self.assertNotIn('Reporte del personal', self.chat('reporte del equipo')['reply'])

    # ── Cierre del día ───────────────────────────────────────────────
    def _a_las(self, hora):
        momento = timezone.make_aware(datetime.combine(self.hoy, time(hora, 0)))
        return mock.patch('econotec.management.commands.tareas_diarias.timezone.localtime', return_value=momento)

    def test_cierre_envia_correo_con_pdf_y_notificacion_a_quien_hizo_algo(self):
        ingreso = self.ingreso(abono_anticipo=Decimal('10.00'), anticipo_metodo='efectivo')
        salida = StringIO()
        with self._a_las(18), mock.patch('econotec.push.enviar_push_ahora', return_value=1) as push:
            call_command('tareas_diarias', stdout=salida)

        self.assertEqual([c.to for c in mail.outbox], [['kim@example.com']])
        correo = mail.outbox[0]
        self.assertEqual(correo.subject, f'Tu cierre del día {self.hoy:%d/%m/%Y} | Econotec')
        self.assertIn('Registraste 1 equipo · cobraste $10.00 (1 cobro)', correo.body)
        self.assertIn(ingreso.codigo_equipo, correo.body)
        self.assertIn(f'https://econosystem.cc/econobot/reporte-dia/pdf/?fecha={self.hoy.isoformat()}', correo.body)
        nombre, contenido, tipo = correo.attachments[0]
        self.assertEqual((nombre, tipo), (f'reporte_del_dia_{self.hoy:%Y-%m-%d}.pdf', 'application/pdf'))
        self.assertTrue(contenido.startswith(b'%PDF-'))
        push.assert_called_once()
        self.assertEqual(push.call_args.args[0], [self.asesora.pk])
        self.assertIn('Cierre del día: 1 correo(s) · 1 notificación(es)', salida.getvalue())

    def test_cierre_no_sale_a_otra_hora_ni_apagado(self):
        self.ingreso()
        with self._a_las(7):
            call_command('tareas_diarias', stdout=StringIO())
        with self._a_las(12):
            call_command('tareas_diarias', stdout=StringIO())
        with self.settings(CIERRE_DIA_AUTOMATICO=False), self._a_las(18):
            call_command('tareas_diarias', stdout=StringIO())
        self.assertEqual(mail.outbox, [])

    def test_cierre_manual_y_sin_movimientos_no_envia(self):
        with self._a_las(10):
            call_command('tareas_diarias', '--cierre', stdout=StringIO())
        self.assertEqual(mail.outbox, [])
        self.ingreso()
        with self._a_las(10):
            call_command('tareas_diarias', '--cierre', stdout=StringIO())
        self.assertEqual([c.to for c in mail.outbox], [['kim@example.com']])

    def test_cierre_no_va_a_usuarios_inactivos_ni_sin_rol(self):
        sin_rol = get_user_model().objects.create_user(username='visita', email='visita@example.com')
        self.ingreso(registrado_por=sin_rol)
        self.asesora.is_active = False
        self.asesora.save()
        self.ingreso()
        self.assertEqual(enviar_cierres_del_dia(self.hoy), (0, 0))
