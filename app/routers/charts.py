# app/routers/charts.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.services import charts as chart_service
from app.schemas.chart import (
    SaveChartRequest,
    SaveChartResponse,
    ChartListResponse,
    ChartListItem,
    ChartDetailResponse,
)

router = APIRouter(prefix="/charts", tags=["charts"])


@router.post("", response_model=SaveChartResponse)
def save_chart(
    req: SaveChartRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保存命盘（自动设为默认）"""
    chart = chart_service.save_chart(
        db=db,
        user_id=user.id,
        name=req.name,
        birth_info=req.birth_info,
        chart_data=req.chart_data,
    )
    db.commit()
    return SaveChartResponse(
        id=chart.id,
        name=chart.name,
        is_default=chart.is_default,
        created_at=chart.created_at.isoformat(),
    )


@router.get("", response_model=ChartListResponse)
def list_charts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取用户的命盘列表"""
    charts = chart_service.get_user_charts(db, user.id)
    return ChartListResponse(
        charts=[
            ChartListItem(
                id=c.id,
                name=c.name,
                is_default=c.is_default,
                created_at=c.created_at.isoformat(),
            )
            for c in charts
        ]
    )


@router.get("/default", response_model=ChartDetailResponse | None)
def get_default_chart(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取默认命盘"""
    chart = chart_service.get_default_chart(db, user.id)
    if not chart:
        return None
    return chart


@router.get("/{chart_id}", response_model=ChartDetailResponse)
def get_chart(
    chart_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取命盘详情"""
    chart = chart_service.get_chart_detail(db, chart_id, user.id)
    if not chart:
        raise HTTPException(status_code=404, detail="命盘不存在")
    return chart


@router.delete("/{chart_id}")
def delete_chart(
    chart_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除命盘"""
    success = chart_service.delete_chart(db, chart_id, user.id)
    if not success:
        raise HTTPException(status_code=404, detail="命盘不存在")
    db.commit()
    return {"message": "删除成功"}


@router.put("/{chart_id}/default")
def set_default(
    chart_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """设置默认命盘"""
    success = chart_service.set_default_chart(db, chart_id, user.id)
    if not success:
        raise HTTPException(status_code=404, detail="命盘不存在")
    db.commit()
    return {"message": "已设为默认命盘"}
