# app/services/profile_service.py
"""
用户档案服务
负责创建、更新、查询用户命盘档案
"""
from datetime import date, datetime, time
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models import User, UserProfile
from app.schemas.profile import ProfileCreateRequest, ProfileUpdateRequest
from app.routers.bazi import PaipanIn, calc_bazi


class ProfileService:
    """用户档案服务"""

    @staticmethod
    def get_user_profile(db: Session, user_id: int) -> Optional[UserProfile]:
        """获取用户档案"""
        return db.query(UserProfile).filter(UserProfile.user_id == user_id).first()

    @staticmethod
    def create_profile(
        db: Session,
        user_id: int,
        data: ProfileCreateRequest
    ) -> UserProfile:
        """
        创建用户档案并计算命盘

        Args:
            db: 数据库会话
            user_id: 用户ID
            data: 档案数据

        Returns:
            创建的档案对象

        Raises:
            ValueError: 如果用户已有档案
        """
        # 检查用户是否已有档案
        existing = ProfileService.get_user_profile(db, user_id)
        if existing:
            raise ValueError("用户已有档案，请使用更新接口")

        # 计算命盘
        bazi_chart = ProfileService._calculate_bazi_chart(
            gender=data.gender,
            calendar_type=data.calendar_type,
            birth_date=data.birth_date,
            birth_time=data.birth_time,
            birth_location=data.birth_location,
            birth_longitude=data.birth_longitude,
            birth_latitude=data.birth_latitude,
        )

        # 创建档案
        profile = UserProfile(
            user_id=user_id,
            gender=data.gender,
            calendar_type=data.calendar_type,
            birth_date=data.birth_date,
            birth_time=data.birth_time,
            birth_location=data.birth_location,
            birth_longitude=data.birth_longitude,
            birth_latitude=data.birth_latitude,
            bazi_chart=bazi_chart,
        )

        try:
            db.add(profile)
            db.commit()
            db.refresh(profile)
            return profile
        except IntegrityError as e:
            db.rollback()
            raise ValueError("创建档案失败，用户可能已有档案") from e

    @staticmethod
    def update_profile(
        db: Session,
        user_id: int,
        data: ProfileUpdateRequest
    ) -> UserProfile:
        """
        更新用户档案并重新计算命盘

        Args:
            db: 数据库会话
            user_id: 用户ID
            data: 更新数据（只更新提供的字段）

        Returns:
            更新后的档案对象

        Raises:
            ValueError: 如果用户没有档案
        """
        profile = ProfileService.get_user_profile(db, user_id)
        if not profile:
            raise ValueError("用户没有档案，请先创建")

        # 记录是否有关键字段变更（需要重算命盘）
        needs_recalculation = False

        # 更新字段
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                setattr(profile, field, value)
                # 关键字段变更需要重算
                if field in ["gender", "calendar_type", "birth_date", "birth_time",
                             "birth_location", "birth_longitude", "birth_latitude"]:
                    needs_recalculation = True

        # 如果关键字段变更，重新计算命盘
        if needs_recalculation:
            bazi_chart = ProfileService._calculate_bazi_chart(
                gender=profile.gender,
                calendar_type=profile.calendar_type,
                birth_date=profile.birth_date,
                birth_time=profile.birth_time,
                birth_location=profile.birth_location,
                birth_longitude=profile.birth_longitude,
                birth_latitude=profile.birth_latitude,
            )
            profile.bazi_chart = bazi_chart

        db.commit()
        db.refresh(profile)
        return profile

    @staticmethod
    def delete_profile(db: Session, user_id: int) -> bool:
        """
        删除用户档案

        Args:
            db: 数据库会话
            user_id: 用户ID

        Returns:
            是否删除成功
        """
        profile = ProfileService.get_user_profile(db, user_id)
        if not profile:
            return False

        db.delete(profile)
        db.commit()
        return True

    @staticmethod
    def _calculate_bazi_chart(
        gender: str,
        calendar_type: str,
        birth_date: date,
        birth_time: time,
        birth_location: str,
        birth_longitude: Optional[float] = None,
        birth_latitude: Optional[float] = None,
    ) -> dict:
        """
        计算八字命盘

        Args:
            gender: 性别 (male/female)
            calendar_type: 历法类型 (solar/lunar)
            birth_date: 出生日期
            birth_time: 出生时间
            birth_location: 出生地点
            birth_longitude: 经度
            birth_latitude: 纬度

        Returns:
            命盘数据字典
        """
        try:
            # 转换性别格式：male -> 男, female -> 女
            gender_cn = "男" if gender == "male" else "女"

            # 转换历法格式：solar -> gregorian, lunar -> lunar
            calendar = "gregorian" if calendar_type == "solar" else "lunar"

            # 构造排盘请求
            paipan_request = PaipanIn(
                gender=gender_cn,
                calendar=calendar,
                birth_date=birth_date.strftime("%Y-%m-%d"),
                birth_time=birth_time.strftime("%H:%M"),
                birthplace=birth_location,
                use_true_solar=True,  # 启用真太阳时
                lng=birth_longitude,
                lat=birth_latitude,
            )

            # 调用排盘函数
            result = calc_bazi(paipan_request)

            # 检查是否有错误
            if "error" in result:
                return {
                    "error": result["error"],
                    "status": "failed",
                    "message": "命盘计算失败，请检查出生信息是否正确"
                }

            return result

        except Exception as e:
            # 如果计算失败，返回错误信息
            return {
                "error": str(e),
                "status": "failed",
                "message": "命盘计算失败，请检查出生信息是否正确"
            }
