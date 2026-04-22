## Code style guidelines
- Keep interfaces explicit with typed schemas (Pydantic/TypeScript types/OpenAPI).
- Fail loudly on invalid data; do not silently skip errors.
- Keep hot-path logic minimal and deterministic.
- Write concise docstrings/comments only where logic is non-obvious.
- For every new or updated function, include a proper docstring that documents all parameters and the return value.

## Code commit guidelines
- make frequent, small, focused commits, with each commit addressing a single, logical change or task. This makes changes easy to review and debug.
- Utilize the Conventional Commits format (e.g., feat:, fix:, docs:) to provide a clear, standardized history of changes. Messages should be in the imperative mood and kept short

## Architecture change guidelines
- for every architecture change, update ./ARCHITECTURE.md to reflect the latest architecture