# photo-merge

This is a small Python script that merges photos from multiple sources into a single directory.

## Example

Alice and Bob were on vacation together. Alice took photos with her DSLR and Bob with his Smartphone:

```shell
$ tree /home/alice/spain_photos_raw
/home/alice/spain_photos_raw
├── Alice
│   ├── DSC_0001.JPG
│   ├── DSC_0002.JPG
│   └── ...
└── Bob
    ├── PXL_20260102_131502000.jpg
    ├── PXL_20260102_131503000.jpg
    └── ...

$ git clone https://github.com/felsenhower/photo-merge.git

$ cd photo-merge

$ uv run main.py \
    --source='/home/alice/spain_photos_raw' \
    --target='/home/alice/spain_photos_merged' \
    --mode=hardlink

$ tree /home/alice/spain_photos_merged
/home/alice/spain_photos_merged
├── 2026-01-02 13-15-01 (Alice, DSC_0001).JPG
├── 2026-01-02 13-15-02 (Bob, PXL_20260102_131502000).JPG
├── 2026-01-02 13-15-03 (Bob, PXL_20260102_131503000).JPG
├── 2026-01-02 13-15-05 (Alice, DSC_0002).JPG
└── ...
```

With the command above, the subdirectories of `~/spain_photos_raw` are inspected and the JPEGs therein are hard-linked to `~/spain_photos_merged`. You can also choose to copy or symlink the photos instead.

The datetimes that are used in the filenames are extracted from the EXIF data. By default, the datetimes are taken as-is. If you pass `--timezone=local`, your current timezone is used instead. If Alice has kept her camera's time to London time (`+01:00`), but Bob's smartphone automatically adjusted to Madrid time (`+02:00`), it makes sense to normalize the datetimes to Madrid time by passing `--timezone=Europe/Madrid`.

## Usage

```shell
usage: photo-merge [-h] --source SOURCE --target TARGET --mode {copy,symlink,hardlink} [--timezone {none, local, <tz>}] [--normalize-extension]

Merge multiple photo directories.

options:
  -h, --help            show this help message and exit
  --source SOURCE       Source directory to read from.
  --target TARGET       Target directory to write to.
  --mode {copy,symlink,hardlink}
                        How to create the photos in the merged directory.
  --timezone {none, local, <tz>}
                        Timezone to use for the merged pictures (none: don't normalize datetimes; local: use local time; <tz>: Use a specific timezone. Supported values for tz are IANA
                        timezone identifiers, e.g. 'Europe/Berlin', 'CET', or 'UTC', and ISO 8601 offsets, e.g. '+01:00').
  --normalize-extension
                        Normalize file extensions. E.g. for all 'image/jpeg' files, '.jpg' is used.
```

