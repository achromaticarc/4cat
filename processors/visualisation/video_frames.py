"""
Create frames of videos

This processor also requires ffmpeg to be installed in 4CAT's backend
https://ffmpeg.org/
"""
import shutil
import subprocess
import oslex

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput
from processors.visualisation.download_videos import VideoDownloaderPlus

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class VideoFrames(BasicProcessor):
	"""
	Video Frame Extracter

	Uses ffmpeg to extract a certain number of frames per second at different sizes and saves them in an archive.
	"""
	type = "video-frames"  # job type ID
	category = "Visual"  # category
	title = "Extract frames from videos"  # title displayed in UI
	description = "Extract frames from videos"  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	followups = ["video-timelines"] + VideoDownloaderPlus.followups

	options = {
		"frame_interval": {
			"type": UserInput.OPTION_TEXT,
			"help": "Number of frames extracted per second to extract from video",
			"tooltip": "The default value is 1 frame per second. For 1 frame per 5 seconds pass 0.2 (1/5). For 5 fps "
					   "pass 5, and so on. Use '0' to only capture the first frame of the video.",
			"coerce_type": float,
			"default": 1,
			"min": 0,
			"max": 5,
		},
		"frame_size": {
			"type": UserInput.OPTION_CHOICE,
			"default": "medium",
			"options": {
				"no_modify": "Do not modify",
				"144x144": "Tiny (144x144)",
				"432x432": "Medium (432x432)",
				"1026x1026": "Large (1026x1026)",
			},
			"help": "Size of extracted frames"
		},
	}

	@classmethod
	def is_compatible_with(cls, module=None, config=None):
		"""
		Allow on videos

        :param ConfigManager|None config:  Configuration reader (context-aware)
		"""
		return (module.get_media_type() == "video" or module.type.startswith("video-downloader")) and \
			   config.get("video-downloader.ffmpeg_path") and \
			   shutil.which(config.get("video-downloader.ffmpeg_path"))

	def process(self):
		"""
		This takes a zipped set of videos, uses https://pypi.org/project/videohash/ and https://ffmpeg.org/ to collect
		frames from the videos at intervals and create image collages to hashes for comparison of videos.
		"""
		# Check processor able to run
		if self.source_dataset.num_rows == 0:
			self.dataset.update_status("No videos from which to extract frames.", is_final=True)
			self.dataset.finish(0)
			return

		# Collect parameters
		frame_interval = self.parameters.get("frame_interval", 1.0)
		frame_size = self.parameters.get("frame_size", "no_modify")

		# Prepare staging area for videos and video tracking
		staging_area = self.dataset.get_staging_area()
		self.dataset.log('Staging directory location: %s' % staging_area)

		# Output folder
		output_directory = staging_area.joinpath('frames')
		output_directory.mkdir(exist_ok=True)

		total_possible_videos = self.source_dataset.num_rows
		processed_videos = 0

		self.dataset.update_status("Extracting video frames")
		for i, path in enumerate(self.iterate_archive_contents(self.source_file, staging_area)):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while determining image wall order")

			# Check for 4CAT's metadata JSON and copy it
			if path.name == '.metadata.json':
				shutil.copy(path, output_directory)
				continue

			vid_name = path.stem
			video_dir = output_directory.joinpath(vid_name)
			video_dir.mkdir(exist_ok=True)

			command = [
				shutil.which(self.config.get("video-downloader.ffmpeg_path")),
				"-i", oslex.quote(str(path))
			]

			if frame_interval != 0:
				command += ["-r", str(frame_interval)]
			else:
				command += ["-vframes", "1"]

			if frame_size != 'no_modify':
				command += ['-s', oslex.quote(frame_size)]
			command += [oslex.quote(str(video_dir) + "/video_frame_%07d.jpeg")]

			self.dataset.log(" ".join(command))

			result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

			# Capture logs
			ffmpeg_output = result.stdout.decode("utf-8")
			ffmpeg_error = result.stderr.decode("utf-8")

			if ffmpeg_output:
				with open(video_dir.joinpath('ffmpeg_output.log'), 'w') as outfile:
					outfile.write(ffmpeg_output)

			if ffmpeg_error:
				with open(video_dir.joinpath('ffmpeg_error.log'), 'w') as outfile:
					outfile.write(ffmpeg_error)

			if result.returncode != 0:
				self.dataset.update_status(f"Unable to extract frames from video {vid_name} (see logs for details)")
				self.dataset.log('Error Return Code (%s) with video %s: %s' % (str(result.returncode), vid_name, "\n".join(ffmpeg_error.split('\n')[-2:]) if ffmpeg_error else ''))
			else:
				processed_videos += 1
				self.dataset.update_status("Created frames for %i of %i videos" % (processed_videos, total_possible_videos))

			self.dataset.update_progress(i / total_possible_videos)

		# Finish up
		# We've created a directory and folder structure here as opposed to a single folder with single files as
		# expected by self.write_archive_and_finish() so we use make_archive instead
		if not processed_videos:
			self.dataset.finish_with_error("Unable to extract frames from any videos")
			return

		from shutil import make_archive
		make_archive(self.dataset.get_results_path().with_suffix(''), "zip", output_directory)

		# Remove staging area
		shutil.rmtree(staging_area)

		self.dataset.finish(processed_videos)
