#!/usr/bin/env python

import math

from gimpfu import *
import gimpcolor
import gimpenums


# Exceptions
class InvalidRowError(Exception):
	def __init__(self, message=None):
		if not message:
			message = "Tried to access row outside selected region."
		super(InvalidRowError, self).__init__(message)


class SelectionSizeError(Exception):
	def __init__(self, message=None):
		if not message:
			message = "Selected region is too small to fit given text."
		super(SelectionSizeError, self).__init__(message)


class NoSelectionError(Exception):
	def __init__(self, message=None):
		if not message:
			message = (
				"SpeechBubblifier must be run with a speech bubble "
				"area selected."
			)
		super(NoSelectionError, self).__init__(message)


# Classes
class WordLayer(object):
	"""Struct to encapsulate data for word layers"""
	def __init__(self, layer, x_min, y_min, x_max, y_max):
		self.layer = layer
		self.x_min = x_min
		self.y_min = y_min
		self.x_max = x_max
		self.y_max = y_max
		self.height = y_max - y_min
		self.width = x_max - x_min


class BlockRow(object):
	"""Class to represent a block row of a selected area.

	A block row here means the largest rectangular area that fits inside a
	given series of consecutive pixel rows.

	We split selected regions into block rows of a given height, extending out
	from the centre, and separate the cases where we have an even number of
	rows and where we have an odd number.

	eg. in the following selected area:

        ................
     .....................
     ......................
    .........................
    ........................
   .........................
      ...................
      .................
         .............

	the 'odd' block rows of height 3 would be:

        +--------------+
     ...| BLOCK ROW 2  |..
     ...+--------------+...
    +----------------------+.
    |     BLOCK ROW 1      |
   .+----------------------+
      ...+-----------+...
      ...|BLOCK ROW 3|.
         +-----------+

	and the 'even' block rows of height 3 would be:

        ................
     .....................
     +--------------------+
    .|   BLOCK ROW 1      |..
    .+--------------------+.
   ...+---------------+.....
      |  BLOCK ROW 2  |..
      +---------------+
         .............
	"""
	def __init__(self, selection, top):
		self.selection = selection
		self.height = selection.row_height
		self.top = top
		self.bottom = top + self.height
		self._compute_horizontal_bounds()

	def _compute_horizontal_bounds(self):
		"""Find left and right bounds of block row."""
		self.left = None
		self.right = None
		for y in range(self.top, self.bottom):
			bounds = self.selection.get_pixel_row_bounds(y)
			if not bounds:
				return
			if not self.left or bounds[0] > self.left:
				self.left = bounds[0]
			if not self.right or bounds[1] < self.right:
				self.right = bounds[1]
		self.width = 0
		if self.left and self.right:
			self.width = self.right - self.left


class Selection(object):
	"""Class to interact with gimp selections and split into block rows."""
	def __init__(self, gimp_selection, x_min, y_min, x_max, y_max, row_height):
		self.selection = gimp_selection
		self.x_min = x_min
		self.y_min = y_min
		self.x_max = x_max
		self.y_max = y_max
		self.height = y_max - y_min
		self.width = x_max - x_min
		self.row_height = row_height
		self._compute_pixel_row_bounds()
		self._compute_block_rows()

	def _compute_pixel_row_bounds(self):
		"""Get the horizontal bounds of each pixel row.

		This finds the first and last non-empty pixel of each row and uses
		it to populate self.pixel_row_bounds.
		"""
		self._pixel_row_bounds = []
		for y in range(self.y_min, self.y_max):
			bound_min = None
			bound_max = None
			for x in range(self.x_min, self.x_max):
				if self.selection.get_pixel(x, y)[0]:
					bound_min = x
					break
			else:
				self._pixel_row_bounds.append(None)
				continue
			for x in range(self.x_max, self.x_min, -1):
				if self.selection.get_pixel(x, y)[0]:
					bound_max = x
					break
			self._pixel_row_bounds.append((bound_min, bound_max))

	def get_pixel_row_bounds(self, pixel_row):
		"""Get horizontal bounds of given pixel row.
		
		Args:
			pixel_row (int): the row we're looking at.

		Returns:
			tuple(int, int) or None: the start and end of the selected region
				of the pixel row, or None if row is all unselected.
		"""
		try:
			return self._pixel_row_bounds[pixel_row - self.y_min]
		except IndexError:
			raise InvalidRowError()

	def _compute_block_rows(self):
		"""Find the odd and even block rows for this selection."""
		centre_height = int(math.floor(0.5 * (self.y_min + self.y_max)))
		num_steps = int(math.floor(0.5 * (self.height / self.row_height)))
		half_row_height_floor = int(math.floor(0.5 * self.row_height))
		half_row_height_ceil = int(math.ceil(0.5 * self.row_height))
		self.odd_block_rows = [
			BlockRow(self, centre_height - half_row_height_floor)
		]
		self.even_block_rows = []
		# add rows going out from centre
		for i in range(num_steps):
			even_row_higher = centre_height - ((i + 1) * self.row_height)
			even_row_lower = centre_height + (i * self.row_height)
			odd_row_higher = even_row_higher - half_row_height_floor
			odd_row_lower = even_row_lower + half_row_height_ceil
			self.even_block_rows.extend([
				BlockRow(self, even_row_higher),
				BlockRow(self, even_row_lower),
			])
			if odd_row_higher >= self.y_min:
				self.odd_block_rows.extend([
					BlockRow(self, odd_row_higher),
					BlockRow(self, odd_row_lower)
				])
		self.max_rows = max(len(self.odd_block_rows, self.even_block_rows))

	def place_words(self, word_layers):
		"""Place words in selection.

		This uses the block rows and places the words centred around
		the middle of the selection.

		Args:
			word_layers (list(WordLayer)): list of WordLayer objects
				representing text to add.
		"""
		min_num_rows = self._get_min_num_rows(word_layers)
		if not min_num_rows:
			raise SelectionSizeError()
		for num_rows in range(min_num_rows, self.max_rows):
			block_row_generator = self._get_block_rows(num_rows)
			block_row = next(block_row_generator)
			word_layers_by_row = {}
			cumulative_word_width = 0
			for word_layer in word_layers:
				cumulative_word_width += word_layer.width
				while cumulative_word_width > block_row.width:
					try:
						block_row = next(block_row_generator)
						cumulative_word_width = word_layer.width
					except StopIteration:
						# reached end of generator
						# break and try again with higher num_rows
						break
				else:
					# didn't hit StopIteration
					# so can add word_layer to word_layers_by_row
					word_layers_by_row.setdefault(block_row, []).append(
						word_layer
					)
					continue
				# if we get here, we hit StopIteration above
				# break and try again with higher num_rows
				break
			else:
				# didn't hit StopIteration with this number of rows
				# hence word layers fit in given number of rows
				# so we can actually place the words now
				self._place_words(word_layers_by_row)
				return
		# didn't hit return above
		# hence word layers do not fit in any number of rows
		raise SelectionSizeError()

	def _place_words(self, word_layers_by_row):
		"""Place words in selection using given grouping of words with rows.

		This is used by place_words method and it assumes that we already know
		the word_layers will fit in the given rows.

		Args:
			word_layers_by_row (dict(BlockRow, WordLayer)): dictionary of word
				layers keyed by the block row they should be added to.
		"""
		for block_row, word_layers in word_layers_by_row.items():
			total_word_width = sum(
				word_layer.width for word_layer in word_layers
			)
			text_start = total_word_width / 
			for word_layer in word_layers:



	def _get_min_num_rows(self, word_layers):
		"""Get minimum number of block rows needed to add text.

		This returns the smallest number of rows that could possibly be needed
		to cover all the text, so that we're not recalculating the text
		positions too many times. We get this value by comparing the total
		width of all the text in the word_layers to the cumulative width of the
		row blocks that will be used.

		Args:
			word_layers (list(WordLayer)): list of WordLayer objects
				representing text to add.

		Returns:
			int or None: minimum number of rows required, or None if the text
				will not fit in this selection.
		"""
		total_word_width = sum(word_layer.width for word_layer in word_layers)
		cumulative_even_row_width = 0
		cumulative_odd_row_width = 0
		min_num_rows_even = None
		min_num_rows_odd = None
		for index, row in enumerate(self.even_block_rows):
			cumulative_even_row_width += row.width
			if cumulative_even_row_width >= total_word_width:
				min_num_rows_even = index + 1 if index % 2 == 0 else index + 2
				break
		for index, row in enumerate(self.odd_block_rows):
			cumulative_odd_row_width += row.width
			if cumulative_odd_row_width >= total_word_width:
				min_num_rows_odd = index + 1 if index % 2 == 1 else index + 2
				break
		if min_num_rows_even is None:
			return min_num_rows_odd
		if min_num_rows_odd is None:
			return min_num_rows_even
		return min(min_num_rows_odd, min_num_rows_even)

	def _get_block_rows(self, n):
		"""Yields the first n block rows, from top downwards.

		If n is odd this will return the first n rows from self.odd_block_rows,
		Otherwise, this will return the first n rows from self.even_block_rows.
		In either case, it reorders the rows from top downwards.

		Args:
			n (int): number of rows we want to get.

		Yields:
			BlockRow: list of the first n BlockRow objects.
		"""
		block_rows = self.even_block_rows if n % 2 == 0 else self.odd_block_rows
		num_steps = int(0.5 * n)
		for i in range(num_steps):
			yield block_rows[n - 2*i - 2]
		if n % 2 == 1:
			yield block_rows[0]
		for i in reversed(range(num_steps)):
			yield block_rows[n - 2*i - 1]


# Main function
def speech_bubblifier(timg, tdrawable, font, text, size):
	# get bounds of current selection (which should be speech bubble)
	non_empty, x_min, y_min, x_max, y_max = pdb.gimp_selection_bounds(timg)
	if not non_empty:
		raise NoSelectionError()
		return
	gimp_selection = timg.selection
	text_group_layer = pdb.gimp_layer_group_new(timg)
	text_group_layer = "text group"
	timg.add_layer(text_group_layer)

	black = gimpcolor.RGB(0,0,0)
	words = text.split()
	word_layers = []
	for word in words:
		print (word)
		word_layer = pdb.gimp_text_layer_new(timg, word, font, size, 0)
		word_layer.name = word
		timg.add_layer(word_layer)
		pdb.gimp_text_layer_set_color(word_layer, black)
		pdb.gimp_image_select_color(
			timg,
			gimpenums.CHANNEL_OP_REPLACE,
			word_layer,
			black
		)
		non_empty, _x_min, _y_min, _x_max, _y_max = pdb.gimp_selection_bounds(timg)
		word_layers.append(WordLayer(word_layer, _x_min, _y_min, _x_max, _y_max))
	row_height = max(word_layer.height for word_layer in word_layers)

	selection = Selection(gimp_selection, x_min, y_min, x_max, y_max, row_height)
	selection.place_words(word_layers)

	for block_row in selection.odd_block_rows:
		if not block_row.left or not block_row.right:
			continue
		pdb.gimp_palette_set_foreground(
			gimpcolor.RGB(236,0,0)
		)
		pdb.gimp_image_select_rectangle(
			timg,
			gimpenums.CHANNEL_OP_REPLACE,
			block_row.left,
			block_row.top,
			block_row.right - block_row.left,
			20
		)
		pdb.gimp_drawable_edit_fill(
			tdrawable,
			gimpenums.FOREGROUND_FILL
		)

	return

	black = gimpcolor.RGB(0,0,0)
	words = text.split()
	word_layers = []
	for word in words:
		print (word)
		word_layer = pdb.gimp_text_layer_new(timg, word, font, size, 0)
		timg.add_layer(word_layer)
		pdb.gimp_text_layer_set_color(word_layer, black)
		pdb.gimp_image_select_color(
			timg,
			gimpenums.CHANNEL_OP_REPLACE,
			word_layer,
			black
		)
		non_empty, _x_min, _y_min, _x_max, _y_max = pdb.gimp_selection_bounds(timg)
		word_layers.append(WordLayer(word_layer, _x_min, _y_min, _x_max, _y_max))


# Register function
register(
	"python_fu_speech_bubblifier",
	"Arrange text in preselected speech bubble shape",
	"Arrange text in preselected speech bubble shape",
	"Ben Carey",
    "Ben Carey",
    "2021",
	"<Image>/Tools/Custom/Speech Bubblifier",
	"*",
	[
		(PF_FONT, "pf_font", "Choose Font", "Comic Sans MS"),
		(PF_STRING, "pf_text", "Write Text", ""),
		(PF_FLOAT, "pf_text_size", "Text size", 60),
	],
	[],
	speech_bubblifier
)

main()
