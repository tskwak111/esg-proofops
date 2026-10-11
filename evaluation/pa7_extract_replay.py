"""PA7 phase measurements over an unchanged retained-response extract replay."""

import functools
import json
import sys
import threading
import time
from pathlib import Path


def main():
    from proofops.adapters.local import upstage_ocr_profile_v8 as v8
    from proofops.adapters.local import upstage_ocr_profile_v9 as v9
    from proofops.adapters.local.local_raster_reader import LocalRasterReader
    from proofops.adapters.local.pa7_raster_cache import ScopedRasterReader
    from proofops.application.ingest import pb1_tables
    from proofops_api.hosted_ocr import ReplayOCRStore
    from proofops_worker.extract_runner import LocalExtractRunner

    from evaluation import pa2_extract_replay
    from evaluation.pa3_replay import checkpoint

    events = []
    lock = threading.Lock()

    def instrument(owner, name, label):
        original = getattr(owner, name)

        @functools.wraps(original)
        def measured(*args, **kwargs):
            start, cpu = time.monotonic(), time.thread_time()
            try:
                return original(*args, **kwargs)
            finally:
                event = dict(
                    phase=label,
                    start=start,
                    seconds=time.monotonic() - start,
                    cpu_seconds=time.thread_time() - cpu,
                    thread=threading.get_ident(),
                )
                with lock:
                    events.append(event)

        setattr(owner, name, measured)

    for owner, name, label in (
        (pb1_tables, "observations", "table_observations"),
        (v8, "_segments", "table_segments"),
        (v8, "cell_proof", "v8_cell_proof"),
        (v9, "cell_proof", "v9_cell_proof"),
        (v9.Reader, "attest_claim_spans", "v9_attest"),
        (v9.Reader, "recompute_claim_receipt", "v9_recompute"),
        (ReplayOCRStore, "fetch", "ocr_replay"),
        (LocalRasterReader, "read", "raster_render_and_cpu_ocr"),
        (ScopedRasterReader, "read", "scoped_raster_read"),
        (LocalExtractRunner, "_publication_payload", "publication_checkpoint"),
    ):
        instrument(owner, name, label)
    source = Path(sys.argv[sys.argv.index("--source") + 1])
    output = Path(sys.argv[sys.argv.index("--output") + 1])
    try:
        pa2_extract_replay.main()
        original = checkpoint(source, "extract")
        replay = json.loads((output / "checkpoint.json").read_bytes())
        phases = {}
        for event in events:
            entry = phases.setdefault(event["phase"], dict(calls=0, wall_sum=0, cpu_sum=0))
            entry["calls"] += 1
            entry["wall_sum"] += event["seconds"]
            entry["cpu_sum"] += event["cpu_seconds"]
        measurement = json.loads((output / "measurement.json").read_bytes())
        limits = {
            name: Path("/sys/fs/cgroup", name).read_text().strip()
            for name in ("cpu.max", "memory.max", "memory.peak")
            if Path("/sys/fs/cgroup", name).is_file()
        }
        measurement.update(
            phases=phases, entire_checkpoint_identical=replay == original, cgroup=limits
        )
        measurement["phase_scope"] = (
            "includes untimed original-reader verification; extract.prof is timed-only"
            if "--verify-original" in sys.argv
            else "timed extract replay only"
        )
        (output / "measurement.json").write_text(json.dumps(measurement, indent=2))
        assert replay == original, "PA7_CHECKPOINT_CHANGED"
        print(
            json.dumps(
                dict(
                    seconds=measurement["seconds"], phases=phases, entire_checkpoint_identical=True
                )
            )
        )
    finally:
        if output.is_dir():
            (output / "phase-events.json").write_text(json.dumps(events))


if __name__ == "__main__":
    main()
