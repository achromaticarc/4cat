"""
Find similar words based on word2vec modeling
"""
import shutil

from gensim.models import KeyedVectors

from common.lib.helpers import UserInput, convert_to_int, convert_to_float
from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen", "Stijn Peeters"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class SimilarWord2VecWords(BasicProcessor):
	"""
	Find similar words based on word2vec modeling
	"""
	type = "similar-word2vec"  # job type ID
	category = "Text analysis"  # category
	title = "Extract similar words"  # title displayed in UI
	description = "Uses a Word2Vec model to find words used in a similar context"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI


	followups = ["wordcloud"]

	flawless = True

	options = {
		"words": {
			"type": UserInput.OPTION_TEXT,
			"help": "Words",
			"tooltip": "Separate with commas."
		},
		"num-words": {
			"type": UserInput.OPTION_TEXT,
			"help": "Amount of similar words",
			"min": 1,
			"default": 10,
			"max": 50
		},
		"threshold": {
			"type": UserInput.OPTION_TEXT,
			"help": "Similarity threshold",
			"tooltip": "Decimal value between 0 and 1; only words with a higher similarity score than this will be included",
			"default": "0.25"
		},
		"crawl_depth": {
			"type": UserInput.OPTION_CHOICE,
			"default": 1,
			"options": {"1": 1, "2": 2, "3": 3},
			"help": "The crawl depth. 1 only gets the neighbours of the input word(s), 2 also their neighbours, etc."
		}
	}

	@classmethod
	def is_compatible_with(cls, module=None, config=None):
		"""
		Allow processor on word embedding models

		:param module: Module to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
		"""
		return module.type == "generate-embeddings"

	def process(self):
		"""
		This takes previously generated Word2Vec models and uses them to find
		similar words based on a list of words
		"""
		self.dataset.update_status("Processing sentences")

		depth = max(1, min(3, convert_to_int(self.parameters.get("crawl_depth"))))
		input_words = self.parameters.get("words", "")
		if not input_words or not input_words.split(","):
			self.dataset.update_status("No input words provided, cannot look for similar words.", is_final=True)
			self.dataset.finish(0)
			return

		input_words = input_words.split(",")

		num_words = convert_to_int(self.parameters.get("num-words", 10))
		threshold = convert_to_float(self.parameters.get("threshold", 0.25), 0.25)

		threshold = max(-1.0, min(1.0, threshold))

		# go through all models and calculate similarity for all given input words
		result = []
		staging_area = self.unpack_archive_contents(self.source_file)
		for model_file in staging_area.glob("*.model"):
				interval = model_file.stem

				# for each separate model, calculate top similar words for each
				# input word, giving us at most
				#   [max amount] * [number of input] * [number of intervals]
				# items
				self.dataset.update_status("Running model %s..." % model_file.name)
				model = KeyedVectors.load(str(model_file))
				word_queue = set()
				checked_words = set()
				level = 1

				words = input_words.copy()
				while words:
					if self.interrupted:
						shutil.rmtree(staging_area)
						raise ProcessorInterruptedException("Interrupted while extracting similar words")

					word = words.pop()
					checked_words.add(word)

					try:
						similar_words = model.most_similar(positive=[word], topn=num_words)
					except KeyError:
						continue

					# Some words may have been excluded from the embedding model due to thresholds
					excluded_words = set()
					for similar_word in similar_words:
						if similar_word[1] < threshold:
							continue

						try:
							input_occurrences = model.get_vecattr(word, "count")
						except KeyError:
							if word not in excluded_words:
								excluded_words.add(word)
								self.dataset.log(f"'{word}' outside thresholds used for embedding model {model_file.name}; no occurrences")
							input_occurrences = 0
							self.flawless = False

						item_occurrences = model.get_vecattr(similar_word[0], "count")

						result.append({
							"date": interval,
							"input": word,
							"item": similar_word[0],
							"value": similar_word[1],
							"input_occurrences": input_occurrences,
							"item_occurrences": item_occurrences,
							"depth": level
						})

						# queue word for the next iteration if there is one and
						# it hasn't been seen yet
						if level < depth and similar_word[0] not in checked_words:
							word_queue.add(similar_word[0])

					# if all words have been checked, but we still have an
					# iteration to go, load the queued words into the list
					if not words and word_queue and level < depth:
						level += 1
						words = word_queue.copy()
						word_queue = set()

		shutil.rmtree(staging_area)

		if not result:
			self.dataset.update_status("None of the words were found in the word embedding model.", is_final=True)
			self.dataset.finish(0)
		else:
			if not self.flawless:
				self.dataset.update_status(
					"Dataset complete, but some input words were not found in the embedding models (0 occurances in model due to chosen thresholds). Similar words are still identified; check log for specifics.", is_final=True)
			self.write_csv_items_and_finish(result)
