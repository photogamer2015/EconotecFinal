"""El dinero de compras de equipo y de ventas de reacondicionados, de punta a punta.

- Comprar un equipo es un egreso: resta en la Caja, en el Registro
  Administrativo y en el saldo de la semana de Seguimiento de pago, y nunca
  cuenta como dinero que entró ni como saldo pendiente de un cliente.
- Vender un equipo reacondicionado suma igual que una venta de producto.
- Chatarrizar o reacondicionar una compra no mueve dinero.
"""
import json
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .caja import caja_del_periodo, movimientos_de_dinero
from .models import Cliente, Egreso, IngresoEquipo, InventarioItem
from .seguimiento_pago import TOTAL, hoja_semana, ingresos_de_seguimiento, inicio_semana, saldo_semana
from .views import _sincronizar_egreso_compra
from .views_admin import _egresos_mes, _ingresos_dinero_mes

HOY = date.today()


class DineroComprasYReacondicionadosTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='RootAdmin', email='a@example.com', password='x')
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri')
        self.tecnico.groups.add(Group.objects.create(name='Tecnicos'))
        asesora = User.objects.create_user(username='Kimberly')
        asesora.groups.add(Group.objects.create(name='Asesores Comerciales'))
        self.cliente = Cliente.objects.create(cedula='0912345678', nombres='Osmar Perez')
        self.client.force_login(self.admin)

    def comprar(self, valor='30.00'):
        compra = IngresoEquipo.objects.create(
            sede='guayaquil', fecha_ingreso=HOY, cliente=self.cliente, tipo_equipo='laptop',
            marca='Lenovo', modelo_serie='ThinkPad', problema_reportado='Compra',
            registrado_por=self.admin, estado='equipo_a_comprar',
            valor_acordado=Decimal(valor), compra_metodo_pago='efectivo',
        )
        _sincronizar_egreso_compra(compra, self.admin)
        return compra

    def vender_reacondicionado(self, valor='80.00'):
        equipo = InventarioItem.objects.create(
            linea='reacondicionado', sede='guayaquil', categoria='computadora', tipo='laptops',
            producto='Laptop reacondicionada', marca='Lenovo', modelo='ThinkPad',
            ubicacion='guayaquil_norte', cantidad=1, costo=Decimal(valor),
        )
        respuesta = self.client.post(reverse('econotec:venta_registrar_reacondicionado'), {
            'venta_aplica_cliente': 'no',
            'ing-fecha_ingreso': HOY.isoformat(),
            'ing-tecnico_encargado': str(self.tecnico.pk),
            'ing-asesor_comercial': 'Kimberly',
            'ing-tipo_equipo': 'otro', 'ing-tipo_equipo_otro': 'Venta',
            'ing-marca': 'N/A', 'ing-modelo_serie': 'N/A',
            'ing-accesorios_entregados': 'Ninguno',
            'ing-problema_reportado': 'Venta de mostrador',
            'ing-valor_acordado': valor,
            'ing-diagnostico_inmediato': 'no',
            'ing-estado': 'entregado', 'ing-subestado_entregado': 'con_solucion',
            'ing-firma_cliente_opcion': 'no',
            'venta_tipo_pago': 'completo', 'venta_metodo_pago': 'efectivo',
            'inventario_seleccionado': json.dumps([{'item_id': equipo.pk, 'cantidad': 1, 'observacion': ''}]),
        })
        self.assertEqual(respuesta.status_code, 302, respuesta.context and respuesta.context['ing_form'].errors)
        return IngresoEquipo.objects.get(sede='ventas')

    def caja(self):
        return caja_del_periodo(HOY.replace(day=1).isoformat(), HOY.isoformat(), hoy=HOY)

    def test_comprar_un_equipo_resta_en_todos_los_registros(self):
        compra = self.comprar('30.00')

        egreso = Egreso.objects.get(ingreso_compra=compra)
        self.assertEqual(egreso.monto, Decimal('30.00'))
        self.assertEqual(egreso.categoria.nombre, 'Compra de equipo')

        # Caja del Ranking: no entró nada y salieron $30.
        caja = self.caja()
        self.assertEqual(caja['entro'], Decimal('0.00'))
        self.assertEqual(caja['egresos'], Decimal('30.00'))
        self.assertEqual(caja['saldo_final'], Decimal('-30.00'))

        # Registro Administrativo del mes.
        self.assertEqual(_egresos_mes(HOY.year, HOY.month), Decimal('30.00'))
        self.assertEqual(_ingresos_dinero_mes(HOY.year, HOY.month)['total'], Decimal('0.00'))

        # Seguimiento de pago: resta del saldo de la semana y no es un cobro pendiente.
        saldo = saldo_semana(HOY)
        self.assertEqual(saldo['total_egresos'], Decimal('30.00'))
        self.assertEqual(saldo['disponible'], Decimal('-30.00'))
        self.assertFalse(ingresos_de_seguimiento('', TOTAL).filter(pk=compra.pk).exists())
        self.assertFalse([m for m in movimientos_de_dinero() if m['ingreso_id'] == compra.pk])

        # Se ve en la lista de egresos y en el panel administrativo.
        self.assertContains(self.client.get(reverse('econotec:admin_egresos_lista')), compra.codigo_equipo)
        self.assertEqual(self.client.get(reverse('econotec:admin_dashboard')).status_code, 200)

    def test_vender_reacondicionado_suma_en_todos_los_registros(self):
        venta = self.vender_reacondicionado('80.00')

        movimientos = [m for m in movimientos_de_dinero() if m['ingreso_id'] == venta.pk]
        self.assertEqual(sum(m['monto'] for m in movimientos), Decimal('80.00'))
        self.assertTrue(all(m['origen'] == 'venta' for m in movimientos))

        caja = self.caja()
        self.assertEqual(caja['ventas'], Decimal('80.00'))
        self.assertEqual(caja['entro'], Decimal('80.00'))
        self.assertEqual(caja['egresos'], Decimal('0.00'))

        ingresos_mes = _ingresos_dinero_mes(HOY.year, HOY.month)
        self.assertEqual(ingresos_mes['cobros_ventas'], Decimal('80.00'))
        self.assertEqual(ingresos_mes['total'], Decimal('80.00'))

        self.assertEqual(hoja_semana(inicio_semana(HOY), tipo=TOTAL)['total'], Decimal('80.00'))
        self.assertEqual(saldo_semana(HOY)['disponible'], Decimal('80.00'))
        self.assertEqual(venta.diferencia, Decimal('0.00'))

    def test_comprar_en_30_y_vender_en_80_deja_50(self):
        compra = self.comprar('30.00')
        # Reacondicionar la compra no mueve dinero.
        self.client.post(reverse('econotec:equipo_reacondicionar', kwargs={'pk': compra.pk}), {
            'sede': 'guayaquil', 'ubicacion': 'guayaquil_norte',
            'tipo_inventario': 'computadora|laptops', 'marca': 'Lenovo', 'modelo': 'ThinkPad',
        })
        self.assertEqual(self.caja()['saldo_final'], Decimal('-30.00'))

        self.vender_reacondicionado('80.00')
        caja = self.caja()
        self.assertEqual((caja['entro'], caja['egresos']), (Decimal('80.00'), Decimal('30.00')))
        self.assertEqual(caja['saldo_final'], Decimal('50.00'))
        self.assertEqual(saldo_semana(HOY)['disponible'], Decimal('50.00'))
        self.assertEqual(
            _ingresos_dinero_mes(HOY.year, HOY.month)['total'] - _egresos_mes(HOY.year, HOY.month),
            Decimal('50.00'),
        )

    def test_chatarrizar_una_compra_no_mueve_dinero(self):
        compra = self.comprar('30.00')
        self.client.post(reverse('econotec:equipo_administrativo_chatarrizar', kwargs={'pk': compra.pk}))
        self.assertEqual(Egreso.objects.get(ingreso_compra=compra).monto, Decimal('30.00'))
        self.assertEqual(self.caja()['saldo_final'], Decimal('-30.00'))

    def test_el_egreso_sigue_al_valor_de_la_compra(self):
        compra = self.comprar('30.00')
        compra.valor_acordado = Decimal('45.00')
        compra.save()
        _sincronizar_egreso_compra(compra, self.admin)
        self.assertEqual(Egreso.objects.get(ingreso_compra=compra).monto, Decimal('45.00'))
        self.assertEqual(Egreso.objects.count(), 1)
        self.assertEqual(self.caja()['egresos'], Decimal('45.00'))

    def test_si_deja_de_ser_compra_el_egreso_ya_no_resta(self):
        compra = self.comprar('30.00')
        compra.estado = 'donado'
        compra.valor_acordado = Decimal('0.00')
        compra.save()
        _sincronizar_egreso_compra(compra, self.admin)
        self.assertFalse(Egreso.objects.filter(ingreso_compra=compra).exists())
        self.assertEqual(self.caja()['egresos'], Decimal('0.00'))
