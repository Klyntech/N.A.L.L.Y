---
name: test-writer
description: Use when the user needs tests written for existing code. Triggers on requests for unit tests, test coverage, test suites, or testing help. Auto-detects framework (pytest, jest, go test, vitest, mocha) from the project.
allowed-tools:
  - read_file
  - file_ops
  - run_command
  - run_code
---

## Test Writing Workflow

### Step 1: Detect Framework and Conventions

1. Check for test config files:
   - `jest.config.*`, `vitest.config.*` → JavaScript/TypeScript (jest/vitest)
   - `pytest.ini`, `setup.cfg`, `pyproject.toml` with pytest → Python
   - `*_test.go` or `go.mod` → Go
   - `.rspec`, `spec/` → Ruby RSpec
2. Read an existing test file to match style: naming, imports, assertion patterns
3. Note the test runner command for verification

### Step 2: Analyze Source Code

1. Read the target file completely
2. List every public function/method with:
   - Function name and signature
   - Expected inputs and outputs
   - Side effects (file I/O, network, DB)
   - Error conditions
3. Identify edge cases:
   - Null/empty inputs
   - Boundary values (0, -1, max int, empty string)
   - Invalid types
   - Concurrent access if applicable

### Step 3: Write Tests

For each public function, write:

1. **Happy path** — standard expected input → correct output
2. **Edge cases** — boundary values, empty inputs
3. **Error cases** — invalid inputs, missing required fields
4. **Integration** (if applicable) — function with its dependencies

Test naming convention (match existing style):
- JavaScript: `describe('ClassName')` → `it('should do X when Y')`
- Python: `class TestClassName` → `def test_do_x_when_y()`
- Go: `TestFunctionName` with subtests via `t.Run`

### Step 4: Verify Tests Pass

1. Run the test suite
2. If tests fail, fix assertions or setup (not the source code)
3. Confirm all new tests pass

### Step 5: Output Report

```
## Test Coverage Report

### Files Modified
- `tests/test_example.py` — added 8 tests

### Tests Written
| Function | Happy | Edge | Error | Total |
|----------|-------|------|-------|-------|
| parse()  | 1     | 2    | 1     | 4     |
| validate()| 1    | 1    | 2     | 4     |

### Missing Coverage
- `internal_helper()` — private, suggest making testable
- Side effects in `save_to_db()` — suggest mocking

### Run Command
pytest tests/ -v
```

## Quality Rules

- Each test tests ONE thing
- No test depends on another test's state
- Use descriptive failure messages: `assert x == 5, f"Expected 5, got {x}"`
- Mock external dependencies (HTTP, DB, filesystem)
- Target: every public function has at least 1 happy + 1 edge test
