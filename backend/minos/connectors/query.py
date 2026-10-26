from ..domain.targets import MonitoredTarget


def _quote(term: str) -> str:
    return f'"{term}"' if " " in term else term


def build_query(target: MonitoredTarget, include_exclusions: bool = True, or_operator: str = "OR", exclude_prefix: str = "-") -> str:
    """Consulta de búsqueda del objetivo con la sintaxis común: comillas, OR y exclusiones."""
    names = [_quote(n) for n in target.search_names()]
    query = names[0] if len(names) == 1 else "(" + f" {or_operator} ".join(names) + ")"
    if target.keywords:
        query += " (" + f" {or_operator} ".join(_quote(k) for k in target.keywords) + ")"
    if include_exclusions:
        for term in target.excluded_terms:
            query += f" {exclude_prefix}{_quote(term)}"
    return query
