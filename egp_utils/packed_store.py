"""Packed Store.

A packed store is a space and time optimised key-value store. It is designed to
be multi-process friendly.

Nested dictionaries are fast but do not scale well. Python dictionaries use huge amounts
of memory and are updated in a spatially broad manner requiring subprocesses to maintain
an almost full copy even if most entries are only read.

The packed store implemented here maintains a dictionary like interface but takes
advantage of structural design choices to efficiently store data in numpy arrays where possible.

NOTE: Packed store does not preserve entry order like a python3 dictionary would.

It also takes advantage of usage patterns to cluster stable and volatile data which
makes efficient use of OS CoW behaviour in a multi-process environment as well as minimising
the volume of null data in irregular structures.

Rough benchmarking:

Assuming an entry can be approximated by 125 integers in a dictionary and
100,000 in a store implemented as a dictionary:

store = {k:{v:v for v in tuple(range(125))} for k in tuple(range(100000))}

The memory used by python3 3.10.6 is 467 MB (4565 MB for 1,000,000)

Assuming an entry can be represented by a dictionary of indexes into to a
numpy array of int64 and shape (125, 100000) then the memory used is

store_index = {k:k for k in tuple(range(100000))}
store = zeros((125, 1000000), dtype=int64)

The memory used by python3 3.10.6 is 10 + 100 = 110 MB. (1085 MB for 1,000,000)

That is a saving of 4x.

The saving get compunded when considering a dict of dict.
Actual results from a random 127 element dict:
14:01:30 INFO test_gene_pool_cache.py 93 Dict size: sys.getsizeof = 4688 bytes, pympler.asizeof = 5399488 bytes.
14:01:30 INFO test_gene_pool_cache.py 94 store size: sys.getsizeof = 56 bytes, pympler.asizeof = 204576 bytes.

That is a saving of 25x.
This is a bit of an anti-pattern for python but in this case the savings are worth it.
"""
from __future__ import annotations

from collections.abc import KeysView as dict_keys
from copy import deepcopy
from functools import partial
from logging import DEBUG, Logger, NullHandler, getLogger
from typing import Any, Callable, Generator, Literal, NoReturn, Self, TypedDict, TypeVar, Generic, Type
from numpy import bool_, float32, float64, full, int16, int32, int64, uint32
from numpy.typing import NDArray

# Logging
_logger: Logger = getLogger(__name__)
_logger.addHandler(NullHandler())
_LOG_DEBUG: bool = _logger.isEnabledFor(DEBUG)


# Pretty print for references
_OVER_MAX: int = 1 << 64
_MASK: int = _OVER_MAX - 1
ref_str: Callable[[int], str] = lambda x: 'None' if x is None else f"{((_OVER_MAX + x) & _MASK):016x}"


class Field(TypedDict):
    """store configured field definition."""

    type: Any
    length: int
    default: Any
    read_only: bool
    read_count: int
    write_count: int


# Lazy add igraph
sql_np_mapping: dict[str, Any] = {
    'BIGINT': int64,
    'BIGSERIAL': int64,
    'BOOLEAN': bool_,
    'DOUBLE PRECISION': float64,
    'FLOAT8': float64,
    'FLOAT4': float32,
    'INT': int32,
    'INT8': int64,
    'INT4': int32,
    'INT2': int16,
    'INTEGER': int32,
    'REAL': float32,
    'SERIAL': int32,
    'SERIAL8': int64,
    'SERIAL4': int32,
    'SERIAL2': int16,
    'SMALLINT': int16,
    'SMALLSERIAL': int16
}

_MODIFIED: Field = {
    'type': bool,
    'length': 1,
    'default': False,
    'read_only': False,
    'read_count': 0,
    'write_count': 0
}


def next_idx_generator(delta_size: int, empty_list: list[int], allocate_func: Callable[[], None]) -> Generator[int, None, None]:
    """Generate the next valid storage idx.

    Storage indicies start at 0 and increment to infinity.
    However the next available index may not be n+1.
    Deleted entries indices are added to the empty_list and are prioritised
    for new storage.
    If all pre-allocated storage is consumed the storage will be expanded by
    delta_size indices.

    Args
    ----
    delta_size: The log2(number of entries) to increase storage capacity by when all existing storage is occupied.
    empty_list: The indices of empty entries in the data store.
    allocate_func: A function that increases the number of entries by delta_size (takes no parameters)

    Returns
    -------
    A next index generator.
    """
    allocation_round: int = 0
    allocation_base: int = 0
    while True:
        _logger.debug(f"Creating new allocation {allocation_round} at base {allocation_base:08x}.")
        allocate_func()
        allocation_base = 2**delta_size * allocation_round
        for idx in range(allocation_base, allocation_base + 2**delta_size):
            while empty_list:
                if _LOG_DEBUG:
                    _logger.debug(f"Using deleted entry index {empty_list[0]} for next new entry.")
                yield empty_list.pop(0)
            yield idx
        allocation_round += 1


def allocate(data: dict[str, list[Any]], delta_size: int, fields: dict[str, Field]) -> None:
    """Allocate storage space for data.

    Each field has a particular storage type for its needs. The only requirement
    that it supports __getitem__() & __setitem__().

    Args
    ----
    data: Data store to expand.
    delta_size: The log2(number of entries) to increase storage capacity by when all existing storage is occupied.
    fields: Definition of data fields
    """
    # This is ordered so read-only fields are allocated together for CoW performance.
    size: int = 2**delta_size
    indexed_stores: dict[str, indexed_store] = {}
    for key, value in sorted(fields.items(), key=lambda x: x[1].get('read_only', True)):
        shape: int | tuple[int, int] = size if value.get('length', 1) == 1 else (size, value['length'])
        if isinstance(value['type'], list):
            data[key].append([value['default']] * size)
        elif not isinstance(value['type'], indexed_store):
            data[key].append(full(shape, value['default'], dtype=value['type']))
        else:
            istore: indexed_store = indexed_stores[key] if key in indexed_stores else indexed_store(size)
            data[key].append(istore.allocate())


class devnull():
    """Behaves like Linux /dev/null."""

    def __len__(self) -> Literal[0]:
        return 0

    def __getitem__(self, _: Any) -> Self:
        return self

    def __setitem__(self, _: Any, __: Any) -> None:
        pass


class entry():
    """Entry is a dict-like object in a dict like packed_store."""

    def __init__(self, data: dict[str, list[Any]] = {}, allocation: int = 0, idx: int = 0, fields: dict[str, Field] = {}) -> None:
        """Bind the entry to an spot in the store.

        NOTE: The data store does not need to be the same as bound in store as the _data
        store object is passed in.

        Args
        ----
        data: Is the packed store from which individual entries are read & written.
        allocation: Is the index of the allocation in the store for this entry.
        idx: Is the index in the allocation.
        fields: The definition of the fields in the entry
        """
        self._data: dict[str, list[Any]] = data
        self._allocation: int = allocation
        self._idx: int = idx
        self.fields: dict[str, Field] = fields

    def __contains__(self, key: str) -> bool:
        """Checks if key is one of the fields in entry."""
        return key in self.fields

    def __getitem__(self, key: str) -> Any:
        """Return the value stored with key."""
        if __debug__:
            assert key in self.fields, f"{key} is not a key in data."
            self.fields[key]['read_count'] += 1
            _logger.debug(f"Getting key '{key}' from allocation {self._allocation}, index {self._idx}).")
        return self._data[key][self._allocation][self._idx]

    def __setitem__(self, key: str, value: Any) -> None:
        """Set the value stored with key."""
        if __debug__:
            assert key in self._data, f"'{key}' is not a key in data."
            assert not self.fields[key]['read_only'], f"Writing to read-only field '{key}'."
            self.fields[key]['write_count'] += 1
            _logger.debug(f"Setting key '{key}' to allocation {self._allocation}, index {self._idx}).")
        self._data[key][self._allocation][self._idx] = value
        self._data['__modified__'][self._allocation][self._idx] = True

    def __copy__(self) -> NoReturn:
        """Make sure we do not copy entries. This is for performance."""
        assert False, f"Shallow copy of entry ref {self['ref']:016X}."

    def __deepcopy__(self, _: Self) -> NoReturn:
        """Make sure we do not copy entrys. This is for performance."""
        assert False, f"Deep copy of entry ref {self['ref']:016X}."

    def keys(self) -> dict_keys[str]:
        """A view of the keys in the entry."""
        return self.fields.keys()

    def items(self) -> Generator[tuple[str, Any], None, None]:
        """A view of the entrys in the store."""
        for key in self.fields.keys():
            yield key, self[key]

    def update(self, value: dict | Self) -> None:
        """Update the entry with a dict-like collection of fields."""
        for k, v in value.items():
            self[k] = v

    def values(self) -> Generator[Any, None, None]:
        """A view of the field values in the entry."""
        for key in self.fields.keys():
            yield self[key]


T = TypeVar('T', bound=entry)


class packed_store(Generic[T]):
    """Store data compactly with a dict like interface."""

    def __init__(self, fields: dict[str, Field], entry_type: Type[T] = entry, delta_size: int = 16) -> None:
        """Create a _store object.

        _store data is stored in numpy arrays or list if not numeric.

        Args
        ----
        fields: Describes the storage type and property hints and must have the following format:
            {
                <field name>: {
                    'type': Any         # A valid numpy type or None
                    'default': Any      # The value the property takes if not specified.
                    'read-only': bool   # True if read-only
                    'length': int       # The number of elements in an array type. 1 for scalar fields.
                },
                ...
            }
        entry_type: A sub-class of entry to be returned from the store. 
        delta_size: The log2(minimum number) of entries to add to the allocation when space runs out.
        """
        if fields is None:
            fields = {}
        self.entry_type = entry_type
        self.fields: dict[str, Field] = deepcopy(fields)
        self.fields['__modified__'] = deepcopy(_MODIFIED)
        self.writable_fields: dict[str, Field] = {k: v for k, v in self.fields.items() if not v['read_only']}
        self.read_only_fields: dict[str, Field] = {k: v for k, v in self.fields.items() if v['read_only']}
        self.delta_size: int = delta_size
        self.ref_to_idx: dict[int, int] = {}
        self.data: dict[str, list[Any]] = {k: [] for k in self.fields.keys()}
        self._devnull: devnull = devnull()
        self._idx_mask: int = (1 << self.delta_size) - 1
        _logger.debug(f"Fields created: {tuple(self.data.keys())}")
        self._empty_list: list[int] = []
        _allocate: partial[None] = partial(allocate, data=self.data, delta_size=delta_size, fields=self.fields)
        self._idx: Generator[int, None, None] = next_idx_generator(delta_size, self._empty_list, _allocate)
        next(self._idx)  # Allocation 0, index 0 = None

    def __del__(self) -> None:
        """Check to see if _store has been reasonably utilised."""
        if __debug__:
            for field, value in self.fields.items():
                if not value['read_count'] + value['write_count']:
                    _logger.warning(f"'{field}' was neither read nor written!")
                if not value['read_only'] and not value['write_count']:
                    _logger.warning(f"'{field}' is writable but was never written!")

    def __contains__(self, ref: int) -> bool:
        """Test if a ref is in the store.

        Args
        ----
        ref: store unique entry reference.

        Returns
        -------
        True if ref is present.
        """
        # Reference 0 = None which is not in the store
        return ref in self.ref_to_idx if ref else False

    def __delitem__(self, ref: int) -> None:
        """Remove the entry for ref from the store.

        Args
        ----
        ref: store unique entry reference.
        """
        # Reference 0 is None which is not in the store
        if not ref:
            raise KeyError("Cannot delete the 0 (null) reference).")
        full_idx: int = self.ref_to_idx[ref]
        del self.ref_to_idx[ref]

        self._empty_list.append(full_idx)
        allocation: int = full_idx >> self.delta_size
        idx: int = full_idx & self._idx_mask
        if _LOG_DEBUG:
            _logger.debug(f"Deleting ref {ref_str(ref)}: Allocation {allocation} index {idx}.")
        for k, v in self.fields.items():
            self.data[k][allocation][idx] = v['default']

    def __getitem__(self, ref: int) -> T:
        """Return an entry dict-like structure from the store.

        Args
        ----
        ref: store unique entry reference.

        Returns
        -------
        dict-like entry record.
        """
        # Reference 0 is None which is not in the store
        if not ref:
            raise KeyError("Cannot read the 0 (null) reference).")
        full_idx: int = self.ref_to_idx[ref]
        allocation: int = full_idx >> self.delta_size
        idx: int = full_idx & self._idx_mask
        if _LOG_DEBUG:
            _logger.debug(f"Getting entry ref {ref_str(self.data['ref'][allocation][idx])}"
                          f" from allocation {allocation}, index {idx} (full index = {full_idx:08x}).")
        return self.entry_type(self.data, allocation, idx, self.fields)

    def __len__(self) -> int:
        """The number of entries."""
        return len(self.ref_to_idx)

    def __setitem__(self, ref: int, value: dict | entry) -> None:
        """Create a entry entry in the store.

        NOTE: Set of an existing entry behaves like an update()

        Args
        ----
        ref: The entry unique reference in the GP.
        value: A dict-like object defining at least the required fields of a entry.
        """
        if not ref:
            raise KeyError("Cannot set the 0 (null) reference.")
        full_idx: int | None = self.ref_to_idx.get(ref)
        if full_idx is None:
            modified: bool = False
            full_idx = next(self._idx)
            self.ref_to_idx[ref] = full_idx
            if _LOG_DEBUG:
                _logger.debug("Ref does not exist in the store generating full index.")
        else:
            modified = True
        allocation: int = full_idx >> self.delta_size
        idx: int = full_idx & self._idx_mask
        if _LOG_DEBUG:
            _logger.debug(f"Setting entry ref {ref_str(ref)} to allocation {allocation},"
                          f" index {idx} (full index = {full_idx:08x}).")
        self.data['__modified__'][allocation][idx] = modified
        for k, v in value.items():
            # None means not set i.e. allocation default.
            if v is not None:
                self.data.get(k, self._devnull)[allocation][idx] = v
                if _LOG_DEBUG and k in self.fields:
                    self.fields[k]['write_count'] += 1
                    _logger.debug(f"Setting entry key '{k}' to {self.data.get(k, self._devnull)[allocation][idx]}).")

    def __copy__(self) -> NoReturn:
        """Make sure we do not copy the store."""
        assert False, "Shallow copy of store."

    def __deepcopy__(self, obj: Any) -> NoReturn:
        """Make sure we do not copy store."""
        assert False, "Deep copy of the store."

    def keys(self) -> dict_keys[int]:
        """A view of the references in the store."""
        return self.ref_to_idx.keys()

    def items(self) -> Generator[tuple[int, entry], None, None]:
        """A view of the entrys in the store."""
        for ref in self.ref_to_idx:
            yield ref, self[ref]

    def update(self, value) -> None:
        """Update the store with a dict-like collection of entrys."""
        for k, v in value.items():
            self[k] = v

    def values(self) -> Generator[T, None, None]:
        """A view of the entrys in the store."""
        for ref in self.ref_to_idx:
            yield self[ref]

    def modified(self, all_fields: bool = False) -> Generator[T, None, None]:
        """A view of the modified entrys in the store.

        Args
        ---
        all_fields: If True all the entry fields are returned else only the writable fields.

        Returns
        -------
        Each modified entry.
        """
        fields: dict[str, Field] = self.fields if all_fields else self.writable_fields
        for full_idx in self.ref_to_idx.values():
            allocation: int = full_idx >> self.delta_size
            idx: int = full_idx & self._idx_mask
            if self.data['__modified__'][allocation][idx]:
                yield self.entry_type(self.data, allocation, idx, fields)


class _indexed_store_allocation():

    def __init__(self, store: indexed_store) -> None:
        self._data: list[Any] = store._data
        self._empty_set: set[uint32] = store._empty_set
        self._allocation: NDArray[uint32] = full(store._size, 0, dtype=uint32)

    def __getitem__(self, idx) -> Any:
        return self._data[self._allocation[idx]]

    def __setitem__(self, idx, value) -> None:
        if not self._empty_set:
            empty_idx: uint32 = self._empty_set.pop()
            self._allocation[idx] = empty_idx
            self._data[empty_idx] = value
        else:
            self._allocation[idx] = len(self._data)
            self._data.append(value)

    def __delitem__(self, idx: int) -> None:
        deleted_idx: uint32 = self._allocation[idx]
        self._allocation[idx] = 0
        if deleted_idx:
            self._data[deleted_idx] = None
            self._empty_set.add(deleted_idx)


class indexed_store():
    """For sparsely populated fields to reduce storage costs.

    Sparsely defined fields with > 4 bytes storage (e.g. > int32) can save memory by
    being stored as a 32 bit index into a smaller store.

    Becomes economic when 'fraction populated' * 'allocation size' > 4
    """

    def __init__(self, size) -> None:
        self._data: list[Any] = [None]
        self._size = size
        self._empty_set: set[uint32] = set()
        self._num_allocations: int = 0

    def allocate(self) -> _indexed_store_allocation:
        """Create a new allocation."""
        self._num_allocations += 1
        return _indexed_store_allocation(self)

    def __del__(self) -> None:
        _logger.debug(f"{len(self._data)} elements in indexed store versus {self._size * self._num_allocations} allocated.")
