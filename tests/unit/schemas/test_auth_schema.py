import pytest
from pydantic import ValidationError

from manage.schemas.auth_schema import UserCreate, phone_number_normalizer


def test_phone_number_normalizer_accepts_local_ua_format():
    assert phone_number_normalizer("0971234567") == "+380971234567"


def test_phone_number_normalizer_accepts_plus_format():
    assert phone_number_normalizer("+380971234567") == "+380971234567"


def test_phone_number_normalizer_rejects_invalid_number():
    with pytest.raises(ValueError):
        phone_number_normalizer("12345")


def test_user_create_normalizes_phone_number():
    payload = UserCreate(
        full_name="Dmytro Test",
        email="dmytro@example.com",
        password="1234567",
        phone_number="0971234567",
        user_role="customer",
    )
    assert payload.phone_number == "+380971234567"


def test_user_create_rejects_short_password():
    with pytest.raises(ValidationError):
        UserCreate(
            full_name="Dmytro Test",
            email="dmytro@example.com",
            password="123",
            phone_number="+380971234567",
            user_role="customer",
        )
