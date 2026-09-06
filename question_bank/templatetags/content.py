import re
from html import escape, unescape
from html.parser import HTMLParser

import markdown
from django import template
from django.utils.safestring import mark_safe

register = template.Library()
LATEX_RE = re.compile(r"\\\[.*?\\\]|\\\(.*?\\\)", re.DOTALL)

# 输出阶段属性白名单：markdown 的 attr_list 等扩展可生成任意属性，
# 一律过滤为仅保留展示类属性，杜绝 on* / style 等属性注入。
ALLOWED_HTML_ATTRS = {
    "href", "src", "alt", "title", "class", "id",
    "width", "height", "colspan", "rowspan", "rel",
}
# 即使是白名单内的 URL 属性，也只允许无害协议（JS 协议等一律丢弃）。
UNSAFE_URL_ATTRS = {"href", "src"}


class _AttributeSanitizer(HTMLParser):
    """按白名单重建标签属性，属性值统一转义，保证输出无事件处理器。"""

    def __init__(self):
        # convert_charrefs=False：保留原始实体文本，避免双重解码破坏占位符
        super().__init__(convert_charrefs=False)
        self.parts = []

    def _render_tag(self, tag, attrs):
        kept = []
        for name, value in attrs:
            if name.lower() not in ALLOWED_HTML_ATTRS:
                continue
            if name.lower() in UNSAFE_URL_ATTRS:
                value = _sanitize_url_value(value or "")
                if value is None:
                    continue
            if value is None:
                kept.append(name)
            else:
                kept.append(f'{name}="{escape(value, quote=True)}"')
        if not kept:
            return f"<{tag}>"
        return f"<{tag} " + " ".join(kept) + ">"

    def handle_starttag(self, tag, attrs):
        self.parts.append(self._render_tag(tag, attrs))

    def handle_startendtag(self, tag, attrs):
        self.parts.append(self._render_tag(tag, attrs))

    def handle_endtag(self, tag):
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        self.parts.append(data)

    def handle_entityref(self, name):
        self.parts.append(f"&{name};")

    def handle_charref(self, name):
        self.parts.append(f"&#{name};")

    def handle_comment(self, data):
        self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl):
        self.parts.append(f"<!{decl}>")

    def handle_pi(self, data):
        self.parts.append(f"<?{data}>")


def _sanitize_url_value(value: str):
    """http/https（href 另允许 mailto）之外一律去掉该属性。"""
    decoded = _unescape_url(value).strip()
    if ":" in decoded:
        scheme = decoded.split(":", 1)[0]
        scheme = re.sub(r"[\x00-\x20\x7f]+", "", scheme).lower()
        if scheme not in {"http", "https", "mailto"}:
            return None
    return decoded


def _sanitize_html_attributes(rendered):
    parser = _AttributeSanitizer()
    parser.feed(rendered)
    parser.close()
    return "".join(parser.parts)


def _unescape_url(value):
    for _ in range(5):
        decoded = unescape(value)
        if decoded == value:
            return decoded
        value = decoded
    return value


def _protect_latex(value):
    placeholders = {}

    def replace(match):
        index = len(placeholders)
        marker = f"\ue000katex-formula-{index}\ue001"
        while marker in value or marker in placeholders:
            index += 1
            marker = f"\ue000katex-formula-{index}\ue001"
        placeholders[marker] = match.group()
        return marker

    return LATEX_RE.sub(replace, value), placeholders


@register.filter
def render_markdown(value):
    escaped = escape(value or "")
    escaped, placeholders = _protect_latex(escaped)
    # 不使用 "extra" 扩展包：其 attr_list 允许给元素附加任意属性（事件处理器）；
    # 显式只启用需求内的子扩展，再加一层输出属性白名单兜底。
    rendered = markdown.markdown(
        escaped,
        extensions=[
            "abbr",
            "def_list",
            "fenced_code",
            "footnotes",
            "sane_lists",
            "tables",
            "nl2br",
        ],
        output_format="html5",
    )
    rendered = _sanitize_html_attributes(rendered)
    for placeholder, formula in placeholders.items():
        rendered = rendered.replace(placeholder, formula)
    return mark_safe(rendered)