import pytest

from manage.schemas.auth_schema import phone_number_normalizer


def test_phone_number_normalizer_normalizes_local_number():
    assert phone_number_normalizer("050 123 45 67") == "+380501234567"


def test_phone_number_normalizer_raises_value_error_for_invalid_number():
    with pytest.raises(ValueError, match="Невірний номер телефону."):
        phone_number_normalizer("123")
