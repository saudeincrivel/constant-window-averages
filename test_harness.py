#!/usr/bin/env python3
"""
Test harness for AverageCompute.

Key insight: the C++ implementation's head only moves forward.
  - add_metric(name, ts, val) rejects ts if ts <= head[name] - window,
    and advances head[name] = max(head[name], ts).
  - get_average(name, now) advances head[name] = max(head[name], now),
    then returns avg over [head - window + 1, head].

So calling GET(name, now) with now < head[name] returns the average
for the OLD head's window, not [now-w+1, now]. This is BY DESIGN for
a streaming/monotonic-time system.

The brute-force below replicates this exact semantic.
"""

import random
import subprocess
import sys


# ---------------------------------------------------------------------------
# Brute-force reference — mirrors C++ semantics exactly
# ---------------------------------------------------------------------------
class BruteForce:
    def __init__(self, window):
        self.window = window
        self.head = {}
        self.data = []

    def add_metric(self, name, timestamp, value):
        h = self.head.get(name, -1)
        if h != -1 and timestamp <= h - self.window:
            return
        if timestamp > h:
            self.head[name] = timestamp
        self.data.append((name, timestamp, value))

    def get_average(self, name, now):
        h = self.head.get(name, -1)
        effective_head = max(h, now)
        self.head[name] = effective_head
        lo = effective_head - self.window + 1
        hi = effective_head
        total = 0
        count = 0
        for n, t, v in self.data:
            if n == name and lo <= t <= hi:
                total += v
                count += 1
        if count == 0:
            return 0.0
        return total / count


# ---------------------------------------------------------------------------
# Test-case generators
# ---------------------------------------------------------------------------
def gen_random(
    seed,
    window_range=(1, 30),
    num_ops_range=(1, 300),
    num_events=5,
    ts_range=(0, 80),
    val_range=(-10000, 10000),
    get_ratio=0.3,
):
    random.seed(seed)
    w = random.randint(*window_range)
    n = random.randint(*num_ops_range)
    ops = []
    for _ in range(n):
        name = random.randint(0, num_events - 1)
        if random.random() < get_ratio:
            ops.append(("GET", name, random.randint(*ts_range)))
        else:
            ops.append(
                ("ADD", name, random.randint(*ts_range), random.randint(*val_range))
            )
    return w, ops


def gen_monotonic(
    seed,
    window_range=(1, 30),
    num_ops_range=(1, 300),
    num_events=5,
    val_range=(-10000, 10000),
    get_ratio=0.3,
):
    random.seed(seed)
    w = random.randint(*window_range)
    n = random.randint(*num_ops_range)
    ops = []
    ts = 0
    for _ in range(n):
        name = random.randint(0, num_events - 1)
        ts += random.randint(0, 3)
        if random.random() < get_ratio:
            ops.append(("GET", name, ts))
        else:
            ops.append(("ADD", name, ts, random.randint(*val_range)))
    return w, ops


def gen_ooo_within_window(
    seed,
    window_range=(1, 30),
    num_ops_range=(1, 200),
    num_events=5,
    val_range=(-10000, 10000),
    get_ratio=0.25,
):
    random.seed(seed)
    w = random.randint(*window_range)
    n = random.randint(*num_ops_range)
    ops = []
    global_ts = 0
    heads = {}

    for _ in range(n):
        name = random.randint(0, num_events - 1)
        h = heads.get(name, -1)
        if random.random() < get_ratio:
            ts = max(global_ts, h + 1) if h >= 0 else global_ts
            global_ts = max(global_ts, ts)
            heads[name] = max(h, ts)
            ops.append(("GET", name, ts))
        else:
            if random.random() < 0.3 and h >= 0:
                lo = max(0, h - w + 1)
                ts = random.randint(lo, h)
            else:
                global_ts += random.randint(0, 3)
                ts = global_ts
            heads[name] = max(heads.get(name, -1), ts)
            ops.append(("ADD", name, ts, random.randint(*val_range)))
    return w, ops


def gen_targeted():
    tests = []

    # Window = 1
    tests.append(
        (
            1,
            [
                ("ADD", 0, 5, 100),
                ("ADD", 0, 5, 200),
                ("GET", 0, 5),
                ("ADD", 0, 6, 50),
                ("GET", 0, 6),
            ],
        )
    )
    # Timestamp 0
    tests.append((5, [("ADD", 0, 0, 10), ("GET", 0, 0)]))
    # Out-of-order ADDs within window
    tests.append(
        (
            5,
            [
                ("ADD", 0, 10, 100),
                ("ADD", 0, 8, 200),
                ("ADD", 0, 6, 300),
                ("GET", 0, 10),
            ],
        )
    )
    # Stale rejected
    tests.append(
        (
            3,
            [
                ("ADD", 0, 10, 100),
                ("ADD", 0, 2, 999),
                ("GET", 0, 10),
            ],
        )
    )
    # Big jump
    tests.append(
        (
            5,
            [
                ("ADD", 0, 1, 10),
                ("ADD", 0, 2, 20),
                ("ADD", 0, 3, 30),
                ("GET", 0, 100),
            ],
        )
    )
    # Multiple vals same ts
    tests.append(
        (
            3,
            [
                ("ADD", 1, 5, 10),
                ("ADD", 1, 5, 20),
                ("ADD", 1, 5, 30),
                ("GET", 1, 5),
            ],
        )
    )
    # Independent names
    tests.append(
        (
            5,
            [
                ("ADD", 0, 3, 100),
                ("ADD", 1, 3, 999),
                ("GET", 0, 3),
                ("GET", 1, 3),
            ],
        )
    )
    # No data
    tests.append((10, [("GET", 0, 5), ("GET", 3, 99)]))
    # Tail boundary
    tests.append(
        (
            5,
            [
                ("ADD", 0, 0, 10),
                ("ADD", 0, 4, 20),
                ("GET", 0, 4),
                ("GET", 0, 5),
            ],
        )
    )
    # Backward ADD within window
    tests.append(
        (
            10,
            [
                ("ADD", 0, 20, 100),
                ("ADD", 0, 15, 200),
                ("ADD", 0, 11, 300),
                ("ADD", 0, 10, 400),  # rejected: 10 <= 20-10
                ("GET", 0, 20),
            ],
        )
    )
    # Fill then slide
    tests.append(
        (
            3,
            [
                ("ADD", 0, 0, 10),
                ("ADD", 0, 1, 20),
                ("ADD", 0, 2, 30),
                ("GET", 0, 2),
                ("ADD", 0, 3, 40),
                ("GET", 0, 3),
            ],
        )
    )
    # Multiple at same ts across slide
    tests.append(
        (
            2,
            [
                ("ADD", 0, 0, 10),
                ("ADD", 0, 0, 20),
                ("GET", 0, 0),
                ("ADD", 0, 1, 30),
                ("GET", 0, 1),
                ("ADD", 0, 2, 40),
                ("GET", 0, 2),
            ],
        )
    )
    return tests


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
def run_bf(window, ops):
    bf = BruteForce(window)
    results = []
    for op in ops:
        if op[0] == "ADD":
            bf.add_metric(op[1], op[2], op[3])
        else:
            results.append(bf.get_average(op[1], op[2]))
    return results


def write_input(window, ops):
    with open("input", "w") as f:
        f.write(f"{window}\n{len(ops)}\n")
        for op in ops:
            if op[0] == "ADD":
                f.write(f"ADD {op[1]} {op[2]} {op[3]}\n")
            else:
                f.write(f"GET {op[1]} {op[2]}\n")


def compile_cpp():
    r = subprocess.run(
        ["g++", "-std=c++17", "-O2", "-o", "solution", "main.cpp"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print("Compile error:", r.stderr)
        sys.exit(1)


def run_cpp():
    r = subprocess.run(["./solution"], capture_output=True, text=True, timeout=10)
    return r.stdout.strip().splitlines() if r.returncode == 0 else None


def floats_eq(a, b, eps=1e-4):
    # Generous eps because C++ cout truncates to ~6 significant digits
    return abs(a - b) / max(1.0, abs(a), abs(b)) < eps


def check(label, w, ops, exp, out):
    if out is None:
        print(f"  {label}: RUNTIME ERROR")
        return False
    got = [float(x) for x in out]
    if len(got) != len(exp):
        print(f"  {label}: count mismatch ({len(got)} vs {len(exp)})")
        return False
    for j, (e, g) in enumerate(zip(exp, got)):
        if not floats_eq(e, g):
            print(
                f"  {label}, GET #{j}: expected={e}, got={g}  (window={w}, {len(ops)} ops)"
            )
            return False
    return True


def run_suite(name, generator, count):
    t = p = 0
    for seed in range(count):
        w, ops = generator(seed)
        exp = run_bf(w, ops)
        write_input(w, ops)
        out = run_cpp()
        t += 1
        if check(f"{name} seed={seed}", w, ops, exp, out):
            p += 1
    return p, t


def main():
    compile_cpp()
    total_p = total_t = 0

    # Targeted
    for i, (w, ops) in enumerate(gen_targeted()):
        exp = run_bf(w, ops)
        write_input(w, ops)
        out = run_cpp()
        total_t += 1
        if check(f"TARGETED #{i}", w, ops, exp, out):
            total_p += 1

    # Suites
    for name, gen, n in [
        ("MONOTONIC", gen_monotonic, 500),
        ("OOO_WINDOW", gen_ooo_within_window, 500),
        ("RANDOM", gen_random, 500),
    ]:
        p, t = run_suite(name, gen, n)
        print(f"  {name}: {p}/{t}")
        total_p += p
        total_t += t

    print(f"\n{'='*50}")
    print(f"Results: {total_p}/{total_t} tests passed")
    print(
        "ALL TESTS PASSED" if total_p == total_t else f"FAILURES: {total_t - total_p}"
    )


if __name__ == "__main__":
    main()
