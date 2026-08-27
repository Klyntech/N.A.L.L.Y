"""Lint hook — called via PostToolUse for file_ops write .py files.

Input JSON via stdin: {"tool_input": {"file_path": "..."}, "tool_output": "...", ...}
Output JSON via stdout: {"hookSpecificOutput": {"additionalContext": "PY_COMPILE FAIL: ..."}}
"""

import json
import pathlib
import py_compile
import sys

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        print(json.dumps({}))
        return
    fp = (data.get("tool_input") or {}).get("file_path", "")
    msg = ""
    if fp and fp.endswith(".py"):
        p = pathlib.Path(fp)
        # Try resolve relative to cwd
        if not p.is_absolute():
            # Try cwd + fp
            try:
                p = pathlib.Path.cwd() / fp
            except Exception:
                pass
        if p.exists():
            try:
                py_compile.compile(str(p), doraise=True)
            except Exception as e:
                msg = f"PY_COMPILE FAIL: {e}"
    if msg:
        print(json.dumps({"hookSpecificOutput": {"additionalContext": msg}}))
    else:
        print(json.dumps({}))

if __name__ == "__main__":
    main()
