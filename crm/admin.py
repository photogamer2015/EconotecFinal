from django.contrib import admin

from .models import Actividad, Contacto, Conversacion, Mensaje, Oportunidad, Perfil, Seguimiento




@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ("user", "rol", "recibe_leads")
    list_filter = ("rol",)


@admin.register(Contacto)
class ContactoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "empresa", "telefono", "email", "creado")
    search_fields = ("nombre", "empresa", "telefono", "email")


@admin.register(Oportunidad)
class OportunidadAdmin(admin.ModelAdmin):
    list_display = ("contacto", "servicio", "canal", "etapa", "valor", "responsable", "creado")
    list_filter = ("etapa", "canal", "responsable")
    search_fields = ("contacto__nombre", "contacto__empresa")


class MensajeInline(admin.TabularInline):
    model = Mensaje
    extra = 0


@admin.register(Conversacion)
class ConversacionAdmin(admin.ModelAdmin):
    list_display = ("contacto", "canal", "no_leidos", "ultimo_mensaje")
    inlines = [MensajeInline]


@admin.register(Actividad)
class ActividadAdmin(admin.ModelAdmin):
    list_display = ("fecha", "tipo", "contacto", "usuario", "resultado")
    list_filter = ("tipo", "resultado")


@admin.register(Seguimiento)
class SeguimientoAdmin(admin.ModelAdmin):
    list_display = ("titulo", "responsable", "fecha_hora", "completado", "notificado")
    list_filter = ("completado", "tipo")
