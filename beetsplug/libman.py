"""Personal beets plugin that manages imports from torrent directories.

This plugin does several jobs:
- Follow what torrents have been imported and what is their contiribution to
  the library.
- Suggest optimization to the library according to stats from my account on
  libre.fm and the playlists.
"""

# from glob import iglob, glob
import sqlite3
import pathlib
import sys

from beets.plugins import BeetsPlugin
from beets.ui import Subcommand
from beets import config
from beets import util


class LibmanDatabase:
    """Database abstraction layer class."""

    def __init__(self, db_path, logger):
        """Initialize database within self."""
        self._log = logger
        self.connection = sqlite3.connect(db_path)
        self.cursor = self.connection.cursor()
        self.ex = self.cursor.execute
        try:
            self.ex('SELECT * FROM imports_history')
        except sqlite3.OperationalError:
            self.ex('CREATE TABLE imports_history ('
                    'origin_path text'
                    'mb_albumid text'
                    ')')

    def insert_album(self, origin_path, mb_albumid):
        """Insert an album to the db according to parameters of function."""
        self.ex('INSERT INTO imports_history values (?, ?)', origin_path,
                mb_albumid)
        return self.cursor.fetchall()

    def search_import(self, origin_path):
        """Search for an album according to either mb_albumid or mb_albumid."""
        self.ex('SELECT * FROM imports_history WHERE origin_path=?',
                origin_path)
        return self.cursor.fetchall()

    def list(self):
        """List all entries in the database."""
        self.ex('SELECT * FROM imports_history')
        imports = self.cursor.fetchall()
        return imports


class LibmanPlugin(BeetsPlugin):
    """Main plugin class."""

    def __init__(self):
        """Initialize the plugin and read configuration."""
        super(LibmanPlugin, self).__init__()
        self.config.add({
            'auto': True,
            'database': config.config_dir() + "/libman.db",
            'torrent_dir': "/var/lib/transmission/downloads/music"
        })
        for conf in (self.config, config['smartplaylist']):
            try:
                playlist_dir = conf['playlist_dir']
                playlist_dir.as_filename()
                self.playlist_dir = str(playlist_dir)
                self._log.debug("playlist dir: {}", self.playlist_dir)
                break
            except util.confit.NotFoundError:
                pass
        else:
            self._log.warning("no playlist_dir was configured so no import "
                              "hooks will be used")
        self._log.debug("database: {}", self.config['database'])
        try:
            self.database = LibmanDatabase(str(self.config['database']),
                                           self._log)
        except sqlite3.OperationalError:
            self._log.error("Could not open/create database file")
            self.config.set({
                'auto': False
            })
        if self.config['auto'] and hasattr(self, 'database'):
            # TODO: register deletion events as well
            self.register_listener('import', self.mark_torrent_dir)
            self.register_listener('item_moved', self.handle_moved_files)

    def commands(self):
        """Define the commands of the plugin."""
        optimize = Subcommand('optimize', help="library optimizer")
        optimize.parser.add_option('-p', '--pretend', action='store_true',
                                   help=u'show actions but do nothing')
        optimize.func = self.optimize
        libman = Subcommand('libman', help="library manager")
        libman.parser.add_option('-p', '--pretend', action='store_true',
                                 help=u'show actions but do nothing')
        libman.parser.add_option('--album', '-a',
                                 help='musicbrainz-albumid or album-path that '
                                 'will be used in the database')
        libman.parser.add_option('--list', '-l', action='store_true',
                                 help='list imports from the past with the '
                                 'corresponding paths')
        libman.func = self.main
        return [libman, optimize]

    def mark_torrent_dir(self, lib, paths):
        """Mark torrent as imported with correspondence to a specific album."""
        self._log.info("marking torrent directory %s as imported", paths)
        # TODO: write to libman.db the album that was added in correspondence
        # to the original directory that was imported
        print(self)
        print(lib)
        print(paths)

    def handle_moved_files(self, item, source, destination):
        """Handle files changing name or location in `libman.db`."""
        # TODO: for every item moved, check if the source and destination
        # parent folders were changed and if so, update libman.db
        print(self)
        print(item)
        print(source)
        print(destination)

    def _get_album(self, lib, suggestion=""):
        # TODO: launch fzf with suggestion in the initial --query
        return suggestion

    def main(self, lib, opts, args):
        """Command line interface function."""
        if opts.list:
            if not hasattr(self, 'database'):
                self._log.error("Can't read imports history for listing")
                sys.exit(1)
            self._log.info("listing all past imports")
            print(self.database.list())
            return 0
        return self.simulate(lib, opts, args)

    def _handle_album_opt(self, lib, album):
        """Handle --album= as either mb_albumid or path (relative/absolute)."""
        album = pathlib.Path(album)
        if album.exists():
            musicdir = pathlib.Path(str(config['directory']))
            if album.is_absolute():
                self._log.info("treating %s as a directory in the music "
                               "library" % album)
                if not musicdir.match(str(album)):
                    self._log.error("%s wasn't found in music library" % album)
                    sys.exit(1)
            else:
                album = musicdir.joinpath(album)
            # FIXME: why does it return an empty list??
            library_matching_albums = lib.albums(
                query="path:%s" % str(album)
            )
            if not library_matching_albums:
                self._log.error("'%s' wasn't found in the library although it "
                                "seems to exist in the music directory" %
                                album)
                sys.exit(1)
            #album = library_matching_albums.albumid
        else:
            album = str(album)
            self._log.info("treating %s as a musicbrainz-albumid" % album)
            library_matching_albums = lib.albums(
                query="mb_albumid:%s" % album
            )
            # FIXME: why does it return an empty list??
            if not library_matching_albums:
                self._log.error("'%s' wasn't found in the library" % album)
                sys.exit(1)
            #album = library_matching_albums.albumid
        return album

    def simulate(self, lib, opts, args):
        """Simulate an import for given arguments."""
        if len(args) > 1:
            self._log.warning("warning: only 1st argument will be processed")
        self._log.info("simulating import of %s" % args[0])
        arg = pathlib.Path(args[0])
        if not arg.is_dir():
            self._log.error("%s is not a directory, aborting" % arg)
            sys.exit(1)
        arg = arg.resolve()
        # NOW `arg` must be an absolute path
        if not opts.album:
            try:
                album = self._get_album(lib, suggestion=arg)
            except FileNotFoundError:
                self._log.warn("fzf was not found in your $PATH and "
                               "--album was not specified for per this "
                               "argument so it will be skipped")
                sys.exit(1)
            self._log.info("treating %s as a musicbrainz album id" % album)
        else:
            album = self._handle_album_opt(lib, album)
        # NOW album must be an album's musicbrainz id
        if self.database.search_import(arg):
            print("%s seems to be already marked in history" % arg)
            return 0
        self.database.insert_album(arg, album)
        return 0

    def optimize(self, lib, opts, args):
        """Optimize downloads directory / music library / playlists."""
        self._log.info("optimizing %s", args[0])
        print(lib)
        print(opts)
        print(args)
