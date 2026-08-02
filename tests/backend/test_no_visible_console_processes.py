"""Windows desktop subprocesses must never create incidental console windows."""

import ast
from pathlib import Path


def test_every_backend_subprocess_declares_a_hidden_window_policy():
    backend = Path(__file__).resolve().parents[2] / "app" / "backend" / "stockroom"
    missing: list[str] = []
    ineffective: list[str] = []

    for source in backend.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            owner = call.func.value
            if not isinstance(owner, ast.Name) or owner.id != "subprocess":
                continue
            if call.func.attr not in {"call", "check_call", "check_output", "Popen", "run"}:
                continue
            policies = [
                keyword
                for keyword in call.keywords
                if keyword.arg in {"creationflags", "startupinfo"}
            ]
            if not policies:
                missing.append(f"{source.relative_to(backend)}:{call.lineno}")
                continue
            if all(ast.unparse(policy.value) in {"0", "None"} for policy in policies):
                ineffective.append(f"{source.relative_to(backend)}:{call.lineno}")

    assert missing == [], f"subprocess calls can flash a Windows console: {missing}"
    assert ineffective == [], f"subprocess calls declare an ineffective hide policy: {ineffective}"
