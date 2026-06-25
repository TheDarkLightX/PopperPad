from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from .pad import PopperPad


CSS = """
Screen {
    background: $surface;
    color: $text;
}

#main {
    layout: vertical;
    padding: 0 1;
}

.dashboard {
    height: auto;
    padding: 0 1;
    border: solid $primary;
    background: $panel;
    margin-bottom: 1;
}

.browser {
    height: 1fr;
    border: solid $accent;
    padding: 0 1;
}

.detail {
    height: 1fr;
    border: solid $secondary;
    padding: 0 1;
}

.stat-label {
    color: $text-muted;
}

.stat-value {
    color: $text-bold;
    text-style: bold;
}

.status-badge {
    text-style: bold;
}

.status-supported { color: green; }
.status-falsified { color: red; }
.status-disputed  { color: yellow; }
.status-unknown   { color: $text-muted; }

ListView {
    height: 1fr;
}

ListItem {
    padding: 0 1;
}

ListItem:hover {
    background: $primary 20%;
}

.action-bar {
    height: 3;
    dock: bottom;
    padding: 0 1;
    background: $boost;
}
"""

STATUS_COLORS = {
    "supported": "bold green",
    "falsified": "bold red",
    "disputed": "bold yellow",
    "unknown": "dim",
}


class DashboardWidget(Static):
    """Live pad statistics: object count, log head, schema distribution."""

    def __init__(self, pad: PopperPad) -> None:
        super().__init__("")
        self._pad = pad

    def render(self) -> Panel:
        stats = self._pad.log.stats()
        doctor = self._pad.doctor(strict=False)
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("key", style="dim")
        table.add_column("value", style="bold")
        table.add_row("objects", str(doctor.stats.get("objects", 0)))
        table.add_row("blobs", str(doctor.stats.get("blobs", 0)))
        table.add_row("log events", str(stats.get("event_count", 0)))
        table.add_row("log head", str(stats.get("head", ""))[:20] + "...")
        table.add_row("integrity", "OK" if doctor.ok else f"{len(doctor.issues)} issues")
        schemas = doctor.stats.get("schemas", {})
        schema_str = ", ".join(f"{k}: {v}" for k, v in sorted(schemas.items()))
        table.add_row("schemas", schema_str or "(none)")
        return Panel(table, title="[bold]Pad Dashboard[/]", border_style="blue")


class ObjectListWidget(ListView):
    """Browseable list of all objects in the pad."""

    objects: reactive[list[tuple[str, str]]] = reactive([])

    def __init__(self, pad: PopperPad) -> None:
        super().__init__()
        self._pad = pad

    def on_mount(self) -> None:
        self.refresh_objects()

    def refresh_objects(self) -> None:
        self.clear()
        items: list[ListItem] = []
        for record in self._pad.log.iter_records():
            if record.get("op") != "add_object":
                continue
            ref = str(record.get("obj_ref", ""))
            schema = str(record.get("obj_schema", ""))
            label = Text(f"{schema.split('/')[-1] if '/' in schema else schema}  ", style="cyan")
            label.append(ref[:20], style="dim")
            items.append(ListItem(Label(label), name=ref))
        for item in items:
            self.append(item)


class DetailWidget(Static):
    """Detail view for the selected object."""

    def __init__(self, pad: PopperPad) -> None:
        super().__init__("[dim]Select an object to view details.[/]")
        self._pad = pad
        self._current_ref: str | None = None

    def show_object(self, ref: str) -> None:
        self._current_ref = ref
        try:
            obj = self._pad.get_object(ref)
        except Exception as e:
            self.update(f"[red]Error: {e}[/]")
            return
        if not isinstance(obj, dict):
            self.update(f"[dim]{obj}[/]")
            return
        tree = Tree(f"[bold cyan]{obj.get('schema', 'unknown')}[/]")
        self._render_dict(tree, obj, depth=0)
        from rich.console import Group
        self.update(Group(tree))

    def _render_dict(self, tree: Tree, data: dict, depth: int) -> None:
        if depth > 4:
            tree.add("[dim]...[/]")
            return
        for key in sorted(data.keys()):
            value = data[key]
            if isinstance(value, dict) and depth < 3:
                branch = tree.add(f"[yellow]{key}[/]")
                self._render_dict(branch, value, depth + 1)
            elif isinstance(value, list):
                branch = tree.add(f"[yellow]{key}[/] ({len(value)} items)")
                for i, item in enumerate(value[:5]):
                    if isinstance(item, dict):
                        sub = branch.add(f"[dim][{i}][/]")
                        self._render_dict(sub, item, depth + 1)
                    else:
                        branch.add(f"[dim][{i}][/ {item}")
                if len(value) > 5:
                    branch.add(f"[dim]... {len(value) - 5} more[/]")
            else:
                val_str = str(value)
                if len(val_str) > 60:
                    val_str = val_str[:57] + "..."
                tree.add(f"[yellow]{key}[/]: [white]{val_str}[/]")


class PopperPadTUI(App):
    """PopperPad textual TUI — minimal, polished, keyboard-driven."""

    CSS = CSS
    TITLE = "PopperPad"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("d", "doctor", "Doctor"),
        Binding("s", "status", "Status"),
    ]

    def __init__(self, pad_root: Path) -> None:
        super().__init__()
        self.pad = PopperPad(root=pad_root)
        self.pad.init()

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main"):
            yield DashboardWidget(self.pad)
            with Horizontal():
                with Vertical(classes="browser"):
                    yield Label("[bold]Objects[/]", id="obj-header")
                    yield ObjectListWidget(self.pad)
                with Vertical(classes="detail"):
                    yield Label("[bold]Detail[/]", id="detail-header")
                    yield DetailWidget(self.pad)
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        ref = event.item.name
        if ref:
            self.query_one(DetailWidget).show_object(ref)

    def action_refresh(self) -> None:
        self.query_one(DashboardWidget).refresh()
        self.query_one(ObjectListWidget).refresh_objects()

    def action_doctor(self) -> None:
        report = self.pad.doctor(strict=False)
        if report.ok:
            self.bell()
            self.query_one(DashboardWidget).update(
                f"[bold green]Doctor: all checks pass ({report.stats.get('objects', 0)} objects)[/]"
            )
        else:
            lines = [f"[bold red]Doctor: {len(report.issues)} issues found[/]"]
            for issue in report.issues[:5]:
                lines.append(f"  [yellow]{issue.get('kind', '?')}[/]: {issue.get('error', '')}")
            self.query_one(DashboardWidget).update("\n".join(lines))

    def action_status(self) -> None:
        self.query_one(DashboardWidget).update(
            "[dim]Select a hypothesis object, then press 's' to check its status.[/]"
        )


def run_tui(pad_root: str) -> None:
    """Entry point for the TUI."""
    app = PopperPadTUI(pad_root=Path(pad_root))
    app.run()


def print_dashboard(pad_root: str) -> None:
    """Non-interactive rich dashboard for CLI use."""
    pad = PopperPad(root=Path(pad_root))
    pad.init()
    console = Console()
    stats = pad.log.stats()
    doctor = pad.doctor(strict=False)
    table = Table(title="[bold blue]PopperPad Dashboard[/]", show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold")
    table.add_row("Objects", str(doctor.stats.get("objects", 0)))
    table.add_row("Blobs", str(doctor.stats.get("blobs", 0)))
    table.add_row("Log Events", str(stats.get("event_count", 0)))
    table.add_row("Log Head", str(stats.get("head", ""))[:32])
    table.add_row("Integrity", "[green]OK[/]" if doctor.ok else f"[red]{len(doctor.issues)} issues[/]")
    schemas = doctor.stats.get("schemas", {})
    for schema, count in sorted(schemas.items()):
        table.add_row(f"  {schema}", str(count))
    console.print(table)
    if doctor.issues:
        console.print("[bold red]Issues:[/]")
        for issue in doctor.issues[:10]:
            console.print(f"  [yellow]{issue.get('kind', '?')}[/]: {issue.get('error', '')}")
