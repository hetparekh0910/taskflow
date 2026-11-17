from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler

from apps.billing.plans import PlanLimitExceeded


def exception_handler(exc, context):
    if isinstance(exc, PlanLimitExceeded):
        return Response(exc.payload, status=exc.status_code)  # keep numbers as numbers
    return drf_handler(exc, context)
