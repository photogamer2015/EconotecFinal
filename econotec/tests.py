from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .forms import IngresoEquipoForm
from .models import Cliente, IngresoEquipo, SalidaEquipo
from .qr_utils import token_para_ingreso


class VentasTests(TestCase):
    def setUp(self):
        User = get_user_model()
        asesores = Group.objects.create(name='Asesores')
        tecnicos = Group.objects.create(name='Tecnicos')

        self.vendedor = User.objects.create_user(username='Kimberly')
        self.vendedor.groups.add(asesores)

        self.usuario = User.objects.create_user(username='Yandri')
        self.usuario.groups.add(tecnicos)
        self.client.force_login(self.usuario)

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
        self.assertEqual(data['salidas_producto'], 1)
        self.assertEqual(data['total'], 1)

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
        self.assertContains(response, 'Registrar salida')
        self.assertContains(response, 'id="btn-perfil-movil"')
        self.assertContains(response, 'Ver perfil')
        self.assertContains(response, 'id="perfil-mobile-modal"')

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
