"""
8kun Search via Sphinx
"""
from datasources.fourchan.search_4chan import Search4Chan

from common.lib.helpers import UserInput


class Search8Kun(Search4Chan):
    """
    Search 8kun corpus

    Defines methods that are used to query the 8kun data indexed and saved.

    Apart from the prefixes, this works identically to the 4chan searcher, so
    most methods are inherited from there.
    """
    type = "eightkun-search"
    sphinx_index = "8kun"
    title = "8kun search"
    prefix = "8kun"
    is_local = True  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    config = {
        "eightkun-search.autoscrape": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Enable collecting",
            "tooltip": "Toggle to automatically collect new boards and threads",
            "global": True
        },
        "eightkun-search.boards": {
            "type": UserInput.OPTION_TEXT_JSON,
            "help": "Boards to index",
            "tooltip": "These boards will be scraped and made available for searching. Provide as a JSON-formatted "
                       "list of strings, e.g. [\"pol\", \"v\"].",
            "default": [""],
            "global": True
        },
        "eightkun-search.interval": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": int,
            "help": "Scrape interval",
            "tooltip": "Scrape new threads every this many seconds",
            "default": 60,
            "global": True
        },
        "eightkun-search.no_scrape": {
            "type": UserInput.OPTION_TEXT_JSON,
            "help": "Boards not to scrape",
            "tooltip": "These boards will not be scraped, but can still be indexed if added to 'Boards to index'",
            "default": [],
            "global": True
        }
    }

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        return {
            "intro": {
                "type": UserInput.OPTION_INFO,
                "help": "Results are limited to 5 million items maximum. Be sure to read the [query "
                        "syntax](/page/query-syntax/) for local data sources first - your query design will "
                        "significantly impact the results. Note that large queries can take a long time to complete!\n\n"
                        "[8kun](https://8kun.top) is an image board that serves as a successor to 8chan. While it is "
                        "virtually identical, it has a different owner and does not incorporate all of 8chan's board, in "
                        "addition to offering new ones that did not exist on 8chan."
            },
            "board": {
                "type": UserInput.OPTION_CHOICE,
                "options": {b: b for b in config.get("eightkun-search.boards", [])},
                "help": "Board",
                "default": config.get("eightkun-search.boards", [""])[0]
            },
            "body_match": {
                "type": UserInput.OPTION_TEXT,
                "help": "Post contains"
            },
            "subject_match": {
                "type": UserInput.OPTION_TEXT,
                "help": "Subject contains"
            },
            "divider": {
                "type": UserInput.OPTION_DIVIDER
            },
            "daterange": {
                "type": UserInput.OPTION_DATERANGE,
                "help": "Date range"
            },
            "search_scope": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Search scope",
                "options": {
                    "posts-only": "All matching messages",
                    "full-threads": "All messages in threads with matching messages (full threads)",
                    "dense-threads": "All messages in threads in which at least x% of messages match (dense threads)"
                },
                "default": "posts-only"
            },
            "scope_density": {
                "type": UserInput.OPTION_TEXT,
                "help": "Min. density %",
                "min": 0,
                "max": 100,
                "default": 15,
                "tooltip": "At least this many % of messages in the thread must match the query"
            },
            "scope_length": {
                "type": UserInput.OPTION_TEXT,
                "help": "Min. dense thread length",
                "min": 30,
                "default": 30,
                "tooltip": "A thread must at least be this many messages long to qualify as a 'dense thread'"
            }
        }
