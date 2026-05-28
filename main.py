import argparse
import mimetypes
import shutil
from datetime import datetime, tzinfo
from enum import StrEnum
from pathlib import Path
from typing import Union
from zoneinfo import ZoneInfo

import exif
from plum.exceptions import (
    ExcessMemoryError,
    InsufficientMemoryError,
    PackError,
    SizeError,
    UnpackError,
)


class CreateMode(StrEnum):
    COPY = "copy"
    SYMLINK = "symlink"
    HARDLINK = "hardlink"


class TimeZoneModeBasic(StrEnum):
    NONE = "none"
    LOCAL = "local"


TimeZoneMode = Union[TimeZoneModeBasic, tzinfo]


def existing_directory(s: str) -> Path:
    p = Path(s)
    if not p.exists():
        raise ValueError(f'Path "{s}" does not exist.')
    if not p.is_dir():
        raise ValueError(f'Path "{s}" is not a directory.')
    return p


def time_zone_mode(s: str) -> TimeZoneMode:
    if s in TimeZoneModeBasic:
        return TimeZoneModeBasic(s)
    try:
        return ZoneInfo(s)
    except Exception:
        pass
    try:
        offset = datetime.fromisoformat(f"1970-01-01T00:00:00{s}").tzinfo
        if offset is not None:
            return offset
    except Exception:
        pass
    raise ValueError(f'Invalid timezone specifier "{s}".')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="photo-merge", description="Merge multiple photo directories."
    )
    parser.register("type", "existing directory", existing_directory)
    parser.register("type", "mode", CreateMode)
    parser.register("type", "timezone", time_zone_mode)
    parser.add_argument(
        "--source",
        required=True,
        type="existing directory",
        help="Source directory to read from.",
    )
    parser.add_argument(
        "--target",
        required=True,
        type="existing directory",
        help="Target directory to write to.",
    )
    parser.add_argument(
        "--mode",
        required=True,
        type="mode",
        choices=[str(c) for c in CreateMode],
        help="How to create the photos in the merged directory.",
    )
    parser.add_argument(
        "--timezone",
        type="timezone",
        metavar="{none, local, <tz>}",
        default="none",
        help="Timezone to use for the merged pictures (none: don't normalize datetimes; local: use local time; <tz>: Use a specific timezone. Supported values for tz are IANA timezone identifiers, e.g. 'Europe/Berlin', 'CET', or 'UTC', and ISO 8601 offsets, e.g. '+01:00').",
    )
    parser.add_argument(
        "--normalize-extension",
        action="store_true",
        help="Normalize file extensions. E.g. for all 'image/jpeg' files, '.jpg' is used.",
    )
    args = parser.parse_args()
    return args


def list_subdirs(p: Path) -> None:
    print("Found subdirectories:")
    for subdir in sorted(list(p.iterdir())):
        print(f'  "{subdir.name}"')


def read_image_datetime(p: Path) -> datetime | None:
    assert p.exists()
    with p.open("rb") as f:
        try:
            img = exif.Image(f)
        except (
            ValueError,
            ExcessMemoryError,
            InsufficientMemoryError,
            PackError,
            SizeError,
            UnpackError,
        ):
            return None
        if not img.has_exif:
            return None
        exif_datetime = img.get("datetime")
        if exif_datetime is None:
            return None
        exif_offset = img.get("offset_time")
        if exif_offset is None:
            return None
        d = datetime.strptime(
            f"{exif_datetime} {exif_offset}", f"{exif.DATETIME_STR_FORMAT} %z"
        )
        return d


def normalize_datetime(d: datetime, tz_mode: TimeZoneMode) -> datetime:
    match tz_mode:
        case TimeZoneModeBasic.NONE:
            return d
        case TimeZoneModeBasic.LOCAL:
            return d.astimezone()
        case tz:
            return d.astimezone(tz)


def get_normalized_extension(p: Path) -> str | None:
    mimetype, _encoding = mimetypes.guess_file_type(p, strict=True)
    if mimetype is None:
        return None
    suffix = mimetypes.guess_extension(mimetype)
    return suffix


def make_target_path(
    source_filename: Path,
    image_datetime: datetime,
    tz_mode: TimeZoneMode,
    target_dir: Path,
    do_normalize_extension: bool,
) -> Path:
    target_datetime = normalize_datetime(image_datetime, tz_mode)
    datetime_str = target_datetime.strftime("%Y-%m-%d %H-%M-%S")
    suffix = source_filename.suffix
    if do_normalize_extension:
        suffix = get_normalized_extension(source_filename) or suffix
    stem = f"{datetime_str} ({source_filename.parent.name}, {source_filename.stem})"
    return target_dir / f"{stem}{suffix}"


def create_target_file(source_file: Path, target_file: Path, mode: CreateMode) -> None:
    print(f'"{source_file.name}" -> "{target_file.name}"')
    if target_file.exists():
        raise FileExistsError(f'Target file "{target_file}" exists.')
    match mode:
        case CreateMode.COPY:
            shutil.copy(source_file, target_file)
        case CreateMode.HARDLINK:
            target_file.hardlink_to(source_file)
        case CreateMode.SYMLINK:
            target_file.symlink_to(source_file)


def merge_photos(
    source_dir: Path,
    target_dir: Path,
    mode: CreateMode,
    tz_mode: TimeZoneMode,
    do_normalize_extension: bool,
) -> None:
    for subdir in sorted(list(source_dir.iterdir())):
        print(f'Entering "{subdir.name}"...')
        for img_filename in sorted(list(subdir.iterdir())):
            image_datetime = read_image_datetime(img_filename)
            if image_datetime is None:
                continue
            target_path = make_target_path(
                img_filename,
                image_datetime,
                tz_mode,
                target_dir,
                do_normalize_extension,
            )
            create_target_file(img_filename, target_path, mode)


def main() -> None:
    args = parse_args()
    mimetypes.init()
    print(f'Reading from "{args.source}"')
    list_subdirs(args.source)
    merge_photos(
        args.source, args.target, args.mode, args.timezone, args.normalize_extension
    )


if __name__ == "__main__":
    main()
