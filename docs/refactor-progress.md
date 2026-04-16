# 用户档案系统重构 - 进度报告

**分支**: `feature/user-profile-system`  
**开始日期**: 2026-04-16  
**当前状态**: 阶段 1 完成 80%

---

## 已完成工作

### ✅ 数据库层（100%）

**提交**: `0f2c3c8` - "feat: add UserProfile model and database schema"

1. **数据库设计**
   - ✅ 创建 `user_profiles` 表（11 个字段）
   - ✅ 修改 `conversations` 表（新增 `profile_id` 外键）
   - ✅ 编写原生 SQL 迁移脚本
   - ✅ 编写回滚脚本

2. **SQLAlchemy 模型**
   - ✅ `UserProfile` 模型（`app/models/profile.py`）
   - ✅ `User.profile` 一对一关系
   - ✅ `Conversation.profile_id` 外键
   - ✅ 便捷属性：`display_info`, `birth_datetime_str`

3. **文档**
   - ✅ 迁移执行指南（`migrations/README.md`）

**文件清单**：
```
migrations/001_add_user_profiles.sql
migrations/001_rollback_user_profiles.sql
migrations/README.md
app/models/profile.py
app/models/user.py (修改)
app/models/chat.py (修改)
app/models/__init__.py (修改)
```

---

### ✅ API 层（100%）

**提交**: `fe2bd0b` - "feat: implement profile API endpoints"

1. **Pydantic Schemas**
   - ✅ `ProfileCreateRequest` - 创建档案请求
   - ✅ `ProfileUpdateRequest` - 更新档案请求
   - ✅ `ProfileResponse` - 完整档案响应
   - ✅ `ProfileBriefResponse` - 简要信息响应

2. **Service 层**
   - ✅ `ProfileService.get_user_profile()` - 查询档案
   - ✅ `ProfileService.create_profile()` - 创建档案 + 计算命盘
   - ✅ `ProfileService.update_profile()` - 更新档案 + 自动重算
   - ✅ `ProfileService.delete_profile()` - 删除档案
   - ✅ `ProfileService._calculate_bazi_chart()` - 命盘计算（集成现有逻辑）

3. **Router 层**
   - ✅ `GET /api/profile/me` - 获取当前用户档案
   - ✅ `GET /api/profile/me/brief` - 获取简要信息
   - ✅ `POST /api/profile/create` - 创建档案
   - ✅ `PUT /api/profile/update` - 更新档案
   - ✅ `DELETE /api/profile/delete` - 删除档案

4. **集成**
   - ✅ 注册 profile router 到 `main.py`
   - ✅ 集成现有 `calc_bazi` 函数

5. **文档**
   - ✅ API 测试指南（`docs/profile-api-testing.md`）

**文件清单**：
```
app/schemas/profile.py
app/services/profile_service.py
app/routers/profile.py
main.py (修改)
docs/profile-api-testing.md
```

---

## 待完成工作

### 🔄 阶段 1 剩余任务（20%）

#### 1. 修改聊天 API 绑定 profile_id

**目标**：新会话自动绑定用户档案

**需要修改的文件**：
- `app/routers/chat.py` - `/api/chat/start` 端点
- `app/chat/service.py` - 会话创建逻辑

**实现要点**：
```python
# 伪代码
def start_chat(user_id, ...):
    # 1. 查询用户档案
    profile = ProfileService.get_user_profile(db, user_id)
    if not profile:
        raise HTTPException(400, "请先创建命盘档案")
    
    # 2. 创建会话时绑定 profile_id
    conversation = Conversation(
        user_id=user_id,
        profile_id=profile.id,  # 新增
        title="..."
    )
    
    # 3. 从 profile.bazi_chart 读取命盘数据（而非临时计算）
    bazi_data = profile.bazi_chart
```

**预计工作量**：0.5 天

---

#### 2. 更新 `/api/auth/me` 端点

**目标**：返回用户信息时包含档案状态

**需要修改的文件**：
- `app/routers/users.py` - `/api/auth/me` 端点
- `app/schemas/user.py` - 响应模型

**实现要点**：
```python
# 响应示例
{
  "id": 1,
  "email": "test@example.com",
  "has_profile": true,  # 新增：是否已建档
  "profile_brief": {    # 新增：档案简要信息（可选）
    "gender": "male",
    "birth_location": "深圳"
  }
}
```

**预计工作量**：0.5 天

---

### 📋 阶段 2：前端开发（未开始）

根据 `refactor-timeline.md`，前端需要：

1. **状态机路由守卫**（1 天）
   - 检查登录态 + 建档态
   - 自动重定向到正确页面

2. **首次建档页**（1 天）
   - 表单组件（性别、日期、时间、地点）
   - 调用 `POST /api/profile/create`
   - 成功后跳转聊天页

3. **聊天页改造**（0.5 天）
   - 顶部显示当前命盘（调用 `GET /api/profile/me/brief`）
   - 点击可查看详情或修改

4. **未登录落地页**（1 天）
   - Hero 区域 + CTA 按钮
   - 点击触发登录

5. **查看命盘页**（1 天）
   - 展示完整命盘信息
   - 调用 `GET /api/profile/me`

6. **修改资料页**（1 天）
   - 表单回填现有数据
   - 调用 `PUT /api/profile/update`
   - 提示"命盘已更新"

**预计总工作量**：5.5 天

---

## 技术债务

完成本次重构后，以下功能可作为后续迭代：

- [ ] 多档案管理（切换/新增档案）
- [ ] 合盘功能（两人命盘对比）
- [ ] 城市搜索组件（出生地点自动补全）
- [ ] 时间校准高级模式
- [ ] 命盘分享功能
- [ ] 档案导入/导出

---

## 测试清单

### 后端测试（待执行）

- [ ] 数据库迁移成功执行
- [ ] 表结构符合预期
- [ ] 外键约束正常工作
- [ ] SQLAlchemy 模型可以正常导入
- [ ] 可以创建 UserProfile 记录
- [ ] User.profile 关系查询正常
- [ ] Conversation.profile_id 可以正常设置
- [ ] API 端点全部可访问
- [ ] 创建档案并计算命盘成功
- [ ] 更新档案自动重算命盘
- [ ] 删除档案后会话 profile_id 变为 NULL
- [ ] 重复创建档案返回 400 错误

### 前端测试（待开发）

- [ ] 未登录用户访问聊天页自动跳转落地页
- [ ] 已登录未建档用户自动跳转建档页
- [ ] 已登录已建档用户直接进入聊天页
- [ ] 建档表单验证正常
- [ ] 建档成功后自动跳转聊天页
- [ ] 聊天页顶部正确显示命盘信息
- [ ] 修改资料后命盘自动更新
- [ ] 响应式布局在移动端正常显示

---

## 风险与注意事项

### 数据迁移风险

⚠️ **老用户数据处理**：
- 现有用户的历史会话 `profile_id` 为 NULL（正常）
- 首次登录后需引导建档
- 建档完成后，新会话自动绑定档案
- 历史会话可选择性关联到新档案（手动操作）

### API 兼容性

⚠️ **破坏性变更**：
- `/api/chat/start` 将要求用户必须有档案
- 前端需要先检查 `has_profile`，无档案时引导建档
- 建议灰度发布，先在测试环境验证

### 性能考虑

⚠️ **命盘计算性能**：
- 每次创建/更新档案都会计算命盘（耗时约 100-500ms）
- 建议前端防抖，避免用户频繁修改
- 后续可考虑缓存机制

---

## 下一步行动

### 立即执行（本周）

1. **执行数据库迁移**
   ```bash
   mysql -u root -p fate < migrations/001_add_user_profiles.sql
   ```

2. **测试 API 端点**
   - 按照 `docs/profile-api-testing.md` 执行测试
   - 验证所有端点正常工作

3. **修改聊天 API**
   - 完成阶段 1 剩余 20% 工作
   - 确保新会话自动绑定 profile_id

### 后续计划（下周）

4. **前端开发**
   - 切换到前端分支
   - 按照 `docs/function_upgrade.md` 实现页面

5. **联调测试**
   - 端到端流程测试
   - 修复发现的问题

6. **灰度发布**
   - 10% 用户 → 50% 用户 → 100% 用户
   - 监控关键指标（建档成功率、命盘计算耗时）

---

## 总结

**当前进度**：阶段 1 完成 80%（数据库 + API 层已完成）

**剩余工作**：
- 后端：0.5-1 天（修改聊天 API）
- 前端：5.5 天（6 个页面 + 状态机）
- 测试：1 天（联调 + 修复）

**预计完成时间**：7-8 天（单人全职）

**关键里程碑**：
- ✅ 数据库设计完成
- ✅ API 端点实现完成
- 🔄 聊天 API 集成（进行中）
- ⏳ 前端开发（待开始）
- ⏳ 联调测试（待开始）
