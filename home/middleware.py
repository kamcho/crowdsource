from django.conf import settings

from home.error_views import error_response


class FriendlyErrorsMiddleware:
    """Replace Django debug error pages with branded templates."""

    HANDLED_STATUSES = {400, 403, 404, 500}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            response = self.get_response(request)
        except Exception as exc:
            if self._use_friendly_errors():
                return error_response(request, 500, exception=exc)
            raise

        if self._use_friendly_errors() and response.status_code in self.HANDLED_STATUSES:
            return error_response(request, response.status_code)
        return response

    def process_exception(self, request, exception):
        if not self._use_friendly_errors():
            return None
        return error_response(request, 500, exception=exception)

    @staticmethod
    def _use_friendly_errors():
        return getattr(settings, 'FRIENDLY_ERRORS', True)
