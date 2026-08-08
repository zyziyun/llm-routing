import os, time, queue, threading, httpx
BASE="http://localhost:8000/v1"; MODEL="Qwen/Qwen2.5-7B-Instruct"
GPU_HOURLY=float(os.environ.get("GPU_HOURLY","0.80"))
PROMPT="Write a clear, self-contained paragraph explaining how a CPU cache improves performance. Be concrete."
MAXTOK=128; REQS=24
def one(c):
    r=c.post(f"{BASE}/chat/completions",json={"model":MODEL,"messages":[{"role":"user","content":PROMPT}],"max_tokens":MAXTOK,"temperature":0.2},timeout=300)
    r.raise_for_status(); return r.json().get("usage",{}).get("completion_tokens",0)
def ttft():
    t0=time.time()
    with httpx.Client(timeout=300) as c:
        with c.stream("POST",f"{BASE}/chat/completions",json={"model":MODEL,"messages":[{"role":"user","content":PROMPT}],"max_tokens":MAXTOK,"temperature":0.2,"stream":True}) as s:
            for line in s.iter_lines():
                if line and "data:" in line and "[DONE]" not in line: return round((time.time()-t0)*1000,1)
    return -1.0
def level(conc):
    q=queue.Queue()
    for _ in range(REQS): q.put(1)
    tot=[0]; lock=threading.Lock()
    def w():
        with httpx.Client() as c:
            while True:
                try: q.get_nowait()
                except queue.Empty: return
                n=one(c)
                with lock: tot[0]+=n
    t0=time.time(); ts=[threading.Thread(target=w) for _ in range(conc)]
    for t in ts: t.start()
    for t in ts: t.join()
    wall=time.time()-t0; toks=tot[0]/wall if wall else 0; reqs=REQS/wall if wall else 0
    cost=(GPU_HOURLY/3600)/toks*1e6 if toks else 0
    return conc,round(toks,1),round(reqs,2),round(cost,4)
print("waiting for vLLM server to come up...")
for _ in range(180):
    try:
        httpx.get(f"{BASE}/models",timeout=5).raise_for_status(); print("server up"); break
    except Exception: time.sleep(10)
with httpx.Client() as c:
    t0=time.time(); one(c); warm=round((time.time()-t0)*1000,1)
print("warmup latency %.0fms, TTFT %.0fms\n"%(warm,ttft()))
rows=[level(x) for x in [1,2,4,8,16]]
base=rows[0][1] or 1
print("%11s%9s%8s%7s%11s"%("concurrency","tok/s","req/s","gain","$/1M out"))
for conc,toks,reqs,cost in rows:
    print("%11d%9.0f%8.2f%6.1fx%11.4f"%(conc,toks,reqs,toks/base,cost))
print("\nbatching gain at c=16: %.1fx | $%.4f per 1M output tokens (GPU $%.2f/hr)"%(rows[-1][1]/base, rows[-1][3], GPU_HOURLY))
