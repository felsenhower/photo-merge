import argparse
import mimetypes
import re
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
    DRYRUN = "dryrun"


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


def regex(s: str) -> re.Pattern:
    return re.compile(s)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="photo-merge",
        description="Merge multiple photo directories.",
    )
    parser.register("type", "existing directory", existing_directory)
    parser.register("type", "mode", CreateMode)
    parser.register("type", "timezone", time_zone_mode)
    parser.register("type", "regex", regex)
    parser.add_argument(
        "--source",
        required=True,
        type="existing directory",
        metavar="DIR",
        help="Source directory to read from.",
    )
    parser.add_argument(
        "--target",
        required=True,
        type="existing directory",
        metavar="DIR",
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
    parser.add_argument(
        "--exiftool",
        action="store_true",
        help="Use exiftool backend instead (requires installing exiftool and running this script with '--extra exiftool').",
    )
    parser.add_argument(
        "--name-format",
        type=str,
        metavar="FORMAT_STR",
        default="{date} {time} ({subdir}, {source_filename})",
        help="Format string for target filenames. Default: '{date} {time} ({subdir}, {source_filename})'. Allowed keys are 'date' (ISO date), 'time' (ISO time), 'subdir' (the parent directory of the source file), 'source_filename' (the original filename of the source file, without extension), 'num' (a running number of the image).",
    )
    parser.add_argument(
        "--ignore-existing",
        action="store_true",
        help="Skip existing files in target directory (default: exit with error).",
    )
    parser.add_argument(
        "--match-path",
        type="regex",
        metavar="REGEX",
        help="Only consider files where '<subdir>/<filename>' matches REGEX.",
    )
    args = parser.parse_args()
    return args


def list_subdirs(p: Path) -> None:
    print("Found subdirectories:")
    for subdir in sorted(list(p.iterdir())):
        print(f'  "{subdir.name}"')


def read_image_datetime_exif_default(p: Path) -> (str | None, str | None):
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
            return (None, None)
        if not img.has_exif:
            return (None, None)
        exif_datetime = img.get("datetime")
        exif_offset = img.get("offset_time")
        return (exif_datetime, exif_offset)


def read_image_datetime_exif_exiftool(p: Path) -> (str | None, str | None):
    import exiftool

    with exiftool.ExifToolHelper() as et:
        metadata = et.get_metadata(p)[0]
        if "EXIF:CreateDate" in metadata:
            exif_datetime = metadata["EXIF:CreateDate"]
            exif_offset = metadata.get("EXIF:OffsetTime", None)
            return (exif_datetime, exif_offset)
        if "QuickTime:MediaCreateDate" in metadata:
            exif_datetime = metadata["QuickTime:MediaCreateDate"]
            exif_offset = "+00:00"
            return (exif_datetime, exif_offset)
        return (None, None)


def read_image_datetime(p: Path, use_exiftool: bool) -> datetime | None:
    assert p.exists()
    if use_exiftool:
        exif_datetime, exif_offset = read_image_datetime_exif_exiftool(p)
    else:
        exif_datetime, exif_offset = read_image_datetime_exif_default(p)
    if exif_datetime is None or exif_offset is None:
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
    name_format: str,
    num: int,
) -> Path:
    target_datetime = normalize_datetime(image_datetime, tz_mode)
    name_components = {
        "date": target_datetime.strftime("%Y-%m-%d"),
        "time": target_datetime.strftime("%H-%M-%S"),
        "subdir": source_filename.parent.name,
        "source_filename": source_filename.stem,
        "num": num,
    }
    stem = name_format.format(**name_components)
    suffix = source_filename.suffix
    if do_normalize_extension:
        suffix = get_normalized_extension(source_filename) or suffix
    return target_dir / f"{stem}{suffix}"


def create_target_file(
    source_file: Path, target_file: Path, mode: CreateMode, ignore_existing: bool
) -> None:
    print(f'"{source_file.name}" -> "{target_file.name}"')
    if mode == CreateMode.DRYRUN:
        return
    if target_file.exists():
        if ignore_existing:
            return
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
    use_exiftool: bool,
    name_format: str,
    ignore_existing: bool,
    match_path: re.Pattern | None,
) -> None:
    for subdir in sorted(list(source_dir.iterdir())):
        print(f'Entering "{subdir.name}"...')
        for num, img_filename in enumerate(sorted(list(subdir.iterdir()))):
            if match_path is not None:
                if not match_path.match(str(img_filename.relative_to(source_dir))):
                    print(f'Skipping "{img_filename}"')
                    continue
            image_datetime = read_image_datetime(img_filename, use_exiftool)
            if image_datetime is None:
                continue
            target_path = make_target_path(
                img_filename,
                image_datetime,
                tz_mode,
                target_dir,
                do_normalize_extension,
                name_format,
                num,
            )
            create_target_file(img_filename, target_path, mode, ignore_existing)


def main() -> None:
    args = parse_args()
    mimetypes.init()
    print(f'Reading from "{args.source}"')
    list_subdirs(args.source)
    merge_photos(
        args.source,
        args.target,
        args.mode,
        args.timezone,
        args.normalize_extension,
        args.exiftool,
        args.name_format,
        args.ignore_existing,
        args.match_path,
    )


if __name__ == "__main__":
    main()
