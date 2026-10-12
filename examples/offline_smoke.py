"""Exercise real media preparation and response parsing with synthetic data; no API."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cinerecon.common import save, sha
from cinerecon.media import ffmpeg
from cinerecon.evaluation import prepare, judge
from cinerecon.aggregate import summarize

parser=argparse.ArgumentParser()
parser.add_argument("--output",type=Path,required=True)
args=parser.parse_args()
out=args.output.resolve()
if out.exists() and any(out.iterdir()):
    raise SystemExit("Use an empty output directory")
out.mkdir(parents=True,exist_ok=True)
source=out/"reference.mp4"
subprocess.run([ffmpeg(),"-v","error","-f","lavfi","-i","testsrc2=size=160x90:rate=8:duration=1","-c:v","libx264","-pix_fmt","yuv420p",str(source)],check=True)
a=dict(clip_id="synthetic_cp001",video_id="synthetic",fps=8.,start_frame=0,end_frame=7,source_frame_offset=0,
       source_sha256=sha(source),first_appearance_definition="Zero-based first visible local frame",entities=[],evaluation_sample_frames=[0,7],evaluation_cut_frames=[],
       items=[dict(item_key=f"L1:synthetic_{i}",statement="Synthetic pipeline test only",category=c,levels=["L1","L2","L3"],start_frame=0,end_frame=7,evidence_frames=[0,7],subject_ids=[]) for i,c in enumerate(["camera_position","object_presence","object_motion"])])
save(out/"dataset/data/annotations/en/synthetic_cp001.json",a)
save(out/"synthetic_response.json",dict(model="gpt-5.6-sol",choices=[dict(finish_reason="stop",message=dict(content=json.dumps({"results":["Unsatisfied","Partially satisfied","Fully satisfied"]})))]))
for level in ["L1","L2","L3"]:
    prompt=out/"dataset/prompts/evaluation/en"/f"{level}.txt";prompt.parent.mkdir(parents=True,exist_ok=True)
    prompt.write_text("Synthetic fixture: not a real evaluation. Return three labels.")
    folder=out/"jobs"/level
    prepare(out/"dataset","synthetic_cp001",level,"en",source,source,folder,"SYNTHETIC_TEST_ONLY")
    result=judge(folder,response_file=out/"synthetic_response.json")
    assert result["status"]=="success"
summary=summarize([out/"jobs"/l for l in ["L1","L2","L3"]])
assert summary["configurations"][0]["overall"]==50.
summary["synthetic_test_only"]=True
save(out/"summary.json",summary)
print(json.dumps({"passed":True,"synthetic_test_only":True,"api_calls":0,"summary":str(out/"summary.json")},indent=2))
