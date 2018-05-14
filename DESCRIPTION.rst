harmonize
=========

Create and synchronize transcoded copies of audio folders.

* Transcodes FLAC files to MP3 (LAME V0)
* Copies everything else as-is
* Parallelized
* Additional runs synchronize changes since the initial run


Installation
------------

Requires the following:

* Python 3.6+
* FFmpeg
* FLAC


Usage
-----

.. code:: shell

    $ harmonize -h
    usage: harmonize [-h] [-n NUM_PROCESSES] source target

    positional arguments:
      source            Source directory
      target            Target directory

    optional arguments:
      -h, --help        show this help message and exit
      -n NUM_PROCESSES  Number of processes to use


.. _PyPI: https://pypi.org/pypi/harmonize
.. _mp3fs: https://khenriks.github.io/mp3fs/
.. _rsync: https://rsync.samba.org/
