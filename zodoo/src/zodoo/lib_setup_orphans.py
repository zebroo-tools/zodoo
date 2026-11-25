"""`odoo setup orphans`: find and clean up settings of deleted projects.

`odoo setting KEY=VALUE` stores values in ``~/.odoo/settings.<project>``
and `odoo reload` generates ``~/.odoo/run/<project>/``. Both stay behind
when the project folder is deleted or renamed. This command lists them
and, on request, moves them into a trash folder.

The project path is read from ``HOST_CUSTOMS_DIR`` in the generated
``run/<project>/settings``. Entries without that information are reported
as "unknown" and are never touched.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import click

from .cli import pass_config
from .lib_setup import setup

STATUS_PRESENT = "present"
STATUS_MISSING = "missing"
STATUS_MOVED = "moved"
STATUS_UNKNOWN = "unknown"

STATUS_COLORS = {
    STATUS_PRESENT: "green",
    STATUS_MISSING: "red",
    STATUS_MOVED: "yellow",
    STATUS_UNKNOWN: "cyan",
}

TRASH_DIRNAME = ".trash"
TRASH_STAMP_FORMAT = "%Y%m%d-%H%M%S"


@dataclass
class ProjectEntry:
    name: str
    settings_file: Path
    run_dir: Path
    stored_path: Path | None
    status: str = STATUS_UNKNOWN
    found: list[Path] = field(default_factory=list)


def _read_stored_path(run_dir):
    """Return HOST_CUSTOMS_DIR from the generated run settings, or None."""
    settings = run_dir / "settings"
    if not settings.is_file():
        return None
    try:
        lines = settings.read_text(errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith("HOST_CUSTOMS_DIR="):
            value = line.split("=", 1)[1].strip().strip("'\"")
            return Path(value) if value else None
    return None


def _index_folders(search_dirs, depth):
    """Map folder name -> paths of all folders up to `depth` below each
    search dir. Symlinks are not followed."""
    index = {}
    for root in search_dirs:
        level = [Path(root).expanduser()]
        for _ in range(depth):
            next_level = []
            for folder in level:
                try:
                    children = list(os.scandir(folder))
                except OSError:
                    continue
                for child in children:
                    if child.is_dir(follow_symlinks=False):
                        path = Path(child.path)
                        index.setdefault(child.name, []).append(path)
                        next_level.append(path)
            level = next_level
    return index


def collect_entries(conf_dir, search_dirs=(), depth=2):
    """Classify every ``settings.<project>`` file below `conf_dir`.

    Searching for moved projects happens only when `search_dirs` is given.
    """
    conf_dir = Path(conf_dir)
    index = _index_folders(search_dirs, depth) if search_dirs else {}
    entries = []
    for settings_file in sorted(conf_dir.glob("settings.*")):
        if not settings_file.is_file():
            continue
        name = settings_file.name[len("settings.") :]
        run_dir = conf_dir / "run" / name
        stored_path = _read_stored_path(run_dir)
        entry = ProjectEntry(
            name=name,
            settings_file=settings_file,
            run_dir=run_dir,
            stored_path=stored_path,
        )
        if stored_path is None:
            entry.status = STATUS_UNKNOWN
        elif stored_path.is_dir():
            entry.status = STATUS_PRESENT
        else:
            entry.found = index.get(stored_path.name, [])
            entry.status = STATUS_MOVED if entry.found else STATUS_MISSING
        entries.append(entry)
    return entries


def _new_trash_dir(conf_dir, now):
    base = Path(conf_dir) / TRASH_DIRNAME
    stamp = now.strftime(TRASH_STAMP_FORMAT)
    target = base / stamp
    counter = 1
    while target.exists():
        target = base / f"{stamp}-{counter}"
        counter += 1
    return target


def move_to_trash(conf_dir, entries, now=None):
    """Move settings file and run dir of each entry with status "missing"
    into ``<conf_dir>/.trash/<timestamp>/``. Returns the trash folder, or
    None if nothing was moved."""
    to_move = [x for x in entries if x.status == STATUS_MISSING]
    if not to_move:
        return None
    target = _new_trash_dir(conf_dir, now or datetime.now())
    (target / "run").mkdir(parents=True)
    for entry in to_move:
        shutil.move(
            str(entry.settings_file), str(target / entry.settings_file.name)
        )
        if entry.run_dir.exists():
            shutil.move(str(entry.run_dir), str(target / "run" / entry.name))
    return target


def _trash_stamp(folder):
    # A suffix "-<n>" is added when two runs happen in the same second.
    stamp = "-".join(folder.name.split("-")[:2])
    try:
        return datetime.strptime(stamp, TRASH_STAMP_FORMAT)
    except ValueError:
        return None


def trash_entries_older_than(conf_dir, days, now=None):
    """Trash folders whose timestamp is more than `days` days old.
    Folders with a name that is not a timestamp are never returned."""
    trash = Path(conf_dir) / TRASH_DIRNAME
    if not trash.is_dir():
        return []
    limit = (now or datetime.now()) - timedelta(days=days)
    result = []
    for folder in sorted(trash.iterdir()):
        if folder.is_symlink() or not folder.is_dir():
            continue
        stamp = _trash_stamp(folder)
        if stamp is not None and stamp < limit:
            result.append(folder)
    return result


def purge_trash(conf_dir, folders):
    """Delete the given trash folders. Returns the folders that failed."""
    trash = (Path(conf_dir) / TRASH_DIRNAME).resolve()
    failed = []
    for folder in folders:
        if folder.resolve().parent != trash:
            raise ValueError(f"Not inside the trash folder: {folder}")
        try:
            shutil.rmtree(folder)
        except OSError as ex:
            click.secho(f"Could not remove {folder}: {ex}", fg="red")
            failed.append(folder)
    return failed


def _print_entries(entries, shown):
    for entry in shown:
        stored = entry.stored_path or "-"
        click.secho(
            f"{entry.status:8} ", fg=STATUS_COLORS[entry.status], nl=False
        )
        click.secho(f"{entry.name}  {stored}")
        for path in entry.found:
            click.secho(f"         -> found: {path}", fg="yellow")
    counts = {}
    for entry in entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1
    summary = ", ".join(
        f"{status}: {counts.get(status, 0)}"
        for status in (
            STATUS_PRESENT,
            STATUS_MISSING,
            STATUS_MOVED,
            STATUS_UNKNOWN,
        )
    )
    click.secho(f"\n{len(entries)} settings files - {summary}", bold=True)


def _confirm(config, text):
    if config.force:
        return True
    return click.confirm(text, default=False)


@setup.command(
    name="orphans",
    help=(
        "List settings.<project> files in ~/.odoo whose project folder no "
        "longer exists. Changes nothing unless --clean or --purge-trash is "
        "given."
    ),
)
@click.option(
    "-s",
    "--search-dir",
    "search_dirs",
    multiple=True,
    type=click.Path(file_okay=False),
    help=(
        "Folder to search for a project whose stored path is gone. A folder "
        "with the same name counts as moved. Can be given several times."
    ),
)
@click.option(
    "--depth",
    default=2,
    show_default=True,
    type=click.IntRange(min=1),
    help="How many folder levels below each --search-dir are searched.",
)
@click.option(
    "--only-orphans",
    is_flag=True,
    help="Do not list entries with status 'present'.",
)
@click.option(
    "--clean",
    is_flag=True,
    help=(
        "Move settings file and run folder of entries with status 'missing' "
        "to ~/.odoo/.trash/<timestamp>/ after confirmation."
    ),
)
@click.option(
    "--purge-trash",
    "purge_days",
    type=click.IntRange(min=0),
    help="Delete trash folders older than this many days after confirmation.",
)
@pass_config
def orphans(config, search_dirs, depth, only_orphans, clean, purge_days):
    conf_dir = Path(config.dirs["user_conf_dir"])
    entries = collect_entries(conf_dir, search_dirs=search_dirs, depth=depth)
    shown = [
        x for x in entries if not (only_orphans and x.status == STATUS_PRESENT)
    ]
    _print_entries(entries, shown)

    if clean:
        missing = [x for x in entries if x.status == STATUS_MISSING]
        if not missing:
            click.secho("Nothing to clean.")
        elif _confirm(
            config,
            f"Move {len(missing)} entries with status 'missing' to the trash?",
        ):
            target = move_to_trash(conf_dir, entries)
            click.secho(
                f"Moved {len(missing)} entries to {target}", fg="green"
            )

    if purge_days is not None:
        folders = trash_entries_older_than(conf_dir, purge_days)
        if not folders:
            click.secho(f"No trash folders older than {purge_days} days.")
        else:
            for folder in folders:
                click.secho(f"  {folder}")
            if _confirm(
                config,
                f"Delete {len(folders)} trash folders permanently?",
            ):
                failed = purge_trash(conf_dir, folders)
                if failed:
                    raise click.ClickException(
                        f"{len(failed)} trash folders could not be removed."
                    )
                click.secho(
                    f"Deleted {len(folders)} trash folders.", fg="green"
                )
