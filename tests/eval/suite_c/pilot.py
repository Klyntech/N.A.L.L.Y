"""Suite C pilot — same 4-gate contract."""

from __future__ import annotations
import sys
from pathlib import Path
_project_root=str(Path(__file__).parent.parent.parent.parent)
if _project_root not in sys.path: sys.path.insert(0,_project_root)
from tests.eval.suite_c.schema import load_all_tasks
from tests.eval.suite_t.runner import gold_trajectory, noop_trajectory, replay
def degraded(task):
    ev=gold_trajectory(task)
    idx=[i for i,e in enumerate(ev) if e.get("role")=="agent"]
    if len(idx)>1: ev.pop(idx[-2])
    return ev
def hallucinating(task):
    if task.category=="II": return [{"role":"agent","name":"end_conversation","args":{"result":"Done!"}}]
    return gold_trajectory(task)
def run_suite(builder):
    tasks=load_all_tasks()
    results=[replay(t, builder(t)) for t in tasks]
    mean=sum(r["score"] for r in results)/len(results) if results else 0
    return {"mean_score": round(mean,4), "results": results, "tasks": tasks}
def main()->int:
    tasks=load_all_tasks()
    print(f"Suite C pilot: {len(tasks)} tasks")
    gold=run_suite(gold_trajectory)
    noop=run_suite(noop_trajectory)
    deg=run_suite(degraded)
    print(f"  gold {gold['mean_score']} noop {noop['mean_score']} degraded {deg['mean_score']}")
    fails=[]
    if gold["mean_score"]<0.99: fails.append(f"gold {gold['mean_score']}")
    for t,r in zip(tasks, noop["results"]):
        exp=1.0 if t.category=="II" else 0.0
        if r["score"]!=exp: fails.append(f"noop {t.id} {r['score']} != {exp}")
    if gold["mean_score"]-deg["mean_score"]<0.10: fails.append("gap<0.10")
    for t in [t for t in tasks if t.category=="II"]:
        res=replay(t, hallucinating(t))
        if res["score"]!=0.0: fails.append(f"minefield {t.id} {res}")
    rep=[run_suite(gold_trajectory)["mean_score"] for _ in range(3)]
    if max(rep)-min(rep)>1e-9: fails.append("unstable")
    if fails:
        print("PILOT FAILED:")
        for f in fails: print(" -",f)
        return 1
    print("PILOT PASSED: all 4 gates green.")
    return 0
if __name__=="__main__": raise SystemExit(main())
