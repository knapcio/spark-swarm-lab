"""Running SELECT queries.

Stages, in order: FROM and JOINs, WHERE, grouping and aggregates, HAVING,
ORDER BY, the select list, DISTINCT, OFFSET and LIMIT.

* ``JOIN ... ON`` keeps the pairs whose condition is TRUE, left rows first
  in their order and, for each, right rows in theirs.  ``LEFT JOIN`` also
  keeps unmatched left rows, padded with NULLs.
* A query with GROUP BY or any aggregate is grouped.  Groups appear in the
  order of their first row; NULL keys form one group.  Outside aggregates, a
  grouped query may only use columns it groups by.  Without GROUP BY, all
  rows form one group, even when there are none.
* ORDER BY items are output column names, 1-based output positions or
  expressions.  Sorting is stable: rows that tie on every ORDER BY item keep
  the order they had before sorting, in ascending and in descending order.
* DISTINCT keeps the first of each set of equal output rows.
"""
from .errors import GroupingError, QuarryError, UnknownTable
from .expr import Column, Group, Literal, Scope, Star, compile_expr, describe
from .functions import contains_aggregate
from .values import sort_key, truth


def _source(db, query):
    if query.table is None:
        return Scope(), [()]
    name, alias = query.table
    table = db.table(name)
    scope = Scope().extend(alias, [(c.name, c.type) for c in table.columns])
    rows, aliases = table.rows(), {alias}
    for (name, alias), condition, left in query.joins:
        if alias in aliases:
            raise QuarryError(f"table alias {alias} used twice")
        aliases.add(alias)
        right = db.table(name)
        scope = scope.extend(alias, [(c.name, c.type) for c in right.columns])
        test = compile_expr(condition, scope)
        right_rows, joined = right.rows(), []
        for row in rows:
            matched = False
            for other in right_rows:
                if truth(test(row + other), "ON") is True:
                    joined.append(row + other)
                    matched = True
            if left and not matched:
                joined.append(row + (None,) * len(right.columns))
        rows = joined
    return scope, rows


def _select_list(query, scope):
    """[(expression, output name)] with ``*`` expanded."""
    items = []
    for node, alias in query.items:
        if isinstance(node, Star):
            columns = [(q, n) for q, n, _ in scope.columns if node.table is None or q == node.table]
            if not columns:
                raise UnknownTable(node.table or "no table in FROM")
            items += [(Column(q, n), n) for q, n in columns]
        else:
            items.append((node, alias or (node.name if isinstance(node, Column) else describe(node))))
    return items


def _groups(query, scope, rows):
    keys = [compile_expr(node, scope) for node in query.group_by]
    grouped = {scope.resolve(node) for node in query.group_by if isinstance(node, Column)}
    if not keys:
        return grouped, [Group(rows)]
    groups = {}
    for row in rows:
        groups.setdefault(tuple(key(row) for key in keys), []).append(row)
    return grouped, [Group(members) for members in groups.values()]


def _order_keys(query, scope, items, grouped):
    names = [name for _, name in items]
    keys = []
    for node, descending in query.order_by:
        if isinstance(node, Column) and node.table is None and names.count(node.name) == 1:
            position = names.index(node.name)
            keys.append((lambda record, p=position: record[1][p], descending))
        elif isinstance(node, Literal) and type(node.value) is int:
            if not 1 <= node.value <= len(items):
                raise QuarryError(f"ORDER BY position {node.value} is out of range")
            keys.append((lambda record, p=node.value - 1: record[1][p], descending))
        else:
            function = compile_expr(node, scope, grouped)
            keys.append((lambda record, f=function: f(record[0]), descending))
    return keys


def run_select(db, query):
    """Returns ``(column names, rows)`` for a parsed :class:`~quarry.parser.Select`."""
    scope, rows = _source(db, query)
    if query.where is not None:
        condition = compile_expr(query.where, scope)
        rows = [row for row in rows if truth(condition(row), "WHERE") is True]
    items = _select_list(query, scope)
    nodes = [node for node, _ in items] + ([query.having] if query.having is not None else [])
    nodes += [node for node, _ in query.order_by]
    grouped = None
    if query.group_by or any(contains_aggregate(node) for node in nodes):
        grouped, contexts = _groups(query, scope, rows)
        if query.having is not None:
            having = compile_expr(query.having, scope, grouped)
            contexts = [group for group in contexts if truth(having(group), "HAVING") is True]
    elif query.having is not None:
        raise GroupingError("HAVING needs GROUP BY or an aggregate")
    else:
        contexts = rows
    outputs = [compile_expr(node, scope, grouped) for node, _ in items]
    records = [(context, tuple(output(context) for output in outputs)) for context in contexts]
    for function, descending in reversed(_order_keys(query, scope, items, grouped)):
        records.sort(key=lambda record: sort_key(function(record)), reverse=descending)
    result = [values for _, values in records]
    if query.distinct:
        unique = []
        for values in result:
            if values not in unique:
                unique.append(values)
        result = unique
    end = None if query.limit is None else query.offset + query.limit
    return [name for _, name in items], result[query.offset:end]
