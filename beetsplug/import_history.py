"""Adds a `source_path` attribute to imported albums indicating from what path
the album was imported from. Also suggests removing that source path in case
you've removed the album from the library.

"""

import re
import os
from shutil import rmtree

from beets.plugins import BeetsPlugin
from beets.ui import input_yn, input_options
from beets.ui import colorize as colorize_text

class ImportHistPlugin(BeetsPlugin):
    """Main plugin class."""

    def __init__(self):
        """Initialize the plugin and read configuration."""
        super(ImportHistPlugin, self).__init__()
        self.config.add({
            'auto': True,
        })
        if self.config['auto']:
            self.import_stages = [self.import_stage]
            self.register_listener('item_removed', self.suggest_removal)
        # In order to stop suggestions for certain albums in
        # self.suggest_removal, we initialize an empty list of mb_albumids that
        # these will be ignored in future runs
        self.stop_suggestions_for_albums = []

    def import_stage(self, _, task):
        """Event handler for albums import finished."""
        # first, we sort the items using a dictionary and a list of paths for every mbid
        for item in task.imported_items():
            item['source_path'] = item.path
            item.try_sync(write=True, move=False)

    def suggest_removal(self, item):
        """Prompts the user to delete the original path the item was imported from."""
        if not item['source_path'] or item.mb_albumid in self.stop_suggestions_for_albums:
            return
        if os.path.isdir(item['source_path']):
            # We ask the user whether they'd like to delete the item's source directory
            delete = input_yn(
                "The item:\n{path}\nis originated in the directory:\n{source}\n"
                "Would you like to delete the source directory of this item?".format(
                    path=colorize_text("text_warning", item.path.decode('utf-8')),
                    source=colorize_text("text_warning", item['source_path'].decode('utf-8'))
                ),
                require=True)
            if delete:
                self._log.info("Deleting the item's source which is a directory: %s",
                               item['source_path'])
                rmtree(item['source_path'])
        elif os.path.isfile(item['source_path']):
            # We ask the user whether they'd like to delete the item's source directory
            print("The item:\n{path}\nis originated in from:\n{source}\n"
                  "What would you like to do?".format(
                      path=colorize_text("text_warning", item.path.decode('utf-8')),
                      source=colorize_text("text_warning", item['source_path'].decode('utf-8')))
                  )
            resp = input_options(
                [
                    "Delete the item's source",
                    "Recursively delete the source's directory",
                    "do Nothing",
                    "do nothing and Stop suggesting to delete items from this album"
                ],
                require=True,
            )
            if resp == 'd':
                self._log.info("Deleting the item's source file: %s", item['source_path'])
                os.remove(item['source_path'])
            elif resp == 'r':
                source_dir = os.path.dirname(item['source_path'])
                self._log.info("Searching for other items with a source_path attr containing: %s",
                               source_dir)
                # NOTE: I'm not sure why, but we need to escape it twice otherwise the search fails
                escaped_source_dir = re.escape(re.escape(
                    source_dir.decode("utf-8")
                ))
                source_dir_query = "source_path::^{}/*".format(escaped_source_dir)
                print("Doing so will delete the following items' sources as well:")
                for searched_item in item._db.items(source_dir_query):
                    print(colorize_text("text_warning", searched_item['path'].decode('utf-8')))
                print("Would you like to continue?")
                continue_resp = input_options(
                    [
                        "Yes",
                        "delete None",
                        "delete just the File"
                    ],
                    require=False, # Yes is the a default
                )
                if continue_resp == 'y':
                    self._log.info("Deleting the item's source directory: %s", source_dir)
                    rmtree(source_dir)
                elif continue_resp == 'n':
                    self._log.info("doing nothing - aborting hook function")
                    return
                elif continue_resp == 'f':
                    self._log.info("removing just the item's original source: %s",
                                   item['source_path'])
                    os.remove(item['source_path'])
            elif resp == 's':
                self.stop_suggestions_for_albums.append(item.mb_albumid)
            else:
                self._log.info("Doing nothing")
