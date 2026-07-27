"""
User-facing API endpoints for customization (themes, etc.)
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from flask import g, Response
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.interface.admin.InterfaceApiAdminConfig import InterfaceApiAdminConfig
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting


blp = Blueprint("Customization", __name__, url_prefix="/customization")


@blp.before_request
def init_customization() -> None:
    """Init the interface and others if needed."""
    logger_api.debug("Calling before_request for ApiUserCustomization")
    process: ProcessSetting = g.process_settings
    interface_api = InterfaceApiAdminConfig(process_setting=process)
    g.inter = interface_api


@blp.route("/themes")
class ApiUserCustomizationThemes(MethodView):
    """
    Endpoint that returns theme CSS.
    This endpoint is public (no auth required) so that themes
    can be loaded before the login page renders.
    """

    public_access = True

    @blp.response(200)
    def get(self) -> ResponseReturnValue:
        """
        Return the theme CSS as a JSON string.

        The response is a JSON string containing CSS custom properties
        that the frontend injects into a <style id="dynamic-theme"> tag.
        """
        interface_api: InterfaceApiAdminConfig = g.inter
        theme_config = interface_api.get_all_setting_theme()

        # theme_config is (api_response, status_code)
        # api_response["data"] contains the theme settings dict
        theme_data = theme_config[0].get("data", {})

        # Generate CSS from theme config
        css = _generate_theme_css(theme_data)
        return css, 200, {"Content-Type": "application/json"}


def _generate_theme_css(theme: dict) -> str:
    """
    Generate a CSS string from theme configuration.

    Falls back to the default theme (from the fake API) if no config is stored.
    """
    if not theme:
        # Return default theme
        return _DEFAULT_THEME_CSS

    lines = [":root {"]
    # Map known theme keys to CSS custom properties
    PROP_MAP = {
        "primary": "--primary",
        "primary_foreground": "--primary-foreground",
        "background": "--background",
        "foreground": "--foreground",
        "sidebar_background": "--sidebar-background",
        "sidebar_foreground": "--sidebar-foreground",
        "sidebar_primary": "--sidebar-primary",
        "sidebar_accent": "--sidebar-accent",
        "sidebar_accent_foreground": "--sidebar-accent-foreground",
        "sidebar_border": "--sidebar-border",
        "header_background": "--header-background",
        "header_foreground": "--header-foreground",
        "card": "--card",
        "card_foreground": "--card-foreground",
        "popover": "--popover",
        "popover_foreground": "--popover-foreground",
        "secondary": "--secondary",
        "secondary_foreground": "--secondary-foreground",
        "muted": "--muted",
        "muted_foreground": "--muted-foreground",
        "accent": "--accent",
        "accent_foreground": "--accent-foreground",
        "destructive": "--destructive",
        "destructive_foreground": "--destructive-foreground",
        "border": "--border",
        "input": "--input",
        "ring": "--ring",
        "radius": "--radius",
    }
    for key, css_var in PROP_MAP.items():
        val = theme.get(key)
        if val is not None:
            lines.append(f"  {css_var}: {val};")

    # Append custom CSS if provided
    custom_css = theme.get("custom_css", "")
    if custom_css:
        lines.append(custom_css)

    lines.append("}")
    return "".join(lines)


_DEFAULT_THEME_CSS = """:root {
  --background: 0 0% 100%;
  --foreground: 240 5% 10%;
  --card: 0 0% 100%;
  --card-foreground: 240 5% 10%;
  --popover: 0 0% 100%;
  --popover-foreground: 240 5% 10%;
  --primary: 180 25% 40%;
  --primary-foreground: 0 0% 100%;
  --secondary: 220 10% 96%;
  --secondary-foreground: 240 5% 10%;
  --muted: 220 10% 96%;
  --muted-foreground: 220 10% 40%;
  --accent: 180 25% 60%;
  --accent-foreground: 0 0% 100%;
  --destructive: 0 70% 40%;
  --destructive-foreground: 0 0% 100%;
  --border: 220 13% 91%;
  --input: 220 13% 91%;
  --ring: 180 60% 45%;
  --radius: 0.5rem;
  --sidebar-background: 180 25% 40%;
  --sidebar-background-secondary: 0 0% 100%;
  --sidebar-foreground: 0 0% 100%;
  --sidebar-foreground-secondary: 240 5% 10%;
  --sidebar-muted-foreground-secondary: 240 5% 10%;
  --sidebar-primary: 180 60% 45%;
  --sidebar-accent: 180 25% 60%;
  --sidebar-accent-foreground: 0 0% 100%;
  --sidebar-border: 220 13% 91%;
  --sidebar-ring: 180 60% 45%;
  --header-background: 0 0% 100%;
  --header-foreground: 270 60% 60%;
  --header-muted-foreground: 270 60% 60%;
}
"""
