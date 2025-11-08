from bouquin.search import Search


def test_make_html_snippet_and_strip_markdown(qtbot, fresh_db):
    s = Search(fresh_db)
    long = (
        "This is **bold** text with alpha in the middle and some more trailing content."
    )
    frag, left, right = s._make_html_snippet(long, "alpha", radius=10, maxlen=40)
    assert "alpha" in frag
    s._strip_markdown("**bold** _italic_ ~~strike~~ 1. item - [x] check")
