import sublime
import sublime_plugin

class CloseRegionCommand(sublime_plugin.TextCommand):
    def run(self, edit: sublime.Edit) -> None:
        sel = self.view.sel()
        if len(sel) != 1:
            sublime.status_message("Refusing to insert end of region for multiple selections")
            return

        s = sel[0]
        line_region = self.view.line(s.end())

        for kind in ("global", "module-set", "module", "options"):
            scope = "meta.block.%s.kdesrc-build" % kind
            if self.view.match_selector(s.end(), "%s - meta.expected-string.kdesrc-build - comment" % scope):
                replacement = "end %s\n" % kind
                self.view.replace(edit, line_region, replacement)
                break;

    def is_enabled(self):
        return self.view.match_selector(0, "source.kdesrc-build")
