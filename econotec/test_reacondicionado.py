"""Reacondicionar equipos e Inventario reacondicionado.

- Chatarrización (Bodegaje) → botón «Reacondicionar equipo» con su ventana.
- Donados y Compras → «Cambiar estado»: Chatarrizar o Reacondicionar, sin tocar
  el estado original, el valor pagado ni el egreso de la compra.
- Inventario → elegir Inventario de producto o Inventario reacondicionado.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .models import Cliente, Egreso, IngresoEquipo, InventarioItem, SalidaEquipo
from .views import _sincronizar_egreso_compra


class ReacondicionadoBase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='RootAdmin', email='a@example.com', password='x')
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri')
        self.tecnico.groups.add(Group.objects.create(name='Tecnicos'))
        self.cliente = Cliente.objects.create(cedula='0912345678', nombres='Osmar Perez')
        self.client.force_login(self.admin)

    def crear_ingreso(self, **extra):
        datos = {
            'sede': 'guayaquil',
            'fecha_ingreso': date.today() - timedelta(days=40),
            'cliente': self.cliente,
            'tipo_equipo': 'impresora',
            'marca': 'Epson',
            'modelo_serie': 'L4160',
            'serie': 'X123',
            'problema_reportado': 'No imprime',
            'registrado_por': self.admin,
            'estado': 'entregado',
        }
        datos.update(extra)
        return IngresoEquipo.objects.create(**datos)

    def crear_chatarrizado(self, **extra):
        ingreso = self.crear_ingreso(**extra)
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date.today() - timedelta(days=35),
            estado_reparacion='chatarrerizacion',
            fecha_retiro_real=date.today(),
            tecnico_reparo=self.tecnico,
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.admin,
        )
        return ingreso

    def datos_reacondicionar(self, **extra):
        datos = {
            'sede': 'guayaquil',
            'ubicacion': 'guayaquil_centro',
            'tipo_inventario': 'impresora|impresora-inyeccion',
            'marca': 'Epson',
            'modelo': 'L4160',
            'serie': 'X123',
            'observacion': 'Cabezal cambiado, probado.',
            'next': reverse('econotec:admin_activos_bodegaje'),
        }
        datos.update(extra)
        return datos


class InventarioDosLineasTests(ReacondicionadoBase):
    def test_inventario_pregunta_que_inventario_abrir(self):
        inicio = self.client.get(reverse('econotec:inventario_menu'))
        self.assertContains(inicio, 'Inventario de producto')
        self.assertContains(inicio, 'Inventario reacondicionado')
        self.assertContains(inicio, f'href="{reverse("econotec:inventario_producto")}"')
        self.assertContains(inicio, f'href="{reverse("econotec:inventario_reacondicionado")}"')

        rea = self.client.get(reverse('econotec:inventario_reacondicionado'))
        self.assertContains(rea, 'Inventario reacondicionado')
        self.assertContains(rea, 'data-sede="guayaquil"')
        self.assertContains(rea, 'data-sede="quito"')
        self.assertContains(rea, reverse('econotec:inventario_reacondicionado_categoria', kwargs={
            'sede': '__sede__', 'categoria': 'otros-equipos-materiales',
        }))

    def test_rutas_del_inventario_de_producto_no_cambian(self):
        self.assertEqual(
            reverse('econotec:inventario_tabla', kwargs={
                'sede': 'guayaquil', 'categoria': 'impresora', 'tipo': 'impresora-laser',
            }),
            '/inventario/guayaquil/impresora/impresora-laser/',
        )
        self.assertEqual(
            reverse('econotec:inventario_reacondicionado_tabla', kwargs={
                'sede': 'guayaquil', 'categoria': 'impresora', 'tipo': 'impresora-laser',
            }),
            '/inventario/reacondicionado/guayaquil/impresora/impresora-laser/',
        )

    def test_cada_inventario_muestra_solo_sus_equipos(self):
        kwargs = {'sede': 'guayaquil', 'categoria': 'impresora', 'tipo': 'impresora-laser'}
        InventarioItem.objects.create(
            sede='guayaquil', categoria='impresora', tipo='impresora-laser',
            producto='Tóner producto', marca='HP', modelo='85A', ubicacion='guayaquil_norte',
        )
        respuesta = self.client.post(
            reverse('econotec:inventario_reacondicionado_registrar', kwargs=kwargs),
            {
                'producto': 'Impresora reacondicionada', 'marca': 'HP', 'modelo': 'M404',
                'serie': '', 'estado': 'disponible', 'causa_no_disponible': '',
                'cantidad': '1', 'costo': '80.00', 'ubicacion': 'guayaquil_norte', 'observacion': '',
            },
        )
        rea = InventarioItem.objects.get(producto='Impresora reacondicionada')
        self.assertEqual(rea.linea, 'reacondicionado')
        self.assertTrue(rea.codigo.startswith('REA-GYE-'))
        self.assertRedirects(respuesta, reverse('econotec:inventario_reacondicionado_tabla', kwargs=kwargs))

        tabla_producto = self.client.get(reverse('econotec:inventario_tabla', kwargs=kwargs))
        self.assertContains(tabla_producto, 'Tóner producto')
        self.assertNotContains(tabla_producto, 'Impresora reacondicionada')

        tabla_rea = self.client.get(reverse('econotec:inventario_reacondicionado_tabla', kwargs=kwargs))
        self.assertContains(tabla_rea, 'Impresora reacondicionada')
        self.assertNotContains(tabla_rea, 'Tóner producto')
        self.assertContains(tabla_rea, 'INVENTARIO REACONDICIONADO')
        self.assertContains(tabla_rea, reverse('econotec:inventario_reacondicionado_export', kwargs=kwargs))

        detalle = self.client.get(reverse('econotec:inventario_detalle_item', kwargs={'codigo': rea.codigo}))
        self.assertContains(detalle, f'href="{reverse("econotec:inventario_reacondicionado")}"')
        self.assertContains(detalle, reverse('econotec:inventario_reacondicionado_tabla', kwargs=kwargs))

    def test_ventas_solo_ofrecen_el_inventario_de_producto(self):
        InventarioItem.objects.create(
            sede='guayaquil', categoria='impresora', tipo='impresora-laser',
            producto='Tóner producto', marca='HP', modelo='85A', ubicacion='guayaquil_norte',
        )
        InventarioItem.objects.create(
            linea='reacondicionado', sede='guayaquil', categoria='impresora', tipo='impresora-laser',
            producto='Impresora reacondicionada', marca='HP', modelo='M404', ubicacion='guayaquil_norte',
        )
        datos = self.client.get(reverse('econotec:venta_inventario_catalogo')).json()
        productos = [item['producto'] for item in datos['items']]
        self.assertIn('Tóner producto', productos)
        self.assertNotIn('Impresora reacondicionada', productos)


class ReacondicionarDesdeChatarrizacionTests(ReacondicionadoBase):
    def test_boton_y_ventana_solo_para_admin(self):
        ingreso = self.crear_chatarrizado()
        url = reverse('econotec:equipo_reacondicionar', kwargs={'pk': ingreso.pk})

        pagina = self.client.get(reverse('econotec:admin_activos_bodegaje'))
        self.assertContains(pagina, '🔧 Reacondicionar equipo')
        self.assertContains(pagina, f'data-rea-url="{url}"')
        self.assertContains(pagina, 'id="rea-modal"')

        self.client.force_login(self.tecnico)
        pagina = self.client.get(reverse('econotec:admin_activos_bodegaje'))
        self.assertContains(pagina, ingreso.codigo_equipo)
        self.assertNotContains(pagina, f'data-rea-url="{url}"')
        self.assertNotContains(pagina, 'id="rea-modal"')

        respuesta = self.client.post(url, self.datos_reacondicionar())
        self.assertRedirects(respuesta, reverse('econotec:bienvenida'), fetch_redirect_response=False)
        self.assertFalse(InventarioItem.objects.exists())

    def test_reacondicionar_crea_la_ficha_y_marca_la_fila(self):
        ingreso = self.crear_chatarrizado()
        url = reverse('econotec:equipo_reacondicionar', kwargs={'pk': ingreso.pk})

        respuesta = self.client.post(url, self.datos_reacondicionar())
        self.assertRedirects(respuesta, reverse('econotec:admin_activos_bodegaje'))

        item = InventarioItem.objects.get()
        self.assertEqual(item.linea, 'reacondicionado')
        self.assertEqual(item.ingreso_origen, ingreso)
        self.assertEqual((item.sede, item.ubicacion), ('guayaquil', 'guayaquil_centro'))
        self.assertEqual((item.categoria, item.tipo), ('impresora', 'impresora-inyeccion'))
        self.assertEqual((item.marca, item.modelo, item.serie), ('Epson', 'L4160', 'X123'))
        self.assertEqual(item.producto, 'Impresora Epson L4160')
        self.assertEqual(item.cantidad, 1)
        self.assertEqual(item.observacion, 'Cabezal cambiado, probado.')

        pagina = self.client.get(reverse('econotec:admin_activos_bodegaje'))
        self.assertContains(pagina, '✅ Reacondicionado')
        self.assertContains(pagina, reverse('econotec:inventario_detalle_item', kwargs={'codigo': item.codigo}))
        self.assertNotContains(pagina, f'data-rea-url="{url}"')
        self.assertEqual(pagina.context['count_chatarrerizacion'], 1)

        # No se puede reacondicionar dos veces.
        self.client.post(url, self.datos_reacondicionar())
        self.assertEqual(InventarioItem.objects.count(), 1)

    def test_valida_ubicacion_tipo_y_sede(self):
        ingreso = self.crear_chatarrizado()
        url = reverse('econotec:equipo_reacondicionar', kwargs={'pk': ingreso.pk})

        self.client.post(url, self.datos_reacondicionar(ubicacion=''))
        self.client.post(url, self.datos_reacondicionar(tipo_inventario='impresora|pc'))
        self.client.post(url, self.datos_reacondicionar(sede='ventas'))
        self.client.post(url, self.datos_reacondicionar(marca='  '))
        self.assertFalse(InventarioItem.objects.exists())

        # Quito tiene una sola ubicación: se pone sola.
        self.client.post(url, self.datos_reacondicionar(sede='quito', ubicacion='guayaquil_norte'))
        item = InventarioItem.objects.get()
        self.assertEqual((item.sede, item.ubicacion), ('quito', 'quito'))
        self.assertTrue(item.codigo.startswith('REA-UIO-'))

    def test_no_reacondiciona_equipos_que_no_estan_chatarrizados(self):
        ingreso = self.crear_ingreso(estado='en_reparacion', subestado_reparacion='en_reparacion')
        self.client.post(
            reverse('econotec:equipo_reacondicionar', kwargs={'pk': ingreso.pk}),
            self.datos_reacondicionar(),
        )
        self.assertFalse(InventarioItem.objects.exists())


class DonadosComprasCambiarEstadoTests(ReacondicionadoBase):
    def crear_compra(self):
        compra = self.crear_ingreso(
            estado='equipo_a_comprar',
            tipo_equipo='laptop',
            marca='Lenovo',
            modelo_serie='ThinkPad',
            valor_acordado=Decimal('30.00'),
            compra_metodo_pago='efectivo',
        )
        _sincronizar_egreso_compra(compra, self.admin)
        return compra

    def test_lista_admin_muestra_cambiar_estado(self):
        donado = self.crear_ingreso(estado='donado')
        pagina = self.client.get(reverse('econotec:admin_equipos_administrativos'))
        self.assertContains(pagina, '🔄 Cambiar estado')
        self.assertContains(pagina, reverse('econotec:equipo_administrativo_chatarrizar', kwargs={'pk': donado.pk}))
        self.assertContains(pagina, 'id="rea-modal"')

        self.client.force_login(self.tecnico)
        general = self.client.get(reverse('econotec:equipos_administrativos_general'))
        self.assertContains(general, donado.codigo_equipo)
        self.assertNotContains(general, '🔄 Cambiar estado')

    def test_chatarrizar_compra_no_toca_estado_ni_egreso(self):
        compra = self.crear_compra()
        egreso = Egreso.objects.get(ingreso_compra=compra)

        respuesta = self.client.post(
            reverse('econotec:equipo_administrativo_chatarrizar', kwargs={'pk': compra.pk}),
            {'next': reverse('econotec:admin_equipos_administrativos')},
        )
        self.assertRedirects(respuesta, reverse('econotec:admin_equipos_administrativos'))

        compra.refresh_from_db()
        self.assertEqual(compra.estado, 'equipo_a_comprar')
        self.assertEqual(compra.valor_acordado, Decimal('30.00'))
        self.assertIsNotNone(compra.fecha_chatarrizacion)
        egreso.refresh_from_db()
        self.assertEqual(egreso.monto, Decimal('30.00'))
        self.assertEqual(egreso.ingreso_compra_id, compra.pk)

        lista = self.client.get(reverse('econotec:admin_equipos_administrativos'))
        self.assertContains(lista, '♻️ Chatarrizado')
        self.assertContains(lista, 'Era: Equipo a comprar')
        self.assertContains(lista, 'data-chatarrizado="si"')
        self.assertEqual(lista.context['resumen']['compras'], 1)

        # Aparece en «Equipos en Chatarrización» y desde ahí se puede reacondicionar.
        bodegaje = self.client.get(reverse('econotec:admin_activos_bodegaje'))
        self.assertContains(bodegaje, 'Equipo comprado')
        self.assertContains(bodegaje, reverse('econotec:equipo_reacondicionar', kwargs={'pk': compra.pk}))

        # Chatarrizar dos veces no cambia nada.
        fecha = compra.fecha_chatarrizacion
        self.client.post(reverse('econotec:equipo_administrativo_chatarrizar', kwargs={'pk': compra.pk}))
        compra.refresh_from_db()
        self.assertEqual(compra.fecha_chatarrizacion, fecha)

    def test_reacondicionar_donado_directo(self):
        donado = self.crear_ingreso(estado='donado', tipo_equipo='celular', marca='Samsung', modelo_serie='A10')
        self.client.post(
            reverse('econotec:equipo_reacondicionar', kwargs={'pk': donado.pk}),
            self.datos_reacondicionar(
                tipo_inventario='celular|celular', marca='Samsung', modelo='A10',
                next=reverse('econotec:admin_equipos_administrativos'),
            ),
        )
        item = InventarioItem.objects.get(ingreso_origen=donado)
        self.assertEqual((item.categoria, item.tipo, item.linea), ('celular', 'celular', 'reacondicionado'))
        donado.refresh_from_db()
        self.assertEqual(donado.estado, 'donado')

        lista = self.client.get(reverse('econotec:admin_equipos_administrativos'))
        self.assertContains(lista, '🔧 Reacondicionado')
        self.assertContains(lista, 'Era: Donado')
        self.assertNotContains(lista, '🔄 Cambiar estado')

    def test_solo_admin_puede_chatarrizar(self):
        donado = self.crear_ingreso(estado='donado')
        self.client.force_login(self.tecnico)
        self.client.post(reverse('econotec:equipo_administrativo_chatarrizar', kwargs={'pk': donado.pk}))
        donado.refresh_from_db()
        self.assertIsNone(donado.fecha_chatarrizacion)

    def test_no_chatarriza_equipos_de_reparacion(self):
        ingreso = self.crear_ingreso(estado='en_reparacion', subestado_reparacion='en_reparacion')
        self.client.post(reverse('econotec:equipo_administrativo_chatarrizar', kwargs={'pk': ingreso.pk}))
        ingreso.refresh_from_db()
        self.assertIsNone(ingreso.fecha_chatarrizacion)
