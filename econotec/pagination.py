"""Utilidades comunes de paginacion para listados del sistema."""

from django.core.paginator import Paginator


ITEMS_PER_PAGE = 10


def paginar_resultados(request, resultados, page_param='pagina', per_page=ITEMS_PER_PAGE):
    """Devuelve la pagina actual y el querystring sin el parametro de pagina."""
    page_obj = Paginator(resultados, per_page).get_page(request.GET.get(page_param))
    query_params = request.GET.copy()
    query_params.pop(page_param, None)
    return page_obj, query_params.urlencode()
