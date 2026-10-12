import concurrent.futures
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from PIL import Image
from cinerecon.common import LABELS, checksum, read, save, sha
from cinerecon.sampling import frames_for
from cinerecon.media import mapping
from cinerecon.evaluation import judge, parse_response, prepare
from cinerecon.aggregate import scores, summarize
from cinerecon.dataset import validate

ROOT = Path(__file__).resolve().parents[1]


def annotation():
    return dict(clip_id="demo_cp001", video_id="demo", start_frame=0, end_frame=3, fps=4., source_frame_offset=0,
                first_appearance_definition="First visible local frame", entities=[], evaluation_sample_frames=[0,3], evaluation_cut_frames=[],
                items=[dict(item_key=f"L1:demo_{n}", statement="Synthetic test assertion", category=cat, levels=["L1","L2","L3"], start_frame=0, end_frame=3, evidence_frames=[0,3], subject_ids=[]) for n,cat in enumerate(["camera_position","object_presence","object_motion"])])


def job_at(folder, clip="demo_cp001", level="L1"):
    folder.mkdir(parents=True)
    img = folder/"pair.jpg"
    Image.new("RGB", (20,40), "gray").save(img)
    a = annotation()
    a["clip_id"] = clip
    job = dict(clip_id=clip, video_id="demo", level=level, language="en", configuration="SYNTHETIC_TEST_ONLY", annotation=a,
               prompt="Synthetic test, not a benchmark result.", source_sha256="synthetic", generated_sha256="synthetic",
               pairs=[dict(path="pair.jpg", sha256=sha(img), source_local_frame=0, generated_local_frame=0, source_local_sec=0., generated_local_sec=0.)])
    save(folder/"job.json", job)
    return job


def response(labels=None):
    return dict(model="gpt-5.6-sol", choices=[dict(finish_reason="stop", message=dict(content=json.dumps({"results":labels or LABELS["en"]})))])


class ProtocolTests(unittest.TestCase):
    def test_preparation_failure_does_not_publish_partial_job(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/"target"
            def broken(*args):
                (Path(args[6])/"partial.txt").write_text("incomplete")
                raise ValueError("synthetic decode failure")
            with patch("cinerecon.evaluation._prepare_inplace", side_effect=broken):
                with self.assertRaises(ValueError):
                    prepare(ROOT,"demo","L1","en","source","generated",folder,"test")
            self.assertFalse(folder.exists())
            self.assertEqual(list(Path(temp).iterdir()),[])

    def test_full_english_release(self):
        report = validate(ROOT)
        self.assertEqual(report["clips"],360)
        self.assertEqual(report["unique_items"],35836)

    def test_sampling_preserves_mandatory_evidence(self):
        a = annotation()
        a.update(end_frame=119, fps=60., evaluation_sample_frames=list(range(120)), evaluation_cut_frames=[50])
        a["items"][0].update(start_frame=10,end_frame=91,evidence_frames=[10,45,91])
        frames = frames_for(a,"L1")
        self.assertEqual(len(frames),50)
        self.assertTrue({0,3,10,45,49,50,51,91,119} <= set(frames))
        a["items"][0]["evidence_frames"] = list(range(60))
        with self.assertRaises(ValueError):
            frames_for(a,"L1")

    def test_fps_mapping_and_truncation(self):
        a=annotation();a.update(fps=24.,end_frame=23,source_frame_offset=24)
        rows=mapping(a,dict(fps=30.,frames=60),[0,12,23])
        self.assertEqual([r["generated_absolute_frame"] for r in rows],[30,45,59])
        with self.assertRaises(ValueError):
            mapping(a,dict(fps=30.,frames=59),[0,23])

    def test_macro_not_micro_and_empty_dimension(self):
        rows=[dict(video_id="v",items=[dict(category="object_presence",score=1)]),dict(video_id="v",items=[dict(category="object_presence",score=0)]*9)]
        s=scores(rows)
        self.assertEqual(s["dimensions"]["static"]["score"],50)
        self.assertIsNone(s["overall"])
        self.assertIsNone(scores([])["dimensions"]["dynamic"]["score"])

    def test_strict_response_labels(self):
        job={"annotation":annotation(),"level":"L1","language":"en"}
        self.assertEqual([i["score"] for i in parse_response(response(),job)],[0,.5,1])
        for labels in [["Fully satisfied"], ["unknown"]*3]:
            with self.assertRaises(ValueError):
                parse_response(response(labels),job)
        r=response();r["choices"][0]["message"]["content"]='{"results":[],"results":[]}'
        with self.assertRaises(ValueError):parse_response(r,job)

    def test_category_macro_coverage_and_unchanged_parent_scores(self):
        rows = [
            dict(video_id="v1", items=[dict(category="object_presence", score=1),
                                      dict(category="camera_position", score=1)]),
            dict(video_id="v2", items=[dict(category="object_presence", score=0)] * 9
                 + [dict(category="object_relation", score=1), dict(category="object_motion", score=.5)]),
        ]
        result = scores(rows)
        self.assertEqual(result["categories"]["object_presence"],
                         dict(dimension="static", score=50, clips=2, items=10))
        self.assertEqual(result["categories"]["object_relation"],
                         dict(dimension="static", score=100, clips=1, items=1))
        self.assertEqual(result["categories"]["action_event"],
                         dict(dimension="dynamic", score=None, clips=0, items=0))
        self.assertEqual(result["dimensions"]["static"]["score"], 55)
        self.assertAlmostEqual(result["overall"], (55 + 50 + 100) / 3)
        self.assertEqual(len(result["categories"]), 11)
        self.assertTrue(all(c["score"] is None and c["clips"] == c["items"] == 0
                            for c in scores([])["categories"].values()))

    def test_provider_qualified_model_identifier(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);folder=base/"job";job_at(folder)
            raw=response();raw["model"]="openai/gpt-5.6-sol"
            save(base/"response.json",raw)
            r=judge(folder,judge_model="openai/gpt-5.6-sol",response_file=base/"response.json")
            self.assertEqual(r["status"],"success")

    def test_refusal_is_terminal_and_unscored(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);folder=base/"job";job_at(folder)
            raw=response();raw["choices"][0]["finish_reason"]="content_filter"
            save(base/"response.json",raw)
            r=judge(folder,response_file=base/"response.json")
            self.assertEqual(r["status"],"refused")
            with self.assertRaises(ValueError):judge(folder,response_file=base/"response.json",retry_failed=True)
            s=summarize([folder])
            self.assertIsNone(s["configurations"][0]["overall"])

    def test_missing_not_zero_and_equal_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);save(base/"response.json",response());folders=[]
            for level in ["L1","L2","L3"]:
                folder=base/level;job_at(folder,level=level);folders.append(folder)
                judge(folder,response_file=base/"response.json")
            missing=base/"missing";job_at(missing,clip="demo_cp002");folders.append(missing)
            s=summarize(folders)
            self.assertEqual(s["configurations"][0]["overall"],50)
            self.assertEqual(s["configurations"][0]["levels"]["L1"]["categories"]["object_motion"],
                             dict(dimension="dynamic", score=100, clips=1, items=1))
            self.assertEqual(s["exclusions"][0]["status"],"missing")
            with self.assertRaises(ValueError):summarize(folders+[folders[0]])

    def test_http_errors_do_not_redirect_retry_or_save_sensitive_body(self):
        received=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                received.append(self.path)
                self.send_response(int(self.path.strip("/")))
                self.send_header("Location", "/unexpected")
                self.end_headers()
                self.wfile.write(b'{"error":"sensitive-placeholder"}')
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{"CINERECON_API_KEY":"local-test-placeholder"}):
                for status in [302,403,429]:
                    folder=Path(temp)/str(status);job_at(folder)
                    result=judge(folder,endpoint=f"http://127.0.0.1:{server.server_port}/{status}",execute=True)
                    self.assertEqual(result["status"],"failed")
                    record=read(folder/"attempts/0001.json")
                    self.assertEqual(record["http_status"],status)
                    self.assertEqual(record["error"],"rate_limit" if status==429 else "http_error")
                    self.assertNotIn("sensitive-placeholder",json.dumps(record))
                    self.assertNotIn("local-test-placeholder",json.dumps(record))
                self.assertEqual(received,["/302","/403","/429"])
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_8_parallel_calls_and_success_cache(self):
        received=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append(body)
                payload=json.dumps(response()).encode()
                self.send_response(200);self.send_header("Content-Type","application/json");self.end_headers();self.wfile.write(payload)
        class TestServer(ThreadingHTTPServer):
            request_queue_size = 32
        server=TestServer(("127.0.0.1",0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{"CINERECON_API_KEY":"local-test-placeholder"}):
                folders=[]
                for i in range(8):
                    p=Path(temp)/str(i);job_at(p,clip=f"demo_cp{i}");folders.append(p)
                endpoint=f"http://127.0.0.1:{server.server_port}/chat/completions"
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    results=list(pool.map(lambda p:judge(p,endpoint=endpoint,execute=True),folders))
                self.assertTrue(all(r["status"]=="success" for r in results), [(r["status"], r.get("error")) for r in results])
                self.assertEqual(len(received),8)
                for body in received:
                    self.assertEqual(body["model"], "openai/gpt-5.6-sol")
                    self.assertEqual(body["provider"], {"only":["openai"], "allow_fallbacks":False, "require_parameters":True})
                    self.assertFalse(body["stream"])
                    self.assertEqual(body["reasoning_effort"], "high")
                    self.assertTrue(body["response_format"]["json_schema"]["strict"])
                with self.assertRaises(ValueError):
                    judge(folders[0], endpoint=endpoint+"/other", execute=True)
                cached=judge(folders[0],endpoint=endpoint,execute=True)
                self.assertEqual(cached["status"],"cached_success")
                self.assertEqual(len(received),8)
                (folders[0]/"pair.jpg").write_bytes(b"changed")
                with self.assertRaises(ValueError):judge(folders[0],endpoint=endpoint,execute=True)
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__ == "__main__":
    unittest.main()
