"""Pruebas de la simulación gamificada del detalle del equipo."""
import json
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import Cliente, IngresoEquipo, SalidaEquipo
from .simulacion import construir_simulacion, inferir_genero, primer_nombre


class GeneroPorNombreTests(SimpleTestCase):
    def test_nombres_frecuentes(self):
        casos = {
            'Osmar Perez': 'm',
            'Kimberly': 'f',
            'Yandri Guevara': 'm',
            'María José Loor': 'f',
            'José María Vera': 'm',
            'Nathaly Mora': 'f',
            'Raquel': 'f',
            'Isabel Cedeño': 'f',
            'Luis Andrés': 'm',
            'Yamileth': 'f',
            'Joshua': 'm',
            'Kenneth': 'm',
            'ANDRÉS ZAMBRANO': 'm',
        }
        for nombre, esperado in casos.items():
            with self.subTest(nombre=nombre):
                self.assertEqual(inferir_genero(nombre), esperado)

    def test_titulo_manda_y_valor_por_defecto(self):
        self.assertEqual(inferir_genero('Sra. Carmen Ruiz'), 'f')
        self.assertEqual(inferir_genero('Lcdo. Andrea Bocelli'), 'm')
        self.assertEqual(inferir_genero('Ing. Gabriela Paz'), 'f')
        self.assertEqual(inferir_genero('', por_defecto='f'), 'f')
        self.assertEqual(inferir_genero('...', por_defecto='m'), 'm')

    def test_primer_nombre_legible(self):
        self.assertEqual(primer_nombre('Sra. MARÍA José'), 'María')
        self.assertEqual(primer_nombre('osmar perez'), 'Osmar')
        self.assertEqual(primer_nombre('McDonald'), 'McDonald')
        self.assertEqual(primer_nombre(''), '')


class SimulacionEquipoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri')
        self.tecnico.groups.add(Group.objects.create(name='Tecnicos'))
        self.tecnica = User.objects.create_user(username='nathaly', first_name='Nathaly', last_name='Mora')
        self.cliente = Cliente.objects.create(
            cedula='0931486860', nombres='Osmar Perez', whatsapp='0958743607',
            correo='cliente@example.com', sector='norte',
        )
        self.client.force_login(self.tecnico)

    def crear_ingreso(self, **datos):
        base = {
            'sede': 'guayaquil', 'asesor_comercial': 'Kimberly', 'fecha_ingreso': date.today() - timedelta(days=3),
            'cliente': self.cliente, 'tipo_equipo': 'impresora', 'marca': 'Epson', 'modelo_serie': 'L4160',
            'problema_reportado': 'No imprime', 'valor_acordado': Decimal('38.00'),
            'abono_anticipo': Decimal('5.00'), 'anticipo_metodo': 'efectivo',
            'tecnico_encargado': self.tecnico, 'estado': 'ingresado', 'registrado_por': self.tecnico,
        }
        base.update(datos)
        return IngresoEquipo.objects.create(**base)

    def crear_salida(self, ingreso, **datos):
        base = {
            'ingreso': ingreso, 'fecha_salida': date.today(), 'estado_reparacion': 'pendiente_retiro',
            'tecnico_reparo': self.tecnica, 'valor_final_cobrado': Decimal('0.00'), 'metodo_pago_final': 'sin_pago',
        }
        base.update(datos)
        return SalidaEquipo.objects.create(**base)

    def estados(self, datos):
        return [etapa['estado'] for etapa in datos['etapas']]

    def test_equipo_en_diagnostico(self):
        datos = construir_simulacion(self.crear_ingreso())
        self.assertEqual(datos['etapa_actual'], 1)
        self.assertEqual(self.estados(datos)[:3], ['hecho', 'actual', 'pendiente'])
        self.assertEqual(datos['dias_texto'], '3 días')
        self.assertEqual(datos['dinero']['saldo'], '$33,00')
        self.assertTrue(datos['dinero']['saldo_pendiente'])
        self.assertEqual(datos['personajes']['cliente']['genero'], 'm')
        self.assertEqual(datos['personajes']['asesora']['genero'], 'f')
        self.assertEqual(datos['personajes']['asesora']['rol'], 'Asesora comercial')
        self.assertEqual(datos['xp'], 20)
        json.dumps(datos)

    def test_alertas_de_taller_y_valor_pendiente(self):
        repuesto = construir_simulacion(self.crear_ingreso(estado='en_reparacion', subestado_reparacion='espera_repuesto'))
        self.assertEqual(repuesto['etapa_actual'], 2)
        self.assertEqual(repuesto['alerta']['tipo'], 'repuesto')
        sin_valor = construir_simulacion(self.crear_ingreso(valor_acordado=None))
        self.assertEqual(sin_valor['alerta']['tipo'], 'valor')
        self.assertEqual(sin_valor['dinero']['total'], 'Pendiente')

    def test_listo_con_saldo_pendiente_marca_la_caja(self):
        ingreso = self.crear_ingreso(estado='en_reparacion')
        self.crear_salida(ingreso)
        ingreso.refresh_from_db()
        datos = construir_simulacion(ingreso)
        self.assertEqual(datos['etapa_actual'], 3)
        self.assertEqual(self.estados(datos)[3:], ['actual', 'alerta', 'pendiente'])
        self.assertEqual(datos['alerta']['tipo'], 'saldo')
        self.assertEqual(datos['personajes']['tecnico_reparo']['nombre'], 'Nathaly')
        self.assertEqual(datos['personajes']['tecnico_reparo']['rol'], 'Técnica que reparó')

    def test_equipo_retirado_completa_el_recorrido(self):
        ingreso = self.crear_ingreso(estado='en_reparacion', abono_anticipo=Decimal('38.00'))
        self.crear_salida(ingreso, fecha_retiro_real=date.today())
        ingreso.refresh_from_db()
        datos = construir_simulacion(ingreso)
        self.assertTrue(datos['retirado'])
        self.assertEqual(datos['progreso'], 100)
        self.assertEqual(set(self.estados(datos)), {'hecho'})
        self.assertTrue(all(logro['ok'] for logro in datos['logros']))
        self.assertIsNone(datos['alerta'])

    def test_retirado_con_saldo_deja_la_caja_en_alerta(self):
        ingreso = self.crear_ingreso(estado='en_reparacion')
        self.crear_salida(ingreso, fecha_retiro_real=date.today())
        ingreso.refresh_from_db()
        datos = construir_simulacion(ingreso)
        self.assertTrue(datos['retirado'])
        self.assertEqual(self.estados(datos)[4], 'alerta')
        self.assertEqual(datos['alerta']['tipo'], 'saldo')
        self.assertEqual(datos['xp'], 100)

    def test_entregado_sin_hoja_de_salida_cuenta_como_retirado(self):
        datos = construir_simulacion(self.crear_ingreso(estado='entregado', subestado_entregado='con_solucion'))
        self.assertTrue(datos['retirado'])
        pendiente = construir_simulacion(self.crear_ingreso(estado='entregado', subestado_entregado='pendiente_retiro'))
        self.assertFalse(pendiente['retirado'])
        self.assertEqual(pendiente['etapa_actual'], 3)

    def test_detalle_muestra_boton_y_datos_seguros(self):
        self.cliente.nombres = 'Osmar </script><b>Perez'
        self.cliente.save()
        ingreso = self.crear_ingreso()
        respuesta = self.client.get(reverse('econotec:ingreso_detalle', args=[ingreso.pk]))
        self.assertContains(respuesta, 'id="sim-abrir"')
        self.assertContains(respuesta, 'id="simulacion-data"')
        self.assertContains(respuesta, 'simulacion/simulacion.js')
        self.assertNotContains(respuesta, 'Osmar </script><b>Perez')

    def test_ventas_y_equipos_administrativos_no_tienen_simulacion(self):
        for datos in ({'sede': 'ventas'}, {'estado': 'donado'}):
            with self.subTest(datos=datos):
                ingreso = self.crear_ingreso(**datos)
                respuesta = self.client.get(reverse('econotec:ingreso_detalle', args=[ingreso.pk]))
                self.assertEqual(respuesta.status_code, 200)
                self.assertNotContains(respuesta, 'id="sim-abrir"')
