"""Tareas diarias por cron: resumen al admin y recordatorio a cada técnico.

Solo las 3 advertencias del inicio: sin diagnosticar 4+ días, en reparación
10+ días y bodegaje vencido.
- El admin (superusuario con correo) recibe un correo con lo atrasado de todos.
- Cada técnico con correo recibe solo SUS equipos atrasados (los que tiene
  encargados y los bodegajes de los que él reparó).
- Si no hay nada atrasado no se envía correo.
- El comando solo envía a la hora configurada, salvo con --forzar.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Cliente, IngresoEquipo, SalidaEquipo
from .emails import enviar_correo_bodegaje_seguro
from .tareas_diarias import (
    enviar_avisos_bodegaje_clientes,
    enviar_recordatorios_tecnicos,
    enviar_resumen_admin,
)


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SISTEMA_URL='https://econosystem.cc',
    TAREAS_DIARIAS_HORA=7,
)
class TareasDiariasTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='root', email='admin@example.com', password='x')
        grupo = Group.objects.get_or_create(name='Tecnicos')[0]
        self.tec1 = User.objects.create_user(username='victor', first_name='Victor', email='victor@example.com')
        self.tec2 = User.objects.create_user(username='randy', first_name='Randy', email='randy@example.com')
        self.tec_sin_correo = User.objects.create_user(username='dylan', first_name='Dylan', email='')
        for tec in (self.tec1, self.tec2, self.tec_sin_correo):
            tec.groups.add(grupo)
        self.cliente = Cliente.objects.create(cedula='0912345678', nombres='Cesar Sandoya', whatsapp='0991234567')

    def crear(self, tecnico, **extra):
        datos = {
            'sede': 'guayaquil',
            'fecha_ingreso': date.today(),
            'cliente': self.cliente,
            'tipo_equipo': 'laptop',
            'marca': 'Lenovo',
            'modelo_serie': 'X1',
            'problema_reportado': 'No enciende',
            'valor_acordado': Decimal('25.00'),
            'tecnico_encargado': tecnico,
            'registrado_por': self.admin,
            'estado': 'ingresado',
        }
        datos.update(extra)
        return IngresoEquipo.objects.create(**datos)

    def sin_diagnosticar(self, tecnico, dias):
        return self.crear(tecnico, fecha_ingreso=date.today() - timedelta(days=dias))

    def en_reparacion(self, tecnico, dias):
        ingreso = self.crear(tecnico, estado='en_reparacion', subestado_reparacion='en_reparacion')
        IngresoEquipo.objects.filter(pk=ingreso.pk).update(
            fecha_alerta_reparacion=date.today() - timedelta(days=dias),
        )
        return ingreso

    def con_bodegaje(self, tecnico, dias):
        ingreso = self.crear(tecnico, estado='en_reparacion', subestado_reparacion='en_reparacion')
        SalidaEquipo.objects.create(
            ingreso=ingreso, fecha_salida=date.today() - timedelta(days=dias),
            estado_reparacion='pendiente_retiro', tecnico_reparo=tecnico,
            valor_final_cobrado=Decimal('0.00'), metodo_pago_final='sin_pago',
        )
        return ingreso

    def correos_para(self, email):
        return [m for m in mail.outbox if email in m.to]

    # ── Recordatorio al técnico ────────────────────────────────────

    def test_tecnico_recibe_solo_sus_3_advertencias(self):
        propio_diag = self.sin_diagnosticar(self.tec1, 4)
        propio_rep = self.en_reparacion(self.tec1, 10)
        propio_bod = self.con_bodegaje(self.tec1, 8)
        ajeno = self.en_reparacion(self.tec2, 12)
        ajeno_bod = self.con_bodegaje(self.tec2, 8)

        enviados = enviar_recordatorios_tecnicos()

        self.assertEqual(enviados, 2)
        correo = self.correos_para('victor@example.com')[0]
        self.assertIn('3 equipos atrasados', correo.subject)
        self.assertIn(propio_diag.codigo_equipo, correo.body)
        self.assertIn(propio_rep.codigo_equipo, correo.body)
        self.assertIn(propio_bod.codigo_equipo, correo.body)
        self.assertIn('BODEGAJE VENCIDO', correo.body)
        self.assertNotIn(ajeno.codigo_equipo, correo.body)
        self.assertNotIn(ajeno_bod.codigo_equipo, correo.body)
        html = correo.alternatives[0][0]
        self.assertIn(f'https://econosystem.cc/ingresos/{propio_rep.pk}/', html)

    def test_tecnico_sin_atrasos_no_recibe_correo(self):
        self.sin_diagnosticar(self.tec1, 3)
        self.en_reparacion(self.tec1, 9)
        self.con_bodegaje(self.tec1, 4)

        self.assertEqual(enviar_recordatorios_tecnicos(), 0)
        self.assertEqual(mail.outbox, [])

    def test_equipo_en_no_molestar_no_se_recuerda(self):
        ingreso = self.sin_diagnosticar(self.tec1, 8)
        IngresoEquipo.objects.filter(pk=ingreso.pk).update(diagnostico_silenciado=True)

        self.assertEqual(enviar_recordatorios_tecnicos(), 0)

    def test_tecnico_sin_correo_o_inactivo_se_salta(self):
        self.sin_diagnosticar(self.tec_sin_correo, 6)
        self.tec1.is_active = False
        self.tec1.save()
        self.sin_diagnosticar(self.tec1, 6)

        self.assertEqual(enviar_recordatorios_tecnicos(), 0)

    # ── Resumen diario al admin ────────────────────────────────────

    def test_admin_recibe_las_3_advertencias_de_todos(self):
        diag = self.sin_diagnosticar(self.tec1, 4)
        rep_10 = self.en_reparacion(self.tec2, 10)
        rep_9 = self.en_reparacion(self.tec2, 9)
        bod = self.con_bodegaje(self.tec1, 8)

        self.assertEqual(enviar_resumen_admin(), 1)

        correo = self.correos_para('admin@example.com')[0]
        self.assertIn('3 equipos por revisar', correo.subject)
        self.assertIn(diag.codigo_equipo, correo.body)
        self.assertIn(rep_10.codigo_equipo, correo.body)
        self.assertNotIn(rep_9.codigo_equipo, correo.body)
        self.assertIn(bod.codigo_equipo, correo.body)
        self.assertIn('Téc.: Randy', correo.body)
        self.assertIn('Bodegaje $', correo.body)

    def test_resumen_admin_no_incluye_equipos_de_prueba(self):
        ingreso = self.crear(self.tec1, estado='en_reparacion', subestado_reparacion='en_reparacion')
        salida = SalidaEquipo.objects.create(
            ingreso=ingreso, fecha_salida=date.today() - timedelta(days=8),
            estado_reparacion='revision', subestado_revision='equipo_prueba', tecnico_reparo=self.tec1,
            valor_final_cobrado=Decimal('0.00'), metodo_pago_final='sin_pago',
        )
        SalidaEquipo.objects.filter(pk=salida.pk).update(
            fecha_subestado_revision=timezone.now() - timedelta(days=8),
        )

        self.assertEqual(enviar_resumen_admin(), 0)

    def test_admin_sin_pendientes_no_recibe_correo(self):
        self.en_reparacion(self.tec1, 9)

        self.assertEqual(enviar_resumen_admin(), 0)
        self.assertEqual(mail.outbox, [])

    # ── Comando y hora ─────────────────────────────────────────────

    def _a_las(self, hora):
        momento = timezone.make_aware(datetime.combine(date.today(), datetime.min.time()).replace(hour=hora))
        return mock.patch('econotec.management.commands.tareas_diarias.timezone.localtime', return_value=momento)

    def test_comando_no_envia_fuera_de_hora(self):
        self.sin_diagnosticar(self.tec1, 5)
        with self._a_las(9):
            call_command('tareas_diarias', stdout=StringIO())
        self.assertEqual(mail.outbox, [])

    def test_comando_envia_a_la_hora_configurada(self):
        self.sin_diagnosticar(self.tec1, 5)
        salida = StringIO()
        with self._a_las(7):
            call_command('tareas_diarias', stdout=salida)
        self.assertEqual(len(self.correos_para('admin@example.com')), 1)
        self.assertEqual(len(self.correos_para('victor@example.com')), 1)
        self.assertIn('1 correo(s) a admins', salida.getvalue())

    def test_comando_forzar_envia_a_cualquier_hora(self):
        self.sin_diagnosticar(self.tec1, 5)
        with self._a_las(15):
            call_command('tareas_diarias', '--forzar', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 2)


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EQUIPO_EMAIL_ADJUNTAR_PDF=False,
    AVISO_BODEGAJE_AUTOMATICO=True,
)
class AvisoBodegajeClienteTests(TestCase):
    """El aviso de bodegaje vencido llega solo al cliente y se repite cada 7 días."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='root', email='', password='x')
        self.tecnico = User.objects.create_user(username='victor', first_name='Victor', email='')
        self.cliente = Cliente.objects.create(
            cedula='0912345678', nombres='Cesar Sandoya', whatsapp='0991234567', correo='cesar@example.com',
        )

    def bodegaje(self, dias=8, cliente=None, **salida):
        ingreso = IngresoEquipo.objects.create(
            sede='guayaquil', fecha_ingreso=date.today() - timedelta(days=dias + 3),
            cliente=cliente or self.cliente, tipo_equipo='laptop', marca='Lenovo', modelo_serie='X1',
            problema_reportado='No enciende', valor_acordado=Decimal('25.00'),
            tecnico_encargado=self.tecnico, registrado_por=self.admin,
            estado='en_reparacion', subestado_reparacion='en_reparacion',
        )
        datos = {
            'ingreso': ingreso, 'fecha_salida': date.today() - timedelta(days=dias),
            'estado_reparacion': 'pendiente_retiro', 'tecnico_reparo': self.tecnico,
            'valor_final_cobrado': Decimal('0.00'), 'metodo_pago_final': 'sin_pago',
        }
        datos.update(salida)
        return SalidaEquipo.objects.create(**datos)

    def test_cliente_con_bodegaje_vencido_recibe_el_aviso(self):
        salida = self.bodegaje(dias=8)

        self.assertEqual(enviar_avisos_bodegaje_clientes(), 1)

        self.assertEqual(mail.outbox[0].to, ['cesar@example.com'])
        self.assertIn('Aviso importante de retiro y bodegaje', mail.outbox[0].subject)
        salida.refresh_from_db()
        self.assertIsNotNone(salida.bodegaje_correo_enviado_en)

    def test_tambien_los_que_ya_llevan_muchos_dias(self):
        self.bodegaje(dias=116)
        self.assertEqual(enviar_avisos_bodegaje_clientes(), 1)

    def test_se_repite_cada_7_dias(self):
        salida = self.bodegaje(dias=20)
        self.assertEqual(enviar_avisos_bodegaje_clientes(), 1)
        self.assertEqual(enviar_avisos_bodegaje_clientes(), 0)

        SalidaEquipo.objects.filter(pk=salida.pk).update(
            bodegaje_correo_enviado_en=timezone.now() - timedelta(days=6),
        )
        self.assertEqual(enviar_avisos_bodegaje_clientes(), 0)

        SalidaEquipo.objects.filter(pk=salida.pk).update(
            bodegaje_correo_enviado_en=timezone.now() - timedelta(days=7),
        )
        self.assertEqual(enviar_avisos_bodegaje_clientes(), 1)
        self.assertEqual(len(mail.outbox), 2)

    def test_envio_manual_reinicia_los_7_dias(self):
        salida = self.bodegaje(dias=8)
        self.assertTrue(enviar_correo_bodegaje_seguro(salida.pk))

        self.assertEqual(enviar_avisos_bodegaje_clientes(), 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_no_se_envia_si_no_corresponde(self):
        sin_correo = Cliente.objects.create(cedula='0911111111', nombres='Sin Correo', correo='')
        self.bodegaje(dias=8, cliente=sin_correo)
        self.bodegaje(dias=4)  # todavía en días de gracia
        self.bodegaje(dias=30, fecha_retiro_real=date.today())  # ya retiró
        self.bodegaje(dias=30, estado_reparacion='chatarrerizacion')
        self.bodegaje(dias=30, bodegaje_silenciado=True)  # No molestar

        self.assertEqual(enviar_avisos_bodegaje_clientes(), 0)
        self.assertEqual(mail.outbox, [])

    @override_settings(AVISO_BODEGAJE_AUTOMATICO=False)
    def test_se_puede_apagar(self):
        self.bodegaje(dias=8)
        self.assertEqual(enviar_avisos_bodegaje_clientes(), 0)

    @override_settings(TAREAS_DIARIAS_HORA=7)
    def test_comando_envia_el_aviso_a_las_7(self):
        self.bodegaje(dias=8)
        momento = timezone.make_aware(datetime.combine(date.today(), datetime.min.time()).replace(hour=7))
        salida = StringIO()
        with mock.patch('econotec.management.commands.tareas_diarias.timezone.localtime', return_value=momento):
            call_command('tareas_diarias', stdout=salida)
        self.assertIn('Bodegaje: 1 aviso(s) a clientes', salida.getvalue())
        self.assertEqual(mail.outbox[-1].to, ['cesar@example.com'])
