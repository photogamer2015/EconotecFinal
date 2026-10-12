"""Pruebas del Seguimiento de pago (hoja semanal de pagos de equipos)."""
import re
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import Abono, Cliente, IngresoEquipo, SalidaEquipo
from .seguimiento_pago import (
    etiqueta_semana, hoja_semana, ingresos_de_seguimiento, inicio_semana,
    titulo_semana, totales_por_semana,
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

    def ver(self, **params):
        with patch('econotec.views_pagos.timezone.localdate', return_value=MIERCOLES):
            return self.client.get(reverse('econotec:seguimiento_pago'), params)

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
        self.assertNotContains(response, 'Ranking')

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
