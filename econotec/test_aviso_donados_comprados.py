"""Donados y Compras: avisar al cliente que su equipo quedó donado o comprado.

Cada tarjeta de la bandeja administrativa ofrece:
- «📄 Descargar PDF»: hoja «EQUIPO DONADO» o «EQUIPO COMPRADO» con cliente y
  equipo; la de comprado lleva además el pago y el egreso.
- «💬 Enviar WhatsApp»: mensaje profesional al teléfono del cliente.
Los datos que faltan (serie, correo, etc.) se omiten: nunca «—» ni «None».
"""
from datetime import date
from decimal import Decimal
from unittest import mock
from urllib.parse import unquote

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from reportlab import rl_config

from .alertas import whatsapp_link_equipo_donado_comprado
from .models import Cliente, IngresoEquipo
from .views import _sincronizar_egreso_compra
from .views_print import generar_equipo_administrativo_pdf_bytes


FECHA = date(2026, 11, 3)


def texto_mensaje(link):
    return unquote(link.split('text=', 1)[1])


def textos_dibujados(pdf):
    """Solo el texto que el PDF dibuja con «(texto) Tj»."""
    import re
    return ' | '.join(re.findall(r'\((.*?)\) Tj', pdf))


def texto_pdf(ingreso):
    """PDF sin comprimir para poder buscar el texto dibujado."""
    with mock.patch.object(rl_config, 'pageCompression', 0):
        return generar_equipo_administrativo_pdf_bytes(ingreso).decode('latin-1')


class AvisoDonadosCompradosBase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='RootAdmin', email='a@example.com', password='x')
        self.cliente = Cliente.objects.create(
            cedula='0912345678', nombres='Osmar Perez', whatsapp='0991234567',
            correo='osmar@example.com',
        )
        self.client.force_login(self.admin)

    def crear(self, estado, cliente=None, **extra):
        datos = {
            'sede': 'guayaquil',
            'fecha_ingreso': FECHA,
            'cliente': cliente or self.cliente,
            'tipo_equipo': 'impresora',
            'marca': 'Epson',
            'modelo_serie': 'L4160',
            'serie': 'X123',
            'problema_reportado': 'Equipo recibido',
            'registrado_por': self.admin,
            'estado': estado,
        }
        if estado == 'equipo_a_comprar':
            datos.update(valor_acordado=Decimal('30.00'), compra_metodo_pago='efectivo')
        datos.update(extra)
        ingreso = IngresoEquipo.objects.create(**datos)
        if estado == 'equipo_a_comprar':
            _sincronizar_egreso_compra(ingreso, self.admin)
        return ingreso

    def cliente_incompleto(self):
        return Cliente.objects.create(cedula='0999999999', nombres='Sin Datos', whatsapp='0987654321')


class WhatsAppDonadoCompradoTests(AvisoDonadosCompradosBase):
    def test_donado_agradece_con_codigo_equipo_fecha_y_sede(self):
        ingreso = self.crear('donado')
        link = whatsapp_link_equipo_donado_comprado(ingreso)
        self.assertTrue(link.startswith('https://wa.me/593991234567?text='))
        mensaje = texto_mensaje(link)
        self.assertIn('Estimado(a) Osmar', mensaje)
        self.assertIn('agradecerle sinceramente por donar su equipo', mensaje)
        self.assertIn(f'*{ingreso.codigo_equipo}*', mensaje)
        self.assertIn('• Equipo: Impresora Epson', mensaje)
        self.assertIn('• Modelo: L4160', mensaje)
        self.assertIn('• Serie: X123', mensaje)
        self.assertIn('• Fecha: 03/11/2026', mensaje)
        self.assertIn('• Sede: Guayaquil', mensaje)
        self.assertNotIn('Valor pagado', mensaje)

    def test_comprado_confirma_compra_valor_y_metodo(self):
        ingreso = self.crear(
            'equipo_a_comprar', compra_metodo_pago='transferencia', compra_banco='pichincha',
        )
        mensaje = texto_mensaje(whatsapp_link_equipo_donado_comprado(ingreso))
        self.assertIn('Econotec compró su equipo', mensaje)
        self.assertIn(f'*{ingreso.codigo_equipo}*', mensaje)
        self.assertIn('• Equipo: Impresora Epson', mensaje)
        self.assertIn('• Valor pagado: *$30,00*', mensaje)
        self.assertIn('• Método de pago: Transferencia bancaria (Banco Pichincha)', mensaje)

    def test_comprado_con_pago_mixto_detalla_cada_parte(self):
        ingreso = self.crear(
            'equipo_a_comprar', compra_metodo_pago='mixto',
            compra_monto_1=Decimal('10.00'), compra_metodo_1='efectivo',
            compra_monto_2=Decimal('20.00'), compra_metodo_2='tarjeta',
            compra_tarjeta_app_2='deuna',
        )
        mensaje = texto_mensaje(whatsapp_link_equipo_donado_comprado(ingreso))
        self.assertIn(
            '• Método de pago: Pago mixto: $10,00 en Efectivo y '
            '$20,00 en Tarjeta de crédito / Débito (Deuna)',
            mensaje,
        )

    def test_datos_faltantes_se_omiten_sin_guiones_ni_none(self):
        ingreso = self.crear('donado', cliente=self.cliente_incompleto(), modelo_serie='', serie='')
        mensaje = texto_mensaje(whatsapp_link_equipo_donado_comprado(ingreso))
        self.assertNotIn('Serie', mensaje)
        self.assertNotIn('Modelo', mensaje)
        self.assertNotIn('None', mensaje)
        self.assertNotIn('—\n', mensaje)
        self.assertNotIn(': —', mensaje)

    def test_sin_whatsapp_u_otro_estado_no_hay_enlace(self):
        sin_tel = Cliente.objects.create(cedula='0911111111', nombres='Sin Tel')
        self.assertIsNone(whatsapp_link_equipo_donado_comprado(self.crear('donado', cliente=sin_tel)))
        self.assertIsNone(whatsapp_link_equipo_donado_comprado(self.crear('en_reparacion')))


class PdfDonadoCompradoTests(AvisoDonadosCompradosBase):
    def test_pdf_donado_dice_equipo_donado_con_cliente_y_equipo(self):
        ingreso = self.crear('donado')
        pdf = texto_pdf(ingreso)
        self.assertTrue(pdf.startswith('%PDF'))
        self.assertIn('(EQUIPO DONADO)', pdf)
        self.assertIn('Osmar Perez', pdf)
        self.assertIn('0912345678', pdf)
        self.assertIn('osmar@example.com', pdf)
        self.assertIn('L4160', pdf)
        self.assertIn('X123', pdf)
        self.assertNotIn('DETALLE DEL PAGO', pdf)

    def test_pdf_comprado_incluye_pago_y_egreso(self):
        ingreso = self.crear(
            'equipo_a_comprar', compra_metodo_pago='mixto',
            compra_monto_1=Decimal('10.00'), compra_metodo_1='efectivo',
            compra_monto_2=Decimal('20.00'), compra_metodo_2='transferencia',
            compra_banco_2='guayaquil',
        )
        pdf = texto_pdf(ingreso)
        self.assertIn('(EQUIPO COMPRADO)', pdf)
        self.assertIn('DETALLE DEL PAGO', pdf)
        self.assertIn('$ 30.00', pdf)
        self.assertIn('Parte 1:', pdf)
        self.assertIn('$ 10.00', pdf)
        self.assertIn('Banco Guayaquil', pdf)
        self.assertIn('EGRESO REGISTRADO', pdf)

    def test_pdf_con_datos_faltantes_dice_igual_donado_o_comprado(self):
        incompleto = self.cliente_incompleto()
        donado = self.crear('donado', cliente=incompleto, modelo_serie='', serie='')
        pdf = texto_pdf(donado)
        self.assertIn('(EQUIPO DONADO)', pdf)
        self.assertIn('fue DONADO por el', pdf)
        self.assertNotIn('(Serie:) Tj', pdf)
        self.assertNotIn('(Correo:) Tj', pdf)
        self.assertNotIn('None', textos_dibujados(pdf))
        # Ningún campo queda solo con «—» (\\227 en WinAnsi).
        self.assertNotIn('| \\227 |', textos_dibujados(pdf))

        comprado = self.crear(
            'equipo_a_comprar', cliente=incompleto, modelo_serie='', serie='',
            valor_acordado=None,
        )
        pdf = texto_pdf(comprado)
        self.assertIn('(EQUIPO COMPRADO)', pdf)
        self.assertIn('COMPR', pdf)
        self.assertIn('Sin registrar', pdf)
        self.assertNotIn('None', textos_dibujados(pdf))

    def test_descarga_desde_la_url(self):
        for estado, nombre in (('donado', 'equipo_donado'), ('equipo_a_comprar', 'equipo_comprado')):
            with self.subTest(estado=estado):
                ingreso = self.crear(estado)
                respuesta = self.client.get(
                    reverse('econotec:equipo_administrativo_pdf', kwargs={'pk': ingreso.pk})
                )
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(respuesta['Content-Type'], 'application/pdf')
                self.assertIn(f'{nombre}_{ingreso.codigo_equipo}.pdf', respuesta['Content-Disposition'])
                self.assertTrue(respuesta.content.startswith(b'%PDF'))

    def test_otro_estado_da_404_y_tecnico_no_puede_descargar(self):
        otro = self.crear('en_reparacion')
        respuesta = self.client.get(reverse('econotec:equipo_administrativo_pdf', kwargs={'pk': otro.pk}))
        self.assertEqual(respuesta.status_code, 404)

        tecnico = get_user_model().objects.create_user(username='yandri')
        tecnico.groups.add(Group.objects.create(name='Tecnicos'))
        self.client.force_login(tecnico)
        donado = self.crear('donado')
        respuesta = self.client.get(reverse('econotec:equipo_administrativo_pdf', kwargs={'pk': donado.pk}))
        self.assertEqual(respuesta.status_code, 302)


class BandejaBotonesTests(AvisoDonadosCompradosBase):
    def test_tarjetas_muestran_pdf_y_whatsapp(self):
        donado = self.crear('donado')
        comprado = self.crear('equipo_a_comprar')
        respuesta = self.client.get(reverse('econotec:admin_equipos_administrativos'))
        for ingreso in (donado, comprado):
            self.assertContains(
                respuesta, reverse('econotec:equipo_administrativo_pdf', kwargs={'pk': ingreso.pk})
            )
        self.assertContains(respuesta, '💬 Enviar WhatsApp', count=2)
        self.assertContains(respuesta, 'https://wa.me/593991234567', count=2)

    def test_chatarrizado_que_era_donado_conserva_los_botones(self):
        donado = self.crear('donado', fecha_chatarrizacion=FECHA)
        respuesta = self.client.get(reverse('econotec:admin_equipos_administrativos'))
        self.assertContains(respuesta, 'Chatarrizado')
        self.assertContains(
            respuesta, reverse('econotec:equipo_administrativo_pdf', kwargs={'pk': donado.pk})
        )
        self.assertContains(respuesta, '💬 Enviar WhatsApp')

    def test_cliente_sin_whatsapp_solo_tiene_pdf(self):
        sin_tel = Cliente.objects.create(cedula='0911111111', nombres='Sin Tel')
        self.crear('donado', cliente=sin_tel)
        respuesta = self.client.get(reverse('econotec:admin_equipos_administrativos'))
        self.assertContains(respuesta, '📄 Descargar PDF')
        self.assertNotContains(respuesta, '💬 Enviar WhatsApp')
        self.assertContains(respuesta, 'Sin WhatsApp registrado')

    def test_vista_general_de_tecnicos_no_muestra_los_botones(self):
        self.crear('donado')
        tecnico = get_user_model().objects.create_user(username='yandri')
        tecnico.groups.add(Group.objects.create(name='Tecnicos'))
        self.client.force_login(tecnico)
        respuesta = self.client.get(reverse('econotec:equipos_administrativos_general'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotContains(respuesta, '📄 Descargar PDF')
        self.assertNotContains(respuesta, '💬 Enviar WhatsApp')
