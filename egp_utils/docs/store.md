# Store Class

## Why

When runtime performance is most impacted by data volume i.e. having to push data to disk or page memory a lot, it can
be advantageous to compress python data structures at the cost of direct access & complexity.

Naively, a store could be implemented as a dictionary with reference keys. This would be fast but does not scale well.
Python dictionaries use huge amounts of memory and are updated in a spatially broad manner which is not good
for caching and require requiring subprocesses to maintain an almost full copy even if most entries are only read.
A store is more efficient in these regards. 

Rough benchmarking:

An entry in a store can be approximated by 125 integers in a dictionary and 100,000 entries in a store implemented as a
dictionary:

store = {k:{v:v for v in tuple(range(125))} for k in tuple(range(100000))}

The memory used by python3 3.10.6 is 467 MB (4565 MB for 1,000,000)

Assuming an entry can be found from a dictionary of indexes into to a numpy array of int64 and shape (125, 100000)
then the memory used is

index = {k:k for k in tuple(range(100000))}
store = zeros((125, 1000000), dtype=int64)

The memory used by python3 3.10.6 is 10 + 100 = 110 MB. (1085 MB for 1,000,000). That is a saving of 4x.

The saving get compounded when considering a dict of dict. Actual results from a random 127 element entry:
14:01:30 INFO test_gene_pool_cache.py 93 Dict size: sys.getsizeof = 4688 bytes, pympler.asizeof = 5399488 bytes.
14:01:30 INFO test_gene_pool_cache.py 94 Store size: sys.getsizeof = 56 bytes, pympler.asizeof = 204576 bytes.

That is a saving of 25x.

## Interface & Behaviour

A store has a python 2 dictionary like interface to member containers with an index interface.

## Implementation

The fundamental principle of a store is that the implementation is required to derive a class from it with
members meeting the following specification after initialization (__init__())

- __getitem__ and __setitem__ indexable from 0 to N-1
- Iterable returning elements 0 to N-1 in order

TODO: Slicing, Negative indices


### Store

Is an abstract base class that provides the common interface to all derived store class. Not to be used for
direct derivation in implementation.

### Static Store

A static store is also an abstract base class. It defines the interface for all dervived static store
classes. In a static store the store is initialized once to a set size. Typically this means a preallocation
of memory (but that is not technically required as it depends on how the members memory is allocated).
The static store provides an interface to access the members in a dictionary like fashion which can then be
indexed.

TODO: This all needs more details.

### Dynamic Store

A dynamic store creates static stores of the same derived type as needed. This allows the implementation
not to have to commit so much memory up front but still get the efficiency of storage at the cost of a little
extra runtime.

Instead of returning a member object directly a dynamic store returns a dynamic_store_member object that
abstracts the linked list of static stores to look like a member of a single static store. 

