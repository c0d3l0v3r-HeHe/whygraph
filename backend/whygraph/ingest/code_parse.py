"""Extract code entities (functions, classes, methods, attributes, constants,
config keys) with line spans from Python source using tree-sitter."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

PY = Language(tspython.language())
_parser = Parser(PY)

UPPER = re.compile(r"^[A-Z][A-Z0-9_]+$")


@dataclass
class Entity:
    id: str
    path: str
    name: str
    qualname: str
    kind: str  # module | class | function | method | attribute | constant | config
    start: int  # 1-based inclusive
    end: int
    parent: str | None = None
    doc: str = ""
    signature: str = ""

    def to_dict(self):
        return asdict(self)


def _text(n: Node | None) -> str:
    return n.text.decode("utf-8", "replace") if n is not None and n.text else ""


def _docstring(body: Node | None) -> str:
    if body is None:
        return ""
    for child in body.children:
        if child.type == "expression_statement" and child.children and child.children[0].type == "string":
            s = _text(child.children[0]).strip("\"' \n\r\t")
            return s.strip().split("\n\n")[0].replace("\n", " ")[:300]
        if child.type not in ("comment",):
            break
    return ""


def _span(n: Node) -> tuple[int, int]:
    return n.start_point[0] + 1, n.end_point[0] + 1


def parse_entities(path: str, source: bytes) -> list[Entity]:
    tree = _parser.parse(source)
    root = tree.root_node
    n_lines = source.count(b"\n") + 1
    out: list[Entity] = [
        Entity(id=f"{path}::<module>", path=path, name=path.rsplit("/", 1)[-1], qualname="<module>",
               kind="module", start=1, end=n_lines, doc=_docstring(root))
    ]

    def add_def(node: Node, outer: Node, prefix: str | None, parent_id: str | None):
        name_node = node.child_by_field_name("name")
        name = _text(name_node)
        if not name:
            return
        qual = f"{prefix}.{name}" if prefix else name
        start, end = _span(outer)
        if node.type == "class_definition":
            kind = "class"
        else:
            kind = "method" if prefix else "function"
        sig = ""
        if node.type == "function_definition":
            params = node.child_by_field_name("parameters")
            sig = f"def {name}{_text(params)}"[:200]
        else:
            sup = node.child_by_field_name("superclasses")
            sig = f"class {name}{_text(sup)}"[:200]
        ent = Entity(id=f"{path}::{qual}", path=path, name=name, qualname=qual, kind=kind,
                     start=start, end=end, parent=parent_id or f"{path}::<module>",
                     doc=_docstring(node.child_by_field_name("body")), signature=sig)
        out.append(ent)
        if node.type == "class_definition":
            walk_block(node.child_by_field_name("body"), qual, ent.id)

    def handle_assignment(stmt: Node, prefix: str | None, parent_id: str | None):
        assign = stmt.children[0] if stmt.children else None
        if assign is None or assign.type not in ("assignment",):
            return
        left = assign.child_by_field_name("left")
        if left is None or left.type != "identifier":
            return
        name = _text(left)
        start, end = _span(stmt)
        if prefix:
            kind = "attribute"
        elif UPPER.match(name):
            kind = "constant"
        else:
            return  # plain module-level variables are noise
        qual = f"{prefix}.{name}" if prefix else name
        out.append(Entity(id=f"{path}::{qual}", path=path, name=name, qualname=qual, kind=kind,
                          start=start, end=end, parent=parent_id or f"{path}::<module>",
                          signature=_text(stmt).split("\n")[0][:200]))
        # Config keys: string keys of dict literals assigned to *config* names.
        if "config" in name.lower():
            right = assign.child_by_field_name("right")
            if right is not None:
                for pair in _iter_pairs(right):
                    key = pair.child_by_field_name("key")
                    if key is not None and key.type == "string":
                        k = _text(key).strip("\"'")
                        if UPPER.match(k):
                            s, e = _span(pair)
                            out.append(Entity(id=f"{path}::config:{k}", path=path, name=k, qualname=f"config:{k}",
                                              kind="config", start=s, end=e, parent=f"{path}::{qual}",
                                              signature=_text(pair)[:200]))

    def walk_block(block: Node | None, prefix: str | None, parent_id: str | None):
        if block is None:
            return
        for child in block.children:
            if child.type in ("function_definition", "class_definition"):
                add_def(child, child, prefix, parent_id)
            elif child.type == "decorated_definition":
                inner = child.child_by_field_name("definition")
                if inner is not None:
                    add_def(inner, child, prefix, parent_id)
            elif child.type == "expression_statement":
                handle_assignment(child, prefix, parent_id)
            elif child.type in ("if_statement", "try_statement") and prefix is None:
                # e.g. `if t.TYPE_CHECKING:` blocks at module level
                for sub in child.children:
                    if sub.type == "block":
                        walk_block(sub, prefix, parent_id)

    walk_block(root, None, None)
    return out


def _iter_pairs(node: Node):
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "pair":
            yield n
            continue
        stack.extend(n.children)


def locate(entities: list[Entity], line: int) -> Entity | None:
    """Most specific entity whose span contains `line`."""
    best = None
    for e in entities:
        if e.start <= line <= e.end and (best is None or (e.end - e.start) < (best.end - best.start)):
            best = e
    return best
