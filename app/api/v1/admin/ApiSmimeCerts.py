"""
Admin S/MIME certificate inventory endpoint
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.service.smime.SMimeKeyManager import SMimeKeyManager
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting


blp = Blueprint("SmimeCerts", __name__, url_prefix="/smime/certs")


@blp.before_request
def init_smime_certs() -> None:
    """
    Initialize the SMimeKeyManager for this request
    """
    logger_api.debug("Calling before_request for ApiSmimeCerts")
    process: ProcessSetting = g.process_settings
    g.smime_key_manager = SMimeKeyManager()


@blp.route("/")
class ApiSmimeCertsInventory(MethodView):
    """
    Admin endpoint for S/MIME certificate inventory
    
    GET /api/admin/smime/certs returns a JSON list of all certificates currently stored,
    each with user_uid, emails, not_before, not_after, has_private_key.
    Empty store -> empty list.
    """

    @blp.response(200)
    def get(self) -> ResponseReturnValue:
        """
        Get all S/MIME certificates with their metadata
        """
        smime_manager: SMimeKeyManager = g.smime_key_manager
        certificates = smime_manager.get_all_certificates()
        return create_api_base_response(certificates)
