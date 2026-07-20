from __future__ import annotations


def classify_failure(type_str: str, exit_code: int, has_summary: bool) -> str:
    t = (type_str or "").lower()
    if "importerror" in t or "modulenotfounderror" in t:
        return "import_error"
    if "syntaxerror" in t:
        return "syntax_error"
    if "timeout" in t:
        return "timeout"
    if "assertionerror" in t or "assert" in t:
        return "assertion_failure"
    if exit_code == 2 and not has_summary:
        return "collection_error"
    return "other"
