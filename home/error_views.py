"""Custom HTTP error pages."""

from django.shortcuts import render


ERROR_COPY = {
    400: {
        'title': 'Bad request',
        'headline': 'We could not process that request',
        'message': (
            'Something about the request was invalid. '
            'Check the link or form and try again.'
        ),
    },
    403: {
        'title': 'Access denied',
        'headline': 'You do not have permission to view this page',
        'message': (
            'This area is restricted. Sign in with the correct account '
            'or return to the storefront.'
        ),
    },
    404: {
        'title': 'Page not found',
        'headline': 'This page does not exist',
        'message': (
            'The link may be outdated or mistyped. '
            'Browse products or go back to the homepage.'
        ),
    },
    500: {
        'title': 'Something went wrong',
        'headline': 'We hit an unexpected error',
        'message': (
            'Our team has been notified. Please try again in a moment '
            'or continue shopping from the homepage.'
        ),
    },
}


def error_response(request, status_code, *, exception=None):
    copy = ERROR_COPY.get(status_code, ERROR_COPY[500])
    return render(
        request,
        f'errors/{status_code}.html',
        {
            'status_code': status_code,
            'error_title': copy['title'],
            'error_headline': copy['headline'],
            'error_message': copy['message'],
            'request_path': getattr(request, 'path', ''),
            'exception': exception,
        },
        status=status_code,
    )


def bad_request(request, exception=None):
    return error_response(request, 400, exception=exception)


def permission_denied(request, exception=None):
    return error_response(request, 403, exception=exception)


def page_not_found(request, exception=None):
    return error_response(request, 404, exception=exception)


def server_error(request):
    return error_response(request, 500)
