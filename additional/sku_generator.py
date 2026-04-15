import uuid
from datetime import datetime


def generate_sku(prefix: str = "RIBA") -> str:
    """
    Генерує SKU для продукту.

    Формат: PREFIX-YYYYMMDD-XXXX
    де:
      PREFIX   = категорія (за замовчуванням RIBA)
      YYYYMMDD = дата створення
      XXXX     = випадковий унікальний шматок (перші 4 символи uuid4)
    """
    date_part = datetime.now().strftime("%Y%m%d")
    random_part = uuid.uuid4().hex[:4].upper()
    return f"{prefix}-{date_part}-{random_part}"