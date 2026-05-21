from __future__ import annotations

import html
import re
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
PPT = ROOT / "docs" / "2022005052-王晨阳-毕业答辩PPT codex版本.pptx"
BACKUP = ROOT / "docs" / "2022005052-王晨阳-毕业答辩PPT codex版本_原始备份.pptx"
REPORT_PPT = ROOT / "docs" / "2022005052-王晨阳-毕业设计汇报版.pptx"
SPEECH_MD = ROOT / "docs" / "2022005052-王晨阳-毕业设计汇报演讲稿.md"
SPEECH_DOCX = ROOT / "docs" / "2022005052-王晨阳-毕业设计汇报演讲稿.docx"

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}
ET.register_namespace("a", NS["a"])
ET.register_namespace("p", "http://schemas.openxmlformats.org/presentationml/2006/main")
ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")


SLIDE_TEXTS: dict[int, list[str]] = {
    1: [
        "本科毕业设计汇报",
        "物联网智能燃气表异常检测",
        "基于深度学习的物联网智能燃气表数据异常检测系统",
        "面向燃气表多维时序数据的 LSTM AutoEncoder 异常识别与运维闭环",
        "24×7",
        "输入窗口",
        "24 个时间步，7 类燃气表运行特征",
        "LSTM AE",
        "核心模型",
        "学习正常时序模式并计算重构误差",
        "0.68s",
        "平均响应",
        "从设备上报到前端告警的端到端耗时",
        "答辩人：王晨阳    学号：2022005052    专业：软件工程",
    ],
    2: [
        "汇报提纲",
        "按照毕业设计汇报逻辑，说明问题、设计、实现和验证结果",
        "01",
        "选题背景与研究意义",
        "智能燃气表时序数据异常检测问题",
        "02",
        "需求分析与总体设计",
        "设备接入、模型推理、告警工单闭环",
        "03",
        "核心算法设计",
        "LSTM AutoEncoder、滑动窗口与阈值判定",
        "04",
        "系统实现",
        "Flask + MySQL + PyTorch + Vue",
        "05",
        "测试与结果分析",
        "检测指标、实时性和持续训练验证",
        "06",
        "总结与展望",
        "完成工作、不足与后续优化方向",
    ],
    3: [
        "选题背景：燃气表从远程抄表走向状态感知",
        "传统阈值方法难以处理多维、非线性、带噪声的物联网时序数据",
        "问题来源",
        "智能燃气表持续产生瞬时流量、累计用量、电压、信号、压力等数据；单点阈值只能发现明显越界，难以识别一段时间内的复杂关联异常。",
        "• 数据具有时间连续性，不同特征之间存在联动关系",
        "• 固定阈值难以适应季节、区域和用户习惯变化",
        "• 异常检测结果还需要进入告警、派单和反馈流程",
        "人工 + 阈值",
        "传统方式",
        "依赖经验规则，发现复杂异常能力有限",
        "深度学习",
        "本文方案",
        "学习正常运行模式，识别时序偏离",
        "告警 + 工单",
        "业务落点",
        "把识别结果转化为可处理任务",
    ],
    4: [
        "研究目标与技术路线",
        "把原始上报数据转化为可解释、可处理、可持续优化的异常检测结果",
        "1",
        "设备数据接入",
        "2",
        "清洗与标准化",
        "3",
        "滑动窗口 24×7",
        "4",
        "LSTM AE 推理",
        "5",
        "异常得分与阈值",
        "6",
        "告警工单闭环",
        "算法目标",
        "学习正常燃气表多维时序规律，利用重构误差发现异常窗口。",
        "系统目标",
        "实现设备接入、实时推理、可视化看板、告警处理和工单流转。",
        "工程目标",
        "通过模型版本管理和持续训练机制，支撑系统长期运行和后续扩展。",
    ],
    5: [
        "系统总体设计",
        "采用分层架构组织设备接入、算法分析和业务处理",
        "层次",
        "核心职责",
        "关键内容",
        "感知接入层",
        "采集燃气表运行数据",
        "真实智能燃气表 / 虚拟模拟设备",
        "数据传输层",
        "完成设备数据上传",
        "HTTP / MQTT，设备密钥校验",
        "计算分析层",
        "执行异常检测",
        "清洗、标准化、滑动窗口、LSTM AE 推理",
        "业务逻辑层",
        "处理异常结果",
        "告警生成、工单派发、模型版本管理",
        "展示层",
        "提供可视化管理",
        "监控看板、告警页面、工单流程",
        "主数据流：设备上报 → 数据预处理 → LSTM AutoEncoder 推理 → 异常得分 → 业务规则复核 → 告警和工单 → 处理反馈进入持续训练。",
    ],
    6: [
        "数据特征与预处理",
        "模型输入不是单一读数，而是 24 个时间步 × 7 个特征的多维时序窗口",
        "特征",
        "业务含义",
        "instant_flow",
        "瞬时流量，反映当前用气速度",
        "cumulative_usage",
        "累计用气量，反映长期用气趋势",
        "battery_voltage",
        "电池电压，反映设备供电状态",
        "signal_strength",
        "信号强度，反映通信质量",
        "valve_state",
        "阀门状态，反映开阀或关阀情况",
        "temperature",
        "环境温度，反映运行环境",
        "pressure",
        "管网压力，反映燃气输送状态",
        "24 × 7",
        "模型输入维度",
        "24 个采样点，每点 7 个特征",
        "• 按设备编号和时间戳排序",
        "• 清洗缺失值、无效值和明显极端值",
        "• 采用 Z-Score 标准化消除量纲差异",
        "• 使用滑动窗口保留最近一段时间的变化趋势",
    ],
    7: [
        "需求分析与异常场景",
        "系统需要覆盖用气异常、设备状态异常、通信异常和管网异常",
        "异常类型",
        "检测依据",
        "业务含义",
        "流量激增",
        "瞬时流量在短时间内明显放大",
        "疑似漏气、阀门异常或用气突增",
        "电压突降",
        "电池电压低于正常工作范围",
        "电池耗尽或供电故障",
        "信号异常",
        "信号强度偏低或数据缺失",
        "通信干扰、网络覆盖较差",
        "累计用气量跳变",
        "累计读数出现异常偏移",
        "计量异常或数据采集错误",
        "压力异常",
        "管网压力超出正常范围",
        "管网波动或传感器异常",
        "长时间静止",
        "流量长时间保持不变",
        "设备损坏或传感器失效",
        "85%-90%",
        "正常样本",
        "符合燃气表多数时间正常运行的业务特征",
        "10%-15%",
        "异常样本",
        "用于模型评估、阈值验证和案例分析",
    ],
    8: [
        "核心算法：LSTM AutoEncoder",
        "利用 LSTM 学习时间依赖，利用自编码器重构误差识别异常",
        "1",
        "输入窗口 24×7",
        "2",
        "LSTM Encoder",
        "3",
        "Latent Space",
        "4",
        "LSTM Decoder",
        "5",
        "MSE 异常得分",
        "正常窗口",
        "模型已经学习正常运行模式，原始序列和重构序列差异较小，重构误差低于阈值。",
        "异常窗口",
        "异常数据偏离正常时序规律，模型难以准确重构，重构误差升高并触发后续判定。",
    ],
    9: [
        "模型训练与参数设置",
        "训练重点不是直接分类异常类型，而是充分学习正常数据的重构规律",
        "参数",
        "取值",
        "Window Size",
        "24",
        "Feature Size",
        "7",
        "Hidden Size",
        "32",
        "Num Layers",
        "2",
        "Learning Rate",
        "0.001",
        "Batch Size",
        "32",
        "Epochs",
        "20",
        "Train Split",
        "0.8",
        "• 损失函数：MSE 均方误差",
        "• 优化器：Adam，学习率 0.001",
        "• 主要使用正常窗口训练模型",
        "• 异常窗口用于效果评估和阈值验证",
        "• 模型、标准化器和阈值写入模型元数据",
        "隐藏层维度 32 在表达能力和压缩约束之间折中，避免模型直接记忆输入，从而保留异常检测所需的重构差异。",
    ],
    10: [
        "异常判定与可解释性设计",
        "异常得分来自重构误差，最终告警结合业务规则复核",
        "深度学习判定",
        "Anomaly Score = MSE(输入序列, 重构序列)",
        "• 得分越高，偏离正常模式越明显",
        "• 阈值来自验证集正常样本误差分布",
        "• 超过阈值后初步判定为异常",
        "业务规则复核",
        "• 电池电压低于安全范围",
        "• 信号强度持续偏低",
        "• 管网压力超出正常范围",
        "• 瞬时流量相较近期均值突增或突降",
        "• 重构误差高但单一规则不明显时标记综合异常",
        "设计要点：LSTM AutoEncoder 负责发现复杂时序偏离，业务规则负责解释异常原因并支持运维处置。",
    ],
    11: [
        "系统实现与关键技术",
        "围绕 Python 深度学习推理和 Web 业务系统完成集成",
        "模块",
        "技术",
        "后端框架",
        "Flask",
        "ORM 工具",
        "Flask-SQLAlchemy",
        "数据库",
        "MySQL / PyMySQL",
        "深度学习框架",
        "PyTorch",
        "数据处理",
        "Pandas、NumPy",
        "标准化",
        "Scikit-learn StandardScaler",
        "模型管理",
        "PyTorch、Joblib、JSON 元数据",
        "实时通信",
        "Flask-Sock、WebSocket",
        "前端实现",
        "Vue",
        "常驻内存",
        "模型推理",
        "避免每次检测重复加载模型",
        "HTTP/JSON",
        "数据上报",
        "设备密钥 X-API-Key 校验",
        "异步检测",
        "任务调度",
        "数据接收与模型推理解耦",
    ],
    12: [
        "测试方案与评价指标",
        "从检测准确性、实时性和业务闭环三个角度验证系统",
        "检测准确性",
        "• Accuracy：整体判断正确比例",
        "• Precision：预测异常中真实异常的比例",
        "• Recall：真实异常被成功发现的比例",
        "• F1-score：精确率和召回率的综合指标",
        "燃气安全场景中漏报风险更高，因此召回率和 F1-score 是重点指标。",
        "工程性能",
        "• ROC / AUC：不同阈值下区分正常与异常的能力",
        "• Latency：单次窗口推理与端到端响应时间",
        "• 业务流程：告警生成、工单派发、处理结果回写",
        "• 持续训练：数据分布变化后的模型恢复能力",
    ],
    13: [
        "测试结果一：检测效果对比",
        "LSTM AutoEncoder 在准确率和 F1-score 上取得较好的综合表现",
        "方法",
        "准确率",
        "精确率",
        "召回率",
        "F1",
        "固定阈值法",
        "0.842",
        "0.806",
        "0.684",
        "0.740",
        "3-Sigma",
        "0.835",
        "0.700",
        "0.958",
        "0.809",
        "LSTM AE",
        "0.893",
        "0.858",
        "0.846",
        "0.852",
        "结论：固定阈值对明显越界有效但召回不足；3-Sigma 召回较高但误报偏多；LSTM AE 能学习多维时序关系，综合表现更稳定。",
    ],
    14: [
        "测试结果二：阈值对检测效果的影响",
        "阈值升高会减少误报，但也会降低召回率；92% 分位点附近 F1-score 最优",
        "0.852",
        "最优 F1-score",
        "92% 分位点，τ = 0.704",
        "• 低阈值：召回率高，但误报增加",
        "• 高阈值：精确率高，但漏报风险上升",
        "• 燃气安全场景不宜设置过高阈值",
    ],
    15: [
        "测试结果三：系统实时性",
        "端到端平均响应时间 0.68s，满足秒级异常监测要求",
        "测试项目",
        "平均耗时",
        "最大耗时",
        "结果",
        "JSON 报文接收与解析",
        "0.05s",
        "0.09s",
        "正常",
        "数据入库与窗口构造",
        "0.12s",
        "0.21s",
        "正常",
        "LSTM AE 推理",
        "0.18s",
        "0.34s",
        "正常",
        "告警记录生成",
        "0.07s",
        "0.13s",
        "正常",
        "WebSocket 页面刷新",
        "0.26s",
        "0.49s",
        "正常",
        "端到端总响应时间",
        "0.68s",
        "1.26s",
        "满足秒级要求",
        "0.18s",
        "平均推理耗时",
        "单个 24×7 窗口",
        "0.68s",
        "端到端平均",
        "上报到前端告警",
        "1.26s",
        "最大端到端",
        "仍处于秒级范围",
    ],
    16: [
        "测试结果四：持续训练验证",
        "数据分布偏移会降低模型效果，持续训练能够恢复并提升检测性能",
        "阶段",
        "准确率",
        "F1",
        "偏移前",
        "0.826",
        "0.689",
        "偏移后",
        "0.781",
        "0.632",
        "持续训练后",
        "0.846",
        "0.721",
        "持续训练流程：提取新数据 → 清洗标准化 → 构造窗口 → 训练候选模型 → 指标评估 → active model 切换。",
    ],
    17: [
        "典型案例：流量突变识别",
        "模型不是判断单点是否越界，而是判断整段时间窗口是否偏离正常模式",
        "• 第 6 至第 7 个时间步出现明显流量突增",
        "• 模型重构结果仍接近正常用气模式",
        "• 原始序列与重构序列差距迅速增大",
        "• 重构误差超过阈值后生成流量异常告警",
        "该案例体现了 LSTM AutoEncoder 的优势：通过学习正常时序模式，对复杂波动和多维关联异常更敏感。",
    ],
    18: [
        "总结与展望",
        "本文完成了深度学习模型与燃气表运维业务流程的结合",
        "主要成果",
        "• 完成物联网智能燃气表异常检测系统设计与实现",
        "• 设计 LSTM AutoEncoder 多维时序异常检测模型",
        "• 实现设备接入、实时推理、告警、工单和看板",
        "• 实验中 LSTM AE 的 F1-score 达到 0.852",
        "• 端到端平均响应时间 0.68s，满足秒级监测要求",
        "不足与展望",
        "• 当前主要基于模拟数据和实验数据验证",
        "• 尚未在大规模真实燃气表网络中长期运行",
        "• 后续可接入真实企业数据提升泛化能力",
        "• 可尝试 GRU AutoEncoder、Transformer 等模型",
        "• 进一步增强异常类型解释能力和部署能力",
    ],
}


SPEECH = """# 2022005052-王晨阳-毕业设计汇报演讲稿

题目：基于深度学习的物联网智能燃气表数据异常检测系统

预计时长：约 6 分钟。正式汇报时可按页停顿，重点讲清背景、算法、系统实现和测试结果。

## 第 1 页：封面，约 15 秒

各位老师好，我是王晨阳，我的毕业设计题目是《基于深度学习的物联网智能燃气表数据异常检测系统》。
本课题面向智慧燃气运维场景，使用 LSTM AutoEncoder 对 24 个时间步、7 类运行特征构成的时序窗口进行异常识别，并把结果转化为告警和工单。

## 第 2 页：汇报提纲，约 15 秒

下面我从六个方面汇报：选题背景与意义、需求分析与总体设计、核心算法、系统实现、测试结果，最后是总结与展望。

## 第 3 页：选题背景，约 30 秒

智能燃气表持续上报瞬时流量、累计用气量、电压、信号、阀门、温度和压力等多维数据，这些数据具有时间连续性和特征关联性。
传统固定阈值能发现明显越界，但难以识别一段时间内的趋势异常和多特征组合异常。燃气安全场景还要求异常发现后能够快速处置，所以系统需要从“识别异常”延伸到“告警、派单和反馈”的闭环。

## 第 4 页：研究目标与技术路线，约 35 秒

本设计的目标是把燃气表原始上报数据转化为可解释、可处理、可持续优化的异常检测结果。
技术路线包括六步：设备数据接入，数据清洗和标准化，构造 24 乘 7 的滑动窗口，输入 LSTM AutoEncoder 计算重构误差，结合阈值和业务规则判断异常，最后生成告警和工单，并把处理反馈用于后续持续训练。

## 第 5 页：系统总体设计，约 35 秒

系统采用五层架构。感知接入层负责燃气表数据采集；数据传输层支持 HTTP 和 MQTT，并通过设备密钥校验身份；计算分析层负责预处理、窗口构造和模型推理；业务逻辑层负责告警、工单和模型版本管理；展示层提供监控看板、告警列表和工单管理。
整体数据流是：设备上报，后端清洗落库，模型推理，规则复核，生成告警和工单。

## 第 6 到 7 页：数据特征与异常场景，约 40 秒

模型使用 7 类特征：瞬时流量、累计用气量、电池电压、信号强度、阀门状态、环境温度和管网压力。这些特征分别对应用户用气行为、设备状态、通信质量和管网环境。
系统不是判断单条读数，而是按设备和时间排序，清洗缺失值、无效值和明显极端值后，构造 24 个连续时间步组成的窗口，并进行 Z-Score 标准化。
异常场景覆盖流量激增、电压突降、信号异常、累计用量跳变、压力异常和长时间静止，对应漏气风险、供电故障、通信异常、计量错误和设备失效等问题。

## 第 8 到 10 页：核心算法与异常判定，约 65 秒

核心模型采用 LSTM AutoEncoder。LSTM 用来学习时间依赖，自编码器用来学习正常样本的重构规律。输入窗口经过编码器压缩为隐含表示，再由解码器重构原始序列。
正常窗口符合已有规律，模型能够较好重构，均方误差较小；异常窗口偏离正常模式，模型重构困难，误差升高。
训练阶段主要使用正常窗口，参数包括窗口长度 24、特征数 7、隐藏层维度 32、LSTM 层数 2、学习率 0.001、训练轮数 20。
异常判定分为两层：第一层根据重构误差和阈值判断是否异常；第二层结合业务规则复核，例如低电压、弱信号、压力异常和流量突变。这样既能发现复杂时序偏离，也能提升告警解释性。

## 第 11 页：系统实现，约 40 秒

系统后端使用 Flask 和 Flask-SQLAlchemy，数据库支持 MySQL，模型推理使用 PyTorch，数据处理使用 Pandas、NumPy 和 Scikit-learn。前端使用 Vue，并通过 WebSocket 接收实时状态。
实现中重点做了三件事：设备上报接口使用 X-API-Key 做身份校验；模型、标准化器、阈值和版本信息统一管理；数据接收和模型检测解耦，上报后先写库，再异步执行检测任务。

## 第 12 到 16 页：测试与结果分析，约 80 秒

测试从检测准确性、系统实时性和持续训练三个方面进行。评价指标包括 Accuracy、Precision、Recall 和 F1-score。燃气安全场景中漏报风险高，所以除准确率外，我重点关注召回率和 F1。
对比结果显示：固定阈值法准确率 0.842，F1 为 0.740；3-Sigma 召回率高但误报较多，F1 为 0.809；LSTM AutoEncoder 准确率达到 0.893，F1-score 达到 0.852，综合效果最好。
阈值实验表明，阈值越高误报越少，但漏报风险也会增加。92% 分位点附近取得较优 F1-score，对应阈值为 0.704。
实时性测试中，从报文接收、入库、窗口构造、模型推理到前端刷新，端到端平均耗时 0.68 秒，最大耗时 1.26 秒，满足秒级监测要求。
持续训练实验说明，数据分布偏移会降低模型效果，而引入新数据训练候选模型后，准确率和 F1 都得到恢复。

## 第 17 页：典型案例，约 30 秒

以流量突变为例，第 6 到第 7 个时间步出现明显流量激增，模型重构结果仍接近正常用气模式，因此原始序列和重构序列之间的误差迅速增大。当误差超过阈值后，系统生成流量异常告警。
这说明模型不是只判断单点是否越界，而是利用一段时间窗口判断整体时序模式是否偏离正常状态。

## 第 18 页：总结与展望，约 40 秒

最后总结一下。本文完成了面向物联网智能燃气表的异常检测系统。算法层面，设计了基于 LSTM AutoEncoder 的多维时序异常检测方法；系统层面，实现了设备接入、实时推理、告警生成、工单流转、可视化看板和模型版本管理；测试层面，F1-score 达到 0.852，端到端平均响应时间为 0.68 秒。
目前不足是实验主要基于模拟数据和本地测试环境，尚未在大规模真实燃气表网络中长期运行。后续可以接入真实企业数据，并尝试 GRU AutoEncoder、Transformer 等模型，进一步增强泛化能力和异常解释能力。
我的汇报到此结束，感谢各位老师。
"""


def rewrite_ppt(source: Path, target: Path) -> None:
    tmp = target.with_suffix(".tmp.pptx")
    with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", item.filename)
            if match:
                slide_no = int(match.group(1))
                replacements = SLIDE_TEXTS.get(slide_no)
                if replacements is not None:
                    root = ET.fromstring(data)
                    text_nodes = root.findall(".//a:t", NS)
                    if len(text_nodes) != len(replacements):
                        raise ValueError(
                            f"slide {slide_no} text count mismatch: "
                            f"{len(text_nodes)} nodes, {len(replacements)} replacements"
                        )
                    for node, new_text in zip(text_nodes, replacements):
                        node.text = new_text
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            zout.writestr(item, data)
    tmp.replace(target)


def make_docx(markdown_text: str, path: Path) -> None:
    lines = markdown_text.splitlines()
    body_parts: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            body_parts.append("<w:p/>")
            continue
        if line.startswith("# "):
            style = "Title"
            text = line[2:]
        elif line.startswith("## "):
            style = "Heading1"
            text = line[3:]
        else:
            style = "Normal"
            text = line
        body_parts.append(
            "<w:p>"
            f"<w:pPr><w:pStyle w:val=\"{style}\"/></w:pPr>"
            "<w:r><w:t xml:space=\"preserve\">"
            f"{html.escape(text)}"
            "</w:t></w:r>"
            "</w:p>"
        )

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
        'xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:w10="urn:schemas-microsoft-com:office:word" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
        'xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk" '
        'xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml" '
        'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
        'mc:Ignorable="w14 wp14">'
        "<w:body>"
        + "".join(body_parts)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
        'w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
        "</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/><w:qFormat/></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title">'
        '<w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:qFormat/>'
        '<w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1">'
        '<w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:qFormat/>'
        '<w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )

    tmp = path.with_suffix(".tmp.docx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/document.xml", document_xml)
        z.writestr("word/styles.xml", styles)
    tmp.replace(path)


def main() -> None:
    if not PPT.exists():
        raise FileNotFoundError(PPT)
    if not BACKUP.exists():
        shutil.copy2(PPT, BACKUP)
    rewrite_ppt(PPT, PPT)
    shutil.copy2(PPT, REPORT_PPT)
    SPEECH_MD.write_text(SPEECH, encoding="utf-8", newline="\n")
    make_docx(SPEECH, SPEECH_DOCX)
    print(PPT)
    print(REPORT_PPT)
    print(SPEECH_MD)
    print(SPEECH_DOCX)


if __name__ == "__main__":
    main()
