"""Prove stopped processes, including a retained systemd failure result."""
from pathlib import Path
from manifest import require

FIELDS={'ActiveState','SubState','MainPID','ControlPID','ControlGroup','Job'}


def snapshot(systemctl,unit):
    raw=systemctl('show',unit,'--all','--property='+','.join(sorted(FIELDS)))
    rows=[line.split('=',1) for line in raw.splitlines()]
    require(all(len(r)==2 for r in rows) and len(rows)==len(FIELDS)
            and {r[0] for r in rows}==FIELDS,'SERVICE_STATE_FORMAT')
    return dict(rows)


def stopped(units,systemctl,*,cgroup_root=Path('/sys/fs/cgroup')):
    observed={}
    for unit in units:
        state=snapshot(systemctl,unit)
        require((state['ActiveState'],state['SubState']) in {('inactive','dead'),('failed','failed')}
                and state['MainPID']=='0' and state['ControlPID']=='0' and state['Job']=='',
                'SERVICES_NOT_STOPPED')
        group=state['ControlGroup']
        if group:
            require(group.startswith('/system.slice/') and '..' not in group,'SERVICE_CGROUP_PATH')
            directory=cgroup_root/group.lstrip('/')
            if directory.exists():
                require(all(not p.read_text().strip() for p in directory.rglob('cgroup.procs')),
                        'SERVICE_CGROUP_NOT_EMPTY')
        observed[unit]=state
    require(all(snapshot(systemctl,unit)==state for unit,state in observed.items()),
            'SERVICE_STATE_CHANGED_DURING_CHECK')
    return observed
