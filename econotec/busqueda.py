"""Helpers para búsquedas de texto tolerantes a tildes y mayúsculas."""

import unicodedata


def normalizar_texto_busqueda(valor):
    texto = str(valor or '').casefold()
    texto = unicodedata.normalize('NFD', texto)
    return ''.join(c for c in texto if unicodedata.category(c) != 'Mn')


def filtrar_objetos_normalizado(iterable, termino, texto_objeto):
    termino_normalizado = normalizar_texto_busqueda(termino).strip()
    if not termino_normalizado:
        return iterable
    return [
        obj for obj in iterable
        if termino_normalizado in normalizar_texto_busqueda(texto_objeto(obj))
    ]


def total_resultados(resultados):
    return len(resultados) if isinstance(resultados, list) else resultados.count()


def unir_textos_busqueda(*valores):
    return ' '.join(str(v or '') for v in valores)


def texto_cliente_busqueda(cliente):
    return unir_textos_busqueda(
        cliente.cedula,
        cliente.nombres,
        cliente.whatsapp,
        cliente.correo,
    )


def texto_ingreso_busqueda(ingreso):
    return unir_textos_busqueda(
        ingreso.codigo_equipo,
        ingreso.numero_equipo,
        ingreso.sede,
        ingreso.cliente.cedula,
        ingreso.cliente.nombres,
        ingreso.cliente.whatsapp,
        ingreso.cliente.correo,
        ingreso.tipo_equipo,
        ingreso.tipo_equipo_display,
        ingreso.marca,
        ingreso.modelo_serie,
        ingreso.serie,
        ingreso.problema_reportado,
        ingreso.asesor_comercial,
    )


def texto_salida_busqueda(salida):
    ingreso = salida.ingreso
    return unir_textos_busqueda(
        texto_ingreso_busqueda(ingreso),
        salida.estado_reparacion,
        salida.get_estado_reparacion_display(),
        getattr(salida.tecnico_reparo, 'first_name', ''),
        getattr(salida.tecnico_reparo, 'last_name', ''),
        getattr(salida.tecnico_reparo, 'username', ''),
        getattr(salida.registrado_por, 'first_name', ''),
        getattr(salida.registrado_por, 'last_name', ''),
        getattr(salida.registrado_por, 'username', ''),
        salida.factura_realizada,
        salida.factura_nombres,
        salida.factura_cedula,
        salida.factura_correo,
    )
