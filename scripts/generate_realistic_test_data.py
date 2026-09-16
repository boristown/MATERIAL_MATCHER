from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Any

SEED = 20260916

SOURCE_HEADERS = [
    "物料编码",
    "物料类型",
    "一层分类描述",
 "二层分类描述",
    "三层分类描述",
    "四层分类描述",
    "五层分类描述",
    "物料名称",
    "型号",
    "型号规格",
    "质量等级",
    "国产/进口",
    "总规范",
    "封装形式",
    "详细规范",
    "外形尺寸",
    "生产厂家",
    "特殊说明",
    "采购标准",
    "规格",
    "技术标准",
    "标准号",
    "型号(牌号)",
    "计量单位",
]

TARGET_HEADERS = [
    "集团码",
    "物料类型",
    "二层分类",
    "三层分类",
    "四层分类",
    "五层分类",
    "物料名称",
    "型号",
    "型号规格",
    "质量等级",
    "国产/进口",
    "封装形式",
    "生产厂家",
    "采用标准",
    "通用规范",
    "详细规范",
    "外形尺寸",
    "牌号",
    "规格",
    "计量单位",
    "特殊说明",
]

TRUTH_HEADERS = ["物料编码", "预期是否可匹配", "预期集团码", "场景", "说明"]

MANUFACTURER_ALIASES = {
    "Texas Instruments": ["TI", "德州仪器", "Texas Instruments Inc."],
    "Analog Devices": ["ADI", "亚德诺", "Analog Devices Inc."],
    "STMicroelectronics": ["ST", "意法半导体", "STMicro"],
    "Nexperia": ["安世半导体", "Nexperia B.V."],
    "Vishay": ["威世", "Vishay Intertechnology"],
    "Murata": ["村田", "Murata Manufacturing"],
    "TDK": ["东电化", "TDK株式会社"],
    "KYOCERA AVX": ["AVX", "京瓷AVX"],
    "TE Connectivity": ["TE", "泰科电子"],
    "中国振华集团永光电子有限公司": ["振华永光", "中国振华永光"],
    "成都宏明电子股份有限公司": ["成都宏明", "宏明电子"],
    "北京七星华创精密电子科技有限责任公司": ["七星华创", "北京七星华创"],
    "四川东材科技集团股份有限公司": ["四川东材", "东材科技"],
    "上海绝缘材料厂有限公司": ["上海绝缘", "上绝"],
    "中复神鹰碳纤维股份有限公司": ["中复神鹰", "神鹰碳纤维"],
    "江苏恒神股份有限公司": ["江苏恒神", "恒神股份"],
}


def _blank(headers: list[str]) -> dict[str, str]:
    return {key: "" for key in headers}


def _material_code(index: int) -> str:
    return f"{100000000000000000 + index:018d}"


def _group_code(index: int) -> str:
    return f"JT13{2026000000 + index:010d}"


def _alias_manufacturer(name: str, rng: random.Random) -> str:
    aliases = MANUFACTURER_ALIASES.get(name)
    return rng.choice(aliases) if aliases else name


def _electronics(index: int, rng: random.Random) -> dict[str, str]:
    row = _blank(TARGET_HEADERS)
    row["物料类型"] = "Z001"
    row["国产/进口"] = rng.choice(["国产", "进口"])
    family = index % 12

    if family == 0:
        package = rng.choice(["0402", "0603", "0805", "1206"])
        value = rng.choice(["10Ω", "22Ω", "47Ω", "100Ω", "220Ω", "470Ω", "1kΩ", "2.2kΩ", "4.7kΩ", "10kΩ", "22kΩ", "47kΩ", "100kΩ", "1MΩ"])
        tolerance = rng.choice(["±1%", "±5%"])
        power = {"0402": "0.063W", "0603": "0.1W", "0805": "0.125W", "1206": "0.25W"}[package]
        encoded_value = value.replace("Ω", "").replace("k", "K").replace(".", "R")
        row.update(
            {
                "二层分类": "电阻器",
                "三层分类": "固定电阻器",
                "四层分类": "片式电阻器",
                "五层分类": "厚膜片式电阻器",
                "物料名称": "厚膜片式固定电阻器",
                "型号": f"RC{package}FR-07{encoded_value}L",
                "型号规格": f"{value} {tolerance} {power}",
                "质量等级": rng.choice(["工业级", "军品筛选级"]),
                "封装形式": package,
                "生产厂家": rng.choice(["Vishay", "中国振华集团永光电子有限公司", "成都宏明电子股份有限公司"]),
                "通用规范": "GJB 1929A-2011",
                "详细规范": "SJ/T 10774-2000",
                "外形尺寸": package,
                "规格": f"{value}/{tolerance}/{power}",
                "计量单位": "只",
            }
        )
    elif family == 1:
        package = rng.choice(["0402", "0603", "0805", "1206"])
        capacitance = rng.choice(["100pF", "1nF", "10nF", "47nF", "100nF", "470nF", "1μF", "2.2μF", "4.7μF", "10μF"])
        voltage = rng.choice(["16V", "25V", "50V"])
        dielectric = rng.choice(["C0G", "X7R", "X5R"])
        row.update(
            {
                "二层分类": "电容器",
                "三层分类": "固定电容器",
                "四层分类": "陶瓷电容器",
                "五层分类": "多层片式陶瓷电容器",
                "物料名称": "多层片式陶瓷电容器",
                "型号": f"GRM{rng.choice(['155', '188', '219', '31'])}{dielectric[0]}1H{rng.randint(100, 999)}K",
                "型号规格": f"{capacitance} {voltage} {dielectric}",
                "质量等级": rng.choice(["工业级", "军品筛选级"]),
                "封装形式": package,
                "生产厂家": rng.choice(["Murata", "TDK", "KYOCERA AVX"]),
                "通用规范": "GJB 63B-2001",
                "详细规范": "GB/T 9324-1997",
                "外形尺寸": package,
                "规格": f"{capacitance}/{voltage}/{dielectric}",
                "计量单位": "只",
            }
        )
    elif family == 2:
        model, name, package, manufacturer = rng.choice(
            [
                ("1N4148WS", "高速开关二极管", "SOD-323", "Nexperia"),
                ("SS34", "肖特基整流二极管", "SMA", "Vishay"),
                ("1N4007", "硅整流二极管", "DO-41", "中国振华集团永光电子有限公司"),
                ("BZX55C5V1", "稳压二极管5.1V", "DO-35", "Nexperia"),
                ("BAT54C", "肖特基二极管阵列", "SOT-23", "Nexperia"),
            ]
        )
        row.update(
            {
                "二层分类": "半导体分立器件",
                "三层分类": "二极管",
                "四层分类": "硅二极管",
                "五层分类": name,
                "物料名称": name,
                "型号": model,
                "型号规格": package,
                "质量等级": rng.choice(["工业级", "军品筛选级"]),
                "封装形式": package,
                "生产厂家": manufacturer,
                "通用规范": "GJB 33A-1997",
                "详细规范": "MIL-PRF-19500",
                "外形尺寸": package,
                "规格": model,
                "计量单位": "只",
            }
        )
    elif family == 3:
        model, name, package, manufacturer = rng.choice(
            [
                ("2N2222A", "NPN小功率晶体管", "TO-92", "中国振华集团永光电子有限公司"),
                ("MMBT3904", "NPN小信号晶体管", "SOT-23", "Nexperia"),
                ("IRF540N", "N沟道功率MOSFET", "TO-220AB", "Vishay"),
                ("AO3400A", "N沟道MOSFET", "SOT-23", "中国振华集团永光电子有限公司"),
                ("2SC3356", "高频NPN晶体管", "SOT-23", "Nexperia"),
            ]
        )
        row.update(
            {
                "二层分类": "半导体分立器件",
                "三层分类": "晶体管",
                "四层分类": "双极型晶体管/场效应管",
                "五层分类": name,
                "物料名称": name,
                "型号": model,
                "型号规格": package,
                "质量等级": rng.choice(["工业级", "军品筛选级"]),
                "封装形式": package,
                "生产厂家": manufacturer,
                "通用规范": "GJB 128A-1997",
                "详细规范": "MIL-PRF-19500",
                "外形尺寸": package,
                "规格": model,
                "计量单位": "只",
            }
        )
    elif family == 4:
        model, name, package, manufacturer = rng.choice(
            [
                ("LM358DR", "双运算放大器", "SOIC-8", "Texas Instruments"),
                ("OPA2277UA", "双精密运算放大器", "SOIC-8", "Texas Instruments"),
                ("AD620ARZ", "仪表放大器", "SOIC-8", "Analog Devices"),
                ("AD8221ARZ", "低功耗仪表放大器", "SOIC-8", "Analog Devices"),
                ("LM324AD", "四运算放大器", "SOIC-14", "Texas Instruments"),
            ]
        )
        row.update(
            {
                "二层分类": "集成电路",
                "三层分类": "模拟集成电路",
                "四层分类": "放大器",
                "五层分类": "运算/仪表放大器",
                "物料名称": name,
                "型号": model,
                "型号规格": package,
                "质量等级": rng.choice(["工业级", "工业扩展级"]),
                "封装形式": package,
                "生产厂家": manufacturer,
                "通用规范": "GJB 597A-1996",
                "详细规范": "Q/IC-AMP",
                "外形尺寸": package,
                "规格": model,
                "计量单位": "只",
            }
        )
    elif family == 5:
        model, name, package, manufacturer = rng.choice(
            [
                ("AD7606BSTZ", "16位8通道ADC", "LQFP-64", "Analog Devices"),
                ("ADS1115IDGSR", "16位4通道ADC", "VSSOP-10", "Texas Instruments"),
                ("DAC8568SPW", "16位8通道DAC", "TSSOP-16", "Texas Instruments"),
                ("AD7689BCPZ", "16位8通道SAR ADC", "LFCSP-20", "Analog Devices"),
            ]
        )
        row.update(
            {
                "二层分类": "集成电路",
                "三层分类": "模拟集成电路",
                "四层分类": "数据转换器",
                "五层分类": "ADC/DAC",
                "物料名称": name,
                "型号": model,
                "型号规格": package,
                "质量等级": "工业级",
                "封装形式": package,
                "生产厂家": manufacturer,
                "通用规范": "GJB 597A-1996",
                "详细规范": "Q/IC-DATA",
                "外形尺寸": package,
                "规格": model,
                "计量单位": "只",
            }
        )
    elif family == 6:
        model, name, package, manufacturer = rng.choice(
            [
                ("STM32F103C8T6", "32位微控制器", "LQFP-48", "STMicroelectronics"),
                ("STM32F407VGT6", "32位微控制器", "LQFP-100", "STMicroelectronics"),
                ("GD32F103C8T6", "32位微控制器", "LQFP-48", "中国振华集团永光电子有限公司"),
                ("MSP430F5438AIPZR", "16位低功耗微控制器", "LQFP-100", "Texas Instruments"),
            ]
        )
        row.update(
            {
                "二层分类": "集成电路",
                "三层分类": "数字集成电路",
                "四层分类": "微控制器",
                "五层分类": "MCU",
                "物料名称": name,
                "型号": model,
                "型号规格": package,
                "质量等级": "工业级",
                "封装形式": package,
                "生产厂家": manufacturer,
                "通用规范": "GJB 597A-1996",
                "详细规范": "Q/IC-MCU",
                "外形尺寸": package,
                "规格": model,
                "计量单位": "只",
            }
        )
    elif family == 7:
        model, name, package, manufacturer = rng.choice(
            [
                ("XC7A35T-1CSG324C", "Artix-7 FPGA", "BGA-324", "AMD Xilinx"),
                ("XC7A100T-2FGG484I", "Artix-7 FPGA", "BGA-484", "AMD Xilinx"),
                ("GW1N-LV9QN88C6/I5", "FPGA", "QFN-88", "广东高云半导体"),
                ("EP4CE22F17C8N", "Cyclone IV FPGA", "BGA-256", "Intel Altera"),
            ]
        )
        row.update(
            {
                "二层分类": "集成电路",
                "三层分类": "数字集成电路",
                "四层分类": "可编程逻辑器件",
                "五层分类": "FPGA",
                "物料名称": name,
                "型号": model,
                "型号规格": package,
                "质量等级": "工业级",
                "封装形式": package,
                "生产厂家": manufacturer,
                "通用规范": "GJB 597A-1996",
                "详细规范": "Q/IC-FPGA",
                "外形尺寸": package,
                "规格": model,
                "计量单位": "只",
            }
        )
    elif family == 8:
        model, name, package, manufacturer = rng.choice(
            [
                ("TPS7A4901DGNR", "正压低噪声线性稳压器", "MSOP-8", "Texas Instruments"),
                ("LM1117-3.3", "低压差线性稳压器3.3V", "SOT-223", "STMicroelectronics"),
                ("TPS5430DDAR", "3A降压型开关稳压器", "SOIC-8-PowerPAD", "Texas Instruments"),
                ("LT1763CS8-5", "低噪声LDO 5V", "SOIC-8", "Analog Devices"),
            ]
        )
        row.update(
            {
                "二层分类": "集成电路",
                "三层分类": "模拟集成电路",
                "四层分类": "电源管理",
                "五层分类": "稳压器",
                "物料名称": name,
                "型号": model,
                "型号规格": package,
                "质量等级": "工业级",
                "封装形式": package,
                "生产厂家": manufacturer,
                "通用规范": "GJB 597A-1996",
                "详细规范": "Q/IC-PWR",
                "外形尺寸": package,
                "规格": model,
                "计量单位": "只",
            }
        )
    elif family == 9:
        pins = rng.choice([9, 15, 21, 25, 31, 37])
        row.update(
            {
                "二层分类": "连接器",
                "三层分类": "矩形连接器",
                "四层分类": "微矩形连接器",
                "五层分类": "J30J系列",
                "物料名称": "微矩形电连接器",
                "型号": f"J30J-{pins}ZKP",
                "型号规格": f"{pins}芯 插座",
                "质量等级": "军品级",
                "封装形式": "插座",
                "生产厂家": "TE Connectivity",
                "通用规范": "GJB 2446A-2011",
                "详细规范": "Q/J30J",
                "外形尺寸": f"{pins}芯",
                "规格": f"{pins}芯",
                "计量单位": "只",
            }
        )
    elif family == 10:
        model, name, package, manufacturer = rng.choice(
            [
                ("6N137", "高速光耦", "DIP-8", "Vishay"),
                ("HCPL-2631", "双通道高速光耦", "DIP-8", "Broadcom"),
                ("PC817C", "晶体管输出光耦", "DIP-4", "SHARP"),
                ("TLP521-1", "晶体管输出光耦", "DIP-4", "Toshiba"),
            ]
        )
        row.update(
            {
                "二层分类": "光电子器件",
                "三层分类": "光耦合器",
                "四层分类": "数字/晶体管输出光耦",
                "五层分类": "光电耦合器",
                "物料名称": name,
                "型号": model,
                "型号规格": package,
                "质量等级": "工业级",
                "封装形式": package,
                "生产厂家": manufacturer,
                "通用规范": "GJB 548B-2005",
                "详细规范": "Q/OPTO",
                "外形尺寸": package,
                "规格": model,
                "计量单位": "只",
            }
        )
    else:
        frequency = rng.choice(["8MHz", "10MHz", "12MHz", "16MHz", "20MHz", "25MHz", "40MHz", "50MHz"])
        package = rng.choice(["3225", "5032", "7050"])
        row.update(
            {
                "二层分类": "频率元件",
                "三层分类": "晶体与振荡器",
                "四层分类": "石英晶体振荡器",
                "五层分类": "有源晶振",
                "物料名称": "石英晶体振荡器",
                "型号": f"OSC-{frequency}-{package}-{rng.choice(['20PPM', '30PPM', '50PPM'])}",
                "型号规格": f"{frequency} {package}",
                "质量等级": "工业级",
                "封装形式": package,
                "生产厂家": rng.choice(["TDK", "Murata", "北京七星华创精密电子科技有限责任公司"]),
                "通用规范": "GJB 1648A-2011",
                "详细规范": "Q/OSC",
                "外形尺寸": package,
                "规格": f"{frequency}/{package}",
                "计量单位": "只",
            }
        )
    return row


def _composite(index: int, rng: random.Random) -> dict[str, str]:
    row = _blank(TARGET_HEADERS)
    row["物料类型"] = "Z006"
    row["国产/进口"] = "国产"
    family = index % 8

    if family == 0:
        thickness = rng.choice(["0.5", "0.8", "1.0", "1.5", "2.0", "2.5", "3.0", "4.0", "5.0", "6.0", "8.0", "10.0"])
        row.update(
            {
                "二层分类": "聚合物基复合材料",
                "三层分类": "层压板",
                "四层分类": "环氧玻璃布层压板",
                "五层分类": "3240环氧玻璃布板",
                "物料名称": "环氧玻璃布层压板",
                "牌号": "3240",
                "型号": "3240",
                "型号规格": f"{thickness}×1020×1220mm",
                "规格": f"厚{thickness}mm 1020×1220mm",
                "生产厂家": rng.choice(["四川东材科技集团股份有限公司", "上海绝缘材料厂有限公司"]),
                "采用标准": "GB/T 1303.1-2009",
                "通用规范": "GB/T 1303.1-2009",
                "详细规范": "GB/T 1303.4-2009",
                "外形尺寸": f"{thickness}×1020×1220mm",
                "计量单位": "张",
            }
        )
    elif family == 1:
        thickness = rng.choice(["0.5", "1.0", "1.5", "2.0", "3.0", "4.0", "5.0", "8.0", "10.0", "12.0", "15.0", "20.0"])
        row.update(
            {
                "二层分类": "聚合物基复合材料",
                "三层分类": "层压板",
                "四层分类": "阻燃环氧玻璃布层压板",
                "五层分类": "FR-4覆铜基材",
                "物料名称": "阻燃环氧玻璃布层压板",
                "牌号": "FR-4",
                "型号": "FR-4",
                "型号规格": f"{thickness}×1020×1220mm",
                "规格": f"厚{thickness}mm 1020×1220mm",
                "生产厂家": "四川东材科技集团股份有限公司",
                "采用标准": "IPC-4101C",
                "通用规范": "IPC-4101C",
                "详细规范": "NEMA LI-1",
                "外形尺寸": f"{thickness}×1020×1220mm",
                "计量单位": "张",
            }
        )
    elif family == 2:
        diameter = rng.choice(["5", "8", "10", "12", "15", "20", "25", "30", "40", "50", "60", "80"])
        row.update(
            {
                "二层分类": "聚合物基复合材料",
                "三层分类": "棒材",
                "四层分类": "环氧玻璃布棒",
                "五层分类": "环氧玻璃布层压棒",
                "物料名称": "环氧玻璃布层压棒",
                "牌号": "3841",
                "型号": "3841",
                "型号规格": f"Φ{diameter}×1000mm",
                "规格": f"直径{diameter}mm 长1000mm",
                "生产厂家": "上海绝缘材料厂有限公司",
                "采用标准": "JB/T 56073.26-1999",
                "通用规范": "JB/T 56073.26-1999",
                "外形尺寸": f"Φ{diameter}×1000mm",
                "计量单位": "根",
            }
        )
    elif family == 3:
        diameter = rng.choice(["6", "8", "10", "12", "16", "20", "25", "30", "35", "40", "50", "60"])
        row.update(
            {
                "二层分类": "聚合物基复合材料",
                "三层分类": "棒材",
                "四层分类": "酚醛棉布棒",
                "五层分类": "酚醛层压布棒",
                "物料名称": "酚醛层压布棒",
                "牌号": "3723",
                "型号": "3723",
                "型号规格": f"Φ{diameter}×1000mm",
                "规格": f"直径{diameter}mm 长1000mm",
                "生产厂家": "上海绝缘材料厂有限公司",
                "采用标准": "GB/T 5133-1985",
                "通用规范": "GB/T 5133-1985",
                "外形尺寸": f"Φ{diameter}×1000mm",
                "计量单位": "根",
            }
        )
    elif family == 4:
        grade = rng.choice(["T300-3K", "T700-12K", "T800-12K"])
        weight = rng.choice(["100g/m²", "150g/m²", "200g/m²", "300g/m²"])
        width = rng.choice(["300mm", "500mm", "1000mm"])
        row.update(
            {
                "二层分类": "碳纤维复合材料",
                "三层分类": "预浸料",
                "四层分类": "环氧树脂基预浸料",
                "五层分类": "单向碳纤维预浸料",
                "物料名称": "单向碳纤维环氧预浸料",
                "牌号": grade,
                "型号": grade,
                "型号规格": f"{weight} 宽{width}",
                "规格": f"{weight}/{width}",
                "生产厂家": rng.choice(["中复神鹰碳纤维股份有限公司", "江苏恒神股份有限公司"]),
                "采用标准": "Q/CF-PREPREG-2024",
                "通用规范": "Q/CF-PREPREG-2024",
                "外形尺寸": width,
                "计量单位": "平方米",
            }
        )
    elif family == 5:
        weave = rng.choice(["平纹", "斜纹"])
        tow = rng.choice(["1K", "3K", "12K"])
        weight = rng.choice(["160g/m²", "200g/m²", "240g/m²", "300g/m²"])
        row.update(
            {
                "二层分类": "碳纤维复合材料",
                "三层分类": "织物",
                "四层分类": "碳纤维布",
                "五层分类": f"{weave}碳纤维布",
                "物料名称": f"{weave}碳纤维布",
                "牌号": tow,
                "型号": f"{tow}-{weave}",
                "型号规格": f"{weight} 宽1000mm",
                "规格": f"{weight}/1000mm",
                "生产厂家": rng.choice(["中复神鹰碳纤维股份有限公司", "江苏恒神股份有限公司"]),
                "采用标准": "Q/CF-FABRIC-2024",
                "通用规范": "Q/CF-FABRIC-2024",
                "外形尺寸": "宽1000mm",
                "计量单位": "平方米",
            }
        )
    elif family == 6:
        cell = rng.choice(["3.2mm", "4.8mm", "6.4mm"])
        thickness = rng.choice(["5mm", "10mm", "15mm", "20mm", "25mm", "30mm"])
        density = rng.choice(["48kg/m³", "64kg/m³", "80kg/m³"])
        row.update(
            {
                "二层分类": "夹层复合材料",
                "三层分类": "蜂窝芯材",
                "四层分类": "芳纶纸蜂窝",
                "五层分类": "Nomex蜂窝",
                "物料名称": "芳纶纸蜂窝芯",
                "牌号": "NOMEX",
                "型号": "NOMEX-HC",
                "型号规格": f"孔格{cell} 厚{thickness} 密度{density}",
                "规格": f"{cell}/{thickness}/{density}",
                "生产厂家": "江苏恒神股份有限公司",
                "采用标准": "HB 5443-1990",
                "通用规范": "HB 5443-1990",
                "外形尺寸": f"厚{thickness}",
                "计量单位": "平方米",
            }
        )
    else:
        grade = rng.choice(["E-51", "E-44", "TDE-85"])
        package = rng.choice(["5kg/桶", "20kg/桶", "25kg/桶"])
        row.update(
            {
                "二层分类": "聚合物基复合材料",
                "三层分类": "树脂体系",
                "四层分类": "环氧树脂",
                "五层分类": "结构胶黏剂基体树脂",
                "物料名称": "环氧树脂",
                "牌号": grade,
                "型号": grade,
                "型号规格": package,
                "规格": package,
                "生产厂家": "四川东材科技集团股份有限公司",
                "采用标准": "GB/T 13657-2011",
                "通用规范": "GB/T 13657-2011",
                "外形尺寸": package,
                "计量单位": "桶",
            }
        )
    return row


def _source_from_target(
    target: dict[str, str],
    source_index: int,
    *,
    matched: bool,
    scenario: str,
    rng: random.Random,
) -> dict[str, str]:
    row = _blank(SOURCE_HEADERS)
    row.update(
        {
            "物料编码": _material_code(source_index),
            "物料类型": target["物料类型"],
            "一层分类描述": "元器件" if target["物料类型"] == "Z001" else "复合材料",
            "二层分类描述": target["二层分类"],
            "三层分类描述": target["三层分类"],
            "四层分类描述": target["四层分类"],
            "五层分类描述": target["五层分类"],
            "物料名称": target["物料名称"],
            "型号": target["型号"],
            "型号规格": target["型号规格"],
            "质量等级": target["质量等级"],
            "国产/进口": "10" if target["国产/进口"] == "国产" else "11",
            "总规范": target["通用规范"],
            "封装形式": target["封装形式"],
            "详细规范": target["详细规范"],
            "外形尺寸": target["外形尺寸"],
            "生产厂家": target["生产厂家"],
            "特殊说明": target["特殊说明"],
            "采购标准": target["采用标准"] or target["通用规范"],
            "规格": target["规格"],
            "技术标准": target["通用规范"],
            "标准号": target["采用标准"] or target["通用规范"],
            "型号(牌号)": target["牌号"] or target["型号"],
            "计量单位": target["计量单位"],
        }
    )

    if not matched:
        if target["物料类型"] == "Z001":
            if "电阻" in row["物料名称"]:
                row["型号"] = f"RC0603FR-07{rng.choice(['13K7', '26K1', '73K2', '187K'])}L"
                row["型号规格"] = f"{rng.choice(['13.7kΩ', '26.1kΩ', '73.2kΩ', '187kΩ'])} ±0.5% 0.1W"
            elif "电容" in row["物料名称"]:
                row["型号"] = f"CC-RARE-{rng.choice(['2N7', '3U3', '6N8', '15U'])}-{rng.choice(['25V', '63V'])}"
                row["型号规格"] = rng.choice(["2.7nF 63V C0G", "3.3μF 25V X7R", "6.8nF 50V C0G"])
            elif "连接器" in row["物料名称"]:
                pins = rng.choice([11, 17, 19, 27, 33, 41])
                row["型号"] = f"J30J-{pins}ZKP"
                row["型号规格"] = f"{pins}芯 插座"
                row["外形尺寸"] = f"{pins}芯"
            else:
                row["型号"] = f"{row['型号']}-Q{rng.randint(7, 9)}"
                row["型号规格"] = f"{row['型号规格']} 特殊温度级"
        else:
            if row["型号(牌号)"] in {"3240", "FR-4"}:
                thickness = rng.choice(["0.65", "1.25", "2.75", "7.5", "11.0"])
                row["型号规格"] = f"{thickness}×1030×1230mm"
                row["规格"] = f"厚{thickness}mm 1030×1230mm"
                row["外形尺寸"] = row["型号规格"]
            elif row["型号(牌号)"] in {"3841", "3723"}:
                diameter = rng.choice(["7", "13", "18", "22", "45", "70"])
                row["型号规格"] = f"Φ{diameter}×1200mm"
                row["规格"] = f"直径{diameter}mm 长1200mm"
                row["外形尺寸"] = row["型号规格"]
            else:
                row["型号(牌号)"] = f"{row['型号(牌号)']}-R{rng.randint(2, 9)}"
                row["型号"] = row["型号(牌号)"]
                row["型号规格"] = f"{row['型号规格']} 定制批次"
        row["特殊说明"] = "目录中无正式集团码，预期需人工确认或未匹配"
        return row

    if scenario == "manufacturer_alias":
        row["生产厂家"] = _alias_manufacturer(row["生产厂家"], rng)
    elif scenario == "standard_format":
        for field in ("总规范", "详细规范", "采购标准", "技术标准", "标准号"):
            row[field] = row[field].replace(" ", "")
    elif scenario == "punctuation_space":
        row["型号"] = f" {row['型号']} "
        row["型号规格"] = row["型号规格"].replace("×", " x ").replace("Φ", "φ")
        row["外形尺寸"] = row["外形尺寸"].replace("×", "X").replace("Φ", "φ")
    elif scenario == "missing_secondary":
        for field in rng.sample(["质量等级", "详细规范", "总规范", "特殊说明", "外形尺寸"], k=2):
            row[field] = "88"
    elif scenario == "unit_variant":
        row["计量单位"] = {"只": "PCS", "张": "片", "根": "支", "平方米": "m2", "桶": "桶"}.get(row["计量单位"], row["计量单位"])
        row["型号规格"] = row["型号规格"].replace("mm", " mm").replace("g/m²", "g / m2")
    elif scenario == "combined":
        row["生产厂家"] = _alias_manufacturer(row["生产厂家"], rng)
        row["型号"] = row["型号"].replace("-", " - ")
        row["型号规格"] = row["型号规格"].replace("×", " x ").replace("Φ", "φ")
        if rng.random() < 0.6:
            row["详细规范"] = "88"
    return row


def generate_rows(seed: int = SEED) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    rng = random.Random(seed)

    true_targets: list[dict[str, str]] = []
    for index in range(630):
        row = _electronics(index, rng)
        row["集团码"] = _group_code(index + 1)
        true_targets.append(row)
    for index in range(270):
        row = _composite(index, rng)
        row["集团码"] = _group_code(631 + index)
        true_targets.append(row)

    # Real catalogs can contain the same commercial model under different screening/specification records.
    # Make only genuinely identical generated rows distinguishable by an enterprise detail-spec suffix.
    seen: set[tuple[str, ...]] = set()
    for index, row in enumerate(true_targets, start=1):
        key = (
            row["物料类型"],
            row["型号"],
            row["型号规格"],
            row["生产厂家"],
            row["牌号"],
            row["规格"],
            row["质量等级"],
        )
        if key in seen:
            row["详细规范"] = f"{row['详细规范'] or '企业规范'}-{index:03d}"
        seen.add(key)

    scenarios = (
        ["exact"] * 270
        + ["manufacturer_alias"] * 135
        + ["standard_format"] * 135
        + ["punctuation_space"] * 135
        + ["missing_secondary"] * 90
        + ["unit_variant"] * 45
        + ["combined"] * 90
    )
    rng.shuffle(scenarios)

    sources: list[dict[str, str]] = []
    truth: list[dict[str, str]] = []
    for source_index, (target, scenario) in enumerate(zip(true_targets, scenarios), start=1):
        source = _source_from_target(target, source_index, matched=True, scenario=scenario, rng=rng)
        sources.append(source)
        truth.append(
            {
                "物料编码": source["物料编码"],
                "预期是否可匹配": "Y",
                "预期集团码": target["集团码"],
                "场景": scenario,
                "说明": "存在唯一业务对应项；允许格式、别名、空值等轻微差异",
            }
        )

    for offset in range(100):
        base = _electronics(1000 + offset, rng) if offset < 70 else _composite(1000 + offset, rng)
        source = _source_from_target(base, 901 + offset, matched=False, scenario="unmatched", rng=rng)
        sources.append(source)
        truth.append(
            {
                "物料编码": source["物料编码"],
                "预期是否可匹配": "N",
                "预期集团码": "",
                "场景": "unmatched",
                "说明": "目标目录无真实对应集团码；存在同类近邻，预期进入人工确认或未匹配",
            }
        )

    paired = list(zip(sources, truth))
    rng.shuffle(paired)
    sources = [item[0] for item in paired]
    truth = [item[1] for item in paired]

    distractors: list[dict[str, str]] = []
    for index in range(300):
        row = dict(rng.choice(true_targets))
        row["集团码"] = f"JT13D{index + 1:06d}"
        if row["物料类型"] == "Z001":
            package_map = {
                "0402": "0603",
                "0603": "0805",
                "0805": "1206",
                "1206": "0805",
                "SOT-23": "SOT-223",
                "SOIC-8": "TSSOP-8",
                "DIP-8": "SO-8",
            }
            new_package = package_map.get(row["封装形式"])
            if new_package:
                row["封装形式"] = new_package
                row["型号规格"] = f"{row['型号规格']} / {new_package}"
                row["外形尺寸"] = new_package
            else:
                row["型号"] = f"{row['型号']}-ALT"
        else:
            if row["牌号"] in {"3240", "FR-4"}:
                row["型号规格"] = row["型号规格"].replace("1020", "1000")
                row["规格"] = f"{row['规格']}（非同规格）"
                row["外形尺寸"] = row["型号规格"]
            elif "Φ" in row["型号规格"]:
                row["型号规格"] = row["型号规格"].replace("1000mm", "800mm")
                row["规格"] = row["规格"].replace("1000mm", "800mm")
                row["外形尺寸"] = row["型号规格"]
            else:
                row["牌号"] = f"{row['牌号']}-ALT"
                row["型号"] = row["牌号"]
        row["特殊说明"] = "近邻干扰项：同类但关键规格不同"
        distractors.append(row)

    targets = true_targets + distractors
    rng.shuffle(targets)

    manifest: dict[str, Any] = {
        "seed": seed,
        "source_rows": len(sources),
        "target_rows": len(targets),
        "expected_matched": sum(1 for row in truth if row["预期是否可匹配"] == "Y"),
        "expected_unmatched": sum(1 for row in truth if row["预期是否可匹配"] == "N"),
        "match_ratio": 0.9,
        "source_type_distribution": {
            "Z001": sum(1 for row in sources if row["物料类型"] == "Z001"),
            "Z006": sum(1 for row in sources if row["物料类型"] == "Z006"),
        },
        "target_true_rows": len(true_targets),
        "target_distractor_rows": len(distractors),
        "scenario_distribution": {
            scenario: sum(1 for row in truth if row["场景"] == scenario)
            for scenario in sorted({row["场景"] for row in truth})
        },
    }
    return sources, targets, truth, manifest


def _write_xlsx(path: Path, sheet_name: str, headers: list[str], rows: list[dict[str, str]]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.table import Table, TableStyleInfo

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(header, "") for header in headers])

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.row_dimensions[1].height = 30

    # IDs are deliberately stored as text so SAP-like 18 digit codes never become scientific notation.
    for cell in sheet["A"]:
        cell.number_format = "@"

    widths = [22, 12, 18, 20, 22, 24, 24, 26, 26, 28, 16, 14, 26, 24, 24, 22, 28, 26, 28, 16, 28, 24, 22, 14]
    for column_index, _ in enumerate(headers, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=column_index).column_letter].width = widths[column_index - 1] if column_index <= len(widths) else 18

    table = Table(displayName="FixtureData", ref=sheet.dimensions)
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True, showFirstColumn=False, showLastColumn=False)
    sheet.add_table(table)
    workbook.save(path)


def generate_dataset(output_dir: Path, *, seed: int = SEED) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    sources, targets, truth, manifest = generate_rows(seed)

    source_path = output_dir / "source_materials_1000.xlsx"
    target_path = output_dir / "target_group_codes_1200.xlsx"
    truth_path = output_dir / "ground_truth.csv"
    manifest_path = output_dir / "manifest.json"

    _write_xlsx(source_path, "待匹配物料", SOURCE_HEADERS, sources)
    _write_xlsx(target_path, "集团码标准数据", TARGET_HEADERS, targets)

    with truth_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=TRUTH_HEADERS)
        writer.writeheader()
        writer.writerows(truth)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "source": source_path,
        "target": target_path,
        "truth": truth_path,
        "manifest": manifest_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="生成接近 13 所业务字段的 1000 行物料匹配测试数据")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tests/fixtures/realistic_materials/generated"),
        help="输出目录",
    )
    parser.add_argument("--seed", type=int, default=SEED, help="固定随机种子，默认保持测试数据可复现")
    args = parser.parse_args()

    paths = generate_dataset(args.output_dir, seed=args.seed)
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
