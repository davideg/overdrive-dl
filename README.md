# overdrive-dl
Command-line tool to download audiobooks from OverDrive

Download an OverDrive file (.odm) from your library (e.g. `book.odm`) and then call `python3 overdrive-dl.py book.odm` to download that book as mp3s.

Includes functionality for updating ID3 tags, changing the owner and group of the files (assuming a Unix-based OS), and printing the metadata from an ODM file without downloading anything.

You can specify a config file in [TOML](https://github.com/toml-lang/toml) format to set a download location, whether to make filenames lowercase, how you would like to update the ID3 tags, and what user and group ownership you would like set for the downloaded files. Check out the `config.toml.example` file as an example.

Requires:
- [Python 3](https://docs.python.org/3/)
- [Requests](http://docs.python-requests.org)
- [Mutagen](https://mutagen.readthedocs.io)


```
python3 overdrive-dl.py --help
usage: overdrive-dl [-h] [-d] [-t] [-o] [-s] [-f] [-c CONFIG] [-m] filename

positional arguments:
  filename

optional arguments:
  -h, --help            show this help message and exit
  -d, --debug           print debug messages
  -t, --tags            Update ID3 tags according to configuration
  -o, --owner           Update file owner according to configuration
  -s, --skip-download   Skip downloading files. This option is only valid when
                        updating tags or owner, in which case it is assumed
                        the expected files already exist
  -f, --force           Ignore whether audiobook files already exist and
                        download all files, replacing any existing files
  -c CONFIG, --config CONFIG
                        Specify configuration file in TOML format (see
                        https://github.com/toml-lang/toml). Without specifying
                        this flag, overdrive-dl will look for file named
                        config.toml to read configuration
  -m, --print-metadata  Print metadata from specified ODM file and exit
  ```

Wrote this to scratch my own itch. Inspired in parts by https://github.com/chbrown/overdrive and https://github.com/jvolkening/gloc
