"""Resolve a synthetic in-memory representation; no file or network inputs."""

from http_range_tools import resolve_range

data = b"abcdefghijkl"
result = resolve_range("bytes=2-4,30-,-2", len(data))
assert result.satisfiable and result.unsatisfied_count == 1
assert [data[part.start:part.stop] for part in result.ranges] == [b"cde", b"kl"]
for part in result.ranges:
    print(f"[{part.start}:{part.stop}] = {data[part.start:part.stop]!r}")
