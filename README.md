# ZYNC Plugin for Nuke

## zync-python

This plugin depends on zync-python, the ZYNC Python API.

Before trying to install zync-nuke, make sure to [download zync-python](https://github.com/zync/zync-python) and follow the setup instructions there.

## Register Script

Log in to the ZYNC Web Console, and go to the My Account page.

In the "Scripts" section, you'll be able to register a new script. Call it "nuke_plugin".

This will generate an API Key, which you'll see listed next to the registered script. Save this key for the next step.

## Config File

Contained in this folder you'll find a file called ```config_nuke.py.example```. Make a copy of this file in the same directory, and rename it ```config_nuke.py```.

Edit ```config_nuke.py```. It defines two config variables:

 ```API_DIR``` - the full path to your zync-python directory.
```API_KEY``` - the API Key of the registered script, from the previous step.

Set these variables, save the file, and close it.

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

