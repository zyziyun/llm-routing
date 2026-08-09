# LLM Router 现场演示脚本

原则:能离线秒跑的现场跑,重的和花钱的实验只展示已提交的图和数,不现场跑。所有命令在 `packages/gateway` 下执行,除非另说。

课前检查:
```bash
cd packages/gateway
pip install -r requirements.lock
PYTHONPATH=src python -m pytest -q      # 24 tests 应全绿,证明离线可跑无 key
```

---

## Demo 1:一个请求的完整决策链,对应讲稿 05-15

路由一个简单问题,看它停在 edge:
```bash
PYTHONPATH=src python -m router.cli "What is the capital of France?"
```
指着输出说:difficulty=easy,起于 edge,零升级,零成本。

再路由一个 strict JSON 抽取,看弱档过不了 schema 而升级:
```bash
PYTHONPATH=src python -m router.cli --schema service,root_cause \
  "Extract the failing service and root cause from this incident log"
```
指着说:这就是 quality gate,不是 error fallback。弱档能生成但过不了 strict JSON,于是升级。

## Demo 2:router vs baseline,对应讲稿 05-15

```bash
PYTHONPATH=src python eval/run_eval.py
```
指着说:同样质量,router 比 all-frontier 便宜,tier mix 显示大部分流量留在便宜档。这是 SLM-first 的直接证据。

## Demo 3:cascade vs predictive,对应讲稿 15-30

不现场跑重实验,打开已提交的图和数:
```bash
open docs/screenshots/predictive-pareto.svg
open docs/screenshots/predictor-pareto.svg
cat benchmarks/results_predictor.json | python3 -m json.tool | head -30
```
现场读关键数:oracle 天花板 0.86,比 cascade 便宜 9 倍;朴素 kNN 只到 0.58;训练过的 predictor 到 69 到 77 percent 准确率。把"架构对、天花板赢、差距是 predictor 问题"这句在图上讲。

如果 Ollama 和 nomic-embed-text 就绪且想现场跑一次训练,标签有缓存,只重训:
```bash
python benchmarks/run_predictor.py        # 用 results_predictor_labels.json 缓存,不再付费
```

## Demo 4:多厂商 frontier select,对应讲稿 30-40

展示这条已进生产代码,不是幻灯:
```bash
PYTHONPATH=src python -m pytest tests/test_frontier_pool.py -q -v
```
指着三个测试名说:best_value 选一个云、只调它、从不 walk 其它。

再展示配置驱动,加一个云是改配置:
```bash
sed -n '/Multi-cloud frontier/,/Layout/p' README.md
```
读那段 FRONTIER_POOL_JSON 的例子,强调 select not cascade、按实测成本排序。

打开 Exp4 的图看真数据:
```bash
open docs/screenshots/hosted-pareto.svg
```
指着说:walk 两个云比直接调单个最优云还贵;DeepSeek 质量成本双杀两个专有 frontier。

## Demo 5:评估诚实性,对应讲稿 40-50

```bash
open docs/screenshots/judge-ab.svg
cat benchmarks/results_judge_ab.json | python3 -m json.tool | head -20
```
读数:qwen 自评整体高 0.14,独立 gold judge 下 edge 从 0.87 掉到 0.58。讲 self-hosted judge 是乐观上界这条方法论。

## Demo 6:serving 经济学,对应讲稿 40-50

```bash
open docs/screenshots/serving-throughput.svg
cat serving/results_serving.json | python3 -m json.tool
```
指着两条线:绿线吞吐 c=1 到 c=32 涨 12.1 倍,蓝线成本降,蓝虚线是 DeepSeek 的 break-even 价。讲即使批 12 倍,自建 72B 到 c=32 仍在虚线之上,要近满载才追平。

myth-busting,并排打开 H100 那张:
```bash
open docs/screenshots/serving-throughput-h100.svg
python3 -c "import json; a=json.load(open('serving/results_serving.json')); h=json.load(open('serving/results_serving_h100.json')); f=lambda d:[l for l in d['levels'] if l['concurrency']==32][0]; print('A100 %s/hr c=32: %s tok/s, \$%.2f/1M'%(a['gpu_hourly'],f(a)['tok_per_s'],f(a)['cost_per_1m_out'])); print('H100 %s/hr c=32: %s tok/s, \$%.2f/1M'%(h['gpu_hourly'],f(h)['tok_per_s'],f(h)['cost_per_1m_out']))"
```
先让学员猜更快更贵的 H100 每 token 更便宜还是更贵,再打印这两行:H100 只快 14 percent 却每 token 贵约一倍。讲 memory-bandwidth-bound 的机理,钉死"贵卡更省是关于 saturation 不是标称速度"。

想现场感受 batching 反差,对着本地 Ollama 跑一次,增益接近 1,正好当反例:
```bash
SERVE_BASE_URL=http://localhost:11434/v1 SERVE_MODEL=qwen2.5-coder:14b \
  GPU_HOURLY=0 CONCURRENCY=1,2,4,8 REQS_PER_LEVEL=8 python3 serving/bench_serving.py
```

## Demo 7 可选:真跑一次 gateway,对应任意时刻

起真 uvicorn,跑 routing、SSE streaming、auth 401、rate limit 429、budget 402、metrics:
```bash
bash demo/live_demo.sh
```
指着 metrics scrape 说:这是生产形态,不是脚本玩具。

---

收尾一句:所有这些图都是学员自己能重跑出来的,repo 里全是真数据,不是 PPT。这就是这一讲和别处不一样的地方。
