import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import IngresoEquipoForm
from .alertas import equipos_demorados_qs, salidas_bodegaje_qs, whatsapp_link_equipo_listo
from .models import (
    BitacoraTecnico, Cliente, IngresoEquipo, NotificacionAsesora,
    SalidaEquipo, UsuarioActividad,
)
from .qr_utils import token_para_ingreso
from .views_auth import CAPTCHA_SESSION_KEY, LOGIN_2FA_SESSION_KEY, LOGIN_EMAIL_SETUP_SESSION_KEY


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class LoginCaptchaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.usuario = User.objects.create_user(
            username='captcha_user',
            password='testpass123',
            email='captcha_user@example.com',
        )
        self.usuario_sin_correo = User.objects.create_user(
            username='sin_correo',
            password='testpass123',
        )

    def _captcha_answer(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        return str(self.client.session[CAPTCHA_SESSION_KEY])

    def test_login_rechaza_captcha_incorrecto(self):
        respuesta = self._captcha_answer()

        response = self.client.post(reverse('login'), {
            'username': self.usuario.username,
            'password': 'testpass123',
            'sede': 'guayaquil',
            'captcha_respuesta': str(int(respuesta) + 1),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Resuelve correctamente la suma de seguridad.')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_acepta_captcha_correcto_y_envia_codigo(self):
        respuesta = self._captcha_answer()

        response = self.client.post(reverse('login'), {
            'username': self.usuario.username,
            'password': 'testpass123',
            'sede': 'quito',
            'captcha_respuesta': respuesta,
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('login_2fa'))
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.session[LOGIN_2FA_SESSION_KEY]['sede'], 'quito')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Código de acceso Econotec', mail.outbox[0].subject)
        html = next(
            alternativa[0]
            for alternativa in mail.outbox[0].alternatives
            if alternativa[1] == 'text/html'
        )
        self.assertIn('Econotec', html)
        self.assertIn('Verificación segura', html)
        self.assertIn('#f97618', html)

    def test_doble_factor_acepta_codigo_correcto_y_guarda_sede(self):
        respuesta = self._captcha_answer()
        self.client.post(reverse('login'), {
            'username': self.usuario.username,
            'password': 'testpass123',
            'sede': 'quito',
            'captcha_respuesta': respuesta,
        })
        codigo = re.search(r'\b(\d{6})\b', mail.outbox[0].body).group(1)

        response = self.client.post(reverse('login_2fa'), {
            'codigo': codigo,
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('econotec:bienvenida'))
        self.assertEqual(self.client.session['sede_actual'], 'quito')
        self.assertEqual(int(self.client.session['_auth_user_id']), self.usuario.pk)
        self.assertNotIn(LOGIN_2FA_SESSION_KEY, self.client.session)

    def test_doble_factor_rechaza_codigo_incorrecto(self):
        respuesta = self._captcha_answer()
        self.client.post(reverse('login'), {
            'username': self.usuario.username,
            'password': 'testpass123',
            'sede': 'guayaquil',
            'captcha_respuesta': respuesta,
        })
        codigo = re.search(r'\b(\d{6})\b', mail.outbox[0].body).group(1)
        codigo_incorrecto = '000000' if codigo != '000000' else '111111'

        response = self.client.post(reverse('login_2fa'), {
            'codigo': codigo_incorrecto,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Código incorrecto.')
        self.assertContains(response, 'Te quedan 9 intentos.')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_sin_correo_pide_registro_de_correo(self):
        respuesta = self._captcha_answer()

        response = self.client.post(reverse('login'), {
            'username': self.usuario_sin_correo.username,
            'password': 'testpass123',
            'sede': 'guayaquil',
            'captcha_respuesta': respuesta,
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('login_registrar_correo'))
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(
            self.client.session[LOGIN_EMAIL_SETUP_SESSION_KEY]['user_id'],
            self.usuario_sin_correo.pk,
        )

    def test_registro_correo_verificado_guarda_email_y_entra(self):
        respuesta = self._captcha_answer()
        self.client.post(reverse('login'), {
            'username': self.usuario_sin_correo.username,
            'password': 'testpass123',
            'sede': 'quito',
            'captcha_respuesta': respuesta,
        })

        response = self.client.post(reverse('login_registrar_correo'), {
            'accion': 'enviar_codigo',
            'email': 'nuevo@example.com',
            'email_confirmacion': 'nuevo@example.com',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('login_registrar_correo'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Verifica tu correo Econotec', mail.outbox[0].subject)
        html = next(
            alternativa[0]
            for alternativa in mail.outbox[0].alternatives
            if alternativa[1] == 'text/html'
        )
        self.assertIn('Verifica tu correo', html)
        self.assertIn('Registrar correo', html)
        self.assertIn('#f97618', html)
        self.usuario_sin_correo.refresh_from_db()
        self.assertEqual(self.usuario_sin_correo.email, '')

        codigo = re.search(r'\b(\d{6})\b', mail.outbox[0].body).group(1)
        response = self.client.post(reverse('login_registrar_correo'), {
            'accion': 'verificar',
            'codigo': codigo,
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('econotec:bienvenida'))
        self.usuario_sin_correo.refresh_from_db()
        self.assertEqual(self.usuario_sin_correo.email, 'nuevo@example.com')
        self.assertEqual(self.client.session['sede_actual'], 'quito')
        self.assertEqual(int(self.client.session['_auth_user_id']), self.usuario_sin_correo.pk)
        self.assertNotIn(LOGIN_EMAIL_SETUP_SESSION_KEY, self.client.session)

    def test_registro_correo_rechaza_email_duplicado(self):
        respuesta = self._captcha_answer()
        self.client.post(reverse('login'), {
            'username': self.usuario_sin_correo.username,
            'password': 'testpass123',
            'sede': 'guayaquil',
            'captcha_respuesta': respuesta,
        })

        response = self.client.post(reverse('login_registrar_correo'), {
            'accion': 'enviar_codigo',
            'email': self.usuario.email,
            'email_confirmacion': self.usuario.email,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ese correo ya está registrado en otro usuario.')
        self.assertEqual(len(mail.outbox), 0)
        self.usuario_sin_correo.refresh_from_db()
        self.assertEqual(self.usuario_sin_correo.email, '')


class VentasTests(TestCase):
    FIRMA_PNG_DATA_URI = (
        'data:image/png;base64,'
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgF/TV5CiwAAAABJRU5ErkJggg=='
    )

    def setUp(self):
        User = get_user_model()
        asesores = Group.objects.create(name='Asesores')
        tecnicos = Group.objects.create(name='Tecnicos')

        self.vendedor = User.objects.create_user(username='Kimberly', email='kimberly@example.com')
        self.vendedor.groups.add(asesores)

        self.usuario = User.objects.create_user(username='Yandri', email='yandri@example.com')
        self.usuario.groups.add(tecnicos)
        self.client.force_login(self.usuario)
        self.admin = User.objects.create_superuser(
            username='RootAdmin',
            email='admin@example.com',
            password='adminpass123',
        )

        self.cliente_existente = Cliente.objects.create(
            cedula='1207342716',
            nombres='Yandri Guevara',
            whatsapp='0939746169',
            correo='yandridavid@hotmail.com',
            sector='norte',
        )

    def venta_post_data(self, **overrides):
        data = {
            'cli-cedula': self.cliente_existente.cedula,
            'cli-nombres': self.cliente_existente.nombres,
            'cli-whatsapp': self.cliente_existente.whatsapp,
            'cli-correo': self.cliente_existente.correo,
            'cli-sector': self.cliente_existente.sector,
            'cli-sector_otro': '',
            'ing-asesor_comercial': 'Kimberly',
            'ing-fecha_ingreso': '2026-07-09',
            'ing-numero_factura': '',
            'ing-tecnico_encargado': str(self.usuario.pk),
            'ing-problema_reportado': 'tinta',
            'ing-valor_acordado': '25',
            'ing-firma_cliente_opcion': 'no',
            'ing-firma_cliente_imagen': '',
            # Valores que el navegador puede enviar desde campos ocultos.
            # Se omite ing-diagnostico_metodo para cubrir el bug corregido.
            'ing-tipo_equipo': 'otro',
            'ing-tipo_equipo_otro': '',
            'ing-marca': 'N/A',
            'ing-modelo_serie': 'N/A',
            'ing-serie': '',
            'ing-accesorios_entregados': 'Ninguno',
            'ing-diagnostico_inmediato': 'no',
            'ing-valor_diagnostico': '0.00',
            'ing-abono_anticipo': '0.00',
            'ing-anticipo_metodo': 'efectivo',
            'ing-estado': 'ingresado',
            'ing-subestado_reparacion': '',
            'ing-subestado_entregado': 'con_solucion',
            'ing-equipo_garantia': '',
            'ing-equipo_garantia_manual': '',
            'ing-motivo_garantia': '',
        }
        data.update(overrides)
        return data

    def crear_ingreso_reparacion(self, **overrides):
        data = {
            'sede': 'guayaquil',
            'asesor_comercial': 'Kimberly',
            'fecha_ingreso': date(2026, 7, 9),
            'cliente': self.cliente_existente,
            'tipo_equipo': 'laptop',
            'marca': 'HP',
            'modelo_serie': 'Elitebook',
            'accesorios_entregados': '',
            'problema_reportado': 'No enciende',
            'valor_acordado': Decimal('25.00'),
            'tecnico_encargado': self.usuario,
            'estado': 'en_reparacion',
            'subestado_reparacion': 'en_reparacion',
            'registrado_por': self.usuario,
        }
        data.update(overrides)
        return IngresoEquipo.objects.create(**data)

    def salida_post_data(self, **overrides):
        data = {
            'fecha_salida': '2026-07-17',
            'estado_reparacion': 'pendiente_retiro',
            'tecnico_reparo': str(self.usuario.pk),
            'reporte_tecnico': 'Equipo revisado.',
            'observaciones': '',
            'valor_final_cobrado': '0.00',
            'metodo_pago_final': 'efectivo',
            'numero_recibo': '',
            'banco': '',
            'banco_otro': '',
            'tarjeta_app': '',
            'comprobante_url': '',
            'monto_1': '',
            'metodo_1': '',
            'banco_1': '',
            'monto_2': '',
            'metodo_2': '',
            'banco_2': '',
            'factura_realizada': 'no',
            'factura_nombres': '',
            'factura_cedula': '',
            'factura_correo': '',
            'asesora_notificacion': '',
            'mensaje_notificacion': '',
        }
        data.update(overrides)
        return data

    def crear_notificacion_asesora(self, asesora=None, mensaje='Pendiente por cobrar.', **overrides):
        asesora = asesora or self.vendedor
        ingreso = self.crear_ingreso_reparacion(
            estado=overrides.pop('estado_ingreso', 'garantia'),
            valor_acordado=overrides.pop('valor_acordado_ingreso', Decimal('60.00')),
            marca=overrides.pop('marca', 'HP'),
            motivo_garantia='Garantía por retorno',
        )
        salida = SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 17),
            estado_reparacion=overrides.pop('estado_reparacion', 'garantia_fallos_adicionales'),
            tecnico_reparo=self.usuario,
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )
        notificacion = NotificacionAsesora.objects.create(
            salida=salida,
            ingreso=ingreso,
            asesora=asesora,
            creado_por=self.usuario,
            valor_acordado=overrides.pop('valor_acordado', Decimal('60.00')),
            mensaje=mensaje,
            **overrides,
        )
        return notificacion

    def crear_venta_producto(self, **overrides):
        data = {
            'sede': 'ventas',
            'asesor_comercial': 'Kimberly',
            'fecha_ingreso': date.today(),
            'cliente': self.cliente_existente,
            'tipo_equipo': 'otro',
            'marca': 'N/A',
            'modelo_serie': 'Producto',
            'accesorios_entregados': 'Ninguno',
            'problema_reportado': 'Venta de producto',
            'valor_acordado': Decimal('10.00'),
            'tecnico_encargado': self.usuario,
            'estado': 'entregado',
            'subestado_entregado': 'con_solucion',
            'registrado_por': self.usuario,
        }
        data.update(overrides)
        return IngresoEquipo.objects.create(**data)

    def ingreso_edit_post_data(self, ingreso, **overrides):
        data = {
            'cli-cedula': ingreso.cliente.cedula,
            'cli-nombres': ingreso.cliente.nombres,
            'cli-whatsapp': ingreso.cliente.whatsapp,
            'cli-correo': ingreso.cliente.correo,
            'cli-sector': ingreso.cliente.sector,
            'cli-sector_otro': ingreso.cliente.sector_otro,
            'ing-numero_factura': ingreso.numero_factura,
            'ing-asesor_comercial': ingreso.asesor_comercial,
            'ing-tecnico_encargado': str(ingreso.tecnico_encargado_id or ''),
            'ing-fecha_ingreso': ingreso.fecha_ingreso.isoformat(),
            'ing-tipo_equipo': ingreso.tipo_equipo,
            'ing-tipo_equipo_otro': ingreso.tipo_equipo_otro,
            'ing-marca': ingreso.marca,
            'ing-modelo_serie': ingreso.modelo_serie,
            'ing-serie': ingreso.serie,
            'ing-accesorios_entregados': ingreso.accesorios_entregados,
            'ing-problema_reportado': ingreso.problema_reportado,
            'ing-firma_cliente_opcion': 'si' if ingreso.firma_cliente and ingreso.firma_cliente_imagen else 'no',
            'ing-firma_cliente_imagen': ingreso.firma_cliente_imagen,
            'ing-diagnostico_inmediato': ingreso.diagnostico_inmediato,
            'ing-valor_diagnostico': str(ingreso.valor_diagnostico),
            'ing-valor_acordado': str(ingreso.valor_acordado or ''),
            'ing-abono_anticipo': str(ingreso.abono_anticipo),
            'ing-diagnostico_metodo': ingreso.diagnostico_metodo,
            'ing-diagnostico_banco': ingreso.diagnostico_banco,
            'ing-diagnostico_banco_otro': ingreso.diagnostico_banco_otro,
            'ing-diagnostico_tarjeta_app': ingreso.diagnostico_tarjeta_app,
            'ing-diagnostico_comprobante_url': ingreso.diagnostico_comprobante_url,
            'ing-diagnostico_monto_1': '',
            'ing-diagnostico_metodo_1': ingreso.diagnostico_metodo_1,
            'ing-diagnostico_banco_1': ingreso.diagnostico_banco_1,
            'ing-diagnostico_monto_2': '',
            'ing-diagnostico_metodo_2': ingreso.diagnostico_metodo_2,
            'ing-diagnostico_banco_2': ingreso.diagnostico_banco_2,
            'ing-anticipo_metodo': ingreso.anticipo_metodo,
            'ing-anticipo_banco': ingreso.anticipo_banco,
            'ing-anticipo_banco_otro': ingreso.anticipo_banco_otro,
            'ing-anticipo_tarjeta_app': ingreso.anticipo_tarjeta_app,
            'ing-anticipo_comprobante_url': ingreso.anticipo_comprobante_url,
            'ing-anticipo_monto_1': '',
            'ing-anticipo_metodo_1': ingreso.anticipo_metodo_1,
            'ing-anticipo_banco_1': ingreso.anticipo_banco_1,
            'ing-anticipo_monto_2': '',
            'ing-anticipo_metodo_2': ingreso.anticipo_metodo_2,
            'ing-anticipo_banco_2': ingreso.anticipo_banco_2,
            'ing-estado': ingreso.estado,
            'ing-subestado_reparacion': ingreso.subestado_reparacion,
            'ing-subestado_entregado': ingreso.subestado_entregado,
            'ing-equipo_garantia': '',
            'ing-equipo_garantia_manual': ingreso.equipo_garantia_manual or '',
            'ing-motivo_garantia': ingreso.motivo_garantia,
        }
        data.update(overrides)
        return data

    def ingreso_registro_post_data(self, **overrides):
        data = {
            'cli-cedula': self.cliente_existente.cedula,
            'cli-nombres': self.cliente_existente.nombres,
            'cli-whatsapp': self.cliente_existente.whatsapp,
            'cli-correo': self.cliente_existente.correo,
            'cli-sector': self.cliente_existente.sector,
            'cli-sector_otro': self.cliente_existente.sector_otro,
            'ing-numero_factura': '',
            'ing-asesor_comercial': 'Kimberly',
            'ing-tecnico_encargado': str(self.usuario.pk),
            'ing-fecha_ingreso': '2026-07-09',
            'ing-tipo_equipo': 'laptop',
            'ing-tipo_equipo_otro': '',
            'ing-marca': 'MacBook M4 S',
            'ing-modelo_serie': 'MacBook M4 S',
            'ing-serie': '',
            'ing-accesorios_entregados': 'Cargador',
            'ing-problema_reportado': 'No enciende',
            'ing-firma_cliente_opcion': 'no',
            'ing-firma_cliente_imagen': '',
            'ing-diagnostico_inmediato': 'no',
            'ing-valor_diagnostico': '0.00',
            'ing-valor_acordado': '25',
            'ing-abono_anticipo': '0.00',
            'ing-diagnostico_metodo': 'efectivo',
            'ing-diagnostico_banco': '',
            'ing-diagnostico_banco_otro': '',
            'ing-diagnostico_tarjeta_app': '',
            'ing-diagnostico_comprobante_url': '',
            'ing-diagnostico_monto_1': '',
            'ing-diagnostico_metodo_1': '',
            'ing-diagnostico_banco_1': '',
            'ing-diagnostico_monto_2': '',
            'ing-diagnostico_metodo_2': '',
            'ing-diagnostico_banco_2': '',
            'ing-anticipo_metodo': 'efectivo',
            'ing-anticipo_banco': '',
            'ing-anticipo_banco_otro': '',
            'ing-anticipo_tarjeta_app': '',
            'ing-anticipo_comprobante_url': '',
            'ing-anticipo_monto_1': '',
            'ing-anticipo_metodo_1': '',
            'ing-anticipo_banco_1': '',
            'ing-anticipo_monto_2': '',
            'ing-anticipo_metodo_2': '',
            'ing-anticipo_banco_2': '',
            'ing-estado': 'en_reparacion',
            'ing-subestado_reparacion': 'en_reparacion',
            'ing-subestado_entregado': '',
            'ing-equipo_garantia': '',
            'ing-equipo_garantia_manual': '',
            'ing-motivo_garantia': '',
        }
        data.update(overrides)
        return data

    def ingreso_form_data(self, **overrides):
        data = {
            key.replace('ing-', '', 1): value
            for key, value in self.ingreso_registro_post_data().items()
            if key.startswith('ing-')
        }
        data.update(overrides)
        return data

    def activar_sede_guayaquil(self):
        session = self.client.session
        session['sede_actual'] = 'guayaquil'
        session.save()

    def test_registrar_venta_no_requiere_campos_diagnostico_ocultos(self):
        response = self.client.post(
            reverse('econotec:venta_registrar'),
            self.venta_post_data(),
        )

        self.assertRedirects(response, reverse('econotec:venta_lista'))
        venta = IngresoEquipo.objects.get(sede='ventas')
        self.assertEqual(venta.cliente, self.cliente_existente)
        self.assertEqual(venta.estado, 'entregado')
        self.assertEqual(venta.subestado_entregado, 'con_solucion')
        self.assertEqual(venta.diagnostico_metodo, 'efectivo')
        self.assertEqual(venta.tecnico_encargado, self.usuario)
        self.assertEqual(venta.valor_acordado, Decimal('25.00'))

    def test_registrar_venta_exige_tecnico_que_vendio(self):
        response = self.client.post(
            reverse('econotec:venta_registrar'),
            self.venta_post_data(**{'ing-tecnico_encargado': ''}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(IngresoEquipo.objects.filter(sede='ventas').exists())
        self.assertIn('tecnico_encargado', response.context['ing_form'].errors)

    def test_editar_venta_conserva_estado_entregado(self):
        venta = IngresoEquipo.objects.create(
            sede='ventas',
            asesor_comercial='Kimberly',
            fecha_ingreso=date(2026, 7, 8),
            cliente=self.cliente_existente,
            tipo_equipo='otro',
            marca='N/A',
            modelo_serie='N/A',
            accesorios_entregados='Ninguno',
            problema_reportado='tinta anterior',
            valor_acordado=Decimal('10.00'),
            tecnico_encargado=self.usuario,
            estado='entregado',
            subestado_entregado='con_solucion',
        )

        response = self.client.post(
            reverse('econotec:venta_editar', kwargs={'pk': venta.pk}),
            self.venta_post_data(
                **{
                    'ing-problema_reportado': 'tinta negra',
                    'ing-valor_acordado': '30',
                    # Este valor llegaba desde el select oculto de la pantalla.
                    'ing-estado': 'ingresado',
                }
            ),
        )

        self.assertRedirects(response, reverse('econotec:venta_lista'))
        venta.refresh_from_db()
        self.assertEqual(venta.problema_reportado, 'tinta negra')
        self.assertEqual(venta.valor_acordado, Decimal('30.00'))
        self.assertEqual(venta.estado, 'entregado')
        self.assertEqual(venta.subestado_entregado, 'con_solucion')
        self.assertEqual(venta.tecnico_encargado, self.usuario)

    def test_perfil_suma_un_punto_por_salida_de_producto(self):
        response = self.client.post(
            reverse('econotec:venta_registrar'),
            self.venta_post_data(
                **{'ing-problema_reportado': 'tinta para perfil'}
            ),
        )
        self.assertRedirects(response, reverse('econotec:venta_lista'))

        response = self.client.get(reverse('econotec:api_perfil'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['email'], 'yandri@example.com')
        self.assertEqual(data['salidas_producto'], 1)
        self.assertEqual(data['total'], 1)
        self.assertGreaterEqual(data['bitacora_total'], 1)

    def test_api_bitacora_hoy_sin_datos_devuelve_vacia(self):
        response = self.client.get(reverse('econotec:api_bitacora_hoy'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['tiene_datos'])
        self.assertEqual(data['total'], 0)
        self.assertIn('Reporte del día', data['texto'])
        self.assertIn('Técnico: Yandri', data['texto'])

    def test_api_bitacora_hoy_genera_reporte_de_salida_del_tecnico(self):
        ingreso = self.crear_ingreso_reparacion(
            fecha_ingreso=timezone.localdate(),
            reporte_tecnico='Instalación de cartuchos nuevos y mantenimiento a Canon PIXMA G3110',
        )
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=timezone.localdate(),
            estado_reparacion='pendiente_retiro',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            tecnico_reparo=self.usuario,
            registrado_por=self.usuario,
        )

        response = self.client.get(reverse('econotec:api_bitacora_hoy'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['tiene_datos'])
        self.assertEqual(data['total'], 1)
        self.assertIn('Reporte del día', data['texto'])
        self.assertIn('Técnico: Yandri', data['texto'])
        self.assertIn('Instalación de cartuchos nuevos y mantenimiento a Canon PIXMA G3110', data['texto'])
        self.assertIn(f'#{ingreso.codigo_equipo} lista, cliente notificado.', data['texto'])
        self.assertRegex(data['texto'], r'\d{1,2}:\d{2} (AM|PM) - Instalación')
        self.assertNotRegex(data['texto'], r'\d{1,2}:\d{2} - \d{1,2}:\d{2}')

    def test_bitacora_se_reinicia_en_medianoche_local(self):
        from .views import _construir_bitacora_usuario

        zona_local = ZoneInfo('America/Guayaquil')
        dia_anterior = date(2026, 7, 22)
        dia_nuevo = date(2026, 7, 23)

        BitacoraTecnico.objects.create(
            user=self.usuario,
            usuario_nombre='Yandri',
            momento=datetime(2026, 7, 22, 23, 59, tzinfo=zona_local),
            tipo='reporte',
            texto='Acción antes de medianoche.',
        )
        BitacoraTecnico.objects.create(
            user=self.usuario,
            usuario_nombre='Yandri',
            momento=datetime(2026, 7, 23, 0, 0, tzinfo=zona_local),
            tipo='reporte',
            texto='Acción justo a medianoche.',
        )

        reporte_anterior = _construir_bitacora_usuario(self.usuario, dia=dia_anterior)
        reporte_nuevo = _construir_bitacora_usuario(self.usuario, dia=dia_nuevo)

        self.assertEqual(reporte_anterior['fecha'], '22/07/2026')
        self.assertEqual(reporte_anterior['total'], 1)
        self.assertIn('Acción antes de medianoche.', reporte_anterior['texto'])
        self.assertNotIn('Acción justo a medianoche.', reporte_anterior['texto'])

        self.assertEqual(reporte_nuevo['fecha'], '23/07/2026')
        self.assertEqual(reporte_nuevo['total'], 1)
        self.assertIn('12:00 AM - Acción justo a medianoche.', reporte_nuevo['texto'])
        self.assertNotIn('Acción antes de medianoche.', reporte_nuevo['texto'])

    def test_perfil_asesor_muestra_datos_basicos(self):
        self.client.force_login(self.vendedor)

        response = self.client.get(reverse('econotec:api_perfil'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['tipo_perfil'], 'asesor')
        self.assertEqual(data['nombre'], 'Kimberly')
        self.assertEqual(data['email'], 'kimberly@example.com')
        self.assertEqual(data['nivel'], 'Asesor registrado')
        self.assertEqual(data['total'], 0)
        self.assertEqual(data['color'], '#0d47a1')
        self.assertIn('#ec4899', data['colores_disponibles'])

    def test_perfil_asesor_guarda_color_preferido(self):
        self.client.force_login(self.vendedor)

        response = self.client.post(
            reverse('econotec:api_perfil_color'),
            data='{"color":"#ec4899"}',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['color'], '#ec4899')
        actividad = UsuarioActividad.objects.get(user=self.vendedor)
        self.assertEqual(actividad.perfil_color_asesor, '#ec4899')

        response = self.client.get(reverse('econotec:api_perfil'))
        self.assertEqual(response.json()['color'], '#ec4899')

    def test_perfil_asesor_rechaza_color_no_permitido(self):
        self.client.force_login(self.vendedor)

        response = self.client.post(
            reverse('econotec:api_perfil_color'),
            data='{"color":"#000000"}',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)

    def test_bienvenida_muestra_boton_perfil_para_asesor(self):
        self.client.force_login(self.vendedor)
        self.activar_sede_guayaquil()

        response = self.client.get(reverse('econotec:bienvenida'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="btn-perfil"')
        self.assertContains(response, 'Asesor')
        self.assertContains(response, 'Ver equipos que registré')
        self.assertContains(response, f'?registrador={self.vendedor.pk}&sede=todas')
        self.assertContains(response, 'Cambiar color del perfil')
        self.assertContains(response, 'data-color="#ec4899"')

    def test_detalle_muestra_asesor_que_registro_el_equipo(self):
        ingreso = self.crear_ingreso_reparacion(registrado_por=self.vendedor)

        response = self.client.get(reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Asesor que registró')
        self.assertContains(response, 'Kimberly')
        self.assertContains(response, 'kimberly@example.com')

    def test_perfil_suma_cuatro_puntos_por_salida_buena_positiva(self):
        ingreso = self.crear_ingreso_reparacion()
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='pendiente_retiro',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            tecnico_reparo=self.usuario,
            registrado_por=self.usuario,
        )

        response = self.client.get(reverse('econotec:api_perfil'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['salidas_buenas'], 1)
        self.assertEqual(data['total'], 4)

    def test_perfil_no_suma_puntos_de_salida_buena_si_no_es_positiva(self):
        ingreso = self.crear_ingreso_reparacion()
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='no_reparable',
            cliente_recibe_conforme='no',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            tecnico_reparo=self.usuario,
            registrado_por=self.usuario,
        )

        response = self.client.get(reverse('econotec:api_perfil'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['salidas_buenas'], 0)
        self.assertEqual(data['salidas_malas'], 1)
        self.assertEqual(data['total'], 0)

    def test_menu_ventas_muestra_control_de_pago_de_ventas(self):
        response = self.client.get(reverse('econotec:venta_menu'))

        self.assertContains(response, 'Control de Pago de Ventas')
        self.assertContains(response, reverse('econotec:pagos_ventas_lista'))

    def test_hoja_qr_muestra_categoria_marca_modelo_serie_y_problema(self):
        ingreso = self.crear_ingreso_reparacion(
            tipo_equipo='otro',
            tipo_equipo_otro='Consola',
            marca='Sony',
            modelo_serie='Playstation 5',
            serie='PS5-001',
            problema_reportado='No da grafica',
        )

        response = self.client.get(
            reverse('econotec:ingreso_imprimir_qr', kwargs={'pk': ingreso.pk})
        )

        self.assertContains(response, 'Consola', count=2)
        self.assertContains(response, 'Marca:', count=2)
        self.assertContains(response, 'Sony', count=2)
        self.assertContains(response, 'Modelo:', count=2)
        self.assertContains(response, 'Playstation 5', count=2)
        self.assertContains(response, 'Serie:', count=2)
        self.assertContains(response, 'PS5-001', count=2)
        self.assertContains(response, 'Problema:')
        self.assertContains(response, 'No da grafica', count=2)
        html = response.content.decode()
        self.assertLess(html.index('Consola'), html.index('Marca:'))
        self.assertLess(html.index('Marca:'), html.index('Modelo:'))
        self.assertLess(html.index('Modelo:'), html.index('Serie:'))
        self.assertLess(html.index('Serie:'), html.index('Problema:'))

    def test_hoja_qr_oculta_serie_si_no_se_registra(self):
        ingreso = self.crear_ingreso_reparacion(
            tipo_equipo='laptop',
            modelo_serie='Elitebook',
            serie='',
        )

        response = self.client.get(
            reverse('econotec:ingreso_imprimir_qr', kwargs={'pk': ingreso.pk})
        )

        self.assertContains(response, 'Modelo:', count=2)
        self.assertContains(response, 'Elitebook', count=2)
        self.assertNotContains(response, 'Serie:')

    def test_firma_cliente_imagen_no_es_obligatoria_si_cliente_no_firma(self):
        form = IngresoEquipoForm(data=self.ingreso_form_data(
            firma_cliente_opcion='no',
            firma_cliente_imagen='',
        ))

        self.assertTrue(form.is_valid(), form.errors.as_data())
        self.assertFalse(form.cleaned_data['firma_cliente'])
        self.assertEqual(form.cleaned_data['firma_cliente_imagen'], '')

    def test_firma_cliente_exige_seleccionar_si_o_no(self):
        data = self.ingreso_form_data()
        data.pop('firma_cliente_opcion')

        form = IngresoEquipoForm(data=data)

        self.assertFalse(form.is_valid())
        self.assertIn('firma_cliente_opcion', form.errors)

    def test_firma_cliente_si_exige_imagen_capturada(self):
        form = IngresoEquipoForm(data=self.ingreso_form_data(
            firma_cliente_opcion='si',
            firma_cliente_imagen='',
        ))

        self.assertFalse(form.is_valid())
        self.assertIn('firma_cliente_opcion', form.errors)

    def test_registrar_ingreso_guarda_firma_cliente_opcional(self):
        self.activar_sede_guayaquil()

        response = self.client.post(
            reverse('econotec:ingreso_registrar'),
            self.ingreso_registro_post_data(
                **{
                    'ing-firma_cliente_opcion': 'si',
                    'ing-firma_cliente_imagen': self.FIRMA_PNG_DATA_URI,
                }
            ),
        )

        ingreso = IngresoEquipo.objects.get(cliente=self.cliente_existente)
        self.assertRedirects(
            response,
            reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk}),
        )
        self.assertTrue(ingreso.firma_cliente)
        self.assertEqual(ingreso.firma_cliente_imagen, self.FIRMA_PNG_DATA_URI)

    def test_ingreso_imprimir_muestra_firma_cliente_si_existe(self):
        ingreso = self.crear_ingreso_reparacion(
            firma_cliente=True,
            firma_cliente_imagen=self.FIRMA_PNG_DATA_URI,
        )

        response = self.client.get(reverse('econotec:ingreso_imprimir', kwargs={'pk': ingreso.pk}))

        self.assertContains(response, 'alt="Firma del cliente"')
        self.assertContains(response, self.FIRMA_PNG_DATA_URI)

        pdf_response = self.client.get(reverse('econotec:ingreso_pdf', kwargs={'pk': ingreso.pk}))
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')

    def test_alerta_bodegaje_usa_tecnico_de_salida_y_tiene_desplegable(self):
        User = get_user_model()
        tecnicos = Group.objects.get(name='Tecnicos')
        tecnico_entrada = User.objects.create_user(
            username='EntradaTec',
            first_name='Entrada',
            last_name='Tec',
        )
        tecnico_salida = User.objects.create_user(
            username='SalidaTec',
            first_name='Salida',
            last_name='Tec',
        )
        tecnico_entrada.groups.add(tecnicos)
        tecnico_salida.groups.add(tecnicos)
        ingreso = self.crear_ingreso_reparacion(
            tecnico_encargado=tecnico_entrada,
            estado='entregado',
            subestado_entregado='con_solucion',
        )
        salida = SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date.today() - timedelta(days=5),
            estado_reparacion='pendiente_retiro',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            tecnico_reparo=tecnico_salida,
            registrado_por=self.usuario,
        )

        self.assertEqual(list(salidas_bodegaje_qs(usuario=tecnico_salida)), [salida])
        self.assertEqual(list(salidas_bodegaje_qs(usuario=tecnico_entrada)), [])

        response = self.client.get(reverse('econotec:bienvenida'))

        self.assertContains(response, 'Téc.:')
        self.assertContains(response, 'Salida Tec')
        self.assertNotContains(response, 'Entrada Tec')
        self.assertContains(response, 'id="btn-toggle-bodegaje"')
        self.assertContains(response, 'aria-controls="alerta-bodegaje-body"')
        self.assertContains(response, 'function toggleDashboardBodegaje')

        response = self.client.get(reverse('econotec:alertas_bodegaje'))

        self.assertContains(response, 'Técnico de salida', count=1)
        self.assertContains(response, 'Salida Tec')
        self.assertNotContains(response, 'Entrada Tec')

    def test_top_clientes_cuenta_equipos_reales_por_sede_sin_multiplicar(self):
        biomedics = Cliente.objects.create(
            cedula='0993018740001',
            nombres='BIOMEDICIS',
            whatsapp='0967792636',
            correo='eromero@grupobiomedics.com',
            sector='norte',
        )
        for _ in range(5):
            self.crear_ingreso_reparacion(cliente=biomedics, sede='guayaquil')
        for _ in range(2):
            self.crear_ingreso_reparacion(cliente=biomedics, sede='quito')
        for _ in range(3):
            self.crear_venta_producto(cliente=biomedics)

        response = self.client.get(reverse('econotec:cliente_top_recurrentes'))

        guayaquil = {
            cliente.pk: cliente.total_ingresos
            for cliente in response.context['clientes_guayaquil']
        }
        quito = {
            cliente.pk: cliente.total_ingresos
            for cliente in response.context['clientes_quito']
        }
        self.assertEqual(response.status_code, 200)
        self.assertEqual(guayaquil[biomedics.pk], 5)
        self.assertEqual(quito[biomedics.pk], 2)

    def test_busqueda_clientes_ignora_tildes_y_mayusculas(self):
        self.cliente_existente.nombres = 'Yandri Guevará'
        self.cliente_existente.save(update_fields=['nombres'])
        Cliente.objects.create(
            cedula='0927827281919',
            nombres='Randy Rodriguez',
            whatsapp='90939202',
            correo='photogamer2016pg@gmail.com',
            sector='norte',
        )

        response = self.client.get(reverse('econotec:cliente_lista'), {'q': 'guevara'})

        self.assertEqual(response.context['total'], 1)
        self.assertContains(response, 'Yandri Guevará')
        self.assertNotContains(response, 'Randy Rodriguez')

    def test_busqueda_lista_equipos_ignora_tildes_y_mayusculas(self):
        self.cliente_existente.nombres = 'Yandri Guevará'
        self.cliente_existente.save(update_fields=['nombres'])
        ingreso = self.crear_ingreso_reparacion()

        response = self.client.get(
            reverse('econotec:ingreso_lista'),
            {'q': 'guevara', 'sede': 'todas'},
        )

        self.assertEqual(response.context['total'], 1)
        self.assertContains(response, ingreso.codigo_equipo)
        self.assertContains(response, 'Yandri Guevará')

    def test_busqueda_lista_salidas_ignora_tildes_y_mayusculas(self):
        self.cliente_existente.nombres = 'Yandri Guevará'
        self.cliente_existente.save(update_fields=['nombres'])
        ingreso = self.crear_ingreso_reparacion()
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='pendiente_retiro',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            tecnico_reparo=self.usuario,
            registrado_por=self.usuario,
        )

        response = self.client.get(reverse('econotec:salida_lista'), {'q': 'GUEVARA'})

        self.assertEqual(response.context['total'], 1)
        self.assertContains(response, ingreso.codigo_equipo)
        self.assertContains(response, 'Yandri Guevará')

    def test_estado_visual_muestra_pendiente_retiro_si_salida_esta_pendiente(self):
        ingreso = self.crear_ingreso_reparacion(
            estado='entregado',
            subestado_entregado='con_solucion',
        )
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='pendiente_retiro',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )
        ingreso.refresh_from_db()

        self.assertEqual(ingreso.estado_visual_key, 'pendiente_retiro')
        self.assertEqual(ingreso.estado_visual_display, 'Pendiente de retiro')
        self.assertEqual(ingreso.subestado_visual_display, 'Reparado - pendiente de retiro')

        response = self.client.get(reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk}))

        self.assertContains(response, 'Pendiente de retiro')
        self.assertContains(response, 'Reparado - pendiente de retiro')
        self.assertNotContains(response, 'Listo para entrega')

    def test_alerta_diagnostico_excluye_ingreso_con_salida_registrada(self):
        ingreso = self.crear_ingreso_reparacion(
            estado='ingresado',
            subestado_reparacion='',
            fecha_ingreso=date.today() - timedelta(days=10),
        )
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date.today() - timedelta(days=6),
            estado_reparacion='pendiente_retiro',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )
        IngresoEquipo.objects.filter(pk=ingreso.pk).update(
            estado='ingresado',
            subestado_entregado='',
        )
        ingreso.refresh_from_db()

        self.assertEqual(ingreso.estado_visual_display, 'Pendiente de retiro')
        self.assertNotIn(ingreso, list(equipos_demorados_qs(usuario=None)))

    def test_editar_ingreso_con_salida_muestra_estado_bloqueado(self):
        ingreso = self.crear_ingreso_reparacion(
            valor_acordado=Decimal('100.00'),
            diagnostico_inmediato='si',
            valor_diagnostico=Decimal('10.00'),
            diagnostico_metodo='mixto',
            diagnostico_monto_1=Decimal('5.00'),
            diagnostico_metodo_1='transferencia',
            diagnostico_banco_1='pichincha',
            diagnostico_monto_2=Decimal('5.00'),
            diagnostico_metodo_2='efectivo',
        )
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='pendiente_retiro',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )

        response = self.client.get(
            reverse('econotec:ingreso_editar', kwargs={'pk': ingreso.pk})
        )

        self.assertContains(response, 'Pendiente de retiro')
        self.assertContains(response, 'Salida registrada')
        self.assertContains(response, 'El diagnóstico inmediato y su método de pago quedan bloqueados')
        self.assertContains(response, 'El valor acordado de este ingreso queda bloqueado')
        self.assertContains(response, '100.00')
        self.assertContains(response, '10.00')
        self.assertContains(response, 'disabled')
        self.assertContains(response, 'value="entregado"')
        self.assertNotContains(response, 'Ingresado / En diagnóstico')

    def test_editar_ingreso_con_salida_ignora_estado_posteado(self):
        ingreso = self.crear_ingreso_reparacion(
            valor_acordado=Decimal('100.00'),
            diagnostico_inmediato='si',
            valor_diagnostico=Decimal('10.00'),
            diagnostico_metodo='mixto',
            diagnostico_monto_1=Decimal('5.00'),
            diagnostico_metodo_1='transferencia',
            diagnostico_banco_1='pichincha',
            diagnostico_monto_2=Decimal('5.00'),
            diagnostico_metodo_2='efectivo',
        )
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='pendiente_retiro',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )
        IngresoEquipo.objects.filter(pk=ingreso.pk).update(
            estado='ingresado',
            subestado_entregado='',
        )
        ingreso.refresh_from_db()

        response = self.client.post(
            reverse('econotec:ingreso_editar', kwargs={'pk': ingreso.pk}),
            self.ingreso_edit_post_data(
                ingreso,
                **{
                    'ing-estado': 'ingresado',
                    'ing-subestado_entregado': '',
                    'ing-valor_acordado': '999.00',
                    'ing-valor_acordado_estado': 'si',
                    'ing-diagnostico_inmediato': 'no',
                    'ing-valor_diagnostico': '99.00',
                    'ing-diagnostico_metodo': 'efectivo',
                    'ing-diagnostico_monto_1': '',
                    'ing-diagnostico_metodo_1': '',
                    'ing-diagnostico_banco_1': '',
                    'ing-diagnostico_monto_2': '',
                    'ing-diagnostico_metodo_2': '',
                    'ing-diagnostico_banco_2': '',
                    'ing-modelo_serie': 'Elitebook actualizado',
                },
            ),
        )

        self.assertRedirects(
            response,
            reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk})
        )
        ingreso.refresh_from_db()
        self.assertEqual(ingreso.estado, 'entregado')
        self.assertEqual(ingreso.subestado_entregado, 'pendiente_retiro')
        self.assertEqual(ingreso.valor_acordado, Decimal('100.00'))
        self.assertEqual(ingreso.diagnostico_inmediato, 'si')
        self.assertEqual(ingreso.valor_diagnostico, Decimal('10.00'))
        self.assertEqual(ingreso.diagnostico_metodo, 'mixto')
        self.assertEqual(ingreso.diagnostico_monto_1, Decimal('5.00'))
        self.assertEqual(ingreso.diagnostico_metodo_1, 'transferencia')
        self.assertEqual(ingreso.diagnostico_banco_1, 'pichincha')
        self.assertEqual(ingreso.diagnostico_monto_2, Decimal('5.00'))
        self.assertEqual(ingreso.diagnostico_metodo_2, 'efectivo')
        self.assertEqual(ingreso.modelo_serie, 'Elitebook actualizado')

    def test_dashboard_modal_total_equipos_muestra_pendiente_retiro_visual(self):
        ingreso = self.crear_ingreso_reparacion(
            estado='entregado',
            subestado_entregado='con_solucion',
        )
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='pendiente_retiro',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )

        response = self.client.get(
            reverse('econotec:dashboard_details', kwargs={'tipo': 'equipos_total'})
        )

        self.assertContains(response, ingreso.codigo_equipo)
        self.assertContains(response, 'Pendiente de retiro')
        self.assertNotContains(response, 'Entregado al cliente')

    def test_dashboard_total_equipos_no_mezcla_ventas_producto(self):
        ingreso = self.crear_ingreso_reparacion(fecha_ingreso=date.today())
        venta = self.crear_venta_producto()

        response = self.client.get(reverse('econotec:bienvenida'))

        self.assertEqual(response.context['stats']['total_ingresos'], 1)
        self.assertEqual(response.context['stats']['ingresos_mes'], 1)
        self.assertEqual(response.context['equipos_top'][0]['nombre'], 'Laptop')
        self.assertNotEqual(ingreso.codigo_equipo[0], venta.codigo_equipo[0])

    def test_bienvenida_muestra_resumen_ingresos_y_salidas_por_sede_para_asesor(self):
        ingreso_g_1 = self.crear_ingreso_reparacion(sede='guayaquil')
        ingreso_g_2 = self.crear_ingreso_reparacion(sede='guayaquil')
        ingreso_u_1 = self.crear_ingreso_reparacion(sede='quito')
        venta = self.crear_venta_producto()
        SalidaEquipo.objects.create(
            ingreso=ingreso_g_1,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='pendiente_retiro',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )
        SalidaEquipo.objects.create(
            ingreso=ingreso_u_1,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='pendiente_retiro',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )
        self.client.force_login(self.vendedor)

        response = self.client.get(reverse('econotec:bienvenida'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Total de ingreso de equipo y salidas')
        self.assertContains(response, 'Sedes G / U')
        self.assertContains(response, '<details class="movement-summary"', html=False)
        self.assertContains(response, "abrirModalDashboard('ingresos_sede_guayaquil')")
        self.assertContains(response, "abrirModalDashboard('ingresos_sede_quito')")
        self.assertContains(response, "abrirModalDashboard('salidas_sede_guayaquil')")
        self.assertContains(response, "abrirModalDashboard('salidas_sede_quito')")
        self.assertEqual(response.context['resumen_movimientos']['ingresos']['guayaquil'], 2)
        self.assertEqual(response.context['resumen_movimientos']['ingresos']['quito'], 1)
        self.assertEqual(response.context['resumen_movimientos']['ingresos']['total'], 3)
        self.assertEqual(response.context['resumen_movimientos']['salidas']['guayaquil'], 1)
        self.assertEqual(response.context['resumen_movimientos']['salidas']['quito'], 1)
        self.assertEqual(response.context['resumen_movimientos']['salidas']['total'], 2)
        self.assertEqual(response.context['resumen_movimientos']['total_general'], 5)

        response_ingresos_g = self.client.get(
            reverse('econotec:dashboard_details', kwargs={'tipo': 'ingresos_sede_guayaquil'})
        )
        response_ingresos_u = self.client.get(
            reverse('econotec:dashboard_details', kwargs={'tipo': 'ingresos_sede_quito'})
        )
        response_salidas_g = self.client.get(
            reverse('econotec:dashboard_details', kwargs={'tipo': 'salidas_sede_guayaquil'})
        )
        response_salidas_u = self.client.get(
            reverse('econotec:dashboard_details', kwargs={'tipo': 'salidas_sede_quito'})
        )

        self.assertContains(response_ingresos_g, ingreso_g_1.codigo_equipo)
        self.assertContains(response_ingresos_g, ingreso_g_2.codigo_equipo)
        self.assertNotContains(response_ingresos_g, ingreso_u_1.codigo_equipo)
        self.assertNotContains(response_ingresos_g, venta.codigo_equipo)
        self.assertContains(response_ingresos_u, ingreso_u_1.codigo_equipo)
        self.assertNotContains(response_ingresos_u, ingreso_g_1.codigo_equipo)
        self.assertContains(response_salidas_g, ingreso_g_1.codigo_equipo)
        self.assertNotContains(response_salidas_g, ingreso_u_1.codigo_equipo)
        self.assertContains(response_salidas_u, ingreso_u_1.codigo_equipo)
        self.assertNotContains(response_salidas_u, ingreso_g_1.codigo_equipo)

    def test_dashboard_modal_total_equipos_excluye_ventas_producto(self):
        ingreso = self.crear_ingreso_reparacion(fecha_ingreso=date.today())
        venta = self.crear_venta_producto()

        response = self.client.get(
            reverse('econotec:dashboard_details', kwargs={'tipo': 'equipos_total'})
        )

        self.assertContains(response, ingreso.codigo_equipo)
        self.assertNotContains(response, venta.codigo_equipo)

    def test_admin_dashboard_equipos_mes_excluye_ventas_producto(self):
        User = get_user_model()
        admin = User.objects.create_superuser(username='Admin', password='x')
        self.client.force_login(admin)
        hoy = date.today()
        self.crear_ingreso_reparacion(fecha_ingreso=hoy)
        self.crear_venta_producto(fecha_ingreso=hoy)

        response = self.client.get(
            reverse('econotec:admin_dashboard'),
            {'ano': str(hoy.year), 'mes': str(hoy.month)},
        )

        self.assertEqual(response.context['equipos_ingresados'], 1)

    def test_estado_visual_conserva_entregado_con_solucion_si_cliente_retiro(self):
        ingreso = self.crear_ingreso_reparacion(estado='entregado')
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='retirado',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )
        ingreso.refresh_from_db()

        self.assertEqual(ingreso.estado_visual_key, 'entregado')
        self.assertEqual(ingreso.estado_visual_display, 'Entregado al cliente')
        self.assertEqual(ingreso.subestado_visual_display, 'Con solución')

        response = self.client.get(reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk}))

        self.assertContains(response, 'Entregado al cliente')
        self.assertContains(response, 'Con solución')

    def test_estado_visual_sin_solucion_usa_color_rojo(self):
        ingreso = self.crear_ingreso_reparacion(
            estado='entregado',
            subestado_entregado='sin_solucion',
        )
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='no_reparable',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )
        ingreso.refresh_from_db()

        self.assertEqual(ingreso.estado_visual_key, 'no_reparable')
        self.assertEqual(ingreso.estado_visual_display, 'Entregado al cliente')
        self.assertEqual(ingreso.subestado_visual_display, 'Sin solución')

        response = self.client.get(reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk}))

        self.assertContains(response, 'badge-no_reparable')
        self.assertContains(response, 'estado-no_reparable')
        self.assertContains(response, 'estado-subestado-no_reparable')

    def test_estado_visual_cliente_no_quiso_usa_color_amarillo(self):
        ingreso = self.crear_ingreso_reparacion(
            estado='entregado',
            subestado_entregado='no_quiso_reparar',
        )
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='cliente_no_acepta',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )
        ingreso.refresh_from_db()

        self.assertEqual(ingreso.estado_visual_key, 'cliente_no_acepta')
        self.assertEqual(ingreso.estado_visual_display, 'Entregado al cliente')
        self.assertEqual(ingreso.subestado_visual_display, 'No quiso repararlo')

        response = self.client.get(reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk}))

        self.assertContains(response, 'badge-cliente_no_acepta')
        self.assertContains(response, 'estado-cliente_no_acepta')
        self.assertContains(response, 'estado-subestado-cliente_no_acepta')

    def test_detalle_ingreso_retirado_bloquea_enlace_de_edicion(self):
        ingreso = self.crear_ingreso_reparacion(estado='entregado')
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            fecha_retiro_real=date(2026, 7, 10),
            estado_reparacion='retirado',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )
        ingreso.refresh_from_db()
        edit_url = reverse('econotec:ingreso_editar', kwargs={'pk': ingreso.pk})

        response = self.client.get(reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk}))

        self.assertTrue(ingreso.retirado_por_cliente)
        self.assertContains(response, 'Ya este equipo fue retirado por el cliente')
        self.assertContains(response, 'Hoja de ingreso cerrada')
        self.assertNotContains(response, f'href="{edit_url}"')

    def test_editar_ingreso_retirado_redirige_y_no_guarda_cambios(self):
        ingreso = self.crear_ingreso_reparacion(estado='entregado')
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            fecha_retiro_real=date(2026, 7, 10),
            estado_reparacion='retirado',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )
        ingreso.refresh_from_db()
        detalle_url = reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk})
        editar_url = reverse('econotec:ingreso_editar', kwargs={'pk': ingreso.pk})

        response_get = self.client.get(editar_url)
        response_post = self.client.post(
            editar_url,
            self.ingreso_edit_post_data(
                ingreso,
                **{'ing-problema_reportado': 'Cambio no permitido'}
            ),
        )

        self.assertRedirects(response_get, detalle_url)
        self.assertRedirects(response_post, detalle_url)
        ingreso.refresh_from_db()
        self.assertNotEqual(ingreso.problema_reportado, 'Cambio no permitido')

    def test_salida_imprimir_muestra_datos_de_factura_si_fue_realizada(self):
        ingreso = self.crear_ingreso_reparacion(estado='entregado')
        salida = SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='retirado',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('25.00'),
            metodo_pago_final='efectivo',
            factura_realizada='si',
            factura_nombres='Yandri Guevara',
            factura_cedula='1207342716',
            factura_correo='factura@example.com',
            registrado_por=self.usuario,
        )

        response = self.client.get(reverse('econotec:salida_imprimir', kwargs={'pk': salida.pk}))

        self.assertContains(response, 'FACTURA REALIZADA')
        self.assertContains(response, 'Nombres / Razón Social')
        self.assertContains(response, 'Yandri Guevara')
        self.assertContains(response, '1207342716')
        self.assertContains(response, 'factura@example.com')

        pdf_response = self.client.get(reverse('econotec:salida_pdf', kwargs={'pk': salida.pk}))
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')

    def test_salida_facturas_lista_muestra_solo_facturas_realizadas(self):
        User = get_user_model()
        admin = User.objects.create_superuser(
            username='AdminFacturas',
            email='admin-facturas@example.com',
            password='testpass123',
        )
        self.client.force_login(admin)

        ingreso_facturado = self.crear_ingreso_reparacion(
            estado='entregado',
            marca='Sony',
            modelo_serie='Playstation 5',
        )
        salida_facturada = SalidaEquipo.objects.create(
            ingreso=ingreso_facturado,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='retirado',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('100.00'),
            metodo_pago_final='efectivo',
            factura_realizada='si',
            factura_nombres='Yandri Guevara',
            factura_cedula='1207342716',
            factura_correo='factura@example.com',
            registrado_por=admin,
        )
        ingreso_sin_factura = self.crear_ingreso_reparacion(
            estado='entregado',
            marca='HP',
            modelo_serie='Elitebook Factura No',
        )
        SalidaEquipo.objects.create(
            ingreso=ingreso_sin_factura,
            fecha_salida=date(2026, 7, 10),
            estado_reparacion='retirado',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            factura_realizada='no',
            registrado_por=admin,
        )

        response = self.client.get(
            reverse('econotec:salida_facturas_lista'),
            {'ano': '2026', 'mes': '7'},
        )

        self.assertEqual(response.context['total_periodo'], 1)
        self.assertEqual(response.context['total'], 1)
        self.assertContains(response, 'Facturas <span class="accent">Realizadas</span>')
        self.assertContains(response, salida_facturada.ingreso.codigo_equipo)
        self.assertContains(response, 'factura@example.com')
        self.assertNotContains(response, 'Todas las salidas')
        self.assertNotContains(response, 'Factura realizada: No')
        self.assertNotContains(response, ingreso_sin_factura.codigo_equipo)

    def test_salida_menu_muestra_acceso_a_facturas_realizadas(self):
        ingreso = self.crear_ingreso_reparacion(estado='entregado')
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='retirado',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('25.00'),
            metodo_pago_final='efectivo',
            factura_realizada='si',
            factura_nombres='Yandri Guevara',
            factura_cedula='1207342716',
            factura_correo='factura@example.com',
            registrado_por=self.usuario,
        )

        response = self.client.get(reverse('econotec:salida_menu'))

        self.assertContains(response, 'Facturas Realizadas')
        self.assertContains(response, reverse('econotec:salida_facturas_lista'))
        self.assertContains(response, '1 salida con factura registrada.')

    def test_busqueda_pagos_ignora_tildes_y_mayusculas(self):
        self.cliente_existente.nombres = 'Yandri Guevará'
        self.cliente_existente.save(update_fields=['nombres'])
        ingreso = self.crear_ingreso_reparacion()

        response = self.client.get(reverse('econotec:pagos_lista'), {'q': 'guevara'})

        self.assertEqual(response.context['total_count'], 1)
        self.assertContains(response, ingreso.codigo_equipo)
        self.assertContains(response, 'Yandri Guevará')

    def test_busqueda_ventas_ignora_tildes_y_mayusculas(self):
        self.cliente_existente.nombres = 'Yandri Guevará'
        self.cliente_existente.save(update_fields=['nombres'])
        venta = IngresoEquipo.objects.create(
            sede='ventas',
            asesor_comercial='Kimberly',
            fecha_ingreso=date(2026, 7, 9),
            cliente=self.cliente_existente,
            tipo_equipo='otro',
            marca='N/A',
            modelo_serie='N/A',
            accesorios_entregados='Ninguno',
            problema_reportado='Tinta Epson',
            valor_acordado=Decimal('25.00'),
            tecnico_encargado=self.usuario,
            estado='entregado',
            subestado_entregado='con_solucion',
            registrado_por=self.usuario,
        )

        response = self.client.get(reverse('econotec:venta_lista'), {'q': 'GUEVARA'})

        self.assertEqual(response.context['total'], 1)
        self.assertContains(response, venta.codigo_equipo)
        self.assertContains(response, 'Yandri Guevará')

    def test_lista_ventas_muestra_tecnico_vendio_y_filtra_personal(self):
        User = get_user_model()
        tecnico_alt = User.objects.create_user(username='Carlos')
        tecnico_alt.groups.add(Group.objects.get(name='Tecnicos'))
        venta_yandri = self.crear_venta_producto(
            problema_reportado='Cable HDMI',
            tecnico_encargado=self.usuario,
            registrado_por=self.usuario,
        )
        venta_carlos = self.crear_venta_producto(
            problema_reportado='Mouse',
            tecnico_encargado=tecnico_alt,
            registrado_por=self.vendedor,
        )

        response = self.client.get(
            reverse('econotec:venta_lista'),
            {'tecnico_vendio': str(self.usuario.pk)},
        )

        self.assertContains(response, 'Técnico vendió')
        self.assertContains(response, venta_yandri.codigo_equipo)
        self.assertNotContains(response, venta_carlos.codigo_equipo)

        response = self.client.get(
            reverse('econotec:venta_lista'),
            {'registrador': str(self.vendedor.pk)},
        )

        self.assertContains(response, venta_carlos.codigo_equipo)
        self.assertNotContains(response, venta_yandri.codigo_equipo)

    def test_export_ventas_respeta_filtro_tecnico_vendio(self):
        User = get_user_model()
        tecnico_alt = User.objects.create_user(username='Carlos')
        tecnico_alt.groups.add(Group.objects.get(name='Tecnicos'))
        venta_yandri = self.crear_venta_producto(
            problema_reportado='Cable HDMI',
            tecnico_encargado=self.usuario,
        )
        venta_carlos = self.crear_venta_producto(
            problema_reportado='Mouse',
            tecnico_encargado=tecnico_alt,
        )

        response = self.client.get(
            reverse('econotec:venta_export'),
            {'tecnico_vendio': str(self.usuario.pk)},
        )

        from openpyxl import load_workbook
        wb = load_workbook(BytesIO(response.content))
        ws = wb.active
        headers = [cell.value for cell in ws[1]]
        codigos = [row[0] for row in ws.iter_rows(min_row=2, values_only=True)]

        self.assertIn('Técnico vendió', headers)
        self.assertIn(venta_yandri.codigo_equipo, codigos)
        self.assertNotIn(venta_carlos.codigo_equipo, codigos)

    def test_busqueda_control_pago_ventas_ignora_tildes_y_mayusculas(self):
        self.cliente_existente.nombres = 'Yandri Guevará'
        self.cliente_existente.save(update_fields=['nombres'])
        venta = IngresoEquipo.objects.create(
            sede='ventas',
            asesor_comercial='Kimberly',
            fecha_ingreso=date(2026, 7, 9),
            cliente=self.cliente_existente,
            tipo_equipo='otro',
            marca='N/A',
            modelo_serie='N/A',
            accesorios_entregados='Ninguno',
            problema_reportado='Tinta Epson',
            valor_acordado=Decimal('25.00'),
            tecnico_encargado=self.usuario,
            estado='entregado',
            subestado_entregado='con_solucion',
            registrado_por=self.usuario,
        )

        response = self.client.get(
            reverse('econotec:pagos_ventas_lista'),
            {'q': 'GUEVARA'},
        )

        self.assertEqual(response.context['total_count'], 1)
        self.assertContains(response, venta.codigo_equipo)
        self.assertContains(response, 'Yandri Guevará')

    def test_ingreso_permite_detalle_simple_en_reparacion(self):
        form = IngresoEquipoForm(data={
            'numero_factura': '',
            'asesor_comercial': 'Kimberly',
            'tecnico_encargado': str(self.usuario.pk),
            'fecha_ingreso': '2026-07-09',
            'tipo_equipo': 'laptop',
            'tipo_equipo_otro': '',
            'marca': 'HP',
            'modelo_serie': 'Elitebook',
            'serie': '',
            'accesorios_entregados': '',
            'problema_reportado': 'No enciende',
            'firma_cliente_opcion': 'no',
            'firma_cliente_imagen': '',
            'diagnostico_inmediato': 'no',
            'valor_diagnostico': '0.00',
            'valor_acordado': '25',
            'abono_anticipo': '0.00',
            'diagnostico_metodo': 'efectivo',
            'diagnostico_banco': '',
            'diagnostico_banco_otro': '',
            'diagnostico_tarjeta_app': '',
            'diagnostico_comprobante_url': '',
            'diagnostico_monto_1': '',
            'diagnostico_metodo_1': '',
            'diagnostico_banco_1': '',
            'diagnostico_monto_2': '',
            'diagnostico_metodo_2': '',
            'diagnostico_banco_2': '',
            'anticipo_metodo': 'efectivo',
            'anticipo_banco': '',
            'anticipo_banco_otro': '',
            'anticipo_tarjeta_app': '',
            'anticipo_comprobante_url': '',
            'anticipo_monto_1': '',
            'anticipo_metodo_1': '',
            'anticipo_banco_1': '',
            'anticipo_monto_2': '',
            'anticipo_metodo_2': '',
            'anticipo_banco_2': '',
            'estado': 'en_reparacion',
            'subestado_reparacion': 'en_reparacion',
            'subestado_entregado': '',
            'equipo_garantia': '',
            'equipo_garantia_manual': '',
            'motivo_garantia': '',
        })

        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertEqual(form.cleaned_data['subestado_reparacion'], 'en_reparacion')

    def test_valor_acordado_no_guarda_como_pendiente(self):
        form = IngresoEquipoForm(data=self.ingreso_form_data(
            valor_acordado_estado='no',
            valor_acordado='99.00',
        ))

        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertIsNone(form.cleaned_data['valor_acordado'])

    def test_valor_acordado_no_con_punto_guarda_como_pendiente(self):
        form = IngresoEquipoForm(data=self.ingreso_form_data(
            valor_acordado_estado='no',
            valor_acordado='.',
        ))

        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertIsNone(form.cleaned_data['valor_acordado'])

    def test_valor_acordado_si_exige_monto(self):
        form = IngresoEquipoForm(data=self.ingreso_form_data(
            valor_acordado_estado='si',
            valor_acordado='',
        ))

        self.assertFalse(form.is_valid())
        self.assertIn('valor_acordado', form.errors)

    def test_ingreso_garantia_fuerza_valor_acordado_cero(self):
        form = IngresoEquipoForm(data=self.ingreso_form_data(
            estado='garantia',
            subestado_reparacion='',
            valor_acordado_estado='si',
            valor_acordado='99.00',
            motivo_garantia='Falla cubierta por garantía',
        ))

        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertEqual(form.cleaned_data['valor_acordado'], Decimal('0.00'))

    def test_ingreso_garantia_no_valida_monto_manual(self):
        form = IngresoEquipoForm(data=self.ingreso_form_data(
            estado='garantia',
            subestado_reparacion='',
            valor_acordado_estado='si',
            valor_acordado='valor indebido',
            motivo_garantia='Falla cubierta por garantía',
        ))

        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertEqual(form.cleaned_data['valor_acordado'], Decimal('0.00'))

    def test_ingreso_garantia_fuerza_diagnostico_sin_cobro(self):
        form = IngresoEquipoForm(data=self.ingreso_form_data(
            estado='garantia',
            subestado_reparacion='',
            valor_acordado_estado='si',
            valor_acordado='99.00',
            diagnostico_inmediato='si',
            valor_diagnostico='25.00',
            diagnostico_metodo='mixto',
            diagnostico_monto_1='5.00',
            diagnostico_metodo_1='transferencia',
            diagnostico_banco_1='pichincha',
            diagnostico_monto_2='20.00',
            diagnostico_metodo_2='efectivo',
            motivo_garantia='Falla cubierta por garantía',
        ))

        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertEqual(form.cleaned_data['diagnostico_inmediato'], 'no')
        self.assertEqual(form.cleaned_data['valor_diagnostico'], Decimal('0.00'))
        self.assertEqual(form.cleaned_data['diagnostico_metodo'], 'efectivo')
        self.assertIsNone(form.cleaned_data['diagnostico_monto_1'])
        self.assertIsNone(form.cleaned_data['diagnostico_monto_2'])

    def test_detalle_bloquea_boton_salida_si_valor_acordado_pendiente(self):
        ingreso = self.crear_ingreso_reparacion(valor_acordado=None)

        response = self.client.get(
            reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk})
        )

        self.assertContains(response, 'btn-salida-bloqueada')
        self.assertContains(
            response,
            'Por favor registra un valor acordado para registrar la salida.'
        )

    def test_no_permite_registrar_salida_sin_valor_acordado(self):
        ingreso = self.crear_ingreso_reparacion(valor_acordado=None)

        response = self.client.get(
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': ingreso.pk})
        )

        self.assertRedirects(
            response,
            reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk})
        )
        self.assertFalse(SalidaEquipo.objects.filter(ingreso=ingreso).exists())

    def test_salida_garantia_fallos_adicionales_deja_valor_pendiente_y_notifica_asesora(self):
        ingreso = self.crear_ingreso_reparacion(
            estado='garantia',
            valor_acordado=Decimal('0.00'),
            motivo_garantia='Garantía por retorno',
            equipo_garantia_manual='G1000',
        )

        response = self.client.post(
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': ingreso.pk}),
            {
                'fecha_salida': '2026-07-17',
                'estado_reparacion': 'garantia_fallos_adicionales',
                'tecnico_reparo': str(self.usuario.pk),
                'reporte_tecnico': 'Se detectaron fallos adicionales.',
                'observaciones': '',
                'valor_final_cobrado': '75.00',
                'metodo_pago_final': 'sin_pago',
                'numero_recibo': '',
                'banco': '',
                'banco_otro': '',
                'tarjeta_app': '',
                'comprobante_url': '',
                'monto_1': '',
                'metodo_1': '',
                'banco_1': '',
                'monto_2': '',
                'metodo_2': '',
                'banco_2': '',
                'factura_realizada': 'no',
                'factura_nombres': '',
                'factura_cedula': '',
                'factura_correo': '',
                'asesora_notificacion': str(self.vendedor.pk),
                'mensaje_notificacion': 'Cobrar fallos adicionales antes del retiro.',
            },
        )

        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        self.assertRedirects(response, reverse('econotec:salida_listo_aviso', kwargs={'pk': salida.pk}))
        ingreso.refresh_from_db()
        self.assertEqual(salida.estado_reparacion, 'garantia_fallos_adicionales')
        self.assertEqual(salida.valor_final_cobrado, Decimal('0.00'))
        self.assertEqual(salida.metodo_pago_final, 'sin_pago')
        self.assertEqual(ingreso.valor_acordado, Decimal('75.00'))
        self.assertEqual(ingreso.diferencia, Decimal('75.00'))
        self.assertEqual(ingreso.estado_pago, 'Pendiente')

        notificacion = NotificacionAsesora.objects.get(salida=salida)
        self.assertEqual(notificacion.asesora, self.vendedor)
        self.assertEqual(notificacion.valor_acordado, Decimal('75.00'))
        self.assertFalse(notificacion.leida)

    def test_salida_cliente_no_acepta_revision_pendiente_notifica_asesora(self):
        ingreso = self.crear_ingreso_reparacion(valor_acordado=Decimal('40.00'))

        response = self.client.post(
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': ingreso.pk}),
            self.salida_post_data(
                estado_reparacion='cliente_no_acepta',
                valor_final_cobrado='12.00',
                metodo_pago_final='sin_pago',
                asesora_notificacion=str(self.vendedor.pk),
                mensaje_notificacion='Cobrar revisión antes del retiro.',
            ),
        )

        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        self.assertRedirects(response, reverse('econotec:salida_listo_aviso', kwargs={'pk': salida.pk}))
        ingreso.refresh_from_db()
        self.assertEqual(salida.valor_final_cobrado, Decimal('0.00'))
        self.assertEqual(salida.metodo_pago_final, 'sin_pago')
        self.assertEqual(ingreso.diferencia, Decimal('12.00'))
        self.assertEqual(ingreso.estado_pago, 'Pendiente')

        notificacion = NotificacionAsesora.objects.get(salida=salida)
        self.assertEqual(notificacion.tipo, NotificacionAsesora.TIPO_REVISION_PENDIENTE)
        self.assertEqual(notificacion.asesora, self.vendedor)
        self.assertEqual(notificacion.valor_acordado, Decimal('12.00'))

    def test_salida_no_reparable_revision_pendiente_notifica_asesora(self):
        ingreso = self.crear_ingreso_reparacion(valor_acordado=Decimal('40.00'))

        response = self.client.post(
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': ingreso.pk}),
            self.salida_post_data(
                estado_reparacion='no_reparable',
                valor_final_cobrado='7.00',
                metodo_pago_final='sin_pago',
                asesora_notificacion=str(self.vendedor.pk),
                mensaje_notificacion='Cobrar revisión antes del retiro.',
            ),
        )

        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        self.assertRedirects(response, reverse('econotec:salida_listo_aviso', kwargs={'pk': salida.pk}))
        ingreso.refresh_from_db()
        self.assertEqual(salida.valor_final_cobrado, Decimal('0.00'))
        self.assertEqual(ingreso.diferencia, Decimal('7.00'))

        notificacion = NotificacionAsesora.objects.get(salida=salida)
        self.assertEqual(notificacion.tipo, NotificacionAsesora.TIPO_REVISION_PENDIENTE)
        self.assertEqual(notificacion.valor_acordado, Decimal('7.00'))

    def test_salida_revision_pendiente_acepta_minimo_un_dolar(self):
        ingreso = self.crear_ingreso_reparacion(valor_acordado=Decimal('40.00'))

        response = self.client.post(
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': ingreso.pk}),
            self.salida_post_data(
                estado_reparacion='cliente_no_acepta',
                valor_final_cobrado='1.00',
                metodo_pago_final='sin_pago',
                asesora_notificacion=str(self.vendedor.pk),
                mensaje_notificacion='Cobrar revisión antes del retiro.',
            ),
        )

        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        self.assertRedirects(response, reverse('econotec:salida_listo_aviso', kwargs={'pk': salida.pk}))
        ingreso.refresh_from_db()
        self.assertEqual(ingreso.diferencia, Decimal('1.00'))

        notificacion = NotificacionAsesora.objects.get(salida=salida)
        self.assertEqual(notificacion.tipo, NotificacionAsesora.TIPO_REVISION_PENDIENTE)
        self.assertEqual(notificacion.valor_acordado, Decimal('1.00'))

    def test_salida_pendiente_retiro_con_saldo_notifica_asesora(self):
        ingreso = self.crear_ingreso_reparacion(valor_acordado=Decimal('100.00'))

        response = self.client.post(
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': ingreso.pk}),
            self.salida_post_data(
                estado_reparacion='pendiente_retiro',
                valor_final_cobrado='20.00',
                metodo_pago_final='efectivo',
                asesora_notificacion=str(self.vendedor.pk),
                mensaje_notificacion='Equipo listo, falta saldo.',
            ),
        )

        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        self.assertRedirects(response, reverse('econotec:salida_listo_aviso', kwargs={'pk': salida.pk}))
        ingreso.refresh_from_db()
        self.assertEqual(salida.valor_final_cobrado, Decimal('0.00'))
        self.assertEqual(salida.metodo_pago_final, 'sin_pago')
        self.assertEqual(ingreso.diferencia, Decimal('100.00'))

        notificacion = NotificacionAsesora.objects.get(salida=salida)
        self.assertEqual(notificacion.tipo, NotificacionAsesora.TIPO_SALDO_RETIRO)
        self.assertEqual(notificacion.valor_acordado, Decimal('100.00'))

    def test_salida_pendiente_retiro_pagada_no_crea_notificacion(self):
        ingreso = self.crear_ingreso_reparacion(
            valor_acordado=Decimal('25.00'),
            abono_anticipo=Decimal('25.00'),
        )

        response = self.client.post(
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': ingreso.pk}),
            self.salida_post_data(
                estado_reparacion='pendiente_retiro',
                valor_final_cobrado='25.00',
                metodo_pago_final='efectivo',
            ),
        )

        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        self.assertRedirects(response, reverse('econotec:salida_listo_aviso', kwargs={'pk': salida.pk}))
        ingreso.refresh_from_db()
        self.assertEqual(salida.valor_final_cobrado, Decimal('0.00'))
        self.assertEqual(salida.metodo_pago_final, 'sin_pago')
        self.assertEqual(ingreso.diferencia, Decimal('0.00'))
        self.assertFalse(NotificacionAsesora.objects.filter(salida=salida).exists())

    def test_whatsapp_retirado_usa_mensaje_de_cierre_sin_bodegaje(self):
        ingreso = self.crear_ingreso_reparacion(
            valor_acordado=Decimal('25.00'),
            abono_anticipo=Decimal('25.00'),
        )
        salida = SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 17),
            fecha_retiro_real=date(2026, 7, 18),
            estado_reparacion='retirado',
            tecnico_reparo=self.usuario,
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )

        link = whatsapp_link_equipo_listo(salida)
        texto = parse_qs(urlparse(link).query)['text'][0]

        self.assertIn('entregado y retirado satisfactoriamente', texto)
        self.assertIn('Gracias por confiar su equipo a Econotec', texto)
        self.assertIn('reparación de sus próximos equipos', texto)
        self.assertIn('Fecha de retiro: 18/07/2026', texto)
        self.assertNotIn('listo para retiro', texto)
        self.assertNotIn('coordine con nosotros', texto)
        self.assertNotIn('Política de bodegaje', texto)

    def test_notificacion_asesora_se_puede_marcar_como_vista(self):
        ingreso = self.crear_ingreso_reparacion(
            estado='garantia',
            valor_acordado=Decimal('60.00'),
            motivo_garantia='Garantía por retorno',
        )
        salida = SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 17),
            estado_reparacion='garantia_fallos_adicionales',
            tecnico_reparo=self.usuario,
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )
        notificacion = NotificacionAsesora.objects.create(
            salida=salida,
            ingreso=ingreso,
            asesora=self.vendedor,
            creado_por=self.usuario,
            valor_acordado=Decimal('60.00'),
            mensaje='Pendiente por cobrar.',
        )

        self.client.force_login(self.vendedor)
        response = self.client.get(reverse('econotec:notificaciones_asesora'))
        self.assertContains(response, ingreso.codigo_equipo)
        self.assertContains(response, 'Pendiente por cobrar.')

        response = self.client.post(
            reverse('econotec:notificacion_asesora_marcar_vista', kwargs={'pk': notificacion.pk})
        )
        self.assertRedirects(response, reverse('econotec:notificaciones_asesora'))
        notificacion.refresh_from_db()
        self.assertTrue(notificacion.leida)
        self.assertIsNotNone(notificacion.leida_en)

    def test_notificacion_asesora_muestra_hecho_si_saldo_esta_pagado(self):
        ingreso = self.crear_ingreso_reparacion(
            estado='garantia',
            valor_acordado=Decimal('60.00'),
            motivo_garantia='Garantía por retorno',
        )
        salida = SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 17),
            estado_reparacion='garantia_fallos_adicionales',
            tecnico_reparo=self.usuario,
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )
        NotificacionAsesora.objects.create(
            salida=salida,
            ingreso=ingreso,
            asesora=self.vendedor,
            creado_por=self.usuario,
            valor_acordado=Decimal('60.00'),
            mensaje='Pendiente por cobrar.',
            leida=True,
        )
        ingreso.abonos.create(
            fecha=date(2026, 7, 17),
            monto=Decimal('60.00'),
            metodo='efectivo',
            registrado_por=self.vendedor,
        )

        self.client.force_login(self.vendedor)
        response = self.client.get(reverse('econotec:notificaciones_asesora'), {'estado': 'todas'})

        self.assertContains(response, 'Hecho')
        self.assertContains(response, 'noti-status-done')
        self.assertContains(response, 'noti-card hecha')
        self.assertContains(response, 'noti-valor pagado')

    def test_notificacion_asesora_limpiar_bandeja_borra_solo_sus_notificaciones(self):
        grupo_asesores = Group.objects.get(name='Asesores')
        otra_asesora = get_user_model().objects.create_user(
            username='OtraAsesora',
            email='otra@example.com',
        )
        otra_asesora.groups.add(grupo_asesores)

        ingreso_1 = self.crear_ingreso_reparacion(
            estado='garantia',
            valor_acordado=Decimal('60.00'),
            motivo_garantia='Garantía por retorno',
        )
        salida_1 = SalidaEquipo.objects.create(
            ingreso=ingreso_1,
            fecha_salida=date(2026, 7, 17),
            estado_reparacion='garantia_fallos_adicionales',
            tecnico_reparo=self.usuario,
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )
        NotificacionAsesora.objects.create(
            salida=salida_1,
            ingreso=ingreso_1,
            asesora=self.vendedor,
            creado_por=self.usuario,
            valor_acordado=Decimal('60.00'),
            mensaje='Pendiente por cobrar.',
        )

        ingreso_2 = self.crear_ingreso_reparacion(
            estado='garantia',
            valor_acordado=Decimal('40.00'),
            marca='Lenovo',
            motivo_garantia='Garantía por retorno',
        )
        salida_2 = SalidaEquipo.objects.create(
            ingreso=ingreso_2,
            fecha_salida=date(2026, 7, 17),
            estado_reparacion='garantia_fallos_adicionales',
            tecnico_reparo=self.usuario,
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )
        notificacion_otra = NotificacionAsesora.objects.create(
            salida=salida_2,
            ingreso=ingreso_2,
            asesora=otra_asesora,
            creado_por=self.usuario,
            valor_acordado=Decimal('40.00'),
            mensaje='Pendiente de otra asesora.',
        )

        self.client.force_login(self.vendedor)
        response = self.client.post(reverse('econotec:notificacion_asesora_limpiar_bandeja'))

        self.assertRedirects(response, reverse('econotec:notificaciones_asesora'))
        self.assertFalse(NotificacionAsesora.objects.filter(asesora=self.vendedor).exists())
        self.assertTrue(NotificacionAsesora.objects.filter(pk=notificacion_otra.pk).exists())

    def test_admin_ve_todas_las_notificaciones_de_asesoras_y_filtra_por_asesora(self):
        grupo_asesores = Group.objects.get(name='Asesores')
        otra_asesora = get_user_model().objects.create_user(
            username='OtraAsesora',
            email='otra@example.com',
        )
        otra_asesora.groups.add(grupo_asesores)
        self.crear_notificacion_asesora(self.vendedor, 'Pendiente de Kimberly.')
        self.crear_notificacion_asesora(
            otra_asesora,
            'Pendiente de otra asesora.',
            marca='Lenovo',
            valor_acordado=Decimal('40.00'),
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse('econotec:notificaciones_asesora'))

        self.assertContains(response, 'Control de notificaciones de asesoras')
        self.assertContains(response, 'Pendiente de Kimberly.')
        self.assertContains(response, 'Pendiente de otra asesora.')
        self.assertContains(response, 'Responder / gestionar pago')

        response = self.client.get(
            reverse('econotec:notificaciones_asesora'),
            {'asesora': str(otra_asesora.pk), 'estado': 'todas'},
        )

        self.assertNotContains(response, 'Pendiente de Kimberly.')
        self.assertContains(response, 'Pendiente de otra asesora.')

    def test_admin_puede_marcar_notificacion_de_asesora_como_gestionada(self):
        notificacion = self.crear_notificacion_asesora(
            self.vendedor,
            'Gestionar desde admin.',
        )

        self.client.force_login(self.admin)
        next_url = reverse('econotec:notificaciones_asesora') + '?estado=todas'
        response = self.client.post(
            reverse('econotec:notificacion_asesora_marcar_vista', kwargs={'pk': notificacion.pk}),
            {'next': next_url},
        )

        self.assertRedirects(response, next_url)
        notificacion.refresh_from_db()
        self.assertTrue(notificacion.leida)
        self.assertIsNotNone(notificacion.leida_en)

    def test_admin_ve_acceso_a_notificaciones_asesoras_en_inicio(self):
        self.crear_notificacion_asesora(self.vendedor, 'Pendiente visible para admin.')
        self.client.force_login(self.admin)

        response = self.client.get(reverse('econotec:bienvenida'))

        self.assertContains(response, 'Notificaciones asesoras')
        self.assertContains(response, 'Asesoras')
        self.assertContains(response, 'Pendientes: 1')

    def test_detalle_muestra_alerta_si_valor_acordado_pendiente(self):
        ingreso = self.crear_ingreso_reparacion(valor_acordado=None)

        response = self.client.get(
            reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk})
        )

        self.assertContains(response, 'pending-value-alert')
        self.assertContains(response, 'Pendiente de valor acordado')

    def test_menu_muestra_apartado_pendientes_de_valor_acordado(self):
        self.crear_ingreso_reparacion(valor_acordado=None)
        self.crear_ingreso_reparacion(
            valor_acordado=Decimal('45.00'),
            marca='Dell',
            modelo_serie='Inspiron',
        )

        response = self.client.get(reverse('econotec:ingreso_menu'))

        self.assertContains(response, 'Pendiente de Valores Acordados')
        self.assertContains(response, 'Lista de equipos sin valor acordado.')
        self.assertContains(response, '?sede=todas&valor=pendiente')
        self.assertContains(response, '1 pendiente')

    def test_lista_filtra_valor_acordado_pendiente(self):
        pendiente = self.crear_ingreso_reparacion(valor_acordado=None)
        con_valor = self.crear_ingreso_reparacion(
            valor_acordado=Decimal('80.00'),
            marca='Lenovo',
            modelo_serie='ThinkPad',
        )

        response = self.client.get(
            reverse('econotec:ingreso_lista'),
            {'sede': 'todas', 'valor': 'pendiente'},
        )

        ingresos = list(response.context['ingresos'])
        self.assertEqual(ingresos, [pendiente])
        self.assertNotIn(con_valor, ingresos)
        self.assertContains(response, 'Equipos <span class="accent">Pendientes de Valor</span>')
        self.assertContains(response, 'value="pendiente" selected')
        self.assertContains(response, 'Pendiente valor acordado')

    def test_hoja_tecnico_muestra_valor_acordado_y_registro_salida(self):
        ingreso = self.crear_ingreso_reparacion(valor_acordado=None)
        token = token_para_ingreso(ingreso.pk)

        response = self.client.get(reverse('econotec:tecnico_hoja', kwargs={'token': token}))

        self.assertContains(response, 'name="valor_acordado"')
        self.assertContains(response, 'Valor acordado')
        self.assertContains(response, 'id="valor-toggle"')
        self.assertContains(response, 'aria-expanded="false"')
        self.assertContains(response, 'id="valor-content" hidden')
        self.assertContains(response, 'readonly')
        self.assertContains(response, 'solo lectura')
        self.assertNotContains(response, 'Actualizar valor')
        self.assertContains(response, 'name="valor_pendiente_reporte"')
        self.assertContains(response, 'Reportar por qué está pendiente el valor acordado')
        self.assertContains(response, 'Registrar equipo listo o reparado')
        self.assertContains(response, 'id="btn-perfil-movil"')
        self.assertContains(response, 'Ver perfil')
        self.assertContains(response, 'id="perfil-mobile-modal"')
        self.assertContains(response, 'id="btn-bitacora-mobile"')
        self.assertContains(response, 'id="bitacora-mobile-modal"')

    def test_hoja_tecnico_reporta_motivo_valor_acordado_pendiente(self):
        ingreso = self.crear_ingreso_reparacion(valor_acordado=None)
        token = token_para_ingreso(ingreso.pk)

        response = self.client.post(
            reverse('econotec:tecnico_hoja', kwargs={'token': token}),
            {
                'reporte_tecnico': 'Equipo sigue en diagnostico',
                'valor_pendiente_reporte': 'Pendiente confirmar repuesto con proveedor.',
                'estado_movil': 'en_reparacion',
                'subestado_reparacion': '',
                'accion': 'reportar_valor_pendiente',
            },
        )

        self.assertRedirects(response, reverse('econotec:tecnico_hoja', kwargs={'token': token}))
        ingreso.refresh_from_db()
        self.assertEqual(ingreso.valor_pendiente_reporte, 'Pendiente confirmar repuesto con proveedor.')
        self.assertEqual(ingreso.valor_pendiente_reporte_por, self.usuario)
        self.assertIsNotNone(ingreso.valor_pendiente_reporte_actualizado)
        self.assertEqual(ingreso.reporte_tecnico, 'Equipo sigue en diagnostico')

        response = self.client.get(
            reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk})
        )
        self.assertContains(response, 'Pendiente de valor acordado')
        self.assertContains(response, 'Reporte del técnico')
        self.assertContains(response, 'Ver reporte del técnico')
        self.assertContains(response, 'Pendiente confirmar repuesto con proveedor.')

    def test_hoja_tecnico_no_actualiza_valor_acordado_desde_movil(self):
        ingreso = self.crear_ingreso_reparacion(
            valor_acordado=None,
            abono_anticipo=Decimal('5.00'),
        )
        token = token_para_ingreso(ingreso.pk)

        response = self.client.post(
            reverse('econotec:tecnico_hoja', kwargs={'token': token}),
            {
                'reporte_tecnico': 'Valor confirmado con el cliente',
                'valor_acordado': '100',
                'estado_movil': 'en_reparacion',
                'subestado_reparacion': '',
                'accion': 'actualizar_valor',
            },
        )

        self.assertRedirects(response, reverse('econotec:tecnico_hoja', kwargs={'token': token}))
        ingreso.refresh_from_db()
        self.assertIsNone(ingreso.valor_acordado)
        self.assertEqual(ingreso.estado_pago, 'Pendiente')

        response = self.client.get(reverse('econotec:tecnico_hoja', kwargs={'token': token}))
        self.assertContains(response, 'Sin valor acordado registrado')
        self.assertNotContains(response, 'Valor acordado total')

        response = self.client.get(
            reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk})
        )
        self.assertContains(response, 'btn-salida-bloqueada')

    def test_hoja_tecnico_bloquea_valor_si_esta_pagado_completo(self):
        ingreso = self.crear_ingreso_reparacion(
            valor_acordado=Decimal('5.00'),
            abono_anticipo=Decimal('5.00'),
        )
        token = token_para_ingreso(ingreso.pk)

        response = self.client.get(reverse('econotec:tecnico_hoja', kwargs={'token': token}))

        self.assertContains(response, 'Ya está pagado todo')
        self.assertContains(response, 'readonly')
        self.assertContains(response, 'Pagado')
        self.assertNotContains(response, 'Actualizar valor')

        response = self.client.post(
            reverse('econotec:tecnico_hoja', kwargs={'token': token}),
            {
                'reporte_tecnico': 'Se intentó cambiar el valor pagado',
                'valor_acordado': '200',
                'estado_movil': 'en_reparacion',
                'subestado_reparacion': '',
                'accion': 'actualizar_valor',
            },
        )

        self.assertRedirects(response, reverse('econotec:tecnico_hoja', kwargs={'token': token}))
        ingreso.refresh_from_db()
        self.assertEqual(ingreso.valor_acordado, Decimal('5.00'))

        response = self.client.post(
            reverse('econotec:tecnico_hoja', kwargs={'token': token}),
            {
                'reporte_tecnico': 'Listo para salida',
                'valor_acordado': '200',
                'estado_movil': 'en_reparacion',
                'subestado_reparacion': '',
                'accion': 'registrar_salida',
            },
        )

        self.assertRedirects(
            response,
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': ingreso.pk})
        )
        ingreso.refresh_from_db()
        self.assertEqual(ingreso.valor_acordado, Decimal('5.00'))
        self.assertFalse(SalidaEquipo.objects.filter(ingreso=ingreso).exists())

    def test_hoja_tecnico_no_registra_salida_con_valor_pendiente(self):
        ingreso = self.crear_ingreso_reparacion(valor_acordado=None)
        token = token_para_ingreso(ingreso.pk)

        response = self.client.post(
            reverse('econotec:tecnico_hoja', kwargs={'token': token}),
            {
                'reporte_tecnico': 'Listo para salir',
                'valor_acordado': '100',
                'estado_movil': 'en_reparacion',
                'subestado_reparacion': '',
                'accion': 'registrar_salida',
            },
        )

        self.assertRedirects(response, reverse('econotec:tecnico_hoja', kwargs={'token': token}))
        ingreso.refresh_from_db()
        self.assertIsNone(ingreso.valor_acordado)
        self.assertEqual(ingreso.reporte_tecnico, 'Listo para salir')
        self.assertFalse(SalidaEquipo.objects.filter(ingreso=ingreso).exists())

    def test_hoja_tecnico_redirige_a_registrar_salida_con_valor_real_existente(self):
        ingreso = self.crear_ingreso_reparacion(valor_acordado=Decimal('100.00'))
        token = token_para_ingreso(ingreso.pk)

        response = self.client.post(
            reverse('econotec:tecnico_hoja', kwargs={'token': token}),
            {
                'reporte_tecnico': 'Reparado y probado',
                'valor_acordado': '100',
                'estado_movil': 'en_reparacion',
                'subestado_reparacion': '',
                'accion': 'registrar_salida',
            },
        )

        self.assertRedirects(
            response,
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': ingreso.pk})
        )
        ingreso.refresh_from_db()
        self.assertEqual(ingreso.valor_acordado, Decimal('100.00'))
        self.assertFalse(SalidaEquipo.objects.filter(ingreso=ingreso).exists())

    def test_lista_ingresos_oculta_boton_detalle_salida_a_no_admin(self):
        ingreso = self.crear_ingreso_reparacion(estado='entregado')
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='pendiente_retiro',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.usuario,
        )

        response = self.client.get(
            reverse('econotec:ingreso_lista'),
            {'sede': 'todas'},
        )

        self.assertNotContains(response, 'Ver detalle de salida')

    def test_lista_ingresos_muestra_boton_detalle_salida_solo_admin(self):
        User = get_user_model()
        admin = User.objects.create_superuser(
            username='Admin',
            email='admin@example.com',
            password='testpass123',
        )
        self.client.force_login(admin)

        ingreso = self.crear_ingreso_reparacion(estado='entregado')
        salida = SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date(2026, 7, 9),
            estado_reparacion='pendiente_retiro',
            cliente_recibe_conforme='si',
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=admin,
        )

        response = self.client.get(
            reverse('econotec:ingreso_lista'),
            {'sede': 'todas'},
        )

        self.assertContains(response, 'Ver detalle de salida')
        self.assertContains(
            response,
            reverse('econotec:salida_editar', kwargs={'pk': salida.pk})
        )

    def test_lista_ingresos_muestra_y_filtra_garantia_de_ingreso(self):
        self.activar_sede_guayaquil()
        ingreso_garantia = self.crear_ingreso_reparacion(
            estado='garantia',
            marca='Epson',
            modelo_serie='L3250 Garantia',
            motivo_garantia='Garantia de ingreso',
        )
        self.crear_ingreso_reparacion(
            marca='HP',
            modelo_serie='Elitebook',
            estado='en_reparacion',
        )

        response = self.client.get(
            reverse('econotec:ingreso_lista'),
            {'estado': 'garantia'},
        )

        self.assertContains(response, 'Garantía (Ingreso)')
        self.assertContains(response, ingreso_garantia.codigo_equipo)
        self.assertContains(response, 'value="garantia" selected')
        self.assertEqual(response.context['total'], 1)

    def test_detalle_garantia_muestra_equipo_manual(self):
        ingreso = self.crear_ingreso_reparacion(
            estado='garantia',
            equipo_garantia_manual='G980',
            motivo_garantia='Garantia por revision',
        )

        response = self.client.get(
            reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk})
        )

        self.assertContains(response, 'Garantía de G980')

    def test_detalle_garantia_muestra_equipo_anterior_seleccionado(self):
        equipo_anterior = self.crear_ingreso_reparacion(
            marca='Epson',
            modelo_serie='L3250',
        )
        ingreso = self.crear_ingreso_reparacion(
            marca='Epson',
            modelo_serie='L3250 Garantia',
            estado='garantia',
            equipo_garantia=equipo_anterior,
            motivo_garantia='Garantia por equipo anterior',
        )

        response = self.client.get(
            reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk})
        )

        self.assertContains(response, f'Garantía de {equipo_anterior.codigo_equipo}')

    def test_editar_mismo_equipo_no_se_detecta_como_duplicado(self):
        ingreso = self.crear_ingreso_reparacion(
            marca='MacBook M4 S',
            modelo_serie='MacBook M4 S',
        )

        response = self.client.post(
            reverse('econotec:ingreso_editar', kwargs={'pk': ingreso.pk}),
            self.ingreso_edit_post_data(ingreso),
        )

        self.assertRedirects(
            response,
            reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk})
        )

    def test_editar_reingreso_igual_sin_cambiar_identidad_no_bloquea(self):
        ingreso = self.crear_ingreso_reparacion(
            marca='Sony',
            modelo_serie='Playstation 5',
        )
        self.crear_ingreso_reparacion(
            marca='Sony',
            modelo_serie='Playstation 5',
            problema_reportado='Reingreso anterior',
        )

        response = self.client.post(
            reverse('econotec:ingreso_editar', kwargs={'pk': ingreso.pk}),
            self.ingreso_edit_post_data(
                ingreso,
                **{'ing-problema_reportado': 'Solo actualizo el reporte'}
            ),
        )

        self.assertRedirects(
            response,
            reverse('econotec:ingreso_detalle', kwargs={'pk': ingreso.pk})
        )
        ingreso.refresh_from_db()
        self.assertEqual(ingreso.problema_reportado, 'Solo actualizo el reporte')

    def test_editar_a_otro_equipo_igual_si_se_detecta_como_duplicado(self):
        duplicado = self.crear_ingreso_reparacion(
            marca='MacBook M4 S',
            modelo_serie='MacBook M4 S',
        )
        ingreso = self.crear_ingreso_reparacion(
            marca='HP',
            modelo_serie='Elitebook',
        )

        response = self.client.post(
            reverse('econotec:ingreso_editar', kwargs={'pk': ingreso.pk}),
            self.ingreso_edit_post_data(
                ingreso,
                **{
                    'ing-marca': duplicado.marca,
                    'ing-modelo_serie': duplicado.modelo_serie,
                }
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('modelo_serie', response.context['ing_form'].errors)

    def test_registrar_mismo_equipo_y_cliente_sin_confirmacion_bloquea(self):
        self.activar_sede_guayaquil()
        self.crear_ingreso_reparacion(
            marca='MacBook M4 S',
            modelo_serie='MacBook M4 S',
        )

        response = self.client.post(
            reverse('econotec:ingreso_registrar'),
            self.ingreso_registro_post_data(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(IngresoEquipo.objects.filter(cliente=self.cliente_existente).count(), 1)
        self.assertIn('modelo_serie', response.context['ing_form'].errors)

    def test_registrar_mismo_modelo_ignora_mayusculas_y_tildes(self):
        self.activar_sede_guayaquil()
        self.crear_ingreso_reparacion(
            marca='Canon',
            modelo_serie='Cámara Pró',
            serie='ABC-001',
        )

        response = self.client.post(
            reverse('econotec:ingreso_registrar'),
            self.ingreso_registro_post_data(
                **{
                    'ing-marca': 'Canon',
                    'ing-modelo_serie': 'CAMARA PRO',
                    'ing-serie': 'XYZ-999',
                }
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(IngresoEquipo.objects.filter(cliente=self.cliente_existente).count(), 1)
        self.assertIn('modelo_serie', response.context['ing_form'].errors)

    def test_registrar_mismo_equipo_y_cliente_confirmado_crea_reingreso(self):
        self.activar_sede_guayaquil()
        ingreso_anterior = self.crear_ingreso_reparacion(
            marca='MacBook M4 S',
            modelo_serie='MacBook M4 S',
        )

        response = self.client.post(
            reverse('econotec:ingreso_registrar'),
            self.ingreso_registro_post_data(
                **{'confirmar_mismo_equipo_cliente': '1'}
            ),
        )

        nuevo_ingreso = IngresoEquipo.objects.exclude(pk=ingreso_anterior.pk).get()
        self.assertRedirects(
            response,
            reverse('econotec:ingreso_detalle', kwargs={'pk': nuevo_ingreso.pk})
        )
        self.assertEqual(nuevo_ingreso.cliente, self.cliente_existente)
        self.assertEqual(nuevo_ingreso.marca, 'MacBook M4 S')

    def test_nueva_solicitud_no_restaura_borrador_localstorage(self):
        self.activar_sede_guayaquil()

        response = self.client.get(reverse('econotec:ingreso_registrar'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="confirmar_mismo_equipo_cliente"')
        self.assertContains(response, 'name="ing-valor_acordado_estado"')
        self.assertContains(response, '¿El técnico ya tiene el valor acordado?')
        self.assertContains(response, 'No / pendiente de valor')
        self.assertContains(response, "localStorage.removeItem('econotec_ingreso_form_nuevo')")
        self.assertNotContains(response, "localStorage.getItem('econotec_ingreso_form_nuevo')")

    def test_lista_filtra_subestado_en_reparacion_simple(self):
        ingreso_reparacion = self.crear_ingreso_reparacion(
            marca='MacBook M4 S',
            subestado_reparacion='en_reparacion',
        )
        self.crear_ingreso_reparacion(
            marca='HP',
            subestado_reparacion='espera_repuesto',
        )

        response = self.client.get(
            reverse('econotec:ingreso_lista'),
            {'estado': 'reparacion_en_reparacion', 'sede': 'todas'},
        )

        ingresos = list(response.context['ingresos'])
        self.assertEqual(ingresos, [ingreso_reparacion])
        self.assertContains(response, '↳ En reparación')
