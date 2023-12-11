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


def parse_region(name, text) -> ScopeRestriction:
    # special case, documentation seem to be wrong about it
    if name == "ignore-modules":
        return ScopeRestriction.GLOBAL | ScopeRestriction.MODULE_SET

    if "Cannot be overridden" in text:
        return ScopeRestriction.GLOBAL

    if "Can only use in" in text:
        return ScopeRestriction.MODULE_SET

    if "Module setting overrides global" in text:
        return ScopeRestriction.ANY

    return ScopeRestriction.ANY


def convert_table(soup: BeautifulSoup, table: Tag):
    replacement = soup.new_tag("div")

    for tr in table.find_all("tr"):
        assert isinstance(tr, Tag) and tr.name == "tr"
        key, value = tr.children
        assert isinstance(key, Tag) and key.name == "td"
        assert isinstance(value, Tag) and value.name == "td"

        key_text = key.text
        if not key_text.endswith(":"):
            key_text += ":"

        key_tag = soup.new_tag("b")
        key_tag.append(key_text)

        value_text = value.text
        value_tag = soup.new_tag("span")
        value_tag.append(value_text)

        line_tag = soup.new_tag("p")
        line_tag.append(key_tag)
        line_tag.append(" ")
        line_tag.append(value_tag)

        replacement.append(line_tag)

    table.replace_with(replacement)


def parse_option(soup: BeautifulSoup, scope: ScopeRestriction, tr: Tag) -> Optional[Option]:
    """
    A row with option has the following format:

        Option name | Description

    Where description cell embeds another table with structured meta-data:

        Type            Boolean
        Default value   True
        Available since 1.6

    The rest of the description cell's content is HTML text.
    """
    name, description = tuple(tr.children)

    assert isinstance(name, Tag)
    assert isinstance(description, Tag)

    anchor = name.find('a')
    if anchor is None:
        print("Skipping deprecated and removed option", name.text)
        return None
    assert isinstance(anchor, Tag)

    for a in description.find_all("a"):
        assert isinstance(a, Tag)
        href = a.attrs.get("href", None)
        if href is None:
            continue

        if href.startswith("http://") or href.startswith("https://"):
            continue

        a.attrs["href"] = urljoin(DOC_BASE_URL, href)

    for table in description.find_all("table", class_="simplelist"):
        assert isinstance(table, Tag)
        convert_table(soup, table)

    notes = ''.join(map(str, description.contents)).strip()

    return Option(name=name.text, anchor=anchor.attrs["name"], scope=scope, notes=notes)


def parse_options(soup: BeautifulSoup) -> Iterable[Option]:
    """
    There are three tables in documentation now:
    1. Global scope only options
    2. All scopes (module, module-set and global) options
    3. Module-set scope only options
    """
    scopes = [ScopeRestriction.GLOBAL, ScopeRestriction.ANY, ScopeRestriction.MODULE_SET]
    tables = soup.find_all("table", class_="table")

    for scope, table in zip(scopes, tables):
        tbody = table.find('tbody')
        assert isinstance(tbody, Tag)

        for tr in tbody.children:
            assert isinstance(tr, Tag)
            option = parse_option(soup, scope, tr)
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
