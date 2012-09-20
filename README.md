# ZYNC Plugin for Nuke

## zync-python

This plugin depends on zync-python, the ZYNC Python API.

Before trying to install zync-nuke, make sure to [download zync-python](https://github.com/zync/zync-python) and follow the setup instructions there.

## Config File

Contained in this folder you'll find a file called ```config_nuke.py.example```. Make a copy of this file in the same directory, and rename it ```config_nuke.py```.

Edit ```config_nuke.py```. It defines only one config variable, ```API_DIR```, which is the full path to your zync-python directory. Set this path, save the file, and close it.

## Set Up menu.py

You'll need to locate your .nuke folder, usually stored within your HOME folder. In there you'll need a file called menu.py. This file may already exist.

menu.py should contain the following text:

```python
import nuke
nuke.pluginAddPath( "/path/to/zync-nuke" )
import zync_nuke
menubar = nuke.menu( "Nuke" );
menu = menubar.addMenu( "&Render" )
menu.addCommand( 'Render on ZYNC', 'zync_nuke.submit_dialog()' )
```

This will add an item to the "Render" menu in ZYNC that will allow you to launch ZYNC jobs.

## Done

That's it! Restart Nuke to pull in the changes you made.

