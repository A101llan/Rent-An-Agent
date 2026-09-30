import json, sys, time
from ollama_proof_lib import INPUTS, ROOT, ChatCapture, read_input
sys.path.insert(0, str(ROOT / "agents" / "meeting-notes-agent"))
import notes_extract as n
t = read_input(INPUTS / "meeting-notes" / "03-client-call-kariuki-logistics.docx")
with ChatCapture() as cap:
    t0 = time.perf_counter()
    try:
        r = n.extract_meeting_notes(t)
        print(json.dumps(r["output"], indent=1)); print(r["meta"]["attempts"], r["meta"]["warnings"])
    except Exception as e:
        print("ERR", repr(e)[:2000])
    print("wall", int((time.perf_counter()-t0)*1000))
for c in cap.calls:
    print({k: v for k, v in c.items() if k != "content"}); print(c["content"][:1500]); print("----")