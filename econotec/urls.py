from django.urls import path
from . import views, views_pagos, views_admin, views_print, views_tecnico

app_name = 'econotec'

urlpatterns = [
    # ── Páginas base ───────────────────────────────────────
    path('bienvenida/', views.bienvenida, name='bienvenida'),
    path('dashboard-details/<str:tipo>/', views.dashboard_details, name='dashboard_details'),
    path('ayuda/', views.ayuda, name='ayuda'),
    path('musica/', views.reproductor_musica, name='reproductor_musica'),
    path('api/perfil/', views.api_perfil, name='api_perfil'),

    # ── Alertas y Bot ──────────────────────────────────────────
    path('alertas/demoras/', views.alertas_demora, name='alertas_demora'),
    path('alertas/bodegaje/', views.alertas_bodegaje, name='alertas_bodegaje'),
    path('ingresos/<int:pk>/diagnostico-silenciar/',
         views.ingreso_diagnostico_silenciar, name='ingreso_diagnostico_silenciar'),
    path('bot-query/', views.bot_query, name='bot_query'),

    # ── Salida: aviso post-creación + cierre del caso ──────
    path('salidas/<int:pk>/aviso/', views.salida_listo_aviso, name='salida_listo_aviso'),
    path('salidas/<int:pk>/marcar-retirada/',
         views.salida_marcar_retirada, name='salida_marcar_retirada'),
    path('salidas/<int:pk>/deshacer-retiro/',
         views.salida_deshacer_retiro, name='salida_deshacer_retiro'),
    path('salidas/<int:pk>/bodegaje-silenciar/',
         views.salida_bodegaje_silenciar, name='salida_bodegaje_silenciar'),

    # ── Ingreso de equipos (la "Solicitud de Ingreso") ────
    path('ingresos/', views.ingreso_lista, name='ingreso_lista'),
    path('ingresos/menu/', views.ingreso_menu, name='ingreso_menu'),
    path('ingresos/registrar/', views.ingreso_registrar, name='ingreso_registrar'),
    path('ingresos/<int:pk>/', views.ingreso_detalle, name='ingreso_detalle'),
    path('ingresos/<int:pk>/editar/', views.ingreso_editar, name='ingreso_editar'),
    path('ingresos/<int:pk>/eliminar/', views.ingreso_eliminar, name='ingreso_eliminar'),
    path('ingresos/<int:pk>/imprimir/', views_print.ingreso_imprimir, name='ingreso_imprimir'),
    path('ingresos/<int:pk>/qr/imprimir/', views_print.ingreso_imprimir_qr, name='ingreso_imprimir_qr'),
    path('ingresos/<int:pk>/qr.png', views_print.ingreso_qr_png, name='ingreso_qr_png'),
    path('ingresos/<int:pk>/pdf/', views_print.ingreso_pdf, name='ingreso_pdf'),

    # ── Hoja digital del técnico (acceso por QR, optimizada para celular) ──
    path('tecnico/hoja/<str:token>/', views_tecnico.tecnico_hoja, name='tecnico_hoja'),

    # ── Ventas de Productos ────────────────────────────────
    path('ventas/', views.venta_lista, name='venta_lista'),
    path('ventas/menu/', views.venta_menu, name='venta_menu'),
    path('ventas/registrar/', views.venta_registrar, name='venta_registrar'),
    path('ventas/<int:pk>/editar/', views.venta_editar, name='venta_editar'),
    path('ventas/<int:pk>/eliminar/', views.venta_eliminar, name='venta_eliminar'),
    path('ventas/exportar/', views.venta_export, name='venta_export'),

    # ── Salida de equipos (cierre / entrega) ───────────────
    path('salidas/', views.salida_lista, name='salida_lista'),
    path('salidas/menu/', views.salida_menu, name='salida_menu'),
    path('salidas/totales/', views.salida_totales, name='salida_totales'),
    path('ingresos/<int:ingreso_pk>/salida/registrar/',
         views.salida_registrar, name='salida_registrar'),
    path('salidas/<int:pk>/editar/', views.salida_editar, name='salida_editar'),
    path('salidas/<int:pk>/eliminar/', views.salida_eliminar, name='salida_eliminar'),
    path('salidas/<int:pk>/imprimir/', views_print.salida_imprimir, name='salida_imprimir'),
    path('salidas/<int:pk>/pdf/', views_print.salida_pdf, name='salida_pdf'),

    # ── Clientes ───────────────────────────────────────────
    path('clientes/', views.cliente_lista, name='cliente_lista'),
    path('clientes/top/', views.cliente_top_recurrentes, name='cliente_top_recurrentes'),
    path('clientes/<int:pk>/', views.cliente_detalle, name='cliente_detalle'),
    path('clientes/exportar/', views.cliente_export, name='cliente_export'),
    path('clientes/buscar-por-cedula/',
         views.cliente_buscar_por_cedula, name='cliente_buscar_por_cedula'),

    # ── Pagos / Abonos ─────────────────────────────────────
    path('pagos/', views_pagos.pagos_lista, name='pagos_lista'),
    path('pagos/ventas/', views_pagos.pagos_ventas_lista, name='pagos_ventas_lista'),
    path('pagos/exportar/', views_pagos.pagos_export, name='pagos_export'),
    path('ingresos/<int:pk>/abonos/',
         views_pagos.ingreso_abonos, name='ingreso_abonos'),
    path('ingresos/<int:ingreso_pk>/abonos/crear/',
         views_pagos.abono_crear, name='abono_crear'),
    path('ingresos/<int:ingreso_pk>/abonos/<int:abono_pk>/editar/',
         views_pagos.abono_editar, name='abono_editar'),
    path('ingresos/<int:ingreso_pk>/abonos/<int:abono_pk>/eliminar/',
         views_pagos.abono_eliminar, name='abono_eliminar'),
    path('abonos/<int:abono_pk>/recibo/',
         views_pagos.abono_recibo, name='abono_recibo'),

    # ── Historial ──────────────────────────────────────────
    path('historial/', views_pagos.historial_lista, name='historial_lista'),
    path('historial/exportar/', views_pagos.historial_export, name='historial_export'),
    path('historial/imprimir/', views_pagos.historial_imprimir, name='historial_imprimir'),

    # ── Registro Administrativo ────────────────────────────
    path('admin-panel/',
         views_admin.admin_dashboard, name='admin_dashboard'),
    path('admin-panel/perfiles/reiniciar/',
         views_admin.admin_perfiles_reiniciar, name='admin_perfiles_reiniciar'),
    path('admin-panel/perfiles/exportar/<str:formato>/',
         views_admin.admin_perfiles_exportar, name='admin_perfiles_exportar'),
    path('admin-panel/mantenimiento/',
         views_admin.admin_mantenimiento_reset, name='admin_mantenimiento_reset'),
    path('admin-panel/egresos/',
         views_admin.egresos_lista, name='admin_egresos_lista'),
    path('admin-panel/egresos/nuevo/',
         views_admin.egreso_crear, name='admin_egreso_crear'),
    path('admin-panel/egresos/<int:pk>/editar/',
         views_admin.egreso_editar, name='admin_egreso_editar'),
    path('admin-panel/egresos/<int:pk>/eliminar/',
         views_admin.egreso_eliminar, name='admin_egreso_eliminar'),
    path('admin-panel/export/reporte/',
         views_admin.export_reporte_mes, name='admin_export_reporte'),
    path('admin-panel/export/egresos/',
         views_admin.export_egresos, name='admin_export_egresos'),
    path('admin-panel/bodegajes/', views_admin.admin_bodegajes, name='admin_bodegajes'),
    path('admin-panel/activos-bodegaje/', views_admin.admin_activos_bodegaje, name='admin_activos_bodegaje'),

    # ── Control de Registro / Auditoría (solo admin) ───────
    path('admin-panel/control-registro/', views_admin.control_registro, name='control_registro'),

    # ── Avisos del panel principal (solo admin) ────────────
    path('admin-panel/avisos/', views_admin.avisos_lista, name='avisos_lista'),
    path('admin-panel/avisos/nuevo/', views_admin.aviso_crear, name='aviso_crear'),
    path('admin-panel/avisos/<int:pk>/editar/', views_admin.aviso_editar, name='aviso_editar'),
    path('admin-panel/avisos/<int:pk>/eliminar/', views_admin.aviso_eliminar, name='aviso_eliminar'),
]
