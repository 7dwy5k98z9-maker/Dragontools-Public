"""Structural review signals; comments, tables and physical line counts do not count.

These checks complement (not replace) the explicit ownership/import contracts in
the architecture tests. They cannot infer a domain responsibility from syntax.
"""
import ast


def decision_complexity(node):
    score = 1
    def visit(current):
        nonlocal score
        if current is not node and isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        if isinstance(current, (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While,
                                ast.ExceptHandler, ast.comprehension, ast.match_case)):
            score += 1
        elif isinstance(current, ast.BoolOp):
            score += len(current.values) - 1
        for child in ast.iter_child_nodes(current):
            visit(child)
    visit(node)
    return score


def structural_risks(source):
    tree = ast.parse(source)
    risks = {}
    def walk_scope(body, prefix=''):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + node.name
                score = decision_complexity(node)
                if score > 25:
                    risks['function:' + name] = max(score, risks.get('function:' + name, 0))
                walk_scope(node.body, name + '.')
            elif isinstance(node, ast.ClassDef):
                methods = list(scope_methods(node.body))
                # Forwarding methods and data fields do not make a god class.
                decisions = sum(decision_complexity(n) - 1 for n in methods)
                substantial = sum(decision_complexity(n) > 5 for n in methods)
                if decisions > 100:
                    risks['class-decisions:' + prefix + node.name] = decisions
                if substantial > 8:
                    risks['class-behaviors:' + prefix + node.name] = substantial
                walk_scope(node.body, prefix + node.name + '.')
            else:
                # Definitions can live inside conditionals, try/except, loops
                # and context managers; those do not create a Python scope.
                walk_scope(ast.iter_child_nodes(node), prefix)
    walk_scope(tree.body)
    return risks


def scope_methods(body):
    """Conditional blocks do not introduce a new scope; nested classes do."""
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node
        elif not isinstance(node, ast.ClassDef):
            yield from scope_methods(ast.iter_child_nodes(node))
