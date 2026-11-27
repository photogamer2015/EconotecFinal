"""Arqueo del efectivo: lo cobrado en efectivo según Pagos contra lo contado."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .arqueo import efectivo_del_dia
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
