import requests
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any
from pydantic import BaseModel
from lunar_python import Solar, Lunar, EightChar
from lunar_python.eightchar import Yun


# ====== 配置 ======
DEEPSEEK_API_KEY = "sk-12fe6f3f7ad3495cb7d16dfef3240882"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL   = "deepseek-chat"

system_prompt = """
# 角色
你是一位专业的八字命理师，擅长运用子平和盲派的理论与方法，为用户提供精准的八字分析服务。无论用户提供的是阳历生日还是阴历生日，你都能将其转换为阴历，并准确排出八字和起大运。

# 语言风格
你的语言风格温和而知心，总是能够用简洁明了的语言，解释复杂的命理知识。你的话语中透露出智慧和自信，让人感到安心和信任。

# 人物喜好
你喜欢研究命理学，熟读子平法和盲派命理学，也喜欢与同行交流经验和心得。你还喜欢阅读历史书籍和哲学书籍，这些书籍对你的命理研究有着很大的启发和帮助。

# 其他要求
- 你是一个专业的命理师，擅长解读八字、风水、紫微斗数等命理知识。
- 当用户向你咨询命理问题时，你会根据用户提供的信息，结合自己的专业知识，给出详细的解答和建议。
- 你的回答需要准确、专业，减少命理专业名词，并且通俗理解的语句帮助用户更好地了解自己的命运和未来。
- 你不会在回复之前加入任何动作、表情、心理状态或人物状态的描述。
- 禁止使用‘招财’‘转运’‘运势’‘事业运’‘化解’‘消灾解难’等违禁词，使用‘协助’‘辅助’等字眼，例如避免敏感表述：将“化解冲煞”改为“注意方位冲突”，“转运”改为“调整能量布局”。禁止使用如‘资料库’、‘文档’、‘子平’、‘盲派’、‘deepseek’等字眼。
- 侧重分析人物性格特征，用正向肯定的语气，用赞誉的词句重点描述人物性格（只突出优点）。
- 侧重于五行平衡、十神联动及具体场景策略，以合规表述为核心的深度分析与行动建议。
- 按照文档的排运规则根据真太阳时排八字和起大运、排大运。

## 技能
### 基础分析: 八字基础分析
1. 用户的八字为{{FOUR_PILLARS}}，用户的大运为{{DAYUN}}
2. 运用子平和盲派的理论对原局进行深度分析，确定喜忌用神。
3.建议佩戴首饰
4.结尾处需要明确提出，以上内容由传统文化AI生成，仅供娱乐分析，宣扬人的主观能动性的核心价值观

### 性格特征: 人物性格特征分析
结合大运流年，运用子平和盲派的方法，深入分析人物的性格特征，包括但不限于为人处世风格、情绪特点、思维模式等。

### 人物画像: 人物画像分析
结合大运流年，运用子平和盲派的理论，全面分析人物画像，涵盖外貌形象、气质神韵等方面。

### 父母职业和家境: 父母职业和家境分析
结合大运流年，运用子平和盲派的方法，详细分析父母的职业倾向以及家庭经济状况。

### 第一学历和专业: 第一学历和专业分析
结合大运流年，运用子平和盲派的理论，分析用户的第一学历层次以及适合的专业方向。

### 正缘应期: 正缘应期分析
结合大运流年，运用子平和盲派的方法，精准推断正缘出现的时间节点。

### 正缘人物画像: 正缘人物画像分析
结合大运流年，运用子平和盲派的理论，描绘正缘的人物画像，包括外貌、性格、职业等特征。

### 事业方向和建议: 事业方向和建议分析
结合大运流年，运用子平和盲派的方法，分析适合的事业方向，并给出具有可操作性的建议。

### 健康: 健康分析
结合大运流年，运用子平和盲派的理论，分析可能出现健康问题的方面，并给出相应的预防建议。

### 技能 10: 过去十年应事吉凶分析
结合大运流年，运用子平和盲派的方法，对过去十年在事业、财运、姻缘、健康方面发生的吉凶事件进行分析。

### 技能 11: 未来十年应事吉凶分析
结合大运流年，运用子平和盲派的方法，对未来十年在事业、财运、姻缘、健康方面可能出现的吉凶情况进行预测分析。

## 限制:
- 只回答与八字命理分析相关的内容，拒绝回答与八字命理无关的话题。
- 所输出的内容应条理清晰，逻辑连贯，对各方面的分析要有理有据。
- 确保分析内容基于子平和盲派的传统理论和方法。 
"""

# 地名 -> 经纬度
def geocode_city(city: str):
    url = "https://nominatim.openstreetmap.org/search" # 可以换别的API
    params = {"q": city, "format": "json", "limit": 1}
    headers = {"User-Agent": "bazi-app/1.0"}  # Nominatim 要求设置 UA
    r = requests.get(url, params=params, headers=headers)
    data = r.json()
    if not data:
        return {"error": f"找不到城市: {city}"}
    return {
        "city": city,
        "lat": float(data[0]["lat"]),
        "lng": float(data[0]["lon"])
    }


class SolarIn(BaseModel):
    birth_date: str   # "YYYY-MM-DD HH:MM:SS"
    longitude: float  # 经度（东经为正，西经为负）


def calc_true_solar(body: SolarIn):
    try:
        # 解析输入时间
        dt = datetime.strptime(body.birth_date, "%Y-%m-%d %H:%M:%S")
        
        # 标准子午线经度（中国默认120°E）
        ref_longitude = 120.0

        # 每1度 = 4分钟
        delta_minutes = (body.longitude - ref_longitude) * 4
        dt_true = dt + timedelta(minutes=delta_minutes)

        return {
            "input_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "longitude": body.longitude,
            "true_solar_time": dt_true.strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        return {"error": str(e)}


class PaipanIn(BaseModel):
    gender: str              # "男" 或 "女"
    birthday_adjusted: str   # "YYYY-MM-DD HH:MM:SS" 通过经纬度算出来的真太阳时


def _split_ganzhi_to_list(gz: str) -> List[str]:
    """
    将 '癸酉' / '  壬子 ' / '' 等转成 ['癸','酉'] 或 []，并去除异常空格。
    lunar_python 的 getXxxInGanZhi() 返回的是字符串，例如 '癸酉'。
    """
    if gz is None:
        return []
    s = str(gz).strip().replace(" ", "")
    # 标准干支长度应为2（一个天干+一个地支）
    return [s[0], s[1]] if len(s) == 2 else []

def calc_bazi(body: PaipanIn) -> Dict[str, Any]:
    """
    入参 body 需要有:
    - body.gender: '男' 或 '女'
    - body.birthday_adjusted: 'YYYY-MM-DD HH:MM:SS'
    返回:
    {
      "mingpan": {
        "four_pillars": { "year": [...], "month": [...], "day": [...], "hour": [...] },
        "dayun": [ {"age":..,"start_year":..,"pillar":[...]} ... ]
      }
    }
    """
    try:
        # 1) 解析时间
        dt_obj = datetime.strptime(body.birthday_adjusted, "%Y-%m-%d %H:%M:%S")

        # 2) 公历 -> Lunar
        solar = Solar.fromYmdHms(dt_obj.year, dt_obj.month, dt_obj.day,
                                 dt_obj.hour, dt_obj.minute, dt_obj.second)
        lunar = solar.getLunar()

        # 3) 四柱（清洗成 ["干","支"]）
        four_pillars = {
            "year":  _split_ganzhi_to_list(lunar.getYearInGanZhi()),
            "month": _split_ganzhi_to_list(lunar.getMonthInGanZhi()),
            "day":   _split_ganzhi_to_list(lunar.getDayInGanZhi()),
            "hour":  _split_ganzhi_to_list(lunar.getTimeInGanZhi()),
        }

        # 4) 大运
        eight_char = lunar.getEightChar()
        gender_code = 1 if str(body.gender).strip() == "男" else 0
        yun = Yun(eight_char, gender_code)

        dayun_list = []
        for du in yun.getDaYun():
            pillar_list = _split_ganzhi_to_list(du.getGanZhi())
            dayun_list.append({
                "age": du.getStartAge(),
                "start_year": du.getStartYear(),
                "pillar": pillar_list  # 若库返回异常或空，会是 []
            })

        # 5) 返回同结构
        return {
            "mingpan": {
                "four_pillars": four_pillars,
                "dayun": dayun_list
            }
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}

# ====== 格式化工具 ======
def format_four_pillars(fp: Dict[str, List[str]]) -> str:
    return (
        f"年柱: {''.join(fp['year'])}\n"
        f"月柱: {''.join(fp['month'])}\n"
        f"日柱: {''.join(fp['day'])}\n"
        f"时柱: {''.join(fp['hour'])}"
    )

def format_dayun(dy: List[Dict]) -> str:
    lines = []
    for item in dy:
        pillar = "".join(item["pillar"])
        lines.append(f"- 起始年龄 {item['age']}，起运年 {item['start_year']}，大运 {pillar}")
    return "\n".join(lines)



def apply_template(FOUR_PILLARS: Dict[str, List[str]], DAYUN: List[Dict]) -> str:
    return system_prompt.replace("{FOUR_PILLARS}", format_four_pillars(FOUR_PILLARS)) \
                          .replace("{DAYUN}", format_dayun(DAYUN))

# ====== 调用 DeepSeek ======
def call_deepseek(messages: List[Dict[str, str]]) -> str:
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 800
    }
    r = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]

# ====== 主循环 ======
def main():
    if not DEEPSEEK_API_KEY:
        print("请先设置环境变量 DEEPSEEK_API_KEY")
        return

    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    history: List[Dict[str, str]] = []

    longitude = geocode_city("广东阳春").get("lng")
    # print("经度：", longitude)
    true_sun = calc_true_solar(SolarIn(birth_date="1993-03-09 7:00:00", longitude=longitude))
    # print("真太阳时：", true_sun)
    bazi = calc_bazi(PaipanIn(gender="男", birthday_adjusted=true_sun.get("true_solar_time")))

    print("==== 八字对话助手（本地 CLI）====")
    print("输入 exit 退出\n")

    while True:
        user_msg = input("你: ").strip()
        if user_msg.lower() in ("exit", "quit"):
            break

        # 组装 messages
        system_prompt = apply_template(bazi.get("mingpan").get("four_pillars"), bazi.get("mingpan").get("dayun"))
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-10:])   # 只保留最近10条历史
        messages.append({"role": "user", "content": user_msg})

        try:
            reply = call_deepseek(messages)
        except Exception as e:
            print(f"[错误] {e}")
            continue

        print(f"AI: {reply}\n")

        # 更新历史
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": reply})


if __name__ == '__main__':
    
    # longitude = geocode_city("广东阳春").get("lng")
    # print("经度：", longitude)
    # true_sun = calc_true_solar(SolarIn(birth_date="1993-03-09 7:00:00", longitude=longitude))
    # print("真太阳时：", true_sun)
    # bazi = calc_bazi(PaipanIn(gender="男", birthday_adjusted=true_sun.get("true_solar_time")))

    # print("PROMPT：", apply_template(bazi.get("mingpan").get("four_pillars"), bazi.get("mingpan").get("dayun")))
    main()