from django.contrib import admin
from .models import (
    Cliente, IngresoEquipo, Abono, SalidaEquipo,
    CategoriaEgreso, Egreso, BitacoraTecnico, HorarioTecnico,
)


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('cedula', 'nombres', 'whatsapp', 'correo', 'sector', 'creado')
    search_fields = ('cedula', 'nombres', 'whatsapp', 'correo')
    list_filter = ('sector',)


class AbonoInline(admin.TabularInline):
    model = Abono
    extra = 0
    readonly_fields = ('numero_recibo', 'creado')


class SalidaEquipoInline(admin.StackedInline):
    model = SalidaEquipo
    extra = 0
    fk_name = 'ingreso'


@admin.register(IngresoEquipo)
class IngresoEquipoAdmin(admin.ModelAdmin):
    list_display = (
        'numero_equipo', 'fecha_ingreso', 'cliente',
        'tipo_equipo', 'marca', 'estado', 'valor_acordado',
    )
    list_filter = ('estado', 'tipo_equipo', 'fecha_ingreso')
    search_fields = (
        'numero_equipo', 'cliente__nombres', 'cliente__cedula',
        'marca', 'modelo_serie', 'serie',
    )
    readonly_fields = ('numero_equipo', 'creado', 'actualizado')
    inlines = [AbonoInline, SalidaEquipoInline]
    date_hierarchy = 'fecha_ingreso'


@admin.register(SalidaEquipo)
class SalidaEquipoAdmin(admin.ModelAdmin):
    list_display = (
        'ingreso', 'fecha_salida', 'estado_reparacion',
        'valor_final_cobrado', 'cliente_recibe_conforme', 'registrado_por',
    )
    list_filter = ('estado_reparacion', 'fecha_salida', 'cliente_recibe_conforme')
    search_fields = (
        'ingreso__numero_equipo', 'ingreso__cliente__nombres',
    )
    date_hierarchy = 'fecha_salida'


@admin.register(Abono)
class AbonoAdmin(admin.ModelAdmin):
    list_display = ('numero_recibo', 'ingreso', 'fecha', 'monto', 'metodo')
    list_filter = ('metodo', 'banco', 'fecha')
    search_fields = ('numero_recibo', 'ingreso__numero_equipo')
    readonly_fields = ('numero_recibo',)
    date_hierarchy = 'fecha'


@admin.register(CategoriaEgreso)
class CategoriaEgresoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'orden', 'activo')
    list_editable = ('orden', 'activo')


@admin.register(Egreso)
class EgresoAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'categoria', 'concepto', 'monto', 'registrado_por')
    list_filter = ('categoria', 'fecha')
    search_fields = ('concepto', 'notas')
    date_hierarchy = 'fecha'


@admin.register(HorarioTecnico)
class HorarioTecnicoAdmin(admin.ModelAdmin):
    list_display = (
        'tecnico', 'activo', 'dias_display', 'hora_inicio', 'hora_fin',
        'ultima_notificacion_laboral', 'ultima_notificacion_fuera_laboral',
    )
    list_filter = ('activo', 'lunes', 'martes', 'miercoles', 'jueves', 'viernes')
    search_fields = ('tecnico__username', 'tecnico__first_name', 'tecnico__last_name')


@admin.register(BitacoraTecnico)
class BitacoraTecnicoAdmin(admin.ModelAdmin):
    list_display = ('momento', 'usuario_nombre', 'tipo', 'codigo', 'texto')
    list_filter = ('tipo', 'momento')
    search_fields = ('usuario_nombre', 'codigo', 'texto')
    readonly_fields = (
        'user', 'usuario_nombre', 'momento', 'tipo', 'texto', 'codigo',
        'ingreso', 'salida', 'abono', 'dedupe_key', 'metadata', 'creado',
    )
    date_hierarchy = 'momento'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
