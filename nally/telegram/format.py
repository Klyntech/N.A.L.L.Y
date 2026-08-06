"""Convert Markdown to Telegram-compatible HTML.

Telegram's HTML parser supports: <b>, <i>, <code>, <pre>, <a>.
It does NOT support Markdown syntax like **bold** or `code`.
"""

import re


def _convert_tables(text: str) -> str:
    """Convert markdown tables to readable key-value format wrapped in <pre>.

    Telegram's HTML parser doesn't support <table> tags. This converts
    markdown tables to "Header: Value | Header: Value" format for readability.
    """
    lines = text.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Detect table: line starts and ends with |, next line is separator
        if (
            line.startswith("|")
            and line.endswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip())
        ):
            # Parse header row
            headers = [h.strip() for h in line.split("|")[1:-1]]

            # Skip separator line
            i += 2

            # Parse data rows
            rows = []
            while i < len(lines):
                row_line = lines[i].strip()
                if not row_line.startswith("|") or not row_line.endswith("|"):
                    break
                cells = [c.strip() for c in row_line.split("|")[1:-1]]
                rows.append(cells)
                i += 1

            # Format as Header: Value pairs, wrapped in <pre>
            if headers and rows:
                table_lines = []
                for row in rows:
                    parts = []
                    for j, header in enumerate(headers):
                        val = row[j] if j < len(row) else ""
                        if val:
                            parts.append(f"{header}: {val}")
                    table_lines.append(" | ".join(parts))
                result.append("<pre>" + "\n".join(table_lines) + "</pre>")
            continue

        result.append(lines[i])
        i += 1

    return "\n".join(result)


def md_to_telegram_html(text: str) -> str:
    """Convert Markdown to Telegram-compatible HTML.

    Handles: bold, italic, code, code blocks, headers, lists, tables.
    Escapes HTML special chars in the source text first.
    """
    if not text:
        return ""

    # 0. Escape HTML special chars (must be first)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")

    # 1. Convert tables AFTER escaping (tables add <pre> tags safely)
    text = _convert_tables(text)

    # 2. Code blocks (```...```) — must come before inline code
    text = re.sub(
        r"```(\w*)\n?(.*?)```",
        r"<pre><code class=\"language-\1\">\2</code></pre>",
        text,
        flags=re.DOTALL,
    )

    # 3. Inline code (`...`)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    # 4. Bold (**...**)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # 5. Italic (*...*) — but not inside tags we just created
    text = re.sub(r"(?<!\w)\*(?!\*)(.+?)(?<!\*)\*(?!\w)", r"<i>\1</i>", text)

    # 6. Headers (# ... → bold)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # 7. Unordered lists (- ... → bullet)
    text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.MULTILINE)

    # 8. Horizontal rules (--- or ***) → line
    text = re.sub(r"^[-*_]{3,}\s*$", "──────────", text, flags=re.MULTILINE)

    return text
