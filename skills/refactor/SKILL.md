---
name: refactor
description: Use when the user wants to improve existing code quality without changing behavior. Triggers on requests to clean up, restructure, simplify, deduplicate, or improve readability of code. Do NOT use for new features or bug fixes.
allowed-tools:
  - read_file
  - file_ops
  - run_command
---

## Refactoring Workflow

1. **Read the target code** — Read the file(s) end-to-end. Note the language, framework, and coding conventions used.

2. **Identify refactoring opportunities** — Check for these specific patterns:
   - Functions longer than 30 lines → extract smaller functions
   - Duplicated code blocks (3+ lines repeated) → extract to shared utility
   - Deeply nested conditionals (3+ levels) → flatten with early returns
   - Magic numbers/strings → extract to named constants
   - Long parameter lists (4+) → group into config object or struct
   - Dead code or unreachable branches → remove

3. **Plan the changes** — List each refactoring with:
   - What: e.g., "Extract lines 45-60 into `parse_config()`"
   - Why: e.g., "Reduces cognitive load, enables testing"
   - Risk: low / medium / high

4. **Apply changes incrementally** — Make one refactoring at a time. After each change, verify the code still looks correct syntactically.

5. **Verify behavior preservation** — Run existing tests if available (`pytest`, `npm test`, `go test`, etc.). If no tests exist, note this as a recommendation.

6. **Output format** — Present results as:

```
## Refactoring Summary

### Changes Made
1. [file:line] Description of change
2. [file:line] Description of change

### Metrics
- Lines of code: before → after
- Longest function: before → after
- Duplications removed: X

### Recommendations
- [ ] Add tests for extracted functions
- [ ] Other follow-up improvements
```

## Refactoring Checklist

- [ ] No behavior change (same inputs → same outputs)
- [ ] All existing tests pass
- [ ] Naming is clear and consistent with codebase style
- [ ] No new dependencies introduced
- [ ] Error handling preserved or improved
- [ ] Comments updated if logic changed
