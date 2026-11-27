"""Bind an archive exchange to the current protected title and Steam selection."""
from copy import deepcopy
from pathlib import Path

from checkpoint_transfer import _selection,send_archive,receive_archive
from coop_checkpoint import HostArchive
from readonly_save_control import read_active_guard,read_connected_lobby
from save_protection import active_save_identity,storage_guard_active


class ArchiveTransferBinding:
    def __init__(self,data,pipe,solo,selection,role):
        if role not in (b'H',b'G'):
            raise ValueError('Invalid checkpoint archive role')
        self.data,self.pipe,self.solo,self.role=Path(data),pipe,Path(solo),role.decode('ascii')
        self.selection=_selection(selection)
        self.scope,lobby=read_connected_lobby(self.data)
        self.revision=lobby['revision']
        self.choice=deepcopy(lobby['settings'].get('coop_checkpoint'))
        if (not isinstance(self.choice,dict)
                or set(self.choice)!={'namespace','digest','scenario','difficulty','saved_at'}
                or any(self.choice.get(key)!=value for key,value in self.selection.items())
                or type(self.choice['scenario']) is not int or self.choice['scenario'] not in (0,1)
                or type(self.choice['difficulty']) is not int or self.choice['difficulty'] not in (0,1,2)
                or not isinstance(self.choice['saved_at'],str) or not 0<len(self.choice['saved_at'])<=32):
            raise ValueError('A complete selected checkpoint is required')
        guard=read_active_guard(self.data,protected=True,runtime_directory=self.solo)
        self.protection=deepcopy(guard['protection'])
        self.guard_run=guard.get('guard_run_id')
        self.directory_identity=active_save_identity(pipe,self.solo)
        self.confirm()

    def confirm(self):
        """Raise on loss; success never loads, writes, or releases a campaign."""
        guard=read_active_guard(self.data,protected=True,runtime_directory=self.solo)
        scope,lobby=read_connected_lobby(self.data)
        if (scope!=self.scope or scope['role']!=self.role or scope['game_pid']!=self.pipe.game_pid
                or self.protection['game_pid']!=self.pipe.game_pid or lobby['revision']!=self.revision
                or lobby['settings'].get('coop_checkpoint')!=self.choice or lobby['save_slot'] is not None
                or 'new_game' in lobby or 'save_ref' in lobby
                or guard.get('protection')!=self.protection or guard.get('guard_run_id')!=self.guard_run
                or not isinstance(self.guard_run,str) or not self.guard_run
                or guard.get('runtime_protection') is not True or guard.get('in_title') is not True
                or guard.get('has_player') is not False or guard.get('loading_flow') is not False or guard.get('busy') is not False
                or type(guard.get('allowed_load_calls')) is not int or guard['allowed_load_calls']!=0
                or type(guard.get('denied_loads')) is not int or guard['denied_loads']!=0
                or guard.get('writes') not in (None,{})
                or self.pipe.lobby_status()!=('owned' if self.role=='H' else 'joined')
                or self.pipe.membership_revision()!=scope['membership']['revision']
                or self.pipe.cloud_status() not in ('cloud-app-disabled','cloud-account-disabled')
                or self.pipe.request(b'peer-status',pipe_name=self.pipe.lobby_name) not in
                    (b'peer-ready',b'peer-ping-pending',b'peer-round-trip-verified')
                or not storage_guard_active(self.solo)
                or active_save_identity(self.pipe,self.solo)!=self.directory_identity):
            raise ValueError('Checkpoint transfer title, selection, protection or Steam binding changed')

    def exchange(self,request_id,*,stop=None,timeout=120):
        """Use only this binding's active profile and selected immutable generation."""
        self.confirm()
        common=(self.data,self.pipe,self.scope['session_id'],request_id)
        if self.role=='H':
            archive=HostArchive(self.solo,self.selection['namespace'])
            return send_archive(*common,archive,self.selection['digest'],self.confirm,stop=stop,timeout=timeout)
        return receive_archive(*common,self.solo,self.selection,self.confirm,stop=stop,timeout=timeout)
