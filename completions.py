from dataclasses import dataclass
from enum import Enum
import html
import json
import multiprocessing
from pathlib import Path
import os
import subprocess
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Type, Union, Tuple
from urllib.parse import urljoin

import sublime
import sublime_plugin
from sublime import View, CompletionItem, CompletionList, Region, Window

from .plugins.lib import *
from .plugins.lib.langs import LANGUAGES

Point = int
HoverZone = int
OptionType = Type[Union[bool, int, str, Path]]

KDESRC_BUILD_SYNTAX = f"Packages/{__package__}/kdesrc-build.sublime-syntax"
KDESRC_BUILD_DOCS_JSON = f"Packages/{__package__}/plugins/conf_options.json"
INCLUDE_KEY = "include"

DOCUMENT_LINK_FLAGS = sublime.HIDE_ON_MINIMAP | sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE | sublime.DRAW_SOLID_UNDERLINE  # noqa: E501

POPUP_TEMPLATE = """
<body id="kdesrc-build-documentation">
<style>
    html.light {{
        --html-background: color(var(--background) blend(black 91%));
        --border-color: color(var(--html-background) blend(black 95%));
    }}
    html.dark {{
        --html-background: color(var(--background) blend(white 93%));
        --border-color: color(var(--html-background) blend(white 95%));
    }}
    html, body {{
        margin: 0;
        padding: 0;
        background-color: var(--html-background);
        color: var(--foreground);
    }}
    h1, h2 {{
        border-bottom: 1px solid var(--border-color);
        font-weight: normal;
        margin: 0;
        padding: 0.5rem 0.6rem;
    }}
    h1 {{
        color: var(--orangish);
        font-size: 1.0rem;
    }}
    html.light h1 {{
        color: var(--redish);
    }}
    h2 {{
        color: color(var(--html-background) blend(var(--foreground) 30%));
        font-size: 1.0rem;
        font-family: monospace;
    }}
    p {{
        margin: 0;
        padding: 0.5rem;
    }}
    a {{
        text-decoration: none;
    }}
</style>
{0}
</body>
"""

class RegionType(Enum):
    GLOBAL = "global"
    MODULE_SET = "module-set"
    MODULE = "module"
    OPTIONS = "options"

    def may_contain(self, restricted: RegionTypeRestriction):
        if restricted == RegionTypeRestriction.ANY:
            return True
        elif restricted == (RegionTypeRestriction.GLOBAL | RegionTypeRestriction.MODULE_SET):
            return self in (RegionType.MODULE_SET, RegionType.OPTIONS)
        elif restricted == RegionTypeRestriction.GLOBAL:
            return self == RegionType.GLOBAL
        elif restricted == RegionTypeRestriction.MODULE_SET:
            return self == RegionType.MODULE_SET
        else:
            return True

CompletionData = Union[int, str, CompletionItem]

@dataclass
class OptionDescriptor:
    name: str
    type: OptionType
    region: RegionTypeRestriction = RegionTypeRestriction.ANY
    choices: Union[Sequence[CompletionData], Set[CompletionData]] = ()
    default: Any = None
    default_fn: Optional[Callable[[], Any]] = None
    doc: str = ""
    anchor: str = ""
    since: str = ""
    deprecated: bool = False

    def fill(self, item: CompletionItem, value: Any, short: bool = False) -> CompletionItem:
        if self.deprecated:
            item.annotation = "Deprecated"
        else:
            default = self.get_default()
            if self.type == int:
                default = str(default)
            if default == value:
                item.annotation = "Default value"

        if short:
            item.details = make_command_link("kdesrc_build_resolve_docs", "More", { "option": self.name })
        else:
            item.details = self.render()

        return item

    def render(self) -> str:
        output = "<h1>{}</h1>".format(html.escape(self.name))
        if self.default is not None:
            output += "<h2>Default: {}</h2>".format(html.escape(sublime.encode_value(self.default)))
        elif self.default_fn is not None:
            output += "<h2>Default: {}</h2>".format(html.escape(sublime.encode_value(self.default_fn())))
        if self.doc:
            output += "<p>{}</p>".format(self.doc)  # deliberately do not escape
        if self.since:
            output += "<h2>Since: {}</h2>".format(html.escape(self.since))
        if self.anchor:
            href = urljoin(DOC_BASE_URL, '#' + self.anchor)
            output += '<p><a href="{}">Read more at kdesrc-build website</a></p>'.format(href)
        return output

    def has_default(self) -> bool:
        return self.default is not None or self.default_fn is not None

    def get_default(self) -> Any:
        if self.default is not None:
            return self.default
        if self.default_fn is not None:
            return self.default_fn()
        return None


def make_link(href: str, text: Any, class_name: Optional[str] = None) -> str:
    if isinstance(text, str):
        text = text.replace(' ', '&nbsp;')
    if class_name:
        return "<a href='{}' class='{}'>{}</a>".format(href, class_name, text)
    else:
        return "<a href='{}'>{}</a>".format(href, text)


def make_command_link(command: str, text: str, command_args: Optional[Dict[str, Any]] = None,
                      class_name: Optional[str] = None, view: Optional[sublime.View] = None) -> str:
    if view:
        cmd = "kdesrc_build_text_command_helper"
        args = {"view_id": view.id(), "command": command, "args": command_args}  # type: Optional[Dict[str, Any]]
    else:
        cmd = command
        args = command_args
    return make_link(sublime.command_url(cmd, args), text, class_name)


class KdesrcBuildTextCommandHelperCommand(sublime_plugin.WindowCommand):
    def run(self, view_id: int, command: str, args: Optional[Dict[str, Any]] = None) -> None:
        view = sublime.View(view_id)
        if view.is_valid():
            view.run_command(command, args)


class KdesrcBuildResolveDocsCommand(sublime_plugin.TextCommand):
    def run(self, edit: sublime.Edit, option: str):

        descriptor = get_option_descriptor(option)
        if descriptor is None:
            return

        minihtml_content = POPUP_TEMPLATE.format(descriptor.render())

        def run_main() -> None:
            if not self.view.is_valid():
                return
            if self.view.is_popup_visible():
                self.view.update_popup(minihtml_content)
            else:
                window_width = min(1000, int(self.view.viewport_extent()[0]) - 64)
                self.view.show_popup(
                    content=minihtml_content,
                    max_width=window_width,
                    flags=sublime.COOPERATE_WITH_AUTO_COMPLETE)


        sublime.set_timeout(run_main)

CMAKE_GENERATORS = (
    "Unix Makefiles",
    "Ninja",
    "Ninja Multi-Config",
    "CodeBlocks - Ninja",
    "CodeBlocks - Unix Makefiles",
    "CodeLite - Ninja",
    "CodeLite - Unix Makefiles",
    "Eclipse CDT4 - Ninja",
    "Eclipse CDT4 - Unix Makefiles",
    "Kate - Ninja",
    "Kate - Unix Makefiles",
    "Sublime Text 2 - Ninja",
    "Sublime Text 2 - Unix Makefiles",
)

def default_git_user() -> str:
    try:
        return subprocess.check_output('echo "$(git config user.name) <$(git config user.email)>"', shell=True, text=True).strip()
    except subprocess.SubprocessError as e:
        return "User Name <email@example.com>"

MODULES: Set[CompletionData] = set()
"""Global set of modules, will be filled asynchronously later."""

# See https://docs.kde.org/trunk5/en/kdesrc-build/kdesrc-build/conf-options-table.html
def ensure_registry():
    global OPTION_DESCRIPTOR_REGISTRY
    if len(OPTION_DESCRIPTOR_REGISTRY) != 0:
        return

    REGISTRY_LIST = [
        # apidox: Removed in 1.6.3
        # apply-qt-patches: Removed in 1.10
        OptionDescriptor("async",                           type=bool, default=True, since="1.6"),
        OptionDescriptor("binpath",                         type=Path),
        OptionDescriptor("branch",                          type=str),
        OptionDescriptor("branch-group",                    type=str,  default="kf5-qt5", choices=("kf5-qt5",), since="1.16-pre2"),
        OptionDescriptor("build-dir",                       type=Path, default="build"),
        OptionDescriptor("build-when-unchanged",            type=bool),
        OptionDescriptor("checkout-only",                   type=bool),
        OptionDescriptor("cmake-generator",                 type=str, default="Unix Makefiles", choices=CMAKE_GENERATORS),
        OptionDescriptor("cmake-toolchain",                 type=str),
        OptionDescriptor("cmake-options",                   type=str),
        OptionDescriptor("colorful-output",                 type=bool, default=True),
        OptionDescriptor("compile-commands-export",         type=bool, default=True),
        OptionDescriptor("compile-commands-linking",        type=bool, default=False),
        OptionDescriptor("configure-flags",                 type=str),
        OptionDescriptor("custom-build-command",            type=str),
        OptionDescriptor("cxxflags",                        type=str),
        OptionDescriptor("dest-dir",                        type=str),
        OptionDescriptor("disable-agent-check",             type=bool, default=False),
        OptionDescriptor("do-not-compile",                  type=str),
        OptionDescriptor("git-desired-protocol",            type=str, choices=("git", "https"), default="git", since="1.16"),
        OptionDescriptor("git-repository-base",             type=str, since="1.12.1"),
        OptionDescriptor("git-user",                        type=str, default_fn=default_git_user, since="15.09"),
        OptionDescriptor("http-proxy",                      type=str, since="1.16"),
        OptionDescriptor("ignore-kde-structure",            type=bool, deprecated=True),
        OptionDescriptor("directory-layout",                type=str, default="metadata", choices=("flat", "invent", "metadata")),  # docs lie about "flat" being the default one
        OptionDescriptor("ignore-modules",                  type=str, choices=MODULES, since="1.16"),
        OptionDescriptor("include-dependencies",            type=bool, default=True),
        OptionDescriptor("install-after-build",             type=bool, default=True),
        OptionDescriptor("install-environment-driver",      type=bool, default=True, since="17.08"),
        OptionDescriptor("install-session-driver",          type=bool, default=True, since="1.16"),
        OptionDescriptor("kdedir",                          type=Path, default="~/kde", choices=("/usr/local/kde")),
        OptionDescriptor("kde-languages",                   type=str, choices=LANGUAGES),
        OptionDescriptor("libpath",                         type=Path),
        OptionDescriptor("log-dir",                         type=Path),
        OptionDescriptor("make-install-prefix",             type=Path),
        OptionDescriptor("make-options",                    type=str),
        OptionDescriptor("manual-build",                    type=bool, default=False),
        OptionDescriptor("manual-update",                   type=bool, default=False),
        OptionDescriptor("module-base-path",                type=str, choices=("trunk/$module", "trunk/KDE/$module")),
        OptionDescriptor("niceness",                        type=int, default=10, choices=list(range(0, 20 + 1))),
        OptionDescriptor("ninja-options",                   type=str),
        OptionDescriptor("no-svn",                          type=bool, default=False),
        OptionDescriptor("num-cores",                       type=int, default=4, choices=list(range(1, multiprocessing.cpu_count() + 1)), since="20.07"),
        OptionDescriptor("num-cores-low-mem",               type=int, default=2, choices=list(range(1, multiprocessing.cpu_count() + 1)), since="20.07"),
        OptionDescriptor("override-build-system",           type=str, choices=("KDE", "Qt", "qmake", "generic", "autotools", "meson"), since="1.16"),
        OptionDescriptor("override-url",                    type=str),
        OptionDescriptor("persistent-data-file",            type=Path, default="~/.local/state/kdesrc-build-data", choices=("~/.config/kdesrc-build-data", "~/.local/state/kdesrc-build-data",), since="1.15"),
        OptionDescriptor("prefix",                          type=Path),
        OptionDescriptor("purge-old-logs",                  type=bool, default=True),
        OptionDescriptor("qmake-options",                   type=str, since="1.16"),
        OptionDescriptor("qtdir",                           type=Path),
        OptionDescriptor("remove-after-install",            type=str, default="none", choices=("none", "builddir", "all")),
        OptionDescriptor("repository",                      type=str, since="1.10"),
        OptionDescriptor("revision",                        type=str),
        OptionDescriptor("run-tests",                       type=bool, default=False),
        OptionDescriptor("set-env",                         type=str),
        OptionDescriptor("source-dir",                      type=Path, default="~/kdesrc", choices=("~/kde/src",)),
        OptionDescriptor("ssh-identity-file",               type=Path),
        OptionDescriptor("stop-on-failure",                 type=bool, default=False),
        OptionDescriptor("svn-server",                      type=str),
        OptionDescriptor("tag",                             type=str),
        OptionDescriptor("use-clean-install",               type=bool, default=False, since="1.12"),
        OptionDescriptor("use-idle-io-priority",            type=bool, default=False, since="1.12"),
        OptionDescriptor("use-inactive-modules",            type=bool, default=False, since="1.12"),
        OptionDescriptor("use-modules",                     type=str, since="1.12.1"),
    ]

    docs_list = json.loads(sublime.load_resource(KDESRC_BUILD_DOCS_JSON), cls=OptionDecoder)  # type: List[Option]
    docs = { option.name: option for option in docs_list }  # type: Dict[str, Option]

    options = {}
    for option in REGISTRY_LIST:
        if option.name in options:
            print("WARNING: Duplicated option", option.name)

        doc = docs.pop(option.name, None)
        if doc is None:
            print("WARNING: Undocumented option", option.name)

        else:
            if not option.doc:
                option.doc = doc.notes
            option.region = doc.region
            option.anchor = doc.anchor

        options[option.name] = option

    if len(docs) != 0:
        print("WARNING: Missing options", docs.keys())

    OPTION_DESCRIPTOR_REGISTRY = options


def registry() -> Dict[str, OptionDescriptor]:
    ensure_registry()
    return OPTION_DESCRIPTOR_REGISTRY


OPTION_DESCRIPTOR_REGISTRY = {}

FALLBACK_OPTION_DESCRIPTOR = OptionDescriptor(name="Unknown option", type=str, region=RegionTypeRestriction.ANY)


def get_option_descriptor(option: str) -> OptionDescriptor:
    descriptor = registry().get(option, FALLBACK_OPTION_DESCRIPTOR)
    return descriptor

def is_applicable(settings: sublime.Settings) -> bool:
    return settings.get("syntax") == KDESRC_BUILD_SYNTAX

def get_region(view: View, pt: Point) -> Optional[RegionType]:
    if view.match_selector(pt, "meta.block.global.kdesrc-build"):
        return RegionType.GLOBAL
    elif view.match_selector(pt, "meta.block.module-set.kdesrc-build"):
        return RegionType.MODULE_SET
    elif view.match_selector(pt, "meta.block.module.kdesrc-build"):
        return RegionType.MODULE
    elif view.match_selector(pt, "meta.block.options.kdesrc-build"):
        return RegionType.OPTIONS
    else:
        return None

def get_key_region_at(view: View, pt: Point) -> Union[None, Region]:
    """Return the key region if point is on a settings key or None."""
    if view.match_selector(pt, KEY_SCOPE):
        for region in view.find_by_selector(KEY_SCOPE):
            if region.contains(pt):
                return region
    return None

KEY_SCOPE = "support.function.kdesrc-build"

def get_known_option_name_at_line(view: View, pt: Point) -> Optional[str]:
    for region in view.find_by_selector(KEY_SCOPE):
        line = view.line(region)
        if line.contains(pt):
            return view.substr(region)
    return None

def get_known_option_name_at_location(view: View, pt: Point) -> Optional[Region]:
    for region in view.find_by_selector(KEY_SCOPE):
        if region.contains(pt):
            return region
    return None


def get_include_dirs(view: View, skip: Point) -> Tuple[str, List[str]]:
    includes = view.find_by_selector("keyword.import.kdesrc-build")

    mine = ""
    others = []

    for include in includes:
        line = view.line(include.end())
        overshoot = Region(include.end(), line.end())
        path = view.substr(overshoot).strip()
        if line.contains(skip):
            mine = path
        else:
            base = os.path.dirname(path)
            if len(base) != 0:
                others.append(base)

    return (mine, others)

def get_filesystem_completions(folder: str) -> List[CompletionItem]:
    try:
        items = os.listdir(folder)
    except IOError:
        return []

    dirs = []
    files = []
    others = []
    for item in items:
        path = os.path.join(folder, item)
        try:
            if os.path.isdir(path):
                dirs.append(item)
            elif os.path.isfile(path):
                files.append(item)
            else:
                others.append(item)
        except IOError:
            pass
    dirs.sort()
    files.sort()
    others.sort()

    completions = []
    for item in dirs:
        completions.append(CompletionItem(item, completion=item + '/', kind=sublime.KIND_NAMESPACE))
    for item in files:
        completions.append(CompletionItem(item, completion=item, kind=sublime.KIND_FUNCTION))
    for item in others:
        completions.append(CompletionItem(item, completion=item, kind=sublime.KIND_AMBIGUOUS))

    return completions


def plugin_loaded():
    sublime.set_timeout_async(query_modules)


def query_modules():
    if len(MODULES) != 0:
        return

    try:
        stdout = subprocess.check_output(["kdesrc-build", "--list-build", "--no-src"], text=True)
    except subprocess.SubprocessError as e:
        sublime.status_message("kdesrc-build: Failed to fetch list of modules")
        return

    # `head -n 1` because kdesrc-build prints this at the end:
    # No modules to build, exiting.
    lines = stdout.splitlines()[:-1]

    # each line looks like this:
    #  ── gammaray : master
    # or this:
    #  ── knotes
    for line in lines:
        try:
            module = line.split()[1]  # cut -d' ' -f 3
            MODULES.add(module)
        except IndexError:
            pass

    sublime.status_message("kdesrc-build: Loaded list of modules")


class KdesrcBuildCompletionsProvider(sublime_plugin.ViewEventListener):
    def on_query_completions(self, prefix: str, locations: List[Point]) -> Union[None, CompletionList]:
        if len(locations) == 0 or not self.is_enabled():
            return None

        loc = locations[0]

        if self.view.match_selector(loc, "comment"):
            return None

        if not self.view.match_selector(loc, "meta.block"):
            return self.complete_includes(loc)

        region = get_region(self.view, loc)
        if region is None:
            return None

        option_name = get_known_option_name_at_line(self.view, loc)
        if option_name is None:
            return self.complete_option_name(region, prefix, loc,)

        option = get_option_descriptor(option_name)

        if self.view.match_selector(loc, "meta.expected.bool.kdesrc-build") and option.type is bool:
            return CompletionList([
                option.fill(CompletionItem("true", kind=sublime.KIND_VARIABLE), True, short=True),
                option.fill(CompletionItem("false", kind=sublime.KIND_VARIABLE), False, short=True),
            ], sublime.INHIBIT_WORD_COMPLETIONS)

        if self.view.match_selector(loc, "meta.expected.string.kdesrc-build") and option.type in (int, str, Path) \
                and (len(option.choices) > 0 or option.has_default()):

            def key(choice: CompletionData) -> Union[int, str]:
                if isinstance(choice, int):
                    assert isinstance(option.type, int)
                    return choice
                if isinstance(choice, str):
                    return choice
                if isinstance(choice, CompletionItem):
                    return choice.trigger

            def item(pair: Tuple[Union[int, str], CompletionData]) -> CompletionItem:
                choice = pair[1]
                if isinstance(choice, CompletionItem):
                    return choice
                else:
                    assert isinstance(choice, (int, str))
                    return CompletionItem(str(choice), kind=sublime.KIND_VARIABLE)

            choices = { key(c): c for c in option.choices }
            if option.has_default():
                c = option.get_default()
                choices[key(c)] = c
            choices = list(map(item, sorted(choices.items())))

            return CompletionList([
                option.fill(choice, choice.trigger, short=True)
                for choice in choices
            ], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_REORDER)

        return None

    def complete_includes(self, loc: Point) -> Union[None, CompletionList]:
        line = self.view.substr(self.view.line(loc))

        if line.lstrip().startswith("include "):
            # suggest files from the same locations
            mine, others = get_include_dirs(self.view, loc)

            if len(mine) == 0:
                others = list(sorted(set(others)))
                completions = [
                    CompletionItem(item, completion=item + '/', kind=sublime.KIND_NAMESPACE)
                    for item in others
                ]
                return CompletionList(completions, sublime.INHIBIT_WORD_COMPLETIONS)

            else:
                completions = get_filesystem_completions(mine)
                return CompletionList(completions, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_REORDER)

        return CompletionList([
            CompletionItem("include", completion="include ", kind=sublime.KIND_KEYWORD, details="Include other configuration file")
        ], sublime.INHIBIT_WORD_COMPLETIONS)

    def complete_option_name(self, region: RegionType, prefix: str, loc: Point) -> Union[None, CompletionList]:

        options: List[OptionDescriptor] = []

        for option in registry().values():
            if (option.name.startswith(prefix) or len(prefix) == 0) and region.may_contain(option.region):
                options.append(option)

        if len(options) != 0:
            options.sort(key=lambda option: option.name)
            return CompletionList([
                option.fill(CompletionItem(option.name, completion=option.name + ' ', kind=sublime.KIND_VARIABLE), option.name, short=True)
                for option in options
            ], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_REORDER)

        return None

    def on_hover(self, point: Point, hover_zone: HoverZone):
        # not a settings file or not hovering text
        if hover_zone != sublime.HOVER_TEXT:
            return

        option = get_known_option_name_at_location(self.view, point)
        if option is None:
            return

        self.show_popup_for(option)

    def show_popup_for(self, region):
        option_name = self.view.substr(region)

        option = get_option_descriptor(option_name)
        if option is None:
            return

        body = option.render()
        window_width = min(1000, int(self.view.viewport_extent()[0]) - 64)
        # offset <h1> padding, if possible
        key_start = region.begin()
        location = max(key_start - 1, self.view.line(key_start).begin())

        self.view.show_popup(
            content=POPUP_TEMPLATE.format(body),
            location=location,
            max_width=window_width,
            flags=sublime.HIDE_ON_MOUSE_MOVE_AWAY | sublime.COOPERATE_WITH_AUTO_COMPLETE
        )

    def on_load(self):
        self.refresh_file_regions()

    def on_activated(self):
        self.refresh_file_regions()

    def on_modified(self):
        self.refresh_file_regions()

    def refresh_file_regions(self):
        if not self.is_enabled():
            return

        regions = []

        for region in self.view.find_by_selector("string.unquoted.kdesrc-build"):
            path = resolve_path(self.view, region)

            if os.path.exists(path):
                regions.append(region)

        self.view.add_regions(INCLUDE_KEY, regions,
            scope="markup.underline.link.lsp", flags=DOCUMENT_LINK_FLAGS)

    def is_enabled(self):
        return self.view.match_selector(0, "source.kdesrc-build")

    @classmethod
    def is_applicable(cls, settings: sublime.Settings) -> bool:
        return is_applicable(settings)


class KdesrcBuildGotoDefinitionEventListener(sublime_plugin.EventListener):
    def on_window_command(self, window: Window, name: str, args: Any):
        if name == 'goto_definition':
            view = window.active_view()
            if view is not None and is_applicable(view.settings()):
                return self._goto(window, view)

        return None

    def _goto(self, window: Window, view: View):
        sel = view.sel()
        if len(sel) != 1:
            return

        s = sel[0]

        region = view.expand_to_scope(s.end(), "string.unquoted.kdesrc-build")
        if region is not None and not region.empty():
            return self._goto_filesystem(window, view, region)

        return None

    def _goto_filesystem(self, window: Window, view: View, region: Region):
        path = resolve_path(view, region)

        if os.path.isfile(path):
            return "open_file", { "file": path }

        elif os.path.isdir(path):
            return "open_dir", { "dir": path }

        else:
            return None

def resolve_path(view: View, region: Region) -> str:
    path = view.substr(region)
    path = os.path.expanduser(os.path.expandvars(path))
    if not os.path.isabs(path):
        base = view.file_name()
        if base is not None:
            base = os.path.dirname(base)
            path = os.path.join(base, path)

    return path
