# ZYNC Plugin for Nuke

## Installing

Everything you need is included in this repository. You'll just need to point Nuke to this folder to load it on startup.

You'll need to locate your .nuke folder, usually stored within your HOME folder. In there you'll need a file called menu.py. This file may already exist.

init.py should contain the following text:

```python
import nuke
nuke.pluginAddPath( "/path/to/nuke_zync_submit" )
import zync_submit
menubar = nuke.menu( "Nuke" );
menu = menubar.addMenu( "&Render" )
menu.addCommand( 'ZYNC Render', 'zync_submit.submit_dialog()' )
```

This will add an item to the "Render" menu in ZYNC that will allow you to launch ZYNC jobs.

Now, open up nuke_zync_submit/zync_submit.py. Near the top you'll see a few lines tell you to REPLACE the values with your own. Edit those lines accordingly.

For the line that says "# REPLACE WITH PATH TO zync/ DIRECTORY", its talking about the "zync" folder included with these plugins. This folder contains the Python API used by both the Nuke and Maya plugins, and should be stored in a central place.
