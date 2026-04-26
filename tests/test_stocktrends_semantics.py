from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_TERMS = [
    "Stock Trends Intermediate Momentum",
    "Stock Trends Indicator Model",
    "ST-IM (Stock Trends Intermediate Momentum)",
    "ST-IM (Stock Trends Indicator Model)",
]

TEXT_EXTENSIONS = {
    ".py",
    ".md",
    ".json",
    ".txt",
    ".yaml",
    ".yml",
}



def iter_repo_text_files():
    skip_dirs = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        "node_modules",
        ".claude",          # ✅ CRITICAL FIX
        "docs",             # ✅ EXCLUDE CONTRACT FILE
        "tests",            # ✅ EXCLUDE TEST FILE ITSELF
    }

    for path in REPO_ROOT.rglob("*"):
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.is_file() and path.suffix in TEXT_EXTENSIONS:
            yield path


def test_forbidden_stocktrends_semantic_terms_absent():
    violations = []

    for path in iter_repo_text_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for term in FORBIDDEN_TERMS:
            if term in text:
                violations.append(f"{path.relative_to(REPO_ROOT)} contains forbidden term: {term}")

    assert not violations, "\n".join(violations)


def test_semantic_contract_defines_stim_correctly():
    contract = REPO_ROOT / "docs" / "STOCK_TRENDS_SEMANTIC_CONTRACT.md"
    text = contract.read_text(encoding="utf-8")

    assert "STIM = Stock Trends Inference Model" in text
    assert "forward return expectations" in text
    assert "statistical distributions" in text
    assert "4-week" in text
    assert "13-week" in text
    assert "40-week" in text