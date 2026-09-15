# -*- coding: utf-8 -*-
"""Konservative Klassifikation von SQL-Anweisungen für die Mediathek-Konsole."""
from __future__ import annotations

import re

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_WRITE_KEYWORDS = {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP", "VACUUM", "ATTACH", "DETACH", "REINDEX"}
_READ_PRAGMAS = {
    "collation_list",
    "compile_options",
    "database_list",
    "foreign_key_list",
    "function_list",
    "index_info",
    "index_list",
    "index_xinfo",
    "integrity_check",
    "module_list",
    "pragma_list",
    "quick_check",
    "table_info",
    "table_list",
    "table_xinfo",
}


def _tokens(sql: str) -> list[str]:
    """Lex SQL enough to classify read-only statements without executing them.

    String literals, quoted identifiers and comments are skipped so keywords in
    text values cannot accidentally turn a SELECT into a write statement.
    """
    text = str(sql or "")
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if text.startswith("--", i):
            end = text.find("\n", i + 2)
            i = n if end < 0 else end + 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                return []
            i = end + 2
            continue
        if ch in {"'", '"', "`"}:
            quote = ch
            i += 1
            while i < n:
                if text[i] == quote:
                    if i + 1 < n and text[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if ch == "[":
            end = text.find("]", i + 1)
            if end < 0:
                return []
            i = end + 1
            continue
        match = _WORD_RE.match(text, i)
        if match:
            out.append(match.group(0).upper())
            i = match.end()
            continue
        if ch in "(),;=":
            out.append(ch)
        i += 1
    return out


def _single_statement(tokens: list[str]) -> list[str] | None:
    if not tokens:
        return None
    if ";" not in tokens:
        return tokens
    first = tokens.index(";")
    # Nur ein optionales abschließendes Semikolon ist für read-only erlaubt.
    if any(token != ";" for token in tokens[first + 1 :]):
        return None
    if any(token == ";" for token in tokens[:first]):
        return None
    return tokens[:first]


def _pragma_is_read_only(tokens: list[str]) -> bool:
    if len(tokens) < 2 or "=" in tokens:
        return False
    # PRAGMA schema.table_info(...) -> letzter Name vor '(' ist der Pragma-Name.
    names = [token.lower() for token in tokens[1:] if token not in {"(", ")", ","}]
    if not names:
        return False
    pragma_name = names[-1] if len(names) == 1 else names[0]
    # Bei optionalem Schema-Prefix erkennt der Lexer den Punkt nicht; dadurch
    # stehen zwei Namen hinter PRAGMA. Der letzte bekannte Name gewinnt.
    for name in reversed(names):
        if name in _READ_PRAGMAS:
            pragma_name = name
            break
    return pragma_name in _READ_PRAGMAS


def _with_terminal_keyword(tokens: list[str]) -> str | None:
    depth = 0
    seen_cte_close = False
    for token in tokens[1:]:
        if token == "(":
            depth += 1
            continue
        if token == ")":
            depth = max(0, depth - 1)
            if depth == 0:
                seen_cte_close = True
            continue
        if token in _WRITE_KEYWORDS and depth > 0:
            # Konservativ: schreibende Tokens innerhalb eines CTE niemals als
            # read-only einstufen, selbst wenn eine SQLite-Version sie ablehnt.
            return token
        if depth == 0 and seen_cte_close and token in {"SELECT", "VALUES", "INSERT", "UPDATE", "DELETE", "REPLACE"}:
            return token
    return None


def sql_is_read_only(sql: str) -> bool:
    """Return True only when *sql* is confidently a single read-only query."""
    tokens = _single_statement(_tokens(sql))
    if not tokens:
        return False
    first = tokens[0]
    if first in {"SELECT", "VALUES"}:
        return not any(token in _WRITE_KEYWORDS for token in tokens[1:])
    if first == "PRAGMA":
        return _pragma_is_read_only(tokens)
    if first == "EXPLAIN":
        rest = tokens[1:]
        if rest[:2] == ["QUERY", "PLAN"]:
            rest = rest[2:]
        if not rest:
            return False
        return _classify_tokens(rest)
    if first == "WITH":
        terminal = _with_terminal_keyword(tokens)
        return terminal in {"SELECT", "VALUES"}
    return False


def _classify_tokens(tokens: list[str]) -> bool:
    if not tokens:
        return False
    first = tokens[0]
    if first in {"SELECT", "VALUES"}:
        return not any(token in _WRITE_KEYWORDS for token in tokens[1:])
    if first == "WITH":
        return _with_terminal_keyword(tokens) in {"SELECT", "VALUES"}
    if first == "PRAGMA":
        return _pragma_is_read_only(tokens)
    return False


__all__ = ["sql_is_read_only"]
