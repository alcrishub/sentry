import logging
from typing import Any

from django.http import HttpRequest, HttpResponse

from sentry.models.organization import Organization
from sentry.models.project import Project
from sentry.toolbar.utils.url import check_origin
from sentry.web.frontend.base import OrganizationView, region_silo_view

logger = logging.getLogger(__name__)


@region_silo_view
class IframeView(OrganizationView):
    security_headers = {
        "X-Frame-Options": "ALLOWALL"
    }  # allows response to be embedded in an iframe.

    def respond(self, template: str, context: dict[str, Any] | None = None, status: int = 200):
        response = super().respond(template, context=context, status=status)
        for header, val in IframeView.security_headers.items():
            response[header] = val
        return response

    def handle_auth_required(self, request: HttpRequest, *args, **kwargs):
        # Override redirects to /auth/login
        return HttpResponse(status=401)

    def handle_permission_required(self, request: HttpRequest, *args, **kwargs):
        # Override redirects to /auth/login
        return HttpResponse(status=403)

    def convert_args(self, request: HttpRequest, organization_slug: str, project_id_or_slug: int | str, *args: Any, **kwargs: Any) -> tuple[tuple[Any, ...], dict[str, Any]]:  # type: ignore[override]
        args, kwargs = super().convert_args(request, organization_slug, *args, **kwargs)
        organization: Organization | None = kwargs["organization"]
        active_project: Project | None = (
            self.get_active_project(
                request=request,
                organization=organization,  # type: ignore[arg-type]
                project_id_or_slug=project_id_or_slug,
            )
            if organization
            else None
        )
        kwargs["project"] = active_project
        return args, kwargs

    def get(self, request: HttpRequest, organization, project, *args, **kwargs):
        logger.info(organization)  # TODO: remove
        logger.info(project)
        if not project:
            return HttpResponse(
                status=404
            )  # TODO: replace with 200 response and template var for "project doesn't exist"

        allowed_origins: list[str] = project.get_option("sentry:", validate=lambda val: True)
        if not check_origin(request.META.get("HTTP_REFERER"), allowed_origins):
            return HttpResponse(
                status=403
            )  # TODO: replace with 200 response and template var for "project not configured"

        return self.respond("sentry/toolbar/iframe.html", status=200)
