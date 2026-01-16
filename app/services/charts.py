# app/services/charts.py
from sqlalchemy.orm import Session
from app.models.saved_chart import SavedChart
from app.utils.encryption import encrypt_data, decrypt_data


def save_chart(db: Session, user_id: int, name: str, birth_info: dict,
               chart_data: dict) -> SavedChart:
    """保存命盘，自动设为默认"""
    # 取消该用户所有命盘的默认状态
    db.query(SavedChart).filter(
        SavedChart.user_id == user_id
    ).update({"is_default": False})

    chart = SavedChart(
        user_id=user_id,
        name=name,
        encrypted_birth_info=encrypt_data(birth_info),
        encrypted_chart_data=encrypt_data(chart_data),
        is_default=True
    )
    db.add(chart)
    db.flush()
    return chart


def get_user_charts(db: Session, user_id: int) -> list[SavedChart]:
    """获取用户的所有命盘（不解密）"""
    return db.query(SavedChart).filter(
        SavedChart.user_id == user_id
    ).order_by(SavedChart.is_default.desc(), SavedChart.created_at.desc()).all()


def get_chart_detail(db: Session, chart_id: int, user_id: int) -> dict | None:
    """获取命盘详情（解密）"""
    chart = db.query(SavedChart).filter(
        SavedChart.id == chart_id,
        SavedChart.user_id == user_id
    ).first()

    if not chart:
        return None

    return {
        "id": chart.id,
        "name": chart.name,
        "birth_info": decrypt_data(chart.encrypted_birth_info),
        "chart_data": decrypt_data(chart.encrypted_chart_data),
        "is_default": chart.is_default,
        "created_at": chart.created_at.isoformat()
    }


def get_default_chart(db: Session, user_id: int) -> dict | None:
    """获取用户的默认命盘（解密）"""
    chart = db.query(SavedChart).filter(
        SavedChart.user_id == user_id,
        SavedChart.is_default == True
    ).first()

    if not chart:
        return None

    return get_chart_detail(db, chart.id, user_id)


def delete_chart(db: Session, chart_id: int, user_id: int) -> bool:
    """删除命盘"""
    result = db.query(SavedChart).filter(
        SavedChart.id == chart_id,
        SavedChart.user_id == user_id
    ).delete()
    return result > 0


def set_default_chart(db: Session, chart_id: int, user_id: int) -> bool:
    """设置默认命盘"""
    chart = db.query(SavedChart).filter(
        SavedChart.id == chart_id,
        SavedChart.user_id == user_id
    ).first()

    if not chart:
        return False

    # 取消其他默认
    db.query(SavedChart).filter(
        SavedChart.user_id == user_id
    ).update({"is_default": False})

    chart.is_default = True
    return True
