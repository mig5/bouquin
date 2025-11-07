import pytest
from bouquin.search import Search


@pytest.fixture
def search_widget(qapp):
    # We don't need a real DB for snippet generation – pass None
    return Search(db=None)


def test_make_html_snippet_empty(search_widget: Search):
    html = ""
    frag, has_prev, has_next = search_widget._make_html_snippet(
        html, "", radius=10, maxlen=20
    )
    assert frag == "" and has_prev is False and has_next is False


def test_make_html_snippet_phrase_preferred(search_widget: Search):
    html = "<p>Alpha beta gamma delta</p>"
    frag, has_prev, has_next = search_widget._make_html_snippet(
        html, "beta gamma", radius=1, maxlen=10
    )
    # We expect a window that includes the phrase and has previous text
    assert "beta" in frag and "gamma" in frag
    assert has_prev is True


def test_make_html_snippet_token_fallback_and_window_flags(search_widget: Search):
    html = "<p>One two three four five six seven eight nine ten eleven twelve</p>"
    # Use tokens such that the phrase doesn't exist, but individual tokens do
    frag, has_prev, has_next = search_widget._make_html_snippet(
        html, "eleven two", radius=3, maxlen=20
    )
    assert "two" in frag
    # The snippet should be a slice within the text (has more following content)
    assert has_next is True
