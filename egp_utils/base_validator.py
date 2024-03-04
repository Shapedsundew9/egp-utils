"""Extension to the Cerberus Validator with common checks."""

from json import JSONDecodeError, load
from logging import Logger, NullHandler, getLogger
from os import R_OK, W_OK, X_OK, access
from os.path import isdir, isfile
from pprint import pformat
from typing import Any, Callable
from uuid import UUID
from datetime import datetime

from cerberus import TypeDefinition, Validator
from cerberus.errors import UNKNOWN_FIELD

_logger: Logger = getLogger(__name__)
_logger.addHandler(NullHandler())


def str_to_sha256(
    obj: str | bytearray | memoryview | bytes | None,
) -> bytearray | memoryview | bytes | None:
    """Convert a hexidecimal string to a bytearray.

    Args
    ----
    obj (str): Must be a hexadecimal string.

    Returns
    -------
    (bytearray): bytearray representation of the string.
    """
    if isinstance(obj, str):
        return bytes.fromhex(obj)
    if isinstance(obj, memoryview) or isinstance(obj, bytearray) or isinstance(obj, bytes):
        return obj
    if obj is None:
        return None
    raise TypeError(f"Un-encodeable type '{type(obj)}': Expected 'str' or bytes type.")


def str_to_uuid(obj: str | UUID | None) -> UUID | None:
    """Convert a UUID formated string to a UUID object.

    Args
    ----
    obj (str): Must be a UUID formated hexadecimal string.

    Returns
    -------
    (uuid): UUID representation of the string.
    """
    if isinstance(obj, str):
        return UUID(obj)
    if isinstance(obj, UUID):
        return obj
    if obj is None:
        return None
    raise TypeError(f"Un-encodeable type '{type(obj)}': Expected 'str' or UUID type.")


def str_to_datetime(obj: str | datetime | None) -> datetime | None:
    """Convert a datetime formated string to a datetime object.

    Args
    ----
    obj (str): Must be a datetime formated string.

    Returns
    -------
    (datetime): datetime representation of the string.
    """
    if isinstance(obj, str):
        return datetime.strptime(obj, "%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(obj, datetime):
        return obj
    if obj is None:
        return None
    raise TypeError(f"Un-encodeable type '{type(obj)}': Expected 'str' or datetime type.")


def sha256_to_str(obj: bytearray | bytes | str | None) -> str | None:
    """Convert a bytearray to its lowercase hexadecimal string representation.

    Args
    ----
    obj (bytearray): bytearray representation of the string.

    Returns
    -------
    (str): Lowercase hexadecimal string.
    """
    if isinstance(obj, (bytes, bytearray)):
        return obj.hex()
    if isinstance(obj, str):
        return obj
    if obj is None:
        return None
    raise TypeError(f"Un-encodeable type '{type(obj)}': Expected bytes, bytearray or str type.")


def uuid_to_str(obj: UUID | str | None) -> str | None:
    """Convert a UUID to its lowercase hexadecimal string representation.

    Args
    ----
    obj (UUID): UUID representation of the string.

    Returns
    -------
    (str): Lowercase hexadecimal UUID string.
    """
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, str):
        return obj
    if obj is None:
        return None
    raise TypeError(f"Un-encodeable type '{type(obj)}': Expected UUID or str type.")


def datetime_to_str(obj: datetime | str | None) -> str | None:
    """Convert a datetime to its string representation.

    Args
    ----
    obj (datetime): datetime representation of the string.

    Returns
    -------
    (str): datetime string.
    """
    if isinstance(obj, datetime):
        return obj.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(obj, str):
        return obj
    if obj is None:
        return None
    raise TypeError(f"Un-encodeable type '{type(obj)}': Expected bytes, bytearray or str type.")


class base_validator(Validator):
    """Additional format checks."""

    types_mapping: Any = Validator.types_mapping.copy()  # type: ignore
    types_mapping["uuid"] = TypeDefinition("uuid", (UUID,), ())
    types_mapping["callable"] = TypeDefinition("callable", (Callable,), ())

    def __init__(self, *args, **kwargs) -> None:
        # FIXME: To satisfy pylance.
        # FIXME: Could better define types here.
        # Cerberus does some complex dynamic definition that pylance cannot statically resolve
        self.document: Any = None
        super().__init__(*args, **kwargs)
        self._error: Callable[[str, str], None] = super()._error  # type: ignore
        self.schema: Any = super().schema  # type: ignore
        self.normalized: Callable = super().normalized  # type: ignore
        self.validate: Callable = super().validate  # type: ignore
        self.rules_set_registry = super().rules_set_registry  # type: ignore

    def error_str(self) -> str:
        """Prettier format to a list of errors."""
        return "\n".join((field + ": " + pformat(error) for field, error in self.errors.items()))  # type: ignore

    def _isdir(self, field: str, value: Any) -> bool:
        """Validate value is a valid, existing directory."""
        if not isdir(value):
            self._error(field, f"{value} is not a valid directory or does not exist.")
            return False
        return True

    def _isfile(self, field: str, value: Any) -> bool:
        """Validate value is a valid, existing file."""
        if not isfile(value):
            self._error(field, f"{value} is not a valid file or does not exist.")
            return False
        return True

    def _isreadable(self, field: str, value: Any) -> bool:
        """Validate value is a readable file."""
        if not access(value, R_OK):
            self._error(field, f"{value} is not readable.")
            return False
        return True

    def _iswriteable(self, field: str, value: Any) -> bool:
        """Validate value is a writeable file."""
        if not access(value, W_OK):
            self._error(field, f"{value} is not writeable.")
            return False
        return True

    def _isexecutable(self, field: str, value: Any) -> bool:
        """Validate value is an executable file."""
        if not access(value, X_OK):
            self._error(field, f"{value} is not executable.")
            return False
        return True

    def _isjsonfile(self, field: str, value: Any) -> dict | list | None:
        """Validate the JSON file is decodable."""
        if self._isfile(field, value) and self._isreadable(field, value):
            with open(value, "r", encoding="utf8") as file_ptr:
                try:
                    schema: dict | list = load(file_ptr)
                except JSONDecodeError as exception:
                    self._error(field, f"The file is not decodable JSON: {exception}")
                else:
                    return schema
        return None

    def _normalize_coerce_sha256_str_to_binary(self, value) -> bytearray | memoryview | bytes | None:
        return str_to_sha256(value)

    def _normalize_coerce_sha256_str_list_to_binary_list(self, value) -> list[list[bytearray | memoryview | bytes | None]]:
        return [[str_to_sha256(v) for v in vv] for vv in value]

    def _normalize_coerce_datetime_str_to_datetime(self, value) -> datetime | None:
        return str_to_datetime(value)

    def _normalize_coerce_uuid_str_to_uuid(self, value) -> UUID | None:
        return str_to_uuid(value)

    def _normalize_coerce_sha256_binary_to_str(self, value) -> str | None:
        return sha256_to_str(value)

    def _normalize_coerce_sha256_binary_list_to_str_list(self, value) -> list[list[str | None]] | None:
        return [[sha256_to_str(v) for v in vv] for vv in value]

    def _normalize_coerce_datetime_to_datetime_str(self, value) -> str | None:
        return datetime_to_str(value)

    def _normalize_coerce_uuid_to_uuid_str(self, value) -> str | None:
        return uuid_to_str(value)

    def str_errors(self, error: Any) -> str:
        """Create an error string."""
        if error.code == UNKNOWN_FIELD.code:
            error.rule = "unknown field"
        str_tuple: tuple[str, str, str] = (
            "Value: " + str(error.value),
            "Rule: " + str(error.rule),
            "Constraint: " + str(error.constraint),
        )
        return ", ".join(str_tuple)
