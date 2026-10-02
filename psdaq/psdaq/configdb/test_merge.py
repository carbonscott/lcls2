"""Demo script: merges two nested dicts by flattening them, keeping only common keys, and unflattening; `main` prints each step."""
from collections.abc import MutableMapping
import json

def _flatten_dict_gen(d, parent_key, sep):
    for k, v in d.items():
        new_key = str(parent_key) + sep + str(k) if parent_key else str(k)
        if isinstance(v, MutableMapping):
            yield from flatten_dict(v, new_key, sep=sep).items()
        else:
            yield new_key, v

def flatten_dict(d: MutableMapping, parent_key: str = '', sep: str = '.'):
    """Return a flat dict whose keys are the paths of `d` joined with `sep` (keys converted to str), prefixed by `parent_key` if given."""
    return dict(_flatten_dict_gen(d, parent_key, sep))

def unflatten_dict(dictionary):
    """Rebuild a nested dict from a flat dict whose keys are '.'-separated paths."""
    resultDict = dict()
    for key, value in dictionary.items():
        parts = key.split(".")
        d = resultDict
        for part in parts[:-1]:
            if part not in d:
                d[part] = dict()
            d = d[part]
        d[parts[-1]] = value
    return resultDict

def trim(dictionary, keep_keys, parent_key: str = '', sep: str = '.'):
    """Return the entries of `dictionary` whose (prefixed) key is in `keep_keys`.

    If a value is a dict, the recursive call uses the undefined name `old_keys`, so it raises
    NameError; with flat input (as in `main`) this does not happen.
    """
    resultDict = {}
    for k, v in dictionary.items():
        new_key = str(parent_key) + sep + k if parent_key else k
        if isinstance(v, dict):
            v = trim(v, old_keys, new_key)
        if new_key in keep_keys:
            resultDict[new_key] = v
    return resultDict

def main():

    """Print two example nested dicts, their flattened forms, the common keys, the trimmed dicts and the unflattened results."""
    input_1 = {'config': {'group': {0: {'rate': 9},
                                 1: {'rate': 99},
                                 2: {'rate': 999}}}}

    input_2 = {'config': {'group': {0: {'rate': 10},
                                 2: {'rate': 100},
                                 4: {'rate': 1000}}}}

    print("input_1: ", end=""); print(json.dumps(input_1, indent=4))
    print("input_2: ", end=""); print(json.dumps(input_2, indent=4))

    flat_1 = flatten_dict(input_1)
    flat_2 = flatten_dict(input_2)

    print("flat_1: ", end=""); print(json.dumps(flat_1, indent=4))
    print("flat_2: ", end=""); print(json.dumps(flat_2, indent=4))

    # Requirements for modifying an existing configdb entry:
    #   elements that are in the configdb entry but not in the json string are ignored
    #   elements that are not in the configdb entry but are in the json string are ignored

    common_keys = flat_1.keys() & flat_2.keys()

    print(f"common_keys: {common_keys}")

    trimmed_1 = trim(flat_1, common_keys)
    print(f"trim(flat_1, common_keys) = {trimmed_1}")

    trimmed_2 = trim(flat_2, common_keys)
    print(f"trim(flat_2, common_keys) = {trimmed_2}")

    unflat_1 = unflatten_dict(trimmed_1)
    print("unflat_1: ", end=""); print(json.dumps(unflat_1, indent=4))

    unflat_2 = unflatten_dict(trimmed_2)
    print("unflat_2: ", end=""); print(json.dumps(unflat_2, indent=4))

if __name__ == '__main__':
    main()
