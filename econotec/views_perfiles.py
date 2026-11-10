from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_http_methods
from .models import PerfilSocial, SalidaEquipo
from .gamificacion import nivel_por_puntos
from .views import datos_perfil
from .permisos import es_admin, es_asesor, es_asistente_caja, es_tecnico


class PerfilForm(forms.ModelForm):
    class Meta:
        model = PerfilSocial
        fields = ['avatar', 'portada', 'biografia', 'musica', 'hobbies', 'cancion']
        widgets = {'biografia': forms.Textarea(attrs={'rows': 3}),
                   'avatar': forms.RadioSelect, 'portada': forms.RadioSelect}
        help_texts = {'musica': 'Separa tus géneros o artistas con comas.',
                      'hobbies': 'Separa tus intereses con comas.'}


# Filas de la tabla «Mis salidas de retiro»; el resto se ve en la lista completa.
LIMITE_TABLA_RETIROS = 300


def rol(usuario):
    return ('Administrador' if es_admin(usuario) else 'Técnico' if es_tecnico(usuario)
            else 'Asesora - Asistente de caja' if es_asistente_caja(usuario)
            else 'Asesor comercial' if es_asesor(usuario) else 'Miembro')


@login_required
@require_http_methods(['GET', 'POST'])
def perfil(request, usuario_id=None):
    usuario = get_object_or_404(get_user_model(), pk=usuario_id or request.user.pk, is_active=True)
    personal, _ = PerfilSocial.objects.get_or_create(usuario=usuario)
    propio = usuario.pk == request.user.pk
    # Each editor updates only its own fields, preserving the other preferences.
    secciones = {'avatar': ['avatar'], 'portada': ['portada'],
                 'datos': ['biografia', 'musica', 'hobbies', 'cancion']}
    seccion = request.POST.get('seccion', 'datos')
    formularios = {}
    for clave, campos in secciones.items():
        clase = forms.modelform_factory(PerfilSocial, form=PerfilForm, fields=campos)
        formularios[clave] = clase(request.POST if request.method == 'POST' and seccion == clave else None,
                                  instance=personal)
    form = formularios.get(seccion)
    if form is None:
        from django.http import HttpResponseBadRequest
        return HttpResponseBadRequest('Sección de perfil no válida.')
    if request.method == 'POST':
        if not propio:
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden('Solo puedes editar tu propio perfil.')
        if form.is_valid():
            form.save()
            messages.success(request, 'Tu perfil se actualizó correctamente.')
            return redirect('econotec:mi_perfil')
    operativo = datos_perfil(usuario, incluir_privado=propio)
    proximo = operativo['proximo']
    umbral = nivel_por_puntos(operativo['total'])['desde']
    operativo['porcentaje'] = round(100 * (operativo['total'] - umbral) / (proximo - umbral)) if proximo else 100
    amigos = personal.amigos.filter(usuario__is_active=True).select_related('usuario')
    # Salidas de retiro (salidas de la oficina) confirmadas por la asesora:
    # las ve ella en su perfil y el administrador.
    retiros_asesora = None
    if es_asesor(usuario) and (propio or es_admin(request.user)):
        qs_retiros = (
            SalidaEquipo.objects
            .filter(retiro_confirmado_por=usuario, fecha_retiro_real__isnull=False)
            .select_related('ingreso', 'ingreso__cliente', 'ingreso__tecnico_encargado', 'tecnico_reparo')
            .order_by('-fecha_retiro_real', '-pk')
        )
        retiros_asesora = {'total': qs_retiros.count(), 'salidas': list(qs_retiros[:LIMITE_TABLA_RETIROS])}
        retiros_asesora['recortada'] = retiros_asesora['total'] > LIMITE_TABLA_RETIROS
    return render(request, 'perfiles/perfil.html', {
        'retiros_asesora': retiros_asesora,
        'operativo': operativo, 'personal': personal, 'persona': usuario, 'propio': propio, 'rol_perfil': rol(usuario),
        'form': form, 'avatares': PerfilSocial.AVATARES, 'amigos': amigos,
        'editores': [('avatar', 'Cambiar avatar', formularios['avatar']),
                     ('portada', 'Cambiar portada', formularios['portada']),
                     ('datos', 'Editar mi información', formularios['datos'])],
        'portadas': PerfilSocial.PORTADAS,
        'es_amigo': amigos.filter(usuario=request.user).exists(),
        'le_gusta': personal.me_gusta.filter(pk=request.user.pk).exists(),
    })


@login_required
def comunidad(request):
    q = request.GET.get('q', '').strip()[:100]
    usuarios = get_user_model().objects.filter(is_active=True).exclude(pk=request.user.pk)
    if q:
        usuarios = usuarios.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
    personal, _ = PerfilSocial.objects.get_or_create(usuario=request.user)
    amigos = set(personal.amigos.values_list('usuario_id', flat=True))
    from django.core.paginator import Paginator
    pagina = Paginator(usuarios.select_related('perfil_social').prefetch_related('groups').order_by('first_name', 'username'), 24).get_page(request.GET.get('page'))
    return render(request, 'perfiles/comunidad.html', {'q': q, 'pagina': pagina,
        'miembros': [(u, rol(u), u.pk in amigos) for u in pagina]})


@login_required
@require_POST
def reaccion(request, usuario_id):
    usuario = get_object_or_404(get_user_model(), pk=usuario_id, is_active=True)
    if usuario.pk != request.user.pk:
        personal, _ = PerfilSocial.objects.get_or_create(usuario=request.user)
        destino, _ = PerfilSocial.objects.get_or_create(usuario=usuario)
        accion = request.POST.get('accion')
        if accion == 'amigo':
            personal.amigos.add(destino)
        elif accion == 'quitar_amigo':
            personal.amigos.remove(destino)
        elif accion == 'like':
            destino.me_gusta.add(request.user)
        elif accion == 'unlike':
            destino.me_gusta.remove(request.user)
    if request.POST.get('volver') == 'comunidad':
        return redirect('econotec:comunidad')
    return redirect('econotec:perfil_social', usuario_id=usuario_id)
