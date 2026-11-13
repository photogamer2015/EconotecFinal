from django.contrib import admin
from .models import (
    Cliente, IngresoEquipo, Abono, SalidaEquipo,
    CategoriaEgreso, Egreso, BitacoraTecnico, HorarioTecnico, AjustePuntaje,
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
        'valor_final_cobrado', 'valor_acordado_adicional',
        'cliente_recibe_conforme', 'registrado_por',
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
    list_display = ('fecha', 'categoria', 'concepto', 'monto', 'asesora', 'registrado_por')
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


@admin.register(AjustePuntaje)
class AjustePuntajeAdmin(admin.ModelAdmin):
    """«Puntajes»: el administrador suma o resta puntos a mano a un técnico."""

    list_display = (
        'fecha', 'tecnico_nombre', 'ajuste', 'motivo', 'puntaje_actual', 'creado_por', 'creado',
    )
    list_filter = ('tipo', 'cuenta_como_reparado', ('tecnico', admin.RelatedOnlyFieldListFilter), 'fecha')
    search_fields = ('tecnico__username', 'tecnico__first_name', 'tecnico__last_name', 'motivo')
    date_hierarchy = 'fecha'
    fields = ('tecnico', 'tipo', 'puntos', 'cuenta_como_reparado', 'motivo', 'fecha', 'creado_por', 'creado')
    readonly_fields = ('creado_por', 'creado')
    radio_fields = {'tipo': admin.HORIZONTAL}
    list_select_related = ('tecnico', 'creado_por')

    @staticmethod
    def _nombre(usuario):
        return f'{usuario.first_name} {usuario.last_name}'.strip() or usuario.username

    @admin.display(description='Técnico', ordering='tecnico__first_name')
    def tecnico_nombre(self, obj):
        return self._nombre(obj.tecnico)

    @admin.display(description='Ajuste')
    def ajuste(self, obj):
        puntos = obj.puntos_con_signo
        texto = f'+{puntos} pts' if puntos > 0 else f'{puntos} pts'
        return f'{texto} · equipo reparado' if obj.cuenta_como_reparado else texto

    @admin.display(description='Puntaje actual del técnico')
    def puntaje_actual(self, obj):
        from .views import puntaje_tecnico
        puntaje = puntaje_tecnico(obj.tecnico)
        return f"{puntaje['total']} pts · {puntaje['nivel']}"

    def get_form(self, request, obj=None, **kwargs):
        # Al editar, el técnico del ajuste sigue en la lista aunque ya no
        # esté activo o en el grupo Técnicos.
        request._ajuste_puntaje_tecnico_id = obj.tecnico_id if obj else None
        form = super().get_form(request, obj, **kwargs)
        # Aquí solo se elige el técnico; los usuarios se gestionan en «Usuarios».
        widget = form.base_fields['tecnico'].widget
        widget.can_add_related = widget.can_change_related = False
        widget.can_view_related = widget.can_delete_related = False
        return form

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'tecnico':
            from django.contrib.auth import get_user_model
            from django.db.models import Q

            from .forms import _queryset_tecnicos
            User = get_user_model()
            tecnicos = _queryset_tecnicos()
            if not tecnicos.exists():
                tecnicos = User.objects.filter(is_active=True)
            actual = getattr(request, '_ajuste_puntaje_tecnico_id', None)
            kwargs['queryset'] = User.objects.filter(
                Q(pk__in=tecnicos.values('pk')) | Q(pk=actual),
            ).order_by('first_name', 'username')
            campo = super().formfield_for_foreignkey(db_field, request, **kwargs)
            campo.label_from_instance = self._nombre
            return campo
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.creado_por = request.user
        super().save_model(request, obj, form, change)
