from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]

SCAN_TARGETS = [
    ROOT / "OpcTagManager.py",
    ROOT / "services",
    ROOT / "workers",
]

TABLE_PATTERNS = [
    r"\bFROM\s+(?:\[?dbo\]?\.)?\[?([A-Za-z_][A-Za-z0-9_]*)\]?",
    r"\bJOIN\s+(?:\[?dbo\]?\.)?\[?([A-Za-z_][A-Za-z0-9_]*)\]?",
    r"\bINSERT\s+INTO\s+(?:\[?dbo\]?\.)?\[?([A-Za-z_][A-Za-z0-9_]*)\]?",
    r"\bUPDATE\s+(?:\[?dbo\]?\.)?\[?([A-Za-z_][A-Za-z0-9_]*)\]?",
    r"\bDELETE\s+FROM\s+(?:\[?dbo\]?\.)?\[?([A-Za-z_][A-Za-z0-9_]*)\]?",
    r"\bMERGE\s+(?:INTO\s+)?(?:\[?dbo\]?\.)?\[?([A-Za-z_][A-Za-z0-9_]*)\]?",
]

SQL_VERB = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|MERGE)\b",
    re.IGNORECASE
)

tables = {}
files_scanned = 0
sql_strings = 0


def python_files():
    for target in SCAN_TARGETS:
        if target.is_file():
            yield target
        elif target.is_dir():
            yield from target.rglob("*.py")


def extract_string(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value

    if isinstance(node, ast.JoinedStr):
        # Extract literal portions from f-strings.
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append(" ")
        return "".join(parts)

    return None


for path in python_files():
    if any(part in {".git", ".venv", "__pycache__", "tests"} for part in path.parts):
        continue

    files_scanned += 1

    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(path))
    except Exception as exc:
        print(f"WARNING: cannot parse {path}: {exc}")
        continue

    for node in ast.walk(tree):
        text = extract_string(node)

        if not text:
            continue

        # Ignore normal prose/docstrings unless it actually looks like SQL.
        if not SQL_VERB.search(text):
            continue

        sql_strings += 1

        for pattern in TABLE_PATTERNS:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                table = match.group(1)

                tables.setdefault(table, set()).add(
                    str(path.relative_to(ROOT))
                )


print("ROOT =", ROOT)
print("Python files scanned =", files_scanned)
print("SQL-like strings scanned =", sql_strings)
print()
print("=== SQL TABLE CANDIDATES ===")
print()

for table in sorted(tables, key=str.lower):
    print(table)
    for source in sorted(tables[table]):
        print(f"    {source}")

print()
print("Total candidate tables =", len(tables))