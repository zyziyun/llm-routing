# LLM Router 讲稿 + 大纲

面向:有 LLM 应用基础、想懂生产级路由和成本的学员。时长约 60 分钟,含 live demo。口吻:资深从业者带你看真数据,不是背概念。

节奏总览:
- 00-05 开场,把问题立起来
- 05-15 两个拓扑 + 两个决策
- 15-30 cascade vs predictive,配 demo
- 30-40 多厂商 select,配 demo
- 40-50 评估诚实性 + serving 经济学,配 demo
- 50-60 主线收束 + Q&A

---

## 00-05 开场:先把问题立起来

开场别讲定义。先抛一个反直觉:大多数人以为上了 router 就省钱,今天我用七个自己跑的真实验告诉你,router 什么时候省,什么时候纯属幻觉。

一句话把主题钉住:router 就是把每个请求送到能答好它的最便宜的地方。就这一句,后面全是它的展开。

引业界锚点:NVIDIA 那篇 SLM 论文,agentic 的未来是小模型打底。做法是 SLM-first,默认小模型,质量门跳闸才升级一次。让学员记住 SLM-first 这个词。

要强调的点:这是成本、延迟、隐私三个决策合一,不只是省钱。

## 05-15 两个拓扑 + 两个决策

先画 edge↔cloud 谱系那张图。左边浏览器里的 edge router,右边服务端 gateway,edge 的升级后端就是 gateway。让学员看到这不是两个东西,是一件事的两个位置。

然后讲两个决策,这是 router 的骨架,反复回到它:
- 决策一 classify → tier。估难度,选起始档。easy 起于 edge,hard 直接跳 frontier。强调:hard 不该在弱档上浪费调用。
- 决策二 quality gate。只接受 valid 且 confident 的回复。这里插一个必须讲清的区分:circuit breaker 是可靠性,provider 挂了跳过;quality gate 是智能,答得不够好升级。学员最容易混这两个。

口播要点:很多人把 router 做成"出错才兜底",那是 error fallback。真正值钱的是"质量才兜底",quality fallback。schema 任务尤其明显,弱模型能生成但过不了 strict JSON。

## 15-30 cascade vs predictive,配 demo

这是全场第一个高潮。先讲两种形态:
- cascade,试便宜档,过门就停,不过升级。好处是不需要预测器。代价是每次 miss 都先付了那一档。
- predictive,只看 query 一次定档。好处是不 double-pay。代价是需要一个好预测器。

抛问题给学员:你觉得哪个便宜?让他们猜。

然后上数字,gold judge 评的。predictive 的完美天花板 oracle,同 cascade 质量,成本便宜 9 倍。为什么,因为它从不为没用上的档付费。学员这里会点头。

紧接着泼冷水,这是诚实的部分:朴素 kNN 预测器只实现一半,准确率 50 percent。我把它换成训练过的 logistic regression 加 embedding,准确率升到 69 到 77 percent,仍然没完全打赢 cascade。

停一下,把 aha 说透:为什么训练过还赢不了。因为每一次错路由把难题送去 edge,损失的质量是 cascade 的 live gate 从不会犯的。cascade 每次真跑一遍再判,它不会在质量上误判,只是多花钱。

收这一段的一句话:predictive 架构是对的,天花板赢,能不能到天花板是 predictor 的问题,不是架构的问题。这也是 RouteLLM 为什么用 80k 偏好对去训,而不是 48 条 prompt。

demo 时机:这里跑 predictive 那个实验,把 oracle、cascade、predictive 曲线的图打出来,指着讲。

## 30-40 多厂商 select,配 demo

先问:如果你有三个云可选,Claude、GPT、DeepSeek,router 该怎么在它们之间挑?

引出错误做法:很多人会逐个云串行试,过门就停。听起来自动又稳。但实验说这是成本陷阱:每个 miss 都先计费,walk 两个云比直接调单个最优云还贵,同质量贵一倍以上。

正解:frontier 做成一个 pool,升级到 frontier 一次,pool 只选一个云,按实测 quality-per-dollar 挑。强调 select,不要 walk。

再补一个容易忽略的点:排序要用实测有效成本,不是官网 list price。reasoning model 的 token 账单事后才看得到,gpt-5 在实验里就是又贵又弱,list price 会把它误排前面。

落地感:这条已经进了生产代码,frontier 是配置驱动的 pool,加一个 provider 是改配置不是改代码。让学员感到这不是纸上谈兵。

demo 时机:展示 frontier pool 的配置和那三行测试跑绿。

## 40-50 评估诚实性 + serving 经济学,配 demo

评估诚实性,先讲一个坑:别用某一档评它自己。实验里 qwen 既是 frontier 档又是裁判,自评整体高 0.14。换独立 gold judge,edge 从 0.69 掉到 0.43。

方法论一句话:self-hosted judge 只能做相对排序,绝对分是乐观上界,绝对质量要独立裁判。这条学员做自己的 eval 时会踩,提前给。

serving 经济学,切到"自己养卡划不划算"。真跑 Qwen2.5-72B on A100。两个数:
- vLLM continuous batching 给 12.1 倍吞吐,对比本地 Ollama 只有 1.1 倍。解释为什么:vLLM 打包整批,Ollama 一次一条。这是"会调 API"和"会 serve model"的分水岭。
- 但即使批到 12 倍,自建 72B 到 c=32 仍比 DeepSeek 的 API 贵。盈亏平衡要到近满载 24/7。

myth-busting 时刻,全场最好玩的一处。抛问题让学员先猜:更快更贵的 GPU,每 token 是更便宜还是更贵。多数人会说更便宜,因为它快。上真数:同一个 72B,H100 每 token 贵约一倍,3.23 对 A100 的 1.52。为什么。单流两者都 18 tok/s,c=32 时 H100 只快 14 percent,但每小时贵 2.4 倍。机理:72B 的 decode 是 memory-bandwidth-bound,4K context、并发 32 时 batch 撑不满 H100 的算力,算力闲着。把这句钉死:贵卡每 token 更省是关于 saturation,不是关于标称速度,要贵卡赢得进 compute-bound 区。这是用自己的数据打破直觉的一刻,学员会记很久。

demo 时机:并排展示 A100 和 H100 两张吞吐成本曲线,指着 break-even 虚线,再指两张图的 dollar per 1M 差,把 myth-busting 落到图上。

## 50-60 主线收束 + Q&A

把全场收到一条:router 和自建 GPU 都不是自动更便宜。便宜又强的开源托管模型在双向侵蚀,既侵蚀聪明路由,也侵蚀自建。

给一个可带走的判据:clever routing 值不值,看档位之间成本差够不够大。差小,cascade 够、cloud-only 也接近;差大,才轮到 predictive 和自建。

结尾立场:大多数同类项目讲到"router 省钱"就停了。真正的深度是敢说出它什么时候不省。你们做自己的系统时,先量,再下结论,别信直觉。

预留 Q&A 常见问题:
- 端上模型能替代云吗。答:隐私和延迟场景是真需求,质量上还是升级少数难 turn。
- 该自己 serve 还是调 API。答:先算盈亏平衡,大多数流量下调 API 更便宜,除非你有持续高利用率或数据不能出 VPC。
- predictor 怎么训到能用。答:需要真训练数据,RouteLLM 级别的偏好数据,48 条 prompt 只够讲原理。
