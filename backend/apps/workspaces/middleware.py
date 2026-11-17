from .tenancy import current_actor


class ResetActorMiddleware:
    """Worker threads are reused; make sure one request's actor never leaks into the next."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        current_actor.set(None)
        try:
            return self.get_response(request)
        finally:
            current_actor.set(None)
