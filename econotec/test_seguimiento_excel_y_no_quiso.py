"""Seguimiento de pago: Excel por semana y filtro por forma de pago.
Finalización «Cliente no quiso reparar»: valor adicional Sí/No obligatorio ($5 sugeridos).
"""
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from .forms import SalidaEquipoForm
from .models import Abono, Cliente, IngresoEquipo, SalidaEquipo
from .qr_utils import token_para_ingreso
from .seguimiento_pago import hoja_semana

LUNES = date(2026, 10, 12)
MIERCOLES = date(2026, 10, 14)


class SeguimientoExcelYFiltroTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='RootAdmin', email='a@example.com', password='x')
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri')
        self.tecnico.groups.add(Group.objects.create(name='Tecnicos'))
        cliente = Cliente.objects.create(cedula='0912345678', nombres='María Loor')
        self.ingreso = IngresoEquipo.objects.create(
            sede='guayaquil', fecha_ingreso=LUNES, cliente=cliente, tipo_equipo='laptop', marca='HP',
            modelo_serie='Pavilion', problema_reportado='No enciende', valor_acordado=Decimal('200.00'),
            tecnico_encargado=self.tecnico, registrado_por=self.admin,
            estado='en_reparacion', subestado_reparacion='en_reparacion',
        )
        Abono.objects.create(ingreso=self.ingreso, fecha=LUNES, monto=Decimal('20.00'), metodo='efectivo')
        Abono.objects.create(ingreso=self.ingreso, fecha=MIERCOLES, monto=Decimal('50.00'),
                             metodo='transferencia', banco='pichincha')
        self.client.force_login(self.admin)

    def test_filtro_deja_solo_la_forma_de_pago_elegida(self):
        self.assertEqual(hoja_semana(LUNES)['total'], Decimal('70.00'))
        efectivo = hoja_semana(LUNES, forma_pago='efectivo')
        self.assertEqual(efectivo['total'], Decimal('20.00'))
        self.assertEqual(efectivo['pagos'], 1)
        transferencia = hoja_semana(LUNES, forma_pago='transferencia')
        self.assertEqual(transferencia['total'], Decimal('50.00'))
        self.assertEqual(hoja_semana(LUNES, forma_pago='tarjeta')['filas'], [])

        pantalla = self.client.get(reverse('econotec:seguimiento_pago'),
                                   {'semana': LUNES.isoformat(), 'forma_pago': 'transferencia'})
        self.assertEqual(pantalla.context['total'], Decimal('50.00'))
        self.assertContains(pantalla, 'Mostrando solo los pagos en')
        self.assertContains(pantalla, 'forma_pago=transferencia')
        # El saldo de caja (egresos) sigue siendo el de toda la semana.
        self.assertEqual(pantalla.context['caja']['recaudado'], Decimal('70.00'))

    def test_excel_de_la_semana_con_filtros(self):
        pantalla = self.client.get(reverse('econotec:seguimiento_pago'), {'semana': LUNES.isoformat()})
        self.assertContains(pantalla, 'Descargar Excel de la semana')
        self.assertContains(pantalla, reverse('econotec:seguimiento_pago_excel'))

        respuesta = self.client.get(reverse('econotec:seguimiento_pago_excel'),
                                    {'semana': MIERCOLES.isoformat(), 'forma_pago': 'efectivo'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('2026-10-12_al_2026-10-18', respuesta['Content-Disposition'])
        self.assertIn('efectivo', respuesta['Content-Disposition'])
        hoja = load_workbook(BytesIO(respuesta.content)).active
        valores = [[c for c in fila] for fila in hoja.iter_rows(values_only=True)]
        filas_pago = [fila for fila in valores if fila and fila[5] == self.ingreso.codigo_equipo]
        self.assertEqual(len(filas_pago), 1)
        self.assertEqual(filas_pago[0][9], 'Efectivo')
        self.assertEqual(filas_pago[0][11], 20.0)
        self.assertTrue(any(fila and fila[3] == 'Total de la semana' and fila[11] == 20.0 for fila in valores))

        todas = load_workbook(BytesIO(self.client.get(
            reverse('econotec:seguimiento_pago_excel'), {'semana': LUNES.isoformat()},
        ).content)).active
        pagos = [f for f in todas.iter_rows(values_only=True) if f and f[5] == self.ingreso.codigo_equipo]
        self.assertEqual([f[11] for f in pagos], [20.0, 50.0])
        # El saldo pendiente va solo en el primer pago del equipo.
        self.assertEqual([f[12] for f in pagos], [130.0, None])

    def test_excel_solo_para_quien_ve_seguimiento(self):
        self.client.force_login(self.tecnico)
        respuesta = self.client.get(reverse('econotec:seguimiento_pago_excel'))
        self.assertEqual(respuesta.status_code, 302)


class ValorAdicionalNoQuisoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri')
        self.tecnico.groups.add(Group.objects.create(name='Tecnicos'))
        cliente = Cliente.objects.create(cedula='0912345678', nombres='María Loor', correo='')
        self.ingreso = IngresoEquipo.objects.create(
            sede='guayaquil', fecha_ingreso=date.today(), cliente=cliente, tipo_equipo='laptop', marca='HP',
            modelo_serie='Pavilion', problema_reportado='No enciende', valor_acordado=Decimal('40.00'),
            tecnico_encargado=self.tecnico, registrado_por=self.tecnico,
            estado='en_reparacion', subestado_reparacion='en_reparacion',
        )
        self.client.force_login(self.tecnico)

    def datos(self, estado, **extra):
        datos = {
            'fecha_salida': date.today().isoformat(), 'estado_reparacion': estado,
            'tecnico_reparo': str(self.tecnico.pk), 'reporte_tecnico': 'Revisado.',
            'valor_final_cobrado': '0.00', 'valor_acordado_revision': '',
            'aplica_valor_acordado_adicional': '', 'valor_acordado_adicional': '',
            'motivo_valor_acordado_adicional': '', 'metodo_pago_final': 'sin_pago',
            'factura_realizada': 'no',
        }
        datos.update(extra)
        return datos

    def form(self, datos):
        return SalidaEquipoForm(datos, instance=SalidaEquipo(ingreso=self.ingreso), permitir_resultados_negativos=True)

    def test_no_quiso_obliga_a_elegir_si_o_no(self):
        for estado in ('cliente_no_acepta', 'revision:cliente_no_acepta'):
            with self.subTest(estado=estado):
                form = self.form(self.datos(estado))
                self.assertFalse(form.is_valid())
                self.assertIn('aplica_valor_acordado_adicional', form.errors)

    def test_otros_estados_siguen_sin_obligar(self):
        for estado in ('no_reparable', 'revision:no_reparable', 'revision:equipo_prueba'):
            with self.subTest(estado=estado):
                form = self.form(self.datos(estado))
                self.assertNotIn('aplica_valor_acordado_adicional', form.errors)

    def test_no_quiso_con_si_llena_el_motivo_y_respeta_el_valor(self):
        form = self.form(self.datos('cliente_no_acepta', aplica_valor_acordado_adicional='si',
                                    valor_acordado_adicional='7.50'))
        self.assertNotIn('aplica_valor_acordado_adicional', form.errors)
        self.assertNotIn('motivo_valor_acordado_adicional', form.errors)
        self.assertNotIn('valor_acordado_adicional', form.errors)
        self.assertEqual(form.cleaned_data['valor_acordado_adicional'], Decimal('7.50'))
        self.assertEqual(form.cleaned_data['motivo_valor_acordado_adicional'], 'Cliente no quiso reparar')

        con_no = self.form(self.datos('cliente_no_acepta', aplica_valor_acordado_adicional='no'))
        self.assertNotIn('aplica_valor_acordado_adicional', con_no.errors)

    def test_pantalla_sugiere_cinco_dolares(self):
        pantalla = self.client.get(
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': self.ingreso.pk}),
            {'estado': 'revision:cliente_no_acepta'},
        )
        self.assertEqual(pantalla.context['form'].initial['estado_reparacion'], 'revision:cliente_no_acepta')
        self.assertContains(pantalla, "inputValorAdicional.value = '5.00'")
        self.assertContains(pantalla, '— Elige Sí o No —')

    def test_hoja_del_tecnico_abre_la_finalizacion_en_no_quiso(self):
        token = token_para_ingreso(self.ingreso.pk)
        respuesta = self.client.post(
            reverse('econotec:tecnico_hoja', kwargs={'token': token}),
            {'estado_movil': 'entregado_no_quiso', 'reporte_tecnico': 'No quiso.', 'accion': 'guardar'},
        )
        self.assertRedirects(
            respuesta,
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': self.ingreso.pk}) + '?estado=revision:cliente_no_acepta',
            fetch_redirect_response=False,
        )
