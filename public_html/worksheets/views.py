from django.http import Http404


def public_worksheet(request, token):
    raise Http404


def public_worksheet_pdf(request, token):
    raise Http404
