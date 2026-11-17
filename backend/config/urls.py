from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from apps.accounts import views as account_views
from apps.audit.views import AuditLogViewSet
from apps.billing import views as billing_views
from apps.notifications.views import NotificationViewSet, WeeklyReportView
from apps.projects import views as pv
from apps.webhooks.views import WebhookDeliveryViewSet, WebhookViewSet
from apps.workspaces import views as wv

router = DefaultRouter()
router.register("projects", pv.ProjectViewSet, basename="project")
router.register("statuses", pv.WorkflowStatusViewSet, basename="status")
router.register("transitions", pv.WorkflowTransitionViewSet, basename="transition")
router.register("columns", pv.BoardColumnViewSet, basename="column")
router.register("sprints", pv.SprintViewSet, basename="sprint")
router.register("labels", pv.LabelViewSet, basename="label")
router.register("issues", pv.IssueViewSet, basename="issue")
router.register("comments", pv.CommentViewSet, basename="comment")
router.register("attachments", pv.AttachmentViewSet, basename="attachment")
router.register("saved-filters", pv.SavedFilterViewSet, basename="savedfilter")
router.register("members", wv.MemberViewSet, basename="member")
router.register("invitations", wv.InvitationViewSet, basename="invitation")
router.register("audit-log", AuditLogViewSet, basename="auditlog")
router.register("webhooks", WebhookViewSet, basename="webhook")
router.register("webhook-deliveries", WebhookDeliveryViewSet, basename="webhookdelivery")
router.register("notifications", NotificationViewSet, basename="notification")


def health(request):
    return JsonResponse({"status": "ok"})


tenant_patterns = [
    path("", wv.WorkspaceDetailView.as_view(), name="workspace-detail"),
    path("dashboard/", pv.DashboardView.as_view(), name="dashboard"),
    path("search/", pv.SearchView.as_view(), name="search"),
    path("reports/weekly/", WeeklyReportView.as_view(), name="weekly-report"),
    path("billing/", billing_views.BillingView.as_view(), name="billing"),
    path("billing/checkout/", billing_views.CheckoutView.as_view(), name="billing-checkout"),
    path("billing/portal/", billing_views.PortalView.as_view(), name="billing-portal"),
    path("billing/cancel/", billing_views.CancelView.as_view(), name="billing-cancel"),
    path("billing/sync/", billing_views.SyncView.as_view(), name="billing-sync"),
    path("billing/mock/confirm/", billing_views.MockConfirmView.as_view(), name="billing-mock-confirm"),
    path("", include(router.urls)),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health),
    path("api/auth/register/", account_views.RegisterView.as_view(), name="register"),
    path("api/auth/login/", account_views.LoginView.as_view(), name="login"),
    path("api/auth/refresh/", account_views.RefreshView.as_view(), name="refresh"),
    path("api/auth/me/", account_views.MeView.as_view(), name="me"),
    path("api/workspaces/", wv.MyWorkspacesView.as_view(), name="my-workspaces"),
    path("api/invitations/accept/", wv.AcceptInvitationView.as_view(), name="invitation-accept"),
    path("api/invitations/<str:token>/", wv.InvitationLookupView.as_view(), name="invitation-lookup"),
    path("api/billing/stripe-webhook/", billing_views.StripeWebhookView.as_view(), name="stripe-webhook"),
    path("api/w/<slug:workspace_slug>/", include(tenant_patterns)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
