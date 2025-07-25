"""
Generate network of values from two columns
"""
from dateutil.relativedelta import relativedelta

from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput, get_interval_descriptor

import networkx as nx
import datetime

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class ColumnNetworker(BasicProcessor):
    """
    Generate network of values from two columns
    """
    type = "column-network"
    category = "Networks"
    title = "Custom network"
    description = "Create a GEXF network file comprised of linked values between a custom set of columns " \
                  "(e.g. 'author' and 'subreddit'). Nodes and edges are weighted by frequency."
    extension = "gexf"

    options = {
        "column-a": {
            "type": UserInput.OPTION_TEXT,
            "help": "Attribute A"
        },
        "column-b": {
            "type": UserInput.OPTION_TEXT,
            "help": "Attribute B"
        },
        "interval": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Make network dynamic by",
            "default": "overall",
            "options": {
                "overall": "Do not make dynamic",
                "year": "Year",
                "month": "Month",
                "week": "Week",
                "day": "Day"
            },
            "tooltip": "Dynamic networks will record in which interval(s) nodes and edges were present. "
                       "Weights will also be calculated per interval. Dynamic graphs can be opened in e.g. Gephi to "
                       "visually analyse the evolution of the network over time."
        },
        "directed": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Directed edges?",
            "default": True,
            "tooltip": "If enabled, e.g. an edge from 'hello' in column 1 to 'world' in column 2 creates a different edge "
                       "than from 'world' in column 1 to 'hello' in column 2. If disabled, these would be considered "
                       "the same edge."
        },
        "allow-loops": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Allow loops?",
            "default": False,
            "tooltip": "If enabled, a looping edge (from a node to itself) is created if the two columns contain the same value."
        },
        "split-comma": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Split column values by comma?",
            "default": False,
            "tooltip": "If enabled, values separated by commas are considered separate nodes, and create separate "
                       "edges. Useful if columns contain e.g. lists of hashtags."
        },
        "categorise": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Categorize nodes by column?",
            "default": True,
            "tooltip": "If enabled, the same values from different columns are treated as separate nodes. For "
                       "example, the value 'hello' from the column 'user' is treated as a different node than the "
                       "value 'hello' from the column 'subject'. If disabled, they would be considered a single node."
        },
        "to-lowercase": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Convert values to lowercase",
            "tooltip": "Merges values with varying cases"
        },
        "ignore-nodes": {
            "type": UserInput.OPTION_TEXT,
            "default": "",
            "help": "Nodes to ignore",
            "tooltip": "Separate with commas if you want to ignore multiple nodes"
        }
    }

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Get processor options

        These are dynamic for this processor: the 'column names' option is
        populated with the column names from the parent dataset, if available.

        :param config:
        :param DataSet parent_dataset:  Parent dataset
        :return dict:  Processor options
        """
        options = cls.options
        if parent_dataset is None:
            return options

        parent_columns = parent_dataset.get_columns()

        if parent_columns:
            parent_columns = {c: c for c in sorted(parent_columns)}
            options["column-a"] = {
                "type": UserInput.OPTION_CHOICE,
                "options": parent_columns,
                "help": "'From' column name",
                "tooltip": "Name of the column of values from which edges originate"
            }
            options["column-b"] = {
                "type": UserInput.OPTION_CHOICE,
                "options": parent_columns,
                "help": "'To' column name",
                "tooltip": "Name of the column of values at which edges terminate"
            }

        return options

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor to run on all csv and NDJSON datasets

        :param module: Module to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        return module.get_extension() in ("csv", "ndjson")

    def process(self):
        """
        This takes a 4CAT results file as input, and creates a network file
        based on co-occurring values from two columns of the original data.
        """

        column_a = self.parameters.get("column-a")
        column_b = self.parameters.get("column-b")
        directed = self.parameters.get("directed")
        categorise = self.parameters.get("categorise")
        split_comma = self.parameters.get("split-comma")
        allow_loops = self.parameters.get("allow-loops")
        interval_type = self.parameters.get("interval")
        to_lower = self.parameters.get("to-lowercase", False)
        ignoreable = [n.strip() for n in self.parameters.get("ignore-nodes", "").split(",") if n.strip()]

        processed = 0

        network_parameters = {"generated_by": "4CAT Capture & Analysis Toolkit", "source_dataset_id": self.source_dataset.key}
        network = nx.DiGraph(**network_parameters) if directed else nx.Graph(**network_parameters)

        for item in self.source_dataset.iterate_items(self):
            if column_a not in item or column_b not in item:
                missing = "'" + "' and '".join([c for c in (column_a, column_b) if c not in item]) + "'"
                self.dataset.update_status(f"Column(s) {missing} not found in dataset", is_final=True)
                self.dataset.finish(0)
                return

            processed += 1
            if processed % 500 == 0:
                self.dataset.update_status(f"Processed {processed:,} items ({len(network.nodes):,} nodes found)")
                self.dataset.update_progress(processed / self.source_dataset.num_rows)

            # both columns need to have a value for an edge to be possible
            if not item.get(column_a) or not item.get(column_b):
                continue

            # try casting the values to strings
            # if this fails, treat them as empty, so skip the item
            try:
                values_a = str(item[column_a])
            except ValueError:
                continue

            try:
                values_b = str(item[column_b])
            except ValueError:
                continue

            # convert to lowercase, if needed
            if to_lower:
                values_a = values_a.lower()
                values_b = values_b.lower()

            # account for possibility of multiple values by always treating a
            # column as a list of values, just sometimes with only one item
            values_a = [values_a]
            values_b = [values_b]

            if split_comma:
                values_a = [value.strip() for value_groups in values_a for value in value_groups.split(",")]
                values_b = [value.strip() for value_groups in values_b for value in value_groups.split(",")]

            if ignoreable:
                values_a = [v for v in values_a if v not in ignoreable]
                values_b = [v for v in values_b if v not in ignoreable]

            # only proceed if we actually have any edges left
            if not values_a or not values_b:
                continue

            try:
                interval = get_interval_descriptor(item, interval_type)
                if interval == "unknown_date":
                    raise ValueError(f"Date '{item.get('timestamp')}' cannot be parsed")
            except ValueError as e:
                return self.dataset.finish_with_error(f"{e}, cannot count posts per {interval_type}")
            
            # Track nodes per item (categoise option adjusts node name to include column if True)
            processed_nodes = set()

            # Track edges per item
            processed_edges = set()

            for value_a in values_a:
                for value_b in values_b:
                    # node 'ID', which we use to differentiate by column (or not)
                    node_a = column_a + "-" + value_a if categorise else "node-" + value_a
                    node_b = column_b + "-" + value_b if categorise else "node-" + value_b

                    if not allow_loops and node_a == node_b:
                        continue

                    # keep a list of intervals the node occurs in in the node
                    # attributes. Use a dictionary to also record per-interval
                    # frequency
                    if node_a not in processed_nodes:
                        if node_a not in network.nodes():
                            network.add_node(node_a, intervals={}, frequency=1, label=value_a, **({"category": column_a} if categorise else {}))
                        else:
                            network.nodes[node_a]["frequency"] += 1

                        if interval not in network.nodes[node_a]["intervals"]:
                            network.nodes[node_a]["intervals"][interval] = 0
                        network.nodes[node_a]["intervals"][interval] += 1

                        processed_nodes.add(node_a)
                    
                    if node_b not in processed_nodes:
                        if node_b not in network.nodes():
                            network.add_node(node_b, intervals={}, frequency=1, label=value_b, **({"category": column_b} if categorise else {}))
                        else:
                            network.nodes[node_b]["frequency"] += 1
                       
                        if interval not in network.nodes[node_b]["intervals"]:
                            network.nodes[node_b]["intervals"][interval] = 0
                        network.nodes[node_b]["intervals"][interval] += 1

                        processed_nodes.add(node_b)

                    # Use the same method to determine per-interval edge weight
                    if not directed:
                        # For undirected graphs, ensure edge direction doesn't matter
                        edge = tuple(sorted((node_a, node_b)))
                    else:
                        edge = (node_a, node_b)
                    
                    if edge not in processed_edges:
                        if edge not in network.edges():
                            network.add_edge(node_a, node_b, intervals={}, frequency=1, weight=1)
                        else:
                            network.edges[edge]["frequency"] += 1
                            network.edges[edge]["weight"] += 1

                        if interval not in network.edges[edge]["intervals"]:
                            network.edges[edge]["intervals"][interval] = 0

                        network.edges[edge]["intervals"][interval] += 1

                        processed_edges.add(edge)

        if not network.edges():
            self.dataset.update_status("No edges could be created for the given parameters", is_final=True)
            self.dataset.finish(0)
            return

        # If the network is dynamic, now we calculate spells from the intervals
        # This is a little complicated... but Gephi requires us to define
        # periods of activity rather than just the moment at which a given node
        # or edge was present
        # since gexf can only handle per-day data, generate weights for each
        # day in the interval at the required resolution
        if interval_type != "overall":
            self.dataset.update_progress(0)
            num_items = len(network.nodes) + len(network.edges)
            transformed = 1
            for component in (network.nodes, network.edges):
                for item in component:
                    if transformed % 500 == 0:
                        self.dataset.update_status(f"Transforming dynamic nodes and edges ({transformed:,} of {num_items:,} done)")
                        self.dataset.update_progress(transformed / num_items)

                    transformed += 1
                    for interval, weight in component[item]["intervals"].copy().items():
                        del component[item]["intervals"][interval]
                        component[item]["intervals"].update(self.extrapolate_weights(interval, weight, interval_type))

                    component[item]["intervals"] = dict(sorted(component[item]["intervals"].items(), key=lambda item: item[0]))

                    # now figure out the continuous periods of node existence
                    # as well as the period in which each weight was accurate
                    spells = []
                    weights = []
                    start = None
                    weight_start = None
                    previous = None
                    previous_weight = 0
                    for interval, weight in component[item]["intervals"].items():
                        if not start:
                            start = interval
                            weight_start = interval
                            previous = interval
                            previous_weight = weight
                            continue

                        # see if there is a gap of more than one day between
                        # this occurrence and the previous one
                        interval_datetime = datetime.datetime.strptime(interval, "%Y-%m-%d")
                        previous_datetime = datetime.datetime.strptime(previous, "%Y-%m-%d")

                        if interval_datetime > previous_datetime + datetime.timedelta(days=1):
                            # if so, create a new spell
                            spells.append((start, previous))
                            weights.append([weight, weight_start, previous])
                            start = interval
                            weight_start = interval
                        elif weight != previous_weight:
                            # for weights, also do so if the weight changes
                            weights.append([weight, weight_start, previous])
                            weight_start = interval

                        previous = interval
                        previous_weight = weight

                    # add final spells
                    spells.append((start, [*component[item]["intervals"].keys()][-1]))
                    weights.append([previous_weight, weight_start, [*component[item]["intervals"].keys()][-1]])

                    component[item]["spells"] = spells
                    component[item]["frequency"] = weights

        # the "intervals" key is no longer needed since it has been gexf-ified
        # in the 'spells' and 'frequency' keys
        for component in (network.nodes, network.edges):
            for item in component:
                del component[item]["intervals"]

        self.dataset.update_status("Writing network file")
        nx.write_gexf(network, self.dataset.get_results_path())
        self.dataset.finish(len(network.nodes))

    def extrapolate_weights(self, interval, weight, interval_type):
        """
        Expand weight for a given interval into weights per day

        For example, the weight '44' for the interval '2021-32' would return a
        dictionary with seven items, one per day in that week, with all items
        having a YYYY-MM-DD key and 44 as value.

        :param str interval:  Interval descriptor to expand
        :param int weight:  Weight for the given interval
        :param str interval_type:  One of `overall`, `year`, `month`, `week`,
        `day`
        :return dict:  A dictionary containing a weight per day
        """
        if interval_type not in ("month", "week", "year"):
            return {interval: weight}

        if interval_type == "year":
            moment = datetime.datetime(int(interval), 1, 1)
            interval_end = moment + relativedelta(years=+1)
        elif interval_type == "month":
            moment = datetime.datetime(int(interval.split("-")[0]), int(interval.split("-")[1]), 1)
            interval_end = moment + relativedelta(months=+1)
        elif interval_type == "week":
            # a little bit more complicated
            moment = datetime.datetime.strptime("%s-%s-1" % tuple(interval.split("-")), "%Y-%W-%w").date()
            interval_end = moment + relativedelta(weeks=+1)
        else:
            raise ValueError("extrapolate_weights() expects interval to be one of year, month, week")

        result = {}
        while moment < interval_end:
            result[moment.strftime("%Y-%m-%d")] = weight
            moment += relativedelta(days=+1)

        return result
