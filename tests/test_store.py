"""Test the store class."""

from random import randint
from typing import Any

from numpy import empty, full
from numpy.typing import NDArray

from egp_utils.store import dynamic_store, static_store


# Create a store implementation.
class sstore_t1(static_store):
    """A simple static store implementation."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.a: NDArray[Any] = empty(self._size, dtype=int)
        self.b: NDArray[Any] = empty(self._size, dtype=int)
        self.c: NDArray[Any] = empty(self._size, dtype=int)


class sstore_t2(static_store):
    """A static store implementation with 2D data type"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.d: NDArray[Any] = empty((self._size, 32), dtype=int)
        self.e: NDArray[Any] = empty((self._size, 32), dtype=int)
        self.f: NDArray[Any] = empty((self._size, 32), dtype=int)


# These 3 stores are identical in functionality.
sstore = sstore_t1(2**10)
dstore = dynamic_store(sstore_t1, 6)
sdict: dict[str, NDArray[Any]] = {
    "a": empty(2**10, dtype=int),
    "b": empty(2**10, dtype=int),
    "c": empty(2**10, dtype=int),
}


def test_sstore_set_get() -> None:
    """Test the set method."""
    sstore["a"][0] = 1
    sstore["a"][1] = 2
    sstore["b"][0] = 3
    sstore["b"][1] = 4
    sstore["c"][0] = 5
    sstore["c"][1] = 6
    assert sstore["a"][0] == 1
    assert sstore["a"][1] == 2
    assert sstore["b"][0] == 3
    assert sstore["b"][1] == 4
    assert sstore["c"][0] == 5
    assert sstore["c"][1] == 6


def test_dstore_set_get() -> None:
    """Test the set method."""
    dstore["a"][0] = 1
    dstore["a"][1] = 2
    dstore["b"][0] = 3
    dstore["b"][1] = 4
    dstore["c"][0] = 5
    dstore["c"][1] = 6
    assert dstore["a"][0] == 1
    assert dstore["a"][1] == 2
    assert dstore["b"][0] == 3
    assert dstore["b"][1] == 4
    assert dstore["c"][0] == 5
    assert dstore["c"][1] == 6


def test_set_get_full() -> None:
    """Fill the stores the same way and validate they all return the same."""
    for i in range(2**10):
        sstore["a"][i] = i
        dstore["a"][i] = i
        sstore["b"][i] = i + 2**10
        dstore["b"][i] = i + 2**10
        sstore["c"][i] = i + 2**10 * 2
        dstore["c"][i] = i + 2**10 * 2
    for _ in range(2**10):
        idx: int = randint(0, 2**10 - 1)
        assert sstore["a"][idx] == idx
        assert dstore["a"][idx] == idx
        assert sstore["b"][idx] == idx + 2**10
        assert dstore["b"][idx] == idx + 2**10
        assert sstore["c"][idx] == idx + 2**10 * 2
        assert dstore["c"][idx] == idx + 2**10 * 2


def test_next_idx() -> None:
    """Fill the stores using next index and validate they all return the same."""
    for i in range(2**10):
        sstore["a"][sstore.next_index()] = i
        dstore["a"][dstore.next_index()] = i
        sstore["b"][sstore.last_index()] = i + 2**10
        dstore["b"][dstore.last_index()] = i + 2**10
        sstore["c"] = i + 2**10 * 2
        dstore["c"] = i + 2**10 * 2
    for _ in range(2**10):
        idx: int = randint(0, 2**10 - 1)
        assert sstore["a"][idx] == idx
        assert dstore["a"][idx] == idx
        assert sstore["b"][idx] == idx + 2**10
        assert dstore["b"][idx] == idx + 2**10
        assert sstore["c"][idx] == idx + 2**10 * 2
        assert dstore["c"][idx] == idx + 2**10 * 2


def test_store_del() -> None:
    """Test the empty store."""
    sstore.reset()
    dstore.reset()
    for i in range(2**10):
        sstore["a"][sstore.next_index()] = i
        dstore["a"][dstore.next_index()] = i
        sstore["b"][sstore.last_index()] = i + 2**10
        dstore["b"][dstore.last_index()] = i + 2**10
        sstore["c"] = i + 2**10 * 2
        dstore["c"] = i + 2**10 * 2
    assert len(sstore) == 2**10
    assert len(dstore) == 2**10
    del sstore[0]
    del dstore[0]
    assert len(sstore) == 2**10 - 1
    assert len(dstore) == 2**10 - 1
    assert sstore.next_index() == 0
    assert dstore.next_index() == 0
    del sstore[2**10 - 1]
    del dstore[2**10 - 1]
    assert len(sstore) == 2**10 - 1
    assert len(dstore) == 2**10 - 1
    assert sstore.next_index() == 2**10 - 1
    assert dstore.next_index() == 2**10 - 1
    del sstore[2**10 - 2]
    del dstore[2**10 - 2]
    del sstore[2**10 - 345]
    del dstore[2**10 - 345]
    assert len(sstore) == 2**10 - 2
    assert len(dstore) == 2**10 - 2


def test_dstore_complex() -> None:
    """Use the dynamic store with a 2D data type."""
    dstore = dynamic_store(sstore_t2, 6)
    for i in range(2**10):
        dstore["d"][dstore.next_index()] = full((32,), i)
        dstore["e"][dstore.last_index()] = full((32,), i + 2**10)
        dstore["f"] = full((32,), i + 2**10 * 2)
    for _ in range(2**10):
        idx: int = randint(0, 2**10 - 1)
        assert dstore["d"][idx][randint(0, 31)] == idx
        assert dstore["e"][idx][randint(0, 31)] == idx + 2**10
        assert dstore["f"][idx][randint(0, 31)] == idx + 2**10 * 2
