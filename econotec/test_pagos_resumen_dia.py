"""Pruebas del apartado «Hoy / Ayer / Este mes» de Control de Pagos (reparaciones)."""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .models import Abono, Cliente, IngresoEquipo, SalidaEquipo
from .permisos import GRUPO_ASISTENTE_CAJA
from .seguimiento_pago import cobros_del_periodo, hoja_semana, inicio_semana

HOY = date(2026, 11, 24)
AYER = date(2026, 11, 23)


class ResumenPagosDiaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='RootAdmin', email='a@example.com', password='x')
        self.asistente = User.objects.create_user(username='karla', first_name='Karla')
        self.asistente.groups.add(Group.objects.get(name=GRUPO_ASISTENTE_CAJA))
        self.asesora = User.objects.create_user(username='kimberly', first_name='Kimberly')
        self.asesora.groups.add(Group.objects.get_or_create(name='Asesores')[0])
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri')
        self.tecnico.groups.add(Group.objects.get_or_create(name='Tecnicos')[0])
        self.cliente = Cliente.objects.create(cedula='0912345678', nombres='María Loor')

        # Hoy: anticipo de $40 + diagnóstico inmediato de $10 + abono de $25 de otro equipo.
        self.crear_ingreso(
            fecha_ingreso=HOY, abono_anticipo=Decimal('40.00'), anticipo_metodo='efectivo',
            diagnostico_inmediato='si', valor_diagnostico=Decimal('10.00'), diagnostico_metodo='efectivo',
        )
        viejo = self.crear_ingreso(fecha_ingreso=date(2026, 10, 30))
        self.abonar(viejo, HOY, '25.00')
        # Ayer: pago al finalizar de $60.
        finalizado = self.crear_ingreso(fecha_ingreso=date(2026, 11, 3))
        SalidaEquipo.objects.create(
            ingreso=finalizado, fecha_salida=AYER, estado_reparacion='pendiente_retiro',
            tecnico_reparo=self.tecnico, valor_final_cobrado=Decimal('60.00'),
        )
        # Este mes (día 2): abono de $15. El mes pasado no cuenta en «Este mes».
        self.abonar(viejo, date(2026, 11, 2), '15.00')
        self.abonar(viejo, date(2026, 10, 31), '99.00')
        # Las ventas de producto tienen su propio Control de Pagos: no suman aquí.
        self.crear_ingreso(
            sede='ventas', fecha_ingreso=HOY, tipo_equipo='otro', marca='N/A', modelo_serie='N/A',
            abono_anticipo=Decimal('500.00'), anticipo_metodo='efectivo', estado='entregado',
            subestado_reparacion='', subestado_entregado='con_solucion',
        )

    def crear_ingreso(self, **overrides):
        datos = {
            'sede': 'guayaquil', 'cliente': self.cliente, 'tipo_equipo': 'laptop', 'marca': 'HP',
            'modelo_serie': 'Pavilion', 'problema_reportado': 'No enciende',
            'valor_acordado': Decimal('200.00'), 'registrado_por': self.asesora,
            'estado': 'en_reparacion', 'subestado_reparacion': 'en_reparacion',
        }
        datos.update(overrides)
        return IngresoEquipo.objects.create(**datos)

    def abonar(self, ingreso, fecha, monto):
        return Abono.objects.create(
            ingreso=ingreso, fecha=fecha, monto=Decimal(monto), metodo='efectivo', registrado_por=self.asesora,
        )

    def abrir(self, usuario, dia=HOY):
        self.client.force_login(usuario)
        with patch('econotec.views_pagos.timezone.localdate', return_value=dia):
            return self.client.get(reverse('econotec:pagos_lista'))

    def test_cobrado_hoy_ayer_y_este_mes(self):
        resumen = self.abrir(self.admin).context['resumen_pagos_dia']
        self.assertEqual([d['etiqueta'] for d in resumen], ['Hoy', 'Ayer', 'Este mes'])
        self.assertEqual([d['periodo'] for d in resumen], ['24/11/2026', '23/11/2026', 'Noviembre 2026'])
        self.assertEqual([d['total'] for d in resumen], [Decimal('75.00'), Decimal('60.00'), Decimal('150.00')])
        self.assertEqual([d['pagos'] for d in resumen], [3, 1, 5])

    def test_hoy_se_reinicia_cada_dia_y_el_mes_el_dia_1(self):
        manana = self.abrir(self.admin, dia=date(2026, 11, 25)).context['resumen_pagos_dia']
        self.assertEqual(manana[0]['total'], Decimal('0.00'))
        self.assertEqual(manana[1]['total'], Decimal('75.00'))
        diciembre = self.abrir(self.admin, dia=date(2026, 12, 1)).context['resumen_pagos_dia']
        self.assertEqual(diciembre[2]['periodo'], 'Diciembre 2026')
        self.assertEqual(diciembre[2]['total'], Decimal('0.00'))
        self.assertEqual(diciembre[2]['pagos'], 0)

    def test_no_depende_de_los_filtros_de_la_tabla(self):
        self.client.force_login(self.admin)
        with patch('econotec.views_pagos.timezone.localdate', return_value=HOY):
            respuesta = self.client.get(reverse('econotec:pagos_lista'), {'sede_pago': 'quito', 'q': 'zzz'})
        self.assertEqual(respuesta.context['resumen_pagos_dia'][0]['total'], Decimal('75.00'))

    def test_cuadra_con_seguimiento_de_pago(self):
        semana = hoja_semana(inicio_semana(HOY), tipo='equipo')
        dias = cobros_del_periodo(semana['lunes'], semana['domingo'])
        self.assertEqual(dias['total'], semana['total'])
        self.assertEqual(dias['pagos'], semana['pagos'])

    def test_dinero_solo_para_admin_y_caja(self):
        for usuario in (self.admin, self.asistente):
            with self.subTest(usuario=usuario.username):
                respuesta = self.abrir(usuario)
                self.assertContains(respuesta, 'Pagos cobrados')
                self.assertContains(respuesta, '$75,00')
                self.assertContains(respuesta, '3 pagos')
        for usuario in (self.asesora, self.tecnico):
            with self.subTest(usuario=usuario.username):
                respuesta = self.abrir(usuario)
                self.assertContains(respuesta, 'Pagos cobrados')
                self.assertNotContains(respuesta, '$75,00')
                self.assertNotContains(respuesta, '$150,00')

    def abrir_ventas(self, usuario, nombre='pagos_ventas_lista', dia=HOY):
        self.client.force_login(usuario)
        with patch('econotec.views_pagos.timezone.localdate', return_value=dia):
            return self.client.get(reverse(f'econotec:{nombre}'))

    def test_ventas_suman_solo_ventas_de_producto(self):
        # Venta de ayer pagada con un abono inicial de $30 y un abono de hoy de $20.
        venta = self.crear_ingreso(
            sede='ventas', fecha_ingreso=AYER, tipo_equipo='otro', marca='N/A', modelo_serie='N/A',
            valor_acordado=Decimal('50.00'), abono_anticipo=Decimal('30.00'), anticipo_metodo='efectivo',
            estado='entregado', subestado_reparacion='', subestado_entregado='con_solucion',
        )
        self.abonar(venta, HOY, '20.00')
        resumen = self.abrir_ventas(self.admin).context['resumen_pagos_dia']
        self.assertEqual([d['etiqueta'] for d in resumen], ['Hoy', 'Ayer', 'Este mes'])
        # Hoy: $500 de la venta del setUp + $20 del abono; nada de reparaciones.
        self.assertEqual([d['total'] for d in resumen], [Decimal('520.00'), Decimal('30.00'), Decimal('550.00')])
        self.assertEqual([d['pagos'] for d in resumen], [2, 1, 3])
        # Reparaciones no se mezclan con las ventas.
        self.assertEqual(self.abrir(self.admin).context['resumen_pagos_dia'][0]['total'], Decimal('75.00'))

    def test_ventas_cuadra_con_seguimiento_de_productos(self):
        semana = hoja_semana(inicio_semana(HOY), tipo='producto')
        dias = cobros_del_periodo(semana['lunes'], semana['domingo'], tipo='producto')
        self.assertEqual(dias['total'], semana['total'])
        self.assertEqual(dias['pagos'], semana['pagos'])

    def test_ventas_en_sus_tres_listas(self):
        for nombre in ('pagos_ventas_lista', 'pagos_ventas_completos', 'pagos_ventas_parciales'):
            with self.subTest(lista=nombre):
                respuesta = self.abrir_ventas(self.admin, nombre)
                self.assertContains(respuesta, 'Pagos cobrados')
                self.assertContains(respuesta, 'Pagos y abonos de todas las ventas de producto.')
                self.assertEqual(respuesta.context['resumen_pagos_dia'][0]['total'], Decimal('500.00'))

    def test_ventas_dinero_solo_para_admin_y_caja(self):
        for usuario in (self.admin, self.asistente):
            with self.subTest(usuario=usuario.username):
                self.assertContains(self.abrir_ventas(usuario), '1 pago<')
        for usuario in (self.asesora, self.tecnico):
            with self.subTest(usuario=usuario.username):
                respuesta = self.abrir_ventas(usuario)
                self.assertContains(respuesta, 'Pagos cobrados')
                self.assertFalse(respuesta.context['resumen_pagos_con_dinero'])
                self.assertNotContains(respuesta, 'pay-day-value">$')
