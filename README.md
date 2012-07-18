# ZYNC Plugin for Nuke

## Installing

Everything you need is included in this repository. You'll just need to point Nuke to this folder to load it on startup.

You'll need to locate your .nuke folder, usually stored within your HOME folder. In there you'll need a file called menu.py. This file may already exist.

init.py should contain the following text:

```python
import nuke
nuke.pluginAddPath( "/path/to/zync-nuke" )
import zync_nuke
menubar = nuke.menu( "Nuke" );
menu = menubar.addMenu( "&Render" )
menu.addCommand( 'ZYNC Render', 'zync_nuke.submit_dialog()' )
```

This will add an item to the "Render" menu in ZYNC that will allow you to launch ZYNC jobs.

Now, open up zync_nuke.py. Near the top you'll see a few lines tell you to REPLACE with the path to your zync-python directory. This is referring to the ZYNC Python API. As both Nuke and Maya use this API, it should be stored in a central location accessible by both softwares.

