"""Notificaciones push al celular.

- La app se puede instalar (manifest y service worker públicos en la raíz).
- Admins, técnicos y asesoras guardan la suscripción de su dispositivo.
- Cada aviso nuevo de una campanita llega como push a quien corresponde:
  admins (cambios, revisión, inventario), el técnico notificado y la asesora.
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

from .avisos_cambios import avisar_cambio
from .avisos_revision import generar_avisos_prueba_demorada
from .models import (
    ClavesPush,
    Cliente,
    IngresoEquipo,
    NotificacionAsesora,
    NotificacionTecnico,
    SalidaEquipo,
    SuscripcionPush,
)
from .push import clave_publica


def _sub(n):
    return {
        'endpoint': f'https://fcm.googleapis.com/fcm/send/abc{n}',
        'keys': {'p256dh': f'clave{n}', 'auth': f'auth{n}'},
    }


@override_settings(PUSH_SINCRONO=True, PUSH_ACTIVO=True)
class PushTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='root', email='a@example.com', password='x')
        self.admin2 = User.objects.create_superuser(username='root2', email='b@example.com', password='x')
        self.tecnico = User.objects.create_user(username='victor', first_name='Victor', password='x')
        self.tecnico.groups.add(Group.objects.get_or_create(name='Tecnicos')[0])
        self.asesora = User.objects.create_user(username='maria', first_name='Maria', password='x')
        self.asesora.groups.add(Group.objects.get_or_create(name='Asesores')[0])
        self.sin_rol = User.objects.create_user(username='nadie', password='x')
        self.cliente = Cliente.objects.create(cedula='0912345678', nombres='Cesar Sandoya', whatsapp='0991234567')

    def suscribir(self, usuario, n):
        return SuscripcionPush.objects.create(
            usuario=usuario, endpoint=_sub(n)['endpoint'], p256dh=f'clave{n}', auth=f'auth{n}',
        )

    def crear_ingreso(self):
        return IngresoEquipo.objects.create(
            sede='guayaquil', fecha_ingreso=date.today(), cliente=self.cliente,
            tipo_equipo='laptop', marca='Lenovo', modelo_serie='X1', problema_reportado='No enciende',
            valor_acordado=Decimal('25.00'), tecnico_encargado=self.tecnico, registrado_por=self.admin,
            estado='en_reparacion', subestado_reparacion='en_reparacion',
        )

    def crear_salida(self, **extra):
        datos = {
            'ingreso': self.crear_ingreso(), 'fecha_salida': date.today(),
            'estado_reparacion': 'pendiente_retiro', 'tecnico_reparo': self.tecnico,
            'valor_final_cobrado': Decimal('0.00'), 'metodo_pago_final': 'sin_pago',
        }
        datos.update(extra)
        return SalidaEquipo.objects.create(**datos)

    def destinos(self, webpush):
        return sorted(llamada.kwargs['subscription_info']['endpoint'] for llamada in webpush.call_args_list)

    # ── App instalable ─────────────────────────────────────

    def test_manifest_y_service_worker_son_publicos(self):
        r = self.client.get('/manifest.webmanifest')
        self.assertEqual(r.status_code, 200)
        self.assertIn('manifest+json', r['Content-Type'])
        datos = json.loads(r.content)
        self.assertEqual(datos['display'], 'standalone')
        self.assertEqual(len(datos['icons']), 2)

        r = self.client.get('/service-worker.js')
        self.assertEqual(r.status_code, 200)
        self.assertIn('javascript', r['Content-Type'])
        self.assertIn("addEventListener('push'", r.content.decode())

    def test_assetlinks_vincula_la_app_de_android(self):
        r = self.client.get('/.well-known/assetlinks.json')
        self.assertEqual(r.status_code, 200)
        self.assertIn('application/json', r['Content-Type'])
        destino = r.json()[0]['target']
        self.assertEqual(destino['namespace'], 'android_app')
        self.assertEqual(destino['package_name'], 'cc.econosystem.app')
        self.assertEqual(len(destino['sha256_cert_fingerprints'][0].split(':')), 32)

    def test_descarga_directa_del_apk_de_android(self):
        url = reverse('econotec:app_android_descargar')
        self.assertEqual(self.client.get(url).status_code, 302)  # pide iniciar sesión

        self.client.force_login(self.asesora)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/vnd.android.package-archive')
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertIn('Econotec.apk', r['Content-Disposition'])
        contenido = b''.join(r.streaming_content)
        self.assertTrue(contenido.startswith(b'PK'))  # un APK es un ZIP

    def test_inicio_tiene_la_tarjeta_de_la_app(self):
        self.client.force_login(self.tecnico)
        html = self.client.get(reverse('econotec:bienvenida')).content.decode()
        self.assertIn(reverse('econotec:app_android_descargar'), html)
        self.assertIn('Descargar para', html)
        self.assertIn('pwa/android-robot.png', html)

    def test_base_tiene_manifest_y_boton_solo_para_roles(self):
        self.client.force_login(self.tecnico)
        html = self.client.get(reverse('econotec:bienvenida')).content.decode()
        self.assertIn('rel="manifest"', html)
        self.assertIn('data-push-toggle', html)
        self.assertIn('push.js', html)

        self.client.force_login(self.sin_rol)
        html = self.client.get(reverse('econotec:mi_perfil')).content.decode()
        self.assertNotIn('data-push-toggle', html)

    # ── Claves ─────────────────────────────────────────────

    def test_claves_se_crean_una_sola_vez(self):
        primera = clave_publica()
        self.assertEqual(clave_publica(), primera)
        self.assertEqual(ClavesPush.objects.count(), 1)
        self.client.force_login(self.asesora)
        self.assertEqual(self.client.get(reverse('econotec:push_clave')).json()['clave'], primera)

    # ── Suscripción ────────────────────────────────────────

    def test_suscribir_guarda_y_reasigna_el_dispositivo(self):
        url = reverse('econotec:push_suscribir')
        self.client.force_login(self.tecnico)
        r = self.client.post(url, json.dumps(_sub(1)), content_type='application/json')
        self.assertTrue(r.json()['ok'])
        self.assertEqual(SuscripcionPush.objects.get().usuario, self.tecnico)

        # El mismo celular, ahora con otra persona: queda a nombre de la nueva.
        self.client.force_login(self.admin)
        self.client.post(url, json.dumps(_sub(1)), content_type='application/json')
        self.assertEqual(SuscripcionPush.objects.count(), 1)
        self.assertEqual(SuscripcionPush.objects.get().usuario, self.admin)

    def test_suscribir_rechaza_datos_invalidos_y_usuarios_sin_rol(self):
        url = reverse('econotec:push_suscribir')
        self.client.force_login(self.tecnico)
        malo = {'endpoint': 'http://inseguro', 'keys': {'p256dh': 'x', 'auth': 'y'}}
        self.assertEqual(self.client.post(url, json.dumps(malo), content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(url, 'no es json', content_type='application/json').status_code, 400)

        self.client.force_login(self.sin_rol)
        self.assertEqual(self.client.post(url, json.dumps(_sub(1)), content_type='application/json').status_code, 403)
        self.assertFalse(SuscripcionPush.objects.exists())

    def test_desuscribir_y_cerrar_sesion_quitan_el_dispositivo(self):
        self.client.force_login(self.asesora)
        self.client.post(reverse('econotec:push_suscribir'), json.dumps(_sub(1)), content_type='application/json')
        self.client.post(reverse('econotec:push_desuscribir'), json.dumps({'endpoint': _sub(1)['endpoint']}),
                         content_type='application/json')
        self.assertFalse(SuscripcionPush.objects.exists())

        self.client.post(reverse('econotec:push_suscribir'), json.dumps(_sub(2)), content_type='application/json')
        self.client.post(reverse('logout'))
        self.assertFalse(SuscripcionPush.objects.exists())

    # ── Avisos de las campanitas ───────────────────────────

    @mock.patch('pywebpush.webpush')
    def test_cambio_de_tecnico_llega_a_todos_los_admins(self, webpush):
        self.suscribir(self.admin, 1)
        self.suscribir(self.admin2, 2)
        self.suscribir(self.tecnico, 3)
        with self.captureOnCommitCallbacks(execute=True):
            aviso = avisar_cambio(self.tecnico, 'estado', 'Cambió el estado del equipo GYE-1.', codigo='GYE-1')
        self.assertEqual(self.destinos(webpush), [_sub(1)['endpoint'], _sub(2)['endpoint']])
        datos = json.loads(webpush.call_args.kwargs['data'])
        self.assertIn('Victor', datos['titulo'])
        self.assertIn('GYE-1', datos['titulo'])
        self.assertEqual(datos['url'], reverse('econotec:notificacion_cambio_admin_ver', args=[aviso.pk]))
        self.assertIsNotNone(SuscripcionPush.objects.get(endpoint=_sub(1)['endpoint']).ultimo_envio)

    @mock.patch('pywebpush.webpush')
    def test_aviso_al_tecnico_solo_le_llega_a_el(self, webpush):
        self.suscribir(self.admin, 1)
        self.suscribir(self.tecnico, 2)
        salida = self.crear_salida()
        with self.captureOnCommitCallbacks(execute=True):
            NotificacionTecnico.objects.create(
                salida=salida, ingreso=salida.ingreso, tecnico=self.tecnico,
                creado_por=self.asesora, mensaje='Revisa el equipo.',
            )
        self.assertEqual(self.destinos(webpush), [_sub(2)['endpoint']])
        self.assertIn('Maria', json.loads(webpush.call_args.kwargs['data'])['titulo'])

    @mock.patch('pywebpush.webpush')
    def test_asesora_recibe_su_aviso_sin_repetir_al_reguardar(self, webpush):
        self.suscribir(self.asesora, 1)
        salida = self.crear_salida()

        def guardar(**extra):
            datos = {'ingreso': salida.ingreso, 'asesora': self.asesora, 'valor_acordado': Decimal('10'),
                     'mensaje': 'Cobrar saldo.', 'leida': False, 'leida_en': None}
            datos.update(extra)
            with self.captureOnCommitCallbacks(execute=True):
                NotificacionAsesora.objects.update_or_create(
                    salida=salida, tipo=NotificacionAsesora.TIPO_SALDO_RETIRO, defaults=datos,
                )

        guardar()
        self.assertEqual(webpush.call_count, 1)
        guardar(mensaje='Cobrar saldo (editado).')  # se vuelve a guardar la salida
        self.assertEqual(webpush.call_count, 1)

        NotificacionAsesora.objects.update(leida=True, leida_en=timezone.now())
        guardar()  # ya la había visto y vuelve a quedar pendiente
        self.assertEqual(webpush.call_count, 2)

    @mock.patch('pywebpush.webpush')
    def test_equipo_de_prueba_demorado_llega_a_los_admins(self, webpush):
        self.suscribir(self.admin, 1)
        salida = self.crear_salida(estado_reparacion='revision', subestado_revision='equipo_prueba')
        SalidaEquipo.objects.filter(pk=salida.pk).update(
            fecha_subestado_revision=timezone.now() - timedelta(days=6),
        )
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(generar_avisos_prueba_demorada(), 1)
        self.assertEqual(webpush.call_count, 1)
        with self.captureOnCommitCallbacks(execute=True):
            generar_avisos_prueba_demorada()  # no se repite
        self.assertEqual(webpush.call_count, 1)

    @mock.patch('pywebpush.webpush')
    def test_suscripcion_vencida_se_borra(self, webpush):
        from pywebpush import WebPushException
        self.suscribir(self.admin, 1)
        respuesta = mock.Mock(status_code=410)
        webpush.side_effect = WebPushException('Gone', response=respuesta)
        with self.captureOnCommitCallbacks(execute=True):
            avisar_cambio(self.tecnico, 'estado', 'Algo.')
        self.assertFalse(SuscripcionPush.objects.exists())

    @mock.patch('pywebpush.webpush')
    @override_settings(PUSH_ACTIVO=False)
    def test_interruptor_apaga_el_push(self, webpush):
        self.suscribir(self.admin, 1)
        with self.captureOnCommitCallbacks(execute=True):
            avisar_cambio(self.tecnico, 'estado', 'Algo.')
        webpush.assert_not_called()

    @mock.patch('pywebpush.webpush')
    def test_boton_de_prueba(self, webpush):
        self.suscribir(self.admin, 1)
        self.client.force_login(self.admin)
        r = self.client.post(reverse('econotec:push_probar'))
        self.assertEqual(r.json()['enviados'], 1)
