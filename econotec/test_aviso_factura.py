"""Aviso de factura a la asesora.

- Con «¿Factura realizada? = Sí» en Finalizar / Editar finalización hay que
  elegir la asesora, y se le avisa al guardar.
- La campanita 🔔 de la tabla de finalizados vuelve a avisar a la misma
  asesora, una sola vez cada 24 horas (aunque ella ya lo haya marcado visto).
"""
import json
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import SalidaEquipoForm
from .models import Cliente, IngresoEquipo, NotificacionAsesora, SalidaEquipo, SuscripcionPush

TIPO = NotificacionAsesora.TIPO_FACTURA


@override_settings(PUSH_SINCRONO=True, PUSH_ACTIVO=True)
class AvisoFacturaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        asesores = Group.objects.get_or_create(name='Asesores')[0]
        tecnicos = Group.objects.get_or_create(name='Tecnicos')[0]
        self.tecnico = User.objects.create_user(username='victor', first_name='Victor', password='x')
        self.tecnico.groups.add(tecnicos)
        self.maria = User.objects.create_user(username='maria', first_name='Maria', password='x')
        self.maria.groups.add(asesores)
        self.ana = User.objects.create_user(username='ana', first_name='Ana', password='x')
        self.ana.groups.add(asesores)
        self.cliente = Cliente.objects.create(
            cedula='0992146818001', nombres='ZC Mayoristas', whatsapp='0991234567',
            correo='contabilidad4@zcmayoristas.com',
        )
        self.client.force_login(self.tecnico)

    def crear_ingreso(self):
        return IngresoEquipo.objects.create(
            sede='guayaquil', fecha_ingreso=date.today(), cliente=self.cliente,
            tipo_equipo='laptop', marca='Lenovo', modelo_serie='X1', problema_reportado='No enciende',
            valor_acordado=Decimal('38.00'), tecnico_encargado=self.tecnico, registrado_por=self.tecnico,
            estado='en_reparacion', subestado_reparacion='en_reparacion',
        )

    def datos(self, **extra):
        datos = {
            'fecha_salida': date.today().isoformat(),
            'estado_reparacion': 'pendiente_retiro',
            'tecnico_reparo': str(self.tecnico.pk),
            'reporte_tecnico': 'Equipo revisado.',
            'observaciones': '',
            'valor_final_cobrado': '0.00',
            'valor_acordado_revision': '',
            'aplica_valor_acordado_adicional': 'no',
            'valor_acordado_adicional': '0.00',
            'motivo_valor_acordado_adicional': '',
            'metodo_pago_final': 'efectivo',
            'numero_recibo': '',
            'banco': '', 'banco_otro': '', 'tarjeta_app': '', 'comprobante_url': '',
            'monto_1': '', 'metodo_1': '', 'banco_1': '',
            'monto_2': '', 'metodo_2': '', 'banco_2': '',
            'factura_realizada': 'si',
            'factura_nombres': 'ZC Mayoristas',
            'factura_cedula': '0992146818001',
            'factura_correo': 'contabilidad4@zcmayoristas.com',
            'aplica_retencion': 'no',
            'valor_con_retencion': '',
            # El equipo queda con saldo: Ana recibe el aviso de cobro (otro tipo).
            'asesora_notificacion': str(self.ana.pk),
            'mensaje_notificacion': '',
            'asesora_factura': str(self.maria.pk),
        }
        datos.update(extra)
        return datos

    def finalizar(self, **extra):
        ingreso = self.crear_ingreso()
        r = self.client.post(
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': ingreso.pk}), self.datos(**extra),
        )
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
        return SalidaEquipo.objects.get(ingreso=ingreso)

    def editar(self, salida, **extra):
        return self.client.post(reverse('econotec:salida_editar', kwargs={'pk': salida.pk}), self.datos(**extra))

    def campanita(self, salida):
        return self.client.post(
            reverse('econotec:salida_notificar_factura', kwargs={'pk': salida.pk}),
            {'next': reverse('econotec:salida_lista')},
        )

    def pasar_horas(self, salida, horas):
        SalidaEquipo.objects.filter(pk=salida.pk).update(
            factura_notificada_en=timezone.now() - timedelta(hours=horas),
        )
        salida.refresh_from_db()

    # ── Formulario ────────────────────────────────────────

    def test_con_factura_si_la_asesora_es_obligatoria(self):
        ingreso = self.crear_ingreso()
        r = self.client.post(
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': ingreso.pk}),
            self.datos(asesora_factura=''),
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn('asesora_factura', r.context['form'].errors)
        self.assertFalse(SalidaEquipo.objects.filter(ingreso=ingreso).exists())

    def test_con_factura_no_no_se_pide_ni_se_avisa(self):
        salida = self.finalizar(factura_realizada='no', asesora_factura='')
        self.assertIsNone(salida.factura_asesora)
        self.assertFalse(NotificacionAsesora.objects.filter(tipo=TIPO).exists())

    def test_formularios_sin_selector_no_cambian(self):
        # EconoBot y la finalización rápida usan el formulario sin el selector.
        self.assertNotIn('asesora_factura', SalidaEquipoForm().fields)
        self.assertIn('asesora_factura', SalidaEquipoForm(pedir_asesora_factura=True).fields)

    def test_pantalla_muestra_el_selector(self):
        ingreso = self.crear_ingreso()
        r = self.client.get(reverse('econotec:salida_registrar', kwargs={'ingreso_pk': ingreso.pk}))
        self.assertContains(r, 'id="factura-asesora"')
        self.assertContains(r, 'Notificar a la asesora (factura)')

    # ── Aviso al guardar ──────────────────────────────────

    @mock.patch('pywebpush.webpush')
    def test_al_finalizar_se_avisa_a_la_asesora_elegida(self, webpush):
        SuscripcionPush.objects.create(
            usuario=self.maria, endpoint='https://fcm.googleapis.com/fcm/send/m1', p256dh='k', auth='a',
        )
        with self.captureOnCommitCallbacks(execute=True):
            salida = self.finalizar()
        self.assertEqual(salida.factura_asesora, self.maria)
        self.assertIsNotNone(salida.factura_notificada_en)
        aviso = NotificacionAsesora.objects.get(tipo=TIPO)
        self.assertEqual(aviso.asesora, self.maria)
        self.assertFalse(aviso.leida)
        self.assertIn('0992146818001', aviso.mensaje)
        self.assertIn('ZC Mayoristas', aviso.mensaje)
        self.assertEqual(webpush.call_count, 1)
        self.assertIn('Factura', json.loads(webpush.call_args.kwargs['data'])['titulo'])

    def test_reguardar_con_la_misma_asesora_no_repite(self):
        salida = self.finalizar()
        primera = salida.factura_notificada_en
        NotificacionAsesora.objects.filter(tipo=TIPO).update(leida=True, leida_en=timezone.now())
        self.editar(salida, observaciones='Cambio menor')
        salida.refresh_from_db()
        self.assertEqual(salida.factura_notificada_en, primera)
        self.assertTrue(NotificacionAsesora.objects.get(tipo=TIPO).leida)

    def test_cambiar_de_asesora_le_avisa_a_la_nueva(self):
        salida = self.finalizar()
        self.editar(salida, asesora_factura=str(self.ana.pk))
        salida.refresh_from_db()
        self.assertEqual(salida.factura_asesora, self.ana)
        aviso = NotificacionAsesora.objects.get(tipo=TIPO)
        self.assertEqual(aviso.asesora, self.ana)

    def test_pasar_factura_a_no_quita_el_aviso(self):
        salida = self.finalizar()
        self.editar(salida, factura_realizada='no', asesora_factura='')
        salida.refresh_from_db()
        self.assertIsNone(salida.factura_asesora)
        self.assertIsNone(salida.factura_notificada_en)
        self.assertFalse(NotificacionAsesora.objects.filter(tipo=TIPO).exists())

    def test_no_toca_los_avisos_de_cobro(self):
        salida = self.finalizar()
        cobro = NotificacionAsesora.objects.get(tipo=NotificacionAsesora.TIPO_SALDO_RETIRO)
        self.assertEqual(cobro.asesora, self.ana)
        self.pasar_horas(salida, 25)
        self.campanita(salida)
        self.editar(salida, factura_realizada='no', asesora_factura='')
        cobro.refresh_from_db()
        self.assertEqual(cobro.asesora, self.ana)
        self.assertEqual(cobro.valor_acordado, Decimal('38.00'))

    # ── Campanita de la tabla (cada 24 horas) ─────────────

    def test_campanita_espera_24_horas(self):
        salida = self.finalizar()
        primera = salida.factura_notificada_en

        r = self.campanita(salida)  # recién avisada
        salida.refresh_from_db()
        self.assertEqual(salida.factura_notificada_en, primera)
        self.assertIn('Podrás volver a avisarle', str(list(r.wsgi_request._messages)[-1]))

        self.pasar_horas(salida, 23)
        self.campanita(salida)
        salida.refresh_from_db()
        self.assertLess(salida.factura_notificada_en, timezone.now() - timedelta(hours=22))

    @mock.patch('pywebpush.webpush')
    def test_despues_de_24_horas_vuelve_a_avisar_una_sola_vez(self, webpush):
        SuscripcionPush.objects.create(
            usuario=self.maria, endpoint='https://fcm.googleapis.com/fcm/send/m1', p256dh='k', auth='a',
        )
        with self.captureOnCommitCallbacks(execute=True):
            salida = self.finalizar()
        NotificacionAsesora.objects.filter(tipo=TIPO).update(leida=True, leida_en=timezone.now())
        self.pasar_horas(salida, 24)

        with self.captureOnCommitCallbacks(execute=True):
            self.campanita(salida)
        salida.refresh_from_db()
        self.assertGreater(salida.factura_notificada_en, timezone.now() - timedelta(minutes=1))
        aviso = NotificacionAsesora.objects.get(tipo=TIPO)
        self.assertFalse(aviso.leida)  # vuelve a quedar pendiente
        self.assertEqual(aviso.asesora, self.maria)
        self.assertEqual(webpush.call_count, 2)

        with self.captureOnCommitCallbacks(execute=True):
            self.campanita(salida)  # segundo toque: debe esperar otras 24 horas
        self.assertEqual(webpush.call_count, 2)
        self.assertEqual(NotificacionAsesora.objects.filter(tipo=TIPO).count(), 1)

    def test_tabla_muestra_campanita_activa_o_en_espera(self):
        salida = self.finalizar()
        url = reverse('econotec:salida_lista')
        html = self.client.get(url, {'sede': 'todas'}).content.decode()
        self.assertIn('factura-bell is-espera', html)
        self.assertNotIn(reverse('econotec:salida_notificar_factura', kwargs={'pk': salida.pk}), html)
        # La campanita en espera se puede tocar y explica por qué y hasta cuándo.
        disponible = timezone.localtime(salida.aviso_factura_disponible_en)
        self.assertIn('<button type="button" class="factura-bell is-espera" data-factura-espera', html)
        self.assertIn(f'data-disponible="{disponible:%d/%m/%Y} a las {disponible:%H:%M}"', html)
        self.assertIn('Aviso de factura ya enviado', html)
        self.assertIn('una vez cada 24 horas', html)

        self.pasar_horas(salida, 25)
        html = self.client.get(url, {'sede': 'todas'}).content.decode()
        self.assertIn(reverse('econotec:salida_notificar_factura', kwargs={'pk': salida.pk}), html)

    def test_sin_factura_no_hay_campanita(self):
        salida = self.finalizar(factura_realizada='no', asesora_factura='')
        r = self.campanita(salida)
        self.assertEqual(r.status_code, 302)
        self.assertFalse(NotificacionAsesora.objects.filter(tipo=TIPO).exists())
        html = self.client.get(reverse('econotec:salida_lista'), {'sede': 'todas'}).content.decode()
        self.assertNotIn('factura-bell', html.split('</style>')[-1])

    def test_campanita_solo_por_post_y_con_sesion(self):
        salida = self.finalizar()
        url = reverse('econotec:salida_notificar_factura', kwargs={'pk': salida.pk})
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.logout()
        self.pasar_horas(salida, 25)
        self.client.post(url)
        salida.refresh_from_db()
        self.assertLess(salida.factura_notificada_en, timezone.now() - timedelta(hours=24))

    def test_bandeja_de_la_asesora_muestra_la_factura(self):
        self.finalizar()
        self.client.force_login(self.maria)
        r = self.client.get(reverse('econotec:notificaciones_asesora'))
        self.assertContains(r, 'Factura por realizar')
        self.assertContains(r, 'Ver datos de factura')
