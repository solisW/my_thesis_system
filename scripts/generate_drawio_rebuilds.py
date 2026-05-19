from __future__ import annotations

import base64
import html
import os
import struct
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PICTURES = ROOT / "picturesfinal"
OUT = PICTURES / "drawio_rebuilds"


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as f:
        sig = f.read(24)
    if sig[:8] != b"\x89PNG\r\n\x1a\n":
        return 1600, 900
    return struct.unpack(">II", sig[16:24])


class Page:
    def __init__(self, name: str, width: int = 1600, height: int = 1000):
        self.name = name
        self.width = width
        self.height = height
        self.cells: list[str] = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
        self.next_id = 2

    def _id(self) -> str:
        value = str(self.next_id)
        self.next_id += 1
        return value

    def text(self, value: str, x: int, y: int, w: int, h: int, size: int = 20) -> str:
        return self.box(value, x, y, w, h, style=f"text;html=1;strokeColor=none;fillColor=none;fontSize={size};")

    def box(self, value: str, x: int, y: int, w: int, h: int, style: str | None = None) -> str:
        cid = self._id()
        style = style or "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=18;"
        self.cells.append(
            f'<mxCell id="{cid}" value="{esc(value)}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
        )
        return cid

    def ellipse(self, value: str, x: int, y: int, w: int, h: int) -> str:
        return self.box(
            value,
            x,
            y,
            w,
            h,
            "ellipse;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=18;",
        )

    def attribute(self, value: str, x: int, y: int, w: int = 120, h: int = 50, primary: bool = False) -> str:
        label = f"<u>{esc(value)}</u>" if primary else value
        return self.box(
            label,
            x,
            y,
            w,
            h,
            "ellipse;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=16;",
        )

    def actor(self, value: str, x: int, y: int) -> str:
        return self.box(
            value,
            x,
            y,
            70,
            130,
            "shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;outlineConnect=0;fontSize=18;",
        )

    def diamond(self, value: str, x: int, y: int, w: int = 150, h: int = 90) -> str:
        return self.box(
            value,
            x,
            y,
            w,
            h,
            "rhombus;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=17;",
        )

    def terminator(self, value: str, x: int, y: int, w: int = 210, h: int = 60) -> str:
        return self.box(
            value,
            x,
            y,
            w,
            h,
            "rounded=1;arcSize=50;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=17;",
        )

    def data_io(self, value: str, x: int, y: int, w: int = 230, h: int = 65) -> str:
        return self.box(
            value,
            x,
            y,
            w,
            h,
            "shape=parallelogram;perimeter=parallelogramPerimeter;whiteSpace=wrap;html=1;fixedSize=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=17;",
        )

    def process(self, value: str, x: int, y: int, w: int = 230, h: int = 65) -> str:
        return self.box(
            value,
            x,
            y,
            w,
            h,
            "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=17;",
        )

    def preparation(self, value: str, x: int, y: int, w: int = 240, h: int = 65) -> str:
        return self.box(
            value,
            x,
            y,
            w,
            h,
            "shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;html=1;fixedSize=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=17;",
        )

    def predefined_process(self, value: str, x: int, y: int, w: int = 240, h: int = 65) -> str:
        return self.box(
            value,
            x,
            y,
            w,
            h,
            "shape=process;whiteSpace=wrap;html=1;backgroundOutline=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=17;",
        )

    def document(self, value: str, x: int, y: int, w: int = 230, h: int = 70) -> str:
        return self.box(
            value,
            x,
            y,
            w,
            h,
            "shape=document;whiteSpace=wrap;html=1;boundedLbl=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=17;",
        )

    def annotation(self, value: str, x: int, y: int, w: int = 220, h: int = 80) -> str:
        return self.box(
            value,
            x,
            y,
            w,
            h,
            "shape=note;whiteSpace=wrap;html=1;size=16;fillColor=#ffffff;strokeColor=#000000;strokeWidth=1;fontSize=15;",
        )

    def parallel_bar(self, x: int, y: int, w: int = 260) -> str:
        return self.box(
            "",
            x,
            y,
            w,
            10,
            "rounded=0;whiteSpace=wrap;html=1;fillColor=#000000;strokeColor=#000000;strokeWidth=1;",
        )

    def loop_limit(self, value: str, x: int, y: int, upper: bool, w: int = 230, h: int = 60) -> str:
        direction = "north" if upper else "south"
        return self.box(
            value,
            x,
            y,
            w,
            h,
            f"shape=trapezoid;direction={direction};whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=16;",
        )

    def table(self, title: str, fields: list[str], x: int, y: int, w: int = 230) -> str:
        value = "<b>" + esc(title) + "</b><hr/>" + "<br/>".join(esc(f) for f in fields)
        return self.box(value, x, y, w, 42 + 24 * max(1, len(fields)), "swimlane;html=1;whiteSpace=wrap;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=15;")

    def edge(self, src: str, dst: str, label: str = "", dashed: bool = False) -> str:
        cid = self._id()
        dash = "dashed=1;" if dashed else ""
        self.cells.append(
            f'<mxCell id="{cid}" value="{esc(label)}" style="endArrow=block;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;strokeWidth=2;{dash}fontSize=14;" edge="1" parent="1" source="{src}" target="{dst}">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
        )
        return cid

    def routed_edge(self, src: str, dst: str, points: list[tuple[int, int]], label: str = "", dashed: bool = False) -> str:
        cid = self._id()
        dash = "dashed=1;" if dashed else ""
        point_xml = "".join(f'<mxPoint x="{x}" y="{y}" as="point"/>' for x, y in points)
        self.cells.append(
            f'<mxCell id="{cid}" value="{esc(label)}" style="endArrow=block;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;strokeWidth=2;{dash}fontSize=14;" edge="1" parent="1" source="{src}" target="{dst}">'
            f'<mxGeometry relative="1" as="geometry"><Array as="points">{point_xml}</Array></mxGeometry></mxCell>'
        )
        return cid

    def point_edge(self, x1: int, y1: int, x2: int, y2: int, label: str = "", dashed: bool = False) -> str:
        cid = self._id()
        dash = "dashed=1;" if dashed else ""
        self.cells.append(
            f'<mxCell id="{cid}" value="{esc(label)}" style="endArrow=block;html=1;rounded=0;strokeWidth=2;{dash}fontSize=14;" edge="1" parent="1">'
            f'<mxGeometry relative="1" as="geometry"><mxPoint x="{x1}" y="{y1}" as="sourcePoint"/><mxPoint x="{x2}" y="{y2}" as="targetPoint"/></mxGeometry></mxCell>'
        )
        return cid

    def line(self, src: str, dst: str, label: str = "") -> str:
        cid = self._id()
        self.cells.append(
            f'<mxCell id="{cid}" value="{esc(label)}" style="endArrow=none;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;strokeWidth=2;fontSize=14;" edge="1" parent="1" source="{src}" target="{dst}">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
        )
        return cid

    def straight_line(self, src: str, dst: str, label: str = "") -> str:
        cid = self._id()
        self.cells.append(
            f'<mxCell id="{cid}" value="{esc(label)}" style="endArrow=none;html=1;rounded=0;strokeWidth=2;fontSize=14;" edge="1" parent="1" source="{src}" target="{dst}">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
        )
        return cid

    def routed_line(self, src: str, dst: str, points: list[tuple[int, int]], label: str = "") -> str:
        cid = self._id()
        point_xml = "".join(f'<mxPoint x="{x}" y="{y}" as="point"/>' for x, y in points)
        self.cells.append(
            f'<mxCell id="{cid}" value="{esc(label)}" style="endArrow=none;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;strokeWidth=2;fontSize=14;" edge="1" parent="1" source="{src}" target="{dst}">'
            f'<mxGeometry relative="1" as="geometry"><Array as="points">{point_xml}</Array></mxGeometry></mxCell>'
        )
        return cid

    def image(self, path: Path, x: int, y: int, w: int, h: int) -> str:
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return self.box("", x, y, w, h, f"shape=image;verticalLabelPosition=bottom;verticalAlign=top;imageAspect=1;aspect=fixed;image=data:image/png,{data};")

    def segment(self, x: int, y: int, w: int, h: int = 2) -> str:
        return self.box(
            "",
            x,
            y,
            w,
            h,
            "rounded=0;whiteSpace=wrap;html=1;fillColor=#000000;strokeColor=#000000;strokeWidth=0;",
        )

    def cylinder(self, value: str, x: int, y: int, w: int, h: int) -> str:
        return self.box(
            value,
            x,
            y,
            w,
            h,
            "shape=cylinder;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=15;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=18;",
        )

    def dfd_process(self, value: str, x: int, y: int, w: int = 210, h: int = 80) -> str:
        return self.box(
            value,
            x,
            y,
            w,
            h,
            "ellipse;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=17;",
        )

    def data_store(self, value: str, x: int, y: int, w: int = 220, h: int = 65) -> str:
        return self.box(
            value,
            x,
            y,
            w,
            h,
            "shape=partialRectangle;whiteSpace=wrap;html=1;right=0;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=17;",
        )

    def dashed_vline(self, x: int, y: int, h: int) -> str:
        return self.box(
            "",
            x,
            y,
            1,
            h,
            "shape=line;html=1;strokeWidth=2;dashed=1;",
        )

    def xml(self) -> str:
        body = "".join(self.cells)
        return (
            f'<diagram name="{esc(self.name)}">'
            f'<mxGraphModel dx="1422" dy="794" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{self.width}" pageHeight="{self.height}" math="0" shadow="0">'
            f"<root>{body}</root></mxGraphModel></diagram>"
        )


def use_case(title: str, actors: list[str], cases: list[str], links: dict[str, list[str]]) -> Page:
    p = Page(title, 1400, 900)
    boundary = p.box(title, 260, 70, 840, 700, "rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#000000;strokeWidth=2;fontSize=22;verticalAlign=top;spacingTop=15;")
    actor_ids = {a: p.actor(a, 80 if i % 2 == 0 else 1180, 150 + (i // 2) * 210) for i, a in enumerate(actors)}
    case_ids = {}
    cols = 3
    for i, c in enumerate(cases):
        x = 330 + (i % cols) * 250
        y = 160 + (i // cols) * 125
        case_ids[c] = p.ellipse(c, x, y, 180, 70)
    for actor, cs in links.items():
        for c in cs:
            if actor in actor_ids and c in case_ids:
                p.line(actor_ids[actor], case_ids[c])
    return p


def clean_total_use_case() -> Page:
    p = Page("系统总用例图", 1300, 900)
    p.text("智能燃气表异常检测系统总用例图", 380, 30, 540, 50, 26)

    admin = p.actor("管理员", 90, 360)
    engineer = p.actor("工程师", 1110, 410)
    device = p.actor("燃气表设备", 1110, 150)
    trainer = p.actor("训练服务", 1110, 665)

    cases = {
        "设备接入": p.ellipse("设备接入", 500, 125, 210, 75),
        "监控管理": p.ellipse("监控管理", 500, 250, 210, 75),
        "告警管理": p.ellipse("告警管理", 500, 375, 210, 75),
        "工单处理": p.ellipse("工单处理", 500, 500, 210, 75),
        "模型训练": p.ellipse("模型训练", 500, 625, 210, 75),
        "系统管理": p.ellipse("系统管理", 500, 750, 210, 75),
    }

    for name in ["设备接入", "监控管理", "告警管理", "工单处理", "模型训练", "系统管理"]:
        p.line(admin, cases[name])
    for name in ["告警管理", "工单处理"]:
        p.line(engineer, cases[name])
    for name in ["设备接入", "监控管理"]:
        p.line(device, cases[name])
    p.line(trainer, cases["模型训练"])
    return p


def hierarchy(title: str, groups: dict[str, list[str]]) -> Page:
    p = Page(title, 1900, 1050)
    root = p.box(title, 620, 60, 620, 70, "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=3;fontSize=24;")
    count = len(groups)
    gap = 260
    start = 80
    for i, (g, children) in enumerate(groups.items()):
        x = start + i * gap
        parent = p.box(g, x, 260, 190, 60)
        p.edge(root, parent)
        prev = parent
        for j, child in enumerate(children):
            node = p.box(child, x, 390 + j * 110, 190, 60)
            p.line(prev, node)
            prev = node
    return p


def system_function_structure_page() -> Page:
    p = Page("系统功能结构图", 1840, 760)
    title_style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=3;fontSize=24;"
    role_style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=19;"
    function_style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=18;spacing=6;"

    def vertical_text(text: str) -> str:
        return "\n".join(text)

    p.box("智能燃气表异常检测系统", 620, 45, 600, 65, title_style)
    columns = [
        ("管理员", ["登录认证", "用户管理", "设备管理", "监控查看", "告警确认", "工单派发", "模型训练", "参数设置"]),
        ("工程师", ["登录认证", "告警查看", "工单接收", "现场处理", "处理反馈", "个人信息维护"]),
        ("设备端", ["设备注册", "密钥校验", "数据上报", "状态同步"]),
        ("系统服务", ["数据预处理", "异常检测", "告警生成", "模型版本管理", "持续训练"]),
    ]

    column_centers = [280, 720, 1110, 1505]
    role_y = 165
    role_w = 170
    role_h = 58
    function_y = 345
    function_w = 54
    function_h = 250
    function_gap = 16
    title_center_x = 920
    title_bottom_y = 110
    role_bus_y = 135
    function_bus_y = 302

    p.segment(title_center_x, title_bottom_y, 2, role_bus_y - title_bottom_y)
    p.segment(column_centers[0], role_bus_y, column_centers[-1] - column_centers[0], 2)

    for index, (role_name, functions) in enumerate(columns):
        center_x = column_centers[index]
        role_x = center_x - role_w // 2
        p.segment(center_x, role_bus_y, 2, role_y - role_bus_y)
        p.box(role_name, role_x, role_y, role_w, role_h, role_style)
        total_w = len(functions) * function_w + (len(functions) - 1) * function_gap
        start_x = center_x - total_w // 2
        p.segment(center_x, role_y + role_h, 2, function_bus_y - (role_y + role_h))
        p.segment(start_x + function_w // 2, function_bus_y, total_w - function_w, 2)
        for function_index, function_name in enumerate(functions):
            x = start_x + function_index * (function_w + function_gap)
            child_center_x = x + function_w // 2
            p.segment(child_center_x, function_bus_y, 2, function_y - function_bus_y)
            p.box(vertical_text(function_name), x, function_y, function_w, function_h, function_style)
    return p


def unified_device_access_page() -> Page:
    p = Page("真实/模拟设备统一接入流程图", 1500, 1320)
    p.text("真实/模拟设备统一接入流程图", 470, 35, 560, 50, 26)

    start = p.terminator("开始", 620, 90, 260, 62)
    real = p.data_io("真实设备\n上报读数", 250, 190, 260, 75)
    sim = p.data_io("模拟设备\n生成读数", 990, 190, 260, 75)
    receive = p.data_io("统一接入接口\n接收数据", 620, 320, 260, 75)
    auth = p.predefined_process("设备身份校验", 620, 430, 260, 72)
    valid = p.diamond("设备是否合法", 665, 535, 170, 105)
    reject = p.document("记录接入失败日志", 990, 555, 260, 80)
    reject_end = p.terminator("结束", 1000, 675, 240, 62)

    parse = p.process("解析上报字段", 620, 690, 260, 72)
    normalize = p.preparation("统一数据格式转换", 620, 800, 270, 76)
    raw = p.data_io("写入原始数据表", 620, 915, 260, 75)
    reading = p.data_io("写入监测读数表", 620, 1025, 260, 75)
    detect = p.predefined_process("进入异常检测流程", 620, 1135, 260, 72)
    end = p.terminator("结束", 630, 1240, 240, 62)

    p.edge(start, real)
    p.edge(start, sim)
    p.edge(real, receive)
    p.edge(sim, receive)
    p.edge(receive, auth)
    p.edge(auth, valid)
    p.edge(valid, reject, "否")
    p.edge(reject, reject_end)
    p.edge(valid, parse, "是")
    p.edge(parse, normalize)
    p.edge(normalize, raw)
    p.edge(raw, reading)
    p.edge(reading, detect)
    p.edge(detect, end)
    return p


def system_data_flow_page() -> Page:
    p = Page("系统数据流图", 1650, 980)
    p.text("智能燃气表异常检测系统数据流图", 500, 35, 650, 50, 26)

    entity_style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=18;"
    device = p.box("燃气表设备", 80, 190, 160, 65, entity_style)
    admin = p.box("管理员", 80, 520, 160, 65, entity_style)
    engineer = p.box("工程师", 1390, 520, 160, 65, entity_style)

    access = p.dfd_process("P1\n数据接入", 350, 170)
    preprocess = p.dfd_process("P2\n数据预处理", 610, 170)
    detect = p.dfd_process("P3\n异常检测", 870, 170)
    alarm = p.dfd_process("P4\n告警生成", 1130, 170)
    work_order = p.dfd_process("P5\n工单处理", 1130, 500)
    monitor = p.dfd_process("P6\n监控展示", 610, 500)
    training = p.dfd_process("P7\n模型训练", 870, 500)

    device_store = p.data_store("D1 设备数据", 350, 780)
    reading_store = p.data_store("D2 读数数据", 610, 780)
    alarm_store = p.data_store("D3 告警数据", 870, 780)
    order_store = p.data_store("D4 工单数据", 1130, 780)
    model_store = p.data_store("D5 模型元数据", 1390, 780)

    p.edge(device, access, "设备注册/读数")
    p.edge(access, preprocess, "统一数据")
    p.edge(preprocess, detect, "特征窗口")
    p.edge(detect, alarm, "异常结果")
    p.edge(alarm, work_order, "告警事件")
    p.edge(admin, monitor, "查询请求")
    p.edge(monitor, admin, "监控结果")
    p.edge(admin, work_order, "派单/复核")
    p.edge(work_order, engineer, "工单任务")
    p.edge(engineer, work_order, "处理反馈")
    p.edge(training, detect, "激活模型")
    p.edge(preprocess, training, "训练样本")

    p.edge(access, device_store)
    p.edge(preprocess, reading_store)
    p.edge(alarm, alarm_store)
    p.edge(work_order, order_store)
    p.edge(training, model_store)
    p.edge(reading_store, monitor)
    p.edge(alarm_store, monitor)
    p.edge(order_store, monitor)
    p.edge(model_store, detect)
    return p


def transform_boundary_page() -> Page:
    p = Page("数据流边界划分图", 1550, 860)
    p.text("数据流边界划分图", 515, 35, 520, 50, 26)

    p.dashed_vline(470, 130, 590)
    p.dashed_vline(1030, 130, 590)
    p.text("输入流", 210, 105, 180, 35, 20)
    p.text("变换中心", 665, 105, 220, 35, 20)
    p.text("输出流", 1175, 105, 180, 35, 20)

    device = p.box("燃气表设备", 90, 250, 160, 65)
    user = p.box("管理员/工程师", 90, 500, 160, 65)
    receive = p.dfd_process("接收外部数据", 300, 250)
    request = p.dfd_process("接收用户请求", 300, 500)

    validate = p.dfd_process("身份校验", 560, 250)
    preprocess = p.dfd_process("数据预处理", 760, 250)
    detect = p.dfd_process("异常检测", 760, 430)
    dispatch = p.dfd_process("业务调度", 560, 500)

    alarm = p.dfd_process("输出告警", 1110, 250)
    order = p.dfd_process("输出工单", 1110, 430)
    view = p.dfd_process("输出看板", 1110, 610)
    store = p.data_store("业务数据库", 700, 670)

    p.edge(device, receive, "上报数据")
    p.edge(user, request, "操作请求")
    p.edge(receive, validate)
    p.edge(validate, preprocess)
    p.edge(preprocess, detect)
    p.edge(request, dispatch)
    p.edge(dispatch, detect)
    p.edge(detect, alarm)
    p.edge(alarm, order)
    p.edge(dispatch, view)
    p.edge(preprocess, store)
    p.edge(detect, store)
    p.edge(order, store)
    p.edge(store, view)
    return p


def data_transport_layer_page() -> Page:
    p = Page("数据传输层流程图", 1500, 1400)
    p.text("数据传输层流程图", 510, 35, 480, 50, 26)

    x = 625
    start = p.terminator("开始", x, 90, 260, 62)
    source = p.data_io("真实设备/模拟设备\n产生读数数据", x - 10, 185, 280, 80)
    package = p.process("封装上报报文", x, 300, 260, 72)
    upload = p.data_io("HTTP/JSON\n上报数据", x, 410, 260, 76)
    receive = p.data_io("统一接入接口\n接收请求", x, 525, 260, 76)
    auth = p.predefined_process("设备身份校验", x, 635, 260, 72)
    valid = p.diamond("身份是否合法", x + 45, 740, 170, 105)

    reject = p.document("记录传输失败日志", 1010, 760, 260, 80)
    reject_end = p.terminator("结束", 1020, 880, 240, 62)

    parse = p.process("解析报文字段", x, 890, 260, 72)
    normalize = p.preparation("数据格式转换", x - 5, 1000, 270, 76)
    raw = p.data_io("写入原始数据表", x, 1115, 260, 76)
    reading = p.data_io("写入监测读数表", x, 1230, 260, 76)
    end = p.terminator("进入异常检测流程", x, 1340, 260, 62)

    p.edge(start, source)
    p.edge(source, package)
    p.edge(package, upload)
    p.edge(upload, receive)
    p.edge(receive, auth)
    p.edge(auth, valid)
    p.edge(valid, reject, "否")
    p.edge(reject, reject_end)
    p.edge(valid, parse, "是")
    p.edge(parse, normalize)
    p.edge(normalize, raw)
    p.edge(raw, reading)
    p.edge(reading, end)
    return p


def level1_structure_page() -> Page:
    p = Page("一级结构图", 1500, 820)
    p.text("一级结构图", 545, 35, 410, 50, 26)

    root = p.box("智能燃气表异常检测系统", 565, 90, 370, 70)
    input_mod = p.box("输入处理模块", 150, 280, 230, 70)
    transform_mod = p.box("核心变换模块", 635, 280, 230, 70)
    output_mod = p.box("输出处理模块", 1120, 280, 230, 70)

    p.edge(root, input_mod)
    p.edge(root, transform_mod)
    p.edge(root, output_mod)

    for i, text in enumerate(["设备接入", "请求接收", "数据校验"]):
        node = p.box(text, 105 + i * 145, 480, 120, 58)
        p.line(input_mod, node)
    for i, text in enumerate(["数据预处理", "异常检测", "模型训练"]):
        node = p.box(text, 590 + i * 145, 480, 120, 58)
        p.line(transform_mod, node)
    for i, text in enumerate(["告警输出", "工单输出", "看板展示"]):
        node = p.box(text, 1075 + i * 145, 480, 120, 58)
        p.line(output_mod, node)
    return p


def level2_structure_page() -> Page:
    p = Page("二级结构图", 1760, 1020)
    p.text("二级结构图", 675, 35, 410, 50, 26)

    root = p.box("核心变换模块", 710, 90, 340, 65)
    modules = [
        ("数据预处理", ["字段解析", "缺失处理", "特征标准化", "窗口构造"]),
        ("异常检测", ["模型加载", "序列重构", "误差计算", "阈值判断"]),
        ("告警工单", ["告警生成", "工单创建", "派单处理", "反馈闭环"]),
        ("持续训练", ["样本清洗", "模型训练", "指标评估", "版本激活"]),
    ]
    start_x = 110
    gap = 410
    for i, (name, children) in enumerate(modules):
        x = start_x + i * gap
        parent = p.box(name, x, 270, 220, 62)
        p.edge(root, parent)
        for j, child in enumerate(children):
            node = p.box(child, x + 35, 420 + j * 105, 150, 56)
            p.line(parent, node)
    return p


def framework_processing_sequence_page() -> Page:
    p = Page("框架处理顺序图", 1350, 760)
    p.text("图 3-2 框架处理顺序图", 440, 675, 470, 50, 24)

    box_style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=18;"
    vertical_style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=20;spacing=8;"

    def vertical_text(text: str) -> str:
        return "\n".join(text)

    request = p.box(vertical_text("页面请求"), 75, 95, 80, 430, vertical_style)
    controller = p.box("根据URL匹配请求\n\nAction\n控制器", 380, 105, 110, 390, box_style)
    manager = p.box("Manager 层\n业务调度与事务处理", 700, 95, 360, 100, box_style)
    domain = p.box("Domain / DAO 层\nDeviceDao、ReadingDao、AlertDao、WorkOrderDao", 700, 285, 360, 90, box_style)
    database = p.cylinder("数据库", 790, 430, 180, 130)

    p.point_edge(155, 180, 380, 180, "页面发送请求")
    p.text("请求URL", 230, 205, 120, 30, 16)
    p.point_edge(490, 145, 700, 145, "调用业务层处理")
    p.point_edge(700, 185, 490, 185, "返回结果", True)

    p.point_edge(880, 195, 880, 285, "调用")
    p.point_edge(920, 285, 920, 195, "返回结果", True)
    p.point_edge(850, 375, 850, 430, "连接数据库")
    p.point_edge(930, 430, 930, 375, "数据库响应", True)

    p.point_edge(380, 390, 155, 390, "返回处理结果", True)
    return p


def er_page(title: str, entities: dict[str, list[str]], rels: list[tuple[str, str, str]]) -> Page:
    return overall_er_page(title, entities, rels)


def single_entity_er_page(title: str, entity: str, attrs: list[str]) -> Page:
    p = Page(title, 1280, 780)
    p.text(title, 425, 35, 430, 50, 26)
    entity_node = p.box(entity, 560, 360, 160, 55, "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=20;")

    positions = [
        (120, 365), (185, 235), (345, 140), (545, 115),
        (750, 140), (930, 235), (1010, 365), (930, 505),
        (750, 610), (545, 635), (340, 595),
    ]
    for i, attr in enumerate(attrs):
        x, y = positions[i % len(positions)]
        primary = i == 0 or attr.endswith("ID") or attr.endswith("编号")
        attr_node = p.attribute(attr, x, y, 130, 52, primary)
        p.straight_line(entity_node, attr_node)
    return p


def overall_er_page(title: str, entities: dict[str, list[str]], rels: list[tuple[str, str, str]]) -> Page:
    p = Page(title, 1600, 980)
    p.text(title, 575, 35, 450, 50, 26)

    entity_style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=19;"
    positions = {
        "设备": (150, 250),
        "读数": (470, 250),
        "告警": (790, 250),
        "工单": (1110, 250),
        "训练数据": (150, 700),
        "模型元数据": (470, 700),
        "用户": (1110, 700),
    }
    ids: dict[str, str] = {}
    for name in entities:
        x, y = positions.get(name, (120 + len(ids) * 180, 160))
        ids[name] = p.box(name, x, y, 150, 55, entity_style)

        attrs = entities[name][:2]
        attr_positions = [(x - 80, y - 85), (x + 120, y - 85)]
        for i, attr in enumerate(attrs):
            ax, ay = attr_positions[i]
            attr_node = p.attribute(attr, ax, ay, 110, 46, i == 0)
            p.straight_line(ids[name], attr_node)

    rel_positions = {
        ("设备", "读数"): (315, 255),
        ("读数", "告警"): (635, 255),
        ("告警", "工单"): (955, 255),
        ("训练数据", "模型元数据"): (315, 705),
        ("模型元数据", "读数"): (495, 475),
        ("用户", "工单"): (1135, 475),
    }
    rel_names = {
        ("设备", "读数"): "产生",
        ("读数", "告警"): "触发",
        ("告警", "工单"): "生成",
        ("用户", "工单"): "处理",
        ("模型元数据", "读数"): "检测",
        ("训练数据", "模型元数据"): "训练",
    }
    clean_rels = [
        ("设备", "读数", "1:N"),
        ("读数", "告警", "1:0..1"),
        ("告警", "工单", "1:0..1"),
        ("训练数据", "模型元数据", "N:1"),
        ("模型元数据", "读数", "1:N"),
        ("用户", "工单", "1:N"),
    ]
    cardinality = {
        "1:N": ("1", "N"),
        "1:0..1": ("1", "0..1"),
        "N:1": ("N", "1"),
    }
    for index, (a, b, label) in enumerate(clean_rels):
        if a not in ids or b not in ids:
            continue
        rx, ry = rel_positions.get((a, b), rel_positions.get((b, a), (760, 600)))
        rel_name = rel_names.get((a, b), rel_names.get((b, a), "关联"))
        rel_node = p.diamond(rel_name, rx, ry, 100, 60)
        left_label, right_label = cardinality.get(label, ("", ""))
        p.straight_line(ids[a], rel_node, left_label)
        p.straight_line(rel_node, ids[b], right_label)
    return p


def flow_page(title: str, steps: list[str], decisions: set[int] | None = None) -> Page:
    p = Page(title, 1200, 1100)
    p.text(title, 380, 30, 440, 50, 26)
    decisions = decisions or set()
    ids = []
    for i, step in enumerate(steps):
        y = 110 + i * 105
        if i == 0 or i == len(steps) - 1:
            ids.append(p.terminator(step, 470, y))
        elif i in decisions:
            ids.append(p.diamond(step, 500, y))
        elif any(keyword in step for keyword in ["接收", "读取", "上报", "采集", "输入", "返回", "写入"]):
            ids.append(p.data_io(step, 460, y))
        else:
            ids.append(p.process(step, 460, y))
    for a, b in zip(ids, ids[1:]):
        p.edge(a, b)
    return p


def system_overall_flow_page() -> Page:
    p = Page("系统总体流程图", 1350, 1080)
    p.text("系统总体流程图", 455, 30, 440, 50, 26)

    start = p.terminator("开始", 555, 105)
    login = p.data_io("用户输入账号密码", 545, 195)
    auth = p.predefined_process("登录认证服务", 545, 285)
    enter = p.process("进入系统首页", 545, 375)
    fork = p.parallel_bar(535, 475, 260)
    monitor = p.predefined_process("监控展示模块", 260, 535)
    alarm = p.predefined_process("异常检测与告警模块", 545, 535)
    work = p.predefined_process("工单处理模块", 830, 535)
    join = p.parallel_bar(535, 655, 260)
    report = p.document("形成运行记录与处理结果", 545, 720)
    feedback = p.process("反馈闭环并更新状态", 545, 825)
    end = p.terminator("结束", 555, 930)
    note = p.annotation("并行方式表示用户可在监控、告警、工单模块间切换处理。", 970, 660)

    p.edge(start, login)
    p.edge(login, auth)
    p.edge(auth, enter)
    p.edge(enter, fork)
    p.edge(fork, monitor)
    p.edge(fork, alarm)
    p.edge(fork, work)
    p.edge(monitor, join)
    p.edge(alarm, join)
    p.edge(work, join)
    p.edge(join, report)
    p.edge(report, feedback)
    p.edge(feedback, end)
    p.line(note, join)
    return p


def anomaly_detection_flow_page() -> Page:
    p = Page("异常检测业务流程图", 1500, 1420)
    p.text("异常检测业务流程图", 510, 30, 480, 50, 26)

    center_x = 635
    start = p.terminator("开始", center_x, 90)
    input_data = p.data_io("接收燃气表上报数据", center_x - 10, 180)
    validate = p.diamond("数据是否合法", center_x + 30, 285)

    reject = p.document("记录无效数据\n返回错误信息", 220, 300)
    reject_end = p.terminator("结束", 230, 430)

    load_window = p.data_io("读取设备最近24点数据", center_x - 10, 430)
    enough = p.diamond("窗口是否完整", center_x + 30, 540)

    startup = p.predefined_process("启动阶段规则评分", 1010, 530)
    startup_result = p.document("输出启动阶段检测结果", 1010, 650)
    startup_end = p.terminator("结束", 1025, 770)

    prep = p.preparation("特征清洗与标准化", center_x - 10, 690)
    window = p.predefined_process("构造模型输入窗口\n24 × 7", center_x - 10, 790)
    infer = p.predefined_process("LSTM AutoEncoder重构", center_x - 10, 890)
    score = p.process("计算重构误差\n生成异常得分", center_x - 10, 990)
    threshold = p.diamond("异常得分\n是否超过阈值", center_x + 30, 1100)

    normal = p.document("记录正常检测结果", 220, 1120)
    normal_end = p.terminator("结束", 230, 1245)

    abnormal = p.document("写入异常事件", 1010, 1120)
    alarm = p.predefined_process("生成告警并联动工单", 1010, 1240)
    alarm_end = p.terminator("结束", 1025, 1360)

    p.edge(start, input_data)
    p.edge(input_data, validate)
    p.edge(validate, reject, "否")
    p.edge(reject, reject_end)
    p.edge(validate, load_window, "是")
    p.edge(load_window, enough)
    p.edge(enough, startup, "否")
    p.edge(startup, startup_result)
    p.edge(startup_result, startup_end)
    p.edge(enough, prep, "是")
    p.edge(prep, window)
    p.edge(window, infer)
    p.edge(infer, score)
    p.edge(score, threshold)
    p.edge(threshold, normal, "否")
    p.edge(normal, normal_end)
    p.edge(threshold, abnormal, "是")
    p.edge(abnormal, alarm)
    p.edge(alarm, alarm_end)
    return p


def continuous_training_flow_page() -> Page:
    p = Page("持续训练流程图", 1650, 1450)
    p.text("持续训练流程图", 585, 30, 480, 50, 26)

    x = 650
    branch_x = 1080
    start = p.terminator("开始", x, 90, 260, 62)
    trigger = p.data_io("定时触发\n训练任务", x - 5, 180, 270, 72)
    load = p.data_io("读取训练\n原始数据", x - 5, 280, 270, 72)
    enough = p.diamond("样本是否充足", x + 45, 385, 180, 105)
    no_data = p.document("样本不足日志", branch_x, 400, 260, 80)
    no_data_end = p.terminator("结束", branch_x + 10, 520, 240, 62)

    clean = p.preparation("数据清洗\n样本标注", x - 5, 535, 280, 76)
    window = p.predefined_process("构造训练窗口\n24 × 7", x - 5, 635, 280, 76)
    split = p.process("划分训练集\n验证集", x - 5, 735, 280, 76)
    train = p.predefined_process("训练 LSTM\nAutoEncoder", x - 5, 835, 280, 76)
    evaluate = p.predefined_process("计算阈值\n评估指标", x - 5, 935, 280, 76)
    pass_node = p.diamond("指标是否达标", x + 45, 1040, 180, 105)

    fail = p.document("保留旧模型\n记录日志", branch_x, 1055, 260, 86)
    fail_end = p.terminator("结束", branch_x + 10, 1180, 240, 62)

    meta = p.document("登记模型元数据", x - 5, 1190, 280, 80)
    activate = p.process("激活新模型版本", x - 5, 1290, 280, 72)
    success_end = p.terminator("结束", x + 10, 1385, 260, 62)

    p.edge(start, trigger)
    p.edge(trigger, load)
    p.edge(load, enough)
    p.edge(enough, no_data, "否")
    p.edge(no_data, no_data_end)
    p.edge(enough, clean, "是")
    p.edge(clean, window)
    p.edge(window, split)
    p.edge(split, train)
    p.edge(train, evaluate)
    p.edge(evaluate, pass_node)
    p.edge(pass_node, fail, "否")
    p.edge(fail, fail_end)
    p.edge(pass_node, meta, "是")
    p.edge(meta, activate)
    p.edge(activate, success_end)
    return p


def alert_work_order_closed_loop_flow_page() -> Page:
    p = Page("告警与工单闭环流程图", 1450, 1420)
    p.text("告警与工单闭环流程图", 465, 30, 520, 50, 26)

    x = 610
    start = p.terminator("开始", x, 90)
    score = p.predefined_process("异常检测服务\n计算异常得分", x - 15, 180)
    alarm_decision = p.diamond("是否触发告警", x + 30, 285)
    normal_record = p.document("记录正常检测结果", 240, 295)
    normal_end = p.terminator("结束", 250, 410)

    alarm = p.document("生成告警事件", x - 10, 430)
    confirm = p.diamond("管理员确认告警", x + 30, 545)
    false_alarm = p.document("标记为误报\n沉淀反馈样本", 240, 555)
    false_end = p.terminator("结束", 250, 670)

    create_order = p.predefined_process("创建工单", x - 15, 690)
    assign = p.process("派单给工程师", x - 10, 790)
    accept = p.diamond("工程师是否接单", x + 30, 890)
    reassign = p.process("重新派单\n返回派单环节", 970, 905)

    handle = p.process("现场处理并填写结果", x - 10, 1035)
    review = p.diamond("复核是否通过", x + 30, 1140)
    return_repair = p.process("退回继续处理\n返回现场处理", 970, 1155)

    close = p.document("关闭工单\n更新告警状态", x - 10, 1275)
    feedback = p.predefined_process("反馈进入训练样本\n形成闭环", 930, 1275)
    end = p.terminator("结束", 1110, 1390)

    p.edge(start, score)
    p.edge(score, alarm_decision)
    p.edge(alarm_decision, normal_record, "否")
    p.edge(normal_record, normal_end)
    p.edge(alarm_decision, alarm, "是")
    p.edge(alarm, confirm)
    p.edge(confirm, false_alarm, "否")
    p.edge(false_alarm, false_end)
    p.edge(confirm, create_order, "是")
    p.edge(create_order, assign)
    p.edge(assign, accept)
    p.edge(accept, reassign, "否")
    p.edge(accept, handle, "是")
    p.edge(handle, review)
    p.edge(review, return_repair, "否")
    p.edge(review, close, "是")
    p.edge(close, feedback)
    p.edge(feedback, end)
    return p


def lstm_encoder_structure_page() -> Page:
    p = Page("LSTM AutoEncoder模型结构图", 1500, 900)
    p.text("LSTM AutoEncoder 模型结构图", 470, 35, 560, 50, 28)

    top_style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=18;fontStyle=1;"
    module_style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;fontSize=17;"
    leaf_style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#fffde7;strokeColor=#000000;strokeWidth=2;fontSize=16;"

    root = p.box("LSTM AutoEncoder\n异常检测模型", 625, 95, 250, 80, top_style)

    input_ctrl = p.box("输入变换\n控制", 170, 280, 180, 75, module_style)
    encoder_ctrl = p.box("编码压缩\n控制\nhidden=32", 470, 270, 180, 95, module_style)
    decoder_ctrl = p.box("解码重构\n控制\nhidden=32", 770, 270, 180, 95, module_style)
    score_ctrl = p.box("误差评分\n控制", 1070, 280, 180, 75, module_style)

    for node in [input_ctrl, encoder_ctrl, decoder_ctrl, score_ctrl]:
        p.straight_line(root, node)

    input_children = [
        p.box("接收窗口\n24×7", 95, 465, 100, 90, leaf_style),
        p.box("特征\n标准化", 215, 465, 100, 90, leaf_style),
        p.box("构造批次\nbatch", 335, 465, 100, 90, leaf_style),
    ]
    encoder_children = [
        p.box("Encoder\nLSTM\n2层", 470, 455, 100, 110, leaf_style),
        p.box("隐藏状态\nh[-1]", 590, 465, 100, 90, leaf_style),
    ]
    decoder_children = [
        p.box("上下文\n向量z", 735, 465, 100, 90, leaf_style),
        p.box("重复\n24步", 855, 465, 100, 90, leaf_style),
        p.box("Decoder\nLSTM\n2层", 975, 455, 100, 110, leaf_style),
    ]
    score_children = [
        p.box("Linear\n32→7", 1095, 465, 100, 90, leaf_style),
        p.box("重构\n序列X'", 1215, 465, 100, 90, leaf_style),
        p.box("MSE\n异常得分", 1335, 465, 100, 90, leaf_style),
    ]

    for node in input_children:
        p.straight_line(input_ctrl, node)
    for node in encoder_children:
        p.straight_line(encoder_ctrl, node)
    for node in decoder_children:
        p.straight_line(decoder_ctrl, node)
    for node in score_children:
        p.straight_line(score_ctrl, node)

    p.point_edge(435, 510, 470, 510, "X")
    p.point_edge(690, 510, 735, 510, "z")
    p.point_edge(1075, 510, 1095, 510, "重构")

    return p


def data_preprocess_flow_page() -> Page:
    p = Page("数据接入与预处理流程图", 1400, 1280)
    p.text("数据接入与预处理流程图", 410, 30, 480, 50, 26)

    start = p.terminator("开始", 555, 90)
    collect = p.data_io("燃气表采集运行数据", 545, 180)
    upload = p.data_io("通过HTTP接口上报数据", 545, 270)
    auth = p.predefined_process("设备密钥校验", 545, 360)
    valid = p.diamond("设备是否合法", 590, 455)
    reject = p.document("拒绝接入并记录日志", 900, 470)
    stop = p.terminator("结束", 910, 570)
    parse = p.process("解析上报字段", 545, 585)
    field_ok = p.diamond("字段是否完整", 590, 675)
    repair = p.preparation("缺失值处理与格式修正", 900, 690)
    enrich = p.preparation("补齐设备与时间信息", 545, 805)
    raw = p.data_io("写入原始物理数据", 545, 900)
    normalize = p.preparation("特征标准化", 545, 995)
    window = p.predefined_process("时间窗口构造", 545, 1090)
    end = p.terminator("进入异常检测流程", 555, 1190)
    note = p.annotation("准备/预处理框用于表示清洗、补齐、标准化等数据预处理动作。", 895, 945)

    p.edge(start, collect)
    p.edge(collect, upload)
    p.edge(upload, auth)
    p.edge(auth, valid)
    p.edge(valid, parse, "是")
    p.edge(valid, reject, "否")
    p.edge(reject, stop)
    p.edge(parse, field_ok)
    p.edge(field_ok, enrich, "是")
    p.edge(field_ok, repair, "否")
    p.edge(repair, enrich)
    p.edge(enrich, raw)
    p.edge(raw, normalize)
    p.edge(normalize, window)
    p.edge(window, end)
    p.line(note, normalize)
    return p


def class_page(title: str, classes: dict[str, list[str]], rels: list[tuple[str, str, str]]) -> Page:
    p = Page(title, 1650, 1050)
    p.text(title, 590, 30, 470, 50, 26)
    positions = [(80, 120), (430, 120), (780, 120), (1130, 120), (80, 520), (430, 520), (780, 520), (1130, 520)]
    ids = {name: p.table(name, fields, *positions[i % len(positions)], 280) for i, (name, fields) in enumerate(classes.items())}
    for a, b, label in rels:
        if a in ids and b in ids:
            p.edge(ids[a], ids[b], label)
    return p


def sequence_page(title: str, actors: list[str], messages: list[tuple[str, str, str]]) -> Page:
    p = Page(title, 1500, 950)
    p.text(title, 520, 30, 460, 50, 26)
    ids = {}
    for i, a in enumerate(actors):
        x = 80 + i * 260
        ids[a] = p.box(a, x, 100, 170, 50)
        lifeline = p.box("", x + 85, 160, 1, 650, "shape=line;html=1;strokeWidth=2;dashed=1;")
    for i, (src, dst, msg) in enumerate(messages):
        y = 210 + i * 70
        p.text(msg, 260, y - 25, 800, 28, 15)
        if src in ids and dst in ids:
            p.edge(ids[src], ids[dst], msg)
    return p


def definitions() -> dict[str, Page]:
    common_entities = {
        "用户": ["id", "username", "password_hash", "role", "engineer_id", "created_at"],
        "设备": ["id", "meter_id", "name", "location", "api_key", "status"],
        "读数": ["id", "device_id", "timestamp", "flow", "pressure", "anomaly_score"],
        "告警": ["id", "device_id", "reading_id", "type", "severity", "status"],
        "工单": ["id", "device_id", "event_id", "engineer_id", "priority", "status"],
        "模型元数据": ["model_id", "model_path", "threshold", "metrics", "is_active"],
        "训练数据": ["meter_id", "timestamp", "features", "is_anomaly"],
    }
    defs: dict[str, Page] = {}
    defs["final_2-1_系统总用例图"] = clean_total_use_case()
    defs["final_2-2_设备接入用例图"] = use_case("设备接入用例图", ["管理员", "燃气表设备"], ["设备注册", "密钥校验", "参数配置", "数据上报", "状态同步", "设备停用"], {"管理员": ["设备注册", "参数配置", "设备停用"], "燃气表设备": ["密钥校验", "数据上报", "状态同步"]})
    defs["final_2-3_监控管理用例图"] = use_case("监控管理用例图", ["管理员", "工程师"], ["实时看板", "历史曲线", "地图定位", "设备筛选", "读数查询", "运行统计"], {"管理员": ["实时看板", "历史曲线", "地图定位", "设备筛选", "读数查询", "运行统计"], "工程师": ["实时看板", "历史曲线", "地图定位"]})
    defs["final_2-4_告警管理用例图"] = use_case("告警管理用例图", ["管理员", "工程师", "检测模型"], ["异常检测", "告警生成", "告警确认", "告警筛选", "工单联动", "反馈闭环"], {"管理员": ["告警确认", "告警筛选", "工单联动"], "工程师": ["告警确认", "反馈闭环"], "检测模型": ["异常检测", "告警生成"]})
    defs["final_2-5_工单处理用例图"] = use_case("工单处理用例图", ["管理员", "工程师"], ["创建工单", "派单处理", "接单", "现场处理", "完成反馈", "记录追踪"], {"管理员": ["创建工单", "派单处理", "记录追踪"], "工程师": ["接单", "现场处理", "完成反馈", "记录追踪"]})
    defs["final_2-6_模型训练用例图"] = use_case("模型训练用例图", ["管理员", "训练服务"], ["导入原始数据", "清洗样本", "注入异常", "训练模型", "评估指标", "版本切换"], {"管理员": ["导入原始数据", "清洗样本", "训练模型", "版本切换"], "训练服务": ["清洗样本", "注入异常", "训练模型", "评估指标"]})
    defs["final_3-1_系统功能结构图"] = system_function_structure_page()
    defs["final_3-2_框架处理顺序图"] = framework_processing_sequence_page()
    defs["final_3-2_真实模拟设备统一接入图"] = unified_device_access_page()
    defs["final_3-17_系统数据流图"] = system_data_flow_page()
    defs["final_3-18_数据流边界划分图"] = transform_boundary_page()
    defs["final_3-18-1_数据传输层图"] = data_transport_layer_page()
    defs["final_3-19_一级结构图"] = level1_structure_page()
    defs["final_3-20_二级结构图"] = level2_structure_page()
    defs["final_3-16_系统登录顺序图"] = sequence_page("系统登录顺序图", ["用户", "前端", "认证接口", "用户服务", "数据库"], [("用户", "前端", "输入账号密码"), ("前端", "认证接口", "提交登录请求"), ("认证接口", "用户服务", "校验凭据"), ("用户服务", "数据库", "查询用户"), ("数据库", "用户服务", "返回用户记录"), ("用户服务", "认证接口", "生成会话"), ("认证接口", "前端", "返回登录结果")])
    defs["final_3-12_系统总体E-R图"] = er_page("系统总体E-R图", common_entities, [("设备", "读数", "1:N"), ("读数", "告警", "1:0..1"), ("告警", "工单", "1:0..1"), ("用户", "工单", "1:N"), ("设备", "工单", "1:N"), ("模型元数据", "读数", "1:N"), ("训练数据", "模型元数据", "N:1")])
    er_attrs = {
        "final_3-3_设备E-R图": ("设备E-R图", "设备", ["设备ID", "表具编号", "设备名称", "安装位置", "所属区域", "经度", "纬度", "通信协议", "API密钥", "设备状态", "创建时间"]),
        "final_3-4_用户E-R图": ("用户E-R图", "用户", ["用户ID", "用户名", "密码哈希", "姓名", "员工编号", "手机号", "角色", "工程师ID", "是否启用", "创建时间"]),
        "final_3-5_读数E-R图": ("读数E-R图", "读数", ["读数ID", "设备ID", "时间戳", "瞬时流量", "累计用气量", "电池电压", "信号强度", "阀门状态", "温度", "压力", "异常得分"]),
        "final_3-6_告警E-R图": ("告警E-R图", "告警", ["告警ID", "设备ID", "读数ID", "告警类型", "告警描述", "异常分数", "阈值", "严重等级", "处理状态", "创建时间"]),
        "final_3-6-1_异常告警表E-R图": ("异常告警表E-R图", "异常告警表", ["告警ID", "设备ID", "读数ID", "告警类型", "告警描述", "异常分数", "检测阈值", "严重等级", "处理状态", "确认标签", "模型版本"]),
        "final_3-7_工单E-R图": ("工单E-R图", "工单", ["工单ID", "标题", "描述", "区域", "优先级", "状态", "当前阶段", "设备ID", "告警ID", "工程师ID", "创建时间"]),
        "final_3-8_模型元数据E-R图": ("模型元数据E-R图", "模型元数据", ["模型ID", "模型路径", "标准化器路径", "特征列", "窗口大小", "隐藏维度", "层数", "阈值", "准确率", "F1值", "是否激活"]),
        "final_3-8-1_模型元数据表E-R图": ("模型元数据表E-R图", "模型元数据表", ["模型ID", "模型路径", "标准化器路径", "元数据路径", "特征列", "窗口大小", "隐藏维度", "网络层数", "检测阈值", "阈值策略", "是否激活"]),
        "final_3-9_历史检测表E-R图": ("历史检测表E-R图", "历史检测表", ["检测ID", "设备ID", "表具编号", "检测时间", "异常得分", "检测阈值", "预测标签", "模型版本", "异常类型", "严重等级", "处理状态"]),
    }
    for key, (title, entity, attrs) in er_attrs.items():
        defs[key] = single_entity_er_page(title, entity, attrs)
    defs["final_3-13_系统总体流程图"] = system_overall_flow_page()
    defs["final_3-14_模块依赖关系图"] = hierarchy("模块依赖关系图", {"前端界面": ["登录认证", "监控看板", "工单页面"], "后端接口": ["设备接口", "告警接口", "训练接口"], "业务服务": ["设备服务", "工单服务", "模型服务"], "数据层": ["SQLite数据库", "模型文件", "训练样本"]})
    class_defs = {
        "设备监测类图": {"Device": common_entities["设备"], "MeterReading": common_entities["读数"], "PhysicalDataRecord": ["device_id", "meter_id", "timestamp", "features"], "DetectionService": ["score_recent_readings()", "reconstruction_trace()"]},
        "告警工单类图": {"AnomalyEvent": common_entities["告警"], "WorkOrder": common_entities["工单"], "WorkOrderRecord": ["stage", "action", "note", "operator"], "Engineer": ["employee_no", "name", "region", "status"]},
        "模型训练类图": {"ModelMetadata": common_entities["模型元数据"], "TrainingRawDataRecord": common_entities["训练数据"], "TrainingCleanDataRecord": common_entities["训练数据"], "ContinuousTrainingService": ["run_once()", "train_model()", "evaluate()"]},
        "系统类图": {"User": common_entities["用户"], "Device": common_entities["设备"], "MeterReading": common_entities["读数"], "AnomalyEvent": common_entities["告警"], "WorkOrder": common_entities["工单"], "Engineer": ["employee_no", "name", "region", "status"], "ModelMetadata": common_entities["模型元数据"]},
    }
    defs["final_3-15-1_设备监测类图"] = class_page("设备监测类图", class_defs["设备监测类图"], [("Device", "MeterReading", "1..*"), ("Device", "PhysicalDataRecord", "1..*"), ("DetectionService", "MeterReading", "uses")])
    defs["final_3-15-2_告警工单类图"] = class_page("告警工单类图", class_defs["告警工单类图"], [("AnomalyEvent", "WorkOrder", "creates"), ("WorkOrder", "WorkOrderRecord", "1..*"), ("Engineer", "WorkOrder", "handles")])
    defs["final_3-15-3_模型训练类图"] = class_page("模型训练类图", class_defs["模型训练类图"], [("TrainingRawDataRecord", "TrainingCleanDataRecord", "clean"), ("ContinuousTrainingService", "ModelMetadata", "writes"), ("ContinuousTrainingService", "TrainingCleanDataRecord", "uses")])
    defs["final_3-15_系统类图"] = class_page("系统类图", class_defs["系统类图"], [("Device", "MeterReading", "1..*"), ("MeterReading", "AnomalyEvent", "0..1"), ("AnomalyEvent", "WorkOrder", "0..1"), ("Engineer", "WorkOrder", "1..*"), ("User", "Engineer", "0..1"), ("ModelMetadata", "MeterReading", "scores")])
    defs["final_4-1_异常检测流程图"] = anomaly_detection_flow_page()
    defs["final_4-2_持续训练流程图"] = continuous_training_flow_page()
    defs["final_4-3_数据接入与预处理流程图"] = data_preprocess_flow_page()
    defs["final_4-4_LSTM Encoder模型结构图"] = lstm_encoder_structure_page()
    defs["final_4-5_告警与工单闭环流程图"] = alert_work_order_closed_loop_flow_page()
    return defs


def mxfile(pages: list[Page]) -> str:
    return '<mxfile host="app.diagrams.net" modified="2026-05-18T00:00:00.000Z" agent="Codex" version="24.0.0">' + "".join(p.xml() for p in pages) + "</mxfile>"


def write_file(path: Path, pages: list[Page]) -> None:
    path.write_text(mxfile(pages), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    defs = definitions()
    combined: list[Page] = []
    direct_keys = [
        "final_3-1_系统功能结构图",
        "final_3-2_框架处理顺序图",
        "final_3-2_真实模拟设备统一接入图",
        "final_3-17_系统数据流图",
        "final_3-18_数据流边界划分图",
        "final_3-18-1_数据传输层图",
        "final_3-19_一级结构图",
        "final_3-20_二级结构图",
        "final_3-3_设备E-R图",
        "final_3-4_用户E-R图",
        "final_3-5_读数E-R图",
        "final_3-6_告警E-R图",
        "final_3-6-1_异常告警表E-R图",
        "final_3-7_工单E-R图",
        "final_3-8_模型元数据E-R图",
        "final_3-8-1_模型元数据表E-R图",
        "final_3-9_历史检测表E-R图",
        "final_3-12_系统总体E-R图",
        "final_4-1_异常检测流程图",
        "final_4-2_持续训练流程图",
        "final_4-3_数据接入与预处理流程图",
        "final_4-4_LSTM Encoder模型结构图",
        "final_4-5_告警与工单闭环流程图",
    ]
    for key in direct_keys:
        if key in defs:
            write_file(OUT / f"{key}.drawio", [defs[key]])
            combined.append(defs[key])
    if "final_3-1_系统功能结构图" in defs:
        write_file(OUT / "final_3-1_系统功能结构图_角色功能版.drawio", [defs["final_3-1_系统功能结构图"]])
    for image in sorted(PICTURES.glob("*.png")):
        key = image.stem
        if key in direct_keys:
            continue
        editable = defs.get(key) or flow_page(key, [key, "请在 draw.io 中补充细节"])
        w, h = png_size(image)
        scale = min(1400 / w, 900 / h, 1.0)
        ref = Page("原图参考", max(1600, int(w * scale) + 120), max(1000, int(h * scale) + 120))
        ref.image(image, 60, 60, int(w * scale), int(h * scale))
        if key == "final_3-1_系统功能结构图":
            write_file(OUT / f"{key}.drawio", [editable])
            write_file(OUT / "final_3-1_系统功能结构图_角色功能版.drawio", [editable])
        else:
            write_file(OUT / f"{key}.drawio", [editable, ref])
        combined.append(editable)
    for extra_key in ["final_4-3_数据接入与预处理流程图", "final_4-4_LSTM Encoder模型结构图", "final_4-5_告警与工单闭环流程图"]:
        if extra_key in defs:
            write_file(OUT / f"{extra_key}.drawio", [defs[extra_key]])
            combined.append(defs[extra_key])
    write_file(OUT / "all_diagrams_editable.drawio", combined)
    print(f"generated {len(list(OUT.glob('*.drawio'))) - 1} individual files and one combined file in {OUT}")


if __name__ == "__main__":
    main()
