"""Pruebas del rol Asesora - Asistente de caja.

Tiene todo lo de la asesora y además Seguimiento de pago (con egresos) y
gestionar el inventario. Nada del Registro Administrativo.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .models import CategoriaEgreso, Cliente, Egreso, IngresoEquipo, InventarioItem, NotificacionCambioAdmin
from .permisos import (
    GRUPO_ASISTENTE_CAJA, es_admin, es_asesor, es_asistente_caja, es_tecnico, puede_gestionar_inventario,
    puede_ver_seguimiento_pago, puede_ver_valores_ranking,
)

MIERCOLES = date(2026, 10, 14)


class AsistenteCajaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='RootAdmin', email='a@example.com', password='x')
        # El grupo lo crea la migración, con el nombre que se ve en el admin de usuarios.
        self.grupo = Group.objects.get(name=GRUPO_ASISTENTE_CAJA)
        self.asistente = User.objects.create_user(username='karla', first_name='Karla', last_name='Caja')
        self.asistente.groups.add(self.grupo)
        self.asesora = User.objects.create_user(username='kimberly', first_name='Kimberly')
        self.asesora.groups.add(Group.objects.get_or_create(name='Asesores')[0])
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri')
        self.tecnico.groups.add(Group.objects.get_or_create(name='Tecnicos')[0])
        cliente = Cliente.objects.create(cedula='0912345678', nombres='María Loor')
        IngresoEquipo.objects.create(
            sede='guayaquil', fecha_ingreso=MIERCOLES, cliente=cliente, tipo_equipo='laptop', marca='HP',
            modelo_serie='Pavilion', problema_reportado='No enciende', valor_acordado=Decimal('100.00'),
            abono_anticipo=Decimal('100.00'), anticipo_metodo='efectivo', registrado_por=self.asesora,
            estado='en_reparacion', subestado_reparacion='en_reparacion',
        )
        self.categoria, _ = CategoriaEgreso.objects.get_or_create(nombre='Otros')
        self.item = InventarioItem.objects.create(
            sede='guayaquil', categoria='impresora', tipo='impresora-laser', producto='Tarjeta lógica',
            marca='Epson', modelo='L3250', estado='disponible', cantidad=5, costo=Decimal('10.00'),
            ubicacion='guayaquil_norte', registrado_por=self.admin,
        )

    def seguimiento(self, metodo='get', datos=None, **params):
        url = reverse('econotec:seguimiento_pago')
        with patch('econotec.views_pagos.timezone.localdate', return_value=MIERCOLES):
            if metodo == 'post':
                return self.client.post(f'{url}?semana={MIERCOLES.isoformat()}', datos)
            return self.client.get(url, params)

    def test_rol(self):
        self.assertTrue(es_asistente_caja(self.asistente))
        # Es una asesora más: tiene todo lo de la asesora.
        self.assertTrue(es_asesor(self.asistente))
        self.assertFalse(es_admin(self.asistente))
        self.assertFalse(es_tecnico(self.asistente))
        self.assertTrue(puede_ver_seguimiento_pago(self.asistente))
        self.assertTrue(puede_gestionar_inventario(self.asistente))
        # Como la asesora, no ve los valores del Ranking.
        self.assertFalse(puede_ver_valores_ranking(self.asistente))
        # La asesora normal no tiene Seguimiento de pago; el inventario ya lo
        # gestionan todos los roles.
        self.assertFalse(es_asistente_caja(self.asesora))
        self.assertFalse(puede_ver_seguimiento_pago(self.asesora))
        self.assertTrue(puede_gestionar_inventario(self.asesora))

    def test_ve_seguimiento_de_pago_y_su_tarjeta_en_el_inicio(self):
        self.client.force_login(self.asistente)

        response = self.seguimiento()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total'], Decimal('100.00'))
        self.assertContains(response, 'Registrar egreso</button>')
        # La asesora del egreso se propone sola: ella misma.
        self.assertEqual(response.context['form_egreso'].initial['asesora'], self.asistente.pk)
        inicio = self.client.get(reverse('econotec:bienvenida'))
        self.assertContains(inicio, f'href="{reverse("econotec:seguimiento_pago")}"')
        self.assertContains(inicio, 'Asesora - Asistente de caja')
        for url in ('seguimiento_pago_saldo', 'seguimiento_pago_equipo'):
            with self.subTest(url=url):
                params = {'fecha': MIERCOLES.isoformat()} if url.endswith('saldo') else {'sede': 'guayaquil', 'numero': '1'}
                self.assertEqual(self.client.get(reverse(f'econotec:{url}'), params).status_code, 200)

    def test_su_rol_en_el_perfil_y_la_ayuda(self):
        self.client.force_login(self.asistente)

        perfil = self.client.get(reverse('econotec:mi_perfil'))
        ayuda = self.client.get(reverse('econotec:ayuda'))

        self.assertContains(perfil, 'Asesora - Asistente de caja')
        self.assertContains(ayuda, 'Asesora - Asistente de caja')
        self.assertContains(ayuda, 'Seguimiento de pago')
        # La asesora sigue con su rol de siempre.
        self.client.force_login(self.asesora)
        self.assertContains(self.client.get(reverse('econotec:mi_perfil')), 'Asesor comercial')

    def test_registra_egresos_y_avisa_al_admin(self):
        self.client.force_login(self.asistente)

        response = self.seguimiento('post', {
            'fecha': MIERCOLES.isoformat(), 'concepto': 'Cable HDMI', 'asesora': self.asistente.pk,
            'categoria': self.categoria.pk, 'monto': '20.00', 'metodo': 'efectivo',
        })

        self.assertEqual(response.status_code, 302)
        egreso = Egreso.objects.get()
        self.assertEqual((egreso.registrado_por, egreso.asesora), (self.asistente, self.asistente))
        aviso = NotificacionCambioAdmin.objects.get()
        self.assertEqual(aviso.creado_por, self.asistente)
        self.assertEqual(aviso.usuario_nombre, 'Karla Caja')
        # El admin lo ve en su campanita.
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('econotec:bienvenida')), 'Cable HDMI')

    def test_gestiona_el_inventario(self):
        self.client.force_login(self.asistente)
        detalle = self.client.get(reverse('econotec:inventario_detalle_item', args=[self.item.codigo]))
        self.assertTrue(detalle.context['puede_gestionar_inventario'])

        self.assertEqual(self.client.get(reverse('econotec:inventario_editar', args=[self.item.codigo])).status_code, 200)
        self.client.post(reverse('econotec:inventario_editar', args=[self.item.codigo]), {
            'producto': 'Tarjeta lógica nueva', 'marca': 'Epson', 'modelo': 'L3250', 'serie': '',
            'estado': 'disponible', 'causa_no_disponible': '', 'cantidad': '5', 'costo': '12.00',
            'ubicacion': 'guayaquil_norte', 'observacion': '',
        })
        self.client.post(reverse('econotec:inventario_actualizar_cantidad', args=[self.item.codigo]), {'accion': 'sumar'})
        self.item.refresh_from_db()
        self.assertEqual((self.item.producto, self.item.costo, self.item.cantidad),
                         ('Tarjeta lógica nueva', Decimal('12.00'), 6))
        # Y puede ingresar productos nuevos.
        response = self.client.post(
            reverse('econotec:inventario_registrar', args=['guayaquil', 'impresora', 'impresora-laser']), {
                'producto': 'Rodillo', 'marca': 'Epson', 'modelo': 'L3250', 'serie': '', 'estado': 'disponible',
                'causa_no_disponible': '', 'cantidad': '2', 'costo': '3.00', 'ubicacion': 'guayaquil_norte',
                'observacion': '',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(InventarioItem.objects.filter(producto='Rodillo', registrado_por=self.asistente).exists())
        self.client.post(reverse('econotec:inventario_eliminar', args=[self.item.codigo]))
        self.assertFalse(InventarioItem.objects.filter(pk=self.item.pk).exists())

    def test_tiene_lo_de_la_asesora_y_nada_del_registro_administrativo(self):
        self.client.force_login(self.asistente)
        for url in ('pagos_lista', 'ingreso_menu'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(reverse(f'econotec:{url}')).status_code, 200)
        for url in ('admin_dashboard', 'admin_egresos_lista', 'admin_ventas_inventario'):
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(reverse(f'econotec:{url}')), reverse('econotec:bienvenida'),
                                     fetch_redirect_response=False)

    def test_la_asesora_y_el_tecnico_siguen_sin_seguimiento(self):
        for usuario in (self.asesora, self.tecnico):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)
                self.assertRedirects(self.seguimiento(), reverse('econotec:bienvenida'), fetch_redirect_response=False)
                self.assertEqual(self.seguimiento('post', {'monto': '1'}).status_code, 302)
                self.assertNotContains(
                    self.client.get(reverse('econotec:bienvenida')), f'href="{reverse("econotec:seguimiento_pago")}"',
                )
        self.assertFalse(Egreso.objects.exists())
        # El inventario ya lo gestionan todos los roles: la asesora también.
        self.client.force_login(self.asesora)
        self.client.post(reverse('econotec:inventario_actualizar_cantidad', args=[self.item.codigo]), {'accion': 'sumar'})
        self.item.refresh_from_db()
        self.assertEqual(self.item.cantidad, 6)
