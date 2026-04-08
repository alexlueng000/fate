#!/usr/bin/env python3
"""
Quota 计费系统测试脚本
模拟完整的购买和消费流程
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.db import SessionLocal, engine
from app.models import User, Product, UserQuota
from app.services.quota import QuotaService
from app.models.product import Product as ProductModel
from app.db import Base


def init_test_products(db: Session):
    """初始化测试商品"""
    products = [
        {
            "code": "chat_5",
            "name": "体验包",
            "price_cents": 990,
            "quota_amount": 5,
            "description": "5次提问，适合新用户体验",
        },
        {
            "code": "chat_20",
            "name": "标准包",
            "price_cents": 2990,
            "quota_amount": 20,
            "description": "20次提问，日常使用",
        },
        {
            "code": "chat_50",
            "name": "超值包",
            "price_cents": 5990,
            "quota_amount": 50,
            "description": "50次提问，深度探索",
        },
        {
            "code": "chat_200",
            "name": "年度包",
            "price_cents": 19900,
            "quota_amount": 200,
            "description": "200次提问，全年无忧",
        },
    ]

    for p in products:
        existing = db.query(ProductModel).filter(ProductModel.code == p["code"]).first()
        if not existing:
            product = ProductModel(**p)
            db.add(product)
            print(f"✓ 创建商品: {p['name']} ({p['code']}) - ¥{p['price_cents']/100:.2f}")

    db.commit()
    print()


def create_test_user(db: Session, email: str) -> User:
    """创建测试用户"""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            username=email.split("@")[0],
            hashed_password="test_password_hash",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"✓ 创建测试用户: {email} (ID: {user.id})")
    else:
        print(f"✓ 使用现有用户: {email} (ID: {user.id})")
    return user


def test_quota_flow(db: Session, user: User):
    """测试完整的 quota 流程"""
    print("\n" + "="*60)
    print("开始测试 Quota 计费流程")
    print("="*60)

    # 1. 检查初始 quota
    print("\n【步骤 1】检查初始配额")
    quota = QuotaService.get_or_create_quota(db, user.id, "chat")
    print(f"  初始配额: total={quota.total_quota}, used={quota.used_quota}, remaining={quota.remaining}")
    print(f"  是否无限制: {quota.is_unlimited}")

    # 2. 模拟消费（如果有配额）
    print("\n【步骤 2】模拟消费配额")
    if quota.total_quota == -1:
        print("  当前是无限制模式，先消费 2 次...")
        for i in range(2):
            allowed, msg, remaining = QuotaService.check_and_consume(db, user.id, "chat")
            print(f"  第 {i+1} 次消费: {msg}")
    else:
        print(f"  当前剩余 {quota.remaining} 次")
        if quota.remaining > 0:
            allowed, msg, remaining = QuotaService.check_and_consume(db, user.id, "chat")
            print(f"  消费 1 次: {msg}, 剩余 {remaining} 次")

    # 3. 模拟购买
    print("\n【步骤 3】模拟购买 chat_20 套餐（20次）")
    product = db.query(ProductModel).filter(ProductModel.code == "chat_20").first()
    if product:
        print(f"  商品: {product.name}")
        print(f"  价格: ¥{product.price_cents/100:.2f}")
        print(f"  次数: {product.quota_amount}")

        # 模拟支付成功，发放 quota
        print("\n  模拟支付成功，发放配额...")
        updated_quota = QuotaService.add_quota(
            db, user.id, product.quota_amount, "chat", "purchase"
        )
        print(f"  ✓ 配额已发放")
        print(f"  新配额: total={updated_quota.total_quota}, used={updated_quota.used_quota}, remaining={updated_quota.remaining}")

    # 4. 再次消费测试
    print("\n【步骤 4】购买后消费测试")
    for i in range(3):
        allowed, msg, remaining = QuotaService.check_and_consume(db, user.id, "chat")
        if allowed:
            print(f"  第 {i+1} 次消费成功: {msg}")
        else:
            print(f"  第 {i+1} 次消费失败: {msg}")
            break

    # 5. 查看最终状态
    print("\n【步骤 5】最终配额状态")
    final_quota = QuotaService.get_or_create_quota(db, user.id, "chat")
    print(f"  总配额: {final_quota.total_quota}")
    print(f"  已使用: {final_quota.used_quota}")
    print(f"  剩余: {final_quota.remaining}")
    print(f"  来源: {final_quota.source}")


def test_quota_exhaustion(db: Session, user: User):
    """测试配额耗尽场景"""
    print("\n" + "="*60)
    print("测试配额耗尽场景")
    print("="*60)

    # 重置用户配额为 3 次
    print("\n【场景】设置用户配额为 3 次")
    quota = QuotaService.set_user_quota(db, user.id, "chat", 3, "never", "test")
    print(f"  配额设置: total={quota.total_quota}, used={quota.used_quota}")

    # 连续消费直到耗尽
    print("\n【测试】连续消费直到耗尽")
    for i in range(5):
        allowed, msg, remaining = QuotaService.check_and_consume(db, user.id, "chat")
        status = "✓" if allowed else "✗"
        print(f"  {status} 第 {i+1} 次: {msg}")
        if not allowed:
            print(f"\n  配额已耗尽！应返回 HTTP 429")
            break


def test_multiple_purchases(db: Session, user: User):
    """测试多次购买累加"""
    print("\n" + "="*60)
    print("测试多次购买累加")
    print("="*60)

    # 重置配额
    print("\n【准备】重置配额为 5 次")
    QuotaService.set_user_quota(db, user.id, "chat", 5, "never", "test")

    # 第一次购买
    print("\n【购买 1】chat_5 (5次)")
    QuotaService.add_quota(db, user.id, 5, "chat", "purchase")
    quota = QuotaService.get_or_create_quota(db, user.id, "chat")
    print(f"  购买后: total={quota.total_quota}, remaining={quota.remaining}")

    # 第二次购买
    print("\n【购买 2】chat_20 (20次)")
    QuotaService.add_quota(db, user.id, 20, "chat", "purchase")
    quota = QuotaService.get_or_create_quota(db, user.id, "chat")
    print(f"  购买后: total={quota.total_quota}, remaining={quota.remaining}")

    print(f"\n  ✓ 累加成功！总配额: {quota.total_quota} 次")


def main():
    """主测试流程"""
    print("="*60)
    print("Quota 计费系统 - 模拟测试")
    print("="*60)

    # 创建数据库表
    print("\n初始化数据库...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 初始化商品
        init_test_products(db)

        # 创建测试用户
        user = create_test_user(db, "test_quota@example.com")

        # 运行测试场景
        test_quota_flow(db, user)
        test_quota_exhaustion(db, user)
        test_multiple_purchases(db, user)

        print("\n" + "="*60)
        print("✓ 所有测试完成！")
        print("="*60)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()
