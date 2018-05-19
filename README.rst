harmonize
=========

|PyPI Version|

Create and synchronize transcoded copies of audio folders.

* Transcodes FLAC files to MP3 with tags
* Copies everything else as-is
* Parallelized
* Additional runs synchronize changes since the initial run


History
-------
My audio library is a comprised of FLAC's, MP3's, cover images, and various
metadata files - totaling roughly 500GB. This is not a problem when I'm on my
desktop - wired into the same network as my server. However, my laptop and
phone use often suffers from poor connectivity and limit storage capacities.
Further, lossless audio often is a waste as the my laptop and phone used in
less-than-ideal environments and equipment. Thus, I decided to use only MP3's
on those devices.

Previously, I was solving this with a combination of mp3fs_ and rsync_. This
served me well for a number of years, but had a few drawbacks for my uses.

* **Only MP3** - Cannot experiment with formats like Opus without implementing
  support in mp3fs's C codebase.
* **Only CBR MP3** - LAME's V0 often is indistinguishable from 320 CBR while
  reducing the file size by ~15%.
* **Uses FUSE** - Makes containerization and portability more complicated.
* **Not Parallelized** - On a system with eight logical cores and competent
  disk speeds, encoding a one file at a time is a gross inefficiency.

Harmonize transcodes to LAME V0, has no dependency on FUSE, and supports
parallel copying and transcoding. While it currently only transcodes to MP3,
it's written in Python. This is far more accessible to modification for a 
Pythonista like myself.


Installation
------------

* `Arch Linux`_
* `Docker`_
* `PyPI`_

If installing from `PyPI`_ or using the script directly, ensure the following
are installed:

* Python 3.6+
* FFmpeg
* FLAC


Usage
-----

.. code::

    $ harmonize -h
    usage: harmonize [-h] [-n NUM_PROCESSES] source target

    positional arguments:
      source            Source directory
      target            Target directory

    optional arguments:
      -h, --help        show this help message and exit
      -n NUM_PROCESSES  Number of processes to use


.. |PyPI Version| image:: https://img.shields.io/pypi/v/harmonize.svg?
   :target: https://pypi.org/pypi/harmonize
.. _PyPI: https://pypi.org/pypi/harmonize
.. _Arch Linux: https://aur.archlinux.org/packages/harmonize/
.. _Docker: https://hub.docker.com/r/nvllsvm/harmonize/
.. _mp3fs: https://khenriks.github.io/mp3fs/
.. _rsync: https://rsync.samba.org/
