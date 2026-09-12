#!/usr/bin/env python3
"""Prepay bounded web egress blocks; never refund a block after a crash.

Only API-C host TCP responses on 80/443 are metered. This is not the complete
cloud bill: installation traffic and SMS have their own reservations/caps.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile

ROOT = Path('/var/lib/noteai/public-website-budget')
TABLE = 'noteai_public_budget'
LIMIT = 10 * 1024**3  # RMB22 reserved: packet/segmentation and billing margin included.
BLOCK = 64 * 1024**2


def nft(*args, input=None):
    return subprocess.run(['/usr/sbin/nft', *args], input=input, text=True,
                          capture_output=True, timeout=10, check=True)


def table_exists():
    data = json.loads(nft('-j', 'list', 'tables').stdout)
    return any(x.get('table', {}).get('family') == 'inet' and
               x.get('table', {}).get('name') == TABLE for x in data['nftables'])


def install_quota(size):
    # One nft transaction replaces ONLY this task's table, with no open interval.
    prefix = f'delete table inet {TABLE}\n' if table_exists() else ''
    nft('-f', '-', input=prefix + f'''table inet {TABLE} {{
      quota web {{ over {int(size)} bytes; }}
      chain output {{
        type filter hook output priority -10; policy accept;
        oifname != "lo" ip saddr 10.42.10.44 tcp sport {{ 80, 443 }} quota name "web" drop
      }}
    }}\n''')


def remaining_quota():
    if not table_exists():
        return 0  # Boot or lost kernel state: old prepaid block is not refunded.
    data = json.loads(nft('-j', 'list', 'quota', 'inet', TABLE, 'web').stdout)
    rows = [x['quota'] for x in data['nftables'] if 'quota' in x]
    if len(rows) != 1 or rows[0].get('inv') is not True:
        raise ValueError('unexpected web quota')
    size, used = rows[0]['bytes'], rows[0]['used']
    if type(size) is not int or type(used) is not int or not 0 <= size <= BLOCK or used < 0:
        raise ValueError('invalid web quota counters')
    return max(0, size - used)


def save_state(path, state):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.budget-')
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(state, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def tick(root=ROOT, initialize=False):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / 'budget.json'
        try:
            if initialize:
                if path.exists():
                    raise ValueError('budget already initialized; never reset')
                save_state(path, {'limit_bytes': LIMIT, 'reserved_bytes': 0})
            state = json.loads(path.read_text())
            reserved = state['reserved_bytes']
            if (state.get('limit_bytes') != LIMIT or type(reserved) is not int
                    or not 0 <= reserved <= LIMIT or reserved % BLOCK):
                raise ValueError('invalid persistent budget')
            remaining = remaining_quota()
            if remaining > BLOCK // 8 or (reserved == LIMIT and remaining > 0):
                return {'status': 'ACTIVE', 'reserved_bytes': reserved}
            if reserved == LIMIT:
                install_quota(0)
                return {'status': 'EXHAUSTED', 'reserved_bytes': reserved}
            # Persist the entire new block BEFORE making any of it available.
            state['reserved_bytes'] = reserved + BLOCK
            save_state(path, state)
            install_quota(BLOCK)
            return {'status': 'ACTIVE', 'reserved_bytes': state['reserved_bytes']}
        except Exception:
            install_quota(0)
            raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--initialize', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0 or socket.gethostname() != 'noteai-prod-api-c':
        raise SystemExit('web budget is restricted to API-C root')
    try:
        result = tick(initialize=args.initialize)
        print(json.dumps(result, sort_keys=True))
        if result['status'] != 'ACTIVE':
            subprocess.run(['systemctl', '--no-block', 'stop', 'nginx.service'],
                           check=True, timeout=10, capture_output=True)
            raise SystemExit(2)
    except Exception as exc:
        # Never print arbitrary command output or private paths from exceptions.
        print(json.dumps({'status': 'BLOCKED', 'error_type': type(exc).__name__}))
        # If kernel enforcement itself is unavailable, stop only this webserver.
        # --no-block also works when called during nginx's own ExecStartPre.
        subprocess.run(['systemctl', '--no-block', 'stop', 'nginx.service'],
                       check=True, timeout=10, capture_output=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
