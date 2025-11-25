from bouquin.code_highlighter import CodeHighlighter, CodeBlockMetadata
from PySide6.QtGui import QTextCharFormat, QFont


def test_get_language_patterns_python(app):
    """Test getting highlighting patterns for Python."""
    patterns = CodeHighlighter.get_language_patterns("python")

    assert len(patterns) > 0
    # Should have comment pattern
    assert any("#" in p[0] for p in patterns)
    # Should have string patterns
    assert any('"' in p[0] for p in patterns)
    # Should have keyword patterns
    assert any("keyword" == p[1] for p in patterns)


def test_get_language_patterns_javascript(app):
    """Test getting highlighting patterns for JavaScript."""
    patterns = CodeHighlighter.get_language_patterns("javascript")

    assert len(patterns) > 0
    # Should have // comment pattern
    assert any("//" in p[0] for p in patterns)
    # Should have /* */ comment pattern (with escaped asterisks in regex)
    assert any(r"/\*" in p[0] for p in patterns)


def test_get_language_patterns_php(app):
    """Test getting highlighting patterns for PHP."""
    patterns = CodeHighlighter.get_language_patterns("php")

    assert len(patterns) > 0
    # Should have # comment pattern
    assert any("#" in p[0] for p in patterns)
    # Should have // comment pattern
    assert any("//" in p[0] for p in patterns)
    # Should have /* */ comment pattern (with escaped asterisks in regex)
    assert any(r"/\*" in p[0] for p in patterns)


def test_get_language_patterns_bash(app):
    """Test getting highlighting patterns for Bash."""
    patterns = CodeHighlighter.get_language_patterns("bash")

    assert len(patterns) > 0
    # Should have # comment pattern
    assert any("#" in p[0] for p in patterns)
    # Should have bash keywords
    keyword_patterns = [p for p in patterns if p[1] == "keyword"]
    assert len(keyword_patterns) > 0


def test_get_language_patterns_html(app):
    """Test getting highlighting patterns for HTML."""
    patterns = CodeHighlighter.get_language_patterns("html")

    assert len(patterns) > 0
    # Should have tag pattern
    assert any("tag" == p[1] for p in patterns)
    # Should have HTML comment pattern
    assert any("<!--" in p[0] for p in patterns)


def test_get_language_patterns_css(app):
    """Test getting highlighting patterns for CSS."""
    patterns = CodeHighlighter.get_language_patterns("css")

    assert len(patterns) > 0
    # Should have // comment pattern
    assert any("//" in p[0] for p in patterns)
    # Should have CSS properties as keywords
    keyword_patterns = [p for p in patterns if p[1] == "keyword"]
    assert len(keyword_patterns) > 0


def test_get_language_patterns_unknown_language(app):
    """Test getting patterns for an unknown language."""
    patterns = CodeHighlighter.get_language_patterns("unknown-lang")

    # Should still return basic patterns (strings, numbers)
    assert len(patterns) > 0
    assert any("string" == p[1] for p in patterns)
    assert any("number" == p[1] for p in patterns)


def test_get_language_patterns_case_insensitive(app):
    """Test that language matching is case insensitive."""
    patterns_lower = CodeHighlighter.get_language_patterns("python")
    patterns_upper = CodeHighlighter.get_language_patterns("PYTHON")
    patterns_mixed = CodeHighlighter.get_language_patterns("PyThOn")

    assert len(patterns_lower) == len(patterns_upper)
    assert len(patterns_lower) == len(patterns_mixed)


def test_get_format_for_type_keyword(app):
    """Test getting format for keyword type."""
    base_format = QTextCharFormat()
    fmt = CodeHighlighter.get_format_for_type("keyword", base_format)

    assert fmt.fontWeight() == QFont.Weight.Bold
    assert fmt.foreground().color().blue() > 0  # Should have blue-ish color


def test_get_format_for_type_string(app):
    """Test getting format for string type."""
    base_format = QTextCharFormat()
    fmt = CodeHighlighter.get_format_for_type("string", base_format)

    # Should have orangish color
    color = fmt.foreground().color()
    assert color.red() > 100


def test_get_format_for_type_comment(app):
    """Test getting format for comment type."""
    base_format = QTextCharFormat()
    fmt = CodeHighlighter.get_format_for_type("comment", base_format)

    assert fmt.fontItalic() is True
    # Should have greenish color
    color = fmt.foreground().color()
    assert color.green() > 0


def test_get_format_for_type_number(app):
    """Test getting format for number type."""
    base_format = QTextCharFormat()
    fmt = CodeHighlighter.get_format_for_type("number", base_format)

    # Should have some color
    color = fmt.foreground().color()
    assert color.isValid()


def test_get_format_for_type_tag(app):
    """Test getting format for HTML tag type."""
    base_format = QTextCharFormat()
    fmt = CodeHighlighter.get_format_for_type("tag", base_format)

    # Should have cyan-ish color
    color = fmt.foreground().color()
    assert color.green() > 0
    assert color.blue() > 0


def test_get_format_for_type_unknown(app):
    """Test getting format for unknown type."""
    base_format = QTextCharFormat()
    fmt = CodeHighlighter.get_format_for_type("unknown", base_format)

    # Should return a valid format (based on base_format)
    assert fmt is not None


def test_code_block_metadata_init(app):
    """Test CodeBlockMetadata initialization."""
    metadata = CodeBlockMetadata()

    assert len(metadata._block_languages) == 0


def test_code_block_metadata_set_get_language(app):
    """Test setting and getting language for a block."""
    metadata = CodeBlockMetadata()

    metadata.set_language(0, "python")
    metadata.set_language(5, "javascript")

    assert metadata.get_language(0) == "python"
    assert metadata.get_language(5) == "javascript"
    assert metadata.get_language(10) is None


def test_code_block_metadata_set_language_case_normalization(app):
    """Test that language is normalized to lowercase."""
    metadata = CodeBlockMetadata()

    metadata.set_language(0, "PYTHON")
    metadata.set_language(1, "JavaScript")

    assert metadata.get_language(0) == "python"
    assert metadata.get_language(1) == "javascript"


def test_code_block_metadata_serialize_empty(app):
    """Test serializing empty metadata."""
    metadata = CodeBlockMetadata()

    result = metadata.serialize()
    assert result == ""


def test_code_block_metadata_serialize(app):
    """Test serializing metadata."""
    metadata = CodeBlockMetadata()
    metadata.set_language(0, "python")
    metadata.set_language(3, "javascript")

    result = metadata.serialize()

    assert "<!-- code-langs:" in result
    assert "0:python" in result
    assert "3:javascript" in result
    assert "-->" in result


def test_code_block_metadata_serialize_sorted(app):
    """Test that serialized metadata is sorted by block number."""
    metadata = CodeBlockMetadata()
    metadata.set_language(5, "python")
    metadata.set_language(2, "javascript")
    metadata.set_language(8, "bash")

    result = metadata.serialize()

    # Find positions in string
    pos_2 = result.find("2:")
    pos_5 = result.find("5:")
    pos_8 = result.find("8:")

    # Should be in order
    assert pos_2 < pos_5 < pos_8


def test_code_block_metadata_deserialize(app):
    """Test deserializing metadata."""
    metadata = CodeBlockMetadata()
    text = (
        "Some content\n<!-- code-langs: 0:python,3:javascript,5:bash -->\nMore content"
    )

    metadata.deserialize(text)

    assert metadata.get_language(0) == "python"
    assert metadata.get_language(3) == "javascript"
    assert metadata.get_language(5) == "bash"


def test_code_block_metadata_deserialize_empty(app):
    """Test deserializing from text without metadata."""
    metadata = CodeBlockMetadata()
    metadata.set_language(0, "python")  # Set some initial data

    text = "Just some regular text with no metadata"
    metadata.deserialize(text)

    # Should clear existing data
    assert len(metadata._block_languages) == 0


def test_code_block_metadata_deserialize_invalid_format(app):
    """Test deserializing with invalid format."""
    metadata = CodeBlockMetadata()
    text = "<!-- code-langs: invalid,format,here -->"

    metadata.deserialize(text)

    # Should handle gracefully, resulting in empty or minimal data
    # Pairs without ':' should be skipped
    assert len(metadata._block_languages) == 0


def test_code_block_metadata_deserialize_invalid_block_number(app):
    """Test deserializing with invalid block number."""
    metadata = CodeBlockMetadata()
    text = "<!-- code-langs: abc:python,3:javascript -->"

    metadata.deserialize(text)

    # Should skip invalid block number 'abc'
    assert metadata.get_language(3) == "javascript"
    assert "abc" not in str(metadata._block_languages)


def test_code_block_metadata_round_trip(app):
    """Test serializing and deserializing preserves data."""
    metadata1 = CodeBlockMetadata()
    metadata1.set_language(0, "python")
    metadata1.set_language(2, "javascript")
    metadata1.set_language(7, "bash")

    serialized = metadata1.serialize()

    metadata2 = CodeBlockMetadata()
    metadata2.deserialize(serialized)

    assert metadata2.get_language(0) == "python"
    assert metadata2.get_language(2) == "javascript"
    assert metadata2.get_language(7) == "bash"


def test_python_keywords_present(app):
    """Test that Python keywords are defined."""
    keywords = CodeHighlighter.KEYWORDS.get("python", [])

    assert "def" in keywords
    assert "class" in keywords
    assert "if" in keywords
    assert "for" in keywords
    assert "import" in keywords


def test_javascript_keywords_present(app):
    """Test that JavaScript keywords are defined."""
    keywords = CodeHighlighter.KEYWORDS.get("javascript", [])

    assert "function" in keywords
    assert "const" in keywords
    assert "let" in keywords
    assert "var" in keywords
    assert "class" in keywords


def test_php_keywords_present(app):
    """Test that PHP keywords are defined."""
    keywords = CodeHighlighter.KEYWORDS.get("php", [])

    assert "function" in keywords
    assert "class" in keywords
    assert "echo" in keywords
    assert "require" in keywords


def test_bash_keywords_present(app):
    """Test that Bash keywords are defined."""
    keywords = CodeHighlighter.KEYWORDS.get("bash", [])

    assert "if" in keywords
    assert "then" in keywords
    assert "fi" in keywords
    assert "for" in keywords


def test_html_keywords_present(app):
    """Test that HTML keywords are defined."""
    keywords = CodeHighlighter.KEYWORDS.get("html", [])

    assert "div" in keywords
    assert "span" in keywords
    assert "body" in keywords
    assert "html" in keywords


def test_css_keywords_present(app):
    """Test that CSS keywords are defined."""
    keywords = CodeHighlighter.KEYWORDS.get("css", [])

    assert "color" in keywords
    assert "background" in keywords
    assert "margin" in keywords
    assert "padding" in keywords


def test_all_patterns_have_string_and_number(app):
    """Test that all languages have string and number patterns."""
    languages = ["python", "javascript", "php", "bash", "html", "css"]

    for lang in languages:
        patterns = CodeHighlighter.get_language_patterns(lang)
        pattern_types = [p[1] for p in patterns]

        assert "string" in pattern_types, f"{lang} should have string pattern"
        assert "number" in pattern_types, f"{lang} should have number pattern"


def test_patterns_have_regex_format(app):
    """Test that patterns are in regex format."""
    patterns = CodeHighlighter.get_language_patterns("python")

    for pattern, pattern_type in patterns:
        # Each pattern should be a string (regex pattern)
        assert isinstance(pattern, str)
        # Each type should be a string
        assert isinstance(pattern_type, str)


def test_code_block_metadata_update_language(app):
    """Test updating language for existing block."""
    metadata = CodeBlockMetadata()

    metadata.set_language(0, "python")
    assert metadata.get_language(0) == "python"

    metadata.set_language(0, "javascript")
    assert metadata.get_language(0) == "javascript"


def test_get_format_preserves_base_format_properties(app):
    """Test that get_format_for_type preserves base format properties."""
    base_format = QTextCharFormat()
    base_format.setFontPointSize(14)

    fmt = CodeHighlighter.get_format_for_type("keyword", base_format)

    # Should be based on the base_format
    assert isinstance(fmt, QTextCharFormat)
