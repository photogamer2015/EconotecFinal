"""Pruebas del Ranking del administrador: dinero, bodegaje, cuadres y Caja."""
import re
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

import openpyxl
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .caja import caja_del_periodo, cuadres_del_periodo, movimientos_de_dinero
from .models import Abono, CategoriaEgreso, Cliente, Egreso, IngresoEquipo, SalidaEquipo
from .views import ranking_con_dinero
from .views_admin import _ingresos_dinero_mes

URL = 'econotec:salida_totales'
URL_REPORTE = 'econotec:admin_export_reporte'
OCTUBRE = {'periodo': 'mes', 'mes': '10', 'mes_anio': '2026'}
AGOSTO = {'periodo': 'mes', 'mes': '8', 'mes_anio': '2026'}
TODOS_LOS_FILTROS = (
    ('mes', OCTUBRE),
    ('varios meses', {'periodo': 'meses', 'inicio_mes': '8', 'inicio_anio': '2026', 'cantidad_meses': '3'}),
    ('año', {'periodo': 'anio', 'anio': '2026'}),
    ('rango', {'periodo': 'rango', 'desde': '2026-08-15', 'hasta': '2026-10-20'}),
    ('todo el historial', {'periodo': 'rango', 'desde': '', 'hasta': ''}),
)


class RankingAdminBase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username='RootAdmin', email='admin@example.com', password='x',
        )
        tecnicos, _ = Group.objects.get_or_create(name='Tecnicos')
        asesores, _ = Group.objects.get_or_create(name='Asesores')
        self.tecnico = User.objects.create_user(username='Yandri', first_name='Yandri')
        self.tecnico.groups.add(tecnicos)
        self.otro_tecnico = User.objects.create_user(username='Mario', first_name='Mario')
        self.otro_tecnico.groups.add(tecnicos)
        self.asesora = User.objects.create_user(username='Kimberly', first_name='Kimberly')
        self.asesora.groups.add(asesores)
        self.superusuario_tecnico = User.objects.create_superuser(
            username='TecRoot', email='tec@example.com', password='x',
        )
        self.superusuario_tecnico.groups.add(tecnicos)
        self.cliente = Cliente.objects.create(
            cedula='0912345678', nombres='Cliente Prueba', whatsapp='0999999999',
        )

    def ingreso(self, fecha=date(2026, 10, 5), sede='guayaquil', **extra):
        datos = {
            'sede': sede,
            'asesor_comercial': 'Kimberly',
            'fecha_ingreso': fecha,
            'cliente': self.cliente,
            'tipo_equipo': 'laptop',
            'marca': 'HP',
            'modelo_serie': 'Elitebook',
            'accesorios_entregados': '',
            'problema_reportado': 'No enciende',
            'valor_acordado': Decimal('50.00'),
            'tecnico_encargado': self.otro_tecnico,
            'estado': 'en_reparacion',
            'subestado_reparacion': 'en_reparacion',
            'registrado_por': self.admin,
        }
        datos.update(extra)
        return IngresoEquipo.objects.create(**datos)

    def salida(self, ingreso, fecha=date(2026, 10, 10), estado='pendiente_retiro', tecnico=None, **extra):
        return SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=fecha,
            estado_reparacion=estado,
            tecnico_reparo=tecnico or self.tecnico,
            valor_final_cobrado=extra.pop('valor_final_cobrado', Decimal('0.00')),
            metodo_pago_final='efectivo',
            registrado_por=self.admin,
            **extra,
        )

    def abono(self, ingreso, monto, fecha=date(2026, 10, 12), **extra):
        return Abono.objects.create(
            ingreso=ingreso, fecha=fecha, monto=Decimal(monto), registrado_por=self.admin, **extra,
        )

    def egreso(self, monto, fecha=date(2026, 10, 15)):
        categoria, _ = CategoriaEgreso.objects.get_or_create(nombre='Repuestos')
        return Egreso.objects.create(fecha=fecha, categoria=categoria, concepto='Gasto', monto=Decimal(monto))

    def ver(self, usuario=None, **parametros):
        self.client.force_login(usuario or self.admin)
        respuesta = self.client.get(reverse(URL), parametros or OCTUBRE)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def fila(self, respuesta, tecnico=None):
        tecnico = tecnico or self.tecnico
        return next(f for f in respuesta.context['ranking'] if f['tecnico_id'] == tecnico.pk)

    def caja(self, respuesta):
        filtros = respuesta.context['filtros']
        return caja_del_periodo(filtros['desde'], filtros['hasta'])

    def cuadres(self, respuesta):
        filtros = respuesta.context['filtros']
        registros, _filas, resumen = ranking_con_dinero(filtros['desde'], filtros['hasta'])
        movimientos = movimientos_de_dinero()
        return cuadres_del_periodo(
            filtros['desde'], filtros['hasta'], registros, resumen,
            caja_del_periodo(filtros['desde'], filtros['hasta'], movimientos),
            movimientos,
        )

    def cuadres_con_problema(self, respuesta):
        return [c for c in self.cuadres(respuesta) if c['estado'] == 'diferencia']


class VistaDeOtrosRolesTests(RankingAdminBase):
    """Técnicos y asesoras siguen viendo el ranking sin ningún cobro."""

    def preparar_datos(self):
        ingreso = self.ingreso(valor_acordado=Decimal('987.65'), abono_anticipo=Decimal('123.45'))
        self.salida(ingreso)
        self.abono(ingreso, '111.11')
        self.egreso('77.77')

    def test_otros_roles_no_ven_dinero_ni_caja_ni_cuadre(self):
        self.preparar_datos()
        for usuario in (self.tecnico, self.asesora, self.superusuario_tecnico):
            with self.subTest(usuario=usuario.username):
                respuesta = self.ver(usuario, **OCTUBRE)
                self.assertFalse(respuesta.context['mostrar_valores_monetarios'])
                for clave in ('caja', 'cuadres', 'cuadres_con_diferencia'):
                    self.assertNotIn(clave, respuesta.context)
                fila = self.fila(respuesta)
                self.assertNotIn('equipos', fila)
                self.assertNotIn('total_bodegaje_cobrado', fila)
                for texto in (
                    'Cuadre con Pagos', 'id="caja"', 'Guardado en caja', 'Ver Caja',
                    'Bodegaje cobrado', 'Bodegaje sin cobrar', 'Total a cobrar',
                    'caja-fuerte', 'equipos-tecnico', '$987,65', '$123,45', '$111,11', '$77,77',
                ):
                    self.assertNotContains(respuesta, texto)

    def test_la_pagina_de_otros_roles_no_cambia_con_los_pagos(self):
        ingreso = self.ingreso()
        salida = self.salida(ingreso)

        def pagina(usuario):
            html = self.ver(usuario, **OCTUBRE).content.decode()
            # El token CSRF cambia en cada respuesta; lo demás debe ser idéntico.
            return re.sub(r'\b[A-Za-z0-9]{40,}\b', '', html)

        antes = {usuario.pk: pagina(usuario) for usuario in (self.tecnico, self.asesora)}
        self.abono(ingreso, '50.00', bodegaje_decision='si', bodegaje_monto_aplicado=Decimal('3.00'))
        self.egreso('20.00')
        salida.refresh_from_db()
        for usuario in (self.tecnico, self.asesora):
            with self.subTest(usuario=usuario.username):
                self.assertEqual(pagina(usuario), antes[usuario.pk])

    def test_solo_el_superusuario_puro_ve_la_caja(self):
        self.preparar_datos()
        respuesta = self.ver()
        self.assertContains(respuesta, 'Ver Caja')
        self.assertNotContains(respuesta, 'Cuadre con Pagos')
        self.assertNotContains(respuesta, 'Cuadra con Pagos')


class DineroDelAdminTests(RankingAdminBase):
    def test_tarjetas_iguales_a_pagos_con_anticipo_y_domicilio(self):
        """El caso de la captura: G1037 y G1032 ya no dan $130 y $130."""
        con_anticipo = self.ingreso(
            valor_acordado=Decimal('90.00'), abono_anticipo=Decimal('5.00'),
            a_domicilio='si', valor_domicilio=Decimal('10.00'),
        )
        self.salida(con_anticipo)
        en_prueba = self.ingreso(
            valor_acordado=Decimal('40.00'),
            a_domicilio='si', valor_domicilio=Decimal('10.00'),
        )
        self.salida(en_prueba, estado='revision', subestado_revision='equipo_prueba')
        for valor in ('60.00', '70.00'):
            pagado = self.ingreso(valor_acordado=Decimal(valor))
            self.salida(pagado, estado='retirado', fecha_retiro_real=date(2026, 10, 19))
            self.abono(pagado, valor, fecha=date(2026, 10, 19))

        respuesta = self.ver()

        resumen = respuesta.context['resumen_salidas']
        self.assertEqual(resumen['total_acordado'], Decimal('260.00'))
        self.assertEqual(resumen['total_domicilio'], Decimal('20.00'))
        self.assertEqual(resumen['total_a_cobrar'], Decimal('280.00'))
        self.assertEqual(resumen['total_recaudado'], Decimal('135.00'))
        self.assertEqual(resumen['total_por_cobrar'], Decimal('145.00'))
        self.assertEqual(resumen['total_a_favor'], Decimal('0.00'))
        self.assertEqual(self.cuadres_con_problema(respuesta), [])
        self.assertContains(respuesta, '$145,00')

    def test_revision_sin_valor_acordado_y_registro_antiguo(self):
        """Revisión — No se pudo reparar: el acordado queda en $0, se cobra adicional + envío − lo pagado."""
        antiguo = self.ingreso(
            fecha=date(2026, 7, 1),
            valor_acordado=Decimal('80.00'), abono_anticipo=Decimal('5.00'),
            a_domicilio='si', valor_domicilio=Decimal('10.00'),
        )
        self.salida(
            antiguo, fecha=date(2026, 7, 2), estado='revision', subestado_revision='no_reparable',
            aplica_valor_acordado_adicional='si', valor_acordado_adicional=Decimal('15.00'),
        )

        respuesta = self.ver(periodo='mes', mes='7', mes_anio='2026')

        fila = self.fila(respuesta)
        self.assertEqual(fila['total_acordado'], Decimal('15.00'))
        self.assertEqual(fila['total_domicilio'], Decimal('10.00'))
        self.assertEqual(fila['total_recaudado'], Decimal('5.00'))
        self.assertEqual(fila['total_por_cobrar'], Decimal('20.00'))
        antiguo.refresh_from_db()
        self.assertEqual(fila['total_por_cobrar'], antiguo.diferencia)

    def test_pago_de_mas_no_infla_el_porcentaje_recaudado(self):
        sin_pagar = self.ingreso(valor_acordado=Decimal('100.00'))
        self.salida(sin_pagar)
        pago_de_mas = self.ingreso(valor_acordado=Decimal('100.00'))
        self.salida(pago_de_mas)
        self.abono(pago_de_mas, '200.00')

        fila = self.fila(self.ver())

        self.assertEqual(fila['total_recaudado'], Decimal('200.00'))
        self.assertEqual(fila['total_por_cobrar'], Decimal('100.00'))
        self.assertEqual(fila['total_a_favor'], Decimal('100.00'))
        self.assertEqual(fila['porcentaje_recaudado'], 50.0)

    def test_pago_de_mas_queda_como_saldo_a_favor(self):
        garantia = self.ingreso(valor_acordado=Decimal('0.00'))
        self.salida(garantia, estado='garantia')
        self.abono(garantia, '20.00')

        respuesta = self.ver()

        fila = self.fila(respuesta)
        self.assertEqual(fila['total_por_cobrar'], Decimal('0.00'))
        self.assertEqual(fila['total_a_favor'], Decimal('20.00'))
        self.assertEqual(fila['total_recaudado'], Decimal('20.00'))
        avisos = [c for c in self.cuadres(respuesta) if c['titulo'] == 'Clientes con saldo a favor']
        self.assertEqual(avisos[0]['estado'], 'aviso')
        self.assertEqual(avisos[0]['diferencia'], Decimal('20.00'))
        self.assertContains(respuesta, 'A favor $20,00')


class BodegajeComoPlusTests(RankingAdminBase):
    def preparar_equipo(self):
        ingreso = self.ingreso(valor_acordado=Decimal('50.00'))
        salida = self.salida(ingreso)
        self.abono(ingreso, '50.00')
        return ingreso, salida

    def valores_de_ranking(self):
        fila = self.fila(self.ver())
        return {clave: fila[clave] for clave in (
            'total_acordado', 'total_recaudado', 'total_por_cobrar',
            'efectividad', 'puntos', 'salidas_positivas', 'total_a_favor',
        )}

    def test_cobrar_bodegaje_suma_aparte_sin_danar_los_valores(self):
        ingreso, _salida = self.preparar_equipo()
        antes = self.valores_de_ranking()
        entro_antes = self.caja(self.ver())['entro']

        self.abono(ingreso, '8.00', bodegaje_decision='si', bodegaje_monto_aplicado=Decimal('8.00'))

        self.assertEqual(self.valores_de_ranking(), antes)
        respuesta = self.ver()
        self.assertEqual(self.fila(respuesta)['total_bodegaje_cobrado'], Decimal('8.00'))
        caja = self.caja(respuesta)
        self.assertEqual(caja['bodegaje'], Decimal('8.00'))
        self.assertEqual(caja['reparaciones'], Decimal('50.00'))
        self.assertEqual(caja['entro'], entro_antes + Decimal('8.00'))
        self.assertEqual(self.cuadres_con_problema(respuesta), [])

    def test_bodegaje_sin_cobrar_solo_se_muestra(self):
        hoy = timezone.localdate()
        fecha = hoy - timedelta(days=10)
        ingreso = self.ingreso(fecha=fecha, valor_acordado=Decimal('50.00'))
        self.salida(ingreso, fecha=fecha)
        self.abono(ingreso, '50.00', fecha=fecha)
        parametros = {'periodo': 'rango', 'desde': fecha.isoformat(), 'hasta': hoy.isoformat()}

        respuesta = self.ver(**parametros)

        fila = self.fila(respuesta)
        self.assertEqual(fila['total_bodegaje_pendiente'], ingreso.bodegaje_pendiente)
        self.assertGreater(fila['total_bodegaje_pendiente'], Decimal('0.00'))
        self.assertEqual(fila['total_recaudado'], Decimal('50.00'))
        self.assertEqual(fila['total_por_cobrar'], Decimal('0.00'))
        self.assertEqual(self.caja(respuesta)['bodegaje'], Decimal('0.00'))
        self.assertEqual(self.caja(respuesta)['entro'], Decimal('50.00'))
        self.assertEqual(fila['equipos'][0]['bodegaje_estado'], 'pendiente')

    def test_bodegaje_perdonado_al_retirar_no_entra_a_la_caja(self):
        ingreso, salida = self.preparar_equipo()
        salida.fecha_retiro_real = date(2026, 10, 20)
        salida.estado_reparacion = 'retirado'
        salida.bodegaje_dias_congelado = 6
        salida.bodegaje_monto_congelado = Decimal('6.00')
        salida.bodegaje_aplicado_al_pago = False
        salida.save()

        respuesta = self.ver()

        fila = self.fila(respuesta)
        self.assertEqual(fila['total_bodegaje_perdonado'], Decimal('6.00'))
        self.assertEqual(fila['total_bodegaje_cobrado'], Decimal('0.00'))
        self.assertEqual(fila['equipos'][0]['bodegaje_estado'], 'perdonado')
        self.assertEqual(self.caja(respuesta)['entro'], Decimal('50.00'))
        self.assertEqual(self.cuadres_con_problema(respuesta), [])

    def test_bodegaje_va_a_nombre_del_tecnico_que_finalizo(self):
        ingreso = self.ingreso(tecnico_encargado=self.otro_tecnico)
        self.salida(ingreso, tecnico=self.tecnico)
        self.abono(ingreso, '50.00')
        self.abono(ingreso, '4.00', bodegaje_decision='si', bodegaje_monto_aplicado=Decimal('4.00'))

        respuesta = self.ver()

        fila = self.fila(respuesta)
        self.assertEqual(fila['total_bodegaje_cobrado'], Decimal('4.00'))
        self.assertEqual(fila['equipos'][0]['bodegaje_cobrado'], Decimal('4.00'))
        self.assertEqual(fila['equipos'][0]['codigo'], ingreso.codigo_equipo)
        self.assertNotIn(self.otro_tecnico.pk, [f['tecnico_id'] for f in respuesta.context['ranking']])

    def test_equipo_en_prueba_no_tiene_bodegaje_por_cobrar(self):
        hoy = timezone.localdate()
        fecha = hoy - timedelta(days=30)
        ingreso = self.ingreso(fecha=fecha)
        self.salida(ingreso, fecha=fecha, estado='revision', subestado_revision='equipo_prueba')
        parametros = {'periodo': 'rango', 'desde': fecha.isoformat(), 'hasta': hoy.isoformat()}

        fila = self.fila(self.ver(**parametros))

        self.assertEqual(fila['total_bodegaje_pendiente'], Decimal('0.00'))
        self.assertEqual(fila['equipos'][0]['bodegaje_estado'], 'sin')

    def test_abono_mixto_con_bodegaje_se_cuenta_una_vez(self):
        ingreso, _salida = self.preparar_equipo()
        self.abono(ingreso, '3.50', bodegaje_decision='si', bodegaje_monto_aplicado=Decimal('7.00'), metodo='efectivo')
        self.abono(ingreso, '3.50', metodo='tarjeta')

        respuesta = self.ver()

        caja = self.caja(respuesta)
        self.assertEqual(caja['bodegaje'], Decimal('7.00'))
        self.assertEqual(caja['entro'], Decimal('57.00'))
        self.assertEqual(self.fila(respuesta)['total_recaudado'], Decimal('50.00'))
        self.assertEqual(self.cuadres_con_problema(respuesta), [])


class CajaTests(RankingAdminBase):
    def preparar_historial(self):
        """Julio a octubre con cada clase de pago."""
        # Julio: anticipo y abono de una reparación, una venta y un diagnóstico.
        julio = self.ingreso(fecha=date(2026, 7, 5), valor_acordado=Decimal('100.00'), abono_anticipo=Decimal('40.00'))
        self.salida(julio, fecha=date(2026, 8, 20))
        self.abono(julio, '60.00', fecha=date(2026, 9, 3))
        self.ingreso(
            fecha=date(2026, 7, 9), sede='ventas', valor_acordado=Decimal('70.00'),
            abono_anticipo=Decimal('70.00'), estado='entregado',
        )
        self.ingreso(
            fecha=date(2026, 7, 11), valor_acordado=None, diagnostico_inmediato='si',
            valor_diagnostico=Decimal('10.00'),
        )
        self.egreso('30.00', fecha=date(2026, 7, 20))
        # Agosto: pago al finalizar.
        final = self.ingreso(fecha=date(2026, 8, 1), valor_acordado=Decimal('25.00'))
        self.salida(final, fecha=date(2026, 8, 25), valor_final_cobrado=Decimal('25.00'))
        # Octubre: abono con bodegaje.
        octubre = self.ingreso(fecha=date(2026, 10, 1), valor_acordado=Decimal('50.00'))
        self.salida(octubre, fecha=date(2026, 10, 10))
        self.abono(octubre, '50.00', fecha=date(2026, 10, 15))
        self.abono(octubre, '5.00', fecha=date(2026, 10, 16), bodegaje_decision='si', bodegaje_monto_aplicado=Decimal('5.00'))

    def test_cada_pago_cuenta_en_el_mes_de_su_fecha(self):
        self.preparar_historial()

        caja = caja_del_periodo('2026-01-01', '2026-12-31')

        self.assertEqual(
            [(m['etiqueta'], m['entro'], m['egresos'], m['guardado']) for m in caja['meses']],
            [
                ('julio 2026', Decimal('120.00'), Decimal('30.00'), Decimal('90.00')),
                ('agosto 2026', Decimal('25.00'), Decimal('0.00'), Decimal('115.00')),
                ('septiembre 2026', Decimal('60.00'), Decimal('0.00'), Decimal('175.00')),
                ('octubre 2026', Decimal('55.00'), Decimal('0.00'), Decimal('230.00')),
            ],
        )
        self.assertEqual(caja['ventas'], Decimal('70.00'))
        self.assertEqual(caja['diagnostico'], Decimal('10.00'))
        self.assertEqual(caja['bodegaje'], Decimal('5.00'))
        self.assertEqual(caja['reparaciones'], Decimal('175.00'))
        self.assertEqual(caja['entro'], Decimal('260.00'))
        self.assertEqual(caja['saldo_final'], Decimal('230.00'))

    def test_venta_pagada_no_se_cuenta_dos_veces(self):
        self.ingreso(
            sede='ventas', valor_acordado=Decimal('20.00'),
            abono_anticipo=Decimal('20.00'), estado='entregado',
        )
        caja = caja_del_periodo('2026-10-01', '2026-10-31')
        self.assertEqual(caja['ventas'], Decimal('20.00'))
        self.assertEqual(caja['entro'], Decimal('20.00'))

    def test_saldo_arrastra_entre_filtros_y_siempre_cuadra(self):
        self.preparar_historial()
        for nombre, parametros in TODOS_LOS_FILTROS:
            with self.subTest(filtro=nombre):
                caja = self.caja(self.ver(**parametros))
                self.assertEqual(caja['saldo_inicial'] + caja['entro'] - caja['egresos'], caja['saldo_final'])
                self.assertEqual(sum(m['entro'] for m in caja['meses']), caja['entro'])
                self.assertEqual(sum(m['monto'] for m in caja['metodos']), caja['entro'])
                self.assertEqual(
                    caja['reparaciones'] + caja['bodegaje'] + caja['diagnostico'] + caja['ventas'],
                    caja['entro'],
                )

    def test_los_meses_suman_el_anio(self):
        self.preparar_historial()
        guardado_anterior = Decimal('0.00')
        for mes in range(7, 11):
            caja = self.caja(self.ver(periodo='mes', mes=str(mes), mes_anio='2026'))
            self.assertEqual(caja['saldo_inicial'], guardado_anterior)
            guardado_anterior = caja['saldo_final']
        anual = self.caja(self.ver(periodo='anio', anio='2026'))
        self.assertEqual(anual['saldo_final'], guardado_anterior)

    def test_rango_a_medio_mes_se_marca_y_arrastra_lo_anterior(self):
        self.preparar_historial()
        caja = caja_del_periodo('2026-10-16', '2026-10-20')
        self.assertTrue(caja['meses'][0]['parcial'])
        self.assertEqual(caja['entro'], Decimal('5.00'))
        self.assertEqual(caja['saldo_inicial'], Decimal('225.00'))
        self.assertEqual(caja['saldo_final'], Decimal('230.00'))

    def test_corregir_un_pago_corrige_la_caja(self):
        self.preparar_historial()
        abono = Abono.objects.get(monto=Decimal('60.00'))
        abono.monto = Decimal('10.00')
        abono.save()
        self.assertEqual(caja_del_periodo('2026-09-01', '2026-09-30')['entro'], Decimal('10.00'))

    def test_periodo_sin_datos(self):
        caja = caja_del_periodo('2026-03-01', '2026-03-31')
        self.assertEqual(caja['entro'], Decimal('0.00'))
        self.assertEqual(len(caja['meses']), 1)
        self.assertEqual(caja['meses'][0]['neto'], Decimal('0.00'))
        self.assertEqual(caja_del_periodo('', '')['meses'], [])
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('econotec:admin_dashboard'), {'ano': '2026', 'mes': '3'})
        self.assertEqual(len(respuesta.context['caja']['meses']), 3)
        self.assertEqual(respuesta.context['caja']['saldo_final'], Decimal('0.00'))

    def test_metodos_separan_las_formas_de_pago(self):
        ingreso = self.ingreso()
        self.abono(ingreso, '10.00', metodo='efectivo')
        self.abono(ingreso, '15.00', metodo='transferencia', banco='pichincha')
        self.abono(ingreso, '5.00', metodo='tarjeta')
        caja = caja_del_periodo('2026-10-01', '2026-10-31')
        self.assertEqual(
            {m['clave']: m['monto'] for m in caja['metodos']},
            {'efectivo': Decimal('10.00'), 'transferencia': Decimal('15.00'), 'tarjeta': Decimal('5.00')},
        )

    def test_caja_tiene_animacion_y_numeros_reales(self):
        self.preparar_historial()
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('econotec:admin_dashboard'), {'ano': '2026', 'mes': '10'})
        self.assertContains(respuesta, 'data-final="230.00"')
        self.assertContains(respuesta, 'caja-fuerte')
        self.assertContains(respuesta, 'prefers-reduced-motion')
        self.assertContains(respuesta, 'data-guardado=', count=4)


class CuadresConPagosTests(RankingAdminBase):
    def preparar_limpio(self):
        anticipo = self.ingreso(
            fecha=date(2026, 8, 1), valor_acordado=Decimal('90.00'), abono_anticipo=Decimal('5.00'),
            a_domicilio='si', valor_domicilio=Decimal('10.00'),
        )
        self.salida(anticipo, fecha=date(2026, 9, 2))
        self.abono(anticipo, '30.00', fecha=date(2026, 10, 3))
        pagado = self.ingreso(fecha=date(2026, 10, 2), valor_acordado=Decimal('60.00'))
        self.salida(pagado, fecha=date(2026, 10, 10), estado='retirado', fecha_retiro_real=date(2026, 10, 11))
        self.abono(pagado, '60.00', fecha=date(2026, 10, 11))
        self.ingreso(fecha=date(2026, 10, 3), valor_acordado=Decimal('40.00'), abono_anticipo=Decimal('10.00'))
        self.egreso('12.00')

    def test_todo_cuadra_en_cada_filtro(self):
        self.preparar_limpio()
        for nombre, parametros in TODOS_LOS_FILTROS:
            with self.subTest(filtro=nombre):
                respuesta = self.ver(**parametros)
                self.assertEqual(self.cuadres_con_problema(respuesta), [])
                self.assertTrue(respuesta.context['todo_cuadra'])

    def test_la_caja_coincide_con_la_pantalla_de_pagos(self):
        self.preparar_limpio()
        self.ingreso(
            sede='ventas', valor_acordado=Decimal('20.00'), abono_anticipo=Decimal('20.00'), estado='entregado',
        )
        self.ingreso(valor_acordado=None, diagnostico_inmediato='si', valor_diagnostico=Decimal('10.00'))
        self.client.force_login(self.admin)

        pagos = self.client.get(reverse('econotec:pagos_lista')).context
        ventas = self.client.get(reverse('econotec:pagos_ventas_lista')).context
        caja = caja_del_periodo('', '')

        self.assertEqual(caja['reparaciones'] + caja['bodegaje'], pagos['total_pagado'])
        self.assertEqual(caja['ventas'], ventas['total_pagado'])
        self.assertEqual(caja['diagnostico'], pagos['total_diagnostico'] + ventas['total_diagnostico'])

    def test_por_cobrar_coincide_con_el_saldo_de_pagos(self):
        self.preparar_limpio()
        self.client.force_login(self.admin)
        pagos = self.client.get(reverse('econotec:pagos_lista')).context
        finalizados = IngresoEquipo.objects.filter(salida__isnull=False)

        resumen = self.ver(periodo='rango', desde='', hasta='').context['resumen_salidas']

        self.assertEqual(
            resumen['total_por_cobrar'],
            sum(ingreso.diferencia for ingreso in finalizados if ingreso.diferencia > 0),
        )
        sin_salida = IngresoEquipo.objects.filter(salida__isnull=True)
        self.assertEqual(
            pagos['total_pendiente'],
            resumen['total_por_cobrar'] - resumen['total_a_favor'] - resumen['total_bodegaje_cobrado']
            + sum(ingreso.valor_efectivo_a_cobrar - ingreso.total_abonado for ingreso in sin_salida),
        )

    def test_bodegaje_cobrado_dos_veces_se_muestra_con_recibos(self):
        """Como G1021: se deshizo y se confirmó otra vez el retiro."""
        ingreso = self.ingreso(valor_acordado=Decimal('10.00'))
        self.salida(ingreso)
        self.abono(ingreso, '10.00')
        primero = self.abono(ingreso, '7.00', bodegaje_decision='si', bodegaje_monto_aplicado=Decimal('7.00'))
        segundo = self.abono(ingreso, '7.00', bodegaje_decision='si', bodegaje_monto_aplicado=Decimal('7.00'))

        respuesta = self.ver()

        problemas = self.cuadres_con_problema(respuesta)
        self.assertEqual(len(problemas), 1)
        self.assertEqual(problemas[0]['diferencia'], Decimal('7.00'))
        self.assertIn(primero.numero_recibo, problemas[0]['causa'])
        self.assertIn(segundo.numero_recibo, problemas[0]['causa'])
        self.assertIn('$14,00', problemas[0]['causa'])
        registro = self.client.get(reverse('econotec:admin_dashboard'), {'ano': '2026', 'mes': '10'})
        self.assertEqual(registro.context['cuadres_con_diferencia'], 1)
        self.assertContains(registro, 'Revisa si se cobró dos veces')
        # El dinero real no se toca: se queda lo que de verdad se pagó.
        self.assertEqual(self.fila(respuesta)['total_bodegaje_cobrado'], Decimal('14.00'))
        self.assertEqual(self.caja(respuesta)['entro'], Decimal('24.00'))

    def test_diferencia_con_el_registro_administrativo_se_muestra(self):
        self.ingreso(sede='ventas', valor_acordado=Decimal('500.00'), abono_anticipo=Decimal('350.00'), estado='entregado')
        con_ventas_dobles = {'total': Decimal('850.00')}

        respuesta = self.ver()
        with patch('econotec.views_admin._ingresos_dinero_mes', return_value=con_ventas_dobles):
            problemas = self.cuadres_con_problema(respuesta)

        self.assertEqual(len(problemas), 1)
        self.assertEqual(problemas[0]['titulo'], 'Registro Administrativo: octubre 2026')
        self.assertEqual(problemas[0]['diferencia'], Decimal('500.00'))
        self.assertTrue(problemas[0]['causa'])
        self.assertEqual(self.caja(respuesta)['ventas'], Decimal('350.00'))

    def test_mes_parcial_no_se_compara_con_el_registro(self):
        respuesta = self.ver(periodo='rango', desde='2026-10-02', hasta='2026-10-20')
        self.assertFalse(any('Registro Administrativo' in c['titulo'] for c in self.cuadres(respuesta)))

    def test_puente_explica_pagos_de_otros_periodos(self):
        self.preparar_limpio()
        respuesta = self.ver(**AGOSTO)
        puente = next(c for c in self.cuadres(respuesta) if c['titulo'] == 'Del Ranking a la Caja')
        self.assertEqual(puente['estado'], 'ok')
        respuesta = self.ver(periodo='mes', mes='9', mes_anio='2026')
        puente = next(c for c in self.cuadres(respuesta) if c['titulo'] == 'Del Ranking a la Caja')
        self.assertEqual(puente['estado'], 'ok')
        self.assertIn('$35,00', puente['cuenta'])

    def test_movimientos_no_inventan_dinero(self):
        self.preparar_limpio()
        total = sum(m['monto'] for m in movimientos_de_dinero())
        self.assertEqual(total, sum(i.total_abonado for i in IngresoEquipo.objects.all()))

    def test_tabla_por_equipo_muestra_el_detalle_al_admin(self):
        self.preparar_limpio()
        respuesta = self.ver()
        self.assertContains(respuesta, 'con pagos y bodegaje')
        self.assertContains(respuesta, 'Cliente Prueba')
        ingreso = IngresoEquipo.objects.get(valor_acordado=Decimal('60.00'))
        self.assertContains(respuesta, reverse('econotec:ingreso_abonos', args=[ingreso.pk]))


class RegistroAdministrativoTests(RankingAdminBase):
    """El Registro cuenta el mismo dinero y la misma efectividad que la Caja y el Ranking."""

    def preparar_mes(self):
        # Venta a medio pagar: vale $200, entraron $100.
        parcial = self.ingreso(
            sede='ventas', valor_acordado=Decimal('200.00'),
            abono_anticipo=Decimal('80.00'), estado='entregado',
        )
        self.abono(parcial, '20.00')
        self.ingreso(
            sede='ventas', valor_acordado=Decimal('30.00'),
            abono_anticipo=Decimal('30.00'), estado='entregado',
        )
        taller = self.ingreso(valor_acordado=Decimal('60.00'), abono_anticipo=Decimal('10.00'))
        self.salida(taller)
        self.abono(taller, '50.00')
        self.ingreso(valor_acordado=None, diagnostico_inmediato='si', valor_diagnostico=Decimal('15.00'))
        self.egreso('5.00')

    def registro(self, **parametros):
        self.client.force_login(self.admin)
        return self.client.get(
            reverse('econotec:admin_dashboard'),
            parametros or {'ano': '2026', 'mes': '10'},
        )

    def test_las_ventas_cuentan_solo_lo_que_entro_y_una_vez(self):
        self.preparar_mes()

        dinero = _ingresos_dinero_mes(2026, 10)

        self.assertEqual(dinero['cobros_ventas'], Decimal('130.00'))
        self.assertEqual(dinero['anticipos'], Decimal('10.00'))
        self.assertEqual(dinero['abonos'], Decimal('50.00'))
        self.assertEqual(dinero['diagnosticos_rapidos'], Decimal('15.00'))
        self.assertEqual(dinero['total'], Decimal('205.00'))

    def test_el_desglose_suma_el_total_y_coincide_con_la_caja(self):
        self.preparar_mes()
        dinero = _ingresos_dinero_mes(2026, 10)
        caja = caja_del_periodo('2026-10-01', '2026-10-31')

        self.assertEqual(
            sum(valor for clave, valor in dinero.items() if clave != 'total'),
            dinero['total'],
        )
        self.assertEqual(dinero['total'], caja['entro'])
        self.assertEqual(dinero['cobros_ventas'], caja['ventas'])
        self.assertEqual(self.cuadres_con_problema(self.ver()), [])

    def test_cuando_una_venta_se_abona_en_otro_mes_cuenta_en_ese_mes(self):
        venta = self.ingreso(
            fecha=date(2026, 9, 20), sede='ventas', valor_acordado=Decimal('70.00'),
            abono_anticipo=Decimal('20.00'), estado='entregado',
        )
        self.abono(venta, '50.00', fecha=date(2026, 10, 2))

        self.assertEqual(_ingresos_dinero_mes(2026, 9)['total'], Decimal('20.00'))
        self.assertEqual(_ingresos_dinero_mes(2026, 10)['total'], Decimal('50.00'))
        self.assertEqual(_ingresos_dinero_mes(2026, 10)['cobros_ventas'], Decimal('50.00'))

    def test_pantalla_muestra_total_y_utilidad_corregidos(self):
        self.preparar_mes()

        respuesta = self.registro()

        self.assertEqual(respuesta.context['dinero_in']['total'], Decimal('205.00'))
        self.assertEqual(respuesta.context['utilidad'], Decimal('200.00'))
        self.assertContains(respuesta, 'Lo que entró por ventas')

    def test_excel_usa_el_total_corregido(self):
        self.preparar_mes()
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse(URL_REPORTE), {'ano': '2026', 'mes': '10'})

        hoja = openpyxl.load_workbook(BytesIO(respuesta.content)).active
        filas = {fila[0].value: fila[1].value for fila in hoja.iter_rows(min_row=3) if fila[0].value}
        self.assertEqual(filas['Ventas de productos'], 130.0)
        self.assertEqual(filas['TOTAL DINERO RECIBIDO'], 205.0)
        self.assertEqual(filas['UTILIDAD DEL MES'], 200.0)

    def preparar_todos_los_resultados(self):
        for estado, subestado in (
            ('pendiente_retiro', ''),
            ('retirado', ''),
            ('cliente_no_acepta', ''),
            ('no_reparable', ''),
            ('garantia', ''),
            ('garantia_fallos_adicionales', ''),
            ('revision', 'no_reparable'),
            ('revision', 'cliente_no_acepta'),
            ('revision', 'equipo_prueba'),
            ('cortesia', ''),
            ('chatarrerizacion', ''),
        ):
            self.salida(self.ingreso(), estado=estado, subestado_revision=subestado)

    def test_ya_no_muestra_la_seccion_de_equipos_finalizados(self):
        self.preparar_mes()
        respuesta = self.registro()
        self.assertNotContains(respuesta, 'id="salidas-tecnicos"')
        self.assertNotContains(respuesta, 'Recaudado al finalizar')
        self.assertNotIn('salidas_tecnicos_total', respuesta.context)
        # Sus datos siguen en el resumen del Ranking.
        self.assertEqual(respuesta.context['ranking_resumen']['num_equipos'], 1)
        self.assertEqual(respuesta.context['ranking_resumen']['total_recaudado'], Decimal('60.00'))


class ResumenRankingEnRegistroTests(RankingAdminBase):
    """El Registro Administrativo muestra la Caja y todo el Ranking de Técnicos."""

    def registro(self, usuario=None, **parametros):
        self.client.force_login(usuario or self.admin)
        return self.client.get(
            reverse('econotec:admin_dashboard'),
            {'ano': '2026', 'mes': '10', **parametros},
        )

    def preparar(self):
        pagado = self.ingreso(valor_acordado=Decimal('60.00'))
        self.salida(pagado)
        self.abono(pagado, '60.00')
        self.abono(pagado, '4.00', bodegaje_decision='si', bodegaje_monto_aplicado=Decimal('4.00'))
        debe = self.ingreso(
            valor_acordado=Decimal('90.00'), abono_anticipo=Decimal('5.00'),
            a_domicilio='si', valor_domicilio=Decimal('10.00'),
        )
        self.salida(debe, tecnico=self.otro_tecnico, estado='no_reparable')
        anterior = self.ingreso(fecha=date(2026, 8, 1), valor_acordado=Decimal('30.00'), abono_anticipo=Decimal('30.00'))
        self.salida(anterior, fecha=date(2026, 8, 10))
        self.egreso('7.00')

    def test_cifras_iguales_al_ranking_en_cada_alcance(self):
        self.preparar()
        for alcance, parametros in (
            ('mes', OCTUBRE),
            ('anio', {'periodo': 'anio', 'anio': '2026'}),
            ('todo', {'periodo': 'rango', 'desde': '', 'hasta': ''}),
        ):
            with self.subTest(alcance=alcance):
                registro = self.registro(ranking=alcance).context
                ranking = self.ver(**parametros).context
                for clave in (
                    'num_equipos', 'salidas_positivas', 'salidas_negativas', 'efectividad',
                    'total_acordado', 'total_domicilio', 'total_recaudado', 'total_por_cobrar',
                    'total_bodegaje_cobrado', 'total_bodegaje_pendiente', 'total_bodegaje_perdonado',
                ):
                    self.assertEqual(registro['ranking_resumen'][clave], ranking['resumen_salidas'][clave], clave)
                self.assertEqual(
                    [(f['tecnico_id'], f['puntos'], f['puesto']) for f in registro['ranking_filas']],
                    [(f['tecnico_id'], f['puntos'], f['puesto']) for f in ranking['ranking']],
                )
                self.assertEqual(len(registro['cuadres']), len(self.cuadres(self.ver(**parametros))))

    def test_muestra_todo_lo_del_ranking(self):
        self.preparar()
        respuesta = self.registro()
        for texto in (
            'id="ranking-admin"', 'Tabla de posiciones', 'Nivel del técnico', 'Puntos de este período',
            'Resultados de los equipos', 'Ubicación', 'Bodegaje cobrado', 'Bodegaje sin cobrar',
            'Bodegaje perdonado', 'con pagos y bodegaje', 'Cuadre con Pagos', 'Ver ranking completo',
            'Cliente Prueba', '$4,00',
        ):
            self.assertContains(respuesta, texto)

    def test_la_caja_esta_en_el_registro_y_no_en_el_ranking(self):
        self.preparar()
        registro = self.registro()
        self.assertContains(registro, 'id="caja"')
        self.assertContains(registro, 'Guardado en caja')
        self.assertEqual(registro.context['caja']['saldo_final'], Decimal('92.00'))
        self.assertEqual(
            [m['etiqueta'] for m in registro.context['caja']['meses']],
            ['agosto 2026', 'septiembre 2026', 'octubre 2026'],
        )
        ranking = self.ver()
        self.assertNotContains(ranking, 'id="cuadre-pagos"')
        self.assertNotContains(ranking, 'id="caja"')
        self.assertNotContains(ranking, 'Guardado en caja')
        self.assertContains(ranking, f"{reverse('econotec:admin_dashboard')}?ano=2026&mes=10#caja")

    def test_el_filtro_de_tecnico_muestra_solo_a_ese_tecnico(self):
        self.preparar()
        contexto = self.registro(tecnico_resumen=str(self.otro_tecnico.pk)).context
        self.assertEqual([f['tecnico_id'] for f in contexto['ranking_filas']], [self.otro_tecnico.pk])
        self.assertEqual(contexto['ranking_resumen']['total_recaudado'], Decimal('5.00'))
        self.assertEqual(contexto['caja']['saldo_final'], Decimal('92.00'))

    def test_tecnico_sin_equipos_no_rompe_la_pagina(self):
        self.preparar()
        respuesta = self.registro(tecnico_resumen=str(self.asesora.pk))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['ranking_filas'], [])
        self.assertContains(respuesta, 'No hay equipos finalizados de este técnico')

    def test_periodo_largo_trae_mes_a_mes_por_tecnico(self):
        self.preparar()
        contexto = self.registro(ranking='anio').context
        fila = next(f for f in contexto['ranking_filas'] if f['tecnico_id'] == self.tecnico.pk)
        self.assertEqual([m['etiqueta'] for m in fila['por_mes']], ['Octubre 2026', 'Agosto 2026'])
        self.assertEqual(fila['por_mes'][1]['resumen']['total_recaudado'], Decimal('30.00'))

    def test_alcance_invalido_usa_el_mes(self):
        self.assertEqual(self.registro(ranking='otro').context['ranking_alcance'], 'mes')

    def test_otros_roles_no_entran_al_registro(self):
        self.preparar()
        for usuario in (self.tecnico, self.asesora):
            with self.subTest(usuario=usuario.username):
                self.assertEqual(self.registro(usuario).status_code, 302)

    def test_tarjeta_igual_a_la_del_ranking_con_enlaces_de_ubicacion(self):
        self.preparar()
        respuesta = self.registro()
        for texto in (
            'class="tech-card', 'Le faltan', 'Ver detalle', 'Equipos finalizados', 'class="composicion"',
            '💡', 'id="guia-efectividad-1"',
        ):
            self.assertContains(respuesta, texto)
        self.assertContains(respuesta, f'tecnico_salida={self.tecnico.pk}&fecha_por=finalizacion&fecha_desde=2026-10-01')

    def test_la_caja_es_solo_del_administrador_puro(self):
        self.preparar()
        respuesta = self.registro(self.superusuario_tecnico)
        self.assertEqual(respuesta.status_code, 200)
        for clave in ('caja', 'cuadres', 'ranking_filas'):
            self.assertNotIn(clave, respuesta.context)
        for texto in ('id="caja"', 'Guardado en caja', 'id="ranking-admin"', 'Cuadre con Pagos', '🔐 Caja'):
            self.assertNotContains(respuesta, texto)
