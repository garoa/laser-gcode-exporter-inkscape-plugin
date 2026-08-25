About This Project
------------------
This project is an all-in-one exporting plugin for laser cutters and Inkscape. It requires Inkscape 1.0 or newer and Python 3, and has been verified on Inkscape 1.3; the original version targeted Inkscape 0.91 and Python 2.7 and is preserved under the `1.0.1` tag.
The plugin builds gcode that is compatible with a fork of Marlin designed to run on laser cutters found at https://github.com/TurnkeyTyranny/buildlog-lasercutter-marlin .

You can contact me via email at : 394ad2f@gmail.com, I check my email daily usually.

Donations
---------
Find this software useful? Donations are gratefully appreciated. 

* Paypal to 394ad2f@gmail.com
* Bitcoins to 16TFmnFyvDA8Q6TTakvvhargy8c89Rb3cj

Installation
------------

**Requires Inkscape 1.0 or newer** (verified on 1.3). For Inkscape 0.91 use the `1.0.1`
release of this plugin instead. See `CHANGELOG.md` for what changed in the 1.x port.

Copy `turnkeylaser.py` and `turnkeylaser.inx` into your Inkscape user extensions folder:

* Windows: `%APPDATA%\inkscape\extensions`
* macOS: `~/Library/Application Support/org.inkscape.Inkscape/config/inkscape/extensions`
* Linux: `~/.config/inkscape/extensions`

The exact path for your install is shown in Inkscape under
*Edit -> Preferences -> System -> User extensions*. Restart Inkscape and you will find
the plugin under *Extensions -> Export -> TurnkeyLaser Exporter*.

That is the whole install if you only cut vector paths. Rastering images and other
non-path objects additionally needs the Pillow imaging library in the Python interpreter
Inkscape uses. Inkscape 1.x bundles its own Python 3 with Pillow already included on
Windows and macOS, so this usually just works. If the plugin tells you Pillow is
missing, install it into that interpreter:

* Windows: `"C:\Program Files\Inkscape\bin\python.exe" -m pip install Pillow`
* macOS: `/Applications/Inkscape.app/Contents/Resources/bin/python3 -m pip install Pillow`
* Linux (system Python): `pip install --user Pillow`, or install your distribution's
  `python3-pillow` package.

Do **not** rename or replace Inkscape's bundled `python` folder — that was a workaround
for Inkscape 0.91 on Windows and will break Inkscape 1.x.

Usage and Setup
---------------
I recommend starting with this cutting surface and doing your designs in it. Its setup to match the size of the K40 Laser cutter bed : https://github.com/TurnkeyTyranny/laser-gcode-exporter-inkscape-plugin/blob/master/designs/cutting_surface.svg


Alternatively just set up your own new Inkscape job however you like. Unlike earlier versions of this plugin, the document no longer has to be in `px`: the exporter reads the page size and scale from the document itself, so mm, inch and px documents all export at the correct size. Set the output units you want the gcode in (mm or in) on the *Preferences* tab of the export dialog.

Name your layer in Inkscape like: 10 [feed=600,ppm=40]

This will set the power level to 10%, the feedrate to 600mm per minute and will fire at 40 pulse per millimetre in 60us duration pulses. PPM is ignored for rasters.
The ppm option is optional, if you do not specify it then the laser will default to continuous wave mode.
If you do not name your layer in this way then the script will use the default settings specified in the dialog box.


When you're ready to export your objects, images or paths just select the items you would like to be exported by dragging over them or holding shift to select multiple and then run the plugin under under Extensions Menu -> Export -> Turnkey Laser Exporter. 
![alt tag](https://raw.githubusercontent.com/TurnkeyTyranny/laser-gcode-exporter-inkscape-plugin/master/instructions.png)


Sending the file to your laser
------------------------------
You can send the file to your laser by serial (USB cable) or SD memory card. 

1) Via USB cable
* Download repetier host and install it on your PC - http://www.repetier.com/download/
* Open the software and set the port of your laser in the options. It will typically be COM7 - otherwise it's the same as what your programmed your Arduino on originally. The port speed should be set to 115200
* Press the connect button, it will turn green.
* Open your gcode file you created earlier and press the print button. Your laser will now burn your instruction set.


Alternatively you can use pronterface http://www.pronterface.com/index.html#download . You must ensure you check the box for Pronterface under 'Advanced' tab in the exporter plugin. It is checked by default.

2) Via SD Memory card
* Place the file onto your SD card
* Insert it into your ramps SD card reader.
* Select the file from the ramps LCD menu and print.

Keyboard Shortcut
-----------------

You may find it handy to assign the extension to a keyboard shortcut. 
Include something like the following line to your inkscape keys 
preferences file (this will bind the plugin to Ctrl+\):

<bind key="backslash" modifiers="Ctrl" action="org.thinkhaus.filter.thlaser"
display="true"/>

You can find your keyboard preferences file:

* On Linux: ~/.config/inkscape/keys/default.xml
* Windows:  %UserProfile%\Application Data\Inkscape\keys\default.xml

If that file doesn't exist, create it and include the following:

<?xml version="1.0"?>
<keys name="My Keys">
<bind key="backslash" modifiers="Ctrl" action="org.thinkhaus.filter.thlaser"
display="true"/>
</keys>


Attribution
--------------------
The project is built on work by other people, thanks go out to the effort they put in before me.
Thanks to work by https://github.com/ajfoul , Thinkhaus and Lansing Makers Network
This script is released under the license GPL v2.

Change log
--------------------
26-Feb-2015 - 2 hours : Forked from user ajfoul to extend functionality of smoothie laser power levels 0.0 to 1.0, generic Marlin power levels being 0 to 100.

07-March-2015 - 10 hours : Cleaned up the exporters code a lot. Added ppm and feedrate detection from the layer name. Updated the gcode that is exported to be neater and work better with pulsed mode using G01, G02 and G03 commands.

07-March-2015 - Fixed the G28 command at the end of the job. Added defaults for laser power, feedrates and ppm if defined. If ppm isn't defined in the layer options it will operate as continuous wave mode. See the help in the extension dialog for how to use.

07-March-2015 - Marlin codebase mod : You need to patch the Marlin codebase to turn on the laser before moving for G02 and G03 commands. This plugin assumes this has been done. More details to come in the future. Copy the code from the G01 above in marlin_main.cpp - This change has been put into my version of the Marlin Laser firmware found here https://github.com/TurnkeyTyranny/buildlog-lasercutter-marlin

19-March-2015 - After optimising the image to gcode 'code' I'm now working on integrating that into the python script run directly from Inkscape. Hiccups though as Inkscape for Windows ships with a shitty version of Python that is missing imaging libraries. Must install Python 2.7 and PIL for image reading. Have a proof of concept running

20-March-2015 - Added raster support for jpeg and png images. Currently they export at Inkscape's default DPI of 90, I'll have to upscale them to around 300 next. Go burn some cool shit!

27-March-2015 - Objects in inkscape which are not paths are now exported to be rastered. They are exported at 270dpi. Images are now also upscaled or downscaled and exported at 270dpi.

28-March-2015 - Fixed many many bugs with default power levels and other defaults, completed the work on exporting objects and images as rasters. Fixed up as many situations I could find that threw python error messages and replaced them with meaningful notices for the user.

30-March-2015 - Modified the way that X-Y coordinates are determined for a node. This allows objects that are on a layer that has been transposed or transformed or if the objects themselves have to be correctly positioned in the gcode exported data. It's a little bit slower but much more reliable. This change only applies to the export of rasters.

01-April-2015 - Need to get the 'positioning for all' functionality working as exporting many raster objects is painfully slow.
Updated script to export rasters with top left as the origin or bottom left.

09-April-2015 - Updated the readme with better install instructions. Updated the expoter to use a faster method of finding the X-Y coordinates to many rasters however it's only compatible with Inkscape 0.91 now using that command as far as I have been told.

10-April-2015 - Fixed a bug with exporting paths when the origin was the top left.
Disabled raster horizintal movement optimisation as it has a bug. Rasters will be a little slower but will come out oriented correctly. Search for line : row2 = rowData 

11-April-2015 - Added back in raster optimising, it's not perfect but it's mostly there. Only a little slow parsing white vertical space now.
Found that raster optimisation code seems to be changing the pixel data at the end of the line somewhere. I'm not sure how since it's meant to just be cutting part of the data line out not changing it. will need to investigate further.
Added option to the menu for users to disable raster optimisations.
