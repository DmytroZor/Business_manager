# Test Structure

- `tests/api/routers/` - endpoint behavior tests
- `tests/unit/schemas/` - Pydantic schema validation tests
- `tests/unit/services/` - business logic service tests
- `tests/integration/services/` - real database integration tests (PostgreSQL recommended)

Run all tests:

```bash
pytest
```

## Integration Tests (Real DB)

Set `TEST_DATABASE_URL` to a dedicated test database before running integration tests.

Example value:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/business_manage_test
```

Run only integration tests:

```bash
pytest -m integration
```

If `TEST_DATABASE_URL` is not set, integration tests are skipped automatically.
