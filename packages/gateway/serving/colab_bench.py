import os, time, queue, threading, httpx
BASE=os.environ.get("SERVE_BASE_URL","http://localhost:8000/v1")
MODEL=os.environ.get("SERVE_MODEL","Qwen/Qwen2.5-7B-Instruct")
GPU_HOURLY=float(os.environ.get("GPU_HOURLY","0.80"))
HOSTED=float(os.environ.get("HOSTED_PRICE_PER_1M","1.10"))
CONC=[int(x) for x in os.environ.get("CONCURRENCY","1,2,4,8,16,32").split(",")]
PROMPT="Write a clear, self-contained paragraph explaining how a CPU cache improves performance. Be concrete."
MAXTOK=128; REQS=int(os.environ.get("REQS_PER_LEVEL","32"))
def one(c):
    r=c.post(f"{BASE}/chat/completions",json={"model":MODEL,"messages":[{"role":"user","content":PROMPT}],"max_tokens":MAXTOK,"temperature":0.2},timeout=600)
    r.raise_for_status(); return r.json().get("usage",{}).get("completion_tokens",0)
def ttft():
    t0=time.time()
    with httpx.Client(timeout=600) as c:
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
print("waiting for vLLM server at %s ..."%BASE)
for _ in range(360):
    try:
        httpx.get(f"{BASE}/models",timeout=5).raise_for_status(); print("server up"); break
    except Exception: time.sleep(10)
with httpx.Client() as c:
    t0=time.time(); one(c); warm=round((time.time()-t0)*1000,1)
print("model=%s  GPU=$%.2f/hr  hosted=$%.2f/1M"%(MODEL,GPU_HOURLY,HOSTED))
print("warmup latency %.0fms, TTFT %.0fms\n"%(warm,ttft()))
rows=[level(x) for x in CONC]
base=rows[0][1] or 1
print("%11s%9s%8s%7s%11s"%("concurrency","tok/s","req/s","gain","$/1M out"))
for conc,toks,reqs,cost in rows:
    print("%11d%9.0f%8.2f%6.1fx%11.4f"%(conc,toks,reqs,toks/base,cost))
beat=next((r for r in rows if r[3]<=HOSTED), None)
print("\nbatching gain at c=%d: %.1fx | $%.4f per 1M output tokens (GPU $%.2f/hr)"%(rows[-1][0],rows[-1][1]/base,rows[-1][3],GPU_HOURLY))
if beat:
    print("self-hosting BEATS hosted API ($%.2f/1M) at concurrency >= %d (%.0f tok/s -> $%.4f/1M)"%(HOSTED,beat[0],beat[1],beat[3]))
else:
    print("self-hosting never beats hosted API ($%.2f/1M) up to c=%d -- calling the API is cheaper at this traffic"%(HOSTED,rows[-1][0]))
