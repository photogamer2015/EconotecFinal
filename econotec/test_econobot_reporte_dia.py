"""Pruebas del reporte del día de EconoBot (saludo, resumen y PDF)."""
import base64
import re
import zlib
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .econobot import reporte_dia
from .models import Cliente, IngresoEquipo, SalidaEquipo


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
            'url': reverse('econotec:econobot_reporte_dia_pdf'), 'kind': 'nueva',
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
        self.assertIn('Todavía no has registrado equipos hoy', datos['reply'])
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
        self.assertIn('No registraste equipos en esta fecha.', texto_pdf(respuesta.content))

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
