from django.urls import path

from . import views, views_admin, views_api, views_config, views_notif

app_name = "crm"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("clientes/", views.clientes, name="clientes"),
    path("clientes/nuevo/", views.cliente_nuevo, name="cliente_nuevo"),
    path("clientes/<int:pk>/editar/", views.cliente_editar, name="cliente_editar"),
    path("oportunidades/", views.oportunidades, name="oportunidades"),
    path("oportunidades/nueva/", views.oportunidad_nueva, name="oportunidad_nueva"),
    path("oportunidades/<int:pk>/", views.oportunidad_detalle, name="oportunidad"),
    path("oportunidades/<int:pk>/mover/", views.oportunidad_mover, name="oportunidad_mover"),
    path("oportunidades/<int:pk>/whatsapp/", views.oportunidad_whatsapp, name="oportunidad_whatsapp"),
    path("bitacora/", views.bitacora, name="bitacora"),
    path("bitacora/nueva/", views.actividad_nueva, name="actividad_nueva"),
    path("seguimientos/", views.seguimientos, name="seguimientos"),
    path("seguimientos/nuevo/", views.seguimiento_nuevo, name="seguimiento_nuevo"),
    path("seguimientos/<int:pk>/completar/", views.seguimiento_completar, name="seguimiento_completar"),

    path("etiquetas/", views_config.etiquetas, name="etiquetas"),
    path("etiquetas/<int:pk>/", views_config.etiqueta_editar, name="etiqueta_editar"),
    path("whatsapp/", views_config.whatsapp, name="whatsapp"),
    path("whatsapp/conexion/", views.whatsapp_conexion, name="whatsapp_conexion"),
    path("whatsapp/conexion/estado/", views.whatsapp_conexion_estado, name="whatsapp_conexion_estado"),
    path("chats/", views.bandeja, name="bandeja"),
    path("chats/<int:pk>/", views.bandeja, name="bandeja_conv"),
    path("chats/<int:pk>/bot/", views.bandeja_bot, name="bandeja_bot"),
    path("chats/<int:pk>/accion/", views.bandeja_accion, name="bandeja_accion"),
    path("chats/estado/", views.bandeja_estado, name="bandeja_estado"),
    path("whatsapp/respuestas/nueva/", views_config.respuesta_editar, name="respuesta_nueva"),
    path("whatsapp/respuestas/<int:pk>/", views_config.respuesta_editar, name="respuesta_editar"),
    path("whatsapp/respuestas/<int:pk>/borrar/", views_config.respuesta_borrar, name="respuesta_borrar"),
    path("whatsapp/categorias/nueva/", views_config.categoria_editar, name="categoria_nueva"),
    path("whatsapp/categorias/<int:pk>/", views_config.categoria_editar, name="categoria_editar"),

    path("notificaciones/", views_notif.notificaciones, name="notificaciones"),
    path("notificaciones/<int:pk>/", views_notif.notificacion_ir, name="notificacion_ir"),
    path("notificaciones/leidas/", views_notif.notificaciones_leidas, name="notificaciones_leidas"),
    path("notificaciones/estado/", views_notif.notificaciones_estado, name="notificaciones_estado"),
    path("notificaciones/aviso/", views_notif.aviso_general, name="aviso_general"),

    path("usuarios/", views_admin.usuarios, name="usuarios"),
    path("usuarios/<int:pk>/", views_admin.usuario_editar, name="usuario_editar"),
    path("integraciones/", views_admin.integraciones, name="integraciones"),
    path("integraciones/simular/", views_admin.simular_entrante, name="simular_entrante"),

    # Públicos: formulario web, botón de WhatsApp para la página, WhatsApp (QR y API oficial)
    path("widget.js", views_api.widget_js, name="widget_js"),
    path("api/entrante/web/", views_api.entrante_web, name="api_web"),
    path("api/boton/config/", views_api.boton_config, name="api_boton_config"),
    path("api/boton/registrar/", views_api.boton_registrar, name="api_boton_registrar"),
    path("api/whatsapp/qr/entrante/", views_api.whatsapp_qr_entrante, name="api_whatsapp_qr"),
    path("api/whatsapp/webhook/", views_api.whatsapp_api_webhook, name="api_whatsapp_webhook"),
]
