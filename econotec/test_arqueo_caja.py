"""Arqueo del efectivo: lo cobrado en efectivo según Pagos contra lo contado."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .arqueo import arqueos_por_dia, efectivo_del_dia
from .models import Abono, ArqueoCaja, CategoriaEgreso, Cliente, Egreso, IngresoEquipo, SalidaEquipo
from .permisos import GRUPO_ASISTENTE_CAJA


class ArqueoCajaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='jefe', email='jefe@example.com', password='x')
        self.caja = User.objects.create_user(username='karla', first_name='Karla')
        self.caja.groups.add(Group.objects.get_or_create(name=GRUPO_ASISTENTE_CAJA)[0])
        self.tecnico = User.objects.create_user(username='yandri')
        self.tecnico.groups.add(Group.objects.get_or_create(name='Tecnicos')[0])
        self.cliente = Cliente.objects.create(cedula='0912345678', nombres='Luis Mora')
        self.hoy = timezone.localdate()
        self.url = reverse('econotec:arqueo_caja')

    def ingreso(self, **datos):
        base = {
            'sede': 'guayaquil', 'asesor_comercial': 'K', 'fecha_ingreso': self.hoy, 'cliente': self.cliente,
            'tipo_equipo': 'laptop', 'marca': 'HP', 'modelo_serie': 'X', 'accesorios_entregados': '-',
            'problema_reportado': '-', 'valor_acordado': Decimal('100.00'), 'estado': 'ingresado',
        }
        base.update(datos)
        return IngresoEquipo.objects.create(**base)

    def escenario(self):
        """Guayaquil: $20 anticipo efectivo + $15 abono efectivo + $30 transferencia + mixto con $10 en efectivo."""
        uno = self.ingreso(abono_anticipo=Decimal('20.00'), anticipo_metodo='efectivo')
        Abono.objects.create(ingreso=uno, fecha=self.hoy, monto=Decimal('15.00'), metodo='efectivo')
        Abono.objects.create(ingreso=uno, fecha=self.hoy, monto=Decimal('30.00'), metodo='transferencia',
                             banco='pichincha')
        Abono.objects.create(ingreso=uno, fecha=self.hoy - timedelta(days=1), monto=Decimal('50.00'),
                             metodo='efectivo')
        dos = self.ingreso(fecha_ingreso=self.hoy - timedelta(days=3))
        SalidaEquipo.objects.create(
            ingreso=dos, fecha_salida=self.hoy, estado_reparacion='pendiente_retiro', tecnico_reparo=self.tecnico,
            valor_final_cobrado=Decimal('25.00'), metodo_pago_final='mixto',
            monto_1=Decimal('10.00'), metodo_1='efectivo', monto_2=Decimal('15.00'), metodo_2='tarjeta',
        )
        self.ingreso(sede='quito', abono_anticipo=Decimal('40.00'), anticipo_metodo='efectivo')
        return uno, dos

    def test_efectivo_del_dia_por_oficina(self):
        self.escenario()
        guayaquil = efectivo_del_dia(self.hoy, 'guayaquil')
        self.assertEqual(guayaquil['efectivo'], Decimal('45.00'))
        self.assertEqual(len(guayaquil['cobros_efectivo']), 3)
        self.assertEqual({m['clave']: m['monto'] for m in guayaquil['por_metodo']},
                         {'efectivo': Decimal('45.00'), 'transferencia': Decimal('30.00'),
                          'tarjeta': Decimal('15.00')})
        self.assertEqual(efectivo_del_dia(self.hoy, 'quito')['efectivo'], Decimal('40.00'))
        self.assertEqual(efectivo_del_dia(self.hoy - timedelta(days=1), 'guayaquil')['efectivo'], Decimal('50.00'))

    def test_guardar_arqueo_que_cuadra_y_que_falta(self):
        self.escenario()
        self.client.force_login(self.caja)
        respuesta = self.client.post(self.url, {'fecha': self.hoy.isoformat(), 'sede': 'guayaquil',
                                                'efectivo_contado': '45.00'}, follow=True)
        self.assertContains(respuesta, 'la caja cuadra')
        arqueo = ArqueoCaja.objects.get(fecha=self.hoy, sede='guayaquil')
        self.assertEqual((arqueo.efectivo_contado, arqueo.efectivo_sistema, arqueo.diferencia),
                         (Decimal('45.00'), Decimal('45.00'), Decimal('0.00')))
        self.assertEqual(arqueo.registrado_por, self.caja)

        respuesta = self.client.post(self.url, {'fecha': self.hoy.isoformat(), 'sede': 'guayaquil',
                                                'efectivo_contado': '$40,00', 'observacion': 'Cambio a cliente'},
                                     follow=True)
        self.assertContains(respuesta, 'faltan $5,00 en la caja')
        self.assertContains(respuesta, 'Faltan $5,00')
        self.assertEqual(ArqueoCaja.objects.count(), 1)
        arqueo.refresh_from_db()
        self.assertEqual((arqueo.efectivo_contado, arqueo.observacion), (Decimal('40.00'), 'Cambio a cliente'))

    def test_sobra_efectivo(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(self.url, {'fecha': self.hoy.isoformat(), 'sede': 'quito',
                                                'efectivo_contado': '3'}, follow=True)
        self.assertContains(respuesta, 'sobran $3,00 en la caja')

    def test_valores_invalidos_no_se_guardan(self):
        self.client.force_login(self.admin)
        for valor in ('', 'abc', '-5', 'NaN', 'Infinity', '999999999'):
            with self.subTest(valor=valor):
                respuesta = self.client.post(self.url, {'sede': 'guayaquil', 'efectivo_contado': valor})
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, 'Escribe el efectivo contado')
        self.assertFalse(ArqueoCaja.objects.exists())

    def test_aviso_si_el_sistema_cambio_despues(self):
        uno, _dos = self.escenario()
        self.client.force_login(self.admin)
        self.client.post(self.url, {'sede': 'guayaquil', 'efectivo_contado': '45'})
        Abono.objects.create(ingreso=uno, fecha=self.hoy, monto=Decimal('5.00'), metodo='efectivo')
        respuesta = self.client.get(self.url, {'sede': 'guayaquil'})
        self.assertContains(respuesta, 'El efectivo del sistema cambió desde el arqueo: ahora es $50,00')

    def test_fecha_futura_usa_hoy_y_dia_anterior_se_puede_ver(self):
        self.client.force_login(self.admin)
        manana = (self.hoy + timedelta(days=1)).isoformat()
        self.assertEqual(self.client.get(self.url, {'fecha': manana}).context['fecha'], self.hoy)
        ayer = self.hoy - timedelta(days=1)
        self.assertEqual(self.client.get(self.url, {'fecha': ayer.isoformat()}).context['fecha'], ayer)

    def test_acceso_solo_admin_y_asistente_de_caja(self):
        self.client.force_login(self.tecnico)
        self.assertRedirects(self.client.get(self.url), reverse('econotec:bienvenida'), fetch_redirect_response=False)
        self.client.force_login(self.caja)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        respuesta = self.client.get(reverse('econotec:seguimiento_pago'))
        self.assertContains(respuesta, reverse('econotec:arqueo_caja'))


class ArqueoEgresosTests(TestCase):
    """Los egresos en efectivo de la oficina se restan del efectivo esperado."""

    def setUp(self):
        self.hoy = timezone.localdate()
        self.categoria, _ = CategoriaEgreso.objects.get_or_create(nombre='Otros')
        cliente = Cliente.objects.create(cedula='0911111111', nombres='Ana Paz')
        IngresoEquipo.objects.create(
            sede='guayaquil', asesor_comercial='K', fecha_ingreso=self.hoy, cliente=cliente,
            tipo_equipo='laptop', marca='HP', modelo_serie='X', accesorios_entregados='-',
            problema_reportado='-', valor_acordado=Decimal('100.00'), estado='ingresado',
            abono_anticipo=Decimal('100.00'), anticipo_metodo='efectivo',
        )

    def egreso(self, monto, **datos):
        base = {'fecha': self.hoy, 'categoria': self.categoria, 'concepto': 'Gasto', 'monto': Decimal(monto),
                'sede': 'guayaquil', 'metodo': 'efectivo'}
        base.update(datos)
        return Egreso.objects.create(**base)

    def test_resta_egresos_en_efectivo_de_la_oficina_y_del_dia(self):
        self.egreso('15.00')
        self.egreso('20.00', metodo='mixto', monto_1=Decimal('5.00'), metodo_1='efectivo',
                    monto_2=Decimal('15.00'), metodo_2='transferencia')
        # No se restan: transferencia, otra oficina, General, sin oficina (viejos) y otro día.
        self.egreso('30.00', metodo='transferencia', banco='pichincha')
        self.egreso('40.00', sede='quito')
        self.egreso('50.00', sede='general')
        self.egreso('60.00', sede='')
        self.egreso('70.00', fecha=self.hoy - timedelta(days=1))

        sistema = efectivo_del_dia(self.hoy, 'guayaquil')
        self.assertEqual(sistema['cobrado'], Decimal('100.00'))
        self.assertEqual(sistema['egresos_total'], Decimal('20.00'))
        self.assertEqual(sistema['efectivo'], Decimal('80.00'))
        self.assertEqual(len(sistema['egresos']), 2)
        self.assertEqual(efectivo_del_dia(self.hoy, 'quito')['efectivo'], Decimal('-40.00'))

    def test_arqueo_guardado_cuadra_con_el_egreso_restado(self):
        self.egreso('15.00', concepto='Pasta térmica')
        admin = get_user_model().objects.create_superuser(username='jefe', email='jefe@example.com', password='x')
        self.client.force_login(admin)
        url = reverse('econotec:arqueo_caja')
        respuesta = self.client.get(url, {'fecha': self.hoy.isoformat(), 'sede': 'guayaquil'})
        self.assertContains(respuesta, 'Pasta térmica')
        self.client.post(url, {'fecha': self.hoy.isoformat(), 'sede': 'guayaquil', 'efectivo_contado': '85'})
        arqueo = ArqueoCaja.objects.get(fecha=self.hoy, sede='guayaquil')
        self.assertEqual(arqueo.efectivo_sistema, Decimal('85.00'))
        self.assertEqual(arqueo.diferencia, Decimal('0.00'))


class ArqueoEnRegistroAdministrativoTests(TestCase):
    """El Registro Administrativo muestra el arqueo de hoy con los mismos números que la página de Arqueo."""

    setUp = ArqueoCajaTests.setUp
    ingreso = ArqueoCajaTests.ingreso
    escenario = ArqueoCajaTests.escenario

    def dashboard(self, usuario=None):
        self.client.force_login(usuario or self.admin)
        return self.client.get(reverse('econotec:admin_dashboard'),
                               {'ano': self.hoy.year, 'mes': self.hoy.month})

    def test_mismos_numeros_que_la_pagina_de_arqueo(self):
        self.escenario()
        Egreso.objects.create(fecha=self.hoy, categoria=CategoriaEgreso.objects.get_or_create(nombre='Otros')[0],
                              concepto='Pasta', monto=Decimal('5.00'), sede='guayaquil', metodo='efectivo')
        respuesta = self.dashboard()
        oficinas = {o['sede']: o for o in respuesta.context['arqueos_hoy']}
        self.assertEqual(list(oficinas), ['guayaquil', 'quito'])
        pagina = self.client.get(self.url, {'fecha': self.hoy.isoformat(), 'sede': 'guayaquil'})
        for sede, esperado in (('guayaquil', Decimal('40.00')), ('quito', Decimal('40.00'))):
            with self.subTest(sede=sede):
                self.assertEqual(oficinas[sede]['sistema']['efectivo'], esperado)
                self.assertEqual(oficinas[sede]['sistema']['efectivo'], efectivo_del_dia(self.hoy, sede)['efectivo'])
        self.assertEqual(oficinas['guayaquil']['sistema']['cobrado'], Decimal('45.00'))
        self.assertEqual(oficinas['guayaquil']['sistema']['egresos_total'], Decimal('5.00'))
        self.assertEqual(pagina.context['sistema']['efectivo'], oficinas['guayaquil']['sistema']['efectivo'])
        self.assertContains(respuesta, 'Arqueo de caja de hoy')
        self.assertContains(respuesta, 'Contar la caja de Guayaquil')
        self.assertContains(respuesta, '$40,00')

    def test_muestra_el_arqueo_guardado_y_el_aviso_si_cambio(self):
        uno, _dos = self.escenario()
        self.client.force_login(self.caja)
        self.client.post(self.url, {'fecha': self.hoy.isoformat(), 'sede': 'guayaquil', 'efectivo_contado': '40'})
        respuesta = self.dashboard()
        self.assertContains(respuesta, 'Faltan $5,00')
        self.assertEqual([a.sede for a in respuesta.context['arqueos_mes']], ['guayaquil'])
        self.assertNotContains(respuesta, 'Hay que volver a contar')

        Abono.objects.create(ingreso=uno, fecha=self.hoy, monto=Decimal('5.00'), metodo='efectivo')
        respuesta = self.dashboard()
        guayaquil = respuesta.context['arqueos_hoy'][0]
        self.assertTrue(guayaquil['sistema_cambio'])
        self.assertEqual(guayaquil['sistema']['efectivo'], Decimal('50.00'))
        self.assertContains(respuesta, 'Hay que volver a contar')

    def test_secciones_en_orden_y_arqueo_junto_a_la_caja_fuerte(self):
        html = self.dashboard().content.decode()
        orden = ['id="seccion-dinero"', 'id="seccion-caja"', 'id="arqueo-admin"', 'id="historico-mensual"',
                 'id="seccion-equipos"', 'id="seccion-tecnicos"', 'id="resumen-tecnicos"', 'id="ranking-admin"',
                 'id="ingresos-tecnicos"', 'id="salidas-fisicas-admin"', 'id="seccion-personal"',
                 'id="seccion-mantenimiento"']
        posiciones = [html.index(marca) for marca in orden]
        self.assertEqual(posiciones, sorted(posiciones))

    def test_admin_que_tambien_es_tecnico_ve_el_arqueo_pero_no_la_caja_fuerte(self):
        self.admin.groups.add(Group.objects.get_or_create(name='Tecnicos')[0])
        respuesta = self.dashboard()
        self.assertContains(respuesta, 'id="arqueo-admin"')
        self.assertNotContains(respuesta, 'id="historico-mensual"')


class ArqueoEnMiniCajaTests(TestCase):
    """La Mini caja de la Caja fuerte muestra el arqueo guardado del día, solo en efectivo y por oficina."""

    setUp = ArqueoCajaTests.setUp
    ingreso = ArqueoCajaTests.ingreso
    escenario = ArqueoCajaTests.escenario

    def caja_fuerte(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('econotec:admin_caja_abrir'), {'password': 'x'})
        respuesta = self.client.get(reverse('econotec:admin_dashboard'), {'ano': self.hoy.year, 'mes': self.hoy.month})
        self.assertTrue(respuesta.context['caja_abierta'])
        return respuesta

    def test_arqueos_por_dia_en_centavos_y_solo_las_oficinas_que_contaron(self):
        self.escenario()
        self.client.force_login(self.caja)
        self.client.post(self.url, {'fecha': self.hoy.isoformat(), 'sede': 'guayaquil', 'efectivo_contado': '40'})
        ayer = self.hoy - timedelta(days=1)
        self.client.post(self.url, {'fecha': ayer.isoformat(), 'sede': 'quito', 'efectivo_contado': '2'})
        self.assertEqual(arqueos_por_dia(), {
            ayer.isoformat(): {'quito': {'contado': 200, 'sistema': 0, 'diferencia': 200}},
            self.hoy.isoformat(): {'guayaquil': {'contado': 4000, 'sistema': 4500, 'diferencia': -500}},
        })

    def test_caja_fuerte_abierta_lleva_los_arqueos_sin_cambiar_sus_totales(self):
        self.escenario()
        antes = self.caja_fuerte().context['caja_fuerte_datos']
        self.assertEqual(antes['arqueos'], {})
        self.client.post(self.url, {'fecha': self.hoy.isoformat(), 'sede': 'guayaquil', 'efectivo_contado': '40'})
        respuesta = self.caja_fuerte()
        datos = respuesta.context['caja_fuerte_datos']
        self.assertEqual(datos['arqueos'], {self.hoy.isoformat(): {
            'guayaquil': {'contado': 4000, 'sistema': 4500, 'diferencia': -500}}})
        # El arqueo no toca lo que entró ni los egresos de la Caja fuerte.
        self.assertEqual((datos['dias'], datos['egresos']), (antes['dias'], antes['egresos']))
        self.assertContains(respuesta, 'Arqueo guardado · solo efectivo')
        self.assertContains(respuesta, 'data-bf-arqueo="guayaquil"')
        self.assertContains(respuesta, 'data-bf-arqueo="quito"')

    def test_caja_fuerte_cerrada_no_muestra_el_arqueo(self):
        self.escenario()
        self.client.force_login(self.caja)
        self.client.post(self.url, {'fecha': self.hoy.isoformat(), 'sede': 'guayaquil', 'efectivo_contado': '40'})
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('econotec:admin_dashboard'))
        self.assertFalse(respuesta.context['caja_abierta'])
        self.assertNotContains(respuesta, 'data-bf-arqueo=')
        self.assertNotIn('caja_fuerte_datos', respuesta.context)


class DetalleCobrosHoyTests(TestCase):
    """Detalle de las tarjetas de Pagos, franja «Hoy» de Seguimiento y Arqueo «Todas».

    Hereda el escenario de hoy: Guayaquil $20 anticipo efectivo, $15 abono
    efectivo, $30 transferencia y un mixto de $25 ($10 efectivo + $15 tarjeta);
    Quito $40 anticipo efectivo. Total de hoy $130: efectivo $85, transferencia
    $30 y tarjeta $15.
    """
    # Mismos datos que ArqueoCajaTests, sin volver a correr sus pruebas.
    setUp = ArqueoCajaTests.setUp
    ingreso = ArqueoCajaTests.ingreso
    escenario = ArqueoCajaTests.escenario

    def test_tarjeta_hoy_de_pagos_trae_el_detalle_que_suma_lo_mismo(self):
        uno, _dos = self.escenario()
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse('econotec:pagos_lista'))

        hoy, ayer, mes = respuesta.context['resumen_pagos_dia']
        self.assertEqual((hoy['total'], hoy['pagos']), (Decimal('130.00'), 5))
        self.assertEqual(sum((p['monto'] for p in hoy['detalle']), Decimal('0')), hoy['total'])
        self.assertEqual(len(hoy['detalle']), hoy['pagos'])
        self.assertEqual(
            (hoy['metodos']['efectivo'], hoy['metodos']['transferencia'], hoy['metodos']['tarjeta']),
            (Decimal('85.00'), Decimal('30.00'), Decimal('15.00')),
        )
        self.assertEqual({p['oficina'] for p in hoy['detalle']}, {'Guayaquil', 'Quito'})
        # Ayer: el abono de $50 en efectivo.
        self.assertEqual((ayer['total'], len(ayer['detalle'])), (Decimal('50.00'), 1))
        self.assertEqual(sum((p['monto'] for p in mes['detalle']), Decimal('0')), mes['total'])
        self.assertContains(respuesta, 'id="pay-detalle-hoy"')
        self.assertContains(respuesta, reverse('econotec:ingreso_abonos', kwargs={'pk': uno.pk}))

    def test_asesora_ve_el_detalle_sin_montos(self):
        self.escenario()
        asesora = get_user_model().objects.create_user(username='ana')
        asesora.groups.add(Group.objects.get_or_create(name='Asesores')[0])
        self.client.force_login(asesora)

        respuesta = self.client.get(reverse('econotec:pagos_lista'))

        self.assertContains(respuesta, 'id="pay-detalle-hoy"')
        self.assertNotContains(respuesta, '$130,00')
        self.assertNotContains(respuesta, 'Efectivo <b>')

    def test_seguimiento_franja_hoy_por_forma_de_pago_y_oficina(self):
        self.escenario()
        self.client.force_login(self.caja)
        url = reverse('econotec:seguimiento_pago')

        todas = self.client.get(url).context['hoy_metodos']
        quito = self.client.get(url, {'sede': 'quito'}).context['hoy_metodos']

        self.assertEqual(
            (todas['total'], todas['efectivo'], todas['transferencia'], todas['tarjeta'], todas['pagos']),
            (Decimal('130.00'), Decimal('85.00'), Decimal('30.00'), Decimal('15.00'), 5),
        )
        self.assertEqual((quito['total'], quito['efectivo'], quito['pagos']), (Decimal('40.00'), Decimal('40.00'), 1))
        self.assertContains(self.client.get(url), 'Ingresos de hoy')

    def test_arqueo_todas_suma_las_dos_oficinas_y_no_guarda(self):
        self.escenario()
        self.client.force_login(self.caja)
        self.client.post(self.url, {'sede': 'guayaquil', 'efectivo_contado': '45'})

        respuesta = self.client.get(self.url, {'sede': 'todas'})

        self.assertTrue(respuesta.context['es_todas'])
        self.assertEqual(respuesta.context['sistema']['efectivo'], Decimal('85.00'))
        self.assertEqual(len(respuesta.context['sistema']['cobros_efectivo']), 4)
        self.assertContains(respuesta, 'Arqueo de cada oficina')
        self.assertContains(respuesta, '✓ Cuadra')
        self.assertContains(respuesta, 'Sin arqueo ese día.')
        self.assertNotContains(respuesta, 'Guardar arqueo')

        guardar = self.client.post(self.url, {'sede': 'todas', 'efectivo_contado': '85'})
        self.assertEqual(guardar.status_code, 302)
        self.assertFalse(ArqueoCaja.objects.filter(sede='todas').exists())
        self.assertEqual(ArqueoCaja.objects.count(), 1)
