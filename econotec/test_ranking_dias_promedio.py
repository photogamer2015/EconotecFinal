"""Ranking de Técnicos: días promedio desde el ingreso hasta la finalización."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Cliente, IngresoEquipo, SalidaEquipo


class RankingDiasPromedioTests(TestCase):
    def setUp(self):
        User = get_user_model()
        tecnicos = Group.objects.create(name='Tecnicos')
        self.admin = User.objects.create_superuser(username='jefe', email='jefe@example.com', password='x')
        self.ana = User.objects.create_user(username='ana', first_name='Ana')
        self.ana.groups.add(tecnicos)
        self.beto = User.objects.create_user(username='beto', first_name='Beto')
        self.beto.groups.add(tecnicos)
        self.cliente = Cliente.objects.create(cedula='0912345678', nombres='Luis Mora')
        self.hoy = timezone.localdate()

    def finalizado(self, tecnico, dias, **datos):
        ingreso = IngresoEquipo.objects.create(
            sede='guayaquil', asesor_comercial='K', fecha_ingreso=self.hoy - timedelta(days=dias),
            cliente=self.cliente, tipo_equipo='laptop', marca='HP', modelo_serie='X', accesorios_entregados='-',
            problema_reportado='-', valor_acordado=Decimal('10.00'), estado='ingresado',
        )
        return SalidaEquipo.objects.create(
            ingreso=ingreso, fecha_salida=self.hoy, estado_reparacion='pendiente_retiro', tecnico_reparo=tecnico,
            valor_final_cobrado=Decimal('0.00'), metodo_pago_final='sin_pago', **datos,
        )

    def ranking(self, usuario):
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse('econotec:salida_totales'))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def fila(self, respuesta, usuario):
        return next(f for f in respuesta.context['ranking'] if f['tecnico_id'] == usuario.pk)

    def test_promedio_por_tecnico_y_global(self):
        self.finalizado(self.ana, 2)
        self.finalizado(self.ana, 5)
        self.finalizado(self.beto, 10)
        respuesta = self.ranking(self.admin)

        self.assertEqual(self.fila(respuesta, self.ana)['dias_promedio'], 3.5)
        self.assertEqual(self.fila(respuesta, self.beto)['dias_promedio'], 10.0)
        self.assertEqual(respuesta.context['dias_promedio_global'], 5.7)
        self.assertContains(respuesta, '⏱️ Días promedio')
        self.assertContains(respuesta, '<span class="kpi-value">3,5</span>', html=False)

    def test_tecnico_tambien_lo_ve(self):
        self.finalizado(self.ana, 4)
        respuesta = self.ranking(self.ana)
        self.assertContains(respuesta, '⏱️ Días promedio hasta finalizar')
        self.assertEqual(self.fila(respuesta, self.ana)['dias_promedio'], 4.0)

    def test_sin_salidas_no_hay_promedio(self):
        respuesta = self.ranking(self.admin)
        self.assertIsNone(respuesta.context['dias_promedio_global'])
