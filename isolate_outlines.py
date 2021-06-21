
#!/usr/bin/env python

from gimpfu import *
import gimpcolor
import gimpenums


# Main function
def isolate_outlines(timg, tdrawable, threshold):
    pdb.gimp_context_set_sample_threshold(threshold)
    pdb.gimp_image_select_color(
        timg,
        gimpenums.CHANNEL_OP_REPLACE,
        tdrawable,
        gimpcolor.RGB(0, 0, 0)
    )

    pdb.gimp_edit_copy(tdrawable)
    floating_layer = pdb.gimp_edit_paste(tdrawable, False)
    pdb.gimp_floating_sel_to_layer(floating_layer)


# Register function
register(
	"python_fu_isolate_outlines",
	"Isolate black outlines and paste to new layer",
	"Isolate black outlines and paste to new layer",
    "Ben Carey",
    "Ben Carey",
    "2021",
	"<Image>/Tools/Custom/Isolate Outlines",
	"*",
	[
        (PF_FLOAT, "pf_threshold", "Threshold", 0.7),
    ],
	[],
	isolate_outlines
)

main()
