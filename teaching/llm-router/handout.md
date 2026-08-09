# LLM Router

一句话:把每个请求送到"能答好它的最便宜的地方"。这一讲用一个真项目和七个真实验讲清楚,router 什么时候值,什么时候是幻觉。

## 1. 为什么需要 router

2026 年的默认不该是"什么都调 frontier"。应该是"用能过质量线的最小模型"。这同时是成本决策、延迟决策、隐私决策。

参考范式:NVIDIA 的 "Small Language Models are the Future of Agentic AI"。做法是 SLM-first,默认跑小模型,只有质量门跳闸时才升级一次到强模型。

## 2. 两个拓扑,同一件事

- **server-side gateway**:Python + FastAPI。classify → route → quality gate → escalate,外加 per-provider circuit breaker、per-key budget、OpenAI 兼容 endpoint、Prometheus metrics。
- **on-device edge router**:TypeScript + WebLLM + WebGPU,浏览器里跑小模型,大部分本地答完,只把难的升级到 gateway。隐私是头号指标,keep-local 时零字节外泄。

edge 的升级后端就是 gateway。两半合起来是完整的 edge↔cloud 谱系。

## 3. 决策一:classify → tier

估计难度,选起始档:easy 起于 edge,hard 直接跳 frontier,不在弱档浪费调用。

三种 classifier,难度递增也更强:
- heuristic:关键词、长度、结构。零成本,够用做 baseline。
- learned:hashed features 上的 softmax,给出校准置信度。
- embedding predictor:prompt embedding 上训分类器,预测"cheap 档能不能搞定"。这是 RouteLLM 的思路。

## 4. 决策二:quality gate,不是 error fallback

只有当回复 valid 且 confident 才接受。schema 任务要求 strict JSON 通过,否则升级。这把"出错才兜底"变成"质量才兜底"。

两种升级原因要分开:
- circuit breaker:某 provider 挂了或超时,跳过它。这是可靠性。
- quality gate:回复能跑但不够好,升级。这是智能。

## 5. cascade vs predictive

- **cascade**:试便宜档,过门就停,不过就升级。不需要预测器,但每次 miss 都先付了那一档,升级不免费。
- **predictive**:只看 query 一次定档,route once。需要一个好预测器,但不 double-pay。

关键数字,gold judge 评:predictive 的完美天花板 oracle 是 0.86 质量、成本比 cascade 便宜 9 倍,因为从不为没用上的档付费。但朴素 kNN 只实现一半 0.58,准确率 50%。换成训练过的分类器,准确率升到 69 到 77 percent,仍不足以完全打赢 cascade,因为错路由的质量损失是 cascade 的 live gate 从不会犯的。

结论:predictive 架构对,天花板赢,能不能到天花板是 predictor 的问题,不是架构问题。

## 6. 多厂商 frontier:select,不要 walk

frontier 档做成一个 cloud pool。升级到 frontier 一次,pool 只选一个云,按实测的 quality-per-dollar 挑最优,或挑最便宜。不逐个云串行试。

为什么:串行试多个云,每个 miss 都计费,比直接调单云还贵。实验里 walk 两个云 0.079 dollar,直接调最优单云 0.037 dollar,同质量便宜一半以上。而且排序要用实测有效成本,不是 list price:reasoning model 的 token 账单事后才看得到。

这条已经落进生产代码:frontier 是配置驱动的 pool,加一个 provider 是改配置不是改代码。

## 7. 评估的诚实性

不要用某一档去评它自己。实验里 qwen 既当 frontier 档又当裁判,自评整体高 0.14。换独立的 claude-opus-5 gold judge 复评,edge 从 0.69 掉到 0.43。自偏好只是次要,主要失真是对最弱档过于宽容。

方法论:self-hosted judge 只能用于相对的路由排序,它给的绝对分是乐观上界。绝对质量要独立裁判。

## 8. serving 经济学:自建 vs 托管 API

自建一个 frontier 级开源模型,什么时候比调 API 便宜。真跑:Qwen2.5-72B-AWQ on A100-80GB。

- vLLM continuous batching 给 12.1 倍吞吐,c=1 的 18 tok/s 到 c=32 的 218。对比本地 Ollama 只有 1.1 倍,因为 Ollama 一次一条,vLLM 打包整批。
- cost-per-token 随并发下降,从 18 dollar per 1M 到 1.52。但到 c=32 仍高于 DeepSeek 的约 1.10。盈亏平衡在约 300 tok/s,即要 A100 近满载 24/7 才追平按量付费 API。

## 9. 主线,记住这一条

router 和自建 GPU 都不是自动更便宜。便宜又强的开源托管模型,比如 DeepSeek,在质量和成本上双杀两个专有 frontier,持续侵蚀"聪明路由"和"自己养卡"的经济性。

clever routing 值不值,取决于档位之间的成本差够不够大。差小,cascade 已经够,cloud-only 也接近。差大,才轮到 predictive 和自建发挥。诚实说出这一点,比只讲"router 省钱"深一层。
