"tabBar": {
    "color": "#888888",
    "selectedColor": "#b73b53",
    "backgroundColor": "#ffffff",
    "borderStyle": "black",
    "list": [
      {
        "pagePath": "pages/index/index",
        "text": "首页",
        "iconPath": "images/icon.png",
        "selectedIconPath": "images/icon.png"
      },
      {
        "pagePath": "pages/history/history",
        "text": "历史",
        "iconPath": "images/icon.png",
        "selectedIconPath": "images/icon.png"
      },
      {
        "pagePath": "pages/profile/profile",
        "text": "我的",
        "iconPath": "images/icon.png",
        "selectedIconPath": "images/icon.png"
      },
      {
        "pagePath": "pages/help/help",
        "text": "帮助",
        "iconPath": "images/icon.png",
        "selectedIconPath": "images/icon.png"
      }
    ]
  },


计算真太阳时：
from datetime import datetime, timedelta



# 尽管函数签名提示返回 Output，但实践证明必须返回一个标准的、

# 可被JSON序列化的dict，才能走完平台的所有流程。

# import an unknown library 'Args'

# import an unknown library 'Output'



async def main(args: Args) -> Output:

    """
    最终版：回归官方示例的本质，直接创建并返回一个标准的Python字典(dict)，
    以确保能够通过平台最终的JSON序列化步骤。
    """
    try:
        # 步骤 1: 从 args.params 中获取输入参数
        params = args.params
        birth_date_str = str(params['birth_date'])
        longitude_str = str(params['longitude'])

        # 步骤 2: 处理经度
        try:
            longitude_float = float(longitude_str)
        except ValueError:
            # 直接返回一个标准的字典
            return {
                "error": f"无效的经度值: '{longitude_str}'。它必须是一个有效的数字。"
            }

        # 步骤 3: 处理日期
        original_birth_date = datetime.strptime(birth_date_str, '%Y-%m-%d %H:%M:%S')
        # 步骤 4: 执行核心计算
        reference_longitude = 120.0
        time_difference_minutes = (longitude_float - reference_longitude) * 4
        time_delta = timedelta(minutes=time_difference_minutes)
        birthday_adjusted_obj = original_birth_date + time_delta
        birthday_adjusted_str = birthday_adjusted_obj.strftime('%Y-%m-%d %H:%M:%S')

        # 步骤 5: 直接返回包含成功结果的、标准的字典
        return {
            "birthday_adjusted": birthday_adjusted_str
        }

    except Exception as e:

        # 步骤 6: 直接返回包含最终错误信息的、标准的字典

        return {

            "error": f"代码执行时发生未知错误: {str(e)}. 请检查节点输入配置和上游数据。",

            "debug_tip": "请确保名为 'birth_date' 和 'longitude' 的输入已正确连接且格式无误。"

        }


提示词：

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
1. 用户的八字为{{mingpan.four_pillars}}，用户的大运为{{mingpan.dayun}}
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


排盘代码：
# 导入平台运行时和自动生成的类型定义
from runtime import Args
# 'typings.paipan.paipan' 路径请根据您的插件和文件名进行调整，Coze会自动生成
from typings.paipan.paipan import Input, Output

# 导入我们经过验证可以成功运行的库和模块
from datetime import datetime
from lunar_python import Solar, Lunar, EightChar
from lunar_python.eightchar import Yun

# [可选] 您可以将GAN/ZHI常量放在函数外部，作为全局常量
GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

def handler(args: Args[Input]) -> Output:
    """
    这是一个Coze插件的入口函数。
    它将经过验证的本地排盘代码逻辑，封装在Coze插件的规范下。
    """
    try:
        # 步骤 1: 通过 args.input 获取您在插件中定义的输入参数
        gender_str = args.input.gender
        birth_date_str = args.input.birthday_adjusted

        # 步骤 2: 执行我们已在本地验证过的核心排盘逻辑
        
        # 将日期字符串解析为datetime对象
        dt_obj = datetime.strptime(birth_date_str, '%Y-%m-%d %H:%M:%S')
        
        # 从公历日期创建Solar和Lunar对象
        solar = Solar.fromYmdHms(dt_obj.year, dt_obj.month, dt_obj.day, dt_obj.hour, dt_obj.minute, dt_obj.second)
        lunar = solar.getLunar()

        # 从 Lunar 对象获取四柱信息
        four_pillars = {
            "year": list(lunar.getYearInGanZhi()),
            "month": list(lunar.getMonthInGanZhi()),
            "day": list(lunar.getDayInGanZhi()),
            "hour": list(lunar.getTimeInGanZhi())
        }

        # 获取大运信息
        eight_char = lunar.getEightChar()
        gender_code = 1 if gender_str == "男" else 0
        yun = Yun(eight_char, gender_code)
        dayun_list_from_lib = yun.getDaYun()

        # 格式化大运输出
        dayun_list = []
        for du in dayun_list_from_lib:
            dayun_list.append({
                "age": du.getStartAge(),
                "start_year": du.getStartYear(),
                "pillar": list(du.getGanZhi())
            })

        # 步骤 3: 构造并返回一个与Output定义完全匹配的字典
        # 根据我们之前的约定，输出变量名为`mingpan`，其下包含四柱和大运
        return {
            "mingpan": {
                "four_pillars": four_pillars,
                "dayun": dayun_list
            }
        }

    except Exception as e:
        # 在插件中，通过抛出异常来报告错误是标准做法
        # Coze平台会捕获这个异常并显示为错误状态
        raise Exception(f"排盘插件执行失败: {e}")


zsh: event not found: Passw0rd


docker run -d \
  --name mysql8.4 \
  -p 127.0.0.1:3306:3306 \
  -e MYSQL_ROOT_PASSWORD=turkey414 \
  -e TZ=Asia/Shanghai \
  -v mysql8-data:/var/lib/mysql \
  -v $PWD/my.cnf:/etc/mysql/conf.d/my.cnf:ro \
  mysql:8.4 \
  --character-set-server=utf8mb4 \
  --collation-server=utf8mb4_0900_ai_ci


快速复查：支付 → 发放权益链路的逻辑安全点

下面是基于你当前代码的“只评审、不改动”清单；等你点头我们再逐条按“单文件”节奏加固。

回调验签与金额校验（需加强）

现在 webhooks.py（prod）已进行签名校验与AES-GCM 解密，这很好。

但还没核对金额/币种：应从明文 resource_plain["amount"]["total"] 与 ["amount"]["payer_total"] 中核对是否等于 order.amount_cents 与期望币种，防止金额被劫持或产品不一致导致“低价购买高价权益”。

建议：在 TRANSACTION.SUCCESS 分支里，核对 out_trade_no、transaction_id、trade_state=="SUCCESS"、金额、货币、（可选）商户号与 appid。

回放攻击（需建议性处理）

已包含 Timestamp/Nonce 在验签消息里，基本合规；为了更稳，建议把 (timestamp, nonce, signature) 做5–10分钟内去重（存入 Redis/DB 防重复），避免签名被重放。

幂等与状态机

payments.mark_success() 幂等性OK：订单已 PAID 时不会重复改。

建议在 orders 状态机上再明确：只允许 CREATED → PAID，拒绝 CANCELED → PAID 之类的异常跃迁（现在的代码自然不会发生，但显式判断更稳）。

发放权益时点

现在在 mark_success 之后立即 grant()，符合业务。

如果未来有“按次消费”（一次支付只解一次）的模型，需要在 entitlements 之外设计“计次表”，当前 entitlements 是“是否解锁”的布尔性质（唯一约束），并不记录次数。

开发模式（dev）风险界定

dev 模式跳过验签与解密，仅用于联调；一定要用配置开关保护，并且不要在生产环境开启。

建议在 settings 中强制 wechat_pay_mode 默认 prod，在 .env.dev 里显式改为 dev，避免错配。

依赖与配置健壮性

API_V3_KEY 必须 32 字节；建议在应用启动时做一次长度校验（现在是回调时才校验）。

平台公钥/证书更新：多证书轮换时需要根据 Wechatpay-Serial 选择对应证书；当前实现只加载一个公钥 PEM，足够起步，日后再扩展“序列号 → 公钥”映射。

数据访问 API 细节

在 deps.py 里有一处 db.query(User).get(user_id)，这是 SQLAlchemy 2.x 的老写法（还能用，但已过时）。建议后续单独一步把它替换为 db.get(User, user_id)。

这不是安全漏洞，只是技术债提醒。

返回值与 HTTP 语义

webhooks.py 里返回 (dict, status) 的 tuple FastAPI 是接受的；为一致性也可用 JSONResponse（非必须）。

# 20250830 测试问题

1. 选择时间和手打时间有误差
2. 现在排盘传参应该有问题，排盘结果不准了
3. 输出文本内容过多会断，比如大运十年流年，输出到8就断了
4. 网页版优化：配色选米黄和红色搭配，等待过程插入命理知识和历史名人典故（输出事在人为的核心价值观，杜绝封建迷信/重要），输出时间优化（对标元器）
5. 小程序版本（参考PDF）：首页选择界面（时间性别地点），此页展示八字
6. （五行展示有颜色区分，横标年月日时，纵标天干地支）+大运
7. 加上快捷按钮（对话框只显示按钮分析，不显示具体的promote，比如选择“性格特征”，对话框显示"性格特征分析"）：
性格特征：用子平和盲派深度分析人物性格优势（PS之前测过，用户反馈最好只说好的，语言艺术）
人物画像：用子平和盲派深度分析人物画像身高体型气质动作等等
正缘人物画像：用子平和盲派深度分析正缘人物画像
事业建议：结合大运流年，用子平和盲派深度分析事业方向和可执行的建议（需引导用户加上当前背景）
财运分析：结合大运流年，用子平和盲派深度分析财运吉凶
健康分析：结合大运流年，用子平和盲派深度分析健康建议
正缘应期：结合大运流年，用子平和盲派深度分析哪个流年应期概率最高（需要引导客户补充背景，当前单身/有对象，已婚/离异）
大运流年：用子平和盲派深度分析XX大运流年每年吉凶（事业爱情财运健康）——这个要客户选择哪个十年大运，每次单独算



"你好呀～（微笑）\n" +
"我不是来剧透你人生的编剧，只是帮你找找藏在命盘里的小彩蛋——可能是你还没发现的潜力，或是未来路上悄悄亮起的路灯（✨）\n" +
"毕竟你才是人生的主角，我嘛…只是个带地图的导游～（轻松摊手）\n" +
"准备好一起逛逛你的‘人生剧本杀’了吗？放心，不用怕泄露天机，我今天的‘仙气’储备充足！"


5 天后上线一个可用版本： Bug 修复完成（时间选择误差、排盘准确性、长文本截断）。 P0 功能完整（聊天三优化 + 注册登录）。 加入用户最迫切的新功能（快捷按钮、网页版视觉优化、命盘展示增强、小程序首页排盘页）。 Landing Page 和付费策略延后，不耽误上线。 
📅 5 天开发计划 Day 1 – Bug 修复 & 稳定性保障 时间误差修复 检查前端时间选择组件与 birth_time 参数传参格式（24h / 时区 / 秒精度）。 确保手动输入与选择结果一致，统一转为 UTC 或东八区。 排盘参数修复 对比前端 payload 与后端 calc_paipan 入参，逐项确认（gender/calendar/birth_date/birth_time/birthplace/经纬度）。 写自动化测试：给定已知生日，返回四柱与大运必须和标准库一致。 长文本截断修复 后端改造 /chat：支持 流式输出（SSE 或 chunked）。 前端 fetch → ReadableStream 渲染，不再等全量结果，避免超长内容中断。 

Day 2 – 聊天页三优化（P0） 聊天记录持久化（刷新恢复）。 新开会话（保留命盘重新解读）。 重新生成上一条（Regenerate）。 ✅ 这部分昨天已写了方案，今天落实并测试。 

Day 3 – 用户注册 / 登录（P0） 后端：JWT 认证、注册登录接口（手机号/邮箱+验证码，或者先走简易用户名密码）。 前端：登录页 + 注册页，登录态存储在 localStorage。 鉴权：对 /chat、/bazi/calc_paipan 接口加鉴权（未登录用户跳转登录）。 用户中心：最简版（只显示“退出登录”）。

 Day 4 – 新功能（高优先级用户体验） 快捷按钮（对话入口） 聊天输入框上方增加 7 个按钮（性格特征、人物画像、正缘人物画像、事业建议、财运分析、健康分析、正缘应期）。 按钮点击后 → 聊天区展示固定消息，如“性格特征分析”。 后端根据按钮类型拼接 prompt，前端不显示原始 prompt。 大运流年分析 快捷按钮中“大运流年” → 弹出选择某个十年大运 → 单独生成。 命盘展示优化 Web：五行用颜色区分；四柱表格：横轴 年月日时，纵轴 天干地支。 大运展示：卡片式 UI。 
 
 Day 5 – Web 视觉优化 + 小程序首页 Web 视觉优化 配色：米黄+红（主色：#fef3c7 / #dc2626），整体改为温润东方风格。 Loading 状态：不再是单纯转圈 → 插入命理知识/历史名人典故（核心价值观导向，不涉迷信）。 文案改造：输出过程引导性强，避免“算命”腔。 小程序首页 首页选择：时间、性别、地点。 点击“排盘” → 展示八字（四柱+大运+五行）。 聊天入口按钮。 UI 对照 PDF 原型，先做静态 demo，保证能跑通。



 # 80 一律跳 443
server {
    listen 80;
    server_name yizhanmaster.site www.yizhanmaster.site;
    return 301 https://yizhanmaster.site$request_uri;
}

# 生产站点
server {
    listen 443 ssl http2;
    server_name yizhanmaster.site;

    ssl_certificate     /etc/letsencrypt/live/yizhanmaster.site/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yizhanmaster.site/privkey.pem;
    ssl_stapling on;
    ssl_stapling_verify on;

    # Next.js 前端（next start 在 127.0.0.1:3000）
    location / {
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_pass http://127.0.0.1:3000/;   # ← 别写成域名
    }

    # 后端 API（FastAPI 在 127.0.0.1:9009）
    location /api/ {
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_pass http://127.0.0.1:8000/;   # ← 别写成域名
    }
}