"""Discover local HDF granules and group by acquisition date."""
import re
from collections import defaultdict
from pathlib import Path

PATTERN = re.compile(r"^(?P<product>[A-Za-z0-9]+)\.A(?P<year>\d{4})(?P<doy>\d{3})\.(?P<tile>h\d{2}v\d{2})\.")

def scan(root, product=None, year=None):
    groups = defaultdict(list)
    for path in sorted(Path(root).rglob("*.hdf")):
        match = PATTERN.match(path.name)
        if not match:
            continue
        info = match.groupdict()
        if product and info["product"] != product:
            continue
        if year and int(info["year"]) != int(year):
            continue
        groups[f'{info["year"]}{info["doy"]}'].append(str(path))
    return dict(sorted(groups.items()))
