"""Pruebas del Seguimiento de pago (hoja semanal de pagos de equipos y ventas de producto)."""
import re
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import (
    Abono, CategoriaEgreso, Cliente, Egreso, IngresoEquipo, InventarioItem, NotificacionCambioAdmin,
    SalidaEquipo, VentaInventarioItem,
)
from .seguimiento_pago import (
    etiqueta_semana, hoja_semana, ingresos_de_seguimiento, inicio_semana,
    saldo_semana, titulo_semana, totales_por_semana,
)

# Semana de referencia: lunes 12 a domingo 18 de octubre de 2026.
LUNES = date(2026, 10, 12)
MIERCOLES = date(2026, 10, 14)
DOMINGO = date(2026, 10, 18)


class SemanaTests(SimpleTestCase):
    def test_inicio_semana_es_el_lunes(self):
        for dia in range(12, 19):
            with self.subTest(dia=dia):
                self.assertEqual(inicio_semana(date(2026, 10, dia)), LUNES)
        self.assertEqual(inicio_semana(date(2026, 10, 19)), date(2026, 10, 19))
        self.assertEqual(inicio_semana(date(2026, 10, 11)), date(2026, 10, 5))

    def test_etiquetas_cruzan_mes_y_anio(self):
        self.assertEqual(etiqueta_semana(LUNES), '12 – 18 oct')
        self.assertEqual(etiqueta_semana(date(2026, 9, 28)), '28 sep – 4 oct')
        self.assertEqual(etiqueta_semana(date(2026, 12, 28)), '28 dic 2026 – 3 ene 2027')
        self.assertEqual(titulo_semana(LUNES), 'del lunes 12 al domingo 18 de octubre de 2026')
        self.assertEqual(
            titulo_semana(date(2026, 9, 28)),
            'del lunes 28 de septiembre al domingo 4 de octubre de 2026',
        )


class SeguimientoPagoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username='RootAdmin', email='admin@example.com', password='adminpass123',
            first_name='Rosa', last_name='Admin',
        )
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri', last_name='Guevara')
        self.tecnico.groups.add(Group.objects.create(name='Tecnicos'))
        self.tecnico_2 = User.objects.create_user(username='osmar', first_name='Osmar', last_name='Perez')
        self.tecnico_2.groups.add(Group.objects.get(name='Tecnicos'))
        self.asesora = User.objects.create_user(username='kimberly', first_name='Kimberly')
        self.asesora.groups.add(Group.objects.create(name='Asesores'))
        self.cliente = Cliente.objects.create(cedula='0912345678', nombres='María Loor', whatsapp='0990000000')
        self.cliente_2 = Cliente.objects.create(cedula='1712345678', nombres='Lucía Paredes')
        self.client.force_login(self.admin)

    def crear_ingreso(self, **overrides):
        datos = {
            'sede': 'guayaquil',
            'fecha_ingreso': LUNES,
            'cliente': self.cliente,
            'tipo_equipo': 'laptop',
            'marca': 'HP',
            'modelo_serie': 'Pavilion',
            'problema_reportado': 'No enciende',
            'valor_acordado': Decimal('85.00'),
            'tecnico_encargado': self.tecnico,
            'registrado_por': self.asesora,
            'estado': 'en_reparacion',
            'subestado_reparacion': 'en_reparacion',
        }
        datos.update(overrides)
        return IngresoEquipo.objects.create(**datos)

    def abonar(self, ingreso, fecha, monto, metodo='efectivo', **extra):
        return Abono.objects.create(
            ingreso=ingreso, fecha=fecha, monto=Decimal(monto), metodo=metodo,
            registrado_por=extra.pop('registrado_por', self.asesora), **extra,
        )

    def crear_venta(self, productos=(), **overrides):
        datos = {
            'sede': 'ventas', 'tipo_equipo': 'otro', 'marca': 'N/A', 'modelo_serie': 'N/A',
            'problema_reportado': '', 'estado': 'entregado', 'subestado_reparacion': '',
            'subestado_entregado': 'con_solucion',
        }
        datos.update(overrides)
        venta = self.crear_ingreso(**datos)
        for producto, cantidad, *bodega in productos:
            self.vender(venta, producto, cantidad, *bodega)
        return venta

    def vender(self, venta, producto, cantidad, sede='guayaquil'):
        """Producto de la bodega de `sede` dentro de la venta."""
        item = InventarioItem.objects.create(
            sede=sede, categoria='Accesorios', tipo='Varios', producto=producto, marca='Genérica',
            modelo='X', ubicacion='quito' if sede == 'quito' else 'guayaquil_norte', cantidad=10,
        )
        VentaInventarioItem.objects.create(venta=venta, inventario_item=item, cantidad=cantidad)

    def abrir(self, **params):
        with patch('econotec.views_pagos.timezone.localdate', return_value=MIERCOLES):
            return self.client.get(reverse('econotec:seguimiento_pago'), params)

    def ver(self, **params):
        """Vista de equipos, la que prueban las pruebas de equipos."""
        params.setdefault('tipo', 'equipo')
        return self.abrir(**params)

    def crear_semana_completa(self):
        """Pagos de varios tipos dentro de la semana, y otros que no cuentan."""
        # Diagnóstico inmediato en efectivo + anticipo mixto (transferencia + efectivo).
        self.laptop = self.crear_ingreso(
            diagnostico_inmediato='si', valor_diagnostico=Decimal('10.00'), diagnostico_metodo='efectivo',
            abono_anticipo=Decimal('40.00'), anticipo_metodo='mixto',
            anticipo_monto_1=Decimal('25.00'), anticipo_metodo_1='transferencia', anticipo_banco_1='pichincha',
            anticipo_monto_2=Decimal('15.00'), anticipo_metodo_2='efectivo',
        )
        # Equipo de la semana pasada con dos abonos esta semana.
        self.impresora = self.crear_ingreso(
            fecha_ingreso=date(2026, 10, 7), tipo_equipo='impresora', marca='Epson',
            modelo_serie='L3250', valor_acordado=Decimal('60.00'), tecnico_encargado=self.tecnico_2,
        )
        self.abonar(self.impresora, date(2026, 10, 13), '20.00', 'tarjeta', tarjeta_app='payphone')
        self.abonar(self.impresora, DOMINGO, '15.00', 'transferencia', banco='guayaquil',
                    registrado_por=self.admin)
        # Equipo de Quito pagado completo al finalizar.
        self.consola = self.crear_ingreso(
            sede='quito', fecha_ingreso=date(2026, 10, 1), cliente=self.cliente_2,
            tipo_equipo='consola', marca='Sony', modelo_serie='PS5', valor_acordado=Decimal('120.00'),
        )
        SalidaEquipo.objects.create(
            ingreso=self.consola, fecha_salida=MIERCOLES, estado_reparacion='pendiente_retiro',
            tecnico_reparo=self.tecnico_2, valor_final_cobrado=Decimal('120.00'),
            metodo_pago_final='transferencia', banco='produbanco', registrado_por=self.admin,
        )

        # No cuentan: pagos fuera de la semana, ventas y equipos administrativos.
        self.abonar(self.impresora, date(2026, 10, 11), '5.00')
        self.abonar(self.impresora, date(2026, 10, 19), '7.00')
        self.crear_ingreso(
            sede='ventas', tipo_equipo='otro', marca='N/A', modelo_serie='Tinta',
            valor_acordado=Decimal('12.00'), abono_anticipo=Decimal('12.00'),
            estado='entregado', subestado_entregado='con_solucion',
        )
        compra = self.crear_ingreso(estado='equipo_a_comprar', subestado_reparacion='', valor_acordado=Decimal('50.00'))
        self.abonar(compra, MIERCOLES, '50.00')

    # ── Acceso y menú ───────────────────────────────────────────

    def test_solo_admin_puede_entrar(self):
        for usuario in (self.tecnico, self.asesora):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)
                response = self.ver()
                self.assertRedirects(response, reverse('econotec:bienvenida'), fetch_redirect_response=False)

        self.client.force_login(self.admin)
        response = self.ver()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'pagos/seguimiento.html')

    def test_menu_muestra_la_tarjeta_solo_al_admin(self):
        url = reverse('econotec:seguimiento_pago')
        response = self.client.get(reverse('econotec:bienvenida'))
        self.assertContains(response, f'href="{url}"')
        self.assertContains(response, 'Seguimiento de pago')

        self.client.force_login(self.tecnico)
        response = self.client.get(reverse('econotec:bienvenida'))
        self.assertNotContains(response, f'href="{url}"')

    # ── Totales y filas ─────────────────────────────────────────

    def test_totales_por_metodo_y_saldo_pendiente(self):
        self.crear_semana_completa()

        response = self.ver()

        ctx = response.context
        self.assertEqual(ctx['lunes'], LUNES)
        self.assertEqual(ctx['domingo'], DOMINGO)
        self.assertTrue(ctx['es_semana_actual'])
        self.assertEqual(ctx['total'], Decimal('205.00'))
        self.assertEqual(ctx['cantidad'], 3)
        self.assertEqual(ctx['pagos'], 5)
        metodos = {m['clave']: m['monto'] for m in ctx['metodos']}
        self.assertEqual(metodos, {
            'transferencia': Decimal('160.00'),
            'efectivo': Decimal('25.00'),
            'tarjeta': Decimal('20.00'),
        })
        tarjeta = next(m for m in ctx['metodos'] if m['clave'] == 'tarjeta')
        self.assertEqual(tarjeta['detalle'], [('Payphone', Decimal('20.00'))])
        # Saldo: laptop 85 - 40 = 45; impresora 60 - (20 + 15 + 5 + 7) = 13; consola 0.
        self.assertEqual(ctx['saldo_total'], Decimal('58.00'))
        saldos = {f['codigo']: (f['saldo_estado'], f['saldo']) for f in ctx['filas']}
        self.assertEqual(saldos[self.laptop.codigo_equipo], ('debe', Decimal('45.00')))
        self.assertEqual(saldos[self.impresora.codigo_equipo], ('debe', Decimal('13.00')))
        self.assertEqual(saldos[self.consola.codigo_equipo], ('pagado', Decimal('0.00')))

        self.assertContains(response, '$205,00')
        self.assertContains(response, '$160,00')
        self.assertContains(response, 'Tarjeta de crédito / Payphone')
        self.assertContains(response, 'Transferencia · Banco Pichincha ($25,00) + Efectivo ($15,00)')
        self.assertContains(response, 'Tarjeta · Payphone')
        self.assertNotContains(response, 'Tinta')

    def test_fila_por_equipo_en_orden_de_pago(self):
        self.crear_semana_completa()

        filas = self.ver().context['filas']

        self.assertEqual(
            [f['codigo'] for f in filas],
            [self.laptop.codigo_equipo, self.impresora.codigo_equipo, self.consola.codigo_equipo],
        )
        self.assertEqual([f['numero'] for f in filas], [1, 2, 3])
        laptop, impresora, consola = filas
        self.assertEqual([c['concepto'] for c in laptop['cobros']], ['Diagnóstico', 'Anticipo'])
        self.assertEqual([c['concepto'] for c in impresora['cobros']], ['Abono', 'Abono'])
        self.assertEqual(impresora['monto'], Decimal('35.00'))
        self.assertEqual(consola['cobros'][0]['concepto'], 'Pago al finalizar')
        self.assertTrue(consola['cobros'][0]['recibo'].startswith('RECS-'))

    def test_columnas_de_ingreso_registro_y_tecnico_responsable(self):
        self.crear_semana_completa()

        response = self.ver()

        html = response.content.decode()
        thead = html[html.index('<thead>'):html.index('</thead>')]
        encabezados = re.findall(r'<th[^>]*>([^<]+)</th>', thead)
        self.assertIn('Fecha de ingreso', encabezados)
        self.assertIn('Registrado por', encabezados)
        self.assertIn('Saldo pendiente', encabezados)
        # El técnico responsable se ve al final.
        self.assertEqual(encabezados[-1], 'Técnico responsable')
        self.assertContains(response, '07/10/2026')
        self.assertContains(response, 'Kimberly')

        consola = next(f for f in response.context['filas'] if f['codigo'] == self.consola.codigo_equipo)
        self.assertEqual(consola['tecnicos'], [
            {'nombre': 'Osmar Perez', 'rol': 'Reparó'},
            {'nombre': 'Yandri Guevara', 'rol': 'Asignado'},
        ])
        laptop = next(f for f in response.context['filas'] if f['codigo'] == self.laptop.codigo_equipo)
        self.assertEqual(laptop['tecnicos'], [{'nombre': 'Yandri Guevara', 'rol': 'Asignado'}])
        self.assertEqual(laptop['registra'], 'Kimberly')
        self.assertEqual(laptop['fecha_ingreso'], LUNES)

    def test_sin_valor_acordado_no_suma_saldo(self):
        self.crear_ingreso(valor_acordado=None, abono_anticipo=Decimal('5.00'), estado='ingresado', subestado_reparacion='')

        response = self.ver()

        fila = response.context['filas'][0]
        self.assertEqual(fila['saldo_estado'], 'sin_valor')
        self.assertEqual(response.context['saldo_total'], Decimal('0.00'))
        self.assertContains(response, 'Sin valor acordado')

    def test_sin_ranking(self):
        self.crear_semana_completa()

        response = self.ver()

        self.assertNotIn('ranking', response.context)
        # La palabra «Ranking» aparece en la barra lateral de apartados; lo
        # que no debe tener esta página es la sección del ranking embebida.
        self.assertNotContains(response, 'id="salidas-tecnicos"')

    def test_pago_mixto_incompleto_va_a_otros(self):
        self.crear_ingreso(
            abono_anticipo=Decimal('30.00'), anticipo_metodo='mixto',
            anticipo_monto_1=Decimal('10.00'), anticipo_metodo_1='efectivo',
        )

        ctx = self.ver().context

        metodos = {m['clave']: m['monto'] for m in ctx['metodos']}
        self.assertEqual(metodos['otros'], Decimal('30.00'))
        self.assertEqual(metodos['efectivo'], Decimal('0.00'))
        self.assertEqual(sum(metodos.values()), ctx['total'])

    def test_semana_sin_pagos(self):
        response = self.ver()

        self.assertEqual(response.context['filas'], [])
        self.assertEqual(response.context['total'], Decimal('0.00'))
        self.assertContains(response, 'Todavía no hay pagos registrados esta semana.')
        self.assertEqual([m['clave'] for m in response.context['metodos']], ['transferencia', 'efectivo', 'tarjeta'])

    # ── Hojas por semana ────────────────────────────────────────

    def test_cualquier_dia_abre_la_hoja_de_su_semana(self):
        self.crear_semana_completa()

        response = self.ver(semana='2026-10-07')

        self.assertEqual(response.context['lunes'], date(2026, 10, 5))
        self.assertFalse(response.context['es_semana_actual'])
        # Solo el abono del domingo 11.
        self.assertEqual(response.context['total'], Decimal('5.00'))
        self.assertContains(response, 'Cerrada')

    def test_fecha_invalida_abre_la_semana_actual(self):
        for valor in ('basura', '', '2026-13-40', '9999-12-31x'):
            with self.subTest(valor=valor):
                response = self.ver(semana=valor)
                self.assertEqual(response.context['lunes'], LUNES)
                self.assertTrue(response.context['es_semana_actual'])

    def test_pago_con_fecha_adelantada_queda_en_su_semana_proxima(self):
        self.crear_semana_completa()

        response = self.ver(semana='2026-10-21')

        self.assertEqual(response.context['lunes'], date(2026, 10, 19))
        self.assertTrue(response.context['es_semana_futura'])
        self.assertEqual(response.context['total'], Decimal('7.00'))
        self.assertContains(response, 'Próxima')

    def test_ultima_semana_del_calendario_no_falla(self):
        response = self.ver(semana='9999-12-31')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['filas'], [])

    def test_pestanas_con_total_de_cada_semana(self):
        self.crear_semana_completa()

        pestanas = self.ver().context['pestanas']

        self.assertEqual(
            [(p['lunes'], p['total'], p['activa'], p['actual'], p['futura']) for p in pestanas],
            [
                (date(2026, 10, 19), Decimal('7.00'), False, False, True),
                (LUNES, Decimal('205.00'), True, True, False),
                (date(2026, 10, 5), Decimal('5.00'), False, False, False),
            ],
        )
        self.assertEqual(pestanas[1]['etiqueta'], '12 – 18 oct')

    def test_total_de_cada_pestana_es_el_de_su_hoja(self):
        self.crear_semana_completa()
        self.abonar(self.laptop, date(2026, 9, 30), '3.50', 'transferencia', banco='otro', banco_otro='Coop. JEP')

        totales = totales_por_semana()

        for lunes, datos in totales.items():
            with self.subTest(lunes=lunes):
                hoja = hoja_semana(lunes)
                self.assertEqual(hoja['total'], datos['total'])
                self.assertEqual(hoja['cantidad'], datos['cantidad'])
                self.assertEqual(sum(m['monto'] for m in hoja['metodos']), hoja['total'])
        # Entre todas las hojas suman lo mismo que los pagos de cada equipo.
        esperado = sum(
            (i.total_abonado + (i.valor_diagnostico if i.diagnostico_inmediato == 'si' else 0)
             for i in ingresos_de_seguimiento()),
            Decimal('0.00'),
        )
        self.assertEqual(sum(d['total'] for d in totales.values()), esperado)

    def test_filtro_por_sede(self):
        self.crear_semana_completa()

        ctx = self.ver(sede='quito').context

        self.assertEqual([f['codigo'] for f in ctx['filas']], [self.consola.codigo_equipo])
        self.assertEqual(ctx['total'], Decimal('120.00'))
        self.assertEqual(self.ver(sede='ventas').context['sede'], '')

    def test_hoja_nueva_el_lunes_a_las_00_00_hora_de_ecuador(self):
        ingreso = self.crear_ingreso()
        self.abonar(ingreso, DOMINGO, '10.00')
        self.abonar(ingreso, date(2026, 10, 19), '30.00')
        url = reverse('econotec:seguimiento_pago')

        # Domingo 18 a las 23:59 en Ecuador (04:59 UTC del lunes): sigue la hoja del 12.
        domingo_noche = datetime(2026, 10, 19, 4, 59, tzinfo=dt_timezone.utc)
        with patch('django.utils.timezone.now', return_value=domingo_noche):
            response = self.client.get(url)
        self.assertEqual(response.context['lunes'], LUNES)
        self.assertEqual(response.context['total'], Decimal('10.00'))

        # Lunes 19 a las 00:00 en Ecuador: hoja nueva; la anterior queda en su pestaña.
        lunes_madrugada = domingo_noche + timedelta(minutes=1)
        with patch('django.utils.timezone.now', return_value=lunes_madrugada):
            response = self.client.get(url)
        self.assertEqual(response.context['lunes'], date(2026, 10, 19))
        self.assertTrue(response.context['es_semana_actual'])
        self.assertEqual(response.context['total'], Decimal('30.00'))
        anterior = next(p for p in response.context['pestanas'] if p['lunes'] == LUNES)
        self.assertEqual(anterior['total'], Decimal('10.00'))
        self.assertFalse(anterior['actual'])

    # ── Ventas de producto y total ──────────────────────────────

    def crear_ventas_de_la_semana(self):
        # Venta pagada completa por transferencia el martes.
        self.venta_cable = self.crear_venta(
            productos=[('Cable USB', 2), ('Mouse', 1)], fecha_ingreso=date(2026, 10, 13),
            valor_acordado=Decimal('30.00'), abono_anticipo=Decimal('30.00'),
            anticipo_metodo='transferencia', anticipo_banco='pichincha', tecnico_encargado=self.tecnico_2,
        )
        # Venta por abonos: abono inicial en efectivo y otro el domingo con Payphone; todavía debe 20.
        self.venta_tinta = self.crear_venta(
            productos=[('Tinta Epson', 1)], cliente=self.cliente_2,
            valor_acordado=Decimal('50.00'), abono_anticipo=Decimal('20.00'), anticipo_metodo='efectivo',
        )
        self.abonar(self.venta_tinta, DOMINGO, '10.00', 'tarjeta', tarjeta_app='payphone')
        # Venta de la semana pasada que termina de pagarse esta semana.
        self.venta_teclado = self.crear_venta(
            fecha_ingreso=date(2026, 10, 8), problema_reportado='Teclado gamer',
            valor_acordado=Decimal('40.00'), abono_anticipo=Decimal('15.00'), anticipo_metodo='efectivo',
        )
        self.abonar(self.venta_teclado, MIERCOLES, '25.00')

    def test_entra_por_el_total_de_seguimiento(self):
        response = self.abrir()

        self.assertEqual(response.context['tipo'], 'total')
        html = response.content.decode()
        vistas = html[html.index('aria-label="Tipo de seguimiento"'):]
        vistas = vistas[:vistas.index('</nav>')]
        self.assertEqual(
            re.findall(r'(Total de seguimiento|Seguimiento de equipo|Seguimiento de producto)', vistas),
            ['Total de seguimiento', 'Seguimiento de equipo', 'Seguimiento de producto'],
        )

    def test_seguimiento_de_producto(self):
        self.crear_semana_completa()
        self.crear_ventas_de_la_semana()

        response = self.ver(tipo='producto')

        ctx = response.context
        # La venta de tinta de 12 de crear_semana_completa + 30 + 30 + 25.
        self.assertEqual(ctx['total'], Decimal('97.00'))
        self.assertEqual(ctx['cantidad'], 4)
        self.assertEqual(ctx['cantidad_equipos'], 0)
        self.assertEqual(ctx['pagos'], 5)
        self.assertTrue(all(f['es_venta'] for f in ctx['filas']))
        metodos = {m['clave']: m['monto'] for m in ctx['metodos']}
        self.assertEqual(metodos, {
            'transferencia': Decimal('30.00'),
            'efectivo': Decimal('57.00'),
            'tarjeta': Decimal('10.00'),
        })
        self.assertEqual(sum(metodos.values()), ctx['total'])
        # Solo la venta de tinta por abonos todavía debe: 50 - 30.
        self.assertEqual(ctx['saldo_total'], Decimal('20.00'))

        filas = {f['codigo']: f for f in ctx['filas']}
        cable = filas[self.venta_cable.codigo_equipo]
        self.assertEqual([c['concepto'] for c in cable['cobros']], ['Pago de venta'])
        self.assertEqual(cable['equipo'], '2 x Cable USB, 1 x Mouse')
        self.assertEqual(cable['tipo_equipo'], 'Venta de producto')
        self.assertEqual(cable['tecnicos'], [{'nombre': 'Osmar Perez', 'rol': 'Vendió'}])
        self.assertEqual(cable['saldo_estado'], 'pagado')
        tinta = filas[self.venta_tinta.codigo_equipo]
        self.assertEqual([c['concepto'] for c in tinta['cobros']], ['Abono inicial', 'Abono'])
        self.assertEqual((tinta['saldo_estado'], tinta['saldo']), ('debe', Decimal('20.00')))
        teclado = filas[self.venta_teclado.codigo_equipo]
        self.assertEqual([c['concepto'] for c in teclado['cobros']], ['Abono'])
        self.assertEqual(teclado['equipo'], 'Teclado gamer')

        self.assertContains(response, '4 ventas · 5 pagos')
        self.assertContains(response, '<th>Producto</th>', html=True)
        self.assertContains(response, '<th>Fecha de venta</th>', html=True)
        self.assertNotContains(response, self.laptop.codigo_equipo)
        # Filtro de sede también en productos, sin perder la vista.
        self.assertContains(response, 'aria-label="Sede"')
        self.assertContains(response, '?semana=2026-10-12&amp;tipo=producto&amp;sede=quito')

    def test_total_es_equipos_mas_productos(self):
        self.crear_semana_completa()
        self.crear_ventas_de_la_semana()

        total = self.abrir().context
        equipos = self.ver(tipo='equipo').context
        productos = self.ver(tipo='producto').context

        self.assertEqual(total['tipo'], 'total')
        self.assertEqual(total['total'], Decimal('302.00'))
        self.assertEqual(total['total'], equipos['total'] + productos['total'])
        self.assertEqual(total['total_equipos'], equipos['total'])
        self.assertEqual(total['total_ventas'], productos['total'])
        self.assertEqual(total['cantidad'], equipos['cantidad'] + productos['cantidad'])
        self.assertEqual(total['pagos'], equipos['pagos'] + productos['pagos'])
        self.assertEqual(total['saldo_total'], equipos['saldo_total'] + productos['saldo_total'])
        por_metodo = lambda ctx: {m['clave']: m['monto'] for m in ctx['metodos']}
        for clave, monto in por_metodo(total).items():
            with self.subTest(metodo=clave):
                self.assertEqual(
                    monto,
                    por_metodo(equipos).get(clave, Decimal('0.00')) + por_metodo(productos).get(clave, Decimal('0.00')),
                )
        self.assertEqual(
            sorted(f['codigo'] for f in total['filas']),
            sorted(f['codigo'] for f in equipos['filas'] + productos['filas']),
        )
        # Filas en orden de pago y numeradas seguidas.
        self.assertEqual([f['numero'] for f in total['filas']], list(range(1, 8)))

        response = self.abrir()
        self.assertContains(response, '3 equipos · 4 ventas · 10 pagos')
        self.assertContains(response, '🔧 Equipos <b>$205,00</b>')
        self.assertContains(response, '🛒 Productos <b>$97,00</b>')
        # Mezclados: barra de color, ícono y etiqueta por fila, y la leyenda.
        self.assertContains(response, 'class="sp-fila is-equipo"', count=3)
        self.assertContains(response, 'class="sp-fila is-producto"', count=4)
        self.assertContains(response, '<span class="sp-tipo">Producto</span>', html=True, count=4)
        self.assertContains(response, '<span class="sp-tipo">Equipo</span>', html=True, count=3)
        self.assertContains(response, 'class="sp-leyenda"')
        # En una sola vista no hace falta distinguir.
        for tipo in ('equipo', 'producto'):
            with self.subTest(tipo=tipo):
                response = self.ver(tipo=tipo)
                self.assertNotContains(response, 'class="sp-fila')
                self.assertNotContains(response, 'class="sp-leyenda"')

    def test_pestanas_cuadran_en_las_tres_vistas(self):
        self.crear_semana_completa()
        self.crear_ventas_de_la_semana()

        totales = {tipo: totales_por_semana(tipo=tipo) for tipo in ('total', 'equipo', 'producto')}

        for tipo, semanas in totales.items():
            for lunes, datos in semanas.items():
                with self.subTest(tipo=tipo, lunes=lunes):
                    hoja = hoja_semana(lunes, tipo=tipo)
                    self.assertEqual(hoja['total'], datos['total'])
                    self.assertEqual(hoja['cantidad'], datos['cantidad'])
                    self.assertEqual(hoja['cantidad_equipos'], datos['equipos'])
                    self.assertEqual(hoja['cantidad_ventas'], datos['ventas'])
        cero = {'total': Decimal('0.00')}
        for lunes, datos in totales['total'].items():
            with self.subTest(suma=lunes):
                self.assertEqual(
                    datos['total'],
                    totales['equipo'].get(lunes, cero)['total'] + totales['producto'].get(lunes, cero)['total'],
                )
        # Entre todas las hojas de producto suman lo que se cobró de cada venta.
        esperado = sum((v.total_abonado for v in ingresos_de_seguimiento(tipo='producto')), Decimal('0.00'))
        self.assertEqual(sum(d['total'] for d in totales['producto'].values()), esperado)

    def test_sede_filtra_las_tres_vistas(self):
        self.crear_semana_completa()
        self.crear_ventas_de_la_semana()
        venta_quito = self.crear_venta(
            productos=[('Control', 1, 'quito')],
            valor_acordado=Decimal('18.00'), abono_anticipo=Decimal('18.00'), anticipo_metodo='efectivo',
        )
        mixta = self.crear_venta(
            productos=[('Audífonos', 1), ('Parlante', 1, 'quito')],
            valor_acordado=Decimal('22.00'), abono_anticipo=Decimal('22.00'), anticipo_metodo='efectivo',
        )

        def codigos(ctx):
            return sorted(f['codigo'] for f in ctx['filas'])

        # Las ventas van a la sede de la bodega de sus productos.
        self.assertEqual(
            codigos(self.ver(tipo='producto', sede='guayaquil').context),
            sorted([self.venta_cable.codigo_equipo, self.venta_tinta.codigo_equipo]),
        )
        self.assertEqual(codigos(self.ver(tipo='producto', sede='quito').context), [venta_quito.codigo_equipo])

        hojas = {}
        for sede in ('', 'guayaquil', 'quito'):
            hojas[sede] = {tipo: self.ver(tipo=tipo, sede=sede).context for tipo in ('total', 'equipo', 'producto')}
            total, equipos, productos = (hojas[sede][t] for t in ('total', 'equipo', 'producto'))
            with self.subTest(sede=sede):
                self.assertEqual(total['sede'], sede)
                self.assertEqual(total['total'], equipos['total'] + productos['total'])
                self.assertEqual(total['saldo_total'], equipos['saldo_total'] + productos['saldo_total'])
                self.assertEqual(total['pagos'], equipos['pagos'] + productos['pagos'])
                self.assertEqual(codigos(total), sorted(codigos(equipos) + codigos(productos)))
                self.assertEqual(sum(m['monto'] for m in total['metodos']), total['total'])
        self.assertEqual(hojas['guayaquil']['total']['total'], Decimal('145.00'))  # 85 equipos + 60 productos
        self.assertEqual(hojas['quito']['total']['total'], Decimal('138.00'))  # 120 equipos + 18 productos
        # Sin sede quedan las ventas sin productos de inventario (12 + 25) y la mixta (22).
        self.assertEqual(
            hojas['']['total']['total'] - hojas['guayaquil']['total']['total'] - hojas['quito']['total']['total'],
            Decimal('59.00'),
        )
        self.assertNotIn(mixta.codigo_equipo, codigos(hojas['guayaquil']['total']) + codigos(hojas['quito']['total']))

        # Las pestañas de cada sede y vista suman lo mismo que su hoja.
        for sede in ('guayaquil', 'quito'):
            for tipo in ('total', 'equipo', 'producto'):
                for lunes, datos in totales_por_semana(sede, tipo).items():
                    with self.subTest(sede=sede, tipo=tipo, lunes=lunes):
                        self.assertEqual(hoja_semana(lunes, sede, tipo)['total'], datos['total'])

        response = self.ver(tipo='total', sede='quito')
        self.assertContains(response, 'cada venta cuenta en la sede de la bodega')
        # Cambiar de vista conserva la sede.
        self.assertContains(response, '?semana=2026-10-12&amp;tipo=producto&amp;sede=quito')
        self.assertNotContains(self.ver(tipo='equipo', sede='quito'), 'cada venta cuenta en la sede de la bodega')

        # Un enlace viejo con sede y sin tipo abre los equipos de esa sede.
        ctx = self.abrir(sede='quito').context
        self.assertEqual(ctx['tipo'], 'equipo')
        self.assertEqual([f['codigo'] for f in ctx['filas']], [self.consola.codigo_equipo])
        self.assertContains(self.ver(), 'aria-label="Sede"')
        # Un tipo inválido abre el total.
        self.assertEqual(self.abrir(tipo='basura').context['tipo'], 'total')

    def test_pestanas_de_semanas_conservan_la_vista(self):
        self.crear_ventas_de_la_semana()

        response = self.ver(tipo='producto')

        self.assertContains(response, '?semana=2026-10-05&amp;tipo=producto')
        anterior = next(p for p in response.context['pestanas'] if p['lunes'] == date(2026, 10, 5))
        self.assertEqual(anterior['total'], Decimal('15.00'))
        self.assertEqual(anterior['resumen'], '1 venta')
        self.assertContains(self.ver(tipo='equipo', sede='quito'), '?semana=2026-10-12&amp;tipo=equipo&amp;sede=quito')


class EgresoSeguimientoTests(TestCase):
    """Egresos registrados desde Seguimiento de pago."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username='RootAdmin', email='admin@example.com', password='adminpass123',
            first_name='Rosa', last_name='Admin',
        )
        self.asesora = User.objects.create_user(username='kimberly', first_name='Kimberly', last_name='Maquilón')
        self.asesora.groups.add(Group.objects.create(name='Asesores'))
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri')
        self.tecnico.groups.add(Group.objects.create(name='Tecnicos'))
        # Categoría sin datos extra; Repuestos y Compra de equipo piden más.
        self.categoria, _ = CategoriaEgreso.objects.get_or_create(nombre='Otros')
        self.repuestos, _ = CategoriaEgreso.objects.get_or_create(nombre='Repuestos')
        self.compra, _ = CategoriaEgreso.objects.get_or_create(nombre='Compra de equipo')
        cliente = Cliente.objects.create(cedula='0912345678', nombres='María Loor')
        # Semana del 12 al 18 de octubre: 100 de un equipo + 50 de una venta = 150 recaudado.
        self.equipo = equipo = IngresoEquipo.objects.create(
            sede='guayaquil', fecha_ingreso=LUNES, cliente=cliente, tipo_equipo='laptop', marca='HP',
            modelo_serie='Pavilion', problema_reportado='No enciende', valor_acordado=Decimal('100.00'),
            abono_anticipo=Decimal('100.00'), anticipo_metodo='efectivo', registrado_por=self.asesora,
            estado='en_reparacion', subestado_reparacion='en_reparacion',
        )
        IngresoEquipo.objects.create(
            sede='ventas', fecha_ingreso=MIERCOLES, cliente=cliente, tipo_equipo='otro', marca='N/A',
            modelo_serie='N/A', problema_reportado='Cable', valor_acordado=Decimal('50.00'),
            abono_anticipo=Decimal('50.00'), anticipo_metodo='transferencia', anticipo_banco='pichincha',
            estado='entregado', subestado_entregado='con_solucion',
        )
        # Otra semana (5 al 11 de octubre) con 30 recaudado.
        Abono.objects.create(ingreso=equipo, fecha=date(2026, 10, 9), monto=Decimal('30.00'), metodo='efectivo')
        self.client.force_login(self.admin)

    def url(self, **params):
        return f"{reverse('econotec:seguimiento_pago')}?{'&'.join(f'{k}={v}' for k, v in params.items())}"

    def registrar(self, url=None, **datos):
        datos = {
            'fecha': MIERCOLES.isoformat(), 'concepto': 'Pasta térmica', 'asesora': self.asesora.pk,
            'categoria': self.categoria.pk, 'monto': '40.00', 'metodo': 'efectivo', **datos,
        }
        with patch('econotec.views_pagos.timezone.localdate', return_value=MIERCOLES):
            return self.client.post(url or self.url(semana=MIERCOLES.isoformat()), datos)

    def ver(self, **params):
        with patch('econotec.views_pagos.timezone.localdate', return_value=MIERCOLES):
            return self.client.get(reverse('econotec:seguimiento_pago'), params)

    def test_saldo_de_la_semana(self):
        saldo = saldo_semana(MIERCOLES)

        self.assertEqual(saldo['lunes'], LUNES)
        self.assertEqual(saldo['recaudado'], Decimal('150.00'))
        self.assertEqual(saldo['disponible'], Decimal('150.00'))
        self.assertEqual(saldo_semana(date(2026, 10, 9))['recaudado'], Decimal('30.00'))
        # Restan todos los egresos de la semana, también los del Registro Administrativo.
        Egreso.objects.create(fecha=DOMINGO, categoria=self.categoria, concepto='Luz', monto=Decimal('25.00'))
        Egreso.objects.create(fecha=date(2026, 10, 19), categoria=self.categoria, concepto='Otra semana',
                              monto=Decimal('99.00'))
        saldo = saldo_semana(LUNES)
        self.assertEqual(saldo['total_egresos'], Decimal('25.00'))
        self.assertEqual(saldo['disponible'], Decimal('125.00'))

    def test_panel_de_egresos_en_la_hoja(self):
        Egreso.objects.create(fecha=LUNES, categoria=self.categoria, concepto='Cable HDMI', monto=Decimal('20.00'),
                              asesora=self.asesora, registrado_por=self.admin)

        # El saldo es de toda la semana aunque la hoja esté filtrada.
        for params in ({}, {'tipo': 'equipo', 'sede': 'quito'}):
            with self.subTest(**params):
                response = self.ver(semana=MIERCOLES.isoformat(), **params)
                caja = response.context['caja']
                self.assertEqual(caja['recaudado'], Decimal('150.00'))
                self.assertEqual(caja['total_egresos'], Decimal('20.00'))
                self.assertEqual(caja['disponible'], Decimal('130.00'))
        self.assertContains(response, 'Registrar egreso</button>')
        self.assertContains(response, 'Cable HDMI')
        self.assertContains(response, 'Kimberly Maquilón')
        self.assertContains(response, '$130,00')
        self.assertFalse(response.context['abrir_egreso'])
        # La fecha sugerida es hoy, dentro de la semana abierta.
        self.assertEqual(response.context['form_egreso'].initial['fecha'], MIERCOLES)
        self.assertEqual(self.ver(semana='2026-10-07').context['form_egreso'].initial['fecha'], date(2026, 10, 11))

    def test_registrar_egreso(self):
        response = self.registrar(url=self.url(semana=LUNES.isoformat(), tipo='producto', sede='guayaquil'))

        egreso = Egreso.objects.get()
        self.assertEqual(egreso.concepto, 'Pasta térmica')
        self.assertEqual(egreso.fecha, MIERCOLES)
        self.assertEqual(egreso.monto, Decimal('40.00'))
        self.assertEqual(egreso.asesora, self.asesora)
        self.assertEqual(egreso.categoria, self.categoria)
        self.assertEqual(egreso.registrado_por, self.admin)
        # Abre la semana del egreso y conserva la vista.
        self.assertRedirects(
            response, self.url(semana=MIERCOLES.isoformat(), tipo='producto', sede='guayaquil') + '#egresos',
            fetch_redirect_response=False,
        )
        self.assertEqual(saldo_semana(MIERCOLES)['disponible'], Decimal('110.00'))

        # Aviso en la campanita del admin, aunque lo registre un admin.
        aviso = NotificacionCambioAdmin.objects.get()
        self.assertEqual(aviso.tipo, 'egreso_seguimiento')
        self.assertEqual(aviso.creado_por, self.admin)
        self.assertIn('$40,00', aviso.mensaje)
        self.assertIn('Pasta térmica', aviso.mensaje)
        self.assertIn('Kimberly Maquilón', aviso.mensaje)
        self.assertIn('Saldo disponible de la semana 12 – 18 oct: $110,00', aviso.mensaje)
        self.assertIn('semana=2026-10-14', aviso.url)

        response = self.ver(semana=MIERCOLES.isoformat())
        self.assertContains(response, 'Saldo disponible de la semana 12 – 18 oct: $110,00')
        self.assertContains(response, '🔔')

    def test_no_pasa_del_saldo_disponible(self):
        Egreso.objects.create(fecha=LUNES, categoria=self.categoria, concepto='Luz', monto=Decimal('100.00'))

        response = self.registrar(monto='50.01')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Egreso.objects.count(), 1)
        self.assertFalse(NotificacionCambioAdmin.objects.exists())
        self.assertTrue(response.context['abrir_egreso'])
        self.assertIn(
            'El egreso supera el saldo disponible de la semana 12 – 18 oct ($50,00).',
            response.context['form_egreso'].errors['monto'],
        )
        # Justo el saldo disponible sí se puede.
        self.registrar(monto='50.00')
        self.assertEqual(saldo_semana(LUNES)['disponible'], Decimal('0.00'))
        # En la hoja de otra semana manda el saldo de esa semana.
        otra_hoja = self.url(semana='2026-10-09')
        self.assertEqual(self.registrar(url=otra_hoja, fecha='2026-10-09', monto='30.01').status_code, 200)
        self.registrar(url=otra_hoja, fecha='2026-10-09', monto='30.00')
        self.assertEqual(Egreso.objects.filter(fecha=date(2026, 10, 9)).count(), 1)

    def test_fecha_solo_de_la_hoja_abierta(self):
        # Hoja del 12 al 18 de octubre: el calendario solo deja esos días.
        response = self.ver(semana=MIERCOLES.isoformat())
        self.assertContains(response, 'min="2026-10-12"')
        self.assertContains(response, 'max="2026-10-18"')
        self.assertContains(response, 'Solo días de esta hoja: 12 – 18 oct')

        for fecha in ('2026-10-11', '2026-10-19', '2026-07-22'):
            with self.subTest(fecha=fecha):
                response = self.registrar(fecha=fecha, monto='5.00')
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['abrir_egreso'])
                self.assertEqual(response.context['form_egreso'].errors['fecha'], [
                    'La fecha debe ser de esta semana (12 – 18 oct). '
                    'Para registrar un egreso de otra semana, abre su hoja en las pestañas de abajo.'
                ])
        # Sin ?semana la hoja abierta es la de hoy.
        self.assertEqual(self.registrar(url=reverse('econotec:seguimiento_pago'), fecha='2026-10-09').status_code, 200)
        self.assertFalse(Egreso.objects.exists())
        self.assertFalse(NotificacionCambioAdmin.objects.exists())

        # Desde la hoja de esa semana sí se puede.
        for url in (self.url(semana='2026-10-05'), self.url(semana='2026-10-11', tipo='equipo', sede='quito')):
            with self.subTest(url=url):
                self.assertEqual(self.registrar(url=url, fecha='2026-10-09', monto='5.00').status_code, 302)
        self.assertEqual(Egreso.objects.filter(fecha=date(2026, 10, 9)).count(), 2)
        self.registrar(fecha=DOMINGO.isoformat(), monto='5.00')
        self.registrar(url=reverse('econotec:seguimiento_pago'), fecha=LUNES.isoformat(), monto='5.00')
        self.assertEqual(Egreso.objects.filter(fecha__range=(LUNES, DOMINGO)).count(), 2)

    def test_datos_obligatorios(self):
        response = self.registrar(concepto='  ', asesora='', categoria='', monto='0')

        errores = response.context['form_egreso'].errors
        self.assertIn('Escribe el nombre del producto.', errores['concepto'])
        self.assertIn('Selecciona la asesora que aplica el egreso.', errores['asesora'])
        self.assertIn('Selecciona la categoría.', errores['categoria'])
        self.assertIn('El monto debe ser mayor que cero.', errores['monto'])
        # Solo se puede elegir una asesora.
        errores = self.registrar(asesora=self.tecnico.pk).context['form_egreso'].errors
        self.assertIn('Selecciona una asesora de la lista.', errores['asesora'])
        self.assertFalse(Egreso.objects.exists())

    def test_saldo_por_fecha(self):
        url = reverse('econotec:seguimiento_pago_saldo')

        datos = self.client.get(url, {'fecha': '2026-10-09'}).json()

        self.assertEqual(datos['etiqueta'], '5 – 11 oct')
        self.assertEqual(datos['recaudado'], '30.00')
        self.assertEqual(datos['disponible_texto'], '$30,00')
        self.assertEqual(self.client.get(url, {'fecha': 'basura'}).status_code, 400)
        Egreso.objects.create(fecha=date(2026, 10, 10), categoria=self.categoria, concepto='X', monto=Decimal('45.00'))
        self.assertEqual(self.client.get(url, {'fecha': '2026-10-09'}).json()['disponible_texto'], '−$15,00')

        self.client.force_login(self.asesora)
        self.assertEqual(self.client.get(url, {'fecha': '2026-10-09'}).status_code, 302)
        response = self.registrar()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Egreso.objects.count(), 1)

    def test_egreso_va_a_caja_y_registro_administrativo(self):
        from .caja import caja_del_periodo
        from .views_admin import _egresos_mes

        self.registrar(monto='40.00')

        self.assertEqual(_egresos_mes(2026, 10), Decimal('40.00'))
        caja = caja_del_periodo('2026-10-01', '2026-10-31', hoy=MIERCOLES)
        self.assertEqual(caja['egresos'], Decimal('40.00'))
        response = self.client.get(reverse('econotec:admin_egresos_lista'))
        self.assertContains(response, 'Pasta térmica')
        self.assertContains(response, 'Kimberly Maquilón')
        # Editarlo desde Egresos del admin conserva la asesora.
        egreso = Egreso.objects.get()
        response = self.client.get(reverse('econotec:admin_egreso_editar', args=[egreso.pk]))
        self.assertEqual(response.context['form'].initial['asesora'], self.asesora.pk)

    # ── Datos por categoría y forma de pago ─────────────────────

    def errores(self, **datos):
        response = self.registrar(**datos)
        self.assertEqual(response.status_code, 200)
        return response.context['form_egreso'].errors

    def test_repuesto_para_un_equipo(self):
        codigo = self.equipo.codigo_equipo

        response = self.registrar(
            categoria=self.repuestos.pk, repuesto_alcance='equipo',
            repuesto_sede='guayaquil', repuesto_numero=self.equipo.numero_equipo,
        )

        self.assertEqual(response.status_code, 302)
        egreso = Egreso.objects.get()
        self.assertEqual(egreso.ingreso_repuesto, self.equipo)
        self.assertEqual(egreso.detalle_categoria, f'Repuesto para {codigo} · María Loor')
        aviso = NotificacionCambioAdmin.objects.get()
        self.assertEqual(aviso.ingreso, self.equipo)
        self.assertEqual(aviso.codigo, codigo)
        self.assertIn(f'(Repuesto para {codigo} · María Loor)', aviso.mensaje)
        self.assertIn('Pago: Efectivo.', aviso.mensaje)
        response = self.ver(semana=MIERCOLES.isoformat())
        self.assertContains(response, f'Repuesto para {codigo} · María Loor')

    def test_repuesto_valida_el_equipo(self):
        datos = {'categoria': self.repuestos.pk}
        self.assertIn('Indica si el repuesto es para un equipo o general.', self.errores(**datos)['repuesto_alcance'])
        errores = self.errores(repuesto_alcance='equipo', **datos)
        self.assertIn('Elige la sede del equipo.', errores['repuesto_sede'])
        self.assertIn('Escribe el número del equipo.', errores['repuesto_numero'])
        errores = self.errores(repuesto_alcance='equipo', repuesto_sede='guayaquil', repuesto_numero='999999', **datos)
        self.assertIn('No existe el equipo G999999 en el sistema.', errores['repuesto_numero'])
        # El número es de la sede elegida: en Quito ese equipo no existe.
        errores = self.errores(
            repuesto_alcance='equipo', repuesto_sede='quito', repuesto_numero=self.equipo.numero_equipo, **datos,
        )
        self.assertIn(f'No existe el equipo U{self.equipo.numero_equipo} en el sistema.', errores['repuesto_numero'])
        self.assertFalse(Egreso.objects.exists())

    def test_repuesto_general(self):
        self.registrar(
            categoria=self.repuestos.pk, repuesto_alcance='general',
            repuesto_sede='guayaquil', repuesto_numero=self.equipo.numero_equipo,
        )

        egreso = Egreso.objects.get()
        self.assertIsNone(egreso.ingreso_repuesto)
        self.assertEqual(egreso.detalle_categoria, 'Repuesto general')
        self.assertEqual(NotificacionCambioAdmin.objects.get().codigo, 'Egreso')

    def test_compra_de_equipo(self):
        self.assertIn('Elige qué equipo vas a comprar.', self.errores(categoria=self.compra.pk)['compra_tipo_equipo'])
        errores = self.errores(categoria=self.compra.pk, compra_tipo_equipo='otro', compra_tipo_equipo_otro='  ')
        self.assertIn('Escribe qué equipo vas a comprar.', errores['compra_tipo_equipo_otro'])

        self.registrar(categoria=self.compra.pk, compra_tipo_equipo='impresora', compra_tipo_equipo_otro='Sobra')
        self.registrar(categoria=self.compra.pk, compra_tipo_equipo='otro', compra_tipo_equipo_otro=' Proyector ',
                       monto='10.00')
        impresora, proyector = Egreso.objects.order_by('pk')
        self.assertEqual((impresora.compra_tipo_equipo, impresora.compra_tipo_equipo_otro), ('impresora', ''))
        self.assertEqual(impresora.detalle_categoria, 'Compra: Impresora')
        self.assertEqual(proyector.detalle_categoria, 'Compra: Proyector')
        # En otras categorías no se guardan datos de repuesto ni de compra.
        self.registrar(compra_tipo_equipo='laptop', repuesto_alcance='equipo', repuesto_sede='guayaquil',
                       repuesto_numero=self.equipo.numero_equipo, monto='5.00')
        otro = Egreso.objects.order_by('pk').last()
        self.assertEqual((otro.compra_tipo_equipo, otro.ingreso_repuesto, otro.detalle_categoria), ('', None, ''))

    def test_formas_de_pago(self):
        self.assertIn('Indica el banco usado para el egreso.', self.errores(metodo='transferencia')['banco'])
        self.assertIn('Especifica el nombre del banco.',
                      self.errores(metodo='transferencia', banco='otro')['banco_otro'])
        self.assertIn('Selecciona la tarjeta o aplicación usada.', self.errores(metodo='tarjeta')['tarjeta_app'])
        self.assertIn('Este campo es obligatorio.', self.errores(metodo='')['metodo'])

        # Lo que no corresponde al método elegido no se guarda.
        self.registrar(metodo='efectivo', banco='pichincha', tarjeta_app='payphone', monto='1.00')
        self.registrar(metodo='transferencia', banco='otro', banco_otro='Coop. JEP',
                       comprobante_url='https://example.com/c.jpg', monto='2.00')
        self.registrar(metodo='tarjeta', tarjeta_app='payphone', banco='pichincha', monto='3.00')
        efectivo, transferencia, tarjeta = Egreso.objects.order_by('pk')
        self.assertEqual((efectivo.banco, efectivo.tarjeta_app), ('', ''))
        self.assertEqual(efectivo.forma_pago_texto, 'Efectivo')
        self.assertEqual(transferencia.forma_pago_texto, 'Transferencia · Coop. JEP')
        self.assertEqual(transferencia.comprobante_url, 'https://example.com/c.jpg')
        self.assertEqual((tarjeta.banco, tarjeta.forma_pago_texto), ('', 'Tarjeta · Payphone'))

    def test_pago_mixto(self):
        errores = self.errores(metodo='mixto')
        for campo in ('monto_1', 'monto_2', 'metodo_1', 'metodo_2'):
            self.assertIn(campo, errores)
        errores = self.errores(metodo='mixto', monto_1='10', metodo_1='transferencia', monto_2='20', metodo_2='tarjeta')
        self.assertIn('Indica el banco del primer pago.', errores['banco_1'])
        self.assertIn('Selecciona la tarjeta o aplicación del segundo pago.', errores['tarjeta_app_2'])
        self.assertIn('La suma de los pagos mixtos debe ser igual al monto del egreso.', errores['monto_2'])
        self.assertIn('metodo_1', self.errores(metodo='mixto', monto_1='20', metodo_1='mixto',
                                               monto_2='20', metodo_2='efectivo'))

        response = self.registrar(
            metodo='mixto', monto='40.00', banco='produbanco',
            monto_1='25.00', metodo_1='transferencia', banco_1='pichincha', tarjeta_app_1='deuna',
            monto_2='15.00', metodo_2='tarjeta', tarjeta_app_2='payphone', banco_2='guayaquil',
        )

        self.assertEqual(response.status_code, 302)
        egreso = Egreso.objects.get()
        self.assertEqual(egreso.banco, '')
        self.assertEqual((egreso.banco_1, egreso.tarjeta_app_1), ('pichincha', ''))
        self.assertEqual((egreso.banco_2, egreso.tarjeta_app_2), ('', 'payphone'))
        self.assertEqual(
            egreso.forma_pago_texto,
            'Mixto: Transferencia · Banco Pichincha ($25,00) + Tarjeta · Payphone ($15,00)',
        )
        self.assertIn('Pago: Mixto: Transferencia · Banco Pichincha ($25,00)', NotificacionCambioAdmin.objects.get().mensaje)

    def test_buscar_equipo_del_repuesto(self):
        url = reverse('econotec:seguimiento_pago_equipo')

        datos = self.client.get(url, {'sede': 'guayaquil', 'numero': self.equipo.numero_equipo}).json()

        self.assertEqual(datos, {
            'existe': True, 'codigo': self.equipo.codigo_equipo, 'cliente': 'María Loor', 'equipo': 'Laptop HP Pavilion',
        })
        self.assertEqual(self.client.get(url, {'sede': 'quito', 'numero': '999999'}).json(), {'existe': False})
        self.assertEqual(self.client.get(url, {'sede': 'ventas', 'numero': '1'}).status_code, 400)
        self.assertEqual(self.client.get(url, {'sede': 'guayaquil', 'numero': 'x'}).status_code, 400)
        self.client.force_login(self.asesora)
        self.assertEqual(self.client.get(url, {'sede': 'guayaquil', 'numero': '1'}).status_code, 302)

    def test_detalle_en_egresos_del_admin(self):
        self.registrar(
            categoria=self.repuestos.pk, repuesto_alcance='equipo', repuesto_sede='guayaquil',
            repuesto_numero=self.equipo.numero_equipo, metodo='transferencia', banco='pichincha',
        )

        response = self.client.get(reverse('econotec:admin_egresos_lista'))

        self.assertContains(response, '<th>Forma de pago</th>', html=True)
        self.assertContains(response, 'Transferencia · Banco Pichincha')
        self.assertContains(response, f'Repuesto para {self.equipo.codigo_equipo} · María Loor')

    def test_resta_en_todo_el_registro_administrativo_y_la_caja(self):
        """Un egreso de aquí resta lo mismo en el Registro, la Caja, el Histórico y el reporte."""
        import json
        from io import BytesIO

        import openpyxl

        from .caja import caja_del_periodo

        def foto():
            self.client.force_login(self.admin)
            registro = self.client.get(reverse('econotec:admin_dashboard'), {'ano': '2026', 'mes': '10'})
            self.client.post(reverse('econotec:admin_caja_abrir'), {'password': 'adminpass123'})
            abierta = self.client.get(reverse('econotec:admin_dashboard'), {'ano': '2026', 'mes': '10'})
            self.assertTrue(abierta.context['caja_abierta'])
            octubre = next(m for m in abierta.context['historico_meses'] if m['mes'] == date(2026, 10, 1))
            reporte = self.client.get(reverse('econotec:admin_export_reporte'), {'ano': '2026', 'mes': '10'})
            hoja = openpyxl.load_workbook(BytesIO(reporte.content)).active
            filas = {fila[0]: fila[1] for fila in hoja.iter_rows(values_only=True) if fila[0]}
            caja_mes = caja_del_periodo('2026-10-01', '2026-10-31')
            # Caja fuerte: lo que entró y los egresos de la semana del 12 al 18 de octubre.
            fuerte = abierta.context['caja_fuerte_datos']
            en_semana = lambda clave: '2026-10-12' <= clave <= '2026-10-18'
            fuerte_entro = sum(v[0] for k, v in fuerte['dias'].items() if en_semana(k))
            fuerte_egresos = sum(v for k, v in fuerte['egresos'].items() if en_semana(k))
            return {
                'caja_fuerte_semana_entro': Decimal(fuerte_entro) / 100,
                'caja_fuerte_semana_egresos': Decimal(fuerte_egresos) / 100,
                'caja_fuerte_semana_queda': Decimal(fuerte_entro - fuerte_egresos) / 100,
                'caja_fuerte_html': abierta.content.decode(),
                'egresos_mes': registro.context['egresos_total'],
                'utilidad_mes': registro.context['utilidad'],
                'grafico_octubre': json.loads(registro.context['chart_tendencia_egresos'])[9],
                'caja_mes_egresos': caja_mes['egresos'],
                'caja_mes_guardado': caja_mes['saldo_final'],
                'caja_grande_egresos': abierta.context['caja']['egresos'],
                'caja_grande_guardado': abierta.context['caja']['saldo_final'],
                'historico_egresos': octubre['egresos'],
                'historico_neto': octubre['neto'],
                'reporte_egresos': Decimal(str(filas['TOTAL EGRESOS'])),
                'reporte_utilidad': Decimal(str(filas['UTILIDAD DEL MES'])),
                'cuadres': [c['titulo'] for c in abierta.context['cuadres'] if c['estado'] == 'diferencia'],
            }

        antes = foto()
        response = self.registrar(
            monto='40.00', categoria=self.repuestos.pk, repuesto_alcance='equipo',
            repuesto_sede='guayaquil', repuesto_numero=self.equipo.numero_equipo,
            metodo='mixto', monto_1='25.00', metodo_1='efectivo', monto_2='15.00', metodo_2='transferencia',
            banco_2='pichincha',
        )
        self.assertEqual(response.status_code, 302)
        despues = foto()

        cuarenta = Decimal('40.00')
        for clave in ('egresos_mes', 'caja_mes_egresos', 'caja_grande_egresos', 'historico_egresos', 'reporte_egresos',
                      'caja_fuerte_semana_egresos'):
            with self.subTest(suma=clave):
                self.assertEqual(despues[clave] - antes[clave], cuarenta)
        self.assertEqual(despues['grafico_octubre'] - antes['grafico_octubre'], 40.0)
        for clave in ('utilidad_mes', 'caja_mes_guardado', 'caja_grande_guardado', 'historico_neto', 'reporte_utilidad',
                      'caja_fuerte_semana_queda'):
            with self.subTest(resta=clave):
                self.assertEqual(antes[clave] - despues[clave], cuarenta)
        # Todo sigue cuadrando: ningún cuadre queda con diferencia.
        self.assertEqual(antes['cuadres'], [])
        self.assertEqual(despues['cuadres'], [])
        # Lo que entró a la caja fuerte no cambia: el egreso se ve aparte.
        self.assertEqual(antes['caja_fuerte_semana_entro'], despues['caja_fuerte_semana_entro'])
        for clave in ('dia', 'semana', 'mes', 'anio'):
            self.assertIn(f'data-bf-queda="{clave}"', despues['caja_fuerte_html'])
        # La hoja de la semana y la caja mediana de la caja fuerte quedan iguales.
        saldo = saldo_semana(MIERCOLES)
        self.assertEqual(saldo['disponible'], Decimal('110.00'))
        self.assertEqual(despues['caja_fuerte_semana_entro'], saldo['recaudado'])
        self.assertEqual(despues['caja_fuerte_semana_queda'], saldo['disponible'])

    def test_egresos_por_dia_de_la_caja_fuerte(self):
        from .caja import egresos_por_dia

        Egreso.objects.create(fecha=LUNES, categoria=self.categoria, concepto='A', monto=Decimal('10.50'))
        Egreso.objects.create(fecha=LUNES, categoria=self.categoria, concepto='B', monto=Decimal('0.25'))
        Egreso.objects.create(fecha=DOMINGO, categoria=self.categoria, concepto='C', monto=Decimal('3.00'))

        self.assertEqual(egresos_por_dia(), {'2026-10-12': 1075, '2026-10-18': 300})
