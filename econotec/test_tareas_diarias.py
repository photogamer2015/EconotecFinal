"""Tareas diarias por cron: resumen al admin y recordatorio a cada técnico.

- El admin (superusuario con correo) recibe un correo con lo atrasado de todos.
- Cada técnico con correo recibe solo SUS equipos atrasados.
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

from .models import Cliente, IngresoEquipo
from .tareas_diarias import enviar_recordatorios_tecnicos, enviar_resumen_admin


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

    def correos_para(self, email):
        return [m for m in mail.outbox if email in m.to]

    # ── Recordatorio al técnico ────────────────────────────────────

    def test_tecnico_recibe_solo_sus_equipos_atrasados(self):
        propio_diag = self.sin_diagnosticar(self.tec1, 4)
        propio_rep = self.en_reparacion(self.tec1, 5)
        ajeno = self.en_reparacion(self.tec2, 6)

        enviados = enviar_recordatorios_tecnicos()

        self.assertEqual(enviados, 2)
        correo = self.correos_para('victor@example.com')[0]
        self.assertIn('2 equipos atrasados', correo.subject)
        self.assertIn(propio_diag.codigo_equipo, correo.body)
        self.assertIn(propio_rep.codigo_equipo, correo.body)
        self.assertNotIn(ajeno.codigo_equipo, correo.body)
        html = correo.alternatives[0][0]
        self.assertIn(f'https://econosystem.cc/ingresos/{propio_rep.pk}/', html)

    def test_tecnico_sin_atrasos_no_recibe_correo(self):
        self.sin_diagnosticar(self.tec1, 3)
        self.en_reparacion(self.tec1, 4)

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

    def test_admin_recibe_resumen_de_todos_con_umbral_de_diez_dias(self):
        diag = self.sin_diagnosticar(self.tec1, 4)
        rep_10 = self.en_reparacion(self.tec2, 10)
        rep_9 = self.en_reparacion(self.tec2, 9)

        self.assertEqual(enviar_resumen_admin(), 1)

        correo = self.correos_para('admin@example.com')[0]
        self.assertIn('2 equipos por revisar', correo.subject)
        self.assertIn(diag.codigo_equipo, correo.body)
        self.assertIn(rep_10.codigo_equipo, correo.body)
        self.assertNotIn(rep_9.codigo_equipo, correo.body)
        self.assertIn('Téc.: Randy', correo.body)
        self.assertNotIn('Bodegaje $', correo.body)

    def test_admin_sin_pendientes_no_recibe_correo(self):
        self.en_reparacion(self.tec1, 6)

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
