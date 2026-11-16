"""Salida de retiro (salida de la oficina).

La confirma la asesora o el administrador; el técnico ya no. Cada salida guarda
quién la confirmó: la asesora lo ve en su perfil y el administrador en el ranking.
Con saldo pendiente, el aviso ofrece pagar ahí mismo o notificar al técnico.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .models import Abono, Cliente, IngresoEquipo, NotificacionTecnico, SalidaEquipo
from .permisos import puede_confirmar_salida_fisica


class BaseSalidaRetiro(TestCase):
    """Usuarios, cliente y ayudas comunes (sin pruebas propias)."""

    def setUp(self):
        User = get_user_model()
        asesores = Group.objects.create(name='Asesores')
        tecnicos = Group.objects.create(name='Tecnicos')
        self.asesora = User.objects.create_user(username='kimberly', first_name='Kimberly', email='kim@example.com')
        self.asesora.groups.add(asesores)
        self.otra_asesora = User.objects.create_user(username='maria', first_name='Maria')
        self.otra_asesora.groups.add(asesores)
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri', email='tecnico@example.com')
        self.tecnico.groups.add(tecnicos)
        self.admin = User.objects.create_superuser(username='RootAdmin', email='a@example.com', password='x')
        self.cliente = Cliente.objects.create(
            cedula='1207342716', nombres='Cliente Prueba', whatsapp='0939746169',
            correo='cliente@example.com', sector='norte',
        )

    def crear_salida(self, valor=Decimal('0.00')):
        ingreso = IngresoEquipo.objects.create(
            sede='guayaquil', asesor_comercial='Kimberly', fecha_ingreso=date.today(),
            cliente=self.cliente, tipo_equipo='laptop', marca='HP', modelo_serie='Elitebook',
            problema_reportado='No enciende', valor_acordado=valor,
            tecnico_encargado=self.tecnico, estado='en_reparacion',
            subestado_reparacion='en_reparacion', registrado_por=self.tecnico,
        )
        return SalidaEquipo.objects.create(
            ingreso=ingreso, fecha_salida=date.today(), estado_reparacion='pendiente_retiro',
            tecnico_reparo=self.tecnico, valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago', registrado_por=self.tecnico,
        )

    def confirmar(self, salida):
        return self.client.post(reverse('econotec:salida_marcar_retirada', kwargs={'pk': salida.pk}))


class SalidaRetiroTests(BaseSalidaRetiro):

    # ── 1. El técnico ya no confirma la salida ───────────────────────
    def test_permiso_por_rol(self):
        self.assertTrue(puede_confirmar_salida_fisica(self.asesora))
        self.assertTrue(puede_confirmar_salida_fisica(self.admin))
        self.assertFalse(puede_confirmar_salida_fisica(self.tecnico))

    def test_tecnico_no_puede_confirmar_la_salida(self):
        salida = self.crear_salida()
        self.client.force_login(self.tecnico)

        self.confirmar(salida)

        salida.refresh_from_db()
        self.assertIsNone(salida.fecha_retiro_real)
        self.assertEqual(salida.estado_reparacion, 'pendiente_retiro')

    def test_tecnico_no_ve_el_boton_de_salida(self):
        salida = self.crear_salida()
        url_salida = reverse('econotec:salida_marcar_retirada', kwargs={'pk': salida.pk})
        self.client.force_login(self.tecnico)

        for nombre, kwargs in (('salida_lista', {}), ('ingreso_detalle', {'pk': salida.ingreso.pk})):
            respuesta = self.client.get(reverse(f'econotec:{nombre}', kwargs=kwargs))
            self.assertEqual(respuesta.status_code, 200)
            self.assertNotContains(respuesta, url_salida)

        self.client.force_login(self.asesora)
        self.assertContains(self.client.get(reverse('econotec:salida_lista')), url_salida)

    def test_tecnico_registra_abono_pero_no_da_salida(self):
        salida = self.crear_salida(valor=Decimal('50.00'))
        self.client.force_login(self.tecnico)
        url = reverse('econotec:abono_crear', kwargs={'ingreso_pk': salida.ingreso.pk})

        formulario = self.client.get(url)
        self.assertNotContains(formulario, 'id="submit-abono-salida"')
        self.assertNotContains(formulario, 'name="asesora_salida"')
        self.client.post(url, {
            'accion_abono': 'registrar_y_salida', 'fecha': date.today().isoformat(), 'monto': '50.00',
            'metodo': 'efectivo', 'factura_realizada': 'no', 'bodegaje_decision': 'na',
        })

        salida.refresh_from_db()
        self.assertEqual(Abono.objects.filter(ingreso=salida.ingreso).count(), 1)
        self.assertIsNone(salida.fecha_retiro_real)

    # ── 2. Queda registrado quién confirmó: perfil y ranking ─────────
    def test_la_salida_guarda_quien_la_confirmo_y_deshacer_lo_limpia(self):
        salida = self.crear_salida()
        self.client.force_login(self.asesora)
        self.confirmar(salida)

        salida.refresh_from_db()
        self.assertEqual(salida.fecha_retiro_real, date.today())
        self.assertEqual(salida.retiro_confirmado_por, self.asesora)

        self.client.force_login(self.admin)
        self.client.post(reverse('econotec:salida_deshacer_retiro', kwargs={'pk': salida.pk}))
        salida.refresh_from_db()
        self.assertIsNone(salida.retiro_confirmado_por)

    def test_perfil_de_la_asesora_muestra_sus_salidas_de_retiro(self):
        self.client.force_login(self.asesora)
        for _ in range(2):
            self.confirmar(self.crear_salida())

        perfil = self.client.get(reverse('econotec:mi_perfil'))
        self.assertEqual(perfil.context['retiros_asesora']['total'], 2)
        self.assertContains(perfil, 'Mis salidas de retiro')
        self.assertContains(perfil, f'?confirmo={self.asesora.pk}')

        lista = self.client.get(reverse('econotec:salida_retiros_lista'), {'confirmo': self.asesora.pk})
        self.assertEqual(lista.context['total'], 2)
        otra = self.client.get(reverse('econotec:salida_retiros_lista'), {'confirmo': self.otra_asesora.pk})
        self.assertEqual(otra.context['total'], 0)

        # Otra asesora no ve el contador ajeno; el técnico no tiene la sección.
        self.client.force_login(self.otra_asesora)
        ajeno = self.client.get(reverse('econotec:perfil_social', kwargs={'usuario_id': self.asesora.pk}))
        self.assertIsNone(ajeno.context['retiros_asesora'])
        self.client.force_login(self.tecnico)
        self.assertIsNone(self.client.get(reverse('econotec:mi_perfil')).context['retiros_asesora'])

    def test_ranking_de_asesoras_solo_para_el_administrador(self):
        self.client.force_login(self.asesora)
        salida = self.crear_salida()
        self.confirmar(salida)
        url = reverse('econotec:ranking_asesoras_salidas')
        self.assertEqual(self.client.get(url).status_code, 302)

        self.client.force_login(self.admin)
        respuesta = self.client.get(url)

        self.assertEqual(respuesta.status_code, 200)
        ranking = respuesta.context['ranking']
        self.assertEqual([(f['usuario'], f['total']) for f in ranking],
                         [(self.asesora, 1), (self.otra_asesora, 0)])
        self.assertContains(respuesta, salida.ingreso.codigo_equipo)
        self.assertContains(respuesta, 'Técnico responsable')
        self.assertContains(respuesta, 'Yandri')

    # ── 3. Saldo pendiente: pagar ahí mismo o notificar al técnico ───
    def test_lista_con_saldo_ofrece_pagar_y_notificar(self):
        salida = self.crear_salida(valor=Decimal('50.00'))
        self.client.force_login(self.asesora)

        lista = self.client.get(reverse('econotec:salida_lista'))

        self.assertContains(lista, 'return alertaSaldoPendienteSalida(event, this);')
        self.assertContains(lista, 'data-saldo-monto="50.00"')
        self.assertContains(lista, reverse('econotec:salida_notificar_tecnico', kwargs={'pk': salida.pk}))
        self.assertContains(lista, 'id="saldo-modal"')
        self.assertContains(lista, 'Notificar al técnico')

    def test_pagar_saldo_desde_la_ventana_da_la_salida(self):
        salida = self.crear_salida(valor=Decimal('50.00'))
        self.client.force_login(self.asesora)

        # Lo mismo que envía la ventana «Pagar saldo pendiente».
        respuesta = self.client.post(
            reverse('econotec:abono_crear', kwargs={'ingreso_pk': salida.ingreso.pk}),
            {
                'accion_abono': 'registrar_y_salida', 'fecha': date.today().isoformat(), 'monto': '50.00',
                'bodegaje_decision': 'na', 'metodo': 'transferencia', 'banco': 'pichincha',
                'banco_otro': '', 'tarjeta_app': '', 'comprobante_url': '', 'factura_realizada': 'no',
                'factura_nombres': 'Cliente Prueba', 'factura_cedula': '1207342716',
                'factura_correo': 'cliente@example.com',
            },
        )

        self.assertRedirects(respuesta, reverse('econotec:salida_retiros_lista'), fetch_redirect_response=False)
        salida.refresh_from_db()
        self.assertEqual(salida.ingreso.diferencia, Decimal('0.00'))
        self.assertEqual(salida.fecha_retiro_real, date.today())
        self.assertEqual(salida.retiro_confirmado_por, self.asesora)

    def test_notificar_al_tecnico_deja_aviso_y_envia_correo(self):
        salida = self.crear_salida(valor=Decimal('50.00'))
        url = reverse('econotec:salida_notificar_tecnico', kwargs={'pk': salida.pk})
        self.client.force_login(self.asesora)

        datos = self.client.post(url).json()

        self.assertTrue(datos['ok'])
        self.assertTrue(datos['correo_enviado'])
        notificacion = NotificacionTecnico.objects.get()
        self.assertEqual(notificacion.tecnico, self.tecnico)
        self.assertEqual(notificacion.creado_por, self.asesora)
        self.assertEqual(notificacion.saldo_pendiente, Decimal('50.00'))
        self.assertIn(salida.ingreso.codigo_equipo, notificacion.mensaje)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['tecnico@example.com'])
        self.assertIn(salida.ingreso.codigo_equipo, mail.outbox[0].subject)

        # Un segundo clic seguido no duplica el aviso ni el correo.
        self.assertTrue(self.client.post(url).json()['ok'])
        self.assertEqual(NotificacionTecnico.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

        # El técnico lo ve en su campanita y lo marca como visto.
        self.client.force_login(self.tecnico)
        inicio = self.client.get(reverse('econotec:notificaciones_tecnico'))
        self.assertEqual(inicio.context['notificaciones_tecnico_count'], 1)
        self.assertContains(inicio, 'tecnico-bell-btn')
        self.assertContains(inicio, salida.ingreso.codigo_equipo)
        self.client.post(reverse('econotec:notificacion_tecnico_marcar_vista', kwargs={'pk': notificacion.pk}))
        notificacion.refresh_from_db()
        self.assertTrue(notificacion.leida)

    def test_tecnico_no_puede_notificar_ni_ver_avisos_ajenos(self):
        salida = self.crear_salida(valor=Decimal('50.00'))
        self.client.force_login(self.tecnico)
        respuesta = self.client.post(reverse('econotec:salida_notificar_tecnico', kwargs={'pk': salida.pk}))
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(NotificacionTecnico.objects.exists())

        self.client.force_login(self.asesora)
        self.assertEqual(self.client.get(reverse('econotec:notificaciones_tecnico')).status_code, 302)


class AsesoraDeLaSalidaTests(BaseSalidaRetiro):
    """«¿A quién pertenece esta salida?»: la salida le cuenta a la asesora elegida."""

    def confirmar_como(self, usuario, salida, **datos):
        self.client.force_login(usuario)
        return self.client.post(reverse('econotec:salida_marcar_retirada', kwargs={'pk': salida.pk}), datos)

    def test_admin_elige_la_asesora_de_la_salida(self):
        salida = self.crear_salida()
        self.confirmar_como(self.admin, salida, asesora_salida=str(self.otra_asesora.pk))
        salida.refresh_from_db()
        self.assertEqual(salida.fecha_retiro_real, date.today())
        self.assertEqual(salida.retiro_confirmado_por, self.otra_asesora)

    def test_sin_elegir_asesora_el_admin_no_confirma(self):
        salida = self.crear_salida()
        self.confirmar_como(self.admin, salida)
        salida.refresh_from_db()
        self.assertIsNone(salida.fecha_retiro_real)

    def test_no_se_puede_elegir_a_un_tecnico(self):
        salida = self.crear_salida()
        self.confirmar_como(self.asesora, salida, asesora_salida=str(self.tecnico.pk))
        salida.refresh_from_db()
        self.assertIsNone(salida.fecha_retiro_real)

    def test_asesora_puede_dar_la_salida_a_otra_asesora(self):
        salida = self.crear_salida()
        self.confirmar_como(self.asesora, salida, asesora_salida=str(self.otra_asesora.pk))
        salida.refresh_from_db()
        self.assertEqual(salida.retiro_confirmado_por, self.otra_asesora)

    def test_pago_con_salida_pide_la_asesora(self):
        salida = self.crear_salida(valor=Decimal('50.00'))
        url = reverse('econotec:abono_crear', kwargs={'ingreso_pk': salida.ingreso.pk})
        datos = {
            'accion_abono': 'registrar_y_salida', 'fecha': date.today().isoformat(), 'monto': '50.00',
            'metodo': 'efectivo', 'factura_realizada': 'no', 'bodegaje_decision': 'na',
        }
        self.client.force_login(self.admin)
        formulario = self.client.get(url)
        self.assertContains(formulario, 'name="asesora_salida"')
        self.assertContains(formulario, '¿A quién pertenece esta salida?')

        # Sin asesora: no se guarda el pago ni la salida.
        self.client.post(url, datos)
        self.assertFalse(Abono.objects.filter(ingreso=salida.ingreso).exists())

        self.client.post(url, {**datos, 'asesora_salida': str(self.otra_asesora.pk)})
        salida.refresh_from_db()
        self.assertEqual(Abono.objects.filter(ingreso=salida.ingreso).count(), 1)
        self.assertEqual(salida.fecha_retiro_real, date.today())
        self.assertEqual(salida.retiro_confirmado_por, self.otra_asesora)

    def test_ventana_de_asesora_en_las_pantallas(self):
        self.crear_salida()
        self.client.force_login(self.admin)
        lista = self.client.get(reverse('econotec:salida_lista'))
        self.assertContains(lista, 'id="asesoras-salida-datos"')
        self.assertContains(lista, '¿A quién pertenece esta salida?')
        self.assertContains(lista, 'Kimberly')
        self.assertNotContains(lista, '"nombre": "Yandri"')

    def test_tecnico_no_ve_el_apartado_de_salidas(self):
        self.client.force_login(self.tecnico)
        respuesta = self.client.get(reverse('econotec:salida_retiros_lista'))
        self.assertRedirects(respuesta, reverse('econotec:salida_lista'), fetch_redirect_response=False)
        lista = self.client.get(reverse('econotec:salida_lista'))
        self.assertNotContains(lista, '<th>Salida de la oficina</th>')
        self.assertNotContains(lista, 'asesoras-salida-datos')

    def test_perfil_y_ranking_muestran_la_tabla_de_salidas(self):
        salida = self.crear_salida()
        self.confirmar_como(self.admin, salida, asesora_salida=str(self.asesora.pk))
        self.client.force_login(self.asesora)
        perfil = self.client.get(reverse('econotec:mi_perfil'))
        self.assertContains(perfil, 'class="retiros-tabla"')
        self.assertContains(perfil, salida.ingreso.codigo_equipo)
        self.assertContains(perfil, 'Técnico responsable')

        self.client.force_login(self.admin)
        ranking = self.client.get(reverse('econotec:ranking_asesoras_salidas'))
        self.assertContains(ranking, 'Detalle de todas las salidas de retiro')
        self.assertEqual([s.pk for s in ranking.context['detalle_salidas']], [salida.pk])


class ResumenSalidasDelDiaTests(BaseSalidaRetiro):
    """Apartado «Hoy / Ayer» de la lista de salidas físicas confirmadas."""

    def setUp(self):
        super().setUp()
        self.hoy = date.today()
        self.ayer = self.hoy - timedelta(days=1)
        self.salidas_hoy = []
        for _ in range(2):
            salida = self.crear_salida()
            SalidaEquipo.objects.filter(pk=salida.pk).update(
                fecha_retiro_real=self.hoy, estado_reparacion='retirado',
            )
            salida.refresh_from_db()
            self.salidas_hoy.append(salida)
        self.salida_ayer = self.crear_salida()
        SalidaEquipo.objects.filter(pk=self.salida_ayer.pk).update(
            fecha_retiro_real=self.ayer, estado_reparacion='retirado',
        )
        self.salida_ayer.refresh_from_db()
        # Una salida vieja que no debe contarse en ninguno de los dos días.
        salida_vieja = self.crear_salida()
        SalidaEquipo.objects.filter(pk=salida_vieja.pk).update(
            fecha_retiro_real=self.hoy - timedelta(days=5), estado_reparacion='retirado',
        )

    def _resumen(self, usuario):
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse('econotec:salida_retiros_lista'))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def test_asesora_y_admin_ven_los_totales_de_hoy_y_ayer(self):
        for usuario in (self.asesora, self.admin):
            respuesta = self._resumen(usuario)
            resumen = respuesta.context['resumen_salidas_dia']
            self.assertEqual(
                [(d['clave'], d['fecha'], d['total']) for d in resumen],
                [('hoy', self.hoy, 2), ('ayer', self.ayer, 1)],
            )
            self.assertContains(respuesta, 'class="exit-day-summary"')
            self.assertContains(respuesta, 'Ver detalle →', count=2)

    def test_el_total_del_dia_no_depende_de_los_filtros(self):
        self.client.force_login(self.asesora)
        respuesta = self.client.get(
            reverse('econotec:salida_retiros_lista'), {'sede': 'quito'},
        )
        self.assertEqual(respuesta.context['total'], 0)
        self.assertEqual(
            [d['total'] for d in respuesta.context['resumen_salidas_dia']], [2, 1],
        )

    def test_ver_detalle_filtra_la_tabla_por_ese_dia(self):
        self.client.force_login(self.asesora)
        resumen = self._resumen(self.asesora).context['resumen_salidas_dia']

        detalle_hoy = self.client.get(resumen[0]['url'])
        self.assertEqual(
            sorted(s.pk for s in detalle_hoy.context['salidas']),
            sorted(s.pk for s in self.salidas_hoy),
        )
        self.assertTrue(detalle_hoy.context['resumen_salidas_dia'][0]['activo'])
        self.assertFalse(detalle_hoy.context['resumen_salidas_dia'][1]['activo'])

        detalle_ayer = self.client.get(resumen[1]['url'])
        self.assertEqual(
            [s.pk for s in detalle_ayer.context['salidas']], [self.salida_ayer.pk],
        )
        self.assertTrue(detalle_ayer.context['resumen_salidas_dia'][1]['activo'])

    def test_el_tecnico_no_llega_al_apartado(self):
        self.client.force_login(self.tecnico)
        respuesta = self.client.get(reverse('econotec:salida_retiros_lista'))
        self.assertRedirects(respuesta, reverse('econotec:salida_lista'), fetch_redirect_response=False)
        lista_oficina = self.client.get(reverse('econotec:salida_lista'))
        self.assertIsNone(lista_oficina.context['resumen_salidas_dia'])
        self.assertNotContains(lista_oficina, 'class="exit-day-summary"')
