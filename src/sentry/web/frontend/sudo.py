from __future__ import annotations

from typing import Any

from django.http.request import HttpRequest

from sentry.auth.authenticators.u2f import U2fInterface
from sentry.users.models.authenticator import Authenticator
from sentry.utils import json
from sentry.web.frontend.base import control_silo_view
from sudo.views import SudoView as BaseSudoView


@control_silo_view
class SudoView(BaseSudoView):
    template_name = "sentry/account/sudo.html"

    def handle_sudo(self, request: HttpRequest, context: dict[str, Any]) -> bool:
        if super().handle_sudo(request, context):
            return True

        try:
            interface: U2fInterface = Authenticator.objects.get_interface(request.user, "u2f")
            if not interface.is_enrolled():
                raise LookupError()
        except LookupError:
            return False

        challenge = interface.activate(request).challenge

        if request.method == "POST":
            if "challenge" in request.POST and "response" in request.POST:
                try:
                    challenge = json.loads(request.POST["challenge"])
                    response = json.loads(request.POST["response"])
                except ValueError:
                    pass
                else:
                    if interface.validate_response(request, challenge, response):
                        return True
        context["u2f_challenge"] = challenge
        return False
