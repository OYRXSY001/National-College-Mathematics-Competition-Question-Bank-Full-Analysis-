import json
import re
import subprocess

from django.conf import settings

FORMULA_DELIMITER_RE = re.compile(r"\\\(|\\\)|\\\[|\\\]")
OPENING_DELIMITERS = {
    r"\(": (r"\)", "行内"),
    r"\[": (r"\]", "块级"),
}
CLOSING_DELIMITERS = {
    r"\)": "行内",
    r"\]": "块级",
}


def extract_formulas(markdown_text):
    formulas = []
    opening = None
    expected_closing = None
    formula_start = None
    formula_kind = None

    for match in FORMULA_DELIMITER_RE.finditer(markdown_text or ""):
        delimiter = match.group()
        if opening is None:
            if delimiter in CLOSING_DELIMITERS:
                raise ValueError(
                    f"{CLOSING_DELIMITERS[delimiter]}公式结束定界符没有对应开始"
                )
            opening = delimiter
            expected_closing, formula_kind = OPENING_DELIMITERS[delimiter]
            formula_start = match.end()
        elif delimiter in OPENING_DELIMITERS or delimiter != expected_closing:
            raise ValueError("公式定界符交叉或嵌套")
        else:
            formulas.append(markdown_text[formula_start:match.start()])
            opening = None
            expected_closing = None
            formula_start = None
            formula_kind = None

    if opening is not None:
        raise ValueError(f"{formula_kind}公式定界符未闭合")
    return formulas


def validate_markdown_formulas(items):
    """返回 (issues, validator_ok)：issues 为公式定界符/语法问题列表；
    validator_ok=False 表示 node 校验器不可用（缺失或超时），调用方应
    将 KaTeX 校验降级为告警而不是阻断流程。"""
    issues = []
    validator_ok = True
    formulas = []
    sources = []

    for source, text in items:
        text = text or ""
        try:
            extracted = extract_formulas(text)
        except ValueError as error:
            issues.append(f"{source}: {error}")
            continue
        for formula in extracted:
            formulas.append(formula)
            sources.append(source)

    if not formulas:
        return issues, validator_ok

    try:
        result = subprocess.run(
            ["node", str(settings.BASE_DIR / "scripts" / "validate-katex.mjs")],
            input=json.dumps(formulas, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=30,
            check=False,
            cwd=settings.BASE_DIR,
        )
    except (OSError, subprocess.TimeoutExpired):
        return issues, False

    if result.returncode != 0:
        return [*issues, f"KaTeX 校验器退出码 {result.returncode}: {result.stderr.strip()}"], validator_ok

    for error in json.loads(result.stdout or "[]"):
        issues.append(f"{sources[error['index']]}: {error['message']}")
    return issues, validator_ok
