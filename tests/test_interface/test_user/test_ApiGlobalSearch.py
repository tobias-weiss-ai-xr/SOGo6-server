"""Structural tests for the Global Quick Search (Cmd+K) API."""

from pathlib import Path

API_DIR = Path(__file__).resolve().parents[3] / "app" / "api" / "v1" / "user"
IFACE_DIR = Path(__file__).resolve().parents[3] / "app" / "interface" / "user"


class TestApiGlobalSearch:
    def test_api_file_exists(self):
        assert (API_DIR / "ApiGlobalSearch.py").exists()

    def test_blueprint_url_prefix(self):
        content = (API_DIR / "ApiGlobalSearch.py").read_text(encoding="utf-8")
        assert 'url_prefix="/search"' in content

    def test_global_route(self):
        content = (API_DIR / "ApiGlobalSearch.py").read_text(encoding="utf-8")
        assert '@blp.route("/global")' in content
        assert "class ApiGlobalSearch" in content

    def test_query_required(self):
        content = (API_DIR / "ApiGlobalSearch.py").read_text(encoding="utf-8")
        assert '"q"' in content
        assert "required" in content

    def test_registered_in_user_apis(self):
        init_content = (API_DIR / "__init__.py").read_text(encoding="utf-8")
        assert "ApiGlobalSearch" in init_content
        assert "global_search_blueprint" in init_content


class TestInterfaceGlobalSearch:
    def test_interface_file_exists(self):
        assert (IFACE_DIR / "InterfaceApiGlobalSearch.py").exists()

    def test_aggregates_three_sections(self):
        content = (IFACE_DIR / "InterfaceApiGlobalSearch.py").read_text(encoding="utf-8")
        assert "contacts" in content
        assert "events" in content
        assert "users" in content

    def test_short_query_guard(self):
        content = (IFACE_DIR / "InterfaceApiGlobalSearch.py").read_text(encoding="utf-8")
        assert "len(query) < 2" in content

    def test_section_failure_isolation(self):
        content = (IFACE_DIR / "InterfaceApiGlobalSearch.py").read_text(encoding="utf-8")
        assert "_search_contacts" in content
        assert "_search_events" in content
        assert "_search_users" in content
        assert content.count("except (RequestException, Exception)") >= 3
