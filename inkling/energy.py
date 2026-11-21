#!/usr/bin/env python3
"""GPU-rail energy for a time window on the four Sparks, from the 1 Hz `nvidia-smi power.draw` logs.

Each node logs `timestamp, power W, temp, sm clock` (node local time, CET = UTC+1) to ~/swarm-lab/inkling/power.csv.
Energy = trapezoidal integral of power over [start, end] per node, summed over nodes. GPU rail only: CPU, memory
controller, NIC, SSD, fans and PSU losses are not measured, so this is a lower bound on wall-socket energy.

usage: energy.py START_UTC END_UTC [--nodes 01 02 03 04]   (ISO times, e.g. 2026-11-21T02:00:00Z)
"""
import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone

LOCAL = timezone(timedelta(hours=1))


def samples(node):
    raw = subprocess.check_output(['ssh', '-o', 'BatchMode=yes', f'Spark_{node}', 'cat ~/swarm-lab/inkling/power.csv'],
                                  text=True)
    out = []
    for line in raw.splitlines():
        parts = [p.strip() for p in line.split(',')]
        try:
            t = datetime.strptime(parts[0], '%Y/%m/%d %H:%M:%S.%f').replace(tzinfo=LOCAL)
            out.append((t.timestamp(), float(parts[1].split()[0])))
        except (ValueError, IndexError):
            continue
    return out


def integrate(points, t0, t1):
    pts = [(t, w) for t, w in points if t0 <= t <= t1]
    if len(pts) < 2:
        return None, 0
    joules = sum((b[0] - a[0]) * (a[1] + b[1]) / 2 for a, b in zip(pts, pts[1:]) if b[0] - a[0] < 10)
    covered = sum(b[0] - a[0] for a, b in zip(pts, pts[1:]) if b[0] - a[0] < 10)
    return joules * (t1 - t0) / covered if covered else None, covered / (t1 - t0)


def window(start, end, nodes=('01', '02', '03', '04')):
    t0 = datetime.fromisoformat(start.replace('Z', '+00:00')).timestamp()
    t1 = datetime.fromisoformat(end.replace('Z', '+00:00')).timestamp()
    per = {}
    for n in nodes:
        j, cov = integrate(samples(n), t0, t1)
        per[n] = dict(joules=round(j) if j else None, coverage=round(cov, 3),
                      mean_w=round(j / (t1 - t0), 1) if j else None)
    total = sum(v['joules'] or 0 for v in per.values())
    return dict(start=start, end=end, seconds=round(t1 - t0), nodes=per, total_joules=total,
                total_wh=round(total / 3600, 2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('start')
    p.add_argument('end')
    p.add_argument('--nodes', nargs='+', default=['01', '02', '03', '04'])
    a = p.parse_args()
    print(json.dumps(window(a.start, a.end, a.nodes), indent=1))


if __name__ == '__main__':
    main()
