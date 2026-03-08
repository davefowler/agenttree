"""Contract tests for web forms to API parameter alignment.

These tests ensure HTML form field names stay in sync with FastAPI endpoint
parameters. When either side changes, the contract tests catch mismatches
before they cause silent form failures.
"""

import inspect
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

import pytest

# Skip all tests if web dependencies aren't installed
pytest.importorskip("fastapi")

from fastapi import File, Form


# --- Helper Functions ---


class FormFieldParser(HTMLParser):
    """Parse HTML to extract form field names."""

    def __init__(self) -> None:
        super().__init__()
        self.field_names: set[str] = set()
        self._form_elements = {"input", "textarea", "select"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._form_elements:
            attr_dict = dict(attrs)
            name = attr_dict.get("name")
            if name:
                self.field_names.add(name)


def extract_form_fields(html_content: str) -> set[str]:
    """Parse HTML and return set of form field names.

    Extracts `name` attributes from <input>, <textarea>, and <select> elements.
    """
    parser = FormFieldParser()
    parser.feed(html_content)
    return parser.field_names


def get_form_params(endpoint_func: Callable[..., Any]) -> set[str]:
    """Inspect endpoint signature and return Form()/File() parameter names.

    Returns names of parameters that have Form() or File() as their default.
    """
    sig = inspect.signature(endpoint_func)
    form_params: set[str] = set()

    for name, param in sig.parameters.items():
        default = param.default
        # Check if default is a Form or File instance
        if isinstance(default, type(Form())):
            form_params.add(name)
        elif isinstance(default, type(File())):
            form_params.add(name)

    return form_params


# --- Path Helpers ---


def get_template_path(relative_path: str) -> Path:
    """Get absolute path to a template file."""
    return Path(__file__).parent.parent.parent / "agenttree" / "web" / "templates" / relative_path


# --- Contract Tests ---


class TestCreateIssueFormContract:
    """Contract tests for create issue modal form."""

    def test_create_issue_form_matches_api_params(self) -> None:
        """Verify new_issue_modal.html form fields match /api/issues params."""
        from agenttree.web.routes.issues import create_issue_api

        # Read the template
        template_path = get_template_path("partials/new_issue_modal.html")
        html_content = template_path.read_text()

        # Extract form fields from HTML
        html_fields = extract_form_fields(html_content)

        # Get expected parameters from API endpoint
        api_params = get_form_params(create_issue_api)

        # The form should have all required API fields
        # Note: 'files' is handled via JavaScript append, not static HTML
        expected_in_html = {"problem", "solutions", "title"}

        missing_in_html = expected_in_html - html_fields
        assert not missing_in_html, (
            f"HTML form missing required fields: {missing_in_html}. "
            f"HTML has: {html_fields}, API expects: {api_params}"
        )

        # Verify API also expects these fields (sanity check)
        api_form_fields = api_params - {"files"}  # files is File(), not Form()
        assert api_form_fields == expected_in_html, (
            f"API Form() params mismatch. Expected: {expected_in_html}, "
            f"Got: {api_form_fields}"
        )


class TestSendMessageFormContract:
    """Contract tests for agent send message form."""

    def test_send_message_form_matches_api_params(self) -> None:
        """Verify tmux_chat.html form fields match /agent/{id}/send params."""
        from agenttree.web.app import send_to_agent

        # Read the template
        template_path = get_template_path("partials/tmux_chat.html")
        html_content = template_path.read_text()

        # Extract form fields from HTML
        html_fields = extract_form_fields(html_content)

        # Get expected parameters from API endpoint
        api_params = get_form_params(send_to_agent)

        # The form must have the 'message' field
        assert "message" in html_fields, (
            f"HTML form missing 'message' field. "
            f"HTML has: {html_fields}, API expects: {api_params}"
        )
        assert "message" in api_params, (
            f"API endpoint missing 'message' parameter. "
            f"API has: {api_params}"
        )


class TestSettingsFormContract:
    """Contract tests for settings form."""

    def test_settings_form_matches_simple_settings(self) -> None:
        """Verify settings.html form fields match SIMPLE_SETTINGS keys."""
        from agenttree.web.app import SIMPLE_SETTINGS

        # Read the template
        template_path = get_template_path("settings.html")
        html_content = template_path.read_text()

        # Extract form fields from HTML
        html_fields = extract_form_fields(html_content)

        # Get expected fields from SIMPLE_SETTINGS
        expected_fields = set(SIMPLE_SETTINGS.keys())

        # Check that all SIMPLE_SETTINGS keys have corresponding HTML fields
        missing_in_html = expected_fields - html_fields
        assert not missing_in_html, (
            f"Settings form missing fields: {missing_in_html}. "
            f"HTML has: {html_fields}, SIMPLE_SETTINGS expects: {expected_fields}"
        )


# --- Helper Function Unit Tests ---


class TestExtractFormFields:
    """Unit tests for extract_form_fields helper."""

    def test_extracts_input_names(self) -> None:
        html = '<input type="text" name="username"><input type="password" name="password">'
        assert extract_form_fields(html) == {"username", "password"}

    def test_extracts_textarea_names(self) -> None:
        html = '<textarea name="content"></textarea>'
        assert extract_form_fields(html) == {"content"}

    def test_extracts_select_names(self) -> None:
        html = '<select name="country"><option>US</option></select>'
        assert extract_form_fields(html) == {"country"}

    def test_ignores_elements_without_name(self) -> None:
        html = '<input type="submit" value="Submit"><input name="field">'
        assert extract_form_fields(html) == {"field"}

    def test_handles_mixed_elements(self) -> None:
        html = """
        <form>
            <input name="a">
            <textarea name="b"></textarea>
            <select name="c"></select>
            <input name="d" type="checkbox">
        </form>
        """
        assert extract_form_fields(html) == {"a", "b", "c", "d"}


class TestGetFormParams:
    """Unit tests for get_form_params helper."""

    def test_extracts_form_params(self) -> None:
        def endpoint(name: str = Form(...), age: int = Form(0)) -> None:
            pass

        assert get_form_params(endpoint) == {"name", "age"}

    def test_extracts_file_params(self) -> None:
        def endpoint(doc: bytes = File(...)) -> None:
            pass

        assert get_form_params(endpoint) == {"doc"}

    def test_ignores_non_form_params(self) -> None:
        def endpoint(request: str, name: str = Form(...), limit: int = 10) -> None:
            pass

        assert get_form_params(endpoint) == {"name"}

    def test_handles_mixed_form_and_file(self) -> None:
        def endpoint(
            title: str = Form(...),
            upload: bytes = File(...),
            count: int = 5,
        ) -> None:
            pass

        assert get_form_params(endpoint) == {"title", "upload"}
