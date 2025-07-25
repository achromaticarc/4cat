"""
Request tags and labels from the Google Vision API for a given set of images
"""
import requests
import base64
import json
import csv

from pathlib import Path

from common.lib.helpers import UserInput, convert_to_int
from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class GoogleVisionAPIFetcher(BasicProcessor):
    """
    Google Vision API data fetcher

    Request tags and labels from the Google Vision API for a given set of images
    """
    type = "google-vision-api"  # job type ID
    category = "Metrics"  # category
    title = "Google Vision API Analysis"  # title displayed in UI
    description = "Use the Google Vision API to annotate images with tags and labels identified via machine learning. " \
                  "One request will be made per image per annotation type. Note that this is not a free service and " \
                  "requests will be credited by Google to the owner of the API token you provide. Requires billing " \
                  "and Google Vision API enabled (this may take a few minutes)."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI

    followups = ["convert-google-vision-to-csv", "vision-bipartite-network", "vision-label-network"]

    references = [
        "[Google Vision API Documentation](https://cloud.google.com/vision/docs)",
        "[Google Vision API Pricing & Free Usage Limits](https://cloud.google.com/vision/pricing)"
    ]

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on image sets

        :param module: Module to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        return module.get_media_type() == "image" or module.type.startswith("image-downloader") or module.type == "video-frames"

    options = {
        "amount": {
            "type": UserInput.OPTION_TEXT,
            "help": "Images to process (0 = all)",
            "default": 0
        },
        "api_key": {
            "type": UserInput.OPTION_TEXT,
            "help": "API Key",
            "tooltip": "The API Key for the Google API account you want to query with. You can generate and find this"
                       "key on console.cloud.google.com. You also need to enable billing and Vision API."
        },
        "features": {
            "type": UserInput.OPTION_MULTI,
            "help": "Features",
            "options": {
                "LABEL_DETECTION": "Label Detection",
                "TEXT_DETECTION": "Text Detection",
                "DOCUMENT_TEXT_DETECTION": "Document Text Detection",
                "SAFE_SEARCH_DETECTION": "Safe Search Detection",
                "FACE_DETECTION": "Facial Detection",
                "LANDMARK_DETECTION": "Landmark Detection",
                "LOGO_DETECTION": "Logo Detection",
                "IMAGE_PROPERTIES": "Image Properties",
                "CROP_HINTS": "Crop Hints",
                "WEB_DETECTION": "Web Detection",
                "OBJECT_LOCALIZATION": "Object Localization"
            },
            "default": ["LABEL_DETECTION"]
        },
        "annotation_info": {
            "type": UserInput.OPTION_INFO,
            "help": "The output can be made human-readable through the following `Convert Vision results to CSV` "
                    "processor. This also lets you write the labels as annotations to the original dataset."
        }
    }

    def process(self):
        """
        This takes a 4CAT results file as input, and outputs a new CSV file
        with one column with image hashes, one with the first file name used
        for the image, and one with the amount of times the image was used
        """
        api_key = self.parameters.get("api_key")
        self.dataset.delete_parameter("api_key")  # sensitive, delete after use

        features = self.parameters.get("features")
        features = [{"type": feature} for feature in features]

        if not api_key:
            self.dataset.finish_with_error("You need to provide a valid API key")
            return

        # is there anything for us to download?
        if self.source_dataset.num_rows == 0:
            self.dataset.finish_with_error("No images to download.")
            return

        max_images = convert_to_int(self.parameters.get("amount", 0), 100)
        total = self.source_dataset.num_rows if not max_images else min(max_images, self.source_dataset.num_rows)
        processed = 0
        done = 0

        # Get the .metadata.json file if we're writing annotations so we can add them to specific rows.
        img_metadata = []

        # Loop through images
        for image_file in self.iterate_archive_contents(self.source_file):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while fetching data from Google Vision API")

            self.dataset.update_status("Annotating image %i/%i" % (done, total))
            self.dataset.update_progress(done / total)

            if image_file.name.startswith(".") or image_file.suffix in (".json", ".log"):

                # Get the .metadata.json file so we can also save post IDs.
                if image_file.name == ".metadata.json":
                    img_metadata = json.load(image_file.open())
                    if img_metadata:
                        img_metadata = {v["filename"]: v.get("post_ids", []) for v in img_metadata.values()}
                else:
                    self.dataset.log(f"Skipping file {image_file.name}, probably not an image.")
                continue

            try:
                annotations = self.annotate_image(image_file, api_key, features)
            except RuntimeError:
                # cannot continue fetching, e.g. when API key is invalid
                break

            if not annotations:
                continue

            annotations = {
                "file_name": image_file.name,
                "post_ids": img_metadata[image_file.name],
                **annotations}

            with self.dataset.get_results_path().open("a", encoding="utf-8") as outfile:
                outfile.write(json.dumps(annotations) + "\n")
                done += 1

            if max_images and done >= max_images:
                break

        self.dataset.update_status("Annotations retrieved for %i images (%i processed in total)" % (done, processed), is_final=True)
        self.dataset.finish(done)

    def annotate_image(self, image_file: Path, api_key: str, features: list):
        """
        Get annotations from the Google Vision API

        :param Path image_file:  Path to file to annotate
        :param str api_key:  API Bearer Token
        :param list features:  Features to request
        :return dict:  Lists of detected features, one key for each feature
        """
        endpoint = "https://vision.googleapis.com/v1/images:annotate?key=%s" % api_key

        with image_file.open("rb") as infile:
            base64_image = base64.b64encode(infile.read()).decode("ascii")

        api_params = {
            "requests": {
                "image": {"content": base64_image},
                "features": features
            }
        }

        try:
            api_request = requests.post(endpoint, json=api_params)
        except (requests.RequestException, ConnectionError) as e:
            self.dataset.update_status("Skipping image %s due to %s (%s)" % (image_file.name, e.__name__, str(e)))
            return None

        if api_request.status_code == 401:
            self.dataset.update_status("Invalid API key or reached API quota, halting", is_final=True)
            raise RuntimeError()  # not recoverable

        elif api_request.status_code == 400 and "BILLING_DISABLED" in api_request.text:
            self.dataset.update_status("Billing is not enabled for your API key. You need to enable billing to use "
                                       "the Google Vision API.", is_final=True)
            raise RuntimeError()  # not recoverable

        elif api_request.status_code != 200:
            self.dataset.update_status("Got response code %i from Google Vision API for image %s, skipping" % (api_request.status_code, image_file.name))
            self.dataset.log(f"Code {api_request.status_code}; Text: {api_request.text}")
            return None

        try:
            response = api_request.json()
            response = response["responses"]
        except (json.JSONDecodeError, KeyError):
            self.dataset.update_status("Got an improperly formatted response from Google Vision API for image %s, skipping" % image_file.name)
            return None

        return response.pop()