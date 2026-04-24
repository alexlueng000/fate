# app/liuyao/paipan.py
"""
六爻排盘核心算法
实现数字起卦、铜钱起卦、时间起卦三种方法
"""
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import random
import uuid


# 八卦基础数据
BAGUA = {
    1: {"name": "乾", "trigram": "☰", "nature": "天", "wuxing": "金"},
    2: {"name": "兑", "trigram": "☱", "nature": "泽", "wuxing": "金"},
    3: {"name": "离", "trigram": "☲", "nature": "火", "wuxing": "火"},
    4: {"name": "震", "trigram": "☳", "nature": "雷", "wuxing": "木"},
    5: {"name": "巽", "trigram": "☴", "nature": "风", "wuxing": "木"},
    6: {"name": "坎", "trigram": "☵", "nature": "水", "wuxing": "水"},
    7: {"name": "艮", "trigram": "☶", "nature": "山", "wuxing": "土"},
    8: {"name": "坤", "trigram": "☷", "nature": "地", "wuxing": "土"},
}

# 64卦名称映射 (上卦索引, 下卦索引) -> 卦名
LIUSHISI_GUA = {
    (1, 1): "乾为天", (1, 2): "天泽履", (1, 3): "天火同人", (1, 4): "天雷无妄",
    (1, 5): "天风姤", (1, 6): "天水讼", (1, 7): "天山遁", (1, 8): "天地否",
    (2, 1): "泽天夬", (2, 2): "兑为泽", (2, 3): "泽火革", (2, 4): "泽雷随",
    (2, 5): "泽风大过", (2, 6): "泽水困", (2, 7): "泽山咸", (2, 8): "泽地萃",
    (3, 1): "火天大有", (3, 2): "火泽睽", (3, 3): "离为火", (3, 4): "火雷噬嗑",
    (3, 5): "火风鼎", (3, 6): "火水未济", (3, 7): "火山旅", (3, 8): "火地晋",
    (4, 1): "雷天大壮", (4, 2): "雷泽归妹", (4, 3): "雷火丰", (4, 4): "震为雷",
    (4, 5): "雷风恒", (4, 6): "雷水解", (4, 7): "雷山小过", (4, 8): "雷地豫",
    (5, 1): "风天小畜", (5, 2): "风泽中孚", (5, 3): "风火家人", (5, 4): "风雷益",
    (5, 5): "巽为风", (5, 6): "风水涣", (5, 7): "风山渐", (5, 8): "风地观",
    (6, 1): "水天需", (6, 2): "水泽节", (6, 3): "水火既济", (6, 4): "水雷屯",
    (6, 5): "水风井", (6, 6): "坎为水", (6, 7): "水山蹇", (6, 8): "水地比",
    (7, 1): "山天大畜", (7, 2): "山泽损", (7, 3): "山火贲", (7, 4): "山雷颐",
    (7, 5): "山风蛊", (7, 6): "山水蒙", (7, 7): "艮为山", (7, 8): "山地剥",
    (8, 1): "地天泰", (8, 2): "地泽临", (8, 3): "地火明夷", (8, 4): "地雷复",
    (8, 5): "地风升", (8, 6): "地水师", (8, 7): "地山谦", (8, 8): "坤为地",
}

# 六兽
LIUSHOU = ["青龙", "朱雀", "勾陈", "腾蛇", "白虎", "玄武"]

# 天干
TIANGAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]

# 地支
DIZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

# 纳甲表：八卦对应的地支
NAJIA = {
    1: ["子", "寅", "辰", "午", "申", "戌"],  # 乾
    2: ["巳", "卯", "丑", "亥", "酉", "未"],  # 兑
    3: ["卯", "丑", "亥", "酉", "未", "巳"],  # 离
    4: ["子", "寅", "辰", "午", "申", "戌"],  # 震
    5: ["丑", "亥", "酉", "未", "巳", "卯"],  # 巽
    6: ["寅", "辰", "午", "申", "戌", "子"],  # 坎
    7: ["辰", "午", "申", "戌", "子", "寅"],  # 艮
    8: ["未", "巳", "卯", "丑", "亥", "酉"],  # 坤
}


class LiuyaoPaipan:
    """六爻排盘类"""

    def __init__(
        self,
        question: str,
        method: str,
        gender: str = "unknown",
        timestamp: Optional[datetime] = None,
        location: str = "beijing",
        solar_time: bool = True,
        numbers: Optional[List[int]] = None,
    ):
        """
        初始化排盘

        Args:
            question: 问事内容
            method: 起卦方式 (number/coin/time)
            gender: 性别 (male/female/unknown)
            timestamp: 起卦时间
            location: 起卦地点
            solar_time: 是否使用真太阳时
            numbers: 数字起卦时的数字列表 [上卦数, 下卦数, 动爻数]
        """
        self.question = question
        self.method = method
        self.gender = gender
        self.timestamp = timestamp or datetime.now()
        self.location = location
        self.solar_time = solar_time
        self.numbers = numbers
        self.hexagram_id = str(uuid.uuid4())[:8]

    def calc(self) -> Dict:
        """执行排盘计算"""
        if self.method == "number":
            return self._calc_by_number()
        elif self.method == "coin":
            return self._calc_by_coin()
        elif self.method == "time":
            return self._calc_by_time()
        else:
            raise ValueError(f"Unknown method: {self.method}")

    def _calc_by_number(self) -> Dict:
        """数字起卦"""
        if not self.numbers or len(self.numbers) != 3:
            raise ValueError("数字起卦需要提供3个数字：[上卦数, 下卦数, 动爻数]")

        shang_num, xia_num, dong_num = self.numbers

        # 计算上卦和下卦（对8取余，余数为0则为8）
        shang_gua = (shang_num % 8) or 8
        xia_gua = (xia_num % 8) or 8

        # 计算动爻（对6取余，余数为0则为6）
        dong_yao = (dong_num % 6) or 6

        return self._build_hexagram(shang_gua, xia_gua, dong_yao)

    def _calc_by_coin(self) -> Dict:
        """铜钱起卦（模拟摇卦6次）"""
        lines = []
        dong_yao = None

        for i in range(6):
            # 模拟摇3个铜钱，正面为3，反面为2
            coins = [random.choice([2, 3]) for _ in range(3)]
            total = sum(coins)

            # 6=老阴（变），7=少阳，8=少阴，9=老阳（变）
            if total == 6:  # 三个反面
                yao_type = "老阴"
                is_yang = False
                is_dong = True
            elif total == 7:  # 两反一正
                yao_type = "少阳"
                is_yang = True
                is_dong = False
            elif total == 8:  # 两正一反
                yao_type = "少阴"
                is_yang = False
                is_dong = False
            else:  # total == 9，三个正面
                yao_type = "老阳"
                is_yang = True
                is_dong = True

            lines.append({"type": yao_type, "is_yang": is_yang, "is_dong": is_dong})

            if is_dong and dong_yao is None:
                dong_yao = i + 1

        # 从六爻推导出上卦和下卦
        xia_gua = self._lines_to_gua(lines[:3])
        shang_gua = self._lines_to_gua(lines[3:])

        return self._build_hexagram(shang_gua, xia_gua, dong_yao or 1, lines)

    def _calc_by_time(self) -> Dict:
        """时间起卦"""
        year = self.timestamp.year
        month = self.timestamp.month
        day = self.timestamp.day
        hour = self.timestamp.hour

        # 上卦 = (年 + 月 + 日) % 8
        shang_gua = ((year + month + day) % 8) or 8

        # 下卦 = (年 + 月 + 日 + 时) % 8
        xia_gua = ((year + month + day + hour) % 8) or 8

        # 动爻 = (年 + 月 + 日 + 时) % 6
        dong_yao = ((year + month + day + hour) % 6) or 6

        return self._build_hexagram(shang_gua, xia_gua, dong_yao)

    def _lines_to_gua(self, lines: List[Dict]) -> int:
        """从三个爻推导出卦象编号"""
        # 从下往上：阳爻=1，阴爻=0
        binary = "".join(["1" if line["is_yang"] else "0" for line in reversed(lines)])
        mapping = {
            "111": 1,  # 乾
            "011": 2,  # 兑
            "101": 3,  # 离
            "001": 4,  # 震
            "110": 5,  # 巽
            "010": 6,  # 坎
            "100": 7,  # 艮
            "000": 8,  # 坤
        }
        return mapping.get(binary, 1)

    def _build_hexagram(
        self,
        shang_gua: int,
        xia_gua: int,
        dong_yao: int,
        lines: Optional[List[Dict]] = None,
    ) -> Dict:
        """构建完整卦象数据"""
        # 本卦名称
        main_gua_name = LIUSHISI_GUA.get((shang_gua, xia_gua), "未知卦")

        # 如果没有提供爻的详细信息，根据卦象生成
        if lines is None:
            lines = self._generate_lines(shang_gua, xia_gua, dong_yao)

        # 计算变卦
        change_lines = self._calc_change_lines(lines, dong_yao)
        change_xia_gua = self._lines_to_gua(change_lines[:3])
        change_shang_gua = self._lines_to_gua(change_lines[3:])
        change_gua_name = LIUSHISI_GUA.get((change_shang_gua, change_xia_gua), "未知卦")

        # 世应爻（简化版本，实际需要根据卦宫判断）
        shi_yao, ying_yao = self._calc_shi_ying(shang_gua, xia_gua)

        # 装纳甲
        lines_with_najia = self._zhuang_najia(lines, xia_gua, shang_gua)

        # 配六兽（简化版本）
        lines_with_liushou = self._pei_liushou(lines_with_najia)

        return {
            "hexagram_id": self.hexagram_id,
            "question": self.question,
            "method": self.method,
            "gender": self.gender,
            "timestamp": self.timestamp.isoformat(),
            "location": self.location,
            "solar_time": self.solar_time,
            "numbers": self.numbers,
            "main_gua": main_gua_name,
            "change_gua": change_gua_name,
            "shang_gua": BAGUA[shang_gua]["name"],
            "xia_gua": BAGUA[xia_gua]["name"],
            "dong_yao": dong_yao,
            "shi_yao": shi_yao,
            "ying_yao": ying_yao,
            "lines": lines_with_liushou,
            "ganzhi": self._get_ganzhi(),
        }

    def _generate_lines(self, shang_gua: int, xia_gua: int, dong_yao: int) -> List[Dict]:
        """根据卦象生成六爻"""
        lines = []

        # 下卦三爻
        for i in range(3):
            gua_num = xia_gua
            is_yang = self._is_yang_yao(gua_num, i)
            is_dong = (i + 1) == dong_yao
            lines.append({
                "position": i + 1,
                "is_yang": is_yang,
                "is_dong": is_dong,
                "type": "老阳" if (is_yang and is_dong) else ("老阴" if (not is_yang and is_dong) else ("少阳" if is_yang else "少阴"))
            })

        # 上卦三爻
        for i in range(3):
            gua_num = shang_gua
            is_yang = self._is_yang_yao(gua_num, i)
            is_dong = (i + 4) == dong_yao
            lines.append({
                "position": i + 4,
                "is_yang": is_yang,
                "is_dong": is_dong,
                "type": "老阳" if (is_yang and is_dong) else ("老阴" if (not is_yang and is_dong) else ("少阳" if is_yang else "少阴"))
            })

        return lines

    def _is_yang_yao(self, gua_num: int, position: int) -> bool:
        """判断某个卦的某个位置是否为阳爻"""
        # 乾=111, 兑=011, 离=101, 震=001, 巽=110, 坎=010, 艮=100, 坤=000
        yang_patterns = {
            1: [True, True, True],    # 乾
            2: [True, True, False],   # 兑
            3: [True, False, True],   # 离
            4: [True, False, False],  # 震
            5: [False, True, True],   # 巽
            6: [False, True, False],  # 坎
            7: [False, False, True],  # 艮
            8: [False, False, False], # 坤
        }
        return yang_patterns[gua_num][position]

    def _calc_change_lines(self, lines: List[Dict], dong_yao: int) -> List[Dict]:
        """计算变卦的爻"""
        change_lines = []
        for i, line in enumerate(lines):
            if (i + 1) == dong_yao:
                # 动爻变化：阳变阴，阴变阳
                change_lines.append({
                    "is_yang": not line["is_yang"],
                    "is_dong": False,
                })
            else:
                change_lines.append({
                    "is_yang": line["is_yang"],
                    "is_dong": False,
                })
        return change_lines

    def _calc_shi_ying(self, shang_gua: int, xia_gua: int) -> Tuple[int, int]:
        """计算世应爻（简化版本）"""
        # 实际应根据八宫卦序判断，这里简化处理
        if shang_gua == xia_gua:
            # 八纯卦，世在上爻
            return (6, 3)
        else:
            # 简化：世在三爻，应在六爻
            return (3, 6)

    def _zhuang_najia(self, lines: List[Dict], xia_gua: int, shang_gua: int) -> List[Dict]:
        """装纳甲（配地支）"""
        result = []

        # 下卦三爻
        xia_najia = NAJIA[xia_gua]
        for i in range(3):
            line = lines[i].copy()
            line["dizhi"] = xia_najia[i]
            result.append(line)

        # 上卦三爻
        shang_najia = NAJIA[shang_gua]
        for i in range(3):
            line = lines[i + 3].copy()
            line["dizhi"] = shang_najia[i + 3]
            result.append(line)

        return result

    def _pei_liushou(self, lines: List[Dict]) -> List[Dict]:
        """配六兽"""
        result = []
        for i, line in enumerate(lines):
            line_copy = line.copy()
            line_copy["liushou"] = LIUSHOU[i % 6]
            result.append(line_copy)
        return result

    def _get_ganzhi(self) -> Dict:
        """获取干支信息（简化版本）"""
        year = self.timestamp.year
        month = self.timestamp.month
        day = self.timestamp.day
        hour = self.timestamp.hour

        # 简化处理，实际需要农历转换
        return {
            "year": f"{TIANGAN[year % 10]}{DIZHI[year % 12]}",
            "month": f"{TIANGAN[month % 10]}{DIZHI[month % 12]}",
            "day": f"{TIANGAN[day % 10]}{DIZHI[day % 12]}",
            "hour": f"{TIANGAN[hour % 10]}{DIZHI[(hour // 2) % 12]}",
        }
