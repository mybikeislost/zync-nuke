"""
ZYNC Submit

This module provides a Nuke + Python implementation of the web-based ZYNC
Job Submit GUI. There are a few advantages to doing render submissions to ZYNC
from within Nuke:
    * extensive preflight checking possible
    * less context switching between the browser and nuke

Future work:
    * split out zync API stuff into separate zync python module

Usage as a menu item:
    nuke.pluginAddPath( "./zync-nuke" )
    import zync_nuke
    menu.addCommand('ZYNC Render', 'zync_nuke.submit_dialog()')
"""

import hashlib
import nuke
import nukescripts
import platform
import os
import re
import socket
import sys
import time
import traceback
import urllib

__author__ = 'Alex Schworer'
__copyright__ = 'Copyright 2011, Atomic Fiction, Inc.'

config_path = '%s/config_nuke.py' % (os.path.dirname(__file__),)
if not os.path.exists(config_path):
    raise Exception('Could not locate config_nuke.py, please create.')
from config_nuke import *

required_config = ['API_DIR', 'API_KEY']

for key in required_config:
    if not key in globals():
        raise Exception('config_nuke.py must define a value for %s.' % (key,))

nuke.pluginAddPath(API_DIR)
import zync

# Try to connect to ZYNC. If we can't that's fine for now, we'll try
# again later when the user tries to launch a job.
try:
    ZYNC = zync.Zync('nuke_plugin', API_KEY)
except:
    ZYNC = None

def generate_script_path(extra_name=None):
    """
    Returns a hash-embedded script path with /cloud_submit/ at the end
    of the path, for separation from user nuke scripts.
    """
    script_path = nuke.root().knob('name').getValue()
    script_dir = os.path.dirname(script_path)
    cloud_dir = "/".join([script_dir, 'cloud_submit'])

    if not os.path.exists(cloud_dir):
        os.makedirs(cloud_dir)

    script_name = os.path.basename(script_path)

    local_time = time.localtime()

    times = [local_time.tm_mon, local_time.tm_mday, local_time.tm_year,
             local_time.tm_hour, local_time.tm_min, local_time.tm_sec]
    timecode = ''.join(['%02d' % x for x in times])

    old_filename = re.split('.nk', script_name)[0]
    if extra_name:
        old_filename = '_'.join([old_filename, extra_name])
    to_hash = '_'.join([old_filename, timecode])
    hash = hashlib.md5(to_hash).hexdigest()[-6:]

    # filename will be something like: shotName_comp_v094_37aa20.nk
    new_filename = '_'.join([old_filename, hash]) + '.nk'

    return "/".join([cloud_dir, new_filename])

def get_dependent_nodes(root):
    """
    Returns a list of all of the root node's dependencies.
    Uses `nuke.dependencies()`. This will work with cyclical dependencies.
    """
    all_deps = set([root])
    all_deps.update(nuke.dependencies(list(all_deps)))

    seen = set()
    while True:
        diff = all_deps - seen
        to_add = nuke.dependencies(list(diff))
        all_deps.update(to_add)
        seen.update(diff)
        if len(diff) == 0:
            break

    return list(all_deps)

def select_deps(nodes):
    """
    Selects all of the dependent nodes for the given list of nodes.
    """
    for node in nodes:
        for node in get_dependent_nodes(node):
            node.setSelected(True)

def freeze_stereo_node(node, view=None):
    """
    Freezes the given stereo node, removes any expressions and creates a L/R
    """
    freeze_node(node)

    if view:
        file_name = node.knob('file').value()
        file_name = file_name.replace('%v', view.lower())
        file_name = file_name.replace('%V', view.upper())

        node.knob('file').setValue(file_name)

def freeze_node(node, view=None):
    """
    If the node has an expression, evaluate it so that the ZYNC can
    parse it. Also accounts for and retains frame number expressions.
    Should be idempotent.
    """
    file_knob = node.knob('file')
    if file_knob == None:
        return
    knob_value = file_knob.value()

    # if the file param has an open bracket, let's assume that it's an
    # expression:
    if '[' in knob_value:
        if node.Class() == 'Write':
            file_knob.setValue(nuke.filename(node))
        else:
            frozen_path = file_knob.evaluate()
            frozen_dir = os.path.split(frozen_path)[0]
            file_expr = os.path.split(knob_value)[-1]

            # sets the read node to be
            file_knob.setValue(os.path.join(frozen_dir, file_expr))

    if view:
        knob_value = knob_value.replace('%v', view.lower())
        knob_value = knob_value.replace('%V', view.upper())

        node.knob('file').setValue(knob_value)

def clear_nodes_by_name(names):
    """
    Removes nodes that match any of the names given.
    """
    nodes = (x for x in nuke.allNodes())
    for node in nodes:
        for name in names:
            if name in node.name():
                nuke.delete(node)

def clear_callbacks(node):
    """
    Call and clear the callbacks on the given node

    WARNING: only supports the create_write_dirs callback
    """
    names = ('beforeRender', 'beforeFrameRender', 'afterFrameRender', 'afterRender')
    knobs = (node.knob(x) for x in names)
    for knob in knobs:
        knob_val = knob.value()
        if 'create_write_dirs' in knob_val:
            try:
                create_write_dirs(node)
            except NameError:
                nuke.callbacks.create_write_dirs(node)
            knob.setValue('')

def clear_view(node):
    """
    Sets the node's 'views' knob to left, for maximum ZYNC compatibility.
    """
    if 'views' in node.knobs():
        node.knob('views').setValue('left')

def is_stereo(node):
    """
    If the node is stereo (i.e. has %v or %V in the path)
    """
    path = node.knob('file').value()
    return '%v' in path or '%V' in path

def is_valid(node):
    """
    Checks if the readnode is valid: if it has spaces or apostrophes in the
    name, it's invalid.
    """
    path = node.knob('file').value()
    return ' ' in path or "'" in path

def stereo_script():
    for read in (x for x in nuke.allNodes() if x.Class() == 'Read'):
        if is_stereo(read):
            return True
    for write in (x for x in nuke.allNodes() if x.Class() == 'Write'):
        if is_stereo(write):
            return True
        if 'left right' == write.knob('views').value():
            return True

    return False

def preflight(view=None):
    """
    Runs a preflight pass on the current nuke scene. Modify as needed.
    Returning True = success, False = failure
    """
    return True
        
class PasswordPrompt(nukescripts.panels.PythonPanel):
    """
    A hacked-in username/password prompt ui.
    """
    def __init__( self, title=None, user_default=None ):
        """
        Initialize the password prompt.
        """
        if not title:
            title = ''
        super(PasswordPrompt, self).__init__(title)

        self.__password = None

        self.username = nuke.String_Knob('username', 'Username: ')
        if user_default != None:
            self.username.setValue( user_default )
        try:
            self.password = nuke.Password_Knob('password', 'Password: ')
        except Exception:
            self.password = nuke.String_Knob('password', 'Password: ')
        self.addKnob(self.username)
        self.addKnob(self.password)

    def knobChanged(self, knob):
        if knob == self.password:
            self.__password = knob.value()
            knob.setValue(len(knob.value()) * '*')

    def get_password(self):
        """
        Function alias for showModalDialog
        """
        return self.showModalDialog()

    def showModalDialog(self):
        """
        Puts the PasswordPrompt in a modal dialog box and returns the inputs
        """
        result = super(PasswordPrompt, self).showModalDialog()
        if result:
            return (self.username.value(), self.__password)

class WriteChanges(object):
    """
    Given a script to save to, will save all of the changes made in the
    with block to the script, then undoes those changes in the current
    script. For example:

    with WriteChanges('/Volumes/af/show/omg/script.nk'):
        for node in nuke.allNodes():
            node.setYpos(100)

    FIXME: need to come up with a better name?
    """
    def __init__(self, script, save_func=None):
        """
        Initialize a WriteChanges context manager.
        Must provide a script to write to.

        If you provide a save_func, it will be called instead of the default
        `nuke.scriptSave`. The function must have the same interface as
        `nuke.scriptSave`. A possible alternative is `nuke.nodeCopy`.
        """
        self.undo = nuke.Undo
        self.__disabled = self.undo.disabled()
        self.script = script
        if save_func:
            self.save_func = save_func
        else:
            self.save_func = nuke.scriptSave

    def __enter__(self):
        """
        Enters the with block.
        NOTE: does not return an object, so assigment using 'as' doesn't work:
            `with WriteChanges('foo') as wc:`
        """
        if self.__disabled:
            self.undo.enable()

        self.undo.begin()

    def __exit__(self, type, value, traceback):
        """
        Exits the with block.

        First it calls the save_func, then undoes all actions in the with
        context, leaving the state of the current script untouched.
        """
        self.save_func(self.script)
        self.undo.cancel()
        if self.__disabled:
            self.undo.disable()

class ZyncRenderPanel(nukescripts.panels.PythonPanel):
    """
    The Zync Render Panel can be initialzed as a dialog or as a free floating 
    pane.

    Usage as a menu item:
        import zync_submit
        menu.addCommand('ZYNC Render', 'zync_submit.submit_dialog()')

    Usage as a panel:
        def addZyncPanel():
            zyncPanel = zync_submit.ZyncRenderPanel()
            return zyncPanel.addToPane()
        pane.addCommand('ZYNC Render', addZyncPanel)
        nukescripts.registerPanel('com.atomicfiction.zyncRender', addZyncPanel)
    """
    def __init__(self):
        """
        Initializes a ZyncRenderPanel
        """

        # make sure this isn't an unsaved script
        if nuke.root().name() == "Root" or nuke.modified():
            msg = "Please save your script before rendering on ZYNC."
            raise Exception(msg)

        nukescripts.panels.PythonPanel.__init__(self, 'ZYNC Render',
                                                'com.atomicfiction.zyncRender')


        if platform.system() in ('Windows', 'Microsoft'):
            self.usernameDefault = os.environ['USERNAME']
        else:
            self.usernameDefault = os.environ['USER']

        #GET WRITE NODES FROM FILE
        self.writeDict = dict()
        self.update_write_dict()

        # CREATE KNOBS

        self.project = nuke.String_Knob('project', 'ZYNC Project:')
        # use the API's get_project_name() to decide what the project
        # of the current Nuke script is.
        proj_response = ZYNC.get_project_name(nuke.root().name())
        if proj_response['code'] != 0:
            nuke.message(proj_response['response'])
            return
        self.project.setValue(proj_response['response'])

        self.upload_only = nuke.Boolean_Knob('upload_only', 'Upload Only')
        self.upload_only.setFlag(nuke.STARTLINE)

        self.parent_id = nuke.String_Knob('parent_id', 'Parent ID:')
        self.parent_id.setValue("")

        # create shotgun controls - they'll only be added if shotgun integration
        # is enabled.
        self.sg_create_version = nuke.Boolean_Knob('sg_create_version', 'Create Shotgun Version')
        self.sg_create_version.setFlag(nuke.STARTLINE)
        self.sg_create_version.setValue(False)
        self.sg_user = nuke.String_Knob('sg_user', 'Shotgun User:')
        self.sg_user.setFlag(nuke.STARTLINE)
        self.sg_project = nuke.String_Knob('sg_project', 'Shotgun Project:')
        self.sg_project.setFlag(nuke.STARTLINE)
        self.sg_shot = nuke.String_Knob('sg_shot', 'Shotgun Shot:')
        self.sg_shot.setFlag(nuke.STARTLINE)
        self.sg_version_code = nuke.String_Knob('sg_version_code', 'Version Code:')
        self.sg_version_code.setFlag(nuke.STARTLINE)
        script_base, ext = os.path.splitext(os.path.basename(nuke.root().knob('name').getValue()))
        self.sg_version_code.setValue( script_base )
        self.hideSGControls()

        self.priority = nuke.Int_Knob('priority', 'Job Priority:')
        self.priority.setDefaultValue((50,))

        self.num_slots = nuke.Int_Knob('num_slots', 'Num. Slots:')
        self.num_slots.setDefaultValue((1,))

        self.only_running = nuke.Boolean_Knob('only_running', 'Only Use Running Slots')

        type_list = []
        non_default = []
        for inst_type in ZYNC.INSTANCE_TYPES:
            if inst_type == zync.DEFAULT_INSTANCE_TYPE:
                type_list.append( '%s (%s)' % ( inst_type, ZYNC.INSTANCE_TYPES[inst_type]["description"] ) )
            else:
                non_default.append( '%s (%s)' % ( inst_type, ZYNC.INSTANCE_TYPES[inst_type]["description"] ) )
        for label in non_default:
            type_list.append( label ) 
        self.instance_type = nuke.Enumeration_Knob( 'instance_type', 'Type:', type_list )

        self.skip_check = nuke.Boolean_Knob('skip_check', 'Skip File Check')
        self.skip_check.setFlag(nuke.STARTLINE)

        self.notify_complete = nuke.Boolean_Knob('notify_complete', 'Notify When Complete')
        self.notify_complete.setFlag(nuke.STARTLINE)

        first = nuke.root().knob('first_frame').value()
        last = nuke.root().knob('last_frame').value()
        frange = '%d-%d' % (first, last)
        self.frange = nuke.String_Knob('frange', 'Frame Range:', frange)

        self.fstep = nuke.Int_Knob('fstep', 'Frame Step:')
        self.fstep.setDefaultValue((1,))

        selected_write_nodes = []
        for node in nuke.selectedNodes():
            if node.Class() == "Write":
                selected_write_nodes.append( node.name() )
        self.writeNodes = []
        colNum = 1
        for writeName in self.writeListNames:
            knob = nuke.Boolean_Knob( writeName, writeName )
            if len(selected_write_nodes) == 0:
                knob.setValue(True)
            elif writeName in selected_write_nodes:
                knob.setValue(True)
            else:
                knob.setValue(False)
            if colNum == 1:
                knob.setFlag( nuke.STARTLINE )
            if colNum > 3:
                colNum = 1
            else:
                colNum += 1
            knob.setTooltip( self.writeDict[writeName].knob("file").value() )
            self.writeNodes.append( knob )

        self.chunk_size = nuke.Int_Knob('chunk_size', 'Chunk Size:')
        self.chunk_size.setDefaultValue((10,))

        # ADD KNOBS
        self.addKnob(self.project)
        self.addKnob(self.parent_id)
        if "shotgun" in ZYNC.FEATURES and ZYNC.FEATURES["shotgun"] == 1: 
            self.addKnob(self.sg_create_version)
            self.addKnob(self.sg_user)
            self.addKnob(self.sg_project)
            self.addKnob(self.sg_shot)
            self.addKnob(self.sg_version_code)
        self.addKnob(self.upload_only)
        self.addKnob(self.priority)
        self.addKnob(self.num_slots)
        self.addKnob(self.only_running)
        self.addKnob(self.instance_type)
        self.addKnob(self.skip_check)
        self.addKnob(self.notify_complete)
        self.addKnob(self.frange)
        self.addKnob(self.fstep)
        for k in self.writeNodes:
            self.addKnob( k )
        self.addKnob(self.chunk_size)

        # collect render-specific knobs for iterating on later
        self.render_knobs = (self.num_slots, self.instance_type,
                             self.frange, self.fstep, self.chunk_size,
                             self.skip_check, self.only_running, self.priority,
                             self.parent_id)

        if "shotgun" in ZYNC.FEATURES and ZYNC.FEATURES["shotgun"] == 1: 
            height = 450
        else:
            height = 350
        self.setMinimumSize( 400, height )

    def update_write_dict(self):
        """ updates self.writeDict """
        wd = dict()
        for node in (x for x in nuke.allNodes() if x.Class() == 'Write'):
            # only put nodes that are not disabled in the write dict
            if not node.knob('disable').value():
                wd[node.name()] = node

        self.writeDict.update(wd)
        self.writeListNames = self.writeDict.keys()
        self.writeListNames.sort()

    def get_params(self):
        """
        Returns a dictionary of the job parameters from the submit render gui.
        """
        params = dict()
        params['num_instances'] = self.num_slots.value()

        for inst_type in ZYNC.INSTANCE_TYPES:
            if self.instance_type.value().startswith( inst_type ):
                params['instance_type'] = ZYNC.INSTANCE_TYPES[inst_type]["csp_label"]

        params['proj_name'] = self.project.value()
        params['frange'] = self.frange.value()
        params['step'] = self.fstep.value()
        params['chunk_size'] = self.chunk_size.value()
        params['upload_only'] = int(self.upload_only.value())
        params['priority'] = int(self.priority.value())
        parent = self.parent_id.value()
        if parent != None and parent != "":
            params['parent_id'] = int(self.parent_id.value())

        # get the opposite of the only_running knob
        params['start_new_slots'] = self.only_running.value() ^ 1

        params['skip_check'] = self.skip_check.value()
        params['notify_complete'] = self.notify_complete.value()

        if "shotgun" in ZYNC.FEATURES and ZYNC.FEATURES["shotgun"] == 1 and self.sg_create_version.value():
            params['sg_user'] = self.sg_user.value()
            params['sg_project'] = self.sg_project.value()
            params['sg_shot'] = self.sg_shot.value()
            params['sg_version_code'] = self.sg_version_code.value()

        return params

    def submit(self, username=None, password=None):
        """
        Does the work to submit the current Nuke script to ZYNC,
        given that the parameters on the dialog are set.

        TODO: factor the bulk of this out of the ZyncRenderPanel object
        """

        if self.skip_check.value():
            skip_answer = nuke.ask( "You've asked ZYNC to skip the file check for this job. If you've added new files to your script this job WILL error. Your nuke script will still be uploaded. Are you sure you want to continue?" )
            if not skip_answer:
                return

        if not username and not password:
            if hasattr(nuke, 'zync_creds') and nuke.zync_creds.get('user'):
                # get username and password
                user = nuke.zync_creds.get('user')
                pw = nuke.zync_creds.get('pw')
            else:
                # prompt username and password:
                msg = 'Enter your ZYNC Render Username/Password'
                pw_prompt = PasswordPrompt( title=msg, user_default=self.usernameDefault )
                try:
                    user, pw = pw_prompt.get_password()
                except Exception:
                    msg = 'You must have a ZYNC account to submit!'
                    raise Exception(msg)
                else:
                    nuke.zync_creds = dict(user=user, pw=pw)

        #selected_write = self.writeListNames[int(self.writeNode.getValue())]
        selected_write_names = []
        selected_write_nodes = []
        for k in self.writeNodes:
            if k.value():
                selected_write_names.append( k.label() )
                selected_write_nodes.append( nuke.toNode( k.label() ) )

        active_viewer = nuke.activeViewer()
        if active_viewer:
            viewer_input = active_viewer.activeInput()
            if viewer_input == None:
                viewed_node = None
            else:
                viewed_node = active_viewer.node().input(viewer_input)
        else:
            viewer_input, viewed_node = None, None

        new_script = generate_script_path()
        with WriteChanges(new_script):
            # The WriteChanges context manager allows us to save the
            # changes to the current session to the given script, leaving
            # the current session unchanged once the context manager is
            # exited.
            preflight_result = preflight()

            #
            #   Nuke 7 broke its own undo() functionality, so this will only
            #   run on Nuke 6 and earlier.
            #
            if nuke.NUKE_VERSION_MAJOR < 7:
                #
                #   Remove all nodes that aren't connected to the Write
                #   nodes being rendered.
                #
                select_deps( selected_write_nodes )
                for node in nuke.allNodes():
                    if node.isSelected():
                        node.setSelected(False)
                    else:
                        node.setSelected(True)
                nuke.nodeDelete()
                #
                #   Freeze expressions on all nodes.
                #
                for node in nuke.allNodes():
                    freeze_node( node )
            
        if not preflight_result:
            return

        # reconnect the viewer
        if viewer_input != None and viewed_node != None:
            nuke.connectViewer(viewer_input, viewed_node)

        # exec before render
        #nuke.callbacks.beforeRenders

        try:
            ZYNC.login( username=user, password=pw )
        except zync.ZyncAuthenticationError as e:
            nuke.zync_creds['user'] = None
            nuke.zync_creds['pw'] = None
            raise Exception('ZYNC Login Failed:\n\n%s' % (str(e),))

        try:
            ZYNC.submit_job('nuke', new_script, ','.join( selected_write_names ), self.get_params())
        except zync.ZyncPreflightError as e:
            raise Exception('Preflight Check Failed:\n\n%s' % (str(e),))

        nuke.message('Job submitted to ZYNC.')

    def addToPane(self):
        """
        Does some work to make the ZyncRenderPanel work as a persistent pane:
            * adds persistent Username/Password fields
            * adds a submit button
            * adds an update UI callback to update the Write node Enum knob
        """
        self.user = nuke.String_Knob('user', 'Username')
        self.password = nuke.Password_Knob('password', 'Password')

        self.submit = nuke.PyScript_Knob('submit', 'Submit')
        self.submit.setFlag(nuke.STARTLINE)

        self.addKnob(self.user)
        self.addKnob(self.password)
        self.addKnob(self.submit)
        super(ZyncRenderPanel, self).addToPane()

        nuke.callbacks.addUpdateUI(self.update_write_dict, nodeClass='Write')

    def knobChanged(self, knob):
        """
        Handles knob callbacks
        """
        # if we're in pane mode and the submit button has been called:
        if hasattr(self, 'sc') and knob is self.submit:
            user = self.user.value()
            pw = self.password.value()
            if not user or not pw:
                return None
            self.submit(user, pw)
        elif knob is self.upload_only:
            checked = self.upload_only.value()
            for rk in self.render_knobs:
                rk.setEnabled(not checked)
            for k in self.writeNodes:
                k.setEnabled(not checked)
        elif knob is self.sg_create_version:
            checked = self.sg_create_version.value()
            if checked:
                self.showSGControls()
            else:
                self.hideSGControls()

    def showModalDialog(self):
        """
        Shows the Zync Submit dialog and does the work to submit it.
        """
        result = nukescripts.panels.PythonPanel.showModalDialog(self)
        if result:
            self.submit()

    def hideSGControls(self):
        self.sg_user.setEnabled(False)
        self.sg_project.setEnabled(False)
        self.sg_shot.setEnabled(False)
        self.sg_version_code.setEnabled(False)
    def showSGControls(self):
        self.sg_user.setEnabled(True)
        self.sg_project.setEnabled(True)
        self.sg_shot.setEnabled(True)
        self.sg_version_code.setEnabled(True)
    

def submit_dialog():
    global ZYNC
    if ZYNC == None:
        try:
            ZYNC = zync.Zync('nuke_plugin', API_KEY)
        except Exception as e:
            nuke.message('Couldn\'t connect to ZYNC. Are you connected to the internet?')
            return
    ZyncRenderPanel().showModalDialog()
