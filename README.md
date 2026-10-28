# http-range-tools

Parse an HTTP `Range` field and resolve its byte members as Python slices, entirely offline.

For static-file tooling, framework integrations, and diagnostics that need to distinguish malformed input, an unsupported unit, and valid ranges outside the representation. Python 3.10+, no runtime dependencies. [Português](README.pt-BR.md).

```python
from http_range_tools import resolve_range

result = resolve_range("bytes=2-4,30-,-2", size=12)
assert result.satisfiable
assert result.unsatisfied_count == 1
assert [(part.start, part.stop) for part in result.ranges] == [(2, 5), (10, 12)]
```

Offsets on the wire are inclusive. Returned `start` and `stop` are half-open: a range `2-4` becomes the Python slice `[2:5]`. The size must describe the selected representation, including its content coding when one is applied.

## Install and run

From a local checkout:

```sh
python -m pip install .
http-range-tools --size 12 'bytes=2-4,-2'
python -m http_range_tools --size 12 'bytes=20-'
```

No package-registry release is assumed. To use the source directly without installing:

```sh
PYTHONPATH=src python -m http_range_tools --size 12 'bytes=2-4,-2'
PYTHONPATH=src python examples/synthetic_slices.py
PYTHONPATH=src python examples/inspect_and_resolve.py
```

The first CLI example prints:

```json
{"size":12,"ranges":[{"start":2,"stop":5,"length":3},{"start":10,"stop":12,"length":2}],"satisfiable":true,"unsatisfied_count":0}
```

| Exit | Meaning | Output |
|---:|---|---|
| 0 | At least one member is satisfiable | Resolution JSON on stdout |
| 1 | Valid byte range set, all members unsatisfiable | Resolution JSON on stdout |
| 2 | Syntax, unsupported unit, resource bound, or argument error | Error on stderr; stdout empty |

Parser errors use `{"error":{"code":"invalid_range","message":"…"}}`; other stable codes are `limit_exceeded` and `unsupported_unit`. Argument errors use ordinary usage text. JSON integers stay exact for huge numbers; consumers need a suitable integer representation. The CLI accepts a required header argument and `--size`, with no implicit stdin, files, network, or environment configuration.

## API

```python
from http_range_tools import (
    ClosedRange, OpenRange, SuffixRange, ResolvedRange,
    parse_range, resolve_ranges, resolve_range,
)

specs = parse_range("BYTES= 0002-0004,8-,-3")
assert specs == (ClosedRange(2, 4), OpenRange(8), SuffixRange(3))
result = resolve_ranges(specs, size=12)
assert result.ranges[0] == ResolvedRange(2, 5)
assert result.ranges[0].length == 3
```

`parse_range(value, *, max_header_length=8192, max_ranges=16)` returns a tuple of immutable spec objects. `resolve_ranges(specs, size)` accepts a nonempty finite `Sequence` of those spec classes; parsed input has no further count limit. `resolve_range(value, size, *, max_header_length=8192, max_ranges=16)` combines both operations, validating size first.

`RangeResult` is immutable and exposes `size`, `ranges: tuple[ResolvedRange, ...]`, `satisfiable: bool`, and `unsatisfied_count: int`. Unsatisfiable members are omitted and counted. Ranges preserve request order, overlaps, adjacency, and duplicates; no sorting or merging occurs. Constructor numeric fields and size must be nonnegative integers, with Booleans rejected. Reversed closed or resolved bounds raise `ValueError`; wrong numeric types raise `TypeError`.

```python
from http_range_tools import RangeSyntaxError, UnsupportedRangeUnit, resolve_range

try:
    resolve_range("items=chapter-one", 12)
except UnsupportedRangeUnit as error:
    assert error.unit == "items"

try:
    resolve_range("bytes=0-1,8-7", 12)
except RangeSyntaxError as error:
    assert error.code == "invalid_range"
```

`RangeSyntaxError`, `RangeLimitError`, and `UnsupportedRangeUnit` inherit from `RangeError`, itself a `ValueError`. Messages may change; `.code` values are stable. Size/configuration mistakes raise `TypeError` or `ValueError` and are never reclassified as an unsatisfiable range.

### Boundary behavior

| Field | Size | Returned intervals | Satisfiable |
|---|---:|---|---|
| `bytes=9-99,30-,-2` | 12 | `(9,12), (10,12)`; one discarded | true |
| `bytes=-99` | 12 | `(0,12)` | true |
| `bytes=12-,-0` | 12 | none; two discarded | false |
| `bytes=0-` | 0 | none | false |
| `bytes=-1` | 0 | `(0,0)` | true |

The zero-size suffix case follows RFC 9110 §14.1.2: a positive suffix is satisfiable even when it selects an empty sequence. Check `satisfiable` explicitly; this package does not choose an HTTP response for that case.

### Input and resource bounds

- Supply one field value without `Range:`. Only ASCII text is accepted. Decimal digits are `0`–`9`; Unicode digits, Unicode whitespace, CR/LF, DEL, and controls other than HTAB are invalid.
- SP/HTAB may surround the field and comma members, including the first member after `=`. Whitespace between the unit and `=` or inside a range is invalid. Units are case-insensitive. Unknown token units raise `UnsupportedRangeUnit` before their payload is examined.
- Closed, open, and suffix forms are `first-last`, `first-`, and `-length`. Leading zeros are accepted. A reversed or malformed member invalidates the entire byte field.
- The default untrimmed header bound is **8192 characters**, and the default nonempty member count is **16**. Exactly the limit is accepted. Configure these with API keyword arguments or CLI `--max-header-length` and `--max-ranges`; limits must be positive integers.
- Up to **16 empty comma members** are ignored. More raise `RangeLimitError`; an all-empty list is invalid.
- There is no additional word-size or digit limit inside the header bound. A 5000-digit endpoint or suffix is parsed safely; Python's global decimal-conversion settings are never changed. The CLI size accepts **1–8192 ASCII decimal digits**. The library accepts nonnegative Python integer sizes.

Increasing the header bound or range count permits more CPU and memory work. Limits are parser policy, separate from syntax errors. The library does not inspect the representation or impose a response-body budget.

## Scope and standards

This is an offline parser/resolver. HTTP serving, downloads, data extraction, `Content-Range`, multipart bodies, status selection, validators/`If-Range`, compression, and file handling belong to the integrating application. It does not claim full HTTP compliance or apply server policy for overlapping requests.

The implementation is original. Semantics are informed by the IETF's [RFC 9110 range specifiers](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.1.1), [byte ranges](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.1.2), and [Range handling](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.2). Recipient list tolerance and whitespace refer to [§5.6.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-5.6.1) and [§5.6.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-5.6.3). Resource bounds, ASCII policy, Python data structures, and CLI behavior are project choices. No RFC prose or code is copied.

## Development

On Linux, install your distribution's `bubblewrap` package, then run:

```sh
python checks-offline.py
```

The wrapper mounts only the Python runtime plus `src`, `tests`, and synthetic `examples`, read-only. It clears the environment, isolates the network, uses a temporary writable directory, and verifies `CapEff=0`, `NoNewPrivs=1`, and absence of home directories, Git metadata, and GPU devices. No local sudo, downloads, app data, or credentials are needed. Unprivileged user namespaces must be permitted by the operating system; the wrapper fails if isolation cannot be established.

To verify an installed wheel, stage it into a fresh directory and select that package mount. The same suite and examples run with `src` omitted, the imported module's location is checked, and the generated console script is exercised inside the sandbox:

```sh
wheel_dir=$(mktemp -d)
package_dir=$(mktemp -d)
python -m pip wheel --no-deps --no-build-isolation --wheel-dir "$wheel_dir" .
python -m pip install --no-deps --no-compile --target "$package_dir" "$wheel_dir"/*.whl
python checks-offline.py --installed-package "$package_dir"
```

Wheel construction needs the declared setuptools build dependency plus wheel tooling. Staging/build tooling is separate from execution of the tested package. CI uses fresh runner temporary directories for these steps.

On GitHub-hosted Linux runners, CI explicitly selects `--github-hosted-runner`. That mode checks the runner environment and uses `sudo -n` only for the system bubblewrap namespace bootstrap, addressing Ubuntu's restricted unprivileged loopback setup. It preserves all namespaces, read-only mounts, and network isolation; before importing the package, the tested Python process must have the runner's numeric UID/GID **inside the user namespace**, zero effective capabilities, and `NoNewPrivs=1`. UID/GID maps are printed for inspection: numeric namespace identity is separate from host-user identity. No host sysctl or AppArmor settings are changed. This mode is restricted to ephemeral GitHub-hosted runners; local checks remain unprivileged and never invoke sudo. Namespace and identity options follow the [bubblewrap reference](https://github.com/containers/bubblewrap/blob/v0.9.0/bwrap.xml), with mapping behavior in its [original source](https://github.com/containers/bubblewrap/blob/v0.9.0/bubblewrap.c).

Hosted mode preflights only the selected public `src`/`tests`/`examples` trees, or `tests`/`examples` plus the fresh installed-package directory. It rejects symlinks, special files, and hidden entries before staging, with a combined 256-entry, 16-level, 8 MiB bound. It copies these inputs into its own temporary directory directly under `/tmp`, sets only those copies to traversable/readable permissions, mounts them read-only, and removes them on exit. This allows bubblewrap's mapped bootstrap to traverse the inputs without exposing a private runner home, checkout metadata, or credentials.

For systems without that Linux sandbox, the portable public suite can also run with `PYTHONPATH=src python -m unittest discover -s tests -v`. This command does not provide the wrapper's isolation. CI exercises Python 3.10, 3.12, and 3.14. Tests include parsing/limit tables, small exhaustive byte selection, huge numerals, type validation, CLI streams/exit codes, and synthetic examples.

MIT license, copyright 2026 Martin. See [LICENSE](LICENSE).
