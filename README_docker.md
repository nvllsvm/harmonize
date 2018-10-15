Create and synchronize transcoded copies of audio folders.

* Transcodes FLAC files to MP3 with tags
* Copies everything else as-is
* Parallelized
* Additional runs synchronize changes since the initial run

# Environment Variables

- ``NUM_PROCESSES`` - Number of processes to transcode and copy with (default 1).

# Volumes

- ``/source`` - Source directory
- ``/target`` - Target directory

# Usage

You probably want to use the ``--user`` option to ensure the target files are
created with a specific UID and GID.

```
$ docker run \
    --user 1000:1000 \
    -e NUM_PROCESSES=8 \
    -v /media/flac:/source \
    -v /media/mp3:/target \
    nvllsvm/harmonize
```

