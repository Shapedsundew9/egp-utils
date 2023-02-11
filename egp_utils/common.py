"""Common routines."""
from datetime import datetime, timedelta, timezone
from typing import Any

EST: timezone = timezone(timedelta(hours=-5))
EGP_EPOCH: datetime = datetime(2019, 12, 25, 16, 26, tzinfo=EST)
EGP_EMPTY_TUPLE: tuple[()] = tuple()


# https://stackoverflow.com/questions/7204805/how-to-merge-dictionaries-of-dictionaries
def merge(dict_a: dict[Any, Any], dict_b: dict[Any, Any], path: list[str] = [],  # pylint: disable=W0102
          no_new_keys: bool = False) -> dict[Any, Any]:
    """Merge dict b into a recursively. a is modified.
    This function is equivilent to a.update(b) if b contains no dictionary values with
    the same key as in a.
    If there are dictionaries
    in b that have the same key as a then those dictionaries are merged in the same way.
    Keys in a & b (or common key'd sub-dictionaries) where one is a dict and the other
    some other type raise an exception.

    Args
    ----
    a: Dictionary to merge in to.
    b: Dictionary to merge.
    no_new_keys: If True keys in b that are not in a are ignored

    Returns
    -------
    a (modified)
    """
    for key in dict_b:
        if key in dict_a:
            if isinstance(dict_a[key], dict) and isinstance(dict_b[key], dict):
                merge(dict_a[key], dict_b[key], path + [str(key)], no_new_keys)
            elif dict_a[key] == dict_b[key]:
                pass  # same leaf value
            else:
                raise ValueError(f"Conflict at {'.'.join(path + [str(key)])}")
        elif not no_new_keys:
            dict_a[key] = dict_b[key]
    return dict_a




