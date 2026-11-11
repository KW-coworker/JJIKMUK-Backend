"""Inspect/grow only the approved backend root EBS; preserve catalog records."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

VOLUME = 'vol0bc5ebc80e1f852c6'
GIB = 1024**3
ROOT = Path('/var/lib/jjikmuk-operations')
RECEIPT = ROOT / 'root-volume-grow-20261111.json'
UNITS = ('jjikmuk-backend.service', 'food-chatbot-team.service', 'nginx.service')


def need(ok, code):
    if not ok:
        raise ValueError(code)


def command(args, timeout=30):
    p = subprocess.run(args, capture_output=True, timeout=timeout, cwd='/',
                       env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})
    need(p.returncode == 0 and len(p.stdout) < 65536, 'ROOT_SPACE_COMMAND_FAILED')
    return p.stdout.decode()


def select_root(mount, tree, resolved, partition, start):
    mounts = mount.get('filesystems', [])
    need(len(mounts) == 1 and mounts[0]['target'] == '/' and
         mounts[0]['fstype'] in ('ext4', 'xfs') and
         'rw' in mounts[0]['options'].split(','), 'ROOT_SPACE_FILESYSTEM')
    need(re.fullmatch(r'/dev/nvme[0-9]+n[0-9]+p[0-9]+', resolved), 'ROOT_SPACE_DEVICE')
    found = [(d, p) for d in tree.get('blockdevices', []) for p in d.get('children', [])
             if p.get('name') == resolved]
    need(len(found) == 1, 'ROOT_SPACE_MAPPING')
    disk, part = found[0]
    need(disk['type'] == 'disk' and disk['serial'] == VOLUME and disk['ro'] is False and
         re.fullmatch(r'/dev/nvme[0-9]+n[0-9]+', disk['name']), 'ROOT_SPACE_VOLUME')
    need(part['type'] == 'part' and part['pkname'] == disk['name'] and
         part['maj:min'] == mounts[0]['maj:min'] and
         part['fstype'] == mounts[0]['fstype'] and part.get('mountpoints') == ['/'] and
         part['ro'] is False and not part.get('children') and
         type(partition) is int and 1 <= partition <= 128 and
         resolved == disk['name'] + 'p' + str(partition), 'ROOT_SPACE_PARTITION')
    # Separate boot/EFI partitions may occupy more than 1GiB before root.
    # The start is preserved exactly; growpart may only extend its end.
    need(type(start) is int and 0 < start < 2*GIB, 'ROOT_SPACE_PARTITION_OFFSET')
    need(type(disk['size']) is int and disk['size'] in (20*GIB, 30*GIB), 'ROOT_SPACE_DISK_BYTES')
    need(type(part['size']) is int and 18*GIB < part['size'] <= disk['size']-start,
         'ROOT_SPACE_PARTITION_BYTES')
    need(all(isinstance(part.get(k), str) and part[k] for k in ('uuid', 'partuuid')),
         'ROOT_SPACE_FILESYSTEM_UUID')
    return {'disk': disk['name'], 'partition': resolved, 'number': partition,
            'disk_bytes': disk['size'], 'partition_bytes': part['size'], 'start': start,
            'fstype': part['fstype'], 'uuid': part['uuid'], 'partuuid': part['partuuid']}


def observe():
    mount = json.loads(command(['/usr/bin/findmnt', '--json', '--mountpoint', '/',
                                '--output', 'TARGET,SOURCE,FSTYPE,OPTIONS,MAJ:MIN']))
    need(len(mount.get('filesystems', [])) == 1, 'ROOT_SPACE_MOUNT')
    source = mount['filesystems'][0]['source']
    need(re.fullmatch(r'/dev/[a-zA-Z0-9/._-]+', source), 'ROOT_SPACE_SOURCE')
    tree = json.loads(command(['/usr/bin/lsblk', '--json', '--bytes', '--paths', '--output',
                               'NAME,TYPE,SIZE,PKNAME,FSTYPE,MOUNTPOINTS,SERIAL,RO,UUID,PARTUUID,MAJ:MIN']))
    device_id = mount['filesystems'][0]['maj:min']
    need(re.fullmatch('[0-9]+:[0-9]+', device_id), 'ROOT_SPACE_KERNEL_DEVICE')
    # /dev/root may be a kernel mount alias with no corresponding symlink.
    matches = [p for d in tree.get('blockdevices', []) for p in d.get('children', [])
               if p.get('maj:min') == device_id]
    need(len(matches) == 1, 'ROOT_SPACE_KERNEL_MAPPING')
    resolved = matches[0]['name']
    need(re.fullmatch(r'/dev/nvme[0-9]+n[0-9]+p[0-9]+', resolved), 'ROOT_SPACE_DEVICE')
    sysblock = Path('/sys/class/block') / Path(resolved).name
    number = int((sysblock/'partition').read_text().strip())
    start = int((sysblock/'start').read_text().strip()) * 512
    result = select_root(mount, tree, resolved, number, start)
    usage = shutil.disk_usage('/')
    result.update(free_bytes=usage.free, filesystem_bytes=usage.total)
    return result


def identities():
    result = {}
    for unit in UNITS:
        raw = command(['/usr/bin/systemctl', 'show', unit, '--no-pager',
                       '--property=ActiveState,MainPID,InvocationID'])
        fields = dict(line.split('=', 1) for line in raw.splitlines())
        need(fields['ActiveState'] == 'active' and fields['MainPID'].isdigit() and
             int(fields['MainPID']) > 0 and re.fullmatch('[a-f0-9]{32}', fields['InvocationID']),
             'ROOT_SPACE_SERVICE_NOT_ACTIVE')
        result[unit] = fields
    return result


def append_record(value):
    # This separate record never overwrites the catalog coordinator or journals.
    with RECEIPT.open('a', encoding='utf-8') as f:
        f.write(json.dumps(value, sort_keys=True)+'\n'); f.flush(); os.fsync(f.fileno())


def tool(name):
    from coordination import secure
    path = shutil.which(name, path='/usr/sbin:/usr/bin:/sbin:/bin')
    need(path is not None, 'ROOT_SPACE_TOOL_MISSING')
    real = Path(path).resolve(strict=True)
    for p in (real, *real.parents):
        secure(p)
    return str(real)


def same_identity(before, after):
    keys = ('disk', 'partition', 'number', 'disk_bytes', 'start', 'fstype', 'uuid', 'partuuid')
    need(all(before[k] == after[k] for k in keys), 'ROOT_SPACE_IDENTITY_CHANGED')


def expand(before, read=observe, run=command, tools=tool, record=append_record):
    need(before['disk_bytes'] == 30*GIB, 'ROOT_SPACE_EBS_NOT_30GIB')
    need(before['free_bytes'] > 2*GIB, 'ROOT_SPACE_EXISTING_RESERVE')
    grow = tools('growpart')
    resize = tools('resize2fs' if before['fstype'] == 'ext4' else 'xfs_growfs')
    if before['partition_bytes'] + before['start'] < before['disk_bytes'] - 8*1024**2:
        run([grow, '--dry-run', before['disk'], str(before['number'])])
        record({'step': 'GROWPART_INTENT'})
        run([grow, before['disk'], str(before['number'])], 90)
    partitioned = read(); same_identity(before, partitioned)
    need(partitioned['partition_bytes'] >= before['partition_bytes'] and
         partitioned['partition_bytes'] + partitioned['start'] >= before['disk_bytes'] - 8*1024**2,
         'ROOT_SPACE_PARTITION_NOT_EXPANDED')
    record({'step': 'FILESYSTEM_GROW_INTENT'})
    run([resize, before['partition']] if before['fstype'] == 'ext4' else [resize, '-d', '/'], 180)
    after = read(); same_identity(before, after)
    need(after['partition_bytes'] == partitioned['partition_bytes'] and
         after['filesystem_bytes']*100 >= after['partition_bytes']*95 and after['free_bytes'] >= 6*GIB and
         after['free_bytes'] >= before['free_bytes'], 'ROOT_SPACE_CAPACITY_NOT_READY')
    return after


def expected_coordinator():
    base = 'a5291163ee0a456b85366e6075d8fce6:42984831949:'
    apply = {'status': 'MUTATION_INTENT', 'component': 'db',
             'operation_id': hashlib.sha256((base+'apply').encode()).hexdigest()}
    return {'status': 'ROLLED_BACK', 'component': 'db',
            'operation_id': hashlib.sha256((base+'recover').encode()).hexdigest(),
            'recovery_of': hashlib.sha256(json.dumps(apply, sort_keys=True).encode()).hexdigest()}


def main(mode):
    import fcntl
    from coordination import secure
    need(mode in ('inspect', 'grow') and os.geteuid() == 0, 'ROOT_SPACE_ENTRY')
    for path in (ROOT, *ROOT.parents, ROOT/'host.lock', ROOT/'state.json'):
        secure(path)
    with (ROOT/'host.lock').open('r+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = (ROOT/'state.json').read_bytes()
        need(len(state) < 4096 and json.loads(state) == expected_coordinator(), 'ROOT_SPACE_COORDINATOR')
        services = identities(); before = observe()
        tool('growpart'); tool('resize2fs' if before['fstype'] == 'ext4' else 'xfs_growfs')
        after = before
        if mode == 'grow':
            need(before['disk_bytes'] == 30*GIB, 'ROOT_SPACE_EBS_NOT_30GIB')
            fd = os.open(RECEIPT, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            append_record({'step': 'STARTED', 'observed_epoch': int(time.time()), 'before': before})
            fd = os.open(ROOT, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
            after = expand(before)
        need(identities() == services and (ROOT/'state.json').read_bytes() == state,
             'ROOT_SPACE_SERVICES_OR_COORDINATOR_CHANGED')
        if mode == 'grow': append_record({'step': 'VERIFIED', 'after': after})
        return {'status': 'VERIFIED', 'checks': {'exact_root_volume': True,
                'services_unchanged': True, 'catalog_coordinator_unchanged': True, 'growth_tools_present': True,
                'capacity_ready': after['disk_bytes'] == 30*GIB and
                                  after['partition_bytes']+after['start'] >= after['disk_bytes']-8*1024**2 and
                                  after['filesystem_bytes']*100 >= after['partition_bytes']*95 and after['free_bytes'] >= 6*GIB},
                'counts': {k: after[k] for k in ('disk_bytes', 'partition_bytes', 'filesystem_bytes', 'free_bytes')}
                          | {'partition_start_bytes': after['start']}
                          | {'observed_epoch': int(time.time())},
                'codes': ['ROOT_FS_'+after['fstype'].upper(), 'ROOT_VOLUME_'+VOLUME.upper()]}


def execute_under_hold(api, ctx, mode):
    from catalog_reapply_contract import REQUEST, LAST_RUN
    from catalog_capacity import ec2_client, root_volume
    from maintenance_gate import Gate
    from run import execute
    from connection import HOSTS, canonical, sha
    need(mode in ('inspect', 'grow') and ctx['request_id'] == REQUEST, 'ROOT_SPACE_REQUEST')
    gate, _ = Gate(api['s3']).read()
    need(gate is not None and gate['state'] == 'WORKING' and gate['request_id'] == REQUEST and
         gate['run_id'] == LAST_RUN, 'ROOT_SPACE_MAINTENANCE_HOLD')
    metadata = root_volume(ec2_client())
    need('HOST_ROOT_'+VOLUME.replace('vol','VOL_').upper() in metadata['codes'], 'ROOT_SPACE_VOLUME')
    if mode == 'grow':
        need(metadata['counts']['host_root_allocated_gib'] == 30, 'ROOT_SPACE_EBS_NOT_30GIB')
    selected = plan(mode)
    path = Path(__file__).parent/'plans'/f'catalog-root-space-{mode}-v2.json'
    need(json.loads(path.read_bytes()) == selected, 'ROOT_SPACE_PLAN_CHANGED')
    outcome = execute(api, ctx, selected, sha(path.read_bytes()), HOSTS['backend'])
    need(outcome['success'] is True, 'ROOT_SPACE_OPERATION_FAILED_KEEP_RECORDS')
    report = json.loads(Path('operation-results/result.json').read_bytes())['report']
    need(report['status'] == 'VERIFIED', 'ROOT_SPACE_REPORT')
    if mode == 'grow': need(all(report['checks'].values()), 'ROOT_SPACE_POSTCHECK')
    return report


def plan(mode):
    import base64
    source = Path(__file__).read_bytes()
    script = ('import base64,hashlib,json,os,sys\nfrom pathlib import Path\n'
              "root=Path('/opt/jjikmuk-cd/bin')\n"
              "for p in (root,*root.parents):\n s=p.lstat();assert not p.is_symlink() and s.st_uid==0 and not s.st_mode&0o022\n"
              "assert os.geteuid()==0 and sys.flags.isolated and sys.flags.no_site\n"
              "sys.dont_write_bytecode=True;sys.path.insert(0,str(root))\n"
              f'raw=base64.b64decode({base64.b64encode(source).decode()!r},validate=True)\n'
              f'assert hashlib.sha256(raw).hexdigest()=={hashlib.sha256(source).hexdigest()!r}\n'
              "namespace={'__name__':'reviewed_root_space'}\nexec(compile(raw,'<reviewed-root-space>','exec'),namespace)\n"
              'try:\n'+f" print(json.dumps(namespace['main']({mode!r})))\n"
              "except Exception as e:\n code=str(e) if isinstance(e,ValueError) and __import__('re').fullmatch('[A-Z][A-Z0-9_]{0,79}',str(e)) else 'ROOT_SPACE_FAILED_KEEP_RECORDS'\n print(json.dumps({'status':'STOPPED','codes':[code]}));sys.exit(1)\n")
    return {'format': 1, 'component': 'backend', 'operation': 'inspect' if mode == 'inspect' else 'install',
            'approval_id': 'USER_BACKEND_ROOT_30GIB_20261111', 'approved': True,
            'document': {'schemaVersion': '2.2', 'parameters': {},
                'description': 'Fixed approved backend root volume '+mode,
                'mainSteps': [{'action': 'aws:runShellScript', 'name': 'report', 'inputs': {
                    'timeoutSeconds': '420', 'runCommand': ["/usr/bin/python3.12 -I -S -B - <<'ROOT_SPACE_FIXED'\n"+script+'\nROOT_SPACE_FIXED']}}]}}
