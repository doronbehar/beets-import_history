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
import re
import os
from shutil import rmtree

from beets.plugins import BeetsPlugin
from beets.ui import Subcommand
from beets import config
from beets.ui import input_yn
from beets.ui import colorize as colorize_text

CMD_USAGE = """beet importhist [options] sub-command

Sub-commands:
{subcommands}
"""

class ImportHistDatabase:
    """Database abstraction layer class."""

    def __init__(self, db_path, logger):
        """Initialize database within self."""
        self._log = logger
        self.db_path = db_path
        connection = sqlite3.connect(self.db_path)
        with connection:
            try:
                connection.execute('SELECT * FROM imports_history')
            except sqlite3.OperationalError:
                connection.execute('CREATE TABLE imports_history ('
                                   'origin_path text, '
                                   'mb_albumid text PRIMARY KEY'
                                   ')')

    def insert_album(self, origin_path, mb_albumid):
        """Insert an album to the db according to parameters of function."""
        connection = sqlite3.connect(self.db_path)
        with connection:
            return connection.execute('INSERT OR REPLACE INTO imports_history VALUES (?, ?)',
                                      (origin_path, mb_albumid)).fetchall()

    def remove_album(self, mbid):
        """Removes an album from the history database according to given mbid."""
        connection = sqlite3.connect(self.db_path)
        with connection:
            return connection.execute('DELETE FROM imports_history WHERE mb_albumid=?',
                                      (mbid, )).fetchall()

    def list(self):
        """List all entries in the database."""
        connection = sqlite3.connect(self.db_path)
        with connection:
            return connection.execute('SELECT * FROM imports_history').fetchall()

    def was_album_recorded(self, mbid):
        """Returns a path the given mbid was associated with it."""
        connection = sqlite3.connect(self.db_path)
        with connection:
            paths = connection.execute('SELECT origin_path FROM imports_history WHERE mb_albumid=?',
                                       (mbid, )).fetchall()
            if paths:
                # Since our database has unique keys and values in each pair,
                # We can return the first parts of the list and be sure these
                # are the only ones
                return paths[0][0]
            # We return none if none were found
            return None


class ImportHistPlugin(BeetsPlugin):
    """Main plugin class."""

    def __init__(self):
        """Initialize the plugin and read configuration."""
        super(ImportHistPlugin, self).__init__()
        self.config.add({
            'auto': True,
            'database': config.config_dir() + "/importhist.db",
            'torrent_dir': "/var/lib/transmission/downloads/music"
        })
        self._log.debug("database: {}", self.config['database'])
        try:
            self.database = ImportHistDatabase(str(self.config['database']),
                                               self._log)
        except sqlite3.OperationalError:
            self._log.error("Could not open/create database file")
            self.config.set({
                'auto': False
            })
            sys.exit(2)
        if self.config['auto']:
            self.register_listener('item_removed', self.suggest_removal)
            self.import_stages = [self.import_stage]
            # TODO: add an event listener for item's metadata updates, which will update the
            # history database if needed
        self.cmd = Subcommand('importhist', help="manage import history")

    def commands(self):
        """Define the commands of the plugin."""
        subcommands_usage = ""
        subcommands_line_format = "{:<12} {help_line}"
        for attr in dir(self):
            if re.match(r'^cmd_', attr):
                subcommand_help = getattr(self, attr).__doc__
                subcommand_name = re.sub(r'cmd_', "  ", attr)
                subcommands_usage += subcommands_line_format.format(
                    subcommand_name,
                    help_line=subcommand_help
                ) + "\n"
        self.cmd.parser.usage = CMD_USAGE.format(subcommands=subcommands_usage)
        self.cmd.func = self.arguments_handler
        return [self.cmd]

    def arguments_handler(self, lib, opts, args):
        """Handles arguments as sub-sub commands of the main beets command."""
        try:
            return getattr(self, 'cmd_' + args[0])(args[1:], opts, lib)
        except AttributeError:
            self._log.error("no such command: %s" % args[0])
            sys.exit(2)
        except IndexError:
            self._log.error("please provide a subcommand")
            return self.cmd.print_help()

    def cmd_list(self, _, __, ___):
        """List all imports recorded in history database"""
        # Format it as a table so we print the headers and the data in a formatted manner
        row_format = "{:<37} {}"
        print(row_format.format("MusicBrainz Album ID", "Origin Path"))
        for row in self.database.list():
            print(row_format.format(row[1], row[0].decode('utf-8')))

    def cmd_add(self, args, _, lib):
        """Add an import record for a given mb_albumid and origin path to the history database"""
        if not args:
            self._log.error("Usage: add <album-id> <path>")
            return 3
        if len(args) > 2:
            self._log.warn("only the first 2 arguments will be handled")
        path_arg = pathlib.Path(args[1])
        if not path_arg.is_dir():
            self._log.error("%s is not a directory, aborting" % path_arg)
            return 1
        album_arg = args[0]
        existing_albums = lib.albums("mb_albumid:{}".format(album_arg))
        if existing_albums:
            self._log.error("no such album was found in the library")
            return 1
        if len(existing_albums) > 1:
            self._log.error("Impossible! There is more then 1 album with a musicbrainz albumid of "
                            "%s", album_arg)
            return 70
        self.database.insert_album(str(path_arg.resolve()), album_arg)
        return 0

    def cmd_delete(self, args, _, lib):
        """Delete an import record from the history database"""
        if not args:
            self._log.error("Usage: delete <album-id>")
            return 3
        if len(args) > 1:
            self._log.warn("only the first argument will be handled")
        existing_albums = lib.albums("mb_albumid:{}".format(args[0]))
        if existing_albums:
            self._log.error("no such album was found in the library")
            return 1
        if len(existing_albums) > 1:
            self._log.error("Impossible! There is more then 1 album with a musicbrainz albumid of "
                            "%s", args[0])
            return 70
        return self.database.remove_album(args[0])

    # Hooks functions

    def import_stage(self, _, task):
        """Event handler for albums import finished."""
        # first, we sort the items using a dictionary and a list of paths for every mbid
        items_sorted = {}
        for item in task.items:
            if item.mb_albumid not in items_sorted:
                items_sorted[item.mb_albumid] = []
            items_sorted[item.mb_albumid].append(item.path)
        # now, we build a dictionary of every mbid and the common prefix of the paths from the list
        # in items_sorted
        remote_path_ids = {}
        for mbid, paths in items_sorted.items():
            remote_path_ids[mbid] = os.path.commonprefix(paths)
        for mbid, common_path in remote_path_ids.items():
            self.database.insert_album(common_path, mbid)
        return 0

    def suggest_removal(self, item):
        """Prompts the user to delete the original path the item was imported from."""
        # We check whether the item has an entry in the database according to it's mb_albumid
        history_path = self.database.was_album_recorded(item.mb_albumid)
        if history_path and os.path.isdir(history_path):
            # First we ask the user whether they'd like to remove the album from the history
            # database
            delete = input_yn("The directory:\n{}\nis the origin of the path of:\n{}\nWould you "
                              "like to delete the source directory of this item?".format(
                                  colorize_text("text_warning", history_path.decode('utf-8')),
                                  colorize_text("text_warning", item.path.decode('utf-8'))
                              ), require=True)
            if delete:
                rmtree(history_path)
        # We clean our database anyway since that item is not in the library anymore
        self.database.remove_album(item.mb_albumid)
