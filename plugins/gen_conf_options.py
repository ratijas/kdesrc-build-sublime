#!/usr/bin/env python3
"""
Navigate to this file's directory, and run it like this:

    $ python gen_conf_options.py /home/ratijas/projects/KDE/sdk/kdesrc-build

"""

import json
import os
import sys
import subprocess
import shutil
import tempfile
from typing import Iterable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from lib import *

TOOL = "meinproc5"

BASE_DIR = "~/kdesrc-build"

INDEX = "doc/index.docbook"
FILENAME = "conf-options-table.html"


def parse_region(name, text) -> RegionTypeRestriction:
    # special case, documentation seem to be wrong about it
    if name == "ignore-modules":
        return RegionTypeRestriction.GLOBAL | RegionTypeRestriction.MODULE_SET

    if "Cannot be overridden" in text:
        return RegionTypeRestriction.GLOBAL

    if "Can only use in" in text:
        return RegionTypeRestriction.MODULE_SET

    if "Module setting overrides global" in text:
        return RegionTypeRestriction.ANY

    return RegionTypeRestriction.ANY


def parse_option(tr: Tag) -> Optional[Option]:
    name, behavior, notes = tuple(tr.children)

    assert isinstance(name, Tag) and isinstance(behavior, Tag) and isinstance(notes, Tag)

    anchor = name.find('a')
    if anchor is None:
        print("Skipping deprecated and removed option", name.text)
        return None
    assert isinstance(anchor, Tag)

    for a in notes.find_all("a"):
        assert isinstance(a, Tag)
        href = a.attrs.get("href", None)
        if href is None:
            continue

        if href.startswith("http://") or href.startswith("https://"):
            continue

        a.attrs["href"] = urljoin(DOC_BASE_URL, href)

    region = parse_region(name.text, behavior.text)
    notes = ''.join(map(str, notes.contents)).strip()

    return Option(name=name.text, anchor=anchor.attrs["name"], region=region, notes=notes)


def parse_options(soup: BeautifulSoup) -> Iterable[Option]:
    table = soup.find("table", class_="table")
    assert isinstance(table, Tag)

    tbody = table.find('tbody')
    assert isinstance(tbody, Tag)

    for tr in tbody.children:
        assert isinstance(tr, Tag)
        option = parse_option(tr)
        if option is not None:
            yield option



def main(basedir: str = BASE_DIR, *argv):
    tmpdir = tempfile.mkdtemp()

    INPUT = os.path.join(os.path.expanduser(basedir), INDEX)
    OUTPUT = os.path.join(tmpdir, FILENAME)

    print("Temp dir:", tmpdir)
    print("Temp file:", OUTPUT)

    try:
        proc = subprocess.run([TOOL, INPUT], cwd=tmpdir, check=True)

        with open(OUTPUT, 'r') as f:
            soup = BeautifulSoup(f, features="lxml")

        options = list(parse_options(soup))

        with open("conf_options.json", "w") as f:
            json.dump(options, f, cls=OptionEncoder, indent=2)

    finally:
        shutil.rmtree(tmpdir)

if __name__ == '__main__':
    main(*sys.argv[1:])
