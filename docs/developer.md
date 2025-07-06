# Developer Guidelines

## Code Quality Standards

### Formatting and Linting

Use **ruff** for all Python code formatting and linting:

```bash
# Format code
ruff format .

# Run linting
ruff check .

# Fix auto-fixable issues
ruff check --fix .
```

### Pre-commit Setup

Install pre-commit hooks to ensure code quality:

```bash
pip install pre-commit
pre-commit install
```

### Testing Requirements

- All new code must include tests
- Run the full test suite before committing:
  ```bash
  pytest tests/
  ```
- Container changes require both build and runtime tests

### Commit Standards

- Use descriptive commit messages
- Include issue references when applicable
- Commit frequently with logical groupings

### Documentation

- Update relevant documentation for any feature changes
- Include docstrings for all public functions
- Update type hints for better code clarity

## Development Workflow

1. **Create feature branch**: `git checkout -b feature/description`
2. **Write tests first**: Test-driven development preferred
3. **Implement feature**: Follow existing code patterns
4. **Run quality checks**: `ruff check . && pytest tests/`
5. **Update documentation**: Keep docs current
6. **Create pull request**: Include description and testing notes

## Module Structure

Follow the established project structure:

```
poststack/
├── containers.py      # Shared container management
├── bootstrap.py       # CLI tool implementation
├── testing/          # Test utilities and fixtures
└── docs/             # Project documentation
```

## Dependencies

- Keep dependencies minimal and well-justified
- Pin versions in requirements.txt
- Separate development dependencies in requirements-dev.txt