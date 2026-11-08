"""Subprocess fixture: real durable journal, symlink and abrupt process termination."""
import os
from pathlib import Path
import sys
from engine import deploy
from host import Host, atomic_json
from manifest import make_manifest


class DiskHost(Host):
    def __init__(self, root, stage):
        self.root, self.stage = Path(root), stage
        self.journal = {}
        self.baseline = {'manifest': make_manifest(self.root/'source.jar','a'*40,'1','1')}
        self.candidate = {'manifest': make_manifest(self.root/'source.jar','b'*40,'2','1')}
        for release in [self.baseline,self.candidate]: self.release_path(release).mkdir(parents=True)
        atomic_json(self.root/'baseline.json',self.baseline)
        (self.root/'runs').mkdir()
        (self.root/'current').symlink_to(self.release_path(self.baseline),target_is_directory=True)
    def stop(self, stage):
        if self.stage == stage: os._exit(77)
    def prepare(self, request): return self.candidate
    def preflight(self, previous, candidate): pass
    def identity(self): return 'fixture'
    def record(self, request, status):
        super().record(request,status); self.stop(status)
    def activate(self, release):
        super().activate(release); self.stop('activate')
    def restart(self): self.stop('restart')
    def verify(self, release, old_identity): self.stop('verify')
    def commit(self, release):
        super().commit(release); self.stop('commit')


if __name__ == '__main__':
    deploy(DiskHost(sys.argv[1],sys.argv[2]),{'run_key':'2-1'})
