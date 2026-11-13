"""Agent facade — action manifest.

The manifest is generated from the ACTIONS registry that every facade module
feeds via ``register_action`` — one source of truth for the HTTP surface, the
MCP tool list and client discovery.
"""
from flask.views import MethodView
from flask.typing import ResponseReturnValue

from app.utils.api.ApiBaseResponse import create_api_base_response

from . import ACTIONS, agent_blueprint, register_action

blp = agent_blueprint("Agent Manifest", "/agent", "Agent action discovery")

MANIFEST_VERSION = 1


@blp.route("/manifest")
class AgentManifest(MethodView):
    """Machine-readable catalog of all agent actions."""

    def get(self) -> ResponseReturnValue:
        """Returns {version, actions: [{id, method, path, description, scope}]}."""
        actions = sorted(ACTIONS, key=lambda a: a["id"])
        return create_api_base_response({"version": MANIFEST_VERSION, "actions": actions})


register_action("agent.manifest", "GET", "/api/user/v1/agent/manifest",
                "This manifest: list all available agent actions", "read")
