from __future__ import annotations

import re
from typing import Dict, Optional

from PySide6.QtGui import QColor, QFont, QTextCharFormat


class CodeHighlighter:
    """Syntax highlighter for different programming languages."""

    # Language keywords
    KEYWORDS = {
        "python": [
            "False",
            "None",
            "True",
            "and",
            "as",
            "assert",
            "async",
            "await",
            "break",
            "class",
            "continue",
            "def",
            "del",
            "elif",
            "else",
            "except",
            "finally",
            "for",
            "from",
            "global",
            "if",
            "import",
            "in",
            "is",
            "lambda",
            "nonlocal",
            "not",
            "or",
            "pass",
            "pprint",
            "print",
            "raise",
            "return",
            "try",
            "while",
            "with",
            "yield",
        ],
        "javascript": [
            "abstract",
            "arguments",
            "await",
            "boolean",
            "break",
            "byte",
            "case",
            "catch",
            "char",
            "class",
            "const",
            "continue",
            "debugger",
            "default",
            "delete",
            "do",
            "double",
            "else",
            "enum",
            "eval",
            "export",
            "extends",
            "false",
            "final",
            "finally",
            "float",
            "for",
            "function",
            "goto",
            "if",
            "implements",
            "import",
            "in",
            "instanceof",
            "int",
            "interface",
            "let",
            "long",
            "native",
            "new",
            "null",
            "package",
            "private",
            "protected",
            "public",
            "return",
            "short",
            "static",
            "super",
            "switch",
            "synchronized",
            "this",
            "throw",
            "throws",
            "transient",
            "true",
            "try",
            "typeof",
            "var",
            "void",
            "volatile",
            "while",
            "with",
            "yield",
        ],
        "php": [
            "abstract",
            "and",
            "array",
            "as",
            "break",
            "callable",
            "case",
            "catch",
            "class",
            "clone",
            "const",
            "continue",
            "declare",
            "default",
            "die",
            "do",
            "echo",
            "else",
            "elseif",
            "empty",
            "enddeclare",
            "endfor",
            "endforeach",
            "endif",
            "endswitch",
            "endwhile",
            "eval",
            "exit",
            "extends",
            "final",
            "for",
            "foreach",
            "function",
            "global",
            "goto",
            "if",
            "implements",
            "include",
            "include_once",
            "instanceof",
            "insteadof",
            "interface",
            "isset",
            "list",
            "namespace",
            "new",
            "or",
            "print",
            "print_r",
            "private",
            "protected",
            "public",
            "require",
            "require_once",
            "return",
            "static",
            "syslog",
            "switch",
            "throw",
            "trait",
            "try",
            "unset",
            "use",
            "var",
            "var_dump",
            "while",
            "xor",
            "yield",
        ],
        "bash": [
            "if",
            "then",
            "echo",
            "else",
            "elif",
            "fi",
            "case",
            "esac",
            "for",
            "select",
            "while",
            "until",
            "do",
            "done",
            "in",
            "function",
            "time",
            "coproc",
        ],
        "html": [
            "DOCTYPE",
            "html",
            "head",
            "title",
            "meta",
            "link",
            "style",
            "script",
            "body",
            "div",
            "span",
            "p",
            "a",
            "img",
            "ul",
            "ol",
            "li",
            "table",
            "tr",
            "td",
            "th",
            "form",
            "input",
            "button",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "br",
            "hr",
        ],
        "css": [
            "color",
            "background",
            "background-color",
            "border",
            "margin",
            "padding",
            "width",
            "height",
            "font",
            "font-size",
            "font-weight",
            "display",
            "position",
            "top",
            "left",
            "right",
            "bottom",
            "float",
            "clear",
            "overflow",
            "z-index",
            "opacity",
        ],
    }

    @staticmethod
    def get_language_patterns(language: str) -> list:
        """Get highlighting patterns for a language."""
        patterns = []

        keywords = CodeHighlighter.KEYWORDS.get(language.lower(), [])

        if language.lower() in ["python", "bash", "php"]:
            # Comments (#)
            patterns.append((r"#.*$", "comment"))

        if language.lower() in ["javascript", "php", "css"]:
            # Comments (//)
            patterns.append((r"//.*$", "comment"))
            # Multi-line comments (/* */)
            patterns.append((r"/\*.*?\*/", "comment"))

        if language.lower() in ["html", "xml"]:
            # HTML/XML tags
            patterns.append((r"<[^>]+>", "tag"))
            # HTML comments
            patterns.append((r"<!--.*?-->", "comment"))

        # Numbers
        patterns.append((r"\b\d+\.?\d*\b", "number"))

        # Keywords
        for keyword in keywords:
            patterns.append((r"\b" + keyword + r"\b", "keyword"))

        # Do strings last so they override any of the above (e.g reserved keywords in strings)

        # Strings (double quotes)
        patterns.append((r'"[^"\\]*(\\.[^"\\]*)*"', "string"))

        # Strings (single quotes)
        patterns.append((r"'[^'\\]*(\\.[^'\\]*)*'", "string"))

        return patterns

    @staticmethod
    def get_format_for_type(
        format_type: str, base_format: QTextCharFormat
    ) -> QTextCharFormat:
        """Get text format for a specific syntax type."""
        fmt = QTextCharFormat(base_format)

        if format_type == "keyword":
            fmt.setForeground(QColor(86, 156, 214))  # Blue
            fmt.setFontWeight(QFont.Weight.Bold)
        elif format_type == "string":
            fmt.setForeground(QColor(206, 145, 120))  # Orange
        elif format_type == "comment":
            fmt.setForeground(QColor(106, 153, 85))  # Green
            fmt.setFontItalic(True)
        elif format_type == "number":
            fmt.setForeground(QColor(181, 206, 168))  # Light green
        elif format_type == "tag":
            fmt.setForeground(QColor(78, 201, 176))  # Cyan

        return fmt


class CodeBlockMetadata:
    """Stores metadata about code blocks (language, etc.) for a document."""

    def __init__(self):
        self._block_languages: Dict[int, str] = {}  # block_number -> language

    def set_language(self, block_number: int, language: str):
        """Set the language for a code block."""
        self._block_languages[block_number] = language.lower()

    def get_language(self, block_number: int) -> Optional[str]:
        """Get the language for a code block."""
        return self._block_languages.get(block_number)

    def serialize(self) -> str:
        """Serialize metadata to a string."""
        # Store as JSON-like format in a comment at the end
        if not self._block_languages:
            return ""

        items = [f"{k}:{v}" for k, v in sorted(self._block_languages.items())]
        return "<!-- code-langs: " + ",".join(items) + " -->\n"

    def deserialize(self, text: str):
        """Deserialize metadata from text."""
        self._block_languages.clear()

        # Look for metadata comment at the end
        match = re.search(r"<!-- code-langs: ([^>]+) -->", text)
        if match:
            pairs = match.group(1).split(",")
            for pair in pairs:
                if ":" in pair:
                    block_num, lang = pair.split(":", 1)
                    try:
                        self._block_languages[int(block_num)] = lang
                    except ValueError:
                        pass

    def clear_language(self, block_number: int):
        """Remove any stored language for a given block, if present."""
        self._block_languages.pop(block_number, None)
