"""Correo al cliente cuando su equipo pasa de diagnóstico a «En reparación»."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Cliente, IngresoEquipo, SalidaEquipo


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', EQUIPO_EMAIL_ADJUNTAR_PDF=True)
class CorreoEnReparacionTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username='jefe', email='jefe@example.com',
                                                               password='x')
        self.cliente = Cliente.objects.create(cedula='0912345678', nombres='Luis Mora', correo='luis@example.com')

    def ingreso(self, **datos):
        base = {
            'sede': 'guayaquil', 'asesor_comercial': 'K', 'fecha_ingreso': timezone.localdate(),
            'cliente': self.cliente, 'tipo_equipo': 'laptop', 'marca': 'HP', 'modelo_serie': 'X',
            'accesorios_entregados': '-', 'problema_reportado': '-', 'valor_acordado': Decimal('60.00'),
            'estado': 'ingresado',
        }
        base.update(datos)
        with self.captureOnCommitCallbacks(execute=True):
            return IngresoEquipo.objects.create(**base)

    def cambiar(self, ingreso, estado, **datos):
        ingreso.estado = estado
        for campo, valor in datos.items():
            setattr(ingreso, campo, valor)
        with self.captureOnCommitCallbacks(execute=True):
            ingreso.save()

    def test_avisa_al_pasar_de_diagnostico_a_reparacion(self):
        ingreso = self.ingreso()
        mail.outbox.clear()
        self.cambiar(ingreso, 'en_reparacion', subestado_reparacion='en_reparacion')

        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, ['luis@example.com'])
        self.assertEqual(correo.subject, f'Tu equipo {ingreso.codigo_equipo} está en reparación | Econotec')
        self.assertIn('Tu equipo está en reparación', correo.alternatives[0][0])
        self.assertIn('comenzó la reparación', correo.body)
        self.assertEqual(correo.attachments[0][0], f'Hoja_equipo_{ingreso.codigo_equipo}.pdf')

    def test_no_avisa_en_otros_cambios(self):
        ingreso = self.ingreso(estado='en_reparacion', subestado_reparacion='en_reparacion')
        mail.outbox.clear()
        # Cambiar el detalle dentro de reparación.
        self.cambiar(ingreso, 'en_reparacion', subestado_reparacion='espera_repuesto')
        # Guardar otros campos sin tocar el estado.
        ingreso.problema_reportado = 'Pantalla'
        with self.captureOnCommitCallbacks(execute=True):
            ingreso.save(update_fields=['problema_reportado'])
        # Garantía → reparación no es «de diagnóstico a reparación».
        self.cambiar(ingreso, 'garantia')
        self.cambiar(ingreso, 'en_reparacion')
        self.assertEqual(mail.outbox, [])

    def test_no_avisa_al_eliminar_una_finalizacion(self):
        ingreso = self.ingreso()
        self.cambiar(ingreso, 'en_reparacion')
        salida = SalidaEquipo.objects.create(
            ingreso=ingreso, fecha_salida=timezone.localdate(), estado_reparacion='pendiente_retiro',
            valor_final_cobrado=Decimal('0.00'), metodo_pago_final='sin_pago',
        )
        mail.outbox.clear()
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('econotec:salida_eliminar', args=[salida.pk]))
        ingreso.refresh_from_db()
        self.assertEqual(ingreso.estado, 'en_reparacion')
        self.assertEqual(mail.outbox, [])

    def test_sin_correo_ventas_o_apagado_no_avisa(self):
        sin_correo = Cliente.objects.create(cedula='0911111111', nombres='Ana Ruiz')
        uno = self.ingreso(cliente=sin_correo)
        dos = self.ingreso(sede='ventas')
        tres = self.ingreso()
        mail.outbox.clear()
        self.cambiar(uno, 'en_reparacion')
        self.cambiar(dos, 'en_reparacion')
        with self.settings(REPARACION_EMAIL_AUTOMATICO=False):
            self.cambiar(tres, 'en_reparacion')
        self.assertEqual(mail.outbox, [])

    def test_registrar_directo_en_reparacion_no_duplica_el_correo_de_ingreso(self):
        self.ingreso(estado='en_reparacion')
        self.assertEqual(mail.outbox, [])
