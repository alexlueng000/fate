"""
初始化敏感词数据
运行方式: python init_sensitive_words.py
"""
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db import Base, engine
from app.models.sensitive_word import SensitiveWord

# 默认敏感词列表
DEFAULT_WORDS = [
    # 吉凶相关（特定组合）
    {"word": "大吉", "replacement": "非常积极", "category": "术语", "priority": 10},
    {"word": "大凶", "replacement": "较大挑战", "category": "术语", "priority": 10},
    {"word": "吉日", "replacement": "适宜日", "category": "术语", "priority": 10},
    {"word": "凶日", "replacement": "需谨慎日", "category": "术语", "priority": 10},
    {"word": "吉时", "replacement": "适宜时段", "category": "术语", "priority": 10},
    {"word": "凶时", "replacement": "需注意时段", "category": "术语", "priority": 10},
    {"word": "吉凶", "replacement": "顺逆", "category": "术语", "priority": 10},

    # 财运相关
    {"word": "破财", "replacement": "资源流动期", "category": "术语", "priority": 5},
    {"word": "发财", "replacement": "资源增长期", "category": "术语", "priority": 5},
    {"word": "财运", "replacement": "财星能量", "category": "术语", "priority": 5},
    {"word": "旺财", "replacement": "财务机遇期", "category": "术语", "priority": 5},

    # 命理术语
    {"word": "八字", "replacement": "出生结构", "category": "术语", "priority": 5},
    {"word": "命盘", "replacement": "个人画像", "category": "术语", "priority": 5},
    {"word": "运势", "replacement": "阶段感受", "category": "术语", "priority": 5},
    {"word": "大运", "replacement": "阶段特征", "category": "术语", "priority": 5},
    {"word": "流年", "replacement": "年度周期", "category": "术语", "priority": 5},
    {"word": "感情运", "replacement": "关系模式", "category": "术语", "priority": 5},
    {"word": "官运", "replacement": "职业发展倾向", "category": "术语", "priority": 5},
    {"word": "婚姻", "replacement": "亲密关系", "category": "术语", "priority": 5},
    {"word": "旺桃花", "replacement": "社交活跃期", "category": "术语", "priority": 5},

    # 迷信相关
    {"word": "算命", "replacement": "文化解读", "category": "迷信", "priority": 5},
    {"word": "算卦", "replacement": "文化解读", "category": "迷信", "priority": 5},
    {"word": "卜卦", "replacement": "文化解读", "category": "迷信", "priority": 5},
    {"word": "看命", "replacement": "了解自己", "category": "迷信", "priority": 5},
    {"word": "测命", "replacement": "自我认知", "category": "迷信", "priority": 5},
    {"word": "改命", "replacement": "自我提升", "category": "迷信", "priority": 5},
    {"word": "命好", "replacement": "状态较好", "category": "迷信", "priority": 5},
    {"word": "命不好", "replacement": "面临挑战", "category": "迷信", "priority": 8},
    {"word": "祸福", "replacement": "得失", "category": "迷信", "priority": 5},

    # 确定性表述
    {"word": "注定", "replacement": "倾向于", "category": "确定性", "priority": 5},
    {"word": "必然", "replacement": "很可能", "category": "确定性", "priority": 5},
    {"word": "一定会", "replacement": "可能会", "category": "确定性", "priority": 8},
    {"word": "预言", "replacement": "趋势分析", "category": "确定性", "priority": 5},
    {"word": "预测未来", "replacement": "趋势参考", "category": "确定性", "priority": 8},

    # 冲突相关
    {"word": "天生克", "replacement": "性格差异", "category": "冲突", "priority": 8},
    {"word": "克父母", "replacement": "与长辈关系需磨合", "category": "冲突", "priority": 8},
    {"word": "克配偶", "replacement": "与伴侣需要沟通", "category": "冲突", "priority": 8},
    {"word": "相克", "replacement": "需要磨合", "category": "冲突", "priority": 5},

    # 功利相关
    {"word": "转运", "replacement": "调整状态", "category": "功利", "priority": 5},
    {"word": "改运", "replacement": "改善现状", "category": "功利", "priority": 5},
    {"word": "化解", "replacement": "改善", "category": "功利", "priority": 5},
    {"word": "破解", "replacement": "优化", "category": "功利", "priority": 5},
]


def init_sensitive_words():
    """初始化敏感词数据"""
    # 创建表（如果不存在）
    Base.metadata.create_all(bind=engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # 检查是否已有数据
        existing_count = session.query(SensitiveWord).count()
        if existing_count > 0:
            print(f"数据库中已有 {existing_count} 条敏感词记录")
            choice = input("是否清空并重新导入？(y/N): ").strip().lower()
            if choice != 'y':
                print("取消导入")
                return
            # 清空现有数据
            session.query(SensitiveWord).delete()
            session.commit()
            print("已清空现有数据")

        # 插入默认敏感词
        added = 0
        for item in DEFAULT_WORDS:
            word = SensitiveWord(
                word=item["word"],
                replacement=item["replacement"],
                category=item.get("category", "general"),
                is_regex=item.get("is_regex", False),
                priority=item.get("priority", 0),
                status=1,
                note=item.get("note"),
            )
            session.add(word)
            added += 1

        session.commit()
        print(f"成功导入 {added} 条敏感词")

    except Exception as e:
        session.rollback()
        print(f"导入失败: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    init_sensitive_words()
